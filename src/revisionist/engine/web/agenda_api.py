"""The agenda on the web (Phase 4 unit S2): live mandates, offered options, the style.

Options come from ``OptionsOffered``, produced at wake open by ``options.offer``.
Picking one files it through the ordinary order path, so it is what a free player
could have typed.
"""

from collections.abc import Iterable

from revisionist.core.events import Event
from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.state import State
from revisionist.engine.llm import Transport
from revisionist.engine.store import EventStore
from revisionist.engine.web.realism_api import AgendaBlock, Reply


def agenda(state: State, seat: SeatId, log: Iterable[Event]) -> AgendaBlock:
    """Phase 4 unit S2: each live mandate and the seat's offers from ``log``."""
    return AgendaBlock(style=seat_style(state, seat), items=[], initiative=[])


def seat_style(state: State, seat: SeatId) -> str:
    """Phase 4 unit S2: the seat's own ``PlayStyle`` value, from its own view."""
    return "free"


def open_offers(store: EventStore, campaign_id: CampaignId, transport: Transport | None) -> None:
    """Phase 4 unit S2: log each human seat's ``options.offer`` for the wake just
    opened. S1 calls it after ``wake.open_wake``; nothing else does."""


def set_style(store: EventStore, campaign_id: CampaignId, seat: SeatId, style: str) -> Reply:
    """Phase 4 unit S2: ``options.set_style`` from the posted ``PlayStyle`` value. Also
    serves the style choice of a new game, once the seat holds a person."""
    return Reply(reply="Nothing has changed yet.", refused=True)


def pick_option(store: EventStore, campaign_id: CampaignId, seat: SeatId, pick: str) -> Reply:
    """Phase 4 unit S2: file the offered option ``pick`` names with
    ``realism_tick.commit_order``."""
    return Reply(reply="Nothing has changed yet.", refused=True)


__all__ = ["agenda", "open_offers", "pick_option", "seat_style", "set_style"]
