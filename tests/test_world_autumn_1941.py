"""The autumn-1941 realism world: it compiles, nobody is pre-seated, the playable cards
(the eight leaders and the military cards flagged playable by hand) are the roster, and every
figure is cited or a gap.

With ``playable_rule`` on (PBD), the roster is the cards the rule admits, which are the cards
flagged by hand: no card is held back, and taking the rule out leaves the scripted run as it
was.

The world takes in the whole globe (WGD): its map is the whole 1941 globe, and every territory,
sea zone and step of that map's staging world is in it, each new territory with the holder and
yields the globe's start and yields files give it, held from the first day like any other."""

import hashlib
import importlib.util
from collections import deque
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism import economy, supply, territory
from revisionist.core.realism.card import CardPath
from revisionist.core.realism.kinds import Domain, Role
from revisionist.core.realism.weather import Month
from revisionist.core.roster import claimable
from revisionist.core.state import Rule, State
from revisionist.core.world import LinkDecl, WorldFile
from revisionist.core.world_compile import WorldError, check_history, compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from tests import test_world_locks_1941 as locks_1941
from tests.test_rule_names import SHIPPED_1941

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "worlds" / "autumn-1941.yaml"
MAPS = ROOT / "worlds" / "maps"
GLOBE = MAPS / "src" / "autumn-1941-globe"
WHOLE_BOX = [-126, -60, 234, 84]
NEW_REGIONS = {
    "americas": "The Americas",
    "africa": "Africa and Arabia",
    "inner_asia": "India and Inner Asia",
    "australasia": "Australasia",
    "southern_seas": "The Southern and Polar Seas",
}
"""The four regions of new land [proposed] (WGD rule 3), and the region the globe's staging world
gives the new sea zones."""

LEADERS = {
    "roosevelt",
    "churchill",
    "stalin",
    "hitler",
    "konoe",
    "tojo",
    "mussolini",
    "chiang",
    "ryti",
}
"""The eight leaders, and Finland's President (NFI), a political card beside them. The
commanders the nation items add are read from the world file: each playable card beside
these is a military card flagged playable by hand."""

# Unsourced values a plan Josh approved puts in the world as [proposed], each marked
# gap: true until a source is named (sealift plan, section 3).
PROPOSED_VALUES = {
    "uk_sealift_grt": 300_000,
    "japan_sealift_grt": 200_000,
    "italy_sealift_grt": 150_000,
}

# Every value in the Phase 0b source note (SOURCES.md); a quantity may hold only these.
SOURCED_VALUES = {
    203,  # House, draft extension, yeas
    202,  # nays
    259,  # House, arming merchant ships
    138,
    50,  # Senate, Neutrality revision
    37,
    212,  # House concurrence
    194,
    66,  # Senate, 77th Congress
    28,
    2,
    267,  # House, 77th Congress
    162,
    5,
    5_985_000_000,  # second Lend-Lease appropriation, USD
    209_835,  # Allied merchant losses to U-boats, GRT: Sep, Oct, Nov
    176_622,
    120_541,
    19_433,  # US aircraft production, 1941
    103,  # US merchant ship deliveries, 1941
    1_159_765,  # DWT
    30,  # U-boats operational, Jul-Sep average
    55,  # Gallup, survey 6/26-7/1: about right
    57,  # Gallup 8 Oct: about right, too far, not far enough
    27,
    16,
    26,  # Gallup 22 Nov: for war on Germany, against
    63,
}


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def test_it_compiles_with_no_seat_and_a_clean_draft() -> None:
    world = _world()
    assert world.ruleset == "realism" and world.seats == ()
    assert check_history(world) == []
    state = replay(compile_world(world, CAMPAIGN, cmp.versions()))
    assert not state.seats and state.in_world_date == world.start_date


def test_the_playable_cards_are_the_roster() -> None:
    world = _world()
    playable = {c.person for c in world.cards if c.playable}
    commanders = {c.person for c in world.cards if c.playable and c.path is CardPath.MILITARY}
    assert len(playable) == len(world.roster)
    assert playable == LEADERS | commanders == {c.entity for c in world.roster}
    assert not LEADERS & commanders


