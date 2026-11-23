"""Every action refuses the wrong caller (AZT).

The table lists every action the server answers, read from the server's own registries
(``SEAT_ACTIONS``, ``GAME_OPEN`` and ``GAME_ACTIONS``, ``NEW_GAME_ACTIONS``,
``REALISM_ACTIONS``), so an action added to a registry and not to the table fails here.
Each action is sent over HTTP by the callers that must not have it: no session; an account
with no seat; a seat in another game; a seat in this game that is not the host, for a
host-only action; and a seat naming another seat's order, paper, held order, ask or agenda
item. Each gets a refusal, and no game's events or tables change (a seat in another game
sending an action that names nothing may change its own game only). A refusal that names a
thing another seat holds reads the same as one naming a thing that does not exist.

The games, in one database, built once and copied for each action: A and B are the toy
world in play (A: Ilse Varg the host, Kara Lind and Tomas Brand; B: Ilse the host and
Kara), C is the toy world choosing its people (its host plays Ilse, a guest has joined), E
has ended. A failure in a guard-lane file is fixed with this item; one in another lane's
file is a strict expected-to-fail case naming the fix in that lane (``FINDINGS``).
"""

import ast
import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer
from itertools import count
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, DocumentId, EntityId, OrderId, SeatId, derived_id
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import BodyField, DocumentKind, DocumentTruth, DocumentView
from revisionist.core.visibility import private_to
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine import scheduler as sch
from revisionist.engine.discord.tables import Invites
from revisionist.engine.store import load_state
from revisionist.engine.web import held, server, wake_api
from revisionist.engine.web.accounts import Accounts, WebSeats
from revisionist.engine.web.server import App, make_handler
from tests import fog_twins as ft
from tests.pg import Cluster, PgDb, url
from tests.test_discord_bot import Game
from tests.test_session_zero_steps import Table
from tests.test_web import PASSWORD, Client

A = CampaignId(derived_id("azt", "game", "a"))
B = CampaignId(derived_id("azt", "game", "b"))
C = CampaignId(derived_id("azt", "game", "c"))
E = CampaignId(derived_id("azt", "game", "e"))

CACHES = frozenset({"snapshots"})
"""Tables with a ``campaign_id`` that hold only what the events already say."""


# --- the table ----------------------------------------------------------------------

OPEN = "any signed-in account"
UNSEATED = "an account with no seat in a live game"
ENDED = "an account that held a seat in the ended game it names"
PLAY = "a seat in a game in play"
PLAY_HOST = "the host of a game in play"
ZERO = "a seat in a game choosing its people"
ZERO_HOST = "the host of a game choosing its people"
KINDS = (OPEN, UNSEATED, ENDED, PLAY, PLAY_HOST, ZERO, ZERO_HOST)


@dataclass
class Ids:
    """What the callers name: things A's seats hold, and the other games' handles."""

    order: str = ""
    """Kara's order in A that has landed."""
    held: str = ""
    """Kara's order in A held by a lock for Ilse, which Kara has asked for."""
    waiting: int = 0
    """Kara's order in A waiting for the next wake (``web_held_orders``)."""
    paper: str = ""
    """A paper only Kara holds in A."""
    item: str = ""
    """An item on Kara's agenda in A: the decision at her step of Ilse's order."""
    zero_host_person: str = "Ilse Varg"
    """The person C's host plays."""
    ended: str = E
    """The game that has ended, in which no caller held a seat."""
    spare_code: str = ""
    """An unspent invite code for C."""


def made_up(ids: Ids) -> Ids:
    """``ids`` with every named thing replaced by one that does not exist."""
    fake = derived_id("azt", "nothing", "here")
    return Ids(
        order=fake,
        held=fake,
        waiting=987654,
        paper=fake,
        item=fake,
        zero_host_person="Nobody Of Note",
        ended=derived_id("azt", "game", "none"),
        spare_code=ids.spare_code,
    )


Body = Callable[[Ids], dict[str, Any]]
Names = Callable[[Ids], list[dict[str, Any]]]


