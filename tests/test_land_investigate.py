"""Investigate lands as a private report built only from what the issuing seat can see."""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import FactId, derived_id
from revisionist.core.ontology import Fact
from revisionist.core.project import project
from revisionist.core.realism import effect as rx
from revisionist.core.realism.document import BodyField, Classification, DocumentKind
from revisionist.core.realism.land import investigate
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.visibility import PUBLIC, Scope, private_to
from tests.test_engine_v2_contract import CAMPAIGN, Slice

ON = date(1941, 9, 11)
LEAK = "LEAK-E5-wheeler-cable-to-berlin"


@pytest.fixture
def sl() -> Slice:
    return Slice()


def add_fact(sl: Slice, key: str, predicate: str, obj: str, scope: Scope) -> None:
    fact = Fact(
        fact_id=FactId(derived_id(CAMPAIGN, "e5-fact", key)),
        subject=sl.entity("pound"),
        predicate=predicate,
        obj=obj,
        scope=scope,
    )
    sl.add(ev.FactAsserted(fact=fact), scope)


def inquire(sl: Slice) -> list[ev.Payload]:
    landed, revealed = investigate.land(
        PassWorld(sl.state),
        rx.Investigate(target=sl.entity("pound"), question="What is Pound doing?"),
        sl.fdr,
        sl.entity("roosevelt"),
        ON,
    )
    assert revealed == []
    return landed


def report(sl: Slice) -> ev.DocumentIssued:
    (payload,) = inquire(sl)
    assert isinstance(payload, ev.DocumentIssued)
    return payload


def test_report_lists_visible_facts(sl: Slice) -> None:
    add_fact(sl, "funds", "funds", "Treasury loan", PUBLIC)
    add_fact(sl, "visit", "visits", sl.entity("churchill"), PUBLIC)
    body = report(sl).document.body
    assert len(body) == 2
    assert BodyField(label="funds", value="Treasury loan") in body
    assert BodyField(label="visits", value="Winston Churchill") in body


def test_report_omits_fact_private_to_another_seat(sl: Slice) -> None:
    add_fact(sl, "leak", "sends", LEAK, private_to(sl.wheeler))
    doc = report(sl)
    assert LEAK not in repr(doc)
    assert doc.document.body == (BodyField(label="Found", value="Nothing yet"),)


def test_nothing_found_when_no_fact_visible(sl: Slice) -> None:
    assert report(sl).document.body == (BodyField(label="Found", value="Nothing yet"),)


def test_report_is_private_confidential_and_arrives_in_two_days(sl: Slice) -> None:
    doc = report(sl).document
    assert doc.kind is DocumentKind.REPORT
    assert doc.author == sl.entity("roosevelt")
    assert doc.issued == ON
    assert doc.arrives == ON + timedelta(days=2)
    assert doc.classification is Classification.CONFIDENTIAL
    assert doc.scope == private_to(sl.fdr)
    assert doc.title == f"Inquiry into {sl.state.entities[sl.entity('pound')].name}"


def test_only_issuer_seat_reads_the_report(sl: Slice) -> None:
    payload = report(sl)
    sl.add(payload, payload.document.scope)
    state = sl.state.model_copy(update={"in_world_date": payload.document.arrives})
    assert payload.document.doc_id in project(state, sl.fdr).documents
    assert payload.document.doc_id not in project(state, sl.wheeler).documents


def test_truth_points_at_the_document(sl: Slice) -> None:
    payload = report(sl)
    assert payload.truth.doc_id == payload.document.doc_id


def test_second_landing_is_skipped_once_folded(sl: Slice) -> None:
    payload = report(sl)
    sl.add(payload, payload.document.scope)
    assert inquire(sl) == []
