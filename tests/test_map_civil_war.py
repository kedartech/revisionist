"""The Civil War's map, 1 September 1862: built by recipe from the cached border data.

Reads the committed map, its world fragment, its recipe and its proof sheets; needs neither the
geometry tool nor the border data, so it runs in CI. The one test that builds the map again from the
data skips when either is absent.
"""

import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "worlds" / "maps"
MAP = MAPS / "civil-war-1862.json"
FRAGMENT = MAPS / "civil-war-1862.world.yaml"
SRC = MAPS / "src" / "civil-war-1862"
RECIPE = SRC / "recipe.yaml"
PROOF = MAPS / "proof"
WHOLE_BOX = [-180, -60, 180, 84]
DATA = os.environ.get("REVISIONIST_MAP_DATA")
"""Read at import: the suite's fixture clears every REVISIONIST_ variable before each test."""
THEATRES = ("eastern_theatre", "western_theatre")
# Places named by the tests, latitude first as the world files write them; general knowledge, not a
# border: each lies well inside the area it is tested against.
WASHINGTON = (38.8951, -77.0364)
RICHMOND = (37.5407, -77.4360)
BANKS = ("missouri", "illinois", "kentucky", "tennessee", "arkansas", "mississippi", "louisiana")
COAST = (
    "northern_waters",
    "chesapeake",
    "carolina_sounds",
    "south_atlantic_coast",
    "florida_straits",
    "eastern_gulf",
    "western_gulf",
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mc = _load("map_check")


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def raw() -> Any:
    return json.loads(MAP.read_text())


@pytest.fixture(scope="module")
def world() -> Any:
    return _yaml(FRAGMENT)


@pytest.fixture(scope="module")
def recipe() -> Any:
    return _yaml(RECIPE)


def _at(raw: Any, place: tuple[float, float]) -> list[str]:
    inside, border = mc.locate(raw, place[1], place[0])
    assert not border, place
    return list(inside)


def _area2(raw: Any, ring: list[int]) -> float:
    pts = [raw["vertices"][i] for i in ring]
    return float(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in itertools.pairwise(pts)))


# ---------------------------------------------------------------- rule 4: the checker passes


def test_the_fragment_passes_the_strict_check() -> None:
    # every check of the map file alone, and the fragment's areas, box and adjacency against it
    assert mc.check_world(FRAGMENT).problems == []


def test_adjacency_is_the_shared_borders_under_the_one_predicate(raw: Any, world: Any) -> None:
    plain = {tuple(sorted(e)) for e in world["adjacency"] if isinstance(e, list)}
    assert plain == {tuple(sorted(p)) for p in mc.adjacency(raw)} - _crossed(world)


def _crossed(world: Any) -> set[tuple[str, ...]]:
    return {tuple(sorted((e["a"], e["b"]))) for e in world["adjacency"] if isinstance(e, dict)}


# ---------------------------------------------------------------- the whole map and its cover


def test_the_box_is_the_whole_maps(raw: Any, world: Any, recipe: Any) -> None:
    assert raw["box"] == WHOLE_BOX
    assert world["map"]["box"] == WHOLE_BOX
    assert recipe["map"]["box"] == WHOLE_BOX


def test_every_area_the_recipe_lists_is_on_the_map_and_no_other(raw: Any, recipe: Any) -> None:
    listed = [a["key"] for k in ("territories", "sea_zones", "rivers") for a in recipe[k]]
    assert sorted(raw["areas"]) == sorted(listed)


def test_the_backdrop_holds_no_face_as_large_as_an_area(raw: Any) -> None:
    # Every unit of the data in the box is claimed and the zones cover every water face, so the
    # backdrop is only the islets no unit holds, each smaller than the smallest area allowed.
    smallest = mc.MIN_AREA["lonlat"]
    sizes = [abs(_area2(raw, r)) / 2 for r in raw["backdrop"]]
    assert max(sizes) < smallest
    assert sum(sizes) < 1.0


def test_the_world_beyond_the_theatres_is_coarse(recipe: Any) -> None:
    beyond = [t for t in recipe["territories"] if t["region"] == "the_world"]
    oceans = [z for z in recipe["sea_zones"] if z["region"] == "the_world"]
    assert len(beyond) + len([t for t in recipe["territories"] if t["region"] in THEATRES]) == len(
        recipe["territories"]
    )
    assert 25 <= len(beyond) <= 36
    assert 10 <= len(oceans) <= 14


# ------------------------------------------------------------ rule 1: the theatres and the capitals


def test_the_theatres_have_about_25_land_territories_and_8_water_zones(recipe: Any) -> None:
    land = [t for t in recipe["territories"] if t["region"] in THEATRES]
    water = [z for k in ("sea_zones", "rivers") for z in recipe[k] if z["region"] == "the_coast"]
    assert 22 <= len(land) <= 30
    assert len(water) == 8


