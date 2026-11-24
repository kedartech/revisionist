"""The Civil War world on 1 September 1862 (CWW): the two nations as they stood that day,
their forces as tiers, the people who held the posts, who decides what, and the groups at
home; every territory outside the two nations held by a nation nobody plays.

``worlds/civil-war-1862.yaml`` reads the map built from the recipe
(``worlds/maps/civil-war-1862.json``) and copies its areas and borders unchanged. Every
person is a real one with a source in the dossier; a figure with no source is marked
``gap: true``. No rule file changes: what the world cannot say is a finding against the
template, kept in ``FINDINGS`` below and in the world file's notes.
"""

import copy
import importlib.util
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from revisionist.core import goals
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, SeatId, derived_id
from revisionist.core.realism.groups import ABANDONED_TIMES
from revisionist.core.state import MODEL_READ_RULES, Rule
from revisionist.core.world import CardDecl, WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import session_zero
from revisionist.engine.store import MemoryStore, load_state

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "worlds" / "civil-war-1862.yaml"
FRAGMENT = ROOT / "worlds" / "maps" / "civil-war-1862.world.yaml"
DOSSIER = ROOT / "worlds" / "dossiers" / "civil-war-1862.yaml"
TEMPLATE = ROOT / "worlds" / "TEMPLATE.md"
CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
START = date(1862, 9, 1)
SIDES = ("usa", "csa")
UNBUILT = {Rule.AIDE_NOTE, Rule.PEACE, Rule.POST_VIEW}
"""Rules no code reads yet: a shipped world names a rule only once its reader is built."""
RULES = set(Rule) - {Rule.PLAYABLE_RULE} - set(MODEL_READ_RULES) - UNBUILT
"""Every rule on except the playable rule, whose report goes to Josh first, the three read
by a live model, and those no code reads yet."""
UNHELD = {
    "central_america",
    "caribbean",
    "new_granada",
    "brazil_guianas",
    "andes",
    "la_plata",
    "iberia",
    "german_states",
    "scandinavia",
    "italy",
    "balkans",
    "arabia_persia",
    "central_asia",
    "north_africa",
    "west_central_africa",
    "east_africa",
    "southern_africa",
    "china",
    "southeast_asia",
    "pacific_islands",
}
"""Map territories that join the lands of several holders: a territory has one holder, so
these stand with none (a finding against the template)."""
NOT_STRESSED = (
    "Who pays each armed body, and who each answers to",
    "Whether the government's seat moves with a named person or body",
    "The outlets of public word: whom each answers to and its voice",
)
"""The three lines the template says this world cannot stress: armies paid by their
commander, a world with no press, and a seat that moves with a person. Each is absent on
purpose."""
FINDINGS = (
    "Occupation inside a territory",
    "A territory that joins the lands of several holders",
    "Forces raised by the states",
    "A nation that broke in two",
    "Ports on a coarse coastline",
)
"""What the world cannot say with the keys that exist, each written into the template."""


def _world_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "world_check", ROOT / "scripts" / "world_check.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _map_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_check", ROOT / "scripts" / "map_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(WORLD.read_text())
    return data


def world() -> WorldFile:
    return cmp.load_world(WORLD)


def polities(w: dict[str, Any]) -> set[str]:
    return {e["key"] for e in w["entities"] if e["kind"] == "polity"}


def people(w: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["key"]: e for e in w["entities"] if e["kind"] == "person"}


def holders(w: dict[str, Any]) -> dict[str, str | None]:
    return {t["key"]: t.get("holder") for t in w["territories"]}


def stand_area(w: dict[str, Any], feature: dict[str, Any]) -> str | None:
    """The area a force stands in: a fleet the zone its port opens on, else the territory
    its place lies within."""
    place = next(e for e in w["entities"] if e["key"] == feature["places"][0])
    key = "port_on" if feature["piece"] == "fleet" else "within"
    area: str | None = place.get(key)
    return area


def off_ground(w: dict[str, Any]) -> list[str]:
    """Forces standing outside their side's ground. A side's ground is the territory it
    holds and the territory bordering it: the front a field army stands on. A fleet's is
    any sea zone."""
    held = holders(w)
    zones = {z["key"] for z in w["sea_zones"]}
    beside: dict[str, set[str]] = {}
    for pair in w["adjacency"]:
        a, b = (pair["a"], pair["b"]) if isinstance(pair, dict) else pair[:2]
        beside.setdefault(a, set()).add(b)
        beside.setdefault(b, set()).add(a)
    wrong = []
    for f in w["features"]:
        area = stand_area(w, f)
        if f["piece"] == "fleet":
            if area not in zones:
                wrong.append(f["key"])
            continue
        own = {t for t, h in held.items() if h == f["side"]}
        if area is None or (area not in own and not beside.get(area, set()) & own):
            wrong.append(f["key"])
    return wrong


