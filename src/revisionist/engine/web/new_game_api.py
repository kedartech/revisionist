"""A new game on the web (Phase 4 unit E1): the timeline, the figures, the start."""

from datetime import date
from http import HTTPStatus

from revisionist.core.ids import SeatId
from revisionist.engine import campaign as cmp
from revisionist.engine import timeline as tl
from revisionist.engine.ids import new_id
from revisionist.engine.llm import Transport
from revisionist.engine.pg_store import PostgresEventStore
from revisionist.engine.web.accounts import WebSeats
from revisionist.engine.web.realism_api import Figure, FigureGroup, Reply, TimelinePoint

UNMARKED = "Only the marked dates can start a game for now."
NO_WORLD = "No game is ready for that date yet."


def timeline() -> list[TimelinePoint]:
    """The war's dates, curated start points marked, from ``timeline``."""
    return [
        TimelinePoint(date=p.on.isoformat(), label=p.label, curated=True, world=p.world)
        for p in tl.start_points()
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


__all__ = ["figures", "start", "timeline"]
