"""Abre a interface do Downverse contra um Weverse SIMULADO (sem internet, sem conta).

Serve para desenvolver/testar a UI e ver o fluxo completo. Os downloads vão para uma
pasta temporária. Uso:  python scripts/demo_server.py [--port 8765] [--throttle 0.05]
"""
import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--throttle", type=float, default=0.02, help="atraso por 4 KB para o progresso ser visível")
    ap.add_argument("--seed", type=int, default=3, help="quantas lives baixar antes de abrir (histórico)")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="downverse-demo-"))
    os.environ["DOWNVERSE_HOME"] = str(tmp / "config")

    from tests import fake_weverse as fw
    from datetime import datetime, timezone

    # mais lives para o canal ficar com cara de verdade
    members = ["채원", "사쿠라", "김가을", "허윤진", "카즈하", "LE SSERAFIM "]
    titles = ["Boa noite 🌙", "Ensaio de dança", "Q&A com a gente", "Jantando juntas 🍜", "Aniversário!", "Bastidores do comeback",
              "Hoje a gente conversa", "Live de fim de semana", "Escutando música", "Maratona de jogos 🎮"]
    base = int(datetime(2026, 2, 1, 11, tzinfo=timezone.utc).timestamp() * 1000)
    for i in range(36):
        fw.POSTS.append(dict(id=f"2-2000{i:04d}", slug="lesserafim", author=members[i % len(members)],
                             title=f"{titles[i % len(titles)]} #{i + 1}", at=base + i * 31 * 3600 * 1000 // 2,
                             subs=["ko_KR", "en_US"], kind="vod"))
    media = fw.MediaServer(tmp / "media", throttle=0)
    fake = fw.FakeWeverse(media, page_size=12).install()

    from downverse.server import AppContext, make_server
    from downverse.engine import download_options_from_settings

    ctx = AppContext(token="demo")
    ctx.img_src_extra = "http://127.0.0.1:*"
    # simula uma versão nova publicada, para ver o aviso de atualização (nada é consultado na rede)
    from downverse.updates import UpdateChecker
    ctx.updates = UpdateChecker(current="0.1.3", frozen=True, fetch=lambda: {"tag_name": "v0.1.9", "assets": []})
    ctx.updates.check()
    ctx.open_url = lambda url: print("abriria:", url)
    cookies = tmp / "cookies.txt"      # sessão de mentira, só para a interface mostrar "conectado"
    cookies.write_text("# Netscape HTTP Cookie File\n.weverse.io\tTRUE\t/\tTRUE\t4102444800\twe2_refresh_token\tdemo\n", encoding="utf-8")
    ctx.settings.update({"output_dir": str(tmp / "Videos"), "auth": {"method": "file", "cookie_file": str(cookies)}})
    server = make_server(ctx, args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    opts = download_options_from_settings(ctx.settings.get())
    seed = [dict(id=p["id"], url=f"https://weverse.io/{p['slug']}/live/{p['id']}", title=p["title"])
            for p in fw.POSTS if p["id"] in ("2-100000003", "2-100000002", "2-100000001")][: args.seed]
    ctx.downloads.add(seed, opts)
    ctx.downloads.wait_idle(120)
    ctx.downloads.add([dict(id="2-100000009", url="https://weverse.io/taeyeon/live/2-100000009", title="Conteúdo DRM")], opts)
    ctx.downloads.wait_idle(60)
    media.stop()
    fake.media = fw.MediaServer(tmp / "media", throttle=args.throttle)   # a partir daqui os downloads ficam lentos
    media_port = fake.media.port
    print(f"Demo pronta: http://127.0.0.1:{ctx.port}/?t=demo  (arquivos em {tmp})", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
