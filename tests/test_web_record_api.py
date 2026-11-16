"""The record block for the room (Train 2 unit S1): the seat's orders and its latest wake.

Spec tests written with the contract; the unit makes them pass without editing them.
"""

import json
import re
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core import record
from revisionist.core.ids import OrderId
from revisionist.core.project import project
from revisionist.core.realism import effect as rx
from revisionist.core.realism.apply import report_doc_id
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    BodyField,
    Document,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.pipeline import StepAction, StepOutcome
from revisionist.core.realism.pipelines import reply_doc_id
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine import realism_tick, wake
from revisionist.engine.store import MemoryStore
from revisionist.engine.web import snapshot
from revisionist.engine.web.realism_api import RecordOrder, RecordWake
from revisionist.engine.web.record_api import record_block
from tests.test_engine_v2_apply import FILED, executed, land
from tests.test_engine_v2_contract import CAMPAIGN as SLICE_CAMPAIGN
from tests.test_engine_v2_contract import Slice
from tests.test_engine_v2_wake import CAMPAIGN, T0, Table, play
from tests.test_web_results import _influence, _land_reports

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
WORDED = re.compile(r"^\d{1,2} [A-Z][a-z]+ \d{4}$")


def _filed(t: Table) -> None:
    wake.open_wake(t.store, CAMPAIGN, T0)
    realism_tick.commit_order(t.store, CAMPAIGN, t.fdr, [t.shoot_on_sight()])
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)


def test_an_order_is_listed_in_the_seats_own_words_with_worded_days() -> None:
    t = Table(MemoryStore())
    _filed(t)
    block = record_block(t.state, list(t.store.read(CAMPAIGN)), t.fdr)
    (entry,) = block["orders"]
    assert set(entry) == set(RecordOrder.__annotations__)
    assert entry["asked"] == "shoot on sight in the western Atlantic"
    assert entry["filed"] == "1 September 1941" and entry["settled"] is None
    assert entry["moving"] is True and entry["wake"] == 0
    assert entry["to"] == t.state.entities[t.entity("stark")].name
    (ledger,) = record.build(t.state, list(t.store.read(CAMPAIGN)), t.fdr).orders
    assert entry["id"] == sha256(ledger.key.encode()).hexdigest()[:12]
    assert entry["track"] is None


def test_a_moving_routed_part_says_when_its_answer_is_due() -> None:
    t = Table(MemoryStore())
    _filed(t)
    (entry,) = record_block(t.state, list(t.store.read(CAMPAIGN)), t.fdr)["orders"]
    assert entry["due"] is not None and WORDED.match(entry["due"])


def test_the_latest_wake_page_counts_papers_and_names_entries_by_token(tmp_path: Path) -> None:
    t = Table(MemoryStore())
    _filed(t)
    first = record_block(t.state, list(t.store.read(CAMPAIGN)), t.fdr)
    assert first["wake"] is not None and first["wake"]["number"] == 0
    assert first["wake"]["filed"] == [first["orders"][0]["id"]]
    play(t, tmp_path, T0 + timedelta(hours=13))
    after = record_block(t.state, list(t.store.read(CAMPAIGN)), t.fdr)
    page = after["wake"]
    assert page is not None and set(page) == set(RecordWake.__annotations__)
    assert page["number"] == 1 and WORDED.match(page["opened"])
    assert page["days_passed"] > 0 and page["papers"] > 0
    (entry,) = after["orders"]
    assert page["settled"] == [entry["id"]] and page["filed"] == []
    assert entry["moving"] is False and entry["settled"] is not None
    assert WORDED.match(entry["settled"])


def test_no_wake_page_before_a_wake_opens() -> None:
    t = Table(MemoryStore())
    block = record_block(t.state, list(t.store.read(CAMPAIGN)), t.fdr)
    assert block == {"orders": [], "wake": None}


def test_a_standard_form_points_at_its_tracker_entry() -> None:
    t = Table(MemoryStore())
    wake.open_wake(t.store, CAMPAIGN, T0)
    card = t.state.cards[t.entity("roosevelt")]
    lever = card.levers[0]
    given = {
        p.name: (p.choices[0] if p.choices else str(p.lo) if p.lo is not None else "word")
        for p in lever.params
    }
    order = realism_tick.file_order(t.store, CAMPAIGN, t.fdr, lever.name, given)
    (entry,) = record_block(t.state, list(t.store.read(CAMPAIGN)), t.fdr)["orders"]
    assert entry["track"] == order.order_id
    assert entry["holder"] is not None and entry["due"] is None


