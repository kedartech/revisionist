"""The 1941 map: the Eastern Front pilot region and Europe, read from the committed files only.

Pins that every place the world has in a built region lies in exactly one territory of the built
map, that Smolensk, Vyazma and Mozhaisk lie in the same or adjacent territories, that each cut line
gives each side to the territory it names, and that the map passes the scoped check against the
newest region's staging world, which extends the earlier ones. It reads the committed map, its
recipes and staging worlds and today's world file; it needs neither the geometry tool nor the
border data, so it runs in CI.
"""

import copy
import hashlib
import importlib.util
import itertools
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
EUROPE = SRC / "europe.yaml"
EUROPE_STAGING = SRC / "europe.world.yaml"
ATLANTIC = SRC / "atlantic.yaml"
ATLANTIC_STAGING = SRC / "atlantic.world.yaml"
RECIPES = (RECIPE, EUROPE, ATLANTIC)
# The regions whose recipes carry cut lines (the Atlantic's carries none, MAA rule 1).
CUT_RECIPES = (RECIPE, EUROPE)
# The newest region's staging world: the scoped check runs on it, and it extends the earlier ones.
NEWEST = ATLANTIC_STAGING
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

# MAE rule 2: the places today's world has in Europe that lie on land. Lorient is not among them:
# the world puts it at 47.7 N, 3.4 W, in the roadstead off the Morbihan shore, so it lies in the Bay
# of Biscay sea zone (pinned below) and is no territory's site.
EUROPE_SITES = ("berlin", "rome")


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


def _staged_territories() -> list[Any]:
    return [
        t
        for path in (STAGING, EUROPE_STAGING, ATLANTIC_STAGING)
        for t in _yaml(path)["territories"]
    ]


def _territory_keys() -> set[str]:
    return {str(t["key"]) for t in _staged_territories()}


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


@pytest.mark.parametrize(
    "staging", [STAGING, EUROPE_STAGING, ATLANTIC_STAGING], ids=lambda p: p.stem
)
def test_the_staging_world_names_the_committed_map(staging: Path) -> None:
    ref = _yaml(staging)["map"]
    assert ref["sha256"] == hashlib.sha256(MAP.read_bytes()).hexdigest()
    assert mc.map_path(staging, ref["file"]) == MAP.resolve()


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


def test_the_europe_staging_world_puts_its_three_places_in_scope() -> None:
    staged = {str(e["key"]): e for e in _yaml(EUROPE_STAGING)["entities"]}
    assert sorted(staged) == sorted([*EUROPE_SITES, "lorient"])
    world = _world_places()
    for key in staged:
        assert staged[key]["at"] == world[key]["at"], key


@pytest.mark.parametrize("site", SITES + EUROPE_SITES)
def test_each_place_lies_in_exactly_one_territory(site: str) -> None:
    assert _home(site) in _territory_keys()


def test_lorient_lies_in_the_bay_of_biscay_off_occupied_france() -> None:
    assert _home("lorient") == "bay_of_biscay"
    assert mc.adjacent(_raw(), "bay_of_biscay", "occupied_france")


@pytest.mark.parametrize("site", SITES + EUROPE_SITES)
def test_each_place_is_a_site_of_the_territory_it_lies_in(site: str) -> None:
    holders = [str(t["key"]) for t in _staged_territories() if site in (t.get("sites") or [])]
    assert holders == [_home(site)]


# ---------------------------------------------------------------- rule 6: the scoped check


def test_the_scoped_check_passes_on_the_newest_staging_world() -> None:
    report = mc.check_region(NEWEST)
    assert [str(p) for p in report.problems] == []
    assert not (set(SITES) | set(EUROPE_SITES)) & set(report.out_of_scope)


def test_the_europe_staging_world_extends_the_pilots() -> None:
    assert (EUROPE_STAGING.parent / _yaml(EUROPE_STAGING)["extends"]).resolve() == STAGING.resolve()


