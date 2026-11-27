"""1941: the Italian Battle Fleet's commander and his locks (NIT).

Admiral Iachino, Commander in Chief of the Battle Fleet, is a military card the players may
claim: his own forms move and detach the Italian Battle Fleet through his own staff with no
step above him; he answers to the Chief of the Comando Supremo, and so to Mussolini, and
cables him; he has three aims with conditions, two filled from the fleet commander's
patterns and one the default a player's own aim would replace. Mussolini keeps his order over
the fleet: his supreme command names the forces it commands, so with both acting on the fleet
in one wake his order stands.

Two locks hold a sortie of the fleet east of the Sicilian narrows: sending the fleet, or part
of it, to Bardia on the eastern Mediterranean is Mussolini's to permit. Neither row has a
condition, so only his grant opens it. Italy has no body and no council that decides.

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
from revisionist.core.realism.pipeline import Order
from revisionist.core.state import Rule
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, check_history, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine.web import dossiers
from tests.test_realism_resolvers import Rig
from tests.test_rule_names import BASELINE_1941
from tests.test_world_forces import with_parts
from tests.test_world_locks_1941 import run_digest
from tests.test_world_locks_uk_1941 import without_third_run

ON = "5cb9d48860d1833b119a377cd7b0863d"
"""The scripted run's digest with the 1941 world's third-run switches on, recorded once by
this item. It equals the baseline: the script seats the President alone and files no order
the new locks hold."""

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
FILED = date(1941, 11, 20)
FORMS = ("battle_fleet_move", "battle_fleet_detach")
ROWS = ("battle_fleet_sortie_east", "battle_fleet_detachment_east")
"""The rows Mussolini decides: the move and the detachment east of the Sicilian narrows."""
EAST = "bardia"
"""The place on the eastern Mediterranean the fleet's forms reach. [proposed]"""
FORCES = with_parts("italian_fleet", "italian_army", "italian_army_libya")
"""The forces Mussolini's supreme command names, the parts split from them with them (KDA)."""
FILLED: dict[int, tuple[str, dict[str, JsonValue]]] = {
    1: ("hold_and_take", {"held": "tripolitania", "place": "british_islands"}),
    2: ("take_ground", {"place": "tobruk_area"}),
}
"""Iachino's two aims from the fleet commander's patterns, with the values filled in."""


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def _card(world: WorldFile, person: str) -> Any:
    return next(c for c in world.cards if c.person == person)


def _compile(world: WorldFile) -> None:
    compile_world(world, CAMPAIGN, cmp.versions())


# --- rule 1: the commander's card ------------------------------------------------------


def test_the_battle_fleet_commander_is_a_playable_military_card_on_the_roster() -> None:
    world = _world()
    iachino = _card(world, "iachino")
    assert iachino.office == "Commander in Chief, Battle Fleet"
    assert iachino.playable and iachino.path is CardPath.MILITARY
    assert iachino.post_kind == "fleet_commander"
    assert iachino.principals == ("cavallero",)
    assert "iachino" in {c.entity for c in world.roster}
    _compile(world)


def test_his_domain_names_the_battle_fleet_and_no_other_military_card_does() -> None:
    world = _world()
    forces = {k for dm in _card(world, "iachino").authority for k in dm.forces}
    assert forces == {"italian_fleet"}
    others = {
        k
        for c in world.cards
        if c.person != "iachino" and c.path is CardPath.MILITARY
        for dm in c.authority
        for k in dm.forces
    }
    assert "italian_fleet" not in others


def test_the_commander_with_no_force_does_not_compile() -> None:
    world = _world()
    bare = _card(world, "iachino").model_copy(update={"authority": ()})
    cards = tuple(bare if c.person == "iachino" else c for c in world.cards)
    by_hand = tuple(r for r in world.rules if r != Rule.PLAYABLE_RULE)
    with pytest.raises(WorldError, match="a playable military card needs a domain naming a force"):
        _compile(world.model_copy(update={"cards": cards, "rules": by_hand}))
    with pytest.raises(WorldError, match=r"iachino: on the roster, .* a commander with no force"):
        _compile(world.model_copy(update={"cards": cards}))


