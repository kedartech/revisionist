"""The office question as the seat sees it (OFR).

The toy of ``tests/test_office_question.py`` (Kara holds the command of the levy, which
rests on the Greens; Ilse removes her; Tomas holds Sudland) read through the seat's own
data: the ``home`` block's ``office``, ``turning`` and ``elections`` keys, the due matters
and the wake notice, and the ``office-vote`` action.

The payload contract these tests hold the implementation to (wording is [proposed]):

* ``home["office"]``: ``list[OfficeQuestionLine]``, one per question open on a post of the
  seat's own nation, by sitting day. A seat of any other nation reads ``[]``.
* ``home["turning"]``: ``list[BaseUnder]``, one per post the seat's person holds whose base
  stands under its line with no question yet open; every other seat reads ``[]``.
* ``home["footing"]``: ``list[FootingLine]``, one per post the seat's person holds that
  may be put to a question, at, above or under its line; every other seat reads ``[]``.
* ``home["results"]``: ``list[OfficeResult]``, each question of the seat's nation decided
  in the last ``home_api.RESULT_DAYS`` world days, public; a seat of another nation reads ``[]``.
* ``home["elections"]``: ``list[ElectionAhead]``, each election of the seat's nation not
  yet held, by day, with each chamber's seats as they would be redrawn today.
* action ``office-vote``, body ``{"question": str, "remove": bool}``, sealed by a commit.
"""

import json
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import AssetId
from revisionist.core.ontology import Controller
from revisionist.core.realism import groups, office
from revisionist.core.state import QuestionCause
from revisionist.engine import notice, realism_tick
from revisionist.engine.web import agenda_api, home_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests.test_blocs_turn import greens_at, low
from tests.test_due_matters import opened
from tests.test_elections import DAY, past_the_day, support, with_post, without_post
from tests.test_notice import GAME
from tests.test_office_question import (
    BY_PERSON,
    Sitting,
    green_row,
    office_on,
    seat_of,
    sitting,
)
from tests.test_posts import CHANCELLERY, COMMAND, ILSE, KARA, NORRA, TOMAS, world
from tests.test_territory_model import CAMPAIGN
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, state_of

BY_BODY = {"by": "vote", "chamber": "assembly"}
TWO = {"by": "council", "members": ["ilse", "kara"], "needed": 1}
POST_NAME = "General of the Norra Levy"
FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"


def built(tmp: Path, *changes: Callable[[dict[str, Any]], None], **kw: Any) -> Sitting:
    tmp.mkdir(parents=True, exist_ok=True)
    return sitting(tmp, *changes, **kw)


def home(g: Sitting, who: Any) -> dict[str, Any]:
    """The seat's ``home`` block as it is sent."""
    log = list(g.store.read(CAMPAIGN))
    out = rs.seat_realism(g.state, seat_of(g.state, who), set(), set(), None, events=log)["home"]
    assert out is not None
    return dict(out)


def seen(g: Sitting, who: Any) -> str:
    """Everything the seat is sent that could carry the question: its realism block, its
    agenda and its wake notice, as bytes for comparison."""
    log = list(g.store.read(CAMPAIGN))
    seat = seat_of(g.state, who)
    out = {
        "realism": rs.seat_realism(g.state, seat, set(), set(), None, events=log),
        "agenda": agenda_api.agenda(g.state, seat, log),
        "notice": notice.compose(opened(g.state), seat, None, GAME),
    }
    return json.dumps(out, sort_keys=True, default=str)


def office_keys(g: Sitting, who: Any) -> str:
    """Only the three keys of the home block this item adds, and the notice."""
    h = home(g, who)
    seat = seat_of(g.state, who)
    shown = {k: h.get(k) for k in ("office", "turning", "elections")}
    shown["notice"] = notice.compose(opened(g.state), seat, None, GAME)[1]
    return json.dumps(shown, sort_keys=True, default=str)


def asked(tmp: Path, *changes: Callable[[dict[str, Any]], None], **kw: Any) -> Sitting:
    """A game with one office question open on the command, whom Ilse removes."""
    g = built(tmp, *changes, greens_at(60), **kw)
    g.ask()
    return g


