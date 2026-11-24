"""What a caller may spend or repeat, counted in the store so a restart forgets nothing.

The hourly lines on each player action that calls a model, files a report or makes a
game, the game's dollar ceiling a wake on those calls, and the sign-up, sign-in and
recovery limits by address and by handle. A refusal is a value the caller sends as a
reply with ``refused: true``. A wake the scheduler closes never comes through here, so
nothing it does is counted or refused; only a player's own close, advance or commit is.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from revisionist.core import events as ev
from revisionist.engine import openrouter
from revisionist.engine import scheduler as sch
from revisionist.engine.store import load_state
from revisionist.engine.web.accounts import WebSeats

SIGNIN_TRIES = 10
"""Failed sign-ins (or recoveries) per handle per 15 minutes."""
SIGNIN_WINDOW_S = 900
LATER = "That is as many as an hour allows. Try again in an hour."
SPENT = "This game has spent what a wake allows on that. Try again after the next wake."
ADDRESS_LATER = "Too many tries from this address. Try again in an hour."

HOUR = timedelta(hours=1)
LINES: Mapping[str, int] = {
    "reading": 30,
    "question": 20,
    "brief": 6,
    "counsel": 20,
    "pitch": 3,
    "cast": 3,
    "pick": 10,
    "figures": 10,
    "wake": 30,
    "newgame": 10,
    "report": 20,
}
"""Tries an hour per account, by the kind of call [proposed]."""
COUNTED: Mapping[str, str] = {
    "realism/order": "reading",
    "realism/directive": "reading",
    "seat/order": "reading",
    "realism/help": "question",
    "realism/aide": "brief",
    "realism/consult": "counsel",
    "seat/ask": "counsel",
    "seat/goal": "counsel",
    "seat/history": "counsel",
    "new/pitch": "pitch",
    "new/cast": "cast",
    "new/pick": "pick",
    "seat/pick": "pick",
    "seat/search": "pick",
    "new/figures": "figures",
    "realism/close": "wake",
    "realism/advance": "wake",
    "realism/commit": "wake",
    "new/ready": "newgame",
    "new/start": "newgame",
    "new/begin": "newgame",
    "realism/report": "report",
    "seat/bug": "report",
}
"""Each player action that calls a model, files a report or makes a game, and the line
it is counted against."""
GAME_OWN = frozenset({"wake", "newgame", "report"})
"""Lines whose model calls are the game's own, not the caller's, once counted."""

CEILING_USD = 5.0
"""What a game's player-triggered calls may cost in one wake [proposed]."""
PLAYER_PURPOSES = frozenset(
    {"aide", "directive", "counsel", "advise", "goal", "history_brief", "structure"}
)
"""The logged costs a player's action makes; a wake's own (prose, options, rulings) are not."""
TEMPLATED = frozenset({"realism/aide", "realism/help"})
"""Past the ceiling these answer from the aide's templates."""
CEILINGED = frozenset(
    {"realism/order", "realism/directive", "realism/consult", "seat/order", "seat/ask"}
    | {"seat/goal", "seat/history"}
)
"""Past the ceiling these are refused until the next wake."""

ADDRESS_LINES: Mapping[str, int] = {"signup": 5, "signin": 30, "recover": 30}
"""Tries an hour from one address [proposed]."""
TRUST_PROXY_ENV = "REVISIONIST_TRUST_PROXY"
FORWARDED = "X-Forwarded-For"


class Refusal:
    """A turn-away the caller sends as a reply with `refused: true`; never raised."""

    def __init__(self, message: str) -> None:
        self.message = message

    def reply(self) -> dict[str, Any]:
        return {"refused": True, "message": self.message}


class TemplateMode:
    """The game is past its ceiling this wake: the aide's brief and help desk answer
    from their templates. Not a refusal."""


TEMPLATE = TemplateMode()


