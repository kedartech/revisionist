"""The evacuation order saves industry (EVC).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories``,
``holders`` and ``economy`` on, and each leader's card holds an evacuation form under the
rule name ``economy``: it names a territory and a rear territory. Norra holds the plain
and the hills (which yield nothing); Sudland the coast (grain 6, iron 2) and the Isle.
Grain and iron play the ``output`` role, levies ``manpower``.

Worked example (rules 2 and 3): the plain yields 4 grain. Norra's evacuation of the plain
to the hills is enacted on day 0, and from day 1 a day's part moves each day: half the
yield over ``EVAC_DAYS`` (20) days, 0.1 a day. Sudland takes the plain on day 10, after
that day's part has moved: the 1 grain already in the hills is kept, and the 1 still to
move stays in the plain and is lost with it. The plain yields 3 and the hills 1.
"""

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from revisionist.core import events as ev
from revisionist.core.fold import replay, state_hash
from revisionist.core.ids import OrderId, derived_id
from revisionist.core.realism import economy, resolvers
from revisionist.core.realism.kinds import Role
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import evacuation
from revisionist.core.realism.resolvers.evacuation import EVAC_DAYS, EVAC_SHARE, RESTART_DAYS
from revisionist.core.visibility import Visibility
from tests.test_adjacency_moves import START, Logged, World, day, entity, seat
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_economy import taken, yields
from tests.test_territory_model import CAMPAIGN

NORRA, SUDLAND = "norra", "sudland"
ISLE, COAST, PLAIN, HILLS = "isle", "sudland_coast", "norra_plain", "norra_hills"
AREAS = [PLAIN, HILLS, COAST, ISLE]
FOUR = yields(PLAIN, grain=4)


def with_economy(w: World) -> None:
    w["rules"] = ["territories", "holders", "economy"]


def holders_only(w: World) -> None:
    w["rules"] = ["territories", "holders"]


def forms(w: World) -> None:
    """An evacuation form on each leader's card, by the rule name ``economy``."""
    w["pipelines"] = [
        {
            "key": "war_office",
            "name": "The war office",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        }
    ]
    params = [
        {"name": "territory", "kind": "enum", "choices": AREAS},
        {"name": "rear", "kind": "enum", "choices": AREAS},
    ]
    for card in w["cards"]:
        card["pipelines"] = ["war_office"]
        card["levers"] = [
            {"name": "evacuate", "pipeline": "war_office", "resolver": "economy", "params": params}
        ]


Change = Callable[[World], None]


def game(tmp: Path, *changes: Change, rules: Change = with_economy) -> Logged:
    return Logged(territories_toy(tmp, rules, *changes, forms), "ilse", "tomas")


def enact(
    g: Logged, by: str = "ilse", on: date = START, n: int = 1, frm: str = PLAIN, rear: str = HILLS
) -> Order:
    """An evacuation of ``frm`` to ``rear``, enacted on ``on``."""
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "evc-order", by, n)),
        issuer=seat(by),
        lever="evacuate",
        pipeline=next(
            p.pipeline_id for p in g.state.pipelines.values() if p.name == "The war office"
        ),
        params={"territory": frm, "rear": rear},
        filed=on,
    )
    g.add(
        [
            ev.OrderDrafted(order=order),
            ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
        ]
    )
    return g.state.orders[order.order_id]


def walk_days(g: Logged, first: int, last: int) -> list[ev.YieldChanged]:
    """``evacuation.on_day`` for each day from ``first`` to ``last``, folded in turn."""
    out: list[ev.YieldChanged] = []
    for n in range(first, last + 1):
        changes = resolvers.apply_changes(g.state, evacuation.on_day(g.state, day(n)))
        g.add(changes)
        out += [c for c in changes if isinstance(c, ev.YieldChanged)]
    return out


def grain(g: Logged, area: str) -> float:
    return economy.yields_of(g.state, entity(area)).get("grain", 0)


def moves(out: Sequence[ev.Event]) -> list[ev.YieldChanged]:
    return [e.payload for e in out if isinstance(e.payload, ev.YieldChanged)]


def test_the_defaults() -> None:
    assert (EVAC_DAYS, EVAC_SHARE, RESTART_DAYS) == (20, 50, 45)


# --- Rule 2: over EVAC_DAYS, EVAC_SHARE of the output yield moves, a day's part at a time


def test_a_days_part_moves_each_day_from_the_day_after_it_is_enacted(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g)
    assert walk_days(g, 0, 0) == []
    (first,) = walk_days(g, 1, 1)
    assert (first.area, first.to, first.resource, first.amount) == (
        entity(PLAIN),
        entity(HILLS),
        "grain",
        0.1,
    )
    assert (grain(g, PLAIN), grain(g, HILLS)) == (3.9, 0.1)


def test_half_the_output_moves_over_twenty_days_and_no_more(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g)
    out = walk_days(g, 0, 40)
    assert [m.on for m in out] == [day(n) for n in range(1, EVAC_DAYS + 1)]
    assert all(m.amount == 0.1 for m in out)
    assert (grain(g, PLAIN), grain(g, HILLS)) == (2, 2)


