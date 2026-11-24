"""The aide's note of what waits (ABN).

With ``aide_note`` on, the catch-up reply a returning seat reads carries ``waits`` beside
its pages' note of what the aide did: one line, with its day, for each thing the seat left
alone. Held orders of its own not asked for; asks and matters put before it; a bloc that
would take an offer on a measure of its nation on its way; a promise due; an incident it
must answer; a sitting on its office; a change pending on its post; its own aim while it is
still open. Each line is read from the state for the seat's own view when the note is read,
so nothing is stored, and another seat's held orders, promises or aim never reach it.

Each kind is tested on the world its own item tests it in, with ``aide_note`` switched on
in the state the note reads.
"""

from pathlib import Path

from revisionist.core.ids import SeatId
from revisionist.core.state import Rule, State
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import agenda_api, catchup_api, locks_api
from revisionist.engine.web.realism_api import WaitLine
from tests import test_offers as to
from tests.async_table import AsyncTable
from tests.test_due_matters import held_at_bram, opened, requested
from tests.test_notice import table  # noqa: F401
from tests.test_territory_model import CAMPAIGN


def noted(state: State) -> State:
    """``state`` with ``aide_note`` on."""
    return state.model_copy(update={"rules": state.rules | {Rule.AIDE_NOTE}})


def note(state: State, seat: SeatId) -> list[WaitLine]:
    found = catchup_api.waits(noted(state), seat)
    assert found is not None
    return found


def of(state: State, seat: SeatId, kind: str) -> list[WaitLine]:
    return [line for line in note(state, seat) if line["kind"] == kind]


# --- the switch, and the reply ------------------------------------------------------


def _locked(tmp: Path) -> MemoryStore:
    from tests.test_realism_locks import played

    return played(tmp)


def test_with_aide_note_off_there_is_no_note(tmp_path: Path) -> None:
    from tests.test_realism_locks import KARA, file, seat

    store = _locked(tmp_path)
    file(store, "isle")
    state = opened(load_state(store, CAMPAIGN))
    assert Rule.AIDE_NOTE not in state.rules
    assert catchup_api.waits(state, seat(KARA)) is None
    assert "waits" not in catchup_api.reply(state, list(store.read(CAMPAIGN)), seat(KARA), {})


def test_the_catchup_reply_carries_the_note_beside_the_pages(tmp_path: Path) -> None:
    from tests.test_realism_locks import KARA, file, seat

    store = _locked(tmp_path)
    file(store, "isle")
    state = noted(opened(load_state(store, CAMPAIGN)))
    got = catchup_api.reply(state, list(store.read(CAMPAIGN)), seat(KARA), {})
    assert set(got) == {"first", "last", "pages", "waits"}
    assert got["waits"] == catchup_api.waits(state, seat(KARA))
    assert [line["kind"] for line in got["waits"]] == ["held"]


# --- one test per kind of line ------------------------------------------------------


def test_a_held_order_not_asked_for_is_a_line_with_the_day_it_was_held(tmp_path: Path) -> None:
    from tests.test_realism_locks import DAY, ILSE, KARA, ask, file, seat

    store = _locked(tmp_path)
    order = file(store, "isle")
    state = load_state(store, CAMPAIGN)
    shown = locks_api.block(state, seat(KARA))
    assert shown is not None
    (held,) = shown["held"]
    assert of(state, seat(KARA), "held") == [
        WaitLine(kind="held", what=held["words"], who=held["who"], day=DAY.isoformat())
    ]
    assert of(state, seat(ILSE), "held") == []  # the note is the seat's own
    ask(store, order.order_id)
    assert of(load_state(store, CAMPAIGN), seat(KARA), "held") == []  # asked for: it waits on Ilse


