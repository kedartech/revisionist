"""The fall, played: the scripted proof that a player can lose a post, by an order
from above or by a question on his office, and goes on playing the person from where he
lands (``tests/the_fall_script.py``).

Rule 1, the relief: Yamamoto sends his held order anyway; it is an incident; Konoe
disowns it and relieves him; the notice reaches Yamamoto's seat the day it is ordered and
the post moves at the close of the next wake; he plays on from Kure; he is restored.
Rule 2, the fall: Konoe's base stands under the line; the warning, the question and the
sitting come in that order and on the days the office question gives; he is removed in
one script and kept in another; removed, he plays on as the person and Tojo, his
successor, holds the office.
Rule 3, on the toy: Ilse's bill fails on the floor, the election redraws the assembly,
and sent again it passes.
Rule 4, on the toy: Ilse is lost; her player takes Kara, who wins only with both aims.
Rule 5: Yamamoto away with his order held, and Konoe away with the incident before him;
the aide does nothing on the bar and its note names what waits.
Rule 6: Konoe and Yamamoto each run by code in turn; the office notices and changes of
post fall on the same days as with both played.
Each script run twice gives one digest, and so does one with a restart in the middle. A
twin world for each shows the seat's view carries no figure outside it and nothing of
whether another seat is human. Each stage-4 rule switched off changes what at least one
script ends with.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.goals import GoalSource
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import defiance, ladder, office
from revisionist.core.realism.card import PostCause
from revisionist.core.realism.detect import Barred
from revisionist.core.state import PostMove, QuestionCause
from revisionist.engine.tick import NotInPlayError
from tests.commanders_script import Script
from tests.locked_orders_script import World, digest
from tests.test_elections import DAY as ELECTION_DAY
from tests.test_posts import ILSE, KARA, seat
from tests.the_fall_script import (
    AWAY_WAKES,
    FLEET_POST,
    LESSER_POST,
    PLAIN,
    PREMIERSHIP,
    STAGE_4,
    Fall,
    away,
    by_code,
    fall,
    floor,
    held_by,
    lost,
    purse,
    relief,
)


def _with[P](g: Fall, kind: type[P]) -> list[tuple[ev.Event, P]]:
    """Each event of ``kind`` in the game's log, with its payload."""
    out: list[tuple[ev.Event, P]] = []
    for e in g.events():
        if isinstance(e.payload, kind):
            out.append((e, e.payload))
    return out


def _moves(g: Fall) -> list[PostMove]:
    return [e.move for e in g.logged(ev.PostMoveOrdered)]


# --- rule 1: the relief --------------------------------------------------------------


