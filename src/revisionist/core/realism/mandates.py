"""The agenda (engine v2, spec §8.5). Wave B unit B2.

Templates on ``State.templates`` issue mandates when their triggers fire, and live
mandates settle met, failed or expired. ``score`` is what a seat's mandates are
worth. Code fills the template and compiles the condition; no model is called.
"""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.goals import goal_met
from revisionist.core.ids import EntityId, MandateId, OrderId, SeatId, derived_id
from revisionist.core.realism.agenda import (
    MANDATE_CAP,
    Mandate,
    MandateKind,
    MandateStatus,
    MandateTemplate,
    TriggerKind,
)
from revisionist.core.realism.effect import EffectKind
from revisionist.core.realism.resolvers import friction
from revisionist.core.state import State
from revisionist.core.visibility import private_to

_FAILS = frozenset({MandateKind.ORDER, MandateKind.CRISIS})
"""Kinds that fail at expiry; the rest merely expire. [proposed]"""

_PAID: dict[tuple[MandateKind, MandateStatus], int] = {
    (MandateKind.ORDER, MandateStatus.MET): 2,
    (MandateKind.CRISIS, MandateStatus.MET): 1,
    (MandateKind.BLOWBACK, MandateStatus.MET): 1,
    (MandateKind.OPPORTUNITY, MandateStatus.MET): 1,
    (MandateKind.ORDER, MandateStatus.FAILED): -2,
    (MandateKind.CRISIS, MandateStatus.FAILED): -1,
}
"""[proposed] Everything not listed (including every EXPIRED) is worth 0."""

_PICK = 1000
"""Range of the seeded roll that orders templates competing for a seat's free slots."""


def _in_words(day: date) -> str:
    return f"{day.day} {day:%B} {day.year}"


def _mandate_id(state: State, template: MandateTemplate, seat: SeatId) -> MandateId:
    return MandateId(derived_id(state.campaign_id, "mandate", template.key, seat))


def _crossed(state: State, template: MandateTemplate, today: date) -> bool:
    t = template.trigger
    assert t.quantity is not None and t.value is not None
    q = state.quantities.get(t.quantity)
    if q is None or q.value is None or q.as_of != today:
        return False
    return q.value >= t.value if t.op == "ge" else q.value <= t.value


def _acts(state: State, kind: EffectKind, today: date) -> list[tuple[OrderId, SeatId]]:
    """Orders with a part of ``kind`` applied today, with their issuers."""
    found: set[tuple[OrderId, SeatId]] = set()
    for order in state.routed.values():
        for part in order.parts:
            effects = [part.effect] if part.effect is not None else []
            if part.applied == today and any(
                EffectKind(e.kind) is kind for e in (*effects, *part.estimated)
            ):
                found.add((order.order_id, order.issuer))
    return sorted(found)


def _firings(state: State, t: MandateTemplate, today: date) -> list[tuple[SeatId, OrderId | None]]:
    """Each seat the template reaches today, with the order it answers (blowback)."""
    people: set[EntityId] = set(t.to)
    held = sorted(s.seat_id for s in state.seats.values() if s.embodies in people)
    trigger = t.trigger
    match trigger.on:
        case TriggerKind.HISTORY:
            event = state.scheduled.get(trigger.history) if trigger.history else None
            fired = event is not None and event.fired and event.on_date == today
            return [(s, None) for s in held] if fired else []
        case TriggerKind.QUANTITY:
            return [(s, None) for s in held] if _crossed(state, t, today) else []
        case TriggerKind.ACT:
            assert trigger.effect is not None
            hits: dict[SeatId, OrderId] = {}
            for order_id, issuer in _acts(state, trigger.effect, today):
                if issuer in held:
                    hits.setdefault(issuer, order_id)
            return sorted(hits.items())


def issue_due(state: State, today: date) -> list[ev.Payload]:
    """A ``mandate_issued`` for each template whose trigger fired today.

    A template reaches a seat once per campaign. Where more fire for a seat than it
    has free slots, the seeded roll decides, so a replay picks the same."""
    wanted: dict[SeatId, list[tuple[int, str, MandateTemplate, OrderId | None]]] = {}
    for key in sorted(state.templates):
        t = state.templates[key]
        for seat, cause in _firings(state, t, today):
            if _mandate_id(state, t, seat) in state.mandates:
                continue
            roll = friction(state, t.key, seat, today, n=_PICK)
            wanted.setdefault(seat, []).append((roll, t.key, t, cause))
    out: list[ev.Payload] = []
    for seat in sorted(wanted):
        live = sum(
            m.seat_id == seat and m.status is MandateStatus.LIVE for m in state.mandates.values()
        )
        person = state.seats[seat].name
        for _, _, t, cause in sorted(wanted[seat], key=lambda w: w[:2])[: MANDATE_CAP - live]:
            text = t.text.replace("{person}", person).replace("{date}", _in_words(today))
            mandate = Mandate(
                mandate_id=_mandate_id(state, t, seat),
                seat_id=seat,
                kind=t.kind,
                issuer=t.issuer,
                text=text,
                condition=t.condition,
                issued=today,
                expires=today + timedelta(days=t.days),
                cause=cause,
                scope=private_to(seat),
            )
            out.append(ev.MandateIssued(mandate=mandate))
    return out


def settle_due(state: State, today: date) -> list[ev.Payload]:
    """A ``mandate_settled`` for each live mandate met, or past its expiry.

    Met wins on the day it expires. Orders and crises then fail; blowback and
    opportunities merely expire."""
    out: list[ev.Payload] = []
    for mandate_id in sorted(state.mandates):
        m = state.mandates[mandate_id]
        if m.status is not MandateStatus.LIVE:
            continue
        if goal_met(state, m.condition):
            status = MandateStatus.MET
        elif today >= m.expires:
            status = MandateStatus.FAILED if m.kind in _FAILS else MandateStatus.EXPIRED
        else:
            continue
        out.append(ev.MandateSettled(mandate_id=mandate_id, status=status))
    return out


def score(state: State, seat: SeatId) -> int:
    """What the seat's settled mandates are worth.

    Met: +2 an order, +1 a crisis, blowback or opportunity. Failed: -2 an order,
    -1 a crisis. Expired, and live, are worth nothing."""
    return sum(
        _PAID.get((m.kind, m.status), 0) for m in state.mandates.values() if m.seat_id == seat
    )


__all__ = ["issue_due", "score", "settle_due"]