def stressed(w: WorldFile) -> list[str]:
    """The lines this world cannot stress that it answers all the same."""
    check = _world_check()
    lines = check.check(w, check.parse_template(TEMPLATE.read_text()))
    return [
        x.row.question for x in lines if x.row.question in NOT_STRESSED and x.status != "absent"
    ]


def uncarded_deciders(w: dict[str, Any]) -> list[str]:
    """Lock rows naming a decider who has no card: a person, a head, or a council's sitter."""
    carded = {c["person"] for c in w["cards"]}
    wrong = []
    for row in w["locks"]:
        d = row["decider"]
        council = d.get("council") or {}
        named = [d.get("person"), d.get("head"), council.get("head"), *council.get("members", [])]
        if any(p is not None and p not in carded for p in named):
            wrong.append(row["key"])
    return wrong


# --- The world compiles from the template ---------------------------------------------


def test_the_world_compiles_with_every_rule_but_the_playable_rule() -> None:
    w = world()
    assert w.ruleset == "realism"
    assert w.start_date == START
    assert set(w.rules) == RULES
    state = replay(compile_world(w, CAMPAIGN, cmp.versions()))
    names = {e.name for e in state.entities.values()}
    assert {"The United States", "The Confederate States"} <= names


def test_the_world_check_finds_no_required_answer_missing() -> None:
    check = _world_check()
    lines = check.check(world(), check.parse_template(TEMPLATE.read_text()))
    assert [x.row.question for x in lines if x.status == "required"] == []


def test_the_strict_map_check_passes() -> None:
    report = _map_check().check_world(WORLD)
    assert [str(p) for p in report.problems] == []


def test_the_areas_and_borders_are_the_maps() -> None:
    w, fragment = raw(), yaml.safe_load(FRAGMENT.read_text())
    assert w["map"] == fragment["map"]
    assert w["regions"] == fragment["regions"]

    def shape(rows: list[dict[str, Any]]) -> dict[str, tuple[str, str, tuple[str, ...]]]:
        return {r["key"]: (r["region"], r["terrain"], tuple(r.get("sites", ()))) for r in rows}

    assert shape(w["territories"]) == shape(fragment["territories"])
    assert shape(w["sea_zones"]) == shape(fragment["sea_zones"])

    def pairs(rows: list[Any]) -> set[str]:
        return {repr(r) for r in rows}

    assert pairs(w["adjacency"]) == pairs(fragment["adjacency"])


# --- Nations ---------------------------------------------------------------------------


def test_two_nations_are_played_and_every_other_holder_is_played_by_nobody() -> None:
    w = raw()
    playable = [c for c in w["cards"] if c.get("playable")]
    sides = {people(w)[c["person"]]["parent"] for c in playable}
    assert sides == set(SIDES)
    others = polities(w) - set(SIDES)
    assert others
    assert {people(w)[c["person"]]["parent"] for c in w["cards"]} <= set(SIDES)
    for key in others:
        tags = next(e["tags"] for e in w["entities"] if e["key"] == key)
        assert any(t.startswith("standing_") for t in tags), key


def test_every_territory_outside_the_two_nations_has_its_holder_or_is_a_finding() -> None:
    w = raw()
    others = polities(w) - set(SIDES)
    for key, holder in holders(w).items():
        if key in UNHELD:
            assert holder is None, key
        else:
            assert holder in polities(w), key
    abroad = {t["key"] for t in w["territories"] if t["region"] == "the_world"}
    assert {k for k in abroad if holders(w)[k] in SIDES} == set()
    assert {holders(w)[k] for k in abroad - UNHELD} == others


def test_each_side_holds_its_capital() -> None:
    w = raw()
    for side, place, area in (("usa", "washington", "maryland"), ("csa", "richmond", "virginia")):
        nation = next(e for e in w["entities"] if e["key"] == side)
        assert nation["capital"] == place
        assert holders(w)[area] == side


# --- People ----------------------------------------------------------------------------


def test_every_person_is_real_and_has_a_source() -> None:
    w = raw()
    dossier = yaml.safe_load(DOSSIER.read_text())
    assert dossier["world"] == w["world"]
    sources = {s["key"] for s in w["sources"]}
    for key, person in people(w).items():
        assert person["parent"] in SIDES, key
        entry = dossier["people"][key]
        assert entry["source"] in sources, key


# --- Forces ----------------------------------------------------------------------------


def test_forces_are_tiers_and_stand_on_their_sides_ground() -> None:
    w = raw()
    assert w["features"]
    for f in w["features"]:
        assert f["kind"] == "piece" and f["piece"] in ("army", "fleet"), f["key"]
        assert 1 <= f["tier"] <= 5, f["key"]
    assert off_ground(w) == []


