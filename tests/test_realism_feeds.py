"""Feeds (unit A2): cadence, determinism, bias, arrival, and truth staying out of views."""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import (
    CampaignId,
    EntityId,
    EventId,
    FeedId,
    QuantityId,
    SeatId,
    derived_id,
)
from revisionist.core.project import project
from revisionist.core.realism.document import Bias, BodyField, Feed
from revisionist.core.realism.feeds import (
    NO_CHANGE,
    RESTATE_DAYS,
    due_feeds,
    issue,
    seed_for_day,
)
from revisionist.core.realism.quantity import Quantity
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.store import MemoryStore, load_state

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
CANARY = "CANARY-FEED-TRUTH-77aa"


class Rig:
    def __init__(self) -> None:
        world = cmp.load_world(cmp.world_path("realism-toy"))
        self.ids = resolve_keys(world, CAMPAIGN)
        self.events = compile_world(world, CAMPAIGN, cmp.versions())
        self.ada = SeatId(derived_id(CAMPAIGN, "seat", "ada"))
        self.add(ev.CharacterClaimed(seat_id=self.ada, entity_id=self.ids["ada"]))
        self.add(ev.SessionZeroClosed())

    def add(self, payload: ev.Payload) -> None:
        seq = len(self.events)
        self.events.append(
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "test-event", seq)),
                campaign_id=CAMPAIGN,
                seq=seq,
                tick=0,
                scope=PUBLIC,
                payload=payload,
                versions=cmp.versions(),
            )
        )

    @property
    def state(self) -> State:
        return replay(self.events)

    @property
    def feed(self) -> Feed:
        return self.state.feeds[FeedId(self.ids["council_count"])]

    @property
    def qid(self) -> QuantityId:
        return QuantityId(self.ids["council_votes"])


@pytest.fixture
def rig() -> Rig:
    return Rig()


def _issue(state: State, feed: Feed, today: date, seed: str = "s") -> ev.DocumentIssued:
    out = issue(state, feed, today, seed)
    assert out is not None
    return out


def _reported(doc: ev.DocumentIssued) -> int | None:
    return doc.document.body[0].value  # type: ignore[return-value]


def test_cadence_first_issue_on_start_then_every_days(rig: Rig) -> None:
    start = rig.state.quantities[rig.qid].as_of
    assert [f.feed_id for f in due_feeds(rig.state, start)] == [rig.feed.feed_id]
    assert due_feeds(rig.state, start - timedelta(days=1)) == []
    rig.add(_issue(rig.state, rig.feed, start))
    assert due_feeds(rig.state, start + timedelta(days=6)) == []
    assert len(due_feeds(rig.state, start + timedelta(days=7))) == 1


def test_a_gap_cadence_never_fires(rig: Rig) -> None:
    gap = rig.feed.model_copy(update={"every_days": None})
    state = rig.state.model_copy(update={"feeds": {gap.feed_id: gap}})
    assert due_feeds(state, date(2100, 1, 1)) == []


def test_same_seed_same_document_and_new_day_new_id(rig: Rig) -> None:
    day = date(1900, 4, 2)
    seed = seed_for_day(CAMPAIGN, day)
    a, b = _issue(rig.state, rig.feed, day, seed), _issue(rig.state, rig.feed, day, seed)
    assert a == b
    other = _issue(rig.state, rig.feed, day + timedelta(days=7), seed_for_day(CAMPAIGN, day))
    assert other.document.doc_id != a.document.doc_id


def test_skew_pushes_the_report_in_its_direction(rig: Rig) -> None:
    day = date(1900, 4, 2)
    true = rig.state.quantities[rig.qid].value
    assert true == 7
    up = rig.feed.model_copy(update={"bias": Bias(skew_pct=50)})
    down = rig.feed.model_copy(update={"bias": Bias(skew_pct=-50)})
    hi, lo = _reported(_issue(rig.state, up, day)), _reported(_issue(rig.state, down, day))
    assert hi is not None and lo is not None
    assert lo < true < hi
    assert (hi, lo) == (11, 4)


def test_noise_stays_within_its_band_and_a_page_with_every_line_left_out_is_not_issued(
    rig: Rig,
) -> None:
    noisy = rig.feed.model_copy(update={"bias": Bias(noise_pct=20)})
    for n in range(20):
        v = _reported(_issue(rig.state, noisy, date(1900, 4, 2), f"seed{n}"))
        assert v is not None and 5 <= v <= 9
    mute = rig.feed.model_copy(update={"bias": Bias(omit_pct=100)})
    assert issue(rig.state, mute, date(1900, 4, 2), "s") is None  # nothing left to state


def test_arrival_is_latency_plus_delay_and_projection_waits(rig: Rig) -> None:
    day = rig.state.in_world_date
    assert day is not None
    delayed = rig.feed.model_copy(update={"bias": Bias(delay_days=2)})
    doc = _issue(rig.state, delayed, day)
    assert doc.document.arrives == day + timedelta(days=1 + 2)
    rig.add(doc)
    did = doc.document.doc_id
    assert did not in project(rig.state, rig.ada).documents
    rig.add(ev.DateAdvanced(to=day + timedelta(days=2)))
    assert did not in project(rig.state, rig.ada).documents
    rig.add(ev.DateAdvanced(to=day + timedelta(days=3)))
    assert did in project(rig.state, rig.ada).documents


