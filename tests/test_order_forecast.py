"""The forecast stored with the order (FCS): a picked suggestion's expected moves and
risks ride on the routed order it files, private to the issuer.

``RoutedOrder.forecast`` is a late field, empty by default, so an older log reads and
writes the same bytes. ``commit_order`` takes it; the aide's path passes the forecast of
the option the aide chose. A pipeline ``Order`` made from a routed part carries no copy:
the forecast is read by the routed order's id. No rule reads it, so an order with and
without it has the same outcome. No test here calls a model.
"""

import json
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import state_hash
from revisionist.core.ids import CampaignId, SeatId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.pipeline import Order
from revisionist.core.visibility import private_to
from revisionist.engine import options, wake
from revisionist.engine import realism_tick as rt
from revisionist.engine.llm import Reply, Request
from revisionist.engine.store import MemoryStore, load_state
from tests.test_engine_v2_contract import CAMPAIGN, Slice
from tests.test_engine_v2_options import _parts
from tests.test_engine_v2_process import HISTORICAL, _seated
from tests.test_options_expects import _house, _move, _world

T0 = datetime(2026, 11, 20, 12, tzinfo=UTC)
RISKS = rx.Risks(escalation=2, refusal=1, exposure=0)


def _forecast(target: str) -> rx.Forecast:
    return rx.Forecast(expects=(rx.Expect.model_validate(_move("figure", target)),), risks=RISKS)


# --- the field ----------------------------------------------------------------------

# An ``order_routed`` payload as main wrote it at schema 58, before the field existed
# (``commit_order`` of the neutrality revision, dumped at 99d54e6).
OLD_ROUTED = (
    '{"kind":"order_routed","order":{"order_id":"01M7Y4X6D859BBC39MHYVVNQRB",'
    '"issuer":"8GC9N6C4ZTJEATM2617MQN6R41","filed":"1941-09-01","parts":[{"route":"process",'
    '"effect":{"kind":"measure","title":"Neutrality Act revision","clauses":[{"kind":"power",'
    '"subject":"arm merchant ships","amount":null},{"kind":"limit",'
    '"subject":"war zones closed to American ships","amount":null}]},"domain":null,'
    '"executor":null,"pipeline":"3V2DEMCEN6BN89DRHN92VF3JV3","target":null,"reason":"",'
    '"fidelity":null,"refusal":"","executed":null,"estimated":[],"was_estimated":false,'
    '"ask":"Revise the act."}]}}'
)


def test_an_old_routed_order_reads_and_writes_the_same_bytes() -> None:
    payload = ev.OrderRouted.model_validate_json(OLD_ROUTED)
    assert payload.order.forecast is None
    assert payload.model_dump_json() == OLD_ROUTED


def test_an_old_log_replays_byte_for_byte() -> None:
    store, fdr = _seated()
    rt.commit_order(store, CAMPAIGN, fdr, [Ask(ask="Revise the act.", effect=HISTORICAL)])
    rt.run_realism_tick(store, CAMPAIGN)
    events = list(store.read(CAMPAIGN))
    assert any(isinstance(e.payload, ev.OrderRouted) for e in events)
    for e in events:
        text = e.model_dump_json()
        assert '"forecast"' not in text
        assert ev.Event.model_validate_json(text).model_dump_json() == text
    again = MemoryStore()
    again.append_all([ev.Event.model_validate_json(e.model_dump_json()) for e in events])
    assert state_hash(load_state(again, CAMPAIGN)) == state_hash(load_state(store, CAMPAIGN))


def test_the_forecast_rides_the_routed_order_and_survives_the_fold() -> None:
    store, fdr = _seated()
    house = _house(load_state(store, CAMPAIGN))
    made = rt.commit_order(
        store, CAMPAIGN, fdr, [Ask(ask="Revise the act.", effect=HISTORICAL)], _forecast(house)
    )
    assert made.forecast == _forecast(house)
    (routed,) = [e for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.OrderRouted)]
    assert isinstance(routed.payload, ev.OrderRouted)
    assert routed.payload.order.forecast == _forecast(house)
    assert routed.scope == private_to(fdr)
    assert load_state(store, CAMPAIGN).routed[made.order_id].forecast == _forecast(house)


def test_an_empty_forecast_is_stored_as_none() -> None:
    store, fdr = _seated()
    made = rt.commit_order(
        store, CAMPAIGN, fdr, [Ask(ask="Revise the act.", effect=HISTORICAL)], rx.Forecast()
    )
    assert made.forecast is None
    assert '"forecast"' not in made.model_dump_json()


