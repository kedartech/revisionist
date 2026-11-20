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

With ``territories`` switched on, a piece stands in one area and moves by adjacency, one
step at a time (ADJ). ``plan`` finds the course of fewest days for the piece's domain:
land pieces over land territories and declared crossings (across sea zones only by lift,
from a port to a port), sea pieces over sea zones, air pieces over any area within their
range of a base of their side, envoys over any area. A step into an area takes the kind's
``days_per_step`` for the terrain of the area entered, and ties between courses of equal
days go to the one whose area keys sort first. ``step`` is the one function that
completes a step, whatever moved the piece; each step lands one ``piece_stepped`` event.
"""

import hashlib
import heapq
import json
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal, NamedTuple

from pydantic import Field, StringConstraints

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, QuantityId

if TYPE_CHECKING:
    from revisionist.core.events import PieceStepped
    from revisionist.core.realism.geography import Feature
    from revisionist.core.realism.kinds import Domain, PieceKind
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
    defence: int = Field(default=0, ge=0, le=2)
    """What the terrain adds to a defender's score in battle."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"defence"})


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


BaseDomain = Literal["land", "sea", "air"]
"""The domains a base serves. An envoy needs none."""


class Port(Model):
    """A place where a territory meets a sea zone: a sea piece declared there stands in
    the zone, and a land piece embarks or lands there on a lift."""

    place: EntityId
    land: EntityId
    """The territory the place lies within."""
    sea: EntityId
    """The sea zone it opens on (``port_on``)."""


class Base(Model):
    """A site a side's pieces work from, for the domains it names (``base`` in the world)."""

    place: EntityId
    land: EntityId | None
    """The territory it lies in; None for a place within a sea zone."""
    sea: EntityId | None
    """The sea zone its ships stand in: the port's, or the zone it lies in; None inland."""
    sides: tuple[EntityId, ...]
    domains: tuple[BaseDomain, ...]

    def area(self, domain: str) -> EntityId | None:
        """The area a piece of ``domain`` stands in at this base."""
        return self.sea if domain == "sea" else self.land


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
    ports: tuple[Port, ...] = ()
    bases: tuple[Base, ...] = ()
    lift_pools: dict[EntityId, QuantityId] = Field(default_factory=dict)
    """Each lifting polity's pool of shipping, by the quantity that holds it."""
    capitals: dict[EntityId, EntityId] = Field(default_factory=dict)
    """Each polity's capital site, a place, by the polity (``capital`` in the world)."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"ports", "bases", "lift_pools", "capitals"})

    def areas(self) -> tuple[EntityId, ...]:
        return tuple(t.area for t in self.territories) + tuple(z.area for z in self.sea_zones)


def pair(a: EntityId, b: EntityId) -> tuple[EntityId, EntityId]:
    """The pair in one order, whichever way it is named."""
    return (a, b) if a <= b else (b, a)


def adjacent(board: WorldMap, a: EntityId, b: EntityId) -> bool:
    """Whether two areas border, or are joined by a crossing. The same either way round."""
    want = pair(a, b)
    return any(pair(link.a, link.b) == want for link in board.adjacency)


def on(state: "State") -> bool:
    """Whether the territory rules act in this game: a map, and ``territories`` switched on."""
    from revisionist.core.state import Rule

    return state.map is not None and Rule.TERRITORIES in state.rules


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


# --- moving by adjacency (ADJ) -----------------------------------------------------


class StepCause(StrEnum):
    """What moved a piece one step."""

    ORDERED = "ordered"
    """A seat's order, the aide's, or an effect that sent it."""
    SCRIPTED = "scripted"
    """A move the record says it made (a leg falling due)."""
    FORCED = "forced"
    """A battle's forced retreat or return."""


class _Graph(NamedTuple):
    kind: dict[EntityId, TerrainKind]
    terrain: dict[EntityId, str]
    key: dict[EntityId, str]
    links: dict[EntityId, tuple[EntityId, ...]]
    """Each area's neighbours, sorted by key."""


