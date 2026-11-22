"""The wake report (WRP): how each wake closed, the aide's wakes and the hours to each
commit per seat, and whether catch-up gave a page for every wake a returning seat missed;
with aims on, each seat's aims met, at risk and failed per wake (SCD).
An operator command; invariant 5 keeps it away from every seat.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from revisionist import cli
from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.fold import replay
from revisionist.core.ids import FeatureId
from revisionist.core.ontology import Controller
from revisionist.core.realism import detect, economy
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask
from revisionist.engine import catchup, options, wake, wake_report
from revisionist.engine.store import MemoryStore, SqliteStore, StoreError
from tests import test_adjacency_moves as adj
from tests import test_detection as det
from tests import test_economy as te
from tests import test_realism_aims as ta
from tests import test_web_forecast as tf
from tests.test_adjacency_moves import day, entity
from tests.test_engine_v2_contract import CAMPAIGN as V2_CAMPAIGN
from tests.test_engine_v2_wake import CAMPAIGN, T0, Table
from tests.test_territory_model import CAMPAIGN as TOY_CAMPAIGN

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


@pytest.fixture
def aided(monkeypatch: pytest.MonkeyPatch) -> Table:
    """The same table, with an aide that files one order for an absent seat in each wake
    it plays: the Home Fleet to Reykjavik in the even wakes, to Scapa Flow in the odd.
    (The aide may not file the First Sea Lord's dismissal: it is irreversible.)"""
    holder: list[Table] = []

    def asks(state, seat, transport):  # type: ignore[no-untyped-def]
        assert state.wake is not None
        t = holder[0]
        port = "reykjavik" if state.wake.number % 2 == 0 else "scapa_flow"
        move = rx.MoveForce(
            force=FeatureId(t.ids["home_fleet"]), to=t.entity(port), posture=rx.Posture.ESCORT
        )
        return [(Ask(ask=f"send the Home Fleet to {port}", effect=move, target=None),)]

    monkeypatch.setattr(options, "aide_asks", asks)
    holder.append(Table(MemoryStore()))
    return holder[0]


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


def test_a_return_is_covered_when_the_catch_up_reply_serves_every_missed_wake_a_note(
    aided: Table,
) -> None:
    """The aide filed for Churchill in wakes 0 and 1: each page carries its note."""
    report = wake_report.build(played(aided))
    assert [(r.seat_id, r.wake, r.missed, r.uncovered, r.covered) for r in report.returns] == [
        (aided.winston, 2, (0, 1), (), True)
    ]


def test_a_return_is_not_covered_when_the_missed_wakes_hold_only_their_openings(
    table: Table,
) -> None:
    """A real log, no patched feed: the aide files nothing, so wakes 0 and 1 hold for
    Churchill only the public ``wake_opened`` and ``date_advanced`` the catch-up reply
    gives no page for. Counted on any event in the feed, these wakes would read covered."""
    events = played(table)
    report = wake_report.build(events)
    assert [(r.seat_id, r.wake, r.missed, r.uncovered, r.covered) for r in report.returns] == [
        (table.winston, 2, (0, 1), (0, 1), False)
    ]
    fed = catchup.feed(replay(events), events, table.winston, 0, 1)  # type: ignore[arg-type]
    assert {f.wake for f in fed} == {0, 1}  # events, but no page


def test_the_feed_is_read_as_the_log_stood_at_the_return(
    aided: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[int, int, int | None]] = []
    real = catchup.feed

    def spy(state, events, seat, first, last):  # type: ignore[no-untyped-def]
        events = list(events)
        seen.append((first, last, state.wake.number if state.wake else None))
        assert max(e.seq for e in events) == state.last_seq
        return real(state, events, seat, first, last)

    monkeypatch.setattr(catchup, "feed", spy)
    wake_report.build(played(aided))
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


def test_the_text_names_the_wakes_the_seats_and_the_returns(aided: Table) -> None:
    text = wake_report.render(wake_report.build(played(aided)))
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


def test_the_text_names_the_wakes_that_had_no_page(table: Table) -> None:
    text = wake_report.render(wake_report.build(played(table)))
    assert "catch-up: 1 return after a missed wake; 0 with a page for every wake missed" in text
    assert (
        "  Winston Churchill returned in wake 2 after missing 0-1: no page for 2 wakes 0-1" in text
    )


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


# --- WEV rule 4: per wake, the territories that changed holder and each nation's figure


def territory_log(tmp: Path) -> list[Event]:
    """The toy territory world with the economy on and the Isle yielding 4 iron. Wake 0:
    Norra takes the Isle. Wake 1: nothing changes hands. Wake 2 is open."""
    g = te.game(tmp, te.yields(te.ISLE, iron=4))
    at = T0
    g.add([ev.WakeOpened(wake=0, deadline=at + 12 * HOUR, opened_at=at)])
    te.taken(g, te.ISLE, te.NORRA, day(1))
    for n in (0, 1):
        at += 12 * HOUR
        g.add(
            [
                ev.WakeClosed(wake=n, how="deadline"),
                ev.WakeOpened(wake=n + 1, deadline=at + 12 * HOUR, opened_at=at),
            ]
        )
    return g.log


def test_each_wake_names_the_territories_that_changed_holder(tmp_path: Path) -> None:
    report = wake_report.build(territory_log(tmp_path))
    assert [(h.number, h.changes) for h in report.holdings] == [
        (0, (("The Isle", "Norra", "Sudland"),)),
        (1, ()),
        (2, ()),
    ]


def test_each_wake_gives_every_nations_figure_at_its_end(tmp_path: Path) -> None:
    log = territory_log(tmp_path)
    state = replay(log)
    figures = (
        ("Norra", economy.figure(state, entity(te.NORRA))),
        ("Sudland", economy.figure(state, entity(te.SUDLAND))),
    )
    report = wake_report.build(log)
    assert [h.figures for h in report.holdings] == [figures] * 3
    assert figures[1][1] < 100 == figures[0][1]


def test_the_holder_and_figure_lines_follow_each_wake(tmp_path: Path) -> None:
    out = wake_report.render(wake_report.build(territory_log(tmp_path)))
    at = out.index("  wake 0: deadline")
    assert out[at : at + 7] == [
        "  wake 0: deadline",
        "    holders: The Isle to Norra from Sudland",
        "    figures: Norra 100.0, Sudland 1.2",
        "  wake 1: deadline",
        "    holders: no change",
        "    figures: Norra 100.0, Sudland 1.2",
        "  wake 2: open",
    ]


def test_a_game_without_holders_prints_no_holder_lines(table: Table) -> None:
    report = wake_report.build(played(table))
    assert report.holdings == ()
    assert not any("holders:" in line for line in wake_report.render(report))


# --- Battles per wake (BTD) ---------------------------------------------------------------


def battle_log(tmp: Path) -> list[Event]:
    """The coast's battle toy (``tests/test_battle_decisions.py``): wake 0 opened on day 0,
    the walk to the day after the battle opened, then wake 1 and two more days."""
    from datetime import UTC, datetime

    from tests.test_adjacency_moves import levers
    from tests.test_battle_decisions import ISLE
    from tests.test_battle_decisions_land import army
    from tests.test_battles import COAST, OPENS, link, no_ferry, to_coast

    now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    g = to_coast(tmp, link(COAST, ISLE), no_ferry, levers, army)
    g.add([ev.WakeOpened(wake=0, deadline=now, opened_at=now)])
    g.walk(day(1), OPENS + timedelta(days=1))
    g.add(
        [
            ev.WakeClosed(wake=0, how="deadline"),
            ev.WakeOpened(wake=1, deadline=now + timedelta(hours=12), opened_at=now),
        ]
    )
    g.walk(OPENS + timedelta(days=2), OPENS + timedelta(days=3))
    return g.log


def test_each_wake_counts_battles_opened_rounds_fought_and_battles_ended(
    tmp_path: Path,
) -> None:
    log = battle_log(tmp_path)
    by_wake: dict[int, list[int]] = {}
    number = -1
    for e in log:
        if isinstance(e.payload, ev.WakeOpened):
            number = e.payload.wake
            by_wake[number] = [0, 0, 0]
        for i, kind in enumerate((ev.BattleOpened, ev.BattleRound, ev.BattleEnded)):
            if isinstance(e.payload, kind) and number >= 0:
                by_wake[number][i] += 1
    assert by_wake[0][:2] == [1, 2] and by_wake[1][1] >= 1
    report = wake_report.build(log)
    assert [(f.number, f.opened, f.rounds, f.ended) for f in report.fighting] == [
        (n, *c) for n, c in sorted(by_wake.items())
    ]
    out = wake_report.render(report)
    at = out.index("  wake 0: deadline")
    assert f"    battles: 1 opened, 2 rounds fought, {by_wake[0][2]} ended" in out[at : at + 4]


def test_a_game_without_battles_prints_no_battle_lines(tmp_path: Path) -> None:
    report = wake_report.build(territory_log(tmp_path))
    assert report.fighting == ()
    assert not any("battles:" in line for line in wake_report.render(report))


# --- RPD rule 5: per wake, the reports made by source and the share that were wrong ----


def _careless(w: adj.World) -> None:
    for c in w["cards"]:
        c["competence"] = 0


def wake_log(tmp: Path) -> tuple[adj.Logged, list[list[ev.ReportMade]]]:
    """Wake 0 walks days 1 to 30, wake 1 days 31 to 60; wake 2 opens. Careless Ilse
    reports contact and air for Norra."""
    g = det.game(tmp, det.intelligence(det.norra_sees("contact", "air")), _careless)
    at = T0
    per: list[list[ev.ReportMade]] = []
    g.add([ev.WakeOpened(wake=0, deadline=at + 12 * HOUR, opened_at=at)])
    for n, (first, last) in enumerate(((1, 30), (31, 60))):
        per.append(det.made(g.walk(day(first), day(last))))
        at += 12 * HOUR
        g.add(
            [
                ev.WakeClosed(wake=n, how="deadline"),
                ev.WakeOpened(wake=n + 1, deadline=at + 12 * HOUR, opened_at=at),
            ]
        )
    return g, per


def test_the_wake_report_counts_each_wakes_reports_by_source_and_the_wrong_share(
    tmp_path: Path,
) -> None:
    g, per = wake_log(tmp_path)
    report = wake_report.build(g.log)
    want = []
    for n, out in enumerate(per):
        by = {s: sum(1 for m in out if m.report.source is s) for s in detect.Source}
        wrong = sum(1 for m in out if m.shift is not None)
        want.append((n, tuple((s.value, k) for s, k in by.items() if k), wrong))
    want.append((2, (), 0))
    assert [(w.number, w.by_source, w.wrong) for w in report.intelligence] == want
    assert sum(w for _, _, w in want) > 0  # careless people do get some wrong


def test_the_report_lines_follow_each_wake(tmp_path: Path) -> None:
    g, per = wake_log(tmp_path)
    out = wake_report.render(wake_report.build(g.log))
    first = per[0]
    by = {s: sum(1 for m in first if m.report.source is s) for s in detect.Source}
    wrong = sum(1 for m in first if m.shift is not None)
    total = len(first)
    counts = ", ".join(f"{s.value} {k}" for s, k in by.items() if k)
    at = out.index("  wake 0: deadline")
    assert out[at + 1] == (
        f"    reports: {counts}; {wrong} of {total} wrong ({100 * wrong / total:.0f}%)"
    )
    assert out[out.index("  wake 2: open") + 1] == "    reports: none"


def test_a_game_without_reports_prints_no_report_lines(tmp_path: Path) -> None:
    report = wake_report.build(territory_log(tmp_path))
    assert report.intelligence == ()
    assert not any("reports:" in line for line in wake_report.render(report))


# --- AGA rule 6: per wake, the clauses judged kept and judged broken ---------------------


def clause_log(tmp: Path) -> list[Event]:
    """AGR's toy (``tests/test_agreements.py``): an agreement whose two dated clauses fall
    due on day 1, the levy on the plain (kept) and on the isle (broken), with a clause of
    wording. Wake 0 is judged through day 1; wake 1 through day 3; wake 2 is open."""
    from tests import test_agreements as agr

    g = agr.game(tmp)
    at = T0
    g.add([ev.WakeOpened(wake=0, deadline=at + 12 * HOUR, opened_at=at)])
    agr.in_force(
        g,
        agr.clause(rx.ClauseType.PLACE, force=agr.LEVY, area=agr.PLAIN, on=day(1)),
        agr.clause(rx.ClauseType.PLACE, force=agr.LEVY, area=agr.ISLE, on=day(1)),
        agr.clause(rx.ClauseType.UNCHECKED, text="Friendship."),
    )
    agr.judged(g, day(1), day(1))
    for n, last in ((0, day(3)), (1, None)):
        at += 12 * HOUR
        g.add(
            [
                ev.WakeClosed(wake=n, how="deadline"),
                ev.WakeOpened(wake=n + 1, deadline=at + 12 * HOUR, opened_at=at),
            ]
        )
        if last is not None:
            agr.judged(g, day(2), last)
    return g.log


def test_each_wake_counts_the_clauses_kept_and_broken(tmp_path: Path) -> None:
    log = clause_log(tmp_path)
    by_wake: dict[int, list[int]] = {}
    number = -1
    for e in log:
        p = e.payload
        if isinstance(p, ev.WakeOpened):
            number = p.wake
            by_wake[number] = [0, 0]
        elif isinstance(p, ev.ClauseJudged) and p.status.value in ("kept", "broken"):
            by_wake[number][0 if p.status.value == "kept" else 1] += 1
    assert by_wake[0] == [1, 1]
    report = wake_report.build(log)
    assert [(c.number, c.kept, c.broken) for c in report.clauses] == [
        (n, *c) for n, c in sorted(by_wake.items())
    ]
    out = wake_report.render(report)
    at = out.index("  wake 0: deadline")
    assert "    clauses: 1 kept, 1 broken" in out[at : at + 4]
    at = out.index("  wake 2: open")
    assert "    clauses: 0 kept, 0 broken" in out[at : at + 4]


def test_a_called_or_void_clause_is_neither_kept_nor_broken(tmp_path: Path) -> None:
    log = clause_log(tmp_path)
    called = [
        e.model_copy(update={"payload": e.payload.model_copy(update={"status": status})})
        for e in log
        if isinstance(e.payload, ev.ClauseJudged)
        for status in ("called", "void", "standing")
    ][:3]
    seq = log[-1].seq
    extra = [c.model_copy(update={"seq": seq + 1 + n}) for n, c in enumerate(called)]
    report = wake_report.build([*log, *extra])
    assert report.clauses[-1].kept == 0 and report.clauses[-1].broken == 0


def test_a_game_without_agreements_prints_no_clause_lines(tmp_path: Path) -> None:
    report = wake_report.build(territory_log(tmp_path))
    assert report.clauses == ()
    assert not any("clauses:" in line for line in wake_report.render(report))


# --- aims met, at risk and failed (SCD) -----------------------------------------------


PLAIN_SUDLAND: ta.World = {"check": "holds_area", "area": "norra_plain", "holder": "sudland"}


def aims_log(tmp: Path) -> list[Event]:
    """The toy world with aims on: Ilse's three aims (the hills, held; the isle, not yet;
    Sudland's hills by the first day, missed) and Tomas's two (the isle, held; the Norra
    plain, not yet), both seats played by people, over two wakes."""
    ilse = (
        ta.rule(1, ta.HILLS_HELD),
        ta.rule(2, ta.ISLE_HELD),
        ta.rule(3, {**ta.HILLS_HELD, "holder": "sudland"}, deadline=ta.day(1).isoformat()),
    )

    tomas = (ta.rule(1, {**ta.ISLE_HELD, "holder": "sudland"}), ta.rule(2, PLAIN_SUDLAND))

    def lines(w: ta.World) -> None:
        w["cards"][0]["aims"] = ["One.", "Two.", "Three."]
        w["cards"][1]["aims"] = ["Hold the isle.", "Take the plain."]

    g = ta.Game(ta.world(tmp, ta.aims(ilse=ilse, tomas=tomas), lines))
    g.hand(ta.TOMAS, Controller.HUMAN)
    for n in (1, 2):
        g.land(ev.WakeOpened(wake=n, deadline=ta.DEADLINE))
        g.tick()
        g.land(ev.WakeClosed(wake=n))
    return list(g.store.read(TOY_CAMPAIGN))


def test_each_wake_counts_each_seats_aims_met_at_risk_and_failed(tmp_path: Path) -> None:
    log = aims_log(tmp_path)
    state = replay(log)
    ilse = state.seats[ta.seat_of(state, ta.ILSE)].name
    tomas = state.seats[ta.seat_of(state, ta.TOMAS)].name
    report = wake_report.build(log)
    want = tuple(sorted([(ilse, 1, 1, 1), (tomas, 1, 1, 0)]))
    assert [a.number for a in report.aims] == [0, 1, 2]
    assert report.aims[0].seats == ()  # goals are made by the first tick, in wake 1
    assert [a.seats for a in report.aims[1:]] == [want, want]


def test_the_aims_line_follows_each_wake(tmp_path: Path) -> None:
    log = aims_log(tmp_path)
    state = replay(log)
    ilse = state.seats[ta.seat_of(state, ta.ILSE)].name
    out = wake_report.render(wake_report.build(log))
    at = out.index("  wake 2: unknown")  # closed by a bare record: no reason
    line = out[at + 1 : at + 8]
    aims = [x for x in line if x.startswith("    aims: ")]
    assert len(aims) == 1
    assert f"{ilse} 1 met, 1 at risk, 1 failed" in aims[0]
    assert "One." not in "\n".join(out) and "holds_area" not in "\n".join(out)


def test_the_command_prints_the_aims_per_seat_per_wake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "aims.db"
    store = SqliteStore(path)
    store.append_all(aims_log(tmp_path))
    store.close()
    monkeypatch.setenv("REVISIONIST_DB", str(path))
    code, out = _out()
    assert code == 0, out
    assert out.count("1 met, 1 at risk, 1 failed") == 2
    assert out.count("1 met, 1 at risk, 0 failed") == 2


def test_a_game_without_aims_prints_no_aims_lines(table: Table) -> None:
    report = wake_report.build(played(table))
    assert report.aims == ()
    assert not any(x.startswith("    aims:") for x in wake_report.render(report))


# --- forecasts checked and held (FCK) ---------------------------------------------------


def _forecast_log(raise_house: bool, ticks: int = 3) -> list[Event]:
    """A beginner picked the public statement expecting the House Democrats to rise, and
    the clock ran ``ticks`` ticks (three pass its settling day); the House rose when
    ``raise_house``."""
    store, seat = tf._picked()
    if raise_house:
        tf._raise_house(store, seat, 3)
    tf._ticks(store, ticks)
    return list(store.read(V2_CAMPAIGN))


@pytest.mark.parametrize(
    ("raise_house", "ticks", "checked", "held"),
    [(True, 3, 1, 1), (False, 3, 1, 0), (True, 1, 0, 0)],
)
def test_the_report_counts_forecasts_checked_and_held(
    raise_house: bool, ticks: int, checked: int, held: int
) -> None:
    report = wake_report.build(_forecast_log(raise_house, ticks))
    assert report.forecasts == (checked, held)
    out = wake_report.render(report)
    assert f"forecasts: {checked} checked, {held} held" in out
    assert not any("House Democrats" in line for line in out)


def test_a_game_without_forecasts_prints_no_forecast_line(table: Table) -> None:
    report = wake_report.build(played(table))
    assert report.forecasts is None
    assert not any(x.startswith("forecasts:") for x in wake_report.render(report))


def locks_log(tmp: Path, *changes: Any) -> list[Event]:
    """The lock tests' world (``tests/test_realism_locks.py``). Wake 0: Kara files the
    march to the Isle (held for Ilse) and the march to the hills, asks for the held one,
    and Ilse guards the Gulf. Wake 1: the clock runs until the held march lands."""
    from revisionist.core.realism import locks
    from revisionist.engine import realism_tick
    from revisionist.engine.store import load_state
    from tests import test_realism_locks as lk

    store = lk.played(tmp, *changes)

    def add(*payloads: ev.Payload) -> None:
        for p in payloads:
            realism_tick._append(store, load_state(store, TOY_CAMPAIGN), p, lk.seat(lk.ILSE))

    add(ev.WakeOpened(wake=0, deadline=T0 + 12 * HOUR, opened_at=T0))
    held = lk.file(store, "isle")
    lk.file(store, "norra_hills")
    if locks.on(load_state(store, TOY_CAMPAIGN)):
        lk.ask(store, held.order_id)
    lk.commit(store, lk.ILSE, lk.guard_the_gulf())
    add(
        ev.WakeClosed(wake=0, how="deadline"),
        ev.WakeOpened(wake=1, deadline=T0 + 24 * HOUR, opened_at=T0 + 12 * HOUR),
    )
    lk.tick_until(store, lambda s: held.order_id not in s.held)
    return list(store.read(TOY_CAMPAIGN))


def test_each_wake_counts_per_seat_orders_filed_held_asked_and_opened(tmp_path: Path) -> None:
    report = wake_report.build(locks_log(tmp_path))
    assert [(x.number, x.seats) for x in report.locked] == [
        (0, (("Ilse Varg", 1, 0, 0, 0), ("Kara Lind", 2, 1, 1, 0))),
        (1, (("Kara Lind", 0, 0, 0, 1),)),
    ]
    out = wake_report.render(report)
    first = out.index("  wake 0: deadline")
    assert out[first + 1] == (
        "    locks: Ilse Varg filed 1, held 0, asked 0, opened 0;"
        " Kara Lind filed 2, held 1, asked 1, opened 0"
    )
    assert out[out.index("  wake 1: open") + 1] == (
        "    locks: Kara Lind filed 0, held 0, asked 0, opened 1"
    )


def test_a_game_without_locks_prints_no_lock_lines(tmp_path: Path) -> None:
    from tests import test_realism_locks as lk

    report = wake_report.build(locks_log(tmp_path, lk.unlocked))
    assert report.locked == ()
    assert not any(x.strip().startswith("locks:") for x in wake_report.render(report))


def test_the_report_counts_the_forms_that_change_nothing(tmp_path: Path) -> None:
    """Every game whose cards have forms prints how many of them change nothing, the count
    ``tests/test_every_form_acts.py`` holds to what the walk finds; 0 is the gate."""
    from revisionist.core.world_compile import compile_world
    from revisionist.engine import campaign as cmp
    from tests.locked_orders_script import autumn_1941

    events = compile_world(autumn_1941(tmp_path), CAMPAIGN, cmp.versions())
    report = wake_report.build(events)
    here = {c.person for c in autumn_1941(tmp_path).cards}
    assert report.inert == len([f for f in wake_report.inert_forms() if f[0] in here]) > 0
    assert f"forms that change nothing: {report.inert}" in wake_report.render(report)
    assert wake_report.build([]).inert is None
