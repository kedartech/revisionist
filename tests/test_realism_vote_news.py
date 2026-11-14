"""A decided vote is news: one public item per decision, with the count and nothing private."""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FactId, OrderId, PipelineId, derived_id
from revisionist.core.ontology import Fact, SeatKind
from revisionist.core.project import project
from revisionist.core.realism.document import DocumentKind
from revisionist.core.realism.effect import ProposeMeasure
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.pipelines import waiting_on_human
from revisionist.core.realism.press import news_pages
from revisionist.core.realism.resolvers import (
    ON_DAY,
    ON_ORDER,
    Change,
    qid,
    settled_on,
    value,
    votes,
)
from revisionist.core.realism.war import NewsEvent, NewsTopic
from revisionist.core.visibility import private_to
from tests.test_realism_resolvers import CAMPAIGN, Rig, enact_bill, rig
from tests.test_realism_wiring import current, db, fixed_campaign, order_id, run

__all__ = ["db", "fixed_campaign"]  # fixtures the end-to-end test borrows

FILED = date(1941, 10, 9)
SETTLED = date(1941, 11, 17)
WHIP = 9731
"""A whip count no floor vote can reach (a chamber has at most 435 members)."""
SECRET = "WHIP-PRIVATE-5521"


def vote_news(changes: tuple[Change, ...]) -> list[NewsEvent]:
    return [c for c in changes if isinstance(c, NewsEvent) and c.topic is NewsTopic.VOTE]


def walk(r: Rig, start: date = FILED, days: int = 60) -> list[NewsEvent]:
    """Every daily resolver, day by day from ``start``, folded; returns the vote news."""
    out: list[NewsEvent] = []
    for n in range(days):
        for on_day in ON_DAY.values():
            changes = on_day(r.state, start + timedelta(days=n))
            out += vote_news(changes)
            r.fold_changes(changes)
    return out


def count(r: Rig, bill: str, chamber: str) -> str:
    return (
        f"{value(r.state, f'{bill}_{chamber}_yeas')} to {value(r.state, f'{bill}_{chamber}_nays')}"
    )


def decided(r: Rig, bill: str, urgency: str = "ordinary") -> list[NewsEvent]:
    """Enact ``bill``, fold its votes, and walk the days around the decision."""
    order = enact_bill(r, bill, urgency)
    r.fold_changes(ON_ORDER["votes"](r.state, order))
    return walk(r)


def hide(r: Rig, key: str) -> None:
    """Take a world quantity out of the public record."""
    q = qid(r.state, key)
    hidden = r.state.quantities[q].model_copy(update={"scope": None})
    r.state = r.state.model_copy(update={"quantities": {**r.state.quantities, q: hidden}})


def test_a_passed_vote_is_one_news_item_with_the_count() -> None:
    r = rig()
    r.set_value("gallup_fdr_about_right", 61)
    (item,) = decided(r, "neutrality_revision", "urgent")
    assert item.on == SETTLED
    assert item.subject == EntityId(r.ids["usa"])
    assert item.headline == "Neutrality Act revision passes Congress"
    assert [(f.label, f.value) for f in item.facts] == [
        ("House", count(r, "neutrality_revision", "house")),
        ("Senate", count(r, "neutrality_revision", "senate")),
        ("House concurrence", count(r, "neutrality_revision", "concur")),
        ("Result", "Passed"),
        ("Date", "17 November 1941"),
    ]
    assert value(r.state, "neutrality_revision_passed") == 1
    assert r.state.news == {item.news_id: item}


def test_a_failed_vote_is_one_news_item_too() -> None:
    r = rig()
    r.set_value("gallup_fdr_about_right", 0)
    (item,) = decided(r, "draft_extension")
    assert value(r.state, "draft_extension_passed") == 0
    assert item.headline == "Selective Service extension fails in the House"
    assert [(f.label, f.value) for f in item.facts] == [
        ("House", count(r, "draft_extension", "house")),
        ("Senate", count(r, "draft_extension", "senate")),
        ("Result", "Failed"),
        ("Date", "17 November 1941"),
    ]


def test_the_headline_takes_no_side() -> None:
    r = rig()
    r.set_value("gallup_fdr_about_right", 0)
    (failed,) = decided(r, "draft_extension")
    (passed,) = decided(rig(), "lend_lease_appropriation")
    assert passed.headline == "Lend-Lease appropriation passes Congress"
    for item in (failed, passed):
        words = item.headline.lower()
        for loaded in ("defeat", "victory", "win", "lose", "isolation", "intervention", "crush"):
            assert loaded not in words


