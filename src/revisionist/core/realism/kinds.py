"""What a piece is and what a resource is for: the world names them, the engine reads roles.

A world with ``piece_kinds`` names its own kinds of piece (a levy, a galley, a panzer
corps) and with ``resources`` its own resources (grain, coal, oil). Compile stores both
in ``kinds_declared``, folded into ``state.kinds``; they are public rules of the world,
the same in every view.

The engine's vocabulary is fixed: four domains a piece moves in and five roles a
resource plays. A rule asks what a piece is only through ``domain`` and ``is_force``
here, never by the kind's key or name, so a world whose kinds are named ``levy`` and
``galley`` plays exactly as one whose kinds are named ``army`` and ``fleet``.

A world with no ``piece_kinds`` keeps the five feature kinds (fleet, army, air, front,
route); ``domain`` answers for those as well.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.realism.geography import Feature, FeatureKind
from revisionist.core.realism.territory import TerrainKind

if TYPE_CHECKING:
    from revisionist.core.state import _World


# [proposed] the four domains and the five roles are the engine's fixed vocabulary.


class Domain(StrEnum):
    """Where a piece moves: over land, over sea, through the air, or as an envoy, who
    goes anywhere and fights nobody."""

    LAND = "land"
    SEA = "sea"
    AIR = "air"
    ENVOY = "envoy"


class Role(StrEnum):
    """What a resource is for. Several resources may share a role; a role may have none."""

    OUTPUT = "output"
    MANPOWER = "manpower"
    FUEL = "fuel"
    SUPPLY = "supply"
    PRESTIGE = "prestige"


MAX_STRENGTH = 5  # [proposed] the pips a piece holds when its kind does not say
Percent = Annotated[int, Field(ge=0, le=100)]


class PieceKind(Model):
    """One kind of piece the world names."""

    key: Label
    name: Label
    domain: Domain
    days_per_step: dict[Label, Annotated[int, Field(ge=1)]]
    """Days a step into an area takes, by the terrain key of the area entered."""
    max_strength: int = Field(default=MAX_STRENGTH, ge=1)
    fuel_per_step: float = Field(default=0, ge=0)
    """Fuel spent at the start of each step, from a resource whose role is ``fuel``."""
    range_steps: int | None = Field(default=None, ge=1)
    """An air kind's reach from its base, in steps. None for every other domain."""
    detect: Percent = 0
    conceal: Percent = 0
    carries: tuple[Label, ...] = ()
    """The kinds it can lift, by key."""

    @model_validator(mode="after")
    def _air_range(self) -> "PieceKind":
        if (self.range_steps is not None) != (self.domain is Domain.AIR):
            raise ValueError(f"piece kind {self.key}: range_steps goes with the air domain")
        return self


class Resource(Model):
    key: Label
    name: Label
    unit: Label
    role: Role


class Kinds(Model):
    """The world's piece kinds and resources, by key, in the world file's order."""

    pieces: dict[Label, PieceKind] = Field(default_factory=dict)
    resources: dict[Label, Resource] = Field(default_factory=dict)


_FORCE_DOMAINS = {
    FeatureKind.ARMY: Domain.LAND,
    FeatureKind.FLEET: Domain.SEA,
    FeatureKind.AIR: Domain.AIR,
}
"""The domains of the three force kinds of a world with no ``piece_kinds``."""

FIGHTS = frozenset({Domain.LAND, Domain.SEA, Domain.AIR})
"""The domains whose pieces are forces. An envoy is a piece and not a force."""


def stands_on(domain: Domain, terrain: TerrainKind) -> bool:
    """Whether a piece of this domain can stand in an area of this kind of terrain."""
    match domain:
        case Domain.LAND:
            return terrain is TerrainKind.LAND
        case Domain.SEA:
            return terrain is TerrainKind.SEA
        case Domain.AIR | Domain.ENVOY:
            return True


def steps_on(domain: Domain) -> frozenset[TerrainKind]:
    """The kinds of terrain a piece of this domain steps into."""
    return frozenset(t for t in TerrainKind if stands_on(domain, t))


def of(state: "_World", feature: Feature) -> PieceKind | None:
    """The world's kind of this piece. None for a feature that is not a piece."""
    if feature.kind is not FeatureKind.PIECE or feature.piece is None or state.kinds is None:
        return None
    return state.kinds.pieces.get(feature.piece)


def domain(state: "_World", feature: Feature) -> Domain | None:
    """Where the piece moves. None for a front or a route, which are not pieces."""
    kind = of(state, feature)
    if kind is not None:
        return kind.domain
    return _FORCE_DOMAINS.get(feature.kind)


def is_force(state: "_World", feature: Feature) -> bool:
    """Whether the feature is a force: a land, sea or air piece, or an army, fleet or
    air group. An envoy, a front and a route are not."""
    return domain(state, feature) in FIGHTS


def with_role(state: "_World", role: Role) -> tuple[Resource, ...]:
    """The world's resources that play this role, in the world file's order."""
    if state.kinds is None:
        return ()
    return tuple(r for r in state.kinds.resources.values() if r.role is role)


__all__ = [
    "FIGHTS",
    "MAX_STRENGTH",
    "Domain",
    "Kinds",
    "PieceKind",
    "Resource",
    "Role",
    "domain",
    "is_force",
    "of",
    "stands_on",
    "steps_on",
    "with_role",
]
