"""The agenda (engine v2, spec §8.5). Wave B unit B2.

Templates on ``State.templates`` issue mandates when their triggers fire, and live
mandates settle met, failed or expired. ``score`` is what a seat's mandates are
worth. Contract stubs until B2 builds them.
"""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import SeatId
from revisionist.core.state import State


def issue_due(state: State, today: date) -> list[ev.Payload]:
    """A ``mandate_issued`` for each template whose trigger fired. Wave B unit B2; empty."""
    return []


def settle_due(state: State, today: date) -> list[ev.Payload]:
    """A ``mandate_settled`` for each live mandate met or past expiry. Wave B unit B2; empty."""
    return []


def score(state: State, seat: SeatId) -> int:
    """What the seat's settled mandates are worth. Wave B unit B2; 0 until then."""
    return 0


__all__ = ["issue_due", "score", "settle_due"]
