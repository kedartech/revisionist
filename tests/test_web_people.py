"""The People roster of ``view.realism``: the seat's staff's view of everyone with an
office, fogged as the opponents list is, with no score or card policy in it."""

import json
from datetime import date
from pathlib import Path

from revisionist.core.ids import (
    CampaignId,
    DocumentId,
    EntityId,
    OrderId,
    RelationshipId,
    SeatId,
    derived_id,
)
from revisionist.core.ontology import Relationship
from revisionist.core.project import project
from revisionist.core.realism.card import ChannelKind, Conflict
from revisionist.core.realism.document import Document, DocumentKind, DocumentTruth, DocumentView
from revisionist.core.realism.effect import Fidelity, Route, RoutedOrder, RoutedPart
from revisionist.core.realism.stance import RANK, Stance
from revisionist.core.state import State
from revisionist.core.visibility import Scope, private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web.people import seat_people
from revisionist.engine.web.realism_api import People, PeopleMeter, PersonLine
from revisionist.engine.web.threats import seat_threats

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
OTHER = SeatId("01ARZ3NDEKTSV4RRFFQ69G5FB0")
"""A seat that is not the viewer's: its private pages and orders must not reach the roster."""
CANARY = "CANARY-PE1-7f3a"


def begun() -> tuple[State, SeatId, dict[str, EntityId]]:
    """Churchill seated in autumn 1941, before any wake: stances as at the start."""
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path("autumn-1941"))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    keys = {k: EntityId(v) for k, v in resolve_keys(decl, CAMPAIGN).items()}
    realism_tick.seat_player(store, CAMPAIGN, keys["churchill"])
    state = load_state(store, CAMPAIGN)
    (seat,) = state.seats
    return state, seat, keys


def people(state: State, seat: SeatId) -> People:
    return seat_people(state, seat, project(state, seat))


def everyone(roster: People) -> list[PersonLine]:
    return [*roster["opponents"], *roster["yours"], *roster["others"]]


def line(roster: People, person: EntityId) -> PersonLine:
    (found,) = [p for p in everyone(roster) if p["person"] == person]
    return found


def on_day(state: State, day: date) -> State:
    return state.model_copy(update={"in_world_date": day})


def letter(
    state: State, author: EntityId, scope: Scope, issued: date, arrives: date, title: str
) -> State:
    doc_id = DocumentId(derived_id(state.campaign_id, "doc", author, issued.isoformat(), title))
    page = DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.LETTER,
        author=author,
        issued=issued,
        arrives=arrives,
        channel=ChannelKind.CABLE,
        title=title,
        scope=scope,
    )
    doc = Document(view=page, truth=DocumentTruth(doc_id=doc_id))
    return state.model_copy(update={"documents": {**state.documents, doc_id: doc}})


def related(state: State, of: EntityId, toward: EntityId, n: int, scope: Scope) -> State:
    rel = Relationship(
        relationship_id=RelationshipId(derived_id(state.campaign_id, "rel", of, toward)),
        a=of,
        b=toward,
        disposition=n,
        scope=scope,
    )
    return state.model_copy(
        update={"relationships": {**state.relationships, rel.relationship_id: rel}}
    )


def carried(state: State, issuer: SeatId, executor: EntityId, *done: RoutedPart) -> State:
    """An order from ``issuer`` whose command parts ``executor`` carried out or refused."""
    order = RoutedOrder(
        order_id=OrderId(derived_id(state.campaign_id, "order", issuer, str(len(state.routed)))),
        issuer=issuer,
        filed=date(1941, 9, 2),
        parts=done,
    )
    return state.model_copy(update={"routed": {**state.routed, order.order_id: order}})


def command(
    executor: EntityId, on: date, fidelity: Fidelity | None, refusal: str = ""
) -> RoutedPart:
    return RoutedPart(
        route=Route.COMMAND,
        domain="naval_operations",
        executor=executor,
        fidelity=fidelity,
        refusal=refusal,
        executed=on,
    )


