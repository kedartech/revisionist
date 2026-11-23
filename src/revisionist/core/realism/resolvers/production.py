"""The production resolver (plan, Phase 2 unit B3; PRD).

Aid findings and allocations, deliveries after a lead time. While a side's latest
enacted production priority names the choice that grows its troop-lift pool (sealift, R6),
the pool gains a fixed tonnage on each 1st. The other forms of the rule name change nothing
here. That is the rule name ``production``.

Which form is the finding, the figure it draws on, each recipient's share figure and
eligibility flag, and which form and choice is the priority, are the world's
(``production``, PRL), read from the board. A board compiled before PRL holds none of
them; a stored game on such a board, or one without a map, keeps the Autumn 1941 names
in ``production_stored``: Lend-Lease, the Soviet Union's eligibility, Churchill's merchant
ships.

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
from typing import NamedTuple

from revisionist.core import events as ev
from revisionist.core.goals import ActOf
from revisionist.core.ids import (
    DocumentId,
    EntityId,
    FeatureId,
    MandateId,
    QuantityId,
    SeatId,
    derived_id,
)
from revisionist.core.ontology import EntityKind, Fact
from revisionist.core.realism import actors, economy, kinds, sealift, territory
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.agenda import (
    MANDATE_CAP,
    Mandate,
    MandateKind,
    MandateStatus,
    opening_id,
)
from revisionist.core.realism.card import ChannelKind, Lever, ParamKind, ParamSpec
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.geography import Feature, FeatureKind
from revisionist.core.realism.kinds import Domain
from revisionist.core.realism.land import allocate
from revisionist.core.realism.pipeline import Order, OrderStatus, StepKind
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import evacuation, shipping
from revisionist.core.realism.resolvers import production_stored as stored
from revisionist.core.realism.resolvers.shipping import shifted
from revisionist.core.realism.resolvers.votes import put
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.core.world_compile import object_id

MERCHANT_GRT_PM = 15_000  # [proposed] sealift plan, section 3
STEP_COST = 10  # [proposed] plan, PRD Defaults
STEP_MANPOWER = 1  # [proposed] plan, PRD Defaults
LEAD_DAYS = 30  # [proposed] plan, PRD Defaults
ADDS_PER_STEP = 1  # [proposed]
AID_USD_PER_POINT = 100_000_000  # [proposed] plan, AID Defaults
AID_LEAD_DAYS = 45  # [proposed] plan, AID Defaults
AID_ANSWER_DAYS = 14  # [proposed]
AID_UNIT = "USD"  # [proposed] the unit of a figure aid is drawn from


def _matter(state: State, lever: str) -> str:
    """What an order of ``lever`` allocates, as its receipt names it: the key of the first
    topic the lever touches, else the lever's own name."""
    return next((t.key for t in state.topics.values() if lever in t.levers), lever)


def _keys(state: State) -> territory.Production | None:
    """The world's production keys, empty for a world that declares none; None for a game
    whose board predates them, or that has no board: a stored game, read by ``stored``."""
    return None if state.map is None else state.map.production


