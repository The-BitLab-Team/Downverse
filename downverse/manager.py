"""Fila de downloads e análise de canais (rodam em threads)."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from yt_dlp.utils import DownloadCancelled

from .engine import (
    LIBRARY_FIELDS, download_options_from_settings,
    AlreadyDownloaded, DownloadCallbacks, DownverseError, Engine, friendly_error,
)
from .library import Library
from .links import WeverseLink
from .paths import LiveMeta, folder_date
from .settings import SettingsStore

ACTIVE = ("queued", "downloading")
FINISHED = ("done", "error", "canceled", "skipped")


@dataclass
class Item:
    id: str
    url: str
    live_id: str
    title: str
    options: dict
    uploader: str = ""
    community: str = ""
    timestamp: int | None = None
    thumbnail: str = ""
    status: str = "queued"          # queued | downloading | done | error | canceled | skipped
    phase: str = "Na fila"
    progress: float = 0.0
    speed: float | None = None
    eta: float | None = None
    downloaded: int = 0
    total: int | None = None
    error: str = ""
    warnings: list = field(default_factory=list)
    result: dict | None = None
    dir: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "live_id": self.live_id,
            "title": self.title,
            "uploader": self.uploader,
            "community": self.community,
            "date": folder_date(self.timestamp, self.options.get("date_timezone", "local")) if self.timestamp else "",
            "thumbnail": self.thumbnail,
            "status": self.status,
            "phase": self.phase,
            "progress": round(self.progress, 1),
            "speed": self.speed,
            "eta": self.eta,
            "downloaded": self.downloaded,
            "total": self.total,
            "error": self.error,
            "warnings": list(self.warnings),
            "dir": self.dir,
            "quality": self.options.get("quality"),
            "size": (self.result or {}).get("size"),
            "local_thumb": bool((self.result or {}).get("thumbnail")),
        }


class DownloadManager:
    MAX_WORKERS = 4

    def __init__(self, settings: SettingsStore, library: Library, engine: Engine,
                 state_path: Path | None = None):
        self.settings = settings
        self.library = library
        self.engine = engine
        self.state_path = state_path     # onde a fila pendente fica salva (None = não salva)
        self.restored = 0                # quantos downloads voltaram para a fila ao abrir
        self._persist_lock = threading.Lock()
        self._items: dict[str, Item] = {}
        self._lock = threading.RLock()
        self._cv = threading.Condition()
        self._pending: list[str] = []
        self._running = 0
        self._session_bytes = 0
        self._started = False

    # -- worker -------------------------------------------------------------------
    def _ensure_workers(self) -> None:
        if self._started:
            return
        self._started = True
        for n in range(self.MAX_WORKERS):
            threading.Thread(target=self._worker, name=f"downverse-worker-{n}", daemon=True).start()

    def _limit(self) -> int:
        return self.settings.get()["concurrent_downloads"]

    def _next_item(self) -> Item | None:
        with self._cv:
            while True:
                if self._running < self._limit():
                    while self._pending:
                        item = self._items.get(self._pending.pop(0))
                        if item and item.status == "queued":
                            self._running += 1
                            return item
                self._cv.wait(timeout=0.5)

    def _worker(self) -> None:
        while True:
            item = self._next_item()
            try:
                self._run(item)
            except Exception as exc:  # nunca derruba a thread
                item.status, item.error = "error", friendly_error(exc)
                item.finished_at = time.time()
            finally:
                with self._cv:
                    self._running -= 1
                    self._cv.notify_all()

    def _run(self, item: Item) -> None:
        item.status, item.phase = "downloading", "Começando…"
        manager = self

        class Cb(DownloadCallbacks):
            def phase(self, text: str) -> None:
                item.phase = text

            def meta(self, meta: LiveMeta, info: dict) -> None:
                item.title = meta.title or item.title
                item.community = meta.community or item.community
                item.uploader = meta.uploader or item.uploader
                item.timestamp = meta.timestamp or item.timestamp
                item.thumbnail = info.get("thumbnail") or item.thumbnail
                item.live_id = meta.live_id or item.live_id

            def dest(self, path: Path) -> None:
                item.dir = str(path)

            def progress(self, pct, speed, eta, downloaded, total) -> None:
                item.progress, item.speed, item.eta = pct, speed, eta
                item.downloaded, item.total = downloaded, total

            def is_cancelled(self) -> bool:
                return item.cancel.is_set()

        try:
            if item.cancel.is_set():
                raise DownloadCancelled()
            result = self.engine.download(item.url, item.options, Cb())
        except DownloadCancelled:
            item.status, item.phase, item.error = "canceled", "Cancelado", ""
        except AlreadyDownloaded as exc:
            item.status, item.phase, item.error = "skipped", "Já baixada", str(exc)
            existing = self.library.get(item.live_id) or {}
            item.result = existing
            item.dir = existing.get("dir", item.dir)
        except DownverseError as exc:
            item.status, item.phase, item.error = "error", "Falhou", str(exc)
        else:
            item.result = result
            item.warnings = result.get("warnings", [])
            item.dir = result["dir"]
            item.progress, item.status, item.phase, item.speed, item.eta = 100.0, "done", "Concluído", None, None
            with self._lock:
                self._session_bytes += result.get("size") or 0
            self.library.add(result["id"], {k: result[k] for k in LIBRARY_FIELDS})
        item.finished_at = time.time()
        self._persist()

    # -- fila salva em disco ----------------------------------------------------------
    def _persist(self) -> None:
        """Grava o que ainda falta baixar. Se o programa fechar no meio, ``restore`` traz de volta."""
        if not self.state_path:
            return
        with self._lock:
            pending = [{
                "id": i.live_id, "url": i.url, "title": i.title, "uploader": i.uploader, "community": i.community,
                "timestamp": i.timestamp, "thumbnail": i.thumbnail, "options": i.options,
            } for i in self._items.values() if i.status in ACTIVE and not i.cancel.is_set()]
        with self._persist_lock:
            try:
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.state_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, self.state_path)
            except OSError:
                pass

    def restore(self) -> int:
        """Recoloca na fila os downloads que estavam pendentes quando o programa fechou."""
        if not self.state_path:
            return 0
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        defaults = download_options_from_settings(self.settings.get())
        count = 0
        for entry in saved if isinstance(saved, list) else []:
            if not isinstance(entry, dict) or not str(entry.get("url", "")).startswith("https://weverse.io/"):
                continue
            options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
            count += len(self.add([entry], {**defaults, **{k: v for k, v in options.items() if k in defaults}}))
        self.restored = count
        return count

    # -- API ----------------------------------------------------------------------
    def add(self, entries: list[dict], options: dict) -> list[str]:
        """Põe lives na fila (mais antigas primeiro, para as pastas do mesmo dia saírem em ordem)."""
        self._ensure_workers()
        ids: list[str] = []
        entries = sorted(entries, key=lambda e: e.get("timestamp") or 0)
        with self._lock:
            busy = {i.live_id for i in self._items.values() if i.status in ACTIVE}
            for e in entries:
                live_id = str(e.get("id") or "")
                if live_id and live_id in busy:
                    continue
                item = Item(
                    id=uuid.uuid4().hex[:12], url=e["url"], live_id=live_id,
                    title=e.get("title") or (f"Live {live_id}" if live_id else "Live"),
                    options=dict(options), uploader=e.get("uploader") or "",
                    community=e.get("community") or "", timestamp=e.get("timestamp"),
                    thumbnail=e.get("thumbnail") or "",
                )
                self._items[item.id] = item
                busy.add(live_id)
                ids.append(item.id)
        with self._cv:
            self._pending.extend(ids)
            self._cv.notify_all()
        self._persist()
        return ids

    def snapshot(self) -> dict:
        with self._lock:
            items = [i.to_dict() for i in self._items.values()]
            counts = {s: 0 for s in ("queued", "downloading", "done", "error", "canceled", "skipped")}
            for i in self._items.values():
                counts[i.status] += 1
            session_bytes = self._session_bytes
        return {"items": items, "counts": counts, "session_bytes": session_bytes, "restored": self.restored}

    def cancel(self, item_id: str) -> bool:
        with self._lock:
            item = self._items.get(item_id)
            if not item or item.status not in ACTIVE:
                return False
            item.cancel.set()
            if item.status == "queued":
                item.status, item.phase, item.finished_at = "canceled", "Cancelado", time.time()
        with self._cv:
            self._cv.notify_all()
        self._persist()
        return True

    def cancel_all(self) -> int:
        with self._lock:
            ids = [i.id for i in self._items.values() if i.status in ACTIVE]
        return sum(1 for i in ids if self.cancel(i))

    def retry(self, item_id: str, force: bool = False) -> bool:
        with self._lock:
            item = self._items.get(item_id)
            if not item or item.status not in ("error", "canceled", "skipped"):
                return False
            item.options = dict(item.options, overwrite=item.options.get("overwrite") or force)
            item.status, item.phase, item.error, item.progress = "queued", "Na fila", "", 0.0
            item.speed = item.eta = None
            item.cancel = threading.Event()
            item.finished_at = None
        self._ensure_workers()
        with self._cv:
            self._pending.append(item_id)
            self._cv.notify_all()
        self._persist()
        return True

    def clear_finished(self) -> int:
        with self._lock:
            done = [k for k, i in self._items.items() if i.status in FINISHED]
            for k in done:
                del self._items[k]
        return len(done)

    def get_dir(self, item_id: str) -> str | None:
        with self._lock:
            item = self._items.get(item_id)
            return item.dir if item and item.dir else None

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Usado em testes e na linha de comando: espera a fila esvaziar."""
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                if not any(i.status in ACTIVE for i in self._items.values()):
                    return True
            time.sleep(0.05)
        return False