# --- Rule 1: the base under its line --------------------------------------------------


def test_the_holder_sees_how_far_under_and_how_long_and_the_day_a_question_would_open(
    tmp_path: Path,
) -> None:
    g = low(tmp_path)
    g.tick()
    fell = g.state.office_base_fell[COMMAND]
    (under,) = home(g, KARA)["turning"]
    assert under["office"] == POST_NAME
    assert under["support"] == 20.0 and under["line"] == office.TURN_LINE
    assert under["under"] == office.TURN_LINE - 20.0
    today = g.state.in_world_date
    assert today is not None
    assert under["days"] == (today - fell).days + 1 >= 1
    assert under["opens"] == (fell + timedelta(days=office.TURN_DAYS - 1)).isoformat()
    greens = groups.group(g.state, NORRA, "greens")
    assert greens is not None and under["groups"] == [greens.name]


def test_no_other_seat_sees_a_base_under_its_line(tmp_path: Path) -> None:
    g = low(tmp_path)
    g.tick()
    for who in (ILSE, TOMAS):
        assert home(g, who)["turning"] == []


def test_a_base_at_its_line_shows_nothing_to_its_holder(tmp_path: Path) -> None:
    g = built(tmp_path, office_on(BY_PERSON), greens_at(60))
    g.tick()
    assert home(g, KARA)["turning"] == []


def test_once_the_question_is_open_the_base_is_no_longer_turning(tmp_path: Path) -> None:
    g = low(tmp_path)
    g.tick()
    g.ask()
    assert home(g, KARA)["turning"] == []


# --- The holder's footing, always in view ---------------------------------------------


def test_the_holder_sees_his_footing_at_and_above_the_line_with_no_days_under(
    tmp_path: Path,
) -> None:
    g = built(tmp_path, office_on(BY_PERSON), greens_at(60))
    g.tick()
    (mine,) = home(g, KARA)["footing"]
    assert mine["office"] == POST_NAME and mine["line"] == office.TURN_LINE
    assert mine["support"] >= office.TURN_LINE and mine["days"] == 0
    assert mine["question"] is None
    assert set(mine) == set(api.FootingLine.__annotations__)


def test_under_the_line_the_footing_counts_the_days_running(tmp_path: Path) -> None:
    g = low(tmp_path)
    g.tick()
    (mine,) = home(g, KARA)["footing"]
    (under,) = home(g, KARA)["turning"]
    assert mine["support"] == under["support"] and mine["days"] == under["days"] >= 1


def test_the_footing_names_the_question_open_on_the_office(tmp_path: Path) -> None:
    g = asked(tmp_path, office_on(BY_PERSON))
    (made,) = g.state.office_questions.values()
    (mine,) = home(g, KARA)["footing"]
    assert mine["question"] == made.question_id


def test_no_seat_but_the_holder_sees_the_footing(tmp_path: Path) -> None:
    g = low(tmp_path)
    g.tick()
    for who in (ILSE, TOMAS):
        assert home(g, who)["footing"] == []


# --- The public result ----------------------------------------------------------------


def test_the_result_is_sent_to_the_nation_once_decided_and_the_question_is_gone(
    tmp_path: Path,
) -> None:
    g = asked(tmp_path, office_on(BY_PERSON))
    (made,) = g.state.office_questions.values()
    g.choose(ILSE, True)
    decided = g.until_decided()
    for who in (ILSE, KARA):
        h = home(g, who)
        assert h["office"] == []
        (line,) = h["results"]
        assert line["question_id"] == made.question_id
        assert line["office"] == POST_NAME and line["holder"] == "Kara Lind"
        assert line["removed"] is True and line["on"] == decided.on.isoformat()
        assert line["rests_until"] is None
        assert set(line) == set(api.OfficeResult.__annotations__)
    assert home(g, TOMAS)["results"] == []


def test_a_kept_holder_shows_the_day_he_rests_until(tmp_path: Path) -> None:
    g = asked(tmp_path, office_on(BY_PERSON))
    g.choose(ILSE, False)
    decided = g.until_decided()
    (line,) = home(g, KARA)["results"]
    assert line["removed"] is False
    assert decided.rests_until is not None
    assert line["rests_until"] == decided.rests_until.isoformat()