def _none(ids: Ids) -> dict[str, Any]:
    return {}


def _fixed(**body: Any) -> Body:
    return lambda ids: dict(body)


@dataclass(frozen=True)
class Row:
    """One action: who may send it, a body a rightful caller could send, and, for an
    action that names a thing a seat holds, the bodies that name another seat's."""

    family: str
    action: str
    kind: str
    body: Body = _none
    names: Names | None = None

    @property
    def id(self) -> str:
        return f"{self.family}/{self.action}"


MARCH = {"lever": "march", "params": {"force": "norra_levy", "to": "norra_hills"}}
ISLE = {"lever": "march", "params": {"force": "norra_levy", "to": "isle"}}
WATCH = {"lever": "set_watch", "params": {"zone": "open", "order": "guard"}}
WRITE = {"to": "Ilse Varg", "channel": "courier"}

ROWS: tuple[Row, ...] = (
    # /api/seat/<action>: the Discord commands a web seat runs
    Row("seat", "join", UNSEATED, lambda ids: {"code": ids.spare_code}),
    Row("seat", "roster", PLAY),
    Row("seat", "search", PLAY, _fixed(text="a general")),
    Row("seat", "claim", PLAY, _fixed(name="Kara Lind")),
    Row("seat", "pick", PLAY, _fixed(name="Kara Lind")),
    Row("seat", "goal", PLAY, _fixed(route="history")),
    Row("seat", "confirm", PLAY, _fixed(label="1")),
    Row("seat", "history", PLAY),
    Row("seat", "agent", PLAY, _fixed(name="Aide", role="secretary")),
    Row("seat", "order", PLAY, _fixed(text="Hold the hills.")),
    Row("seat", "ask", PLAY, _fixed(question="What now?")),
    Row("seat", "dossier", PLAY),
    Row("seat", "dispatch", PLAY),
    Row("seat", "status", PLAY),
    Row("seat", "report", PLAY),
    Row("seat", "bug", PLAY, _fixed(notes="The map is blank.")),
    # /api/game/<action>
    Row("game", "reveal", ENDED, lambda ids: {"game": E}, lambda ids: [{"game": ids.ended}]),
    Row("game", "notice-address", OPEN),
    Row("game", "pause", PLAY_HOST),
    Row("game", "resume", PLAY_HOST),
    Row("game", "end", PLAY_HOST),
    Row("game", "leave", PLAY),
    Row("game", "wake-hours", PLAY_HOST, _fixed(hours=12)),
    Row("game", "handover-list", PLAY_HOST),
    Row("game", "handover", PLAY_HOST, _fixed(leader="olaf")),
    # /api/new/<action>
    Row("new", "worlds", OPEN),
    Row("new", "timeline", OPEN),
    Row("new", "figures", OPEN, _fixed(date="1900-04-02")),
    Row("new", "ready", UNSEATED, _fixed(world="autumn-1941")),
    Row("new", "pitch", UNSEATED, _fixed(text="The strait in 1900, at the brink.")),
    Row("new", "cast", UNSEATED, _fixed(choice=1)),
    Row("new", "start", UNSEATED, _fixed(date="1941-06-01")),
    Row("new", "pick", ZERO, _fixed(name="Kara Lind")),
    Row("new", "unpick", ZERO, _fixed(name=""), lambda ids: [{"name": ids.zero_host_person}]),
    Row("new", "style", ZERO, _fixed(style="guided")),
    Row("new", "invite", ZERO_HOST),
    Row("new", "begin", ZERO_HOST),
    # /api/realism/<action>
    Row("realism", "catchup", PLAY),
    Row("realism", "map", PLAY),
    Row("realism", "check", PLAY, _fixed(**MARCH)),
    Row("realism", "odds", PLAY, _fixed(force="norra_levy", to="isle")),
    Row(
        "realism",
        "read",
        PLAY,
        lambda ids: {"doc_id": ids.paper},
        lambda ids: [{"doc_id": ids.paper}],
    ),
    Row(
        "realism",
        "flag",
        PLAY,
        lambda ids: {"doc_id": ids.paper, "flagged": True},
        lambda ids: [{"doc_id": ids.paper, "flagged": True}],
    ),
    Row("realism", "lever", PLAY, _fixed(**MARCH)),
    Row("realism", "directive", PLAY, _fixed(**WRITE, text="Hold the hills.")),
    Row("realism", "sign", PLAY, _fixed(**WRITE, **MARCH)),
    Row("realism", "aide", PLAY),
    Row("realism", "consult", PLAY, _fixed(to="Ilse Varg", question="Will you hold?")),
    Row("realism", "help", PLAY, _fixed(question="What can I do?")),
    Row(
        "realism",
        "step",
        PLAY,
        lambda ids: {"order_id": ids.order, "action": "pass"},
        lambda ids: [
            {"order_id": ids.order, "action": "pass"},
            {"order_id": ids.held, "action": "pass"},
            {"order_id": ids.item, "action": "pass"},
        ],
    ),
    Row("realism", "advance", PLAY_HOST),
    Row("realism", "commit", PLAY),
    Row("realism", "close", PLAY_HOST),
    Row("realism", "style", PLAY, _fixed(style="guided")),
    Row("realism", "option", PLAY, _fixed(pick="w0.o0.p0")),
    Row(
        "realism",
        "answer",
        PLAY,
        lambda ids: {"item": ids.item, "accept": True},
        lambda ids: [{"item": ids.item, "accept": True}],
    ),
    Row("realism", "order", PLAY, _fixed(to="Kara Lind", channel="courier", text="March.")),
    Row("realism", "agreement-offer", PLAY, _fixed(wording="Peace.", parties=["sudland"])),
    Row("realism", "file", PLAY),
    Row(
        "realism",
        "withdraw",
        PLAY,
        lambda ids: {"order_id": ids.order},
        lambda ids: [{"order_id": ids.order}, {"held_id": ids.waiting}],
    ),
    Row(
        "realism",
        "ask",
        PLAY,
        lambda ids: {"order_id": ids.held},
        lambda ids: [{"order_id": ids.held}],
    ),
    Row("realism", "battle", PLAY, _fixed(force="norra_levy", choice="attack")),
    Row("realism", "contingency", PLAY, _fixed(force="norra_levy", when="attacked")),
    Row("realism", "agreement-publish", PLAY, _fixed(agreement="norra_sudland_pact")),
    Row("realism", "conference-call", PLAY, _fixed(conference="strait")),
    Row("realism", "conference-vote", PLAY, _fixed(conference="strait", vote="for")),
)


