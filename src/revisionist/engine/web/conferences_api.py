"""Conferences on the web (CNA): calling one, sealing the seat's vote, the vote on the
seat's agenda, and the ``conferences`` block.

A call and a vote are the conference's own sealed actions (CNF): ``wake.call_conference``
and ``wake.seal_vote`` land them at once, a later vote in the same wake replaces the
earlier, and after the seat commits either is held for the next wake like any order.
Everything shown is read from the seat's view, which holds the conferences its nation is
invited to (and the public ones) and, of the votes, its own only. Nothing here says
whether a nation's counted vote was a person's or the aide's.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any

from pydantic import ValidationError

from revisionist.core.canary import scan_text
from revisionist.core.ids import CampaignId, EntityId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import agreement, conference, process
from revisionist.core.realism.conference import Conference, ConferenceText, Vote
from revisionist.core.realism.effect import AgreementClause
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State, View
from revisionist.engine import wake
from revisionist.engine.store import EventStore
from revisionist.engine.web.agreements_api import checked
from revisionist.engine.web.realism_api import (
    AgendaItem,
    ConferenceLine,
    ConferencesBlock,
    ConferenceVoteLine,
    TermClause,
)

VOTE_KIND = "Vote"  # [proposed] a conference the seat's nation votes in, on its agenda
CALLED = "The conference is called. Each nation invited is told; it votes on {day}."  # [proposed]
SEALED_VOTE = "Your vote is sealed. No one sees it before the tally."  # [proposed]
_YOURS = "Your vote, sealed until the tally: {vote}."  # [proposed]
_CALLS = "{caller} calls a conference of {invited}: {wording}"  # [proposed]
_WORDING_MAX = 600
_CLAUSES_MAX = 8


def _day(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def _own(state: State, view: View) -> EntityId | None:
    return polity_of(state, view.me.embodies)


def _in_order(view: View) -> list[Conference]:
    """The conferences in the seat's view, by voting day, then name."""
    return sorted(view.conferences.held.values(), key=lambda c: (c.voting_day, c.key))


def _names(state: State, nations: tuple[EntityId, ...]) -> list[str]:
    return [agreement.nation_name(state, n) for n in nations]


# --- the two actions ------------------------------------------------------------------


def _text(body: Mapping[str, Any], key: str, most: int, required: bool = True) -> str:
    value = body.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"Give the conference's {key}.")
    if len(value) > most:
        raise ValueError(f"{key} is at most {most} characters.")
    return value


def _flag(body: Mapping[str, Any], key: str) -> bool:
    value = body.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"{key} is true or false.")
    return value


def _clauses(body: Mapping[str, Any]) -> tuple[AgreementClause, ...]:
    value = body.get("clauses", [])
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise ValueError("clauses is a list of clauses.")
    if len(value) > _CLAUSES_MAX:
        raise ValueError(f"A conference's text holds at most {_CLAUSES_MAX} clauses.")
    out: list[AgreementClause] = []
    for n, item in enumerate(value, start=1):
        try:
            out.append(AgreementClause.model_validate(item))
        except ValidationError:
            raise ValueError(f"Clause {n} cannot be read.") from None
    return tuple(out)


