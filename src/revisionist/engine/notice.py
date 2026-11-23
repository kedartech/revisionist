"""Notices: one message to each human seat when a wake opens (invariant 7).

A notice names the wake, the world date, when the wake closes in real time in the
reader's zone, and every matter that waits on this seat (``agenda_api.due_matters``:
what another seat has put before it, and what the world has put on its desk). It says nothing about
whether anyone else has committed, is present or was played by the aide, so the text
is the same whether the others are at the table or away. A commit sends nothing.

Where it goes: ``$REVISIONIST_NOTICE_SMTP`` (``smtp://`` with STARTTLS or ``smtps://``,
``user:password@host:port``) sends email from ``$REVISIONIST_NOTICE_FROM`` (default: the
login). Otherwise ``$REVISIONIST_NOTICE_OUTBOX`` is a dry run: one JSON line per
message, appended to that file. With neither set nothing is sent and no table is read.

The same senders carry the operator's report digest (``send_digest``): one message a
day to ``$REVISIONIST_REPORTS_DIGEST_TO`` counting the players' reports by kind and game,
never their words; ``player_report_digests`` (migration 0015) holds one row per day sent.

Addresses live on the web account (``web_notice_addresses``); ``web_notices_sent``
holds one row per seat and wake, so a wake that opens again in a resumed run sends
nothing twice. Both tables come from migration 0012; a room that has not run it reads
them as empty.
"""

import json
import logging
import os
import re
import smtplib
import ssl
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.state import State
from revisionist.engine import campaign as cmp
from revisionist.engine.store import EventStore, load_state
from revisionist.engine.web import agenda_api

if TYPE_CHECKING:
    from psycopg import Connection

log = logging.getLogger(__name__)

OUTBOX_ENV = "REVISIONIST_NOTICE_OUTBOX"
SMTP_ENV = "REVISIONIST_NOTICE_SMTP"
FROM_ENV = "REVISIONIST_NOTICE_FROM"
DIGEST_TO_ENV = "REVISIONIST_REPORTS_DIGEST_TO"
DEFAULT_ZONE = "America/New_York"
"""[proposed] The zone a notice's close time is given in when the account set none."""
AIDE_CLAUSE = "If you have not pressed Done by then, your aide plays your seat."
ADDRESS_MAX = 254
_ADDRESS = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def zone_of(name: str | None) -> ZoneInfo:
    """The named IANA zone; the default for none or a name this host does not know."""
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    return ZoneInfo(DEFAULT_ZONE)


def _day(day: date) -> str:
    return f"{day:%A} {day.day} {day:%B %Y}"


def _line(matter: agenda_api.DueMatter) -> str:
    said = f"{matter.issuer}: {matter.what}" if matter.issuer else matter.what
    return f"- {said}. Due {matter.due}."


def _waiting(state: State, seat: SeatId) -> list[str]:
    """Each matter that waits on ``seat`` (``agenda_api.due_matters``), one line each:
    the same words its agenda or paper gives, withheld where those withhold them."""
    return [_line(m) for m in agenda_api.due_matters(state, seat)]


def compose(state: State, seat: SeatId, zone: str | None, game: str) -> tuple[str, str]:
    """The subject and text of ``seat``'s notice for the open wake.

    Reads the wake's number and deadline, the world date and what waits on the seat:
    nothing about any other seat's commit, presence or aide play."""
    wake = state.wake
    if wake is None:
        raise ValueError("no wake has opened")
    tz = zone_of(zone)
    close = wake.deadline.astimezone(tz)
    lines = [f"Wake {wake.number} of {game} is open."]
    today = state.in_world_date
    if today is not None:
        lines.append(f"In the world it is {_day(today)}.")
    lines.append(f"It closes by {close:%H:%M} on {_day(close.date())}, {tz.key} time.")
    lines.append("")
    waiting = _waiting(state, seat)
    if waiting:
        lines.append("Before you:")
        lines.extend(waiting)
    else:
        lines.append("Nothing from another player waits on you.")
    lines.append("")
    lines.append(AIDE_CLAUSE)
    return f"{game}: wake {wake.number} is open", "\n".join(lines)


