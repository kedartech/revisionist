"""The stakes of ``view.realism``: the contests the seat's view holds and its own open
mandates, each with the days left from the world date.

A contest's countdown is counted from the in-world date it was created on, since the
realism tick never runs it down (``ContestMoved`` comes only from the older tick). A
lean is sent only once the log holds a move of the contest's track, and then only as
one of ten steps and the side it favours.
"""

from collections.abc import Sequence
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.contest import leader
from revisionist.core.events import Event
from revisionist.core.ids import ContestId, EntityId, SeatId
from revisionist.core.ontology import TRACK_MAX, TRACK_MIN, Contest, ContestKind
from revisionist.core.project import project
from revisionist.core.realism.agenda import MandateStatus
from revisionist.core.state import State, View
from revisionist.engine.web.realism_api import Stake, StakeLean, StakeMandate, Stakes

STEPS = 10


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


def _name(view: View, entity: EntityId) -> str:
    found = view.entities.get(entity)
    return found.name if found is not None else ""


def seat_stakes(state: State, seat: SeatId, events: Sequence[Event]) -> Stakes:
    """The ``view.realism.stakes`` block: the undecided contests the seat's view holds,
    then the seat's own live mandates, each list soonest first."""
    view = project(state, seat)
    today = view.in_world_date
    if today is None:
        return Stakes(contests=[], mandates=[])
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
    mandates = [
        StakeMandate(text=m.text, days_left=max(0, (m.expires - today).days))
        for m in sorted(view.mandates.values(), key=lambda m: (m.expires, m.mandate_id))
        if m.status is MandateStatus.LIVE
    ]
    return Stakes(contests=contests, mandates=mandates)


__all__ = ["STEPS", "seat_stakes"]
