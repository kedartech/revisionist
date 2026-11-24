"""1941: Finland's President, the army's Commander-in-Chief and their lock (NFI).

Risto Ryti, President of Finland from 19 December 1940, is a political card the players may
claim; Marshal Mannerheim, to whom the command of the armed forces was handed on 30 November
1939, is a military card under him. Ryti did not command himself, so his order over the army
goes through Mannerheim (the executor of his ``supreme_command`` domain); Mannerheim's own forms
move the Finnish Army and hide its moves through his own headquarters, with no step above him.
Each has a pipeline, a feed, an inner circle, three aims with conditions and a dossier line.

One army, the Finnish Army, stands in Finland's own territory, and the war with the Soviet
Union is in force from the start. Its day is read two ways (amendment 9): the night of 25 June
1941 (the US Army history) and 26 June (the Library of Congress country study). The world keeps
the first and names the second in that source's note.

A lock holds sending the Finnish Army on past the 1939 border to Leningrad: it is Ryti's to
permit, with no condition, and Finland's Parliament does not decide it. No source gives
Finland's home groups, so the world declares none and the home rules are off for Finland.

The scripted run's digest (``run_digest``) with the third-run switches taken out of a copy's
rules is the baseline; with them on it is recorded here once, and it is unchanged.
"""

from datetime import date
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core import roster
from revisionist.core.aim_patterns import build
from revisionist.core.ids import CampaignId, EntityId, OrderId, PipelineId, SeatId, derived_id
from revisionist.core.realism import locks
from revisionist.core.realism.card import CardPath, superiors
from revisionist.core.realism.pipeline import Order
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, check_history, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import session_zero
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import dossiers, new_game_api
from tests.test_realism_resolvers import Rig
from tests.test_rule_names import BASELINE_1941
from tests.test_world_locks_1941 import run_digest
from tests.test_world_locks_uk_1941 import without_third_run

ON = "45f00e1d6cb09e84245f4a7affb44692"
"""The scripted run's digest with the 1941 world's third-run switches on, as the nation items
before this one recorded it: Finland's two cards leave it as it was."""

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
FILED = date(1941, 10, 10)
NATION = "finland_state"
HOME = "finland"
"""Finland's own territory: its holder and yields stay as they were."""
ARMY = "finnish_army"
FORM = "finnish_army_move"
CONCEAL = "finnish_army_conceal"
RYTIS = "finnish_army_order"
ROW = "finnish_army_beyond_the_border"
"""The row Ryti decides: the Finnish Army sent on past the 1939 border to Leningrad."""
BEYOND = "leningrad"
"""The place past the 1939 border the army's forms reach. [proposed]"""
FILLED: dict[int, tuple[str, dict[str, Any]]] = {
    1: ("hold_and_take", {"held": HOME, "place": "the_north"}),
    2: ("take_ground", {"place": "the_north"}),
}
"""Mannerheim's two aims from the army commander's patterns, with the values filled in."""


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def _card(world: WorldFile, person: str) -> Any:
    return next(c for c in world.cards if c.person == person)


def _compile(world: WorldFile) -> None:
    compile_world(world, CAMPAIGN, cmp.versions())


def _where(world: WorldFile, key: str) -> str | None:
    return next(e.within for e in world.entities if e.key == key)


# --- rule 1: the two cards ------------------------------------------------------------------


def test_finland_has_a_playable_political_head_and_a_playable_military_commander() -> None:
    world = _world()
    ryti, mannerheim = _card(world, "ryti"), _card(world, "mannerheim")
    assert ryti.office == "President of the Republic of Finland"
    assert ryti.playable and ryti.path is not CardPath.MILITARY
    assert ryti.post_kind == "head_of_government"
    assert mannerheim.office == "Commander-in-Chief of the Finnish Armed Forces"
    assert mannerheim.playable and mannerheim.path is CardPath.MILITARY
    assert mannerheim.post_kind == "army_commander"
    assert mannerheim.principals == ("ryti",)
    parents = {e.key: e.parent for e in world.entities if e.key in ("ryti", "mannerheim")}
    assert parents == {"ryti": NATION, "mannerheim": NATION}
    assert {"ryti", "mannerheim"} <= {c.entity for c in world.roster}
    _compile(world)


@pytest.mark.parametrize("person", ["ryti", "mannerheim"])
def test_each_has_forms_a_pipeline_a_feed_an_inner_circle_and_three_aims(person: str) -> None:
    world = _world()
    card = _card(world, person)
    pipelines = {p.key for p in world.pipelines}
    assert card.levers and card.pipelines and set(card.pipelines) <= pipelines
    assert {lv.pipeline for lv in card.levers} <= set(card.pipelines)
    assert card.feeds == ("finnish_hq_reports",)
    assert card.inner_circle
    assert len(card.aims) == 3
    assert sorted(r.aim for r in card.aim_rules) == [1, 2, 3]
    assert all(r.condition is not None for r in card.aim_rules)
    assert [r.replaceable for r in sorted(card.aim_rules, key=lambda r: r.aim)][-1]