def test_every_quantity_is_cited_a_gap_or_computed() -> None:
    world = _world()
    declared = {s.key for s in world.sources}
    for q in world.quantities:
        if q.computed:
            assert q.value is None and q.source is None and not q.gap, q.key
        elif q.gap:
            assert q.source is None and q.value == PROPOSED_VALUES.get(q.key), q.key
        else:
            assert q.source in declared and q.value is not None, q.key


def test_no_quantity_holds_a_value_outside_the_source_note() -> None:
    values = {q.key: q.value for q in _world().quantities if q.value is not None}
    stray = {k: v for k, v in values.items() if v not in SOURCED_VALUES}
    assert stray == PROPOSED_VALUES
    stray = {k: v for k, v in stray.items() if k not in PROPOSED_VALUES}
    assert not stray


def test_every_card_lever_names_a_resolver_and_a_card_pipeline() -> None:
    for c in _world().cards:
        assert all(lv.pipeline in c.pipelines for lv in c.levers), c.person
    # The Prime Minister's card holds twelve: the raising form (KDA) is his twelfth.
    assert all(2 <= len(c.levers) <= 12 for c in _world().cards if c.playable)


def test_every_playable_card_has_authority_or_a_rank() -> None:
    for c in _world().cards:
        if c.playable:
            assert c.authority or c.reach.rank > 0, c.person


def test_every_mandate_goes_to_a_playable_person() -> None:
    world = _world()
    playable = {c.person for c in world.cards if c.playable}
    assert world.mandates
    assert all(set(m.to) <= playable for m in world.mandates)
    assert playable <= {k for m in world.mandates for k in m.to}


def _open(world: WorldFile) -> set[str]:
    """The roster people a player may take in a new game of ``world``, by key."""
    keys = {v: k for k, v in resolve_keys(world, CAMPAIGN).items()}
    state = replay(compile_world(world, CAMPAIGN, cmp.versions()))
    return {keys[c.person] for c in claimable(state) if c.reason is None}


def _without_the_rule(world: WorldFile) -> WorldFile:
    return world.model_copy(
        update={"rules": tuple(r for r in world.rules if r != Rule.PLAYABLE_RULE)}
    )


def test_the_world_plays_by_the_playable_rule() -> None:
    assert Rule.PLAYABLE_RULE in _world().rules


def test_the_rule_admits_the_roster_the_hand_flags_made() -> None:
    world = _world()
    assert Rule.PLAYABLE_RULE in world.rules
    before, after = sorted(_open(_without_the_rule(world))), sorted(_open(world))
    print("\nby the hand flags   by the playable rule")
    for a, b in zip(before, after, strict=False):
        print(f"{a:<20}{b}")
    hand = {c.person for c in world.cards if c.playable}
    commanders = {c.person for c in world.cards if c.playable and c.path is CardPath.MILITARY}
    assert before == after == sorted(hand) == sorted(LEADERS | commanders)
    assert not any(c.held_back for c in world.cards)


def test_a_card_held_back_may_not_be_on_the_roster() -> None:
    world = _world()
    assert Rule.PLAYABLE_RULE in world.rules
    cards = tuple(c.model_copy(update={"held_back": c.person == "king"}) for c in world.cards)
    with pytest.raises(WorldError, match="character king: held back"):
        compile_world(world.model_copy(update={"cards": cards}), CAMPAIGN, cmp.versions())
    roster = tuple(c for c in world.roster if c.entity != "king")
    held = world.model_copy(update={"cards": cards, "roster": roster})
    assert _open(held) == {c.entity for c in roster}


def test_the_scripted_run_without_the_rule_is_the_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world()
    assert Rule.PLAYABLE_RULE in world.rules
    assert locks_1941.run_digest(_without_the_rule(world), monkeypatch) == SHIPPED_1941


