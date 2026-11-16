"""The People roster of ``view.realism``: the seat's staff's view of everyone with an
office, fogged as the opponents list is, with no score in it and card values only for
the seat's own chain and inner circle."""

import json
from datetime import date
from pathlib import Path

import pytest

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
from revisionist.core.realism.answer import ParamValue
from revisionist.core.realism.card import ChannelKind, Conflict, Lever
from revisionist.core.realism.document import (
    BodyField,
    Document,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.effect import Fidelity, Route, RoutedOrder, RoutedPart
from revisionist.core.realism.geography import FeatureKind, Sight
from revisionist.core.realism.pipeline import Order, OrderStatus, StepAction, StepOutcome
from revisionist.core.realism.pipelines import reply_doc_id
from revisionist.core.realism.stance import RANK, Stance
from revisionist.core.state import State
from revisionist.core.visibility import Scope, private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web.people import seat_people
from revisionist.engine.web.realism_api import (
    People,
    PeopleMeter,
    PersonChannel,
    PersonHold,
    PersonLine,
    PersonTally,
)
from revisionist.engine.web.realism_snapshot import lever_label
from revisionist.engine.web.threats import seat_threats

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
OTHER = SeatId("01ARZ3NDEKTSV4RRFFQ69G5FB0")
"""A seat that is not the viewer's: its private pages and orders must not reach the roster."""
CANARY = "CANARY-PE1-7f3a"


def begun() -> tuple[State, SeatId, dict[str, EntityId]]:
    """Churchill seated in autumn 1941, before any wake: stances as at the start. The
    world's starting regard is left out, so each test makes the relationships it reads."""
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path("autumn-1941"))
    decl = decl.model_copy(update={"relationships": ()})
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


OWN_KEYS = frozenset(PersonLine.__annotations__)
"""The seat's own chain and inner circle: every key, card values and standing too."""
ELSE_KEYS = frozenset(PersonLine.__required_keys__)
"""Opponents and everyone else: no card value and no standing, which reads hidden rank."""


def assert_group_keys(roster: People) -> None:
    """Each group's lines carry exactly that group's keys: no key beyond them, none short."""
    assert ELSE_KEYS < OWN_KEYS
    groups = (
        ("opponents", roster["opponents"], ELSE_KEYS),
        ("yours", roster["yours"], OWN_KEYS),
        ("others", roster["others"], ELSE_KEYS),
    )
    for group, lines, want in groups:
        assert lines, group
        for p in lines:
            assert set(p) == want, (group, p["name"], sorted(set(p) ^ want))


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
    """Card values reach only the seat's own chain and inner circle (the figure card's
    fog rule); an opponent's line carries none of them, and no card text at all."""
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
            "wants": ("embargo",),
            "holds_to": ("free_trade",),
        }
    )
    state = state.model_copy(update={"cards": {**state.cards, hitler: card}})
    roster = people(state, seat)
    assert CANARY not in json.dumps(roster)
    text = json.dumps(line(roster, hitler))
    assert "loyalty" not in text and "competence" not in text
    assert '"wants"' not in text and '"holds_to"' not in text
    assert_group_keys(roster)
    for p in everyone(roster):
        meters = [p["regard"], p["reliability"], p["pace"]]
        meters += [
            m
            for m in (
                p["stance"],
                p["power"],
                p.get("standing"),
                p.get("loyalty"),
                p.get("competence"),
            )
            if m
        ]
        for meter in meters:
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


# --- the figure card -------------------------------------------------------------------

TODAY = date(1941, 9, 10)


def seated(who: str) -> tuple[State, SeatId, dict[str, EntityId]]:
    """``who`` seated in autumn 1941 with the world as written, on ``TODAY``."""
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path("autumn-1941"))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    keys = {k: EntityId(v) for k, v in resolve_keys(decl, CAMPAIGN).items()}
    realism_tick.seat_player(store, CAMPAIGN, keys[who])
    state = load_state(store, CAMPAIGN)
    (seat,) = state.seats
    return on_day(state, TODAY), seat, keys


def lever_of(state: State, seat: SeatId, name: str) -> Lever:
    desk = project(state, seat).desk
    assert desk is not None
    (found,) = [x for x in desk.levers if x.name == name]
    return found


