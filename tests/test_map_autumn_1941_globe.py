"""The whole-globe 1941 map: the Americas region, read from the committed files only.

Pins that the Americas recipe claims its thirteen territories whole and leaves the earlier regions'
keys alone, that each of its sites lies in the territory that names it, that the cut lines of the
earlier regions still give each side to the territory they name, that the map passes the scoped
check against the Americas staging world (which extends the earlier ones), and that the start and
yields files give each new territory a holder and a row. It reads the committed map, its recipes,
staging worlds and objects; it needs neither the geometry tool nor the border data, so it runs in
CI.
"""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "worlds" / "maps"
MAP = MAPS / "autumn-1941-globe.json"
FRAGMENT = MAPS / "autumn-1941-globe.world.yaml"
OBJECTS = MAPS / "objects"
SRC = MAPS / "src" / "autumn-1941-globe"
AMERICAS = SRC / "americas.yaml"
AMERICAS_STAGING = SRC / "americas.world.yaml"
AMERICAS_PLACES = SRC / "americas.places.yaml"
PACIFIC_STAGING = SRC / "pacific.world.yaml"
PACIFIC_PLACES = SRC / "pacific.places.yaml"
START = SRC / "start.yaml"
YIELDS = SRC / "yields.yaml"
EARLIER = tuple(
    SRC / f"{name}.yaml"
    for name in ("eastern-front", "europe", "atlantic", "mediterranean", "pacific")
)
RECIPES = (*EARLIER, AMERICAS)
STAGINGS = tuple(p.with_suffix(".world.yaml") for p in RECIPES)

# The regions draft's thirteen territories, in the recipe's order.
AMERICAS_TERRITORIES = (
    "alaska",
    "western_canada",
    "mexico",
    "central_america",
    "colombia_venezuela",
    "guianas",
    "andes",
    "brazil_north",
    "brazil_south",
    "river_plate",
    "chile",
    "falklands",
    "lesser_antilles",
)

# Each present-day country the region takes whole, by the code prefix of its units, and how many
# units the data gives it; Canada, the United States, France and the Netherlands only in part.
WHOLE_COUNTRIES = {
    "MEX": 33, "GTM": 22, "BLZ": 6, "HND": 18, "SLV": 14, "NIC": 17, "CRI": 7, "PAN": 12,
    "COL": 34, "VEN": 26, "GUY": 10, "SUR": 10, "ECU": 24, "PER": 26, "BOL": 9, "BRA": 27,
    "ARG": 24, "URY": 19, "PRY": 18, "CHL": 16, "FLK": 1, "SGS": 1, "TTO": 16, "BRB": 11,
    "GRD": 7, "VCT": 6, "LCA": 11, "DMA": 10, "ATG": 8, "KNA": 14, "MSR": 3, "AIA": 15,
    "VGB": 1, "VIR": 3, "MAF": 1, "SXM": 1, "BLM": 1, "ABW": 1, "CUW": 1, "CYM": 1, "TCA": 6,
}  # fmt: skip
PART_UNITS = {
    "alaska": {"USA-3563"},
    "western_canada": {f"CAN-{n}" for n in range(630, 637)},
    "guianas": {"FRA-2000"},
    "lesser_antilles": {"FRA-1442", "FRA-4603", "NLD-5147", "NLD-5148", "NLD-5149"},
}

# The region's sites: (lat, lon) as the places file gives them, and the territory each lies in.
AMERICAS_SITES = {
    "dutch_harbor": ((53.87, -166.53), "alaska"),
    "vancouver": ((49.28, -123.12), "western_canada"),
    "winnipeg": ((49.9, -97.14), "western_canada"),
    "mexico_city": ((19.43, -99.13), "mexico"),
    "tampico": ((22.25, -97.86), "mexico"),
    "guatemala_city": ((14.63, -90.51), "central_america"),
    "balboa": ((8.96, -79.56), "central_america"),
    "maracaibo": ((10.65, -71.64), "colombia_venezuela"),
    "bogota": ((4.71, -74.07), "colombia_venezuela"),
    "georgetown": ((6.8, -58.16), "guianas"),
    "paramaribo": ((5.85, -55.2), "guianas"),
    "lima": ((-12.05, -77.04), "andes"),
    "guayaquil": ((-2.19, -79.89), "andes"),
    "natal": ((-5.79, -35.21), "brazil_north"),
    "recife": ((-8.05, -34.88), "brazil_north"),
    "rio_de_janeiro": ((-22.91, -43.2), "brazil_south"),
    "santos": ((-23.96, -46.33), "brazil_south"),
    "buenos_aires": ((-34.62, -58.4), "river_plate"),
    "montevideo": ((-34.9, -56.16), "river_plate"),
    "valparaiso": ((-33.05, -71.62), "chile"),
    "punta_arenas": ((-53.14, -70.94), "chile"),
    "port_stanley": ((-51.69, -57.86), "falklands"),
    "port_of_spain": ((10.65, -61.51), "lesser_antilles"),
    "fort_de_france": ((14.56, -61.03), "lesser_antilles"),
}

