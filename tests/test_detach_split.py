"""Splitting a fleet and its rejoining (reach R4, unit D2; plan decisions 1, 3 to 6 and 9).

An enacted movement order that names a strength sends that much of the force's tier to
another place as a detachment, a force of its own; the rest stays where it is. A side has
at most ``DETACHMENTS_PER_SIDE`` detachments of a kind in play, and a parent keeps at
least strength 1. A detachment that stands still where its parent stands still merges
back: its tier returns to the parent (to at most 5) and it leaves play.
"""

from datetime import date, timedelta

from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism import detachments
from revisionist.core.realism.bases import Tier, reach
from revisionist.core.realism.geography import Feature, FeatureKind, in_play
from revisionist.core.realism.resolvers import movement
from revisionist.core.realism.routing import travel_days
from revisionist.core.world_compile import object_id
from tests.test_realism_resolvers import Rig, rig

DAY = date(1941, 9, 10)
"""The day the first order settles."""


def at(r: Rig, key: str) -> EntityId:
    return EntityId(r.ids[key])


def fid(r: Rig, key: str) -> FeatureId:
    return FeatureId(object_id(r.campaign, "feature", key))


def feature(r: Rig, key: str) -> Feature:
    return r.state.features[fid(r, key)]


def order(r: Rig, settled: date, seat: str = "roosevelt", **params: object) -> tuple[Feature, ...]:
    """What the movement resolver makes of ``seat``'s enacted order settling on ``settled``."""
    enacted = r.enact(
        seat,
        "detach_fleet" if "strength" in params else "move_fleet",
        "naval_order",
        settled - timedelta(days=4),
        [settled - timedelta(days=2), settled],
        **params,
    )
    return movement.resolve(r.state, enacted)


def detach(
    r: Rig, force: str, to: str, strength: object, settled: date = DAY, **kw: str
) -> tuple[Feature, ...]:
    out = order(r, settled, force=force, to=to, strength=strength, **kw)
    r.fold_changes(out)
    return out


def move(r: Rig, force: str, to: str, settled: date) -> Feature:
    (out,) = order(r, settled, force=force, to=to)
    r.fold_changes((out,))
    return out


def day(r: Rig, today: date) -> tuple[Feature, ...]:
    out = movement.on_day(r.state, today)
    r.fold_changes(out)
    return out


def arrive(r: Rig, key: str) -> date:
    """Run the day ``key`` arrives; return that day."""
    when = feature(r, key).arrives
    assert when is not None
    day(r, when)
    return when


def two_seats() -> Rig:
    r = Rig()
    r.seat("roosevelt")
    r.seat("churchill")
    r.close_session_zero()
    return r


# --- the split ----------------------------------------------------------------------------


def test_roosevelt_detaches_strength_2_of_the_atlantic_fleet_to_argentia() -> None:
    r = rig()
    before = feature(r, "us_atlantic_fleet")
    parent, part = detach(r, "us_atlantic_fleet", "argentia", 2)
    assert parent == before.model_copy(update={"tier": 2, "as_of": DAY})
    days = travel_days(r.state, before, at(r, "argentia"))
    assert days is not None
    assert part.feature_id == fid(r, "us_atlantic_fleet__d1")
    assert part.name == "US Atlantic Fleet detachment 1"
    assert (part.kind, part.side, part.tier) == (FeatureKind.FLEET, at(r, "usa"), 2)
    assert part.detached_from == before.feature_id and part.rejoined_on is None
    assert part.places == (at(r, "norfolk"),) and part.legs == ()
    assert (part.bound_for, part.arrives, part.as_of) == (
        at(r, "argentia"),
        DAY + timedelta(days=days),
        DAY,
    )
    arrive(r, "us_atlantic_fleet__d1")
    assert feature(r, "us_atlantic_fleet__d1").places == (at(r, "argentia"),)
    assert feature(r, "us_atlantic_fleet").places == (at(r, "norfolk"),)
    assert feature(r, "us_atlantic_fleet").tier == 2


def test_a_strength_given_as_text_is_read_as_a_number() -> None:
    r = rig()
    parent, part = detach(r, "us_atlantic_fleet", "argentia", "3")
    assert (parent.tier, part.tier) == (1, 3)


def test_a_split_to_a_refused_place_makes_nothing_and_moves_nothing() -> None:
    r = rig()
    fleet = feature(r, "us_atlantic_fleet")
    found = reach(r.state, fleet, at(r, "chungking"))
    assert found is not None and found.tier is Tier.REFUSED
    assert order(r, DAY, force="us_atlantic_fleet", to="chungking", strength=2) == ()


def test_a_split_to_where_the_force_already_is_makes_nothing() -> None:
    r = rig()
    assert order(r, DAY, force="us_atlantic_fleet", to="norfolk", strength=2) == ()