def test_an_ask_put_before_the_seat_is_a_line(tmp_path: Path) -> None:
    from tests.test_realism_locks import ILSE, KARA, ask, file, seat

    store = _locked(tmp_path)
    order = file(store, "isle")
    ask(store, order.order_id)
    state = load_state(store, CAMPAIGN)
    (due,) = [m for m in agenda_api.due_matters(state, seat(ILSE)) if m.kind == "ask"]
    assert of(state, seat(ILSE), "ask") == [
        WaitLine(kind="ask", what=due.what, who="Kara Lind", day=locks_api.ASK_DUE)
    ]
    assert of(state, seat(KARA), "ask") == []


def test_a_request_put_before_the_seat_is_a_line(table: AsyncTable) -> None:  # noqa: F811
    words, _ = requested(table)
    (line,) = of(table.state, table.churchill, "request")
    (item,) = agenda_api.requests(table.state, table.churchill)
    assert line == WaitLine(
        kind="request", what=item["text"], who=item["issuer"], day=item["deadline"]
    )
    assert words in line["what"]
    assert note(table.state, table.fdr) == []


def test_a_decision_held_at_the_seat_is_a_line() -> None:
    t = held_at_bram()
    (item,) = agenda_api.held_steps(t.state, t.bram)
    assert of(t.state, t.bram, "decision") == [
        WaitLine(kind="decision", what=item["text"], who=item["issuer"], day=item["deadline"])
    ]
    assert of(t.state, t.ada, "decision") == []


def test_a_bloc_that_would_take_an_offer_on_a_measure_on_its_way_is_a_line(
    tmp_path: Path,
) -> None:
    from tests.test_realism_locks import seat

    g = to.game(tmp_path)
    assert of(g.state, seat(to.ILSE), "bloc") == []  # no bill on its way
    to.bill(g)
    line = WaitLine(
        kind="bloc",
        what="The Greens would take an offer for its votes on The Barge Act",
        who=None,
        day=catchup_api.BEFORE_THE_VOTE,
    )
    assert of(g.state, seat(to.ILSE), "bloc") == [line]
    assert of(g.state, seat(to.KARA), "bloc") == [line]  # the nation's measure
    assert of(g.state, seat(to.TOMAS), "bloc") == []
    to.offer(g, to.KARA)
    g.walk(to.day(1), to.day(1))
    assert of(g.state, seat(to.ILSE), "bloc") == []  # an offer holds the bloc


def test_a_promise_due_is_a_line_of_the_seat_that_made_it(tmp_path: Path) -> None:
    from tests.test_realism_locks import seat

    g = to.game(tmp_path)
    to.bill(g)
    to.offer(g, to.ILSE)
    g.walk(to.day(1), to.VOTE)
    (line,) = of(g.state, seat(to.ILSE), "promise")
    assert line["day"] == to.DUE.isoformat() and line["who"] is None
    assert line["what"].startswith("Your promise to The Greens: ")
    assert of(g.state, seat(to.KARA), "promise") == []
    assert of(g.state, seat(to.TOMAS), "promise") == []


def test_an_incident_awaiting_its_answer_is_a_line_of_the_superior(tmp_path: Path) -> None:
    from tests.test_realism_locks import ILSE, KARA, seat
    from tests.test_web_locks import _incident

    store, incident = _incident(tmp_path)
    state = load_state(store, CAMPAIGN)
    assert of(state, seat(ILSE), "incident") == [
        WaitLine(
            kind="incident",
            what=locks_api.SENT_WITHOUT_LEAVE,
            who="Kara Lind",
            day=incident.due.isoformat(),
        )
    ]
    assert of(state, seat(KARA), "incident") == []


def _questioned(tmp: Path):  # type: ignore[no-untyped-def]
    from tests.test_blocs_turn import greens_at
    from tests.test_office_question import BY_PERSON, office_on
    from tests.test_web_office import built

    g = built(tmp, office_on(BY_PERSON), greens_at(60))
    g.ask()
    return g


