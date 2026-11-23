"""The guard and limits modules give what the server's own plumbing gives today."""

from __future__ import annotations

import io
import json
import threading
import time
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest

from revisionist.engine.web import guard, limits, server


class Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[Any, ...]] = []

    def send_response(self, status: HTTPStatus) -> None:
        self.sent.append(("status", status))

    def send_header(self, name: str, value: str) -> None:
        self.sent.append((name, value))

    def end_headers(self) -> None:
        self.sent.append(("end",))


def server_handler(secure: bool = False) -> Any:
    app = SimpleNamespace(secure_cookie=secure, static=None)
    cls: Any = server.make_handler(app)  # type: ignore[arg-type]
    handler = cls.__new__(cls)
    rec = Recorder()
    for attr, fn in (
        ("send_response", rec.send_response),
        ("send_header", rec.send_header),
        ("end_headers", rec.end_headers),
        ("rec", rec),
    ):
        setattr(handler, attr, fn)
    return handler


def outcome(call: Any) -> Any:
    try:
        return ("ok", call())
    except (server.ApiError, guard.RefusedError) as e:
        return ("err", e.status, e.message)


@pytest.mark.parametrize("status", [HTTPStatus.OK, HTTPStatus.NOT_FOUND])
@pytest.mark.parametrize("kind", ["text/html; charset=utf-8", "application/json"])
def test_headers_equal_the_servers(status: HTTPStatus, kind: str) -> None:
    ours, theirs = Recorder(), server_handler()
    guard.headers(ours, status, kind, 42)
    theirs._headers(status, kind, 42)
    assert ours.sent == theirs.rec.sent
    names = [s[0] for s in ours.sent]
    assert "Content-Security-Policy" in names and "Cross-Origin-Opener-Policy" in names


@pytest.mark.parametrize("cookie", [None, "rv_session=abc; Path=/"])
def test_json_headers_equal_send_json(cookie: str | None) -> None:
    theirs = server_handler()
    theirs.wfile = io.BytesIO()
    payload = {"a": "é"}
    theirs._send_json(HTTPStatus.OK, payload, cookie)
    raw = json.dumps(payload, ensure_ascii=False).encode()
    ours = Recorder()
    guard.json_headers(ours, HTTPStatus.OK, len(raw), cookie)
    ours.end_headers()
    assert ours.sent == theirs.rec.sent
    assert theirs.wfile.getvalue() == raw


@pytest.mark.parametrize("suffix", [".html", ".js", ".css", ".png", ".svg", ""])
def test_static_cache_values(suffix: str) -> None:
    assert guard.static_cache(suffix) == (
        "no-cache" if suffix in (".html", ".js", ".css") else "max-age=86400"
    )


def test_static_cache_equals_the_servers_static_reply(tmp_path: Any) -> None:
    for name in ("a.js", "b.png"):
        (tmp_path / name).write_bytes(b"x")
    app = SimpleNamespace(secure_cookie=False, static=tmp_path)
    cls: Any = server.make_handler(app)  # type: ignore[arg-type]
    for name in ("a.js", "b.png"):
        h = cls.__new__(cls)
        rec = Recorder()
        for attr, fn in (
            ("send_response", rec.send_response),
            ("send_header", rec.send_header),
            ("end_headers", rec.end_headers),
        ):
            setattr(h, attr, fn)
        h.wfile = io.BytesIO()
        h._static(f"/{name}")
        cache = next(v[0] for n, *v in rec.sent if n == "Cache-Control")
        assert cache == guard.static_cache("." + name.split(".")[1])


@pytest.mark.parametrize("secure", [False, True])
@pytest.mark.parametrize("token,age", [("t0k", 3600), ("", 0)])
def test_cookie_equals_the_servers(secure: bool, token: str, age: int) -> None:
    assert guard.cookie(token, age, secure) == server_handler(secure)._cookie(token, age)


ORIGIN_CASES = [
    {},
    {"Content-Type": "text/plain"},
    {"Content-Type": "application/json"},
    {
        "Content-Type": "application/json; charset=utf-8",
        "Host": "a.test",
        "Origin": "http://a.test",
    },
    {"Content-Type": "application/json", "Host": "a.test", "Origin": "http://b.test"},
    {"Content-Type": "application/json", "Host": "a.test"},
    {"Content-Type": "application/json", "Host": "", "Origin": "http://a.test"},
]


@pytest.mark.parametrize("hdrs", ORIGIN_CASES)
def test_same_origin_equals_the_servers(hdrs: dict[str, str]) -> None:
    theirs = server_handler()
    theirs.headers = hdrs
    want = outcome(theirs._same_origin)
    got = outcome(lambda: guard.same_origin(hdrs))
    assert got == want


BODIES = [
    (b"", None),
    (b"{}", None),
    (b'{"a": 1}', None),
    (b"[1]", None),
    (b"nope", None),
    (b"x" * (guard.BODY_MAX + 1), None),
    (b"{}", str(guard.BODY_MAX + 1)),
    (b"{}", "0"),
]


@pytest.mark.parametrize("raw,length", BODIES)
def test_body_equals_the_servers(raw: bytes, length: str | None) -> None:
    hdrs = {"Content-Length": length if length is not None else str(len(raw))}
    theirs = server_handler()
    theirs.headers, theirs.rfile = hdrs, io.BytesIO(raw)
    want = outcome(theirs._body)
    got = outcome(lambda: guard.body(hdrs, io.BytesIO(raw), guard.json_body))
    assert got == want


def test_body_limit_is_the_servers() -> None:
    assert guard.BODY_MAX == server.BODY_MAX == 64 * 1024
    assert guard.COOKIE == server.COOKIE
    assert guard.CSP == server.CSP


def test_signin_throttle_equals_the_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    theirs = server.App.__new__(server.App)
    theirs._lock, theirs._failures = threading.Lock(), {}
    ours = limits.SigninThrottle()
    assert limits.SIGNIN_TRIES == server.SIGNIN_TRIES == 10
    for i in range(12):
        assert ours.throttled(" Ann ") == theirs.throttled("ann") == (i >= 10)
        ours.failed(" Ann ")
        theirs.failed("ANN")
        clock[0] += 1
    assert ours.throttled("bob") is theirs.throttled("bob") is False
    clock[0] += 899
    assert ours.throttled("ann") == theirs.throttled("ann")
    clock[0] += 20
    assert ours.throttled("ann") is theirs.throttled("ann") is False


def test_signin_throttle_trips_at_exactly_ten() -> None:
    t = limits.SigninThrottle()
    for _ in range(limits.SIGNIN_TRIES - 1):
        t.failed("x")
    assert not t.throttled("x")
    t.failed("x")
    assert t.throttled("x")


def test_check_and_address_return_nothing_yet() -> None:
    assert limits.check(None, "a", "c", "act", None) is None
    assert limits.address(object(), "signin") is None


def test_a_refusal_is_a_value_with_refused_true() -> None:
    reply = limits.Refusal("Slow down.").reply()
    assert reply == {"refused": True, "message": "Slow down."}
    assert not isinstance(limits.Refusal("x"), BaseException)
