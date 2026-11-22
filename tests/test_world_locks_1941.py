"""1941: the Atlantic Fleet's commander, the two locks and the war zone (KCD).

Admiral King, Commander in Chief, Atlantic Fleet, is a military card the players may
claim: his own forms move and detach the Atlantic Fleet and give it a naval order, through
his own staff with no step above him; he cables the President; he has three aims with
conditions. Two locks hold his naval orders: shoot on sight on the Iceland route needs the
President's posture, and escort beyond Iceland into the war zone needs the Neutrality
revision in force. The war zone is a region of the map whose sea zones are the Western
Approaches and the Mid-Ocean Gap.

The scripted run's digest (``run_digest``) is a hash of every payload the scripted run of
``tests/test_realism_bands.py`` folds after the world is compiled, for its first seed, with
the figures that run returns (the aims of the eight cards ``main`` read): what the run did,
not what the world declares. With ``command`` and ``locks`` taken out of a copy's rules it
equals ``BEFORE``, so nothing else in the file moved the run.
"""

import hashlib
import json
from datetime import date, timedelta
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, OrderId, PipelineId, derived_id
from revisionist.core.realism import locks
from revisionist.core.realism.card import CardPath
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.resolvers import shipping
from revisionist.core.state import Rule
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from tests import test_realism_bands as bands
from tests.test_realism_resolvers import Rig

BEFORE = "041db15f62465c8c98ff5c1f330ed04a"
"""The scripted run's digest with ``command`` and ``locks`` taken out of the rules."""
AFTER = "041db15f62465c8c98ff5c1f330ed04a"
"""The scripted run's digest with ``command`` and ``locks`` on, recorded once by this item.
It equals ``BEFORE``: the script seats the President alone and files no order a lock holds,
and his naval order passes King's step on the day the record gives."""

EIGHT = ("roosevelt", "churchill", "stalin", "hitler", "konoe", "tojo", "mussolini", "chiang")
"""The playable cards before this item: the run's aims are read for these in the digest, as
the bands script read them on ``main``; King's are read beside them, not folded."""
FILED = date(1941, 9, 20)
WAR_ZONE = {"mid_ocean_gap", "western_approaches_area"}


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def _card(world: WorldFile, person: str) -> Any:
    return next(c for c in world.cards if c.person == person)


def without_switches(world: WorldFile) -> WorldFile:
    """A copy of ``world`` with ``command`` and ``locks`` taken out of its rules."""
    off = {Rule.COMMAND.value, Rule.LOCKS.value}
    return world.model_copy(update={"rules": tuple(r for r in world.rules if r not in off)})


