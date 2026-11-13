"""In-tray rules the client cannot work out alone: which papers only acknowledge an order,
and which belong to a feed that files one paper a day."""

import re

from revisionist.core.realism.document import DocumentKind, DocumentView
from revisionist.core.realism.effect import Fidelity, PartView

_TRAILING_DATE = re.compile(r", \d{4}-\d{2}-\d{2}$")

_PLAIN_STEPS = frozenset({"passed it on", "pressed it forward"})
"""A step reply that says only this is a receipt: the order moved and nothing changed."""


def acknowledgement(doc: DocumentView, part: PartView | None = None) -> bool:
    """A paper that only says an order went through as given. ``part`` is the routed part a
    report paper answers: the report acknowledges when that part was carried out in full
    with no account (a refused part has no fidelity). Any other paper acknowledges when it
    is a step reply that passed the order on unchanged. Anything loose, late, refused,
    amended or explained is news and stays in the tray."""
    if doc.kind is DocumentKind.PRESS:
        return False
    if part is not None:
        return part.fidelity is Fidelity.FULL and not part.reason
    lines = {b.label: b.value for b in doc.body}
    if "What was done" in lines:
        return lines["What was done"] in _PLAIN_STEPS and not any(
            k == "Outcome" or k.startswith("Changed:") for k in lines
        )
    return False


def feed_group(title: str) -> str | None:
    """The feed's name for a paper titled "<feed>, YYYY-MM-DD"; None for a one-off paper."""
    found = _TRAILING_DATE.search(title)
    return title[: found.start()] if found else None


__all__ = ["acknowledgement", "feed_group"]
