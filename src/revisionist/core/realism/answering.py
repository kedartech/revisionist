"""People nobody plays answer what is done to them (strategy step 2).

Each day, after the day's acts have landed, every unplayed person with written answers
looks at what landed: a form someone filed that went through, or a typed act that was
carried out. An answer whose trigger matches, whose stance gate holds and whose
cooldown has run is taken up and falls due some days later; on that day the person
files an order of their own through the same routing as a player's. Taking up an
answer to someone's act costs that someone a point of the person's regard, unless the
answer is a good turn. Code decides throughout; no model is asked.

Caps: one answer made per person per day, ``DAILY`` per game per day. An answer set off
by another unplayed person's act is not made the day it is taken up, so one day's acts
never chain.
"""

from collections.abc import Iterator
from datetime import date, timedelta
from typing import NamedTuple

from revisionist.core import events as ev
from revisionist.core.goals import Ordered
from revisionist.core.ids import EntityId, MandateId, OrderId, SeatId, derived_id
from revisionist.core.ontology import SeatKind
from revisionist.core.realism import actors, opponents
from revisionist.core.realism.agenda import (
    MANDATE_CAP,
    Ask,
    Mandate,
    MandateKind,
    MandateStatus,
    opening_id,
)
from revisionist.core.realism.answer import ENTITY_FIELDS, Answer, AnswerWhen
from revisionist.core.realism.apply import shift
from revisionist.core.realism.card import words
from revisionist.core.realism.effect import (
    Deal,
    Effect,
    EffectKind,
    EstimatedEffect,
    MakeStatement,
    RoutedOrder,
    ShiftDisposition,
)
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.pipeline import SETTLED, Order, OrderStatus
from revisionist.core.realism.resolvers import settled_on
from revisionist.core.realism.route import route
from revisionist.core.realism.war_rules import order_refusal
from revisionist.core.state import State
from revisionist.core.visibility import private_to

DAILY = 6
"""The most answers made in one game on one day [proposed]."""
APPROACH_DAYS = 14
"""How long a player has to take up an approach put to them [proposed]."""


class Act(NamedTuple):
    """Something that landed: a form gone through, or the typed effects carried out."""

    order_id: OrderId
    seat: SeatId
    lever: str | None
    params: dict[str, int | str]
    effects: tuple[EstimatedEffect, ...]


def acts_on(state: State, day: date) -> list[Act]:
    """What landed on ``day``, by order id."""
    out: list[Act] = []
    for order in state.orders.values():
        if order.status is OrderStatus.ENACTED and settled_on(order) == day:
            out.append(Act(order.order_id, order.issuer, order.lever, dict(order.params), ()))
    for routed in state.routed.values():
        effects: list[EstimatedEffect] = []
        for part in routed.parts:
            if part.applied == day:
                effects += [part.effect] if part.effect is not None else []
                effects += part.estimated
        if effects:
            out.append(Act(routed.order_id, routed.issuer, None, {}, tuple(effects)))
    return sorted(out, key=lambda a: a.order_id)


def _belongs(state: State, entity: EntityId | None, key: EntityId) -> bool:
    return entity is not None and key in opponents.line(state, entity)


def _names(effect: EstimatedEffect) -> Iterator[EntityId]:
    for name in ENTITY_FIELDS:
        found = getattr(effect, name, None)
        if isinstance(found, str):
            yield EntityId(found)


def matches(state: State, when: AnswerWhen, act: Act) -> bool:
    """The act is one the trigger names, by the side it names."""
    if when.by is None or not _belongs(state, state.seats[act.seat].embodies, when.by):
        return False
    if when.human and act.seat not in actors.readers(state):
        return False
    if when.lever is not None:
        return act.lever == when.lever and all(
            act.params.get(k) in allowed for k, allowed in when.params.items()
        )
    party = when.party
    return any(
        EffectKind(e.kind) is when.effect
        and (party is None or any(_belongs(state, n, party) for n in _names(e)))
        for e in act.effects
    )


