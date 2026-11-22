"""The conference: seats vote on a text, votes sealed ahead (CNF).

A conference has a caller, the nations it invites, a text (its wording, its clauses and
the topics its words touch) and a voting day at least ``CONF_DAYS`` world days after the
call. A seat calls one by an action, as an answer is given; a world may schedule one that
opens on its date. Each invited seat may seal one vote, for, against or abstain, in any
wake before the tally; a later vote in the same wake replaces the earlier, there is no
withdraw, and nobody but the voter sees it before the tally.

The tally runs in the day walk on the voting day, or on the first day after it whose
walk follows the second wake opening after the call, so every seat has at least two
wakes to vote. A seat with no vote sealed by then is given the aide's fallback: it
abstains on a binding text (one whose passing would bind its nation), and on any other
votes as its leader's card leans on the text's topics, or abstains. The fallback is the
same whoever runs the seat, so nothing in the tally says who was present. An invited
nation no seat holds casts one vote by the same rule, read from the card of the person
the world gives as its head; with no head it has no vote.

``tally`` counts nations, not seats: a nation's vote is its seats' vote when they agree
and an abstention when they differ. Quorum is a majority of the invited nations with a
vote; without it the conference is cancelled. The text passes when the nations for
outnumber the nations against, or when every invited nation is for if the text says
unanimous. A passed text becomes an agreement among the distinct nations that voted for
it when there are at least two, keeping only the clauses that bind one of them; with
fewer it is a nonbinding resolution that binds no one. A vote clause of an agreement in
force is judged from the tally of its conference, and is void when that conference is
cancelled or does not invite the nation it binds. Every rule here acts only with
``conference`` (and ``agreements``) on.
"""

import re
from collections.abc import Sequence
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import DocumentId, EntityId, SeatId, derived_id
from revisionist.core.realism.effect import MAX_PARTIES, AgreementClause, ClauseType

if TYPE_CHECKING:
    from revisionist.core.events import Payload
    from revisionist.core.realism.agreement import Agreement
    from revisionist.core.state import State, _World
    from revisionist.core.visibility import Scope

CONF_DAYS = 4  # [proposed] plan, CNF Defaults
"""World days from the call to the earliest voting day."""
CONF_WAKES = 2
"""Wake openings after the call before the tally may run (rule 1)."""
MAX_INVITED = MAX_PARTIES
"""Nations one conference invites, as many as an agreement may name."""

NOT_ON = "Conferences are not part of this game."
NOT_INVITED = "Your nation is not invited to that conference."
NO_SUCH = "There is no such conference."


class Vote(StrEnum):
    FOR = "for"
    AGAINST = "against"
    ABSTAIN = "abstain"


class Outcome(StrEnum):
    AGREEMENT = "agreement"
    """Passed, with two or more nations for: an agreement among them."""
    RESOLUTION = "resolution"
    """Passed with fewer than two nations for: binds no one."""
    FAILED = "failed"
    CANCELLED = "cancelled"
    """No quorum at the tally."""


class ConferenceText(Model):
    """What a conference votes on: its wording, its clauses, the topics its words touch
    (by key, worked out when it is called) and whether only a unanimous vote passes it."""

    wording: str = Field(min_length=1, max_length=600)
    clauses: tuple[AgreementClause, ...] = Field(default=(), max_length=8)
    topics: tuple[Label, ...] = ()
    unanimous: bool = False


class NationVote(Model):
    """One invited nation's counted vote at the tally."""

    nation: EntityId
    vote: Vote


class Tally(Model):
    """A conference's result, on the day it was tallied."""

    on: date
    outcome: Outcome
    votes: tuple[NationVote, ...] = ()
    """Each invited nation with a vote, in the invited order."""
    agreement_id: Label | None = None
    """The agreement a passed text made; None for any other outcome."""


