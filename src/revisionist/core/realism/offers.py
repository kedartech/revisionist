"""The priced move: an offer to a bloc, with a promise that comes due (PRC).

With ``offers`` on (and ``groups`` and ``laws``, which give the blocs and the measures), a
chamber's bloc may carry ``prices``: each a key, a sentence, a condition built from the
checks aims use, the days within which it must hold, the points it moves the bloc's yes
share by, and the support the bloc loses if it is unmet. The price is an item from that
closed list; nothing here reads free wording or calls a model.

A seat of the bloc's nation offers one bloc one price for one measure: a law the world
declares whose bill is on its way (an order carrying the law's key that has not settled).
The filing (``offer_made``) waits for the next day's batch, which settles every filing for
a bloc and a measure by content: a live offer already standing refuses them all, else the
one with the most points is taken, ties to the smaller price key, then the smaller seat
key, and the rest are refused. No filing time or append order enters the batch.

From the day it is taken, ``points`` returns the price's points for that bloc and measure,
and the votes rule adds them to the bloc's part of the count. The promise binds only if
the measure passes: when its bill settles, the offer lapses (nothing owed, no points) or
comes due on the day the measure passed plus the price's days. On that day the condition
is read from state: kept, and the bloc's support rises by ``KEPT_POINTS``; unmet, and it
falls by the price's loss, the cause recorded as a promise broken. Each step is an
``offer_settled``. An offer cannot be withdrawn once taken.

An offer and its outcome are sealed to the seats of the bloc's nation (``seen_by``).
"""

from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.goals import (
    AgreementInForce,
    AimCondition,
    HoldsOffice,
    Ordered,
    QuantityAt,
    leaves,
)
from revisionist.core.ids import EntityId, OrderId, SeatId, derived_id

if TYPE_CHECKING:
    from revisionist.core.events import GroupMoved, OfferMade, OfferSettled
    from revisionist.core.realism.laws import Law
    from revisionist.core.realism.pipeline import Order
    from revisionist.core.state import State, _World

KEPT_POINTS = 2  # [proposed] plan, PRC Defaults
"""The support a bloc gains when a promise made to it is kept."""
MAX_POINTS = 20
"""The most a price may move a bloc's yes share by, in points."""
MAX_DAYS = 366
"""The longest a price may give for its condition to hold, in world days."""

ACTED_ON = (Ordered, QuantityAt, HoldsOffice, AgreementInForce)
"""The checks an act changes: an order of a named effect kind, a quantity, an office held,
an agreement in force. A price's condition holds at least one."""

NOT_ON = "Offers to a bloc are not part of this game."
NOT_YOURS = "You can make an offer only to a bloc of your own nation."
NO_BLOC = "Your nation has no such bloc."
NO_PRICE = "That bloc has no such price."
NO_BILL = "That measure has no bill on its way."
LIVE = "That bloc already holds an offer on that measure."
FILED = "You have already made that offer."


class OffersError(ValueError):
    """An offer the rules cannot take, in the seat's words."""


class Price(Model):
    """One thing a bloc will take for its votes on a measure (PRC rule 1)."""

    key: Label
    sentence: str = Field(min_length=1, max_length=300)
    """What is promised, as the seat reads it."""
    condition: AimCondition
    """What must hold on the due day, by the checks aims use."""
    days: int = Field(ge=1, le=MAX_DAYS)
    """World days after the measure passes on which the condition is read."""
    points: int = Field(ge=1, le=MAX_POINTS)
    """Points the offer moves the bloc's yes share by."""
    loss: int = Field(ge=0, le=100)
    """Support the bloc loses when the promise is broken."""


def acted_on(price: Price) -> bool:
    """Whether the price's condition holds a check an act changes (rule 1)."""
    return any(isinstance(leaf, ACTED_ON) for leaf in leaves(price.condition))


