"""Autumn 1941's forces (reach R5): each major power fields three to six in the five theatres
the world had before the whole globe, each opens the game in reach of a base of its side and
kind, and the sides whose Atlantic figures read where their fleets are keep exactly the fleets
those figures were set against.

The forces of the new lands (WGN): the commands the record has there enter as pieces with their
side, place and tier, every nation nobody plays that the whole globe added fields a force in its
capital territory, and no force of the new lands stands in a territory its side does not hold.
"""

import json
from collections import Counter
from pathlib import Path

from revisionist.core.ontology import EntityKind
from revisionist.core.realism import kinds
from revisionist.core.realism.bases import Tier, area_reach
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.kinds import Domain
from revisionist.core.realism.resolvers.shipping import NORTH_ATLANTIC
from revisionist.core.world import FeatureDecl, WorldFile
from revisionist.engine import campaign as cmp
from tests.test_realism_resolvers import Rig, rig

MAJOR = ("usa", "uk", "ussr", "germany", "japan")
MAP = Path(__file__).resolve().parents[1] / "worlds" / "maps" / "autumn-1941.json"
OLD_REGIONS = {"eastern_front", "europe", "atlantic", "war_zone", "mediterranean", "pacific"}
"""The regions of the five theatres, before the world took in the whole globe."""
NEW_LAND = {"americas", "africa", "inner_asia", "australasia"}
"""The four regions of new land (WGD rule 3)."""

NEW_NATIONS = (
    "mexico_state",
    "guatemala",
    "venezuela",
    "peru",
    "brazil",
    "argentina",
    "chile_state",
    "free_france",
    "belgium",
    "ethiopia_state",
    "saudi_arabia",
    "liberia_state",
    "afghanistan_state",
    "tibet",
    "mongolia_state",
)
"""The nations the whole globe added (WGD), none of them played."""

NEW_FORCES: dict[str, tuple[str, str, str, int]] = {
    "india_command": ("uk", "new_delhi", "army", 3),
    "australian_home_forces": ("uk", "sydney", "army", 2),
    "east_indies_station": ("uk", "trincomalee", "fleet", 2),
    "south_atlantic_station": ("uk", "freetown", "fleet", 2),
    "far_eastern_front": ("ussr", "khabarovsk", "army", 3),
    "transbaikal_front": ("ussr", "chita", "army", 2),
    "central_asian_district": ("ussr", "tashkent", "army", 1),
    "gondar_garrison": ("italy", "gondar_town", "army", 2),
    "free_french_africa": ("free_france", "fort_lamy", "army", 1),
    "force_publique": ("belgium", "leopoldville", "army", 1),
    "ethiopian_army": ("ethiopia_state", "addis_ababa", "army", 1),
    "mexican_army": ("mexico_state", "mexico_city", "army", 1),
    "guatemalan_army": ("guatemala", "guatemala_city", "army", 1),
    "venezuelan_army": ("venezuela", "maracaibo", "army", 1),
    "peruvian_army": ("peru", "lima", "army", 1),
    "brazilian_army": ("brazil", "rio_de_janeiro", "army", 1),
    "argentine_army": ("argentina", "buenos_aires", "army", 1),
    "chilean_army": ("chile_state", "valparaiso", "army", 1),
    "saudi_army": ("saudi_arabia", "riyadh", "army", 1),
    "liberian_frontier_force": ("liberia_state", "monrovia", "army", 1),
    "afghan_army": ("afghanistan_state", "kabul", "army", 1),
    "tibetan_army": ("tibet", "lhasa", "army", 1),
    "mongolian_army": ("mongolia_state", "ulan_bator", "army", 1),
}
"""The forces of the new lands [proposed] (WGN rule 3): side, place, kind and tier. A nation the
record gives no strength for at the world's grain takes one piece of tier 1 in its capital
territory, a design value; the kinds are the world's own until the 1941 kinds item gives each
its kind."""


def forces(r: Rig) -> list[Feature]:
    return sorted(
        (f for f in r.state.features.values() if kinds.is_force(r.state, f)),
        key=lambda f: f.feature_id,
    )


def key_of(r: Rig, id_: str | None) -> str | None:
    return next((k for k, v in r.ids.items() if v == id_), None)


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def _pieces(world: WorldFile) -> list[FeatureDecl]:
    """The world's forces: every piece of a kind that fights (not an envoy)."""
    domains = {k.key: k.domain for k in world.piece_kinds}
    return [
        f
        for f in world.features
        if f.piece is not None and domains[f.piece] in (Domain.LAND, Domain.SEA, Domain.AIR)
    ]


