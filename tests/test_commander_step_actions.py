"""A commander's step on his superior's order offers only pass and stall.

In 1941 the President's naval order crosses Admiral King's desk at a step whose own set is
pass, expedite, stall and refuse. King answers to the President, and with ``command`` on he
may only pass or stall it (``pipelines.step_allowed``); with ``defiance`` on, as the 1941 world
has it since the offices item, he may also refuse it. What needs him lists exactly those;
his aide is given the same set; an action he was not offered is refused in one plain
sentence that names no step, action or id. With ``command`` off the step keeps its own set.
"""

from datetime import date
from typing import Any

import pytest

from revisionist.core.ids import SeatId
from revisionist.core.project import project
from revisionist.core.realism import pipelines
from revisionist.core.realism.pipeline import Order, StepAction
from revisionist.core.state import Rule, State
from revisionist.engine import aide
from revisionist.engine.web import agenda_api
from tests.test_realism_resolvers import Rig
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, seat_of, state_of

FILED = date(1941, 9, 11)
NOT_OFFERED = "You cannot do that with this order."
TERMS = {"order": "escort_convoys", "zone": "western_atlantic"}
NAVAL = {"lever": "naval_order", "params": TERMS}


def _at_king(*, command: bool = True) -> tuple[Rig, Order]:
    """The President's naval order, through Admiral Stark's step, at King's."""
    r = Rig("autumn-1941")
    r.seat("roosevelt")
    r.seat("king")
    r.close_session_zero()
    if not command:
        r.state = r.state.model_copy(update={"rules": r.state.rules - {Rule.COMMAND}})
    order = r.draft("roosevelt", "naval_order", "naval_order", FILED, **TERMS)
    r.pass_steps(order, [FILED])
    r.state = r.state.model_copy(update={"in_world_date": FILED})
    order = r.state.orders[order.order_id]
    assert pipelines.held_by_another(r.state, order) == r.seats["king"]
    return r, order


def _king_actions(state: State, seat: SeatId) -> list[list[str]]:
    return [item["actions"] for item in agenda_api.held_steps(state, seat)]


def test_the_step_itself_allows_expedite_and_refuse() -> None:
    r, order = _at_king()
    step = r.state.pipelines[order.pipeline].steps[order.step]
    assert {StepAction.EXPEDITE, StepAction.REFUSE} <= step.allowed


def test_what_needs_king_offers_pass_stall_and_refuse_only() -> None:
    r, _ = _at_king()
    assert _king_actions(r.state, r.seats["king"]) == [["stall", "refuse", "pass"]]


def test_with_command_off_king_is_offered_the_steps_own_set_without_amend() -> None:
    r, _ = _at_king(command=False)
    assert _king_actions(r.state, r.seats["king"]) == [["expedite", "stall", "refuse", "pass"]]


def test_a_step_on_an_order_not_from_up_his_chain_keeps_its_own_set() -> None:
    r, order = _at_king()
    # Hold the President's chain off King: nobody above him issued it.
    cards = dict(r.state.cards)
    king = r.state.seats[r.seats["king"]].embodies
    cards[king] = cards[king].model_copy(update={"principals": ()})
    state = r.state.model_copy(update={"cards": cards})
    assert not pipelines.under_issuer(state, order)
    assert _king_actions(state, r.seats["king"]) == [["expedite", "stall", "refuse", "pass"]]


@pytest.mark.parametrize("command", [True, False])
def test_the_aide_is_given_what_the_step_allows_each_seat(command: bool) -> None:
    r, order = _at_king(command=command)
    for seat in r.seats.values():
        for decision in aide.decisions_due(project(r.state, seat), r.state.pipelines):
            held = r.state.orders[decision.order_id]
            want = sorted(a.value for a in pipelines.step_allowed(r.state, held))
            assert list(decision.allowed) == want
    king_view = project(r.state, r.seats["king"])
    assert order.order_id not in {
        d.order_id for d in aide.decisions_due(king_view, r.state.pipelines)
    }


# --- the room ---------------------------------------------------------------------------


@pytest.fixture
def room(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    game = Realism(web, "autumn-1941")
    roosevelt = game.seat("fdr", "roosevelt")
    king = game.seat("king", "king")
    make_host(game, roosevelt)
    begin(game)
    return game, roosevelt, king


def _close(*clients: Client) -> None:
    for who in clients:
        status, out = post(who, "commit")
        assert status == 200 and not out["refused"], out


def _decision(game: Realism, roosevelt: Client, king: Client) -> dict[str, Any]:
    """The President's naval order, filed and moved until it waits at King's step: his item."""
    status, out = post(roosevelt, "lever", **NAVAL)
    assert status == 200 and not out["refused"], out
    for _ in range(8):
        state = state_of(game)
        if any(
            pipelines.held_by_another(state, o) == seat_of(game, "king")
            for o in state.orders.values()
        ):
            (item,) = [i for i in realism_of(king)["agenda"]["items"] if i["kind"] == "Decision"]
            return dict(item)
        _close(roosevelt, king)
    raise AssertionError("the naval order never reached King's step")


def test_king_sees_pass_stall_and_refuse_and_is_refused_the_rest_in_plain_words(
    room: tuple[Realism, Client, Client],
) -> None:
    game, roosevelt, king = room
    item = _decision(game, roosevelt, king)
    assert item["actions"] == ["stall", "refuse", "pass"]
    for action in ("expedite", "amend", "leak"):
        status, out = post(king, "step", order_id=item["id"], action=action)
        assert status == 200 and out["refused"], out
        assert out["reply"] == NOT_OFFERED
    status, out = post(king, "step", order_id=item["id"], action="stall")
    assert status == 200 and not out["refused"], out


def test_once_king_has_committed_the_held_queue_refuses_the_same_way(
    room: tuple[Realism, Client, Client],
) -> None:
    game, roosevelt, king = room
    item = _decision(game, roosevelt, king)
    status, out = post(king, "commit")
    assert status == 200 and not out["refused"], out
    status, out = post(king, "step", order_id=item["id"], action="expedite")
    assert status == 200 and out["refused"], out
    assert out["reply"] == NOT_OFFERED