def _invited(state: State, seat: SeatId, body: Mapping[str, Any]) -> tuple[EntityId, ...]:
    """The nations ``body`` invites (entity ids), the caller's own first: a seat that
    calls a conference is always at it."""
    value = body.get("invited", [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("invited is a list of nations.")
    view = project(state, seat)
    named = [EntityId(v) for v in value]
    if any(n not in view.entities for n in named):
        raise ValueError("Every nation invited is one you know of.")
    own = _own(state, view)
    return tuple(dict.fromkeys(((own,) if own is not None else ()) + tuple(named)))


def call_args(state: State, seat: SeatId, body: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """The ``conference-call`` action, checked against the open wake: what filing it
    needs and its label. Raises ``ValueError`` with the reason it is refused."""
    wording = _text(body, "text", _WORDING_MAX)
    text = ConferenceText(
        wording=wording, clauses=_clauses(body), unanimous=_flag(body, "unanimous")
    )
    invited = _invited(state, seat, body)
    raw_day = _text(body, "voting_day", 10)
    try:
        voting_day = date.fromisoformat(raw_day)
    except ValueError:
        raise ValueError("voting_day is a date, as 1941-07-12.") from None
    key = _text(body, "key", 60, required=False) or derived_id(
        state.campaign_id, "conference-call", seat, state.tick, wording
    )
    why = conference.call_refusal(state, seat, key, invited, text, voting_day)
    if why:
        raise ValueError(why)
    args = {
        "key": key,
        "invited": list(invited),
        "text": text.model_dump(mode="json"),
        "voting_day": voting_day.isoformat(),
        "public": _flag(body, "public"),
    }
    return args, f"Your call of a conference, voting on {_day(voting_day)}"


def vote_args(state: State, seat: SeatId, body: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """The ``conference-vote`` action, checked against the open wake: the conference and
    the vote, and its label. Raises ``ValueError`` with the reason it is refused."""
    key = _text(body, "conference", 60)
    try:
        choice = Vote(_text(body, "vote", 10).lower())
    except ValueError:
        raise ValueError(f"The vote is one of {', '.join(v.value for v in Vote)}.") from None
    why = conference.vote_refusal(state, seat, key)
    if why:
        raise ValueError(why)
    return {"conference": key, "vote": choice.value}, f"Your vote in a conference: {choice.value}"


def call(store: EventStore, campaign_id: CampaignId, seat: SeatId, args: Mapping[str, Any]) -> str:
    """Land a checked call; returns the reply. Raises ``ValueError`` when refused."""
    voting_day = date.fromisoformat(args["voting_day"])
    wake.call_conference(
        store,
        campaign_id,
        seat,
        args["key"],
        tuple(EntityId(n) for n in args["invited"]),
        ConferenceText.model_validate(args["text"]),
        voting_day,
        bool(args["public"]),
    )
    return CALLED.format(day=_day(voting_day))


def vote(store: EventStore, campaign_id: CampaignId, seat: SeatId, args: Mapping[str, Any]) -> str:
    """Seal a checked vote; returns the reply. Raises ``ValueError`` when refused."""
    wake.seal_vote(store, campaign_id, seat, args["conference"], Vote(args["vote"]))
    return SEALED_VOTE


# --- the agenda and the notice --------------------------------------------------------


def items(state: State, seat: SeatId) -> list[AgendaItem]:
    """Each conference the seat's nation is invited to and that has not voted, as an
    agenda item of kind "Vote" due on its voting day (rule 4). The item's ``cause`` is
    the seat's own sealed vote, which ``agenda_api.due_matters`` leaves out of the
    notice; nothing says what the aide would vote."""
    if not conference.on(state):
        return []
    view = project(state, seat)
    own = _own(state, view)
    out: list[AgendaItem] = []
    for conf in _in_order(view):
        if conf.tally is not None or own not in conf.invited:
            continue
        caller = agreement.nation_name(state, conf.caller)
        text = _CALLS.format(
            caller=caller,
            invited=", ".join(_names(state, conf.invited)),
            wording=conf.text.wording,
        )
        ballot = view.conferences.votes.get(conf.key, {}).get(seat)
        out.append(
            AgendaItem(
                id=conf.key,
                kind=VOTE_KIND,
                issuer=caller,
                text=process.WITHHELD if scan_text(state, seat, text) else text,
                issued=_day(conf.opens),
                deadline=_day(conf.voting_day),
                cause=None if ballot is None else _YOURS.format(vote=ballot.vote.value),
                options=[],
                plan=[],
                actions=[],
            )
        )
    return out


# --- the block ------------------------------------------------------------------------


def _line(state: State, seat: SeatId, view: View, conf: Conference) -> ConferenceLine:
    ballot = view.conferences.votes.get(conf.key, {}).get(seat)
    result = conf.tally
    return ConferenceLine(
        key=conf.key,
        called_by=agreement.nation_name(state, conf.caller),
        invited=_names(state, conf.invited),
        text=conf.text.wording,
        clauses=[
            TermClause(
                text=agreement.render_clause(state, c), checked=checked(c), interpretation=False
            )
            for c in conf.text.clauses
        ],
        unanimous=conf.text.unanimous,
        called=conf.opens.isoformat(),
        voting_day=conf.voting_day.isoformat(),
        public=conf.public,
        vote=None if ballot is None else ballot.vote.value,
        can_vote=not conference.vote_refusal(state, seat, conf.key),
        tallied=None if result is None else result.on.isoformat(),
        result=None if result is None else result.outcome.value,
        votes=[]
        if result is None
        else [
            ConferenceVoteLine(nation=agreement.nation_name(state, v.nation), vote=v.vote.value)
            for v in result.votes
        ],
        agreement=None if result is None else result.agreement_id,
    )


def block(state: State, seat: SeatId, view: View) -> ConferencesBlock | None:
    """The conferences as the seat sees them (rule 3), or None with conferences off:
    each one its nation is invited to and each public one, the seat's own vote, and
    after the tally the result and each nation's counted vote. No other seat's vote
    before the tally, and none marked as the aide's after it."""
    if not conference.on(state):
        return None
    return ConferencesBlock(conferences=[_line(state, seat, view, c) for c in _in_order(view)])


__all__ = [
    "CALLED",
    "SEALED_VOTE",
    "VOTE_KIND",
    "block",
    "call",
    "call_args",
    "items",
    "vote",
    "vote_args",
]
