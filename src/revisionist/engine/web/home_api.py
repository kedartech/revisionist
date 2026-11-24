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

What moved since the seat's last wake (HFR): its last wake is its player's last commit.
Each group lists every move logged since, each worded from the move alone, and the block
lists one line a group, heaviest net change first. Each vote of a measure on its way
carries the count the votes rule gave it on the log as it stood at that commit, beside
today's. Each place of political weight of the nation is listed with the holder and the
threat its area shows on the seat's map.

A capital's live questions: ``capitals`` lists every nation's capital, the seat's own
first. Its own holds one line a live question of its nation, each naming the shape of who
decides it (a body, a council, one person), its day and where its data already sits in the
payload; another nation's holds only what its public record gives. The list is read from
what the seat is sent and the public news, so it carries nothing new.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Literal, cast

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.fold import replay
from revisionist.core.ids import EntityId, OrderId, SeatId
from revisionist.core.ontology import Controller, EntityKind
from revisionist.core.project import at_post, project
from revisionist.core.realism import elections, groups, locks, offers, office, posts
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import resolver_for, votes
from revisionist.core.state import QuestionCause, Removal, RemovalWay, State, View
from revisionist.engine.web import economy_api
from revisionist.engine.web.realism_api import (
    BaseUnder,
    BlocCount,
    CapitalAt,
    CapitalDecider,
    CapitalKind,
    CapitalLine,
    CapitalQuestion,
    CapitalShape,
    ElectionAhead,
    ElectionBloc,
    ElectionChamber,
    FloorBloc,
    FloorChamber,
    FloorVote,
    FootingLine,
    GroupMove,
    HomeBlock,
    HomeGroup,
    HomeMove,
    HomeMoved,
    HomePlace,
    HomeTheme,
    LiveOffer,
    MapArea,
    MapPlace,
    NationStanding,
    OfferBloc,
    OfferMeasure,
    OfferPrice,
    OfferPromise,
    OfficeCount,
    OfficeQuestionLine,
    OfficeResult,
    OfficeWay,
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


RESULT_DAYS = office.REST_DAYS
"""[proposed] World days an office question's result stays in the home block after its
sitting, so the seats of the nation read it in place of the question."""


OFFERED = "Offered to {bloc} for {measure}: {sentence}"  # [proposed]
OFFER_HELD = "Your offer to {bloc}: {sentence}"  # [proposed]

WHY: dict[str, str] = {
    "battle_won": "a battle won",
    "battle_lost": "a battle lost",
    "territory_taken": "territory taken",
    "territory_lost": "territory lost",
    "capital_threatened": "the capital threatened",
    "losses_at_sea": "shipping lost at sea",
    "agreement_broken": "an agreement broken",
    "measure_passed": "a measure passed",
    "war_declared": "war declared",
    "daily_life_passed": "a measure touching daily life passed",
    "writing": "a statement",
    "drift": "the weekly drift",
    "offer_taken": "an offer taken",
    "promise_kept": "a promise kept",
    "promise_broken": "a promise broken",
    "battle_losses": "battle losses reported",
    "losses_felt": "earlier battle losses felt at home",
    "losses_halved": "losses counted at half after a battle won",
    "place_lost": "a place of weight lost in battle",
    "place_abandoned": "a place of weight abandoned",
    "place_retaken": "a place of weight retaken",
}
"""[proposed] each cause a group moves by, in plain words."""

MOVED_LINE = "{name} {change:+d}: {why}"  # [proposed]
MORE = " and {n} more"  # [proposed]


def standing_band(figure: float) -> Band:
    """The public band a standing at home of ``figure`` (0 to 100) falls in."""
    return next(band for low, band in BANDS if figure >= low)


def carries(voting: int) -> int:
    """The yeas that carry a vote of ``voting`` members: the votes rule passes a vote on
    more yeas than nays among those voting (``votes.by_groups``)."""
    return voting // 2 + 1


Counts = dict[tuple[str, str], tuple[list[int], dict[str, list[int]]]]
"""Each vote's yeas and nays at the seat's last wake, whole and by bloc (``_then``)."""


def last_wake(events: Sequence[Event], seat: SeatId, person: EntityId) -> int | None:
    """The index in ``events`` of the seat's last wake: its player's last commit since a
    player took ``person`` up, as the wake report counts it. None while it has none."""
    out: int | None = None
    for i, e in enumerate(events):
        p = e.payload
        if isinstance(p, ev.SeatHandover):
            if p.entity_id == person and p.controller is Controller.HUMAN:
                out = None
        elif isinstance(p, ev.WakeCommitted) and p.seat_id == seat and not p.by_aide:
            out = i
    return out


REACH: dict[str, Literal["felt", "reported"]] = {
    "losses_felt": "felt",
    "losses_halved": "reported",
    "battle_losses": "reported",
    "writing": "reported",
    "offer_taken": "reported",
    "promise_kept": "reported",
    "promise_broken": "reported",
    "drift": "felt",
}
"""[proposed] how a move whose cause is not a classed happening reached the public: the
felt share of battle losses lands as ``losses_felt``, their reported share and the
winner's correction by report, a statement, an offer and a promise by report, and the
weekly drift as the mood at home."""


def reach(view: View, cause: str) -> Literal["felt", "reported"]:
    """How a move reached the public, felt or reported: a happening's class as the seat
    holds it from its own nation's groups (``groups.cls`` where it holds none), else
    ``REACH``."""
    if cause in REACH:
        return REACH[cause]
    happening = groups.Happening(cause)
    # A view carries no rules, so ``groups.cls`` on a view never reads the world's classes;
    # the seat holds its own nation's classes (``groups.seen_by``), empty with the rule off.
    found = view.groups.classes.get(happening) or groups.cls(view, happening)
    return "felt" if found.reach is groups.Class.FELT else "reported"


def _since(
    view: View, events: Sequence[Event], own: EntityId, wake: int | None
) -> dict[str, list[HomeMove]]:
    """Every move of ``own``'s groups logged after index ``wake``, by group key: a move
    the clamp held to nothing moved nothing."""
    out: dict[str, list[HomeMove]] = {}
    for e in events[0 if wake is None else wake + 1 :]:
        p = e.payload
        if isinstance(p, ev.GroupMoved) and p.polity == own and p.change:
            out.setdefault(p.group, []).append(
                HomeMove(
                    cause=p.cause.value,
                    change=p.change,
                    on=p.on.isoformat(),
                    why=WHY[p.cause.value],
                    reach=reach(view, p.cause.value),
                )
            )
    return out


def _moved(view: View, own: EntityId, since: dict[str, list[HomeMove]]) -> list[HomeMoved]:
    """One line a group that moved, heaviest net change first, the heaviest move named."""
    out: list[HomeMoved] = []
    for g in groups.of(view, own):
        moves = since.get(g.key)
        if not moves:
            continue
        net = sum(m["change"] for m in moves)
        lead = max(moves, key=lambda m: abs(m["change"]))
        line = MOVED_LINE.format(name=g.name, change=net, why=lead["why"])
        if len(moves) > 1:
            line += MORE.format(n=len(moves) - 1)
        out.append(HomeMoved(group=g.key, name=g.name, change=net, line=line))
    return sorted(out, key=lambda m: -abs(m["change"]))


def _places(state: State, view: View, own: EntityId, areas: Sequence[MapArea]) -> list[HomePlace]:
    """Each weighted place of ``own``, with the holder and the threat its area shows on
    the seat's map; a place whose area the map does not show is left out."""
    shown = {a["key"]: a for a in areas}
    board = state.map
    keys = {t.area: t.key for t in board.territories} if board is not None else {}
    out: list[HomePlace] = []
    for place in view.groups.places:
        area = shown.get(keys.get(place.territory, ""))
        if place.nation != own or area is None:
            continue
        threatened = area.get("falling") is not None or bool(area.get("threatened_from"))
        out.append(
            HomePlace(
                key=area["key"], name=area["name"], holder=area["holder"], threatened=threatened
            )
        )
    return out


def _then(events: Sequence[Event], wake: int | None, seat: SeatId, own: EntityId) -> Counts:
    """Each vote's count by bloc on the log as it stood at the seat's last wake, by order
    and vote: the same tally ``_chambers`` gives today, run on the state replayed to
    there. Empty while the seat has had no wake."""
    if wake is None:
        return {}
    state = replay(events[: wake + 1])
    out: Counts = {}
    for chamber in _chambers(state, project(state, seat), own, {}):
        for measure in chamber["measures"]:
            for vote in measure["votes"]:
                out[(measure["order_id"], vote["vote"])] = (
                    [vote["yeas"], vote["nays"]],
                    {b["group"]: [b["yeas"], b["nays"]] for b in vote["blocs"]},
                )
    return out


def _last_moved(events: Iterable[Event], own: EntityId) -> dict[str, GroupMove]:
    """What last moved each of ``own``'s groups, by group key: a move the clamp held to
    nothing moved nothing."""
    out: dict[str, GroupMove] = {}
    for e in events:
        p = e.payload
        if isinstance(p, ev.GroupMoved) and p.polity == own and p.change:
            out[p.group] = GroupMove(cause=p.cause.value, change=p.change, on=p.on.isoformat())
    return out


def open_measures(state: State, view: View, own: EntityId) -> list[tuple[Order, str, str]]:
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
    state: State, own: EntityId, order: Order, key: str, then: Counts | None = None
) -> list[tuple[str, FloorVote]]:
    """Each (chamber, vote) ``own``'s blocs cast on measure ``key`` for ``order``, counted
    by bloc as the votes rule would tally it on ``state`` (``votes.floor_counts``), each
    beside its count in ``then`` (``_then``) where it has one."""
    out: list[tuple[str, FloorVote]] = []
    for chamber, vote, parts in votes.floor_counts(state, own, order, key, order.measure):
        yeas, nays = sum(y for _, y, _ in parts), sum(n for _, _, n in parts)
        whole, by_bloc = (then or {}).get((order.order_id, vote), (None, {}))
        out.append(
            (
                chamber,
                FloorVote(
                    vote=vote,
                    yeas=yeas,
                    nays=nays,
                    blocs=[
                        BlocCount(
                            group=g,
                            yeas=y,
                            nays=n,
                            then=by_bloc.get(g),
                            moved=g in by_bloc and by_bloc[g] != [y, n],
                        )
                        for g, y, n in parts
                    ],
                    carries=carries(yeas + nays),
                    then=whole,
                ),
            )
        )
    return out


