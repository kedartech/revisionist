"""The server reaches headers, the origin check, the body reader and limits through one seam.

`guard` sends every header and reads every write; `limits` is asked before each action family
and at sign-up, sign-in and recovery. The replies are pinned byte for byte, less the date and
the random token and codes.
"""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from revisionist.engine.web import guard, limits
from revisionist.engine.web.server import App, make_handler
from tests.pg import PgDb

PASSWORD = "a long enough passphrase"
Reply = tuple[int, list[tuple[str, str]], bytes]
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'; manifest-src 'self'; worker-src 'self'"
)


def _no_model() -> Any:
    raise AssertionError("no model call in these tests")


class Site:
    def __init__(self, pg_db: PgDb, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        (static / "index.html").write_text("<!doctype html><title>Revisionist</title>")
        (static / "app.js").write_text("export {};")
        (static / "logo.png").write_bytes(b"\x89PNG\r\n")
        self.app = App(
            pg_db.app_dsn,
            static,
            transport_factory=_no_model,
            clock=lambda: datetime(2026, 11, 22, 12, 0, tzinfo=UTC),
            briefings=tmp_path / "briefings",
            offline_prose=True,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        self.cookie = ""

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def raw(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Reply:
        conn = http.client.HTTPConnection(self.host, timeout=30)
        try:
            sent = dict(headers or {})
            if self.cookie:
                sent["Cookie"] = f"rv_session={self.cookie}"
            conn.request(method, path, body=body, headers=sent)
            resp = conn.getresponse()
            got = [(k, v) for k, v in resp.getheaders() if k != "Date"]
            data = resp.read()
        finally:
            conn.close()
        for k, v in got:
            if k == "Set-Cookie":
                self.cookie = v.split(";", 1)[0].split("=", 1)[1]
        return resp.status, got, data

    def post(self, path: str, payload: Any = None, **headers: str) -> Reply:
        hdrs = {"Content-Type": "application/json", "Origin": f"http://{self.host}"}
        hdrs.update({k.replace("_", "-"): v for k, v in headers.items()})
        raw = payload if isinstance(payload, bytes) else json.dumps(payload or {}).encode()
        return self.raw("POST", path, raw, hdrs)


@pytest.fixture
def site(pg_db: PgDb, tmp_path: Path) -> Iterator[Site]:
    s = Site(pg_db, tmp_path)
    yield s
    s.close()


def _masked(reply: Reply) -> tuple[Any, ...]:
    status, headers, body = reply
    text = body.decode("latin-1")
    text = re.sub(r'"codes": \[[^\]]*\]', '"codes": [CODES]', text)
    hdrs = tuple((k, re.sub(r"^rv_session=[^;]+", "rv_session=TOKEN", v)) for k, v in headers)
    return status, hdrs, text


def walk(s: Site) -> list[tuple[Any, ...]]:
    """One call of each family, and each refusal the guard makes."""
    calls: list[Callable[[], Reply]] = [
        lambda: s.raw("GET", "/"),
        lambda: s.raw("GET", "/app.js"),
        lambda: s.raw("GET", "/logo.png"),
        lambda: s.raw("GET", "/missing.css"),
        lambda: s.raw("GET", "/api/me"),
        lambda: s.raw("GET", "/api/nope"),
        lambda: s.post("/api/signup", {}, Content_Type="text/plain"),
        lambda: s.post("/api/signup", {}, Origin="http://elsewhere.test"),
        lambda: s.post("/api/signup", b"{}", Content_Length=str(64 * 1024 + 1)),
        lambda: s.post("/api/signup", b"nope"),
        lambda: s.post("/api/signup", b"[1]"),
        lambda: s.post("/api/signup", {"handle": "lorenzo", "password": PASSWORD}),
        lambda: s.post("/api/signin", {"handle": "lorenzo", "password": "wrong password!!"}),
        lambda: s.post("/api/signin", {"handle": "lorenzo", "password": PASSWORD}),
        lambda: s.post(
            "/api/recover", {"handle": "lorenzo", "code": "AAAAA-AAAAA", "password": PASSWORD}
        ),
        lambda: s.raw("GET", "/api/me"),
        lambda: s.post("/api/seat/status"),
        lambda: s.post("/api/seat/nope"),
        lambda: s.post("/api/new/worlds"),
        lambda: s.post("/api/game/pause"),
        lambda: s.post("/api/realism/status"),
        lambda: s.post("/api/signout"),
        lambda: s.post("/api/seat/status"),
    ]
    return [_masked(call()) for call in calls]


JSON = "application/json; charset=utf-8"
SET = "rv_session=TOKEN; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000"
CLEAR = "rv_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
NO_GAME = "No game yet. Start one with /establish."
EXPECTED: list[tuple[int, str, str, str | None, int, str]] = [
    (
        200,
        "text/html; charset=utf-8",
        "no-cache",
        None,
        41,
        "<!doctype html><title>Revisionist</title>",
    ),
    (200, "text/javascript; charset=utf-8", "no-cache", None, 10, "export {};"),
    (200, "image/png", "max-age=86400", None, 6, "\x89PNG\r\n"),
    (404, JSON, "no-store", None, 23, '{"error": "Not found."}'),
    (200, JSON, "no-store", None, 17, '{"account": null}'),
    (404, JSON, "no-store", None, 26, '{"error": "No such call."}'),
    (415, JSON, "no-store", None, 23, '{"error": "Send JSON."}'),
    (403, JSON, "no-store", None, 42, '{"error": "Cross-origin request refused."}'),
    (413, JSON, "no-store", None, 39, '{"error": "That request is too large."}'),
    (400, JSON, "no-store", None, 45, '{"error": "That request was not valid JSON."}'),
    (400, JSON, "no-store", None, 32, '{"error": "Send a JSON object."}'),
    (201, JSON, "no-store", SET, 182, '{"handle": "lorenzo", "codes": [CODES]}'),
    (401, JSON, "no-store", None, 50, '{"error": "That handle and password don\'t match."}'),
    (200, JSON, "no-store", SET, 21, '{"handle": "lorenzo"}'),
    (401, JSON, "no-store", None, 46, '{"error": "That handle and code don\'t match."}'),
    (
        200,
        JSON,
        "no-store",
        None,
        94,
        '{"account": {"handle": "lorenzo", "codes_left": 10}, "game": null, "live": [], '
        '"finished": []}',
    ),
    (200, JSON, "no-store", None, 69, f'{{"reply": "{NO_GAME}", "refused": true}}'),
    (404, JSON, "no-store", None, 26, '{"error": "No such call."}'),
    (
        200,
        JSON,
        "no-store",
        None,
        98,
        '{"worlds": [{"key": "autumn-1941", "name": "Autumn 1941", '
        '"start": "Washington, September 1941"}]}',
    ),
    (400, JSON, "no-store", None, 52, f'{{"error": "{NO_GAME}"}}'),
    (400, JSON, "no-store", None, 52, f'{{"error": "{NO_GAME}"}}'),
    (200, JSON, "no-store", CLEAR, 12, '{"ok": true}'),
    (401, JSON, "no-store", None, 27, '{"error": "Sign in first."}'),
]


def _expected(row: tuple[int, str, str, str | None, int, str]) -> tuple[Any, ...]:
    status, kind, cache, cookie, length, body = row
    headers = [
        ("Server", "revisionist-web "),
        ("Content-Type", kind),
        ("Content-Length", str(length)),
        ("Content-Security-Policy", CSP),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("Cross-Origin-Opener-Policy", "same-origin"),
        ("Cross-Origin-Resource-Policy", "same-origin"),
        ("Permissions-Policy", guard.PERMISSIONS),
    ]
    if status == 413:
        headers.append(("Connection", "close"))
    headers.append(("Cache-Control", cache))
    if cookie is not None:
        headers.append(("Set-Cookie", cookie))
    return status, tuple(headers), body


def test_every_reply_is_byte_for_byte_as_pinned(site: Site) -> None:
    got = walk(site)
    assert len(got) == len(EXPECTED)
    for i, (have, row) in enumerate(zip(got, EXPECTED, strict=True)):
        assert have == _expected(row), i


HEADER_NAMES = {
    "Content-Type",
    "Content-Length",
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Cross-Origin-Opener-Policy",
    "Cache-Control",
    "Set-Cookie",
    "Origin",
    "Host",
}
LIMIT_NAMES = {"SIGNIN_TRIES", "SIGNIN_WINDOW_S", "BODY_MAX", "CSP"}


def test_the_server_names_no_header_and_no_limit() -> None:
    import io
    import tokenize

    from revisionist.engine.web import server

    source = Path(server.__file__).read_text(encoding="utf-8")
    strings, names = set(), set()
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.STRING:
            strings.add(tok.string.strip("\"'"))
        elif tok.type == tokenize.NAME:
            names.add(tok.string)
    assert not strings & HEADER_NAMES
    assert not names & LIMIT_NAMES
    assert "send_header" not in names
    assert "_failures" not in names


FAMILIES = [
    ("/api/seat/status", "seat/status"),
    ("/api/new/worlds", "new/worlds"),
    ("/api/game/pause", "game/pause"),
    ("/api/realism/status", "realism/status"),
]


def _signed_up(s: Site) -> None:
    status, _, body = s.post("/api/signup", {"handle": "lorenzo", "password": PASSWORD})
    assert status == 201, body


def test_limits_check_is_asked_once_for_each_action_family(
    site: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    _signed_up(site)
    asked: list[tuple[Any, ...]] = []

    def check(store: Any, account_id: Any, campaign_id: Any, action: str, now: Any) -> None:
        asked.append((store is not None, account_id, campaign_id, action, now))

    monkeypatch.setattr(limits, "check", check)
    me = site.app.clock()
    for path, action in FAMILIES:
        asked.clear()
        site.post(path)
        assert [a[3] for a in asked] == [action], path
        assert asked[0][0] and asked[0][1] and asked[0][2] is None and asked[0][4] == me


def test_a_refusal_from_the_limits_is_a_reply(site: Site, monkeypatch: pytest.MonkeyPatch) -> None:
    _signed_up(site)
    monkeypatch.setattr(limits, "check", lambda *a: limits.Refusal("Slow down."))
    for path, _ in FAMILIES:
        status, _, body = site.post(path)
        assert status == 200, path
        assert json.loads(body) == {"refused": True, "message": "Slow down."}, path


def test_limits_address_is_asked_at_sign_up_sign_in_and_recovery(
    site: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(limits, "address", lambda handler, what: asked.append(what))
    _signed_up(site)
    site.post("/api/signin", {"handle": "lorenzo", "password": PASSWORD})
    site.post("/api/recover", {"handle": "lorenzo", "code": "AAAAA-AAAAA", "password": PASSWORD})
    site.post("/api/signout")
    assert asked == ["signup", "signin", "recover"]


def test_an_address_refusal_is_a_reply_and_opens_no_account(
    site: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "address", lambda handler, what: limits.Refusal("Not now."))
    for path in ("/api/signup", "/api/signin", "/api/recover"):
        status, headers, body = site.post(
            path, {"handle": "lorenzo", "password": PASSWORD, "code": "AAAAA-AAAAA"}
        )
        assert status == 200, path
        assert json.loads(body) == {"refused": True, "message": "Not now."}, path
        assert "Set-Cookie" not in dict(headers), path
    monkeypatch.undo()
    _signed_up(site)


def test_the_sign_in_throttle_is_the_limits_one(
    site: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    _signed_up(site)
    monkeypatch.setattr(limits, "SIGNIN_TRIES", 2)
    for _ in range(2):
        status, _, _ = site.post("/api/signin", {"handle": "lorenzo", "password": "wrong one!!!"})
        assert status == 401
    status, _, _ = site.post("/api/signin", {"handle": "lorenzo", "password": PASSWORD})
    assert status == 429
