"""1941: the Combined Fleet's commander, the Liaison Conference as a council, and his locks (NJP).

Admiral Yamamoto, Commander in Chief of the Combined Fleet, is a military card the players may
claim: his own forms move and detach the Combined Fleet through his own staff with no step
above him; he answers to the Chief of the Navy General Staff, and cables him; he has three aims
with conditions, two filled from the fleet commander's patterns and one the default a player's
own aim would replace.

Two locks hold his orders, each over both his forms. Sending the fleet, or part of it, against
Pearl Harbor opens hostilities with the United States: a question of war for the Liaison
Conference, a council of the cards that sit on it, all of whom must agree, with the Prime
Minister the head an ask goes to. Gathering the fleet at Hitokappu Bay waits on the Navy chief's
permission. Neither row has a condition, so only a granted ask opens it, and no form is asked of
the conference's members. The world switches ``deciders`` on, so the council decides.

The scripted run's digest (``run_digest``) with the third-run switches taken out of a copy's
rules is the baseline; with them on it is recorded here once. The record's move of the fleet to
Hitokappu Bay on 22 November still runs with the switches out.
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
from revisionist.core.realism.pipeline import Order
from revisionist.core.state import Rule
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, check_history, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine.web import dossiers
from tests import test_realism_bands as bands
from tests.test_realism_resolvers import Rig
from tests.test_rule_names import BASELINE_1941
from tests.test_world_locks_1941 import run_digest
from tests.test_world_locks_uk_1941 import without_third_run

ON = "45f00e1d6cb09e84245f4a7affb44692"
"""The scripted run's digest with the 1941 world's third-run switches on, ``deciders`` among
them, recorded once by this item. It equals the baseline: the script seats the President
alone and files no order the new locks hold."""

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
FILED = date(1941, 11, 20)
WAR = ("pearl_harbor_strike", "pearl_harbor_detachment")
"""The rows the Liaison Conference decides: the move and the detachment against Pearl Harbor."""
GATHER = ("hitokappu_bay_gathering", "hitokappu_bay_detachment")
"""The rows the Navy chief decides: the move and the detachment to Hitokappu Bay."""
MEMBERS = ("konoe", "tojo", "sugiyama", "nagano")
"""The Liaison Conference's members that have cards. [proposed]"""
FILLED: dict[int, tuple[str, dict[str, JsonValue]]] = {
    1: ("hold_and_take", {"held": "japan_west", "place": "hawaii"}),
    2: ("raise_group", {"group": "navy", "line": 80}),
}
"""Yamamoto's two aims from the fleet commander's patterns, with the values filled in."""


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def _card(world: WorldFile, person: str) -> Any:
    return next(c for c in world.cards if c.person == person)


def _compile(world: WorldFile) -> None:
    compile_world(world, CAMPAIGN, cmp.versions())


# --- rule 1: the commander's card ------------------------------------------------------


def test_the_combined_fleet_commander_is_a_playable_military_card_on_the_roster() -> None:
    world = _world()
    yamamoto = _card(world, "yamamoto")
    assert yamamoto.office == "Commander in Chief, Combined Fleet"
    assert yamamoto.playable and yamamoto.path is CardPath.MILITARY
    assert yamamoto.post_kind == "fleet_commander"
    assert yamamoto.principals == ("nagano",)
    assert "yamamoto" in {c.entity for c in world.roster}
    _compile(world)


def test_his_domain_names_the_combined_fleet_and_no_other_military_card_does() -> None:
    world = _world()
    forces = {k for dm in _card(world, "yamamoto").authority for k in dm.forces}
    assert forces == {"combined_fleet"}
    others = {
        k
        for c in world.cards
        if c.person != "yamamoto" and c.path is CardPath.MILITARY
        for dm in c.authority
        for k in dm.forces
    }
    assert "combined_fleet" not in others


def test_the_commander_with_no_force_does_not_compile() -> None:
    world = _world()
    bare = _card(world, "yamamoto").model_copy(update={"authority": ()})
    cards = tuple(bare if c.person == "yamamoto" else c for c in world.cards)
    by_hand = tuple(r for r in world.rules if r != Rule.PLAYABLE_RULE)
    with pytest.raises(WorldError, match="a playable military card needs a domain naming a force"):
        _compile(world.model_copy(update={"cards": cards, "rules": by_hand}))
    with pytest.raises(WorldError, match=r"yamamoto: on the roster, .* a commander with no force"):
        _compile(world.model_copy(update={"cards": cards}))


