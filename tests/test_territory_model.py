"""The world file defines the map.

A world may name a map file by name and hash, the terrain, a tree of regions, its land
territories and sea zones, and which of them border. Compile checks all of it against
the file and stores the board, never the shapes, in one ``map_declared`` event; every
view holds the same board. A game finds its map again only by the hash it stored.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, SeatId, derived_id
from revisionist.core.ontology import EntityKind
from revisionist.core.project import project
from revisionist.core.realism import territory
from revisionist.core.state import Rule, State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import (
    PLACES_MIN,
    WorldError,
    check_history,
    compile_world,
    resolve_keys,
)
from revisionist.engine import campaign as cmp
from revisionist.engine import maps

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
HERE = Path(__file__).parent / "worlds"
TOY = HERE / "territory-toy.yaml"
TOY_MAP = HERE / "toy.map.json"
SHAPES = ("vertices", "rings", "backdrop", "label")


def raw_toy() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(TOY.read_text())
    return data


def raw_map() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(TOY_MAP.read_text())
    return data


def written(
    tmp: Path, world: dict[str, Any], board: dict[str, Any] | bytes | None = None
) -> WorldFile:
    """The world and its map written to ``tmp`` and loaded as a world file is."""
    if board is not None:
        data = board if isinstance(board, bytes) else json.dumps(board).encode()
        (tmp / str(world["map"]["file"])).write_bytes(data)
        world["map"].setdefault("sha256", hashlib.sha256(data).hexdigest())
    path = tmp / "world.yaml"
    path.write_text(yaml.safe_dump(world, sort_keys=False))
    return cmp.load_world(path)


def variant(tmp: Path, change: Any = None, board_change: Any = None) -> WorldFile:
    """The toy world with ``change(world)`` and ``board_change(map)`` applied; the
    world's hash is rewritten to the changed map's."""
    world, board = raw_toy(), raw_map()
    if change is not None:
        change(world)
    if board_change is not None:
        board_change(board)
    if "map" in world:
        world["map"].pop("sha256", None)
    return written(tmp, world, board if "map" in world else None)


def created(world: WorldFile) -> tuple[list[ev.Event], State]:
    events = compile_world(world, CAMPAIGN, cmp.versions())
    return events, replay(events)


def entity(key: str) -> EntityId:
    return EntityId(resolve_keys(cmp.load_world(TOY), CAMPAIGN)[key])


def refused(world: WorldFile) -> tuple[str, ...]:
    with pytest.raises(WorldError) as caught:
        compile_world(world, CAMPAIGN, cmp.versions())
    return caught.value.problems


def claim(events: list[ev.Event], *people: str) -> State:
    """The game with each person claimed by a seat of their own."""
    more = list(events)
    for person in people:
        last = more[-1]
        more.append(
            last.model_copy(
                update={
                    "seq": last.seq + 1,
                    "event_id": derived_id(CAMPAIGN, "event", str(last.seq + 1)),
                    "payload": ev.CharacterClaimed(
                        seat_id=SeatId(derived_id(CAMPAIGN, "seat", person)),
                        entity_id=entity(person),
                    ),
                }
            )
        )
    return replay(more)


# --- The board in state -----------------------------------------------------------


def test_the_toy_world_declares_its_board_once() -> None:
    events, state = created(cmp.load_world(TOY))
    declared = [e.payload for e in events if isinstance(e.payload, ev.MapDeclared)]
    assert len(declared) == 1
    board = declared[0].map
    assert state.map == board
    assert board.file == "toy.map.json"
    assert board.sha256 == hashlib.sha256(TOY_MAP.read_bytes()).hexdigest()
    assert board.coords == "flat"
    assert board.box == (0, 0, 300, 200)
    assert [t.key for t in board.territories] == [
        "norra_hills",
        "norra_plain",
        "sudland_coast",
        "isle",
    ]
    assert [z.key for z in board.sea_zones] == ["the_gulf", "open_sea"]
    assert [(r.key, r.parent) for r in board.regions] == [
        ("mainland", None),
        ("north", "mainland"),
        ("south", "mainland"),
        ("waters", None),
    ]
    assert len(board.adjacency) == 8
    assert [link.crossing for link in board.adjacency if link.crossing] == ["the ferry"]
    plain = board.territories[1]
    assert plain.holder == entity("norra")
    assert plain.sites == (entity("norrhavn"),)
    assert plain.terrain == "plain"
    assert plain.region == "north"


def test_the_shapes_never_enter_the_log_or_the_state() -> None:
    events, state = created(cmp.load_world(TOY))
    for text in (
        json.dumps([e.model_dump(mode="json") for e in events]),
        state.model_dump_json(),
    ):
        for word in SHAPES:
            assert f'"{word}"' not in text, word


def test_every_area_is_a_place_named_by_its_key() -> None:
    _, state = created(cmp.load_world(TOY))
    assert state.map is not None
    for t in state.map.territories:
        assert t.area == entity(t.key)
        assert state.entities[t.area].kind is EntityKind.LOCATION
        assert state.entities[t.area].name == t.name
    for z in state.map.sea_zones:
        assert z.area == entity(z.key)
        assert state.entities[z.area].kind is EntityKind.LOCATION
    assert set(state.map.areas()) == {entity(k) for k in raw_map()["areas"]}


def test_a_reference_to_a_place_may_name_an_area(tmp_path: Path) -> None:
    def force(w: dict[str, Any]) -> None:
        w["assets"] = [
            {
                "key": "norra_guard",
                "kind": "force",
                "name": "The Norra Guard",
                "controller": "norra",
                "location": "norra_hills",
            }
        ]

    _, state = created(variant(tmp_path, force))
    (asset,) = state.assets.values()
    assert asset.location == entity("norra_hills")


def test_a_place_is_within_its_area() -> None:
    _, state = created(cmp.load_world(TOY))
    assert state.entities[entity("norrhavn")].within == entity("norra_plain")
    assert state.entities[entity("sudby")].within == entity("sudland_coast")
    assert state.entities[entity("norra")].within is None


def test_the_board_is_the_same_in_every_view() -> None:
    events, _ = created(cmp.load_world(TOY))
    state = claim(events, "ilse", "tomas")
    views = [project(state, seat) for seat in state.seats]
    assert len(views) == 2
    assert all(v.map == state.map for v in views)
    assert state.map is not None


def test_adjacency_is_the_same_either_way_round() -> None:
    _, state = created(cmp.load_world(TOY))
    board = state.map
    assert board is not None
    named = {(link.a, link.b) for link in board.adjacency}
    # The toy names some pairs with the later id first; each reads both ways.
    assert any(a > b for a, b in named)
    for a, b in named:
        assert territory.adjacent(board, a, b)
        assert territory.adjacent(board, b, a)
    assert not territory.adjacent(board, entity("norra_hills"), entity("open_sea"))
    assert territory.adjacent(board, entity("norra_plain"), entity("isle"))


def test_a_territory_carries_its_yields_and_districts(tmp_path: Path) -> None:
    def detail(w: dict[str, Any]) -> None:
        w["territories"][0]["yields"] = {"grain": 3, "iron": 1.5}
        w["territories"][0]["districts"] = ["upper_hills", "lower_hills"]

    def shapes(m: dict[str, Any]) -> None:
        m["districts"] = {"upper_hills": {"rings": [[4, 5, 8, 7, 4]]}, "lower_hills": {}}

    _, state = created(variant(tmp_path, detail, shapes))
    assert state.map is not None
    hills = state.map.territories[0]
    assert hills.yields == {"grain": 3, "iron": 1.5}
    assert hills.districts == ("upper_hills", "lower_hills")


# --- No map ------------------------------------------------------------------------

BOARD_KEYS = ("map", "terrain", "regions", "territories", "sea_zones", "adjacency")


def without_board(w: dict[str, Any]) -> None:
    for key in BOARD_KEYS:
        w.pop(key, None)
    w["entities"] = [e for e in w["entities"] if e["kind"] != "location"]


def test_a_world_with_no_map_has_no_board(tmp_path: Path) -> None:
    events, state = created(variant(tmp_path, without_board))
    assert state.map is None
    assert not any(isinstance(e.payload, ev.MapDeclared) for e in events)
    assert '"map"' not in state.model_dump_json()
    assert not territory.on(state)


def test_the_territory_rules_act_only_on_a_board(tmp_path: Path) -> None:
    def switched(w: dict[str, Any]) -> None:
        w["rules"] = ["territories"]

    _, state = created(variant(tmp_path, switched))
    assert territory.on(state)
    _, plain = created(cmp.load_world(TOY))
    assert not territory.on(plain)
    assert not territory.on(state.model_copy(update={"map": None}))
    assert Rule.TERRITORIES in state.rules


def test_a_place_within_an_area_needs_a_map(tmp_path: Path) -> None:
    def mapless(w: dict[str, Any]) -> None:
        without_board(w)
        w["entities"].append({"key": "spa", "kind": "location", "name": "Spa", "within": "isle"})

    problems = refused(variant(tmp_path, mapless))
    assert "entity spa: within isle, but the world has no map" in problems
    legacy = cmp.load_world(cmp.world_path("salt-strait"))
    place = next(e for e in legacy.entities if e.kind is EntityKind.LOCATION)
    moved = place.model_copy(update={"within": "nowhere"})
    entities = tuple(moved if e is place else e for e in legacy.entities)
    problems = refused(legacy.model_copy(update={"entities": entities}))
    assert f"entity {place.key}: within nowhere, but the world has no map" in problems


def test_territories_switched_on_without_a_map_are_refused(tmp_path: Path) -> None:
    def switched(w: dict[str, Any]) -> None:
        without_board(w)
        w["rules"] = ["territories"]

    assert "rules: territories needs a map" in refused(variant(tmp_path, switched))


def test_nothing_limits_the_number_of_areas(tmp_path: Path) -> None:
    """A 12 by 10 grid of land, 120 territories, in 30 regions."""
    cols, rows = 12, 10
    verts = [[x * 10, y * 10] for y in range(rows + 1) for x in range(cols + 1)]

    def v(x: int, y: int) -> int:
        return y * (cols + 1) + x

    areas, territories, adjacency = {}, [], []
    for y in range(rows):
        for x in range(cols):
            key = f"t{x}_{y}"
            ring = [v(x, y), v(x + 1, y), v(x + 1, y + 1), v(x, y + 1), v(x, y)]
            areas[key] = {"rings": [ring], "label": [x * 10 + 5, y * 10 + 5]}
            territories.append(
                {
                    "key": key,
                    "name": f"Square {x} {y}",
                    "region": f"r{x // 2}_{y // 2}",
                    "terrain": "plain",
                    "holder": "norra" if x < cols // 2 else "sudland",
                    "gap": True,
                }
            )
            if x + 1 < cols:
                adjacency.append([key, f"t{x + 1}_{y}"])
            if y + 1 < rows:
                adjacency.append([key, f"t{x}_{y + 1}"])
    board = {"format": 1, "coords": "flat", "box": [0, 0, 120, 100], "vertices": verts}
    board |= {"areas": areas, "backdrop": []}
    world = raw_toy()
    without_board(world)
    world["map"] = {"coords": "flat", "file": "grid.json", "box": [0, 0, 120, 100]}
    world["terrain"] = [{"key": "plain", "kind": "land"}]
    world["regions"] = [
        {"key": f"r{x}_{y}", "name": f"Region {x} {y}"} for x in range(6) for y in range(5)
    ]
    world["territories"] = territories
    world["adjacency"] = adjacency
    _, state = created(written(tmp_path, world, board))
    assert state.map is not None
    assert len(state.map.territories) == 120
    assert len(state.map.adjacency) == len(adjacency) == 218


# --- What compile refuses ------------------------------------------------------------


def test_a_region_tree_with_a_cycle_is_refused(tmp_path: Path) -> None:
    def cycle(w: dict[str, Any]) -> None:
        w["regions"][0]["parent"] = "north"

    problems = refused(variant(tmp_path, cycle))
    assert "region mainland: its parents lead back to it" in problems
    assert "region north: its parents lead back to it" in problems


def test_an_area_in_an_unknown_region_is_refused(tmp_path: Path) -> None:
    def lost(w: dict[str, Any]) -> None:
        w["territories"][0]["region"] = "nowhere"
        w["sea_zones"][0]["region"] = "deeps"
        w["regions"][1]["parent"] = "overworld"

    problems = refused(variant(tmp_path, lost))
    assert "territory norra_hills: unknown region nowhere" in problems
    assert "sea zone the_gulf: unknown region deeps" in problems
    assert "region north: unknown region overworld" in problems


def test_an_area_on_terrain_of_the_wrong_kind_is_refused(tmp_path: Path) -> None:
    def swapped(w: dict[str, Any]) -> None:
        w["territories"][0]["terrain"] = "deep"
        w["sea_zones"][0]["terrain"] = "plain"
        w["sea_zones"][1]["terrain"] = "lava"

    problems = refused(variant(tmp_path, swapped))
    assert "territory norra_hills: deep is sea terrain, not land" in problems
    assert "sea zone the_gulf: plain is land terrain, not sea" in problems
    assert "sea zone open_sea: unknown terrain lava" in problems


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        (["norra_hills", "atlantis"], "adjacency norra_hills-atlantis: unknown area atlantis"),
        (["norra", "isle"], "adjacency norra-isle: norra is not an area"),
        (["isle", "isle"], "adjacency isle-isle: links an area to itself"),
        (["norra_plain", "norra_hills"], "adjacency norra_plain-norra_hills: listed twice"),
        (
            {"a": "norra_hills", "b": "norra_plain", "crossing": "a bridge"},
            "adjacency norra_hills-norra_plain: listed twice",
        ),
    ],
)
def test_a_bad_adjacency_entry_is_refused(
    tmp_path: Path, entry: list[str] | dict[str, str], problem: str
) -> None:
    def add(w: dict[str, Any]) -> None:
        w["adjacency"].append(entry)

    assert problem in refused(variant(tmp_path, add))


@pytest.mark.parametrize(
    ("holder", "problem"),
    [
        ("ilse", "territory norra_hills: holder ilse is not a polity"),
        ("nobody", "territory norra_hills: unknown entity nobody"),
        ("norrhavn", "territory norra_hills: holder norrhavn is not a polity"),
    ],
)
def test_a_land_territory_held_by_no_polity_is_refused(
    tmp_path: Path, holder: str, problem: str
) -> None:
    def held(w: dict[str, Any]) -> None:
        w["territories"][0]["holder"] = holder

    assert problem in refused(variant(tmp_path, held))


def test_a_sea_zone_has_no_holder(tmp_path: Path) -> None:
    def held(w: dict[str, Any]) -> None:
        w["sea_zones"][0]["holder"] = "norra"

    with pytest.raises(ValueError, match="holder"):
        variant(tmp_path, held)


def test_a_place_within_an_unknown_area_is_refused(tmp_path: Path) -> None:
    def moved(w: dict[str, Any]) -> None:
        w["entities"][4]["within"] = "atlantis"
        w["entities"][5]["within"] = "norra"
        w["entities"][0]["within"] = "isle"

    problems = refused(variant(tmp_path, moved))
    assert "entity norrhavn: within unknown area atlantis" in problems
    assert "entity sudby: within norra, which is not an area" in problems
    assert "entity norra: only a place lies within an area" in problems


def test_a_site_must_be_a_place_within_its_territory(tmp_path: Path) -> None:
    def sites(w: dict[str, Any]) -> None:
        w["territories"][0]["sites"] = ["norrhavn", "ilse", "elsewhere"]
        w["territories"][3]["sites"] = ["sudby"]

    problems = refused(variant(tmp_path, sites))
    assert "territory norra_hills: site norrhavn is within norra_plain" in problems
    assert "territory norra_hills: site ilse is not a place" in problems
    assert "territory norra_hills: unknown entity elsewhere" in problems
    assert "territory isle: site sudby is within sudland_coast" in problems


def test_a_missing_map_file_is_refused(tmp_path: Path) -> None:
    world = raw_toy()
    world["map"]["file"] = "lost.json"
    assert "map: the map file lost.json is not found" in refused(written(tmp_path, world))


def test_a_map_file_whose_hash_differs_is_refused(tmp_path: Path) -> None:
    world = raw_toy()
    board = raw_map()
    board["areas"]["isle"]["label"] = [251, 100]
    data = json.dumps(board).encode()
    problems = refused(written(tmp_path, world, data))
    named, actual = world["map"]["sha256"], hashlib.sha256(data).hexdigest()
    assert f"map: the world names {named}, but toy.map.json hashes to {actual}" in problems


def test_a_map_file_that_is_not_a_map_is_refused(tmp_path: Path) -> None:
    world = raw_toy()
    world["map"].pop("sha256")
    assert "map: toy.map.json is not a map file" in refused(written(tmp_path, world, b"[1, 2]"))


def test_a_map_whose_areas_differ_from_the_worlds_is_refused(tmp_path: Path) -> None:
    def fewer(w: dict[str, Any]) -> None:
        w["sea_zones"].pop()
        w["adjacency"] = [a for a in w["adjacency"] if "open_sea" not in a]

    def more(m: dict[str, Any]) -> None:
        m["areas"]["skerry"] = m["areas"].pop("isle")

    problems = refused(variant(tmp_path, fewer, more))
    assert "map: area open_sea is in the map file but not in the world" in problems
    assert "map: area skerry is in the map file but not in the world" in problems
    assert "map: area isle is in the world but not in the map file" in problems


def test_a_district_missing_from_the_map_file_is_refused(tmp_path: Path) -> None:
    def detail(w: dict[str, Any]) -> None:
        w["territories"][0]["districts"] = ["upper_hills", "lower_hills"]

    def shapes(m: dict[str, Any]) -> None:
        m["districts"] = {"upper_hills": {}}

    problems = refused(variant(tmp_path, detail, shapes))
    assert "territory norra_hills: district lower_hills is not in the map file" in problems


def test_a_flat_map_needs_a_box(tmp_path: Path) -> None:
    def boxless(w: dict[str, Any]) -> None:
        del w["map"]["box"]

    assert "map: a flat map needs a box" in refused(variant(tmp_path, boxless))


def test_a_place_on_a_flat_map_lies_in_its_box(tmp_path: Path) -> None:
    def outside(w: dict[str, Any]) -> None:
        w["entities"][4]["at"] = [150, 350]

    problems = refused(variant(tmp_path, outside))
    assert "entity norrhavn: at [150, 350] is outside the map's box" in problems


def test_areas_without_a_map_are_refused(tmp_path: Path) -> None:
    def mapless(w: dict[str, Any]) -> None:
        del w["map"]
        for e in w["entities"]:
            e.pop("at", None)

    problems = refused(variant(tmp_path, mapless))
    assert "map: the world has areas but no map" in problems


def test_only_a_realism_world_has_a_map(tmp_path: Path) -> None:
    world = cmp.load_world(TOY)
    legacy = world.model_copy(update={"ruleset": "legacy", "cards": (), "sources": (), "wars": ()})
    problems = refused(legacy)
    assert "map: only a realism world has map" in problems
    assert "territories: only a realism world has territories" in problems


def test_two_regions_or_terrains_with_one_key_are_refused(tmp_path: Path) -> None:
    def doubled(w: dict[str, Any]) -> None:
        w["regions"].append({"key": "north", "name": "The Far North"})
        w["terrain"].append({"key": "deep", "kind": "land"})

    problems = refused(variant(tmp_path, doubled))
    assert "region north: duplicate key" in problems
    assert "terrain deep: duplicate key" in problems


def test_an_area_key_shares_the_one_namespace(tmp_path: Path) -> None:
    def clash(w: dict[str, Any]) -> None:
        w["territories"][3]["key"] = "norrhavn"

    with pytest.raises(WorldError) as caught:
        compile_world(variant(tmp_path, clash), CAMPAIGN, cmp.versions())
    assert "entity norrhavn: duplicate key" in caught.value.problems


# --- Coordinates ---------------------------------------------------------------------


def lonlat(w: dict[str, Any]) -> None:
    """The toy board laid on degrees: x as longitude 10 to 40, y as latitude 40 to 60."""
    w["map"] = {"coords": "lonlat", "file": "toy-lonlat.json", "box": [10, 40, 40, 60]}
    w["entities"][4]["at"] = [55, 25]
    w["entities"][5]["at"] = [44, 16]


def degrees(m: dict[str, Any]) -> None:
    m["coords"] = "lonlat"
    m["box"] = [10, 40, 40, 60]
    m["vertices"] = [[10 + x / 10, 40 + y / 10] for x, y in m["vertices"]]
    for area in m["areas"].values():
        x, y = area["label"]
        area["label"] = [10 + x / 10, 40 + y / 10]


def test_a_lonlat_board_reads_places_in_degrees(tmp_path: Path) -> None:
    world = raw_toy()
    lonlat(world)
    board = raw_map()
    degrees(board)
    _, state = created(written(tmp_path, world, board))
    assert state.map is not None
    assert state.map.coords == "lonlat"
    assert state.entities[entity("norrhavn")].at == (55, 25)


def test_a_lonlat_place_is_a_latitude_and_longitude(tmp_path: Path) -> None:
    world = raw_toy()
    lonlat(world)
    world["entities"][4]["at"] = [150, 150]
    board = raw_map()
    degrees(board)
    with pytest.raises(ValueError, match="latitude"):
        written(tmp_path, world, board)


def test_a_world_without_a_map_keeps_latitude_and_longitude() -> None:
    raw = yaml.safe_load(cmp.world_path("autumn-1941").read_text())
    place = next(e for e in raw["entities"] if e.get("at"))
    place["at"] = [91, 0]
    with pytest.raises(ValueError):
        WorldFile.model_validate(raw)


def test_the_drafters_schema_is_unchanged() -> None:
    schema = WorldFile.model_json_schema()
    props = schema["properties"]
    for key in BOARD_KEYS:
        assert key not in props, key
    entity_props = schema["$defs"]["EntityDecl"]["properties"]
    assert "within" not in entity_props
    at = entity_props["at"]["anyOf"][0]
    assert at["prefixItems"] == [
        {"maximum": 90, "minimum": -90, "type": "number"},
        {"maximum": 180, "minimum": -180, "type": "number"},
    ]


# --- Finding a map by its hash ---------------------------------------------------------


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    objects, named = tmp_path / "objects", tmp_path / "maps"
    objects.mkdir()
    named.mkdir()
    monkeypatch.setenv(maps.OBJECTS_ENV, str(objects))
    monkeypatch.setattr(maps, "MAPS_DIR", named)
    return objects, named


def test_a_map_is_found_by_its_hash(stores: tuple[Path, Path]) -> None:
    objects, named = stores
    old, new = b'{"areas": {"a": 1}}', b'{"areas": {"b": 2}}'
    sha_old = hashlib.sha256(old).hexdigest()
    (objects / f"{sha_old}.json").write_bytes(old)
    # The world now names a corrected file under the same name.
    (named / "board.json").write_bytes(new)
    assert maps.map_object(sha_old, "board.json") == old
    assert maps.map_object(hashlib.sha256(new).hexdigest(), "board.json") == new


def test_a_map_whose_hash_differs_is_never_returned(stores: tuple[Path, Path]) -> None:
    objects, named = stores
    data = b'{"areas": {}}'
    sha = hashlib.sha256(data).hexdigest()
    (objects / f"{sha}.json").write_bytes(data + b" ")
    (named / "board.json").write_bytes(data + b"  ")
    assert maps.map_object(sha, "board.json") is None
    assert maps.map_object(sha) is None
    assert maps.map_object("../" + sha, "board.json") is None


def test_the_objects_directory_defaults_to_the_shipped_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(maps.OBJECTS_ENV, raising=False)
    assert maps.objects_dir() == cmp.WORLDS_DIR / "maps" / "objects"
    manifest = (maps.objects_dir() / "MANIFEST").read_text().split()
    sha = next(line for line in manifest if not line.startswith("#") and len(line) == 64)
    data = maps.map_object(sha)
    assert data is not None
    assert hashlib.sha256(data).hexdigest() == sha


def test_the_stored_hash_finds_the_toy_map(stores: tuple[Path, Path]) -> None:
    _, named = stores
    (named / "toy.map.json").write_bytes(TOY_MAP.read_bytes())
    _, state = created(cmp.load_world(TOY))
    assert state.map is not None
    assert maps.map_object(state.map.sha256, state.map.file) == TOY_MAP.read_bytes()


# --- Places counted for a drafted world ---------------------------------------------


def test_areas_count_as_places_for_a_draft(tmp_path: Path) -> None:
    world = variant(tmp_path)
    places = [e for e in world.entities if e.kind is EntityKind.LOCATION]
    assert len(places) + len(world.territories) + len(world.sea_zones) >= PLACES_MIN
    assert len(places) < PLACES_MIN
    assert not any("places:" in p for p in check_history(world))
