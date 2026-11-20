"""The map as the seat sees it in a territory game (TMD): the board's areas and regions in
the ``map`` block, the ``map`` action serving the map object the game's stored hash names,
and the moves lit on each own piece, computed from the seat's own view.

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories`` on.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.realism import bases, kinds, territory
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.territory import Plan
from revisionist.core.state import State
from revisionist.engine import maps
from revisionist.engine.web import map_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests import test_adjacency_moves as adj
from tests import test_territory_model as tm
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, post

FIXTURES = Path(__file__).parents[1] / "web" / "test" / "fixtures"
SEATS = ("ilse", "tomas")
AREAS = ("norra_hills", "norra_plain", "sudland_coast", "isle", "the_gulf", "open_sea")


def block(state: State, who: str = "ilse") -> dict[str, Any]:
    return rs.seat_realism(state, adj.seat(who), set(), set(), None)


def pieces(state: State, who: str = "ilse") -> dict[str, dict[str, Any]]:
    marks = block(state, who)["map"]["marks"]
    return {m["name"]: m["piece"] for m in marks if m["piece"] is not None}


def moves(state: State, name: str, who: str = "ilse") -> dict[str, dict[str, Any]]:
    return {m["area"]["key"]: m for m in pieces(state, who)[name]["moves"]}


def neutral_hills(w: adj.World) -> None:
    """A power at war with nobody holds the Norra hills, so the levy reaches the Sudland
    coast only by lift; the levy is small enough for Norra's shipping."""
    w["entities"].append({"key": "ostmark", "kind": "polity", "name": "Ostmark"})
    (hills,) = [t for t in w["territories"] if t["key"] == "norra_hills"]
    hills["holder"] = "ostmark"
    adj.set_feature("norra_levy", tier=1)(w)


def fixture_game(tmp: Path) -> State:
    """The game the seat fixture's ``territory_map`` is Ilse's map of: the toy world on its
    committed map file, with bases, a neutral in the hills and a field order."""
    world = tm.raw_toy()
    for change in (adj.with_rule, adj.levers, adj.based, neutral_hills):
        change(world)
    return adj.game(tm.written(tmp, world, tm.TOY_MAP.read_bytes()))[1]


def area(key: str, name: str) -> dict[str, Any]:
    return {"key": key, "name": name, "place": None}


def area_key(state: State, at: Any) -> str:
    assert state.map is not None
    keys = {t.area: t.key for t in state.map.territories}
    keys |= {z.area: z.key for z in state.map.sea_zones}
    return keys[at]


# --- Rule 1: the map block gains the board ------------------------------------------


def test_a_territory_map_block_carries_the_areas_the_regions_and_the_file(
    tmp_path: Path,
) -> None:
    state = adj.play(tmp_path, adj.levers)
    assert state.map is not None
    m = block(state)["map"]
    assert (m["coords"], m["box"]) == ("flat", [0, 0, 300, 200])
    assert m["file"] == {"name": "toy.map.json", "sha256": state.map.sha256}
    shown = {a["key"]: a for a in m["areas"]}
    assert set(shown) == set(AREAS)
    assert shown["norra_plain"] == {
        "key": "norra_plain",
        "name": "The Norra Plain",
        "kind": "land",
        "region": "north",
        "terrain": "plain",
        "neighbours": ["isle", "norra_hills", "open_sea", "the_gulf"],
        "holder": None,  # holders are off in this game
        "held_since": None,
        "taken_from": None,
        "falling": None,
        "yields": {"grain": 10, "levies": 2000},
        "threatened_from": None,
    }
    assert (shown["the_gulf"]["kind"], shown["the_gulf"]["terrain"]) == ("sea", "shallows")
    assert shown["isle"]["neighbours"] == ["norra_plain", "open_sea"]
    assert m["regions"] == [
        {"key": "mainland", "name": "The Mainland", "parent": None},
        {"key": "north", "name": "The North", "parent": "mainland"},
        {"key": "south", "name": "The South", "parent": "mainland"},
        {"key": "waters", "name": "The Waters", "parent": None},
    ]