def filed(
    state: State,
    issuer: SeatId,
    lever: Lever,
    on: date,
    *outcomes: StepOutcome,
    step: int = 0,
    params: dict[str, ParamValue] | None = None,
) -> tuple[State, OrderId]:
    """An order on ``lever``'s pipeline, filed by ``issuer`` on ``on``, now at ``step``."""
    order = Order(
        order_id=OrderId(derived_id(state.campaign_id, "order", issuer, str(len(state.orders)))),
        issuer=issuer,
        lever=lever.name,
        pipeline=lever.pipeline,
        params=params or {},
        step=step,
        filed=on,
        outcomes=outcomes,
    )
    return state.model_copy(update={"orders": {**state.orders, order.order_id: order}}), (
        order.order_id
    )


def taken(step: int, person: EntityId, action: StepAction, on: date) -> StepOutcome:
    amended: dict[str, ParamValue] = {"days": 1} if action is StepAction.AMEND else {}
    return StepOutcome(step=step, person=person, action=action, on=on, amended=amended)


def reply_page(state: State, seat: SeatId, order: OrderId, n: int, on: date) -> State:
    """The reply the seat holds for its order's ``n``th step outcome."""
    doc_id = reply_doc_id(state.campaign_id, order, n)
    page = DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.MEMO,
        author=next(iter(state.cards)),
        issued=on,
        arrives=on,
        channel=ChannelKind.IN_PERSON,
        title="On your order",
        scope=private_to(seat),
    )
    doc = Document(view=page, truth=DocumentTruth(doc_id=doc_id))
    return state.model_copy(update={"documents": {**state.documents, doc_id: doc}})


def with_card(state: State, person: EntityId, **values: object) -> State:
    card = state.cards[person].model_copy(update=values)
    return state.model_copy(update={"cards": {**state.cards, person: card}})


def sighted(state: State, scope: Scope, side: EntityId, places: list[EntityId], on: date) -> State:
    """One page placing a force of ``side`` at each of ``places``."""
    doc_id = DocumentId(
        derived_id(state.campaign_id, "doc", "sighting", on.isoformat(), str(scope))
    )
    page = DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.REPORT,
        author=next(iter(state.cards)),
        issued=on,
        arrives=on,
        channel=ChannelKind.CABLE,
        title="Sightings",
        body=tuple(
            BodyField(
                label=f"Force {i}",
                value="sighted",
                sight=Sight(kind=FeatureKind.ARMY, side=side, places=(place,)),
            )
            for i, place in enumerate(places)
        ),
        scope=scope,
    )
    doc = Document(view=page, truth=DocumentTruth(doc_id=doc_id))
    return state.model_copy(update={"documents": {**state.documents, doc_id: doc}})


NO_TALLY: PersonTally = {
    "passed": 0,
    "hurried": 0,
    "held": 0,
    "amended": 0,
    "refused": 0,
    "leaked": 0,
}


def test_holds_and_load_list_the_seats_orders_waiting_on_the_person() -> None:
    state, seat, keys = seated("churchill")
    pound, ismay = keys["pound"], keys["ismay"]
    move = lever_of(state, seat, "move_fleet")
    convoy = lever_of(state, seat, "convoy_orders")
    state, first = filed(state, seat, move, date(1941, 9, 4))
    state, second = filed(
        state,
        seat,
        convoy,
        date(1941, 9, 2),
        taken(0, pound, StepAction.PASS, date(1941, 9, 5)),
        step=1,
    )
    roster = people(state, seat)
    got = line(roster, pound)
    assert got["holds"] == [
        {
            "id": first,
            "label": lever_label(move),
            "since": "1941-09-04",
            "held_days": 6,
            "days": 2,
            "read": "may hold it",
        }
    ]
    assert got["load"] == 1
    (at_ismay,) = line(roster, ismay)["holds"]
    assert (at_ismay["id"], at_ismay["since"], at_ismay["held_days"], at_ismay["days"]) == (
        second,
        "1941-09-05",
        5,
        1,
    )
    assert line(roster, keys["eden"])["holds"] == [] and line(roster, keys["eden"])["load"] == 0


def test_a_settled_order_is_held_by_nobody() -> None:
    state, seat, keys = seated("churchill")
    state, oid = filed(state, seat, lever_of(state, seat, "move_fleet"), date(1941, 9, 4))
    done = state.orders[oid].model_copy(update={"status": OrderStatus.ENACTED})
    state = state.model_copy(update={"orders": {**state.orders, oid: done}})
    assert line(people(state, seat), keys["pound"])["load"] == 0


