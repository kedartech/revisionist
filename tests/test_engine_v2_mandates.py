"""The agenda (engine v2, spec §8.5): templates issue private mandates when their
triggers fire, live mandates settle, the cap and the seeded choice hold."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.goals import Ordered
from revisionist.core.ids import EntityId, MandateId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import agenda as ra
from revisionist.core.realism import effect as rx
from revisionist.core.realism import mandates
from revisionist.core.realism.resolvers import friction
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick as rt
from revisionist.engine import session_zero
from revisionist.engine.store import MemoryStore, load_state
from tests.test_engine_v2_contract import CAMPAIGN, Slice
from tests.test_engine_v2_contract_b import (
    FILED,
    _applied,
    _decided,
    _executed,
    _influence,
    _order,
    _routed,
)

GREER = date(1941, 9, 4)


def _fire(sl: Slice, key: str) -> None:
    sl.add(ev.ScheduledEventFired(scheduled_id=sl.ids[key]))


def _issued(state: State, today: date) -> list[ra.Mandate]:
    return [p.mandate for p in mandates.issue_due(state, today) if isinstance(p, ev.MandateIssued)]


def _play(max_date: date = date(1941, 9, 5)) -> tuple[MemoryStore, State]:
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    ids = resolve_keys(decl, CAMPAIGN)
    for who in ("roosevelt", "churchill"):
        name = load_state(store, CAMPAIGN).entities[EntityId(ids[who])].name
        session_zero.claim(store, CAMPAIGN, SeatId(derived_id(CAMPAIGN, "seat", ids[who])), name)
    rt.open_play(store, CAMPAIGN)
    while (load_state(store, CAMPAIGN).in_world_date or max_date) < max_date:
        rt.run_realism_tick(store, CAMPAIGN)
    return store, load_state(store, CAMPAIGN)


def _mandate_events(store: MemoryStore) -> list[str]:
    return [
        e.payload.model_dump_json()
        for e in store.read(CAMPAIGN)
        if isinstance(e.payload, ev.MandateIssued | ev.MandateSettled)
    ]


def _statement_applied(sl: Slice, n: int = 9) -> None:
    said = rx.MakeStatement(theme="convoys")
    order = _routed(sl, _order(sl, n, _influence(sl, said)))
    sl.add(_decided(order.order_id), private_to(sl.fdr))
    sl.add(_applied(order.order_id), private_to(sl.fdr))


def test_history_templates_reach_their_own_seats_privately() -> None:
    _, state = _play()
    by_key = {m.mandate_id: m for m in state.mandates.values()}
    assert len(by_key) == 2
    roosevelt = next(m for m in by_key.values() if m.kind is ra.MandateKind.CRISIS)
    churchill = next(m for m in by_key.values() if m.kind is ra.MandateKind.ORDER)
    assert state.seats[roosevelt.seat_id].name != state.seats[churchill.seat_id].name
    assert roosevelt.expires == GREER + timedelta(days=14) and roosevelt.issuer is None
    assert churchill.expires == GREER + timedelta(days=10)
    assert churchill.issuer == state.templates["commons_convoys"].issuer
    assert roosevelt.scope == private_to(roosevelt.seat_id)
    assert roosevelt.mandate_id in project(state, roosevelt.seat_id).mandates
    assert roosevelt.mandate_id not in project(state, churchill.seat_id).mandates
    assert churchill.mandate_id not in project(state, roosevelt.seat_id).mandates


def test_two_runs_log_identical_mandate_events() -> None:
    (a, _), (b, _) = _play(), _play()
    assert _mandate_events(a) == _mandate_events(b) != []


def test_a_shot_on_sight_order_brings_its_blowback_to_its_issuer() -> None:
    sl = Slice()
    order = _executed(sl)
    sl.add(_applied(order.order_id), private_to(sl.fdr))
    [m] = _issued(sl.state, FILED)
    assert m.kind is ra.MandateKind.BLOWBACK and m.seat_id == sl.fdr
    assert m.cause == order.order_id and m.scope == private_to(sl.fdr)
    assert m.expires == FILED + timedelta(days=7)
    assert _issued(sl.state, FILED + timedelta(days=1)) == []


def test_an_order_applied_on_an_earlier_day_is_no_trigger() -> None:
    sl = Slice()
    order = _executed(sl)
    sl.add(_applied(order.order_id), private_to(sl.fdr))
    assert _issued(sl.state, FILED + timedelta(days=1)) == []


def test_a_template_reaches_a_seat_once() -> None:
    sl = Slice()
    _fire(sl, "greer_incident")
    [first] = _issued(sl.state, GREER)
    sl.add(ev.MandateIssued(mandate=first), private_to(sl.fdr))
    assert _issued(sl.state, GREER) == []
    settled = mandates.settle_due(sl.state, first.expires)
    sl.add(settled[0])
    assert _issued(sl.state, GREER) == []


def test_mandates_settle_met_or_at_expiry_by_kind() -> None:
    sl = Slice()
    seat = sl.fdr
    kinds = {
        1: (ra.MandateKind.CRISIS, ra.MandateStatus.FAILED),
        2: (ra.MandateKind.BLOWBACK, ra.MandateStatus.EXPIRED),
        3: (ra.MandateKind.OPPORTUNITY, ra.MandateStatus.EXPIRED),
    }
    for n, (kind, _) in kinds.items():
        extra: dict[str, object] = {"kind": kind}
        if kind is ra.MandateKind.BLOWBACK:
            extra["cause"] = _executed(sl).order_id
        sl.add(
            ev.MandateIssued(
                mandate=sl.mandate(
                    n,
                    seat,
                    condition=Ordered(person=sl.entity("roosevelt"), effect=rx.EffectKind.DEAL),
                    **extra,
                )
            ),
            private_to(seat),
        )
    live = sl.state
    expires = next(iter(live.mandates.values())).expires
    assert mandates.settle_due(live, expires - timedelta(days=1)) == []
    got = {
        p.mandate_id: p.status
        for p in mandates.settle_due(live, expires)
        if isinstance(p, ev.MandateSettled)
    }
    for n, (_, status) in kinds.items():
        assert got[MandateId(derived_id(CAMPAIGN, "mandate", n))] is status


def test_an_order_mandate_fails_at_expiry_and_is_met_when_done() -> None:
    sl = Slice()
    condition = Ordered(person=sl.entity("roosevelt"), effect=rx.EffectKind.STATEMENT)
    for n in (1, 2):
        sl.add(
            ev.MandateIssued(
                mandate=sl.mandate(
                    n,
                    sl.fdr,
                    kind=ra.MandateKind.ORDER,
                    issuer=sl.entity("wheeler"),
                    condition=condition,
                )
            ),
            private_to(sl.fdr),
        )
    state = sl.state
    day = state.mandates[next(iter(state.mandates))].expires
    assert {
        p.status for p in mandates.settle_due(state, day) if isinstance(p, ev.MandateSettled)
    } == {ra.MandateStatus.FAILED}
    _statement_applied(sl)
    met = mandates.settle_due(sl.state, FILED)
    assert [p.status for p in met if isinstance(p, ev.MandateSettled)] == [ra.MandateStatus.MET] * 2


def test_a_freed_slot_is_refilled_after_settling_and_the_cap_holds() -> None:
    sl = Slice()
    greer = sl.state.templates["greer_response"]
    extras = [greer.model_copy(update={"key": f"extra_{n}"}) for n in range(3)]
    sl.add(ev.CardsDeclared(templates=tuple(extras)))
    _fire(sl, "greer_incident")
    got = _issued(sl.state, GREER)
    assert len(got) == ra.MANDATE_CAP == 3
    keys = sorted(
        ("greer_response", *(t.key for t in extras)),
        key=lambda k: (friction(sl.state, k, sl.fdr, GREER, n=1000), k),
    )
    chosen = keys[:3]
    assert sorted(m.mandate_id for m in got) == sorted(
        MandateId(derived_id(CAMPAIGN, "mandate", k, sl.fdr)) for k in chosen
    )
    assert [m.mandate_id for m in _issued(sl.state, GREER)] == [m.mandate_id for m in got]
    for m in got:
        sl.add(ev.MandateIssued(mandate=m), private_to(sl.fdr))
    assert _issued(sl.state, GREER) == []
    _fire(sl, "arms_window")
    assert _issued(sl.state, date(1941, 9, 20)) == []
    replay(sl.events)


def test_score_follows_the_table() -> None:
    sl = Slice()
    condition = Ordered(person=sl.entity("roosevelt"), effect=rx.EffectKind.DEAL)
    paid = [
        (ra.MandateKind.ORDER, ra.MandateStatus.MET, 2),
        (ra.MandateKind.CRISIS, ra.MandateStatus.MET, 1),
        (ra.MandateKind.ORDER, ra.MandateStatus.FAILED, -2),
        (ra.MandateKind.CRISIS, ra.MandateStatus.FAILED, -1),
        (ra.MandateKind.OPPORTUNITY, ra.MandateStatus.EXPIRED, 0),
    ]
    state = sl.state
    for n, (kind, status, _) in enumerate(paid):
        m = sl.mandate(
            n,
            sl.fdr,
            kind=kind,
            condition=condition,
            status=status,
            issuer=sl.entity("wheeler") if kind is ra.MandateKind.ORDER else None,
        )
        state = state.model_copy(update={"mandates": {**state.mandates, m.mandate_id: m}})
        assert mandates.score(state, sl.fdr) == sum(p for *_, p in paid[: n + 1])
    assert mandates.score(state, sl.wheeler) == 0
