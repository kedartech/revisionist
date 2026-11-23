"""The playback feed (PBF): a missed wake's steps, in the order they happened.

Built from the catch-up seam alone (``catchup.seat_events``, or ``catchup.feed`` over a
log already read), never from where the state says things stand now. Only the kinds
named here become steps:

- the seat's own order steps (``order_drafted`` and ``order_routed`` as filed,
  ``order_step_taken``, ``order_settled``, ``order_executed``), keyed by the record line
  they move, the aide's filings shaped exactly like the seat's own;
- its own nation's pieces, a step at a time (``piece_stepped``), and a refused step
  (``step_refused``). A move the record made, the aide's and a battle's forced move are
  shaped exactly like a seat's ordered move: the cause never leaves;
- its papers, on the day each arrived (``document_issued``): reports, the press, and the
  battle reports and news that reach a seat only as papers;
- holders as they change (``area_held``);
- its stakes: contests, its own mandates and goals as they land, move or settle;
- its own held orders (``order_held``, ``held_order_ended``): held, and how each ended,
  landed, failed with the stored reason, replaced by its later order, or withdrawn. Only
  the issuer's seat is given these lines, here as well as at the seam; the decider learns
  of an ask only from its own list, as before.

Commit and close events, hand-overs and who played a seat are never fed by the seam
and are refused here too. A dateless event takes the day of the step before it in its
wake, or the earliest day its wake's events name.
"""

from collections.abc import Iterable, Mapping
from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, OrderId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import apply, locks
from revisionist.core.realism.pipelines import order_words
from revisionist.core.state import State, View
from revisionist.engine.catchup import SeatEvent
from revisionist.engine.web import economy_api, map_api
from revisionist.engine.web.realism_api import (
    MapNation,
    PlaybackHalt,
    PlaybackHeld,
    PlaybackHolder,
    PlaybackMove,
    PlaybackOrder,
    PlaybackPaper,
    PlaybackStake,
    PlaybackStep,
)
from revisionist.engine.web.record_api import _token

STEP_KINDS: frozenset[str] = frozenset(
    {
        "order_drafted",
        "order_routed",
        "order_step_taken",
        "order_settled",
        "order_executed",
        "piece_stepped",
        "step_refused",
        "document_issued",
        "area_held",
        "contest_moved",
        "contest_decided",
        "mandate_issued",
        "mandate_settled",
        "goal_progressed",
        "goal_met",
        "goal_undone",
        "order_held",
        "held_order_ended",
    }
)
"""The event kinds that make a step. Every other kind makes none."""

HELD = "{reason}: {words}."  # [proposed]
"""A held order, as its seat was told when it was held, with its words."""
LANDED = "Your held order went ahead: {words}."  # [proposed]
FAILED = "Your held order failed: {reason}: {words}."  # [proposed]
REPLACED = "Your held order was replaced by a later one: {words}."  # [proposed]
WITHDRAWN = "Your held order was withdrawn: {words}."  # [proposed]
AN_ORDER = "an order"  # [proposed]
"""The words of an order the seat's steps cannot name."""


class _Names:
    """How the seat names what a step points at: area keys, piece keys, nations."""

    def __init__(self, state: State, view: View, held: Mapping[OrderId, locks.HeldOrder]) -> None:
        self.state = state
        self.view = view
        self.held = held
        board = view.map
        self.areas: dict[EntityId, str] = {}
        if board is not None:
            self.areas = {t.area: t.key for t in board.territories}
            self.areas |= {z.area: z.key for z in board.sea_zones}
        self.own = economy_api.own_nation(view)

    def area(self, area: EntityId) -> str:
        return self.areas.get(area, "")

    def nation(self, polity: EntityId | None) -> MapNation | None:
        if polity is None:
            return None
        return economy_api.nation(self.state, self.own, polity)

    def words(self, order_id: OrderId | None) -> str:
        """One of the seat's own orders in plain words: a held order's, a form order's
        label and terms, or a written order's asks."""
        state, me = self.state, self.view.viewer
        held = self.held.get(order_id) if order_id is not None else None
        held = held or (state.held.get(order_id) if order_id is not None else None)
        said = ""
        if held is not None and held.issuer == me:
            said = locks.held_words(state, held)
        elif order_id in self.view.orders:
            said = order_words(state, self.view.orders[order_id])
        elif order_id in self.view.routed and order_id in state.routed:
            parts = state.routed[order_id].parts
            said = " ".join(p.ask for p in parts if p.ask.strip())
            said = said or "; ".join(apply.describe(state, p) for p in parts)
        return _plain(said) or AN_ORDER