def test_another_seats_orders_are_never_held_counted_or_tallied() -> None:
    state, seat, keys = seated("churchill")
    pound = keys["pound"]
    move = lever_of(state, seat, "move_fleet")
    before = line(people(state, seat), pound)
    state, _ = filed(state, OTHER, move, date(1941, 9, 4))
    state, _ = filed(
        state,
        OTHER,
        move,
        date(1941, 9, 2),
        taken(0, pound, StepAction.REFUSE, date(1941, 9, 3)),
    )
    got = line(people(state, seat), pound)
    assert got == before
    assert (got["holds"], got["load"], got["tally"]) == ([], 0, NO_TALLY)


def test_the_tally_counts_what_they_did_with_the_seats_orders_at_their_step() -> None:
    state, seat, keys = seated("churchill")
    pound, ismay = keys["pound"], keys["ismay"]
    move = lever_of(state, seat, "move_fleet")
    state, _ = filed(
        state,
        seat,
        move,
        date(1941, 9, 2),
        taken(0, pound, StepAction.PASS, date(1941, 9, 3)),
        taken(1, ismay, StepAction.PASS, date(1941, 9, 4)),
        step=2,
    )
    state, _ = filed(
        state, seat, move, date(1941, 9, 2), taken(0, pound, StepAction.EXPEDITE, date(1941, 9, 3))
    )
    state, _ = filed(
        state, seat, move, date(1941, 9, 2), taken(0, pound, StepAction.AMEND, date(1941, 9, 4))
    )
    state, _ = filed(
        state, seat, move, date(1941, 9, 2), taken(0, pound, StepAction.REFUSE, date(1941, 9, 5))
    )
    roster = people(state, seat)
    assert line(roster, pound)["tally"] == {
        **NO_TALLY,
        "passed": 1,
        "hurried": 1,
        "amended": 1,
        "refused": 1,
    }
    assert line(roster, ismay)["tally"] == {**NO_TALLY, "passed": 1}


def test_a_hold_or_leak_counts_only_when_the_seat_has_the_reply_that_says_so() -> None:
    state, seat, keys = seated("churchill")
    pound = keys["pound"]
    move = lever_of(state, seat, "move_fleet")
    state, held = filed(
        state,
        seat,
        move,
        date(1941, 9, 2),
        taken(0, pound, StepAction.STALL, date(1941, 9, 4)),
        taken(0, pound, StepAction.LEAK, date(1941, 9, 6)),
        step=1,
    )
    assert line(people(state, seat), pound)["tally"] == NO_TALLY
    told = reply_page(state, seat, held, 0, date(1941, 9, 4))
    assert line(people(told, seat), pound)["tally"] == {**NO_TALLY, "held": 1}
    told = reply_page(told, seat, held, 1, date(1941, 9, 6))
    assert line(people(told, seat), pound)["tally"] == {**NO_TALLY, "held": 1, "leaked": 1}
    theirs = reply_page(state, OTHER, held, 0, date(1941, 9, 4))
    assert line(people(theirs, seat), pound)["tally"] == NO_TALLY


def test_pace_is_untested_until_the_person_moves_one_of_the_seats_orders() -> None:
    state, seat, keys = seated("churchill")
    pound = keys["pound"]
    move = lever_of(state, seat, "move_fleet")
    assert line(people(state, seat), pound)["pace"] == UNTESTED
    refused, _ = filed(
        state, seat, move, date(1941, 9, 2), taken(0, pound, StepAction.REFUSE, date(1941, 9, 9))
    )
    assert line(people(refused, seat), pound)["pace"] == UNTESTED


@pytest.mark.parametrize(
    ("passed_on", "step", "word"),
    [
        (date(1941, 9, 3), 5, "Quick"),
        (date(1941, 9, 4), 4, "On time"),
        (date(1941, 9, 5), 3, "Slow"),
        (date(1941, 9, 6), 2, "Late"),
        (date(1941, 9, 7), 1, "Very late"),
    ],
)
def test_pace_weighs_days_taken_against_days_stated(passed_on: date, step: int, word: str) -> None:
    state, seat, keys = seated("churchill")
    pound = keys["pound"]
    move = lever_of(state, seat, "move_fleet")
    state, _ = filed(
        state, seat, move, date(1941, 9, 2), taken(0, pound, StepAction.PASS, passed_on), step=1
    )
    pace = line(people(state, seat), pound)["pace"]
    assert (pace["step"], pace["word"], pace["as_of"]) == (step, word, passed_on.isoformat())


