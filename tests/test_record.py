"""The game record: wake, order and ledger pages built from the log, one seat's edition."""

from datetime import date, timedelta
from pathlib import Path

from revisionist.core import events as ev
from revisionist.core import record
from revisionist.core.canary import scan_text
from revisionist.core.project import project
from revisionist.core.realism.agenda import PlayStyle
from revisionist.core.visibility import private_to
from revisionist.engine import options, realism_tick, wake
from revisionist.engine.store import MemoryStore
from tests.test_engine_v2_contract import Slice, _with_covert_fact
from tests.test_engine_v2_wake import CAMPAIGN, T0, Table, play

START = date(1941, 9, 1)


def _record(t: Table, seat: str) -> record.Record:
    return record.build(t.state, list(t.store.read(CAMPAIGN)), getattr(t, seat))


def test_the_ledger_holds_each_order_in_the_seats_own_words(tmp_path: Path) -> None:
    t = Table(MemoryStore())
    wake.open_wake(t.store, CAMPAIGN, T0)
    realism_tick.commit_order(t.store, CAMPAIGN, t.fdr, [t.shoot_on_sight()])
    wake.commit(
        t.store, CAMPAIGN, t.fdr, T0
    )  # a seat that has not committed is played on its opening matter
    (entry,) = _record(t, "fdr").orders
    assert entry.asked == "shoot on sight in the western Atlantic"
    assert entry.to == t.state.entities[t.entity("stark")].name
    assert (entry.wake, entry.filed, entry.moving, entry.settled) == (0, START, True, None)

    play(t, tmp_path, T0 + timedelta(hours=13))
    (after,) = _record(t, "fdr").orders
    assert after.key == entry.key and not after.moving
    assert after.settled is not None and after.settled > START
    assert after.status != entry.status


def test_a_wake_page_says_what_arrived_what_was_filed_and_what_settled(tmp_path: Path) -> None:
    t = Table(MemoryStore())
    wake.open_wake(t.store, CAMPAIGN, T0)
    realism_tick.commit_order(t.store, CAMPAIGN, t.fdr, [t.shoot_on_sight()])
    wake.commit(
        t.store, CAMPAIGN, t.fdr, T0
    )  # a seat that has not committed is played on its opening matter
    play(t, tmp_path, T0 + timedelta(hours=13))
    rec = _record(t, "fdr")
    (entry,) = rec.orders
    first, second = rec.wakes
    assert (first.number, first.opened, first.days_passed) == (0, START, 0)
    assert first.filed == (entry.key,) and first.settled == ()
    assert second.number == 1 and second.opened == t.state.in_world_date
    assert second.days_passed == (second.opened - START).days > 0
    assert second.filed == () and second.settled == (entry.key,)
    seen = {p.title for w in rec.wakes for p in w.papers}
    assert seen == {d.title for d in project(t.state, t.fdr).documents.values()}
    assert all(first.opened < p.arrived <= second.opened for p in second.papers)


def test_a_standard_form_is_on_the_ledger_with_who_holds_it() -> None:
    t = Table(MemoryStore())
    wake.open_wake(t.store, CAMPAIGN, T0)
    card = t.state.cards[t.entity("roosevelt")]
    lever = card.levers[0]
    given = {
        p.name: (p.choices[0] if p.choices else str(p.lo) if p.lo is not None else "word")
        for p in lever.params
    }
    order = realism_tick.file_order(t.store, CAMPAIGN, t.fdr, lever.name, given)
    (entry,) = _record(t, "fdr").orders
    holder = t.state.pipelines[order.pipeline].steps[0].person
    assert entry.asked.startswith(lever.label or lever.name)
    assert entry.holder == t.state.entities[holder].name and entry.moving
    assert "_" not in entry.asked


def test_an_offer_is_marked_taken_once_its_order_is_filed() -> None:
    t = Table(MemoryStore())
    options.set_style(t.store, CAMPAIGN, t.fdr, PlayStyle.BEGINNER)
    wake.open_wake(t.store, CAMPAIGN, T0)
    assert wake.offer_all(t.store, CAMPAIGN, None) == 1
    (page,) = _record(t, "fdr").wakes
    assert len(page.offered) >= 3 and not any(o.taken for o in page.offered)
    offered = [
        e.payload for e in t.store.read(CAMPAIGN) if isinstance(e.payload, ev.OptionsOffered)
    ]
    chosen = offered[-1].offers[-1].options[1]
    realism_tick.commit_order(t.store, CAMPAIGN, t.fdr, chosen.asks)
    (page,) = _record(t, "fdr").wakes
    # the opening matter and the Greer crisis each list the option, and one order takes both
    assert [o.label for o in page.offered if o.taken] == [chosen.label] * len(offered[-1].offers)


def test_a_seats_edition_holds_nothing_of_another_seats() -> None:
    sl = Slice()
    _with_covert_fact(sl)
    marker = "MARKER-ONLY-ROOSEVELT-TYPED-THIS"
    order = sl.shoot_on_sight(ask=marker)
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    state = sl.state
    mine = record.build(state, sl.events, sl.fdr)
    theirs = record.build(state, sl.events, sl.wheeler)
    assert [o.asked for o in mine.orders] == [marker]
    assert theirs.orders == () and marker not in theirs.model_dump_json()
    for seat in (sl.fdr, sl.wheeler):
        text = record.build(state, sl.events, seat).model_dump_json()
        assert scan_text(state, seat, text) == []
