"""The forecast checked (FCK): a picked suggestion's expected moves are judged once
their targets have settled, and the seat's running record is sent in its own block.

A forecast settles ``forecast.SETTLE_DAYS`` world days after its order is enacted
(every part applied), at the first tick close on or past that day; each move is judged
from the seat's own view by whether its target moved the expected way since the order
was filed. Whether the aide chose is read from the aide's sealed commit and is in the
owner's block only. Every order here is filed through ``agenda_api.pick_option`` or the
aide's close; no test builds a pipeline ``Order`` by hand, and none calls a model.
"""

import json
from datetime import timedelta
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import QuantityId, SeatId
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask, PlayStyle
from revisionist.core.realism.effect import Expect, Risks
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine import options, wake
from revisionist.engine import realism_tick as rt
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import agenda_api, forecast
from tests.test_engine_v2_contract import CAMPAIGN
from tests.test_engine_v2_options import _store
from tests.test_options_expects import _house, _move, _world
from tests.test_order_forecast import T0, _reply, _Same

RISKS = Risks(escalation=2, refusal=1, exposure=0)
STATEMENT = "Make a public statement"


def _offered(store: MemoryStore, seat: SeatId, direction: str = "gain") -> None:
    """The seat's offer for the open wake, every option expecting the House Democrats
    to move ``direction`` by one step."""
    state = load_state(store, CAMPAIGN)
    made = options.offer(state, seat, None)
    assert made is not None
    move = Expect.model_validate(_move("figure", _house(state), direction=direction))
    offers = tuple(
        of.model_copy(
            update={
                "options": tuple(
                    o.model_copy(update={"expects": (move,), "risks": RISKS}) for o in of.options
                )
            }
        )
        for of in made.offers
    )
    rt._append(store, state, made.model_copy(update={"offers": offers}), seat, private_to(seat))


def _block(store: MemoryStore, seat: SeatId) -> Any:
    return agenda_api.agenda(load_state(store, CAMPAIGN), seat, list(store.read(CAMPAIGN)))


def _picked(direction: str = "gain") -> tuple[MemoryStore, SeatId]:
    """A beginner who picked the public statement, a command the seat carries out itself."""
    store, seat = _store(PlayStyle.BEGINNER)
    _offered(store, seat, direction)
    (chosen,) = [o for o in _block(store, seat)["initiative"] if o["label"] == STATEMENT]
    done = agenda_api.pick_option(store, CAMPAIGN, seat, chosen["pick"])
    assert done == {"reply": f"Filed: {STATEMENT}.", "refused": False}
    return store, seat


def _raise_house(store: MemoryStore, seat: SeatId, by: int) -> None:
    """The House Democrats moved by ``by``, as a resolver would set them."""
    state = load_state(store, CAMPAIGN)
    q = state.quantities[QuantityId(_house(state))]
    assert q.value is not None
    moved = q.model_copy(update={"value": q.value + by})
    rt._append(store, state, ev.QuantitySet(quantity=moved), seat)


def _ticks(store: MemoryStore, n: int) -> None:
    for _ in range(n):
        rt.run_realism_tick(store, CAMPAIGN)


def _only_order(state: State) -> rx.RoutedOrder:
    (order,) = state.routed.values()
    return order


# --- rule 1: the pick carries the forecast -----------------------------------------


def test_a_picked_statement_is_reloaded_from_the_log_with_its_forecast() -> None:
    store, seat = _picked()
    reloaded = MemoryStore()
    reloaded.append_all(
        [ev.Event.model_validate_json(e.model_dump_json()) for e in store.read(CAMPAIGN)]
    )
    order = _only_order(load_state(reloaded, CAMPAIGN))
    assert order.issuer == seat
    assert [p.route for p in order.parts] == [rx.Route.COMMAND]
    assert order.forecast is not None
    (move,) = order.forecast.expects
    assert (move.on, move.target, move.direction.value) == (
        rx.ExpectOn.FIGURE,
        _house(load_state(store, CAMPAIGN)),
        "gain",
    )
    assert order.forecast.risks == RISKS


def test_an_order_filed_without_a_suggestion_has_no_forecast() -> None:
    store, seat = _store(PlayStyle.BEGINNER)
    _offered(store, seat)
    statement = [
        Ask.model_validate(
            {"ask": "Speak to the nation.", "effect": {"kind": "statement", "theme": "convoys"}}
        )
    ]
    rt.commit_order(store, CAMPAIGN, seat, statement)
    assert _only_order(load_state(store, CAMPAIGN)).forecast is None
    _ticks(store, 3)
    assert _block(store, seat)["forecast"] == {"checked": 0, "held": 0, "orders": []}


# --- rules 2 and 3: judged once settled, the record in its own block -----------------


def test_the_forecast_is_open_until_it_settles_then_judged() -> None:
    store, seat = _picked()
    block = _block(store, seat)["forecast"]
    (shown,) = block["orders"]
    assert [m["outcome"] for m in shown["moves"]] == ["open"]
    assert shown["settles"] is None, "not enacted yet"
    assert (block["checked"], block["held"]) == (0, 0)
    _ticks(store, 1)  # enacted on 2 September
    (shown,) = _block(store, seat)["forecast"]["orders"]
    assert shown["settles"] == "9 September 1941"
    assert [m["outcome"] for m in shown["moves"]] == ["open"]
    _ticks(store, 2)  # the clock passes 9 September
    block = _block(store, seat)["forecast"]
    (shown,) = block["orders"]
    assert [m["outcome"] for m in shown["moves"]] == ["missed"], "the House did not move"
    assert (block["checked"], block["held"]) == (1, 0)


