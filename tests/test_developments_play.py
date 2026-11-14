"""Developments in play (DV2): the realism tick draws the world's deck by window,
condition and the campaign's seed, prints what fires as news, applies its effects
through the fold, and offers its suggested asks as ideas. A development never files
an order. The seat view lists the public developments that fired ("The world").
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core import history
from revisionist.core.fold import replay
from revisionist.core.goals import EntityIs
from revisionist.core.ids import CampaignId, EntityId, ScheduledEventId, SeatId, derived_id
from revisionist.core.ontology import EntityStatus, ScheduledEvent, ScheduleSource
from revisionist.core.realism import apply
from revisionist.core.realism.agenda import PlayStyle
from revisionist.core.realism.war import NewsTopic
from revisionist.core.state import State
from revisionist.core.visibility import Visibility
from revisionist.core.world import DevelopmentDecl, WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import options, realism_tick
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import agenda_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
OTHER = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAW")
UNTIL = date(1941, 11, 20)
FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"


def autumn(**changes: dict[str, Any]) -> WorldFile:
    """autumn-1941 with its deck, each named development's declaration changed."""
    world = cmp.load_world(cmp.world_path("autumn-1941"))
    deck = tuple(
        DevelopmentDecl.model_validate({**d.model_dump(), **changes.get(d.key, {})})
        for d in world.developments
    )
    return world.model_copy(update={"developments": deck})


def played(
    world: WorldFile, campaign: CampaignId = CAMPAIGN, until: date = UNTIL, ticks: int = 60
) -> tuple[MemoryStore, SeatId, dict[str, Any]]:
    """Roosevelt seated, then realism ticks until ``until`` is reached."""
    store = MemoryStore()
    store.append_all(compile_world(world, campaign, cmp.versions()))
    ids: dict[str, Any] = dict(resolve_keys(world, campaign))
    realism_tick.seat_player(store, campaign, EntityId(ids["roosevelt"]))
    seat = SeatId(derived_id(campaign, "seat", ids["roosevelt"]))
    for _ in range(ticks):
        today = load_state(store, campaign).in_world_date
        if today is not None and today >= until:
            break
        realism_tick.run_realism_tick(store, campaign)
    return store, seat, ids


def deck(state: State) -> dict[ScheduledEventId, ScheduledEvent]:
    return {
        s.scheduled_id: s
        for s in state.scheduled.values()
        if s.source is ScheduleSource.DEVELOPMENT
    }


def fired_days(store: MemoryStore, campaign: CampaignId) -> dict[ScheduledEventId, date]:
    """Each fired development's id and the day its news is dated."""
    state = load_state(store, campaign)
    news_of = {derived_id(campaign, "news", "history", sid): sid for sid in deck(state)}
    return {
        news_of[n.news_id]: n.on
        for n in state.news.values()
        if n.topic is NewsTopic.EVENT and n.news_id in news_of
    }


# --- the draw in the tick ------------------------------------------------------


def test_the_tick_fires_each_development_on_the_day_the_campaign_draws() -> None:
    store, _, _ = played(autumn())
    state = load_state(store, CAMPAIGN)
    days = fired_days(store, CAMPAIGN)
    assert days, "nothing in the deck fired"
    for sid, s in deck(state).items():
        drawn = history.drawn_day(CAMPAIGN, s)
        if drawn is not None and drawn <= UNTIL and s.fired:
            assert days[sid] == drawn, s.name
        assert s.fired == (sid in days), s.name
    # the draw is not the window's first day for every development
    assert any(days[sid] != deck(state)[sid].on_date for sid in days)


def test_the_draw_is_deterministic_for_a_campaign_and_varies_across_campaigns() -> None:
    a, _, _ = played(autumn())
    b, _, _ = played(autumn())
    c, _, _ = played(autumn(), campaign=OTHER)
    names = {s.scheduled_id: s.name for s in deck(load_state(a, CAMPAIGN)).values()}
    other = {s.scheduled_id: s.name for s in deck(load_state(c, OTHER)).values()}
    first = {names[k]: d for k, d in fired_days(a, CAMPAIGN).items()}
    assert first == {names[k]: d for k, d in fired_days(b, CAMPAIGN).items()}
    assert first != {other[k]: d for k, d in fired_days(c, OTHER).items()}