# --- the pipeline order carries no copy -----------------------------------------------


def test_a_pipeline_order_from_a_routed_part_carries_no_copy() -> None:
    assert "forecast" not in Order.model_fields
    store, fdr = _seated()
    house = _house(load_state(store, CAMPAIGN))
    made = rt.commit_order(
        store, CAMPAIGN, fdr, [Ask(ask="Revise the act.", effect=HISTORICAL)], _forecast(house)
    )
    for _ in range(3):
        rt.run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    (order,) = [o for o in state.orders.values() if o.routed_from is not None]
    assert "forecast" not in order.model_dump_json()
    assert order.routed_from == rx.PartRef(order_id=made.order_id, part=0)
    assert state.routed[made.order_id].forecast == _forecast(house)


# --- no rule reads it ---------------------------------------------------------------


def _played(forecast: rx.Forecast | None, monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], str]:
    """The log from the order on and the state at the end, with every forecast and
    state hash taken out. Order ids are numbered, so both games mint the same ones."""
    minted = count()
    monkeypatch.setattr(rt, "new_id", lambda: derived_id(CAMPAIGN, "fcs-id", next(minted)))
    store, fdr = _seated()
    rt.commit_order(store, CAMPAIGN, fdr, [Ask(ask="Revise the act.", effect=HISTORICAL)], forecast)
    for _ in range(4):
        rt.run_realism_tick(store, CAMPAIGN)
    events = list(store.read(CAMPAIGN))
    start = next(i for i, e in enumerate(events) if isinstance(e.payload, ev.OrderRouted))
    log: list[str] = []
    for e in events[start:]:
        dumped = e.payload.model_dump(mode="json")
        if isinstance(e.payload, ev.OrderRouted):
            dumped["order"].pop("forecast", None)
        dumped.pop("state_hash", None)
        log.append(json.dumps(dumped, sort_keys=True))
    state = load_state(store, CAMPAIGN).model_dump(mode="json")
    for routed in state["routed"].values():
        routed.pop("forecast", None)
    return log, json.dumps(state, sort_keys=True)


def test_an_order_with_and_without_a_forecast_has_the_same_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    house = _house(load_state(_seated()[0], CAMPAIGN))
    plain, end_plain = _played(None, monkeypatch)
    told, end_told = _played(_forecast(house), monkeypatch)
    assert plain == told
    assert end_plain == end_told
    assert any('"order_drafted"' in row for row in plain), "the order reached a pipeline"


# --- the aide's path ----------------------------------------------------------------


class _Same:
    """Gives the same reply to every request."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply

    def call(self, request: Request) -> Reply:
        return Reply(self.reply, "hand", 0, 0, 0, 0.0)


def _reply(sl: Slice, house: str) -> dict[str, Any]:
    p = _parts(sl)
    first = p["patrol"] | {
        "expects": [_move("figure", house)],
        "risks": RISKS.model_dump(mode="json"),
    }
    return {"options": [first, p["word"], p["press"]]}


def test_the_aide_hands_over_the_forecast_of_the_option_it_chose() -> None:
    sl, state = _world()
    house = _house(state)
    orders = options.aide_asks(state, sl.fdr, _Same(_reply(sl, house)))
    assert orders
    first = orders[0]
    assert options.forecast_of(first) == _forecast(house)
    assert first == options.aide_asks(state, sl.fdr, _Same(_reply(sl, house)))[0]
    assert options.forecast_of(tuple(first)) is None, "a plain tuple of asks carries none"


def test_the_aide_files_with_the_chosen_options_forecast_at_the_close() -> None:
    sl, state = _world()
    house = _house(state)
    store = MemoryStore()
    store.append_all(sl.events)
    cid: CampaignId = CAMPAIGN
    wheeler: SeatId = sl.wheeler
    wake.open_wake(store, cid, T0)
    wake.commit(store, cid, wheeler, T0)
    wake.close_wake(store, cid, T0 + timedelta(hours=12), _Same(_reply(sl, house)))
    after = load_state(store, cid)
    (aide,) = [
        e.payload
        for e in store.read(cid)
        if isinstance(e.payload, ev.WakeCommitted) and e.payload.by_aide
    ]
    assert aide.seat_id == sl.fdr and aide.aide_orders
    filed = [after.routed[o] for o in aide.aide_orders]
    assert [o.forecast for o in filed] == [_forecast(house)]
