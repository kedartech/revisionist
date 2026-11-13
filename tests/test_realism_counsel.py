"""Counsel (Phase 4): the request holds only the person's projection, the reply is the
seat's alone, the world does not move, and truth never reaches the model."""

import json
from collections.abc import Sequence
from datetime import date, timedelta
from typing import get_type_hints

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import state_hash
from revisionist.core.ids import DocumentId, EntityId, EventId, SeatId, derived_id
from revisionist.core.ontology import Controller, EntityKind
from revisionist.core.project import project
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.person import PersonView, project_person
from revisionist.core.realism.reach import channels_to, takes_meeting
from revisionist.core.report import leak_report
from revisionist.core.sealing import seal_holder
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC as PUBLIC_SCOPE
from revisionist.core.visibility import Scope, Visibility, private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import counsel, realism_tick, session_zero
from revisionist.engine.counsel import (
    Asker,
    ClaudeCounsellor,
    Counsellor,
    CounselRefusedError,
    Spoken,
    consult,
    counsel_prompt,
    counsel_records,
)
from revisionist.engine.llm import RecordedTransport, Reply, Request, TransportError
from revisionist.engine.store import EventStore, MemoryStore, load_state
from revisionist.engine.web import server
from revisionist.engine.web.realism_snapshot import counsel_lines
from tests.counsel_scenario import CANARY, QUESTION, hopkins, plant_memo, roosevelt_seat, ticked
from tests.handwritten import COUNSEL, COUNSEL_BY_QUESTION, GREER_QUESTION, greer_fired
from tests.test_realism_tick import CAMPAIGN


class Capturing:
    def __init__(self) -> None:
        self.inner = RecordedTransport(COUNSEL)
        self.sent: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.sent.append(request)
        return self.inner.call(request)


def ready() -> EventStore:
    store = MemoryStore()
    ticked(store)
    plant_memo(store)
    return store


def held(store: EventStore) -> list[ev.Event]:
    return [e for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.CounselHeld)]


def test_the_request_holds_only_the_persons_projection() -> None:
    store = ready()
    state = load_state(store, CAMPAIGN)
    seat, person = roosevelt_seat(store), hopkins(store)
    transport = Capturing()
    consult(store, CAMPAIGN, seat, person, QUESTION, ClaudeCounsellor(transport))
    (req,) = transport.sent
    asker = Asker(
        name="Franklin D. Roosevelt", office=state.cards[state.seats[seat].embodies].office
    )
    seen = project_person(state, person, seat)
    assert req.prompt == counsel_prompt(seen, asker, ChannelKind.IN_PERSON, QUESTION)
    assert req.call_class == "counsel"
    mine = project(state, seat).documents
    assert set(mine) <= {x.doc_id for x in seen.documents}, "Hopkins knows the desk he serves"
    for page in seen.documents:
        assert page.title in req.prompt
    marshall = project_person(state, person_named(store, "George C. Marshall"), seat)
    not_his = [d for k, d in mine.items() if k not in {x.doc_id for x in marshall.documents}]
    assert not_his, "Roosevelt should hold pages Marshall does not"
    told = counsel_prompt(marshall, asker, ChannelKind.IN_PERSON, QUESTION)
    for page in not_his:
        assert page.title not in told


def test_the_reply_is_private_to_the_seat_and_its_cost_is_logged() -> None:
    store = ready()
    seat = roosevelt_seat(store)
    out = consult(store, CAMPAIGN, seat, hopkins(store), QUESTION, ClaudeCounsellor(Capturing()))
    assert "500 a month" in out.text and out.channel is ChannelKind.IN_PERSON
    (record,) = held(store)
    assert record.scope.visibility is Visibility.PRIVATE and record.scope.known_by == {seat}
    assert seal_holder(record) == seat
    assert [p.text for p in counsel_records(list(store.read(CAMPAIGN)), seat)] == [out.text]
    (cost,) = [e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.CostLogged)]
    assert cost.purpose == "counsel" and cost.costs[0].call_class == "counsel"


def test_counsel_changes_nothing_in_the_world() -> None:
    store = ready()
    before = load_state(store, CAMPAIGN)
    consult(
        store,
        CAMPAIGN,
        roosevelt_seat(store),
        hopkins(store),
        QUESTION,
        ClaudeCounsellor(Capturing()),
    )
    after = load_state(store, CAMPAIGN)
    assert after.last_seq == before.last_seq + 2  # counsel_held and cost_logged, both records
    assert state_hash(after.model_copy(update={"last_seq": before.last_seq})) == state_hash(before)
    assert after.orders == before.orders and after.in_world_date == before.in_world_date