def _compile(world: WorldFile) -> None:
    compile_world(world, CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV"), cmp.versions())


def run_digest(world: WorldFile, monkeypatch: pytest.MonkeyPatch) -> str:
    """The scripted run's digest on ``world``, first seed: blake2b over every payload the
    run folds after the world's own events, in order, and the figures it returns."""
    folded: list[object] = []

    class Recording(Rig):
        def __init__(self, world_name: str, campaign: CampaignId) -> None:
            del world_name
            self.campaign = campaign
            self.ids = resolve_keys(world, campaign)
            events = compile_world(world, campaign, cmp.versions())
            self.state = replay(events)
            self.seq = len(events)
            self.seats = {}
            self.n_orders = 0

        def add(self, payload: ev.Payload) -> None:
            folded.append(payload.model_dump(mode="json"))
            super().add(payload)

    monkeypatch.setattr(bands, "Rig", Recording)
    run = bands.play(bands.SEEDS[0])
    eight = {k: v for k, v in run.aims.items() if k[0] in EIGHT}
    figures = {k: repr(eight if k == "aims" else v) for k, v in sorted(vars(run).items())}
    canon = json.dumps([folded, figures], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.blake2b(canon.encode(), digest_size=16).hexdigest()


# --- rule 6: the world's rules gain command and locks; it compiles ---------------------


def test_the_world_compiles_with_command_and_locks_on() -> None:
    world = _world()
    assert {Rule.COMMAND.value, Rule.LOCKS.value} <= set(world.rules)
    _compile(world)


# --- rule 1: the commander's card --------------------------------------------------------


def test_the_atlantic_fleet_commander_is_a_playable_military_card_on_the_roster() -> None:
    world = _world()
    king = _card(world, "king")
    assert king.office == "Commander in Chief, Atlantic Fleet"
    assert king.playable and king.path is CardPath.MILITARY
    assert king.principals == ("stark",)
    assert "king" in {c.entity for c in world.roster}


def test_his_domain_names_the_atlantic_fleet_and_no_other_military_card_does() -> None:
    world = _world()
    forces = {k for dm in _card(world, "king").authority for k in dm.forces}
    assert forces == {"us_atlantic_fleet"}
    others = {
        k
        for c in world.cards
        if c.person != "king" and c.path is CardPath.MILITARY
        for dm in c.authority
        for k in dm.forces
    }
    assert "us_atlantic_fleet" not in others


def test_the_commander_with_no_force_does_not_compile() -> None:
    world = _world()
    bare = _card(world, "king").model_copy(update={"authority": ()})
    cards = tuple(bare if c.person == "king" else c for c in world.cards)
    with pytest.raises(WorldError, match="a playable military card needs a domain naming a force"):
        _compile(world.model_copy(update={"cards": cards}))


def test_his_own_forms_go_through_a_pipeline_with_no_step_above_him() -> None:
    world = _world()
    king = _card(world, "king")
    levers = {lv.name: lv for lv in king.levers}
    assert {"move_fleet", "detach_fleet", "fleet_naval_order"} <= set(levers)
    for lv in levers.values():
        pipeline = next(p for p in world.pipelines if p.key == lv.pipeline)
        assert [s.person for s in pipeline.steps] == ["king"], lv.name
    for name in ("move_fleet", "detach_fleet"):
        force = next(p for p in levers[name].params if p.name == "force")
        assert force.choices == ("us_atlantic_fleet",)


def test_he_cables_the_president() -> None:
    king = _card(_world(), "king")
    assert ("roosevelt", "cable") in {(k.person, k.channel) for k in king.inner_circle}


def test_he_has_three_aims_with_conditions_the_third_replaceable() -> None:
    king = _card(_world(), "king")
    assert len(king.aims) == 3
    rules = {r.aim: r for r in king.aim_rules}
    assert sorted(rules) == [1, 2, 3]
    assert [rules[n].replaceable for n in (1, 2, 3)] == [False, False, True]
    assert all(r.condition is not None for r in rules.values())


def test_he_holds_a_post_that_meets_the_character_rule() -> None:
    world = _world()
    held = [a for a in world.assets if a.controller == "king"]
    assert held and max(a.tier for a in held) >= 2


def test_a_mandate_goes_to_him() -> None:
    assert any("king" in m.to for m in _world().mandates)


# --- rules 2 and 4: the zone beyond Iceland and the war zone's sea zones -----------------


def _zone_param(world: WorldFile) -> Any:
    lever = next(lv for lv in _card(world, "king").levers if lv.name == "fleet_naval_order")
    return next(p for p in lever.params if p.name == "zone")


def test_the_naval_order_gains_the_zone_beyond_iceland_with_a_label() -> None:
    zone = _zone_param(_world())
    assert "war_zone" in zone.choices
    label = zone.choice_labels[zone.choices.index("war_zone")]
    assert "Iceland" in label and "war zone" in label


def test_the_war_zone_is_the_western_approaches_and_the_mid_ocean_gap() -> None:
    world = _world()
    assert next(r for r in world.regions if r.key == "war_zone").parent == "atlantic"
    assert {z.key for z in world.sea_zones if z.region == "war_zone"} == WAR_ZONE


def test_the_shipping_rule_reads_the_zone_value_as_those_sea_zones() -> None:
    r = Rig("autumn-1941")
    want = {EntityId(r.ids[k]) for k in WAR_ZONE}
    assert shipping._waters(r.state, "war_zone") == frozenset(want)


def test_iceland_stays_british() -> None:
    iceland = next(t for t in _world().territories if t.key == "iceland")
    assert iceland.holder == "uk"


# --- rules 3 and 5: the two locks ---------------------------------------------------------


def test_two_locks_on_his_naval_order_one_naming_the_president_one_congress() -> None:
    world = _world()
    rows = {r.key: r for r in world.locks}
    assert set(rows) == {"iceland_shoot_on_sight", "war_zone_escort"}
    shoot, escort = rows["iceland_shoot_on_sight"], rows["war_zone_escort"]
    assert shoot.order.form == escort.order.form == "fleet_naval_order"
    assert shoot.order.params == {"order": "shoot_on_sight", "zone": "iceland_route"}
    assert shoot.decider.person == "roosevelt"
    assert shoot.when is not None and shoot.when.check == "posture_not_set"
    assert escort.order.params == {"order": "escort_convoys", "zone": "war_zone"}
    assert escort.decider.nation == "usa" and set(escort.decider.chambers) == {"house", "senate"}
    assert escort.when is not None and escort.when.check == "law_not_in_force"


def test_a_row_naming_a_missing_zone_does_not_compile() -> None:
    world = _world()
    rows = tuple(
        r.model_copy(update={"order": r.order.model_copy(update={"params": {"zone": "nowhere"}})})
        if r.key == "war_zone_escort"
        else r
        for r in world.locks
    )
    with pytest.raises(WorldError, match="does not fit fleet_naval_order's zone"):
        _compile(world.model_copy(update={"locks": rows}))


def test_the_acts_reach_is_worded_from_a_source() -> None:
    source = next(s for s in _world().sources if s.key == "neutrality_act_1939")
    assert "section 3" in source.title.casefold()
    assert "american vessel" in source.note.casefold()


def _rig() -> Rig:
    r = Rig("autumn-1941")
    r.seat("roosevelt")
    r.seat("king")
    r.close_session_zero()
    return r


def _order(r: Rig, order: str, zone: str) -> Order:
    return Order(
        order_id=OrderId(derived_id(r.campaign, "order", f"kcd-{order}-{zone}")),
        issuer=r.seats["king"],
        lever="fleet_naval_order",
        pipeline=PipelineId(r.ids["atlantic_fleet_staff"]),
        params={"order": order, "zone": zone},
        filed=FILED,
    )


def test_shoot_on_sight_on_the_iceland_route_is_held_for_the_president() -> None:
    r = _rig()
    lock = locks.lock_for(r.state, r.seats["king"], _order(r, "shoot_on_sight", "iceland_route"))
    assert lock is not None and lock.decider.person == EntityId(r.ids["roosevelt"])
    free = _order(r, "escort_convoys", "iceland_route")
    assert locks.lock_for(r.state, r.seats["king"], free) is None


def test_the_presidents_naval_order_sets_the_posture_and_opens_the_first_lock() -> None:
    r = _rig()
    d = date(1941, 9, 11)
    r.enact(
        "roosevelt",
        "naval_order",
        "naval_order",
        d,
        [d + timedelta(days=2), d + timedelta(days=4)],
        order="shoot_on_sight",
        zone="iceland_route",
    )
    order = _order(r, "shoot_on_sight", "iceland_route")
    assert locks.lock_for(r.state, r.seats["king"], order) is None


def test_escort_into_the_war_zone_is_held_for_congress_until_the_revision_passes() -> None:
    r = _rig()
    order = _order(r, "escort_convoys", "war_zone")
    lock = locks.lock_for(r.state, r.seats["king"], order)
    assert lock is not None and lock.decider.nation == EntityId(r.ids["usa"])
    free = _order(r, "escort_convoys", "western_atlantic")
    assert locks.lock_for(r.state, r.seats["king"], free) is None
    r.set_value("neutrality_revision_passed", 1, as_of=date(1941, 11, 17))
    assert locks.lock_for(r.state, r.seats["king"], order) is None


def test_with_the_switches_off_nothing_holds_his_orders() -> None:
    world = without_switches(_world())
    campaign = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
    state = replay(compile_world(world, campaign, cmp.versions()))
    assert Rule.LOCKS not in state.rules and Rule.COMMAND not in state.rules


# --- the scripted run's digest ----------------------------------------------------------


def test_the_scripted_run_is_unchanged_with_the_switches_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(without_switches(_world()), monkeypatch) == BEFORE


def test_the_scripted_run_with_the_switches_on_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(_world(), monkeypatch) == AFTER