def test_the_commander_sends_his_held_order_anyway_and_it_is_an_incident(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = relief(tmp_path, monkeypatch)
    f = g.fallen
    assert f.defied is not None and f.defied.defied.order_id == f.held
    opened = [e.incident for e in g.logged(ev.IncidentOpened)]
    assert [i.incident_id for i in opened] == [f.incident]
    assert opened[0].cause is defiance.Cause.DEFIED
    assert opened[0].commander == g.entity("yamamoto")
    assert opened[0].superior == g.entity("konoe")
    answered = g.logged(ev.IncidentAnswered)
    assert [a.verdict for a in answered] == [defiance.Verdict.DISOWNED]


def test_the_head_relieves_him_with_the_notice_a_wake_ahead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = relief(tmp_path, monkeypatch)
    f = g.fallen
    relieved = next(m for m in _moves(g) if not m.appoint)
    assert relieved.person == g.entity("yamamoto") and relieved.by == g.entity("konoe")
    assert relieved.wake == f.relieved_wake and not relieved.question
    notice = ladder.notice_id(g.state, relieved.move_id)
    told = [e for e, d in _with(g, ev.DocumentIssued) if d.document.doc_id == notice]
    assert len(told) == 1 and g.commander in told[0].scope.known_by
    assert notice in project(g.state, g.commander).documents
    assert notice not in project(g.state, g.head).documents if g.head else True
    landed = [s for s in g.logged(ev.PostMoveSettled) if s.move_id == relieved.move_id and s.landed]
    assert len(landed) == 1
    settled = next(e for e, s in _with(g, ev.PostMoveSettled) if s.move_id == relieved.move_id)
    assert told[0].tick < settled.tick
    # the first close after the order leaves him in post; the next moves him
    days = [(fleet, kure) for _, fleet, kure in f.holders]
    first = days.index((None, "yamamoto"))
    assert first >= 1 and days[first - 1] == ("yamamoto", None)


def test_the_commander_plays_on_from_the_lesser_post_and_is_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = relief(tmp_path, monkeypatch)
    f = g.fallen
    assert f.played_on and all(o in g.state.routed for o in f.played_on)
    assert g.state.routed[f.played_on[0]].issuer == g.commander
    changed = [(p.post, p.to, p.cause) for p in g.logged(ev.PostChanged)]
    yamamoto = g.entity("yamamoto")
    assert (g.post(LESSER_POST), yamamoto, PostCause.APPOINTED) in changed
    assert g.holder(FLEET_POST) == "yamamoto"
    restored = next(m for m in _moves(g) if m.appoint)
    assert restored.person == yamamoto and not restored.question
    assert g.commander in g.state.seats and g.state.seats[g.commander].embodies == yamamoto


# --- rule 2: the fall ----------------------------------------------------------------


@pytest.mark.parametrize("removed", [True, False], ids=["removed", "kept"])
def test_the_warning_then_the_question_then_the_sitting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, removed: bool
) -> None:
    g = fall(tmp_path, monkeypatch, removed=removed)
    post = g.post(PREMIERSHIP)
    issued = _with(g, ev.DocumentIssued)
    opened, first = _with(g, ev.OfficeQuestionOpened)[0]
    question = first.question
    sat, decided = _with(g, ev.OfficeQuestionDecided)[0]
    assert question.post == post and question.holder == g.entity("konoe")
    assert question.cause is QuestionCause.BASE
    warned = [
        e
        for e, d in issued
        if g.commander in e.scope.known_by and d.document.title.startswith("The base turns")
    ]
    question_notice = office.notice_id(g.state, question.question_id)
    told = [e for e, d in issued if d.document.doc_id == question_notice]
    assert told and g.commander in told[0].scope.known_by
    assert decided.question_id == question.question_id
    assert warned and warned[0].seq < opened.seq < sat.seq
    assert (decided.on - question.opened).days >= office.SITTING_DAYS
    assert sat.tick >= question.tick + office.WAKES_AHEAD - 1
    assert decided.removed is removed


