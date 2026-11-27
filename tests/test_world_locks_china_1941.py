"""1941: the Ninth War Area's commander and his locks (NCH).

General Xue Yue, in command of the Ninth War Area on 1 September 1941, is a military card the
players may claim: his own forms move the Ninth War Area and hide its moves, through his own
headquarters with no step above him (a side keeps no army detachment in play, so he has no
detach form); he answers to the Chief of the General Staff, and so to Chiang, and telephones
him; he has three aims with conditions, two filled from the army commander's patterns and one
the default a player's own aim would replace.

Chiang's ``military_affairs`` domain, carried out by He Yingqin, names the two Chinese armies
it commands and the moves it orders, so his ``move_army`` form lies inside his own domain and,
with both acting on the Ninth War Area in one wake, his order stands.

A lock holds giving up Changsha without a fight: sending the Ninth War Area back to Chungking
is Chiang's to permit. The row has no condition, so only his grant opens it. China has no body
and no council that decides.

The scripted run's digest (``run_digest``) with the third-run switches taken out of a copy's
rules is the baseline; with them on it is recorded here once.
"""

from datetime import date
from typing import Any

import pytest
from pydantic import JsonValue

from revisionist.core import events as ev
from revisionist.core.aim_patterns import build
from revisionist.core.ids import CampaignId, EntityId, OrderId, PipelineId, derived_id
from revisionist.core.realism import locks
from revisionist.core.realism.card import CardPath, superiors
from revisionist.core.realism.detachments import DETACHMENTS_PER_SIDE
from revisionist.core.realism.geography import FeatureKind
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

ON = "5cb9d48860d1833b119a377cd7b0863d"
"""The scripted run's digest with the 1941 world's third-run switches on, as the British,
German, Japanese, Italian and Soviet items recorded it: the Ninth War Area's card leaves it as
it was."""

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
FILED = date(1941, 10, 10)
AREA = "ninth_war_area"
ARMIES = {"chinese_army", AREA}
"""The two Chinese armies on the board, which Chiang's military affairs command."""
FORM = "ninth_war_area_move"
CONCEAL = "ninth_war_area_conceal"
ROW = "changsha_given_up"
"""The row Chiang decides: the Ninth War Area sent away from Changsha without a fight."""
BACK = "chungking"
"""The place away from Changsha the area's forms reach. [proposed]"""
FILLED: dict[int, tuple[str, dict[str, JsonValue]]] = {
    1: ("hold_and_take", {"held": "hunan", "place": "wuhan_area"}),
    2: ("take_ground", {"place": "south_china_coast"}),
}
"""Xue Yue's two aims from the army commander's patterns, with the values filled in."""


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def _card(world: WorldFile, person: str) -> Any:
    return next(c for c in world.cards if c.person == person)


def _compile(world: WorldFile) -> None:
    compile_world(world, CAMPAIGN, cmp.versions())


# --- rule 1: the commander's card ------------------------------------------------------


def test_the_ninth_war_area_commander_is_a_playable_military_card_on_the_roster() -> None:
    world = _world()
    xue = _card(world, "xue_yue")
    assert xue.office == "Commander, Ninth War Area"
    assert xue.playable and xue.path is CardPath.MILITARY
    assert xue.post_kind == "army_commander"
    assert xue.principals == ("he_yingqin",)
    assert "xue_yue" in {c.entity for c in world.roster}
    _compile(world)


def test_his_domain_names_the_ninth_war_area_and_no_other_military_card_does() -> None:
    world = _world()
    forces = {k for dm in _card(world, "xue_yue").authority for k in dm.forces}
    assert forces == {AREA}
    others = {
        k
        for c in world.cards
        if c.person != "xue_yue" and c.path is CardPath.MILITARY
        for dm in c.authority
        for k in dm.forces
    }
    assert AREA not in others


def test_the_commander_with_no_force_does_not_compile() -> None:
    world = _world()
    bare = _card(world, "xue_yue").model_copy(update={"authority": ()})
    cards = tuple(bare if c.person == "xue_yue" else c for c in world.cards)
    by_hand = tuple(r for r in world.rules if r != Rule.PLAYABLE_RULE)
    with pytest.raises(WorldError, match="a playable military card needs a domain naming a force"):
        _compile(world.model_copy(update={"cards": cards, "rules": by_hand}))
    with pytest.raises(WorldError, match=r"xue_yue: on the roster, .* a commander with no force"):
        _compile(world.model_copy(update={"cards": cards}))