def _plain(text: str) -> str:
    return " ".join(text.split()).rstrip(".")


_GOAL = {"goal_progressed": "progressed", "goal_met": "met", "goal_undone": "undone"}


def _day(p: ev.Payload) -> date | None:
    """The in-world day the event names for itself, if any."""
    match p:
        case ev.PieceStepped() | ev.StepRefused() | ev.AreaHeld() | ev.OrderExecuted():
            return p.on
        case ev.OrderStepTaken():
            return p.outcome.on
        case ev.OrderDrafted() | ev.OrderRouted():
            return p.order.filed
        case ev.MandateIssued():
            return p.mandate.issued
        case ev.DocumentIssued():
            return p.document.arrives
        case ev.OrderHeld():
            return p.held.filed
        case ev.HeldOrderEnded():
            return p.on
    return None


def _steps(p: ev.Payload, on: str, names: _Names) -> list[PlaybackStep]:
    """An event's steps: one, or one per part for a routed order, or none."""
    if isinstance(p, ev.OrderRouted):
        oid = p.order.order_id
        return [
            PlaybackOrder(kind="order", on=on, order=_token(f"{oid}.{n}"), what="filed")
            for n in range(len(p.order.parts))
        ]
    one = _step(p, on, names)
    return [] if one is None else [one]


def _step(p: ev.Payload, on: str, names: _Names) -> PlaybackStep | None:
    view, campaign = names.view, names.view.campaign_id
    match p:
        case ev.OrderDrafted():
            order = _token(p.order.order_id)
            return PlaybackOrder(kind="order", on=on, order=order, what="filed")
        case ev.OrderStepTaken():
            return PlaybackOrder(
                kind="order", on=on, order=_token(p.order_id), what=p.outcome.action.value
            )
        case ev.OrderSettled():
            return PlaybackOrder(kind="order", on=on, order=_token(p.order_id), what=p.status.value)
        case ev.OrderExecuted():
            what = "refused" if p.refusal else "carried_out"
            return PlaybackOrder(
                kind="order", on=on, order=_token(f"{p.order_id}.{p.part}"), what=what
            )
        case ev.PieceStepped():
            return PlaybackMove(
                kind="move",
                on=on,
                piece=map_api.step_key(campaign, p),
                left=names.area(p.left),
                entered=names.area(p.entered),
            )
        case ev.StepRefused():
            return PlaybackHalt(
                kind="halt",
                on=on,
                piece=map_api.mark_key(campaign, p.nation, p.mark),
                area=names.area(p.area),
                to=names.area(p.to),
                reason=p.reason,
            )
        case ev.DocumentIssued():
            doc = p.document
            return PlaybackPaper(kind="paper", on=on, paper=str(doc.doc_id), title=doc.title)
        case ev.AreaHeld():
            holder = names.nation(p.holder)
            assert holder is not None
            return PlaybackHolder(
                kind="holder",
                on=on,
                area=names.area(p.area),
                holder=holder,
                was=names.nation(p.was),
            )
        case ev.ContestMoved() | ev.ContestDecided():
            contest = view.contests.get(p.contest_id)
            if contest is None:
                return None
            what = "moved" if isinstance(p, ev.ContestMoved) else "decided"
            return PlaybackStake(kind="stake", on=on, name=contest.name, what=what)
        case ev.MandateIssued():
            mandate = view.mandates.get(p.mandate.mandate_id)
            if mandate is None:
                return None
            return PlaybackStake(kind="stake", on=on, name=mandate.text, what="issued")
        case ev.MandateSettled():
            mandate = view.mandates.get(p.mandate_id)
            if mandate is None:
                return None
            return PlaybackStake(kind="stake", on=on, name=mandate.text, what=p.status.value)
        case ev.GoalProgressed() | ev.GoalMet() | ev.GoalUndone():
            goal = view.goals.get(p.goal_id)
            if goal is None:
                return None
            return PlaybackStake(kind="stake", on=on, name=goal.text, what=_GOAL[p.kind])
        case ev.OrderHeld() | ev.HeldOrderEnded():
            return _held(p, on, names)
    return None


