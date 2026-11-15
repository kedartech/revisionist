"""Sealift in the place picker (unit SL4 of the sealift plan, decisions 7 and 8).

An army's form lists a place across the sea with the days of the lift (the march to its
port and the voyage at convoy pace) and, beside them, the tonnage the lift needs and its
side's pool as the seat's latest page reporting it gave it: ``None`` before any page has.
A refused crossing carries no lift. Everything shown is read from the seat's own pages,
so a change in the truth that no page reports changes nothing in the picker.
"""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism import bases
from revisionist.core.realism.document import Feed
from revisionist.core.realism.feeds import issue
from revisionist.core.realism.resolvers import qid
from revisionist.core.world_compile import object_id
from revisionist.engine import campaign as cmp
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web.realism_api import PlaceChoice, PlaceLift
from tests.test_realism_resolvers import START, Rig, rig

FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
POOL = "uk_sealift_grt"
POOL_NAME = "British shipping free for troop lift"
ARMY = "home_forces"


def keys(r: Rig) -> dict[EntityId, str]:
    world = cmp.load_world(cmp.world_path("autumn-1941"))
    return {
        EntityId(object_id(r.campaign, "entity", e.key)): e.key
        for e in world.entities
        if e.at is not None
    }


def feed_named(r: Rig, name: str) -> Feed:
    (feed,) = [f for f in r.state.feeds.values() if f.name == name]
    return feed


def page(
    r: Rig, name: str, days_before: int, sights: tuple[str, ...] = (), report: bool = True
) -> ev.DocumentIssued:
    """Feed ``name`` issues a page ``days_before`` the seat's date (arrived by then),
    sighting ``sights`` beside its own, and with the pool's line unless ``report`` is false."""
    feed = feed_named(r, name)
    extra = tuple(FeatureId(r.ids[k]) for k in sights)
    reports = feed.reports if report else tuple(q for q in feed.reports if q != qid(r.state, POOL))
    feed = feed.model_copy(update={"sights": feed.sights + extra, "reports": reports})
    doc = issue(r.state, feed, START - timedelta(days=days_before), f"seed-{name}-{days_before}")
    assert doc is not None
    r.add(doc)
    return doc


def pool_line(doc: ev.DocumentIssued) -> int:
    (line,) = [b for b in doc.document.body if b.label == POOL_NAME]
    assert isinstance(line.value, int)
    return line.value


def places(r: Rig, seat: str = "churchill", lever: str = "move_army") -> dict[str, dict[str, Any]]:
    block = rs.seat_realism(r.state, r.seats[seat], set(), set(), None, keys(r))
    form = next(x for x in block["desk"]["levers"] if x["name"] == lever)
    to = next(p for p in form["params"] if p["name"] == "to")
    return {p["value"]: p for p in to["places"]}


def churchill_placed() -> tuple[Rig, ev.DocumentIssued]:
    """Churchill seated, with an Admiralty page that places Home Forces in London."""
    r = rig(seat="churchill")
    return r, page(r, "Admiralty reports", 2, sights=(ARMY,))


def test_churchills_army_form_lists_reykjavik_by_sea_with_the_need_and_his_reported_pool() -> None:
    r, doc = churchill_placed()
    home = r.state.features[FeatureId(r.ids[ARMY])]
    lift = bases.lift(r.state, home, EntityId(r.ids["reykjavik"]))
    assert lift is not None
    reykjavik = places(r)["reykjavik"]
    assert reykjavik["days"] == {ARMY: lift.days}
    assert reykjavik["reach"][ARMY]["tier"] == "sustained"
    assert reykjavik["lift"] == {ARMY: {"need": 200_000, "reported": pool_line(doc)}}


def test_before_any_page_reports_the_pool_reported_is_null() -> None:
    r = rig(seat="churchill")
    page(r, "Admiralty reports", 2, sights=(ARMY,), report=False)
    assert places(r)["reykjavik"]["lift"] == {ARMY: {"need": 200_000, "reported": None}}


def test_the_latest_page_reporting_the_pool_gives_the_figure() -> None:
    r, _ = churchill_placed()
    r.set_value(POOL, 120_000, START)
    later = page(r, "Admiralty reports", 1)
    lift = places(r)["reykjavik"]["lift"][ARMY]
    assert lift["reported"] == pool_line(later)
    assert pool_line(later) < 200_000  # the later page's figure, not the first page's


def test_a_place_on_the_armys_own_land_carries_no_lift() -> None:
    r, _ = churchill_placed()
    shown = places(r)
    assert shown["liverpool"]["lift"] == {ARMY: None}
    assert shown["london"]["lift"] == {ARMY: None}


def test_a_refused_landing_carries_no_lift() -> None:
    r, _ = churchill_placed()
    pearl = places(r)["pearl_harbor_base"]
    assert pearl["reach"][ARMY]["tier"] == "refused"
    assert pearl["lift"] == {ARMY: None}


def test_a_seat_with_no_pool_sees_the_refusal_and_no_lift() -> None:
    r = rig(seat="hitler")
    page(r, "OKW situation reports", 2)
    london = places(r, "hitler")["london"]
    agc = "army_group_centre"
    assert london["reach"][agc]["tier"] == "refused"
    assert "sealift" in london["reach"][agc]["reason"]
    assert "no shipping" in london["reach"][agc]["reason"]
    assert london["lift"] == {agc: None}


def test_a_force_no_page_places_has_no_lift() -> None:
    r = rig(seat="churchill")
    assert places(r)["reykjavik"]["lift"] == {ARMY: None}


def test_a_truth_change_with_no_page_changes_nothing_in_the_picker() -> None:
    r, _ = churchill_placed()
    before = places(r)
    assert before["reykjavik"]["lift"][ARMY] is not None
    r.set_value(POOL, 10_000, START)
    home = r.state.features[FeatureId(r.ids[ARMY])]
    r.fold_changes((home.model_copy(update={"places": (EntityId(r.ids["liverpool"]),)}),))
    assert places(r) == before


def test_every_fixture_place_carries_a_lift_per_force_in_the_api_shape() -> None:
    levers = json.loads(FIXTURE.read_text())["desk"]["levers"]
    shown = [x for lever in levers for p in lever["params"] for x in p["places"]]
    assert shown
    for place in shown:
        assert set(place) == set(PlaceChoice.__annotations__)
        assert set(place["lift"]) == set(place["days"])
        for lift in place["lift"].values():
            assert lift is None or set(lift) == set(PlaceLift.__annotations__)
