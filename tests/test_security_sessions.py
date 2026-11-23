"""Sessions and the transport: HTTPS marks, the write check, the reply headers, stalled and
malformed requests, signing out everywhere, and the sweep of expired sessions.

Header and body checks drive ``guard`` and the server's handler class with a recorder; the
session rules run against a real server on a free port (``tests/test_web.py``'s ``Web``).
"""

from __future__ import annotations

import io
import json
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from revisionist import cli
from revisionist.engine.web import accounts as acc
from revisionist.engine.web import guard, server
from tests.test_web import PASSWORD, Web, web  # noqa: F401
from tests.test_web_guard import Recorder, outcome
from tests.test_web_serve_transport import served  # noqa: F401

runner = CliRunner()


def handler(secure: bool) -> Any:
    app = SimpleNamespace(secure_cookie=secure, static=None)
    cls: Any = server.make_handler(app)  # type: ignore[arg-type]
    h = cls.__new__(cls)
    rec = Recorder()
    h.send_response, h.send_header, h.end_headers = (
        rec.send_response,
        rec.send_header,
        rec.end_headers,
    )
    h.rec, h.wfile = rec, io.BytesIO()
    return h


def sent(h: Any) -> dict[str, str]:
    return {s[0]: s[1] for s in h.rec.sent if len(s) == 2 and isinstance(s[0], str)}


# --- 1. HTTPS: Strict-Transport-Security and the start warning ------------------------


def test_a_secure_server_sends_strict_transport_security() -> None:
    h = handler(secure=True)
    h._send_json(HTTPStatus.OK, {})
    assert sent(h)["Strict-Transport-Security"] == guard.HSTS
    assert guard.HSTS.startswith("max-age=") and int(guard.HSTS.split("=")[1]) >= 86400


def test_a_plain_server_sends_no_strict_transport_security() -> None:
    h = handler(secure=False)
    h._send_json(HTTPStatus.OK, {})
    assert "Strict-Transport-Security" not in sent(h)


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "localhost", "LOCALHOST"])
def test_no_warning_on_this_machine(host: str) -> None:
    assert guard.start_warning(host, secure=False) is None


@pytest.mark.parametrize("host", ["0.0.0.0", "100.101.102.103", "otis-lab", "::"])
def test_one_warning_line_elsewhere_without_the_secure_setting(host: str) -> None:
    line = guard.start_warning(host, secure=False)
    assert line is not None and "\n" not in line and "--secure-cookie" in line
    assert guard.start_warning(host, secure=True) is None


def test_web_serve_warns_once_and_passes_the_secure_setting(served: Any) -> None:  # noqa: F811
    result = runner.invoke(cli.app, ["web", "serve", "--host", "100.101.102.103"])
    assert result.exit_code == 0, result.output
    warned = [line for line in result.output.splitlines() if "--secure-cookie" in line]
    assert warned == [guard.start_warning("100.101.102.103", secure=False)]
    assert served.kwargs["secure_cookie"] is False
    result = runner.invoke(cli.app, ["web", "serve", "--host", "0.0.0.0", "--secure-cookie"])
    assert result.exit_code == 0, result.output
    assert "--secure-cookie" not in result.output
    assert served.kwargs["secure_cookie"] is True
    result = runner.invoke(cli.app, ["web", "serve"])
    assert "--secure-cookie" not in result.output


# --- 2. A write names this host --------------------------------------------------------

JSON = {"Content-Type": "application/json", "Host": "a.ts.net"}
CROSS = ("err", HTTPStatus.FORBIDDEN, "Cross-origin request refused.")


@pytest.mark.parametrize(
    "extra,want",
    [
        ({}, CROSS),
        ({"Origin": "http://a.ts.net"}, ("ok", None)),
        ({"Referer": "http://a.ts.net/play/room"}, ("ok", None)),
        ({"Referer": "http://b.test/a.ts.net"}, CROSS),
        ({"Referer": "http://a.ts.net.b.test/"}, CROSS),
        ({"Origin": "http://b.test", "Referer": "http://a.ts.net/"}, CROSS),
        ({"Origin": "null"}, CROSS),
    ],
)
def test_a_write_must_name_this_host(extra: dict[str, str], want: Any) -> None:
    assert outcome(lambda: guard.same_origin({**JSON, **extra})) == want