def test_they_telephone_each_other() -> None:
    world = _world()
    for one, other in (("ryti", "mannerheim"), ("mannerheim", "ryti")):
        circle = {(k.person, k.channel) for k in _card(world, one).inner_circle}
        assert (other, "telephone") in circle, one


def test_mannerheims_aims_two_from_the_army_commanders_patterns_the_third_replaceable() -> None:
    world = _world()
    rules = {r.aim: r for r in _card(world, "mannerheim").aim_rules}
    assert [rules[n].replaceable for n in (1, 2, 3)] == [False, False, True]
    patterns = {p.key: p for p in world.aim_patterns}
    for n, (key, values) in FILLED.items():
        pattern = patterns[key]
        assert "army_commander" in pattern.posts
        filled = build(pattern.condition, {**values, "nation": NATION, "person": "mannerheim"})
        assert rules[n].condition == filled, n


def test_rytis_agreement_aim_is_the_head_of_governments_pattern() -> None:
    world = _world()
    rules = {r.aim: r for r in _card(world, "ryti").aim_rules}
    pattern = next(p for p in world.aim_patterns if p.key == "make_agreement")
    assert "head_of_government" in pattern.posts
    filled = build(pattern.condition, {"other": "germany", "nation": NATION, "person": "ryti"})
    assert rules[2].condition == filled


@pytest.mark.parametrize("person", ["ryti", "mannerheim"])
def test_each_holds_a_post_that_meets_the_character_rule(person: str) -> None:
    held = [a for a in _world().assets if a.controller == person]
    assert held and max(a.tier for a in held) >= 2


def test_their_dossiers_say_the_border_is_rytis_to_permit() -> None:
    people, _ = dossiers.load("autumn-1941")
    for person in ("ryti", "mannerheim"):
        assert people[person]["bio"] and people[person]["arena"] and people[person]["fact"]
    ryti = " ".join((people["ryti"]["arena"] or "").split())
    assert "past the 1939 border towards Leningrad is yours to give" in ryti
    mannerheim = " ".join((people["mannerheim"]["arena"] or "").split())
    assert "Crossing the 1939 border towards Leningrad waits on the President's leave" in mannerheim


def test_ryti_is_up_mannerheims_chain() -> None:
    r = Rig("autumn-1941")
    chain = superiors(r.state.cards, EntityId(r.ids["mannerheim"]))
    assert EntityId(r.ids["ryti"]) in chain


@pytest.mark.parametrize("person", ["ryti", "mannerheim"])
def test_a_mandate_reaches_each(person: str) -> None:
    assert [m.key for m in _world().mandates if person in m.to]


# --- the head commands through the Commander-in-Chief --------------------------------------


def test_rytis_supreme_command_is_carried_out_by_mannerheim() -> None:
    ryti = _card(_world(), "ryti")
    (command,) = [dm for dm in ryti.authority if dm.forces]
    assert command.name == "supreme_command"
    assert command.executor == "mannerheim"
    assert set(command.forces) == {ARMY}
    assert {"move_force", "engagement"} <= set(command.effects)


def test_rytis_order_goes_through_the_commander_in_chief() -> None:
    world = _world()
    order = next(lv for lv in _card(world, "ryti").levers if lv.name == RYTIS)
    pipeline = next(p for p in world.pipelines if p.key == order.pipeline)
    assert [s.person for s in pipeline.steps] == ["mannerheim"]
    assert next(p for p in order.params if p.name == "force").choices == (ARMY,)


def test_the_executor_reaches_compiled_state() -> None:
    r = Rig("autumn-1941")
    card = r.state.cards[EntityId(r.ids["ryti"])]
    executors = {dm.name: dm.executor for dm in card.authority}
    assert executors["supreme_command"] == EntityId(r.ids["mannerheim"])


def test_the_head_as_his_own_executor_does_not_compile() -> None:
    world = _world()
    ryti = _card(world, "ryti")
    authority = tuple(
        dm.model_copy(update={"executor": "ryti"}) if dm.name == "supreme_command" else dm
        for dm in ryti.authority
    )
    bare = ryti.model_copy(update={"authority": authority})
    cards = tuple(bare if c.person == "ryti" else c for c in world.cards)
    with pytest.raises(WorldError, match="the person is their own executor"):
        _compile(world.model_copy(update={"cards": cards}))


# --- the commander's own forms --------------------------------------------------------------