def test_the_capitals_lie_in_different_territories_a_short_march_apart(raw: Any) -> None:
    assert _at(raw, WASHINGTON) == ["maryland"]
    assert _at(raw, RICHMOND) == ["virginia"]
    assert mc.adjacent(raw, "maryland", "virginia")
    assert math.dist(WASHINGTON, RICHMOND) < 2.0


def test_each_capital_is_a_site_of_its_territory(world: Any) -> None:
    sites = {t["key"]: t.get("sites", []) for t in world["territories"]}
    assert sites["maryland"] == ["washington"]
    assert sites["virginia"] == ["richmond"]


# ---------------------------------------------------------------- rule 2: 1862 lines


def test_virginia_is_the_two_present_day_states_dissolved_with_no_cut(recipe: Any) -> None:
    virginia = next(t for t in recipe["territories"] if t["key"] == "virginia")
    assert sorted(virginia["provinces"]) == ["USA-3552", "USA-3554"]
    assert not virginia.get("gap")
    assert not recipe.get("cuts")


def test_every_gap_is_marked_with_its_reason(recipe: Any) -> None:
    for t in recipe["territories"]:
        assert bool(t.get("gap")) == bool(t.get("gap_note")), t["key"]


def test_every_territory_has_a_terrain_with_a_source_or_a_gap(recipe: Any) -> None:
    for t in recipe["territories"]:
        assert t.get("terrain"), t["key"]
        assert bool(t.get("terrain_source")) != bool(t.get("terrain_gap")), t["key"]


def test_no_province_is_claimed_twice(recipe: Any) -> None:
    codes = [c for t in recipe["territories"] for c in t["provinces"]]
    assert len(codes) == len(set(codes))


# ---------------------------------------------------------------- rule 3: the river and the coast


def test_the_mississippi_and_the_coast_are_zones_a_fleet_can_stand_in(world: Any) -> None:
    zones = {z["key"]: z["terrain"] for z in world["sea_zones"]}
    assert zones["mississippi_river"] == "river"
    assert all(zones[k] == "sea" for k in COAST)
    assert "mississippi_river" not in {t["key"] for t in world["territories"]}


def test_the_river_touches_every_state_on_its_banks(raw: Any) -> None:
    for bank in BANKS:
        assert mc.adjacent(raw, "mississippi_river", bank), bank


def test_the_river_parts_its_banks_and_each_pair_is_a_crossing(raw: Any, world: Any) -> None:
    parted = [("illinois", "missouri"), ("kentucky", "missouri"), ("missouri", "tennessee")]
    parted += [("arkansas", "tennessee"), ("arkansas", "mississippi")]
    for a, b in parted:
        assert not mc.adjacent(raw, a, b), (a, b)
        assert (a, b) in _crossed(world), (a, b)


def test_the_river_joins_the_gulf_by_a_crossing(world: Any) -> None:
    assert ("mississippi_river", "western_gulf") in _crossed(world)


def test_each_coast_zone_touches_the_coast_it_is_named_for(raw: Any) -> None:
    pairs = [
        ("chesapeake", "virginia"),
        ("chesapeake", "maryland"),
        ("northern_waters", "new_england"),
        ("carolina_sounds", "north_carolina"),
        ("south_atlantic_coast", "south_carolina"),
        ("south_atlantic_coast", "georgia"),
        ("florida_straits", "florida"),
        ("eastern_gulf", "alabama"),
        ("western_gulf", "louisiana"),
        ("western_gulf", "texas"),
    ]
    for zone, land in pairs:
        assert mc.adjacent(raw, zone, land), (zone, land)


# ------------------------------------------------------------ rule 5: the map object and the proof


def test_the_map_is_kept_as_its_object_and_listed_in_the_manifest(world: Any) -> None:
    sha = hashlib.sha256(MAP.read_bytes()).hexdigest()
    assert world["map"]["sha256"] == sha
    assert (MAPS / "objects" / f"{sha}.json").read_bytes() == MAP.read_bytes()
    assert sha in (MAPS / "objects" / "MANIFEST").read_text().split()


def test_the_proof_sheets_are_the_ones_the_checker_renders(raw: Any, world: Any) -> None:
    sheets = mc.render(raw, world, [_yaml(RECIPE)], MAP.stem)
    regions = {r["key"] for r in world["regions"]}
    assert set(sheets) == {MAP.stem} | {f"{MAP.stem}-{r}" for r in regions}
    for name, svg in sheets.items():
        assert (PROOF / f"{name}.svg").read_text() == svg, name


# ---------------------------------------------------------------- the build, repeated


def test_the_recipe_builds_the_committed_map_byte_for_byte(tmp_path: Path) -> None:
    pytest.importorskip("shapely")
    if not DATA:
        pytest.skip("REVISIONIST_MAP_DATA is not set")
    mb = _load("map_build")
    built = mb.build(
        [SRC], data=Path(DATA), sources=MAPS / "SOURCES.md", out=tmp_path, slug=MAP.stem
    )
    assert built.map_path.read_bytes() == MAP.read_bytes()
    assert built.world_path.read_text() == FRAGMENT.read_text()
