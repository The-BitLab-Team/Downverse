"""Fluxo completo com o extrator real do yt-dlp falando com um Weverse simulado."""
import pytest
from yt_dlp.utils import DownloadCancelled

from downverse.engine import AlreadyDownloaded, DownloadCallbacks, DownverseError, download_options_from_settings
from downverse.links import parse_link


class Quiet(DownloadCallbacks):
    pass


def run(core, url, **overrides):
    opts = download_options_from_settings(core.settings.get()) | overrides
    return core.engine.download(url, opts, Quiet())


def rel(core, path):
    return str(path.relative_to(core.root)).replace("\\", "/") if hasattr(path, "relative_to") else path


def tree(core):
    return sorted(str(p.relative_to(core.root)).replace("\\", "/") for p in core.root.rglob("*") if p.is_file())


def test_member_live_full_layout(core, fake):
    res = run(core, "https://weverse.io/lesserafim/live/2-100000003")
    base = "LE SSERAFIM/채원/2026-03-15"
    assert tree(core) == [
        f"{base}/Legendas/Live de domingo 💜.en_US.srt",
        f"{base}/Legendas/Live de domingo 💜.ko_KR.srt",
        f"{base}/Legendas/Live de domingo 💜.pt_BR.srt",
        f"{base}/Live de domingo 💜.jpg",
        f"{base}/Live de domingo 💜.mp4",
    ]
    assert res["height"] == 720                      # "melhor qualidade" = maior altura
    srt = (core.root / base / "Legendas" / "Live de domingo 💜.pt_BR.srt").read_text(encoding="utf-8")
    assert "Legenda pt_BR" in srt and "-->" in srt and "," in srt.split("-->")[0]   # formato SRT
    assert not res["warnings"]


def test_official_group_live_has_no_member_folder(core, fake):
    run(core, "https://weverse.io/lesserafim/live/2-100000002")
    assert all(p.startswith("LE SSERAFIM/2026-03-10/") for p in tree(core))


def test_solo_artist_and_title_sanitizing(core, fake):
    run(core, "https://weverse.io/taeyeon/live/2-100000001")
    assert "TAEYEON/2026-01-02/Hello Olá 안녕.mp4" in tree(core)


@pytest.mark.parametrize("quality,height", [("720", 720), ("360", 360), ("144", 144), ("worst", 144), ("best", 720)])
def test_quality_selection(core, fake, quality, height):
    assert run(core, "https://weverse.io/taeyeon/live/2-100000001", quality=quality)["height"] == height


def test_subtitle_language_filter_and_vtt(core, fake):
    run(core, "https://weverse.io/lesserafim/live/2-100000003", subtitle_langs=["pt", "ko"], subtitle_format="vtt")
    subs = [p for p in tree(core) if "/Legendas/" in p]
    assert [s.rsplit(".", 2)[1:] for s in subs] == [["ko_KR", "vtt"], ["pt_BR", "vtt"]]


def test_subtitles_and_thumbnail_can_be_disabled(core, fake):
    run(core, "https://weverse.io/lesserafim/live/2-100000003", subtitles=False, thumbnail=False)
    assert tree(core) == ["LE SSERAFIM/채원/2026-03-15/Live de domingo 💜.mp4"]


def test_missing_subtitle_language_is_only_a_warning(core, fake):
    res = run(core, "https://weverse.io/lesserafim/live/2-100000004", subtitle_langs=["pt"])
    assert any("legendas" in w.lower() for w in res["warnings"])
    assert not [p for p in tree(core) if "Legendas" in p]


def test_custom_subtitles_folder_name(core, fake):
    run(core, "https://weverse.io/taeyeon/live/2-100000001", subtitles_dir_name="Subs")
    assert any("/Subs/" in p for p in tree(core))


def test_same_day_lives_do_not_mix(core, fake):
    a = run(core, "https://weverse.io/lesserafim/live/2-100000003")
    b = run(core, "https://weverse.io/lesserafim/live/2-100000004")
    assert a["dir"].endswith("2026-03-15") and b["dir"].endswith("2026-03-15 (2)")