def test_the_board_is_the_same_for_every_seat(tmp_path: Path) -> None:
    state = adj.play(tmp_path, adj.levers)
    keys = ("areas", "regions", "coords", "box", "file")
    ilse, tomas = block(state, "ilse")["map"], block(state, "tomas")["map"]
    assert {k: ilse[k] for k in keys} == {k: tomas[k] for k in keys}


# --- Rule 2: the map action serves the object the stored hash names -------------------


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    objects, named = tmp_path / "objects", tmp_path / "named"
    objects.mkdir()
    named.mkdir()
    monkeypatch.setenv(maps.OBJECTS_ENV, str(objects))
    monkeypatch.setattr(maps, "MAPS_DIR", named)
    return objects, named


def stored(tmp_path: Path, objects: Path, *changes: Callable[[adj.World], None]) -> State:
    """The toy game, with its map kept as an object under its stored hash."""
    state = adj.play(tmp_path, *changes)
    assert state.map is not None
    data = (tmp_path / state.map.file).read_bytes()
    (objects / f"{state.map.sha256}.json").write_bytes(data)
    return state


def corrected(named: Path, state: State) -> bytes:
    """The world now names a corrected file under the game's file name."""
    assert state.map is not None
    board = json.loads((named.parent / state.map.file).read_text())
    board["areas"]["isle"]["label"] = [251, 101]
    data = json.dumps(board).encode()
    (named / state.map.file).write_bytes(data)
    return data


def test_the_map_action_serves_the_object_the_stored_hash_names(
    tmp_path: Path, stores: tuple[Path, Path]
) -> None:
    objects, named = stores
    state = stored(tmp_path, objects)
    assert state.map is not None
    kept = json.loads((tmp_path / state.map.file).read_text())
    assert json.loads(corrected(named, state)) != kept
    out = map_api.map_reply(state)
    assert out["refused"] is False
    assert out["map"] == kept
    assert out["file"] == {"name": "toy.map.json", "sha256": state.map.sha256}


def test_a_map_with_no_object_for_its_hash_is_refused_in_one_line(
    tmp_path: Path, stores: tuple[Path, Path]
) -> None:
    _, named = stores
    state = adj.play(tmp_path)
    corrected(named, state)
    out = map_api.map_reply(state)
    assert out == {
        "reply": "This game's map is missing on the server.",
        "refused": True,
        "file": None,
        "map": None,
    }


def test_the_world_named_file_is_served_while_its_bytes_still_hash_the_same(
    tmp_path: Path, stores: tuple[Path, Path]
) -> None:
    _, named = stores
    state = adj.play(tmp_path)
    assert state.map is not None
    data = (tmp_path / state.map.file).read_bytes()
    (named / state.map.file).write_bytes(data)
    out = map_api.map_reply(state)
    assert out["refused"] is False and out["map"] == json.loads(data)


def test_the_map_action_answers_every_seat_alike_through_the_server(
    web: Web,  # noqa: F811
    tmp_path: Path,
    stores: tuple[Path, Path],
) -> None:
    objects, _ = stores
    state = stored(tmp_path, objects, adj.levers)
    game = Realism(web, str(tmp_path / "world.yaml"))
    clients = [game.seat("ada", "ilse"), game.seat("bea", "tomas")]
    game.open_play()
    replies = []
    for client in clients:
        status, out = post(client, "map")
        assert status == 200, out
        replies.append(out)
    assert replies[0] == replies[1]
    assert replies[0]["refused"] is False
    assert replies[0]["map"] == json.loads((tmp_path / "toy.map.json").read_text())
    assert state.map is not None and replies[0]["file"]["sha256"] == state.map.sha256


def test_the_toy_map_fixture_is_the_map_the_action_serves(
    tmp_path: Path, stores: tuple[Path, Path]
) -> None:
    objects, _ = stores
    out = map_api.map_reply(stored(tmp_path, objects))
    fixture = json.loads((FIXTURES / "toy.map.json").read_text())
    assert out["map"] == fixture
    assert fixture == json.loads((Path(__file__).parent / "worlds" / "toy.map.json").read_text())


def shape(examples: list[Any], kind: Any) -> None:
    """Each example has every key ``kind`` declares, required or not."""
    assert examples
    for example in examples:
        assert set(example) == set(kind.__annotations__), kind.__name__


