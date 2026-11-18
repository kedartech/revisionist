"""The 1941 map: the Eastern Front pilot region, read from the committed files only.

Pins that every place the world has on the Eastern Front lies in exactly one territory of the
built map, that Smolensk, Vyazma and Mozhaisk lie in the same or adjacent territories, and that the
map passes the scoped check against the region's staging world. It reads the committed map, its
staging world and today's world file; it needs neither the geometry tool nor the border data, so it
runs in CI.
"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "worlds" / "maps" / "autumn-1941.json"
FRAGMENT = ROOT / "worlds" / "maps" / "autumn-1941.world.yaml"
SRC = ROOT / "worlds" / "maps" / "src" / "autumn-1941"
RECIPE = SRC / "eastern-front.yaml"
STAGING = SRC / "eastern-front.world.yaml"
WORLD = ROOT / "worlds" / "autumn-1941.yaml"

# Rule 2: every place the world has on the Eastern Front today.
SITES = (
    "leningrad",
    "kalinin",
    "smolensk",
    "vyazma",
    "mozhaisk",
    "moscow",
    "kiev",
    "poltava",
    "kharkov",
    "odessa",
    "taganrog",
    "archangel",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_check", ROOT / "scripts" / "map_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mc = _load()


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def _raw() -> Any:
    return json.loads(MAP.read_text())


def _world_places() -> dict[str, Any]:
    return {
        str(e["key"]): e
        for e in _yaml(WORLD)["entities"]
        if e.get("kind") == "location" and isinstance(e.get("at"), list)
    }


def _territory_keys() -> set[str]:
    return {str(t["key"]) for t in _yaml(STAGING)["territories"]}


def _home(site: str) -> str:
    """The one area the world's place lies in; fails when it lies in none, several or a border."""
    lat, lon = _world_places()[site]["at"]
    inside, border = mc.locate(_raw(), float(lon), float(lat))
    assert not border, f"{site} lies on the border of {border}"
    assert len(inside) == 1, f"{site} lies in {inside}"
    return str(inside[0])


def _same_or_adjacent(a: str, b: str) -> bool:
    ka, kb = _home(a), _home(b)
    return ka == kb or bool(mc.adjacent(_raw(), ka, kb))


# ---------------------------------------------------------------- the files


def test_the_map_passes_the_check() -> None:
    assert mc.check(_raw()) == []


def test_the_staging_world_names_the_committed_map() -> None:
    ref = _yaml(STAGING)["map"]
    assert ref["sha256"] == hashlib.sha256(MAP.read_bytes()).hexdigest()
    assert mc.map_path(STAGING, ref["file"]) == MAP.resolve()


def test_the_built_fragment_names_the_committed_map() -> None:
    ref = _yaml(FRAGMENT)["map"]
    assert ref["file"] == MAP.name
    assert ref["sha256"] == hashlib.sha256(MAP.read_bytes()).hexdigest()


# ---------------------------------------------------------------- rule 2: the places


def test_the_staging_world_puts_the_twelve_places_in_scope() -> None:
    staged = {str(e["key"]): e for e in _yaml(STAGING)["entities"]}
    assert sorted(staged) == sorted(SITES)
    world = _world_places()
    for key in SITES:
        assert staged[key]["at"] == world[key]["at"], key


@pytest.mark.parametrize("site", SITES)
def test_each_place_lies_in_exactly_one_territory(site: str) -> None:
    assert _home(site) in _territory_keys()


@pytest.mark.parametrize("site", SITES)
def test_each_place_is_a_site_of_the_territory_it_lies_in(site: str) -> None:
    holders = [
        str(t["key"]) for t in _yaml(STAGING)["territories"] if site in (t.get("sites") or [])
    ]
    assert holders == [_home(site)]


# ---------------------------------------------------------------- rule 6: the scoped check


def test_the_scoped_check_passes_on_the_staging_world() -> None:
    report = mc.check_region(STAGING)
    assert [str(p) for p in report.problems] == []
    assert not set(SITES) & set(report.out_of_scope)


def test_the_scoped_check_fails_when_a_places_territory_leaves_the_region(tmp_path: Path) -> None:
    raw = _raw()
    gone = _home("kalinin")
    cut = copy.deepcopy(raw)
    cut["backdrop"] = cut["backdrop"] + cut["areas"].pop(gone)["rings"]
    data = json.dumps(cut).encode()
    (tmp_path / "pilot.json").write_bytes(data)
    staging = _yaml(STAGING)
    staging["map"]["file"] = "pilot.json"
    staging["map"]["sha256"] = hashlib.sha256(data).hexdigest()
    staging["places_of"] = str(WORLD)
    staging["territories"] = [t for t in staging["territories"] if t["key"] != gone]
    staging["adjacency"] = [
        e
        for e in staging["adjacency"]
        if gone not in ((e["a"], e["b"]) if isinstance(e, dict) else tuple(e))
    ]
    path = tmp_path / "pilot.world.yaml"
    path.write_text(yaml.safe_dump(staging, sort_keys=False))
    report = mc.check_region(path)
    assert ("place", "kalinin") in [(p.code, p.face) for p in report.problems]


# ---------------------------------------------------------------- rule 7: the Moscow road


def test_smolensk_and_vyazma_lie_in_the_same_or_adjacent_territories() -> None:
    assert _same_or_adjacent("smolensk", "vyazma")


def test_vyazma_and_mozhaisk_lie_in_the_same_or_adjacent_territories() -> None:
    assert _same_or_adjacent("vyazma", "mozhaisk")


# ---------------------------------------------------------------- rule 3: each cut's two sides

# Probe points for the cuts, a town on each side of each line as the recipe draws it: (latitude,
# longitude) to two decimals, for this test only. They pin which side the recipe gives to which
# territory, so a cut whose sides are swapped fails here.
CUT_SIDES = (
    ("Kretinga", 55.89, 21.24, "baltic_states"),
    ("Silute", 55.35, 21.48, "east_prussia"),
    ("Taurage", 55.25, 22.29, "baltic_states"),
    ("Pagegiai", 55.14, 21.91, "east_prussia"),
    ("Suwalki", 54.10, 22.93, "east_prussia"),
    ("Augustow", 53.84, 22.98, "belorussia"),
    ("Rzeszow", 50.04, 22.00, "occupied_poland"),
    ("Lubaczow", 50.16, 23.12, "western_ukraine"),
    ("Ustrzyki Dolne", 49.43, 22.59, "western_ukraine"),
    ("Nikel", 69.41, 30.22, "finland"),
    ("Murmansk", 68.97, 33.08, "the_north"),
)


@pytest.mark.parametrize(("town", "lat", "lon", "key"), CUT_SIDES)
def test_each_cut_gives_each_side_to_the_territory_it_names(
    town: str, lat: float, lon: float, key: str
) -> None:
    inside, border = mc.locate(_raw(), lon, lat)
    assert not border, town
    assert inside == [key], town


# ---------------------------------------------------------------- rules 3 to 5: sources and gaps


def test_every_cut_has_a_source_or_is_a_gap() -> None:
    cuts = _yaml(RECIPE).get("cuts") or []
    assert cuts
    for c in cuts:
        assert bool(c.get("source")) != bool(c.get("gap")), c["name"]


def test_every_territory_has_a_terrain_with_a_source_or_a_gap() -> None:
    for t in _yaml(RECIPE)["territories"]:
        assert t.get("terrain"), t["key"]
        assert bool(t.get("terrain_source")) != bool(t.get("terrain_gap")), t["key"]
