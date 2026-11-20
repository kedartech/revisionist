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
MEDITERRANEAN = SRC / "mediterranean.yaml"
MEDITERRANEAN_STAGING = SRC / "mediterranean.world.yaml"
MEDITERRANEAN_PLACES = SRC / "mediterranean.places.yaml"
PACIFIC = SRC / "pacific.yaml"
PACIFIC_STAGING = SRC / "pacific.world.yaml"
PACIFIC_PLACES = SRC / "pacific.places.yaml"
RECIPES = (RECIPE, EUROPE, ATLANTIC, MEDITERRANEAN, PACIFIC)
# The regions whose recipes carry cut lines (the Atlantic's carries none, MAA rule 1).
CUT_RECIPES = (RECIPE, EUROPE, MEDITERRANEAN, PACIFIC)
STAGINGS = (STAGING, EUROPE_STAGING, ATLANTIC_STAGING, MEDITERRANEAN_STAGING, PACIFIC_STAGING)
# The newest region's staging world: the scoped check runs on it, and it extends the earlier ones.
NEWEST = PACIFIC_STAGING
WORLD = ROOT / "worlds" / "autumn-1941.yaml"
POINTS = ROOT / "tests" / "worlds" / "autumn-1941-points.yaml"
"""The 1941 world before territories: the places the staging files were written against."""

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
    """The places of the world the staging files were written against (before territories)."""
    return {
        str(e["key"]): e
        for e in _yaml(POINTS)["entities"]
        if e.get("kind") == "location" and isinstance(e.get("at"), list)
    }


def _staged_territories() -> list[Any]:
    return [t for path in STAGINGS for t in _yaml(path)["territories"]]


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


@pytest.mark.parametrize("staging", STAGINGS, ids=lambda p: p.stem)
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
    places = {MEDITERRANEAN_STAGING: MEDITERRANEAN_PLACES, PACIFIC_STAGING: PACIFIC_PLACES}
    for staging in STAGINGS[1:]:
        doc = _yaml(staging)
        doc["map"].update(ref)
        doc["places_of"] = str(places.get(staging, WORLD))
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
    "sweden_area",
    "finland",
    "hungary_slovakia",
    "romania",
    "balkans",
    "italy_north",
    "italy_south",
    "iberia",
    "switzerland_area",
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
    ("Stockholm", 59.33, 18.07, "sweden_area"),
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
    ("Bern", 46.95, 7.45, "switzerland_area"),
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
        ("north_sea", 60.0, -1.5, -4.5, "western_approaches_area"),
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
NEUTRALS = {
    "sweden_area": ["sweden"],
    "switzerland_area": ["switzerland"],
    "iberia": ["spain", "portugal"],
}


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
    "western_approaches_area",
    "mid_ocean_gap",
    "western_atlantic",
    "labrador_sea",
    "denmark_strait",
    "arctic_route_area",
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
    "liverpool": "western_approaches_area",
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
    "reykjavik": ("iceland", "arctic_route_area"),
    "liverpool": ("britain_south", "western_approaches_area"),
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
        ("arctic_route_area", "white_sea"),
        ("arctic_route_area", "north_sea"),
        ("english_channel", "bay_of_biscay"),
        ("mid_ocean_gap", "bay_of_biscay"),
        ("western_approaches_area", "north_sea"),
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


# ---------------------------------------------------------------- MAM: the Mediterranean

# Rule 1: the region's territories and sea zones, by key. [proposed] Malta is not a territory of its
# own: the data's 68 units add up to 0.0325 square degrees, under the checker's minimum of 0.05, so
# it is joined to Cyprus (the recipe says so).
MEDITERRANEAN_TERRITORIES = (
    "french_north_africa",
    "tunisia",
    "tripolitania",
    "cyrenaica",
    "tobruk_area",
    "egypt",
    "levant",
    "syria",
    "iraq",
    "iran",
    "turkey",
    "caucasus",
    "greece",
    "dodecanese",
    "british_islands",
)
MEDITERRANEAN_SEA_ZONES = (
    "gibraltar_approaches",
    "western_mediterranean",
    "central_mediterranean",
    "eastern_mediterranean",
    "aegean_sea",
)
# Rule 2: the six new places, the territory each lies in and the sea zone it opens on.
MEDITERRANEAN_PLACE_HOMES = {
    "alexandria": ("egypt", "eastern_mediterranean", (31.20, 29.92)),
    "malta": ("british_islands", "central_mediterranean", (35.90, 14.51)),
    "tobruk": ("tobruk_area", "eastern_mediterranean", (32.08, 23.98)),
    "bardia": ("cyrenaica", "eastern_mediterranean", (31.74, 25.07)),
    "tripoli": ("tripolitania", "central_mediterranean", (32.89, 13.19)),
    "taranto": ("italy_south", "central_mediterranean", (40.47, 17.24)),
}


