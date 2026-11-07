"""The war helpers: ids, the at-war test, polity and outlet lookup."""

from datetime import date

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, replay
from revisionist.core.ids import CampaignId, EntityId, EventId, SeatId
from revisionist.core.ontology import Entity, EntityKind, Seat, SeatKind
from revisionist.core.project import project
from revisionist.core.realism.war import (
    Outlet,
    War,
    at_war,
    outlet_for,
    polity_of,
    war_id_for,
)
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
USA, GER, OFFICE, FDR = (EntityId(k) for k in ("usa", "germany", "ministry", "fdr"))
SEAT = SeatId("seat-fdr")


def entity(key: EntityId, kind: EntityKind, parent: EntityId | None = None) -> Entity:
    return Entity(entity_id=key, kind=kind, name=key, parent=parent)


def world() -> State:
    state = State(campaign_id=CAMPAIGN, ruleset="realism", in_world_date=date(1941, 9, 1))
    entities = {
        e.entity_id: e
        for e in (
            entity(USA, EntityKind.POLITY),
            entity(GER, EntityKind.POLITY),
            entity(OFFICE, EntityKind.ORG, USA),
            entity(FDR, EntityKind.PERSON, OFFICE),
            entity(EntityId("ledger"), EntityKind.ORG, USA),
            entity(EntityId("loose"), EntityKind.PERSON),
        )
    }
    seat = Seat(seat_id=SEAT, kind=SeatKind.PLAYER, name="fdr", embodies=FDR)
    ledger = Outlet(outlet_id=EntityId("ledger"), polity=USA, name="Ledger", voice="Brisk.")
    return state.model_copy(
        update={"entities": entities, "seats": {SEAT: seat}, "outlets": {ledger.outlet_id: ledger}}
    )


def war(a: EntityId = GER, b: EntityId = USA) -> War:
    return War(war_id=war_id_for(a, b), a=a, b=b, since=date(1941, 12, 11), declared_by=FDR)


def test_war_id_is_the_same_in_either_order() -> None:
    assert war_id_for(GER, USA) == war_id_for(USA, GER) == "germany|usa"


def test_at_war_holds_the_pair_in_either_order() -> None:
    state = world()
    assert not at_war(state, GER, USA)
    state = state.model_copy(update={"wars": {war().war_id: war()}})
    assert at_war(state, GER, USA) and at_war(state, USA, GER)
    assert not at_war(state, GER, EntityId("uk"))


def test_at_war_reads_a_view() -> None:
    state = world().model_copy(update={"wars": {war().war_id: war()}})
    state = state.model_copy(update={"seats": {SEAT: state.seats[SEAT]}})
    assert at_war(project(state, SEAT), USA, GER)


def test_polity_of_walks_parents_to_the_first_polity() -> None:
    state = world()
    assert polity_of(state, FDR) == USA
    assert polity_of(state, USA) == USA
    assert polity_of(state, EntityId("loose")) is None
    assert polity_of(state, EntityId("nobody")) is None


def test_outlet_for_is_the_outlet_of_the_persons_polity() -> None:
    state = world()
    found = outlet_for(state, SEAT)
    assert found is not None and found.outlet_id == "ledger"
    assert outlet_for(state, SeatId("nobody")) is None
    assert outlet_for(state.model_copy(update={"outlets": {}}), SEAT) is None


def event(payload: ev.Payload, state: State) -> ev.Event:
    return ev.Event(
        event_id=EventId("e"),
        campaign_id=state.campaign_id,
        seq=state.last_seq + 1,
        tick=0,
        scope=PUBLIC,
        payload=payload,
        versions=ev.Versions(engine="t", schema_version="t"),
    )


def test_the_fold_puts_a_war_once() -> None:
    state = world()
    state = replay([event(ev.WarDeclared(war=war()), state)], initial=state)
    assert at_war(state, USA, GER)
    with pytest.raises(FoldError, match="already at war"):
        replay([event(ev.WarDeclared(war=war(USA, GER)), state)], initial=state)


def test_the_fold_refuses_a_war_on_a_non_polity() -> None:
    state = world()
    with pytest.raises(FoldError, match="not a polity"):
        replay([event(ev.WarDeclared(war=war(GER, OFFICE)), state)], initial=state)
