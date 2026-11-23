"""1941: the Home Fleet's commander, the Commons as a body, and his two locks (NUK).

Admiral Tovey, Commander in Chief, Home Fleet, is a military card the players may claim: his
own forms move and detach the Home Fleet through his own staff with no step above him; he
answers to the First Sea Lord, and so to the Prime Minister, and cables the Prime Minister;
he has three aims with conditions, two filled from the fleet commander's patterns and one
the default a player's own aim would replace. The Prime Minister keeps his order over the
fleet, so with both acting on it in one wake his order stands.

Britain's groups gain a chamber, the Commons, as three blocs with seats, and one law, the
National Service bill, with its passed quantity and the blocs' rows for it. Two locks hold
the commander's orders: lending the fleet's strength to the Western Approaches waits on the
Prime Minister's convoy priority, and basing the fleet at Iceland waits on the National
Service bill, which the Commons passes and the Prime Minister answers for.

The scripted run's digest (``run_digest``) with the third-run switches taken out of a copy's
rules is the baseline; with them on it is recorded here once.
"""

from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import JsonValue

from revisionist.core.aim_patterns import build
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, OrderId, PipelineId, derived_id
from revisionist.core.realism import locks
from revisionist.core.realism.card import CardPath, superiors
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.resolvers import votes
from revisionist.core.state import Rule
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, check_history, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine.web import dossiers
from tests.test_realism_resolvers import Rig
from tests.test_rule_names import BASELINE_1941, THIRD_RUN
from tests.test_world_locks_1941 import run_digest

ON = "45f00e1d6cb09e84245f4a7affb44692"
"""The scripted run's digest with the 1941 world's third-run switches on, recorded once by
this item. It equals the baseline: the script seats the President alone, files no order the
two new locks hold, and no happening of the run moves the Commons' blocs."""

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
FILED = date(1941, 9, 20)
BLOCS = ("commons_government", "commons_labour", "commons_others")
LAW = "national_service"
FILLED: dict[int, tuple[str, dict[str, JsonValue]]] = {
    1: ("hold_and_take", {"held": "iceland", "place": "norway"}),
    2: ("raise_group", {"group": "public", "line": 80}),
}
"""Tovey's two aims from the fleet commander's patterns, with the values filled in."""
NEW_PEOPLE = 8
"""The playable people this run's nation items add to 1941: a commander each for Britain,
Germany, Japan, Italy, the Soviet Union and China, and Finland's two."""


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def _card(world: WorldFile, person: str) -> Any:
    return next(c for c in world.cards if c.person == person)


def _compile(world: WorldFile) -> None:
    compile_world(world, CAMPAIGN, cmp.versions())


def without_third_run(world: WorldFile) -> WorldFile:
    """A copy of ``world`` with every third-run switch taken out of its rules, and the lock
    rows that read a law only the world declares with them: with ``laws`` off no such law is
    in the game, and the compiler refuses a row whose clause it cannot find."""
    tabled = {c.subject for m in votes.HISTORICAL.values() for c in m.clauses}
    rows = tuple(
        r
        for r in world.locks
        if r.when is None or r.when.check != "law_not_in_force" or r.when.clause in tabled
    )
    rules = tuple(r for r in world.rules if r not in THIRD_RUN)
    return world.model_copy(update={"rules": rules, "locks": rows})


def _uk_groups(world: WorldFile) -> dict[str, Any]:
    (uk,) = [d for d in world.groups if d.nation == "uk"]
    return {g.key: g for g in uk.groups}


# --- rule 1: the commander's card ------------------------------------------------------


def test_the_home_fleet_commander_is_a_playable_military_card_on_the_roster() -> None:
    world = _world()
    tovey = _card(world, "tovey")
    assert tovey.office == "Commander in Chief, Home Fleet"
    assert tovey.playable and tovey.path is CardPath.MILITARY
    assert tovey.post_kind == "fleet_commander"
    assert tovey.principals == ("pound",)
    assert "tovey" in {c.entity for c in world.roster}
    _compile(world)


def test_his_domain_names_the_home_fleet_and_no_other_military_card_does() -> None:
    world = _world()
    forces = {k for dm in _card(world, "tovey").authority for k in dm.forces}
    assert forces == {"home_fleet"}
    others = {
        k
        for c in world.cards
        if c.person != "tovey" and c.path is CardPath.MILITARY
        for dm in c.authority
        for k in dm.forces
    }
    assert "home_fleet" not in others


