"""The movement resolver (realism, Batch 6; the fifth, by Josh's word).

An enacted order whose lever names it sends one force to one place: the lever's
``force`` parameter names a feature key and ``to`` a place key. The force sets
out the day the order settles and arrives after its route at its kind's pace (a
fleet sails by sea, through the passages open to its side; armies and air groups
go straight); it stays where it was until then. A fleet with no open sea route
does not sail, and no force goes beyond its side's reach (``bases.reach``). Only the
issuer's own side moves:
an order naming another side's force changes nothing. An order drops the moves
history still had for that force. Fronts and routes move only with history.

A fleet or air group keeps a clock from the day it leaves its side's bases
(``Feature.left_base_on``) through every move between places that are not bases, and
the clock stops when it reaches one. A force with no clock starts one on its next
move: the day it sets out, or on arrival, the day it set out if it left a base and
else the day it arrives. One that has been out longer than its kind's raid limit
(``bases.RAID_DAYS``) while at a raid place turns for the base nearest it, unless it is
already bound for a base. Armies keep no clock.

An order that also names a ``strength`` splits the force instead (``detachments``): that
much of it sets out as a detachment on the course a move would take, and the rest stays.
Each day, after arrivals, a detachment standing still where its force stands still
merges back. A detachment that has merged is out of play: no order or day moves it.

An army sent across the sea goes by sealift (``sealift``, ``bases.lift``): it arrives
after the march to its port and the voyage, and the order draws the lift from its side's
pool the day it sets out. A pool too small for the lift moves nothing and draws nothing.
The lift is given back the day the army lands (``day_changes``), or the day a later order
changes its course, which draws again if that course also crosses the sea. Each change to
a pool is dated no earlier than the pool's own date, and several on one day add up.

With ``territories`` on (ADJ), a piece moves by adjacency instead (``territory``): the order
names an area or a place, the piece takes the course of fewest days for its domain
(``territory.plan``), and ``walk`` completes each step on the day it falls due, one
``piece_stepped`` event a step, so the piece stands in each area it passes through. An
order to a piece under way re-plans from the area it is in. A step into an area held by a
polity neither its own, an ally, nor at war with it is refused and the piece stops; a step
into an area where an enemy piece at war stands ends the move there. Both read where the
pieces stood when the day began, so the order the pieces are walked in changes nothing. A
land piece's lift is drawn from its nation's pool when the order sets it on a course across
the sea, and given back the day it lands. The rule above stays as it was for every game
without ``territories``.

A leg of the record names a place, or with ``territories`` on an area, and its piece goes
there by adjacency as an order would send it, its steps marked scripted. With ``holders`` on,
the territories a leg ``takes`` pass to the piece's nation on the leg's date, read from where
everything stood as the day began (HSA).

With ``fuel`` on as well (FUL, ``trade``), ``walk`` spends a piece's ``fuel_per_step`` from
its nation's stock as each step falls due in the day walk, never when the order is filed;
with too little stock the step is refused (``step_refused``, with the reason) and the
piece holds where it stands. The day's spending lands as the nation's ``economy_set``.
"""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId, QuantityId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism import battle, detect, economy, holders, kinds, territory, trade
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.bases import (
    RAID_DAYS,
    Force,
    Tier,
    crossing,
    lift,
    nearest_base,
    pool_key,
    reach,
    world_of,
)
from revisionist.core.realism.detachments import rejoin, split
from revisionist.core.realism.geography import FORCES, Feature, FeatureKind, in_play
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.routing import travel_days
from revisionist.core.realism.sealift import lift_needed
from revisionist.core.realism.war import at_war
from revisionist.core.state import State
from revisionist.core.world_compile import object_id

FORCE, TO, STRENGTH = "force", "to", "strength"
DEPTH = 8
"""How far up a person's parents their side may lie (person, body, polity)."""


def _of_side(state: State, person: EntityId, side: EntityId) -> bool:
    at: EntityId | None = person
    for _ in range(DEPTH):
        if at is None:
            return False
        if at == side:
            return True
        at = state.entities[at].parent if at in state.entities else None
    return False


