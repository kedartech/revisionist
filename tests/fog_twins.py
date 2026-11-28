"""Twin worlds for the fog sweep: two games that differ in one fact a seat may not know.

A pair is two games on the same campaign id, each in its own scratch database and served
by its own ``App``, built the same way through the engine's public entry points (the
world file, a claim, the wake's opening, the server's own actions) except for one hidden
fact, which only the second game (``hidden=True``) carries. ``reads`` collects every
read the viewing seat can make and ``refusals`` every refusal it can provoke by naming
the hidden thing, each as the bytes the server would send, with the seat's view and its
agent's prompt as a model is given them. The sweep
(``tests/test_fog_sweep.py``) compares the two games' bytes; another item's test may
import ``PAIRS``, ``Side``, ``reads`` and ``refusals`` and run them with its own rule on.

The toy world is ``tests/worlds/territory-toy.yaml`` as the lock tests build it (Ilse
Varg, Kara Lind and Olaf Brun of Norra, Tomas Brand of Sudland) with the groups rule on;
Salt Strait is ``worlds/salt-strait-realism.yaml`` (Oren Vale of Varda, the Marshal Aske
of Ostrel, and Kesh and the Lune Isles run by code).
"""

import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Any

import yaml

from revisionist.core import events as ev
from revisionist.core.fold import state_hash
from revisionist.core.ids import DocumentId, EntityId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import BodyField, DocumentKind, DocumentTruth, DocumentView
from revisionist.core.visibility import private_to
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, counsel, directive, emit, notice, realism_tick, session_zero
from revisionist.engine import wake as wk
from revisionist.engine.advise import advise
from revisionist.engine.llm import Reply, Request
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import wake_api
from revisionist.engine.web.accounts import Account, WebSeats
from revisionist.engine.web.server import ApiError
from tests import test_realism_locks as toy_locks
from tests.pg import Cluster, PgDb
from tests.test_ask_answers import answers_on, hostile
from tests.test_session_zero_steps import Table
from tests.test_territory_model import CAMPAIGN, written
from tests.test_web import Web

World = dict[str, Any]
ROOT = Path(__file__).resolve().parents[1]
SALT = ROOT / "worlds" / "salt-strait-realism.yaml"


# --- the two worlds ------------------------------------------------------------------


def toy_world(tmp: Path, change: Callable[[World], None]) -> WorldFile:
    """The lock tests' toy world with the groups rule on, then ``change``."""

    def more(w: World) -> None:
        w["rules"] = sorted({*w["rules"], "groups"})
        change(w)

    return toy_locks.world(tmp, more)


def salt_world(tmp: Path, change: Callable[[World], None]) -> WorldFile:
    """Salt Strait with ``change`` applied, written beside its own map."""
    raw: World = yaml.safe_load(SALT.read_text())
    change(raw)
    board = (SALT.parent / "maps" / str(raw["map"]["file"])).read_bytes()
    return written(tmp, raw, board)


WORLDS: dict[str, Callable[[Path, Callable[[World], None]], WorldFile]] = {
    "toy": toy_world,
    "salt": salt_world,
}

TOY_SEATS = ("ilse", "kara", "olaf", "tomas")
SALT_SEATS = ("oren_vale", "general_aske")


# --- ids drawn the same way in both games --------------------------------------------


ID_MODULES = (realism_tick, wk, emit, directive, counsel, cmp, session_zero)
"""Every engine module a game of a pair draws a random id in (``new_id``)."""

CONTENT = ("seat", "issuer", "lever", "params", "today", "asks", "parts", "payload", "kind")
"""The caller's locals an id is drawn from: what is being named, never the log's length."""

_counts: list[Counter[str]] = []


def stable_id() -> str:
    """An id drawn from what its caller is naming and how often it has named it, in
    place of a random one. Seeded rolls (an order's fidelity, a route) read ids, so with
    random ids two games built the same way would roll apart; with these, the same
    order in both games gets the same id, and an act only one game has draws ids of its
    own without moving the other ids."""
    frame = sys._getframe(1)
    named = sorted((k, repr(v)) for k, v in frame.f_locals.items() if k in CONTENT)
    base = repr((frame.f_code.co_name, frame.f_lineno, named))
    counts = _counts[-1]
    counts[base] += 1
    return derived_id("fog-twins", base, counts[base])


