"""The shared wake (engine v2, spec §4, decision 41).

One wake for the whole table: it opens, each seat commits, and it closes when all
have committed or at the deadline, the aide playing any seat that has not.
"""

import logging
from datetime import datetime, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EventId, SeatId
from revisionist.core.ontology import Controller
from revisionist.core.realism.agenda import STANDING_DEFAULT, Ask
from revisionist.core.realism.effect import IRREVERSIBLE
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.engine import campaign as cmp
from revisionist.engine import options, realism_tick
from revisionist.engine.ids import new_id
from revisionist.engine.llm import Transport
from revisionist.engine.store import EventStore, load_state

log = logging.getLogger(__name__)


def _land(
    store: EventStore, state: State, payload: ev.Payload, actor: SeatId | None = None
) -> None:
    store.append_all(
        [
            ev.Event(
                event_id=EventId(new_id()),
                campaign_id=state.campaign_id,
                seq=state.last_seq + 1,
                tick=state.tick,
                actor=actor,
                scope=PUBLIC,
                payload=payload,
                versions=cmp.versions(),
            )
        ]
    )


def _open(state: State) -> bool:
    return state.wake is not None and not state.wake.closed


def open_wake(store: EventStore, campaign_id: CampaignId, now: datetime) -> int:
    """Open the next wake; returns its number. Raises ``ValueError`` while one is open."""
    state = load_state(store, campaign_id)
    if _open(state):
        assert state.wake is not None
        raise ValueError(f"wake {state.wake.number} is still open")
    number = 0 if state.wake is None else state.wake.number + 1
    deadline = now + timedelta(hours=state.settings.wake_hours)
    _land(store, state, ev.WakeOpened(wake=number, deadline=deadline))
    return number


def commit(store: EventStore, campaign_id: CampaignId, seat: SeatId, now: datetime) -> bool:
    """Seal ``seat``'s orders for the open wake; False if it already had or none is open."""
    state = load_state(store, campaign_id)
    held = state.seats.get(seat)
    if held is None or held.controller is not Controller.HUMAN:
        raise ValueError(f"seat {seat} is not a human seat")
    wake = state.wake
    if wake is None or wake.closed or seat in wake.committed:
        return False
    _land(store, state, ev.WakeCommitted(wake=wake.number, seat_id=seat), seat)
    return True


def wake_due(state: State, now: datetime) -> bool:
    """Every human seat has committed, or the deadline is at or before ``now``."""
    wake = state.wake
    if wake is None or wake.closed:
        return False
    humans = {s.seat_id for s in state.seats.values() if s.controller is Controller.HUMAN}
    return wake.deadline <= now or (bool(humans) and humans <= wake.committed)


def _allowed(state: State, seat: SeatId, order: tuple[Ask, ...]) -> tuple[Ask, ...]:
    """The aide never takes an irreversible step without a standing order naming it."""
    standing = state.standing.get(seat, STANDING_DEFAULT)
    return tuple(
        a
        for a in order
        if a.effect is None or a.effect.kind not in IRREVERSIBLE or a.effect.kind in standing
    )


def close_wake(
    store: EventStore, campaign_id: CampaignId, now: datetime, transport: Transport | None
) -> tuple[SeatId, ...]:
    """Close the open wake; the aide plays each human seat that has not committed.

    Returns those seats, in seat-id order.
    """
    state = load_state(store, campaign_id)
    wake = state.wake
    if wake is None or wake.closed:
        return ()
    absent = tuple(s for s in cmp.human_seats(state) if s not in wake.committed)
    for seat in absent:
        state = load_state(store, campaign_id)
        for order in options.aide_asks(state, seat, transport):
            asks = _allowed(state, seat, order)
            if not asks:
                continue
            try:
                realism_tick.commit_order(store, campaign_id, seat, asks)
            except ValueError as exc:
                log.warning("aide order for %s dropped: %s", seat, exc)
        _land(
            store,
            load_state(store, campaign_id),
            ev.WakeCommitted(wake=wake.number, seat_id=seat, by_aide=True),
            seat,
        )
    _land(store, load_state(store, campaign_id), ev.WakeClosed(wake=wake.number, timed_out=absent))
    return absent


__all__ = ["close_wake", "commit", "open_wake", "wake_due"]
