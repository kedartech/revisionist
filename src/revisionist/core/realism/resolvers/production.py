"""The production resolver (plan, Phase 2 unit B3; PRD).

Lend-Lease findings and allocations, deliveries after a lead time. While a side's
latest enacted production priority is merchant ships, its troop-lift pool (sealift, R6)
gains a fixed tonnage on each 1st; in Autumn 1941 that is Churchill's priority and
Britain's pool. The other sectors and Stalin's ``aid_request`` change nothing in this
wave: no quantity is declared for them yet. That is the rule name ``production``, which
stored games keep.

The rule name ``economy`` (PRD), with the ``economy`` rule on: an enacted form that names
a ``force`` builds one strength step for it, ``LEAD_DAYS`` after the order left its last
step. On that day the nation's pools are read and, if both hold enough, ``STEP_COST``
output points and ``STEP_MANPOWER`` manpower points are spent and the piece gains a step,
up to its kind's maximum. A short pool, a piece out of supply that day, a piece at full
strength or one that is not the nation's own adds and spends nothing. A form that names a
world figure (``adds_to``) adds ``ADDS_PER_STEP`` to it instead, at the same cost. Either
way the issuing seat gets one report that day saying what was built or why nothing was.
Each enacted order counts once: it is read only on its due day. The due orders of a day
are taken by settling day, then by what they name, then by id, so an earlier order spends
first; pools are read before the same day's first-of-the-month payment (``economy.walk``
runs after the day rules).
"""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId, FeatureId, derived_id
from revisionist.core.realism import actors, economy, kinds, supply, territory
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import evacuation
from revisionist.core.realism.resolvers.shipping import moved
from revisionist.core.realism.resolvers.votes import put
from revisionist.core.realism.sealift import POOLS
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.core.world_compile import object_id

MERCHANT_GRT_PM = 15_000  # [proposed] sealift plan, section 3
STEP_COST = 10  # [proposed] plan, PRD Defaults
STEP_MANPOWER = 1  # [proposed] plan, PRD Defaults
LEAD_DAYS = 30  # [proposed] plan, PRD Defaults
ADDS_PER_STEP = 1  # [proposed]


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


FORCE, ADDS_TO = "force", "adds_to"
TIER_CAP = 5
"""The most strength a feature holds (``Feature.tier``), whatever its kind says."""
LINE = 60


def economy_order(state: State, order: Order) -> tuple["rs.Change", ...]:
    """The order changes nothing when it is enacted: its step is built on its due day,
    and an evacuation (EVC) moves its parts day by day."""
    return ()


def _due(state: State, today: date) -> list[Order]:
    """The enacted ``economy`` orders whose step falls due ``today``, earliest first."""
    due = []
    for o in state.orders.values():
        if o.status is not OrderStatus.ENACTED or rs.settled_on(o) + timedelta(LEAD_DAYS) != today:
            continue
        if evacuation.is_evacuation(o):
            continue
        try:
            if rs.resolver_for(state, o) != "economy":
                continue
        except KeyError:
            continue
        due.append(o)
    return sorted(
        due,
        key=lambda o: (
            rs.settled_on(o),
            sorted((k, repr(v)) for k, v in o.params.items()),
            o.order_id,
        ),
    )


def _short(pools: Pools) -> str | None:
    """Why the pools cannot pay for a step; None when they can."""
    if pools.output < STEP_COST:
        return f"The output pool is short: {pools.output:g} of {STEP_COST}"
    if pools.manpower < STEP_MANPOWER:
        return f"The manpower pool is short: {pools.manpower:g} of {STEP_MANPOWER}"
    return None


def _force(state: State, nation: EntityId, key: str) -> tuple[Feature | None, str | None]:
    """The nation's force named ``key`` and why it gains no step (None when it can)."""
    force = state.features.get(FeatureId(object_id(state.campaign_id, "feature", key)))
    if force is None or not kinds.is_force(state, force) or force.rejoined_on is not None:
        return None, f"{key} is not a force of {state.entities[nation].name}"
    if territory.nation(state, force.side) != nation:
        return None, f"{force.name} is not a force of {state.entities[nation].name}"
    kind = kinds.of(state, force)
    top = min(kind.max_strength if kind is not None else kinds.MAX_STRENGTH, TIER_CAP)
    if force.tier >= top:
        return force, f"{force.name} is at full strength"
    found = supply.status(state, force)
    if found is not None and not found.supplied:
        return force, f"{force.name} is out of supply"
    return force, None


