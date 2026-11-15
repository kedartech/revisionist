"""Britain's troop-lift pool tied to the war at sea and to production (sealift, R6): on
the 1st it loses a share of the month's U-boat losses, and while Churchill's latest
production priority is merchant ships it gains a fixed tonnage."""

from datetime import date, timedelta

import pytest

from revisionist.core.fold import FoldError
from revisionist.core.ids import QuantityId
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import production, qid, shipping, value
from tests.test_realism_resolvers import Rig, naval

POOL = "uk_sealift_grt"
START_POOL = 300_000
OCT, NOV, DEC = date(1941, 10, 1), date(1941, 11, 1), date(1941, 12, 1)
GAIN = 15_000


def seated() -> Rig:
    r = Rig()
    for person in ("roosevelt", "churchill", "hitler"):
        r.seat(person)
    r.close_session_zero()
    return r


def pool(r: Rig) -> int | None:
    return value(r.state, POOL)


def pool_id(r: Rig) -> QuantityId:
    return qid(r.state, POOL)


def ship_day(r: Rig, day: date) -> tuple[QuantityChange, ...]:
    out = shipping.on_day(r.state, day)
    r.fold_changes(out)
    return out


def make_day(r: Rig, day: date) -> tuple[QuantityChange, ...]:
    out = production.on_day(r.state, day)
    r.fold_changes(out)
    return out


def priority(
    r: Rig, sector: str, filed: date, person: str = "churchill", passed: bool = True
) -> Order:
    """A production priority through its pipeline: two days at Pound, one at Ismay (or
    one at Jodl, two at Raeder for Hitler's)."""
    pipeline = {"churchill": "cos_directive", "hitler": "okw_directive"}[person]
    order = r.draft(person, "production_priority", pipeline, filed, sector=sector)
    days = [filed + timedelta(days=2), filed + timedelta(days=3)]
    r.pass_steps(order, days)
    return r.settle(order, OrderStatus.ENACTED if passed else OrderStatus.REFUSED)


def without_pool(r: Rig) -> Rig:
    held = {k: q for k, q in r.state.quantities.items() if k != pool_id(r)}
    r.state = r.state.model_copy(update={"quantities": held})
    return r


def test_on_1_november_the_pool_loses_a_tenth_of_octobers_losses() -> None:
    r = seated()
    ship_day(r, NOV)
    losses = value(r.state, "uboat_losses_oct")
    assert losses is not None and losses > 0
    assert pool(r) == START_POOL - losses * 10 // 100
    assert r.state.quantities[pool_id(r)].as_of == date(1941, 10, 31)


def test_on_1_october_the_pool_loses_nothing_for_septembers_sourced_figure() -> None:
    r = seated()
    out = ship_day(r, OCT)
    assert [c for c in out if c.quantity_id == pool_id(r)] == []
    assert pool(r) == START_POOL


def test_only_the_1st_takes_a_share() -> None:
    r = seated()
    assert ship_day(r, date(1941, 11, 2)) == ()
    assert pool(r) == START_POOL


def test_an_escort_order_in_september_keeps_more_of_the_pool_on_1_november() -> None:
    plain, escorted = seated(), seated()
    naval(escorted, "escort_convoys", "western_atlantic", day=date(1941, 9, 11))
    ship_day(plain, NOV)
    ship_day(escorted, NOV)
    p, e = pool(plain), pool(escorted)
    assert p is not None and e is not None
    assert START_POOL - e < START_POOL - p


def test_the_pool_never_falls_below_zero() -> None:
    r = seated()
    r.set_value(POOL, 5_000)
    ship_day(r, NOV)
    assert pool(r) == 0
    assert ship_day(r, DEC) and pool(r) == 0


def test_a_pool_already_empty_takes_no_change() -> None:
    r = seated()
    r.set_value(POOL, 0)
    out = ship_day(r, NOV)
    assert [c for c in out if c.quantity_id == pool_id(r)] == []


