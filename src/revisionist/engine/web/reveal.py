"""The end-of-game reveal (Phase 4 unit S5): secret goals, covert acts, each seat's
style history and the estimator's full rationale.

The server calls this for an ended game only, and only for an account that held a
seat in it. It is the one read that does not pass ``snapshot.checked``.
"""

from collections.abc import Iterable

from revisionist.core.events import Event
from revisionist.core.state import State
from revisionist.engine.web.realism_api import Reveal


def build(state: State, log: Iterable[Event]) -> Reveal:
    """Phase 4 unit S5: the whole table's record, from the truth and the full log."""
    return Reveal(name="", seats=[])


__all__ = ["build"]
