"""Abre o Downverse: janela nativa (pywebview) ou, se não houver, o navegador padrão."""
from __future__ import annotations

import threading
import time
import webbrowser

from .server import AppContext, make_server


def _native_folder_picker(window):
    import webview

    dialog_type = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
    if dialog_type is None:
        dialog_type = webview.FOLDER_DIALOG

    def pick() -> str | None:
        result = window.create_file_dialog(dialog_type)
        return result[0] if result else None

    return pick


def _native_file_picker(window):
    import webview

    dialog_type = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
    if dialog_type is None:
        dialog_type = webview.OPEN_DIALOG

    def pick() -> str | None:
        result = window.create_file_dialog(
            dialog_type, allow_multiple=False,
            file_types=("Cookies (*.txt;*.json)", "Todos os arquivos (*.*)"))
        return result[0] if result else None

    return pick


def run_gui(port: int = 0, prefer_browser: bool = False) -> None:
    ctx = AppContext()
    server = make_server(ctx, port)
    threading.Thread(target=server.serve_forever, name="downverse-http", daemon=True).start()
    url = f"http://127.0.0.1:{ctx.port}/?t={ctx.token}"
    ctx.updates.check_in_background(lambda: ctx.settings.get()["check_updates"])

    window = None
    if not prefer_browser:
        try:
            import webview  # type: ignore

            window = webview.create_window(
                "Downverse", url, width=1360, height=860, min_size=(1040, 700), background_color="#EEF0F8")
            ctx.pick_folder = _native_folder_picker(window)
            ctx.pick_file = _native_file_picker(window)
        except Exception:
            window = None

    if window is not None:
        try:
            import webview  # type: ignore

            webview.start()
            return
        except Exception:
            ctx.pick_folder = ctx.pick_file = None  # sem janela nativa: cai para o navegador

    print(f"Downverse rodando em {url}\nPressione Ctrl+C para sair.", flush=True)
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
