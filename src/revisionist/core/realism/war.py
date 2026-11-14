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
    EVENT = "event"
    """A history event that fired."""


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


OPPOSITION = "opposition"
"""Entity tag on a paper of the domestic opposition: read second at home, never the home paper."""
NEUTRAL = "neutral"
"""Entity tag on a neutral country's paper: read second where no opposition paper exists."""


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


def paper_of(state: "State", polity: EntityId) -> Outlet | None:
    """The polity's home paper: its first outlet that is not an opposition daily."""
    return next(
        (
            o
            for o in state.outlets.values()
            if o.polity == polity and OPPOSITION not in _tags(state, o.outlet_id)
        ),
        None,
    )


def _tags(state: "State", entity: EntityId) -> frozenset[str]:
    here = state.entities.get(entity)
    return here.tags if here is not None else frozenset()


def outlet_for(state: "State", seat: SeatId) -> Outlet | None:
    """The home paper of the polity the person the seat embodies belongs to."""
    held = state.seats.get(seat)
    if held is None:
        return None
    polity = polity_of(state, held.embodies)
    return paper_of(state, polity) if polity is not None else None


def tagged(state: "State", tag: str, polity: EntityId | None = None) -> Outlet | None:
    """The first outlet carrying ``tag``, of ``polity`` when one is given."""
    return next(
        (
            o
            for o in state.outlets.values()
            if (polity is None or o.polity == polity) and tag in _tags(state, o.outlet_id)
        ),
        None,
    )


__all__ = [
    "NEUTRAL",
    "OPPOSITION",
    "NewsEvent",
    "NewsTopic",
    "Outlet",
    "War",
    "at_war",
    "outlet_for",
    "paper_of",
    "polity_of",
    "tagged",
    "war_id_for",
]
