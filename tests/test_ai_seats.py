"""Seats for people nobody plays are inert: nothing is issued to them, nothing is
written for them, and the human's game runs exactly as it does without them."""

from collections import Counter
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, DocumentId, EntityId, FeatureId, SeatId, derived_id
from revisionist.core.ontology import Controller, SeatKind
from revisionist.core.project import project
from revisionist.core.realism import actors, answering
from revisionist.core.realism.card import ChannelKind, superiors
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.war import NewsTopic
from revisionist.core.resolution import TickStage
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.core.world_compile import compile_world, object_id, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.advise import advise
from revisionist.engine.emit import Emitter
from revisionist.engine.prose import Author, Written, template_prose
from revisionist.engine.realism_tick import file_order, run_realism_tick
from revisionist.engine.store import EventStore, MemoryStore, load_state
from tests import fog_twins as ft
from tests import test_ask_answers as aa
from tests import test_realism_locks as toy
from tests.test_advise import FakeTransport
from tests.test_territory_model import CAMPAIGN as TOY

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
WORLD = "autumn-1941"
POINTS = str(Path(__file__).parent / "worlds" / "autumn-1941-points.yaml")
"""The 1941 world before territories, for the case that sails a fleet between places."""
TICKS = 8


class Counting:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[DocumentId, ...]]] = []

    def write(self, author: Author, pages: Sequence[DocumentView]) -> Written:
        self.calls.append((author.name, tuple(p.doc_id for p in pages)))
        return Written(prose={p.doc_id: template_prose(author, p) for p in pages})


def seated(store: EventStore, who: str, world: str = WORLD) -> SeatId:
    decl = cmp.load_world(cmp.world_path(world))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    realism_tick.seat_player(store, CAMPAIGN, EntityId(resolve_keys(decl, CAMPAIGN)[who]))
    (seat,) = load_state(store, CAMPAIGN).seats
    return seat


def churchill(store: EventStore) -> SeatId:
    return seated(store, "churchill")


def seat_the_rest(store: EventStore) -> list[SeatId]:
    """An AI seat for every other playable person."""
    state = load_state(store, CAMPAIGN)
    em = Emitter(store, state, cmp.versions())
    made = actors.unseated(state, [p for p, c in sorted(state.cards.items()) if c.playable])
    em.commit([em.event(m, scope=PUBLIC) for m in made])
    return [m.seat.seat_id for m in made]


def played(store: EventStore, writer: Counting, ticks: int = TICKS) -> State:
    for _ in range(ticks):
        run_realism_tick(store, CAMPAIGN, prose=writer)
    return load_state(store, CAMPAIGN)


def shape(store: EventStore) -> Counter[str]:
    return Counter(e.payload.kind for e in store.read(CAMPAIGN) if e.payload.kind != "seat_created")


def seen(state: State, seat: SeatId) -> dict[str, Any]:
    view = project(state, seat).model_dump(mode="json")
    view.pop("seats")
    return view


def test_an_unplayed_person_gets_an_ai_seat_once() -> None:
    store = MemoryStore()
    human = churchill(store)
    made = seat_the_rest(store)
    state = load_state(store, CAMPAIGN)
    roster = cmp.load_world(cmp.world_path("autumn-1941")).roster
    assert len(made) == len(roster) - 1 and human not in made
    for seat_id in made:
        seat = state.seats[seat_id]
        assert seat.kind is SeatKind.FACTION and seat.controller is Controller.AI
        assert seat.slots == 0 and seat.name == state.entities[seat.embodies].name
    assert actors.unseated(state, [s.embodies for s in state.seats.values()]) == []
    assert actors.readers(state) == frozenset({human})


def test_ai_seats_change_nothing_the_human_sees_or_the_writer_is_asked() -> None:
    plain, crowded = MemoryStore(), MemoryStore()
    human = churchill(plain)
    assert churchill(crowded) == human
    seat_the_rest(crowded)
    alone, among = Counting(), Counting()
    before = played(plain, alone)
    after = played(crowded, among)
    assert before.in_world_date == after.in_world_date
    assert len(alone.calls) > 0
    assert among.calls == alone.calls
    assert shape(crowded) == shape(plain)
    assert seen(after, human) == seen(before, human)


