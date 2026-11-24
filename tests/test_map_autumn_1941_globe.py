"""The whole-globe 1941 map: the Americas and Africa regions, read from the committed files only.

Pins that the Americas recipe claims its thirteen territories and the Africa recipe its twenty-two
whole and leave the earlier regions' keys alone, that each region's sites lie in the territory that
names them, that the cut lines of the earlier regions still give each side to the territory they
name, that the map passes the scoped check against the newest staging world (which extends the
earlier ones), that the Gondar cut gives each side to the territory it names, and that the start
and yields files give each new territory a holder and a row. It reads the committed map, its
recipes, staging worlds and objects; it needs neither the geometry tool nor the border data, so it
runs in CI.
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
AFRICA = SRC / "africa.yaml"
AFRICA_STAGING = SRC / "africa.world.yaml"
AFRICA_PLACES = SRC / "africa.places.yaml"
# The newest region's staging world: the scoped check runs on it, and it extends the earlier ones.
NEWEST = AFRICA_STAGING
PACIFIC_STAGING = SRC / "pacific.world.yaml"
PACIFIC_PLACES = SRC / "pacific.places.yaml"
START = SRC / "start.yaml"
YIELDS = SRC / "yields.yaml"
EARLIER = tuple(
    SRC / f"{name}.yaml"
    for name in ("eastern-front", "europe", "atlantic", "mediterranean", "pacific")
)
RECIPES = (*EARLIER, AMERICAS, AFRICA)
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

# The regions draft's twenty-two Africa and Arabia territories, in the recipe's order.
AFRICA_TERRITORIES = (
    "french_west_africa",
    "british_west_africa",
    "french_equatorial_africa",
    "belgian_congo",
    "sudan",
    "ethiopia",
    "gondar",
    "horn_of_africa",
    "french_somaliland",
    "british_east_africa",
    "angola",
    "mozambique",
    "rhodesias",
    "south_africa",
    "madagascar",
    "arabia",
    "aden_gulf",
    "spanish_sahara",
    "liberia",
    "portuguese_guinea",
    "spanish_guinea",
    "azores_madeira",
)

# Each present-day country Africa takes whole, by the code prefix of its units, and how many units
# the data gives it; Ethiopia, Yemen, France, Spain and Portugal only in part.
AFRICA_WHOLE_COUNTRIES = {
    "SEN": 14, "MRT": 13, "MLI": 9, "GIN": 34, "CIV": 19, "BFA": 45, "NER": 8, "BEN": 12, "TGO": 5,
    "NGA": 37, "GHA": 10, "SLE": 4, "GMB": 6, "TCD": 22, "CAF": 17, "COG": 12, "GAB": 9, "CMR": 10,
    "COD": 11, "RWA": 5, "BDI": 17, "SDN": 17, "SDS": 10, "ERI": 6, "SOM": 13, "SOL": 1, "DJI": 6,
    "KEN": 8, "UGA": 112, "TZA": 30, "SYC": 26, "MUS": 16, "AGO": 18, "STP": 2, "MOZ": 11,
    "ZWE": 10, "ZMB": 10, "MWI": 28, "ZAF": 9, "NAM": 13, "BWA": 15, "LSO": 10, "SWZ": 4, "MDG": 22,
    "COM": 3, "SAU": 13, "OMN": 11, "ARE": 9, "QAT": 7, "BHR": 5, "KWT": 6, "SAH": 1,
    "LBR": 15, "GNB": 9, "CPV": 22, "GNQ": 7,
}  # fmt: skip
YEMEN_NORTH = {
    "YEM-150", "YEM-151", "YEM-152", "YEM-153", "YEM-154", "YEM-155", "YEM-156", "YEM-158",
    "YEM-333", "YEM-335", "YEM-337", "YEM-3496", "YEM-3498", "YEM-3499",
}  # fmt: skip
YEMEN_SOUTH = {"YEM-332", "YEM-334", "YEM-336", "YEM-157", "YEM-3497", "YEM-3510", "YEM-3511"}
AFRICA_PART_UNITS = {
    "ethiopia": {f"ETH-{n}" for n in (3110, 3111, 3129, 3130, 3131, 3132, 3133, 3134, 3135, 3136)},
    "arabia": YEMEN_NORTH,
    "aden_gulf": YEMEN_SOUTH,
    "madagascar": {"FRA-4601", "FRA-4602"},
    "spanish_sahara": {"ESP-5842", "ESP-5829"},
    "azores_madeira": {"PRT-735", "PRT-736"},
}
# Ethiopia's Amhara unit, which the Gondar cut divides.
AMHARA = "ETH-3109"

# The region's sites: (lat, lon) as the places file gives them, and the territory each lies in.
AFRICA_SITES = {
    "dakar": ((14.69, -17.44), "french_west_africa"),
    "bamako": ((12.64, -8.0), "french_west_africa"),
    "freetown": ((8.48, -13.23), "british_west_africa"),
    "lagos": ((6.44, 3.37), "british_west_africa"),
    "takoradi": ((4.89, -1.75), "british_west_africa"),
    "brazzaville": ((-4.27, 15.28), "french_equatorial_africa"),
    "fort_lamy": ((12.11, 15.04), "french_equatorial_africa"),
    "leopoldville": ((-4.32, 15.31), "belgian_congo"),
    "elisabethville": ((-11.66, 27.48), "belgian_congo"),
    "khartoum": ((15.59, 32.53), "sudan"),
    "port_sudan": ((19.62, 37.22), "sudan"),
    "addis_ababa": ((9.03, 38.74), "ethiopia"),
    "dessie": ((11.13, 39.63), "ethiopia"),
    "gondar_town": ((12.61, 37.47), "gondar"),
    "massawa": ((15.63, 39.42), "horn_of_africa"),
    "mogadishu": ((2.05, 45.32), "horn_of_africa"),
    "berbera": ((10.44, 45.01), "horn_of_africa"),
    "djibouti": ((11.55, 43.12), "french_somaliland"),
    "mombasa": ((-4.0, 39.69), "british_east_africa"),
    "dar_es_salaam": ((-6.79, 39.21), "british_east_africa"),
    "luanda": ((-8.84, 13.23), "angola"),
    "lobito": ((-12.35, 13.55), "angola"),
    "lourenco_marques": ((-25.95, 32.54), "mozambique"),
    "beira": ((-19.82, 34.87), "mozambique"),
    "salisbury": ((-17.83, 31.05), "rhodesias"),
    "broken_hill": ((-14.45, 28.45), "rhodesias"),
    "cape_town": ((-33.92, 18.42), "south_africa"),
    "durban": ((-29.86, 31.02), "south_africa"),
    "diego_suarez": ((-12.28, 49.29), "madagascar"),
    "tananarive": ((-18.91, 47.54), "madagascar"),
    "riyadh": ((24.71, 46.68), "arabia"),
    "jeddah": ((21.49, 39.19), "arabia"),
    "dhahran": ((26.29, 50.11), "arabia"),
    "aden": ((12.85, 45.03), "aden_gulf"),
    "manama": ((26.23, 50.59), "aden_gulf"),
    "kuwait_town": ((29.37, 47.98), "aden_gulf"),
    "las_palmas": ((28.12, -15.43), "spanish_sahara"),
    "monrovia": ((6.31, -10.76), "liberia"),
    "bissau": ((11.86, -15.6), "portuguese_guinea"),
    "mindelo": ((16.89, -24.98), "portuguese_guinea"),
    "santa_isabel": ((3.75, 8.78), "spanish_guinea"),
    "ponta_delgada": ((37.74, -25.67), "azores_madeira"),
    "lajes": ((38.76, -27.09), "azores_madeira"),
}

# The Gondar cut, read on the map: the pocket's towns and the towns beyond it.
GONDAR_SIDES = (
    ("Gondar", 12.61, 37.47, "gondar"),
    ("Wolchefit", 13.13, 37.83, "gondar"),
    ("Kulkaber", 12.37, 37.73, "gondar"),
    ("Bahir Dar", 11.59, 37.39, "ethiopia"),
    ("Debre Tabor", 11.85, 38.02, "ethiopia"),
    ("Metemma", 12.95, 36.15, "ethiopia"),
)

# The new holders with no seat that start.yaml adds for the region.
AFRICA_POLITIES = (
    "free_france",
    "belgium",
    "ethiopia_state",
    "saudi_arabia",
    "liberia_state",
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


def test_the_map_is_the_seven_regions_areas_and_no_others() -> None:
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


def test_no_province_is_claimed_twice_across_the_seven_recipes() -> None:
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


def test_the_scoped_check_passes_on_the_newest_staging_world_with_the_americas_in_scope() -> None:
    report = mc.check_region(NEWEST)
    assert [str(p) for p in report.problems] == []
    assert not set(AMERICAS_SITES) & set(report.out_of_scope)


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


# ---------------------------------------------------------------- Africa and Arabia


def test_the_africa_region_has_its_territories() -> None:
    staged = _yaml(AFRICA_STAGING)
    assert [t["key"] for t in staged["territories"]] == list(AFRICA_TERRITORIES)
    assert {t["region"] for t in staged["territories"]} == {"africa"}
    assert not staged.get("sea_zones")
    assert set(AFRICA_TERRITORIES) <= set(_raw()["areas"])
    for t in _yaml(AFRICA)["territories"]:
        assert t["key"] == "gondar" or t.get("provinces"), t["key"]
        assert t.get("terrain"), t["key"]
        assert bool(t.get("terrain_source")) != bool(t.get("terrain_gap")), t["key"]


@pytest.mark.parametrize("country", sorted(AFRICA_WHOLE_COUNTRIES))
def test_africa_takes_each_country_whole(country: str) -> None:
    claimed = [c for c in _claims(AFRICA) if c.startswith(country)]
    assert len(claimed) == AFRICA_WHOLE_COUNTRIES[country], country


@pytest.mark.parametrize("territory", sorted(AFRICA_PART_UNITS))
def test_africa_takes_the_units_of_a_shared_country(territory: str) -> None:
    rows = {str(t["key"]): t for t in _yaml(AFRICA)["territories"]}
    assert AFRICA_PART_UNITS[territory] <= {str(c) for c in rows[territory]["provinces"]}


def test_yemen_is_split_between_arabia_and_aden_and_nothing_else_claims_it() -> None:
    yemen = {c for c in _claims(AFRICA) if c.startswith("YEM")}
    assert yemen == YEMEN_NORTH | YEMEN_SOUTH
    assert not YEMEN_NORTH & YEMEN_SOUTH


def test_the_gondar_cut_is_the_regions_one_cut_and_is_marked_a_gap() -> None:
    cuts = _yaml(AFRICA)["cuts"]
    assert [(c["province"], c["left"], c["right"]) for c in cuts] == [
        (AMHARA, "gondar", "ethiopia")
    ]
    assert cuts[0]["gap"] is True
    assert str(cuts[0].get("named_source") or "").strip()
    assert AMHARA not in _claims(AFRICA)


@pytest.mark.parametrize(("town", "lat", "lon", "key"), GONDAR_SIDES)
def test_the_gondar_cut_gives_each_side_to_the_territory_it_names(
    town: str, lat: float, lon: float, key: str
) -> None:
    inside, border = mc.locate(_raw(), lon, lat)
    assert not border, town
    assert inside == [key], town


def test_the_africa_staging_world_lists_the_sites_of_each_territory() -> None:
    sites = {
        str(s): str(t["key"])
        for t in _yaml(AFRICA_STAGING)["territories"]
        for s in t.get("sites") or []
    }
    assert sites == {k: home for k, (_, home) in AFRICA_SITES.items()}


@pytest.mark.parametrize("site", sorted(AFRICA_SITES))
def test_each_africa_site_lies_in_its_territory(site: str) -> None:
    (lat, lon), home = AFRICA_SITES[site]
    inside, border = mc.locate(_raw(), float(lon), float(lat))
    assert not border, site
    assert inside == [home], site


def test_the_africa_places_file_extends_the_americas_one() -> None:
    assert _yaml(AFRICA_STAGING)["places_of"] == AFRICA_PLACES.name
    here = _yaml(AFRICA_PLACES)["entities"]
    earlier = _yaml(AMERICAS_PLACES)["entities"]
    assert here[: len(earlier)] == earlier
    new = {str(e["key"]): e for e in here[len(earlier) :]}
    assert {k: tuple(e["at"]) for k, e in new.items()} == {
        k: at for k, (at, _) in AFRICA_SITES.items()
    }


def test_the_africa_staging_world_extends_the_americas() -> None:
    parent = (AFRICA_STAGING.parent / _yaml(AFRICA_STAGING)["extends"]).resolve()
    assert parent == AMERICAS_STAGING.resolve()


def test_the_africa_staging_blocks_are_the_built_fragments() -> None:
    fragment, staged = _yaml(FRAGMENT), _yaml(AFRICA_STAGING)
    assert staged["territories"] == [a for a in fragment["territories"] if a["region"] == "africa"]
    own = {str(a["key"]) for a in staged["territories"]}

    def pair(e: Any) -> tuple[str, str]:
        return (e["a"], e["b"]) if isinstance(e, dict) else (e[0], e[1])

    assert staged["adjacency"] == [e for e in fragment["adjacency"] if own & set(pair(e))]


def test_the_africa_staging_world_is_the_newest() -> None:
    assert NEWEST == AFRICA_STAGING
    report = mc.check_region(AFRICA_STAGING)
    assert [str(p) for p in report.problems] == []
    assert not set(AFRICA_SITES) & set(report.out_of_scope)


def test_each_africa_territory_has_a_holder_with_a_gap_or_a_source() -> None:
    start = _yaml(START)
    holders = {str(h["territory"]): h for h in start["holders"]}
    keys = {str(e["key"]): e for e in start["entities"]}
    seats = {"usa", "uk", "germany", "ussr", "japan", "italy", "china"}
    for t in AFRICA_TERRITORIES:
        h = holders[t]
        assert h.get("gap") is True or h.get("source"), t
        assert h["holder"] in seats or keys[h["holder"]]["kind"] == "polity", t


def test_the_africa_holders_are_polities() -> None:
    keys = {str(e["key"]): e for e in _yaml(START)["entities"]}
    for p in AFRICA_POLITIES:
        assert keys[p]["kind"] == "polity", p
    assert not set(AFRICA_POLITIES) & set(AFRICA_TERRITORIES)


def test_each_africa_site_is_a_place_of_the_start_within_its_territory() -> None:
    keys = {str(e["key"]): e for e in _yaml(START)["entities"]}
    for site, (at, home) in AFRICA_SITES.items():
        e = keys[site]
        assert e["kind"] == "location", site
        assert tuple(e["at"]) == at, site
        assert e["within"] == home, site


def test_each_africa_territory_has_a_yields_row() -> None:
    doc = _yaml(YIELDS)
    rows = {str(r["key"]): r for r in doc["territories"]}
    sources = {str(s["key"]) for s in doc["sources"]}
    resources = [str(r["key"]) for r in _yaml(START)["resources"]]
    for t in AFRICA_TERRITORIES:
        row = rows[t]
        assert set(row) == {"key", *resources}, t
        for r in resources:
            entry = row[r]
            assert entry.get("gap") is True, (t, r)
            assert entry["named_source"] in sources, (t, r)
            assert str(entry.get("basis") or "").strip(), (t, r)
        assert row["supply"]["amount"] == len(row["supply"].get("hubs") or []), t
