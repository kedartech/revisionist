"""The forecast checked (FCK): each picked suggestion's expected moves, judged once
their targets have settled, and the seat's running record.

A routed order that came from a suggested action carries its forecast (FCS,
``RoutedOrder.forecast``). The order is enacted on the day its last part was applied;
its forecast settles ``SETTLE_DAYS`` world days later, and is judged at the first tick
close on or past that day. Each move is judged by whether its target moved the expected
way between the order's filing and that close: a gain is the target going up (a person's
regard for the seat's person, a weighed leader's stance toward the seat, the seat's side
of a contest, or a figure), a cost is it going down, and no change is a miss. Every
reading comes from the issuer's own view (and its own weighing of leaders), so a move
whose target is out of that view at either reading is never judged, and is left out of
the record.

The fold of each campaign's log is kept in the process, so a seat's snapshot folds only
the events added since the last one; a log that does not start with the events already
folded is folded afresh.

Whether the aide chose the order is read from the aide's commit (``WakeCommitted``
``aide_orders``), which is sealed to the seat; the block is the seat's own and goes to
no other seat. No rule reads any of it.
"""

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from hashlib import sha256
from threading import Lock
from typing import Literal

from revisionist.core import events as ev
from revisionist.core.contest import side_of
from revisionist.core.events import Event
from revisionist.core.fold import apply, replay
from revisionist.core.ids import CampaignId, ContestId, EntityId, OrderId, QuantityId, SeatId
from revisionist.core.ontology import ContestKind
from revisionist.core.project import project
from revisionist.core.realism.effect import Expect, ExpectDirection, ExpectOn, RoutedOrder
from revisionist.core.realism.stance import RANK
from revisionist.core.state import State, View
from revisionist.engine import expects
from revisionist.engine.web.realism_api import (
    AgendaRisks,
    ForecastBlock,
    ForecastMove,
    ForecastOrder,
)

SETTLE_DAYS = 7  # [proposed] plan, FCK Defaults
"""World days from an order's enactment to the day its forecast settles."""

Outcome = Literal["held", "missed", "open"]
HELD: Outcome = "held"
MISSED: Outcome = "missed"
OPEN: Outcome = "open"


def _enacted(order: RoutedOrder) -> date | None:
    """The day the order's last part was applied; None while any part is still out."""
    days = [p.applied for p in order.parts]
    return None if any(d is None for d in days) else max(d for d in days if d is not None)


def settles(order: RoutedOrder) -> date | None:
    """The day the order's forecast settles; None until the order is enacted."""
    enacted = _enacted(order)
    return None if enacted is None else enacted + timedelta(days=SETTLE_DAYS)


def _contest_lean(view: View, me: EntityId, target: str) -> int | None:
    contest = view.contests.get(ContestId(target))
    if contest is None:
        return None
    side = side_of(view, me, contest)
    if side is None:
        return None
    if contest.kind is ContestKind.TRIAL or side == contest.sides[0]:
        return contest.track
    return -contest.track if len(contest.sides) == 2 else None


def _reading(state: State, view: View, move: Expect) -> int | None:
    """Where the move's target stands in the seat's own view; None when it cannot see it."""
    me = view.me.embodies
    if move.on is ExpectOn.FIGURE:
        q = view.quantities.get(QuantityId(move.target))
        return q.value if q is not None else None
    if move.on is ExpectOn.REGARD:
        pair = {EntityId(move.target), me}
        rel = next((r for r in view.relationships.values() if {r.a, r.b} == pair), None)
        return rel.disposition if rel is not None else None
    if move.on is ExpectOn.STANCE:
        today = view.in_world_date
        history = state.stances.get(view.viewer, {}).get(EntityId(move.target), ())
        known = [s for s in history if today is None or s.on <= today]
        return RANK[known[-1].stance] if known else None
    return _contest_lean(view, me, move.target)


def _readings(state: State, seat: SeatId, order: RoutedOrder) -> tuple[int | None, ...]:
    assert order.forecast is not None
    view = project(state, seat)
    return tuple(_reading(state, view, m) for m in order.forecast.expects)


def _outcome(move: Expect, before: int | None, after: int | None) -> Outcome | None:
    if before is None or after is None:
        return None
    moved = after > before if move.direction is ExpectDirection.GAIN else after < before
    return HELD if moved else MISSED


@dataclass(frozen=True)
class _Watch:
    issuer: SeatId
    before: tuple[int | None, ...]
    outcomes: tuple[Outcome | None, ...] | None = None


@dataclass(frozen=True)
class _Fold:
    """How far one campaign's log has been folded for judging: the ids of the events
    folded, in order, the state after them and every forecast order watched."""

    ids: tuple[str, ...]
    state: State | None
    watched: dict[OrderId, _Watch]


_FOLDS: OrderedDict[CampaignId, _Fold] = OrderedDict()
_FOLDS_KEPT = 8
_FOLDS_LOCK = Lock()