def _graph(board: WorldMap) -> _Graph:
    kind = {t.area: TerrainKind.LAND for t in board.territories} | {
        z.area: TerrainKind.SEA for z in board.sea_zones
    }
    terrain = {t.area: t.terrain for t in board.territories} | {
        z.area: z.terrain for z in board.sea_zones
    }
    key = {t.area: t.key for t in board.territories} | {z.area: z.key for z in board.sea_zones}
    near: dict[EntityId, set[EntityId]] = {a: set() for a in kind}
    for link in board.adjacency:
        near.setdefault(link.a, set()).add(link.b)
        near.setdefault(link.b, set()).add(link.a)
    links = {a: tuple(sorted(ns, key=lambda n: key.get(n, n))) for a, ns in near.items()}
    return _Graph(kind, terrain, key, links)


def _by_domain(g: _Graph, area: EntityId, domain: str) -> tuple[EntityId, ...]:
    """The neighbours a piece of ``domain`` steps to: land over land (borders and
    crossings), sea over sea, air and envoys anywhere."""
    near = g.links.get(area, ())
    if domain == "land":
        return tuple(n for n in near if g.kind.get(n) is TerrainKind.LAND)
    if domain == "sea":
        return tuple(n for n in near if g.kind.get(n) is TerrainKind.SEA)
    return near


def neighbours(board: WorldMap, area: EntityId, domain: "Domain") -> tuple[EntityId, ...]:
    """The areas a piece of ``domain`` can step to from ``area``, sorted by key. A land
    piece's lift across sea zones is ``plan``'s, not a neighbour."""
    return _by_domain(_graph(board), area, domain)


def steps_from(board: WorldMap, domain: str, sources: Iterable[EntityId]) -> dict[EntityId, int]:
    """Steps from the nearest of ``sources`` to each area a piece of ``domain`` can reach."""
    g = _graph(board)
    out = {s: 0 for s in sources}
    queue = deque(sorted(out))
    while queue:
        here = queue.popleft()
        for n in _by_domain(g, here, domain):
            if n not in out:
                out[n] = out[here] + 1
                queue.append(n)
    return out


Course = tuple[int, tuple[EntityId, ...], tuple[int, ...]]
"""Days in all, the areas entered in order, and the days each step takes."""


def _search(
    g: _Graph, start: EntityId, moves: Callable[[EntityId], Iterable[tuple[EntityId, int]]]
) -> dict[EntityId, Course]:
    """The course of fewest days from ``start`` to every area ``moves`` reaches; between
    courses of equal days, the one whose area keys sort first."""
    heap: list[tuple[int, tuple[str, ...], EntityId, tuple[EntityId, ...], tuple[int, ...]]]
    heap = [(0, (), start, (), ())]
    done: dict[EntityId, Course] = {}
    while heap:
        days, keys, here, path, each = heapq.heappop(heap)
        if here in done:
            continue
        done[here] = (days, path, each)
        for n, cost in moves(here):
            if n not in done:
                entry = (days + cost, (*keys, g.key.get(n, n)), n, (*path, n), (*each, cost))
                heapq.heappush(heap, entry)
    return done


def steps_within(
    board: WorldMap, kind: "PieceKind", frm: EntityId, days: int
) -> dict[EntityId, int]:
    """Every area a piece of ``kind`` could reach from ``frm`` in ``days`` days or fewer, with
    the fewest days to each (``frm`` itself at 0). The board alone: no holder, base, range or
    lift is read."""
    from revisionist.core.realism.kinds import stands_on

    g = _graph(board)

    def moves(here: EntityId) -> Iterable[tuple[EntityId, int]]:
        for n in _by_domain(g, here, kind.domain):
            cost = kind.days_per_step.get(g.terrain[n])
            if cost is not None:
                yield n, cost

    found = _search(g, frm, moves)
    return {
        a: d for a, (d, _, _) in found.items() if d <= days and stands_on(kind.domain, g.kind[a])
    }


def holder(state: "State | View", area: EntityId) -> EntityId | None:
    """The polity holding a territory now: the last ``area_held`` for it (THL), else the
    board's; None for a sea zone or a territory nobody holds."""
    board = state.map
    if board is None:
        return None
    held = state.holders.get(area)
    if held is not None:
        return held.holder
    return next((t.holder for t in board.territories if t.area == area), None)


def nation(state: "State", side: EntityId | None) -> EntityId | None:
    """The polity a piece's side belongs to: the side itself, or its nearest polity."""
    from revisionist.core.realism.war import polity_of

    return None if side is None else polity_of(state, side) or side


