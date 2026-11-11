"""A built card may carry mandate templates aimed at its own figure, so the agenda keeps
filling after the opening matter. A fake transport answers; no model is called."""

import copy
from typing import Any

import pytest

from revisionist.engine import build
from revisionist.engine.llm import prompt_text
from revisionist.engine.store import load_state
from tests.cast_scenario import BUILD_BY_NAME, person
from tests.test_build_authority import Replies, opened_kennedy

WHO = "john_f_kennedy"


def template(**over: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "key": "answer_the_outcry",
        "kind": "blowback",
        "trigger": {"on": "act", "effect": "engagement"},
        "to": [WHO],
        "text": "Answer the outcry over the quarantine.",
        "condition": {"check": "ordered", "person": WHO, "effect": "statement"},
        "days": 7,
    }
    raw.update(over)
    return raw


def kennedy_with(mandates: list[dict[str, Any]]) -> dict[str, Any]:
    raw = copy.deepcopy(BUILD_BY_NAME["John F. Kennedy"])
    raw["mandates"] = mandates
    return raw


def test_a_template_in_the_reply_lands_among_the_worlds_templates() -> None:
    store, cid, kennedy = opened_kennedy()
    reply = kennedy_with([template()])
    assert build.build_figure(store, cid, kennedy, Replies(reply))
    (t,) = load_state(store, cid).templates.values()
    assert t.to == (kennedy,) and t.days == 7 and t.text.startswith("Answer the outcry")


def test_a_template_aimed_at_anyone_else_is_retried_with_the_problem() -> None:
    store, cid, kennedy = opened_kennedy()
    bad = kennedy_with([template(to=["robert_mcnamara"])])
    good = kennedy_with([template()])
    transport = Replies(bad, good)
    assert build.build_figure(store, cid, kennedy, transport)
    assert "was refused" in transport.sent[1].prompt
    assert "mandate answer_the_outcry: aimed at" in transport.sent[1].prompt
    assert len(load_state(store, cid).templates) == 1


def test_a_trigger_that_names_nothing_in_the_world_is_refused() -> None:
    store, cid, kennedy = opened_kennedy()
    bad = kennedy_with(
        [template(trigger={"on": "quantity", "quantity": "ghosts", "op": "ge", "value": 3})]
    )
    with pytest.raises(build.BuildError, match="ghosts"):
        build.build_figure(store, cid, kennedy, Replies(bad, bad, bad))
    assert load_state(store, cid).templates == {}


def test_two_figures_may_use_the_same_template_key() -> None:
    store, cid, kennedy = opened_kennedy()
    khrushchev = person(store, cid, "Nikita Khrushchev")
    first = kennedy_with([template()])
    other = copy.deepcopy(BUILD_BY_NAME["Nikita Khrushchev"])
    other["mandates"] = [
        template(
            to=[other["cards"][0]["person"]],
            condition={
                "check": "ordered",
                "person": other["cards"][0]["person"],
                "effect": "statement",
            },
        )
    ]
    assert build.build_figure(store, cid, kennedy, Replies(first))
    assert build.build_figure(store, cid, khrushchev, Replies(other))
    templates = load_state(store, cid).templates.values()
    assert sorted(t.to for t in templates) == sorted([(kennedy,), (khrushchev,)])


def test_the_schema_and_the_prompt_ask_for_templates() -> None:
    assert "mandates" in build.BUILD_SCHEMA["properties"]
    assert "mandates" in prompt_text("build")


def test_more_than_three_templates_are_refused() -> None:
    store, cid, kennedy = opened_kennedy()
    many = kennedy_with([template(key=f"matter_{n}") for n in range(4)])
    with pytest.raises(build.BuildError, match="4 templates, at most 3"):
        build.build_figure(store, cid, kennedy, Replies(many, many, many))
