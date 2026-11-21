"""Catch-up from the server: the seam ``engine.catchup.seat_events``, the ``catchup``
realism action, and the owner's note of what the aide did (CUP; invariants 5 and 6).
"""

import contextlib
import json
import re
import typing
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core import ontology, record
from revisionist.core.ids import (
    ContestId,
    DocumentId,
    EntityId,
    EventId,
    FactId,
    GoalId,
    MandateId,
    OrderId,
    QuantityId,
    ScheduledEventId,
    SeatId,
    derived_id,
)
from revisionist.core.project import project
from revisionist.core.realism import agenda as ra
from revisionist.core.realism import effect as rx
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.effect import Fidelity
from revisionist.core.realism.locks import HeldEnd
from revisionist.core.realism.pipeline import OrderStatus, StepAction, StepOutcome
from revisionist.core.realism.quantity import Quantity
from revisionist.core.sealing import scopes_in
from revisionist.core.state import View
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, options, realism_tick
from revisionist.engine.store import MemoryStore
from revisionist.engine.web import catchup_api
from tests.async_table import AsyncTable
from tests.test_engine_v2_wake import CAMPAIGN
from tests.test_web import PASSWORD, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post
from tests.test_web_wake import begin, log_of, seat_of

WORLD = "engine-v2-slice-1941"
LATER = "catch-up-canary-not-arrived"
ENGINE_ONLY = "catch-up-canary-engine-only"


def payload_kinds() -> set[str]:
    union = typing.get_args(ev.Payload)[0]
    return {m.model_fields["kind"].default for m in typing.get_args(union)}


# --- Every event kind is classified ------------------------------------------------


def test_every_event_kind_is_in_exactly_one_list() -> None:
    kinds = payload_kinds()
    both = sorted(catchup.FEED_KINDS & catchup.NEVER)
    unclassified = sorted(kinds - catchup.FEED_KINDS - catchup.NEVER)
    stale = sorted((catchup.FEED_KINDS | catchup.NEVER) - kinds)
    assert not (both or unclassified or stale), (
        "src/revisionist/engine/catchup.py: every kind in events.Payload goes in exactly "
        f"one of FEED_KINDS or NEVER. Unclassified: {unclassified}. In both: {both}. "
        f"Not a kind: {stale}."
    )


def test_never_holds_the_close_the_commit_the_estimates_and_the_costs() -> None:
    for kind in (
        "wake_committed",
        "wake_closed",
        "effects_estimated",
        "cost_logged",
        "tick_stage_completed",
        "feature_set",
        "cards_declared",
        "agent_assigned",
        # A seat learns news from its press paper, never from the structured item.
        "news_reported",
    ):
        assert kind in catchup.NEVER, kind
    # The seat's own routed order is fed, as its view (``RoutedOrderView``) only.
    assert "order_routed" in catchup.FEED_KINDS


def test_the_board_is_fed_to_every_seat() -> None:
    # The map is public and the same in every view: no seat's feed leaves it out.
    assert "map_declared" in catchup.FEED_KINDS


def test_the_worlds_kinds_are_fed_to_every_seat() -> None:
    # The piece kinds and resources are public rules of the world, like the board.
    assert "kinds_declared" in catchup.FEED_KINDS


def test_a_pieces_steps_are_fed_and_feature_set_never_is() -> None:
    # Playback's source for a seat's own pieces: each step, sealed to the seats of the
    # piece's nation. The raw feature is never fed.
    assert "piece_stepped" in catchup.FEED_KINDS
    assert "feature_set" in catchup.NEVER


def test_a_battle_decision_is_never_fed() -> None:
    # BDC: the decision is the seat's own order, already fed; a join carries the true
    # strength a side brought.
    assert "battle_decided" in catchup.NEVER


def test_a_groups_true_support_is_never_fed() -> None:
    # GRP: a seat reads its own nation's groups from its own data, others' from the press;
    # the declaration and the writing in waiting are engine only.
    assert {"groups_declared", "group_moved", "group_proposed"} <= catchup.NEVER


