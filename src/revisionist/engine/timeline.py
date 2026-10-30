"""The war's timeline and who held power on a date (Phase 4 unit E1)."""

from dataclasses import dataclass
from datetime import date

from revisionist.engine.llm import Transport


@dataclass(frozen=True)
class StartPoint:
    on: date
    label: str
    world: str | None
    """The ready-made world to start; None: a date with no curated world."""


@dataclass(frozen=True)
class HeldPower:
    """One figure who held real power on a date."""

    name: str
    title: str
    side: str
    power: str


def start_points() -> tuple[StartPoint, ...]:
    """Phase 4 unit E1: the curated start points, oldest first."""
    return ()


def held_power(on: date, transport: Transport) -> tuple[HeldPower, ...]:
    """Phase 4 unit E1: the generated list of who held power ``on``."""
    return ()


__all__ = ["HeldPower", "StartPoint", "held_power", "start_points"]
