"""The shared wake (engine v2, unit B1): open, commit, close, the aide, the clock."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.goals import AnyOf, Ordered, WinCondition
from revisionist.core.ids import (
    CampaignId,
    EntityId,
    EventId,
    FeatureId,
    MandateId,
    OrderId,
    SeatId,
    derived_id,
)
from revisionist.core.realism import effect as rx
from revisionist.core.realism.advance import next_wake
from revisionist.core.realism.agenda import Ask, Mandate, MandateKind, Option, PlayStyle
from revisionist.core.realism.effect import EffectKind
from revisionist.core.resolution import TickStage
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import options, realism_tick, runner, scheduler, session_zero, wake
from revisionist.engine.llm import Reply, Request
from revisionist.engine.store import EventStore, MemoryStore, SqliteStore, load_state
from tests.test_engine_v2_contract import Slice

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
T0 = datetime(2026, 11, 1, 12, tzinfo=UTC)
WORLD = "engine-v2-slice-1941"


class Table:
    """The slice with Roosevelt and Churchill both seated and play open."""

    def __init__(self, store: EventStore, *, churchill: bool = True) -> None:
        self.store = store
        decl = cmp.load_world(cmp.world_path(WORLD))
        self.ids = resolve_keys(decl, CAMPAIGN)
        store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
        self.fdr = self.claim("roosevelt", "Roosevelt")
        self.winston = self.claim("churchill", "Churchill") if churchill else None
        realism_tick.open_play(store, CAMPAIGN)

    def claim(self, key: str, name: str) -> SeatId:
        seat = SeatId(derived_id(CAMPAIGN, "seat", self.ids[key]))
        session_zero.claim(self.store, CAMPAIGN, seat, name)
        return seat

    def entity(self, key: str) -> EntityId:
        return EntityId(self.ids[key])

    @property
    def state(self) -> State:
        return load_state(self.store, CAMPAIGN)

    def shoot_on_sight(self) -> Ask:
        effect = rx.SetEngagement(
            force=FeatureId(self.ids["us_atlantic_fleet"]),
            zone="western Atlantic",
            rule=rx.Engagement.SHOOT_ON_SIGHT,
        )
        return Ask(ask="shoot on sight in the western Atlantic", effect=effect, target=None)

    def aide_orders(self) -> list[tuple[Ask, ...]]:
        move = rx.MoveForce(
            force=FeatureId(self.ids["home_fleet"]),
            to=self.entity("scapa_flow"),
            posture=rx.Posture.ESCORT,
        )
        sack = rx.Appointment(person=self.entity("pound"), office="First Sea Lord", appoint=False)
        return [
            (Ask(ask="keep the Home Fleet escorting", effect=move, target=None),),
            (Ask(ask="replace the First Sea Lord", effect=sack, target=None),),
        ]

    def payloads[P: ev.Payload](self, kind: type[P]) -> list[P]:
        return [e.payload for e in self.store.read(CAMPAIGN) if isinstance(e.payload, kind)]


def play(table: Table, tmp_path: Path, now: datetime) -> runner.TickRun:
    return runner.play_tick(
        table.store,
        CAMPAIGN,
        offline=True,
        transport_factory=cmp.live_transport,
        briefings=tmp_path,
        warn=lambda _m: None,
        now=now,
    )


def test_open_then_commit_once() -> None:
    t = Table(MemoryStore())
    assert wake.commit(t.store, CAMPAIGN, t.fdr, T0) is False  # nothing open yet
    assert wake.open_wake(t.store, CAMPAIGN, T0) == 0
    with pytest.raises(ValueError, match="still open"):
        wake.open_wake(t.store, CAMPAIGN, T0)
    opened = t.state.wake
    assert opened is not None and opened.deadline == T0 + timedelta(hours=12)
    assert wake.commit(t.store, CAMPAIGN, t.fdr, T0) is True
    assert wake.commit(t.store, CAMPAIGN, t.fdr, T0) is False
    assert t.state.wake is not None and t.state.wake.committed == {t.fdr}


def test_commit_refuses_a_seat_that_is_not_human() -> None:
    t = Table(MemoryStore())
    wake.open_wake(t.store, CAMPAIGN, T0)
    stranger = SeatId(derived_id(CAMPAIGN, "seat", "nobody"))
    with pytest.raises(ValueError, match="not a human"):
        wake.commit(t.store, CAMPAIGN, stranger, T0)


def test_wake_is_due_when_all_commit_or_at_the_deadline() -> None:
    t = Table(MemoryStore())
    wake.open_wake(t.store, CAMPAIGN, T0)
    deadline = T0 + timedelta(hours=12)
    assert not wake.wake_due(t.state, T0)
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)
    assert not wake.wake_due(t.state, deadline - timedelta(seconds=1))
    assert wake.wake_due(t.state, deadline)
    assert t.winston is not None
    wake.commit(t.store, CAMPAIGN, t.winston, T0)
    assert wake.wake_due(t.state, T0)


def test_a_solo_game_closes_on_commit() -> None:
    t = Table(MemoryStore(), churchill=False)
    wake.open_wake(t.store, CAMPAIGN, T0)
    assert not wake.wake_due(t.state, T0)
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)
    assert wake.wake_due(t.state, T0)


def test_band_w_the_shared_wake_closes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t = Table(SqliteStore(tmp_path / "w.db"))
    assert t.winston is not None
    filed: list[Sequence[Ask]] = []
    real = realism_tick.commit_order

    def spy(store: EventStore, cid: CampaignId, seat: SeatId, asks: Sequence[Ask]):  # type: ignore[no-untyped-def]
        if seat == t.winston:
            filed.append(asks)
        return real(store, cid, seat, asks)

    monkeypatch.setattr(options, "aide_asks", lambda s, seat, tr: t.aide_orders())
    monkeypatch.setattr(realism_tick, "commit_order", spy)

    now = T0
    play(t, tmp_path, now)  # no wake yet: the tick runs, then wake 0 opens
    for n in range(3):
        wk = t.state.wake
        assert wk is not None and wk.number == n and not wk.closed
        realism_tick.commit_order(t.store, CAMPAIGN, t.fdr, [t.shoot_on_sight()])
        assert wake.commit(t.store, CAMPAIGN, t.fdr, now)
        assert not wake.wake_due(t.state, wk.deadline - timedelta(minutes=1))
        now = wk.deadline
        play(t, tmp_path, now)
        (closed,) = [p for p in t.payloads(ev.WakeClosed) if p.wake == n]
        assert closed.timed_out == (t.winston,)
        by_aide = [p for p in t.payloads(ev.WakeCommitted) if p.wake == n]
        assert [(p.seat_id, p.by_aide) for p in by_aide] == [(t.fdr, False), (t.winston, True)]
    assert len(filed) == 3
    assert all(not isinstance(a.effect, rx.Appointment) for order in filed for a in order), (
        "no appointment without a standing order"
    )
    assert all(isinstance(a.effect, rx.MoveForce) for order in filed for a in order)

    # with the standing order, the appointment is filed (routing may refuse it; the aide tried)
    t.store.append_all(
        [
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "style")),
                campaign_id=CAMPAIGN,
                seq=t.state.last_seq + 1,
                tick=t.state.tick,
                scope=private_to(t.winston),
                payload=ev.PlayStyleSet(
                    seat_id=t.winston,
                    style=PlayStyle.FREE,
                    standing=frozenset({rx.EffectKind.APPOINTMENT}),
                ),
                versions=cmp.versions(),
            )
        ]
    )
    filed.clear()
    wk = t.state.wake
    assert wk is not None
    wake.commit(t.store, CAMPAIGN, t.fdr, now)
    play(t, tmp_path, wk.deadline)
    assert any(isinstance(a.effect, rx.Appointment) for order in filed for a in order)


def test_all_committed_closes_before_the_deadline_and_the_scheduler_follows(
    tmp_path: Path,
) -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    play(t, tmp_path, T0)
    state = t.state
    assert state.wake is not None
    tail = list(t.store.read(CAMPAIGN))
    assert not scheduler.all_submitted(state, scheduler.since_last_close(tail))
    row = scheduler.Schedule(CAMPAIGN, next_due_at=T0 - timedelta(days=1))
    # the schedule's own timer has passed, but the wake deadline is the timer
    timer = replace(row, next_due_at=state.wake.deadline)
    assert scheduler.due(timer, T0, in_flight=False, submitted=False) is None
    assert scheduler.due(timer, state.wake.deadline, in_flight=False, submitted=False)
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)
    assert not scheduler.all_submitted(t.state, [])
    wake.commit(t.store, CAMPAIGN, t.winston, T0)
    assert scheduler.all_submitted(t.state, [])
    before = t.state.wake
    play(t, tmp_path, T0 + timedelta(hours=1))
    after = t.state.wake
    assert before is not None and after is not None and after.number == before.number + 1
    assert t.payloads(ev.WakeClosed)[-1] == ev.WakeClosed(wake=before.number, how="all_committed")


def test_next_wake_stops_at_a_live_mandate_expiry() -> None:
    sl = Slice()
    today = date(1941, 9, 11)
    quiet = next_wake(sl.state, today)
    assert quiet.reason.what != "agenda"
    due_on = today + timedelta(days=2)
    sl.add(
        ev.MandateIssued(
            mandate=sl.mandate(
                1, sl.fdr, issued=today, expires=due_on, text="Keep the convoys moving."
            )
        ),
        private_to(sl.fdr),
    )
    found = next_wake(sl.state, today)
    assert found.to == due_on
    assert found.reason.what == "agenda"
    assert found.reason.label == "Keep the convoys moving., due"


# --- The wake record (WRC): when it opened, each commit's time, how it closed ---------


def _events_of(t: Table, kind: type[ev.Payload]) -> list[ev.Event]:
    return [e for e in t.store.read(CAMPAIGN) if isinstance(e.payload, kind)]


def test_the_record_times_the_opening_and_each_commit() -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    wake.open_wake(t.store, CAMPAIGN, T0)
    wake.commit(t.store, CAMPAIGN, t.fdr, T0 + timedelta(minutes=5))
    wake.commit(t.store, CAMPAIGN, t.winston, T0 + timedelta(hours=3))
    (opened,) = t.payloads(ev.WakeOpened)
    assert opened.opened_at == T0
    assert [(p.seat_id, p.at, p.aide_orders) for p in t.payloads(ev.WakeCommitted)] == [
        (t.fdr, T0 + timedelta(minutes=5), ()),
        (t.winston, T0 + timedelta(hours=3), ()),
    ]


def test_a_wake_closes_all_committed_when_every_human_has() -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    wake.open_wake(t.store, CAMPAIGN, T0)
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)
    wake.commit(t.store, CAMPAIGN, t.winston, T0)
    wake.close_wake(t.store, CAMPAIGN, T0 + timedelta(hours=1), None)
    assert [p.how for p in t.payloads(ev.WakeClosed)] == ["all_committed"]


def test_a_wake_closes_by_deadline_once_it_has_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    t = Table(MemoryStore())
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: [])
    wake.open_wake(t.store, CAMPAIGN, T0)
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)
    wake.close_wake(t.store, CAMPAIGN, T0 + timedelta(hours=12), None)
    assert [p.how for p in t.payloads(ev.WakeClosed)] == ["deadline"]


def test_a_wake_closed_early_with_a_seat_out_is_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = Table(MemoryStore())
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: [])
    wake.open_wake(t.store, CAMPAIGN, T0)
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)
    wake.close_wake(t.store, CAMPAIGN, T0 + timedelta(hours=12) - timedelta(seconds=1), None)
    assert [p.how for p in t.payloads(ev.WakeClosed)] == ["host"]


def test_the_aides_commit_is_sealed_to_its_owner_and_names_its_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: t.aide_orders())
    wake.open_wake(t.store, CAMPAIGN, T0)
    before = set(t.state.routed)
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)
    closed_at = T0 + timedelta(hours=12)
    wake.close_wake(t.store, CAMPAIGN, closed_at, None)
    filed = tuple(
        o.order_id
        for o in t.state.routed.values()
        if o.issuer == t.winston and o.order_id not in before
    )
    assert filed, "the aide filed for Churchill"
    (mine, aide) = _events_of(t, ev.WakeCommitted)
    assert mine.scope == PUBLIC and mine.payload == ev.WakeCommitted(wake=0, seat_id=t.fdr, at=T0)
    assert aide.payload == ev.WakeCommitted(
        wake=0, seat_id=t.winston, by_aide=True, at=closed_at, aide_orders=filed
    )
    assert aide.scope == private_to(t.winston)
    assert aide.scope.visible_to(t.winston) and not aide.scope.visible_to(t.fdr)
    # the close stays public: the fold still sees both seats committed
    (close,) = _events_of(t, ev.WakeClosed)
    assert close.scope == PUBLIC
    assert close.payload == ev.WakeClosed(wake=0, timed_out=(t.winston,), how="deadline")
    assert t.state.wake is not None and t.state.wake.committed == {t.fdr, t.winston}


# --- The aide is bounded (ABD): no deal accepted, offers lapse ---------------------


def _deal(t: Table, *, accept: bool) -> Ask:
    terms = rx.Deal(
        counterparty=t.entity("roosevelt"),
        accept=accept,
        offer=() if accept else ("bases in the West Indies",),
    )
    return Ask(ask=f"{'accept' if accept else 'offer'} a deal with the President", effect=terms)


def _say(theme: str) -> Ask:
    return Ask(ask=f"Say plainly: {theme}", effect=rx.MakeStatement(theme=theme))


def _opening(t: Table, text: str, condition: WinCondition) -> MandateId:
    """A mandate put to Churchill's seat with the given condition, live for ten days."""
    assert t.winston is not None
    state = t.state
    today = state.in_world_date
    assert today is not None
    mandate_id = MandateId(derived_id(CAMPAIGN, "abd-opening", text))
    mandate = Mandate(
        mandate_id=mandate_id,
        seat_id=t.winston,
        kind=MandateKind.OPPORTUNITY,
        text=text,
        condition=condition,
        issued=today,
        expires=today + timedelta(days=10),
        scope=private_to(t.winston),
    )
    t.store.append_all(
        [
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "abd-opening-event", mandate_id)),
                campaign_id=CAMPAIGN,
                seq=state.last_seq + 1,
                tick=state.tick,
                scope=private_to(t.winston),
                payload=ev.MandateIssued(mandate=mandate),
                versions=cmp.versions(),
            )
        ]
    )
    return mandate_id