def test_the_scoped_check_fails_when_a_places_territory_leaves_the_region(tmp_path: Path) -> None:
    raw = _raw()
    gone = _home("kalinin")
    cut = copy.deepcopy(raw)
    cut["backdrop"] = cut["backdrop"] + cut["areas"].pop(gone)["rings"]
    data = json.dumps(cut).encode()
    (tmp_path / "pilot.json").write_bytes(data)
    ref = {"file": "pilot.json", "sha256": hashlib.sha256(data).hexdigest()}
    pilot = _yaml(STAGING)
    pilot["map"].update(ref)
    pilot["places_of"] = str(WORLD)
    pilot["territories"] = [t for t in pilot["territories"] if t["key"] != gone]
    pilot["adjacency"] = [
        e
        for e in pilot["adjacency"]
        if gone not in ((e["a"], e["b"]) if isinstance(e, dict) else tuple(e))
    ]
    (tmp_path / STAGING.name).write_text(yaml.safe_dump(pilot, sort_keys=False))
    for staging in (EUROPE_STAGING, ATLANTIC_STAGING):
        doc = _yaml(staging)
        doc["map"].update(ref)
        doc["places_of"] = str(WORLD)
        (tmp_path / staging.name).write_text(yaml.safe_dump(doc, sort_keys=False))
    path = tmp_path / NEWEST.name
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
    # MAE: the demarcation line of 1940, in the departments it divides.
    ("Bordeaux", 44.84, -0.58, "occupied_france"),
    ("Sainte-Foy-la-Grande", 44.84, 0.22, "vichy_france"),
    ("Mont-de-Marsan", 43.89, -0.50, "occupied_france"),
    ("Pau", 43.30, -0.37, "vichy_france"),
    ("Angouleme", 45.65, 0.16, "occupied_france"),
    ("Poitiers", 46.58, 0.34, "occupied_france"),
    ("Montmorillon", 46.43, 0.87, "vichy_france"),
    ("Tours", 47.39, 0.69, "occupied_france"),
    ("Loches", 47.13, 1.00, "vichy_france"),
    ("Romorantin", 47.36, 1.74, "occupied_france"),
    ("Bourges", 47.08, 2.40, "vichy_france"),
    ("Autun", 46.95, 4.30, "occupied_france"),
    ("Macon", 46.31, 4.83, "vichy_france"),
    ("Dole", 47.09, 5.49, "occupied_france"),
    ("Lons-le-Saunier", 46.67, 5.55, "vichy_france"),
    ("Gex", 46.33, 6.06, "occupied_france"),
    ("Nantua", 46.15, 5.61, "vichy_france"),
    # MAE: the Reich's eastern border of 1939, in the voivodeships it divides.
    ("Katowice", 50.26, 19.02, "germany_east"),
    ("Czestochowa", 50.81, 19.12, "occupied_poland"),
    ("Oswiecim", 50.04, 19.22, "germany_east"),
    ("Krakow", 50.06, 19.94, "occupied_poland"),
    ("Lodz", 51.76, 19.46, "germany_east"),
    ("Piotrkow", 51.41, 19.70, "occupied_poland"),
    ("Plock", 52.55, 19.70, "east_prussia"),
    ("Ciechanow", 52.88, 20.62, "east_prussia"),
    ("Warsaw", 52.23, 21.01, "occupied_poland"),
    # MAE: the Vienna Award line of 1940, in the counties it divides.
    ("Oradea", 47.07, 21.93, "hungary_slovakia"),
    ("Beius", 46.67, 22.35, "romania"),
    ("Cluj", 46.77, 23.60, "hungary_slovakia"),
    ("Turda", 46.57, 23.78, "romania"),
    ("Targu Mures", 46.54, 24.56, "hungary_slovakia"),
    ("Ludus", 46.48, 24.10, "romania"),
    # MAE: Alsace-Lorraine follows department lines, so no cut: the annexed departments and their
    # French neighbours.
    ("Strasbourg", 48.58, 7.75, "germany_west"),
    ("Metz", 49.12, 6.18, "germany_west"),
    ("Mulhouse", 47.75, 7.34, "germany_west"),
    ("Nancy", 48.69, 6.18, "occupied_france"),
    ("Belfort", 47.64, 6.86, "occupied_france"),
)


@pytest.mark.parametrize(("town", "lat", "lon", "key"), CUT_SIDES)
def test_each_cut_gives_each_side_to_the_territory_it_names(
    town: str, lat: float, lon: float, key: str
) -> None:
    inside, border = mc.locate(_raw(), lon, lat)
    assert not border, town
    assert inside == [key], town


# ---------------------------------------------------------------- rules 3 to 5: sources and gaps


