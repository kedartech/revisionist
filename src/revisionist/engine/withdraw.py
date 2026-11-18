"""A seat takes back its own order before the wake closes (WDR).

An order can be withdrawn while the wake it was filed in is open and its seat has not
committed, and only while it is still at its first step: the order lands as
``OrderSettled(WITHDRAWN)``. After the commit or the close an order stands, and a recall
is a new order. The answer is the same whichever seat has committed first and wherever
the press comes from, because it reads only the log and the seat's own commit.
"""

from collections.abc import Iterable

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.ids import CampaignId, OrderId, SeatId
from revisionist.core.realism.pipeline import SETTLED, Order, OrderStatus
from revisionist.core.state import State
from revisionist.engine import realism_tick
from revisionist.engine.store import EventStore, load_state

NO_SUCH = "There is no such order of yours to withdraw."
STANDS = "It stands: send a new order to recall it."


def _filed_in_open_wake(log: Iterable[Event]) -> set[OrderId]:
    """Orders drafted since the latest wake opened (held ones are filed after it opens)."""
    filed: set[OrderId] = set()
    for event in log:
        payload = event.payload
        if isinstance(payload, ev.WakeOpened):
            filed.clear()
        elif isinstance(payload, ev.OrderDrafted):
            filed.add(payload.order.order_id)
    return filed


def _own(state: State, seat: SeatId, order_id: str) -> Order | None:
    order = state.orders.get(OrderId(order_id))
    if order is None or order.issuer != seat or order.routed_from is not None:
        return None
    return order


def _open(state: State, seat: SeatId, *, sealed: bool) -> str | None:
    wake = state.wake
    if wake is None or wake.closed or sealed:
        return f"The wake has closed, so the order has gone out. {STANDS}"
    if seat in wake.committed:
        return f"You have committed this wake, so your orders are sealed. {STANDS}"
    return None


def _refusal(
    state: State, seat: SeatId, order_id: str, filed: set[OrderId], *, sealed: bool
) -> str | None:
    order = _own(state, seat, order_id)
    if order is None:
        return NO_SUCH
    if order.status in SETTLED:
        return f"It is already {order.status.value}."
    if (why := _open(state, seat, sealed=sealed)) is not None:
        return why
    if order.step != 0 or order.outcomes:
        return f"It has already moved on. {STANDS}"
    if order.order_id not in filed:
        return f"It was sent in an earlier wake. {STANDS}"
    return None


def refusal(
    state: State, log: Iterable[Event], seat: SeatId, order_id: str, *, sealed: bool
) -> str | None:
    """Why the seat cannot withdraw the order now; None when it can. ``sealed`` is true
    while a close is running or the seat is being handed to a new player."""
    return _refusal(state, seat, order_id, _filed_in_open_wake(log), sealed=sealed)


def withdrawable(
    state: State, log: Iterable[Event], seat: SeatId, *, sealed: bool
) -> list[OrderId]:
    """The seat's own orders it could withdraw now, oldest first."""
    filed = _filed_in_open_wake(log)
    return [
        o.order_id
        for o in sorted(state.orders.values(), key=lambda o: (o.filed, o.order_id))
        if _refusal(state, seat, str(o.order_id), filed, sealed=sealed) is None
    ]


def withdraw_order(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, order_id: str, *, sealed: bool
) -> Order:
    """Settle the seat's own order as withdrawn. Raises ``ValueError`` with the reason."""
    state = load_state(store, campaign_id)
    why = refusal(state, store.read(campaign_id), seat, order_id, sealed=sealed)
    if why is not None:
        raise ValueError(why)
    order = state.orders[OrderId(order_id)]
    payload = ev.OrderSettled(order_id=order.order_id, status=OrderStatus.WITHDRAWN)
    realism_tick._append(store, state, payload, seat)
    return order.model_copy(update={"status": OrderStatus.WITHDRAWN})
