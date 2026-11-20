"""The 1941 start (WPD): wars, starting holders, bases and pieces, as a staging file.

``worlds/maps/src/autumn-1941/start.yaml`` holds the blocks the territory world of autumn 1941
starts from; the item that converts the world (FLP) assembles them into the world file, so the
game plays as today until then. These tests read the staging file against the map's world
fragment (``worlds/maps/autumn-1941.world.yaml``), the map file and today's world file. Each
block is shaped as the world file has it and is validated by the world's own declarations, with
three blocks of the staging file's own: ``holders`` (each territory's holder on the start date),
``forces`` (each force's piece kind, the area it stands in and its scripted legs as areas), and
the places it restates with ``within``, ``port_on`` and ``base``.
"""

import copy
import importlib.util
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from revisionist.core.realism.bases import BASES
from revisionist.core.realism.geography import FeatureKind
from revisionist.core.world import (
    EntityDecl,
    FeatureDecl,
    PieceKindDecl,
    ResourceDecl,
    SourceDecl,
    TerrainDecl,
    WarDecl,
)

ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "worlds" / "maps" / "src" / "autumn-1941" / "start.yaml"
FRAGMENT = ROOT / "worlds" / "maps" / "autumn-1941.world.yaml"
MAP = ROOT / "worlds" / "maps" / "autumn-1941.json"
WORLD = ROOT / "tests" / "worlds" / "autumn-1941-points.yaml"
"""The world before territories, which the staging files were written against."""

SEATED = ("usa", "uk", "japan", "germany", "italy", "ussr", "china")
"""The seven nations with seats in the 1941 world."""

PIECE_OF = {FeatureKind.ARMY: "army", FeatureKind.FLEET: "fleet", FeatureKind.AIR: "air_group"}
"""The piece kind each of today's force kinds becomes."""

DOMAIN_OF = {"F": "sea", "A": "land", "R": "air"}


def _load_map_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_check", ROOT / "scripts" / "map_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mc = _load_map_check()


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def start() -> dict[str, Any]:
    return dict(_yaml(START))


@pytest.fixture(scope="module")
def world() -> dict[str, Any]:
    return dict(_yaml(WORLD))


@pytest.fixture(scope="module")
def fragment() -> dict[str, Any]:
    return dict(_yaml(FRAGMENT))


@pytest.fixture(scope="module")
def raw() -> Any:
    return mc.load(MAP)[0]


# ---------------------------------------------------------------- reading the files


def _territories(fragment: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(t["key"]): t for t in fragment["territories"]}


def _zones(fragment: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(z["key"]): z for z in fragment["sea_zones"]}


def _links(fragment: dict[str, Any]) -> set[frozenset[str]]:
    out = set()
    for e in fragment["adjacency"]:
        a, b = (e["a"], e["b"]) if isinstance(e, dict) else e
        out.add(frozenset((str(a), str(b))))
    return out


def _places(start: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(e["key"]): e for e in start["entities"] if e["kind"] == "location"}


def _polities(start: dict[str, Any], world: dict[str, Any]) -> set[str]:
    return {
        str(e["key"]) for e in [*world["entities"], *start["entities"]] if e["kind"] == "polity"
    }


def _world_forces(world: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(f["key"]): f for f in world["features"] if FeatureKind(f["kind"]) in PIECE_OF}


def _seated(world: dict[str, Any]) -> set[str]:
    seats = {str(s.get("polity") or s.get("entity")) for s in world.get("seats") or []}
    sides = {str(side["side"]) for r in world["roster"] for side in r.get("sides") or []}
    return seats | sides


def _kinds(start: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(k["key"]): k for k in start["piece_kinds"]}


def _stand_area(place: dict[str, Any], domain: str) -> str:
    """The area a piece of ``domain`` stands in at ``place``: a sea piece at a port stands
    in the zone the port opens on, any other piece in the area the place lies within."""
    if domain == "sea" and place.get("port_on"):
        return str(place["port_on"])
    return str(place["within"])


