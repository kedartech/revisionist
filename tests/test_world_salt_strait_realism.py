"""Salt Strait as a second world: a flat hand-written map and a playable cast (SSM), at
parity with 1941: yields, a trade line, groups, a pact, intelligence and aims (SSG), and
keeping parity with the third run's world data: a law of its own and the body that passes
it, a council that decides one question and a person who decides another, aim patterns
for its posts, and a second military card under Varda's head of government (SSO).

``worlds/salt-strait-realism.yaml`` plays the four polities of Salt Strait under the
current ruleset, on a flat map written by hand straight into the committed format
(``worlds/maps/salt-strait-realism.json``): no geometry tool, no recipe, no border data.
It names its own terrain, resources and piece kinds, none of them a key of the 1941
world. Two leaders are playable and two are run by code. No model is called: the game
runs with no prose writer and no estimator.
"""

import importlib.util
import itertools
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from revisionist.core import aim_patterns
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
from revisionist.core.realism import economy, groups, laws, locks
from revisionist.core.realism.kinds import Domain, Role
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import apply_changes, intel, movement, qid, votes
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
TEMPLATE = ROOT / "worlds" / "TEMPLATE.md"
CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
START = date(1900, 4, 2)
POLITIES = {"varda": "Varda", "ostrel": "Ostrel", "kesh": "Kesh", "lune": "Lune Isles"}
PLAYED = {"varda": "oren_vale", "ostrel": "general_aske"}
COMMODORE = "brask"
"""Varda's second playable card: a military card under the First Minister (SSO)."""
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
    Rule.COMMAND,
    Rule.LOCKS,
    Rule.LAWS,
    Rule.ASK_ANSWERS,
    Rule.DECIDERS,
    Rule.OWN_AIM,
}
"""Every rule name the engine had when Salt Strait reached parity (SSG), less the three read
by a live model, which stay off in a shipped world; and the commander's seat, locks, laws,
answers to asks, deciders and the player's own aim (SSO)."""


def _map_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("map_check", ROOT / "scripts" / "map_check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _world_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "world_check", ROOT / "scripts" / "world_check.py"
    )
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


def test_two_leaders_and_a_commodore_are_playable_and_two_are_run_by_code() -> None:
    w = world()
    cards = {c.person: c for c in w.cards}
    playable = {*PLAYED.values(), COMMODORE}
    assert {p for p, c in cards.items() if c.playable} == playable
    assert set(RUN_BY_CODE.values()) <= set(cards)
    assert not any(cards[p].playable for p in RUN_BY_CODE.values())
    assert {r.entity for r in w.roster} == playable
    for polity, person in {**PLAYED, **RUN_BY_CODE}.items():
        assert cards[person].principals == (polity,)


@pytest.mark.parametrize("person", [*PLAYED.values(), *RUN_BY_CODE.values()])
def test_each_leader_has_one_feed_and_a_move_form_through_his_first_pipeline(
    person: str,
) -> None:
    w = world()
    (card,) = [c for c in w.cards if c.person == person]
    assert card.pipelines and len(card.feeds) == 1
    (form,) = [lv for lv in card.levers if lv.name == "move_force"]
    assert form.resolver == "movement"
    assert form.pipeline == card.pipelines[0]
    side = card.principals[0]
    own = {f.key for f in w.features if f.side == side}
    choices = {p.name: set(p.choices) for p in form.params}
    assert choices["force"] == own and own
    areas = {t.key for t in w.territories} | {z.key for z in w.sea_zones}
    assert choices["to"] == areas


# --- A game opens, and pieces move --------------------------------------------------------


def opened(commodore: bool = False) -> MemoryStore:
    store = MemoryStore()
    store.append_all(compile_world(world(), CAMPAIGN, cmp.versions()))
    session_zero.claim(store, CAMPAIGN, seat("general_aske"), "General Aske")
    if commodore:
        session_zero.claim(store, CAMPAIGN, seat(COMMODORE), "Commodore Brask")
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
    assert set(autumn.rules) <= rules
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
        assert lv.pipeline in decl.pipelines
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


# --- Laws, deciders, aim patterns and a second military seat (SSO) -----------------------


def _row(key: str) -> locks.LockRow:
    (row,) = [r for r in compiled().locks if r.key == key]
    return row


