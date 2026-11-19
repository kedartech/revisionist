"""Every due matter reaches the wake notice (DMN).

``agenda_api.due_matters(state, seat)`` is the one list of what waits on a seat: the
requests another seat has put to it, the decisions it holds on another seat's order, and
each kind registered in ``agenda_api.DUE_KINDS`` (here THL's capital warning). The wake
notice composes its list from it. A matter reached by two paths is listed once, and no
line shows a sealed choice or any mark of the aide.

The capital cases use THL's toy (``tests/test_holders.py``): Norra's levy stands on the
Sudland Coast, which holds Sudland's capital, and the coast is marked to fall at the
close of the next wake; Tomas holds Sudland, Ilse holds Norra.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import SeatId
from revisionist.core.realism import advance, holders
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.pipeline import StepAction
from revisionist.core.state import State, Wake
from revisionist.engine import notice, realism_tick, wake
from revisionist.engine.web import agenda_api
from revisionist.engine.web.agenda_api import AT_CLOSE, DueMatter
from tests.async_table import AsyncTable
from tests.test_adjacency_moves import entity, seat
from tests.test_engine_v2_wake import CAMPAIGN as SLICE
from tests.test_holders import COAST, Wakes, to_capital
from tests.test_notice import GAME, table  # noqa: F401
from tests.test_realism_human_due import Toy
from tests.test_territory_model import CAMPAIGN

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
TOMAS = seat("tomas")
ILSE = seat("ilse")


def opened(state: State) -> State:
    """``state`` with a wake open, for a pure ``compose`` where no wake was opened."""
    if state.wake is not None:
        return state
    return state.model_copy(update={"wake": Wake(number=1, deadline=NOW + timedelta(hours=24))})


def text(state: State, seat_id: SeatId) -> str:
    return notice.compose(opened(state), seat_id, None, GAME)[1]


def marked(tmp: Path) -> Wakes:
    """The toy run one close: the coast is marked to fall, Tomas holds its paper."""
    w = to_capital(tmp)
    w.close()
    return w


def requested(t: AsyncTable) -> tuple[str, str]:
    """Roosevelt's request has reached Churchill; returns its words and agenda id."""
    t.open_play()
    churchill = t.entity("churchill")
    words = "Ask the Prime Minister to take fifty old destroyers"
    gift = rx.Allocate(recipient=churchill, what="old destroyers", amount=50, unit="ships")
    t.file(t.fdr, Ask(ask=words, target=churchill, effect=gift))
    for _ in range(6):
        t.close()
        today = t.state.in_world_date
        assert today is not None
        if advance.awaiting(t.state, t.churchill, today):
            break
    (item,) = agenda_api.requests(t.state, t.churchill)
    return words, item["id"]


def held_at_bram() -> Toy:
    """Ada's levy waits at Bram's decision step, and the day has reached it."""
    t = Toy()
    t.run(t.arrival)
    t.add(ev.DateAdvanced(to=t.arrival))
    return t


# --- Rule 1: one projection: today's requests plus the registered kinds ----------------


def test_the_requests_before_a_seat_are_due_matters(table: AsyncTable) -> None:  # noqa: F811
    words, item_id = requested(table)
    (matter,) = agenda_api.due_matters(table.state, table.churchill)
    assert (matter.kind, matter.subject) == ("request", item_id)
    (item,) = agenda_api.requests(table.state, table.churchill)
    assert matter == DueMatter(
        "request", item["id"], item["text"], item["issuer"], item["deadline"]
    )
    assert words in matter.what
    assert agenda_api.due_matters(table.state, table.fdr) == []


def test_a_decision_held_on_another_seats_order_is_a_due_matter() -> None:
    t = held_at_bram()
    (item,) = agenda_api.held_steps(t.state, t.bram)
    assert agenda_api.due_matters(t.state, t.bram) == [
        DueMatter("decision", item["id"], item["text"], item["issuer"], item["deadline"])
    ]
    assert agenda_api.due_matters(t.state, t.ada) == []


def test_a_capital_marked_to_fall_is_due_to_its_holding_seat_only(tmp_path: Path) -> None:
    w = marked(tmp_path)
    state = w.state
    ((area, on),) = holders.falling(state, TOMAS)
    paper = holders.paper_id(state, area, on, TOMAS)
    assert agenda_api.due_matters(state, TOMAS) == [
        DueMatter(
            "capital", paper, "The Sudland Coast will fall at the next close", "Sudland", AT_CLOSE
        )
    ]
    assert agenda_api.due_matters(state, ILSE) == []


def test_a_capital_warning_needs_the_seats_own_paper(tmp_path: Path) -> None:
    """The mark is engine only: a seat that does not hold the warning paper is told
    nothing, however the mark stands."""
    state = marked(tmp_path).state
    paper = holders.paper_id(state, entity(COAST), holders.falling(state, TOMAS)[0][1], TOMAS)
    docs = {k: v for k, v in state.documents.items() if k != paper}
    assert agenda_api.due_matters(state.model_copy(update={"documents": docs}), TOMAS) == []


def test_every_kind_reads_only_state_and_seat(tmp_path: Path) -> None:
    state = marked(tmp_path).state
    assert list(agenda_api.DUE_KINDS) == ["request", "decision", "capital"]
    for kind in agenda_api.DUE_KINDS.values():
        assert kind(state, TOMAS) == kind(state, TOMAS)


