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
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId
from revisionist.core.state import MODEL_READ_RULES, Rule
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp

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
