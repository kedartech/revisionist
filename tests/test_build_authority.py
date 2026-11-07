"""A built card carries authority and reach (engine v2). A fake transport answers; no
model is called."""

import copy
from typing import Any

import pytest

from revisionist.engine import build
from revisionist.engine.llm import RecordedTransport, Reply, Request, prompt_text
from revisionist.engine.store import MemoryStore, load_state
from tests.cast_scenario import BUILD_BY_NAME, opened, person
from tests.handwritten import CAST
from tests.test_realism_cast import Fixed

DOMAIN = {
    "name": "Orders to the forces",
    "effects": ["move_force", "engagement"],
    "executor": "robert_mcnamara",
    "summary": "Orders to the forces, carried out by the Secretary of Defense.",
}


def kennedy_with(**card: Any) -> dict[str, Any]:
    raw = copy.deepcopy(BUILD_BY_NAME["John F. Kennedy"])
    raw["cards"][0].pop("reach", None)
    raw["cards"][0].update(card)
    return raw


def opened_kennedy() -> tuple[MemoryStore, Any, Any]:
    store = MemoryStore()
    cid = opened(store, RecordedTransport(CAST))
    return store, cid, person(store, cid, "John F. Kennedy")


def test_a_domain_and_a_rank_land_on_the_card() -> None:
    store, cid, kennedy = opened_kennedy()
    reply = kennedy_with(authority=[DOMAIN], reach={"rank": 5, "chain": [], "heads": True})
    assert build.build_figure(store, cid, kennedy, Fixed(reply))
    state = load_state(store, cid)
    card = state.cards[kennedy]
    (domain,) = card.authority
    assert domain.name == DOMAIN["name"]
    assert domain.executor == person(store, cid, "Robert McNamara")
    assert (card.reach.rank, card.reach.heads) == (5, True)


def test_an_unknown_executor_is_retried_with_the_compile_problem() -> None:
    store, cid, kennedy = opened_kennedy()
    bad = kennedy_with(authority=[{**DOMAIN, "executor": "nobody"}], reach={"rank": 5})
    good = kennedy_with(authority=[DOMAIN], reach={"rank": 5})
    transport = Replies(bad, good)
    assert build.build_figure(store, cid, kennedy, transport)
    assert "was refused" in transport.sent[1].prompt
    assert (
        "unknown entity nobody" in transport.sent[1].prompt or "nobody" in transport.sent[1].prompt
    )
    assert load_state(store, cid).cards[kennedy].authority[0].executor is not None


def test_a_playable_card_with_neither_is_retried() -> None:
    store, cid, kennedy = opened_kennedy()
    bare = kennedy_with()
    good = kennedy_with(reach={"rank": 5})
    transport = Replies(bare, good)
    assert build.build_figure(store, cid, kennedy, transport)
    assert "reach rank 0" in transport.sent[1].prompt
    assert load_state(store, cid).cards[kennedy].reach.rank == 5

    store, cid, kennedy = opened_kennedy()
    with pytest.raises(build.BuildError, match="no order has a route"):
        build.build_figure(store, cid, kennedy, Fixed(bare))


def test_the_prompt_explains_authority_and_reach_and_leaks_no_policy() -> None:
    system = prompt_text("build")
    for word in ("authority", "executor", "forces", "rank", "chain", "heads"):
        assert word in system
    store, cid, kennedy = opened_kennedy()
    transport = Fixed(kennedy_with(reach={"rank": 5}))
    build.build_figure(store, cid, kennedy, transport)
    sent = transport.sent[0].prompt
    voices = [
        c["voice"]
        for name, raw in BUILD_BY_NAME.items()
        if name != "John F. Kennedy"
        for c in raw["cards"]
    ]
    assert voices and not any(v in sent for v in voices)
    assert "loyalty" not in sent and "doctrine" not in sent


class Replies:
    """Each request gets the next output in turn."""

    def __init__(self, *outputs: Any) -> None:
        self.outputs = list(outputs)
        self.sent: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.sent.append(request)
        return Fixed(self.outputs[len(self.sent) - 1]).call(request)


def test_a_force_key_cannot_resolve_for_a_built_card() -> None:
    """compile_figure holds no features, so the prompt tells the builder to leave
    ``forces`` empty; a reply that names one is refused as an unknown feature."""
    store, cid, kennedy = opened_kennedy()
    reply = kennedy_with(authority=[{**DOMAIN, "forces": ["us_atlantic_fleet"]}], reach={"rank": 5})
    with pytest.raises(build.BuildError, match="unknown feature us_atlantic_fleet"):
        build.build_figure(store, cid, kennedy, Fixed(reply))
