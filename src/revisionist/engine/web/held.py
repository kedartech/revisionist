"""Orders a seat gives after it has committed, or while its wake is closing (HLD).

They wait in ``web_held_orders`` and are filed when the next wake opens, in the order
they were given and before that wake's offers: no seat files into a wake it has sealed,
and filing needs no client. One that no longer goes through is dropped, and the seat's
catch-up page for the wake it was due in says so. Each row keeps what the action
needs, already checked as far as the wake it was given in allows.

The table lives in Postgres only, like every web table. Code that reads it treats a
missing table (before ``db migrate`` has run 0013) as empty and logs once.
"""

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict

from revisionist.core.ids import CampaignId, EntityId, OrderId, SeatId
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.pipeline import StepAction
from revisionist.engine import directive, realism_tick
from revisionist.engine.store import EventStore
from revisionist.engine.tick import NotInPlayError
from revisionist.engine.web import agenda_api

if TYPE_CHECKING:
    from psycopg import Connection

log = logging.getLogger(__name__)

HELD = "Held for the next wake."
"""The reply to an order that is held [proposed]."""
TABLE = "web_held_orders"


class Listed(TypedDict):
    """One held order in its own seat's payload."""

    id: int
    label: str
    wake: int
    """The wake it was given in; it is filed when a later one opens."""


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
    """Another session holds the campaign's close lock: a wake is closing. Read from
    ``pg_locks`` rather than by taking the lock, which would turn a close away."""
    from revisionist.engine.scheduler import (
        _LOCK_CLASS,
    )  # it imports the runner, which imports this

    conn = _conn(store)
    if conn is None:
        return False
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted"
        " AND classid = %s::oid AND objid = hashtext(%s)::oid AND objsubid = 2)",
        (_LOCK_CLASS, campaign_id),
    ).fetchone()
    return bool(row and row[0])


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


def listing(store: EventStore, campaign_id: CampaignId, seat: SeatId) -> list[Listed]:
    """The seat's orders still held, oldest first. Only its own payload carries them."""
    rows = _rows(
        store,
        "SELECT held_id, label, wake FROM web_held_orders WHERE campaign_id = %s"
        " AND seat_id = %s AND filed_in IS NULL ORDER BY held_id",
        (campaign_id, seat),
    )
    return [Listed(id=int(r[0]), label=r[1], wake=int(r[2])) for r in rows]


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
        out.setdefault(int(wake), []).append(f"{label} was not filed: {why}")
    return out


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
            realism_tick.take_step(
                store, campaign_id, OrderId(args["order_id"]), taken, args["params"]
            )
        elif action in ("option", "file"):
            asks = tuple(Ask.model_validate(a) for a in args["asks"])
            realism_tick.commit_order(store, campaign_id, seat, asks)
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
    "HELD",
    "Filer",
    "Listed",
    "closing",
    "drop",
    "dropped",
    "file_held",
    "file_one",
    "forget_missing",
    "hold",
    "listing",
]
