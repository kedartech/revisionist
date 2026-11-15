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
"""

from datetime import date, timedelta

from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.ontology import EntityKind
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
from revisionist.core.realism.geography import FORCES, Feature, in_play
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.routing import travel_days
from revisionist.core.realism.sealift import lift_needed
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
    for f in sorted(state.features.values(), key=lambda x: x.feature_id):
        if not in_play(f):
            continue
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
