"""Theatres and capitals on the seat's map: each place carries its theatre, and each
leader the People roster weighs against the seat sits at their own place with the
roster's stance for them, fogged exactly as the roster fogs it."""

import json
from datetime import timedelta
from pathlib import Path

from revisionist.core.ids import CampaignId, EntityId, OrderId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.stance import Stance, StanceCause, Standing
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web.people import seat_people
from revisionist.engine.web.realism_api import MapCapital, MapOrder, MapPlace, SeatMap

POINTS = str(Path(__file__).parent / "worlds" / "autumn-1941-points.yaml")
"""The autumn-1941 world before territories: these tests pin movement between points."""

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
SEATS_AT = {
    "hitler": "berlin",
    "stalin": "moscow",
    "roosevelt": "washington",
    "mussolini": "rome",
    "tojo": "tokyo",
    "chiang": "chungking",
    "eden": "london",
}
"""Konoe is left with no place; Eden is Churchill's own man, never a capital."""


def world(located: dict[str, str] | None = None, *, theatres: bool = True) -> WorldFile:
    decl = cmp.load_world(cmp.world_path(POINTS))
    entities = []
    for e in decl.entities:
        update: dict[str, object] = {}
        if located and e.key in located:
            update["location"] = located[e.key]
        if not theatres:
            update["theatre"] = None
        entities.append(e.model_copy(update=update))
    return decl.model_copy(update={"entities": tuple(entities)})


def seated(who: str, decl: WorldFile) -> tuple[State, SeatId, dict[str, EntityId]]:
    """``who`` seated in ``decl``, before any wake."""
    store = MemoryStore()
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    keys = {k: EntityId(v) for k, v in resolve_keys(decl, CAMPAIGN).items()}
    realism_tick.seat_player(store, CAMPAIGN, keys[who])
    state = load_state(store, CAMPAIGN)
    (seat,) = state.seats
    return state, seat, keys


def the_map(state: State, seat: SeatId) -> SeatMap:
    view = project(state, seat)
    out = rs.seat_map(view, pipelines=state.pipelines, people=seat_people(state, seat, view))
    assert out is not None
    return out


# --- theatres ------------------------------------------------------------------------


def test_each_place_on_the_map_carries_its_theatre() -> None:
    decl = world()
    state, seat, _ = seated("churchill", decl)
    written = {e.name: e.theatre for e in decl.entities if e.at is not None}
    places = the_map(state, seat)["places"]
    assert {p["name"]: p["theatre"] for p in places} == written
    by_name = {p["name"]: p for p in places}
    assert by_name["Moscow"]["theatre"] == "Moscow front"
    assert by_name["Reykjavik"]["theatre"] == "North Atlantic"


def test_a_marks_places_and_an_orders_destination_carry_the_theatre_too() -> None:
    state, seat, _ = seated("roosevelt", world())
    assert state.in_world_date is not None
    desk = project(state, seat).desk
    assert desk is not None
    (lever,) = [x for x in desk.levers if x.name == "move_fleet"]
    order = Order(
        order_id=OrderId(derived_id(state.campaign_id, "order", seat, "ths")),
        issuer=seat,
        lever="move_fleet",
        pipeline=lever.pipeline,
        params={"force": "us_atlantic_fleet", "to": "argentia"},
        filed=state.in_world_date,
    )
    state = state.model_copy(update={"orders": {**state.orders, order.order_id: order}})
    m = the_map(state, seat)
    marked = [p for mark in m["marks"] for p in mark["places"]]
    assert marked and all(p["theatre"] for p in marked)
    theatres = {p["name"]: p["theatre"] for p in m["places"]}
    assert all(p["theatre"] == theatres[p["name"]] for p in marked)
    (sent,) = m["orders"]
    assert sent["to"]["name"] == "Argentia" and sent["to"]["theatre"] == "North America"


def test_a_place_the_world_gives_no_theatre_sends_none() -> None:
    state, seat, _ = seated("churchill", world(theatres=False))
    places = the_map(state, seat)["places"]
    assert places and {p["theatre"] for p in places} == {None}


# --- capitals ------------------------------------------------------------------------


def test_each_weighed_leader_with_a_place_sits_there_with_the_rosters_stance() -> None:
    state, seat, _ = seated("churchill", world(SEATS_AT))
    view = project(state, seat)
    roster = seat_people(state, seat, view)
    capitals = the_map(state, seat)["capitals"]
    expected = [
        (p["name"], p["stance"], p["at_war"])
        for p in roster["opponents"]
        if p["stance"] is not None and p["name"] != "Fumimaro Konoe"
    ]
    assert [(c["name"], c["stance"], c["at_war"]) for c in capitals] == expected
    at = {c["name"]: c["place"] for c in capitals}
    assert at["Adolf Hitler"] == {
        "name": "Berlin",
        "lat": 52.5,
        "lon": 13.4,
        "theatre": "Europe",
    }
    assert at["Joseph Stalin"]["name"] == "Moscow"
    assert at["Franklin D. Roosevelt"]["name"] == "Washington"


