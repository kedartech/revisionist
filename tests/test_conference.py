"""The conference: seats vote on a text, votes sealed ahead (CNF).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``agreements`` and
``conference`` on, Ostmark (its regent Olaf) at peace with both, a fourth power Vesta that
nobody plays, and a second Norra leader, Inge, for a nation with two seats. Wakes are
opened and closed by hand; each tick advances the date to its last day and walks the days
as the realism tick does, so the walk sees the wake that has just closed. A seat calls a
conference and seals a vote with the engine's actions (``conference.call``,
``conference.vote``), each landed with the scope the web lands it with.
"""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, replay
from revisionist.core.ids import EntityId, EventId, SeatId, derived_id
from revisionist.core.ontology import Controller
from revisionist.core.project import project
from revisionist.core.realism import agreement, conference
from revisionist.core.realism.agreement import Agreement, ClauseStatus
from revisionist.core.realism.conference import (
    CONF_DAYS,
    Conference,
    ConferenceText,
    Outcome,
    Vote,
)
from revisionist.core.realism.effect import AgreementClause, ClauseType, Deal
from revisionist.core.visibility import PUBLIC, Scope, private_to
from revisionist.core.world import WorldFile
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick
from revisionist.engine import orders_reader as orr
from revisionist.engine.llm import Reply, Request
from revisionist.engine.store import MemoryStore, load_state
from tests.test_adjacency_moves import START, Logged, entity, seat, toy
from tests.test_territory_model import CAMPAIGN, refused

World = dict[str, Any]
NORRA, SUDLAND, OSTMARK, VESTA = (entity(k) for k in ("norra", "sudland", "ostmark", "vesta"))
ILSE, TOMAS, OLAF, INGE = (seat(p) for p in ("ilse", "tomas", "olaf", "inge"))
THREE = (NORRA, SUDLAND, OSTMARK)
DEADLINE = datetime(1900, 1, 1, tzinfo=UTC)
NAME = "charter"
"""The name Ilse calls the conference by, and the key of the world's scheduled one."""
CHARTER = conference.call_key(CAMPAIGN, ILSE, NAME)
"""The key Ilse's call of ``NAME`` is filed under."""


def day(n: int) -> date:
    return START + timedelta(days=n)


def powers(w: World) -> None:
    """Ostmark with a playable regent, Vesta with nobody, a second Norra leader, the topic
    of trade, and Olaf's card wanting trade and holding to neutrality."""
    w["entities"] += [
        {"key": "ostmark", "kind": "polity", "name": "Ostmark"},
        {"key": "olaf", "kind": "person", "name": "Olaf Strand", "parent": "ostmark"},
        {"key": "vesta", "kind": "polity", "name": "Vesta"},
        {"key": "inge", "kind": "person", "name": "Inge Holm", "parent": "norra"},
    ]
    w["topics"] = [
        {"key": "trade", "name": "Free trade", "words": ["trade", "tariffs"]},
        {"key": "neutrality", "name": "Neutrality", "words": ["neutral", "neutrality"]},
    ]
    for person, office, nation, wants, holds in (
        ("olaf", "Regent of Ostmark", "ostmark", ["trade"], ["neutrality"]),
        ("inge", "Marshal of Norra", "norra", [], []),
    ):
        w["cards"].append(
            {
                "person": person,
                "office": office,
                "playable": True,
                "principals": [nation],
                "horizon_days": 14,
                "wants": wants,
                "holds_to": holds,
            }
        )
        w["roster"].append(
            {"entity": person, "pitch": f"The {office}.", "reach": "Home.", "composite": True}
        )


