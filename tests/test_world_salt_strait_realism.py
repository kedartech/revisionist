"""Salt Strait as a second world: a flat hand-written map and a playable cast (SSM).

``worlds/salt-strait-realism.yaml`` plays the four polities of Salt Strait under the
current ruleset, on a flat map written by hand straight into the committed format
(``worlds/maps/salt-strait-realism.json``): no geometry tool, no recipe, no border data.
It names its own terrain, resources and piece kinds, none of them a key of the 1941
world. Two leaders are playable and two are run by code. No model is called: the game
runs with no prose writer and no estimator.
"""

import importlib.util
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, EventId, OrderId, SeatId, derived_id
from revisionist.core.realism.kinds import Role
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import apply_changes, movement
from revisionist.core.realism.territory import StepCause
from revisionist.core.state import Rule, State
from revisionist.core.visibility import PUBLIC
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.realism_tick import draft_order, run_realism_tick
from revisionist.engine.store import MemoryStore, load_state

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "worlds" / "salt-strait-realism.yaml"
MAP = ROOT / "worlds" / "maps" / "salt-strait-realism.json"
PROOF = ROOT / "worlds" / "maps" / "proof" / "salt-strait-realism.svg"
CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
START = date(1900, 4, 2)
POLITIES = {"varda": "Varda", "ostrel": "Ostrel", "kesh": "Kesh", "lune": "Lune Isles"}
PLAYED = {"varda": "oren_vale", "ostrel": "general_aske"}
RUN_BY_CODE = {"kesh": "abbess_ren", "lune": "admiral_quell"}


def _map_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_check", ROOT / "scripts" / "map_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def world() -> WorldFile:
    return cmp.load_world(WORLD)


def ids() -> dict[str, str]:
    return resolve_keys(world(), CAMPAIGN)


def entity(key: str) -> EntityId:
    return EntityId(ids()[key])


def seat(person: str) -> SeatId:
    return SeatId(derived_id(CAMPAIGN, "seat", entity(person)))


def keys(node: Any) -> Iterator[str]:
    """Every key a parsed world file names anywhere: ``key`` values, and the terrain and
    piece kinds its areas and pieces name (the 1941 map names terrain it does not declare)."""
    if isinstance(node, dict):
        for field in ("key", "terrain", "piece"):
            if isinstance(node.get(field), str):
                yield node[field]
        for value in node.values():
            yield from keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from keys(value)


# --- The world file and its map -------------------------------------------------------


def test_the_world_compiles_under_the_current_ruleset() -> None:
    w = world()
    assert w.ruleset == "realism"
    assert w.start_date == START
    assert w.rules == (Rule.TERRITORIES,)
    events = compile_world(w, CAMPAIGN, cmp.versions())
    state = replay(events)
    names = {e.name for e in state.entities.values()}
    assert set(POLITIES.values()) <= names


def test_the_strict_map_check_passes() -> None:
    report = _map_check().check_world(WORLD)
    assert [str(p) for p in report.problems] == []


def test_the_map_is_flat_and_written_by_hand() -> None:
    raw = yaml.safe_load(WORLD.read_text())
    assert raw["map"]["coords"] == "flat"
    assert not (ROOT / "worlds" / "maps" / "src" / "salt-strait-realism").exists()
    assert "Built by" not in WORLD.read_text()
    assert PROOF.is_file()


def test_the_board_has_two_regions_eight_territories_and_three_sea_zones() -> None:
    w = world()
    assert len(w.regions) == 2
    assert len(w.territories) == 8
    assert len(w.sea_zones) == 3
    regions = {r.key for r in w.regions}
    assert {t.region for t in w.territories} | {z.region for z in w.sea_zones} == regions
    holders = {t.holder for t in w.territories}
    assert holders == set(POLITIES)


def test_harrow_pass_is_mountain_and_the_strait_is_a_sea_zone() -> None:
    w = world()
    terrain = {t.key: t for t in w.terrain}
    (harrow,) = [t for t in w.territories if t.key == "harrow_pass"]
    assert harrow.name == "Harrow Pass"
    assert terrain[harrow.terrain].kind == "land"
    assert terrain[harrow.terrain].defence == 2
    assert max(t.defence for t in terrain.values()) == 2
    (strait,) = [z for z in w.sea_zones if z.key == "the_strait"]
    assert strait.name == "The Salt Strait"
    assert terrain[strait.terrain].kind == "sea"


def test_the_adjacency_list_matches_what_the_checker_derives() -> None:
    mc = _map_check()
    raw, _ = mc.load(MAP)
    derived = {frozenset(p) for p in mc.adjacency(raw)}
    listed = {frozenset(p) for p in yaml.safe_load(WORLD.read_text())["adjacency"]}
    assert listed == derived
    assert frozenset({"ostrel_heartland", "harrow_pass"}) in listed
    assert frozenset({"harrow_pass", "varda_saltworks"}) in listed


# --- Its own terrain, resources and piece kinds ----------------------------------------


def test_the_world_names_its_own_resources_one_per_role() -> None:
    by_role = {r.role: r.key for r in world().resources}
    assert by_role == {
        Role.OUTPUT: "salt",
        Role.MANPOWER: "levies",
        Role.FUEL: "fodder",
        Role.SUPPLY: "roads",
        Role.PRESTIGE: "renown",
    }


def test_the_world_names_its_own_piece_kinds_and_none_flies() -> None:
    kinds = {k.key: k.domain.value for k in world().piece_kinds}
    assert kinds == {"levy": "land", "galley": "sea", "rider": "envoy"}


