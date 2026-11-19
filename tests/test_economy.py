"""What a territory yields, and one war-economy figure per nation (YLD).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories``,
``holders`` and ``economy`` on. Norra holds the hills (no yields) and the plain (grain 10,
levies 2000); Sudland holds the coast (grain 6, iron 2) and the Isle. Grain and iron play
the ``output`` role, levies ``manpower``, pitch ``fuel``. The game starts on 2 April 1900,
so day 29 is 1 May and day 60 is 1 June.

Worked example (rule 3): the Isle, given 4 iron of output, is taken by Norra on day 0.
Taken output pays nothing for ``CAPTURE_LAG_DAYS`` (30) days, then ``CAPTURE_SHARE``
(half): Norra's income from it is 0 on day 29 and 2 on day 31. Had Sudland taken it back
on day 40, it would pay Sudland 2 until day 69 and the full 4 from day 70 (rule 4).
"""

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, replay, state_hash
from revisionist.core.ids import PipelineId
from revisionist.core.project import project
from revisionist.core.realism import economy
from revisionist.core.realism.economy import (
    CAPTURE_LAG_DAYS,
    CAPTURE_SHARE,
    SUPPLY_LAG_DAYS,
    WEIGHTS,
    EconomyError,
    Pools,
)
from revisionist.core.realism.kinds import Role
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.quantity import RESOLVER_KEYS
from revisionist.core.state import State, View
from revisionist.core.visibility import Visibility
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup
from tests.test_adjacency_moves import START, Logged, World, day, entity, levers, order, seat
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_holders import Wakes, held
from tests.test_territory_model import CAMPAIGN, created, refused, variant

NORRA, SUDLAND = "norra", "sudland"
ISLE, COAST, PLAIN, HILLS = "isle", "sudland_coast", "norra_plain", "norra_hills"
MAY_1, JUNE_1 = day(29), day(60)


def with_economy(w: World) -> None:
    w["rules"] = ["territories", "holders", "economy"]


