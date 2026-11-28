"""The stakes of ``view.realism``: the contests the seat's view holds and its own open
mandates, each with the days left from the world date; then the seat's own aims, the
degree of the win they make as they stand, the drift from history and the days to the
season's end (SCD).

A contest's countdown is counted from the in-world date it was created on, since the
realism tick never runs it down (``ContestMoved`` comes only from the older tick). A
lean is sent only once the log holds a move of the contest's track, and then only as
one of ten steps and the side it favours. A decided contest leaves the open list and is
sent among the decided ones, with its winner.

The aims are the goals of the person the seat holds now (``goals.holder_seat``), never
another seat's. Each carries its source, its status, its success rule, its period, each
check of its condition with the evidence the seat may see, and the reason for its
status. A check that reads a fact hidden from the seat is ``uncertain``: its evidence is
read from the seat's own view only, and the aim's status is worked out without it (a
hidden check is neither true nor false), so two games that differ only in a hidden fact
send the same aims. Once the season is over every goal is public and every check is read
as it stands, and an aim's status is its stored record (``Goal.holding``). The degree is
counted from the statuses sent, by the season's own rule (``goals.season_winners``), so
at the season's end it is a win or a full win exactly for the seats that rule crowns.
No points total.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from enum import Enum

from revisionist.core import aim_patterns
from revisionist.core import events as ev
from revisionist.core import goals as gl
from revisionist.core.contest import leader
from revisionist.core.events import Event
from revisionist.core.goals import AimRule, AimStatus, Exposure, Goal, Leaf, WinCondition
from revisionist.core.ids import CampaignId, ContestId, EntityId, SeatId
from revisionist.core.ontology import (
    TRACK_MAX,
    TRACK_MIN,
    Contest,
    ContestKind,
    Controller,
    Phase,
)
from revisionist.core.project import at_post, project
from revisionist.core.realism import economy, groups, holders
from revisionist.core.realism.agenda import MandateStatus
from revisionist.core.realism.agreement import ClauseStatus
from revisionist.core.realism.card import words
from revisionist.core.realism.war import at_war
from revisionist.core.state import State, View
from revisionist.engine import realism_tick, season
from revisionist.engine.store import EventStore
from revisionist.engine.web.realism_api import (
    AimBlankLine,
    AimCheck,
    AimPatternLine,
    AimValue,
    OwnAimBlock,
    Stake,
    StakeAim,
    StakeDecided,
    StakeLeaf,
    StakeLean,
    StakeMandate,
    Stakes,
)

STEPS = 10
FULL_WIN = "full win"
WIN = "win"
UNCERTAIN = "uncertain"


def _deciding_days(events: Sequence[Event]) -> tuple[dict[ContestId, date], set[ContestId]]:
    """Each contest's deciding day, and the contests whose track has moved."""
    today: date | None = None
    deciding: dict[ContestId, date] = {}
    moved: set[ContestId] = set()
    for e in events:
        p = e.payload
        if isinstance(p, ev.DateAdvanced):
            today = p.to
        elif isinstance(p, ev.ContestCreated) and today is not None:
            deciding[p.contest.contest_id] = today + timedelta(days=p.contest.countdown_days)
        elif isinstance(p, ev.ContestMoved) and p.change != 0:
            moved.add(p.contest_id)
    return deciding, moved


def _due(today: date, contest: Contest) -> date:
    """A contest the log does not show being created: its countdown from today."""
    return today + timedelta(days=contest.countdown_days)


