"""Orders a seat gives after it has committed, or while its wake is closing (HLD).

They wait in ``web_held_orders`` and are filed when the next wake opens, in the order
they were given and before that wake's offers: no seat files into a wake it has sealed,
and filing needs no client. One that no longer goes through is dropped, and the seat's
catch-up page for the wake it was due in says so, as does its own payload while that
wake is open. Each row keeps what the action needs, already checked as far as the wake
it was given in allows. A new player taking up a seat starts with none of its rows.

The table lives in Postgres only, like every web table. Code that reads it treats a
missing table (before ``db migrate`` has run 0013) as empty and logs once.
"""

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from revisionist.core.ids import CampaignId, EntityId, OrderId, SeatId
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.effect import Forecast
from revisionist.core.realism.pipeline import StepAction
from revisionist.engine import directive, orders_reader, realism_tick
from revisionist.engine.store import EventStore
from revisionist.engine.tick import NotInPlayError
from revisionist.engine.web import agenda_api, conferences_api

if TYPE_CHECKING:
    from psycopg import Connection

log = logging.getLogger(__name__)

HELD = "Held for the next wake."
"""The reply to an order that is held [proposed]."""
TABLE = "web_held_orders"
CLOSE_CLASS = 0x72767363  # "rvsc": first key of the advisory lock that marks a close


class Listed(TypedDict):
    """One held order in its own seat's payload."""

    id: int
    label: str
    wake: int
    """The wake it was given in; it is filed when a later one opens."""
    dropped: NotRequired[str]
    """The line saying it did not go through, while the wake it was due in is open."""


Filer = Callable[[EventStore, CampaignId, SeatId, str, dict[str, Any]], str | None]
"""Files one held action; None when it went through, else why it did not."""


_missing = False


def forget_missing() -> None:
    """Log a missing table again (tests)."""
    global _missing
    _missing = False


def _is_missing(exc: Exception) -> bool:
    from psycopg import errors

    global _missing
    if not isinstance(exc, errors.UndefinedTable):
        return False
    if not _missing:
        _missing = True
        log.warning("%s is missing (run db migrate): read as empty", TABLE)
    return True


def _conn(store: EventStore) -> "Connection[Any] | None":
    """The store's connection when it is Postgres; None otherwise."""
    try:
        from revisionist.engine.pg_store import PostgresEventStore
    except ImportError:  # the postgres extra is not installed
        return None
    return store.conn if isinstance(store, PostgresEventStore) else None


def _rows(store: EventStore, sql: str, args: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    """A read of the table; empty when it is missing or the store is not Postgres."""
    conn = _conn(store)
    if conn is None:
        return []
    try:
        return conn.execute(sql, args).fetchall()
    except Exception as exc:
        if _is_missing(exc):
            return []
        raise


def closing(store: EventStore, campaign_id: CampaignId) -> bool:
    """A close of the campaign's wake is running: some session holds its mark
    (``marking_close``). A leave, a join or a scheduler pass that closes nothing holds
    the game's lock but not the mark. Read from ``pg_locks``, so it takes nothing; only
    this database's marks count, since ``pg_locks`` lists the whole cluster's and a
    campaign id may recur in another database."""
    conn = _conn(store)
    if conn is None:
        return False
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted"
        " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
        " AND classid = %s::oid AND objid = hashtext(%s)::oid AND objsubid = 2)",
        (CLOSE_CLASS, campaign_id),
    ).fetchone()
    return bool(row and row[0])


@contextmanager
def marking_close(store: EventStore, campaign_id: CampaignId) -> Iterator[None]:
    """Mark the campaign as closing a wake while the block runs. The close holds the
    game's lock already, so nothing waits on the mark; if another session somehow holds
    it, the campaign reads as closing all the same."""
    conn = _conn(store)
    args = (CLOSE_CLASS, campaign_id)
    row = (
        None
        if conn is None
        else conn.execute("SELECT pg_try_advisory_lock(%s, hashtext(%s))", args).fetchone()
    )
    try:
        yield
    finally:
        if conn is not None and row and row[0]:
            try:
                conn.execute("SELECT pg_advisory_unlock(%s, hashtext(%s))", args)
            except Exception:  # the session ends the lock when it closes
                log.exception("the close mark of %s was not released", campaign_id)


