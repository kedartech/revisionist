"""The shipping resolver (plan, Phase 2 unit B3).

Atlantic losses from U-boat strength and escort level. Churchill's
``convoy_orders`` and Mussolini's ``libya_convoys`` change nothing in this wave.
Once the escort level has reached 1 the escort factor counts from that month, even
if a later order holds the ships in port.

Where the fleets are counts, read as the month ends (before that day's arrivals): the
escort factor applies only while a fleet of the escorting side lies in the North
Atlantic, and the U-boats sink nothing while no fleet of their side lies there. A
side with no fleet on the map is taken to be on station.

The month's losses also take a share from Britain's troop-lift pool (sealift, R6), so an
escort order that cuts the losses keeps British lift free. A sourced month takes nothing,
and the pool never falls below 0. That is a stored game's rule, and a world's without the
territory rules.

In a territory game (``territories`` on) the forms read the board, never a key of one
world (SHP). A form's parameters are read by what each value names in the world: a
route, a piece, waters (a sea zone, a region of them, or a place at sea), a nation, or an
escort value (``ESCORT_LEVEL``). A form naming a route and pieces is a supply convoy; a
route alone, a convoy priority; waters and an escort value, an escort order; waters or a
nation otherwise, a raid directive; nothing of these, a requisition. The sea zones a route
crosses are those its places lie in or open on, and the pool a nation's shipping is drawn
from is the one the world names for it (``lift_pool``).

- A convoy priority raises the escort level on the route it names by ``ESCORT_RAISE``
  while it is its nation's latest.
- A requisition adds ``REQUISITION_GRT`` to the issuer's nation's lift pool. A form whose
  every parameter is free text is a message instead: the person abroad who let it through
  thinks better of the issuer by ``MESSAGE_REGARD``.
- A supply convoy keeps the pieces it names supplied for ``CONVOY_DAYS`` (``supplied``),
  unless it is cut: while an enemy holds a territory its route names, it is cut with a
  chance of ``CONVOY_CUT_PCT`` in 100.
- An escort order sets its level on every route crossing its waters, while it is its
  nation's latest.
- Sea pieces sink shipping on the routes crossing the zone they stand in: those of a
  nation at war with theirs, or of one their nation's latest raid directive names; in
  the directive's waters they press harder. Escorts, and a law arming a nation's merchant
  ships from the month after it passes, cut what a route loses. An escort's cut grows
  month by month from the month the route first had one, to its full cut in its
  ``ESCORT_RAMP_MONTHS``th month. On the 1st, each nation's pool loses ``LOSS_SHARE_PCT``
  of what its routes lost in the month just ended.
"""

from collections.abc import Callable
from datetime import date, timedelta
from typing import NamedTuple

from revisionist.core.ids import EntityId, FeatureId, QuantityId, RelationshipId, derived_id
from revisionist.core.ontology import EntityKind, Relationship
from revisionist.core.realism import kinds, supply, territory
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.card import ParamKind
from revisionist.core.realism.geography import Feature, FeatureKind
from revisionist.core.realism.kinds import Domain
from revisionist.core.realism.pipeline import Order, OrderStatus, StepKind
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import votes
from revisionist.core.realism.resolvers.votes import put
from revisionist.core.realism.war import at_war, polity_of
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.core.world_compile import object_id

