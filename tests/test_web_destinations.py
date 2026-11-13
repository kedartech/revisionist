"""The place picker's server half (reach R1): a movement form's destination offers every
place on the seat's map, grouped by what the seat's own pages show, each with the days a
force of the form would take to get there from where the seat's latest page places it."""

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.events import Event
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.project import project
from revisionist.core.realism import bases, routing
from revisionist.core.realism.geography import SPEED_KM_PER_DAY, FeatureKind, km_between
from revisionist.core.realism.pipelines import order_words
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.record import _form_words
from revisionist.core.state import State
from revisionist.engine.store import load_state
from revisionist.engine.web import destinations
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web.realism_api import LeverParam, PlaceChoice
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_map import set_feature
from tests.test_web_realism import Realism, post, realism_of

FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
AUTHORED = ["norfolk", "argentia", "reykjavik", "pearl_harbor_base"]


@pytest.fixture
def fdr(web: Web) -> tuple[Realism, Client]:  # noqa: F811
    game = Realism(web, "autumn-1941")
    client = game.seat("ada", "roosevelt")
    game.open_play()
    game.first_tick()
    return game, client


def param(client: Client, lever: str, name: str) -> dict[str, Any]:
    levers = {x["name"]: x for x in realism_of(client)["desk"]["levers"]}
    return next(p for p in levers[lever]["params"] if p["name"] == name)


def state_of(game: Realism) -> State:
    store = game.web.app.open()
    try:
        return load_state(store, game.campaign)
    finally:
        store.close()


def events_of(game: Realism) -> list[Event]:
    store = game.web.app.open()
    try:
        return list(store.read(game.campaign))
    finally:
        store.close()


def places(client: Client) -> dict[str, dict[str, Any]]:
    return {p["label"]: p for p in param(client, "move_fleet", "to")["places"]}


def days(game: Realism, kind: FeatureKind, a: str, b: str) -> int:
    decl = {e.key: e for e in game.decl.entities}
    at_a, at_b = decl[a].at, decl[b].at
    assert at_a is not None and at_b is not None
    return max(1, math.ceil(km_between(at_a, at_b) / SPEED_KM_PER_DAY[kind]))


def test_the_fleet_form_offers_every_place_on_the_map(fdr: tuple[Realism, Client]) -> None:
    game, ada = fdr
    to = param(ada, "move_fleet", "to")
    on_map = {p["name"] for p in realism_of(ada)["map"]["places"]}
    assert to["kind"] == "enum" and len(on_map) == 30
    assert {p["label"] for p in to["places"]} == on_map
    assert [(c["value"], c["label"]) for c in to["choices"]] == [
        (p["value"], p["label"]) for p in to["places"]
    ]
    located = {e.key for e in game.decl.entities if e.at is not None}
    assert {p["value"] for p in to["places"]} == located


def test_places_are_grouped_by_what_the_seats_pages_show(fdr: tuple[Realism, Client]) -> None:
    _, ada = fdr
    found = places(ada)
    groups = {label: p["group"] for label, p in found.items()}
    # the form's own destinations and the seat's own fleets' places
    for own in ("Norfolk", "Argentia", "Reykjavik", "Pearl Harbor"):
        assert groups[own] == "own", own
    assert groups["Scapa Flow"] == "allied"  # the Home Fleet: Britain is Roosevelt's ally
    assert groups["Lorient"] == "contested"  # the U-boat arm: not his side, not an ally
    for route in ("Halifax", "North Atlantic", "Liverpool", "Sydney, Cape Breton", "Archangel"):
        assert groups[route] == "route", route
    assert groups["Tokyo"] == "other" and groups["Kure"] == "other"
    order = ["own", "allied", "route", "contested", "other"]
    shown = [p["group"] for p in param(ada, "move_fleet", "to")["places"]]
    assert shown == sorted(shown, key=order.index)


def test_days_are_the_movement_resolvers_own_count(fdr: tuple[Realism, Client]) -> None:
    """Each fleet's page places it where it truly is here, so every day count must be
    what the movement resolver would take: by sea, through the open passages."""
    game, ada = fdr
    state = state_of(game)
    found = param(ada, "move_fleet", "to")["places"]
    for key in ("us_atlantic_fleet", "us_pacific_fleet"):
        force = state.features[FeatureId(game.ids[key])]
        for p in found:
            to = EntityId(game.ids[p["value"]])
            want = 0 if to == force.places[0] else routing.travel_days(state, force, to)
            assert p["days"][key] == want, (key, p["label"])
    argentia = places(ada)["Argentia"]["days"]["us_pacific_fleet"]
    assert argentia > days(game, FeatureKind.FLEET, "pearl_harbor_base", "argentia")  # by Panama
    assert places(ada)["Norfolk"]["days"]["us_atlantic_fleet"] == 0