@pytest.mark.parametrize("recipe", CUT_RECIPES, ids=lambda p: p.stem)
def test_every_cut_has_a_source_or_is_a_gap(recipe: Path) -> None:
    cuts = _yaml(recipe).get("cuts") or []
    assert cuts
    for c in cuts:
        assert bool(c.get("source")) != bool(c.get("gap")), c["name"]
        assert c.get("source") or c.get("named_source"), c["name"]


@pytest.mark.parametrize("recipe", RECIPES, ids=lambda p: p.stem)
def test_every_territory_has_a_terrain_with_a_source_or_a_gap(recipe: Path) -> None:
    for t in _yaml(recipe)["territories"]:
        assert t.get("terrain"), t["key"]
        assert bool(t.get("terrain_source")) != bool(t.get("terrain_gap")), t["key"]


# ---------------------------------------------------------------- MAE: Europe


def _claims(recipe: Path) -> set[str]:
    """Every province code a recipe file names, in a territory or a cut."""
    doc = _yaml(recipe)
    return {str(c) for t in doc["territories"] for c in t.get("provinces") or []} | {
        str(c["province"]) for c in doc.get("cuts") or []
    }


def test_no_province_is_claimed_by_two_recipe_files() -> None:
    assert _claims(RECIPE)
    assert _claims(EUROPE)
    assert _claims(RECIPE) & _claims(EUROPE) == set()


# Rule 1: the Europe region's territories and sea zones, by key. [proposed]
EUROPE_TERRITORIES = (
    "germany_east",
    "germany_west",
    "germany_south",
    "east_prussia",
    "occupied_poland",
    "denmark",
    "low_countries",
    "occupied_france",
    "vichy_france",
    "norway",
    "sweden",
    "finland",
    "hungary_slovakia",
    "romania",
    "balkans",
    "italy_north",
    "italy_south",
    "iberia",
    "switzerland",
)
EUROPE_SEA_ZONES = ("north_sea", "danish_straits", "gulf_of_bothnia", "bay_of_biscay")


def test_the_europe_region_has_its_territories_and_sea_zones() -> None:
    staged = _yaml(EUROPE_STAGING)
    assert [t["key"] for t in staged["territories"]] == list(EUROPE_TERRITORIES)
    assert [z["key"] for z in staged["sea_zones"]] == list(EUROPE_SEA_ZONES)
    assert {t["region"] for t in staged["territories"] + staged["sea_zones"]} == {"europe"}
    for t in _yaml(EUROPE)["territories"]:
        assert t.get("provinces"), t["key"]
    assert set(EUROPE_TERRITORIES + EUROPE_SEA_ZONES) <= set(_raw()["areas"])


# Rule 1: a town of each place the item names, in the territory that holds it.
EUROPE_TOWNS = (
    ("Berlin", 52.52, 13.40, "germany_east"),
    ("Hamburg", 53.55, 9.99, "germany_west"),
    ("Munich", 48.14, 11.58, "germany_south"),
    ("Vienna", 48.21, 16.37, "germany_south"),
    ("Prague", 50.08, 14.44, "germany_south"),
    ("Konigsberg", 54.71, 20.51, "east_prussia"),
    ("Roskilde", 55.64, 12.08, "denmark"),
    ("Aarhus", 56.16, 10.20, "denmark"),
    ("Amsterdam", 52.37, 4.90, "low_countries"),
    ("Brussels", 50.85, 4.35, "low_countries"),
    ("Paris", 48.86, 2.35, "occupied_france"),
    ("Vichy", 46.13, 3.43, "vichy_france"),
    ("Oslo", 59.91, 10.75, "norway"),
    ("Stockholm", 59.33, 18.07, "sweden"),
    ("Helsinki", 60.17, 24.94, "finland"),
    ("Budapest", 47.50, 19.04, "hungary_slovakia"),
    ("Bratislava", 48.15, 17.11, "hungary_slovakia"),
    ("Bucharest", 44.43, 26.10, "romania"),
    ("Ploiesti", 44.94, 26.02, "romania"),
    ("Belgrade", 44.82, 20.46, "balkans"),
    ("Sofia", 42.70, 23.32, "balkans"),
    ("Milan", 45.46, 9.19, "italy_north"),
    ("Naples", 40.85, 14.27, "italy_south"),
    ("Madrid", 40.42, -3.70, "iberia"),
    ("Lisbon", 38.72, -9.14, "iberia"),
    ("Bern", 46.95, 7.45, "switzerland"),
)


