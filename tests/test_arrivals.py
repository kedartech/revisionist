"""Arrivals: a force that reaches its destination is reported to the seat that commands it.

The report is the commanding seat's alone, once per arrival, and only on the day the
force is in its new place (spec §8.3, §4 2.1)."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.realism import reach
from revisionist.core.realism.arrivals import arrivals
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import BodyField, DocumentKind
from revisionist.core.realism.effect import Engagement, Posture
from revisionist.core.realism.geography import FeatureKind, Sight, SightRef
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from tests.test_engine_v2_contract import Slice

ARRIVES = date(1941, 9, 13)


def under_way(sl: Slice) -> None:
    """The Atlantic fleet sails from Norfolk for Argentia, with orders set on the way."""
    ft = sl.state.features[sl.feature("us_atlantic_fleet")]
    sl.add(
        ev.FeatureSet(
            feature=ft.model_copy(
                update={
                    "bound_for": sl.entity("argentia"),
                    "arrives": ARRIVES,
                    "posture": Posture.ESCORT,
                    "engagement": Engagement.DEFEND,
                }
            )
        )
    )


def arrive(sl: Slice) -> tuple[State, State]:
    """Before and after the movement resolver lands the fleet at Argentia."""
    before = sl.state
    ft = before.features[sl.feature("us_atlantic_fleet")]
    sl.add(
        ev.FeatureSet(
            feature=ft.model_copy(
                update={
                    "places": (sl.entity("argentia"),),
                    "bound_for": None,
                    "arrives": None,
                    "as_of": ARRIVES,
                }
            )
        )
    )
    return before, sl.state


def test_an_arrival_is_reported_to_the_commanding_seat() -> None:
    sl = Slice()
    under_way(sl)
    before, after = arrive(sl)
    (p,) = arrivals(before, after, ARRIVES)
    assert isinstance(p, ev.DocumentIssued)
    doc = p.document
    assert doc.scope == private_to(sl.fdr)
    assert doc.kind is DocumentKind.REPORT and doc.issued == ARRIVES
    assert doc.author == sl.entity("stark")
    assert doc.title == "US Atlantic Fleet has reached Argentia"
    channels = reach.channels_to(after, sl.entity("stark"), sl.entity("roosevelt"))
    channel = channels[0] if channels else ChannelKind.IN_PERSON
    assert doc.channel is channel
    assert doc.arrives == ARRIVES + timedelta(days=reach.transit_days(channel))
    sight = BodyField(
        label="US Atlantic Fleet",
        value="Argentia",
        sight=Sight(kind=FeatureKind.FLEET, side=sl.entity("usa"), places=(sl.entity("argentia"),)),
    )
    assert doc.body == (
        BodyField(label="Position", value="Argentia"),
        BodyField(label="Posture", value="Escort"),
        BodyField(label="Rule", value="Defend"),
        sight,
    )
    assert p.truth.sightings == (
        SightRef(feature_id=sl.feature("us_atlantic_fleet"), places=(sl.entity("argentia"),)),
    )


def test_the_other_seat_does_not_see_the_arrival() -> None:
    sl = Slice()
    under_way(sl)
    before, after = arrive(sl)
    (p,) = arrivals(before, after, ARRIVES)
    assert isinstance(p, ev.DocumentIssued)
    assert sl.wheeler not in p.document.scope.known_by


def test_no_report_while_the_force_is_under_way() -> None:
    sl = Slice()
    under_way(sl)
    before = sl.state
    assert arrivals(before, before, ARRIVES) == []


def test_an_arrival_is_reported_once() -> None:
    sl = Slice()
    under_way(sl)
    before, after = arrive(sl)
    for p in arrivals(before, after, ARRIVES):
        assert isinstance(p, ev.DocumentIssued)
        sl.add(p, p.document.scope)
    assert arrivals(before, sl.state, ARRIVES) == []