# The cut lines of the earlier regions, read on the whole globe: a town each side of each line.
CUT_SIDES = (
    ("Gex", 46.33, 6.06, "occupied_france"),
    ("Nantua", 46.15, 5.61, "vichy_france"),
    ("Katowice", 50.26, 19.02, "germany_east"),
    ("Krakow", 50.06, 19.94, "occupied_poland"),
    ("Oradea", 47.07, 21.93, "hungary_slovakia"),
    ("Beius", 46.67, 22.35, "romania"),
)

# The new holders with no seat that start.yaml adds for the region.
AMERICAS_POLITIES = (
    "mexico_state",
    "guatemala",
    "venezuela",
    "peru",
    "brazil",
    "argentina",
    "chile_state",
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


def _sha() -> str:
    return hashlib.sha256(MAP.read_bytes()).hexdigest()


def _claims(recipe: Path) -> list[str]:
    return [str(c) for t in _yaml(recipe)["territories"] for c in t.get("provinces") or []]


# ---------------------------------------------------------------- the files


def test_the_map_passes_the_check() -> None:
    assert mc.check(_raw()) == []


@pytest.mark.parametrize("staging", STAGINGS, ids=lambda p: p.stem)
def test_each_staging_world_names_the_committed_map(staging: Path) -> None:
    ref = _yaml(staging)["map"]
    assert ref["sha256"] == _sha()
    assert mc.map_path(staging, ref["file"]) == MAP.resolve()


def test_the_built_fragment_names_the_committed_map() -> None:
    ref = _yaml(FRAGMENT)["map"]
    assert ref["file"] == MAP.name
    assert ref["sha256"] == _sha()


def test_the_map_is_kept_as_an_object_and_in_the_manifest() -> None:
    sha = _sha()
    assert (OBJECTS / f"{sha}.json").read_bytes() == MAP.read_bytes()
    assert sha in (OBJECTS / "MANIFEST").read_text().split()


# ---------------------------------------------------------------- the territories


def test_the_americas_region_has_its_territories() -> None:
    staged = _yaml(AMERICAS_STAGING)
    assert [t["key"] for t in staged["territories"]] == list(AMERICAS_TERRITORIES)
    assert {t["region"] for t in staged["territories"]} == {"americas"}
    assert not staged.get("sea_zones")
    assert set(AMERICAS_TERRITORIES) <= set(_raw()["areas"])
    recipe = _yaml(AMERICAS)
    assert recipe["cuts"] == []
    for t in recipe["territories"]:
        assert t.get("provinces"), t["key"]
        assert t.get("terrain"), t["key"]
        assert bool(t.get("terrain_source")) != bool(t.get("terrain_gap")), t["key"]


def test_the_map_is_the_six_regions_areas_and_no_others() -> None:
    keys = {
        str(a["key"])
        for recipe in RECIPES
        for block in ("territories", "sea_zones", "rivers")
        for a in _yaml(recipe).get(block) or []
    }
    assert set(_raw()["areas"]) == keys


@pytest.mark.parametrize("country", sorted(WHOLE_COUNTRIES))
def test_the_americas_take_each_country_whole(country: str) -> None:
    claimed = [c for c in _claims(AMERICAS) if c.startswith(country)]
    assert len(claimed) == WHOLE_COUNTRIES[country], country


@pytest.mark.parametrize("territory", sorted(PART_UNITS))
def test_the_americas_take_the_units_left_of_a_shared_country(territory: str) -> None:
    rows = {str(t["key"]): t for t in _yaml(AMERICAS)["territories"]}
    assert PART_UNITS[territory] <= {str(c) for c in rows[territory]["provinces"]}


def test_no_province_is_claimed_twice_across_the_six_recipes() -> None:
    claims = [c for recipe in RECIPES for c in _claims(recipe)]
    assert len(claims) == len(set(claims))


# ---------------------------------------------------------------- the sites


def test_the_americas_staging_world_lists_the_sites_of_each_territory() -> None:
    sites = {
        str(s): str(t["key"])
        for t in _yaml(AMERICAS_STAGING)["territories"]
        for s in t.get("sites") or []
    }
    assert sites == {k: home for k, (_, home) in AMERICAS_SITES.items()}


@pytest.mark.parametrize("site", sorted(AMERICAS_SITES))
def test_each_americas_site_lies_in_its_territory(site: str) -> None:
    (lat, lon), home = AMERICAS_SITES[site]
    x = lon + 360 if lon < _raw()["box"][0] else lon
    inside, border = mc.locate(_raw(), float(x), float(lat))
    assert not border, site
    assert inside == [home], site


@pytest.mark.parametrize(("town", "lat", "lon", "key"), CUT_SIDES)
def test_each_earlier_cut_gives_each_side_to_the_territory_it_names(
    town: str, lat: float, lon: float, key: str
) -> None:
    inside, border = mc.locate(_raw(), lon, lat)
    assert not border, town
    assert inside == [key], town


def test_the_americas_places_file_extends_the_pacific_one() -> None:
    assert _yaml(AMERICAS_STAGING)["places_of"] == AMERICAS_PLACES.name
    here = _yaml(AMERICAS_PLACES)["entities"]
    earlier = _yaml(PACIFIC_PLACES)["entities"]
    assert here[: len(earlier)] == earlier
    new = {str(e["key"]): e for e in here[len(earlier) :]}
    assert {k: tuple(e["at"]) for k, e in new.items()} == {
        k: at for k, (at, _) in AMERICAS_SITES.items()
    }


def test_the_americas_staging_world_extends_the_pacific() -> None:
    parent = (AMERICAS_STAGING.parent / _yaml(AMERICAS_STAGING)["extends"]).resolve()
    assert parent == PACIFIC_STAGING.resolve()


def test_the_americas_staging_blocks_are_the_built_fragments() -> None:
    fragment, staged = _yaml(FRAGMENT), _yaml(AMERICAS_STAGING)
    assert staged["territories"] == [
        a for a in fragment["territories"] if a["region"] == "americas"
    ]
    own = {str(a["key"]) for a in staged["territories"]}

    def pair(e: Any) -> tuple[str, str]:
        return (e["a"], e["b"]) if isinstance(e, dict) else (e[0], e[1])

    assert staged["adjacency"] == [e for e in fragment["adjacency"] if own & set(pair(e))]


def test_the_scoped_check_passes_on_the_americas_staging_world() -> None:
    report = mc.check_region(AMERICAS_STAGING)
    assert [str(p) for p in report.problems] == []


# ---------------------------------------------------------------- the start and the yields


def test_each_americas_territory_has_a_holder_with_a_gap_or_a_source() -> None:
    start = _yaml(START)
    holders = {str(h["territory"]): h for h in start["holders"]}
    keys = {str(e["key"]): e for e in start["entities"]}
    seats = {"usa", "uk", "germany", "ussr", "japan", "italy", "china"}
    for t in AMERICAS_TERRITORIES:
        h = holders[t]
        assert h.get("gap") is True or h.get("source"), t
        assert h["holder"] in seats or keys[h["holder"]]["kind"] == "polity", t


def test_the_new_holders_are_polities() -> None:
    keys = {str(e["key"]): e for e in _yaml(START)["entities"]}
    for p in AMERICAS_POLITIES:
        assert keys[p]["kind"] == "polity", p
    assert not set(AMERICAS_POLITIES) & set(AMERICAS_TERRITORIES)


def test_each_americas_site_is_a_place_of_the_start_within_its_territory() -> None:
    keys = {str(e["key"]): e for e in _yaml(START)["entities"]}
    for site, (at, home) in AMERICAS_SITES.items():
        e = keys[site]
        assert e["kind"] == "location", site
        assert tuple(e["at"]) == at, site
        assert e["within"] == home, site


def test_each_americas_territory_has_a_yields_row() -> None:
    doc = _yaml(YIELDS)
    rows = {str(r["key"]): r for r in doc["territories"]}
    sources = {str(s["key"]) for s in doc["sources"]}
    resources = [str(r["key"]) for r in _yaml(START)["resources"]]
    for t in AMERICAS_TERRITORIES:
        row = rows[t]
        assert set(row) == {"key", *resources}, t
        for r in resources:
            entry = row[r]
            assert entry.get("gap") is True, (t, r)
            assert entry["named_source"] in sources, (t, r)
            assert str(entry.get("basis") or "").strip(), (t, r)
        assert row["supply"]["amount"] == len(row["supply"].get("hubs") or []), t