def test_varda_declares_a_law_of_its_own_that_no_code_table_knows() -> None:
    w = world()
    (law,) = w.laws
    assert law.nation == "varda"
    tabled = set(votes.HISTORICAL) | set(votes.TALLIES)
    assert law.key not in tabled
    assert law.passed not in {f"{bill}_passed" for bill in tabled}
    subjects = {c.subject for c in law.clauses}
    assert not subjects & {c.subject for m in votes.HISTORICAL.values() for c in m.clauses}
    assert law.passed in {q.key for q in w.quantities}
    (oren,) = [c for c in w.cards if c.person == "oren_vale"]
    (bill,) = [lv for lv in oren.levers if lv.resolver == "votes"]
    assert {p.name: p.choices for p in bill.params}["bill"] == (law.key,)
    (row,) = [r for r in w.locks if r.when is not None and r.when.check == "law_not_in_force"]
    assert row.when is not None and row.when.clause in subjects


def test_the_law_is_in_force_once_its_own_flag_reads_one() -> None:
    state = compiled()
    (law,) = state.laws
    (clause,) = law.clauses
    assert laws.in_force(state, clause.subject) == {}
    flag = state.quantities[qid(state, "salt_convoy_act_passed")]
    passed = _fold(
        state, [ev.QuantitySet(quantity=flag.model_copy(update={"value": 1, "as_of": START}))]
    )
    assert laws.in_force(passed, clause.subject) == {entity("varda"): START}


def test_the_salt_assembly_is_the_body_that_passes_the_law() -> None:
    row = _row("sound_convoy_escort")
    blocs = [g for g in compiled().groups.declared[entity("varda")] if g.chamber is not None]
    assert {g.chamber for g in blocs} == {"salt_assembly"}
    assert row.decider.nation == entity("varda")
    assert row.decider.chambers == ("salt_assembly",)
    assert row.decider.head == entity("oren_vale")


def test_a_council_decides_one_question_and_a_person_another() -> None:
    council, person = _row("outer_sea_sortie"), _row("kesh_quay_call")
    assert council.decider.council is not None
    assert set(council.decider.council.members) == {
        entity("oren_vale"),
        entity("mira"),
        entity("warden_pell"),
    }
    assert council.decider.council.needed == 2
    assert council.decider.council.head == entity("oren_vale")
    assert person.decider.person == entity("abbess_ren")
    assert council.question is not None and person.question is not None
    assert council.question is not person.question
    cards = compiled().cards
    assert all(m in cards for m in council.decider.council.members)


def test_the_commodore_is_a_military_card_under_the_head_of_government() -> None:
    state = compiled()
    card = state.cards[entity(COMMODORE)]
    assert card.path.value == "military"
    chain, who = [], entity(COMMODORE)
    for _ in range(4):
        if state.cards.get(who) is None or not state.cards[who].principals:
            break
        who = state.cards[who].principals[0]
        chain.append(who)
    assert chain[:2] == [entity("mira"), entity("oren_vale")]
    w = world()
    (decl,) = [c for c in w.cards if c.person == COMMODORE]
    assert {f for d in decl.authority for f in d.forces} == {"varda_galleys"}
    assert sum(r.replaceable for r in decl.aim_rules) == 1


def _filed_and_asked(form: dict[str, str]) -> tuple[MemoryStore, OrderId]:
    store = opened(commodore=True)
    run_realism_tick(store, CAMPAIGN)
    order = realism_tick.file_order(store, CAMPAIGN, seat(COMMODORE), "sail", form)
    realism_tick.ask_order(store, CAMPAIGN, seat(COMMODORE), order.order_id)
    return store, order.order_id


def _logged(store: MemoryStore, kind: type[Any], order_id: OrderId) -> list[Any]:
    found = (e.payload for e in store.read(CAMPAIGN))
    return [p for p in found if isinstance(p, kind) and p.order_id == order_id]


def _answered(store: MemoryStore, order_id: OrderId) -> bool:
    """Tick until the ask on ``order_id`` is answered, and a tick past it; its answer."""
    for _ in range(12):
        run_realism_tick(store, CAMPAIGN)
        (answer,) = _logged(store, ev.AskAnswered, order_id) or [None]
        if answer is not None:
            run_realism_tick(store, CAMPAIGN)
            return bool(answer.granted)
    raise AssertionError("the ask was never answered")


