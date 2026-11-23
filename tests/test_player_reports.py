"""Reports that are delivered (RPS): a bug, an idea or something confusing.

A report is filed by the realism action ``report`` (or the seat action ``bug``, or a
question to the aide that opens ``report:``, ``idea:`` or ``bug:``), pinned to its moment
and stored in ``player_reports`` with its words sealed to the seat. It is delivered as a
drop file, in the host's inbox and as a count in one digest a day. Only its author, the
host and the operator read it; no model does. Same harness as ``tests/test_web_held_step.py``.
"""

import json
import stat
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from typer.testing import CliRunner

from revisionist import cli
from revisionist.core.fold import state_hash
from revisionist.engine import aide_help, notice
from revisionist.engine.seal import new_master_key
from revisionist.engine.web import reports
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post
from tests.test_web_wake import begin, seat_of, state_of

runner = CliRunner()
ADA_WORDS = "The harbour toll reads 8 on the map and 9 on my desk."
BRAM_WORDS = "Let me name the ships I build."


@pytest.fixture
def toy(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    game = Realism(web)
    ada = game.seat("ada", "ada")
    bram = game.seat("bram", "bram")
    make_host(game, ada)
    begin(game)
    return game, ada, bram


def rows(game: Realism) -> list[dict[str, Any]]:
    with psycopg.connect(game.web.db.app_dsn) as conn:
        found = conn.execute(
            "SELECT row_to_json(r)::text FROM player_reports r ORDER BY report_id"
        ).fetchall()
    return [json.loads(r[0]) for r in found]


def bugs_table(game: Realism) -> int:
    with psycopg.connect(game.web.db.app_dsn) as conn:
        row = conn.execute("SELECT count(*) FROM discord_bugs").fetchone()
    assert row is not None
    return int(row[0])


def file(client: Client, kind: str, text: str) -> int:
    status, out = post(client, "report", kind=kind, text=text)
    assert status == 200 and out["refused"] is False, out
    assert isinstance(out["report"], int)
    return int(out["report"])


def listed(client: Client, **body: Any) -> dict[str, Any]:
    status, out = post(client, "reports", **body)
    assert status == 200, out
    return dict(out)


# --- rule 1: one action, three kinds, pinned and sealed ---------------------------------


def test_a_report_is_filed_with_its_kind_and_answered_with_its_number(
    toy: tuple[Realism, Client, Client],
) -> None:
    game, ada, _ = toy
    before = state_of(game)
    number = file(ada, "idea", ADA_WORDS)
    (row,) = rows(game)
    assert row["report_id"] == number
    assert row["kind"] == "idea" and row["words"] == ADA_WORDS
    assert row["seat_id"] == seat_of(game, "ada")
    assert row["seq"] == before.last_seq and row["state_hash"] == state_hash(before)
    assert before.wake is not None and row["wake"] == before.wake.number
    assert row["status"] == "new" and row["reply"] == ""
    assert bugs_table(game) == 0, "a new report goes to player_reports only"


@pytest.mark.parametrize("kind", ["bug", "idea", "confusing"])
def test_each_of_the_three_kinds_is_taken(toy: tuple[Realism, Client, Client], kind: str) -> None:
    game, ada, _ = toy
    file(ada, kind, "Words.")
    assert [r["kind"] for r in rows(game)] == [kind]


def test_another_kind_empty_words_and_words_past_the_limit_are_refused(
    toy: tuple[Realism, Client, Client],
) -> None:
    game, ada, _ = toy
    for body in (
        {"kind": "rant", "text": "Words."},
        {"kind": "bug", "text": "   "},
        {"kind": "bug", "text": "x" * (reports.WORDS_MAX + 1)},
    ):
        status, out = post(ada, "report", **body)
        assert status == 200 and out["refused"] is True, (body, out)
    file(ada, "bug", "x" * reports.WORDS_MAX)
    assert len(rows(game)) == 1


def test_the_season_report_is_not_the_new_action(toy: tuple[Realism, Client, Client]) -> None:
    game, ada, _ = toy
    status, _ = ada.call("/api/seat/report", {})
    assert status == 200
    assert rows(game) == [], "the seat family's report is the season report, unchanged"


def test_the_seat_action_bug_files_through_the_same_path(
    toy: tuple[Realism, Client, Client],
) -> None:
    game, ada, _ = toy
    reply = ada.seat("bug", notes=ADA_WORDS)
    (row,) = rows(game)
    assert reply.startswith(f"Bug {row['report_id']} filed"), reply
    assert row["kind"] == "bug" and row["words"] == ADA_WORDS
    assert bugs_table(game) == 0


def test_a_sealed_games_report_is_stored_sealed_to_the_seat(
    web: Web,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key = tmp_path / "master.key"
    new_master_key(key)
    monkeypatch.setenv("REVISIONIST_MASTER_KEY_FILE", str(key))
    game = Realism(web)
    ada = game.seat("ada", "ada")
    make_host(game, ada)
    begin(game)
    file(ada, "bug", ADA_WORDS)
    (row,) = rows(game)
    assert row["words"].startswith("sealed:") and ADA_WORDS not in row["words"]
    (mine,) = listed(ada)["reports"]
    assert mine["words"] == ADA_WORDS, "its author reads it back in plain"
    (inbox,) = listed(ada, inbox=True)["reports"]
    assert inbox["words"] == ADA_WORDS


def test_reports_an_hour_are_capped_per_account(
    toy: tuple[Realism, Client, Client], monkeypatch: pytest.MonkeyPatch
) -> None:
    game, ada, bram = toy
    monkeypatch.setattr(reports, "PER_HOUR", 2)
    file(ada, "bug", "One.")
    file(ada, "bug", "Two.")
    status, out = post(ada, "report", kind="bug", text="Three.")
    assert status == 200 and out["refused"] is True and out["reply"] == reports.LATER
    file(bram, "bug", "Bram's own line is his.")
    assert len(rows(game)) == 3


# --- rule 2: delivered as a drop file, in the inbox and in a digest ---------------------


def test_each_report_is_dropped_as_a_file_only_the_operator_reads(
    toy: tuple[Realism, Client, Client], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    game, ada, _ = toy
    folder = tmp_path / "reports"
    monkeypatch.setenv(reports.DIR_ENV, str(folder))
    state = state_of(game)
    number = file(ada, "confusing", ADA_WORDS)
    (path,) = folder.iterdir()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    text = path.read_text()
    office = state.cards[state.seats[seat_of(game, "ada")].embodies].office
    assert state.wake is not None
    for part in (
        f"Report {number}",
        "confusing",
        game.campaign,
        office,
        f"Wake: {state.wake.number}",
        f"Log position: {state.last_seq}",
        state_hash(state),
        ADA_WORDS,
    ):
        assert part in text, (part, text)


def test_without_the_folder_a_report_is_stored_and_listed_only(
    toy: tuple[Realism, Client, Client], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    game, ada, _ = toy
    monkeypatch.delenv(reports.DIR_ENV, raising=False)
    here = tmp_path / "cwd"
    here.mkdir()
    monkeypatch.chdir(here)
    file(ada, "bug", ADA_WORDS)
    assert len(rows(game)) == 1 and list(here.iterdir()) == []


def _today(game: Realism) -> date:
    return game.web.app.clock().date()


def test_one_digest_a_day_counts_by_kind_and_carries_no_words(
    toy: tuple[Realism, Client, Client], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    game, ada, bram = toy
    file(ada, "bug", ADA_WORDS)
    file(bram, "idea", BRAM_WORDS)
    file(bram, "idea", "A second idea.")
    box = tmp_path / "outbox.jsonl"
    monkeypatch.setenv(notice.OUTBOX_ENV, str(box))
    monkeypatch.setenv(notice.DIGEST_TO_ENV, "operator@example.org")
    day = _today(game).isoformat()
    first = runner.invoke(cli.app, ["reports", "digest", "--day", day])
    assert first.exit_code == 0, first.output
    again = runner.invoke(cli.app, ["reports", "digest", "--day", day])
    assert again.exit_code == 0, again.output
    (line,) = [json.loads(x) for x in box.read_text().splitlines()]
    assert line["to"] == "operator@example.org"
    assert "1 bug" in line["text"] and "2 ideas" in line["text"], line["text"]
    for words in (ADA_WORDS, BRAM_WORDS, "A second idea."):
        assert words not in line["text"] and words not in line["subject"]
    assert "already" in again.output


def test_no_digest_goes_without_an_address_or_for_a_day_with_no_reports(
    toy: tuple[Realism, Client, Client], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    game, ada, _ = toy
    box = tmp_path / "outbox.jsonl"
    monkeypatch.setenv(notice.OUTBOX_ENV, str(box))
    file(ada, "bug", ADA_WORDS)
    day = _today(game).isoformat()
    out = runner.invoke(cli.app, ["reports", "digest", "--day", day])
    assert out.exit_code == 0 and notice.DIGEST_TO_ENV in out.output, out.output
    monkeypatch.setenv(notice.DIGEST_TO_ENV, "operator@example.org")
    out = runner.invoke(cli.app, ["reports", "digest", "--day", "2001-01-01"])
    assert out.exit_code == 0 and not box.exists(), out.output


# --- rule 3: your own reports, and the host's inbox --------------------------------------


def test_reports_gives_the_caller_its_own_with_status_and_reply(
    toy: tuple[Realism, Client, Client],
) -> None:
    _, ada, bram = toy
    a1 = file(ada, "bug", ADA_WORDS)
    b1 = file(bram, "idea", BRAM_WORDS)
    mine = listed(ada)
    assert mine["refused"] is False and mine["inbox"] is False
    assert [(r["id"], r["kind"], r["status"], r["reply"]) for r in mine["reports"]] == [
        (a1, "bug", "new", "")
    ]
    assert mine["reports"][0]["words"] == ADA_WORDS
    assert [r["id"] for r in listed(bram)["reports"]] == [b1]


def test_the_host_inbox_lists_every_report_in_his_game_and_others_get_the_empty_shape(
    toy: tuple[Realism, Client, Client],
) -> None:
    _, ada, bram = toy
    a1 = file(ada, "bug", ADA_WORDS)
    b1 = file(bram, "idea", BRAM_WORDS)
    inbox = listed(ada, inbox=True)
    assert inbox["inbox"] is True and inbox["refused"] is False
    assert [(r["id"], r["words"]) for r in inbox["reports"]] == [(a1, ADA_WORDS), (b1, BRAM_WORDS)]
    assert all(r["office"] for r in inbox["reports"]), "the host sees which office filed it"
    empty = listed(bram, inbox=True)
    assert empty == {"reply": "", "refused": False, "inbox": True, "reports": []}


def test_another_seat_gets_nothing_of_a_report_from_any_reply(
    toy: tuple[Realism, Client, Client],
) -> None:
    _, ada, bram = toy
    file(ada, "bug", ADA_WORDS)
    status, asked = post(ada, "help", question=f"bug: {ADA_WORDS} twice")
    assert status == 200 and asked["refused"] is False, asked
    replies: list[Any] = [
        bram.me(),
        listed(bram),
        listed(bram, inbox=True),
        post(bram, "catchup")[1],
        post(bram, "map")[1],
        post(bram, "help", question="What can I do?")[1],
        bram.call("/api/seat/status", {})[1],
        bram.call("/api/seat/report", {})[1],
    ]
    text = json.dumps(replies)
    assert ADA_WORDS not in text
    assert "twice" not in text


# --- rule 4: the host marks a report; the operator's commands ----------------------------


def test_the_host_marks_a_report_and_its_author_sees_the_status_and_reply(
    toy: tuple[Realism, Client, Client],
) -> None:
    game, ada, bram = toy
    b1 = file(bram, "idea", BRAM_WORDS)
    status, out = post(ada, "report-mark", id=b1, status="acted", reply="Ships get names next.")
    assert status == 200 and out["refused"] is False, out
    (mine,) = listed(bram)["reports"]
    assert (mine["status"], mine["reply"]) == ("acted", "Ships get names next.")
    (row,) = rows(game)
    assert row["marked_at"] is not None


def test_report_mark_is_refused_to_anyone_but_the_host_and_for_bad_values(
    toy: tuple[Realism, Client, Client],
) -> None:
    game, ada, bram = toy
    a1 = file(ada, "bug", ADA_WORDS)
    before = rows(game)
    for who, body in (
        (bram, {"id": a1, "status": "seen"}),
        (ada, {"id": a1, "status": "binned"}),
        (ada, {"id": a1, "status": "seen", "reply": "x" * (reports.REPLY_MAX + 1)}),
        (ada, {"id": "one", "status": "seen"}),
    ):
        status, out = post(who, "report-mark", **body)
        assert status == 200 and out["refused"] is True, (body, out)
    assert rows(game) == before


def test_a_report_in_another_game_reads_as_no_such_report(
    toy: tuple[Realism, Client, Client],
    web: Web,  # noqa: F811
) -> None:
    _, ada, _ = toy
    other = Realism(web)
    cara = other.seat("cara", "ada")
    make_host(other, cara)
    begin(other)
    theirs = file(cara, "bug", "Another game's words.")
    _, named = post(ada, "report-mark", id=theirs, status="seen")
    _, unknown = post(ada, "report-mark", id=theirs + 1000, status="seen")
    assert named["refused"] is True and named == unknown


def _cli(*args: str) -> Any:
    out = runner.invoke(cli.app, ["reports", *args])
    assert out.exit_code == 0, out.output
    return out


def test_the_operator_lists_shows_exports_and_marks_reports(
    toy: tuple[Realism, Client, Client], tmp_path: Path
) -> None:
    _, ada, bram = toy
    a1 = file(ada, "bug", ADA_WORDS)
    b1 = file(bram, "idea", BRAM_WORDS)
    lines = _cli("list").output.splitlines()
    assert [line.split()[0] for line in lines] == [str(a1), str(b1)]
    assert "bug" in lines[0] and "new" in lines[0]
    assert ADA_WORDS in _cli("show", str(a1)).output
    _cli("mark", str(b1), "--status", "seen", "--reply", "Read it.")
    seen = _cli("list", "--status", "seen").output.splitlines()
    assert [line.split()[:3] for line in seen] == [[str(b1), "idea", "seen"]]
    out = tmp_path / "export.jsonl"
    _cli("export", "--out", str(out))
    exported = [json.loads(x) for x in out.read_text().splitlines()]
    assert [(r["id"], r["words"], r["status"]) for r in exported] == [
        (a1, ADA_WORDS, "new"),
        (b1, BRAM_WORDS, "seen"),
    ]
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    (mine,) = listed(bram)["reports"]
    assert mine["reply"] == "Read it."
    missing = runner.invoke(cli.app, ["reports", "show", "99999"])
    assert missing.exit_code != 0


# --- rule 5: the aide files a prefixed question as a report, by code --------------------


@pytest.mark.parametrize(
    ("question", "kind", "words"),
    [
        ("idea: Let me name the ships.", "idea", "Let me name the ships."),
        ("Bug: the toll is wrong", "bug", "the toll is wrong"),
        ("report:   The map went blank.", "bug", "The map went blank."),
    ],
)
def test_a_prefixed_question_is_filed_as_a_report_and_no_model_reads_it(
    toy: tuple[Realism, Client, Client],
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    kind: str,
    words: str,
) -> None:
    game, ada, _ = toy
    calls: list[str] = []

    def no_model() -> Any:
        calls.append("transport")
        raise AssertionError("a report reached a model")

    def no_aide(*_a: Any, **_k: Any) -> Any:
        calls.append("aide")
        raise AssertionError("the aide read a report")

    game.web.app.offline_prose = False
    monkeypatch.setattr(game.web.app, "transport_factory", no_model)
    monkeypatch.setattr(aide_help, "answer", no_aide)
    status, out = post(ada, "help", question=question)
    assert status == 200 and out["refused"] is False, out
    (row,) = rows(game)
    assert (row["kind"], row["words"]) == (kind, words)
    said = out["help"][-1]
    assert said["from"] == "aide" and f"report {row['report_id']}" in said["text"].lower()
    assert calls == []


def test_a_question_without_the_prefix_still_goes_to_the_aide(
    toy: tuple[Realism, Client, Client],
) -> None:
    game, ada, _ = toy
    status, out = post(ada, "help", question="What is a bug: in your view?")
    assert status == 200 and out["refused"] is False, out
    assert rows(game) == []


def test_the_digest_day_is_in_utc() -> None:
    assert reports.day_bounds(date(2026, 11, 23)) == (
        datetime(2026, 11, 23, tzinfo=UTC),
        datetime(2026, 11, 24, tzinfo=UTC),
    )