def test_no_key_is_borrowed_from_the_1941_world() -> None:
    ours = set(keys(yaml.safe_load(WORLD.read_text())))
    theirs: set[str] = set()
    for path in sorted(p for p in (ROOT / "worlds").rglob("*.yaml") if "1941" in str(p)):
        theirs |= set(keys(yaml.safe_load(path.read_text())))
    assert {"plain", "forest", "moscow"} <= theirs
    assert sorted(ours & theirs) == []


# --- The cast ---------------------------------------------------------------------------


def test_two_leaders_are_playable_and_two_are_run_by_code() -> None:
    w = world()
    cards = {c.person: c for c in w.cards}
    assert {p for p, c in cards.items() if c.playable} == set(PLAYED.values())
    assert set(RUN_BY_CODE.values()) <= set(cards)
    assert not any(cards[p].playable for p in RUN_BY_CODE.values())
    assert {r.entity for r in w.roster} == set(PLAYED.values())
    for polity, person in {**PLAYED, **RUN_BY_CODE}.items():
        assert cards[person].principals == (polity,)


@pytest.mark.parametrize("person", [*PLAYED.values(), *RUN_BY_CODE.values()])
def test_each_leader_has_one_pipeline_one_feed_and_a_move_form(person: str) -> None:
    w = world()
    (card,) = [c for c in w.cards if c.person == person]
    assert len(card.pipelines) == 1 and len(card.feeds) == 1
    (form,) = [lv for lv in card.levers if lv.resolver == "movement"]
    assert form.pipeline == card.pipelines[0]
    side = card.principals[0]
    own = {f.key for f in w.features if f.side == side}
    choices = {p.name: set(p.choices) for p in form.params}
    assert choices["force"] == own and own
    areas = {t.key for t in w.territories} | {z.key for z in w.sea_zones}
    assert choices["to"] == areas


# --- A game opens, and pieces move --------------------------------------------------------


def opened() -> MemoryStore:
    store = MemoryStore()
    store.append_all(compile_world(world(), CAMPAIGN, cmp.versions()))
    session_zero.claim(store, CAMPAIGN, seat("general_aske"), "General Aske")
    realism_tick.seat_player(store, CAMPAIGN, entity("oren_vale"))
    return store


def test_a_game_opens_with_both_playable_leaders_seated() -> None:
    store = opened()
    state = load_state(store, CAMPAIGN)
    assert {state.entities[s.embodies].name for s in state.seats.values()} == {
        "Oren Vale",
        "General Aske",
    }
    run_realism_tick(store, CAMPAIGN)
    assert load_state(store, CAMPAIGN).in_world_date is not None


@pytest.mark.parametrize(
    ("person", "force", "to"),
    [
        ("oren_vale", "varda_galleys", "the_outer_sea"),
        ("general_aske", "ostrel_levy", "harrow_pass"),
    ],
)
def test_each_playable_leader_drafts_a_move_on_the_form(person: str, force: str, to: str) -> None:
    state = load_state(opened(), CAMPAIGN)
    order = draft_order(state, seat(person), "move_force", {"force": force, "to": to})
    assert order.params == {"force": force, "to": to}


def _fold(state: State, payloads: list[ev.Payload]) -> State:
    batch = [
        ev.Event(
            event_id=EventId(derived_id(CAMPAIGN, "ssm-test", state.last_seq + 1 + n)),
            campaign_id=CAMPAIGN,
            seq=state.last_seq + 1 + n,
            tick=0,
            scope=PUBLIC,
            payload=p,
            versions=cmp.versions(),
        )
        for n, p in enumerate(payloads)
    ]
    return replay(batch, initial=state) if batch else state


def _send(state: State, by: str, force: str, to: str) -> State:
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "ssm-order", by, force)),
        issuer=seat(by),
        lever="move_force",
        pipeline=state.cards[entity(by)].pipelines[0],
        params={"force": force, "to": to},
        status=OrderStatus.ENACTED,
        filed=START,
    )
    return _fold(state, list(apply_changes(state, movement.order_changes(state, order))))


def _walk(state: State, days: int) -> list[ev.PieceStepped]:
    stepped: list[ev.PieceStepped] = []
    for n in range(1, days + 1):
        out = movement.walk(state, START + timedelta(days=n))
        stepped += [p for p in out if isinstance(p, ev.PieceStepped)]
        state = _fold(state, list(out))
    return stepped


def _days(kind: str, area: str) -> int:
    w = world()
    terrain = {t.key: t.terrain for t in w.territories} | {z.key: z.terrain for z in w.sea_zones}
    (k,) = [k for k in w.piece_kinds if k.key == kind]
    return k.days_per_step[terrain[area]]


def test_a_galley_moves_two_sea_zones_and_a_levy_one_territory_at_its_kinds_days() -> None:
    state = load_state(opened(), CAMPAIGN)
    state = _send(state, "oren_vale", "varda_galleys", "the_outer_sea")
    state = _send(state, "general_aske", "ostrel_levy", "harrow_pass")
    strait, outer = _days("galley", "the_strait"), _days("galley", "the_outer_sea")
    mountain = _days("levy", "harrow_pass")
    assert (strait, outer, mountain) == (2, 3, 9)
    assert mountain > _days("levy", "ostrel_heartland")
    moves = {(s.on, s.left, s.entered, s.cause) for s in _walk(state, 20)}
    assert moves == {
        (_on(strait), entity("the_lune_sound"), entity("the_strait"), StepCause.ORDERED),
        (_on(strait + outer), entity("the_strait"), entity("the_outer_sea"), StepCause.ORDERED),
        (_on(mountain), entity("ostrel_heartland"), entity("harrow_pass"), StepCause.ORDERED),
    }


def _on(days: int) -> date:
    return START + timedelta(days=days)
