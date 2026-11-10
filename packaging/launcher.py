"""Ponto de entrada do executável (PyInstaller). Em desenvolvimento use ``python -m downverse``."""
import sys

from downverse.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