@contextmanager
def drawn_from(counts: Counter[str]) -> Iterator[None]:
    """Every ``new_id`` in the engine is ``stable_id`` on ``counts`` meanwhile."""
    saved = [m.new_id for m in ID_MODULES]
    _counts.append(counts)
    for m in ID_MODULES:
        m.new_id = stable_id  # type: ignore[attr-defined]
    try:
        yield
    finally:
        _counts.pop()
        for m, f in zip(ID_MODULES, saved, strict=True):
            m.new_id = f  # type: ignore[attr-defined]


# --- one game of a pair --------------------------------------------------------------


@dataclass
class Side:
    """One game of a pair: a scratch database, its ``App`` and the seated accounts."""

    web: Web
    decl: WorldFile
    accounts: dict[str, Account] = field(default_factory=dict)
    counts: Counter[str] = field(default_factory=Counter)
    hosting: str = ""
    """Who hosts the game, once ``host`` has run."""

    @property
    def app(self) -> Any:
        return self.web.app

    def ids(self) -> dict[str, str]:
        return resolve_keys(self.decl, CAMPAIGN)

    def seat(self, who: str) -> SeatId:
        return SeatId(derived_id(CAMPAIGN, "seat", EntityId(self.ids()[who])))

    def state(self) -> Any:
        store = self.app.open()
        try:
            return load_state(store, CAMPAIGN)
        finally:
            store.close()

    def run(self, fn: Callable[[Any], Any]) -> Any:
        store = self.app.open()
        try:
            with drawn_from(self.counts):
                return fn(store)
        finally:
            store.close()

    def claim(self, who: str) -> Account:
        """Sign ``who`` up as an account of that name and seat it as ``who``."""
        client, _ = self.web.signed_up(who)
        handle = client.me()["account"]["handle"]

        def link(store: Any) -> Account:
            name = load_state(store, CAMPAIGN).entities[EntityId(self.ids()[who])].name
            session_zero.claim(store, CAMPAIGN, self.seat(who), name)
            row = store.conn.execute(
                "SELECT account_id FROM web_accounts WHERE handle = %s", (handle,)
            ).fetchone()
            assert row is not None
            WebSeats(store.conn).link(CAMPAIGN, self.seat(who), row[0])
            return Account(account_id=row[0], handle=handle)

        account: Account = self.run(link)
        self.accounts[who] = account
        return account

    def host(self, who: str) -> None:
        account = self.accounts[who]
        self.hosting = who

        def insert(store: Any) -> None:
            store.conn.execute(
                "INSERT INTO web_hosts (campaign_id, account_id) VALUES (%s, %s)",
                (CAMPAIGN, account.account_id),
            )

        self.run(insert)

    def begin(self) -> None:
        """Open play as the server's ``begin`` does: play, then wake 0 and its offers."""

        def start(store: Any) -> None:
            realism_tick.open_play(store, CAMPAIGN)
            wake_api.start_play(store, CAMPAIGN, self.app.clock(), tools=self.app._tools())

        self.run(start)

    def act(self, who: str, action: str, /, **body: Any) -> dict[str, Any]:
        """``/api/realism/<action>`` as ``who``'s account sends it, through ``App``."""
        with drawn_from(self.counts):
            out: dict[str, Any] = self.app.realism(self.accounts[who], action, body)
        return out

    def me(self, who: str) -> dict[str, Any]:
        """``/api/me`` as ``who``'s account reads it, through ``App``."""
        with drawn_from(self.counts):
            out: dict[str, Any] = self.app.state_for(self.accounts[who])
        return out

    def new(self, who: str, action: str) -> dict[str, Any]:
        """``/api/new/<action>`` as ``who``'s account sends it, through ``App``."""
        with drawn_from(self.counts):
            out: dict[str, Any] = self.app.new_game(self.accounts[who], action, {})
        return out

    def game(self, who: str, action: str) -> dict[str, Any]:
        """``/api/game/<action>`` as ``who``'s account sends it, through ``App``."""
        with drawn_from(self.counts):
            out: dict[str, Any] = self.app.game(self.accounts[who], action, {})
        return out


def side(db: PgDb, tmp: Path, decl: WorldFile) -> Side:
    tmp.mkdir(parents=True, exist_ok=True)
    web = Web(db, tmp, Table())
    s = Side(web=web, decl=decl)
    s.run(lambda store: store.append_all(compile_world(decl, CAMPAIGN, cmp.versions())))
    return s


# --- what the seat can read, and what it can provoke ---------------------------------