def test_his_own_forms_move_and_hide_the_area_through_a_pipeline_with_no_step_above_him() -> None:
    world = _world()
    levers = {lv.name: lv for lv in _card(world, "xue_yue").levers}
    assert set(levers) == {FORM, CONCEAL}
    for lv in levers.values():
        pipeline = next(p for p in world.pipelines if p.key == lv.pipeline)
        assert [s.person for s in pipeline.steps] == ["xue_yue"], lv.name
    chiangs = next(lv for lv in _card(world, "chiang").levers if lv.name == "move_army")
    chiangs_to = set(next(p for p in chiangs.params if p.name == "to").choices)
    move = levers[FORM]
    assert next(p for p in move.params if p.name == "force").choices == (AREA,)
    to = next(p for p in move.params if p.name == "to")
    assert set(to.choices) == chiangs_to and BACK in to.choices
    hide = levers[CONCEAL]
    assert hide.resolver == "intel"
    assert next(p for p in hide.params if p.name == "intel").choices == ("conceal",)
    assert next(p for p in hide.params if p.name == "piece").choices == (AREA,)


def test_he_has_no_detach_form_while_a_side_keeps_no_army_detachment() -> None:
    assert DETACHMENTS_PER_SIDE[FeatureKind.ARMY] == 0
    levers = _card(_world(), "xue_yue").levers
    assert not [lv.name for lv in levers if "strength" in {p.name for p in lv.params}]


def test_he_telephones_the_chief_of_the_general_staff() -> None:
    world = _world()
    assert _card(world, "he_yingqin").office == "Chief of the General Staff, China"
    xue = _card(world, "xue_yue")
    assert ("he_yingqin", "telephone") in {(k.person, k.channel) for k in xue.inner_circle}


def test_he_has_three_aims_two_from_the_army_commanders_patterns_the_third_replaceable() -> None:
    world = _world()
    xue = _card(world, "xue_yue")
    assert len(xue.aims) == 3
    rules = {r.aim: r for r in xue.aim_rules}
    assert sorted(rules) == [1, 2, 3]
    assert [rules[n].replaceable for n in (1, 2, 3)] == [False, False, True]
    patterns = {p.key: p for p in world.aim_patterns}
    for n, (key, values) in FILLED.items():
        pattern = patterns[key]
        assert "army_commander" in pattern.posts
        filled = build(pattern.condition, {**values, "nation": "china", "person": "xue_yue"})
        assert rules[n].condition == filled, n


def test_he_holds_a_post_that_meets_the_character_rule() -> None:
    held = [a for a in _world().assets if a.controller == "xue_yue"]
    assert held and max(a.tier for a in held) >= 2


def test_his_dossier_has_a_line_that_says_chiang_permits_giving_up_changsha() -> None:
    people, _ = dossiers.load("autumn-1941")
    assert people["xue_yue"]["bio"] and people["xue_yue"]["arena"]
    arena = " ".join((people["xue_yue"]["arena"] or "").split())
    assert "give up Changsha without a fight is Chiang's to give" in arena


def test_the_general_staff_and_chiang_are_up_his_chain() -> None:
    r = Rig("autumn-1941")
    chain = superiors(r.state.cards, EntityId(r.ids["xue_yue"]))
    assert EntityId(r.ids["he_yingqin"]) in chain and EntityId(r.ids["chiang"]) in chain


def test_a_mandate_reaches_him() -> None:
    world = _world()
    assert [m.key for m in world.mandates if "xue_yue" in m.to]


# --- rule 3: Chiang's military affairs name the armies -----------------------------------


def test_chiangs_military_affairs_name_the_armies_and_their_moves() -> None:
    chiang = _card(_world(), "chiang")
    (affairs,) = [dm for dm in chiang.authority if dm.name == "military_affairs"]
    assert affairs.executor == "he_yingqin"
    assert set(affairs.forces) == ARMIES
    assert {"move_force", "engagement"} <= set(affairs.effects)
    move_army = next(lv for lv in chiang.levers if lv.name == "move_army")
    assert set(next(p for p in move_army.params if p.name == "force").choices) == ARMIES


# --- rule 2: the lock, decided by Chiang ----------------------------------------------------


def _rows(world: WorldFile) -> dict[str, Any]:
    return {r.key: r for r in world.locks if r.order.form == FORM}


def test_a_lock_on_giving_up_changsha_for_chiang() -> None:
    rows = _rows(_world())
    assert set(rows) == {ROW}
    row = rows[ROW]
    assert row.order.form == FORM and row.order.params == {"to": BACK}
    assert row.decider.person == "chiang"
    assert row.question == "permission" and row.when is None


