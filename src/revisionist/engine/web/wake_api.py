"""The shared wake on the web (Phase 4 unit S1): commit, close, the wake header.

Commit replaces Advance: a seat commits, and the wake closes (the aide plays absent
seats, the tick runs, the next wake opens, as in ``runner.play_tick``) when every
human has committed or the host closes it. A solo game closes on commit.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from revisionist.core.ids import CampaignId, EntityId, SeatId
from revisionist.core.ontology import Controller, Phase
from revisionist.core.state import State, controller_after
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, runner
from revisionist.engine import scheduler as sch
from revisionist.engine import wake as wk
from revisionist.engine.discord.tables import Invites
from revisionist.engine.llm import Transport
from revisionist.engine.prose import ClaudeProseWriter, ProseWriter, TemplateProseWriter
from revisionist.engine.store import EventStore, load_state
from revisionist.engine.web.realism_api import Reply, WakeHeader

if TYPE_CHECKING:
    from revisionist.engine.pg_store import PostgresEventStore

log = logging.getLogger("revisionist.web")


@dataclass(frozen=True)
class TickTools:
    """What running a tick needs: ``runner.play_tick``'s arguments, passed in. Read
    from the app per request, so nothing here builds a transport of its own."""

    offline: bool
    transport_factory: Callable[[], Transport]
    briefings: Path


NO_WAKE = "No wake is open."
CLOSING = "The wake is closing."


def _open_number(state: State) -> int | None:
    wake = state.wake
    return wake.number if wake is not None and not wake.closed else None


def start_play(
    store: EventStore, campaign_id: CampaignId, now: datetime, *, tools: TickTools
) -> None:
    """Write the opening papers, then open wake 0 and its offers: the first wake opens
    with play, no tick before it."""
    writer: ProseWriter = (
        TemplateProseWriter() if tools.offline else ClaudeProseWriter(tools.transport_factory())
    )
    try:
        done = realism_tick.write_opening(store, campaign_id, writer)
    except Exception:  # the game is begun: wake 0 must open, and the first tick writes the pages
        log.exception("the opening papers were not written at the begin")
    else:
        for dropped in done.prose_dropped:
            log.warning("no prose at the begin for %s", dropped)
    wk.open_wake(store, campaign_id, now)
    wk.offer_all(store, campaign_id, None if tools.offline else tools.transport_factory())


def seats(state: State) -> int:
    """How many seats the wake counts: every leader a player could hold (on the roster,
    with a card), up to the game's human seats, whether a person or the code plays it."""
    leaders = sum(1 for p in state.roster if p in state.cards)
    return max(1, min(leaders, state.settings.max_human_seats))


def done(state: State) -> int:
    """How many seats have pressed Done in the open wake. A seat sealed by its player's
    leave counts as not done, as a seat the code plays does."""
    wake = state.wake
    if wake is None or wake.closed:
        return 0
    return sum(
        1
        for s in wake.committed
        if s in state.seats and controller_after(state, state.seats[s].embodies) is Controller.HUMAN
    )


def wake_header(state: State, seat: SeatId, *, host: bool) -> WakeHeader:
    """The wake as ``seat`` sees it. ``host``: the account is the host. Counts only, and
    the same counts whoever plays the other seats."""
    wake = state.wake
    humans = seats(state)
    if wake is None or wake.closed:
        return WakeHeader(
            wake=0 if wake is None else wake.number,
            deadline=None,
            committed=0,
            humans=humans,
            you_committed=False,
            is_host=host,
            can_close=host,  # a game begun before wakes: closing runs the tick that opens one
        )
    return WakeHeader(
        wake=wake.number,
        deadline=wake.deadline.isoformat(),
        committed=done(state),
        humans=humans,
        you_committed=seat in wake.committed,
        is_host=host,
        can_close=host,
    )


def _play(
    store: "PostgresEventStore",
    campaign_id: CampaignId,
    number: int | None,
    now: datetime,
    tools: TickTools,
) -> Reply:
    """Close wake ``number`` and run the tick; ``None``: no wake is open to close.

    Under the scheduler's lock: it closes a due wake too, and two last commits can
    land together, so whoever gets here second finds the wake already gone.
    """
    table = sch.ScheduleTable(store.conn)
    if not table.try_lock(campaign_id):
        return Reply(reply=CLOSING, refused=False)
    try:
        if number != _open_number(load_state(store, campaign_id)):
            return Reply(reply=CLOSING, refused=False)
        run = runner.play_tick(
            store,
            campaign_id,
            offline=tools.offline,
            transport_factory=tools.transport_factory,
            briefings=tools.briefings,
            warn=log.warning,
            now=now,
        )
        if run.leaks:
            table.pause(campaign_id, f"canary leak at tick {run.result.tick}")
    finally:
        table.unlock(campaign_id)
    done = run.result
    stop = done.wake if isinstance(done, realism_tick.RealismTickResult) else None
    today = load_state(store, campaign_id).in_world_date
    reason = stop.reason.label if stop and stop.reason.what != "horizon" else None
    return Reply(reply=_calendar_line(today, reason), refused=False)


def commit(
    store: "PostgresEventStore",
    campaign_id: CampaignId,
    seat: SeatId,
    now: datetime,
    *,
    tools: TickTools,
) -> Reply:
    """Seal the seat's orders; close the wake if that was the last."""
    opened = load_state(store, campaign_id)
    if _open_number(opened) is None:
        return Reply(reply=NO_WAKE, refused=True)
    if wk.joining(opened, seat):
        return Reply(reply=JOINING, refused=True)
    if not wk.commit(store, campaign_id, seat, now):
        return Reply(reply="You have already committed this wake.", refused=True)
    state = load_state(store, campaign_id)
    if wk.wake_due(state, now):
        return _play(store, campaign_id, _open_number(state), now, tools)
    waiting = seats(state) - done(state)
    return Reply(
        reply=f"Your orders are sealed. Waiting for {waiting} other player(s).", refused=False
    )


