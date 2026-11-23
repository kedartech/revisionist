"""Holders and the war economy as the seat sees them (WEV).

``holding`` is what a land area of the ``map`` block gains with ``holders`` on: its holder,
the day it changed hands and the holder it was taken from, all public, and for the holding
nation's seats only the day a capital in it was marked to fall (``holders.falling``, the
same mark the seat's paper and wake notice carry). Every area also carries the yields the
board prints.

``block`` is the ``economy`` block with ``economy`` on: every nation's public figure, and
for the seat's own nation its income by resource, its pools (with ``fuel`` on, its fuel
stock too), its months of fuel left and each held territory's yields and factors. It is
read from the seat's ``View``, which holds its own nation's pools and moved yields and no
other's, so no other nation's economy can reach the payload.
"""

from datetime import date
from typing import Literal

from revisionist.core.ids import EntityId, SeatId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism import economy, holders, territory, trade
from revisionist.core.realism.kinds import Role
from revisionist.core.realism.war import at_war
from revisionist.core.state import State, View
from revisionist.engine.web.realism_api import (
    EconomyBlock,
    EconomyFigure,
    EconomyIncome,
    EconomyOwn,
    EconomyPools,
    EconomyTerritory,
    MapNation,
)

Relation = Literal["own", "ally", "enemy", "neutral"]


def own_nation(view: View) -> EntityId | None:
    """The polity the seat sits for: its person's nearest polity; None for none."""
    seen: set[EntityId] = set()
    here = view.entities.get(view.me.embodies)
    while here is not None and here.entity_id not in seen:
        if here.kind is EntityKind.POLITY:
            return here.entity_id
        seen.add(here.entity_id)
        here = view.entities.get(here.parent) if here.parent is not None else None
    return None


def nation(state: State, own: EntityId | None, polity: EntityId) -> MapNation:
    """``polity`` as the seat of ``own`` names it. Wars are public, so the relation is the
    same whichever seat of one nation asks."""
    e = state.entities.get(polity)
    relation: Relation = "neutral"
    if own is not None and polity == own:
        relation = "own"
    elif own is not None and at_war(state, own, polity):
        relation = "enemy"
    elif own is not None and territory.allied(state, own, polity):
        relation = "ally"
    return MapNation(key=polity, name=e.name if e is not None else "", relation=relation)


class Holdings:
    """The holder keys of the land areas, for one seat. With ``holders`` off, every key
    is None."""

    def __init__(self, state: State, view: View, seat: SeatId) -> None:
        self.state = state
        self.own = own_nation(view)
        self.on = holders.on(state)
        self.marked = dict(holders.falling(state, seat)) if self.on else {}

    def holder(self, area: EntityId) -> MapNation | None:
        held = holders.holder(self.state, area) if self.on else None
        return nation(self.state, self.own, held) if held is not None else None

    def held_since(self, area: EntityId) -> str | None:
        was = self.state.holders.get(area) if self.on else None
        return was.on.isoformat() if was is not None else None

    def taken_from(self, area: EntityId) -> MapNation | None:
        was = self.state.holders.get(area) if self.on else None
        if was is None or was.taken_from is None:
            return None
        return nation(self.state, self.own, was.taken_from)

    def falling(self, area: EntityId) -> str | None:
        marked = self.marked.get(area)
        return marked.isoformat() if marked is not None else None


def _income(view: View, own: EntityId, day: date) -> list[EconomyIncome]:
    kinds = view.kinds
    if kinds is None:
        return []
    amounts = dict.fromkeys(kinds.resources, 0.0)
    board = view.map
    for t in board.territories if board is not None else ():
        if economy.holder(view, t.area) != own:
            continue
        for key, amount in sorted(economy.working(view, t.area, day).items()):
            found = kinds.resources.get(key)
            if found is not None:
                amounts[key] += amount * economy.factor(view, t.area, found.role, day)
    return [
        EconomyIncome(
            key=key,
            name=r.name,
            unit=r.unit,
            role=r.role.value,
            amount=round(amounts[key], 6),
        )
        for key, r in kinds.resources.items()
    ]


def _pools(state: State, view: View, own: EntityId) -> EconomyPools:
    pools = view.economy.pools.get(own, economy.Pools())
    out = EconomyPools(output=pools.output, manpower=pools.manpower)
    if trade.on(state):
        out["fuel"] = pools.fuel
    return out


def _fuel_months(state: State, view: View, own: EntityId, day: date) -> float | None:
    """The stock over a month's fuel income as the first of the month pays it: the fuel
    yields of what the nation holds and what its open trade lines pay."""
    if not trade.on(state):
        return None
    monthly = economy.income(view, own, Role.FUEL, day) + trade.paid_to(view, own, Role.FUEL)
    if monthly <= 0:
        return None
    return round(economy.stock(view, own) / monthly, 6)


def _territories(view: View, own: EntityId, day: date) -> list[EconomyTerritory]:
    board = view.map
    held = [
        t
        for t in (board.territories if board is not None else ())
        if economy.holder(view, t.area) == own
    ]
    return [
        EconomyTerritory(
            area=t.key,
            name=t.name,
            yields=economy.working(view, t.area, day),
            factors={role.value: economy.factor(view, t.area, role, day) for role in Role},
        )
        for t in sorted(held, key=lambda t: t.key)
    ]


def _figures(state: State, view: View, own: EntityId | None) -> list[EconomyFigure]:
    polities = [k for k, e in view.entities.items() if e.kind is EntityKind.POLITY]
    out = [
        EconomyFigure(nation=nation(state, own, p), figure=economy.figure(view, p))
        for p in polities
    ]
    out.sort(key=lambda f: (-f["figure"], f["nation"]["name"], f["nation"]["key"]))
    return out


def block(state: State, view: View) -> EconomyBlock | None:
    """The ``economy`` block; None with ``economy`` off."""
    day = view.in_world_date
    if not economy.on(state) or day is None:
        return None
    own = own_nation(view)
    mine: EconomyOwn | None = None
    if own is not None:
        mine = EconomyOwn(
            nation=nation(state, own, own),
            income=_income(view, own, day),
            pools=_pools(state, view, own),
            fuel_months=_fuel_months(state, view, own, day),
            territories=_territories(view, own, day),
        )
    return EconomyBlock(day=day.isoformat(), figures=_figures(state, view, own), own=mine)


__all__ = ["Holdings", "block", "nation", "own_nation"]