def allied(state: "State", a: EntityId, b: EntityId) -> bool:
    """Whether two polities are allies: not at war with each other, and both at war with a
    common enemy (the plan's one definition, shared with the holders' base rule)."""
    from revisionist.core.realism.war import at_war

    if a == b or at_war(state, a, b):
        return False
    foes = {w.b if w.a == a else w.a for w in state.wars.values() if a in (w.a, w.b)}
    return any(at_war(state, b, foe) for foe in foes if foe != b)


def barred(state: "State", side: EntityId | None, area: EntityId) -> EntityId | None:
    """The holder that bars a piece of ``side`` from ``area``: a polity neither its own, an
    ally, nor at war with it. None when the piece may enter."""
    from revisionist.core.realism.war import at_war

    own = nation(state, side)
    held = holder(state, area)
    if held is None or own is None or held == own:
        return None
    if allied(state, own, held) or at_war(state, own, held):
        return None
    return held


def area_of(state: "State", place: EntityId, domain: "Domain") -> EntityId | None:
    """The area a piece of ``domain`` stands in when it is at ``place``: the area itself,
    a sea piece at a port the zone the port opens on, else the area the place lies
    within. None for a place in no area."""
    board = state.map
    if board is None:
        return None
    areas = set(board.areas())
    if place in areas:
        return place
    if domain == "sea":
        port = next((p for p in board.ports if p.place == place), None)
        if port is not None:
            return port.sea
    entity = state.entities.get(place)
    within = entity.within if entity is not None else None
    return within if within in areas else None


def _is_sea(board: WorldMap, area: EntityId) -> bool:
    return any(z.area == area for z in board.sea_zones)


def _kind_of(state: "State", piece: "Feature") -> "PieceKind | None":
    from revisionist.core.realism import kinds

    return kinds.of(state, piece)


def lifted(state: "State", piece: "Feature") -> bool:
    """Whether a land piece is on a lift: at sea, or on a course that crosses the sea."""
    board, kind = state.map, _kind_of(state, piece)
    if board is None or kind is None or kind.domain != "land":
        return False
    return any(_is_sea(board, a) for a in (piece.places[0], *piece.path))


def carrier(state: "State", piece: "Feature") -> "PieceKind | None":
    """The first of the world's kinds, in the world file's order, that carries this piece's."""
    kind = _kind_of(state, piece)
    if state.kinds is None or kind is None:
        return None
    return next((k for k in state.kinds.pieces.values() if kind.key in k.carries), None)


def lift_pool(state: "State", piece: "Feature") -> QuantityId | None:
    """The pool a land piece's lift is drawn from: its nation's, if the world names one."""
    board, own = state.map, nation(state, piece.side)
    if board is None or own is None:
        return None
    return board.lift_pools.get(own)


def lift_tons(piece: "Feature") -> int:
    """What a lift of this piece takes from its pool, by today's lift rule."""
    from revisionist.core.realism.sealift import lift_needed

    return lift_needed(piece)


def _can_lift(state: "State", piece: "Feature") -> bool:
    """A carrier kind, and a pool that holds the lift (or the piece already at sea)."""
    if carrier(state, piece) is None:
        return False
    if lifted(state, piece):
        return True
    pool = lift_pool(state, piece)
    q = state.quantities.get(pool) if pool is not None else None
    return q is not None and q.value is not None and q.value >= lift_tons(piece)


def step_days(state: "State", piece: "Feature", to: EntityId) -> int | None:
    """Days a step into ``to`` takes this piece: its kind's for the terrain entered, or a
    land piece's carrier's for a sea zone. None where it cannot step."""
    board, kind = state.map, _kind_of(state, piece)
    if board is None or kind is None:
        return None
    terrain = _graph(board).terrain.get(to)
    if terrain is None:
        return None
    if kind.domain == "land" and _is_sea(board, to):
        lift = carrier(state, piece)
        days = None if lift is None else lift.days_per_step.get(terrain)
    else:
        days = kind.days_per_step.get(terrain)
    return None if days is None else days + _slower(piece)


def _slower(piece: "Feature") -> int:
    """A day more a step for a concealed piece (IOR)."""
    from revisionist.core.realism.detect import concealed

    return 1 if concealed(piece) else 0


