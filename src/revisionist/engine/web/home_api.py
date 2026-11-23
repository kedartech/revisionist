"""Groups at home and the floor as the seat sees them (GPD).

``block`` is the ``home`` block with ``groups`` on. For the seat's own nation: each group
at home with its support, what last moved it and when, and what it feeds; each chamber its
blocs sit in, with their seats and, for each measure the seat has on its way, the count by
bloc as the votes rule would tally it today (``votes.floor_counts``, never a count of its
own) and the yeas that carry each vote; the nation's themes and its standing at home as a
figure. For every nation: its standing as one of five public bands. The groups, chambers
and themes are read from the seat's ``View``, which holds its own nation's groups and no
other's, so no other nation's group can reach the payload; the bands are read from the
truth and sent as bands only.

With ``offers`` on (PRR), the block also lists each law of the seat's nation whose bill is
on its way, with each bloc that votes on it, the prices it would take and the offer that
holds it, read from the seat's view; and the offers the seat itself made, each with its
due day once its measure has passed. The count on the floor already carries a taken
offer's points (``votes.bloc_counts``).
"""

from collections.abc import Iterable
from typing import Literal

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism import groups, offers
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import resolver_for, votes
from revisionist.core.state import State, View
from revisionist.engine.web import economy_api
from revisionist.engine.web.realism_api import (
    BlocCount,
    FloorBloc,
    FloorChamber,
    FloorVote,
    GroupMove,
    HomeBlock,
    HomeGroup,
    HomeTheme,
    LiveOffer,
    NationStanding,
    OfferBloc,
    OfferMeasure,
    OfferPrice,
    OfferPromise,
    OpenMeasure,
    StandingVote,
)

Band = Literal["collapsing", "shaken", "steady", "firm", "united"]


BANDS: tuple[tuple[float, Band], ...] = (
    (80, "united"),
    (60, "firm"),
    (40, "steady"),
    (20, "shaken"),
    (0, "collapsing"),
)
"""[proposed] plan, GPD Defaults: the five public bands of a nation's standing at home,
each from its lower bound."""


OFFERED = "Offered to {bloc} for {measure}: {sentence}"  # [proposed]
OFFER_HELD = "Your offer to {bloc}: {sentence}"  # [proposed]


def standing_band(figure: float) -> Band:
    """The public band a standing at home of ``figure`` (0 to 100) falls in."""
    return next(band for low, band in BANDS if figure >= low)


def carries(voting: int) -> int:
    """The yeas that carry a vote of ``voting`` members: the votes rule passes a vote on
    more yeas than nays among those voting (``votes.by_groups``)."""
    return voting // 2 + 1


def _last_moved(events: Iterable[Event], own: EntityId) -> dict[str, GroupMove]:
    """What last moved each of ``own``'s groups, by group key: a move the clamp held to
    nothing moved nothing."""
    out: dict[str, GroupMove] = {}
    for e in events:
        p = e.payload
        if isinstance(p, ev.GroupMoved) and p.polity == own and p.change:
            out[p.group] = GroupMove(cause=p.cause.value, change=p.change, on=p.on.isoformat())
    return out


def _open_measures(state: State, view: View, own: EntityId) -> list[tuple[Order, str, str]]:
    """The seat's own orders on their way that the votes rule tallies, with each one's
    measure key and title."""
    out: list[tuple[Order, str, str]] = []
    for o in sorted(view.orders.values(), key=lambda o: (o.filed, o.order_id)):
        if o.status is not OrderStatus.MOVING or resolver_for(state, o) != "votes":
            continue
        if o.measure is not None:
            out.append((o, votes.measure_key(o.measure), o.measure.title))
        elif (bill := o.params.get("bill")) is not None:
            out.append((o, str(bill), str(bill).replace("_", " ").capitalize()))
    return out


def _floor_votes(
    state: State, own: EntityId, order: Order, key: str
) -> list[tuple[str, FloorVote]]:
    """Each (chamber, vote) ``own``'s blocs cast on measure ``key`` for ``order``, counted
    by bloc as the votes rule would tally it on ``state`` (``votes.floor_counts``)."""
    out: list[tuple[str, FloorVote]] = []
    for chamber, vote, parts in votes.floor_counts(state, own, order, key, order.measure):
        yeas, nays = sum(y for _, y, _ in parts), sum(n for _, _, n in parts)
        out.append(
            (
                chamber,
                FloorVote(
                    vote=vote,
                    yeas=yeas,
                    nays=nays,
                    blocs=[BlocCount(group=g, yeas=y, nays=n) for g, y, n in parts],
                    carries=carries(yeas + nays),
                ),
            )
        )
    return out


