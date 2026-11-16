"""The table the asynchronous invariants play on (``tests/test_async_invariants.py``).

The engine-v2 slice with Roosevelt and Churchill seated, as ``Table`` in the wake
tests, plus what the invariants need: ids drawn per seat, so the way two seats'
filings interleave cannot change an id or a seeded draw; sittings; and an outcome
digest of the state.
"""

import hashlib
import itertools
import json
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.ids import SeatId, derived_id
from revisionist.core.realism import advance
from revisionist.core.realism.agenda import Ask, PlayStyle
from revisionist.core.state import State
from revisionist.engine import ids as engine_ids
from revisionist.engine import options, realism_tick, runner, wake
from revisionist.engine.store import EventStore
from tests.test_engine_v2_wake import CAMPAIGN, T0, Table, play

ENGINE = "engine"
"""The id stream for everything no seat files: the tick, the close, the offers."""

DIGEST_LEAVES_OUT = ("last_seq",)
"""State fields the outcome digest leaves out: how many records were logged on the
way there. Event ids and read marks are records, never state; the wake's commit set
is left out in ``digest`` itself."""


class SeatIds:
    """``new_id`` drawn from a seeded counter per stream: one per seat, one for the
    engine. Ids are a pure function of the stream and its count, never of the clock or
    of how the streams interleave."""

    def __init__(self) -> None:
        self.stream = ENGINE
        self.counts: dict[str, itertools.count[int]] = {}

    def __call__(self) -> str:
        count = self.counts.setdefault(self.stream, itertools.count())
        return derived_id(CAMPAIGN, "async-id", self.stream, next(count))

    @contextmanager
    def drawn_by(self, stream: str) -> Iterator[None]:
        before, self.stream = self.stream, stream
        try:
            yield
        finally:
            self.stream = before

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every ``revisionist`` module that imported ``new_id`` draws from here."""
        real = engine_ids.new_id
        for name, module in list(sys.modules.items()):
            if name.startswith("revisionist") and getattr(module, "new_id", None) is real:
                monkeypatch.setattr(module, "new_id", self)


class AsyncTable(Table):
    """The slice, two human seats, ids per seat; every act goes through the engine."""

    def __init__(
        self,
        store: EventStore,
        monkeypatch: pytest.MonkeyPatch,
        briefings: Path,
        *,
        style: PlayStyle | None = PlayStyle.BEGINNER,
    ) -> None:
        self.ids_drawn = SeatIds()
        self.ids_drawn.install(monkeypatch)
        super().__init__(store)
        assert self.winston is not None
        self.churchill: SeatId = self.winston
        self.briefings = briefings
        self.now = T0
        if style is not None:
            for seat in (self.fdr, self.churchill):
                with self.ids_drawn.drawn_by(seat):
                    options.set_style(store, CAMPAIGN, seat, style)

    @property
    def seats(self) -> tuple[SeatId, SeatId]:
        return (self.fdr, self.churchill)

    def file(self, seat: SeatId, *asks: Ask) -> None:
        """One order per ask, each drawn from the seat's own id stream."""
        with self.ids_drawn.drawn_by(seat):
            for ask in asks:
                realism_tick.commit_order(self.store, CAMPAIGN, seat, [ask])

    def commit(self, seat: SeatId) -> None:
        with self.ids_drawn.drawn_by(seat):
            assert wake.commit(self.store, CAMPAIGN, seat, self.now)

    def sitting(self, seat: SeatId) -> int:
        """The seat opens every paper it holds, as a browser does; returns how many.
        Read marks are records: they change nothing the world holds."""
        state = self.state
        papers = [d for d in state.documents.values() if seat in d.view.scope.known_by]
        with self.ids_drawn.drawn_by(f"reads:{seat}"):
            for paper in papers:
                realism_tick.mark_read(self.store, CAMPAIGN, seat, paper.view.doc_id)
        return len(papers)

    def open_play(self) -> runner.TickRun:
        """The first tick and wake 0, as the server's begin."""
        return play(self, self.briefings, self.now)

    def close(self, at: datetime | None = None) -> runner.TickRun:
        """The tick at ``at`` (default: the open wake's deadline): the wake closes, the
        aide plays any human seat that has not committed, and the next wake opens."""
        if at is None:
            open_wake = self.state.wake
            assert open_wake is not None and not open_wake.closed
            at = open_wake.deadline
        self.now = at
        return play(self, self.briefings, at)

    def wake_number(self) -> int:
        current = self.state.wake
        assert current is not None
        return current.number


Step = Callable[[AsyncTable, int], None]
"""One act in a wake's script, given the wake number."""


def run_wakes(table: AsyncTable, script: Sequence[Step], wakes: int) -> None:
    """Open play, then each wake: the script's acts in order, then the close."""
    table.open_play()
    for n in range(wakes):
        assert table.wake_number() == n
        for step in script:
            step(table, n)
        table.close()


def digest(state: State) -> str:
    """blake2b-128 over the state's canonical JSON, less how it was reached: the record
    count and the wake's commit set. Everything the world holds is in it."""
    dumped = state.model_dump(mode="json")
    for field in DIGEST_LEAVES_OUT:
        dumped.pop(field)
    if dumped.get("wake") is not None:
        dumped["wake"].pop("committed")
    canon = json.dumps(dumped, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.blake2b(canon.encode(), digest_size=16).hexdigest()


def papers(state: State, seat: SeatId) -> list[tuple[Any, ...]]:
    """The shape of every paper the seat holds: kind, author, channel, classification,
    title, the days it was written and reached the seat, and its lines' labels."""
    held = [d.view for d in state.documents.values() if seat in d.view.scope.known_by]
    return sorted(
        (
            str(v.kind),
            v.author,
            str(v.channel),
            str(v.classification),
            v.title,
            v.issued,
            v.arrives,
            tuple((line.label, line.unit) for line in v.body),
        )
        for v in held
    )


def answer_days(state: State, seat: SeatId) -> list[tuple[str, date | None]]:
    """For each part of each order the seat filed: its words and the day its answer
    reaches the seat, or None when no day is set."""
    out: list[tuple[str, date | None]] = []
    for order in sorted(state.routed.values(), key=lambda o: (o.filed, o.order_id)):
        if order.issuer != seat:
            continue
        for i, part in enumerate(order.parts):
            due = advance.answer_due(state, order, i)
            out.append((part.ask, None if due is None else due[0]))
    return out
