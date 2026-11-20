"""Groups at home and the floor as the seat sees them (GPD).

``block`` is the ``home`` block with ``groups`` on. For the seat's own nation: each group
at home with its support, what last moved it and when, and what it feeds; each chamber its
blocs sit in, with their seats and, for each measure the seat has on its way, the count by
bloc as the votes rule would tally it today (``votes.floor_counts``, never a count of its
own); the nation's themes and its standing at home as a figure. For every nation: its
standing as one of five public bands. The groups, chambers and themes are read from the
seat's ``View``, which holds its own nation's groups and no other's, so no other nation's
group can reach the payload; the bands are read from the truth and sent as bands only.
"""

from collections.abc import Iterable
from typing import Literal

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.ids import EntityId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism import groups
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
    NationStanding,
    OpenMeasure,
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


def standing_band(figure: float) -> Band:
    """The public band a standing at home of ``figure`` (0 to 100) falls in."""
    return next(band for low, band in BANDS if figure >= low)


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


def _chambers(state: State, view: View, own: EntityId) -> list[FloorChamber]:
    blocs = [g for g in groups.of(view, own) if g.chamber is not None and g.seats is not None]
    chambers = list(dict.fromkeys(str(g.chamber) for g in blocs))
    measures: dict[str, list[OpenMeasure]] = {key: [] for key in chambers}
    for order, key, title in _open_measures(state, view, own):
        counted: dict[str, list[FloorVote]] = {}
        for chamber, vote, parts in votes.floor_counts(state, own, order, key, order.measure):
            counted.setdefault(chamber, []).append(
                FloorVote(
                    vote=vote,
                    yeas=sum(y for _, y, _ in parts),
                    nays=sum(n for _, _, n in parts),
                    blocs=[BlocCount(group=g, yeas=y, nays=n) for g, y, n in parts],
                )
            )
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


def block(state: State, view: View, events: Iterable[Event] = ()) -> HomeBlock | None:
    """The ``home`` block with ``groups`` on: the seat's own nation's groups, its chambers
    with the seat's open measures counted by bloc, its themes, its standing as a figure,
    and every nation's standing as a band. The groups, chambers and themes are read from
    the seat's ``View``, which holds its own nation's groups and no other's. None with the
    rule off and for a seat of no nation."""
    own = economy_api.own_nation(view)
    today = view.in_world_date
    if not groups.on(state) or own is None or today is None:
        return None
    moved = _last_moved(events, own)
    return HomeBlock(
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
