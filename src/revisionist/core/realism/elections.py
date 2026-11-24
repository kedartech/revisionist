"""Elections redraw a chamber (ELE).

With ``elections`` on, a world may list elections: the nation, the chambers each redraws,
its day, and optionally a post whose term ends that day. On the day each bloc of a chamber
gains or loses one percent of the chamber's seats for each ``POINTS_PER_PERCENT`` points its
support stands above or below its baseline, and the seats are scaled back to the chamber's
total, largest remainders first, every bloc keeping one. Each row of a bloc's votes is
scaled by its new seats over its old (``groups.reseated``). The redrawn seats are public.

Where an election names a post, the post is put to the office question with the cause
``election`` on the first walk, sitting on the election's day, so its day is told to every
seat of the holder's nation from the first wake: the holder is removed when the mean
support of what the post rests on stands under ``office.ELECTION_LINE`` that day. The same
notice and sitting apply to every seat, whoever plays it. A kept holder's rest does not
stop an election's question.
"""

from datetime import date
from fractions import Fraction

from revisionist.core import events as ev
from revisionist.core._base import Label
from revisionist.core.ids import EntityId
from revisionist.core.realism import groups, office
from revisionist.core.realism.groups import Group
from revisionist.core.state import QuestionCause, Rule, State

POINTS_PER_PERCENT = 5
"""A bloc gains or loses one percent of its chamber's seats per this many points of
support above or below its baseline. [proposed]"""


def on(state: State) -> bool:
    return Rule.ELECTIONS in state.rules and groups.on(state)


def blocs(state: State, polity: EntityId, chamber: Label) -> tuple[Group, ...]:
    return tuple(g for g in groups.of(state, polity) if g.chamber == chamber and g.seats)


def redrawn(state: State, polity: EntityId, chamber: Label) -> dict[Label, int]:
    """Each bloc's seats after an election today, by group key; the chamber's total kept."""
    found = blocs(state, polity, chamber)
    total = sum(g.seats or 0 for g in found)
    wanted: dict[Label, Fraction] = {}
    for g in found:
        moved = Fraction((groups.support(state, polity, g.key) or 0) - g.baseline)
        gain = total * moved / (POINTS_PER_PERCENT * 100)
        wanted[g.key] = max(Fraction(0), (g.seats or 0) + gain - 1)
    left = total - len(found)  # every bloc keeps one seat; the rest go by share
    weight = sum(wanted.values())
    if weight == 0:
        return {g.key: g.seats or 0 for g in found}
    share = {k: w * left / weight for k, w in wanted.items()}
    seats = {k: int(s) for k, s in share.items()}
    order = sorted(share, key=lambda k: (-(share[k] - seats[k]), list(share).index(k)))
    for k in order[: left - sum(seats.values())]:
        seats[k] += 1
    return {k: n + 1 for k, n in seats.items()}


def walk(state: State, today: date) -> list[ev.Payload]:
    """The day's elections: before its day, each named post put to the office question on
    the first walk one may, sitting on the day; on the day, each chamber redrawn."""
    if not on(state):
        return []
    out: list[ev.Payload] = []
    for election in state.groups.elections:
        post, cause = election.post, QuestionCause.ELECTION
        if post is not None and office.on(state) and today < election.day:
            if not office.refusal(state, post, today, cause):
                out += office.open_question(
                    state, post, cause, today, in_walk=True, sits=election.day
                )
        if election.day == today:
            for chamber in election.chambers:
                seats = redrawn(state, election.nation, chamber)
                out.append(
                    ev.SeatsRedrawn(polity=election.nation, chamber=chamber, seats=seats, on=today)
                )
    return out


__all__ = ["POINTS_PER_PERCENT", "blocs", "on", "redrawn", "walk"]
