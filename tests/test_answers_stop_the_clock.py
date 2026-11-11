"""The clock stops once for the answers to a human's routed orders: on the day the
last one outstanding lands. A quiet stretch is capped, whatever the seat's horizon."""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, derived_id
from revisionist.core.ontology import Controller
from revisionist.core.realism import advance, apply, reach
from revisionist.core.realism import effect as rx
from revisionist.core.realism.advance import QUIET_DAYS, next_wake
from revisionist.core.realism.card import ChannelKind
from revisionist.core.state import State
from tests.test_engine_v2_contract import CAMPAIGN, Slice

TODAY = date(1941, 9, 1)
GREER = date(1941, 9, 4)


@pytest.fixture
def sl() -> Slice:
    return Slice()


def approach(sl: Slice, who: str, n: int, **part: object) -> rx.RoutedOrder:
    fields: dict[str, object] = {
        "route": rx.Route.INFLUENCE,
        "target": sl.entity(who),
        "effect": rx.MakeStatement(theme="Stand with us"),
    }
    order = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "answer", n)),
        issuer=sl.fdr,
        filed=TODAY,
        parts=(rx.RoutedPart.model_validate(fields | part),),
    )
    sl.add(ev.OrderRouted(order=order))
    return order


def slow_meetings(monkeypatch: pytest.MonkeyPatch, days: int) -> None:
    monkeypatch.setitem(reach.TRANSIT_DAYS, ChannelKind.IN_PERSON, days)


def test_a_command_stops_the_clock_the_day_its_report_arrives(sl: Slice) -> None:
    """Carried out the day after filing; Stark's memo comes in person, a day more."""
    order = sl.shoot_on_sight().model_copy(update={"filed": TODAY})
    sl.add(ev.OrderRouted(order=order))
    wake = next_wake(sl.state, TODAY)
    assert (wake.to, wake.reason.what) == (TODAY + timedelta(days=2), "answer")
    assert wake.reason.label == f"Answer from {sl.state.entities[sl.entity('stark')].name}"
    sl.add(
        ev.OrderExecuted(
            order_id=order.order_id, part=0, on=TODAY + timedelta(days=1), fidelity=rx.Fidelity.FULL
        )
    )
    landed = apply.apply_due(sl.state, TODAY + timedelta(days=1))
    (paper,) = [p for p in landed if isinstance(p, ev.DocumentIssued)]
    assert paper.document.arrives <= wake.to


def test_the_clock_stops_once_when_the_last_answer_is_in(
    sl: Slice, monkeypatch: pytest.MonkeyPatch
) -> None:
    sl.add(ev.OrderRouted(order=sl.shoot_on_sight().model_copy(update={"filed": TODAY})))
    approach(sl, "rayburn", 2)
    assert next_wake(sl.state, TODAY).to == TODAY + timedelta(days=2)
    monkeypatch.setitem(reach.TRANSIT_DAYS, ChannelKind.TELEPHONE, 2)
    wake = next_wake(sl.state.model_copy(update={"scheduled": {}}), TODAY)
    assert (wake.to, wake.reason.what) == (TODAY + timedelta(days=4), "answer")
    assert "Rayburn" in wake.reason.label


def test_history_still_stops_the_clock_before_a_late_answer(
    sl: Slice, monkeypatch: pytest.MonkeyPatch
) -> None:
    slow_meetings(monkeypatch, 5)
    approach(sl, "stark", 1)
    wake = next_wake(sl.state, TODAY)
    assert (wake.to, wake.reason.what) == (GREER, "history")


def test_an_answer_already_given_does_not_stop_the_clock(sl: Slice) -> None:
    approach(sl, "stark", 1, decided=TODAY, accepted=True, applied=TODAY)
    assert next_wake(sl.state, TODAY).reason.what != "answer"


def test_an_ask_no_one_will_rule_on_does_not_stop_the_clock(sl: Slice) -> None:
    approach(sl, "stark", 1, effect=None)
    assert next_wake(sl.state, TODAY).reason.what != "answer"


def test_an_approach_to_a_person_a_player_holds_does_not_stop_the_clock(sl: Slice) -> None:
    approach(sl, "wheeler", 1)
    assert next_wake(sl.state, TODAY).reason.what != "answer"


def test_an_order_from_a_seat_no_player_holds_does_not_stop_the_clock(sl: Slice) -> None:
    approach(sl, "stark", 1)
    state = sl.state
    seats = {
        **state.seats,
        sl.fdr: state.seats[sl.fdr].model_copy(update={"controller": Controller.AI}),
    }
    assert next_wake(state.model_copy(update={"seats": seats}), TODAY).reason.what != "answer"


def far_sighted(state: State, days: int) -> State:
    cards = {k: c.model_copy(update={"horizon_days": days}) for k, c in state.cards.items()}
    return state.model_copy(update={"cards": cards, "scheduled": {}})


def test_a_quiet_stretch_is_capped_whatever_the_horizon(sl: Slice) -> None:
    wake = next_wake(far_sighted(sl.state, 45), TODAY)
    assert (wake.to, wake.reason.what) == (TODAY + timedelta(days=QUIET_DAYS), "horizon")
    assert QUIET_DAYS == 14


def test_a_short_horizon_still_wakes_before_the_cap(sl: Slice) -> None:
    wake = next_wake(far_sighted(sl.state, 5), TODAY)
    assert wake.to == TODAY + timedelta(days=5)


def test_answer_ranks_after_a_step_and_before_history() -> None:
    assert advance.CATEGORIES == ("step", "answer", "history", "agenda", "horizon")