def _base_area(place: dict[str, Any], domain: str, fragment: dict[str, Any]) -> str | None:
    """The area a piece of ``domain`` stands in at a base: a ship at the port's zone, or the
    zone the place lies in; a land or air piece in the territory, none for a place at sea."""
    within = str(place["within"])
    if domain == "sea":
        return str(place.get("port_on") or (within if within in _zones(fragment) else None))
    return within if within in _territories(fragment) else None


# ---------------------------------------------------------------- the checker


def problems(start: dict[str, Any], world: dict[str, Any], fragment: dict[str, Any]) -> list[str]:
    """What is wrong with the staging file against the map's fragment and today's world:
    every area named exists, every holder is a polity, every force's kind can stand in its
    area and every force opens at a base of its side."""
    out: list[str] = []
    territories, zones = _territories(fragment), _zones(fragment)
    areas = set(territories) | set(zones)
    polities = _polities(start, world)
    places = _places(start)
    kinds = _kinds(start)

    held = [str(h["territory"]) for h in start["holders"]]
    for t in sorted(set(territories) - set(held)):
        out.append(f"territory {t} has no holder")
    for t in sorted({t for t in held if held.count(t) > 1}):
        out.append(f"territory {t} has more than one holder")
    for h in start["holders"]:
        if h["territory"] not in territories:
            out.append(f"holder of {h['territory']}: no such territory")
        if h["holder"] not in polities:
            out.append(f"holder of {h['territory']}: {h['holder']} is not a polity")

    for key, p in places.items():
        if p.get("within") not in areas:
            out.append(f"place {key}: within {p.get('within')}, which is no area")
        if p.get("port_on") is not None and p["port_on"] not in zones:
            out.append(f"place {key}: port_on {p['port_on']}, which is no sea zone")
        base = p.get("base")
        if base is not None:
            for side in base["sides"]:
                if side not in polities:
                    out.append(f"place {key}: base side {side} is not a polity")

    for f in start["forces"]:
        key, kind = str(f["key"]), kinds.get(str(f["piece"]))
        if kind is None:
            out.append(f"force {key}: unknown piece kind {f['piece']}")
            continue
        domain = str(kind["domain"])
        for n, area in enumerate([f["area"], *(leg["area"] for leg in f.get("legs") or [])]):
            at = "" if n == 0 else f" leg {n}"
            if area not in areas:
                out.append(f"force {key}{at}: area {area} is no area of the map")
            elif domain == "land" and area not in territories:
                out.append(f"force {key}{at}: a land piece cannot stand in {area}")
            elif domain == "sea" and area not in zones:
                out.append(f"force {key}{at}: a sea piece cannot stand in {area}")
        side = str(f["side"])
        if not any(
            p.get("base") is not None
            and side in p["base"]["sides"]
            and domain in p["base"]["domains"]
            and _base_area(p, domain, fragment) == f["area"]
            for p in places.values()
        ):
            out.append(f"force {key}: opens at {f['area']}, at no {domain} base of {side}")
    return out


def test_the_staging_file_validates_against_the_map(
    start: dict[str, Any], world: dict[str, Any], fragment: dict[str, Any]
) -> None:
    assert problems(start, world, fragment) == []


# ---------------------------------------------------------------- the mutants


def _holder(doc: dict[str, Any], territory: str) -> dict[str, Any]:
    return next(h for h in doc["holders"] if h["territory"] == territory)


def test_a_force_off_its_base_is_refused(
    start: dict[str, Any], world: dict[str, Any], fragment: dict[str, Any]
) -> None:
    doc = copy.deepcopy(start)
    force = next(f for f in doc["forces"] if f["key"] == "afrika_korps")
    force["area"] = "tripolitania"
    assert problems(doc, world, fragment) == [
        "force afrika_korps: opens at tripolitania, at no land base of germany"
    ]