def _med_places() -> dict[str, Any]:
    return {str(e["key"]): e for e in _yaml(MEDITERRANEAN_STAGING)["entities"]}


def _where(lat: float, lon: float) -> str:
    inside, border = mc.locate(_raw(), lon, lat)
    assert not border, f"({lat}, {lon}) lies on the border of {border}"
    assert len(inside) == 1, f"({lat}, {lon}) lies in {inside}"
    return str(inside[0])


def test_the_mediterranean_region_has_its_territories_and_sea_zones() -> None:
    staged = _yaml(MEDITERRANEAN_STAGING)
    assert [t["key"] for t in staged["territories"]] == list(MEDITERRANEAN_TERRITORIES)
    assert [z["key"] for z in staged["sea_zones"]] == list(MEDITERRANEAN_SEA_ZONES)
    assert {t["region"] for t in staged["territories"] + staged["sea_zones"]} == {"mediterranean"}
    assert set(MEDITERRANEAN_TERRITORIES + MEDITERRANEAN_SEA_ZONES) <= set(_raw()["areas"])
    cut_to = {str(c[key]) for c in _yaml(MEDITERRANEAN)["cuts"] for key in ("left", "right")}
    for t in _yaml(MEDITERRANEAN)["territories"]:
        assert t.get("provinces") or t["key"] in cut_to, t["key"]


def test_the_mediterranean_staging_world_extends_the_atlantic() -> None:
    parent = (MEDITERRANEAN_STAGING.parent / _yaml(MEDITERRANEAN_STAGING)["extends"]).resolve()
    assert parent == ATLANTIC_STAGING.resolve()


def test_the_staging_blocks_are_the_built_fragments() -> None:
    fragment, staged = _yaml(FRAGMENT), _yaml(MEDITERRANEAN_STAGING)
    keep = ("territories", "sea_zones")
    for block in keep:
        assert staged[block] == [a for a in fragment[block] if a["region"] == "mediterranean"]
    own = {str(a["key"]) for block in keep for a in staged[block]}

    def pair(e: Any) -> tuple[str, str]:
        return (e["a"], e["b"]) if isinstance(e, dict) else (e[0], e[1])

    assert staged["adjacency"] == [e for e in fragment["adjacency"] if own & set(pair(e))]


def test_the_staging_world_names_this_regions_places_file() -> None:
    assert _yaml(MEDITERRANEAN_STAGING)["places_of"] == MEDITERRANEAN_PLACES.name
    here = {str(e["key"]): e for e in _yaml(MEDITERRANEAN_PLACES)["entities"]}
    world = _world_places()
    for key, e in here.items():
        if key in world:
            assert e["at"] == world[key]["at"], key
    assert sorted(set(here) - set(world)) == sorted(MEDITERRANEAN_PLACE_HOMES)


def test_the_scoped_check_passes_on_the_mediterranean_staging_world() -> None:
    # The map now holds a newer region, so the Mediterranean's staging world is checked through the
    # newest one, which extends it.
    report = mc.check_region(NEWEST)
    assert [str(p) for p in report.problems] == []
    assert not set(MEDITERRANEAN_PLACE_HOMES) & set(report.out_of_scope)


def test_the_mediterranean_staging_world_puts_six_new_places_in_scope() -> None:
    staged = _med_places()
    assert sorted(staged) == sorted(MEDITERRANEAN_PLACE_HOMES)
    for key, (_, _, at) in MEDITERRANEAN_PLACE_HOMES.items():
        assert staged[key]["at"] == list(at), key
        assert not _world_places().get(key), key


