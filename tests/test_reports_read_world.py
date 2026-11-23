"""Reports that read the world (RPT).

An enacted order's report names the figure it moved and by how much, and never reads "no
change" when something moved. A feed page reads "no change" by its own claims alone: one that
repeats its last full page's claims says so whether or not a hidden figure moved. Over every
playable seat of both worlds, no paper is written by the seat's own person, and every report's
author holds the subject's office. Every reply here is canned.
"""

from datetime import date, timedelta
from typing import Any, cast

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, OrderId, QuantityId, SeatId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.realism.apply import MOVED, apply_due, reporter
from revisionist.core.realism.document import DocumentView, Feed
from revisionist.core.realism.feeds import NO_CHANGE, issue, seed_for_day
from revisionist.core.realism.quantity import Quantity
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, private_to
from tests.test_engine_v2_apply import FILED, estimated
from tests.test_engine_v2_contract import CAMPAIGN, Slice


@pytest.fixture
def sl() -> Slice:
    return Slice()


def _pool(sl: Slice, key: str, owner: str, name: str, value: int) -> QuantityId:
    qid = QuantityId(derived_id(CAMPAIGN, "rpt-pool", key))
    sl.add(
        ev.QuantitySet(
            quantity=Quantity(
                quantity_id=qid,
                owner=sl.entity(owner),
                name=name,
                value=value,
                unit="tons",
                as_of=FILED,
                estimable=True,
            )
        ),
        PUBLIC,
    )
    return qid


def _papers(sl: Slice) -> list[DocumentView]:
    out = apply_due(sl.state, FILED)
    for p in out:
        scope = p.document.scope if isinstance(p, ev.DocumentIssued) else private_to(sl.fdr)
        sl.add(p, scope if isinstance(p, ev.DocumentIssued) else PUBLIC)
    return [p.document for p in out if isinstance(p, ev.DocumentIssued)]


def _lines(doc: DocumentView, label: str) -> list[str]:
    return [str(b.value) for b in doc.body if b.label == label]


# --- rule 1 -------------------------------------------------------------------------------


def test_a_report_names_the_figure_moved_and_by_how_much(sl: Slice) -> None:
    qid = _pool(sl, "steel", "usa", "Steel stocks", 200)
    order = estimated(
        sl, cast(rx.Effect, rx.MoveFigure(quantity=qid, percent=-10)), reason="Output fell."
    )
    [paper] = _papers(sl)
    assert _lines(paper, MOVED) == ["Steel stocks -10%"]
    assert sl.state.quantities[qid].value == 180
    assert order.order_id in sl.state.routed


def test_a_report_that_names_a_move_never_reads_no_change(sl: Slice) -> None:
    qid = _pool(sl, "steel", "usa", "Steel stocks", 200)
    estimated(
        sl,
        cast(rx.Effect, rx.MoveFigure(quantity=qid, percent=5)),
        reason="No change in the mills.",
    )
    [paper] = _papers(sl)
    text = " ".join(str(b.value) for b in paper.body).casefold()
    assert "no change" not in text and _lines(paper, MOVED) == ["Steel stocks +5%"]


def test_an_account_that_moved_nothing_keeps_its_own_words(sl: Slice) -> None:
    estimated(sl, reason="No change in the mills.")
    [paper] = _papers(sl)
    assert _lines(paper, MOVED) == []
    assert _lines(paper, "Account") == ["No change in the mills."]


def test_an_allocation_names_the_issuers_own_pool_and_what_it_gave(sl: Slice) -> None:
    mine = _pool(sl, "mine", "usa", "tonnage", 100)
    _pool(sl, "theirs", "uk", "tonnage", 10)
    estimated(
        sl,
        rx.Allocate(recipient=sl.entity("uk"), what="tonnage", amount=7, unit="tons"),
        reason="Sent.",
    )
    [paper] = _papers(sl)
    assert sl.state.quantities[mine].value == 93
    assert _lines(paper, MOVED) == ["tonnage -7 tons"], "the other nation's pool is not read out"


def _biased(rig: Any, start: date) -> tuple[State, Feed]:
    """The rig's feed skewed to 40 percent with no noise, its first page issued on ``start``."""
    feed = rig.feed.model_copy(
        update={"bias": rig.feed.bias.model_copy(update={"skew_pct": -60, "noise_pct": 0})}
    )
    feeds = {**rig.state.feeds, feed.feed_id: feed}
    first = issue(rig.state.model_copy(update={"feeds": feeds}), feed, start, "s")
    assert first is not None
    rig.add(first)
    return rig.state.model_copy(update={"feeds": feeds}), feed


