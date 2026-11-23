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

import hashlib
import json
import os
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, NamedTuple

from revisionist.core.events import PieceStepped
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism import bases, kinds, territory
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.kinds import Domain
from revisionist.core.state import State, View
from revisionist.engine import maps
from revisionist.engine.store import EventStore, load_state
from revisionist.engine.web.destinations import own_sides
from revisionist.engine.web.economy_api import Holdings
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


MARK_SECRET_ENV = "REVISIONIST_MARK_SECRET"
"""A deployment's persistent 32-byte secret, encoded as 64 hex digits."""


def mark_secret() -> bytes:
    """Fail closed, including outside the HTTP server; never log the supplied value."""
    value = os.environ.get(MARK_SECRET_ENV, "")
    if re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError(f"{MARK_SECRET_ENV} must be set to 64 hex digits")
    return bytes.fromhex(value)


def mark_key(campaign: CampaignId, nation: EntityId, raw: str) -> str:
    """Seat-safe MAC of a core/label mark, shared by this nation's map and playback.

    The core digest is public-input data, not a secret. Namespace the MAC by campaign
    and viewing nation even when the inner digest already includes them. JSON framing
    keeps arbitrary labels/ids unambiguous. Never persist this deployment-specific key.
    """
    message = json.dumps(["seat-mark-v1", campaign, nation, raw], separators=(",", ":"))
    return "m" + hashlib.blake2b(message.encode(), key=mark_secret(), digest_size=16).hexdigest()


def step_key(campaign: CampaignId, step: PieceStepped) -> str:
    """Protect a stored movement mark for its owning nation's playback, old logs too.

    The caller must enforce the event's visibility before sending it. This converts a
    key, not access rights; no current web endpoint serializes movement events.
    """
    return mark_key(campaign, step.nation, step.mark)


def viewing_nation(view: View) -> EntityId:
    """Nearest polity of the viewing seat, including the view-only label fallback."""
    seen: set[EntityId] = set()
    here = view.entities.get(view.me.embodies)
    while here is not None and here.entity_id not in seen:
        if here.kind is EntityKind.POLITY:
            return here.entity_id
        seen.add(here.entity_id)
        here = view.entities.get(here.parent) if here.parent is not None else None
    return view.me.embodies


def protect_marks(out: SeatMap, view: View) -> None:
    """MAC each outgoing mark once, after raw keys have joined marks and own pieces; and
    each report's key the same way (RPD)."""
    nation = viewing_nation(view)
    for mark in out["marks"]:
        key = mark_key(view.campaign_id, nation, mark["key"])
        mark["key"] = key
        if mark["piece"] is not None:
            mark["piece"]["key"] = key
    for report in out.get("reports", ()):
        report["key"] = mark_key(view.campaign_id, nation, report["key"])


def report_keys(view: View, raw: Sequence[str]) -> tuple[str, ...]:
    """The keys ``protect_marks`` gives the reports with core keys ``raw``, sorted: the
    one key a seat knows a report by, in every reply that names one."""
    nation = viewing_nation(view)
    return tuple(sorted(mark_key(view.campaign_id, nation, k) for k in raw))


def _areas(board: territory.WorldMap, held: Holdings) -> list[MapArea]:
    """Every area of the board, territories first, each with its neighbours' keys; a
    territory with its holder keys and printed yields."""
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
            holder=held.holder(t.area),
            held_since=held.held_since(t.area),
            taken_from=held.taken_from(t.area),
            falling=held.falling(t.area),
            yields=dict(t.yields),
            threatened_from=None,
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
            holder=None,
            held_since=None,
            taken_from=None,
            falling=None,
            yields={},
            threatened_from=None,
        )
        for z in board.sea_zones
    ]
    return land + sea


def _threats(out: SeatMap, board: territory.WorldMap, state: State, view: View) -> None:
    """Each land area the seat's nation holds names the reports whose area or ring takes
    in it or an area next to it (RNG). Read from the reports already in ``out`` and the
    public board and holders."""
    nation = viewing_nation(view)
    own = {t.key for t in board.territories if territory.holder(state, t.area) == nation}
    touched = []
    for r in out.get("reports", ()):
        where = set(r["ring"] or ())
        if r["area"] is not None:
            where.add(r["area"]["key"])
        touched.append((r["key"], where))
    for area in out.get("areas", ()):
        if area["key"] in own:
            near = {area["key"], *area["neighbours"]}
            area["threatened_from"] = sorted(k for k, where in touched if where & near)