def leave(
    store: "PostgresEventStore",
    campaign_id: CampaignId,
    seat: SeatId,
    now: datetime,
    *,
    tools: TickTools,
) -> bool:
    """The seat's player leaves (``engine.wake.leave``), under the game's lock so the
    leave cannot land inside a close; then close the wake if that sealed the last seat.
    False, with nothing logged, while the game is closing a wake. True with nothing
    logged when no player holds the seat in the log."""
    table = sch.ScheduleTable(store.conn)
    if not table.try_lock(campaign_id):
        return False
    try:
        wk.leave(store, campaign_id, seat, now)
    except ValueError:
        return True
    finally:
        table.unlock(campaign_id)
    state = load_state(store, campaign_id)
    if wk.wake_due(state, now):
        _play(store, campaign_id, _open_number(state), now, tools)
    return True


def close(
    store: "PostgresEventStore",
    campaign_id: CampaignId,
    now: datetime,
    *,
    host: bool,
    tools: TickTools,
) -> Reply:
    """ "Close the wake now". The host alone; a refusal otherwise. With no wake open (a
    game begun before wakes) it runs the tick, which opens the first."""
    if not host:
        return Reply(reply="Only the host can close the wake.", refused=True)
    return _play(store, campaign_id, _open_number(load_state(store, campaign_id)), now, tools)


class Leader(TypedDict):
    """One leader the host may hand to a new player (``handover-list``)."""

    key: str
    """The person's entity id; ``handover`` takes it back as ``leader``."""
    name: str
    office: str


JOINING = "You play from the next wake. Your orders now are held for it."
"""[proposed] The refusal of Done to a player who takes up the seat when this wake closes."""
NOT_IN_PLAY = "Hand a leader over once the game has begun."
"""[proposed] The refusal of ``handover-list`` and ``handover`` before play."""
NOT_FREE = "That leader cannot be handed over."
"""[proposed] The refusal of ``handover`` for a leader someone plays or will play."""


def _in_play(state: State) -> bool:
    return state.ruleset == "realism" and state.phase is Phase.PLAY


def handover_list(state: State) -> dict[str, Any]:
    """``handover-list`` (the host): the leaders nobody plays at the next close.
    Reply ``{reply, refused, leaders: [{key, name, office}]}``; the reply's words are
    [proposed]."""
    if not _in_play(state):
        return {"reply": NOT_IN_PLAY, "refused": True, "leaders": []}
    leaders = [
        Leader(key=p, name=state.entities[p].name, office=state.cards[p].office)
        for p in wk.leaders(state)
    ]
    reply = (
        f"{len(leaders)} leader(s) can be handed to a new player."
        if leaders
        else "No leader is free to hand over."
    )
    return {"reply": reply, "refused": False, "leaders": leaders}


def handover(
    store: "PostgresEventStore", campaign_id: CampaignId, body: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """``handover`` (the host), request ``{leader: key}``: an invite code for a leader
    nobody plays. Reply ``{reply, refused, code, from_wake}``; ``from_wake`` is the first
    wake the new player counts in if they join now; the reply's words are [proposed].
    Nothing is logged until the code is redeemed."""
    refused: dict[str, Any] = {"refused": True, "code": None, "from_wake": None}
    state = load_state(store, campaign_id)
    if not _in_play(state):
        return {"reply": NOT_IN_PLAY, **refused}
    key = body.get("leader")
    leader = EntityId(key) if isinstance(key, str) else None
    if leader is None or leader not in wk.leaders(state):
        return {"reply": NOT_FREE, **refused}
    code = Invites(store.conn).issue(campaign_id, wk.seat_for(state, leader), now)
    first = wk.from_wake(state)
    name = state.entities[leader].name
    return {
        "reply": f"Send this code to the new player privately. It works once: they take up "
        f"{name} from wake {first}.",
        "refused": False,
        "code": code,
        "from_wake": first,
    }


def set_wake_hours(store: EventStore, campaign_id: CampaignId, hours: int) -> Reply:
    """The host sets ``settings.wake_hours``, 1 to 168, via ``SettingsSet``."""
    if not 1 <= hours <= 168:
        return Reply(reply="Wake hours run from 1 to 168.", refused=True)
    wk.set_hours(store, campaign_id, hours)
    return Reply(reply=f"Wakes now stay open for up to {hours} hour(s).", refused=False)


def advance(
    store: "PostgresEventStore",
    campaign_id: CampaignId,
    seat: SeatId,
    now: datetime,
    *,
    host: bool,
    tools: TickTools,
) -> Reply:
    """What an old client's Advance means now: close the wake (a solo seat counts as
    host). A game begun before wakes has none open; the tick runs and opens the first."""
    state = load_state(store, campaign_id)
    if cmp.human_seats(state) != [seat] and not host:
        return Reply(reply="Only the host advances a shared game.", refused=True)
    return _play(store, campaign_id, _open_number(state), now, tools)


def _calendar_line(today: date | None, reason: str | None) -> str:
    """What the web says after an advance, in words rather than the CLI's log line."""
    if today is None:
        return "The calendar moves on."
    line = f"The calendar moves to {today:%A} {today.day} {today:%B %Y}."
    return f"{line} Reason: {reason.rstrip('.')}." if reason else line


__all__ = [
    "JOINING",
    "NOT_FREE",
    "NOT_IN_PLAY",
    "Leader",
    "TickTools",
    "advance",
    "close",
    "commit",
    "done",
    "handover",
    "handover_list",
    "leave",
    "seats",
    "set_wake_hours",
    "start_play",
    "wake_header",
]
