"""Ponto de entrada: ``python -m downverse`` (interface) ou ``python -m downverse download URL`` (terminal)."""
from __future__ import annotations

import argparse
import os
import sys
import time

from . import __version__


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="downverse", description="Baixa VODs do Weverse com legendas e thumbnails.")
    p.add_argument("--version", action="version", version=f"Downverse {__version__}")
    sub = p.add_subparsers(dest="cmd")

    gui = sub.add_parser("gui", help="abre a interface (padrão)")
    gui.add_argument("--browser", action="store_true", help="abre no navegador em vez da janela nativa")
    gui.add_argument("--port", type=int, default=0, help="porta local (padrão: automática)")

    dl = sub.add_parser("download", help="baixa uma live ou todas as lives de um canal, pelo terminal")
    dl.add_argument("url", help="link de uma live ou do canal do artista/grupo")
    dl.add_argument("-q", "--quality", choices=["best", "1080", "720", "480", "360", "worst"])
    dl.add_argument("--no-subs", action="store_true", help="não baixar legendas")
    dl.add_argument("--langs", help="idiomas das legendas, separados por vírgula (ex.: pt,en). Padrão: todos")
    dl.add_argument("--no-thumb", action="store_true", help="não baixar a thumbnail")
    dl.add_argument("-o", "--output", help="pasta onde criar a pasta Weverse (padrão: Vídeos)")
    dl.add_argument("--solo", action="store_true", help="artista solo: nunca criar pasta de membro")
    dl.add_argument("--overwrite", action="store_true", help="baixar de novo o que já foi baixado")
    return p


def _download(args) -> int:
    from .links import KIND_CHANNEL, LinkError, parse_link
    from .server import AppContext

    try:
        link = parse_link(args.url)
    except LinkError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    ctx = AppContext()
    patch: dict = {}
    if args.quality:
        patch["quality"] = args.quality
    if args.no_subs:
        patch["subtitles"] = False
    if args.langs:
        patch["subtitle_langs"] = [c.strip() for c in args.langs.split(",") if c.strip()]
    if args.no_thumb:
        patch["thumbnail"] = False
    if args.output:
        patch["output_dir"] = args.output
    if args.solo:
        patch["artist_mode"] = "solo"
    if args.overwrite:
        patch["overwrite"] = True
    options = ctx.download_options({**ctx.settings.get(), **patch})
    if "output_dir" in patch:
        ctx.settings.update({"output_dir": patch["output_dir"]})

    if link.note:
        print(link.note)
    if link.kind == KIND_CHANNEL:
        print("Listando as lives do canal…")
        analysis_id = ctx.analyses.start(link)
        while True:
            data = ctx.analyses.get(analysis_id)
            if data["status"] != "running":
                break
            time.sleep(0.3)
        if data["status"] == "error":
            print(f"Erro: {data['error']}", file=sys.stderr)
            return 1
        entries = ctx.analyses.entries_by_ids(analysis_id, [e["id"] for e in data["entries"]])
        print(f"{len(entries)} lives baixáveis ({data['total']} no total).")
    else:
        entries = [{"id": link.post_id, "url": link.url, "title": f"Live {link.post_id}"}]

    ctx.downloads.add(entries, options)
    last = ""
    while not ctx.downloads.wait_idle(0.5):
        snap = ctx.downloads.snapshot()
        active = [i for i in snap["items"] if i["status"] == "downloading"]
        line = "  ".join(f"{i['title'][:40]} {i['progress']:.0f}%" for i in active)
        if line != last:
            print(line)
            last = line
    snap = ctx.downloads.snapshot()
    for item in snap["items"]:
        mark = {"done": "ok", "skipped": "já baixada", "error": "ERRO", "canceled": "cancelada"}[item["status"]]
        extra = f" — {item['error']}" if item["error"] else ""
        print(f"[{mark}] {item['title']}{extra}")
    return 0 if not snap["counts"]["error"] else 1


def _ensure_std_streams() -> None:
    """Sem console (pythonw.exe ou executável em modo janela) stdout/stderr vêm como ``None``;
    ``print`` e o yt-dlp quebrariam. Troca por um descarte."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _report_crash() -> None:
    """Sem console ninguém veria o erro: grava um log e, no Windows, avisa numa caixa de mensagem."""
    import traceback

    from .settings import config_dir

    text = traceback.format_exc()
    log = None
    try:
        folder = config_dir()
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / "erro.log"
        log.write_text(text, encoding="utf-8")
    except OSError:
        pass
    print(text, file=sys.stderr)
    if os.name == "nt":
        try:
            import ctypes

            where = f"\n\nDetalhes salvos em:\n{log}" if log else ""
            ctypes.windll.user32.MessageBoxW(
                None, f"O Downverse não conseguiu abrir.{where}", "Downverse", 0x10)
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _ensure_std_streams()
    args = _parser().parse_args(argv)
    if args.cmd == "download":
        return _download(args)
    from .app import run_gui

    try:
        run_gui(port=getattr(args, "port", 0), prefer_browser=getattr(args, "browser", False))
    except Exception:
        _report_crash()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