def test_a_vote_still_open_makes_no_news() -> None:
    r = rig()
    order = r.draft(
        "roosevelt",
        "send_bill",
        "bill_through_congress",
        FILED,
        bill="draft_extension",
        urgency="urgent",
    )
    r.pass_steps(order, [FILED + timedelta(days=n) for n in (8, 9)])
    assert vote_news(ON_ORDER["votes"](r.state, r.state.orders[order.order_id])) == []
    assert walk(r) == []
    r.settle(order, OrderStatus.REFUSED)
    assert walk(r) == []
    assert r.state.news == {}


def test_a_bill_withdrawn_the_day_another_passes_makes_no_news_of_its_own() -> None:
    r = rig()
    order = enact_bill(r, "neutrality_revision")
    r.fold_changes(ON_ORDER["votes"](r.state, order))
    other = r.draft(
        "roosevelt", "send_bill", "bill_through_congress", FILED, bill="neutrality_revision"
    )
    r.pass_steps(other, [FILED + timedelta(days=n) for n in (8, 9, 29, 39)])
    r.settle(other, OrderStatus.WITHDRAWN)
    (item,) = walk(r)
    assert item.news_id == derived_id(CAMPAIGN, "news", "vote", order.order_id)


def test_a_result_overwritten_by_a_later_order_is_not_reported_as_the_earlier_one() -> None:
    r = rig()
    first = enact_bill(r, "neutrality_revision")
    r.fold_changes(ON_ORDER["votes"](r.state, first))
    later = r.enact(
        "roosevelt",
        "send_bill",
        "bill_through_congress",
        FILED,
        [FILED + timedelta(days=n) for n in (9, 10, 30, 40)],
        bill="neutrality_revision",
        urgency="ordinary",
    )
    r.fold_changes(ON_ORDER["votes"](r.state, later))
    (item,) = walk(r, SETTLED + timedelta(days=1), 3)
    assert item.news_id == derived_id(CAMPAIGN, "news", "vote", later.order_id)


def test_one_news_item_per_decision_on_the_day_it_is_decided() -> None:
    r = rig()
    order = enact_bill(r, "neutrality_revision")
    r.fold_changes(ON_ORDER["votes"](r.state, order))
    tally_days = {
        r.state.quantities[qid(r.state, f"neutrality_revision_{chamber}_yeas")].as_of
        for chamber in ("house", "senate", "concur")
    }
    assert len(tally_days) == 3  # each chamber votes on its own day, before the settlement
    for day in sorted(d for d in tally_days if d is not None):
        assert day < SETTLED
        assert vote_news(votes.on_day(r.state, day)) == []
    (item,) = walk(r, FILED, 90)
    assert item.on == SETTLED == settled_on(r.state.orders[order.order_id])
    assert item.news_id == derived_id(CAMPAIGN, "news", "vote", order.order_id)
    assert walk(r, FILED, 90) == []
    assert len(r.state.news) == 1


def test_a_bill_settled_between_wakes_is_reported_on_the_next_day() -> None:
    r = rig()
    order = enact_bill(r, "neutrality_revision")
    r.fold_changes(ON_ORDER["votes"](r.state, order))
    (item,) = walk(r, SETTLED + timedelta(days=1), 5)
    assert item.on == SETTLED


def test_a_decision_from_before_the_last_wake_is_not_reported_late() -> None:
    r = rig()
    order = enact_bill(r, "neutrality_revision")
    r.fold_changes(ON_ORDER["votes"](r.state, order))
    assert walk(r, SETTLED + timedelta(days=2), 30) == []


def test_a_whip_count_is_never_in_the_news() -> None:
    r = rig()
    r.set_value("senate_neutrality_yeas", WHIP)
    r.set_value("house_democrats", WHIP + 1)
    r.set_value("house_republicans", WHIP + 2)
    assert walk(r, date(1941, 9, 1), 60) == []
    (item,) = decided(r, "neutrality_revision")
    dump = item.model_dump_json()
    for whip in (WHIP, WHIP + 1, WHIP + 2):
        assert str(whip) not in dump
    assert [f.label for f in item.facts] == [
        "House",
        "Senate",
        "House concurrence",
        "Result",
        "Date",
    ]


