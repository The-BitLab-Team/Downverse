"""Aviso de versão nova (sem rede: a consulta ao GitHub é simulada)."""
import pytest

from downverse.updates import REPO, UpdateChecker, is_newer, parse_version

from .test_server import api  # noqa: F401  (fixture)


def release(tag, installer=True, page=None):
    assets = [{"name": f"Downverse-portatil-{tag[1:]}.zip", "browser_download_url": f"https://github.com/{REPO}/releases/download/{tag}/p.zip"}]
    if installer:
        assets.append({"name": f"Downverse-Setup-{tag[1:]}.exe",
                       "browser_download_url": f"https://github.com/{REPO}/releases/download/{tag}/Downverse-Setup-{tag[1:]}.exe"})
    return {"tag_name": tag, "html_url": page or f"https://github.com/{REPO}/releases/tag/{tag}", "assets": assets}


def test_version_compare():
    assert parse_version("v0.1.12") == (0, 1, 12) and parse_version("nightly") is None
    assert is_newer("0.1.10", "0.1.9") and is_newer("v0.2.0", "0.1.99") and is_newer("1.0", "0.9.9")
    assert not is_newer("0.1.3", "0.1.3") and not is_newer("0.1.2", "0.1.3") and not is_newer("lixo", "0.1.0")
    # rodando pelo código-fonte, o número da execução não conta
    assert not is_newer("0.1.57", "0.1.0", compare_build=False)
    assert is_newer("0.2.1", "0.1.0", compare_build=False)


def test_checker_states():
    checker = UpdateChecker(current="0.1.3", frozen=True, fetch=lambda: release("v0.1.7"))
    assert checker.status()["available"] is False and checker.status()["checked"] is False   # antes de consultar
    status = checker.check()
    assert status["available"] and status["notify"] and status["latest"] == "0.1.7"
    assert checker.status(skipped="0.1.7")["notify"] is False                                # "pular esta versão"
    assert checker.status(skipped="0.1.6")["notify"] is True

    assert UpdateChecker(current="0.1.7", frozen=True, fetch=lambda: release("v0.1.7")).check()["available"] is False
    assert UpdateChecker(current="0.1.0", frozen=False, fetch=lambda: release("v0.1.7")).check()["available"] is False


def test_checker_never_raises_and_keeps_last_answer():
    answers = [release("v0.2.0")]

    def fetch():
        if not answers:
            raise OSError("sem internet")
        return answers.pop()

    checker = UpdateChecker(current="0.1.3", frozen=True, fetch=fetch)
    assert checker.check()["available"]
    status = checker.check()                              # caiu a internet: avisa, mas não esquece a versão
    assert status["error"] and status["available"] and status["latest"] == "0.2.0"
    assert UpdateChecker(current="0.1.3", fetch=lambda: {"tag_name": "nightly"}).check()["error"]


def test_download_url_only_trusts_the_repo(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    good = UpdateChecker(current="0.1.3", frozen=True, fetch=lambda: release("v0.1.7"))
    good.check()
    assert good.download_url().endswith("/Downverse-Setup-0.1.7.exe") and good.status()["has_installer"]

    evil = release("v0.1.7", page="https://evil.example/x")
    evil["assets"][1]["browser_download_url"] = "https://evil.example/Downverse-Setup-0.1.7.exe"
    checker = UpdateChecker(current="0.1.3", frozen=True, fetch=lambda: evil)
    checker.check()
    assert checker.download_url() == f"https://github.com/{REPO}/releases/latest"

    source = UpdateChecker(current="0.1.0", frozen=False, fetch=lambda: release("v0.2.0"))
    source.check()                                         # sem instalador próprio: abre a página da release
    assert source.download_url() == f"https://github.com/{REPO}/releases/tag/v0.2.0"


def test_api_update_flow(api):  # noqa: F811
    ctx = api.ctx
    ctx.updates = UpdateChecker(current="0.1.3", frozen=True, fetch=lambda: release("v0.1.9"))
    opened = []
    ctx.open_url = opened.append

    assert api("GET", "/api/state")[1]["update"]["available"] is False       # abrir a tela não consulta a rede
    status, body = api("POST", "/api/update/check")
    assert status == 200 and body["update"]["notify"] is True
    api("POST", "/api/update/download")
    assert len(opened) == 1 and opened[0].startswith(f"https://github.com/{REPO}/")

    api("POST", "/api/settings", {"skipped_version": "0.1.9"})
    update = api("GET", "/api/state")[1]["update"]
    assert update["available"] is True and update["notify"] is False
    api("POST", "/api/settings", {"skipped_version": "<script>"})            # só aceita número de versão
    assert ctx.settings.get()["skipped_version"] == ""
    assert api("POST", "/api/settings", {"check_updates": False})[1]["settings"]["check_updates"] is False