def registries() -> dict[str, tuple[str, ...]]:
    """Every action the server answers, by family, from its own lists."""
    return {
        "seat": tuple(server.SEAT_ACTIONS),
        "game": (*server.GAME_OPEN, *server.GAME_ACTIONS),
        "new": tuple(server.NEW_GAME_ACTIONS),
        "realism": tuple(server.REALISM_ACTIONS),
    }


def table_gaps(rows: tuple[Row, ...]) -> list[str]:
    """Actions a registry lists and the table does not, and rows no registry lists."""
    listed = {f"{family}/{a}" for family, names in registries().items() for a in names}
    tabled = {r.id for r in rows}
    return sorted(f"not in the table: {a}" for a in listed - tabled) + sorted(
        f"in no registry: {a}" for a in tabled - listed
    )


UNMARKED = (
    "rules lane fix: a seat command from an account with no seat is refused in words but sent "
    "with refused false: the web seat's own refusals (handlers.NOT_LINKED, BEGUN, BUSY) are "
    "not in the server's list of refusals (src/revisionist/engine/web/server.py, REFUSALS)"
)
UNPICK = (
    "rules lane fix: a guest who names a person in the cast is told 'Only the host can do "
    "that.' when a player holds that person and 'No player holds ...' when none does, so the "
    "refusal says who is held; refuse a guest naming anyone but their own person before the "
    "look-up (src/revisionist/engine/web/server.py, App._unpick)"
)
FINDINGS: dict[str, str] = {
    **{
        f"seat/{a}:no-seat:1": UNMARKED
        for a in (
            "roster",
            "search",
            "claim",
            "pick",
            "goal",
            "confirm",
            "history",
            "agent",
            "order",
            "ask",
            "dossier",
            "dispatch",
            "status",
            "report",
            "bug",
        )
    },
    "new/unpick:another-seats-thing:3": UNPICK,
}
"""Cases that fail today: the case's id and the fix it waits on, in the owner's lane."""


