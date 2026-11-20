"""The shared wake (engine v2, spec §4, decision 41).

One wake for the whole table: it opens, each seat commits, and it closes when all
have committed or at the deadline, the aide playing any seat that has not. A leader
changes hands only at a close: a player who leaves, or one who takes up a leader nobody
plays, counts from the next wake.
"""

import logging
from datetime import date, datetime, timedelta

from revisionist.core import events as ev
from revisionist.core import record
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, EventId, OrderId, SeatId, derived_id
from revisionist.core.ontology import Controller, Phase
from revisionist.core.realism import battle, conference, detect
from revisionist.core.realism.agenda import STANDING_DEFAULT, Ask
from revisionist.core.realism.effect import IRREVERSIBLE, Deal
from revisionist.core.state import State, controller_after, seat_of_person
from revisionist.core.visibility import PUBLIC, Scope, private_to
from revisionist.engine import campaign as cmp
from revisionist.engine import options, realism_tick
from revisionist.engine.ids import new_id
from revisionist.engine.llm import Transport, TransportError
from revisionist.engine.store import EventStore, load_state

log = logging.getLogger(__name__)


def _land(
    store: EventStore,
    state: State,
    payload: ev.Payload,
    actor: SeatId | None = None,
    scope: Scope = PUBLIC,
) -> None:
    """Fold the event on ``state``, then store it: an event the fold refuses raises
    ``FoldError`` here and is never stored, so it cannot stop the game loading."""
    event = ev.Event(
        event_id=EventId(new_id()),
        campaign_id=state.campaign_id,
        seq=state.last_seq + 1,
        tick=state.tick,
        actor=actor,
        scope=scope,
        payload=payload,
        versions=cmp.versions(),
    )
    replay([event], initial=state)
    store.append_all([event])


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
    _land(store, state, ev.WakeOpened(wake=number, deadline=deadline, opened_at=now))
    return number


def offer_all(store: EventStore, campaign_id: CampaignId, transport: Transport | None) -> int:
    """Offer each human seat its options for the open wake; returns how many landed.

    Each offer is sealed to its seat: no seat learns another's style from it.
    """
    landed = 0
    for seat in cmp.human_seats(load_state(store, campaign_id)):
        state = load_state(store, campaign_id)
        memory = record.build(state, list(store.read(campaign_id)), seat)
        try:
            offered = options.offer(state, seat, transport, memory)
        except TransportError as exc:
            log.warning("no options for %s: %s", seat, exc)
            continue
        if offered is not None:
            _land(store, state, offered, seat, private_to(seat))
            landed += 1
        if options.last_cost is not None:
            cmp.log_cost(store, campaign_id, options.CALL_CLASS, [options.last_cost], seat)
    return landed


def set_hours(store: EventStore, campaign_id: CampaignId, hours: int) -> None:
    """How long wakes stay open from the next one on; an open wake keeps its deadline."""
    state = load_state(store, campaign_id)
    settings = state.settings.model_copy(update={"wake_hours": hours})
    _land(store, state, ev.SettingsSet(settings=settings))


def commit(store: EventStore, campaign_id: CampaignId, seat: SeatId, now: datetime) -> bool:
    """Seal ``seat``'s orders for the open wake; False if it already had or none is open."""
    state = load_state(store, campaign_id)
    held = state.seats.get(seat)
    if held is None or held.controller is not Controller.HUMAN:
        raise ValueError(f"seat {seat} is not a human seat")
    wake = state.wake
    if wake is None or wake.closed or seat in wake.committed:
        return False
    _land(store, state, ev.WakeCommitted(wake=wake.number, seat_id=seat, at=now), seat)
    return True


def wake_due(state: State, now: datetime) -> bool:
    """Every human seat has committed, or the deadline is at or before ``now``."""
    wake = state.wake
    if wake is None or wake.closed:
        return False
    humans = {s.seat_id for s in state.seats.values() if s.controller is Controller.HUMAN}
    return wake.deadline <= now or (bool(humans) and humans <= wake.committed)


def seat_for(state: State, person: EntityId) -> SeatId:
    """The seat ``person`` is played from: theirs, else the id a claim would give."""
    seat = seat_of_person(state, person)
    return (
        seat.seat_id if seat is not None else SeatId(derived_id(state.campaign_id, "seat", person))
    )


def _full(state: State) -> bool:
    """The players once the open wake closes already fill every human seat. Counted as
    the fold counts them when a ``SeatHandover`` to a player lands."""
    people = {s.embodies for s in state.seats.values()} | set(state.handovers)
    after = [p for p in people if controller_after(state, p) is Controller.HUMAN]
    return len(after) >= state.settings.max_human_seats


def leaders(state: State) -> list[EntityId]:
    """The leaders the host may hand to a new player: people on the roster, with a card,
    whom nobody plays once the open wake closes. In name order; none while the players
    after the close fill every human seat."""
    if state.phase is not Phase.PLAY or _full(state):
        return []
    free = [
        p for p in state.roster if p in state.cards and controller_after(state, p) is Controller.AI
    ]
    return sorted(free, key=lambda p: (state.entities[p].name, p))


def from_wake(state: State) -> int:
    """The first wake a leader handed over now is played in: the one after the next close."""
    wake = state.wake
    if wake is None:
        return 1
    return wake.number + (2 if wake.closed else 1)


