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

import functools
import json
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core import fold
from revisionist.core.ids import CampaignId, EntityId, FeatureId, SeatId, derived_id
from revisionist.core.ontology import Phase
from revisionist.core.state import Rule, State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import orders_reader, realism_tick, session_zero, wake, wake_open
from revisionist.engine.llm import Reply, Request, TransportError
from revisionist.engine.prose import TemplateProseWriter
from revisionist.engine.realism_tick import run_realism_tick
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web.server import MODEL_DOWN, model_down
from tests.locked_orders_script import Ids
from tests.written_order_cases import CASES, ENTITY_FIELDS, FEATURE_FIELDS, FIXES, Case

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
    asked: Counter[str] = field(default_factory=Counter)

    def call(self, request: Request) -> Reply:
        self.asked[request.call_class] += 1
        if request.call_class == orders_reader.CALL_CLASS:
            return Reply({"asks": self.asks, "reason": ""}, request.model, 0, 0, 0, 0.0)
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


def _open(name: str) -> Opened:
    world = written_orders_on(cmp.load_world(cmp.world_path(WORLDS[name])))
    ids = Ids(CAMPAIGN)
    with pytest.MonkeyPatch.context() as mp:
        ids.install(mp)
        store = Kept()
        store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
        names = load_state(store, CAMPAIGN).entities
        people = sorted({c.person for c in world.cards if c.playable and c.levers})
        for person in people:
            with ids.drawn_by("claim:" + person):
                session_zero.claim(store, CAMPAIGN, seat(person), names[entity(person)].name)
        with ids.drawn_by("open"):
            realism_tick.open_play(store, CAMPAIGN)
    return Opened(world, list(store.read(CAMPAIGN)), people)


_OPENED: dict[str, Opened] = {}


def opened(name: str) -> Opened:
    if name not in _OPENED:
        _OPENED[name] = _open(name)
    return _OPENED[name]


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

    def written(self, case: Case) -> str:
        state = self.state
        asks = [_ask(case.sentence, effect) for effect in case.reading]
        self.transport.asks = asks
        self.transport.ruling = [_keyed(e) for e in case.ruling]
        to = _addressee(state, case)
        reading = orders_reader.read_order(
            state, seat(case.person), to, "", case.sentence, self.transport
        )
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
    return {"ask": sentence, "effect": _keyed(effect)}


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
    base = opened(cases[0].world)
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


def batches(cases: Sequence[Case]) -> list[tuple[Case, ...]]:
    """The cases played together: one world and one fix to a batch, and at most one case
    per person and per piece, so no order in a batch replaces or redirects another. A
    batch's digests are equal when each of its orders lands as its form does; it costs one
    twin pair where a case alone costs one each."""
    out: list[list[Case]] = []
    for case in cases:
        home = next(
            (
                b
                for b in out
                if (b[0].world, b[0].fix) == (case.world, case.fix)
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
        assert len({c.person for c in batch}) == len(batch)
        pieces = [p for c in batch for p in _pieces(c)]
        assert len(set(pieces)) == len(pieces)
    assert len(played) < len(CASES) / 2


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


READER_FALLBACK = (
    "core lane fix item: a failed reading of an order to another nation's person tells the"
    " seat the model is down, and offers no agreement reading in its place"
)


class Down(Canned):
    """The aide's model fails with ``why``."""

    def __init__(self, why: str) -> None:
        super().__init__()
        self.why = why

    def call(self, request: Request) -> Reply:
        self.asked[request.call_class] += 1
        raise TransportError(self.why)


@pytest.mark.xfail(strict=True, reason=READER_FALLBACK)
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


REFUSED_AT_FILING = (
    "core lane fix item: a written order is refused at filing by the check its form takes"
)


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


@pytest.mark.xfail(strict=True, reason=REFUSED_AT_FILING)
def test_a_written_move_the_rules_refuse_is_refused_in_the_forms_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    by_form, form_told, in_writing, written_told = _refused(monkeypatch)
    assert written_told == "written refused: " + form_told.removeprefix("form refused: ")
    assert outcome(by_form.state) == outcome(in_writing.state)
