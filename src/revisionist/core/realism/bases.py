"""Reach: how far a side can hold a force from its bases (reach, R2).

A force at one of its side's bases is sustained. Within its kind's operating radius of
such a base it operates; beyond that, up to its raid radius, it raids; past that the move
is refused. Radii are days of travel by the movement resolver's own route
(``routing.days_between``: fleets by sea, armies and air groups straight), so they read in
the unit the place picker shows. An army marches only over land; it crosses the sea only by
sealift (``sealift``): its side needs a pool of shipping, a fleet base of its own on the
army's land to embark at, the place it is sent to must be a fleet base of its side, and a
way by sea must be open to its side's fleets. Such a place reads as sustained, for once
ashore the army holds it: for an army, a fleet base of its side counts as one of its bases
while an army of that side stands there, and a front place does while an army of that side
stands there or a front runs through it.

Bases are fixed for the game: a base taken or blockaded still counts. A refusal names its
reason and the nearest base the force can work from: the base of its side and kind
nearest the place it was sent to, among those it can get to from where it is.

The tables are [proposed] values Josh accepted on the R2 values sheet, keyed by world and
place key and read only here. A world with no table has no reach rule.

With ``territories`` on (ADJ), bases are the world's own: sites with ``base: {sides,
domains}`` (``WorldMap.bases``), and reach is counted in steps over the board, not days or
kilometres, from the nearest base of the piece's side and domain (``area_reach``). An envoy
has no reach rule, and neither has a world whose board names no base.
"""

import math
from collections.abc import Iterable
from enum import StrEnum
from typing import NamedTuple

from revisionist.core.ids import EntityId, QuantityId
from revisionist.core.realism import sealift
from revisionist.core.realism.geography import Feature, FeatureKind, Sight
from revisionist.core.realism.routing import days_between, sea_route
from revisionist.core.state import State, View
from revisionist.core.world_compile import object_id

F, A, R = FeatureKind.FLEET, FeatureKind.ARMY, FeatureKind.AIR


class Radius(NamedTuple):
    operate: int
    """Days from a base within which a force operates."""
    raid: int | None
    """Days from a base up to which it may raid; None: it may not raid."""


RADIUS: dict[FeatureKind, Radius] = {
    F: Radius(10, 20),  # [proposed] about 4,500 and 9,000 km by sea
    A: Radius(12, None),  # [proposed] about 300 km on the march; overseas only by sealift
    R: Radius(1, 2),  # [proposed] about 1,000 and 2,000 km
}

RAID_DAYS: dict[FeatureKind, int] = {
    F: 30,  # [proposed] then it must put in at the nearest friendly base
    R: 3,  # [proposed] then back to a base
}
"""Days a force may stay away from its side's bases while it raids; past that it turns for
the nearest one. A kind not listed (an army) has no limit."""


class Base(NamedTuple):
    sides: frozenset[str]
    """Polity keys of the sides it serves."""
    kinds: frozenset[FeatureKind]


def _base(*sides: str, kinds: Iterable[FeatureKind]) -> Base:
    return Base(frozenset(sides), frozenset(kinds))


BASES: dict[str, dict[str, Base]] = {
    "autumn-1941": {
        "norfolk": _base("usa", kinds=(F, A, R)),  # [proposed] Atlantic Fleet's home port
        "argentia": _base("usa", kinds=(F, R)),  # [proposed] leased from 1941
        "pearl_harbor_base": _base("usa", kinds=(F, A, R)),  # [proposed]
        "washington": _base("usa", kinds=(A, R)),  # [proposed]
        "reykjavik": _base("uk", "usa", kinds=(F, R)),  # [proposed] British, US from July 1941
        "halifax_port": _base("uk", kinds=(F,)),  # [proposed] HX convoy assembly
        "sydney_cb": _base("uk", kinds=(F,)),  # [proposed] SC convoy assembly
        "liverpool": _base("uk", kinds=(F,)),  # [proposed] Western Approaches
        "scapa_flow": _base("uk", kinds=(F,)),  # [proposed] Home Fleet
        "london": _base("uk", kinds=(A, R)),  # [proposed]
        "lorient": _base("germany", kinds=(F,)),  # [proposed] U-boat arm
        "berlin": _base("germany", kinds=(A, R)),  # [proposed]
        "kure": _base("japan", kinds=(F, A, R)),  # [proposed] Combined Fleet
        "tokyo": _base("japan", kinds=(A, R)),  # [proposed]
        "rome": _base("italy", kinds=(A, R)),  # [proposed]
        "moscow": _base("ussr", kinds=(A, R)),  # [proposed]
        "archangel": _base("ussr", kinds=(F,)),  # [proposed] Arctic convoy terminal
        "leningrad": _base("ussr", kinds=(F, A, R)),  # [proposed] Baltic Fleet, besieged
        "chungking": _base("china", kinds=(A, R)),  # [proposed]
    },
}
"""Each world's bases, by place key. A place not listed (an anchorage, a sea area, a
front place) is no side's fixed base. Canada's and Newfoundland's ports serve ``uk``."""