def test_his_own_forms_move_and_detach_through_a_pipeline_with_no_step_above_him() -> None:
    world = _world()
    levers = {lv.name: lv for lv in _card(world, "yamamoto").levers}
    assert set(levers) == {"combined_fleet_move", "combined_fleet_detach"}
    for lv in levers.values():
        pipeline = next(p for p in world.pipelines if p.key == lv.pipeline)
        assert [s.person for s in pipeline.steps] == ["yamamoto"], lv.name
        force = next(p for p in lv.params if p.name == "force")
        assert force.choices == ("combined_fleet",)
        to = next(p for p in lv.params if p.name == "to")
        assert {"kure", "hitokappu_bay", "pearl_harbor_base"} == set(to.choices)


def test_his_detachment_offers_only_a_strength_the_fleet_can_spare() -> None:
    world = _world()
    detach = next(
        lv for lv in _card(world, "yamamoto").levers if lv.name == "combined_fleet_detach"
    )
    strength = next(p for p in detach.params if p.name == "strength")
    fleet = next(f for f in world.features if f.key == "combined_fleet")
    assert strength.lo == 1 and strength.hi == fleet.tier - 1


def test_he_cables_the_chief_of_the_navy_general_staff() -> None:
    yamamoto = _card(_world(), "yamamoto")
    assert ("nagano", "cable") in {(k.person, k.channel) for k in yamamoto.inner_circle}


def test_he_has_three_aims_two_from_the_fleet_commanders_patterns_the_third_replaceable() -> None:
    world = _world()
    yamamoto = _card(world, "yamamoto")
    assert len(yamamoto.aims) == 3
    rules = {r.aim: r for r in yamamoto.aim_rules}
    assert sorted(rules) == [1, 2, 3]
    assert [rules[n].replaceable for n in (1, 2, 3)] == [False, False, True]
    patterns = {p.key: p for p in world.aim_patterns}
    for n, (key, values) in FILLED.items():
        pattern = patterns[key]
        assert "fleet_commander" in pattern.posts
        filled = build(pattern.condition, {**values, "nation": "japan", "person": "yamamoto"})
        assert rules[n].condition == filled, n


def test_he_holds_a_post_that_meets_the_character_rule() -> None:
    held = [a for a in _world().assets if a.controller == "yamamoto"]
    assert held and max(a.tier for a in held) >= 2


def test_his_dossier_has_a_line_that_names_the_conference() -> None:
    people, _ = dossiers.load("autumn-1941")
    assert people["yamamoto"]["bio"] and people["yamamoto"]["arena"]
    assert "Liaison Conference" in (people["yamamoto"]["arena"] or "")


def test_the_navy_chief_and_the_emperor_are_up_his_chain() -> None:
    r = Rig("autumn-1941")
    chain = superiors(r.state.cards, EntityId(r.ids["yamamoto"]))
    assert EntityId(r.ids["nagano"]) in chain and EntityId(r.ids["hirohito"]) in chain


# --- rule 2: the Liaison Conference as a council --------------------------------------------


def _rows(world: WorldFile) -> dict[str, Any]:
    forms = {"combined_fleet_move", "combined_fleet_detach"}
    return {r.key: r for r in world.locks if r.order.form in forms}


def test_the_world_switches_deciders_on() -> None:
    assert Rule.DECIDERS.value in _world().rules


def test_the_conference_decides_opening_hostilities_against_pearl_harbor() -> None:
    rows = _rows(_world())
    assert set(WAR) <= set(rows)
    for key, form in zip(WAR, ("combined_fleet_move", "combined_fleet_detach"), strict=True):
        row = rows[key]
        assert row.order.form == form and row.order.params == {"to": "pearl_harbor_base"}
        assert row.question == "war" and row.when is None, key
        council = row.decider.council
        assert council is not None and row.decider.person is None, key
        assert set(council.members) == set(MEMBERS) and council.head == "konoe"
        assert 1 <= council.needed <= len(council.members)


