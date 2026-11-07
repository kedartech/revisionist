"""Who the seat can reach and how (Phase 4 unit S4), from ``core.realism.reach``.

The four groups partition the reachable people in this order: the desk's inner circle, the
seat's own government (same polity, holds an office), a foreign polity, then everyone else.
Only public card faces and the seat's own desk are read; ``reach`` derives who is open and
never shows another card's policy.
"""

from collections.abc import Mapping
from typing import Literal

from revisionist.core.ids import EntityId, SeatId
from revisionist.core.ontology import Entity, EntityKind, EntityStatus
from revisionist.core.project import project
from revisionist.core.realism.card import Tie, words
from revisionist.core.realism.reach import channels_to, tie
from revisionist.core.state import State
from revisionist.engine.web.realism_api import ReachContact, ReachGroups


def _polity(entities: Mapping[EntityId, Entity], who: EntityId) -> EntityId | None:
    node: EntityId | None = who
    while node is not None:
        if entities[node].kind is EntityKind.POLITY:
            return node
        node = entities[node].parent
    return None


def reach(state: State, seat: SeatId) -> ReachGroups:
    """Phase 4 unit S4: everyone the seat can reach, in four groups, channels in words."""
    view = project(state, seat)
    me = view.me.embodies
    groups: ReachGroups = {"inner_circle": [], "government": [], "foreign": [], "other": []}
    if view.entities[me].kind is not EntityKind.PERSON:
        return groups
    my_polity = _polity(view.entities, me)
    people = sorted(
        (
            e
            for e in view.entities.values()
            if e.kind is EntityKind.PERSON
            and e.entity_id != me
            # A dead person takes no channel.
            and e.status is not EntityStatus.DEAD
        ),
        key=lambda e: (e.name, e.entity_id),
    )
    for them in people:
        channels = channels_to(state, me, them.entity_id)
        if not channels:
            continue
        their_polity = _polity(view.entities, them.entity_id)
        group: Literal["inner_circle", "government", "foreign", "other"]
        if tie(state, me, them.entity_id) is Tie.INNER:
            group = "inner_circle"
        elif (
            them.entity_id in view.cards and their_polity is not None and their_polity == my_polity
        ):
            group = "government"
        elif their_polity is not None and their_polity != my_polity:
            group = "foreign"
        else:
            group = "other"
        groups[group].append(
            ReachContact(
                name=them.name,
                title=view.cards[them.entity_id].office if them.entity_id in view.cards else None,
                channels=[words(c) for c in channels],
            )
        )
    return groups


__all__ = ["reach"]
