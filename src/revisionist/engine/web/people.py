"""The People roster of ``view.realism``: everyone with an office, as the seat's staff
know them.

Three groups: the leaders weighed against the seat (``opponents.figures``), the seat's
own chain and inner circle, and everyone else. Each metric is a meter in five steps
with a word, the day of the evidence it rests on and a confidence from that day's age.
The stance is fogged exactly as the opponents list fogs it. Regard comes only from a
relationship in the seat's view, and reliability only from the seat's own orders the
person carried. No score or other seat's page leaves the engine here, and a card's
values leave it only for the seat's own chain and inner circle, as below.

The figure card's data (plan item "the figure card's data"; board design §4) adds, for
everyone: the seat's own orders waiting on the person, what they did with the seat's
orders at their step and how fast, and their body, and for the inner circle the
channel. Orders are read from ``view.orders`` (the seat's own only) and the
pipelines from ``state``, as the court reads them. A hold or a leak is the issuer's to
know only once its reply has arrived (``UNSEEN``). Card values
(loyalty, competence, the topics wanted and held to) and standing, which reads the
card's hidden rank, go to the seat's own chain and inner circle only; for anyone else
those keys are absent. A leader weighed against the seat gets a power meter from rank
and the forces the seat's own pages place under them (approved; first-run change 14).
The staff read on an order mirrors the pipeline policy without its draw.
"""

from datetime import date
from typing import Literal

from revisionist.core.ids import EntityId, SeatId
from revisionist.core.ontology import EntityKind, EntityStatus, Relationship
from revisionist.core.realism import opponents
from revisionist.core.realism.card import SeatCard, Tie, words
from revisionist.core.realism.effect import Fidelity
from revisionist.core.realism.geography import FORCES
from revisionist.core.realism.pipeline import (
    ADVANCES,
    Order,
    OrderStatus,
    StepAction,
    StepOutcome,
)
from revisionist.core.realism.pipelines import (
    FREE_ORDERS,
    STALL_AT,
    _interest,
    reply_doc_id,
    waiting_on_human,
)
from revisionist.core.realism.reach import tie, transit_days
from revisionist.core.realism.stance import RANK, Stance, band
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State, View
from revisionist.engine.web.destinations import latest_sightings
from revisionist.engine.web.realism_api import (
    People,
    PeopleMeter,
    PersonChannel,
    PersonHold,
    PersonLine,
    PersonTally,
)
from revisionist.engine.web.threats import DATED_DAYS, FIRM_DAYS, _evidence

REGARD: dict[Stance, str] = {
    Stance.HOSTILE: "Hostile",
    Stance.OBSTRUCTING: "Cool",
    Stance.NEUTRAL: "Indifferent",
    Stance.COOPERATIVE: "Warm",
    Stance.ALIGNED: "Devoted",
}
"""Regard in words, by the stance band its disposition falls in [proposed]."""

CARRIED: dict[Fidelity | None, int] = {
    Fidelity.FULL: 4,
    Fidelity.LOOSE: 3,
    Fidelity.SLOW: 2,
    Fidelity.PARTIAL: 1,
    None: 0,
}
"""What one carried order counts toward reliability; None is a refusal [proposed]."""
RELIABLE = ("Unreliable", "Poor", "Uneven", "Sound", "Dependable")

STANDING = ("Minor", "Junior", "Established", "Senior", "Paramount")
"""Rank 0 and 1 are the first step, then one step a rank [proposed]."""
POWER = ("Slight", "Modest", "Considerable", "Great", "Overwhelming")
FORCES_FOR_A_STEP = 3
"""Forces of a leader's country the seat's pages place before power reads a step up
[proposed]."""
LOYALTY = ("Disloyal", "Doubtful", "Steady", "Loyal", "Devoted")
LOYALTY_FLOOR = (-3, -1, 0, 2, 5)
"""The highest card loyalty each step takes, -5 to 5 [proposed]."""
COMPETENCE = ("Poor", "Limited", "Capable", "Able", "Outstanding")
"""Card competence 0 and 1 are the first step, then one step a point [proposed]."""
PACE = ("Very late", "Late", "Slow", "On time", "Quick")
PACE_UNDER = (0.75, 1.25, 1.75, 2.25)
"""Days taken over days stated, on average: under the first is quick, then on time,
slow and late; past the last, very late [proposed]."""

