"""Limits on what costs money: the hourly lines on model calls, the game's ceiling a wake,
the sign-up, sign-in and recovery limits by address, and counts that outlive a restart.

The model is never called: replies come from canned transports, and the free
transport runs against the local fake server of ``tests/test_openrouter.py``, which
counts every request, retry and fallback.
"""

import importlib
import threading
from collections.abc import Iterator
from datetime import timedelta
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, SeatId, derived_id
from revisionist.engine import campaign as cmp
from revisionist.engine.llm import TransportError
from revisionist.engine.openrouter import DOTS, ERNIE, FLINT
from revisionist.engine.web import limits
from revisionist.engine.web.server import App, make_handler
from tests.test_openrouter import DAY, Clock, Fake, Script, make
from tests.test_web import PASSWORD, Client, Web, _florence, web  # noqa: F401
from tests.test_web_realism import Realism, post, solo  # noqa: F401

LINES = [
    ("realism/order", 30),
    ("realism/directive", 30),
    ("seat/order", 30),
    ("realism/help", 20),
    ("realism/aide", 6),
    ("realism/consult", 20),
    ("seat/ask", 20),
    ("new/pitch", 3),
    ("new/cast", 3),
    ("new/pick", 10),
    ("seat/pick", 10),
    ("seat/search", 10),
    ("new/figures", 10),
]
WAKE_OWN = ("realism/commit", "realism/close", "realism/advance")
FREE = (
    "realism/read",
    "realism/file",
    "realism/sign",
    "realism/lever",
    "new/worlds",
    "seat/status",
)


def hits(web: Web) -> int:  # noqa: F811
    store = web.app.open()
    try:
        row = store.conn.execute("SELECT count(*) FROM web_limit_hits").fetchone()
        assert row is not None
        return int(row[0])
    finally:
        store.close()


def ask(web: Web, account: str, action: str) -> Any:  # noqa: F811
    store = web.app.open()
    try:
        return limits.check(store, account, None, action, web.app.clock())
    finally:
        store.close()


def account_of(web: Web, handle: str) -> str:  # noqa: F811
    store = web.app.open()
    try:
        row = store.conn.execute(
            "SELECT account_id FROM web_accounts WHERE handle = %s", (handle,)
        ).fetchone()
        assert row is not None
        return str(row[0])
    finally:
        store.close()


# --- rules 1 and 2: each model call counted per account, refused past its line ---------


@pytest.mark.parametrize(("action", "line"), LINES)
def test_a_model_action_is_refused_past_its_hourly_line(
    web: Web,  # noqa: F811
    action: str,
    line: int,
) -> None:
    for _ in range(line):
        assert ask(web, "acct-a", action) is None
    refused = ask(web, "acct-a", action)
    assert isinstance(refused, limits.Refusal)
    assert refused.reply() == {"refused": True, "message": limits.LATER}
    assert ask(web, "acct-b", action) is None
    web.game.clock.now += timedelta(hours=1, seconds=1)
    assert ask(web, "acct-a", action) is None


def test_the_refusal_is_one_fixed_sentence_saying_when() -> None:
    assert limits.LATER.endswith("Try again in an hour.")
    assert limits.SPENT.endswith("Try again after the next wake.")
    assert limits.ADDRESS_LATER.endswith("Try again in an hour.")


def test_order_and_directive_readings_share_one_line(web: Web) -> None:  # noqa: F811
    for _ in range(15):
        assert ask(web, "acct-a", "realism/order") is None
        assert ask(web, "acct-a", "realism/directive") is None
    assert isinstance(ask(web, "acct-a", "realism/order"), limits.Refusal)
    assert isinstance(ask(web, "acct-a", "realism/directive"), limits.Refusal)
    assert ask(web, "acct-a", "realism/help") is None


def test_a_refused_try_is_not_counted(web: Web) -> None:  # noqa: F811
    for _ in range(3):
        ask(web, "acct-a", "new/pitch")
    before = hits(web)
    for _ in range(5):
        assert isinstance(ask(web, "acct-a", "new/pitch"), limits.Refusal)
    assert hits(web) == before == 3


@pytest.mark.parametrize("action", WAKE_OWN + FREE)
def test_an_action_that_calls_no_player_model_is_never_counted(
    web: Web,  # noqa: F811
    action: str,
) -> None:
    for _ in range(40):
        assert ask(web, "acct-a", action) is None
    assert hits(web) == 0


def test_the_refusal_reaches_the_seat_as_a_reply_in_words(
    solo: tuple[Realism, Client],  # noqa: F811
) -> None:
    _, ada = solo
    for _ in range(20):
        status, out = post(ada, "help", question="How do I raise money for the harbour?")
        assert status == 200 and out["refused"] is False, out
    status, out = post(ada, "help", question="And now?")
    assert status == 200
    assert out == {"refused": True, "message": limits.LATER}


# --- rule 3: the game's ceiling a wake on player-triggered calls ------------------------