def _timed(state: State, f: Feature) -> bool:
    """Whether ``f`` keeps a clock: a kind with a raid limit, in a world with bases."""
    return f.kind in RAID_DAYS and world_of(state) is not None


def _is_base(state: State, f: Feature, place: EntityId) -> bool:
    found = reach(state, Force(f.kind, f.side, place), place)
    return found is not None and found.tier is Tier.SUSTAINED


def _clock(state: State, f: Feature, to: EntityId, set_out: date, today: date) -> dict[str, object]:
    """The clock once ``f``, which set out on ``set_out``, stands at ``to`` today."""
    if not _timed(state, f):
        return {}
    if _is_base(state, f, to):
        return {"left_base_on": None}
    if f.left_base_on is not None:
        return {}
    return {"left_base_on": set_out if _is_base(state, f, f.places[0]) else today}


def _turned(state: State, f: Feature, today: date) -> Feature | None:
    """``f`` turned for its nearest base, when it has raided longer than its kind may."""
    limit = RAID_DAYS.get(f.kind)
    if limit is None or f.left_base_on is None or (today - f.left_base_on).days <= limit:
        return None
    found = reach(state, f, f.places[0])
    if found is None or found.tier is not Tier.RAID:
        return None
    if f.bound_for is not None and _is_base(state, f, f.bound_for):
        return None
    base = nearest_base(state, f)
    days = None if base is None else travel_days(state, f, base)
    if base is None or days is None:
        return None
    as_of = max(today, f.as_of)
    return f.model_copy(
        update={
            "bound_for": base,
            "arrives": as_of + timedelta(days=days),
            "legs": (),
            "as_of": as_of,
        }
    )


def _at_sea(state: State, f: Feature) -> bool:
    """Whether ``f`` is an army under way on a lift, whose tonnage is out of its pool."""
    return f.bound_for is not None and crossing(state, f.kind, f.places[0], f.bound_for)


def _pool_change(state: State, key: str, delta: int, on: date) -> QuantityChange | None:
    """The pool ``key`` moved by ``delta`` on ``on`` (no earlier than its own date); None
    when it holds no figure or would fall below 0."""
    q = state.quantities.get(rs.qid(state, key))
    if q is None or q.value is None or q.value + delta < 0:
        return None
    return QuantityChange(quantity_id=q.quantity_id, value=q.value + delta, as_of=max(on, q.as_of))


def _sent(state: State, force: Feature, to: EntityId, as_of: date) -> Feature | None:
    """``force`` under way to ``to`` from ``as_of``, halted if it is already there, or
    None when the place is out of its reach or it has no route."""
    here = force.places[0]
    if to == here:
        return force.model_copy(
            update={
                "bound_for": None,
                "arrives": None,
                "legs": (),
                "as_of": as_of,
                **_clock(state, force, here, as_of, as_of),
            }
        )
    found = reach(state, force, to)
    if found is not None and found.tier is Tier.REFUSED:
        return None
    by_sea = lift(state, force, to)
    days = travel_days(state, force, to) if by_sea is None else by_sea.days
    if days is None:
        return None
    return force.model_copy(
        update={
            "bound_for": to,
            "arrives": as_of + timedelta(days=days),
            "legs": (),
            "as_of": as_of,
            **({"left_base_on": force.left_base_on or as_of} if _timed(state, force) else {}),
        }
    )


def resolve(state: State, order: Order) -> tuple[Feature, ...]:
    """The force under way, or halted if sent where it already is; for an order that
    names a strength, the force and the detachment it sends. Nothing for a lift its
    side's pool cannot carry (``order_changes`` adds the pool's change)."""
    return _resolved(state, order)[0]


def order_changes(state: State, order: Order) -> tuple[Feature | QuantityChange, ...]:
    """``resolve``'s moves, with the pool as a lift taken or given back leaves it."""
    moved, pool = _resolved(state, order)
    return moved if pool is None else (*moved, pool)