@pytest.mark.parametrize("place", MEDITERRANEAN_PLACE_HOMES)
def test_each_mediterranean_place_lies_in_its_territory_and_is_its_site(place: str) -> None:
    key, _, (lat, lon) = MEDITERRANEAN_PLACE_HOMES[place]
    assert _where(lat, lon) == key
    holders = [str(t["key"]) for t in _staged_territories() if place in (t.get("sites") or [])]
    assert holders == [key]


@pytest.mark.parametrize("port", MEDITERRANEAN_PLACE_HOMES)
def test_each_mediterranean_port_names_its_sea_zone(port: str) -> None:
    key, zone, _ = MEDITERRANEAN_PLACE_HOMES[port]
    entry = next(p for p in _yaml(MEDITERRANEAN_STAGING)["ports"] if p["port"] == port)
    assert (entry["territory"], entry["sea_zone"]) == (key, zone)
    assert mc.adjacent(_raw(), key, zone)


# Rule 1: Tobruk and Bardia are in different territories, and the enclave is the perimeter.
def test_tobruk_and_bardia_lie_in_different_territories() -> None:
    places = _med_places()
    tobruk, bardia = (_where(*places[k]["at"]) for k in ("tobruk", "bardia"))
    assert (tobruk, bardia) == ("tobruk_area", "cyrenaica")
    assert mc.adjacent(_raw(), "tobruk_area", "cyrenaica")


@pytest.mark.parametrize(
    ("name", "lat", "lon", "key"),
    [
        ("inside the perimeter, south of the town", 31.95, 23.98, "tobruk_area"),
        ("inside the perimeter, east of the town", 32.00, 24.15, "tobruk_area"),
        ("outside the perimeter, south", 31.55, 23.98, "cyrenaica"),
        ("outside the perimeter, east", 31.95, 24.55, "cyrenaica"),
        ("outside the perimeter, west", 31.95, 23.40, "cyrenaica"),
        ("Benghazi", 32.12, 20.07, "cyrenaica"),
        ("Kufra", 24.20, 23.30, "cyrenaica"),
        ("Sollum, on the Egyptian side of the wire", 31.57, 25.15, "egypt"),
        ("Tripoli", 32.89, 13.19, "tripolitania"),
        ("Sirte", 31.21, 16.59, "tripolitania"),
        ("Sabha", 27.04, 14.43, "tripolitania"),
    ],
)
def test_the_libyan_territories_and_the_tobruk_perimeter(
    name: str, lat: float, lon: float, key: str
) -> None:
    assert _where(lat, lon) == key, name


def test_the_tobruk_enclave_is_at_least_the_checkers_minimum() -> None:
    assert mc.area(_raw(), "tobruk_area") >= mc.MIN_AREA["lonlat"]


def test_the_tobruk_cut_is_the_enclaves_and_the_split_is_drawn_on_the_proof_sheet() -> None:
    cuts = {str(c["name"]): c for c in _yaml(MEDITERRANEAN)["cuts"]}
    tobruk = cuts["the Tobruk perimeter of September 1941"]
    assert (tobruk["province"], tobruk["left"], tobruk["right"]) == (
        "LBY-2987",
        "tobruk_area",
        "cyrenaica",
    )
    assert tobruk["gap"] is True
    sheet = (ROOT / "worlds" / "maps" / "proof" / "autumn-1941-mediterranean.svg").read_text()
    assert "the Tobruk perimeter of September 1941" in sheet
    assert "The Tobruk enclave" in sheet
    assert "Bardia" in sheet


# Rule 3: Cyrenaica and Egypt meet at the present-day border, which is the 1941 wire.
def test_cyrenaica_and_egypt_meet_at_the_present_day_border() -> None:
    doc = {str(t["key"]): t for t in _yaml(MEDITERRANEAN)["territories"]}
    assert {str(c)[:3] for c in doc["egypt"]["provinces"]} == {"EGY"}
    assert {str(c)[:3] for c in doc["cyrenaica"]["provinces"]} == {"LBY"}
    assert mc.adjacent(_raw(), "cyrenaica", "egypt")
    assert not mc.adjacent(_raw(), "tobruk_area", "egypt")


