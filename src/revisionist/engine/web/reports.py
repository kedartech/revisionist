"""Player reports: a bug, an idea or something confusing, filed from the room.

A report is filed by the realism action ``report``, by the seat action ``bug``, or by a
question to the aide that opens with ``report:``, ``idea:`` or ``bug:`` (``from_question``:
code files it, and no model reads it). Each is pinned to its moment, the log position
and the state's hash, and stored in ``player_reports`` (migration 0015) with its words
sealed to the seat in a sealed game. Reports sit outside the game's log: no event, no
catch-up line.

Delivered three ways: a file per report in the folder ``$REVISIONIST_REPORTS_DIR`` names
(mode 600, the words in plain; without the folder nothing is written), the host's inbox
(``reports`` with ``inbox: true``), and a count by kind in one digest a day
(``send_digest``, through the notice sender, with no report's words). A report is read
by its author, the host of its game and the operator, never by another seat.
"""

import base64
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from revisionist.core.fold import state_hash
from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.state import State
from revisionist.engine import notice
from revisionist.engine import scheduler as sch
from revisionist.engine.pg_store import PostgresEventStore

log = logging.getLogger(__name__)

KINDS = ("bug", "idea", "confusing")
STATUSES = ("new", "seen", "acted")
"""A report's status: new, seen, or acted on."""
WORDS_MAX = 4000
REPLY_MAX = 200
PER_HOUR = 20
"""Reports one account may file in an hour [proposed]."""
DIR_ENV = "REVISIONIST_REPORTS_DIR"
PREFIXES: Mapping[str, str] = {"report": "bug", "idea": "idea", "bug": "bug"}
"""A question to the aide that opens with one of these and a colon is a report of this
kind [proposed: a plain ``report:`` is a bug]."""
_PREFIXED = re.compile(r"\s*(report|idea|bug)\s*:(.*)", re.IGNORECASE | re.DOTALL)

FILED = "Report {n} filed. Only the host and the makers read it."
LATER = "That is as many reports as an hour allows. Try again in an hour."
NO_KIND = "A report is a bug, an idea or something confusing."
NO_WORDS = "Write what you want to report."
TOO_LONG = f"A report is at most {WORDS_MAX:,} characters."
HOST_ONLY = "Only the host can do that."
NO_SUCH = "No such report."
NO_STATUS = "A report is new, seen or acted on."
REPLY_LONG = f"A reply is at most {REPLY_MAX} characters."
NOT_SET_UP = "Reports are not set up on this server yet."
ERASED = "(The words of this report were erased.)"
SEALED = "(Sealed: set REVISIONIST_MASTER_KEY_FILE to read these words.)"
_A = {"bug": "a bug", "idea": "an idea", "confusing": "something confusing"}


class RefusedError(Exception):
    """A report not filed or not marked: its message is the reply."""


@dataclass(frozen=True)
class Report:
    report_id: int
    campaign_id: CampaignId
    seat_id: SeatId
    account_id: str
    kind: str
    wake: int | None
    seq: int
    state_hash: str
    words: str
    """In plain, opened with the seat's key."""
    status: str
    reply: str
    filed_at: datetime

    def shown(self) -> dict[str, Any]:
        """What its author sees."""
        return {
            "id": self.report_id,
            "kind": self.kind,
            "status": self.status,
            "reply": self.reply,
            "words": self.words,
            "wake": self.wake,
            "filed": self.filed_at.astimezone(UTC).isoformat(),
        }


_COLUMNS = (
    "report_id, campaign_id, seat_id, account_id, kind, wake, seq, state_hash, words,"
    " status, reply, filed_at"
)


def _missing(exc: Exception) -> bool:
    from psycopg import errors

    return isinstance(exc, errors.UndefinedTable)


def _opened(store: PostgresEventStore, campaign_id: str, words: str) -> str:
    """A report's words in plain: as stored, or opened with the seat's key."""
    if not words.startswith("sealed:"):
        return words
    keyring = getattr(store.sealer, "keyring", None)
    if keyring is None:
        return SEALED
    _, key_id, body = words.split(":", 2)
    key = keyring.key(key_id)
    if key is None:
        return ERASED
    from revisionist.engine.seal import decrypt

    aad = f"{campaign_id}|text|{key_id}".encode()
    return decrypt(key, base64.b64decode(body), aad).decode()


def _report(store: PostgresEventStore, row: Any) -> Report:
    return Report(
        report_id=int(row[0]),
        campaign_id=CampaignId(row[1]),
        seat_id=SeatId(row[2]),
        account_id=str(row[3]),
        kind=str(row[4]),
        wake=row[5],
        seq=int(row[6]),
        state_hash=str(row[7]),
        words=_opened(store, row[1], str(row[8])),
        status=str(row[9]),
        reply=str(row[10]),
        filed_at=row[11],
    )


def office(state: State, seat: SeatId) -> str:
    """The office of the person the seat plays, else the seat's name."""
    held = state.seats[seat]
    card = state.cards.get(held.embodies)
    return card.office if card is not None and card.office else held.name


