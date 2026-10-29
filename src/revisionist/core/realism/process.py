"""Process and influence parts (engine v2, spec §8.2). Wave B unit B5.

A process part opens its pipeline as an ``order_drafted`` that carries the part
(``Order.routed_from``); an influence part is decided by its target's card policy
as ``influence_decided``. Contract stubs until B5 builds them.
"""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.state import State


def open_processes(state: State, today: date) -> list[ev.Payload]:
    """A pipeline order for each process part not yet carried. Wave B unit B5; empty."""
    return []


def influence_due(state: State, today: date) -> list[ev.Payload]:
    """A decision for each influence part due on ``today``. Wave B unit B5; empty."""
    return []


__all__ = ["influence_due", "open_processes"]
