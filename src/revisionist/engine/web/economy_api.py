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

With ``raising`` on (RNR), the seat's own nation's block also carries ``places``: for a seat
whose card holds a form that raises, each place the form names where a base of the
nation's own takes one of the form's kinds, each kind with its cost, its lead days, the day
it would arrive and the pools after, and the raising check's words when it may not be
filed now (``production.raise_refusal``, the check filing runs); and ``raising``: every
piece the nation is raising, with its place and its day. Both are of the seat's own nation
only: no other nation's place, cost or raising reaches the payload.
"""

from datetime import date, timedelta
from typing import Literal

from revisionist.core.ids import EntityId, OrderId, PipelineId, SeatId, derived_id
from revisionist.core.ontology import EntityKind
from revisionist.core.project import at_post
from revisionist.core.realism import economy, holders, territory, trade
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.card import Lever
from revisionist.core.realism.kinds import Role
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import production
from revisionist.core.realism.war import at_war, polity_of
from revisionist.core.state import State, View
from revisionist.engine.web.realism_api import (
    EconomyBlock,
    EconomyFigure,
    EconomyIncome,
    EconomyOwn,
    EconomyPools,
    EconomyTerritory,
    MapNation,
    RaiseKind,
    RaisePlace,
    RaisingLine,
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


def _pools(state: State, view: View, own: EntityId, post: bool) -> EconomyPools:
    pools = view.economy.pools.get(own, economy.Pools())
    out = EconomyPools() if post else EconomyPools(output=pools.output, manpower=pools.manpower)
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


def _forms(state: State, seat: SeatId) -> list[Lever]:
    """The forms on the seat's card that raise: of the economy or of production, naming a
    kind and a place."""
    held = state.seats.get(seat)
    card = state.cards.get(held.embodies) if held is not None else None
    return [
        x
        for x in (card.levers if card is not None else ())
        if production.raising_form(state, seat, x.name)
        and {production.KIND, production.PLACE} <= {p.name for p in x.params}
    ]


def _choices(form: Lever, name: str) -> tuple[str, ...]:
    found = next(p for p in form.params if p.name == name)
    return tuple(str(c) for c in found.choices or ())


def _arrives(state: State, order: Order) -> date:
    """The day ``order`` brings its piece in: the rule's once it is enacted, else the day
    it would if each step left were taken on its day."""
    if order.status is OrderStatus.ENACTED:
        return production.raise_day(state, order)
    kind = production.raised_kind(state, order.params.get(production.KIND))
    lead = kind.lead_days if kind is not None and kind.lead_days is not None else 0
    left = state.pipelines[order.pipeline].steps[order.step :]
    return rs.settled_on(order) + timedelta(sum(s.days or 0 for s in left) + lead)


def _raising(state: State, own: EntityId, today: date) -> list[tuple[date, Order]]:
    """The nation's raisings under way, each with its day, by day then order id."""
    out = [
        (_arrives(state, o), o)
        for o in production.being_raised(state, today)
        if polity_of(state, state.seats[o.issuer].embodies) == own
    ]
    return sorted(out, key=lambda t: (t[0], t[1].order_id))


def area_key(state: State, place: EntityId) -> str:
    """The map key of the territory a place's base stands in; empty when none."""
    board = state.map
    if board is None:
        return ""
    land = next((b.land for b in board.bases if b.place == place and b.land is not None), None)
    return next((t.key for t in board.territories if t.area == land), "")


def _name(state: State, key: EntityId) -> str:
    found = state.entities.get(key)
    return found.name if found is not None else ""


def raising_lines(state: State, own: EntityId, today: date) -> list[RaisingLine]:
    """Every piece the nation ``own`` is raising on ``today``, by day."""
    out: list[RaisingLine] = []
    for day, order in _raising(state, own, today):
        key = str(order.params[production.KIND])
        kind = production.raised_kind(state, key)
        place = production.place_id(state, order.params[production.PLACE])
        out.append(
            RaisingLine(
                kind=key,
                name=kind.name if kind is not None else key,
                place=str(order.params[production.PLACE]),
                place_name=_name(state, place),
                area=area_key(state, place),
                day=day.isoformat(),
                fixed=order.status is OrderStatus.ENACTED,
                picture=kind.picture.value
                if kind is not None and kind.picture is not None
                else None,
            )
        )
    return out


