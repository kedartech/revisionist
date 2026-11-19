"""Supply: pieces operate only within reach of the rail and ports their side holds (SUP).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories``,
``holders``, ``economy`` and ``supply`` on, and ``with_supply`` adds a railway. Norra and
Sudland are at war. Norra's rail hub is the hills and Sudland's the coast; the plain
(Norrhavn) is Norra's one port. Over land the hills border the plain and the coast, and
the Isle borders the plain by the ferry, so the coast is two steps from the plain and the
Isle is three from the coast.
"""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import state_hash
from revisionist.core.realism import supply, war_rules
from revisionist.core.realism.bases import RADIUS_STEPS, Radius
from revisionist.core.realism.economy import SUPPLY_LAG_DAYS
from revisionist.core.world import WorldFile
from tests.test_adjacency_moves import (
    START,
    Logged,
    World,
    based,
    entity,
    levers,
    piece,
    seat,
    set_feature,
)
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_economy import taken

HILLS, PLAIN, COAST, ISLE = "norra_hills", "norra_plain", "sudland_coast", "isle"
Change = Callable[[World], None]


def with_supply(w: World) -> None:
    """The rules on, and a railway (the supply role) with a hub in the hills and on the coast."""
    w["rules"] = ["territories", "holders", "economy", "supply"]
    w["resources"].append({"key": "track", "name": "Railway", "unit": "miles", "role": "supply"})
    for t in w["territories"]:
        if t["key"] in (HILLS, COAST):
            t["yields"] = {**t.get("yields", {}), "track": 1}


def toy(tmp: Path, *changes: Change) -> WorldFile:
    return territories_toy(tmp, with_supply, *changes)


def game(tmp: Path, *changes: Change) -> Logged:
    return Logged(toy(tmp, *changes), "ilse", "tomas")


def hub(area: str, on: bool) -> Change:
    """The railway on ``area`` or not."""

    def change(w: World) -> None:
        (t,) = [t for t in w["territories"] if t["key"] == area]
        kept = {k: v for k, v in t.get("yields", {}).items() if k != "track"}
        t["yields"] = kept | ({"track": 1} if on else {})

    return change


def no_port(w: World) -> None:
    """Norrhavn is no longer a port, so the plain is no source."""
    for e in w["entities"]:
        if e["key"] == "norrhavn":
            e.pop("port_on")


def third_power(at_war: bool) -> Change:
    """Ostmark holds the Isle, which carries a railway; at war with Sudland, or with nobody."""

    def change(w: World) -> None:
        w["entities"].append({"key": "ostmark", "kind": "polity", "name": "Ostmark"})
        (isle,) = [t for t in w["territories"] if t["key"] == ISLE]
        isle["holder"] = "ostmark"
        isle["yields"] = {"track": 1}
        if at_war:
            war = {"a": "ostmark", "b": "sudland", "since": "1900-03-01", "source": "toy"}
            w["wars"].append(war)

    return change


def place(key: str, within: str, at: tuple[int, int]) -> Change:
    """A named place in an area, for a piece to stand at."""

    def change(w: World) -> None:
        w["entities"].append(
            {"key": key, "kind": "location", "name": key, "at": list(at), "within": within}
        )

    return change


ON_THE_ISLE = (
    place("isle_fort", ISLE, (100, 250)),
    set_feature("sudland_levy", places=["isle_fort"]),
)


def railed() -> tuple[Change, ...]:
    """Norra's hub in the hills is its one source; the plain is no port."""
    return (no_port, levers)


def lone(*changes: Change) -> tuple[Change, ...]:
    """Norra with no hub of its own and no port; Sudland's hub on the coast stays."""
    return (hub(HILLS, False), no_port, levers, *changes)


def status(g: Logged, key: str) -> supply.Status:
    found = supply.status(g.state, piece(g.state, key))
    assert found is not None
    return found


def advance(g: Logged, days: int) -> None:
    g.add([ev.DateAdvanced(to=START + timedelta(days=days))])


def words(g: Logged, by: str, force: str, to: str) -> str:
    return war_rules.order_refusal(g.state, seat(by), "move_piece", {"force": force, "to": to})


# --- Rule 1: a land piece is supplied by a short chain of its own and allied land -------


