"""The event-driven advance (unit B1): candidates, clamping, ties, and determinism."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import (
    CampaignId,
    EntityId,
    EventId,
    OrderId,
    PipelineId,
    SeatId,
    derived_id,
)
from revisionist.core.realism.advance import DEFAULT_HORIZON_DAYS, next_wake
from revisionist.core.realism.feeds import issue
from revisionist.core.realism.pipeline import Order, StepAction, StepOutcome
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")


class Rig:
    def __init__(self, world: str = "realism-toy") -> None:
        loaded = cmp.load_world(cmp.world_path(world))
        self.ids = resolve_keys(loaded, CAMPAIGN)
        self.events = compile_world(loaded, CAMPAIGN, cmp.versions())

    def start(self, *keys: str) -> None:
        for key in keys:
            self.add(ev.CharacterClaimed(seat_id=self.seat(key), entity_id=EntityId(self.ids[key])))
        self.add(ev.SessionZeroClosed())

    def seat(self, key: str) -> SeatId:
        return SeatId(derived_id(CAMPAIGN, "seat", key))

    def add(self, payload: ev.Payload) -> None:
        seq = len(self.events)
        self.events.append(
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "test-event", seq)),
                campaign_id=CAMPAIGN,
                seq=seq,
                tick=0,
                scope=PUBLIC,
                payload=payload,
                versions=cmp.versions(),
            )
        )

    @property
    def state(self) -> State:
        return replay(self.events)

    @property
    def start_day(self) -> date:
        return next(iter(self.state.quantities.values())).as_of

    def order(self, filed: date, **kw: object) -> Order:
        base: dict[str, object] = {
            "order_id": OrderId(derived_id(CAMPAIGN, "order", filed.isoformat())),
            "issuer": self.seat("ada"),
            "lever": "propose_levy",
            "pipeline": PipelineId(self.ids["levy_bill"]),
            "filed": filed,
        }
        return Order.model_validate(base | kw)


def _with_order(state: State, order: Order) -> State:
    return state.model_copy(update={"orders": {order.order_id: order}})


def test_quiet_world_wakes_at_the_horizon() -> None:
    rig = Rig()
    rig.start("bram")
    today = rig.start_day - timedelta(days=30)
    wake = next_wake(rig.state, today)
    assert wake.to == today + timedelta(days=7)
    assert wake.reason.what == "horizon" and wake.reason.label == "horizon"
    assert wake.collapsed_days == 6


def test_the_smallest_human_horizon_wins() -> None:
    ada, bram = Rig(), Rig()
    ada.start("ada")
    bram.start("bram")
    today = ada.start_day - timedelta(days=30)
    assert next_wake(ada.state, today).to == today + timedelta(days=14)
    assert next_wake(bram.state, today).to == today + timedelta(days=7)
    both = Rig()
    both.start("ada", "bram")
    assert next_wake(both.state, today).to == today + timedelta(days=7)


def test_no_human_seat_uses_the_default_horizon() -> None:
    rig = Rig()
    today = rig.start_day - timedelta(days=30)
    assert next_wake(rig.state, today).to == today + timedelta(days=DEFAULT_HORIZON_DAYS)


def test_a_feed_falling_due_does_not_wake_the_world() -> None:
    """Routine paper waits in the in-tray (Josh, 2026-10-23)."""
    rig = Rig()
    rig.start("ada", "bram")
    today = rig.start_day - timedelta(days=3)
    wake = next_wake(rig.state, today)
    assert wake.reason.what == "horizon"
    assert wake.to == today + timedelta(days=7)


def test_an_unreceived_feed_does_not_count() -> None:
    rig = Rig()
    rig.start("bram")
    today = rig.start_day - timedelta(days=3)
    wake = next_wake(rig.state, today)
    assert wake.reason.what == "horizon"
    assert wake.to == today + timedelta(days=7)


def test_a_document_arriving_tomorrow_does_not_wake_the_world() -> None:
    rig = Rig()
    rig.start("ada", "bram")
    today = rig.start_day - timedelta(days=30)
    feed = next(iter(rig.state.feeds.values()))
    doc = issue(rig.state, feed, today, "s")
    assert doc is not None
    rig.add(doc)
    wake = next_wake(rig.state, today)
    assert wake.reason.what == "horizon"
    assert wake.to == today + timedelta(days=7)


def test_an_order_filed_mid_stretch_shortens_the_wake() -> None:
    rig = Rig()
    rig.start("ada", "bram")
    today = rig.start_day - timedelta(days=30)
    assert next_wake(rig.state, today).to == today + timedelta(days=7)
    rig.add(ev.OrderDrafted(order=rig.order(today)))
    wake = next_wake(rig.state, today)
    assert wake.to == today + timedelta(days=2)
    assert wake.reason.what == "step"
    assert wake.reason.label == "Propose a levy, now with Cora Senn"


def test_a_step_held_by_a_human_adds_no_candidate_and_an_ai_step_does() -> None:
    today = Rig().start_day - timedelta(days=30)
    cora = "cora"

    held = Rig()
    held.start("ada", "bram")
    at_bram = held.order(
        today,
        step=1,
        outcomes=(
            StepOutcome(step=0, person=EntityId(held.ids[cora]), action=StepAction.PASS, on=today),
        ),
    )
    wake = next_wake(_with_order(held.state, at_bram), today)
    assert wake.reason.what == "horizon" and wake.to == today + timedelta(days=7)

    ai = Rig()
    ai.start("ada")
    at_ai = ai.order(
        today,
        step=1,
        outcomes=(
            StepOutcome(step=0, person=EntityId(ai.ids[cora]), action=StepAction.PASS, on=today),
        ),
    )
    wake = next_wake(_with_order(ai.state, at_ai), today)
    assert wake.reason.what == "step" and wake.to == today + timedelta(days=5)


def test_a_relay_step_does_not_wake_the_world_the_answer_does() -> None:
    """Cora's clerical pass is routine; Bram's decision at the last step answers Ada."""
    rig = Rig()
    rig.start("ada")
    today = rig.start_day - timedelta(days=30)
    rig.add(ev.OrderDrafted(order=rig.order(today)))
    wake = next_wake(rig.state, today)
    assert wake.to == today + timedelta(days=2 + 5)
    assert wake.reason.what == "step"
    assert wake.reason.label == "Propose a levy, now with Bram Tull"


def test_an_ai_order_that_never_reaches_a_human_does_not_wake_the_world() -> None:
    rig = Rig()
    rig.start("ada")
    today = rig.start_day - timedelta(days=30)
    theirs = rig.order(today, issuer=rig.seat("bram"))
    wake = next_wake(_with_order(rig.state, theirs), today)
    assert wake.reason.what == "horizon"
    assert wake.to == today + timedelta(days=14)


def test_a_decision_mid_chain_on_your_order_wakes_the_world() -> None:
    """A clerk after the decision does not delay the answer: Bram may refuse or amend."""
    rig = Rig()
    rig.start("ada")
    today = rig.start_day - timedelta(days=30)
    order = rig.order(today)
    pid = order.pipeline
    chain = rig.state.pipelines[pid]
    steps = (*chain.steps, chain.steps[0])
    state = _with_order(rig.state, order)
    state = state.model_copy(
        update={"pipelines": {**state.pipelines, pid: chain.model_copy(update={"steps": steps})}}
    )
    wake = next_wake(state, today)
    assert wake.to == today + timedelta(days=2 + 5)
    assert wake.reason.label == "Propose a levy, now with Bram Tull"


def test_an_all_clerical_order_wakes_the_world_when_it_settles() -> None:
    rig = Rig()
    rig.start("ada")
    today = rig.start_day - timedelta(days=30)
    order = rig.order(today)
    pid = order.pipeline
    chain = rig.state.pipelines[pid]
    steps = (chain.steps[0], chain.steps[0])
    state = _with_order(rig.state, order)
    state = state.model_copy(
        update={"pipelines": {**state.pipelines, pid: chain.model_copy(update={"steps": steps})}}
    )
    assert next_wake(state, today).to == today + timedelta(days=2 + 2)


def test_a_step_with_no_length_ahead_adds_no_candidate() -> None:
    rig = Rig()
    rig.start("ada")
    today = rig.start_day - timedelta(days=30)
    order = rig.order(today)
    pid = order.pipeline
    gap = rig.state.pipelines[pid]
    steps = (gap.steps[0], gap.steps[1].model_copy(update={"days": None}))
    state = _with_order(rig.state, order)
    state = state.model_copy(
        update={"pipelines": {**state.pipelines, pid: gap.model_copy(update={"steps": steps})}}
    )
    assert next_wake(state, today).reason.what == "horizon"


def test_autumn_1941_first_wake_is_the_greer_event() -> None:
    rig = Rig("autumn-1941")
    rig.start("roosevelt")
    today = date(1941, 9, 1)
    wake = next_wake(rig.state, today)
    assert wake.to == date(1941, 9, 4)
    assert wake.reason.what == "history"
    assert wake.collapsed_days == 2


def test_a_past_due_candidate_clamps_to_tomorrow() -> None:
    rig = Rig()
    rig.start("ada")
    today = rig.start_day - timedelta(days=30)
    stale = rig.order(today - timedelta(days=10))
    wake = next_wake(_with_order(rig.state, stale), today)
    assert wake.to == today + timedelta(days=1)
    assert wake.reason.what == "step"
    assert wake.collapsed_days == 0


def test_the_same_state_and_day_give_an_equal_wake() -> None:
    rig = Rig()
    rig.start("ada", "bram")
    today = rig.start_day - timedelta(days=30)
    assert next_wake(rig.state, today) == next_wake(replay(rig.events), today)
