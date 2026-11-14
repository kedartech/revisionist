"""The OpenRouter transport against a local fake HTTP server: no network, no key.

Every guard refuses before a request leaves; the routing table, the three 429
cases and the bucket are driven by the fake server's script and a fake clock.
"""

import json
import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from revisionist.engine import openrouter as orr
from revisionist.engine.llm import Reply, Request, TransportError, cli_schema
from revisionist.engine.openrouter import DOTS, ERNIE, FLINT, OpenRouterTransport

SENTINEL = "test-key-SENTINEL-0123456789abcdef"
PAID = "vendor/paid-model"
GOOD = {"choices": [{"message": {"content": '{"text": "ok"}'}, "finish_reason": "stop"}]}


def free(mid: str) -> dict[str, Any]:
    return {
        "id": mid,
        "pricing": {"prompt": "0", "completion": "0"},
        "supported_parameters": ["response_format", "max_tokens"],
    }


def listing(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"data": list(entries) or [free(ERNIE), free(DOTS), free(FLINT)]}


@dataclass
class Script:
    """What the fake server answers. A model's list is popped; its last entry repeats."""

    listing: dict[str, Any] = field(default_factory=listing)
    listing_status: int = 200
    usage: list[float] = field(default_factory=lambda: [0.0])
    key_status: int = 200
    chat: dict[str, list[tuple[int, Any]]] = field(default_factory=dict)
    echo_key: bool = False
    """Put the Authorization header into every error body, as a careless server might."""
    delay_s: float = 0.0
    seen: list[tuple[str, str]] = field(default_factory=list)
    posts: list[dict[str, Any]] = field(default_factory=list)
    auth: list[str] = field(default_factory=list)


