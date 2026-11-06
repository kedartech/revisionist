"""Each seat's press: one page per outlet per news event, public facts only."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.ontology import Entity, EntityKind, Seat, SeatKind
from revisionist.core.project import project
from revisionist.core.realism.document import BodyField, DocumentKind
from revisionist.core.realism.press import news_pages
from revisionist.core.realism.war import NewsEvent, NewsTopic, Outlet
from revisionist.core.state import State
from revisionist.engine.prose import Author, TemplateProseWriter, author_of
from tests.test_war_contract import FDR, GER, USA, event, world

UK, CHURCHILL, TIMES = (EntityId(k) for k in ("uk", "churchill", "times"))
LEDGER = EntityId("ledger")
SEAT_UK = SeatId("seat-churchill")
SEAT_US = SeatId("seat-fdr")
SECRET = "ZEBRA-PRIVATE-7731"
DAY = date(1941, 12, 11)


def press_world() -> State:
    state = world()
    extra = {
        UK: Entity(entity_id=UK, kind=EntityKind.POLITY, name="uk"),
        TIMES: Entity(entity_id=TIMES, kind=EntityKind.ORG, name="The Times", parent=UK),
        CHURCHILL: Entity(entity_id=CHURCHILL, kind=EntityKind.PERSON, name="W", parent=UK),
    }
    seat = Seat(seat_id=SEAT_UK, kind=SeatKind.PLAYER, name="w", embodies=CHURCHILL)
    outlet = Outlet(outlet_id=TIMES, polity=UK, name="The Times", voice="Measured.")
    return state.model_copy(
        update={
            "entities": {**state.entities, **extra},
            "seats": {**state.seats, SEAT_UK: seat},
            "outlets": {**state.outlets, TIMES: outlet},
        }
    )


def news(on: date = DAY) -> NewsEvent:
    return NewsEvent(
        news_id="n1",
        on=on,
        topic=NewsTopic.WAR_DECLARED,
        subject=GER,
        obj=USA,
        facts=(BodyField(label="Declared by", value="Germany"),),
        headline="Germany declares war on the United States of America now",
    )


def folded(state: State, *payloads: ev.Payload) -> State:
    out = state
    for p in payloads:
        out = replay([event(p, out)], initial=out)
    return out


def test_one_page_per_outlet_each_visible_to_its_own_country() -> None:
    state = folded(press_world(), ev.NewsReported(news=news()))
    pages = news_pages(state, DAY)
    assert len(pages) == 2
    state = folded(state, *pages)
    state = state.model_copy(update={"in_world_date": DAY})
    us, uk = project(state, SEAT_US).documents, project(state, SEAT_UK).documents
    assert len(us) == len(uk) == 1
    (us_page,), (uk_page,) = us.values(), uk.values()
    assert us_page.title.startswith("Ledger: ") and uk_page.title.startswith("The Times: ")
    assert len(us_page.title) <= 60 and us_page.title.endswith("…")
    assert us_page.body == uk_page.body == news().facts
    assert us_page.kind is DocumentKind.PRESS
    assert us_page.author == LEDGER and uk_page.author == TIMES
    assert {state.documents[d].truth.news_id for d in state.documents} == {"n1"}


def test_a_page_leaks_nothing_private() -> None:
    from revisionist.core.ontology import Fact
    from revisionist.core.visibility import private_to

    state = folded(press_world(), ev.NewsReported(news=news()))
    fact = Fact(fact_id="f1", subject=FDR, predicate="plans", obj=SECRET, scope=private_to(SEAT_US))
    state = folded(state, ev.FactAsserted(fact=fact))
    dump = "".join(p.model_dump_json() for p in news_pages(state, DAY))
    assert SECRET not in dump


def test_second_call_and_future_event_emit_nothing() -> None:
    state = folded(press_world(), ev.NewsReported(news=news()))
    assert news_pages(state, DAY - timedelta(days=1)) == []
    state = folded(state, *news_pages(state, DAY))
    assert news_pages(state, DAY) == []
    assert news_pages(state, DAY + timedelta(days=3)) == []


def test_author_of_an_outlet_and_template_prose() -> None:
    state = press_world()
    author = author_of(state, TIMES)
    assert author.voice == "Measured." and author.name == "The Times"
    assert author.office == "newspaper"
    state = folded(state, ev.NewsReported(news=news()))
    page = news_pages(state, DAY)[0].document
    written = TemplateProseWriter().write(Author(**author.model_dump()), [page])
    assert written.prose[page.doc_id]