def test_the_result_leaves_the_home_block_after_its_days(tmp_path: Path) -> None:
    g = asked(tmp_path, office_on(BY_PERSON))
    g.choose(ILSE, False)
    decided = g.until_decided()
    while (today := g.state.in_world_date) is not None and (
        (today - decided.on).days < home_api.RESULT_DAYS
    ):
        assert home(g, KARA)["results"] != []
        g.tick()
    assert home(g, KARA)["results"] == []


def test_with_office_off_the_home_block_has_no_footing_or_results(tmp_path: Path) -> None:
    g = built(tmp_path, greens_at(60))
    assert "footing" not in home(g, ILSE) and "results" not in home(g, ILSE)


# --- Rule 2: an open question is in every seat of the nation --------------------------


def test_every_seat_of_the_nation_sees_the_open_question(tmp_path: Path) -> None:
    g = asked(tmp_path, office_on(BY_PERSON))
    (made,) = g.state.office_questions.values()
    for who in (ILSE, KARA):
        (line,) = home(g, who)["office"]
        assert line["question_id"] == made.question_id
        assert line["office"] == POST_NAME
        assert line["cause"] == QuestionCause.INCIDENT.value
        assert line["sits"] == made.sits.isoformat()
        assert line["way"] == "person" and line["deciders"] == [g.state.entities[ILSE].name]
        assert line["count"] is None
    assert set(line) == set(api.OfficeQuestionLine.__annotations__)


def test_the_seat_that_decides_is_told_so_and_the_others_are_not(tmp_path: Path) -> None:
    g = asked(tmp_path, office_on(BY_PERSON))
    assert [home(g, w)["office"][0]["mine"] for w in (ILSE, KARA)] == [True, False]


def test_a_council_names_those_who_decide(tmp_path: Path) -> None:
    g = asked(tmp_path, office_on(TWO))
    (line,) = home(g, KARA)["office"]
    assert line["way"] == "council"
    assert sorted(line["deciders"]) == sorted(g.state.entities[p].name for p in (ILSE, KARA))


@pytest.mark.parametrize(("yeas", "carries"), [(45, True), (10, False)], ids=["carried", "lost"])
def test_a_bodys_question_shows_the_count_as_it_would_fall_today(
    tmp_path: Path, yeas: int, carries: bool
) -> None:
    g = asked(tmp_path, office_on(BY_BODY), green_row(yeas))
    for who in (ILSE, KARA):
        (line,) = home(g, who)["office"]
        assert line["way"] == "vote" and line["chamber"] == "assembly"
        assert set(line["count"]) == set(api.OfficeCount.__annotations__)
        assert (line["count"]["yeas"] > line["count"]["nays"]) is carries


def test_with_office_off_the_home_block_has_no_office_keys(tmp_path: Path) -> None:
    g = built(tmp_path, greens_at(60))
    assert "office" not in home(g, ILSE) and "turning" not in home(g, ILSE)


def test_the_home_block_declares_the_three_new_keys() -> None:
    assert "office" in api.HomeBlock.__annotations__
    assert "turning" in api.HomeBlock.__annotations__
    assert "elections" in api.HomeBlock.__annotations__


# --- Fog: another nation's seat sees nothing of it ------------------------------------


def test_another_nations_seat_sees_nothing_of_the_question_before_its_result(
    tmp_path: Path,
) -> None:
    g = asked(tmp_path, office_on(BY_BODY), green_row(45))
    (made,) = g.state.office_questions.values()
    abroad = home(g, TOMAS)
    assert abroad["office"] == [] and abroad["turning"] == []
    assert made.question_id not in seen(g, TOMAS)
    assert (
        "office question"
        not in notice.compose(opened(g.state), seat_of(g.state, TOMAS), None, GAME)[1]
    )