# Rule 4: the Italian Dodecanese is cut from the Greek province that holds it.
@pytest.mark.parametrize(
    ("name", "lat", "lon", "key"),
    [
        ("Rhodes, inland", 36.20, 28.00, "dodecanese"),
        ("Kos", 36.85, 27.20, "dodecanese"),
        ("Astypalaia", 36.55, 26.35, "dodecanese"),
        ("Amorgos", 36.83, 25.90, "greece"),
        ("Athens", 37.98, 23.73, "greece"),
        ("Heraklion, Crete", 35.34, 25.14, "greece"),
    ],
)
def test_the_dodecanese_cut_gives_each_side_to_the_territory_it_names(
    name: str, lat: float, lon: float, key: str
) -> None:
    assert _where(lat, lon) == key, name


def test_the_dodecanese_cut_has_a_named_source_and_is_a_gap() -> None:
    cut = next(c for c in _yaml(MEDITERRANEAN)["cuts"] if c["name"] == "the Italian Dodecanese")
    assert (cut["province"], cut["left"], cut["right"]) == ("GRC-3013", "dodecanese", "greece")
    assert cut["gap"] is True
    assert cut["named_source"]


# The default taken for Malta.
def test_malta_is_joined_to_cyprus_because_it_is_under_the_minimum_area() -> None:
    territories = {str(t["key"]): t for t in _yaml(MEDITERRANEAN)["territories"]}
    assert "malta" not in territories
    islands = {str(c)[:3] for c in territories["british_islands"]["provinces"]}
    assert islands == {"MLT", "CYP"}
    assert _where(35.90, 14.51) == _where(35.17, 33.36) == "british_islands"


@pytest.mark.parametrize(
    ("town", "lat", "lon", "key"),
    [
        ("Algiers", 36.75, 3.06, "french_north_africa"),
        ("Casablanca", 33.57, -7.59, "french_north_africa"),
        ("Tunis", 36.80, 10.18, "tunisia"),
        ("Cairo", 30.04, 31.24, "egypt"),
        ("Suez", 29.97, 32.55, "egypt"),
        ("Jerusalem", 31.77, 35.22, "levant"),
        ("Amman", 31.95, 35.93, "levant"),
        ("Damascus", 33.51, 36.29, "syria"),
        ("Beirut", 33.89, 35.50, "syria"),
        ("Baghdad", 33.31, 44.37, "iraq"),
        ("Tehran", 35.69, 51.39, "iran"),
        ("Ankara", 39.93, 32.86, "turkey"),
        ("Istanbul", 41.01, 28.98, "turkey"),
        ("Baku", 40.41, 49.87, "caucasus"),
        ("Tbilisi", 41.72, 44.79, "caucasus"),
        ("Grozny", 43.32, 45.69, "caucasus"),
        ("Maikop", 44.60, 40.10, "caucasus"),
        ("Salonika", 40.64, 22.94, "greece"),
    ],
)
def test_each_mediterranean_town_lies_in_its_territory(
    town: str, lat: float, lon: float, key: str
) -> None:
    assert _where(lat, lon) == key, town


# Rule 1 (sea zones): the new zones join the Atlantic, Europe's and the pilot's, by shared border or
# by a declared crossing, so a convoy can pass from the Atlantic to Alexandria and to the Black Sea.
def _sea_links() -> dict[str, set[str]]:
    seas = _sea_keys() | set(MEDITERRANEAN_SEA_ZONES)
    links: dict[str, set[str]] = {z: set() for z in seas}
    for e in _yaml(FRAGMENT)["adjacency"]:
        a, b = (e["a"], e["b"]) if isinstance(e, dict) else (e[0], e[1])
        if a in seas and b in seas:
            links[a].add(b)
            links[b].add(a)
    return links


def _joined(a: str, b: str) -> bool:
    links, seen, todo = _sea_links(), {a}, [a]
    while todo:
        here = todo.pop()
        for z in links[here] - seen:
            seen.add(z)
            todo.append(z)
    return b in seen


