"""A seat cannot file the same ask again while the first is still on its way; once the
first is refused or turned down, it can."""

from datetime import date

import pytest

from revisionist.core import events as ev
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.visibility import private_to
from revisionist.engine.realism_tick import commit_order, file_order
from revisionist.engine.store import MemoryStore, load_state
from tests.test_engine_v2_contract import CAMPAIGN, Slice


def shoot(sl: Slice) -> Ask:
    return Ask(
        ask="Shoot on sight.",
        effect=rx.SetEngagement(
            force=sl.feature("us_atlantic_fleet"),
            zone="western Atlantic",
            rule=rx.Engagement.SHOOT_ON_SIGHT,
        ),
    )


def store_of(sl: Slice) -> MemoryStore:
    store = MemoryStore()
    store.append_all(sl.events)
    return store


def routed(store: MemoryStore) -> int:
    return len(load_state(store, CAMPAIGN).routed)


def test_the_same_ask_is_refused_while_the_first_is_pending() -> None:
    sl = Slice()
    store = store_of(sl)
    commit_order(store, CAMPAIGN, sl.fdr, [shoot(sl)])
    with pytest.raises(ValueError, match="already"):
        commit_order(store, CAMPAIGN, sl.fdr, [shoot(sl)])
    assert routed(store) == 1


def test_the_same_ask_twice_in_one_order_is_refused() -> None:
    sl = Slice()
    store = store_of(sl)
    with pytest.raises(ValueError, match="already"):
        commit_order(store, CAMPAIGN, sl.fdr, [shoot(sl), shoot(sl)])
    assert routed(store) == 0


def test_a_refused_order_can_be_sent_again() -> None:
    sl = Slice()
    first = sl.shoot_on_sight()
    sl.add(ev.OrderRouted(order=first), private_to(sl.fdr))
    sl.add(
        ev.OrderExecuted(
            order_id=first.order_id, part=0, on=date(1941, 9, 11), refusal="loyalty -4"
        ),
        private_to(sl.fdr),
    )
    store = store_of(sl)
    commit_order(store, CAMPAIGN, sl.fdr, [shoot(sl)])
    assert routed(store) == 2


def test_a_different_ask_is_not_a_duplicate() -> None:
    sl = Slice()
    store = store_of(sl)
    commit_order(store, CAMPAIGN, sl.fdr, [shoot(sl)])
    defend = shoot(sl).model_copy(
        update={
            "effect": rx.SetEngagement(
                force=sl.feature("us_atlantic_fleet"),
                zone="western Atlantic",
                rule=rx.Engagement.DEFEND,
            )
        }
    )
    commit_order(store, CAMPAIGN, sl.fdr, [defend])
    assert routed(store) == 2


def bill(store: MemoryStore, sl: Slice) -> None:
    file_order(store, CAMPAIGN, sl.fdr, "send_bill", {"bill": "neutrality_revision"})


def test_the_same_form_is_refused_while_the_first_is_moving_and_says_where() -> None:
    sl = Slice()
    store = store_of(sl)
    bill(store, sl)
    with pytest.raises(ValueError, match="already") as refused:
        bill(store, sl)
    state = load_state(store, CAMPAIGN)
    (order,) = state.orders.values()
    holder = state.entities[state.pipelines[order.pipeline].steps[order.step].person].name
    assert holder in str(refused.value)
    assert len(state.orders) == 1


def test_a_form_can_be_filed_again_once_the_first_is_settled() -> None:
    sl = Slice()
    store = store_of(sl)
    bill(store, sl)
    (first,) = load_state(store, CAMPAIGN).orders
    sl2 = Slice()
    sl2.events = list(store.read(CAMPAIGN))
    sl2.add(ev.OrderSettled(order_id=first, status=OrderStatus.REFUSED))
    store = store_of(sl2)
    bill(store, sl)
    assert len(load_state(store, CAMPAIGN).orders) == 2


def test_the_same_words_to_the_same_person_are_refused_while_pending() -> None:
    sl = Slice()
    store = store_of(sl)
    ask = Ask(ask="Hold the fleet at Argentia.", target=sl.entity("wheeler"))
    commit_order(store, CAMPAIGN, sl.fdr, [ask])
    again = ask.model_copy(update={"ask": "  hold the fleet at argentia. "})
    with pytest.raises(ValueError, match="already"):
        commit_order(store, CAMPAIGN, sl.fdr, [again])
    assert routed(store) == 1
    other = ask.model_copy(update={"target": sl.entity("rayburn")})
    commit_order(store, CAMPAIGN, sl.fdr, [other])
    assert routed(store) == 2
