"""Contests that move and decide (CON).

With ``contests`` switched on, a world's contest may name moves (``Contest.moves``), each
a step toward one of its sides when a thing happens in play:

- a battle won in a named region (or any of its subregions) by a nation on the side;
- a named territory taken by a nation on the side;
- a measure's flag (a quantity) set, from none or 0 to any other value;
- a quantity, a nation's war-economy figure or a group's support crossing a line, upward
  to at or above it, or downward to below it for a falling move;
- an agreement made among nations that include every one the move names, or a clause of
  such an agreement judged broken.

Each move lands ``ContestMoved`` once (cause ``move``, its index), and never again: the
fold marks it landed. A move reads only what the contest's whole audience may see, so a
public contest moves on public facts alone (battles from the news, holders, a public
quantity, the war-economy figure, a published agreement); a sealed agreement lands its
move the day it is published, and a crossing the audience could not see does not land.
On its deciding day (``Contest.decides``: the world's start date plus its countdown) a
contest is decided for the side ahead, or for nobody on a level track
(``core.contest.leader``). The score counts outcomes, never orders: nothing here reads
an order or how many were filed. A world with the rule off is unchanged.

The legacy tick's countdown (``core/contest.py``'s ``momentum_moves``) is not used here.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from revisionist.core.contest import leader, side_of
from revisionist.core.ids import EntityId
from revisionist.core.ontology import TRACK_MAX, Contest, ContestMove, MoveKind
from revisionist.core.visibility import PUBLIC, Scope, Visibility

if TYPE_CHECKING:
    from datetime import date

    from revisionist.core.events import ContestDecided, ContestMoved, Payload
    from revisionist.core.realism.agreement import Agreement
    from revisionist.core.realism.territory import WorldMap
    from revisionist.core.state import State, _World

STEPS: dict[MoveKind, int] = {
    MoveKind.BATTLE: 10,  # [proposed] plan, CON Defaults
    MoveKind.HOLDER: 15,  # [proposed] plan, CON Defaults
    MoveKind.FLAG: 25,  # [proposed] plan, CON Defaults
    MoveKind.LINE: 10,  # [proposed] plan, CON Defaults
    MoveKind.AGREEMENT_MADE: 15,  # [proposed] plan, CON Defaults
    MoveKind.AGREEMENT_BROKEN: 15,  # [proposed] plan, CON Defaults
}
"""The step a move takes when the world gives none, on a track of -100 to 100."""


def on(state: "_World") -> bool:
    """Whether contests move and decide in this game: the ``contests`` rule on."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.CONTESTS in rules


# --- what a move reads ------------------------------------------------------------------


def in_region(board: "WorldMap | None", area: EntityId, region: str) -> bool:
    """Whether ``area`` lies in ``region`` or in one of its subregions."""
    if board is None:
        return False
    found = {t.area: t.region for t in board.territories} | {
        z.area: z.region for z in board.sea_zones
    }
    if area not in found:
        return False
    parents = {r.key: r.parent for r in board.regions}
    at: str | None = found[area]
    seen: set[str] = set()
    while at is not None and at not in seen:
        if at == region:
            return True
        seen.add(at)
        at = parents.get(at)
    return False


def sees(audience: Scope, fact: Scope | None) -> bool:
    """Whether every seat that sees a contest (``audience``) may see a fact of ``fact``'s
    scope; None is engine only, seen by no seat."""
    if fact is None:
        return False
    if fact.visibility is Visibility.PUBLIC:
        return True
    if audience.visibility is Visibility.PUBLIC:
        return False
    return audience.known_by <= fact.known_by


def _nation_scope(state: "State", nation: EntityId) -> Scope | None:
    from revisionist.core.realism.holders import holding_seats

    seats = frozenset(holding_seats(state, nation))
    return Scope(visibility=Visibility.RESTRICTED, known_by=seats) if seats else None


def _agreement_scope(state: "State", found: "Agreement") -> Scope:
    from revisionist.core.realism import agreement

    return PUBLIC if found.public else agreement.parties_scope(state, found.parties)


def _value(state: "State", move: ContestMove, day: "date | None") -> float | None:
    """What a flag or a line move reads on ``day`` (the war-economy figure moves with the
    date as captured industry comes back); None when there is nothing."""
    from revisionist.core.realism import economy, groups

    if move.quantity is not None:
        q = state.quantities.get(move.quantity)
        return None if q is None or q.value is None else float(q.value)
    assert move.nation is not None
    if move.group is not None:
        found = groups.support(state, move.nation, move.group)
        return None if found is None else float(found)
    return economy.figure(state, move.nation, day)


def _fact_scope(state: "State", move: ContestMove) -> Scope | None:
    """Who may see what a flag or a line move reads."""
    if move.quantity is not None:
        q = state.quantities.get(move.quantity)
        return None if q is None else q.scope
    assert move.nation is not None
    if move.group is not None:
        return _nation_scope(state, move.nation)  # true support: the nation's seats (GRP)
    return PUBLIC  # the war-economy figure is public (YLD)


