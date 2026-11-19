"""Sealift (reach, R6): an army crosses the sea only on its side's shipping.

It marches to its side's fleet base nearest it on its own land (``embark``), sails the
fleet's sea route for its side at convoy pace (``lift_days``), and lands only at a fleet
base of its side. The tonnage (``lift_needed``) is drawn from the side's pool, a world
quantity, the day the order sets it out, and given back the day it lands. The whole army
sails: armies cannot detach. An army at sea stays at its origin until it lands, as every
force does, so nothing meets it on the way. The checks and refusals are ``bases``'s; the
draw and the return are ``resolvers.movement``'s.

Values are [proposed] (sealift plan, section 3) and unsourced; the pool is ``gap: true`` in
the world file until a source is named. Candidate sources: C. B. A. Behrens, *Merchant
Shipping and the Demands of War* (HMSO, 1955), for British tonnage free for military use;
the Admiralty's troopship returns of 1941 for the tonnage per division lifted.
"""

import math
from collections.abc import Iterable
from typing import NamedTuple

from revisionist.core.ids import EntityId, QuantityId
from revisionist.core.realism.geography import Feature, FeatureKind
from revisionist.core.realism.routing import days_between, sea_route
from revisionist.core.state import State, View

GRT_PER_TIER = 50_000
"""[proposed] Shipping a lift takes per tier point of the army: Home Forces (tier 4) needs
200,000 GRT. Candidate source: Behrens, tonnage per division in 1941 troop convoys."""

CONVOY_KM_PER_DAY = 350
"""[proposed] A troop convoy's pace at sea, about 8 knots: slower than a fleet's cruise."""

POOLS: dict[str, dict[str, str]] = {
    "autumn-1941": {"uk": "uk_sealift_grt"},
}
"""Each world's lifting sides: the polity key and its pool's quantity key, for a game
without the territory rules (a stored game). A side not listed cannot lift. In a territory
game the world names each nation's pool (``lift_pool``) and the table is not read."""


def pools(state: State) -> tuple[QuantityId, ...]:
    """The lift pools this game holds a figure for, in id order: in a territory game the
    ones the world names (``lift_pool``); otherwise those of the table."""
    from revisionist.core.realism import territory
    from revisionist.core.world_compile import object_id

    if territory.on(state) and state.map is not None:
        named = set(state.map.lift_pools.values())
    else:
        keys = {k for table in POOLS.values() for k in table.values()}
        named = {QuantityId(object_id(state.campaign_id, "quantity", k)) for k in keys}
    return tuple(sorted(q for q in named if q in state.quantities))


class Lift(NamedTuple):
    """How an army crosses the sea: where it embarks, the days to land, and its pool."""

    embark: EntityId
    days: int
    """The march to ``embark`` (0 when it stands there) and the sea route at convoy pace."""
    pool: str
    """The world-file key of the quantity the lift draws on."""


def lift_needed(force: Feature) -> int:
    """The tonnage an army's lift takes from its side's pool."""
    return force.tier * GRT_PER_TIER


def embark(
    world: State | View, side: EntityId, at: EntityId, ports: Iterable[EntityId]
) -> tuple[EntityId, int] | None:
    """Of ``ports`` (its side's fleet bases on its own land), the one nearest ``at`` by
    march and the days to it: 0 when the army stands at one. None: there is no port."""
    ranked = [
        (0 if p == at else days_between(world, FeatureKind.ARMY, side, at, p), p) for p in ports
    ]
    best = min(((d, str(p), p) for d, p in ranked if d is not None), default=None)
    return None if best is None else (best[2], best[0])


def lift_days(
    world: State | View, side: EntityId, port: EntityId, march: int, to: EntityId
) -> int | None:
    """``march`` plus the days by sea from ``port`` to ``to`` at convoy pace on the fleet
    route for ``side``; None when every way by sea is closed to it."""
    origin, dest = world.entities[port].at, world.entities[to].at
    if origin is None or dest is None:
        return None
    route = sea_route(world, side, origin, dest)
    if route is None:
        return None
    return max(1, march + math.ceil(route.km / CONVOY_KM_PER_DAY))


__all__ = [
    "CONVOY_KM_PER_DAY",
    "GRT_PER_TIER",
    "POOLS",
    "Lift",
    "embark",
    "lift_days",
    "lift_needed",
    "pools",
]
