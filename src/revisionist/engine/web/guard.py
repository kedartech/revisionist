"""The request guard: response headers, the cookie line, the origin check and the body reader."""

from __future__ import annotations

import gzip
import ipaddress
import json
import os
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

COOKIE = "rv_session"
BODY_MAX = 64 * 1024
GZIP_MIN = 1024
"""A reply over this many bytes is sent gzip-compressed to a client that accepts it. [proposed]"""
MAP_CACHE = "private, max-age=31536000, immutable"
"""A map object is named by its hash, so a client keeps it a year. [proposed]"""
ASSETLINKS_ENV = "REVISIONIST_ASSETLINKS_FILE"
PUBLIC_NAMES_ENV = "REVISIONIST_PUBLIC_NAMES"
"""The names the server is served under, comma separated, each a host or host:port."""
MISDIRECTED = "This server does not answer to that name."
LOCAL_SUFFIX = ".ts.net"
"""[proposed] With no names set, a write must name an IP address, localhost or a tailnet name."""
MANIFEST_TYPE = "application/manifest+json"
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


def accepts_gzip(request_headers: Any) -> bool:
    if request_headers is None:
        return False
    for part in request_headers.get("Accept-Encoding", "").split(","):
        name, _, params = part.partition(";")
        if name.strip().lower() in ("gzip", "x-gzip"):
            quality = params.strip().lower().removeprefix("q=") if "q=" in params else "1"
            try:
                return float(quality) > 0
            except ValueError:
                return False
    return False


def compress(handler: Any, data: bytes) -> tuple[bytes, bool]:
    """The bytes to send and whether they are gzipped: only a reply over ``GZIP_MIN``
    bytes, only to a handler whose request accepts gzip."""
    if len(data) > GZIP_MIN and accepts_gzip(getattr(handler, "headers", None)):
        return gzip.compress(data, mtime=0), True
    return data, False


def headers(handler: Any, status: HTTPStatus, kind: str, length: int, zipped: bool = False) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", kind)
    handler.send_header("Content-Length", str(length))
    if zipped:
        handler.send_header("Content-Encoding", "gzip")
        handler.send_header("Vary", "Accept-Encoding")
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


def json_headers(
    handler: Any, status: HTTPStatus, length: int, cookie: str | None, zipped: bool = False
) -> None:
    headers(handler, status, "application/json; charset=utf-8", length, zipped)
    handler.send_header("Cache-Control", "no-store")
    if cookie is not None:
        handler.send_header("Set-Cookie", cookie)


def static_cache(suffix: str) -> str:
    return "no-cache" if suffix in (".html", ".js", ".css") else "max-age=86400"


def static_headers(
    handler: Any,
    status: HTTPStatus,
    kind: str,
    length: int,
    suffix: str,
    zipped: bool = False,
    worker: bool = False,
) -> None:
    headers(handler, status, kind, length, zipped)
    handler.send_header("Cache-Control", static_cache(suffix))
    if worker:
        handler.send_header("Service-Worker-Allowed", "/")


def map_headers(handler: Any, length: int, zipped: bool = False) -> None:
    headers(handler, HTTPStatus.OK, "application/json; charset=utf-8", length, zipped)
    handler.send_header("Cache-Control", MAP_CACHE)


def assetlinks() -> bytes | None:
    """The file ``REVISIONIST_ASSETLINKS_FILE`` names, or None when unset or unreadable."""
    named = os.environ.get(ASSETLINKS_ENV)
    if not named:
        return None
    try:
        return Path(named).read_bytes()
    except OSError:
        return None


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


def public_names() -> list[tuple[str, int | None]]:
    """The names ``REVISIONIST_PUBLIC_NAMES`` lists, read afresh on every call."""
    found = []
    for entry in os.environ.get(PUBLIC_NAMES_ENV, "").split(","):
        if entry.strip():
            found.append(_split(entry.strip()))
    return [name for name in found if name[0]]


def _split(netloc: str) -> tuple[str, int | None]:
    """A host header or netloc as its lower-case host and its port; no host when malformed."""
    if "@" in netloc:
        return "", None
    try:
        parts = urlsplit("//" + netloc)
        return parts.hostname or "", parts.port
    except ValueError:
        return "", None


def _listed(netloc: str, names: list[tuple[str, int | None]]) -> bool:
    host, port = _split(netloc)
    return bool(host) and any(host == name and want in (None, port) for name, want in names)


def _local(netloc: str) -> bool:
    host = _split(netloc)[0]
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or host.endswith(LOCAL_SUFFIX)
    return True


def _netloc(url: str) -> str:
    try:
        return urlsplit(url).netloc
    except ValueError:
        return ""


def served(request_headers: Any) -> None:
    """Any request, of any method: when names are set, its Host must be one of them."""
    names = public_names()
    if names and not _listed(request_headers.get("Host", ""), names):
        raise RefusedError(HTTPStatus.MISDIRECTED_REQUEST, MISDIRECTED)


def same_origin(request_headers: Any) -> None:
    """Writes must come from this page: a JSON body whose Origin, or else Referer, is a name
    the server is served under; with no names set, this host, if it is not a borrowed name."""
    served(request_headers)
    if not request_headers.get("Content-Type", "").startswith("application/json"):
        raise RefusedError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.")
    origin = request_headers.get("Origin")
    named = origin if origin is not None else request_headers.get("Referer")
    host = request_headers.get("Host", "")
    if not host or named is None:
        raise RefusedError(HTTPStatus.FORBIDDEN, "Cross-origin request refused.")
    names = public_names()
    if names:
        if not _listed(_netloc(named), names):
            raise RefusedError(HTTPStatus.FORBIDDEN, "Cross-origin request refused.")
        return
    if not _local(host):
        raise RefusedError(HTTPStatus.MISDIRECTED_REQUEST, MISDIRECTED)
    if _netloc(named) != host:
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