# --- the games ----------------------------------------------------------------------


@dataclass
class World:
    """The built database and every account's session cookie."""

    db: PgDb
    ids: Ids
    cookies: dict[str, str] = field(default_factory=dict)


class Site:
    """A server over one database, with the test clock and no model."""

    def __init__(self, db: PgDb, tmp: Path) -> None:
        tmp.mkdir(parents=True, exist_ok=True)
        game = Game(db, Table(), tmp / "briefings")
        static = tmp / "static"
        static.mkdir(exist_ok=True)
        (static / "index.html").write_text("<!doctype html><title>Revisionist</title>")
        self.app = App(
            db.app_dsn,
            static,
            transport_factory=lambda: game.transport,
            clock=game.clock,
            briefings=tmp / "briefings",
            offline_prose=True,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def client(self, cookie: str = "") -> Client:
        c = Client(self.base)
        c.cookie = cookie
        return c

    def run(self, fn: Callable[[Any], Any]) -> Any:
        store = self.app.open()
        try:
            return fn(store)
        finally:
            store.close()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _account(store: Any, handle: str) -> str:
    row = store.conn.execute(
        "SELECT account_id FROM web_accounts WHERE handle = %s", (handle,)
    ).fetchone()
    assert row is not None
    return str(row[0])


def _seat(decl: WorldFile, cid: CampaignId, who: str) -> SeatId:
    return SeatId(derived_id(cid, "seat", EntityId(resolve_keys(decl, cid)[who])))


def _paper(store: Any, cid: CampaignId, seat: SeatId) -> DocumentId:
    """A report to ``seat`` alone that has arrived today."""
    state = load_state(store, cid)
    today = state.in_world_date
    assert today is not None
    doc = DocumentId(derived_id(cid, "doc", "azt-paper"))
    view = DocumentView(
        doc_id=doc,
        kind=DocumentKind.INTERCEPT,
        author=state.seats[seat].embodies,
        issued=today,
        arrives=today,
        channel=ChannelKind.COURIER,
        title="An intercepted letter",
        body=(BodyField(label="Pieces seen", value=3, unit="pieces"),),
        prose="The letter names a march for the end of the month.",
        scope=private_to(seat),
    )
    payload = ev.DocumentIssued(document=view, truth=DocumentTruth(doc_id=doc))
    realism_tick._append(store, state, payload, seat)
    return doc


def staff(w: dict[str, Any]) -> None:
    """Ilse's watch goes through her staff, where Kara decides at the second step, so an
    order of Ilse's waits on Kara's agenda."""
    w["pipelines"].append(
        {
            "key": "staff",
            "name": "The staff",
            "source": "toy",
            "steps": [
                {"person": "ilse", "kind": "clerical", "days": 1},
                {"person": "kara", "kind": "decision", "days": 2},
            ],
        }
    )
    card = next(c for c in w["cards"] if c["person"] == "ilse")
    card["pipelines"] = [*card["pipelines"], "staff"]
    card["levers"][0]["pipeline"] = "staff"


def build(db: PgDb, tmp: Path) -> World:
    """The four games and their accounts, through the server where a player would act."""
    (tmp / "decl").mkdir(parents=True)
    decl = ft.toy_world(tmp / "decl", staff)
    site = Site(db, tmp / "build")
    world = World(db=db, ids=Ids())
    cookies, ids = world.cookies, world.ids

    def sign_up(handle: str) -> Client:
        """An account and a session, made as sign-up makes them, past its limit per address."""

        def make(store: Any) -> str:
            accounts = Accounts(store.conn)
            account, _ = accounts.create(handle, PASSWORD)
            return accounts.open_session(account.account_id, site.app.clock())

        cookies[handle] = site.run(make)
        return site.client(cookies[handle])

    def claim(cid: CampaignId, who: str, handle: str) -> None:
        sign_up(handle)

        def link(store: Any) -> None:
            seat = _seat(decl, cid, who)
            name = load_state(store, cid).entities[EntityId(resolve_keys(decl, cid)[who])].name
            session_zero.claim(store, cid, seat, name)
            WebSeats(store.conn).link(cid, seat, _account(store, handle))

        site.run(link)

    def host_and_begin(cid: CampaignId, handle: str) -> None:
        def start(store: Any) -> None:
            store.conn.execute(
                "INSERT INTO web_hosts (campaign_id, account_id) VALUES (%s, %s)",
                (cid, _account(store, handle)),
            )
            realism_tick.open_play(store, cid)
            wake_api.start_play(store, cid, site.app.clock(), tools=site.app._tools())

        site.run(start)

    def act(c: Client, action: str, **body: Any) -> dict[str, Any]:
        status, out = c.call(f"/api/realism/{action}", body)
        assert status == 200 and out.get("refused") is not True, out
        return dict(out)

    def end(store: Any) -> None:
        sch.register(store, site.app.clock()).retire(E, site.app.clock())
        WebSeats(store.conn).finish_campaign(E, site.app.clock())

    try:
        site.run(
            lambda store: [
                store.append_all(compile_world(decl, cid, cmp.versions())) for cid in (A, B, C, E)
            ]
        )
        for who in ("ilse", "kara", "tomas"):
            claim(A, who, f"a_{who}")
        for who in ("ilse", "kara"):
            claim(B, who, f"b_{who}")
        claim(E, "ilse", "e_ilse")
        for cid, handle in ((A, "a_ilse"), (B, "b_ilse"), (E, "e_ilse")):
            host_and_begin(cid, handle)
        site.run(end)

        # C: its host starts it from the web and plays Ilse; a guest joins on a code
        sign_up("c_host")
        site.run(
            lambda store: WebSeats(store.conn).start(
                C, SeatId(derived_id(C, "seat", "host")), _account(store, "c_host")
            )
        )
        status, out = site.client(cookies["c_host"]).call("/api/new/pick", {"name": "Ilse Varg"})
        assert status == 200 and not out["refused"], out
        guest = sign_up("c_guest")
        codes = site.run(
            lambda store: [
                Invites(store.conn).issue(C, SeatId(derived_id(C, "seat", n)), site.app.clock())
                for n in ("guest", "spare")
            ]
        )
        assert "Session Zero is open" in guest.seat("join", code=codes[0])
        ids.spare_code = codes[1]
        sign_up("loner")

        # A: Ilse's watch reaches Kara's step at the close; then what Kara holds
        ilse, kara = site.client(cookies["a_ilse"]), site.client(cookies["a_kara"])
        act(ilse, "lever", **WATCH)
        act(ilse, "close")
        items = kara.me()["game"]["view"]["realism"]["agenda"]["items"]
        (ids.item,) = [i["id"] for i in items if i["actions"] == ["pass"]]
        act(kara, "lever", **MARCH)
        mine = _seat(decl, A, "kara")
        (ids.order,) = site.run(
            lambda store: [o for o, x in load_state(store, A).orders.items() if x.issuer == mine]
        )
        act(kara, "lever", **ISLE)
        (ids.held,) = site.run(lambda store: list(load_state(store, A).held))
        act(kara, "ask", order_id=ids.held)
        ids.paper = site.run(lambda store: _paper(store, A, _seat(decl, A, "kara")))
        act(kara, "commit")
        ids.waiting = int(act(kara, "lever", **ISLE)["held"])
    finally:
        site.close()
    return world


# --- copies, snapshots and callers ------------------------------------------------


def copy_of(cluster: Cluster, src: PgDb, n: int) -> PgDb:
    """A new database copied from ``src``, connected to as the same app role."""
    source = str(conninfo_to_dict(src.admin_dsn)["dbname"])
    name = f"{source}_c{n}"
    with psycopg.connect(cluster.admin, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(source)
            )
        )
    return PgDb(
        admin_dsn=url(cluster.admin, dbname=name),
        app_dsn=url(cluster.admin, dbname=name, user=cluster.role, password=cluster.password),
        app_role=cluster.role,
    )