def test_the_mediterranean_zones_join_the_atlantic_europe_and_the_black_sea() -> None:
    raw = _raw()
    for a, b in (
        ("gibraltar_approaches", "mid_ocean_gap"),
        ("gibraltar_approaches", "bay_of_biscay"),
        ("western_mediterranean", "central_mediterranean"),
        ("central_mediterranean", "eastern_mediterranean"),
        ("central_mediterranean", "aegean_sea"),
        ("aegean_sea", "eastern_mediterranean"),
    ):
        assert mc.adjacent(raw, a, b), (a, b)
    crossings = {
        (e["a"], e["b"]): e["crossing"] for e in _yaml(FRAGMENT)["adjacency"] if isinstance(e, dict)
    }
    assert crossings[("gibraltar_approaches", "western_mediterranean")] == "the Strait of Gibraltar"
    assert crossings[("aegean_sea", "black_sea")] == "the Turkish Straits"
    assert _joined("mid_ocean_gap", "eastern_mediterranean")
    assert _joined("mid_ocean_gap", "black_sea")


def test_the_mediterranean_recipe_agrees_with_the_others_on_the_box() -> None:
    assert _yaml(MEDITERRANEAN)["map"]["box"] == _raw()["box"]


def test_no_province_is_claimed_by_two_of_the_four_recipe_files() -> None:
    claims = [_claims(p) for p in RECIPES]
    assert claims[3]
    for i, a in enumerate(claims):
        for b in claims[i + 1 :]:
            assert a & b == set()


# ---------------------------------------------------------------- MAC: China, Japan and the Pacific

# Rule 1: the region's territories and sea zones, by key. [proposed] The plan's list of fourteen is
# here, with Japan in two, and five more the front and the bases need: Formosa, Hong Kong, the free
# Northwest and free South China (the land behind the front, which is in play), and Burma.
PACIFIC_TERRITORIES = (
    "japan_east",
    "japan_west",
    "formosa",
    "korea",
    "manchuria",
    "north_china",
    "wuhan_area",
    "hunan",
    "szechwan",
    "northwest_china",
    "south_china",
    "south_china_coast",
    "hong_kong",
    "indochina",
    "thailand",
    "malaya",
    "burma",
    "dutch_east_indies",
    "philippines",
    "hawaii",
    "soviet_far_east",
)
PACIFIC_SEA_ZONES = (
    "sea_of_japan",
    "east_china_sea",
    "south_china_sea",
    "andaman_sea",
    "java_sea",
    "philippine_sea",
    "north_pacific",
    "central_pacific",
    "eastern_pacific",
)
# Rule 2: the world's five places in the region, and the territory each lies in.
PACIFIC_WORLD_SITES = {
    "tokyo": "japan_east",
    "kure": "japan_west",
    "hitokappu_bay": "japan_east",
    "pearl_harbor_base": "hawaii",
    "chungking": "szechwan",
}
# Rule 2: the two new sites, their territory and their coordinates (GeoNames 1815577 and 1791247, to
# two decimals; the recipe cites them).
PACIFIC_NEW_SITES = {
    "changsha": ("hunan", (28.20, 112.97)),
    "wuhan": ("wuhan_area", (30.58, 114.27)),
}


def _pacific_places() -> dict[str, Any]:
    return {str(e["key"]): e for e in _yaml(PACIFIC_STAGING)["entities"]}


def test_the_pacific_region_has_its_territories_and_sea_zones() -> None:
    staged = _yaml(PACIFIC_STAGING)
    assert [t["key"] for t in staged["territories"]] == list(PACIFIC_TERRITORIES)
    assert [z["key"] for z in staged["sea_zones"]] == list(PACIFIC_SEA_ZONES)
    assert {t["region"] for t in staged["territories"] + staged["sea_zones"]} == {"pacific"}
    assert set(PACIFIC_TERRITORIES + PACIFIC_SEA_ZONES) <= set(_raw()["areas"])
    cut_to = {str(c[key]) for c in _yaml(PACIFIC)["cuts"] for key in ("left", "right") if key in c}
    for t in _yaml(PACIFIC)["territories"]:
        assert t.get("provinces") or t["key"] in cut_to, t["key"]


def test_the_pacific_staging_world_extends_the_mediterranean() -> None:
    parent = (PACIFIC_STAGING.parent / _yaml(PACIFIC_STAGING)["extends"]).resolve()
    assert parent == MEDITERRANEAN_STAGING.resolve()


