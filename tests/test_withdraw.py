"""Withdrawing a pending order (WDR).

A seat may take back its own order that has not moved and was filed in the wake that is
open, until it commits; a held order is taken back by dropping it from the queue. Same
harness as ``tests/test_web_held_orders.py``.
"""

from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.engine import withdraw
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_held_orders import BILL, WORLD, both_commit, held_of
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, log_of, seat_of, state_of


@pytest.fixture
def duo(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    bea = game.seat("bea", "churchill")
    make_host(game, ada)
    begin(game)
    return game, ada, bea


def mine(game: Realism, who: str) -> list[Order]:
    seat = seat_of(game, who)
    return [o for o in state_of(game).orders.values() if o.issuer == seat]


def file_bill(game: Realism, client: Client, who: str) -> str:
    status, out = post(client, "lever", **BILL)
    assert status == 200 and out["refused"] is False, out
    (order,) = mine(game, who)
    return str(order.order_id)


def settled(game: Realism, order_id: str) -> list[ev.OrderSettled]:
    return [
        e.payload
        for e in log_of(game)
        if isinstance(e.payload, ev.OrderSettled) and e.payload.order_id == order_id
    ]


def withdrawable_of(client: Client) -> list[str]:
    return list(client.me()["game"]["withdrawable"])


# --- rule 1: a seat's own unmoved order, filed in the open wake, before it commits ----------


def test_a_seat_withdraws_its_own_unmoved_order_filed_in_the_open_wake(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, _ = duo
    order_id = file_bill(game, ada, "roosevelt")
    assert withdrawable_of(ada) == [order_id]
    status, out = post(ada, "withdraw", order_id=order_id)
    assert status == 200 and out["refused"] is False, out
    (landed,) = settled(game, order_id)
    assert landed.status is OrderStatus.WITHDRAWN
    assert state_of(game).orders[landed.order_id].status is OrderStatus.WITHDRAWN
    assert withdrawable_of(ada) == []
    (shown,) = realism_of(ada)["orders"]["orders"]
    assert shown["status"] == "withdrawn"


def test_another_seats_order_is_not_withdrawn(duo: tuple[Realism, Client, Client]) -> None:
    game, ada, bea = duo
    order_id = file_bill(game, ada, "roosevelt")
    assert withdrawable_of(bea) == []
    status, out = post(bea, "withdraw", order_id=order_id)
    assert status == 200 and out["refused"] is True, out
    assert settled(game, order_id) == []
    assert state_of(game).orders[mine(game, "roosevelt")[0].order_id].status is OrderStatus.MOVING


def test_an_unknown_order_and_a_request_naming_nothing_are_refused(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, _ = duo
    file_bill(game, ada, "roosevelt")
    assert post(ada, "withdraw", order_id="nope")[1]["refused"] is True
    assert post(ada, "withdraw")[1]["refused"] is True
    assert post(ada, "withdraw", order_id="x", held_id=1)[1]["refused"] is True
    assert [e for e in log_of(game) if isinstance(e.payload, ev.OrderSettled)] == []


def test_an_order_that_has_taken_a_step_is_not_withdrawn(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, _ = duo
    order_id = file_bill(game, ada, "roosevelt")
    state = state_of(game)
    seat = seat_of(game, "roosevelt")
    moved = state.orders[mine(game, "roosevelt")[0].order_id].model_copy(update={"step": 1})
    gone = state.model_copy(update={"orders": {moved.order_id: moved}})
    log = log_of(game)
    assert withdraw.refusal(state, log, seat, order_id, sealed=False) is None
    assert withdraw.refusal(gone, log, seat, order_id, sealed=False) is not None
    assert withdraw.withdrawable(gone, log, seat, sealed=False) == []


def test_an_order_filed_in_an_earlier_wake_is_not_withdrawn(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    order_id = file_bill(game, ada, "roosevelt")
    both_commit(ada, bea)
    assert realism_of(ada)["wake"]["wake"] == 1
    assert state_of(game).orders[mine(game, "roosevelt")[0].order_id].step == 0
    assert withdrawable_of(ada) == []
    status, out = post(ada, "withdraw", order_id=order_id)
    assert status == 200 and out["refused"] is True, out
    assert settled(game, order_id) == []


# --- rule 2: not after the close, not after the seat's commit ------------------------------


def test_a_withdrawal_after_the_seat_has_committed_is_refused_and_not_held(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, _ = duo
    order_id = file_bill(game, ada, "roosevelt")
    assert not post(ada, "commit")[1]["refused"]
    assert withdrawable_of(ada) == []
    status, out = post(ada, "withdraw", order_id=order_id)
    assert status == 200 and out["refused"] is True and "held" not in out, out
    assert "new" in out["reply"], "a recall is a new move order"
    assert held_of(ada) == []
    assert settled(game, order_id) == []


def test_a_withdrawal_after_the_close_or_while_it_closes_is_refused(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, _ = duo
    order_id = file_bill(game, ada, "roosevelt")
    state, log, seat = state_of(game), log_of(game), seat_of(game, "roosevelt")
    assert state.wake is not None
    closed = state.model_copy(update={"wake": state.wake.model_copy(update={"closed": True})})
    assert withdraw.refusal(state, log, seat, order_id, sealed=False) is None
    assert withdraw.refusal(closed, log, seat, order_id, sealed=False) is not None
    assert withdraw.refusal(state, log, seat, order_id, sealed=True) is not None
    assert withdraw.withdrawable(closed, log, seat, sealed=False) == []
    assert withdraw.withdrawable(state, log, seat, sealed=True) == []


def test_it_is_the_same_whether_the_other_seat_has_committed_first(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    order_id = file_bill(game, ada, "roosevelt")
    assert not post(bea, "commit")[1]["refused"]
    status, out = post(ada, "withdraw", order_id=order_id)
    assert status == 200 and out["refused"] is False, out
    assert [s.status for s in settled(game, order_id)] == [OrderStatus.WITHDRAWN]


# --- rule 3: the twin-form check ignores withdrawn orders -----------------------------------


def test_the_same_form_can_be_sent_again_once_the_first_is_withdrawn(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, _ = duo
    order_id = file_bill(game, ada, "roosevelt")
    again = post(ada, "lever", **BILL)[1]
    assert again["refused"] is True and "already sent" in again["reply"], again
    assert post(ada, "withdraw", order_id=order_id)[1]["refused"] is False
    status, out = post(ada, "lever", **BILL)
    assert status == 200 and out["refused"] is False, out
    assert len(mine(game, "roosevelt")) == 2
    assert withdrawable_of(ada) == [
        str(o.order_id) for o in mine(game, "roosevelt") if o.status is OrderStatus.MOVING
    ]


# --- rule 4: a held order is withdrawn by dropping it from the queue -----------------------


def test_a_held_order_withdrawn_before_the_close_is_never_filed(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    assert not post(ada, "commit")[1]["refused"]
    out: dict[str, Any] = post(ada, "lever", **BILL)[1]
    held_id = out["held"]
    assert [x["id"] for x in held_of(ada)] == [held_id]
    status, done = post(ada, "withdraw", held_id=held_id)
    assert status == 200 and done["refused"] is False, done
    assert held_of(ada) == []
    post(bea, "commit")
    assert mine(game, "roosevelt") == []
    assert [e for e in log_of(game) if isinstance(e.payload, ev.OrderSettled)] == []


def test_another_seats_held_order_or_one_already_filed_is_not_withdrawn(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    assert not post(ada, "commit")[1]["refused"]
    held_id = post(ada, "lever", **BILL)[1]["held"]
    assert post(bea, "withdraw", held_id=held_id)[1]["refused"] is True
    assert [x["id"] for x in held_of(ada)] == [held_id]
    post(bea, "commit")
    assert len(mine(game, "roosevelt")) == 1, "filed at the opening"
    status, out = post(ada, "withdraw", held_id=held_id)
    assert status == 200 and out["refused"] is True, out
    assert len(mine(game, "roosevelt")) == 1
