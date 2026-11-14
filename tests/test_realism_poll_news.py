"""A move in the Gallup figure is news: one public item per move, with nothing private."""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId
from revisionist.core.project import project
from revisionist.core.realism.document import BodyField, DocumentKind
from revisionist.core.realism.press import LINE, news_pages
from revisionist.core.realism.resolvers import ON_DAY, Change, opinion, qid, value
from revisionist.core.realism.war import NewsEvent, NewsTopic
from revisionist.core.visibility import Scope, private_to
from tests.test_realism_resolvers import Rig, rig

MONDAY = date(1941, 9, 8)
FIGURE = "Gallup, Roosevelt's course 'about right'"
TARGET = 87
"""A target the figure cannot reach in the weeks a test walks, so it shows if it leaks."""


def poll_news(changes: tuple[Change, ...]) -> list[NewsEvent]:
    return [c for c in changes if isinstance(c, NewsEvent) and c.topic is NewsTopic.POLL]


def walk(r: Rig, start: date = MONDAY, days: int = 28) -> list[NewsEvent]:
    """Every daily resolver, day by day from ``start``, folded; returns the poll news."""
    out: list[NewsEvent] = []
    for n in range(days):
        for on_day in ON_DAY.values():
            changes = on_day(r.state, start + timedelta(days=n))
            out += poll_news(changes)
            r.fold_changes(changes)
    return out


def hide(r: Rig, key: str, scope: Scope | None) -> None:
    """Take a world quantity out of the public record."""
    q = qid(r.state, key)
    hidden = r.state.quantities[q].model_copy(update={"scope": scope})
    r.state = r.state.model_copy(update={"quantities": {**r.state.quantities, q: hidden}})


def test_a_rise_on_monday_is_one_news_item_with_the_figure() -> None:
    r = rig()
    r.set_value("opinion_target", 58)
    (item,) = poll_news(opinion.on_day(r.state, MONDAY))
    assert item.on == MONDAY
    assert item.subject == EntityId(r.ids["usa"])
    assert item.obj is None
    assert item.headline == "Poll: Roosevelt's course up to 56%"
    assert item.facts == (
        BodyField(label=FIGURE, value=56, unit="percent"),
        BodyField(label="Previous poll", value=55, unit="percent"),
        BodyField(label="Date", value="8 September 1941"),
    )


def test_a_fall_reads_down() -> None:
    r = rig()
    r.set_value("opinion_target", 50)
    (item,) = poll_news(opinion.on_day(r.state, MONDAY))
    assert item.headline == "Poll: Roosevelt's course down to 54%"
    assert item.facts[0].value == 54
    assert item.facts[1].value == 55


def test_an_incident_that_moves_the_figure_is_news_too() -> None:
    r = rig()
    greer = next(s for i, s in r.state.scheduled.items() if i == r.ids["greer_incident"])
    r.add(ev.ScheduledEventFired(scheduled_id=greer.scheduled_id))
    (item,) = poll_news(opinion.on_day(r.state, MONDAY))
    assert item.facts[0].value == 56


def test_no_news_when_the_figure_does_not_move() -> None:
    r = rig()
    assert poll_news(opinion.on_day(r.state, MONDAY)) == []  # no target set
    r.set_value("opinion_target", 55)
    assert poll_news(opinion.on_day(r.state, MONDAY)) == []  # at target
    r.set_value("opinion_target", 58)
    assert poll_news(opinion.on_day(r.state, MONDAY + timedelta(days=3))) == []  # a Thursday


def test_one_item_per_move_never_one_per_wake_or_day() -> None:
    r = rig()
    r.set_value("opinion_target", 58)
    items = walk(r)
    assert [i.on for i in items] == [MONDAY + timedelta(weeks=n) for n in range(3)]
    assert [i.facts[0].value for i in items] == [56, 57, 58]
    assert len({i.news_id for i in items}) == 3
    assert {i.news_id for i in items} <= set(r.state.news)
    assert value(r.state, "gallup_fdr_about_right") == 58


@pytest.mark.parametrize("private", [False, True])
def test_a_figure_off_the_public_record_makes_no_news(private: bool) -> None:
    r = rig()
    r.set_value("opinion_target", 58)
    hide(r, "gallup_fdr_about_right", private_to(r.seats["roosevelt"]) if private else None)
    changes = opinion.on_day(r.state, MONDAY)
    assert poll_news(changes) == []
    r.fold_changes(changes)
    assert value(r.state, "gallup_fdr_about_right") == 56


def test_the_private_target_never_reaches_the_news() -> None:
    r = rig()
    r.set_value("opinion_target", TARGET)
    (item,) = poll_news(opinion.on_day(r.state, MONDAY))
    assert str(TARGET) not in item.model_dump_json()
    assert all(f.value != TARGET for f in item.facts)


def test_each_seat_press_prints_the_public_facts() -> None:
    r = Rig()
    roosevelt, churchill = r.seat("roosevelt"), r.seat("churchill")
    r.close_session_zero()
    r.set_value("opinion_target", TARGET)
    changes = opinion.on_day(r.state, MONDAY)
    (item,) = poll_news(changes)
    r.fold_changes(changes)
    pages = news_pages(r.state, MONDAY)
    assert pages
    for page in pages:
        r.add(page)
    assert str(TARGET) not in "".join(p.model_dump_json() for p in pages)
    r.state = r.state.model_copy(update={"in_world_date": MONDAY})
    for seat in (roosevelt, churchill):
        held = [
            d for d in project(r.state, seat).documents.values() if d.kind is DocumentKind.PRESS
        ]
        assert len(held) == 3
        assert {d.body for d in held} == {item.facts}
        assert {r.state.documents[d.doc_id].truth.news_id for d in held} == {item.news_id}


def test_the_figure_survives_the_longest_outlet_name_in_a_press_title() -> None:
    r = Rig()
    r.seat("roosevelt")
    r.close_session_zero()
    r.set_value("gallup_fdr_about_right", 100)
    r.set_value("opinion_target", 0)
    (item,) = poll_news(opinion.on_day(r.state, MONDAY))
    longest = max(len(o.name) for o in r.state.outlets.values())
    assert longest + len(": ") + len(item.headline) <= LINE
    assert item.headline.endswith(" down to 99%")