ESCORT_LEVEL = {"hold_in_port": 0, "escort_convoys": 1, "shoot_on_sight": 2}
ESCORT_ZONES = ("western_atlantic", "iceland_route")
POSTURE = {"restrict_us_ships": 0, "unrestricted_atlantic": 1}
PER_BOAT_GRT = 209_835 / 30  # [fitted] to Sep 1941 (209,835 GRT, 30 boats)
ESCORT_STEP_PM = 150  # [fitted] to the Oct (176,622) and Nov (120,541) record
ESCORT_FLOOR_PM = 500  # [proposed]
UNRESTRICTED_PM = 1300  # [proposed]
NOISE_PM = 80  # [proposed] friction keeps losses within +-8%
NORTH_ATLANTIC = ((0.0, 70.0), (-82.0, 0.0))  # [proposed] latitude, longitude bounds
LOSS_SHARE_PCT = 10  # [proposed] sealift plan, section 3
LOSS_POOLS = ("uk_sealift_grt",)
"""The troop-lift pools that bear a share of the month's losses: Britain's."""
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def resolve(state: State, order: Order) -> tuple[QuantityChange | Relationship, ...]:
    """Changes from one order enacted through its pipeline. In a territory game only a
    requisition changes a figure and a message a regard when it is enacted; the other forms
    act as they are read (``escort_level``, ``losses``, ``supplied``)."""
    if order.status is not OrderStatus.ENACTED:
        return ()
    if on(state):
        return _message(state, order) or _requisition(state, order)
    as_of = rs.settled_on(order)
    if order.lever == "naval_order" and order.params.get("zone") in ESCORT_ZONES:
        level = ESCORT_LEVEL.get(str(order.params.get("order")))
        change = None if level is None else put(state, "us_atlantic_escort", level, as_of)
    elif order.lever == "uboat_directive" and order.params.get("posture") in POSTURE:
        change = put(state, "uboat_posture", POSTURE[str(order.params["posture"])], as_of)
    else:
        return ()
    return () if change is None else (change,)


def _escorted_since(state: State, today: date) -> date | None:
    """The day the first enacted escort order (level 1 or more) settled."""
    days = [
        rs.settled_on(o)
        for o in state.orders.values()
        if o.status is OrderStatus.ENACTED
        and o.lever == "naval_order"
        and o.params.get("zone") in ESCORT_ZONES
        and ESCORT_LEVEL.get(str(o.params.get("order")), 0) >= 1
        and rs.settled_on(o) <= today
    ]
    return min(days, default=None)


def _in_north_atlantic(state: State, place: EntityId) -> bool:
    here = state.entities.get(place)
    if here is None or here.at is None:
        return False
    (south, north), (west, east) = NORTH_ATLANTIC
    return south <= here.at[0] <= north and west <= here.at[1] <= east


def _on_station(state: State, key: str) -> bool:
    """Whether a fleet of the side that owns quantity ``key`` lies in the North
    Atlantic; true when that side has no fleet on the map."""
    q = state.quantities.get(rs.qid(state, key))
    side = None if q is None or q.owner is None else polity_of(state, q.owner)
    if side is None:
        return True
    fleets = [
        f
        for f in state.features.values()
        if f.kind is FeatureKind.FLEET and f.side is not None and polity_of(state, f.side) == side
    ]
    return not fleets or any(_in_north_atlantic(state, f.places[0]) for f in fleets)


def moved(state: State, key: str, delta: int, on: date) -> QuantityChange | None:
    """The pool ``key`` moved by ``delta`` on ``on``, never below 0 and dated no earlier
    than its own date; None when the world holds no figure for it or nothing changes."""
    return shifted(state, rs.qid(state, key), delta, on)


def shifted(state: State, pool: QuantityId, delta: int, on: date) -> QuantityChange | None:
    """``moved``, for a pool known by its id."""
    q = state.quantities.get(pool)
    if q is None or q.value is None or max(0, q.value + delta) == q.value:
        return None
    return QuantityChange(
        quantity_id=q.quantity_id, value=max(0, q.value + delta), as_of=max(on, q.as_of)
    )


