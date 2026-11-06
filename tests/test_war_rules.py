"""What a state of war allows and sets in motion."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import SeatId
from revisionist.core.realism import war_rules
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.war import NewsTopic, War, war_id_for
from revisionist.core.state import State
from tests.test_engine_v2_contract import CAMPAIGN, Slice

DAY = date(1941, 9, 12)


def declared(sl: Slice, a: str, b: str) -> None:
    """Fold a war between two slice polities."""
    ea, eb = sl.entity(a), sl.entity(b)
    war = War(war_id=war_id_for(ea, eb), a=ea, b=eb, since=DAY, declared_by=sl.entity("roosevelt"))
    sl.add(ev.WarDeclared(war=war))


def slice_with(*keys: str) -> Slice:
    """The slice with extra people claimed, seat id "seat-<key>"."""
    sl = Slice()
    sl.events.pop()
    for key in keys:
        sl.add(ev.CharacterClaimed(seat_id=SeatId(f"seat-{key}"), entity_id=sl.entity(key)))
    sl.add(ev.SessionZeroClosed())
    return sl


def together() -> Slice:
    """Home Fleet in Norfolk beside the US Atlantic Fleet, Churchill claimed."""
    sl = slice_with("churchill")
    fleet = sl.state.features[sl.feature("home_fleet")]
    sl.add(ev.FeatureSet(feature=fleet.model_copy(update={"places": (sl.entity("norfolk"),)})))
    return sl


def test_attack_us_shipping_is_refused_until_the_war() -> None:
    sl = slice_with("churchill")
    params = {"posture": "attack_us_shipping"}
    churchill = SeatId("seat-churchill")
    text = war_rules.order_refusal(sl.state, churchill, "uboat_directive", params)
    assert text.endswith("so the U-boats cannot be ordered to attack American ships on sight.")
    assert "United Kingdom is not at war with United States" in text and len(text) <= 200
    declared(sl, "uk", "usa")
    assert war_rules.order_refusal(sl.state, churchill, "uboat_directive", params) == ""


def test_other_postures_and_levers_are_untouched() -> None:
    sl = Slice()
    state = sl.state
    for posture in ("restrict_us_ships", "unrestricted_atlantic"):
        assert war_rules.order_refusal(state, sl.fdr, "uboat_directive", {"posture": posture}) == ""
    assert war_rules.order_refusal(state, sl.fdr, "send_bill", {}) == ""


def test_declaring_war_twice_is_refused() -> None:
    sl = slice_with("churchill")
    params = {"target": "usa"}
    churchill = SeatId("seat-churchill")
    assert war_rules.order_refusal(sl.state, churchill, "declare_war", params) == ""
    declared(sl, "uk", "usa")
    text = war_rules.order_refusal(sl.state, churchill, "declare_war", params)
    assert text == "United Kingdom is already at war with United States."


def test_missing_data_is_not_a_refusal() -> None:
    sl = Slice()
    state = sl.state
    posture = {"posture": "attack_us_shipping"}
    assert war_rules.order_refusal(state, SeatId("nobody"), "uboat_directive", posture) == ""
    assert war_rules.order_refusal(state, SeatId("nobody"), "declare_war", {"target": "usa"}) == ""
    assert war_rules.order_refusal(state, sl.fdr, "declare_war", {"target": "atlantis"}) == ""
    assert war_rules.order_refusal(state, sl.fdr, "declare_war", {}) == ""
    bare = State(campaign_id=CAMPAIGN, ruleset="realism", in_world_date=DAY)
    assert war_rules.order_refusal(bare, sl.fdr, "uboat_directive", posture) == ""


def test_ask_refusal_is_empty() -> None:
    sl = Slice()
    assert war_rules.ask_refusal(sl.state, sl.fdr, Ask(ask="x")) == ""


def _apply(sl: Slice, payloads: list[ev.Payload]) -> None:
    for p in payloads:
        sl.add(p)


def test_forces_meeting_in_a_war_land_one_news_and_a_report_each() -> None:
    sl = together()
    declared(sl, "uk", "usa")
    out = war_rules.contacts(sl.state, DAY)
    news = [p for p in out if isinstance(p, ev.NewsReported)]
    docs = [p for p in out if isinstance(p, ev.DocumentIssued)]
    assert len(news) == 1 and len(docs) == 2
    item = news[0].news
    assert item.topic is NewsTopic.CONTACT and item.on == DAY and len(item.headline) <= 60
    assert " met at Norfolk" in item.headline
    assert {item.subject, item.obj} == {sl.entity("uk"), sl.entity("usa")}
    assert all(d.truth.news_id == item.news_id for d in docs)
    assert {d.document.scope.known_by for d in docs} == {
        frozenset({sl.fdr}),
        frozenset({SeatId("seat-churchill")}),
    }


def test_no_contact_when_not_at_war_apart_or_under_way() -> None:
    sl = together()
    assert war_rules.contacts(sl.state, DAY) == []
    declared(sl, "uk", "usa")
    fleet = sl.state.features[sl.feature("home_fleet")]
    sl.add(ev.FeatureSet(feature=fleet.model_copy(update={"places": (sl.entity("lorient"),)})))
    assert war_rules.contacts(sl.state, DAY) == []
    moving = fleet.model_copy(
        update={"bound_for": sl.entity("lorient"), "arrives": date(1941, 9, 20)}
    )
    sl.add(ev.FeatureSet(feature=moving))
    assert war_rules.contacts(sl.state, DAY) == []


def test_a_contact_lands_once_and_costs_nothing() -> None:
    sl = together()
    declared(sl, "uk", "usa")
    before = sl.state.features
    _apply(sl, war_rules.contacts(sl.state, DAY))
    assert sl.state.features == before
    assert len(sl.state.news) == 1
    assert war_rules.contacts(sl.state, date(1941, 9, 13)) == []


def test_declaring_war_on_yourself_or_a_non_polity_is_refused() -> None:
    sl = slice_with("churchill")
    churchill = SeatId("seat-churchill")
    own = war_rules.order_refusal(sl.state, churchill, "declare_war", {"target": "uk"})
    assert own == "United Kingdom cannot declare war on itself."
    org = war_rules.order_refusal(sl.state, churchill, "declare_war", {"target": "commons"})
    assert org == "House of Commons is not a power to declare war on."
