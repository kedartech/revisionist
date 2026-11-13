"""Sea routing (reach, R3): fleets sail by sea, through the passages open to their side."""

import math
from datetime import date, timedelta

from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism.geography import SPEED_KM_PER_DAY, FeatureKind, km_between
from revisionist.core.realism.resolvers import movement
from revisionist.core.realism.routing import sea_route, travel_days
from revisionist.core.realism.war import War, war_id_for
from tests.test_realism_resolvers import Rig, rig

NAVAL = [date(1941, 9, 3), date(1941, 9, 5)]


def place(r: Rig, key: str) -> EntityId:
    return EntityId(r.ids[key])


def at(r: Rig, key: str) -> tuple[float, float]:
    where = r.state.entities[place(r, key)].at
    assert where is not None
    return where


def fleet(r: Rig, key: str) -> FeatureId:
    return FeatureId(r.ids[key])


def war(r: Rig, a: str, b: str) -> None:
    ea, eb = place(r, a), place(r, b)
    r.fold_changes((War(war_id=war_id_for(ea, eb), a=ea, b=eb, since=NAVAL[0], declared_by=ea),))


def straight_days(r: Rig, a: str, b: str) -> int:
    return max(1, math.ceil(km_between(at(r, a), at(r, b)) / SPEED_KM_PER_DAY[FeatureKind.FLEET]))


def test_norfolk_to_pearl_harbor_goes_by_panama_and_takes_longer_than_the_straight_line() -> None:
    r = rig()
    route = sea_route(r.state, place(r, "usa"), at(r, "norfolk"), at(r, "pearl_harbor_base"))
    assert route is not None and route.via == ("panama",)
    assert route.km > km_between(at(r, "norfolk"), at(r, "pearl_harbor_base"))
    order = r.enact(
        "roosevelt",
        "move_fleet",
        "naval_order",
        NAVAL[0] - timedelta(days=2),
        NAVAL,
        force="us_atlantic_fleet",
        to="pearl_harbor_base",
    )
    r.fold_changes(movement.resolve(r.state, order))
    sailing = r.state.features[fleet(r, "us_atlantic_fleet")]
    days = math.ceil(route.km / SPEED_KM_PER_DAY[FeatureKind.FLEET])
    assert sailing.arrives == NAVAL[-1] + timedelta(days=days)
    assert days > straight_days(r, "norfolk", "pearl_harbor_base")


def test_the_route_is_the_shortest_over_the_whole_way_not_to_the_last_door() -> None:
    r = rig()
    route = sea_route(r.state, place(r, "japan"), at(r, "kure"), at(r, "liverpool"))
    assert route is not None
    assert route.via == ("malacca", "bab_el_mandeb", "suez", "gibraltar")


def test_a_move_inside_one_sea_keeps_the_straight_line() -> None:
    r = rig()
    route = sea_route(r.state, place(r, "usa"), at(r, "norfolk"), at(r, "reykjavik"))
    assert route == (km_between(at(r, "norfolk"), at(r, "reykjavik")), ())


def test_a_passage_held_by_a_power_at_war_with_the_fleet_is_closed() -> None:
    r = rig()
    open_ = sea_route(r.state, place(r, "japan"), at(r, "kure"), at(r, "norfolk"))
    assert open_ is not None and open_.via == ("panama",)
    war(r, "japan", "usa")
    closed = sea_route(r.state, place(r, "japan"), at(r, "kure"), at(r, "norfolk"))
    assert closed is not None and "panama" not in closed.via
    assert closed.km > open_.km


def test_a_passage_stays_open_to_the_side_that_holds_it() -> None:
    r = rig()
    war(r, "japan", "usa")
    route = sea_route(r.state, place(r, "usa"), at(r, "norfolk"), at(r, "pearl_harbor_base"))
    assert route is not None and route.via == ("panama",)


def test_a_fleet_with_every_sea_route_closed_does_not_sail() -> None:
    r = rig(seat="churchill")
    war(r, "uk", "germany")
    home = r.state.features[fleet(r, "home_fleet")]
    assert sea_route(r.state, place(r, "uk"), at(r, "scapa_flow"), at(r, "leningrad")) is None
    assert travel_days(r.state, home, place(r, "leningrad")) is None
    order = r.enact(
        "churchill",
        "move_fleet",
        "cos_directive",
        NAVAL[0] - timedelta(days=2),
        NAVAL,
        force="home_fleet",
        to="leningrad",
    )
    assert movement.resolve(r.state, order) == ()


def test_armies_march_the_straight_line_even_between_seas() -> None:
    r = rig()
    group = r.state.features[fleet(r, "army_group_centre")]
    km = km_between(at(r, "smolensk"), at(r, "kiev"))
    assert travel_days(r.state, group, place(r, "kiev")) == math.ceil(
        km / SPEED_KM_PER_DAY[FeatureKind.ARMY]
    )
