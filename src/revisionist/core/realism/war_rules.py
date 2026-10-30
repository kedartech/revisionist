"""What a state of war allows and forbids, and what it sets in motion. Stubs for now."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import SeatId
from revisionist.core.realism.agenda import Ask
from revisionist.core.state import State


def order_refusal(state: State, seat: SeatId, lever: str, params: dict[str, str]) -> str:
    """The words for why the seat may not pull this lever now; empty if it may."""
    return ""


def ask_refusal(state: State, seat: SeatId, ask: Ask) -> str:
    """The words for why this ask cannot be sent now; empty if it can."""
    return ""


def contacts(state: State, day: date) -> list[ev.Payload]:
    """What forces in contact do on ``day``."""
    return []