def _chambers(state: State, view: View, own: EntityId, then: Counts) -> list[FloorChamber]:
    blocs = [g for g in groups.of(view, own) if g.chamber is not None and g.seats is not None]
    chambers = list(dict.fromkeys(str(g.chamber) for g in blocs))
    measures: dict[str, list[OpenMeasure]] = {key: [] for key in chambers}
    for order, key, title in open_measures(state, view, own):
        counted: dict[str, list[FloorVote]] = {}
        for chamber, vote in _floor_votes(state, own, order, key, then):
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


def _office(state: State, view: View, own: EntityId) -> list[OfficeQuestionLine]:
    """Each office question open on a post of ``own``'s nation, as every seat of it sees
    it: the body's count as it falls today, never another member's choice. The seat's own
    choice is its own to see."""
    out: list[OfficeQuestionLine] = []
    for q in office.questions(state, own):
        way = office.removal(state, q.post)
        if way is None:
            continue
        who = office.deciders(state, q)
        voted = q.cause is not QuestionCause.ELECTION and way.way is RemovalWay.VOTE
        count = None
        if voted and way.chamber is not None and way.vote is not None:
            yeas, nays = votes.bloc_tally(
                state, own, way.chamber, office.MEASURE, way.vote, OrderId(q.question_id)
            )
            count = OfficeCount(yeas=yeas, nays=nays)
        mine = view.me.embodies in who
        out.append(
            OfficeQuestionLine(
                question_id=q.question_id,
                office=state.assets[q.post].name,
                holder=state.entities[q.holder].name,
                cause=q.cause.value,
                sits=q.sits.isoformat(),
                way="election"
                if q.cause is QuestionCause.ELECTION
                else cast(OfficeWay, way.way.value),
                chamber=way.chamber if voted else None,
                deciders=[state.entities[m].name for m in who],
                mine=mine,
                choice=state.office_choices.get(q.question_id, {}).get(view.viewer)
                if mine
                else None,
                count=count,
            )
        )
    return out


