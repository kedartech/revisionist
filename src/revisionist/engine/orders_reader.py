"""Free text read into engine-v2 asks (Phase 4 unit D): a cheap model proposes, the
player signs, and the order is routed and filed with ``realism_tick.commit_order``.
"""

from dataclasses import dataclass

from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.realism.agenda import Ask
from revisionist.core.state import State
from revisionist.engine.llm import Transport
from revisionist.engine.store import EventStore
from revisionist.engine.web.realism_api import OrderProposal, Reply


@dataclass(frozen=True)
class Reading:
    """A proposal and what signing it files. The server holds it between ``order``
    and ``file``: asks carry ids, and the client is sent words."""

    shown: OrderProposal
    asks: tuple[Ask, ...]
    """Empty: it cannot be filed, and ``shown`` says why."""


def read_order(
    state: State, seat: SeatId, to: str, channel: str, text: str, transport: Transport
) -> Reading:
    """Phase 4 unit D: read ``text`` from the seat's view. ``to`` and ``channel`` are
    as posted and may be empty. A failed model call raises ``TransportError``."""
    shown = OrderProposal(
        person=None, channel=None, text=text, parts=[], reason="Nothing has changed yet."
    )
    return Reading(shown=shown, asks=())


def file_order(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, reading: Reading | None
) -> Reply:
    """Phase 4 unit D: file a signed reading; a refusal when ``reading`` is None or
    empty, or when a part has no route."""
    return Reply(reply="Nothing has changed yet.", refused=True)


__all__ = ["Reading", "file_order", "read_order"]