@pytest.mark.parametrize(("town", "lat", "lon", "key"), EUROPE_TOWNS)
def test_each_town_lies_in_its_territory(town: str, lat: float, lon: float, key: str) -> None:
    inside, border = mc.locate(_raw(), lon, lat)
    assert not border, town
    assert inside == [key], town


def test_berlin_and_rome_are_sites_of_one_territory_each() -> None:
    staged = {str(t["key"]): t.get("sites") or [] for t in _yaml(EUROPE_STAGING)["territories"]}
    for site, key in (("berlin", "germany_east"), ("rome", "italy_south")):
        assert [k for k, sites in staged.items() if site in sites] == [key]
    assert not [k for k, sites in staged.items() if "lorient" in sites]


# Rule 2: the sea zones join the pilot's; the North Sea and the Bay of Biscay reach the open water
# that the Atlantic region's zones (MAA) now fill: a point just west of each lies in one of them.
def test_the_europe_sea_zones_join_the_pilots() -> None:
    raw = _raw()
    assert mc.adjacent(raw, "danish_straits", "baltic_sea")
    assert mc.adjacent(raw, "gulf_of_bothnia", "baltic_sea")
    assert mc.adjacent(raw, "danish_straits", "north_sea")


@pytest.mark.parametrize(
    ("zone", "lat", "inside_lon", "west_lon", "next_zone"),
    [
        ("bay_of_biscay", 46.0, -9.9, -10.5, "mid_ocean_gap"),
        ("north_sea", 60.0, -1.5, -4.5, "western_approaches"),
    ],
)
def test_the_western_sea_zones_reach_the_open_atlantic(
    zone: str, lat: float, inside_lon: float, west_lon: float, next_zone: str
) -> None:
    raw = _raw()
    assert mc.locate(raw, inside_lon, lat) == ([zone], [])
    assert mc.locate(raw, west_lon, lat) == ([next_zone], [])
    assert mc.adjacent(raw, zone, next_zone)


# Rule 5: the neutrals are territories held by a polity with no seat.
NEUTRALS = {"sweden": ["sweden"], "switzerland": ["switzerland"], "iberia": ["spain", "portugal"]}


def test_the_neutrals_are_territories_held_by_a_polity_with_no_seat() -> None:
    doc = _yaml(EUROPE)
    held = {str(t["key"]): t["neutral"] for t in doc["territories"] if "neutral" in t}
    assert held == NEUTRALS
    world = _yaml(WORLD)
    seated = {str(s.get("polity") or s.get("entity")) for s in world.get("seats") or []}
    sides = {str(side["side"]) for r in world["roster"] for side in r.get("sides") or []}
    for polities in held.values():
        assert not set(polities) & (seated | sides)


# ---------------------------------------------------------------- MAA: the Atlantic

# Rule 1: the Atlantic region's territories and sea zones, by key. [proposed]
ATLANTIC_TERRITORIES = (
    "britain_south",
    "britain_north",
    "ireland",
    "iceland",
    "greenland",
    "newfoundland",
    "eastern_canada",
    "us_east",
    "us_central",
    "us_west",
    "caribbean",
)
ATLANTIC_SEA_ZONES = (
    "english_channel",
    "western_approaches",
    "mid_ocean_gap",
    "western_atlantic",
    "labrador_sea",
    "denmark_strait",
    "arctic_route",
    "caribbean_sea",
)
# Rule 2: the places today's world has in the region, and where each lies. Six are on land and
# sites of their territory; Liverpool, Argentia and Scapa Flow lie in the water of the border data
# (the recipe says so), so each is a place in a sea zone and no territory's site. North Atlantic is
# the world's convoy waypoint.
ATLANTIC_LAND_SITES = {
    "washington": "us_east",
    "norfolk": "us_east",
    "halifax_port": "eastern_canada",
    "sydney_cb": "eastern_canada",
    "reykjavik": "iceland",
    "london": "britain_south",
}
ATLANTIC_WATER_SITES = {
    "liverpool": "western_approaches",
    "argentia": "western_atlantic",
    "scapa_flow": "north_sea",
    "north_atlantic": "mid_ocean_gap",
}
ATLANTIC_PLACES = tuple(ATLANTIC_LAND_SITES) + tuple(ATLANTIC_WATER_SITES)