def test_mannerheims_own_forms_move_and_hide_the_army_with_no_step_above_him() -> None:
    world = _world()
    levers = {lv.name: lv for lv in _card(world, "mannerheim").levers}
    assert set(levers) == {FORM, CONCEAL}
    for lv in levers.values():
        pipeline = next(p for p in world.pipelines if p.key == lv.pipeline)
        assert [s.person for s in pipeline.steps] == ["mannerheim"], lv.name
    move = levers[FORM]
    assert next(p for p in move.params if p.name == "force").choices == (ARMY,)
    assert BEYOND in next(p for p in move.params if p.name == "to").choices
    hide = levers[CONCEAL]
    assert hide.resolver == "intel"
    assert next(p for p in hide.params if p.name == "intel").choices == ("conceal",)
    assert next(p for p in hide.params if p.name == "piece").choices == (ARMY,)


def test_his_domain_names_the_finnish_army_and_no_other_military_card_does() -> None:
    world = _world()
    forces = {k for dm in _card(world, "mannerheim").authority for k in dm.forces}
    assert forces == {ARMY}
    others = {
        k
        for c in world.cards
        if c.person != "mannerheim" and c.path is CardPath.MILITARY
        for dm in c.authority
        for k in dm.forces
    }
    assert ARMY not in others


def test_the_commander_with_no_force_does_not_compile() -> None:
    world = _world()
    bare = _card(world, "mannerheim").model_copy(update={"authority": ()})
    cards = tuple(bare if c.person == "mannerheim" else c for c in world.cards)
    with pytest.raises(WorldError, match="a playable military card needs a domain naming a force"):
        _compile(world.model_copy(update={"cards": cards}))


# --- one army in Finland, and the war -------------------------------------------------------


def _armies_at_home(world: WorldFile) -> list[str]:
    """The Finnish pieces, each named only if every place it stands in is in Finland."""
    finnish = [f for f in world.features if f.piece is not None and f.side == NATION]
    return [f.key for f in finnish if f.places and all(_where(world, p) == HOME for p in f.places)]


def test_one_finnish_army_stands_in_finlands_own_territory() -> None:
    world = _world()
    finnish = [f for f in world.features if f.piece is not None and f.side == NATION]
    assert [(f.key, f.piece) for f in finnish] == [(ARMY, "army")]
    assert _armies_at_home(world) == [ARMY]
    _compile(world)


def test_the_army_standing_outside_finland_is_caught() -> None:
    world = _world()
    assert _where(world, BEYOND) != HOME
    features = tuple(
        f.model_copy(update={"places": (BEYOND,)}) if f.key == ARMY else f for f in world.features
    )
    assert _armies_at_home(world.model_copy(update={"features": features})) == []


def test_finlands_territory_holder_and_yields_are_unchanged() -> None:
    world = _world()
    home = next(t for t in world.territories if t.key == HOME)
    assert home.holder == NATION
    assert home.yields == {"industry": 0.3, "manpower": 3.7, "oil": 0, "supply": 2, "prestige": 3}


def test_finland_is_at_war_with_the_soviet_union_from_the_start_on_a_named_source() -> None:
    world = _world()
    (war,) = [w for w in world.wars if NATION in (w.a, w.b)]
    assert {war.a, war.b} == {"ussr", NATION}
    assert war.since == date(1941, 6, 25)
    assert war.source == "ziemke_1959"
    sources = {s.key: s for s in world.sources}
    assert war.source in sources
    other = sources["loc_finland_country_study"].note or ""
    assert "26 June 1941" in other and "both readings kept" in other


def test_finland_has_no_home_groups_and_the_world_check_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    world = _world()
    assert [d for d in world.groups if d.nation == NATION] == []
    from tests.test_world_template import wc

    assert wc.without_groups(world) == [NATION]
    groups = world.model_copy(update={"groups": ()})
    assert wc.without_groups(groups) == []
    assert wc.main(["autumn-1941"]) == 0
    said = capsys.readouterr().out
    assert f"{NATION}: no groups at home, so the home rules are off for it" in said


# --- rule 2: the lock, decided by Ryti ------------------------------------------------------


def _rows(world: WorldFile) -> dict[str, Any]:
    return {r.key: r for r in world.locks if r.order.form == FORM}


def test_one_lock_on_crossing_the_border_for_ryti() -> None:
    world = _world()
    rows = _rows(world)
    assert set(rows) == {ROW}
    ryti = [r.key for r in world.locks if r.decider.person == "ryti" and r.question != "peace"]
    assert ryti == [ROW]
    row = rows[ROW]
    assert row.order.params == {"to": BEYOND}
    assert row.decider.person == "ryti"
    assert row.question == "permission" and row.when is None


