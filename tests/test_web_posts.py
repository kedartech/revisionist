"""Posts as the seat sees them (PPR).

The ladder toy of ``tests/test_ladder.py``: Ilse holds the chancellery, which moves the
command (Kara's), the garrison and the staff post, and her card commands appointments;
the command's ladder runs garrison, then staff. Olav is a colonel with no post and no
seat. Tomas holds Sudland's seat and no post. Each seat's ``posts`` block, its check
before sending a move of post, and the line a pending change puts in what needs it.
"""

from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId
from revisionist.core.project import project
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.land import appointment
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.state import State
from revisionist.engine import notice, realism_tick
from revisionist.engine.web import agenda_api, locks_api, people
from tests.test_adjacency_moves import toy
from tests.test_ladder import GARRISON, STAFF, Ladders, ladders, no_ladders
from tests.test_posts import (
    CHANCELLERY,
    COMMAND,
    DAY,
    ILSE,
    KARA,
    OLAV,
    TOMAS,
    World,
    command_post,
    forms,
    seat,
    world,
)
from tests.test_realism_command import card, general, orders
from tests.test_territory_model import CAMPAIGN

LEVY = "General of the Norra Levy"
NORRHAVN = "Commandant of Norrhavn"
STAFF_POST = "Staff of the War Ministry"
SITTING = "only at the sitting of the office question"


def appoints(w: World) -> None:
    """Ilse's card commands appointments herself."""
    ilse = card(w, "ilse")
    ilse["authority"] = [*ilse["authority"], {"name": "posts_by_order", "effects": ["appointment"]}]


@pytest.fixture
def g(tmp_path: Path) -> Ladders:
    return Ladders(world(tmp_path, ladders, appoints))


def block(state: State, person: EntityId) -> dict[str, Any]:
    found = people.posts_block(state, seat(person))
    assert found is not None
    return dict(found)


def post_due(state: State, person: EntityId) -> list[agenda_api.DueMatter]:
    return [m for m in agenda_api.due_matters(state, seat(person)) if m.kind == "post"]


def landed(g: Ladders, n: int) -> None:
    """Close wake ``n``, the one the change was ordered in, open and close the next, and
    walk."""
    g.close(n)
    g.open(n + 1)
    g.close(n + 1)
    g.walk()


def rungs_full(g: Ladders) -> None:
    """Olav in the garrison and Tomas in the staff post, landed; wake 2 open."""
    g.open(0)
    g.order(OLAV, GARRISON)
    g.order(TOMAS, STAFF)
    landed(g, 0)
    g.open(2)


# --- rule 1: an appointment that lands moves the post, with its fact and news ---------


def test_an_appointment_to_a_post_with_no_ladder_moves_it_with_its_fact_and_news(
    tmp_path: Path,
) -> None:
    g = Ladders(world(tmp_path, no_ladders))
    out = g.order(OLAV, COMMAND)
    moved = [p for p in out if isinstance(p, ev.PostChanged)]
    assert [(p.post, p.holder, p.to) for p in moved] == [(COMMAND, KARA, OLAV)]
    assert any(isinstance(p, ev.FactAsserted) for p in out)
    assert any(isinstance(p, ev.NewsReported) for p in out)
    assert g.held(COMMAND) == OLAV


def test_a_dismissal_from_a_post_with_no_ladder_leaves_it_to_nobody(tmp_path: Path) -> None:
    g = Ladders(world(tmp_path, no_ladders))
    out = g.order(KARA, COMMAND, appoint=False)
    assert [(p.post, p.to) for p in out if isinstance(p, ev.PostChanged)] == [(COMMAND, None)]
    assert any(isinstance(p, ev.NewsReported) for p in out)
    assert g.held(COMMAND) is None


def test_a_dismissal_of_someone_who_does_not_hold_the_post_moves_nothing(
    tmp_path: Path,
) -> None:
    g = Ladders(world(tmp_path, no_ladders))
    out = g.order(OLAV, COMMAND, appoint=False)
    assert not [p for p in out if isinstance(p, ev.PostChanged)]
    assert g.held(COMMAND) == KARA


def test_with_posts_off_an_appointment_lands_as_today(tmp_path: Path) -> None:
    g = Ladders(toy(tmp_path, general, orders, command_post, no_ladders))
    effect = rx.Appointment(person=OLAV, office=LEVY)
    out, _ = appointment.land(PassWorld(g.state), effect, seat(ILSE), ILSE, DAY)
    assert [type(p).__name__ for p in out] == ["FactAsserted", "NewsReported"]


# --- rule 2: the seat's own post, ladder, movers and pending change -------------------


