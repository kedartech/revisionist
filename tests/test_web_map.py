"""The map in ``/api/me`` (realism, Batch 6b): only what the seat's own pages place,
as of when they placed it. A move in the truth reaches the map only with a page, except
the seat's own pieces: each force its own movement forms name is sent as a piece, with
its area, strength and orders (PCS). Every mark has an opaque key."""

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId, EventId, FeatureId, derived_id
from revisionist.core.realism import territory
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    BodyField,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.engine import campaign as cmp
from revisionist.engine.store import load_state
from revisionist.engine.web import map_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web.realism_api import MapMark, MapPlace, SeatMap
from tests import test_adjacency_moves as adj
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin

CANARY = "CANARY-FLEET-TRUTH-3e9d"


@pytest.fixture
def fdr(web: Web) -> tuple[Realism, Client]:  # noqa: F811
    game = Realism(web, "autumn-1941")
    client = game.seat("ada", "roosevelt")
    game.open_play()
    game.first_tick()
    return game, client


POINTS = str(Path(__file__).parent / "worlds" / "autumn-1941-points.yaml")
"""The 1941 world before territories, for the cases that move a force between places."""


@pytest.fixture
def fdr_points(web: Web) -> tuple[Realism, Client]:  # noqa: F811
    game = Realism(web, POINTS)
    client = game.seat("ada", "roosevelt")
    game.open_play()
    game.first_tick()
    return game, client


def set_feature(game: Realism, key: str, **update: Any) -> None:
    """Change one feature in the truth, as a resolver would, without a page."""
    store = game.web.app.open()
    try:
        state = load_state(store, game.campaign)
        f = state.features[FeatureId(game.ids[key])]
        store.append_all(
            [
                ev.Event(
                    event_id=EventId(derived_id(game.campaign, "test-feature", key)),
                    campaign_id=game.campaign,
                    seq=state.last_seq + 1,
                    tick=state.tick,
                    scope=PUBLIC,
                    payload=ev.FeatureSet(feature=f.model_copy(update=update)),
                    versions=cmp.versions(),
                )
            ]
        )
    finally:
        store.close()


def marks(client: Client) -> dict[str, dict[str, Any]]:
    return {m["name"]: m for m in realism_of(client)["map"]["marks"]}


def test_the_map_shows_what_the_seats_pages_place(fdr_points: tuple[Realism, Client]) -> None:
    _, ada = fdr_points
    seen = marks(ada)
    assert set(seen) == {
        "Arctic convoys",
        "HX convoys",
        "Home Fleet",
        "SC convoys",
        "U-boat arm",
        "US Atlantic Fleet",
        "US Pacific Fleet",
    }
    atlantic = seen["US Atlantic Fleet"]
    assert (atlantic["side"], atlantic["certainty"], atlantic["side_name"]) == (
        "own",
        "known",
        "United States",
    )
    assert [p["name"] for p in atlantic["places"]] == ["Norfolk"]
    assert seen["U-boat arm"]["side"] == "other" and seen["U-boat arm"]["certainty"] == "reported"
    assert atlantic["source"] == "Harold R. Stark"
    # the page it came from opens
    status, page = post(ada, "read", doc_id=atlantic["document"])
    assert status == 200 and any(b["label"] == "US Atlantic Fleet" for b in page["body"])


def test_a_feature_no_page_places_is_nowhere_in_a_response(
    fdr_points: tuple[Realism, Client],
) -> None:
    game, ada = fdr_points
    set_feature(game, "combined_fleet", name=CANARY)
    text = json.dumps(ada.me())
    for absent in (CANARY, "Combined Fleet", "Army Group Centre", "The Eastern Front"):
        assert absent not in text
    text = json.dumps(post(ada, "advance")[1]) + json.dumps(ada.me())
    assert CANARY not in text