def _resolved(state: State, order: Order) -> tuple[tuple[Feature, ...], QuantityChange | None]:
    if order.status is not OrderStatus.ENACTED:
        return (), None
    cid = state.campaign_id
    key = str(order.params.get(FORCE))
    force = state.features.get(FeatureId(object_id(cid, "feature", key)))
    to = state.entities.get(EntityId(object_id(cid, "entity", str(order.params.get(TO)))))
    if force is not None and force.kind is FeatureKind.PIECE and territory.on(state):
        return _piece_order(state, order, force)
    if force is None or force.kind not in FORCES or force.side is None or not in_play(force):
        return (), None
    if to is None or to.kind is not EntityKind.LOCATION or to.at is None:
        return (), None
    if not _of_side(state, state.seats[order.issuer].embodies, force.side):
        return (), None
    set_out = max(rs.settled_on(order), force.as_of)
    sent = _sent(state, force, to.entity_id, set_out)
    if sent is None:
        return (), None
    if STRENGTH in order.params:
        return split(state, force, key, order.params[STRENGTH], sent), None
    return _shipped(state, force, sent, set_out)


def _shipped(
    state: State, force: Feature, sent: Feature, set_out: date
) -> tuple[tuple[Feature, ...], QuantityChange | None]:
    """``sent`` with its pool's change: the lift it is on given back, the lift it now
    takes drawn. Nothing when the pool cannot carry the new lift."""
    by_sea = lift(state, force, sent.bound_for) if sent.bound_for is not None else None
    back = lift_needed(force) if _at_sea(state, force) else 0
    if by_sea is None and not back:
        return (sent,), None
    assert force.side is not None  # resolve moves only a force with a side
    key = by_sea.pool if by_sea is not None else pool_key(state, force.side)
    if key is None:
        return (sent,), None
    change = _pool_change(state, key, back - (lift_needed(force) if by_sea else 0), set_out)
    if change is None:
        return ((), None) if by_sea is not None else ((sent,), None)
    return (sent,), change


# --- moving by adjacency (ADJ) -----------------------------------------------------


def _halted(piece: Feature, as_of: date) -> Feature:
    """The piece standing still where it is from ``as_of``."""
    return piece.model_copy(
        update={
            "path": (),
            "step_due": None,
            "bound_for": None,
            "arrives": None,
            "as_of": max(as_of, piece.as_of),
        }
    )


def _set_on(piece: Feature, course: territory.Plan, to: EntityId, set_out: date) -> Feature:
    """The piece under way to ``to`` from ``set_out`` along ``course``."""
    if not course.path:
        return _halted(piece, set_out).model_copy(update={"legs": ()})
    return piece.model_copy(
        update={
            "path": course.path,
            "step_due": set_out + timedelta(days=course.days[0]),
            "bound_for": to,
            "arrives": set_out + timedelta(days=course.total),
            "legs": (),
            "as_of": max(set_out, piece.as_of),
            "concealed_leg": False,
        }
    )


def _lift_change(state: State, was: Feature, now: Feature, on: date) -> QuantityChange | None:
    """The pool as a lift is drawn (``now`` crosses the sea, ``was`` did not) or given back
    (the other way round); None when nothing changes or there is no pool."""
    before, after = territory.lifted(state, was), territory.lifted(state, now)
    pool = territory.lift_pool(state, was)
    if before == after or pool is None:
        return None
    tons = territory.lift_tons(was)
    return _pool_by_id(state, pool, tons if before else -tons, on)


def _pool_by_id(state: State, pool: QuantityId, delta: int, on: date) -> QuantityChange | None:
    q = state.quantities.get(pool)
    if q is None or q.value is None or q.value + delta < 0:
        return None
    return QuantityChange(quantity_id=pool, value=q.value + delta, as_of=max(on, q.as_of))


