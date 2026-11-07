"""Engine v2 wave A1: the router, the command path, and bands A and A'.

A command inside the seat's authority goes straight to its executor, who carries it
out with a fidelity or, at the loyalty floor, may refuse under a stated rule."""

import itertools
from datetime import date, timedelta
from typing import Any
from unittest import mock

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, OrderId, derived_id
from revisionist.core.realism import route as rt
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.effect import (
    Appointment,
    Clause,
    ClauseKind,
    Engagement,
    Fidelity,
    MakeStatement,
    ProposeMeasure,
    Route,
    RoutedOrder,
    RoutedPart,
    SetEngagement,
)
from revisionist.core.state import State
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.realism_tick import commit_order, run_realism_tick
from revisionist.engine.store import MemoryStore, load_state
from tests.test_engine_v2_contract import Slice
from tests.test_realism_bands import SEEDS

WORLD = "engine-v2-slice-1941"
TODAY = date(1941, 9, 1)


@pytest.fixture
def sl() -> Slice:
    return Slice()


def shoot(sl: Slice) -> Ask:
    return Ask(
        ask="Shoot on sight in the western Atlantic.",
        effect=SetEngagement(
            force=sl.feature("us_atlantic_fleet"),
            zone="western Atlantic",
            rule=Engagement.SHOOT_ON_SIGHT,
        ),
    )


def bill() -> Ask:
    clause = Clause(kind=ClauseKind.POWER, subject="revise the Neutrality Act")
    return Ask(ask="Send the bill.", effect=ProposeMeasure(title="Neutrality", clauses=(clause,)))


def routed(sl: Slice, part: RoutedPart, filed: date = TODAY, n: int = 1) -> RoutedOrder:
    return RoutedOrder(
        order_id=OrderId(derived_id(sl.state.campaign_id, "a1-order", n)),
        issuer=sl.fdr,
        filed=filed,
        parts=(part,),
    )


def command(sl: Slice) -> RoutedOrder:
    part = rt.route(sl.state, sl.fdr, shoot(sl), TODAY).part
    assert part is not None
    return routed(sl, part)


def with_card(state: State, key: Any, **changes: object) -> State:
    card = state.cards[key].model_copy(update=changes)
    return state.model_copy(update={"cards": {**state.cards, key: card}})


def pin(monkeypatch: pytest.MonkeyPatch, refuse: int = 99, fidelity: int = 1) -> None:
    def fixed(state: State, *parts: object, n: int) -> int:
        return refuse if parts[-1] == "refuse" else fidelity

    monkeypatch.setattr(rt, "friction", fixed)


# --- route ----------------------------------------------------------------------


def test_a_covered_effect_is_a_command_to_the_domains_executor(sl: Slice) -> None:
    routing = rt.route(sl.state, sl.fdr, shoot(sl), TODAY)
    assert routing.part is not None and routing.part.route is Route.COMMAND
    assert routing.part.domain == "naval_operations"
    assert routing.part.executor == sl.entity("stark")


def test_an_effect_of_the_seats_own_is_a_command_with_no_executor(sl: Slice) -> None:
    ask = Ask(ask="Address the nation.", effect=MakeStatement(theme="freedom of the seas"))
    part = rt.route(sl.state, sl.fdr, ask, TODAY).part
    assert part is not None and part.domain == "public_word" and part.executor is None


def test_a_measure_no_domain_covers_runs_the_votes_pipeline(sl: Slice) -> None:
    part = rt.route(sl.state, sl.fdr, bill(), TODAY).part
    assert part is not None and part.route is Route.PROCESS
    lever = next(x for x in sl.state.cards[sl.entity("roosevelt")].levers if x.name == "send_bill")
    assert part.pipeline == lever.pipeline


def test_a_measure_with_no_pipeline_is_refused(sl: Slice) -> None:
    state = with_card(sl.state, sl.entity("roosevelt"), levers=(), pipelines=())
    routing = rt.route(state, sl.fdr, bill(), TODAY)
    assert routing.part is None and routing.refusal.startswith("Nobody under you commands")