def ruled(*rules: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = ["territories", *rules]

    return change


def world(tmp: Path, *changes: Callable[[World], None], rules: Sequence[str] = ()) -> WorldFile:
    on = rules or ("holders", "agreements", "conference")
    return toy(tmp, powers, ruled(*on), *changes)


class Game(Logged):
    """A logged game whose events can carry the scope the engine lands them with."""

    def land(self, payload: ev.Payload, scope: Scope = PUBLIC) -> None:
        e = ev.Event(
            event_id=EventId(derived_id(CAMPAIGN, "cnf-test", self.state.last_seq + 1)),
            campaign_id=CAMPAIGN,
            seq=self.state.last_seq + 1,
            tick=0,
            scope=scope,
            payload=payload,
            versions=cmp.versions(),
        )
        self.state = replay([e], initial=self.state)
        self.log.append(e)

    def open(self) -> int:
        w = self.state.wake
        n = 0 if w is None else w.number + 1
        self.land(ev.WakeOpened(wake=n, deadline=DEADLINE))
        return n

    def close(self) -> None:
        assert self.state.wake is not None
        self.land(ev.WakeClosed(wake=self.state.wake.number))

    def tick(self, last: date) -> list[ev.Event]:
        """The date moves to ``last`` and the days since are walked, as a realism tick."""
        before = self.state.in_world_date
        assert before is not None
        self.land(ev.DateAdvanced(to=last))
        return self.walk(before + timedelta(days=1), last)

    def call(
        self,
        by: SeatId = ILSE,
        invited: Sequence[EntityId] = THREE,
        text: ConferenceText | None = None,
        voting_day: date | None = None,
        public: bool = False,
        key: str = NAME,
    ) -> Conference:
        today = self.state.in_world_date
        assert today is not None
        called = conference.call(
            self.state,
            by,
            key,
            tuple(invited),
            text or ConferenceText(wording="A charter for the gulf."),
            voting_day or today + timedelta(days=CONF_DAYS),
            public,
        )
        assert isinstance(called, ev.ConferenceCalled)
        self.land(called, conference.scope(self.state, called.conference))
        return self.state.conferences.held[called.conference.key]

    def vote(self, by: SeatId, choice: Vote, key: str = CHARTER) -> None:
        self.land(conference.vote(self.state, by, key, choice), private_to(by))


def game(tmp: Path, *changes: Callable[[World], None], people: Sequence[str] = ()) -> Game:
    return Game(world(tmp, *changes), *(people or ("ilse", "tomas", "olaf")))


def run_until_tallied(g: Game, *, wakes: int = 3, days: int = 4) -> list[ev.Event]:
    """Close the open wake, tick ``days`` on, and open the next, until the tally (at
    most ``wakes`` closes). Returns every walked event."""
    out: list[ev.Event] = []
    for _ in range(wakes):
        g.close()
        today = g.state.in_world_date
        assert today is not None
        out += g.tick(today + timedelta(days=days))
        if any(c.tally is not None for c in g.state.conferences.held.values()):
            return out
        g.open()
    return out


def of(out: Sequence[ev.Event], kind: type) -> list[Any]:
    return [e.payload for e in out if isinstance(e.payload, kind)]


def tallied(g: Game, key: str = CHARTER) -> conference.Tally:
    found = g.state.conferences.held[key].tally
    assert found is not None
    return found


def counted(g: Game, key: str = CHARTER) -> dict[EntityId, Vote]:
    return {v.nation: v.vote for v in tallied(g, key).votes}


def binding_text(*binds: EntityId) -> ConferenceText:
    return ConferenceText(
        wording="No war in the gulf.",
        clauses=tuple(
            AgreementClause(type=ClauseType.NO_WAR, binds=b, nation=VESTA) for b in binds
        ),
    )


def made(g: Game) -> list[Agreement]:
    return list(g.state.agreements.made.values())


# --- Rule 1: a caller, the invited, a text and a voting day two wakes on ---------------


def test_a_seat_calls_a_conference_with_the_invited_a_text_and_a_voting_day(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.open()
    conf = g.call(text=ConferenceText(wording="Free trade on the gulf, and no tariffs."))
    assert conf.caller == NORRA and conf.invited == THREE
    assert conf.voting_day == START + timedelta(days=CONF_DAYS)
    assert conf.text.topics == ("trade",)
    assert conf.tally is None


def test_a_voting_day_under_conf_days_and_an_uninvited_caller_are_refused(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.open()
    text = ConferenceText(wording="A charter.")
    early = conference.call_refusal(
        g.state, ILSE, CHARTER, THREE, text, START + timedelta(days=CONF_DAYS - 1)
    )
    assert "at least" in early
    outside = conference.call_refusal(g.state, ILSE, CHARTER, (SUDLAND, OSTMARK), text, day(9))
    assert outside == "Your own nation must be invited."
    nobody = conference.call_refusal(g.state, ILSE, CHARTER, (NORRA, VESTA), text, day(9))
    assert nobody == "No one answers for Vesta."
    with pytest.raises(ValueError):
        Conference(
            key="x",
            caller=NORRA,
            invited=THREE,
            text=text,
            opens=START,
            voting_day=day(1),
            tally_wake=2,
        )


def test_the_tally_waits_for_two_wake_openings_after_the_call(tmp_path: Path) -> None:
    # The voting day falls in the first tick after the call; the tally waits for the
    # second wake to open and close after it.
    g = game(tmp_path)
    g.open()  # wake 0: the call
    g.call(voting_day=day(CONF_DAYS))
    g.close()
    first = g.tick(day(8))  # past the voting day, before wake 1
    assert of(first, ev.ConferenceTallied) == []
    g.open()  # wake 1
    g.close()
    second = g.tick(day(12))
    assert of(second, ev.ConferenceTallied) == [], "a one-wake conference"
    g.open()  # wake 2
    g.close()
    third = g.tick(day(16))
    (done,) = of(third, ev.ConferenceTallied)
    assert done.tally.on == day(13)


def test_with_the_rule_off_nothing_is_called_or_walked(tmp_path: Path) -> None:
    g = Game(world(tmp_path, rules=("holders", "agreements")), "ilse", "tomas", "olaf")
    g.open()
    why = conference.call_refusal(
        g.state, ILSE, CHARTER, THREE, ConferenceText(wording="x"), day(9)
    )
    assert why == conference.NOT_ON
    assert conference.vote_refusal(g.state, ILSE, CHARTER) == conference.NOT_ON
    assert conference.walk(g.state, day(5)) == []


# --- Rule 2: one sealed vote, seen by the voter alone until the tally -----------------


def test_a_vote_is_in_the_voters_view_alone_until_the_tally(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    g.call()
    g.vote(TOMAS, Vote.AGAINST)
    assert project(g.state, TOMAS).conferences.votes[CHARTER][TOMAS].vote is Vote.AGAINST
    for other in (ILSE, OLAF):
        assert CHARTER not in project(g.state, other).conferences.votes, "a vote seen early"
    feed = catchup.feed(g.state, g.log, ILSE, 0, 9)
    assert not [f for f in feed if f.event.kind == "vote_sealed"]
    assert realism_tick._scope_of(  # the engine seals it to the voter
        g.state, ev.VoteSealed(conference=CHARTER, seat_id=TOMAS, vote=Vote.FOR, wake=0)
    ) == private_to(TOMAS)


def test_a_later_vote_in_the_same_wake_replaces_the_earlier_and_a_later_wake_cannot(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.open()
    g.call()
    g.vote(OLAF, Vote.FOR)
    g.vote(OLAF, Vote.AGAINST)
    assert g.state.conferences.votes[CHARTER][OLAF].vote is Vote.AGAINST
    g.close()
    g.tick(day(2))
    g.open()
    assert "already sealed" in conference.vote_refusal(g.state, OLAF, CHARTER)
    with pytest.raises(FoldError):
        g.land(ev.VoteSealed(conference=CHARTER, seat_id=OLAF, vote=Vote.FOR, wake=1))


def test_an_uninvited_seat_cannot_vote(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    g.call(invited=(NORRA, OSTMARK), public=True)
    assert conference.vote_refusal(g.state, TOMAS, CHARTER) == conference.NOT_INVITED


# --- Rule 3: the aide's fallback --------------------------------------------------------


def test_an_absent_seat_whose_card_leans_for_a_binding_text_abstains_and_is_not_bound(
    tmp_path: Path,
) -> None:
    # Olaf's card wants trade, and the text is about trade; but it binds Ostmark, so the
    # aide abstains and no obligation falls on Ostmark.
    g = game(tmp_path)
    g.open()
    text = binding_text(NORRA, SUDLAND, OSTMARK).model_copy(
        update={"wording": "Free trade and no war in the gulf."}
    )
    g.call(text=text)
    assert g.state.conferences.held[CHARTER].text.topics == ("trade",)
    g.vote(ILSE, Vote.FOR)
    g.vote(TOMAS, Vote.FOR)
    run_until_tallied(g)
    assert counted(g)[OSTMARK] is Vote.ABSTAIN, "the aide voted for a binding text"
    assert tallied(g).outcome is Outcome.AGREEMENT
    (x,) = made(g)
    assert x.parties == (NORRA, SUDLAND)
    assert OSTMARK not in {c.binds for c in x.clauses}


def test_on_a_nonbinding_text_the_aide_votes_as_the_card_leans(tmp_path: Path) -> None:
    for wording, leaning in (
        ("Free trade on the gulf.", Vote.FOR),
        ("Neutrality for the gulf.", Vote.AGAINST),
        ("Free trade and neutrality.", Vote.ABSTAIN),
        ("A charter for the gulf.", Vote.ABSTAIN),
    ):
        g = game(tmp_path)
        g.open()
        g.call(text=ConferenceText(wording=wording))
        run_until_tallied(g)
        assert counted(g)[OSTMARK] is leaning, wording


def test_the_aide_never_replaces_a_vote_the_player_filed(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    g.call(text=ConferenceText(wording="Free trade on the gulf."))
    g.vote(OLAF, Vote.AGAINST)  # the card leans for; the player's vote stands
    run_until_tallied(g)
    assert counted(g)[OSTMARK] is Vote.AGAINST, "the aide overwrote a vote"


def test_a_tally_with_one_seat_absent_for_every_wake(tmp_path: Path) -> None:
    # Tomas never sits: no vote is filed for him in any wake, the tally still runs on
    # time, and Sudland counts as an abstention (his card leans on nothing).
    g = game(tmp_path)
    g.open()
    g.call()
    g.vote(ILSE, Vote.FOR)
    g.vote(OLAF, Vote.FOR)
    run_until_tallied(g)
    assert counted(g) == {NORRA: Vote.FOR, SUDLAND: Vote.ABSTAIN, OSTMARK: Vote.FOR}
    assert tallied(g).outcome is Outcome.AGREEMENT
    (x,) = made(g)
    assert x.parties == (NORRA, OSTMARK)


def test_the_tally_reads_nothing_of_who_runs_a_seat(tmp_path: Path) -> None:
    # The same tally whether the regent's seat is a person's or the aide's (invariant 5).
    g = game(tmp_path)
    g.open()
    conf = g.call(text=ConferenceText(wording="Free trade on the gulf."))
    seats = dict(g.state.seats)
    for controller in Controller:
        seats[OLAF] = seats[OLAF].model_copy(update={"controller": controller})
        run = g.state.model_copy(update={"seats": seats})
        assert conference.tally(run, conf, day(9)) == conference.tally(g.state, conf, day(9))


# --- Rule 4: nations, not seats; quorum; passing --------------------------------------


def test_one_for_and_the_rest_abstaining_passes_as_a_resolution(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    g.call(text=binding_text(NORRA, SUDLAND))
    g.vote(ILSE, Vote.FOR)
    g.vote(TOMAS, Vote.ABSTAIN)
    g.vote(OLAF, Vote.ABSTAIN)
    run_until_tallied(g)
    assert tallied(g).outcome is Outcome.RESOLUTION
    assert tallied(g).agreement_id is None
    assert made(g) == [], "a resolution binds no one"


def test_two_supporting_seats_of_one_nation_count_once(tmp_path: Path) -> None:
    g = game(tmp_path, people=("ilse", "tomas", "olaf", "inge"))
    g.open()
    g.call(text=binding_text(NORRA, SUDLAND, OSTMARK))
    g.vote(ILSE, Vote.FOR)
    g.vote(INGE, Vote.FOR)
    g.vote(TOMAS, Vote.AGAINST)
    g.vote(OLAF, Vote.ABSTAIN)
    run_until_tallied(g)
    assert counted(g) == {NORRA: Vote.FOR, SUDLAND: Vote.AGAINST, OSTMARK: Vote.ABSTAIN}
    # one nation for, one against: not passed (parties counted by seat would pass it)
    assert tallied(g).outcome is Outcome.FAILED
    assert made(g) == []


def test_a_nations_seats_that_differ_make_its_abstention(tmp_path: Path) -> None:
    g = game(tmp_path, people=("ilse", "tomas", "olaf", "inge"))
    g.open()
    g.call()
    g.vote(ILSE, Vote.FOR)
    g.vote(INGE, Vote.AGAINST)
    g.vote(TOMAS, Vote.FOR)
    g.vote(OLAF, Vote.FOR)
    run_until_tallied(g)
    assert counted(g)[NORRA] is Vote.ABSTAIN
    (x,) = made(g)
    assert x.parties == (SUDLAND, OSTMARK)


def test_no_quorum_cancels_the_conference(tmp_path: Path) -> None:
    # A world's conference invites Norra, Ostmark and Vesta; nobody holds Ostmark or
    # Vesta, so one of three nations has a vote.
    def scheduled(w: World) -> None:
        w["conferences"] = [
            {
                "key": NAME,
                "caller": "norra",
                "invited": ["norra", "ostmark", "vesta"],
                "wording": "A charter for the gulf.",
                "opens": "1900-04-03",
                "voting_day": "1900-04-08",
                "gap": True,
            }
        ]

    g = game(tmp_path, scheduled, people=("ilse", "tomas"))
    g.open()  # nothing to vote on before it opens
    assert conference.vote_refusal(g.state, ILSE, NAME) == conference.NO_SUCH
    out = run_until_tallied(g)
    assert tallied(g, NAME).outcome is Outcome.CANCELLED
    assert counted(g, NAME) == {NORRA: Vote.ABSTAIN}
    assert of(out, ev.AgreementMade) == []


def test_quorum_counts_votes_not_people_online(tmp_path: Path) -> None:
    # Nobody sits in any wake and no vote is sealed: the fallback gives every invited
    # nation a vote, so quorum holds and the text fails (no nation for).
    g = game(tmp_path)
    g.open()
    g.call()
    run_until_tallied(g)
    assert len(tallied(g).votes) == 3
    assert tallied(g).outcome is Outcome.FAILED


def test_a_unanimous_text_passes_only_with_every_nation_for(tmp_path: Path) -> None:
    for olaf, outcome in ((Vote.ABSTAIN, Outcome.FAILED), (Vote.FOR, Outcome.AGREEMENT)):
        g = game(tmp_path)
        g.open()
        g.call(text=ConferenceText(wording="A charter.", unanimous=True))
        g.vote(ILSE, Vote.FOR)
        g.vote(TOMAS, Vote.FOR)
        g.vote(OLAF, olaf)
        run_until_tallied(g)
        assert tallied(g).outcome is outcome


# --- Rule 5: an agreement among the nations for --------------------------------------


def test_a_passed_text_binds_only_the_nations_that_voted_for(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    g.call(text=binding_text(NORRA, SUDLAND, OSTMARK))
    g.vote(ILSE, Vote.FOR)
    g.vote(TOMAS, Vote.AGAINST)
    g.vote(OLAF, Vote.FOR)
    out = run_until_tallied(g)
    assert tallied(g).outcome is Outcome.AGREEMENT
    (x,) = of(out, ev.AgreementMade)
    assert x.agreement.parties == (NORRA, OSTMARK)
    assert {c.binds for c in x.agreement.clauses} == {NORRA, OSTMARK}
    assert x.agreement.offer_id is None
    assert all(s is ClauseStatus.STANDING for s in x.agreement.statuses)


# --- Rule 6: papers to the invited, news when public ----------------------------------


def test_the_call_and_the_result_are_papers_to_every_invited_seat(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    conf = g.call(invited=(NORRA, OSTMARK))
    out = run_until_tallied(g)
    issued = {d.document.doc_id for d in of(out, ev.DocumentIssued)}
    for s in (ILSE, OLAF):
        assert conference.paper_id(g.state, conf, "call", s) in issued
        assert conference.paper_id(g.state, conf, "result", s) in issued
    assert conference.paper_id(g.state, conf, "call", TOMAS) not in issued
    assert of(out, ev.NewsReported) == [], "a private conference makes no news"
    assert CHARTER not in project(g.state, TOMAS).conferences.held


def test_a_public_conference_is_news_and_in_every_view(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    g.call(invited=(NORRA, OSTMARK), public=True)
    assert CHARTER in project(g.state, TOMAS).conferences.held
    out = run_until_tallied(g)
    heads = [n.news.headline for n in of(out, ev.NewsReported)]
    assert [h.split(":")[0] for h in heads] == ["Conference called", "Conference voted"]


def test_the_call_and_tally_reach_the_invited_through_catch_up(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    g.call(invited=(NORRA, OSTMARK))
    run_until_tallied(g)
    kinds = [f.event.kind for f in catchup.feed(g.state, g.log, OLAF, 0, 9)]
    assert "conference_called" in kinds and "conference_tallied" in kinds
    theirs = [f.event.kind for f in catchup.feed(g.state, g.log, TOMAS, 0, 9)]
    assert "conference_called" not in theirs and "conference_tallied" not in theirs


def test_twin_games_differing_in_one_pre_tally_vote_read_the_same_to_others(
    tmp_path: Path,
) -> None:
    def played(choice: Vote) -> Game:
        g = game(tmp_path)
        g.open()
        g.call()
        g.vote(ILSE, choice)
        g.close()
        g.tick(day(3))
        g.open()
        return g

    a, b = played(Vote.FOR), played(Vote.AGAINST)
    for s in (TOMAS, OLAF):
        assert project(a.state, s) == project(b.state, s)
        fa = [_seen(f) for f in catchup.feed(a.state, a.log, s, 0, 9)]
        fb = [_seen(f) for f in catchup.feed(b.state, b.log, s, 0, 9)]
        assert fa == fb


def _seen(f: catchup.SeatEvent) -> tuple[int, int, Any, Any]:
    """What a seat reads of a fed event: the walk's event ids are random, so left out."""
    return (f.wake, f.event.seq, f.event.scope, f.event.payload)


# --- Rule 7: a world schedules conferences --------------------------------------------


def scheduled_charter(w: World) -> None:
    w["conferences"] = [
        {
            "key": NAME,
            "caller": "norra",
            "invited": ["norra", "sudland", "ostmark"],
            "wording": "Free trade on the gulf.",
            "opens": "1900-04-05",
            "voting_day": "1900-04-10",
            "public": True,
            "gap": True,
        }
    ]


def test_a_worlds_conference_opens_on_its_date(tmp_path: Path) -> None:
    g = game(tmp_path, scheduled_charter)
    held = g.state.conferences.held[NAME]
    assert held.tally_wake is None and held.text.topics == ("trade",)
    assert NAME not in project(g.state, ILSE).conferences.held, "seen before it opens"
    g.open()
    g.close()
    out = g.tick(day(2))
    assert of(out, ev.ConferenceCalled) == []
    g.open()
    g.close()
    out = g.tick(day(5))
    (opened,) = of(out, ev.ConferenceCalled)
    assert opened.conference.tally_wake == 3
    assert NAME in project(g.state, TOMAS).conferences.held


def test_a_world_conference_is_checked(tmp_path: Path) -> None:
    def bad(w: World) -> None:
        scheduled_charter(w)
        w["conferences"][0]["voting_day"] = "1900-04-06"
        w["conferences"][0]["caller"] = "vesta"

    problems = refused(world(tmp_path, bad))
    assert any("votes less than" in p for p in problems)
    assert any("is not invited" in p for p in problems)
    off = refused(world(tmp_path, scheduled_charter, rules=("holders", "agreements")))
    assert "conferences: needs the conference rule" in off


# --- Rule 8 and AGR rule 6: vote clauses judged only from the tally --------------------


def in_force(g: Game, *clauses: AgreementClause) -> Agreement:
    x = Agreement(
        agreement_id=f"agr-{len(made(g))}",
        version=agreement.version(THREE, "", clauses),
        parties=(NORRA, SUDLAND),
        clauses=clauses,
        made=START,
        statuses=agreement.statuses(clauses),
    )
    g.add([ev.AgreementMade(agreement=x)])
    return g.state.agreements.made[x.agreement_id]


def vote_clause(binds: EntityId, present: bool = True, key: str = CHARTER) -> AgreementClause:
    return AgreementClause(type=ClauseType.VOTE, binds=binds, text=key, present=present)


def test_a_vote_clause_is_kept_or_broken_by_the_tally_only(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    g.call()
    x = in_force(g, vote_clause(NORRA), vote_clause(SUDLAND))
    g.vote(ILSE, Vote.FOR)
    g.vote(TOMAS, Vote.AGAINST)
    g.close()
    g.tick(day(8))
    assert g.state.agreements.made[x.agreement_id].statuses == (
        ClauseStatus.STANDING,
        ClauseStatus.STANDING,
    ), "a vote clause judged before the tally"
    g.open()
    run_until_tallied(g)
    after = g.state.agreements.made[x.agreement_id]
    assert after.statuses == (ClauseStatus.KEPT, ClauseStatus.BROKEN)


def test_a_vote_clause_on_a_conference_its_nation_is_not_invited_to_is_void(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.open()
    g.call(invited=(NORRA, OSTMARK))
    x = in_force(g, vote_clause(NORRA), vote_clause(SUDLAND))
    g.vote(ILSE, Vote.FOR)
    out = run_until_tallied(g)
    after = g.state.agreements.made[x.agreement_id]
    assert after.statuses == (ClauseStatus.KEPT, ClauseStatus.VOID)
    assert of(out, ev.GroupMoved) == []


def test_a_vote_clause_on_a_cancelled_conference_is_void_and_costs_nothing(
    tmp_path: Path,
) -> None:
    def scheduled(w: World) -> None:
        scheduled_charter(w)
        w["conferences"][0]["invited"] = ["norra", "ostmark", "vesta"]

    g = game(tmp_path, scheduled, people=("ilse", "tomas"))
    x = in_force(g, vote_clause(NORRA, key=NAME))
    before = dict(g.state.relationships)
    g.open()
    run_until_tallied(g)
    assert tallied(g, NAME).outcome is Outcome.CANCELLED
    assert g.state.agreements.made[x.agreement_id].statuses == (ClauseStatus.VOID,)
    assert dict(g.state.relationships) == before


def test_an_offer_whose_vote_clause_falls_before_the_voting_day_is_refused(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.open()
    conf = g.call(voting_day=day(6))
    early = AgreementClause(
        type=ClauseType.VOTE, binds=SUDLAND, text=CHARTER, on=conf.voting_day - timedelta(1)
    )
    deal = Deal(counterparty=SUDLAND, parties=(NORRA, SUDLAND), wording="x", clauses=(early,))
    assert "voting day" in agreement.refusal(g.state, ILSE, deal)
    on_time = early.model_copy(update={"on": conf.voting_day})
    fine = deal.model_copy(update={"clauses": (on_time,)})
    assert agreement.refusal(g.state, ILSE, fine) == ""


# --- Refusals keep a conference out of view -------------------------------------------

PRIVATE = (NORRA, SUDLAND)
"""A conference of Norra and Sudland, which Olaf's Ostmark cannot see."""
CALLED = "A conference of that name has been called."


def test_a_vote_in_a_conference_the_seat_cannot_see_is_refused_as_one_that_does_not_exist(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.open()
    theirs = g.call(invited=PRIVATE)
    assert theirs.key not in project(g.state, OLAF).conferences.held
    held = conference.vote_refusal(g.state, OLAF, theirs.key)
    absent = conference.vote_refusal(g.state, OLAF, "no-such-conference")
    assert held == absent == conference.NO_SUCH


def test_a_call_under_the_name_of_a_conference_the_caller_cannot_see_is_called(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.open()
    theirs = g.call(invited=PRIVATE)
    text = ConferenceText(wording="A charter for the gulf.")
    assert conference.call_refusal(g.state, OLAF, NAME, (OSTMARK, NORRA), text, day(9)) == ""
    ours = g.call(by=OLAF, invited=(OSTMARK, NORRA))
    assert ours.key != theirs.key and ours.caller == OSTMARK
    assert g.state.conferences.held[theirs.key] == theirs


def test_a_call_under_a_world_conferences_name_does_not_read_as_a_hold_on_it(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, scheduled_charter)
    g.open()
    assert NAME not in project(g.state, ILSE).conferences.held
    text = ConferenceText(wording="A charter for the gulf.")
    assert conference.call_refusal(g.state, ILSE, NAME, THREE, text, day(9)) == ""
    mine = g.call()
    assert mine.key != NAME and g.state.conferences.held[NAME].tally_wake is None


def test_a_conference_the_seat_can_see_keeps_its_refusals(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    g.call(invited=(NORRA, OSTMARK), public=True)
    text = ConferenceText(wording="Again.")
    assert conference.call_refusal(g.state, ILSE, NAME, THREE, text, day(9)) == CALLED
    assert conference.vote_refusal(g.state, TOMAS, CHARTER) == conference.NOT_INVITED
    g.close()
    closed = conference.vote_refusal(g.state, OLAF, CHARTER)
    assert closed == "A vote is sealed while a wake is open."
    g.tick(day(1))
    g.open()
    run_until_tallied(g)
    g.open()
    assert conference.vote_refusal(g.state, OLAF, CHARTER) == "That conference has voted."


def test_a_call_under_an_opened_world_conferences_name_is_refused_as_before(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, scheduled_charter)
    for last in (day(2), day(5)):
        g.open()
        g.close()
        g.tick(last)
    g.open()
    assert NAME in project(g.state, TOMAS).conferences.held
    text = ConferenceText(wording="Again.")
    assert conference.call_refusal(g.state, TOMAS, NAME, THREE, text, day(12)) == CALLED


# --- A written vote, with written orders on ------------------------------------------


class Canned:
    """Answers with ``output``; keeps every request."""

    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.requests: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.requests.append(request)
        return Reply(self.output, request.model, 10, 10, 0, 0.0)


def written_vote(choice: str) -> dict[str, Any]:
    return {"asks": [], "reason": "", "vote": {"conference": CHARTER, "vote": choice}}


def test_a_written_vote_is_read_into_the_same_sealed_vote(tmp_path: Path) -> None:
    on = ("holders", "agreements", "conference", "written_orders")
    g = Game(world(tmp_path, rules=on), "ilse", "tomas", "olaf")
    g.open()
    g.call()
    canned = Canned(written_vote("against"))
    reading = orr.read_order(g.state, TOMAS, "", "", "Sudland votes no on the charter.", canned)
    assert reading.vote == (CHARTER, Vote.AGAINST) and reading.asks == ()
    assert '"vote"' in json.dumps(canned.requests[0].schema)
    store = MemoryStore()
    store.append_all(g.log)
    done = orr.file_order(store, CAMPAIGN, TOMAS, reading)
    assert done["refused"] is False
    (sealed,) = [e for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.VoteSealed)]
    assert sealed.scope == private_to(TOMAS)
    assert load_state(store, CAMPAIGN).conferences.votes[CHARTER][TOMAS].vote is Vote.AGAINST


def test_with_written_orders_off_the_reader_reads_no_vote(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    g.call()
    canned = Canned(written_vote("for"))
    reading = orr.read_order(g.state, TOMAS, "Varg", "", "Sudland votes for the charter.", canned)
    assert reading.vote is None and reading.asks == ()
    assert '"vote"' not in json.dumps(canned.requests[0].schema)
