"""Sealift (reach, R6): an army crosses the sea only on its side's shipping. It marches to
its side's fleet base nearest it on its own land, sails at convoy pace, and lands only at a
fleet base of its side; the lift is drawn from the side's pool the day it sets out and given
back the day it lands. Autumn 1941 gives Britain the only pool."""

import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism import bases, sealift
from revisionist.core.realism.apply import _move
from revisionist.core.realism.bases import Tier, reach
from revisionist.core.realism.effect import MoveForce
from revisionist.core.realism.geography import SPEED_KM_PER_DAY, Feature, FeatureKind, km_between
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import movement, qid, value
from revisionist.core.realism.routing import sea_route
from revisionist.core.realism.war import War, war_id_for
from tests.test_realism_resolvers import Rig, rig

POINTS = str(Path(__file__).parent / "worlds" / "autumn-1941-points.yaml")
"""The autumn-1941 world before territories: these tests pin movement between points."""

F, A = FeatureKind.FLEET, FeatureKind.ARMY
POOL = "uk_sealift_grt"
FILED = date(1941, 9, 2)
COS = [date(1941, 9, 4), date(1941, 9, 5)]  # Pound decides, Ismay passes it on
SET_OUT = COS[-1]


def at(r: Rig, key: str) -> EntityId:
    return EntityId(r.ids[key])


def feature(r: Rig, key: str) -> Feature:
    return r.state.features[FeatureId(r.ids[key])]


def placed(r: Rig, key: str, where: str) -> Feature:
    f = feature(r, key).model_copy(update={"places": (at(r, where),)})
    r.fold_changes((f,))
    return f


def order(r: Rig, to: str, force: str = "home_forces", days: list[date] = COS) -> Order:
    return r.enact("churchill", "move_army", "cos_directive", FILED, days, force=force, to=to)


def churchill() -> Rig:
    return rig(POINTS, seat="churchill")


def pool(r: Rig) -> int | None:
    return value(r.state, POOL)


def lift_days(r: Rig, origin: str, port: str, land: str) -> int:
    """The march to the port at an army's pace plus the sea route at convoy pace."""
    a, b, c = (r.state.entities[at(r, k)].at for k in (origin, port, land))
    assert a is not None and b is not None and c is not None
    route = sea_route(r.state, at(r, "uk"), b, c)
    assert route is not None
    march = math.ceil(km_between(a, b) / SPEED_KM_PER_DAY[A])
    return march + math.ceil(route.km / 350)


def resolved(r: Rig, o: Order) -> tuple[Feature, list[QuantityChange]]:
    out = movement.order_changes(r.state, o)
    moved = [c for c in out if isinstance(c, Feature)]
    assert len(moved) == 1, out
    return moved[0], [c for c in out if isinstance(c, QuantityChange)]


def arrive(r: Rig, day: date) -> None:
    r.fold_changes(movement.day_changes(r.state, day))


def test_britain_starts_with_a_pool_no_seat_sees_but_the_admiralty_reports() -> None:
    r = churchill()
    q = r.state.quantities[qid(r.state, POOL)]
    assert (q.value, q.unit, q.owner, q.scope) == (300_000, "GRT", at(r, "uk"), None)
    (feed,) = [f for f in r.state.feeds.values() if f.name == "Admiralty reports"]
    assert q.quantity_id in feed.reports


def test_home_forces_sail_from_liverpool_to_reykjavik_and_give_the_ships_back() -> None:
    r = churchill()
    lift = bases.lift(r.state, feature(r, "home_forces"), at(r, "reykjavik"))
    days = lift_days(r, "london", "liverpool", "reykjavik")
    assert lift == sealift.Lift(embark=at(r, "liverpool"), days=days, pool=POOL)
    assert days == 12 + 5  # 288 km on the march, 1,602 km at sea
    moved, drawn = resolved(r, order(r, "reykjavik"))
    assert moved.bound_for == at(r, "reykjavik") and moved.places == (at(r, "london"),)
    assert moved.arrives == SET_OUT + timedelta(days=days)
    assert [(c.quantity_id, c.value, c.as_of) for c in drawn] == [
        (qid(r.state, POOL), 100_000, SET_OUT)
    ]
    r.fold_changes((moved, *drawn))
    arrive(r, SET_OUT + timedelta(days=days - 1))
    assert pool(r) == 100_000 and feature(r, "home_forces").places == (at(r, "london"),)
    arrive(r, SET_OUT + timedelta(days=days))
    assert feature(r, "home_forces").places == (at(r, "reykjavik"),)
    assert pool(r) == 300_000