def test_an_office_question_open_on_the_seats_post_is_a_line(tmp_path: Path) -> None:
    from tests.test_office_question import seat_of
    from tests.test_posts import ILSE, KARA, TOMAS

    g = _questioned(tmp_path)
    (made,) = g.state.office_questions.values()
    for who in (KARA, ILSE):  # its holder, and the one who decides
        (line,) = of(g.state, seat_of(g.state, who), "office")
        assert (line["day"], line["who"]) == (made.sits.isoformat(), None)
    assert of(g.state, seat_of(g.state, TOMAS), "office") == []


def test_a_sitting_on_the_seats_office_is_a_line(tmp_path: Path) -> None:
    from tests.test_office_question import seat_of
    from tests.test_posts import KARA, TOMAS

    g = _questioned(tmp_path)
    (made,) = g.state.office_questions.values()
    near = g.state.model_copy(update={"tick": made.tick + 1})
    (line,) = of(near, seat_of(near, KARA), "sitting")
    assert line["what"].startswith("The office question on ")
    assert line["day"] == made.sits.isoformat()
    assert of(near, seat_of(near, KARA), "office") == []
    assert of(near, seat_of(near, TOMAS), "sitting") == []


def test_a_change_pending_on_the_seats_post_is_a_line(tmp_path: Path) -> None:
    from tests.test_ladder import Ladders, ladders
    from tests.test_posts import COMMAND, ILSE, KARA, TOMAS, seat, world
    from tests.test_web_posts import LEVY, appoints

    g = Ladders(world(tmp_path, ladders, appoints))
    g.open(0)
    g.order(KARA, COMMAND, appoint=False)
    (line,) = of(g.state, seat(KARA), "post")
    assert (line["what"], line["day"]) == (
        f"You are relieved of {LEVY}",
        "at the close of the next wake",
    )
    for other in (ILSE, TOMAS):
        assert of(g.state, seat(other), "post") == []


def test_the_own_aim_still_open_is_a_line(tmp_path: Path) -> None:
    from tests import test_own_aim as oa
    from tests.test_realism_aims import ILSE, TOMAS, seat_of

    g = oa.game(tmp_path, oa.setup(), people=(ILSE, TOMAS))
    card = g.state.cards[ILSE]
    (line,) = of(g.state, seat_of(g.state, ILSE), "aim")
    assert line == WaitLine(
        kind="aim",
        what=catchup_api.OWN_AIM_OPEN.format(aim=card.aims[2]),
        who=None,
        day=agenda_api.AT_CLOSE,
    )
    assert of(g.state, seat_of(g.state, TOMAS), "aim") == []  # no replaceable aim
    shut = g.state.model_copy(update={"aim_shut": g.state.aim_shut | {ILSE}})
    assert of(shut, seat_of(shut, ILSE), "aim") == []


# --- fog ----------------------------------------------------------------------------


def test_twin_worlds_differing_in_another_seats_held_order_give_the_same_note(
    tmp_path: Path,
) -> None:
    """Kara's held order is hers: Olaf's note, and Ilse's before she is asked, read the
    same whether Kara has one or not."""
    from tests.test_realism_locks import ILSE, OLAF, file, seat

    quiet = _locked(tmp_path / "quiet")
    held = _locked(tmp_path / "held")
    file(held, "isle")
    for person in (OLAF, ILSE):
        assert note(load_state(held, CAMPAIGN), seat(person)) == note(
            load_state(quiet, CAMPAIGN), seat(person)
        )


def test_twin_worlds_differing_in_another_nations_measure_give_the_same_note(
    tmp_path: Path,
) -> None:
    """Norra's bill, offer and promise never reach a seat of Sudland."""
    from tests.test_realism_locks import seat

    for name in ("quiet", "busy"):
        (tmp_path / name).mkdir()
    quiet = to.game(tmp_path / "quiet")
    busy = to.game(tmp_path / "busy")
    to.bill(busy)
    to.offer(busy, to.ILSE)
    for g in (quiet, busy):
        g.walk(to.day(1), to.VOTE)
    assert of(busy.state, seat(to.ILSE), "promise") != []
    assert note(busy.state, seat(to.TOMAS)) == note(quiet.state, seat(to.TOMAS))
