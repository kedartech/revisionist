"""Elections redraw a chamber (ELE).

The toy world of ``tests/test_posts.py`` with ``groups`` and ``elections`` on: Norra's
assembly holds the Greens (60 seats, baseline 55) and the Greys (40, baseline 30), and an
election on 1 May 1900, inside the season, redraws it. With ``office`` on the election names
the chancellery, which rests on the Greens: Ilse is told its day from the first wake, and
the post is put to the office question sitting that day.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.ids import OrderId
from revisionist.core.realism import actors, elections, groups, office
from revisionist.core.realism.resolvers.votes import bloc_tally
from revisionist.core.state import QuestionCause
from revisionist.core.visibility import PUBLIC
from revisionist.core.world_compile import WorldError
from revisionist.engine import campaign as cmp
from revisionist.engine.emit import Emitter
from tests.test_office_question import Sitting, seat_of, sitting
from tests.test_posts import CHANCELLERY, ILSE, KARA, NORRA, TOMAS

World = dict[str, Any]
DAY = date(1900, 5, 1)
BILL = "arm_merchant_ships"


def support(greens: int, greys: int, yeas: int = 48) -> Callable[[World], None]:
    """``groups`` and ``elections`` on; the Greens and Greys start at these supports, and
    their rows on the bill: ``yeas`` of the Greens' 60 for it, the Greys against."""

    def change(w: World) -> None:
        w["rules"] = sorted({*w["rules"], "groups", "elections"})
        for n in w["groups"]:
            for g in n["groups"]:
                if g["key"] == "greens":
                    g["start"] = greens
                    g["votes"] = {BILL: {"assembly": {"voting": 60, "yeas": yeas}}}
                if g["key"] == "greys":
                    g["start"] = greys
                    g["votes"] = {BILL: {"assembly": {"voting": 40, "yeas": 0}}}

    return change


def with_post(w: World) -> None:
    """``office`` on; the election names the chancellery, which rests on the Greens."""
    w["rules"] = sorted({*w["rules"], "office"})
    for e in w["elections"]:
        e["post"] = "norra_chancellery"
    for a in w["assets"]:
        if a["key"] == "norra_chancellery":
            a["rests_on"] = ["greens"]


def without_post(w: World) -> None:
    """The election as the toy lists it: no post named."""


def seats(g: Sitting) -> dict[str, int | None]:
    return {b.key: b.seats for b in groups.of(g.state, NORRA) if b.chamber == "assembly"}


def past_the_day(g: Sitting) -> None:
    while g.state.in_world_date is None or g.state.in_world_date < DAY:
        g.tick()


def bill(g: Sitting) -> tuple[int, int]:
    return bloc_tally(g.state, NORRA, "assembly", BILL, "assembly", OrderId("bill"))


# --- the redraw ----------------------------------------------------------------------


def test_the_chamber_is_redrawn_on_its_day_and_its_total_kept(tmp_path: Path) -> None:
    """Greens 25 points over their baseline want five seats more, Greys 20 under four
    fewer: 65 and 36, scaled back to 100 by largest remainders."""
    g = sitting(tmp_path, support(80, 10), without_post)
    assert seats(g) == {"greens": 60, "greys": 40}
    past_the_day(g)
    (drawn,) = g.payloads(ev.SeatsRedrawn)
    assert drawn.on == DAY and drawn.chamber == "assembly"
    assert drawn.seats == {"greens": 64, "greys": 36}
    assert seats(g) == drawn.seats
    assert sum(drawn.seats.values()) == 100


def test_redrawn_seats_are_public(tmp_path: Path) -> None:
    g = sitting(tmp_path, support(80, 10), without_post)
    past_the_day(g)
    (event,) = [e for e in g.store.read(g.state.campaign_id) if e.kind == "seats_redrawn"]
    assert event.scope == PUBLIC


def test_each_row_is_scaled_by_new_seats_over_old(tmp_path: Path) -> None:
    g = sitting(tmp_path, support(80, 10), without_post)
    past_the_day(g)
    greens = groups.group(g.state, NORRA, "greens")
    assert greens is not None
    row = greens.votes[BILL]["assembly"]
    assert (row.voting, row.yeas) == (64, 51)  # 60 * 64/60, 48 * 64/60 = 51.2


def test_a_bill_failing_before_the_election_passes_after(tmp_path: Path) -> None:
    g = sitting(tmp_path, support(95, 0, yeas=44), without_post)
    yeas, nays = bill(g)
    assert yeas <= nays
    past_the_day(g)
    yeas, nays = bill(g)
    assert yeas > nays


def test_at_the_baseline_nothing_moves(tmp_path: Path) -> None:
    g = sitting(tmp_path, support(55, 30), without_post)
    past_the_day(g)
    (drawn,) = g.payloads(ev.SeatsRedrawn)
    assert drawn.seats == {"greens": 60, "greys": 40}


def test_every_bloc_keeps_a_seat(tmp_path: Path) -> None:
    g = sitting(tmp_path, support(100, 0), without_post)
    past_the_day(g)
    (drawn,) = g.payloads(ev.SeatsRedrawn)
    assert min(drawn.seats.values()) >= 1 and sum(drawn.seats.values()) == 100


def test_redrawn_by_largest_remainders_first() -> None:
    """Three equal blocs of a chamber of ten with no support moved: 3, 3, 4 would change
    the total; the redraw keeps the seats each had."""

    class Bloc:
        def __init__(self, key: str, n: int) -> None:
            self.key, self.seats, self.baseline, self.chamber = key, n, 50, "c"

    class Fake:
        rules: frozenset[str] = frozenset()

    found = (Bloc("a", 3), Bloc("b", 3), Bloc("c", 4))
    mp = pytest.MonkeyPatch()
    mp.setattr(elections, "blocs", lambda *_: found)
    mp.setattr(groups, "support", lambda *_: 50)
    try:
        assert elections.redrawn(Fake(), NORRA, "c") == {"a": 3, "b": 3, "c": 4}  # type: ignore[arg-type]
    finally:
        mp.undo()


