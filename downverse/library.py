"""Histórico dos downloads concluídos (evita baixar de novo e alimenta a Biblioteca)."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .settings import config_dir


class Library:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config_dir() / "library.json"
        self._lock = threading.RLock()
        self._items: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._items, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- consulta ---------------------------------------------------------------
    def get(self, live_id: str) -> dict | None:
        with self._lock:
            item = self._items.get(live_id)
            return dict(item) if item else None

    def has_video(self, live_id: str) -> bool:
        item = self.get(live_id)
        return bool(item and item.get("video") and Path(item["video"]).is_file())

    def all(self) -> list[dict]:
        with self._lock:
            items = [dict(v, id=k) for k, v in self._items.items()]
        items.sort(key=lambda i: i.get("downloaded_at", ""), reverse=True)
        return items

    def owner_of_folder(self, folder: Path) -> str | None:
        """ID da live que já usa essa pasta (ou None)."""
        target = os.path.normcase(os.path.abspath(folder))
        with self._lock:
            for live_id, item in self._items.items():
                if item.get("dir") and os.path.normcase(os.path.abspath(item["dir"])) == target:
                    return live_id
        return None

    # -- alteração --------------------------------------------------------------
    def add(self, live_id: str, entry: dict) -> None:
        entry = dict(entry)
        entry["downloaded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._items[live_id] = entry
            self._save()

    def remove(self, live_id: str) -> bool:
        with self._lock:
            if live_id in self._items:
                del self._items[live_id]
                self._save()
                return True
        return False
