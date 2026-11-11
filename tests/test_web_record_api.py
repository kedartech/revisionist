"""The record block for the room (Train 2 unit S1): the seat's orders and its latest wake.

Spec tests written with the contract; the unit makes them pass without editing them.
"""

import json
import re
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path

from revisionist.core import events as ev
from revisionist.core import record
from revisionist.core.visibility import private_to
from revisionist.engine import realism_tick, wake
from revisionist.engine.store import MemoryStore
from revisionist.engine.web import snapshot
from revisionist.engine.web.realism_api import RecordOrder, RecordWake
from revisionist.engine.web.record_api import record_block
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
