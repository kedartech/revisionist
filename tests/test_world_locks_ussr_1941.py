"""1941: the Soviet Western Front's commander and his locks (NSU).

Marshal Timoshenko, in command of the Western Front on 1 September 1941, is a military card
the players may claim: his own forms move the Western Front and hide its moves, through his own
staff with no step above him (a side keeps no army detachment in play, so he has no detach form);
he answers to the Chief of the General Staff, and so to Stalin, and telephones him; he has three
aims with conditions, two filled from the army commander's patterns and one the default a
player's own aim would replace. Stalin keeps his order over the front: his military operations
name it, so with both acting on the front in one wake his order stands. The record changes this
front's commander inside the season; the card is the man in post on the start date, and the
change is left to the ladder of posts.

A lock holds a withdrawal of the front behind the Mozhaisk line: sending the front back to
Moscow is Stalin's to permit. The row has no condition, so only his grant opens it. The Soviet
Union has no body and no council that decides.

The record's move of the front on 24 October (``Feature.legs``) still runs with the third-run
switches out. With a player in the seat, history steps aside as the rule already has it: an
order that sends the front drops the moves the record still had for it, and a battle does too;
a seat that files no such order leaves the record's move in place.

The scripted run's digest (``run_digest``) with the third-run switches taken out of a copy's
rules is the baseline; with them on it is recorded here once.
"""

from datetime import date
from typing import Any

import pytest
from pydantic import JsonValue

from revisionist.core import events as ev
from revisionist.core.aim_patterns import build
from revisionist.core.ids import CampaignId, EntityId, FeatureId, OrderId, PipelineId, derived_id
from revisionist.core.realism import locks
from revisionist.core.realism.card import CardPath, superiors
from revisionist.core.realism.detachments import DETACHMENTS_PER_SIDE
from revisionist.core.realism.geography import FeatureKind
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import movement
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, check_history, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine.web import dossiers
from tests.test_realism_resolvers import Rig
from tests.test_rule_names import BASELINE_1941
from tests.test_world_locks_1941 import run_digest
from tests.test_world_locks_japan_1941 import _season
from tests.test_world_locks_uk_1941 import without_third_run

ON = "45f00e1d6cb09e84245f4a7affb44692"
"""The scripted run's digest with the 1941 world's third-run switches on, as the British,
German, Japanese and Italian items recorded it: the Western Front's card leaves it as it was."""

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
FILED = date(1941, 10, 10)
FRONT = "soviet_western_front"
FORM = "western_front_move"
CONCEAL = "western_front_conceal"
ROW = "western_front_withdrawal"
"""The row Stalin decides: the front's move behind the Mozhaisk line."""
BEHIND = "moscow"
"""The place behind the Mozhaisk line the front's forms reach. [proposed]"""
FILLED: dict[int, tuple[str, dict[str, JsonValue]]] = {
    1: ("hold_and_take", {"held": "moscow_area", "place": "smolensk_area"}),
    2: ("take_ground", {"place": "belorussia"}),
}
"""Timoshenko's two aims from the army commander's patterns, with the values filled in."""


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def _card(world: WorldFile, person: str) -> Any:
    return next(c for c in world.cards if c.person == person)


def _compile(world: WorldFile) -> None:
    compile_world(world, CAMPAIGN, cmp.versions())


# --- rule 1: the commander's card ------------------------------------------------------


def test_the_western_front_commander_is_a_playable_military_card_on_the_roster() -> None:
    world = _world()
    timoshenko = _card(world, "timoshenko")
    assert timoshenko.office == "Commander, Western Front"
    assert timoshenko.playable and timoshenko.path is CardPath.MILITARY
    assert timoshenko.post_kind == "army_commander"
    assert timoshenko.principals == ("shaposhnikov",)
    assert "timoshenko" in {c.entity for c in world.roster}
    _compile(world)


def test_his_domain_names_the_western_front_and_no_other_military_card_does() -> None:
    world = _world()
    forces = {k for dm in _card(world, "timoshenko").authority for k in dm.forces}
    assert forces == {FRONT}
    others = {
        k
        for c in world.cards
        if c.person != "timoshenko" and c.path is CardPath.MILITARY
        for dm in c.authority
        for k in dm.forces
    }
    assert FRONT not in others