def hold(
    store: EventStore,
    campaign_id: CampaignId,
    seat: SeatId,
    wake: int,
    action: str,
    args: dict[str, Any],
    label: str,
) -> int | None:
    """Keep ``action`` for the first wake opened after ``wake``; returns its id, or None
    when it cannot be kept (no table)."""
    conn = _conn(store)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "INSERT INTO web_held_orders (campaign_id, seat_id, wake, action, args, label)"
            " VALUES (%s, %s, %s, %s, %s, %s) RETURNING held_id",
            (campaign_id, seat, wake, action, json.dumps(args), label),
        ).fetchone()
    except Exception as exc:
        if _is_missing(exc):
            return None
        raise
    assert row is not None
    return int(row[0])


def listing(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, open_wake: int | None = None
) -> list[Listed]:
    """The seat's orders still held, and those due in ``open_wake`` (the wake now open)
    that did not go through, with the line saying so; oldest first. Only its own
    payload carries them."""
    rows = _rows(
        store,
        "SELECT held_id, label, wake, dropped FROM web_held_orders WHERE campaign_id = %s"
        " AND seat_id = %s AND (filed_in IS NULL OR (dropped IS NOT NULL AND filed_in = %s))"
        " ORDER BY held_id",
        (campaign_id, seat, open_wake),
    )
    out: list[Listed] = []
    for held_id, label, wake, why in rows:
        listed = Listed(id=int(held_id), label=label, wake=int(wake))
        if why is not None:
            listed["dropped"] = _line(label, why)
        out.append(listed)
    return out


def held_battles(store: EventStore, campaign_id: CampaignId, seat: SeatId) -> set[str]:
    """The area keys of the battles the seat has a decision held for (BTD): only its own
    payload reads them."""
    rows = _rows(
        store,
        "SELECT args FROM web_held_orders WHERE campaign_id = %s AND seat_id = %s"
        " AND action = 'battle' AND filed_in IS NULL",
        (campaign_id, seat),
    )
    out: set[str] = set()
    for (args,) in rows:
        kept = args if isinstance(args, dict) else json.loads(args)
        if isinstance(kept.get("area"), str):
            out.add(kept["area"])
    return out


NOT_OFFERED = "You cannot do that with this order."  # [proposed]
"""The refusal of a step action the seat was not offered, the same for every action."""


def _line(label: str, why: str) -> str:
    return f"{label} was not filed: {why}"


def drop(store: EventStore, campaign_id: CampaignId, seat: SeatId, held_id: int) -> bool:
    """Withdraw the seat's own held order before it is filed; False if there is none."""
    rows = _rows(
        store,
        "DELETE FROM web_held_orders WHERE held_id = %s AND campaign_id = %s"
        " AND seat_id = %s AND filed_in IS NULL RETURNING 1",
        (held_id, campaign_id, seat),
    )
    return bool(rows)


def dropped(store: EventStore, campaign_id: CampaignId, seat: SeatId) -> dict[int, list[str]]:
    """The seat's lines for held orders that did not go through, by the wake they were
    due in, in the order given."""
    out: dict[int, list[str]] = {}
    for wake, label, why in _rows(
        store,
        "SELECT filed_in, label, dropped FROM web_held_orders WHERE campaign_id = %s"
        " AND seat_id = %s AND dropped IS NOT NULL ORDER BY held_id",
        (campaign_id, seat),
    ):
        out.setdefault(int(wake), []).append(_line(label, why))
    return out


def clear(store: EventStore, campaign_id: CampaignId, seat: SeatId) -> int:
    """Forget every row of the seat, waiting or done, when a new player takes it up:
    none of the last player's orders is filed for them and none of their lines is
    shown. Returns how many rows went. Runs in a savepoint of its own, so a missing
    table leaves the caller's transaction as it was."""
    conn = _conn(store)
    if conn is None:
        return 0
    try:
        with conn.transaction():
            rows = conn.execute(
                "DELETE FROM web_held_orders WHERE campaign_id = %s AND seat_id = %s RETURNING 1",
                (campaign_id, seat),
            ).fetchall()
    except Exception as exc:
        if _is_missing(exc):
            return 0
        raise
    return len(rows)