def test_a_holder_that_is_not_a_polity_is_refused(
    start: dict[str, Any], world: dict[str, Any], fragment: dict[str, Any]
) -> None:
    doc = copy.deepcopy(start)
    _holder(doc, "egypt")["holder"] = "alexandria"
    assert problems(doc, world, fragment) == ["holder of egypt: alexandria is not a polity"]


def test_tobruk_and_bardia_given_one_holder_are_refused(start: dict[str, Any]) -> None:
    doc = copy.deepcopy(start)
    _holder(doc, "tobruk_area")["holder"] = "italy"
    with pytest.raises(AssertionError):
        _check_the_desert(doc)


def test_a_territory_with_no_holder_is_refused(
    start: dict[str, Any], world: dict[str, Any], fragment: dict[str, Any]
) -> None:
    doc = copy.deepcopy(start)
    doc["holders"] = [h for h in doc["holders"] if h["territory"] != "crimea"]
    assert problems(doc, world, fragment) == ["territory crimea has no holder"]


def test_a_fleet_on_land_is_refused(
    start: dict[str, Any], world: dict[str, Any], fragment: dict[str, Any]
) -> None:
    doc = copy.deepcopy(start)
    force = next(f for f in doc["forces"] if f["key"] == "home_fleet")
    force["area"] = "britain_north"
    assert "force home_fleet: a sea piece cannot stand in britain_north" in problems(
        doc, world, fragment
    )


# ---------------------------------------------------------------- rule 1: five wars

WARS = {
    ("uk", "germany"): (date(1939, 9, 3), True),
    ("italy", "uk"): (date(1940, 6, 10), True),
    ("germany", "ussr"): (date(1941, 6, 22), True),
    ("italy", "ussr"): (date(1941, 6, 22), True),
    ("japan", "china"): (date(1937, 7, 7), False),
}
"""Who began each war, the day, and whether it was declared."""

ITALIAN = {("italy", "uk"), ("italy", "ussr")}
"""The two Italian declarations: a gap until sourced (the plan's default)."""


def test_five_wars_are_in_force_at_the_start(start: dict[str, Any]) -> None:
    wars = [WarDecl.model_validate(w) for w in start["wars"]]
    assert {(w.a, w.b): (w.since, w.declared) for w in wars} == WARS
    assert len(wars) == len(WARS)


def test_each_war_is_sourced_or_a_gap_until_sourced(start: dict[str, Any]) -> None:
    sources = {s.key for s in (SourceDecl.model_validate(s) for s in start["sources"])}
    for w in start["wars"]:
        if (w["a"], w["b"]) in ITALIAN:
            assert w.get("gap") is True and "source" not in w
        else:
            assert w["source"] in sources


def test_every_war_is_between_seated_nations(start: dict[str, Any]) -> None:
    for w in start["wars"]:
        assert w["a"] in SEATED and w["b"] in SEATED


# ---------------------------------------------------------------- rule 2: holders