class OfferStanding(StrEnum):
    """Where an offer stands."""

    FILED = "filed"
    """Made, waiting for its day's batch."""
    TAKEN = "taken"
    """Landed: its points count on the measure's vote."""
    REFUSED = "refused"
    """Another offer, or one already standing, holds the bloc on that measure."""
    LAPSED = "lapsed"
    """The measure did not pass: nothing is owed."""
    DUE = "due"
    """The measure passed: the promise comes due on the offer's due day."""
    KEPT = "kept"
    BROKEN = "broken"


LIVE_STANDINGS = frozenset({OfferStanding.TAKEN, OfferStanding.DUE})
"""An offer that holds its bloc on its measure."""
NEXT: dict[OfferStanding, frozenset[OfferStanding]] = {
    OfferStanding.FILED: frozenset(
        {OfferStanding.TAKEN, OfferStanding.REFUSED, OfferStanding.LAPSED}
    ),
    OfferStanding.TAKEN: frozenset({OfferStanding.DUE, OfferStanding.LAPSED}),
    OfferStanding.DUE: frozenset({OfferStanding.KEPT, OfferStanding.BROKEN}),
}
"""Where an offer may go from where it stands."""


class PricedOffer(Model):
    """One seat's offer of one price to one bloc for one measure."""

    offer_id: Label
    seat: SeatId
    nation: EntityId
    bloc: Label
    measure: Label
    """The key of the law the bill carries."""
    price: Label
    bill: OrderId
    """The bill on its way when the offer was made."""
    filed: date
    standing: OfferStanding = OfferStanding.FILED
    on: date | None = None
    """The world day it last moved; None while filed."""
    due: date | None = None
    """The day the promise is read; set when the measure passes."""

    @model_validator(mode="after")
    def _shape(self) -> "PricedOffer":
        if (self.on is None) != (self.standing is OfferStanding.FILED):
            raise ValueError("an offer carries the day it moved once it has moved")
        owed = self.standing in (OfferStanding.DUE, OfferStanding.KEPT, OfferStanding.BROKEN)
        if (self.due is not None) != owed:
            raise ValueError("an offer has a due day once, and only once, its measure passed")
        return self


# --- reading ------------------------------------------------------------------------


def on(state: "_World") -> bool:
    """Whether offers act in this game: the ``offers`` rule on."""
    from revisionist.core.state import Rule

    return Rule.OFFERS in getattr(state, "rules", frozenset())


def price(state: "State", nation: EntityId, bloc: str, key: str) -> Price | None:
    from revisionist.core.realism import groups

    found = groups.group(state, nation, bloc)
    if found is None:
        return None
    return next((p for p in found.prices if p.key == key), None)


def law(state: "State", nation: EntityId, measure: str) -> "Law | None":
    """The law ``measure`` names, binding ``nation``; None when the world has none."""
    return next((x for x in state.laws if x.key == measure and x.nation == nation), None)


def _bill_key(order: "Order") -> str | None:
    from revisionist.core.realism.resolvers.votes import measure_key

    if order.measure is not None:
        return measure_key(order.measure)
    bill = order.params.get("bill")
    return None if bill is None else str(bill)


def bill(state: "State", measure: str) -> "Order | None":
    """The bill on its way for ``measure``: the first unsettled order, by id, carrying its
    key; None when there is none."""
    from revisionist.core.realism.pipeline import OrderStatus

    moving = (
        o
        for _, o in sorted(state.orders.items())
        if o.status is OrderStatus.MOVING and _bill_key(o) == measure
    )
    return next(moving, None)


def live(state: "_World", nation: EntityId, bloc: str, measure: str) -> PricedOffer | None:
    """The offer that holds ``bloc`` on ``measure``, if one does."""
    return next(
        (
            o
            for o in state.offers
            if (o.nation, o.bloc, o.measure) == (nation, bloc, measure)
            and o.standing in LIVE_STANDINGS
        ),
        None,
    )


def points(state: "State", nation: EntityId, bloc: str, measure: str) -> int:
    """The points ``bloc`` of ``nation`` moves its yes share by on ``measure`` for the
    offer taken on it (rule 3): the price's, from the day the offer lands until the
    measure is decided; 0 with none, or with ``offers`` off."""
    if not on(state):
        return 0
    found = live(state, nation, bloc, measure)
    if found is None or found.standing is not OfferStanding.TAKEN:
        return 0
    held = price(state, nation, bloc, found.price)
    return 0 if held is None else held.points