UNLISTED = frozenset({production.NOT_RAISED, production.NO_BASE, production.NOT_YOURS})
"""Refusals that mean the place does not raise the kind for the nation at all."""


def _kind(
    state: State,
    seat: SeatId,
    form: Lever,
    place: str,
    key: str,
    pools: economy.Pools,
    due: list[tuple[date, Order]],
) -> RaiseKind | None:
    """A kind the form can raise at ``place``, as filing it today would go; None when no
    base of the nation's own there takes it."""
    params = {production.KIND: key, production.PLACE: place}
    refusal = production.raise_refusal(state, seat, form.name, params)
    kind = production.raised_kind(state, key)
    today = state.in_world_date
    if refusal in UNLISTED or kind is None or kind.cost is None or today is None:
        return None
    draft = Order(
        order_id=OrderId(derived_id(state.campaign_id, "raise-draft", seat)),
        issuer=seat,
        lever=form.name,
        pipeline=PipelineId(form.pipeline),
        params=params,
        filed=today,
    )
    arrives = _arrives(state, draft)
    before = [o for day, o in due if day <= arrives]
    spent = [production.raised_kind(state, o.params[production.KIND]) for o in before]
    costs = [k.cost for k in (*spent, kind) if k is not None and k.cost is not None]
    return RaiseKind(
        kind=key,
        name=kind.name,
        cost={"output": kind.cost.output, "manpower": kind.cost.manpower},
        lead_days=kind.lead_days or 0,
        arrives=arrives.isoformat(),
        pools_after=EconomyPools(
            output=pools.output - sum(c.output for c in costs),
            manpower=pools.manpower - sum(c.manpower for c in costs),
        ),
        refusal=refusal,
    )


def places(state: State, view: View, own: EntityId, today: date) -> list[RaisePlace]:
    """Each place where the seat's own forms can raise, by key; none for a seat held to
    its post, whose pools are its government's books."""
    seat = view.viewer
    if at_post(state, seat):
        return []
    pools = view.economy.pools.get(own, economy.Pools())
    due = _raising(state, own, today)
    out: dict[str, RaisePlace] = {}
    for form in _forms(state, seat):
        for place in _choices(form, production.PLACE):
            kinds = [
                found
                for key in _choices(form, production.KIND)
                if (found := _kind(state, seat, form, place, key, pools, due)) is not None
            ]
            if kinds and place not in out:
                at = production.place_id(state, place)
                out[place] = RaisePlace(
                    place=place,
                    name=_name(state, at),
                    area=area_key(state, at),
                    form=form.name,
                    kinds=kinds,
                )
    return [out[k] for k in sorted(out)]


def block(state: State, view: View) -> EconomyBlock | None:
    """The ``economy`` block; None with ``economy`` off. A commander held to his post gets
    of his own nation its fuel stock and months of fuel only: its income, other pools and
    territories' yields are his government's books."""
    day = view.in_world_date
    if not economy.on(state) or day is None:
        return None
    own = own_nation(view)
    post = at_post(state, view.viewer)
    mine: EconomyOwn | None = None
    if own is not None:
        mine = EconomyOwn(
            nation=nation(state, own, own),
            income=[] if post else _income(view, own, day),
            pools=_pools(state, view, own, post),
            fuel_months=_fuel_months(state, view, own, day),
            territories=[] if post else _territories(view, own, day),
        )
        if production.raising_on(state):
            mine["places"] = places(state, view, own, day)
            mine["raising"] = raising_lines(state, own, day)
    return EconomyBlock(day=day.isoformat(), figures=_figures(state, view, own), own=mine)


__all__ = ["Holdings", "area_key", "block", "nation", "own_nation", "places", "raising_lines"]