def test_a_false_condition_never_fires_no_news_no_effect() -> None:
    nye_dead = {"check": "entity_is", "entity": "nye", "status": "dead"}
    store, _, ids = played(autumn(dev_hollywood_hearings={"condition": nye_dead}))
    state = load_state(store, CAMPAIGN)
    (hearings,) = [s for s in deck(state).values() if s.name.startswith("The Senate's hearings")]
    assert isinstance(hearings.condition, EntityIs)
    assert hearings.condition.status is EntityStatus.DEAD
    assert hearings.skipped and not hearings.fired
    assert hearings.scheduled_id not in fired_days(store, CAMPAIGN)
    nye, fdr = EntityId(ids["nye"]), EntityId(ids["roosevelt"])
    assert not [r for r in state.relationships.values() if {r.a, r.b} == {nye, fdr}]


def test_a_skipped_development_adds_no_divergence() -> None:
    nye_dead = {"check": "entity_is", "entity": "nye", "status": "dead"}
    with_skip, _, _ = played(autumn(dev_hollywood_hearings={"condition": nye_dead}))
    plain, _, _ = played(autumn())
    assert load_state(with_skip, CAMPAIGN).divergence == load_state(plain, CAMPAIGN).divergence


# --- effects through the fold -------------------------------------------------


def _fire(state: State, key: str, ids: dict[str, Any], day: date) -> list[ev.Payload]:
    sid = ids[key]
    fired = [ev.ScheduledEventFired(scheduled_id=sid)]
    return apply.developed(state, fired, day)


def test_a_figure_effect_moves_the_figure_by_its_percent() -> None:
    world = autumn()
    events = compile_world(world, CAMPAIGN, cmp.versions())
    state, ids = replay(events), dict[str, Any](resolve_keys(world, CAMPAIGN))
    q = state.quantities[ids["gallup_fdr_about_right"]]
    assert q.value == 55
    out = _fire(state, "dev_captive_mines_strike", ids, date(1941, 11, 1))
    assert [type(p) for p in out] == [ev.QuantitySet]
    (moved,) = out
    assert isinstance(moved, ev.QuantitySet)
    assert moved.quantity.value == 54  # -2 percent of 55, toward zero
    assert moved.quantity.as_of == date(1941, 11, 1)


def test_a_figure_with_no_value_is_left_alone() -> None:
    world = autumn()
    state = replay(compile_world(world, CAMPAIGN, cmp.versions()))
    ids: dict[str, Any] = dict(resolve_keys(world, CAMPAIGN))
    assert state.quantities[ids["gallup_help_britain"]].value is None
    assert _fire(state, "dev_lindbergh_des_moines", ids, date(1941, 9, 11)) == []


def test_a_disposition_effect_shifts_a_public_relationship() -> None:
    world = autumn()
    state = replay(compile_world(world, CAMPAIGN, cmp.versions()))
    ids: dict[str, Any] = dict(resolve_keys(world, CAMPAIGN))
    (shift,) = _fire(state, "dev_hollywood_hearings", ids, date(1941, 9, 9))
    assert isinstance(shift, ev.RelationshipSet)
    rel = shift.relationship
    assert (rel.a, rel.b, rel.disposition) == (ids["nye"], ids["roosevelt"], -1)
    assert rel.scope.visibility is Visibility.PUBLIC


def test_only_fired_developments_have_effects() -> None:
    world = autumn()
    state = replay(compile_world(world, CAMPAIGN, cmp.versions()))
    ids: dict[str, Any] = dict(resolve_keys(world, CAMPAIGN))
    skipped = [ev.ScheduledEventSkipped(scheduled_id=ids["dev_captive_mines_strike"])]
    assert apply.developed(state, skipped, date(1941, 11, 1)) == []


def test_the_tick_applies_the_effects_and_files_no_order() -> None:
    store, _, ids = played(autumn())
    state = load_state(store, CAMPAIGN)
    hearings = state.scheduled[ids["dev_hollywood_hearings"]]
    nye, fdr = ids["nye"], ids["roosevelt"]
    shifted = [r for r in state.relationships.values() if {r.a, r.b} == {nye, fdr}]
    assert hearings.fired and len(shifted) == 1 and shifted[0].disposition == -1
    seat = SeatId(derived_id(CAMPAIGN, "seat", fdr))
    assert not [o for o in state.routed.values() if o.issuer == seat]


# --- asks as ideas -------------------------------------------------------------


def _styled(
    world: WorldFile, style: PlayStyle = PlayStyle.BEGINNER
) -> tuple[MemoryStore, SeatId, dict[str, Any]]:
    """Roosevelt in ``style``, ticked until Lindbergh's speech fires: the latest stretch."""
    store, seat, ids = played(world, until=date(1941, 9, 1), ticks=0)
    options.set_style(store, CAMPAIGN, seat, style)
    for _ in range(60):
        if load_state(store, CAMPAIGN).scheduled[ids["dev_lindbergh_des_moines"]].fired:
            break
        realism_tick.run_realism_tick(store, CAMPAIGN)
    return store, seat, ids


