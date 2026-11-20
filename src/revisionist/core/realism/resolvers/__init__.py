"""The resolvers: four for quantities (plan, Phase 2 unit B3) and movement for
features (Batch 6).

Each module has ``resolve(state, order)`` for an enacted order whose lever names
it, and ``on_day(state, today)`` for what moves with time. Both are pure and
seeded only by ``friction``, so a replay computes the same numbers. Another
resolver needs Josh's word.
"""

import hashlib
from collections.abc import Callable
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import QuantityId
from revisionist.core.ontology import Fact, Relationship
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange, ResolverKey
from revisionist.core.realism.resolvers import (
    intel,
    movement,
    opinion,
    production,
    shipping,
    trade,
    votes,
    war,
)
from revisionist.core.realism.war import NewsEvent, War
from revisionist.core.state import State
from revisionist.core.world_compile import object_id

Change = (
    QuantityChange
    | Feature
    | War
    | NewsEvent
    | Fact
    | Relationship
    | ev.EconomySet
    | ev.DocumentIssued
    | ev.YieldChanged
    | ev.MandateIssued
    | ev.TradeSet
    | ev.AgentSet
    | ev.CodebreakingSet
    | ev.BattleDecided
)
"""A quantity's new value, a feature as it now stands, a war declared, a public news
event, a fact asserted, a relationship as it now stands, a nation's pools as they now
stand, a paper issued, part of a yield moved, a matter put on a seat's agenda, a trade
line cut or reopened, a nation's agent or codebreaking level set, or a battle decision
taken by an order's posture."""
OrderFn = Callable[[State, Order], tuple[Change, ...]]
DayFn = Callable[[State, date], tuple[Change, ...]]


def _votes(state: State, order: Order) -> tuple[Change, ...]:
    """``votes.resolve`` and what the bill does if it passes (``votes.law_effects``), or
    for an order carrying a measure (engine v2, a process
    part) its tally through each chamber under the bill keys it lands on: the
    historical bill of the same title, else the novel reference."""
    measure = order.measure
    if measure is None:
        changes = votes.resolve(state, order)
        known = votes.HISTORICAL.get(str(order.params.get("bill")))
        flag = next((c for c in changes if known and c.quantity_id == _flag(state, order)), None)
        return (*changes, *(votes.law_effects(state, known, flag) if known else ()))
    if order.status is not OrderStatus.ENACTED:
        return ()
    bill = next(
        (k for k, m in votes.HISTORICAL.items() if m.title == measure.title and k in votes.TALLIES),
        votes.NOVEL_REFERENCE,
    )
    senate_day = votes._step_day(order, 2)
    days = {
        "house": votes._step_day(order, 0),
        "senate": senate_day,
        "concur": senate_day + timedelta(days=votes.CONCUR_LAG_DAYS),
    }
    out: list[QuantityChange | None] = []
    passed = 1
    for chamber in votes.TALLIES[bill]:
        yeas, nays = votes.tally_measure(state, order.order_id, measure, chamber, False)
        out += [
            votes.put(state, f"{bill}_{chamber}_yeas", yeas, days[chamber]),
            votes.put(state, f"{bill}_{chamber}_nays", nays, days[chamber]),
        ]
        passed &= int(yeas > nays)
    flag = votes.put(state, f"{bill}_passed", passed, settled_on(order))
    out.append(flag)
    return (*(c for c in out if c is not None), *votes.law_effects(state, measure, flag))


def _flag(state: State, order: Order) -> QuantityId:
    return qid(state, f"{order.params.get('bill')}_passed")


ON_ORDER: dict[ResolverKey, OrderFn] = {
    "votes": _votes,
    "shipping": shipping.resolve,
    "production": production.resolve,
    "opinion": opinion.resolve,
    "movement": movement.order_changes,
    "war": war.resolve,
    "economy": production.economy_order,
    "trade": trade.resolve,
    "intel": intel.resolve,
}
ON_DAY: dict[ResolverKey, DayFn] = {
    "votes": votes.on_day,
    "shipping": shipping.on_day,
    "production": production.on_day,
    "opinion": opinion.on_day,
    "movement": movement.day_changes,
    "war": war.on_day,
    "economy": production.economy_day,
    "trade": trade.on_day,
    "intel": intel.on_day,
}


def qid(state: State, key: str) -> QuantityId:
    """The id a world-file quantity key compiles to in this campaign."""
    return QuantityId(object_id(state.campaign_id, "quantity", key))


def value(state: State, key: str) -> int | None:
    """A quantity's current value by world-file key; None if absent or a gap."""
    q = state.quantities.get(qid(state, key))
    return None if q is None else q.value


def resolver_for(state: State, order: Order) -> ResolverKey:
    """The resolver the issuer's card names for the order's lever; an order carrying
    a measure is counted by votes."""
    if order.measure is not None:
        return "votes"
    seat = state.seats[order.issuer]
    card = state.cards[seat.embodies]
    for lever in card.levers:
        if lever.name == order.lever:
            return lever.resolver
    raise KeyError(f"order {order.order_id}: lever {order.lever} is not on the issuer's card")


def settled_on(order: Order) -> date:
    """The day the order left its last step (its filing day if it had none)."""
    return order.outcomes[-1].on if order.outcomes else order.filed


def friction(state: State, *parts: object, n: int) -> int:
    """A deterministic integer in [0, n) from the campaign and ``parts``: the only
    randomness a resolver may use."""
    key = "\x1f".join([str(state.campaign_id), *map(str, parts)])
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big") % n


def apply_changes(state: State, changes: tuple[Change, ...]) -> list[ev.Payload]:
    """The events for ``changes``: each quantity as it stands, with the new value and
    date, and every other change as given. Raises ``KeyError`` for a quantity the
    world never declared."""
    out: list[ev.Payload] = []
    for c in changes:
        if isinstance(c, Feature):
            out.append(ev.FeatureSet(feature=c))
        elif isinstance(c, War):
            out.append(ev.WarDeclared(war=c))
        elif isinstance(c, NewsEvent):
            out.append(ev.NewsReported(news=c))
        elif isinstance(c, Fact):
            out.append(ev.FactAsserted(fact=c))
        elif isinstance(c, Relationship):
            out.append(ev.RelationshipSet(relationship=c))
        elif isinstance(
            c,
            ev.EconomySet
            | ev.DocumentIssued
            | ev.YieldChanged
            | ev.MandateIssued
            | ev.TradeSet
            | ev.AgentSet
            | ev.CodebreakingSet
            | ev.BattleDecided,
        ):
            out.append(c)
        else:
            out.append(
                ev.QuantitySet(
                    quantity=state.quantities[c.quantity_id].model_copy(
                        update={"value": c.value, "as_of": c.as_of}
                    )
                )
            )
    return out


__all__ = [
    "ON_DAY",
    "ON_ORDER",
    "Change",
    "apply_changes",
    "friction",
    "qid",
    "resolver_for",
    "settled_on",
    "value",
]
