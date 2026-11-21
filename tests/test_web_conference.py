"""Calling a conference and voting in it, from the seat (CNA).

The toy world is played as CNF's tests play it (``tests/test_conference.py``):
``agreements`` and ``conference`` on, Ilse for Norra, Tomas for Sudland and Olaf for
Ostmark, a fourth power Vesta that nobody plays. The seat's ``conferences`` block lists
each conference its nation is invited to (and each public one) with the text, the
invited, the voting day, the seat's own vote and, after the tally, the result and each
nation's vote. An invited seat has a "Vote" item on its agenda due on the voting day,
which the wake notice lists without the vote. The web cases play the same world through
the server: ``conference-call`` calls one and ``conference-vote`` seals the seat's vote.
"""

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.ids import SeatId
from revisionist.core.realism.conference import CONF_DAYS, ConferenceText, Vote
from revisionist.engine import notice
from revisionist.engine.web import agenda_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests.test_adjacency_moves import START
from tests.test_conference import (
    CHARTER,
    ILSE,
    NORRA,
    OLAF,
    SUDLAND,
    TOMAS,
    Game,
    binding_text,
    day,
    game,
    run_until_tallied,
    world,
)
from tests.test_due_matters import opened
from tests.test_notice import GAME
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, state_of

FIXTURES = Path(__file__).parents[1] / "web" / "test" / "fixtures"
TRADE = ConferenceText(wording="Free trade on the gulf, and no tariffs.")


def block(g: Game, who: SeatId) -> dict[str, Any] | None:
    out = rs.seat_realism(g.state, who, set(), set(), None, events=g.log)["conferences"]
    return None if out is None else dict(out)


def lines(g: Game, who: SeatId) -> list[dict[str, Any]]:
    found = block(g, who)
    assert found is not None
    return list(found["conferences"])


def vote_items(g: Game, who: SeatId) -> list[api.AgendaItem]:
    return [i for i in agenda_api.agenda(g.state, who, g.log)["items"] if i["kind"] == "Vote"]


def notice_text(g: Game, who: SeatId) -> str:
    return notice.compose(opened(g.state), who, None, GAME)[1]


def seen(g: Game, who: SeatId) -> str:
    """Everything the seat is sent: its realism block (papers included), its agenda and
    its wake notice, as bytes for comparison."""
    out = {
        "realism": rs.seat_realism(g.state, who, set(), set(), None, events=g.log),
        "agenda": agenda_api.agenda(g.state, who, g.log),
        "notice": notice.compose(opened(g.state), who, None, GAME),
    }
    return json.dumps(out, sort_keys=True, default=str)


def called(tmp: Path, text: ConferenceText = TRADE, **kw: Any) -> Game:
    g = game(tmp)
    g.open()
    g.call(text=text, **kw)
    return g


# --- Rule 3: the conferences block ---------------------------------------------------


def test_the_block_lists_each_conference_the_seat_is_invited_to(tmp_path: Path) -> None:
    g = called(tmp_path)
    (line,) = lines(g, TOMAS)
    assert set(line) == set(api.ConferenceLine.__annotations__)
    assert line["key"] == CHARTER and line["called_by"] == "Norra"
    assert line["invited"] == ["Norra", "Sudland", "Ostmark"]
    assert line["text"] == TRADE.wording and line["clauses"] == []
    assert line["voting_day"] == (START + timedelta(days=CONF_DAYS)).isoformat()
    assert line["called"] == START.isoformat() and line["public"] is False
    assert line["vote"] is None and line["can_vote"] is True
    assert line["result"] is None and line["votes"] == [] and line["agreement"] is None


def test_a_seat_not_invited_sees_no_private_conference(tmp_path: Path) -> None:
    g = called(tmp_path, invited=(NORRA, SUDLAND))
    assert lines(g, OLAF) == []
    assert vote_items(g, OLAF) == []
    assert [c["key"] for c in lines(g, TOMAS)] == [CHARTER]


def test_with_the_rule_off_the_block_is_none(tmp_path: Path) -> None:
    g = Game(world(tmp_path, rules=("holders", "agreements")), "ilse", "tomas", "olaf")
    g.open()
    assert block(g, ILSE) is None


def test_a_binding_texts_clauses_are_shown_in_the_rules_words(tmp_path: Path) -> None:
    g = called(tmp_path, binding_text(SUDLAND))
    (line,) = lines(g, ILSE)
    (shown,) = line["clauses"]
    assert set(shown) == set(api.TermClause.__annotations__)
    assert shown["checked"] is True and "Sudland" in shown["text"]


