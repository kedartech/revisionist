"""Autumn 1941's forces (reach R5): each major power fields three to six in the five theatres
the world had before the whole globe, each opens the game in reach of a base of its side and
kind, and the sides whose Atlantic figures read where their fleets are keep exactly the fleets
those figures were set against.

The forces of the new lands (WGN): the commands the record has there enter as pieces with their
side, place and tier, every nation nobody plays that the whole globe added fields a force in its
capital territory, and no force of the new lands stands in a territory its side does not hold.
"""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

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
    "india_command": ("uk", "new_delhi", "infantry", 3),
    "australian_home_forces": ("uk", "sydney", "garrison", 2),
    "east_indies_station": ("uk", "trincomalee", "battle_fleet", 2),
    "south_atlantic_station": ("uk", "freetown", "battle_fleet", 2),
    "far_eastern_front": ("ussr", "khabarovsk", "infantry", 3),
    "transbaikal_front": ("ussr", "chita", "infantry", 2),
    "central_asian_district": ("ussr", "tashkent", "garrison", 1),
    "gondar_garrison": ("italy", "gondar_town", "garrison", 2),
    "free_french_africa": ("free_france", "fort_lamy", "garrison", 1),
    "force_publique": ("belgium", "leopoldville", "garrison", 1),
    "ethiopian_army": ("ethiopia_state", "addis_ababa", "garrison", 1),
    "mexican_army": ("mexico_state", "mexico_city", "garrison", 1),
    "guatemalan_army": ("guatemala", "guatemala_city", "garrison", 1),
    "venezuelan_army": ("venezuela", "maracaibo", "garrison", 1),
    "peruvian_army": ("peru", "lima", "garrison", 1),
    "brazilian_army": ("brazil", "rio_de_janeiro", "garrison", 1),
    "argentine_army": ("argentina", "buenos_aires", "garrison", 1),
    "chilean_army": ("chile_state", "valparaiso", "garrison", 1),
    "saudi_army": ("saudi_arabia", "riyadh", "garrison", 1),
    "liberian_frontier_force": ("liberia_state", "monrovia", "garrison", 1),
    "afghan_army": ("afghanistan_state", "kabul", "garrison", 1),
    "tibetan_army": ("tibet", "lhasa", "garrison", 1),
    "mongolian_army": ("mongolia_state", "ulan_bator", "garrison", 1),
}
"""The forces of the new lands [proposed] (WGN rule 3): side, place, kind and tier. A nation the
record gives no strength for at the world's grain takes one piece of tier 1 in its capital
territory, a design value, as a garrison (KDA rule 2)."""


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