def test_the_pacific_staging_blocks_are_the_built_fragments() -> None:
    fragment, staged = _yaml(FRAGMENT), _yaml(PACIFIC_STAGING)
    keep = ("territories", "sea_zones")
    for block in keep:
        assert staged[block] == [a for a in fragment[block] if a["region"] == "pacific"]
    own = {str(a["key"]) for block in keep for a in staged[block]}

    def pair(e: Any) -> tuple[str, str]:
        return (e["a"], e["b"]) if isinstance(e, dict) else (e[0], e[1])

    assert staged["adjacency"] == [e for e in fragment["adjacency"] if own & set(pair(e))]


def test_the_pacific_staging_world_names_its_places_file() -> None:
    assert _yaml(PACIFIC_STAGING)["places_of"] == PACIFIC_PLACES.name
    here = {str(e["key"]): e for e in _yaml(PACIFIC_PLACES)["entities"]}
    world = _world_places()
    for key, e in here.items():
        if key in world:
            assert e["at"] == world[key]["at"], key
    new = sorted(set(here) - set(world))
    assert new == sorted([*MEDITERRANEAN_PLACE_HOMES, *PACIFIC_NEW_SITES])
    for key in MEDITERRANEAN_PLACE_HOMES:
        assert here[key]["at"] == _med_places()[key]["at"], key


def test_the_scoped_check_passes_on_the_pacific_staging_world() -> None:
    report = mc.check_region(PACIFIC_STAGING)
    assert [str(p) for p in report.problems] == []
    assert not (set(PACIFIC_WORLD_SITES) | set(PACIFIC_NEW_SITES)) & set(report.out_of_scope)


def test_the_pacific_staging_world_puts_its_seven_places_in_scope() -> None:
    staged = _pacific_places()
    assert sorted(staged) == sorted([*PACIFIC_WORLD_SITES, *PACIFIC_NEW_SITES])
    world = _world_places()
    for key in PACIFIC_WORLD_SITES:
        assert staged[key]["at"] == world[key]["at"], key
    for key, (_, at) in PACIFIC_NEW_SITES.items():
        assert staged[key]["at"] == list(at), key
        assert not world.get(key), key


@pytest.mark.parametrize("site", PACIFIC_WORLD_SITES)
def test_each_pacific_world_place_lies_in_its_territory_and_is_its_site(site: str) -> None:
    assert _home(site) == PACIFIC_WORLD_SITES[site]
    holders = [str(t["key"]) for t in _staged_territories() if site in (t.get("sites") or [])]
    assert holders == [PACIFIC_WORLD_SITES[site]]


@pytest.mark.parametrize("site", PACIFIC_NEW_SITES)
def test_each_new_pacific_site_lies_in_its_territory_and_is_its_site(site: str) -> None:
    key, (lat, lon) = PACIFIC_NEW_SITES[site]
    assert _where(lat, lon) == key
    holders = [str(t["key"]) for t in _staged_territories() if site in (t.get("sites") or [])]
    assert holders == [key]


def test_the_new_pacific_sites_cite_their_coordinates() -> None:
    head = PACIFIC.read_text().split("\nmap:")[0]
    for geonames_id in ("1815577", "1791247"):
        assert f"https://www.geonames.org/{geonames_id}" in head