def _chambers(state: State, view: View, own: EntityId) -> list[FloorChamber]:
    blocs = [g for g in groups.of(view, own) if g.chamber is not None and g.seats is not None]
    chambers = list(dict.fromkeys(str(g.chamber) for g in blocs))
    measures: dict[str, list[OpenMeasure]] = {key: [] for key in chambers}
    for order, key, title in _open_measures(state, view, own):
        counted: dict[str, list[FloorVote]] = {}
        for chamber, vote in _floor_votes(state, own, order, key):
            counted.setdefault(chamber, []).append(vote)
        for chamber, found in counted.items():
            measures[chamber].append(
                OpenMeasure(order_id=order.order_id, key=key, title=title, votes=found)
            )
    return [
        FloorChamber(
            key=chamber,
            blocs=[
                FloorBloc(
                    group=g.key,
                    name=g.name,
                    seats=g.seats or 0,
                    support=groups.support(view, own, g.key) or 0,
                )
                for g in blocs
                if g.chamber == chamber
            ],
            measures=measures[chamber],
        )
        for chamber in chambers
    ]


def _standings(state: State, own: EntityId) -> list[NationStanding]:
    """Every nation's public band, by name: read from the truth, sent as a band only."""
    polities = [k for k, e in state.entities.items() if e.kind is EntityKind.POLITY]
    out: list[NationStanding] = []
    for p in polities:
        figure = groups.home_standing(state, p)
        band = standing_band(figure) if figure is not None else None
        out.append(NationStanding(nation=economy_api.nation(state, own, p), band=band))
    return sorted(out, key=lambda s: (s["nation"]["name"], s["nation"]["key"]))


def _price(world: State | View, nation: EntityId, bloc: str, key: str) -> offers.Price | None:
    found = groups.group(world, nation, bloc)
    return None if found is None else next((p for p in found.prices if p.key == key), None)


def _title(world: State | View, nation: EntityId, measure: str) -> str:
    law = next((x for x in world.laws if x.key == measure and x.nation == nation), None)
    return law.title if law is not None else measure


def _on_offer(state: State, view: View, own: EntityId) -> list[OfferMeasure]:
    """Each law of ``own`` whose bill is on its way (``offers.bill``, as filing reads
    it), with each bloc that votes on it: the prices it would take and the offer that
    holds it, read from the seat's view."""
    out: list[OfferMeasure] = []
    for law in sorted(view.laws, key=lambda x: x.key):
        if law.nation != own or offers.bill(state, law.key) is None:
            continue
        blocs = [
            OfferBloc(
                group=g.key,
                name=g.name,
                prices=[
                    OfferPrice(
                        key=p.key, sentence=p.sentence, points=p.points, days=p.days, loss=p.loss
                    )
                    for p in g.prices
                ],
                live=_live(view, own, g.key, law.key),
            )
            for g in groups.of(view, own)
            if g.chamber is not None and (law.key in g.votes or g.vote_default)
        ]
        out.append(OfferMeasure(key=law.key, title=law.title, blocs=blocs))
    return out


def _live(view: View, own: EntityId, bloc: str, measure: str) -> LiveOffer | None:
    found = offers.live(view, own, bloc, measure)
    held = None if found is None else _price(view, own, bloc, found.price)
    if found is None or held is None:
        return None
    return LiveOffer(price=found.price, points=held.points, mine=found.seat == view.viewer)


def promises(view: View) -> list[OfferPromise]:
    """The offers the seat itself made, by filing day and id."""
    out: list[OfferPromise] = []
    mine = [o for o in view.offers if o.seat == view.viewer]
    for o in sorted(mine, key=lambda o: (o.filed, o.offer_id)):
        held = _price(view, o.nation, o.bloc, o.price)
        bloc = groups.group(view, o.nation, o.bloc)
        out.append(
            OfferPromise(
                offer_id=o.offer_id,
                group=o.bloc,
                name=bloc.name if bloc is not None else o.bloc,
                measure=o.measure,
                title=_title(view, o.nation, o.measure),
                price=o.price,
                sentence=held.sentence if held is not None else o.price,
                standing=o.standing.value,
                filed=o.filed.isoformat(),
                due=o.due.isoformat() if o.due is not None else None,
            )
        )
    return out