def _piece_order(
    state: State, order: Order, piece: Feature
) -> tuple[tuple[Feature, ...], QuantityChange | None]:
    """An order to a piece with ``territories`` on: re-planned from the area it is in."""
    cid = state.campaign_id
    to = state.entities.get(EntityId(object_id(cid, "entity", str(order.params.get(TO)))))
    if piece.side is None or not in_play(piece) or STRENGTH in order.params:
        return (), None
    if to is None or to.kind is not EntityKind.LOCATION:
        return (), None
    if not _of_side(state, state.seats[order.issuer].embodies, piece.side):
        return (), None
    course = territory.plan(state, piece, to.entity_id)
    if not isinstance(course, territory.Plan):
        return (), None
    set_out = max(rs.settled_on(order), piece.as_of)
    dest = course.path[-1] if course.path else piece.places[0]
    sent = _set_on(piece, course, dest, set_out)
    if territory.lifted(state, sent) and not territory.lifted(state, piece):
        drawn = _lift_change(state, piece, sent, set_out)
        return ((sent,), drawn) if drawn is not None else ((), None)
    return (sent,), _lift_change(state, piece, sent, set_out)


Meeting = frozenset[tuple[EntityId, EntityId]]
"""The areas pieces enter today, each with the nation of the piece entering."""


def _enemy_in(state: State, piece: Feature, area: EntityId, meeting: Meeting) -> bool:
    """Whether a piece of a nation at war with this one's stands in ``area`` as the day
    begins, or enters it today too."""
    own = territory.nation(state, piece.side)
    if own is None:
        return False
    there = {n for a, n in meeting if a == area}
    for other in state.features.values():
        if other.feature_id == piece.feature_id or not in_play(other):
            continue
        theirs = territory.nation(state, other.side)
        if other.places[0] == area and kinds.is_force(state, other) and theirs is not None:
            there.add(theirs)
    return any(n != own and at_war(state, own, n) for n in there)


def _course_set(state: State, piece: Feature, today: date) -> tuple[Feature, bool]:
    """A piece another writer sent (``bound_for`` with no course, as an effect sends it)
    given its course; a leg of the record falling due turned into a course to its area.
    The flag says the move is the record's."""
    if piece.bound_for is not None and not piece.path:
        course = territory.plan(state, piece, piece.bound_for)
        if not isinstance(course, territory.Plan):
            return _halted(piece, today), False
        return _set_on(piece, course, piece.bound_for, min(piece.as_of, today)), False
    if piece.bound_for is None and piece.legs and piece.legs[0].since <= today:
        due = [leg for leg in piece.legs if leg.since <= today]
        domain = kinds.domain(state, piece)
        target = None if domain is None else territory.area_of(state, due[-1].places[0], domain)
        rest = piece.legs[len(due) :]
        if target is None:
            return piece.model_copy(update={"legs": rest}), True
        course = territory.plan(state, piece, target)
        if not isinstance(course, territory.Plan):
            return piece.model_copy(update={"legs": rest}), True
        moved = _set_on(piece, course, target, due[-1].since)
        update = {"legs": rest, "bound_for": None, "arrives": None}
        hidden = due[-1].concealed and detect.on(state)  # IOR: a game without reports as before
        return moved.model_copy(update=update | {"concealed_leg": hidden}), True
    return piece, piece.bound_for is None and bool(piece.path)


def _fuelled(
    state: State, piece: Feature, entered: EntityId, on: date, fuel: dict[EntityId, float]
) -> ev.StepRefused | None:
    """With ``fuel`` on (FUL): the step's fuel taken from the nation's stock in ``fuel``
    (the stock as the day began, less what today's earlier steps spent), or, with too
    little left, the refusal. Nothing for a kind that spends no fuel."""
    cost = trade.cost(state, piece)
    own = territory.nation(state, piece.side)
    if not cost or own is None:
        return None
    have = fuel.setdefault(own, economy.stock(state, own))
    if have >= cost:
        fuel[own] = round(have - cost, 6)
        return None
    name, unit = trade.unit(state)
    return ev.StepRefused(
        mark=territory.mark_key(state, own, piece),
        nation=own,
        area=piece.places[0],
        to=entered,
        on=on,
        reason=(
            f"too little {name.lower()}: the step needs {cost:g} {unit}, the stock holds {have:g}"
        ),
    )