def test_an_actionable_development_offers_its_ask_through_ideas() -> None:
    store, seat, ids = _styled(autumn())
    state = load_state(store, CAMPAIGN)
    assert state.scheduled[ids["dev_lindbergh_des_moines"]].fired
    before = len(state.routed)
    block = agenda_api.agenda(state, seat, list(store.read(CAMPAIGN)))
    labels = [o["label"] for o in block["initiative"]]
    assert "Answer Lindbergh in a public statement" in labels
    (offered,) = [o for o in block["initiative"] if o["label"].startswith("Answer Lindbergh")]
    assert offered["risk"].startswith("From the news:")
    assert not offered["historical"] and not offered["taken"]
    assert len(load_state(store, CAMPAIGN).routed) == before


def test_a_suggestive_development_offers_nothing() -> None:
    store, seat, ids = _styled(autumn(dev_lindbergh_des_moines={"asks": ()}))
    state = load_state(store, CAMPAIGN)
    assert state.scheduled[ids["dev_lindbergh_des_moines"]].fired
    block = agenda_api.agenda(state, seat, list(store.read(CAMPAIGN)))
    assert not [o for o in block["initiative"] if "Lindbergh" in o["risk"]]


@pytest.mark.parametrize("style", [PlayStyle.FREE, PlayStyle.GUIDED])
def test_only_a_beginner_is_offered_news_asks(style: PlayStyle) -> None:
    store, seat, ids = _styled(autumn(), style)
    state = load_state(store, CAMPAIGN)
    assert state.scheduled[ids["dev_lindbergh_des_moines"]].fired
    block = agenda_api.agenda(state, seat, list(store.read(CAMPAIGN)))
    assert not [o for o in block["initiative"] if o["risk"].startswith("From the news:")]


def test_news_asks_are_only_from_the_latest_stretch() -> None:
    store, seat, _ = _styled(autumn())
    realism_tick.run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    block = agenda_api.agenda(state, seat, list(store.read(CAMPAIGN)))
    assert "Answer Lindbergh in a public statement" not in [o["label"] for o in block["initiative"]]


def test_picking_a_news_ask_files_nothing_and_says_to_write_it() -> None:
    store, seat, _ = _styled(autumn())
    state = load_state(store, CAMPAIGN)
    block = agenda_api.agenda(state, seat, list(store.read(CAMPAIGN)))
    (offered,) = [o for o in block["initiative"] if o["label"].startswith("Answer Lindbergh")]
    before = len(list(store.read(CAMPAIGN)))
    reply = agenda_api.pick_option(store, CAMPAIGN, seat, offered["pick"])
    assert reply["refused"] and "order" in reply["reply"]
    assert len(list(store.read(CAMPAIGN))) == before


# --- the world in the seat view ------------------------------------------------


def test_the_seat_view_lists_the_public_developments_that_fired() -> None:
    store, seat, ids = played(autumn(), until=date(1941, 9, 16))
    state = load_state(store, CAMPAIGN)
    world = rs.seat_realism(state, seat, set(), set(), None)["world"]
    fired = [s for s in deck(state).values() if s.fired]
    assert fired and len(world) == len(fired)
    assert all(set(d) == set(api.WorldDevelopment.__annotations__) for d in world)
    assert [d["on"] for d in world] == sorted((d["on"] for d in world), reverse=True)
    (lindbergh,) = [d for d in world if d["headline"].startswith("Lindbergh")]
    assert lindbergh["category"] == "Public figures"
    assert lindbergh["asks"] == ["Answer Lindbergh in a public statement"]
    drawn = history.drawn_day(CAMPAIGN, state.scheduled[ids["dev_lindbergh_des_moines"]])
    assert lindbergh["on"] == str(drawn)
    pending = [s for s in deck(state).values() if not s.fired]
    shown = {d["headline"] for d in world}
    assert not any(s.headline in shown for s in pending)


def test_a_game_with_no_deck_shows_an_empty_world() -> None:
    world = autumn().model_copy(update={"developments": ()})
    store, seat, _ = played(world, until=date(1941, 9, 16))
    state = load_state(store, CAMPAIGN)
    assert rs.seat_realism(state, seat, set(), set(), None)["world"] == []


def test_the_client_fixture_carries_the_world_in_the_servers_shape() -> None:
    world = json.loads(FIXTURE.read_text())["world"]
    assert world and all(set(d) == set(api.WorldDevelopment.__annotations__) for d in world)
    assert any(d["asks"] for d in world) and any(not d["asks"] for d in world)
