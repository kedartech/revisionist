"""The raid time limit (reach R2B): a fleet or air group at a raid place turns for its
nearest base once it has been away from its bases longer than its kind may stay out (a
fleet 30 days, an air group 3; Josh's R2 sheet). The clock runs from the day the force
left a base, holds while it moves between places that are not bases, and stops when it
reaches one. Armies carry no clock."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId, derived_id
from revisionist.core.realism.arrivals import arrivals
from revisionist.core.realism.document import DocumentKind
from revisionist.core.realism.geography import Feature, FeatureKind
from revisionist.core.realism.resolvers import movement
from revisionist.core.realism.routing import travel_days
from revisionist.core.visibility import private_to
from tests.test_realism_resolvers import START, Rig, rig

OUT = date(1941, 9, 6)
"""The day the force left its base."""


def at(r: Rig, key: str) -> EntityId:
    return EntityId(r.ids[key])


def feature(r: Rig, key: str) -> Feature:
    return r.state.features[FeatureId(r.ids[key])]


def away(r: Rig, key: str, where: str, since: date | None, **update: object) -> Feature:
    """Put a force at ``where``, away from its bases since ``since``."""
    f = feature(r, key).model_copy(
        update={"places": (at(r, where),), "legs": (), "left_base_on": since, **update}
    )
    r.fold_changes((f,))
    return feature(r, key)


def on_day(r: Rig, key: str, today: date) -> Feature | None:
    """The force as the movement resolver leaves it today; None when it is untouched."""
    fid = FeatureId(r.ids[key])
    return next((f for f in movement.on_day(r.state, today) if f.feature_id == fid), None)


def day(r: Rig, today: date) -> None:
    r.fold_changes(movement.on_day(r.state, today))


def sail(r: Rig, fleet: str, to: str, settled: date) -> Feature:
    """Roosevelt's order sends ``fleet`` to ``to``; it sets out on ``settled``."""
    order = r.enact(
        "roosevelt",
        "move_fleet",
        "naval_order",
        settled - timedelta(days=4),
        [settled - timedelta(days=2), settled],
        force=fleet,
        to=to,
    )
    r.fold_changes(movement.resolve(r.state, order))
    return feature(r, fleet)


def air_group(r: Rig, where: str) -> str:
    """An American air group at ``where`` (the world has none of its own)."""
    fid = FeatureId(derived_id(r.campaign, "test-feature", "air_group"))
    r.fold_changes(
        (
            Feature(
                feature_id=fid,
                kind=FeatureKind.AIR,
                name="Air group",
                side=at(r, "usa"),
                places=(at(r, where),),
                as_of=START,
            ),
        )
    )
    r.ids["air_group"] = fid
    return "air_group"


# --- the limit ----------------------------------------------------------------------------


def test_kido_butai_holds_pearl_harbor_through_day_30_and_turns_for_kure_on_day_31() -> None:
    r = Rig()
    fleet = away(r, "combined_fleet", "pearl_harbor_base", OUT)
    assert on_day(r, "combined_fleet", OUT + timedelta(days=30)) is None
    today = OUT + timedelta(days=31)
    back = on_day(r, "combined_fleet", today)
    kure = at(r, "kure")
    days = travel_days(r.state, fleet, kure)
    assert back is not None and days is not None
    assert back.places == (at(r, "pearl_harbor_base"),)
    assert back.bound_for == kure and back.arrives == today + timedelta(days=days)
    assert back.as_of == today and back.legs == ()
    assert back.left_base_on == OUT


def test_an_air_group_at_a_raid_place_returns_to_its_nearest_base_on_day_4() -> None:
    r = Rig()
    key = air_group(r, "london")
    away(r, key, "london", OUT)
    assert on_day(r, key, OUT + timedelta(days=3)) is None
    back = on_day(r, key, OUT + timedelta(days=4))
    assert back is not None and back.bound_for == at(r, "reykjavik")


