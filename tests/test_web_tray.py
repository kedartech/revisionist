"""The in-tray's two server-side rules: acknowledgements and daily-feed groups."""

from datetime import date

import pytest

from revisionist.core.ids import DocumentId, EntityId
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import BodyField, Classification, DocumentKind, DocumentView
from revisionist.core.visibility import PUBLIC
from revisionist.engine.web.tray import acknowledgement, feed_group

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


def test_a_report_carried_out_in_full_with_no_account_is_an_acknowledgement() -> None:
    assert acknowledgement(page(("Ordered", "Shoot on sight"), ("Carried out", "full")))


@pytest.mark.parametrize("fidelity", ["loose", "slow", "partial", "posture only"])
def test_a_report_carried_out_less_than_fully_is_news(fidelity: str) -> None:
    assert not acknowledgement(page(("Ordered", "Shoot on sight"), ("Carried out", fidelity)))


def test_a_full_report_with_an_account_or_a_refusal_is_news() -> None:
    assert not acknowledgement(
        page(("Carried out", "full"), ("Account", "The fleet sailed short."))
    )
    assert not acknowledgement(page(("Ordered", "Shoot on sight"), ("Refused under", "loyalty -3")))


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