def test_his_own_forms_move_and_detach_through_a_pipeline_with_no_step_above_him() -> None:
    world = _world()
    levers = {lv.name: lv for lv in _card(world, "iachino").levers}
    assert set(levers) == set(FORMS)
    for lv in levers.values():
        pipeline = next(p for p in world.pipelines if p.key == lv.pipeline)
        assert [s.person for s in pipeline.steps] == ["iachino"], lv.name
        force = next(p for p in lv.params if p.name == "force")
        assert force.choices == ("italian_fleet",)
        to = next(p for p in lv.params if p.name == "to")
        assert set(to.choices) == {"taranto", "tripoli", EAST}


def test_his_detachment_offers_only_a_strength_the_fleet_can_spare() -> None:
    world = _world()
    detach = next(lv for lv in _card(world, "iachino").levers if lv.name == FORMS[1])
    strength = next(p for p in detach.params if p.name == "strength")
    fleet = next(f for f in world.features if f.key == "italian_fleet")
    assert strength.lo == 1 and strength.hi == fleet.tier - 1


def test_he_cables_the_chief_of_the_comando_supremo() -> None:
    iachino = _card(_world(), "iachino")
    assert ("cavallero", "cable") in {(k.person, k.channel) for k in iachino.inner_circle}


def test_he_has_three_aims_two_from_the_fleet_commanders_patterns_the_third_replaceable() -> None:
    world = _world()
    iachino = _card(world, "iachino")
    assert len(iachino.aims) == 3
    rules = {r.aim: r for r in iachino.aim_rules}
    assert sorted(rules) == [1, 2, 3]
    assert [rules[n].replaceable for n in (1, 2, 3)] == [False, False, True]
    patterns = {p.key: p for p in world.aim_patterns}
    for n, (key, values) in FILLED.items():
        pattern = patterns[key]
        assert "fleet_commander" in pattern.posts
        filled = build(pattern.condition, {**values, "nation": "italy", "person": "iachino"})
        assert rules[n].condition == filled, n


def test_he_holds_a_post_that_meets_the_character_rule() -> None:
    held = [a for a in _world().assets if a.controller == "iachino"]
    assert held and max(a.tier for a in held) >= 2


def test_his_dossier_has_a_line_that_says_the_duce_permits_a_sortie() -> None:
    people, _ = dossiers.load("autumn-1941")
    assert people["iachino"]["bio"] and people["iachino"]["arena"]
    assert "Duce" in (people["iachino"]["arena"] or "")


def test_the_comando_supremo_and_mussolini_are_up_his_chain() -> None:
    r = Rig("autumn-1941")
    chain = superiors(r.state.cards, EntityId(r.ids["iachino"]))
    assert EntityId(r.ids["cavallero"]) in chain and EntityId(r.ids["mussolini"]) in chain


# --- rule 3: Mussolini's supreme command names its forces ----------------------------------


def test_mussolinis_supreme_command_names_the_forces_it_commands() -> None:
    mussolini = _card(_world(), "mussolini")
    (supreme,) = [dm for dm in mussolini.authority if dm.name == "supreme_command"]
    assert set(supreme.forces) == FORCES
    assert "move_force" in supreme.effects and supreme.executor == "cavallero"


def test_every_force_mussolinis_move_forms_name_is_in_his_supreme_command() -> None:
    mussolini = _card(_world(), "mussolini")
    (supreme,) = [dm for dm in mussolini.authority if dm.name == "supreme_command"]
    named = {
        choice
        for lv in mussolini.levers
        if lv.name in {"move_fleet", "move_army"}
        for p in lv.params
        if p.name == "force"
        for choice in p.choices
    }
    assert named == FORCES and named <= set(supreme.forces)


