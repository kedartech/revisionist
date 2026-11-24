"""Blocs turn on the leader: the warning, then the question (TUR).

The toy office question world of ``tests/test_office_question.py``: Kara holds the
command of the levy, which rests on the Greens and whose holder Ilse removes. Here the
Greens stand at 20 from the start, under the line of 30, and stay there unless a test
moves them. Each world day the walk reads the Greens; on the 14th day running under the
line Kara's seat gets one warning, and on the 21st the office question opens with the
cause "the base turned". A day at or above the line clears the count.
"""

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.realism import actors, groups, office
from revisionist.core.state import QuestionCause
from revisionist.core.visibility import PUBLIC
from revisionist.engine import campaign as cmp
from revisionist.engine.emit import Emitter
from tests.test_office_question import BY_PERSON, Sitting, office_on, seat_of, sitting
from tests.test_posts import COMMAND, ILSE, KARA, NORRA, TOMAS
from tests.test_territory_model import CAMPAIGN

World = dict[str, Any]
WARNING = "The base turns"


def greens_at(support: int) -> Callable[[World], None]:
    """``groups`` on; the Greens start at ``support`` and drift toward it."""

    def change(w: World) -> None:
        w["rules"] = sorted({*w["rules"], "groups"})
        for n in w["groups"]:
            for g in n["groups"]:
                if g["key"] == "greens":
                    g["start"] = support
                    g["baseline"] = support

    return change


def low(tmp: Path, **kw: Any) -> Sitting:
    return sitting(tmp, office_on(BY_PERSON), greens_at(20), **kw)


def start(g: Sitting) -> date:
    day = g.state.in_world_date
    assert day is not None
    return day


def warnings(g: Sitting) -> list[tuple[ev.DocumentIssued, frozenset[SeatId]]]:
    return [
        (e.payload, e.scope.known_by)
        for e in g.store.read(CAMPAIGN)
        if isinstance(e.payload, ev.DocumentIssued) and e.payload.document.title.startswith(WARNING)
    ]


def opened(g: Sitting) -> list[ev.OfficeQuestionOpened]:
    return g.payloads(ev.OfficeQuestionOpened)


def move_greens(g: Sitting, to: int) -> None:
    """The Greens set to ``to`` on the in-world date, as a group move would."""
    state = g.state
    was = groups.support(state, NORRA, "greens")
    assert was is not None and state.in_world_date is not None
    em = Emitter(g.store, state, cmp.versions())
    moved = ev.GroupMoved(
        polity=NORRA,
        group="greens",
        support=to,
        change=to - was,
        cause=groups.Cause.WRITING,
        on=state.in_world_date,
    )
    em.commit([em.event(moved, scope=PUBLIC)])


def papers(g: Sitting) -> list[tuple[str, str, frozenset[EntityId]]]:
    """The warnings and the questions, their dates and who was told, by person."""
    state = g.state
    rows: list[tuple[str, str, frozenset[EntityId]]] = []
    for doc, told in warnings(g):
        people = frozenset(state.seats[s].embodies for s in told if s in state.seats)
        rows.append(("warning", doc.document.issued.isoformat(), people))
    for q in opened(g):
        rows.append(("question", q.question.opened.isoformat(), frozenset()))
    return rows


# --- the warning on day 14, the question on day 21 ----------------------------------


def test_state_keeps_the_day_the_base_fell_from_the_start(tmp_path: Path) -> None:
    g = low(tmp_path)
    assert g.state.office_base_fell == {COMMAND: start(g)}


def test_the_holders_seat_is_warned_on_the_fourteenth_day_naming_the_groups(
    tmp_path: Path,
) -> None:
    g = low(tmp_path)
    first = start(g)
    g.tick()  # each tick walks fourteen days: to day 15
    ((doc, told),) = warnings(g)
    assert doc.document.issued == first + timedelta(days=office.WARN_DAYS - 1)
    assert told == frozenset({seat_of(g.state, KARA)})
    named = {f.label: f.value for f in doc.document.body}
    assert named["Groups"] == "The Greens"
    assert opened(g) == []


def test_the_question_opens_on_the_twenty_first_day_after_the_warning(tmp_path: Path) -> None:
    """Mutant: the question opened with no warning."""
    g = low(tmp_path)
    first = start(g)
    g.tick()
    g.tick()  # to day 29
    ((doc, _),) = warnings(g)
    (q,) = opened(g)
    assert q.question.cause is QuestionCause.BASE
    assert q.question.opened == first + timedelta(days=office.TURN_DAYS - 1)
    assert doc.document.issued < q.question.opened
    assert q.question.holder == KARA


def test_one_good_day_clears_the_count(tmp_path: Path) -> None:
    """Mutant: the count not cleared. The Greens stand at 40 from day 1 to day 14, then
    fall back on day 15: the count starts again there, so no warning comes on day 14 and
    the next comes on day 28, with no question by day 29."""
    g = low(tmp_path)
    first = start(g)
    move_greens(g, 40)
    assert g.state.office_base_fell == {}
    g.tick()  # to day 15
    assert warnings(g) == [] and opened(g) == []
    move_greens(g, 20)
    fell = first + timedelta(days=14)
    assert g.state.office_base_fell == {COMMAND: fell}
    g.tick()  # to day 29
    ((doc, _),) = warnings(g)
    assert doc.document.issued == fell + timedelta(days=office.WARN_DAYS - 1)
    assert opened(g) == []


def test_a_base_at_the_line_is_not_under_it(tmp_path: Path) -> None:
    g = sitting(tmp_path, office_on(BY_PERSON), greens_at(office.TURN_LINE))
    g.tick()
    g.tick()
    assert g.state.office_base_fell == {}
    assert warnings(g) == [] and opened(g) == []


def test_the_same_script_with_the_holder_run_by_code(tmp_path: Path) -> None:
    """Two games that differ in who plays Kara: a person, or code. The same warning goes
    to Kara's seat on the same day and the question opens on the same day."""
    (tmp_path / "human").mkdir()
    (tmp_path / "code").mkdir()
    human = low(tmp_path / "human")
    code = low(tmp_path / "code", claimed=(ILSE, TOMAS))
    em = Emitter(code.store, code.state, cmp.versions())
    em.commit([em.event(m, scope=PUBLIC) for m in actors.unseated(code.state, [KARA])])
    assert code.state.seats[seat_of(code.state, KARA)].controller.value == "ai"
    for g in (human, code):
        g.tick()
        g.tick()
    assert papers(human) == papers(code)
    assert [r[0] for r in papers(human)] == ["warning", "question"]
    assert papers(human)[0][2] == frozenset({KARA})


def test_the_warning_is_sealed_from_every_other_seat(tmp_path: Path) -> None:
    g = low(tmp_path)
    g.tick()
    ((_, told),) = warnings(g)
    assert seat_of(g.state, ILSE) not in told and seat_of(g.state, TOMAS) not in told


# --- gated by office -----------------------------------------------------------------


def test_with_office_off_nothing_is_counted(tmp_path: Path) -> None:
    def off(w: World) -> None:
        for a in w["assets"]:
            if a["key"] == "levy_command":
                a["moved_by"] = ["norra_chancellery"]

    g = sitting(tmp_path, off, greens_at(20))
    g.tick()
    g.tick()
    assert g.state.office_base_fell == {}
    assert warnings(g) == [] and opened(g) == []