def test_removed_he_plays_on_as_the_person_and_the_successor_holds_the_office(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = fall(tmp_path, monkeypatch, removed=True)
    causes = [(p.to, p.cause) for p in g.logged(ev.PostChanged) if p.post == g.post(PREMIERSHIP)]
    assert causes[:2] == [(None, PostCause.REMOVED), (g.entity("tojo"), PostCause.SUCCEEDED)]
    assert g.holder(PREMIERSHIP) == "tojo"
    assert g.commander in g.state.seats
    assert g.fallen.played_on and g.fallen.played_on[0] in g.state.routed


def test_kept_he_holds_the_office_and_it_rests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = fall(tmp_path, monkeypatch, removed=False)
    sat = g.logged(ev.OfficeQuestionDecided)[0]
    assert not sat.removed and sat.rests_until is not None
    assert not [p for p in g.logged(ev.PostChanged) if p.post == g.post(PREMIERSHIP)]
    assert g.holder(PREMIERSHIP) == "konoe"


# --- one digest, and a restart in the middle ----------------------------------------


def _removed(tmp: Path, mp: pytest.MonkeyPatch, script: Script = PLAIN) -> Fall:
    return fall(tmp, mp, removed=True, script=script)


def _kept(tmp: Path, mp: pytest.MonkeyPatch, script: Script = PLAIN) -> Fall:
    return fall(tmp, mp, removed=False, script=script)


def _relief(tmp: Path, mp: pytest.MonkeyPatch, script: Script = PLAIN) -> Fall:
    return relief(tmp, mp, script=script)


SCRIPTS: dict[str, Callable[..., Fall]] = {"relief": _relief, "removed": _removed, "kept": _kept}
each_script = pytest.mark.parametrize("name", sorted(SCRIPTS))


@each_script
def test_each_script_run_twice_gives_one_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    play = SCRIPTS[name]
    a = play(tmp_path / "a", monkeypatch)
    b = play(tmp_path / "b", monkeypatch)
    assert digest(a.state) == digest(b.state)
    assert a.fallen.holders == b.fallen.holders


@each_script
def test_each_script_with_a_restart_in_the_middle_gives_the_same_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    play = SCRIPTS[name]
    full = play(tmp_path / "full", monkeypatch)
    cut = play(tmp_path / "cut", monkeypatch, script=Script(restart_at=2))
    assert digest(cut.state) == digest(full.state)


# --- the played seat's view: twin worlds --------------------------------------------


def _halved(key: str):  # type: ignore[no-untyped-def]
    def change(w: World) -> None:
        q = next(q for q in w["quantities"] if q["key"] == key)
        q["value"] = q["value"] // 2

    return change


HIDDEN = "uk_sealift_grt"
"""A figure no Japanese seat sees."""


def _views(g: Fall) -> tuple[object, ...]:
    seats = [s for s in (g.commander, g.head) if s is not None]
    return tuple(project(g.state, s).model_dump(mode="json") for s in seats)


def test_the_relief_carries_no_fact_outside_either_seats_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = relief(tmp_path / "a", monkeypatch)
    b = relief(tmp_path / "b", monkeypatch, more=(_halved(HIDDEN),))
    assert digest(a.state) != digest(b.state)
    assert _views(a) == _views(b)


def _controller(g: Fall, person: str) -> str:
    """Who plays ``person``: a seat's controller, or the code for a person with no seat."""
    who = g.entity(person)
    return next((s.controller.value for s in g.state.seats.values() if s.embodies == who), "ai")


def _first_question(g: Fall) -> tuple[str, str, str, str, bool]:
    """What Konoe's seat is told of his office up to the first sitting: the day the base
    turned, the question's opening and sitting days, the day its paper went out, and the
    outcome."""
    warned = next(
        d.document.issued
        for e, d in _with(g, ev.DocumentIssued)
        if g.commander in e.scope.known_by and d.document.title.startswith("The base turns")
    )
    q = g.logged(ev.OfficeQuestionOpened)[0].question
    paper = next(
        d.document.issued
        for e, d in _with(g, ev.DocumentIssued)
        if d.document.doc_id == office.notice_id(g.state, q.question_id)
        and g.commander in e.scope.known_by
    )
    sat = g.logged(ev.OfficeQuestionDecided)[0]
    assert sat.question_id == q.question_id and sat.on >= q.sits
    return (
        warned.isoformat(),
        q.opened.isoformat(),
        q.sits.isoformat(),
        paper.isoformat(),
        sat.removed,
    )


@pytest.mark.parametrize("removed", [True, False], ids=["removed", "kept"])
def test_the_fall_carries_no_fact_outside_his_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, removed: bool
) -> None:
    a = fall(tmp_path / "a", monkeypatch, removed=removed)
    b = fall(tmp_path / "b", monkeypatch, removed=removed, more=(_halved(HIDDEN),))
    assert digest(a.state) != digest(b.state)
    view = project(a.state, a.commander).model_dump(mode="json")
    assert view == project(b.state, b.commander).model_dump(mode="json")


@pytest.mark.parametrize("removed", [True, False], ids=["removed", "kept"])
def test_the_fall_tells_him_nothing_of_who_beside_him_is_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, removed: bool
) -> None:
    """The code plays Yamamoto, beside Konoe, in one game; in its twin a player takes him up
    at the first close and the aide plays his seat. Konoe is told the same things of his
    office on the same days, the question sits on the same day and comes out the same, and
    no view he has names who plays a seat. The code and the aide play Yamamoto
    differently, so later wakes run to different days and are not compared."""
    code = fall(tmp_path / "code", monkeypatch, removed=removed)
    person = fall(tmp_path / "person", monkeypatch, removed=removed, beside_played=True)
    played = {g: _controller(g, "yamamoto") for g in (code, person)}
    assert played == {code: "ai", person: "human"}
    assert _first_question(code) == _first_question(person)
    assert _first_question(code)[-1] is removed
    for g in (code, person):
        view = project(g.state, g.commander).model_dump(mode="json")
        assert _who_plays(view) == ["/me"]