def test_every_member_of_the_conference_has_a_card() -> None:
    world = _world()
    carded = {c.person for c in world.cards}
    for key in WAR:
        council = _rows(world)[key].decider.council
        assert council is not None and set(council.members) <= carded


def _struck(world: WorldFile, person: str) -> WorldFile:
    return world.model_copy(update={"cards": tuple(c for c in world.cards if c.person != person)})


def test_the_conferences_row_is_refused_when_a_member_is_struck_from_the_cards() -> None:
    with pytest.raises(WorldError, match="council member sugiyama has no card"):
        _compile(_struck(_world(), "sugiyama"))


def test_the_conferences_count_above_its_members_is_refused() -> None:
    world = _world()
    rows = []
    for r in world.locks:
        if r.key == WAR[0]:
            assert r.decider.council is not None
            council = r.decider.council.model_copy(update={"needed": len(MEMBERS) + 1})
            r = r.model_copy(update={"decider": r.decider.model_copy(update={"council": council})})
        rows.append(r)
    with pytest.raises(WorldError, match=f"a council needs {len(MEMBERS) + 1} of {len(MEMBERS)}"):
        _compile(world.model_copy(update={"locks": tuple(rows)}))


# --- rule 3: a lock the Navy chief decides --------------------------------------------------


def test_the_navy_chief_decides_gathering_the_fleet_at_hitokappu_bay() -> None:
    world = _world()
    rows = _rows(world)
    assert set(rows) == set(WAR) | set(GATHER)
    for key, form in zip(GATHER, ("combined_fleet_move", "combined_fleet_detach"), strict=True):
        row = rows[key]
        assert row.order.form == form and row.order.params == {"to": "hitokappu_bay"}
        assert row.decider.person == "nagano" and row.decider.council is None, key
        assert row.question == "permission" and row.when is None, key
    assert not {lv.name for lv in _card(world, "nagano").levers} & {
        "combined_fleet_move",
        "combined_fleet_detach",
    }


# --- rule 4: no form is asked of Konoe or Tojo ----------------------------------------------


def test_no_row_asks_a_form_of_the_conferences_members() -> None:
    for row in _rows(_world()).values():
        assert row.when is None, row.key


# --- the rows in play -----------------------------------------------------------------------


def _rig(*people: str) -> Rig:
    r = Rig("autumn-1941")
    for person in people:
        r.seat(person)
    r.close_session_zero()
    return r


def _order(r: Rig, lever: str, **params: str | int) -> Order:
    return Order(
        order_id=OrderId(derived_id(r.campaign, "order", f"njp-{lever}-{sorted(params.items())}")),
        issuer=r.seats["yamamoto"],
        lever=lever,
        pipeline=PipelineId(r.ids["combined_fleet_staff"]),
        params=params,
        filed=FILED,
    )


@pytest.mark.parametrize(
    ("lever", "extra"), [("combined_fleet_move", {}), ("combined_fleet_detach", {"strength": 2})]
)
def test_the_strike_on_pearl_harbor_is_held_for_the_conference(
    lever: str, extra: dict[str, int]
) -> None:
    r = _rig("yamamoto")
    order = _order(r, lever, force="combined_fleet", to="pearl_harbor_base", **extra)
    lock = locks.lock_for(r.state, r.seats["yamamoto"], order)
    assert lock is not None and lock.decider.council is not None
    assert set(lock.decider.council.members) == {EntityId(r.ids[m]) for m in MEMBERS}
    assert lock.decider.council.head == EntityId(r.ids["konoe"])
    assert lock.row is not None and locks.by_kind(r.state, lock.row)
    free = _order(r, lever, force="combined_fleet", to="kure", **extra)
    assert locks.lock_for(r.state, r.seats["yamamoto"], free) is None


@pytest.mark.parametrize(
    ("lever", "extra"), [("combined_fleet_move", {}), ("combined_fleet_detach", {"strength": 2})]
)
def test_gathering_at_hitokappu_bay_is_held_for_the_navy_chief(
    lever: str, extra: dict[str, int]
) -> None:
    r = _rig("yamamoto")
    order = _order(r, lever, force="combined_fleet", to="hitokappu_bay", **extra)
    lock = locks.lock_for(r.state, r.seats["yamamoto"], order)
    assert lock is not None and lock.decider.person == EntityId(r.ids["nagano"])
    assert lock.row is not None and locks.by_kind(r.state, lock.row)