class Conference(Model):
    """A conference called or scheduled. ``key`` names it, and is the text a vote clause
    names. ``tally_wake``: the tally runs only in a day walk after that wake has opened;
    None for a world's conference that has not yet opened."""

    key: Label
    caller: EntityId
    """The calling nation."""
    invited: tuple[EntityId, ...] = Field(min_length=2, max_length=MAX_INVITED)
    text: ConferenceText
    opens: date
    """The day it is called: the day its call goes out."""
    voting_day: date
    tally_wake: int | None = Field(default=None, ge=0)
    public: bool = False
    tally: Tally | None = None

    late_fields: ClassVar[frozenset[str]] = frozenset({"tally"})

    @model_validator(mode="after")
    def _shape(self) -> "Conference":
        if len(set(self.invited)) != len(self.invited):
            raise ValueError("a conference invites each nation once")
        if self.voting_day < self.opens + timedelta(days=CONF_DAYS):
            raise ValueError(f"the voting day is at least {CONF_DAYS} days after the call")
        return self


class Ballot(Model):
    """A seat's sealed vote, and the wake it was sealed in."""

    vote: Vote
    wake: int = Field(ge=0)


class Conferences(Model):
    """Conferences and their sealed votes (CNF). A view holds the conferences its nation
    is invited to and every public one, from the day each opens, and its own votes only."""

    held: dict[Label, Conference] = Field(default_factory=dict)
    votes: dict[Label, dict[SeatId, Ballot]] = Field(default_factory=dict)


# --- reading --------------------------------------------------------------------------


def on(state: "_World") -> bool:
    """Whether conferences act in this game: ``conference`` and ``agreements`` on."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.CONFERENCE in rules and Rule.AGREEMENTS in rules


def _nation(state: "State", seat: SeatId) -> EntityId | None:
    from revisionist.core.realism.war import polity_of

    found = state.seats.get(seat)
    return None if found is None else polity_of(state, found.embodies)


def _wake(state: "State") -> int:
    """The number of the current or last wake; -1 before the first opens."""
    return state.wake.number if state.wake is not None else -1


def opened(conf: Conference, today: date | None) -> bool:
    """Called, or scheduled and its day come and gone through the walk."""
    return conf.tally_wake is not None and today is not None and conf.opens <= today


def binding(conf: Conference, nation: EntityId) -> bool:
    """Whether the text's passing would make an agreement with a clause binding
    ``nation``."""
    return any(c.binds == nation for c in conf.text.clauses)


def text_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def topics_of(state: "State", wording: str, clauses: Sequence[AgreementClause]) -> tuple[str, ...]:
    """The keys of the world's topics the text's words touch (``Topic.touched``), sorted."""
    said = text_words(" ".join([wording, *(c.text for c in clauses)]))
    return tuple(sorted(k for k, t in state.topics.items() if t.touched(None, (), said)))


def seen_by(state: "State", seat: SeatId) -> Conferences:
    """What ``seat`` sees: each opened conference its nation is invited to, and each
    opened public one; of the votes, its own only."""
    own = _nation(state, seat)
    today = state.in_world_date
    held = {
        k: c
        for k, c in state.conferences.held.items()
        if opened(c, today) and (c.public or (own is not None and own in c.invited))
    }
    votes = {
        k: {seat: b[seat]} for k, b in state.conferences.votes.items() if k in held and seat in b
    }
    return Conferences(held=held, votes=votes)


def scope(state: "State", conf: Conference) -> "Scope":
    """Public for a public conference once it opens; else sealed to the invited seats.
    Before it opens, sealed to a seat nobody holds."""
    from revisionist.core.realism.agreement import parties_scope
    from revisionist.core.visibility import PUBLIC, Scope, Visibility

    if not opened(conf, state.in_world_date):
        held = SeatId(derived_id(state.campaign_id, "engine-only", "conference"))
        return Scope(visibility=Visibility.RESTRICTED, known_by=frozenset({held}))
    return PUBLIC if conf.public else parties_scope(state, conf.invited)


# --- filing ---------------------------------------------------------------------------


def call_key(campaign_id: str, seat: SeatId, name: str) -> str:
    """The key a seat's call of ``name`` is filed under: its own, so no seat's call can
    take, or be refused for, the name of a conference it cannot see."""
    return derived_id(campaign_id, "conference-call-key", seat, name)


def call_refusal(
    state: "State",
    seat: SeatId,
    key: str,
    invited: Sequence[EntityId],
    text: ConferenceText,
    voting_day: date,
) -> str:
    """Why a seat may not call this conference under the name ``key``; empty when it may.
    The name is taken only by the seat's own call of it, or by a conference it sees."""
    from revisionist.core.ontology import EntityKind
    from revisionist.core.realism import agreement

    if not on(state):
        return NOT_ON
    today = state.in_world_date
    if today is None or state.wake is None or state.wake.closed:
        return "A conference is called while a wake is open."
    own = _nation(state, seat)
    if own is None or own not in invited:
        return "Your own nation must be invited."
    if call_key(state.campaign_id, seat, key) in state.conferences.held or (
        key in seen_by(state, seat).held
    ):
        return "A conference of that name has been called."
    if len(set(invited)) != len(invited) or len(invited) < 2:
        return "A conference invites two or more nations, each once."
    for nation in invited:
        found = state.entities.get(nation)
        if found is None or found.kind is not EntityKind.POLITY:
            return "Every nation invited is a nation."
        if agreement.speaker(state, nation) is None:
            return f"No one answers for {found.name}."
    for clause in text.clauses:
        if clause.binds not in invited:
            return "Each clause binds a nation invited."
        if clause.type is ClauseType.VOTE:
            return "A conference's text holds no vote clause."
        why = agreement.clause_refusal(state, clause)
        if why:
            return why
    if voting_day < today + timedelta(days=CONF_DAYS):
        return f"The voting day is at least {CONF_DAYS} days after the call."
    return ""


