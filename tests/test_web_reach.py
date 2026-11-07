"""Reach groups for a seat (Phase 4 unit S4): who is open, by which channel, in words."""

import pytest

from revisionist.core.ids import SeatId, derived_id
from revisionist.core.ontology import Seat, SeatKind
from revisionist.core.state import State
from revisionist.engine.web.reach_groups import reach
from revisionist.engine.web.realism_api import ReachContact, ReachGroups
from tests.test_engine_v2_contract import CAMPAIGN, Slice


@pytest.fixture
def sl() -> Slice:
    return Slice()


def _names(group: list[ReachContact]) -> list[str]:
    return [c["name"] for c in group]


def _strings(groups: ReachGroups) -> list[str]:
    out: list[str] = []
    for group in (groups["inner_circle"], groups["government"], groups["foreign"], groups["other"]):
        for c in group:
            out += [c["name"], c["title"] or "", *c["channels"]]
    return out


def _seat(sl: Slice, key: str, kind: SeatKind, embodies: str) -> tuple[State, SeatId]:
    """A seat added to a copy of the slice's state; the slice only claims Roosevelt and Wheeler."""
    seat = SeatId(derived_id(CAMPAIGN, "seat", key))
    entry = Seat(seat_id=seat, kind=kind, name=key, embodies=sl.entity(embodies))
    return sl.state.model_copy(update={"seats": {**sl.state.seats, seat: entry}}), seat


def test_roosevelt_reaches_stark_and_rayburn_in_the_inner_circle(sl: Slice) -> None:
    inner = reach(sl.state, sl.fdr)["inner_circle"]
    assert _names(inner) == ["Harold R. Stark", "Sam Rayburn"]
    assert inner[0]["channels"][0] == "In person"
    assert inner[1]["channels"][0] == "Telephone"
    assert inner[1]["title"] == "Speaker of the House of Representatives"


def test_roosevelt_reaches_wheeler_in_government_by_telephone_letter_or_in_person(
    sl: Slice,
) -> None:
    government = reach(sl.state, sl.fdr)["government"]
    assert _names(government) == ["Burton K. Wheeler"]
    assert government[0]["title"] == "Senator for Montana"
    assert government[0]["channels"] == ["Telephone", "Letter", "In person"]


def test_roosevelt_reaches_churchill_abroad_by_cable_or_courier(sl: Slice) -> None:
    foreign = reach(sl.state, sl.fdr)["foreign"]
    assert _names(foreign) == ["Sir Dudley Pound", "Winston Churchill"]
    churchill = foreign[1]
    assert churchill["title"] == "Prime Minister of the United Kingdom"
    assert churchill["channels"] == ["Cable", "Courier"]


def test_a_person_with_no_card_is_reached_in_other_groups(sl: Slice) -> None:
    assert _names(reach(sl.state, sl.fdr)["other"]) == ["Henry A. Wallace"]
    assert reach(sl.state, sl.fdr)["other"][0]["title"] is None


def test_a_seat_that_may_not_address_a_head_does_not_list_him(sl: Slice) -> None:
    state, stark = _seat(sl, "stark", SeatKind.PLAYER, "stark")
    groups = reach(state, stark)
    assert _names(groups["foreign"]) == ["Sir Dudley Pound"]
    assert _names(groups["government"]) == ["Burton K. Wheeler", "Sam Rayburn"]
    assert "Winston Churchill" not in _strings(groups)


def test_churchill_reaches_the_cabinet_by_the_inner_circle_channel_first(sl: Slice) -> None:
    state, churchill = _seat(sl, "churchill", SeatKind.PLAYER, "churchill")
    groups = reach(state, churchill)
    assert _names(groups["inner_circle"]) == ["Franklin D. Roosevelt", "Sir Dudley Pound"]
    assert groups["inner_circle"][0]["channels"][0] == "Cable"
    assert groups["inner_circle"][1]["channels"][0] == "In person"
    assert groups["government"] == []
    assert _names(groups["foreign"]) == [
        "Burton K. Wheeler",
        "Harold R. Stark",
        "Henry A. Wallace",
        "Sam Rayburn",
    ]


def test_a_seat_with_no_person_gets_four_empty_groups(sl: Slice) -> None:
    state, outlet = _seat(sl, "herald", SeatKind.OUTLET, "usa")
    assert reach(state, outlet) == {
        "inner_circle": [],
        "government": [],
        "foreign": [],
        "other": [],
    }


def test_the_seat_is_never_its_own_contact(sl: Slice) -> None:
    assert "Franklin D. Roosevelt" not in _strings(reach(sl.state, sl.fdr))


def test_no_string_a_player_reads_has_an_underscore(sl: Slice) -> None:
    state, stark = _seat(sl, "stark", SeatKind.PLAYER, "stark")
    for seat, s in ((sl.fdr, sl.state), (stark, state)):
        assert all("_" not in text for text in _strings(reach(s, seat)))