def add_board(out: SeatMap, state: State, view: View) -> SeatMap:
    """``out`` with the board's keys, in a territory game; else ``out`` as it is. The
    holder keys are as ``view``'s seat sees them. With ``reports`` on (``out`` carries
    them), each of the seat's own areas names the reports that threaten it."""
    board = state.map
    if board is None or not territory.on(state):
        return out
    out["areas"] = _areas(board, Holdings(state, view, view.me.seat_id))
    if "reports" in out:
        _threats(out, board, state, view)
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


class MapRef(NamedTuple):
    """The map a stored campaign names: the file name and hash its ``map_declared`` holds."""

    campaign: CampaignId
    file: str
    sha256: str


def references(store: EventStore, campaign_ids: Sequence[CampaignId]) -> list[MapRef]:
    """Every map the campaigns name; a campaign without a map names none."""
    out: list[MapRef] = []
    for campaign in campaign_ids:
        board = load_state(store, campaign).map
        if board is not None:
            out.append(MapRef(campaign, board.file, board.sha256))
    return out


def _kept(directory: Path, sha256: str) -> bytes | None:
    """The bytes of ``<sha256>.json`` in ``directory`` when they hash to ``sha256``."""
    path = directory / f"{sha256}.json"
    data = path.read_bytes() if path.is_file() else None
    return data if data is not None and hashlib.sha256(data).hexdigest() == sha256 else None


def verify_objects(store: EventStore, campaign_ids: Sequence[CampaignId]) -> tuple[list[str], bool]:
    """One line per campaign that names a map: ``ok``, or ``FAIL`` when its object is not
    in the map-objects directory. Only that directory counts, never a world-named file."""
    here = maps.objects_dir()
    lines: list[str] = []
    ok = True
    for ref in references(store, campaign_ids):
        if _kept(here, ref.sha256) is None:
            lines.append(
                f"FAIL {ref.campaign}: map object {ref.sha256} ({ref.file}) is not in {here}"
            )
            ok = False
        else:
            lines.append(f"ok {ref.campaign}: map object {ref.sha256} ({ref.file})")
    return lines, ok


def _put(to: Path, sha256: str, data: bytes) -> str | None:
    """Write ``<sha256>.json`` into ``to`` and read it back against its hash; the problem,
    or None when it reads back."""
    to.mkdir(parents=True, exist_ok=True)
    part = to / f"{sha256}.json.partial"
    part.write_bytes(data)
    part.replace(to / f"{sha256}.json")
    return (
        None
        if _kept(to, sha256) is not None
        else f"map object {sha256} does not read back from {to}"
    )


def copy_objects(
    store: EventStore, campaign_ids: Sequence[CampaignId], to: Path
) -> tuple[list[str], bool]:
    """Copy each referenced object into ``to`` and read it back against its hash. Nothing
    is written for a missing object, and no source file is changed."""
    here = maps.objects_dir()
    lines: list[str] = []
    ok = True
    done: set[str] = set()
    for ref in references(store, campaign_ids):
        data = _kept(here, ref.sha256)
        if data is None:
            lines.append(
                f"FAIL {ref.campaign}: map object {ref.sha256} ({ref.file}) is not in {here}"
            )
            ok = False
        elif ref.sha256 not in done:
            problem = _put(to, ref.sha256, data)
            ok = ok and problem is None
            lines.append(
                f"FAIL {ref.campaign}: {problem}"
                if problem
                else f"copied {ref.sha256} ({ref.file}) to {to}"
            )
            done.add(ref.sha256)
    return lines, ok


def copy_all_objects(to: Path) -> tuple[list[str], bool]:
    """Copy every object in the map-objects directory into ``to``, each read back against
    its hash; needs no database. A file whose bytes do not hash to its name fails."""
    here = maps.objects_dir()
    lines: list[str] = []
    ok = True
    for path in sorted(here.glob("*.json")):
        sha256 = path.stem
        if _kept(here, sha256) is None:
            lines.append(f"FAIL map object {path.name} in {here} does not hash to its name")
            ok = False
        else:
            problem = _put(to, sha256, path.read_bytes())
            ok = ok and problem is None
            lines.append(f"FAIL {problem}" if problem else f"copied {sha256} to {to}")
    return lines, ok


__all__ = [
    "MARK_SECRET_ENV",
    "MISSING",
    "NO_MAP",
    "MapRef",
    "Reaches",
    "add_board",
    "copy_all_objects",
    "copy_objects",
    "lit",
    "map_reply",
    "mark_key",
    "mark_secret",
    "protect_marks",
    "references",
    "report_keys",
    "seat_board",
    "step_key",
    "verify_objects",
    "viewing_nation",
]