class Counting:
    """Records each call's kind and fails it, as an unreachable model would."""

    def __init__(self) -> None:
        self.kinds: list[str] = []

    def call(self, request: Any) -> Any:
        self.kinds.append(request.call_class)
        raise TransportError("no model in these tests")


def spend(game: Realism, usd: float, purpose: str = "counsel", who: str = "ada") -> None:
    seat = SeatId(derived_id(game.campaign, "seat", EntityId(game.ids[who])))
    cost = ev.CallCost(call_class=purpose, model="m", input_tokens=1, output_tokens=1, usd=usd)
    store = game.web.app.open()
    try:
        cmp.log_cost(store, CampaignId(game.campaign), purpose, [cost], seat)
    finally:
        store.close()


@pytest.fixture
def spent(solo: tuple[Realism, Client]) -> Iterator[tuple[Realism, Client, Counting]]:  # noqa: F811
    game, ada = solo
    transport = Counting()
    game.web.app.transport_factory = lambda: transport
    game.web.app.offline_prose = False
    spend(game, 3.0)
    spend(game, 2.0, "aide")
    yield game, ada, transport


def test_past_the_ceiling_the_aide_answers_from_its_templates(
    spent: tuple[Realism, Client, Counting],
) -> None:
    _, ada, transport = spent
    status, out = post(ada, "aide", again=True)
    assert status == 200 and out["refused"] is False, out
    assert out["brief"]["summary"]
    status, out = post(ada, "help", question="How do I raise money for the harbour?")
    assert status == 200 and out["refused"] is False, out
    assert out["help"][-1]["from"] == "aide" and out["help"][-1]["text"]
    assert transport.kinds == []


@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("order", {"text": "Put a small harbour levy to the Council."}),
        ("directive", {"to": "Cora Senn", "channel": "letter", "text": "A levy."}),
        ("consult", {"to": "Cora Senn", "question": "Will the levy pass?"}),
    ],
)
def test_past_the_ceiling_written_orders_and_counsel_are_refused(
    spent: tuple[Realism, Client, Counting], route: str, body: dict[str, Any]
) -> None:
    _, ada, transport = spent
    status, out = post(ada, route, **body)
    assert status == 200
    assert out == {"refused": True, "message": limits.SPENT}
    assert transport.kinds == []


def test_below_the_ceiling_the_aide_still_asks_the_model(
    solo: tuple[Realism, Client],  # noqa: F811
) -> None:
    game, ada = solo
    transport = Counting()
    game.web.app.transport_factory = lambda: transport
    game.web.app.offline_prose = False
    spend(game, 4.99)
    spend(game, 50.0, "prose")
    _, out = post(ada, "aide", again=True)
    assert out["refused"] is True
    assert transport.kinds == ["aide"]


def test_the_ceiling_resets_at_the_next_wake(
    spent: tuple[Realism, Client, Counting],
) -> None:
    game, _, _ = spent
    account = account_of(game.web, "ada")
    refused = ask(game.web, account, "realism/order")
    assert isinstance(refused, limits.Refusal) and refused.message == limits.SPENT
    game.first_tick()
    assert ask(game.web, account, "realism/order") is None


@pytest.mark.parametrize("action", WAKE_OWN)
def test_the_wakes_own_calls_are_never_refused(
    solo: tuple[Realism, Client],  # noqa: F811
    action: str,
) -> None:
    game, _ = solo
    account = account_of(game.web, "ada")
    for line_action, line in LINES:
        for _ in range(line + 1):
            ask(game.web, account, line_action)
    spend(game, 9.0)
    assert isinstance(ask(game.web, account, "realism/aide"), limits.TemplateMode)
    assert ask(game.web, account, action) is None


def test_the_wake_advances_past_the_ceiling(
    spent: tuple[Realism, Client, Counting],
) -> None:
    game, ada, _ = spent
    game.web.app.offline_prose = True
    status, out = post(ada, "advance")
    assert status == 200 and "message" not in out, out


# --- rule 4: sign-up, sign-in and recovery by address ----------------------------------


def signup(web: Web, handle: str, headers: dict[str, str] | None = None) -> tuple[int, Any, Client]:  # noqa: F811
    c = web.client()
    status, out = c.call(
        "/api/signup", {"handle": handle, "password": PASSWORD}, headers=headers or {}
    )
    return status, out, c


def test_sign_up_is_limited_per_address(web: Web) -> None:  # noqa: F811
    for i in range(5):
        status, out, _ = signup(web, f"user{i}")
        assert status == 201, out
    status, out, c = signup(web, "user5")
    assert status == 200
    assert out == {"refused": True, "message": limits.ADDRESS_LATER}
    assert c.last_set_cookie == ""
    web.game.clock.now += timedelta(hours=1, seconds=1)
    status, out, _ = signup(web, "user6")
    assert status == 201, out


def test_the_forwarded_address_is_ignored_without_the_setting(web: Web) -> None:  # noqa: F811
    for i in range(5):
        status, out, _ = signup(web, f"user{i}", {"X-Forwarded-For": f"10.0.0.{i}"})
        assert status == 201, out
    status, out, _ = signup(web, "user5", {"X-Forwarded-For": "10.0.0.99"})
    assert out == {"refused": True, "message": limits.ADDRESS_LATER}


