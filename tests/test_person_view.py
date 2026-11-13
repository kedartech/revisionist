"""What a consulted person knows: pages another seat holds stay with that seat, the news is
everyone's, and a person who serves the asker knows the asker's desk."""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.goals import Ordered
from revisionist.core.ids import DocumentId, EntityId, EventId, MandateId, SeatId, derived_id
from revisionist.core.ontology import Controller, SeatKind
from revisionist.core.realism.agenda import Mandate, MandateKind, MandateStatus
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.effect import EffectKind
from revisionist.core.realism.person import PersonView, project_person
from revisionist.core.realism.war import NewsEvent, NewsTopic
from revisionist.core.state import State
from revisionist.core.visibility import Scope, private_to
from revisionist.engine import campaign as cmp
from revisionist.engine import counsel
from revisionist.engine.counsel import Asker, ClaudeCounsellor, consult, counsel_prompt
from revisionist.engine.llm import Reply, Request, TransportError
from revisionist.engine.store import EventStore, MemoryStore, load_state
from tests.counsel_scenario import QUESTION, hopkins, roosevelt_seat, ticked
from tests.test_realism_tick import CAMPAIGN

HUMAN_CANARY = "CANARY-HUMAN-SEAT-PAGE-61c2"
AI_CANARY = "CANARY-AI-SEAT-PAGE-0d9e"
SHARED = "The Prime Minister to the President, on the convoys"
CHURCHILL = "Winston Churchill"
MARSHALL = "George C. Marshall"
HEADLINE = "Iceland garrison relieved by American troops"
LATER = "Headline not yet out"


class Kept:
    """A transport that keeps each request and fails it, so nothing is written."""

    def __init__(self) -> None:
        self.sent: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.sent.append(request)
        raise TransportError("kept")


def person_named(store: EventStore, name: str) -> EntityId:
    return next(e for e, x in load_state(store, CAMPAIGN).entities.items() if x.name == name)


def seat_of(state: State, person: EntityId) -> SeatId:
    (seat,) = [s.seat_id for s in state.seats.values() if s.embodies == person]
    return seat


def plant_page(store: EventStore, author: EntityId, title: str, scope: Scope, key: str) -> None:
    state = load_state(store, CAMPAIGN)
    today = state.in_world_date
    assert today is not None
    doc_id = DocumentId(derived_id(CAMPAIGN, key))
    view = DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.MEMO,
        author=author,
        issued=today,
        arrives=today,
        channel=ChannelKind.CABLE,
        classification=Classification.SECRET,
        title=title,
        body=(BodyField(label="Escorts", value=12, unit="ships"),),
        scope=scope,
    )
    store.append_all(
        [
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, key, "event")),
                campaign_id=CAMPAIGN,
                seq=state.last_seq + 1,
                tick=state.tick,
                scope=scope,
                payload=ev.DocumentIssued(document=view, truth=DocumentTruth(doc_id=doc_id)),
                versions=cmp.versions(),
            )
        ]
    )


def churchills_pages(canary: str) -> tuple[EventStore, SeatId, EntityId]:
    """Churchill's private page (titled ``canary``) and one he sent the President."""
    store = MemoryStore()
    ticked(store)
    state = load_state(store, CAMPAIGN)
    churchill = person_named(store, CHURCHILL)
    roosevelt = roosevelt_seat(store)
    assert churchill in {
        c.person for c in state.cards[state.seats[roosevelt].embodies].inner_circle
    }
    plant_page(store, churchill, canary, private_to(seat_of(state, churchill)), "private")
    plant_page(store, churchill, SHARED, private_to(roosevelt), "shared")
    return store, roosevelt, churchill


def played_by_a_human(state: State, person: EntityId) -> State:
    seat = state.seats[seat_of(state, person)]
    human = seat.model_copy(update={"kind": SeatKind.PLAYER, "controller": Controller.HUMAN})
    return state.model_copy(update={"seats": {**state.seats, seat.seat_id: human}})


def prompt(view: PersonView) -> str:
    return counsel_prompt(view, Asker(name="Franklin D. Roosevelt"), ChannelKind.CABLE, QUESTION)


