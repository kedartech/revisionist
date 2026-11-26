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
A form whose rule name is ``production`` and that is not an aid finding or an aid order
acts the same way when it names a force or a figure; one whose pipeline has a decision by
a person of another nation is a request that nation granted, and ``AID_LEAD_DAYS`` later
sends ``REQUEST_SHARE_PCT`` of that nation's aid fund to the asker (``_requested``); one
naming none of these mobilises: ``LEAD_DAYS`` later its nation spends ``STEP_MANPOWER``
manpower for ``MOBILISE_OUTPUT`` output (``_mobilised``). A ``production`` form that would
build on a day its nation holds less output than a step costs mobilises instead.
Each enacted order counts once: it is read only on its due day. The due orders of a day
are taken by settling day, then by what they name, then by id, so an earlier order spends
first; pools are read before the same day's first-of-the-month payment (``economy.walk``
runs after the day rules).

The rule name ``raising`` (RNC), with ``economy`` on too: an enacted form that names a
``kind`` and a ``place`` raises a new piece of that kind there, the kind's ``lead_days``
after the order left its last step. The place must be a base of the nation's own whose
domains take the kind's ``raised_at``, in a territory the nation holds, and in supply that
day. If both pools hold the kind's cost it is spent and the piece enters at strength 1,
named for its kind with the next number its nation has not used; the fold puts it under
the nation's command (``fold._commanded``). Where an enemy stands on that day, it arrives
at the nearest other base of the nation's own that would raise it, and nothing is raised
when there is none. One piece is raised at a place at a time: filing refuses a second
order while one is under way (``raise_refusal``, read by ``war_rules.order_refusal``), and
of two that are both enacted the earlier is the only one raised. Either way the issuing
seat gets one report that day.
"""

import math
import re
from datetime import date, timedelta
from typing import NamedTuple

from revisionist.core import events as ev
from revisionist.core.goals import ActOf
from revisionist.core.ids import (
    DocumentId,
    EntityId,
    FeatureId,
    MandateId,
    OrderId,
    PipelineId,
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
from revisionist.core.realism.geography import Feature, FeatureKind, in_play
from revisionist.core.realism.kinds import Domain, PieceKind
from revisionist.core.realism.land import allocate
from revisionist.core.realism.pipeline import Order, OrderStatus, StepKind
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import evacuation, shipping
from revisionist.core.realism.resolvers import production_stored as stored
from revisionist.core.realism.resolvers.shipping import shifted
from revisionist.core.realism.resolvers.votes import put
from revisionist.core.realism.territory import Base
from revisionist.core.realism.war import at_war, polity_of
from revisionist.core.state import Rule, State
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
MOBILISE_OUTPUT = 5  # [proposed]
"""Output one mobilisation raises, for ``STEP_MANPOWER`` manpower."""
REQUEST_SHARE_PCT = 10  # [proposed]
"""The share of the giver's aid fund a request it decided sends, in per cent."""

NOT_RAISED = "That kind of piece is not raised"
NO_BASE = "No base for that kind there"
NOT_YOURS = "The place is not yours"
NO_SUPPLY = "The place is out of supply"
BUSY = "A piece is already being raised there"
NO_ARRIVAL = "No base of yours to arrive at"


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


def _builds(state: State, order: Order) -> bool:
    """Whether a ``production`` order builds as the economy rule's forms do: it names a
    force or a figure, and is neither an aid finding nor an aid order."""
    if FORCE not in order.params and ADDS_TO not in order.params:
        return False
    return _aid(state, order) is None and not _finding(state, order)


def _finding(state: State, order: Order) -> bool:
    keys = _keys(state)
    if keys is None:
        return order.lever == stored.FINDING
    return any(f.form == order.lever for f in keys.findings)


def _giver(state: State, order: Order) -> EntityId | None:
    """The other nation whose person decides a step of the order's pipeline: the first in
    the pipeline's order; None when only the issuer's own nation decides it."""
    asker = polity_of(state, state.seats[order.issuer].embodies)
    pipeline = state.pipelines.get(order.pipeline)
    for step in pipeline.steps if pipeline is not None else ():
        nation = polity_of(state, step.person)
        if step.kind is StepKind.DECISION and nation is not None and nation != asker:
            return nation
    return None


def _requested(state: State, order: Order) -> "_Aid | None":
    """The aid a ``production`` request sends once the other nation deciding it has let it
    through: ``REQUEST_SHARE_PCT`` of that nation's fund to the asker. None for an order
    that builds, sends aid itself, is a finding, or that no other nation decides."""
    if FORCE in order.params or ADDS_TO in order.params or _finding(state, order):
        return None
    if raises(state, order) or _aid(state, order) is not None:
        return None
    asker = polity_of(state, state.seats[order.issuer].embodies)
    giver = _giver(state, order)
    if asker is None or giver is None:
        return None
    return _Aid(giver, asker, None, REQUEST_SHARE_PCT)


