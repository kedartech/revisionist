"""A built figure's quantities each carry a value: the record's, or the builder's best
estimate. A figure with no value is never reported, cannot be moved by an order and
fires no matter. A fake transport answers; no model is called."""

import copy
from typing import Any

import pytest

from revisionist.engine import build
from revisionist.engine.llm import prompt_text
from revisionist.engine.store import load_state
from tests.cast_scenario import BUILD_BY_NAME
from tests.test_build_authority import Replies, opened_kennedy
from tests.test_realism_cast import Fixed


def kennedy(value: int | None) -> dict[str, Any]:
    raw = copy.deepcopy(BUILD_BY_NAME["John F. Kennedy"])
    raw["cards"][0]["reach"] = {"rank": 5}
    (figure,) = raw["quantities"]
    if value is None:
        figure.pop("value", None)
    else:
        figure["value"] = value
    return raw


def test_a_figure_with_no_value_is_sent_back_and_the_estimate_lands() -> None:
    store, cid, jfk = opened_kennedy()
    transport = Replies(kennedy(None), kennedy(9))
    assert build.build_figure(store, cid, jfk, transport)
    told = transport.sent[1].prompt
    assert "quantity sites_seen" in told and "best estimate" in told
    built = [q for q in load_state(store, cid).quantities.values() if q.estimable]
    assert [q.value for q in built] == [9]


def test_a_figure_left_empty_twice_fails_the_build() -> None:
    store, cid, jfk = opened_kennedy()
    with pytest.raises(build.BuildError, match="quantity sites_seen"):
        build.build_figure(store, cid, jfk, Fixed(kennedy(None)))


def test_the_hand_written_cast_gives_every_figure_a_value() -> None:
    for name, raw in BUILD_BY_NAME.items():
        assert all(q.get("value") is not None for q in raw["quantities"]), name


def test_the_prompt_asks_for_a_value_on_every_figure() -> None:
    system = prompt_text("build")
    assert "best estimate" in system
    assert "no value where the record gives none" not in system
