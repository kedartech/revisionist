"""One notice per wake opening (NTC): its text, its transports, the sent table and the
``notice-address`` game action.

A notice leaves the game, so it must say nothing about another seat's commit,
presence or aide play: the same text whether the others are at the table or away.
"""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.realism import advance
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask
from revisionist.engine import notice, options, wake_open
from revisionist.engine.store import EventStore, MemoryStore
from tests.async_table import AsyncTable
from tests.test_engine_v2_wake import CAMPAIGN
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, seat_of

WORLD = "engine-v2-slice-1941"
GAME = "The slice"


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncTable:
    return AsyncTable(MemoryStore(), monkeypatch, tmp_path)


def no_aide(monkeypatch: pytest.MonkeyPatch) -> None:
    """The aide files nothing, so an aide-played seat leaves the world as a quiet one."""
    monkeypatch.setattr(options, "aide_asks", lambda *_a, **_k: [])


class Recorder:
    """A notifier that records each wake it is told has opened."""

    def __init__(self) -> None:
        self.opened: list[int] = []

    def wake_opened(self, store: EventStore, campaign_id: CampaignId, wake: int) -> int:
        self.opened.append(wake)
        return 0


# --- the text -----------------------------------------------------------------


def test_the_text_names_the_wake_the_date_the_close_and_the_aide(table: AsyncTable) -> None:
    t = table
    t.open_play()
    t.close()
    state = t.state
    assert state.wake is not None and state.wake.number == 1
    subject, text = notice.compose(state, t.fdr, "America/Los_Angeles", GAME)
    assert "wake 1" in subject.lower() and GAME in subject
    assert "Wake 1" in text
    today = state.in_world_date
    assert today is not None
    assert f"{today.day} {today:%B %Y}" in text
    close = state.wake.deadline.astimezone(notice.zone_of("America/Los_Angeles"))
    assert f"{close:%H:%M}" in text and "America/Los_Angeles" in text
    assert "your aide plays your seat" in text


def test_the_close_is_in_new_york_time_when_no_zone_is_set(table: AsyncTable) -> None:
    t = table
    t.open_play()
    t.close()
    state = t.state
    assert state.wake is not None
    _, text = notice.compose(state, t.fdr, None, GAME)
    close = state.wake.deadline.astimezone(notice.zone_of(notice.DEFAULT_ZONE))
    assert f"{close:%H:%M}" in text and "America/New_York" in text


def test_a_request_from_another_seat_is_listed(table: AsyncTable) -> None:
    t = table
    t.open_play()
    churchill = t.entity("churchill")
    words = "Ask the Prime Minister to take fifty old destroyers"
    gift = rx.Allocate(recipient=churchill, what="old destroyers", amount=50, unit="ships")
    t.file(t.fdr, Ask(ask=words, target=churchill, effect=gift))
    for _ in range(6):  # close wakes until the request has reached him
        t.close()
        today = t.state.in_world_date
        assert today is not None
        if advance.awaiting(t.state, t.churchill, today):
            break
    state = t.state
    _, churchill_text = notice.compose(state, t.churchill, None, GAME)
    _, fdr_text = notice.compose(state, t.fdr, None, GAME)
    assert "Before you:" in churchill_text
    assert words in churchill_text and "Roosevelt" in churchill_text
    assert words not in fdr_text  # his own ask is not before him


def test_nothing_waiting_names_no_other_seat_and_no_commit(table: AsyncTable) -> None:
    t = table
    t.open_play()
    t.commit(t.churchill)
    t.close()
    _, text = notice.compose(t.state, t.fdr, None, GAME)
    lowered = text.lower()
    assert "churchill" not in lowered
    for word in ("commit", "present", "away", "aide played", "timed out", "waiting on"):
        assert word not in lowered, word


def _fdr_text_after_one_wake(t: AsyncTable, churchill_present: bool) -> str:
    t.open_play()
    t.commit(t.fdr)
    if churchill_present:
        t.commit(t.churchill)
    t.close()
    return notice.compose(t.state, t.fdr, None, GAME)[1]