def call(
    state: "State",
    seat: SeatId,
    key: str,
    invited: Sequence[EntityId],
    text: ConferenceText,
    voting_day: date,
    public: bool,
) -> "Payload":
    """The ``conference_called`` a seat's call of ``key`` lands, filed under
    ``call_key``; raises ``ValueError`` when refused."""
    from revisionist.core import events as ev

    why = call_refusal(state, seat, key, invited, text, voting_day)
    if why:
        raise ValueError(why)
    own = _nation(state, seat)
    assert own is not None and state.in_world_date is not None
    topics = topics_of(state, text.wording, text.clauses)
    conf = Conference(
        key=call_key(state.campaign_id, seat, key),
        caller=own,
        invited=tuple(invited),
        text=text.model_copy(update={"topics": topics}),
        opens=state.in_world_date,
        voting_day=voting_day,
        tally_wake=_tally_wake(state),
        public=public,
    )
    return ev.ConferenceCalled(conference=conf)


def _tally_wake(state: "State") -> int:
    """Called in wake N's sitting, or opened in the walk after wake N closed, the tally
    waits for openings N + 1 and N + 2: it runs in the walk after wake N + 2."""
    return max(0, _wake(state) + CONF_WAKES)


def scheduled(
    key: str,
    caller: EntityId,
    invited: Sequence[EntityId],
    text: ConferenceText,
    opens: date,
    voting_day: date,
    public: bool,
) -> Conference:
    """A world's scheduled conference (rule 7), not yet open: the day walk opens it on
    ``opens``, when its tally wake is set."""
    return Conference(
        key=key,
        caller=caller,
        invited=tuple(invited),
        text=text,
        opens=opens,
        voting_day=voting_day,
        public=public,
    )


def vote_refusal(state: "State", seat: SeatId, key: str) -> str:
    """Why ``seat`` may not seal a vote in conference ``key`` now; empty when it may.
    A conference the seat does not see is refused as one that does not exist."""
    if not on(state):
        return NOT_ON
    conf = seen_by(state, seat).held.get(key)
    if conf is None:
        return NO_SUCH
    own = _nation(state, seat)
    if own is None or own not in conf.invited:
        return NOT_INVITED
    if conf.tally is not None:
        return "That conference has voted."
    if state.wake is None or state.wake.closed:
        return "A vote is sealed while a wake is open."
    held = state.conferences.votes.get(key, {}).get(seat)
    if held is not None and held.wake != state.wake.number:
        return "Your vote in that conference is already sealed."
    return ""


