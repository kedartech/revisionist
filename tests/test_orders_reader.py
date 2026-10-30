"""The order reader (Phase 4 unit D): free text read from the seat's view into asks
that route, and filed only when they all do. A fake transport answers; no model is called."""

from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import FactId, derived_id
from revisionist.core.ontology import Fact
from revisionist.core.realism.effect import Route
from revisionist.core.state import State
from revisionist.core.visibility import Scope, Visibility
from revisionist.engine import orders_reader as orr
from revisionist.engine.llm import Reply, Request
from revisionist.engine.store import MemoryStore, load_state
from tests.test_engine_v2_contract import CAMPAIGN, REASON_CANARY, Slice


class Aide:
    """Answers every call with ``output``; remembers the prompts."""

    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.prompts: list[str] = []

    def call(self, request: Request) -> Reply:
        self.prompts.append(request.system + request.prompt)
        return Reply(self.output, request.model, 10, 10, 0, 0.0)


def engage(sl: Slice, kind: str = "engagement") -> dict[str, Any]:
    return {
        "asks": [
            {
                "ask": "Have the fleet shoot on sight in the western Atlantic",
                "effect": {
                    "kind": kind,
                    "force": sl.feature("us_atlantic_fleet"),
                    "zone": "western Atlantic",
                    "rule": "shoot_on_sight",
                },
            }
        ],
        "reason": "",
    }


@pytest.fixture
def sl() -> Slice:
    return Slice()


def store_of(sl: Slice) -> MemoryStore:
    store = MemoryStore()
    store.append_all(sl.events)
    return store


def test_a_clear_order_to_stark_reads_and_files_routed(sl: Slice) -> None:
    aide = Aide(engage(sl))
    reading = orr.read_order(
        sl.state, sl.fdr, "Stark", "", "Tell Stark to shoot on sight in the west.", aide
    )
    assert reading.shown["reason"] is None and len(reading.asks) == 1
    assert reading.shown["person"] is not None and "Stark" in reading.shown["person"]
    assert reading.shown["parts"] == ["Have the fleet shoot on sight in the western Atlantic"]
    store = store_of(sl)
    done = orr.file_order(store, CAMPAIGN, sl.fdr, reading)
    assert done["refused"] is False and "Stark" in done["reply"]
    order = next(iter(load_state(store, CAMPAIGN).routed.values()))
    assert order.issuer == sl.fdr and order.parts[0].route is Route.COMMAND
    assert order.parts[0].executor == sl.entity("stark")


def test_text_naming_nobody_reachable_is_refused_in_words(sl: Slice) -> None:
    aide = Aide({"asks": [{"ask": "Make it so"}], "reason": ""})
    reading = orr.read_order(sl.state, sl.fdr, "", "", "Make it so.", aide)
    assert not reading.asks and reading.shown["parts"] == []
    reason = reading.shown["reason"]
    assert reason and "_" not in reason
    named = orr.read_order(sl.state, sl.fdr, "Nobody Atall", "", "Do it.", aide)
    assert not named.asks and named.shown["reason"] == orr.UNREACHED
    refused = orr.file_order(store_of(sl), CAMPAIGN, sl.fdr, reading)
    assert refused["refused"] is True and refused["reply"]


def test_an_unknown_effect_kind_is_dropped_not_filed(sl: Slice) -> None:
    reading = orr.read_order(
        sl.state, sl.fdr, "Stark", "", "Sink them.", Aide(engage(sl, kind="sink_everything"))
    )
    assert not reading.asks and reading.shown["reason"] == orr.UNREADABLE
    store = store_of(sl)
    assert orr.file_order(store, CAMPAIGN, sl.fdr, reading)["refused"] is True
    assert not load_state(store, CAMPAIGN).routed
    assert orr.file_order(store, CAMPAIGN, sl.fdr, None)["refused"] is True


def test_the_prompt_holds_nothing_outside_the_seats_view(sl: Slice) -> None:
    fact = Fact(
        fact_id=FactId(derived_id(CAMPAIGN, "fact", "covert")),
        subject=sl.entity("wheeler"),
        predicate="took_money_from",
        obj=sl.entity("germany"),
        scope=Scope(visibility=Visibility.COVERT, known_by=frozenset({sl.wheeler})),
        canary=REASON_CANARY,
    )
    sl.add(ev.FactAsserted(fact=fact), fact.scope)
    state: State = sl.state
    aide = Aide(engage(sl))
    orr.read_order(state, sl.fdr, "Stark", "", "Tell Stark to shoot on sight.", aide)
    assert aide.prompts and REASON_CANARY not in aide.prompts[0]
    assert "Wheeler" in aide.prompts[0]
    assert "took_money_from" not in aide.prompts[0]
    own = Aide(engage(sl))
    orr.read_order(state, sl.wheeler, "Stark", "", "Hold your tongue.", own)
    assert "took_money_from" in own.prompts[0]