def test_the_text_is_the_same_whether_the_other_seat_was_present_or_away(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Invariant 2 on the notice: Churchill committing or the aide playing him leaves
    Roosevelt's notice word for word the same."""
    no_aide(monkeypatch)
    present = _fdr_text_after_one_wake(
        AsyncTable(MemoryStore(), monkeypatch, tmp_path / "a"), churchill_present=True
    )
    away = _fdr_text_after_one_wake(
        AsyncTable(MemoryStore(), monkeypatch, tmp_path / "b"), churchill_present=False
    )
    assert present == away


# --- the hook -----------------------------------------------------------------


def test_after_open_runs_for_each_wake_after_the_first(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = Recorder()
    monkeypatch.setattr(notice, "for_store", lambda _store: seen)
    t = table
    t.open_play()
    assert seen.opened == [], "no notice for wake 0"
    t.commit(t.fdr)
    assert seen.opened == [], "a commit sends nothing"
    t.close()
    t.close()
    assert seen.opened == [1, 2]


def test_a_failing_notifier_never_stops_the_tick(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        def wake_opened(self, *_a: Any) -> int:
            raise OSError("mail server down")

    monkeypatch.setattr(notice, "for_store", lambda _store: Broken())
    t = table
    t.open_play()
    t.close()
    assert t.wake_number() == 1


def test_after_open_skips_wake_zero_and_a_missing_notifier() -> None:
    seen = Recorder()
    store = MemoryStore()
    wake_open.after_open(store, CAMPAIGN, 0, notifier=seen)
    wake_open.after_open(store, CAMPAIGN, 3, notifier=None)
    assert seen.opened == []


# --- transports -----------------------------------------------------------------


def a_notice(to: str = "ada@example.test") -> notice.Notice:
    return notice.Notice(
        campaign_id=CAMPAIGN,
        seat_id=SeatId("s1"),
        wake=2,
        to=to,
        subject="The slice: wake 2 is open",
        text="Wake 2 of The slice is open.",
    )


def test_the_outbox_writes_one_json_line_per_message(tmp_path: Path) -> None:
    box = tmp_path / "out" / "outbox.jsonl"
    sender = notice.Outbox(box)
    sender.send(a_notice("ada@example.test"))
    sender.send(a_notice("bea@example.test"))
    lines = [json.loads(x) for x in box.read_text().splitlines()]
    assert [x["to"] for x in lines] == ["ada@example.test", "bea@example.test"]
    assert lines[0]["subject"] == "The slice: wake 2 is open"
    assert lines[0]["text"] == "Wake 2 of The slice is open."
    assert lines[0]["wake"] == 2


class FakeSmtp:
    """Stands in for ``smtplib.SMTP`` / ``SMTP_SSL``: records what was asked of it."""

    def __init__(self, calls: list[Any], host: str, port: int, tls: bool) -> None:
        self.calls = calls
        calls.append(("connect", host, port, tls))

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_a: Any) -> None:
        self.calls.append(("quit",))

    def starttls(self, **_k: Any) -> None:
        self.calls.append(("starttls",))

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user, password))

    def send_message(self, msg: Any) -> None:
        self.calls.append(("send", msg["From"], msg["To"], msg["Subject"], msg.get_content()))


def fake_connect(calls: list[Any]) -> Any:
    return lambda host, port, tls: FakeSmtp(calls, host, port, tls)


def test_smtp_starts_tls_logs_in_and_sends() -> None:
    calls: list[Any] = []
    sender = notice.Smtp(
        "smtp://rv%40example.test:p%40ss@mail.example.test:587",
        "Revisionist <rv@example.test>",
        connect=fake_connect(calls),
    )
    sender.send(a_notice())
    assert calls == [
        ("connect", "mail.example.test", 587, False),
        ("starttls",),
        ("login", "rv@example.test", "p@ss"),
        (
            "send",
            "Revisionist <rv@example.test>",
            "ada@example.test",
            "The slice: wake 2 is open",
            "Wake 2 of The slice is open.\n",
        ),
        ("quit",),
    ]


def test_smtps_connects_with_tls_and_sends_from_the_login() -> None:
    calls: list[Any] = []
    sender = notice.Smtp(
        "smtps://rv%40example.test:pw@mail.example.test", None, connect=fake_connect(calls)
    )
    sender.send(a_notice())
    assert calls[0] == ("connect", "mail.example.test", 465, True)
    assert ("starttls",) not in calls
    assert calls[2][1] == "rv@example.test"


def test_the_sender_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert notice.sender_from_env() is None, "nothing set: nothing is sent"
    monkeypatch.setenv(notice.OUTBOX_ENV, str(tmp_path / "o.jsonl"))
    assert isinstance(notice.sender_from_env(), notice.Outbox)
    monkeypatch.setenv(notice.SMTP_ENV, "smtp://u:p@mail.example.test:587")
    assert isinstance(notice.sender_from_env(), notice.Smtp)
    monkeypatch.setenv(notice.SMTP_ENV, "http://mail.example.test")
    assert notice.sender_from_env() is None, "a bad SMTP URL turns notices off"


def test_a_store_without_the_web_tables_gets_no_notifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(notice.OUTBOX_ENV, str(tmp_path / "o.jsonl"))
    assert notice.for_store(MemoryStore()) is None


# --- on the web (Postgres) ---------------------------------------------------------


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    box = tmp_path / "outbox.jsonl"
    monkeypatch.setenv(notice.OUTBOX_ENV, str(box))
    return box


def sent(box: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in box.read_text().splitlines()] if box.exists() else []