def test_a_named_person_with_no_command_is_influence(sl: Slice) -> None:
    ask = Ask(ask="Ask Wheeler to hold his fire.", target=sl.entity("wheeler"))
    part = rt.route(sl.state, sl.fdr, ask, TODAY).part
    assert part is not None and part.route is Route.INFLUENCE
    assert part.target == sl.entity("wheeler") and part.effect is None


def test_an_uncovered_effect_with_a_target_is_influence_and_keeps_its_effect(sl: Slice) -> None:
    ask = shoot(sl).model_copy(update={"target": sl.entity("wheeler")})
    state = with_card(sl.state, sl.entity("roosevelt"), authority=())
    part = rt.route(state, sl.fdr, ask, TODAY).part
    assert part is not None and part.route is Route.INFLUENCE and part.effect == ask.effect


def test_the_refusals_speak_plainly(sl: Slice) -> None:
    state = with_card(sl.state, sl.entity("roosevelt"), authority=())
    stranded = rt.route(state, sl.fdr, shoot(sl), TODAY)
    assert stranded.part is None
    assert stranded.refusal == "Nobody under you commands that. Name the person who decides it."
    bare = rt.route(sl.state, sl.fdr, Ask(ask="Do something."), TODAY)
    assert bare.refusal == "Name who should act on it."
    for words in (stranded.refusal, bare.refusal):
        assert "_" not in words and not any(c.isdigit() for c in words)


def test_a_force_outside_the_domain_is_not_commanded(sl: Slice) -> None:
    ask = shoot(sl).model_copy(
        update={
            "effect": SetEngagement(
                force=sl.feature("uboat_arm"), zone="the Atlantic", rule=Engagement.HOLD_FIRE
            )
        }
    )
    assert rt.route(sl.state, sl.fdr, ask, TODAY).part is None


def test_a_force_before_its_service_date_is_refused_in_words(sl: Slice) -> None:
    key = sl.feature("us_atlantic_fleet")
    later = sl.state.features[key].model_copy(update={"in_service": date(1941, 12, 1)})
    state = sl.state.model_copy(update={"features": {**sl.state.features, key: later}})
    routing = rt.route(state, sl.fdr, shoot(sl), TODAY)
    assert routing.part is None
    assert routing.refusal == "US Atlantic Fleet is not in service until 1 December 1941."
    assert rt.route(state, sl.fdr, shoot(sl), date(1941, 12, 1)).part is not None


# --- fidelity inputs ------------------------------------------------------------


def test_workload_counts_the_executors_uncarried_commands(sl: Slice) -> None:
    stark = sl.entity("stark")
    assert rt.fidelity_inputs(sl.state, stark).workload == 0
    sl.add(ev.OrderRouted(order=command(sl)))
    inputs = rt.fidelity_inputs(sl.state, stark)
    assert (inputs.loyalty, inputs.competence, inputs.workload) == (2, 3, 1)
    assert rt.fidelity_inputs(sl.state, sl.entity("rayburn")).workload == 0
    sl.add(
        ev.OrderExecuted(order_id=command(sl).order_id, part=0, on=TODAY, fidelity=Fidelity.FULL)
    )
    assert rt.fidelity_inputs(sl.state, stark).workload == 0


def test_no_card_means_ordinary_inputs(sl: Slice) -> None:
    inputs = rt.fidelity_inputs(sl.state, sl.entity("germany"))
    assert (inputs.loyalty, inputs.competence, inputs.workload) == (0, 3, 0)
    assert rt.fidelity_inputs(sl.state, None).workload == 0


# --- carry_out ------------------------------------------------------------------


def test_the_seat_acting_itself_is_always_full(sl: Slice) -> None:
    ask = Ask(ask="Address the nation.", effect=MakeStatement(theme="freedom of the seas"))
    part = rt.route(sl.state, sl.fdr, ask, TODAY).part
    assert part is not None
    assert rt.carry_out(sl.state, routed(sl, part), 0) == (Fidelity.FULL, "")


