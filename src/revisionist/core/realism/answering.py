"""People nobody plays answer what is done to them (strategy step 2).

Each day, after the day's acts have landed, every unplayed person with written answers
looks at what landed: a form someone filed that went through, or a typed act that was
carried out. An answer whose trigger matches, whose stance gate holds and whose
cooldown has run is taken up and falls due some days later; on that day the person
files an order of their own through the same routing as a player's; an order a lock
would hold is dropped with the router's refusal (LCK). Taking up an
answer to someone's act costs that someone a point of the person's regard, unless the
answer is a good turn. Code decides throughout; no model is asked.

Caps: one answer made per person per day, ``DAILY`` per game per day. An answer set off
by another unplayed person's act is not made the day it is taken up, so one day's acts
never chain.

With ``ask_answers`` on, the same people answer an ask (AAK): an ask for a held order put
to a person no seat with a desk holds falls due ``ANSWER_DAYS`` world days after it was
made, and on that day the person's card grants or declines it from state, once. A grant
opens nothing itself: the person files their own order through today's routing, and the
lock opens from state once that order has taken effect. A person a seat holds is never
answered for, so the asker is told neither the card's answer (``told``) nor who holds
the decider (``as_asked``): it learns only what the decider's own order does.
"""

from collections.abc import Iterable, Iterator, Mapping
from datetime import date, timedelta
from typing import NamedTuple

from revisionist.core import events as ev
from revisionist.core.goals import Ordered
from revisionist.core.ids import EntityId, MandateId, OrderId, SeatId, derived_id
from revisionist.core.realism import actors, laws, locks, opponents
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
from revisionist.core.realism.card import Lever, ParamKind, words
from revisionist.core.realism.effect import (
    Deal,
    Effect,
    EffectKind,
    EstimatedEffect,
    MakeStatement,
    RoutedOrder,
    SetEngagement,
    ShiftDisposition,
)
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.pipeline import SETTLED, Order, OrderStatus
from revisionist.core.realism.process import ANSWER_DAYS
from revisionist.core.realism.resolvers import friction, settled_on
from revisionist.core.realism.route import NOBODY, held, route
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


def answerers(state: State) -> list[EntityId]:
    """The unplayed people with written answers, in id order."""
    played = {state.seats[s].embodies for s in actors.readers(state)}
    return sorted(p for p, card in state.cards.items() if card.answers and p not in played)


def _counterparty(answer: Answer) -> EntityId | None:
    effect = answer.act.effect
    return effect.counterparty if isinstance(effect, Deal) else None


def plan(
    state: State, day: date, since: date | None = None, between: frozenset[OrderId] = frozenset()
) -> list[ev.Payload]:
    """The answers taken up on ``day``: set off by what landed on ``day``, by an act in
    ``between`` that landed from ``since`` on (a form carried through between ticks,
    which no earlier day's walk saw), or by their cadence. Each is preceded, where it
    costs regard, by the change to the person's regard for whoever acted."""
    landed = [
        a
        for d in _days(since or day, day)
        for a in acts_on(state, d)
        if d == day or a.order_id in between
    ]
    world = PassWorld(state)
    out: list[ev.Payload] = []
    for figure in answerers(state):
        seat = actors.seat_of(state, figure)
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
    seat = actors.seat_of(state, figure)
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
        if locks.seen_lock(state, seat, order) is not None:
            return [made(refusal=NOBODY[:60])]
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
    ask = Ask(ask=_said(effect), effect=effect)
    routing = route(state, seat, ask, day)
    if routing.part is None:
        return [made(refusal=routing.refusal[:60] or "no route")]
    if held(state, seat, ask, day) is not None:
        return [made(refusal=NOBODY[:60])]
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


# --- An ask to a person nobody plays (AAK) --------------------------------------------

GRANT_AT = 1
"""The score at which the card grants an ask [proposed]: the middle of the policy's range."""
TOPIC_POINTS = 2
"""What a held order that touches a topic the card wants adds, or one it holds to takes
[proposed]."""
CARRIED_FREE = 2
"""The orders a person carries before each further one takes a point from the score
[proposed]."""


def asks_on(state: State) -> bool:
    from revisionist.core.state import Rule

    return Rule.ASK_ANSWERS in state.rules and locks.on(state)


def _played(state: State, person: EntityId) -> bool:
    return any(state.seats[s].embodies == person for s in actors.readers(state))


