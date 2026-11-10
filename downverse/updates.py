"""Aviso de versão nova: consulta a última release no GitHub. Não baixa nem instala nada sozinho.

A única chamada de rede é um GET público em api.github.com; nenhum dado do usuário é enviado.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__

REPO = "The-BitLab-Team/Downverse"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
CHECK_INTERVAL = 6 * 3600  # com o programa aberto, confere de novo a cada 6 horas


def parse_version(text: object) -> tuple[int, ...] | None:
    """'v0.1.12' -> (0, 1, 12). Devolve None se não for uma versão numérica."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", str(text or "").strip())
    return tuple(int(p) for p in match.group(1).split(".")) if match else None


def is_newer(latest: object, current: object, *, compare_build: bool = True) -> bool:
    """``compare_build=False`` ignora o terceiro número (o da execução do GitHub Actions), que só
    existe nas versões instaladas; rodando pelo código-fonte ele não diz nada."""
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    size = 3 if compare_build else 2
    pad = lambda v: (v + (0, 0, 0))[:size]  # noqa: E731
    return pad(a) > pad(b)


MAX_INSTALLER_BYTES = 500 * 1024 * 1024
INSTALLER_PREFIX = f"https://github.com/{REPO}/releases/download/"


class UpdateError(Exception):
    """Falha na atualização com mensagem pronta para o usuário."""


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _download(url: str, dest: Path, progress: Callable[[int], None], timeout: float = 30.0) -> None:
    """Baixa ``url`` para ``dest`` avisando quantos bytes já vieram."""
    request = urllib.request.Request(url, headers={"User-Agent": f"Downverse/{__version__}"})
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response, open(dest, "wb") as out:
        done = 0
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            done += len(chunk)
            if done > MAX_INSTALLER_BYTES:
                raise UpdateError("O arquivo da atualização é maior do que o esperado.")
            out.write(chunk)
            progress(done)


