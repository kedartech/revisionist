"""1941: losses, places with political weight, and the class of each happening (HFD).

Autumn 1941 switches on ``classes``, ``losses`` and ``places``. Each kind of happening is
classed as the design's first sort of events has it, and each declared law is marked as
touching daily life or not. Each of the seven nations with groups names the groups the size
of a day's battle losses moves, and lists up to five territories it holds at the start whose
loss weighs at home, each line ``gap: true`` until sourced. With the three switches taken out
of a copy's rules the scripted run's digest is the baseline; with them on it is recorded here.
"""

import re

import pytest

from revisionist.core.ids import EntityId
from revisionist.core.realism import groups
from revisionist.core.realism.groups import Class, Happening
from revisionist.core.state import Rule, State
from revisionist.core.world import WorldFile
from revisionist.engine import campaign as cmp
from tests import test_world_locks_1941 as locks_1941
from tests.test_realism_resolvers import Rig
from tests.test_rule_names import BASELINE_1941
from tests.test_world_groups_1941 import SEVEN, raw, section

SWITCHES = (Rule.CLASSES, Rule.LOSSES, Rule.PLACES)
"""The three rules this item switches on in 1941."""
SORT = {
    Happening.CAPITAL_THREATENED: Class.FELT,
    Happening.BATTLE_WON: Class.REPORTED,
    Happening.BATTLE_LOST: Class.REPORTED,
    Happening.LOSSES_AT_SEA: Class.REPORTED,
    Happening.TERRITORY_TAKEN: Class.REPORTED,
    Happening.WAR_DECLARED: Class.REPORTED,
    Happening.AGREEMENT_BROKEN: Class.REPORTED,
}
"""The design's first sort of events: the kinds wholly felt or wholly reported."""
MIXED = (Happening.TERRITORY_LOST, Happening.BATTLE_LOSSES)
"""The kinds the first sort mixes: reported, each with a felt share."""
PLACES_MAX = 5
"""The most places with political weight one nation lists (HFD rule 3)."""
ON_1941 = "ab03df1be1ecad010be0b6534d879942"
"""The scripted run's digest with the three switches on, recorded once: the baseline's, as the
scripted run walks no groups."""
GAP = re.compile(r"#\s*gap:\s*true\b")


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def without_switches(world: WorldFile) -> WorldFile:
    return world.model_copy(update={"rules": tuple(r for r in world.rules if r not in SWITCHES)})


@pytest.fixture(scope="module")
def rig() -> Rig:
    return Rig()


@pytest.fixture(scope="module")
def state(rig: Rig) -> State:
    return rig.state


# --- rule 4: the world's rules gain the three; it compiles ---------------------------------


def test_the_world_switches_on_classes_losses_and_places_and_compiles(state: State) -> None:
    assert {r.value for r in SWITCHES} <= set(raw()["rules"])
    assert groups.classes_on(state) and groups.losses_on(state) and groups.places_on(state)


# --- rule 1: the class of each kind of happening, and the laws ------------------------------


def test_every_kind_is_classed_once_with_one_of_the_three_classes() -> None:
    written = raw()["happenings"]
    assert all(h["reach"] in {c.value for c in Class} for h in written)
    kinds = [h["kind"] for h in written]
    assert len(kinds) == len(set(kinds))


def test_the_classes_follow_the_first_sort_of_events(state: State) -> None:
    for kind, reach in SORT.items():
        assert groups.cls(state, kind).reach is reach, kind
        assert not groups.cls(state, kind).mixed, kind
    for kind in MIXED:
        c = groups.cls(state, kind)
        assert c.reach is Class.REPORTED and c.mixed, kind
    assert not any(groups.cls(state, k).reach is Class.SECRET for k in Happening)


def test_a_daily_life_law_is_felt_and_any_other_measure_reported(state: State) -> None:
    assert groups.cls(state, Happening.DAILY_LIFE_PASSED).reach is Class.FELT
    assert groups.cls(state, Happening.MEASURE_PASSED).reach is Class.REPORTED


def test_each_declared_law_is_marked_as_touching_daily_life_or_not() -> None:
    laws = raw()["laws"]
    assert laws and all(isinstance(law.get("daily_life"), bool) for law in laws)
    marked = {law["key"]: law["daily_life"] for law in laws}
    assert marked["national_service"] and marked["draft_extension"]
    assert not marked["neutrality_revision"]


def test_a_group_a_measure_passed_moves_is_moved_by_a_daily_life_law_too() -> None:
    for decl in raw()["groups"]:
        for g in decl["groups"]:
            moved = g.get("moved_by", {})
            if "measure_passed" in moved:
                assert moved.get("daily_life_passed") == moved["measure_passed"], g["key"]


# --- rule 2: the groups losses move ---------------------------------------------------------


def test_each_nation_with_groups_names_the_groups_its_losses_move() -> None:
    by_nation = {d["nation"]: d["groups"] for d in raw()["groups"]}
    assert set(by_nation) == set(SEVEN)
    for nation, gs in by_nation.items():
        amounts = {g["key"]: g.get("moved_by", {}).get("battle_losses") for g in gs}
        moved = {k: v for k, v in amounts.items() if v is not None}
        assert moved, nation
        assert "public" in moved, nation
        assert all(-groups.LOSSES_DAY_CAP <= v < 0 for v in moved.values()), nation


# --- rule 3: places with political weight ---------------------------------------------------


def test_each_nation_with_groups_lists_up_to_five_weighted_places() -> None:
    places = raw()["places"]
    for nation in SEVEN:
        mine = [p for p in places if p["nation"] == nation]
        assert 1 <= len(mine) <= PLACES_MAX, nation
    assert {p["nation"] for p in places} == set(SEVEN)


def test_each_place_is_ground_its_nation_holds_at_the_start() -> None:
    holder = {t["key"]: t["holder"] for t in raw()["territories"]}
    for p in raw()["places"]:
        assert holder[p["territory"]] == p["nation"], p["territory"]


def test_each_place_moves_its_own_nations_groups_down_when_lost() -> None:
    own = {d["nation"]: {g["key"] for g in d["groups"]} for d in raw()["groups"]}
    for p in raw()["places"]:
        assert set(p["moves"]) <= own[p["nation"]], p["territory"]
        assert all(v < 0 for v in p["moves"].values()), p["territory"]


def test_each_place_line_is_gap_until_sourced() -> None:
    lines = [line for line in section("places") if line.lstrip().startswith("- {territory:")]
    assert len(lines) == len(raw()["places"])
    assert all(GAP.search(line) for line in lines)


def test_the_compiled_places_are_the_worlds(rig: Rig) -> None:
    def entity(key: str) -> EntityId:
        return EntityId(rig.ids[key])

    assert {(p.territory, p.nation) for p in rig.state.groups.places} == {
        (entity(p["territory"]), entity(p["nation"])) for p in raw()["places"]
    }


# --- rule 5 and Accept: the scripted run ----------------------------------------------------


def test_the_scripted_run_with_the_three_switches_out_is_the_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = without_switches(_world())
    assert not set(SWITCHES) & set(world.rules)
    assert locks_1941.run_digest(world, monkeypatch) == BASELINE_1941


def test_the_scripted_run_with_the_three_switches_on_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world()
    assert set(SWITCHES) <= set(world.rules)
    assert locks_1941.run_digest(world, monkeypatch) == ON_1941
