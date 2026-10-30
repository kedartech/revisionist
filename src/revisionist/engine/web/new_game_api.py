"""A new game on the web (Phase 4 unit E1): the timeline, the figures, the start."""

from datetime import date

from revisionist.engine.llm import Transport
from revisionist.engine.pg_store import PostgresEventStore
from revisionist.engine.web.realism_api import FigureGroup, Reply, TimelinePoint


def timeline() -> list[TimelinePoint]:
    """Phase 4 unit E1: the war's dates, curated start points marked, from ``timeline``."""
    return []


def figures(on: date, search: str, transport: Transport) -> list[FigureGroup]:
    """Phase 4 unit E1: up to about 40 who held power ``on``, by side and kind of
    power, narrowed by ``search`` (empty: everyone)."""
    return []


def start(store: PostgresEventStore, account_id: str, on: date, transport: Transport) -> Reply:
    """Phase 4 unit E1: a game on the chosen date, with the account as host; everyone
    then picks a figure through ``/api/new/pick``. The account holds no seat yet."""
    return Reply(reply="Nothing has changed yet.", refused=True)


__all__ = ["figures", "start", "timeline"]
