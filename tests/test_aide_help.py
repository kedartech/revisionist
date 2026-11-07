"""The aide's help desk: answers from the seat's View only, points to a form the desk
holds, falls back to the template when the model fails, and files nothing."""

from typing import Any, get_type_hints

import pytest

from revisionist.core.fold import state_hash
from revisionist.core.project import project
from revisionist.core.state import State, View
from revisionist.engine.aide_help import (
    Answer,
    ClaudeHelper,
    TemplateHelper,
    answer,
    best_lever,
    help_prompt,
)
from revisionist.engine.llm import Reply, TransportError
from revisionist.engine.store import MemoryStore, load_state
from tests.counsel_scenario import roosevelt_seat, ticked
from tests.test_realism_tick import CAMPAIGN


def fdr() -> View:
    store = MemoryStore()
    ticked(store)
    return project(load_state(store, CAMPAIGN), roosevelt_seat(store))


class Fixed:
    def __init__(self, output: Any) -> None:
        self.output = output

    def call(self, request: Any) -> Reply:
        return Reply(self.output, request.model, 10, 10, 0, 0.0)


class Down:
    def call(self, request: Any) -> Reply:
        raise TransportError("down")


def test_the_help_desk_reads_a_view_and_nothing_else() -> None:
    for fn in (help_prompt, answer, best_lever):
        assert State not in get_type_hints(fn).values()
    store = MemoryStore()
    ticked(store)
    state = load_state(store, CAMPAIGN)
    with pytest.raises(TypeError):
        help_prompt(state, "How?")  # type: ignore[arg-type]
    before = state_hash(state)
    answer(project(state, roosevelt_seat(store)), "How do I move a fleet?", TemplateHelper())
    assert state_hash(load_state(store, CAMPAIGN)) == before


def test_the_template_points_to_the_form_whose_words_match() -> None:
    said = TemplateHelper().answer(fdr(), "How do I move a fleet to Reykjavik?")
    assert said.lever == "move_fleet" and "Move a fleet" in said.text
    assert "Standard forms" in said.text and "_" not in said.text


def test_with_no_form_the_template_says_so_and_lists_what_there_is() -> None:
    said = TemplateHelper().answer(fdr(), "Abolish the Supreme Court")
    assert said.lever == "" and "no form" in said.text and "consult" in said.text


def test_a_failure_leads_the_answer() -> None:
    said = TemplateHelper().answer(fdr(), "x", failed="That person is not within your reach.")
    assert said.text.startswith("That did not go through: That person is not within your reach.")


def test_the_model_answer_keeps_only_a_lever_on_the_desk() -> None:
    view = fdr()
    said = answer(view, "How?", ClaudeHelper(Fixed({"text": "Use it.", "lever": "move_fleet"})))
    assert said == Answer(text="Use it.", lever="move_fleet", cost=said.cost)
    said = answer(view, "How?", ClaudeHelper(Fixed({"text": "Use it.", "lever": "nonesuch"})))
    assert said.lever == ""


def test_a_failed_or_empty_call_falls_back_to_the_template() -> None:
    view = fdr()
    for helper in (ClaudeHelper(Down()), ClaudeHelper(Fixed({"text": "", "lever": ""}))):
        said = answer(view, "How do I move a fleet?", helper)
        assert said.lever == "move_fleet" and said.text
