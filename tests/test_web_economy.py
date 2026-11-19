"""Holders and the war economy as the seat sees them (WEV).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories``,
``holders`` and ``economy`` on. Ilse sits for Norra, which holds the hills (no yields) and
the plain (grain 10, levies 2000); Tomas sits for Sudland, which holds the coast (grain 6,
iron 2) and the Isle. Norra and Sudland are at war.

Every land area of the seat's ``map`` block carries its holder, the day it changed hands
and the holder it was taken from, and, for the holding nation's seats, the day a capital
in it was marked to fall. Every area carries the yields the board prints. The ``economy``
block holds every nation's public figure and, for the seat's own nation only, its income
by resource, its pools, its months of fuel left and each held territory's factors.
"""

import json
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.realism import economy
from revisionist.core.realism.economy import CAPTURE_LAG_DAYS, Pools
from revisionist.core.state import State
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests import test_economy as te
from tests import test_holders as th
from tests.test_adjacency_moves import START, Logged, World, day, entity, seat
from tests.test_adjacency_moves import toy as territories_toy

FIXTURES = Path(__file__).parents[1] / "web" / "test" / "fixtures"
NORRA, SUDLAND = te.NORRA, te.SUDLAND
ISLE, COAST, PLAIN, HILLS = te.ISLE, te.COAST, te.PLAIN, te.HILLS


def block(state: State, who: str = "ilse") -> dict[str, Any]:
    return rs.seat_realism(state, seat(who), set(), set(), None)


def areas(state: State, who: str = "ilse") -> dict[str, dict[str, Any]]:
    return {a["key"]: a for a in block(state, who)["map"]["areas"]}


def nation(key: str, name: str, relation: str) -> dict[str, Any]:
    return {"key": entity(key), "name": name, "relation": relation}


def own(state: State, who: str = "ilse") -> dict[str, Any]:
    out = block(state, who)["economy"]
    assert out is not None and out["own"] is not None
    return dict(out["own"])


def fixture_game(tmp: Path) -> State:
    """The game the seat fixture's ``economy`` is Ilse's block of: the toy world with
    the economy on, the Isle yielding every role and taken by Norra on day 0, a grain
    yield moved from the plain to the hills, and the first of May paid."""
    g = te.game(tmp, te.RICH_ISLE)
    te.taken(g, ISLE, NORRA, START)
    g.add([economy.move_yield(g.state, entity(PLAIN), entity(HILLS), "grain", 4, START)])
    g.walk(day(1), te.MAY_1)
    return g.state


# --- Rule 1: each land area carries its holder, the day and the holder it was taken from


def test_every_land_area_carries_the_holder_the_world_gives(tmp_path: Path) -> None:
    shown = areas(te.game(tmp_path).state)
    assert shown[PLAIN]["holder"] == nation(NORRA, "Norra", "own")
    assert shown[COAST]["holder"] == nation(SUDLAND, "Sudland", "enemy")
    for key in (PLAIN, HILLS, COAST, ISLE):
        assert (shown[key]["held_since"], shown[key]["taken_from"]) == (None, None)
        assert shown[key]["falling"] is None
    for key in ("the_gulf", "open_sea"):
        sea = shown[key]
        assert (sea["holder"], sea["held_since"], sea["taken_from"], sea["falling"]) == (
            None,
            None,
            None,
            None,
        )


def test_a_taken_territory_names_its_new_holder_the_day_and_the_old_one(
    tmp_path: Path,
) -> None:
    g = te.game(tmp_path)
    te.taken(g, ISLE, NORRA, day(3))
    for who, relation, was in (("ilse", "own", "enemy"), ("tomas", "enemy", "own")):
        isle = areas(g.state, who)[ISLE]
        assert isle["holder"] == nation(NORRA, "Norra", relation)
        assert isle["held_since"] == day(3).isoformat()
        assert isle["taken_from"] == nation(SUDLAND, "Sudland", was)


