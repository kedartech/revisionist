"""A written order gets the same result as its form (WRT).

For every form in Autumn 1941 and in Salt Strait, ``tests/written_order_cases.py`` gives
one written sentence and the reading it stands for. Each case plays twin games from one
opened world, with written orders on in the test's copy: in one the seat files the form;
in the other it writes the sentence, the aide reads it as the table says and the seat
signs it. Both games are then played to the
season's close, every seat committing each wake, and the outcome digests (what the world
holds at the close) must be equal.

No live model is called. The ticks run as the live game's do, with a canned transport:
it answers the aide's reading and the estimator's ruling from the table, fails every other
call as a model that is down, and counts each request per case. The prose is the template
prose, and the runner's leak report and wake notices are left out of the ticks: they check
and tell, and change nothing the world holds.
"""

import contextlib
import functools
import json
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from revisionist.core import events as ev
from revisionist.core import fold
from revisionist.core.ids import CampaignId, EntityId, FeatureId, SeatId, derived_id
from revisionist.core.ontology import Phase
from revisionist.core.realism import locks
from revisionist.core.realism.pipeline import OrderStatus, StepAction
from revisionist.core.state import Rule, State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import orders_reader, realism_tick, session_zero, wake, wake_open
from revisionist.engine.llm import Reply, Request, TransportError
from revisionist.engine.pg_store import PostgresEventStore
from revisionist.engine.prose import TemplateProseWriter
from revisionist.engine.realism_tick import run_realism_tick
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import held as held_orders
from revisionist.engine.web import server
from revisionist.engine.web.battles_api import DECIDED, NOT_YOURS_FORCE
from revisionist.engine.web.server import MODEL_DOWN, model_down
from tests.locked_orders_script import Ids, table
from tests.written_order_cases import (
    CASES,
    ENTITY_FIELDS,
    FEATURE_FIELDS,
    FIXES,
    PAST_THE_CAP,
    PLANTED_FACT,
    PLANTED_FIGURE,
    RULED_BY,
    RULINGS,
    Case,
    detail,
    give,
    move,
    naval,
    war,
)

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
WORLDS = {"1941": "autumn-1941", "salt": "salt-strait-realism"}
WAKES = 60
"""More wakes than either season takes."""
T0 = datetime(2030, 1, 1, tzinfo=UTC)
OUTCOME = (
    "quantities",
    "features",
    "relationships",
    "meters",
    "clocks",
    "facts",
    "contests",
    "wars",
    "holders",
    "economy",
    "groups",
    "agreements",
    "intelligence",
    "reports",
    "battles",
    "captures",
    "goals",
    "flags",
)
"""What the world holds: the parts of the state the outcome digest is taken over. The
orders, the papers and the news a filing writes about itself are records, not outcomes."""


def entity(key: str) -> EntityId:
    return EntityId(object_id(CAMPAIGN, "entity", key))


def feature(key: str) -> FeatureId:
    return FeatureId(object_id(CAMPAIGN, "feature", key))


def seat(key: str) -> SeatId:
    return SeatId(derived_id(CAMPAIGN, "seat", entity(key)))


# --- the canned transport ---------------------------------------------------------------


@dataclass
class Canned:
    """The aide's reading and the estimator's ruling from the table; every other call
    fails as a model that is down. ``asked`` counts each request by call class, and each
    failure handed back as ``<class>:failed``."""

    asks: list[dict[str, Any]] = field(default_factory=list)
    ruling: list[dict[str, Any]] = field(default_factory=list)
    war: dict[str, Any] | None = None
    treaty: dict[str, Any] | None = None
    vote: dict[str, Any] | None = None
    asked: Counter[str] = field(default_factory=Counter)

    def call(self, request: Request) -> Reply:
        self.asked[request.call_class] += 1
        if request.call_class == orders_reader.CALL_CLASS:
            out: dict[str, Any] = {"asks": self.asks, "reason": ""}
            out |= {"war": self.war} if self.war is not None else {}
            out |= {"treaty": self.treaty} if self.treaty is not None else {}
            out |= {"vote": self.vote} if self.vote is not None else {}
            return Reply(out, request.model, 0, 0, 0, 0.0)
        if request.call_class == "estimator":
            out = {"effects": self.ruling, "reason": "As written.", "rationale": ""}
            return Reply(out, request.model, 0, 0, 0, 0.0)
        self.asked[f"{request.call_class}:failed"] += 1
        raise TransportError("canned: no model plays this game")


# --- the games --------------------------------------------------------------------------


class Kept(MemoryStore):
    """A memory store that keeps its latest snapshot as the state itself, unserialised."""

    def save_snapshot(self, state: State) -> None:
        self._kept = state

    def latest_snapshot(self, campaign_id: CampaignId) -> State | None:
        return getattr(self, "_kept", None)


@dataclass
class Opened:
    """One world compiled, every playable seat claimed and play opened: the log both
    twins start from."""

    world: WorldFile
    events: list[ev.Event]
    people: list[str]


def written_orders_on(world: WorldFile) -> WorldFile:
    """The world with written orders on, in the test's copy only: every shipped world has
    the rule off until the live reader is checked (WAR rule 2)."""
    if Rule.WRITTEN_ORDERS in world.rules:
        return world
    return world.model_copy(
        update={"rules": type(world.rules)((*world.rules, Rule.WRITTEN_ORDERS))}
    )


@functools.cache
def table_of(name: str, person: str | None) -> tuple[str, ...]:
    """The people seated in the game ``person`` plays (``locked_orders_script.table``)."""
    return table(cmp.load_world(cmp.world_path(WORLDS[name])), person)


def _open(name: str, without: tuple[Rule, ...], people: tuple[str, ...]) -> Opened:
    world = written_orders_on(cmp.load_world(cmp.world_path(WORLDS[name])))
    if without:
        kept = tuple(r for r in world.rules if r not in without)
        world = world.model_copy(update={"rules": type(world.rules)(kept)})
    ids = Ids(CAMPAIGN)
    with pytest.MonkeyPatch.context() as mp:
        ids.install(mp)
        store = Kept()
        store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
        names = load_state(store, CAMPAIGN).entities
        for person in people:
            with ids.drawn_by("claim:" + person):
                session_zero.claim(store, CAMPAIGN, seat(person), names[entity(person)].name)
        with ids.drawn_by("open"):
            realism_tick.open_play(store, CAMPAIGN)
    return Opened(world, list(store.read(CAMPAIGN)), list(people))


_OPENED: dict[tuple[str, tuple[Rule, ...], tuple[str, ...]], Opened] = {}


def opened(name: str, without: tuple[Rule, ...] = (), who: str | None = None) -> Opened:
    """The world opened with the people ``who`` plays beside (``table``), with the rules in
    ``without`` off in the test's copy."""
    people = table_of(name, who)
    if (name, without, people) not in _OPENED:
        _OPENED[name, without, people] = _open(name, without, people)
    return _OPENED[name, without, people]