def test_the_seat_fixture_carries_a_territory_map_in_the_snapshot_shape(tmp_path: Path) -> None:
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["territory_map"]
    assert fixture == block(fixture_game(tmp_path))["map"]
    # ``reports`` comes only with the reports rule: the reports fixture checks it (RPD)
    assert set(fixture) == set(api.SeatMap.__annotations__) - {"reports"}
    shape(fixture["areas"], api.MapArea)
    shape(fixture["regions"], api.MapRegion)
    shape([fixture["file"]], api.MapFile)
    own = [m["piece"] for m in fixture["marks"] if m["piece"] is not None]
    shape(own, api.MapPiece)
    lit = [move for p in own for move in p["moves"]]
    shape(lit, api.MapMove)
    shape([a for move in lit for a in (move["area"], *move["path"])], api.PieceArea)
    shape([move["lift"] for move in lit if move["lift"] is not None], api.MapLift)
    assert {move["reach"] for move in lit} == {None, "operate", "raid"}
    # The file is the one the fixture's map object is.
    assert fixture["file"]["sha256"] == territory.file_hash(
        (FIXTURES / "toy.map.json").read_bytes()
    )


# --- Rule 3: each own piece carries the moves lit for it ------------------------------


def test_each_own_piece_carries_every_area_it_can_be_sent_to(tmp_path: Path) -> None:
    state = adj.play(tmp_path, adj.levers)
    lit = moves(state, "The Norra Levy")
    assert set(lit) == {"norra_hills", "sudland_coast", "isle"}
    assert lit["sudland_coast"] == {
        "area": area("sudland_coast", "The Sudland Coast"),
        "path": [
            area("norra_hills", "The Norra Hills"),
            area("sudland_coast", "The Sudland Coast"),
        ],
        "step_days": [7, 5],
        "days": 12,
        "reach": None,
        "lift": None,
    }
    assert lit["isle"]["path"] == [area("isle", "The Isle")]
    # An envoy goes anywhere but enemy ground (ENV): Sudland holds the coast and the Isle.
    enemy = {"norra_plain", "sudland_coast", "isle"}
    assert set(moves(state, "The Norra Herald")) == set(AREAS) - enemy
    assert set(moves(state, "The Sudland Levy", "tomas")) == {"norra_hills", "norra_plain", "isle"}


def test_the_lit_moves_are_the_movement_rules_own_courses(tmp_path: Path) -> None:
    state = adj.play(tmp_path, adj.levers)
    for key, name in (("norra_levy", "The Norra Levy"), ("norra_kites", "The Norra Kites")):
        f = adj.piece(state, key)
        for k, move in moves(state, name).items():
            found = territory.plan(state, f, adj.entity(k))
            assert isinstance(found, Plan)
            assert [a["key"] for a in move["path"]] == [area_key(state, a) for a in found.path]
            assert move["step_days"] == list(found.days) and move["days"] == found.total


def test_a_move_by_lift_names_the_lift_it_needs(tmp_path: Path) -> None:
    state = adj.clear_gulf(adj.play(tmp_path, adj.levers, adj.lift_world))
    lit = moves(state, "The Norra Levy")
    assert lit["sudland_coast"]["path"] == [
        area("the_gulf", "The Gulf"),
        area("sudland_coast", "The Sudland Coast"),
    ]
    assert lit["sudland_coast"]["lift"] == {
        "tons": territory.lift_tons(adj.piece(state, "norra_levy")),
        "carrier": "Galley",
    }
    assert lit["sudland_coast"]["lift"]["tons"] == 50_000
    assert lit["norra_hills"]["lift"] is None


def test_a_move_names_its_reach_tier_from_the_bases(tmp_path: Path) -> None:
    state = adj.play(tmp_path, adj.levers, adj.based)
    kites = adj.piece(state, "norra_kites")
    lit = moves(state, "The Norra Kites")
    tiers = {k: m["reach"] for k, m in lit.items()}
    for k, tier in tiers.items():
        found = bases.area_reach(state, kites, adj.entity(k))
        assert found is not None and tier == found.tier.value
    assert tiers["norra_hills"] == "operate" and "raid" in tiers.values()
    assert moves(state, "The Norra Herald")["the_gulf"]["reach"] is None