# --- Rule 2: the notice composes its list from due_matters ------------------------------


def test_the_notice_lists_the_capital_warning(tmp_path: Path) -> None:
    state = marked(tmp_path).state
    tomas = text(state, TOMAS)
    assert "Before you:" in tomas
    assert (
        "- Sudland: The Sudland Coast will fall at the next close. Due at this wake's close."
        in (tomas.splitlines())
    )
    ilse = text(state, ILSE)
    assert "Sudland Coast" not in ilse
    assert "Nothing from another player waits on you." in ilse


def test_the_notice_lists_a_held_decision() -> None:
    t = held_at_bram()
    (item,) = agenda_api.held_steps(t.state, t.bram)
    line = f"- {item['issuer']}: {item['text']}. Due {item['deadline']}."
    assert line in text(t.state, t.bram).splitlines()
    assert "Before you:" not in text(t.state, t.ada)


def test_the_notice_lists_every_registered_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A kind a later item registers reaches the notice with no change to the notice."""
    state = marked(tmp_path).state
    extra = DueMatter("battle", "b1", "The battle at the ford awaits your decision", None, "today")
    monkeypatch.setitem(agenda_api.DUE_KINDS, "battle", lambda _s, _seat: [extra])
    assert "- The battle at the ford awaits your decision. Due today." in text(state, ILSE)


# --- Rule 3: THL's capital warning is registered here -----------------------------------


def test_the_capital_warning_is_a_registered_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = marked(tmp_path).state
    monkeypatch.delitem(agenda_api.DUE_KINDS, "capital")
    assert agenda_api.due_matters(state, TOMAS) == []
    assert "Sudland Coast" not in text(state, TOMAS)


# --- Rule 4: a matter reached by two paths is listed once -------------------------------


def test_a_matter_reached_two_ways_is_listed_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = marked(tmp_path).state
    (once,) = agenda_api.due_matters(state, TOMAS)
    again = agenda_api.DUE_KINDS["capital"]
    monkeypatch.setitem(agenda_api.DUE_KINDS, "capital again", again)
    assert agenda_api.due_matters(state, TOMAS) == [once]
    lines = text(state, TOMAS).splitlines()
    assert sum("Sudland Coast" in line for line in lines) == 1


def test_two_matters_of_one_kind_with_different_subjects_are_both_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = marked(tmp_path).state
    two = [DueMatter("battle", s, f"Battle {s}", None, "today") for s in ("b1", "b2")]
    monkeypatch.setitem(agenda_api.DUE_KINDS, "battle", lambda _s, _seat: two)
    assert agenda_api.due_matters(state, ILSE) == two


# --- Rule 5: no sealed choice and no mark of the aide -----------------------------------


def test_an_answer_given_before_its_due_day_is_not_in_the_notice(
    table: AsyncTable,  # noqa: F811
) -> None:
    words, item_id = requested(table)
    before = text(table.state, table.churchill)
    reply = agenda_api.answer(table.store, SLICE, table.churchill, item_id, True)
    assert not reply["refused"]
    (item,) = agenda_api.requests(table.state, table.churchill)
    assert item["cause"] is not None  # the agenda shows the seat its own answer
    after = text(table.state, table.churchill)
    assert after == before
    assert words in after and "agree" not in after.lower()


def test_a_decision_chosen_before_its_due_day_is_not_in_the_notice() -> None:
    t = held_at_bram()
    before = text(t.state, t.bram)
    t.add(ev.StepChosen(order_id=t.order_id, step=1, action=StepAction.REFUSE))
    (item,) = agenda_api.held_steps(t.state, t.bram)
    assert item["cause"] is not None
    after = text(t.state, t.bram)
    assert after == before
    assert "refuse" not in after.lower() and "chosen" not in after.lower()


def test_no_line_names_the_aide(tmp_path: Path) -> None:
    state = marked(tmp_path).state
    for m in agenda_api.due_matters(state, TOMAS):
        for said in (m.what, m.issuer or "", m.due):
            assert "aide" not in said.lower()


# --- Accept: the capital notice with the other seat present and away --------------------


def _tomas_notice(tmp: Path, ilse_present: bool) -> tuple[str, str]:
    """Tomas's notice for the wake after the coast was marked, and the holders after its
    close, with Ilse at the table (her papers read and her Done pressed) or away."""
    w = marked(tmp)
    wake.open_wake(w.store, CAMPAIGN, NOW)
    if ilse_present:
        state = w.state
        for d in state.documents.values():
            if d.view.scope.visible_to(ILSE):
                realism_tick.mark_read(w.store, CAMPAIGN, ILSE, d.view.doc_id)
        assert wake.commit(w.store, CAMPAIGN, ILSE, NOW)
    said = notice.compose(w.state, TOMAS, None, GAME)[1]
    w.close()
    return said, repr(sorted(w.state.holders.items()))


def test_the_capital_notice_reads_the_same_with_the_other_seat_present_or_away(
    tmp_path: Path,
) -> None:
    (tmp_path / "present").mkdir()
    (tmp_path / "away").mkdir()
    present = _tomas_notice(tmp_path / "present", ilse_present=True)
    away = _tomas_notice(tmp_path / "away", ilse_present=False)
    assert present == away
    said = present[0]
    assert "Due at this wake's close." in said
    print(said)