def test_the_seat_sees_its_post_its_ladder_and_who_may_move_it(g: Ladders) -> None:
    kara = block(g.state, KARA)
    assert kara["post"] == {"id": COMMAND, "name": LEVY}
    assert kara["ladder"] == [
        {"id": GARRISON, "name": NORRHAVN, "free": True},
        {"id": STAFF, "name": STAFF_POST, "free": True},
    ]
    assert kara["moved_by"] == ["Chancellor of Norra"]
    assert kara["pending"] == []


def test_with_posts_off_the_payload_has_no_posts_block(tmp_path: Path) -> None:
    g = Ladders(toy(tmp_path, general, orders, command_post, no_ladders))
    assert people.posts_block(g.state, seat(KARA)) is None


def test_a_pending_change_is_shown_to_the_person_moved_and_nobody_else(g: Ladders) -> None:
    """The fog test: the change Ilse orders on Kara reaches Kara's block and what needs
    her only, with the day it lands, until it lands."""
    g.open(0)
    g.order(KARA, COMMAND, appoint=False)
    state = g.state
    (line,) = block(state, KARA)["pending"]
    assert (line["post"], line["move"]) == (LEVY, "relieve")
    assert (line["lands"], line["wake"], line["rung"]) == (
        "at the close of the next wake",
        1,
        NORRHAVN,
    )
    for other in (ILSE, TOMAS):
        assert block(state, other)["pending"] == []
        assert post_due(state, other) == []
    (due,) = post_due(state, KARA)
    assert agenda_api.due_matters(state, seat(KARA))[0] == due  # at the head
    assert due.what == f"You are relieved of {LEVY}"
    assert due.due == "at the close of the next wake"
    assert due.subject == line["id"]
    told = notice.compose(state, seat(KARA), None, "Norra")[1]
    assert f"You are relieved of {LEVY}. Due at the close of the next wake." in told
    for other in (ILSE, TOMAS):
        assert LEVY not in notice.compose(state, seat(other), None, "Norra")[1]
    g.close(0)
    g.open(1)
    assert block(g.state, KARA)["pending"][0]["lands"] == "at the close of this wake"
    g.close(1)
    g.walk()
    after = block(g.state, KARA)
    assert after["pending"] == [] and after["post"] == {"id": GARRISON, "name": NORRHAVN}
    assert post_due(g.state, KARA) == []


def test_the_holder_an_appointment_puts_down_has_the_line_until_it_lands(g: Ladders) -> None:
    """Olav, whom no seat plays, is appointed to Kara's command: Kara's block and what
    needs her carry the fall a wake ahead, by the notice she holds; no other seat's do."""
    g.open(0)
    g.order(OLAV, COMMAND)
    state = g.state
    (line,) = block(state, KARA)["pending"]
    assert (line["post"], line["move"]) == (LEVY, "relieve")
    assert (line["lands"], line["wake"], line["rung"]) == (
        "at the close of the next wake",
        1,
        NORRHAVN,
    )
    assert line["id"] in project(state, seat(KARA)).documents
    for other in (ILSE, TOMAS):
        assert block(state, other)["pending"] == []
        assert post_due(state, other) == []
    (due,) = post_due(state, KARA)
    assert (due.what, due.due, due.subject) == (
        f"You are relieved of {LEVY}",
        "at the close of the next wake",
        line["id"],
    )
    told = notice.compose(state, seat(KARA), None, "Norra")[1]
    assert f"You are relieved of {LEVY}. Due at the close of the next wake." in told
    assert "Olav" not in str(block(state, KARA)["pending"]) + told
    landed(g, 0)
    assert block(g.state, KARA)["pending"] == [] and post_due(g.state, KARA) == []
    assert block(g.state, KARA)["post"] == {"id": GARRISON, "name": NORRHAVN}


def test_a_holder_who_left_the_post_before_it_lands_loses_the_line(g: Ladders) -> None:
    """Kara is relieved of the command, then told Olav's appointment to it puts her down.
    Her relief lands first: the appointment no longer puts her down, so its line goes
    while it still waits."""
    g.open(0)
    g.order(KARA, COMMAND, appoint=False)
    g.close(0)
    g.open(1)
    g.order(OLAV, COMMAND)
    assert [p["post"] for p in block(g.state, KARA)["pending"]] == [LEVY, LEVY]
    g.close(1)
    g.walk()
    assert g.held(COMMAND) is None and g.held(GARRISON) == KARA
    assert block(g.state, KARA)["pending"] == []
    assert post_due(g.state, KARA) == []


