"""Switch names for every third-run rule (RUL).

Sixteen names join the rules a world may switch on, each read by a later item of the run.
Until its reader exists a name does nothing: a world that names one compiles and plays as
with it off. A shipped world names one only once its own lane has switched it on, and
none leans on a live model's reading.
"""

import ast
import inspect
import re
from pathlib import Path

import pytest
import yaml

from revisionist.core import state as core_state
from revisionist.core.state import MODEL_READ_RULES, Rule
from tests import locked_orders_script as lo
from tests import test_world_locks_1941 as locks_1941

ROOT = Path(__file__).resolve().parents[1]

THIRD_RUN = (
    "laws",
    "ask_answers",
    "deciders",
    "own_aim",
    "offers",
    "classes",
    "losses",
    "places",
    "posts",
    "office",
    "elections",
    "defiance",
    "aide_note",
    "peace",
    "post_view",
    "playable_rule",
)
READ = frozenset({"laws", "own_aim"})
"""The names whose reader has been built: a world that names one is no longer as with it off."""
UNREAD = tuple(n for n in THIRD_RUN if n not in READ)

SHIPPED_ON: dict[str, frozenset[str]] = {"autumn-1941": frozenset({"own_aim"})}
"""The names a shipped world's own lane has switched on, by world; each one whose reader
has been built."""

BASELINE_1941 = "45f00e1d6cb09e84245f4a7affb44692"
"""The 1941 scripted run's digest (``run_digest``) with every third-run switch off."""


def _docstrings() -> dict[str, str | None]:
    """Each ``Rule`` member's value and the string literal written under it, if any."""
    tree = ast.parse(inspect.getsource(core_state))
    (cls,) = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Rule"]
    out: dict[str, str | None] = {}
    body = cls.body
    for i, node in enumerate(body):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            after = body[i + 1] if i + 1 < len(body) else None
            doc = (
                after.value.value
                if isinstance(after, ast.Expr) and isinstance(after.value, ast.Constant)
                else None
            )
            out[str(node.value.value)] = doc if isinstance(doc, str) else None
    return out


def _with_third_run(rules: tuple[Rule, ...]) -> tuple[Rule, ...]:
    return (*rules, *(Rule(n) for n in UNREAD))


# --- rule 1: the sixteen names ------------------------------------------------------------


def test_the_sixteen_third_run_names_follow_the_rules_before_them() -> None:
    values = [r.value for r in Rule]
    assert values[-len(THIRD_RUN) :] == list(THIRD_RUN)
    assert values[: -len(THIRD_RUN)][-2:] == ["command", "locks"]


def test_none_of_the_sixteen_leans_on_a_live_models_reading() -> None:
    assert MODEL_READ_RULES == {Rule.WRITING, Rule.CLAUSE_READER, Rule.WRITTEN_ORDERS}
    assert not {r.value for r in MODEL_READ_RULES} & set(THIRD_RUN)


# --- rule 2: each names the item that reads it --------------------------------------------


@pytest.mark.parametrize("name", THIRD_RUN)
def test_each_name_has_a_one_line_docstring_naming_its_reader(name: str) -> None:
    doc = _docstrings().get(name)
    assert doc, f"{name} has no docstring"
    assert "\n" not in doc
    assert re.search(r"\([A-Z]{3}(, [A-Z]{3})*\)\.$", doc), doc


# --- rule 3: a name whose reader has not merged changes nothing ---------------------------


def test_the_1941_run_with_the_unread_names_on_folds_as_with_them_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = locks_1941._world()
    on = world.model_copy(update={"rules": _with_third_run(world.rules)})
    assert locks_1941.run_digest(on, monkeypatch) == BASELINE_1941


def test_the_toy_world_with_the_unread_names_on_plays_as_with_them_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def played(name: str, third_run: bool) -> tuple[set[str], dict[str, object]]:
        with monkeypatch.context() as mp:
            decl = lo.TOY.world(tmp_path / name / "world", ())
            if third_run:
                decl = decl.model_copy(update={"rules": _with_third_run(decl.rules)})
            state = lo.Game(lo.TOY, tmp_path / name, mp, decl).play().state
        dumped = state.model_dump(mode="json")
        dumped.pop("last_seq")
        return set(dumped.pop("rules")), dumped

    (rules_off, off), (rules_on, on) = played("off", False), played("on", True)
    assert rules_on - rules_off == set(UNREAD)
    assert on == off


# --- rule 4: a shipped world switches one on only by its own lane ------------------------


@pytest.mark.parametrize("path", sorted((ROOT / "worlds").glob("*.yaml")), ids=lambda p: p.stem)
def test_a_shipped_world_names_only_the_third_run_rules_its_lane_switched_on(path: Path) -> None:
    raw = yaml.safe_load(path.read_text())
    named = set(raw.get("rules") or ()) & set(THIRD_RUN)
    assert named == SHIPPED_ON.get(path.stem, frozenset())
    assert named <= READ
