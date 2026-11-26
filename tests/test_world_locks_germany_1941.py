"""1941: the U-boat arm's commander and his two locks (NGE).

Vice-Admiral Dönitz, Commander of U-boats, is a military card the players may claim: his own
forms move and detach the U-boat arm through his own staff with no step above him; he answers
to the Navy's commander in chief, and so to Hitler, and cables Hitler; he has three aims with
conditions, two filled from the fleet commander's patterns and one the default a player's own
aim would replace. Hitler keeps his order over the U-boat arm, so with both acting on it in one
wake his order stands.

Two locks hold the commander's orders against American ships in the western Atlantic: sending
the U-boats off Argentia, or detaching boats there, waits until Hitler has set the U-boats'
posture in the North Atlantic to attack American ships, and Hitler decides. Germany has no body
and no council that decides: the head decides alone.

The scripted run's digest (``run_digest``) with the third-run switches taken out of a copy's
rules is the baseline; with them on it is recorded here once.
"""

from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import JsonValue

from revisionist.core.aim_patterns import build
from revisionist.core.ids import CampaignId, EntityId, OrderId, PipelineId, derived_id
from revisionist.core.realism import locks
from revisionist.core.realism.card import CardPath, superiors
from revisionist.core.realism.pipeline import Order
from revisionist.core.state import Rule
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, check_history, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine.web import dossiers
from tests.test_realism_resolvers import Rig
from tests.test_rule_names import BASELINE_1941
from tests.test_world_locks_1941 import run_digest
from tests.test_world_locks_uk_1941 import without_third_run

ON = "45f00e1d6cb09e84245f4a7affb44692"
"""The scripted run's digest with the 1941 world's third-run switches on, recorded once by
this item. It equals the baseline: the script seats the President alone and files no order
the two new locks hold."""

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
FILED = date(1941, 9, 20)
ROWS = ("uboats_against_american_ships", "uboat_detachment_against_american_ships")
POSTURE = {"posture": "attack_us_shipping"}
WATERS = {"theatre": "north_atlantic"}
FILLED: dict[int, tuple[str, dict[str, JsonValue]]] = {
    1: ("hold_and_take", {"held": "occupied_france", "place": "iceland"}),
    2: ("war_with", {"foe": "usa"}),
}
"""Dönitz's two aims from the fleet commander's patterns, with the values filled in."""


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def _card(world: WorldFile, person: str) -> Any:
    return next(c for c in world.cards if c.person == person)


def _compile(world: WorldFile) -> None:
    compile_world(world, CAMPAIGN, cmp.versions())


# --- rule 1: the commander's card ------------------------------------------------------


def test_the_uboat_commander_is_a_playable_military_card_on_the_roster() -> None:
    world = _world()
    doenitz = _card(world, "doenitz")
    assert doenitz.office == "Commander of U-boats"
    assert doenitz.playable and doenitz.path is CardPath.MILITARY
    assert doenitz.post_kind == "fleet_commander"
    assert doenitz.principals == ("raeder",)
    assert "doenitz" in {c.entity for c in world.roster}
    _compile(world)


def test_his_domain_names_the_uboat_arm_and_no_other_military_card_does() -> None:
    world = _world()
    forces = {k for dm in _card(world, "doenitz").authority for k in dm.forces}
    assert forces == {"uboat_arm"}
    others = {
        k
        for c in world.cards
        if c.person != "doenitz" and c.path is CardPath.MILITARY
        for dm in c.authority
        for k in dm.forces
    }
    assert "uboat_arm" not in others


def test_the_commander_with_no_force_does_not_compile() -> None:
    world = _world()
    bare = _card(world, "doenitz").model_copy(update={"authority": ()})
    cards = tuple(bare if c.person == "doenitz" else c for c in world.cards)
    by_hand = tuple(r for r in world.rules if r != Rule.PLAYABLE_RULE)
    with pytest.raises(WorldError, match="a playable military card needs a domain naming a force"):
        _compile(world.model_copy(update={"cards": cards, "rules": by_hand}))
    with pytest.raises(WorldError, match=r"doenitz: on the roster, .* a commander with no force"):
        _compile(world.model_copy(update={"cards": cards}))


def test_his_own_forms_move_and_detach_through_a_pipeline_with_no_step_above_him() -> None:
    world = _world()
    levers = {lv.name: lv for lv in _card(world, "doenitz").levers}
    assert set(levers) == {"uboat_move", "uboat_detach"}
    for lv in levers.values():
        pipeline = next(p for p in world.pipelines if p.key == lv.pipeline)
        assert [s.person for s in pipeline.steps] == ["doenitz"], lv.name
        force = next(p for p in lv.params if p.name == "force")
        assert force.choices == ("uboat_arm",)
        to = next(p for p in lv.params if p.name == "to")
        assert "argentia" in to.choices
    assert "strength" in {p.name for p in levers["uboat_detach"].params}


def test_he_cables_hitler() -> None:
    doenitz = _card(_world(), "doenitz")
    assert ("hitler", "cable") in {(k.person, k.channel) for k in doenitz.inner_circle}


def test_he_has_three_aims_two_from_the_fleet_commanders_patterns_the_third_replaceable() -> None:
    world = _world()
    doenitz = _card(world, "doenitz")
    assert len(doenitz.aims) == 3
    rules = {r.aim: r for r in doenitz.aim_rules}
    assert sorted(rules) == [1, 2, 3]
    assert [rules[n].replaceable for n in (1, 2, 3)] == [False, False, True]
    patterns = {p.key: p for p in world.aim_patterns}
    for n, (key, values) in FILLED.items():
        pattern = patterns[key]
        assert "fleet_commander" in pattern.posts
        filled = build(pattern.condition, {**values, "nation": "germany", "person": "doenitz"})
        assert rules[n].condition == filled, n


