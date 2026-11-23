"""A receipt is written once, whichever path files it.

A Lend-Lease finding filed by form and the written allocation it stands for name one
receipt fact: the recipient's, from the President, of the share, on the day it lands
(``land/allocate.py``). When both land on one day the form's receipt is filed only if
the game does not hold it already, as the written path's is, so the fold never sees the
id twice and the day completes. Where the form files it is the written path's rule: in
every game, a stored one too.
"""

import functools
from datetime import date, timedelta

import pytest

from revisionist.core.ids import EntityId
from revisionist.core.ontology import Fact
from revisionist.core.realism.land import allocate
from revisionist.core.realism.pipeline import Order, OrderStatus, StepAction
from revisionist.core.realism.pipelines import waiting_on_human
from revisionist.core.realism.resolvers import production
from revisionist.core.state import Rule
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, wake
from tests.test_realism_resolvers import POINTS, Rig, finding, rig, stored
from tests.test_written_order_parity import CAMPAIGN, Canned, Game, entity, opened, seat
from tests.written_order_cases import CASES

# --- the same day, played ---------------------------------------------------------------

WRITTEN_ON = date(1941, 9, 14)
"""A wake's first day whose next wake opens the day after: a written order filed then is
carried out on the day the President next acts."""
LANDS = WRITTEN_ON + timedelta(days=1)


def _commit_all(game: Game) -> None:
    state = game.state
    game.now = state.wake.deadline if state.wake else game.now
    for person in game.base.people:
        with game.ids.drawn_by(f"commit:{person}"):
            wake.commit(game.store, CAMPAIGN, seat(person), game.now)
    game.tick()


def _receipts(game: Game) -> list[Fact]:
    return [
        f
        for f in game.state.facts.values()
        if f.predicate == "received_from"
        and f.subject == entity("uk")
        and f.obj == entity("roosevelt")
    ]


@pytest.mark.parametrize("without", [(), (Rule.WRITTEN_ORDERS,)], ids=["written_on", "written_off"])
def test_a_form_and_its_written_order_landing_one_day_write_one_receipt(
    monkeypatch: pytest.MonkeyPatch, without: tuple[Rule, ...]
) -> None:
    """The President files the finding by form and leaves its last step until the day his
    written allocation for the same share is carried out; his pass that day goes through,
    the next tick completes, and the game holds one receipt."""
    case = next(c for c in CASES if c.lever == "lend_lease_finding")
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    game = Game(opened(case.world, without), monkeypatch, Canned())
    assert game.form(case) == ""
    (form,) = (o for o in game.state.orders.values() if o.lever == case.lever)
    passed = False
    for _ in range(8):
        state = game.state
        if state.in_world_date == WRITTEN_ON:
            assert game.written(case) == ""
        if state.in_world_date == LANDS:
            assert waiting_on_human(state, state.orders[form.order_id])
            (written,) = state.routed.values()
            assert [p.applied for p in written.parts] == [LANDS]
            with game.ids.drawn_by("step"):
                realism_tick.take_step(
                    game.store, CAMPAIGN, seat("roosevelt"), form.order_id, StepAction.PASS, {}
                )
            passed = True
        _commit_all(game)
        if passed:
            break
    assert passed
    enacted = game.state.orders[form.order_id]
    assert enacted.status is OrderStatus.ENACTED
    assert enacted.outcomes[-1].on == LANDS
    assert game.state.in_world_date is not None and game.state.in_world_date > LANDS
    (receipt,) = _receipts(game)
    assert receipt.scope.known_by == frozenset({seat("roosevelt")})


# --- the resolver ------------------------------------------------------------------------

SETTLED = date(1941, 11, 4)
"""The day ``finding`` passes its last step."""


def _written(r: Rig, recipient: str, share: int, on: date = SETTLED) -> Fact:
    """The receipt the written allocation of ``share`` per cent to ``recipient`` files."""
    taker = EntityId(r.ids[recipient])
    issuer = r.state.seats[r.seats["roosevelt"]].embodies
    return allocate.receipt(r.state, taker, issuer, r.seats["roosevelt"], "lend_lease", share, on)


def _hold(r: Rig, fact: Fact) -> None:
    r.fold_changes((fact,))


def _facts(changes: tuple[object, ...]) -> list[Fact]:
    return [c for c in changes if isinstance(c, Fact)]


GAMES = {
    "world_keys": lambda: rig(),
    "stored_board": lambda: stored(rig()),
    "no_map": lambda: rig(POINTS),
}
"""A game the world compiles today, a stored game on a board without the production
keys, and a stored game with no map."""


def _finding(r: Rig, recipient: str, share: int) -> Order:
    order = finding(r, recipient, share)
    assert order.outcomes[-1].on == SETTLED
    return order


@pytest.mark.parametrize("game", GAMES)
def test_the_form_files_the_receipt_the_written_path_would(game: str) -> None:
    r = GAMES[game]()
    want = _written(r, "ussr", 10)
    assert want.fact_id not in r.state.facts
    assert _facts(production.resolve(r.state, _finding(r, "ussr", 10))) == [want]


@pytest.mark.parametrize("game", GAMES)
def test_the_form_files_no_receipt_its_written_order_has_filed(game: str) -> None:
    r = GAMES[game]()
    _hold(r, _written(r, "ussr", 10))
    order = _finding(r, "ussr", 10)
    changes = production.resolve(r.state, order)
    assert _facts(changes) == []
    r.fold_changes(changes)
    assert r.state.orders[order.order_id].status is OrderStatus.ENACTED


@pytest.mark.parametrize("game", GAMES)
def test_another_allocations_receipt_leaves_the_forms_own(game: str) -> None:
    r = GAMES[game]()
    _hold(r, _written(r, "ussr", 20))
    _hold(r, _written(r, "ussr", 10, SETTLED - timedelta(days=1)))
    want = _written(r, "ussr", 10)
    assert _facts(production.resolve(r.state, _finding(r, "ussr", 10))) == [want]
