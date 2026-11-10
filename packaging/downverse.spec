# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller. Use o criar_instalador.bat (ele chama: pyinstaller packaging\downverse.spec).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve().parent
ICON = ROOT / "assets" / "downverse.ico"

datas = [(str(ROOT / "downverse" / "ui"), "downverse/ui")]
binaries = []
hiddenimports = []


def bundle(package):
    """Inclui código, dados e binários de um pacote, se ele estiver instalado."""
    try:
        d, b, h = collect_all(package)
    except Exception:
        return
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# FFmpeg embutido (usado quando o computador não tem ffmpeg) e o solucionador de desafios do yt-dlp.
for name in ("imageio_ffmpeg", "yt_dlp_ejs"):
    bundle(name)
datas += collect_data_files("certifi")

# Janela nativa (WebView2 no Windows). Sem o pywebview o app abre no navegador padrão.
if sys.platform == "win32":
    for name in ("webview", "clr_loader", "pythonnet"):
        bundle(name)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Downverse",
    console=False,          # sem janela de terminal
    icon=str(ICON) if ICON.exists() else None,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Downverse",
)
