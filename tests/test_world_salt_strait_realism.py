"""Salt Strait as a second world: a flat hand-written map and a playable cast (SSM), and
at parity with 1941: yields, a trade line, groups, a pact, intelligence and aims (SSG).

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
from revisionist.core.ids import (
    CampaignId,
    EntityId,
    EventId,
    FeatureId,
    OrderId,
    SeatId,
    derived_id,
)
from revisionist.core.realism import economy, groups
from revisionist.core.realism.kinds import Domain, Role
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import apply_changes, intel, movement
from revisionist.core.realism.territory import StepCause
from revisionist.core.state import MODEL_READ_RULES, Rule, State
from revisionist.core.visibility import PUBLIC
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import odds, realism_tick, session_zero
from revisionist.engine.realism_tick import draft_order, run_realism_tick
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import battles_api

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "worlds" / "salt-strait-realism.yaml"
MAP = ROOT / "worlds" / "maps" / "salt-strait-realism.json"
PROOF = ROOT / "worlds" / "maps" / "proof" / "salt-strait-realism.svg"
CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
START = date(1900, 4, 2)
POLITIES = {"varda": "Varda", "ostrel": "Ostrel", "kesh": "Kesh", "lune": "Lune Isles"}
PLAYED = {"varda": "oren_vale", "ostrel": "general_aske"}
RUN_BY_CODE = {"kesh": "abbess_ren", "lune": "admiral_quell"}
RULES = {
    Rule.TERRITORIES,
    Rule.HOLDERS,
    Rule.ECONOMY,
    Rule.SUPPLY,
    Rule.FUEL,
    Rule.AID,
    Rule.BATTLES,
    Rule.REPORTS,
    Rule.AGREEMENTS,
    Rule.CONFERENCE,
    Rule.GROUPS,
    Rule.CONTESTS,
    Rule.AIMS,
}
"""Every rule name the engine had when Salt Strait reached parity (SSG), less the three read
by a live model, which stay off in a shipped world."""


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
    assert set(w.rules) == RULES
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


def test_the_world_names_its_own_piece_kinds_and_one_flies() -> None:
    kinds = {k.key: k.domain.value for k in world().piece_kinds}
    assert kinds == {
        "levy": "land",
        "galley": "sea",
        "rider": "envoy",
        "balloon_corps": "air",
    }


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


# --- At parity with 1941 (SSG) -------------------------------------------------------------


def compiled() -> State:
    return replay(compile_world(world(), CAMPAIGN, cmp.versions()))


def test_the_rules_are_every_rule_but_the_three_a_model_reads() -> None:
    rules = set(world().rules)
    assert rules == RULES
    assert RULES <= set(Rule)
    assert not rules & MODEL_READ_RULES
    autumn = cmp.load_world(ROOT / "worlds" / "autumn-1941.yaml")
    assert set(autumn.rules) - {Rule.COMMAND, Rule.LOCKS, Rule.OWN_AIM} <= rules
    assert compiled().rules == frozenset(RULES)


def test_every_territory_yields_each_resource_and_every_nation_has_a_figure() -> None:
    w = world()
    resources = {r.key for r in w.resources}
    for t in w.territories:
        assert set(t.yields) == resources, t.key
        assert sum(t.yields.values()) > 0, t.key
    state = load_state(opened(), CAMPAIGN)
    figures = {key: economy.figure(state, entity(key)) for key in POLITIES}
    assert all(f > 0 for f in figures.values()), figures
    assert max(figures.values()) == 100


def test_one_trade_line_runs_between_two_nations() -> None:
    w = world()
    (line,) = w.trade_lines
    roles = {r.key: r.role for r in w.resources}
    assert roles[line.resource] in (Role.OUTPUT, Role.MANPOWER, Role.FUEL)
    assert {line.exporter, line.importer} <= set(POLITIES)
    assert line.exporter != line.importer and not line.cut
    assert set(compiled().economy.lines) == {line.key}


def test_each_polity_has_groups_at_home_and_themes() -> None:
    w = world()
    declared = {d.nation: d for d in w.groups}
    assert set(declared) == set(POLITIES)
    for nation, d in declared.items():
        assert len(d.groups) >= 2, nation
        assert d.themes, nation
    state = compiled()
    assert set(state.groups.declared) == {entity(k) for k in POLITIES}
    assert set(state.groups.themes) == {entity(k) for k in POLITIES}
    opened_state = load_state(opened(), CAMPAIGN)
    for key in POLITIES:
        assert groups.manpower_factor(opened_state, entity(key)) == 1.0, key
        assert groups.output_factor(opened_state, entity(key)) == 1.0, key


def test_each_polity_has_its_own_intelligence() -> None:
    w = world()
    people = {d.key: d.parent for d in w.entities if d.kind.value == "person"}
    declared = {d.nation: d for d in w.intelligence}
    assert set(declared) == set(POLITIES)
    for nation, d in declared.items():
        assert d.sources, nation
        assert {people[s.person] for s in d.sources} == {nation}
    assert any(d.codebreaking for d in declared.values())
    assert any(d.agents for d in declared.values())
    assert set(compiled().intelligence) == {entity(k) for k in POLITIES}


@pytest.mark.parametrize("person", list(PLAYED.values()))
def test_each_playable_leader_has_every_intelligence_form(person: str) -> None:
    state = compiled()
    card = state.cards[entity(person)]
    forms = {intel.form_of(lv): lv for lv in card.levers if intel.form_of(lv) is not None}
    assert set(forms) == set(intel.Form)
    w = world()
    (decl,) = [c for c in w.cards if c.person == person]
    side = decl.principals[0]
    own = {f.key: f for f in w.features if f.side == side}
    kinds = {k.key: k.domain for k in w.piece_kinds}
    for lv in decl.levers:
        if lv.resolver != "intel":
            continue
        assert lv.pipeline == decl.pipelines[0]
        params = {p.name: p.choices for p in lv.params}
        for piece in params.get("piece", ()):
            assert piece in own, (lv.name, piece)
        if params["intel"] == ("recon",):
            assert {kinds[own[p].piece or ""] for p in params["piece"]} == {Domain.AIR}
        if params["intel"] == ("patrol",):
            assert {kinds[own[p].piece or ""] for p in params["piece"]} == {Domain.SEA}


def test_one_pact_is_in_force_at_the_start() -> None:
    (pact,) = world().pacts
    assert set(pact.parties) <= set(POLITIES) and len(pact.parties) >= 2
    assert any(c.type.value != "unchecked" for c in pact.clauses)
    made = compiled().agreements.made
    assert len(made) == 1
    (agreement,) = made.values()
    assert set(agreement.parties) == {entity(k) for k in pact.parties}


def test_a_conference_is_scheduled() -> None:
    w = world()
    (conf,) = w.conferences
    assert set(conf.invited) == set(POLITIES)
    assert w.start_date is not None and conf.opens > w.start_date
    assert len(compiled().conferences.held) == 1


def test_a_contest_moves_on_play_between_the_two_playable_nations() -> None:
    (contest,) = world().contests
    assert set(PLAYED) <= set(contest.sides)
    assert contest.moves
    (k,) = compiled().contests.values()
    assert len(k.moves) == len(contest.moves)


@pytest.mark.parametrize("person", list(PLAYED.values()))
def test_each_playable_leader_has_three_aims_with_conditions(person: str) -> None:
    (card,) = [c for c in world().cards if c.person == person]
    assert len(card.aims) == 3
    assert sorted(r.aim for r in card.aim_rules) == [1, 2, 3]
    assert sum(r.replaceable for r in card.aim_rules) == 1
    assert all(r.rule and r.deadline is not None for r in card.aim_rules)
    rules = compiled().cards[entity(person)].aim_rules
    assert len(rules) == 3 and all(r is not None for r in rules)


def test_a_game_with_every_rule_on_opens_and_runs_a_week() -> None:
    store = opened()
    for _ in range(7):
        run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    assert state.in_world_date is not None and state.in_world_date > START


# --- The leaders command their own armies ------------------------------------------------

FORCES = {
    "oren_vale": ["varda_levy", "varda_galleys", "varda_balloons"],
    "general_aske": ["ostrel_levy", "ostrel_galleys", "ostrel_balloons"],
}


def _commands(state: State, person: str, force: str) -> bool:
    from revisionist.core.realism import war_rules

    fid = FeatureId(ids()[force])
    return any(s == seat(person) for s, _ in war_rules.commanders(state, fid))


@pytest.mark.parametrize(
    ("person", "other"), [("oren_vale", "general_aske"), ("general_aske", "oren_vale")]
)
def test_each_leader_commands_his_nations_forces_and_not_the_others(
    person: str, other: str
) -> None:
    state = load_state(opened(), CAMPAIGN)
    assert all(_commands(state, person, f) for f in FORCES[person])
    assert not any(_commands(state, person, f) for f in FORCES[other])


@pytest.mark.parametrize(
    ("person", "other"), [("oren_vale", "general_aske"), ("general_aske", "oren_vale")]
)
def test_a_leader_files_a_standing_order_for_his_force_and_is_refused_the_others(
    person: str, other: str
) -> None:
    state = load_state(opened(), CAMPAIGN)
    asks, _ = battles_api.contingency_asks(
        state, seat(person), {"force": FORCES[person][0], "kind": "hold_fast"}
    )
    assert len(asks) == 1
    with pytest.raises(ValueError, match="not yours to order"):
        battles_api.contingency_asks(
            state, seat(person), {"force": FORCES[other][0], "kind": "hold_fast"}
        )


@pytest.mark.parametrize(
    ("person", "other"), [("oren_vale", "general_aske"), ("general_aske", "oren_vale")]
)
def test_the_odds_desk_takes_a_leaders_own_force_and_refuses_the_others(
    person: str, other: str
) -> None:
    state = load_state(opened(), CAMPAIGN)
    assert odds._piece(state, seat(person), FORCES[person][0]).name
    with pytest.raises(ValueError, match="not yours to order"):
        odds._piece(state, seat(person), FORCES[other][0])