def test_the_truth_canary_never_reaches_a_counsel_request() -> None:
    store = ready()
    state = load_state(store, CAMPAIGN)
    assert any(r.canary == CANARY for d in state.documents.values() for r in d.truth.truth_refs)
    transport = Capturing()
    consult(
        store,
        CAMPAIGN,
        roosevelt_seat(store),
        hopkins(store),
        QUESTION,
        ClaudeCounsellor(transport),
    )
    for req in transport.sent:
        assert CANARY not in req.system + req.prompt + json.dumps(req.schema)
        for secret in ("truth_refs", "loyalty", "doctrine", "interests"):
            assert secret not in req.prompt
    assert leak_report(load_state(store, CAMPAIGN), store.read(CAMPAIGN)) == []


def test_only_a_living_person_the_seat_can_reach_can_be_consulted() -> None:
    store = ready()
    state = load_state(store, CAMPAIGN)
    seat = roosevelt_seat(store)
    polity = next(e for e, x in state.entities.items() if x.kind is EntityKind.POLITY)
    with pytest.raises(CounselRefusedError, match="within your reach"):
        consult(store, CAMPAIGN, seat, polity, QUESTION, ClaudeCounsellor(Capturing()))
    with pytest.raises(CounselRefusedError, match="within your reach"):
        consult(store, CAMPAIGN, seat, EntityId("nobody"), QUESTION, ClaudeCounsellor(Capturing()))
    with pytest.raises(CounselRefusedError):
        consult(store, CAMPAIGN, seat, hopkins(store), "   ", ClaudeCounsellor(Capturing()))
    assert held(store) == []


# Rank 3, so a head of government outside his chain is always met.
OUTER = "Boris Shaposhnikov"
SEALED = "Shaposhnikov's own note on the Moscow front, for no one else"
SHARED = "Shaposhnikov to the President, on the supply protocol"


def person_named(store: EventStore, name: str) -> EntityId:
    return next(e for e, x in load_state(store, CAMPAIGN).entities.items() if x.name == name)


def plant_page(store: EventStore, author: EntityId, title: str, scope: Scope, key: str) -> None:
    """A page by ``author`` that arrived today, seen by ``scope`` only."""
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
        classification=Classification.CONFIDENTIAL,
        title=title,
        body=(),
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


class Kept:
    """A transport that keeps each request and fails it, so nothing is written."""

    def __init__(self) -> None:
        self.sent: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.sent.append(request)
        raise TransportError("kept")


def test_an_outer_contact_is_consulted_over_the_first_channel_that_reaches_them() -> None:
    store = ready()
    state = load_state(store, CAMPAIGN)
    seat = roosevelt_seat(store)
    me = state.seats[seat].embodies
    outer = person_named(store, OUTER)
    assert outer not in {c.person for c in state.cards[me].inner_circle}
    channels: list[ChannelKind] = []

    class Keep:
        def speak(
            self, person: PersonView, asker: Asker, channel: ChannelKind, question: str
        ) -> Spoken:
            channels.append(channel)
            return Spoken(text="We need lorries before tanks.")

    out = consult(store, CAMPAIGN, seat, outer, QUESTION, Keep())
    assert out.person == OUTER
    assert channels == [out.channel] and out.channel == channels_to(state, me, outer)[0]
    (h,) = held(store)
    assert isinstance(h.payload, ev.CounselHeld) and h.payload.channel == out.channel
    assert h.scope == private_to(seat)


def test_an_outer_contact_speaks_only_from_pages_the_asking_seat_also_holds() -> None:
    store = ready()
    seat = roosevelt_seat(store)
    outer = person_named(store, OUTER)
    plant_page(store, outer, SEALED, private_to(SeatId(derived_id(CAMPAIGN, "x"))), "sealed")
    plant_page(store, outer, SHARED, private_to(seat), "shared")
    transport = Kept()
    with pytest.raises(TransportError):
        consult(store, CAMPAIGN, seat, outer, QUESTION, ClaudeCounsellor(transport))
    (req,) = transport.sent
    assert SHARED in req.prompt
    assert SEALED not in req.prompt


def test_the_inner_circle_still_speaks_from_all_its_own_pages() -> None:
    store = ready()
    seat = roosevelt_seat(store)
    plant_page(store, hopkins(store), SEALED, private_to(SeatId(derived_id(CAMPAIGN, "x"))), "s")
    transport = Kept()
    with pytest.raises(TransportError):
        consult(store, CAMPAIGN, seat, hopkins(store), QUESTION, ClaudeCounsellor(transport))
    (req,) = transport.sent
    assert SEALED in req.prompt


def with_twin(state: State, of: EntityId, key: str) -> State:
    """``state`` with a second person of the same name, placed first in the entities."""
    twin = EntityId(derived_id(CAMPAIGN, key))
    copy = state.entities[of].model_copy(update={"entity_id": twin})
    return state.model_copy(update={"entities": {twin: copy, **state.entities}})