def test_the_commander_with_no_force_does_not_compile() -> None:
    world = _world()
    bare = _card(world, "timoshenko").model_copy(update={"authority": ()})
    cards = tuple(bare if c.person == "timoshenko" else c for c in world.cards)
    with pytest.raises(WorldError, match="a playable military card needs a domain naming a force"):
        _compile(world.model_copy(update={"cards": cards}))


def test_his_own_forms_move_and_hide_the_front_through_a_pipeline_with_no_step_above_him() -> None:
    world = _world()
    levers = {lv.name: lv for lv in _card(world, "timoshenko").levers}
    assert set(levers) == {FORM, CONCEAL}
    for lv in levers.values():
        pipeline = next(p for p in world.pipelines if p.key == lv.pipeline)
        assert [s.person for s in pipeline.steps] == ["timoshenko"], lv.name
    stalins = next(lv for lv in _card(world, "stalin").levers if lv.name == "move_army")
    stalins_to = set(next(p for p in stalins.params if p.name == "to").choices)
    move = levers[FORM]
    assert next(p for p in move.params if p.name == "force").choices == (FRONT,)
    to = next(p for p in move.params if p.name == "to")
    assert set(to.choices) == stalins_to and BEHIND in to.choices
    hide = levers[CONCEAL]
    assert hide.resolver == "intel"
    assert next(p for p in hide.params if p.name == "intel").choices == ("conceal",)
    assert next(p for p in hide.params if p.name == "piece").choices == (FRONT,)


def test_he_has_no_detach_form_while_a_side_keeps_no_army_detachment() -> None:
    assert DETACHMENTS_PER_SIDE[FeatureKind.ARMY] == 0
    levers = _card(_world(), "timoshenko").levers
    assert not [lv.name for lv in levers if "strength" in {p.name for p in lv.params}]


def test_he_telephones_the_chief_of_the_general_staff() -> None:
    timoshenko = _card(_world(), "timoshenko")
    assert ("shaposhnikov", "telephone") in {(k.person, k.channel) for k in timoshenko.inner_circle}


def test_he_has_three_aims_two_from_the_army_commanders_patterns_the_third_replaceable() -> None:
    world = _world()
    timoshenko = _card(world, "timoshenko")
    assert len(timoshenko.aims) == 3
    rules = {r.aim: r for r in timoshenko.aim_rules}
    assert sorted(rules) == [1, 2, 3]
    assert [rules[n].replaceable for n in (1, 2, 3)] == [False, False, True]
    patterns = {p.key: p for p in world.aim_patterns}
    for n, (key, values) in FILLED.items():
        pattern = patterns[key]
        assert "army_commander" in pattern.posts
        filled = build(pattern.condition, {**values, "nation": "ussr", "person": "timoshenko"})
        assert rules[n].condition == filled, n


def test_he_holds_a_post_that_meets_the_character_rule() -> None:
    held = [a for a in _world().assets if a.controller == "timoshenko"]
    assert held and max(a.tier for a in held) >= 2


def test_his_dossier_has_a_line_that_says_stalin_permits_a_withdrawal() -> None:
    people, _ = dossiers.load("autumn-1941")
    assert people["timoshenko"]["bio"] and people["timoshenko"]["arena"]
    assert "Stalin" in (people["timoshenko"]["arena"] or "")


def test_the_general_staff_and_stalin_are_up_his_chain() -> None:
    r = Rig("autumn-1941")
    chain = superiors(r.state.cards, EntityId(r.ids["timoshenko"]))
    assert EntityId(r.ids["shaposhnikov"]) in chain and EntityId(r.ids["stalin"]) in chain


def test_stalins_military_operations_still_name_the_front() -> None:
    stalin = _card(_world(), "stalin")
    (ops,) = [dm for dm in stalin.authority if dm.name == "military_operations"]
    assert FRONT in ops.forces and "move_force" in ops.effects


def test_a_mandate_reaches_him() -> None:
    world = _world()
    assert [m.key for m in world.mandates if "timoshenko" in m.to]


# --- rule 2: the locks, each decided by Stalin --------------------------------------------


def _rows(world: WorldFile) -> dict[str, Any]:
    return {r.key: r for r in world.locks if r.order.form == FORM}


def test_a_lock_on_a_withdrawal_behind_the_mozhaisk_line_for_stalin() -> None:
    rows = _rows(_world())
    assert set(rows) == {ROW}
    row = rows[ROW]
    assert row.order.form == FORM and row.order.params == {"to": BEHIND}
    assert row.decider.person == "stalin"
    assert row.question == "permission" and row.when is None