def _turning(state: State, view: View, today: date) -> list[BaseUnder]:
    """Each post the seat's person holds whose base stands under its line, with no
    question yet open on it: how far under, for how long, and the day one would open."""
    out: list[BaseUnder] = []
    for post, fell in office.base_fell(state, today).items():
        mean = office.base_support(state, post)
        if (
            mean is None
            or posts.holder(state, post) != view.me.embodies
            or office.removal(state, post) is None
            or office.open_on(state, post) is not None
        ):
            continue
        out.append(
            BaseUnder(
                office=state.assets[post].name,
                groups=[g.name for g in office.base(state, post)],
                support=round(mean, 1),
                line=office.TURN_LINE,
                under=round(office.TURN_LINE - mean, 1),
                days=(today - fell).days + 1,
                opens=(fell + timedelta(days=office.TURN_DAYS - 1)).isoformat(),
            )
        )
    return out


def _footing(state: State, view: View, today: date) -> list[FootingLine]:
    """Each post the seat's person holds that may be put to an office question and rests
    on groups: its base today against its line, the days it has stood under, and the
    question open on it, if any."""
    out: list[FootingLine] = []
    for post in sorted(state.ladders):
        mean = office.base_support(state, post)
        if (
            mean is None
            or posts.holder(state, post) != view.me.embodies
            or office.removal(state, post) is None
        ):
            continue
        open_ = office.open_on(state, post)
        out.append(
            FootingLine(
                office=state.assets[post].name,
                groups=[g.name for g in office.base(state, post)],
                support=round(mean, 1),
                line=office.TURN_LINE,
                days=office.days_under(state, post, today) if mean < office.TURN_LINE else 0,
                question=open_.question_id if open_ is not None else None,
            )
        )
    return out


