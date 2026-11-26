"""Autumn 1941 as a territory world for new games (FLP).

The world file names its map, terrain, piece kinds, territories, sea zones and wars, and switches on
the territory rules. Every place lies in exactly one area and says which (`within`), every force
is a piece standing in an area, every destination a form offers still resolves to an area,
and the opening has the Tobruk enclave British and Cyrenaica Italian, each base serving its holder
only, with a British land piece in the enclave supplied by its port. The old world, places only, is
frozen at tests/worlds/autumn-1941-points.yaml for the tests that pin movement between points.
"""

import importlib.util
from datetime import date
from pathlib import Path
from types import ModuleType

import yaml

from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism import holders, kinds, supply, territory
from revisionist.core.realism.geography import Feature, FeatureKind
from revisionist.core.state import Rule
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from tests.test_realism_resolvers import CAMPAIGN, Rig

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "worlds" / "autumn-1941.yaml"
POINTS = ROOT / "tests" / "worlds" / "autumn-1941-points.yaml"
START = ROOT / "worlds" / "maps" / "src" / "autumn-1941" / "start.yaml"


def _load_map_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_check", ROOT / "scripts" / "map_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mc = _load_map_check()


def world() -> WorldFile:
    return cmp.load_world(WORLD)


def key_of(r: Rig, id_: str | None) -> str | None:
    return next((k for k, v in r.ids.items() if v == id_), None)


def test_the_world_switches_on_the_territory_rules() -> None:
    assert [str(r) for r in world().rules] == [
        "territories",
        "holders",
        "economy",
        "supply",
        "fuel",
        "aid",
        "battles",
        "reports",
        "agreements",
        "conference",
        "groups",
        "contests",
        "aims",
        "command",
        "locks",
        "own_aim",
        "laws",
        "ask_answers",
        "deciders",
        "offers",
        "classes",
        "losses",
        "places",
        "posts",
        "office",
        "defiance",
        "peace",
        "playable_rule",
    ]
    assert Rig().state.rules == frozenset(
        {
            Rule.TERRITORIES,
            Rule.HOLDERS,
            Rule.ECONOMY,
            Rule.SUPPLY,
            Rule.FUEL,
            Rule.AID,
            Rule.BATTLES,
            Rule.REPORTS,
            Rule.AGREEMENTS,
            Rule.CONFERENCE,
            Rule.GROUPS,
            Rule.CONTESTS,
            Rule.AIMS,
            Rule.COMMAND,
            Rule.LOCKS,
            Rule.OWN_AIM,
            Rule.LAWS,
            Rule.ASK_ANSWERS,
            Rule.DECIDERS,
            Rule.OFFERS,
            Rule.CLASSES,
            Rule.LOSSES,
            Rule.PLACES,
            Rule.POSTS,
            Rule.OFFICE,
            Rule.DEFIANCE,
            Rule.PEACE,
            Rule.PLAYABLE_RULE,
        }
    )


def test_the_world_names_its_map_and_the_bytes_match() -> None:
    w = world()
    assert w.map is not None and w.map.coords == "lonlat" and w.map.file == "autumn-1941.json"
    assert w.map_data is not None
    assert len(w.territories) > 50 and len(w.sea_zones) > 20


def test_the_strict_global_check_passes_with_every_original_place() -> None:
    report = mc.check_world(WORLD)
    assert [str(p) for p in report.problems] == []
    old = {d.key for d in cmp.load_world(POINTS).entities if d.at is not None}
    now = {d.key for d in world().entities if d.at is not None}
    assert old <= now


def test_every_place_says_which_area_it_lies_within() -> None:
    w = world()
    areas = {t.key for t in w.territories} | {z.key for z in w.sea_zones}
    placed = [d for d in w.entities if d.kind is EntityKind.LOCATION and d.at is not None]
    assert [d.key for d in placed if d.within not in areas] == []


def _missing_within(w: WorldFile) -> list[str]:
    return [
        d.key
        for d in w.entities
        if d.kind is EntityKind.LOCATION and d.at is not None and d.within is None
    ]


def test_no_place_lacks_within() -> None:
    assert _missing_within(world()) == []


def _forces(r: Rig) -> list[Feature]:
    return sorted(
        (f for f in r.state.features.values() if kinds.is_force(r.state, f)),
        key=lambda f: f.feature_id,
    )


def test_every_force_is_a_piece_standing_in_an_area() -> None:
    r = Rig()
    board = r.state.map
    assert board is not None
    areas = set(board.areas())
    forces = _forces(r)
    assert len(forces) == 30
    assert [key_of(r, f.feature_id) for f in forces if f.kind is not FeatureKind.PIECE] == []
    assert [key_of(r, f.feature_id) for f in forces if f.places[0] not in areas] == []