def _mobilises(state: State, order: Order) -> bool:
    """Whether a ``production`` order names nothing it builds, sends or asks for."""
    return (
        FORCE not in order.params
        and ADDS_TO not in order.params
        and not _finding(state, order)
        and _aid(state, order) is None
        and _giver(state, order) is None
    )


def _due(state: State, today: date) -> list[Order]:
    """The enacted ``economy`` orders whose step falls due ``today``, and the
    ``production`` orders that build or mobilise, earliest first."""
    due = []
    for o in state.orders.values():
        if (
            o.status is not OrderStatus.ENACTED
            or rs.settled_on(o) + timedelta(_lead(state, o)) != today
        ):
            continue
        if evacuation.is_evacuation(o):
            continue
        try:
            resolver = rs.resolver_for(state, o)
        except KeyError:
            continue
        if (
            resolver == "economy"
            or raises(state, o)
            or (resolver == "production" and (_builds(state, o) or _mobilises(state, o)))
        ):
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
    spent = pools.model_copy(
        update={"output": pools.output - STEP_COST, "manpower": pools.manpower - STEP_MANPOWER}
    )
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
        if raises(state, order):
            changes = _raise(state, order, today)
        elif rs.resolver_for(state, order) == "production" and (
            _mobilises(state, order) or _output_short(state, order)
        ):
            changes = _mobilised(state, order, today)
        else:
            changes = _build(state, order, today)
        out += changes
        state = _after(state, changes)
    for order in _aid_due(state, today):
        changes = _deliver(state, order, today)
        out += changes
        state = _after(state, changes)
    return (*out, *evacuation.on_day(state, today))


def _output_short(state: State, order: Order) -> bool:
    """Whether the issuer's nation holds less output than a step costs: a ``production``
    form that would build then mobilises instead."""
    nation = polity_of(state, state.seats[order.issuer].embodies)
    pools = state.economy.pools.get(nation, Pools()) if nation is not None else Pools()
    return pools.output < STEP_COST


def _mobilised(state: State, order: Order, today: date) -> list["rs.Change"]:
    """What one due mobilisation raises today: ``STEP_MANPOWER`` manpower spent for
    ``MOBILISE_OUTPUT`` output, and the report; only the report when the manpower pool is
    short."""
    nation = polity_of(state, state.seats[order.issuer].embodies)
    if nation is None:
        return []
    pools = state.economy.pools.get(nation, Pools())
    name = state.entities[nation].name
    if pools.manpower < STEP_MANPOWER:
        why = f"The manpower pool is short: {pools.manpower:g} of {STEP_MANPOWER}"
        rows = [BodyField(label="For", value=_clip(name)), BodyField(label="Why", value=_clip(why))]
        paper = _report(state, order, nation, today, "Production: nothing raised", rows)
        return [paper] if paper is not None else []
    raised = pools.model_copy(
        update={
            "output": pools.output + MOBILISE_OUTPUT,
            "manpower": pools.manpower - STEP_MANPOWER,
        }
    )
    rows = [
        BodyField(label="For", value=_clip(name)),
        BodyField(label="Raised", value=f"{MOBILISE_OUTPUT} output for {STEP_MANPOWER} manpower"),
    ]
    paper = _report(state, order, nation, today, "Production: output raised", rows)
    out: list[rs.Change] = [ev.EconomySet(polity=nation, pools=raised, on=today)]
    return out + ([paper] if paper is not None else [])


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


# --- Raising a new piece (RNC) ------------------------------------------------------------

KIND, PLACE = "kind", "place"
RAISED_TIER = 1  # [proposed] plan, RNC Defaults


def raising_on(state: State) -> bool:
    """Whether new pieces are raised in this game: the economy on, and ``raising`` too."""
    return economy.on(state) and Rule.RAISING in state.rules


def raising_form(state: State, seat: SeatId, lever: str) -> bool:
    """Whether ``lever`` on the seat's card is a form of the economy or of production."""
    held = state.seats.get(seat)
    card = state.cards.get(held.embodies) if held is not None else None
    found = next((x for x in card.levers if x.name == lever), None) if card else None
    return found is not None and found.resolver in ("economy", "production")


def raises(state: State, order: Order) -> bool:
    """Whether ``order`` raises a piece: the rule on, and an economy or production form
    that names a kind and a place."""
    return (
        raising_on(state)
        and KIND in order.params
        and PLACE in order.params
        and raising_form(state, order.issuer, order.lever)
    )


def raised_kind(state: State, key: object) -> PieceKind | None:
    """The world's kind ``key``, if it is raised: it has a cost, lead days and a base."""
    found = state.kinds.pieces.get(str(key)) if state.kinds is not None else None
    if found is None or found.cost is None or found.lead_days is None or found.raised_at is None:
        return None
    return found


