"""Weverse falso para testes offline.

Em vez de reimplementar o extrator, a gente substitui só a camada de rede do
``WeverseBaseIE`` do yt-dlp: as chamadas da API do Weverse viram JSONs montados
aqui (com o mesmo formato que o extrator espera) e os vídeos/legendas/thumbnails
são servidos por um servidor HTTP local. Assim o código real do extrator roda.
"""
from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from yt_dlp.extractor import weverse as wv

HEIGHTS = (144, 360, 720)


def _ms(year, month, day, hour=12, minute=0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


# slug -> comunidade
COMMUNITIES = {
    "lesserafim": {"id": 47, "name": "LE SSERAFIM"},
    "taeyeon": {"id": 12, "name": "TAEYEON"},
}

# postId -> dados da live
POSTS = [
    # live de um membro do grupo
    dict(id="2-100000003", slug="lesserafim", author="채원", title="Live de domingo 💜",
         at=_ms(2026, 3, 15, 12), subs=["ko_KR", "en_US", "pt_BR"], kind="vod"),
    # live da conta oficial do grupo (perfil com espaço no final, como no Weverse real)
    dict(id="2-100000002", slug="lesserafim", author="LE SSERAFIM ", title="Comeback talk",
         at=_ms(2026, 3, 10, 12), subs=["ko_KR", "en_US"], kind="vod"),
    # outra live do mesmo membro no mesmo dia da primeira
    dict(id="2-100000004", slug="lesserafim", author="채원", title="Segunda live do dia",
         at=_ms(2026, 3, 15, 15), subs=["ko_KR"], kind="vod"),
    # ao vivo agora (não baixável)
    dict(id="2-100000005", slug="lesserafim", author="사쿠라", title="Ao vivo!",
         at=_ms(2026, 3, 16, 12), subs=[], kind="onair"),
    # artista solo, perfil com mesmo nome do canal
    dict(id="2-100000001", slug="taeyeon", author="TAEYEON", title="Hello / Olá: 안녕?",
         at=_ms(2026, 1, 2, 3), subs=["ko_KR"], kind="vod"),
    # protegida por DRM
    dict(id="2-100000009", slug="taeyeon", author="TAEYEON", title="Conteúdo DRM",
         at=_ms(2026, 1, 3, 3), subs=[], kind="vod", drm=True),
]


def post_by_id(post_id: str) -> dict:
    for p in POSTS:
        if p["id"] == post_id:
            return p
    raise KeyError(post_id)


class MediaServer:
    """Gera mp4/vtt/ttml/png pequenos e serve por HTTP em 127.0.0.1."""

    def __init__(self, root: Path, throttle: float = 0.0):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._build_media()
        _QuietHandler.throttle = throttle
        handler = partial(_QuietHandler, directory=str(root))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.port}/{name}"

    def _build_media(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        for h in HEIGHTS:
            w = h * 16 // 9 // 2 * 2
            out = self.root / f"vod_{h}.mp4"
            if not out.exists():
                subprocess.run([
                    ffmpeg, "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=10:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(out)], check=True)
        thumb = self.root / "thumb.png"
        if not thumb.exists():
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc=size=320x180:rate=1:duration=1", "-frames:v", "1", str(thumb)], check=True)
        for loc in ("ko_KR", "en_US", "pt_BR"):
            (self.root / f"cap_{loc}.vtt").write_text(
                f"WEBVTT\n\n00:00:00.500 --> 00:00:02.000\nLegenda {loc}\n", encoding="utf-8")
            (self.root / f"cap_{loc}.ttml").write_text(
                '<?xml version="1.0" encoding="utf-8"?><tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
                f'<p begin="00:00:00.500" end="00:00:02.000">Legenda {loc}</p></div></body></tt>', encoding="utf-8")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    throttle = 0.0   # segundos de espera a cada 4 KB (deixa o progresso visível nas demos)

    ranges: list = []  # cabeçalhos Range recebidos (os testes de retomada conferem)

    def log_message(self, *a, **k):
        pass

    def send_head(self):
        rng = self.headers.get("Range")
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", rng or "")
        path = self.translate_path(self.path)
        if not m or not os.path.isfile(path):
            return super().send_head()
        type(self).ranges.append(rng)
        size = os.path.getsize(path)
        start = int(m.group(1))
        end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
        if start >= size:
            self.send_error(416)
            return None
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        if not self.throttle:
            return super().copyfile(source, outputfile)
        import time
        while chunk := source.read(4096):
            outputfile.write(chunk)
            time.sleep(self.throttle)


def _post_json(p: dict, media: MediaServer) -> dict:
    c = COMMUNITIES[p["slug"]]
    onair = p["kind"] == "onair"
    video = {
        "videoId": int(p["id"].split("-")[1]),
        "infraVideoId": "infra-" + p["id"],
        "serviceId": "2070",
        "playTime": 3,
        "onAirStartAt": p["at"],
        "thumb": media.url("thumb.png"),
        "playCount": 10,
        "likeCount": 2,
        "paid": False,
        "membershipOnly": False,
    }
    if onair:
        video.update(type="LIVE", status="ONAIR")
    else:
        video.update(type="VOD", liveToVod=True)
    return {
        "postId": p["id"],
        "publishedAt": p["at"] + 5000,
        "title": p["title"],
        "body": "",
        "author": {"profileName": p["author"], "memberId": "m-" + p["author"], "communityId": c["id"],
                   "profileImageUrl": media.url("thumb.png")},
        "community": {"communityName": c["name"], "communityId": c["id"]},
        "commentCount": 0,
        "extension": {"video": video},
    }


def _vod_json(p: dict, media: MediaServer) -> dict:
    return {
        "meta": {"provider": {"name": "drm" if p.get("drm") else "naver"}},
        "videos": {"list": [{
            "source": media.url(f"vod_{h}.mp4"),
            "encodingOption": {"width": h * 16 // 9 // 2 * 2, "height": h, "id": f"{h}P"},
            "type": "AVC1",
            "bitrate": {"video": 100 * h, "audio": 64},
            "size": 1000 * h,
        } for h in HEIGHTS]},
        "captions": {"list": [{
            "source": media.url(f"cap_{loc}.vtt"), "locale": loc, "label": loc, "type": "direct",
        } for loc in p["subs"]]},
    }


class FakeWeverse:
    """Instala/desinstala os patches no extrator do yt-dlp."""

    def __init__(self, media: MediaServer, page_size: int = 2):
        self.media = media
        self.page_size = page_size
        self.calls: list[str] = []
        self._orig: dict = {}

    def install(self):
        base = wv.WeverseBaseIE
        fake = self

        def _call_api(self, ep, video_id, data=None, note=None):
            fake.calls.append(ep)
            return fake._api(ep)

        orig_dl = base._download_json

        def _download_json(self, url_or_request, video_id, *a, **kw):
            url = url_or_request if isinstance(url_or_request, str) else url_or_request.url
            m = re.search(r"/vod/play/v2\.0/infra-(\S+?)(?:\?|$)", url)
            if m:
                fake.calls.append("vod:" + m.group(1))
                return _vod_json(post_by_id(m.group(1)), fake.media)
            return orig_dl(self, url_or_request, video_id, *a, **kw)

        for name, new in (("_call_api", _call_api), ("_download_json", _download_json),
                          ("_real_initialize", lambda self: None)):
            self._orig[name] = getattr(base, name)
            setattr(base, name, new)
        return self

    def uninstall(self):
        for name, fn in self._orig.items():
            setattr(wv.WeverseBaseIE, name, fn)

    # -- respostas da "API" ----------------------------------------------------------
    def _api(self, ep: str):
        m = re.search(r"keyword=([\w.-]+)", ep)
        if "communityIdUrlPathByUrlPathArtistCode" in ep and m:
            slug = m.group(1)
            if slug not in COMMUNITIES:
                raise wv.ExtractorError("Canal inexistente", expected=True)
            return {"communityId": COMMUNITIES[slug]["id"]}

        m = re.search(r"/post-([\d-]+)", ep)
        if m:
            return _post_json(post_by_id(m.group(1)), self.media)

        if "/inKey" in ep:
            return {"inKey": "fake-key"}

        m = re.search(r"community-(\d+)/liveTabPosts", ep)
        if m:
            cid = int(m.group(1))
            slug = next(s for s, c in COMMUNITIES.items() if c["id"] == cid)
            posts = sorted((p for p in POSTS if p["slug"] == slug), key=lambda p: -p["at"])
            after = re.search(r"after=(\d+)", ep)
            start = int(after.group(1)) if after else 0
            page = posts[start:start + self.page_size]
            nxt = start + self.page_size
            return {
                "data": [_post_json(p, self.media) for p in page],
                "paging": {"nextParams": {"after": str(nxt)} if nxt < len(posts) else {}},
            }

        raise AssertionError(f"endpoint não simulado: {ep}")