def test_a_name_resolves_to_the_inner_circle_first_and_an_unclear_one_is_refused() -> None:
    store = ready()
    seat = roosevelt_seat(store)
    state = with_twin(load_state(store, CAMPAIGN), hopkins(store), "twin-hopkins")
    assert server._reachable(state, seat, "Harry L. Hopkins") == hopkins(store)
    state = with_twin(state, person_named(store, OUTER), "twin-outer")
    with pytest.raises(ValueError, match="More than one"):
        server._reachable(state, seat, OUTER)


def test_an_outsider_who_would_not_take_a_meeting_does_not_answer() -> None:
    store = ready()
    state = load_state(store, CAMPAIGN)
    seat = roosevelt_seat(store)
    konoe = person_named(store, "Fumimaro Konoe")
    assert not takes_meeting(state, state.seats[seat].embodies, konoe, "counsel", state.tick)
    transport = Kept()
    for question in (QUESTION, "Will Tokyo talk before the winter?"):
        with pytest.raises(CounselRefusedError, match="Fumimaro Konoe did not answer"):
            consult(store, CAMPAIGN, seat, konoe, question, ClaudeCounsellor(transport))
    assert transport.sent == [] and held(store) == []


def test_a_person_with_no_channel_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    store = ready()
    monkeypatch.setattr(counsel, "channels_to", lambda *_: (), raising=False)
    with pytest.raises(CounselRefusedError, match="within your reach"):
        consult(
            store,
            CAMPAIGN,
            roosevelt_seat(store),
            person_named(store, OUTER),
            QUESTION,
            ClaudeCounsellor(Capturing()),
        )
    assert held(store) == []


def test_a_failed_call_writes_nothing() -> None:
    class Down:
        def call(self, request: Request) -> Reply:
            raise TransportError("model unavailable")

    store = ready()
    before = load_state(store, CAMPAIGN).last_seq
    with pytest.raises(TransportError):
        consult(
            store,
            CAMPAIGN,
            roosevelt_seat(store),
            hopkins(store),
            QUESTION,
            ClaudeCounsellor(Down()),
        )
    assert load_state(store, CAMPAIGN).last_seq == before


def test_a_counsellor_takes_a_person_view_never_state() -> None:
    hints = get_type_hints(Counsellor.speak)
    assert hints["person"] is PersonView and State not in hints.values()
    store = ready()
    state = load_state(store, CAMPAIGN)
    with pytest.raises(TypeError):
        counsel_prompt(state, Asker(name="x"), ChannelKind.LETTER, "q")  # type: ignore[arg-type]

    class Echo:
        def speak(
            self, person: PersonView, asker: Asker, channel: ChannelKind, question: str
        ) -> Spoken:
            return Spoken(text=f"{len(person.documents)} papers")

    seq: Sequence[Counsellor] = [Echo()]
    out = consult(store, CAMPAIGN, roosevelt_seat(store), hopkins(store), QUESTION, seq[0])
    assert out.text.endswith("papers")


def advance_to(store: EventStore, day: date) -> None:
    state = load_state(store, CAMPAIGN)
    store.append_all(
        [
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "advance", day.isoformat())),
                campaign_id=CAMPAIGN,
                seq=state.last_seq + 1,
                tick=state.tick,
                scope=PUBLIC_SCOPE,
                payload=ev.DateAdvanced(to=day),
                versions=cmp.versions(),
            )
        ]
    )


def test_counsel_lines_carry_the_day_they_were_held_and_the_tie() -> None:
    store = ready()
    seat = roosevelt_seat(store)
    first = load_state(store, CAMPAIGN).in_world_date
    assert first is not None

    class Says:
        def speak(
            self, person: PersonView, asker: Asker, channel: ChannelKind, question: str
        ) -> Spoken:
            return Spoken(text="Noted.")

    consult(store, CAMPAIGN, seat, hopkins(store), "Harry, a word?", Says())
    later = first + timedelta(days=3)
    advance_to(store, later)
    consult(store, CAMPAIGN, seat, person_named(store, OUTER), "Trucks or tanks?", Says())
    state = load_state(store, CAMPAIGN)
    lines = counsel_lines(project(state, seat), list(store.read(CAMPAIGN)), seat)
    assert [(x["person"], x["question"], x["tie"]) for x in lines] == [
        (OUTER, "Trucks or tanks?", "outer"),
        ("Harry L. Hopkins", "Harry, a word?", "inner"),
    ]
    assert [x["day_iso"] for x in lines] == [later.isoformat(), first.isoformat()]
    assert lines[0]["day"] == f"{later.day} {later:%B %Y}"
    assert lines[0]["answer"] == "Noted." and lines[0]["channel"] == "telephone"