def test_offers_and_agreements_are_fed_to_their_parties() -> None:
    # AGR: scoped to the parties' seats (public once published), and kept only when the
    # agreement is in the seat's view.
    kinds = {"agreement_offered", "agreement_made", "clause_judged", "agreement_published"}
    assert kinds <= catchup.FEED_KINDS


def test_a_held_order_and_its_end_are_fed_to_its_own_seat_only() -> None:
    # LCK: sealed to the issuer's seat, and kept only for the seat whose order it is,
    # whatever the envelope says.
    assert {"order_held", "held_order_ended"} <= catchup.FEED_KINDS
    held = ev.HeldOrderEnded(
        order_id=OrderId("held"),
        issuer=SeatId("mine"),
        end=HeldEnd.REPLACED,
        on=date(1941, 9, 1),
        by=OrderId("later"),
    )
    mine = typing.cast(View, SimpleNamespace(viewer=SeatId("mine")))
    other = typing.cast(View, SimpleNamespace(viewer=SeatId("other")))
    assert catchup._named(held, mine) and not catchup._named(held, other)


def test_a_conferences_call_and_tally_are_fed_and_a_sealed_vote_never_is() -> None:
    # CNF: the call and the tally go to the invited seats (or everyone, when public) and
    # are kept only when the conference is in the seat's view; a vote is the voter's own.
    assert {"conference_called", "conference_tallied"} <= catchup.FEED_KINDS
    assert "vote_sealed" in catchup.NEVER
    assert "vote_sealed" not in catchup.FEED_KINDS


# --- The fog path ------------------------------------------------------------------


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncTable:
    return AsyncTable(MemoryStore(), monkeypatch, tmp_path)


def three_wakes(t: AsyncTable, monkeypatch: pytest.MonkeyPatch) -> None:
    """Roosevelt plays wakes 0 to 2 himself; Churchill's aide plays them."""
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: t.aide_orders())
    t.open_play()
    for _ in range(3):
        t.file(t.fdr, t.shoot_on_sight())
        t.commit(t.fdr)
        t.close()


def not_yet_arrived(t: AsyncTable, seat: SeatId) -> DocumentId:
    """A paper for ``seat`` issued today that arrives in thirty days."""
    state = t.state
    today = state.in_world_date
    assert today is not None
    doc_id = DocumentId(derived_id(CAMPAIGN, "catch-up-later", seat))
    view = DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.REPORT,
        author=state.seats[seat].embodies,
        issued=today,
        arrives=today + timedelta(days=30),
        channel=ChannelKind.COURIER,
        title="Later",
        scope=private_to(seat),
    )
    truth = DocumentTruth(doc_id=doc_id)
    payloads: list[ev.Payload] = [
        ev.DocumentIssued(document=view, truth=truth),
        ev.DocumentWritten(doc_id=doc_id, prose=LATER),
    ]
    t.store.append_all(
        [
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "catch-up-later-event", seat, n)),
                campaign_id=CAMPAIGN,
                seq=state.last_seq + 1 + n,
                tick=state.tick,
                scope=private_to(seat),
                payload=payload,
                versions=cmp.versions(),
            )
            for n, payload in enumerate(payloads)
        ]
    )
    return doc_id


def feed_of(t: AsyncTable, seat: SeatId) -> tuple[catchup.SeatEvent, ...]:
    state = t.state
    assert state.wake is not None
    return catchup.seat_events(t.store, CAMPAIGN, seat, 0, state.wake.number)