def test_a_human_seats_private_page_stays_out_when_another_seat_consults_that_person(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, roosevelt, churchill = churchills_pages(HUMAN_CANARY)
    state = played_by_a_human(load_state(store, CAMPAIGN), churchill)
    assert state.seats[seat_of(state, churchill)].controller is Controller.HUMAN
    monkeypatch.setattr(counsel, "load_state", lambda *_: state)
    transport = Kept()
    with pytest.raises(TransportError):
        consult(store, CAMPAIGN, roosevelt, churchill, QUESTION, ClaudeCounsellor(transport))
    (req,) = transport.sent
    assert SHARED in req.prompt
    assert HUMAN_CANARY not in req.system + req.prompt


def test_an_ai_seats_private_page_stays_out_of_the_counsel_request() -> None:
    store, roosevelt, churchill = churchills_pages(AI_CANARY)
    state = load_state(store, CAMPAIGN)
    assert state.seats[seat_of(state, churchill)].controller is Controller.AI
    transport = Kept()
    with pytest.raises(TransportError):
        consult(store, CAMPAIGN, roosevelt, churchill, QUESTION, ClaudeCounsellor(transport))
    (req,) = transport.sent
    assert SHARED in req.prompt
    assert AI_CANARY not in req.system + req.prompt


def test_the_askers_own_person_keeps_every_page_they_wrote() -> None:
    store = MemoryStore()
    ticked(store)
    state = load_state(store, CAMPAIGN)
    roosevelt = roosevelt_seat(store)
    me = state.seats[roosevelt].embodies
    churchill = seat_of(state, person_named(store, CHURCHILL))
    plant_page(store, me, "The President to the Prime Minister", private_to(churchill), "sent")
    seen = project_person(load_state(store, CAMPAIGN), me, roosevelt)
    assert "The President to the Prime Minister" in [d.title for d in seen.documents]


def with_news(state: State) -> State:
    today = state.in_world_date
    assert today is not None
    subject = next(iter(state.entities))
    news = {
        n.news_id: n
        for n in (
            NewsEvent(
                news_id="n-today",
                on=today,
                topic=NewsTopic.STATEMENT,
                subject=subject,
                headline=HEADLINE,
                facts=(BodyField(label="Troops landed", value=4000, unit="men"),),
            ),
            NewsEvent(
                news_id="n-later",
                on=today + timedelta(days=1),
                topic=NewsTopic.STATEMENT,
                subject=subject,
                headline=LATER,
            ),
        )
    }
    return state.model_copy(update={"news": news})


def test_every_person_knows_the_news_to_date_and_none_later() -> None:
    store = MemoryStore()
    ticked(store)
    state = with_news(load_state(store, CAMPAIGN))
    roosevelt = roosevelt_seat(store)
    for person in (hopkins(store), person_named(store, MARSHALL), person_named(store, CHURCHILL)):
        view = project_person(state, person, roosevelt)
        assert [n.headline for n in view.news] == [HEADLINE]
        seen = prompt(view)
        assert HEADLINE in seen and "4000" in seen
        assert LATER not in seen


def foreign_mandate(state: State, seat: SeatId) -> State:
    today = state.in_world_date
    assert today is not None
    person = state.seats[seat].embodies
    m = Mandate(
        mandate_id=MandateId(derived_id(CAMPAIGN, "foreign-mandate")),
        seat_id=seat,
        kind=MandateKind.CRISIS,
        text="Another desk's crisis, not the President's",
        condition=Ordered(person=person, effect=EffectKind.STATEMENT),
        issued=today,
        expires=today + timedelta(days=7),
        scope=private_to(seat),
    )
    return state.model_copy(update={"mandates": {**state.mandates, m.mandate_id: m}})


def test_a_person_who_serves_the_asker_knows_the_askers_live_mandates() -> None:
    store = MemoryStore()
    ticked(store)
    roosevelt = roosevelt_seat(store)
    raw = load_state(store, CAMPAIGN)
    state = foreign_mandate(raw, seat_of(raw, person_named(store, CHURCHILL)))
    mine = [
        m
        for m in state.mandates.values()
        if m.seat_id == roosevelt and m.status is MandateStatus.LIVE
    ]
    assert mine and any(m.status is not MandateStatus.LIVE for m in state.mandates.values())
    harry = project_person(state, hopkins(store), roosevelt)
    assert sorted(harry.mandates) == sorted(m.text for m in mine)
    seen = prompt(harry)
    for m in state.mandates.values():
        assert (m.text in seen) == (m in mine)
    marshall = project_person(state, person_named(store, MARSHALL), roosevelt)
    assert marshall.mandates == ()
    assert all(m.text not in prompt(marshall) for m in state.mandates.values())


def test_a_person_who_serves_the_asker_holds_the_askers_pages() -> None:
    store = MemoryStore()
    ticked(store)
    roosevelt = roosevelt_seat(store)
    state = load_state(store, CAMPAIGN)
    desk = {
        k
        for k, d in state.documents.items()
        if d.view.scope.visible_to(roosevelt)
        and d.view.arrives <= (state.in_world_date or date.min)
    }
    harry = {d.doc_id for d in project_person(state, hopkins(store), roosevelt).documents}
    marshall = {
        d.doc_id for d in project_person(state, person_named(store, MARSHALL), roosevelt).documents
    }
    assert desk and desk <= harry
    assert not desk <= marshall


def bare(**update: object) -> PersonView:
    page = DocumentView(
        doc_id=DocumentId("d1"),
        kind=DocumentKind.LETTER,
        author=EntityId("molotov"),
        issued=date(1941, 9, 4),
        arrives=date(1941, 9, 4),
        channel=ChannelKind.CABLE,
        classification=Classification.CONFIDENTIAL,
        title="On the supply protocol",
        body=(BodyField(label="Tanks a month", value=500, unit="tanks"),),
        scope=private_to(SeatId("s")),
    )
    view = PersonView(
        person=EntityId("molotov"),
        name="Vyacheslav Molotov",
        voice="Stone-faced.",
        today=date(1941, 9, 4),
        documents=(page,),
    )
    return view.model_copy(update=update)


def test_a_person_with_no_news_and_no_principal_gets_todays_prompt_bytes() -> None:
    text = counsel_prompt(bare(), Asker(name="Winston Churchill"), ChannelKind.CABLE, "Tanks?")
    assert text == (
        "## You are\nVyacheslav Molotov\nVoice: Stone-faced.\n\n## Today\n1941-09-04\n\n"
        '## Your papers\n[{"kind": "letter", "title": "On the supply protocol", '
        '"issued": "1941-09-04", "channel": "cable", "lines": [{"label": "Tanks a month", '
        '"value": 500, "unit": "tanks"}]}]\n\n## Winston Churchill asks you, by cable\nTanks?'
    )
    told = counsel_prompt(
        bare(mandates=("Settle the convoys.",)), Asker(name="x"), ChannelKind.CABLE, "Tanks?"
    )
    assert "## Before your principal\n" in told and "## The news" not in told