# ---------------------------------------------------------------------------
# Análise de canal (listar todas as lives antes de baixar)
# ---------------------------------------------------------------------------

_STATUS_MAP = {
    "was_live": "vod",
    "not_live": "vod",
    "is_live": "live",
    "is_upcoming": "upcoming",
    "post_live": "processing",
}


def normalize_entry(entry: dict, community: str, slug: str, tz_mode: str, library: Library) -> dict:
    """Entrada crua do yt-dlp -> dicionário simples para a interface."""
    live_id = str(entry.get("id") or "")
    status = _STATUS_MAP.get(entry.get("live_status") or "", "vod")
    ts = entry.get("release_timestamp") or entry.get("timestamp")
    creators = entry.get("creators") or []
    return {
        "id": live_id,
        "url": entry.get("url") or f"https://weverse.io/{slug}/live/{live_id}",
        "title": (entry.get("title") or "").strip() or f"Live {live_id}",
        "uploader": (entry.get("uploader") or "").strip(),
        "community": (creators[0] if creators else "") or community,
        "timestamp": ts,
        "date": folder_date(ts, tz_mode) if ts else "",
        "duration": entry.get("duration"),
        "thumbnail": entry.get("thumbnail") or "",
        "status": status,
        "downloadable": status == "vod",
        "availability": entry.get("availability") or "",
        "in_library": library.has_video(live_id),
    }


