"""The guard and limits modules give what the server's own plumbing gives today."""

from __future__ import annotations

import io
import json
import time
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest

from revisionist.engine.web import guard, limits, server

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'; manifest-src 'self'; worker-src 'self'"
)


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
    except guard.RefusedError as e:
        return ("err", e.status, e.message)


@pytest.mark.parametrize("status", [HTTPStatus.OK, HTTPStatus.NOT_FOUND])
@pytest.mark.parametrize("kind", ["text/html; charset=utf-8", "application/json"])
def test_headers_equal_the_servers(status: HTTPStatus, kind: str) -> None:
    ours = Recorder()
    guard.headers(ours, status, kind, 42)
    assert ours.sent == [
        ("status", status),
        ("Content-Type", kind),
        ("Content-Length", "42"),
        ("Content-Security-Policy", CSP),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("Cross-Origin-Opener-Policy", "same-origin"),
        ("Cross-Origin-Resource-Policy", "same-origin"),
        ("Permissions-Policy", guard.PERMISSIONS),
    ]
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
    tail = "; Secure" if secure else ""
    want = f"rv_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}{tail}"
    assert guard.cookie(token, age, secure) == want


SEND_JSON = ("err", HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.")
CROSS = ("err", HTTPStatus.FORBIDDEN, "Cross-origin request refused.")
ORIGIN_CASES: list[tuple[dict[str, str], Any]] = [
    ({}, SEND_JSON),
    ({"Content-Type": "text/plain"}, SEND_JSON),
    ({"Content-Type": "application/json"}, CROSS),
    (
        {
            "Content-Type": "application/json; charset=utf-8",
            "Host": "a.ts.net",
            "Origin": "http://a.ts.net",
        },
        ("ok", None),
    ),
    ({"Content-Type": "application/json", "Host": "a.ts.net", "Origin": "http://b.ts.net"}, CROSS),
    ({"Content-Type": "application/json", "Host": "a.ts.net"}, CROSS),
    ({"Content-Type": "application/json", "Host": "", "Origin": "http://a.ts.net"}, CROSS),
]


@pytest.fixture(autouse=True)
def _no_public_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PUBLIC_NAMES, raising=False)


@pytest.mark.parametrize("hdrs,want", ORIGIN_CASES)
def test_same_origin_equals_the_servers(hdrs: dict[str, str], want: Any) -> None:
    assert outcome(lambda: guard.same_origin(hdrs)) == want


MISDIRECTED = ("err", HTTPStatus.MISDIRECTED_REQUEST, "This server does not answer to that name.")
TAILNET = "rv.tailf1d7f1.ts.net"
PUBLIC_NAMES = "REVISIONIST_PUBLIC_NAMES"


def write(host: str, origin: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "Host": host, "Origin": origin}


def test_a_rebinding_name_cannot_write_when_no_names_are_set() -> None:
    hdrs = write("rebind.example:8740", "http://rebind.example:8740")
    assert outcome(lambda: guard.same_origin(hdrs)) == MISDIRECTED


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1:8740",
        "localhost:8740",
        "LOCALHOST",
        "[::1]:8740",
        "100.101.102.103:8742",
        TAILNET,
        f"{TAILNET}:8742",
    ],
)
def test_loopback_addresses_and_the_tailnet_name_still_write(host: str) -> None:
    assert outcome(lambda: guard.same_origin(write(host, f"http://{host}"))) == ("ok", None)
    assert outcome(lambda: guard.served({"Host": host})) == ("ok", None)


@pytest.mark.parametrize("host", ["rebind.example", "localhost.rebind.example", "ts.net.example"])
def test_any_name_may_read_when_no_names_are_set(host: str) -> None:
    assert outcome(lambda: guard.served({"Host": host})) == ("ok", None)


@pytest.fixture
def named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PUBLIC_NAMES, f" {TAILNET} , ,127.0.0.1:8809,play.example")


@pytest.mark.usefixtures("named")
@pytest.mark.parametrize(
    "host,origin",
    [
        (TAILNET, f"https://{TAILNET}"),
        (TAILNET.upper(), f"https://{TAILNET}"),
        (f"{TAILNET}:8742", f"http://{TAILNET}:8742"),
        ("127.0.0.1:8809", "http://127.0.0.1:8809"),
        ("play.example", "https://play.example"),
        ("play.example", f"https://{TAILNET}"),
    ],
)
def test_a_listed_name_is_served_and_may_write(host: str, origin: str) -> None:
    assert outcome(lambda: guard.served({"Host": host})) == ("ok", None)
    assert outcome(lambda: guard.same_origin(write(host, origin))) == ("ok", None)