def test_nothing_is_addressed_to_an_ai_seat() -> None:
    store = MemoryStore()
    human = churchill(store)
    made = set(seat_the_rest(store))
    state = played(store, Counting())
    for e in store.read(CAMPAIGN):
        if e.payload.kind not in OWN_ORDERS | NATION_STATE:
            assert not (made & e.scope.known_by), e.payload.kind
    assert {m.seat_id for m in state.mandates.values()} <= {human}


OWN_ORDERS = frozenset(
    {
        "order_drafted",
        "order_routed",
        "order_step_taken",
        "order_settled",
        "order_executed",
        "effects_applied",
        "influence_decided",
        "relationship_set",
        "answer_planned",
        "answer_made",
    }
)
"""What an AI seat may be scoped: its answers and the orders they file, as a player's
orders are scoped to the player."""

NATION_STATE = frozenset(
    {"piece_stepped", "economy_set", "step_refused", "trade_set", "group_moved"}
)
"""A nation's own state, scoped to its seats as to a player's (``realism_tick._nation_scope``):
no page, report or mandate."""


def test_a_page_only_an_ai_seat_holds_is_never_sent_to_the_writer() -> None:
    store = MemoryStore()
    churchill(store)
    (ai, *_) = seat_the_rest(store)
    writer = Counting()
    run_realism_tick(store, CAMPAIGN, prose=writer, stop_after=TickStage.FEEDS)
    state = load_state(store, CAMPAIGN)
    today = state.in_world_date
    assert today is not None
    doc_id = DocumentId(derived_id(CAMPAIGN, "document", "stray"))
    page = DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.REPORT,
        author=state.seats[ai].embodies,
        issued=today,
        arrives=today,
        channel=ChannelKind.IN_PERSON,
        classification=Classification.CONFIDENTIAL,
        title="A stray page",
        body=(BodyField(label="Men", value=22000),),
        scope=private_to(ai),
    )
    em = Emitter(store, state, cmp.versions())
    issued = ev.DocumentIssued(document=page, truth=DocumentTruth(doc_id=doc_id))
    em.commit([em.event(issued, scope=page.scope)])
    run_realism_tick(store, CAMPAIGN, prose=writer)
    assert doc_id in load_state(store, CAMPAIGN).documents
    assert len(writer.calls) > 0
    assert all(doc_id not in pages for _, pages in writer.calls)


def at_war_with_america(store: EventStore, hitler: SeatId) -> None:
    for _ in range(5):  # an order's id is random, and about one in a hundred lapses
        order = file_order(store, CAMPAIGN, hitler, "declare_war", {"target": "usa"})
        for _ in range(30):
            run_realism_tick(store, CAMPAIGN)
            status = load_state(store, CAMPAIGN).orders[order.order_id].status
            if status is OrderStatus.ENACTED:
                return
            if status is not OrderStatus.MOVING:
                break
    raise AssertionError("the declaration never enacted")