def _crossed(move: ContestMove, was: float | None, now: float | None) -> bool:
    if was is None or now is None:
        return False
    if move.kind is MoveKind.FLAG:
        return was == 0 and now != 0
    assert move.line is not None
    if move.falling:
        return was >= move.line > now
    return was < move.line <= now


def _agreements_touched(state: "State", happened: Sequence["Payload"]) -> list["Agreement"]:
    """The agreements made, published or judged among ``happened``, in that order, once."""
    from revisionist.core.events import AgreementMade, AgreementPublished, ClauseJudged

    ids: list[str] = []
    for p in happened:
        if isinstance(p, AgreementMade):
            ids.append(p.agreement.agreement_id)
        elif isinstance(p, AgreementPublished | ClauseJudged):
            ids.append(p.agreement_id)
    made = state.agreements.made
    return [made[i] for i in dict.fromkeys(ids) if i in made]


def _broken_on(found: "Agreement", happened: Sequence["Payload"]) -> bool:
    """Whether ``found`` has a broken clause that ``happened`` judged or published."""
    from revisionist.core.events import AgreementPublished, ClauseJudged
    from revisionist.core.realism.agreement import ClauseStatus

    for p in happened:
        if isinstance(p, ClauseJudged) and p.agreement_id == found.agreement_id:
            if p.status is ClauseStatus.BROKEN:
                return True
        if isinstance(p, AgreementPublished) and p.agreement_id == found.agreement_id:
            if ClauseStatus.BROKEN in found.statuses:
                return True
    return False


def happened(
    state: "State",
    before: "State",
    today: Sequence["Payload"],
    contest: Contest,
    move: ContestMove,
    dates: "tuple[date | None, date | None]" = (None, None),
) -> bool:
    """Whether ``move`` of ``contest`` happened among ``today``'s happenings, read from
    ``before`` (the state they started from) on ``dates[0]`` and ``state`` (the state
    after them) on ``dates[1]``, and is one the contest's audience may see."""
    from revisionist.core.events import AreaHeld, BattleEnded
    from revisionist.core.realism.battle import Ending

    toward, audience = move.toward, contest.scope
    if move.kind is MoveKind.BATTLE:
        assert move.region is not None
        return any(
            isinstance(p, BattleEnded)
            and p.ending is not Ending.CEASED
            and in_region(state.map, p.area, move.region)
            and side_of(state, p.winner, contest) == toward
            for p in today
        )
    if move.kind is MoveKind.HOLDER:
        return any(
            isinstance(p, AreaHeld)
            and p.area == move.area
            and side_of(state, p.holder, contest) == toward
            for p in today
        )
    if move.kind in (MoveKind.FLAG, MoveKind.LINE):
        if not sees(audience, _fact_scope(state, move)):
            return False
        return _crossed(move, _value(before, move, dates[0]), _value(state, move, dates[1]))
    wanted = set(move.between)
    for found in _agreements_touched(state, today):
        if not wanted <= set(found.parties):
            continue
        if not sees(audience, _agreement_scope(state, found)):
            continue  # a sealed agreement lands its move the day it is published
        if move.kind is MoveKind.AGREEMENT_BROKEN:
            if _broken_on(found, today):
                return True
            continue
        was = before.agreements.made.get(found.agreement_id)
        if was is None or not sees(audience, _agreement_scope(before, was)):
            return True  # made today, or seen by the audience from today
    return False


def _change(contest: Contest, track: int, move: ContestMove) -> int:
    """The step toward ``move.toward`` from ``track``, clamped to the track's ends: up for
    the first side, down for any other."""
    step = move.step if move.toward == contest.sides[0] else -move.step
    return max(contest.floor - track, min(TRACK_MAX - track, step))


# --- the day walk -----------------------------------------------------------------------


def moves(
    state: "State",
    before: "State",
    today: Sequence["Payload"],
    since: "date | None" = None,
    day: "date | None" = None,
) -> list["ContestMoved"]:
    """One ``ContestMoved`` for each move of an undecided contest that happened among
    ``today`` and has not landed, contests in id order, moves in the world's order.
    ``before`` is read as of ``since`` and ``state`` as of ``day`` (default: the in-world
    date)."""
    from revisionist.core.events import ContestMoved

    if not on(state):
        return []
    out: list[ContestMoved] = []
    for k in sorted(state.contests.values(), key=lambda c: c.contest_id):
        if k.decided:
            continue
        track = k.track
        for i, m in enumerate(k.moves):
            if m.landed or not happened(state, before, today, k, m, (since, day)):
                continue
            change = _change(k, track, m)
            track += change
            out.append(ContestMoved(contest_id=k.contest_id, change=change, cause="move", move=i))
    return out


def decisions(state: "State", day: "date") -> list["ContestDecided"]:
    """A ``ContestDecided`` for each undecided contest whose deciding day has come, for
    the side ahead or for nobody on a level track, in id order."""
    from revisionist.core.events import ContestDecided

    if not on(state):
        return []
    return [
        ContestDecided(contest_id=k.contest_id, winner=leader(k))
        for k in sorted(state.contests.values(), key=lambda c: c.contest_id)
        if not k.decided and k.decides is not None and k.decides <= day
    ]
