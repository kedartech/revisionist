"""In-tray rules the client cannot work out alone: which papers only acknowledge an order,
and which belong to a feed that files one paper a day."""

import re

from revisionist.core.realism.document import DocumentKind, DocumentView
from revisionist.core.realism.effect import Fidelity, PartView

_TRAILING_DATE = re.compile(r", \d{4}-\d{2}-\d{2}$")

_PLAIN_STEPS = {"passed it on": "Passed on", "pressed it forward": "Pressed forward"}
"""A step reply that says only this is a receipt: the order moved and nothing changed."""


def receipt_word(doc: DocumentView, part: PartView | None = None) -> str | None:
    """The words a ledger line gives a paper that only says an order went through as given,
    or None when the paper is news and stays in the tray. ``part`` is the routed part a
    report paper answers: the report is a receipt when that part was carried out in full
    with no account (a refused part has no fidelity). Any other paper is a receipt when it
    is a step reply that passed the order on unchanged. Anything loose, late, refused,
    amended or explained is news."""
    if doc.kind is DocumentKind.PRESS:
        return None
    if part is not None:
        return "Carried out in full" if part.fidelity is Fidelity.FULL and not part.reason else None
    lines = {b.label: b.value for b in doc.body}
    if any(k == "Outcome" or k.startswith("Changed:") for k in lines):
        return None
    done = lines.get("What was done")
    return _PLAIN_STEPS.get(done) if isinstance(done, str) else None


def acknowledgement(doc: DocumentView, part: PartView | None = None) -> bool:
    """A paper that only says an order went through as given (``receipt_word``)."""
    return receipt_word(doc, part) is not None


def feed_group(title: str) -> str | None:
    """The feed's name for a paper titled "<feed>, YYYY-MM-DD"; None for a one-off paper."""
    found = _TRAILING_DATE.search(title)
    return title[: found.start()] if found else None


__all__ = ["acknowledgement", "feed_group", "receipt_word"]