def _who_plays(view: object, at: str = "") -> list[str]:
    """Each place in a view that says whether a person or the code plays a seat."""
    found: list[str] = []
    if isinstance(view, dict):
        for k, v in view.items():
            if k == "controller" and v in ("human", "ai"):
                found.append(at)
            found += _who_plays(v, f"{at}/{k}")
    elif isinstance(view, list):
        for i, v in enumerate(view):
            found += _who_plays(v, f"{at}[{i}]")
    return found


TOY_HOLDS = {"isle": held_by("norra", "isle"), "hills": held_by("sudland", "norra_hills")}
"""Kara's two aims are the hills held and the isle taken; the toy opens with the first."""


# --- rule 3: the toy floor, before and after an election -----------------------------


def test_the_election_redraws_the_chamber_and_the_failed_measure_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = floor(tmp_path, monkeypatch)
    (before, failed), (after, passed) = f.passed
    assert before < ELECTION_DAY <= after
    assert (failed, passed) == (0, 1)
    assert f.seats[0] != f.seats[1]
    assert f.seats[1]["greens"] > f.seats[0]["greens"]  # type: ignore[operator]
    assert sum(v or 0 for v in f.seats[0].values()) == sum(v or 0 for v in f.seats[1].values())


# --- rule 4: the lost person and his replacement --------------------------------------


@pytest.mark.parametrize(
    ("held", "wins"),
    [((), False), (("isle",), True), (("isle", "hills"), False)],
    ids=["first-aim-only", "both-aims", "second-aim-only"],
)
def test_the_replacement_wins_only_with_both_aims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held: tuple[str, ...], wins: bool
) -> None:
    lo = lost(tmp_path, monkeypatch, *(TOY_HOLDS[h] for h in held))
    kara = seat(KARA)
    aims = [(x.source, x.holding) for x in lo.game.goals_of(KARA)]
    assert [s for s, _ in aims] == [GoalSource.REPLACEMENT] * 2
    assert (kara in lo.winners) is wins
    assert all(h for _, h in aims) is wins


# --- rule 5: every seat away in turn --------------------------------------------------


def _on_the_bar(g: Fall, gone: SeatId, person: EntityId) -> list[str]:
    """Each act on the aide's bar done for the seat ``gone`` (playing ``person``) after
    it went."""
    out: list[str] = []
    for e in g.events()[g.fallen.gone_at :]:
        p = e.payload
        if isinstance(p, ev.OrderDefied) and p.defied.issuer == gone:
            out.append(Barred.SEND_HELD)
        elif isinstance(p, ev.OrderAsked) and p.asked.asker == gone:
            out.append(Barred.ASK_HELD)
        elif isinstance(p, ev.IncidentAnswered) and not p.by_card and gone in p.seats:
            out.append(Barred.ANSWER)
        elif isinstance(p, ev.OfficeChoiceFiled) and p.seat_id == gone:
            out.append(Barred.OFFICE_VOTE)
        elif isinstance(p, ev.OfferMade) and p.offer.seat == gone:
            out.append(Barred.BLOC_OFFER)
        elif isinstance(p, ev.PostMoveOrdered) and p.move.by == person:
            out.append(Barred.APPOINT)
    return out


@pytest.mark.parametrize("who", ["commander", "head"])
def test_the_aide_does_nothing_on_the_bar_and_notes_what_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, who: str
) -> None:
    """Yamamoto away with his order held, or Konoe away with Yamamoto's incident before
    him: the aide commits each wake for the seat, does nothing on the bar, and its note
    names what waits."""
    g = away(tmp_path, monkeypatch, who)
    gone = g.fallen.away
    assert gone is not None
    person = g.entity("yamamoto" if who == "commander" else "konoe")
    commits = [
        e.payload
        for e in g.events()[g.fallen.gone_at :]
        if isinstance(e.payload, ev.WakeCommitted) and e.payload.seat_id == gone
    ]
    assert len(commits) >= AWAY_WAKES and all(c.by_aide for c in commits)
    assert _on_the_bar(g, gone, person) == []
    kinds = [w["kind"] for w in g.fallen.waits]
    if who == "commander":
        assert g.fallen.held in g.state.held, "the held order stays held"
        assert "held" in kinds
    else:
        assert g.logged(ev.IncidentOpened)
        assert kinds, "the incident waits on Konoe"