def test_a_holder_at_peace_with_the_seat_is_neutral(tmp_path: Path) -> None:
    def ostmark(w: World) -> None:
        w["entities"].append({"key": "ostmark", "kind": "polity", "name": "Ostmark"})
        (hills,) = [t for t in w["territories"] if t["key"] == HILLS]
        hills["holder"] = "ostmark"

    shown = areas(te.game(tmp_path, ostmark).state)
    assert shown[HILLS]["holder"] == nation("ostmark", "Ostmark", "neutral")


def test_the_holding_seat_sees_the_day_its_capital_was_marked_to_fall(tmp_path: Path) -> None:
    w = th.to_capital(tmp_path)
    w.close()
    state = w.state
    marked = state.captures[entity(COAST)].marked_on
    assert marked is not None
    assert areas(state, "tomas")[COAST]["falling"] == marked.isoformat()
    # The mark is the holding nation's warning: the other seat is not told.
    assert areas(state, "ilse")[COAST]["falling"] is None


def test_without_holders_no_area_names_a_holder(tmp_path: Path) -> None:
    state = Logged(territories_toy(tmp_path), "ilse", "tomas").state
    assert all(a["holder"] is None for a in areas(state).values())


# --- Rule 2: the economy block: every figure, and the seat's own nation in full --------


def test_the_block_holds_every_nations_figure_the_same_for_every_seat(tmp_path: Path) -> None:
    state = te.game(tmp_path).state
    figures = block(state, "ilse")["economy"]["figures"]
    assert [(f["nation"]["name"], f["figure"]) for f in figures] == [
        ("Norra", economy.figure(state, entity(NORRA))),
        ("Sudland", economy.figure(state, entity(SUDLAND))),
    ]
    assert figures[0]["figure"] == 100
    theirs = block(state, "tomas")["economy"]["figures"]
    assert [(f["nation"]["key"], f["figure"]) for f in theirs] == [
        (f["nation"]["key"], f["figure"]) for f in figures
    ]
    assert block(state, "ilse")["economy"]["day"] == START.isoformat()


def test_the_seat_sees_its_own_income_by_resource_with_the_worlds_names(
    tmp_path: Path,
) -> None:
    mine = own(te.game(tmp_path).state)
    assert mine["nation"] == nation(NORRA, "Norra", "own")
    assert mine["income"] == [
        {"key": "grain", "name": "Grain", "unit": "tons", "role": "output", "amount": 10},
        {"key": "iron", "name": "Iron", "unit": "tons", "role": "output", "amount": 0},
        {"key": "levies", "name": "Levies", "unit": "men", "role": "manpower", "amount": 2000},
        {"key": "pitch", "name": "Pitch", "unit": "barrels", "role": "fuel", "amount": 0},
    ]


def test_income_by_resource_counts_each_territorys_factor(tmp_path: Path) -> None:
    g = te.game(tmp_path, te.yields(ISLE, iron=4))
    te.taken(g, ISLE, NORRA, START)
    g.add([ev.DateAdvanced(to=day(CAPTURE_LAG_DAYS + 1))])
    iron = {i["key"]: i["amount"] for i in own(g.state)["income"]}["iron"]
    assert iron == 2  # half the Isle's 4 after the lag


def test_the_seat_sees_its_own_pools(tmp_path: Path) -> None:
    g = te.game(tmp_path)
    assert own(g.state)["pools"] == {"output": 0, "manpower": 0}
    g.walk(day(1), te.MAY_1)
    assert own(g.state, "ilse")["pools"] == {"output": 10, "manpower": 2000}
    assert own(g.state, "tomas")["pools"] == {"output": 8, "manpower": 0}


