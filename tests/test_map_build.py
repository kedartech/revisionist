"""The map build: recipes dissolved, cut, cut from the ocean and simplified into a checked map.

Runs on the committed fixture (made-up provinces and a strip of sea), never on the border data, and
skips when the geometry tool is absent, as it is in CI.
"""

import copy
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

pytest.importorskip("shapely")

ROOT = Path(__file__).resolve().parents[1]
MAPS = Path(__file__).resolve().parent / "maps"
GEOJSON = MAPS / "build-fixture.geojson"
RECIPE = MAPS / "build-fixture.recipe.yaml"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_build", ROOT / "scripts" / "map_build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mb = _load()
mc = mb.map_check


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources(path: Path, data: Path) -> None:
    rows = [
        f"| {f.name} | {_sha(f)} | {f.stat().st_size} | https://example.invalid/{f.name} |"
        for f in sorted(data.iterdir())
    ]
    path.write_text(
        "# Map sources\n\n| file | sha256 | bytes | url |\n|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )


def _square(x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


# The land file: an islet in the strait that no province holds, and a strip that overlaps the coast
# province and runs past it, as two files tracing one coast a little apart do.
LAND = {
    "type": "FeatureCollection",
    "features": [_square(3.2, 1.7, 3.3, 1.8), _square(2.9, 0.2, 3.05, 0.4)],
}


@pytest.fixture
def env(tmp_path: Path) -> dict[str, Path]:
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(GEOJSON, data / mb.PROVINCES)
    (data / mb.LAND).write_text(json.dumps(LAND))
    sources = tmp_path / "SOURCES.md"
    _sources(sources, data)
    return {"data": data, "sources": sources, "out": tmp_path / "out", "tmp": tmp_path}


def _recipe(env: dict[str, Path], name: str = "recipe.yaml", **changes: Any) -> Path:
    doc = yaml.safe_load(RECIPE.read_text())
    doc.update(changes)
    path = env["tmp"] / name
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return path


def build(env: dict[str, Path], recipes: list[Path] | None = None, **kw: Any) -> Any:
    return mb.build(
        recipes or [RECIPE],
        data=env["data"],
        sources=env["sources"],
        out=kw.pop("out", env["out"]),
        slug=kw.pop("slug", "fixture"),
        **kw,
    )


def _map(built: Any) -> Any:
    return json.loads(Path(built.map_path).read_text())


def _world(built: Any) -> Any:
    return yaml.safe_load(Path(built.world_path).read_text())


def _where(raw: Any, x: float, y: float) -> list[str]:
    inside, border = mc.locate(raw, x, y)
    assert not border
    return list(inside)


# ---------------------------------------------------------------- rule 1: the recipe


def test_recipe_files_in_one_directory_build_as_one_map(env: dict[str, Path]) -> None:
    whole = build(env, out=env["tmp"] / "one")
    doc = yaml.safe_load(RECIPE.read_text())
    parts = env["tmp"] / "parts"
    parts.mkdir()
    sea = {k: doc.pop(k) for k in ("sea_zones", "crossings")}
    (parts / "a-land.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    (parts / "b-sea.yaml").write_text(yaml.safe_dump(sea, sort_keys=False))
    split = build(env, [parts], out=env["tmp"] / "two")
    assert split.sha256 == whole.sha256
    assert "strait" in _map(split)["areas"]


def test_recipes_that_disagree_on_the_box_are_refused(env: dict[str, Path]) -> None:
    other = env["tmp"] / "other.yaml"
    other.write_text("map: {box: [0, 0, 5, 3]}\n")
    with pytest.raises(mb.BuildError, match=r"other\.yaml: its box"):
        build(env, [RECIPE, other])


# ---------------------------------------------------------------- rule 2: data and province codes


@pytest.mark.parametrize("name", ["PROVINCES", "LAND"])
def test_a_data_file_whose_hash_differs_is_refused_by_name(env: dict[str, Path], name: str) -> None:
    with (env["data"] / getattr(mb, name)).open("a") as f:
        f.write(" ")
    with pytest.raises(mb.BuildError, match=getattr(mb, name)):
        build(env)
    assert not env["out"].exists()


def test_a_data_file_sources_does_not_record_is_refused(env: dict[str, Path]) -> None:
    env["sources"].write_text("# Map sources\n\nno table\n")
    with pytest.raises(mb.BuildError, match=mb.PROVINCES):
        build(env)


def test_a_province_the_data_lacks_is_named(env: dict[str, Path]) -> None:
    doc = yaml.safe_load(RECIPE.read_text())
    doc["territories"][1]["provinces"] = ["FX-N1", "FX-NOPE"]
    with pytest.raises(mb.BuildError, match="FX-NOPE"):
        build(env, [_recipe(env, territories=doc["territories"])])


def test_a_province_two_territories_claim_is_named(env: dict[str, Path]) -> None:
    doc = yaml.safe_load(RECIPE.read_text())
    doc["territories"][1]["provinces"] = ["FX-N1", "FX-W2"]
    with pytest.raises(mb.BuildError, match=r"FX-W2.*(west.*north|north.*west)"):
        build(env, [_recipe(env, territories=doc["territories"])])


# ---------------------------------------------------------------- rule 3: dissolve and cut


def test_a_territory_is_its_provinces_dissolved(env: dict[str, Path]) -> None:
    raw = _map(build(env))
    assert mc.area(raw, "west") == pytest.approx(2.0, abs=0.01)
    assert _where(raw, 0.5, 0.5) == ["west"]
    assert _where(raw, 1.5, 0.5) == ["west"]
    assert len(raw["areas"]["west"]["rings"]) == 1
    verts = raw["vertices"]
    inner = [verts[i] for i in raw["areas"]["west"]["rings"][0] if verts[i] == [1, 1]]
    assert inner == []


def test_a_cut_gives_each_side_to_the_territory_the_recipe_names(env: dict[str, Path]) -> None:
    raw = _map(build(env))
    assert _where(raw, 2.25, 0.75) == ["middle"]
    assert _where(raw, 2.75, 0.75) == ["coast"]
    assert mc.area(raw, "middle") == pytest.approx(0.75, abs=0.001)
    assert mc.area(raw, "coast") == pytest.approx(0.75, abs=0.001)


def test_a_cut_that_stops_inside_its_province_fails(env: dict[str, Path]) -> None:
    doc = yaml.safe_load(RECIPE.read_text())
    doc["cuts"][0]["line"] = [[2.5, -0.1], [2.5, 1.0]]
    with pytest.raises(mb.BuildError, match="the fixture line"):
        build(env, [_recipe(env, cuts=doc["cuts"])])


def test_a_cut_that_misses_its_province_fails(env: dict[str, Path]) -> None:
    doc = yaml.safe_load(RECIPE.read_text())
    doc["cuts"][0]["line"] = [[1.5, -0.1], [1.5, 1.6]]
    with pytest.raises(mb.BuildError, match="the fixture line"):
        build(env, [_recipe(env, cuts=doc["cuts"])])


# ---------------------------------------------------------------- rule 4: sea zones and backdrop


def test_a_sea_zone_is_its_polygon_cut_from_the_ocean(env: dict[str, Path]) -> None:
    raw = _map(build(env))
    # the polygon's x 2.9..3 lies over land; the isle (0.12), the skerry (0.0875) and the islet
    # (0.01) are holes
    assert mc.area(raw, "strait") == pytest.approx(2.0 - 0.12 - 0.0875 - 0.01, abs=0.001)
    assert _where(raw, 3.5, 0.5) == ["strait"]
    assert _where(raw, 3.25, 1.75) == []  # an island no province holds is land, in the backdrop
    assert _where(raw, 3.02, 0.3) == ["strait"]  # a sliver touching a province is not
    assert _where(raw, 2.95, 1.75) == []  # unclaimed land under the polygon stays land
    assert _where(raw, 2.95, 0.75) == ["coast"]


def test_a_coast_is_one_border_shared_by_land_and_sea(env: dict[str, Path]) -> None:
    raw = _map(build(env))
    assert mc.shared_length(raw, "coast", "strait") == pytest.approx(1.5)
    assert mc.shared_length(raw, "isle", "strait") == pytest.approx(2 * (0.3 + 0.4) - 0.05)


def test_unclaimed_land_and_water_become_the_backdrop(env: dict[str, Path]) -> None:
    raw = _map(build(env))
    assert raw["backdrop"]
    assert _where(raw, 2.5, 2.5) == []
    assert _where(raw, 3.5, 2.5) == []
    assert mc.check(raw) == []
    playable = sum(mc.area(raw, k) for k in raw["areas"])
    assert playable == pytest.approx(12.0 - 1.5 - 1.0 - 0.01, abs=0.001)


def _with_islet(env: dict[str, Path], islet: dict[str, Any]) -> None:
    land = {"type": "FeatureCollection", "features": [*copy.deepcopy(LAND["features"]), islet]}
    (env["data"] / mb.LAND).write_text(json.dumps(land))
    _sources(env["sources"], env["data"])


def test_an_islet_nearer_a_province_than_the_tolerance_is_water(env: dict[str, Path]) -> None:
    # MAC: an islet no province holds, 0.02 off the cut province's coast, cannot be kept apart from
    # that coast when the borders are simplified at 0.05 (the coast is simplified across it), so the
    # build leaves it out as water; with no simplifying it stays land, in the backdrop.
    _with_islet(env, _square(3.02, 0.55, 3.12, 0.65))
    raw = _map(build(env))
    assert _where(raw, 3.07, 0.6) == ["strait"]
    assert mc.check(raw) == []
    exact = _map(build(env, tolerance=0, out=env["tmp"] / "exact"))
    assert _where(exact, 3.07, 0.6) == []


def test_an_islet_farther_than_the_tolerance_stays_land(env: dict[str, Path]) -> None:
    _with_islet(env, _square(3.2, 0.5, 3.3, 0.6))
    raw = _map(build(env))
    assert _where(raw, 3.25, 0.55) == []


def test_two_sea_zones_over_the_same_water_are_named(env: dict[str, Path]) -> None:
    doc = yaml.safe_load(RECIPE.read_text())
    extra: dict[str, Any] = {"key": "sound", "name": "The Sound", "region": "fixland"}
    extra["polygon"] = [[3.2, 1.6], [4.5, 1.6], [4.5, 3.5], [3.2, 3.5]]
    with pytest.raises(mb.BuildError, match=r"strait.*sound|sound.*strait"):
        build(env, [_recipe(env, sea_zones=[*doc["sea_zones"], extra])])


# ---------------------------------------------------------------- rule 5: simplify together


@pytest.mark.parametrize("how", ["coverage", "arcs"])
def test_simplifying_keeps_one_shared_border(env: dict[str, Path], how: str) -> None:
    built = build(env, simplify=how)
    raw = _map(built)
    assert built.simplify == how
    assert mc.check(raw) == []
    verts = raw["vertices"]
    for key in ("west", "north"):
        wiggles = [verts[i] for r in raw["areas"][key]["rings"] for i in r if 0 < verts[i][0] < 2]
        assert all(abs(y - 1) > 0.5 for _, y in wiggles), (key, wiggles)
    assert mc.shared_length(raw, "west", "north") == pytest.approx(2.0)


def test_both_paths_simplify_less_with_a_smaller_tolerance(env: dict[str, Path]) -> None:
    for how in ("coverage", "arcs"):
        raw = _map(build(env, simplify=how, tolerance=0.0001, out=env["tmp"] / how))
        assert mc.check(raw) == []
        ys = {raw["vertices"][i][1] for i in raw["areas"]["north"]["rings"][0]}
        assert {0.999, 1.001} <= ys, how


def test_the_tools_simplifier_is_used_when_it_has_one(env: dict[str, Path]) -> None:
    built = build(env)
    assert built.simplify == ("coverage" if mb.has_coverage_simplify() else "arcs")
    assert f"simplify {built.simplify}" in Path(built.world_path).read_text()


# ------------------------------------------------------------- rule 6: adjacency and the fragment


EXPECTED = {
    ("middle", "north"),
    ("middle", "west"),
    ("north", "west"),
    ("coast", "middle"),
    ("coast", "strait"),
    ("isle", "strait"),
    ("skerry", "strait"),
}


def _pairs(world: Any) -> tuple[set[tuple[str, str]], list[Any]]:
    plain = {tuple(sorted(e)) for e in world["adjacency"] if isinstance(e, list)}
    crossings = [e for e in world["adjacency"] if isinstance(e, dict)]
    return plain, crossings


def test_adjacency_is_derived_with_the_checkers_predicate(env: dict[str, Path]) -> None:
    built = build(env)
    plain, crossings = _pairs(_world(built))
    assert plain == EXPECTED
    assert ("isle", "skerry") not in plain  # they share 0.05, under MIN_SHARED
    assert crossings == [{"a": "isle", "b": "west", "crossing": "the ferry"}]


def test_adjacency_follows_the_checkers_threshold(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(mc.MIN_SHARED, "lonlat", 0.05)
    plain, _ = _pairs(_world(build(env)))
    assert plain == EXPECTED | {("isle", "skerry")}


def test_the_world_fragment_lists_the_areas_and_names_the_map(env: dict[str, Path]) -> None:
    built = build(env)
    world = _world(built)
    assert world["map"] == {
        "coords": "lonlat",
        "file": "fixture.json",
        "sha256": built.sha256,
        "box": [0, 0, 4, 3],
    }
    assert world["regions"] == [{"key": "fixland", "name": "Fixture Land"}]
    keys = [t["key"] for t in world["territories"]]
    assert keys == ["west", "north", "middle", "coast", "isle", "skerry"]
    west = world["territories"][0]
    assert west == {
        "key": "west",
        "name": "The West",
        "region": "fixland",
        "terrain": "plain",
        "sites": ["mill"],
    }
    assert world["sea_zones"] == [
        {"key": "strait", "name": "The Strait", "region": "fixland", "terrain": "sea"}
    ]
    problems = mc.check_world(built.world_path).problems
    assert [(p.code, p.face) for p in problems] == [("whole", "map")]


# ---------------------------------------------------------------- rule 7: same bytes, kept objects


def test_the_same_inputs_give_the_same_bytes(env: dict[str, Path]) -> None:
    a = build(env, out=env["tmp"] / "a")
    b = build(env, out=env["tmp"] / "b")
    assert Path(a.map_path).read_bytes() == Path(b.map_path).read_bytes()
    assert Path(a.world_path).read_bytes() == Path(b.world_path).read_bytes()
    assert a.sha256 == b.sha256 == _sha(Path(a.map_path))


def test_the_map_is_kept_as_its_object_and_listed_once(env: dict[str, Path]) -> None:
    built = build(env)
    build(env)
    obj = env["out"] / "objects" / f"{built.sha256}.json"
    assert obj.read_bytes() == Path(built.map_path).read_bytes()
    lines = (env["out"] / "objects" / "MANIFEST").read_text().splitlines()
    assert lines.count(built.sha256) == 1


def test_an_existing_object_is_never_overwritten(env: dict[str, Path]) -> None:
    sha = build(env, out=env["tmp"] / "first").sha256
    obj = env["out"] / "objects" / f"{sha}.json"
    obj.parent.mkdir(parents=True)
    obj.write_text("not the map\n")
    with pytest.raises(mb.BuildError, match=sha):
        build(env)
    assert obj.read_text() == "not the map\n"


def test_the_command_prints_the_hash(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    code = mb.main(
        [
            "build",
            str(RECIPE),
            "--slug",
            "fixture",
            "--data",
            str(env["data"]),
            "--sources",
            str(env["sources"]),
            "--out",
            str(env["out"]),
        ]
    )
    assert code == 0
    assert _sha(env["out"] / "fixture.json") in capsys.readouterr().out


# ---------------------------------------------------------------- rule 8: the date line


def test_a_territory_across_the_date_line_stays_one_area(env: dict[str, Path]) -> None:
    recipe = env["tmp"] / "dateline.yaml"
    recipe.write_text(
        yaml.safe_dump(
            {
                "map": {"box": [178.5, 9.5, 181.5, 11.5]},
                "regions": [{"key": "pacific", "name": "Pacific"}],
                "territories": [
                    {
                        "key": "line",
                        "name": "The Line",
                        "region": "pacific",
                        "provinces": ["FX-E", "FX-F"],
                    },
                ],
            }
        )
    )
    raw = _map(build(env, [recipe], slug="dateline"))
    assert mc.check(raw) == []
    assert len(raw["areas"]["line"]["rings"]) == 1
    xs = {raw["vertices"][i][0] for i in raw["areas"]["line"]["rings"][0]}
    assert min(xs) == 179 and max(xs) == 181
    assert mc.area(raw, "line") == pytest.approx(2.0)


# ---------------------------------------------------------------- rule 9: the build runs the check


def test_a_map_that_fails_the_check_is_not_written(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(mc.MIN_AREA, "lonlat", 0.1)
    with pytest.raises(mb.BuildError, match=r"skerry: its area"):
        build(env)
    assert not (env["out"] / "fixture.json").exists()


# ---------------------------------------------------------------- rule 10: river zones

BROOK = {
    "key": "brook",
    "name": "The Brook",
    "region": "fixland",
    "terrain": "river",
    "width": 0.2,
    "borders": [["FX-W2", "FX-C"]],
}


def _river(env: dict[str, Path], **changes: Any) -> Path:
    return _recipe(env, rivers=[{**BROOK, **changes}])


def test_a_river_zone_follows_the_shared_border_of_its_provinces(env: dict[str, Path]) -> None:
    raw = _map(build(env, [_river(env)]))
    assert mc.area(raw, "brook") == pytest.approx(0.2, abs=0.001)
    assert _where(raw, 2.0, 0.5) == ["brook"]
    assert _where(raw, 1.95, 0.5) == ["brook"]
    assert _where(raw, 2.05, 0.5) == ["brook"]
    assert _where(raw, 2.15, 0.5) == ["middle"]


def test_a_river_zone_is_carved_from_the_land_on_both_banks(env: dict[str, Path]) -> None:
    raw = _map(build(env, [_river(env)]))
    assert mc.area(raw, "west") == pytest.approx(2.0 - 0.1, abs=0.01)
    assert mc.area(raw, "middle") == pytest.approx(0.75 - 0.1, abs=0.001)
    assert not mc.adjacent(raw, "west", "middle")
    assert mc.adjacent(raw, "brook", "west")
    assert mc.adjacent(raw, "brook", "middle")


def test_a_river_zone_is_listed_with_the_sea_zones(env: dict[str, Path]) -> None:
    built = build(env, [_river(env)])
    zones = _world(built)["sea_zones"]
    assert zones[-1] == {
        "key": "brook",
        "name": "The Brook",
        "region": "fixland",
        "terrain": "river",
    }
    problems = mc.check_world(built.world_path).problems
    assert [(p.code, p.face) for p in problems] == [("whole", "map")]


def test_a_river_zones_polygon_limits_the_stretch_it_follows(env: dict[str, Path]) -> None:
    clip = [[1.5, -1], [2.5, -1], [2.5, 0.5], [1.5, 0.5]]
    raw = _map(build(env, [_river(env, polygon=clip)]))
    assert mc.area(raw, "brook") == pytest.approx(0.1, abs=0.001)
    assert mc.locate(raw, 2.0, 0.75) == ([], ["middle", "west"])  # the border, past the stretch
    assert mc.adjacent(raw, "west", "middle")


def test_a_river_between_provinces_that_share_no_border_is_refused(env: dict[str, Path]) -> None:
    with pytest.raises(mb.BuildError, match=r"brook: FX-W1 and FX-C share no border"):
        build(env, [_river(env, borders=[["FX-W1", "FX-C"]])])


def test_a_river_with_no_width_is_refused(env: dict[str, Path]) -> None:
    with pytest.raises(mb.BuildError, match=r"brook: a river zone needs a width"):
        build(env, [_river(env, width=0)])


def test_two_river_zones_over_the_same_land_are_named(env: dict[str, Path]) -> None:
    twin = {**BROOK, "key": "creek", "name": "The Creek"}
    with pytest.raises(mb.BuildError, match=r"creek: the river zone covers land brook already"):
        build(env, [_recipe(env, rivers=[BROOK, twin])])


# ---------------------------------------------------------------- the whole map

GLOBE = [-180, -60, 180, 84]


def _whole(env: dict[str, Path], **changes: Any) -> Path:
    """The fixture recipe over the whole globe: every province claimed, one ocean over the box."""
    doc = yaml.safe_load(RECIPE.read_text())
    doc["map"] = {"box": GLOBE, "cover": "whole"}
    doc["territories"] += [
        {
            "key": "uplands",
            "name": "The Uplands",
            "region": "fixland",
            "terrain": "hills",
            "provinces": ["FX-N2"],
        },
        {
            "key": "dateline",
            "name": "The Date Line",
            "region": "fixland",
            "terrain": "plain",
            "provinces": ["FX-E", "FX-F"],
        },
    ]
    w, s, e, n = GLOBE
    doc["sea_zones"] = [
        {
            "key": "ocean",
            "name": "The Ocean",
            "region": "fixland",
            "terrain": "sea",
            "polygon": [[w, s], [e, s], [e, n], [w, n]],
        }
    ]
    doc.update(changes)
    path = env["tmp"] / "whole.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return path


def test_a_whole_map_of_60_s_to_84_n_builds_with_no_backdrop(env: dict[str, Path]) -> None:
    raw = _map(build(env, [_whole(env)]))
    assert raw["box"] == GLOBE
    assert raw["cover"] == "whole"
    assert raw["backdrop"] == []
    assert mc.check(raw) == []


def test_a_map_without_the_mark_is_written_as_before(env: dict[str, Path]) -> None:
    assert "cover" not in _map(build(env))


def test_land_no_recipe_claims_is_reported_by_its_unit_and_fails(env: dict[str, Path]) -> None:
    doc = yaml.safe_load(_whole(env).read_text())
    doc["territories"] = [t for t in doc["territories"] if t["key"] != "uplands"]
    path = env["tmp"] / "short.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    with pytest.raises(mb.BuildError, match=r"no recipe claims[\s\S]*FX-N2 \(North Two\)"):
        build(env, [path])


def test_water_no_sea_zone_takes_fails_a_whole_map(env: dict[str, Path]) -> None:
    strait = yaml.safe_load(RECIPE.read_text())["sea_zones"]
    with pytest.raises(mb.BuildError, match=r"backdrop"):
        build(env, [_whole(env, sea_zones=strait)])


def test_an_island_no_unit_holds_goes_to_the_territory_nearest_it(env: dict[str, Path]) -> None:
    raw = _map(build(env, [_whole(env)]))
    assert _where(raw, 3.25, 1.75) == ["uplands"]


def test_an_island_under_the_least_size_is_dropped_as_water(env: dict[str, Path]) -> None:
    (env["data"] / mb.LAND).write_text(
        json.dumps({"type": "FeatureCollection", "features": [_square(3.2, 1.7, 3.25, 1.75)]})
    )
    _sources(env["sources"], env["data"])
    raw = _map(build(env, [_whole(env)]))
    assert _where(raw, 3.225, 1.725) == ["ocean"]


def test_a_cover_other_than_whole_is_refused(env: dict[str, Path]) -> None:
    other = env["tmp"] / "other.yaml"
    other.write_text("map: {box: [0, 0, 4, 3], cover: territories}\n")
    with pytest.raises(mb.BuildError, match=r"other\.yaml: map\.cover"):
        build(env, [RECIPE, other])