def test_pace_starts_the_clock_when_the_order_reached_the_person() -> None:
    state, seat, keys = seated("churchill")
    pound, ismay = keys["pound"], keys["ismay"]
    move = lever_of(state, seat, "move_fleet")
    state, _ = filed(
        state,
        seat,
        move,
        date(1941, 9, 1),
        taken(0, pound, StepAction.STALL, date(1941, 9, 3)),
        taken(0, pound, StepAction.PASS, date(1941, 9, 6)),
        taken(1, ismay, StepAction.PASS, date(1941, 9, 7)),
        step=2,
    )
    roster = people(state, seat)
    assert line(roster, ismay)["pace"]["word"] == "On time"
    assert line(roster, pound)["pace"]["word"] == "Very late"


def test_standing_reads_rank_in_five_steps_for_the_seats_own_people() -> None:
    state, seat, keys = seated("churchill")
    roster = people(state, seat)
    assert line(roster, keys["pound"])["standing"] == {
        "step": 3,
        "word": "Established",
        "as_of": None,
        "confidence": None,
    }
    pound = state.cards[keys["pound"]]
    for rank, step in ((0, 1), (1, 1), (4, 4), (5, 5)):
        ranked = with_card(
            state, keys["pound"], reach=pound.reach.model_copy(update={"rank": rank})
        )
        assert line(people(ranked, seat), keys["pound"])["standing"]["step"] == step


def test_standing_is_absent_for_anyone_outside_the_seats_chain_and_inner_circle() -> None:
    """Standing reads the card's hidden rank, which a seat's view does not hold
    (``card.py`` public face); like the other card values it reaches only the seat's
    own chain and inner circle. The opponents' power meter still reads rank, as
    approved (first-run change 14)."""
    state, seat, keys = seated("churchill")
    roster = people(state, seat)
    assert roster["opponents"] and roster["others"]
    for p in roster["opponents"] + roster["others"]:
        assert "standing" not in p, p["name"]
    for who in ("hitler", "stalin", "hull"):
        assert "standing" not in line(roster, keys[who])
    assert all("standing" in p for p in roster["yours"])
    assert_group_keys(roster)


def test_bloc_is_the_name_of_the_persons_parent_body() -> None:
    state, seat, keys = seated("roosevelt")
    roster = people(state, seat)
    assert line(roster, keys["stark"])["bloc"] == "Navy Department"
    assert line(roster, keys["barkley"])["bloc"] == "Senate"
    assert line(roster, keys["tojo"])["bloc"] == state.entities[keys["japan"]].name


def test_a_circle_member_carries_the_channel_and_its_days() -> None:
    state, seat, keys = seated("churchill")
    roster = people(state, seat)
    assert line(roster, keys["pound"])["channel"] == {"channel": "in_person", "days": 1}
    assert line(roster, keys["roosevelt"])["channel"] == {"channel": "cable", "days": 0}
    assert line(roster, keys["uk_cipher_clerk"])["channel"] is None
    assert line(roster, keys["hull"])["channel"] is None


def test_own_people_carry_loyalty_competence_and_their_topics_by_name() -> None:
    state, seat, keys = seated("roosevelt")
    roster = people(state, seat)
    hull = line(roster, keys["hull"])
    assert hull["loyalty"] == {"step": 4, "word": "Loyal", "as_of": None, "confidence": None}
    assert hull["competence"] == {"step": 3, "word": "Capable", "as_of": None, "confidence": None}
    names = {k: t.name for k, t in state.topics.items()}
    assert hull["wants"] == [names["japan_talks"], names["diplomacy"]]
    assert hull["holds_to"] == [names["free_trade"]]
    morgenthau = line(roster, keys["morgenthau"])
    assert morgenthau["holds_to"] == [names["embargo"]]
    assert line(roster, keys["marshall"])["competence"]["step"] == 5


def test_an_outsider_and_a_leader_weighed_against_the_seat_carry_no_card_value() -> None:
    state, seat, keys = seated("roosevelt")
    state = with_card(state, keys["king"], wants=("embargo",), loyalty=4)
    roster = people(state, seat)
    for who in ("king", "tojo", "churchill", "hitler"):
        got = line(roster, keys[who])
        assert not {"loyalty", "competence", "wants", "holds_to"} & set(got), who


