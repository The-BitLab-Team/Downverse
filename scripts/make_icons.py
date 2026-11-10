"""Gera ui/icons.svg (sprite com os ícones usados) a partir do pacote lucide-static (licença ISC).

Uso: python scripts/make_icons.py /caminho/para/node_modules/lucide-static/icons
"""
import re
import sys
from pathlib import Path

ICONS = [
    "download", "link-2", "clipboard-paste", "search", "folder-open", "folder", "library-big",
    "circle-user-round", "settings", "sun", "moon", "check", "x", "play", "trash-2", "rotate-cw",
    "external-link", "lock", "calendar", "clock", "captions", "image", "film", "loader-circle",
    "triangle-alert", "info", "chevron-down", "list-checks", "hard-drive", "plug", "shield-check",
    "circle-check", "circle-x", "ban", "layers", "radio", "timer", "users", "arrow-down-to-line",
    "badge-check", "square-play", "cookie", "key-round", "file-text", "house",
]


def main(src: Path, out: Path) -> None:
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">']
    for name in ICONS:
        svg = (src / f"{name}.svg").read_text(encoding="utf-8")
        inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
        inner = re.sub(r"\s+", " ", inner).strip()
        parts.append(f'<symbol id="i-{name}" viewBox="0 0 24 24">{inner}</symbol>')
    parts.append("</svg>")
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(__file__).resolve().parents[1] / "downverse" / "ui" / "icons.svg")