def test_a_lift_the_pool_cannot_carry_moves_nothing_and_draws_nothing() -> None:
    r = churchill()
    r.set_value(POOL, 150_000)
    assert movement.order_changes(r.state, order(r, "reykjavik")) == ()
    r.set_value(POOL, 200_000)
    _, drawn = resolved(r, order(r, "reykjavik"))
    assert [c.value for c in drawn] == [0]


def test_germany_has_no_shipping_to_lift_an_army() -> None:
    r = rig(POINTS, seat="hitler")
    found = reach(r.state, feature(r, "army_group_centre"), at(r, "london"))
    assert found is not None and found.tier is Tier.REFUSED and found.reason is not None
    assert "Germany has no shipping" in found.reason and "sealift" in found.reason
    assert bases.lift(r.state, feature(r, "army_group_centre"), at(r, "london")) is None


def test_an_army_lands_only_at_a_port_of_its_side_and_is_told_the_nearest() -> None:
    r = churchill()
    found = reach(r.state, feature(r, "home_forces"), at(r, "pearl_harbor_base"))
    assert found is not None and found.tier is Tier.REFUSED and found.reason is not None
    assert found.base == at(r, "halifax_port")
    assert "Halifax" in found.reason and "sealift" in found.reason
    assert movement.order_changes(r.state, order(r, "pearl_harbor_base")) == ()


def test_an_army_with_no_port_of_its_side_on_its_land_cannot_embark() -> None:
    r = churchill()
    placed(r, "home_forces", "tokyo")
    found = reach(r.state, feature(r, "home_forces"), at(r, "reykjavik"))
    assert found is not None and found.tier is Tier.REFUSED and found.reason is not None
    assert "embark" in found.reason and "sealift" in found.reason


def test_a_lift_whose_sea_way_is_closed_is_refused_with_the_passage_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Leningrad is reached only through the Danish straits, which Germany holds.
    table = {**bases.BASES["autumn-1941"]}
    table["leningrad"] = bases.Base(frozenset({"ussr", "uk"}), frozenset({F, A}))
    monkeypatch.setitem(bases.BASES, "autumn-1941", table)
    r = churchill()
    assert bases.lift(r.state, feature(r, "home_forces"), at(r, "leningrad")) is not None
    uk, germany = at(r, "uk"), at(r, "germany")
    war = War(war_id=war_id_for(uk, germany), a=uk, b=germany, since=FILED, declared_by=uk)
    r.state = r.state.model_copy(update={"wars": {war.war_id: war}})
    found = reach(r.state, feature(r, "home_forces"), at(r, "leningrad"))
    assert found is not None and found.tier is Tier.REFUSED
    assert found.reason is not None and found.reason.startswith(
        "No sea passage open to United Kingdom's fleets reaches Leningrad."
    )
    assert movement.order_changes(r.state, order(r, "leningrad")) == ()


def test_at_reykjavik_home_forces_are_sustained_and_need_a_lift_home() -> None:
    r = churchill()
    placed(r, "home_forces", "reykjavik")
    here = reach(r.state, feature(r, "home_forces"), at(r, "reykjavik"))
    assert here is not None and here.tier is Tier.SUSTAINED
    london = reach(r.state, feature(r, "home_forces"), at(r, "london"))
    assert london is not None and london.tier is Tier.REFUSED and london.reason is not None
    assert "Liverpool" in london.reason and "sealift" in london.reason
    moved, drawn = resolved(r, order(r, "liverpool"))
    assert moved.arrives == SET_OUT + timedelta(
        days=lift_days(r, "reykjavik", "reykjavik", "liverpool")
    )
    assert [c.value for c in drawn] == [100_000]


