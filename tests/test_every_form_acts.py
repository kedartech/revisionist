"""Every form does something (EFD).

Every form on every playable card, in Autumn 1941 and in Salt Strait, is filed on the
opened game and the world is walked forward day by day to the season's end. A form acts
when, against the same walk with no order filed, it changes a quantity, a piece, a
relationship, a fact, a war, a holder, a pool, a group, an agreement, a contest, a report,
an agent or a goal. Each order is filed as a seat files it (``realism_tick.form_filing``)
and enacted as it would be after its pipeline. An order a lock holds is filed held; the
lock is opened from state (the superior's own order setting the posture, or the law it
waits on put in force, in both walks), and the order counts once it lands through the
engine's own landing (``realism_tick._unlocked``). A held order that never lands in the
walk is reported, not counted. Forms that change nothing are listed in ``INERT`` as strict
expected-to-fail cases, each naming the fix that owns it; each mark goes when its fix
merges.
"""

import json
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, EventId, OrderId, SeatId, derived_id
from revisionist.core.realism import economy, holders, locks
from revisionist.core.realism.card import ParamKind, ParamSpec, superiors
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import (
    ON_DAY,
    ON_ORDER,
    apply_changes,
    movement,
    resolver_for,
    votes,
)
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC as _PUBLIC
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.wake_report import inert_forms
from tests.locked_orders_script import Ids, autumn_1941

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
SALT = "salt-strait-realism"
WATCHED = (
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
)
"""The parts of the state an enacted form may change; the documents and news a filing
writes about itself are not among them."""

HORIZON_DAYS = 100
WARM_DAYS = 35
CHECK_EVERY = 5
OWNER = "rules lane: the second run's forms that change nothing act"
INERT: dict[tuple[str, str], str] = {key: OWNER for key in inert_forms()}
"""Each form that changes nothing, and the fix that owns it; the strict cases below hold
this list equal to what the walk finds, so a form fixed must leave it."""


def _entity(key: str) -> EntityId:
    return EntityId(object_id(CAMPAIGN, "entity", key))


def _seat(key: str) -> SeatId:
    return SeatId(derived_id(CAMPAIGN, "seat", _entity(key)))


