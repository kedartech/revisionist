"""Wars, public news and the papers that print it (engine v2, consequences).

A war is a public fact between two polities. A news event is the structured public
fact of something that happened; each seat's press later words it in its own
outlet's voice, so the event itself never carries prose.
"""

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism.document import BodyField

if TYPE_CHECKING:
    from revisionist.core.state import State, View


class War(Model):
    war_id: Label
    """``war_id_for(a, b)``: the same for the pair in either order."""
    a: EntityId
    """The declaring polity."""
    b: EntityId
    """The target polity."""
    since: date
    declared_by: EntityId
    """The person who issued the declaration."""


class NewsTopic(StrEnum):
    WAR_DECLARED = "war_declared"
    STATEMENT = "statement"
    APPOINTMENT = "appointment"
    DEAL = "deal"
    CONTACT = "contact"
    VOTE = "vote"


class NewsEvent(Model):
    """A public event, as structured public facts only. Never prose. One per event;
    each seat's press later words it in its own outlet's voice."""

    news_id: Label
    on: date
    topic: NewsTopic
    subject: EntityId
    obj: EntityId | None = None
    facts: tuple[BodyField, ...] = ()
    headline: Label
    """Neutral, plain words."""


class Outlet(Model):
    """A seat's newspaper: the voice its press is written in."""

    outlet_id: EntityId
    """An org entity in the world file."""
    polity: EntityId
    name: str
    voice: str = Field(max_length=300)


def war_id_for(a: EntityId, b: EntityId) -> Label:
    return f"{min(a, b)}|{max(a, b)}"


def at_war(world: "State | View", a: EntityId, b: EntityId) -> bool:
    return war_id_for(a, b) in world.wars


def polity_of(state: "State", entity: EntityId) -> EntityId | None:
    """The entity itself if it is a polity, else its nearest polity ancestor."""
    seen: set[EntityId] = set()
    here = state.entities.get(entity)
    while here is not None and here.entity_id not in seen:
        if here.kind is EntityKind.POLITY:
            return here.entity_id
        seen.add(here.entity_id)
        here = state.entities.get(here.parent) if here.parent is not None else None
    return None


def outlet_for(state: "State", seat: SeatId) -> Outlet | None:
    """The outlet of the polity the person the seat embodies belongs to."""
    held = state.seats.get(seat)
    if held is None:
        return None
    polity = polity_of(state, held.embodies)
    return next((o for o in state.outlets.values() if o.polity == polity), None)


__all__ = [
    "NewsEvent",
    "NewsTopic",
    "Outlet",
    "War",
    "at_war",
    "outlet_for",
    "polity_of",
    "war_id_for",
]