def _bytes(payload: Any) -> bytes:
    return json.dumps(payload).encode()


RANDOM_ID = re.compile(rb"\b[0-9A-HJKMNP-TV-Z]{26}\b|\b[0-9a-f]{12}\b")
"""A 26-character id, or the 12-digit short form some replies cut from one."""


def canonical(found: dict[str, bytes]) -> dict[str, bytes]:
    """``found`` with every 26-character id renamed by its first appearance, keys and
    replies read in order. The engine draws most ids at random (``new_id``), so two
    games built the same way name the same page differently; an id still tells the seat
    nothing, and a difference in how many there are or where they recur still shows."""
    names: dict[bytes, bytes] = {}

    def rename(m: re.Match[bytes]) -> bytes:
        return names.setdefault(m.group(0), b"id%d" % (len(names) + 1))

    out: dict[str, bytes] = {}
    for key, raw in found.items():
        k = RANDOM_ID.sub(rename, key.encode()).decode()
        out[k] = RANDOM_ID.sub(rename, raw)
    return out


def _call(fn: Callable[[], Any]) -> bytes:
    """The bytes the server sends for one call: its reply, or its error and status."""
    try:
        return _bytes(fn())
    except ApiError as exc:
        return _bytes({"status": int(exc.status), "error": exc.message})


@dataclass(frozen=True)
class Probe:
    """One request the seat can send: an action and its body."""

    action: str
    body: dict[str, Any] = field(default_factory=dict)

    def label(self) -> str:
        return f"{self.action} {json.dumps(self.body, sort_keys=True)}"


TOY_READS = (
    Probe("check", {"lever": "march", "params": {"force": "norra_levy", "to": "isle"}}),
    Probe("check", {"lever": "march", "params": {"force": "norra_levy", "to": "sudland_coast"}}),
    Probe("odds", {"force": "norra_levy", "to": "sudland_coast"}),
)
SALT_READS = (
    Probe("check", {"lever": "move_force", "params": {"force": "varda_levy", "to": "harrow_pass"}}),
    Probe("check", {"lever": "declare_war", "params": {"target": "ostrel"}}),
    Probe("odds", {"force": "varda_levy", "to": "harrow_pass"}),
    Probe("odds", {"force": "varda_galleys", "to": "the_strait"}),
)
READS = {"toy": TOY_READS, "salt": SALT_READS}


def reads(
    s: Side, who: str, probes: tuple[Probe, ...], seam: bool = False, apart: bool = False
) -> dict[str, bytes]:
    """Every read ``who`` can make: the snapshot (every sheet's data is in it), each
    page it holds, the map, catch-up, the opening's list of people, the check and the
    odds, the wake notice, the seat's view and the prompt a model is sent. With ``seam``,
    also the catch-up seam itself and the seat's own record of its asks. With ``apart``,
    the view and the prompt leave out who is seated (``_unseated``)."""
    out = {"me": _call(lambda: s.me(who)), "opening": opening(s, who)}
    me = json.loads(out["me"])
    realism = ((me.get("game") or {}).get("view") or {}).get("realism") or {}
    listing = realism.get("documents") or {}
    for item in listing.get("documents", []):
        out[f"read {item['id']}"] = _call(partial(s.act, who, "read", doc_id=item["id"]))
    out["map"] = _call(lambda: s.act(who, "map"))
    out["catchup"] = _call(lambda: s.act(who, "catchup"))
    for p in probes:
        out[p.label()] = _call(partial(s.act, who, p.action, **p.body))
    state = s.state()
    name = s.run(lambda store: notice._game_name(store, CAMPAIGN))
    try:
        out["notice"] = _bytes(notice.compose(state, s.seat(who), None, name))
    except ValueError as exc:
        out["notice"] = _bytes({"error": str(exc)})
    if seam:
        out["seam"] = _bytes(s.run(partial(_fed, s.seat(who))))
        asked = project(state, s.seat(who)).asked.values()
        out["asked"] = _bytes(sorted((a.model_dump(mode="json") for a in asked), key=str))
    view = project(state, s.seat(who))
    out["view"] = view.model_dump_json().encode()
    out["prompt"] = advice_prompt(s, who)
    if apart:
        out["view"], out["prompt"] = _unseated(view, out["view"], out["prompt"])
    return out