def _results(state: State, log: Sequence[Event], own: EntityId, today: date) -> list[OfficeResult]:
    """Each office question on a post of ``own``'s nation decided in the last
    ``RESULT_DAYS`` world days, by day: public news, read from the log."""
    out: list[OfficeResult] = []
    for e in log:
        p = e.payload
        if (
            not isinstance(p, ev.OfficeQuestionDecided)
            or office.nation(state, p.post) != own
            or not 0 <= (today - p.on).days < RESULT_DAYS
        ):
            continue
        out.append(
            OfficeResult(
                question_id=p.question_id,
                office=state.assets[p.post].name,
                holder=state.entities[p.holder].name,
                on=p.on.isoformat(),
                removed=p.removed,
                rests_until=p.rests_until.isoformat() if p.rests_until is not None else None,
            )
        )
    return sorted(out, key=lambda r: r["on"])


def _elections(state: State, own: EntityId, today: date) -> list[ElectionAhead]:
    """Each election of ``own``'s nation not yet held, by day, with each chamber's seats
    as they would be redrawn today."""
    ahead = sorted(
        (e for e in state.groups.elections if e.nation == own and e.day >= today),
        key=lambda e: e.day,
    )
    out: list[ElectionAhead] = []
    for e in ahead:
        chambers: list[ElectionChamber] = []
        for chamber in e.chambers:
            drawn = elections.redrawn(state, own, chamber)
            chambers.append(
                ElectionChamber(
                    key=chamber,
                    blocs=[
                        ElectionBloc(
                            group=g.key, name=g.name, seats=g.seats or 0, would=drawn[g.key]
                        )
                        for g in elections.blocs(state, own, chamber)
                    ],
                )
            )
        out.append(
            ElectionAhead(
                day=e.day.isoformat(),
                office=state.assets[e.post].name if e.post is not None else None,
                chambers=chambers,
            )
        )
    return out


