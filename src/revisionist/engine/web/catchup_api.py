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
committing that did not go through when this wake opened; and ``steps``, the wake's
playback (PBF, ``playback.steps``), built from the same seam as ``papers``. A page takes
further optional keys without a breaking change.

With ``aide_note`` on, the reply also carries ``waits``, the aide's note of what the seat
left alone (ABN): beside the pages' note of what the aide did, one line, with its day, for
each held order of its own not asked for, each matter that waits on it (``due_matters``:
the asks and matters put before it, a promise due, an incident to answer, a sitting on its
office, a change pending on its post), each bloc that would take an offer on a measure of
its nation on its way, and its own aim while it may still set one. Every line is read from
the state for the seat's own view when the note is read; nothing is stored.
"""

from collections.abc import Mapping, Sequence
from typing import Any, NotRequired

from revisionist.core import events as ev
from revisionist.core import record
from revisionist.core.events import Event
from revisionist.core.ids import OrderId, SeatId
from revisionist.core.ontology import Controller
from revisionist.core.project import project
from revisionist.core.realism import groups, locks, offers
from revisionist.core.state import Rule, State
from revisionist.engine import catchup
from revisionist.engine.web import agenda_api, economy_api, locks_api, playback, stakes
from revisionist.engine.web.realism_api import PlaybackStep, RecordWake, WaitLine
from revisionist.engine.web.record_api import _day, _token


class CatchupPage(RecordWake):
    aide_filed: NotRequired[list[str]]
    """The labels of the orders the aide filed for this seat in this wake."""
    held_dropped: NotRequired[list[str]]
    """The seat's held orders that were due in this wake and did not go through."""
    steps: NotRequired[list[PlaybackStep]]
    """What the seat's view held in this wake, in the order it happened (PBF)."""


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


BLOC_WOULD_TAKE = "{bloc} would take an offer for its votes on {measure}"  # [proposed]
BEFORE_THE_VOTE = "before the vote"  # [proposed]
OWN_AIM_OPEN = 'Your own aim is still open: you may replace "{aim}"'  # [proposed]


def _held(state: State, seat: SeatId) -> list[WaitLine]:
    """The seat's own held orders it has not asked for, from its own view."""
    if not locks.on(state):
        return []
    view = project(state, seat)
    return [
        WaitLine(
            kind="held",
            what=locks.held_words(state, h),
            who=locks_api.who(view, h.decider),
            day=h.filed.isoformat(),
        )
        for h in sorted(view.held.values(), key=lambda h: (h.filed, h.order_id))
        if h.order_id not in view.asked
    ]


def _blocs(state: State, seat: SeatId) -> list[WaitLine]:
    """Each bloc of the seat's own nation that names a price and is held by no offer, on
    each law of that nation whose bill is on its way, from the seat's own view."""
    if not offers.on(state):
        return []
    view = project(state, seat)
    own = economy_api.own_nation(view)
    if own is None:
        return []
    out: list[WaitLine] = []
    for law in sorted(view.laws, key=lambda x: x.key):
        if law.nation != own or offers.bill(state, law.key) is None:
            continue
        for g in groups.of(view, own):
            if g.chamber is None or not (law.key in g.votes or g.vote_default) or not g.prices:
                continue
            if offers.live(view, own, g.key, law.key) is None:
                said = BLOC_WOULD_TAKE.format(bloc=g.name, measure=law.title)
                out.append(WaitLine(kind="bloc", what=said, who=None, day=BEFORE_THE_VOTE))
    return out


def _aim(state: State, seat: SeatId) -> list[WaitLine]:
    """The seat's own aim, while it may still set one: the window shuts when a wake
    closes with a player holding the person."""
    found = stakes.own_aim_block(state, seat)
    if found is None:
        return []
    said = OWN_AIM_OPEN.format(aim=found["replaces"])
    return [WaitLine(kind="aim", what=said, who=None, day=agenda_api.AT_CLOSE)]


def waits(state: State, seat: SeatId) -> list[WaitLine] | None:
    """The aide's note of what waits on ``seat`` (ABN), read now from its own view; None
    with ``aide_note`` off."""
    if Rule.AIDE_NOTE not in state.rules:
        return None
    due = [
        WaitLine(kind=m.kind, what=m.what, who=m.issuer, day=m.due)
        for m in agenda_api.due_matters(state, seat)
    ]
    return [*_held(state, seat), *due, *_blocs(state, seat), *_aim(state, seat)]


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
    played = playback.steps(fed, state, seat, playback.held_orders(events, seat))
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
            steps=played.get(page.number, []),
        )
        commit = commits.get(page.number)
        if commit is not None and commit.by_aide:
            out["aide_filed"] = _labels(ledger, commit.aide_orders)
        if dropped and dropped.get(page.number):
            out["held_dropped"] = list(dropped[page.number])
        pages.append(out)
    answer: dict[str, Any] = {"first": first, "last": last, "pages": pages}
    note = waits(state, seat)
    if note is not None:
        answer["waits"] = note
    return answer


__all__ = [
    "BEFORE_THE_VOTE",
    "BLOC_WOULD_TAKE",
    "OWN_AIM_OPEN",
    "CatchupPage",
    "reply",
    "waits",
]