@pytest.mark.parametrize(
    ("drawn", "said"),
    [({"greens": 64, "greys": 37}, "total"), ({"greens": 100}, "other blocs")],
)
def test_the_fold_refuses_a_redraw_of_another_shape(
    tmp_path: Path, drawn: dict[str, int], said: str
) -> None:
    g = sitting(tmp_path, support(80, 10), without_post)
    g.add(ev.SeatsRedrawn(polity=NORRA, chamber="assembly", seats=drawn, on=DAY))
    with pytest.raises(FoldError, match=said):
        _ = g.state


def test_with_elections_off_no_chamber_is_redrawn(tmp_path: Path) -> None:
    def off(w: World) -> None:
        w["rules"] = [r for r in w["rules"] if r != "elections"]

    g = sitting(tmp_path, support(80, 10), without_post, off)
    past_the_day(g)
    assert g.payloads(ev.SeatsRedrawn) == []
    assert g.state.groups.elections == ()
    assert seats(g) == {"greens": 60, "greys": 40}


def test_the_world_is_checked(tmp_path: Path) -> None:
    def bad(w: World) -> None:
        w["elections"] = [
            {"nation": "norra", "chambers": ["senate"], "day": "1900-03-01", "post": "nowhere"}
        ]

    with pytest.raises(WorldError) as err:
        sitting(tmp_path, support(80, 10), bad)
    said = str(err.value)
    assert "no chamber senate" in said
    assert "not after the start date" in said
    assert "nowhere is not an office" in said


# --- the post ------------------------------------------------------------------------


def test_the_holders_seat_is_told_the_day_from_the_first_wake(tmp_path: Path) -> None:
    g = sitting(tmp_path, support(40, 30), with_post)
    g.tick()
    (opened,) = g.payloads(ev.OfficeQuestionOpened)
    q = opened.question
    assert q.cause is QuestionCause.ELECTION and q.sits == DAY and q.tick == 1
    (notice,) = [
        d
        for d in g.payloads(ev.DocumentIssued)
        if d.document.doc_id == office.notice_id(g.state, q.question_id)
    ]
    assert seat_of(g.state, ILSE) in notice.document.scope.known_by


def test_the_holder_is_removed_on_the_day_and_the_post_goes_to_his_successor(
    tmp_path: Path,
) -> None:
    g = sitting(tmp_path, support(40, 30), with_post)
    past_the_day(g)
    (opened,) = g.payloads(ev.OfficeQuestionOpened)
    q = opened.question
    assert q.cause is QuestionCause.ELECTION and q.post == CHANCELLERY and q.holder == ILSE
    assert q.sits == DAY and q.opened < date(1900, 4, 10)
    (made,) = g.decided()
    assert made.removed and made.on == DAY
    assert g.held(CHANCELLERY) == KARA


def test_the_holder_is_kept_when_his_base_holds(tmp_path: Path) -> None:
    g = sitting(tmp_path, support(60, 30), with_post)
    past_the_day(g)
    (made,) = g.decided()
    assert not made.removed and made.on == DAY
    assert g.held(CHANCELLERY) == ILSE
    assert len(g.payloads(ev.OfficeQuestionOpened)) == 1  # the successor's term is not put


def test_nobody_decides_an_election_question_by_choice(tmp_path: Path) -> None:
    g = sitting(tmp_path, support(40, 30), with_post)
    while not g.state.office_questions:
        g.tick()
    (q,) = g.state.office_questions.values()
    assert office.deciders(g.state, q) == ()
    with pytest.raises(ValueError):
        g.choose(ILSE, False)


def test_election_day_with_nobody_online(tmp_path: Path) -> None:
    """No seat of Norra is played: the chamber is redrawn and the holder removed all the
    same."""
    g = sitting(tmp_path, support(40, 30), with_post, claimed=(TOMAS,))
    past_the_day(g)
    assert len(g.payloads(ev.SeatsRedrawn)) == 1
    (made,) = g.decided()
    assert made.removed and made.on == DAY


def test_the_same_election_with_the_holder_run_by_code(tmp_path: Path) -> None:
    """Two games that differ in who plays Ilse: a person, or code. The same papers go to
    her seat on the same days and she is removed on the same day."""
    (tmp_path / "human").mkdir()
    (tmp_path / "code").mkdir()
    human = sitting(tmp_path / "human", support(40, 30), with_post)
    code = sitting(tmp_path / "code", support(40, 30), with_post, claimed=(KARA, TOMAS))
    em = Emitter(code.store, code.state, cmp.versions())
    em.commit([em.event(m, scope=PUBLIC) for m in actors.unseated(code.state, [ILSE])])
    assert code.state.seats[seat_of(code.state, ILSE)].controller.value == "ai"

    def papers(g: Sitting) -> list[tuple[str, date]]:
        mine = seat_of(g.state, ILSE)
        return [
            (d.document.title, d.document.issued)
            for d in g.payloads(ev.DocumentIssued)
            if mine in d.document.scope.known_by
        ]

    for g in (human, code):
        past_the_day(g)
    assert papers(human) == papers(code) != []
    assert [(d.on, d.removed) for d in human.decided()] == [
        (d.on, d.removed) for d in code.decided()
    ]
