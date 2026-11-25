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
from datetime import UTC, datetime
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
from revisionist.engine.web.server import MODEL_DOWN, model_down
from tests.locked_orders_script import Ids, table
from tests.written_order_cases import (
    CASES,
    ENTITY_FIELDS,
    FEATURE_FIELDS,
    FIXES,
    Case,
    detail,
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
    asked: Counter[str] = field(default_factory=Counter)

    def call(self, request: Request) -> Reply:
        self.asked[request.call_class] += 1
        if request.call_class == orders_reader.CALL_CLASS:
            out: dict[str, Any] = {"asks": self.asks, "reason": ""}
            out |= {"war": self.war} if self.war is not None else {}
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
