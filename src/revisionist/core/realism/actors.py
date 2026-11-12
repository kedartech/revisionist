"""Seats for the people nobody plays, so their acts go through the same routing as a
player's. An AI seat is addressed nothing: papers, reports and mandates go to seats with a desk."""

from collections.abc import Iterable

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, SeatId, derived_id
from revisionist.core.ontology import Controller, Seat, SeatKind
from revisionist.core.state import State


def readers(state: State) -> frozenset[SeatId]:
    """The seats with a desk, the only ones anything is issued to: every seat but
    the AI seats of people nobody plays."""
    return frozenset(s.seat_id for s in state.seats.values() if s.kind is not SeatKind.FACTION)


def seat_of(state: State, person: EntityId) -> SeatId | None:
    """The AI seat of a person nobody plays."""
    held = [s for s in state.seats.values() if s.embodies == person]
    if len(held) == 1 and held[0].kind is SeatKind.FACTION:
        return held[0].seat_id
    return None


def unseated(state: State, people: Iterable[EntityId]) -> list[ev.SeatCreated]:
    """An AI seat for each of ``people`` who has a card and no seat, in person order."""
    seated = {s.embodies for s in state.seats.values()}
    return [
        ev.SeatCreated(
            seat=Seat(
                seat_id=SeatId(derived_id(state.campaign_id, "seat", person)),
                kind=SeatKind.FACTION,
                name=state.entities[person].name,
                embodies=person,
                controller=Controller.AI,
                slots=0,
            )
        )
        for person in sorted(set(people))
        if person in state.cards and person not in seated
    ]


__all__ = ["readers", "seat_of", "unseated"]
