"""A seat's view holds the developments that fired and no others: a development's
window, chance, condition, effects and asks are the engine's until it fires, and the
view is what goes into a model prompt whose answer returns to the player.
"""

from collections.abc import Mapping

from revisionist.core.ids import ScheduledEventId
from revisionist.core.ontology import ScheduledEvent, ScheduleSource
from revisionist.core.project import project
from revisionist.engine.store import load_state
from tests.test_developments_play import CAMPAIGN, autumn, deck, played


def _developments(
    view_scheduled: Mapping[ScheduledEventId, ScheduledEvent],
) -> list[ScheduledEvent]:
    return [s for s in view_scheduled.values() if s.source is ScheduleSource.DEVELOPMENT]


def test_a_new_game_shows_no_development_in_the_seat_view() -> None:
    store, seat, _ = played(autumn(), ticks=0)
    state = load_state(store, CAMPAIGN)
    assert len(deck(state)) == 12
    view = project(state, seat)
    assert _developments(view.scheduled) == []
    dumped = view.model_dump_json()
    for s in deck(state).values():
        assert s.scheduled_id not in dumped
        assert s.headline is not None and s.headline not in dumped


def test_the_view_keeps_fired_developments_and_drops_pending_and_skipped() -> None:
    store, seat, _ = played(autumn())
    state = load_state(store, CAMPAIGN)
    held = deck(state)
    fired = {k for k, s in held.items() if s.fired}
    assert fired and fired != set(held)
    assert any(s.skipped for s in held.values()) or any(
        not s.fired and not s.skipped for s in held.values()
    )
    shown = {s.scheduled_id for s in _developments(project(state, seat).scheduled)}
    assert shown == fired


def test_history_events_stay_in_the_seat_view() -> None:
    store, seat, _ = played(autumn(), ticks=0)
    state = load_state(store, CAMPAIGN)
    history = {k for k, s in state.scheduled.items() if s.source is ScheduleSource.HISTORY}
    assert history
    assert history <= set(project(state, seat).scheduled)