FRONT_PLACES: dict[str, frozenset[str]] = {
    "autumn-1941": frozenset(
        {
            "smolensk",
            "vyazma",
            "kalinin",
            "mozhaisk",
            "kiev",
            "poltava",
            "kharkov",
            "odessa",
            "taganrog",
        }
    ),
}
"""Places whose holder moves with the front. [proposed]"""

LANDS: dict[str, dict[str, str]] = {
    "autumn-1941": {
        "washington": "north_america",
        "norfolk": "north_america",
        "halifax_port": "north_america",
        "argentia": "newfoundland",
        "sydney_cb": "cape_breton",
        "london": "britain",
        "liverpool": "britain",
        "scapa_flow": "orkney",
        "reykjavik": "iceland",
        "pearl_harbor_base": "oahu",
        "tokyo": "honshu",
        "kure": "honshu",
        "hitokappu_bay": "kurils",
        "north_atlantic": "sea",
        **{
            k: "eurasia"
            for k in (
                "berlin",
                "rome",
                "moscow",
                "archangel",
                "leningrad",
                "lorient",
                "chungking",
                "smolensk",
                "vyazma",
                "kalinin",
                "mozhaisk",
                "kiev",
                "poltava",
                "kharkov",
                "odessa",
                "taganrog",
            )
        },
    },
}
"""The land mass each place stands on, as of 1941 (no causeway to Cape Breton yet). An army
goes only between places on one land. [proposed]"""


class Tier(StrEnum):
    SUSTAINED = "sustained"
    OPERATE = "operate"
    RAID = "raid"
    REFUSED = "refused"


class Force(NamedTuple):
    """A force as a reader knows it: its kind, its side, and where it is."""

    kind: FeatureKind
    side: EntityId | None
    at: EntityId


class Reach(NamedTuple):
    tier: Tier
    base: EntityId | None
    """The base the tier is measured from (the place itself when sustained); for a
    refusal, the nearest base the force can work from. None when there is none."""
    days: int | None
    """Days from that base to the place; 0 when sustained; None for a refused landing,
    whose base is the nearest port of its side the army could land at."""
    reason: str | None
    """Why the move is refused, naming that base. None unless refused."""


def _id(world: State | View, key: str) -> EntityId:
    return EntityId(object_id(world.campaign_id, "entity", key))


def world_of(world: State | View) -> str | None:
    """The table whose every base and front place is a place in this campaign."""
    for name, table in sorted(BASES.items()):
        keys = (*table, *FRONT_PLACES.get(name, ()))
        if all(_id(world, k) in world.entities for k in keys):
            return name
    return None


def _days(
    world: State | View, kind: FeatureKind, side: EntityId | None, a: EntityId, b: EntityId
) -> int | None:
    return days_between(world, kind, side, a, b)


def _held(world: State | View, name: str, force: Force, seen: Iterable[Sight]) -> set[EntityId]:
    """Front places an army of ``force``'s side holds: its side's army or a front is there."""
    out = {force.at}
    for s in seen:
        if (s.kind is A and s.side == force.side) or (
            s.kind is FeatureKind.FRONT and s.side in (None, force.side)
        ):
            out.update(s.places)
    return out & {_id(world, k) for k in FRONT_PLACES.get(name, ())}


def _ports(world: State | View, name: str, side: EntityId) -> list[EntityId]:
    """The fleet bases of ``side``, in table order: where an army embarks and lands."""
    return [
        _id(world, key)
        for key, b in BASES[name].items()
        if F in b.kinds and any(_id(world, s) == side for s in b.sides)
    ]


