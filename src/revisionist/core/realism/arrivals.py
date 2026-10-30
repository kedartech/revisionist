"""What a force's arrival sets going. Stub for now."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.state import State


def arrivals(before: State, after: State, day: date) -> list[ev.Payload]:
    return []
