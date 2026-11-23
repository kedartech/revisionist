"""Switch names for the piece rules (KSW).

Three names join the rules a world may switch on: the kinds of piece counting in a battle,
weather by season, and raising a new piece. Each is read by a later item; until then a name
does nothing, so a world that names one compiles and plays as with it off, and a stored game
of the schema before them loads as it did.
"""

import dataclasses
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId
from revisionist.core.state import MODEL_READ_RULES, Rule, State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from tests import locked_orders_script as lo
from tests import test_salt_strait_plays as ssp
from tests import test_world_locks_1941 as locks_1941
from tests.test_rule_names import BASELINE_1941, THIRD_RUN, _docstrings

PIECES = ("kinds_in_battle", "weather", "raising")
CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
TOY = Path(__file__).parent / "worlds" / "territory-toy.yaml"
STORED_SCHEMA = "74"
"""The schema number before the three names: a game stored under it must load."""


def _toy(rules: list[str]) -> WorldFile:
    raw = yaml.safe_load(TOY.read_text())
    raw["rules"] = [*raw.get("rules", ()), *rules]
    world = WorldFile.model_validate(raw)
    return world.model_copy(update={"map_data": cmp.load_world(TOY).map_data})


def _with_pieces(rules: tuple[Rule, ...]) -> tuple[Rule, ...]:
    return (*rules, *(Rule(n) for n in PIECES))


# --- rule 1: the three names --------------------------------------------------------------


def test_the_three_piece_names_follow_the_third_run_names() -> None:
    values = [r.value for r in Rule]
    assert values[-len(PIECES) :] == list(PIECES)
    assert values[-len(PIECES) - len(THIRD_RUN) : -len(PIECES)] == list(THIRD_RUN)


def test_none_of_the_three_leans_on_a_live_models_reading() -> None:
    assert not {r.value for r in MODEL_READ_RULES} & set(PIECES)


@pytest.mark.parametrize("name", PIECES)
def test_each_name_has_a_one_line_docstring_naming_its_reader(name: str) -> None:
    doc = _docstrings().get(name)
    assert doc, f"{name} has no docstring"
    assert "\n" not in doc
    assert re.search(r"\([A-Z]{3}(, [A-Z]{3})*\)\.$", doc), doc


# --- rule 2: the world compile accepts each -----------------------------------------------


@pytest.mark.parametrize("name", PIECES)
def test_a_world_with_each_name_compiles_with_it_on(name: str) -> None:
    state = replay(compile_world(_toy([name]), CAMPAIGN, cmp.versions()))
    assert Rule(name) in state.rules


# --- a stored game of the schema before them loads ----------------------------------------


def _stamped(node: Any, schema: str) -> Any:
    if isinstance(node, dict):
        return {
            k: schema if k == "schema_version" else _stamped(v, schema) for k, v in node.items()
        }
    if isinstance(node, list):
        return [_stamped(v, schema) for v in node]
    return node


def test_a_stored_game_of_the_schema_before_loads_unchanged() -> None:
    events = compile_world(_toy([]), CAMPAIGN, cmp.versions())
    stored = [_stamped(e.model_dump(mode="json"), STORED_SCHEMA) for e in events]
    assert any("schema_version" in str(s) for s in stored)
    loaded = [ev.Event.model_validate(s) for s in stored]
    assert replay(loaded).model_dump(mode="json") == replay(events).model_dump(mode="json")


# --- keeps: with the three on, every world plays as with them off -------------------------


def test_the_1941_run_with_the_piece_names_on_folds_as_the_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = locks_1941._world()
    assert locks_1941.run_digest(world, monkeypatch) == BASELINE_1941
    on = world.model_copy(update={"rules": _with_pieces(world.rules)})
    assert locks_1941.run_digest(on, monkeypatch) == BASELINE_1941


def _less_rules(state: State) -> str:
    return lo.digest(state.model_copy(update={"rules": frozenset()}))


def test_the_toy_world_with_the_piece_names_on_plays_as_with_them_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def played(name: str, pieces: bool) -> State:
        with monkeypatch.context() as mp:
            decl = lo.TOY.world(tmp_path / name / "world", ())
            if pieces:
                decl = decl.model_copy(update={"rules": _with_pieces(decl.rules)})
            return lo.Game(lo.TOY, tmp_path / name, mp, decl).play().state

    off, on = played("off", False), played("on", True)
    assert on.rules - off.rules == {Rule(n) for n in PIECES}
    assert _less_rules(on) == _less_rules(off)


def test_salt_strait_with_the_piece_names_on_plays_as_with_them_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def switched_on(w: dict[str, Any]) -> None:
        w["rules"] = [*w.get("rules", ()), *PIECES]

    def played(cast: ssp.Cast) -> State:
        (tmp_path / cast.name).mkdir()
        with monkeypatch.context() as mp:
            return ssp.Game(cast, tmp_path / cast.name, mp).play().state

    on_cast = dataclasses.replace(
        ssp.SALT_STRAIT, name="salt-pieces", changes=(*ssp.SALT_STRAIT.changes, switched_on)
    )
    off, on = played(ssp.SALT_STRAIT), played(on_cast)
    assert on.rules - off.rules == {Rule(n) for n in PIECES}
    assert _less_rules(on) == _less_rules(off)