def _landed(world: State | View, name: str, force: Force, seen: Iterable[Sight]) -> set[EntityId]:
    """Ports of ``force``'s side where an army of that side stands (``force`` included)."""
    assert force.side is not None
    out = {force.at}
    for s in seen:
        if s.kind is A and s.side == force.side:
            out.update(s.places)
    return out & set(_ports(world, name, force.side))


def _bases(world: State | View, name: str, force: Force, seen: Iterable[Sight]) -> list[EntityId]:
    """The places that serve ``force`` as a base, in table order."""
    seen = list(seen)
    out = [
        _id(world, key)
        for key, b in BASES[name].items()
        if force.kind in b.kinds and any(_id(world, s) == force.side for s in b.sides)
    ]
    if force.kind is A:
        out += sorted(
            (_held(world, name, force, seen) | _landed(world, name, force, seen)) - set(out)
        )
    return out


def _name(world: State | View, at: EntityId | None) -> str:
    e = world.entities.get(at) if at is not None else None
    return e.name if e is not None else "its side"


WORDS = {F: ("a fleet", "sail"), A: ("an army", "march"), R: ("an air group", "flight")}


def _sights(world: State | View, seen: Iterable[Sight] | None) -> Iterable[Sight]:
    """``seen``, or when None a state's own features (nothing for a view)."""
    if seen is not None:
        return seen
    feats = world.features.values() if isinstance(world, State) else ()
    return [Sight(kind=f.kind, side=f.side, places=f.places) for f in feats]


def _same_land(world: State | View, name: str, kind: FeatureKind, a: EntityId, b: EntityId) -> bool:
    """An army goes only between places on one land; other forces go anywhere."""
    if kind is not A:
        return True
    lands = {_id(world, k): v for k, v in LANDS.get(name, {}).items()}
    return None in (lands.get(a), lands.get(b)) or lands.get(a) == lands.get(b)


def _land(world: State | View, name: str, at: EntityId) -> str | None:
    return {_id(world, k): v for k, v in LANDS.get(name, {}).items()}.get(at)


def crossing(world: State | View, kind: FeatureKind, a: EntityId, b: EntityId) -> bool:
    """Whether a force of ``kind`` going from ``a`` to ``b`` crosses the sea by sealift: an
    army between two lands, in a world with a table."""
    name = world_of(world)
    return name is not None and not _same_land(world, name, kind, a, b)


def _pool(world: State | View, name: str, side: EntityId) -> str | None:
    """The key of ``side``'s shipping pool; None when it has none. A state must hold the
    quantity (a stored game compiled without it has no lift); a seat's view, which never
    holds it, goes by the table."""
    for side_key, key in sealift.POOLS.get(name, {}).items():
        if _id(world, side_key) != side:
            continue
        held = QuantityId(object_id(world.campaign_id, "quantity", key)) in world.quantities
        return key if isinstance(world, View) or held else None
    return None


def pool_key(world: State | View, side: EntityId) -> str | None:
    """The world-file key of ``side``'s shipping pool; None when it cannot lift."""
    name = world_of(world)
    return None if name is None else _pool(world, name, side)


class _NoLift(NamedTuple):
    reason: str
    port: EntityId | None = None
    """The nearest port it could land at, for a place with none of its side's."""
    lead: bool = True
    """Whether the reason follows the words on sealift (else it stands alone)."""


def _lift(world: State | View, name: str, force: Force, to: EntityId) -> sealift.Lift | _NoLift:
    """The lift that takes army ``force`` across the sea to ``to``, or why there is none."""
    side = force.side
    assert side is not None
    side_name = _name(world, side)
    pool = _pool(world, name, side)
    if pool is None:
        return _NoLift(f"{side_name} has no shipping to lift an army.")
    ports = _ports(world, name, side)
    land = _land(world, name, force.at)
    start = sealift.embark(
        world, side, force.at, [p for p in ports if _land(world, name, p) == land]
    )
    if start is None:
        return _NoLift(f"{side_name} has no port on this army's land where it can embark.")
    if to not in ports:
        dest = world.entities[to].at
        ranked = [
            (route.km, str(p), p)
            for p in ports
            if _land(world, name, p) != land
            and (pt := world.entities[p].at) is not None
            and dest is not None
            and (route := sea_route(world, side, pt, dest)) is not None
        ]
        best = min(ranked, default=None)
        port = None if best is None else best[2]
        why = f"An army lands only at a port of {side_name}, and {_name(world, to)} is none."
        if port is not None:
            why += f" The nearest it could land at is {_name(world, port)}."
        return _NoLift(why, port)
    days = sealift.lift_days(world, side, start[0], start[1], to)
    if days is None:
        return _NoLift(
            f"No sea passage open to {side_name}'s fleets reaches {_name(world, to)}.",
            lead=False,
        )
    return sealift.Lift(start[0], days, pool)