def on_day(state: State, today: date) -> tuple[QuantityChange, ...]:
    """On the 1st, the month just ended's losses, if that quantity is still a gap, and
    each lift pool's share of them. In a territory game, each lift pool's share of what
    its nation's routes lost (``losses``)."""
    if today.day != 1:
        return ()
    last = today - timedelta(days=1)
    if on(state):
        return _sink(state, last)
    key = f"uboat_losses_{MONTHS[last.month - 1]}"
    if rs.qid(state, key) not in state.quantities or rs.value(state, key) is not None:
        return ()
    boats = rs.value(state, "uboats_operational")
    if boats is None:
        return ()
    if not _on_station(state, "uboats_operational"):
        boats = 0
    since = _escorted_since(state, last) if _on_station(state, "us_atlantic_escort") else None
    months = 0 if since is None else (last.year - since.year) * 12 + last.month - since.month
    escort_pm = max(ESCORT_FLOOR_PM, 1000 - ESCORT_STEP_PM * months)
    posture_pm = UNRESTRICTED_PM if rs.value(state, "uboat_posture") == 1 else 1000
    noise_pm = 1000 - NOISE_PM + rs.friction(state, key, n=2 * NOISE_PM + 1)
    losses = round(PER_BOAT_GRT * boats * escort_pm * posture_pm * noise_pm / 10**9)
    shares = (moved(state, k, -(losses * LOSS_SHARE_PCT // 100), last) for k in LOSS_POOLS)
    return tuple(c for c in (put(state, key, losses, last), *shares) if c is not None)


# ------------------------------------------------------------------ the territory game (SHP)

ESCORT_RAISE = 1  # [proposed] plan, SHP Defaults: escort plus one level
ESCORT_LEVEL_PM = ESCORT_STEP_PM
"""Per mille off a route's losses for each escort level on it."""
ESCORT_RAMP_MONTHS = 3  # [proposed] sinkings fall from Oct (176,622) to Nov (120,541) on the record
"""Months a route's escort takes to reach its full cut, counting the month it first sailed."""
RAID_GRT_PER_TIER = 70_000  # [proposed] about Sep 1941's sinkings for a U-boat arm of strength 3
MESSAGE_REGARD = 1  # [proposed]
"""How far a message moves the regard of the person abroad who let it through."""
REQUISITION_GRT = 50_000  # [proposed]
"""Tonnage one enacted requisition takes into the state's service, into its lift pool."""
CONVOY_DAYS = 30  # [proposed]
"""Days a supply convoy keeps the pieces it names supplied, from the day it settles."""
CONVOY_CUT_PCT = 50  # [proposed]
"""Chance in 100 that a convoy is cut while an enemy holds a territory on its route."""
ARMING_CUT_PCT = 10  # [proposed] plan, SHP Defaults: merchant arming minus 10 percent


class Form(NamedTuple):
    """What a shipping form names, read from its parameters' values against the world."""

    routes: tuple[Feature, ...]
    pieces: tuple[Feature, ...]
    waters: frozenset[EntityId]
    nations: tuple[EntityId, ...]
    escort: int | None
    """The level an escort value sets (``ESCORT_LEVEL``); None when it names none."""


def on(state: State) -> bool:
    """Whether the shipping forms read the board: a territory game."""
    return territory.on(state)


def _feature(state: State, key: str) -> Feature | None:
    return state.features.get(FeatureId(object_id(state.campaign_id, "feature", key)))


def _waters(state: State, key: str) -> frozenset[EntityId]:
    """The sea zones ``key`` names: a sea zone, a region (and those below it), or a place
    in or opening on a zone."""
    board = state.map
    assert board is not None
    zone = next((z.area for z in board.sea_zones if z.key == key), None)
    if zone is not None:
        return frozenset({zone})
    keys = {r.key for r in board.regions}
    if key in keys:
        below, grown = {key}, True
        while grown:
            more = {r.key for r in board.regions if r.parent in below} - below
            below |= more
            grown = bool(more)
        return frozenset(z.area for z in board.sea_zones if z.region in below)
    place = EntityId(object_id(state.campaign_id, "entity", key))
    area = territory.area_of(state, place, Domain.SEA) if place in state.entities else None
    return frozenset({area}) if area in {z.area for z in board.sea_zones} else frozenset()


def form(state: State, order: Order) -> Form:
    """What ``order`` names, by the type of each parameter's value."""
    routes: list[Feature] = []
    pieces: list[Feature] = []
    waters: set[EntityId] = set()
    nations: list[EntityId] = []
    escort = None
    for _, raw in sorted(order.params.items()):
        if not isinstance(raw, str):
            continue
        found = _feature(state, raw)
        if found is not None and found.kind is FeatureKind.ROUTE:
            routes.append(found)
        elif found is not None and kinds.of(state, found) is not None:
            pieces.append(found)
        elif raw in ESCORT_LEVEL:
            escort = ESCORT_LEVEL[raw]
        else:
            nation = state.entities.get(EntityId(object_id(state.campaign_id, "entity", raw)))
            if nation is not None and nation.kind is EntityKind.POLITY:
                nations.append(nation.entity_id)
            else:
                waters |= _waters(state, raw)
    return Form(tuple(routes), tuple(pieces), frozenset(waters), tuple(nations), escort)


def _nation(state: State, order: Order) -> EntityId | None:
    return polity_of(state, state.seats[order.issuer].embodies)


def zones(state: State, route: Feature) -> tuple[EntityId, ...]:
    """The sea zones a route crosses, in its order: the zone each of its places lies in or
    opens on, once each."""
    board = state.map
    assert board is not None
    seas = {z.area for z in board.sea_zones}
    out: list[EntityId] = []
    for place in route.places:
        area = territory.area_of(state, place, Domain.SEA)
        if area in seas and area not in out:
            out.append(area)
    return tuple(out)


def _territories(state: State, route: Feature) -> tuple[EntityId, ...]:
    """The territories a route names: those its places lie within."""
    board = state.map
    assert board is not None
    lands = {t.area for t in board.territories}
    found = (territory.area_of(state, p, Domain.LAND) for p in route.places)
    return tuple(a for a in found if a is not None and a in lands)


def _enacted(state: State, day: date) -> list[tuple[Order, Form]]:
    """The shipping forms enacted by ``day``, latest last, with what each names."""
    out = []
    for o in state.orders.values():
        if o.status is not OrderStatus.ENACTED or o.measure is not None or rs.settled_on(o) > day:
            continue
        try:
            if rs.resolver_for(state, o) != "shipping":
                continue
        except KeyError:
            continue
        out.append(o)
    out.sort(key=lambda o: (rs.settled_on(o), o.filed, o.order_id))
    return [(o, form(state, o)) for o in out]


def _latest(
    found: list[tuple[Order, Form]], test: Callable[[Form], bool], state: State
) -> dict[EntityId, Form]:
    """Each nation's latest form that passes ``test``."""
    out: dict[EntityId, Form] = {}
    for o, f in found:
        nation = _nation(state, o)
        if nation is not None and test(f):
            out[nation] = f
    return out


def _priority(f: Form) -> bool:
    return bool(f.routes) and not f.pieces


def _escorts(f: Form) -> bool:
    return f.escort is not None and bool(f.waters) and not f.routes


def _raid(f: Form) -> bool:
    return f.escort is None and not f.routes and not f.pieces and bool(f.waters or f.nations)


def escort_level(state: State, route: Feature, day: date) -> int:
    """The escort level on ``route`` on ``day``: the highest a nation's latest escort order
    sets in waters the route crosses, raised ``ESCORT_RAISE`` while the latest convoy
    priority of the route's own nation names it."""
    found = _enacted(state, day)
    crossed = set(zones(state, route))
    base = max(
        (f.escort or 0 for f in _latest(found, _escorts, state).values() if f.waters & crossed),
        default=0,
    )
    own = territory.nation(state, route.side)
    first = _latest(found, _priority, state).get(own) if own is not None else None
    raised = first is not None and route.feature_id in {r.feature_id for r in first.routes}
    return base + (ESCORT_RAISE if raised else 0)


def _escort_pm(state: State, route: Feature, last: date) -> int:
    """Per mille of its losses ``route`` keeps under escort in the month that ends ``last``.
    An escort's cut grows by a share each month from the month the route first had an
    escort level of 1 or more, and is full from its ``ESCORT_RAMP_MONTHS``th month."""
    level = escort_level(state, route, last)
    since = next(
        (
            rs.settled_on(o)
            for o, _ in _enacted(state, last)
            if escort_level(state, route, rs.settled_on(o)) >= 1
        ),
        None,
    )
    if not level or since is None:
        return 1000
    months = (last.year - since.year) * 12 + last.month - since.month + 1
    ramp = min(months, ESCORT_RAMP_MONTHS)
    return max(ESCORT_FLOOR_PM, 1000 - ESCORT_LEVEL_PM * level * ramp // ESCORT_RAMP_MONTHS)


def cut(state: State, order: Order, day: date) -> bool:
    """Whether a supply convoy is cut on ``day``: an enemy of its nation holds a territory
    its route names, and the convoy's draw falls under ``CONVOY_CUT_PCT``."""
    nation = _nation(state, order)
    f = form(state, order)
    if nation is None or not f.routes:
        return False
    held = {territory.holder(state, a) for r in f.routes for a in _territories(state, r)}
    if not any(h is not None and at_war(state, nation, h) for h in held):
        return False
    return rs.friction(state, order.order_id, "convoy", n=100) < CONVOY_CUT_PCT


def convoyed(state: State, piece: Feature, day: date) -> bool:
    """Whether the latest supply convoy naming ``piece``, settled within ``CONVOY_DAYS``
    before ``day``, got through."""
    if not on(state):
        return False
    latest = None
    for o, f in _enacted(state, day):
        if f.routes and piece.feature_id in {p.feature_id for p in f.pieces}:
            latest = o
    if latest is None or (day - rs.settled_on(latest)).days >= CONVOY_DAYS:
        return False
    return not cut(state, latest, day)


def supplied(state: State, piece: Feature, day: date | None) -> bool | None:
    """The piece's supply on ``day``: by land and port (``supply.status``) or by a supply
    convoy that got through. None when supply is off."""
    found = supply.status(state, piece)
    if found is None:
        return None
    return found.supplied or (day is not None and convoyed(state, piece, day))


def _pool(state: State, nation: EntityId | None) -> QuantityId | None:
    """The lift pool the board names for ``nation``, if the game holds a figure for it."""
    board = state.map
    pool = None if board is None or nation is None else board.lift_pools.get(nation)
    if pool is None or pool not in state.quantities:
        return None
    return pool


def _armed(state: State, nation: EntityId, last: date) -> bool:
    """Whether a law arming ``nation``'s merchant ships passed before ``last``'s month."""
    since = votes.in_force(state, votes.ARMING).get(nation)
    return since is not None and (since.year, since.month) < (last.year, last.month)


def losses(state: State, last: date) -> dict[FeatureId, int]:
    """The tonnage sunk on each route in the month that ends ``last``. Each sea piece
    standing in a zone a route crosses sinks ``RAID_GRT_PER_TIER`` a strength point, split
    evenly over the routes it can attack there: those of a nation it is at war with, or
    one its nation's latest raid directive names. Raiders in the waters that directive
    names press harder (``UNRESTRICTED_PM``). A route's escort level and its nation's armed
    merchant ships cut what it loses."""
    if not on(state) or state.map is None:
        return {}
    found = _enacted(state, last)
    raids = _latest(found, _raid, state)
    routes = sorted(
        (f for f in state.features.values() if f.kind is FeatureKind.ROUTE and f.side is not None),
        key=lambda f: f.feature_id,
    )
    crossing = {r.feature_id: set(zones(state, r)) for r in routes}
    raw: dict[FeatureId, float] = {}
    for raider in sorted(state.features.values(), key=lambda f: f.feature_id):
        kind = kinds.of(state, raider)
        if kind is None or kind.domain is not Domain.SEA or raider.rejoined_on is not None:
            continue
        side = territory.nation(state, raider.side)
        zone = territory.area_of(state, raider.places[0], Domain.SEA)
        if side is None or zone is None or raider.tier == 0:
            continue
        raid = raids.get(side)
        named = set(raid.nations) if raid is not None else set()
        targets = [
            r
            for r in routes
            if zone in crossing[r.feature_id]
            and (own := territory.nation(state, r.side)) is not None
            and own != side
            and (at_war(state, side, own) or own in named)
        ]
        if not targets:
            continue
        pressed = raid is not None and zone in raid.waters
        grt = RAID_GRT_PER_TIER * raider.tier * (UNRESTRICTED_PM if pressed else 1000) / 1000
        for r in targets:
            raw[r.feature_id] = raw.get(r.feature_id, 0.0) + grt / len(targets)
    out: dict[FeatureId, int] = {}
    for r in routes:
        if r.feature_id not in raw:
            continue
        own = territory.nation(state, r.side)
        escort_pm = _escort_pm(state, r, last)
        arm_pm = (
            1000 - 10 * ARMING_CUT_PCT if own is not None and _armed(state, own, last) else 1000
        )
        month = f"{last.year}-{last.month}"
        noise_pm = 1000 - NOISE_PM + rs.friction(state, r.feature_id, month, n=2 * NOISE_PM + 1)
        out[r.feature_id] = round(raw[r.feature_id] * escort_pm * arm_pm * noise_pm / 10**9)
    return out


def _sink(state: State, last: date) -> tuple[QuantityChange, ...]:
    """On the 1st, each nation's lift pool loses ``LOSS_SHARE_PCT`` of what its routes lost."""
    by_pool: dict[QuantityId, int] = {}
    for fid, lost in losses(state, last).items():
        pool = _pool(state, territory.nation(state, state.features[fid].side))
        if pool is not None:
            by_pool[pool] = by_pool.get(pool, 0) + lost
    found = (
        shifted(state, p, -(n * LOSS_SHARE_PCT // 100), last) for p, n in sorted(by_pool.items())
    )
    return tuple(c for c in found if c is not None)


def _requisition(state: State, order: Order) -> tuple[QuantityChange, ...]:
    """A form that names no route, piece, waters, nation or escort takes merchant tonnage
    into the state's service: ``REQUISITION_GRT`` into the pool the world names for the
    issuer's nation."""
    f = form(state, order)
    if f.routes or f.pieces or f.waters or f.nations or f.escort is not None:
        return ()
    pool = _pool(state, _nation(state, order))
    change = None if pool is None else shifted(state, pool, REQUISITION_GRT, rs.settled_on(order))
    return () if change is None else (change,)


def _message(state: State, order: Order) -> tuple[Relationship, ...]:
    """A form whose every parameter is free text is a message, not a requisition: once
    enacted, the first person of another nation who decides a step of its pipeline thinks
    better of the issuer by ``MESSAGE_REGARD``. Nothing for any other form, or a message
    no one abroad decides."""
    issuer = state.seats[order.issuer].embodies
    card = state.cards.get(issuer)
    lever = next((lv for lv in card.levers if lv.name == order.lever), None) if card else None
    if lever is None or not lever.params or any(p.kind is not ParamKind.TEXT for p in lever.params):
        return ()
    nation = polity_of(state, issuer)
    pipeline = state.pipelines.get(order.pipeline)
    decider = next(
        (
            step.person
            for step in (pipeline.steps if pipeline is not None else ())
            if step.kind is StepKind.DECISION
            and polity_of(state, step.person) not in (None, nation)
        ),
        None,
    )
    if decider is None:
        return ()
    now = next((r for r in state.relationships.values() if (r.a, r.b) == (decider, issuer)), None)
    if now is None:
        return (
            Relationship(
                relationship_id=RelationshipId(
                    derived_id(state.campaign_id, "rel", decider, issuer)
                ),
                a=decider,
                b=issuer,
                disposition=max(-5, min(5, MESSAGE_REGARD)),
                scope=private_to(order.issuer),
            ),
        )
    moved = max(-5, min(5, now.disposition + MESSAGE_REGARD))
    return () if moved == now.disposition else (now.model_copy(update={"disposition": moved}),)
