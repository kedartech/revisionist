"""A new game on the web (Phase 4 unit E1): the timeline, the figures, the start."""

from datetime import date
from http import HTTPStatus

from revisionist.core import events as ev
from revisionist.core import roster
from revisionist.core.ids import CampaignId, EntityId, SeatId
from revisionist.core.ontology import Controller
from revisionist.core.realism.card import CardPath
from revisionist.core.state import State, controller_after
from revisionist.engine import campaign as cmp
from revisionist.engine import timeline as tl
from revisionist.engine.ids import new_id
from revisionist.engine.llm import Transport
from revisionist.engine.pg_store import PostgresEventStore
from revisionist.engine.store import EventStore
from revisionist.engine.web.accounts import WebSeats
from revisionist.engine.web.realism_api import (
    Figure,
    FigureGroup,
    Opening,
    OpeningNation,
    OpeningPath,
    OpeningPerson,
    Reply,
    TimelinePoint,
)

UNMARKED = "Only the marked dates can start a game for now."
NO_WORLD = "No game is ready for that date yet."
SET_BY_WORLD = "This game's people are set by its world. Choose from those it offers."  # [proposed]
"""The refusal of the who-held-power list in a game made from a ready-made world."""
OFF_ROSTER = "Only the people this game offers can be played in it."  # [proposed]
"""The refusal of a name off the roster in a game made from a ready-made world."""
NO_NATION = "Without a nation"  # [proposed]
"""The heading for people the world places under no nation."""
PITCHED = "cast-"
"""How the name of a world the cast drafts from a pitch begins (``engine.cast``)."""
_PATHS = (CardPath.POLITICAL, CardPath.MILITARY, None)


def timeline() -> list[TimelinePoint]:
    """The start points the screen lists, from ``timeline``: each offered world at its own
    name and date, then the turning dates."""
    from revisionist.engine.web.server import OFFERED

    return [
        TimelinePoint(date=p.on.isoformat(), label=p.label, curated=True, world=p.world)
        for p in tl.start_points(OFFERED)
    ]


def figures(on: date, search: str, transport: Transport) -> list[FigureGroup]:
    """Up to about 40 who held power ``on``, by side and kind of power, narrowed by
    ``search`` (empty: everyone). A date outside the war is a 400 with the reason."""
    try:
        people = tl.held_power(on, transport)
    except tl.OutsideWarError as exc:
        from revisionist.engine.web.server import ApiError

        raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from None
    needle = search.strip().casefold()
    groups: dict[tuple[str, str], list[Figure]] = {}
    for p in people:
        if needle and needle not in p.name.casefold() and needle not in p.title.casefold():
            continue
        groups.setdefault((p.side, p.power), []).append(Figure(name=p.name, title=p.title))
    return [
        FigureGroup(side=side, power=power, figures=found)
        for (side, power), found in sorted(groups.items())
    ]


def start(
    store: PostgresEventStore,
    account_id: str,
    on: date,
    transport: Transport,
    world: str | None = None,
) -> Reply:
    """A game on the chosen date, with the account as host; everyone then picks a
    figure through ``/api/new/pick``. The account holds no seat yet. ``world`` picks
    between two ready worlds on one date; without it the first on that date starts."""
    point = next(
        (p for p in tl.start_points() if p.on == on and (not world or p.world == world)), None
    )
    if point is None:
        return Reply(reply=UNMARKED, refused=True)
    if point.world is None:
        return Reply(reply=NO_WORLD, refused=True)
    cid = cmp.new_campaign(store, cmp.load_world(cmp.world_path(point.world)))
    WebSeats(store.conn).start(cid, SeatId(new_id()), account_id)
    return Reply(reply="The game is made. Choose who you will play.", refused=False)


def ready_made(store: EventStore, campaign_id: CampaignId) -> bool:
    """True unless the game's world was drafted from a pitch: a ready-made world's people
    are its roster, so it never asks a model who held power or to place someone."""
    for e in store.read(campaign_id):
        if isinstance(e.payload, ev.CampaignCreated):
            return not e.payload.world.startswith(PITCHED)
    return True


def opening(state: State) -> Opening:
    """The game's people by nation, then path, then person, from ``roster.claimable``
    alone: everyone a player may take, and everyone already taken, marked. A nation or a
    path with neither is not listed. The same for every caller; the server serves it only
    while the game chooses its people."""
    listed = [c for c in roster.claimable(state) if c.taken or c.reason is None]
    grouped: dict[EntityId | None, dict[CardPath | None, list[roster.Candidate]]] = {}
    for c in listed:
        grouped.setdefault(c.nation, {}).setdefault(c.path, []).append(c)
    nations: list[OpeningNation] = []
    for nation, paths in grouped.items():
        shown = [
            OpeningPath(
                path=path.value if path is not None else None,
                persons=[
                    OpeningPerson(name=c.name, office=c.office, pitch=c.pitch, taken=c.taken)
                    for c in paths[path]
                ],
            )
            for path in _PATHS
            if path in paths
        ]
        name = state.entities[nation].name if nation is not None else NO_NATION
        nations.append(OpeningNation(key=nation, name=name, paths=shown))
    nations.sort(key=lambda n: (n["key"] is None, n["name"]))
    most = state.settings.max_human_seats
    return Opening(nations=nations, seats_left=max(0, most - _humans(state)), seats_max=most)


def _humans(state: State) -> int:
    """The players once the open wake closes, counted as the fold counts a claim or a
    leader handed to a player."""
    people = {s.embodies for s in state.seats.values()} | set(state.handovers)
    return sum(controller_after(state, p) is Controller.HUMAN for p in people)


__all__ = ["figures", "opening", "ready_made", "start", "timeline"]
