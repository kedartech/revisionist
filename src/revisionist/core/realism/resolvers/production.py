"""The production resolver (plan, Phase 2 unit B3).

Lend-Lease findings and allocations, deliveries after a lead time. While a side's
latest enacted production priority is merchant ships, its troop-lift pool (sealift, R6)
gains a fixed tonnage on each 1st; in Autumn 1941 that is Churchill's priority and
Britain's pool. The other sectors and Stalin's ``aid_request`` change nothing in this
wave: no quantity is declared for them yet.
"""

from datetime import date

from revisionist.core.ids import EntityId
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers.shipping import moved
from revisionist.core.realism.resolvers.votes import put
from revisionist.core.realism.sealift import POOLS
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State

MERCHANT_GRT_PM = 15_000  # [proposed] sealift plan, section 3


def resolve(state: State, order: Order) -> tuple[QuantityChange, ...]:
    """Changes from one order enacted through its pipeline."""
    recipient = order.params.get("recipient")
    if order.status is not OrderStatus.ENACTED or order.lever != "lend_lease_finding":
        return ()
    as_of = rs.settled_on(order)
    out = []
    if recipient == "ussr":
        out.append(put(state, "soviet_lend_lease_eligible", 1, as_of))
    total, share = rs.value(state, "lend_lease_second_appropriation"), order.params.get("share_pct")
    if total is not None and isinstance(share, int):
        out.append(put(state, f"lend_lease_share_{recipient}", total * share // 100, as_of))
    return tuple(c for c in out if c is not None)


def _priority(state: State, side: EntityId, today: date) -> object:
    """The sector of the latest production priority a seat of ``side`` has enacted by
    ``today``; None when it has enacted none."""
    enacted = [
        (rs.settled_on(o), o.filed, str(o.order_id), o.params.get("sector"))
        for o in state.orders.values()
        if o.status is OrderStatus.ENACTED
        and o.lever == "production_priority"
        and rs.settled_on(o) <= today
        and polity_of(state, state.seats[o.issuer].embodies) == side
    ]
    return max(enacted, default=(None,) * 4)[3]


def on_day(state: State, today: date) -> tuple[QuantityChange, ...]:
    """On the 1st, each lift pool whose side's priority is merchant ships gains the
    month's tonnage. A pool with no owner names no side and gains nothing."""
    if today.day != 1:
        return ()
    out = []
    for key in sorted({k for pools in POOLS.values() for k in pools.values()}):
        q = state.quantities.get(rs.qid(state, key))
        side = None if q is None or q.owner is None else polity_of(state, q.owner)
        if side is not None and _priority(state, side, today) == "merchant_ships":
            out.append(moved(state, key, MERCHANT_GRT_PM, today))
    return tuple(c for c in out if c is not None)