def test_a_place_no_open_passage_reaches_has_no_day_count(fdr: tuple[Realism, Client]) -> None:
    """At war with Britain, an American fleet cannot pass Gibraltar or Suez: the
    Mediterranean is out of reach, as the resolver has it."""
    game, _ = fdr
    state = state_of(game)
    usa, uk = EntityId(game.ids["usa"]), EntityId(game.ids["uk"])
    war = War(war_id=war_id_for(usa, uk), a=usa, b=uk, since=date(1941, 9, 4), declared_by=usa)
    state = state.model_copy(update={"wars": {war.war_id: war}})
    view = project(state, next(iter(state.seats)))
    known = destinations.Known(
        keys=destinations.place_keys(state, events_of(game)),
        forces={"us_atlantic_fleet": "US Atlantic Fleet", "us_pacific_fleet": "US Pacific Fleet"},
    )
    lever = next(x for x in rs.desk(view, known)["levers"] if x["name"] == "move_fleet")
    to = {p["label"]: p for p in next(p for p in lever["params"] if p["name"] == "to")["places"]}
    assert to["Rome"]["days"] == {"us_atlantic_fleet": None, "us_pacific_fleet": None}
    assert to["Argentia"]["days"]["us_atlantic_fleet"] is not None


def test_a_move_in_the_truth_does_not_move_the_day_count(fdr: tuple[Realism, Client]) -> None:
    game, ada = fdr
    before = places(ada)["Argentia"]["days"]
    set_feature(game, "us_atlantic_fleet", places=(EntityId(game.ids["argentia"]),))
    assert places(ada)["Argentia"]["days"] == before


def test_each_place_carries_its_reach_per_force(fdr: tuple[Realism, Client]) -> None:
    """The fleets' pages place them where they truly are, so each tier is the rule's own;
    a refused place stays listed, with its reason and the nearest base it can work from."""
    game, ada = fdr
    state = state_of(game)
    key = {v: k for k, v in game.ids.items()}
    found = param(ada, "move_fleet", "to")["places"]
    for name in ("us_atlantic_fleet", "us_pacific_fleet"):
        force = state.features[FeatureId(game.ids[name])]
        for p in found:
            want = bases.reach(state, force, EntityId(game.ids[p["value"]]))
            assert want is not None
            assert p["reach"][name] == {
                "tier": want.tier.value,
                "base": key[want.base] if want.base is not None else None,
                "reason": want.reason,
            }, (name, p["label"])
    shown = places(ada)
    assert shown["Reykjavik"]["reach"]["us_atlantic_fleet"]["tier"] == "sustained"
    assert shown["Kure"]["reach"]["us_pacific_fleet"]["tier"] == "raid"
    china = shown["Chungking"]["reach"]["us_atlantic_fleet"]
    assert china["tier"] == "refused" and china["base"] == "pearl_harbor_base"
    assert "Pearl Harbor" in china["reason"]


def test_an_army_form_reads_the_front_from_the_seats_pages(web: Web) -> None:  # noqa: F811
    game = Realism(web, "autumn-1941")
    joe = game.seat("joe", "stalin")
    game.open_play()
    game.first_tick()
    to = {p["label"]: p for p in param(joe, "move_army", "to")["places"]}
    assert to["Moscow"]["reach"] == {
        "soviet_western_front": {"tier": "sustained", "base": "moscow", "reason": None}
    }
    smolensk = to["Smolensk"]["reach"]["soviet_western_front"]
    assert smolensk["tier"] == "sustained"  # the front runs through it on his page
    london = to["London"]["reach"]["soviet_western_front"]
    assert london["tier"] == "refused" and "sealift" in london["reason"]
    set_feature(
        game, "eastern_front", places=tuple(EntityId(game.ids[k]) for k in ("kalinin", "kharkov"))
    )
    again = {p["label"]: p for p in param(joe, "move_army", "to")["places"]}
    assert again["Smolensk"]["reach"] == to["Smolensk"]["reach"]  # the truth moved, no page did


def test_a_force_no_page_places_has_no_reach(fdr: tuple[Realism, Client]) -> None:
    game, _ = fdr
    state = state_of(game)
    blind = project(state, next(iter(state.seats))).model_copy(update={"documents": {}})
    known = destinations.Known(keys=destinations.place_keys(state, events_of(game)))
    lever = next(x for x in rs.desk(blind, known)["levers"] if x["name"] == "move_fleet")
    to = next(p for p in lever["params"] if p["name"] == "to")
    assert to["places"] and all(r is None for p in to["places"] for r in p["reach"].values())