def _walk_one(
    state: State,
    course: tuple[Feature, bool],
    today: date,
    meeting: Meeting,
    fuel: dict[EntityId, float],
    closed: dict[EntityId, EntityId] | None = None,
) -> tuple[Feature, list[ev.Payload]]:
    """The piece after every step that falls due by ``today``, with one ``piece_stepped``
    for each. Stances are read from ``state``, where everything stood when the day began,
    and from ``meeting``, so the order the pieces are walked in changes nothing but the
    fuel: a nation's stock is spent by its pieces in the order walked (FUL). A step into an
    area of a meeting battle (``closed``) held by a power at war with the piece's is not
    taken and its move is dropped (HON)."""
    moved, scripted = course
    cause = territory.StepCause.SCRIPTED if scripted else territory.StepCause.ORDERED
    out: list[ev.Payload] = []
    own = territory.nation(state, moved.side)
    while moved.path and moved.step_due is not None and moved.step_due <= today:
        entered, on = moved.path[0], moved.step_due
        if territory.barred(state, moved.side, entered, kinds.domain(state, moved)) is not None:
            moved = _halted(moved, on)
            break
        there = (closed or {}).get(entered)
        if there is not None and own is not None and at_war(state, own, there):
            moved = _halted(moved, on)
            break
        refused = _fuelled(state, moved, entered, on, fuel)
        if refused is not None:
            moved = _halted(moved, on)
            out.append(refused)
            break
        moved, stepped = territory.step(state, moved, entered, on, cause)
        out.append(stepped)
        if moved.path and _enemy_in(state, moved, entered, meeting):
            moved = _halted(moved, on)
        elif moved.path:
            days = territory.step_days(state, moved, moved.path[0])
            if days is None:
                moved = _halted(moved, on)
            else:
                moved = moved.model_copy(update={"step_due": on + timedelta(days=days)})
    return moved, out


def _pieces(state: State) -> list[Feature]:
    return sorted(
        (
            f
            for f in state.features.values()
            if f.kind is FeatureKind.PIECE and f.side is not None and in_play(f)
        ),
        key=lambda x: x.feature_id,
    )


def _head_on(
    state: State, courses: dict[FeatureId, tuple[Feature, bool]], today: date
) -> list[battle.Meet]:
    if not battle.on(state):
        return []
    movers: list[tuple[Feature, EntityId, EntityId]] = []
    for fid in sorted(courses):
        c, _ = courses[fid]
        if not c.path or c.step_due is None or c.step_due > today:
            continue
        frm = battle.fighting_area(state, c)
        if frm is None or territory.barred(state, c.side, c.path[0]) is not None:
            continue
        movers.append((c, frm, c.path[0]))
    return battle.meetings(state, movers)


def head_on(state: State, today: date) -> list[battle.Meet]:
    """With ``battles`` on, the borders met head-on on ``today`` (HON rule 1): pieces of two
    powers at war each due to step into the other's area. ``walk`` holds their movers, and
    the battle walk opens a meeting battle on each."""
    if not territory.on(state):
        return []
    pieces = _pieces(state)
    return _head_on(state, {f.feature_id: _course_set(state, f, today) for f in pieces}, today)