def vote(state: "State", seat: SeatId, key: str, choice: Vote) -> "Payload":
    """The ``vote_sealed`` a seat's vote lands; raises ``ValueError`` when refused."""
    from revisionist.core import events as ev

    why = vote_refusal(state, seat, key)
    if why:
        raise ValueError(why)
    assert state.wake is not None
    return ev.VoteSealed(conference=key, seat_id=seat, vote=choice, wake=state.wake.number)


# --- the tally ------------------------------------------------------------------------


def fallback(state: "State", conf: Conference, seat: SeatId) -> Vote:
    """The aide's vote for a seat with none sealed (rule 3): the lean of the seat's own
    card. It never reads who runs the seat."""
    nation = _nation(state, seat)
    if nation is None:
        return Vote.ABSTAIN
    return lean(state, conf, nation, state.seats[seat].embodies)


def lean(state: "State", conf: Conference, nation: EntityId, person: EntityId) -> Vote:
    """How ``person``'s card votes for ``nation``: abstain on a text binding the nation;
    else for when the text touches only topics the card wants, against when only topics
    it holds to, and abstain otherwise."""
    if binding(conf, nation):
        return Vote.ABSTAIN
    card = state.cards.get(person)
    touched = set(conf.text.topics)
    if card is None or not touched:
        return Vote.ABSTAIN
    wants, holds = set(card.wants), set(card.holds_to)
    if touched <= wants and not touched & holds:
        return Vote.FOR
    if touched <= holds and not touched & wants:
        return Vote.AGAINST
    return Vote.ABSTAIN


HEAD_RANK = 5
"""A card's rank as a head of government."""


def head(state: "State", nation: EntityId) -> EntityId | None:
    """The person the world gives as ``nation``'s head: of the nation's people whose card
    leads it (a head of government's rank, or the nation itself among its principals),
    the highest in rank, a playable leader before any other, then in id order. None when
    no card leads it."""
    from revisionist.core.realism.war import polity_of

    leads = [
        (-card.reach.rank, person not in state.roster, person)
        for person, card in state.cards.items()
        if polity_of(state, person) == nation
        and (card.reach.rank == HEAD_RANK or nation in card.principals)
    ]
    return min(leads)[2] if leads else None


def seat_votes(state: "State", conf: Conference) -> dict[EntityId, list[Vote]]:
    """Each invited nation's votes: for a nation with seats, each seat's sealed vote, else
    its fallback; for a nation no seat holds, one vote by its head's card (no vote when
    the world gives it no head)."""
    from revisionist.core.realism.holders import holding_seats

    sealed = state.conferences.votes.get(conf.key, {})
    out: dict[EntityId, list[Vote]] = {}
    for nation in conf.invited:
        seats = holding_seats(state, nation)
        if seats:
            out[nation] = [
                sealed[s].vote if s in sealed else fallback(state, conf, s) for s in seats
            ]
            continue
        leader = head(state, nation)
        if leader is not None:
            vote = lean(state, conf, nation, leader)
            assert vote is not Vote.FOR or not binding(conf, nation)
            out[nation] = [vote]
    return out


def tally(state: "State", conf: Conference, day: date) -> Tally:
    """Count nations, not seats (rule 4), and say what the count makes (rule 5)."""
    votes: list[NationVote] = []
    for nation, cast in seat_votes(state, conf).items():
        agreed = cast[0] if len(set(cast)) == 1 else Vote.ABSTAIN  # [proposed]
        votes.append(NationVote(nation=nation, vote=agreed))
    if len(votes) * 2 <= len(conf.invited):
        return Tally(on=day, outcome=Outcome.CANCELLED, votes=tuple(votes))
    ayes = [v.nation for v in votes if v.vote is Vote.FOR]
    noes = [v.nation for v in votes if v.vote is Vote.AGAINST]
    if conf.text.unanimous:
        passed = len(ayes) == len(conf.invited)
    else:
        passed = len(ayes) > len(noes)
    if not passed:
        return Tally(on=day, outcome=Outcome.FAILED, votes=tuple(votes))
    if len(ayes) < 2:
        return Tally(on=day, outcome=Outcome.RESOLUTION, votes=tuple(votes))
    return Tally(
        on=day,
        outcome=Outcome.AGREEMENT,
        votes=tuple(votes),
        agreement_id=derived_id(state.campaign_id, "conference", conf.key),
    )


