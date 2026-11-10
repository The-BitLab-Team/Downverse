"""Integração com o yt-dlp: listar lives de um canal e baixar uma live.

O extrator do Weverse do yt-dlp faz o trabalho pesado (API, formatos, legendas).
Aqui a gente só:
  * monta as opções (login, qualidade, legendas, thumbnail),
  * decide a pasta de destino com base nos metadados da live,
  * acompanha o progresso e traduz os erros para mensagens claras.
"""
from __future__ import annotations

import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError, ExtractorError

from .library import Library
from .paths import (
    LiveMeta, file_base_name, live_folder, sanitize_component, unique_live_folder,
)
from .settings import SettingsStore, config_dir

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def clean_message(msg: object) -> str:
    text = _ANSI.sub("", str(msg or "")).strip()
    text = re.sub(r"^(?:ERROR|WARNING):\s*", "", text)
    text = re.sub(r"^\[[^\]]+\]\s*(?:[\w-]+:\s*)?", "", text, count=1) if text.startswith("[") else text
    return text.strip()


class DownverseError(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


class AlreadyDownloaded(DownverseError):
    """A live já está na biblioteca (não é um erro de verdade)."""


# ---------------------------------------------------------------------------
# FFmpeg
# ---------------------------------------------------------------------------


def find_ffmpeg() -> str | None:
    """ffmpeg do sistema ou, na falta dele, o binário embutido do imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if exe and os.path.exists(exe) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Logger do yt-dlp que guarda avisos/erros para a gente interpretar
# ---------------------------------------------------------------------------


class CaptureLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def debug(self, msg: str) -> None:  # noqa: D401
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        text = clean_message(msg)
        if text and text not in self.warnings:
            self.warnings.append(text)

    def error(self, msg: str) -> None:
        text = clean_message(msg)
        if text and text not in self.errors:
            self.errors.append(text)


# ---------------------------------------------------------------------------
# Tradução de erros
# ---------------------------------------------------------------------------

_ERROR_MAP: list[tuple[str, str]] = [
    ("only available for logged-in users",
     "Esse conteúdo exige login. Conecte sua conta Weverse na aba Conta."),
    ("does not have access to this content",
     "Sua conta não tem acesso a esse conteúdo (exclusivo para membros ou pago)."),
    ("has not yet started", "A live ainda não começou."),
    ("downloadable vod is not available",
     "A live terminou, mas o VOD ainda não está disponível. Tente de novo mais tarde."),
    ("drm", "Conteúdo protegido por DRM. O Downverse não baixa vídeos protegidos."),
    ("refresh token", "O token de acesso expirou. Entre no Weverse pelo navegador e conecte a conta de novo."),
    ("access token", "O login expirou. Entre no Weverse pelo navegador e conecte a conta de novo."),
    ("could not find", "Não consegui ler os cookies do navegador escolhido. Feche o navegador ou escolha outro método na aba Conta."),
    ("failed to decrypt", "Não consegui ler os cookies do navegador (criptografados). Use o Firefox, um arquivo cookies.txt ou o token na aba Conta."),
    ("http error 404", "Live não encontrada. O link pode estar errado ou o vídeo foi removido."),
    ("http error 429", "O Weverse limitou as requisições. Espere alguns minutos e tente de novo."),
    ("timed out", "A conexão demorou demais. Verifique sua internet e tente de novo."),
    ("unable to download", "Falha ao falar com o Weverse. Verifique sua internet e tente de novo."),
    ("urlopen error", "Sem conexão com a internet."),
    ("no space left", "Sem espaço no disco de destino."),
    ("permission denied", "Sem permissão para gravar na pasta de destino."),
]


def friendly_error(exc: BaseException, warnings: list[str] | None = None) -> str:
    if isinstance(exc, DownverseError):
        return str(exc)
    text = clean_message(exc)
    low = text.lower()
    for needle, message in _ERROR_MAP:
        if needle in low:
            return message
    if warnings:
        joined = " ".join(warnings).lower()
        for needle, message in _ERROR_MAP:
            if needle in joined:
                return message
    return (text[:300] + "…") if len(text) > 300 else (text or "Erro desconhecido ao baixar.")


# ---------------------------------------------------------------------------
# Opções do yt-dlp
# ---------------------------------------------------------------------------


def format_spec(quality: str) -> str:
    if quality == "worst":
        return "wv*+wa/w"
    if quality.isdigit():
        h = int(quality)
        return f"bv*[height<=?{h}]+ba/b[height<=?{h}]/wv*+wa/w"
    return "bv*+ba/b"


def subtitle_patterns(langs: list[str], fan_subtitles: bool) -> list[str]:
    patterns = [f"{re.escape(code)}(?:_.*)?" for code in langs] if langs else ["all"]
    if not fan_subtitles:
        patterns.append(r"-.*_fan\d+")
    return patterns


def download_options_from_settings(cfg: dict) -> dict:
    """Recorte das configurações que valem para um download (guardado em cada item da fila)."""
    keys = (
        "quality", "subtitles", "subtitle_langs", "subtitle_format", "fan_subtitles",
        "thumbnail", "subtitles_dir_name", "artist_mode", "date_timezone", "overwrite",
    )
    return {k: cfg[k] for k in keys}


class Engine:
    def __init__(self, settings: SettingsStore, library: Library):
        self.settings = settings
        self.library = library
        self.ffmpeg = find_ffmpeg()
        self.cache_dir = config_dir() / "cache"

    # -- opções -----------------------------------------------------------------
    def _base_opts(self, logger: CaptureLogger) -> dict:
        opts: dict = {
            "quiet": True,
            "noprogress": True,
            "logger": logger,
            "cachedir": str(self.cache_dir),
            "retries": 5,
            "fragment_retries": 10,
            "extractor_retries": 3,
            "socket_timeout": 30,
            "concurrent_fragment_downloads": 4,
            "continuedl": True,
        }
        if self.ffmpeg:
            opts["ffmpeg_location"] = self.ffmpeg
        auth = self.settings.get()["auth"]
        if auth["method"] == "browser":
            opts["cookiesfrombrowser"] = (auth["browser"], auth["profile"] or None, None, None)
        elif auth["method"] == "file" and auth["cookie_file"]:
            opts["cookiefile"] = auth["cookie_file"]
        elif auth["method"] == "token" and auth["refresh_token"]:
            opts["username"] = "oauth"
            opts["password"] = auth["refresh_token"]
        return opts

    def _download_opts(self, options: dict, logger: CaptureLogger) -> dict:
        opts = self._base_opts(logger)
        opts["format"] = format_spec(options["quality"])
        opts["merge_output_format"] = "mp4"
        opts["overwrites"] = bool(options["overwrite"])
        opts["writesubtitles"] = bool(options["subtitles"])
        if options["subtitles"]:
            opts["subtitleslangs"] = subtitle_patterns(options["subtitle_langs"], options["fan_subtitles"])
            opts["subtitlesformat"] = "vtt/best"
        opts["writethumbnail"] = bool(options["thumbnail"])
        pps: list[dict] = []
        if self.ffmpeg:
            if options["subtitles"] and options["subtitle_format"] == "srt":
                pps.append({"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"})
            if options["thumbnail"]:
                pps.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
        opts["postprocessors"] = pps
        return opts

    def _make_ydl(self, opts: dict) -> yt_dlp.YoutubeDL:
        try:
            return yt_dlp.YoutubeDL(opts)
        except Exception as exc:  # cookies do navegador ilegíveis, arquivo inexistente...
            raise DownverseError(friendly_error(exc)) from exc

    # -- login ------------------------------------------------------------------
    def check_login(self) -> dict:
        """Confere se há uma sessão do Weverse utilizável com o método escolhido."""
        auth = self.settings.get()["auth"]
        method = auth["method"]
        if method == "none":
            return {"ok": False, "method": method, "message": "Nenhuma conta conectada."}
        if method == "file" and not Path(auth["cookie_file"]).is_file():
            return {"ok": False, "method": method, "message": "Arquivo de cookies não encontrado."}
        if method == "token":
            if not auth["refresh_token"]:
                return {"ok": False, "method": method, "message": "Cole o token de atualização."}
            return {"ok": True, "method": method, "message": "Token salvo. Ele será validado no primeiro download."}

        logger = CaptureLogger()
        try:
            ydl = self._make_ydl(self._base_opts(logger))
        except DownverseError as exc:
            return {"ok": False, "method": method, "message": str(exc)}
        names = {c.name for c in ydl.cookiejar if "weverse.io" in (c.domain or "")}
        ydl.close()
        if "we2_access_token" in names or "we2_refresh_token" in names:
            return {"ok": True, "method": method, "message": "Sessão do Weverse encontrada."}
        return {
            "ok": False, "method": method,
            "message": "Não achei uma sessão do Weverse. Entre em weverse.io nesse navegador e tente de novo.",
        }

    # -- listagem do canal ------------------------------------------------------
    def list_channel(self, url: str, should_stop: Callable[[], bool]) -> tuple[dict, Iterator[dict]]:
        """Devolve (info do canal, iterador preguiçoso com as lives)."""
        logger = CaptureLogger()
        ydl = self._make_ydl({**self._base_opts(logger), "extract_flat": "in_playlist"})
        try:
            info = ydl.extract_info(url, download=False, process=False)
        except Exception as exc:
            ydl.close()
            raise DownverseError(friendly_error(exc, logger.warnings)) from exc

        def entries() -> Iterator[dict]:
            try:
                for entry in info.get("entries") or []:
                    if should_stop():
                        return
                    if entry:
                        yield entry
            except Exception as exc:
                raise DownverseError(friendly_error(exc, logger.warnings)) from exc
            finally:
                ydl.close()

        return info, entries()

    # -- download de uma live -----------------------------------------------------
    def download(self, url: str, options: dict, cb: "DownloadCallbacks") -> dict:
        """Baixa uma live. Devolve um dicionário descrevendo o que foi salvo."""
        logger = CaptureLogger()
        ydl = self._make_ydl(self._download_opts(options, logger))
        dest: Path | None = None
        try:
            cb.phase("Lendo informações…")
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as exc:
                raise DownverseError(friendly_error(exc, logger.warnings)) from exc
            cb.check_cancel()

            if not info or info.get("_type") == "playlist":
                raise DownverseError("Esse link aponta para vários itens. Use o link de uma live específica.")
            if not str(info.get("extractor_key", "")).lower().startswith("weverse"):
                raise DownverseError("Esse conteúdo é de outro site (por exemplo, um vídeo do YouTube) e não é suportado.")
            live_status = info.get("live_status")
            if live_status == "is_live":
                raise DownverseError("Essa live está acontecendo agora. Baixe o VOD depois que ela terminar.")
            if live_status == "is_upcoming":
                raise DownverseError("Essa live ainda não começou.")
            joined = " ".join(logger.warnings).lower()
            if "drm" in joined:
                raise DownverseError("Conteúdo protegido por DRM: só existe uma prévia de 30 segundos. O Downverse não baixa vídeos protegidos.")
            if not info.get("formats"):
                raise DownverseError("Nenhum vídeo disponível para esta live.")

            meta = meta_from_info(info)
            cb.meta(meta, info)

            existing = self.library.get(meta.live_id)
            if existing and self.library.has_video(meta.live_id) and not options["overwrite"]:
                raise AlreadyDownloaded("Já baixada. Ative “Substituir arquivos existentes” para baixar de novo.")

            root = self.settings.output_root()
            dest = unique_live_folder(
                live_folder(root, meta, options["artist_mode"], options["date_timezone"]),
                meta.live_id, self.library.owner_of_folder,
            )
            dest.mkdir(parents=True, exist_ok=True)
            base = file_base_name(meta.title, meta.live_id)
            sub_dir = sanitize_component(options["subtitles_dir_name"], fallback="Legendas", max_chars=40)

            ydl.params["paths"] = {"home": str(dest), "subtitle": str(dest / sub_dir)}
            ydl.params["outtmpl"] = {"default": base.replace("%", "%%") + ".%(ext)s"}
            cb.dest(dest)

            cb.phase("Baixando…")
            cb.attach(ydl)
            result = ydl.process_ie_result(info, download=True)
            cb.check_cancel()
            return self._describe_result(result, dest, base, sub_dir, meta, info, logger, options)
        except DownloadCancelled:
            self._cleanup(dest)
            raise
        except (AlreadyDownloaded, DownverseError):
            self._cleanup(dest)
            raise
        except Exception as exc:
            self._cleanup(dest)
            raise DownverseError(friendly_error(exc, logger.warnings)) from exc
        finally:
            ydl.close()

    # -- utilitários ------------------------------------------------------------
    def _describe_result(self, result, dest, base, sub_dir, meta, info, logger, options) -> dict:
        video = None
        for d in (result or {}).get("requested_downloads") or []:
            path = d.get("filepath")
            if path and Path(path).is_file():
                video = Path(path)
                break
        if video is None:
            candidates = [p for p in dest.glob(base + ".*") if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")]
            video = candidates[0] if candidates else None
        if video is None:
            raise DownverseError("O download terminou, mas não encontrei o arquivo de vídeo.")

        thumbs = sorted(p for p in dest.glob(base + ".*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
        subs = sorted(p for p in (dest / sub_dir).glob(glob_escape(base) + ".*")
                      if p.suffix.lower() in (".srt", ".vtt", ".ttml")) if (dest / sub_dir).is_dir() else []

        warnings = []
        if options["subtitles"] and not subs:
            warnings.append("Esta live não tem legendas nos idiomas escolhidos.")
        if options["thumbnail"] and not thumbs:
            warnings.append("Não foi possível salvar a thumbnail.")

        return {
            "id": meta.live_id,
            "title": meta.title,
            "community": meta.community,
            "slug": meta.slug,
            "uploader": meta.uploader,
            "timestamp": meta.timestamp,
            "duration": info.get("duration"),
            "dir": str(dest),
            "video": str(video),
            "thumbnail": str(thumbs[0]) if thumbs else "",
            "subtitles": [str(p) for p in subs],
            "size": video.stat().st_size,
            "height": (info.get("requested_formats") or [info])[0].get("height") or info.get("height"),
            "warnings": warnings,
        }

    def _cleanup(self, dest: Path | None) -> None:
        """Remove restos de um download interrompido e pastas vazias."""
        if not dest or not dest.exists():
            return
        try:
            for p in dest.rglob("*"):
                if p.is_file() and (p.suffix in (".part", ".ytdl", ".temp") or ".part-" in p.name):
                    p.unlink(missing_ok=True)
            for folder in sorted((p for p in dest.rglob("*") if p.is_dir()), reverse=True):
                try:
                    folder.rmdir()
                except OSError:
                    pass
            folder = dest
            for _ in range(3):  # data -> membro -> grupo
                try:
                    folder.rmdir()
                except OSError:
                    break
                folder = folder.parent
        except OSError:
            pass


def glob_escape(text: str) -> str:
    import glob

    return glob.escape(text)


def meta_from_info(info: dict) -> LiveMeta:
    creators = info.get("creators") or []
    community = (creators[0] if creators else None) or info.get("creator") or ""
    slug = info.get("channel") or ""
    if not community:
        community = slug
    return LiveMeta(
        live_id=str(info.get("id") or ""),
        title=str(info.get("title") or "").strip(),
        community=str(community).strip(),
        slug=str(slug).strip(),
        uploader=str(info.get("uploader") or "").strip(),
        timestamp=info.get("release_timestamp") or info.get("timestamp"),
    )


# ---------------------------------------------------------------------------
# Callbacks de progresso
# ---------------------------------------------------------------------------


class DownloadCallbacks:
    """Ponte entre o yt-dlp e o item da fila. A fila sobrescreve os métodos."""

    def phase(self, text: str) -> None: ...
    def meta(self, meta: LiveMeta, info: dict) -> None: ...
    def dest(self, path: Path) -> None: ...
    def progress(self, pct: float, speed: float | None, eta: float | None, downloaded: int, total: int | None) -> None: ...
    def is_cancelled(self) -> bool:
        return False

    def check_cancel(self) -> None:
        if self.is_cancelled():
            raise DownloadCancelled()

    def attach(self, ydl: yt_dlp.YoutubeDL) -> None:
        """Liga os hooks de progresso do yt-dlp a este objeto."""
        streams = {"total": 1, "done": 0}

        def hook(d: dict) -> None:
            self.check_cancel()
            info = d.get("info_dict") or {}
            total_streams = len(info.get("requested_formats") or []) or 1
            streams["total"] = total_streams
            if d.get("status") == "finished":
                streams["done"] += 1
                self.progress(min(100.0, streams["done"] / total_streams * 100), None, None,
                              d.get("downloaded_bytes") or 0, d.get("total_bytes"))
                return
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            if total:
                frac = done / total
            elif d.get("fragment_count"):
                frac = (d.get("fragment_index") or 0) / d["fragment_count"]
            else:
                frac = 0.0
            frac = max(0.0, min(1.0, frac))
            pct = (streams["done"] + frac) / total_streams * 100
            self.progress(min(99.9, pct), d.get("speed"), d.get("eta"), done, total)

        def pp_hook(d: dict) -> None:
            self.check_cancel()
            if d.get("status") == "started":
                names = {
                    "Merger": "Juntando vídeo e áudio…",
                    "FFmpegSubtitlesConvertor": "Convertendo legendas…",
                    "FFmpegThumbnailsConvertor": "Convertendo thumbnail…",
                    "MoveFiles": "Organizando arquivos…",
                }
                self.phase(names.get(d.get("postprocessor"), "Finalizando…"))

        ydl.add_progress_hook(hook)
        ydl.add_postprocessor_hook(pp_hook)