def _unseated(view: Any, raw: bytes, prompt: bytes) -> tuple[bytes, bytes]:
    """``raw`` (the view) and ``prompt`` with the roster's claims and the seat faces left
    out: they tell any person a seat holds from one the code runs, the "person or code"
    pair's finding, so a pair whose games seat different people reads past them."""
    shown = json.loads(raw)
    shown["roster"] = {k: {**c, "claimed_by": None} for k, c in shown["roster"].items()}
    shown["seats"] = {}
    faces = view.model_dump_json(include={"seats"}, exclude_none=True)[1:-1].encode()
    assert faces in prompt, "the prompt no longer carries the seat faces as the view dumps them"
    return _bytes(shown), prompt.replace(faces, b'"seats":{}')


class _Asked:
    """A transport that keeps the request it is sent and answers nothing."""

    def __init__(self) -> None:
        self.requests: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.requests.append(request)
        return Reply({"text": ""}, request.model, 0, 0, 0, 0.0)


def advice_prompt(s: Side, who: str) -> bytes:
    """The prompt ``who``'s agent would be sent for a question: the seat's view as a
    model reads it, and so as the adviser, the narrator and the agent are given it."""
    t = _Asked()
    copy = MemoryStore()  # the call logs its cost: on a copy, so the game is untouched
    copy.append_all(s.run(lambda store: list(store.read(CAMPAIGN))))
    advise(copy, CAMPAIGN, s.seat(who), "What now?", t)
    (req,) = t.requests
    return req.prompt.encode()


def opening(s: Side, who: str) -> bytes:
    """``/api/new/opening`` as ``who`` reads it: the people of the game, who is taken,
    and the seats left."""
    return _call(lambda: s.new(who, "opening"))


def _fed(seat: SeatId, store: Any) -> list[Any]:
    """Every event the catch-up seam feeds ``seat``, by wake, kind and payload: what any
    feed built on it may draw, whether or not one draws it yet."""
    fed = catchup.seat_events(store, CAMPAIGN, seat, 0, 999)
    return [(f.wake, f.event.kind, f.event.payload.model_dump(mode="json")) for f in fed]


def truth(s: Side) -> tuple[str, list[Any], list[Any]]:
    """What the game holds, whoever may see it: the state's hash, every order held for
    the next wake and who filed each player report. The two games of a pair must differ
    here, or the pair hides nothing."""

    def held(store: Any) -> list[Any]:
        rows = store.conn.execute(
            "SELECT seat_id, action, args FROM web_held_orders ORDER BY held_id"
        ).fetchall()
        return [tuple(r) for r in rows]

    def filed(store: Any) -> list[Any]:
        rows = store.conn.execute(
            "SELECT seat_id, kind FROM player_reports ORDER BY report_id"
        ).fetchall()
        return [tuple(r) for r in rows]

    return state_hash(s.state()), s.run(held), s.run(filed)


def where(key: str, x: bytes, y: bytes) -> str:
    """Where two replies part, for reading a finding."""
    i = next((i for i, (p, q) in enumerate(zip(x, y, strict=False)) if p != q), min(len(x), len(y)))
    return f"{key}\n  a: {x[max(0, i - 160) : i + 160]!r}\n  b: {y[max(0, i - 160) : i + 160]!r}"


def refusals(s: Side, who: str, probes: tuple[Probe, ...]) -> dict[str, bytes]:
    """The reply to each request that names the hidden thing."""
    return {p.label(): _call(partial(s.act, who, p.action, **p.body)) for p in probes}


# --- the pairs ------------------------------------------------------------------------


Change = Callable[[World, bool], None]
Act = Callable[[Side, bool], None]


def _no_change(w: World, hidden: bool) -> None:
    return None


def _no_act(s: Side, hidden: bool) -> None:
    return None


@dataclass(frozen=True)
class Pair:
    """One kind of hidden fact in one world, seen from each of ``viewers``' seats.

    ``change`` edits the world file and ``act`` plays after wake 0 opens; each is told
    which game it builds, and only the second (``hidden``) carries the fact. ``names``
    are the requests that name the hidden thing, sent after the reads. ``wakes``: how
    many wakes the host closes before the reads are taken again (none for a fact that
    the seat is due to learn by then, such as a report on its way)."""

    kind: str
    world: str
    viewers: tuple[str, ...]
    change: Change = _no_change
    act: Act = _no_act
    names: Callable[[Side], tuple[Probe, ...]] = lambda s: ()
    unseated: str | None = None
    """A person seated by an account in the first game and left to code in the second."""
    swapped: str | None = None
    """A person left to code in the first game only, so both games seat as many people."""
    host: str | None = None
    """Who hosts both games; the world's usual host when None."""
    wakes: int = 1
    seam: bool = False
    """Also compare the catch-up seam and the seat's record of its asks (``reads``)."""
    apart: bool = False
    """The two games seat different people: the view and the prompt are read without who
    is seated (``reads``), which the "person or code" pair holds as its own finding."""

    @property
    def id(self) -> str:
        return f"{self.world}-{self.kind.replace(' ', '-')}"

    def seated(self, hidden: bool) -> tuple[str, ...]:
        every = TOY_SEATS if self.world == "toy" else SALT_SEATS
        coded = self.unseated if hidden else self.swapped
        return tuple(p for p in every if p != coded)