def test_a_share_taken_after_the_pools_own_date_is_dated_the_pools_date() -> None:
    r = seated()
    r.set_value(POOL, 250_000, as_of=NOV)  # a lift drawn on the 1st, before the day runs
    ship_day(r, NOV)
    q = r.state.quantities[pool_id(r)]
    losses = value(r.state, "uboat_losses_oct")
    assert losses is not None
    assert (q.value, q.as_of) == (250_000 - losses * 10 // 100, NOV)


def test_a_share_dated_before_the_pool_would_be_refused_by_the_fold() -> None:
    """The guard above is needed: the fold refuses a quantity set dated before its own."""
    r = seated()
    r.set_value(POOL, 250_000, as_of=NOV)
    with pytest.raises(FoldError):
        r.set_value(POOL, 240_000, as_of=date(1941, 10, 31))


def test_merchant_ship_priority_adds_to_the_pool_each_1st() -> None:
    r = seated()
    priority(r, "merchant_ships", date(1941, 9, 8))
    assert make_day(r, date(1941, 9, 20)) == ()
    make_day(r, OCT)
    assert pool(r) == START_POOL + GAIN
    assert r.state.quantities[pool_id(r)].as_of == OCT
    assert make_day(r, date(1941, 10, 2)) == ()
    make_day(r, NOV)
    assert pool(r) == START_POOL + 2 * GAIN


def test_no_priority_and_another_sector_add_nothing() -> None:
    r = seated()
    assert make_day(r, OCT) == ()
    priority(r, "aircraft", date(1941, 10, 6))
    assert make_day(r, NOV) == ()
    assert pool(r) == START_POOL


def test_a_later_priority_for_another_sector_stops_the_gain() -> None:
    r = seated()
    priority(r, "merchant_ships", date(1941, 9, 8))
    make_day(r, OCT)
    priority(r, "escorts", date(1941, 10, 6))
    assert make_day(r, NOV) == ()
    assert pool(r) == START_POOL + GAIN


def test_a_priority_set_back_to_merchant_ships_restarts_the_gain() -> None:
    r = seated()
    priority(r, "aircraft", date(1941, 9, 8))
    priority(r, "merchant_ships", date(1941, 10, 6))
    make_day(r, NOV)
    assert pool(r) == START_POOL + GAIN


def test_a_priority_counts_from_the_day_it_is_enacted() -> None:
    r = seated()
    order = priority(r, "merchant_ships", date(1941, 10, 27))  # settles 30 Oct
    assert order.outcomes[-1].on == date(1941, 10, 30)
    make_day(r, NOV)
    assert pool(r) == START_POOL + GAIN
    late = seated()
    priority(late, "merchant_ships", date(1941, 10, 30))  # settles 2 Nov
    assert make_day(late, NOV) == ()


def test_a_refused_merchant_ship_priority_adds_nothing() -> None:
    r = seated()
    priority(r, "merchant_ships", date(1941, 9, 8), passed=False)
    assert make_day(r, OCT) == ()


def test_another_sides_priority_neither_adds_nor_stops_britains() -> None:
    r = seated()
    priority(r, "merchant_ships", date(1941, 9, 8))
    priority(r, "uboats", date(1941, 10, 6), person="hitler")
    make_day(r, NOV)
    assert pool(r) == START_POOL + GAIN
    other = seated()
    priority(other, "merchant_ships", date(1941, 9, 8), person="hitler")
    assert make_day(other, OCT) == ()


def test_losses_and_the_priority_on_the_same_1st_both_count() -> None:
    r = seated()
    priority(r, "merchant_ships", date(1941, 9, 8))
    ship_day(r, NOV)
    make_day(r, NOV)
    losses = value(r.state, "uboat_losses_oct")
    assert losses is not None
    assert pool(r) == START_POOL - losses * 10 // 100 + GAIN


def test_a_world_without_the_pool_changes_nothing_else() -> None:
    held, bare = seated(), without_pool(seated())
    priority(held, "merchant_ships", date(1941, 9, 8))
    priority(bare, "merchant_ships", date(1941, 9, 8))
    assert make_day(bare, OCT) == ()
    out = ship_day(bare, NOV)
    assert [c.quantity_id for c in out] == [qid(bare.state, "uboat_losses_oct")]
    ship_day(held, NOV)
    assert value(bare.state, "uboat_losses_oct") == value(held.state, "uboat_losses_oct")


def test_a_pool_with_no_owner_takes_no_priority() -> None:
    r = seated()
    priority(r, "merchant_ships", date(1941, 9, 8))
    q = r.state.quantities[pool_id(r)]
    quantities = {**r.state.quantities, q.quantity_id: q.model_copy(update={"owner": None})}
    r.state = r.state.model_copy(update={"quantities": quantities})
    assert make_day(r, OCT) == ()