def test_the_commander_with_no_force_does_not_compile() -> None:
    world = _world()
    bare = _card(world, "tovey").model_copy(update={"authority": ()})
    cards = tuple(bare if c.person == "tovey" else c for c in world.cards)
    with pytest.raises(WorldError, match="a playable military card needs a domain naming a force"):
        _compile(world.model_copy(update={"cards": cards}))


def test_his_own_forms_move_and_detach_through_a_pipeline_with_no_step_above_him() -> None:
    world = _world()
    levers = {lv.name: lv for lv in _card(world, "tovey").levers}
    assert set(levers) == {"home_fleet_move", "home_fleet_detach"}
    for lv in levers.values():
        pipeline = next(p for p in world.pipelines if p.key == lv.pipeline)
        assert [s.person for s in pipeline.steps] == ["tovey"], lv.name
        force = next(p for p in lv.params if p.name == "force")
        assert force.choices == ("home_fleet",)
    assert "strength" in {p.name for p in levers["home_fleet_detach"].params}


def test_he_cables_the_prime_minister() -> None:
    tovey = _card(_world(), "tovey")
    assert ("churchill", "cable") in {(k.person, k.channel) for k in tovey.inner_circle}


def test_he_has_three_aims_two_from_the_fleet_commanders_patterns_the_third_replaceable() -> None:
    world = _world()
    tovey = _card(world, "tovey")
    assert len(tovey.aims) == 3
    rules = {r.aim: r for r in tovey.aim_rules}
    assert sorted(rules) == [1, 2, 3]
    assert [rules[n].replaceable for n in (1, 2, 3)] == [False, False, True]
    patterns = {p.key: p for p in world.aim_patterns}
    for n, (key, values) in FILLED.items():
        pattern = patterns[key]
        assert "fleet_commander" in pattern.posts
        filled = build(pattern.condition, {**values, "nation": "uk", "person": "tovey"})
        assert rules[n].condition == filled, n


def test_he_holds_a_post_that_meets_the_character_rule() -> None:
    held = [a for a in _world().assets if a.controller == "tovey"]
    assert held and max(a.tier for a in held) >= 2


def test_his_dossier_has_a_line() -> None:
    people, _ = dossiers.load("autumn-1941")
    assert people["tovey"]["bio"] and people["tovey"]["arena"]


# --- rule 2: the Prime Minister keeps the fleet -----------------------------------------


def test_the_prime_minister_keeps_his_order_over_the_fleet_and_is_up_the_chain() -> None:
    world = _world()
    forces = {k for dm in _card(world, "churchill").authority for k in dm.forces}
    assert "home_fleet" in forces
    r = Rig("autumn-1941")
    chain = superiors(r.state.cards, EntityId(r.ids["tovey"]))
    assert EntityId(r.ids["churchill"]) in chain


# --- rule 3: the Commons, its blocs and the law ------------------------------------------


def test_the_commons_is_a_chamber_of_three_blocs_with_seats() -> None:
    found = _uk_groups(_world())
    for key in BLOCS:
        assert found[key].chamber == "commons", key
        assert found[key].seats is not None
    assert sum(found[k].seats or 0 for k in BLOCS) == 615
    assert "commons" in found and found["commons"].chamber is None


def test_the_law_binds_britain_and_its_key_is_the_blocs_rows() -> None:
    world = _world()
    (law,) = [x for x in world.laws if x.nation == "uk"]
    assert law.key == LAW
    assert law.passed in {q.key for q in world.quantities}
    found = _uk_groups(world)
    for key in BLOCS:
        assert set(found[key].votes) == {law.key}, key
        assert set(found[key].votes[law.key]) == {"commons"}, key


def test_the_commons_tallies_the_law_from_its_blocs() -> None:
    r = Rig("autumn-1941")
    uk = EntityId(r.ids["uk"])
    assert votes.bloc_votes(r.state, uk, LAW) == (("commons", "commons"),)
    rows = [g.votes[LAW]["commons"] for g in _uk_groups(_world()).values() if g.chamber]
    seed = OrderId(derived_id(r.campaign, "order", "nuk-tally"))
    assert votes.bloc_tally(r.state, uk, "commons", LAW, "commons", seed) == (
        sum(x.yeas for x in rows),
        sum(x.voting - x.yeas for x in rows),
    )


# --- rule 4: the two locks ----------------------------------------------------------------


def _rows(world: WorldFile) -> dict[str, Any]:
    return {
        r.key: r for r in world.locks if r.order.form in {"home_fleet_move", "home_fleet_detach"}
    }