@pytest.mark.parametrize(
    ("to", "row", "asked_of"),
    [
        ("the_outer_sea", "outer_sea_sortie", "oren_vale"),
        ("kesh_quay", "kesh_quay_call", "abbess_ren"),
    ],
)
def test_a_sailing_the_world_locks_is_held_asked_and_answered_by_its_decider(
    to: str, row: str, asked_of: str
) -> None:
    store, order_id = _filed_and_asked({"force": "varda_galleys", "to": to})
    state = load_state(store, CAMPAIGN)
    assert state.held[order_id].row == row
    assert state.asked[order_id].to == entity(asked_of)
    granted = _answered(store, order_id)
    landed = [e.end for e in _logged(store, ev.HeldOrderEnded, order_id)]
    assert landed == ([locks.HeldEnd.LANDED] if granted else [])
    assert (order_id in load_state(store, CAMPAIGN).held) is not granted


def test_the_councils_matter_is_before_the_first_minister_and_not_the_marshal() -> None:
    store, order_id = _filed_and_asked({"force": "varda_galleys", "to": "the_outer_sea"})
    state = load_state(store, CAMPAIGN)
    locks.may_choose(state, seat("oren_vale"), order_id)
    with pytest.raises(ValueError, match=locks.NOT_A_MEMBER):
        locks.may_choose(state, seat("general_aske"), order_id)


@pytest.mark.parametrize("person", [*PLAYED.values(), COMMODORE])
def test_each_playable_card_has_aim_patterns_for_its_post(person: str) -> None:
    store = opened(commodore=True)
    state = load_state(store, CAMPAIGN)
    rungs = aim_patterns.ladder(state, seat(person))
    assert rungs
    stands = [r for r in rungs if r.difficulty is not None]
    assert stands, person
    rung = stands[0]
    fills = (
        aim_patterns.fill(state, seat(person), rung.key, dict(zip(names, values, strict=True)))
        for names in [[b.name for b in rung.blanks]]
        for values in itertools.product(*(b.values for b in rung.blanks))
    )
    assert any(isinstance(f, aim_patterns.Filled) for f in fills), rung.key


ABSENT_ON_PURPOSE = {
    "settings.end_date": "the season ends when the contest's countdown runs out",
    "settings.tick_hours": "the rules' own turn and wake suit an invented world",
    "settings": "the table's default limits and tone",
    "notes": "an invented world has no record to dispute",
    "fuel_stocks": "each nation starts with the rules' stock of its fodder income",
    "entities.lift_pool": "no land piece crosses the water",
    "production": "no aid finding is run in the strait",
    "wars": "the season opens at peace; a war is declared in play",
    "groups.groups.abroad": "writing is read by a live model and stays off",
    "cards.successor": "nobody is named to succeed in one season",
    "features.legs": "the season opens on its first day: no force has moved yet",
    "cards.reach": "every person keeps rank 0 and no chain",
    "cards.allies": "nobody stands with or against anyone but by the contest",
    "relationships": "regard starts at 0 between any two",
    "cards.wants": "nobody wants or holds to a topic",
    "mandates": "no mandate is issued",
    "schedule": "an invented world has no history to keep",
    "developments": "no development falls",
    "outlets": "no press: word reaches each audience with no slant",
    "cards.levers.escort_level": "no shipping form: the galleys' watch is a patrol",
    "cards.answers": "Kesh and the Lune Isles do nothing back unless asked",
    "goals": "the older ruleset only",
    "meters": "the older ruleset only",
    "clocks": "the older ruleset only",
    "facts": "the older ruleset only",
    "commitments": "the older ruleset only",
    "groups.groups.prices": "no bloc is offered a price: offers stay off",
    "happenings": "classes stay off: every kind of happening is reported",
    "happenings.felt": "classes stay off: no kind is part felt",
    "places": "no place carries political weight: losing ground moves groups only by territory",
}
"""The questions on main that Salt Strait leaves unanswered, each on purpose, by the first
key of its row in ``worlds/TEMPLATE.md``, with why (SSO rule 4)."""


def test_the_world_check_reports_every_question_built_so_far_answered_or_absent_on_purpose() -> (
    None
):
    lines = _world_check().check(world(), _world_check().parse_template(TEMPLATE.read_text()))
    assert [x.row.question for x in lines if x.status == "required"] == []
    built = [x for x in lines if x.row.standing == "on main"]
    absent = {x.row.keys[0] for x in built if x.status == "absent"}
    assert absent == set(ABSENT_ON_PURPOSE)
    answered = {k for x in built if x.status == "answered" for k in x.row.keys}
    assert {"laws", "locks.question", "locks.decider.council", "aim_patterns"} <= answered
    assert {"groups.groups.chamber", "cards.path", "locks.decider.person"} <= answered
