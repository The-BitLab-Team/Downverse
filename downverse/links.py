"""Tratamento e normalização dos links do Weverse.

O usuário pode colar praticamente qualquer coisa: o link da página inicial do
canal, da aba de lives, de uma live específica, com ou sem ``https://``, com
parâmetros de rastreio (``?hl=ko``), com texto em volta, etc. Aqui tudo isso vira
um ``WeverseLink`` com uma URL canônica que o yt-dlp entende.

Regras:
* link de uma live (``/artista/live/2-123456``)      -> uma live específica;
* link do canal, da aba de lives ou de qualquer aba -> todas as lives do canal;
* links que não dá para baixar (Moments, loja, etc.) -> ``LinkError`` com uma
  mensagem em português dizendo o que fazer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

KIND_LIVE = "live"
KIND_CHANNEL = "channel"

HOST = "weverse.io"
# subdomínios que apontam para o mesmo site
_ALLOWED_SUBDOMAINS = {"", "www", "m"}

# 1º segmento do caminho que NÃO é o nome de um canal
_RESERVED_SLUGS = {
    "more", "live", "discover", "home", "shop", "notice", "notifications", "search",
    "setting", "settings", "policy", "terms", "privacy", "login", "signin", "signup",
    "join", "my", "dm", "api", "static", "artist", "feed", "media", "moment", "highlight",
    "fan", "membership", "ko", "en", "ja", "index.html", "favicon.ico", "robots.txt",
}

# prefixos de idioma que algumas URLs do site têm antes do nome do canal
_LOCALE_PREFIXES = {"ko", "en", "ja", "zh-cn", "zh-tw", "es", "id", "th", "vi"}

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
# IDs de post do Weverse: "2-102331763", "0-107323480", ...
_POST_ID_RE = re.compile(r"^\d+-\d+$")

# acha algo parecido com um link do Weverse no meio de um texto qualquer
_FIND_RE = re.compile(
    r"(?<![\w.-])(?:https?://)?(?:[a-z0-9-]+\.)*weverse\.io(?:[/?#][^\s<>\"'«»“”]*)?",
    re.IGNORECASE,
)
_TRAILING_JUNK = ".,;:!)]}>'\"”"


class LinkError(ValueError):
    """Link inválido ou sem suporte. A mensagem já é pensada para o usuário final."""


@dataclass(frozen=True)
class WeverseLink:
    kind: str                 # KIND_LIVE | KIND_CHANNEL
    community: str            # código do canal na URL (ex.: "lesserafim")
    post_id: str | None       # só para KIND_LIVE
    url: str                  # URL canônica entendida pelo yt-dlp
    note: str = ""            # aviso opcional sobre como o link foi interpretado

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "community": self.community,
            "post_id": self.post_id,
            "url": self.url,
            "note": self.note,
        }


def _clean_candidate(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise LinkError("Cole o link de uma live ou do canal do artista/grupo no Weverse.")

    if "onelink.me" in text.lower() and HOST not in text.lower().replace("onelink.me", ""):
        raise LinkError(
            "Esse é um link curto de compartilhamento do app. Abra-o no navegador e "
            "copie o endereço que aparece na barra (começa com weverse.io/)."
        )

    matches = _FIND_RE.findall(text)
    if not matches:
        raise LinkError(
            "Isso não parece um link do Weverse. Use algo como "
            "weverse.io/artista/live ou weverse.io/artista/live/2-123456789."
        )
    return matches[0].rstrip(_TRAILING_JUNK)


def parse_link(text: str) -> WeverseLink:
    """Interpreta o que o usuário colou e devolve um ``WeverseLink`` normalizado."""
    raw = _clean_candidate(text)
    extra = ""
    if len({m.rstrip(_TRAILING_JUNK).lower() for m in _FIND_RE.findall(text)}) > 1:
        extra = "Você colou mais de um link; usando o primeiro. "

    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = "https://" + raw
    parts = urlsplit(raw)

    host = (parts.hostname or "").lower()
    if host != HOST and not host.endswith("." + HOST):
        raise LinkError("Esse link não é do weverse.io.")
    sub = host[: -len(HOST)].rstrip(".") if host != HOST else ""
    if sub not in _ALLOWED_SUBDOMAINS:
        raise LinkError(
            f"Links de {host} (loja, conta etc.) não têm vídeos para baixar. "
            "Use o link de uma live ou do canal em weverse.io."
        )

    segs = [unquote(s).strip() for s in parts.path.split("/") if s.strip()]
    if not segs:
        raise LinkError(
            "Faltou o nome do artista/grupo no link. Abra o canal dele no Weverse e "
            "copie o endereço (ex.: weverse.io/lesserafim)."
        )

    if len(segs) > 1 and segs[0].lower() in _LOCALE_PREFIXES:
        segs = segs[1:]

    slug = segs[0].lower()
    if slug in _RESERVED_SLUGS or not _SLUG_RE.match(slug):
        raise LinkError(
            "Não consegui identificar o artista/grupo nesse link. Abra o canal dele no "
            "Weverse e copie o endereço (ex.: weverse.io/lesserafim)."
        )

    rest = segs[1:]
    base = f"https://{HOST}/{slug}"

    # --- canal inteiro --------------------------------------------------------
    if not rest:
        return WeverseLink(
            KIND_CHANNEL, slug, None, f"{base}/live",
            note=extra + "Link do canal: vamos listar todas as lives dele.",
        )

    tab = rest[0].lower()
    post_id = next((s for s in rest[1:] if _POST_ID_RE.match(s)), None)

    if tab == "live":
        if len(rest) == 1:
            return WeverseLink(KIND_CHANNEL, slug, None, f"{base}/live", note=extra)
        if _POST_ID_RE.match(rest[1]):
            return WeverseLink(KIND_LIVE, slug, rest[1], f"{base}/live/{rest[1]}", note=extra)
        return WeverseLink(
            KIND_CHANNEL, slug, None, f"{base}/live",
            note=extra + "Usando a página de lives do canal.",
        )

    if tab == "moment":
        raise LinkError(
            "Moments não são suportados. Use o link de uma live (…/live/ID) "
            "ou da página de lives do canal."
        )

    if post_id is None:
        # qualquer outra aba do canal (feed, artist, media, highlight...) -> lives do canal
        return WeverseLink(
            KIND_CHANNEL, slug, None, f"{base}/live",
            note=extra + f"Link da aba “{tab}”: vamos listar as lives do canal.",
        )

    if tab == "media":
        return WeverseLink(KIND_LIVE, slug, post_id, f"{base}/media/{post_id}", note=extra)

    # publicação de outra aba que pode ser um vídeo: tenta como live
    return WeverseLink(
        KIND_LIVE, slug, post_id, f"{base}/live/{post_id}",
        note=extra + "Link de uma publicação; tentando baixar como live.",
    )