def lift(world: State | View, force: Feature | Force, to: EntityId) -> sealift.Lift | None:
    """How army ``force`` crosses the sea to ``to``; None when it does not cross (another
    kind, or the same land), when the world has no table, or when the lift is refused."""
    if isinstance(force, Feature):
        force = Force(force.kind, force.side, force.places[0])
    name = world_of(world)
    if name is None or force.side is None or _same_land(world, name, force.kind, force.at, to):
        return None
    found = _lift(world, name, force, to)
    return found if isinstance(found, sealift.Lift) else None


def _nearest(
    world: State | View, name: str, force: Force, own: list[EntityId], to: EntityId
) -> tuple[EntityId | None, int | None]:
    """Of the bases in ``own`` the force can get to, the one nearest ``to``, and its days
    there (None: no way there)."""
    kind, side = force.kind, force.side
    workable = [
        b
        for b in own
        if _same_land(world, name, kind, force.at, b)
        and (b == force.at or _days(world, kind, side, force.at, b) is not None)
    ]
    ranked = [(_days(world, kind, side, b, to), b) for b in workable]
    best = min(ranked, key=lambda x: (math.inf if x[0] is None else x[0], str(x[1])), default=None)
    return (None, None) if best is None else (best[1], best[0])


def nearest_base(world: State | View, force: Feature | Force) -> EntityId | None:
    """The base of ``force``'s side and kind nearest where it is, among those it can get to;
    None when the world has no table, the force has no side, or no base will do."""
    if isinstance(force, Feature):
        force = Force(force.kind, force.side, force.places[0])
    name = world_of(world)
    if name is None or force.side is None:
        return None
    own = _bases(world, name, force, _sights(world, None))
    return _nearest(world, name, force, own, force.at)[0]


def reach(
    world: State | View,
    force: Feature | Force,
    to: EntityId,
    seen: Iterable[Sight] | None = None,
) -> Reach | None:
    """How far ``force``'s side can hold it at ``to``; None when the world has no table or
    the force has no side. ``seen`` is the forces and fronts the front-place rule reads;
    None reads a state's own features, and nothing for a view."""
    if isinstance(force, Feature):
        force = Force(force.kind, force.side, force.places[0])
    name = world_of(world)
    if name is None or force.side is None or force.kind not in RADIUS:
        return None
    kind, side = force.kind, force.side
    own = _bases(world, name, force, _sights(world, seen))

    noun, verb = WORDS[kind]
    side_name = _name(world, side)

    def refused(why: str) -> Reach:
        base, days = _nearest(world, name, force, own, to)
        if base is not None:
            why += f" The nearest base it can work from is {_name(world, base)}."
        return Reach(Tier.REFUSED, base, days, why)

    if to != force.at and _days(world, kind, side, force.at, to) is None:
        return refused(f"No sea passage open to {side_name}'s fleets reaches {_name(world, to)}.")
    if not _same_land(world, name, kind, force.at, to):
        found = _lift(world, name, force, to)
        if isinstance(found, sealift.Lift):
            return Reach(Tier.SUSTAINED, to, 0, None)
        if not found.lead:
            return refused(found.reason)
        why = f"{_name(world, to)} is across the sea, and {noun} crosses it only by sealift."
        if found.port is not None:
            return Reach(Tier.REFUSED, found.port, None, f"{why} {found.reason}")
        return refused(f"{why} {found.reason}")
    if to in own:
        return Reach(Tier.SUSTAINED, to, 0, None)
    measured = [(d, str(b), b) for b in own if (d := _days(world, kind, side, b, to)) is not None]
    if not measured:
        return refused(f"No base of {side_name} reaches {_name(world, to)}.")
    days, _, base = min(measured)
    radius = RADIUS[kind]
    if days <= radius.operate:
        return Reach(Tier.OPERATE, base, days, None)
    if radius.raid is not None and days <= radius.raid:
        return Reach(Tier.RAID, base, days, None)
    limit = radius.raid if radius.raid is not None else radius.operate
    return refused(
        f"{_name(world, to)} is {days} days' {verb} from the nearest base of {side_name},"
        f" and {noun} reaches {limit} days at most."
    )