def test_no_card_or_office_names_chiang_chairman_of_the_national_government() -> None:
    world = _world()
    chiang_offices = [c.office for c in world.cards if c.person == "chiang"]
    held = [a.name for a in world.assets if a.kind == "office" and a.controller == "chiang"]
    assert chiang_offices and held
    for title in chiang_offices + held:
        assert "National Government" not in title, title


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def _staging() -> Any:
    return _yaml(MAPS / "autumn-1941-globe.world.yaml")


def _old_staging() -> Any:
    return _yaml(MAPS / "autumn-1941.world.yaml")


def _load_map_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_check", ROOT / "scripts" / "map_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pairs(adjacency: list[Any]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for p in adjacency:
        a, b = (p["a"], p["b"]) if isinstance(p, dict) else p
        out.add((min(a, b), max(a, b)))
    return out


def _new_keys() -> tuple[list[str], list[str]]:
    """The globe's land territories and sea zones the old 1941 map did not have, in order."""
    old = _old_staging()
    had = {t["key"] for t in old["territories"]} | {z["key"] for z in old["sea_zones"]}
    g = _staging()
    return (
        [t["key"] for t in g["territories"] if t["key"] not in had],
        [z["key"] for z in g["sea_zones"] if z["key"] not in had],
    )


def _state() -> tuple[State, dict[str, str]]:
    world = _world()
    return replay(compile_world(world, CAMPAIGN, cmp.versions())), resolve_keys(world, CAMPAIGN)


def test_the_world_names_the_whole_globe_by_its_hash_and_box() -> None:
    world = _world()
    assert world.map is not None and world.map.file == "autumn-1941-globe.json"
    data = (MAPS / world.map.file).read_bytes()
    assert world.map.sha256 == hashlib.sha256(data).hexdigest()
    assert list(world.map.box or ()) == WHOLE_BOX
    assert _yaml(MAPS / world.map.file).get("cover") == "whole"


def test_the_strict_world_check_passes_and_the_world_is_converted() -> None:
    mc = _load_map_check()
    assert "autumn-1941" not in mc.NOT_WHOLE_YET
    assert [str(p) for p in mc.check_world(WORLD).problems] == []


def test_every_area_of_the_globe_is_in_the_world_as_its_staging_world_gives_it() -> None:
    world = _world()
    g = _staging()
    for decl, rows in ((world.territories, g["territories"]), (world.sea_zones, g["sea_zones"])):
        have = {d.key: d for d in decl}
        assert [r["key"] for r in rows] == [d.key for d in decl]
        for r in rows:
            d = have[r["key"]]
            got = (d.name, d.terrain, tuple(getattr(d, "sites", ())))
            assert got == (r["name"], r["terrain"], tuple(r.get("sites", ()))), r["key"]
    new_t, new_s = _new_keys()
    assert len(new_t) == 56 and len(new_s) == 22
    regions = {t["key"]: t["region"] for t in g["territories"] + g["sea_zones"]}
    placed = {d.key: d.region for d in world.territories} | {
        z.key: z.region for z in world.sea_zones
    }
    assert {k: placed[k] for k in new_t + new_s} == {k: regions[k] for k in new_t + new_s}


def test_the_old_areas_keep_their_regions() -> None:
    old = _old_staging()
    world = _world()
    placed = {d.key: d.region for d in world.territories} | {
        z.key: z.region for z in world.sea_zones
    }
    before = {r["key"]: r["region"] for r in old["territories"] + old["sea_zones"]}
    moved = {k: (v, placed[k]) for k, v in before.items() if placed[k] != v}
    assert moved == {
        "western_approaches_area": ("atlantic", "war_zone"),
        "mid_ocean_gap": ("atlantic", "war_zone"),
    }


def test_four_regions_of_new_land_and_the_southern_seas_are_added_to_the_five() -> None:
    regions = {r.key: r.name for r in _world().regions}
    assert {k: regions.get(k) for k in NEW_REGIONS} == NEW_REGIONS
    assert len(regions) == 6 + len(NEW_REGIONS)


def test_every_new_territory_has_the_holder_and_yields_the_globe_gives_it() -> None:
    world = _world()
    start, yields = _yaml(GLOBE / "start.yaml"), _yaml(GLOBE / "yields.yaml")
    holders = {h["territory"]: h["holder"] for h in start["holders"]}
    figures = {t["key"]: t for t in yields["territories"]}
    polities = {e.key for e in world.entities if e.kind is EntityKind.POLITY}
    have = {t.key: t for t in world.territories}
    new_t, _ = _new_keys()
    for key in new_t:
        t = have[key]
        assert t.holder == holders[key] and t.holder in polities, key
        assert t.yields == {r: figures[key][r]["amount"] for r in t.yields}, key
        assert set(t.yields) == {"industry", "manpower", "oil", "supply", "prestige"}, key
        assert t.gap, key


def test_every_new_nation_is_declared_with_a_capital_it_holds() -> None:
    world = _world()
    start = _yaml(GLOBE / "start.yaml")
    keys = {RENAMED.get(e["key"], e["key"]) for e in start["entities"]}
    assert keys - {e.key for e in world.entities} == set()
    holders = {t.key: t.holder for t in world.territories}
    within = {e.key: e.within for e in world.entities}
    new = [e for e in start["entities"] if e["kind"] == "polity"]
    declared = {e.key: e for e in world.entities if e.kind is EntityKind.POLITY}
    fresh = [e["key"] for e in new if e["key"] not in _OLD_POLITIES]
    assert len(fresh) == 15
    for key in fresh:
        e = declared[key]
        assert e.name and e.capital, key
        area = e.capital if e.capital in holders else within[e.capital]
        assert area is not None and holders[area] == key, key


def test_the_adjacency_is_the_globes_and_every_step_runs_both_ways() -> None:
    world = _world()
    listed = [(p.a, p.b) if isinstance(p, LinkDecl) else p for p in world.adjacency]
    pairs = {(min(a, b), max(a, b)) for a, b in listed}
    assert len(pairs) == len(listed)
    assert pairs == _pairs(_staging()["adjacency"])
    state, ids = _state()
    board = state.map
    assert board is not None
    keys = {v: k for k, v in ids.items()}
    steps = 0
    for domain, areas in ((Domain.LAND, board.territories), (Domain.SEA, board.sea_zones)):
        kind = {a.area for a in areas}
        for area in kind:
            for n in set(territory.neighbours(board, area, domain)) & kind:
                steps += 1
                assert area in territory.neighbours(board, n, domain), (keys[area], keys[n])
    assert steps > len(board.areas())


def _sea_path(state: State, ids: dict[str, str], a: str, b: str, avoid: set[str]) -> bool:
    board = state.map
    assert board is not None
    barred = {EntityId(ids[k]) for k in avoid}
    goal, seen = EntityId(ids[b]), {EntityId(ids[a])}
    queue = deque(seen)
    while queue:
        here = queue.popleft()
        if here == goal:
            return True
        for n in territory.neighbours(board, here, Domain.SEA):
            if n not in seen and n not in barred:
                seen.add(n)
                queue.append(n)
    return False


MEDITERRANEAN = {
    "western_mediterranean",
    "central_mediterranean",
    "eastern_mediterranean",
    "aegean_sea",
    "red_sea",
}


def test_the_sea_routes_of_the_record_are_steps() -> None:
    state, ids = _state()

    def path(a: str, b: str, avoid: set[str] | None = None) -> bool:
        return _sea_path(state, ids, a, b, avoid or set())

    # Round the Cape: the Cape waters join the South Atlantic to the Indian Ocean, and a fleet
    # reaches the Arabian Sea from the Western Approaches with the Mediterranean shut.
    assert {"south_atlantic_east", "western_indian_ocean"} <= _keys_near(state, ids, "cape_waters")
    assert path("western_approaches_area", "arabian_sea", MEDITERRANEAN)
    # Through the Red Sea to Suez.
    assert {"eastern_mediterranean", "arabian_sea"} <= _keys_near(state, ids, "red_sea")
    assert path("eastern_mediterranean", "arabian_sea", {"cape_waters"})
    # Across the Indian Ocean to Australia, clear of the seas of the Indies.
    assert "tasman_sea" in _keys_near(state, ids, "eastern_indian_ocean")
    assert path("arabian_sea", "tasman_sea", {"java_sea", "andaman_sea", "south_china_sea"})
    # Round Cape Horn: the western South Atlantic meets the waters off Chile, so the Pacific
    # coast is reached from the Caribbean with the Panama Canal shut.
    assert "chile_peru_waters" in _keys_near(state, ids, "south_atlantic_west")
    assert path("caribbean_sea", "chile_peru_waters", {"american_pacific"})


def _keys_near(state: State, ids: dict[str, str], area: str) -> set[str]:
    board = state.map
    assert board is not None
    keys = {v: k for k, v in ids.items()}
    return {keys[n] for n in territory.neighbours(board, EntityId(ids[area]), Domain.SEA)}


RENAMED = {"wake": "wake_island"}
"""Places the world keys apart from the globe's start: a key that is also a word the rules spell
(``tests/test_no_fixed_names.py``)."""

AT_WAR = ("uk", "ussr", "italy", "japan", "china", "free_france", "belgium", "ethiopia_state")
"""The holders of new territory at war on 1 September 1941 (the world's ``wars``)."""


def test_a_new_territory_held_by_a_nation_at_war_pays_and_supplies_it_from_the_first_day() -> None:
    world = _world()
    state, ids = _state()
    start = world.start_date
    assert start is not None
    new_t, _ = _new_keys()
    held = {t.key: t for t in world.territories}
    counted = [k for k in new_t if held[k].holder in AT_WAR]
    assert {held[k].holder for k in counted} == set(AT_WAR)
    for nation in AT_WAR:
        own = EntityId(ids[nation])
        mine = [t for t in world.territories if t.holder == nation]
        want = round(sum(t.yields.get("manpower", 0) for t in mine), 6)
        assert economy.income(state, own, Role.MANPOWER, start) == pytest.approx(want), nation
        sources = set(supply.sources(state, own, start))
        for k in counted:
            if held[k].holder == nation:
                assert EntityId(ids[k]) in sources, k


_OLD_POLITIES = {
    "usa",
    "uk",
    "japan",
    "germany",
    "italy",
    "ussr",
    "china",
    "french_state",
    "sweden",
    "spain",
    "portugal",
    "ireland_state",
    "finland_state",
    "hungary",
    "romania_state",
    "turkey_state",
    "iran_state",
    "thailand_state",
    "netherlands",
    "cuba",
    "switzerland",
}
"""The nations of the 1941 world before it took in the whole globe."""


# --- the nations and forces of the new lands (WGN) --------------------------------------

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
"""The nations the whole globe added (WGD), completed here as polities nobody plays."""

AT_WAR_WITH = {
    "free_france": {"germany", "italy"},
    "belgium": {"germany", "italy"},
    "ethiopia_state": {"italy"},
}
"""Each new nation's wars on 1 September 1941; every other new nation is at peace with all."""


def _enemies(state: State, ids: dict[str, str], nation: str) -> set[str]:
    keys = {v: k for k, v in ids.items()}
    me = ids[nation]
    out: set[str] = set()
    for w in state.wars.values():
        if me in (w.a, w.b):
            out.add(keys[w.b if w.a == me else w.a])
    return out


def test_each_new_nation_stands_to_the_wars_as_the_record_gives_it() -> None:
    world = _world()
    state, ids = _state()
    got = {n: _enemies(state, ids, n) for n in NEW_NATIONS}
    assert got == {n: AT_WAR_WITH.get(n, set()) for n in NEW_NATIONS}
    theirs = [w for w in world.wars if {w.a, w.b} & set(NEW_NATIONS)]
    assert len(theirs) == sum(len(v) for v in AT_WAR_WITH.values())


def test_mongolia_and_the_soviet_union_are_bound_by_their_protocol() -> None:
    """The protocol of 1936 bound each to help the other if attacked. Its wording is kept as an
    unchecked clause: the typed defence clause calls a party at every attack, and Mongolia
    stayed out of the war with Germany."""
    world = _world()
    (pact,) = [p for p in world.pacts if set(p.parties) & set(NEW_NATIONS)]
    assert set(pact.parties) == {"ussr", "mongolia_state"} and pact.public
    assert pact.source in {s.key for s in world.sources}
    assert {(c.type.value, c.binds) for c in pact.clauses} == {
        ("unchecked", "ussr"),
        ("unchecked", "mongolia_state"),
    }
    state, ids = _state()
    made = [a for a in state.agreements.made.values() if ids["mongolia_state"] in a.parties]
    assert [set(a.parties) for a in made] == [{ids["ussr"], ids["mongolia_state"]}]


def test_a_new_nation_is_one_nobody_plays_as_the_neutrals_of_today_are() -> None:
    """No card, no roster place, no person, no groups, no intelligence and no relationship: a
    seat's dealings with it are by its wars and pacts alone, as with Sweden or Turkey."""
    world = _world()
    new = set(NEW_NATIONS)
    parents = {e.key: e.parent for e in world.entities}
    people = {e.key for e in world.entities if e.kind is EntityKind.PERSON}

    def nation_of(key: str | None) -> str | None:
        while key is not None and key not in new:
            key = parents.get(key)
        return key

    assert [p for p in people if nation_of(p)] == []
    assert [c.person for c in world.cards if nation_of(c.person)] == []
    assert [g.nation for g in world.groups if g.nation in new] == []
    assert [i.nation for i in world.intelligence if i.nation in new] == []
    assert not {r.a for r in world.relationships} & new
    assert not {r.b for r in world.relationships} & new


def test_a_declaration_of_war_on_a_new_nation_moves_the_declaring_nations_groups() -> None:
    from revisionist.core import events as ev
    from revisionist.core.realism import groups
    from revisionist.core.realism.war import War, war_id_for

    state, ids = _state()
    usa, mexico = EntityId(ids["usa"]), EntityId(ids["mexico_state"])
    day = state.in_world_date
    assert day is not None
    war = War(war_id=war_id_for(usa, mexico), a=usa, b=mexico, since=day, declared_by=usa)
    moved = groups.react(state, state, [ev.WarDeclared(war=war)], day)
    named = {g.key for g in groups.of(state, usa) if g.moved_by.get(groups.Happening.WAR_DECLARED)}
    assert named
    assert {m.group for m in moved if m.polity == usa} == named
    assert all(m.cause.value == "war_declared" for m in moved)
    assert [m for m in moved if m.polity == mexico] == []


FOG_SEATS = ("roosevelt", "churchill", "stalin", "hitler", "tojo", "mussolini", "chiang", "ryti")
"""One playable person of each playable nation."""


def _views(world: WorldFile) -> dict[str, str]:
    from revisionist.core import events as ev
    from revisionist.core.fold import apply
    from revisionist.core.ids import EventId, SeatId, derived_id
    from revisionist.core.project import project
    from revisionist.core.visibility import PUBLIC

    ids = resolve_keys(world, CAMPAIGN)
    events = compile_world(world, CAMPAIGN, cmp.versions())
    base = replay(events)
    out: dict[str, str] = {}
    for who in FOG_SEATS:
        seat = SeatId(derived_id(CAMPAIGN, "seat", who))
        claim = ev.Event(
            event_id=EventId(derived_id(CAMPAIGN, "test-event", len(events))),
            campaign_id=CAMPAIGN,
            seq=len(events),
            tick=0,
            scope=PUBLIC,
            payload=ev.CharacterClaimed(seat_id=seat, entity_id=EntityId(ids[who])),
            versions=cmp.versions(),
        )
        out[who] = project(apply(base, claim), seat).model_dump_json()
    return out


def test_a_new_nations_private_state_reaches_no_seat() -> None:
    """Two games that differ only in which territory Mexico's army stands in and how strong it
    is, and in the strength of Free France's force in Africa, read the same to every playable
    nation."""
    world = _world()
    moved = {"mexican_army": ("guatemala_city", 3), "free_french_africa": ("brazzaville", 2)}
    features = []
    for f in world.features:
        if f.key in moved:
            place, tier = moved[f.key]
            assert (f.places[0], f.tier) != (place, tier), f.key
            f = f.model_copy(update={"places": (place,), "tier": tier})
        features.append(f)
    assert set(moved) <= {f.key for f in world.features}
    twin = world.model_copy(update={"features": tuple(features)})
    a, b = _views(world), _views(twin)
    assert [who for who in FOG_SEATS if a[who] != b[who]] == []


# --- the kinds, the weather and raising (KDA) ---------------------------------------------

PIECE_SWITCHES = (Rule.KINDS_IN_BATTLE, Rule.WEATHER, Rule.RAISING)
"""The three piece rules (KSW)."""

SEASON: tuple[Month, ...] = ("sep", "oct", "nov", "dec")
WEATHER = {
    "eastern_front": ("clear", "mud", "frost", "deep_winter"),
    "europe": ("clear", "storms_at_sea", "storms_at_sea", "storms_at_sea"),
    "atlantic": ("clear", "storms_at_sea", "storms_at_sea", "storms_at_sea"),
    "war_zone": ("clear", "storms_at_sea", "storms_at_sea", "storms_at_sea"),
    "mediterranean": ("clear", "clear", "clear", "clear"),
    "pacific": ("monsoon_rain", "monsoon_rain", "clear", "clear"),
    "americas": ("clear", "clear", "clear", "clear"),
    "africa": ("monsoon_rain", "clear", "clear", "clear"),
    "inner_asia": ("monsoon_rain", "clear", "clear", "clear"),
    "australasia": ("clear", "clear", "clear", "monsoon_rain"),
    "southern_seas": ("clear", "clear", "clear", "clear"),
}
"""The weather of the season by region, September to December (KDA rule 4; the formations
draft's grid). The region named China follows Burma, where the monsoon ends in late October."""

RAISERS = {
    "churchill": "cos_directive",
    "stalin": "gko_decree",
    "hitler": "okw_directive",
    "konoe": "japan_state_policy",
    "tojo": "japan_state_policy",
    "mussolini": "comando_supremo_order",
    "chiang": "mac_order",
}
"""The people who hold production today, and the pipeline of their production form (KDA rule
5)."""


def _switched(world: WorldFile) -> WorldFile:
    """The world with the three piece rules on, whether or not it ships with them."""
    rules = tuple(world.rules) + tuple(r for r in PIECE_SWITCHES if r not in world.rules)
    return world.model_copy(update={"rules": rules})


def test_every_region_has_its_season_of_weather_and_every_month() -> None:
    weather = _world().weather
    assert weather is not None
    rows = {r: tuple(m[s] for s in SEASON) for r, m in weather.regions.items()}
    assert rows == WEATHER
    assert all(len(m) == 12 for m in weather.regions.values())


def _sky() -> tuple[Any, dict[str, str], State]:
    from revisionist.core.realism import weather

    world = _switched(_world())
    state = replay(compile_world(world, CAMPAIGN, cmp.versions()))
    sky = weather.sky(state)
    assert sky is not None
    return sky, resolve_keys(world, CAMPAIGN), state


@pytest.mark.parametrize(
    ("area", "day", "kind", "added"),
    [
        ("moscow_area", "1941-09-30", "armour", 0),
        ("moscow_area", "1941-10-01", "armour", 5),
        ("moscow_area", "1941-10-01", "infantry", 3),
        ("moscow_area", "1941-11-15", "armour", 0),
        ("moscow_area", "1941-12-10", "infantry", 2),
        ("western_atlantic", "1941-09-20", "battle_fleet", 0),
        ("western_atlantic", "1941-11-20", "battle_fleet", 1),
        ("mid_ocean_gap", "1941-11-20", "submarines", 1),
        ("burma", "1941-10-20", "infantry", 2),
        ("burma", "1941-11-02", "infantry", 0),
        ("hunan", "1941-09-20", "infantry", 2),
        ("hunan", "1941-11-20", "infantry", 0),
        ("western_mediterranean", "1941-11-20", "battle_fleet", 0),
    ],
)
def test_the_weather_adds_days_to_a_step_by_region_month_and_kind(
    area: str, day: str, kind: str, added: int
) -> None:
    from datetime import date

    sky, ids, state = _sky()
    assert state.kinds is not None
    got = sky.step(state.kinds.pieces[kind], EntityId(ids[area]), date.fromisoformat(day))
    assert got == added


def test_the_eastern_winter_grounds_the_air_and_the_autumn_mud_blunts_armour() -> None:
    from datetime import date

    sky, ids, state = _sky()
    assert state.kinds is not None
    moscow = EntityId(ids["moscow_area"])
    assert sky.grounded(moscow, date(1941, 12, 10))
    assert not sky.grounded(moscow, date(1941, 11, 10))
    armour = state.kinds.pieces["armour"]
    assert [c.attack for c in sky.shift(armour, moscow, date(1941, 10, 10))] == [-1]
    assert sky.shift(armour, moscow, date(1941, 9, 10)) == ()


class _Seated:
    """The world with the piece rules on, compiled and folded, one person seated at a time."""

    def __init__(self) -> None:
        from tests.test_realism_resolvers import Rig

        world = _switched(_world())

        class Switched(Rig):
            def __init__(self) -> None:
                self.campaign = CAMPAIGN
                self.ids = resolve_keys(world, CAMPAIGN)
                events = compile_world(world, CAMPAIGN, cmp.versions())
                self.state = replay(events)
                self.seq = len(events)
                self.seats = {}
                self.n_orders = 0

        self.rig = Switched()
        self.world = world


def test_each_holder_of_production_has_a_form_to_raise_a_piece() -> None:
    cards = {c.person: c for c in _world().cards}
    for person, pipeline in RAISERS.items():
        form = next((x for x in cards[person].levers if x.name == "raise_piece"), None)
        assert form is not None, person
        # the economy resolver's order raises, as Salt Strait's form does (RNC)
        assert (form.resolver, form.pipeline) == ("economy", pipeline), person
        assert {p.name for p in form.params} == {"kind", "place"}, person


def test_every_kind_and_place_a_raising_form_offers_can_be_ordered_on_the_first_day() -> None:
    """Each kind a form offers can be raised at one of its places on 1 Sept, and each place
    takes one of its kinds: the form offers nothing the rules refuse (KSC)."""
    from revisionist.core.realism.resolvers import production

    seated = _Seated()
    cards = {c.person: c for c in seated.world.cards}
    idle = []
    for person in RAISERS:
        seat = seated.rig.seat(person)
        form = next(x for x in cards[person].levers if x.name == "raise_piece")
        params = {p.name: p for p in form.params}
        ok = {
            (kind, place)
            for kind in params["kind"].choices
            for place in params["place"].choices
            if not production.raise_refusal(
                seated.rig.state, seat, "raise_piece", {"kind": kind, "place": place}
            )
        }
        idle += [(person, k) for k in params["kind"].choices if k not in {k for k, _ in ok}]
        idle += [(person, p) for p in params["place"].choices if p not in {p for _, p in ok}]
    assert idle == []


def test_every_kind_but_the_envoy_is_raised_at_a_base_of_its_domain() -> None:
    raised = {
        k.key: (k.raised_at, k.cost is not None, k.lead_days is not None)
        for k in _world().piece_kinds
    }
    assert raised.pop("envoy") == (None, False, False)
    domains = {k.key: k.domain.value for k in _world().piece_kinds}
    assert {k: v for k, v in raised.items() if v != (domains[k], True, True)} == {}