def test_an_appointment_beyond_the_offices_law_is_refused_by_rule(sl: Slice) -> None:
    state = with_card(
        sl.state,
        sl.entity("roosevelt"),
        authority=(
            *sl.state.cards[sl.entity("roosevelt")].authority,
            sl.state.cards[sl.entity("roosevelt")]
            .authority[0]
            .model_copy(update={"name": "appointments", "effects": frozenset({"appointment"})}),
        ),
    )
    for who, lawful in (("stark", True), ("wheeler", False)):
        ask = Ask(ask="Appoint him.", effect=Appointment(person=sl.entity(who), office="Envoy"))
        part = rt.route(state, sl.fdr, ask, TODAY).part
        assert part is not None
        order = routed(sl, part)
        if lawful:
            assert rt.outside_the_law(state, order, 0) == ""
            assert rt.carry_out(state, order, 0)[1] == ""
        else:
            fidelity, words = rt.carry_out(state, order, 0)
            assert fidelity is None and words == rt.outside_the_law(state, order, 0) != ""


TABLE = [
    # loyalty, competence, workload, d (roll - 1), expected
    (2, 3, 0, 0, Fidelity.FULL),
    (1, 3, 0, 0, Fidelity.FULL),
    (0, 3, 0, 0, Fidelity.LOOSE),
    (0, 3, 0, -1, Fidelity.SLOW),
    (-1, 3, 0, 0, Fidelity.SLOW),
    (-2, 3, 0, 0, Fidelity.PARTIAL),
    (-3, 3, 0, -1, Fidelity.PARTIAL),
    (0, 5, 0, 0, Fidelity.FULL),
    (2, 3, 3, 0, Fidelity.FULL),
    (0, 3, 4, 0, Fidelity.PARTIAL),
    (3, 3, 0, 1, Fidelity.FULL),
]


@pytest.mark.parametrize(("loyalty", "competence", "load", "d", "expected"), TABLE)
def test_the_fidelity_table(
    sl: Slice,
    monkeypatch: pytest.MonkeyPatch,
    loyalty: int,
    competence: int,
    load: int,
    d: int,
    expected: Fidelity,
) -> None:
    pin(monkeypatch, fidelity=d + 1)
    stark = sl.entity("stark")
    base = with_card(sl.state, stark, loyalty=loyalty, competence=competence)
    order = command(sl)
    others = [routed(sl, order.parts[0], n=10 + k) for k in range(load - 1)]
    queued = {o.order_id: o for o in (order, *others)} if load else {}
    state = base.model_copy(update={"routed": queued})
    assert rt.fidelity_inputs(state, stark).workload == load
    assert rt.carry_out(state, order, 0) == (expected, "")


def test_refusal_needs_the_floor(sl: Slice, monkeypatch: pytest.MonkeyPatch) -> None:
    pin(monkeypatch, refuse=0)  # the roll always says refuse
    stark = sl.entity("stark")
    order = command(sl)
    fidelity, words = rt.carry_out(with_card(sl.state, stark, loyalty=-4), order, 0)
    assert fidelity is None and words == "loyalty -4: Stark will not carry it out"
    assert rt.carry_out(with_card(sl.state, stark, loyalty=-3), order, 0)[0] is not None
    pin(monkeypatch, refuse=50)
    assert rt.carry_out(with_card(sl.state, stark, loyalty=-4), order, 0)[0] is not None


# --- due_executions -------------------------------------------------------------


def test_executions_fall_due_in_order_and_once(sl: Slice) -> None:
    sl.add(ev.OrderRouted(order=command(sl)))
    assert rt.due_executions(sl.state, TODAY) == []
    (done,) = rt.due_executions(sl.state, TODAY + timedelta(days=5))
    assert done.on - TODAY <= timedelta(days=2) and done.order_id == command(sl).order_id
    sl.add(done)
    assert rt.due_executions(sl.state, TODAY + timedelta(days=5)) == []


def test_execution_days_never_pass_two() -> None:
    assert max([*rt.EXECUTE_DAYS.values(), rt.REFUSE_DAYS]) <= 2


# --- the bands, through the real entry points -----------------------------------


def play(campaign: CampaignId, loyalty: int) -> tuple[RoutedOrder, State, str]:
    """One run to the first wake. The order id is pinned so a rerun rolls the same dice."""
    ids = itertools.count()
    with mock.patch.object(
        realism_tick, "new_id", lambda: derived_id(campaign, "a1-new-id", next(ids))
    ):
        return _play(campaign, loyalty)


