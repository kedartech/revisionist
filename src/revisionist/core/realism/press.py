"""Each seat's press: public news worded in its own outlet's voice. Stub for now."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.state import State


def news_pages(state: State, day: date) -> list[ev.DocumentIssued]:
    return []
