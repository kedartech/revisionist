"""The shared wake (engine v2, spec §4, decision 41). Wave B unit B1.

One wake for the whole table: it opens, each seat commits, and it closes when all
have committed or at the deadline, the aide playing any seat that has not.
Contract stubs until B1 builds them.
"""

from datetime import datetime

from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.state import State
from revisionist.engine.llm import Transport
from revisionist.engine.store import EventStore


def open_wake(store: EventStore, campaign_id: CampaignId, now: datetime) -> int:
    """Open the next wake; returns its number. Wave B unit B1."""
    raise NotImplementedError("Wave B unit B1")


def commit(store: EventStore, campaign_id: CampaignId, seat: SeatId, now: datetime) -> bool:
    """Seal ``seat``'s orders for the open wake; False if it already had. Wave B unit B1."""
    raise NotImplementedError("Wave B unit B1")


def close_wake(
    store: EventStore, campaign_id: CampaignId, now: datetime, transport: Transport | None
) -> tuple[SeatId, ...]:
    """Close the open wake; returns the seats the aide played. Wave B unit B1."""
    raise NotImplementedError("Wave B unit B1")


def wake_due(state: State, now: datetime) -> bool:
    """Whether the open wake should close at ``now``. Wave B unit B1."""
    raise NotImplementedError("Wave B unit B1")


__all__ = ["close_wake", "commit", "open_wake", "wake_due"]
