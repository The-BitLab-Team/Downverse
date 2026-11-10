"""Apoio ao login no Weverse: limpeza do que o usuário cola e preparo do arquivo de cookies.

O yt-dlp só aceita cookies no formato Netscape, com cabeçalho. Na prática as pessoas chegam com
um JSON (extensões Cookie-Editor / EditThisCookie), com um arquivo sem cabeçalho ou com o caminho
entre aspas ("Copiar como caminho" do Windows). Este módulo aceita todos esses casos.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

NETSCAPE_HEADER = "# Netscape HTTP Cookie File"
TOKEN_COOKIES = ("we2_access_token", "we2_refresh_token")
_QUOTES = "\"'“”‘’`"


class AuthError(Exception):
    """Problema de login com mensagem pronta para o usuário."""


def clean_path(text: object) -> str:
    """Tira espaços e aspas em volta de um caminho colado."""
    return str(text or "").strip().strip(_QUOTES).strip()


def clean_token(text: object) -> str:
    """Aceita o token puro, entre aspas ou no formato ``we2_refresh_token=...;``."""
    value = str(text or "").strip().strip(_QUOTES).strip()
    match = re.search(r"we2_refresh_token\s*[=:]\s*[\"']?([\w.\-]+)", value)
    if match:
        return match.group(1)
    return re.sub(r"\s+", "", value).rstrip(";")


def _netscape_line(domain: str, name: str, value: str, path: str = "/", secure: bool = True,
                   expires: object = None, host_only: bool = False) -> str:
    domain = domain.strip()
    if not host_only and not domain.startswith("."):
        domain = "." + domain
    try:
        exp = str(int(float(expires))) if expires else "0"
    except (TypeError, ValueError):
        exp = "0"
    flag = "FALSE" if host_only else "TRUE"
    return "\t".join([domain, flag, path or "/", "TRUE" if secure else "FALSE", exp, name, value])


def _from_json(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AuthError("O arquivo de cookies parece um JSON, mas está incompleto ou corrompido. Exporte de novo.") from exc
    if isinstance(data, dict):
        data = data.get("cookies") if isinstance(data.get("cookies"), list) else [data]
    lines = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not item.get("name") or not item.get("domain"):
            continue
        lines.append(_netscape_line(
            str(item["domain"]), str(item["name"]), str(item.get("value", "")), str(item.get("path") or "/"),
            bool(item.get("secure", True)), item.get("expirationDate") or item.get("expires"),
            bool(item.get("hostOnly", False))))
    return lines


def _from_text(text: str) -> list[str]:
    """Linhas de cookie de um arquivo Netscape (com ou sem cabeçalho, tabs ou espaços)."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        http_only = line.startswith("#HttpOnly_")
        if not line or (line.startswith("#") and not http_only):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            parts = line.split(None, 6)
        if len(parts) == 6:      # valor vazio
            parts.append("")
        if len(parts) == 7 and parts[1].strip().upper() in ("TRUE", "FALSE") and parts[3].strip().upper() in ("TRUE", "FALSE"):
            lines.append("\t".join(p.strip() for p in parts))
    return lines


def prepare_cookie_file(source: str, work_dir: Path) -> str:
    """Devolve um arquivo de cookies que o yt-dlp consegue ler.

    Trabalha sempre numa cópia dentro de ``work_dir``: o original do usuário nunca é alterado e os
    tokens renovados pelo Weverse ficam guardados na cópia. A cópia só é refeita quando o original
    é mais novo que ela (ou seja, quando o usuário exportou os cookies de novo).
    """
    path = Path(clean_path(source)).expanduser()
    if not clean_path(source):
        raise AuthError("Indique o arquivo de cookies (cookies.txt).")
    if path.is_dir():
        raise AuthError("Esse caminho é uma pasta. Indique o arquivo de cookies dentro dela.")
    if not path.is_file():
        raise AuthError(f"Arquivo de cookies não encontrado: {path}")

    work_dir.mkdir(parents=True, exist_ok=True)
    copy = work_dir / "cookies-weverse.txt"
    marker = work_dir / "cookies-weverse.origem"
    try:
        same_source = marker.read_text(encoding="utf-8") == str(path.resolve())
        if same_source and copy.is_file() and copy.stat().st_mtime >= path.stat().st_mtime:
            return str(copy)
    except OSError:
        pass

    try:
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
    except OSError as exc:
        raise AuthError(f"Não consegui abrir o arquivo de cookies: {exc.strerror or exc}") from exc
    stripped = text.lstrip()
    lines = _from_json(stripped) if stripped[:1] in ("[", "{") else _from_text(text)
    if not lines:
        raise AuthError(
            "Esse arquivo não tem cookies que eu consiga ler. Exporte os cookies do weverse.io com uma "
            "extensão como “Get cookies.txt LOCALLY” (formato Netscape) ou “Cookie-Editor” (JSON).")
    weverse = [ln for ln in lines if "weverse.io" in ln.split("\t")[0].lstrip("#HttpOnly_")]
    if not any(ln.split("\t")[5] in TOKEN_COOKIES for ln in weverse):
        raise AuthError(
            "O arquivo não tem a sessão do Weverse (cookies we2_access_token / we2_refresh_token). "
            "Entre em weverse.io, exporte os cookies com a página do Weverse aberta e tente de novo.")

    copy.write_text(NETSCAPE_HEADER + "\n\n" + "\n".join(weverse) + "\n", encoding="utf-8")
    marker.write_text(str(path.resolve()), encoding="utf-8")
    try:
        copy.chmod(0o600)
    except OSError:
        pass
    return str(copy)