@pytest.mark.parametrize(
    ("loyalty", "step", "word"),
    [
        (-4, 1, "Disloyal"),
        (-1, 2, "Doubtful"),
        (0, 3, "Steady"),
        (2, 4, "Loyal"),
        (3, 5, "Devoted"),
    ],
)
def test_loyalty_reads_in_five_steps(loyalty: int, step: int, word: str) -> None:
    state, seat, keys = seated("churchill")
    state = with_card(state, keys["pound"], loyalty=loyalty)
    got = line(people(state, seat), keys["pound"])["loyalty"]
    assert (got["step"], got["word"]) == (step, word)


def test_competence_reads_in_five_steps() -> None:
    state, seat, keys = seated("churchill")
    words_by = {}
    for n in range(6):
        got = line(people(with_card(state, keys["pound"], competence=n), seat), keys["pound"])
        words_by[n] = (got["competence"]["step"], got["competence"]["word"])
    assert words_by == {
        0: (1, "Poor"),
        1: (1, "Poor"),
        2: (2, "Limited"),
        3: (3, "Capable"),
        4: (4, "Able"),
        5: (5, "Outstanding"),
    }


def test_power_is_for_leaders_weighed_against_the_seat_only() -> None:
    state, seat, keys = seated("churchill")
    roster = people(state, seat)
    hitler = line(roster, keys["hitler"])["power"]
    assert hitler is not None and (hitler["step"], hitler["word"]) == (5, "Overwhelming")
    assert line(roster, keys["tojo"])["power"] == {
        "step": 3,
        "word": "Considerable",
        "as_of": None,
        "confidence": None,
    }
    assert line(roster, keys["pound"])["power"] is None
    assert line(roster, keys["hull"])["power"] is None


def power_of(state: State, seat: SeatId, person: EntityId) -> PeopleMeter:
    got = line(people(state, seat), person)["power"]
    assert got is not None
    return got


def test_power_rises_a_step_when_the_seats_pages_place_three_forces_under_the_leader() -> None:
    state, seat, keys = seated("churchill")
    tojo, japan = keys["tojo"], keys["japan"]
    places = [keys["tokyo"], keys["kure"], keys["hitokappu_bay"]]
    two = sighted(state, private_to(seat), japan, places[:2], date(1941, 9, 6))
    assert power_of(two, seat, tojo)["step"] == 3
    three = sighted(state, private_to(seat), japan, places, date(1941, 9, 6))
    power = power_of(three, seat, tojo)
    assert (power["step"], power["word"], power["as_of"]) == (4, "Great", "1941-09-06")
    theirs = sighted(state, private_to(OTHER), japan, places, date(1941, 9, 6))
    assert power_of(theirs, seat, tojo)["step"] == 3
    capped = sighted(state, private_to(seat), keys["germany"], places, date(1941, 9, 6))
    assert power_of(capped, seat, keys["hitler"])["step"] == 5


@pytest.mark.parametrize(
    ("loyalty", "read"),
    [
        (2, "likely to pass it"),
        (1, "may hold it"),
        (-2, "may hold it"),
        (-3, "likely to hold or refuse it"),
    ],
)
def test_the_staff_read_weighs_loyalty_with_no_roll(loyalty: int, read: str) -> None:
    state, seat, keys = seated("roosevelt")
    stark = keys["stark"]
    state = with_card(state, stark, loyalty=loyalty)
    state, _ = filed(state, seat, lever_of(state, seat, "move_fleet"), date(1941, 9, 8))
    (hold,) = line(people(state, seat), stark)["holds"]
    assert hold["read"] == read


def test_the_staff_read_counts_a_topic_the_holder_wants() -> None:
    state, seat, keys = seated("roosevelt")
    stark = keys["stark"]
    move = lever_of(state, seat, "move_fleet")
    state, plain = filed(state, seat, move, date(1941, 9, 8))
    state, pacific = filed(state, seat, move, date(1941, 9, 8), params={"to": "pearl_harbor_base"})
    reads = {h["id"]: h["read"] for h in line(people(state, seat), stark)["holds"]}
    assert reads == {plain: "may hold it", pacific: "likely to pass it"}