def test_the_force_turns_for_the_base_nearest_where_it_is_not_the_one_it_left() -> None:
    r = Rig()
    away(r, "us_atlantic_fleet", "rome", OUT)
    back = on_day(r, "us_atlantic_fleet", OUT + timedelta(days=31))
    assert back is not None and back.bound_for == at(r, "reykjavik")


def test_a_raider_that_hops_between_raid_places_keeps_one_clock() -> None:
    r = rig()
    left = date(1941, 9, 5)
    out = sail(r, "us_pacific_fleet", "hitokappu_bay", left)
    assert out.left_base_on == left
    assert out.arrives is not None
    day(r, out.arrives)
    assert feature(r, "us_pacific_fleet").left_base_on == left
    on = sail(r, "us_pacific_fleet", "kure", out.arrives + timedelta(days=3))
    assert on.left_base_on == left
    assert on.arrives is not None and on.arrives < left + timedelta(days=30)
    day(r, on.arrives)
    assert feature(r, "us_pacific_fleet").places == (at(r, "kure"),)
    assert feature(r, "us_pacific_fleet").left_base_on == left
    assert on_day(r, "us_pacific_fleet", left + timedelta(days=30)) is None
    back = on_day(r, "us_pacific_fleet", left + timedelta(days=31))
    assert back is not None and back.bound_for == at(r, "pearl_harbor_base")


def test_a_force_halted_at_the_base_it_was_leaving_has_no_clock() -> None:
    r = rig()
    out = sail(r, "us_pacific_fleet", "kure", OUT)
    assert out.left_base_on == OUT
    halted = sail(r, "us_pacific_fleet", "pearl_harbor_base", OUT + timedelta(days=3))
    assert halted.bound_for is None and halted.left_base_on is None
    again = sail(r, "us_pacific_fleet", "kure", OUT + timedelta(days=20))
    assert again.left_base_on == OUT + timedelta(days=20)


def test_reaching_a_base_stops_the_clock() -> None:
    r = Rig()
    away(r, "combined_fleet", "pearl_harbor_base", OUT)
    today = OUT + timedelta(days=31)
    day(r, today)
    back = feature(r, "combined_fleet")
    assert back.arrives is not None
    day(r, back.arrives)
    home = feature(r, "combined_fleet")
    assert home.places == (at(r, "kure"),) and home.left_base_on is None
    assert home.model_dump().keys() == Rig().state.features[home.feature_id].model_dump().keys()


def test_a_game_saved_before_the_limit_starts_the_clock_on_the_forces_first_move() -> None:
    r = rig()
    away(r, "us_pacific_fleet", "kure", None)
    assert on_day(r, "us_pacific_fleet", date(1942, 3, 1)) is None
    left = date(1942, 3, 2)
    on = sail(r, "us_pacific_fleet", "tokyo", left)
    assert on.left_base_on == left and on.arrives is not None
    day(r, on.arrives)
    assert on_day(r, "us_pacific_fleet", left + timedelta(days=30)) is None
    back = on_day(r, "us_pacific_fleet", left + timedelta(days=31))
    assert back is not None and back.bound_for == at(r, "pearl_harbor_base")


def test_a_force_with_no_clock_that_arrives_from_a_base_counts_from_the_day_it_set_out() -> None:
    r = Rig()
    arrives = OUT + timedelta(days=16)
    away(r, "combined_fleet", "kure", None, bound_for=at(r, "pearl_harbor_base"), arrives=arrives)
    r.fold_changes((feature(r, "combined_fleet").model_copy(update={"as_of": OUT}),))
    day(r, arrives)
    assert feature(r, "combined_fleet").left_base_on == OUT


def test_history_moving_kido_butai_out_of_kure_starts_its_clock_that_day() -> None:
    r = Rig()
    leg = date(1941, 11, 22)
    day(r, leg)
    fleet = feature(r, "combined_fleet")
    assert fleet.places == (at(r, "hitokappu_bay"),) and fleet.left_base_on == leg


