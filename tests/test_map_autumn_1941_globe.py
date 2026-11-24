"""The whole-globe 1941 map: the Americas, Africa, inner Asia and Australasia regions, read from the
committed files only.

Pins that the Americas recipe claims its thirteen territories, the Africa recipe its twenty-two, the
inner Asia recipe its fourteen and the Australasia recipe its seven whole and leave the earlier
regions' keys alone, that each region's sites lie in the territory that names them, that the cut
lines of the earlier regions still give each side to the territory they name, that the map passes
the scoped check against the newest staging world (which extends the earlier ones), that the Gondar
cut gives each side to the territory it names, and that the start and yields files give each new
territory a holder and a row. It reads
the committed map, its recipes, staging worlds and objects; it needs neither the geometry tool nor
the border data, so it runs in CI.
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
INNER_ASIA = SRC / "inner-asia.yaml"
INNER_ASIA_STAGING = SRC / "inner-asia.world.yaml"
INNER_ASIA_PLACES = SRC / "inner-asia.places.yaml"
AUSTRALASIA = SRC / "australasia.yaml"
AUSTRALASIA_STAGING = SRC / "australasia.world.yaml"
AUSTRALASIA_PLACES = SRC / "australasia.places.yaml"
# The newest region's staging world: the scoped check runs on it, and it extends the earlier ones.
NEWEST = AUSTRALASIA_STAGING
PACIFIC_STAGING = SRC / "pacific.world.yaml"
PACIFIC_PLACES = SRC / "pacific.places.yaml"
START = SRC / "start.yaml"
YIELDS = SRC / "yields.yaml"
EARLIER = tuple(
    SRC / f"{name}.yaml"
    for name in ("eastern-front", "europe", "atlantic", "mediterranean", "pacific")
)
RECIPES = (*EARLIER, AMERICAS, AFRICA, INNER_ASIA, AUSTRALASIA)
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

# The regions draft's thirteen inner Asia territories and its small Goa, in the recipe's order.
INNER_ASIA_TERRITORIES = (
    "middle_volga",
    "urals",
    "western_siberia",
    "kazakhstan",
    "eastern_siberia",
    "turkestan",
    "afghanistan",
    "indus_northwest",
    "ganges_bengal",
    "southern_india",
    "portuguese_india",
    "tibet_nepal",
    "sinkiang",
    "mongolia",
)

# Each present-day country inner Asia takes whole, by the code prefix of its units, and how many
# units the data gives it; Russia, India and China only in part.
INNER_ASIA_WHOLE_COUNTRIES = {
    "KAZ": 16, "KAB": 1, "UZB": 14, "TKM": 5, "TJK": 5, "KGZ": 8, "AFG": 34, "PAK": 8, "KAS": 1,
    "BGD": 7, "LKA": 25, "NPL": 14, "BTN": 20, "MNG": 22,
}  # fmt: skip
# The Russian units the earlier regions left, by the territory that takes them.
INNER_ASIA_RUSSIA = {
    "middle_volga": {f"RUS-{n}" for n in (2390, 2388, 2392, 2395, 2394, 2385, 2384, 2387)},
    "urals": {f"RUS-{n}" for n in (2383, 2381, 3200, 2378, 2391, 2386, 2379, 2380)},
    "western_siberia": {"RUS+99?"}
    | {f"RUS-{n}" for n in (2398, 2396, 2382, 2397, 2403, 2167, 2401, 2399, 2400)},
    "eastern_siberia": {f"RUS-{n}" for n in (2603, 2402, 2602, 2606, 2612, 2615, 2321, 3468)},
    "mongolia": {"RUS-2605"},
}  # fmt: skip
# The Andaman and Nicobar Islands, left unclaimed until the Andaman Sea zone's edge is moved.
ANDAMANS = "IND-2474"
INNER_ASIA_PART_UNITS = {
    **INNER_ASIA_RUSSIA,
    "indus_northwest": {"IND-2431", "IND-20012", "IND-3249", "IND-3250", "IND-3264"},
    "ganges_bengal": {"IND-2428", "IND-3253", "IND-3257", "IND-2477", "IND-3299"},
    "southern_india": {"IND-2447", "IND-3263", "IND-2443"},
    "portuguese_india": {"IND-3265"},
    "tibet_nepal": {"CHN-1662"},
    "sinkiang": {"CHN-1756"},
}

# The region's sites: (lat, lon) as the places file gives them, and the territory each lies in.
INNER_ASIA_SITES = {
    "kuibyshev": ((53.2, 50.14), "middle_volga"),
    "kazan": ((55.8, 49.11), "middle_volga"),
    "astrakhan": ((46.35, 48.03), "middle_volga"),
    "sverdlovsk": ((56.84, 60.61), "urals"),
    "magnitogorsk": ((53.38, 59.03), "urals"),
    "novosibirsk": ((55.05, 82.95), "western_siberia"),
    "stalinsk": ((53.77, 87.13), "western_siberia"),
    "alma_ata": ((43.23, 76.95), "kazakhstan"),
    "karaganda": ((49.8, 73.11), "kazakhstan"),
    "krasnoyarsk": ((56.01, 92.87), "eastern_siberia"),
    "irkutsk": ((52.29, 104.28), "eastern_siberia"),
    "tashkent": ((41.31, 69.28), "turkestan"),
    "krasnovodsk": ((40.02, 52.97), "turkestan"),
    "kabul": ((34.53, 69.18), "afghanistan"),
    "karachi": ((24.86, 67.01), "indus_northwest"),
    "lahore": ((31.55, 74.34), "indus_northwest"),
    "rawalpindi": ((33.6, 73.03), "indus_northwest"),
    "new_delhi": ((28.61, 77.21), "ganges_bengal"),
    "calcutta": ((22.57, 88.37), "ganges_bengal"),
    "bombay": ((19.08, 72.88), "southern_india"),
    "madras": ((13.08, 80.28), "southern_india"),
    "trincomalee": ((8.57, 81.23), "southern_india"),
    "colombo": ((6.93, 79.9), "southern_india"),
    "nova_goa": ((15.5, 73.83), "portuguese_india"),
    "lhasa": ((29.65, 91.12), "tibet_nepal"),
    "urumchi": ((43.82, 87.61), "sinkiang"),
    "hami": ((42.82, 93.52), "sinkiang"),
    "ulan_bator": ((47.92, 106.92), "mongolia"),
    "kyzyl": ((51.72, 94.45), "mongolia"),
}

# The new holders with no seat that start.yaml adds for the region.
INNER_ASIA_POLITIES = (
    "afghanistan_state",
    "tibet",
    "mongolia_state",
)


# The regions draft's seven Australasia and Pacific territories, in the recipe's order.
AUSTRALASIA_TERRITORIES = (
    "australia_west",
    "australia_east",
    "new_zealand",
    "new_guinea",
    "japanese_mandate",
    "south_pacific",
    "new_caledonia",
)

# Each present-day country or dependency the region takes whole, by the code prefix of its units,
# and how many units the data gives it.
AUSTRALASIA_WHOLE_COUNTRIES = {
    "AUS": 11, "ATC": 1, "IOA": 2, "NFK": 1, "CSI": 1, "NZL": 24, "PNG": 20, "SLB": 10, "PLW": 16,
    "FSM": 4, "MHL": 2, "MNP": 4, "FJI": 5, "TON": 5, "WSM": 11, "ASM": 5, "KIR": 2, "TUV": 1,
    "NRU": 14, "COK": 11, "NIU": 1, "WLF": 3, "PYF": 5, "PCN": 1, "NCL": 3, "VUT": 6,
}  # fmt: skip
# Guam and the United States' minor islands (Wake, Midway and the rest) stay places in their sea
# zones, unclaimed (the regions draft); Heard Island waits for the southern seas.
AUSTRALASIA_UNCLAIMED = {
    "GUM+00?", "UMI-5171", "UMI-5172", "UMI-5173", "UMI-5174", "UMI-5176", "UMI-5178", "UMI-5179",
    "HMD+00?",
}  # fmt: skip
AUSTRALASIA_PART_UNITS = {
    "australia_west": {"AUS-2650", "AUS-2651", "ATC+00?", "IOA-1928", "IOA-2652"},
    "japanese_mandate": {"PLW-5249", "FSM-4942", "MHL-4969", "MNP-4939"},
    "new_guinea": {"PNG-1250", "PNG-1254", "SLB-1263"},
}

# The region's sites: (lat, lon) as the places file gives them, and the territory each lies in.
AUSTRALASIA_SITES = {
    "darwin": ((-12.42, 130.88), "australia_west"),
    "perth": ((-31.95, 115.86), "australia_west"),
    "sydney": ((-33.87, 151.21), "australia_east"),
    "melbourne": ((-37.81, 144.96), "australia_east"),
    "brisbane": ((-27.47, 153.03), "australia_east"),
    "wellington": ((-41.28, 174.75), "new_zealand"),
    "auckland": ((-36.85, 174.76), "new_zealand"),
    "port_moresby": ((-9.44, 147.18), "new_guinea"),
    "rabaul": ((-4.2, 152.18), "new_guinea"),
    "tulagi": ((-9.06, 160.17), "new_guinea"),
    "saipan": ((15.18, 145.75), "japanese_mandate"),
    "koror": ((7.34, 134.48), "japanese_mandate"),
    "suva": ((-18.14, 178.44), "south_pacific"),
    "pago_pago": ((-14.3, -170.74), "south_pacific"),
    "papeete": ((-17.54, -149.57), "south_pacific"),
    "noumea": ((-22.27, 166.44), "new_caledonia"),
    "espiritu_santo": ((-15.51, 167.18), "new_caledonia"),
}

# The region's places at sea: atolls the simplified coast does not keep, each in its sea zone.
AUSTRALASIA_SEA_PLACES = {
    "truk": ((7.45, 151.85), "central_pacific"),
    "kwajalein": ((8.72, 167.73), "central_pacific"),
    "wake": ((19.28, 166.65), "central_pacific"),
}

# The holder with no seat that the region's territories name.
AUSTRALASIA_POLITIES = ("free_france",)


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


def test_the_map_is_the_nine_regions_areas_and_no_others() -> None:
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


def test_no_province_is_claimed_twice_across_the_nine_recipes() -> None:
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


def test_the_scoped_check_passes_on_the_newest_staging_world_with_africa_in_scope() -> None:
    report = mc.check_region(NEWEST)
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


# ---------------------------------------------------------------- India, Central Asia and Siberia


def test_the_inner_asia_region_has_its_territories() -> None:
    staged = _yaml(INNER_ASIA_STAGING)
    assert [t["key"] for t in staged["territories"]] == list(INNER_ASIA_TERRITORIES)
    assert {t["region"] for t in staged["territories"]} == {"inner_asia"}
    assert not staged.get("sea_zones")
    assert set(INNER_ASIA_TERRITORIES) <= set(_raw()["areas"])
    recipe = _yaml(INNER_ASIA)
    assert recipe["cuts"] == []
    for t in recipe["territories"]:
        assert t.get("provinces"), t["key"]
        assert t.get("terrain"), t["key"]
        assert bool(t.get("terrain_source")) != bool(t.get("terrain_gap")), t["key"]


@pytest.mark.parametrize("country", sorted(INNER_ASIA_WHOLE_COUNTRIES))
def test_inner_asia_takes_each_country_whole(country: str) -> None:
    claimed = [c for c in _claims(INNER_ASIA) if c.startswith(country)]
    assert len(claimed) == INNER_ASIA_WHOLE_COUNTRIES[country], country


@pytest.mark.parametrize("territory", sorted(INNER_ASIA_PART_UNITS))
def test_inner_asia_takes_the_units_of_a_shared_country(territory: str) -> None:
    rows = {str(t["key"]): t for t in _yaml(INNER_ASIA)["territories"]}
    assert INNER_ASIA_PART_UNITS[territory] <= {str(c) for c in rows[territory]["provinces"]}


def test_russia_is_wholly_claimed_and_india_all_but_the_andamans() -> None:
    claims = {c for recipe in RECIPES for c in _claims(recipe)}
    cut = {str(c["province"]) for recipe in RECIPES for c in _yaml(recipe).get("cuts") or []}
    russia = {c for t in INNER_ASIA_RUSSIA.values() for c in t}
    assert russia <= claims
    assert len({c for c in claims | cut if c.startswith("RUS")}) == 86
    assert len({c for c in _claims(INNER_ASIA) if c.startswith("IND")}) == 35
    assert ANDAMANS not in claims


def test_the_inner_asia_staging_world_lists_the_sites_of_each_territory() -> None:
    sites = {
        str(s): str(t["key"])
        for t in _yaml(INNER_ASIA_STAGING)["territories"]
        for s in t.get("sites") or []
    }
    assert sites == {k: home for k, (_, home) in INNER_ASIA_SITES.items()}


@pytest.mark.parametrize("site", sorted(INNER_ASIA_SITES))
def test_each_inner_asia_site_lies_in_its_territory(site: str) -> None:
    (lat, lon), home = INNER_ASIA_SITES[site]
    inside, border = mc.locate(_raw(), float(lon), float(lat))
    assert not border, site
    assert inside == [home], site


def test_the_inner_asia_places_file_extends_the_africa_one() -> None:
    assert _yaml(INNER_ASIA_STAGING)["places_of"] == INNER_ASIA_PLACES.name
    here = _yaml(INNER_ASIA_PLACES)["entities"]
    earlier = _yaml(AFRICA_PLACES)["entities"]
    assert here[: len(earlier)] == earlier
    new = {str(e["key"]): e for e in here[len(earlier) :]}
    assert {k: tuple(e["at"]) for k, e in new.items()} == {
        k: at for k, (at, _) in INNER_ASIA_SITES.items()
    }


def test_the_inner_asia_staging_world_extends_africa() -> None:
    parent = (INNER_ASIA_STAGING.parent / _yaml(INNER_ASIA_STAGING)["extends"]).resolve()
    assert parent == AFRICA_STAGING.resolve()


def test_the_inner_asia_staging_blocks_are_the_built_fragments() -> None:
    fragment, staged = _yaml(FRAGMENT), _yaml(INNER_ASIA_STAGING)
    assert staged["territories"] == [
        a for a in fragment["territories"] if a["region"] == "inner_asia"
    ]
    own = {str(a["key"]) for a in staged["territories"]}

    def pair(e: Any) -> tuple[str, str]:
        return (e["a"], e["b"]) if isinstance(e, dict) else (e[0], e[1])

    assert staged["adjacency"] == [e for e in fragment["adjacency"] if own & set(pair(e))]


def test_the_scoped_check_passes_on_the_newest_staging_world_with_inner_asia_in_scope() -> None:
    report = mc.check_region(NEWEST)
    assert [str(p) for p in report.problems] == []
    assert not set(INNER_ASIA_SITES) & set(report.out_of_scope)


def test_each_inner_asia_territory_has_a_holder_with_a_gap_or_a_source() -> None:
    start = _yaml(START)
    holders = {str(h["territory"]): h for h in start["holders"]}
    keys = {str(e["key"]): e for e in start["entities"]}
    seats = {"usa", "uk", "germany", "ussr", "japan", "italy", "china"}
    for t in INNER_ASIA_TERRITORIES:
        h = holders[t]
        assert h.get("gap") is True or h.get("source"), t
        assert h["holder"] in seats or keys[h["holder"]]["kind"] == "polity", t


def test_the_inner_asia_holders_are_polities() -> None:
    keys = {str(e["key"]): e for e in _yaml(START)["entities"]}
    for p in INNER_ASIA_POLITIES:
        assert keys[p]["kind"] == "polity", p
    assert not set(INNER_ASIA_POLITIES) & set(INNER_ASIA_TERRITORIES)


def test_each_inner_asia_site_is_a_place_of_the_start_within_its_territory() -> None:
    keys = {str(e["key"]): e for e in _yaml(START)["entities"]}
    for site, (at, home) in INNER_ASIA_SITES.items():
        e = keys[site]
        assert e["kind"] == "location", site
        assert tuple(e["at"]) == at, site
        assert e["within"] == home, site


def test_each_inner_asia_territory_has_a_yields_row() -> None:
    doc = _yaml(YIELDS)
    rows = {str(r["key"]): r for r in doc["territories"]}
    sources = {str(s["key"]) for s in doc["sources"]}
    resources = [str(r["key"]) for r in _yaml(START)["resources"]]
    for t in INNER_ASIA_TERRITORIES:
        row = rows[t]
        assert set(row) == {"key", *resources}, t
        for r in resources:
            entry = row[r]
            assert entry.get("gap") is True, (t, r)
            assert entry["named_source"] in sources, (t, r)
            assert str(entry.get("basis") or "").strip(), (t, r)
        assert row["supply"]["amount"] == len(row["supply"].get("hubs") or []), t


# ---------------------------------------------------------------- Australasia and the Pacific


def test_the_australasia_region_has_its_territories() -> None:
    staged = _yaml(AUSTRALASIA_STAGING)
    assert [t["key"] for t in staged["territories"]] == list(AUSTRALASIA_TERRITORIES)
    assert {t["region"] for t in staged["territories"]} == {"australasia"}
    assert not staged.get("sea_zones")
    assert set(AUSTRALASIA_TERRITORIES) <= set(_raw()["areas"])
    recipe = _yaml(AUSTRALASIA)
    assert recipe["cuts"] == []
    for t in recipe["territories"]:
        assert t.get("provinces"), t["key"]
        assert t.get("terrain"), t["key"]
        assert bool(t.get("terrain_source")) != bool(t.get("terrain_gap")), t["key"]


@pytest.mark.parametrize("country", sorted(AUSTRALASIA_WHOLE_COUNTRIES))
def test_australasia_takes_each_country_whole(country: str) -> None:
    claimed = [c for c in _claims(AUSTRALASIA) if c.startswith(country)]
    assert len(claimed) == AUSTRALASIA_WHOLE_COUNTRIES[country], country


@pytest.mark.parametrize("territory", sorted(AUSTRALASIA_PART_UNITS))
def test_australasia_puts_each_unit_in_its_territory(territory: str) -> None:
    rows = {str(t["key"]): t for t in _yaml(AUSTRALASIA)["territories"]}
    assert AUSTRALASIA_PART_UNITS[territory] <= {str(c) for c in rows[territory]["provinces"]}


def test_guam_and_the_united_states_minor_islands_stay_unclaimed() -> None:
    claims = {c for recipe in RECIPES for c in _claims(recipe)}
    assert not AUSTRALASIA_UNCLAIMED & claims


def test_new_guinea_has_no_cut_and_its_dutch_half_stays_in_the_indies() -> None:
    claims = {c for recipe in RECIPES for c in _claims(recipe)}
    cut = {str(c["province"]) for recipe in RECIPES for c in _yaml(recipe).get("cuts") or []}
    assert not {c for c in cut if c.startswith(("PNG", "IDN"))}
    pacific = {str(t["key"]): t for t in _yaml(SRC / "pacific.yaml")["territories"]}
    indies = {str(c) for c in pacific["dutch_east_indies"]["provinces"]}
    assert {c for c in claims if c.startswith("IDN")} <= indies


def test_the_australasia_staging_world_lists_the_sites_of_each_territory() -> None:
    sites = {
        str(s): str(t["key"])
        for t in _yaml(AUSTRALASIA_STAGING)["territories"]
        for s in t.get("sites") or []
    }
    assert sites == {k: home for k, (_, home) in AUSTRALASIA_SITES.items()}


@pytest.mark.parametrize("site", sorted({**AUSTRALASIA_SITES, **AUSTRALASIA_SEA_PLACES}))
def test_each_australasia_site_lies_in_its_territory(site: str) -> None:
    (lat, lon), home = {**AUSTRALASIA_SITES, **AUSTRALASIA_SEA_PLACES}[site]
    inside, border = mc.locate(_raw(), float(lon), float(lat))
    assert not border, site
    assert inside == [home], site


def test_the_australasia_places_file_extends_the_inner_asia_one() -> None:
    assert _yaml(AUSTRALASIA_STAGING)["places_of"] == AUSTRALASIA_PLACES.name
    here = _yaml(AUSTRALASIA_PLACES)["entities"]
    earlier = _yaml(INNER_ASIA_PLACES)["entities"]
    assert here[: len(earlier)] == earlier
    new = {str(e["key"]): e for e in here[len(earlier) :]}
    assert {k: tuple(e["at"]) for k, e in new.items()} == {
        k: at for k, (at, _) in {**AUSTRALASIA_SITES, **AUSTRALASIA_SEA_PLACES}.items()
    }


def test_the_australasia_staging_world_extends_inner_asia() -> None:
    parent = (AUSTRALASIA_STAGING.parent / _yaml(AUSTRALASIA_STAGING)["extends"]).resolve()
    assert parent == INNER_ASIA_STAGING.resolve()


def test_the_australasia_staging_blocks_are_the_built_fragments() -> None:
    fragment, staged = _yaml(FRAGMENT), _yaml(AUSTRALASIA_STAGING)
    assert staged["territories"] == [
        a for a in fragment["territories"] if a["region"] == "australasia"
    ]
    own = {str(a["key"]) for a in staged["territories"]}

    def pair(e: Any) -> tuple[str, str]:
        return (e["a"], e["b"]) if isinstance(e, dict) else (e[0], e[1])

    assert staged["adjacency"] == [e for e in fragment["adjacency"] if own & set(pair(e))]


def test_the_australasia_staging_world_is_the_newest() -> None:
    assert NEWEST == AUSTRALASIA_STAGING
    report = mc.check_region(AUSTRALASIA_STAGING)
    assert [str(p) for p in report.problems] == []
    assert not {*AUSTRALASIA_SITES, *AUSTRALASIA_SEA_PLACES} & set(report.out_of_scope)


def test_each_australasia_territory_has_a_holder_with_a_gap_or_a_source() -> None:
    start = _yaml(START)
    holders = {str(h["territory"]): h for h in start["holders"]}
    keys = {str(e["key"]): e for e in start["entities"]}
    seats = {"usa", "uk", "germany", "ussr", "japan", "italy", "china"}
    for t in AUSTRALASIA_TERRITORIES:
        h = holders[t]
        assert h.get("gap") is True or h.get("source"), t
        assert h["holder"] in seats or keys[h["holder"]]["kind"] == "polity", t
    assert holders["japanese_mandate"]["holder"] == "japan"
    assert holders["new_caledonia"]["holder"] == "free_france"


def test_the_australasia_holders_are_polities() -> None:
    keys = {str(e["key"]): e for e in _yaml(START)["entities"]}
    for p in AUSTRALASIA_POLITIES:
        assert keys[p]["kind"] == "polity", p
    assert not set(AUSTRALASIA_POLITIES) & set(AUSTRALASIA_TERRITORIES)


def test_each_australasia_site_is_a_place_of_the_start_within_its_territory() -> None:
    keys = {str(e["key"]): e for e in _yaml(START)["entities"]}
    for site, (at, home) in {**AUSTRALASIA_SITES, **AUSTRALASIA_SEA_PLACES}.items():
        e = keys[site]
        assert e["kind"] == "location", site
        assert tuple(e["at"]) == at, site
        assert e["within"] == home, site


def test_each_australasia_territory_has_a_yields_row() -> None:
    doc = _yaml(YIELDS)
    rows = {str(r["key"]): r for r in doc["territories"]}
    sources = {str(s["key"]) for s in doc["sources"]}
    resources = [str(r["key"]) for r in _yaml(START)["resources"]]
    for t in AUSTRALASIA_TERRITORIES:
        row = rows[t]
        assert set(row) == {"key", *resources}, t
        for r in resources:
            entry = row[r]
            assert entry.get("gap") is True, (t, r)
            assert entry["named_source"] in sources, (t, r)
            assert str(entry.get("basis") or "").strip(), (t, r)
        assert row["supply"]["amount"] == len(row["supply"].get("hubs") or []), t
