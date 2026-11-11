"""Offered options marked once filed (Train 2 unit S2): ``AgendaOption.taken``.

Spec tests written with the contract; the unit makes them pass without editing them.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

from revisionist.core.ids import SeatId
from revisionist.core.realism.agenda import PlayStyle
from revisionist.engine import options, wake
from revisionist.engine.store import MemoryStore
from revisionist.engine.web import agenda_api
from tests.test_engine_v2_wake import CAMPAIGN, T0, Table, play


def _offered(style: PlayStyle) -> Table:
    t = Table(MemoryStore())
    options.set_style(t.store, CAMPAIGN, t.fdr, style)
    if t.winston is not None:
        options.set_style(t.store, CAMPAIGN, t.winston, style)
    wake.open_wake(t.store, CAMPAIGN, T0)
    wake.offer_all(t.store, CAMPAIGN, None)
    return t


def _block(t: Table, seat: SeatId) -> Any:
    return agenda_api.agenda(t.state, seat, list(t.store.read(CAMPAIGN)))


def _all(block: Any) -> list[Any]:
    out: list[Any] = [o for i in block["items"] for o in i["options"] + i["plan"]]
    return out + list(block["initiative"])


def test_nothing_is_taken_before_a_pick_and_the_pick_is_after() -> None:
    t = _offered(PlayStyle.BEGINNER)
    before = _all(_block(t, t.fdr))
    assert before and not any(o["taken"] for o in before)
    chosen = before[0]
    assert not agenda_api.pick_option(t.store, CAMPAIGN, t.fdr, chosen["pick"])["refused"]
    after = _all(_block(t, t.fdr))
    assert [o["label"] for o in after if o["taken"]] == [
        o["label"] for o in after if o["label"] == chosen["label"]
    ]
    assert any(o["taken"] for o in after) and not all(o["taken"] for o in after)


def test_a_guided_plans_steps_share_one_value() -> None:
    t = _offered(PlayStyle.GUIDED)
    (item, *_) = [i for i in _block(t, t.fdr)["items"] if i["plan"]]
    assert {s["taken"] for s in item["plan"]} == {False}
    agenda_api.pick_option(t.store, CAMPAIGN, t.fdr, item["plan"][0]["pick"])
    (after, *_) = [i for i in _block(t, t.fdr)["items"] if i["plan"]]
    assert {s["taken"] for s in after["plan"]} == {True}


def test_another_seats_pick_does_not_mark_this_seats_options() -> None:
    t = _offered(PlayStyle.BEGINNER)
    assert t.winston is not None
    theirs = _all(_block(t, t.winston))
    agenda_api.pick_option(t.store, CAMPAIGN, t.winston, theirs[0]["pick"])
    assert not any(o["taken"] for o in _all(_block(t, t.fdr)))


def test_the_next_wakes_fresh_offer_starts_untaken(tmp_path: Path) -> None:
    t = _offered(PlayStyle.BEGINNER)
    chosen = _all(_block(t, t.fdr))[0]
    agenda_api.pick_option(t.store, CAMPAIGN, t.fdr, chosen["pick"])
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)
    play(t, tmp_path, T0 + timedelta(hours=13))
    wake.offer_all(t.store, CAMPAIGN, None)
    fresh = _all(_block(t, t.fdr))
    assert fresh and not any(o["taken"] for o in fresh)