def _lead(state: State, order: Order) -> int:
    """Days from the order leaving its last step to its day: a raising kind's own."""
    kind = raised_kind(state, order.params.get(KIND)) if raises(state, order) else None
    return kind.lead_days if kind is not None and kind.lead_days is not None else LEAD_DAYS


def raised_id(state: State, order_id: OrderId) -> FeatureId:
    """The id of the piece an order to raise brings in."""
    return FeatureId(derived_id(state.campaign_id, "raised", order_id))


def place_id(state: State, key: object) -> EntityId:
    """The place a form names by its world key."""
    return EntityId(object_id(state.campaign_id, "entity", str(key)))


def _own(state: State, nation: EntityId, base: Base) -> bool:
    """A base of the nation's own, in a territory it holds."""
    return (
        nation in base.sides
        and base.land is not None
        and territory.holder(state, base.land) == nation
    )


def _piece(
    state: State, order: Order, nation: EntityId, kind: PieceKind, at: EntityId, today: date
) -> Feature:
    """The piece ``order`` raises, standing at ``at``."""
    pattern = re.compile(rf"{re.escape(kind.name)} (\d+)")
    used = [
        int(m.group(1))
        for f in state.features.values()
        if territory.nation(state, f.side) == nation and (m := pattern.fullmatch(f.name))
    ]
    return Feature(
        feature_id=raised_id(state, order.order_id),
        kind=FeatureKind.PIECE,
        name=f"{kind.name} {max(used, default=0) + 1}",
        side=nation,
        tier=RAISED_TIER,
        places=(at,),
        as_of=today,
        piece=kind.key,
    )


def _site(
    state: State, order: Order, nation: EntityId, kind: PieceKind, today: date
) -> tuple[Base | None, str | None]:
    """The base the order's place is and why nothing is raised there (None when it can
    be): no base takes the kind, it is not the nation's own, or it is out of supply."""
    assert state.map is not None and kind.raised_at is not None
    place = place_id(state, order.params[PLACE])
    bases = [b for b in state.map.bases if b.place == place and kind.raised_at in b.domains]
    if not bases:
        return None, NO_BASE
    own = [b for b in bases if _own(state, nation, b)]
    if not own:
        return None, NOT_YOURS
    piece = _piece(state, order, nation, kind, own[0].place, today)
    if shipping.supplied(state, piece, today) is False:
        return None, NO_SUPPLY
    return own[0], None


def raise_day(state: State, order: Order) -> date:
    """The day an order to raise is decided: its kind's lead days after its last step."""
    return rs.settled_on(order) + timedelta(_lead(state, order))


def _same_place(state: State, order: Order, place: EntityId) -> bool:
    return raises(state, order) and place_id(state, order.params[PLACE]) == place


def being_raised(state: State, today: date) -> list[Order]:
    """The orders whose piece is being raised on ``today``, by order id: still moving, or
    enacted with their day not passed and their piece not entered."""
    return sorted(
        (
            o
            for o in state.orders.values()
            if raises(state, o)
            and (
                o.status is OrderStatus.MOVING
                or (
                    o.status is OrderStatus.ENACTED
                    and raise_day(state, o) >= today
                    and raised_id(state, o.order_id) not in state.features
                )
            )
        ),
        key=lambda o: o.order_id,
    )


def _under_way(state: State, place: EntityId, today: date) -> bool:
    """Whether a piece is being raised at ``place``."""
    return any(place_id(state, o.params[PLACE]) == place for o in being_raised(state, today))


def _behind(state: State, order: Order) -> bool:
    """Whether another enacted order for the same place, settled before it, was still
    being raised when ``order`` left its last step."""
    place, settled = place_id(state, order.params[PLACE]), rs.settled_on(order)
    return any(
        o.order_id != order.order_id
        and o.status is OrderStatus.ENACTED
        and _same_place(state, o, place)
        and (rs.settled_on(o), o.order_id) < (settled, order.order_id)
        and raise_day(state, o) >= settled
        for o in state.orders.values()
    )


def raise_refusal(state: State, seat: SeatId, lever: str, params: dict[str, str]) -> str:
    """Why an order to raise may not be filed now, in fixed words; empty when it may, and
    for every other order. The place's checks are the day's as they stand today, and a
    second order for a place where a piece is being raised is refused."""
    if not raising_on(state) or KIND not in params or PLACE not in params:
        return ""
    if not raising_form(state, seat, lever):
        return ""
    nation = polity_of(state, state.seats[seat].embodies)
    kind = raised_kind(state, params[KIND])
    today = state.in_world_date
    if nation is None or state.map is None or today is None:
        return ""
    if kind is None:
        return NOT_RAISED
    draft = Order(
        order_id=OrderId(derived_id(state.campaign_id, "raise-check", seat)),
        issuer=seat,
        lever=lever,
        pipeline=PipelineId("check"),
        params=dict(params),
        filed=today,
    )
    _, why = _site(state, draft, nation, kind, today)
    if why is not None:
        return why
    return BUSY if _under_way(state, place_id(state, params[PLACE]), today) else ""