def build(pair: Pair, db: PgDb, tmp: Path, hidden: bool) -> Side:
    """One game of ``pair``: the world, the seats, wake 0, then the pair's act."""
    tmp.mkdir(parents=True, exist_ok=True)
    decl = WORLDS[pair.world](tmp, lambda w: pair.change(w, hidden))
    s = side(db, tmp / "game", decl)
    for who in pair.seated(hidden):
        s.claim(who)
    s.host(pair.host or HOSTS[pair.world])
    s.begin()
    pair.act(s, hidden)
    return s


HOSTS = {"toy": "ilse", "salt": "oren_vale"}


def close_wake(s: Side) -> None:
    """The host closes the open wake, as its "close the wake now" does."""
    out = s.act(s.hosting or HOSTS[s_world(s)], "close")
    assert not out.get("refused"), out


def s_world(s: Side) -> str:
    return "salt" if s.decl.world == "salt-strait-realism" else "toy"


def _done(out: dict[str, Any]) -> None:
    """An act a pair is built from must land, or the pair would compare nothing."""
    assert out.get("refused") is not True, out


def _find(rows: list[World], key: str) -> World:
    return next(r for r in rows if r.get("key") == key or r.get("person") == key)


# toy: the kinds


def toy_piece(w: World, hidden: bool) -> None:
    """The Norra Levy's strength (its tier), which Sudland has no report of."""
    if hidden:
        _find(w["features"], "norra_levy")["tier"] = 3


def toy_economy(w: World, hidden: bool) -> None:
    """Norra's shipping, a figure Norra keeps to itself."""
    if hidden:
        _find(w["quantities"], "norra_shipping")["value"] = 140000


def toy_groups(w: World, hidden: bool) -> None:
    """The Greys' support in Norra (they feed votes only, not the public standing)."""
    if hidden:
        for nation in w["groups"]:
            for g in nation["groups"]:
                if g["key"] == "greys":
                    g["start"] = g["baseline"] = 45


def toy_held(s: Side, hidden: bool) -> None:
    """Kara's march to the Isle, held for Ilse, and Kara's ask of her."""
    if hidden:
        _done(s.act("kara", "lever", lever="march", params={"force": "norra_levy", "to": "isle"}))
        (held_id,) = list(s.state().held)
        _done(s.act("kara", "ask", order_id=held_id))


def toy_unplayed_decider(w: World, hidden: bool) -> None:
    """Both games: asks are answered, and the march to the Isle is held for Sven Hald, a
    councillor of Norra with a card, no written answers and no seat."""
    w["rules"] = sorted({*w["rules"], "ask_answers"})
    w["entities"].append({"key": "sven", "kind": "person", "name": "Sven Hald", "parent": "norra"})
    w["cards"].append({"person": "sven", "office": "Councillor of Norra", "horizon_days": 14})
    _find(w["locks"], "island_march")["decider"] = {"person": "sven"}


def toy_ask_unplayed(s: Side, hidden: bool) -> None:
    """Kara's march to the Isle, held for Sven, in both games; Kara asks him for it in one."""
    _done(s.act("kara", "lever", lever="march", params={"force": "norra_levy", "to": "isle"}))
    if hidden:
        (held_id,) = list(s.state().held)
        _done(s.act("kara", "ask", order_id=held_id))


def toy_held_names(s: Side) -> tuple[Probe, ...]:
    ids = list(s.state().held) or ["no-such-order"]
    return tuple(Probe(a, {"order_id": str(i)}) for i in ids for a in ("ask", "withdraw")) + tuple(
        Probe("step", {"order_id": str(i), "action": "pass"}) for i in ids
    )


