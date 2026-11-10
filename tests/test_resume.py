"""Reconhecer o que já está no disco e retomar downloads interrompidos."""
import json

import pytest

from downverse.engine import AlreadyDownloaded, DownloadCallbacks, DownverseError, download_options_from_settings
from downverse.library import Library
from downverse.manager import DownloadManager

from . import fake_weverse as fw

MEMBER = "https://weverse.io/lesserafim/live/2-100000003"
VIDEO = "LE SSERAFIM/채원/2026-03-15/Live de domingo 💜.mp4"


def opts(core, **kw):
    return download_options_from_settings(core.settings.get()) | kw


def files(core):
    return sorted(str(p.relative_to(core.root)).replace("\\", "/") for p in core.root.rglob("*") if p.is_file())


class FailAfter(DownloadCallbacks):
    """Simula a internet caindo no meio do vídeo."""

    def __init__(self, limit):
        self.limit = limit

    def progress(self, pct, speed, eta, downloaded, total):
        if downloaded and downloaded >= self.limit and pct < 100:
            raise OSError("conexão perdida")


# ------------------------------------------------------------------ já está no disco?

def test_recognizes_video_on_disk_when_history_is_lost(core, fake):
    core.engine.download(MEMBER, opts(core), DownloadCallbacks())
    before = files(core)
    core.library.remove("2-100000003")                      # histórico apagado / programa reinstalado
    assert not core.library.has_video("2-100000003")

    with pytest.raises(AlreadyDownloaded, match="Já estava na pasta"):
        core.engine.download(MEMBER, opts(core), DownloadCallbacks())
    assert files(core) == before                            # nada duplicado em "2026-03-15 (2)"
    entry = core.library.get("2-100000003")                 # e a live volta para a biblioteca
    assert entry["video"].endswith("Live de domingo 💜.mp4") and entry["thumbnail"] and len(entry["subtitles"]) == 3


def test_overwrite_still_downloads_again(core, fake):
    core.engine.download(MEMBER, opts(core), DownloadCallbacks())
    core.library.remove("2-100000003")
    core.engine.download(MEMBER, opts(core, overwrite=True), DownloadCallbacks())
    assert VIDEO in files(core) and not any("(2)" in f for f in files(core))


def test_folder_of_another_live_is_not_mistaken(core, fake):
    """Duas lives no mesmo dia: a segunda não é dada como baixada por causa da primeira."""
    core.engine.download(MEMBER, opts(core), DownloadCallbacks())
    core.library.add("2-100000003", {"dir": str(core.root / "LE SSERAFIM/채원/2026-03-15"),
                                      "video": str(core.root / VIDEO)})
    core.engine.download("https://weverse.io/lesserafim/live/2-100000004", opts(core), DownloadCallbacks())
    assert any(f.startswith("LE SSERAFIM/채원/2026-03-15 (2)/") and f.endswith(".mp4") for f in files(core))


# ------------------------------------------------------------------ retomar de onde parou

def test_failed_download_keeps_partial_and_retry_resumes(core, fake, media, monkeypatch):
    monkeypatch.setattr(fw._QuietHandler, "throttle", 0.001)
    fw._QuietHandler.ranges.clear()
    with pytest.raises(DownverseError):
        core.engine.download(MEMBER, opts(core, subtitles=False, thumbnail=False), FailAfter(20_000))
    partial = [f for f in files(core) if f.endswith(".part")]
    assert partial, files(core)                             # o pedaço baixado fica guardado
    size = (core.root / partial[0]).stat().st_size
    assert size >= 20_000

    monkeypatch.setattr(fw._QuietHandler, "throttle", 0.0)
    result = core.engine.download(MEMBER, opts(core, subtitles=False, thumbnail=False), DownloadCallbacks())
    assert files(core) == [VIDEO]
    assert any(int(r.split("=")[1].split("-")[0]) >= 20_000 for r in fw._QuietHandler.ranges), fw._QuietHandler.ranges
    assert result["size"] == (media.root / "vod_720.mp4").stat().st_size   # arquivo final íntegro


def test_cancel_still_removes_partial_files(core, fake, monkeypatch):
    from yt_dlp.utils import DownloadCancelled

    monkeypatch.setattr(fw._QuietHandler, "throttle", 0.001)

    class Cancel(DownloadCallbacks):
        seen = 0

        def progress(self, pct, speed, eta, downloaded, total):
            Cancel.seen = downloaded

        def is_cancelled(self):
            return Cancel.seen > 10_000

    with pytest.raises(DownloadCancelled):
        core.engine.download(MEMBER, opts(core), Cancel())
    assert not [f for f in files(core) if ".part" in f]


# ------------------------------------------------------------------ fila sobrevive ao fechamento

def test_queue_is_saved_and_restored(core, fake, home, monkeypatch):
    state = home / "cfg" / "queue.json"
    monkeypatch.setattr(fw._QuietHandler, "throttle", 0.02)   # lento: o "programa fecha" no meio
    first = DownloadManager(core.settings, core.library, core.engine, state_path=state)
    first.add([{"id": "2-100000003", "url": MEMBER, "title": "Live de domingo"},
               {"id": "2-100000001", "url": "https://weverse.io/taeyeon/live/2-100000001", "title": "Hello"}],
              opts(core, quality="360", subtitles=False))
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert [e["id"] for e in saved] == ["2-100000003", "2-100000001"] and saved[0]["options"]["quality"] == "360"
    first.cancel_all = None                                    # (o processo "morreu": nada mais roda nele)
    for item in list(first._items.values()):
        item.cancel.set()                                      # só para as threads de teste pararem
    first.state_path = None
    first.wait_idle(30)

    monkeypatch.setattr(fw._QuietHandler, "throttle", 0.0)
    second = DownloadManager(core.settings, Library(), core.engine, state_path=state)   # programa aberto de novo
    assert second.restore() == 2 and second.snapshot()["restored"] == 2
    assert second.wait_idle(60)
    snap = second.snapshot()
    assert snap["counts"]["done"] == 2, snap["items"]
    assert all(i["quality"] == "360" for i in snap["items"])  # volta com as opções escolhidas na hora
    assert json.loads(state.read_text(encoding="utf-8")) == []


def test_finished_and_canceled_items_are_not_restored(core, fake, home):
    state = home / "cfg" / "queue.json"
    manager = DownloadManager(core.settings, core.library, core.engine, state_path=state)
    manager.add([{"id": "2-100000001", "url": "https://weverse.io/taeyeon/live/2-100000001", "title": "Hello"}], opts(core))
    assert manager.wait_idle(60)
    assert json.loads(state.read_text(encoding="utf-8")) == []
    again = DownloadManager(core.settings, core.library, core.engine, state_path=state)
    assert again.restore() == 0


def test_restore_ignores_garbage(core, home):
    state = home / "cfg" / "queue.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{nada", encoding="utf-8")
    manager = DownloadManager(core.settings, core.library, core.engine, state_path=state)
    assert manager.restore() == 0
    state.write_text(json.dumps([{"url": "https://evil.example/x"}, 7, {"url": "file:///etc/passwd"}]), encoding="utf-8")
    assert manager.restore() == 0