@dataclass
class Analysis:
    id: str
    url: str
    status: str = "running"          # running | done | error | canceled
    error: str = ""
    channel: dict = field(default_factory=dict)
    entries: list = field(default_factory=list)
    stop: threading.Event = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.time)


class AnalysisManager:
    KEEP = 5

    def __init__(self, settings: SettingsStore, library: Library, engine: Engine):
        self.settings, self.library, self.engine = settings, library, engine
        self._items: dict[str, Analysis] = {}
        self._lock = threading.RLock()

    def start(self, link: WeverseLink) -> str:
        analysis = Analysis(id=uuid.uuid4().hex[:12], url=link.url,
                            channel={"slug": link.community, "name": "", "thumbnail": ""})
        with self._lock:
            for old in list(self._items.values()):
                old.stop.set()
            self._items[analysis.id] = analysis
            while len(self._items) > self.KEEP:
                self._items.pop(next(iter(self._items)))
        threading.Thread(target=self._run, args=(analysis,), name="downverse-analysis", daemon=True).start()
        return analysis.id

    def _run(self, a: Analysis) -> None:
        tz_mode = self.settings.get()["date_timezone"]
        try:
            info, entries = self.engine.list_channel(a.url, a.stop.is_set)
            name = info.get("title") or a.channel["slug"]
            with self._lock:
                a.channel.update(name=name, thumbnail=info.get("thumbnail") or "")
            for raw in entries:
                row = normalize_entry(raw, name, a.channel["slug"], tz_mode, self.library)
                with self._lock:
                    a.entries.append(row)
            with self._lock:
                a.status = "canceled" if a.stop.is_set() else "done"
        except DownverseError as exc:
            with self._lock:
                a.status, a.error = "error", str(exc)
        except Exception as exc:
            with self._lock:
                a.status, a.error = "error", friendly_error(exc)

    def get(self, analysis_id: str, since: int = 0) -> dict | None:
        with self._lock:
            a = self._items.get(analysis_id)
            if not a:
                return None
            # reavalia "já baixada" a cada consulta (o usuário pode ter baixado enquanto olhava)
            new = [dict(e, in_library=self.library.has_video(e["id"])) for e in a.entries[since:]]
            return {
                "id": a.id, "status": a.status, "error": a.error, "channel": dict(a.channel),
                "total": len(a.entries), "since": since, "entries": new,
            }

    def cancel(self, analysis_id: str) -> None:
        with self._lock:
            a = self._items.get(analysis_id)
            if a:
                a.stop.set()

    def entries_by_ids(self, analysis_id: str, ids: list[str]) -> list[dict]:
        wanted = set(ids)
        with self._lock:
            a = self._items.get(analysis_id)
            return [dict(e) for e in (a.entries if a else []) if e["id"] in wanted and e["downloadable"]]