def seen_by(state: "State", seat: SeatId) -> tuple[PricedOffer, ...]:
    """The offers ``seat`` sees: those to its own nation's blocs (rule 5)."""
    from revisionist.core.realism.war import polity_of

    me = state.seats.get(seat)
    own = polity_of(state, me.embodies) if me is not None else None
    return tuple(o for o in state.offers if own is not None and o.nation == own)


# --- filing ---------------------------------------------------------------------------


def offer_id(state: "State", seat: SeatId, bloc: str, measure: str, key: str, day: date) -> str:
    return derived_id(state.campaign_id, "offer", seat, bloc, measure, key, day.isoformat())


def offer(
    state: "State", seat: SeatId, bloc: str, measure: str, key: str, day: date
) -> "OfferMade":
    """The ``offer_made`` for ``seat``'s offer of price ``key`` to ``bloc`` for ``measure``
    on world day ``day`` (rule 2). Raises ``OffersError`` in the seat's words when the rule
    is off, the bloc is not of the seat's nation, the price or the bill is not there, an
    offer already holds the bloc on the measure, or the seat made this offer today."""
    from revisionist.core import events as ev
    from revisionist.core.realism import groups
    from revisionist.core.realism.war import polity_of

    if not on(state) or not groups.on(state):
        raise OffersError(NOT_ON)
    me = state.seats.get(seat)
    nation = polity_of(state, me.embodies) if me is not None else None
    if nation is None:
        raise OffersError(NOT_YOURS)
    found = groups.group(state, nation, bloc)
    if found is None or found.chamber is None:
        raise OffersError(NO_BLOC)
    if price(state, nation, bloc, key) is None:
        raise OffersError(NO_PRICE)
    carried = bill(state, measure) if law(state, nation, measure) is not None else None
    if carried is None:
        raise OffersError(NO_BILL)
    if live(state, nation, bloc, measure) is not None:
        raise OffersError(LIVE)
    made_id = offer_id(state, seat, bloc, measure, key, day)
    if any(o.offer_id == made_id for o in state.offers):
        raise OffersError(FILED)
    return ev.OfferMade(
        offer=PricedOffer(
            offer_id=made_id,
            seat=seat,
            nation=nation,
            bloc=bloc,
            measure=measure,
            price=key,
            bill=carried.order_id,
            filed=day,
        )
    )


def _settled(
    found: PricedOffer, standing: OfferStanding, day: date, due: date | None = None
) -> "OfferSettled":
    from revisionist.core import events as ev

    return ev.OfferSettled(offer_id=found.offer_id, standing=standing, on=day, due=due)


def _chosen(state: "State", filed: list[PricedOffer]) -> PricedOffer:
    """The filing a batch takes: the most points, then the smaller price key, then the
    smaller seat key, then the smaller offer id."""

    def held(o: PricedOffer) -> int:
        found = price(state, o.nation, o.bloc, o.price)
        return 0 if found is None else found.points

    return min(filed, key=lambda o: (-held(o), o.price, o.seat, o.offer_id))


def batch(state: "State", day: date) -> list["OfferSettled"]:
    """The day's filings, settled by content (rule 2): for each bloc and measure, by
    nation, bloc and measure, every filing made on or before ``day`` is refused while an
    offer already holds the bloc on the measure, lapses when its bill has settled, and
    otherwise one is taken and the rest refused."""
    if not on(state):
        return []
    pending: dict[tuple[EntityId, str, str], list[PricedOffer]] = {}
    for o in state.offers:
        if o.standing is OfferStanding.FILED and o.filed <= day:
            pending.setdefault((o.nation, o.bloc, o.measure), []).append(o)
    out: list[OfferSettled] = []
    for (nation, bloc, measure), filed in sorted(pending.items()):
        filed.sort(key=lambda o: o.offer_id)
        if live(state, nation, bloc, measure) is not None:
            out += [_settled(o, OfferStanding.REFUSED, day) for o in filed]
            continue
        moving = bill(state, measure)
        open_ = [o for o in filed if moving is not None and o.bill == moving.order_id]
        out += [_settled(o, OfferStanding.LAPSED, day) for o in filed if o not in open_]
        if not open_:
            continue
        taken = _chosen(state, open_)
        out += [
            _settled(o, OfferStanding.TAKEN if o is taken else OfferStanding.REFUSED, day)
            for o in open_
        ]
    return out