def test_a_split_that_would_leave_the_parent_below_strength_1_is_refused() -> None:
    r = rig()
    assert order(r, DAY, force="us_atlantic_fleet", to="argentia", strength=4) == ()
    assert order(r, DAY, force="us_atlantic_fleet", to="argentia", strength=0) == ()
    assert order(r, DAY, force="us_atlantic_fleet", to="argentia", strength="two") == ()
    assert len(order(r, DAY, force="us_atlantic_fleet", to="argentia", strength=3)) == 2


def test_a_third_live_us_fleet_detachment_is_refused_but_another_side_may_still_split() -> None:
    r = two_seats()
    detach(r, "us_atlantic_fleet", "argentia", 1)
    detach(r, "us_pacific_fleet", "argentia", 1)
    assert detachments.DETACHMENTS_PER_SIDE[FeatureKind.FLEET] == 2
    assert order(r, DAY, force="us_atlantic_fleet", to="argentia", strength=1) == ()
    assert order(r, DAY, force="us_pacific_fleet", to="argentia", strength=1) == ()
    uk = order(r, DAY, seat="churchill", force="home_fleet", to="reykjavik", strength=1)
    assert [f.feature_id for f in uk] == [fid(r, "home_fleet"), fid(r, "home_fleet__d1")]


def test_the_cap_table_allows_no_army_detachment_and_one_air_group() -> None:
    assert detachments.DETACHMENTS_PER_SIDE == {
        FeatureKind.FLEET: 2,
        FeatureKind.ARMY: 0,
        FeatureKind.AIR: 1,
    }


def test_slots_are_numbered_per_parent_from_1() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "argentia", 1)
    _, second = detach(r, "us_atlantic_fleet", "reykjavik", 1)
    assert second.feature_id == fid(r, "us_atlantic_fleet__d2")
    assert second.name == "US Atlantic Fleet detachment 2"


def test_a_detachment_is_not_split_again() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "argentia", 3)
    arrive(r, "us_atlantic_fleet__d1")
    assert (
        order(
            r, DAY + timedelta(days=10), force="us_atlantic_fleet__d1", to="reykjavik", strength=1
        )
        == ()
    )


def test_only_the_issuers_side_splits() -> None:
    r = rig()
    assert order(r, DAY, force="home_fleet", to="reykjavik", strength=1) == ()


def test_a_long_name_is_cut_to_fit_and_keeps_the_slot_number() -> None:
    r = rig()
    long = feature(r, "us_atlantic_fleet").model_copy(update={"name": "N" * 60, "as_of": DAY})
    r.fold_changes((long,))
    _, part = detach(r, "us_atlantic_fleet", "argentia", 1)
    assert len(part.name) == 60 and part.name.endswith(" detachment 1")


# --- the raid clock -----------------------------------------------------------------------


def test_a_detachment_sent_to_a_raid_place_starts_the_raid_clock_and_turns_for_base() -> None:
    r = rig()
    _, part = detach(r, "us_atlantic_fleet", "rome", 2)
    assert part.left_base_on == DAY
    arrive(r, "us_atlantic_fleet__d1")
    assert feature(r, "us_atlantic_fleet__d1").left_base_on == DAY
    back = {f.feature_id: f for f in movement.on_day(r.state, DAY + timedelta(days=31))}
    turned = back[fid(r, "us_atlantic_fleet__d1")]
    assert turned.bound_for == at(r, "reykjavik")
    assert fid(r, "us_atlantic_fleet") not in back


# --- the rejoin ---------------------------------------------------------------------------


def test_the_detachment_sent_back_to_norfolk_merges_on_arrival() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "argentia", 2)
    there = arrive(r, "us_atlantic_fleet__d1")
    move(r, "us_atlantic_fleet__d1", "norfolk", there + timedelta(days=1))
    home = feature(r, "us_atlantic_fleet__d1").arrives
    assert home is not None
    out = {f.feature_id: f for f in day(r, home)}
    assert set(out) == {fid(r, "us_atlantic_fleet"), fid(r, "us_atlantic_fleet__d1")}
    parent, part = feature(r, "us_atlantic_fleet"), feature(r, "us_atlantic_fleet__d1")
    assert (parent.tier, parent.as_of) == (4, home)
    assert part.rejoined_on == home and part.as_of == home
    assert part.places == (at(r, "norfolk"),) and part.bound_for is None
    assert not in_play(part)
    after = {f.feature_id for f in movement.on_day(r.state, home + timedelta(days=1))}
    assert not after & set(out)


def test_the_parent_arriving_where_its_detachment_stands_merges() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "argentia", 2)
    there = arrive(r, "us_atlantic_fleet__d1")
    move(r, "us_atlantic_fleet", "argentia", there + timedelta(days=1))
    when = arrive(r, "us_atlantic_fleet")
    parent, part = feature(r, "us_atlantic_fleet"), feature(r, "us_atlantic_fleet__d1")
    assert parent.places == (at(r, "argentia"),) and parent.tier == 4
    assert part.rejoined_on == when