def test_each_held_territory_carries_its_factor_by_role(tmp_path: Path) -> None:
    g = te.game(tmp_path, te.RICH_ISLE)
    te.taken(g, ISLE, NORRA, START)
    held = {t["area"]: t for t in own(g.state)["territories"]}
    assert set(held) == {HILLS, PLAIN, ISLE}
    assert held[ISLE]["name"] == "The Isle"
    assert held[ISLE]["yields"] == {"iron": 4, "levies": 100, "pitch": 2, "rails": 3, "glory": 1}
    assert held[ISLE]["factors"] == {
        "output": 0,
        "manpower": 0,
        "fuel": 0,
        "supply": 0,
        "prestige": 1,
    }
    assert held[PLAIN]["factors"] == {r: 1 for r in held[PLAIN]["factors"]}
    g.add([ev.DateAdvanced(to=day(CAPTURE_LAG_DAYS))])
    held = {t["area"]: t for t in own(g.state)["territories"]}
    assert held[ISLE]["factors"]["output"] == 0.5


def test_months_of_fuel_are_not_known_before_a_fuel_stock_exists(tmp_path: Path) -> None:
    assert own(te.game(tmp_path).state)["fuel_months"] is None


def test_without_economy_there_is_no_block(tmp_path: Path) -> None:
    state = Logged(th.toy(tmp_path), "ilse", "tomas").state
    assert block(state)["economy"] is None


# --- The fog: no other nation's pool, stock, moved yield or factor in any payload ------


def _fogged(tmp: Path) -> State:
    """Norra's pools and moved yields carry figures no other number in the game has."""
    g = te.game(tmp)
    g.add(
        [
            ev.EconomySet(
                polity=entity(NORRA), pools=Pools(output=4321.5, manpower=8765.25), on=START
            )
        ]
    )
    g.add([economy.move_yield(g.state, entity(PLAIN), entity(HILLS), "grain", 3.75, START)])
    return g.state


def test_no_other_nations_pools_moved_yields_or_factors_reach_the_seat(tmp_path: Path) -> None:
    state = _fogged(tmp_path)
    mine = json.dumps(block(state, "ilse"))
    theirs = json.dumps(block(state, "tomas"))
    for secret in ("4321.5", "8765.25", "3.75", "6.25"):
        assert secret in mine
        assert secret not in theirs
    held = {t["area"] for t in own(state, "tomas")["territories"]}
    assert held == {COAST, ISLE}


# --- Rule 3: each area carries its printed yields ---------------------------------------


def test_each_area_carries_the_yields_the_board_prints(tmp_path: Path) -> None:
    state = _fogged(tmp_path)
    for who in ("ilse", "tomas"):
        shown = areas(state, who)
        assert shown[PLAIN]["yields"] == {"grain": 10, "levies": 2000}  # printed, not moved
        assert shown[COAST]["yields"] == {"grain": 6, "iron": 2}
        assert shown[HILLS]["yields"] == {}
        assert shown["the_gulf"]["yields"] == {}


# --- The shapes -----------------------------------------------------------------------


def shape(examples: list[Any], kind: Any) -> None:
    assert examples
    for example in examples:
        assert set(example) == set(kind.__annotations__), kind.__name__


def test_the_seat_fixture_carries_an_economy_block_in_the_snapshot_shape(
    tmp_path: Path,
) -> None:
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["economy"]
    assert fixture == block(fixture_game(tmp_path))["economy"]
    shape([fixture], api.EconomyBlock)
    shape([f for f in fixture["figures"]], api.EconomyFigure)
    shape([f["nation"] for f in fixture["figures"]], api.MapNation)
    shape([fixture["own"]], api.EconomyOwn)
    shape(fixture["own"]["income"], api.EconomyIncome)
    shape(fixture["own"]["territories"], api.EconomyTerritory)
    shape([fixture["own"]["pools"]], api.EconomyPools)


def test_the_seat_fixture_carries_areas_with_holders_in_the_snapshot_shape(
    tmp_path: Path,
) -> None:
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["economy_areas"]
    assert fixture == block(fixture_game(tmp_path))["map"]["areas"]
    shape(fixture, api.MapArea)
    shape([a["holder"] for a in fixture if a["holder"] is not None], api.MapNation)
    (isle,) = [a for a in fixture if a["key"] == ISLE]
    assert isle["taken_from"] is not None and isle["held_since"] is not None