def _ports() -> dict[str, dict[str, str]]:
    return {str(p["port"]): p for p in _yaml(ATLANTIC_STAGING)["ports"]}


def test_the_atlantic_region_has_its_territories_and_sea_zones() -> None:
    staged = _yaml(ATLANTIC_STAGING)
    assert [t["key"] for t in staged["territories"]] == list(ATLANTIC_TERRITORIES)
    assert [z["key"] for z in staged["sea_zones"]] == list(ATLANTIC_SEA_ZONES)
    assert {t["region"] for t in staged["territories"] + staged["sea_zones"]} == {"atlantic"}
    for t in _yaml(ATLANTIC)["territories"]:
        assert t.get("provinces"), t["key"]
    assert set(ATLANTIC_TERRITORIES + ATLANTIC_SEA_ZONES) <= set(_raw()["areas"])


def test_the_atlantic_staging_world_extends_europe_and_puts_its_places_in_scope() -> None:
    assert (ATLANTIC_STAGING.parent / _yaml(ATLANTIC_STAGING)["extends"]).resolve() == (
        EUROPE_STAGING.resolve()
    )
    staged = {str(e["key"]): e for e in _yaml(ATLANTIC_STAGING)["entities"]}
    assert sorted(staged) == sorted(ATLANTIC_PLACES)
    world = _world_places()
    for key in staged:
        assert staged[key]["at"] == world[key]["at"], key


@pytest.mark.parametrize("site", ATLANTIC_LAND_SITES)
def test_each_land_place_lies_in_exactly_one_territory_and_is_its_site(site: str) -> None:
    key = ATLANTIC_LAND_SITES[site]
    assert _home(site) == key
    holders = [str(t["key"]) for t in _staged_territories() if site in (t.get("sites") or [])]
    assert holders == [key]


@pytest.mark.parametrize("place", ATLANTIC_WATER_SITES)
def test_each_water_place_lies_in_its_sea_zone_and_is_no_territorys_site(place: str) -> None:
    assert _home(place) == ATLANTIC_WATER_SITES[place]
    assert not [t["key"] for t in _staged_territories() if place in (t.get("sites") or [])]


# Rule 2, ports: each port names its sea zone, and the zone borders the territory that holds it.
PORT_ZONES = {
    "norfolk": ("us_east", "western_atlantic"),
    "argentia": ("newfoundland", "western_atlantic"),
    "halifax_port": ("eastern_canada", "western_atlantic"),
    "sydney_cb": ("eastern_canada", "western_atlantic"),
    "reykjavik": ("iceland", "arctic_route"),
    "liverpool": ("britain_south", "western_approaches"),
    "scapa_flow": ("britain_north", "north_sea"),
}


def test_each_port_names_its_sea_zone() -> None:
    ports = _ports()
    assert sorted(ports) == sorted(PORT_ZONES)
    seas = {
        str(z["key"])
        for path in (STAGING, EUROPE_STAGING, ATLANTIC_STAGING)
        for z in _yaml(path)["sea_zones"]
    }
    for port, (territory, zone) in PORT_ZONES.items():
        assert ports[port].get("sea_zone") == zone, port
        assert ports[port].get("territory") == territory, port
        assert zone in seas, port
        assert mc.adjacent(_raw(), territory, zone), port


@pytest.mark.parametrize(
    ("town", "lat", "lon", "key"),
    [
        ("London", 51.51, -0.13, "britain_south"),
        ("Cardiff", 51.48, -3.18, "britain_south"),
        ("Edinburgh", 55.95, -3.19, "britain_north"),
        ("Belfast", 54.60, -5.93, "britain_north"),
        ("Dublin", 53.35, -6.26, "ireland"),
        ("Reykjavik", 64.14, -21.90, "iceland"),
        ("Greenland ice sheet", 70.0, -42.0, "greenland"),
        ("St John's", 47.56, -52.71, "newfoundland"),
        ("Montreal", 45.50, -73.57, "eastern_canada"),
        ("Truro", 45.37, -63.27, "eastern_canada"),
        ("Washington", 38.90, -77.04, "us_east"),
        ("Boston", 42.36, -71.06, "us_east"),
        ("Chicago", 41.88, -87.63, "us_central"),
        ("New Orleans", 29.95, -90.07, "us_central"),
        ("San Francisco", 37.77, -122.42, "us_west"),
        ("Havana", 23.11, -82.37, "caribbean"),
        ("Kingston", 17.99, -76.79, "caribbean"),
    ],
)
def test_each_atlantic_town_lies_in_its_territory(
    town: str, lat: float, lon: float, key: str
) -> None:
    inside, border = mc.locate(_raw(), lon, lat)
    assert not border, town
    assert inside == [key], town