def _step(state: State, e: Event, watched: dict[OrderId, _Watch]) -> None:
    """Watch a new forecast order at its filing; judge each watched one at the first
    tick close on or past its settling day."""
    p = e.payload
    if isinstance(p, ev.OrderRouted) and p.order.forecast is not None:
        order = state.routed[p.order.order_id]
        watched[order.order_id] = _Watch(order.issuer, _readings(state, order.issuer, order))
    elif isinstance(p, ev.TickClosed) and state.in_world_date is not None:
        for order_id, w in list(watched.items()):
            order = state.routed[order_id]
            day = settles(order)
            if w.outcomes is None and day is not None and state.in_world_date >= day:
                assert order.forecast is not None
                after = _readings(state, w.issuer, order)
                outcomes = tuple(
                    _outcome(m, b, a)
                    for m, b, a in zip(order.forecast.expects, w.before, after, strict=True)
                )
                watched[order_id] = replace(w, outcomes=outcomes)


def _fold(events: Sequence[Event]) -> dict[OrderId, _Watch]:
    """Every forecast order in ``events``, watched to the end. The fold of each campaign
    is kept, so a later call folds only the events added since, when the log it is given
    starts with exactly the events already folded."""
    if not events:
        return {}
    cid = events[0].campaign_id
    ids = tuple(e.event_id for e in events)
    with _FOLDS_LOCK:
        kept = _FOLDS.get(cid)
    if kept is None or ids[: len(kept.ids)] != kept.ids:
        kept = _Fold((), None, {})
    state, watched = kept.state, dict(kept.watched)
    for e in events[len(kept.ids) :]:
        state = replay([e]) if state is None else apply(state, e)
        _step(state, e, watched)
    with _FOLDS_LOCK:
        _FOLDS[cid] = _Fold(ids, state, watched)
        _FOLDS.move_to_end(cid)
        while len(_FOLDS) > _FOLDS_KEPT:
            _FOLDS.popitem(last=False)
    return watched


def judge(
    events: Sequence[Event], seat: SeatId | None = None
) -> dict[OrderId, tuple[Outcome | None, ...]]:
    """Each forecast order's moves as judged at the end of ``events``, in order: held,
    missed or open; None for a move the issuer could not see at a reading. Only
    ``seat``'s orders when it is given."""
    return {
        order_id: w.outcomes
        if w.outcomes is not None
        else tuple(OPEN if b is not None else None for b in w.before)
        for order_id, w in _fold(events).items()
        if seat is None or w.issuer == seat
    }


def tally(judged: dict[OrderId, tuple[Outcome | None, ...]]) -> tuple[int, int]:
    """How many moves were checked (held or missed), and how many held."""
    done = [o for row in judged.values() for o in row if o in (HELD, MISSED)]
    return len(done), sum(1 for o in done if o == HELD)


def _aide_orders(events: Sequence[Event], seat: SeatId) -> set[OrderId]:
    return {
        o
        for e in events
        if isinstance(e.payload, ev.WakeCommitted)
        and e.payload.by_aide
        and e.payload.seat_id == seat
        for o in e.payload.aide_orders
    }


def _day(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def _asked(order: RoutedOrder) -> str:
    return "; ".join(p.ask.strip() for p in order.parts if p.ask.strip())


def block(state: State, seat: SeatId, events: Sequence[Event]) -> ForecastBlock:
    """The seat's own forecasts, newest first, each move with its outcome, and the
    record: how many were checked and how many held."""
    mine = [o for o in state.routed.values() if o.issuer == seat and o.forecast is not None]
    if not mine:
        return ForecastBlock(checked=0, held=0, orders=[])
    judged = judge(events, seat)
    view = project(state, seat)
    found = expects.targets(state, view)
    aide = _aide_orders(events, seat)
    shown: list[ForecastOrder] = []
    for order in sorted(mine, key=lambda o: (o.filed, o.order_id), reverse=True):
        assert order.forecast is not None
        outcomes = judged.get(order.order_id, ())
        moves: list[ForecastMove] = []
        for move, outcome in zip(order.forecast.expects, outcomes, strict=False):
            name = expects.name(found, move) or _settled_name(view, move)
            if outcome is None or name is None:
                continue
            moves.append(
                ForecastMove(
                    on=move.on.value,
                    name=name,
                    direction=move.direction.value,
                    size=move.size,
                    sure=move.sure.value,
                    outcome=outcome,
                )
            )
        risks = order.forecast.risks
        day = settles(order)
        shown.append(
            ForecastOrder(
                id=sha256(str(order.order_id).encode()).hexdigest()[:12],
                filed=_day(order.filed),
                asked=_asked(order),
                aide=order.order_id in aide,
                settles=_day(day) if day is not None else None,
                moves=moves,
                risks=None
                if risks is None
                else AgendaRisks(
                    escalation=risks.escalation, refusal=risks.refusal, exposure=risks.exposure
                ),
            )
        )
    done = [m["outcome"] for o in shown for m in o["moves"] if m["outcome"] != OPEN]
    return ForecastBlock(checked=len(done), held=done.count(HELD), orders=shown)


def _settled_name(view: View, move: Expect) -> str | None:
    """The name of a target that has left the targets list but not the view: a decided
    stake, a person no longer weighed or dead, a figure whose value was cleared."""
    if move.on is ExpectOn.STAKE:
        contest = view.contests.get(ContestId(move.target))
        return contest.name if contest is not None else None
    if move.on is ExpectOn.FIGURE:
        q = view.quantities.get(QuantityId(move.target))
        return q.name if q is not None else None
    entity = view.entities.get(EntityId(move.target))
    return entity.name if entity is not None else None


__all__ = ["HELD", "MISSED", "OPEN", "SETTLE_DAYS", "block", "judge", "settles", "tally"]