def test_a_decided_approach_carries_the_papers_answer() -> None:
    sl = Slice()
    order = _influence(sl, 1, ask="drop the filibuster")
    private = "estimator reckons Wheeler is bluffing"
    sl.add(
        ev.EffectsEstimated(order_id=order.order_id, part=0, reason="r", rationale=private),
        private_to(sl.fdr),
    )
    sl.add(
        ev.InfluenceDecided(order_id=order.order_id, part=0, on=date(1941, 9, 14), accepted=False),
        private_to(sl.fdr),
    )
    _land_reports(sl, date(1941, 9, 14))
    block = record_block(sl.state, sl.events, sl.fdr)
    (entry,) = block["orders"]
    assert entry["asked"] == "drop the filibuster" and entry["said"]
    assert entry["moving"] is False
    assert private not in json.dumps(block)


def test_newest_filed_first() -> None:
    sl = Slice()
    _influence(sl, 1, ask="first")
    _influence(sl, 2, ask="second")
    rows = record_block(sl.state, sl.events, sl.fdr)["orders"]
    assert [r["asked"] for r in rows] == ["second", "first"]


def test_another_seat_shares_no_entry_and_no_id_leaves() -> None:
    t = Table(MemoryStore())
    _filed(t)
    state, log = t.state, list(t.store.read(CAMPAIGN))
    assert t.winston is not None
    mine = record_block(state, log, t.fdr)
    theirs = record_block(state, log, t.winston)
    assert not {o["id"] for o in mine["orders"]} & {o["id"] for o in theirs["orders"]}
    text = json.dumps(mine)
    assert "shoot on sight" not in json.dumps(theirs)
    ids = [str(o) for o in state.routed] + list(state.entities)
    assert not [i for i in ids if i in text]
    assert not ISO.search(text)
    assert snapshot.checked(state, t.fdr, {"record": mine}) == {"record": mine}


RECEIPT_KEYS = {"word", "day", "doc"}


def _carried_out(
    fidelity: rx.Fidelity | None, *, refusal: str = "", reason: str = "", arrived: bool = True
) -> tuple[Slice, record.OrderEntry, RecordOrder]:
    """A shoot-on-sight order carried out as given, its report landed, and the seat's one
    ledger line for it."""
    sl = Slice()
    order = sl.shoot_on_sight(reason=reason)
    executed(sl, order, fidelity, refusal)
    land(sl, order)
    if arrived:
        sl.add(ev.DateAdvanced(to=FILED + timedelta(days=30)))
    (line,) = record_block(sl.state, sl.events, sl.fdr)["orders"]
    (entry,) = record.build(sl.state, sl.events, sl.fdr).orders
    return sl, entry, line


def test_an_order_carried_out_in_full_has_a_receipt_that_links_its_paper() -> None:
    sl, entry, line = _carried_out(rx.Fidelity.FULL)
    order_id, _, part = entry.key.rpartition(".")
    report = report_doc_id(SLICE_CAMPAIGN, OrderId(order_id), int(part))
    arrived = project(sl.state, sl.fdr).documents[report].arrives
    assert line["receipt"] == {
        "word": "Carried out in full",
        "day": f"{arrived.day} {arrived:%B %Y}",
        "doc": report,
    }
    assert line["moving"] is False


@pytest.mark.parametrize("fidelity", [rx.Fidelity.LOOSE, rx.Fidelity.SLOW, rx.Fidelity.PARTIAL])
def test_an_order_carried_out_less_than_fully_has_no_receipt(fidelity: rx.Fidelity) -> None:
    assert _carried_out(fidelity)[2]["receipt"] is None


def test_an_account_or_a_refusal_leaves_the_paper_whole() -> None:
    assert _carried_out(rx.Fidelity.FULL, reason="The fleet sailed short.")[2]["receipt"] is None
    assert _carried_out(None, refusal="loyalty -3")[2]["receipt"] is None


def test_a_report_that_has_not_arrived_gives_no_receipt() -> None:
    assert _carried_out(rx.Fidelity.FULL, arrived=False)[2]["receipt"] is None