FRICTION_LOW = -3
"""The worst draw the pipeline policy adds to a decision (``pipelines._policy``)."""
Read = Literal["likely to pass it", "may hold it", "likely to hold or refuse it"]
LIKELY_HELD = -3
"""At or below this, half the policy's ten draws or more hold or refuse the order."""

UNSEEN = frozenset({StepAction.STALL, StepAction.LEAK})
"""What the order tracker hides from the issuer (``realism_snapshot._HIDDEN``, which
imports this module): known here only from the reply that says so."""

TALLY: dict[StepAction, str] = {
    StepAction.PASS: "passed",
    StepAction.EXPEDITE: "hurried",
    StepAction.STALL: "held",
    StepAction.AMEND: "amended",
    StepAction.REFUSE: "refused",
    StepAction.LEAK: "leaked",
}

UNTESTED: PeopleMeter = {"step": None, "word": "Untested", "as_of": None, "confidence": None}
UNKNOWN: PeopleMeter = {"step": None, "word": "Unknown", "as_of": None, "confidence": None}


def _meter(step: int, word: str, seen: date | None, today: date) -> PeopleMeter:
    if seen is None:
        return {"step": step, "word": word, "as_of": None, "confidence": None}
    age = (today - seen).days
    return {
        "step": step,
        "word": word,
        "as_of": seen.isoformat(),
        "confidence": "firm" if age <= FIRM_DAYS else "dated" if age <= DATED_DAYS else "old",
    }


def _flat(step: int, scale: tuple[str, ...]) -> PeopleMeter:
    return {"step": step, "word": scale[step - 1], "as_of": None, "confidence": None}


def _regard(rel: Relationship | None, seen: date | None, today: date) -> PeopleMeter:
    if rel is None:
        return UNKNOWN
    stance = band(rel.disposition)
    return _meter(RANK[stance] + 1, REGARD[stance], seen, today)


def _reliability(view: View, person: EntityId, today: date) -> PeopleMeter:
    done = [
        (part.executed, CARRIED[part.fidelity])
        for order in view.routed.values()
        for part in order.parts
        if part.executor == person and part.executed is not None
    ]
    if not done:
        return UNTESTED
    step = round(sum(n for _, n in done) / len(done))
    return _meter(step + 1, RELIABLE[step], max(d for d, _ in done), today)


def _last_answer(view: View, person: EntityId) -> str | None:
    answers = [
        (part.decided, part.accepted)
        for order in view.routed.values()
        for part in order.parts
        if part.target == person and part.decided is not None
    ]
    if not answers:
        return None
    on, accepted = max(answers, key=lambda a: a[0])
    return f"{'Went along' if accepted else 'Refused'}, {on:%-d %B %Y}"


def _arrived(order: Order, before: int | None = None) -> date:
    """The day the order reached the step of its outcome ``before`` (its current step
    when None): the latest earlier outcome at an earlier step, or the filing date. A
    stall never moves it, so the issuer learns nothing from the day."""
    upto = order.outcomes if before is None else order.outcomes[:before]
    step = order.step if before is None else order.outcomes[before].step
    moved = [o.on for o in upto if o.step < step]
    return moved[-1] if moved else order.filed


def _at(state: State, order: Order) -> EntityId | None:
    """Who holds a moving order now; None once it is settled or off its pipeline."""
    steps = state.pipelines[order.pipeline].steps if order.pipeline in state.pipelines else ()
    if order.status is not OrderStatus.MOVING or order.step >= len(steps):
        return None
    return steps[order.step].person