def test_the_staff_read_counts_the_seats_own_load_only() -> None:
    state, seat, keys = seated("roosevelt")
    stark = keys["stark"]
    move = lever_of(state, seat, "move_fleet")
    pacific: dict[str, ParamValue] = {"to": "pearl_harbor_base"}
    state, mine = filed(state, seat, move, date(1941, 9, 8), params=pacific)
    theirs = state
    for _ in range(4):
        theirs, _ = filed(theirs, OTHER, move, date(1941, 9, 8))
    read = {h["id"]: h["read"] for h in line(people(theirs, seat), stark)["holds"]}
    assert read[mine] == "likely to pass it"
    loaded = state
    for _ in range(3):
        loaded, _ = filed(loaded, seat, move, date(1941, 9, 8))
    read = {h["id"]: h["read"] for h in line(people(loaded, seat), stark)["holds"]}
    assert read[mine] == "likely to pass it"
    loaded, _ = filed(loaded, seat, move, date(1941, 9, 8))
    read = {h["id"]: h["read"] for h in line(people(loaded, seat), stark)["holds"]}
    assert read[mine] == "may hold it"


def test_a_clerk_always_passes_it() -> None:
    state, seat, keys = seated("roosevelt")
    early = keys["early"]
    state = with_card(state, early, loyalty=-5)
    state, _ = filed(state, seat, lever_of(state, seat, "public_address"), date(1941, 9, 8))
    (hold,) = line(people(state, seat), early)["holds"]
    assert hold["read"] == "likely to pass it"


def test_no_read_for_an_outsider_or_a_leader_weighed_against_the_seat() -> None:
    state, seat, keys = seated("roosevelt")
    naval = lever_of(state, seat, "naval_order")
    cable = lever_of(state, seat, "cable_to_churchill")
    clerk = state.pipelines[cable.pipeline].steps[0].person
    state, _ = filed(
        state,
        seat,
        naval,
        date(1941, 9, 4),
        taken(0, keys["stark"], StepAction.PASS, date(1941, 9, 5)),
        step=1,
    )
    state, _ = filed(
        state,
        seat,
        cable,
        date(1941, 9, 4),
        taken(0, clerk, StepAction.PASS, date(1941, 9, 5)),
        step=1,
    )
    roster = people(state, seat)
    (at_king,) = line(roster, keys["king"])["holds"]
    (at_churchill,) = line(roster, keys["churchill"])["holds"]
    assert at_king["read"] is None and at_churchill["read"] is None


def test_no_read_on_a_step_a_player_holds() -> None:
    state, seat, keys = seated("roosevelt")
    stark = keys["stark"]
    player = state.seats[seat].model_copy(update={"seat_id": OTHER, "embodies": stark})
    state = state.model_copy(update={"seats": {**state.seats, OTHER: player}})
    state, _ = filed(state, seat, lever_of(state, seat, "move_fleet"), date(1941, 9, 8))
    (hold,) = line(people(state, seat), stark)["holds"]
    assert hold["read"] is None


# --- the view block and the client fixture ---------------------------------------------


def test_the_realism_view_carries_people_and_keeps_threats_as_they_were() -> None:
    state, seat, _ = begun()
    block = rs.seat_realism(state, seat, set(), set(), None)
    view = project(state, seat)
    assert block["people"] == seat_people(state, seat, view)
    assert block["threats"] == seat_threats(state, seat, view)


def test_the_hidden_actions_match_the_order_trackers() -> None:
    from revisionist.engine.web import people as module

    assert module.UNSEEN == rs._HIDDEN


def test_the_client_fixture_carries_people_in_the_servers_shape() -> None:
    fixture = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
    roster = json.loads(fixture.read_text())["people"]
    assert set(roster) == set(People.__annotations__)
    lines = [p for p in everyone(roster)]
    assert_group_keys(roster)
    meters = [
        m
        for p in lines
        for m in (
            p["regard"],
            p["reliability"],
            p["stance"],
            p["pace"],
            p.get("standing"),
            p["power"],
            p.get("loyalty"),
            p.get("competence"),
        )
        if m
    ]
    assert all(set(m) == set(PeopleMeter.__annotations__) for m in meters)
    holds = [h for p in lines for h in p["holds"]]
    assert holds and all(set(h) == set(PersonHold.__annotations__) for h in holds)
    assert all(set(p["tally"]) == set(PersonTally.__annotations__) for p in lines)
    reach = [p["channel"] for p in lines if p["channel"]]
    assert reach and all(set(r) == set(PersonChannel.__annotations__) for r in reach)