Rows = dict[str | None, list[str]]


def tables(db: PgDb) -> Rows:
    """Every row of every table that names a game, by game, events included."""
    out: Rows = {}
    with psycopg.connect(db.admin_dsn) as conn:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.columns WHERE table_schema = "
                "'public' AND column_name = 'campaign_id' ORDER BY table_name"
            ).fetchall()
        ]
        for t in names:
            if t in CACHES:
                continue
            q = sql.SQL("SELECT campaign_id, row_to_json(x)::text FROM {} x").format(
                sql.Identifier(t)
            )
            for cid, row in conn.execute(q).fetchall():
                out.setdefault(cid, []).append(f"{t} {row}")
    return {k: sorted(v) for k, v in out.items()}


def changed(before: Rows, after: Rows) -> set[str]:
    return {str(k) for k in {*before, *after} if before.get(k) != after.get(k)}


@dataclass(frozen=True)
class Caller:
    """One wrong caller of a row: who sends it, with what body, and which game, if any,
    it may change (its own, when the action names nothing in another)."""

    who: str
    account: str | None
    body: dict[str, Any]
    may_change: frozenset[str] = frozenset()
    must_refuse: bool = True
    fake: dict[str, Any] | None = None
    """The same request naming a thing that does not exist, for a request that names one."""


