"""History's clock and divergence (spec §5.4). Phase 2 unit.

On each tick, history events due by today's in-world date fire if their
condition still holds and are skipped otherwise; a skip raises divergence by
the event's weight.
"""

import hashlib
from collections.abc import Iterable
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.goals import goal_met
from revisionist.core.ids import CampaignId, derived_id
from revisionist.core.ontology import ScheduledEvent, ScheduleSource
from revisionist.core.realism.document import BodyField
from revisionist.core.realism.war import NewsEvent, NewsTopic
from revisionist.core.state import State, View
from revisionist.core.visibility import Visibility


def _pending(events: Iterable[ScheduledEvent]) -> list[ScheduledEvent]:
    """Unsettled history events, earliest first, ties broken by id."""
    pending = [
        s
        for s in events
        if s.source is ScheduleSource.HISTORY
        and not s.fired
        and not s.skipped
        and s.on_date is not None
    ]
    return sorted(pending, key=lambda s: (s.on_date, s.scheduled_id))


def due(state: State, today: date) -> tuple[ScheduledEvent, ...]:
    """Pending history events with ``on_date`` on or before ``today``, in date order."""
    return tuple(s for s in _pending(state.scheduled.values()) if s.on_date and s.on_date <= today)


def settle(
    state: State, today: date
) -> list[ev.ScheduledEventFired | ev.ScheduledEventSkipped | ev.DivergenceChanged]:
    """Fire or skip every due event, with the divergence each skip adds.

    Conditions are read from ``state`` as given, not from the events this batch
    produces, so the result does not depend on the order of the due events.
    """
    out: list[ev.ScheduledEventFired | ev.ScheduledEventSkipped | ev.DivergenceChanged] = []
    for s in due(state, today):
        if s.condition is None or goal_met(state, s.condition):
            out.append(ev.ScheduledEventFired(scheduled_id=s.scheduled_id))
            continue
        out.append(ev.ScheduledEventSkipped(scheduled_id=s.scheduled_id))
        out.append(ev.DivergenceChanged(change=s.weight, reason=f"{s.name} did not happen"[:200]))
    return out


def drawn_day(campaign_id: CampaignId, s: ScheduledEvent) -> date | None:
    """The day the draw gives a development in this campaign, or None if it never comes.

    Seeded by the campaign and the development alone, so a replay, another tick
    length or another development in the deck draws the same.
    """
    if s.source is not ScheduleSource.DEVELOPMENT or s.on_date is None or s.window_end is None:
        return None
    seed = "\x1f".join((campaign_id, "draw", s.scheduled_id)).encode()
    n = int.from_bytes(hashlib.blake2b(seed, digest_size=16).digest(), "big")
    if n % 100 >= (s.chance or 0):
        return None
    return s.on_date + timedelta(days=(n // 100) % ((s.window_end - s.on_date).days + 1))


def developments_due(
    state: State, today: date
) -> list[ev.ScheduledEventFired | ev.ScheduledEventSkipped]:
    """Fire each pending development drawn to a day on or before ``today`` whose
    condition holds; skip it if the condition fails then, or if the draw gave it
    no day and its window has closed. A skip adds no divergence: the deck is what
    might have happened, not the record."""
    out: list[ev.ScheduledEventFired | ev.ScheduledEventSkipped] = []
    pending = (
        s
        for s in state.scheduled.values()
        if s.source is ScheduleSource.DEVELOPMENT and not s.fired and not s.skipped
    )
    for s in sorted(pending, key=lambda s: (s.on_date or today, s.scheduled_id)):
        day = drawn_day(state.campaign_id, s)
        if day is None:
            if s.window_end is not None and s.window_end <= today:
                out.append(ev.ScheduledEventSkipped(scheduled_id=s.scheduled_id))
            continue
        if day > today:
            continue
        holds = s.condition is None or goal_met(state, s.condition)
        kind = ev.ScheduledEventFired if holds else ev.ScheduledEventSkipped
        out.append(kind(scheduled_id=s.scheduled_id))
    return out


def news(state: State, settled: Iterable[ev.Payload], day: date) -> list[ev.NewsReported]:
    """The news of each event in ``settled`` that fired in public with a headline.

    The news id comes from the scheduled id, so a replay names the same item.
    """
    out: list[ev.NewsReported] = []
    for e in settled:
        if not isinstance(e, ev.ScheduledEventFired):
            continue
        s = state.scheduled[e.scheduled_id]
        if s.headline is None or s.subject is None or s.scope.visibility is not Visibility.PUBLIC:
            continue
        item = NewsEvent(
            news_id=derived_id(state.campaign_id, "news", "history", s.scheduled_id),
            on=day,
            topic=NewsTopic.EVENT,
            subject=s.subject,
            obj=s.obj,
            facts=(BodyField(label="Date", value=f"{day.day} {day:%B %Y}"),),
            headline=s.headline,
        )
        out.append(ev.NewsReported(news=item))
    return out


def next_due(world: State | View, today: date | None) -> ScheduledEvent | None:
    """The earliest pending history event visible in ``world``, on or after
    ``today`` (any date when None). For the deputy context and the calendar."""
    upcoming = [
        s
        for s in _pending(world.scheduled.values())
        if today is None or (s.on_date and s.on_date >= today)
    ]
    return upcoming[0] if upcoming else None