def _area(world: WorldFile, place: str) -> str:
    """The territory or sea zone a place lies in; an area is its own."""
    within = {e.key: e.within for e in world.entities if e.kind is EntityKind.LOCATION}
    return within.get(place) or place


def _region(world: WorldFile, area: str) -> str:
    regions = {t.key: t.region for t in world.territories}
    regions |= {z.key: z.region for z in world.sea_zones}
    return regions[area]


def test_each_major_power_fields_three_to_six_forces_in_the_five_theatres() -> None:
    world = _world()
    count = Counter(
        f.side for f in _pieces(world) if _region(world, _area(world, f.places[0])) in OLD_REGIONS
    )
    assert {side: count[side] for side in MAJOR if not 3 <= count[side] <= 6} == {}


def test_every_force_opens_the_game_in_reach_of_a_base_of_its_side_and_kind() -> None:
    """At a base, but for the U-boat arm, on station in the mid-ocean gap and working from
    Lorient. The Soviet Western Front opens at Mozhaisk, in reach of Moscow (ITD)."""
    r = rig()
    tiers = {}
    for f in forces(r):
        got = area_reach(r.state, f, f.places[0])
        tiers[key_of(r, f.feature_id)] = None if got is None else got.tier
    assert [k for k, t in tiers.items() if t not in (Tier.SUSTAINED, Tier.OPERATE)] == []
    assert [k for k, t in tiers.items() if t is Tier.OPERATE] == ["uboat_arm"]


def test_the_forces_of_the_new_lands_enter_with_their_side_place_kind_and_tier() -> None:
    have = {f.key: f for f in _world().features}
    got = {
        k: (f.side, f.places[0], f.piece, f.tier)
        for k, f in have.items()
        if k in NEW_FORCES and f.side is not None and f.piece is not None
    }
    assert got == NEW_FORCES
    assert all(have[k].gap or have[k].source for k in NEW_FORCES)


def test_every_new_nation_fields_a_force_in_its_capital_territory() -> None:
    world = _world()
    capitals = {e.key: e.capital for e in world.entities if e.kind is EntityKind.POLITY}
    bare = []
    for n in NEW_NATIONS:
        capital = capitals[n]
        assert capital is not None, n
        home = _area(world, capital)
        if not [f for f in _pieces(world) if f.side == n and _area(world, f.places[0]) == home]:
            bare.append(n)
    assert bare == []


def test_no_force_of_the_new_lands_stands_in_a_territory_its_side_does_not_hold() -> None:
    """A fleet at a port stands in the port's territory's waters: its side holds the port."""
    world = _world()
    holders = {t.key: t.holder for t in world.territories}
    stray = []
    checked = set()
    for f in _pieces(world):
        area = _area(world, f.places[0])
        new = f.key in NEW_FORCES or f.side in NEW_NATIONS
        if not new and _region(world, area) not in NEW_LAND:
            continue
        checked.add(f.key)
        if holders.get(area) != f.side:
            stray.append((f.key, area, holders.get(area)))
    assert stray == []
    assert set(NEW_FORCES) <= checked


def test_the_forces_of_the_new_lands_are_pieces_in_the_game() -> None:
    r = rig()
    sides = Counter(key_of(r, f.side) for f in forces(r))
    assert {n: sides[n] for n in NEW_NATIONS if sides[n] < 1} == {}
    keys = {key_of(r, f.feature_id) for f in forces(r)}
    assert set(NEW_FORCES) <= keys


def _north_atlantic_zones() -> set[str]:
    """The sea zones whose label point lies in the shipping rule's North Atlantic."""
    (south, north), (west, east) = NORTH_ATLANTIC
    areas = json.loads(MAP.read_text())["areas"]
    return {
        k
        for k, a in areas.items()
        if south <= a["label"][1] <= north and west <= a["label"][0] <= east
    }


def test_the_sides_with_atlantic_figures_keep_only_their_own_atlantic_fleets() -> None:
    """U-boat losses run while a German fleet lies in the North Atlantic, and a US escort
    cuts them while a US fleet does; a second fleet there would keep either going after a
    player had sent the first away."""
    r = rig()
    zones = _north_atlantic_zones()
    atlantic = sorted(
        (key_of(r, f.side), key_of(r, f.feature_id))
        for f in forces(r)
        if kinds.domain(r.state, f) is Domain.SEA
        and key_of(r, f.side) in ("usa", "germany")
        and key_of(r, f.places[0]) in zones
    )
    assert atlantic == [("germany", "uboat_arm"), ("usa", "us_atlantic_fleet")]
