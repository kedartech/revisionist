"""The People roster of ``view.realism``: everyone with an office, as the seat's staff
know them.

Three groups: the leaders weighed against the seat (``opponents.figures``), the seat's
own chain and inner circle, and everyone else. Each metric is a meter in five steps
with a word, the day of the evidence it rests on and a confidence from that day's age.
The stance is fogged exactly as the opponents list fogs it. Regard comes only from a
relationship in the seat's view, and reliability only from the seat's own orders the
person carried. No score, card policy or other seat's page leaves the engine here.
"""

from datetime import date
from typing import Literal

from revisionist.core.ids import EntityId, SeatId
from revisionist.core.ontology import EntityKind, EntityStatus, Relationship
from revisionist.core.realism import opponents
from revisionist.core.realism.card import Tie, words
from revisionist.core.realism.effect import Fidelity
from revisionist.core.realism.reach import tie
from revisionist.core.realism.stance import RANK, Stance, band
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State, View
from revisionist.engine.web.realism_api import People, PeopleMeter, PersonLine
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


def _line(state: State, view: View, person: EntityId, today: date) -> PersonLine:
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
    return PersonLine(
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
    )


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
        out[group].append(_line(state, view, person, today))
    out["opponents"].sort(key=lambda p: (p["stance"]["step"] if p["stance"] else 6, p["name"]))
    out["yours"].sort(key=lambda p: p["name"])
    out["others"].sort(key=lambda p: p["name"])
    return out


__all__ = ["seat_people"]
