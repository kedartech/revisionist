"""Sea routing: how far a fleet sails between two places (reach, R3).

The world's water is a few seas joined by doors: the canals, straits and capes a
fleet must pass to get from one sea to another. Inside one sea a fleet sails the
great circle; between seas it goes door to door by the shortest open way. A
place belongs to the sea of its nearest anchor point, so an inland place is
reached from the nearest coast's sea.

A door held by a power is closed to a fleet whose side is at war with that power;
a door whose holder is not in the world, or has none, is always open. All points
and holders are [proposed], world-independent, and read only from this table.
Armies and air groups do not use it: they go in a straight line.
"""

import heapq
import math
from typing import NamedTuple

from revisionist.core.ids import EntityId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism.geography import SPEED_KM_PER_DAY, Feature, FeatureKind, km_between
from revisionist.core.realism.war import at_war
from revisionist.core.state import State
from revisionist.core.world_compile import object_id

Point = tuple[float, float]


class Door(NamedTuple):
    key: str
    name: str
    at: Point
    seas: tuple[str, str]
    holder: str | None
    """A polity's world-file key, or None for open water."""


SEAS: dict[str, tuple[Point, ...]] = {
    "north_atlantic": (
        (40.0, -40.0),
        (55.0, -25.0),
        (25.0, -50.0),
        (15.0, -70.0),
        (30.0, -15.0),
        (45.0, -8.0),
        (56.0, 3.0),
        (62.0, -10.0),
    ),
    "south_atlantic": ((-25.0, -20.0), (-40.0, -50.0), (-10.0, -30.0)),
    "pacific": (
        (20.0, -160.0),
        (35.0, 145.0),
        (15.0, 130.0),
        (10.0, 115.0),
        (30.0, -130.0),
        (-20.0, -120.0),
        (45.0, 160.0),
        (0.0, -100.0),
        (-30.0, 170.0),
    ),
    "mediterranean": ((38.0, 5.0), (35.0, 18.0), (34.0, 28.0), (40.0, 20.0)),
    "black_sea": ((43.5, 34.0), (46.5, 36.0)),
    "baltic": ((57.0, 19.0), (60.0, 25.0), (55.0, 15.0)),
    "arctic": ((70.0, 40.0), (65.0, 39.0)),
    "red_sea": ((20.0, 38.0),),
    "indian": ((-10.0, 75.0), (15.0, 62.0), (5.0, 90.0), (-30.0, 80.0)),
}
"""Each sea's anchor points (latitude, longitude). [proposed]"""

DOORS: tuple[Door, ...] = (
    Door("panama", "the Panama Canal", (9.1, -79.7), ("north_atlantic", "pacific"), "usa"),
    Door(
        "narrows", "the Atlantic narrows", (2.0, -30.0), ("north_atlantic", "south_atlantic"), None
    ),
    Door("cape_horn", "Cape Horn", (-56.0, -67.3), ("south_atlantic", "pacific"), None),
    Door("good_hope", "the Cape of Good Hope", (-34.8, 20.0), ("south_atlantic", "indian"), None),
    Door(
        "gibraltar",
        "the Strait of Gibraltar",
        (35.95, -5.6),
        ("north_atlantic", "mediterranean"),
        "uk",
    ),
    Door("suez", "the Suez Canal", (30.6, 32.3), ("mediterranean", "red_sea"), "uk"),
    Door("bab_el_mandeb", "the Bab-el-Mandeb", (12.6, 43.3), ("red_sea", "indian"), None),
    Door(
        "bosporus", "the Turkish Straits", (41.1, 29.05), ("mediterranean", "black_sea"), "turkey"
    ),
    Door(
        "danish_straits",
        "the Danish straits",
        (57.8, 10.6),
        ("north_atlantic", "baltic"),
        "germany",
    ),
    Door("north_cape", "the North Cape", (71.2, 25.8), ("north_atlantic", "arctic"), None),
    Door("malacca", "the Strait of Malacca", (1.3, 103.8), ("indian", "pacific"), "uk"),
    Door("sunda", "the Sunda Strait", (-6.0, 105.8), ("indian", "pacific"), "netherlands"),
)
"""[proposed] Holders as of autumn 1941: the United States holds the canal zone; Britain
holds Gibraltar, Suez and Singapore; Germany holds the Danish straits, Denmark being
occupied. Turkey and the Netherlands are named for worlds that have them."""


ARRIVED = ""
"""The search's mark for a way that has reached its destination."""


class SeaRoute(NamedTuple):
    km: int
    via: tuple[str, ...]
    """The doors passed, in order, by key."""


def sea_of(where: Point) -> str:
    """The sea of the anchor nearest ``where``."""
    return min(
        ((km_between(where, a), sea) for sea, anchors in SEAS.items() for a in anchors),
    )[1]


def _closed(state: State, side: EntityId | None, door: Door) -> bool:
    if side is None or door.holder is None:
        return False
    holder = state.entities.get(EntityId(object_id(state.campaign_id, "entity", door.holder)))
    if holder is None or holder.kind is not EntityKind.POLITY:
        return False
    return at_war(state, side, holder.entity_id)


def sea_route(state: State, side: EntityId | None, origin: Point, dest: Point) -> SeaRoute | None:
    """The shortest way by sea from ``origin`` to ``dest`` for a fleet of ``side``,
    or None when every way passes a door closed to it."""
    start, goal = sea_of(origin), sea_of(dest)
    if start == goal:
        return SeaRoute(km_between(origin, dest), ())
    doors = [d for d in DOORS if not _closed(state, side, d)]
    # Dijkstra over doors; ties break on the door keys so a replay takes the same way.
    queue: list[tuple[int, tuple[str, ...], Point, str]] = [(0, (), origin, start)]
    done: set[tuple[str, str]] = set()
    while queue:
        km, via, here, sea = heapq.heappop(queue)
        if sea == ARRIVED:
            return SeaRoute(km, via)
        if sea == goal:
            heapq.heappush(queue, (km + km_between(here, dest), via, dest, ARRIVED))
        node = (via[-1] if via else "", sea)
        if node in done:
            continue
        done.add(node)
        for d in doors:
            if sea not in d.seas or d.key in via:
                continue
            other = d.seas[1] if d.seas[0] == sea else d.seas[0]
            heapq.heappush(queue, (km + km_between(here, d.at), (*via, d.key), d.at, other))
    return None


def travel_days(state: State, force: Feature, to: EntityId) -> int | None:
    """Days for ``force`` to reach ``to`` from where it is, at least one; None for a
    fleet with no open way by sea."""
    origin = state.entities[force.places[0]].at
    dest = state.entities[to].at
    if origin is None or dest is None:
        km = 0
    elif force.kind is FeatureKind.FLEET:
        route = sea_route(state, force.side, origin, dest)
        if route is None:
            return None
        km = route.km
    else:
        km = km_between(origin, dest)
    return max(1, math.ceil(km / SPEED_KM_PER_DAY[force.kind]))


__all__ = ["DOORS", "SEAS", "Door", "SeaRoute", "sea_of", "sea_route", "travel_days"]