def asks_due(state: State, day: date) -> list[locks.Asked]:
    """The asks due by ``day`` and not yet answered, oldest first: each put to a person no
    seat with a desk holds, falling due ``ANSWER_DAYS`` world days after it was made. An
    ask to a person a seat holds, the aide's included, is never answered for."""
    if not asks_on(state):
        return []
    return sorted(
        (
            a
            for a in state.asked.values()
            if a.answered is None
            and a.order_id in state.held
            and a.on + timedelta(days=ANSWER_DAYS) <= day
            and not _played(state, a.to)
        ),
        key=lambda a: (a.on, a.order_id),
    )


def told(state: State, row: str | None) -> bool:
    """Whether the answer to an ask on the lock row keyed ``row`` is told to the asker:
    only on a row decided by its kind of question (``locks.by_kind``), which is answered
    on its due day whoever holds the decider. On any other row a person a seat holds is
    never answered for, so a card's answer told would say the decider is run by code."""
    found = next((r for r in state.locks if r.key == row), None)
    return found is not None and locks.by_kind(state, found)


def as_asked(state: State, asked: locks.Asked, seat: SeatId) -> locks.Asked:
    """``asked`` as ``seat`` holds it. With ``ask_answers`` on, the asker's own record
    names no seat it went before and no answer, the same whether a person or code holds
    the decider; a seat the ask was put before holds it whole."""
    if not asks_on(state) or seat != asked.asker or seat in (asked.seat, *asked.seats):
        return asked
    return asked.model_copy(update={"seat": None, "seats": (), "answered": None, "granted": None})


def ask_deciders(state: State, day: date) -> list[EntityId]:
    """The people who answer an ask on ``day``, so each has a seat to file from."""
    return sorted({a.to for a in asks_due(state, day)})


def _regard(state: State, one: EntityId, other: EntityId) -> int:
    return next(
        (r.disposition for r in state.relationships.values() if {r.a, r.b} == {one, other}),
        0,
    )


def _words(*texts: object) -> set[str]:
    return {w for t in texts for w in str(t).lower().replace("_", " ").split() if len(w) >= 4}


def _touches(state: State, held: locks.HeldOrder, keys: Iterable[str]) -> bool:
    """Whether the held order touches one of the topics ``keys``: by its form and the
    values it carries, or by its asks' typed effects. Never by an ask's own words."""
    topics = [state.topics[k] for k in keys if k in state.topics]
    form = held.form
    if form is not None:
        return any(t.touched(form.lever, (), _words(*form.params.values())) for t in topics)
    effects = [a.effect for a in held.asks if a.effect is not None]
    kinds = {e.kind for e in effects}
    said = _words(*(v for e in effects for v in e.model_dump(mode="json").values()))
    return any(t.touched(None, kinds, said) for t in topics)


def _carried(state: State, person: EntityId) -> int:
    seat = actors.seat_of(state, person)
    moving = sum(o.issuer == seat and o.status not in SETTLED for o in state.orders.values())
    routed = sum(
        o.issuer == seat and any(p.applied is None for p in o.parts) for o in state.routed.values()
    )
    return moving + routed


def ask_score(state: State, asked: locks.Asked) -> int:
    """The card's score for an ask: its person's regard for the asker, plus
    ``TOPIC_POINTS`` when the held order touches a topic the card wants and less as much
    when it touches one it holds to, plus a draw from -2 to 2 seeded by the campaign and
    the order's id, less one for each order the person carries past ``CARRIED_FREE``."""
    card = state.cards.get(asked.to)
    held = state.held[asked.order_id]
    score = _regard(state, asked.to, asked.by)
    if card is not None:
        score += TOPIC_POINTS * _touches(state, held, card.wants)
        score -= TOPIC_POINTS * _touches(state, held, card.holds_to)
    score += friction(state, asked.order_id, "ask", n=5) - 2
    return score - max(0, _carried(state, asked.to) - CARRIED_FREE)


def grants(state: State, asked: locks.Asked) -> bool:
    return ask_score(state, asked) >= GRANT_AT


def answer_ask(state: State, day: date) -> list[ev.Payload]:
    """The oldest ask due by ``day``, answered: the answer, then on a grant the order its
    person files. Call again on the state after it until it returns nothing."""
    due = asks_due(state, day)
    if not due:
        return []
    asked = due[0]
    granted = grants(state, asked)
    out: list[ev.Payload] = [
        ev.AskAnswered(order_id=asked.order_id, asker=asked.asker, on=day, granted=granted)
    ]
    return out + (_granted(state, asked, day) if granted else [])