def test_a_row_whose_decider_is_the_issuer_does_not_compile() -> None:
    world = _world()
    rows = tuple(
        r.model_copy(update={"decider": r.decider.model_copy(update={"person": "mannerheim"})})
        if r.key == ROW
        else r
        for r in world.locks
    )
    with pytest.raises(WorldError, match="mannerheim carries the form and would decide"):
        _compile(world.model_copy(update={"locks": rows}))


def test_finland_has_no_chamber_that_decides_the_border() -> None:
    world = _world()
    for row in _rows(world).values():
        assert row.decider.nation is None and row.decider.council is None, row.key
        assert not row.decider.chambers, row.key


def _rig(*people: str) -> Rig:
    r = Rig("autumn-1941")
    for person in people:
        r.seat(person)
    r.close_session_zero()
    return r


def _order(r: Rig, lever: str, **params: str | int) -> Order:
    return Order(
        order_id=OrderId(derived_id(r.campaign, "order", f"nfi-{lever}-{sorted(params.items())}")),
        issuer=r.seats["mannerheim"],
        lever=lever,
        pipeline=PipelineId(r.ids["finnish_headquarters"]),
        params=params,
        filed=FILED,
    )


def test_crossing_the_border_is_held_for_ryti() -> None:
    r = _rig("mannerheim")
    order = _order(r, FORM, force=ARMY, to=BEYOND)
    lock = locks.lock_for(r.state, r.seats["mannerheim"], order)
    assert lock is not None and lock.decider.person == EntityId(r.ids["ryti"])
    for free_to in ("mikkeli", "helsinki"):
        free = _order(r, FORM, force=ARMY, to=free_to)
        assert locks.lock_for(r.state, r.seats["mannerheim"], free) is None, free_to


@pytest.mark.parametrize("granted", [True, False])
def test_only_rytis_grant_opens_the_way_past_the_border(granted: bool) -> None:
    r = _rig("mannerheim")
    seat = r.seats["mannerheim"]
    order = _order(r, FORM, force=ARMY, to=BEYOND)
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
    assert asked.to == EntityId(r.ids["ryti"])
    assert not locks.open_now(r.state, r.state.held[asked.order_id])
    r.add(ev.AskAnswered(order_id=asked.order_id, asker=seat, on=FILED, granted=granted))
    assert locks.open_now(r.state, r.state.held[asked.order_id]) is granted


def test_with_the_third_run_switches_out_the_lock_stays() -> None:
    assert ROW in {r.key for r in without_third_run(_world()).locks}


# --- rule 4: the opening lists Finland, and each seat is claimed through it -----------------


def _opened() -> tuple[MemoryStore, Any]:
    store = MemoryStore()
    store.append_all(compile_world(_world(), CAMPAIGN, cmp.versions()))
    return store, load_state(store, CAMPAIGN)


def _finland(state: Any) -> list[Any]:
    return [n for n in new_game_api.opening(state)["nations"] if n["name"] == "Finland"]


def test_the_opening_lists_finland_once_with_its_two_paths() -> None:
    _, state = _opened()
    (finland,) = _finland(state)
    paths = {p["path"]: [x["name"] for x in p["persons"]] for p in finland["paths"]}
    assert paths == {"political": ["Risto Ryti"], "military": ["C. G. E. Mannerheim"]}
    free = {c.name for c in roster.claimable(state) if c.reason is None}
    assert {"Risto Ryti", "C. G. E. Mannerheim"} <= free


def test_each_finnish_seat_is_claimed_through_the_openings_answer() -> None:
    _, state = _opened()
    (finland,) = _finland(state)
    names = [x["name"] for p in finland["paths"] for x in p["persons"]]
    assert len(names) == 2
    for n, name in enumerate(names):
        store, _ = _opened()
        seat = SeatId(derived_id(CAMPAIGN, "seat", f"nfi-{n}"))
        assert session_zero.claim(store, CAMPAIGN, seat, name) == name
        (after,) = _finland(load_state(store, CAMPAIGN))
        taken = {x["name"] for p in after["paths"] for x in p["persons"] if x["taken"]}
        assert taken == {name}


# --- the roster holds them ------------------------------------------------------------------


def test_the_roster_limit_holds_them() -> None:
    world = _world()
    assert world.roster_limit is not None
    least, most = world.roster_limit
    assert least <= len(world.roster) <= most
    assert not [p for p in check_history(world) if p.startswith("roster")]


# --- rule 5: the scripted run ---------------------------------------------------------------


def test_the_scripted_run_is_the_baseline_with_the_third_run_switches_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(without_third_run(_world()), monkeypatch) == BASELINE_1941


def test_the_scripted_run_with_the_third_run_switches_on_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(_world(), monkeypatch) == ON