class Plan(NamedTuple):
    """A course: the areas entered in order and the days each step takes."""

    path: tuple[EntityId, ...]
    days: tuple[int, ...]

    @property
    def total(self) -> int:
        return sum(self.days)


class Refused(NamedTuple):
    """Why a piece cannot be sent somewhere, and the nearest area it could be sent to."""

    reason: str
    nearest: EntityId | None


def _air_range(state: "State", piece: "Feature", kind: "PieceKind") -> set[EntityId] | None:
    """The areas within an air kind's range of a base of its side; None when the world
    names no base (no reach rule) or the piece is not air."""
    board = state.map
    if board is None or kind.range_steps is None or not board.bases:
        return None
    from revisionist.core.realism.holders import serves

    own = nation(state, piece.side)
    sources = [
        a
        for b in board.bases
        if serves(state, b, own) and "air" in b.domains and (a := b.area("air")) is not None
    ]
    reach = steps_from(board, "air", sources)
    return {a for a, n in reach.items() if n <= kind.range_steps}


def _reach(state: "State", piece: "Feature") -> set[EntityId] | None:
    from revisionist.core.realism.bases import within_reach

    return within_reach(state, piece)


def _reach_refused(state: "State", piece: "Feature", area: EntityId) -> str | None:
    from revisionist.core.realism.bases import Tier, area_reach

    found = area_reach(state, piece, area)
    return found.reason if found is not None and found.tier is Tier.REFUSED else None


def plans(state: "State", piece: "Feature") -> dict[EntityId, Plan]:
    """Every area the piece can be sent to, with its course of fewest days (the area it
    stands in with an empty course). A land piece goes by land wherever land reaches, and
    by lift, from a port to a port, only to an area no land course reaches."""
    from revisionist.core.realism.kinds import stands_on

    board, kind = state.map, _kind_of(state, piece)
    if board is None or kind is None:
        return {}
    g = _graph(board)
    domain = kind.domain
    lift = domain == "land" and _can_lift(state, piece)
    in_range = _air_range(state, piece, kind)
    reach = _reach(state, piece)
    ship = carrier(state, piece)
    shut = {a for a in g.kind if barred(state, piece.side, a) is not None}
    slower = _slower(piece)

    def moves(here: EntityId, by_lift: bool) -> Iterable[tuple[EntityId, int]]:
        at_sea = g.kind.get(here) is TerrainKind.SEA
        if domain == "land" and at_sea:
            near = [n for n in g.links.get(here, ()) if g.kind.get(n) is TerrainKind.SEA]
            near += [p.land for p in board.ports if p.sea == here]
        else:
            near = list(_by_domain(g, here, domain))
            if by_lift:
                near += [p.sea for p in board.ports if p.land == here]
        for n in sorted(set(near), key=lambda a: g.key.get(a, a)):
            if n in shut:
                continue
            if in_range is not None and n not in in_range:
                continue
            transit = domain == "land" and g.kind.get(n) is TerrainKind.SEA
            if not transit and reach is not None and n not in reach:
                continue
            by = ship if domain == "land" and g.kind.get(n) is TerrainKind.SEA else kind
            cost = None if by is None else by.days_per_step.get(g.terrain[n])
            if cost is not None:
                yield n, cost + slower

    here = piece.places[0]
    found: dict[EntityId, Course] = {}
    if g.kind.get(here) is not TerrainKind.SEA or domain != "land":
        found = _search(g, here, lambda a: moves(a, False))
    if lift:
        for a, course in _search(g, here, lambda a: moves(a, True)).items():
            found.setdefault(a, course)
    return {
        a: Plan(path, each) for a, (_, path, each) in found.items() if stands_on(domain, g.kind[a])
    }


def _name(state: "State", entity: EntityId | None) -> str:
    e = state.entities.get(entity) if entity is not None else None
    return e.name if e is not None else "it"


def _why(state: "State", piece: "Feature", kind: "PieceKind", area: EntityId) -> str:
    from revisionist.core.realism.kinds import stands_on

    board = state.map
    assert board is not None
    there = _name(state, area)
    if not stands_on(kind.domain, _graph(board).kind[area]):
        return f"{piece.name} cannot stand in {there}."
    held = barred(state, piece.side, area)
    if held is not None:
        own = _name(state, nation(state, piece.side))
        return f"{there} is held by {_name(state, held)}, neither {own}'s ally nor at war with it."
    in_range = _air_range(state, piece, kind)
    if in_range is not None and area not in in_range:
        return f"{there} is beyond {piece.name}'s range of {kind.range_steps} steps from a base."
    refused = _reach_refused(state, piece, area)
    if refused is not None:
        return refused
    return f"No way lies open for {piece.name} to {there}."


