"""Only the holder acts at a step, and the holder can decide a held step.

A decision step that one human seat's leader holds on another seat's order is that
holder's alone. It is listed on the holder's agenda as an item of kind "Decision",
whose id is the paper that brought it; the ``step`` action takes that id in place of
an order id. The issuer cannot act at the step, directly or through the held queue,
and the issuer's order id never reaches the holder. Same harness as
``tests/test_web_answer.py``, in the realism toy: Ada files a levy, Bram decides it.
"""

import json
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import OrderId
from revisionist.core.realism import pipelines
from revisionist.core.realism.pipeline import StepAction
from revisionist.engine import realism_tick
from revisionist.engine.web import held
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, log_of, seat_of, state_of

NOT_YOURS = "That decision is not yours to take."
LEVY = {"lever": "propose_levy", "params": {"rate": 8, "purpose": "harbour"}}


@pytest.fixture
def toy(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    game = Realism(web)
    ada = game.seat("ada", "ada")
    bram = game.seat("bram", "bram")
    make_host(game, ada)
    begin(game)
    return game, ada, bram


def _close(ada: Client, bram: Client) -> None:
    for who in (ada, bram):
        status, out = post(who, "commit")
        assert status == 200 and not out["refused"], out


def _decisions(client: Client) -> list[dict[str, Any]]:
    return [i for i in realism_of(client)["agenda"]["items"] if i["kind"] == "Decision"]


def _held_at_bram(game: Realism, ada: Client, bram: Client) -> OrderId:
    """Ada's levy, filed and moved until it waits at Bram's step."""
    status, out = post(ada, "lever", **LEVY)
    assert status == 200 and not out["refused"], out
    (order_id,) = state_of(game).orders
    for _ in range(6):
        state = state_of(game)
        if pipelines.held_by_another(state, state.orders[order_id]) == seat_of(game, "bram"):
            return order_id
        _close(ada, bram)
    raise AssertionError("the levy never reached Bram's step")


def _item(bram: Client) -> dict[str, Any]:
    """Bram's one held decision on his agenda."""
    (item,) = _decisions(bram)
    return item


def _bram_steps(game: Realism, order_id: OrderId) -> list[ev.OrderStepTaken]:
    return [
        e.payload
        for e in log_of(game)
        if isinstance(e.payload, ev.OrderStepTaken)
        and e.payload.order_id == order_id
        and e.payload.outcome.step == 1
    ]


def test_the_issuer_cannot_act_at_the_step_another_player_holds(
    toy: tuple[Realism, Client, Client],
) -> None:
    game, ada, bram = toy
    order_id = _held_at_bram(game, ada, bram)
    _, out = post(ada, "step", order_id=str(order_id), action="pass")
    assert out == {"reply": NOT_YOURS, "refused": True}, out
    assert _bram_steps(game, order_id) == []
    assert state_of(game).orders[order_id].step == 1
    assert _decisions(ada) == []


def test_the_holder_decides_a_held_step_before_its_due_day_and_the_card_does_not(
    toy: tuple[Realism, Client, Client],
) -> None:
    game, ada, bram = toy
    order_id = _held_at_bram(game, ada, bram)
    item = _item(bram)
    state = state_of(game)
    due = pipelines.held_due(state, state.orders[order_id])
    today = state.in_world_date
    assert due is not None and today is not None and today < due
    assert item["issuer"] == "Ada Mor"
    assert item["options"] == [] and item["plan"] == [] and item["cause"] is None
    assert "levy" in item["text"].lower()
    assert item["deadline"] == f"{due.day} {due:%B %Y}"
    status, out = post(bram, "step", order_id=item["id"], action="pass")
    assert status == 200 and not out["refused"], out
    (taken,) = _bram_steps(game, order_id)
    assert (taken.outcome.action, taken.outcome.on) == (StepAction.PASS, today)
    assert _decisions(bram) == []
    for _ in range(3):
        _close(ada, bram)
    assert state_of(game).in_world_date > due  # type: ignore[operator]
    assert len(_bram_steps(game, order_id)) == 1, "the card decided again"


def test_the_issuers_order_id_never_reaches_the_holder(
    toy: tuple[Realism, Client, Client],
) -> None:
    game, ada, bram = toy
    order_id = _held_at_bram(game, ada, bram)
    item = _item(bram)
    assert str(order_id) not in item["id"]
    _, out = post(ada, "step", order_id=item["id"], action="pass")
    assert out["refused"] is True, out
    assert str(order_id) not in json.dumps(bram.me())


def test_the_issuer_cannot_act_at_the_holders_step_through_the_held_queue(
    toy: tuple[Realism, Client, Client],
) -> None:
    game, ada, bram = toy
    order_id = _held_at_bram(game, ada, bram)
    assert not post(ada, "commit")[1]["refused"]
    _, out = post(ada, "step", order_id=str(order_id), action="pass")
    assert out == {"reply": NOT_YOURS, "refused": True}, out
    assert list(ada.me()["game"]["held"]) == []
    store = game.web.app.open()
    try:
        args = {"order_id": str(order_id), "action": "pass", "params": {}}
        filed = held.file_one(store, game.campaign, seat_of(game, "ada"), "step", args)
        assert filed == NOT_YOURS
        by_holder = {"order_id": str(order_id), "action": "pass", "params": {}}
        assert held.file_one(store, game.campaign, seat_of(game, "bram"), "step", by_holder) is None
    finally:
        store.close()
    (taken,) = _bram_steps(game, order_id)
    assert taken.outcome.action is StepAction.PASS


def test_a_step_on_a_seats_own_order_at_its_own_leader_is_still_its_own(
    toy: tuple[Realism, Client, Client],
) -> None:
    """take_step with the holder's seat goes through; with any other seat it is refused."""
    game, ada, bram = toy
    order_id = _held_at_bram(game, ada, bram)
    store = game.web.app.open()
    try:
        with pytest.raises(ValueError, match=NOT_YOURS):
            realism_tick.take_step(
                store, game.campaign, seat_of(game, "ada"), str(order_id), StepAction.PASS, {}
            )
        order = realism_tick.take_step(
            store, game.campaign, seat_of(game, "bram"), str(order_id), StepAction.PASS, {}
        )
    finally:
        store.close()
    assert order.step >= 1 and len(_bram_steps(game, order_id)) == 1
