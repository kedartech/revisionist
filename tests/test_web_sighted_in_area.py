"""The room's map in a territory game when a page sights a piece standing in an area (a
territory or a sea zone), which has no position: the mark carries the area the page named,
its ``places`` only the places with a position, and the seat's block is built for every seat.

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories`` on and a
scouting feed of Ilse's that sights the Sudland levy and galleys, each standing in an area.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import EntityId
from revisionist.core.project import project
from revisionist.core.realism import feeds, territory
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine.web import map_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests import test_adjacency_moves as adj
from tests import test_territory_model as tm
from tests.test_web_people import sighted
from tests.test_web_territory_map import FIXTURES, block, neutral_hills

LEVY, GALLEYS = "The Sudland Levy", "The Sudland Galleys"
COAST = {"key": "sudland_coast", "name": "The Sudland Coast"}


def scouts(*sights: str) -> Callable[[adj.World], None]:
    """Ilse reads a daily scouting report placing the pieces ``sights``."""

    def change(w: adj.World) -> None:
        w.setdefault("feeds", []).append(
            {
                "key": "norra_scouts",
                "name": "Norra scouts",
                "author": "ilse",
                "kind": "report",
                "channel": "cable",
                "sights": list(sights),
                "every_days": 1,
                "latency_days": 0,
                "source": "toy",
            }
        )
        (card,) = [c for c in w["cards"] if c["person"] == "ilse"]
        card["feeds"] = ["norra_scouts"]

    return change


def scouted(state: State) -> State:
    """``state`` with today's scouting page issued and arrived."""
    (feed,) = state.feeds.values()
    issued = feeds.issue(state, feed, adj.START, "seed")
    assert issued is not None
    return adj.fold(state, [issued])


def fixture_game(tmp: Path) -> State:
    """The game the seat fixture's ``sighted_map`` is Ilse's map of: the territory fixture's
    game (``test_web_territory_map.fixture_game``) with a scouting page placing the Sudland
    levy in its coast."""
    world = tm.raw_toy()
    for change in (adj.with_rule, adj.levers, adj.based, neutral_hills, scouts("sudland_levy")):
        change(world)
    return scouted(adj.game(tm.written(tmp, world, tm.TOY_MAP.read_bytes()))[1])


SCOUTS = scouts("sudland_levy", "sudland_galleys")


def stand(state: State, key: str, at: str) -> State:
    """The piece ``key`` stands at ``at`` in the truth, with no page saying so."""
    f = adj.piece(state, key)
    return adj.fold(
        state, [ev.FeatureSet(feature=f.model_copy(update={"places": (adj.entity(at),)}))]
    )


def in_area_game(tmp: Path) -> State:
    """The scouting page has arrived; the levy stands in the Sudland coast, which the board
    gives no position, and the galleys in the Gulf."""
    state = adj.play(tmp, SCOUTS)
    assert adj.where(state, "sudland_levy") == adj.entity("sudland_coast")
    return scouted(state)


def marks(state: State, who: str = "ilse") -> dict[str, dict[str, Any]]:
    return {m["name"]: m for m in block(state, who)["map"]["marks"]}


# --- Rule 1: the block is built for every seat ------------------------------------------


def test_a_page_sighting_a_piece_in_an_area_builds_the_block_for_every_seat(
    tmp_path: Path,
) -> None:
    state = in_area_game(tmp_path)
    for who in ("ilse", "tomas"):
        assert block(state, who)["map"] is not None


# --- Rule 2: the mark carries the area the page named ------------------------------------


def test_the_mark_carries_the_area_and_only_the_places_with_a_position(tmp_path: Path) -> None:
    levy = marks(in_area_game(tmp_path))[LEVY]
    assert levy["area"] == COAST
    assert levy["places"] == []
    assert levy["side"] == "other" and levy["piece"] is None
    assert set(levy["area"]) == set(api.MarkArea.__annotations__)


def test_a_mark_sighted_at_a_place_with_a_position_has_no_area(tmp_path: Path) -> None:
    """A page that names a place with a position, inside the Gulf: drawn there, no area."""
    state = in_area_game(tmp_path)
    roads = adj.entity("gulf_roads")
    paged = sighted(state, private_to(adj.seat("ilse")), adj.entity("sudland"), [roads], adj.START)
    force = marks(paged)["Force 0"]
    assert force["area"] is None
    assert [p["name"] for p in force["places"]] == ["The Gulf Roads"]
    assert marks(paged)[LEVY]["area"] == COAST