def _granted(state: State, asked: locks.Asked, day: date) -> list[ev.Payload]:
    """What the person files on a grant, through today's routing: the form the row's
    posture names with its values, or its written engagement; for a law, the bill by the
    person's own form, at the first of each other choice. Nothing when the row has no
    condition, or the filing is refused: the lock stays as it is."""
    h = state.held[asked.order_id]
    row = next((r for r in state.locks if r.key == h.row), None)
    seat = actors.seat_of(state, asked.to)
    if row is None or row.when is None or seat is None:
        return []
    oid = OrderId(derived_id(state.campaign_id, "ask-answer", asked.order_id))
    when = row.when
    if isinstance(when, locks.LawNotInForce):
        found = _bill(state, asked.to, h.decider, when.clause)
        return _form(state, seat, oid, *found, day) if found is not None else []
    if when.form is not None:
        return _form(state, seat, oid, when.form, {**when.where, **when.posture}, day)
    assert when.zone is not None and when.rule is not None
    effect = SetEngagement(zone=when.zone, rule=when.rule)
    ask = Ask(ask=words(effect.kind), effect=effect)
    routing = route(state, seat, ask, day)
    if routing.part is None or held(state, seat, ask, day) is not None:
        return []
    return [
        ev.OrderRouted(
            order=RoutedOrder(order_id=oid, issuer=seat, filed=day, parts=(routing.part,))
        )
    ]


def _form(
    state: State,
    seat: SeatId,
    oid: OrderId,
    name: str,
    params: Mapping[str, int | str],
    day: date,
) -> list[ev.Payload]:
    card = state.cards[state.seats[seat].embodies]
    lever = next((x for x in card.levers if x.name == name), None)
    if lever is None or order_refusal(state, seat, name, {k: str(v) for k, v in params.items()}):
        return []
    if _twin(state, seat, name, dict(params)):
        return []
    order = Order(
        order_id=oid,
        issuer=seat,
        lever=name,
        pipeline=lever.pipeline,
        params=dict(params),
        filed=day,
    )
    if locks.seen_lock(state, seat, order) is not None:
        return []
    return [ev.OrderDrafted(order=order)]


def _bill(
    state: State, person: EntityId, decider: locks.Decider, clause: str
) -> tuple[str, dict[str, int | str]] | None:
    """The person's own form that sends the bill of the law carrying ``clause`` for the
    decider's nation, and its values: the bill, and the first of every other choice."""
    from revisionist.core.realism.war import polity_of

    nation = decider.nation or polity_of(state, person)
    if laws.on(state):
        keys = [law.key for law in laws.carrying(state, clause) if law.nation == nation]
    else:
        from revisionist.core.realism.resolvers.votes import HISTORICAL

        keys = [
            k for k, m in sorted(HISTORICAL.items()) if clause in {c.subject for c in m.clauses}
        ]
    card = state.cards.get(person)
    for key in keys:
        for lever in card.levers if card is not None else ():
            values = _values(lever, key)
            if lever.resolver == "votes" and values is not None:
                return lever.name, values
    return None


def _values(lever: Lever, key: str) -> dict[str, int | str] | None:
    """A form's values that name ``key`` in one of its choices, and the first choice (or
    the floor) of every other; None when no choice names it, or a value cannot be set."""
    out: dict[str, int | str] = {}
    named = False
    for spec in lever.params:
        if spec.kind is ParamKind.ENUM and key in spec.choices and not named:
            out[spec.name], named = key, True
        elif spec.kind is ParamKind.ENUM:
            out[spec.name] = spec.choices[0]
        elif spec.kind is ParamKind.INT and spec.lo is not None:
            out[spec.name] = spec.lo
        else:
            return None
    return out if named else None


__all__ = [
    "CARRIED_FREE",
    "DAILY",
    "GRANT_AT",
    "TOPIC_POINTS",
    "Act",
    "acts_on",
    "answer_ask",
    "answerers",
    "as_asked",
    "ask_deciders",
    "ask_score",
    "asks_due",
    "asks_on",
    "grants",
    "make",
    "matches",
    "plan",
    "told",
]
