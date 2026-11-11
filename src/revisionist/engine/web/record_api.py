"""The seat's record block for the room (Train 2 unit S1): its orders and the latest wake.

Built from ``core.record.build``, so it holds only what the seat's own edition holds.
Days are worded; ledger keys become opaque tokens, so no order id or entity id leaves.
"""

from collections.abc import Sequence

from revisionist.core.events import Event
from revisionist.core.ids import SeatId
from revisionist.core.state import State
from revisionist.engine.web.realism_api import RecordBlock


def record_block(state: State, events: Sequence[Event], seat: SeatId) -> RecordBlock:
    """``seat``'s orders, newest filed first, and its latest wake page. contract stub"""
    return RecordBlock(orders=[], wake=None)


__all__ = ["record_block"]
