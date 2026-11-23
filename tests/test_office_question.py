"""The office question as a formal sitting (OFQ).

The toy world of ``tests/test_posts.py`` (``posts`` on: Ilse holds the chancellery, Kara
the command of the levy, her successor Olav a colonel with no seat; Tomas holds Sudland)
with ``office`` on. The command has no ladder, so dismissing Kara would take her last
authority: that is never done on Ilse's order, only at the office question's sitting,
dated ten days ahead and told that day to every seat of Norra, whoever plays it.
"""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core import sealing
from revisionist.core.fold import FoldError, state_hash
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.realism import actors, office
from revisionist.core.resolution import TickStage
from revisionist.core.state import QuestionCause, State
from revisionist.core.visibility import PUBLIC, Visibility
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick, session_zero
from revisionist.engine.emit import Emitter
from revisionist.engine.store import MemoryStore, load_state
from tests.test_ladder import Ladders
from tests.test_posts import CHANCELLERY, COMMAND, ILSE, KARA, NORRA, OLAV, TOMAS, seat, world
from tests.test_territory_model import CAMPAIGN

World = dict[str, Any]
PAPER = "The office question"


def office_on(removed_by: dict[str, Any] | None) -> Callable[[World], None]:
    """``office`` on; the chancellery moves the command, which has no ladder, and its
    holder is removed as ``removed_by`` says."""

    def change(w: World) -> None:
        w["rules"] = [*w["rules"], "office"]
        for a in w["assets"]:
            if a["key"] == "levy_command":
                a["moved_by"] = ["norra_chancellery"]
                if removed_by is not None:
                    a["removed_by"] = removed_by
                a["rests_on"] = ["greens"]

    return change


def office_off(w: World) -> None:
    """The command moved by the chancellery, no ladder, ``office`` off: LDR's rule."""
    for a in w["assets"]:
        if a["key"] == "levy_command":
            a["moved_by"] = ["norra_chancellery"]


BY_PERSON = {"by": "person", "person": "ilse"}
BY_COUNCIL = {"by": "council", "members": ["ilse", "olav", "tomas"], "needed": 2}


def green_row(yeas: int) -> Callable[[World], None]:
    """The Greens' row on the office question in the assembly."""

    def change(w: World) -> None:
        w["rules"] = sorted({*w["rules"], "groups"})
        row = {"assembly": {"voting": 50, "yeas": yeas}}
        for n in w["groups"]:
            for g in n["groups"]:
                if g["key"] == "greens":
                    g["votes"] = {**g.get("votes", {}), office.MEASURE: row}

    return change


class Sitting(Ladders):
    """The toy game, played by real ticks of seven world days."""

    def __init__(self, w: WorldFile, claimed: tuple[EntityId, ...] = (ILSE, KARA, TOMAS)) -> None:
        self.store = MemoryStore()
        self.store.append_all(compile_world(w, CAMPAIGN, cmp.versions()))
        for person in claimed:
            session_zero.claim(self.store, CAMPAIGN, seat(person), self.state.entities[person].name)
        realism_tick.open_play(self.store, CAMPAIGN)

    def ask(self, cause: QuestionCause = QuestionCause.INCIDENT) -> ev.OfficeQuestionOpened:
        return realism_tick.open_office_question(self.store, CAMPAIGN, COMMAND, cause)

    def choose(self, person: EntityId, remove: bool) -> None:
        q = next(iter(self.state.office_questions))
        realism_tick.choose_office(self.store, CAMPAIGN, seat_of(self.state, person), q, remove)

    def payloads[T](self, kind: type[T]) -> list[T]:
        return [e.payload for e in self.store.read(CAMPAIGN) if isinstance(e.payload, kind)]

    def decided(self) -> list[ev.OfficeQuestionDecided]:
        return self.payloads(ev.OfficeQuestionDecided)

    def until_decided(self, ticks: int = 4) -> ev.OfficeQuestionDecided:
        for _ in range(ticks):
            self.tick()
            if self.decided():
                (made,) = self.decided()
                return made
        raise AssertionError("the question was never decided")


def seat_of(state: State, person: EntityId) -> SeatId:
    return next(s.seat_id for s in state.seats.values() if s.embodies == person)


def sitting(tmp: Path, *changes: Callable[[World], None], **kw: Any) -> Sitting:
    return Sitting(world(tmp, *changes), **kw)


# --- each way of removal -------------------------------------------------------------