def test_a_feed_with_no_bias_says_no_change_over_figures_that_held() -> None:
    from tests.test_realism_feeds import Rig, _issue

    rig = Rig()
    start = rig.state.quantities[rig.qid].as_of
    rig.add(_issue(rig.state, rig.feed, start))
    week = start + timedelta(days=7)
    same = issue(rig.state, rig.feed, week, seed_for_day(CAMPAIGN, week))
    assert same is not None and same.document.body[0].label == NO_CHANGE


def test_a_page_that_repeats_its_claim_says_no_change_though_the_truth_moved() -> None:
    from tests.test_realism_feeds import Rig

    rig = Rig()
    start = rig.state.quantities[rig.qid].as_of
    week = start + timedelta(days=7)
    base, feed = _biased(rig, start)
    quiet = issue(base, feed, week, "s")
    assert quiet is not None and quiet.document.body[0].label == NO_CHANGE
    q = base.quantities[rig.qid]
    true = q.value or 0
    claim = (true * 40 + 50) // 100
    step = next(s for s in (1, 2) if ((true + s) * 40 + 50) // 100 == claim)
    moved = q.model_copy(update={"value": true + step})
    page = issue(base.model_copy(update={"quantities": {rig.qid: moved}}), feed, week, "s")
    assert page is not None
    assert [b.label for b in page.document.body] == [NO_CHANGE], (
        "the page repeats its claim, so it reads no change whatever the hidden figure did"
    )


def test_a_page_whose_claim_moved_states_it_in_full() -> None:
    from tests.test_realism_feeds import Rig

    rig = Rig()
    start = rig.state.quantities[rig.qid].as_of
    week = start + timedelta(days=7)
    base, feed = _biased(rig, start)
    q = base.quantities[rig.qid]
    true = (q.value or 0) + 100
    moved = q.model_copy(update={"value": true})
    page = issue(base.model_copy(update={"quantities": {rig.qid: moved}}), feed, week, "s")
    assert page is not None
    assert page.document.body[0].label != NO_CHANGE
    assert page.document.body[0].value == (true * 40 + 50) // 100


# --- rule 2 -------------------------------------------------------------------------------


def _reporters(world: str) -> list[tuple[str, str]]:
    from revisionist.engine import campaign as cmp

    w = cmp.load_world(cmp.world_path(world))
    return [(world, c.person) for c in w.cards if c.playable]


def _claimed(world: str, person: str) -> tuple[State, SeatId, EntityId]:
    from revisionist.core.fold import replay
    from revisionist.core.ids import EventId
    from revisionist.core.world_compile import compile_world, object_id
    from revisionist.engine import campaign as cmp

    w = cmp.load_world(cmp.world_path(world))
    events = list(compile_world(w, CAMPAIGN, cmp.versions()))
    me = EntityId(object_id(CAMPAIGN, "entity", person))
    seat = SeatId(derived_id(CAMPAIGN, "seat", me))
    for n, payload in enumerate(
        (ev.CharacterClaimed(seat_id=seat, entity_id=me), ev.SessionZeroClosed())
    ):
        seq = len(events)
        events.append(
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "rpt-event", n)),
                campaign_id=CAMPAIGN,
                seq=seq,
                tick=0,
                scope=PUBLIC,
                payload=payload,
                versions=cmp.versions(),
            )
        )
    return replay(events), seat, me


@pytest.mark.parametrize(
    ("world", "person"), _reporters("autumn-1941") + _reporters("salt-strait-realism")
)
def test_no_report_is_written_by_the_seats_own_person_and_its_author_holds_the_office(
    world: str, person: str
) -> None:
    state, seat, me = _claimed(world, person)
    card = state.cards[me]
    checked = 0
    for n, domain in enumerate(card.authority):
        order = rx.RoutedOrder(
            order_id=OrderId(derived_id(CAMPAIGN, "rpt-order", person, n)),
            issuer=seat,
            filed=FILED,
            parts=(
                rx.RoutedPart(route=rx.Route.COMMAND, domain=domain.name, executor=domain.executor),
            ),
        )
        held = state.model_copy(update={"routed": {order.order_id: order}})
        author, _ = reporter(held, order, 0)
        assert author != me, f"{person}.{domain.name}: the report is written to himself"
        if domain.executor is not None:
            assert author == domain.executor, "the author holds the office that carried it out"
        else:
            assert author in {c.person for c in card.inner_circle}
        checked += 1
    for contact in card.inner_circle:
        order = rx.RoutedOrder(
            order_id=OrderId(derived_id(CAMPAIGN, "rpt-order", person, contact.person)),
            issuer=seat,
            filed=FILED,
            parts=(rx.RoutedPart(route=rx.Route.INFLUENCE, target=contact.person),),
        )
        held = state.model_copy(update={"routed": {order.order_id: order}})
        assert reporter(held, order, 0)[0] != me
        checked += 1
    assert checked, f"{person} has nothing to report on"
