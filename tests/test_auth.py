"""Login no Weverse: o extrator real do yt-dlp roda contra uma API de contas simulada."""
import base64
import json
import time

import pytest
from yt_dlp.extractor import weverse as wv
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import ExtractorError

from downverse.auth import AuthError, clean_path, clean_token, prepare_cookie_file


def jwt(scope: str, ttl: int = 30 * 86400, tag: str = "a") -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'HS256'})}.{enc({'exp': int(time.time()) + ttl, 'scope': scope, 'tag': tag})}.sig"


class FakeAccounts:
    """Responde /token/validate e /token/refresh como a API de contas do Weverse."""

    def __init__(self):
        self.valid_access: set[str] = set()
        self.valid_refresh: set[str] = set()
        self.offline = False
        self.calls: list[str] = []

    def install(self, monkeypatch):
        fake = self

        def _download_json(self, url, video_id, *a, **kw):
            headers = kw.get("headers") or {}
            if fake.offline:
                raise ExtractorError("Unable to download JSON metadata: <urlopen error timed out>")
            if url.endswith("/token/validate"):
                fake.calls.append("validate")
                ok = headers.get("Authorization", "")[7:] in fake.valid_access
                return {"expiresIn": 3600} if ok else {}
            if url.endswith("/token/refresh"):
                fake.calls.append("refresh")
                token = json.loads(kw["data"])["refreshToken"]
                if token not in fake.valid_refresh:
                    class Resp:  # mínimo que o HTTPError precisa
                        status, reason, url, headers = 401, "Unauthorized", "x", {}
                        def read(self, *a): return b""
                        def close(self): pass
                    raise ExtractorError("Unable to refresh access token", cause=HTTPError(Resp()))
                fake.valid_refresh.discard(token)  # o Weverse troca o token a cada renovação
                new_access, new_refresh = jwt("access", tag="novo"), jwt("refresh", tag="novo")
                fake.valid_access.add(new_access)
                fake.valid_refresh.add(new_refresh)
                return {"accessToken": new_access, "refreshToken": new_refresh}
            raise AssertionError(f"chamada inesperada: {url}")

        monkeypatch.setattr(wv.WeverseBaseIE, "_download_json", _download_json)
        monkeypatch.setattr(wv.WeverseBaseIE, "_oauth_tokens", {})
        monkeypatch.setattr(wv.WeverseBaseIE, "_device_id", None)
        return self


@pytest.fixture()
def accounts(monkeypatch):
    return FakeAccounts().install(monkeypatch)