def toy_declined(w: World, hidden: bool) -> None:
    """Asks answered, and Ilse cold to Kara and holding to the Isle, so her card declines."""
    answers_on(w)
    hostile(w)


def toy_asked(s: Side, hidden: bool) -> None:
    """Kara's march to the Isle, held for Ilse, and Kara's ask of her, in both games."""
    _done(s.act("kara", "lever", lever="march", params={"force": "norra_levy", "to": "isle"}))
    (held_id,) = list(s.state().held)
    _done(s.act("kara", "ask", order_id=held_id))


def toy_defiant(w: World, hidden: bool) -> None:
    """Both games: Kara may cross a border without leave, a move to the Isle needs Ilse,
    and Olav carries out Kara's command (``tests/test_defiance.py``'s world)."""
    from tests.test_defiance import defiant

    toy_locks.isle_move(w)
    defiant("border")(w)


def toy_incident(s: Side, hidden: bool) -> None:
    """Both games: Kara sends her march to the Isle anyway, the wake closes and Olav
    carries it out, which puts the incident before Ilse. In the first game Ilse, a
    person, answers it at once, as her card will answer it in the second."""
    from revisionist.core.realism import defiance
    from tests.test_defiance import to_isle

    held = s.run(
        lambda store: realism_tick.commit_order(store, CAMPAIGN, s.seat("kara"), (to_isle(),))
    )
    _done(s.act("kara", "send-anyway", order_id=held.order_id))
    close_wake(s)
    state = s.state()
    (incident,) = state.incidents.values()
    assert incident.verdict is None, incident
    if not hidden:
        verdict = defiance.card_verdict(state, incident)
        _done(s.act("ilse", "answer", item=incident.incident_id, verdict=verdict.value))


def toy_aims(w: World, hidden: bool) -> None:
    """Ilse's own aims."""
    _find(w["cards"], "ilse")["aims"] = (
        ["Take the Sudland Coast by summer."] if hidden else ["Hold the Norra Plain."]
    )


UNARRIVED = DocumentId(derived_id(CAMPAIGN, "doc", "fog-unarrived"))


def unarrived(person: str) -> Act:
    """A report to ``person`` issued today that arrives in five days."""

    def act(s: Side, hidden: bool) -> None:
        if not hidden:
            return
        state = s.state()
        today = state.in_world_date
        who = s.seat(person)
        view = DocumentView(
            doc_id=UNARRIVED,
            kind=DocumentKind.INTERCEPT,
            author=state.seats[who].embodies,
            issued=today,
            arrives=today + timedelta(days=5),
            channel=ChannelKind.COURIER,
            title="An intercepted letter",
            body=(BodyField(label="Pieces seen", value=3, unit="pieces"),),
            prose="The letter names a march for the end of the month.",
            scope=private_to(who),
        )
        payload = ev.DocumentIssued(document=view, truth=DocumentTruth(doc_id=UNARRIVED))
        s.run(lambda store: realism_tick._append(store, state, payload, who))

    return act


def unarrived_names(s: Side) -> tuple[Probe, ...]:
    return (
        Probe("read", {"doc_id": UNARRIVED}),
        Probe("flag", {"doc_id": UNARRIVED, "flagged": True}),
    )


def toy_law(w: World, hidden: bool) -> None:
    """The arming law's passed flag, not public."""
    if hidden:
        toy_locks.law_passed(w)


def committed_lever(who: str, lever: str, params: dict[str, str]) -> Act:
    """``who`` presses Done in both games, then in one gives an order, which waits for
    the next wake."""

    def act(s: Side, hidden: bool) -> None:
        _done(s.act(who, "commit"))
        if hidden:
            out = s.act(who, "lever", lever=lever, params=params)
            assert out.get("held") is not None, out

    return act


def own_held(lever: str, params: dict[str, str]) -> Callable[[Side], tuple[Probe, ...]]:
    """The viewer presses Done and gives an order of its own (its reply numbers the
    held order), then tries to withdraw the first held order of the game."""

    def names(s: Side) -> tuple[Probe, ...]:
        return (
            Probe("commit"),
            Probe("lever", {"lever": lever, "params": params}),
            Probe("withdraw", {"held_id": 1}),
        )

    return names


# salt: the kinds


def salt_piece(w: World, hidden: bool) -> None:
    """The Ostrel Levy's strength and place: at Kael, or stronger and at the High Temple,
    both out of sight of every Varda source."""
    if hidden:
        levy = _find(w["features"], "ostrel_levy")
        levy["tier"], levy["places"] = 3, ["high_temple"]