def test_the_forwarded_address_is_used_with_the_setting(
    web: Web,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REVISIONIST_TRUST_PROXY", "1")
    for i in range(6):
        status, out, _ = signup(web, f"user{i}", {"X-Forwarded-For": f"203.0.113.9, 10.0.0.{i}"})
        assert status == 201, out
    for i in range(5):
        status, out, _ = signup(web, f"same{i}", {"X-Forwarded-For": "10.1.1.1"})
        assert status == 201, out
    status, out, _ = signup(web, "same5", {"X-Forwarded-For": "10.1.1.1"})
    assert out == {"refused": True, "message": limits.ADDRESS_LATER}


@pytest.mark.parametrize("path", ["/api/signin", "/api/recover"])
def test_sign_in_and_recovery_are_limited_per_address(web: Web, path: str) -> None:  # noqa: F811
    c = web.client()
    body = {"password": "not the password", "code": "AAAAA-AAAAA"}
    for i in range(30):
        status, out = c.call(path, body | {"handle": f"nobody{i}"})
        assert status == 401, out
    status, out = c.call(path, body | {"handle": "someone-else"})
    assert status == 200
    assert out == {"refused": True, "message": limits.ADDRESS_LATER}


def test_the_address_is_not_stored_as_written(web: Web) -> None:  # noqa: F811
    signup(web, "user0")
    store = web.app.open()
    try:
        keys = [r[0] for r in store.conn.execute("SELECT key FROM web_limit_hits")]
    finally:
        store.close()
    assert keys and not any("127.0.0.1" in k for k in keys)


# --- rule 6: counts survive a restart --------------------------------------------------


def restarted(web: Web) -> App:  # noqa: F811
    """The module's memory, the app's and the server's all gone, as after a restart."""
    importlib.reload(limits)
    old = web.app
    web.server.shutdown()
    web.app = App(
        old.dsn,
        old.static,
        transport_factory=old.transport_factory,
        clock=old.clock,
        briefings=old.briefings,
        offline_prose=True,
    )
    web.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(web.app))
    threading.Thread(target=web.server.serve_forever, daemon=True).start()
    web.base = f"http://127.0.0.1:{web.server.server_address[1]}"
    return web.app


def test_an_hourly_count_survives_a_restart(web: Web) -> None:  # noqa: F811
    for _ in range(3):
        assert ask(web, "acct-a", "new/cast") is None
    restarted(web)
    assert isinstance(ask(web, "acct-a", "new/cast"), limits.Refusal)
    assert hits(web) == 3


def test_the_handle_and_address_counts_survive_a_restart(web: Web) -> None:  # noqa: F811
    status, out, _ = signup(web, "lorenzo")
    assert status == 201, out
    c = web.client()
    for _ in range(limits.SIGNIN_TRIES):
        status, _ = c.call("/api/signin", {"handle": "lorenzo", "password": "wrong one!!!"})
        assert status == 401
    for i in range(4):
        signup(web, f"user{i}")
    app = restarted(web)
    assert app.signin.throttled("lorenzo")
    status, out, _ = signup(web, "user9")
    assert out == {"refused": True, "message": limits.ADDRESS_LATER}


# --- the canned transport: a quota spent and a failed transport each count once ----------


@pytest.fixture
def free_room(
    solo: tuple[Realism, Client],  # noqa: F811
) -> Iterator[tuple[Realism, Client, Script]]:
    game, ada = solo
    script = Script()
    fake = Fake(script)
    try:
        transport = make(fake, Clock())
        game.web.app.transport_factory = lambda: transport
        yield game, ada, script
    finally:
        fake.close()


def counsel_hits(game: Realism) -> int:
    store = game.web.app.open()
    try:
        row = store.conn.execute(
            "SELECT count(*) FROM web_limit_hits WHERE kind = 'counsel'"
        ).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        store.close()


def test_a_spent_quota_and_a_failed_transport_each_count_once(
    free_room: tuple[Realism, Client, Script],
) -> None:
    game, ada, script = free_room
    question = {"to": "Cora Senn", "question": "Will the levy pass?"}
    for m in (ERNIE, DOTS, FLINT):
        script.chat[m] = [(500, {"error": {"message": "server"}})]
    status, out = post(ada, "consult", **question)
    assert status == 200 and out["refused"] is True, out
    assert len(script.posts) == 3  # one request for each model in turn
    assert counsel_hits(game) == 1
    script.chat[ERNIE] = [DAY]
    status, out = post(ada, "consult", **question)
    assert out["refused"] is True, out
    assert len(script.posts) == 4
    assert counsel_hits(game) == 2
    status, out = post(ada, "consult", **question)
    assert out["refused"] is True, out
    assert len(script.posts) == 4  # refused before a request leaves
    assert counsel_hits(game) == 3