def _offered_by_mandate(
    monkeypatch: pytest.MonkeyPatch, by_text: dict[str, tuple[Ask, ...]]
) -> list[str]:
    """Each mandate is offered the one option named for its text; returns the
    mandates the aide asked options for."""
    asked: list[str] = []

    def offered(
        state: State, view: object, mandate: Mandate | None, *a: object, **k: object
    ) -> tuple[Option, ...]:
        assert mandate is not None
        asked.append(mandate.text)
        asks = by_text.get(mandate.text, (_say("the convoys"),))
        return (Option(label=f"answer {mandate.text}", asks=asks),)

    monkeypatch.setattr(options, "_options_for", offered)
    return asked


def test_the_aide_files_no_deal_offered_or_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    _opening(
        t,
        "Speak to the Commons.",
        Ordered(person=t.entity("churchill"), effect=EffectKind.STATEMENT),
    )
    both = (_deal(t, accept=True), _deal(t, accept=False), _say("the Commons"))
    _offered_by_mandate(monkeypatch, {"Speak to the Commons.": both})
    filed = [a for order in options.aide_asks(t.state, t.winston, None) for a in order]
    assert _say("the Commons") in filed
    assert [a for a in filed if isinstance(a.effect, rx.Deal)] == []


def test_an_order_that_is_only_a_deal_is_not_filed(monkeypatch: pytest.MonkeyPatch) -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    _opening(
        t,
        "Answer the Americans.",
        Ordered(person=t.entity("churchill"), effect=EffectKind.STATEMENT),
    )
    _offered_by_mandate(monkeypatch, {"Answer the Americans.": (_deal(t, accept=True),)})
    orders = options.aide_asks(t.state, t.winston, None)
    assert orders and all(orders), orders
    assert all(not isinstance(a.effect, rx.Deal) for order in orders for a in order)