def netscape(path, access, refresh, header=True):
    lines = ["# Netscape HTTP Cookie File", ""] if header else []
    for name, value in (("we2_access_token", access), ("we2_refresh_token", refresh), ("we2_device_id", "dev-1")):
        lines.append("\t".join([".weverse.io", "TRUE", "/", "TRUE", "1999999999", name, value]))
    lines.append("\t".join([".exemplo.com", "TRUE", "/", "TRUE", "1999999999", "outro", "x"]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------------ limpeza do que o usuário cola

def test_clean_path_and_token():
    assert clean_path('  "C:\\Users\\Ana\\Downloads\\cookies.txt" ') == "C:\\Users\\Ana\\Downloads\\cookies.txt"
    assert clean_token(' "abc.def.ghi" ') == "abc.def.ghi"
    assert clean_token("we2_refresh_token=abc.def-g_h; Path=/") == "abc.def-g_h"
    assert clean_token("abc.\n def") == "abc.def"


def test_settings_strip_quotes(core):
    core.settings.update({"auth": {"method": "file", "cookie_file": '"/tmp/c.txt"', "refresh_token": "'tok'"}})
    auth = core.settings.get()["auth"]
    assert auth["cookie_file"] == "/tmp/c.txt" and auth["refresh_token"] == "tok"


# ------------------------------------------------------------------ arquivo de cookies

def test_cookie_file_formats(tmp_path):
    work = tmp_path / "work"
    plain = netscape(tmp_path / "ok.txt", "A", "R")
    out = prepare_cookie_file(f'"{plain}"', work)            # caminho entre aspas
    text = open(out, encoding="utf-8").read()
    assert text.startswith("# Netscape HTTP Cookie File") and "exemplo.com" not in text
    assert out != str(plain)                                  # nunca mexe no original

    no_header = netscape(tmp_path / "sem.txt", "A", "R", header=False)
    assert "we2_refresh_token\tR" in open(prepare_cookie_file(str(no_header), work), encoding="utf-8").read()

    as_json = tmp_path / "cookies.json"
    as_json.write_text(json.dumps([
        {"domain": ".weverse.io", "name": "we2_access_token", "value": "JA", "path": "/", "secure": True,
         "expirationDate": 1999999999.5, "hostOnly": False},
        {"domain": "weverse.io", "name": "we2_refresh_token", "value": "JR", "hostOnly": True},
    ]), encoding="utf-8")
    text = open(prepare_cookie_file(str(as_json), work), encoding="utf-8").read()
    assert ".weverse.io\tTRUE\t/\tTRUE\t1999999999\twe2_access_token\tJA" in text
    assert "weverse.io\tFALSE\t/\tTRUE\t0\twe2_refresh_token\tJR" in text


def test_cookie_file_errors(tmp_path):
    work = tmp_path / "work"
    with pytest.raises(AuthError, match="não encontrado"):
        prepare_cookie_file(str(tmp_path / "nada.txt"), work)
    with pytest.raises(AuthError, match="pasta"):
        prepare_cookie_file(str(tmp_path), work)
    other = tmp_path / "outro.txt"
    other.write_text("# Netscape HTTP Cookie File\n.exemplo.com\tTRUE\t/\tTRUE\t0\ta\tb\n", encoding="utf-8")
    with pytest.raises(AuthError, match="sessão do Weverse"):
        prepare_cookie_file(str(other), work)
    junk = tmp_path / "lixo.txt"
    junk.write_text("isto não é um arquivo de cookies", encoding="utf-8")
    with pytest.raises(AuthError, match="não tem cookies"):
        prepare_cookie_file(str(junk), work)


def test_cookie_copy_keeps_renewed_tokens_until_reexport(tmp_path):
    import os

    work = tmp_path / "work"
    src = netscape(tmp_path / "c.txt", "A1", "R1")
    copy = prepare_cookie_file(str(src), work)
    open(copy, "a", encoding="utf-8").write("# renovado\n")
    os.utime(copy, (time.time() + 5, time.time() + 5))
    assert "# renovado" in open(prepare_cookie_file(str(src), work), encoding="utf-8").read()   # cópia preservada
    netscape(src, "A2", "R2")
    os.utime(src, (time.time() + 60, time.time() + 60))                                          # exportou de novo
    assert "A2" in open(prepare_cookie_file(str(src), work), encoding="utf-8").read()


# ------------------------------------------------------------------ "Testar conexão" de ponta a ponta

def test_check_none_and_empty_fields(core, accounts):
    assert core.engine.check_login()["ok"] is False
    core.settings.update({"auth": {"method": "file"}})
    assert "Indique" in core.engine.check_login()["message"]
    core.settings.update({"auth": {"method": "token"}})
    assert "Cole o token" in core.engine.check_login()["message"]


def test_check_cookie_file_valid_session(core, accounts, tmp_path):
    access, refresh = jwt("access"), jwt("refresh")
    accounts.valid_access.add(access)
    core.settings.update({"auth": {"method": "file", "cookie_file": str(netscape(tmp_path / "c.txt", access, refresh))}})
    result = core.engine.check_login()
    assert result["ok"] is True, result
    assert accounts.calls == ["validate"]


def test_check_cookie_file_renews_expired_access_and_saves_it(core, accounts, tmp_path):
    access, refresh = jwt("access"), jwt("refresh")
    accounts.valid_refresh.add(refresh)                       # access vencido, refresh ainda vale
    src = netscape(tmp_path / "c.txt", access, refresh)
    core.settings.update({"auth": {"method": "file", "cookie_file": str(src)}})
    assert core.engine.check_login()["ok"] is True
    assert "refresh" in accounts.calls
    # o token novo fica guardado: um segundo teste (ou um download) não depende do token já trocado
    accounts.calls.clear()
    wv.WeverseBaseIE._oauth_tokens.clear()
    assert core.engine.check_login()["ok"] is True
    assert accounts.calls == ["validate"]
    assert refresh in src.read_text(encoding="utf-8")         # original intacto


def test_check_cookie_file_dead_session(core, accounts, tmp_path):
    core.settings.update({"auth": {"method": "file", "cookie_file": str(netscape(tmp_path / "c.txt", jwt("access"), jwt("refresh")))}})
    result = core.engine.check_login()
    assert result["ok"] is False and "expirou" in result["message"]


def test_check_cookie_file_problems_are_messages_not_crashes(core, accounts, tmp_path):
    core.settings.update({"auth": {"method": "file", "cookie_file": str(tmp_path / "sumiu.txt")}})
    assert "não encontrado" in core.engine.check_login()["message"]
    bad = tmp_path / "x.json"
    bad.write_text("[{", encoding="utf-8")
    core.settings.update({"auth": {"cookie_file": str(bad)}})
    assert "JSON" in core.engine.check_login()["message"]


def test_check_browser_not_installed(core, accounts, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    for browser in ("firefox", "chrome", "edge"):
        core.settings.update({"auth": {"method": "browser", "browser": browser}})
        result = core.engine.check_login()
        assert result["ok"] is False
        assert "Não achei esse navegador" in result["message"], result
        assert result["detail"]                               # o erro original vai junto, para suporte


def test_check_token(core, accounts):
    refresh = jwt("refresh")
    accounts.valid_refresh.add(refresh)
    core.settings.update({"auth": {"method": "token", "refresh_token": f'"{refresh}"'}})
    assert core.engine.check_login()["ok"] is True

    core.settings.update({"auth": {"refresh_token": jwt("access")}})          # colou o cookie errado
    result = core.engine.check_login()
    assert result["ok"] is False and "we2_refresh_token" in result["message"]

    core.settings.update({"auth": {"refresh_token": "qualquer-coisa"}})
    assert core.engine.check_login()["ok"] is False

    core.settings.update({"auth": {"refresh_token": jwt("refresh", tag="morto")}})
    result = core.engine.check_login()
    assert result["ok"] is False and "expirou" in result["message"]


def test_token_survives_restart_after_rotation(core, accounts):
    """O Weverse troca o refresh token ao renovar; o novo fica no cache e vale na próxima abertura."""
    refresh = jwt("refresh")
    accounts.valid_refresh.add(refresh)
    core.settings.update({"auth": {"method": "token", "refresh_token": refresh}})
    assert core.engine.check_login()["ok"] is True
    assert refresh not in accounts.valid_refresh
    wv.WeverseBaseIE._oauth_tokens.clear()                    # "fechou e abriu o programa"
    ydl = core.engine._make_ydl(core.engine._base_opts(type("L", (), {"debug": print, "info": print, "warning": print, "error": print})()))
    extractor = ydl.get_info_extractor("Weverse")
    extractor.initialize()
    assert extractor._is_logged_in


def test_changing_method_drops_old_session(core, accounts, tmp_path):
    access, refresh = jwt("access"), jwt("refresh")
    accounts.valid_access.add(access)
    core.settings.update({"auth": {"method": "file", "cookie_file": str(netscape(tmp_path / "c.txt", access, refresh))}})
    assert core.engine.check_login()["ok"] is True
    assert wv.WeverseBaseIE._oauth_tokens
    core.settings.update({"auth": {"method": "none"}})
    core.engine._base_opts(None)                              # qualquer uso seguinte
    assert not wv.WeverseBaseIE._oauth_tokens


def test_check_offline(core, accounts, tmp_path):
    accounts.offline = True
    core.settings.update({"auth": {"method": "file", "cookie_file": str(netscape(tmp_path / "c.txt", jwt("access"), jwt("refresh")))}})
    result = core.engine.check_login()
    assert result["ok"] is False and "internet" in result["message"].lower()