class Fake:
    def __init__(self, script: Script) -> None:
        self.script = script
        lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send(self, status: int, body: Any) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _echo(self, body: Any) -> Any:
                if script.echo_key and isinstance(body, dict):
                    auth = self.headers.get("Authorization", "")
                    err = dict(body.get("error") or {})
                    err["message"] = f"{err.get('message', 'bad')} (sent {auth})"
                    return {**body, "error": err, "headers": dict(self.headers)}
                return body

            def do_GET(self) -> None:
                with lock:
                    script.seen.append(("GET", self.path))
                    script.auth.append(self.headers.get("Authorization", ""))
                if self.path.endswith("/models"):
                    status = script.listing_status
                    self._send(status, script.listing if status == 200 else self._echo({}))
                elif self.path.endswith("/key"):
                    with lock:
                        used = script.usage.pop(0) if len(script.usage) > 1 else script.usage[0]
                    status = script.key_status
                    body = {"data": {"usage": used}} if status == 200 else self._echo({})
                    self._send(status, body)
                else:
                    self._send(404, {})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                with lock:
                    script.seen.append(("POST", self.path))
                    script.posts.append(body)
                    script.auth.append(self.headers.get("Authorization", ""))
                    queue = script.chat.get(body["model"]) or [(200, GOOD)]
                    status, out = queue.pop(0) if len(queue) > 1 else queue[0]
                if script.delay_s:
                    threading.Event().wait(script.delay_s)
                self._send(status, out if status == 200 else self._echo(out))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/api/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class Clock:
    """Monotonic seconds and a UTC wall clock that move together; sleep moves both."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.wall = datetime(2026, 11, 13, 22, 0, tzinfo=UTC)
        self.slept: list[float] = []

    def mono(self) -> float:
        return self.t

    def now(self) -> datetime:
        return self.wall

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.advance(s)

    def advance(self, s: float) -> None:
        self.t += s
        self.wall += timedelta(seconds=s)


@pytest.fixture
def script() -> Script:
    return Script()


@pytest.fixture
def fake(script: Script) -> Iterator[Fake]:
    f = Fake(script)
    yield f
    f.close()


@pytest.fixture
def clock() -> Clock:
    return Clock()


def make(fake: Fake, clock: Clock, **kw: Any) -> OpenRouterTransport:
    return OpenRouterTransport(
        SENTINEL,
        base=fake.base,
        clock=clock.mono,
        now=clock.now,
        sleep=clock.sleep,
        **kw,
    )


def req(kind: str = "prose") -> Request:
    return Request(
        call_class=kind,
        model="claude-haiku-5-5",
        system="You write one page.",
        prompt="Write the page.",
        schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )


def posted(script: Script) -> list[str]:
    return [p["model"] for p in script.posts]


def err(message: str, raw: str = "") -> dict[str, Any]:
    e: dict[str, Any] = {"message": message, "code": 429}
    if raw:
        e["metadata"] = {"raw": raw, "provider_name": "P"}
    return {"error": e}


UPSTREAM = (429, err("Provider returned error", "x:free is temporarily rate-limited upstream"))
MINUTE = (429, err("Rate limit exceeded: free-models-per-min."))
DAY = (429, err("Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000"))


# --- guard 1: the id must end in :free ----------------------------------------------


def test_a_model_id_without_free_is_refused_at_construction(fake: Fake, script: Script) -> None:
    for bad in (PAID, f"{ERNIE}:extended", "vendor/free", ""):
        with pytest.raises(TransportError, match="free"):
            OpenRouterTransport(SENTINEL, {"prose": (bad,)}, base=fake.base)
    assert script.seen == []


def test_a_paid_id_put_in_the_table_later_is_refused_before_any_request(
    fake: Fake, script: Script, clock: Clock
) -> None:
    t = make(fake, clock)
    t.models["prose"] = (ERNIE, PAID)
    with pytest.raises(TransportError, match="free"):
        t.call(req())
    assert script.seen == []


def test_the_env_table_overrides_a_kind_and_is_held_to_free_ids() -> None:
    env = {orr.KEY_ENV: SENTINEL, orr.MODELS_ENV: json.dumps({"prose": ["x/y:free"]})}
    t = OpenRouterTransport.from_env(env)
    assert t.models["prose"] == ("x/y:free",)
    assert t.models["options"] == orr.DEFAULT_MODELS["options"]
    for bad in ('{"prose": ["x/y"]}', "not json", '{"prose": "x/y:free"}', "[1]"):
        with pytest.raises(TransportError):
            OpenRouterTransport.from_env({orr.KEY_ENV: SENTINEL, orr.MODELS_ENV: bad})
    with pytest.raises(TransportError, match=orr.KEY_ENV):
        OpenRouterTransport.from_env({})


# --- guard 2: the live listing must price the model at 0 ----------------------------


def test_a_priced_model_is_skipped_and_the_next_free_one_answers(
    fake: Fake, script: Script, clock: Clock
) -> None:
    priced = free(ERNIE) | {"pricing": {"prompt": "0", "completion": "0.000001"}}
    script.listing = listing(priced, free(DOTS), free(FLINT))
    reply = make(fake, clock).call(req("prose"))
    assert posted(script) == [FLINT] and reply.output == {"text": "ok"}


def test_a_model_with_a_request_price_or_gone_from_the_listing_is_skipped(
    fake: Fake, script: Script, clock: Clock
) -> None:
    per_request = free(ERNIE) | {"pricing": {"prompt": "0", "completion": "0", "request": "0.01"}}
    script.listing = listing(per_request, free(DOTS))
    make(fake, clock).call(req("prose"))
    assert posted(script) == [DOTS]


def test_with_no_model_listed_at_zero_nothing_is_posted(
    fake: Fake, script: Script, clock: Clock
) -> None:
    script.listing = listing(free("other/model:free"))
    with pytest.raises(TransportError):
        make(fake, clock).call(req("prose"))
    assert script.posts == []


def test_the_listing_is_read_once_an_hour(fake: Fake, script: Script, clock: Clock) -> None:
    t = make(fake, clock)
    t.call(req())
    clock.advance(3000)
    t.call(req())
    assert script.seen.count(("GET", "/api/v1/models")) == 1
    script.listing = listing(free(DOTS))
    clock.advance(700)
    t.call(req())
    assert script.seen.count(("GET", "/api/v1/models")) == 2
    assert posted(script)[-1] == DOTS


def test_an_unreadable_listing_refuses_the_call(fake: Fake, script: Script, clock: Clock) -> None:
    script.listing_status = 503
    with pytest.raises(TransportError, match="listing"):
        make(fake, clock).call(req())
    assert script.posts == []


# --- guard 3: key usage may not rise ------------------------------------------------


def test_usage_is_read_at_start_up(fake: Fake, script: Script, clock: Clock) -> None:
    make(fake, clock).start()
    assert script.seen == [("GET", "/api/v1/key")]


def test_a_usage_rise_refuses_every_call_until_restart(
    fake: Fake, script: Script, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    script.usage = [0.5, 0.5, 0.75]
    t = make(fake, clock)
    t.start()
    for _ in range(orr.USAGE_EVERY):
        t.call(req())
        clock.advance(10)
    assert len(script.posts) == orr.USAGE_EVERY
    assert script.seen.count(("GET", "/api/v1/key")) == 1
    t.call(req())  # call 26 reads usage first: 0.5, unchanged
    assert script.seen.count(("GET", "/api/v1/key")) == 2
    for _ in range(orr.USAGE_EVERY - 1):
        t.call(req())
        clock.advance(10)
    with caplog.at_level(logging.INFO):
        for _ in range(3):
            with pytest.raises(TransportError, match="usage"):
                t.call(req())
    assert len(script.posts) == 2 * orr.USAGE_EVERY
    assert script.seen.count(("GET", "/api/v1/key")) == 3
    assert len([r for r in caplog.records if "usage" in r.getMessage()]) == 1


def test_an_unreadable_usage_refuses_the_call(fake: Fake, script: Script, clock: Clock) -> None:
    script.key_status = 500
    with pytest.raises(TransportError, match="usage"):
        make(fake, clock).call(req())
    assert script.posts == []


def test_a_reply_that_reports_a_cost_stops_every_call(
    fake: Fake, script: Script, clock: Clock
) -> None:
    script.chat[ERNIE] = [(200, GOOD | {"usage": {"cost": 0.0002}})]
    t = make(fake, clock)
    with pytest.raises(TransportError, match="cost"):
        t.call(req())
    with pytest.raises(TransportError):
        t.call(req())
    assert len(script.posts) == 1


# --- routing --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "order"),
    [
        ("prose", [ERNIE, FLINT, DOTS]),
        ("counsel", [ERNIE, FLINT, DOTS]),
        ("options", [ERNIE, DOTS, FLINT]),
        ("estimator", [FLINT, ERNIE, DOTS]),
    ],
)
def test_each_kind_tries_its_models_in_order_then_raises(
    fake: Fake, script: Script, clock: Clock, kind: str, order: list[str]
) -> None:
    for m in (ERNIE, DOTS, FLINT):
        script.chat[m] = [(500, {"error": {"message": "boom"}})]
    with pytest.raises(TransportError, match="no free model"):
        make(fake, clock).call(req(kind))
    assert posted(script) == order
    script.posts.clear()
    script.chat[order[-1]] = [(200, GOOD)]
    reply = make(fake, clock).call(req(kind))
    assert posted(script) == order and reply.model == order[-1]


@pytest.mark.parametrize(
    "kind",
    [
        "aide",
        "build",
        "cast",
        "pitch",
        "held_power",
        "session_zero",
        "character_search",
        "character_record",
        "character_pick",
        "goal",
        "history_brief",
        "draft_world",
        "resolver",
        "narrator",
    ],
)
def test_kinds_off_the_table_are_refused_before_any_request(
    fake: Fake, script: Script, clock: Clock, kind: str
) -> None:
    with pytest.raises(TransportError, match="off"):
        make(fake, clock).call(req(kind))
    assert script.seen == []


def test_a_reply_without_json_goes_to_the_next_model(
    fake: Fake, script: Script, clock: Clock
) -> None:
    script.chat[ERNIE] = [(200, {"choices": [{"message": {"content": "I cannot."}}]})]
    script.chat[FLINT] = [(200, {"choices": []})]
    reply = make(fake, clock).call(req("prose"))
    assert posted(script) == [ERNIE, FLINT, DOTS] and reply.output == {"text": "ok"}


def test_a_fenced_reply_is_read(fake: Fake, script: Script, clock: Clock) -> None:
    fenced = '```json\n{"text": "fenced"}\n```'
    script.chat[ERNIE] = [(200, {"choices": [{"message": {"content": fenced}}]})]
    assert make(fake, clock).call(req()).output == {"text": "fenced"}


def test_the_body_pins_the_free_model_and_sends_the_schema(
    fake: Fake, script: Script, clock: Clock
) -> None:
    r = req("options")
    reply = make(fake, clock).call(r)
    (body,) = script.posts
    assert body["model"] == ERNIE and body["models"] == [ERNIE]
    assert body["provider"] == {"allow_fallbacks": False}
    assert body["max_tokens"] == 32000
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["schema"] == cli_schema(r.schema)
    assert body["messages"][0] == {"role": "system", "content": r.system}
    assert body["messages"][1]["content"].startswith(r.prompt)
    assert isinstance(reply, Reply) and reply.usd == 0.0
    assert reply.cost("options").model == ERNIE


# --- the three 429 cases ------------------------------------------------------------


def test_an_upstream_429_goes_to_the_next_model(fake: Fake, script: Script, clock: Clock) -> None:
    script.chat[ERNIE] = [UPSTREAM]
    make(fake, clock).call(req("prose"))
    assert posted(script) == [ERNIE, FLINT] and clock.slept == []


def test_three_upstream_429s_in_a_row_rest_the_model_for_ten_minutes(
    fake: Fake, script: Script, clock: Clock
) -> None:
    script.chat[ERNIE] = [UPSTREAM]
    t = make(fake, clock)
    for _ in range(3):
        t.call(req("prose"))
        clock.advance(5)
    assert posted(script) == [ERNIE, FLINT] * 3
    script.posts.clear()
    t.call(req("prose"))
    assert posted(script) == [FLINT]
    clock.advance(600)
    script.posts.clear()
    t.call(req("prose"))
    assert posted(script) == [ERNIE, FLINT]


def test_an_answer_between_upstream_429s_resets_the_count(
    fake: Fake, script: Script, clock: Clock
) -> None:
    script.chat[ERNIE] = [UPSTREAM, UPSTREAM, (200, GOOD), UPSTREAM, UPSTREAM, (200, GOOD)]
    t = make(fake, clock)
    for _ in range(6):
        t.call(req("prose"))
        clock.advance(5)
    assert posted(script).count(ERNIE) == 6


def test_a_per_minute_429_waits_a_minute_and_retries_once(
    fake: Fake, script: Script, clock: Clock
) -> None:
    script.chat[ERNIE] = [MINUTE, (200, GOOD)]
    reply = make(fake, clock).call(req("prose"))
    assert posted(script) == [ERNIE, ERNIE] and reply.model == ERNIE
    assert clock.slept == [60.0]


def test_a_second_per_minute_429_refuses_the_call(fake: Fake, script: Script, clock: Clock) -> None:
    script.chat[ERNIE] = [MINUTE]
    with pytest.raises(TransportError, match="limit"):
        make(fake, clock).call(req("prose"))
    assert posted(script) == [ERNIE, ERNIE]


def test_the_day_quota_refuses_every_call_until_midnight_utc(
    fake: Fake, script: Script, clock: Clock
) -> None:
    script.chat[ERNIE] = [DAY, (200, GOOD)]
    t = make(fake, clock)
    with pytest.raises(TransportError, match="limit"):
        t.call(req("prose"))
    assert posted(script) == [ERNIE]
    clock.advance(3600)  # 23:00 UTC
    for kind in ("prose", "options", "estimator", "counsel"):
        with pytest.raises(TransportError, match="00:00 UTC"):
            t.call(req(kind))
    assert posted(script) == [ERNIE]
    clock.advance(3601)  # past 00:00 UTC
    t.call(req("prose"))
    assert posted(script) == [ERNIE, ERNIE]


# --- the bucket ---------------------------------------------------------------------


def test_the_sixteenth_call_in_a_minute_waits(fake: Fake, script: Script, clock: Clock) -> None:
    t = make(fake, clock)
    for _ in range(orr.PER_MINUTE):
        t.call(req())
    assert clock.slept == []
    t.call(req())
    assert len(clock.slept) == 1 and 59.0 <= clock.slept[0] <= 60.1
    assert len(script.posts) == orr.PER_MINUTE + 1


def test_the_bucket_is_shared_by_every_kind(fake: Fake, script: Script, clock: Clock) -> None:
    t = make(fake, clock)
    kinds = ["prose", "options", "estimator", "counsel"] * 4
    for kind in kinds:
        t.call(req(kind))
    assert len(clock.slept) == 1


# --- the key --------------------------------------------------------------------------


def test_the_key_reaches_no_log_error_repr_or_reply(
    fake: Fake, script: Script, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    texts: list[str] = []
    replies: list[Reply] = []

    def failing(t: OpenRouterTransport, kind: str = "prose") -> None:
        with pytest.raises(TransportError) as info:
            t.call(req(kind))
        texts.extend([str(info.value), repr(info.value), repr(info.value.__cause__)])
        texts.append(repr(info.value.__context__) if not info.value.__suppress_context__ else "")

    script.echo_key = True
    t = make(fake, clock)
    texts.append(repr(t))
    texts.append(str(vars(t)))

    script.key_status = 401
    failing(t)
    script.key_status = 200

    script.listing_status = 500
    failing(make(fake, clock))
    script.listing_status = 200

    for m in (ERNIE, DOTS, FLINT):
        script.chat[m] = [(500, {"error": {"message": "server"}})]
    failing(t)
    for m in (ERNIE, DOTS, FLINT):
        script.chat[m] = [(401, {"error": {"message": "auth"}})]
    failing(t)
    for m in (ERNIE, DOTS, FLINT):
        script.chat[m] = [UPSTREAM]
    failing(t, "counsel")
    script.chat[ERNIE] = [MINUTE]
    failing(t, "options")
    script.chat[ERNIE] = [(200, GOOD | {"usage": {"cost": 1.0}})]
    failing(OpenRouterTransport(SENTINEL, base=fake.base, clock=clock.mono, sleep=clock.sleep))
    script.chat[ERNIE] = [DAY]
    failing(t)

    script.chat = {}
    slow = OpenRouterTransport(SENTINEL, base=fake.base, timeout_s=0.2, clock=clock.mono)
    script.delay_s = 1.0
    failing(slow)
    script.delay_s = 0.0

    closed = Fake(Script())
    gone = closed.base
    closed.close()
    failing(OpenRouterTransport(SENTINEL, base=gone, clock=clock.mono))

    script.echo_key = False
    clean = Fake(Script())
    try:
        replies.append(make(clean, Clock()).call(req()))
    finally:
        clean.close()
    texts.extend(repr(r) for r in replies)
    texts.extend(json.dumps(r.output) for r in replies)
    texts.extend(r.getMessage() for r in caplog.records)
    texts.extend(str(r.args) for r in caplog.records)
    texts.append(caplog.text)

    assert any("Bearer " + SENTINEL == a for a in script.auth)  # the key was sent
    leaks = [x for x in texts if SENTINEL in x or "SENTINEL" in x]
    assert leaks == []
    assert len(texts) > 30