def test_an_ai_seat_gets_no_report_of_its_own_forces_and_no_newspaper() -> None:
    store = MemoryStore()
    hitler = seated(store, "hitler", POINTS)
    made = set(seat_the_rest(store))
    at_war_with_america(store, hitler)
    state = load_state(store, CAMPAIGN)
    ids = resolve_keys(cmp.load_world(cmp.world_path(POINTS)), CAMPAIGN)
    today = state.in_world_date
    assert today is not None

    def feature(key: str) -> FeatureId:
        return FeatureId(object_id(CAMPAIGN, "feature", key))

    uboats = state.features[feature("uboat_arm")]
    pacific = state.features[feature("us_pacific_fleet")]
    argentia = EntityId(ids["argentia"])
    sailing = pacific.model_copy(
        update={"bound_for": argentia, "arrives": today + timedelta(days=1)}
    )
    met = uboats.model_copy(update={"places": (EntityId(ids["norfolk"]),)})
    for moved in (sailing, met):
        realism_tick._append(
            store, load_state(store, CAMPAIGN), ev.FeatureSet(feature=moved), hitler
        )
    start = len(list(store.read(CAMPAIGN)))
    run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    assert state.features[feature("us_pacific_fleet")].places == (argentia,)
    contact = [n for n in state.news.values() if n.topic is NewsTopic.CONTACT]
    assert len(contact) == 1
    mine = project(state, hitler).documents.values()
    assert any(state.documents[d.doc_id].truth.news_id == contact[0].news_id for d in mine)
    for e in list(store.read(CAMPAIGN))[start:]:
        if e.payload.kind not in OWN_ORDERS:
            assert not (made & e.scope.known_by), getattr(e.payload, "document", e.payload)


# --- an ask to a person nobody plays: no seat appears on its due day -----------------


def _toy(tmp: Path, ask: bool, *changes: Any) -> MemoryStore:
    """The ask tests' toy game (Kara and Olaf claimed, Ilse left to her card, which
    writes no answers), with Kara's march to the Isle held for Ilse; Kara asks for it
    only with ``ask``. Ids are drawn from what they name, so the two games match."""
    with ft.drawn_from(Counter()):
        store = aa.unplayed(tmp, *changes, aa.hostile)
        order = toy.file(store, "isle")
        if ask:
            aa.ask(store, order.order_id)
        aa.tick_until(store, lambda s: False, ticks=4)
    return store


def _prompt(store: MemoryStore, seat: SeatId) -> str:
    t = FakeTransport({"text": "Wait."})
    advise(store, TOY, seat, "Who sits at the table?", t)
    (req,) = t.requests
    return req.prompt


def test_an_ask_to_a_person_nobody_plays_shows_no_other_seat_a_new_seat(tmp_path: Path) -> None:
    quiet = _toy(tmp_path / "a", False, aa.answers_on)
    asked = _toy(tmp_path / "b", True, aa.answers_on)
    assert aa.answered(asked) and not aa.answered(quiet)
    other = toy.seat(toy.OLAF)
    a, b = (project(load_state(s, TOY), other) for s in (quiet, asked))
    assert a.seats == b.seats
    assert a.model_dump(mode="json") == b.model_dump(mode="json")
    assert _prompt(quiet, other) == _prompt(asked, other)
    for store in (quiet, asked):
        assert actors.seat_of(load_state(store, TOY), toy.ILSE) is not None


def test_with_ask_answers_off_nobody_unplayed_is_seated_for_an_ask(tmp_path: Path) -> None:
    state = load_state(_toy(tmp_path, True), TOY)
    assert actors.seat_of(state, toy.ILSE) is None
    assert answering.askable(state) == []


def test_who_could_be_asked_is_each_rows_decider_and_each_card_with_authority_above_another(
    tmp_path: Path,
) -> None:
    state = load_state(aa.unplayed(tmp_path, aa.answers_on), TOY)
    assert answering.askable(state) == [toy.ILSE]
    no_rows = state.model_copy(update={"locks": ()})
    assert answering.askable(no_rows) == [toy.ILSE]
    bare = state.cards[toy.ILSE].model_copy(update={"authority": ()})
    no_authority = state.model_copy(update={"cards": {**state.cards, toy.ILSE: bare}})
    assert answering.askable(no_authority) == [toy.ILSE]
    assert answering.askable(no_rows.model_copy(update={"cards": no_authority.cards})) == []
    assert toy.ILSE in superiors(state.cards, toy.KARA)
    kara = state.cards[toy.KARA].model_copy(update={"principals": ()})
    nobody_above = no_rows.model_copy(update={"cards": {**state.cards, toy.KARA: kara}})
    assert answering.askable(nobody_above) == []