# Rule 3: each cut gives each side to the territory it names (a town on each side of every line).
PACIFIC_CUT_SIDES = (
    # Manchukuo's western border in Inner Mongolia.
    ("Hailar", 49.21, 119.74, "manchuria"),
    ("Ulanhot", 46.08, 122.05, "manchuria"),
    ("Chifeng", 42.26, 118.89, "manchuria"),
    ("Xilinhot", 43.93, 116.07, "north_china"),
    # Mengjiang against the free Hetao and Ordos.
    ("Hohhot", 40.82, 111.65, "north_china"),
    ("Baotou", 40.66, 109.84, "north_china"),
    ("Bayannur", 40.74, 107.39, "northwest_china"),
    ("Ordos", 39.61, 109.78, "northwest_china"),
    # The Yellow River flood front in Henan.
    ("Kaifeng", 34.80, 114.31, "north_china"),
    ("Shangqiu", 34.41, 115.65, "north_china"),
    ("Luoyang", 34.62, 112.45, "northwest_china"),
    ("Nanyang", 33.00, 112.53, "northwest_china"),
    # The Yichang front in Hubei.
    ("Yichang", 30.69, 111.29, "wuhan_area"),
    ("Shashi", 30.30, 112.25, "wuhan_area"),
    ("Enshi", 30.30, 109.48, "szechwan"),
    ("Xiangyang", 32.04, 112.14, "szechwan"),
    # The Xinqiang front at Yueyang.
    ("Yueyang", 29.36, 113.13, "wuhan_area"),
    ("Zhuzhou", 27.83, 113.13, "hunan"),
    # The Nanchang front in Jiangxi.
    ("Nanchang", 28.68, 115.86, "wuhan_area"),
    ("Jiujiang", 29.71, 116.00, "wuhan_area"),
    ("Ji'an", 27.11, 114.99, "hunan"),
    # The Chekiang front south of Ningbo.
    ("Hangzhou", 30.27, 120.15, "wuhan_area"),
    ("Shaoxing", 30.00, 120.58, "wuhan_area"),
    ("Jinhua", 29.08, 119.65, "south_china"),
    ("Wenzhou", 28.00, 120.67, "south_china"),
    # The Canton and Swatow perimeters in Guangdong.
    ("Canton", 23.13, 113.26, "south_china_coast"),
    ("Chaozhou", 23.66, 116.62, "south_china_coast"),
    ("Shaoguan", 24.80, 113.60, "south_china"),
    ("Meizhou", 24.29, 116.12, "south_china"),
    # Karafuto and the Kuriles.
    ("Toyohara", 46.96, 142.73, "japan_east"),
    ("Shumshu", 50.75, 156.30, "japan_east"),
    ("Okha", 53.57, 142.95, "soviet_far_east"),
)


@pytest.mark.parametrize(("town", "lat", "lon", "key"), PACIFIC_CUT_SIDES)
def test_each_pacific_cut_gives_each_side_to_the_territory_it_names(
    town: str, lat: float, lon: float, key: str
) -> None:
    assert _where(lat, lon) == key, town


def test_every_pacific_cut_is_a_gap_with_a_named_source() -> None:
    cuts = _yaml(PACIFIC)["cuts"]
    assert len(cuts) == 9
    for c in cuts:
        assert c["gap"] is True, c["name"]
        assert c.get("named_source"), c["name"]


@pytest.mark.parametrize(
    ("town", "lat", "lon", "key"),
    [
        ("Peking", 39.90, 116.40, "north_china"),
        ("Shanghai", 31.23, 121.47, "wuhan_area"),
        ("Nanking", 32.06, 118.80, "wuhan_area"),
        ("Kunming", 25.04, 102.71, "szechwan"),
        ("Xi'an", 34.26, 108.94, "northwest_china"),
        ("Yan'an", 36.60, 109.49, "northwest_china"),
        ("Guilin", 25.27, 110.29, "south_china"),
        ("Haikou", 20.04, 110.34, "south_china_coast"),
        ("Mukden", 41.80, 123.43, "manchuria"),
        ("Harbin", 45.75, 126.65, "manchuria"),
        ("Seoul", 37.57, 126.98, "korea"),
        ("Taipei", 25.03, 121.56, "formosa"),
        ("the New Territories", 22.45, 114.10, "hong_kong"),
        ("Vladivostok", 43.12, 131.89, "soviet_far_east"),
        ("Khabarovsk", 48.48, 135.08, "soviet_far_east"),
        ("Hanoi", 21.03, 105.85, "indochina"),
        ("Saigon", 10.82, 106.63, "indochina"),
        ("Battambang", 13.10, 103.20, "thailand"),
        ("Bangkok", 13.75, 100.50, "thailand"),
        ("Singapore", 1.35, 103.82, "malaya"),
        ("Kuching", 1.55, 110.35, "malaya"),
        ("Rangoon", 16.80, 96.15, "burma"),
        ("Batavia", -6.20, 106.85, "dutch_east_indies"),
        ("Manila", 14.60, 120.98, "philippines"),
        ("Honolulu", 21.30, -157.86, "hawaii"),
    ],
)
def test_each_pacific_town_lies_in_its_territory(
    town: str, lat: float, lon: float, key: str
) -> None:
    assert _where(lat, lon) == key, town