def test_removed_by_one_persons_choice_and_the_post_goes_to_its_successor(tmp_path: Path) -> None:
    g = sitting(tmp_path, office_on(BY_PERSON))
    opened = g.ask().question
    assert opened.sits == opened.opened + timedelta(days=office.SITTING_DAYS)
    g.choose(ILSE, True)
    made = g.until_decided()
    assert made.removed and made.on >= opened.sits and made.rests_until is None
    assert g.held(COMMAND) == OLAV  # removed by post_changed; the walk gives it on
    assert g.state.office_questions == {}


def test_kept_by_a_council_and_no_second_question_inside_the_rest(tmp_path: Path) -> None:
    """Ilse chooses removal; Tomas files keep; Olav, with no seat, has his card decide on
    the day, and regards Kara well enough to keep her: one of three, two needed."""
    g = sitting(tmp_path, office_on(BY_COUNCIL))
    g.ask()
    g.choose(ILSE, True)
    g.choose(TOMAS, False)
    made = g.until_decided()
    assert not made.removed and g.held(COMMAND) == KARA
    assert made.rests_until == made.on + timedelta(days=office.REST_DAYS)
    with pytest.raises(ValueError, match="was kept"):
        g.ask()


def test_removed_by_a_council_when_enough_members_choose_so(tmp_path: Path) -> None:
    g = sitting(tmp_path, office_on(BY_COUNCIL))
    g.ask()
    g.choose(ILSE, True)
    g.choose(TOMAS, True)
    assert g.until_decided().removed


def test_a_later_choice_replaces_the_first(tmp_path: Path) -> None:
    g = sitting(tmp_path, office_on(BY_PERSON))
    g.ask()
    g.choose(ILSE, True)
    g.choose(ILSE, False)
    assert not g.until_decided().removed


@pytest.mark.parametrize(("yeas", "removed"), [(45, True), (10, False)], ids=["carried", "lost"])
def test_removed_by_a_bodys_vote(tmp_path: Path, yeas: int, removed: bool) -> None:
    way = {"by": "vote", "chamber": "assembly"}
    g = sitting(tmp_path, office_on(way), green_row(yeas))
    g.ask()
    assert g.until_decided().removed is removed


def test_removed_at_the_end_of_a_term_which_opens_its_own_question(tmp_path: Path) -> None:
    (tmp_path / "probe").mkdir()
    start = Sitting(world(tmp_path / "probe")).state.in_world_date
    assert start is not None
    (tmp_path / "w").mkdir()
    ends = (start + timedelta(days=3)).isoformat()
    g = sitting(tmp_path / "w", office_on({"by": "term", "ends": ends}))
    g.tick()
    (opened,) = g.payloads(ev.OfficeQuestionOpened)
    assert opened.question.cause is QuestionCause.TERM
    assert opened.question.opened.isoformat() == ends
    assert g.until_decided().removed


def test_a_post_whose_holder_is_never_removed_faces_no_question(tmp_path: Path) -> None:
    for way in ({"by": "never"}, None):
        (tmp_path / str(way)).mkdir()
        g = sitting(tmp_path / str(way), office_on(way))
        with pytest.raises(ValueError, match="nobody can put"):
            g.ask()


# --- the sitting, on its day only --------------------------------------------------


def test_the_sitting_is_dated_ahead_and_never_decided_before_its_day(tmp_path: Path) -> None:
    """Mutant: decided before its day. The engine waits; the fold refuses one written
    early."""
    g = sitting(tmp_path, office_on(BY_PERSON))
    q = g.ask().question
    g.choose(ILSE, True)
    early = ev.OfficeQuestionDecided(
        question_id=q.question_id, post=COMMAND, holder=KARA, on=q.opened, removed=True
    )
    g.add(early)
    with pytest.raises(FoldError, match="before its day"):
        _ = g.state


def test_it_sits_only_after_two_wakes_the_seats_could_act_in(tmp_path: Path) -> None:
    """Told before this wake's orders, the seats act in this wake and the next: it sits
    in the second wake's walk, never in this one's, even were its day to fall there."""
    g = sitting(tmp_path, office_on(BY_PERSON))
    q = g.ask().question
    assert not office.sits(g.state, q, q.sits)
    g.choose(ILSE, True)
    g.tick()
    first_walk_ended = g.state.in_world_date
    assert first_walk_ended is not None and first_walk_ended >= q.sits  # its day passed
    assert g.decided() == []
    assert office.sits(g.state, q, q.sits)
    g.tick()
    assert [d.on for d in g.decided()] == [first_walk_ended + timedelta(days=1)]


