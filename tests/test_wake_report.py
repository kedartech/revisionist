"""The wake report (WRP): how each wake closed, the aide's wakes and the hours to each
commit per seat, and whether catch-up gave a page for every wake a returning seat missed.
An operator command; invariant 5 keeps it away from every seat.
"""

from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from revisionist import cli
from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.engine import catchup, options, wake, wake_report
from revisionist.engine.store import MemoryStore, SqliteStore, StoreError
from tests.test_engine_v2_wake import CAMPAIGN, T0, Table

runner = CliRunner()

HOUR = timedelta(hours=1)


def played(t: Table) -> list[Event]:
    """Five wakes. Roosevelt commits himself in each of 0 to 3 (1, 2, 1 and 4 hours in);
    Churchill's aide plays 0 and 1, and he commits himself in wake 2 three hours in, so
    he returns after two missed wakes. Wake 0 and 1 close at their deadline, wake 2 with
    everyone committed, wake 3 early by the host with Churchill out; wake 4 is open."""
    assert t.winston is not None
    wake.open_wake(t.store, CAMPAIGN, T0)
    for n, (fdr_at, churchill_at) in enumerate([(1, None), (2, None), (1, 3), (4, None)]):
        opened = t.state.wake.deadline - timedelta(hours=12)  # type: ignore[union-attr]
        wake.commit(t.store, CAMPAIGN, t.fdr, opened + fdr_at * HOUR)
        if churchill_at is not None:
            wake.commit(t.store, CAMPAIGN, t.winston, opened + churchill_at * HOUR)
        early = n == 3
        wake.close_wake(t.store, CAMPAIGN, opened + (6 if early else 12) * HOUR, None)
        wake.open_wake(t.store, CAMPAIGN, opened + (6 if early else 12) * HOUR)
    return list(t.store.read(CAMPAIGN))


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> Table:
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: [])
    return Table(MemoryStore())


def test_each_wake_says_how_it_closed(table: Table) -> None:
    report = wake_report.build(played(table))
    assert [(w.number, w.how) for w in report.wakes] == [
        (0, "deadline"),
        (1, "deadline"),
        (2, "all_committed"),
        (3, "host"),
        (4, "open"),
    ]


def test_per_seat_the_aides_wakes_and_hours_to_each_commit(table: Table) -> None:
    report = wake_report.build(played(table))
    rows = {s.seat_id: s for s in report.seats}
    fdr, churchill = rows[table.fdr], rows[table.winston]  # type: ignore[index]
    assert (fdr.name, fdr.aide_wakes, fdr.hours) == (
        "Franklin D. Roosevelt",
        0,
        (1.0, 2.0, 1.0, 4.0),
    )
    assert (fdr.median, fdr.highest) == (1.5, 4.0)
    assert (churchill.name, churchill.aide_wakes, churchill.hours) == (
        "Winston Churchill",
        3,
        (3.0,),
    )
    assert (churchill.median, churchill.highest) == (3.0, 3.0)


def test_the_aides_commits_are_not_the_players(table: Table) -> None:
    """The aide's commit lands at the deadline, 12 hours in: counted as the player's it
    would make Churchill's highest 12 hours."""
    report = wake_report.build(played(table))
    churchill = next(s for s in report.seats if s.seat_id == table.winston)
    assert churchill.highest == 3.0 and len(churchill.hours) == 1


def test_a_return_after_missed_wakes_is_covered_when_every_one_has_a_page(table: Table) -> None:
    report = wake_report.build(played(table))
    assert [(r.seat_id, r.wake, r.missed, r.covered) for r in report.returns] == [
        (table.winston, 2, (0, 1), True)
    ]