def _told(view: View, order: Order, n: int, outcome: StepOutcome) -> bool:
    """The seat knows what the step did: it shows on the order, or the reply came."""
    return (
        outcome.action not in UNSEEN
        or reply_doc_id(view.campaign_id, order.order_id, n) in view.documents
    )


def _read(state: State, view: View, order: Order, person: EntityId) -> Read:
    """What the staff expect of ``person`` with ``order``: the pipeline policy's score
    with no draw, the load counted from the seat's own orders only. A step that cannot
    hold an order (every clerical step) passes it."""
    step = state.pipelines[order.pipeline].steps[order.step]
    if not {StepAction.STALL, StepAction.REFUSE} & step.allowed:
        return "likely to pass it"
    card = state.cards.get(person)
    loyalty = card.loyalty if card is not None else 0
    load = sum(
        1 for o in view.orders.values() if o.order_id != order.order_id and _at(state, o) == person
    )
    score = loyalty + _interest(state, order, card) - max(0, load - FREE_ORDERS)
    if score + FRICTION_LOW > STALL_AT:
        return "likely to pass it"
    return "likely to hold or refuse it" if score <= LIKELY_HELD else "may hold it"


def _holds(state: State, view: View, person: EntityId, today: date, own: bool) -> list[PersonHold]:
    levers = {x.name: x for x in view.desk.levers} if view.desk is not None else {}
    held = [o for o in view.orders.values() if _at(state, o) == person]
    out: list[PersonHold] = []
    for order in sorted(held, key=lambda o: (_arrived(o), o.order_id)):
        since = _arrived(order)
        lever = levers.get(order.lever)
        out.append(
            PersonHold(
                id=order.order_id,
                label=(lever.label or words(lever.name))
                if lever is not None
                else words(order.lever),
                since=since.isoformat(),
                held_days=max(0, (today - since).days),
                days=state.pipelines[order.pipeline].steps[order.step].days,
                read=(
                    _read(state, view, order, person)
                    if own and not waiting_on_human(state, order)
                    else None
                ),
            )
        )
    return out


def _record(
    state: State, view: View, person: EntityId, today: date
) -> tuple[PersonTally, PeopleMeter]:
    """What the person did with the seat's own orders at their step, and their pace."""
    tally: PersonTally = {
        "passed": 0,
        "hurried": 0,
        "held": 0,
        "amended": 0,
        "refused": 0,
        "leaked": 0,
    }
    ratios: list[float] = []
    last: date | None = None
    for order in view.orders.values():
        steps = state.pipelines[order.pipeline].steps if order.pipeline in state.pipelines else ()
        for n, outcome in enumerate(order.outcomes):
            if outcome.person != person or not _told(view, order, n, outcome):
                continue
            tally[TALLY[outcome.action]] += 1  # type: ignore[literal-required]
            stated = steps[outcome.step].days if outcome.step < len(steps) else None
            if outcome.action in ADVANCES and stated is not None:
                taken = (outcome.on - _arrived(order, n)).days
                ratios.append(taken / max(1, stated))
                last = outcome.on if last is None else max(last, outcome.on)
    if not ratios:
        return tally, UNTESTED
    mean = sum(ratios) / len(ratios)
    step = len(PACE) - sum(1 for edge in PACE_UNDER if mean >= edge)
    return tally, _meter(step, PACE[step - 1], last, today)


def _channel(view: View, person: EntityId) -> PersonChannel | None:
    circle = view.desk.inner_circle if view.desk is not None else ()
    found = next((c.channel for c in circle if c.person == person), None)
    return None if found is None else {"channel": found.value, "days": transit_days(found)}


def _power(state: State, view: View, person: EntityId, rank: int, today: date) -> PeopleMeter:
    """Rank in five steps, one higher once the seat's own pages place enough forces of
    the leader's country."""
    country = polity_of(state, person)
    seen = [
        doc.issued
        for _, doc, line in latest_sightings(view).values()
        if line.sight is not None
        and line.sight.kind in FORCES
        and country is not None
        and line.sight.side == country
    ]
    enough = len(seen) >= FORCES_FOR_A_STEP
    step = min(max(1, rank) + enough, len(POWER))
    return _meter(step, POWER[step - 1], max(seen) if enough else None, today)


