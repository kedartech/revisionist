"""Appointments and dismissals land as public facts and public news."""

from datetime import date

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.realism.land import appointment
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.war import NewsTopic
from revisionist.core.visibility import PUBLIC
from tests.test_engine_v2_contract import Slice


@pytest.fixture
def sl() -> Slice:
    return Slice()


ON = date(1941, 11, 6)


def land(sl: Slice, effect: rx.Appointment, issuer: EntityId | None = None) -> list[ev.Payload]:
    """Land the effect, fold what it returned, and hand back the payloads."""
    out, revealed = appointment.land(
        PassWorld(sl.state), effect, sl.fdr, issuer or sl.entity("roosevelt"), ON
    )
    assert revealed == []
    for p in out:
        sl.add(p, PUBLIC)
    return out


def test_an_appointment_lands_a_public_office_fact_and_news(sl: Slice) -> None:
    out = land(sl, rx.Appointment(person=sl.entity("stark"), office="Chief of Naval Ops"))

    facts = [p.fact for p in out if isinstance(p, ev.FactAsserted)]
    assert len(facts) == 1
    assert facts[0].subject == sl.entity("stark")
    assert facts[0].predicate == "holds_office"
    assert facts[0].obj == "Chief of Naval Ops"
    assert facts[0].scope == PUBLIC
    assert sl.state.facts[facts[0].fact_id] == facts[0]

    news = [p.news for p in out if isinstance(p, ev.NewsReported)]
    assert len(news) == 1
    assert news[0].topic is NewsTopic.APPOINTMENT
    assert news[0].subject == sl.entity("stark")
    assert news[0].on == ON
    assert news[0].headline == "Harold R. Stark appointed: Chief of Naval Ops"
    assert news[0].facts[0].label == "Office"
    assert news[0].facts[0].value == "Chief of Naval Ops"
    assert news[0].facts[1].label == "Appointed"
    assert news[0].facts[1].value == "Harold R. Stark"
    assert sl.state.news[news[0].news_id] == news[0]


def test_news_carries_the_polity_of_the_issuer(sl: Slice) -> None:
    out = land(sl, rx.Appointment(person=sl.entity("stark"), office="Chief of Naval Ops"))

    news = next(p.news for p in out if isinstance(p, ev.NewsReported))
    assert news.obj == sl.entity("usa")


def test_a_dismissal_lands_a_dismissed_from_fact_and_news(sl: Slice) -> None:
    out = land(sl, rx.Appointment(person=sl.entity("rayburn"), office="Speaker", appoint=False))

    facts = [p.fact for p in out if isinstance(p, ev.FactAsserted)]
    assert [(f.predicate, f.obj) for f in facts] == [("dismissed_from", "Speaker")]

    news = next(p.news for p in out if isinstance(p, ev.NewsReported))
    assert news.headline == "Sam Rayburn dismissed: Speaker"
    assert news.facts[1].label == "Dismissed"
    assert news.facts[1].value == "Sam Rayburn"


def test_news_is_structured_with_no_prose_beyond_the_headline(sl: Slice) -> None:
    out = land(sl, rx.Appointment(person=sl.entity("stark"), office="Chief of Naval Ops"))

    news = next(p.news for p in out if isinstance(p, ev.NewsReported))
    assert all(len(f.label) <= 60 for f in news.facts)
    assert all(isinstance(f.value, str) and len(f.value) <= 60 for f in news.facts)
    assert all(f.unit == "" and f.sight is None for f in news.facts)


def test_a_repeat_on_the_same_day_is_not_folded_twice(sl: Slice) -> None:
    effect = rx.Appointment(person=sl.entity("stark"), office="Chief of Naval Ops")
    land(sl, effect)
    facts, news = dict(sl.state.facts), dict(sl.state.news)

    assert appointment.land(PassWorld(sl.state), effect, sl.fdr, sl.entity("roosevelt"), ON) == (
        [],
        [],
    )
    assert sl.state.facts == facts
    assert sl.state.news == news


def test_a_long_office_is_truncated_in_the_headline(sl: Slice) -> None:
    office = "Director of Strategic Coordination for Hemispheric Affairs"
    out = land(sl, rx.Appointment(person=sl.entity("stark"), office=office))

    news = next(p.news for p in out if isinstance(p, ev.NewsReported))
    assert len(news.headline) <= 60
    assert news.headline.endswith("…")
    assert news.headline.startswith("Harold R. Stark appointed: Director")


def test_an_unknown_person_does_not_crash(sl: Slice) -> None:
    ghost = EntityId(derived_id(sl.state.campaign_id, "entity", "nobody"))
    out = land(sl, rx.Appointment(person=ghost, office="Chief of Naval Ops"))

    news = next(p.news for p in out if isinstance(p, ev.NewsReported))
    assert news.headline == "someone appointed: Chief of Naval Ops"
    assert news.facts[1].value == "someone"