def test_each_major_power_fields_three_to_six_formations_in_the_five_theatres() -> None:
    """A split formation's parts count as the one formation they were (KDA rule 3)."""
    world = _world()
    whole = {part: parent for parent, (_, parts) in SPLITS.items() for part in parts}
    count = Counter(
        f.side
        for f in _pieces(world)
        if _region(world, _area(world, f.places[0])) in OLD_REGIONS
        and whole.get(f.key, f.key) == f.key
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
    cuts them while a US fleet does; a fleet of another command there would keep either going
    after a player had sent his own away. The Atlantic Fleet's carrier division is a part of the
    one fleet (KDA), on the same cards: the escort runs until both are sent away."""
    r = rig()
    zones = _north_atlantic_zones()
    atlantic = sorted(
        (key_of(r, f.side), key_of(r, f.feature_id))
        for f in forces(r)
        if kinds.domain(r.state, f) is Domain.SEA
        and key_of(r, f.side) in ("usa", "germany")
        and key_of(r, f.places[0]) in zones
    )
    assert atlantic == [
        ("germany", "uboat_arm"),
        ("usa", "atlantic_fleet_carriers"),
        ("usa", "us_atlantic_fleet"),
    ]


# --- the 1941 kinds, the split formations (KDA) ------------------------------------------

KINDS = (
    "infantry",
    "armour",
    "garrison",
    "battle_fleet",
    "carrier_force",
    "submarines",
    "fighters",
    "bombers",
    "envoy",
)
"""The nine kinds of 1941 [proposed] (KDA rule 1), in the world file's order."""

PICTURES = {
    "infantry": "infantry",
    "armour": "armour",
    "garrison": "garrison",
    "battle_fleet": "battle_fleet",
    "carrier_force": "carrier",
    "submarines": "submarines",
    "fighters": "fighters",
    "bombers": "bombers",
    "envoy": "envoy",
}

FIGURE_KEYS = (
    "attack",
    "defence",
    "on_terrain",
    "against",
    "strike_steps",
    "covers",
    "may_attack",
    "holds_ground",
    "picture",
    "cost",
    "lead_days",
    "raised_at",
)
"""Every key a kind may carry for its figures and its raising (KFG rule 1)."""

SPLITS: dict[str, tuple[int, dict[str, tuple[str, str, int]]]] = {
    "army_group_centre": (
        5,
        {
            "army_group_centre": ("infantry", "smolensk", 3),
            "second_panzer_group": ("armour", "smolensk", 1),
            "third_panzer_group": ("armour", "smolensk", 1),
        },
    ),
    "combined_fleet": (
        5,
        {
            "combined_fleet": ("battle_fleet", "kure", 2),
            "first_air_fleet": ("carrier_force", "kure", 2),
            "sixth_fleet": ("submarines", "kure", 1),
        },
    ),
    "home_fleet": (
        4,
        {
            "home_fleet": ("battle_fleet", "scapa_flow", 3),
            "home_fleet_carrier": ("carrier_force", "scapa_flow", 1),
        },
    ),
    "mediterranean_fleet": (
        4,
        {
            "mediterranean_fleet": ("battle_fleet", "alexandria", 3),
            "tenth_submarine_flotilla": ("submarines", "alexandria", 1),
        },
    ),
    "us_atlantic_fleet": (
        4,
        {
            "us_atlantic_fleet": ("battle_fleet", "norfolk", 3),
            "atlantic_fleet_carriers": ("carrier_force", "norfolk", 1),
        },
    ),
    "us_pacific_fleet": (
        5,
        {
            "us_pacific_fleet": ("battle_fleet", "pearl_harbor_base", 3),
            "pacific_fleet_carriers": ("carrier_force", "pearl_harbor_base", 1),
            "pacific_submarine_force": ("submarines", "pearl_harbor_base", 1),
        },
    ),
    "baltic_fleet": (
        3,
        {
            "baltic_fleet": ("battle_fleet", "leningrad", 2),
            "baltic_submarines": ("submarines", "leningrad", 1),
        },
    ),
    "hawaiian_air_force": (
        3,
        {
            "hawaiian_air_force": ("fighters", "pearl_harbor_base", 2),
            "eighteenth_bombardment_wing": ("bombers", "pearl_harbor_base", 1),
        },
    ),
    "italian_army_libya": (
        3,
        {
            "italian_army_libya": ("infantry", "tripoli", 2),
            "xx_corps": ("armour", "bardia", 1),
        },
    ),
    "western_desert_force": (
        3,
        {
            "western_desert_force": ("infantry", "alexandria", 2),
            "tobruk_garrison": ("garrison", "tobruk", 1),
        },
    ),
}
"""The ten formations split where the record names their parts on 1 Sept 1941 [proposed] (KDA
rule 3; the formations draft's Table 2): each whole's strength, and each part's kind, place and
strength. A part stands at the base of its side and kind nearest where the record has it. The
parent's key stays with its largest part, so the cards and forms that name it still reach it."""

WHOLE = {
    "uboat_arm": "submarines",
    "soviet_western_front": "infantry",
    "hawaiian_department": "garrison",
    "western_approaches": "battle_fleet",
    "home_forces": "infantry",
    "bomber_command": "bombers",
    "replacement_army": "garrison",
    "luftwaffe_centre": "fighters",
    "general_defence_command": "garrison",
    "southern_army": "infantry",
    "eleventh_air_fleet": "bombers",
    "northern_fleet": "battle_fleet",
    "leningrad_front": "infantry",
    "italian_army": "infantry",
    "chinese_army": "infantry",
    "italian_fleet": "battle_fleet",
    "afrika_korps": "armour",
    "ninth_war_area": "infantry",
    "eleventh_army": "infantry",
    "finnish_army": "infantry",
    "moscow_mission": "envoy",
    "kurusu_mission": "envoy",
    **{k: v[2] for k, v in NEW_FORCES.items()},
}
"""Every piece that is not split, and its kind [proposed] (KDA rule 2)."""

SOURCED_PARTS = {
    "army_group_centre",
    "third_panzer_group",
    "combined_fleet",
    "first_air_fleet",
    "home_fleet",
    "home_fleet_carrier",
    "mediterranean_fleet",
    "tenth_submarine_flotilla",
    "hawaiian_air_force",
    "eighteenth_bombardment_wing",
    "xx_corps",
    "western_desert_force",
    "tobruk_garrison",
    "second_panzer_group",
}
"""The parts a source read names for a day or span that covers 1 Sept 1941; every other part's
source is for another date, or none was read. Every part's strength is a share [proposed], so
every part is `gap: true` and the source is its comment's line."""


def parts(whole: str) -> tuple[str, ...]:
    """A formation's pieces: the whole's own key first, then each part split from it (KDA);
    the key alone for a formation not split."""
    return tuple(SPLITS[whole][1]) if whole in SPLITS else (whole,)


def with_parts(*wholes: str) -> set[str]:
    """Every piece of each of ``wholes``."""
    return {k for w in wholes for k in parts(w)}


SPLIT_PARTS = frozenset(k for w in SPLITS for k in parts(w) if k != w)
"""The pieces the splits added, each its formation's part but not the key the whole kept."""


def _raw_kinds() -> list[dict[str, object]]:
    raw = yaml.safe_load((MAP.parents[1] / "autumn-1941.yaml").read_text())
    return list(raw["piece_kinds"])


def test_the_world_names_the_nine_kinds_each_with_every_key_and_its_picture() -> None:
    raw = _raw_kinds()
    assert [k["key"] for k in raw] == list(KINDS)
    assert {str(k["key"]): [f for f in FIGURE_KEYS if f not in k] for k in raw} == {
        k: [] for k in KINDS
    }
    assert {str(k["key"]): k["picture"] for k in raw} == PICTURES


LAND_DAYS = {"plain": 5, "forest": 7, "marsh": 7, "mountain": 10}
ANY_DAYS = ("plain", "forest", "marsh", "mountain", "sea")
FIGURES: dict[
    str, tuple[int, int, dict[str, int], str | None, tuple[int, int] | None, int | None]
] = {
    "infantry": (3, 3, LAND_DAYS, "land", (15, 3), 45),
    "armour": (5, 3, LAND_DAYS, "land", (25, 2), 75),
    "garrison": (1, 4, {"plain": 8, "forest": 10, "marsh": 10, "mountain": 14}, "land", (1, 3), 30),
    "battle_fleet": (4, 4, {"sea": 3}, "sea", (40, 3), 180),
    "carrier_force": (4, 2, {"sea": 3}, "sea", (40, 2), 180),
    "submarines": (3, 1, {"sea": 3}, "sea", (15, 1), 90),
    "fighters": (3, 4, dict.fromkeys(ANY_DAYS, 1), "air", (15, 1), 45),
    "bombers": (4, 2, dict.fromkeys(ANY_DAYS, 1), "air", (20, 1), 60),
    "envoy": (3, 3, dict.fromkeys(ANY_DAYS, 2), None, None, None),
}
"""Each kind's attack, defence, days a step, where it is raised, its cost in output and
manpower, and its lead days: design values [proposed], not history (KDA rule 1). A garrison
costs one output, so every nation that raises can pay for one in its first month. Armour moves
at the infantry's pace: a step is a region, and supply, not engines, set the pace at that
grain."""


def test_each_kind_takes_its_figures_from_the_table() -> None:
    def row(k: dict[str, Any]) -> tuple[object, ...]:
        cost = k.get("cost")
        paid = None if cost is None else (cost["output"], cost["manpower"])
        return (
            k["attack"],
            k["defence"],
            k["days_per_step"],
            k.get("raised_at"),
            paid,
            k.get("lead_days"),
        )

    assert {str(k["key"]): row(k) for k in _raw_kinds()} == FIGURES


def test_every_piece_takes_one_of_the_nine_kinds() -> None:
    world = _world()
    pieces = [f for f in world.features if f.kind.value == "piece"]
    assert [f.key for f in pieces if f.piece not in KINDS] == []
    expected = dict(WHOLE)
    for _, parts in SPLITS.values():
        expected |= {k: v[0] for k, v in parts.items()}
    assert {f.key: f.piece for f in pieces} == expected


def test_each_split_formation_has_its_parts_with_their_kind_place_and_strength() -> None:
    have = {f.key: f for f in _world().features}
    for _, parts in SPLITS.values():
        got = {k: (have[k].piece, have[k].places[0], have[k].tier) for k in parts if k in have}
        assert got == parts


def test_the_parts_of_each_split_sum_to_the_whole() -> None:
    have = {f.key: f for f in _world().features}
    sums = {p: sum(have[k].tier for k in parts if k in have) for p, (_, parts) in SPLITS.items()}
    assert sums == {p: whole for p, (whole, _) in SPLITS.items()}


def _comment_over(key: str) -> str:
    """The comment lines directly over a feature's line in the world file."""
    lines = (MAP.parents[1] / "autumn-1941.yaml").read_text().splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith(f"  - {{key: {key}, "))
    above = []
    for line in reversed(lines[:at]):
        if not line.strip().startswith("#"):
            break
        above.append(line.strip().lstrip("#").strip())
    return " ".join(reversed(above))


