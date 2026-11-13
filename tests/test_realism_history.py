"""History's clock in autumn 1941 reads who acts, not meters (act_of, quantity_at).
A fired public history event the world gives a headline is reported as news."""

from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core import history
from revisionist.core.fold import replay
from revisionist.core.goals import ActOf, QuantityAt, goal_met
from revisionist.core.ids import EntityId, ScheduledEventId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism.document import DocumentKind
from revisionist.core.realism.war import NewsEvent, NewsTopic
from revisionist.core.visibility import private_to
from revisionist.core.world import HistoryDecl, WorldFile
from revisionist.core.world_compile import WorldError, compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.realism_tick import run_realism_tick
from revisionist.engine.store import MemoryStore, load_state
from tests.test_realism_resolvers import CAMPAIGN, Rig

START, END = date(1941, 9, 1), date(1941, 12, 8)
HUMAN_SKIPS = {
    "house_arms_merchant_ships",
    "senate_neutrality_vote",
    "house_concurrence",
    "soviet_lend_lease_finding",
    "kearny_hit",
    "reuben_james_sunk",
}
WEIGHTS = {
    "greer_incident": 2,
    "konoe_resigns": 3,
    "house_arms_merchant_ships": 2,
    "kearny_hit": 2,
    "tojo_cabinet": 3,
    "reuben_james_sunk": 2,
    "soviet_lend_lease_finding": 2,
    "senate_neutrality_vote": 3,
    "house_concurrence": 3,
    "hull_note": 3,
    "pearl_harbor": 3,
}


def walk(r: Rig) -> tuple[set[str], set[str]]:
    """Settle history day by day to 8 Dec; returns the keys fired and skipped."""
    day = START
    while day <= END:
        if day > START:
            r.add(ev.DateAdvanced(to=day))
        for event in history.settle(r.state, day):
            r.add(event)
        day += timedelta(days=1)
    by_id = {ScheduledEventId(r.ids[k]): k for k in WEIGHTS}
    fired = {by_id[s.scheduled_id] for s in r.state.scheduled.values() if s.fired}
    skipped = {by_id[s.scheduled_id] for s in r.state.scheduled.values() if s.skipped}
    return fired, skipped


def played(key: str | None) -> Rig:
    r = Rig("autumn-1941")
    if key is not None:
        r.seat(key)
        r.close_session_zero()
    return r


def test_no_human_every_event_fires() -> None:
    r = played(None)
    fired, skipped = walk(r)
    assert fired == set(WEIGHTS)
    assert not skipped
    assert r.state.divergence == 0


def test_human_roosevelt_who_files_nothing() -> None:
    r = played("roosevelt")
    fired, skipped = walk(r)
    assert skipped == HUMAN_SKIPS
    assert fired == set(WEIGHTS) - HUMAN_SKIPS
    assert r.state.divergence == sum(WEIGHTS[k] for k in HUMAN_SKIPS)


def test_human_konoe_skips_his_own_acts() -> None:
    r = played("konoe")
    fired, skipped = walk(r)
    assert skipped == {"konoe_resigns", "tojo_cabinet", "pearl_harbor"}
    assert r.state.divergence == 9
    assert "greer_incident" in fired


def test_bill_past_rayburn_makes_the_house_event_fire() -> None:
    r = played("roosevelt")
    order = r.draft(
        "roosevelt",
        "send_bill",
        "bill_through_congress",
        START,
        bill="neutrality_revision",
        urgency="urgent",
    )
    r.pass_steps(order, [date(1941, 9, 9)])
    fired, skipped = walk(r)
    assert "house_arms_merchant_ships" in fired
    assert {"senate_neutrality_vote", "house_concurrence"} <= skipped


def test_view_cannot_see_who_is_human() -> None:
    r = played("roosevelt")
    view = project(r.state, r.seats["roosevelt"])
    act = ActOf(person=r.ids["konoe"])
    assert goal_met(r.state, act)
    assert not goal_met(view, act)


@pytest.mark.parametrize(
    ("op", "value", "met"), [("ge", 1, True), ("ge", 31, False), ("le", 30, True)]
)
def test_quantity_at(op: str, value: int, met: bool) -> None:
    r = played(None)
    cond = QuantityAt(quantity=r.ids["uboats_operational"], op=op, value=value)
    assert goal_met(r.state, cond) is met


def test_quantity_at_without_a_value_is_unmet() -> None:
    r = played(None)
    cond = QuantityAt(quantity=r.ids["neutrality_revision_house_yeas"], op="ge", value=0)
    assert not goal_met(r.state, cond)


GREER_NEWS = {"headline": "US destroyer Greer and a U-boat exchange fire", "subject": "usa"}


def headlined(entries: dict[str, dict[str, Any]]) -> WorldFile:
    """autumn-1941 with its own headlines taken off and the given keys added to the named
    history entries."""
    world = cmp.load_world(cmp.world_path("autumn-1941"))
    bare = {"headline": None, "subject": None, "obj": None}
    schedule = tuple(
        HistoryDecl.model_validate({**h.model_dump(), **bare, **entries.get(h.key, {})})
        for h in world.schedule
    )
    return world.model_copy(update={"schedule": schedule})