# --- filing -------------------------------------------------------------------------


def file(
    store: PostgresEventStore,
    state: State,
    seat: SeatId,
    account_id: str,
    kind: str,
    words: str,
    now: datetime,
) -> int:
    """Store one report, pinned to ``state``, and drop its file; its number.
    ``RefusedError`` for a bad kind, empty or long words, or past the hourly line."""
    if kind not in KINDS:
        raise RefusedError(NO_KIND)
    words = words.strip()
    if not words:
        raise RefusedError(NO_WORDS)
    if len(words) > WORDS_MAX:
        raise RefusedError(TOO_LONG)
    conn = store.conn
    row = conn.execute(
        "SELECT count(*) FROM player_reports WHERE account_id = %s AND filed_at > %s",
        (account_id, now - timedelta(hours=1)),
    ).fetchone()
    if row is not None and row[0] >= PER_HOUR:
        raise RefusedError(LATER)
    stored = words
    if store.sealer is not None:  # the seat's own words, like its orders
        stored = store.sealer.seal_text(state.campaign_id, seat, words)
    wake = state.wake.number if state.wake is not None else None
    pinned = state_hash(state)
    made = conn.execute(
        "INSERT INTO player_reports (campaign_id, seat_id, account_id, kind, wake, seq,"
        " state_hash, words, filed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " RETURNING report_id",
        (state.campaign_id, seat, account_id, kind, wake, state.last_seq, pinned, stored, now),
    ).fetchone()
    assert made is not None
    number = int(made[0])
    folder = os.environ.get(DIR_ENV)
    if folder:
        game = sch.campaign_name(store, state.campaign_id)
        text = drop_text(number, kind, game, state, seat, pinned, words, now)
        try:
            drop(Path(folder), number, text)
        except OSError:
            log.exception("report %s is stored, but its file could not be written", number)
    return number


def drop_text(
    number: int,
    kind: str,
    game: str,
    state: State,
    seat: SeatId,
    pinned: str,
    words: str,
    now: datetime,
) -> str:
    """The drop file of one report: what it is, where it was filed, then its words."""
    wake = state.wake.number if state.wake is not None else "none"
    return "\n".join(
        [
            f"# Report {number}: {kind}",
            "",
            f"- Game: {game} ({state.campaign_id})",
            f"- Office: {office(state, seat)}",
            f"- Wake: {wake}",
            f"- Log position: {state.last_seq}",
            f"- State hash: {pinned}",
            f"- Filed: {now.astimezone(UTC).isoformat()}",
            "",
            words,
            "",
        ]
    )


def drop(folder: Path, number: int, text: str) -> Path:
    """Write ``text`` as ``report-<number>.md`` in ``folder``: the folder 700, the file
    600, made that way rather than narrowed after."""
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / f"report-{number}.md"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def from_question(
    store: PostgresEventStore,
    state: State,
    seat: SeatId,
    account_id: str,
    question: str,
    now: datetime,
) -> str | None:
    """The aide's reply when ``question`` opens with a report's prefix, having filed it;
    None for any other question. Code reads the prefix; no model sees the words."""
    found = _PREFIXED.fullmatch(question)
    if found is None:
        return None
    kind = PREFIXES[found.group(1).lower()]
    try:
        number = file(store, state, seat, account_id, kind, found.group(2), now)
    except RefusedError as exc:
        return str(exc)
    except Exception as exc:
        if _missing(exc):
            return NOT_SET_UP
        raise
    return (
        f"I have filed that as report {number}, {_A[kind]}. "
        "Only the host and the makers read it; I do not."
    )


def seat_bug(
    store: PostgresEventStore,
    state: State,
    seat: SeatId,
    account_id: str,
    notes: str,
    now: datetime,
) -> str:
    """The seat action ``bug``: a bug report, filed as ``report`` files one."""
    try:
        number = file(store, state, seat, account_id, "bug", notes, now)
    except RefusedError as exc:
        return str(exc)
    return f"Bug {number} filed at tick {state.tick}. Thank you."


# --- the realism actions ------------------------------------------------------------


def own(store: PostgresEventStore, campaign_id: CampaignId, account_id: str) -> list[Report]:
    """The reports ``account_id`` filed in the game, oldest first."""
    rows = store.conn.execute(
        f"SELECT {_COLUMNS} FROM player_reports WHERE campaign_id = %s AND account_id = %s"
        " ORDER BY report_id",
        (campaign_id, account_id),
    ).fetchall()
    return [_report(store, r) for r in rows]


def listing(
    store: PostgresEventStore,
    campaign_id: CampaignId | None = None,
    status: str | None = None,
) -> list[Report]:
    """Every report, or a game's, or those with one status, oldest first."""
    where: list[str] = []
    args: list[str] = []
    if campaign_id is not None:
        where.append("campaign_id = %s")
        args.append(campaign_id)
    if status is not None:
        where.append("status = %s")
        args.append(status)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    rows = store.conn.execute(
        f"SELECT {_COLUMNS} FROM player_reports{clause} ORDER BY report_id", args
    ).fetchall()
    return [_report(store, r) for r in rows]


