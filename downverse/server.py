"""Servidor HTTP local que alimenta a interface (só aceita conexões da própria máquina).

Proteções contra outras páginas abertas no navegador do usuário:
* escuta apenas em 127.0.0.1;
* confere o cabeçalho ``Host`` (anti DNS-rebinding);
* toda chamada ``/api`` exige um token aleatório gerado a cada execução.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yt_dlp

from . import __version__
from .engine import Engine, download_options_from_settings
from .library import Library
from .links import KIND_CHANNEL, LinkError, parse_link
from .manager import AnalysisManager, DownloadManager
from .paths import default_videos_dir
from .settings import DEFAULTS, SettingsStore, normalize
from .updates import UpdateChecker

UI_DIR = Path(__file__).parent / "ui"
MAX_BODY = 1_000_000
WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")


def open_path(path: Path | str) -> None:
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class AppContext:
    """Tudo que o servidor precisa, num lugar só (facilita os testes)."""

    def __init__(self, settings: SettingsStore | None = None, library: Library | None = None,
                 token: str | None = None):
        self.settings = settings or SettingsStore()
        self.library = library or Library()
        self.engine = Engine(self.settings, self.library)
        self.downloads = DownloadManager(self.settings, self.library, self.engine)
        self.analyses = AnalysisManager(self.settings, self.library, self.engine)
        self.engine.is_busy = lambda: self.downloads._running > 0
        self.updates = UpdateChecker()     # só consulta a rede quando alguém manda (app.py ou o botão)
        self.open_url = webbrowser.open    # trocável nos testes
        self.token = token or secrets.token_urlsafe(24)
        self.port = 0
        self.pick_file = None              # idem, para escolher o cookies.txt
        self.pick_folder = None            # preenchido pela janela nativa, se houver
        self.opener = open_path            # trocável nos testes
        self.img_src_extra = ""            # só a demo local usa (miniaturas simuladas em http://)

    @property
    def can_pick_folder(self) -> bool:
        return self.pick_folder is not None

    # -- estado -----------------------------------------------------------------
    def activity(self) -> list[dict]:
        today = datetime.now().astimezone().date()
        counts: dict = {}
        for item in self.library.all():
            try:
                day = datetime.fromisoformat(item["downloaded_at"]).astimezone().date()
            except (KeyError, ValueError):
                continue
            counts[day] = counts.get(day, 0) + 1
        days = [today - timedelta(days=n) for n in range(6, -1, -1)]
        return [{"date": d.isoformat(), "label": WEEKDAYS[d.weekday()], "count": counts.get(d, 0)} for d in days]

    def state(self) -> dict:
        items = self.library.all()
        return {
            "version": __version__,
            "ytdlp": yt_dlp.version.__version__,
            "platform": sys.platform,
            "settings": self.settings.public(),
            "output_dir": str(self.settings.weverse_root()),
            "default_output_dir": str(default_videos_dir()),
            "ffmpeg": bool(self.engine.ffmpeg),
            "can_pick_folder": self.can_pick_folder,
            "can_pick_file": self.pick_file is not None,
            "update": self.updates.status(self.settings.get()["skipped_version"]),
            "queue": self.downloads.snapshot(),
            "library": {
                "count": len(items),
                "size": sum(i.get("size") or 0 for i in items),
                "activity": self.activity(),
            },
        }

    def library_view(self) -> list[dict]:
        out = []
        for i in self.library.all():
            out.append({
                "id": i["id"], "title": i.get("title", ""), "community": i.get("community", ""),
                "uploader": i.get("uploader", ""), "timestamp": i.get("timestamp"),
                "size": i.get("size"), "duration": i.get("duration"), "height": i.get("height"),
                "subtitles": len(i.get("subtitles") or []),
                "has_thumb": bool(i.get("thumbnail") and Path(i["thumbnail"]).is_file()),
                "exists": bool(i.get("video") and Path(i["video"]).is_file()),
                "downloaded_at": i.get("downloaded_at"),
            })
        return out

    def download_options(self, overrides: dict | None = None) -> dict:
        cfg = self.settings.get()
        allowed = set(download_options_from_settings(cfg))
        merged = {**cfg, **{k: v for k, v in (overrides or {}).items() if k in allowed}}
        return download_options_from_settings(normalize(merged))


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def make_handler(ctx: AppContext):
    routes: list[tuple[str, re.Pattern, str]] = []

    def route(method: str, pattern: str):
        def deco(fn):
            routes.append((method, re.compile(f"^{pattern}$"), fn.__name__))
            return fn
        return deco

    class Handler(BaseHTTPRequestHandler):
        server_version = "Downverse"
        protocol_version = "HTTP/1.1"

        # -- infraestrutura ---------------------------------------------------------
        def log_message(self, *args):  # silencia o log padrão
            pass

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                f"default-src 'self'; img-src 'self' https: data: {ctx.img_src_extra}; style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, payload, status: int = 200):
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", {"Cache-Control": "no-store"})

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in {f"127.0.0.1:{ctx.port}", f"localhost:{ctx.port}"}

        def _token_ok(self, query: dict) -> bool:
            supplied = self.headers.get("X-Downverse-Token") or (query.get("t") or [""])[0]
            return secrets.compare_digest(supplied, ctx.token)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ApiError("Corpo da requisição grande demais.", 413)
            if not length:
                return {}
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ApiError("JSON inválido.")
            return data if isinstance(data, dict) else {}

        def _dispatch(self, method: str):
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            if not self._host_ok():
                return self._send(403, b"Forbidden", "text/plain")
            path = parts.path

            if not path.startswith("/api/"):
                return self._static(path) if method in ("GET", "HEAD") else self._send(405, b"", "text/plain")

            if not self._token_ok(query):
                return self._json({"error": "Sessão inválida. Reabra o Downverse."}, 401)
            try:
                for m, pattern, name in routes:
                    match = pattern.match(path)
                    if m == method and match:
                        body = self._body() if method == "POST" else {}
                        result = getattr(self, name)(match, body, query)
                        if result is not None:
                            return self._json(result)
                        return
                raise ApiError("Rota não encontrada.", 404)
            except ApiError as exc:
                self._json({"error": str(exc)}, exc.status)
            except Exception as exc:  # erro inesperado: não derruba o servidor
                self._json({"error": f"Erro interno: {exc}"}, 500)

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("HEAD")

        def do_POST(self):
            self._dispatch("POST")

        # -- arquivos da interface ----------------------------------------------------
        def _static(self, path: str):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (UI_DIR / rel).resolve()
            if UI_DIR.resolve() not in target.parents or not target.is_file():
                return self._send(404, b"Not found", "text/plain")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            data = target.read_bytes()
            if target.name == "index.html":  # sprite de ícones embutido (evita requisição extra)
                data = data.replace(b"<!--ICONS-->", (UI_DIR / "icons.svg").read_bytes())
            if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
                ctype += "; charset=utf-8"
            self._send(200, data, ctype, {"Cache-Control": "no-cache"})

        # -- rotas --------------------------------------------------------------------
        @route("GET", "/api/state")
        def state(self, m, body, q):
            return ctx.state()

        @route("POST", "/api/parse")
        def parse(self, m, body, q):
            try:
                return {"ok": True, "link": parse_link(str(body.get("text", ""))).to_dict()}
            except LinkError as exc:
                return {"ok": False, "error": str(exc)}

        @route("POST", "/api/analyze")
        def analyze(self, m, body, q):
            try:
                link = parse_link(str(body.get("url", "")))
            except LinkError as exc:
                raise ApiError(str(exc))
            if link.kind != KIND_CHANNEL:
                raise ApiError("Esse link é de uma live específica. Use o botão Baixar.")
            return {"id": ctx.analyses.start(link), "link": link.to_dict()}

        @route("GET", r"/api/analysis/(?P<id>\w+)")
        def analysis(self, m, body, q):
            since = int((q.get("since") or ["0"])[0] or 0)
            data = ctx.analyses.get(m["id"], since)
            if not data:
                raise ApiError("Análise não encontrada.", 404)
            return data

        @route("POST", r"/api/analysis/(?P<id>\w+)/cancel")
        def analysis_cancel(self, m, body, q):
            ctx.analyses.cancel(m["id"])
            return {"ok": True}

        @route("POST", "/api/downloads")
        def downloads(self, m, body, q):
            options = ctx.download_options(body.get("options"))
            if body.get("analysis_id"):
                entries = ctx.analyses.entries_by_ids(str(body["analysis_id"]), [str(i) for i in body.get("ids") or []])
                if not entries:
                    raise ApiError("Nenhuma live selecionada.")
            else:
                try:
                    link = parse_link(str(body.get("url", "")))
                except LinkError as exc:
                    raise ApiError(str(exc))
                if link.kind == KIND_CHANNEL:
                    raise ApiError("Esse link é de um canal. Clique em Buscar lives e escolha o que baixar.")
                entries = [{"id": link.post_id, "url": link.url, "title": f"Live {link.post_id}"}]
            ids = ctx.downloads.add(entries, options)
            return {"added": len(ids), "ids": ids}

        @route("POST", r"/api/queue/(?P<id>\w+)/cancel")
        def queue_cancel(self, m, body, q):
            return {"ok": ctx.downloads.cancel(m["id"])}

        @route("POST", r"/api/queue/(?P<id>\w+)/retry")
        def queue_retry(self, m, body, q):
            return {"ok": ctx.downloads.retry(m["id"], bool(body.get("force")))}

        @route("POST", "/api/queue/clear")
        def queue_clear(self, m, body, q):
            return {"removed": ctx.downloads.clear_finished()}

        @route("POST", "/api/queue/cancel-all")
        def queue_cancel_all(self, m, body, q):
            return {"canceled": ctx.downloads.cancel_all()}

        @route("POST", "/api/settings")
        def settings(self, m, body, q):
            return {"settings": ctx.settings.update(body), "output_dir": str(ctx.settings.weverse_root())}

        @route("POST", "/api/login/check")
        def login_check(self, m, body, q):
            return ctx.engine.check_login()

        @route("POST", "/api/pick-cookie-file")
        def pick_cookie_file(self, m, body, q):
            if not ctx.pick_file:
                raise ApiError("Seletor de arquivo indisponível neste modo. Cole o caminho do arquivo.")
            chosen = ctx.pick_file()
            if chosen:
                ctx.settings.update({"auth": {"method": "file", "cookie_file": str(chosen)}})
            return {"settings": ctx.settings.public(), "output_dir": str(ctx.settings.weverse_root())}

        @route("POST", "/api/pick-folder")
        def pick_folder(self, m, body, q):
            if not ctx.pick_folder:
                raise ApiError("Seletor de pasta indisponível neste modo. Digite o caminho.")
            chosen = ctx.pick_folder()
            if chosen:
                ctx.settings.update({"output_dir": str(chosen)})
            return {"settings": ctx.settings.public(), "output_dir": str(ctx.settings.weverse_root())}

        @route("POST", "/api/update/check")
        def update_check(self, m, body, q):
            ctx.updates.check()
            return {"update": ctx.updates.status(ctx.settings.get()["skipped_version"])}

        @route("POST", "/api/update/download")
        def update_download(self, m, body, q):
            # abre no navegador padrão; o endereço vem da nossa consulta ao GitHub, nunca da página
            ctx.open_url(ctx.updates.download_url())
            return {"ok": True}

        @route("POST", "/api/open")
        def open_(self, m, body, q):
            target = body.get("target")
            if target == "root":
                path = ctx.settings.weverse_root()
                path.mkdir(parents=True, exist_ok=True)
            elif target == "item":
                path = ctx.downloads.get_dir(str(body.get("id", "")))
            elif target in ("library", "library-video"):
                entry = ctx.library.get(str(body.get("id", ""))) or {}
                path = entry.get("dir") if target == "library" else entry.get("video")
            else:
                raise ApiError("Alvo inválido.")
            if not path or not Path(path).exists():
                raise ApiError("Essa pasta ou arquivo não existe mais.", 404)
            ctx.opener(path)
            return {"ok": True}

        @route("GET", "/api/library")
        def library(self, m, body, q):
            return {"items": ctx.library_view()}

        @route("GET", r"/api/library/(?P<id>[\w-]+)/thumb")
        def library_thumb(self, m, body, q):
            entry = ctx.library.get(m["id"]) or {}
            thumb = entry.get("thumbnail")
            if not thumb or not Path(thumb).is_file():
                self._send(404, b"", "text/plain")
                return
            ctype = mimetypes.guess_type(thumb)[0] or "image/jpeg"
            self._send(200, Path(thumb).read_bytes(), ctype, {"Cache-Control": "private, max-age=3600"})

        @route("POST", r"/api/library/(?P<id>[\w-]+)/remove")
        def library_remove(self, m, body, q):
            return {"ok": ctx.library.remove(m["id"])}

    return Handler


def make_server(ctx: AppContext, port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(ctx))
    server.daemon_threads = True
    ctx.port = server.server_address[1]
    return server