@pytest.mark.usefixtures("named")
@pytest.mark.parametrize(
    "host",
    [
        "rebind.example:8740",
        "127.0.0.1:8740",
        "localhost:8809",
        "a.ts.net",
        "",
        "[::1]:8809",
        "x:y",
        f"x@{TAILNET}",
    ],
)
def test_an_unlisted_host_is_refused_on_every_method(host: str) -> None:
    assert outcome(lambda: guard.served({"Host": host})) == MISDIRECTED
    assert outcome(lambda: guard.same_origin(write(host, f"http://{host}"))) == MISDIRECTED
    hdrs = {"Content-Type": "text/plain", "Host": host}
    assert outcome(lambda: guard.same_origin(hdrs)) == MISDIRECTED


@pytest.mark.usefixtures("named")
@pytest.mark.parametrize(
    "origin",
    [
        "http://rebind.example",
        "http://127.0.0.1:8740",
        "null",
        "http://[::1",
        f"http://x@{TAILNET}",
    ],
)
def test_the_origin_is_checked_against_the_list(origin: str) -> None:
    assert outcome(lambda: guard.same_origin(write(TAILNET, origin))) == CROSS


@pytest.mark.usefixtures("named")
def test_the_server_refuses_an_unlisted_host_on_a_static_get() -> None:
    handler = server_handler()
    handler.path = "/index.html"
    handler.headers = {"Host": "rebind.example:8740"}
    handler.wfile = io.BytesIO()
    handler.request_version = "HTTP/1.1"
    handler.do_GET()
    assert handler.rec.sent[0] == ("status", HTTPStatus.MISDIRECTED_REQUEST)
    assert json.loads(handler.wfile.getvalue()) == {"error": MISDIRECTED[2]}


def test_the_names_are_read_when_a_request_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    hdrs = write("play.example", "https://play.example")
    assert outcome(lambda: guard.same_origin(hdrs)) == MISDIRECTED
    monkeypatch.setenv(PUBLIC_NAMES, "play.example")
    assert outcome(lambda: guard.same_origin(hdrs)) == ("ok", None)
    monkeypatch.setenv(PUBLIC_NAMES, " , ")
    assert outcome(lambda: guard.same_origin(hdrs)) == MISDIRECTED


TOO_LARGE = ("err", HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "That request is too large.")
BODIES: list[tuple[bytes, str | None, Any]] = [
    (b"", None, ("ok", {})),
    (b"{}", None, ("ok", {})),
    (b'{"a": 1}', None, ("ok", {"a": 1})),
    (b"[1]", None, ("err", HTTPStatus.BAD_REQUEST, "Send a JSON object.")),
    (b"nope", None, ("err", HTTPStatus.BAD_REQUEST, "That request was not valid JSON.")),
    (b"x" * (64 * 1024 + 1), None, TOO_LARGE),
    (b"{}", str(64 * 1024 + 1), TOO_LARGE),
    (b"{}", "0", ("ok", {})),
]


@pytest.mark.parametrize("raw,length,want", BODIES)
def test_body_equals_the_servers(raw: bytes, length: str | None, want: Any) -> None:
    hdrs = {"Content-Length": length if length is not None else str(len(raw))}
    assert outcome(lambda: guard.body(hdrs, io.BytesIO(raw), guard.json_body)) == want


def test_body_limit_is_the_servers() -> None:
    assert guard.BODY_MAX == 64 * 1024
    assert guard.COOKIE == server.COOKIE == "rv_session"
    assert guard.CSP == CSP


def test_signin_throttle_equals_the_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    ours = limits.SigninThrottle()
    assert limits.SIGNIN_TRIES == 10
    for i in range(12):
        assert ours.throttled(" Ann ") == (i >= 10)
        ours.failed(" Ann ")
        clock[0] += 1
    assert ours.throttled("bob") is False
    clock[0] += 887
    assert ours.throttled("ann") is True
    clock[0] += 20
    assert ours.throttled("ann") is False


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


@pytest.mark.parametrize("host", ["x@127.0.0.1:8740", "x@localhost"])
def test_a_host_carrying_a_user_is_not_a_local_name(host: str) -> None:
    assert outcome(lambda: guard.same_origin(write(host, f"http://{host}"))) == MISDIRECTED


def test_a_malformed_referer_is_cross_origin() -> None:
    hdrs = {"Content-Type": "application/json", "Host": "127.0.0.1:8740", "Referer": "http://[::1"}
    assert outcome(lambda: guard.same_origin(hdrs)) == CROSS
