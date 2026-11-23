"""The world template and the world check: every key the loader accepts has a row, and
the check reports each question answered, marked a gap, absent, or absent and required."""

import ast
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from revisionist.core.state import Rule

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "worlds" / "TEMPLATE.md"
SCRIPT = ROOT / "scripts" / "world_check.py"
TOY = ROOT / "tests" / "worlds" / "territory-toy.yaml"
WORLDS = (
    ROOT / "worlds" / "autumn-1941.yaml",
    ROOT / "worlds" / "salt-strait-realism.yaml",
    TOY,
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("world_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["world_check"] = module
    spec.loader.exec_module(module)
    return module


wc = _load()


def rows() -> list[Any]:
    found: list[Any] = wc.parse_template(TEMPLATE.read_text())
    return found


def toy(tmp_path: Path, **changes: Any) -> Path:
    data = yaml.safe_load(TOY.read_text())
    data.update(changes)
    path = tmp_path / "toy.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def lines_for(path: Path) -> dict[str, Any]:
    return {line.row.question: line for line in wc.check(wc.load(path), rows())}


# --- the document ------------------------------------------------------------------


def test_every_key_the_loader_accepts_has_a_row() -> None:
    documented = {key for row in rows() for key in row.keys}
    missing = sorted(wc.loader_keys() - documented)
    assert missing == [], f"keys the loader accepts with no row in worlds/TEMPLATE.md: {missing}"


def test_a_key_struck_from_the_document_is_found_missing() -> None:
    text = TEMPLATE.read_text()
    assert text.count("`territories.holder`") == 1
    struck = text.replace("`territories.holder`", "")
    documented = {key for row in wc.parse_template(struck) for key in row.keys}
    assert "territories.holder" in wc.loader_keys() - documented


def test_rows_on_main_name_only_keys_the_loader_accepts() -> None:
    accepted = wc.loader_keys()
    stale = sorted(
        (row.question, key)
        for row in rows()
        if row.standing == "on main"
        for key in row.keys
        if key not in accepted
    )
    assert stale == []


def test_every_row_has_its_standing_and_a_known_switch() -> None:
    rule_names = {r.value for r in Rule}
    assert rows(), "the template has no rows"
    for row in rows():
        assert row.question and row.keys and row.when_absent, row
        assert row.standing == "on main" or row.standing.startswith(("this run: ", "parked")), row
        if row.standing == "on main":
            unknown = set(row.switches) - rule_names - {"legacy"}
            assert not unknown, (row.question, unknown)


def test_every_part_of_the_draft_is_in_the_document() -> None:
    parts = [p for p in dict.fromkeys(row.part for row in rows())]
    for word in ("world", "map", "nations", "groups", "offices", "armed", "people", "aims"):
        assert any(word in p.lower() for p in parts), (word, parts)
    assert any("happenings" in p.lower() for p in parts), parts


def test_the_four_amendments_of_the_pre_modern_check_are_written_in() -> None:
    by_q = {row.question.lower(): row for row in rows()}

    def one(*words: str) -> Any:
        hits = [r for q, r in by_q.items() if all(w in q for w in words)]
        assert len(hits) == 1, (words, [r.question for r in hits])
        return hits[0]

    seat = one("seat of government")
    weight = one("political weight", "which audience")
    assert set(seat.keys).isdisjoint(weight.keys)
    outlet = one("outlets")
    assert "no outlet" in outlet.when_absent.lower()
    leave = one("leave")
    assert leave.standing.startswith("parked") and "faction" in leave.question.lower()
    holder = one("holds a territory")
    assert holder.standing.startswith("parked")
    assert "person" in holder.question.lower() and "faction" in holder.question.lower()


def test_the_template_names_no_place_nation_or_era() -> None:
    text = TEMPLATE.read_text()
    names: set[str] = set()
    for world in (*WORLDS, ROOT / "worlds" / "realism-toy.yaml"):
        data = yaml.safe_load(world.read_text())
        for section in ("entities", "territories", "sea_zones", "regions"):
            names.update(str(d["name"]) for d in data.get(section, ()) if len(str(d["name"])) > 3)
    named = sorted(n for n in names if re.search(rf"\b{re.escape(n)}\b", text))
    assert named == []
    assert re.findall(r"\b1[5-9]\d\d\b", text) == []


def test_brace_shorthand_expands_to_each_key() -> None:
    assert wc.expand("`a.b.{c, d}` and `e`") == ("a.b.c", "a.b.d", "e")


# --- the check ---------------------------------------------------------------------


@pytest.mark.parametrize("world", WORLDS, ids=lambda p: p.stem)
def test_the_check_reports_every_question_for_each_world(
    world: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = wc.main([str(world)])
    out = capsys.readouterr().out
    assert code == 0, out
    reported = [line for line in out.splitlines() if re.match(r"^\s*\d+\.\d+ ", line)]
    assert len(reported) == len(rows())
    for line in reported:
        assert re.search(
            r": (answered|answered, marked a gap|absent|absent and required)\b", line
        ), line


def test_a_written_key_is_answered(tmp_path: Path) -> None:
    got = lines_for(TOY)
    holder = next(line for q, line in got.items() if "holds each territory" in q.lower())
    assert holder.status == "answered"


def test_a_gap_mark_is_reported_apart_from_an_absent_line(tmp_path: Path) -> None:
    data = yaml.safe_load(TOY.read_text())
    first = data["territories"][0]
    first.pop("source")
    first["gap"] = True
    got = lines_for(toy(tmp_path, territories=data["territories"]))
    holder = next(line for q, line in got.items() if "holds each territory" in q.lower())
    assert holder.status == "gap"
    assert "1 of 4" in holder.text()
    fuel = next(line for q, line in got.items() if "fuel stock" in q.lower())
    assert fuel.status == "absent"
    assert fuel.row.when_absent in fuel.text()


def test_an_absent_line_names_the_mechanism_that_is_off() -> None:
    got = lines_for(TOY)
    locks = next(line for q, line in got.items() if "lock holds" in q.lower())
    assert locks.status == "absent"
    assert locks.text().startswith(f"{locks.row.number_label} ")
    assert locks.row.when_absent in locks.text()


def test_a_switched_on_rule_without_its_decider_fails_the_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = toy(tmp_path, rules=["locks"])
    got = lines_for(path)
    locks = next(line for q, line in got.items() if "lock holds" in q.lower())
    assert locks.status == "required"
    assert ": absent and required" in locks.text()
    assert wc.main([str(path)]) == 1
    assert "absent and required" in capsys.readouterr().out


def test_an_empty_list_is_no_decider(tmp_path: Path) -> None:
    got = lines_for(toy(tmp_path, rules=["locks"], locks=[]))
    locks = next(line for q, line in got.items() if "lock holds" in q.lower())
    assert locks.status == "required"
    outlets = next(
        line for q, line in lines_for(toy(tmp_path, outlets=[])).items() if "outlets" in q
    )
    assert outlets.status == "answered"


def test_no_decider_row_is_left_optional_under_its_switch() -> None:
    deciders = [
        row
        for row in rows()
        if "decide" in row.question.lower() or "allows" in row.question.lower()
    ]
    assert deciders
    for row in deciders:
        assert row.needed is not None, row.question


def test_a_question_not_built_yet_is_absent_and_says_so() -> None:
    got = lines_for(TOY)
    kinds = next(line for q, line in got.items() if q.lower().startswith("who decides to accept"))
    assert kinds.status == "absent"
    assert "not built yet" in kinds.text()


def test_the_check_reads_only_the_standard_library_and_the_world_loader() -> None:
    tree = ast.parse(SCRIPT.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    outside = {
        m
        for m in imported
        if m.split(".")[0] not in sys.stdlib_module_names and m != "revisionist.engine.campaign"
    }
    assert outside == set()