def test_a_levy_on_a_hub_or_a_port_is_in_supply(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert status(g, "norra_levy") == supply.Status(True, entity(PLAIN), 0, None)
    assert status(g, "sudland_levy") == supply.Status(True, entity(COAST), 0, None)


def test_a_levy_a_step_from_a_hub_is_in_supply(tmp_path: Path) -> None:
    g = game(tmp_path, *railed())
    assert status(g, "norra_levy") == supply.Status(True, entity(HILLS), 1, None)


def test_the_chain_is_at_most_supply_steps_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = game(tmp_path, *lone())
    taken(g, COAST, "norra", START)
    advance(g, SUPPLY_LAG_DAYS)
    assert supply.SUPPLY_STEPS == 2
    assert status(g, "norra_levy") == supply.Status(True, entity(COAST), 2, None)
    monkeypatch.setattr(supply, "SUPPLY_STEPS", 1)
    assert not status(g, "norra_levy").supplied


def test_the_chain_does_not_run_through_enemy_land(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = game(tmp_path, *ON_THE_ISLE, levers)
    monkeypatch.setattr(supply, "SUPPLY_STEPS", 3)  # the coast is three steps off, by enemy land
    found = status(g, "sudland_levy")
    assert found == supply.Status(False, None, None, entity(COAST))


def test_land_an_ally_holds_counts_and_land_a_neutral_holds_does_not(tmp_path: Path) -> None:
    allied = game(tmp_path, *lone(third_power(True)))
    assert status(allied, "norra_levy") == supply.Status(True, entity(ISLE), 1, None)
    neutral = game(tmp_path, *lone(third_power(False)))
    assert not status(neutral, "norra_levy").supplied


def test_a_chain_cut_by_a_captured_hub_leaves_the_piece_out_of_supply(tmp_path: Path) -> None:
    g = game(tmp_path, *railed())
    assert status(g, "norra_levy").supplied
    assert words(g, "ilse", "norra_levy", "sudby") == ""
    taken(g, HILLS, "sudland", START)
    assert status(g, "norra_levy") == supply.Status(False, None, None, None)
    assert words(g, "ilse", "norra_levy", "sudby") == (
        "The Norra Levy is out of supply, so it cannot be sent into The Norra Hills, "
        "held by Sudland."
    )


def test_a_captured_hub_works_for_its_taker_only_after_the_lag(tmp_path: Path) -> None:
    g = game(tmp_path, *lone())
    taken(g, COAST, "norra", START)
    for n in (0, SUPPLY_LAG_DAYS - 1):
        advance(g, n)
        assert not status(g, "norra_levy").supplied, n
    advance(g, SUPPLY_LAG_DAYS)
    assert status(g, "norra_levy").supplied


# --- Rule 2: sea and air pieces are supplied within their kind's radius of a base -------


def test_a_ship_is_in_supply_within_the_radius_of_a_base_of_its_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = game(
        tmp_path,
        based,
        place("deep", "open_sea", (180, 215)),
        set_feature("sudland_galleys", places=["deep"]),
    )
    assert status(g, "sudland_galleys").supplied
    monkeypatch.setitem(RADIUS_STEPS, "sea", Radius(0, None))
    assert not status(g, "sudland_galleys").supplied


def test_an_air_wing_and_an_envoy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    g = game(tmp_path, based, set_feature("norra_kites", places=["sudby"]))
    assert not status(g, "norra_kites").supplied  # a raid at two steps, not an operation
    assert status(g, "norra_herald").supplied
    monkeypatch.setitem(RADIUS_STEPS, "air", Radius(2, None))
    assert status(g, "norra_kites").supplied


def test_a_board_with_no_bases_sets_no_limit_on_ships(tmp_path: Path) -> None:
    assert status(game(tmp_path), "sudland_galleys").supplied


# --- Rule 3: out of supply, no order into enemy land ---------------------------------


def test_the_refusal_names_the_nearest_area_the_piece_is_supplied_in(tmp_path: Path) -> None:
    g = game(tmp_path, *ON_THE_ISLE, levers)
    assert words(g, "tomas", "sudland_levy", "norrhavn") == (
        "The Sudland Levy is out of supply, so it cannot be sent into The Norra Plain, "
        "held by Norra. The nearest area it would be supplied in is The Sudland Coast."
    )


def test_an_unsupplied_piece_may_still_go_through_its_own_land(tmp_path: Path) -> None:
    g = game(tmp_path, *railed())
    taken(g, HILLS, "sudland", START)
    assert not status(g, "norra_levy").supplied
    assert words(g, "ilse", "norra_levy", "norrhavn") == ""
    taken(g, HILLS, "norra", START)
    assert words(g, "ilse", "norra_levy", HILLS) == ""


def test_a_supplied_piece_may_be_sent_into_enemy_land(tmp_path: Path) -> None:
    g = game(tmp_path, levers)
    assert words(g, "ilse", "norra_levy", "sudby") == ""
    assert words(g, "tomas", "sudland_levy", "norrhavn") == ""


# --- Rule 4 and 5: one function, from the state alone, and only when switched on -------


def test_status_is_a_function_of_the_state_and_stores_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, *lone())
    before = state_hash(g.state)
    first = status(g, "norra_levy")
    assert status(g, "norra_levy") == first
    assert state_hash(g.state) == before


def test_without_the_rule_there_is_no_supply_and_no_refusal(tmp_path: Path) -> None:
    def off(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy"]

    g = Logged(territories_toy(tmp_path, off, *lone()), "ilse", "tomas")
    taken(g, HILLS, "sudland", START)
    assert supply.status(g.state, piece(g.state, "norra_levy")) is None
    assert words(g, "ilse", "norra_levy", "sudby") == ""