def test_batch_from_manager_registers_library_and_skips_duplicates(core, fake):
    entry = {"id": "2-100000001", "url": "https://weverse.io/taeyeon/live/2-100000001", "title": "x"}
    opts = download_options_from_settings(core.settings.get())
    core.downloads.add([entry], opts)
    assert core.downloads.wait_idle(60)
    snap = core.downloads.snapshot()
    assert snap["counts"]["done"] == 1
    assert core.library.has_video("2-100000001")
    assert snap["items"][0]["title"] == "Hello / Olá: 안녕?"      # título real da live
    assert snap["items"][0]["progress"] == 100

    core.downloads.add([entry], opts)
    assert core.downloads.wait_idle(60)
    assert core.downloads.snapshot()["counts"]["skipped"] == 1

    item = [i for i in core.downloads.snapshot()["items"] if i["status"] == "skipped"][0]
    assert core.downloads.retry(item["id"], force=True)
    assert core.downloads.wait_idle(60)
    assert core.downloads.snapshot()["counts"]["done"] == 2


def test_drm_content_is_refused_and_leaves_nothing_behind(core, fake):
    with pytest.raises(DownverseError) as exc:
        run(core, "https://weverse.io/taeyeon/live/2-100000009")
    assert "DRM" in str(exc.value)
    assert not core.root.exists() or tree(core) == []


def test_cancel_cleans_up(core, fake):
    class Cancel(DownloadCallbacks):
        def meta(self, meta, info):
            self.flag = True

        def is_cancelled(self):
            return getattr(self, "flag", False)

    opts = download_options_from_settings(core.settings.get())
    with pytest.raises(DownloadCancelled):
        core.engine.download("https://weverse.io/taeyeon/live/2-100000001", opts, Cancel())
    assert not core.root.exists() or tree(core) == []


def test_unknown_channel_gives_readable_error(core, fake):
    import time
    analysis_id = core.analyses.start(parse_link("https://weverse.io/naoexiste"))
    for _ in range(100):
        data = core.analyses.get(analysis_id)
        if data["status"] != "running":
            break
        time.sleep(0.05)
    assert data["status"] == "error" and data["error"]


def test_single_live_link_ignores_a_wrong_channel_name_in_the_url(core, fake):
    res = run(core, "https://weverse.io/qualquercoisa/live/2-100000001")
    assert res["community"] == "TAEYEON"


def test_channel_listing_and_selection(core, fake):
    link = parse_link("https://weverse.io/lesserafim")             # página inicial do canal
    analysis_id = core.analyses.start(link)
    import time
    for _ in range(100):
        data = core.analyses.get(analysis_id)
        if data["status"] != "running":
            break
        time.sleep(0.05)
    assert data["status"] == "done" and data["total"] == 4          # 2 páginas da API
    assert data["channel"]["name"] == "LE SSERAFIM"
    by_id = {e["id"]: e for e in data["entries"]}
    assert by_id["2-100000005"]["status"] == "live" and not by_id["2-100000005"]["downloadable"]
    assert by_id["2-100000003"]["date"] == "2026-03-15" and by_id["2-100000003"]["uploader"] == "채원"
    assert by_id["2-100000003"]["title"] == "Live de domingo 💜"

    # mesmo resultado se o usuário colar direto a página de lives
    other = core.analyses.start(parse_link("https://weverse.io/lesserafim/live/"))
    for _ in range(100):
        if core.analyses.get(other)["status"] != "running":
            break
        time.sleep(0.05)
    assert core.analyses.get(other)["total"] == 4

    wanted = core.analyses.entries_by_ids(analysis_id, ["2-100000003", "2-100000004", "2-100000005"])
    assert {e["id"] for e in wanted} == {"2-100000003", "2-100000004"}      # a ao vivo fica de fora
    opts = download_options_from_settings(core.settings.get())
    core.downloads.add(wanted, opts)
    assert core.downloads.wait_idle(60)
    folders = sorted(p.name for p in (core.root / "LE SSERAFIM" / "채원").iterdir())
    assert folders == ["2026-03-15", "2026-03-15 (2)"]               # a mais antiga ficou com a data "pura"