def _held_and_asked(r: Rig, order: Order) -> locks.Asked:
    seat = r.seats["yamamoto"]
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


def test_the_ask_goes_to_the_prime_minister_and_is_before_each_member_a_seat_holds() -> None:
    r = _rig("yamamoto", "konoe", "tojo")
    asked = _held_and_asked(
        r, _order(r, "combined_fleet_move", force="combined_fleet", to="pearl_harbor_base")
    )
    assert asked.to == EntityId(r.ids["konoe"])
    assert set(asked.seats) == {r.seats["konoe"], r.seats["tojo"]}
    assert locks.is_matter(r.state, r.state.held[asked.order_id], asked)


def test_one_member_declining_keeps_the_strike_held() -> None:
    r = _rig("yamamoto", "konoe", "tojo")
    asked = _held_and_asked(
        r, _order(r, "combined_fleet_move", force="combined_fleet", to="pearl_harbor_base")
    )
    r.add(ev.MatterChosen(order_id=asked.order_id, seat_id=r.seats["tojo"], accept=True, on=FILED))
    r.add(
        ev.MatterChosen(order_id=asked.order_id, seat_id=r.seats["konoe"], accept=False, on=FILED)
    )
    assert not locks.matter_granted(r.state, r.state.asked[asked.order_id])


def test_with_deciders_off_the_prime_minister_decides_alone() -> None:
    world = _world()
    off = world.model_copy(update={"rules": tuple(x for x in world.rules if x != "deciders")})
    r = Rig("autumn-1941")
    events = compile_world(off, r.campaign, cmp.versions())
    declared = next(e.payload for e in events if isinstance(e.payload, ev.LocksDeclared))
    rows = {row.key: row for row in declared.rows}
    for key in WAR:
        assert rows[key].decider.council is None and rows[key].question is None
        assert rows[key].decider.person == EntityId(r.ids["konoe"])


# --- the roster holds him -----------------------------------------------------------------


def test_the_roster_limit_holds_him() -> None:
    world = _world()
    assert world.roster_limit is not None
    least, most = world.roster_limit
    assert least <= len(world.roster) <= most
    assert not [p for p in check_history(world) if p.startswith("roster")]


# --- rule 5: the scripted run -------------------------------------------------------------


def _season(world: WorldFile, monkeypatch: pytest.MonkeyPatch) -> Rig:
    """The scripted run on ``world``, first seed, at its end."""
    rigs: list[Rig] = []

    class Kept(Rig):
        def __init__(self, world_name: str, campaign: CampaignId) -> None:
            del world_name
            from revisionist.core.fold import replay
            from revisionist.core.world_compile import resolve_keys

            self.campaign = campaign
            self.ids = resolve_keys(world, campaign)
            events = compile_world(world, campaign, cmp.versions())
            self.state = replay(events)
            self.seq = len(events)
            self.seats = {}
            self.n_orders = 0
            rigs.append(self)

    monkeypatch.setattr(bands, "Rig", Kept)
    bands.play(bands.SEEDS[0])
    return rigs[0]


def test_the_fleets_move_to_hitokappu_bay_on_22_november_runs_with_the_switches_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = without_third_run(_world())
    r = _season(world, monkeypatch)
    fleet = r.state.features[FeatureId(r.ids["combined_fleet"])]
    assert fleet.legs == ()  # the leg of 22 November was taken
    assert fleet.places == (EntityId(r.ids["north_pacific"]),)  # the sea Hitokappu Bay is on


def test_with_the_third_run_switches_out_his_locks_stay() -> None:
    kept = {r.key for r in without_third_run(_world()).locks}
    assert set(WAR) | set(GATHER) <= kept


def test_the_scripted_run_is_the_baseline_with_the_third_run_switches_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(without_third_run(_world()), monkeypatch) == BASELINE_1941


def test_the_scripted_run_with_the_third_run_switches_on_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(_world(), monkeypatch) == ON