def test_truth_never_reaches_the_view(rig: Rig) -> None:
    day = rig.state.in_world_date
    assert day is not None
    doc = _issue(rig.state, rig.feed, day)
    planted = doc.truth.truth_refs[0].model_copy(update={"canary": CANARY})
    rig.add(
        ev.DocumentIssued(
            document=doc.document, truth=doc.truth.model_copy(update={"truth_refs": (planted,)})
        )
    )
    rig.add(ev.DateAdvanced(to=day + timedelta(days=30)))
    assert doc.document.doc_id in rig.state.documents
    raw = project(rig.state, rig.ada).model_dump_json()
    assert doc.document.doc_id in raw and "truth_refs" not in raw and CANARY not in raw


def test_the_document_goes_to_card_holders_only_and_nobody_means_none(rig: Rig) -> None:
    day = rig.state.in_world_date
    assert day is not None
    assert _issue(rig.state, rig.feed, day).document.scope.known_by == {rig.ada}
    bare = rig.state.model_copy(update={"seats": {}})
    assert issue(bare, rig.feed, day, "s") is None


def test_a_feed_whose_every_figure_is_a_gap_issues_nothing(rig: Rig) -> None:
    state = rig.state
    gap = Quantity(
        quantity_id=rig.qid, name="Votes", value=None, unit="votes", as_of=date(1900, 4, 2)
    )
    state = state.model_copy(update={"quantities": {rig.qid: gap}})
    assert issue(state, rig.feed, date(1900, 4, 2), "s") is None


def test_a_feed_with_one_figure_stated_still_issues(rig: Rig) -> None:
    gap = Quantity(
        quantity_id=QuantityId("01ARZ3NDEKTSV4RRFFQ69GAP00"),
        name="Abstentions",
        value=None,
        unit="votes",
        as_of=date(1900, 4, 2),
    )
    state = rig.state.model_copy(
        update={"quantities": {**rig.state.quantities, gap.quantity_id: gap}}
    )
    feed = rig.feed.model_copy(update={"reports": (*rig.feed.reports, gap.quantity_id)})
    doc = _issue(state, feed, date(1900, 4, 2))
    assert [line.value is None for line in doc.document.body] == [False, True]


def _on(rig: Rig, day: date) -> ev.DocumentIssued | None:
    return issue(rig.state, rig.feed, day, seed_for_day(CAMPAIGN, day))


def test_a_page_that_would_repeat_the_last_one_says_no_change_since_its_date(rig: Rig) -> None:
    start = rig.state.quantities[rig.qid].as_of
    rig.add(_issue(rig.state, rig.feed, start))
    week = start + timedelta(days=7)
    page = _on(rig, week)
    assert page is not None
    assert page.document.body == (BodyField(label=NO_CHANGE, value=f"{start.day} {start:%B %Y}"),)
    assert page.document.title.endswith(": no change")
    assert page.truth.truth_refs, "the truth record still holds the figure"
    moved = rig.state.quantities[rig.qid].model_copy(update={"value": 3})
    state = rig.state.model_copy(update={"quantities": {rig.qid: moved}})
    full = issue(state, rig.feed, week, seed_for_day(CAMPAIGN, week))
    assert full is not None and full.document.body[0].label != NO_CHANGE


def test_a_no_change_title_fits_the_title_limit_for_a_long_feed_name(rig: Rig) -> None:
    start = rig.state.quantities[rig.qid].as_of
    feed = rig.feed.model_copy(update={"name": "Atlantic reports from the Navy Department"})
    state = rig.state.model_copy(update={"feeds": {**rig.state.feeds, feed.feed_id: feed}})
    rig.add(_issue(state, feed, start))
    state = rig.state.model_copy(update={"feeds": {**rig.state.feeds, feed.feed_id: feed}})
    week = start + timedelta(days=7)
    page = issue(state, feed, week, seed_for_day(CAMPAIGN, week))
    assert page is not None
    assert len(page.document.title) <= 60
    assert page.document.title.endswith(f"{week.isoformat()}: no change")


def test_no_change_counts_from_the_last_full_page_not_the_last_no_change_page(rig: Rig) -> None:
    start = rig.state.quantities[rig.qid].as_of
    rig.add(_issue(rig.state, rig.feed, start))
    rig.add(_issue(rig.state, rig.feed, start + timedelta(days=7)))
    page = _on(rig, start + timedelta(days=13))
    assert page is not None
    assert page.document.body == (BodyField(label=NO_CHANGE, value=f"{start.day} {start:%B %Y}"),)


def test_an_unchanged_page_is_stated_in_full_again_once_the_last_full_page_is_old(
    rig: Rig,
) -> None:
    start = rig.state.quantities[rig.qid].as_of
    first = _issue(rig.state, rig.feed, start)
    rig.add(first)
    page = _on(rig, start + timedelta(days=RESTATE_DAYS))
    assert page is not None
    assert page.document.body == first.document.body


def test_a_sighting_page_that_would_repeat_says_no_change_and_places_nothing() -> None:
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path("autumn-1941"))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    realism_tick.seat_player(store, CAMPAIGN, EntityId(resolve_keys(decl, CAMPAIGN)["churchill"]))
    state = load_state(store, CAMPAIGN)
    feed = state.feeds[FeedId(resolve_keys(decl, CAMPAIGN)["admiralty_reports"])]
    first = next(d.view for d in state.documents.values() if d.truth.feed == feed.feed_id)
    assert any(line.sight for line in first.body), "seating issues the opening sighting page"
    start = first.issued
    week = start + timedelta(days=7)
    page = issue(state, feed, week, seed_for_day(CAMPAIGN, week))
    assert page is not None
    assert [line.label for line in page.document.body] == [NO_CHANGE]
    assert page.truth.sightings == ()
