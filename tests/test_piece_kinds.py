"""The world names its piece kinds, terrain and resources (PKD).

The territory toy world names its own kinds (a levy, a galley, a kite wing, a herald)
and resources (grain, timber, levies, pitch). Rules ask what a piece is only through
``kinds.domain`` and ``kinds.is_force``, and what a resource is for only through its
role, so the same world with its kinds named ``army`` and ``fleet`` plays the same.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, replay
from revisionist.core.ids import FeatureId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import kinds
from revisionist.core.realism.geography import Feature, FeatureKind
from revisionist.core.realism.kinds import Domain, Role
from revisionist.core.realism.territory import Terrain, TerrainKind
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from tests.test_territory_model import (
    CAMPAIGN,
    TOY,
    claim,
    created,
    entity,
    raw_toy,
    refused,
    variant,
    without_board,
    written,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "revisionist"
SALT_STRAIT = Path(__file__).resolve().parents[1] / "worlds" / "salt-strait.yaml"
# The 1941 world as it stood before territories: a world with no kinds, resources or pieces.
POINTS = str(Path(__file__).parent / "worlds" / "autumn-1941-points.yaml")


def toy_state() -> State:
    return created(cmp.load_world(TOY))[1]


def piece_kind(w: dict[str, Any], key: str) -> dict[str, Any]:
    found: list[dict[str, Any]] = [k for k in w["piece_kinds"] if k["key"] == key]
    (one,) = found
    return one


def feature(w: dict[str, Any], key: str) -> dict[str, Any]:
    found: list[dict[str, Any]] = [f for f in w["features"] if f["key"] == key]
    (one,) = found
    return one


def feat(state: State, key: str) -> Feature:
    return state.features[FeatureId(entity(key))]


# --- Rule 1: piece kinds ------------------------------------------------------------


def test_the_toy_world_declares_its_piece_kinds() -> None:
    state = toy_state()
    assert state.kinds is not None
    assert list(state.kinds.pieces) == ["levy", "galley", "kite", "herald"]
    levy, galley, kite, herald = state.kinds.pieces.values()
    assert (levy.name, levy.domain, levy.days_per_step) == (
        "Levy",
        Domain.LAND,
        {"hills": 7, "plain": 5},
    )
    assert galley.domain is Domain.SEA
    assert (galley.max_strength, galley.fuel_per_step, galley.carries) == (3, 1, ("levy",))
    assert (galley.detect, galley.conceal) == (20, 10)
    assert (kite.domain, kite.range_steps, kite.detect) == (Domain.AIR, 2, 60)
    assert herald.domain is Domain.ENVOY


def test_a_kind_left_unsaid_takes_the_defaults() -> None:
    state = toy_state()
    assert state.kinds is not None
    levy = state.kinds.pieces["levy"]
    assert levy.max_strength == 5
    assert levy.fuel_per_step == 0
    assert levy.range_steps is None
    assert (levy.detect, levy.conceal) == (0, 0)
    assert levy.carries == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("detect", 101),
        ("detect", -1),
        ("conceal", 101),
        ("max_strength", 0),
        ("fuel_per_step", -1),
        ("domain", "space"),
    ],
)
def test_a_kind_out_of_bounds_does_not_load(tmp_path: Path, field: str, value: Any) -> None:
    def change(w: dict[str, Any]) -> None:
        piece_kind(w, "levy")[field] = value

    with pytest.raises(ValidationError, match=rf"piece_kinds\.0\.{field}\n"):
        variant(tmp_path, change)


def test_a_step_takes_at_least_a_day(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        piece_kind(w, "levy")["days_per_step"]["plain"] = 0

    with pytest.raises(ValidationError, match=r"piece_kinds\.0\.days_per_step\.plain\n"):
        variant(tmp_path, change)


def test_range_steps_belongs_to_air_and_air_needs_it(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        piece_kind(w, "levy")["range_steps"] = 2
        del piece_kind(w, "kite")["range_steps"]

    problems = refused(variant(tmp_path, change))
    assert "piece kind levy: only an air kind has range_steps" in problems
    assert "piece kind kite: an air kind needs range_steps" in problems


def test_a_kind_carries_only_kinds_the_world_names(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        piece_kind(w, "galley")["carries"] = ["levy", "cannon"]

    assert refused(variant(tmp_path, change)) == ("piece kind galley: carries unknown kind cannon",)


def test_a_kind_key_is_named_once(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        w["piece_kinds"].append(dict(piece_kind(w, "levy"), name="Second Levy"))

    assert "piece kind levy: duplicate key" in refused(variant(tmp_path, change))


def test_piece_kinds_need_a_map(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        without_board(w)
        w["piece_kinds"] = raw_toy()["piece_kinds"]

    assert refused(variant(tmp_path, change)) == (
        "piece_kinds: a world with piece kinds needs a map",
    )


def test_only_a_realism_world_names_kinds_and_resources(tmp_path: Path) -> None:
    w = yaml.safe_load(SALT_STRAIT.read_text())
    w["piece_kinds"] = [{"key": "levy", "name": "Levy", "domain": "land", "days_per_step": {}}]
    w["resources"] = [{"key": "grain", "name": "Grain", "unit": "tons", "role": "output"}]
    problems = refused(written(tmp_path, w))
    assert "piece_kinds: only a realism world has piece_kinds" in problems
    assert "resources: only a realism world has resources" in problems


# --- Rule 2: resources ---------------------------------------------------------------


def test_the_toy_world_declares_its_resources_by_role() -> None:
    state = toy_state()
    assert state.kinds is not None
    assert [(r.key, r.name, r.unit, r.role) for r in state.kinds.resources.values()] == [
        ("grain", "Grain", "tons", Role.OUTPUT),
        ("iron", "Iron", "tons", Role.OUTPUT),
        ("levies", "Levies", "men", Role.MANPOWER),
        ("pitch", "Pitch", "barrels", Role.FUEL),
    ]


def test_several_resources_share_a_role_and_a_role_may_have_none() -> None:
    state = toy_state()
    assert [r.key for r in kinds.with_role(state, Role.OUTPUT)] == ["grain", "iron"]
    assert [r.key for r in kinds.with_role(state, Role.FUEL)] == ["pitch"]
    assert kinds.with_role(state, Role.SUPPLY) == ()
    assert kinds.with_role(state, Role.PRESTIGE) == ()


def test_a_world_with_no_resources_has_none_of_any_role() -> None:
    _, state = created(cmp.load_world(cmp.world_path(POINTS)))
    assert state.kinds is None
    for role in Role:
        assert kinds.with_role(state, role) == ()


def test_a_resource_role_outside_the_five_does_not_load(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        w["resources"][0]["role"] = "gold"

    with pytest.raises(ValidationError, match=r"resources\.0\.role\n"):
        variant(tmp_path, change)


def test_a_resource_key_is_named_once(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        w["resources"].append(dict(w["resources"][0]))

    assert "resource grain: duplicate key" in refused(variant(tmp_path, change))


def test_a_yield_names_a_resource_the_world_has(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        w["territories"][0]["yields"] = {"grain": 1, "gold": 3}

    assert refused(variant(tmp_path, change)) == (
        "territory norra_hills: yields unknown resource gold",
    )


# --- Rule 3: terrain ---------------------------------------------------------------


def test_terrain_carries_its_defence() -> None:
    state = toy_state()
    assert state.map is not None
    assert [(t.key, t.kind, t.defence) for t in state.map.terrain] == [
        ("hills", TerrainKind.LAND, 1),
        ("plain", TerrainKind.LAND, 0),
        ("shallows", TerrainKind.SEA, 0),
        ("deep", TerrainKind.SEA, 0),
    ]


@pytest.mark.parametrize("value", [-1, 3])
def test_a_defence_outside_nought_to_two_does_not_load(tmp_path: Path, value: int) -> None:
    def change(w: dict[str, Any]) -> None:
        w["terrain"][0]["defence"] = value

    with pytest.raises(ValidationError, match=r"terrain\.0\.defence\n +Input should be"):
        variant(tmp_path, change)


def test_terrain_with_no_defence_dumps_as_before() -> None:
    # A board declared before defence existed hashes byte for byte as it did.
    assert Terrain(key="plain", kind=TerrainKind.LAND).model_dump() == {
        "key": "plain",
        "kind": TerrainKind.LAND,
    }
    assert "defence" in Terrain(key="hills", kind=TerrainKind.LAND, defence=2).model_dump()


# --- Rule 4: compile refuses what cannot be played -----------------------------------


def test_a_kind_missing_a_terrain_of_its_domain_is_refused(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        del piece_kind(w, "levy")["days_per_step"]["hills"]
        del piece_kind(w, "galley")["days_per_step"]["deep"]
        del piece_kind(w, "kite")["days_per_step"]["shallows"]
        del piece_kind(w, "herald")["days_per_step"]["plain"]

    assert set(refused(variant(tmp_path, change))) == {
        "piece kind levy: no days_per_step for hills",
        "piece kind galley: no days_per_step for deep",
        "piece kind kite: no days_per_step for shallows",
        "piece kind herald: no days_per_step for plain",
    }


def test_a_kind_stepping_on_terrain_it_cannot_enter_is_refused(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        piece_kind(w, "levy")["days_per_step"]["shallows"] = 9
        piece_kind(w, "galley")["days_per_step"]["swamp"] = 9

    assert set(refused(variant(tmp_path, change))) == {
        "piece kind levy: shallows is sea terrain, where a land piece cannot step",
        "piece kind galley: unknown terrain swamp",
    }


def test_a_land_piece_in_a_sea_zone_is_refused(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        feature(w, "norra_levy")["places"] = ["gulf_roads"]

    assert refused(variant(tmp_path, change)) == (
        "feature norra_levy: a land piece cannot stand in the_gulf",
    )


def test_a_sea_piece_on_land_is_refused(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        feature(w, "sudland_galleys")["places"] = ["sudby"]

    assert refused(variant(tmp_path, change)) == (
        "feature sudland_galleys: a sea piece cannot stand in sudland_coast",
    )


def test_a_leg_into_an_area_the_piece_cannot_stand_in_is_refused(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        feature(w, "sudland_levy")["legs"] = [{"since": "1900-05-01", "places": ["gulf_roads"]}]

    assert refused(variant(tmp_path, change)) == (
        "feature sudland_levy leg 1: a land piece cannot stand in the_gulf",
    )


def test_air_and_envoy_pieces_stand_on_land_or_sea(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        feature(w, "norra_kites")["places"] = ["gulf_roads"]
        feature(w, "norra_herald")["places"] = ["gulf_roads"]

    _, state = created(variant(tmp_path, change))
    assert feat(state, "norra_kites").places == (entity("gulf_roads"),)
    assert feat(state, "norra_herald").places == (entity("gulf_roads"),)


def test_what_stands_where() -> None:
    land, sea = TerrainKind.LAND, TerrainKind.SEA
    assert [kinds.stands_on(d, land) for d in Domain] == [True, False, True, True]
    assert [kinds.stands_on(d, sea) for d in Domain] == [False, True, True, True]


# --- Rule 5: a force is a piece of the world's kind ---------------------------------


def test_a_force_carries_the_worlds_kind_key() -> None:
    state = toy_state()
    levy = feat(state, "norra_levy")
    assert levy.kind is FeatureKind.PIECE
    assert levy.piece == "levy"
    assert feat(state, "sudland_galleys").piece == "galley"


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        ({"piece": "cannon"}, "feature norra_levy: unknown piece kind cannon"),
        ({"piece": None}, "feature norra_levy: a piece names its kind"),
        ({"kind": "front"}, "feature norra_levy: only a piece names a piece kind"),
        (
            {"kind": "army", "piece": None},
            "feature norra_levy: this world's forces are pieces of its own kinds",
        ),
        ({"side": None}, "feature norra_levy: a piece belongs to a side"),
    ],
)
def test_a_piece_names_a_kind_the_world_has(
    tmp_path: Path, edit: dict[str, Any], problem: str
) -> None:
    def change(w: dict[str, Any]) -> None:
        f = feature(w, "norra_levy")
        for key, value in edit.items():
            if value is None:
                f.pop(key, None)
            else:
                f[key] = value

    assert problem in refused(variant(tmp_path, change))


def test_a_piece_in_a_world_with_no_kinds_is_refused(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        del w["piece_kinds"]
        w["features"] = [feature(w, "norra_levy")]

    assert refused(variant(tmp_path, change)) == (
        "feature norra_levy: a piece needs the world's piece_kinds",
    )


def test_a_world_with_no_kinds_keeps_the_five_feature_kinds() -> None:
    _, state = created(cmp.load_world(cmp.world_path(POINTS)))
    found = {f.kind for f in state.features.values()}
    assert FeatureKind.PIECE not in found
    assert {FeatureKind.FLEET, FeatureKind.ARMY} <= found
    assert all(f.piece is None for f in state.features.values())


def test_the_piece_field_goes_with_the_piece_kind() -> None:
    base: dict[str, Any] = {
        "feature_id": FeatureId("f"),
        "name": "x",
        "places": (entity("norrhavn"),),
        "as_of": "1900-04-02",
    }
    Feature(**base, kind=FeatureKind.PIECE, piece="levy")
    with pytest.raises(ValidationError):
        Feature(**base, kind=FeatureKind.PIECE)
    with pytest.raises(ValidationError):
        Feature(**base, kind=FeatureKind.ARMY, piece="levy")
    with pytest.raises(ValidationError):
        Feature(
            **dict(base, places=(entity("norrhavn"), entity("sudby"))),
            kind=FeatureKind.PIECE,
            piece="levy",
        )


def test_a_feature_with_no_piece_dumps_as_before() -> None:
    army = Feature(
        feature_id=FeatureId("f"),
        kind=FeatureKind.ARMY,
        name="x",
        places=(entity("norrhavn"),),
        as_of="1900-04-02",
    )
    assert "piece" not in army.model_dump()


def _then(events: list[ev.Event], payload: ev.Payload) -> list[ev.Event]:
    last = events[-1]
    return [
        *events,
        last.model_copy(
            update={
                "seq": last.seq + 1,
                "event_id": derived_id(CAMPAIGN, "event", str(last.seq + 1)),
                "payload": payload,
            }
        ),
    ]


def test_the_fold_refuses_a_piece_of_a_kind_it_was_not_told() -> None:
    events, state = created(cmp.load_world(TOY))
    levy = feat(state, "norra_levy")
    with pytest.raises(FoldError, match="unknown piece kind cannon"):
        replay(_then(events, ev.FeatureSet(feature=levy.model_copy(update={"piece": "cannon"}))))


def test_the_fold_refuses_a_piece_that_changes_its_kind() -> None:
    events, state = created(cmp.load_world(TOY))
    levy = feat(state, "norra_levy")
    with pytest.raises(FoldError, match="cannot go back or change kind"):
        replay(_then(events, ev.FeatureSet(feature=levy.model_copy(update={"piece": "galley"}))))


# --- Rule 6: kinds_declared ---------------------------------------------------------


def test_compile_declares_the_kinds_once_before_any_feature() -> None:
    events, state = created(cmp.load_world(TOY))
    kinds_at = [i for i, e in enumerate(events) if isinstance(e.payload, ev.KindsDeclared)]
    features_at = [i for i, e in enumerate(events) if isinstance(e.payload, ev.FeatureSet)]
    assert len(kinds_at) == 1
    assert features_at and kinds_at[0] < features_at[0]
    declared = events[kinds_at[0]]
    assert declared.kind == "kinds_declared"
    assert declared.scope == PUBLIC
    assert isinstance(declared.payload, ev.KindsDeclared)
    assert [k.key for k in declared.payload.pieces] == list(state.kinds.pieces)  # type: ignore[union-attr]
    assert [r.key for r in declared.payload.resources] == list(state.kinds.resources)  # type: ignore[union-attr]


def test_a_world_with_no_kinds_declares_none() -> None:
    events, state = created(cmp.load_world(cmp.world_path(POINTS)))
    assert not [e for e in events if isinstance(e.payload, ev.KindsDeclared)]
    assert state.kinds is None
    assert '"kinds"' not in state.model_dump_json()


def test_a_world_with_resources_alone_declares_them(tmp_path: Path) -> None:
    def change(w: dict[str, Any]) -> None:
        del w["piece_kinds"]
        w["features"] = []

    _, state = created(variant(tmp_path, change))
    assert state.kinds is not None
    assert state.kinds.pieces == {}
    assert list(state.kinds.resources) == ["grain", "iron", "levies", "pitch"]


def test_the_kinds_are_declared_once() -> None:
    events, _ = created(cmp.load_world(TOY))
    (declared,) = [e.payload for e in events if isinstance(e.payload, ev.KindsDeclared)]
    with pytest.raises(FoldError, match="declared once"):
        replay(_then(events, declared))


def test_the_kinds_are_the_same_in_every_view() -> None:
    events, state = created(cmp.load_world(TOY))
    state = claim(events, "ilse", "tomas")
    assert state.kinds is not None
    for seat in state.seats:
        assert project(state, seat).kinds == state.kinds


# --- Rule 7: domain and is_force are how a rule asks --------------------------------


TOY_ANSWERS = {
    "norra_levy": (Domain.LAND, True),
    "sudland_levy": (Domain.LAND, True),
    "sudland_galleys": (Domain.SEA, True),
    "norra_kites": (Domain.AIR, True),
    "norra_herald": (Domain.ENVOY, False),
}


def answers(state: State) -> dict[str, tuple[Domain | None, bool]]:
    return {
        key: (kinds.domain(state, feat(state, key)), kinds.is_force(state, feat(state, key)))
        for key in TOY_ANSWERS
    }


def test_a_rule_asks_what_a_piece_is_through_its_domain() -> None:
    assert answers(toy_state()) == TOY_ANSWERS


def test_the_five_feature_kinds_answer_by_their_kind() -> None:
    _, state = created(cmp.load_world(cmp.world_path(POINTS)))
    seen: dict[FeatureKind, tuple[Domain | None, bool]] = {}
    for f in state.features.values():
        seen[f.kind] = (kinds.domain(state, f), kinds.is_force(state, f))
    assert seen[FeatureKind.ARMY] == (Domain.LAND, True)
    assert seen[FeatureKind.FLEET] == (Domain.SEA, True)
    if FeatureKind.AIR in seen:
        assert seen[FeatureKind.AIR] == (Domain.AIR, True)
    for line in (FeatureKind.FRONT, FeatureKind.ROUTE):
        if line in seen:
            assert seen[line] == (None, False)


RENAME = {"levy": "army", "galley": "fleet", "kite": "air", "herald": "envoy"}


def renamed(w: dict[str, Any]) -> None:
    """The toy world with its kinds named as the five feature kinds are."""
    for k in w["piece_kinds"]:
        k["key"] = RENAME[k["key"]]
        k["carries"] = [RENAME[c] for c in k.get("carries", [])]
    for f in w["features"]:
        f["piece"] = RENAME[f["piece"]]


def test_army_and_fleet_names_give_the_same_outcomes(tmp_path: Path) -> None:
    _, state = created(variant(tmp_path, renamed))
    assert state.kinds is not None
    assert list(state.kinds.pieces) == ["army", "fleet", "air", "envoy"]
    assert answers(state) == answers(toy_state()) == TOY_ANSWERS


@pytest.mark.parametrize(
    "bad",
    [
        lambda w: feature(w, "norra_levy").update(places=["gulf_roads"]),
        lambda w: feature(w, "sudland_galleys").update(places=["sudby"]),
        lambda w: w["piece_kinds"][0]["days_per_step"].pop("hills"),
        lambda w: w["piece_kinds"][1]["days_per_step"].pop("deep"),
    ],
)
def test_army_and_fleet_names_are_refused_alike(tmp_path: Path, bad: Any) -> None:
    def named(w: dict[str, Any]) -> None:
        renamed(w)
        bad(w)

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    toy = refused(variant(tmp_path / "a", bad))
    other = refused(variant(tmp_path / "b", named))
    back = {v: k for k, v in RENAME.items()}
    assert toy == tuple(
        re.sub(r"piece kind (\w+)", lambda m: f"piece kind {back.get(m[1], m[1])}", p)
        for p in other
    )


def test_no_rule_reads_a_pieces_kind_key_but_kinds() -> None:
    # Only the model, the compiler, the fold and ``kinds`` touch ``Feature.piece``.
    allowed = {
        SRC / "core" / "realism" / "kinds.py",
        SRC / "core" / "realism" / "geography.py",
        SRC / "core" / "world_compile.py",
        SRC / "core" / "fold.py",
    }
    reads = re.compile(r"\.piece\b(?!\s*\()")
    found = [
        f"{path.relative_to(SRC)}:{n}"
        for path in sorted(SRC.rglob("*.py"))
        if path not in allowed
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if reads.search(line)
    ]
    assert found == []


def test_the_drafter_is_offered_no_kinds_resources_or_pieces() -> None:
    # Kinds are written by hand: a model drafting a world never sees them, so no
    # recorded drafting request changes.
    schema = WorldFile.model_json_schema()
    assert "piece_kinds" not in schema["properties"]
    assert "resources" not in schema["properties"]
    assert "piece" not in schema["$defs"]["FeatureDecl"]["properties"]
    assert schema["$defs"]["FeatureKind"]["enum"] == ["fleet", "army", "air", "front", "route"]
    assert "defence" not in json.dumps(schema)


def test_stored_games_replay_with_no_kinds() -> None:
    # A game made before this item holds no kinds_declared and no piece: the dump of
    # its state names neither.
    events = compile_world(cmp.load_world(cmp.world_path(POINTS)), CAMPAIGN, cmp.versions())
    text = json.dumps([e.model_dump(mode="json") for e in events])
    assert "kinds_declared" not in text
    assert '"piece"' not in text
    assert raw_toy()["piece_kinds"]