def block(
    state: State, view: View, events: Iterable[Event] = (), areas: Sequence[MapArea] = ()
) -> HomeBlock | None:
    """The ``home`` block with ``groups`` on: the seat's own nation's groups, its chambers
    with the seat's open measures counted by bloc, its themes, its standing as a figure,
    and every nation's standing as a band; with ``offers`` on, each measure on its way with
    what its blocs would take, and the seat's own promises; with ``office`` on, the office
    questions open in its own nation and the posts it holds whose base has turned; with
    ``elections`` on, its nation's elections ahead. The groups, chambers, themes
    and offers are read from the seat's ``View``, which holds its own nation's and no
    other's. ``areas`` are the seat's map areas, which mark a threatened place. A
    commander held to his post gets his nation's public band and places only. None
    with the rule off and for a seat of no nation."""
    own = economy_api.own_nation(view)
    today = view.in_world_date
    if not groups.on(state) or own is None or today is None:
        return None
    post = at_post(state, view.viewer)
    log = list(events)
    moved = _last_moved(log, own)
    wake = last_wake(log, view.viewer, view.me.embodies)
    since = _since(view, log, own, wake)
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
                since=since.get(g.key, []),
                feeds={f.value: w for f, w in g.feeds.items()},
            )
            for g in groups.of(view, own)
        ],
        chambers=[] if post else _chambers(state, view, own, _then(log, wake, view.viewer, own)),
        themes=[
            HomeTheme(key=t.key, name=t.name, moves=dict(t.moves))
            for t in view.groups.themes.get(own, ())
        ],
        # read from state: a view holds no rules, and home_standing reads the economy rule
        standing=None if post else groups.home_standing(state, own),
        standings=_standings(state, own),
        moved=_moved(view, own, since),
        places=_places(state, view, own, areas) if groups.places_on(state) else [],
    )
    if post:
        return out
    if offers.on(state):
        out["offers"] = _on_offer(state, view, own)
        out["promises"] = promises(view)
    if office.on(state):
        out["office"] = _office(state, view, own)
        out["turning"] = _turning(state, view, today)
        out["footing"] = _footing(state, view, today)
        out["results"] = _results(state, log, own, today)
    if elections.on(state):
        out["elections"] = _elections(state, own, today)
    return out


# --- A capital's live questions --------------------------------------------------------

AGREEMENT_TITLE = "Agreement of {parties}"  # [proposed]
VOTE_TITLE = "Vote called by {nation}"  # [proposed]
PEACE_TITLE = "Peace offered by {nation}"  # [proposed]
OFFERS_TITLE = "Offers to the blocs on {title}"  # [proposed]
ELECTION_TITLE = "Election"  # [proposed]
THE_COUNCIL = "the council"  # [proposed]
THE_VOTERS = "the voters"  # [proposed]