def hand_over(store: EventStore, campaign_id: CampaignId, person: EntityId) -> SeatId:
    """A new player takes up ``person`` at the next close; returns the seat they will hold.
    Raises ``ValueError`` for a leader someone plays or will play, and while the players
    after the close fill every human seat."""
    state = load_state(store, campaign_id)
    if person not in leaders(state):
        raise ValueError("That leader cannot be handed over.")
    seat = seat_for(state, person)
    handover = ev.SeatHandover(entity_id=person, controller=Controller.HUMAN)
    _land(store, state, handover, None, private_to(seat))
    return seat


def _person_of(state: State, seat: SeatId) -> EntityId | None:
    held = state.seats.get(seat)
    if held is not None:
        return held.embodies
    return next((p for p in state.handovers if seat_for(state, p) == seat), None)


def joining(state: State, seat: SeatId) -> bool:
    """A new player has taken up ``seat``, and it is theirs from the next close."""
    person = _person_of(state, seat)
    held = state.seats.get(seat)
    return (
        person is not None
        and state.handovers.get(person) is Controller.HUMAN
        and (held is None or held.controller is not Controller.HUMAN)
    )


def leave(store: EventStore, campaign_id: CampaignId, seat: SeatId, now: datetime) -> None:
    """The seat's player leaves. From the next close the code runs the leader, whose
    orders stay in flight; the open wake is sealed for the seat now, so it holds no wake
    open. Raises ``ValueError`` unless a player holds or is taking up the seat."""
    state = load_state(store, campaign_id)
    person = _person_of(state, seat)
    if person is None or controller_after(state, person) is not Controller.HUMAN:
        raise ValueError(f"seat {seat} has no player to leave")
    handover = ev.SeatHandover(entity_id=person, controller=Controller.AI)
    _land(store, state, handover, seat, private_to(seat))
    held = state.seats.get(seat)
    if held is not None and held.controller is Controller.HUMAN:
        commit(store, campaign_id, seat, now)


def call_conference(
    store: EventStore,
    campaign_id: CampaignId,
    seat: SeatId,
    key: str,
    invited: tuple[EntityId, ...],
    text: conference.ConferenceText,
    voting_day: date,
    public: bool,
) -> None:
    """A seat calls a conference (CNF): an action, as an answer is, landed at once.
    Raises ``ValueError`` with the reason when it is refused."""
    state = load_state(store, campaign_id)
    called = conference.call(state, seat, key, invited, text, voting_day, public)
    assert isinstance(called, ev.ConferenceCalled)
    _land(store, state, called, seat, conference.scope(state, called.conference))


def seal_vote(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, key: str, vote: conference.Vote
) -> None:
    """A seat seals its vote in a conference (CNF), sealed to itself; a later vote in the
    same wake replaces it. Raises ``ValueError`` with the reason when it is refused."""
    state = load_state(store, campaign_id)
    _land(store, state, conference.vote(state, seat, key, vote), seat, private_to(seat))


def _allowed(state: State, seat: SeatId, order: tuple[Ask, ...]) -> tuple[Ask, ...]:
    """The aide never takes an irreversible step without a standing order naming it,
    never makes or accepts a deal (a deal is the seat's own to strike), and in a battle
    game never presses, withdraws or changes a contingency (BDC rule 8)."""
    standing = state.standing.get(seat, STANDING_DEFAULT)
    out: list[Ask] = []
    for a in order:
        if a.effect is None:
            out.append(a)
            continue
        if isinstance(a.effect, Deal):
            continue
        if a.effect.kind in IRREVERSIBLE and a.effect.kind not in standing:
            continue
        kept = battle.aide_may(state, a.effect)
        kept = None if kept is None else detect.aide_may(kept)
        if kept is not None:
            out.append(a if kept is a.effect else a.model_copy(update={"effect": kept}))
    return tuple(out)


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
    how = _how(absent, wake.deadline, now)
    for seat in absent:
        state = load_state(store, campaign_id)
        filed: list[OrderId] = []
        for order in options.aide_asks(state, seat, transport):
            asks = _allowed(state, seat, order)
            if not asks:
                continue
            try:
                filed.append(realism_tick.commit_order(store, campaign_id, seat, asks).order_id)
            except ValueError as exc:
                log.warning("aide order for %s dropped: %s", seat, exc)
        played = ev.WakeCommitted(
            wake=wake.number, seat_id=seat, by_aide=True, at=now, aide_orders=tuple(filed)
        )
        _land(store, load_state(store, campaign_id), played, seat, private_to(seat))
    closed = ev.WakeClosed(wake=wake.number, timed_out=absent, how=how)
    _land(store, load_state(store, campaign_id), closed)
    return absent


def _how(absent: tuple[SeatId, ...], deadline: datetime, now: datetime) -> ev.WakeCloseHow:
    """Every human committed; else the deadline passed; else the host closed it early."""
    if not absent:
        return "all_committed"
    return "deadline" if deadline <= now else "host"


__all__ = [
    "call_conference",
    "close_wake",
    "commit",
    "from_wake",
    "hand_over",
    "joining",
    "leaders",
    "leave",
    "offer_all",
    "open_wake",
    "seal_vote",
    "seat_for",
    "set_hours",
    "wake_due",
]