def test_the_count_is_not_shown_abroad(tmp_path: Path) -> None:
    """Twin games, the Greens' row on the question 45 for it in one and 10 in the other:
    the nation's seat reads another count, a seat of Sudland reads the same."""
    carried = asked(tmp_path / "a", office_on(BY_BODY), green_row(45))
    lost = asked(tmp_path / "b", office_on(BY_BODY), green_row(10))
    (here,), (there,) = home(carried, ILSE)["office"], home(lost, ILSE)["office"]
    assert here["count"] != there["count"]
    assert home(carried, TOMAS)["office"] == home(lost, TOMAS)["office"] == []
    assert office_keys(carried, TOMAS) == office_keys(lost, TOMAS)


# --- A sealed choice is its own seat's -------------------------------------------------


def test_a_seat_sees_its_own_choice_and_no_other_before_the_sitting(tmp_path: Path) -> None:
    g = asked(tmp_path, office_on(TWO))
    g.choose(ILSE, True)
    (mine,) = home(g, ILSE)["office"]
    assert mine["choice"] is True
    for who in (KARA, TOMAS):
        assert all(line["choice"] is None for line in home(g, who)["office"])


def test_twin_games_differing_in_one_members_choice_read_the_same_to_everyone_else(
    tmp_path: Path,
) -> None:
    yes = asked(tmp_path / "yes", office_on(TWO))
    no = asked(tmp_path / "no", office_on(TWO))
    yes.choose(ILSE, True)
    no.choose(ILSE, False)
    assert home(yes, ILSE)["office"] != home(no, ILSE)["office"]
    for who in (KARA, TOMAS):
        assert seen(yes, who) == seen(no, who)


def test_a_choice_is_not_in_the_notice_or_the_due_matters(tmp_path: Path) -> None:
    g = asked(tmp_path, office_on(TWO))

    def told(who: Any) -> str:
        return notice.compose(opened(g.state), seat_of(g.state, who), None, GAME)[1]

    before = told(KARA), told(ILSE)
    g.choose(ILSE, True)
    assert (told(KARA), told(ILSE)) == before
    g.choose(KARA, False)
    assert (told(KARA), told(ILSE)) == before


# --- Twin worlds on the count ---------------------------------------------------------


def test_twin_worlds_differing_in_a_blocs_row_differ_in_the_count_at_home_only(
    tmp_path: Path,
) -> None:
    a = asked(tmp_path / "a", office_on(BY_BODY), green_row(45))
    b = asked(tmp_path / "b", office_on(BY_BODY), green_row(20))
    for who in (ILSE, KARA):
        assert home(a, who)["office"][0]["count"] != home(b, who)["office"][0]["count"]
    assert seen(a, TOMAS) == seen(b, TOMAS)


# --- Nothing says who plays a seat ----------------------------------------------------


def test_the_payload_never_says_whether_a_seat_is_a_person_the_aide_or_code(
    tmp_path: Path,
) -> None:
    """Twin games, Kara played by a person in one and handed to the aide in the other:
    every other seat reads the same office data."""
    present = asked(tmp_path / "p", office_on(BY_PERSON))
    absent = asked(tmp_path / "a", office_on(BY_PERSON))
    absent.add(ev.SeatHandover(entity_id=KARA, controller=Controller.AI))
    for who in (ILSE, TOMAS):
        assert office_keys(present, who) == office_keys(absent, who)
    (line,) = home(present, ILSE)["office"]
    assert not {"human", "aide", "controller", "present", "played"} & set(line)


# --- Due matters and the notice ------------------------------------------------------


def test_the_question_is_a_due_matter_of_the_holder_and_of_each_member(tmp_path: Path) -> None:
    g = asked(tmp_path, office_on(BY_PERSON))
    (made,) = g.state.office_questions.values()
    for who in (KARA, ILSE):
        matters = [
            m for m in agenda_api.due_matters(g.state, seat_of(g.state, who)) if m.kind == "office"
        ]
        assert [(m.subject, m.due) for m in matters] == [(made.question_id, made.sits.isoformat())]
    assert [
        m for m in agenda_api.due_matters(g.state, seat_of(g.state, TOMAS)) if m.kind == "office"
    ] == []


def test_the_office_question_and_its_sitting_are_registered_as_due_kinds() -> None:
    assert "office" in agenda_api.DUE_KINDS and "sitting" in agenda_api.DUE_KINDS


