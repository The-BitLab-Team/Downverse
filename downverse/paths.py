"""Pasta de vídeos do sistema, nomes de arquivo seguros e a hierarquia de pastas.

Hierarquia (dentro da pasta de Vídeos do computador)::

    Weverse/
      <Artista solo ou Grupo>/
        [<Membro>/]            só quando um membro de grupo fez a live
          <AAAA-MM-DD>/        data da live
            <Título>.mp4       vídeo e thumbnail ficam soltos aqui
            <Título>.jpg
            Legendas/
              <Título>.pt_BR.srt
"""
from __future__ import annotations

import os
import platform
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ROOT_FOLDER_NAME = "Weverse"
DEFAULT_SUBTITLES_DIR = "Legendas"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".ts"}

# ---------------------------------------------------------------------------
# Pasta de vídeos do sistema
# ---------------------------------------------------------------------------


def _windows_videos_dir() -> Path | None:
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
            ]

        u = uuid.UUID("{18989B1D-99B5-455B-841C-AB7C74E4DDFC}")  # FOLDERID_Videos
        guid = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        ptr = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(ptr)) != 0:
            return None
        value = ptr.value
        ctypes.windll.ole32.CoTaskMemFree(ptr)
        return Path(value) if value else None
    except Exception:
        return None


def _xdg_videos_dir() -> Path | None:
    env = os.environ.get("XDG_VIDEOS_DIR")
    if env:
        return Path(env).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    cfg = config_home / "user-dirs.dirs"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            m = re.match(r'\s*XDG_VIDEOS_DIR\s*=\s*"?([^"\n]+)"?', line)
            if m:
                return Path(m.group(1).replace("$HOME", str(Path.home()))).expanduser()
    except OSError:
        pass
    return None


def default_videos_dir() -> Path:
    """Pasta de Vídeos do usuário (respeita o idioma do sistema e redirecionamentos)."""
    system = platform.system()
    found: Path | None = None
    if system == "Windows":
        found = _windows_videos_dir()
    elif system == "Darwin":
        found = Path.home() / "Movies"
    else:
        found = _xdg_videos_dir()
    return found or (Path.home() / "Videos")


# ---------------------------------------------------------------------------
# Nomes seguros
# ---------------------------------------------------------------------------

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿︀-️‍⃣←-⇿]+"
)


def strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text or "")


def _truncate_bytes(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    return raw[:max_bytes].decode("utf-8", errors="ignore")


def sanitize_component(name: str, fallback: str = "_", max_chars: int = 100, max_bytes: int = 180) -> str:
    """Deixa ``name`` seguro como nome de pasta/arquivo no Windows, macOS e Linux."""
    text = unicodedata.normalize("NFC", name or "")
    text = _ILLEGAL_CHARS.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:max_chars]
    text = _truncate_bytes(text, max_bytes)
    text = text.strip(" .")
    if not text:
        return fallback
    if text.split(".")[0].upper() in _WINDOWS_RESERVED:
        text = "_" + text
    return text


def sanitize_folder_name(name: str, fallback: str = "_") -> str:
    """Nome de pasta de artista/membro: igual ao anterior, mas sem emojis."""
    return sanitize_component(strip_emoji(name), fallback=fallback, max_chars=80)


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------

KST = timezone(timedelta(hours=9), "KST")


def _tz(mode: str):
    if mode == "utc":
        return timezone.utc
    if mode == "kst":
        return KST
    return None  # fuso local do computador


def folder_date(timestamp: int | float | None, tz_mode: str = "local") -> str:
    """AAAA-MM-DD da live, no fuso escolhido ('local', 'utc' ou 'kst')."""
    if not timestamp:
        return "Sem data"
    moment = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    tz = _tz(tz_mode)
    moment = moment.astimezone(tz) if tz else moment.astimezone()
    return moment.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Hierarquia de pastas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveMeta:
    live_id: str
    title: str
    community: str          # nome do canal (ex.: "LE SSERAFIM")
    slug: str               # código na URL (ex.: "lesserafim")
    uploader: str           # perfil que fez a live (membro, ou o próprio grupo)
    timestamp: int | None


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", strip_emoji(text or "")).casefold()
    text = "".join(ch for ch in text if ch.isalnum())
    if text.endswith("official") and len(text) > len("official"):
        text = text[: -len("official")]
    return text


def is_official_account(uploader: str, community: str, slug: str = "") -> bool:
    """True quando a live foi feita pela conta oficial do canal (o grupo/artista em si)."""
    up = _norm(uploader)
    if not up:
        return True
    return up in {_norm(community), _norm(slug)} - {""}


def artist_parts(meta: LiveMeta, artist_mode: str = "auto") -> list[str]:
    """Pastas de artista: ``[Grupo]`` ou ``[Grupo, Membro]``.

    ``artist_mode='solo'`` nunca cria pasta de membro (artista solo cujo perfil
    tem nome diferente do canal).
    """
    group = sanitize_folder_name(meta.community or meta.slug, fallback=meta.slug or "Weverse")
    if artist_mode == "solo" or is_official_account(meta.uploader, meta.community, meta.slug):
        return [group]
    member = sanitize_folder_name(meta.uploader, fallback="")
    if not member or member.casefold() == group.casefold():
        return [group]
    return [group, member]


def live_folder(root: Path, meta: LiveMeta, artist_mode: str = "auto", tz_mode: str = "local") -> Path:
    """Pasta-base da live, sem desempate: ``<root>/Weverse/<artista>/[<membro>/]<data>``."""
    path = root / ROOT_FOLDER_NAME
    for part in artist_parts(meta, artist_mode):
        path /= part
    return path / folder_date(meta.timestamp, tz_mode)


def _has_video(folder: Path) -> bool:
    try:
        return any(p.suffix.lower() in VIDEO_EXTENSIONS for p in folder.iterdir() if p.is_file())
    except OSError:
        return False


def unique_live_folder(candidate: Path, live_id: str, owner_of: Callable[[Path], str | None]) -> Path:
    """Evita misturar duas lives do mesmo artista no mesmo dia.

    ``2026-11-10``, ``2026-11-10 (2)``, ``2026-11-10 (3)``… A pasta é reaproveitada
    quando já pertence a esta mesma live (``owner_of`` devolve o ID dela).
    """
    for n in range(1, 1000):
        folder = candidate if n == 1 else candidate.with_name(f"{candidate.name} ({n})")
        owner = owner_of(folder)
        if owner == live_id:
            return folder
        if owner is not None:
            continue
        if not folder.exists() or not _has_video(folder):
            return folder
    raise RuntimeError("Não foi possível escolher uma pasta livre para esta live.")


def find_on_disk(candidate: Path, base: str) -> tuple[Path, Path] | None:
    """Procura o vídeo desta live já salvo na pasta da data (ou nas irmãs ``(2)``, ``(3)``…).

    Serve para reconhecer downloads que o histórico não conhece: histórico apagado, pasta copiada
    de outro computador, programa reinstalado. Devolve (pasta, vídeo) ou None.
    """
    for n in range(1, 1000):
        folder = candidate if n == 1 else candidate.with_name(f"{candidate.name} ({n})")
        if not folder.is_dir():
            return None
        for ext in VIDEO_EXTENSIONS:
            video = folder / f"{base}{ext}"
            if video.is_file() and video.stat().st_size > 0:
                return folder, video
    return None


def file_base_name(title: str, live_id: str) -> str:
    """Nome-base (sem extensão) dos arquivos da live."""
    return sanitize_component(title, fallback=f"Live {live_id}", max_chars=90, max_bytes=170)