def callers(row: Row, ids: Ids) -> list[Caller]:
    """The wrong callers of ``row``, of the contract's five kinds."""
    body = row.body(ids)
    named = list(zip(row.names(ids), row.names(made_up(ids)), strict=True)) if row.names else []
    out = [Caller("no session", None, body)]
    if row.kind == OPEN:
        return out
    if row.kind != UNSEATED:
        out.append(Caller("no seat", "loner", body))
    if named:  # B's Kara names A's things
        out += [Caller("seat in another game", "b_kara", x, fake=y) for x, y in named]
    else:  # B's Kara can reach only B: it may act there, and A must not move
        own = row.kind == PLAY
        out.append(
            Caller(
                "seat in another game",
                "b_kara",
                body,
                may_change=frozenset({B}) if own else frozenset(),
                must_refuse=not own,
            )
        )
    if row.kind == UNSEATED:
        out.append(Caller("seat in this game", "a_tomas", body))
    if row.kind == PLAY_HOST:
        out.append(Caller("not the host", "a_tomas", body))
    if row.kind == ZERO_HOST:
        out.append(Caller("not the host", "c_guest", body))
    if named:
        who = "c_guest" if row.kind in (ZERO, ZERO_HOST) else "a_tomas"
        out += [Caller("another seat's thing", who, x, fake=y) for x, y in named]
    return out


def refused(status: int, out: Any) -> bool:
    if status != 200:
        return True
    return isinstance(out, dict) and (out.get("refused") is True or "error" in out)


def _said(out: Any, body: dict[str, Any]) -> str:
    """The reply with the named thing blanked, so a real and a made-up one compare."""
    text = json.dumps(out, sort_keys=True)
    for v in body.values():
        if isinstance(v, bool):
            continue
        if isinstance(v, str | int) and str(v):
            text = text.replace(str(v), "<named>")
    return text


def _label(row: Row, c: Caller, i: int) -> str:
    return f"{row.id}:{c.who.replace(' ', '-').replace(chr(39), '')}:{i}"


CASES: tuple[tuple[Row, int, str], ...] = tuple(
    (row, i, _label(row, c, i)) for row in ROWS for i, c in enumerate(callers(row, Ids()))
)
"""Each row with each of its wrong callers, by index: the callers' bodies need the built
games' ids, but how many there are and who they are does not."""