def walk(state: State, today: date) -> list[ev.Payload]:
    """With ``territories`` on: every piece's steps that fall due by ``today``, each piece's
    ``feature_set`` before its steps' ``piece_stepped`` events, then each pool as the lifts
    that landed today give their shipping back, then (FUL) each nation's pools with the
    fuel today's steps spent. With ``battles`` on, the movers of a border met head-on and
    the pieces of an open meeting battle do not step (HON). Last, with ``holders`` on, the
    territories the legs falling due today take (``holders.record_takes``, HSA)."""
    if not territory.on(state):
        return []
    out: list[ev.Payload] = []
    back: dict[QuantityId, int] = {}
    pieces = _pieces(state)
    courses = {f.feature_id: _course_set(state, f, today) for f in pieces}
    met = _head_on(state, courses, today)
    held = {fid for m in met for fid in m.movers}
    if battle.on(state):
        held |= battle.pinned(state)
    closed = battle.closed(state, met) if battle.on(state) else {}
    meeting = frozenset(
        (c.path[0], n)
        for c, _ in courses.values()
        if c.path and c.step_due is not None and c.step_due <= today and kinds.is_force(state, c)
        if c.feature_id not in held
        if (n := territory.nation(state, c.side)) is not None
    )
    fuel: dict[EntityId, float] = {}
    claims = [
        (area, n)
        for f in pieces
        if f.bound_for is None and (n := territory.nation(state, f.side)) is not None
        for leg in f.legs
        if leg.since <= today
        for area in leg.takes
    ]
    for f in pieces:
        stepped: list[ev.Payload] = []
        if f.feature_id in held:
            moved = courses[f.feature_id][0]
        else:
            moved, stepped = _walk_one(state, courses[f.feature_id], today, meeting, fuel, closed)
        if moved == f:
            continue
        out += [ev.FeatureSet(feature=moved), *stepped]
        pool = territory.lift_pool(state, f)
        if pool is not None and territory.lifted(state, f) and not territory.lifted(state, moved):
            back[pool] = back.get(pool, 0) + territory.lift_tons(f)
    for pool, tons in sorted(back.items()):
        change = _pool_by_id(state, pool, tons, today)
        if change is not None:
            q = state.quantities[pool]
            out.append(
                ev.QuantitySet(
                    quantity=q.model_copy(update={"value": change.value, "as_of": change.as_of})
                )
            )
    for own, left in sorted(fuel.items()):
        pools = state.economy.pools.get(own, economy.Pools())
        if left != pools.fuel:
            spent = pools.model_copy(update={"fuel": left})
            out.append(ev.EconomySet(polity=own, pools=spent, on=today))
    return out + holders.record_takes(state, claims, today)


def day_changes(state: State, today: date) -> tuple[Feature | QuantityChange, ...]:
    """``on_day``'s moves, and each pool with the lifts that land today given back."""
    moved = on_day(state, today)
    back: dict[str, int] = {}
    for f in moved:
        was = state.features.get(f.feature_id)
        if was is None or not _at_sea(state, was) or f.bound_for is not None:
            continue
        key = pool_key(state, was.side) if was.side is not None else None
        if key is not None and f.places == (was.bound_for,):
            back[key] = back.get(key, 0) + lift_needed(was)
    given = (_pool_change(state, k, n, today) for k, n in sorted(back.items()))
    return (*moved, *(c for c in given if c is not None))


def on_day(state: State, today: date) -> tuple[Feature, ...]:
    """Forces arriving today, history's moves that fall due, raiders out too long turned
    for base, and detachments that stand still with their force merged back."""
    out: list[Feature] = []
    adjacency = territory.on(state)
    for f in sorted(state.features.values(), key=lambda x: x.feature_id):
        if not in_play(f) or (adjacency and f.kind is FeatureKind.PIECE):
            continue  # with territories on, ``walk`` moves the pieces
        if f.bound_for is not None and f.arrives is not None and f.arrives <= today:
            out.append(
                f.model_copy(
                    update={
                        "places": (f.bound_for,),
                        "bound_for": None,
                        "arrives": None,
                        "as_of": today,
                        **_clock(state, f, f.bound_for, f.as_of, today),
                    }
                )
            )
        elif f.bound_for is None and f.legs and f.legs[0].since <= today:
            due = [leg for leg in f.legs if leg.since <= today]
            out.append(
                f.model_copy(
                    update={
                        "places": due[-1].places,
                        "legs": f.legs[len(due) :],
                        "as_of": today,
                        **_clock(state, f, due[-1].places[0], today, today),
                    }
                )
            )
        elif (back := _turned(state, f, today)) is not None:
            out.append(back)
    moved = {f.feature_id: f for f in out}
    return tuple({**moved, **rejoin({**state.features, **moved}, today)}.values())