def test_the_split_parts_stand_for_their_side_and_carry_a_source_line_or_a_gap() -> None:
    world = _world()
    have = {f.key: f for f in world.features}
    sources = {s.key for s in world.sources}
    wrong = []
    for parent, (_, parts) in SPLITS.items():
        for k in parts:
            line = _comment_over(k)
            cited = re.findall(r"source: ([a-z0-9_]+)", line)
            ok = (
                have[k].side == have[parent].side
                and have[k].gap
                and "[proposed]" in line
                and (
                    bool(cited) and set(cited) <= sources
                    if k in SOURCED_PARTS
                    else "gap: true" in line
                )
            )
            if not ok:
                wrong.append(k)
    assert wrong == []


def test_the_forty_four_pieces_of_the_old_world_are_its_thirty_one_and_their_parts() -> None:
    world = _world()
    old = [
        f.key
        for f in world.features
        if f.kind.value == "piece" and f.key not in NEW_FORCES and f.key != "finnish_army"
    ]
    assert len(old) == 44
    assert len(old) - sum(len(parts) - 1 for _, parts in SPLITS.values()) == 31


def test_the_record_s_moves_go_with_the_parts_that_made_them() -> None:
    """Kiev falls to the Second Panzer Group; the whole army group steps to Mozhaisk; the
    concealed leg to Hitokappu Bay is the carrier striking force's alone."""
    have = {f.key: f for f in _world().features}

    def legs(key: str) -> list[tuple[str, tuple[str, ...], tuple[str, ...], bool]]:
        return [
            (str(g.since), tuple(g.places), tuple(g.takes), g.concealed) for g in have[key].legs
        ]

    assert legs("second_panzer_group") == [
        ("1941-09-19", ("smolensk",), ("kiev_area",), False),
        ("1941-09-30", ("mozhaisk",), (), False),
    ]
    for key in ("army_group_centre", "third_panzer_group"):
        assert legs(key) == [("1941-09-30", ("mozhaisk",), (), False)], key
    assert legs("first_air_fleet") == [("1941-11-22", ("hitokappu_bay",), (), True)]
    assert legs("combined_fleet") == [] and legs("sixth_fleet") == []


def test_a_card_that_commands_a_split_formation_commands_every_part() -> None:
    world = _world()
    short = []
    for card in world.cards:
        for domain in card.authority:
            named = set(domain.forces)
            for parent, (_, parts) in SPLITS.items():
                if parent in named and not set(parts) <= named:
                    short.append((card.person, domain.name, parent))
    assert short == []