def test_he_holds_a_post_that_meets_the_character_rule() -> None:
    held = [a for a in _world().assets if a.controller == "doenitz"]
    assert held and max(a.tier for a in held) >= 2


def test_his_dossier_has_a_line() -> None:
    people, _ = dossiers.load("autumn-1941")
    assert people["doenitz"]["bio"] and people["doenitz"]["arena"]


def test_hitler_keeps_his_order_over_the_uboat_arm_and_is_up_the_chain() -> None:
    world = _world()
    forces = {k for dm in _card(world, "hitler").authority for k in dm.forces}
    assert "uboat_arm" in forces
    r = Rig("autumn-1941")
    chain = superiors(r.state.cards, EntityId(r.ids["doenitz"]))
    assert EntityId(r.ids["hitler"]) in chain


# --- rule 2: the two locks, each decided by Hitler ------------------------------------------


def _rows(world: WorldFile) -> dict[str, Any]:
    return {r.key: r for r in world.locks if r.order.form in {"uboat_move", "uboat_detach"}}


def test_two_locks_on_american_ships_in_the_western_atlantic_each_for_hitler() -> None:
    rows = _rows(_world())
    assert set(rows) == set(ROWS)
    move, detach = (rows[k] for k in ROWS)
    assert move.order.form == "uboat_move" and move.order.params == {"to": "argentia"}
    assert detach.order.form == "uboat_detach" and detach.order.params == {"to": "argentia"}
    for row in (move, detach):
        assert row.decider.person == "hitler", row.key
        assert row.when is not None and row.when.check == "posture_not_set"
        assert row.when.form == "uboat_directive"
        assert row.when.where == WATERS and row.when.posture == POSTURE


def test_hitlers_form_can_state_the_posture_the_locks_wait_on() -> None:
    lever = next(lv for lv in _card(_world(), "hitler").levers if lv.name == "uboat_directive")
    params = {p.name: p for p in lever.params}
    assert POSTURE["posture"] in params["posture"].choices
    assert WATERS["theatre"] in params["theatre"].choices


def test_a_row_whose_decider_is_the_issuer_does_not_compile() -> None:
    world = _world()
    rows = tuple(
        r.model_copy(update={"decider": r.decider.model_copy(update={"person": "doenitz"})})
        if r.key == ROWS[0]
        else r
        for r in world.locks
    )
    with pytest.raises(WorldError, match="doenitz carries the form and would decide"):
        _compile(world.model_copy(update={"locks": rows}))


def _rig() -> Rig:
    r = Rig("autumn-1941")
    r.seat("hitler")
    r.seat("doenitz")
    r.close_session_zero()
    return r


def _order(r: Rig, lever: str, **params: str | int) -> Order:
    return Order(
        order_id=OrderId(derived_id(r.campaign, "order", f"nge-{lever}-{sorted(params.items())}")),
        issuer=r.seats["doenitz"],
        lever=lever,
        pipeline=PipelineId(r.ids["bdu_staff"]),
        params=params,
        filed=FILED,
    )


def _directive(r: Rig, posture: str, on: date) -> None:
    r.enact(
        "hitler",
        "uboat_directive",
        "okw_directive",
        on,
        [on + timedelta(days=1), on + timedelta(days=3)],
        posture=posture,
        theatre="north_atlantic",
    )


@pytest.mark.parametrize(
    ("lever", "extra"), [("uboat_move", {}), ("uboat_detach", {"strength": 2})]
)
def test_the_uboats_against_american_ships_wait_on_hitlers_posture(
    lever: str, extra: dict[str, int]
) -> None:
    r = _rig()
    order = _order(r, lever, force="uboat_arm", to="argentia", **extra)
    lock = locks.lock_for(r.state, r.seats["doenitz"], order)
    assert lock is not None and lock.decider.person == EntityId(r.ids["hitler"])
    free = _order(r, lever, force="uboat_arm", to="lorient", **extra)
    assert locks.lock_for(r.state, r.seats["doenitz"], free) is None
    _directive(r, "unrestricted_atlantic", date(1941, 9, 11))
    assert locks.lock_for(r.state, r.seats["doenitz"], order) is not None
    _directive(r, "attack_us_shipping", date(1941, 9, 15))
    assert locks.lock_for(r.state, r.seats["doenitz"], order) is None


# --- rule 3: no body and no council -------------------------------------------------------


def test_germany_has_no_body_and_no_council_and_the_dossier_says_the_head_decides_alone() -> None:
    world = _world()
    (germany,) = [d for d in world.groups if d.nation == "germany"]
    assert not [g.key for g in germany.groups if g.chamber is not None]
    for row in _rows(world).values():
        assert row.decider.nation is None and row.decider.council is None, row.key
        assert not row.decider.chambers, row.key
    people, _ = dossiers.load("autumn-1941")
    assert "decides alone" in (people["doenitz"]["arena"] or "")


# --- the roster holds him -----------------------------------------------------------------


def test_the_roster_limit_holds_him() -> None:
    world = _world()
    assert world.roster_limit is not None
    least, most = world.roster_limit
    assert least <= len(world.roster) <= most
    assert not [p for p in check_history(world) if p.startswith("roster")]


# --- rule 4: the scripted run -------------------------------------------------------------


def test_with_the_third_run_switches_out_his_locks_stay() -> None:
    kept = {r.key for r in without_third_run(_world()).locks}
    assert set(ROWS) <= kept


def test_the_scripted_run_is_the_baseline_with_the_third_run_switches_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(without_third_run(_world()), monkeypatch) == BASELINE_1941


def test_the_scripted_run_with_the_third_run_switches_on_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(_world(), monkeypatch) == ON