def test_a_force_on_the_far_side_of_the_line_is_caught() -> None:
    w = copy.deepcopy(raw())
    army = next(f for f in w["features"] if f["side"] == "csa" and f["piece"] == "army")
    w["entities"].append(
        {"key": "boston", "kind": "location", "name": "Boston", "within": "new_england"}
    )
    army["places"] = ["boston"]
    assert off_ground(w) == [army["key"]]


def test_squadrons_of_the_nations_nobody_plays_stand_on_the_american_coast() -> None:
    w = raw()
    coast = {z["key"] for z in w["sea_zones"] if z["region"] == "the_coast"}
    foreign = [f for f in w["features"] if f["side"] not in SIDES]
    assert foreign
    for f in foreign:
        assert f["piece"] == "fleet", f["key"]
        assert stand_area(w, f) in coast, f["key"]


# --- Deciders and groups ---------------------------------------------------------------


def test_every_decider_has_a_card() -> None:
    w = raw()
    assert w["locks"]
    assert uncarded_deciders(w) == []
    assert {q for row in w["locks"] if (q := row.get("question"))} >= {"war", "permission"}


def test_a_lock_whose_decider_has_no_card_is_caught() -> None:
    w = copy.deepcopy(raw())
    row = next(r for r in w["locks"] if "person" in r["decider"])
    nobody = next(p for p in people(w) if p not in {c["person"] for c in w["cards"]})
    row["decider"] = {"person": nobody}
    assert uncarded_deciders(w) == [row["key"]]


def test_groups_stand_only_in_the_two_nations() -> None:
    w = raw()
    assert {g["nation"] for g in w["groups"]} == set(SIDES)


# --- What the world leaves out ----------------------------------------------------------


def test_the_three_lines_this_world_cannot_stress_are_absent_on_purpose() -> None:
    check = _world_check()
    questions = {r.question for r in check.parse_template(TEMPLATE.read_text())}
    assert set(NOT_STRESSED) <= questions
    assert stressed(world()) == []


def test_a_world_that_answers_a_line_it_cannot_stress_is_caught() -> None:
    w = raw()
    w["outlets"] = [{"key": "tribune", "polity": "usa", "name": "The Tribune", "voice": "Radical."}]
    assert stressed(WorldFile.model_validate(w)) == [NOT_STRESSED[2]]


def test_each_finding_against_the_template_is_written_into_it() -> None:
    text = TEMPLATE.read_text()
    assert "## The second scenario's filling, written in" in text
    section = text.split("## The second scenario's filling, written in", 1)[1]
    assert [f for f in FINDINGS if f"**{f}.**" not in section] == []


# --- Aims, contests, the election, places and history's clock ---------------------------

SEASON_END = date(1862, 12, 15)
"""The last deciding day: every contest decides on it and the season ends on it."""
NOT_ISSUED: dict[str, tuple[int, str]] = {
    "lincoln": (3, "seward"),
    "davis": (3, "randolph"),
    "stanton": (3, "lincoln"),
    "randolph": (3, "davis"),
    "mcclellan": (3, "halleck"),
    "buell": (3, "halleck"),
    "lee": (3, "davis"),
    "bragg": (3, "davis"),
}
"""Each playable card's aim its own government would not issue: the aim's number and the
member of the same government the card is set against over it (the card's ``opposes``)."""


def playable(w: dict[str, Any]) -> list[str]:
    return [c["person"] for c in w["cards"] if c.get("playable")]


def cards(w: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["person"]: c for c in w["cards"]}


def day_one(w: dict[str, Any]) -> dict[tuple[str, int], goals.AimStatus]:
    """Each playable card's aim status on the start date with ``w``'s cards, every card on
    the roster seated."""
    doc = world().model_copy(
        update={"cards": tuple(CardDecl.model_validate(c) for c in w["cards"])}
    )
    store = MemoryStore()
    store.append_all(compile_world(doc, CAMPAIGN, cmp.versions()))
    ids = resolve_keys(doc, CAMPAIGN)
    key = {v: k for k, v in ids.items()}
    for entry in doc.roster:
        person = EntityId(ids[entry.entity])
        name = load_state(store, CAMPAIGN).entities[person].name
        session_zero.claim(store, CAMPAIGN, SeatId(derived_id(CAMPAIGN, "seat", person)), name)
    state = load_state(store, CAMPAIGN)
    out: dict[tuple[str, int], goals.AimStatus] = {}
    for made in goals.aim_goals(state):
        g = made.goal
        assert g.person is not None and g.aim is not None
        out[(key[g.person], g.aim)] = goals.aim_status(state, g)
    return out


