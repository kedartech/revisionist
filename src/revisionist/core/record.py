"""The game record: one seat's pages, computed from the log (spec §15).

The log stays the only record. These pages are a view of it, rebuilt on every call
and never stored: one page per wake (what arrived, what was filed, what settled,
what was offered) and one ledger line per order part or standard form.

A seat's edition holds what that seat may know. Status, dates and papers come from
``project(state, seat)``; the log is read only for the public wake and calendar
events and for the seat's own filings and offers. The words of an ask are the
issuer's own, so they are read from the seat's own routed orders.
"""

from collections.abc import Sequence
from datetime import date

from revisionist.core import events as ev
from revisionist.core._base import Model
from revisionist.core.events import Event
from revisionist.core.ids import DocumentId, EntityId, OrderId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import apply
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.card import words
from revisionist.core.realism.effect import PartRef, Route, RoutedPart
from revisionist.core.realism.pipeline import SETTLED, Order
from revisionist.core.realism.pipelines import _param_value
from revisionist.core.state import State, View

ON_ITS_WAY = "on its way"


class PaperLine(Model):
    doc_id: DocumentId
    title: str
    author: str
    kind: str
    arrived: date


class OfferLine(Model):
    """One option the seat was offered in a wake."""

    label: str
    to: str | None = None
    taken: bool = False
    """The seat filed exactly this in the wake it was offered."""


class OrderEntry(Model):
    """One ledger line: a part of a routed order, or a standard form."""

    key: str
    wake: int
    """The wake it was filed in. 0 when filed before any wake opened."""
    filed: date
    asked: str
    """A routed part: the seat's own words. A form: its label and terms."""
    to: str | None = None
    """Who it was sent to. None: the seat acts itself, or it runs a pipeline."""
    holder: str | None = None
    """Who has it now, while it is moving."""
    status: str
    moving: bool
    settled: date | None = None


class WakePage(Model):
    number: int
    opened: date
    """The in-world date the wake opened on."""
    days_passed: int
    """In-world days since the wake before it opened."""
    papers: tuple[PaperLine, ...] = ()
    """Papers that reached the seat's desk since the wake before."""
    filed: tuple[str, ...] = ()
    """Ledger keys filed in this wake."""
    settled: tuple[str, ...] = ()
    """Ledger keys settled since the wake before."""
    offered: tuple[OfferLine, ...] = ()


class Record(Model):
    seat: SeatId
    wakes: tuple[WakePage, ...] = ()
    orders: tuple[OrderEntry, ...] = ()
    """The ledger, in the order filed."""


def _name(view: View, who: EntityId | None) -> str | None:
    if who is None:
        return None
    found = view.entities.get(who)
    return found.name if found is not None else "someone"


def _plain(text: str) -> str:
    return " ".join(text.casefold().split())


def _form_words(view: View, order: Order) -> str:
    lever = (
        next((x for x in view.desk.levers if x.name == order.lever), None) if view.desk else None
    )
    label = (lever.label if lever is not None else "") or words(order.lever)
    specs = {p.name: p for p in lever.params} if lever is not None else {}
    terms = [str(_param_value(specs.get(k), v)) for k, v in order.params.items()]
    return f"{label}: {', '.join(terms)}" if terms else label


def _pipeline_state(state: State, view: View, order: Order) -> tuple[str | None, str, date | None]:
    """Holder, status and settled date of an order in a pipeline."""
    if order.status in SETTLED:
        on = order.outcomes[-1].on if order.outcomes else order.filed
        return None, order.status.value, on
    steps = state.pipelines[order.pipeline].steps
    holder = _name(view, steps[order.step].person) if order.step < len(steps) else None
    return holder, ON_ITS_WAY, None


def _form(state: State, view: View, order: Order, wake: int) -> OrderEntry:
    holder, status, settled = _pipeline_state(state, view, order)
    return OrderEntry(
        key=order.order_id,
        wake=wake,
        filed=order.filed,
        asked=_form_words(view, order),
        holder=holder,
        status=status,
        moving=settled is None,
        settled=settled,
    )