def _hit(conn: Any, kind: str, key: str, now: datetime, line: int, window: timedelta) -> bool:
    """Count one try against ``line`` in ``window``; False, and nothing counted, past it."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{kind}:{key}",))
        conn.execute(
            "DELETE FROM web_limit_hits WHERE kind = %s AND key = %s AND at <= %s",
            (kind, key, now - window),
        )
        row = conn.execute(
            "SELECT count(*) FROM web_limit_hits WHERE kind = %s AND key = %s AND at > %s",
            (kind, key, now - window),
        ).fetchone()
        if row is not None and row[0] >= line:
            return False
        conn.execute(
            "INSERT INTO web_limit_hits (kind, key, at) VALUES (%s, %s, %s)", (kind, key, now)
        )
        return True


def _count(conn: Any, kind: str, key: str, since: datetime) -> int:
    row = conn.execute(
        "SELECT count(*) FROM web_limit_hits WHERE kind = %s AND key = %s AND at > %s",
        (kind, key, since),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _game(store: Any, account_id: Any, now: datetime) -> Any:
    """The game in play the account holds a seat in, as the server's lookup finds it."""
    live = set(sch.live_campaigns(store, now))
    for seat in WebSeats(store.conn).for_account(account_id):
        if seat.campaign_id in live:
            return seat.campaign_id
    return None


def spent(store: Any, campaign_id: Any) -> float:
    """Dollars the game's players' calls have cost in the wake now open."""
    tick = load_state(store, campaign_id).tick
    return sum(
        cost.usd
        for e in store.read(campaign_id)
        if e.tick == tick
        and isinstance(e.payload, ev.CostLogged)
        and e.payload.purpose in PLAYER_PURPOSES
        for cost in e.payload.costs
    )


def check(
    store: Any, account_id: Any, campaign_id: Any, action: str, now: Any
) -> Refusal | TemplateMode | None:
    """Count one try of ``action`` for the account, or say why not. ``action`` is
    ``<family>/<action>``; one not in ``COUNTED`` is never counted or refused."""
    kind = COUNTED.get(action)
    if kind is None:
        openrouter.serve_as("")
        return None
    openrouter.serve_as("" if kind in GAME_OWN else str(account_id))
    if action in TEMPLATED or action in CEILINGED:
        game = campaign_id or _game(store, account_id, now)
        if game is not None and spent(store, game) >= CEILING_USD:
            return TEMPLATE if action in TEMPLATED else Refusal(SPENT)
    if not _hit(store.conn, kind, str(account_id), now, LINES[kind], HOUR):
        return Refusal(LATER)
    return None


class SigninThrottle:
    """Failed sign-ins and recoveries per handle; counted in the store when it is given
    one, else in memory."""

    def __init__(
        self,
        open_store: Callable[[], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.open_store, self.clock = open_store, clock
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def throttled(self, handle: str) -> bool:
        key = handle.strip().casefold()
        if self.open_store is not None and self.clock is not None:
            store = self.open_store()
            try:
                since = self.clock() - timedelta(seconds=SIGNIN_WINDOW_S)
                return _count(store.conn, "signin-failed", key, since) >= SIGNIN_TRIES
            finally:
                store.close()
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if now - t < SIGNIN_WINDOW_S]
            self._failures[key] = recent
            return len(recent) >= SIGNIN_TRIES

    def failed(self, handle: str) -> None:
        key = handle.strip().casefold()
        if self.open_store is not None and self.clock is not None:
            store = self.open_store()
            try:
                store.conn.execute(
                    "INSERT INTO web_limit_hits (kind, key, at) VALUES (%s, %s, %s)",
                    ("signin-failed", key, self.clock()),
                )
            finally:
                store.close()
            return
        with self._lock:
            self._failures.setdefault(key, []).append(time.monotonic())


def _address(handler: Any) -> str:
    """The caller's address: the socket's, or the one the proxy in front of the server
    wrote last in the forwarded header when the server is told to trust it."""
    if os.environ.get(TRUST_PROXY_ENV, "").strip() == "1":
        forwarded = (handler.headers.get(FORWARDED) or "").split(",")[-1].strip()
        if forwarded:
            return forwarded
    return str(handler.client_address[0])


def address(handler: Any, what: str) -> Refusal | None:
    """Count one sign-up, sign-in or recovery from the caller's address, or refuse it.
    The address is kept only as a hash."""
    throttle = getattr(handler, "throttle", None)
    line = ADDRESS_LINES.get(what)
    if not isinstance(throttle, SigninThrottle) or throttle.open_store is None or line is None:
        return None
    assert throttle.clock is not None
    key = hashlib.sha256(_address(handler).encode()).hexdigest()[:32]
    store = throttle.open_store()
    try:
        if not _hit(store.conn, f"address-{what}", key, throttle.clock(), line, HOUR):
            return Refusal(ADDRESS_LATER)
    finally:
        store.close()
    return None