def test_every_playable_card_holds_three_aims_each_with_a_rule_and_one_replaceable() -> None:
    w = raw()
    by_person = cards(w)
    assert len(playable(w)) == len(NOT_ISSUED)
    for person in playable(w):
        card = by_person[person]
        assert len(card["aims"]) == 3, person
        rules = card["aim_rules"]
        assert sorted(r["aim"] for r in rules) == [1, 2, 3], person
        assert all(START < r["deadline"] <= SEASON_END for r in rules), person
        assert sum(bool(r.get("replaceable")) for r in rules) == 1, person


def test_each_playable_card_has_an_aim_its_own_government_would_not_issue() -> None:
    w = raw()
    by_person = cards(w)
    assert set(NOT_ISSUED) == set(playable(w))
    for person, (aim, against) in NOT_ISSUED.items():
        card = by_person[person]
        rule = next(r for r in card["aim_rules"] if r["aim"] == aim)
        assert not rule.get("replaceable"), person  # an own aim may not drop it
        assert against in {o["against"] for o in card.get("opposes", ())}, person
        same = against in card["principals"] or person in by_person[against].get("principals", ())
        assert same, person


def test_each_post_the_world_has_has_aim_patterns_one_its_government_would_not_issue() -> None:
    w = raw()
    kinds = {c["post_kind"] for c in w["cards"] if c.get("playable") and c.get("post_kind")}
    assert kinds == {"head_of_government", "military"}
    for kind in kinds:
        found = [p for p in w["aim_patterns"] if kind in p["posts"]]
        assert len(found) >= 3, kind
        assert any(p.get("government") is False for p in found), kind


def test_every_aim_is_neither_met_nor_impossible_on_day_one() -> None:
    found = day_one(raw())
    assert len(found) == 3 * len(NOT_ISSUED)
    assert {k: s for k, s in found.items() if s is not goals.AimStatus.AT_RISK} == {}


def test_mutant_an_aim_already_met_at_the_start_is_caught() -> None:
    w = raw()
    lincoln = cards(w)["lincoln"]
    lincoln["aim_rules"][0] = {
        **lincoln["aim_rules"][0],
        "condition": {"check": "holds_area", "area": "maryland", "holder": "usa"},
    }
    lincoln["aim_rules"][0].pop("opens", None)
    found = day_one(w)
    assert found[("lincoln", 1)] is goals.AimStatus.MET


def test_at_most_three_contests_each_moved_and_decided_on_the_last_deciding_day() -> None:
    w = raw()
    contests = w["contests"]
    assert 1 <= len(contests) <= 3
    assert {k["key"] for k in contests} == {"border_states", "recognition", "eastern_war"}
    for k in contests:
        assert set(k["sides"]) == set(SIDES), k["key"]
        assert START + timedelta(days=k["countdown_days"]) == SEASON_END, k["key"]
        assert {m["toward"] for m in k["moves"]} == set(SIDES), k["key"]
    assert w["settings"]["end_date"] == SEASON_END


def test_the_union_lower_chamber_is_redrawn_by_an_election_inside_the_season() -> None:
    w = raw()
    found = [(e["nation"], tuple(e["chambers"]), e["day"]) for e in w["elections"]]
    assert found == [("usa", ("house",), date(1862, 11, 4))]
    assert START < found[0][2] < SEASON_END
    house = [g for x in w["groups"] if x["nation"] == "usa" for g in x["groups"]]
    assert sum(g.get("seats", 0) for g in house if g.get("chamber") == "house") > 0


def test_each_side_has_places_of_weight_and_its_capital_is_one() -> None:
    w = raw()
    capitals = {e["key"]: e["capital"] for e in w["entities"] if e.get("capital")}
    within = {e["key"]: e.get("within") for e in w["entities"]}
    nation_groups = {x["nation"]: {g["key"] for g in x["groups"]} for x in w["groups"]}
    places = w["places"]
    for side in SIDES:
        mine = [p for p in places if p["nation"] == side]
        assert len(mine) >= 2, side
        assert within[capitals[side]] in {p["territory"] for p in mine}, side
        for p in mine:
            assert set(p["moves"]) <= nation_groups[side], p
            assert all(v < 0 for v in p["moves"].values()), p  # losing it costs support
    assert ABANDONED_TIMES > 1  # abandoning a place costs more than losing it


def test_history_is_a_dated_schedule_each_event_with_its_condition() -> None:
    w = raw()
    schedule = w["schedule"]
    assert len(schedule) >= 6
    for e in schedule:
        assert START < e["on_date"] <= SEASON_END, e["key"]
        assert e["condition"]["check"], e["key"]
    assert max(e["on_date"] for e in schedule) == SEASON_END  # a wake falls on the last day
    state = replay(compile_world(world(), CAMPAIGN, cmp.versions()))
    assert len(state.scheduled) == len(schedule)
