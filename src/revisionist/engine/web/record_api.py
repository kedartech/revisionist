"""The seat's record block for the room (Train 2 unit S1): its orders and the latest wake.

Built from ``core.record.build``, so it holds only what the seat's own edition holds.
Days are worded; ledger keys become opaque tokens, so no order id or entity id leaves.
"""

from collections.abc import Sequence
from datetime import date
from hashlib import sha256

from revisionist.core import record
from revisionist.core.events import Event
from revisionist.core.ids import OrderId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import advance
from revisionist.core.realism.apply import report_doc_id
from revisionist.core.realism.document import DocumentView
from revisionist.core.realism.effect import PartView
from revisionist.core.realism.pipelines import reply_doc_id
from revisionist.core.state import State, View
from revisionist.engine.web import results
from revisionist.engine.web.realism_api import Receipt, RecordBlock, RecordOrder, RecordWake
from revisionist.engine.web.tray import receipt_word


def _day(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def _token(key: str) -> str:
    return sha256(key.encode()).hexdigest()[:12]


def _part_of(key: str) -> tuple[OrderId, int] | None:
    """A routed ledger key is ``<order_id>.<part>``; a standard form's key has no dot."""
    order_id, dot, part = key.rpartition(".")
    return (OrderId(order_id), int(part)) if dot else None


def _receipt(state: State, view: View, key: str) -> Receipt | None:
    """The paper that answers a ledger line, when it only acknowledges the order. A routed
    part is answered by its report. A form has one reply per step: it takes a receipt only
    while every reply that reached the seat is a receipt, the latest one giving the line."""
    part = _part_of(key)
    found: list[tuple[DocumentView, PartView | None]]
    if part is not None:
        order_id, i = part
        doc = view.documents.get(report_doc_id(state.campaign_id, order_id, i))
        found = [(doc, view.routed[order_id].parts[i])] if doc is not None else []
    else:
        order = view.orders[OrderId(key)]
        replies = (
            view.documents.get(reply_doc_id(state.campaign_id, order.order_id, n))
            for n in range(len(order.outcomes))
        )
        found = [(doc, None) for doc in replies if doc is not None]
    words = [receipt_word(doc, part) for doc, part in found]
    word = words[-1] if words else None
    if word is None or None in words:
        return None
    doc = found[-1][0]
    return Receipt(word=word, day=_day(doc.arrives), doc=doc.doc_id)


def _entry(state: State, view: View, e: record.OrderEntry) -> RecordOrder:
    part = _part_of(e.key)
    due = said = None
    if part is not None:
        order_id, i = part
        if e.moving:
            answer = advance.answer_due(state, state.routed[order_id], i)
            due = _day(answer[0]) if answer is not None else None
        routed = view.routed[order_id]
        said = results.said_for(view, routed, i) or routed.parts[i].reason or None
    return RecordOrder(
        id=_token(e.key),
        wake=e.wake,
        filed=_day(e.filed),
        settled=_day(e.settled) if e.settled is not None else None,
        asked=e.asked,
        to=e.to,
        holder=e.holder,
        status=e.status,
        moving=e.moving,
        track=e.key if part is None else None,
        due=due,
        said=said,
        receipt=_receipt(state, view, e.key),
    )


def record_block(state: State, events: Sequence[Event], seat: SeatId) -> RecordBlock:
    """``seat``'s orders, newest filed first, and its latest wake page."""
    view = project(state, seat)
    ledger = record.build(state, events, seat)
    orders = [
        _entry(state, view, e)
        for e in sorted(reversed(ledger.orders), key=lambda e: e.filed, reverse=True)
    ]
    page = ledger.wakes[-1] if ledger.wakes else None
    wake = (
        RecordWake(
            number=page.number,
            opened=_day(page.opened),
            days_passed=page.days_passed,
            papers=len(page.papers),
            filed=[_token(k) for k in page.filed],
            settled=[_token(k) for k in page.settled],
        )
        if page is not None
        else None
    )
    return RecordBlock(orders=orders, wake=wake)


__all__ = ["record_block"]