def test_a_draw_before_the_pools_date_is_dated_the_pools_date() -> None:
    r = churchill()
    later = SET_OUT + timedelta(days=3)
    r.set_value(POOL, 300_000, as_of=later)
    moved, drawn = resolved(r, order(r, "reykjavik"))
    assert [(c.value, c.as_of) for c in drawn] == [(100_000, later)]
    r.fold_changes((moved, *drawn))
    assert r.state.quantities[qid(r.state, POOL)].as_of == later and pool(r) == 100_000


def test_lifts_landing_on_one_day_give_back_both() -> None:
    r = churchill()
    twin = feature(r, "home_forces").model_copy(
        update={"feature_id": FeatureId(r.ids["replacement_army"]), "side": at(r, "uk")}
    )
    r.fold_changes((twin,))
    r.set_value(POOL, 400_000)
    first, drawn = resolved(r, order(r, "reykjavik"))
    r.fold_changes((first, *drawn))
    second, drawn = resolved(r, order(r, "reykjavik", force="replacement_army"))
    r.fold_changes((second, *drawn))
    assert pool(r) == 0 and first.arrives == second.arrives and first.arrives is not None
    landed = movement.day_changes(r.state, first.arrives)
    returned = [c for c in landed if isinstance(c, QuantityChange)]
    assert [(c.value, c.as_of) for c in returned] == [(400_000, first.arrives)]


def test_an_army_called_back_before_it_sails_gives_the_ships_back() -> None:
    r = churchill()
    moved, drawn = resolved(r, order(r, "reykjavik"))
    r.fold_changes((moved, *drawn))
    assert pool(r) == 100_000
    later = [d + timedelta(days=4) for d in COS]
    halted, back = resolved(r, order(r, "london", days=later))
    assert halted.bound_for is None and halted.places == (at(r, "london"),)
    assert [(c.value, c.as_of) for c in back] == [(300_000, later[-1])]


def test_a_march_on_its_own_land_draws_no_shipping() -> None:
    r = churchill()
    moved, drawn = resolved(r, order(r, "liverpool"))
    assert drawn == [] and moved.bound_for == at(r, "liverpool")
    assert bases.lift(r.state, feature(r, "home_forces"), at(r, "liverpool")) is None


def test_an_engine_v2_move_never_ships_an_army_across_the_sea() -> None:
    # The free-text path draws no shipping, so it must not land an army whose arrival
    # would give back a lift never drawn.
    r = churchill()
    home = feature(r, "home_forces").feature_id
    (event,) = _move(PassWorld(r.state), MoveForce(force=home, to=at(r, "reykjavik")), SET_OUT)
    assert isinstance(event, ev.FeatureSet) and event.feature.bound_for is None
    (walk,) = _move(PassWorld(r.state), MoveForce(force=home, to=at(r, "liverpool")), SET_OUT)
    assert isinstance(walk, ev.FeatureSet) and walk.feature.bound_for == at(r, "liverpool")
    # nor halts one on a lift, whose tonnage only its landing or an order gives back
    moved, drawn = resolved(r, order(r, "reykjavik"))
    r.fold_changes((moved, *drawn))
    (held,) = _move(PassWorld(r.state), MoveForce(force=home, to=at(r, "london")), SET_OUT)
    assert isinstance(held, ev.FeatureSet) and held.feature.bound_for == at(r, "reykjavik")


def test_a_stored_game_compiled_without_the_pool_has_no_lift() -> None:
    r = churchill()
    held = {k: q for k, q in r.state.quantities.items() if k != qid(r.state, POOL)}
    r.state = r.state.model_copy(update={"quantities": held})
    found = reach(r.state, feature(r, "home_forces"), at(r, "reykjavik"))
    assert found is not None and found.tier is Tier.REFUSED and found.reason is not None
    assert "United Kingdom has no shipping" in found.reason
    assert movement.order_changes(r.state, order(r, "reykjavik")) == ()