def _held(p: ev.OrderHeld | ev.HeldOrderEnded, on: str, names: _Names) -> PlaybackHeld | None:
    """A line on one of the seat's own held orders; none for another seat's."""
    if isinstance(p, ev.OrderHeld):
        h = p.held
        if h.issuer != names.view.viewer:
            return None
        line = HELD.format(reason=_plain(h.reason), words=names.words(h.order_id))
        return PlaybackHeld(kind="held", on=on, what="held", line=line)
    if p.issuer != names.view.viewer:
        return None
    match p.end:
        case locks.HeldEnd.LANDED:
            own = names.words(p.order_id)
            line = LANDED.format(words=own if own != AN_ORDER else names.words(p.by))
        case locks.HeldEnd.FAILED:
            line = FAILED.format(reason=_plain(p.reason), words=names.words(p.order_id))
        case locks.HeldEnd.REPLACED:
            line = REPLACED.format(words=names.words(p.by))
        case locks.HeldEnd.WITHDRAWN:
            line = WITHDRAWN.format(words=names.words(p.order_id))
    return PlaybackHeld(kind="held", on=on, what=p.end.value, line=line)


def steps(
    fed: Iterable[SeatEvent],
    state: State,
    seat: SeatId,
    held: Mapping[OrderId, locks.HeldOrder] | None = None,
) -> dict[int, list[PlaybackStep]]:
    """The steps of each wake in ``fed``, the seam's events for ``seat``, in the order they
    happened. ``state`` names things (area keys, nations, stake names); it never says
    where anything went. ``held``: the seat's own held orders as they were held, from
    the whole log, so an order held in a wake before ``fed`` begins is named when it ends;
    those held within ``fed`` are read from it."""
    ordered = sorted(fed, key=lambda f: (f.wake, f.event.seq))
    holds = dict(held or {})
    for f in ordered:
        if isinstance(f.event.payload, ev.OrderHeld) and f.event.payload.held.issuer == seat:
            holds[f.event.payload.held.order_id] = f.event.payload.held
    names = _Names(state, project(state, seat), holds)
    first: dict[int, date] = {}
    for f in ordered:
        p = f.event.payload
        day = _day(p) if f.event.kind in STEP_KINDS else None
        if isinstance(p, ev.DateAdvanced):
            day = p.to
        if day is not None:
            first[f.wake] = min(day, first.get(f.wake, day))
    out: dict[int, list[tuple[date, int, PlaybackStep]]] = {}
    today: dict[int, date] = {}
    for f in ordered:
        p = f.event.payload
        if f.event.kind not in STEP_KINDS:
            continue
        day = _day(p) or today.get(f.wake) or first.get(f.wake)
        if day is None:
            continue
        found = _steps(p, day.isoformat(), names)
        if found:
            today[f.wake] = day
        out.setdefault(f.wake, []).extend((day, f.event.seq, s) for s in found)
    return {
        w: [s for _, _, s in sorted(found, key=lambda t: t[:2])]
        for w, found in out.items()
        if found
    }


def held_orders(events: Iterable[ev.Event], seat: SeatId) -> dict[OrderId, locks.HeldOrder]:
    """``seat``'s own held orders, as each was held, from a log already read."""
    return {
        e.payload.held.order_id: e.payload.held
        for e in events
        if isinstance(e.payload, ev.OrderHeld) and e.payload.held.issuer == seat
    }


__all__ = ["STEP_KINDS", "held_orders", "steps"]