def salt_economy(w: World, hidden: bool) -> None:
    """Ostrel's fuel stock."""
    stock = 40.0 if hidden else 10.0
    w["fuel_stocks"] = [{"polity": "ostrel", "amount": stock, "source": "salt_strait"}]


def salt_groups(w: World, hidden: bool) -> None:
    """What moves the Marshal's staff in Ostrel, and what it is called. Its support is
    left alone: every nation's standing is a public band, and the staff feeds it."""
    if hidden:
        for nation in w["groups"]:
            for g in nation["groups"]:
                if g["key"] == "marshals_staff":
                    g["name"] = "The Old Guard"
                    g["moved_by"] = {"battle_won": 1, "battle_lost": -5, "war_declared": 3}


def conference_now(w: World, hidden: bool) -> None:
    """Both games: the strait's conference open from the first day, voting on the 20th."""
    c = _find(w["conferences"], "strait_peace_conference")
    c["opens"], c["voting_day"] = "1900-04-02", "1900-04-20"


def salt_vote(s: Side, hidden: bool) -> None:
    """The Marshal's sealed vote: for in one game, against in the other, once the
    first wake has opened the conference."""
    close_wake(s)
    _done(
        s.act(
            "general_aske",
            "conference-vote",
            conference="strait_peace_conference",
            vote="against" if hidden else "for",
        )
    )


SECRET = "ostrel_kesh_secret"


def salt_agreement(w: World, hidden: bool) -> None:
    """A secret pact between Ostrel and Kesh."""
    if hidden:
        w["pacts"].append(
            {
                "key": SECRET,
                "name": "The Fodder Understanding",
                "parties": ["ostrel", "kesh"],
                "public": False,
                "wording": "Kesh goes to war within seven days on any power that attacks Ostrel.",
                "source": "salt_strait",
                "clauses": [{"type": "defend", "binds": "kesh", "nation": "ostrel", "days": 7}],
            }
        )


def salt_agreement_names(s: Side) -> tuple[Probe, ...]:
    made = list(s.state().agreements.made) or [SECRET]
    return tuple(Probe("agreement-publish", {"agreement": k}) for k in {SECRET, *made})


def salt_aims(w: World, hidden: bool) -> None:
    """The Marshal's third aim."""
    if hidden:
        card = _find(w["cards"], "general_aske")
        card["aims"][2] = "Keep the Kael burghers fed."
        card["aim_rules"][2] = {
            "aim": 3,
            "deadline": "1900-07-31",
            "replaceable": True,
            "rule": "The Kael burghers' support is 60 or more.",
            "condition": {
                "check": "support_at",
                "nation": "ostrel",
                "group": "kael_burghers",
                "op": "ge",
                "value": 60,
            },
        }


def leaves(who: str) -> Act:
    """``who``'s player leaves the game in the open wake, as the game menu's leave does:
    the leader is the code's from the close."""

    def act(s: Side, hidden: bool) -> None:
        if hidden:
            _done(s.game(who, "leave"))

    return act


REPORT_WORDS = "The toll on my desk reads 9 and the map says 8."
INBOX = (Probe("reports", {"inbox": True}),)


def report_author(s: Side, hidden: bool) -> None:
    """The same words filed as a report by Kara, or (hidden) by Tomas of the other side:
    the host reads them in the inbox, and must not learn whose they are."""
    _done(s.act("tomas" if hidden else "kara", "report", kind="bug", text=REPORT_WORDS))


SALT_PIECE_NAMES = (
    Probe("odds", {"force": "varda_levy", "to": "harrow_pass"}),
    Probe("odds", {"force": "varda_balloons", "to": "harrow_pass"}),
    Probe(
        "check",
        {
            "lever": "fly_balloon",
            "params": {"intel": "recon", "piece": "varda_balloons", "area": "harrow_pass"},
        },
    ),
)