def test_a_row_whose_decider_is_the_issuer_does_not_compile() -> None:
    world = _world()
    rows = tuple(
        r.model_copy(update={"decider": r.decider.model_copy(update={"person": "xue_yue"})})
        if r.key == ROW
        else r
        for r in world.locks
    )
    with pytest.raises(WorldError, match="xue_yue carries the form and would decide"):
        _compile(world.model_copy(update={"locks": rows}))


def test_a_row_naming_a_missing_chamber_does_not_compile() -> None:
    world = _world()
    body = {"person": None, "nation": "china", "chambers": ("legislative_yuan",), "head": "chiang"}
    rows = tuple(
        r.model_copy(update={"decider": r.decider.model_copy(update=body)}) if r.key == ROW else r
        for r in world.locks
    )
    with pytest.raises(WorldError, match="china has no chamber legislative_yuan"):
        _compile(world.model_copy(update={"locks": rows}))


def _rig(*people: str) -> Rig:
    r = Rig("autumn-1941")
    for person in people:
        r.seat(person)
    r.close_session_zero()
    return r


def _order(r: Rig, lever: str, **params: str | int) -> Order:
    return Order(
        order_id=OrderId(derived_id(r.campaign, "order", f"nch-{lever}-{sorted(params.items())}")),
        issuer=r.seats["xue_yue"],
        lever=lever,
        pipeline=PipelineId(r.ids["ninth_war_area_hq"]),
        params=params,
        filed=FILED,
    )


def test_giving_up_changsha_is_held_for_chiang() -> None:
    r = _rig("xue_yue")
    order = _order(r, FORM, force=AREA, to=BACK)
    lock = locks.lock_for(r.state, r.seats["xue_yue"], order)
    assert lock is not None and lock.decider.person == EntityId(r.ids["chiang"])
    assert lock.row is not None and locks.by_kind(r.state, lock.row)
    for free_to in ("changsha", "wuhan"):
        free = _order(r, FORM, force=AREA, to=free_to)
        assert locks.lock_for(r.state, r.seats["xue_yue"], free) is None, free_to


def _held_and_asked(r: Rig, order: Order) -> locks.Asked:
    seat = r.seats["xue_yue"]
    lock = locks.lock_for(r.state, seat, order)
    assert lock is not None and lock.row is not None
    held = locks.HeldOrder(
        order_id=order.order_id,
        issuer=seat,
        filed=order.filed,
        form=order,
        row=lock.row.key,
        decider=lock.decider,
        reason="Held.",
    )
    r.add(ev.OrderHeld(held=held))
    asked = locks.ask(r.state, seat, order.order_id, FILED)
    r.add(ev.OrderAsked(asked=asked))
    return asked


@pytest.mark.parametrize("granted", [True, False])
def test_only_chiangs_grant_opens_the_way_back_from_changsha(granted: bool) -> None:
    r = _rig("xue_yue")
    asked = _held_and_asked(r, _order(r, FORM, force=AREA, to=BACK))
    assert asked.to == EntityId(r.ids["chiang"])
    held = r.state.held[asked.order_id]
    assert not locks.open_now(r.state, held)
    seat = r.seats["xue_yue"]
    r.add(ev.AskAnswered(order_id=asked.order_id, asker=seat, on=FILED, granted=granted))
    assert locks.open_now(r.state, r.state.held[asked.order_id]) is granted


# --- no body and no council ---------------------------------------------------------------


def test_china_has_no_body_and_no_council_that_decides_giving_up_changsha() -> None:
    world = _world()
    chambers = [g.key for d in world.groups if d.nation == "china" for g in d.groups if g.chamber]
    assert chambers == []
    for row in _rows(world).values():
        assert row.decider.nation is None and row.decider.council is None, row.key
        assert not row.decider.chambers, row.key


# --- the roster holds him -----------------------------------------------------------------


def test_the_roster_limit_holds_him() -> None:
    world = _world()
    assert world.roster_limit is not None
    least, most = world.roster_limit
    assert least <= len(world.roster) <= most
    assert not [p for p in check_history(world) if p.startswith("roster")]


def test_with_the_third_run_switches_out_his_lock_stays() -> None:
    kept = {r.key for r in without_third_run(_world()).locks}
    assert ROW in kept


# --- rule 4: the scripted run -------------------------------------------------------------


def test_the_scripted_run_is_the_baseline_with_the_third_run_switches_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(without_third_run(_world()), monkeypatch) == BASELINE_1941


def test_the_scripted_run_with_the_third_run_switches_on_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(_world(), monkeypatch) == ON
