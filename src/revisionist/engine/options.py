"""Options and play styles (engine v2, spec §8.6). Wave B unit B3.

A guided or beginner seat is offered ordinary orders for its agenda; an aide
drafts asks for an absent seat. Contract stubs until B3 builds them.
"""

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.realism.agenda import Ask, PlayStyle
from revisionist.core.realism.effect import EffectKind
from revisionist.core.state import State
from revisionist.engine.llm import Transport
from revisionist.engine.store import EventStore

OPTIONS_MODEL = "claude-haiku-5-5"
"""[proposed] The option generator's model."""
CALL_CLASS = "options"
"""``Request.call_class`` and ``CallCost.call_class`` for every options call."""
PROMPT = "options"
"""The system prompt: ``engine/prompts/options.md``."""
RECORDING = "realism-options-slice.json"
"""Recorded replies under ``tests/recordings/``, keyed by ``Request.key()``."""


def offer(state: State, seat: SeatId, transport: Transport | None) -> ev.OptionsOffered | None:
    """What ``seat`` is offered this wake, or None for a free seat. Wave B unit B3."""
    raise NotImplementedError("Wave B unit B3")


def aide_asks(state: State, seat: SeatId, transport: Transport | None) -> list[tuple[Ask, ...]]:
    """The orders an aide files for an absent seat. Wave B unit B3."""
    raise NotImplementedError("Wave B unit B3")


def set_style(
    store: EventStore,
    campaign_id: CampaignId,
    seat: SeatId,
    style: PlayStyle,
    standing: frozenset[EffectKind] = frozenset(),
) -> None:
    """Set ``seat``'s play style and standing orders. Wave B unit B3."""
    raise NotImplementedError("Wave B unit B3")


__all__ = [
    "CALL_CLASS",
    "OPTIONS_MODEL",
    "PROMPT",
    "RECORDING",
    "aide_asks",
    "offer",
    "set_style",
]