def test_a_move_the_expected_way_holds() -> None:
    store, seat = _picked()
    _raise_house(store, seat, 3)
    _ticks(store, 3)
    block = _block(store, seat)["forecast"]
    assert [m["outcome"] for m in block["orders"][0]["moves"]] == ["held"]
    assert (block["checked"], block["held"]) == (1, 1)


def test_a_move_after_the_settling_day_does_not_count() -> None:
    store, seat = _picked()
    _ticks(store, 3)
    _raise_house(store, seat, 3)
    _ticks(store, 1)
    block = _block(store, seat)["forecast"]
    assert [m["outcome"] for m in block["orders"][0]["moves"]] == ["missed"]


def test_a_cost_holds_when_the_figure_falls() -> None:
    store, seat = _picked("cost")
    _raise_house(store, seat, -2)
    _ticks(store, 3)
    assert _block(store, seat)["forecast"]["orders"][0]["moves"][0]["outcome"] == "held"


def test_the_block_names_the_move_and_carries_the_order_and_risks() -> None:
    store, seat = _picked()
    (shown,) = _block(store, seat)["forecast"]["orders"]
    asked = _only_order(load_state(store, CAMPAIGN)).parts[0].ask
    assert asked and shown["asked"] == asked
    assert shown["filed"] == "1 September 1941"
    assert shown["aide"] is False
    assert shown["risks"] == {"escalation": 2, "refusal": 1, "exposure": 0}
    (move,) = shown["moves"]
    assert move == {
        "on": "figure",
        "name": "House Democrats",
        "direction": "gain",
        "size": 1,
        "sure": "likely",
        "outcome": "open",
    }


def test_judging_reads_nothing_but_the_log() -> None:
    store, seat = _picked()
    _raise_house(store, seat, 3)
    _ticks(store, 3)
    events = list(store.read(CAMPAIGN))
    assert forecast.judge(events) == forecast.judge(list(events))
    order = _only_order(load_state(store, CAMPAIGN))
    assert forecast.judge(events)[order.order_id] == (forecast.HELD,)


def test_a_kept_fold_gives_what_a_fresh_one_does() -> None:
    """Judged step by step as the log grows, then on another log of the same campaign:
    each answer is the one a fold from the start gives."""
    store, seat = _picked()
    grown: list[dict[Any, Any]] = []
    for _ in range(3):
        grown.append(forecast.judge(list(store.read(CAMPAIGN)), seat))
        _ticks(store, 1)
    forecast._FOLDS.clear()
    events = list(store.read(CAMPAIGN))
    assert forecast.judge(events, seat) == {k: (forecast.MISSED,) for k in grown[0]}
    other, theirs = _picked()
    _raise_house(other, theirs, 3)
    _ticks(other, 3)
    fresh = forecast.judge(list(other.read(CAMPAIGN)))
    forecast._FOLDS.clear()
    assert forecast.judge(list(other.read(CAMPAIGN))) == fresh
    assert list(fresh.values()) == [(forecast.HELD,)]
    assert [list(g.values()) for g in grown] == [[(forecast.OPEN,)]] * 3


# --- rule 4: the aide's choice, to its owner only ------------------------------------


def _aide_played() -> tuple[MemoryStore, SeatId, SeatId]:
    sl, state = _world()
    house = _house(state)
    store = MemoryStore()
    store.append_all(sl.events)
    wake.open_wake(store, CAMPAIGN, T0)
    wake.commit(store, CAMPAIGN, sl.wheeler, T0)
    wake.close_wake(store, CAMPAIGN, T0 + timedelta(hours=12), _Same(_reply(sl, house)))
    return store, sl.fdr, sl.wheeler


def test_an_aide_chosen_action_is_judged_and_marked_to_its_owner() -> None:
    store, fdr, _ = _aide_played()
    (shown,) = _block(store, fdr)["forecast"]["orders"]
    assert shown["aide"] is True
    assert [m["outcome"] for m in shown["moves"]] == ["open"]
    _ticks(store, 3)
    block = _block(store, fdr)["forecast"]
    (shown,) = block["orders"]
    assert shown["aide"] is True
    assert [m["outcome"] for m in shown["moves"]] == ["missed"]
    assert block["checked"] == 1


def test_a_person_s_own_pick_is_not_marked_as_the_aide_s() -> None:
    store, seat = _picked()
    assert _block(store, seat)["forecast"]["orders"][0]["aide"] is False


# --- fog -----------------------------------------------------------------------------


def _strings(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def test_another_seat_never_sees_the_forecast_or_the_aide_mark() -> None:
    store, fdr, wheeler = _aide_played()
    _ticks(store, 3)
    mine = _block(store, fdr)["forecast"]
    theirs = _block(store, wheeler)["forecast"]
    assert mine["orders"] and theirs == {"checked": 0, "held": 0, "orders": []}
    text = _strings(_block(store, wheeler))
    assert mine["orders"][0]["id"] not in text
    assert '"aide": true' not in text


def test_a_figure_the_seat_cannot_see_is_never_judged() -> None:
    """A move whose target is out of the seat's view at either reading is left out, so
    the record never hints at a hidden figure."""
    store, seat = _picked()
    state = load_state(store, CAMPAIGN)
    q = state.quantities[QuantityId(_house(state))]
    hidden = q.model_copy(update={"scope": private_to(SeatId("someone-else")), "value": 999})
    rt._append(store, state, ev.QuantitySet(quantity=hidden), seat)
    _ticks(store, 3)
    block = _block(store, seat)["forecast"]
    assert block["orders"][0]["moves"] == []
    assert (block["checked"], block["held"]) == (0, 0)
    assert "999" not in _strings(block)
    order = _only_order(load_state(store, CAMPAIGN))
    assert forecast.judge(list(store.read(CAMPAIGN)), seat)[order.order_id] == (None,)