def test_newfoundland_is_a_territory_of_its_own_not_part_of_canada() -> None:
    doc = {str(t["key"]): set(t["provinces"]) for t in _yaml(ATLANTIC)["territories"]}
    assert doc["newfoundland"] == {"CAN-686"}
    assert "CAN-686" not in doc["eastern_canada"]


def test_the_atlantic_region_carries_no_cut_line() -> None:
    assert not (_yaml(ATLANTIC).get("cuts") or [])


def test_the_atlantic_ireland_is_neutral_with_no_seat() -> None:
    held = {str(t["key"]): t["neutral"] for t in _yaml(ATLANTIC)["territories"] if "neutral" in t}
    assert held == {"ireland": ["ireland"]}
    world = _yaml(WORLD)
    seated = {str(s.get("polity") or s.get("entity")) for s in world.get("seats") or []}
    sides = {str(side["side"]) for r in world["roster"] for side in r.get("sides") or []}
    assert not {"ireland"} & (seated | sides)


# Rule 3: the three convoy routes of today's world, traced through adjacent sea zones.
def _sea_keys() -> set[str]:
    return {
        str(z["key"])
        for path in (STAGING, EUROPE_STAGING, ATLANTIC_STAGING)
        for z in _yaml(path)["sea_zones"]
    }


def _waters(place: str) -> set[str]:
    """The sea zones a convoy leg starts or ends in at this place."""
    raw, seas = _raw(), _sea_keys()
    port = _ports().get(place)
    if port:
        return {str(port["sea_zone"])}
    home = _home(place)
    if home in seas:
        return {home}
    return {z for z in seas if mc.adjacent(raw, home, z)}


def _sea_path(a: set[str], b: set[str]) -> bool:
    """Whether the water of `a` reaches the water of `b` through adjacent sea zones only."""
    raw, seas = _raw(), _sea_keys()
    seen, todo = set(a), list(a)
    while todo:
        here = todo.pop()
        if here in b:
            return True
        for z in seas:
            if z not in seen and mc.adjacent(raw, here, z):
                seen.add(z)
                todo.append(z)
    return False


@pytest.mark.parametrize("route", ["hx_route", "sc_route", "arctic_route"])
def test_each_convoy_route_can_be_traced_through_adjacent_sea_zones(route: str) -> None:
    feature = next(f for f in _yaml(WORLD)["features"] if f.get("key") == route)
    places = feature["places"]
    for here, there in itertools.pairwise(places):
        assert _sea_path(_waters(here), _waters(there)), f"{route}: {here} to {there}"


def test_the_atlantic_zones_join_europe_the_arctic_and_the_channel() -> None:
    raw = _raw()
    for a, b in (
        ("arctic_route", "white_sea"),
        ("arctic_route", "north_sea"),
        ("english_channel", "bay_of_biscay"),
        ("mid_ocean_gap", "bay_of_biscay"),
        ("western_approaches", "north_sea"),
        ("western_atlantic", "mid_ocean_gap"),
    ):
        assert mc.adjacent(raw, a, b), (a, b)
    # The Strait of Dover is a declared crossing, not a shared border.
    assert not mc.adjacent(raw, "english_channel", "north_sea")
    crossings = [e for e in _yaml(FRAGMENT)["adjacency"] if isinstance(e, dict)]
    assert {
        "a": "english_channel",
        "b": "north_sea",
        "crossing": "the Strait of Dover",
    } in crossings


def test_the_recipes_agree_on_the_box_and_it_is_the_maps() -> None:
    boxes = {str(_yaml(p).get("map", {}).get("box")) for p in RECIPES if _yaml(p).get("map")}
    assert boxes == {str(_raw()["box"])}


def test_no_province_is_claimed_by_two_of_the_three_recipe_files() -> None:
    a, b, c = _claims(RECIPE), _claims(EUROPE), _claims(ATLANTIC)
    assert c
    assert a & c == set()
    assert b & c == set()
