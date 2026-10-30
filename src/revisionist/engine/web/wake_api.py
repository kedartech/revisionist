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
from typing import TYPE_CHECKING

from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.state import State
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, runner
from revisionist.engine import scheduler as sch
from revisionist.engine import wake as wk
from revisionist.engine.llm import Transport
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
    """Open wake 0 and its offers: the first wake opens with play, no tick before it."""
    wk.open_wake(store, campaign_id, now)
    wk.offer_all(store, campaign_id, None if tools.offline else tools.transport_factory())


def wake_header(state: State, seat: SeatId, *, host: bool) -> WakeHeader:
    """The wake as ``seat`` sees it. ``host``: the account is the host. Counts only."""
    wake = state.wake
    humans = len(cmp.human_seats(state))
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
        committed=len(wake.committed),
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
    if _open_number(load_state(store, campaign_id)) is None:
        return Reply(reply=NO_WAKE, refused=True)
    if not wk.commit(store, campaign_id, seat, now):
        return Reply(reply="You have already committed this wake.", refused=True)
    state = load_state(store, campaign_id)
    if wk.wake_due(state, now):
        return _play(store, campaign_id, _open_number(state), now, tools)
    wake = state.wake
    assert wake is not None
    waiting = len(cmp.human_seats(state)) - len(wake.committed)
    return Reply(
        reply=f"Your orders are sealed. Waiting for {waiting} other player(s).", refused=False
    )


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
    "TickTools",
    "advance",
    "close",
    "commit",
    "set_wake_hours",
    "start_play",
    "wake_header",
]
