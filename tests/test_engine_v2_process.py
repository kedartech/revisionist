"""Engine v2, unit B5: process parts open pipelines, influence parts are decided by
their target (spec §8.2)."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.fold import replay, state_hash
from revisionist.core.ids import CampaignId, EntityId, QuantityId, SeatId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.realism import process
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import ON_ORDER, Change, resolver_for, votes
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick as rt
from revisionist.engine import session_zero
from revisionist.engine.store import MemoryStore, load_state
from tests.test_engine_v2_contract import CAMPAIGN
from tests.test_realism_bands import SEEDS

FAR = date(1942, 1, 1)
HISTORICAL = votes.HISTORICAL["neutrality_revision"]
NOVEL = rx.ProposeMeasure(
    title="Arm the convoys, within limits",
    clauses=(
        *HISTORICAL.clauses,
        rx.Clause(kind=rx.ClauseKind.LIMIT, subject="no convoys past Iceland"),
    ),
)


def _world(**wheeler: object) -> WorldFile:
    """The slice, with the neutrality vote quantities from autumn 1941 and Wheeler's
    card changed by ``wheeler``."""
    world = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
    autumn = cmp.load_world(cmp.world_path("autumn-1941"))
    counts = tuple(q for q in autumn.quantities if q.key.startswith("neutrality_revision_"))
    cards = tuple(c.model_copy(update=wheeler) if c.person == "wheeler" else c for c in world.cards)
    return world.model_copy(update={"quantities": (*world.quantities, *counts), "cards": cards})


def _entity(cid: CampaignId, key: str) -> EntityId:
    return EntityId(derived_id(cid, "entity", key))


def _seated(
    cid: CampaignId = CAMPAIGN, *, human_wheeler: bool = False, **wheeler: object
) -> tuple[MemoryStore, SeatId]:
    store = MemoryStore()
    store.append_all(compile_world(_world(**wheeler), cid, cmp.versions()))
    if human_wheeler:
        name = load_state(store, cid).entities[_entity(cid, "wheeler")].name
        session_zero.claim(
            store, cid, SeatId(derived_id(cid, "seat", _entity(cid, "wheeler"))), name
        )
    rt.seat_player(store, cid, _entity(cid, "roosevelt"))
    (fdr,) = [
        s.seat_id
        for s in load_state(store, cid).seats.values()
        if s.embodies == _entity(cid, "roosevelt")
    ]
    return store, fdr


def _payloads[T: ev.Payload](store: MemoryStore, cid: CampaignId, kind: type[T]) -> list[T]:
    return [e.payload for e in store.read(cid) if isinstance(e.payload, kind)]


def _estimate(
    store: MemoryStore, cid: CampaignId, seat: SeatId, order: rx.RoutedOrder, *effects: rx.Effect
) -> None:
    payload = ev.EffectsEstimated(
        order_id=order.order_id, part=0, effects=effects, reason="Wheeler may be moved."
    )
    rt._append(store, load_state(store, cid), payload, seat, private_to(seat))


def _enacted(order: Order) -> Order:
    return order.model_copy(update={"status": OrderStatus.ENACTED})


# --- process ----------------------------------------------------------------------


def _measure(store: MemoryStore, fdr: SeatId, measure: rx.ProposeMeasure) -> rx.RoutedOrder:
    return rt.commit_order(store, CAMPAIGN, fdr, [Ask(ask="Revise the act.", effect=measure)])


def test_a_measure_routes_process_and_drafts_one_pipeline_order() -> None:
    store, fdr = _seated()
    routed = _measure(store, fdr, HISTORICAL)
    (part,) = routed.parts
    assert part.route is rx.Route.PROCESS
    state = load_state(store, CAMPAIGN)
    assert part.pipeline == state.cards[_entity(CAMPAIGN, "roosevelt")].pipelines[0]
    today = routed.filed
    (drafted,) = process.open_processes(state, today)
    assert isinstance(drafted, ev.OrderDrafted)
    order = drafted.order
    assert order.routed_from == rx.PartRef(order_id=routed.order_id, part=0)
    assert order.measure == HISTORICAL and order.lever == "measure" and order.params == {}
    assert (order.issuer, order.filed, order.pipeline) == (fdr, routed.filed, part.pipeline)


def test_an_opened_process_is_not_opened_again() -> None:
    store, fdr = _seated()
    routed = _measure(store, fdr, HISTORICAL)
    (drafted,) = process.open_processes(load_state(store, CAMPAIGN), routed.filed)
    assert isinstance(drafted, ev.OrderDrafted)
    rt._append(store, load_state(store, CAMPAIGN), drafted, fdr)
    assert process.open_processes(load_state(store, CAMPAIGN), routed.filed) == []


def _drafted(measure: rx.ProposeMeasure) -> tuple[State, Order]:
    store, fdr = _seated()
    routed = _measure(store, fdr, measure)
    state = load_state(store, CAMPAIGN)
    (drafted,) = process.open_processes(state, routed.filed)
    assert isinstance(drafted, ev.OrderDrafted)
    return state, drafted.order


def test_an_enacted_measure_is_tallied_as_the_legacy_bill_is() -> None:
    state, order = _drafted(HISTORICAL)
    assert resolver_for(state, order) == "votes"
    legacy = order.model_copy(
        update={
            "lever": votes.LEVER,
            "params": {"bill": "neutrality_revision"},
            "measure": None,
            "routed_from": None,
        }
    )
    carried = ON_ORDER["votes"](state, _enacted(order))
    assert carried and carried == votes.resolve(state, _enacted(legacy))
    assert ON_ORDER["votes"](state, order) == ()


def _values(changes: tuple[Change, ...]) -> dict[QuantityId, int | None]:
    return {c.quantity_id: c.value for c in changes if isinstance(c, QuantityChange)}


def test_a_novel_measure_counts_differently_and_deterministically() -> None:
    state, order = _drafted(NOVEL)
    _, known = _drafted(HISTORICAL)
    novel = ON_ORDER["votes"](state, _enacted(order))
    again = ON_ORDER["votes"](state, _enacted(order))
    assert novel == again
    historical = ON_ORDER["votes"](
        state, _enacted(known.model_copy(update={"order_id": order.order_id}))
    )
    assert _values(novel).keys() == _values(historical).keys()
    assert _values(novel) != _values(historical)


def test_a_process_order_runs_its_pipeline_and_enacts() -> None:
    store, fdr = _seated()
    routed = _measure(store, fdr, HISTORICAL)
    for _ in range(3):
        rt.run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    (order,) = [o for o in state.orders.values() if o.routed_from is not None]
    assert order.routed_from == rx.PartRef(order_id=routed.order_id, part=0)
    assert order.outcomes and order.outcomes[0].person == _entity(CAMPAIGN, "rayburn")


# --- influence --------------------------------------------------------------------


def _ask_wheeler(store: MemoryStore, cid: CampaignId, fdr: SeatId) -> rx.RoutedOrder:
    ask = Ask(ask="Ask Wheeler to back the convoys.", target=_entity(cid, "wheeler"))
    return rt.commit_order(store, cid, fdr, [ask])


def _decisions(store: MemoryStore, cid: CampaignId) -> list[ev.InfluenceDecided]:
    return _payloads(store, cid, ev.InfluenceDecided)


def _war(cid: CampaignId, state: State) -> rx.SetEngagement:
    fleet = state.cards[_entity(cid, "roosevelt")].authority[0].forces[0]
    return rx.SetEngagement(force=fleet, zone="western Atlantic", rule=rx.Engagement.SHOOT_ON_SIGHT)


def test_wheeler_turns_down_a_war_ask_after_the_transit_delay() -> None:
    rejected = 0
    for cid in SEEDS:
        store, fdr = _seated(cid)
        routed = _ask_wheeler(store, cid, fdr)
        assert routed.parts[0].route is rx.Route.INFLUENCE
        _estimate(store, cid, fdr, routed, _war(cid, load_state(store, cid)))
        state = load_state(store, cid)
        assert process.influence_due(state, routed.filed - timedelta(days=1)) == []
        rt.run_realism_tick(store, cid)
        (decided,) = _decisions(store, cid)
        assert decided.order_id == routed.order_id and decided.part == 0
        assert decided.on >= routed.filed
        rejected += not decided.accepted
        assert decided.reason.startswith("Burton K. Wheeler")
        assert "_" not in decided.reason and len(decided.reason) < 300
        assert routed.order_id not in decided.reason
    assert rejected >= 8


def test_wheeler_goes_along_when_loyal_and_given_leverage() -> None:
    for cid in SEEDS:
        store, fdr = _seated(cid, loyalty=5, principals=("senate", "roosevelt"))
        routed = _ask_wheeler(store, cid, fdr)
        wheeler, roosevelt = _entity(cid, "wheeler"), _entity(cid, "roosevelt")
        shift = rx.ShiftDisposition(of=wheeler, toward=roosevelt, change=2)
        _estimate(store, cid, fdr, routed, shift)
        rt.run_realism_tick(store, cid)
        (decided,) = _decisions(store, cid)
        assert decided.accepted and "agreed" in decided.reason


def test_a_target_a_human_holds_is_never_decided_by_code() -> None:
    store, fdr = _seated(human_wheeler=True)
    _ask_wheeler(store, CAMPAIGN, fdr)
    rt.run_realism_tick(store, CAMPAIGN)
    rt.run_realism_tick(store, CAMPAIGN)
    assert _decisions(store, CAMPAIGN) == []


def test_influence_is_decided_once_deterministically_and_replays() -> None:
    first, fdr = _seated()
    _ask_wheeler(first, CAMPAIGN, fdr)
    second = MemoryStore()
    second.append_all(list(first.read(CAMPAIGN)))
    for store in (first, second):
        rt.run_realism_tick(store, CAMPAIGN)
        rt.run_realism_tick(store, CAMPAIGN)
        assert len(_decisions(store, CAMPAIGN)) == 1
        state = load_state(store, CAMPAIGN)
        assert process.influence_due(state, state.in_world_date or FAR) == []
        assert state_hash(replay(list(store.read(CAMPAIGN)))) == state_hash(state)
    assert _decisions(first, CAMPAIGN) == _decisions(second, CAMPAIGN)