def test_the_seat_sees_its_own_vote_and_no_other_before_the_tally(tmp_path: Path) -> None:
    g = called(tmp_path)
    g.vote(ILSE, Vote.FOR)
    g.vote(TOMAS, Vote.AGAINST)
    assert lines(g, ILSE)[0]["vote"] == "for"
    assert lines(g, TOMAS)[0]["vote"] == "against"
    theirs = lines(g, OLAF)[0]
    assert theirs["vote"] is None and theirs["votes"] == [] and theirs["result"] is None
    assert "against" not in json.dumps(block(g, OLAF)) and "for" not in json.dumps(theirs["votes"])


def test_a_vote_sealed_in_an_earlier_wake_can_no_longer_be_given(tmp_path: Path) -> None:
    g = called(tmp_path)
    g.vote(TOMAS, Vote.AGAINST)
    g.close()
    g.tick(day(1))
    g.open()
    line = lines(g, TOMAS)[0]
    assert line["vote"] == "against" and line["can_vote"] is False
    assert lines(g, ILSE)[0]["can_vote"] is True


def test_after_the_tally_the_block_gives_the_result_and_each_nations_vote(
    tmp_path: Path,
) -> None:
    g = called(tmp_path)
    g.vote(ILSE, Vote.FOR)
    g.vote(OLAF, Vote.FOR)
    run_until_tallied(g)  # Tomas never sits
    conf = g.state.conferences.held[CHARTER]
    assert conf.tally is not None
    for s in (ILSE, TOMAS, OLAF):
        (line,) = lines(g, s)
        assert line["result"] == "agreement" and line["can_vote"] is False
        assert line["tallied"] == conf.tally.on.isoformat()
        assert line["votes"] == [
            {"nation": "Norra", "vote": "for"},
            {"nation": "Sudland", "vote": "abstain"},
            {"nation": "Ostmark", "vote": "for"},
        ]
        assert line["agreement"] == conf.tally.agreement_id
    assert lines(g, TOMAS)[0]["vote"] is None  # his own: no vote of his was sealed


# --- Fog: no other seat's vote, and no mark of the aide, before or after the tally ----


def _twins(tmp_path: Path, first: Vote | None, second: Vote | None) -> tuple[Game, Game]:
    def played(tomas: Vote | None, sub: str) -> Game:
        here = tmp_path / sub
        here.mkdir()
        g = called(here)
        g.vote(ILSE, Vote.FOR)
        if tomas is not None:
            g.vote(TOMAS, tomas)
        return g

    return played(first, "a"), played(second, "b")


def _same_to_others(a: Game, b: Game) -> None:
    for s in (ILSE, OLAF):
        assert seen(a, s) == seen(b, s), s


def test_twin_games_differing_in_another_seats_vote_read_the_same_until_the_tally(
    tmp_path: Path,
) -> None:
    a, b = _twins(tmp_path, Vote.FOR, Vote.AGAINST)
    _same_to_others(a, b)
    for g in (a, b):
        g.close()
        g.tick(day(1))
        g.open()
    _same_to_others(a, b)
    for g in (a, b):
        g.close()
        g.tick(day(2))
        g.open()
    _same_to_others(a, b)
    assert a.state.conferences.held[CHARTER].tally is None


def test_an_absent_seat_reads_to_the_others_as_one_that_sealed_the_same_vote(
    tmp_path: Path,
) -> None:
    # Tomas never sits, so the aide abstains for him; in the twin he seals an abstention.
    # Before and after the tally, nothing any other seat is sent tells them apart.
    a, b = _twins(tmp_path, None, Vote.ABSTAIN)
    _same_to_others(a, b)
    for g in (a, b):
        run_until_tallied(g)
        assert g.state.conferences.held[CHARTER].tally is not None
    _same_to_others(a, b)
    assert "aide" not in json.dumps(block(a, ILSE))


# --- Rule 4: the vote is an agenda item due on the voting day, in the notice ----------


def test_an_invited_seat_has_a_vote_item_due_on_the_voting_day(tmp_path: Path) -> None:
    g = called(tmp_path)
    voting = g.state.conferences.held[CHARTER].voting_day
    for s in (ILSE, TOMAS, OLAF):
        (item,) = vote_items(g, s)
        assert item["id"] == CHARTER
        assert item["deadline"] == f"{voting.day} {voting:%B %Y}"
        assert item["issuer"] == "Norra" and TRADE.wording in item["text"]
        assert item["cause"] is None


