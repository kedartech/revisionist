"""The wake report: how asynchronous play is going, read from a campaign's log.

Per campaign: how each wake closed; per seat, the wakes its aide played and the hours
from a wake's opening to the seat's own commit; and, for each return after a missed
wake, whether the catch-up reply (``catchup_api.reply``) served a page for every wake
missed: one with at least one paper, or the owner's note of what the aide filed. A
wake's own opening (``wake_opened``, ``date_advanced``) is public and in every feed, so
it does not make a page. A log written before the wake record shows ``unknown`` where
the opening time, a commit's time or the close reason is missing.

In a game with ``holders`` on, each wake also lists the territories that changed holder
while it was the latest wake opened (a capture lands at a close, so in the wake that
closed), and, with ``economy`` on, every nation's public figure as the wake ended. Both
are public facts: the board's holders and ``economy.figure``. In a game with ``battles``
on, each wake also counts the battles opened, the rounds fought and the battles ended
while it was the latest wake opened (BTD): counts only, never a side or a figure. In a
game with ``reports`` on, each wake also counts the reports every nation's sources made,
by source, and the share that were wrong (RPD): engine-only counts for the operator,
naming no piece. In a game with ``agreements`` on, each wake also counts the clauses of
agreements judged kept and judged broken while it was the latest wake opened (AGA):
counts only, never an agreement, a party or a clause.

An operator command (``revisionist db wake-report``) that prints counts and public
board facts, and no record's content. Nothing a seat reaches imports it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.fold import apply, replay
from revisionist.core.ids import CampaignId, EntityId, SeatId
from revisionist.core.ontology import Controller, EntityKind
from revisionist.core.realism import agreement, battle, detect, economy, holders
from revisionist.core.realism.agreement import ClauseStatus
from revisionist.core.state import State
from revisionist.engine.store import EventStore
from revisionist.engine.web import catchup_api

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
    """The missed wakes the catch-up reply served no paper or note for."""

    @property
    def covered(self) -> bool:
        return not self.uncovered


@dataclass(frozen=True)
class Holding:
    number: int
    changes: tuple[tuple[str, str, str], ...]
    """Each territory that changed holder in the wake, in log order: its name, the new
    holder's name and the old one's ("" for none)."""
    figures: tuple[tuple[str, float], ...]
    """Every nation's figure as the wake ended, by name; empty with ``economy`` off."""


@dataclass(frozen=True)
class Fighting:
    number: int
    opened: int
    rounds: int
    ended: int


@dataclass(frozen=True)
class Clauses:
    number: int
    kept: int
    broken: int


@dataclass(frozen=True)
class Intelligence:
    number: int
    by_source: tuple[tuple[str, int], ...]
    """The reports every nation's sources made in the wake, by source in the rules'
    order; a source that made none is left out."""
    wrong: int
    """How many of them were shifted (``report_made``'s engine-only ``shift``)."""

    @property
    def made(self) -> int:
        return sum(n for _, n in self.by_source)


@dataclass(frozen=True)
class Report:
    campaign_id: CampaignId | None
    wakes: tuple[WakeRow, ...]
    seats: tuple[SeatRow, ...]
    returns: tuple[Return, ...]
    holdings: tuple[Holding, ...] = ()
    """One per wake opened, in a game with ``holders`` on; else empty."""
    fighting: tuple[Fighting, ...] = ()
    """One per wake opened, in a game with ``battles`` on; else empty."""
    intelligence: tuple[Intelligence, ...] = ()
    """One per wake opened, in a game with ``reports`` on; else empty."""
    clauses: tuple[Clauses, ...] = ()
    """One per wake opened, in a game with ``agreements`` on; else empty."""


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
    return Report(
        events[0].campaign_id,
        wakes,
        seat_rows,
        returns,
        _holdings(events),
        _fighting(events, state),
        _intelligence(events, state),
        _clauses(events, state),
    )


def _name(state: State, entity: EntityId | None) -> str:
    e = state.entities.get(entity) if entity is not None else None
    return e.name if e is not None else ""


def _ended(state: State, number: int, changes: list[tuple[str, str, str]]) -> Holding:
    figures: tuple[tuple[str, float], ...] = ()
    if economy.on(state):
        polities = [k for k, e in state.entities.items() if e.kind is EntityKind.POLITY]
        figures = tuple(sorted((_name(state, p), economy.figure(state, p)) for p in polities))
    return Holding(number, tuple(changes), figures)


def _holdings(events: Sequence[Event]) -> tuple[Holding, ...]:
    """Each wake's holder changes and figures, folding the log once in order."""
    state: State | None = None
    out: list[Holding] = []
    number: int | None = None
    changes: list[tuple[str, str, str]] = []
    for e in events:
        p = e.payload
        if isinstance(p, ev.WakeOpened) and state is not None and number is not None:
            out.append(_ended(state, number, changes))
            changes = []
        state = replay([e]) if state is None else apply(state, e)
        if isinstance(p, ev.WakeOpened):
            number = p.wake
        elif isinstance(p, ev.AreaHeld) and number is not None:
            changes.append((_name(state, p.area), _name(state, p.holder), _name(state, p.was)))
    if state is None or number is None or not holders.on(state):
        return ()
    out.append(_ended(state, number, changes))
    return tuple(out)


