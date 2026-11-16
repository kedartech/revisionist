"""The wake report: how asynchronous play is going, read from a campaign's log.

Per campaign: how each wake closed; per seat, the wakes its aide played and the hours
from a wake's opening to the seat's own commit; and, for each return after a missed
wake, whether ``catchup.feed`` gave a page for every wake missed. A log written before
the wake record shows ``unknown`` where the opening time, a commit's time or the close
reason is missing.

An operator command (``revisionist db wake-report``) that prints counts and no record's
content. Nothing a seat reaches imports it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.ontology import Controller
from revisionist.engine import catchup
from revisionist.engine.store import EventStore

UNKNOWN = "unknown"
OPEN = "open"


@dataclass(frozen=True)
class WakeRow:
    number: int
    how: str
    """``all_committed``, ``deadline``, ``host``, ``unknown`` (a close logged before the
    record had its reason) or ``open``."""


@dataclass(frozen=True)
class SeatRow:
    seat_id: SeatId
    name: str
    aide_wakes: int
    hours: tuple[float, ...]
    """Hours from the wake's opening to each of the seat's own commits that have both
    times, in commit order. The aide's commits are never in it."""
    unknown_hours: int

    @property
    def commits(self) -> int:
        return len(self.hours) + self.unknown_hours

    @property
    def median(self) -> float | None:
        return median(self.hours) if self.hours else None

    @property
    def highest(self) -> float | None:
        return max(self.hours) if self.hours else None


@dataclass(frozen=True)
class Return:
    seat_id: SeatId
    name: str
    wake: int
    """The wake the seat's player commits in after missing others."""
    missed: tuple[int, ...]
    uncovered: tuple[int, ...]
    """The missed wakes ``catchup.feed`` held no event for."""

    @property
    def covered(self) -> bool:
        return not self.uncovered


@dataclass(frozen=True)
class Report:
    campaign_id: CampaignId | None
    wakes: tuple[WakeRow, ...]
    seats: tuple[SeatRow, ...]
    returns: tuple[Return, ...]


@dataclass
class _Seat:
    aide: set[int]
    hours: list[float]
    unknown: int = 0


def build(events: Sequence[Event]) -> Report:
    """The report over a whole log, read in order."""
    if not events:
        return Report(None, (), (), ())
    state = replay(events)
    opened: dict[int, ev.WakeOpened] = {}
    closed: dict[int, ev.WakeClosed] = {}
    seats: dict[SeatId, _Seat] = {}
    last_own: dict[SeatId, int] = {}
    due: list[tuple[SeatId, int, tuple[int, ...], int]] = []
    for index, e in enumerate(events):
        p = e.payload
        if isinstance(p, ev.WakeOpened):
            opened[p.wake] = p
        elif isinstance(p, ev.WakeClosed):
            closed[p.wake] = p
        elif isinstance(p, ev.SeatHandover) and p.controller is Controller.HUMAN:
            for seat in e.scope.known_by:
                last_own.pop(seat, None)
        elif isinstance(p, ev.WakeCommitted):
            row = seats.setdefault(p.seat_id, _Seat(set(), []))
            if p.by_aide:
                row.aide.add(p.wake)
                continue
            start = opened[p.wake].opened_at if p.wake in opened else None
            if start is None or p.at is None:
                row.unknown += 1
            else:
                row.hours.append((p.at - start).total_seconds() / 3600)
            missed = tuple(range(last_own.get(p.seat_id, -1) + 1, p.wake))
            last_own[p.seat_id] = p.wake
            if missed:
                due.append((p.seat_id, p.wake, missed, index))
    wakes = tuple(WakeRow(n, _how(closed.get(n))) for n in sorted(opened))
    names = {s.seat_id: s.name for s in state.seats.values()}
    seat_rows = tuple(
        SeatRow(
            seat,
            names.get(seat, seat),
            len(row.aide),
            tuple(row.hours),
            row.unknown,
        )
        for seat, row in sorted(
            seats.items(), key=lambda item: (names.get(item[0], item[0]), item[0])
        )
    )
    returns = tuple(
        Return(
            seat, names.get(seat, seat), wake, missed, _uncovered(events[: index + 1], seat, missed)
        )
        for seat, wake, missed, index in due
    )
    return Report(events[0].campaign_id, wakes, seat_rows, returns)


def _how(closed: ev.WakeClosed | None) -> str:
    if closed is None:
        return OPEN
    return closed.how or UNKNOWN


def _uncovered(log: Sequence[Event], seat: SeatId, missed: tuple[int, ...]) -> tuple[int, ...]:
    """The missed wakes with no event in the seat's feed, read as the log stood when the
    seat came back."""
    fed = catchup.feed(replay(log), log, seat, missed[0], missed[-1])
    held = {f.wake for f in fed}
    return tuple(n for n in missed if n not in held)


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {many or one + 's'}"


def _span(wakes: tuple[int, ...]) -> str:
    return str(wakes[0]) if len(wakes) == 1 else f"{wakes[0]}-{wakes[-1]}"


def _hours(row: SeatRow) -> str:
    if not row.commits:
        return "no commit"
    if not row.hours:
        return f"hours to commit {UNKNOWN} ({_plural(row.commits, 'commit')})"
    extra = f", {row.unknown_hours} {UNKNOWN}" if row.unknown_hours else ""
    return (
        f"hours to commit median {row.median:.1f}, highest {row.highest:.1f} "
        f"({_plural(row.commits, 'commit')}{extra})"
    )


def render(report: Report) -> list[str]:
    """The report as lines of text."""
    if not report.wakes:
        return ["no wake has opened"]
    counts = {
        how: sum(1 for w in report.wakes if w.how == how)
        for how in ("all_committed", "deadline", "host", UNKNOWN, OPEN)
    }
    lines = [
        f"campaign {report.campaign_id}",
        f"wakes: {len(report.wakes)}; " + ", ".join(f"{how} {n}" for how, n in counts.items()),
        *(f"  wake {w.number}: {w.how}" for w in report.wakes),
    ]
    lines += [
        f"seat {s.name}: aide played {_plural(s.aide_wakes, 'wake')}; {_hours(s)}"
        for s in report.seats
    ]
    whole = sum(1 for r in report.returns if r.covered)
    if not report.returns:
        lines.append("catch-up: no return after a missed wake")
        return lines
    lines.append(
        f"catch-up: {_plural(len(report.returns), 'return')} after a missed wake; "
        f"{whole} with a page for every wake missed"
    )
    for r in report.returns:
        result = (
            "every wake had a page"
            if r.covered
            else f"no page for {_plural(len(r.uncovered), 'wake')} {_span(r.uncovered)}"
        )
        lines.append(
            f"  {r.name} returned in wake {r.wake} after missing {_span(r.missed)}: {result}"
        )
    return lines


def lines(store: EventStore, campaign_ids: Sequence[CampaignId]) -> list[str]:
    """The report for each campaign, a blank line between."""
    out: list[str] = []
    for campaign_id in campaign_ids:
        if out:
            out.append("")
        out.extend(render(build(list(store.read(campaign_id)))))
    return out


__all__ = ["Report", "Return", "SeatRow", "WakeRow", "build", "lines", "render"]