def _enemy_at(state: State, nation: EntityId, base: Base, domain: str) -> bool:
    """Whether a force of a nation at war with ``nation`` stands where a piece of
    ``domain`` raised at ``base`` would."""
    areas = {base.land, base.area(domain)} - {None}
    for f in state.features.values():
        side = territory.nation(state, f.side)
        if not in_play(f) or not kinds.is_force(state, f) or side is None:
            continue
        if not at_war(state, nation, side):
            continue
        where = kinds.domain(state, f)
        if where is not None and territory.area_of(state, f.places[0], where) in areas:
            return True
    return False


def _arrival(
    state: State, order: Order, nation: EntityId, kind: PieceKind, site: Base, today: date
) -> Base | None:
    """Where the piece arrives: its place, or, where an enemy stands, the nearest other
    base of the nation's own that takes the kind, in supply and with no enemy; ties to the
    place whose id sorts first. None when there is no such base."""
    if not _enemy_at(state, nation, site, kind.domain):
        return site
    assert state.map is not None
    start = site.land or site.sea
    steps = territory.steps_from(state.map, "air", [start] if start is not None else [])
    open_ = [
        b
        for b in state.map.bases
        if b.place != site.place
        and kind.raised_at in b.domains
        and _own(state, nation, b)
        and not _enemy_at(state, nation, b, kind.domain)
        and shipping.supplied(state, _piece(state, order, nation, kind, b.place, today), today)
        is not False
    ]
    far = math.inf
    return min(
        open_,
        key=lambda b: (steps.get(b.land, far) if b.land else far, str(b.place)),
        default=None,
    )


def _cost_short(pools: Pools, kind: PieceKind) -> str | None:
    assert kind.cost is not None
    if pools.output < kind.cost.output:
        return f"The output pool is short: {pools.output:g} of {kind.cost.output}"
    if pools.manpower < kind.cost.manpower:
        return f"The manpower pool is short: {pools.manpower:g} of {kind.cost.manpower}"
    return None


def _raise(state: State, order: Order, today: date) -> list["rs.Change"]:
    """What one due order to raise does today: the cost spent, the new piece and the
    report; only the report when nothing is raised."""
    nation = polity_of(state, state.seats[order.issuer].embodies)
    if nation is None or state.map is None:
        return []
    place = state.entities.get(place_id(state, order.params[PLACE]))
    where = place.name if place is not None else str(order.params[PLACE])
    kind = raised_kind(state, order.params[KIND])
    what = kind.name if kind is not None else str(order.params[KIND])
    pools = state.economy.pools.get(nation, Pools())
    site, why = (None, NOT_RAISED) if kind is None else _site(state, order, nation, kind, today)
    if why is None and _behind(state, order):
        why = BUSY
    arrive = None
    if why is None and kind is not None and site is not None:
        arrive = _arrival(state, order, nation, kind, site, today)
        why = NO_ARRIVAL if arrive is None else _cost_short(pools, kind)
    if why is not None or kind is None or kind.cost is None or arrive is None:
        rows = [
            BodyField(label="For", value=_clip(what)),
            BodyField(label="At", value=_clip(where)),
            BodyField(label="Why", value=_clip(why or "")),
        ]
        paper = _report(state, order, nation, today, f"Raising: nothing raised at {where}", rows)
        return [paper] if paper is not None else []
    piece = _piece(state, order, nation, kind, arrive.place, today)
    cost = kind.cost
    spent = pools.model_copy(
        update={"output": pools.output - cost.output, "manpower": pools.manpower - cost.manpower}
    )
    rows = [
        BodyField(label="Kind", value=_clip(what)),
        BodyField(label="At", value=_clip(state.entities[arrive.place].name)),
        BodyField(label="Spent", value=f"{cost.output} output, {cost.manpower} manpower"),
    ]
    paper = _report(state, order, nation, today, f"Raised: {piece.name}", rows)
    out: list[rs.Change] = [ev.EconomySet(polity=nation, pools=spent, on=today), piece]
    return out + ([paper] if paper is not None else [])


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
    """The enacted ``production`` orders that send aid, or a request's, and arrive
    ``today``, in id order."""
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
        if _aid(state, o) is not None or _requested(state, o) is not None:
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
    aid = _aid(state, order) or _requested(state, order)
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
    if not economy.on(state) or _aid(state, order) is not None or raises(state, order):
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