def _retired(state: State, answer: Answer) -> bool:
    if answer.until is None:
        return False
    item = state.scheduled.get(answer.until)
    return item is not None and item.fired


def _seat(state: State, figure: EntityId) -> SeatId | None:
    """The person's AI seat, while nobody plays them."""
    held = [s for s in state.seats.values() if s.embodies == figure]
    if len(held) == 1 and held[0].kind is SeatKind.FACTION:
        return held[0].seat_id
    return None


def answerers(state: State) -> list[EntityId]:
    """The unplayed people with written answers, in id order."""
    played = {state.seats[s].embodies for s in actors.readers(state)}
    return sorted(p for p, card in state.cards.items() if card.answers and p not in played)


def _counterparty(answer: Answer) -> EntityId | None:
    effect = answer.act.effect
    return effect.counterparty if isinstance(effect, Deal) else None


def plan(state: State, day: date, since: date | None = None) -> list[ev.Payload]:
    """The answers taken up on ``day``: set off by what landed from ``since`` (default
    ``day``) to ``day``, or by their cadence. Each is preceded, where it costs regard,
    by the change to the person's regard for whoever acted."""
    landed = [a for d in _days(since or day, day) for a in acts_on(state, d)]
    world = PassWorld(state)
    out: list[ev.Payload] = []
    for figure in answerers(state):
        seat = _seat(state, figure)
        if seat is None:
            continue
        held = state.answers.get(figure, {})
        for answer in state.cards[figure].answers:
            last = held.get(answer.key)
            if _retired(state, answer):
                continue
            if last is not None and (
                last.made is None or day < last.planned + timedelta(days=answer.cooldown_days)
            ):
                continue
            when = answer.when
            cause: Act | None = None
            if when.every_days is not None:
                assert when.start is not None
                if day < when.start or (day - when.start).days % when.every_days:
                    continue
                toward = _counterparty(answer)
            else:
                cause = next(
                    (
                        a
                        for a in landed
                        if state.seats[a.seat].embodies != figure
                        and matches(state, when, a)
                        and all(log.cause != a.order_id for log in held.values())
                    ),
                    None,
                )
                if cause is None:
                    continue
                toward = state.seats[cause.seat].embodies
            if answer.gate and (
                toward is None or opponents.stance_toward(state, figure, toward) not in answer.gate
            ):
                continue
            due = day + timedelta(days=answer.delay_days)
            if cause is not None and cause.seat not in actors.readers(state):
                due = max(due, day + timedelta(days=1))
            if cause is not None and not answer.helps and toward is not None:
                drop = ShiftDisposition(of=figure, toward=toward, change=-1)
                out.append(shift(world, drop, seat))
            out.append(
                ev.AnswerPlanned(
                    figure=figure,
                    key=answer.key,
                    on=day,
                    due=due,
                    cause=cause.order_id if cause is not None else None,
                    toward=toward,
                )
            )
    return out


def _days(first: date, last: date) -> Iterator[date]:
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def _said(effect: Effect) -> str:
    if isinstance(effect, MakeStatement):
        return effect.theme
    if isinstance(effect, Deal):
        return "; ".join(x for x in (", ".join(effect.offer), ", ".join(effect.ask)) if x) or words(
            effect.kind
        )
    return words(effect.kind)