def test_a_decided_approach_has_no_receipt() -> None:
    sl = Slice()
    order = _influence(sl, 1, ask="drop the filibuster")
    sl.add(
        ev.EffectsEstimated(order_id=order.order_id, part=0, reason="r", rationale="private"),
        private_to(sl.fdr),
    )
    sl.add(
        ev.InfluenceDecided(order_id=order.order_id, part=0, on=date(1941, 9, 14), accepted=True),
        private_to(sl.fdr),
    )
    _land_reports(sl, date(1941, 9, 14))
    (entry,) = record_block(sl.state, sl.events, sl.fdr)["orders"]
    assert entry["said"] and entry["receipt"] is None


def test_a_receipt_names_no_id_and_no_numeric_date_outside_its_paper_link() -> None:
    sl, _, line = _carried_out(rx.Fidelity.FULL)
    receipt = line["receipt"]
    assert isinstance(receipt, dict) and set(receipt) == RECEIPT_KEYS
    assert not ISO.search(f"{receipt['word']} {receipt['day']}")
    block = record_block(sl.state, sl.events, sl.fdr)
    assert snapshot.checked(sl.state, sl.fdr, {"record": block}) == {"record": block}


def _with_replies(t: Table, *said: tuple[str, tuple[BodyField, ...]]) -> tuple[State, OrderId]:
    """A standard form filed, then one reply paper per ``said`` in the order's step outcomes'
    numbering, each dated a day after the last."""
    wake.open_wake(t.store, CAMPAIGN, T0)
    lever = t.state.cards[t.entity("roosevelt")].levers[0]
    given = {
        p.name: (p.choices[0] if p.choices else str(p.lo) if p.lo is not None else "word")
        for p in lever.params
    }
    order = realism_tick.file_order(t.store, CAMPAIGN, t.fdr, lever.name, given)
    state = t.state
    docs = dict(state.documents)
    on = state.in_world_date or T0.date()
    outcomes = tuple(
        StepOutcome(step=n, person=t.entity("stark"), action=StepAction.PASS, on=on)
        for n in range(len(said))
    )
    held = state.orders[order.order_id].model_copy(update={"outcomes": outcomes})
    for n, (done, extra) in enumerate(said):
        doc_id = reply_doc_id(state.campaign_id, order.order_id, n)
        view = DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.MEMO,
            author=t.entity("stark"),
            issued=on,
            arrives=on,
            channel=ChannelKind.IN_PERSON,
            title="On your order: a form",
            body=(BodyField(label="What was done", value=done), *extra),
            scope=private_to(t.fdr),
        )
        docs[doc_id] = Document(view=view, truth=DocumentTruth(doc_id=doc_id))
    orders = {**state.orders, order.order_id: held}
    return state.model_copy(update={"documents": docs, "orders": orders}), order.order_id


def _form_line(t: Table, state: State) -> RecordOrder:
    (line,) = record_block(state, list(t.store.read(CAMPAIGN)), t.fdr)["orders"]
    return line


def test_a_form_passed_on_unchanged_has_a_receipt_with_its_reply() -> None:
    t = Table(MemoryStore())
    state, order = _with_replies(t, ("passed it on", ()))
    line = _form_line(t, state)
    assert line["receipt"] is not None
    assert line["receipt"]["word"] == "Passed on"
    assert line["receipt"]["doc"] == reply_doc_id(state.campaign_id, order, 0)


def test_a_form_pressed_forward_is_worded_as_pressed_forward() -> None:
    t = Table(MemoryStore())
    state, _ = _with_replies(t, ("pressed it forward", ()))
    receipt = _form_line(t, state)["receipt"]
    assert receipt is not None and receipt["word"] == "Pressed forward"


def test_a_form_held_amended_or_finished_has_no_receipt() -> None:
    for done, extra in (
        ("held it", ()),
        ("passed it on", (BodyField(label="Changed: Rate", value=3),)),
        ("passed it on", (BodyField(label="Outcome", value="enacted"),)),
    ):
        t = Table(MemoryStore())
        state, _ = _with_replies(t, (done, extra))
        assert _form_line(t, state)["receipt"] is None


def test_one_news_reply_among_the_replies_takes_the_receipt_away() -> None:
    t = Table(MemoryStore())
    state, _ = _with_replies(t, ("held it", ()), ("passed it on", ()))
    assert _form_line(t, state)["receipt"] is None


def test_the_latest_of_several_receipts_gives_the_line() -> None:
    t = Table(MemoryStore())
    state, order = _with_replies(t, ("passed it on", ()), ("pressed it forward", ()))
    receipt = _form_line(t, state)["receipt"]
    assert receipt is not None and receipt["word"] == "Pressed forward"
    assert receipt["doc"] == reply_doc_id(state.campaign_id, order, 1)
