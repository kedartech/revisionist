"""The reach rule (reach R2): a force is sustained at its side's bases, operates within its
kind's radius of one, raids beyond that up to its raid radius, and is refused past it, with
the reason and the nearest base it can work from. Values from Josh's R2 sheet."""

from datetime import date, timedelta
from typing import Any

import pytest

from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.project import project
from revisionist.core.realism import bases
from revisionist.core.realism.bases import Force, Tier, reach
from revisionist.core.realism.geography import Feature, FeatureKind, Sight
from revisionist.core.realism.resolvers import movement
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.state import State
from tests.test_realism_resolvers import Rig, rig

F, A, R = FeatureKind.FLEET, FeatureKind.ARMY, FeatureKind.AIR
NAVAL = [date(1941, 9, 3), date(1941, 9, 5)]
OCT_FRONT = ("leningrad", "kalinin", "mozhaisk", "kharkov", "taganrog")


def at(r: Rig, key: str) -> EntityId:
    return EntityId(r.ids[key])


def feature(r: Rig, key: str) -> Feature:
    return r.state.features[FeatureId(r.ids[key])]


def placed(r: Rig, key: str, *where: str) -> Feature:
    """Put a feature somewhere in the truth, as history or an arrival would."""
    f = feature(r, key).model_copy(update={"places": tuple(at(r, w) for w in where)})
    r.fold_changes((f,))
    return f


def force(r: Rig, kind: FeatureKind, side: str, where: str) -> Force:
    return Force(kind, at(r, side), at(r, where))


def got(r: Rig, found: bases.Reach | None) -> tuple[Any, ...] | None:
    if found is None:
        return None
    key = {v: k for k, v in r.ids.items()}
    return (found.tier, key.get(found.base) if found.base else None, found.days)


def tier(r: Rig, found: bases.Reach | None) -> Tier | None:
    return None if found is None else found.tier


def at_war(state: State, a: EntityId, b: EntityId) -> State:
    war = War(war_id=war_id_for(a, b), a=a, b=b, since=date(1941, 9, 2), declared_by=a)
    return state.model_copy(update={"wars": {war.war_id: war}})


# --- the sheet's cases -------------------------------------------------------------------


def test_the_strike_from_hitokappu_bay_on_pearl_harbor_is_a_raid() -> None:
    r = Rig()
    fleet = placed(r, "combined_fleet", "hitokappu_bay")
    found = reach(r.state, fleet, at(r, "pearl_harbor_base"))
    assert got(r, found) == (Tier.RAID, "kure", 16)  # 6,847 km from Kure, past 10 days
    assert found is not None and found.reason is None


def test_norfolk_to_reykjavik_is_held_and_by_way_of_argentia_without_its_own_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = Rig()
    fleet = feature(r, "us_atlantic_fleet")
    reykjavik = at(r, "reykjavik")
    assert got(r, reach(r.state, fleet, reykjavik)) == (Tier.SUSTAINED, "reykjavik", 0)
    table = dict(bases.BASES["autumn-1941"])
    table["reykjavik"] = bases.Base(frozenset({"uk"}), frozenset({F, R}))
    monkeypatch.setitem(bases.BASES, "autumn-1941", table)
    # 11 days from Norfolk is past the 10-day radius; 6 from Argentia is within it
    assert got(r, reach(r.state, fleet, reykjavik)) == (Tier.OPERATE, "argentia", 6)
    del table["argentia"]
    assert got(r, reach(r.state, fleet, reykjavik)) == (Tier.RAID, "norfolk", 11)


def test_army_group_centre_reaches_moscow_only_once_the_front_moves_on() -> None:
    r = Rig()
    group = feature(r, "army_group_centre")
    moscow = at(r, "moscow")
    found = reach(r.state, group, moscow)
    assert got(r, found) == (Tier.REFUSED, "smolensk", 15)  # 371 km, past 12 days
    assert found is not None and found.reason is not None
    assert "15 days" in found.reason and "Smolensk" in found.reason
    there = placed(r, "army_group_centre", "vyazma")
    assert got(r, reach(r.state, there, moscow)) == (Tier.OPERATE, "vyazma", 9)
    back = placed(r, "army_group_centre", "smolensk")
    placed(r, "eastern_front", *OCT_FRONT)
    assert got(r, reach(r.state, back, moscow)) == (Tier.OPERATE, "mozhaisk", 5)


def test_a_front_place_is_no_base_for_a_fleet_or_with_no_army_or_front_there() -> None:
    r = Rig()
    placed(r, "eastern_front", *OCT_FRONT)
    group = placed(r, "army_group_centre", "smolensk")
    assert tier(r, reach(r.state, group, at(r, "mozhaisk"))) is Tier.SUSTAINED
    # Vyazma is a front place with no German army and no front there any more
    assert got(r, reach(r.state, group, at(r, "vyazma"))) == (Tier.OPERATE, "mozhaisk", 5)
    soviet = force(r, F, "ussr", "leningrad")
    assert tier(r, reach(r.state, soviet, at(r, "taganrog"))) is not Tier.SUSTAINED