def _no_hash(state: State) -> str:
    """The tick's integrity hash, left out: it checks the log against the fold, and
    taking it over the whole 1941 state is most of a tick's time."""
    return ""


class Game:
    """One twin: the opened log in its own store, played by every seat committing."""

    def __init__(self, base: Opened, mp: pytest.MonkeyPatch, transport: Canned) -> None:
        self.base = base
        self.store = Kept()
        self.store.append_all(base.events)
        self.ids = Ids(CAMPAIGN)
        self.ids.install(mp)
        for module in (fold, realism_tick):
            mp.setattr(module, "state_hash", _no_hash)
        self.transport = transport
        self.now = T0
        self.tick()  # opens the first wake

    @property
    def state(self) -> State:
        return load_state(self.store, CAMPAIGN)

    def tick(self) -> None:
        """One tick as ``runner.play_tick`` runs it for a realism game, with template
        prose and the canned estimator; the offers are made with no model, and the leak
        report and the wake notices are left out."""
        state = self.state
        if state.wake is not None and not state.wake.closed:
            wake.close_wake(self.store, CAMPAIGN, self.now, None)
        done = run_realism_tick(
            self.store,
            CAMPAIGN,
            versions=cmp.versions(),
            prose=TemplateProseWriter(),
            estimator=self.transport,
        )
        if done.stopped_after is None:
            opened = wake.open_wake(self.store, CAMPAIGN, self.now)
            wake_open.before_offers(self.store, CAMPAIGN, opened)
            wake.offer_all(self.store, CAMPAIGN, None)

    def form(self, case: Case) -> str:
        with self.ids.drawn_by(f"order:{case.name}"):
            try:
                realism_tick.file_order(
                    self.store, CAMPAIGN, seat(case.person), case.lever, case.params
                )
            except ValueError as exc:
                return f"form refused: {exc}"
        return ""

    def read(self, case: Case) -> orders_reader.Reading:
        """The aide's reading of the case's sentence, as the table gives it."""
        state = self.state
        asks = [_ask(case.sentence, effect) for effect in case.reading if "war" not in effect]
        self.transport.asks = asks
        self.transport.ruling = [_keyed(e) for e in case.ruling]
        declared = [e["war"] for e in case.reading if "war" in e]
        self.transport.war = {"target": entity(declared[0])} if declared else None
        to = _addressee(state, case)
        return orders_reader.read_order(
            state, seat(case.person), to, "", case.sentence, self.transport
        )

    def written(self, case: Case) -> str:
        reading = self.read(case)
        if not reading.asks:
            return f"written unreadable: {reading.shown['reason']}"
        with self.ids.drawn_by(f"order:{case.name}"):
            done = orders_reader.file_order(self.store, CAMPAIGN, seat(case.person), reading)
        return f"written refused: {done['reply']}" if done["refused"] else ""

    def play(self) -> State:
        for _ in range(WAKES):
            state = self.state
            if state.phase is not Phase.PLAY:
                break
            if state.wake is not None and not state.wake.closed:
                self.now = state.wake.deadline
                for person in self.base.people:
                    with self.ids.drawn_by(f"commit:{person}"):
                        wake.commit(self.store, CAMPAIGN, seat(person), self.now)
            self.tick()
        return self.state


def _keyed(effect: dict[str, Any]) -> dict[str, Any]:
    out = dict(effect)
    for k, v in effect.items():
        if k in ENTITY_FIELDS and isinstance(v, str):
            out[k] = entity(v)
        elif k in FEATURE_FIELDS and isinstance(v, str):
            out[k] = feature(v)
    return out


def _ask(sentence: str, effect: dict[str, Any]) -> dict[str, Any]:
    if set(effect) == {"target"}:
        return {"ask": sentence, "target": entity(effect["target"])}
    plain = {k: v for k, v in effect.items() if k != "detail"}
    out = {"ask": sentence, "effect": _keyed(plain)}
    return out | ({"detail": effect["detail"]} if "detail" in effect else {})


def _addressee(state: State, case: Case) -> str:
    """The person the order is written to: the executor of the card's first authority
    that covers the reading's first effect, else the target of an approach, else the
    first person within the seat's reach."""
    from revisionist.core.project import project
    from revisionist.core.realism.reach import channels_to

    card = state.cards[entity(case.person)]
    first = case.reading[0]
    kind = first.get("kind")
    for domain in card.authority:
        if (
            kind is not None
            and domain.executor is not None
            and kind in {k.value for k in domain.effects}
        ):
            return state.entities[domain.executor].name
    target = state.entities.get(entity(first["target"])) if set(first) == {"target"} else None
    if target is not None and target.kind.value == "person":
        if channels_to(state, card.person, target.entity_id):
            return target.name
    view = project(state, seat(case.person))
    reach = sorted(
        e.name
        for e in view.entities.values()
        if e.entity_id != card.person
        and e.kind.value == "person"
        and channels_to(state, card.person, e.entity_id)
    )
    return reach[0] if reach else ""


def outcome(state: State) -> dict[str, str]:
    dumped = state.model_dump(mode="json")
    return {k: json.dumps(dumped.get(k), sort_keys=True) for k in OUTCOME}


# --- the twins --------------------------------------------------------------------------


@dataclass
class Twins:
    cases: tuple[Case, ...]
    notes: list[str]
    form: dict[str, str]
    written: dict[str, str]
    asked: dict[str, int]

    def differences(self) -> list[str]:
        return self.notes + [k for k in OUTCOME if self.form[k] != self.written[k]]


def play_twins(*cases: Case) -> Twins:
    """The cases' forms filed in one game and their sentences signed in a twin, both on
    the first wake, and both played to the season's close."""
    base = opened(cases[0].world, who=cases[0].person)
    notes: list[str] = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cmp, "load_world", functools.cache(cmp.load_world))
        by_form = Game(base, mp, Canned())
        notes += [f"{c.name}: {n}" for c in cases if (n := by_form.form(c))]
        form_end = by_form.play()
        canned = Canned()
        in_writing = Game(base, mp, canned)
        notes += [f"{c.name}: {n}" for c in cases if (n := in_writing.written(c))]
        written_end = in_writing.play()
    return Twins(cases, notes, outcome(form_end), outcome(written_end), dict(canned.asked))


def _pieces(case: Case) -> set[str]:
    return {v for k, v in case.params.items() if k in ("force", "piece")}