def _nearest(
    board: WorldMap, open_to: Mapping[EntityId, Plan], wanted: EntityId
) -> EntityId | None:
    """Of the areas the piece could be sent to, the fewest steps from ``wanted`` over every
    link; ties go to the area whose key sorts first."""
    g = _graph(board)
    far = steps_from(board, "envoy", [wanted])
    ranked = sorted((far[a], g.key.get(a, a), a) for a in open_to if a in far)
    return ranked[0][2] if ranked else None


def plan(state: "State", piece: "Feature", to: EntityId) -> Plan | Refused:
    """The course to send the piece to ``to`` (an area or a place), or why it cannot go
    there with the nearest area it could be sent to."""
    board, kind = state.map, _kind_of(state, piece)
    if board is None or kind is None:
        return Refused(f"{piece.name} does not move on the map.", None)
    dest = area_of(state, to, kind.domain)
    if dest is None:
        return Refused(f"{_name(state, to)} is not on the map.", None)
    open_to = plans(state, piece)
    found = open_to.get(dest)
    if found is not None:
        return found
    nearest = _nearest(board, open_to, dest)
    tail = (
        ""
        if nearest is None
        else f" The nearest area it could be sent to is {_name(state, nearest)}."
    )
    return Refused(_why(state, piece, kind, dest) + tail, nearest)


def path(state: "State", piece: "Feature", to: EntityId) -> tuple[EntityId, ...] | None:
    """The areas the piece would enter, in order, sent to ``to``; None if it cannot go."""
    found = plan(state, piece, to)
    return found.path if isinstance(found, Plan) else None


def mark_key(state: "State", polity: EntityId, feature: "Feature") -> str:
    """Stable core/event correlation key, NOT seat-safe: public inputs recover it.

    The web boundary MACs this value under a deployment secret before sending it to a
    seat. Keep this function unchanged for deterministic replay of stored events.
    """
    raw = "\x1f".join((str(state.campaign_id), "mark", str(polity), str(feature.feature_id)))
    return "m" + hashlib.blake2b(raw.encode(), digest_size=8).hexdigest()


def step(
    state: "State", piece: "Feature", entered: EntityId, on: date, cause: StepCause
) -> tuple["Feature", "PieceStepped"]:
    """Complete one step: ``piece`` stands in ``entered`` from ``on``. The area entered
    comes off the head of its course if it was next; a piece whose course is spent has
    arrived. Raises ``ValueError`` for an area that does not border the one it is in."""
    from revisionist.core.events import PieceStepped

    board = state.map
    left = piece.places[0]
    if board is None or not adjacent(board, left, entered):
        raise ValueError(f"{piece.feature_id}: {entered} does not border {left}")
    rest = piece.path[1:] if piece.path[:1] == (entered,) else piece.path
    update: dict[str, object] = {"places": (entered,), "path": rest, "as_of": max(on, piece.as_of)}
    if not rest:
        update |= {"step_due": None, "bound_for": None, "arrives": None}
    own = nation(state, piece.side)
    assert own is not None, "a piece that steps belongs to a side"
    stepped = PieceStepped(
        mark=mark_key(state, own, piece),
        nation=own,
        left=left,
        entered=entered,
        on=on,
        cause=cause,
    )
    return piece.model_copy(update=update), stepped


__all__ = [
    "Base",
    "Box",
    "Coords",
    "Link",
    "Plan",
    "Port",
    "Refused",
    "Region",
    "SeaZone",
    "Sha256",
    "StepCause",
    "Terrain",
    "TerrainKind",
    "Territory",
    "WorldMap",
    "adjacent",
    "allied",
    "area_of",
    "barred",
    "carrier",
    "file_hash",
    "file_keys",
    "holder",
    "lift_pool",
    "lift_tons",
    "lifted",
    "mark_key",
    "nation",
    "neighbours",
    "on",
    "pair",
    "path",
    "plan",
    "plans",
    "step",
    "step_days",
    "steps_from",
    "steps_within",
]