# --- transports ---------------------------------------------------------------------


@dataclass(frozen=True)
class Notice:
    campaign_id: CampaignId
    seat_id: SeatId
    wake: int
    to: str
    subject: str
    text: str


class Sender(Protocol):
    def send(self, notice: Notice) -> None: ...


class Outbox:
    """The dry run: one JSON line per message, appended to ``path``."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def send(self, notice: Notice) -> None:
        line = {**asdict(notice), "campaign": notice.campaign_id, "seat": notice.seat_id}
        del line["campaign_id"], line["seat_id"]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


Connect = Callable[[str, int, bool], Any]
"""``(host, port, tls)`` to an open SMTP client: ``tls`` means TLS from the start."""


def _connect(host: str, port: int, tls: bool) -> smtplib.SMTP:
    if tls:
        return smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
    return smtplib.SMTP(host, port, timeout=30)


class Smtp:
    """Email over ``smtps://`` (TLS from the start) or ``smtp://`` (STARTTLS)."""

    def __init__(self, url: str, sender: str | None, *, connect: Connect = _connect) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("smtp", "smtps") or not parts.hostname:
            raise ValueError(f"{SMTP_ENV} must be smtp://… or smtps://…")
        self.tls = parts.scheme == "smtps"
        self.host = parts.hostname
        self.port = parts.port or (465 if self.tls else 587)
        self.user = unquote(parts.username) if parts.username else None
        self.password = unquote(parts.password) if parts.password else ""
        found = sender or self.user
        if not found:
            raise ValueError(f"set {FROM_ENV}, or log in with an address")
        self.sender = found
        self.connect = connect

    def send(self, notice: Notice) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = notice.to
        msg["Subject"] = notice.subject
        msg.set_content(notice.text)
        with self.connect(self.host, self.port, self.tls) as client:
            if not self.tls:
                client.starttls(context=ssl.create_default_context())
            if self.user:
                client.login(self.user, self.password)
            client.send_message(msg)


def sender_from_env() -> Sender | None:
    """SMTP when ``$REVISIONIST_NOTICE_SMTP`` is set, else the outbox file when
    ``$REVISIONIST_NOTICE_OUTBOX`` is, else None: nothing is sent."""
    url = os.environ.get(SMTP_ENV)
    if url:
        try:
            return Smtp(url, os.environ.get(FROM_ENV) or None)
        except ValueError as exc:
            log.warning("notices are off: %s", exc)
            return None
    box = os.environ.get(OUTBOX_ENV)
    return Outbox(Path(box)) if box else None


# --- the tables ---------------------------------------------------------------------

_missing: set[str] = set()


def forget_missing() -> None:
    """Log a missing table again (tests)."""
    _missing.clear()


def _is_missing(exc: Exception, table: str) -> bool:
    from psycopg import errors

    if not isinstance(exc, errors.UndefinedTable):
        return False
    if table not in _missing:
        _missing.add(table)
        log.warning("%s is missing (run db migrate): read as empty", table)
    return True


@dataclass(frozen=True)
class Address:
    address: str
    """Empty: no notices."""
    zone: str


def read_address(conn: "Connection[Any]", account_id: str) -> Address | None:
    """The account's address and zone; None when the table is missing."""
    table = "web_notice_addresses"
    try:
        row = conn.execute(
            "SELECT address, zone FROM web_notice_addresses WHERE account_id = %s", (account_id,)
        ).fetchone()
    except Exception as exc:
        if _is_missing(exc, table):
            return None
        raise
    if row is None:
        return Address("", DEFAULT_ZONE)
    return Address(row[0] or "", row[1] or DEFAULT_ZONE)


def _addresses(conn: "Connection[Any]", campaign_id: CampaignId) -> dict[SeatId, Address]:
    """Each web-held seat of the campaign that has an address."""
    table = "web_notice_addresses"
    try:
        rows = conn.execute(
            "SELECT s.seat_id, n.address, n.zone FROM web_seats s"
            " JOIN web_notice_addresses n ON n.account_id = s.account_id"
            " WHERE s.campaign_id = %s AND s.finished_at IS NULL"
            " AND n.address IS NOT NULL AND n.address <> ''",
            (campaign_id,),
        ).fetchall()
    except Exception as exc:
        if _is_missing(exc, table):
            return {}
        raise
    return {SeatId(r[0]): Address(r[1], r[2] or DEFAULT_ZONE) for r in rows}