def _lean(view: View, contest: Contest) -> StakeLean:
    low = 0 if contest.kind is ContestKind.TRIAL else TRACK_MIN
    step = min(STEPS, 1 + (contest.track - low) * STEPS // (TRACK_MAX - low))
    side = leader(contest)
    return StakeLean(step=step, favours=_name(view, side) if side is not None else None)


def _name(view: View, entity: EntityId | None) -> str:
    found = view.entities.get(entity) if entity is not None else None
    return found.name if found is not None else ""


def _names(view: View, ids: Sequence[EntityId]) -> str:
    return ", ".join(_name(view, i) for i in ids)


# --- the seat's own aims --------------------------------------------------------------


class _Truth(Enum):
    """A check as the seat may judge it: it holds; it does not, and still can come to;
    it does not, and no longer can; or unknown, since it reads a fact hidden from the seat."""

    HOLDS = "holds"
    NOT = "not"
    SETTLED = "settled"
    UNKNOWN = "unknown"


def own_goals(state: State, seat: SeatId) -> list[Goal]:
    """The aims' goals of the person ``seat`` holds now, by aim: none of another seat's."""
    mine = [
        g for g in state.goals.values() if g.person is not None and gl.holder_seat(state, g) == seat
    ]
    return sorted(mine, key=lambda g: (g.aim or 0, g.goal_id))


def _hidden(state: State, goal: Goal, rule: AimRule | None) -> list[bool]:
    """For each check of ``goal``'s condition, whether it reads a fact hidden from the
    seat: as the card's rule says, every check when the rule is lost, none once the
    season is over and everything has been revealed. A commander held to his post does
    not see his own nation's facts (``goals.post_sees``)."""
    count = len(gl.leaves(goal.condition))
    if state.phase is Phase.SEASON_OVER:
        return [False] * count
    if rule is None or len(rule.sees) != count:
        return [True] * count
    sees = rule.sees
    seat = gl.holder_seat(state, goal)
    if seat is not None and at_post(state, seat):
        sees = gl.post_sees(goal.condition, sees)
    return [s is Exposure.HIDDEN for s in sees]


def _truth(state: State, c: WinCondition, hidden: list[bool], at: list[int]) -> _Truth:
    """``c`` judged with its hidden checks unknown, in ``leaves`` order: an all-of falls
    on any check that does not hold, an any-of stands on any check that does; otherwise
    unknown wherever a hidden check could decide it."""
    if isinstance(c, gl.AllOf | gl.AnyOf):
        parts = [_truth(state, x, hidden, at) for x in c.conditions]
        if isinstance(c, gl.AllOf):
            return next(
                (t for t in (_Truth.SETTLED, _Truth.NOT, _Truth.UNKNOWN) if t in parts),
                _Truth.HOLDS,
            )
        if _Truth.HOLDS in parts:
            return _Truth.HOLDS
        if _Truth.UNKNOWN in parts:
            return _Truth.UNKNOWN
        return _Truth.SETTLED if all(p is _Truth.SETTLED for p in parts) else _Truth.NOT
    i = at[0]
    at[0] += 1
    if hidden[i]:
        return _Truth.UNKNOWN
    if gl.goal_met(state, c):
        return _Truth.HOLDS
    return _Truth.SETTLED if gl._settled(state, c) else _Truth.NOT


def _day(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def _status(
    state: State, goal: Goal, rule: AimRule | None, hidden: list[bool]
) -> tuple[AimStatus, str]:
    """The status the seat is shown and why. With no hidden check it is the aim's own
    status (``goals.aim_status``); with one it is worked out from the checks the seat
    may see alone, and a closed period, which only the goal's record could settle, stays
    at risk until the season's end. Once the season is over it is the goal's stored
    record, the one the season's winners are read from, now public."""
    if state.phase is Phase.SEASON_OVER:
        if goal.holding:
            return AimStatus.MET, "The season ended with it holding."
        return AimStatus.FAILED, "The season ended without it holding."
    today = state.in_world_date
    opens = rule.opens if rule is not None else None
    deadline = rule.deadline if rule is not None else None
    closed = deadline is not None and today is not None and today > deadline
    if opens is not None and (today is None or today < opens):
        return AimStatus.AT_RISK, f"It is judged from {_day(opens)}."
    if not any(hidden):
        status = gl.aim_status(state, goal)
        if status is AimStatus.MET:
            if closed and deadline is not None:
                return status, f"It held on its last day, {_day(deadline)}."
            return status, "It holds now."
        if status is AimStatus.FAILED:
            if closed and deadline is not None:
                return status, f"Its last day, {_day(deadline)}, passed without it holding."
            return status, "It can no longer come to hold."
        left = (
            f" {(deadline - today).days} days are left."
            if deadline is not None and today is not None
            else ""
        )
        return status, "It does not hold now; it still can." + left
    if closed and deadline is not None:
        return AimStatus.AT_RISK, (
            f"Its last day, {_day(deadline)}, has passed; whether it held rests on what is "
            "hidden from you, and the season's end will tell."
        )
    truth = _truth(state, goal.condition, hidden, [0])
    if truth is _Truth.HOLDS:
        return AimStatus.MET, "It holds now on what you can see."
    if truth is _Truth.SETTLED:
        return AimStatus.FAILED, "It can no longer come to hold, on what you can see."
    if truth is _Truth.NOT:
        return AimStatus.AT_RISK, "It does not hold now on what you can see; it still can."
    n = sum(hidden)
    checks = "one of its checks reads" if n == 1 else f"{n} of its checks read"
    return AimStatus.AT_RISK, f"It is uncertain: {checks} what is hidden from you."


def _op(op: str) -> str:
    return "at least" if op == "ge" else "at most"


def _reads(view: View, leaf: Leaf) -> str:
    """What a check reads, in words, naming only what the seat's view holds by name."""
    match leaf:
        case gl.HoldsArea():
            return f"{_name(view, leaf.area)} held by {_name(view, leaf.holder)}"
        case gl.IncomeAt():
            return f"{_name(view, leaf.nation)}'s war-economy figure {_op(leaf.op)} {leaf.value}"
        case gl.SupportAt():
            return (
                f"support for {words(leaf.group)} in {_name(view, leaf.nation)} "
                f"{_op(leaf.op)} {leaf.value}"
            )
        case gl.AgreementInForce():
            return f"an agreement in force among {_names(view, leaf.between)}"
        case gl.ContestWon():
            k = view.contests.get(leaf.contest)
            return f"{k.name if k is not None else 'a contest'} won by {_name(view, leaf.side)}"
        case gl.AtWar():
            how = "at war" if leaf.war else "at peace"
            return f"{_name(view, leaf.a)} and {_name(view, leaf.b)} {how}"
        case gl.RegardAt():
            pair = f"{_name(view, leaf.a)} and {_name(view, leaf.b)}"
            return f"regard between {pair} {_op(leaf.op)} {leaf.value}"
        case gl.EntityIs():
            return f"{_name(view, leaf.entity)} {leaf.status.value}"
        case gl.QuantityAt():
            q = view.quantities.get(leaf.quantity)
            return f"{q.name if q is not None else 'a figure'} {_op(leaf.op)} {leaf.value}"
        case _:
            return words(leaf.check)


def _evidence(view: View, leaf: Leaf) -> list[str]:
    """What the seat's own view shows of a check, in words: public facts and its own
    nation's, and of a fact hidden from it only what its own picture holds. Read from
    the view alone, never from the state."""
    match leaf:
        case gl.HoldsArea():
            area, h = _name(view, leaf.area), holders.holder(view, leaf.area)
            return [f"{area} is held by {_name(view, h)}." if h else f"{area} has no holder."]
        case gl.IncomeAt():
            figure = economy.figure(view, leaf.nation)
            return [f"{_name(view, leaf.nation)}'s war-economy figure is {figure:.1f}."]
        case gl.SupportAt():
            g = groups.group(view, leaf.nation, leaf.group)
            n = groups.support(view, leaf.nation, leaf.group)
            if g is None or n is None:
                return []
            return [f"{g.name} in {_name(view, leaf.nation)} stands at {n}."]
        case gl.AgreementInForce():
            wanted = set(leaf.between)
            made = sorted(view.agreements.made.values(), key=lambda a: (a.made, a.agreement_id))
            return [
                f"An agreement among {_names(view, a.parties)} "
                + ("has a clause broken." if ClauseStatus.BROKEN in a.statuses else "is in force.")
                for a in made
                if wanted <= set(a.parties)
            ]
        case gl.ContestWon():
            k = view.contests.get(leaf.contest)
            if k is None:
                return []
            if k.decided and k.winner is not None:
                return [f"{k.name} was decided for {_name(view, k.winner)}."]
            return [f"{k.name} is not yet decided."]
        case gl.AtWar():
            war = "are at war" if at_war(view, leaf.a, leaf.b) else "are not at war"
            return [f"{_name(view, leaf.a)} and {_name(view, leaf.b)} {war}."]
        case gl.RegardAt():
            pair = {leaf.a, leaf.b}
            r = next((x for x in view.relationships.values() if {x.a, x.b} == pair), None)
            if r is None:
                return []
            names = f"{_name(view, leaf.a)} and {_name(view, leaf.b)}"
            return [f"{names} regard each other at {r.disposition}."]
        case gl.EntityIs():
            e = view.entities.get(leaf.entity)
            return [] if e is None else [f"{e.name} is {e.status.value}."]
        case gl.QuantityAt():
            q = view.quantities.get(leaf.quantity)
            if q is None or q.value is None:
                return []
            return [f"{q.name} stands at {q.value} {q.unit}."]
        case _:
            return []


def _seen(sees: Sequence[Exposure], i: int) -> str:
    """How a check the seat may see is seen: its own nation's, or public (a check once
    hidden, revealed at the season's end, among them)."""
    return Exposure.OWN.value if sees and sees[i] is Exposure.OWN else Exposure.PUBLIC.value


def _aim(state: State, view: View, goal: Goal) -> StakeAim:
    rule = gl.aim_rule(state, goal)
    hidden = _hidden(state, goal, rule)
    sees = rule.sees if rule is not None and len(rule.sees) == len(hidden) else ()
    status, reason = _status(state, goal, rule, hidden)
    return StakeAim(
        aim=goal.aim or 0,
        text=goal.text,
        source=goal.source.value if goal.source is not None else "",
        status=status.value,
        rule=rule.rule if rule is not None else goal.text,
        opens=rule.opens.isoformat() if rule is not None and rule.opens is not None else None,
        deadline=(
            rule.deadline.isoformat() if rule is not None and rule.deadline is not None else None
        ),
        leaves=[
            StakeLeaf(
                reads=_reads(view, leaf),
                seen=UNCERTAIN if hidden[i] else _seen(sees, i),
                holds=None if hidden[i] else gl.goal_met(state, leaf),
                evidence=_evidence(view, leaf),
            )
            for i, leaf in enumerate(gl.leaves(goal.condition))
        ],
        reason=reason,
    )


def degree(state: State, seat: SeatId, aims: Sequence[StakeAim]) -> str | None:
    """The degree of the win the aims make as they stand, by the season's own rule:
    ``full win`` with three of three holding, ``win`` with two (or every aim of a card
    with fewer than two), else None."""
    if not aims:
        return None
    met = sum(1 for a in aims if a["status"] == AimStatus.MET.value)
    card = state.cards.get(state.seats[seat].embodies)
    count = len(card.aims) if card is not None else len(aims)
    if met >= 3:
        return FULL_WIN
    return WIN if met >= max(1, min(2, count)) else None


SEASON_END_SEEN = True
"""[proposed] The days to the season's end count only the contests the seat's view holds,
so a contest hidden from the seat cannot be told by the day it decides. Off: every
contest in the world counts."""


def season_days_left(state: State, view: View | None = None) -> int | None:
    """Days from the world date to the season's last deciding day; None without one.
    With ``SEASON_END_SEEN`` and a ``view``, the last day among the contests it holds."""
    last = season.last_deciding_day(state)
    if SEASON_END_SEEN and view is not None and last is not None:
        days = [k.decides for k in view.contests.values() if k.decides is not None]
        last = max(days) if days else None
    today = state.in_world_date
    if last is None or today is None:
        return None
    return max(0, (last - today).days)


def _contests(view: View, today: date, events: Sequence[Event]) -> list[Stake]:
    deciding, moved = _deciding_days(events)
    contests = [
        Stake(
            name=k.name,
            prize=k.prize,
            sides=[_name(view, s) for s in k.sides],
            days_left=max(0, (deciding.get(k.contest_id, _due(today, k)) - today).days),
            lean=_lean(view, k) if k.contest_id in moved else None,
        )
        for k in view.contests.values()
        if not k.decided
    ]
    contests.sort(key=lambda s: (s["days_left"], s["name"]))
    return contests


def _decided(view: View) -> list[StakeDecided]:
    """The decided contests the seat's view holds, by name, each with its winner."""
    return [
        StakeDecided(
            name=k.name,
            prize=k.prize,
            sides=[_name(view, s) for s in k.sides],
            winner=_name(view, k.winner) if k.winner is not None else None,
        )
        for k in sorted(view.contests.values(), key=lambda k: (k.name, k.contest_id))
        if k.decided
    ]


def seat_stakes(state: State, seat: SeatId, events: Sequence[Event]) -> Stakes:
    """The ``view.realism.stakes`` block: the undecided contests the seat's view holds,
    then the seat's own live mandates, each list soonest first; then the decided contests
    with their winners, its own aims by number, the degree they make, the drift from
    history and the days to the season's end."""
    view = project(state, seat)
    today = view.in_world_date
    aims = [_aim(state, view, g) for g in own_goals(state, seat)] if gl.aims_on(state) else []
    mandates = (
        [
            StakeMandate(text=m.text, days_left=max(0, (m.expires - today).days))
            for m in sorted(view.mandates.values(), key=lambda m: (m.expires, m.mandate_id))
            if m.status is MandateStatus.LIVE
        ]
        if today is not None
        else []
    )
    return Stakes(
        contests=_contests(view, today, events) if today is not None else [],
        mandates=mandates,
        decided=_decided(view),
        aims=aims,
        degree=degree(state, seat, aims),
        drift=view.divergence,
        season_days_left=season_days_left(state, view),
    )


# --- the seat's own aim: its ladder, the check and the set (OWR) ------------------------

AIM_STANDS = "It stands: {text}"
"""[proposed] The check's reply when a filled pattern stands."""
AIM_CANNOT = "It cannot stand as filled."
"""[proposed] The check's reply when it does not; the reasons follow in ``aim``."""
AIM_SET = "Your own aim is set: {text}"
"""[proposed] The set's reply when the aim is stored."""
AIM_NOT_SET = "Your own aim was not set."
"""[proposed] The set's reply when it is refused (after the window, a second time, or a
pattern that does not stand); the reasons follow in ``aim``."""
KEY_MAX = 120


def own_aim_block(state: State, seat: SeatId) -> OwnAimBlock | None:
    """The patterns the seat's post may use (``aim_patterns.ladder``), each blank with the
    values its view allows, while the person it holds may still set an own aim: own aims
    part of the game, a player holding a card with a replaceable aim, none set and the
    window open. None otherwise."""
    if not aim_patterns.on(state) or seat not in state.seats:
        return None
    me = state.seats[seat]
    found = aim_patterns.replaceable(state, me.embodies)
    card = state.cards.get(me.embodies)
    if (
        found is None
        or card is None
        or me.controller is not Controller.HUMAN
        or not aim_patterns.window_open(state, me.embodies)
    ):
        return None
    return OwnAimBlock(
        aim=found[0],
        replaces=card.aims[found[0] - 1],
        patterns=[
            AimPatternLine(
                key=r.key,
                sentence=r.sentence,
                blanks=[
                    AimBlankLine(
                        name=b.name,
                        values=[
                            AimValue(value=v, label=label)
                            for v, label in zip(b.values, b.labels, strict=True)
                        ],
                    )
                    for b in r.blanks
                ],
                difficulty=r.difficulty,
                government=r.government,
            )
            for r in aim_patterns.ladder(state, seat)
        ],
    )


def aim_args(body: Mapping[str, object]) -> tuple[str, dict[str, aim_patterns.BlankValue]]:
    """The pattern's key and each blank's value from an ``aim-check`` or ``aim-set`` body.
    Raises ``ValueError`` on a body no pattern could take."""
    key = body.get("key")
    if not isinstance(key, str) or not key or len(key) > KEY_MAX:
        raise ValueError("key names a pattern.")
    given = body.get("values", {})
    if not isinstance(given, dict):
        raise ValueError("values names each blank with its value.")
    values: dict[str, aim_patterns.BlankValue] = {}
    for name, v in given.items():
        if not isinstance(name, str) or isinstance(v, bool) or not isinstance(v, str | int):
            raise ValueError("values names each blank with its value.")
        values[name] = v
    return key, values


def _checked(out: aim_patterns.Filled | aim_patterns.Refused) -> AimCheck:
    if isinstance(out, aim_patterns.Refused):
        return AimCheck(stands=False, text=None, reasons=list(out.reasons))
    return AimCheck(stands=True, text=out.text, reasons=[])


def aim_check(
    state: State, seat: SeatId, key: str, values: Mapping[str, aim_patterns.BlankValue]
) -> AimCheck:
    """What the pattern ``key`` filled with ``values`` makes for the seat, from its own view
    (``aim_patterns.fill``). Files nothing."""
    return _checked(aim_patterns.fill(state, seat, key, values))


def aim_set(
    store: EventStore,
    campaign_id: CampaignId,
    seat: SeatId,
    key: str,
    values: Mapping[str, aim_patterns.BlankValue],
) -> AimCheck:
    """Store the filled pattern as the seat's own aim (``realism_tick.set_own_aim``) and
    answer with it as stored; or the reasons it cannot be, storing nothing."""
    return _checked(realism_tick.set_own_aim(store, campaign_id, seat, key, values))


def aim_reply(found: AimCheck, setting: bool) -> dict[str, object]:
    """The reply to ``aim-check`` (``setting`` false) or ``aim-set``, in fixed words."""
    if found["stands"]:
        said = (AIM_SET if setting else AIM_STANDS).format(text=found["text"])
    else:
        said = AIM_NOT_SET if setting else AIM_CANNOT
    return {"reply": said, "refused": not found["stands"], "aim": found}


__all__ = [
    "AIM_CANNOT",
    "AIM_NOT_SET",
    "AIM_SET",
    "AIM_STANDS",
    "FULL_WIN",
    "SEASON_END_SEEN",
    "STEPS",
    "UNCERTAIN",
    "WIN",
    "aim_args",
    "aim_check",
    "aim_reply",
    "aim_set",
    "degree",
    "own_aim_block",
    "own_goals",
    "season_days_left",
    "seat_stakes",
]
