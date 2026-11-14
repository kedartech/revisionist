"""Detachments on paper and in command (reach R4, unit D3): sighted with their parent,
reported to its commander, out of every rule once rejoined, and refused at filing past the
cap or past the parent's strength."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, FeatureId, FeedId, SeatId
from revisionist.core.realism import apply as rapply
from revisionist.core.realism import effect as rx
from revisionist.core.realism import feeds as rf
from revisionist.core.realism import war_rules
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.document import Bias, Feed
from revisionist.core.realism.geography import Feature, FeatureKind
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.state import State
from revisionist.core.world_compile import object_id
from tests.test_engine_v2_contract import CAMPAIGN as SLICE_CAMPAIGN
from tests.test_engine_v2_contract import Slice
from tests.test_realism_resolvers import CAMPAIGN, START, Rig
from tests.test_war_rules import DAY, declared, slice_with

LATER = START + timedelta(days=3)


def detachment(
    state: State,
    campaign: CampaignId,
    parent_key: str,
    place: EntityId,
    n: int = 1,
    rejoined: date | None = None,
) -> Feature:
    """The parent's detachment ``n`` at ``place``, as D2's split would make it."""
    parent = state.features[FeatureId(object_id(campaign, "feature", parent_key))]
    return parent.model_copy(
        update={
            "feature_id": FeatureId(object_id(campaign, "feature", f"{parent_key}__d{n}")),
            "name": f"{parent.name} detachment {n}",
            "tier": 1,
            "places": (place,),
            "as_of": max(LATER, parent.as_of),
            "legs": (),
            "detached_from": parent.feature_id,
            "rejoined_on": rejoined,
        }
    )


# --- sighting ---------------------------------------------------------------------------


def rig_with(*seats: str) -> Rig:
    r = Rig()
    for key in seats:
        r.seat(key)
    r.close_session_zero()
    return r


def feed(r: Rig, key: str) -> Feed:
    return r.state.feeds[FeedId(r.ids[key])]


def labels(doc: ev.DocumentIssued | None) -> list[str]:
    return [] if doc is None else [b.label for b in doc.document.body if b.sight is not None]


def home_detachment(r: Rig, n: int = 1, rejoined: date | None = None) -> Feature:
    det = detachment(r.state, CAMPAIGN, "home_fleet", EntityId(r.ids["reykjavik"]), n, rejoined)
    r.add(ev.FeatureSet(feature=det))
    return det


def test_germanys_naval_reports_place_a_home_fleet_detachment_once_one_exists() -> None:
    r = rig_with("hitler")
    naval = feed(r, "german_naval_reports")
    assert "Home Fleet detachment 1" not in labels(rf.issue(r.state, naval, LATER, "s"))
    det = home_detachment(r)
    doc = rf.issue(r.state, naval, LATER, "s")
    assert doc is not None
    line = next(b for b in doc.document.body if b.label == "Home Fleet detachment 1")
    assert line.value == "Reykjavik"
    assert line.sight is not None and line.sight.kind is FeatureKind.FLEET
    assert line.sight.side == det.side and line.sight.places == det.places
    assert det.feature_id in {s.feature_id for s in doc.truth.sightings}
    assert "tier" not in doc.document.model_dump_json()


def test_a_detachment_line_follows_its_parent() -> None:
    r = rig_with("hitler")
    home_detachment(r)
    got = labels(rf.issue(r.state, feed(r, "german_naval_reports"), LATER, "s"))
    assert got.index("Home Fleet detachment 1") == got.index("Home Fleet") + 1


def test_a_detachment_has_its_own_omit_draw() -> None:
    r = rig_with("hitler")
    home_detachment(r)
    half = feed(r, "german_naval_reports").model_copy(update={"bias": Bias(omit_pct=50)})
    pairs = set()
    for n in range(40):
        got = labels(rf.issue(r.state, half, LATER, f"seed-{n}"))
        pairs.add(("Home Fleet" in got, "Home Fleet detachment 1" in got))
    assert (True, False) in pairs and (False, True) in pairs


def test_only_feeds_that_sight_the_parent_place_its_detachment() -> None:
    """Japan holds no feed that sights the Home Fleet, so no Japanese page places it."""
    r = rig_with("hitler", "tojo", "roosevelt", "churchill")
    det = home_detachment(r)
    parent = FeatureId(r.ids["home_fleet"])
    tojo = r.seats["tojo"]
    placed = set()
    for f in r.state.feeds.values():
        doc = rf.issue(r.state, f, LATER, "s")
        if doc is None or det.feature_id not in {s.feature_id for s in doc.truth.sightings}:
            continue
        placed.add(f.feed_id)
        assert parent in f.sights
        assert tojo not in doc.document.scope.known_by
    assert len(placed) == 3  # churchill_cables, admiralty_reports, german_naval_reports


def test_a_rejoined_detachment_is_no_longer_placed() -> None:
    r = rig_with("hitler")
    home_detachment(r, rejoined=LATER)
    got = labels(rf.issue(r.state, feed(r, "german_naval_reports"), LATER, "s"))
    assert "Home Fleet" in got and "Home Fleet detachment 1" not in got


# --- contact and command ---------------------------------------------------------------


def slice_detachment(
    sl: Slice, parent_key: str, place: str, n: int = 1, rejoined: date | None = None
) -> Feature:
    det = detachment(sl.state, SLICE_CAMPAIGN, parent_key, sl.entity(place), n, rejoined)
    sl.add(ev.FeatureSet(feature=det))
    return det


def test_a_contact_with_a_detachment_reports_to_the_parents_commander() -> None:
    sl = slice_with("churchill")
    slice_detachment(sl, "home_fleet", "norfolk")
    declared(sl, "uk", "usa")
    docs = [p for p in war_rules.contacts(sl.state, DAY) if isinstance(p, ev.DocumentIssued)]
    to_churchill = [d for d in docs if d.document.scope.known_by == {SeatId("seat-churchill")}]
    assert len(docs) == 2 and len(to_churchill) == 1
    assert to_churchill[0].document.title == (
        "Home Fleet detachment 1 has met US Atlantic Fleet at Norfolk"
    )


def test_a_rejoined_detachment_raises_no_contact() -> None:
    sl = slice_with("churchill")
    slice_detachment(sl, "home_fleet", "norfolk", rejoined=DAY)
    declared(sl, "uk", "usa")
    assert war_rules.contacts(sl.state, DAY) == []


def test_shoot_on_sight_counts_live_detachments_only() -> None:
    sl = slice_with("churchill")
    churchill = SeatId("seat-churchill")
    effect = rx.SetEngagement(
        force=sl.feature("home_fleet"),
        zone=sl.entity("scapa_flow"),
        rule=rx.Engagement.SHOOT_ON_SIGHT,
    )
    ask = Ask(ask="Fire on any ship you meet", effect=effect)
    slice_detachment(sl, "us_atlantic_fleet", "scapa_flow", rejoined=DAY)
    assert war_rules.ask_refusal(sl.state, churchill, ask) == ""
    slice_detachment(sl, "us_atlantic_fleet", "scapa_flow", n=2)
    assert war_rules.ask_refusal(sl.state, churchill, ask) == (
        "United Kingdom is not at war with United States, "
        "so forces in Scapa Flow cannot be ordered to shoot on sight."
    )


def test_an_engage_order_naming_no_force_covers_live_detachments() -> None:
    sl = Slice()
    live = slice_detachment(sl, "us_atlantic_fleet", "scapa_flow")
    gone = slice_detachment(sl, "us_atlantic_fleet", "norfolk", n=2, rejoined=DAY)
    effect = rx.SetEngagement(force=None, zone="western Atlantic", rule=rx.Engagement.DEFEND)
    out = rapply._engage(PassWorld(sl.state), effect, sl.entity("roosevelt"), DAY)
    set_ = {p.feature.feature_id for p in out if isinstance(p, ev.FeatureSet)}
    assert set_ == {sl.feature("us_atlantic_fleet"), live.feature_id}
    assert gone.feature_id not in set_


# --- filing refusals -------------------------------------------------------------------


def detach(r: Rig, force: str, strength: int | str) -> str:
    params = {"force": force, "to": "argentia", "strength": str(strength)}
    return war_rules.order_refusal(r.state, r.seats["roosevelt"], "detach_fleet", params)


def us_detachment(r: Rig, parent_key: str, n: int = 1, rejoined: date | None = None) -> None:
    det = detachment(r.state, CAMPAIGN, parent_key, EntityId(r.ids["argentia"]), n, rejoined)
    r.add(ev.FeatureSet(feature=det))


def test_a_third_live_fleet_detachment_is_refused_and_names_the_cap() -> None:
    r = rig_with("roosevelt")
    us_detachment(r, "us_atlantic_fleet")
    assert detach(r, "us_pacific_fleet", 2) == ""
    us_detachment(r, "us_pacific_fleet")
    text = detach(r, "us_atlantic_fleet", 1)
    assert text == (
        "United States already has 2 fleet detachments out, the most a side may have at once."
    )


def test_a_rejoined_detachment_frees_its_place_under_the_cap() -> None:
    r = rig_with("roosevelt")
    us_detachment(r, "us_atlantic_fleet")
    us_detachment(r, "us_pacific_fleet", rejoined=LATER)
    assert detach(r, "us_atlantic_fleet", 1) == ""


def test_another_sides_detachments_do_not_count_against_the_cap() -> None:
    r = rig_with("roosevelt")
    home = EntityId(r.ids["reykjavik"])
    for n in (1, 2):
        r.add(ev.FeatureSet(feature=detachment(r.state, CAMPAIGN, "home_fleet", home, n)))
    assert detach(r, "us_atlantic_fleet", 1) == ""


def test_a_split_that_leaves_the_parent_below_strength_one_is_refused() -> None:
    r = rig_with("roosevelt")
    assert detach(r, "us_atlantic_fleet", 3) == ""
    text = detach(r, "us_atlantic_fleet", 4)
    assert text == "US Atlantic Fleet has strength 4, so at most 3 of it can be detached."


def test_a_kind_with_a_cap_of_none_is_refused_in_words() -> None:
    r = rig_with("hitler")
    params = {"force": "army_group_centre", "to": "smolensk", "strength": "1"}
    text = war_rules.order_refusal(r.state, r.seats["hitler"], "detach_fleet", params)
    assert text == "No side may detach part of an army."


def test_missing_or_unreadable_detach_params_are_not_a_refusal() -> None:
    r = rig_with("roosevelt")
    assert detach(r, "atlantis", 2) == ""
    assert detach(r, "us_atlantic_fleet", "two") == ""
    assert war_rules.order_refusal(r.state, r.seats["roosevelt"], "detach_fleet", {}) == ""