def capitals(
    state: State, view: View, sent: Mapping[str, Any], events: Iterable[Event] = ()
) -> list[CapitalLine]:
    """Every nation's capital as the seat may know it, its own first: for its own nation
    each live question in the payload ``sent`` (its measures on their way, the offers to
    its blocs, its sittings, its elections ahead, the orders it holds for a decider, the
    asks before it and a peace before it to answer); for another nation only its public
    record: a published agreement, a reported public vote, a sitting's result that is
    news. Each line points at data the seat is already sent, so the list adds nothing."""
    own = economy_api.own_nation(view)
    polities = [k for k, e in state.entities.items() if e.kind is EntityKind.POLITY]
    nations = sorted(
        (economy_api.nation(state, own, p) for p in polities),
        key=lambda n: (n["relation"] != "own", n["name"], n["key"]),
    )
    keys = {economy_api.nation(state, own, p)["key"]: p for p in polities}
    log = list(events)
    out: list[CapitalLine] = []
    for n in nations:
        polity = keys[n["key"]]
        found = _own_questions(state, view, sent) if polity == own else []
        found += _public_questions(state, sent, log, polity, n["name"])
        out.append(
            CapitalLine(nation=n, place=_capital_place(state, view, polity), questions=found)
        )
    return out


def _capital_place(state: State, view: View, polity: EntityId) -> MapPlace | None:
    """``polity``'s capital as the map draws it; None for none, or for one with no position."""
    site = state.map.capitals.get(polity) if state.map is not None else None
    place = view.entities.get(site) if site is not None else None
    if place is None or place.at is None:
        return None
    return MapPlace(name=place.name, lat=place.at[0], lon=place.at[1], theatre=place.theatre)


def _decider(shape: CapitalShape, who: str, members: Sequence[str]) -> CapitalDecider:
    return CapitalDecider(shape=shape, who=who, members=list(members))


def _lock_decider(state: State, view: View, decider: locks.Decider) -> CapitalDecider:
    from revisionist.engine.web import locks_api

    who = locks_api.who(view, decider)
    if decider.person is not None:
        return _decider("person", who, [who])
    if decider.council is not None:
        names = [_named(state, m) for m in decider.council.members]
        return _decider("council", who, names)
    return _decider("body", who, [c.replace("_", " ") for c in decider.chambers])


def _named(state: State, entity: EntityId) -> str:
    found = state.entities.get(entity)
    return found.name if found is not None else str(entity)


def _blocs(home: Mapping[str, Any] | None, chamber: str | None) -> list[str]:
    for c in (home or {}).get("chambers", []):
        if c["key"] == chamber:
            return [b["name"] for b in c["blocs"]]
    return []


def _own_questions(state: State, view: View, sent: Mapping[str, Any]) -> list[CapitalQuestion]:
    home: Mapping[str, Any] = sent.get("home") or {}
    out: list[CapitalQuestion] = []
    for c in home.get("chambers", []):
        body = _decider("body", c["key"].replace("_", " "), _blocs(home, c["key"]))
        for m in c["measures"]:
            out.append(_q("measure", m["title"], None, body, "home.chambers", m["order_id"]))
    for o in home.get("offers", []):
        blocs = _decider("body", THE_VOTERS, [b["name"] for b in o["blocs"]])
        title = OFFERS_TITLE.format(title=o["title"])
        out.append(_q("offer", title, None, blocs, "home.offers", o["key"]))
    for q in home.get("office", []):
        out.append(
            _q("office", q["office"], q["sits"], _sitting(home, q), "home.office", q["question_id"])
        )
    for e in home.get("elections", []):
        chambers = [c["key"].replace("_", " ") for c in e["chambers"]]
        voters = _decider("body", " and ".join(chambers) or THE_VOTERS, chambers)
        title = e["office"] or ELECTION_TITLE
        out.append(_q("election", title, e["day"], voters, "home.elections", e["day"]))
    out += _locked(state, view, sent)
    return out


def _sitting(home: Mapping[str, Any], q: Mapping[str, Any]) -> CapitalDecider:
    if q["way"] == "vote":
        return _decider("body", (q["chamber"] or "").replace("_", " "), _blocs(home, q["chamber"]))
    if q["way"] == "council":
        return _decider("council", THE_COUNCIL, q["deciders"])
    if q["way"] == "person" and q["deciders"]:
        return _decider("person", q["deciders"][0], q["deciders"][:1])
    return _decider("body", THE_VOTERS, [])


