"""A built card's levers name only resolvers a built card can feed. A movement or war
lever offers forces and places by key, and a figure's card declares neither. A fake
transport answers; no model is called."""

import copy
from typing import Any

import pytest

from revisionist.engine import build
from tests.cast_scenario import BUILD_BY_NAME
from tests.test_build_authority import Replies, opened_kennedy
from tests.test_realism_cast import Fixed

BUILT = ["votes", "shipping", "production", "opinion"]


def kennedy_moving(resolver: str) -> dict[str, Any]:
    raw = copy.deepcopy(BUILD_BY_NAME["John F. Kennedy"])
    raw["cards"][0]["reach"] = {"rank": 5}
    raw["cards"][0]["levers"][0]["resolver"] = resolver
    return raw


def test_the_schema_offers_only_the_resolvers_a_built_card_can_feed() -> None:
    lever = build.BUILD_SCHEMA["$defs"]["LeverDecl"]["properties"]["resolver"]
    assert lever["enum"] == BUILT


@pytest.mark.parametrize("resolver", ["movement", "war"])
def test_a_lever_on_forces_is_retried_with_where_the_power_belongs(resolver: str) -> None:
    store, cid, kennedy = opened_kennedy()
    transport = Replies(kennedy_moving(resolver), kennedy_moving("shipping"))
    assert build.build_figure(store, cid, kennedy, transport)
    told = transport.sent[1].prompt
    assert "lever quarantine" in told and "move_force" in told
    assert "is not a force" not in told and "is not a place" not in told


def test_a_lever_on_forces_twice_fails_the_build_with_one_line_for_the_lever() -> None:
    store, cid, kennedy = opened_kennedy()
    with pytest.raises(build.BuildError) as refused:
        build.build_figure(store, cid, kennedy, Fixed(kennedy_moving("movement")))
    assert [p for p in refused.value.problems if "quarantine" in p] == [
        p for p in refused.value.problems if "move_force" in p
    ]
    assert len(refused.value.problems) == 1
