"""Checagens estáticas dos .bat (não dá para executá-los fora do Windows)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BATS = ["iniciar.bat", "criar_instalador.bat"]


@pytest.mark.parametrize("name", BATS)
def test_bat_is_ascii_with_crlf(name):
    raw = (ROOT / name).read_bytes()
    raw.decode("ascii")  # acentos quebram em alguns consoles do Windows
    assert raw.count(b"\r\n") == raw.count(b"\n"), "todas as linhas devem terminar em CRLF"


@pytest.mark.parametrize("name", BATS)
def test_bat_jump_targets_exist(name):
    text = (ROOT / name).read_text(encoding="ascii")
    labels = set(re.findall(r"^:(\w+)", text, re.M))
    targets = re.findall(r"\bgoto\s+(\w+)", text, re.I) + re.findall(r"\bcall\s+:(\w+)", text, re.I)
    assert targets
    assert [t for t in targets if t.lower() != "eof" and t not in labels] == []


def test_installer_files_exist():
    for rel in ("packaging/downverse.spec", "packaging/launcher.py", "packaging/installer.iss", "assets/downverse.ico"):
        assert (ROOT / rel).is_file(), rel
    iss = (ROOT / "packaging/installer.iss").read_text(encoding="utf-8")
    assert "..\\dist\\Downverse\\*" in iss


def test_release_workflow_runs_on_main_and_publishes():
    yaml = pytest.importorskip("yaml")  # PyYAML não é dependência do app; roda onde estiver instalado

    wf = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    triggers = wf.get("on") or wf.get(True)  # PyYAML lê a chave "on" como True
    assert triggers["push"]["branches"] == ["main"]
    assert set(wf["jobs"]) == {"version", "test", "build", "release"}
    assert wf["jobs"]["release"]["permissions"]["contents"] == "write"
    # a release só sai depois dos testes e do build
    assert "build" in wf["jobs"]["release"]["needs"]
    assert "test" in wf["jobs"]["build"]["needs"]


def test_version_has_a_single_source():
    import re

    init = (ROOT / "downverse/__init__.py").read_text(encoding="utf-8")
    assert re.search(r'^__version__ = "\d+\.\d+\.\d+"', init, re.M)  # o workflow lê MAIOR.MENOR daqui
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert not re.search(r'^version\s*=\s*"', pyproject, re.M)  # sem número duplicado no pyproject