def test_a_piece_under_way_is_lit_from_the_area_it_stands_in(tmp_path: Path) -> None:
    state = adj.send(adj.play(tmp_path, adj.levers), "ilse", "norra_levy", "sudby")
    state, _ = adj.walk(state, adj.day(1), adj.day(7))
    lit = moves(state, "The Norra Levy")
    assert "norra_hills" not in lit
    assert lit["sudland_coast"]["path"] == [area("sudland_coast", "The Sudland Coast")]


# --- Rule 4: lit moves come from the seat's own view ----------------------------------


def moved(state: State, f: Feature, to: str) -> State:
    """``f`` stood in ``to`` in the truth, with no page saying so."""
    there = f.model_copy(update={"places": (adj.entity(to),)})
    return adj.fold(state, [ev.FeatureSet(feature=there)])


def stands_in(state: State, f: Feature) -> list[str]:
    """The areas a piece of ``f``'s domain can stand in."""
    assert state.map is not None
    domain = kinds.domain(state, f)
    land = [t.key for t in state.map.territories]
    sea = [z.key for z in state.map.sea_zones]
    return land if domain == "land" else sea if domain == "sea" else land + sea


def test_an_unseen_enemy_changes_no_other_seats_payload(tmp_path: Path) -> None:
    state = adj.play(tmp_path, adj.levers, adj.based)
    nation = {"ilse": adj.entity("norra"), "tomas": adj.entity("sudland")}
    for who in SEATS:
        before = json.dumps(block(state, who), sort_keys=True)
        theirs = [
            f
            for f in state.features.values()
            if territory.nation(state, f.side) not in (None, nation[who])
        ]
        assert theirs
        for f in theirs:
            for to in stands_in(state, f):
                after = json.dumps(block(moved(state, f, to), who), sort_keys=True)
                assert after == before, (who, f.name, to)


def test_an_area_an_unseen_enemy_holds_is_lit_as_an_empty_one(tmp_path: Path) -> None:
    state = adj.play(tmp_path, adj.levers)
    empty = moves(state, "The Norra Levy")
    enemy = adj.piece(state, "sudland_levy")
    held = moves(moved(state, enemy, "norra_hills"), "The Norra Levy")
    assert held == empty


def test_the_moves_are_planned_on_a_board_holding_only_the_seats_own_pieces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def gold(w: adj.World) -> None:
        w["quantities"].append(
            {
                "key": "sudland_gold",
                "owner": "sudland",
                "name": "Sudland's gold",
                "value": 5,
                "unit": "tons",
                "source": "toy",
            }
        )

    state = adj.play(tmp_path, adj.levers, gold)
    assert len(state.quantities) == 2
    seen: list[tuple[set[str], set[str]]] = []
    real = territory.plans

    def spy(board: State, piece: Any) -> Any:
        names = {f.name for f in board.features.values()}
        seen.append((names, {q.name for q in board.quantities.values()}))
        return real(board, piece)

    monkeypatch.setattr(territory, "plans", spy)
    block(state, "ilse")
    assert seen, "the moves are planned with territory.plans"
    own = {"The Norra Levy", "The Norra Kites", "The Norra Herald"}
    assert all(names <= own and pools <= {"Norra's shipping"} for names, pools in seen)


# --- Rule 5: a game without territories sends none of the new keys --------------------


def test_without_territories_the_map_block_and_pieces_keep_their_keys(tmp_path: Path) -> None:
    def off(w: adj.World) -> None:
        w["rules"] = []

    state = adj.play(tmp_path, adj.levers, off)
    assert not territory.on(state)
    m = block(state)["map"]
    assert set(m) == {"places", "marks", "orders", "capitals"}
    own = [mark["piece"] for mark in m["marks"] if mark["piece"] is not None]
    assert own and all("moves" not in p for p in own)


def test_without_territories_the_map_action_refuses(tmp_path: Path) -> None:
    def off(w: adj.World) -> None:
        w["rules"] = []

    out = map_api.map_reply(adj.play(tmp_path, off))
    assert out == {
        "reply": "This game has no territory map.",
        "refused": True,
        "file": None,
        "map": None,
    }
