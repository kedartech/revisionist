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
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, NamedTuple, cast

from revisionist.core.events import PieceStepped
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism import (
    bases,
    battle,
    detect,
    economy,
    kinds,
    supply,
    territory,
    trade,
    weather,
)
from revisionist.core.realism.card import words
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.kinds import Domain
from revisionist.core.realism.weather import WeatherKind
from revisionist.core.state import State, View
from revisionist.engine import maps
from revisionist.engine.store import EventStore, load_state
from revisionist.engine.web.destinations import own_sides
from revisionist.engine.web.economy_api import Holdings
from revisionist.engine.web.realism_api import (
    FigureCause,
    FigureChange,
    FigureName,
    MapArea,
    MapFile,
    MapLift,
    MapMove,
    MapRegion,
    MapReply,
    PieceArea,
    PieceFigures,
    PieceKindView,
    RegionWeather,
    SeatMap,
    WeatherBlock,
    WeatherEffect,
    WeatherKindView,
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
    seen: State,
    piece: Feature,
    area: Callable[[EntityId], PieceArea],
    reaches: Reaches,
    there: "Callable[[EntityId, date], Standing] | None" = None,
) -> list[MapMove]:
    """Every area ``piece`` can be sent to on the seat's board ``seen`` (``seat_board``),
    by area key; ``area`` names an area as the map names it. With ``there`` (KVW), each
    move carries the piece's figures as ``there`` gives them in the area on the day it
    would arrive."""
    out: list[MapMove] = []
    today = seen.in_world_date
    for at, course in territory.plans(seen, piece).items():
        if not course.path:
            continue
        kind = kinds.of(seen, piece)
        asked = (piece.side, kind.key if kind is not None else None, at)
        if asked not in reaches:
            reaches[asked] = bases.area_reach(seen, piece, at)
        reach = reaches[asked]
        move = MapMove(
            area=area(at),
            path=[area(a) for a in course.path],
            step_days=list(course.days),
            days=course.total,
            reach=_TIERS.get(reach.tier) if reach is not None else None,
            lift=_lift(seen, piece, course),
        )
        if there is not None and today is not None:
            stood = there(at, today + timedelta(days=course.total))
            move["figures"], move["changes"] = stood.figures, stood.changes
        out.append(move)
    out.sort(key=lambda m: str(m["area"]["key"]))
    return out


# --- a piece's figures as the seat sees them (KVW) ------------------------------------

SPEED_TOP = 6
"""[proposed] A kind's speed is this less the fewest days a step of it takes, held to 1 to 5:
a day a step is 5, five days or more is 1."""
HIDDEN_STEP = 25
"""[proposed] A kind's hidden figure is 1 and one more for each this much concealment."""
CAUSE_WORDS: dict[FigureCause, str] = {
    "terrain": "the ground",
    "weather": "the weather",
    "out_of_supply": "out of supply",
    "out_of_fuel": "out of fuel",
    "air_cover": "air cover",
    "enemy_kind": "an enemy kind reported there",
}
"""The fixed words of each cause; the ground, the weather and the enemy kind are named."""


class Standing(NamedTuple):
    """A piece's figures in an area on a day, and what changes them there."""

    figures: PieceFigures
    changes: list[FigureChange]


class Reported(NamedTuple):
    """What the seat's reports say of the enemy at an area on a day: what an ``against``
    reads of it (each reported kind's key and domain, a report naming no kind as the
    area's domain), the names those stand for, whether a reported piece gives the enemy
    air support there and whether a reported piece covers it. Read from the view alone."""

    facing: frozenset[str]
    names: dict[str, str]
    air: bool
    covers: bool
    support: tuple[kinds.PieceKind, ...]
    """The kinds of the reported pieces that give that support."""