def test_a_move_in_the_truth_waits_for_a_page(fdr_points: tuple[Realism, Client]) -> None:
    game, ada = fdr_points
    store = game.web.app.open()
    try:
        today = load_state(store, game.campaign).in_world_date
    finally:
        store.close()
    reykjavik = EntityId(game.ids["reykjavik"])
    set_feature(game, "us_atlantic_fleet", places=(reykjavik,), as_of=today)
    assert [p["name"] for p in marks(ada)["US Atlantic Fleet"]["places"]] == ["Norfolk"]
    post(ada, "advance")
    after = marks(ada)["US Atlantic Fleet"]
    assert [p["name"] for p in after["places"]] == ["Reykjavik"]


def test_map_words_carry_no_engine_words(fdr: tuple[Realism, Client]) -> None:
    _, ada = fdr
    m = realism_of(ada)["map"]
    for mark in m["marks"]:
        for text in (
            mark["name"],
            mark["side_name"],
            mark["source"],
            *(p["name"] for p in mark["places"]),
        ):
            assert "_" not in text and "truth" not in text.lower()


def test_the_fixture_map_has_the_snapshot_shape() -> None:
    fixture = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
    m = json.loads(fixture.read_text())["map"]
    # A point game's map: the territory keys are the fixture's ``territory_map`` (TMD).
    assert set(m) == set(SeatMap.__required_keys__)
    for p in m["places"]:
        assert set(p) == set(MapPlace.__annotations__)
    for mark in m["marks"]:
        assert set(mark) == set(MapMark.__annotations__)
        for p in mark["places"]:
            assert set(p) == set(MapPlace.__annotations__)
    pieces = [mark["piece"] for mark in m["marks"] if mark["piece"] is not None]
    assert pieces, "the fixture shows one own piece"
    for piece in pieces:
        assert set(piece) == set(api.MapPiece.__required_keys__)
        assert set(piece["area"]) == set(api.PieceArea.__annotations__)
        if piece["waiting"] is not None:
            assert set(piece["waiting"]) == set(api.PieceWait.__annotations__)
        if piece["under_way"] is not None:
            assert set(piece["under_way"]) == set(api.PieceCourse.__annotations__)
            for area in piece["under_way"]["path"]:
                assert set(area) == set(api.PieceArea.__annotations__)


def test_a_movement_order_shows_on_the_map_until_a_page_places_the_force(
    fdr: tuple[Realism, Client],
) -> None:
    _, ada = fdr
    assert realism_of(ada)["map"]["orders"] == []
    params = {"force": "us_atlantic_fleet", "to": "argentia"}
    status, out = post(ada, "lever", lever="move_fleet", params=params)
    assert status == 200 and out["refused"] is False, out
    (order,) = realism_of(ada)["map"]["orders"]
    assert order["force"] == "US Atlantic Fleet" and order["mark"] == "US Atlantic Fleet"
    assert order["to"]["name"] == "Argentia" and order["status"] == "awaiting"
    assert order["with_person"] == "Harold R. Stark"


# --- pieces sent as pieces (PCS) ------------------------------------------------------


def state_of(game: Realism) -> State:
    store = game.web.app.open()
    try:
        return load_state(store, game.campaign)
    finally:
        store.close()


def feature_named(state: State, name: str) -> Any:
    (found,) = [f for f in state.features.values() if f.name == name]
    return found


def plant_line(game: Realism, label: str, value: int) -> None:
    """A page that reaches every seat today with one line: ``label``, ``value``."""
    state = state_of(game)
    today = state.in_world_date
    assert today is not None
    doc_id = DocumentId(derived_id(game.campaign, "doc", "strength", label))
    page = DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.REPORT,
        author=EntityId(game.ids["stark"]),
        issued=today,
        arrives=today,
        channel=ChannelKind.LETTER,
        title="A count of the boats",
        body=(BodyField(label=label, value=value, unit="strength"),),
        scope=PUBLIC,
    )
    store = game.web.app.open()
    try:
        store.append_all(
            [
                ev.Event(
                    event_id=EventId(derived_id(game.campaign, "test-page", label)),
                    campaign_id=game.campaign,
                    seq=state.last_seq + 1,
                    tick=state.tick,
                    scope=PUBLIC,
                    payload=ev.DocumentIssued(document=page, truth=DocumentTruth(doc_id=doc_id)),
                    versions=cmp.versions(),
                )
            ]
        )
    finally:
        store.close()