def test_a_sea_piece_sighted_in_a_sea_zone_carries_the_zone(tmp_path: Path) -> None:
    state = scouted(stand(adj.play(tmp_path, SCOUTS), "sudland_galleys", "open_sea"))
    galleys = marks(state)[GALLEYS]
    assert galleys["area"] == {"key": "open_sea", "name": "The Open Sea"}
    assert galleys["places"] == []


# --- Rule 3: the area is the page's, never the truth's -----------------------------------


def test_an_enemy_moved_since_the_page_is_shown_where_the_page_had_it(tmp_path: Path) -> None:
    state = in_area_game(tmp_path)
    before = json.dumps(block(state), sort_keys=True)
    after = stand(state, "sudland_levy", "norra_hills")
    assert json.dumps(block(after), sort_keys=True) == before
    assert marks(after)[LEVY]["area"] == COAST


def test_a_piece_no_arrived_page_sighted_is_not_on_the_seats_map(tmp_path: Path) -> None:
    state = in_area_game(tmp_path)
    theirs = marks(state, "tomas")
    assert LEVY not in theirs and GALLEYS not in theirs
    # Tomas reads no page about anyone's pieces, so nothing is placed on his map.
    assert all(m["side"] == "own" and m["area"] is None for m in theirs.values())


# --- Rule 4: games without territories keep their marks ----------------------------------


def test_without_territories_every_mark_has_no_area_and_keeps_its_key(tmp_path: Path) -> None:
    def no_rule(w: adj.World) -> None:
        w["rules"] = []

    state = scouted(adj.play(tmp_path, SCOUTS, no_rule))
    assert not territory.on(state)
    got = marks(state)
    assert {LEVY, GALLEYS} <= set(got)
    assert all(m["area"] is None for m in got.values())
    nation = adj.entity("norra")
    for name, key in ((LEVY, "sudland_levy"), (GALLEYS, "sudland_galleys")):
        raw = territory.mark_key(state, nation, adj.piece(state, key))
        assert got[name]["key"] == map_api.mark_key(state.campaign_id, nation, raw)
        assert got[name]["places"], name


def test_the_area_mark_keeps_the_key_the_piece_had_at_a_place(tmp_path: Path) -> None:
    state = in_area_game(tmp_path)
    nation = adj.entity("norra")
    raw = territory.mark_key(state, nation, adj.piece(state, "sudland_levy"))
    assert marks(state)[LEVY]["key"] == map_api.mark_key(state.campaign_id, nation, raw)


# --- Rule 6: a capital that is an area ----------------------------------------------------


def test_a_capital_that_is_an_area_is_left_out_of_the_pins(tmp_path: Path) -> None:
    state = in_area_game(tmp_path)
    view = project(state, adj.seat("ilse"))
    tomas, coast = adj.entity("tomas"), EntityId(adj.entity("sudland_coast"))
    sudby = adj.entity("sudby")
    line = {
        "person": str(tomas),
        "name": "Tomas Brand",
        "stance": {"word": "Hostile"},
        "at_war": True,
    }
    people: Any = {"opponents": [line]}

    def living(at: EntityId) -> Any:
        moved = view.entities[tomas].model_copy(update={"location": at})
        return view.model_copy(update={"entities": {**view.entities, tomas: moved}})

    assert [c["name"] for c in rs._capitals(living(sudby), people)] == ["Tomas Brand"]
    assert rs._capitals(living(coast), people) == []


# --- The seat fixture -------------------------------------------------------------------


def test_the_seat_fixture_carries_a_mark_a_page_placed_in_an_area(tmp_path: Path) -> None:
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["sighted_map"]
    assert fixture == block(fixture_game(tmp_path))["map"]
    (levy,) = [m for m in fixture["marks"] if m["piece"] is None]
    assert levy["area"] == COAST and levy["places"] == []
    for mark in fixture["marks"]:
        assert set(mark) == set(api.MapMark.__annotations__)