def test_a_row_whose_decider_is_the_issuer_does_not_compile() -> None:
    world = _world()
    rows = tuple(
        r.model_copy(update={"decider": r.decider.model_copy(update={"person": "timoshenko"})})
        if r.key == ROW
        else r
        for r in world.locks
    )
    with pytest.raises(WorldError, match="timoshenko carries the form and would decide"):
        _compile(world.model_copy(update={"locks": rows}))


def test_a_row_naming_a_missing_chamber_does_not_compile() -> None:
    world = _world()
    body = {"person": None, "nation": "ussr", "chambers": ("soviet",), "head": "stalin"}
    rows = tuple(
        r.model_copy(update={"decider": r.decider.model_copy(update=body)}) if r.key == ROW else r
        for r in world.locks
    )
    with pytest.raises(WorldError, match="ussr has no chamber soviet"):
        _compile(world.model_copy(update={"locks": rows}))


def _rig(*people: str) -> Rig:
    r = Rig("autumn-1941")
    for person in people:
        r.seat(person)
    r.close_session_zero()
    return r


def _order(r: Rig, lever: str, **params: str | int) -> Order:
    return Order(
        order_id=OrderId(derived_id(r.campaign, "order", f"nsu-{lever}-{sorted(params.items())}")),
        issuer=r.seats["timoshenko"],
        lever=lever,
        pipeline=PipelineId(r.ids["western_front_staff"]),
        params=params,
        filed=FILED,
    )


def test_a_withdrawal_behind_the_mozhaisk_line_is_held_for_stalin() -> None:
    r = _rig("timoshenko")
    order = _order(r, FORM, force=FRONT, to=BEHIND)
    lock = locks.lock_for(r.state, r.seats["timoshenko"], order)
    assert lock is not None and lock.decider.person == EntityId(r.ids["stalin"])
    assert lock.row is not None and locks.by_kind(r.state, lock.row)
    for free_to in ("mozhaisk", "vyazma"):
        free = _order(r, FORM, force=FRONT, to=free_to)
        assert locks.lock_for(r.state, r.seats["timoshenko"], free) is None, free_to


def _held_and_asked(r: Rig, order: Order) -> locks.Asked:
    seat = r.seats["timoshenko"]
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
def test_only_stalins_grant_opens_the_withdrawal(granted: bool) -> None:
    r = _rig("timoshenko")
    asked = _held_and_asked(r, _order(r, FORM, force=FRONT, to=BEHIND))
    assert asked.to == EntityId(r.ids["stalin"])
    held = r.state.held[asked.order_id]
    assert not locks.open_now(r.state, held)
    seat = r.seats["timoshenko"]
    r.add(ev.AskAnswered(order_id=asked.order_id, asker=seat, on=FILED, granted=granted))
    assert locks.open_now(r.state, r.state.held[asked.order_id]) is granted


# --- no body and no council ---------------------------------------------------------------


def test_the_soviet_union_has_no_body_and_no_council_that_decides_the_withdrawal() -> None:
    world = _world()
    (ussr,) = [d for d in world.groups if d.nation == "ussr"]
    assert not [g.key for g in ussr.groups if g.chamber is not None]
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


# --- rule 3: the record's move of 24 October ----------------------------------------------


def _front(r: Rig) -> Any:
    return r.state.features[FeatureId(r.ids[FRONT])]


def test_the_fronts_move_to_moscow_on_24_october_runs_with_the_switches_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = _season(without_third_run(_world()), monkeypatch)
    front = _front(r)
    assert front.legs == ()  # the leg of 24 October was taken
    assert front.places == (EntityId(r.ids["moscow_area"]),)  # the area Moscow is in


def test_with_a_player_in_his_seat_the_records_move_stays_until_he_sends_the_front() -> None:
    r = _rig("timoshenko")
    assert [leg.since for leg in _front(r).legs] == [date(1941, 10, 24)]
    order = _order(r, FORM, force=FRONT, to="vyazma").model_copy(
        update={"status": OrderStatus.ENACTED}
    )
    r.fold_changes(movement.order_changes(r.state, order))
    assert _front(r).legs == ()  # history steps aside: his order drops the record's move


def test_with_the_third_run_switches_out_his_locks_stay() -> None:
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