# --- rule 6: every seat run by code in turn -------------------------------------------


def _notices(g: Fall) -> list[tuple[str, str]]:
    """The notices on Konoe's office up to the first sitting, each with its day: the
    warning, the question and its paper, and the sitting."""
    out: list[tuple[str, str]] = []
    papers: set[str] = set()
    for e in g.events():
        p = e.payload
        if isinstance(p, ev.OfficeQuestionOpened):
            q = p.question
            papers.add(office.notice_id(g.state, q.question_id))
            out.append(("question", f"{q.opened} sits {q.sits} {q.cause}"))
        elif isinstance(p, ev.DocumentIssued):
            d = p.document
            if d.title.startswith("The base turns") or d.doc_id in papers:
                out.append(("paper", f"{d.issued} {d.title}"))
        elif isinstance(p, ev.OfficeQuestionDecided):
            out.append(("decided", f"{p.on} removed={p.removed}"))
            break
    return sorted(set(out))


@pytest.mark.parametrize("removed", [True, False], ids=["removed", "kept"])
def test_each_seat_run_by_code_gets_the_same_notices_and_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, removed: bool
) -> None:
    """Konoe's base turns under the line with nobody filing anything: run by code, each
    of Konoe and Yamamoto in turn changes nothing of what is noticed on the office, or on
    which day, up to the sitting."""
    played = by_code(tmp_path / "played", monkeypatch, None, removed=removed)
    assert played.logged(ev.OfficeQuestionDecided)[0].removed is removed
    for who in ("konoe", "yamamoto"):
        coded = by_code(tmp_path / who, monkeypatch, who, removed=removed)
        assert _controller(coded, who) == "ai"
        assert _notices(coded) == _notices(played), who
    kinds = [k for k, _ in _notices(played)]
    assert kinds.count("paper") >= 2 and kinds.count("question") == 1
    assert (played.fallen.holders[-1][1] != "konoe") is removed


# --- rules 3 and 4: one digest, a restart, and a twin -------------------------------


def _floor_digest(tmp: Path, mp: pytest.MonkeyPatch, restart_at: int | None) -> str:
    return digest(floor(tmp, mp, restart_at=restart_at).game.state)


def _lost_digest(tmp: Path, mp: pytest.MonkeyPatch, restart: bool = False) -> str:
    return digest(lost(tmp, mp, TOY_HOLDS["isle"], restart=restart).game.state)


def test_the_floor_and_the_lost_person_give_one_digest_twice_and_across_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    floors = {
        _floor_digest(tmp_path / f"f{i}", monkeypatch, restart_at=r)
        for i, r in enumerate((None, None, 1))
    }
    losts = {
        _lost_digest(tmp_path / f"l{i}", monkeypatch, restart=r)
        for i, r in enumerate((False, False, True))
    }
    assert len(floors) == 1 and len(losts) == 1


def test_the_floor_and_the_lost_person_carry_no_fact_outside_the_seat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = floor(tmp_path / "a", monkeypatch).game
    b = floor(tmp_path / "b", monkeypatch, more=(purse(500),)).game
    assert digest(a.state) != digest(b.state)
    view = project(a.state, seat(ILSE)).model_dump(mode="json")
    assert view == project(b.state, seat(ILSE)).model_dump(mode="json")
    assert _who_plays(view) == ["/me"]
    c = lost(tmp_path / "c", monkeypatch, TOY_HOLDS["isle"]).game
    d = lost(tmp_path / "d", monkeypatch, TOY_HOLDS["isle"], purse(500)).game
    assert digest(c.state) != digest(d.state)
    view = project(c.state, seat(KARA)).model_dump(mode="json")
    assert view == project(d.state, seat(KARA)).model_dump(mode="json")
    assert _who_plays(view) == ["/me"]


