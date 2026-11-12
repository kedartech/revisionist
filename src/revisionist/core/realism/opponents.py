"""Who stands where toward each seat, and who is actively opposing it.

Worked out in code, day by day, from what the world declares and what has
happened: wars, the sides of open contests, each card's allies and conflicts,
and each person's regard for the seat's person. A change is logged with its
cause, so the chain that turned someone can be read back from the log.

A world whose cards declare no allies and no conflicts has no stances.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import NamedTuple

from revisionist.core import events as ev
from revisionist.core.ids import ContestId, EntityId, OrderId, SeatId
from revisionist.core.ontology import ContestKind
from revisionist.core.realism import actors
from revisionist.core.realism.card import Conflict
from revisionist.core.realism.stance import OPPOSED, Stance, StanceCause, Standing, step
from revisionist.core.realism.war import at_war, polity_of
from revisionist.core.state import State

CAP = 4
"""The most people actively opposing one seat at a time."""
JOIN_PER_WAKE = 1
"""How many may join a seat's opponents in one wake, once it has a list."""
ENEMY, ALLY = -3, 2
"""What a side is worth to the score [proposed]."""
PER_CONFLICT = 2


class Parts(NamedTuple):
    """What a score is made of."""

    side: int
    disposition: int
    conflicts: int
    capped: bool
    """One of the conflicts is irreducible."""

    @property
    def total(self) -> int:
        return self.side + self.disposition - PER_CONFLICT * self.conflicts


def _line(state: State, entity: EntityId) -> tuple[EntityId, ...]:
    """The entity and everything it belongs to, nearest first."""
    out: list[EntityId] = []
    here = state.entities.get(entity)
    while here is not None and here.entity_id not in out:
        out.append(here.entity_id)
        here = state.entities.get(here.parent) if here.parent is not None else None
    return tuple(out)


def _stands(state: State, person: EntityId) -> dict[ContestId, EntityId]:
    """The person's side in each open rivalry: the roster's word, else the side
    they belong to."""
    listed = state.roster.get(person)
    said = {s.contest_id: s.side for s in listed.sides} if listed is not None else {}
    line = _line(state, person)
    out: dict[ContestId, EntityId] = {}
    for cid, contest in state.contests.items():
        if contest.kind is not ContestKind.RIVALRY or contest.decided:
            continue
        side = said.get(cid) or next((e for e in line if e in contest.sides), None)
        if side is not None:
            out[cid] = side
    return out


def _side(state: State, figure: EntityId, person: EntityId) -> int:
    theirs, ours = polity_of(state, figure), polity_of(state, person)
    if theirs is not None and theirs == ours:
        return 0
    if theirs is not None and ours is not None and at_war(state, theirs, ours):
        return ENEMY
    if set(state.cards[figure].allies) & set(_line(state, person)):
        return ALLY
    mine = _stands(state, person)
    if any(mine.get(cid, side) != side for cid, side in _stands(state, figure).items()):
        return ENEMY
    return 0


def _regard(state: State, figure: EntityId, person: EntityId) -> int:
    """Loyalty to a principal, else the relationship, else 0: as an approach weighs it."""
    card = state.cards[figure]
    if person in card.principals:
        return card.loyalty
    return next(
        (r.disposition for r in state.relationships.values() if {r.a, r.b} == {figure, person}),
        0,
    )


def conflicts(state: State, figure: EntityId, person: EntityId) -> tuple[Conflict, ...]:
    """What the figure's card declares against the person or anything they belong to."""
    line = _line(state, person)
    return tuple(x for x in state.cards[figure].opposes if x.against in line)


def parts(state: State, figure: EntityId, seat: SeatId) -> Parts:
    person = state.seats[seat].embodies
    declared = conflicts(state, figure, person)
    return Parts(
        side=_side(state, figure, person),
        disposition=_regard(state, figure, person),
        conflicts=len(declared),
        capped=any(x.irreducible for x in declared),
    )