def kind_figures(kind: kinds.PieceKind) -> PieceFigures:
    """The kind's own five figures."""
    return PieceFigures(
        attack=kind.attack,
        defence=kind.defence,
        speed=kinds.held(SPEED_TOP - min(kind.days_per_step.values(), default=SPEED_TOP)),
        reach=kinds.held(_reach_steps(kind)),
        hidden=kinds.held(1 + kind.conceal // HIDDEN_STEP),
    )


def _reach_steps(kind: kinds.PieceKind) -> int:
    found = battle._reach(kind)
    return found if found else 1


def area_domain(board: territory.WorldMap, area: EntityId) -> Domain:
    """The domain an unnamed kind is taken for in ``area``: sea in a sea zone, else land."""
    return Domain.SEA if any(z.area == area for z in board.sea_zones) else Domain.LAND


def plain_kind(domain: Domain) -> kinds.PieceKind:
    """The kind a report naming none is taken for: its domain's, with every figure 3."""
    return kinds.PieceKind(key=domain.value, name=domain.value, domain=domain, days_per_step={})


def reported(world: State, view: View, area: EntityId, day: date) -> Reported:
    """What the seat's reports say of the enemy at ``area`` on ``day``: ``view.reports``
    and the public board, kinds and weather of ``world`` only."""
    board = world.map
    assert board is not None
    pieces = view.kinds.pieces if view.kinds is not None else {}
    sky = weather.sky(world)
    facing: set[str] = set()
    names: dict[str, str] = {}
    support: list[kinds.PieceKind] = []
    covers = False
    for _, r in sorted(view.reports.items()):
        if r.area is None:
            continue
        kind = pieces.get(r.kind) if r.kind is not None else None
        if r.area == area:
            if kind is None:
                where = area_domain(board, area)
                facing.add(where.value)
                names.setdefault(where.value, f"{where.value} pieces")
            else:
                facing |= {kind.key, kind.domain.value}
                names.setdefault(kind.key, kind.name)
                names.setdefault(kind.domain.value, kind.name)
        steps = battle._reach(kind) if kind is not None else None
        if kind is not None and kind.covers and steps is None and r.area == area:
            covers = True
        if kind is None or steps is None:
            continue
        far = territory.steps_from(board, "air", [r.area]).get(area)
        grounded = sky is not None and (sky.grounded(r.area, day) or sky.grounded(area, day))
        if far is None or far > steps or grounded:
            continue
        support.append(kind)
        facing |= {kind.key, kind.domain.value}
        names.setdefault(kind.key, kind.name)
        names.setdefault(kind.domain.value, kind.name)
        covers = covers or kind.covers
    return Reported(frozenset(facing), names, bool(support), covers, tuple(support))


def _line(which: str, by: int, cause: FigureCause, said: str) -> FigureChange:
    return FigureChange(
        figure=cast("FigureName", which),
        direction="up" if by > 0 else "down",
        cause=cause,
        words=said,
    )


def standing(
    seen: State,
    view: View,
    piece: Feature,
    kind: kinds.PieceKind,
    area: EntityId,
    day: date,
    *,
    supplied: bool = True,
    fuelled: bool = True,
) -> Standing:
    """``piece``'s figures in ``area`` on ``day`` and what changes them there, in the order
    the battle applies them: the ground, the enemy kinds the reports put there or in reach,
    the weather; then air cover from its own side's pieces in reach, unless a reported
    enemy covers the area, and being out of supply, each a step as the battle counts them.
    ``seen`` is the seat's board (``seat_board``): its own side's pieces only; the enemy
    is read from ``view``'s reports alone."""
    from revisionist.core.realism.kinds import Condition, Figure

    board = seen.map
    assert board is not None
    sky = weather.sky(seen)
    terrain = battle._terrain(seen, area)
    enemy = reported(seen, view, area, day)
    holds = set() if enemy.air else {Condition.NO_ENEMY_AIR}
    shift = sky.shift(kind, area, day) if sky is not None else ()
    held = sky.holds(area, day) if sky is not None else None
    nation = territory.nation(seen, piece.side)
    air = nation is not None and bool(battle._support(seen, nation, area, day))
    air = air and not enemy.covers
    lines: list[FigureChange] = []
    out = kind_figures(kind)
    for which in (Figure.ATTACK, Figure.DEFENCE):
        steps: list[tuple[int, FigureCause, str]] = []
        if terrain is not None and terrain in kind.on_terrain:
            by = getattr(kind.on_terrain[terrain], which.value)
            steps.append((by, "terrain", f"the {words(terrain)}"))
        for a in kind.against:
            if a.facing in enemy.facing and (a.when is None or a.when in holds):
                said = f"{enemy.names.get(a.facing, words(a.facing))} reported there"
                steps.append((getattr(a, which.value), "enemy_kind", said))
        for s in shift:
            steps.append((getattr(s, which.value), "weather", held.name if held else "weather"))
        if air:
            steps.append((battle.AIR_SUPPORT, "air_cover", CAUSE_WORDS["air_cover"]))
        if not supplied:
            steps.append((-1, "out_of_supply", CAUSE_WORDS["out_of_supply"]))
        value: int = getattr(kind, which.value)
        for by, cause, said in steps:
            value = kinds.held(value + by)
            if by:
                lines.append(_line(which.value, by, cause, said))
        out[which.value] = value  # type: ignore[literal-required]
    least = min(kind.days_per_step.values(), default=SPEED_TOP)
    days = kind.days_per_step.get(terrain or "", least)
    if days > least:
        lines.append(_line("speed", -1, "terrain", f"the {words(terrain or '')}"))
    extra = sky.step(kind, area, day) if sky is not None else 0
    if extra is None or extra > 0:
        lines.append(_line("speed", -1, "weather", held.name if held else "weather"))
    out["speed"] = kinds.held(SPEED_TOP - days - (extra or 0)) if extra is not None else 1
    if not fuelled:
        out["speed"] = kinds.FIGURE_LOW
        lines.append(_line("speed", -1, "out_of_fuel", CAUSE_WORDS["out_of_fuel"]))
    if battle._reach(kind) is not None and sky is not None and sky.grounded(area, day):
        out["reach"] = kinds.FIGURE_LOW
        lines.append(_line("reach", -1, "weather", held.name if held else "weather"))
    return Standing(out, lines)


def piece_view(state: State, seen: State, view: View, piece: Feature) -> PieceKindView | None:
    """The seat's own ``piece`` with its kind and figures (KVW): with ``kinds_in_battle``
    on, for a piece of a kind the world names; else None. Supply and fuel are its own
    side's, read from the truth as the desk reads them."""
    kind = kinds.of(state, piece)
    today = view.in_world_date
    if not battle.kinds_count(state) or kind is None or today is None or state.map is None:
        return None
    area = territory.area_of(state, piece.places[0], kind.domain)
    status = supply.status(state, piece)
    nation = territory.nation(state, piece.side)
    cost = trade.cost(state, piece)
    fuelled = not cost or nation is None or economy.stock(state, nation) >= cost
    figures = kind_figures(kind)
    if area is None:
        stood = Standing(kind_figures(kind), [])
    else:
        stood = standing(
            seen,
            view,
            piece,
            kind,
            area,
            today,
            supplied=status is None or status.supplied,
            fuelled=fuelled,
        )
    return PieceKindView(
        key=kind.key,
        name=kind.name,
        picture=kind.picture.value if kind.picture is not None else None,
        figures=figures,
        here=stood.figures,
        changes=stood.changes,
    )


def _names(kind: kinds.PieceKind, named: Sequence[str]) -> bool:
    """Every kind when ``named`` is empty, else a kind or domain it names."""
    return not named or kind.key in named or kind.domain.value in named


def _does(w: WeatherKind, kind: kinds.PieceKind) -> list[WeatherEffect]:
    """What weather ``w`` does to ``kind``, in the order the world file gives it."""
    out: list[WeatherEffect] = []
    for slow in w.slows:
        if _names(kind, slow.pieces):
            out.append(
                WeatherEffect(
                    kind=kind.key, figure="speed", direction="down", terrain=[*slow.terrain]
                )
            )
    for s in w.figures:
        if not _names(kind, s.pieces):
            continue
        for which in ("attack", "defence"):
            by = getattr(s, which)
            if by:
                out.append(
                    WeatherEffect(
                        kind=kind.key,
                        figure=which,
                        direction="up" if by > 0 else "down",
                        terrain=[],
                    )
                )
    if w.grounds_air and battle._reach(kind) is not None:
        out.append(WeatherEffect(kind=kind.key, figure="reach", direction="down", terrain=[]))
    for c in w.closes:
        if kind.key in c.pieces or kind.domain.value in c.pieces:
            out.append(
                WeatherEffect(
                    kind=kind.key, figure="speed", direction="closed", terrain=[*c.terrain]
                )
            )
    return out


def weather_block(
    state: State, today: date | None, own: Sequence[kinds.PieceKind]
) -> WeatherBlock | None:
    """Every region's weather this month and next, and what each weather that holds does
    to each of ``own`` (the seat's own kinds); None when the weather does not act."""
    sky = weather.sky(state)
    board = state.map
    if sky is None or board is None or board.weather is None or today is None:
        return None
    month = today.replace(day=1)
    after = (month + timedelta(days=32)).replace(day=1)
    rows: list[RegionWeather] = []
    held: list[str] = []
    for region in board.regions:
        now, then = _row(board, region.key, month), _row(board, region.key, after)
        rows.append(RegionWeather(region=region.key, now=now, next=then))
        held += [k for k in (now, then) if k is not None and k not in held]
    table = board.weather.kinds
    return WeatherBlock(
        month=weather.MONTHS[month.month - 1],
        next_month=weather.MONTHS[after.month - 1],
        regions=rows,
        kinds=[
            WeatherKindView(
                key=key,
                name=table[key].name,
                does=[e for k in own for e in _does(table[key], k)],
            )
            for key in sorted(held, key=list(table).index)
        ],
    )


def _row(board: territory.WorldMap, region: str, month: date) -> str | None:
    """The key of the weather in ``region`` in ``month``: its row, else the row of the
    nearest region it lies in."""
    assert board.weather is not None
    parent = {r.key: r.parent for r in board.regions}
    seen: set[str] = set()
    at: str | None = region
    while at is not None and at not in seen:
        row = board.weather.regions.get(at)
        if row is not None:
            return row[month.month - 1]
        seen.add(at)
        at = parent.get(at)
    return None


LOOKBACK_DAYS = 60
"""How far before a step's due day ``step_began`` looks for the day it began: past the
slowest step any world's kinds and weather make. [proposed]"""


def _concealment_flipped(piece: Feature) -> Feature:
    """``piece`` as it would step with its concealment the other way (IOR)."""
    if detect.concealed(piece):
        return piece.model_copy(update={"concealed": False, "concealed_leg": False})
    return piece.model_copy(update={"concealed": True})


def step_began(
    state: State,
    piece: Feature,
    to: EntityId,
    due: date,
    latest: date | None = None,
    hint: date | None = None,
) -> tuple[date, int] | None:
    """The day a step of ``piece`` into ``to`` falling due on ``due`` began, and the days it
    takes by the step rule (``territory.step_days``). The day is not stored: it is the
    latest day, no later than ``latest`` (and before ``due``), whose step counted with that
    day's weather falls due on ``due``; ``hint`` first, when its step does. The piece's
    concealment may have changed since the step began, so each day is counted with it
    either way. None when no day in the ``LOOKBACK_DAYS`` before ``due`` gives ``due``."""
    either = (piece, _concealment_flipped(piece))

    def takes(on: date) -> int | None:
        for p in either:
            days = territory.step_days(state, p, to, on)
            if days is not None and on + timedelta(days=days) == due:
                return days
        return None

    if hint is not None and hint < due and (days := takes(hint)) is not None:
        return hint, days
    on = due - timedelta(days=1)
    if latest is not None:
        on = min(on, latest)
    while on >= due - timedelta(days=LOOKBACK_DAYS):
        days = takes(on)
        if days is not None:
            return on, days
        on -= timedelta(days=1)
    return None


def map_reply(state: State, shapes: bool = True) -> MapReply:
    """The ``map`` action's answer: the same for every seat. Without ``shapes`` the reply
    carries the file and its hash and no map object."""
    board = state.map
    if board is None or not territory.on(state):
        return MapReply(reply=NO_MAP, refused=True, file=None, map=None)
    data = maps.map_object(board.sha256, board.file)
    if data is None:
        return MapReply(reply=MISSING, refused=True, file=None, map=None)
    kept: dict[str, object] | None = json.loads(data) if shapes else None
    return MapReply(
        reply="", refused=False, file=MapFile(name=board.file, sha256=board.sha256), map=kept
    )


class MapRef(NamedTuple):
    """The map a stored campaign names: the file name and hash its ``map_declared`` holds."""

    campaign: CampaignId
    file: str
    sha256: str


def references(
    store: EventStore, campaign_ids: Sequence[CampaignId]
) -> tuple[list[MapRef], list[str]]:
    """Every map the campaigns name, and a ``FAIL`` line for each campaign that cannot be
    read; a campaign without a map names none."""
    out: list[MapRef] = []
    unread: list[str] = []
    for campaign in campaign_ids:
        try:
            board = load_state(store, campaign).map
        except ValueError:
            unread.append(f"FAIL {campaign}: cannot be read")
            continue
        if board is not None:
            out.append(MapRef(campaign, board.file, board.sha256))
    return out, unread


def _kept(directory: Path, sha256: str) -> bytes | None:
    """The bytes of ``<sha256>.json`` in ``directory`` when they hash to ``sha256``."""
    path = directory / f"{sha256}.json"
    data = path.read_bytes() if path.is_file() else None
    return data if data is not None and hashlib.sha256(data).hexdigest() == sha256 else None


def verify_objects(store: EventStore, campaign_ids: Sequence[CampaignId]) -> tuple[list[str], bool]:
    """One line per campaign that names a map: ``ok``, or ``FAIL`` when its object is not
    in the map-objects directory. Only that directory counts, never a world-named file."""
    here = maps.objects_dir()
    refs, lines = references(store, campaign_ids)
    ok = not lines
    for ref in refs:
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
    refs, lines = references(store, campaign_ids)
    ok = not lines
    done: set[str] = set()
    for ref in refs:
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
    its hash; needs no database. A file whose bytes do not hash to its name fails, and so
    does a directory with no object to copy."""
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
    if not lines:
        return [f"FAIL no map object in {here}"], False
    return lines, ok


__all__ = [
    "CAUSE_WORDS",
    "HIDDEN_STEP",
    "LOOKBACK_DAYS",
    "MARK_SECRET_ENV",
    "MISSING",
    "NO_MAP",
    "SPEED_TOP",
    "MapRef",
    "Reaches",
    "Reported",
    "Standing",
    "add_board",
    "area_domain",
    "copy_all_objects",
    "copy_objects",
    "kind_figures",
    "lit",
    "map_reply",
    "mark_key",
    "mark_secret",
    "piece_view",
    "plain_kind",
    "protect_marks",
    "references",
    "report_keys",
    "reported",
    "seat_board",
    "standing",
    "step_began",
    "step_key",
    "verify_objects",
    "viewing_nation",
    "weather_block",
]