def _approach(
    state: State, figure: EntityId, answer: Answer, deal: Deal, day: date
) -> ev.MandateIssued | str:
    """A deal put to the player who holds its other side, as an opening on their desk,
    or why it could not be put (their desk is full)."""
    seat = next(
        s for s in sorted(actors.readers(state)) if state.seats[s].embodies == deal.counterparty
    )
    live = sum(
        m.seat_id == seat
        and m.status is MandateStatus.LIVE
        and m.mandate_id != opening_id(state.campaign_id, seat)
        for m in state.mandates.values()
    )
    if live >= MANDATE_CAP:
        return "their desk is full"
    who = state.entities[figure].name
    asks = ", ".join(deal.ask) or "nothing in return"
    offers = ", ".join(deal.offer) or "nothing"
    text = f"{who} asks for {asks}, and offers {offers}. Open talks with them to take it up."
    return ev.MandateIssued(
        mandate=Mandate(
            mandate_id=MandateId(
                derived_id(state.campaign_id, "approach", figure, answer.key, day.isoformat())
            ),
            seat_id=seat,
            kind=MandateKind.OPPORTUNITY,
            text=text[:400],
            condition=Ordered(person=deal.counterparty, effect=EffectKind.DEAL),
            issued=day,
            expires=day + timedelta(days=APPROACH_DAYS),
            scope=private_to(seat),
        )
    )


def _twin(state: State, seat: SeatId, lever: str, params: dict[str, int | str]) -> bool:
    return any(
        o.issuer == seat and o.status not in SETTLED and (o.lever, o.params) == (lever, params)
        for o in state.orders.values()
    )


def _make(state: State, figure: EntityId, answer: Answer, day: date) -> list[ev.Payload]:
    """The order, or the approach, the answer files on ``day``, then its record."""
    seat = _seat(state, figure)
    oid = OrderId(derived_id(state.campaign_id, "answer", figure, answer.key, day.isoformat()))

    def made(**kw: object) -> ev.AnswerMade:
        return ev.AnswerMade(figure=figure, key=answer.key, on=day, **kw)

    if seat is None or _retired(state, answer):
        return [made(refusal="no longer able to act")]
    act = answer.act
    if act.lever is not None:
        card = state.cards[figure]
        lever = next((x for x in card.levers if x.name == act.lever), None)
        if lever is None:
            return [made(refusal="no such form")]
        refused = order_refusal(state, seat, act.lever, {k: str(v) for k, v in act.params.items()})
        if refused:
            return [made(refusal=refused[:60])]
        if _twin(state, seat, act.lever, dict(act.params)):
            return [made(refusal="the same order is still moving")]
        order = Order(
            order_id=oid,
            issuer=seat,
            lever=act.lever,
            pipeline=lever.pipeline,
            params=dict(act.params),
            filed=day,
        )
        return [ev.OrderDrafted(order=order), made(order=oid)]
    assert act.effect is not None
    effect = act.effect
    if isinstance(effect, Deal) and effect.counterparty in {
        state.seats[s].embodies for s in actors.readers(state)
    }:
        put = _approach(state, figure, answer, effect, day)
        if isinstance(put, str):
            return [made(refusal=put)]
        return [put, made(mandate=put.mandate.mandate_id)]
    routing = route(state, seat, Ask(ask=_said(effect), effect=effect), day)
    if routing.part is None:
        return [made(refusal=routing.refusal[:60] or "no route")]
    routed = RoutedOrder(order_id=oid, issuer=seat, filed=day, parts=(routing.part,))
    return [ev.OrderRouted(order=routed), made(order=oid)]


def make(state: State, day: date) -> list[ev.Payload]:
    """The oldest answer due by ``day`` and not yet made, within the caps: call again
    on the state after it until it returns nothing. One left over by a cap waits for
    the next day."""
    due = sorted(
        (log.due, figure, key)
        for figure, held in state.answers.items()
        for key, log in held.items()
        if log.made is None and log.due <= day
    )
    today = {
        figure for figure, held in state.answers.items() for log in held.values() if log.made == day
    }
    for _, figure, key in due:
        if len(today) >= DAILY:
            break
        if figure in today:
            continue
        answer = next((a for a in state.cards[figure].answers if a.key == key), None)
        if answer is None:
            return [ev.AnswerMade(figure=figure, key=key, on=day, refusal="withdrawn")]
        return _make(state, figure, answer, day)
    return []


__all__ = ["DAILY", "Act", "acts_on", "answerers", "make", "matches", "plan"]