def _told(state: State, nation: EntityId, bloc: str, key: str) -> tuple[str, str]:
    """The bloc's name and the price's sentence; ``ValueError`` in the seat's words."""
    found = groups.group(state, nation, bloc)
    held = _price(state, nation, bloc, key)
    if found is None or held is None:
        raise ValueError(offers.NO_PRICE)
    return found.name, held.sentence


def offered(state: State, made: offers.PricedOffer) -> str:
    """The reply to an ``offer`` filed: the bloc, the measure and the price."""
    name, sentence = _told(state, made.nation, made.bloc, made.price)
    title = _title(state, made.nation, made.measure)
    return OFFERED.format(bloc=name, measure=title, sentence=sentence)


def offer_label(state: State, seat: SeatId, bloc: str, measure: str, key: str) -> str:
    """The label of an offer held for the next wake. Raises ``ValueError`` with the seat's
    words as filing it now would."""
    today = state.in_world_date
    if today is None:
        raise ValueError(offers.NOT_ON)
    made = offers.offer(state, seat, bloc, measure, key, today).offer
    name, sentence = _told(state, made.nation, bloc, key)
    return OFFER_HELD.format(bloc=name, sentence=sentence)


def would_stand(
    state: State, seat: SeatId, bloc: str, measure: str, key: str
) -> list[StandingVote]:
    """Each vote of ``measure``'s bill counted as it would stand with the seat's offer of
    price ``key`` to ``bloc`` landed: the floor count (``votes.floor_counts``) on the game
    with that offer taken today, so the points are the rule's and never a sum of the
    client's. Raises ``offers.OffersError`` as filing the offer would."""
    today = state.in_world_date
    if today is None:
        raise offers.OffersError(offers.NOT_ON)
    made = offers.offer(state, seat, bloc, measure, key, today).offer
    order = offers.bill(state, measure)
    if order is None:
        raise offers.OffersError(offers.NO_BILL)
    taken = made.model_copy(update={"standing": offers.OfferStanding.TAKEN, "on": today})
    landed = state.model_copy(update={"offers": (*state.offers, taken)})
    return [
        StandingVote(chamber=chamber, **vote)
        for chamber, vote in _floor_votes(landed, made.nation, order, measure)
    ]


def block(state: State, view: View, events: Iterable[Event] = ()) -> HomeBlock | None:
    """The ``home`` block with ``groups`` on: the seat's own nation's groups, its chambers
    with the seat's open measures counted by bloc, its themes, its standing as a figure,
    and every nation's standing as a band; with ``offers`` on, each measure on its way with
    what its blocs would take, and the seat's own promises. The groups, chambers, themes
    and offers are read from the seat's ``View``, which holds its own nation's and no
    other's. None with the rule off and for a seat of no nation."""
    own = economy_api.own_nation(view)
    today = view.in_world_date
    if not groups.on(state) or own is None or today is None:
        return None
    moved = _last_moved(events, own)
    out = HomeBlock(
        day=today.isoformat(),
        nation=economy_api.nation(state, own, own),
        groups=[
            HomeGroup(
                key=g.key,
                name=g.name,
                kind=g.kind,
                support=groups.support(view, own, g.key) or 0,
                last_moved=moved.get(g.key),
                feeds={f.value: w for f, w in g.feeds.items()},
            )
            for g in groups.of(view, own)
        ],
        chambers=_chambers(state, view, own),
        themes=[
            HomeTheme(key=t.key, name=t.name, moves=dict(t.moves))
            for t in view.groups.themes.get(own, ())
        ],
        # read from state: a view holds no rules, and home_standing reads the economy rule
        standing=groups.home_standing(state, own),
        standings=_standings(state, own),
    )
    if offers.on(state):
        out["offers"] = _on_offer(state, view, own)
        out["promises"] = promises(view)
    return out