def _clip(text: str) -> str:
    return text if len(text) <= LINE else text[: LINE - 1] + "\N{HORIZONTAL ELLIPSIS}"


def _report(
    state: State, order: Order, nation: EntityId, today: date, title: str, rows: list[BodyField]
) -> ev.DocumentIssued | None:
    """The one report to the issuing seat on the due day; None for a seat with no desk."""
    if order.issuer not in actors.readers(state):
        return None
    doc_id = DocumentId(derived_id(state.campaign_id, "production", order.order_id))
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.REPORT,
            author=nation,
            issued=today,
            arrives=today,
            channel=ChannelKind.CABLE,
            classification=Classification.CONFIDENTIAL,  # [proposed]
            title=_clip(title),
            body=tuple(rows),
            scope=private_to(order.issuer),
        ),
        truth=DocumentTruth(doc_id=doc_id),
    )


def _build(state: State, order: Order, today: date) -> list["rs.Change"]:
    """What one due order builds today: the pools spent, the step or the figure, and the
    report; only the report when nothing can be built."""
    nation = polity_of(state, state.seats[order.issuer].embodies)
    if nation is None:
        return []
    pools = state.economy.pools.get(nation, Pools())
    figure = order.params.get(ADDS_TO)
    built: rs.Change | None = None
    if isinstance(figure, str):
        q = state.quantities.get(rs.qid(state, figure))
        name = q.name if q is not None else figure
        why = None if q is not None and q.value is not None else f"{name} is not known"
        if why is None and q is not None and q.value is not None:
            built = QuantityChange(
                quantity_id=q.quantity_id, value=q.value + ADDS_PER_STEP, as_of=max(today, q.as_of)
            )
        what = name
    else:
        force, why = _force(state, nation, str(order.params.get(FORCE)))
        what = force.name if force is not None else str(order.params.get(FORCE))
        if force is not None and why is None:
            built = force.model_copy(update={"tier": force.tier + 1})
    why = why or _short(pools)
    if why is not None or built is None:
        paper = _report(
            state,
            order,
            nation,
            today,
            f"Production: nothing built for {what}",
            [
                BodyField(label="For", value=_clip(what)),
                BodyField(label="Why", value=_clip(why or "")),
            ],
        )
        return [paper] if paper is not None else []
    spent = Pools(output=pools.output - STEP_COST, manpower=pools.manpower - STEP_MANPOWER)
    paper = _report(
        state,
        order,
        nation,
        today,
        f"Production: {what} built up",
        [
            BodyField(label="For", value=_clip(what)),
            BodyField(label="Spent", value=f"{STEP_COST} output, {STEP_MANPOWER} manpower"),
        ],
    )
    out: list[rs.Change] = [
        ev.EconomySet(polity=nation, pools=spent, on=today),
        built,
    ]
    return out + ([paper] if paper is not None else [])


def economy_day(state: State, today: date) -> tuple["rs.Change", ...]:
    """With ``economy`` on, every step due today built or reported, each order folded
    before the next reads the pools; then each evacuation's part for the day (EVC)."""
    if not economy.on(state):
        return ()
    out: list[rs.Change] = []
    for order in _due(state, today):
        changes = _build(state, order, today)
        out += changes
        state = _after(state, changes)
    return (*out, *evacuation.on_day(state, today))


def _after(state: State, changes: list["rs.Change"]) -> State:
    """``state`` as the next due order reads it: the pools spent, the piece or the figure
    built."""
    pools, features, quantities = (
        dict(state.economy.pools),
        dict(state.features),
        dict(state.quantities),
    )
    for c in changes:
        if isinstance(c, ev.EconomySet):
            pools[c.polity] = c.pools
        elif isinstance(c, Feature):
            features[c.feature_id] = c
        elif isinstance(c, QuantityChange):
            quantities[c.quantity_id] = quantities[c.quantity_id].model_copy(
                update={"value": c.value, "as_of": c.as_of}
            )
    return state.model_copy(
        update={
            "economy": state.economy.model_copy(update={"pools": pools}),
            "features": features,
            "quantities": quantities,
        }
    )
