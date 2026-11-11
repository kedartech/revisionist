"""The event-driven advance (plan, Phase 2 unit B1).

The world does not move a fixed number of days a turn. It wakes at the earliest
thing that could need someone: an order's step falling due, a history event, or the
horizon of the people at the table. Routine paper does not wake the world: documents
issue and arrive during the stretch and wait in the in-tray (Josh, 2026-10-23: a
daily feed otherwise turns every tick into one day). The days in between pass unseen
and are reported as collapsed.
"""

from datetime import date, timedelta

from revisionist.core import history
from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId
from revisionist.core.ontology import Controller
from revisionist.core.realism.agenda import MandateStatus
from revisionist.core.realism.pipeline import Order, Step, StepKind, step_due
from revisionist.core.realism.pipelines import waiting_on_human
from revisionist.core.state import State

DEFAULT_HORIZON_DAYS = 7
"""The horizon when no human holds a seat [proposed]."""


class WakeReason(Model):
    """One candidate for the next wake, and what it waits on, in plain words."""

    on: date
    what: Label
    """""step", "history", "agenda" or "horizon"."""
    label: Label
    """For the clock line: "Rayburn's count expected ~14 Oct"."""


class Wake(Model):
    to: date
    """The in-world date the next advance runs to. Always after ``today``."""
    reason: WakeReason
    """The earliest candidate. Ties go to the first in the order above."""
    collapsed_days: int
    """Quiet days passed over: ``(to - today).days - 1``."""


CATEGORIES = ("step", "history", "agenda", "horizon")


def _reason(what: str, on: date, label: str, today: date) -> WakeReason:
    """A candidate, due no earlier than tomorrow: one on or before today is handled now."""
    due = on if on > today else today + timedelta(days=1)
    return WakeReason(on=due, what=what, label=label[:60])


def _horizon(state: State) -> int:
    """The smallest horizon among the people a human holds."""
    cards = (
        state.cards.get(seat.embodies)
        for seat in state.seats.values()
        if seat.controller is Controller.HUMAN
    )
    return min((card.horizon_days for card in cards if card), default=DEFAULT_HORIZON_DAYS)


def _lever_words(state: State, order: Order) -> str:
    """The lever as its issuer's card words it; a lever with no label shows its name spaced out."""
    seat = state.seats.get(order.issuer)
    card = state.cards.get(seat.embodies) if seat is not None else None
    found = next((x for x in card.levers if x.name == order.lever), None) if card else None
    if found is not None and found.label:
        return found.label
    spoken = order.lever.replace("_", " ")
    return spoken[:1].upper() + spoken[1:]


def _human(state: State, person: EntityId) -> bool:
    return any(
        s.embodies == person and s.controller is Controller.HUMAN for s in state.seats.values()
    )


def _stop(state: State, order: Order) -> tuple[date, Step] | None:
    """When a moving order next has something for a human, and the step falling due then.

    Clerical steps pass unseen. The order stops the clock when a step decides on an
    order a human issued, when it settles for that human, or when the next step is a
    decision a human holds. Later steps are projected as passing on time; None when
    the order never reaches a human or a step ahead has no length.
    """
    steps = state.pipelines[order.pipeline].steps
    seat = state.seats.get(order.issuer)
    mine = seat is not None and seat.controller is Controller.HUMAN
    when = step_due(order, state.pipelines[order.pipeline])
    i = order.step
    while when is not None:
        step = steps[i]
        if mine and (step.kind is StepKind.DECISION or i + 1 == len(steps)):
            return when, step
        if i + 1 == len(steps):
            return None
        ahead = steps[i + 1]
        if ahead.kind is StepKind.DECISION and _human(state, ahead.person):
            return when, step
        i += 1
        when = None if ahead.days is None else when + timedelta(days=ahead.days)
    return None


def next_wake(state: State, today: date) -> Wake:
    """Where the next advance stops. Pure: same state and day, same wake."""
    found: list[WakeReason] = []
    for order in state.orders.values():
        if waiting_on_human(state, order):
            continue
        stop = _stop(state, order)
        if stop is not None:
            when, step = stop
            holder = state.entities[step.person].name
            found.append(
                _reason("step", when, f"{_lever_words(state, order)}, now with {holder}", today)
            )
    event = history.next_due(state, today + timedelta(days=1))
    if event is not None and event.on_date is not None:
        found.append(_reason("history", event.on_date, event.name, today))
    humans = {s.seat_id for s in state.seats.values() if s.controller is Controller.HUMAN}
    for m in state.mandates.values():
        if m.status is MandateStatus.LIVE and m.seat_id in humans:
            found.append(_reason("agenda", m.expires, f"{m.text[:40]}, due", today))
    found.append(_reason("horizon", today + timedelta(days=_horizon(state)), "horizon", today))
    reason = min(found, key=lambda r: (r.on, CATEGORIES.index(r.what), r.label))
    return Wake(to=reason.on, reason=reason, collapsed_days=(reason.on - today).days - 1)


__all__ = ["DEFAULT_HORIZON_DAYS", "Wake", "WakeReason", "next_wake"]