class _World:
    """One world opened for play, and the walk of it with nothing filed."""

    def __init__(self, world: WorldFile, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.world = world
        ids = Ids(CAMPAIGN)
        ids.install(monkeypatch)
        store = MemoryStore()
        store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
        names = load_state(store, CAMPAIGN).entities
        self.people = sorted({c.person for c in world.cards if c.playable and c.levers})
        for person in self.people:
            with ids.drawn_by("claim:" + person):
                session_zero.claim(store, CAMPAIGN, _seat(person), names[_entity(person)].name)
        with ids.drawn_by("open"):
            realism_tick.open_play(store, CAMPAIGN)
        self._controls: dict[str | None, dict[int, dict[str, str]]] = {}
        self.unlanded: list[tuple[str, str, dict[str, str]]] = []
        opened = load_state(store, CAMPAIGN)
        self.start = self._day_by_day(opened, WARM_DAYS)
        self.last = self.start
        self._walk(self.start, None, None)

    def forms(self) -> list[tuple[str, str]]:
        return [(c.person, lv.name) for c in self.world.cards if c.playable for lv in c.levers]

    def params(self, person: str, lever: str) -> tuple[ParamSpec, ...]:
        (lv,) = [
            lv
            for c in self.world.cards
            if c.person == person and c.playable
            for lv in c.levers
            if lv.name == lever
        ]
        return lv.params

    def acts(self, person: str, lever: str) -> list[str] | None:
        """The parts that differ from the control for the first case that changes
        something; ``[]`` when every case that can be filed changes nothing; None when no
        case can be filed, or every case is held and never lands."""
        filed = False
        for given in _cases(self.params(person, lever)):
            try:
                order = realism_tick.draft_order(self.start, _seat(person), lever, given)
            except ValueError:
                continue
            walked = self.enacted(order)
            if walked is None:
                self.unlanded.append((person, lever, given))
                continue
            filed = True
            if walked:
                return walked
        return [] if filed else None

    def enacted(self, order: Order) -> list[str] | None:
        """The parts the order changes against the control, filed as its seat files it;
        None when a lock holds it and it never lands in the walk."""
        start, key = self.start, None
        landing, _ = realism_tick.form_filing(start, order.issuer, order)
        lock = locks.lock_for(start, order.issuer, order)
        if lock is not None:
            assert lock.row is not None and lock.row.when is not None
            key = lock.row.key
            start = _opened(start, order, lock.row.when)
            assert locks.lock_for(start, order.issuer, order) is None
            if key not in self._controls:
                self._controls[key] = {}
                self._walk(start, None, key)
        state = _fold(start, [p for p, _ in landing])
        if lock is None:
            return self._walk(_landed(state, order.order_id), order, key)
        assert order.order_id in state.held
        diff = self._walk(state, order, key)
        return None if order.order_id in self.last.held else diff

    @staticmethod
    def _day_by_day(
        state: State, days: int, seen: Callable[[int, State], bool] | None = None
    ) -> State:
        """``state`` walked ``days`` days, each day as the walk takes it; a held order
        whose lock has opened lands as the engine lands it, and is enacted."""
        first = state.in_world_date
        assert first is not None
        for n in range(1, days + 1):
            day = first + timedelta(days=n)
            state = _fold(state, [ev.DateAdvanced(to=day)])
            for on_day in ON_DAY.values():
                state = _fold(state, apply_changes(state, on_day(state, day)))
            for step in (movement.walk, holders.walk, economy.walk):
                state = _fold(state, step(state, day))
            unlocked = realism_tick._unlocked(state, day)
            state = _fold(state, unlocked)
            for p in unlocked:
                if isinstance(p, ev.OrderDrafted):
                    state = _landed(state, p.order.order_id)
            if seen is not None and seen(n, state):
                break
        return state

    def _walk(self, state: State, order: Order | None, key: str | None) -> list[str]:
        """Walk ``state`` to the season's end with ``order`` filed on day one; with none,
        record the control's checkpoints under ``key``. Returns the parts that first
        differ."""
        control = self._controls.setdefault(key, {})
        diff: list[str] = []

        def check(n: int, now: State) -> bool:
            if n % CHECK_EVERY and n != HORIZON_DAYS:
                return False
            seen = _digest(now)
            if order is None:
                control[n] = seen
                return False
            diff.extend(k for k in WATCHED if seen[k] != control[n][k])
            return bool(diff)

        self.last = self._day_by_day(state, HORIZON_DAYS, check)
        return diff


def _landed(state: State, order_id: Any) -> State:
    """``state`` with the order enacted, as after its pipeline, and what it changes."""
    state = _fold(state, [ev.OrderSettled(order_id=order_id, status=OrderStatus.ENACTED)])
    order = state.orders[order_id]
    return _fold(state, apply_changes(state, ON_ORDER[resolver_for(state, order)](state, order)))


def _opened(state: State, order: Order, when: locks.Condition) -> State:
    """``state`` with the lock that holds ``order`` opened from state: the law it waits on
    put in force for the issuer's nation, or the posture set by the superior's own form."""
    day = state.in_world_date
    assert day is not None
    if isinstance(when, locks.LawNotInForce):
        bills = [
            b for b, m in votes.HISTORICAL.items() if when.clause in {c.subject for c in m.clauses}
        ]
        changes = [votes.put(state, f"{b}_passed", 1, day) for b in bills]
        return _fold(state, apply_changes(state, tuple(c for c in changes if c is not None)))
    assert when.form is not None
    issuer = state.seats[order.issuer].embodies
    above = set(superiors(state.cards, issuer))
    (seat,) = [
        s
        for s, held in state.seats.items()
        if held.embodies in above
        and any(lv.name == when.form for lv in state.cards[held.embodies].levers)
    ]
    (lever,) = [lv for lv in state.cards[state.seats[seat].embodies].levers if lv.name == when.form]
    given = {p.name: _value(p) for p in lever.params} | {
        k: str(v) for k, v in (when.where | when.posture).items()
    }
    setter = realism_tick.draft_order(state, seat, when.form, given)
    return _landed(_fold(state, [ev.OrderDrafted(order=setter)]), setter.order_id)


def _fold(state: State, payloads: list[ev.Payload]) -> State:
    batch = [
        ev.Event(
            event_id=EventId(derived_id(CAMPAIGN, "efd", state.last_seq + 1 + n)),
            campaign_id=CAMPAIGN,
            seq=state.last_seq + 1 + n,
            tick=state.tick,
            scope=_PUBLIC,
            payload=p,
            versions=cmp.versions(),
        )
        for n, p in enumerate(payloads)
    ]
    return replay(batch, initial=state) if batch else state


def _digest(state: State) -> dict[str, str]:
    dumped = state.model_dump(mode="json")
    return {k: json.dumps(dumped.get(k), sort_keys=True) for k in WATCHED}


def _value(p: ParamSpec) -> str:
    if p.kind is ParamKind.ENUM:
        return p.choices[0]
    if p.kind is ParamKind.INT:
        assert p.lo is not None and p.hi is not None
        return str((p.lo + p.hi) // 2)
    return "a message"


def _cases(params: tuple[ParamSpec, ...]) -> Iterator[dict[str, str]]:
    """The form with each parameter at its first value, then with each one of an
    enum's other values in turn (a naval order is tried in every zone)."""
    base = {p.name: _value(p) for p in params}
    yield base
    for p in params:
        if p.kind is ParamKind.ENUM:
            for choice in p.choices[1:]:
                yield {**base, p.name: choice}


_WORLDS: dict[str, _World] = {}
_ACTS: dict[tuple[str, str, str], list[str] | None] = {}


def _open(name: str, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> _World:
    if name not in _WORLDS:
        world = autumn_1941(tmp) if name == "1941" else cmp.load_world(cmp.world_path(SALT))
        _WORLDS[name] = _World(world, tmp, monkeypatch)
    return _WORLDS[name]


def _acts(
    form: tuple[str, str, str], tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> list[str] | None:
    """What the walk finds for one form, walked once per test session."""
    if form not in _ACTS:
        name, person, lever = form
        _ACTS[form] = _open(name, tmp, monkeypatch).acts(person, lever)
    return _ACTS[form]


def _forms() -> list[tuple[str, str, str]]:
    out = []
    for name, path in (("1941", cmp.world_path("autumn-1941")), ("salt", cmp.world_path(SALT))):
        world = cmp.load_world(path)
        out += [(name, c.person, lv.name) for c in world.cards if c.playable for lv in c.levers]
    return out


def _case(form: tuple[str, str, str]) -> Any:
    marks = []
    if (form[1], form[2]) in INERT:
        marks.append(pytest.mark.xfail(strict=True, reason=INERT[(form[1], form[2])]))
    return pytest.param(*form, marks=marks, id=".".join(form))


@pytest.mark.parametrize(("name", "person", "lever"), [_case(f) for f in _forms()])
def test_every_form_changes_something(
    name: str, person: str, lever: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Filed, the form changes a number, a piece, a holder, a pool, a group, an
    agreement, a contest, a report or regard within the walk; the failing ones are named
    in ``INERT``, each as a strict expected failure."""
    changed = _acts((name, person, lever), tmp_path, monkeypatch)
    assert changed, f"{person}.{lever} changes nothing (no case of it could be filed: {changed})"


def test_the_list_of_inert_forms_names_real_forms() -> None:
    real = {(p, lv) for _, p, lv in _forms()}
    assert set(INERT) <= real
    assert len(inert_forms()) == len(set(inert_forms()))


def test_the_count_the_wake_report_prints_is_the_count_the_walk_finds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file the wake report counts names exactly the forms the walk finds changing
    nothing, once each."""
    from revisionist.engine import wake_report

    walked = {
        (p, lv) for name, p, lv in _forms() if not _acts((name, p, lv), tmp_path, monkeypatch)
    }
    assert set(wake_report.inert_forms()) == walked
    assert len(wake_report.inert_forms()) == len(walked)


def test_a_held_form_is_filed_held_and_lands_once_its_lock_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """King's escort into the war zone is held while the revision is not in force; with
    the law put in force it lands through the engine's landing, as an ordinary order under
    its landed id, and is enacted; the filed order never enters a pipeline itself."""
    world = _open("1941", tmp_path, monkeypatch)
    given = {"order": "escort_convoys", "zone": "war_zone"}
    order = realism_tick.draft_order(world.start, _seat("king"), "fleet_naval_order", given)
    assert locks.lock_for(world.start, order.issuer, order) is not None
    assert world.enacted(order) is not None
    end = world.last
    assert order.order_id not in end.orders
    assert order.order_id not in end.held
    landed = OrderId(derived_id(CAMPAIGN, "landed", order.order_id))
    assert end.orders[landed].status is OrderStatus.ENACTED
    assert end.orders[landed].params == order.params


def test_a_held_form_that_never_lands_is_reported_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A held order whose lock the walk cannot open counts as not filed, and is named."""
    world = _open("1941", tmp_path, monkeypatch)
    given = {"order": "escort_convoys", "zone": "war_zone"}
    order = realism_tick.draft_order(world.start, _seat("king"), "fleet_naval_order", given)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(realism_tick, "_unlocked", lambda state, day: [])
        assert world.enacted(order) is None
