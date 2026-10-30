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

from revisionist.core.ids import CampaignId, SeatId
from revisionist.core.state import State
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.llm import Transport
from revisionist.engine.prose import ClaudeProseWriter, ProseWriter, TemplateProseWriter
from revisionist.engine.store import EventStore, load_state
from revisionist.engine.web.realism_api import Reply, WakeHeader

log = logging.getLogger("revisionist.web")


@dataclass(frozen=True)
class TickTools:
    """What running a tick needs: ``runner.play_tick``'s arguments, passed in. Read
    from the app per request, so nothing here builds a transport of its own."""

    offline: bool
    transport_factory: Callable[[], Transport]
    briefings: Path


def wake_header(state: State, seat: SeatId, *, host: bool) -> WakeHeader:
    """Phase 4 unit S1: the wake as ``seat`` sees it. ``host``: the account is the host."""
    return WakeHeader(
        wake=0,
        deadline=None,
        committed=0,
        humans=0,
        you_committed=False,
        is_host=host,
        can_close=False,
    )


def commit(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, now: datetime, *, tools: TickTools
) -> Reply:
    """Phase 4 unit S1: seal the seat's orders; close the wake if that was the last."""
    return Reply(reply="Nothing has changed yet.", refused=True)


def close(
    store: EventStore, campaign_id: CampaignId, now: datetime, *, host: bool, tools: TickTools
) -> Reply:
    """Phase 4 unit S1: "Close the wake now". The host alone; a refusal otherwise."""
    return Reply(reply="Nothing has changed yet.", refused=True)


def set_wake_hours(store: EventStore, campaign_id: CampaignId, hours: int) -> Reply:
    """Phase 4 unit S1: the host sets ``settings.wake_hours``, 1 to 168, via ``SettingsSet``."""
    return Reply(reply="Nothing has changed yet.", refused=True)


def advance(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, *, host: bool, tools: TickTools
) -> str:
    """Phase 4 unit S1 replaces this: a forced advance, the old one moved here as it
    was. Raises ``ValueError`` to refuse."""
    state = load_state(store, campaign_id)
    humans = cmp.human_seats(state)
    if humans != [seat] and not host:
        raise ValueError("Only the host advances a shared game.")
    prose: ProseWriter = (
        TemplateProseWriter() if tools.offline else ClaudeProseWriter(tools.transport_factory())
    )
    result = realism_tick.run_realism_tick(store, campaign_id, prose=prose)
    for dropped in result.prose_dropped:
        log.warning("no prose for %s", dropped)
    today = load_state(store, campaign_id).in_world_date
    return _calendar_line(
        today,
        (
            result.wake.reason.label
            if result.wake and result.wake.reason.what != "horizon"
            else None
        ),
    )


def _calendar_line(today: date | None, reason: str | None) -> str:
    """What the web says after an advance, in words rather than the CLI's log line."""
    if today is None:
        return "The calendar moves on."
    line = f"The calendar moves to {today:%A} {today.day} {today:%B %Y}."
    return f"{line} Reason: {reason.rstrip('.')}." if reason else line


__all__ = ["TickTools", "advance", "close", "commit", "set_wake_hours", "wake_header"]