@pytest.fixture
def fdr_open(web: Web) -> tuple[Realism, Client]:  # noqa: F811
    game = Realism(web, "autumn-1941")
    client = game.seat("ada", "roosevelt")
    make_host(game, client)
    begin(game)
    return game, client


@pytest.fixture
def pair(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    game = Realism(web, "autumn-1941")
    ada = game.seat("ada", "roosevelt")
    bea = game.seat("bea", "churchill")
    game.open_play()
    game.first_tick()
    return game, ada, bea


@pytest.fixture
def pair_points(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    game = Realism(web, POINTS)
    ada = game.seat("ada", "roosevelt")
    bea = game.seat("bea", "churchill")
    game.open_play()
    game.first_tick()
    return game, ada, bea


def toy_marks(state: State, who: str = "ilse") -> dict[str, dict[str, Any]]:
    block = rs.seat_realism(state, adj.seat(who), set(), set(), None)
    return {m["name"]: dict(m) for m in block["map"]["marks"]}


def test_every_mark_carries_an_opaque_key_its_nation_shares(fdr: tuple[Realism, Client]) -> None:
    game, ada = fdr
    shown = realism_of(ada)["map"]["marks"]
    state = state_of(game)
    usa = EntityId(game.ids["usa"])
    ids = set(game.ids.values()) | {str(f) for f in state.features}
    for mark in shown:
        assert re.fullmatch(r"m[0-9a-f]{32}", mark["key"]), mark
        assert mark["key"] not in ids
        raw = territory.mark_key(state, usa, feature_named(state, mark["name"]))
        assert mark["key"] == map_api.mark_key(state.campaign_id, usa, raw)
    assert len({m["key"] for m in shown}) == len(shown)
    assert [m["key"] for m in realism_of(ada)["map"]["marks"]] == [m["key"] for m in shown]


def test_a_steps_mark_is_the_key_the_map_shows(tmp_path: Path) -> None:
    state = adj.play(tmp_path, adj.levers)
    state = adj.send(state, "ilse", "norra_levy", "sudby")
    state, stepped = adj.walk(state, adj.day(1), adj.day(12))
    key = toy_marks(state)["The Norra Levy"]["key"]
    assert stepped and {map_api.step_key(state.campaign_id, s) for s in stepped} == {key}


def test_each_own_force_the_forms_name_is_sent_as_a_piece(tmp_path: Path) -> None:
    state = adj.play(tmp_path, adj.levers, adj.set_feature("norra_levy", tier=3))
    seen = toy_marks(state)
    assert {n for n, m in seen.items() if m["piece"] is not None} == {
        "The Norra Levy",
        "The Norra Kites",
        "The Norra Herald",
    }
    levy = seen["The Norra Levy"]
    assert (levy["side"], levy["certainty"], levy["places"]) == ("own", "known", [])
    # With territories on, the piece also carries its lit moves (TMD).
    assert {k: v for k, v in levy["piece"].items() if k != "moves"} == {
        "key": levy["key"],
        "kind": "Levy",
        "domain": "land",
        "strength": 3,
        "posture": None,
        "area": {"key": "norra_plain", "name": "The Norra Plain", "place": None},
        "waiting": None,
        "under_way": None,
    }
    assert seen["The Norra Kites"]["piece"]["kind"] == "Kite Wing"
    assert seen["The Norra Herald"]["piece"]["domain"] == "envoy"
    assert "The Sudland Levy" not in seen


def test_a_piece_under_way_carries_its_path_its_step_and_its_arrival(tmp_path: Path) -> None:
    state = adj.play(tmp_path, adj.levers)
    state = adj.send(state, "ilse", "norra_levy", "sudby")
    course = toy_marks(state)["The Norra Levy"]["piece"]["under_way"]
    assert [a["key"] for a in course["path"]] == ["norra_hills", "sudland_coast"]
    assert course["path"][0] == {"key": "norra_hills", "name": "The Norra Hills", "place": None}
    assert (course["step_due"], course["arrives"]) == (
        adj.day(7).isoformat(),
        adj.day(12).isoformat(),
    )
    state, _ = adj.walk(state, adj.day(1), adj.day(7))
    levy = toy_marks(state)["The Norra Levy"]
    assert levy["places"] == []
    assert levy["piece"]["area"] == {"key": "norra_hills", "name": "The Norra Hills", "place": None}
    assert [a["key"] for a in levy["piece"]["under_way"]["path"]] == ["sudland_coast"]
    assert levy["piece"]["under_way"]["step_due"] == adj.day(12).isoformat()


def test_an_own_order_with_a_holder_waits_with_whom_until_when_and_can_be_withdrawn(
    fdr_open: tuple[Realism, Client],
) -> None:
    game, ada = fdr_open
    status, out = post(
        ada, "lever", lever="move_fleet", params={"force": "us_atlantic_fleet", "to": "argentia"}
    )
    assert status == 200 and out["refused"] is False, out
    state = state_of(game)
    (order,) = [o for o in state.orders.values() if o.params.get("force") == "us_atlantic_fleet"]
    started = order.outcomes[-1].on if order.outcomes else order.filed
    days = state.pipelines[order.pipeline].steps[order.step].days
    until = None if days is None else date.fromordinal(started.toordinal() + days).isoformat()
    assert marks(ada)["US Atlantic Fleet"]["piece"]["waiting"] == {
        "order": order.order_id,
        "with_person": "Harold R. Stark",
        "until": until,
        "withdrawable": True,
    }
    assert ada.me()["game"]["withdrawable"] == [order.order_id]
    status, out = post(ada, "withdraw", order_id=order.order_id)
    assert status == 200 and out["refused"] is False, out
    assert marks(ada)["US Atlantic Fleet"]["piece"]["waiting"] is None


def test_without_territories_a_piece_stands_at_its_place_as_the_truth_has_it(
    fdr_points: tuple[Realism, Client],
) -> None:
    game, ada = fdr_points
    fleet = marks(ada)["US Atlantic Fleet"]
    norfolk = {"name": "Norfolk", "lat": 36.9, "lon": -76.3, "theatre": "North America"}
    assert fleet["piece"] == {
        "key": fleet["key"],
        "kind": "Fleet",
        "domain": "sea",
        "strength": 4,
        "posture": None,
        "area": {"key": "norfolk", "name": "Norfolk", "place": norfolk},
        "waiting": None,
        "under_way": None,
    }
    today = state_of(game).in_world_date
    assert today is not None
    reykjavik = EntityId(game.ids["reykjavik"])
    set_feature(game, "us_atlantic_fleet", places=(reykjavik,), as_of=today)
    moved = marks(ada)["US Atlantic Fleet"]
    assert [p["name"] for p in moved["places"]] == ["Norfolk"]
    assert moved["piece"]["area"]["key"] == "reykjavik"


def test_an_enemy_mark_has_no_strength_until_a_page_states_one(
    fdr_points: tuple[Realism, Client],
) -> None:
    """A sighting mark, in a game without reports: with reports on, autumn 1941 sends other
    sides' pieces only as reports."""
    game, ada = fdr_points
    assert feature_named(state_of(game), "U-boat arm").tier > 0
    boats = marks(ada)["U-boat arm"]
    assert (boats["strength"], boats["piece"]) == (None, None)
    plant_line(game, "U-boat arm", 2)
    assert marks(ada)["U-boat arm"]["strength"] == 2


def test_another_seats_force_has_no_piece_and_another_nations_key(
    pair_points: tuple[Realism, Client, Client],
) -> None:
    """Sighting marks, in a game without reports (as above)."""
    _, ada, bea = pair_points
    mine, theirs = marks(ada), marks(bea)
    assert mine["Home Fleet"]["piece"] is None
    assert theirs["Home Fleet"]["piece"] is not None
    assert mine["Home Fleet"]["key"] != theirs["Home Fleet"]["key"]
    assert mine["US Atlantic Fleet"]["piece"] is not None
    assert all(m["piece"] is None for n, m in theirs.items() if n.startswith("US "))
    text = json.dumps(bea.me())
    for mark in mine.values():
        assert mark["key"] not in text