def _claim(conn: "Connection[Any]", campaign_id: CampaignId, seat: SeatId, wake: int) -> bool:
    """Mark the seat's notice for ``wake`` as sent; False if it already was."""
    table = "web_notices_sent"
    try:
        row = conn.execute(
            "INSERT INTO web_notices_sent (campaign_id, seat_id, wake) VALUES (%s, %s, %s)"
            " ON CONFLICT DO NOTHING RETURNING 1",
            (campaign_id, seat, wake),
        ).fetchone()
    except Exception as exc:
        if _is_missing(exc, table):
            return True
        raise
    return row is not None


def _release(conn: "Connection[Any]", campaign_id: CampaignId, seat: SeatId, wake: int) -> None:
    """Unmark a notice that did not go, so the next try sends it."""
    table = "web_notices_sent"
    try:
        conn.execute(
            "DELETE FROM web_notices_sent WHERE campaign_id = %s AND seat_id = %s AND wake = %s",
            (campaign_id, seat, wake),
        )
    except Exception as exc:
        if not _is_missing(exc, table):
            raise


def _game_name(store: EventStore, campaign_id: CampaignId) -> str:
    for e in store.read(campaign_id):
        if isinstance(e.payload, ev.CampaignCreated):
            return e.payload.name
    return "Revisionist"


class Notifier(Protocol):
    def wake_opened(self, store: EventStore, campaign_id: CampaignId, wake: int) -> int:
        """Send each seat's notice for ``wake``, which has just opened; returns how many."""
        ...


class WebNotifier:
    """Notices to the web accounts that hold the campaign's human seats."""

    def __init__(self, conn: "Connection[Any]", sender: Sender) -> None:
        self.conn = conn
        self.sender = sender

    def wake_opened(self, store: EventStore, campaign_id: CampaignId, wake: int) -> int:
        state = load_state(store, campaign_id)
        if state.wake is None or state.wake.number != wake or state.wake.closed:
            return 0
        addresses = _addresses(self.conn, campaign_id)
        game = _game_name(store, campaign_id) if addresses else ""
        sent = 0
        for seat in cmp.human_seats(state):
            to = addresses.get(seat)
            if to is None:
                continue
            subject, text = compose(state, seat, to.zone, game)
            if not _claim(self.conn, campaign_id, seat, wake):
                continue
            try:
                self.sender.send(Notice(campaign_id, seat, wake, to.address, subject, text))
            except Exception:
                log.exception("the notice for wake %s of %s did not go", wake, campaign_id)
                _release(self.conn, campaign_id, seat, wake)
                continue
            sent += 1
        return sent


def for_store(store: EventStore) -> Notifier | None:
    """The notifier for a Postgres store when a transport is set; None otherwise: the
    web tables live only in Postgres."""
    sender = sender_from_env()
    if sender is None:
        return None
    try:
        from revisionist.engine.pg_store import PostgresEventStore
    except ImportError:  # the postgres extra is not installed
        return None
    if not isinstance(store, PostgresEventStore):
        return None
    return WebNotifier(store.conn, sender)


# --- the report digest --------------------------------------------------------------

_KIND_WORDS: dict[str, tuple[str, str]] = {
    "bug": ("bug", "bugs"),
    "idea": ("idea", "ideas"),
    "confusing": ("marked confusing", "marked confusing"),
}
"""The kinds of player report, in the digest's order, and how a count of each reads."""


def _counted(counts: Mapping[str, int]) -> str:
    said = []
    for kind, (one, many) in _KIND_WORDS.items():
        n = counts.get(kind, 0)
        if n:
            said.append(f"{n} {one if n == 1 else many}")
    return ", ".join(said)


