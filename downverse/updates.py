"""Aviso de versão nova: consulta a última release no GitHub. Não baixa nem instala nada sozinho.

A única chamada de rede é um GET público em api.github.com; nenhum dado do usuário é enviado.
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import threading
import time
import urllib.request
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


def _fetch_latest(timeout: float = 8.0) -> dict:
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
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
                 fetch: Callable[[], dict] = _fetch_latest):
        self.current = current
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self._fetch = fetch
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
            installer = ""
            for asset in data.get("assets") or []:
                name = str(asset.get("name") or "")
                if name.lower().startswith("downverse-setup") and name.lower().endswith(".exe"):
                    installer = _safe_url(asset.get("browser_download_url"))
            info = {"version": version, "page": _safe_url(data.get("html_url")) or RELEASES_PAGE,
                    "installer": installer}
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
            "has_installer": bool(info and info["installer"]) and sys.platform.startswith("win") and self.frozen,
        }

    def download_url(self) -> str:
        with self._lock:
            info = self._info
        if not info:
            return RELEASES_PAGE
        if info["installer"] and sys.platform.startswith("win") and self.frozen:
            return info["installer"]
        return info["page"]
