"""Applying a part's effects to the world (engine v2, spec §8.2-8.3). Wave B unit B4.

A part is applied once it is ready: a command carried out or refused, an estimate
ruled, an influence decided. ``apply_due`` lands ``effects_applied`` for each, and
``report`` is the paper its issuer gets back. Contract stubs until B4 builds them.
"""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.realism.effect import RoutedOrder
from revisionist.core.state import State


def apply_due(state: State, today: date) -> list[ev.Payload]:
    """Every part ready to apply on ``today``. Wave B unit B4; empty until then."""
    return []


def report(state: State, order: RoutedOrder, part: int, on: date) -> ev.DocumentIssued | None:
    """The paper the issuer gets for one applied part. Wave B unit B4; None until then."""
    return None


__all__ = ["apply_due", "report"]