def test_every_land_territory_has_one_holder_and_no_sea_zone_has_one(
    start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    held = [str(h["territory"]) for h in start["holders"]]
    assert sorted(held) == sorted(_territories(fragment))
    assert not set(held) & set(_zones(fragment))


def test_each_holder_cites_a_source_or_is_a_gap(start: dict[str, Any]) -> None:
    sources = {str(s["key"]) for s in start["sources"]}
    for h in start["holders"]:
        assert (h.get("gap") is True) != (h.get("source") in sources), h


CAPITALS = {
    "usa": "us_east",
    "uk": "britain_south",
    "japan": "japan_east",
    "germany": "germany_east",
    "italy": "italy_south",
    "ussr": "moscow_area",
    "china": "szechwan",
}


@pytest.mark.parametrize(("nation", "territory"), sorted(CAPITALS.items()))
def test_each_nation_holds_its_capitals_territory(
    start: dict[str, Any], nation: str, territory: str
) -> None:
    assert _holder(start, territory)["holder"] == nation


HELD = {
    "smolensk_area": "germany",
    "baltic_states": "germany",
    "belorussia": "germany",
    "western_ukraine": "germany",
    "kiev_area": "ussr",
    "odessa_area": "ussr",
    "leningrad_area": "ussr",
    "occupied_france": "germany",
    "vichy_france": "french_state",
    "greece": "germany",
    "dodecanese": "italy",
    "north_china": "japan",
    "wuhan_area": "japan",
    "hunan": "china",
    "manchuria": "japan",
    "hong_kong": "uk",
    "philippines": "usa",
    "dutch_east_indies": "netherlands",
}
"""Holders on 1 Sep 1941 the tests pin: the front in the east, the occupied west and China."""


@pytest.mark.parametrize(("territory", "holder"), sorted(HELD.items()))
def test_the_front_of_1_september_1941(start: dict[str, Any], territory: str, holder: str) -> None:
    assert _holder(start, territory)["holder"] == holder


def test_the_neutrals_are_polities_with_no_seat(
    start: dict[str, Any], world: dict[str, Any]
) -> None:
    neutral = {str(h["holder"]) for h in start["holders"]} - set(SEATED)
    assert neutral >= {"sweden", "switzerland", "spain", "turkey_state"}
    assert not neutral & _seated(world)
    declared = {str(e["key"]) for e in world["entities"] if e["kind"] == "polity"}
    added = {str(e["key"]) for e in start["entities"] if e["kind"] == "polity"}
    assert neutral <= declared | added


def test_the_new_polities_are_valid_and_their_keys_name_no_area(
    start: dict[str, Any], world: dict[str, Any], fragment: dict[str, Any]
) -> None:
    taken = {str(e["key"]) for e in world["entities"]}
    areas = set(_territories(fragment)) | set(_zones(fragment))
    for e in start["entities"]:
        if e["kind"] != "polity":
            continue
        EntityDecl.model_validate(e)
        assert e["key"] not in taken
        if e["key"] != "sweden":  # the key the Europe recipe names for Sweden's holder
            assert e["key"] not in areas, e["key"]


# ---------------------------------------------------------------- rule 3: terrain, resources, kinds


def test_the_terrain_is_the_maps(start: dict[str, Any], fragment: dict[str, Any]) -> None:
    terrain = {t.key: t.kind.value for t in map(TerrainDecl.model_validate, start["terrain"])}
    land = {str(t["terrain"]) for t in fragment["territories"]}
    sea = {str(z["terrain"]) for z in fragment["sea_zones"]}
    assert terrain == {k: "land" for k in land} | {k: "sea" for k in sea}


def test_five_resources_one_for_each_role(start: dict[str, Any]) -> None:
    resources = [ResourceDecl.model_validate(r) for r in start["resources"]]
    assert {r.key: r.role.value for r in resources} == {
        "industry": "output",
        "manpower": "manpower",
        "oil": "fuel",
        "supply": "supply",
        "prestige": "prestige",
    }


def test_the_piece_kinds_and_their_days_per_step(start: dict[str, Any]) -> None:
    kinds = {k.key: k for k in map(PieceKindDecl.model_validate, start["piece_kinds"])}
    assert set(kinds) == {"army", "fleet", "air_group", "envoy"}
    assert kinds["army"].domain.value == "land"
    assert kinds["army"].days_per_step == {"plain": 5, "forest": 7, "marsh": 7, "mountain": 10}
    assert kinds["fleet"].domain.value == "sea"
    assert kinds["fleet"].days_per_step == {"sea": 3}
    assert kinds["fleet"].carries == ("army",)
    air = kinds["air_group"]
    assert air.domain.value == "air" and air.range_steps == 2
    assert set(air.days_per_step) == {"plain", "forest", "marsh", "mountain", "sea"}
    assert set(air.days_per_step.values()) == {1}
    envoy = kinds["envoy"]
    assert envoy.domain.value == "envoy" and set(envoy.days_per_step.values()) == {2}
    assert set(envoy.days_per_step) == set(air.days_per_step)


# ---------------------------------------------------------------- rule 4: bases and ports


def test_every_restated_place_keeps_the_worlds_name_and_coordinates(
    start: dict[str, Any], world: dict[str, Any]
) -> None:
    theirs = {str(e["key"]): e for e in world["entities"] if e["kind"] == "location"}
    for key, p in _places(start).items():
        EntityDecl.model_validate(p)
        if key in theirs:
            assert p["name"] == theirs[key]["name"]
            assert [float(c) for c in p["at"]] == [float(c) for c in theirs[key]["at"]]


def test_every_world_place_is_restated_with_its_area(
    start: dict[str, Any], world: dict[str, Any]
) -> None:
    theirs = {str(e["key"]) for e in world["entities"] if e["kind"] == "location"}
    assert theirs <= set(_places(start))


def test_each_place_lies_within_the_area_the_map_puts_it_in(
    start: dict[str, Any], raw: Any
) -> None:
    for key, p in _places(start).items():
        lat, lon = p["at"]
        inside, border = mc.locate(raw, float(lon), float(lat))
        assert not border, key
        assert inside == [p["within"]], key


def test_each_territorys_sites_are_its_places_within(
    start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    places = _places(start)
    for key, t in _territories(fragment).items():
        for site in t.get("sites") or []:
            assert places[site]["within"] == key


def test_every_base_in_the_code_table_is_a_site_with_base(start: dict[str, Any]) -> None:
    places = _places(start)
    letter = {"F": FeatureKind.FLEET, "A": FeatureKind.ARMY, "R": FeatureKind.AIR}
    domain = {letter[k]: v for k, v in DOMAIN_OF.items()}
    for key, base in BASES["autumn-1941"].items():
        site = places[key].get("base")
        assert site is not None, key
        assert set(site["sides"]) == set(base.sides), key
        assert set(site["domains"]) == {domain[k] for k in base.kinds}, key


def test_every_port_opens_on_a_sea_zone_its_territory_borders(
    start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    territories, zones, links = _territories(fragment), _zones(fragment), _links(fragment)
    ports = {k: p for k, p in _places(start).items() if p.get("port_on")}
    for key, p in ports.items():
        assert p["within"] in territories, key
        assert p["port_on"] in zones, key
        assert frozenset((p["within"], p["port_on"])) in links, key


def test_every_naval_base_on_land_is_a_port(
    start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    territories = _territories(fragment)
    for key, p in _places(start).items():
        base = p.get("base")
        if base is not None and "sea" in base["domains"] and p["within"] in territories:
            assert p.get("port_on"), key


PORTS = {
    "alexandria": "eastern_mediterranean",
    "tobruk": "eastern_mediterranean",
    "bardia": "eastern_mediterranean",
    "tripoli": "central_mediterranean",
    "taranto": "central_mediterranean",
    "malta": "central_mediterranean",
    "kure": "philippine_sea",
    "pearl_harbor_base": "central_pacific",
    "norfolk": "western_atlantic",
    "archangel": "white_sea",
    "leningrad": "baltic_sea",
}


@pytest.mark.parametrize(("place", "zone"), sorted(PORTS.items()))
def test_the_ports(start: dict[str, Any], place: str, zone: str) -> None:
    assert _places(start)[place]["port_on"] == zone


# ---------------------------------------------------------------- rule 5: existing forces


def _force(start: dict[str, Any], key: str) -> dict[str, Any]:
    return next(f for f in start["forces"] if f["key"] == key)


def test_every_existing_force_is_given_the_area_of_its_place(
    start: dict[str, Any], world: dict[str, Any]
) -> None:
    places, kinds = _places(start), _kinds(start)
    for key, f in _world_forces(world).items():
        mine = _force(start, key)
        assert mine["piece"] == PIECE_OF[FeatureKind(f["kind"])], key
        assert mine["side"] == f["side"], key
        domain = str(kinds[mine["piece"]]["domain"])
        assert mine["area"] == _stand_area(places[f["places"][0]], domain), key


def test_the_scripted_legs_are_restated_as_areas(
    start: dict[str, Any], world: dict[str, Any]
) -> None:
    places, kinds = _places(start), _kinds(start)
    for key, f in _world_forces(world).items():
        mine = _force(start, key)
        domain = str(kinds[mine["piece"]]["domain"])
        legs = [(str(leg["since"]), leg["places"][0]) for leg in f.get("legs") or []]
        assert [(str(leg["since"]), leg["area"]) for leg in mine.get("legs") or []] == [
            (since, _stand_area(places[place], domain)) for since, place in legs
        ], key


def test_the_combined_fleet_sails_from_hitokappu_bay_into_the_north_pacific(
    start: dict[str, Any],
) -> None:
    fleet = _force(start, "combined_fleet")
    assert fleet["area"] == "philippine_sea"
    assert fleet["legs"] == [{"since": date(1941, 11, 22), "area": "north_pacific"}]


# ---------------------------------------------------------------- rule 6: new forces

NEW = {
    "mediterranean_fleet": ("uk", "fleet", "alexandria", "eastern_mediterranean"),
    "western_desert_force": ("uk", "army", "alexandria", "egypt"),
    "italian_fleet": ("italy", "fleet", "taranto", "central_mediterranean"),
    "italian_army_libya": ("italy", "army", "tripoli", "tripolitania"),
    "afrika_korps": ("germany", "army", "bardia", "cyrenaica"),
    "ninth_war_area": ("china", "army", "changsha", "hunan"),
    "eleventh_army": ("japan", "army", "wuhan", "wuhan_area"),
}


def test_the_seven_new_forces(start: dict[str, Any], world: dict[str, Any]) -> None:
    features = {f.key: f for f in map(FeatureDecl.model_validate, start["features"])}
    assert set(features) == set(NEW)
    taken = {str(f["key"]) for f in world["features"]}
    for key, (side, piece, place, area) in NEW.items():
        f = features[key]
        assert key not in taken
        assert f.kind is FeatureKind.PIECE and f.piece == piece and f.side == side
        assert f.places == (place,)
        assert 1 <= f.tier <= 5 and f.gap
        mine = _force(start, key)
        assert (mine["side"], mine["piece"], mine["area"]) == (side, piece, area)


def test_the_eleventh_army_marches_on_changsha_and_back(start: dict[str, Any]) -> None:
    features = {str(f["key"]): f for f in start["features"]}
    legs = [(leg["since"], leg["places"]) for leg in features["eleventh_army"]["legs"]]
    assert legs == [(date(1941, 9, 17), ["changsha"]), (date(1941, 10, 6), ["wuhan"])]
    assert _force(start, "eleventh_army")["legs"] == [
        {"since": date(1941, 9, 17), "area": "hunan"},
        {"since": date(1941, 10, 6), "area": "wuhan_area"},
    ]


def test_every_force_is_listed_once(start: dict[str, Any], world: dict[str, Any]) -> None:
    keys = [str(f["key"]) for f in start["forces"]]
    assert len(keys) == len(set(keys))
    assert set(keys) == set(_world_forces(world)) | set(NEW)


# ---------------------------------------------------------------- rule 7: Tobruk and Bardia


def _check_the_desert(start: dict[str, Any]) -> None:
    assert _holder(start, "tobruk_area")["holder"] == "uk"
    assert _holder(start, "cyrenaica")["holder"] == "italy"
    assert _holder(start, "tobruk_area")["holder"] != _holder(start, "cyrenaica")["holder"]
    places = _places(start)
    assert places["tobruk"]["within"] == "tobruk_area" and places["bardia"]["within"] == "cyrenaica"
    assert places["tobruk"]["base"]["sides"] == ["uk"]
    assert places["bardia"]["base"]["sides"][0] == "italy"
    assert "uk" not in places["bardia"]["base"]["sides"]
    assert not any(f["area"] == "tobruk_area" for f in start["forces"])


def test_the_tobruk_enclave_is_british_and_cyrenaica_italian(start: dict[str, Any]) -> None:
    _check_the_desert(start)
