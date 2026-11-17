"""The ``catchup`` realism action: a page for every wake the seat missed (CUP).

Request ``{first?: int, last?: int}``. With no range named, the pages run from the wake
after the seat last committed by itself (wake 0 if it never has, or if a new player has
taken it up since) to the latest closed wake, and also take in the wake it last committed
and the open wake when a held order of its own was dropped as that wake opened; the
range comes from the log, never from the browser. Reply
``{first, last, pages}``: each page is the record's wake page, its papers counted from
the catch-up seam, and, only in the owner's own payload and only for a wake the aide
played for it, ``aide_filed``: what the aide filed, in the order's own words; and, only
in the owner's own payload, ``held_dropped``: a line for each order the seat gave after
committing that did not go through when this wake opened. A page takes further
optional keys without a breaking change.
"""

from collections.abc import Mapping, Sequence
from typing import Any, NotRequired

from revisionist.core import events as ev
from revisionist.core import record
from revisionist.core.events import Event
from revisionist.core.ids import OrderId, SeatId
from revisionist.core.ontology import Controller
from revisionist.core.state import State
from revisionist.engine import catchup
from revisionist.engine.web.realism_api import RecordWake
from revisionist.engine.web.record_api import _day, _token


class CatchupPage(RecordWake):
    aide_filed: NotRequired[list[str]]
    """The labels of the orders the aide filed for this seat in this wake."""
    held_dropped: NotRequired[list[str]]
    """The seat's held orders that were due in this wake and did not go through."""


def _whole(body: dict[str, Any], key: str) -> int | None:
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} is a wake number.")
    return value


def _own_commits(events: Sequence[Event], seat: SeatId) -> dict[int, ev.WakeCommitted]:
    """The seat's commits by wake, since its player took it up: a player who joins a
    seat someone left reads from wake 0, as one who joins a fresh seat does. A log from
    before the aide's commit was sealed holds other seats' aide commits under a public
    envelope, so the seat is matched by name."""
    out: dict[int, ev.WakeCommitted] = {}
    for e in events:
        p = e.payload
        if isinstance(p, ev.SeatHandover) and seat in e.scope.known_by:
            if p.controller is Controller.HUMAN:
                out = {}
        elif isinstance(p, ev.WakeCommitted) and p.seat_id == seat:
            out[p.wake] = p
    return out


def _range(
    state: State,
    commits: dict[int, ev.WakeCommitted],
    body: dict[str, Any],
    dropped: Mapping[int, list[str]],
) -> tuple[int, int]:
    wake = state.wake
    if wake is None:
        raise ValueError("No wake has opened yet.")
    first, last = _whole(body, "first"), _whole(body, "last")
    named = first is not None or last is not None
    if first is None:
        mine = [n for n, c in commits.items() if not c.by_aide]
        first = max(mine) + 1 if mine else 0
        if mine and not named and dropped.get(max(mine)):
            first = max(mine)
    if last is None:
        last = wake.number if wake.closed else wake.number - 1
        if not wake.closed and not named and dropped.get(wake.number):
            last = wake.number
    if named and not 0 <= first <= last <= wake.number:
        raise ValueError(f"Name wakes from 0 to {wake.number}, the first no later than the last.")
    return first, last


def _labels(ledger: record.Record, orders: Sequence[OrderId]) -> list[str]:
    out: list[str] = []
    for order_id in orders:
        parts = [e.asked for e in ledger.orders if e.key.rpartition(".")[0] == order_id]
        if parts:
            out.append("; ".join(parts))
    return out


def reply(
    state: State,
    events: Sequence[Event],
    seat: SeatId,
    body: dict[str, Any],
    dropped: Mapping[int, list[str]] | None = None,
) -> dict[str, Any]:
    """``seat``'s catch-up. ``dropped``: the seat's own lines for held orders that did
    not go through, by wake. Raises ``ValueError`` on a range it cannot serve."""
    commits = _own_commits(events, seat)
    first, last = _range(state, commits, body, dropped or {})
    ledger = record.build(state, events, seat)
    fed = catchup.feed(state, events, seat, first, last)
    pages: list[CatchupPage] = []
    for page in ledger.wakes:
        if not first <= page.number <= last:
            continue
        out = CatchupPage(
            number=page.number,
            opened=_day(page.opened),
            days_passed=page.days_passed,
            papers=sum(
                1
                for f in fed
                if f.wake == page.number and isinstance(f.event.payload, ev.DocumentIssued)
            ),
            filed=[_token(k) for k in page.filed],
            settled=[_token(k) for k in page.settled],
        )
        played = commits.get(page.number)
        if played is not None and played.by_aide:
            out["aide_filed"] = _labels(ledger, played.aide_orders)
        if dropped and dropped.get(page.number):
            out["held_dropped"] = list(dropped[page.number])
        pages.append(out)
    return {"first": first, "last": last, "pages": pages}


__all__ = ["CatchupPage", "reply"]