def _locked(state: State, view: View, sent: Mapping[str, Any]) -> list[CapitalQuestion]:
    from revisionist.engine.web import locks_api

    out: list[CapitalQuestion] = []
    held_lines = {h["id"]: h for h in (sent.get("locks") or {}).get("held", [])}
    for h in sorted(view.held.values(), key=lambda h: (h.filed, h.order_id)):
        if h.order_id in held_lines:
            who = _lock_decider(state, view, h.decider)
            out.append(
                _q("held", held_lines[h.order_id]["words"], None, who, "locks.held", h.order_id)
            )
    asks = {a["id"]: a for a in (sent.get("locks") or {}).get("asks", [])}
    for a in sorted(view.asked.values(), key=lambda a: (a.on, a.order_id)):
        line = asks.get(locks_api.ask_id(state.campaign_id, a.order_id))
        if line is None:
            continue
        held = state.held.get(a.order_id)
        if held is not None:
            who = _lock_decider(state, view, held.decider)
        else:
            who = _decider("person", _named(state, a.to), [_named(state, a.to)])
        out.append(_q("ask", a.words, None, who, "locks.asks", line["id"]))
    nation = economy_api.own_nation(view)
    for o in (sent.get("agreements") or {}).get("offers", []):
        if "accept" not in o or o["item"] is None:
            continue
        row = locks.peace_row(state, nation) if nation is not None else None
        if row is not None:
            who = _lock_decider(state, view, row.decider)
        else:
            me = _named(state, view.me.embodies)
            who = _decider("person", me, [me])
        title = PEACE_TITLE.format(nation=o["by"])
        out.append(_q("peace", title, o["expires"], who, "agreements.offers", o["item"]))
    return out


def _public_questions(
    state: State, sent: Mapping[str, Any], log: Sequence[Event], polity: EntityId, name: str
) -> list[CapitalQuestion]:
    out: list[CapitalQuestion] = []
    for a in (sent.get("agreements") or {}).get("agreements", []):
        if a["published"] is not None and name in a["parties"]:
            parties = " and ".join(a["parties"])
            who = _decider("council", parties, a["parties"])
            title = AGREEMENT_TITLE.format(parties=parties)
            out.append(
                _q("agreement", title, a["published"], who, "agreements.agreements", a["id"])
            )
    for c in (sent.get("conferences") or {}).get("conferences", []):
        if c["public"] and c["tallied"] is not None and name in c["invited"]:
            who = _decider("council", " and ".join(c["invited"]), c["invited"])
            title = VOTE_TITLE.format(nation=c["called_by"])
            out.append(_q("vote", title, c["tallied"], who, "conferences.conferences", c["key"]))
    for e in log:
        p = e.payload
        if not isinstance(p, ev.OfficeQuestionDecided) or e.scope.visibility.value != "public":
            continue
        if p.post not in state.assets or office.nation(state, p.post) != polity:
            continue
        way = office.removal(state, p.post)
        who = _removal_decider(state, way)
        title = state.assets[p.post].name
        out.append(_q("result", title, p.on.isoformat(), who, "news", p.question_id))
    return out


def _removal_decider(state: State, way: Removal | None) -> CapitalDecider:
    if way is not None and way.way is RemovalWay.COUNCIL:
        return _decider("council", THE_COUNCIL, [_named(state, m) for m in way.members])
    if way is not None and way.way is RemovalWay.PERSON and way.person is not None:
        name = _named(state, way.person)
        return _decider("person", name, [name])
    chamber = way.chamber if way is not None and way.chamber is not None else THE_VOTERS
    return _decider("body", chamber.replace("_", " "), [])


def _q(
    kind: CapitalKind, title: str, day: str | None, who: CapitalDecider, at: CapitalAt, ref: str
) -> CapitalQuestion:
    return CapitalQuestion(kind=kind, title=title, day=day, decider=who, at=at, ref=ref)