# --- Rule 5: the elections ahead -----------------------------------------------------


def test_the_home_data_carries_each_election_ahead_with_its_seats_as_redrawn_today(
    tmp_path: Path,
) -> None:
    g = built(tmp_path, support(80, 10), with_post)
    (ahead,) = home(g, ILSE)["elections"]
    assert ahead["day"] == DAY.isoformat()
    assert ahead["office"] == g.state.assets[CHANCELLERY].name
    (chamber,) = ahead["chambers"]
    assert chamber["key"] == "assembly"
    seats = {b["group"]: (b["seats"], b["would"]) for b in chamber["blocs"]}
    assert seats == {"greens": (60, 64), "greys": (40, 36)}
    assert set(ahead) == set(api.ElectionAhead.__annotations__)
    assert set(chamber["blocs"][0]) == set(api.ElectionBloc.__annotations__)


def test_the_seats_as_they_would_fall_move_with_the_bloc_support(tmp_path: Path) -> None:
    """At the baselines no seat would move; at 80 and 10 the Greens gain four."""
    still = built(tmp_path / "s", support(55, 30), without_post)
    moved = built(tmp_path / "m", support(80, 10), without_post)
    (a,), (b,) = home(still, ILSE)["elections"], home(moved, ILSE)["elections"]
    assert a["office"] is None
    assert [x["would"] for x in a["chambers"][0]["blocs"]] == [60, 40]
    assert [x["would"] for x in b["chambers"][0]["blocs"]] == [64, 36]


def test_an_election_held_is_no_longer_ahead(tmp_path: Path) -> None:
    g = built(tmp_path, support(80, 10), without_post)
    past_the_day(g)
    assert home(g, ILSE)["elections"] == []


def test_another_nations_seat_sees_no_election_of_norra(tmp_path: Path) -> None:
    g = built(tmp_path, support(80, 10), without_post)
    assert home(g, TOMAS)["elections"] == []
    assert "assembly" not in json.dumps(home(g, TOMAS)["elections"])


def test_with_elections_off_the_home_block_has_no_elections_key(tmp_path: Path) -> None:
    g = built(tmp_path, office_on(BY_PERSON), greens_at(60))
    assert "elections" not in home(g, ILSE)


# --- The action ---------------------------------------------------------------------


@pytest.fixture
def trio(web: Web, tmp_path: Path) -> Iterator[tuple[Realism, Client, Client, Client]]:  # noqa: F811
    world(tmp_path, office_on(BY_PERSON), greens_at(60))
    game_ = Realism(web, str(tmp_path / "world.yaml"))
    ada = game_.seat("ada", "ilse")
    bea = game_.seat("bea", "kara")
    cy = game_.seat("cyd", "tomas")
    make_host(game_, ada)
    begin(game_)
    store = game_.web.app.open()
    try:
        realism_tick.open_office_question(
            store, game_.campaign, AssetId(game_.ids["levy_command"]), QuestionCause.INCIDENT
        )
    finally:
        store.close()
    yield game_, ada, bea, cy


def _question(game_: Realism) -> str:
    (only,) = state_of(game_).office_questions
    return only


def _choices(game_: Realism) -> list[bool]:
    return list(state_of(game_).office_choices.get(_question(game_), {}).values())


def test_the_action_is_one_the_server_knows_and_seals_by_commit() -> None:
    from revisionist.engine.web import server

    assert "office-vote" in server.REALISM_ACTIONS and "office-vote" in server.SEALED_BY_COMMIT