def file_one(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, action: str, args: dict[str, Any]
) -> str | None:
    """File one held action as the seat would have; None when it went through."""
    try:
        if action == "lever":
            realism_tick.file_order(store, campaign_id, seat, args["lever"], args["params"])
        elif action == "sign":
            proposal = directive.Proposal(
                person=EntityId(args["to"]),
                channel=ChannelKind(args["channel"]),
                text=args["text"],
                lever=args["lever"],
                params=args["params"],
            )
            directive.sign(store, campaign_id, seat, proposal)
        elif action == "step":
            taken = StepAction(args["action"])
            try:
                realism_tick.take_step(
                    store, campaign_id, seat, args["order_id"], taken, args["params"]
                )
            except ValueError as exc:  # the step moved on since it was held
                said = str(exc)
                return (
                    said if said in (realism_tick.NOT_YOURS, realism_tick.NO_AMEND) else NOT_OFFERED
                )
        elif action in ("option", "file", "battle", "contingency", "agreement-publish"):
            asks = tuple(Ask.model_validate(a) for a in args["asks"])
            told = args.get("forecast")
            if args.get("forms"):  # a written order whose asks the seat's forms give
                forms = [(f[0], dict(f[1])) if f else None for f in args["forms"]]
                orders_reader.file_written(store, campaign_id, seat, asks, forms)
            elif told is None:
                realism_tick.commit_order(store, campaign_id, seat, asks)
            else:  # a picked suggestion keeps its forecast (FCK)
                forecast = Forecast.model_validate(told)
                realism_tick.commit_order(store, campaign_id, seat, asks, forecast)
        elif action == "conference-call":
            conferences_api.call(store, campaign_id, seat, args)
        elif action == "conference-vote":
            conferences_api.vote(store, campaign_id, seat, args)
        elif action == "office-vote":
            agenda_api.office_vote(store, campaign_id, seat, args)
        elif action == "ask":
            realism_tick.ask_order(store, campaign_id, seat, OrderId(args["order_id"]))
        elif action == "offer":
            realism_tick.make_offer(
                store, campaign_id, seat, args["bloc"], args["measure"], args["price"]
            )
        elif action == "send-anyway":
            realism_tick.send_anyway(store, campaign_id, seat, OrderId(args["order_id"]))
        elif action == "answer" and "verdict" in args:  # an incident (DFR)
            done = agenda_api.answer_incident(
                store, campaign_id, seat, args["item"], args["verdict"]
            )
            return done["reply"] if done["refused"] else None
        elif action == "answer":
            done = agenda_api.answer(store, campaign_id, seat, args["item"], args["accept"])
            return done["reply"] if done["refused"] else None
        else:
            return f"No such order as {action}."
    except (ValueError, KeyError, NotInPlayError) as exc:
        return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    return None


def file_held(
    store: EventStore, campaign_id: CampaignId, wake: int, *, filer: Filer = file_one
) -> int:
    """File every order held in a wake before ``wake``, which has just opened, in the
    order given; returns how many were taken. Each row is claimed before it is filed,
    so a resumed or second run never files one twice."""
    conn = _conn(store)
    taken = 0
    for held_id, seat, action, args in _rows(
        store,
        "SELECT held_id, seat_id, action, args FROM web_held_orders WHERE campaign_id = %s"
        " AND filed_in IS NULL AND wake < %s ORDER BY held_id",
        (campaign_id, wake),
    ):
        assert conn is not None
        claimed = conn.execute(
            "UPDATE web_held_orders SET filed_in = %s WHERE held_id = %s AND filed_in IS NULL"
            " RETURNING 1",
            (wake, held_id),
        ).fetchone()
        if claimed is None:
            continue
        taken += 1
        try:
            why = filer(store, campaign_id, SeatId(seat), action, args)
        except Exception:  # the wake is open: one bad order must not stop the rest
            log.exception("held order %s of %s was not filed", held_id, campaign_id)
            why = "It could not be filed."
        if why is not None:
            conn.execute(
                "UPDATE web_held_orders SET dropped = %s WHERE held_id = %s", (why, held_id)
            )
    return taken


__all__ = [
    "CLOSE_CLASS",
    "HELD",
    "Filer",
    "Listed",
    "clear",
    "closing",
    "drop",
    "dropped",
    "file_held",
    "file_one",
    "forget_missing",
    "hold",
    "listing",
    "marking_close",
]