def _parts(state: State, view: View, order_id: OrderId, wake: int) -> list[OrderEntry]:
    order = view.routed[order_id]
    asked = state.routed[order_id].parts
    carriers = {o.routed_from: o for o in view.orders.values() if o.routed_from is not None}
    out: list[OrderEntry] = []
    for i, part in enumerate(order.parts):
        to = _name(view, part.executor if part.route is Route.COMMAND else part.target)
        holder, status, settled = to, ON_ITS_WAY, None
        if part.route is Route.PROCESS:
            carrier = carriers.get(PartRef(order_id=order_id, part=i))
            if carrier is not None:
                holder, status, settled = _pipeline_state(state, view, carrier)
        elif part.applied is not None:
            holder, status, settled = None, apply.outcome(part), part.applied
        out.append(
            OrderEntry(
                key=f"{order_id}.{i}",
                wake=wake,
                filed=order.filed,
                asked=asked[i].ask.strip() or apply.describe(state, part),
                to=to,
                holder=holder,
                status=status,
                moving=settled is None,
                settled=settled,
            )
        )
    return out


def _same(ask: Ask, part: RoutedPart) -> bool:
    if ask.effect is not None or part.effect is not None:
        return ask.effect == part.effect
    return _plain(ask.ask) == _plain(part.ask) and ask.target in (part.target, part.executor)


def taken(asks: Sequence[Ask], filed: Sequence[Sequence[RoutedPart]]) -> bool:
    """True when one of ``filed`` (each a routed order's parts) is exactly ``asks``."""
    return any(
        len(parts) == len(asks) and all(_same(a, p) for a, p in zip(asks, parts, strict=True))
        for parts in filed
    )


def build(state: State, events: Sequence[Event], seat: SeatId) -> Record:
    """``seat``'s edition of the record as the log stands."""
    view = project(state, seat)
    opened: list[tuple[int, date]] = []
    wake_of: dict[OrderId, int] = {}
    offers: dict[int, ev.OptionsOffered] = {}
    today: date | None = None
    number = 0
    for e in events:
        p = e.payload
        if isinstance(p, ev.DateAdvanced):
            today = p.to
        elif isinstance(p, ev.WakeOpened):
            number = p.wake
            if today is not None:
                opened.append((number, today))
        elif isinstance(p, ev.OrderRouted | ev.OrderDrafted) and p.order.issuer == seat:
            wake_of[p.order.order_id] = number
        elif isinstance(p, ev.OptionsOffered) and p.seat_id == seat:
            offers[p.wake] = p

    ledger: list[OrderEntry] = []
    for order_id, wake in wake_of.items():
        if order_id in view.routed:
            ledger += _parts(state, view, order_id, wake)
        elif order_id in view.orders and view.orders[order_id].routed_from is None:
            ledger.append(_form(state, view, view.orders[order_id], wake))

    pages: list[WakePage] = []
    before: date | None = None
    for number, day in opened:

        def since(on: date, day: date = day, before: date | None = before) -> bool:
            return on <= day and (before is None or on > before)

        filed = [
            state.routed[k].parts for k, w in wake_of.items() if w == number and k in view.routed
        ]
        made = offers.get(number)
        pages.append(
            WakePage(
                number=number,
                opened=day,
                days_passed=(day - before).days if before is not None else 0,
                papers=tuple(
                    PaperLine(
                        doc_id=d.doc_id,
                        title=d.title,
                        author=_name(view, d.author) or "",
                        kind=d.kind.value,
                        arrived=d.arrives,
                    )
                    for d in sorted(view.documents.values(), key=lambda d: (d.arrives, d.doc_id))
                    if since(d.arrives)
                ),
                filed=tuple(x.key for x in ledger if x.wake == number),
                settled=tuple(x.key for x in ledger if x.settled is not None and since(x.settled)),
                offered=tuple(
                    OfferLine(label=o.label, to=_name(view, o.to), taken=taken(o.asks, filed))
                    for offer in (made.offers if made is not None else ())
                    for o in offer.options
                ),
            )
        )
        before = day
    return Record(seat=seat, wakes=tuple(pages), orders=tuple(ledger))


__all__ = ["OfferLine", "OrderEntry", "PaperLine", "Record", "WakePage", "build", "taken"]
