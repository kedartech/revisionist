"""A movement form's destination carries the area each offered place puts each force in (BPA).

On a territory map a piece stands in an area while a form may still offer places as its
destinations (the 1941 fleet forms offer bases). The board lights the area a place lies in, so
the seat's form says, for each force it offers, the area that force would stand in at each
offered place: map geography, never a report. A game without territories carries none.
"""

from pathlib import Path
from typing import Any

from revisionist.core.state import State
from tests import test_adjacency_moves as adj
from tests import test_territory_model as tm
from tests.test_web_territory_map import AREAS, block, fixture_game


def to_param(state: State, who: str = "ilse") -> dict[str, Any]:
    (lever,) = [x for x in block(state, who)["desk"]["levers"] if x["name"] == "move_piece"]
    (to,) = [p for p in lever["params"] if p["name"] == "to"]
    return dict(to)


def galleys_moved_by_form(w: adj.World) -> None:
    """Sudland's galleys on the form too, so a sea piece's areas can be read from Tomas's seat."""
    for card in w["cards"]:
        for lever in card.get("levers", []):
            for p in lever["params"]:
                if p["name"] == "force" and "sudland_galleys" not in p["choices"]:
                    p["choices"] = [*p["choices"], "sudland_galleys"]


def test_each_offered_place_names_the_area_it_puts_each_of_the_forms_forces_in(
    tmp_path: Path,
) -> None:
    areas = to_param(fixture_game(tmp_path))["areas"]
    assert areas["norra_levy"] == {"sudby": "sudland_coast", "norrhavn": "norra_plain"}
    assert areas["norra_kites"] == {"sudby": "sudland_coast", "norrhavn": "norra_plain"}


def test_a_sea_piece_at_a_port_stands_in_the_zone_the_port_opens_on(tmp_path: Path) -> None:
    world = tm.raw_toy()
    for change in (adj.with_rule, adj.levers, galleys_moved_by_form):
        change(world)
    state = adj.game(tm.written(tmp_path, world, tm.TOY_MAP.read_bytes()))[1]
    areas = to_param(state, "tomas")["areas"]
    assert areas["sudland_galleys"]["norrhavn"] == "the_gulf"
    assert areas["sudland_levy"]["norrhavn"] == "norra_plain"


def test_the_areas_are_only_the_maps_and_only_for_the_forms_own_forces(tmp_path: Path) -> None:
    state = fixture_game(tmp_path)
    (lever,) = [x for x in block(state)["desk"]["levers"] if x["name"] == "move_piece"]
    (force,) = [p for p in lever["params"] if p["name"] == "force"]
    (to,) = [p for p in lever["params"] if p["name"] == "to"]
    assert set(to["areas"]) <= {c["value"] for c in force["choices"]}
    offered = {c["value"] for c in to["choices"]}
    for by_place in to["areas"].values():
        assert set(by_place) <= offered
        assert set(by_place.values()) <= set(AREAS)
    assert force["areas"] == {}, "only the destination carries areas"


def test_a_game_without_territories_carries_no_areas(tmp_path: Path) -> None:
    world = tm.raw_toy()
    adj.levers(world)
    state = adj.game(tm.written(tmp_path, world, tm.TOY_MAP.read_bytes()))[1]
    for lever in block(state)["desk"]["levers"]:
        assert all(p["areas"] == {} for p in lever["params"])