def test_the_feed_holds_only_what_the_seat_may_see(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every event is visible to the seat, inside and out, of a kind in ``FEED_KINDS``,
    and every paper in it is one ``project(state, seat)`` holds."""
    t = table
    three_wakes(t, monkeypatch)
    state = t.state
    for seat in t.seats:
        found = feed_of(t, seat)
        assert found, seat
        view = project(state, seat)
        docs = [f.event.payload for f in found if isinstance(f.event.payload, ev.DocumentIssued)]
        assert docs, "the seat had papers"
        for doc in docs:
            assert doc.document.doc_id in view.documents
            assert doc.truth == DocumentTruth(doc_id=doc.document.doc_id), "truth stays home"
        for f in found:
            assert f.event.kind in catchup.FEED_KINDS, f.event.kind
            if isinstance(f.event.payload, ev.QuantitySet):
                assert f.event.payload.quantity.scope is not None, "an engine-only quantity"
            for scope in [f.event.scope, *scopes_in(f.event.payload)]:
                assert scope.visible_to(seat), (f.event.kind, scope)
        assert [f.wake for f in found] == sorted(f.wake for f in found)


def test_a_paper_not_yet_arrived_is_not_in_the_feed(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = table
    three_wakes(t, monkeypatch)
    later = not_yet_arrived(t, t.fdr)
    assert later not in project(t.state, t.fdr).documents
    issued = [
        f.event.payload.document.doc_id
        for f in feed_of(t, t.fdr)
        if isinstance(f.event.payload, ev.DocumentIssued)
    ]
    assert later not in issued
    ahead = catchup.seat_events(t.store, CAMPAIGN, t.fdr, 0, 99)
    assert LATER not in json.dumps([f.event.model_dump(mode="json") for f in ahead])


def test_another_seats_form_order_is_not_in_the_feed(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A form order lands under a public envelope; only its issuer's feed holds it."""
    t = table
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: t.aide_orders())
    t.open_play()
    order = realism_tick.file_order(
        t.store, CAMPAIGN, t.fdr, "send_bill", {"bill": "neutrality_revision"}
    )
    t.commit(t.fdr)
    t.close()
    t.close()
    mine = json.dumps([f.event.model_dump(mode="json") for f in feed_of(t, t.fdr)])
    assert order.order_id in mine
    theirs = json.dumps([f.event.model_dump(mode="json") for f in feed_of(t, t.churchill)])
    assert order.order_id not in theirs


