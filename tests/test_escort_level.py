"""The escort level is marked on a form's choice in the world, not read from its words.

A form's parameter may mark each of its choices with ``escort_level`` (0 none, 1 escort,
2 shoot on sight), as a form may mark a choice ``needs_war``. The compiler refuses a level
outside 0 to 2, a form that marks some of a parameter's choices and not others, and marks on
more than one parameter. The compiled form carries the marks as ``escort_levels``, choice to
level, where the shipping rule can read them. No rule reads them yet, and no world on main is
marked.
"""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from revisionist.core.fold import replay
from revisionist.core.ids import EntityId
from revisionist.core.realism.card import Lever
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from tests.test_war_forms_from_world import CAMPAIGN, LEVERS, toy, toy_raw

CONVOY_ORDERS: dict[str, Any] = {
    "name": "convoy_orders",
    "pipeline": "norra_order",
    "resolver": "shipping",
    "params": [
        {"name": "waters", "kind": "enum", "choices": ["the_gulf"]},
        {"name": "guard", "kind": "enum", "choices": ["stay_moored", "shepherd", "ram_first"]},
    ],
}
"""A toy shipping form whose escort choices carry none of 1941's words."""

LEVELS = {"stay_moored": 0, "shepherd": 1, "ram_first": 2}


def marked(levels: dict[str, Any]) -> dict[str, Any]:
    return {**CONVOY_ORDERS, "escort_level": levels}


def compiled_lever(lever: dict[str, Any]) -> Lever:
    world = toy(toy_raw([lever]))
    state = replay(compile_world(world, CAMPAIGN, cmp.versions()))
    found = [lv for card in state.cards.values() for lv in card.levers if lv.name == lever["name"]]
    assert len(found) == 1
    return found[0]


def compile_problems(lever: dict[str, Any]) -> tuple[str, ...]:
    with pytest.raises(WorldError) as caught:
        compile_world(toy(toy_raw([lever])), CAMPAIGN, cmp.versions())
    return caught.value.problems


def test_a_marked_toy_form_compiles_and_carries_its_levels() -> None:
    lever = compiled_lever(marked({"guard": LEVELS}))
    assert lever.escort_levels == LEVELS


def test_an_unmarked_form_carries_no_levels_and_dumps_as_before() -> None:
    lever = compiled_lever(CONVOY_ORDERS)
    assert lever.escort_levels == {}
    assert "escort_levels" not in lever.model_dump(mode="json")


def test_a_level_of_three_is_refused_at_compile() -> None:
    problems = compile_problems(marked({"guard": {**LEVELS, "ram_first": 3}}))
    assert any("escort_level guard ram_first: 3 is not 0, 1 or 2" in p for p in problems)


def test_a_negative_level_is_refused_at_compile() -> None:
    problems = compile_problems(marked({"guard": {**LEVELS, "stay_moored": -1}}))
    assert any("escort_level guard stay_moored: -1 is not 0, 1 or 2" in p for p in problems)


def test_a_half_marked_form_is_refused_at_compile() -> None:
    problems = compile_problems(marked({"guard": {"shepherd": 1, "ram_first": 2}}))
    assert any("escort_level guard leaves stay_moored unmarked" in p for p in problems)


def test_marks_on_two_parameters_are_refused_at_compile() -> None:
    problems = compile_problems(marked({"guard": LEVELS, "waters": {"the_gulf": 1}}))
    assert any("escort_level marks more than one parameter" in p for p in problems)


def test_a_mark_on_no_choice_of_the_form_is_refused_at_compile() -> None:
    mood = compile_problems(marked({"mood": {"calm": 0}}))
    assert any("escort_level names no parameter mood" in p for p in mood)
    board = compile_problems(marked({"guard": {**LEVELS, "board": 2}}))
    assert any("escort_level: guard offers no choice board" in p for p in board)


def test_a_marked_form_beside_a_needs_war_form_keeps_both() -> None:
    world = toy(toy_raw([LEVERS[2], marked({"guard": LEVELS})]))
    state = replay(compile_world(world, CAMPAIGN, cmp.versions()))
    levers = {lv.name: lv for card in state.cards.values() for lv in card.levers}
    assert levers["convoy_orders"].escort_levels == LEVELS
    assert levers["galley_orders"].escort_levels == {}
    assert levers["galley_orders"].needs_war


@pytest.mark.parametrize(
    "levels",
    [{"a": 3, "c": 0}, {"a": 1, "zz": 1}, {"a": 1, "c": 1, "b": 1}, {"a": 1}],
    ids=["out of range", "no such choice", "two parameters", "half marked"],
)
def test_a_stored_lever_with_a_bad_mark_is_refused(levels: dict[str, int]) -> None:
    params = [
        {"name": "guard", "kind": "enum", "choices": ["a", "c"]},
        {"name": "other", "kind": "enum", "choices": ["b"]},
    ]
    lever = {"name": "f", "pipeline": "p", "resolver": "shipping", "params": params}
    with pytest.raises(ValidationError):
        Lever.model_validate({**lever, "escort_levels": levels})


def test_a_stored_lever_marking_every_choice_of_one_parameter_is_kept() -> None:
    params = [{"name": "guard", "kind": "enum", "choices": ["a", "c"]}]
    lever = {"name": "f", "pipeline": "p", "resolver": "shipping", "params": params}
    kept = Lever.model_validate({**lever, "escort_levels": {"a": 0, "c": 2}})
    assert kept.model_dump(mode="json")["escort_levels"] == {"a": 0, "c": 2}


def test_the_world_schema_offered_to_a_model_has_no_mark() -> None:
    assert "escort_level" not in json.dumps(WorldFile.model_json_schema())


def test_no_1941_form_is_marked() -> None:
    world = cmp.load_world(cmp.world_path("autumn-1941"))
    assert [lv.name for c in world.cards for lv in c.levers if lv.escort_level] == []


def test_the_compiled_card_carries_the_marks_on_the_issuers_own_card() -> None:
    world = toy(toy_raw([marked({"guard": LEVELS})]))
    state = replay(compile_world(world, CAMPAIGN, cmp.versions()))
    ilse = EntityId(resolve_keys(world, CAMPAIGN)["ilse"])
    assert [lv.escort_levels for lv in state.cards[ilse].levers] == [LEVELS]