# --- rules 5 and 6: one digest, a restart, and a twin -------------------------------


def test_the_seat_away_gives_one_digest_twice_and_across_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for who in ("commander", "head"):
        runs = [
            away(tmp_path / f"{who}{i}", monkeypatch, who, script=s)
            for i, s in enumerate((PLAIN, PLAIN, Script(restart_at=2)))
        ]
        assert len({digest(g.state) for g in runs}) == 1, who


def test_the_seat_away_is_noted_nothing_outside_its_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for who in ("commander", "head"):
        a = away(tmp_path / f"{who}a", monkeypatch, who)
        b = away(tmp_path / f"{who}b", monkeypatch, who, more=(_halved(HIDDEN),))
        assert digest(a.state) != digest(b.state)
        assert a.fallen.waits == b.fallen.waits
        gone = a.fallen.away
        assert gone is not None
        view = project(a.state, gone).model_dump(mode="json")
        assert view == project(b.state, gone).model_dump(mode="json")
        assert _who_plays(view) == ["/me"]


def test_the_seat_run_by_code_gives_one_digest_and_learns_nothing_outside_its_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = [
        by_code(tmp_path / f"c{i}", monkeypatch, "konoe", removed=True, script=s)
        for i, s in enumerate((PLAIN, PLAIN, Script(restart_at=2)))
    ]
    assert len({digest(g.state) for g in runs}) == 1
    twin = by_code(tmp_path / "twin", monkeypatch, "konoe", removed=True, more=(_halved(HIDDEN),))
    assert digest(twin.state) != digest(runs[0].state)
    view = project(runs[0].state, runs[0].commander).model_dump(mode="json")
    assert view == project(twin.state, twin.commander).model_dump(mode="json")
    assert _who_plays(view) == ["/me"]


# --- each stage-4 rule switched off fails a check ----------------------------------


def _plays(off: str, tmp: Path, mp: pytest.MonkeyPatch) -> list[object]:
    """What each script ends with, the rule ``off`` where given: the holders and the
    incidents of the relief and the fall, the floor's results, the replacement's win and
    the aide's notes."""
    rule = off or None
    out: list[object] = []
    plays: tuple[tuple[str, Callable[[], Fall]], ...] = (
        ("relief", lambda: relief(tmp / "relief", mp, off=rule)),
        ("fall", lambda: fall(tmp / "fall", mp, removed=True, off=rule)),
    )
    for name, play in plays:
        try:
            g = play()
        except (AssertionError, ValueError, StopIteration, NotInPlayError) as e:
            out.append((name, "cannot be played", type(e).__name__))
            continue
        out.append((name, g.fallen.holders, len(g.logged(ev.IncidentOpened))))
    f = floor(tmp / "floor", mp, off=rule)
    out.append(("floor", [r for _, r in f.passed]))
    toy_off = (_toy_without(off),) if off else ()
    try:
        lo = lost(tmp / "lost", mp, TOY_HOLDS["isle"], *toy_off)
        out.append(("lost", seat(KARA) in lo.winners))
    except ValueError as e:
        out.append(("lost", "cannot be played", str(e)))
    try:
        g = away(tmp / "away", mp, "commander", off=rule)
        out.append(("away", [w["kind"] for w in g.fallen.waits]))
    except (AssertionError, ValueError, StopIteration, NotInPlayError) as e:
        out.append(("away", "cannot be played", type(e).__name__))
    return out


def _toy_without(rule: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = [r for r in w["rules"] if r != rule]

    return change


@pytest.fixture(scope="module")
def all_on(tmp_path_factory: pytest.TempPathFactory) -> list[object]:
    with pytest.MonkeyPatch.context() as mp:
        return _plays("", tmp_path_factory.mktemp("on"), mp)


@pytest.mark.parametrize("off", STAGE_4)
def test_each_stage_4_rule_switched_off_changes_what_a_script_ends_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, off: str, all_on: list[object]
) -> None:
    assert _plays(off, tmp_path, monkeypatch) != all_on