def test_a_front_and_an_enemy_army_make_a_place_contested(web: Web) -> None:  # noqa: F811
    game = Realism(web, "autumn-1941")
    joe = game.seat("joe", "stalin")
    game.open_play()
    game.first_tick()
    to = param(joe, "move_army", "to")
    groups = {p["label"]: p["group"] for p in to["places"]}
    for own in ("Vyazma", "Mozhaisk", "Moscow"):
        assert groups[own] == "own", own
    for contested in ("Smolensk", "Leningrad", "Kiev", "Odessa"):
        assert groups[contested] == "contested", contested
    assert groups["Norfolk"] == "other"
    moscow = next(p for p in to["places"] if p["label"] == "Moscow")
    army = FeatureKind.ARMY
    assert moscow["days"] == {"soviet_western_front": days(game, army, "vyazma", "moscow")}


def test_other_parameters_carry_no_places(fdr: tuple[Realism, Client]) -> None:
    _, ada = fdr
    for lever in realism_of(ada)["desk"]["levers"]:
        for p in lever["params"]:
            assert set(p) == set(LeverParam.__annotations__)
            if (lever["name"], p["name"]) != ("move_fleet", "to"):
                assert p["places"] == [], (lever["name"], p["name"])


def test_any_place_on_the_map_can_be_filed(fdr: tuple[Realism, Client]) -> None:
    game, ada = fdr
    params = {"force": "us_atlantic_fleet", "to": "halifax_port"}
    status, out = post(ada, "lever", lever="move_fleet", params=params)
    assert status == 200 and out["refused"] is False, out
    (track,) = [o for o in realism_of(ada)["orders"]["orders"] if o["params"].get("to")]
    assert track["terms"] == ["Which fleet: The Atlantic Fleet", "To: Halifax"]
    store = game.web.app.open()
    try:
        state = load_state(store, game.campaign)
    finally:
        store.close()
    (order,) = state.orders.values()
    assert "Halifax" in order_words(state, order) and "halifax_port" not in order_words(
        state, order
    )
    words = _form_words(project(state, order.issuer), order)
    assert "Halifax" in words and "halifax_port" not in words


@pytest.mark.parametrize("to", ["atlantis", "usa", "roosevelt"])
def test_a_place_not_on_the_map_is_refused(fdr: tuple[Realism, Client], to: str) -> None:
    _, ada = fdr
    status, out = post(
        ada, "lever", lever="move_fleet", params={"force": "us_atlantic_fleet", "to": to}
    )
    assert status == 200 and out["refused"] is True, out
    assert "is not a place on the map" in out["reply"]
    assert realism_of(ada)["orders"]["orders"] == []


def test_a_force_no_page_places_has_no_day_count(fdr: tuple[Realism, Client]) -> None:
    game, _ = fdr
    store = game.web.app.open()
    try:
        state = load_state(store, game.campaign)
        events = list(store.read(game.campaign))
    finally:
        store.close()
    seat = next(iter(state.seats))
    blind = project(state, seat).model_copy(update={"documents": {}})
    keys = destinations.place_keys(state, events)
    known = destinations.Known(keys=keys)
    lever = next(x for x in rs.desk(blind, known)["levers"] if x["name"] == "move_fleet")
    to = next(p for p in lever["params"] if p["name"] == "to")
    assert all(d is None for p in to["places"] for d in p["days"].values())
    own = {p["value"] for p in to["places"] if p["group"] == "own"}
    assert own == set(AUTHORED)  # with no page, only the form's own destinations are its own
    assert {p["group"] for p in to["places"]} == {"own", "other"}


def test_without_the_worlds_keys_the_form_offers_its_own_places(
    fdr: tuple[Realism, Client],
) -> None:
    game, _ = fdr
    store = game.web.app.open()
    try:
        state = load_state(store, game.campaign)
    finally:
        store.close()
    view = project(state, next(iter(state.seats)))
    lever = next(x for x in rs.desk(view)["levers"] if x["name"] == "move_fleet")
    to = next(p for p in lever["params"] if p["name"] == "to")
    assert [c["value"] for c in to["choices"]] == AUTHORED
    assert to["places"] == []


def test_place_keys_come_from_the_campaigns_world(fdr: tuple[Realism, Client]) -> None:
    game, _ = fdr
    store = game.web.app.open()
    try:
        state = load_state(store, game.campaign)
        events = list(store.read(game.campaign))
    finally:
        store.close()
    keys = destinations.place_keys(state, events)
    located = {e.key for e in game.decl.entities if e.at is not None}
    assert set(keys.values()) == located
    assert all(keys[EntityId(game.ids[k])] == k for k in located)
    assert destinations.place_keys(state, []) == {}


def test_the_fixture_levers_have_the_api_shape() -> None:
    levers = json.loads(FIXTURE.read_text())["desk"]["levers"]
    shown = [p for lever in levers for p in lever["params"]]
    assert any(p["places"] for p in shown)
    for p in shown:
        assert set(p) == set(LeverParam.__annotations__)
        for place in p["places"]:
            assert set(place) == set(PlaceChoice.__annotations__)
        if p["places"]:
            assert [c["value"] for c in p["choices"]] == [x["value"] for x in p["places"]]
