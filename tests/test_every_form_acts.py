"""Every form does something (EFD).

Every form on every playable card, in Autumn 1941 and in Salt Strait, is enacted on the
opened game and the world is walked forward day by day to the season's end. A form acts
when, against the same walk with no order filed, it changes a quantity, a piece, a
relationship, a fact, a war, a holder, a pool, a group, an agreement, a contest, a report,
an agent or a goal. The orders are enacted as they would be after their pipeline (a held
order counts as acting once its lock opens and it lands, so a lock is not asked here).
Forms that change nothing are listed in ``INERT`` as strict expected-to-fail cases, each
naming the fix that owns it; each mark goes when its fix merges.
"""

import json
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, EventId, SeatId, derived_id
from revisionist.core.realism import economy, holders
from revisionist.core.realism.card import ParamKind, ParamSpec
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.resolvers import (
    ON_DAY,
    ON_ORDER,
    apply_changes,
    movement,
    resolver_for,
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
OWNER = "core lane: the fix item queued with stage 5 (SSP's guard lines, `until EFD`)"
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
        self._seen: dict[int, dict[str, str]] = {}
        opened = load_state(store, CAMPAIGN)
        self.start = self._day_by_day(opened, WARM_DAYS)
        self._walk(self.start, None)

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
        case can be filed."""
        filed = False
        for given in _cases(self.params(person, lever)):
            try:
                order = realism_tick.draft_order(self.start, _seat(person), lever, given)
            except ValueError:
                continue
            filed = True
            if diff := self._walk(self.start, order):
                return diff
        return [] if filed else None

    @staticmethod
    def _day_by_day(
        state: State, days: int, seen: Callable[[int, State], bool] | None = None
    ) -> State:
        """``state`` walked ``days`` days, each day as the walk takes it."""
        first = state.in_world_date
        assert first is not None
        for n in range(1, days + 1):
            day = first + timedelta(days=n)
            state = _fold(state, [ev.DateAdvanced(to=day)])
            for on_day in ON_DAY.values():
                state = _fold(state, apply_changes(state, on_day(state, day)))
            for step in (movement.walk, holders.walk, economy.walk):
                state = _fold(state, step(state, day))
            if seen is not None and seen(n, state):
                break
        return state

    def _walk(self, state: State, order: Any) -> list[str]:
        """Walk ``state`` to the season's end with ``order`` enacted on day one; with none,
        record the control's checkpoints. Returns the parts that first differ."""
        if order is not None:
            state = _fold(
                state,
                [
                    ev.OrderDrafted(order=order),
                    ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
                ],
            )
            order = state.orders[order.order_id]
            state = _fold(
                state, apply_changes(state, ON_ORDER[resolver_for(state, order)](state, order))
            )
        diff: list[str] = []

        def check(n: int, now: State) -> bool:
            if n % CHECK_EVERY and n != HORIZON_DAYS:
                return False
            seen = _digest(now)
            if order is None:
                self._seen[n] = seen
                return False
            diff.extend(k for k in WATCHED if seen[k] != self._seen[n][k])
            return bool(diff)

        self._day_by_day(state, HORIZON_DAYS, check)
        return diff
        return diff


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


def _open(name: str, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> _World:
    if name not in _WORLDS:
        world = autumn_1941(tmp) if name == "1941" else cmp.load_world(cmp.world_path(SALT))
        _WORLDS[name] = _World(world, tmp, monkeypatch)
    return _WORLDS[name]


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
    """Enacted, the form changes a number, a piece, a holder, a pool, a group, an
    agreement, a contest, a report or regard within the walk; the failing ones are named
    in ``INERT``, each as a strict expected failure."""
    changed = _open(name, tmp_path, monkeypatch).acts(person, lever)
    assert changed, f"{person}.{lever} changes nothing (no case of it could be filed: {changed})"


def test_the_list_of_inert_forms_names_real_forms() -> None:
    real = {(p, lv) for _, p, lv in _forms()}
    assert set(INERT) <= real
    assert len(inert_forms()) == len(set(inert_forms()))


def test_the_count_the_wake_report_prints_is_the_count_the_walk_finds() -> None:
    from revisionist.engine import wake_report

    ours = {(p, lv) for p, lv in INERT}
    assert wake_report.inert_forms() == tuple(INERT)
    assert len(ours) == len(wake_report.inert_forms())