def test_two_detachments_merging_on_one_day_both_return_their_strength() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "argentia", 1)
    detach(r, "us_atlantic_fleet", "argentia", 2, DAY + timedelta(days=1))
    arrive(r, "us_atlantic_fleet__d1")
    there = feature(r, "us_atlantic_fleet__d2").arrives
    assert there is not None
    day(r, there)
    assert feature(r, "us_atlantic_fleet").tier == 1
    move(r, "us_atlantic_fleet", "argentia", there + timedelta(days=1))
    arrive(r, "us_atlantic_fleet")
    assert feature(r, "us_atlantic_fleet").tier == 4
    assert not in_play(feature(r, "us_atlantic_fleet__d1"))
    assert not in_play(feature(r, "us_atlantic_fleet__d2"))


def test_a_detachment_under_way_from_its_parents_place_does_not_merge() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "argentia", 2)
    assert movement.on_day(r.state, DAY + timedelta(days=1)) == ()
    assert in_play(feature(r, "us_atlantic_fleet__d1"))


def test_a_detachment_does_not_merge_into_a_parent_under_way() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "argentia", 2)
    there = arrive(r, "us_atlantic_fleet__d1")
    move(r, "us_atlantic_fleet__d1", "norfolk", there + timedelta(days=1))
    home = feature(r, "us_atlantic_fleet__d1").arrives
    assert home is not None
    move(r, "us_atlantic_fleet", "reykjavik", home - timedelta(days=1))
    day(r, home)
    assert in_play(feature(r, "us_atlantic_fleet__d1"))
    assert feature(r, "us_atlantic_fleet").tier == 2


def test_a_merge_brings_the_parent_to_at_most_strength_5() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "argentia", 2)
    there = arrive(r, "us_atlantic_fleet__d1")
    move(r, "us_atlantic_fleet__d1", "norfolk", there + timedelta(days=1))
    home = feature(r, "us_atlantic_fleet__d1").arrives
    assert home is not None
    r.fold_changes((feature(r, "us_atlantic_fleet").model_copy(update={"tier": 4, "as_of": home}),))
    day(r, home)
    assert feature(r, "us_atlantic_fleet").tier == 5


def test_a_rejoined_slot_is_reused_and_no_longer_counts_against_the_cap() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "argentia", 1)
    detach(r, "us_atlantic_fleet", "reykjavik", 1)
    there = arrive(r, "us_atlantic_fleet__d1")
    move(r, "us_atlantic_fleet__d1", "norfolk", there + timedelta(days=1))
    home = arrive(r, "us_atlantic_fleet__d1")
    assert not in_play(feature(r, "us_atlantic_fleet__d1"))
    _, again = detach(r, "us_atlantic_fleet", "argentia", 1, home + timedelta(days=1))
    assert again.feature_id == fid(r, "us_atlantic_fleet__d1")
    assert again.rejoined_on is None and again.tier == 1
    assert again.as_of == home + timedelta(days=1)
    assert in_play(feature(r, "us_atlantic_fleet__d1"))


def test_a_reused_slot_never_steps_back_in_time() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "argentia", 1)
    there = arrive(r, "us_atlantic_fleet__d1")
    move(r, "us_atlantic_fleet__d1", "norfolk", there + timedelta(days=1))
    home = arrive(r, "us_atlantic_fleet__d1")
    _, again = detach(r, "us_atlantic_fleet", "argentia", 1, home - timedelta(days=3))
    assert again.as_of == home
    days = travel_days(r.state, feature(r, "us_atlantic_fleet"), at(r, "argentia"))
    assert days is not None and again.arrives == home + timedelta(days=days)


# --- out of play --------------------------------------------------------------------------


def test_a_rejoined_detachment_is_not_turned_for_base_or_moved_by_an_order() -> None:
    r = rig()
    detach(r, "us_atlantic_fleet", "rome", 2)
    move(r, "us_atlantic_fleet", "rome", DAY + timedelta(days=1))
    arrive(r, "us_atlantic_fleet__d1")
    when = arrive(r, "us_atlantic_fleet")
    part = feature(r, "us_atlantic_fleet__d1")
    assert part.rejoined_on == when and part.left_base_on is not None
    later = DAY + timedelta(days=40)
    ids = {f.feature_id for f in movement.on_day(r.state, later)}
    assert fid(r, "us_atlantic_fleet__d1") not in ids
    assert order(r, later, force="us_atlantic_fleet__d1", to="reykjavik") == ()


def test_a_world_with_no_detachment_moves_as_before() -> None:
    r = rig()
    (out,) = order(r, DAY, force="us_atlantic_fleet", to="argentia")
    assert out.feature_id == fid(r, "us_atlantic_fleet") and out.tier == 4
    assert out.bound_for == at(r, "argentia")