def _play(campaign: CampaignId, loyalty: int) -> tuple[RoutedOrder, State, str]:
    world = cmp.load_world(cmp.world_path(WORLD))
    cards = tuple(
        c.model_copy(update={"loyalty": loyalty}) if c.person == "stark" else c for c in world.cards
    )
    world = world.model_copy(update={"cards": cards})
    store = MemoryStore()
    store.append_all(compile_world(world, campaign, cmp.versions()))
    realism_tick.seat_player(store, campaign, EntityId(resolve_keys(world, campaign)["roosevelt"]))
    state = load_state(store, campaign)
    (seat,) = state.seats
    fleet = resolve_keys(world, campaign)["us_atlantic_fleet"]
    order = commit_order(
        store,
        campaign,
        seat,
        [
            Ask(
                ask="Shoot on sight.",
                effect=SetEngagement(
                    force=fleet, zone="western Atlantic", rule=Engagement.SHOOT_ON_SIGHT
                ),
            )
        ],
    )
    result = run_realism_tick(store, campaign)
    return order, load_state(store, campaign), result.state_hash or ""


def kinds(campaign: CampaignId, store: MemoryStore) -> list[str]:
    return [e.kind for e in store.read(campaign)]


@pytest.mark.parametrize("loyalty", [0, 2, 5])
def test_band_a_a_command_inside_authority_lands_within_two_days(loyalty: int) -> None:
    for seed in SEEDS:
        order, state, _ = play(seed, loyalty)
        part = state.routed[order.order_id].parts[0]
        assert part.route is Route.COMMAND and part.executor is not None
        assert state.entities[part.executor].name == "Harold R. Stark"
        assert part.refusal == "" and part.fidelity is not None
        assert part.executed is not None and part.executed - order.filed <= timedelta(days=2)
        assert order.order_id not in state.orders


def test_band_a_a_command_has_no_approval_step() -> None:
    campaign = SEEDS[0]
    store = MemoryStore()
    world = cmp.load_world(cmp.world_path(WORLD))
    store.append_all(compile_world(world, campaign, cmp.versions()))
    realism_tick.seat_player(store, campaign, EntityId(resolve_keys(world, campaign)["roosevelt"]))
    (seat,) = load_state(store, campaign).seats
    fleet = resolve_keys(world, campaign)["us_atlantic_fleet"]
    ask = Ask(
        ask="Shoot on sight.",
        effect=SetEngagement(force=fleet, zone="western Atlantic", rule=Engagement.SHOOT_ON_SIGHT),
    )
    commit_order(store, campaign, seat, [ask])
    run_realism_tick(store, campaign)
    log = kinds(campaign, store)
    assert "order_executed" in log
    assert "order_drafted" not in log and "order_step_taken" not in log


def test_band_a_prime_the_refusal_floor() -> None:
    def outcomes(loyalty: int) -> list[str]:
        return [load_state_part(play(seed, loyalty)).refusal for seed in SEEDS]

    def load_state_part(played: tuple[RoutedOrder, State, str]) -> RoutedPart:
        order, state, _ = played
        return state.routed[order.order_id].parts[0]

    floor = outcomes(-4)
    assert any(floor), "at -4 some seed should refuse"
    assert all("loyalty -4" in r and "Stark" in r for r in floor if r)
    assert outcomes(-4) == floor
    assert not any(outcomes(-3))


def test_a_routed_command_replays_to_the_same_hash() -> None:
    first = play(SEEDS[0], 2)
    second = play(SEEDS[0], 2)
    assert first[2] and first[2] == second[2]


def test_a_refused_ask_logs_nothing() -> None:
    campaign = SEEDS[0]
    store = MemoryStore()
    world = cmp.load_world(cmp.world_path(WORLD))
    store.append_all(compile_world(world, campaign, cmp.versions()))
    realism_tick.seat_player(store, campaign, EntityId(resolve_keys(world, campaign)["roosevelt"]))
    (seat,) = load_state(store, campaign).seats
    before = len(list(store.read(campaign)))
    with pytest.raises(ValueError, match="Name who should act on it"):
        commit_order(store, campaign, seat, [Ask(ask="Do something.")])
    assert len(list(store.read(campaign))) == before
