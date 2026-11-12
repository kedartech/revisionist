"""Where a person nobody plays stands toward a seat: five stances, from a score.

The score is the engine's; a seat is shown the stance as its staff last had
evidence for it, never the score.
"""

from datetime import date
from enum import StrEnum

from pydantic import Field

from revisionist.core._base import Model
from revisionist.core.ids import OrderId


class Stance(StrEnum):
    """Worst first, so the order of the members is the order of the stances."""

    HOSTILE = "hostile"
    OBSTRUCTING = "obstructing"
    NEUTRAL = "neutral"
    COOPERATIVE = "cooperative"
    ALIGNED = "aligned"


RANK: dict[Stance, int] = {s: i for i, s in enumerate(Stance)}
"""0 for hostile up to 4 for aligned."""

OPPOSED = frozenset({Stance.HOSTILE, Stance.OBSTRUCTING})
"""The stances that make a person an opponent."""

BANDS: dict[Stance, tuple[int | None, int | None]] = {
    Stance.HOSTILE: (None, -5),
    Stance.OBSTRUCTING: (-4, -2),
    Stance.NEUTRAL: (-1, 1),
    Stance.COOPERATIVE: (2, 3),
    Stance.ALIGNED: (4, None),
}
"""The lowest and highest score of each stance [proposed]."""

SLACK = 1
"""How far past its band's edge a score must go before the stance changes."""


def band(score: int) -> Stance:
    """The stance a score falls in, with no memory of what it was."""
    for stance, (lo, hi) in BANDS.items():
        if (lo is None or score >= lo) and (hi is None or score <= hi):
            return stance
    raise AssertionError(f"no band holds {score}")


def step(was: Stance | None, score: int, *, capped: bool = False) -> Stance:
    """The stance after ``score``. It holds until the score passes the edge of its
    band by more than ``SLACK``. ``capped``: an irreducible conflict keeps it at
    obstructing or worse whatever the score."""
    now = band(score)
    if was is not None:
        lo, hi = BANDS[was]
        inside = (lo is None or score >= lo - SLACK) and (hi is None or score <= hi + SLACK)
        now = was if inside else now
    if capped and RANK[now] > RANK[Stance.OBSTRUCTING]:
        return Stance.OBSTRUCTING
    return now


class StanceCause(StrEnum):
    START = "start"
    """As things stood when the stance was first worked out."""
    SIDES = "sides"
    """A war began, or a contest the two were on opposite sides of was decided."""
    DISPOSITION = "disposition"
    """The person's regard for the seat's person moved."""


class Standing(Model):
    """One person's stance toward one seat, from the day it took hold."""

    on: date
    stance: Stance
    score: int = Field(ge=-20, le=20)
    side: int = Field(ge=-5, le=5)
    """The part of the score that came from wars, contests and allies."""
    disposition: int = Field(ge=-5, le=5)
    cause: StanceCause
    order: OrderId | None = None
    """The order whose effects moved the disposition, where one did."""


__all__ = ["BANDS", "OPPOSED", "RANK", "SLACK", "Stance", "StanceCause", "Standing", "band", "step"]