def test_the_office_vote_action_files_a_choice_and_filing_again_replaces_it(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, ada, bea, _ = trio
    q = _question(game_)
    status, out = post(ada, "office-vote", question=q, remove=True)
    assert status == 200 and not out["refused"], out
    assert _choices(game_) == [True]
    status, out = post(ada, "office-vote", question=q, remove=False)
    assert status == 200 and not out["refused"], out
    assert _choices(game_) == [False]
    (mine,) = realism_of(ada)["home"]["office"]
    assert mine["choice"] is False
    (other,) = realism_of(bea)["home"]["office"]
    assert other["choice"] is None and other["mine"] is False


def test_an_office_vote_from_a_seat_that_does_not_decide_is_refused(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, _, bea, cy = trio
    q = _question(game_)
    for client in (bea, cy):
        status, out = post(client, "office-vote", question=q, remove=True)
        assert status == 200 and out["refused"], out
    assert _choices(game_) == []


def test_a_refused_office_vote_reads_the_same_whether_the_question_is_open_or_not(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    """A seat naming a question it does not decide is told what it is told of one that does
    not exist, so it cannot learn whether another nation has a question open."""
    game_, ada, bea, cy = trio
    q = _question(game_)
    for client in (bea, cy):
        open_, none = (post(client, "office-vote", question=n, remove=True)[1] for n in (q, "x"))
        assert open_["refused"] and open_ == none, (open_, none)
    _, none = post(ada, "office-vote", question="x", remove=True)
    _, abroad = post(cy, "office-vote", question=q, remove=True)
    assert none["reply"] == abroad["reply"] == office.NOT_YOURS
    assert _choices(game_) == []


@pytest.mark.parametrize(
    "body",
    [{"question": "no-such-question", "remove": True}, {"remove": True}, {"question": "x"}],
    ids=["no such question", "no question named", "no choice named"],
)
def test_an_office_vote_naming_nothing_real_is_refused(
    trio: tuple[Realism, Client, Client, Client], body: dict[str, Any]
) -> None:
    game_, ada, _, _ = trio
    status, out = post(ada, "office-vote", **body)
    assert status == 200 and out["refused"], out
    assert _choices(game_) == []


def test_an_office_vote_with_the_choice_not_true_or_false_is_refused(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, ada, _, _ = trio
    _, out = post(ada, "office-vote", question=_question(game_), remove="maybe")
    assert out["refused"] and _choices(game_) == []


def test_a_vote_after_the_seats_commit_is_held_for_the_next_wake(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, ada, bea, cy = trio
    q = _question(game_)
    status, out = post(ada, "commit")
    assert status == 200 and not out["refused"], out
    status, out = post(ada, "office-vote", question=q, remove=True)
    assert status == 200 and not out["refused"] and "held" in out, out
    assert _choices(game_) == []
    for other in (bea, cy):  # the last commit closes the wake and opens the next
        status, out = post(other, "commit")
        assert status == 200 and not out["refused"], out
    assert _choices(game_) == [True]


def test_the_reply_to_a_filed_choice_never_says_which(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, ada, _, _ = trio
    q = _question(game_)
    _, said = post(ada, "office-vote", question=q, remove=True)
    _, other = post(ada, "office-vote", question=q, remove=False)
    assert said == other
    assert "sealed" in said["reply"].lower()


# --- The board's fixture --------------------------------------------------------------


def test_the_seat_fixture_carries_the_office_keys_as_a_game_sends_them(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text())["home"]
    for name in "ole":
        (tmp_path / name).mkdir()
    g = asked(tmp_path / "o", office_on(BY_BODY), green_row(40))
    assert fixture["office"] == home(g, ILSE)["office"]
    g = low(tmp_path / "l")
    g.tick()
    assert fixture["turning"] == home(g, KARA)["turning"]
    assert (
        fixture["elections"]
        == home(built(tmp_path / "e", support(80, 10), with_post), ILSE)["elections"]
    )
    assert set(fixture["office"][0]["count"]) == set(api.OfficeCount.__annotations__)
    assert set(fixture["turning"][0]) == set(api.BaseUnder.__annotations__)


def test_the_seat_fixture_carries_the_footing_and_a_result_as_a_game_sends_them(
    tmp_path: Path,
) -> None:
    fixture = json.loads(FIXTURE.read_text())["home"]
    for name in "lr":
        (tmp_path / name).mkdir()
    g = low(tmp_path / "l")
    g.tick()
    assert fixture["footing"] == home(g, KARA)["footing"]
    g = asked(tmp_path / "r", office_on(BY_PERSON))
    g.choose(ILSE, False)
    g.until_decided()
    assert fixture["results"] == home(g, KARA)["results"]