# --- rule 2: the locks, each decided by Mussolini -----------------------------------------


def _rows(world: WorldFile) -> dict[str, Any]:
    return {r.key: r for r in world.locks if r.order.form in set(FORMS)}


def test_two_locks_on_a_sortie_east_of_the_narrows_each_for_mussolini() -> None:
    rows = _rows(_world())
    assert set(rows) == set(ROWS)
    for key, form in zip(ROWS, FORMS, strict=True):
        row = rows[key]
        assert row.order.form == form and row.order.params == {"to": EAST}, key
        assert row.decider.person == "mussolini", key
        assert row.question == "permission" and row.when is None, key


def test_a_row_whose_decider_is_the_issuer_does_not_compile() -> None:
    world = _world()
    rows = tuple(
        r.model_copy(update={"decider": r.decider.model_copy(update={"person": "iachino"})})
        if r.key == ROWS[0]
        else r
        for r in world.locks
    )
    with pytest.raises(WorldError, match="iachino carries the form and would decide"):
        _compile(world.model_copy(update={"locks": rows}))


def test_a_row_naming_a_missing_chamber_does_not_compile() -> None:
    world = _world()
    body = {"person": None, "nation": "italy", "chambers": ("camera",), "head": "mussolini"}
    rows = tuple(
        r.model_copy(update={"decider": r.decider.model_copy(update=body)})
        if r.key == ROWS[0]
        else r
        for r in world.locks
    )
    with pytest.raises(WorldError, match="italy has no chamber camera"):
        _compile(world.model_copy(update={"locks": rows}))


def _rig(*people: str) -> Rig:
    r = Rig("autumn-1941")
    for person in people:
        r.seat(person)
    r.close_session_zero()
    return r


def _order(r: Rig, lever: str, **params: str | int) -> Order:
    return Order(
        order_id=OrderId(derived_id(r.campaign, "order", f"nit-{lever}-{sorted(params.items())}")),
        issuer=r.seats["iachino"],
        lever=lever,
        pipeline=PipelineId(r.ids["battle_fleet_staff"]),
        params=params,
        filed=FILED,
    )


@pytest.mark.parametrize(("lever", "extra"), [(FORMS[0], {}), (FORMS[1], {"strength": 2})])
def test_a_sortie_east_of_the_narrows_is_held_for_mussolini(
    lever: str, extra: dict[str, int]
) -> None:
    r = _rig("iachino")
    order = _order(r, lever, force="italian_fleet", to=EAST, **extra)
    lock = locks.lock_for(r.state, r.seats["iachino"], order)
    assert lock is not None and lock.decider.person == EntityId(r.ids["mussolini"])
    assert lock.row is not None and locks.by_kind(r.state, lock.row)
    free = _order(r, lever, force="italian_fleet", to="tripoli", **extra)
    assert locks.lock_for(r.state, r.seats["iachino"], free) is None


def _held_and_asked(r: Rig, order: Order) -> locks.Asked:
    seat = r.seats["iachino"]
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
def test_only_mussolinis_grant_opens_the_sortie(granted: bool) -> None:
    r = _rig("iachino")
    asked = _held_and_asked(r, _order(r, FORMS[0], force="italian_fleet", to=EAST))
    assert asked.to == EntityId(r.ids["mussolini"])
    held = r.state.held[asked.order_id]
    assert not locks.open_now(r.state, held)
    seat = r.seats["iachino"]
    r.add(ev.AskAnswered(order_id=asked.order_id, asker=seat, on=FILED, granted=granted))
    assert locks.open_now(r.state, r.state.held[asked.order_id]) is granted


# --- no body and no council ---------------------------------------------------------------


def test_italy_has_no_body_and_no_council_that_decides_the_sortie() -> None:
    world = _world()
    (italy,) = [d for d in world.groups if d.nation == "italy"]
    assert not [g.key for g in italy.groups if g.chamber is not None]
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