PAIRS: tuple[Pair, ...] = (
    Pair("enemy piece", "toy", ("tomas",), change=toy_piece),
    Pair("other economy", "toy", ("tomas",), change=toy_economy),
    Pair("other groups", "toy", ("tomas",), change=toy_groups),
    Pair("held order and ask", "toy", ("olaf", "tomas"), act=toy_held, names=toy_held_names),
    Pair("other aims", "toy", ("kara", "tomas"), change=toy_aims),
    Pair(
        "ask to a person with no seat",
        "toy",
        ("olaf", "tomas"),
        change=toy_unplayed_decider,
        act=toy_ask_unplayed,
    ),
    Pair(
        "report not arrived",
        "toy",
        ("ilse",),
        act=unarrived("ilse"),
        names=unarrived_names,
        wakes=0,
    ),
    Pair("report author", "toy", ("ilse",), act=report_author, names=lambda s: INBOX),
    Pair("person or code", "toy", ("ilse", "kara"), unseated="tomas"),
    Pair("pending leave", "toy", ("ilse", "kara"), act=leaves("tomas")),
    Pair(
        "person or code answering an ask",
        "toy",
        ("kara",),
        change=toy_declined,
        act=toy_asked,
        names=toy_held_names,
        unseated="ilse",
        swapped="tomas",
        host="olaf",
        wakes=2,
        seam=True,
        apart=True,
    ),
    Pair(
        "person or code answering an incident",
        "toy",
        ("kara",),
        change=toy_defiant,
        act=toy_incident,
        unseated="ilse",
        swapped="tomas",
        host="olaf",
        wakes=1,
        seam=True,
        apart=True,
    ),
    Pair("hidden law", "toy", ("kara", "tomas"), change=toy_law),
    Pair(
        "written order awaiting the close",
        "toy",
        ("ilse", "tomas"),
        act=committed_lever("kara", "march", {"force": "norra_levy", "to": "norra_hills"}),
        names=own_held("set_watch", {"zone": "gulf", "order": "guard"}),
        wakes=0,
    ),
    Pair(
        "enemy piece", "salt", ("oren_vale",), change=salt_piece, names=lambda s: SALT_PIECE_NAMES
    ),
    Pair("other economy", "salt", ("oren_vale",), change=salt_economy),
    Pair("other groups", "salt", ("oren_vale",), change=salt_groups),
    Pair("sealed vote", "salt", ("oren_vale",), change=conference_now, act=salt_vote),
    Pair(
        "private agreement",
        "salt",
        ("oren_vale",),
        change=salt_agreement,
        names=salt_agreement_names,
    ),
    Pair("other aims", "salt", ("oren_vale",), change=salt_aims),
    Pair(
        "report not arrived",
        "salt",
        ("oren_vale",),
        act=unarrived("oren_vale"),
        names=unarrived_names,
        wakes=0,
    ),
    Pair("person or code", "salt", ("oren_vale",), unseated="general_aske"),
    Pair("pending leave", "salt", ("oren_vale",), act=leaves("general_aske")),
    Pair(
        "written order awaiting the close",
        "salt",
        ("oren_vale",),
        act=committed_lever(
            "general_aske", "move_force", {"force": "ostrel_levy", "to": "harrow_pass"}
        ),
        names=lambda s: (Probe("withdraw", {"held_id": 1}),),
        wakes=0,
    ),
)
"""Every kind the contract names, in each world that can build it."""

NOT_BUILT: dict[str, str] = {
    "toy-sealed-vote": "the toy world has no conference or vote a seat files",
    "toy-private-agreement": "the toy world's two nations are at war and there is no third",
    "salt-held-order-and-ask": "Salt Strait declares no locks, so no order is ever held",
    "salt-person-or-code-answering-an-ask": "Salt Strait declares no locks, so nothing is asked",
    "salt-hidden-law": "Salt Strait declares no law",
    "salt-ask-to-a-person-with-no-seat": "Salt Strait declares no locks, so nothing is asked",
    "salt-person-or-code-answering-an-incident": (
        "Salt Strait declares no locks, so no order is held or sent anyway"
    ),
    "salt-report-author": "Salt Strait seats one player besides the host, so no second author",
}
"""Kinds that cannot be built in a world through its public entry points, left for the
security review."""


@contextmanager
def twins(pair: Pair, cluster: Cluster, tmp: Path) -> Iterator[tuple[Side, Side]]:
    """The two games of ``pair``, each in a scratch database dropped afterwards."""
    dbs: list[PgDb] = []
    sides: list[Side] = []
    try:
        for hidden in (False, True):
            dbs.append(cluster.fresh())
            sides.append(build(pair, dbs[-1], tmp / ("b" if hidden else "a"), hidden))
        yield sides[0], sides[1]
    finally:
        for s in sides:
            s.web.close()
        for db in dbs:
            cluster.drop(db)