def made(state: "State", conf: Conference, result: Tally) -> "Agreement":
    """The agreement a passed text makes: among the nations for, in the invited order,
    with only the clauses that bind one of them."""
    from revisionist.core.realism import agreement

    assert result.agreement_id is not None
    ayes = {v.nation for v in result.votes if v.vote is Vote.FOR}
    parties = tuple(n for n in conf.invited if n in ayes)
    clauses = tuple(c for c in conf.text.clauses if c.binds in ayes)
    return agreement.Agreement(
        agreement_id=result.agreement_id,
        version=agreement.version(parties, conf.text.wording, clauses),
        parties=parties,
        wording=conf.text.wording,
        clauses=clauses,
        made=result.on,
        published=result.on if conf.public else None,
        statuses=agreement.statuses(clauses),
    )


def _clauses_judged(state: "State", conf: Conference, result: Tally) -> list["Payload"]:
    """Each vote clause on ``conf`` of an agreement already in force, judged from the
    tally: kept when the bound nation's counted vote is the one the clause names, else
    broken; void when the conference is cancelled or does not invite the bound nation."""
    from revisionist.core import events as ev
    from revisionist.core.realism import agreement
    from revisionist.core.realism.agreement import ClauseStatus

    counted = {v.nation: v.vote for v in result.votes}
    out: list[Payload] = []
    for x in sorted(state.agreements.made.values(), key=lambda a: (a.made, a.agreement_id)):
        if x.made > result.on:
            continue
        for n, c in enumerate(x.clauses):
            if c.type is not ClauseType.VOTE or c.text != conf.key:
                continue
            if x.statuses[n] not in (ClauseStatus.STANDING, ClauseStatus.UNCHECKED):
                continue
            if result.outcome is Outcome.CANCELLED or c.binds not in conf.invited:
                status, why = ClauseStatus.VOID, "The vote it names was not held for it."
            else:
                wanted = Vote.FOR if c.present else Vote.AGAINST
                given = counted.get(c.binds, Vote.ABSTAIN)
                kept = given is wanted
                status = ClauseStatus.KEPT if kept else ClauseStatus.BROKEN
                why = f"{agreement.nation_name(state, c.binds)} voted {given.value}."
            out.append(
                ev.ClauseJudged(
                    agreement_id=x.agreement_id, clause=n, status=status, on=result.on, reason=why
                )
            )
            rows = [("Clause", agreement.render_clause(state, c)), ("Finding", why)]
            key = ("judged", x.agreement_id, str(n), status.value, "None", result.on.isoformat())
            title = agreement.title_of(status)
            out += agreement.papers(state, x.parties, key, result.on, title, rows)
            if status is ClauseStatus.BROKEN:
                out += agreement.broken_costs(state, x, n, result.on)
    return out


# --- papers and news ------------------------------------------------------------------


def _day(day: date) -> str:
    return f"{day.day} {day:%B} {day.year}"


def _names(state: "State", nations: Sequence[EntityId]) -> str:
    from revisionist.core.realism import agreement

    return ", ".join(agreement.nation_name(state, n) for n in nations) + "."


def _call_rows(state: "State", conf: Conference) -> list[tuple[str, str]]:
    from revisionist.core.realism import agreement

    rows = [
        ("Conference", conf.key),
        ("Called by", agreement.nation_name(state, conf.caller)),
        ("Invited", _names(state, conf.invited)),
        ("Voting day", _day(conf.voting_day)),
        ("Text", conf.text.wording),
    ]
    rows += [
        (f"Clause {n + 1}", agreement.render_clause(state, c))
        for n, c in enumerate(conf.text.clauses)
    ]
    if conf.text.unanimous:
        rows.append(("Passes", "Only if every nation invited votes for."))
    return rows


_SAID = {
    Outcome.AGREEMENT: "Passed: an agreement is in force among the nations for.",
    Outcome.RESOLUTION: "Passed as a resolution that binds no nation.",
    Outcome.FAILED: "Not passed.",
    Outcome.CANCELLED: "Cancelled: too few nations voted.",
}