def test_two_locks_one_for_the_prime_minister_one_for_the_commons() -> None:
    rows = _rows(_world())
    assert set(rows) == {"home_fleet_to_the_atlantic", "home_fleet_based_at_iceland"}
    lend, base = rows["home_fleet_to_the_atlantic"], rows["home_fleet_based_at_iceland"]
    assert lend.order.form == "home_fleet_detach" and lend.order.params == {"to": "liverpool"}
    assert lend.decider.person == "churchill"
    assert lend.when is not None and lend.when.check == "posture_not_set"
    assert lend.when.form == "convoy_orders"
    assert base.order.form == "home_fleet_move" and base.order.params == {"to": "reykjavik"}
    assert base.decider.nation == "uk" and base.decider.chambers == ("commons",)
    assert base.decider.head == "churchill"
    assert base.when is not None and base.when.check == "law_not_in_force"
    (law,) = [x for x in _world().laws if x.key == LAW]
    assert base.when.clause in {c.subject for c in law.clauses}


def test_a_row_naming_a_missing_chamber_does_not_compile() -> None:
    world = _world()
    rows = tuple(
        r.model_copy(
            update={"decider": r.decider.model_copy(update={"chambers": ("house_of_lords",)})}
        )
        if r.key == "home_fleet_based_at_iceland"
        else r
        for r in world.locks
    )
    with pytest.raises(WorldError, match="uk has no chamber house_of_lords"):
        _compile(world.model_copy(update={"locks": rows}))


def _rig() -> Rig:
    r = Rig("autumn-1941")
    r.seat("churchill")
    r.seat("tovey")
    r.close_session_zero()
    return r


def _order(r: Rig, lever: str, **params: str | int) -> Order:
    return Order(
        order_id=OrderId(derived_id(r.campaign, "order", f"nuk-{lever}-{sorted(params.items())}")),
        issuer=r.seats["tovey"],
        lever=lever,
        pipeline=PipelineId(r.ids["home_fleet_staff"]),
        params=params,
        filed=FILED,
    )


def test_lending_the_fleet_to_the_atlantic_waits_on_the_prime_ministers_priority() -> None:
    r = _rig()
    order = _order(r, "home_fleet_detach", force="home_fleet", to="liverpool", strength=2)
    lock = locks.lock_for(r.state, r.seats["tovey"], order)
    assert lock is not None and lock.decider.person == EntityId(r.ids["churchill"])
    free = _order(r, "home_fleet_detach", force="home_fleet", to="scapa_flow", strength=2)
    assert locks.lock_for(r.state, r.seats["tovey"], free) is None
    d = date(1941, 9, 11)
    r.enact(
        "churchill",
        "convoy_orders",
        "cos_directive",
        d,
        [d + timedelta(days=2), d + timedelta(days=3)],
        priority="atlantic",
        route="hx_route",
    )
    assert locks.lock_for(r.state, r.seats["tovey"], order) is None


def test_basing_the_fleet_at_iceland_waits_on_the_law_with_the_commons_deciding() -> None:
    r = _rig()
    order = _order(r, "home_fleet_move", force="home_fleet", to="reykjavik")
    lock = locks.lock_for(r.state, r.seats["tovey"], order)
    assert lock is not None and lock.decider.nation == EntityId(r.ids["uk"])
    assert locks.asked_of(lock.decider) == EntityId(r.ids["churchill"])
    free = _order(r, "home_fleet_move", force="home_fleet", to="scapa_flow")
    assert locks.lock_for(r.state, r.seats["tovey"], free) is None
    r.set_value("national_service_passed", 1, as_of=date(1941, 12, 2))
    assert locks.lock_for(r.state, r.seats["tovey"], order) is None


# --- rule 5: the roster holds the run's new people ----------------------------------------


def test_the_roster_limit_holds_the_runs_new_people() -> None:
    world = _world()
    assert world.roster_limit is not None
    least, most = world.roster_limit
    assert least <= len(world.roster) <= most
    assert most >= len(world.roster) - 1 + NEW_PEOPLE
    assert not [p for p in check_history(world) if p.startswith("roster")]


# --- rule 7: the scripted run -------------------------------------------------------------


def test_with_the_third_run_switches_out_the_world_still_compiles() -> None:
    state = replay(compile_world(without_third_run(_world()), CAMPAIGN, cmp.versions()))
    assert not {r.value for r in state.rules} & set(THIRD_RUN)
    assert Rule.LOCKS in state.rules
    assert [r.key for r in without_third_run(_world()).locks] == [
        "iceland_shoot_on_sight",
        "war_zone_escort",
        "home_fleet_to_the_atlantic",
    ]


def test_the_scripted_run_is_the_baseline_with_the_third_run_switches_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(without_third_run(_world()), monkeypatch) == BASELINE_1941


def test_the_scripted_run_with_the_third_run_switches_on_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(_world(), monkeypatch) == ON
