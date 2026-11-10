import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from downverse.server import AppContext, make_server


@pytest.fixture()
def api(core, fake):
    ctx = AppContext(settings=core.settings, library=core.library, token="tok")
    server = make_server(ctx)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{ctx.port}"
    opened = []
    ctx.opener = opened.append

    def call(method, path, body=None, token="tok", host=None):
        req = urllib.request.Request(
            base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-Downverse-Token": token, "Content-Type": "application/json"})
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers["Content-Type"].startswith("application/json") else raw)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw

    call.ctx, call.opened, call.base = ctx, opened, base
    yield call
    server.shutdown()


def wait(predicate, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_requires_token_and_local_host(api):
    assert api("GET", "/api/state", token="errado")[0] == 401
    assert api("GET", "/api/state", host="evil.example.com")[0] == 403
    assert api("GET", "/api/state")[0] == 200


def test_ui_is_served_with_security_headers(api):
    with urllib.request.urlopen(api.base + "/") as r:
        html = r.read().decode()
        assert "Downverse" in html
        assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert urllib.request.urlopen(api.base + "/app.js").status == 200
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(api.base + "/../server.py")
    assert e.value.code in (403, 404)


def test_parse_endpoint(api):
    ok = api("POST", "/api/parse", {"text": "https://weverse.io/lesserafim"})[1]
    assert ok["ok"] and ok["link"]["kind"] == "channel"
    bad = api("POST", "/api/parse", {"text": "https://example.com"})[1]
    assert not bad["ok"] and bad["error"]


def test_state_never_exposes_the_token(api):
    api("POST", "/api/settings", {"auth": {"method": "token", "refresh_token": "SEGREDO"}})
    status, state = api("GET", "/api/state")
    assert "SEGREDO" not in json.dumps(state)
    assert state["settings"]["auth"]["has_token"] is True
    # salvar outra opção sem mandar o token não apaga o token
    api("POST", "/api/settings", {"quality": "720", "auth": {"method": "token"}})
    assert api.ctx.settings.get()["auth"]["refresh_token"] == "SEGREDO"


def test_single_live_download_flow(api, core):
    status, res = api("POST", "/api/downloads", {"url": "https://weverse.io/taeyeon/live/2-100000001?hl=ko"})
    assert status == 200 and res["added"] == 1
    assert wait(lambda: api("GET", "/api/state")[1]["queue"]["counts"]["done"] == 1)
    state = api("GET", "/api/state")[1]
    assert state["library"]["count"] == 1 and sum(d["count"] for d in state["library"]["activity"]) == 1
    item = state["queue"]["items"][0]
    assert api("POST", "/api/open", {"target": "item", "id": item["id"]})[0] == 200
    assert api.opened and api.opened[0].endswith("2026-01-02")
    lib = api("GET", "/api/library")[1]["items"]
    assert lib[0]["exists"] and lib[0]["has_thumb"] and lib[0]["subtitles"] == 1
    status, raw = api("GET", f"/api/library/{lib[0]['id']}/thumb")
    assert status == 200 and raw[:3] == b"\xff\xd8\xff"          # JPEG
    assert api("POST", f"/api/library/{lib[0]['id']}/remove")[1]["ok"]


def test_channel_link_is_rejected_by_direct_download_and_vice_versa(api):
    assert "canal" in api("POST", "/api/downloads", {"url": "https://weverse.io/lesserafim"})[1]["error"]
    assert "específica" in api("POST", "/api/analyze", {"url": "https://weverse.io/lesserafim/live/2-100000003"})[1]["error"]


def test_channel_flow_with_selection(api):
    status, res = api("POST", "/api/analyze", {"url": "https://weverse.io/lesserafim"})
    aid = res["id"]
    assert wait(lambda: api("GET", f"/api/analysis/{aid}")[1]["status"] == "done")
    first = api("GET", f"/api/analysis/{aid}?since=0")[1]
    assert first["total"] == 4
    assert api("GET", f"/api/analysis/{aid}?since=3")[1]["entries"].__len__() == 1      # paginação incremental
    status, res = api("POST", "/api/downloads", {"analysis_id": aid, "ids": ["2-100000002", "2-100000005"]})
    assert res["added"] == 1                                                         # a ao vivo não entra
    assert wait(lambda: api("GET", "/api/state")[1]["queue"]["counts"]["done"] == 1)
    assert api("POST", "/api/downloads", {"analysis_id": aid, "ids": []})[0] == 400


def test_error_items_can_be_retried_and_cleared(api, core):
    api("POST", "/api/downloads", {"url": "https://weverse.io/taeyeon/live/2-100000009"})      # DRM
    assert wait(lambda: api("GET", "/api/state")[1]["queue"]["counts"]["error"] == 1)
    item = api("GET", "/api/state")[1]["queue"]["items"][0]
    assert "DRM" in item["error"]
    assert api("POST", f"/api/queue/{item['id']}/retry")[1]["ok"]
    assert wait(lambda: api("GET", "/api/state")[1]["queue"]["counts"]["error"] == 1)
    assert api("POST", "/api/queue/clear")[1]["removed"] == 1
    assert api("GET", "/api/state")[1]["queue"]["items"] == []
