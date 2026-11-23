"""The request guard: response headers, the cookie line, the origin check and the body reader."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable
from http import HTTPStatus
from typing import Any
from urllib.parse import urlsplit

COOKIE = "rv_session"
BODY_MAX = 64 * 1024
IDLE_S = 30
"""[proposed] Seconds a connection may send nothing before it is closed."""

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'; manifest-src 'self'; worker-src 'self'"
)
HSTS = "max-age=31536000"
"""[proposed] Sent only when the server is told it sits behind HTTPS; no subdomains, no preload."""
PERMISSIONS = ", ".join(
    f"{feature}=()"
    for feature in (
        "accelerometer",
        "ambient-light-sensor",
        "autoplay",
        "battery",
        "bluetooth",
        "camera",
        "display-capture",
        "encrypted-media",
        "geolocation",
        "gyroscope",
        "hid",
        "idle-detection",
        "magnetometer",
        "microphone",
        "midi",
        "payment",
        "picture-in-picture",
        "publickey-credentials-get",
        "screen-wake-lock",
        "serial",
        "usb",
        "xr-spatial-tracking",
    )
)
"""Every feature the client does not use, granted to nobody. Full screen and writing to the
clipboard are left out: the room's own page uses them, and unlisted they reach no other origin."""


class RefusedError(Exception):
    """A request the guard turns away, with the status and the words the caller sends."""

    def __init__(self, status: HTTPStatus, message: str, *, close: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.close = close
        """The body was left unread, so the connection cannot carry another request."""


def headers(handler: Any, status: HTTPStatus, kind: str, length: int) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", kind)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Content-Security-Policy", CSP)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("Cross-Origin-Opener-Policy", "same-origin")
    handler.send_header("Cross-Origin-Resource-Policy", "same-origin")
    handler.send_header("Permissions-Policy", PERMISSIONS)
    if getattr(handler, "secure", False) is True:
        handler.send_header("Strict-Transport-Security", HSTS)
    if getattr(handler, "closing", False) is True:
        handler.send_header("Connection", "close")


def json_headers(handler: Any, status: HTTPStatus, length: int, cookie: str | None) -> None:
    headers(handler, status, "application/json; charset=utf-8", length)
    handler.send_header("Cache-Control", "no-store")
    if cookie is not None:
        handler.send_header("Set-Cookie", cookie)


def static_cache(suffix: str) -> str:
    return "no-cache" if suffix in (".html", ".js", ".css") else "max-age=86400"


def static_headers(handler: Any, status: HTTPStatus, kind: str, length: int, suffix: str) -> None:
    headers(handler, status, kind, length)
    handler.send_header("Cache-Control", static_cache(suffix))


def cookie(token: str, max_age: int, secure_cookie: bool) -> str:
    secure = "; Secure" if secure_cookie else ""
    return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"


def closing(handler: Any, refusal: Exception) -> None:
    """After a refusal that left the body unread, this reply is the connection's last."""
    if getattr(refusal, "close", False) is True:
        handler.closing = True
        handler.close_connection = True


def start_warning(host: str, secure: bool) -> str | None:
    """The one line ``web serve`` prints when it binds beyond this machine without HTTPS."""
    if secure:
        return None
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host.lower() == "localhost"
    if local:
        return None
    return (
        f"warning: serving on {host} without --secure-cookie: the session cookie can travel"
        " unencrypted and no Strict-Transport-Security is sent; put HTTPS in front and pass"
        " --secure-cookie"
    )


def same_origin(request_headers: Any) -> None:
    """Writes must come from this page: a JSON body whose Origin, or else Referer, is this host."""
    if not request_headers.get("Content-Type", "").startswith("application/json"):
        raise RefusedError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.")
    origin = request_headers.get("Origin")
    named = origin if origin is not None else request_headers.get("Referer")
    host = request_headers.get("Host", "")
    if not host or named is None or urlsplit(named).netloc != host:
        raise RefusedError(HTTPStatus.FORBIDDEN, "Cross-origin request refused.")


def body(
    request_headers: Any, rfile: Any, parse: Callable[[bytes], dict[str, Any]]
) -> dict[str, Any]:
    given = request_headers.get("Content-Length") or "0"
    if not (given.isascii() and given.isdigit()):
        raise RefusedError(
            HTTPStatus.BAD_REQUEST, "That request's length is not a number.", close=True
        )
    length = int(given)
    if length > BODY_MAX:
        raise RefusedError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "That request is too large.", close=True
        )
    try:
        raw = rfile.read(length) if length else b""
    except TimeoutError:
        raise RefusedError(
            HTTPStatus.REQUEST_TIMEOUT, "That request stalled.", close=True
        ) from None
    return parse(raw)


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