def test_an_army_sent_overseas_is_refused_and_told_it_needs_sealift() -> None:
    r = Rig()
    found = reach(r.state, feature(r, "army_group_centre"), at(r, "london"))
    assert found is not None and found.tier is Tier.REFUSED
    assert found.reason is not None and "sealift" in found.reason
    assert got(r, found) == (Tier.REFUSED, "berlin", 38)  # its nearest base on its own land
    beyond = reach(r.state, feature(r, "army_group_centre"), at(r, "rome"))
    assert beyond is not None and beyond.tier is Tier.REFUSED
    assert beyond.reason is not None and "sealift" not in beyond.reason


def test_a_fleet_beyond_twenty_days_is_refused_and_named_the_nearest_base() -> None:
    r = Rig()
    found = reach(r.state, feature(r, "us_atlantic_fleet"), at(r, "chungking"))
    # Pearl Harbor is 21 days away, Norfolk 42: the nearest is named, not the first
    assert got(r, found) == (Tier.REFUSED, "pearl_harbor_base", 21)
    assert found is not None and found.reason is not None
    assert "Pearl Harbor" in found.reason and "21 days" in found.reason


def test_a_fleet_with_no_open_passage_is_refused_with_that_reason() -> None:
    r = Rig()
    state = at_war(r.state, at(r, "uk"), at(r, "germany"))
    found = reach(state, feature(r, "home_fleet"), at(r, "leningrad"))
    assert found is not None and found.tier is Tier.REFUSED
    assert found.reason is not None and "No sea passage" in found.reason
    assert found.base is not None


def test_a_fleet_reaches_by_its_sea_route_not_the_straight_line() -> None:
    """Liverpool to Odessa is 6 days in a straight line, 13 by Gibraltar and the Straits."""
    r = Rig()
    found = reach(r.state, feature(r, "home_fleet"), at(r, "odessa"))
    assert got(r, found) == (Tier.RAID, "liverpool", 13)


def test_an_air_group_raids_two_days_out_and_no_further() -> None:
    r = Rig()
    group = force(r, R, "usa", "washington")
    assert got(r, reach(r.state, group, at(r, "london"))) == (Tier.RAID, "reykjavik", 2)
    assert tier(r, reach(r.state, group, at(r, "berlin"))) is Tier.REFUSED
    assert got(r, reach(r.state, group, at(r, "norfolk"))) == (Tier.SUSTAINED, "norfolk", 0)


def test_a_world_with_no_table_has_no_reach_rule() -> None:
    r = Rig("engine-v2-slice-1941")
    assert reach(r.state, feature(r, "us_atlantic_fleet"), at(r, "reykjavik")) is None


def test_a_view_reads_fronts_only_from_the_sightings_it_is_given() -> None:
    r = rig(seat="hitler")
    placed(r, "eastern_front", *OCT_FRONT)
    group = force(r, A, "germany", "smolensk")
    moscow = at(r, "moscow")
    assert tier(r, reach(r.state, group, moscow)) is Tier.OPERATE  # by the front at Mozhaisk
    view = project(r.state, r.seats["hitler"])
    assert tier(r, reach(view, group, moscow)) is Tier.REFUSED  # the truth is not read
    page = Sight(kind=FeatureKind.FRONT, places=tuple(at(r, k) for k in OCT_FRONT))
    assert tier(r, reach(view, group, moscow, [page])) is Tier.OPERATE


# --- the movement resolver ---------------------------------------------------------------


def test_the_resolver_refuses_a_move_beyond_reach() -> None:
    r = rig()
    order = r.enact(
        "roosevelt",
        "move_fleet",
        "naval_order",
        NAVAL[0] - timedelta(days=2),
        NAVAL,
        force="us_atlantic_fleet",
        to="chungking",
    )
    assert movement.resolve(r.state, order) == ()
    raid = r.enact(
        "roosevelt",
        "move_fleet",
        "naval_order",
        NAVAL[0] - timedelta(days=2),
        NAVAL,
        force="us_pacific_fleet",
        to="kure",
    )
    (moved,) = movement.resolve(r.state, raid)
    assert isinstance(moved, Feature) and moved.bound_for == at(r, "kure")


def test_the_resolver_holds_army_group_centre_at_smolensk() -> None:
    r = rig(seat="hitler")
    days = [date(1941, 9, 3), date(1941, 9, 5)]
    order = r.enact(
        "hitler",
        "move_army",
        "okw_directive",
        days[0] - timedelta(days=2),
        days,
        force="army_group_centre",
        to="moscow",
    )
    assert movement.resolve(r.state, order) == ()