@pytest.mark.parametrize("nested", [False, True])
def test_the_aide_leaves_an_opening_met_only_by_a_deal_to_lapse(
    monkeypatch: pytest.MonkeyPatch, nested: bool
) -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    deal: WinCondition = Ordered(person=t.entity("churchill"), effect=EffectKind.DEAL)
    condition: WinCondition = AnyOf(conditions=(deal,)) if nested else deal
    _opening(t, "The Americans offer fifty destroyers.", condition)
    welcome = (_say("the American offer is welcome"),)
    asked = _offered_by_mandate(monkeypatch, {"The Americans offer fifty destroyers.": welcome})
    orders = options.aide_asks(t.state, t.winston, None)
    assert "The Americans offer fifty destroyers." not in asked
    assert asked, "the seat's other mandate is still played"
    assert all(welcome[0] not in order for order in orders)


def test_the_aide_still_plays_a_mandate_met_by_another_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    _opening(
        t,
        "Speak to the Commons.",
        Ordered(person=t.entity("churchill"), effect=EffectKind.STATEMENT),
    )
    asked = _offered_by_mandate(monkeypatch, {})
    options.aide_asks(t.state, t.winston, None)
    assert "Speak to the Commons." in asked


def test_the_close_files_no_deal_whatever_the_aide_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    given = [(_deal(t, accept=True), _say("the convoys")), (_deal(t, accept=False),)]
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: given)
    filed: list[Ask] = []
    real = realism_tick.commit_order

    def spy(store: EventStore, cid: CampaignId, seat: SeatId, asks: Sequence[Ask]) -> object:
        filed.extend(asks)
        return real(store, cid, seat, asks)

    monkeypatch.setattr(realism_tick, "commit_order", spy)
    wake.open_wake(t.store, CAMPAIGN, T0)
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)
    wake.close_wake(t.store, CAMPAIGN, T0 + timedelta(hours=12), None)
    assert filed == [_say("the convoys")]
    (aide,) = [p for p in t.payloads(ev.WakeCommitted) if p.by_aide]
    assert len(aide.aide_orders) == 1, "the aide's commit names the one order it filed"


