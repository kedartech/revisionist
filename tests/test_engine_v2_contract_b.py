"""Engine v2 wave B contract, schema 19: the new records store, project and scan as
specified, the hook stubs answer their neutral values, the ESTIMATE stage lands one
ruling per uncovered part, and an older log hashes as it did before any of it.

No wave B behaviour is tested here: nothing applies, decides, opens or issues yet.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.canary import scan
from revisionist.core.fold import FoldError, replay, state_hash
from revisionist.core.goals import ActOf, GoalKind, Ordered, difficulty, goal_kind, goal_met
from revisionist.core.ids import CampaignId, EntityId, FactId, OrderId, PipelineId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import agenda as ra
from revisionist.core.realism import apply, mandates, process
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.pipeline import Order, Pipeline, Step, StepKind
from revisionist.core.resolution import TickStage
from revisionist.core.settings import Settings
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.core.world import TriggerDecl
from revisionist.core.world_compile import WorldError, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import options, wake
from revisionist.engine import realism_tick as rt
from revisionist.engine.estimate import CALL_CLASS, clamp
from revisionist.engine.llm import Reply, Request
from revisionist.engine.store import MemoryStore, load_state
from tests.test_engine_v2_contract import (
    CAMPAIGN,
    REASON_CANARY,
    Slice,
    _refused,
    _with_covert_fact,
)

FILED = date(1941, 9, 11)
COVERT = FactId(derived_id(CAMPAIGN, "fact", "covert"))
NEW_LATE = frozenset(
    {
        "templates",
        "wake_hours",
        "posture",
        "engagement",
        "decided",
        "accepted",
        "applied",
        "routed_from",
        "measure",
    }
)


def _keys(dump: object) -> set[str]:
    """Every field name anywhere in a dumped model."""
    if isinstance(dump, dict):
        return {str(k) for k in dump} | {k for v in dump.values() for k in _keys(v)}
    if isinstance(dump, list):
        return {k for v in dump for k in _keys(v)}
    return set()


@pytest.fixture
def sl() -> Slice:
    return Slice()


def _order(sl: Slice, n: int, *parts: rx.RoutedPart) -> rx.RoutedOrder:
    return rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "b-order", n)),
        issuer=sl.fdr,
        filed=FILED,
        parts=parts,
    )


def _influence(sl: Slice, effect: rx.Effect | None = None) -> rx.RoutedPart:
    return rx.RoutedPart(route=rx.Route.INFLUENCE, target=sl.entity("wheeler"), effect=effect)


def _process(sl: Slice) -> rx.RoutedPart:
    return rx.RoutedPart(
        route=rx.Route.PROCESS,
        pipeline=sl.state.cards[sl.entity("roosevelt")].pipelines[0],
        effect=_bill(),
    )


def _bill() -> rx.ProposeMeasure:
    return rx.ProposeMeasure(
        title="Arm the merchant ships",
        clauses=(rx.Clause(kind=rx.ClauseKind.POWER, subject="arm merchant ships"),),
    )


def _routed(sl: Slice, order: rx.RoutedOrder) -> rx.RoutedOrder:
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    return order


def _executed(sl: Slice, refused: bool = False) -> rx.RoutedOrder:
    order = _routed(sl, sl.shoot_on_sight())
    done: dict[str, Any] = {"refusal": "loyalty -4"} if refused else {"fidelity": rx.Fidelity.FULL}
    sl.add(ev.OrderExecuted(order_id=order.order_id, part=0, on=FILED, **done), private_to(sl.fdr))
    return order


def _applied(order_id: OrderId, part: int = 0, **more: Any) -> ev.EffectsApplied:
    return ev.EffectsApplied(order_id=order_id, part=part, on=FILED, **more)


def _decided(order_id: OrderId, part: int = 0, **more: Any) -> ev.InfluenceDecided:
    return ev.InfluenceDecided(order_id=order_id, part=part, on=FILED, accepted=True, **more)


# --- schema --------------------------------------------------------------------------


def test_new_late_fields_leave_older_dumps_unchanged(sl: Slice) -> None:
    fleet = sl.state.features[sl.feature("us_atlantic_fleet")]
    part = sl.shoot_on_sight().parts[0]
    models = [fleet, part, Settings(), ev.CardsDeclared(), replay(sl.events[:5])]
    assert NEW_LATE.isdisjoint(k for m in models for k in _keys(m.model_dump(mode="json")))
    assert Settings().wake_hours == 12


def test_a_part_is_decided_and_accepted_together_and_only_as_influence() -> None:
    who = EntityId(derived_id("who"))
    rx.PartView(route=rx.Route.INFLUENCE, target=who, decided=FILED, accepted=False)
    with pytest.raises(ValidationError, match="together"):
        rx.PartView(route=rx.Route.INFLUENCE, target=who, decided=FILED)
    with pytest.raises(ValidationError, match="together"):
        rx.PartView(route=rx.Route.INFLUENCE, target=who, accepted=True)
    with pytest.raises(ValidationError, match="only an influence part"):
        rx.PartView(route=rx.Route.COMMAND, domain="x", decided=FILED, accepted=True)
    rx.PartView(route=rx.Route.PROCESS, pipeline=PipelineId("p"), applied=FILED)


def test_a_trigger_names_exactly_the_fields_for_its_kind() -> None:
    ra.Trigger(on=ra.TriggerKind.QUANTITY, quantity="q", op="ge", value=0)
    ra.Trigger(on=ra.TriggerKind.ACT, effect=rx.EffectKind.ENGAGEMENT)
    with pytest.raises(ValidationError, match="names exactly history"):
        ra.Trigger(on=ra.TriggerKind.HISTORY)
    with pytest.raises(ValidationError, match="names exactly op, quantity, value"):
        ra.Trigger(on=ra.TriggerKind.QUANTITY, quantity="q", op="ge")
    with pytest.raises(ValidationError, match="names exactly effect"):
        ra.Trigger(on=ra.TriggerKind.ACT, effect=rx.EffectKind.DEAL, history="h")


# --- the slice's templates -------------------------------------------------------


def test_the_slices_templates_compile_into_state_and_never_into_a_view(sl: Slice) -> None:
    state = sl.state
    assert len(state.cards) == 6
    assert list(state.templates) == [
        "greer_response",
        "commons_convoys",
        "shoot_outcry",
        "arms_bill",
    ]
    greer = state.templates["greer_response"]
    assert greer.kind is ra.MandateKind.CRISIS and greer.to == (sl.entity("roosevelt"),)
    assert greer.trigger.history == sl.ids["greer_incident"]
    assert greer.condition == Ordered(
        person=sl.entity("roosevelt"), effect=rx.EffectKind.ENGAGEMENT
    )
    convoys = state.templates["commons_convoys"]
    assert convoys.issuer == sl.entity("commons") and convoys.days == 10
    assert state.templates["shoot_outcry"].trigger.effect is rx.EffectKind.ENGAGEMENT
    for seat in (sl.fdr, sl.wheeler):
        dump = project(state, seat).model_dump_json()
        assert "templates" not in dump and "the Navy's rules" not in dump


def _slice_with(**mandate: Any) -> None:
    world = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
    first = world.mandates[0].model_copy(update=mandate)
    compile_world(
        world.model_copy(update={"mandates": (first, *world.mandates[1:])}),
        CAMPAIGN,
        cmp.versions(),
    )


def test_a_template_names_only_what_the_world_holds() -> None:
    with pytest.raises(WorldError, match="unknown history no_such_day"):
        _slice_with(trigger=TriggerDecl(on=ra.TriggerKind.HISTORY, history="no_such_day"))
    with pytest.raises(WorldError, match="names exactly history"):
        _slice_with(trigger=TriggerDecl(on=ra.TriggerKind.HISTORY))
    with pytest.raises(WorldError, match="unknown entity nobody"):
        _slice_with(to=("nobody",))
    with pytest.raises(WorldError, match="only an order, has an issuer"):
        _slice_with(issuer="commons")
    world = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
    twice = world.model_copy(update={"mandates": (*world.mandates, world.mandates[0])})
    with pytest.raises(WorldError, match="greer_response: duplicate key"):
        compile_world(twice, CAMPAIGN, cmp.versions())


def test_a_legacy_world_has_no_mandates() -> None:
    legacy = cmp.load_world(cmp.world_path("salt-strait"))
    slice_ = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
    with pytest.raises(WorldError, match="only a realism world has mandates"):
        compile_world(
            legacy.model_copy(update={"mandates": slice_.mandates}), CAMPAIGN, cmp.versions()
        )


def test_the_fold_refuses_a_template_twice_or_for_nobody(sl: Slice) -> None:
    greer = sl.state.templates["greer_response"]
    _refused(sl, ev.CardsDeclared(templates=(greer,)), "duplicate mandate template")
    stray = greer.model_copy(update={"key": "stray", "to": (EntityId(derived_id("nobody")),)})
    _refused(sl, ev.CardsDeclared(templates=(stray,)), "unknown entity")
    sl.add(ev.CardsDeclared(templates=(greer.model_copy(update={"key": "fresh"}),)))
    assert "fresh" in sl.state.templates


# --- effects_applied -------------------------------------------------------------


def test_an_executed_command_applies_once(sl: Slice) -> None:
    order = _executed(sl)
    sl.add(_applied(order.order_id), private_to(sl.fdr))
    assert sl.state.routed[order.order_id].parts[0].applied == FILED
    _refused(sl, _applied(order.order_id), "already applied")


def test_a_refused_command_still_closes_by_applying(sl: Slice) -> None:
    order = _executed(sl, refused=True)
    sl.add(_applied(order.order_id), private_to(sl.fdr))
    assert sl.state.routed[order.order_id].parts[0].applied == FILED


def test_an_estimated_part_and_a_decided_influence_apply(sl: Slice) -> None:
    order = _routed(sl, _order(sl, 1, _influence(sl), _influence(sl)))
    sl.add(ev.EffectsEstimated(order_id=order.order_id, part=0, reason="r"), private_to(sl.fdr))
    sl.add(_decided(order.order_id, 1), private_to(sl.fdr))
    sl.add(_applied(order.order_id, 0), private_to(sl.fdr))
    sl.add(_applied(order.order_id, 1), private_to(sl.fdr))
    assert [p.applied for p in sl.state.routed[order.order_id].parts] == [FILED, FILED]


def test_applying_reveals_facts_to_the_public(sl: Slice) -> None:
    _with_covert_fact(sl)
    order = _executed(sl)
    assert sl.state.facts[COVERT].scope != PUBLIC
    sl.add(_applied(order.order_id, revealed=(COVERT,)), private_to(sl.fdr))
    assert sl.state.facts[COVERT].scope == PUBLIC


def test_applying_an_unknown_order_is_refused(sl: Slice) -> None:
    _refused(sl, _applied(OrderId(derived_id("no-order"))), "unknown order")


def test_applying_a_missing_part_is_refused(sl: Slice) -> None:
    order = _executed(sl)
    _refused(sl, _applied(order.order_id, 1), "has no part 1")


def test_applying_a_command_not_yet_executed_is_refused(sl: Slice) -> None:
    order = _routed(sl, sl.shoot_on_sight())
    _refused(sl, _applied(order.order_id), "not ready")


def test_applying_an_undecided_influence_is_refused(sl: Slice) -> None:
    order = _routed(sl, _order(sl, 1, _influence(sl, rx.MakeStatement(theme="x"))))
    _refused(sl, _applied(order.order_id), "not ready")


def test_applying_an_unruled_process_is_refused(sl: Slice) -> None:
    order = _routed(sl, _order(sl, 1, _process(sl)))
    _refused(sl, _applied(order.order_id), "not ready")


def test_applying_before_the_order_was_filed_is_refused(sl: Slice) -> None:
    order = _executed(sl)
    early = _applied(order.order_id).model_copy(update={"on": date(1941, 9, 10)})
    _refused(sl, early, "before it is filed")


def test_revealing_an_unknown_fact_is_refused(sl: Slice) -> None:
    order = _executed(sl)
    _refused(sl, _applied(order.order_id, revealed=(COVERT,)), "unknown fact")


def test_wave_b_records_are_refused_in_a_legacy_campaign() -> None:
    legacy = compile_world(cmp.load_world(cmp.world_path("salt-strait")), CAMPAIGN, cmp.versions())
    for n, payload in enumerate((_applied(OrderId("x")), _decided(OrderId("x")))):
        stray = legacy[-1].model_copy(
            update={
                "seq": len(legacy),
                "event_id": derived_id(CAMPAIGN, "b-stray", n),
                "payload": payload,
            }
        )
        with pytest.raises(FoldError, match="realism campaign"):
            replay([*legacy, stray])


# --- influence_decided -----------------------------------------------------------


def test_an_influence_part_is_decided_once(sl: Slice) -> None:
    order = _routed(sl, _order(sl, 1, _influence(sl)))
    refused = ev.InfluenceDecided(order_id=order.order_id, part=0, on=FILED, accepted=False)
    sl.add(refused, private_to(sl.fdr))
    part = sl.state.routed[order.order_id].parts[0]
    assert part.decided == FILED and part.accepted is False
    _refused(sl, _decided(order.order_id), "already decided")


def test_deciding_a_command_is_refused(sl: Slice) -> None:
    order = _routed(sl, sl.shoot_on_sight())
    _refused(sl, _decided(order.order_id), "not influence")


def test_deciding_an_unknown_order_is_refused(sl: Slice) -> None:
    _refused(sl, _decided(OrderId(derived_id("no-order"))), "unknown order")


def test_a_canary_in_an_influence_reason_is_a_leak_for_the_issuer(sl: Slice) -> None:
    _with_covert_fact(sl)
    order = _routed(sl, _order(sl, 1, _influence(sl)))
    sl.add(_decided(order.order_id, reason=f"Not while {REASON_CANARY}."), private_to(sl.fdr))
    leaks = scan(sl.state, sl.events)
    assert [(lk.seat_id, lk.kind) for lk in leaks] == [(sl.fdr, "influence_decided")]


# --- order_drafted carrying a process part ---------------------------------------


def _carrier(sl: Slice, order: rx.RoutedOrder, n: int = 1, **more: Any) -> ev.OrderDrafted:
    fields: dict[str, Any] = {
        "order_id": OrderId(derived_id(CAMPAIGN, "carrier", n)),
        "issuer": sl.fdr,
        "lever": "send_bill",
        "pipeline": order.parts[0].pipeline,
        "filed": FILED,
        "routed_from": rx.PartRef(order_id=order.order_id, part=0),
        "measure": _bill(),
    }
    return ev.OrderDrafted(order=Order.model_validate(fields | more))


def test_a_pipeline_order_carries_a_process_part_once(sl: Slice) -> None:
    order = _routed(sl, _order(sl, 1, _process(sl)))
    sl.add(_carrier(sl, order))
    carried = sl.state.orders[OrderId(derived_id(CAMPAIGN, "carrier", 1))]
    assert carried.routed_from == rx.PartRef(order_id=order.order_id, part=0)
    assert carried.measure == _bill()
    _refused(sl, _carrier(sl, order, 2), "already carried")


def test_carrying_an_unknown_routed_order_is_refused(sl: Slice) -> None:
    order = _order(sl, 1, _process(sl))
    _refused(sl, _carrier(sl, order), "unknown order")


def test_carrying_a_part_that_is_not_a_process_is_refused(sl: Slice) -> None:
    order = _routed(sl, _order(sl, 1, _influence(sl)))
    pipeline = sl.state.cards[sl.entity("roosevelt")].pipelines[0]
    _refused(sl, _carrier(sl, order, pipeline=pipeline), "is not that process")


def test_carrying_a_part_down_another_pipeline_is_refused(sl: Slice) -> None:
    other = Pipeline(
        pipeline_id=PipelineId(derived_id(CAMPAIGN, "pipeline", "other")),
        name="Another way",
        steps=(Step(person=sl.entity("rayburn"), kind=StepKind.CLERICAL, days=1),),
    )
    sl.add(ev.CardsDeclared(pipelines=(other,)))
    order = _routed(sl, _order(sl, 1, _process(sl)))
    _refused(sl, _carrier(sl, order, pipeline=other.pipeline_id), "is not that process")


# --- the ordered check -------------------------------------------------------------


def test_ordered_is_met_once_a_human_seats_part_of_that_kind_applies(sl: Slice) -> None:
    engaged = Ordered(person=sl.entity("roosevelt"), effect=rx.EffectKind.ENGAGEMENT)
    assert goal_kind(engaged) is GoalKind.LASTING
    order = _executed(sl)
    assert not goal_met(sl.state, engaged)
    assert difficulty(sl.state, sl.fdr, engaged) == 2
    sl.add(_applied(order.order_id), private_to(sl.fdr))
    assert goal_met(sl.state, engaged)
    assert not goal_met(project(sl.state, sl.fdr), engaged)  # a View hides who is human
    assert not goal_met(sl.state, engaged.model_copy(update={"effect": rx.EffectKind.DEAL}))
    assert not goal_met(sl.state, engaged.model_copy(update={"person": sl.entity("wheeler")}))


def test_ordered_counts_an_estimated_effect(sl: Slice) -> None:
    spoke = Ordered(person=sl.entity("roosevelt"), effect=rx.EffectKind.STATEMENT)
    order = _routed(sl, _order(sl, 1, _influence(sl)))
    ruling = ev.EffectsEstimated(
        order_id=order.order_id, part=0, effects=(rx.MakeStatement(theme="x"),), reason="r"
    )
    sl.add(ruling, private_to(sl.fdr))
    assert not goal_met(sl.state, spoke)
    sl.add(_applied(order.order_id), private_to(sl.fdr))
    assert goal_met(sl.state, spoke)


def test_ordered_is_never_met_for_a_person_no_human_holds(sl: Slice) -> None:
    """Unlike act_of, which history meets for a person nobody plays."""
    churchill = sl.entity("churchill")
    assert not goal_met(sl.state, Ordered(person=churchill, effect=rx.EffectKind.MOVE_FORCE))
    assert goal_met(sl.state, ActOf(person=churchill))


# --- the hook stubs ------------------------------------------------------------------


def test_every_stub_returns_its_neutral_value(sl: Slice) -> None:
    state, today = sl.state, FILED
    assert apply.apply_due(state, today) == []
    assert apply.report(state, sl.shoot_on_sight(), 0, today) is None
    assert process.open_processes(state, today) == []
    assert process.influence_due(state, today) == []
    assert mandates.issue_due(state, today) == []
    assert mandates.settle_due(state, today) == []
    assert mandates.score(state, sl.fdr) == 0
    store, now = MemoryStore(), datetime(2026, 11, 1, tzinfo=UTC)
    b1: list[Callable[[], object]] = [
        lambda: wake.open_wake(store, CAMPAIGN, now),
        lambda: wake.commit(store, CAMPAIGN, sl.fdr, now),
        lambda: wake.close_wake(store, CAMPAIGN, now, None),
        lambda: wake.wake_due(state, now),
    ]
    for call in b1:
        with pytest.raises(NotImplementedError, match="Wave B unit B1"):
            call()
    b3: list[Callable[[], object]] = [
        lambda: options.offer(state, sl.fdr, None),
        lambda: options.aide_asks(state, sl.fdr, None),
        lambda: options.set_style(store, CAMPAIGN, sl.fdr, ra.PlayStyle.GUIDED),
    ]
    for call in b3:
        with pytest.raises(NotImplementedError, match="Wave B unit B3"):
            call()
    assert (options.OPTIONS_MODEL, options.CALL_CLASS, options.PROMPT) == (
        "claude-haiku-5-5",
        "options",
        "options",
    )
    assert options.RECORDING == "realism-options-slice.json"


# --- the ESTIMATE stage --------------------------------------------------------------


class _Ruler:
    """Rules every part the same way and counts its calls."""

    def __init__(self) -> None:
        self.calls = 0

    def call(self, request: Request) -> Reply:
        self.calls += 1
        output = {"effects": [], "reason": "Wheeler hears you out.", "rationale": "No change."}
        return Reply(
            output=output, model="stub", input_tokens=10, output_tokens=5, cached_tokens=0, usd=0.0
        )


def _seated_slice(store: MemoryStore) -> tuple[CampaignId, rx.RoutedOrder]:
    world = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
    store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
    roosevelt = EntityId(derived_id(CAMPAIGN, "entity", "roosevelt"))
    rt.seat_player(store, CAMPAIGN, roosevelt)
    (fdr,) = load_state(store, CAMPAIGN).seats
    wheeler = EntityId(derived_id(CAMPAIGN, "entity", "wheeler"))
    fleet = load_state(store, CAMPAIGN).cards[roosevelt].authority[0].forces[0]
    shoot = rx.SetEngagement(
        force=fleet, zone="western Atlantic", rule=rx.Engagement.SHOOT_ON_SIGHT
    )
    asks = [
        Ask(ask="Shoot on sight in the western Atlantic.", effect=shoot),
        Ask(ask="Ask Wheeler to hold his fire in the Senate.", target=wheeler),
    ]
    return CAMPAIGN, rt.commit_order(store, CAMPAIGN, fdr, asks)


def test_the_estimate_stage_rules_each_uncovered_part_once_and_resumes() -> None:
    store, ruler = MemoryStore(), _Ruler()
    cid, order = _seated_slice(store)
    assert [p.effect is None for p in order.parts] == [False, True]
    rt.run_realism_tick(store, cid, estimator=ruler, stop_after=TickStage.ESTIMATE)
    rt.run_realism_tick(store, cid, estimator=ruler)
    log = list(store.read(cid))
    rulings = [e for e in log if isinstance(e.payload, ev.EffectsEstimated)]
    assert ruler.calls == 1 and len(rulings) == 1
    ruling = rulings[0].payload
    assert isinstance(ruling, ev.EffectsEstimated) and ruling.part == 1
    assert rulings[0].scope == private_to(order.issuer)
    costs = [e.payload for e in log if isinstance(e.payload, ev.CostLogged)]
    assert [c.purpose for c in costs] == [CALL_CLASS]
    marks = [e.payload.stage for e in log if isinstance(e.payload, ev.TickStageCompleted)]
    assert marks.count(TickStage.ESTIMATE) == 1 and marks[0] is TickStage.ESTIMATE
    assert load_state(store, cid).routed[order.order_id].parts[1].was_estimated


def test_the_disposition_cap_holds_across_an_order(sl: Slice) -> None:
    wheeler, fdr = sl.entity("wheeler"), sl.entity("roosevelt")
    given = rx.ShiftDisposition(of=wheeler, toward=fdr, change=-2)
    order = _routed(sl, _order(sl, 1, _influence(sl, given), _influence(sl)))
    down = rx.ShiftDisposition(of=wheeler, toward=fdr, change=-1)
    kept, dropped = clamp(sl.state, order, [down], FILED)
    assert kept == () and "at the cap" in dropped[0]
    up = rx.ShiftDisposition(of=wheeler, toward=fdr, change=2)
    kept, _ = clamp(sl.state, order, [up], FILED)
    assert kept == (up,)


# --- older logs ----------------------------------------------------------------------


def test_an_older_realism_log_hashes_as_before_wave_b() -> None:
    """One realism tick of autumn-1941 with no estimator: no new late field reaches the
    state, so its hash is what schema 18 gave. The recorded legacy log is pinned byte
    for byte by tests/test_realism_contract.py::
    test_the_recorded_legacy_log_replays_and_reserialises_byte_for_byte."""
    store = MemoryStore()
    world = cmp.load_world(cmp.world_path("autumn-1941"))
    store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
    rt.seat_player(store, CAMPAIGN, EntityId(derived_id(CAMPAIGN, "entity", "roosevelt")))
    result = rt.run_realism_tick(store, CAMPAIGN)
    log = list(store.read(CAMPAIGN))
    before_close = replay(log[:-1])
    assert state_hash(before_close) == result.state_hash
    dump = before_close.model_dump(mode="json", exclude={"contests"})  # a contest is decided
    assert NEW_LATE.isdisjoint(_keys(dump))
    stages = [e.payload.stage for e in log if isinstance(e.payload, ev.TickStageCompleted)]
    assert TickStage.ESTIMATE not in stages