def test_the_vote_item_shows_the_seat_its_own_vote_alone(tmp_path: Path) -> None:
    g = called(tmp_path)
    g.vote(TOMAS, Vote.AGAINST)
    (mine,) = vote_items(g, TOMAS)
    assert mine["cause"] is not None and "against" in mine["cause"]
    assert vote_items(g, ILSE)[0]["cause"] is None


def test_the_vote_item_goes_once_the_conference_has_voted(tmp_path: Path) -> None:
    g = called(tmp_path)
    run_until_tallied(g)
    assert vote_items(g, ILSE) == []
    assert [m for m in agenda_api.due_matters(g.state, ILSE) if m.kind == "vote"] == []


def test_the_notice_lists_the_vote_and_never_the_vote_filed(tmp_path: Path) -> None:
    g = called(tmp_path)
    (matter,) = [m for m in agenda_api.due_matters(g.state, TOMAS) if m.kind == "vote"]
    assert matter.subject == CHARTER
    before = notice_text(g, TOMAS)
    assert TRADE.wording in before
    g.vote(TOMAS, Vote.AGAINST)
    assert notice_text(g, TOMAS) == before


def test_votes_are_registered_as_a_due_kind() -> None:
    assert "vote" in agenda_api.DUE_KINDS


# --- The fixture -----------------------------------------------------------------------


def test_the_seat_fixture_carries_the_conferences_block() -> None:
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())
    shown = fixture["conferences"]
    assert set(shown) == set(api.ConferencesBlock.__annotations__)
    results = [c["result"] for c in shown["conferences"]]
    assert None in results and any(r is not None for r in results)


# --- Rules 1, 2 and 5 through the server ---------------------------------------------


@pytest.fixture
def trio(web: Web, tmp_path: Path) -> Iterator[tuple[Realism, Client, Client, Client]]:  # noqa: F811
    world(tmp_path)
    game_ = Realism(web, str(tmp_path / "world.yaml"))
    ada = game_.seat("ada", "ilse")
    bea = game_.seat("bea", "tomas")
    cy = game_.seat("cyd", "olaf")
    make_host(game_, ada)
    begin(game_)
    yield game_, ada, bea, cy


def _call(game_: Realism, ada: Client, **extra: Any) -> dict[str, Any]:
    body = {
        "key": CHARTER,
        "text": "Free trade on the gulf.",
        "invited": [game_.ids["sudland"], game_.ids["ostmark"]],
        "voting_day": (START + timedelta(days=CONF_DAYS + 1)).isoformat(),
        "public": False,
    } | extra
    status, out = post(ada, "conference-call", **body)
    assert status == 200, out
    return out


def test_the_call_action_calls_the_conference(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, ada, bea, _ = trio
    out = _call(game_, ada)
    assert not out["refused"], out
    conf = state_of(game_).conferences.held[CHARTER]
    assert [str(n) for n in conf.invited] == [
        game_.ids["norra"],
        game_.ids["sudland"],
        game_.ids["ostmark"],
    ]
    assert conf.voting_day == START + timedelta(days=CONF_DAYS + 1)
    assert [c["key"] for c in realism_of(bea)["conferences"]["conferences"]] == [CHARTER]
    again = _call(game_, ada)
    assert again["refused"]  # the name is taken


def test_a_call_with_an_early_voting_day_is_refused(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, ada, _, _ = trio
    out = _call(game_, ada, voting_day=(START + timedelta(days=1)).isoformat())
    assert out["refused"] and "at least" in out["reply"]
    assert state_of(game_).conferences.held == {}


def test_the_vote_action_seals_for_against_and_abstain_and_a_later_one_replaces(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, ada, bea, cy = trio
    _call(game_, ada)
    for choice in ("for", "against", "abstain"):
        status, out = post(bea, "conference-vote", conference=CHARTER, vote=choice)
        assert status == 200 and not out["refused"], out
        ballot = state_of(game_).conferences.votes[CHARTER]
        assert [b.vote.value for b in ballot.values()] == [choice]
    assert realism_of(bea)["conferences"]["conferences"][0]["vote"] == "abstain"
    assert realism_of(cy)["conferences"]["conferences"][0]["vote"] is None
    status, out = post(bea, "conference-vote", conference=CHARTER, vote="maybe")
    assert out["refused"]


def test_a_vote_after_the_seats_commit_is_held_for_the_next_wake(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, ada, bea, _ = trio
    _call(game_, ada)
    status, out = post(bea, "commit")
    assert status == 200 and not out["refused"], out
    status, out = post(bea, "conference-vote", conference=CHARTER, vote="for")
    assert status == 200 and not out["refused"] and "held" in out, out
    assert CHARTER not in state_of(game_).conferences.votes