# --- the measure decided, the promise due ---------------------------------------------


def _decided(state: "State", found: PricedOffer, day: date) -> "OfferSettled | None":
    """A taken offer whose bill has settled: due the day the measure passed plus the
    price's days, or lapsed; None while the bill is on its way."""
    from revisionist.core.realism.pipeline import OrderStatus

    order = state.orders.get(found.bill)
    if order is not None and order.status is OrderStatus.MOVING:
        return None
    measure = law(state, found.nation, found.measure)
    flag = None if measure is None else state.quantities.get(measure.passed)
    held = price(state, found.nation, found.bloc, found.price)
    passed = (
        order is not None
        and order.status is OrderStatus.ENACTED
        and flag is not None
        and flag.value == 1
    )
    if not passed or flag is None or held is None:
        return _settled(found, OfferStanding.LAPSED, day)
    return _settled(found, OfferStanding.DUE, day, due=flag.as_of + timedelta(days=held.days))


def _judged(
    state: "State", found: PricedOffer, day: date, now: dict[tuple[EntityId, str], int]
) -> list["OfferSettled | GroupMoved"]:
    """A promise on its due day, read from state (rule 4): kept, and the bloc gains
    ``KEPT_POINTS``; else broken, and it loses the price's loss. The bloc moves from its
    support in ``now`` when an earlier promise moved it that day, and ``now`` is updated."""
    from revisionist.core.goals import goal_met
    from revisionist.core.realism import groups

    held = price(state, found.nation, found.bloc, found.price)
    if held is None:
        return []
    kept = goal_met(state, held.condition)
    out: list[OfferSettled | GroupMoved] = [
        _settled(found, OfferStanding.KEPT if kept else OfferStanding.BROKEN, day, due=found.due)
    ]
    change = KEPT_POINTS if kept else -held.loss
    cause = groups.Cause.PROMISE_KEPT if kept else groups.Cause.PROMISE_BROKEN
    bloc = (found.nation, found.bloc)
    was = now.get(bloc, groups.support(state, *bloc))
    if change and was is not None:
        moved = groups._moved(was, found.nation, found.bloc, change, cause, day)
        now[bloc] = moved.support
        out.append(moved)
    return out


def walk(state: "State", day: date) -> list["OfferSettled | GroupMoved"]:
    """On world day ``day``, in offer id order: each taken offer whose bill has settled
    comes due or lapses, and each promise whose due day has come is judged, each bloc's
    support carried from one promise to the next."""
    if not on(state):
        return []
    out: list[OfferSettled | GroupMoved] = []
    now: dict[tuple[EntityId, str], int] = {}
    for found in sorted(state.offers, key=lambda o: o.offer_id):
        if found.standing is OfferStanding.TAKEN:
            decided = _decided(state, found, day)
            if decided is not None:
                out.append(decided)
            if decided is not None and decided.due is not None and decided.due <= day:
                out += _judged(state, found.model_copy(update={"due": decided.due}), day, now)
        elif found.standing is OfferStanding.DUE and found.due is not None and found.due <= day:
            out += _judged(state, found, day, now)
    return out


__all__ = [
    "ACTED_ON",
    "KEPT_POINTS",
    "LIVE_STANDINGS",
    "MAX_DAYS",
    "MAX_POINTS",
    "NEXT",
    "OfferStanding",
    "OffersError",
    "Price",
    "PricedOffer",
    "acted_on",
    "batch",
    "bill",
    "law",
    "live",
    "offer",
    "offer_id",
    "on",
    "points",
    "price",
    "seen_by",
    "walk",
]