def _result_rows(state: "State", conf: Conference, result: Tally) -> list[tuple[str, str]]:
    from revisionist.core.realism import agreement

    rows = [("Conference", conf.key), ("Result", _SAID[result.outcome])]
    rows += [(agreement.nation_name(state, v.nation), v.vote.value) for v in result.votes]
    return rows


def _papers(
    state: "State", conf: Conference, what: str, day: date, title: str, rows: list[tuple[str, str]]
) -> list["Payload"]:
    from revisionist.core.realism import agreement

    return agreement.papers(state, conf.invited, ("conference", conf.key, what), day, title, rows)


def news_id(state: "State", conf: Conference, what: str) -> str:
    return derived_id(state.campaign_id, "conference-news", conf.key, what)


def _news(state: "State", conf: Conference, day: date, headline: str, what: str) -> "Payload":
    from revisionist.core import events as ev
    from revisionist.core.realism import agreement
    from revisionist.core.realism.document import BodyField
    from revisionist.core.realism.war import NewsEvent, NewsTopic

    facts = (
        BodyField(label="Conference", value=conf.key[:60]),
        BodyField(label="Invited", value=_names(state, conf.invited)[:60]),
    )
    return ev.NewsReported(
        news=NewsEvent(
            news_id=news_id(state, conf, what),
            on=day,
            topic=NewsTopic.VOTE,
            subject=conf.caller,
            facts=facts,
            headline=f"{headline}: {agreement.nation_name(state, conf.caller)}'s conference"[:200],
        )
    )


def walk(state: "State", day: date) -> list["Payload"]:
    """With ``conference`` on, on ``day``: each conference that has opened sends its call
    to every invited seat once (news when public); each whose voting day has come, in a
    walk after its second wake opening, is tallied, makes what the tally makes, and sends
    the result (news when public); vote clauses on it are judged."""
    if not on(state):
        return []
    from revisionist.core import events as ev

    out: list[Payload] = []
    for conf in sorted(state.conferences.held.values(), key=lambda c: (c.opens, c.key)):
        if conf.opens > day:
            continue
        if conf.tally_wake is None:  # a world's conference opens on its day
            conf = conf.model_copy(update={"tally_wake": _tally_wake(state)})
            out.append(ev.ConferenceCalled(conference=conf))
        rows = _call_rows(state, conf)
        call_paper = (
            _papers(state, conf, "call", day, "A conference is called", rows)
            if conf.tally is None
            else []
        )
        out += call_paper
        if call_paper and conf.public and news_id(state, conf, "call") not in state.news:
            out.append(_news(state, conf, day, "Conference called", "call"))
        assert conf.tally_wake is not None
        if conf.tally is not None or day < conf.voting_day or _wake(state) < conf.tally_wake:
            continue
        result = tally(state, conf, day)
        out.append(ev.ConferenceTallied(conference=conf.key, tally=result))
        if result.outcome is Outcome.AGREEMENT:
            out.append(ev.AgreementMade(agreement=made(state, conf, result)))
        out += _clauses_judged(state, conf, result)
        rows = _result_rows(state, conf, result)
        out += _papers(state, conf, "result", day, "A conference has voted", rows)
        if conf.public:
            out.append(_news(state, conf, day, "Conference voted", "result"))
    return out


def paper_id(state: "State", conf: Conference, what: str, seat: SeatId) -> DocumentId:
    """The id of the paper ``what`` ("call" or "result") to ``seat``."""
    return DocumentId(
        derived_id(state.campaign_id, "agreement-paper", "conference", conf.key, what, seat)
    )


__all__ = [
    "CONF_DAYS",
    "CONF_WAKES",
    "Ballot",
    "Conference",
    "ConferenceText",
    "Conferences",
    "NationVote",
    "Outcome",
    "Tally",
    "Vote",
    "binding",
    "call",
    "call_key",
    "call_refusal",
    "fallback",
    "head",
    "lean",
    "made",
    "on",
    "opened",
    "paper_id",
    "scheduled",
    "scope",
    "seat_votes",
    "seen_by",
    "tally",
    "topics_of",
    "vote",
    "vote_refusal",
    "walk",
]