def _start_areas() -> dict[str, tuple[str, list[str]]]:
    """Each force's area at the start and its legs' areas, as the 1941 start stages them."""
    doc = yaml.safe_load(START.read_text())
    return {
        f["key"]: (f["area"], [leg["area"] for leg in f.get("legs") or []]) for f in doc["forces"]
    }


ON_STATION = {"uboat_arm": "mid_ocean_gap", "soviet_western_front": "moscow_area"}
"""Forces the world puts somewhere other than the start's base area: the U-boat arm opens on
station across the convoy routes, working from Lorient, so the scripted season sinks ships;
the Soviet Western Front opens at Mozhaisk, since with battles on a front at Vyazma, in the
Smolensk area with Army Group Centre, would open a battle on the first day (ITD)."""

LEGS = {"soviet_western_front": ["moscow_area"]}
"""Scripted legs the world changes from the start's: the Western Front's leg to Mozhaisk is its
start now (ITD)."""


def test_every_force_stands_in_the_area_the_start_gives_it() -> None:
    r = Rig()
    want = _start_areas()
    got = {}
    for f in _forces(r):
        key = key_of(r, f.feature_id)
        assert key is not None
        got[key] = key_of(r, f.places[0])
    assert got == {k: ON_STATION.get(k, area) for k, (area, _) in want.items()}


def test_every_existing_force_is_still_a_force() -> None:
    old = cmp.load_world(POINTS)
    moved = {
        f.key
        for f in old.features
        if f.kind in (FeatureKind.ARMY, FeatureKind.FLEET, FeatureKind.AIR)
    }
    assert moved <= set(_start_areas())
    assert len(moved) == 22


def test_each_scripted_leg_lands_in_the_area_the_start_gives_it() -> None:
    r = Rig()
    want = _start_areas()
    for f in _forces(r):
        key = key_of(r, f.feature_id)
        assert key is not None
        domain = kinds.domain(r.state, f)
        assert domain is not None
        legs = [key_of(r, territory.area_of(r.state, leg.places[0], domain)) for leg in f.legs]
        assert legs == LEGS.get(key, want[key][1]), key


def test_every_destination_a_form_offers_resolves_to_an_area() -> None:
    r = Rig()
    by_key = {key_of(r, f.feature_id): f for f in _forces(r)}
    lost = []
    for c in world().cards:
        for lv in c.levers:
            if lv.resolver != "movement":
                continue
            params = {p.name: p for p in lv.params}
            for force in params["force"].choices or ():
                piece = by_key[force]
                domain = kinds.domain(r.state, piece)
                assert domain is not None
                for to in params["to"].choices or ():
                    if territory.area_of(r.state, EntityId(r.ids[to]), domain) is None:
                        lost.append((c.person, lv.name, force, to))
    assert lost == []


def test_the_world_compiles_and_every_key_of_the_old_world_is_kept() -> None:
    old = cmp.load_world(POINTS)
    new = world()
    old_keys = set(resolve_keys(old, CAMPAIGN))
    assert old_keys - set(resolve_keys(new, CAMPAIGN)) == set()
    compile_world(new, CAMPAIGN, cmp.versions())


def _entity(r: Rig, key: str) -> EntityId:
    return EntityId(r.ids[key])


def test_the_tobruk_enclave_is_british_and_cyrenaica_italian() -> None:
    r = Rig()
    assert holders.holder(r.state, _entity(r, "tobruk_area")) == _entity(r, "uk")
    assert holders.holder(r.state, _entity(r, "cyrenaica")) == _entity(r, "italy")


def test_each_libyan_base_serves_its_holder_only() -> None:
    r = Rig()
    board = r.state.map
    assert board is not None
    base = {b.place: b for b in board.bases}
    tobruk, bardia = base[_entity(r, "tobruk")], base[_entity(r, "bardia")]
    uk, italy, germany = _entity(r, "uk"), _entity(r, "italy"), _entity(r, "germany")
    assert holders.serves(r.state, tobruk, uk)
    assert not holders.serves(r.state, tobruk, italy)
    assert not holders.serves(r.state, tobruk, germany)
    assert holders.serves(r.state, bardia, italy)
    assert not holders.serves(r.state, bardia, uk)


def test_a_british_land_piece_in_the_enclave_is_in_supply_by_its_port() -> None:
    r = Rig()
    force = next(
        f for f in r.state.features.values() if key_of(r, f.feature_id) == "western_desert_force"
    )
    there = force.model_copy(
        update={"places": (_entity(r, "tobruk_area"),), "as_of": date(1941, 9, 1)}
    )
    r.fold_changes((there,))
    got = supply.status(r.state, r.state.features[FeatureId(force.feature_id)])
    assert got is not None and got.supplied and got.source is not None
    assert got.source in (_entity(r, "tobruk_area"), _entity(r, "tobruk"))


def test_the_old_world_has_no_map_and_no_rules() -> None:
    old = cmp.load_world(POINTS)
    assert old.map is None and old.rules == () and old.territories == ()