def test_a_world_with_no_public_result_makes_no_news() -> None:
    r = rig()
    hide(r, "draft_extension_passed")
    assert decided(r, "draft_extension") == []
    assert value(r.state, "draft_extension_passed") is not None


def test_a_chamber_count_the_world_keeps_private_is_left_out() -> None:
    r = rig()
    hide(r, "draft_extension_senate_yeas")
    (item,) = decided(r, "draft_extension")
    assert [f.label for f in item.facts] == ["House", "Result", "Date"]


def measure_order(r: Rig, title: str) -> Order:
    """A bill carried as a process part (engine v2), enacted on ``SETTLED``."""
    bill = votes.HISTORICAL["neutrality_revision"]
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "process", title)),
        issuer=r.seats["roosevelt"],
        lever="measure",
        pipeline=PipelineId(r.ids["bill_through_congress"]),
        params={},
        filed=FILED,
        measure=ProposeMeasure(title=title, clauses=bill.clauses),
    )
    r.add(ev.OrderDrafted(order=order))
    r.pass_steps(order, [FILED + timedelta(days=n) for n in (8, 9, 29, 39)])
    return r.settle(order)


def test_a_bill_carried_as_a_measure_is_news_under_its_own_title() -> None:
    r = rig()
    order = measure_order(r, "Coastal Defence Act")
    r.fold_changes(ON_ORDER["votes"](r.state, order))
    (item,) = walk(r)
    verb = "passes Congress" if value(r.state, "neutrality_revision_passed") else "fails in"
    assert item.headline.startswith(f"Coastal Defence Act {verb}")
    assert item.facts[0].value == count(r, "neutrality_revision", "house")


def test_the_press_page_holds_only_the_public_facts() -> None:
    r = Rig()
    roosevelt, churchill = r.seat("roosevelt"), r.seat("churchill")
    r.close_session_zero()
    r.set_value("senate_neutrality_yeas", WHIP)
    fact = Fact(
        fact_id=FactId("f-whip"),
        subject=EntityId(r.ids["rayburn"]),
        predicate="counts",
        obj=SECRET,
        scope=private_to(roosevelt),
    )
    r.add(ev.FactAsserted(fact=fact))
    (item,) = decided(r, "neutrality_revision")
    pages = news_pages(r.state, item.on)
    # Ledger, Sentinel, Chronicle, Alpine Gazette, and the Reichsbote both seats read.
    assert len(pages) == 5
    for page in pages:
        r.add(page)
    dump = "".join(p.model_dump_json() for p in pages)
    assert SECRET not in dump and str(WHIP) not in dump
    r.state = r.state.model_copy(update={"in_world_date": item.on})
    for seat in (roosevelt, churchill):
        held = [
            d for d in project(r.state, seat).documents.values() if d.kind is DocumentKind.PRESS
        ]
        assert len(held) == 3
        assert {d.body for d in held} == {item.facts}
        assert {r.state.documents[d.doc_id].truth.news_id for d in held} == {item.news_id}


@pytest.mark.usefixtures("db", "fixed_campaign")
def test_a_bill_passed_in_play_is_on_the_seat_press_after_the_next_wake() -> None:
    run("new", "autumn-1941", "--seat", "roosevelt")
    oid = order_id(run("lever", "send_bill", "bill=neutrality_revision", "urgency=urgent"))
    for _ in range(200):
        _, state = current()
        if waiting_on_human(state, state.orders[oid]):
            break
        run("tick", "--offline")
    else:
        pytest.fail("the bill never reached Roosevelt's desk")
    run("step", oid, "pass")
    _, state = current()
    assert [n for n in state.news.values() if n.topic is NewsTopic.VOTE] == []
    run("tick", "--offline")
    _, state = current()
    (item,) = (n for n in state.news.values() if n.topic is NewsTopic.VOTE)
    assert item.on == settled_on(state.orders[oid])
    (seat,) = (s.seat_id for s in state.seats.values() if s.kind is SeatKind.PLAYER)
    view = project(state, seat)
    pages = [
        d
        for d in view.documents.values()
        if d.kind is DocumentKind.PRESS and state.documents[d.doc_id].truth.news_id == item.news_id
    ]
    assert len(pages) == 3 and {p.body for p in pages} == {item.facts}