def _launch_installer(path: Path) -> None:
    """Roda o instalador (Inno Setup) sem perguntas; ele fecha o app, atualiza e abre de novo."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"],
        creationflags=flags, close_fds=True, cwd=str(path.parent))


def _fetch_latest(timeout: float = 8.0) -> dict:
    context = _ssl_context()
    request = urllib.request.Request(LATEST_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"Downverse/{__version__}"})
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read(2_000_000).decode("utf-8"))


def _safe_url(url: object) -> str:
    """Só aceita links https do próprio repositório no GitHub."""
    url = str(url or "")
    return url if url.startswith(f"https://github.com/{REPO}/") else ""


class UpdateChecker:
    def __init__(self, current: str = __version__, frozen: bool | None = None,
                 fetch: Callable[[], dict] = _fetch_latest,
                 download: Callable[[str, Path, Callable[[int], None]], None] = _download,
                 launch: Callable[[Path], None] = _launch_installer,
                 windows: bool | None = None, work_dir: Path | None = None):
        self.current = current
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self.windows = sys.platform.startswith("win") if windows is None else windows
        self._fetch = fetch
        self._download = download
        self._launch = launch
        self._work_dir = work_dir
        self._install = {"state": "idle", "progress": 0, "error": ""}  # idle | downloading | installing | error
        self._lock = threading.Lock()
        self._info: dict | None = None
        self._checked_at = 0.0
        self._error = ""
        self._checking = False

    # -- consulta ---------------------------------------------------------------
    def check(self) -> dict:
        """Consulta agora (bloqueia por alguns segundos). Nunca levanta exceção."""
        with self._lock:
            self._checking = True
        info, error = None, ""
        try:
            data = self._fetch()
            version = str(data.get("tag_name") or "").lstrip("v")
            if not parse_version(version):
                raise ValueError("resposta sem versão")
            installer, size, digest = "", 0, ""
            for asset in data.get("assets") or []:
                name = str(asset.get("name") or "")
                url = str(asset.get("browser_download_url") or "")
                if (name.lower().startswith("downverse-setup") and name.lower().endswith(".exe")
                        and url.startswith(INSTALLER_PREFIX)):
                    installer = url
                    size = int(asset.get("size") or 0)
                    digest = str(asset.get("digest") or "")  # "sha256:..." (o GitHub informa nas releases)
            info = {"version": version, "page": _safe_url(data.get("html_url")) or RELEASES_PAGE,
                    "installer": installer, "size": size, "digest": digest}
        except Exception:  # sem internet, limite da API, resposta estranha...
            error = "Não consegui consultar as atualizações. Verifique sua internet e tente de novo."
        with self._lock:
            self._checking = False
            self._checked_at = time.time()
            self._error = error
            if info:
                self._info = info
        return self.status()

    def check_in_background(self, enabled: Callable[[], bool]) -> None:
        """Confere ao abrir e depois de tempos em tempos, enquanto a opção estiver ligada."""
        def loop() -> None:
            while True:
                if enabled():
                    self.check()
                time.sleep(CHECK_INTERVAL)

        threading.Thread(target=loop, name="downverse-updates", daemon=True).start()

    # -- leitura ----------------------------------------------------------------
    def status(self, skipped: str = "") -> dict:
        with self._lock:
            info, error, checked, checking = self._info, self._error, self._checked_at, self._checking
            install = dict(self._install)
        latest = info["version"] if info else ""
        available = bool(info) and is_newer(latest, self.current, compare_build=self.frozen)
        return {
            "current": self.current,
            "latest": latest,
            "available": available,
            "notify": available and latest != skipped,
            "checked": bool(checked),
            "checking": checking,
            "error": error,
            # no Windows instalado o botão já baixa o instalador; nos outros casos abre a página da release
            "has_installer": self._can_install(info),
            "can_install": available and self._can_install(info),   # atualização com um clique
            "install": install,
        }

    def _can_install(self, info: dict | None) -> bool:
        return bool(info and info["installer"]) and self.windows and self.frozen

    def download_url(self) -> str:
        with self._lock:
            info = self._info
        if not info:
            return RELEASES_PAGE
        if self._can_install(info):
            return info["installer"]
        return info["page"]

    # -- atualização com um clique ------------------------------------------------
    def start_install(self, on_launched: Callable[[], None]) -> None:
        """Baixa o instalador em segundo plano, confere e executa. ``on_launched`` fecha o app."""
        with self._lock:
            info = self._info
            if self._install["state"] in ("downloading", "installing"):
                return
            if not (info and self._can_install(info) and is_newer(info["version"], self.current)):
                raise UpdateError("Não há atualização para instalar por aqui. Use “Verificar agora”.")
            self._install = {"state": "downloading", "progress": 0, "error": ""}
        threading.Thread(target=self._run_install, args=(dict(info), on_launched),
                         name="downverse-update-install", daemon=True).start()

    def _run_install(self, info: dict, on_launched: Callable[[], None]) -> None:
        folder = self._work_dir or Path(tempfile.gettempdir()) / "Downverse-atualizacao"
        target = folder / f"Downverse-Setup-{info['version']}.exe"
        part = target.with_suffix(".part")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob("Downverse-Setup-*"):      # sobras de atualizações anteriores
                try:
                    old.unlink()
                except OSError:
                    pass

            def progress(done: int) -> None:
                pct = min(99, int(done * 100 / info["size"])) if info["size"] else 0
                with self._lock:
                    self._install["progress"] = pct

            try:
                self._download(info["installer"], part, progress)
            except UpdateError:
                raise
            except Exception as exc:
                raise UpdateError("Não consegui baixar a atualização. Verifique sua internet e tente de novo.") from exc

            self._verify(part, info)
            os.replace(part, target)
            with self._lock:
                self._install = {"state": "installing", "progress": 100, "error": ""}
            try:
                self._launch(target)
            except Exception as exc:
                raise UpdateError("Não consegui abrir o instalador. Use “Baixar instalador” e instale manualmente.") from exc
        except UpdateError as exc:
            try:
                part.unlink()
            except OSError:
                pass
            with self._lock:
                self._install = {"state": "error", "progress": 0, "error": str(exc)}
            return
        on_launched()

    @staticmethod
    def _verify(path: Path, info: dict) -> None:
        """O arquivo tem que bater com o que o GitHub publicou (tamanho e, quando informado, SHA-256)."""
        problem = UpdateError("O arquivo baixado veio incompleto ou diferente do publicado. Tente de novo.")
        if info["size"] and path.stat().st_size != info["size"]:
            raise problem
        if info["digest"].startswith("sha256:"):
            sha = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    sha.update(chunk)
            if sha.hexdigest() != info["digest"][7:].lower():
                raise problem