class _EstimatorSaying:
    """An estimator that rules every part it is asked about as a deal with the President."""

    def __init__(self, t: Table) -> None:
        deal = {
            "kind": "deal",
            "counterparty": t.entity("roosevelt"),
            "accept": False,
            "offer": ["bases in the West Indies"],
            "ask": [],
        }
        self.ruling = {"effects": [deal], "reason": "He takes it as an offer.", "rationale": "x"}
        self.calls = 0

    def call(self, request: Request) -> Reply:
        self.calls += 1
        return Reply(
            output=self.ruling, model="m", input_tokens=1, output_tokens=1, cached_tokens=0, usd=0.0
        )


def _estimated_for(t: Table, order: OrderId) -> list[object]:
    (ruled,) = [p for p in t.payloads(ev.EffectsEstimated) if p.order_id == order]
    return list(ruled.effects)


def test_the_estimator_cannot_hand_the_aide_a_deal(monkeypatch: pytest.MonkeyPatch) -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    ask = Ask(ask="Ask the President to back our course", target=t.entity("roosevelt"))
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: [(ask,)])
    wake.open_wake(t.store, CAMPAIGN, T0)
    wake.commit(t.store, CAMPAIGN, t.fdr, T0)
    wake.close_wake(t.store, CAMPAIGN, T0 + timedelta(hours=12), None)
    (aide,) = [p for p in t.payloads(ev.WakeCommitted) if p.by_aide]
    (order,) = aide.aide_orders
    said = _EstimatorSaying(t)
    realism_tick.run_realism_tick(t.store, CAMPAIGN, stop_after=TickStage.ESTIMATE, estimator=said)
    assert said.calls == 1, "the estimator was asked about the aide's order"
    assert _estimated_for(t, order) == [], "no deal stands on an order the aide filed"


def test_the_estimator_still_rules_a_deal_on_a_players_own_order() -> None:
    t = Table(MemoryStore())
    ask = Ask(ask="Ask the President to back our course", target=t.entity("roosevelt"))
    assert t.winston is not None
    order = realism_tick.commit_order(t.store, CAMPAIGN, t.winston, [ask]).order_id
    said = _EstimatorSaying(t)
    realism_tick.run_realism_tick(t.store, CAMPAIGN, stop_after=TickStage.ESTIMATE, estimator=said)
    (deal,) = _estimated_for(t, order)
    assert isinstance(deal, rx.Deal)