def address(client: Client, **body: Any) -> dict[str, Any]:
    status, out = client.call("/api/game/notice-address", body)
    assert status == 200, out
    return dict(out)


def two_seats(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    bea = game.seat("bea", "churchill")
    make_host(game, ada)
    begin(game)
    return game, ada, bea


def test_two_humans_get_one_message_each_and_a_commit_gets_none(
    web: Web,  # noqa: F811
    outbox: Path,
) -> None:
    game, ada, bea = two_seats(web)
    address(ada, address="ada@example.test")
    address(bea, address="bea@example.test", zone="Europe/London")
    assert sent(outbox) == [], "no notice for wake 0"
    post(ada, "commit")
    assert sent(outbox) == [], "a commit sends nothing"
    post(bea, "commit")
    assert realism_of(ada)["wake"]["wake"] == 1
    lines = sent(outbox)
    assert sorted(x["to"] for x in lines) == ["ada@example.test", "bea@example.test"]
    assert {x["wake"] for x in lines} == {1}
    post(ada, "commit")
    assert len(sent(outbox)) == 2, "a commit in wake 1 sends nothing either"
    by_to = {x["to"]: x for x in lines}
    assert "Europe/London" in by_to["bea@example.test"]["text"]
    assert "America/New_York" in by_to["ada@example.test"]["text"]
    assert "Churchill" not in by_to["ada@example.test"]["text"]
    assert "Roosevelt" not in by_to["bea@example.test"]["text"]
    assert by_to["ada@example.test"]["seat"] == seat_of(game, "roosevelt")


def test_a_resumed_open_sends_nothing_twice(web: Web, outbox: Path) -> None:  # noqa: F811
    game, ada, bea = two_seats(web)
    address(ada, address="ada@example.test")
    address(bea, address="bea@example.test")
    post(ada, "commit")
    post(bea, "commit")
    assert len(sent(outbox)) == 2
    store = web.app.open()
    try:
        again = notice.for_store(store)
        assert again is not None
        wake_open.after_open(store, game.campaign, 1, notifier=again)
    finally:
        store.close()
    assert len(sent(outbox)) == 2


def test_a_seat_without_an_address_gets_nothing(web: Web, outbox: Path) -> None:  # noqa: F811
    _, ada, bea = two_seats(web)
    address(ada, address="ada@example.test")
    post(ada, "commit")
    post(bea, "commit")
    assert [x["to"] for x in sent(outbox)] == ["ada@example.test"]


def test_no_outbox_and_no_smtp_sends_nothing(
    web: Web,  # noqa: F811
    tmp_path: Path,
) -> None:
    _, ada, bea = two_seats(web)
    address(ada, address="ada@example.test")
    post(ada, "commit")
    post(bea, "commit")
    assert realism_of(ada)["wake"]["wake"] == 1
    assert not list(tmp_path.rglob("*.jsonl"))


def test_the_address_action_reads_sets_and_clears(web: Web) -> None:  # noqa: F811
    _, ada, bea = two_seats(web)
    first = address(bea)
    assert first == {
        "reply": first["reply"],
        "refused": False,
        "address": "",
        "zone": "America/New_York",
    }
    out = address(bea, address="bea@example.test", zone="Europe/London")
    assert not out["refused"] and out["address"] == "bea@example.test"
    assert out["zone"] == "Europe/London"
    out = address(bea, zone="Asia/Tokyo")
    assert out["address"] == "bea@example.test" and out["zone"] == "Asia/Tokyo"
    assert address(bea)["zone"] == "Asia/Tokyo"
    assert address(ada)["address"] == "", "one account's address is its own"
    out = address(bea, address="")
    assert not out["refused"] and out["address"] == "" and out["zone"] == "Asia/Tokyo"


@pytest.mark.parametrize(
    "body",
    [
        {"address": "not an address"},
        {"address": "a@b"},
        {"address": 7},
        {"zone": "Mars/Olympus"},
        {"zone": "../etc"},
        {"zone": ""},
    ],
)
def test_the_address_action_refuses_a_bad_value(web: Web, body: dict[str, Any]) -> None:  # noqa: F811
    _, _, bea = two_seats(web)
    address(bea, address="bea@example.test")
    out = address(bea, **body)
    assert out["refused"] is True
    assert out["address"] == "bea@example.test" and out["zone"] == "America/New_York"


@pytest.fixture
def no_tables(web: Web) -> Iterator[None]:  # noqa: F811
    """The room before ``db migrate`` has run 0012."""
    with psycopg.connect(web.db.admin_dsn, autocommit=True) as conn:
        conn.execute("DROP TABLE web_notice_addresses, web_notices_sent")
    notice.forget_missing()
    yield
    notice.forget_missing()


def test_missing_tables_read_as_empty_and_log_once(
    web: Web,  # noqa: F811
    outbox: Path,
    no_tables: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, ada, bea = two_seats(web)
    with caplog.at_level(logging.WARNING, logger="revisionist.engine.notice"):
        out = address(ada, address="ada@example.test")
        assert out["refused"] is True and out["address"] == ""
        for _ in range(2):
            post(ada, "commit")
            post(bea, "commit")
    assert realism_of(ada)["wake"]["wake"] == 2
    assert sent(outbox) == []
    missing = [r for r in caplog.records if "web_notice_addresses" in r.getMessage()]
    assert len(missing) == 1


def test_a_send_that_fails_is_not_marked_sent(
    web: Web,  # noqa: F811
    outbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game, ada, bea = two_seats(web)
    address(ada, address="ada@example.test")
    real = notice.Outbox.send

    def down(self: notice.Outbox, n: notice.Notice) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(notice.Outbox, "send", down)
    post(ada, "commit")
    post(bea, "commit")
    assert sent(outbox) == []
    monkeypatch.setattr(notice.Outbox, "send", real)
    store = web.app.open()
    try:
        wake_open.after_open(store, game.campaign, 1, notifier=notice.for_store(store))
    finally:
        store.close()
    assert [x["to"] for x in sent(outbox)] == ["ada@example.test"]


def test_the_web_text_is_the_same_whether_the_other_seat_committed_or_not(
    web: Web,  # noqa: F811
    outbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ada's notice for wake 1 is word for word the same whether Bea pressed Done or
    the host closed the wake and the aide played her."""
    no_aide(monkeypatch)
    texts: list[str] = []
    for n, bea_present in enumerate((True, False)):
        game = Realism(web, world=WORLD)
        ada = game.seat(f"ada{n}", "roosevelt")
        bea = game.seat(f"bea{n}", "churchill")
        make_host(game, ada)
        begin(game)
        address(ada, address=f"ada{n}@example.test")
        if bea_present:
            post(bea, "commit")
            post(ada, "commit")
        else:
            post(ada, "commit")
            status, out = post(ada, "close")
            assert status == 200 and not out["refused"], out
        mine = [x for x in sent(outbox) if x["to"] == f"ada{n}@example.test"]
        assert len(mine) == 1
        texts.append(mine[0]["text"])
    assert texts[0] == texts[1]


def test_the_deadline_is_the_open_wakes(table: AsyncTable) -> None:
    """The close named is the deadline set at the open, which no commit moves."""
    t = table
    t.open_play()
    t.close()
    state = t.state
    assert state.wake is not None
    t.commit(t.fdr)
    assert notice.compose(t.state, t.fdr, None, GAME) == notice.compose(state, t.fdr, None, GAME)


def test_zone_of_falls_back_on_a_bad_name() -> None:
    assert notice.zone_of("Mars/Olympus").key == notice.DEFAULT_ZONE
    assert notice.zone_of(None).key == notice.DEFAULT_ZONE
    assert notice.zone_of("Europe/London").key == "Europe/London"
    assert datetime(2026, 7, 1, tzinfo=UTC).astimezone(notice.zone_of("Europe/London")).hour == 1


# --- the report digest (RPS) --------------------------------------------------------

DAY = date(2026, 11, 22)
COUNTS = {"The slice": {"bug": 1, "idea": 2}, "Toy": {"confusing": 1}}


def test_the_report_digest_counts_by_kind_and_game() -> None:
    subject, text = notice.compose_digest(DAY, COUNTS)
    assert subject == "Revisionist: 4 reports on Sunday 22 November 2026"
    assert text.splitlines() == [
        "Reports filed on Sunday 22 November 2026 (UTC): 1 bug, 2 ideas, 1 marked confusing.",
        "",
        "By game:",
        "- The slice: 1 bug, 2 ideas.",
        "- Toy: 1 marked confusing.",
        "",
        "Read them with: revisionist reports list",
    ]


def test_a_digest_goes_once_a_day_and_a_failed_send_is_not_marked(
    web: Web,  # noqa: F811
    outbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = notice.Outbox.send

    def down(self: notice.Outbox, n: notice.Notice) -> None:
        raise OSError("disk full")

    box = notice.Outbox(outbox)
    with psycopg.connect(web.db.app_dsn, autocommit=True) as conn:
        monkeypatch.setattr(notice.Outbox, "send", down)
        assert notice.send_digest(conn, box, "op@example.test", DAY, COUNTS) is False
        monkeypatch.setattr(notice.Outbox, "send", real)
        assert notice.send_digest(conn, box, "op@example.test", DAY, COUNTS) is True
        assert notice.send_digest(conn, box, "op@example.test", DAY, COUNTS) is False
        assert notice.send_digest(conn, box, "op@example.test", DAY, {}) is False
    (line,) = sent(outbox)
    assert line["to"] == "op@example.test" and line["subject"].startswith("Revisionist: 4 reports")