def figures(state: State, seat: SeatId) -> list[EntityId]:
    """The people weighed against a seat: everyone with an office to act from whom
    no seat with a desk holds."""
    desks = actors.readers(state)
    held = {s.embodies for s in state.seats.values() if s.seat_id in desks}
    held.add(state.seats[seat].embodies)
    return sorted(p for p, card in state.cards.items() if card.authority and p not in held)


def weight(state: State, figure: EntityId, seat: SeatId) -> int:
    """How much an opponent counts: their conflicts with the seat, times their power."""
    card = state.cards[figure]
    power = card.reach.rank + len({f for dm in card.authority for f in dm.forces})
    return (1 + parts(state, figure, seat).conflicts) * power


def _order_behind(
    landed: Sequence[ev.Payload], figure: EntityId, person: EntityId
) -> OrderId | None:
    """The last order whose effects set the pair's relationship: effects land
    before the ``effects_applied`` that closes their part."""
    hit, order = False, None
    for payload in landed:
        if isinstance(payload, ev.RelationshipSet):
            hit = hit or {payload.relationship.a, payload.relationship.b} == {figure, person}
        elif isinstance(payload, ev.EffectsApplied) and hit:
            hit, order = False, payload.order_id
    return order


def _ranked(
    state: State,
    seat: SeatId,
    stances: Mapping[EntityId, Stance],
    wake_start: Mapping[SeatId, tuple[EntityId, ...]] | None,
) -> tuple[EntityId, ...]:
    """Those already opposing stay while they are opposed; the rest join by
    weight while there is room."""
    had = state.opponents.get(seat)
    stay = tuple(f for f in had or () if stances.get(f) in OPPOSED)
    if had is None:
        room = CAP
    else:
        since = had if wake_start is None else wake_start.get(seat)
        joined = JOIN_PER_WAKE if since is None else len(set(had) - set(since))
        room = min(CAP - len(stay), max(0, JOIN_PER_WAKE - joined))
    waiting = sorted(
        (f for f, s in stances.items() if s in OPPOSED and f not in stay),
        key=lambda f: (-weight(state, f, seat), f),
    )
    return (*stay, *waiting[:room])


def settle(
    state: State,
    day: date,
    landed: Sequence[ev.Payload] = (),
    wake_start: Mapping[SeatId, tuple[EntityId, ...]] | None = None,
) -> list[ev.Payload]:
    """Each stance that changed by ``day``, and each seat's opponents where the
    list changed. ``landed`` is what the day's applied effects put in the log, to
    name the order behind a change of regard. ``wake_start`` is each seat's
    opponents when the wake began: at most ``JOIN_PER_WAKE`` join in one wake."""
    if not any(c.allies or c.opposes for c in state.cards.values()):
        return []
    out: list[ev.Payload] = []
    for seat in sorted(actors.readers(state)):
        person = state.seats[seat].embodies
        known = state.stances.get(seat, {})
        stances: dict[EntityId, Stance] = {}
        for figure in figures(state, seat):
            got = parts(state, figure, seat)
            past = known.get(figure, ())
            was = past[-1] if past else None
            stance = step(was.stance if was else None, got.total, capped=got.capped)
            stances[figure] = stance
            if was is not None and stance is was.stance:
                continue
            order = _order_behind(landed, figure, person)
            if was is None:
                cause = StanceCause.START
            elif got.side != was.side and order is None:
                cause = StanceCause.SIDES
            else:
                cause = StanceCause.DISPOSITION
            standing = Standing(
                on=day,
                stance=stance,
                score=max(-20, min(20, got.total)),
                side=got.side,
                disposition=got.disposition,
                cause=cause,
                order=order if cause is StanceCause.DISPOSITION else None,
            )
            out.append(ev.StanceChanged(seat_id=seat, figure=figure, standing=standing))
        active = _ranked(state, seat, stances, wake_start)
        if active != state.opponents.get(seat):
            out.append(ev.OpponentsRanked(seat_id=seat, active=active))
    return out


__all__ = ["CAP", "Parts", "conflicts", "figures", "parts", "settle", "weight"]