GREER = "The Greer has been fired on: settle the U-boats' rules toward American ships."
GREER_HEADLINE = "USS Greer and U-652 exchange fire south of Iceland"


def test_raeder_asked_after_the_greer_knows_the_crisis_on_his_principals_desk() -> None:
    store = MemoryStore()
    seat, raeder = greer_fired(store)
    state = load_state(store, CAMPAIGN)
    assert GREER in [m.text for m in state.mandates.values() if m.seat_id == seat]
    transport = Capturing()
    out = consult(store, CAMPAIGN, seat, raeder, GREER_QUESTION, ClaudeCounsellor(transport))
    (req,) = transport.sent
    assert "## Before your principal\n" in req.prompt and GREER in req.prompt
    assert "## The news\n" in req.prompt and GREER_HEADLINE in req.prompt
    assert out.text.endswith(COUNSEL_BY_QUESTION[GREER_QUESTION])


class Counting:
    """A counsellor that answers and keeps the name of everyone it spoke as."""

    def __init__(self) -> None:
        self.spoke: list[str] = []

    def speak(
        self, person: PersonView, asker: Asker, channel: ChannelKind, question: str
    ) -> Spoken:
        self.spoke.append(person.name)
        cost = ev.CallCost(call_class="counsel", model="m", input_tokens=1, output_tokens=1, usd=0)
        return Spoken(text="In my view, wait.", cost=cost)


def humans(store: EventStore, *who: str) -> dict[str, SeatId]:
    """Autumn 1941 with a human seated as each of ``who``, play open."""
    decl = cmp.load_world(cmp.world_path("autumn-1941"))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    keys = resolve_keys(decl, CAMPAIGN)
    seats: dict[str, SeatId] = {}
    for key in who:
        person = EntityId(keys[key])
        seats[key] = SeatId(derived_id(CAMPAIGN, "seat", person))
        name = load_state(store, CAMPAIGN).entities[person].name
        session_zero.claim(store, CAMPAIGN, seats[key], name)
    realism_tick.open_play(store, CAMPAIGN)
    return seats


def test_a_person_another_human_plays_speaks_for_themselves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryStore()
    seats = humans(store, "roosevelt", "churchill", "stalin")
    state = load_state(store, CAMPAIGN)
    me = state.seats[seats["roosevelt"]].embodies
    inner = {c.person for c in state.cards[me].inner_circle}
    churchill = state.seats[seats["churchill"]].embodies
    stalin = state.seats[seats["stalin"]].embodies
    assert churchill in inner and stalin not in inner
    assert all(s.controller is Controller.HUMAN for s in state.seats.values())

    def no_roll(*_: object) -> bool:
        raise AssertionError("a meeting roll was spent")

    monkeypatch.setattr(counsel, "takes_meeting", no_roll)
    before = list(store.read(CAMPAIGN))
    counting = Counting()
    for person, name in ((churchill, "Winston Churchill"), (stalin, "Joseph Stalin")):
        with pytest.raises(CounselRefusedError) as refused:
            consult(store, CAMPAIGN, seats["roosevelt"], person, QUESTION, counting)
        assert str(refused.value) == f"{name} speaks for themselves: write to them."
        assert counting.spoke == []
    assert list(store.read(CAMPAIGN)) == before


def test_only_a_person_another_human_plays_is_refused() -> None:
    store = MemoryStore()
    seats = humans(store, "roosevelt", "churchill")
    counting = Counting()
    hopkins_ = hopkins(store)
    out = consult(store, CAMPAIGN, seats["roosevelt"], hopkins_, QUESTION, counting)
    assert out.person == "Harry L. Hopkins" and counting.spoke == ["Harry L. Hopkins"]
    kinds = [type(e.payload) for e in store.read(CAMPAIGN)][-2:]
    assert kinds == [ev.CounselHeld, ev.CostLogged]
    me = load_state(store, CAMPAIGN).seats[seats["roosevelt"]].embodies
    with pytest.raises(CounselRefusedError, match="is not within your reach"):
        consult(store, CAMPAIGN, seats["roosevelt"], me, QUESTION, counting)
    assert counting.spoke == ["Harry L. Hopkins"]


def test_a_person_an_ai_seat_holds_is_still_voiced() -> None:
    store = ready()
    state = load_state(store, CAMPAIGN)
    churchill = person_named(store, "Winston Churchill")
    (holder,) = [s for s in state.seats.values() if s.embodies == churchill]
    assert holder.controller is Controller.AI
    counting = Counting()
    out = consult(store, CAMPAIGN, roosevelt_seat(store), churchill, QUESTION, counting)
    assert out.person == "Winston Churchill" and counting.spoke == ["Winston Churchill"]
