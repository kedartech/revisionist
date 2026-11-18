"""The map checker on a hand-written three-area map, its broken copies and the counterexamples."""

import copy
import importlib.util
import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MAPS = Path(__file__).resolve().parent / "maps"
CASES = MAPS / "counterexamples"
THREE = MAPS / "three-areas.json"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_check", ROOT / "scripts" / "map_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mc = _load()


def three() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(THREE.read_text())
    return data


def case(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((CASES / f"{name}.json").read_text())
    return data


def codes(problems: list[Any]) -> set[tuple[str, str]]:
    return {(p.code, p.face) for p in problems}


def test_the_three_area_map_passes() -> None:
    assert mc.check(three()) == []


# Rule 2: one broken copy of the three-area map per failure, each named by its face.


def _open_ring(m: dict[str, Any]) -> None:
    m["areas"]["marsh"]["rings"] = [[0, 1, 4, 3]]


def _crossed_ring(m: dict[str, Any]) -> None:
    m["areas"]["ridge"]["rings"] = [[1, 2, 4, 5, 1]]


def _hole_outside(m: dict[str, Any]) -> None:
    m["vertices"] += [[60, 10], [60, 20], [70, 20], [70, 10]]
    m["areas"]["marsh"]["rings"].append([9, 10, 11, 12, 9])


def _overlap(m: dict[str, Any]) -> None:
    m["vertices"] += [[40, 10], [60, 10], [60, 20], [40, 20]]
    m["areas"]["fen"] = {"rings": [[9, 10, 11, 12, 9]], "label": [45, 15]}


def _duplicate(m: dict[str, Any]) -> None:
    m["areas"]["marsh2"] = copy.deepcopy(m["areas"]["marsh"])


def _gap(m: dict[str, Any]) -> None:
    m["backdrop"] = []


def _t_junction(m: dict[str, Any]) -> None:
    m["vertices"].append([25, 50])
    m["backdrop"] = [[3, 9, 4, 7, 6, 3]]


def _small(m: dict[str, Any]) -> None:
    m["vertices"] = [[x * 0.09, y * 0.09] for x, y in m["vertices"]]
    m["box"] = [0, 0, 9, 9]
    for a in m["areas"].values():
        a["label"] = [v * 0.09 for v in a["label"]]


def _label_outside(m: dict[str, Any]) -> None:
    m["areas"]["marsh"]["label"] = [75, 25]


def _label_on_border(m: dict[str, Any]) -> None:
    m["areas"]["marsh"]["label"] = [50, 25]


BROKEN: list[tuple[str, Callable[[dict[str, Any]], None], str, str]] = [
    ("an open ring", _open_ring, "ring", "marsh"),
    ("a ring that crosses itself", _crossed_ring, "ring", "ridge"),
    ("a hole outside its outer ring", _hole_outside, "hole", "marsh"),
    ("two areas that overlap", _overlap, "overlap", "fen"),
    ("a duplicate area", _duplicate, "overlap", "marsh"),
    ("a part of the box no face covers", _gap, "coverage", "box"),
    ("a border that only looks shared", _t_junction, "vertex", "backdrop 1"),
    ("an area smaller than the minimum", _small, "small", "marsh"),
    ("a label outside its area", _label_outside, "label", "marsh"),
    ("a label on its area's border", _label_on_border, "label", "marsh"),
]


@pytest.mark.parametrize(("what", "breaks", "code", "face"), BROKEN, ids=[b[0] for b in BROKEN])
def test_a_broken_copy_fails_naming_its_face(
    what: str, breaks: Callable[[dict[str, Any]], None], code: str, face: str
) -> None:
    m = three()
    breaks(m)
    problems = mc.check(m)
    assert (code, face) in codes(problems), (what, [str(p) for p in problems])


def test_an_overlap_names_both_faces() -> None:
    m = three()
    _overlap(m)
    text = [str(p) for p in mc.check(m) if p.code == "overlap"]
    assert any("fen" in t and "marsh" in t for t in text), text
    assert any("fen" in t and "ridge" in t for t in text), text


def test_a_gap_names_the_faces_beside_it() -> None:
    problems = mc.check(case("gap"))
    assert {("edge", "marsh"), ("edge", "bay"), ("coverage", "box")} <= codes(problems)
    text = [str(p) for p in problems]
    assert "box: the faces cover 7500 of the box's 10000" in text, text
    assert "box: the west edge of the box is covered for 50 of 100" in text, text


def test_a_duplicate_backdrop_fails_though_it_shares_every_playable_edge() -> None:
    problems = mc.check(case("duplicate-backdrop"))
    overlaps = [str(p) for p in problems if p.code == "overlap"]
    assert any("backdrop 1" in t and "backdrop 2" in t for t in overlaps), overlaps
    assert ("coverage", "box") in codes(problems)


def test_an_area_inside_another_fails() -> None:
    problems = mc.check(case("area-inside"))
    overlaps = [str(p) for p in problems if p.code == "overlap"]
    assert any("islet" in t and "ridge" in t for t in overlaps), overlaps


def test_a_vertex_outside_the_box_fails() -> None:
    m = three()
    m["box"] = [0, 0, 100, 90]
    assert ("box", "bay") in codes(mc.check(m))


def test_coordinates_are_rounded_to_four_decimals_before_comparison() -> None:
    m = three()
    m["vertices"].append([50.00004, 49.99996])
    m["areas"]["marsh"]["rings"] = [[0, 1, 9, 3, 0]]
    assert mc.check(m) == []
    m["vertices"][9] = [50.0002, 50]
    assert mc.check(m) != []


def test_a_structural_fault_is_named() -> None:
    m = three()
    m["areas"]["marsh"]["rings"] = [[0, 1, 44, 3, 0]]
    assert ("format", "marsh") in codes(mc.check(m))


# The counterexamples that must pass.


def test_an_island_in_a_sea_zone_passes_and_touches_the_sea() -> None:
    m = case("island-in-sea")
    assert mc.check(m) == []
    assert mc.adjacency(m) == [("holm", "sound")]


def test_an_area_with_a_hole_passes_and_the_hole_is_not_in_it() -> None:
    m = case("area-with-hole")
    assert mc.check(m) == []
    assert mc.area(m, "moor") == pytest.approx(5000 - 400)
    assert mc.locate(m, 20, 50) == ([], [])
    assert mc.locate(m, 5, 50) == (["moor"], [])
    assert mc.locate(m, 50, 50) == ([], ["fell", "moor"])


# Rule 3: one adjacency predicate.


@pytest.mark.parametrize(
    ("name", "adjacent"),
    [
        ("shared-below", False),
        ("shared-at", True),
        ("shared-above", True),
        ("shared-at-split", True),
    ],
)
def test_the_shared_border_threshold(name: str, adjacent: bool) -> None:
    m = case(name)
    assert mc.check(m) == []
    assert mc.adjacent(m, "west", "east") is adjacent
    assert mc.adjacent(m, "east", "west") is adjacent
    assert mc.adjacency(m) == ([("east", "west")] if adjacent else [])


def test_a_border_split_by_extra_vertices_counts_its_whole_length() -> None:
    assert mc.shared_length(case("shared-at-split"), "west", "east") == pytest.approx(2.0)
    assert mc.MIN_SHARED == {"lonlat": 0.1, "flat": 2.0}


def test_a_touching_corner_is_not_adjacent() -> None:
    m = three()
    assert mc.adjacent(m, "marsh", "bay") is False
    assert mc.adjacency(m) == [("bay", "ridge"), ("marsh", "ridge")]


def test_an_unknown_area_is_refused() -> None:
    with pytest.raises(KeyError, match="moat"):
        mc.adjacent(three(), "marsh", "moat")


# Rules 3 and 4: the strict check of a world, and the scoped check of a staging world.

SHA = "6df7397e41de0a8c84d1e2e78d89d82e8aeb90e6815b6aa7d3a4bddf49044e41"


def world() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((CASES / "scoped-world.yaml").read_text())
    data["entities"] = [e for e in data["entities"] if e["key"] != "tower"]
    return data


def run_world(tmp_path: Path, w: dict[str, Any], *, mode: str = "world") -> Any:
    (tmp_path / "maps").mkdir(exist_ok=True)
    (tmp_path / "maps" / "three-areas.json").write_bytes(THREE.read_bytes())
    w = copy.deepcopy(w)
    w["map"]["file"] = "three-areas.json"
    path = tmp_path / "w.yaml"
    path.write_text(yaml.safe_dump(w))
    if mode == "world":
        return mc.check_world(path)
    return mc.check_region(path)


def test_the_world_passes(tmp_path: Path) -> None:
    assert run_world(tmp_path, world()).problems == []


def _pair_rejected(w: dict[str, Any]) -> None:
    w["adjacency"].append(["marsh", "bay"])


def _pair_missing(w: dict[str, Any]) -> None:
    w["adjacency"].remove(["ridge", "bay"])


def _place_in_no_area(w: dict[str, Any]) -> None:
    w["entities"].append({"key": "tower", "kind": "location", "name": "T", "at": [75, 25]})


def _place_on_a_border(w: dict[str, Any]) -> None:
    w["entities"].append({"key": "gate", "kind": "location", "name": "G", "at": [25, 50]})


def _site_outside_within(w: dict[str, Any]) -> None:
    w["entities"][1]["within"] = "marsh"


def _site_listed_elsewhere(w: dict[str, Any]) -> None:
    w["territories"][0]["sites"] = ["fort"]


def _keys_differ(w: dict[str, Any]) -> None:
    w["sea_zones"] = []
    w["adjacency"].remove(["ridge", "bay"])
    w["entities"].pop()


def _hash_differs(w: dict[str, Any]) -> None:
    w["map"]["sha256"] = "0" * 64


def _coords_differ(w: dict[str, Any]) -> None:
    w["map"]["coords"] = "lonlat"


WORLD_BROKEN: list[tuple[str, Callable[[dict[str, Any]], None], str, str]] = [
    ("a listed pair the predicate rejects", _pair_rejected, "adjacency", "marsh"),
    ("an accepted pair not listed", _pair_missing, "adjacency", "bay"),
    ("a place in no area", _place_in_no_area, "place", "tower"),
    ("a place on a border", _place_on_a_border, "place", "gate"),
    ("a site outside the area it is within", _site_outside_within, "place", "fort"),
    ("a site a territory lists that lies elsewhere", _site_listed_elsewhere, "place", "fort"),
    ("area keys that differ from the world's", _keys_differ, "keys", "bay"),
    ("a hash that differs", _hash_differs, "hash", "map"),
    ("coordinates of another kind", _coords_differ, "map", "map"),
]


@pytest.mark.parametrize(
    ("what", "breaks", "code", "face"), WORLD_BROKEN, ids=[b[0] for b in WORLD_BROKEN]
)
@pytest.mark.parametrize("mode", ["world", "region"])
def test_a_broken_world_fails(
    tmp_path: Path,
    what: str,
    breaks: Callable[[dict[str, Any]], None],
    code: str,
    face: str,
    mode: str,
) -> None:
    w = world()
    breaks(w)
    problems = run_world(tmp_path, w, mode=mode).problems
    assert (code, face) in codes(problems), (what, [str(p) for p in problems])


def test_a_declared_crossing_allows_a_pair_with_no_shared_border(tmp_path: Path) -> None:
    w = world()
    w["adjacency"].append({"a": "marsh", "b": "bay", "crossing": "the causeway"})
    assert run_world(tmp_path, w).problems == []


def test_a_place_on_a_border_is_a_failure_not_a_tie(tmp_path: Path) -> None:
    w = world()
    _place_on_a_border(w)
    text = [str(p) for p in run_world(tmp_path, w).problems]
    assert text == ["gate: lies on the border of marsh and ridge"], text


def test_the_scoped_check_passes_with_an_out_of_scope_place_the_strict_check_fails_on() -> None:
    strict = mc.check_world(CASES / "scoped-world.yaml")
    assert [(p.code, p.face) for p in strict.problems] == [("place", "tower")]
    scoped = mc.check_region(CASES / "scoped-pass.staging.yaml")
    assert scoped.problems == []
    assert scoped.out_of_scope == ["tower"]


def test_the_scoped_check_fails_when_an_in_scope_site_is_missing() -> None:
    scoped = mc.check_region(CASES / "scoped-fail.staging.yaml")
    assert [(p.code, p.face) for p in scoped.problems] == [("place", "tower")]


def test_a_staging_world_may_extend_an_earlier_one(tmp_path: Path) -> None:
    w = world()
    w["map"]["file"] = "three-areas.json"
    (tmp_path / "maps").mkdir()
    (tmp_path / "maps" / "three-areas.json").write_bytes(THREE.read_bytes())
    first = {k: w[k] for k in ("regions", "territories", "adjacency")}
    first["entities"] = w["entities"][:2]
    (tmp_path / "first.yaml").write_text(yaml.safe_dump(first))
    second = {k: w[k] for k in ("map", "sea_zones")}
    second["extends"] = "first.yaml"
    second["adjacency"] = []
    second["entities"] = w["entities"][2:]
    (tmp_path / "second.yaml").write_text(yaml.safe_dump(second))
    assert mc.check_region(tmp_path / "second.yaml").problems == []
    second["adjacency"] = [["marsh", "bay"]]
    (tmp_path / "second.yaml").write_text(yaml.safe_dump(second))
    assert ("adjacency", "marsh") in codes(mc.check_region(tmp_path / "second.yaml").problems)


def test_a_site_whose_coordinates_differ_from_the_world_fails(tmp_path: Path) -> None:
    w = yaml.safe_load((CASES / "scoped-pass.staging.yaml").read_text())
    w["places_of"] = str(CASES / "scoped-world.yaml")
    w["map"]["file"] = str(THREE)
    path = tmp_path / "moved.yaml"
    path.write_text(yaml.safe_dump(w))
    assert mc.check_region(path).problems == []
    w["entities"][0]["at"] = [21, 25]
    path.write_text(yaml.safe_dump(w))
    assert ("place", "mill") in codes(mc.check_region(path).problems)


def test_lonlat_places_read_latitude_first(tmp_path: Path) -> None:
    m = three()
    m["coords"] = "lonlat"
    m["vertices"] = [[x / 10, y / 10] for x, y in m["vertices"]]
    m["box"] = [0, 0, 10, 10]
    for a in m["areas"].values():
        a["label"] = [v / 10 for v in a["label"]]
    assert mc.check(m) == []
    assert mc.locate(m, 7.5, 2.5) == (["ridge"], [])
    (tmp_path / "maps").mkdir()
    (tmp_path / "maps" / "m.json").write_text(json.dumps(m))
    w = world()
    w["map"] = {
        "coords": "lonlat",
        "file": "m.json",
        "sha256": mc.load(tmp_path / "maps" / "m.json")[1],
    }
    w["entities"] = [
        {"key": "fort", "kind": "location", "name": "F", "at": [2.5, 7.5], "within": "ridge"}
    ]
    path = tmp_path / "w.yaml"
    path.write_text(yaml.safe_dump(w))
    assert mc.check_world(path).problems == []
    w["entities"][0]["at"] = [7.5, 2.5]
    path.write_text(yaml.safe_dump(w))
    assert ("place", "fort") in codes(mc.check_world(path).problems)


# Rule 5: the proof sheet.


def test_the_proof_sheet_draws_borders_names_sites_adjacency_and_cut_lines() -> None:
    w = yaml.safe_load((CASES / "scoped-world.yaml").read_text())
    w["adjacency"].append({"a": "marsh", "b": "bay", "crossing": "the causeway"})
    recipe = {
        "cuts": [
            {
                "name": "the old dyke",
                "line": [[10, 5], [10, 45]],
                "source": "Survey of 1850, sheet 4",
            },
            {"name": "the new drain", "line": [[30, 5], [30, 45]], "gap": True},
        ]
    }
    sheets = mc.render(three(), w, [recipe], name="three-areas")
    assert sorted(sheets) == ["three-areas", "three-areas-lowlands"]
    svg = sheets["three-areas"]
    root = ET.fromstring(svg)
    texts = " ".join(t.text or "" for t in root.iter("{http://www.w3.org/2000/svg}text"))
    for word in ("The Marsh", "The Ridge", "The Bay", "The Mill", "The Tower", "the old dyke"):
        assert word in texts, word
    assert "Survey of 1850, sheet 4" in texts
    assert "gap" in texts
    classes = [e.get("class") or "" for e in root.iter()]
    assert classes.count("area") == 2
    assert classes.count("area sea") == 1
    assert classes.count("backdrop") == 1
    assert classes.count("adj") == 2
    assert classes.count("crossing") == 1
    assert classes.count("site") == 4
    assert classes.count("cut") == 1
    assert classes.count("cut gap") == 1
    assert mc.render(three(), w, [recipe], name="three-areas") == sheets


def test_the_proof_sheet_draws_a_map_with_no_world() -> None:
    sheets = mc.render(case("island-in-sea"), None, [], name="islands")
    assert list(sheets) == ["islands"]
    ET.fromstring(sheets["islands"])


# The command line.


def test_the_command_line_checks_a_map_and_a_world(capsys: pytest.CaptureFixture[str]) -> None:
    assert mc.main(["check", str(THREE)]) == 0
    assert f"ok {THREE}" in capsys.readouterr().out
    assert mc.main(["check", "--world", str(CASES / "scoped-world.yaml")]) == 1
    out = capsys.readouterr().out
    assert "tower: lies in no area" in out
    assert mc.main(["check", "--region", str(CASES / "scoped-pass.staging.yaml")]) == 0
    assert "out of scope: tower" in capsys.readouterr().out
    assert mc.main(["check", str(CASES / "gap.json")]) == 1


def test_the_command_line_prints_adjacency(capsys: pytest.CaptureFixture[str]) -> None:
    assert mc.main(["adjacency", str(THREE)]) == 0
    assert yaml.safe_load(capsys.readouterr().out) == {
        "adjacency": [["bay", "ridge"], ["marsh", "ridge"]]
    }


def test_the_command_line_renders(tmp_path: Path) -> None:
    world_path = CASES / "scoped-world.yaml"
    assert mc.main(["render", str(THREE), "--world", str(world_path), "--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "three-areas-lowlands.svg",
        "three-areas.svg",
    ]


def test_the_readme_names_the_format_the_commands_and_the_licence_rule() -> None:
    text = (ROOT / "worlds" / "maps" / "README.md").read_text()
    for word in ("vertices", "areas", "backdrop", "label", "rings", "box", "coords"):
        assert f"`{word}`" in text, word
    for command in ("check", "adjacency", "render"):
        assert f"map_check.py {command}" in text, command
    for word in ("CShapes", "historical-basemaps", "Natural Earth"):
        assert word in text, word