def rigged(world: WorldFile, key: str | None = None) -> Rig:
    r = played(None)
    events = compile_world(world, r.campaign, cmp.versions())
    r.state, r.seq = replay(events), len(events)
    if key is not None:
        r.seat(key)
        r.close_session_zero()
    return r


def walk_news(r: Rig) -> list[NewsEvent]:
    """Settle history day by day to 8 Dec, reporting what fires; returns the news."""
    out: list[NewsEvent] = []
    day = START
    while day <= END:
        if day > START:
            r.add(ev.DateAdvanced(to=day))
        settled = history.settle(r.state, day)
        for event in settled:
            r.add(event)
        for reported in history.news(r.state, settled, day):
            r.add(reported)
            out.append(reported.news)
        day += timedelta(days=1)
    return out


def test_a_fired_headlined_event_is_news_once_on_its_day() -> None:
    r = rigged(headlined({"greer_incident": {**GREER_NEWS, "obj": "germany"}}))
    news = walk_news(r)
    assert len(news) == 1
    (item,) = news
    assert item.on == date(1941, 9, 4)
    assert item.topic is NewsTopic.EVENT
    assert item.headline == GREER_NEWS["headline"]
    assert (item.subject, item.obj) == (EntityId(r.ids["usa"]), EntityId(r.ids["germany"]))
    assert r.state.news == {item.news_id: item}


def test_the_news_id_comes_from_the_scheduled_event() -> None:
    world = headlined({"greer_incident": GREER_NEWS})
    first, again = walk_news(rigged(world)), walk_news(rigged(world))
    assert [n.news_id for n in first] == [n.news_id for n in again]
    greer = ScheduledEventId(rigged(world).ids["greer_incident"])
    assert first[0].news_id == derived_id(CAMPAIGN, "news", "history", greer)


def test_an_entry_without_a_headline_is_no_news() -> None:
    r = rigged(headlined({"greer_incident": {"subject": "usa"}}))
    assert walk_news(r) == []
    assert all(s.fired for s in r.state.scheduled.values())


def test_a_skipped_event_is_no_news() -> None:
    world = headlined({"konoe_resigns": {"headline": "Konoe cabinet resigns", "subject": "japan"}})
    assert [n.headline for n in walk_news(rigged(world))] == ["Konoe cabinet resigns"]
    assert walk_news(rigged(world, "konoe")) == []


def test_a_history_event_not_public_is_no_news() -> None:
    r = rigged(headlined({"greer_incident": GREER_NEWS}))
    sid = ScheduledEventId(r.ids["greer_incident"])
    hidden = private_to(SeatId(derived_id(CAMPAIGN, "seat", "hitler")))
    scheduled = {
        **r.state.scheduled,
        sid: r.state.scheduled[sid].model_copy(update={"scope": hidden}),
    }
    r.state = r.state.model_copy(update={"scheduled": scheduled})
    assert walk_news(r) == []
    assert r.state.scheduled[sid].fired


def test_an_entry_without_the_new_keys_dumps_as_before() -> None:
    r = rigged(headlined({}))
    for s in r.state.scheduled.values():
        assert not {"headline", "subject", "obj"} & s.model_dump(mode="json").keys()


def test_a_headline_needs_a_subject() -> None:
    with pytest.raises(ValidationError, match="headline needs a subject"):
        headlined({"greer_incident": {"headline": GREER_NEWS["headline"]}})


def test_the_subject_and_object_must_be_entities() -> None:
    for keys in ({"subject": "nowhere"}, {**GREER_NEWS, "obj": "greer_incident"}):
        with pytest.raises(WorldError) as err:
            compile_world(headlined({"greer_incident": keys}), CAMPAIGN, cmp.versions())
        assert "history greer_incident" in str(err.value)


def test_a_tick_reports_the_fired_event_on_each_press() -> None:
    world = headlined({"greer_incident": {**GREER_NEWS, "obj": "germany"}})
    store = MemoryStore()
    store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
    ids = resolve_keys(world, CAMPAIGN)
    realism_tick.seat_player(store, CAMPAIGN, EntityId(ids["roosevelt"]))
    seat = SeatId(derived_id(CAMPAIGN, "seat", ids["roosevelt"]))
    state = load_state(store, CAMPAIGN)
    for _ in range(10):
        if state.in_world_date is not None and state.in_world_date > date(1941, 9, 5):
            break
        run_realism_tick(store, CAMPAIGN)
        state = load_state(store, CAMPAIGN)
    news = [n for n in state.news.values() if n.topic is NewsTopic.EVENT]
    assert [n.on for n in news] == [date(1941, 9, 4)]
    pages = [
        d
        for d in project(state, seat).documents.values()
        if d.kind is DocumentKind.PRESS
        and state.documents[d.doc_id].truth.news_id == news[0].news_id
    ]
    assert len(pages) == 1