def test_a_holder_who_came_to_the_post_after_the_order_is_told_before_it_lands(
    g: Ladders,
) -> None:
    """Olav is appointed to the vacant garrison a wake after Kara is: nobody is put down
    when it is ordered. Kara takes the garrison first, so at its landing it would put her
    down untold: it is ordered afresh instead, she has the notice and the line, and it
    lands a wake later."""
    g.open(0)
    g.order(KARA, GARRISON)
    g.close(0)
    g.open(1)
    g.order(OLAV, GARRISON)
    g.close(1)
    g.walk()
    g.open(2)
    assert g.held(GARRISON) == KARA
    assert block(g.state, KARA)["pending"] == []  # no notice held, no line
    g.close(2)
    out = g.walk()
    assert g.held(GARRISON) == KARA
    (again,) = [p.move for p in out if isinstance(p, ev.PostMoveOrdered)]
    assert (again.person, again.wake, again.question) == (OLAV, 2, False)
    (paper,) = [p.document for p in out if isinstance(p, ev.DocumentIssued)]
    assert paper.scope.known_by == frozenset({seat(KARA)})
    assert paper.title == f"You are relieved of {NORRHAVN}"
    g.open(3)
    (line,) = block(g.state, KARA)["pending"]
    assert (line["post"], line["lands"], line["wake"]) == (
        NORRHAVN,
        "at the close of this wake",
        3,
    )
    g.close(3)
    g.walk()
    assert (g.held(GARRISON), g.held(STAFF)) == (OLAV, KARA)
    assert not g.state.post_moves


def test_a_notice_to_the_holder_before_tells_nothing_to_the_holder_now(g: Ladders) -> None:
    """Kara holds the command when both Tomas's and Olav's appointments to it are
    ordered, so she has both notices. Tomas's lands first: Olav's would now put Tomas
    down, and Kara's notice is not his, so it is ordered afresh with Tomas's."""
    g.open(0)
    g.order(TOMAS, COMMAND)
    g.close(0)
    g.open(1)
    g.order(OLAV, COMMAND)
    g.close(1)
    g.walk()
    g.open(2)
    assert (g.held(COMMAND), g.held(GARRISON)) == (TOMAS, KARA)
    assert block(g.state, KARA)["pending"] == []
    g.close(2)
    out = g.walk()
    assert g.held(COMMAND) == TOMAS
    (paper,) = [p.document for p in out if isinstance(p, ev.DocumentIssued)]
    assert paper.scope.known_by == frozenset({seat(TOMAS)})


def test_the_line_a_holder_is_shown_names_no_rung_from_the_appointee(g: Ladders) -> None:
    """Olav holds the garrison when Ilse appoints him to Kara's command, so the garrison
    he gives up is the rung Kara lands on. Kara is not told who comes, and a held rung on
    her line would name him: her line reads the first rung free in the open."""
    g.open(0)
    g.order(OLAV, GARRISON)
    landed(g, 0)
    g.open(2)
    g.order(OLAV, COMMAND)
    (line,) = block(g.state, KARA)["pending"]
    assert line["rung"] == STAFF_POST
    landed(g, 2)
    assert (g.held(COMMAND), g.held(GARRISON)) == (OLAV, KARA)


def test_a_change_that_would_take_the_last_authority_waits_for_the_sitting(
    g: Ladders,
) -> None:
    rungs_full(g)
    g.order(KARA, COMMAND, appoint=False)
    (line,) = block(g.state, KARA)["pending"]
    assert (line["lands"], line["wake"], line["rung"]) == (SITTING, None, None)
    (due,) = post_due(g.state, KARA)
    assert due.due == SITTING


def test_a_relieved_seat_is_not_sent_its_old_forms(g: Ladders) -> None:
    before = forms(g.state, KARA)
    g.open(0)
    g.order(KARA, COMMAND, appoint=False)
    assert forms(g.state, KARA) == before  # not yet landed
    landed(g, 0)
    assert block(g.state, KARA)["post"] == {"id": GARRISON, "name": NORRHAVN}
    assert before and not before & forms(g.state, KARA)


# --- rule 3: a seat with no post ------------------------------------------------------


def test_a_seat_with_no_post_gets_the_room_it_still_has(g: Ladders) -> None:
    tomas = block(g.state, TOMAS)
    assert tomas["post"] is None and tomas["ladder"] == [] and tomas["moved_by"] == []
    assert set(tomas["room"]) == {"inner_circle", "letters", "aims", "through"}
    assert "room" not in block(g.state, KARA)


def test_a_seat_that_loses_its_post_keeps_its_circle_and_who_it_acts_through(
    tmp_path: Path,
) -> None:
    g = Ladders(world(tmp_path, no_ladders))
    g.order(ILSE, CHANCELLERY, appoint=False)
    ilse = block(g.state, ILSE)
    assert ilse["post"] is None
    room = ilse["room"]
    assert room["inner_circle"] == ["Kara Lind"]
    assert [t["name"] for t in room["through"]] == ["Kara Lind"]


# --- rule 4: the moves a seat may make on others --------------------------------------