def _fighting(events: Sequence[Event], state: State) -> tuple[Fighting, ...]:
    """Each wake's battles opened, rounds fought and battles ended, by the latest wake
    opened when each happened; empty with ``battles`` off."""
    if not battle.on(state):
        return ()
    counts: dict[int, list[int]] = {}
    number: int | None = None
    kinds = (ev.BattleOpened, ev.BattleRound, ev.BattleEnded)
    for e in events:
        p = e.payload
        if isinstance(p, ev.WakeOpened):
            number = p.wake
            counts.setdefault(number, [0, 0, 0])
        elif number is not None:
            for i, kind in enumerate(kinds):
                if isinstance(p, kind):
                    counts[number][i] += 1
    return tuple(Fighting(n, *c) for n, c in sorted(counts.items()))


def _clauses(events: Sequence[Event], state: State) -> tuple[Clauses, ...]:
    """Each wake's clauses judged kept and judged broken, by the latest wake opened when
    each was judged; empty with ``agreements`` off."""
    if not agreement.on(state):
        return ()
    counts: dict[int, list[int]] = {}
    number: int | None = None
    for e in events:
        p = e.payload
        if isinstance(p, ev.WakeOpened):
            number = p.wake
            counts.setdefault(number, [0, 0])
        elif number is not None and isinstance(p, ev.ClauseJudged):
            if p.status is ClauseStatus.KEPT:
                counts[number][0] += 1
            elif p.status is ClauseStatus.BROKEN:
                counts[number][1] += 1
    return tuple(Clauses(n, *c) for n, c in sorted(counts.items()))


def _intelligence(events: Sequence[Event], state: State) -> tuple[Intelligence, ...]:
    """Each wake's reports by source and how many were wrong, in a game with ``reports``
    on. A report counts in the wake last opened when it was made; none is made before
    the first wake opens."""
    if not detect.on(state):
        return ()
    made: dict[int, list[ev.ReportMade]] = {}
    number: int | None = None
    for e in events:
        p = e.payload
        if isinstance(p, ev.WakeOpened):
            number = p.wake
            made.setdefault(number, [])
        elif isinstance(p, ev.ReportMade) and number is not None:
            made[number].append(p)
    return tuple(
        Intelligence(
            n,
            tuple(
                (s.value, k)
                for s in detect.Source
                if (k := sum(1 for m in made[n] if m.report.source is s))
            ),
            sum(1 for m in made[n] if m.shift is not None),
        )
        for n in sorted(made)
    )


def _how(closed: ev.WakeClosed | None) -> str:
    if closed is None:
        return OPEN
    return closed.how or UNKNOWN


def _uncovered(log: Sequence[Event], seat: SeatId, missed: tuple[int, ...]) -> tuple[int, ...]:
    """The missed wakes whose catch-up page holds no paper and no aide note, read as the
    log stood when the seat came back: what the seat's own reply would have served."""
    reply = catchup_api.reply(replay(log), log, seat, {"first": missed[0], "last": missed[-1]})
    served = {page["number"] for page in reply["pages"] if page["papers"] or page.get("aide_filed")}
    return tuple(n for n in missed if n not in served)


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
    ]
    held = {h.number: h for h in report.holdings}
    fought = {f.number: f for f in report.fighting}
    heard = {i.number: i for i in report.intelligence}
    judged = {c.number: c for c in report.clauses}
    for w in report.wakes:
        lines.append(f"  wake {w.number}: {w.how}")
        if w.number in held:
            lines += _holding(held[w.number])
        if w.number in fought:
            f = fought[w.number]
            lines.append(
                f"    battles: {f.opened} opened, {_plural(f.rounds, 'round')} fought,"
                f" {f.ended} ended"
            )
        if w.number in heard:
            lines.append(_heard(heard[w.number]))
        if w.number in judged:
            c = judged[w.number]
            lines.append(f"    clauses: {c.kept} kept, {c.broken} broken")
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


def _holding(h: Holding) -> list[str]:
    moved = "; ".join(
        f"{area} to {new} from {old}" if old else f"{area} to {new}" for area, new, old in h.changes
    )
    out = [f"    holders: {moved or 'no change'}"]
    if h.figures:
        out.append("    figures: " + ", ".join(f"{name} {n:.1f}" for name, n in h.figures))
    return out


def _heard(i: Intelligence) -> str:
    if not i.made:
        return "    reports: none"
    counts = ", ".join(f"{source} {n}" for source, n in i.by_source)
    share = 100 * i.wrong / i.made
    return f"    reports: {counts}; {i.wrong} of {i.made} wrong ({share:.0f}%)"


def lines(store: EventStore, campaign_ids: Sequence[CampaignId]) -> list[str]:
    """The report for each campaign, a blank line between."""
    out: list[str] = []
    for campaign_id in campaign_ids:
        if out:
            out.append("")
        out.extend(render(build(list(store.read(campaign_id)))))
    return out


__all__ = [
    "Clauses",
    "Fighting",
    "Holding",
    "Report",
    "Return",
    "SeatRow",
    "WakeRow",
    "build",
    "lines",
    "render",
]