# Rule 4: the map joins across the date line. The box runs once round the globe, so Hawaii and the
# Central Pacific are drawn east of 180 and the Eastern Pacific reaches the American west coast.
def _pacific_sea_links() -> dict[str, set[str]]:
    fragment = _yaml(FRAGMENT)
    seas = {str(z["key"]) for z in fragment["sea_zones"]}
    links: dict[str, set[str]] = {z: set() for z in seas}
    for e in fragment["adjacency"]:
        a, b = (e["a"], e["b"]) if isinstance(e, dict) else (e[0], e[1])
        if a in seas and b in seas:
            links[a].add(b)
            links[b].add(a)
    return links


def _sea_route(a: str, b: str) -> bool:
    links, seen, todo = _pacific_sea_links(), {a}, [a]
    while todo:
        for z in links[todo.pop()] - seen:
            seen.add(z)
            todo.append(z)
    return b in seen


def _xs(key: str) -> list[float]:
    raw = _raw()
    return [raw["vertices"][i][0] for ring in raw["areas"][key]["rings"] for i in ring]


def test_the_box_runs_past_the_date_line_and_the_recipes_agree_on_it() -> None:
    box = _raw()["box"]
    assert box[0] < -120 and box[2] > 180
    assert box[2] - box[0] <= 360
    assert _yaml(PACIFIC)["map"]["box"] == box


def test_the_central_pacific_is_one_zone_across_the_date_line() -> None:
    xs = _xs("central_pacific")
    assert min(xs) < 180 < max(xs)
    assert _where(19.28, 166.65) == "central_pacific"  # Wake
    assert _where(28.20, -177.37) == "central_pacific"  # Midway, written west of the line
    assert min(_xs("hawaii")) > 180


def test_the_pacific_sea_zones_reach_the_american_west_coast() -> None:
    raw = _raw()
    # The coast lies inside the box's west edge and the zone ends at its east edge, the seam between
    # them: the two are joined by the declared crossing over the seam.
    assert max(_xs("eastern_pacific")) == raw["box"][2]
    assert 0 < min(_xs("us_west")) - raw["box"][0] < 3
    crossings = {
        (e["a"], e["b"]): e["crossing"] for e in _yaml(FRAGMENT)["adjacency"] if isinstance(e, dict)
    }
    assert crossings[("eastern_pacific", "us_west")] == "the box's seam at 126 W"
    staged = [e for e in _yaml(PACIFIC_STAGING)["adjacency"] if isinstance(e, dict)]
    assert {"a": "eastern_pacific", "b": "us_west", "crossing": "the box's seam at 126 W"} in staged
    assert mc.check_region(PACIFIC_STAGING).problems == []
    for a, b in (
        ("central_pacific", "eastern_pacific"),
        ("north_pacific", "eastern_pacific"),
        ("central_pacific", "hawaii"),
    ):
        assert mc.adjacent(raw, a, b), (a, b)
    assert _sea_route("sea_of_japan", "eastern_pacific")


def test_a_fleet_can_pass_from_the_pacific_to_the_atlantic_only_round_the_world() -> None:
    # No sea zone of the Pacific touches the Atlantic's: the map has no Panama or Cape Horn route.
    atlantic = {"western_atlantic", "caribbean_sea", "mid_ocean_gap"}
    for z in PACIFIC_SEA_ZONES:
        assert not _pacific_sea_links()[z] & atlantic, z


def test_the_pacific_proof_sheet_draws_the_region_and_its_cuts() -> None:
    sheet = (ROOT / "worlds" / "maps" / "proof" / "autumn-1941-pacific.svg").read_text()
    for name in ("Japan East", "Hunan and Kiangsi", "Hawaii", "The Eastern Pacific", "Changsha"):
        assert name in sheet, name
    for c in _yaml(PACIFIC)["cuts"]:
        assert str(c["name"]) in sheet, c["name"]