def test_the_mover_sees_each_move_open_with_the_rung_it_leads_to(g: Ladders) -> None:
    moves = block(g.state, ILSE)["moves"]
    relieve = [m for m in moves if m["move"] == "relieve" and m["post"] == COMMAND]
    assert relieve == [
        {
            "person": KARA,
            "name": "Kara Lind",
            "post": COMMAND,
            "office": LEVY,
            "move": "relieve",
            "down": "Kara Lind",
            "rung": NORRHAVN,
            "question": False,
        }
    ]
    appoint = next(
        m for m in moves if m["move"] == "appoint" and m["person"] == OLAV and m["post"] == COMMAND
    )
    assert (appoint["down"], appoint["rung"]) == ("Kara Lind", NORRHAVN)
    assert not [m for m in moves if m["person"] in (TOMAS, ILSE)]  # another polity; herself
    assert block(g.state, KARA)["moves"] == []


def test_a_seat_whose_card_commands_no_appointment_is_offered_no_move(
    tmp_path: Path,
) -> None:
    g = Ladders(world(tmp_path, ladders))
    assert block(g.state, ILSE)["moves"] == []


def test_a_person_down_the_ladder_is_offered_back_as_a_restore(g: Ladders) -> None:
    g.open(0)
    g.order(KARA, COMMAND, appoint=False)
    landed(g, 0)
    moves = block(g.state, ILSE)["moves"]
    (back,) = [m for m in moves if m["person"] == KARA and m["post"] == COMMAND]
    assert (back["move"], back["down"], back["rung"]) == ("restore", None, None)


def test_a_move_that_would_take_the_last_authority_is_marked(g: Ladders) -> None:
    rungs_full(g)
    moves = block(g.state, ILSE)["moves"]
    (relieve,) = [m for m in moves if m["move"] == "relieve" and m["post"] == COMMAND]
    assert relieve["question"] is True and relieve["rung"] is None


# --- rule 5: the check before sending, equal to what filing then does ------------------


def _filed(g: Ladders, by: EntityId, ask: Ask) -> object:
    return realism_tick.commit_order(g.store, CAMPAIGN, seat(by), (ask,))


def test_the_check_answers_allowed_and_filing_sends_it(g: Ladders) -> None:
    checked = locks_api.check_move(g.state, seat(ILSE), KARA, COMMAND, "relieve")
    assert checked == locks_api.ALLOWED
    ask = locks_api.move_ask(g.state, seat(ILSE), KARA, COMMAND, "relieve")
    assert ask.ask == f"Relieve Kara Lind of {LEVY}"
    filed = _filed(g, ILSE, ask)
    assert isinstance(filed, rx.RoutedOrder)


def test_the_check_refuses_what_filing_refuses_in_the_same_words(g: Ladders) -> None:
    checked = locks_api.check_move(g.state, seat(KARA), OLAV, COMMAND, "appoint")
    assert checked["check"] == "beyond"
    ask = Ask(ask=f"Appoint Olav Holm: {LEVY}", effect=rx.Appointment(person=OLAV, office=LEVY))
    with pytest.raises(ValueError) as refused:
        _filed(g, KARA, ask)
    assert checked["reason"] == str(refused.value)


def test_the_check_says_the_move_would_open_the_office_question(g: Ladders) -> None:
    rungs_full(g)
    checked = locks_api.check_move(g.state, seat(ILSE), KARA, COMMAND, "relieve")
    assert checked == {
        "check": "question",
        "who": None,
        "reason": "It would open the office question.",
    }
    moved = [
        p.move for p in g.order(KARA, COMMAND, appoint=False) if isinstance(p, ev.PostMoveOrdered)
    ]
    assert [m.question for m in moved] == [True]  # what landing the filed order then does


def test_a_written_reading_of_the_move_gets_the_same_answer(g: Ladders) -> None:
    rungs_full(g)
    ask = Ask(ask="relieve Kara", effect=rx.Appointment(person=KARA, office=LEVY, appoint=False))
    assert locks_api.check_asks(g.state, seat(ILSE), (ask,))["check"] == "question"
    assert locks_api.check_asks(g.state, seat(TOMAS), (ask,))["check"] == "beyond"


@pytest.mark.parametrize(
    ("person", "post", "move", "reason"),
    [
        (KARA, "nowhere", "relieve", locks_api.NO_POST),
        ("nobody", COMMAND, "appoint", locks_api.NO_PERSON),
        (KARA, COMMAND, "promote", locks_api.NO_POST),
    ],
    ids=["no such post", "no such person", "no such move"],
)
def test_an_unknown_post_person_or_move_is_refused_in_words(
    g: Ladders, person: str, post: str, move: str, reason: str
) -> None:
    checked = locks_api.check_move(g.state, seat(ILSE), person, post, move)
    assert checked == {"check": "beyond", "who": None, "reason": reason}


def test_no_payload_says_who_is_human(g: Ladders) -> None:
    for person in (ILSE, KARA, TOMAS):
        assert "human" not in str(block(g.state, person)).lower()