UNTESTED: PeopleMeter = {"step": None, "word": "Untested", "as_of": None, "confidence": None}
UNKNOWN: PeopleMeter = {"step": None, "word": "Unknown", "as_of": None, "confidence": None}


# --- the groups -------------------------------------------------------------------


def test_the_roster_puts_each_person_in_one_group_and_the_seat_in_none() -> None:
    state, seat, keys = begun()
    roster = people(state, seat)
    stanced = set(state.stances[seat])
    assert {p["person"] for p in roster["opponents"]} == stanced
    yours = {p["person"] for p in roster["yours"]}
    assert {keys["eden"], keys["pound"], keys["ismay"]} <= yours
    assert keys["halifax"] in yours and not yours & stanced
    ids = [p["person"] for p in everyone(roster)]
    assert len(ids) == len(set(ids))
    assert keys["churchill"] not in ids
    assert keys["hull"] in {p["person"] for p in roster["others"]}
    assert all(p["stance"] is None for p in roster["yours"] + roster["others"])


def test_an_opponent_line_carries_the_stance_as_the_opponents_list_has_it() -> None:
    state, seat, keys = begun()
    state = state.model_copy(
        update={
            "cards": {
                **state.cards,
                keys["hitler"]: state.cards[keys["hitler"]].model_copy(
                    update={
                        "opposes": (
                            Conflict(against=keys["uk"], over="Command of the Atlantic"),
                            Conflict(against=keys["ussr"], over="Living space in the east"),
                        )
                    }
                ),
            }
        }
    )
    hitler = line(people(state, seat), keys["hitler"])
    (threat,) = [
        t for t in seat_threats(state, seat, project(state, seat)) if t["name"] == hitler["name"]
    ]
    assert hitler["stance"] == {
        "step": RANK[Stance(threat["stance"])] + 1,
        "word": threat["stance_label"],
        "as_of": threat["as_of"],
        "confidence": threat["confidence"],
    }
    assert hitler["trend"] == threat["trend"] == "steady"
    assert hitler["over"] == ["Command of the Atlantic"]
    assert hitler["office"] == state.cards[keys["hitler"]].office


# --- fog rules ----------------------------------------------------------------------


def test_regard_is_unknown_for_everyone_until_play_makes_a_relationship() -> None:
    state, seat, _ = begun()
    assert not state.relationships
    roster = people(state, seat)
    assert all(p["regard"] == UNKNOWN for p in everyone(roster))


def test_regard_reads_the_relationship_the_seat_knows_in_steps() -> None:
    state, seat, keys = begun()
    me, stalin = keys["churchill"], keys["stalin"]
    state = on_day(related(state, stalin, me, 3, private_to(seat)), date(1941, 9, 3))
    regard = line(people(state, seat), stalin)["regard"]
    assert regard == {"step": 4, "word": "Warm", "as_of": "1941-09-01", "confidence": "firm"}


def test_another_seats_relationship_does_not_move_regard() -> None:
    state, seat, keys = begun()
    state = related(state, keys["stalin"], keys["churchill"], -5, private_to(OTHER))
    assert line(people(state, seat), keys["stalin"])["regard"] == UNKNOWN


def test_another_seats_private_page_does_not_move_a_meter() -> None:
    state, seat, keys = begun()
    stalin = keys["stalin"]
    today = date(1941, 9, 20)
    before = line(people(on_day(state, today), seat), stalin)
    theirs = letter(
        on_day(state, today),
        stalin,
        private_to(OTHER),
        date(1941, 9, 18),
        date(1941, 9, 18),
        CANARY,
    )
    roster = people(theirs, seat)
    assert line(roster, stalin) == before
    assert before["stance"] is not None and before["stance"]["as_of"] == "1941-09-01"
    assert CANARY not in json.dumps(roster)