def test_the_holder_plays_on_and_it_is_decided_with_him_absent(tmp_path: Path) -> None:
    """Nobody plays Kara: no seat of hers is told and none chooses, and the sitting is
    decided on its day all the same; while it runs she keeps the post and every move."""
    g = sitting(tmp_path, office_on(BY_PERSON), claimed=(ILSE, TOMAS))
    q = g.ask().question
    g.choose(ILSE, True)
    g.tick()
    assert g.held(COMMAND) == KARA and q.question_id in g.state.office_questions
    assert g.until_decided().removed


# --- sealed, told the same, whoever plays ---------------------------------------------


def test_a_members_choice_is_sealed_from_every_other_seat(tmp_path: Path) -> None:
    """Mutant: a sealed choice shown. It is sealed to the seat that chose, never fed,
    and the decision names no one's choice."""
    g = sitting(tmp_path, office_on(BY_COUNCIL))
    g.ask()
    g.choose(ILSE, True)
    (filed,) = [e for e in g.store.read(CAMPAIGN) if isinstance(e.payload, ev.OfficeChoiceFiled)]
    assert filed.scope.visibility is not Visibility.PUBLIC
    assert filed.scope.known_by == frozenset({seat(ILSE)})
    assert "office_choice_filed" in catchup.NEVER
    made = g.until_decided()
    assert set(type(made).model_fields) == {
        "kind",
        "question_id",
        "post",
        "holder",
        "on",
        "removed",
        "rests_until",
    }
    (told,) = [e for e in g.store.read(CAMPAIGN) if isinstance(e.payload, ev.OfficeQuestionDecided)]
    assert told.scope == PUBLIC


def test_the_new_kinds_are_fed_or_never_fed() -> None:
    assert {"office_question_opened", "office_question_decided"} <= catchup.FEED_KINDS
    assert "office_choice_filed" in catchup.NEVER


def _told(g: Sitting) -> dict[EntityId, list[tuple[str, str, str]]]:
    """Each person's papers on the question and their dates, by the seat that holds him."""
    state = g.state
    out: dict[EntityId, list[tuple[str, str, str]]] = {}
    for e in g.store.read(CAMPAIGN):
        p = e.payload
        if isinstance(p, ev.OfficeQuestionOpened):
            row = ("opened", p.question.opened.isoformat(), p.question.sits.isoformat())
        elif isinstance(p, ev.DocumentIssued) and p.document.title.startswith(
            "The office question"
        ):
            row = ("paper", p.document.issued.isoformat(), p.document.arrives.isoformat())
        else:
            continue
        for s in e.scope.known_by:
            if s in state.seats:
                out.setdefault(state.seats[s].embodies, []).append(row)
    return out


def test_twin_worlds_differing_in_who_is_human_tell_every_seat_the_same(tmp_path: Path) -> None:
    """Mutant: notice sent only to a human holder. In one game a person plays Kara; in
    its twin the aide's seat does. Every seat of Norra has the same papers on the same
    days, and the sitting falls on the same day with the same outcome."""
    (tmp_path / "human").mkdir()
    (tmp_path / "aide").mkdir()
    human = sitting(tmp_path / "human", office_on(BY_PERSON))
    aide = sitting(tmp_path / "aide", office_on(BY_PERSON), claimed=(ILSE, TOMAS))
    em = Emitter(aide.store, aide.state, cmp.versions())
    made = actors.unseated(aide.state, [KARA])
    em.commit([em.event(m, scope=PUBLIC) for m in made])
    assert aide.state.seats[seat_of(aide.state, KARA)].controller.value == "ai"
    for g in (human, aide):
        g.ask()
        g.choose(ILSE, True)
    told_human, told_aide = _told(human), _told(aide)
    assert told_human == told_aide
    assert set(told_human) == {ILSE, KARA}  # Norra's seats; not Tomas of Sudland
    a, b = human.until_decided(), aide.until_decided()
    assert (a.on, a.removed) == (b.on, b.removed)


def test_a_restart_before_the_sitting_gives_one_decision(tmp_path: Path) -> None:
    g = sitting(tmp_path, office_on(BY_PERSON))
    g.ask()
    g.choose(ILSE, True)
    g.tick()
    twin = MemoryStore()
    twin.append_all(list(g.store.read(CAMPAIGN)))
    g.tick()
    realism_tick.run_realism_tick(twin, CAMPAIGN, stop_after=TickStage.ADVANCE)
    realism_tick.run_realism_tick(twin, CAMPAIGN)
    assert state_hash(load_state(twin, CAMPAIGN)) == state_hash(g.state)
    once = [e for e in twin.read(CAMPAIGN) if isinstance(e.payload, ev.OfficeQuestionDecided)]
    assert len(once) == 1