@functools.cache
def _with_above(name: str, person: str) -> frozenset[str]:
    """``person`` and the people above him on his card's principals who sit at his own
    table: those any table his case is played at must seat."""
    cards = {c.person: c for c in cmp.load_world(cmp.world_path(WORLDS[name])).cards}
    above: set[str] = set()
    stack = [person]
    while stack:
        for up in cards[stack.pop()].principals:
            if up in cards and up not in above and up != person:
                above.add(up)
                stack.append(up)
    return frozenset({person, *above}) & set(table_of(name, person))


def seated(case: Case, first: Case) -> bool:
    """Whether the table ``first`` is played at seats ``case``'s person and those above him."""
    return _with_above(case.world, case.person) <= set(table_of(first.world, first.person))


def batches(cases: Sequence[Case]) -> list[tuple[Case, ...]]:
    """The cases played together: one world, one table and one fix to a batch, and at most
    one case per person and per piece, so no order in a batch replaces or redirects another.
    A batch's digests are equal when each of its orders lands as its form does; it costs one
    twin pair where a case alone costs one each. A batch is played at its first case's table,
    which seats every case's person and those above him; the cases of people the world's
    first table does not seat are placed first, so the batches opened at their tables take
    the other cases too."""
    out: list[list[Case]] = []
    for case in sorted(cases, key=lambda c: c.person in table_of(c.world, None)):
        home = next(
            (
                b
                for b in out
                if (b[0].world, b[0].fix) == (case.world, case.fix)
                and seated(case, b[0])
                and all(c.person != case.person and not _pieces(c) & _pieces(case) for c in b)
            ),
            None,
        )
        if home is None:
            out.append([case])
        else:
            home.append(case)
    return [tuple(b) for b in out]


def _batch(batch: tuple[Case, ...]) -> Any:
    fix = batch[0].fix
    marks = [pytest.mark.xfail(strict=True, reason=fix)] if fix else []
    name = f"{batch[0].world}:" + "+".join(c.name.split(".", 1)[1] for c in batch)
    return pytest.param(batch, marks=marks, id=name)


def _forms() -> Iterator[tuple[str, str, str]]:
    for name, world in WORLDS.items():
        w = cmp.load_world(cmp.world_path(world))
        for c in w.cards:
            if c.playable:
                for lv in c.levers:
                    yield name, c.person, lv.name


def test_the_table_has_a_sentence_for_every_form_and_no_other() -> None:
    assert {(c.world, c.person, c.lever) for c in CASES} == set(_forms())
    assert len({c.name for c in CASES}) == len(CASES)
    assert set(FIXES) <= {c.name for c in CASES}


def test_the_batches_hold_every_case_once_and_share_no_person_or_piece() -> None:
    played = batches(CASES)
    assert sorted(c.name for b in played for c in b) == sorted(c.name for c in CASES)
    for batch in played:
        assert len({(c.world, c.fix) for c in batch}) == 1
        assert all(seated(c, batch[0]) for c in batch)
        assert len({c.person for c in batch}) == len(batch)
        pieces = [p for c in batch for p in _pieces(c)]
        assert len(set(pieces)) == len(pieces)
    assert len(played) < len(CASES) * 11 / 20


@pytest.mark.parametrize("batch", [_batch(b) for b in batches(CASES)])
def test_a_written_order_gets_the_same_outcome_as_its_form(batch: tuple[Case, ...]) -> None:
    twins = play_twins(*batch)
    assert not twins.differences(), twins.differences()


@pytest.mark.parametrize("case", [c for c in CASES if c.world == "salt"][:2], ids=lambda c: c.name)
def test_each_case_asks_the_aide_once_and_the_estimator_once_per_approach(case: Case) -> None:
    """The canned transport counts every request: the aide reads the sentence once, the
    estimator rules once on each ask with no typed effect, and nothing is retried."""
    twins = play_twins(case)
    approaches = sum(1 for e in case.reading if set(e) == {"target"})
    if any(": written " in n for n in twins.notes):
        assert twins.asked.get(orders_reader.CALL_CLASS) == 1
        assert twins.asked.get("estimator", 0) == 0
    else:
        assert twins.asked.get(orders_reader.CALL_CLASS) == 1
        assert twins.asked.get("estimator", 0) == approaches
    assert not any(k.startswith(("aide:", "estimator:")) for k in twins.asked)


class Down(Canned):
    """The aide's model fails with ``why``."""

    def __init__(self, why: str) -> None:
        super().__init__()
        self.why = why

    def call(self, request: Request) -> Reply:
        self.asked[request.call_class] += 1
        raise TransportError(self.why)