def get(store: PostgresEventStore, number: int) -> Report | None:
    row = store.conn.execute(
        f"SELECT {_COLUMNS} FROM player_reports WHERE report_id = %s", (number,)
    ).fetchone()
    return None if row is None else _report(store, row)


def mark(
    store: PostgresEventStore,
    number: int,
    status: str,
    reply: str | None,
    now: datetime,
    campaign_id: CampaignId | None = None,
) -> None:
    """Set a report's status, and its reply when one is given; ``RefusedError`` for a
    bad value or a report that is not there (or not in ``campaign_id``)."""
    if status not in STATUSES:
        raise RefusedError(NO_STATUS)
    if reply is not None and len(reply.strip()) > REPLY_MAX:
        raise RefusedError(REPLY_LONG)
    done = store.conn.execute(
        "UPDATE player_reports SET status = %s, reply = COALESCE(%s, reply), marked_at = %s"
        " WHERE report_id = %s AND (%s::text IS NULL OR campaign_id = %s)",
        (status, None if reply is None else reply.strip(), now, number, campaign_id, campaign_id),
    )
    if done.rowcount != 1:
        raise RefusedError(NO_SUCH)


def _refused(text: str) -> dict[str, Any]:
    return {"reply": text, "refused": True}


def _number(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RefusedError(NO_SUCH)
    return value


def action(
    store: PostgresEventStore,
    state: State,
    seat: SeatId,
    account_id: str,
    host: bool,
    name: str,
    body: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """``report``, ``reports`` or ``report-mark`` for a seat in play. A refusal is a reply."""
    try:
        if name == "report":
            kind, words = body.get("kind"), body.get("text")
            if not isinstance(kind, str):
                raise RefusedError(NO_KIND)
            if not isinstance(words, str):
                raise RefusedError(NO_WORDS)
            number = file(store, state, seat, account_id, kind, words, now)
            return {"reply": FILED.format(n=number), "refused": False, "report": number}
        if name == "reports":
            inbox = body.get("inbox") is True
            if not inbox:
                found = [r.shown() for r in own(store, state.campaign_id, account_id)]
            elif host:
                found = [
                    r.shown() | {"office": office(state, r.seat_id)}
                    if r.seat_id in state.seats
                    else r.shown() | {"office": ""}
                    for r in listing(store, state.campaign_id)
                ]
            else:
                found = []
            return {"reply": "", "refused": False, "inbox": inbox, "reports": found}
        if not host:
            return _refused(HOST_ONLY)
        number = _number(body.get("id"))
        reply = body.get("reply")
        if reply is not None and not isinstance(reply, str):
            raise RefusedError(REPLY_LONG)
        status = body.get("status")
        mark(
            store, number, status if isinstance(status, str) else "", reply, now, state.campaign_id
        )
        return {"reply": "Marked.", "refused": False, "id": number}
    except RefusedError as exc:
        return _refused(str(exc))
    except Exception as exc:
        if _missing(exc):
            return _refused(NOT_SET_UP)
        raise


# --- for the operator ---------------------------------------------------------------


def record(report: Report, game: str) -> dict[str, Any]:
    """One report as the operator's export writes it."""
    return report.shown() | {
        "game": game,
        "campaign": report.campaign_id,
        "seat": report.seat_id,
        "seq": report.seq,
        "state_hash": report.state_hash,
    }


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """A digest's day, midnight to midnight in UTC."""
    start = datetime.combine(day, time(0), tzinfo=UTC)
    return start, start + timedelta(days=1)


def day_counts(store: PostgresEventStore, day: date) -> dict[str, dict[str, int]]:
    """Reports filed on ``day``, by game name and kind: counts only, no words."""
    start, end = day_bounds(day)
    rows = store.conn.execute(
        "SELECT campaign_id, kind, count(*) FROM player_reports"
        " WHERE filed_at >= %s AND filed_at < %s GROUP BY campaign_id, kind",
        (start, end),
    ).fetchall()
    out: dict[str, dict[str, int]] = {}
    for cid, kind, n in rows:
        game = sch.campaign_name(store, CampaignId(cid))
        out.setdefault(game, {})
        out[game][kind] = out[game].get(kind, 0) + int(n)
    return out


def send_digest(store: PostgresEventStore, day: date, sender: notice.Sender, to: str) -> bool:
    """``day``'s digest to ``to``: True if it went now, False if it had gone already,
    did not go, or the day had no reports."""
    return notice.send_digest(store.conn, sender, to, day, day_counts(store, day))


__all__ = [
    "DIR_ENV",
    "KINDS",
    "PER_HOUR",
    "REPLY_MAX",
    "STATUSES",
    "WORDS_MAX",
    "RefusedError",
    "Report",
    "action",
    "day_bounds",
    "day_counts",
    "drop",
    "file",
    "from_question",
    "get",
    "listing",
    "mark",
    "office",
    "own",
    "record",
    "seat_bug",
    "send_digest",
]
