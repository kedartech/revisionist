"""The second run's gate reviews' low findings, each reproduced before its fix.

One section per finding, named by what a player or host meets.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from revisionist.core.fold import FoldError
from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import economy
from revisionist.core.realism.conference import CONF_DAYS
from revisionist.core.realism.kinds import Role
from revisionist.core.visibility import private_to
from revisionist.engine import maps, realism_tick
from revisionist.engine.options import _forces
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import conferences_api, held, map_api
from tests import test_economy as te
from tests import test_realism_aims as ta
from tests import test_realism_locks as lk
from tests.test_adjacency_moves import START, entity
from tests.test_conference import CHARTER, ILSE, NAME, NORRA, OSTMARK, SUDLAND, day, game, world
from tests.test_map_versions import Games, games, run  # noqa: F401
from tests.test_realism_locks import HELD_FOR_ILSE
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_conference import LEVY, _game, _placed
from tests.test_web_economy import own
from tests.test_web_locks import TO_ISLE, trio  # noqa: F401
from tests.test_web_playback import caught, everything, failing, held_lines
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_stakes import ruled, toy_stakes, with_contest
from tests.test_web_wake import begin, state_of

# --- a held form order is answered with why it waits, not "Sent to" ----------------------


def test_a_held_form_order_is_answered_with_its_held_reason(
    trio: tuple[Realism, Client, Client, Client],  # noqa: F811
) -> None:
    _, ada, _, _ = trio
    status, out = post(ada, "lever", lever="march", params=TO_ISLE)
    assert status == 200 and not out["refused"], out
    (line,) = realism_of(ada)["locks"]["held"]
    assert out["reply"] == line["reason"] == HELD_FOR_ILSE
    assert "Sent to" not in out["reply"]


# --- a held conference call is checked against the caller's view when it lands -----------


def test_a_held_call_naming_a_piece_that_left_the_callers_desk_is_refused(
    tmp_path: Path,
) -> None:
    (tmp_path / "then").mkdir()
    (tmp_path / "now").mkdir()
    then = _game(tmp_path / "then")
    body = {
        "key": CHARTER,
        "text": "The gulf stays as it stands.",
        "invited": [str(SUDLAND), str(OSTMARK)],
        "voting_day": day(CONF_DAYS).isoformat(),
        "clauses": [_placed(LEVY, binds=NORRA).model_dump(mode="json")],
    }
    args, _ = conferences_api.call_args(then.state, ILSE, body)
    now = game(tmp_path / "now")
    now.open()
    assert LEVY in now.state.features and LEVY not in _forces(project(now.state, ILSE))
    store = MemoryStore()
    store.append_all(now.log)
    with pytest.raises(ValueError) as refused:
        conferences_api.call(store, now.state.campaign_id, ILSE, args)
    assert str(refused.value) == conferences_api.NOT_SEEN
    assert list(store.read(now.state.campaign_id)) == now.log


# --- a conference called by name is voted in by that name -------------------------------


@pytest.fixture
def callers(web: Web, tmp_path: Path) -> Iterator[tuple[Realism, Client, Client]]:  # noqa: F811
    world(tmp_path)
    game_ = Realism(web, str(tmp_path / "world.yaml"))
    ada = game_.seat("ada", "ilse")
    bea = game_.seat("bea", "tomas")
    game_.seat("cyd", "olaf")
    make_host(game_, ada)
    begin(game_)
    yield game_, ada, bea


def _called_by_name(game_: Realism, ada: Client) -> None:
    status, out = post(
        ada,
        "conference-call",
        key=NAME,
        text="Free trade on the gulf.",
        invited=[game_.ids["sudland"], game_.ids["ostmark"]],
        voting_day=(START + timedelta(days=CONF_DAYS + 1)).isoformat(),
        public=False,
    )
    assert status == 200 and not out["refused"], out


def test_the_caller_votes_in_its_conference_by_the_name_it_gave(
    callers: tuple[Realism, Client, Client],
) -> None:
    game_, ada, _ = callers
    _called_by_name(game_, ada)
    (stored,) = state_of(game_).conferences.held
    assert stored != NAME
    status, out = post(ada, "conference-vote", conference=NAME, vote="for")
    assert status == 200 and not out["refused"], out
    assert state_of(game_).conferences.votes[stored]


def test_another_seat_cannot_vote_by_the_callers_name(
    callers: tuple[Realism, Client, Client],
) -> None:
    game_, ada, bea = callers
    _called_by_name(game_, ada)
    status, out = post(bea, "conference-vote", conference=NAME, vote="for")
    assert status == 200 and out["refused"], out


# --- the seat's income is what the month pays, moved industry not yet restarted left out -


def test_the_seats_income_and_territories_leave_out_a_moved_part_not_yet_restarted(
    tmp_path: Path,
) -> None:
    g = te.game(tmp_path, te.FOUR)
    te.evacuate(g, START, amount=1)
    pays = economy.income(g.state, entity(te.NORRA), Role.OUTPUT, START)
    assert pays == 3
    mine = own(g.state)
    grain = {i["key"]: i["amount"] for i in mine["income"]}["grain"]
    assert grain == pays
    held = {t["area"]: t for t in mine["territories"]}
    assert held[te.HILLS]["yields"] == {"grain": 0}
    assert held[te.PLAIN]["yields"] == {"grain": 3}


# --- the backup's copy of every map object fails when there is none to copy --------------


def test_copying_every_map_object_from_an_empty_directory_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "objects"
    empty.mkdir()
    monkeypatch.setenv(maps.OBJECTS_ENV, str(empty))
    out = run("copy", "--all", "--to", str(tmp_path / "copy"))
    assert out.exit_code != 0
    assert f"FAIL no map object in {empty}" in out.output


# --- one campaign that cannot be read does not stop the map check for the others ---------


@pytest.mark.parametrize("command", ["verify", "copy"])
def test_a_campaign_that_cannot_be_read_is_one_fail_line_and_the_rest_are_checked(
    games: Games,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    def load(store: object, campaign: CampaignId) -> object:
        if campaign == games.old:
            raise FoldError("a stored event the fold refuses")
        return load_state(store, campaign)  # type: ignore[arg-type]

    monkeypatch.setattr(map_api, "load_state", load)
    args = ("--to", str(tmp_path / "copy")) if command == "copy" else ()
    out = run(command, *args)
    assert out.exception is None or isinstance(out.exception, SystemExit), out.exception
    assert out.exit_code != 0
    assert f"FAIL {games.old}: cannot be read" in out.output
    assert games.h2 in out.output  # the readable campaign is still checked


# --- the days to the season's end count only the contests the seat's view holds ----------


def test_a_contest_hidden_from_the_seat_moves_not_its_days_to_the_seasons_end(
    tmp_path: Path,
) -> None:
    g = ruled(tmp_path, ta.HILLS_HELD)
    (border,) = g.state.contests.values()
    assert border.decides is not None and g.state.in_world_date is not None
    other = SeatId("a-seat-of-another-nation")
    hidden = border.model_copy(
        update={
            "contest_id": type(border.contest_id)(f"{border.contest_id}-hidden"),
            "scope": private_to(other),
            "decides": border.decides + timedelta(days=30),
        }
    )
    twin = with_contest(g.state, hidden)
    seen = (border.decides - g.state.in_world_date).days
    assert toy_stakes(g)["season_days_left"] == seen
    assert toy_stakes(g, state=twin)["season_days_left"] == seen


# --- a held step that fails at the next opening is told in the room's words --------------


@pytest.mark.parametrize(
    ("raised", "told"),
    [
        ("order o1 is not waiting on a human", None),
        ("step 2 does not allow expedite", None),
        (realism_tick.NOT_YOURS, realism_tick.NOT_YOURS),
        (realism_tick.NO_AMEND, realism_tick.NO_AMEND),
    ],
)
def test_a_held_step_that_fails_at_replay_gives_no_engine_text(
    monkeypatch: pytest.MonkeyPatch, raised: str, told: str | None
) -> None:
    def refused(*_: object) -> None:
        raise ValueError(raised)

    monkeypatch.setattr(realism_tick, "take_step", refused)
    step = {"order_id": "o1", "action": "expedite", "params": {}}
    why = held.file_one(MemoryStore(), CampaignId("c"), SeatId("s"), "step", step)
    assert why == (told or held.NOT_OFFERED)


# --- a held order that fails is told with its words, as one that lands is ----------------


def test_the_failed_line_names_the_held_order_by_its_words(tmp_path: Path) -> None:
    store, _ = failing(tmp_path)
    lines = held_lines(caught(store, lk.KARA, first=0, last=everything(store)))
    (_, was_held), (_, failed) = lines
    words = was_held["line"].rsplit(": ", 1)[1].rstrip(".")
    assert words and words in failed["line"]
    assert failed["line"].startswith("Your held order failed")