def test_an_empty_host_matches_nothing() -> None:
    hdrs = {"Content-Type": "application/json", "Host": "", "Origin": "null"}
    assert outcome(lambda: guard.same_origin(hdrs)) == CROSS
    hdrs = {"Content-Type": "application/json", "Host": "", "Referer": "file:///x"}
    assert outcome(lambda: guard.same_origin(hdrs)) == CROSS


def test_a_post_with_no_origin_is_refused_by_the_server(web: Web) -> None:  # noqa: F811
    c = web.client()
    status, out = c.call("/api/signup", {"handle": "lorenzo", "password": PASSWORD})
    assert status == 201, out
    for drop in ({"Origin": ""}, {"Origin": "", "Referer": web.base + "/"}):
        status, out = _post_raw(web, "/api/seat/status", b"{}", drop, c.cookie)
        if "Referer" in drop:
            assert status == 200, out
        else:
            assert status == 403 and out["error"] == "Cross-origin request refused."


def _post_raw(
    web: Web,  # noqa: F811
    path: str,
    body: bytes,
    extra: dict[str, str],
    cookie: str = "",
) -> tuple[int, Any]:
    import http.client

    host = web.base.removeprefix("http://")
    conn = http.client.HTTPConnection(host, timeout=30)
    try:
        hdrs = {"Content-Type": "application/json", **{k: v for k, v in extra.items() if v}}
        if cookie:
            hdrs["Cookie"] = f"{server.COOKIE}={cookie}"
        conn.request("POST", path, body=body, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
    finally:
        conn.close()
    return resp.status, json.loads(raw) if raw else None


# --- 3. Every reply's resource and permissions policies --------------------------------


@pytest.mark.parametrize("secure", [False, True])
def test_every_reply_carries_the_resource_and_permissions_policies(secure: bool) -> None:
    rec = Recorder()
    guard.headers(rec, HTTPStatus.OK, "text/html", 1)
    got = {s[0]: s[1] for s in rec.sent if len(s) == 2}
    assert got["Cross-Origin-Resource-Policy"] == "same-origin"
    grants = [d.strip() for d in got["Permissions-Policy"].split(",")]
    assert len(grants) >= 10 and all(d.endswith("=()") for d in grants)
    for feature in ("camera", "microphone", "geolocation", "payment", "usb"):
        assert f"{feature}=()" in grants
    h = handler(secure)
    h._send_json(HTTPStatus.OK, {})
    assert sent(h)["Permissions-Policy"] == got["Permissions-Policy"]
    assert sent(h)["Cross-Origin-Resource-Policy"] == "same-origin"


def test_the_content_policy_names_the_manifest_and_the_worker() -> None:
    parts = [p.strip() for p in guard.CSP.split(";")]
    assert "manifest-src 'self'" in parts and "worker-src 'self'" in parts
    assert "default-src 'self'" in parts and "script-src 'self'" in parts


def test_a_static_reply_carries_them_too(web: Web) -> None:  # noqa: F811
    import urllib.request

    with urllib.request.urlopen(web.base + "/app.js", timeout=10) as resp:
        assert resp.headers["Cross-Origin-Resource-Policy"] == "same-origin"
        assert resp.headers["Permissions-Policy"] == guard.PERMISSIONS
        assert "manifest-src 'self'" in resp.headers["Content-Security-Policy"]


# --- 4. Stalled and malformed requests --------------------------------------------------

BAD_LENGTH = ("err", HTTPStatus.BAD_REQUEST, "That request's length is not a number.")


@pytest.mark.parametrize("length", ["abc", "-1", "1_0", " 2", "1.5", "\u00b2", "0x10"])
def test_a_length_that_is_not_a_number_is_a_400(length: str) -> None:
    hdrs = {"Content-Length": length}
    assert outcome(lambda: guard.body(hdrs, io.BytesIO(b"{}" * 8), guard.json_body)) == BAD_LENGTH


def test_a_refusal_that_leaves_the_body_unread_closes_the_connection() -> None:
    for hdrs in ({"Content-Length": "abc"}, {"Content-Length": str(guard.BODY_MAX + 1)}):
        try:
            guard.body(hdrs, io.BytesIO(b""), guard.json_body)
        except guard.RefusedError as exc:
            assert exc.close is True
        else:
            pytest.fail("no refusal")
    try:
        guard.body({"Content-Length": "2"}, io.BytesIO(b"[]"), guard.json_body)
    except guard.RefusedError as exc:
        assert exc.close is False


def test_the_idle_limit_is_thirty_seconds() -> None:
    assert guard.IDLE_S == 30
    cls: Any = server.make_handler(SimpleNamespace(secure_cookie=False, static=None))  # type: ignore[arg-type]
    assert cls.timeout == guard.IDLE_S


def test_the_server_answers_a_bad_length_with_a_400(web: Web) -> None:  # noqa: F811
    status, out = _post_raw(
        web, "/api/signin", b"{}", {"Origin": web.base, "Content-Length": "abc"}
    )
    assert status == 400 and out == {"error": "That request's length is not a number."}


class Quiet:
    """A server whose handler times out after a fraction of a second."""

    def __init__(self, web: Web, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
        from http.server import ThreadingHTTPServer

        monkeypatch.setattr(guard, "IDLE_S", 0.5)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(web.app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def silent_for(self, first: bytes) -> tuple[bytes, float]:
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            start = time.monotonic()
            if first:
                sock.sendall(first)
            got = b""
            while chunk := sock.recv(4096):
                got += chunk
            return got, time.monotonic() - start


def test_a_connection_that_sends_nothing_is_closed(
    web: Web,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    q = Quiet(web, monkeypatch)
    try:
        got, took = q.silent_for(b"")
        assert got == b"" and took < 5
        got, took = q.silent_for(b"POST /api/signin HTTP/1.1\r\nHost: x\r\n")
        assert got == b"" and took < 5
    finally:
        q.close()


def test_a_body_that_stalls_is_a_408_and_the_connection_closes(
    web: Web,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    q = Quiet(web, monkeypatch)
    host = f"127.0.0.1:{q.port}"
    head = (
        f"POST /api/signin HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\n"
        "Content-Type: application/json\r\nContent-Length: 40\r\n\r\n{"
    ).encode()
    try:
        got, took = q.silent_for(head)
    finally:
        q.close()
    assert got.startswith(b"HTTP/1.1 408 "), got[:80]
    assert b"Connection: close" in got and took < 5


# --- 5. Signing out everywhere, and the sweep -------------------------------------------


def test_signout_all_ends_every_session_of_the_account(web: Web) -> None:  # noqa: F811
    a, _ = web.signed_up("lorenzo")
    b = web.client()
    assert b.call("/api/signin", {"handle": "lorenzo", "password": PASSWORD})[0] == 200
    other, _ = web.signed_up("florence")
    assert b.me()["account"]["handle"] == "lorenzo"
    status, out = a.call("/api/signout-all", {})
    assert status == 200 and out == {"ok": True}
    assert "Max-Age=0" in a.last_set_cookie
    assert a.me() == {"account": None}
    assert b.me() == {"account": None}
    assert other.me()["account"]["handle"] == "florence"


def test_signout_all_needs_a_session(web: Web) -> None:  # noqa: F811
    status, out = web.client().call("/api/signout-all", {})
    assert status == 401 and out["error"] == "Sign in first."


def test_signout_all_goes_through_close_all(web: Web, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    a, _ = web.signed_up("lorenzo")
    closed: list[str] = []
    real = acc.Accounts.close_all

    def spy(self: acc.Accounts, account_id: str) -> None:
        closed.append(account_id)
        real(self, account_id)

    monkeypatch.setattr(acc.Accounts, "close_all", spy)
    assert a.call("/api/signout-all", {})[0] == 200
    assert len(closed) == 1


def _sessions(web: Web) -> list[tuple[str, Any]]:  # noqa: F811
    store = web.app.open()
    try:
        rows = store.conn.execute(
            "SELECT token_hash, expires_at FROM web_sessions ORDER BY expires_at"
        ).fetchall()
        return [(str(r[0]), r[1]) for r in rows]
    finally:
        store.close()


def test_the_sweep_deletes_expired_sessions_and_keeps_live_ones(web: Web) -> None:  # noqa: F811
    now = web.app.clock()
    store = web.app.open()
    try:
        accounts = acc.Accounts(store.conn)
        account, _ = accounts.create("lorenzo", PASSWORD)
        old = accounts.open_session(account.account_id, now - timedelta(days=acc.SESSION_DAYS + 1))
        edge = accounts.open_session(account.account_id, now - timedelta(days=acc.SESSION_DAYS))
        live = accounts.open_session(account.account_id, now - timedelta(days=1))
        days = timedelta(days=acc.SESSION_DAYS)
        soon = accounts.open_session(account.account_id, now - days + timedelta(seconds=1))
        assert accounts.sweep(now) == 2
        assert accounts.session(live, now) is not None
        assert accounts.session(soon, now) is not None
        assert accounts.session(old, now - timedelta(days=acc.SESSION_DAYS + 1)) is None
        assert accounts.session(edge, now - timedelta(days=1)) is None
        assert accounts.sweep(now) == 0
    finally:
        store.close()
    assert len(_sessions(web)) == 2


NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


class _Store:
    def __init__(self, log: list[str]) -> None:
        self.conn = SimpleNamespace(execute=lambda sql, args: self._run(sql, args))
        self.log = log

    def _run(self, sql: str, args: Any) -> Any:
        self.log.append(sql.split()[0])
        return SimpleNamespace(rowcount=0)

    def close(self) -> None:
        self.log.append("close")


def test_the_sweep_runs_at_start_and_then_every_day() -> None:
    log: list[str] = []
    waits: list[float] = []

    class Stop:
        def wait(self, s: float) -> bool:
            waits.append(s)
            return len(waits) >= 3

    acc.sweep_daily(lambda: _Store(log), lambda: NOW, Stop())
    assert log == ["DELETE", "close"] * 3
    assert waits == [acc.SWEEP_EVERY_S] * 3 and acc.SWEEP_EVERY_S == 86400


def test_a_failed_sweep_does_not_stop_the_next_one() -> None:
    tries: list[int] = []

    def broken() -> Any:
        tries.append(1)
        raise OSError("database down")

    class Stop:
        def wait(self, s: float) -> bool:
            return len(tries) >= 2

    acc.sweep_daily(broken, lambda: NOW, Stop())
    assert len(tries) == 2


def test_serve_starts_the_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Any] = []

    class FakeServer:
        def __init__(self, *a: Any) -> None:
            self.daemon_threads = False

        def serve_forever(self) -> None:
            return

        def server_close(self) -> None:
            return

    monkeypatch.setattr(server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(
        acc, "sweep_daily", lambda open_store, clock, stop: started.append((open_store, stop))
    )
    app = SimpleNamespace(open=object(), clock=object(), secure_cookie=False, static=None)
    server.serve(app, "127.0.0.1", 0)  # type: ignore[arg-type]
    for _ in range(100):
        if started:
            break
        time.sleep(0.01)
    assert len(started) == 1 and started[0][0] is app.open
    assert started[0][1].is_set()


# --- 6. A recovery still ends every session ---------------------------------------------


def test_a_recovery_ends_every_session(web: Web) -> None:  # noqa: F811
    a, codes = web.signed_up("lorenzo")
    b = web.client()
    assert b.call("/api/signin", {"handle": "lorenzo", "password": PASSWORD})[0] == 200
    new = "another long passphrase"
    c = web.client()
    status, _ = c.call("/api/recover", {"handle": "lorenzo", "code": codes[0], "password": new})
    assert status == 200
    assert a.me() == {"account": None} and b.me() == {"account": None}
    assert c.me()["account"]["handle"] == "lorenzo"
    assert len(_sessions(web)) == 1