def test_a_force_with_no_clock_that_arrives_from_elsewhere_counts_from_its_arrival() -> None:
    r = Rig()
    arrives = OUT + timedelta(days=5)
    away(
        r,
        "combined_fleet",
        "hitokappu_bay",
        None,
        bound_for=at(r, "pearl_harbor_base"),
        arrives=arrives,
    )
    day(r, arrives)
    assert feature(r, "combined_fleet").left_base_on == arrives


def test_an_order_on_to_another_raid_place_does_not_outrun_the_limit() -> None:
    r = Rig()
    tokyo = at(r, "tokyo")
    later = OUT + timedelta(days=40)
    away(r, "us_pacific_fleet", "kure", OUT, bound_for=tokyo, arrives=later)
    back = on_day(r, "us_pacific_fleet", OUT + timedelta(days=31))
    assert back is not None and back.bound_for == at(r, "pearl_harbor_base")


def test_a_force_already_bound_for_a_base_is_left_on_its_course() -> None:
    r = Rig()
    norfolk = at(r, "norfolk")
    later = OUT + timedelta(days=60)
    away(r, "us_pacific_fleet", "kure", OUT, bound_for=norfolk, arrives=later)
    assert on_day(r, "us_pacific_fleet", OUT + timedelta(days=31)) is None


def test_a_force_at_a_base_or_within_its_operating_radius_never_turns() -> None:
    r = Rig()
    long_after = OUT + timedelta(days=200)
    away(r, "us_atlantic_fleet", "halifax_port", OUT)
    assert on_day(r, "us_atlantic_fleet", long_after) is None
    away(r, "us_pacific_fleet", "argentia", OUT)
    assert on_day(r, "us_pacific_fleet", long_after) is None


def test_an_army_carries_no_clock() -> None:
    r = rig(seat="hitler")
    left = date(1941, 9, 5)
    order = r.enact(
        "hitler",
        "move_army",
        "okw_directive",
        left - timedelta(days=4),
        [left - timedelta(days=2), left],
        force="army_group_centre",
        to="vyazma",
    )
    r.fold_changes(movement.resolve(r.state, order))
    army = feature(r, "army_group_centre")
    assert army.bound_for == at(r, "vyazma")
    assert army.model_dump().get("left_base_on") is None
    assert army.arrives is not None
    day(r, army.arrives)
    assert feature(r, "army_group_centre").model_dump().get("left_base_on") is None


def test_a_world_with_no_bases_table_turns_nothing() -> None:
    r = Rig()
    away(r, "combined_fleet", "pearl_harbor_base", OUT)
    world = r.state.model_copy(
        update={"entities": {k: v for k, v in r.state.entities.items() if k != at(r, "scapa_flow")}}
    )
    assert [f for f in movement.on_day(world, OUT + timedelta(days=60)) if f.bound_for] == []


# --- the paper ----------------------------------------------------------------------------


def test_the_commanding_seat_is_told_why_its_fleet_turns_for_base() -> None:
    r = rig()
    away(r, "us_pacific_fleet", "kure", OUT)
    today = OUT + timedelta(days=31)
    before = r.state
    day(r, today)
    (p,) = arrivals(before, r.state, today)
    assert isinstance(p, ev.DocumentIssued)
    doc = p.document
    assert doc.scope == private_to(r.seats["roosevelt"])
    assert doc.kind is DocumentKind.REPORT and doc.issued == today
    assert doc.title == "US Pacific Fleet turns for Pearl Harbor"
    lines = {f.label: f.value for f in doc.body}
    assert lines["Position"] == "Kure" and lines["Bound for"] == "Pearl Harbor"
    assert lines["Why"] == "31 days from base, past the 30 it can stay out"
    assert p.truth.sightings[0].feature_id == FeatureId(r.ids["us_pacific_fleet"])


def test_an_ordered_move_gets_no_turn_report() -> None:
    r = rig()
    sail(r, "us_pacific_fleet", "kure", OUT)
    before = r.state
    day(r, OUT + timedelta(days=1))
    assert arrivals(before, r.state, OUT + timedelta(days=1)) == []