def test_an_as_of_date_is_the_date_of_the_page_it_came_from() -> None:
    state, seat, keys = begun()
    stalin = keys["stalin"]
    heard = letter(
        on_day(state, date(1941, 9, 20)),
        stalin,
        private_to(seat),
        date(1941, 9, 6),
        date(1941, 9, 11),
        "A reply",
    )
    stance = line(people(heard, seat), stalin)["stance"]
    assert stance is not None
    assert (stance["as_of"], stance["confidence"]) == ("1941-09-06", "dated")


def test_an_opponents_loyalty_and_competence_never_appear() -> None:
    state, seat, keys = begun()
    hitler = keys["hitler"]
    card = state.cards[hitler].model_copy(
        update={
            "loyalty": -5,
            "competence": 5,
            "doctrine": (f"{CANARY} doctrine",),
            "interests": (f"{CANARY} interest",),
            "voice": f"{CANARY} voice",
            "aims": (f"{CANARY} aim",),
        }
    )
    state = state.model_copy(update={"cards": {**state.cards, hitler: card}})
    roster = people(state, seat)
    text = json.dumps(roster)
    assert CANARY not in text
    assert "loyalty" not in text and "competence" not in text
    for p in everyone(roster):
        assert set(p) == set(PersonLine.__annotations__)
        for meter in (p["regard"], p["reliability"], *([p["stance"]] if p["stance"] else [])):
            assert set(meter) == set(PeopleMeter.__annotations__)


# --- reliability ------------------------------------------------------------------------


def test_reliability_is_untested_until_the_person_carries_an_order_for_the_seat() -> None:
    state, seat, _ = begun()
    roster = people(state, seat)
    assert all(p["reliability"] == UNTESTED for p in everyone(roster))


def test_reliability_reads_fidelity_lateness_and_refusals_of_the_seats_orders() -> None:
    state, seat, keys = begun()
    pound = keys["pound"]
    today = date(1941, 9, 20)
    full = carried(
        on_day(state, today), seat, pound, command(pound, date(1941, 9, 4), Fidelity.FULL)
    )
    got = line(people(full, seat), pound)["reliability"]
    assert got == {"step": 5, "word": "Dependable", "as_of": "1941-09-04", "confidence": "dated"}
    late = carried(full, seat, pound, command(pound, date(1941, 9, 15), Fidelity.SLOW))
    got = line(people(late, seat), pound)["reliability"]
    assert (got["step"], got["as_of"], got["confidence"]) == (4, "1941-09-15", "firm")
    refused = carried(late, seat, pound, command(pound, date(1941, 9, 16), None, "Not in my remit"))
    assert line(people(refused, seat), pound)["reliability"]["step"] == 3


def test_reliability_counts_only_orders_for_this_seat() -> None:
    state, seat, keys = begun()
    pound = keys["pound"]
    theirs = carried(
        on_day(state, date(1941, 9, 20)),
        OTHER,
        pound,
        command(pound, date(1941, 9, 4), None, CANARY),
    )
    roster = people(theirs, seat)
    assert line(roster, pound)["reliability"] == UNTESTED
    assert CANARY not in json.dumps(roster)


# --- the view block and the client fixture ---------------------------------------------


def test_the_realism_view_carries_people_and_keeps_threats_as_they_were() -> None:
    state, seat, _ = begun()
    block = rs.seat_realism(state, seat, set(), set(), None)
    view = project(state, seat)
    assert block["people"] == seat_people(state, seat, view)
    assert block["threats"] == seat_threats(state, seat, view)


def test_the_client_fixture_carries_people_in_the_servers_shape() -> None:
    fixture = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
    roster = json.loads(fixture.read_text())["people"]
    assert set(roster) == set(People.__annotations__)
    lines = [p for p in everyone(roster)]
    assert lines and all(set(p) == set(PersonLine.__annotations__) for p in lines)
    meters = [m for p in lines for m in (p["regard"], p["reliability"], p["stance"]) if m]
    assert all(set(m) == set(PeopleMeter.__annotations__) for m in meters)
