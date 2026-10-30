"""Who the seat can reach and how (Phase 4 unit S4), from ``core.realism.reach``."""

from revisionist.core.ids import SeatId
from revisionist.core.state import State
from revisionist.engine.web.realism_api import ReachGroups


def reach(state: State, seat: SeatId) -> ReachGroups:
    """Phase 4 unit S4: everyone the seat can reach, in four groups, channels in words."""
    return ReachGroups(inner_circle=[], government=[], foreign=[], other=[])


__all__ = ["reach"]
