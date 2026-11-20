"""Geography: forces, fronts and routes on the map (realism, Batch 6).

A feature is truth, like a quantity: where a fleet lies, where a front runs,
which ports a convoy route joins. No seat sees one. Seats learn of features
from documents whose feed sights them, so a seat's map is only what its paper
says, as of when it said it.

A force sits at one place and moves by order (the movement resolver). In a world
that names its own piece kinds every force is a ``piece`` whose ``piece`` field holds
the world's kind key; what that kind is (its domain, whether it fights) is asked of
``revisionist.core.realism.kinds``, never read from the key. A front
or a route joins two or more places and moves only with history: a feature's
``legs`` are the moves the record says it made, and an order to a force drops
the ones still to come.
"""

import math
from datetime import date
from enum import StrEnum
from typing import ClassVar

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism.effect import Contingency, Engagement, Posture


class FeatureKind(StrEnum):
    FLEET = "fleet"
    ARMY = "army"
    AIR = "air"
    FRONT = "front"
    ROUTE = "route"
    PIECE = "piece"
    """A piece of one of the world's own kinds, named in ``Feature.piece``."""


FORCES = frozenset({FeatureKind.FLEET, FeatureKind.ARMY, FeatureKind.AIR})
"""The force kinds of a world with no ``piece_kinds``."""

AT_ONE_PLACE = FORCES | {FeatureKind.PIECE}
"""The kinds of feature that stand at one place and move by order."""

SPEED_KM_PER_DAY = {
    FeatureKind.FLEET: 450,  # [proposed] about 10 knots, a fleet's cruising pace
    FeatureKind.ARMY: 25,  # [proposed] a field army on the march
    FeatureKind.AIR: 1000,  # [proposed] an air group rebasing, a day's hops
}


class Leg(Model):
    """One move the record says a feature made."""

    since: date
    places: tuple[EntityId, ...] = Field(min_length=1)
    takes: tuple[EntityId, ...] = ()
    """With ``holders`` on, the territories that pass to the feature's side on ``since``,
    but where a battle has been fought or an enemy land piece stands (HSA)."""
    concealed: bool = False
    """The piece is concealed from ``since`` until it arrives (HSA; read by intelligence)."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"takes", "concealed"})


class Feature(Model):
    feature_id: FeatureId
    kind: FeatureKind
    name: Label
    side: EntityId | None = None
    """The polity or body it belongs to. None for a front, which belongs to both."""
    tier: int = Field(default=0, ge=0, le=5)
    places: tuple[EntityId, ...] = Field(min_length=1)
    """A force: where it is. A front or route: the places it joins, in order."""
    as_of: date
    bound_for: EntityId | None = None
    """A force under orders: where it is going. It stays at ``places`` until it arrives."""
    arrives: date | None = None
    legs: tuple[Leg, ...] = ()
    """History's moves still to come, earliest first."""
    in_service: date | None = None
    """Engine v2: the day the capability enters service. An order that uses it
    before then is refused (spec §8.3). None: in service from the start."""
    posture: Posture | None = None
    """Engine v2: a force's posture, set by an applied order. None: as authored."""
    engagement: Engagement | None = None
    """Engine v2: a force's rules of engagement, set by an applied order. None: as authored."""
    left_base_on: date | None = None
    """A fleet or air group away from its side's bases: the day it left the last one. None
    at a base, for an army, and for a force no move has started the clock for."""
    detached_from: FeatureId | None = None
    """A detachment: the force it was split from. None for a force of its own."""
    rejoined_on: date | None = None
    """A detachment that has merged back into its parent: the day it did. It is out of
    play from then on. None while it is in play."""
    piece: Label | None = None
    """A ``piece``: the world's kind key. None for every other feature kind. Rules ask
    ``kinds.domain`` and ``kinds.is_force``, never this key."""
    path: tuple[EntityId, ...] = ()
    """With ``territories`` on, a piece under way: the areas still to enter, in order
    (``territory.plan``). Empty when it stands still."""
    step_due: date | None = None
    """The day the step into the head of ``path`` completes. None when it stands still."""
    lost_on: date | None = None
    """With ``battles`` on, a piece brought to strength 0 or destroyed in battle: the day it
    was. It is out of play from then on. None while it is in play (BTL)."""
    contingency: Contingency | None = None
    """With ``battles`` on, what the force does in a battle with no decision from its seat,
    set by an applied engagement order. None: hold (BDC)."""

    late_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "in_service",
            "posture",
            "engagement",
            "left_base_on",
            "detached_from",
            "rejoined_on",
            "piece",
            "path",
            "step_due",
            "lost_on",
            "contingency",
        }
    )

    @model_validator(mode="after")
    def _shape(self) -> "Feature":
        if (self.piece is None) == (self.kind is FeatureKind.PIECE):
            raise ValueError(
                f"feature {self.feature_id}: a piece, and only a piece, names its kind"
            )
        force = self.kind in AT_ONE_PLACE
        if force and len(self.places) != 1:
            raise ValueError(f"feature {self.feature_id}: a force is at one place")
        if not force and len(self.places) < 2:
            raise ValueError(f"feature {self.feature_id}: a {self.kind.value} joins two places")
        if (self.bound_for is None) != (self.arrives is None):
            raise ValueError(f"feature {self.feature_id}: bound_for and arrives go together")
        if self.bound_for is not None and not force:
            raise ValueError(f"feature {self.feature_id}: only a force moves by order")
        if self.detached_from is not None and not force:
            raise ValueError(f"feature {self.feature_id}: only a force is detached")
        if bool(self.path) != (self.step_due is not None):
            raise ValueError(f"feature {self.feature_id}: path and step_due go together")
        if self.path and not force:
            raise ValueError(f"feature {self.feature_id}: only a force steps by order")
        return self


def in_play(feature: Feature) -> bool:
    """False for a detachment that has rejoined its parent and for a piece lost in battle;
    True for every other feature."""
    return feature.rejoined_on is None and feature.lost_on is None


class Sight(Model):
    """A document line's claim about a feature: what it is, whose, and where."""

    kind: FeatureKind
    side: EntityId | None = None
    places: tuple[EntityId, ...] = Field(min_length=1)


class SightRef(Model):
    """The truth behind one sighting line."""

    feature_id: FeatureId
    places: tuple[EntityId, ...]


EARTH_KM = 6371


def km_between(a: tuple[float, float], b: tuple[float, float]) -> int:
    """Great-circle distance between two (lat, lon) points, whole kilometres."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    )
    return round(2 * EARTH_KM * math.asin(math.sqrt(h)))


__all__ = [
    "AT_ONE_PLACE",
    "FORCES",
    "SPEED_KM_PER_DAY",
    "Feature",
    "FeatureKind",
    "Leg",
    "Sight",
    "SightRef",
    "in_play",
    "km_between",
]
