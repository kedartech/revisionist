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

A kind may carry its own figures (KFG): an attack and a defence from 1 to 5, changed by
the terrain fought on and by what is on the other side, and held to 1 to 5 after every
change (``figure``). A kind given none of them has 3 for each, which is the battle's
arithmetic of a piece with no kind. Rules read the figures only with their own switch on.
"""

from collections.abc import Collection, Iterable, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal

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

FIGURE_LOW, FIGURE_HIGH = 1, 5  # [proposed] the range of an attack or defence figure
FIGURE = 3
"""[proposed] A kind's attack and defence when the world does not say: the middle of the
range, which a rule reads as no change to today's arithmetic."""
FigureValue = Annotated[int, Field(ge=FIGURE_LOW, le=FIGURE_HIGH)]
Shift = Annotated[int, Field(ge=FIGURE_LOW - FIGURE_HIGH, le=FIGURE_HIGH - FIGURE_LOW)]
BaseDomain = Literal["land", "sea", "air"]
"""The domains a base serves, and so the domains a kind may be raised at."""


class Figure(StrEnum):
    """The two figures a kind carries into a fight."""

    ATTACK = "attack"
    DEFENCE = "defence"


class Condition(StrEnum):
    """[proposed] When a change for what is on the other side applies, from a fixed list."""

    NO_ENEMY_AIR = "no_enemy_air"
    """No enemy air piece has the area in range."""
    ENEMY_OUT_OF_SUPPLY = "enemy_out_of_supply"


class Picture(StrEnum):
    """[proposed] The pictures a client draws a kind with, by key: the fixed list."""

    INFANTRY = "infantry"
    ARMOUR = "armour"
    GARRISON = "garrison"
    CAVALRY = "cavalry"
    ARTILLERY = "artillery"
    BATTLE_FLEET = "battle_fleet"
    CARRIER = "carrier"
    SUBMARINES = "submarines"
    TRANSPORTS = "transports"
    GUNBOAT = "gunboat"
    IRONCLAD = "ironclad"
    FIGHTERS = "fighters"
    BOMBERS = "bombers"
    ENVOY = "envoy"


class Change(Model):
    """A change to a kind's figures: added to each, then held to the range."""

    attack: Shift = 0
    defence: Shift = 0


class Against(Change):
    """A change while a named kind, or a piece of a named domain, is on the other side;
    with ``when``, only while that condition holds."""

    facing: Label
    """A kind key or a domain of the world."""
    when: Condition | None = None


class Cost(Model):
    """What raising one piece of a kind spends: output and manpower points."""

    output: int = Field(ge=0)
    manpower: int = Field(ge=0)


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
    attack: FigureValue = FIGURE
    defence: FigureValue = FIGURE
    on_terrain: dict[Label, Change] = Field(default_factory=dict)
    """A change to the figures by the terrain key of the area fought in."""
    against: tuple[Against, ...] = ()
    strike_steps: int | None = Field(default=None, ge=1)
    """The steps from a fight within which it supports its side without standing in it."""
    covers: bool = False
    """Whether it cancels the enemy's air support within its range."""
    may_attack: bool = True
    holds_ground: bool = True
    """Whether standing in a territory can take it."""
    picture: Picture | None = None
    cost: Cost | None = None
    """What raising one spends. None: the kind is not raised."""
    lead_days: int | None = Field(default=None, ge=1)
    """Days from the order to raise to the new piece."""
    raised_at: BaseDomain | None = None
    """The domain of base a place needs to raise one."""

    late_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "attack",
            "defence",
            "on_terrain",
            "against",
            "strike_steps",
            "covers",
            "may_attack",
            "holds_ground",
            "picture",
            "cost",
            "lead_days",
            "raised_at",
        }
    )

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


def held(value: int) -> int:
    """A figure held to the range."""
    return max(FIGURE_LOW, min(FIGURE_HIGH, value))


def figure(
    kind: PieceKind,
    which: Figure,
    *,
    terrain: str | None = None,
    facing: Collection[str] = frozenset(),
    holds: Collection[Condition] = frozenset(),
    weather: Sequence[Change] = (),
) -> int:
    """The kind's attack or defence in a fight on ``terrain`` (a terrain key) against a
    side whose kinds and domains are ``facing`` (``facing``), while ``holds`` hold: the
    kind's own figure, changed first by the terrain, then by each ``against`` that applies
    in the world file's order, then by each change the ``weather`` makes (KWX), held to 1
    to 5 after every change."""
    value: int = getattr(kind, which.value)
    changes: list[Change] = []
    if terrain is not None and terrain in kind.on_terrain:
        changes.append(kind.on_terrain[terrain])
    changes.extend(
        a for a in kind.against if a.facing in facing and (a.when is None or a.when in holds)
    )
    changes.extend(weather)
    for change in changes:
        value = held(value + getattr(change, which.value))
    return value


def facing(state: "_World", pieces: Iterable[Feature]) -> frozenset[str]:
    """What is on a side, as an ``against`` names it: each piece's kind key and domain."""
    named: set[str] = set()
    for piece in pieces:
        kind = of(state, piece)
        if kind is not None:
            named.add(kind.key)
        where = domain(state, piece)
        if where is not None:
            named.add(where.value)
    return frozenset(named)


def with_role(state: "_World", role: Role) -> tuple[Resource, ...]:
    """The world's resources that play this role, in the world file's order."""
    if state.kinds is None:
        return ()
    return tuple(r for r in state.kinds.resources.values() if r.role is role)


__all__ = [
    "FIGHTS",
    "FIGURE",
    "FIGURE_HIGH",
    "FIGURE_LOW",
    "MAX_STRENGTH",
    "Against",
    "BaseDomain",
    "Change",
    "Condition",
    "Cost",
    "Domain",
    "Figure",
    "Kinds",
    "Picture",
    "PieceKind",
    "Resource",
    "Role",
    "domain",
    "facing",
    "figure",
    "held",
    "is_force",
    "of",
    "stands_on",
    "steps_on",
    "with_role",
]
