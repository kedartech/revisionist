"""Landing a MakeStatement: public news that may move opinion, or a private fact."""

from datetime import date

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FactId
from revisionist.core.ontology import Fact
from revisionist.core.realism import effect as rx
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.document import BodyField
from revisionist.core.realism.land import statement
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.war import NewsEvent, NewsTopic
from revisionist.core.visibility import private_to
from tests.test_engine_v2_contract import Slice
from tests.test_realism_resolvers import Rig, rig

FILED = date(1941, 9, 11)


@pytest.fixture
def sl() -> Slice:
    return Slice()


def land(
    sl: Slice, effect: rx.MakeStatement, on: date = FILED
) -> tuple[list[ev.Payload], list[FactId]]:
    return statement.land(PassWorld(sl.state), effect, sl.fdr, sl.entity("roosevelt"), on)


def news(payloads: list[ev.Payload]) -> list[NewsEvent]:
    return [p.news for p in payloads if isinstance(p, ev.NewsReported)]


def autumn(target: int | None = 50) -> Rig:
    r = rig("autumn-1941")
    if target is not None:
        r.set_value("opinion_target", target)
    return r


def speak(r: Rig, effect: rx.MakeStatement) -> list[ev.Payload]:
    roosevelt = EntityId(r.ids["roosevelt"])
    payloads, facts = statement.land(
        PassWorld(r.state), effect, r.seats["roosevelt"], roosevelt, FILED
    )
    assert facts == []
    return payloads


def test_a_public_statement_is_news_about_the_issuer_and_its_polity(sl: Slice) -> None:
    payloads, facts = land(sl, rx.MakeStatement(theme="aid_to_allies"))
    assert facts == []
    [item] = news(payloads)
    assert item.topic is NewsTopic.STATEMENT
    assert item.subject == sl.entity("roosevelt")
    assert item.obj == sl.entity("usa")
    assert item.facts == (BodyField(label="Theme", value="aid_to_allies"),)
    name = sl.state.entities[sl.entity("roosevelt")].name
    assert item.headline == f"{name} speaks on aid_to_allies"


def test_the_news_id_differs_by_theme_and_day_and_repeats_for_the_same_one(sl: Slice) -> None:
    ids = {
        news(land(sl, rx.MakeStatement(theme=t), on=d)[0])[0].news_id
        for t in ("aid_to_allies", "national_unity")
        for d in (FILED, date(1941, 9, 12))
    }
    assert len(ids) == 4
    first = news(land(sl, rx.MakeStatement(theme="aid_to_allies"))[0])[0]
    again = news(land(sl, rx.MakeStatement(theme="aid_to_allies"))[0])[0]
    assert first.news_id == again.news_id


def test_a_long_headline_is_cut_to_the_label_cap(sl: Slice) -> None:
    [item] = news(land(sl, rx.MakeStatement(theme="t" * 60))[0])
    assert len(item.headline) <= 60
    assert item.headline.endswith("…")


@pytest.mark.parametrize(
    ("theme", "points"), [("aid_to_allies", 2), ("freedom_of_the_seas", 3), ("national_unity", 1)]
)
def test_a_known_theme_moves_the_target_by_its_points(theme: str, points: int) -> None:
    r = autumn(50)
    for p in speak(r, rx.MakeStatement(theme=theme)):
        r.add(p)
    assert rs.value(r.state, "opinion_target") == 50 + points


def test_the_target_is_clamped_at_one_hundred() -> None:
    r = autumn(99)
    for p in speak(r, rx.MakeStatement(theme="freedom_of_the_seas")):
        r.add(p)
    assert rs.value(r.state, "opinion_target") == 100


def test_a_gap_target_starts_from_the_about_right_figure() -> None:
    r = autumn(None)
    assert rs.value(r.state, "gallup_fdr_about_right") == 55
    for p in speak(r, rx.MakeStatement(theme="aid_to_allies")):
        r.add(p)
    assert rs.value(r.state, "opinion_target") == 57


def test_an_unknown_theme_moves_nothing_but_still_reports() -> None:
    r = autumn(50)
    payloads = speak(r, rx.MakeStatement(theme="tea_party"))
    assert [type(p) for p in payloads] == [ev.NewsReported]
    for p in payloads:
        r.add(p)
    assert rs.value(r.state, "opinion_target") == 50


def test_a_private_statement_is_a_fact_and_no_news(sl: Slice) -> None:
    audience = sl.entity("wallace")
    payloads, facts = land(sl, rx.MakeStatement(theme="aid_to_allies", audience=audience))
    assert facts == []
    [p] = payloads
    assert isinstance(p, ev.FactAsserted)
    fact: Fact = p.fact
    assert fact.subject == sl.entity("roosevelt")
    assert fact.predicate == "told"
    assert fact.obj == audience
    assert fact.scope == private_to(sl.fdr)


def test_a_private_statement_moves_no_quantity() -> None:
    r = autumn(50)
    payloads = speak(
        r, rx.MakeStatement(theme="freedom_of_the_seas", audience=EntityId(r.ids["wallace"]))
    )
    assert not any(isinstance(p, ev.QuantitySet) for p in payloads)


def test_a_public_statement_lands_once_on_folded_state(sl: Slice) -> None:
    effect = rx.MakeStatement(theme="aid_to_allies")
    payloads, _ = land(sl, effect)
    for p in payloads:
        sl.add(p)
    assert land(sl, effect) == ([], [])


def test_a_private_statement_lands_once_on_folded_state(sl: Slice) -> None:
    effect = rx.MakeStatement(theme="aid_to_allies", audience=sl.entity("wallace"))
    payloads, _ = land(sl, effect)
    for p in payloads:
        sl.add(p)
    assert land(sl, effect) == ([], [])