@pytest.mark.parametrize(
    ("why", "told"),
    [
        ("openrouter: day quota used up, usage limit until 00:00 UTC", "at its usage limit"),
        ("connection refused", MODEL_DOWN),
    ],
    ids=["quota", "transport"],
)
def test_a_reader_that_fails_files_nothing_and_says_so(
    why: str, told: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A quota used up and a failed transport each file nothing, ask once with no retry
    and no fallback reading, and the seat is told the model could not be reached."""
    case = next(c for c in CASES if c.world == "salt" and c.lever == "declare_war")
    down = Down(why)
    game = Game(opened("salt"), monkeypatch, down)
    down.asked.clear()  # the opening tick's prose and offers fail as the model is down
    before = game.store.last_seq(CAMPAIGN)
    state = game.state
    try:
        reading = orders_reader.read_order(
            state, seat(case.person), _addressee(state, case), "", case.sentence, down
        )
    except TransportError as exc:
        said, signable = model_down(exc), 0
    else:
        said, signable = reading.shown["reason"] or "", len(reading.asks)
    assert game.store.last_seq(CAMPAIGN) == before
    assert dict(down.asked) == {orders_reader.CALL_CLASS: 1}
    assert not signable, f"a failed reading offers {signable} asks to sign: {said}"
    assert told in said


def test_a_lend_lease_finding_records_the_receipt_its_written_allocation_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The form's finding, once enacted, records Britain's receipt from the President,
    private to his seat, as the written allocation it stands for does. The President
    holds the finding's last step and passes it."""
    case = next(c for c in CASES if c.lever == "lend_lease_finding")
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    game = Game(opened(case.world, who=case.person), monkeypatch, Canned())
    assert game.form(case) == ""
    (finding,) = (o for o in game.state.orders.values() if o.lever == case.lever)
    for _ in range(6):
        if game.state.orders[finding.order_id].status is OrderStatus.MOVING:
            with game.ids.drawn_by("step"), contextlib.suppress(ValueError):
                realism_tick.take_step(
                    game.store, CAMPAIGN, seat("roosevelt"), finding.order_id, StepAction.PASS, {}
                )
        game.now = game.state.wake.deadline if game.state.wake else game.now
        for person in game.base.people:
            with game.ids.drawn_by(f"commit:{person}"):
                wake.commit(game.store, CAMPAIGN, seat(person), game.now)
        game.tick()
    assert game.state.orders[finding.order_id].status is OrderStatus.ENACTED
    receipts = [
        f
        for f in game.state.facts.values()
        if f.predicate == "received_from"
        and f.subject == entity("uk")
        and f.obj == entity("roosevelt")
    ]
    assert len(receipts) == 1
    assert receipts[0].scope.known_by == frozenset({seat("roosevelt")})


# --- the two locked orders --------------------------------------------------------------

LOCKED = (
    naval("king", "fleet_naval_order", "escort_convoys", "war_zone"),
    naval("king", "fleet_naval_order", "shoot_on_sight", "iceland_route"),
)
"""Admiral King's escort into the war zone, held while the Neutrality revision is not in
force (Congress decides), and his shoot on sight on the Iceland route, held until the
President sets it there by his own naval order."""
OPENS_ICELAND = naval("roosevelt", "naval_order", "shoot_on_sight", "iceland_route")
"""The President's form that opens the Iceland lock from state."""


def _held(game: Game) -> list[tuple[Any, ...]]:
    """Each held order of Admiral King's: its filing day, decider and held words."""
    state = game.state
    return [
        (h.filed, h.decider, locks.held_words(state, h))
        for h in state.held.values()
        if h.issuer == seat("king")
    ]


@pytest.mark.parametrize("case", LOCKED, ids=lambda c: c.params["zone"])
def test_a_locked_form_is_held_and_names_its_decider(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    game = Game(opened(case.world, who=case.person), monkeypatch, Canned())
    assert game.form(case) == ""
    (held,) = _held(game)
    assert held[0] == game.state.in_world_date


@pytest.mark.parametrize("case", LOCKED, ids=lambda c: c.params["zone"])
def test_a_locked_written_order_is_held_as_its_form_is(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same decider named in the same held words, on the same filing day."""
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    by_form = Game(opened(case.world, who=case.person), monkeypatch, Canned())
    in_writing = Game(opened(case.world, who=case.person), monkeypatch, Canned())
    assert by_form.form(case) == in_writing.written(case) == ""
    assert _held(in_writing) == _held(by_form)


def _landed(game: Game) -> list[Any]:
    return [
        e.payload.on
        for e in game.store.read(CAMPAIGN)
        if isinstance(e.payload, ev.HeldOrderEnded)
        and e.payload.issuer == seat("king")
        and e.payload.end is locks.HeldEnd.LANDED
    ]


def test_a_locked_written_order_lands_the_day_its_form_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The President's naval order opens the Iceland lock from state: both twins land
    Admiral King's order on one day, and the outcomes are equal."""
    case = LOCKED[1]
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    games = []
    for file in ("form", "written"):
        game = Game(opened(case.world, who=case.person), monkeypatch, Canned())
        assert game.form(OPENS_ICELAND) == ""
        assert getattr(game, file)(case) == ""
        game.play()
        games.append(game)
    by_form, in_writing = games
    assert len(_landed(by_form)) == 1
    assert _landed(in_writing) == _landed(by_form)
    assert outcome(in_writing.state) == outcome(by_form.state)


@pytest.mark.parametrize("case", LOCKED, ids=lambda c: c.params["zone"])
def test_with_locks_off_a_locked_order_goes_through_as_an_ordinary_one(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    # defiance needs locks, so it goes with them (the 1941 world has it on since the offices item)
    base = opened(case.world, without=(Rule.LOCKS, Rule.DEFIANCE), who=case.person)
    by_form = Game(base, monkeypatch, Canned())
    in_writing = Game(base, monkeypatch, Canned())
    assert by_form.form(case) == in_writing.written(case) == ""
    assert _held(by_form) == _held(in_writing) == []
    for game in (by_form, in_writing):
        kings = [o.lever for o in game.state.orders.values() if o.issuer == seat("king")]
        assert kings == [case.lever]


# --- orders the rules refuse ------------------------------------------------------------

NO_GROUND = Case(
    "1941",
    "churchill",
    "move_army",
    {"force": "home_forces", "to": "liverpool"},
    "Send the Home Forces to Liverpool.",
    ({"kind": "move_force", "force": "home_forces", "to": "liverpool"},),
)
"""An army sent to a port in a sea zone: no path ends there for it."""


def _refused(monkeypatch: pytest.MonkeyPatch) -> tuple[Game, str, Game, str]:
    base = opened(NO_GROUND.world)
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    by_form = Game(base, monkeypatch, Canned())
    form_told = by_form.form(NO_GROUND)
    in_writing = Game(base, monkeypatch, Canned())
    return by_form, form_told, in_writing, in_writing.written(NO_GROUND)


def test_the_rules_refuse_the_form_and_file_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    game = Game(opened(NO_GROUND.world), monkeypatch, Canned())
    before = game.store.last_seq(CAMPAIGN)
    assert game.form(NO_GROUND) == (
        "form refused: Home Forces cannot stand in The Western Approaches. The nearest area"
        " it could be sent to is Scotland and Ulster."
    )
    assert game.store.last_seq(CAMPAIGN) == before


def test_a_written_move_the_rules_refuse_is_refused_in_the_forms_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    by_form, form_told, in_writing, written_told = _refused(monkeypatch)
    assert written_told == "written refused: " + form_told.removeprefix("form refused: ")
    assert outcome(by_form.state) == outcome(in_writing.state)


# --- the written path takes every check its form takes ----------------------------------


@pytest.mark.parametrize("case", LOCKED, ids=lambda c: c.params["zone"])
def test_with_written_orders_off_a_locked_written_order_is_held_as_its_form_is(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain engagement stays readable with the rule off, and the lock holds it there
    as it holds the form."""
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    base = opened(case.world, without=(Rule.WRITTEN_ORDERS,))
    by_form = Game(base, monkeypatch, Canned())
    in_writing = Game(base, monkeypatch, Canned())
    assert by_form.form(case) == in_writing.written(case) == ""
    assert _held(in_writing) == _held(by_form) != []


def test_a_written_order_kept_for_the_next_wake_is_held_as_its_form_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signed after the seat committed, the order is kept and filed at the next wake, and
    the lock holds it then as it holds the form."""
    case = LOCKED[0]
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    by_form = Game(opened(case.world), monkeypatch, Canned())
    assert by_form.form(case) == ""
    in_writing = Game(opened(case.world), monkeypatch, Canned())
    reading = in_writing.read(case)
    kept, _ = server._held_args(
        cast(PostgresEventStore, in_writing.store),
        in_writing.state,
        seat(case.person),
        "file",
        {},
        reading,
    )
    kept = json.loads(json.dumps(kept))
    with in_writing.ids.drawn_by(f"order:{case.name}"):
        assert (
            held_orders.file_one(in_writing.store, CAMPAIGN, seat(case.person), "file", kept)
            is None
        )
    assert _held(in_writing) == _held(by_form) != []


DETACH = next(c for c in CASES if c.person == "king" and c.lever == "detach_fleet")


def test_a_detail_never_changes_what_the_effect_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """A detail names only what the effect cannot hold; one that contradicts the effect
    matches no form, and the reading is not offered to sign."""
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    game = Game(opened("1941"), monkeypatch, Canned())
    wrong = detail(move("us_atlantic_fleet", "reykjavik"), strength="2", to="norfolk")
    reading = game.read(replace(DETACH, reading=(wrong,)))
    assert not reading.asks
    assert reading.shown["reason"] == orders_reader.TO_THE_FORM


def test_a_written_detachment_is_refused_as_its_form_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """A strength the form does not take is refused at filing in the form's words."""
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    too_many = {**DETACH.params, "strength": "9"}
    by_form = Game(opened("1941"), monkeypatch, Canned())
    told = by_form.form(replace(DETACH, params=too_many))
    reading = (detail(move("us_atlantic_fleet", "reykjavik"), strength="9"),)
    in_writing = Game(opened("1941"), monkeypatch, Canned())
    written_told = in_writing.written(replace(DETACH, reading=reading))
    assert told.startswith("form refused: ")
    assert written_told == "written refused: " + told.removeprefix("form refused: ")


def test_a_written_declaration_needs_a_declaration_on_the_desk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seat whose card has no form that declares war on the nation cannot declare it in
    writing either."""
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    game = Game(opened("1941"), monkeypatch, Canned())
    cable = next(c for c in CASES if c.lever == "cable_to_churchill")
    reading = game.read(replace(cable, reading=(war("germany"),)))
    assert not reading.asks
    assert reading.shown["reason"] == orders_reader.TO_THE_FORM


# --- battle decisions and contingencies, in the toy war of ``tests/test_web_battles.py`` --


def _toy(tmp: Path) -> MemoryStore:
    """The coast's battle open, wake 0 open, written orders on; Ilse commands Norra's levy in
    it and the Second Levy at home."""
    from tests import test_adjacency_moves as adj
    from tests.test_battle_decisions import opened as battle_opened
    from tests.test_battle_decisions import second_levy
    from tests.test_battle_decisions_land import army
    from tests.test_web_battles import store_of

    def written(w: dict[str, Any]) -> None:
        w["rules"] = [*w["rules"], Rule.WRITTEN_ORDERS.value]

    tmp.mkdir(exist_ok=True)
    return store_of(battle_opened(tmp, adj.levers, second_levy, army, written))


def _toy_piece(store: MemoryStore, key: str) -> FeatureId:
    from tests.test_adjacency_moves import piece
    from tests.test_territory_model import CAMPAIGN as TOY

    return piece(load_state(store, TOY), key).feature_id


def _toy_form(store: MemoryStore, action: str, **body: Any) -> str:
    from tests.test_web_battles import ILSE, file

    try:
        file(store, ILSE, action, **body)
    except ValueError as exc:
        return f"form refused: {exc}"
    return ""


def _toy_written(store: MemoryStore, *effects: dict[str, Any]) -> str:
    from tests.test_territory_model import CAMPAIGN as TOY
    from tests.test_web_battles import ILSE

    sentence = "The levy is to act as I say."
    transport = Canned(asks=[{"ask": sentence, "effect": e} for e in effects])
    state = load_state(store, TOY)
    reading = orders_reader.read_order(state, ILSE, "Aide of ilse", "", sentence, transport)
    if not reading.asks:
        return f"written unreadable: {reading.shown['reason']}"
    done = orders_reader.file_order(store, TOY, ILSE, reading)
    return f"written refused: {done['reply']}" if done["refused"] else ""


def _toy_routed(store: MemoryStore) -> list[Any]:
    from tests.test_web_battles import ILSE, routed

    return routed(store, ILSE)


def _decision(store: MemoryStore, posture: str, force: str = "norra_levy", to: str = "") -> Any:
    effect: dict[str, Any] = {
        "kind": "move_force",
        "force": _toy_piece(store, force),
        "posture": posture,
    }
    return effect | ({"to": _toy_entity(to)} if to else {})


def _toy_entity(key: str) -> EntityId:
    from tests.test_adjacency_moves import entity as toy_entity

    return toy_entity(key)


def _contingency(store: MemoryStore, force: str, **contingency: Any) -> dict[str, Any]:
    return {
        "kind": "engagement",
        "force": _toy_piece(store, force),
        "zone": "wherever it stands",
        "rule": "shoot_on_sight",
        "contingency": contingency,
    }


TOY_DECISIONS = [
    ("press", "attack", ""),
    ("hold", "hold", ""),
    ("withdraw", "withdraw", ""),
    ("withdraw", "withdraw", "norra_hills"),
]


@pytest.mark.parametrize(
    ("decision", "posture", "to"),
    TOY_DECISIONS,
    ids=[f"{d}{t and '-' + t}" for d, _, t in TOY_DECISIONS],
)
def test_a_written_battle_decision_files_what_its_form_files(
    tmp_path: Path, decision: str, posture: str, to: str
) -> None:
    by_form, in_writing = _toy(tmp_path / "form"), _toy(tmp_path / "written")
    body = {"area": "sudland_coast", "decision": decision} | ({"to": to} if to else {})
    assert _toy_form(by_form, "battle", **body) == ""
    effect = _decision(in_writing, posture)
    if to:
        effect["to"] = _toy_entity(to)
    assert _toy_written(in_writing, effect) == ""
    assert _toy_routed(in_writing) == _toy_routed(by_form) != []


def test_a_second_written_decision_in_a_wake_is_refused_as_its_form_is(tmp_path: Path) -> None:
    by_form, in_writing = _toy(tmp_path / "form"), _toy(tmp_path / "written")
    assert _toy_form(by_form, "battle", area="sudland_coast", decision="press") == ""
    told = _toy_form(by_form, "battle", area="sudland_coast", decision="hold")
    assert _toy_written(in_writing, _decision(in_writing, "attack")) == ""
    written_told = _toy_written(in_writing, _decision(in_writing, "hold"))
    assert told == f"form refused: {DECIDED}"
    assert written_told == f"written unreadable: {DECIDED}"
    assert _toy_routed(in_writing) == _toy_routed(by_form)


def test_two_decisions_for_one_battle_in_one_written_order_are_refused(tmp_path: Path) -> None:
    in_writing = _toy(tmp_path)
    both = (_decision(in_writing, "attack"), _decision(in_writing, "hold"))
    assert _toy_written(in_writing, *both) == f"written unreadable: {DECIDED}"
    assert _toy_routed(in_writing) == []


@pytest.mark.parametrize(
    ("force", "want"),
    [("second_levy", "NOT_IN"), ("sudland_levy", "NOT_YOURS_FORCE")],
    ids=["in-no-battle", "the-enemys"],
)
def test_a_written_decision_the_form_cannot_give_is_refused_in_the_forms_words(
    tmp_path: Path, force: str, want: str
) -> None:
    from revisionist.engine.web import battles_api

    in_writing = _toy(tmp_path)
    told = _toy_written(in_writing, _decision(in_writing, "attack", force))
    assert told == f"written unreadable: {getattr(battles_api, want)}"
    assert _toy_routed(in_writing) == []


def test_a_written_contingency_files_what_its_form_files(tmp_path: Path) -> None:
    """The form keeps the force's rule and names its own zone; a reading that names
    others files the form's."""
    by_form, in_writing = _toy(tmp_path / "form"), _toy(tmp_path / "written")
    body = {"force": "norra_levy", "kind": "withdraw_below", "below": 2}
    assert _toy_form(by_form, "contingency", **body) == ""
    effect = _contingency(in_writing, "norra_levy", kind="withdraw_below", below=2)
    assert _toy_written(in_writing, effect) == ""
    assert _toy_routed(in_writing) == _toy_routed(by_form) != []


def test_a_written_contingency_for_a_force_not_the_seats_is_refused_in_the_forms_words(
    tmp_path: Path,
) -> None:
    by_form, in_writing = _toy(tmp_path / "form"), _toy(tmp_path / "written")
    told = _toy_form(by_form, "contingency", force="sudland_levy", kind="hold")
    effect = _contingency(in_writing, "sudland_levy", kind="hold")
    written_told = _toy_written(in_writing, effect)
    assert told == f"form refused: {NOT_YOURS_FORCE}"
    assert written_told == f"written unreadable: {NOT_YOURS_FORCE}"
    assert _toy_routed(in_writing) == []


# --- evacuation and embargo, in the toy worlds of their own tests -------------------------


def _with_aides(w: dict[str, Any]) -> None:
    """An aide in each leader's inner circle, to write the order to."""
    for who in ("ilse", "tomas"):
        w["entities"].append({"key": f"{who}_aide", "kind": "person", "name": f"Aide of {who}"})
    for card in w["cards"]:
        if card["person"] in ("ilse", "tomas"):
            aide = {"person": f"{card['person']}_aide", "channel": "courier"}
            card["inner_circle"] = [*card.get("inner_circle", []), aide]


def _written_on(w: dict[str, Any]) -> None:
    w["rules"] = [*w["rules"], Rule.WRITTEN_ORDERS.value]


def _economy(tmp: Path, form: str) -> MemoryStore:
    """The toy world carrying ``form`` (``trade`` or ``evacuate``) on each leader's card,
    in play with wake 0 open, written orders on."""
    from tests import test_evacuation, test_trade_orders

    tmp.mkdir(exist_ok=True)
    made = test_trade_orders.game if form == "trade" else test_evacuation.game
    g = made(tmp, _with_aides, _written_on)
    opened_at = datetime(2026, 11, 19, 12, tzinfo=UTC)
    g.add([ev.WakeOpened(wake=0, deadline=opened_at + timedelta(days=1), opened_at=opened_at)])
    store = MemoryStore()
    store.append_all(g.log)
    return store


def _toy_seat(key: str) -> SeatId:
    from tests.test_adjacency_moves import seat as toy_seat

    return toy_seat(key)


def _economy_form(store: MemoryStore, lever: str, params: dict[str, str]) -> str:
    from tests.test_territory_model import CAMPAIGN as TOY

    try:
        realism_tick.file_order(store, TOY, _toy_seat("ilse"), lever, params)
    except ValueError as exc:
        return f"form refused: {exc}"
    return ""


def _economy_written(store: MemoryStore, params: dict[str, str]) -> str:
    from tests.test_territory_model import CAMPAIGN as TOY

    sentence = "See to it, as the form would have it."
    transport = Canned(asks=[{"ask": sentence, "detail": params}])
    state = load_state(store, TOY)
    reading = orders_reader.read_order(
        state, _toy_seat("ilse"), "Aide of ilse", "", sentence, transport
    )
    if not reading.asks:
        return f"written unreadable: {reading.shown['reason']}"
    done = orders_reader.file_order(store, TOY, _toy_seat("ilse"), reading)
    return f"written refused: {done['reply']}" if done["refused"] else ""


def _economy_orders(store: MemoryStore) -> list[tuple[Any, ...]]:
    from tests.test_territory_model import CAMPAIGN as TOY

    state = load_state(store, TOY)
    return sorted(
        (o.lever, sorted(o.params.items()), o.status.value, o.filed)
        for o in state.orders.values()
        if o.issuer == _toy_seat("ilse")
    )


ECONOMY = [
    ("trade", {"line": "norra_pitch", "action": "embargo"}),
    ("trade", {"line": "norra_pitch", "action": "restore"}),
    ("evacuate", {"territory": "norra_plain", "rear": "norra_hills"}),
]


@pytest.mark.parametrize(
    ("lever", "params"), ECONOMY, ids=[f"{lv}-{'-'.join(p.values())}" for lv, p in ECONOMY]
)
def test_a_written_evacuation_or_embargo_files_what_its_form_files(
    tmp_path: Path, lever: str, params: dict[str, str]
) -> None:
    by_form, in_writing = _economy(tmp_path / "form", lever), _economy(tmp_path / "written", lever)
    assert _economy_form(by_form, lever, params) == ""
    assert _economy_written(in_writing, params) == ""
    assert _economy_orders(in_writing) == _economy_orders(by_form) != []


@pytest.mark.parametrize(
    ("lever", "params"),
    [
        ("trade", {"line": "norra_pitch", "action": "blockade"}),
        ("evacuate", {"territory": "norra_plain", "rear": "atlantis"}),
    ],
    ids=["no-such-action", "no-such-rear"],
)
def test_a_written_evacuation_or_embargo_the_form_refuses_is_refused_in_its_words(
    tmp_path: Path, lever: str, params: dict[str, str]
) -> None:
    by_form, in_writing = _economy(tmp_path / "form", lever), _economy(tmp_path / "written", lever)
    told = _economy_form(by_form, lever, params)
    assert told.startswith("form refused: ")
    assert _economy_written(in_writing, params) == told.replace("form", "written", 1)
    assert _economy_orders(in_writing) == _economy_orders(by_form) == []


AID = next(c for c in CASES if c.lever == "lend_lease_finding")


@pytest.mark.parametrize("share", ["150", "101"])
def test_a_written_allocation_past_its_cap_is_refused_as_its_form_is(
    monkeypatch: pytest.MonkeyPatch, share: str
) -> None:
    """The form takes a share from 0 to 100 and refuses any other in its own words; the
    written allocation it stands for is held to the same cap, never filed around it."""
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    by_form = Game(opened(AID.world, who=AID.person), monkeypatch, Canned())
    told = by_form.form(replace(AID, params={**AID.params, "share_pct": share}))
    reading = (detail(give("uk", "lend_lease", int(share), "percent"), route="hx_route"),)
    in_writing = Game(opened(AID.world, who=AID.person), monkeypatch, Canned())
    written_told = in_writing.written(replace(AID, reading=reading))
    assert told == f"form refused: share_pct: {share} is outside 0..100"
    assert written_told == "written refused: " + told.removeprefix("form refused: ")
    assert [o for o in in_writing.state.orders.values() if o.issuer == seat(AID.person)] == []
    assert not in_writing.state.routed


# --- offers with clauses, in the toy world of the treaty reader's tests -------------------


OFFER_WORDING = "Norra will keep out of the isle, and neither side will attack the other."


def _offers(tmp: Path) -> MemoryStore:
    """The agreements toy world with written orders and the clause reader on."""
    from tests.test_agreements import game as agreements_game

    tmp.mkdir(exist_ok=True)
    rules = ("holders", "agreements", "written_orders", "clause_reader")
    store = MemoryStore()
    store.append_all(agreements_game(tmp, rules=rules).log)
    return store


def _toy_clauses(*keys: str) -> list[dict[str, Any]]:
    from tests.test_agreements import NORRA, OSTMARK, SUDLAND

    known: dict[str, dict[str, Any]] = {
        "keep_out": {"type": "keep_out", "binds": NORRA, "area": _toy_entity("isle")},
        "no_attack": {"type": "no_attack", "binds": SUDLAND, "nation": NORRA},
        "no_such_area": {"type": "keep_out", "binds": NORRA, "area": "nowhere"},
        "foreign": {"type": "no_war", "binds": OSTMARK, "nation": NORRA},
        "vote": {"type": "vote", "binds": NORRA, "text": "t", "present": True},
    }
    return [dict(known[k]) for k in keys]


def _offer_parties() -> list[str]:
    from tests.test_agreements import NORRA, SUDLAND

    return [NORRA, SUDLAND]


def _offer_filed(store: MemoryStore, reading: orders_reader.Reading, how: str) -> str:
    from tests.test_agreements import ILSE
    from tests.test_territory_model import CAMPAIGN as TOY

    done = orders_reader.file_order(store, TOY, ILSE, reading)
    return f"{how} refused: {done['reply']}" if done["refused"] else ""


def _offer_form(store: MemoryStore, clauses: list[dict[str, Any]]) -> tuple[str, Any]:
    from revisionist.engine.web import agreements_api
    from tests.test_agreements import ILSE
    from tests.test_territory_model import CAMPAIGN as TOY

    body = {"parties": _offer_parties(), "wording": OFFER_WORDING, "clauses": clauses}
    try:
        reading = agreements_api.offer_reading(load_state(store, TOY), ILSE, body)
    except ValueError as exc:
        return f"form refused: {exc}", None
    return _offer_filed(store, reading, "form"), reading


def _offer_written(store: MemoryStore, clauses: list[dict[str, Any]]) -> tuple[str, Any]:
    from tests.test_agreements import ILSE
    from tests.test_territory_model import CAMPAIGN as TOY

    transport = Canned(treaty={"parties": _offer_parties(), "clauses": clauses})
    state = load_state(store, TOY)
    reading = orders_reader.read_order(state, ILSE, "Brand", "", OFFER_WORDING, transport)
    if not reading.asks:
        return f"written unreadable: {reading.shown['reason']}", None
    return _offer_filed(store, reading, "written"), reading


def _offered(store: MemoryStore) -> list[Any]:
    from tests.test_territory_model import CAMPAIGN as TOY

    state = load_state(store, TOY)
    return [(o.filed, [p.model_dump(mode="json") for p in o.parts]) for o in state.routed.values()]


OFFERS = [("keep_out", "no_attack"), ("keep_out",), ()]


@pytest.mark.parametrize("clauses", OFFERS, ids=["two-clauses", "one-clause", "wording-only"])
def test_a_written_offer_with_clauses_files_what_its_form_files(
    tmp_path: Path, clauses: tuple[str, ...]
) -> None:
    by_form, in_writing = _offers(tmp_path / "form"), _offers(tmp_path / "written")
    told, form = _offer_form(by_form, _toy_clauses(*clauses))
    written_told, written = _offer_written(in_writing, _toy_clauses(*clauses))
    assert (told, written_told) == ("", "")
    assert written.asks[0].effect == form.asks[0].effect
    assert (written.version, written.terms) == (form.version, form.terms)
    assert _offered(in_writing) == _offered(by_form) != []


REFUSED_OFFERS = [
    ("keep_out", "no_such_area"),
    ("foreign",),
    ("keep_out", "vote"),
    ("keep_out",) * 9,
]


@pytest.mark.parametrize(
    "clauses", REFUSED_OFFERS, ids=["no-such-area", "foreign", "vote", "nine-clauses"]
)
def test_a_written_offer_the_form_refuses_is_refused_whole_in_its_words(
    tmp_path: Path, clauses: tuple[str, ...]
) -> None:
    """The form refuses the whole offer when one clause cannot be offered; the written
    offer is refused in the same words, not filed with that clause left out."""
    by_form, in_writing = _offers(tmp_path / "form"), _offers(tmp_path / "written")
    told, _ = _offer_form(by_form, _toy_clauses(*clauses))
    written_told, _ = _offer_written(in_writing, _toy_clauses(*clauses))
    assert told.startswith("form refused: ")
    assert written_told == told.replace("form refused", "written unreadable", 1)
    assert _offered(in_writing) == _offered(by_form) == []


# --- the conference vote, in the toy world of the conference's tests ----------------------


def _conference(tmp: Path) -> MemoryStore:
    """The conference toy world, written orders on, with Ilse's charter called."""
    from tests.test_conference import Game as Conference
    from tests.test_conference import world as conference_world

    tmp.mkdir(exist_ok=True)
    rules = ("holders", "agreements", "conference", "written_orders")
    g = Conference(conference_world(tmp, rules=rules), "ilse", "tomas", "olaf")
    g.open()
    g.call()
    store = MemoryStore()
    store.append_all(g.log)
    return store


def _vote_form(store: MemoryStore, who: SeatId, body: dict[str, str]) -> str:
    from revisionist.engine.web import conferences_api
    from tests.test_territory_model import CAMPAIGN as TOY

    try:
        args, _ = conferences_api.vote_args(load_state(store, TOY), who, body)
        conferences_api.vote(store, TOY, who, args)
    except ValueError as exc:
        return f"form refused: {exc}"
    return ""


def _vote_written(store: MemoryStore, who: SeatId, body: dict[str, str]) -> str:
    from tests.test_territory_model import CAMPAIGN as TOY

    state = load_state(store, TOY)
    words = "We vote on the conference, as the form would have it."
    reading = orders_reader.read_order(state, who, "", "", words, Canned(vote=body))
    if reading.vote is None:
        return f"written unreadable: {reading.shown['reason']}"
    done = orders_reader.file_order(store, TOY, who, reading)
    return f"written refused: {done['reply']}" if done["refused"] else ""


def _votes(store: MemoryStore) -> dict[str, dict[str, tuple[str, int]]]:
    from tests.test_territory_model import CAMPAIGN as TOY

    votes = load_state(store, TOY).conferences.votes
    return {k: {s: (v.vote.value, v.wake) for s, v in by.items()} for k, by in votes.items()}


def _voter(key: str) -> SeatId:
    from tests.test_conference import ILSE, TOMAS

    return {"ilse": ILSE, "tomas": TOMAS}[key]


def _conference_key(name: str) -> str:
    from tests.test_conference import CHARTER, NAME

    return {"charter-key": CHARTER, "charter-name": NAME}.get(name, name)


VOTES = [
    ("tomas", "charter-key", "against"),
    ("ilse", "charter-name", "for"),
    ("tomas", "charter-key", "ABSTAIN"),
]


@pytest.mark.parametrize(
    ("who", "conference", "vote"), VOTES, ids=["by-key", "by-the-callers-name", "in-capitals"]
)
def test_a_written_vote_seals_what_its_form_seals(
    tmp_path: Path, who: str, conference: str, vote: str
) -> None:
    by_form, in_writing = _conference(tmp_path / "form"), _conference(tmp_path / "written")
    body = {"conference": _conference_key(conference), "vote": vote}
    assert _vote_form(by_form, _voter(who), body) == ""
    assert _vote_written(in_writing, _voter(who), body) == ""
    assert _votes(in_writing) == _votes(by_form) != {}


REFUSED_VOTES = [("tomas", "charter-key", "maybe"), ("tomas", "nowhere", "for")]


@pytest.mark.parametrize(
    ("who", "conference", "vote"), REFUSED_VOTES, ids=["no-such-vote", "no-such-conference"]
)
def test_a_written_vote_the_form_refuses_is_refused_in_its_words(
    tmp_path: Path, who: str, conference: str, vote: str
) -> None:
    by_form, in_writing = _conference(tmp_path / "form"), _conference(tmp_path / "written")
    body = {"conference": _conference_key(conference), "vote": vote}
    told = _vote_form(by_form, _voter(who), body)
    assert told.startswith("form refused: ")
    assert _vote_written(in_writing, _voter(who), body) == told.replace(
        "form refused", "written unreadable", 1
    )
    assert _votes(in_writing) == _votes(by_form) == {}


# --- canned rulings on a written order no form covers -------------------------------------


RULED = next(c for c in CASES if c.lever == RULED_BY)
_RULING_ENTITIES = frozenset({"of", "toward", "counterparty"})


def _planted() -> dict[str, str]:
    return {
        PLANTED_FACT: derived_id(CAMPAIGN, "fact", PLANTED_FACT),
        PLANTED_FIGURE: derived_id(CAMPAIGN, "quantity", PLANTED_FIGURE),
    }


def _plant(game: Game) -> None:
    """A fact and a figure the estimator may name, as a cast or an event would make them."""
    from revisionist.core.ids import FactId, QuantityId
    from revisionist.core.ontology import Fact
    from revisionist.core.realism.quantity import Quantity
    from revisionist.core.visibility import PUBLIC

    state = game.state
    ids = _planted()
    fact = Fact(
        fact_id=FactId(ids[PLANTED_FACT]),
        subject=entity("usa"),
        predicate="funds",
        obj=entity("uk"),
        scope=PUBLIC,
    )
    figure = Quantity(
        quantity_id=QuantityId(ids[PLANTED_FIGURE]),
        name="Aircraft output",
        value=1000,
        unit="aircraft",
        as_of=state.in_world_date,
        estimable=True,
    )
    landing: realism_tick.Landing = [
        (ev.FactAsserted(fact=fact), PUBLIC),
        (ev.QuantitySet(quantity=figure), PUBLIC),
    ]
    realism_tick._append_all(game.store, state, landing, seat(RULED.person))


def _ruling(effect: dict[str, Any]) -> dict[str, Any]:
    out = _keyed(effect)
    for k, v in effect.items():
        if k in _RULING_ENTITIES:
            out[k] = entity(v)
        elif k in {"fact", "quantity"}:
            out[k] = _planted()[v]
    return out


def _ruled(mp: pytest.MonkeyPatch, ruling: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the estimator's canned ``ruling`` lands on the written approach, once ruled."""
    mp.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    game = Game(opened(RULED.world, who=RULED.person), mp, Canned())
    _plant(game)
    assert game.written(RULED) == ""
    (order,) = [o for o in game.state.routed.values() if o.issuer == seat(RULED.person)]
    assert order.parts[0].effect is None
    game.transport.ruling = [_ruling(e) for e in ruling]
    game.tick()
    part = game.state.routed[order.order_id].parts[0]
    assert part.was_estimated
    return [
        {"kind": e.kind} | e.model_dump(mode="json", exclude_defaults=True) for e in part.estimated
    ]


@pytest.mark.parametrize("kind", sorted(RULINGS))
def test_a_canned_ruling_of_each_kind_lands_on_a_written_order_no_form_covers(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    ruling = _ruling(RULINGS[kind])
    landed = _ruled(monkeypatch, [RULINGS[kind]])
    assert landed == [{k: v for k, v in ruling.items() if v is not None} | {"kind": kind}]


@pytest.mark.parametrize("cap", sorted(PAST_THE_CAP))
def test_a_canned_ruling_past_a_cap_is_cut_to_the_cap(
    monkeypatch: pytest.MonkeyPatch, cap: str
) -> None:
    ruled, kept = PAST_THE_CAP[cap]
    landed = _ruled(monkeypatch, list(ruled))
    assert landed == [
        {k: v for k, v in _ruling(e).items() if v is not None} | {"kind": e["kind"]} for e in kept
    ]


@pytest.mark.parametrize("share", ["150", "101"])
def test_a_written_allocation_past_its_cap_with_no_route_named_files_nothing(
    monkeypatch: pytest.MonkeyPatch, share: str
) -> None:
    """With no route named, the written allocation still stands for the form, which holds
    the share to 0..100: it is not filed past the cap by another path."""
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    in_writing = Game(opened(AID.world, who=AID.person), monkeypatch, Canned())
    reading = (give("uk", "lend_lease", int(share), "percent"),)
    told = in_writing.written(replace(AID, reading=reading))
    assert told == f"written unreadable: share_pct: {share} is outside 0..100"
    assert [o for o in in_writing.state.orders.values() if o.issuer == seat(AID.person)] == []
    assert not in_writing.state.routed
