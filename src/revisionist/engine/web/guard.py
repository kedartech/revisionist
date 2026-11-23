"""The request guard: response headers, the cookie line, the origin check and the body reader."""

from __future__ import annotations

import json
from collections.abc import Callable
from http import HTTPStatus
from typing import Any
from urllib.parse import urlsplit

COOKIE = "rv_session"
BODY_MAX = 64 * 1024

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)


class RefusedError(Exception):
    """A request the guard turns away, with the status and the words the caller sends."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def headers(handler: Any, status: HTTPStatus, kind: str, length: int) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", kind)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Content-Security-Policy", CSP)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("Cross-Origin-Opener-Policy", "same-origin")


def json_headers(handler: Any, status: HTTPStatus, length: int, cookie: str | None) -> None:
    headers(handler, status, "application/json; charset=utf-8", length)
    handler.send_header("Cache-Control", "no-store")
    if cookie is not None:
        handler.send_header("Set-Cookie", cookie)


def static_cache(suffix: str) -> str:
    return "no-cache" if suffix in (".html", ".js", ".css") else "max-age=86400"


def cookie(token: str, max_age: int, secure_cookie: bool) -> str:
    secure = "; Secure" if secure_cookie else ""
    return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"


def same_origin(request_headers: Any) -> None:
    """Writes must come from this page: a JSON body with our own Origin."""
    if not request_headers.get("Content-Type", "").startswith("application/json"):
        raise RefusedError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.")
    origin = request_headers.get("Origin")
    host = request_headers.get("Host", "")
    if origin is not None and urlsplit(origin).netloc != host:
        raise RefusedError(HTTPStatus.FORBIDDEN, "Cross-origin request refused.")


def body(
    request_headers: Any, rfile: Any, parse: Callable[[bytes], dict[str, Any]]
) -> dict[str, Any]:
    length = int(request_headers.get("Content-Length") or 0)
    if length > BODY_MAX:
        raise RefusedError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "That request is too large.")
    return parse(rfile.read(length) if length else b"")


def json_body(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise RefusedError(HTTPStatus.BAD_REQUEST, "That request was not valid JSON.") from None
    if not isinstance(parsed, dict):
        raise RefusedError(HTTPStatus.BAD_REQUEST, "Send a JSON object.")
    return parsed