def test_a_leader_with_no_place_and_anyone_not_weighed_have_no_capital() -> None:
    state, seat, _ = seated("churchill", world(SEATS_AT))
    names = {c["name"] for c in the_map(state, seat)["capitals"]}
    assert "Fumimaro Konoe" not in names
    assert "Anthony Eden" not in names
    assert "London" not in {c["place"]["name"] for c in the_map(state, seat)["capitals"]}


def test_a_leader_with_no_stance_on_the_roster_has_no_capital() -> None:
    state, seat, keys = seated("churchill", world(SEATS_AT))
    stances = {**state.stances[seat], keys["hitler"]: ()}
    state = state.model_copy(update={"stances": {**state.stances, seat: stances}})
    view = project(state, seat)
    (hitler,) = [
        p for p in seat_people(state, seat, view)["opponents"] if p["name"] == "Adolf Hitler"
    ]
    assert hitler["stance"] is None
    names = {c["name"] for c in the_map(state, seat)["capitals"]}
    assert "Adolf Hitler" not in names and "Joseph Stalin" in names


def test_a_stance_the_staff_have_no_evidence_for_stays_off_the_capital() -> None:
    state, seat, keys = seated("churchill", world(SEATS_AT))
    history = state.stances[seat][keys["stalin"]]
    assert state.in_world_date is not None
    turned = Standing(
        on=state.in_world_date + timedelta(days=1),
        stance=Stance.HOSTILE,
        score=-15,
        side=0,
        disposition=-5,
        cause=StanceCause.DISPOSITION,
    )
    stances = {**state.stances[seat], keys["stalin"]: (*history, turned)}
    state = state.model_copy(
        update={
            "stances": {**state.stances, seat: stances},
            "in_world_date": state.in_world_date + timedelta(days=5),
        }
    )
    (stalin,) = [c for c in the_map(state, seat)["capitals"] if c["name"] == "Joseph Stalin"]
    view = project(state, seat)
    (line,) = [
        p for p in seat_people(state, seat, view)["opponents"] if p["name"] == "Joseph Stalin"
    ]
    assert stalin["stance"] == line["stance"]
    assert stalin["stance"] is not None and stalin["stance"]["word"] != "Hostile"


def test_a_capital_says_when_the_two_countries_are_at_war() -> None:
    state, seat, keys = seated("churchill", world(SEATS_AT))
    assert state.in_world_date is not None
    war = War(
        war_id=war_id_for(keys["germany"], keys["uk"]),
        a=keys["germany"],
        b=keys["uk"],
        since=state.in_world_date,
        declared_by=keys["hitler"],
    )
    state = state.model_copy(update={"wars": {war.war_id: war}})
    by_name = {c["name"]: c for c in the_map(state, seat)["capitals"]}
    assert by_name["Adolf Hitler"]["at_war"] is True
    assert by_name["Joseph Stalin"]["at_war"] is False


def test_the_realism_block_sends_the_capitals() -> None:
    state, seat, _ = seated("churchill", world(SEATS_AT))
    block = rs.seat_realism(state, seat, set(), set(), None)
    names = [c["name"] for c in block["map"]["capitals"]]
    assert "Adolf Hitler" in names and "Joseph Stalin" in names


def test_the_world_as_written_places_no_leader_so_the_map_has_no_capitals() -> None:
    state, seat, _ = seated("churchill", world())
    assert the_map(state, seat)["capitals"] == []


def test_a_map_built_without_the_roster_has_no_capitals() -> None:
    state, seat, _ = seated("churchill", world(SEATS_AT))
    m = rs.seat_map(project(state, seat))
    assert m is not None and m["capitals"] == []


# --- the shared fixture --------------------------------------------------------------


def test_the_fixture_map_carries_theatres_and_capitals_in_the_snapshot_shape() -> None:
    m = json.loads(FIXTURE.read_text())["map"]
    assert set(m) == set(SeatMap.__required_keys__)  # a point game: no territory keys
    places = [
        *m["places"],
        *(p for mark in m["marks"] for p in mark["places"]),
        *(o["to"] for o in m["orders"]),
        *(c["place"] for c in m["capitals"]),
    ]
    assert all(set(p) == set(MapPlace.__annotations__) for p in places)
    assert any(p["theatre"] for p in places)
    assert m["capitals"]
    for c in m["capitals"]:
        assert set(c) == set(MapCapital.__annotations__)
    for o in m["orders"]:
        assert set(o) == set(MapOrder.__annotations__)
    opponents = {p["name"]: p for p in json.loads(FIXTURE.read_text())["people"]["opponents"]}
    for c in m["capitals"]:
        assert c["stance"] == opponents[c["name"]]["stance"]
        assert c["at_war"] == opponents[c["name"]]["at_war"]
