"""Configurações persistentes (JSON na pasta de configuração do usuário)."""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
from pathlib import Path

from .auth import clean_path, clean_token
from .paths import DEFAULT_SUBTITLES_DIR, ROOT_FOLDER_NAME, default_videos_dir, sanitize_component

QUALITIES = ("best", "1080", "720", "480", "360", "worst")
BROWSERS = ("firefox", "chrome", "edge", "brave", "chromium", "opera", "vivaldi", "safari", "whale")
AUTH_METHODS = ("none", "browser", "file", "token")


def config_dir() -> Path:
    env = os.environ.get("DOWNVERSE_HOME")
    if env:
        path = Path(env).expanduser()
    elif os.name == "nt":
        path = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Downverse"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Downverse"
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "downverse"
    path.mkdir(parents=True, exist_ok=True)
    return path


DEFAULTS: dict = {
    "output_dir": "",              # vazio = pasta de Vídeos do sistema
    "quality": "best",             # best | 1080 | 720 | 480 | 360 | worst
    "subtitles": True,
    "subtitle_langs": [],          # vazio = todos os idiomas; ex.: ["pt", "en"]
    "subtitle_format": "srt",      # srt | vtt
    "fan_subtitles": False,
    "thumbnail": True,
    "subtitles_dir_name": DEFAULT_SUBTITLES_DIR,
    "artist_mode": "auto",         # auto | solo
    "date_timezone": "local",      # local | utc | kst
    "concurrent_downloads": 1,
    "overwrite": False,
    "theme": "light",              # light | dark
    "auth": {
        "method": "none",          # none | browser | file | token
        "browser": "firefox",
        "profile": "",
        "cookie_file": "",
        "refresh_token": "",
    },
}


def _pick(value, allowed, default):
    return value if value in allowed else default


def _clean_langs(value) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for v in value:
        code = str(v).strip().replace("-", "_")
        if code and code.replace("_", "").isalnum() and code not in out:
            out.append(code)
    return out[:20]


def normalize(raw: dict) -> dict:
    """Valida e completa um dicionário de configurações."""
    cfg = copy.deepcopy(DEFAULTS)
    raw = raw if isinstance(raw, dict) else {}

    cfg["output_dir"] = str(raw.get("output_dir") or "").strip()
    cfg["quality"] = _pick(str(raw.get("quality", "")), QUALITIES, "best")
    cfg["subtitles"] = bool(raw.get("subtitles", DEFAULTS["subtitles"]))
    cfg["subtitle_langs"] = _clean_langs(raw.get("subtitle_langs", []))
    cfg["subtitle_format"] = _pick(str(raw.get("subtitle_format", "")), ("srt", "vtt"), "srt")
    cfg["fan_subtitles"] = bool(raw.get("fan_subtitles", False))
    cfg["thumbnail"] = bool(raw.get("thumbnail", DEFAULTS["thumbnail"]))
    cfg["subtitles_dir_name"] = sanitize_component(
        str(raw.get("subtitles_dir_name") or ""), fallback=DEFAULT_SUBTITLES_DIR, max_chars=40)
    cfg["artist_mode"] = _pick(str(raw.get("artist_mode", "")), ("auto", "solo"), "auto")
    cfg["date_timezone"] = _pick(str(raw.get("date_timezone", "")), ("local", "utc", "kst"), "local")
    try:
        cfg["concurrent_downloads"] = max(1, min(4, int(raw.get("concurrent_downloads", 1))))
    except (TypeError, ValueError):
        cfg["concurrent_downloads"] = 1
    cfg["overwrite"] = bool(raw.get("overwrite", False))
    cfg["theme"] = _pick(str(raw.get("theme", "")), ("light", "dark"), "light")

    auth = raw.get("auth") if isinstance(raw.get("auth"), dict) else {}
    cfg["auth"] = {
        "method": _pick(str(auth.get("method", "")), AUTH_METHODS, "none"),
        "browser": _pick(str(auth.get("browser", "")), BROWSERS, "firefox"),
        "profile": str(auth.get("profile") or "").strip(),
        "cookie_file": clean_path(auth.get("cookie_file")),
        "refresh_token": clean_token(auth.get("refresh_token")),
    }
    return cfg


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config_dir() / "settings.json"
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            return normalize(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return normalize({})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)  # pode conter o token de acesso
        except OSError:
            pass
        os.replace(tmp, self.path)

    # -- leitura ----------------------------------------------------------------
    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def public(self) -> dict:
        """Versão para a interface: nunca inclui o token."""
        data = self.get()
        token = data["auth"].pop("refresh_token", "")
        data["auth"]["has_token"] = bool(token)
        return data

    def output_root(self) -> Path:
        """Pasta onde a pasta ``Weverse`` é criada."""
        custom = self.get()["output_dir"]
        return Path(custom).expanduser() if custom else default_videos_dir()

    def weverse_root(self) -> Path:
        return self.output_root() / ROOT_FOLDER_NAME

    # -- escrita ----------------------------------------------------------------
    def update(self, patch: dict) -> dict:
        """Aplica uma alteração parcial. ``auth.refresh_token`` ausente/None mantém o atual."""
        with self._lock:
            merged = copy.deepcopy(self._data)
            patch = dict(patch or {})
            auth_patch = patch.pop("auth", None)
            merged.update({k: v for k, v in patch.items() if k in DEFAULTS and k != "auth"})
            if isinstance(auth_patch, dict):
                auth = dict(merged["auth"])
                for key, value in auth_patch.items():
                    if key == "has_token":
                        continue
                    if key == "refresh_token" and value is None:
                        continue
                    auth[key] = value
                merged["auth"] = auth
            self._data = normalize(merged)
            self._save()
        return self.public()
