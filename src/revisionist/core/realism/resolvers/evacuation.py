"""The evacuation order (EVC), under the rule name ``economy``.

With ``economy`` on, an enacted form that names a ``territory`` and a ``rear`` territory,
both held by the issuing nation, moves ``EVAC_SHARE`` of the territory's printed output
yield to the rear over ``EVAC_DAYS`` days, the same part each day, from the day after the
order left its last step. Each part moves through ``economy.move_yield`` and pays nothing
for ``RESTART_DAYS``, then in full. The evacuation ends the first day either territory is
not the nation's, or has changed hands since the evacuation began: what has moved is kept,
and what had not stays in the territory and goes with it.

A territory is evacuated once: of the enacted evacuations that name it, the earliest (by
settling day, then terms, then id) is its evacuation, and the others move nothing.
No territory is named here; any world's card may carry the form.
"""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import EntityId
from revisionist.core.realism import economy
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.kinds import Role
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State
from revisionist.core.world_compile import object_id

EVAC_DAYS = 20  # [proposed] plan, EVC Defaults
EVAC_SHARE = 50  # [proposed] plan, EVC Defaults: percent of the output yield moved
RESTART_DAYS = 45  # [proposed] plan, EVC Defaults
TERRITORY, REAR = "territory", "rear"


def is_evacuation(order: Order) -> bool:
    """Whether an ``economy`` order is an evacuation: it names a territory and a rear."""
    return TERRITORY in order.params and REAR in order.params


def resolve(state: State, order: Order) -> tuple[ev.YieldChanged, ...]:
    """The order moves nothing when it is enacted: its parts move day by day."""
    return ()


def _key(order: Order) -> tuple[date, list[tuple[str, str]], str]:
    terms = sorted((k, repr(v)) for k, v in order.params.items())
    return rs.settled_on(order), terms, str(order.order_id)


def evacuations(state: State) -> list[Order]:
    """The enacted evacuations that act: the earliest for each territory named."""
    found: dict[str, Order] = {}
    enacted = [
        o for o in state.orders.values() if o.status is OrderStatus.ENACTED and is_evacuation(o)
    ]
    for o in sorted(enacted, key=_key):
        try:
            if rs.resolver_for(state, o) != "economy":
                continue
        except KeyError:
            continue
        found.setdefault(str(o.params[TERRITORY]), o)
    return sorted(found.values(), key=_key)


def _area(state: State, order: Order, name: str) -> EntityId:
    return EntityId(object_id(state.campaign_id, "entity", str(order.params[name])))


def _kept(state: State, area: EntityId, nation: EntityId, first: date) -> bool:
    """Whether the nation holds ``area`` and has held it since before ``first``."""
    if economy.holder(state, area) != nation:
        return False
    held = state.holders.get(area)
    return held is None or held.on < first


def _output(state: State, area: EntityId) -> dict[str, float]:
    """The territory's printed yields of the ``output`` role, by resource key."""
    board, found = state.map, state.kinds
    if board is None or found is None:
        return {}
    printed = next((dict(t.yields) for t in board.territories if t.area == area), {})
    return {
        k: v
        for k, v in sorted(printed.items())
        if (r := found.resources.get(k)) is not None and r.role is Role.OUTPUT
    }


def _parts(state: State, order: Order, today: date) -> list[ev.YieldChanged]:
    """The day's parts one evacuation moves, one per output resource."""
    first = rs.settled_on(order) + timedelta(days=1)
    if not first <= today < first + timedelta(days=EVAC_DAYS):
        return []
    nation = polity_of(state, state.seats[order.issuer].embodies)
    frm, to = _area(state, order, TERRITORY), _area(state, order, REAR)
    if nation is None or not (_kept(state, frm, nation, first) and _kept(state, to, nation, first)):
        return []
    now = economy.yields_of(state, frm)
    out = []
    for resource, printed in _output(state, frm).items():
        part = round(min(printed * EVAC_SHARE / 100 / EVAC_DAYS, now.get(resource, 0)), 6)
        if part <= 0 or economy.refusal(state, frm, to, resource, part) is not None:
            continue
        out.append(
            economy.move_yield(state, frm, to, resource, part, today, restart_days=RESTART_DAYS)
        )
    return out


def on_day(state: State, today: date) -> tuple[ev.YieldChanged, ...]:
    """The day's part of every evacuation under way; none with ``economy`` off, which
    ``economy.refusal`` refuses."""
    return tuple(p for order in evacuations(state) for p in _parts(state, order, today))
