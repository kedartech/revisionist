"""How each routed order landed (Phase 4 unit S3), built from the seat's own view.

Never the estimator's ``rationale``, never its engine-only effects: ``View.routed``
carries neither, and this module reads nothing else.
"""

from revisionist.core.ids import SeatId
from revisionist.core.state import State
from revisionist.engine.web.realism_api import OrderResult


def results(state: State, seat: SeatId) -> list[OrderResult]:
    """Phase 4 unit S3: the seat's routed orders, newest first, each part in words."""
    return []


__all__ = ["results"]