def resolve(state: State, order: Order) -> tuple["rs.Change", ...]:
    """Changes from one order enacted through its pipeline: an aid finding's figures and
    the recipient's receipt, and with ``economy`` on, a request for aid put on the giver's
    agenda."""
    if order.status is not OrderStatus.ENACTED:
        return ()
    keys = _keys(state)
    if keys is None:
        return _stored_finding(state, order)
    found = next((f for f in keys.findings if f.form == order.lever), None)
    if found is None:
        return tuple(_asked(state, order))
    aid = _aid(state, order)
    if aid is None:
        return ()
    as_of = rs.settled_on(order)
    out: list[rs.Change | None] = []
    if (flag := found.eligible.get(aid.recipient)) is not None:
        out.append(_set(state, flag, 1, as_of))
    total, figure = _value(state, found.draws_on), found.shares.get(aid.recipient)
    if total is not None and figure is not None:
        out.append(_set(state, figure, total * aid.share_pct // 100, as_of))
    out.append(_receipt(state, order, aid.recipient, aid.share_pct, as_of))
    return tuple(c for c in out if c is not None)


def _value(state: State, figure: QuantityId) -> int | None:
    q = state.quantities.get(figure)
    return None if q is None else q.value


def _set(state: State, figure: QuantityId, value: int, as_of: date) -> QuantityChange | None:
    """A change to ``figure``, or None when the game holds no such figure."""
    if figure not in state.quantities:
        return None
    return QuantityChange(quantity_id=figure, value=value, as_of=as_of)


def _receipt(state: State, order: Order, taker: EntityId, share: int, as_of: date) -> Fact | None:
    """The recipient's receipt, or None when the game holds it already: the written
    allocation for the same share landed that day files the same fact."""
    issuer = state.seats[order.issuer].embodies
    what = _matter(state, order.lever)
    fact = allocate.receipt(state, taker, issuer, order.issuer, what, share, as_of)
    return None if fact.fact_id in state.facts else fact


def _stored_finding(state: State, order: Order) -> tuple["rs.Change", ...]:
    """A stored game's finding, by the Autumn 1941 names (``production_stored``)."""
    if order.lever != stored.FINDING:
        return tuple(_asked(state, order))
    recipient = order.params.get(stored.RECIPIENT)
    as_of = rs.settled_on(order)
    out: list[rs.Change | None] = []
    if recipient == stored.ELIGIBLE_NATION:
        out.append(put(state, stored.ELIGIBLE_FLAG, 1, as_of))
    total, share = rs.value(state, stored.FUND), order.params.get(stored.SHARE)
    if total is not None and isinstance(share, int):
        out.append(put(state, stored.share_figure(recipient), total * share // 100, as_of))
    taker = EntityId(object_id(state.campaign_id, "entity", str(recipient)))
    if taker in state.entities and isinstance(share, int):
        out.append(_receipt(state, order, taker, share, as_of))
    return tuple(c for c in out if c is not None)


def _priority(state: State, side: EntityId, today: date) -> bool:
    """Whether the latest priority a seat of ``side`` has enacted by ``today`` names the
    choice that grows a lift pool: the world's form and choice, or a stored game's."""
    keys = _keys(state)
    if keys is None:
        form, grows = stored.PRIORITY, stored.GROWS
    elif keys.priority is None:
        return False
    else:
        form, grows = keys.priority.form, keys.priority.choice
    enacted = [
        (rs.settled_on(o), o.filed, str(o.order_id), o)
        for o in state.orders.values()
        if o.status is OrderStatus.ENACTED
        and o.lever == form
        and rs.settled_on(o) <= today
        and polity_of(state, state.seats[o.issuer].embodies) == side
    ]
    if not enacted:
        return False
    latest = max(enacted, key=lambda e: e[:3])[3]
    if keys is None:
        return latest.params.get(stored.SECTOR) == grows
    return grows in latest.params.values()


def on_day(state: State, today: date) -> tuple[QuantityChange, ...]:
    """On the 1st, each lift pool whose side's latest priority names the growing choice
    gains the month's tonnage. A pool with no owner names no side and gains nothing."""
    if today.day != 1:
        return ()
    out = []
    for pool in sealift.pools(state):
        q = state.quantities[pool]
        side = None if q.owner is None else polity_of(state, q.owner)
        if side is not None and _priority(state, side, today):
            out.append(shifted(state, pool, MERCHANT_GRT_PM, today))
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
    if shipping.supplied(state, force, state.in_world_date) is False:
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
    before the next reads the pools; then each aid share due today (AID); then each
    evacuation's part for the day (EVC)."""
    if not economy.on(state):
        return ()
    out: list[rs.Change] = []
    for order in _due(state, today):
        changes = _build(state, order, today)
        out += changes
        state = _after(state, changes)
    for order in _aid_due(state, today):
        changes = _deliver(state, order, today)
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


# --- Aid that arrives (AID) ---------------------------------------------------------------


class _Aid(NamedTuple):
    """What an aid form names, read from its parameters' values against the world."""

    giver: EntityId
    recipient: EntityId
    route: Feature | None
    share_pct: int


def _polity(state: State, key: object) -> EntityId | None:
    if not isinstance(key, str):
        return None
    found = state.entities.get(EntityId(object_id(state.campaign_id, "entity", key)))
    return found.entity_id if found is not None and found.kind is EntityKind.POLITY else None


def _aid(state: State, order: Order) -> _Aid | None:
    """The aid ``order`` sends, by what each parameter's value names: another nation (the
    recipient), a world route, and a whole number (the share in per cent). None for an
    order that names no other nation or no share."""
    giver = polity_of(state, state.seats[order.issuer].embodies)
    recipients = [p for v in order.params.values() if (p := _polity(state, v)) not in (None, giver)]
    shares = [v for v in order.params.values() if isinstance(v, int)]
    routes = [
        f
        for v in order.params.values()
        if isinstance(v, str)
        and (f := state.features.get(FeatureId(object_id(state.campaign_id, "feature", v))))
        and f.kind is FeatureKind.ROUTE
    ]
    if giver is None or len(recipients) != 1 or len(shares) != 1:
        return None
    recipient = recipients[0]
    assert recipient is not None
    return _Aid(giver, recipient, routes[0] if routes else None, shares[0])


def _aid_due(state: State, today: date) -> list[Order]:
    """The enacted ``production`` orders that send aid and arrive ``today``, in id order."""
    due = []
    for o in state.orders.values():
        if o.status is not OrderStatus.ENACTED:
            continue
        if rs.settled_on(o) + timedelta(AID_LEAD_DAYS) != today:
            continue
        try:
            if rs.resolver_for(state, o) != "production":
                continue
        except KeyError:
            continue
        if _aid(state, o) is not None:
            due.append(o)
    return sorted(due, key=lambda o: o.order_id)


def aid_shares(state: State, giver: EntityId, on: date) -> dict[EntityId, int]:
    """The aid share in per cent ``giver`` sends each nation under its enacted
    ``production`` orders settled on or before ``on``: the largest share per recipient."""
    out: dict[EntityId, int] = {}
    for o in sorted(state.orders.values(), key=lambda o: o.order_id):
        if o.status is not OrderStatus.ENACTED or rs.settled_on(o) > on:
            continue
        try:
            if rs.resolver_for(state, o) != "production":
                continue
        except KeyError:
            continue
        aid = _aid(state, o)
        if aid is not None and aid.giver == giver:
            out[aid.recipient] = max(out.get(aid.recipient, 0), aid.share_pct)
    return out


def _fund(state: State, giver: EntityId) -> int:
    """The giver's aid figure: its largest figure in ``AID_UNIT``; 0 when it has none.
    A share allocated from it is never larger, so the fund is the largest."""
    return max(
        (
            q.value
            for q in state.quantities.values()
            if q.unit == AID_UNIT
            and q.value is not None
            and q.owner is not None
            and polity_of(state, q.owner) == giver
        ),
        default=0,
    )


def _reaches(state: State, route: Feature, nation: EntityId) -> bool:
    """Whether one of the route's places lies in a territory ``nation`` holds."""
    for place in route.places:
        area = territory.area_of(state, place, Domain.LAND)
        if area is not None and territory.holder(state, area) == nation:
            return True
    return False


def _lost(state: State, aid: _Aid, today: date) -> float:
    """The share of the month's shipping lost on the aid's route: what the route lost over
    the shipping its nation holds (its lift pool), at most 1. Nothing is lost when no world
    route reaches the recipient, when the form names no route, or when the route's nation
    holds no shipping figure."""
    routes = (f for f in state.features.values() if f.kind is FeatureKind.ROUTE)
    if aid.route is None or not any(_reaches(state, r, aid.recipient) for r in routes):
        return 0.0
    board = state.map
    side = territory.nation(state, aid.route.side)
    pool = None if board is None or side is None else board.lift_pools.get(side)
    held = state.quantities[pool].value if pool is not None and pool in state.quantities else None
    if not held or held <= 0:
        return 0.0
    lost = shipping.losses(state, today).get(aid.route.feature_id, 0)
    return min(1.0, lost / held)


def _deliver(state: State, order: Order, today: date) -> list["rs.Change"]:
    """The aid ``order`` sends arriving ``today``: the recipient's output pool grows by the
    share's dollars at ``AID_USD_PER_POINT`` a point, less the route's loss share; the
    issuing seat gets one report."""
    aid = _aid(state, order)
    assert aid is not None
    lost = _lost(state, aid, today)
    points = _fund(state, aid.giver) * aid.share_pct / 100 / AID_USD_PER_POINT * (1 - lost)
    pools = state.economy.pools.get(aid.recipient, Pools())
    name = state.entities[aid.recipient].name
    out: list[rs.Change] = []
    if points > 0:
        out.append(
            ev.EconomySet(
                polity=aid.recipient,
                pools=pools.model_copy(update={"output": pools.output + points}),
                on=today,
            )
        )
    paper = _report(
        state,
        order,
        aid.giver,
        today,
        f"Aid arrives in {name}",
        [
            BodyField(label="Output", value=f"{points:.1f} points"),
            BodyField(label="Lost at sea", value=f"{round(100 * lost)} per cent"),
        ],
    )
    return out + ([paper] if paper is not None else [])


def _aid_lever(state: State, person: EntityId, asker: EntityId) -> tuple[Lever, ParamSpec] | None:
    """The aid form on ``person``'s card that can name ``asker``, and that parameter."""
    card = state.cards.get(person)
    for lever in card.levers if card is not None else ():
        if lever.resolver != "production" or not any(p.kind is ParamKind.INT for p in lever.params):
            continue
        for p in lever.params:
            if any(_polity(state, c) == asker for c in p.choices):
                return lever, p
    return None


def _asks(state: State, order: Order, asker: EntityId, giver: EntityId | None) -> bool:
    """Whether ``order`` asks ``giver`` for aid: the world routes it through a decision by
    a person of the giver's nation, which an order kept inside the asker's nation is not."""
    pipeline = state.pipelines.get(order.pipeline)
    return (
        giver is not None
        and giver != asker
        and pipeline is not None
        and any(
            s.kind is StepKind.DECISION and polity_of(state, s.person) == giver
            for s in pipeline.steps
        )
    )


def _asked(state: State, order: Order) -> list[ev.MandateIssued]:
    """With ``economy`` on, a request from a nation that another nation's aid form names
    raises its share on the agenda of each seat of that nation holding that form: an
    opportunity met by filing the form for the asker, due ``AID_ANSWER_DAYS`` later. An
    order is a request to the nations whose people decide a step of its pipeline. A full
    desk gets none; nothing waits on the answer."""
    if not economy.on(state) or _aid(state, order) is not None:
        return []
    asker = polity_of(state, state.seats[order.issuer].embodies)
    if asker is None:
        return []
    day = rs.settled_on(order)
    out = []
    for seat in sorted(actors.readers(state)):
        person = state.seats[seat].embodies
        found = _aid_lever(state, person, asker)
        if found is None or _desk_full(state, seat):
            continue
        if not _asks(state, order, asker, polity_of(state, person)):
            continue
        lever, param = found
        key = next(c for c in param.choices if _polity(state, c) == asker)
        form = lever.label or lever.name
        out.append(
            ev.MandateIssued(
                mandate=Mandate(
                    mandate_id=MandateId(
                        derived_id(state.campaign_id, "aid", order.order_id, seat)
                    ),
                    seat_id=seat,
                    kind=MandateKind.OPPORTUNITY,
                    text=f"{state.entities[asker].name} asks for aid: raise its share ({form}).",
                    condition=ActOf(person=person, lever=lever.name, params={param.name: key}),
                    issued=day,
                    expires=day + timedelta(days=AID_ANSWER_DAYS),
                    scope=private_to(seat),
                )
            )
        )
    return out


def _desk_full(state: State, seat: SeatId) -> bool:
    live = sum(
        m.seat_id == seat
        and m.status is MandateStatus.LIVE
        and m.mandate_id != opening_id(state.campaign_id, seat)
        for m in state.mandates.values()
    )
    return live >= MANDATE_CAP