class Copies:
    """A copy of the games for each row, shared by the row's callers in turn; a caller
    that changed anything leaves the next a fresh copy."""

    def __init__(self, world: World, cluster: Cluster, tmp: Path) -> None:
        self.world, self.cluster, self.tmp = world, cluster, tmp
        self.n = count(1)
        self.open: dict[str, tuple[PgDb, Site]] = {}

    def get(self, key: str) -> tuple[PgDb, Site]:
        if key not in self.open:
            n = next(self.n)
            db = copy_of(self.cluster, self.world.db, n)
            self.open[key] = (db, Site(db, self.tmp / f"c{n}"))
        return self.open[key]

    def spoil(self, key: str) -> None:
        if key in self.open:
            db, site = self.open.pop(key)
            site.close()
            self.cluster.drop(db)

    def close(self) -> None:
        for key in list(self.open):
            self.spoil(key)


def run_case(row: Row, i: int, world: World, copies: Copies) -> list[str]:
    """Wrong caller ``i`` of ``row`` on the row's copy of the games; what went wrong."""
    c = callers(row, world.ids)[i]
    db, site = copies.get(row.id)
    found: list[str] = []
    client = site.client(world.cookies[c.account] if c.account else "")
    path = f"/api/{row.family}/{row.action}"
    before = tables(db)
    status, out = client.call(path, c.body)
    if c.must_refuse and not refused(status, out):
        found.append(f"not refused: {status} {out}")
    if c.fake is not None:
        again, other = client.call(path, c.fake)
        if (status, _said(out, c.body)) != (again, _said(other, c.fake)):
            found.append(f"says it exists: {out} against {other}")
    moved = changed(before, tables(db))
    if moved - c.may_change:
        found.append(f"changed {sorted(moved - c.may_change)}")
    if moved or found or i == len(callers(row, world.ids)) - 1:
        copies.spoil(row.id)
    label = f"{row.id} by {c.who} {json.dumps(c.body, sort_keys=True)}"
    return [f"{label}: {f}" for f in found]


# --- the tests ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def world(pg_cluster: Cluster, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    db = pg_cluster.fresh()
    with pytest.MonkeyPatch.context() as mp:  # the autouse setting is per test
        mp.setenv("REVISIONIST_MARK_SECRET", "12" * 32)
        try:
            yield build(db, tmp_path_factory.mktemp("azt"))
        finally:
            pg_cluster.drop(db)


@pytest.fixture(scope="module")
def copies(
    world: World, pg_cluster: Cluster, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Copies]:
    made = Copies(world, pg_cluster, tmp_path_factory.mktemp("copies"))
    try:
        yield made
    finally:
        made.close()


def _case(row: Row, i: int, label: str) -> Any:
    fix = FINDINGS.get(label)
    marks = [pytest.mark.xfail(strict=True, reason=fix)] if fix else []
    return pytest.param(row, i, id=label, marks=marks)


@pytest.mark.parametrize(("row", "i"), [_case(*c) for c in CASES])
def test_every_wrong_caller_is_refused_and_changes_nothing(
    row: Row, i: int, world: World, copies: Copies
) -> None:
    found = run_case(row, i, world, copies)
    assert not found, "\n".join(found)


def test_the_table_lists_every_action_the_server_answers() -> None:
    assert not table_gaps(ROWS), table_gaps(ROWS)
    assert all(r.kind in KINDS for r in ROWS)
    assert len({r.id for r in ROWS}) == len(ROWS)


def test_an_action_left_out_of_the_table_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "REALISM_ACTIONS", (*server.REALISM_ACTIONS, "new-thing"))
    assert table_gaps(ROWS) == ["not in the table: realism/new-thing"]
    monkeypatch.undo()
    assert table_gaps(ROWS[1:]) == [f"not in the table: {ROWS[0].id}"]