def toy(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    """The toy world with ``territories``, ``holders`` and ``economy`` on."""
    return territories_toy(tmp, with_economy, *changes)


def yields(area: str, **amounts: float) -> Callable[[World], None]:
    def change(w: World) -> None:
        (t,) = [t for t in w["territories"] if t["key"] == area]
        t["yields"] = amounts

    return change


def roles(w: World) -> None:
    """Two more resources, for the supply and prestige roles."""
    w["resources"] += [
        {"key": "rails", "name": "Rails", "unit": "miles", "role": "supply"},
        {"key": "glory", "name": "Glory", "unit": "laurels", "role": "prestige"},
    ]


def rich_isle(w: World) -> None:
    """The Isle yields every role: iron 4, levies 100, pitch 2, rails 3, glory 1."""
    if not any(r["role"] == "supply" for r in w["resources"]):
        roles(w)
    yields(ISLE, iron=4, levies=100, pitch=2, rails=3, glory=1)(w)


RICH_ISLE = rich_isle


def game(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    return Logged(toy(tmp, *changes), "ilse", "tomas")


def taken(g: Logged, area: str, by: str, on: date) -> None:
    """``area`` changes hands to ``by`` on ``on``, as the day walk would land it."""
    was = economy.holder(g.state, entity(area))
    g.add([ev.AreaHeld(area=entity(area), holder=entity(by), was=was, on=on)])


def income(g: Logged, polity: str, role: Role, on: date) -> float:
    return economy.income(g.state, entity(polity), role, on)


def pools(state: State | View, polity: str) -> Pools | None:
    return state.economy.pools.get(entity(polity))


def sets(out: Sequence[ev.Event]) -> list[ev.EconomySet]:
    return [e.payload for e in out if isinstance(e.payload, ev.EconomySet)]


# --- Rule 1: income is the sum of a role's yields over held territories, times factor --


def test_income_sums_each_roles_yields_over_the_territories_held(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert income(g, NORRA, Role.OUTPUT, START) == 10
    assert income(g, NORRA, Role.MANPOWER, START) == 2000
    assert income(g, SUDLAND, Role.OUTPUT, START) == 8  # grain 6 and iron 2 share the role
    assert income(g, SUDLAND, Role.MANPOWER, START) == 0
    assert income(g, NORRA, Role.FUEL, START) == 0


def test_income_follows_the_holder(tmp_path: Path) -> None:
    g = game(tmp_path, RICH_ISLE)
    assert income(g, SUDLAND, Role.OUTPUT, START) == 12
    taken(g, ISLE, NORRA, START)
    assert income(g, SUDLAND, Role.OUTPUT, day(400)) == 8
    assert income(g, NORRA, Role.OUTPUT, day(400)) == 10 + 2


def test_a_polity_holding_nothing_has_no_income(tmp_path: Path) -> None:
    g = game(
        tmp_path, lambda w: w["entities"].append({"key": "ost", "kind": "polity", "name": "Ost"})
    )
    for role in Role:
        assert income(g, "ost", role, START) == 0


# --- Rule 2: on the 1st of each month output and manpower income go into the pools ------


def test_the_pools_are_paid_on_the_first_of_each_month(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert sets(g.walk(day(1), day(28))) == []
    out = g.walk(MAY_1, MAY_1)
    assert sorted((p.polity, p.pools, p.on) for p in sets(out)) == sorted(
        [
            (entity(NORRA), Pools(output=10, manpower=2000), MAY_1),
            (entity(SUDLAND), Pools(output=8, manpower=0), MAY_1),
        ]
    )
    assert pools(g.state, NORRA) == Pools(output=10, manpower=2000)
    assert sets(g.walk(day(30), day(59))) == []
    g.walk(JUNE_1, JUNE_1)
    assert pools(g.state, NORRA) == Pools(output=20, manpower=4000)
    assert pools(g.state, SUDLAND) == Pools(output=16, manpower=0)


def test_fuel_supply_and_prestige_are_not_pooled(tmp_path: Path) -> None:
    g = game(tmp_path, yields(PLAIN, pitch=5, rails=2, glory=1), roles)
    g.walk(day(1), MAY_1)
    assert pools(g.state, NORRA) is None  # no output or manpower: nothing paid


def test_the_month_is_paid_from_what_is_held_that_day(tmp_path: Path) -> None:
    g = game(tmp_path, RICH_ISLE)
    taken(g, ISLE, NORRA, START)
    g.walk(day(1), MAY_1)
    assert pools(g.state, SUDLAND) == Pools(output=8, manpower=0)
    assert pools(g.state, NORRA) == Pools(output=10, manpower=2000)  # the Isle pays 0 yet
    g.walk(day(30), JUNE_1)
    assert pools(g.state, NORRA) == Pools(output=10 + 12, manpower=4000)


def test_the_monthly_payment_is_sealed_to_the_nations_seats(tmp_path: Path) -> None:
    g = game(tmp_path)
    out = [e for e in g.walk(day(1), MAY_1) if isinstance(e.payload, ev.EconomySet)]
    assert len(out) == 2
    for e in out:
        assert isinstance(e.payload, ev.EconomySet)
        own = seat("ilse") if e.payload.polity == entity(NORRA) else seat("tomas")
        assert e.scope.visibility is Visibility.RESTRICTED
        assert e.scope.known_by == frozenset({own})


# --- Rule 3: a taken territory's factors ------------------------------------------------


def test_the_defaults() -> None:
    assert (CAPTURE_LAG_DAYS, CAPTURE_SHARE, SUPPLY_LAG_DAYS) == (30, 50, 7)
    assert WEIGHTS == {Role.OUTPUT: 3, Role.MANPOWER: 1, Role.FUEL: 2}


def test_taken_output_pays_nothing_for_the_lag_then_the_share(tmp_path: Path) -> None:
    """The docstring's worked example: 4 output taken on day 0 pays 0 on day 29 and 2 on
    day 31."""
    g = game(tmp_path, yields(ISLE, iron=4))
    taken(g, ISLE, NORRA, START)

    def isle_part(n: int) -> float:
        return income(g, NORRA, Role.OUTPUT, day(n)) - 10

    assert isle_part(29) == 0
    assert isle_part(30) == 2
    assert isle_part(31) == 2
    assert isle_part(400) == 2


def test_taken_fuel_lags_like_output(tmp_path: Path) -> None:
    g = game(tmp_path, RICH_ISLE)
    taken(g, ISLE, NORRA, START)
    assert income(g, NORRA, Role.FUEL, day(29)) == 0
    assert income(g, NORRA, Role.FUEL, day(30)) == 1


def test_an_occupier_gets_no_manpower(tmp_path: Path) -> None:
    g = game(tmp_path, RICH_ISLE)
    taken(g, ISLE, NORRA, START)
    for n in (0, 29, 31, 400):
        assert income(g, NORRA, Role.MANPOWER, day(n)) == 2000  # the plain's only
    assert income(g, SUDLAND, Role.MANPOWER, day(400)) == 0


def test_taken_supply_works_for_the_taker_after_its_lag(tmp_path: Path) -> None:
    g = game(tmp_path, RICH_ISLE)
    taken(g, ISLE, NORRA, START)
    assert income(g, NORRA, Role.SUPPLY, day(SUPPLY_LAG_DAYS - 1)) == 0
    assert income(g, NORRA, Role.SUPPLY, day(SUPPLY_LAG_DAYS)) == 3


def test_taken_prestige_moves_at_once(tmp_path: Path) -> None:
    g = game(tmp_path, RICH_ISLE)
    assert income(g, SUDLAND, Role.PRESTIGE, START) == 1
    taken(g, ISLE, NORRA, START)
    assert income(g, NORRA, Role.PRESTIGE, START) == 1
    assert income(g, SUDLAND, Role.PRESTIGE, START) == 0


# --- Rule 4: a territory retaken by the holder it was taken from ------------------------


def test_a_retaken_territory_pays_the_share_for_the_lag_then_in_full(tmp_path: Path) -> None:
    g = game(tmp_path, RICH_ISLE)
    taken(g, ISLE, NORRA, START)
    taken(g, ISLE, SUDLAND, day(40))
    assert income(g, NORRA, Role.OUTPUT, day(41)) == 10
    assert income(g, SUDLAND, Role.OUTPUT, day(40)) == 8 + 2
    assert income(g, SUDLAND, Role.OUTPUT, day(69)) == 8 + 2
    assert income(g, SUDLAND, Role.OUTPUT, day(70)) == 8 + 4
    assert income(g, SUDLAND, Role.MANPOWER, day(69)) == 50
    assert income(g, SUDLAND, Role.MANPOWER, day(70)) == 100
    assert income(g, SUDLAND, Role.FUEL, day(69)) == 1
    assert income(g, SUDLAND, Role.FUEL, day(70)) == 2


def test_a_third_holder_takes_it_as_a_capture(tmp_path: Path) -> None:
    def ost(w: World) -> None:
        w["entities"].append({"key": "ost", "kind": "polity", "name": "Ost"})
        w["wars"].append({"a": "ost", "b": "norra", "since": "1900-03-01", "source": "toy"})

    g = game(tmp_path, RICH_ISLE, ost)
    taken(g, ISLE, NORRA, START)
    taken(g, ISLE, "ost", day(40))
    assert income(g, "ost", Role.OUTPUT, day(69)) == 0
    assert income(g, "ost", Role.OUTPUT, day(70)) == 2
    assert income(g, "ost", Role.MANPOWER, day(400)) == 0


# --- Rule 5: one public figure per nation -----------------------------------------------


FIGURE_WORLD = (yields(PLAIN, grain=10, levies=20), yields(COAST, grain=6, iron=2, pitch=1))
"""Norra: 3 x 10 output + 1 x 20 manpower = 50. Sudland: 3 x 8 + 2 x 1 fuel = 26."""


def test_the_largest_nation_at_the_start_is_100(tmp_path: Path) -> None:
    g = game(tmp_path, *FIGURE_WORLD)
    assert economy.figure(g.state, entity(NORRA)) == 100
    assert economy.figure(g.state, entity(SUDLAND)) == 52


def test_the_figure_reads_holders_and_the_days_they_changed(tmp_path: Path) -> None:
    g = game(tmp_path, *FIGURE_WORLD)
    taken(g, COAST, NORRA, START)
    assert economy.figure(g.state, entity(SUDLAND), day(1)) == 0
    assert economy.figure(g.state, entity(NORRA), day(1)) == 100  # nothing yet: lagged
    # After the lag: half the coast's output and fuel, none of its manpower (it has none).
    assert economy.figure(g.state, entity(NORRA), day(30)) == 126


def test_the_figure_reads_no_pool_and_no_moved_yield(tmp_path: Path) -> None:
    g = game(tmp_path, *FIGURE_WORLD)
    before = economy.figure(g.state, entity(NORRA)), economy.figure(g.state, entity(SUDLAND))
    g.walk(day(1), MAY_1)
    assert pools(g.state, NORRA) is not None
    g.add([economy.move_yield(g.state, entity(PLAIN), entity(HILLS), "grain", 4, MAY_1)])
    now = (
        economy.figure(g.state, entity(NORRA), START),
        economy.figure(g.state, entity(SUDLAND), START),
    )
    assert now == before
    rich = g.state.model_copy(
        update={
            "economy": g.state.economy.model_copy(
                update={"pools": {entity(SUDLAND): Pools(output=10**6, manpower=10**6)}}
            )
        }
    )
    assert economy.figure(rich, entity(SUDLAND), START) == before[1]


def test_the_figure_reads_the_printed_yield_when_a_moved_one_changes_hands(
    tmp_path: Path,
) -> None:
    """Norra moves 4 grain from the plain to the hills, and Sudland takes the hills. The
    move is Norra's own data: the figure still reads the printed yields, so the hills
    (printed: nothing) add nothing to Sudland's figure and take nothing from Norra's."""
    g = game(tmp_path, *FIGURE_WORLD)
    g.add([economy.move_yield(g.state, entity(PLAIN), entity(HILLS), "grain", 4, START)])
    taken(g, HILLS, SUDLAND, START)
    later = day(400)
    assert income(g, SUDLAND, Role.OUTPUT, later) == 8 + 2  # the true income moves
    assert economy.figure(g.state, entity(NORRA), later) == 100
    assert economy.figure(g.state, entity(SUDLAND), later) == 52


def test_every_seat_reads_the_same_figure_from_its_own_view(tmp_path: Path) -> None:
    g = game(tmp_path, *FIGURE_WORLD)
    taken(g, COAST, NORRA, START)
    g.walk(day(1), MAY_1)
    for person in ("ilse", "tomas"):
        view = project(g.state, seat(person))
        for polity in (NORRA, SUDLAND):
            assert economy.figure(view, entity(polity), MAY_1) == economy.figure(
                g.state, entity(polity), MAY_1
            )


def test_no_figure_without_income_at_the_start(tmp_path: Path) -> None:
    def barren(w: World) -> None:
        for t in w["territories"]:
            t.pop("yields", None)

    g = game(tmp_path, barren)
    assert economy.figure(g.state, entity(NORRA)) == 0


# --- Rule 6: move part of a yield between two territories of one holder ----------------


def test_move_yield_moves_part_of_a_yield_and_lands_yield_changed(tmp_path: Path) -> None:
    g = game(tmp_path)
    moved = economy.move_yield(g.state, entity(PLAIN), entity(HILLS), "grain", 4, day(3))
    assert moved == ev.YieldChanged(
        area=entity(PLAIN), to=entity(HILLS), resource="grain", amount=4, on=day(3)
    )
    g.add([moved])
    assert economy.yields_of(g.state, entity(PLAIN)) == {"grain": 6, "levies": 2000}
    assert economy.yields_of(g.state, entity(HILLS)) == {"grain": 4}
    assert income(g, NORRA, Role.OUTPUT, day(3)) == 10  # one holder: the total holds


def test_moved_yield_pays_where_it_now_lies(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.add([economy.move_yield(g.state, entity(PLAIN), entity(HILLS), "grain", 4, day(3))])
    taken(g, HILLS, SUDLAND, day(3))
    assert income(g, NORRA, Role.OUTPUT, day(100)) == 6
    assert income(g, SUDLAND, Role.OUTPUT, day(100)) == 8 + 2


@pytest.mark.parametrize(
    ("frm", "to", "resource", "amount", "why"),
    [
        (PLAIN, COAST, "grain", 4, "one holder"),
        (PLAIN, HILLS, "grain", 11, "more than"),
        (PLAIN, HILLS, "iron", 1, "more than"),
        (PLAIN, HILLS, "silk", 1, "resource"),
        (PLAIN, HILLS, "grain", 0, "more than nothing"),
        (PLAIN, "the_gulf", "grain", 1, "territor"),
        (PLAIN, PLAIN, "grain", 1, "another"),
    ],
)
def test_move_yield_refuses_what_it_cannot_move(
    tmp_path: Path, frm: str, to: str, resource: str, amount: float, why: str
) -> None:
    g = game(tmp_path)
    with pytest.raises(EconomyError, match=why):
        economy.move_yield(g.state, entity(frm), entity(to), resource, amount, day(3))


def test_the_fold_refuses_a_move_the_rule_would_refuse(tmp_path: Path) -> None:
    g = game(tmp_path)
    bad = ev.YieldChanged(
        area=entity(PLAIN), to=entity(COAST), resource="grain", amount=1, on=day(3)
    )
    with pytest.raises(FoldError):
        g.add([bad])
    more = ev.YieldChanged(
        area=entity(PLAIN), to=entity(HILLS), resource="grain", amount=11, on=day(3)
    )
    with pytest.raises(FoldError):
        g.add([more])


def test_the_fold_refuses_pools_for_what_is_not_a_polity(tmp_path: Path) -> None:
    g = game(tmp_path)
    with pytest.raises(FoldError):
        g.add([ev.EconomySet(polity=entity(PLAIN), pools=Pools(output=1), on=MAY_1)])


# --- Rule 7: the rule name ``economy`` for forms -----------------------------------------


def test_economy_is_a_rule_name_for_forms() -> None:
    assert "economy" in RESOLVER_KEYS


def test_a_form_naming_a_rule_with_no_function_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revisionist.core.realism import resolvers

    def lever_for(key: str) -> Callable[[World], None]:
        def change(w: World) -> None:
            levers(w)
            for card in w["cards"]:
                card["levers"][0]["resolver"] = key

        return change

    economy_lever = lever_for("economy")
    awaiting = [k for k in RESOLVER_KEYS if k not in resolvers.ON_ORDER]
    for key in awaiting:
        problems = refused(toy(tmp_path, lever_for(key)))
        assert any(f"has no rule yet: {key}" in p for p in problems)
    monkeypatch.delitem(resolvers.ON_ORDER, "economy", raising=False)
    problems = refused(toy(tmp_path, economy_lever))
    assert any("has no rule yet: economy" in p for p in problems)


# --- Rule 8: gated by ``economy``; stored games unchanged --------------------------------


def test_without_economy_nothing_is_paid_or_moved(tmp_path: Path) -> None:
    def holders_only(w: World) -> None:
        w["rules"] = ["territories", "holders"]

    g = Logged(territories_toy(tmp_path, holders_only), "ilse", "tomas")
    out = g.walk(day(1), MAY_1)
    assert sets(out) == []
    assert g.state.economy == economy.Economy()
    with pytest.raises(EconomyError, match="off"):
        economy.move_yield(g.state, entity(PLAIN), entity(HILLS), "grain", 1, day(3))
    with pytest.raises(FoldError):
        g.add([ev.EconomySet(polity=entity(NORRA), pools=Pools(output=1), on=MAY_1)])
    assert economy.walk(g.state, MAY_1) == []


def test_economy_needs_holders(tmp_path: Path) -> None:
    problems = refused(variant(tmp_path, lambda w: w.update(rules=["territories", "economy"])))
    assert "rules: economy needs holders" in problems


def test_a_stored_game_gains_no_economy() -> None:
    world = cmp.load_world(Path(__file__).parent / "worlds" / "territory-toy.yaml")
    events, state = created(world)
    assert "economy" not in state.model_dump(mode="json")
    assert economy.walk(state, MAY_1) == []
    assert state_hash(replay(events)) == state_hash(state)


# --- The view: a nation's pools are seen by its own seats only ---------------------------


def test_a_seat_sees_its_own_nations_pools_and_no_other(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.walk(day(1), MAY_1)
    g.add([economy.move_yield(g.state, entity(PLAIN), entity(HILLS), "grain", 4, MAY_1)])
    mine = project(g.state, seat("ilse"))
    assert mine.economy.pools == {entity(NORRA): Pools(output=10, manpower=2000)}
    assert set(mine.economy.yields) == {entity(PLAIN), entity(HILLS)}
    theirs = project(g.state, seat("tomas"))
    assert theirs.economy.pools == {entity(SUDLAND): Pools(output=8, manpower=0)}
    assert theirs.economy.yields == {}


def test_economy_events_never_reach_the_catch_up_feed(tmp_path: Path) -> None:
    assert {"economy_set", "yield_changed"} <= catchup.NEVER
    g = game(tmp_path)
    g.walk(day(1), MAY_1)
    for person in ("ilse", "tomas"):
        fed = catchup.feed(g.state, g.log, seat(person), 0, 10_000)
        assert not [f for f in fed if f.event.kind in {"economy_set", "yield_changed"}]


# --- Invariant 3: income from what is held, never from orders filed ----------------------


def drafted(by: str, force: str, to: str, n: int) -> ev.OrderDrafted:
    """``order`` filed through the toy's field-order pipeline, at its first step."""
    o = order(by, force, to, n=n)
    return ev.OrderDrafted(
        order=o.model_copy(
            update={
                "pipeline": PipelineId(object_id(CAMPAIGN, "pipeline", "field_order")),
                "status": OrderStatus.MOVING,
            }
        )
    )


def test_orders_filed_in_either_order_or_not_at_all_give_the_same_pools(tmp_path: Path) -> None:
    """Norra's levy takes the undefended Isle in every run (sent before the wakes); the
    filed orders move only pieces that take nothing. The pools are the same whichever order
    the orders are filed in, and the same as with none filed."""
    world = toy(tmp_path, RICH_ISLE, levers)
    filings = [
        drafted("tomas", "sudland_galleys", "open_sea", 1),
        drafted("ilse", "norra_herald", "norrhavn", 2),
        drafted("ilse", "norra_kites", "norrhavn", 3),
    ]

    def run(filed: Sequence[ev.OrderDrafted]) -> tuple[Any, ...]:
        g = Logged(world, "ilse", "tomas")
        g.send("ilse", "norra_levy", ISLE)
        w = Wakes(g)
        if filed:
            w.add(filed)
        taken_on: list[Any] = []
        while (w.state.in_world_date or START) < JUNE_1:
            taken_on += [(h.area, h.holder) for h in held(w.close())]
        state = w.state
        assert len(state.orders) == len(filed)
        return pools(state, NORRA), pools(state, SUDLAND), taken_on

    none = run([])
    a = run(filings)
    b = run(filings[::-1])
    assert a == b == none
    assert none[2] == [(entity(ISLE), entity(NORRA))]
    assert none[0] is not None and none[1] is not None


# --- RSD: moved industry restarts after a delay ------------------------------------------
#
# Worked example: the plain yields 4 grain of output; on day 0 Norra moves 0.1 of it to
# the hills (which yield nothing) with ``restart_days`` 45. The plain loses the part at
# once and the hills pay nothing of it until day 45: Norra's output income is 3.9 on day 0
# and on day 44, and 4.0 on day 45.

FOUR = yields(PLAIN, grain=4)


def evacuate(g: Logged, on: date, amount: float = 0.1, days: int = 45) -> ev.YieldChanged:
    moved = economy.move_yield(
        g.state, entity(PLAIN), entity(HILLS), "grain", amount, on, restart_days=days
    )
    g.add([moved])
    return moved


def test_move_yield_lands_the_date_the_moved_part_restarts(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    later = economy.move_yield(
        g.state, entity(PLAIN), entity(HILLS), "grain", 0.1, day(3), restart_days=45
    )
    assert later.restart == day(48)
    now = economy.move_yield(g.state, entity(PLAIN), entity(HILLS), "grain", 0.1, day(3))
    assert now.restart is None  # the default, 0 days: today's behaviour
    assert "restart" not in now.model_dump(mode="json")
    with pytest.raises(EconomyError, match="restart"):
        economy.move_yield(
            g.state, entity(PLAIN), entity(HILLS), "grain", 0.1, day(3), restart_days=-1
        )


def test_the_worked_example_a_moved_part_restarts_on_its_date(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    evacuate(g, START)
    assert income(g, NORRA, Role.OUTPUT, START) == 3.9
    assert income(g, NORRA, Role.OUTPUT, day(44)) == 3.9
    assert income(g, NORRA, Role.OUTPUT, day(45)) == 4.0
    assert income(g, NORRA, Role.OUTPUT, day(400)) == 4.0


def test_the_source_loses_the_part_on_the_day_of_the_move(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    evacuate(g, day(10), amount=1)
    assert economy.yields_of(g.state, entity(PLAIN)) == {"grain": 3}
    assert economy.yields_of(g.state, entity(HILLS)) == {"grain": 1}
    assert income(g, NORRA, Role.OUTPUT, day(10)) == 3
    assert income(g, NORRA, Role.OUTPUT, day(54)) == 3
    assert income(g, NORRA, Role.OUTPUT, day(55)) == 4


def test_the_month_pays_nothing_of_a_part_before_it_restarts(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    evacuate(g, START, amount=1)
    g.walk(day(1), JUNE_1)  # May 1 is day 29 and June 1 day 60; the part restarts on day 45
    assert pools(g.state, NORRA) == Pools(output=3 + 4, manpower=0)


def test_the_pending_restart_is_folded_so_replay_and_the_view_agree(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    evacuate(g, START)
    again = replay(g.log)
    assert state_hash(again) == state_hash(g.state)
    mine = project(g.state, seat("ilse"))
    for n in (0, 44, 45):
        live = economy.income(g.state, entity(NORRA), Role.OUTPUT, day(n))
        assert economy.income(again, entity(NORRA), Role.OUTPUT, day(n)) == live
        assert economy.income(mine, entity(NORRA), Role.OUTPUT, day(n)) == live
    assert set(mine.economy.pending) == {entity(HILLS)}
    assert project(g.state, seat("tomas")).economy.pending == {}


def test_a_taken_territory_carries_its_pending_part(tmp_path: Path) -> None:
    """Sudland takes the hills on day 0 with Norra's 1 grain pending until day 45. The
    capture lag ends on day 30, but the part is still idle until day 45; from then it
    pays Sudland the capture share, half."""
    g = game(tmp_path, FOUR)
    evacuate(g, START, amount=1)
    taken(g, HILLS, SUDLAND, START)
    assert income(g, SUDLAND, Role.OUTPUT, day(44)) == 8
    assert income(g, SUDLAND, Role.OUTPUT, day(45)) == 8 + 0.5
    assert income(g, NORRA, Role.OUTPUT, day(45)) == 3


def test_moving_from_a_territory_takes_its_working_part_first(tmp_path: Path) -> None:
    """The hills hold 1 grain idle until day 45 and 1 working. Moving 1 away on day 10
    leaves the idle one idle; moving more takes part of the idle one too, which then pays
    where it lands from that move's own restart date (here at once), and what stays is
    idle, never below nothing."""

    def hills_back(amount: float) -> Logged:
        g = game(tmp_path, yields(PLAIN, grain=4), yields(HILLS, grain=1))
        evacuate(g, START, amount=1)
        move = economy.move_yield(g.state, entity(HILLS), entity(PLAIN), "grain", amount, day(10))
        g.add([move])
        return g

    g = hills_back(1)
    assert income(g, NORRA, Role.OUTPUT, day(10)) == 4  # plain 4; the hills' 1 idle
    assert income(g, NORRA, Role.OUTPUT, day(45)) == 5
    g = hills_back(1.5)  # all the working part and half the idle one
    assert economy.working(g.state, entity(HILLS), day(10)) == {"grain": 0}
    assert income(g, NORRA, Role.OUTPUT, day(10)) == 4.5
    assert income(g, NORRA, Role.OUTPUT, day(45)) == 5


def test_the_fold_refuses_a_restart_before_the_move(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    bad = ev.YieldChanged(
        area=entity(PLAIN),
        to=entity(HILLS),
        resource="grain",
        amount=1,
        on=day(3),
        restart=day(2),
    )
    with pytest.raises(FoldError, match="restart"):
        g.add([bad])


def test_a_move_with_no_restart_date_folds_as_restarting_at_once(tmp_path: Path) -> None:
    """A stored ``yield_changed`` from before RSD has no restart date: the part pays where
    it lies from the day of the move, and the economy dumps no pending key."""
    g = game(tmp_path, FOUR)
    g.add(
        [
            ev.YieldChanged(
                area=entity(PLAIN), to=entity(HILLS), resource="grain", amount=1, on=START
            )
        ]
    )
    assert income(g, NORRA, Role.OUTPUT, START) == 4
    assert g.state.economy.pending == {}
    assert "pending" not in g.state.economy.model_dump(mode="json")