def test_only_the_output_yield_moves(tmp_path: Path) -> None:
    g = game(tmp_path, yields(PLAIN, grain=4, iron=2, levies=100))
    enact(g)
    walk_days(g, 0, 30)
    assert economy.yields_of(g.state, entity(PLAIN)) == {"grain": 2, "iron": 1, "levies": 100}
    assert economy.yields_of(g.state, entity(HILLS)) == {"grain": 2, "iron": 1}


# --- Rule 3: a territory taken mid-way keeps what moved; the rest is lost with it ------


def test_the_worked_example_taken_on_day_ten_one_is_saved(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g)
    walk_days(g, 0, 10)
    taken(g, PLAIN, SUDLAND, day(10))
    walk_days(g, 11, 40)
    assert (grain(g, PLAIN), grain(g, HILLS)) == (3, 1)
    assert economy.holder(g.state, entity(HILLS)) == entity(NORRA)


def test_a_territory_taken_and_retaken_stays_evacuated_no_further(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g)
    walk_days(g, 0, 10)
    taken(g, PLAIN, SUDLAND, day(10))
    taken(g, PLAIN, NORRA, day(12))
    walk_days(g, 11, 40)
    assert (grain(g, PLAIN), grain(g, HILLS)) == (3, 1)


def test_a_rear_taken_ends_the_evacuation(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g)
    walk_days(g, 0, 5)
    taken(g, HILLS, SUDLAND, day(5))
    walk_days(g, 6, 40)
    assert (grain(g, PLAIN), grain(g, HILLS)) == (3.5, 0.5)


# --- Rule 1: the territory and the rear are both held by the issuing nation ------------


def test_another_nations_territory_is_not_evacuated(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, frm=COAST, rear=ISLE)  # both Sudland's; the order is Norra's
    assert walk_days(g, 0, 30) == []
    assert economy.yields_of(g.state, entity(COAST)) == {"grain": 6, "iron": 2}


def test_a_rear_held_by_another_nation_receives_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g, rear=COAST)
    assert walk_days(g, 0, 30) == []
    assert grain(g, PLAIN) == 4


def test_a_territory_is_not_its_own_rear(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g, rear=PLAIN)
    assert walk_days(g, 0, 30) == []


# --- Rule 4: moved yield produces nothing for RESTART_DAYS, then in full ---------------


def test_each_part_restarts_restart_days_after_it_moves(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g)
    out = walk_days(g, 0, 30)
    assert len(out) == EVAC_DAYS
    assert all(m.restart == day((m.on - START).days + RESTART_DAYS) for m in out)


def test_moved_industry_pays_nothing_until_it_restarts_then_in_full(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g)
    walk_days(g, 0, 30)

    def output(n: int) -> float:
        return economy.income(g.state, entity(NORRA), Role.OUTPUT, day(n))

    assert output(20) == 2  # all 2 moved, none restarted
    assert output(45) == 2
    assert output(46) == 2.1  # the day-1 part restarts on day 46
    assert output(65) == 4


# --- Rule 5: a territory can be evacuated once ------------------------------------------


def test_a_second_order_for_the_same_territory_moves_nothing_more(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g, n=1)
    enact(g, on=day(3), n=2)
    walk_days(g, 0, 30)
    assert (grain(g, PLAIN), grain(g, HILLS)) == (2, 2)


def test_a_territory_evacuated_once_is_not_evacuated_again_later(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g, n=1)
    walk_days(g, 0, 30)
    enact(g, on=day(31), n=2)
    assert walk_days(g, 31, 80) == []
    assert (grain(g, PLAIN), grain(g, HILLS)) == (2, 2)


def test_two_orders_on_one_day_give_the_same_result_in_either_order(tmp_path: Path) -> None:
    def run(ns: list[int]) -> dict[str, float]:
        g = game(tmp_path, FOUR, yields(HILLS, grain=1))
        for n in ns:
            enact(g, n=n, frm=PLAIN if n == 1 else HILLS, rear=HILLS if n == 1 else PLAIN)
        walk_days(g, 0, 30)
        return {a: grain(g, a) for a in (PLAIN, HILLS)}

    assert run([1, 2]) == run([2, 1]) == {PLAIN: 2.5, HILLS: 2.5}


# --- The gate, the day walk and replay ---------------------------------------------------


def test_without_the_economy_rule_nothing_moves(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR, rules=holders_only)
    enact(g)
    assert walk_days(g, 0, 30) == []


def test_the_day_walk_moves_the_parts_sealed_to_the_nations_seats(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g)
    out = g.walk(day(1), day(3))
    assert [m.on for m in moves(out)] == [day(1), day(2), day(3)]
    for e in out:
        if isinstance(e.payload, ev.YieldChanged):
            assert e.scope.visibility is Visibility.RESTRICTED
            assert e.scope.known_by == frozenset({seat("ilse")})
    assert state_hash(replay(g.log)) == state_hash(g.state)


def test_an_evacuation_order_draws_no_production_report(tmp_path: Path) -> None:
    g = game(tmp_path, FOUR)
    enact(g)
    out = g.walk(day(1), day(35))
    assert len(moves(out)) == EVAC_DAYS
    assert [e for e in out if isinstance(e.payload, ev.DocumentIssued)] == []
