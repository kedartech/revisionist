"""The map as the seat sees it in a territory game (TMD).

``board`` is what the ``map`` block gains in a territory game: every area with its
neighbours, the regions, the coordinates, the box and the map file by name and hash. It
is the public board, the same for every seat.

``lit`` is the moves one own piece carries: every area it can be sent to, with the
movement rule's own course (``territory.plans``), its days, the reach tier from the
bases of its side and the lift it draws. The course is planned on ``seat_board``, the
truth cut down to what the seat's view holds: the pieces of its own side and the
quantities it sees. An enemy piece the seat has no report of is not on that board, so
an area holding one is lit exactly as an empty one. Nothing is stored: the moves are
computed on every request (invariant 3).

``map_reply`` answers the ``map`` action with the map object the game's stored hash
names (``maps.map_object``), whatever map the world file names now.
"""

import json
from collections.abc import Callable
from typing import Literal

from revisionist.core.ids import EntityId
from revisionist.core.realism import bases, kinds, territory
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.kinds import Domain
from revisionist.core.state import State, View
from revisionist.engine import maps
from revisionist.engine.web.destinations import own_sides
from revisionist.engine.web.realism_api import (
    MapArea,
    MapFile,
    MapLift,
    MapMove,
    MapRegion,
    MapReply,
    PieceArea,
    SeatMap,
)

MISSING = "This game's map is missing on the server."
"""The ``map`` action's one line when no object has the game's stored hash. [proposed]"""
NO_MAP = "This game has no territory map."
"""The ``map`` action's one line in a game without territories. [proposed]"""

_TIERS: dict[bases.Tier, Literal["sustained", "operate", "raid"]] = {
    bases.Tier.SUSTAINED: "sustained",
    bases.Tier.OPERATE: "operate",
    bases.Tier.RAID: "raid",
}
"""The reach tiers a lit move can have: ``plans`` never lights a refused area."""


def _areas(board: territory.WorldMap) -> list[MapArea]:
    """Every area of the board, territories first, each with its neighbours' keys."""
    keys = {t.area: t.key for t in board.territories} | {z.area: z.key for z in board.sea_zones}

    def near(area: EntityId) -> list[str]:
        return sorted(keys[n] for n in territory.neighbours(board, area, Domain.ENVOY))

    land = [
        MapArea(
            key=t.key,
            name=t.name,
            kind="land",
            region=t.region,
            terrain=t.terrain,
            neighbours=near(t.area),
        )
        for t in board.territories
    ]
    sea = [
        MapArea(
            key=z.key,
            name=z.name,
            kind="sea",
            region=z.region,
            terrain=z.terrain,
            neighbours=near(z.area),
        )
        for z in board.sea_zones
    ]
    return land + sea


def add_board(out: SeatMap, state: State) -> SeatMap:
    """``out`` with the board's keys, in a territory game; else ``out`` as it is."""
    board = state.map
    if board is None or not territory.on(state):
        return out
    out["areas"] = _areas(board)
    out["regions"] = [MapRegion(key=r.key, name=r.name, parent=r.parent) for r in board.regions]
    out["coords"] = board.coords
    out["box"] = list(board.box) if board.box is not None else None
    out["file"] = MapFile(name=board.file, sha256=board.sha256)
    return out


def seat_board(state: State, view: View) -> State:
    """The truth with only what the seat knows of pieces and quantities: the pieces of its
    own side, the quantities its view admits, and its own nation's shipping, which a lift
    draws on (read from the truth, as the desk's lift facts are; no other side's). The
    board, the kinds, the wars and the entities are public, the same in every view."""
    own = own_sides(view)
    quantities = dict(view.quantities)
    nation = territory.nation(state, view.me.embodies)
    pool = state.map.lift_pools.get(nation) if state.map is not None and nation else None
    if pool is not None and pool in state.quantities:
        quantities[pool] = state.quantities[pool]
    return state.model_copy(
        update={
            "features": {k: f for k, f in state.features.items() if f.side in own},
            "quantities": quantities,
        }
    )


def _lift(seen: State, piece: Feature, course: territory.Plan) -> MapLift | None:
    """The lift a course draws, as the movement rule draws it: when the piece sets out on
    the water and is not on it already."""
    sent = piece.model_copy(update={"path": course.path})
    if not territory.lifted(seen, sent) or territory.lifted(seen, piece):
        return None
    ship = territory.carrier(seen, piece)
    return MapLift(tons=territory.lift_tons(piece), carrier=ship.name if ship is not None else "")


Reaches = dict[tuple[EntityId | None, str | None, EntityId], bases.AreaReach | None]
"""``bases.area_reach`` by the piece's side, its kind's key and the area: pieces of one side
and kind share every answer, so one map asks each once."""


def lit(
    seen: State, piece: Feature, area: Callable[[EntityId], PieceArea], reaches: Reaches
) -> list[MapMove]:
    """Every area ``piece`` can be sent to on the seat's board ``seen`` (``seat_board``),
    by area key; ``area`` names an area as the map names it."""
    out: list[MapMove] = []
    for at, course in territory.plans(seen, piece).items():
        if not course.path:
            continue
        kind = kinds.of(seen, piece)
        asked = (piece.side, kind.key if kind is not None else None, at)
        if asked not in reaches:
            reaches[asked] = bases.area_reach(seen, piece, at)
        reach = reaches[asked]
        out.append(
            MapMove(
                area=area(at),
                path=[area(a) for a in course.path],
                step_days=list(course.days),
                days=course.total,
                reach=_TIERS.get(reach.tier) if reach is not None else None,
                lift=_lift(seen, piece, course),
            )
        )
    out.sort(key=lambda m: str(m["area"]["key"]))
    return out


def map_reply(state: State) -> MapReply:
    """The ``map`` action's answer: the same for every seat."""
    board = state.map
    if board is None or not territory.on(state):
        return MapReply(reply=NO_MAP, refused=True, file=None, map=None)
    data = maps.map_object(board.sha256, board.file)
    if data is None:
        return MapReply(reply=MISSING, refused=True, file=None, map=None)
    shapes: dict[str, object] = json.loads(data)
    return MapReply(
        reply="", refused=False, file=MapFile(name=board.file, sha256=board.sha256), map=shapes
    )


__all__ = ["MISSING", "NO_MAP", "Reaches", "add_board", "lit", "map_reply", "seat_board"]
