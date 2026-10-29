"""The shared wake (engine v2, unit B1): open, commit, close, the aide, the clock."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, EventId, FeatureId, SeatId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.realism.advance import next_wake
from revisionist.core.realism.agenda import Ask, PlayStyle
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import options, realism_tick, runner, scheduler, session_zero, wake
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
    assert t.payloads(ev.WakeClosed)[-1] == ev.WakeClosed(wake=before.number)


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