def _dispatched(fn: ast.FunctionDef) -> set[str]:
    """The action names a method compares ``action`` with."""
    found: set[str] = set()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)):
            continue
        if node.left.id != "action":
            continue
        for right in node.comparators:
            if isinstance(right, ast.Constant) and isinstance(right.value, str):
                found.add(right.value)
            elif isinstance(right, ast.Tuple):
                found |= {
                    e.value
                    for e in right.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
    return found


def test_the_registries_and_the_dispatch_name_the_same_actions() -> None:
    """A branch whose name is in no list is never reached, and a listed name with no
    branch is refused as no such call: the lists and the code must agree."""
    tree = ast.parse(Path(server.__file__).read_text())
    app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App")
    methods = {f.name: f for f in app.body if isinstance(f, ast.FunctionDef)}
    reg = registries()
    realism = _dispatched(methods["realism"])
    game = _dispatched(methods["game"]) | {"end"}  # reached past the last branch
    new = set().union(*(_dispatched(methods[m]) for m in ("new_game", "_session_zero", "_start")))
    new |= {"begin"}  # reached past the last branch
    assert realism == set(reg["realism"]), realism ^ set(reg["realism"])
    assert game == set(reg["game"]), game ^ set(reg["game"])
    assert new == set(reg["new"]), new ^ set(reg["new"])


def test_every_finding_names_a_case_and_a_fix_and_is_strict() -> None:
    assert set(FINDINGS) <= {label for _, _, label in CASES}
    lanes = ("core", "rules", "data", "scenario", "board", "surface")
    assert all(fix.split(" lane fix: ")[0] in lanes for fix in FINDINGS.values())
    for case in CASES:
        marks = _case(*case).marks
        assert [m.kwargs.get("strict") for m in marks] == ([True] if case[2] in FINDINGS else [])


def test_the_matrix_is_red_on_a_dropped_ownership_check(
    world: World, copies: Copies, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A held order withdrawn by its number alone, whoever holds it, is found."""

    def drop(store: Any, campaign_id: Any, seat: Any, held_id: int) -> bool:
        rows = store.conn.execute(
            "DELETE FROM web_held_orders WHERE held_id = %s RETURNING 1", (held_id,)
        ).fetchall()
        return bool(rows)

    monkeypatch.setattr(held, "drop", drop)
    cases = [(r, i) for r, i, label in CASES if label.startswith("realism/withdraw:")]
    found = [f for r, i in cases for f in run_case(r, i, world, copies)]
    assert [f for f in found if '"held_id"' in f] and all("held_id" in f for f in found), found


OWNED: tuple[tuple[str, str, Callable[[Ids], dict[str, Any]]], ...] = (
    ("read", "a_kara", lambda ids: {"doc_id": ids.paper}),
    ("flag", "a_kara", lambda ids: {"doc_id": ids.paper, "flagged": True}),
    ("step", "a_kara", lambda ids: {"order_id": ids.item, "action": "pass"}),
    ("withdraw", "a_kara", lambda ids: {"held_id": ids.waiting}),
)
"""Requests the matrix sends as another seat, sent by the seat that holds the thing."""


@pytest.mark.parametrize(("action", "who", "body"), OWNED, ids=[o[0] for o in OWNED])
def test_the_things_named_are_real_and_their_holder_may_act_on_them(
    action: str,
    who: str,
    body: Callable[[Ids], dict[str, Any]],
    world: World,
    copies: Copies,
) -> None:
    """The control: the matrix's refusals are of the caller, not of a wrong request."""
    _, site = copies.get(f"owned/{action}")
    try:
        status, out = site.client(world.cookies[who]).call(
            f"/api/realism/{action}", body(world.ids)
        )
        assert status == 200 and out.get("refused") is not True, out

        def held_by_kara(store: Any) -> tuple[bool, bool]:
            state = load_state(store, A)
            kara = next(s for s in state.seats.values() if s.name == "Kara Lind").seat_id
            return (
                state.orders[OrderId(world.ids.order)].issuer == kara,
                state.held[OrderId(world.ids.held)].issuer == kara,
            )

        assert site.run(held_by_kara) == (True, True)
    finally:
        copies.spoil(f"owned/{action}")
