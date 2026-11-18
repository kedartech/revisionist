"""The board a world file defines: regions, territories, sea zones and who borders whom.

A world with a ``map`` names a map file (``worlds/maps/<file>``) by name and SHA-256.
Compile reads the file only to check it (its hash, its area keys, its districts) and
stores the topology in ``map_declared``: the areas, their regions and terrain, and the
adjacency list. The shapes stay in the file and never enter the log or the state, so
a game is served the map object its own stored hash names (``revisionist.engine.maps``
reads it, since the core reads no files).

Every area is also a ``location`` entity whose key is the area's key, so anything that
names a place can name an area. The map is public: every view holds the same board.

The map file may carry, beside the format's ``areas``, a ``districts`` object of finer
shapes by key, for drawing only; a territory names its own, and no rule reads them.
"""

import hashlib
import json
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field, StringConstraints

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId

if TYPE_CHECKING:
    from revisionist.core.state import State, View

Coords = Literal["lonlat", "flat"]
"""``lonlat``: x is longitude and y latitude, in degrees. ``flat``: units of the
world's own plane inside its ``box``."""

Box = tuple[float, float, float, float]
"""``[west, south, east, north]``."""

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A map file's SHA-256, as lowercase hex."""


class TerrainKind(StrEnum):
    LAND = "land"
    SEA = "sea"


class Terrain(Model):
    key: Label
    kind: TerrainKind


class Region(Model):
    key: Label
    name: Label
    parent: Label | None = None


class Territory(Model):
    """A land area. Its ``area`` is the location entity standing for it."""

    area: EntityId
    key: Label
    """The area's key in the map file."""
    name: Label
    region: Label
    terrain: Label
    holder: EntityId | None = None
    """The polity holding it at the start."""
    yields: dict[Label, float] = Field(default_factory=dict)
    """What it yields, by resource key."""
    sites: tuple[EntityId, ...] = ()
    """The places in it the world names."""
    districts: tuple[Label, ...] = ()
    """Finer shapes in the map file, for drawing. No rule reads them."""


class SeaZone(Model):
    area: EntityId
    key: Label
    name: Label
    region: Label
    terrain: Label


class Link(Model):
    """Two areas that border, ``a`` before ``b``; ``crossing`` names a link across
    water or a strait where they share no border."""

    a: EntityId
    b: EntityId
    crossing: Label | None = None


class WorldMap(Model):
    """The board: everything about the map but its shapes."""

    file: Label
    sha256: Sha256
    coords: Coords
    box: Box | None = None
    terrain: tuple[Terrain, ...] = ()
    regions: tuple[Region, ...] = ()
    territories: tuple[Territory, ...] = ()
    sea_zones: tuple[SeaZone, ...] = ()
    adjacency: tuple[Link, ...] = ()
    """One entry per bordering pair, in either order; never a pair twice."""

    def areas(self) -> tuple[EntityId, ...]:
        return tuple(t.area for t in self.territories) + tuple(z.area for z in self.sea_zones)


def pair(a: EntityId, b: EntityId) -> tuple[EntityId, EntityId]:
    """The pair in one order, whichever way it is named."""
    return (a, b) if a <= b else (b, a)


def adjacent(board: WorldMap, a: EntityId, b: EntityId) -> bool:
    """Whether two areas border, or are joined by a crossing. The same either way round."""
    want = pair(a, b)
    return any(pair(link.a, link.b) == want for link in board.adjacency)


def on(state: "State | View") -> bool:
    """Whether the territory rules act in this game: a map, and ``territories`` switched on."""
    from revisionist.core.state import Rule, State

    rules = state.rules if isinstance(state, State) else frozenset()
    return state.map is not None and Rule.TERRITORIES in rules


def file_hash(data: bytes) -> str:
    """The SHA-256 a world names its map file by."""
    return hashlib.sha256(data).hexdigest()


def file_keys(data: bytes) -> tuple[frozenset[str], frozenset[str]] | None:
    """The area keys and the district keys of a map file; None if it is not one."""
    try:
        raw: Any = json.loads(data)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    areas, districts = raw.get("areas"), raw.get("districts", {})
    if not isinstance(areas, dict) or not isinstance(districts, dict):
        return None
    return frozenset(map(str, areas)), frozenset(map(str, districts))


__all__ = [
    "Box",
    "Coords",
    "Link",
    "Region",
    "SeaZone",
    "Sha256",
    "Terrain",
    "TerrainKind",
    "Territory",
    "WorldMap",
    "adjacent",
    "file_hash",
    "file_keys",
    "on",
    "pair",
]