def test_nothing_another_seat_holds_is_named_in_the_feed(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No order, goal, mandate or contest outside the seat's view is named in its feed."""
    t = table
    three_wakes(t, monkeypatch)
    state = t.state
    for seat in t.seats:
        view = project(state, seat)
        text = json.dumps([f.event.model_dump(mode="json") for f in feed_of(t, seat)])
        hidden = (
            {*state.orders, *state.routed} - {*view.orders, *view.routed}
            | set(state.goals) - set(view.goals)
            | set(state.mandates) - set(view.mandates)
            | set(state.contests) - set(view.contests)
        )
        assert hidden, "the other seat holds something"
        assert not [k for k in hidden if k in text]


def test_a_private_fact_or_engine_truth_under_a_public_envelope_stays_home(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fact private to Churchill reaches his feed only; a figure only the engine
    holds reaches no feed."""
    t = table
    three_wakes(t, monkeypatch)
    state = t.state
    today = state.in_world_date
    assert today is not None
    fact = ontology.Fact(
        fact_id=FactId(derived_id(CAMPAIGN, "catch-up-fact")),
        subject=state.seats[t.churchill].embodies,
        predicate="catch_up_canary",
        obj=LATER,
        scope=private_to(t.churchill),
    )
    figure = Quantity(
        quantity_id=QuantityId(derived_id(CAMPAIGN, "catch-up-figure")),
        name=ENGINE_ONLY,
        value=1,
        unit="ships",
        as_of=today,
    )
    payloads: list[ev.Payload] = [ev.FactAsserted(fact=fact), ev.QuantitySet(quantity=figure)]
    t.store.append_all(
        [
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "catch-up-public-envelope", n)),
                campaign_id=CAMPAIGN,
                seq=state.last_seq + 1 + n,
                tick=state.tick,
                scope=PUBLIC,
                payload=payload,
                versions=cmp.versions(),
            )
            for n, payload in enumerate(payloads)
        ]
    )
    theirs = json.dumps([f.event.model_dump(mode="json") for f in feed_of(t, t.churchill)])
    mine = json.dumps([f.event.model_dump(mode="json") for f in feed_of(t, t.fdr)])
    assert LATER in theirs and LATER not in mine
    assert ENGINE_ONLY not in theirs + mine


ELSEWHERE = "catch-up-elsewhere"


def naming_elsewhere(t: AsyncTable) -> list[ev.Payload]:
    """One event of each kind that names something by id, naming what the seat lacks."""
    other = next(o for o in t.state.routed.values() if o.issuer == t.churchill)
    on = other.filed
    held = (other.order_id, ELSEWHERE)
    return [
        ev.OrderStepTaken(
            order_id=OrderId(ELSEWHERE),
            outcome=StepOutcome(
                step=0, person=t.entity("churchill"), action=StepAction.PASS, on=on
            ),
        ),
        ev.OrderSettled(order_id=OrderId(ELSEWHERE), status=OrderStatus.ENACTED),
        ev.OrderRouted(order=other),
        *(
            ev.OrderExecuted(order_id=OrderId(o), part=0, on=on, fidelity=Fidelity.FULL)
            for o in held
        ),
        *(ev.EffectsApplied(order_id=OrderId(o), part=0, on=on) for o in held),
        *(ev.InfluenceDecided(order_id=OrderId(o), part=0, on=on, accepted=True) for o in held),
        ev.GoalProgressed(goal_id=GoalId(ELSEWHERE), parts_met=1),
        ev.GoalMet(goal_id=GoalId(ELSEWHERE)),
        ev.GoalUndone(goal_id=GoalId(ELSEWHERE)),
        ev.ContestMoved(contest_id=ContestId(ELSEWHERE), change=1),
        ev.ContestDecided(contest_id=ContestId(ELSEWHERE)),
        ev.ScheduledEventFired(scheduled_id=ScheduledEventId(ELSEWHERE)),
        ev.MandateSettled(mandate_id=MandateId(ELSEWHERE), status=ra.MandateStatus.EXPIRED),
        ev.NarrationWritten(seat_id=t.churchill, text=ELSEWHERE),
        ev.BriefingDelivered(
            seat_id=t.churchill, narration=EventId(ELSEWHERE), channel="web", idempotency_key="k"
        ),
    ]


def test_an_event_naming_what_the_seat_lacks_is_not_in_the_feed(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under a public envelope, an event naming another seat's order, goal, contest,
    mandate, history event or narration stays out of the seat's feed, kind by kind."""
    t = table
    three_wakes(t, monkeypatch)
    state = t.state
    log = list(t.store.read(CAMPAIGN))
    planted = naming_elsewhere(t)
    extra = [
        ev.Event(
            event_id=EventId(derived_id(CAMPAIGN, "catch-up-elsewhere", n)),
            campaign_id=CAMPAIGN,
            seq=state.last_seq + 1 + n,
            tick=state.tick,
            scope=PUBLIC,
            payload=payload,
            versions=cmp.versions(),
        )
        for n, payload in enumerate(planted)
    ]
    fed = {f.event.event_id for f in catchup.feed(state, [*log, *extra], t.fdr, 0, 99)}
    assert not [e.kind for e in extra if e.event_id in fed]
    assert {e.kind for e in extra} <= catchup.FEED_KINDS


def test_a_paper_belongs_to_the_wake_whose_page_shows_it(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The feed puts each paper in the wake the record's page lists it under."""
    t = table
    three_wakes(t, monkeypatch)
    state = t.state
    pages = record.build(state, list(t.store.read(CAMPAIGN)), t.fdr).wakes
    found = feed_of(t, t.fdr)
    by_wake = {
        page.number: sorted(
            f.event.payload.document.doc_id
            for f in found
            if f.wake == page.number and isinstance(f.event.payload, ev.DocumentIssued)
        )
        for page in pages
    }
    assert by_wake == {page.number: sorted(p.doc_id for p in page.papers) for page in pages}
    assert sum(len(v) for v in by_wake.values()) > len(by_wake[0]), "papers after wake 0"


def test_an_order_settles_in_the_wake_whose_page_shows_it(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A part carried out while the wake ran belongs to the next wake's page, as the
    record's ``settled`` has it."""
    t = table
    three_wakes(t, monkeypatch)
    state = t.state
    pages = record.build(state, list(t.store.read(CAMPAIGN)), t.fdr).wakes
    found = feed_of(t, t.fdr)
    by_wake = {
        page.number: sorted(
            f"{f.event.payload.order_id}.{f.event.payload.part}"
            for f in found
            if f.wake == page.number and isinstance(f.event.payload, ev.EffectsApplied)
        )
        for page in pages
    }
    assert by_wake == {page.number: sorted(k for k in page.settled if "." in k) for page in pages}
    assert any(by_wake.values()), "a part settled"


def test_the_feed_keeps_to_the_range(table: AsyncTable, monkeypatch: pytest.MonkeyPatch) -> None:
    t = table
    three_wakes(t, monkeypatch)
    whole = feed_of(t, t.fdr)
    middle = catchup.seat_events(t.store, CAMPAIGN, t.fdr, 1, 2)
    assert middle == tuple(f for f in whole if 1 <= f.wake <= 2)
    assert {f.wake for f in middle} == {1, 2}
    assert catchup.seat_events(t.store, CAMPAIGN, t.fdr, 2, 1) == ()


def test_a_history_event_reaches_no_seat_as_news(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The USS Greer exchange fires in public with a headline; the log holds its news
    item, and no seat's feed does at any wake."""
    t = table
    three_wakes(t, monkeypatch)
    log = list(t.store.read(CAMPAIGN))
    assert any(isinstance(e.payload, ev.ScheduledEventFired) for e in log), "a history event"
    assert any(isinstance(e.payload, ev.NewsReported) for e in log), "its news was logged"
    for seat in t.seats:
        found = catchup.seat_events(t.store, CAMPAIGN, seat, 0, 99)
        assert found, seat
        assert not [f for f in found if isinstance(f.event.payload, ev.NewsReported)], seat
    public = ev.Event(
        event_id=EventId(derived_id(CAMPAIGN, "catch-up-news-public")),
        campaign_id=CAMPAIGN,
        seq=t.state.last_seq + 1,
        tick=t.state.tick,
        scope=PUBLIC,
        payload=next(e.payload for e in log if isinstance(e.payload, ev.NewsReported)),
        versions=cmp.versions(),
    )
    for seat in t.seats:
        fed = catchup.feed(t.state, [*log, public], seat, 0, 99)
        assert public.event_id not in {f.event.event_id for f in fed}, seat


ASKED = "catch-up-canary-asked"


def test_a_routed_order_is_fed_as_its_view_only(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The issuer's own routed order reaches its feed with the view's fields and
    nothing the engine keeps: no ``ask``, no ``estimated`` effect, no held answer."""
    t = table
    three_wakes(t, monkeypatch)
    state = t.state
    log = list(t.store.read(CAMPAIGN))
    mine = next(o for o in state.routed.values() if o.issuer == t.fdr)
    engine_side = mine.model_copy(
        update={
            "parts": tuple(
                p.model_copy(
                    update={
                        "ask": ASKED,
                        "estimated": (rx.MakeStatement(theme=ENGINE_ONLY),),
                        "was_estimated": True,
                        "held_answer": True,
                    }
                )
                for p in mine.parts
            )
        }
    )
    planted = ev.Event(
        event_id=EventId(derived_id(CAMPAIGN, "catch-up-routed-whole")),
        campaign_id=CAMPAIGN,
        seq=state.last_seq + 1,
        tick=state.tick,
        scope=private_to(t.fdr),
        payload=ev.OrderRouted(order=engine_side),
        versions=cmp.versions(),
    )
    logged = {e.event_id: e.payload for e in [*log, planted]}
    fed = [
        (f.event.event_id, f.event.payload)
        for f in catchup.feed(state, [*log, planted], t.fdr, 0, 99)
        if isinstance(f.event.payload, ev.OrderRouted)
    ]
    assert planted.event_id in dict(fed), "the planted order is the seat's own"
    assert len(fed) > 1, "the seat's routed orders are fed"
    for event_id, p in fed:
        whole = json.dumps(p.model_dump(mode="json"))
        assert ASKED not in whole and ENGINE_ONLY not in whole
        for part in p.order.parts:
            assert part.ask == "" and part.estimated == () and part.held_answer is None
            assert not part.was_estimated
            assert "ask" not in part.model_dump(mode="json")
        source = logged[event_id]
        assert isinstance(source, ev.OrderRouted)
        assert p.order.view() == source.order.view(), "the view is whole"


ID = re.compile(r"\b[0-9A-Za-z]{26}\b|\b[0-9a-f]{32}\b|\b[0-9a-f-]{36}\b")


def shapes(t: AsyncTable, seat: SeatId) -> list[tuple[int, str, str]]:
    """The feed with every id replaced by its first-seen index."""
    seen: dict[str, str] = {}

    def plain(text: str) -> str:
        return ID.sub(lambda m: seen.setdefault(m.group(0), f"id{len(seen)}"), text)

    return [
        (f.wake, f.event.kind, plain(json.dumps(f.event.payload.model_dump(mode="json"))))
        for f in feed_of(t, seat)
    ]


def test_the_feed_is_the_same_whether_the_seat_or_its_aide_played(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Churchill files the aide's orders himself in one game; his aide files them in
    the other. His feed cannot tell the two apart."""

    def game(by_aide: bool) -> list[tuple[int, str, str]]:
        with monkeypatch.context() as m:
            t = AsyncTable(MemoryStore(), m, tmp_path / str(by_aide))
            m.setattr(options, "aide_asks", lambda state, seat, transport: t.aide_orders())
            t.open_play()
            if not by_aide:
                for asks in t.aide_orders():
                    with contextlib.suppress(ValueError):  # what the aide cannot route, it drops
                        t.file(t.churchill, *asks)
                t.commit(t.churchill)
            t.commit(t.fdr)
            t.close()
            played = [
                e.payload.by_aide
                for e in t.store.read(CAMPAIGN)
                if isinstance(e.payload, ev.WakeCommitted) and e.payload.seat_id == t.churchill
            ]
            assert played == [by_aide]
            return shapes(t, t.churchill)

    by_hand, by_aide = game(False), game(True)
    assert any(kind == "order_routed" for _, kind, _ in by_hand)
    assert by_hand == by_aide


# --- The catchup action ------------------------------------------------------------


def test_an_aide_commit_logged_in_public_gives_no_note_to_another_seat(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A log from before the aide's commit was sealed holds it under a public envelope;
    only the seat it played gets the note."""
    t = table
    three_wakes(t, monkeypatch)
    old_log = [
        e.model_copy(update={"scope": PUBLIC})
        if isinstance(e.payload, ev.WakeCommitted) and e.payload.by_aide
        else e
        for e in t.store.read(CAMPAIGN)
    ]
    state = t.state
    whole = {"first": 0, "last": 2}
    theirs = catchup_api.reply(state, old_log, t.churchill, whole)
    assert all(p.get("aide_filed") for p in theirs["pages"]), theirs
    mine = catchup_api.reply(state, old_log, t.fdr, whole)
    assert [p["number"] for p in mine["pages"]] == [0, 1, 2]
    assert not [p for p in mine["pages"] if "aide_filed" in p]


def away(web: Web) -> tuple[Realism, Any, Any]:  # noqa: F811
    """Ada (Roosevelt) commits wakes 0 to 2 herself; Bea (Churchill) is away and her
    aide plays them. Bea comes back in a fresh browser."""
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    game.seat("bea", "churchill")
    make_host(game, ada)
    begin(game)
    for _ in range(3):
        post(ada, "commit")
        _, out = post(ada, "close")
        assert not out["refused"], out
    fresh = web.client()
    status, out = fresh.call("/api/signin", {"handle": "bea", "password": PASSWORD})
    assert status == 200, out
    return game, ada, fresh


def aide_labels(game: Realism, seat: SeatId) -> dict[int, list[str]]:
    """What the log says the aide filed for ``seat``, wake by wake, in the seat's words."""
    log = log_of(game)
    asked: dict[str, str] = {}
    for e in log:
        if isinstance(e.payload, ev.OrderRouted) and e.payload.order.issuer == seat:
            asked[e.payload.order.order_id] = "; ".join(
                p.ask.strip() for p in e.payload.order.parts
            )
    return {
        e.payload.wake: [asked[o] for o in e.payload.aide_orders if o in asked]
        for e in log
        if isinstance(e.payload, ev.WakeCommitted)
        and e.payload.by_aide
        and e.payload.seat_id == seat
    }


def test_catchup_gives_a_page_for_each_wake_missed_with_the_aides_note(
    web: Web,  # noqa: F811
) -> None:
    game, _, fresh = away(web)
    status, out = post(fresh, "catchup")
    assert status == 200, out
    assert (out["first"], out["last"]) == (0, 2)
    pages = out["pages"]
    assert [p["number"] for p in pages] == [0, 1, 2]
    for p in pages:
        assert {"number", "opened", "days_passed", "papers", "filed", "settled"} <= set(p)
    labels = aide_labels(game, seat_of(game, "churchill"))
    assert set(labels) == {0, 1, 2}
    assert {p["number"]: p["aide_filed"] for p in pages} == labels


def test_catchup_starts_after_the_seats_own_last_commit(web: Web) -> None:  # noqa: F811
    _, ada, fresh = away(web)
    _, out = post(ada, "catchup")
    assert out["pages"] == [] and out["first"] == 3 and out["last"] == 2
    post(fresh, "commit")
    _, out = post(fresh, "catchup")
    assert out["pages"] == [], "Bea committed herself in wake 3, which is still open"


def test_catchup_serves_a_named_range_and_the_note_only_to_its_owner(
    web: Web,  # noqa: F811
) -> None:
    _, ada, fresh = away(web)
    _, out = post(ada, "catchup", first=0, last=2)
    assert [p["number"] for p in out["pages"]] == [0, 1, 2]
    text = json.dumps(out)
    for word in ("aide_filed", "aide_orders", "by_aide", "timed_out"):
        assert word not in text, word
    _, named = post(ada, "catchup", first=1)
    assert (named["first"], named["last"]) == (1, 2), named
    _, mine = post(fresh, "catchup", first=1, last=1)
    assert [p["number"] for p in mine["pages"]] == [1]
    assert "aide_filed" in mine["pages"][0]


@pytest.mark.parametrize(
    "body",
    [
        {"first": 2, "last": 1},
        {"first": -1, "last": 1},
        {"first": 0, "last": 9},
        {"first": "0", "last": 1},
        {"first": True, "last": 1},
    ],
)
def test_catchup_refuses_a_range_it_cannot_serve(
    web: Web,  # noqa: F811
    body: dict[str, Any],
) -> None:
    _, ada, _ = away(web)
    status, out = post(ada, "catchup", **body)
    assert status == 200 and out["refused"] is True, out


def test_catchup_api_pages_have_the_record_shape() -> None:
    """A page carries the record block's wake fields, so the client reads one shape."""
    fields = set(typing.get_type_hints(catchup_api.CatchupPage))
    assert {"number", "opened", "days_passed", "papers", "filed", "settled", "aide_filed"} <= (
        fields
    )


def test_an_ask_is_fed_to_the_asker_and_the_seat_asked_only() -> None:
    # ASK: sealed to the asker and the seat holding the person asked, whatever the
    # envelope says; an ask to a card no seat holds reaches the asker only.
    from revisionist.core.realism.locks import Asked

    assert "order_asked" in catchup.FEED_KINDS
    asked = Asked(
        order_id=OrderId("held"),
        asker=SeatId("mine"),
        by=EntityId("kara"),
        to=EntityId("ilse"),
        seat=SeatId("hers"),
        words="March (To Isle)",
        on=date(1941, 9, 1),
    )

    def seen(payload: ev.OrderAsked, viewer: str) -> bool:
        return catchup._named(payload, typing.cast(View, SimpleNamespace(viewer=SeatId(viewer))))

    made = ev.OrderAsked(asked=asked)
    assert seen(made, "mine") and seen(made, "hers") and not seen(made, "other")
    to_card = ev.OrderAsked(asked=asked.model_copy(update={"seat": None}))
    assert seen(to_card, "mine") and not seen(to_card, "hers")
