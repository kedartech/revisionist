"""The in-tray's two server-side rules: acknowledgements and daily-feed groups."""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId
from revisionist.core.project import project
from revisionist.core.realism import effect as rx
from revisionist.core.realism.apply import report_doc_id
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import BodyField, Classification, DocumentKind, DocumentView
from revisionist.core.visibility import PUBLIC
from revisionist.engine.web.realism_api import DocumentListing, DocumentListItem
from revisionist.engine.web.realism_snapshot import documents
from revisionist.engine.web.tray import acknowledgement, feed_group
from tests.test_engine_v2_apply import FILED, executed, land
from tests.test_engine_v2_contract import CAMPAIGN, Slice

DAY = date(1941, 9, 5)


def page(*body: tuple[str, str], kind: DocumentKind = DocumentKind.MEMO) -> DocumentView:
    """A paper with the given body lines, everything else fixed."""
    return DocumentView(
        doc_id=DocumentId("D1"),
        kind=kind,
        author=EntityId("A1"),
        issued=DAY,
        arrives=DAY,
        channel=ChannelKind.IN_PERSON,
        classification=Classification.CONFIDENTIAL,
        title="Shoot on sight in western Atlantic: carried out",
        body=tuple(BodyField(label=k, value=v) for k, v in body),
        scope=PUBLIC,
    )


def tray(
    fidelity: rx.Fidelity | None, refusal: str = "", reason: str = ""
) -> tuple[DocumentListItem, DocumentListing]:
    """The officer's report on a carried-out shoot-on-sight order, as the issuer's tray lists
    it once it has arrived, and the whole listing."""
    sl = Slice()
    order = sl.shoot_on_sight(reason=reason)
    executed(sl, order, fidelity, refusal)
    land(sl, order)
    sl.add(ev.DateAdvanced(to=FILED + timedelta(days=30)))
    listing = documents(project(sl.state, sl.fdr), set(), set())
    report = report_doc_id(CAMPAIGN, order.order_id, 0)
    [row] = [r for r in listing["documents"] if r["id"] == report]
    return row, listing


def test_a_report_carried_out_in_full_with_no_account_is_an_acknowledgement() -> None:
    row, listing = tray(rx.Fidelity.FULL)
    assert row["answer"] and row["unread"] and row["ack"]
    _, loose = tray(rx.Fidelity.LOOSE)
    assert listing["unread"] == loose["unread"] - 1


@pytest.mark.parametrize("fidelity", [rx.Fidelity.LOOSE, rx.Fidelity.SLOW, rx.Fidelity.PARTIAL])
def test_a_report_carried_out_less_than_fully_is_news(fidelity: rx.Fidelity) -> None:
    row, _ = tray(fidelity)
    assert row["answer"] and not row["ack"]


def test_a_full_report_with_an_account_or_a_refusal_is_news() -> None:
    accounted, _ = tray(rx.Fidelity.FULL, reason="The fleet sailed short.")
    refused, _ = tray(None, refusal="loyalty -3")
    assert accounted["answer"] and not accounted["ack"]
    assert refused["answer"] and not refused["ack"]


def test_a_verdict_line_in_a_paper_body_decides_nothing() -> None:
    assert not acknowledgement(page(("Ordered", "Shoot on sight"), ("Carried out", "full")))


def test_a_step_reply_that_only_passed_the_order_on_is_an_acknowledgement() -> None:
    assert acknowledgement(
        page(("What was done", "passed it on"), ("Order", "Attack American ships"))
    )
    assert acknowledgement(page(("What was done", "pressed it forward"), ("Order", "Attack")))


def test_a_step_reply_that_held_amended_or_finished_the_order_is_news() -> None:
    assert not acknowledgement(page(("What was done", "held it"), ("Order", "Attack")))
    assert not acknowledgement(page(("What was done", "passed it on"), ("Changed: Zone", "Arctic")))
    assert not acknowledgement(page(("What was done", "passed it on"), ("Outcome", "enacted")))


def test_press_and_feed_papers_are_never_acknowledgements() -> None:
    assert not acknowledgement(page(("Carried out", "full"), kind=DocumentKind.PRESS))
    assert not acknowledgement(page(("Votes for", "212"), kind=DocumentKind.WHIP_COUNT))


def test_a_dated_feed_title_names_its_group_and_a_one_off_title_does_not() -> None:
    assert feed_group("MAGIC intercepts, 1941-09-03") == "MAGIC intercepts"
    assert feed_group("The Speaker's count, 1941-09-08") == "The Speaker's count"
    assert feed_group("On your order: Attack American ships on sight") is None
    assert feed_group("Moscow situation, week ending 16 October") is None