def _card_values(state: State, card: SeatCard) -> dict[str, object]:
    loyalty = next(i for i, top in enumerate(LOYALTY_FLOOR) if card.loyalty <= top) + 1
    competence = max(1, card.competence)
    named = state.topics
    return {
        "loyalty": _flat(loyalty, LOYALTY),
        "competence": _flat(competence, COMPETENCE),
        "wants": [named[k].name for k in card.wants if k in named],
        "holds_to": [named[k].name for k in card.holds_to if k in named],
    }


def _line(
    state: State,
    view: View,
    person: EntityId,
    today: date,
    group: Literal["opponents", "yours", "others"],
) -> PersonLine:
    me = view.me.embodies
    history = state.stances.get(view.viewer, {}).get(person, ())
    rel = next((r for r in view.relationships.values() if {r.a, r.b} == {person, me}), None)
    seen: date | None = None
    if history or rel is not None:
        seen = _evidence(state, view, person, history[0].on if history else date.min)
        seen = None if seen == date.min else seen
    stance: PeopleMeter | None = None
    trend: Literal["worse", "better", "steady"] | None = None
    if history and seen is not None:
        known = [s for s in history if s.on <= seen] or [history[0]]
        believed = known[-1].stance
        stance = _meter(RANK[believed] + 1, words(believed.value), seen, today)
        drift = 0 if len(known) < 2 else RANK[believed] - RANK[known[-2].stance]
        trend = "worse" if drift < 0 else "better" if drift > 0 else "steady"
    theirs, mine = polity_of(state, person), polity_of(state, me)
    holds = _holds(state, view, person, today, own=group == "yours")
    tally, pace = _record(state, view, person, today)
    rank = state.cards[person].reach.rank
    parent = view.entities[person].parent
    body = view.entities.get(parent) if parent is not None else None
    out = PersonLine(
        person=person,
        name=view.entities[person].name,
        office=view.cards[person].office,
        stance=stance,
        trend=trend,
        over=[x.over for x in opponents.conflicts(state, person, me)] if history else [],
        at_war=theirs is not None and any({w.a, w.b} == {theirs, mine} for w in view.wars.values()),
        last_answer=_last_answer(view, person),
        regard=_regard(rel, seen, today),
        reliability=_reliability(view, person, today),
        holds=holds,
        load=len(holds),
        tally=tally,
        pace=pace,
        bloc=body.name if body is not None else None,
        channel=_channel(view, person),
        power=_power(state, view, person, rank, today) if group == "opponents" else None,
    )
    if group == "yours":
        out["standing"] = _flat(max(1, rank), STANDING)
        card = state.cards[person]
        if isinstance(card, SeatCard):
            out.update(_card_values(state, card))  # type: ignore[typeddict-item]
    return out


def seat_people(state: State, seat: SeatId, view: View) -> People:
    """Every living person with a card face but the seat's own, each in one group,
    the most hostile opponent first and the rest by name."""
    today = view.in_world_date
    out: People = {"opponents": [], "yours": [], "others": []}
    if today is None:
        return out
    me = view.me.embodies
    weighed = state.stances.get(seat, {})
    for person in view.cards:
        entity = view.entities.get(person)
        if (
            person == me
            or entity is None
            or entity.kind is not EntityKind.PERSON
            or entity.status is EntityStatus.DEAD
        ):
            continue
        group: Literal["opponents", "yours", "others"] = (
            "opponents"
            if person in weighed
            else "yours"
            if tie(state, me, person) in (Tie.INNER, Tie.CHAIN)
            else "others"
        )
        out[group].append(_line(state, view, person, today, group))
    out["opponents"].sort(key=lambda p: (p["stance"]["step"] if p["stance"] else 6, p["name"]))
    out["yours"].sort(key=lambda p: p["name"])
    out["others"].sort(key=lambda p: p["name"])
    return out


__all__ = ["seat_people"]