def test_a_return_is_not_covered_when_the_feed_gives_no_page_for_a_missed_wake(
    table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = catchup.feed

    def without_wake_one(state, events, seat, first, last):  # type: ignore[no-untyped-def]
        return tuple(f for f in real(state, events, seat, first, last) if f.wake != 1)

    monkeypatch.setattr(catchup, "feed", without_wake_one)
    report = wake_report.build(played(table))
    assert [r.covered for r in report.returns] == [False]


def test_the_feed_is_read_as_the_log_stood_at_the_return(
    table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[int, int, int | None]] = []
    real = catchup.feed

    def spy(state, events, seat, first, last):  # type: ignore[no-untyped-def]
        events = list(events)
        seen.append((first, last, state.wake.number if state.wake else None))
        assert max(e.seq for e in events) == state.last_seq
        return real(state, events, seat, first, last)

    monkeypatch.setattr(catchup, "feed", spy)
    wake_report.build(played(table))
    assert seen == [(0, 1, 2)]


def test_a_seat_that_commits_every_wake_has_no_return(table: Table) -> None:
    report = wake_report.build(played(table))
    assert all(r.seat_id != table.fdr for r in report.returns)


def test_a_player_who_takes_up_a_seat_someone_left_reads_from_wake_zero(table: Table) -> None:
    assert table.winston is not None
    wake.open_wake(table.store, CAMPAIGN, T0)
    wake.commit(table.store, CAMPAIGN, table.fdr, T0 + HOUR)
    wake.commit(table.store, CAMPAIGN, table.winston, T0 + HOUR)
    wake.close_wake(table.store, CAMPAIGN, T0 + 2 * HOUR, None)
    wake.open_wake(table.store, CAMPAIGN, T0 + 2 * HOUR)
    wake.leave(table.store, CAMPAIGN, table.winston, T0 + 2 * HOUR)
    wake.commit(table.store, CAMPAIGN, table.fdr, T0 + 3 * HOUR)
    wake.close_wake(table.store, CAMPAIGN, T0 + 4 * HOUR, None)
    wake.open_wake(table.store, CAMPAIGN, T0 + 4 * HOUR)
    wake.hand_over(table.store, CAMPAIGN, table.entity("churchill"))
    wake.commit(table.store, CAMPAIGN, table.fdr, T0 + 5 * HOUR)
    wake.close_wake(table.store, CAMPAIGN, T0 + 6 * HOUR, None)
    wake.open_wake(table.store, CAMPAIGN, T0 + 6 * HOUR)
    wake.commit(table.store, CAMPAIGN, table.winston, T0 + 7 * HOUR)
    report = wake_report.build(list(table.store.read(CAMPAIGN)))
    assert [(r.seat_id, r.wake, r.missed) for r in report.returns] == [
        (table.winston, 3, (0, 1, 2))
    ]


def _unrecorded(events: list[Event]) -> list[Event]:
    """The same log as written before the wake record: no opening time, no commit time,
    no close reason."""
    out: list[Event] = []
    for e in events:
        p = e.payload
        if isinstance(p, ev.WakeOpened):
            p = p.model_copy(update={"opened_at": None})
        elif isinstance(p, ev.WakeCommitted):
            p = p.model_copy(update={"at": None})
        elif isinstance(p, ev.WakeClosed):
            p = p.model_copy(update={"how": None})
        out.append(e.model_copy(update={"payload": p}))
    return out


def test_an_older_log_prints_unknown(table: Table) -> None:
    report = wake_report.build(_unrecorded(played(table)))
    assert [w.how for w in report.wakes] == ["unknown"] * 4 + ["open"]
    assert all(s.hours == () and s.unknown_hours > 0 for s in report.seats)
    text = "\n".join(wake_report.render(report))
    assert "  wake 0: unknown" in text
    assert "hours to commit unknown" in text
    assert "median" not in text.split("seat Franklin D. Roosevelt")[1].splitlines()[0]


def test_a_commit_with_no_time_does_not_hide_the_ones_with(table: Table) -> None:
    events = played(table)
    first = next(e for e in events if isinstance(e.payload, ev.WakeCommitted))
    assert isinstance(first.payload, ev.WakeCommitted)
    blanked = [
        e.model_copy(update={"payload": first.payload.model_copy(update={"at": None})})
        if e is first
        else e
        for e in events
    ]
    fdr = next(s for s in wake_report.build(blanked).seats if s.seat_id == table.fdr)
    assert fdr.hours == (2.0, 1.0, 4.0) and fdr.unknown_hours == 1


def test_the_text_names_the_wakes_the_seats_and_the_returns(table: Table) -> None:
    text = wake_report.render(wake_report.build(played(table)))
    assert text[0] == f"campaign {CAMPAIGN}"
    assert "  wake 0: deadline" in text and "  wake 2: all_committed" in text
    assert "  wake 3: host" in text and "  wake 4: open" in text
    assert (
        "seat Franklin D. Roosevelt: aide played 0 wakes; "
        "hours to commit median 1.5, highest 4.0 (4 commits)"
    ) in text
    assert (
        "seat Winston Churchill: aide played 3 wakes; "
        "hours to commit median 3.0, highest 3.0 (1 commit)"
    ) in text
    assert "catch-up: 1 return after a missed wake; 1 with a page for every wake missed" in text
    assert "  Winston Churchill returned in wake 2 after missing 0-1: every wake had a page" in text


def test_a_campaign_with_no_wake_says_so() -> None:
    assert wake_report.render(wake_report.build([])) == ["no wake has opened"]


# --- The command ---------------------------------------------------------------------


def _out(*args: str) -> tuple[int, str]:
    result = runner.invoke(cli.app, ["db", "wake-report", *args])
    return result.exit_code, result.output


@pytest.fixture
def game(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: [])
    path = tmp_path / "wakes.db"
    store = SqliteStore(path)
    played(Table(store))
    store.close()
    monkeypatch.setenv("REVISIONIST_DB", str(path))
    return path


def test_the_command_prints_the_report_for_every_campaign(game: Path) -> None:
    code, out = _out()
    assert code == 0, out
    assert f"campaign {CAMPAIGN}" in out
    assert "wake 3: host" in out and "seat Winston Churchill: aide played 3 wakes" in out


def test_the_command_takes_one_campaign(game: Path) -> None:
    code, out = _out("--campaign", str(CAMPAIGN))
    assert code == 0, out
    assert out.count("campaign ") == 1


def test_the_command_refuses_a_campaign_that_is_not_there(game: Path) -> None:
    code, out = _out("--campaign", "01ARZ3NDEKTSV4RRFFQ69G5FAW")
    assert code == 1 and "no campaign" in out


def test_the_command_says_so_when_the_log_cannot_be_read(
    game: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(store: object, ids: object) -> list[str]:
        raise StoreError("this campaign is sealed: set REVISIONIST_MASTER_KEY_FILE to read it")

    monkeypatch.setattr(wake_report, "lines", refuse)
    code, out = _out()
    assert code == 1 and "this campaign is sealed" in out


def test_the_command_reads_a_database_with_no_campaign(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REVISIONIST_DB", str(tmp_path / "empty.db"))
    code, out = _out()
    assert code == 1 and "no campaigns" in out


def test_no_seat_is_served_the_report() -> None:
    """Invariant 5: an operator command. Nothing a seat reaches imports it."""
    root = Path(wake_report.__file__).parents[1]
    served = [
        p
        for folder in ("engine/web", "engine/discord")
        for p in (root / folder).rglob("*.py")
        if "wake_report" in p.read_text()
    ]
    assert served == []


def test_the_report_has_a_row_for_each_seat_that_committed(table: Table) -> None:
    report = wake_report.build(played(table))
    assert {s.seat_id for s in report.seats} == {table.fdr, table.winston}