RADIUS_STEPS: dict[str, Radius] = {
    "land": Radius(2, None),  # [proposed] ADJ: two steps from a base, no raiding
    "sea": Radius(3, 6),  # [proposed] ADJ
    "air": Radius(1, 2),  # [proposed] ADJ
}
"""With ``territories`` on: the operating and raid radii in steps, by the piece's domain."""


class AreaReach(NamedTuple):
    tier: Tier
    base: EntityId | None
    """The nearest base of the piece's side and domain (the place); None when it has none."""
    steps: int | None
    """Steps from that base's area; None when no course of the domain joins them."""
    reason: str | None
    """Why the area is refused. None unless refused."""


def within_reach(state: State, piece: Feature) -> set[EntityId] | None:
    """Every area ``area_reach`` does not refuse the piece, in one pass; None where no reach
    rule applies."""
    from revisionist.core.realism import kinds, territory

    board = state.map
    kind = kinds.of(state, piece)
    if board is None or not board.bases or kind is None or kind.domain.value not in RADIUS_STEPS:
        return None
    domain = kind.domain.value
    own = territory.nation(state, piece.side)
    sources = [
        at
        for b in board.bases
        if own in b.sides and domain in b.domains and (at := b.area(domain)) is not None
    ]
    radius = RADIUS_STEPS[domain]
    far = radius.raid if radius.raid is not None else radius.operate
    return {a for a, n in territory.steps_from(board, domain, sources).items() if n <= far}


def area_reach(state: State, piece: Feature, area: EntityId) -> AreaReach | None:
    """How far ``area`` lies from the bases of the piece's side and domain, in steps; None
    where no reach rule applies (no board bases, an envoy, or not a piece)."""
    from revisionist.core.realism import kinds, territory

    board = state.map
    kind = kinds.of(state, piece)
    if board is None or not board.bases or kind is None or kind.domain.value not in RADIUS_STEPS:
        return None
    domain = kind.domain.value
    own = territory.nation(state, piece.side)
    sources: dict[EntityId, EntityId] = {}
    for b in sorted(board.bases, key=lambda b: str(b.place)):
        at = b.area(domain)
        if own in b.sides and domain in b.domains and at is not None:
            sources.setdefault(at, b.place)
    radius = RADIUS_STEPS[domain]
    best: tuple[int, EntityId] | None = None
    for at, place in sources.items():
        n = territory.steps_from(board, domain, [at]).get(area)
        if n is not None and (best is None or (n, str(place)) < (best[0], str(best[1]))):
            best = (n, place)
    if best is not None and best[0] == 0:
        return AreaReach(Tier.SUSTAINED, best[1], 0, None)
    if best is not None and best[0] <= radius.operate:
        return AreaReach(Tier.OPERATE, best[1], best[0], None)
    if best is not None and radius.raid is not None and best[0] <= radius.raid:
        return AreaReach(Tier.RAID, best[1], best[0], None)
    there = _name(state, area)
    words = f"{there} is beyond the reach of {_name(state, own)}'s bases for {kind.name}"
    if best is None:
        return AreaReach(Tier.REFUSED, None, None, words + ".")
    far = radius.raid if radius.raid is not None else radius.operate
    words += f": {best[0]} steps from {_name(state, best[1])}, past {far}."
    return AreaReach(Tier.REFUSED, best[1], best[0], words)


__all__ = [
    "BASES",
    "FRONT_PLACES",
    "LANDS",
    "RADIUS",
    "RADIUS_STEPS",
    "RAID_DAYS",
    "AreaReach",
    "Base",
    "Force",
    "Radius",
    "Reach",
    "Tier",
    "area_reach",
    "crossing",
    "lift",
    "nearest_base",
    "pool_key",
    "reach",
]