# --- an order that would take the last authority -----------------------------------------


def test_an_order_taking_the_last_authority_opens_the_question_and_waits(tmp_path: Path) -> None:
    """Ilse dismisses Kara: no rung below, so the move is her last authority. The day
    walk opens the office question with it as the cause; only the sitting removes her."""
    g = sitting(tmp_path, office_on(BY_PERSON))
    out = g.order(KARA, COMMAND, appoint=False)
    (move,) = [p.move for p in out if isinstance(p, ev.PostMoveOrdered)]
    assert move.question and g.held(COMMAND) == KARA
    g.tick()
    (opened,) = g.payloads(ev.OfficeQuestionOpened)
    assert opened.question.cause is QuestionCause.ORDER
    assert opened.question.move_id == move.move_id
    assert g.held(COMMAND) == KARA
    g.choose(ILSE, True)
    made = g.until_decided()
    assert made.removed and move.move_id not in g.state.post_moves
    (settled,) = g.payloads(ev.PostMoveSettled)
    assert settled.landed


def test_with_office_off_the_order_stands_and_no_question_opens(tmp_path: Path) -> None:
    g = sitting(tmp_path, office_off)
    out = g.order(KARA, COMMAND, appoint=False)
    (move,) = [p.move for p in out if isinstance(p, ev.PostMoveOrdered)]
    for _ in range(3):
        g.tick()
    assert g.payloads(ev.OfficeQuestionOpened) == []
    assert g.held(COMMAND) == KARA and move.move_id in g.state.post_moves
    with pytest.raises(ValueError, match="no office question"):
        g.ask()


# --- the world keys ---------------------------------------------------------------


def test_the_keys_ride_on_the_ladders_and_are_public(tmp_path: Path) -> None:
    g = sitting(tmp_path, office_on(BY_COUNCIL))
    held = g.state.ladders[COMMAND]
    assert held.removed_by is not None and held.removed_by.needed == 2
    assert held.rests_on == ("greens",)
    assert CHANCELLERY not in g.state.office_rests and NORRA


def bad(**asset: Any) -> Callable[[World], None]:
    def change(w: World) -> None:
        for a in w["assets"]:
            if a["key"] == asset.get("key", "levy_command"):
                a.update({k: v for k, v in asset.items() if k != "key"})

    return change


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (bad(removed_by={"by": "council", "members": ["ilse"], "needed": 2}), "needs 1 to 1"),
        (bad(removed_by={"by": "council", "members": ["nobody"], "needed": 1}), "nobody"),
        (bad(removed_by={"by": "person"}), "names no person"),
        (bad(removed_by={"by": "term"}), "names no day"),
        (bad(removed_by={"by": "vote", "chamber": "senate"}), "no chamber"),
        (bad(rests_on=["nothing"]), "nothing"),
    ],
    ids=["council too few", "unknown member", "no person", "no day", "no chamber", "no base"],
)
def test_the_compiler_refuses(tmp_path: Path, change: Callable[[World], None], words: str) -> None:
    with pytest.raises(WorldError, match=words):
        compile_world(world(tmp_path, office_on(None), change), CAMPAIGN, cmp.versions())


def test_with_office_off_the_keys_are_not_read(tmp_path: Path) -> None:
    state = load_state_of(world(tmp_path, office_off, bad(removed_by=BY_PERSON)))
    assert state.ladders[COMMAND].removed_by is None


def load_state_of(w: WorldFile) -> State:
    store = MemoryStore()
    store.append_all(compile_world(w, CAMPAIGN, cmp.versions()))
    return load_state(store, CAMPAIGN)


def test_the_engine_seals_the_opening_to_the_holders_nation(tmp_path: Path) -> None:
    g = sitting(tmp_path, office_on(BY_PERSON))
    day = g.state.in_world_date
    assert day is not None
    opened, _paper = office.open_question(g.state, COMMAND, QuestionCause.INCIDENT, day)
    assert isinstance(opened, ev.OfficeQuestionOpened)
    held = realism_tick._scope_of(g.state, opened)
    assert held.known_by == office.scope_of(g.state, opened.question).known_by
    assert held.known_by == frozenset({seat(ILSE), seat(KARA)})


def test_showing_a_members_choice_to_a_person_is_an_admin_read(tmp_path: Path) -> None:
    g = sitting(tmp_path, office_on(BY_COUNCIL))
    g.ask()
    g.choose(TOMAS, False)
    (filed,) = [e for e in g.store.read(CAMPAIGN) if isinstance(e.payload, ev.OfficeChoiceFiled)]
    assert sealing.needs_admin_read(filed)