def compose_digest(day: date, counts: Mapping[str, Mapping[str, int]]) -> tuple[str, str]:
    """The subject and text of ``day``'s report digest, from a count per game and kind.
    It is built from numbers and game names only, so no report's words can reach it."""
    total: dict[str, int] = {}
    for by_kind in counts.values():
        for kind, n in by_kind.items():
            total[kind] = total.get(kind, 0) + int(n)
    whole = sum(total.values())
    on = _day(day)
    lines = [f"Reports filed on {on} (UTC): {_counted(total)}.", "", "By game:"]
    lines += [f"- {game}: {_counted(counts[game])}." for game in sorted(counts)]
    lines += ["", "Read them with: revisionist reports list"]
    noun = "report" if whole == 1 else "reports"
    return f"Revisionist: {whole} {noun} on {on}", "\n".join(lines)


def send_digest(
    conn: "Connection[Any]",
    sender: Sender,
    to: str,
    day: date,
    counts: Mapping[str, Mapping[str, int]],
) -> bool:
    """Send ``day``'s digest once (``player_report_digests``); True if it went now. A day
    with no reports sends nothing, and a send that fails is not marked, so a later try
    sends it."""
    if not any(n for by_kind in counts.values() for n in by_kind.values()):
        return False
    subject, text = compose_digest(day, counts)
    claimed = conn.execute(
        "INSERT INTO player_report_digests (day) VALUES (%s) ON CONFLICT DO NOTHING RETURNING 1",
        (day,),
    ).fetchone()
    if claimed is None:
        return False
    try:
        sender.send(Notice(CampaignId(""), SeatId(""), 0, to, subject, text))
    except Exception:
        log.exception("the report digest for %s did not go", day)
        conn.execute("DELETE FROM player_report_digests WHERE day = %s", (day,))
        return False
    return True


# --- the game action ----------------------------------------------------------------

_NOT_SET_UP = "Notices are not set up on this server yet."


def _described(found: Address) -> str:
    if not found.address:
        return f"No notices are sent to you. Times would be given in {found.zone}."
    return f"Notices go to {found.address}, with times in {found.zone}."


def _refused(reply: str, found: Address) -> dict[str, Any]:
    return {"reply": reply, "refused": True, "address": found.address, "zone": found.zone}


def address_action(
    conn: "Connection[Any]", account_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """``notice-address``: ``{address?, zone?}`` sets either (an empty address clears
    it); no keys reads them. Replies ``{reply, refused, address, zone}``."""
    found = read_address(conn, account_id)
    if found is None:
        return _refused(_NOT_SET_UP, Address("", DEFAULT_ZONE))
    address, zone = body.get("address"), body.get("zone")
    if address is None and zone is None:
        return {"reply": _described(found), "refused": False, **asdict(found)}
    if address is not None:
        if not isinstance(address, str) or len(address) > ADDRESS_MAX:
            return _refused("Give the address as text.", found)
        address = address.strip()
        if address and not _ADDRESS.fullmatch(address):
            return _refused("That does not look like an email address.", found)
    if zone is not None:
        if not isinstance(zone, str) or not zone or zone_of(zone).key != zone:
            return _refused("Give a time zone by name, such as America/New_York.", found)
    now = Address(found.address if address is None else address, zone or found.zone)
    conn.execute(
        "INSERT INTO web_notice_addresses (account_id, address, zone) VALUES (%s, %s, %s)"
        " ON CONFLICT (account_id) DO UPDATE"
        " SET address = EXCLUDED.address, zone = EXCLUDED.zone, updated_at = now()",
        (account_id, now.address or None, now.zone),
    )
    return {"reply": _described(now), "refused": False, **asdict(now)}


__all__ = [
    "AIDE_CLAUSE",
    "DEFAULT_ZONE",
    "DIGEST_TO_ENV",
    "FROM_ENV",
    "OUTBOX_ENV",
    "SMTP_ENV",
    "Address",
    "Notice",
    "Notifier",
    "Outbox",
    "Sender",
    "Smtp",
    "WebNotifier",
    "address_action",
    "compose",
    "compose_digest",
    "for_store",
    "forget_missing",
    "read_address",
    "send_digest",
    "sender_from_env",
    "zone_of",
]
