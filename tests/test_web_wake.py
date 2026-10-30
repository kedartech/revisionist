"""The shared wake on the web (Phase 4 unit S1): commit, close, wake hours, offers
at wake open. Same harness as ``tests/test_web_realism.py``."""

import json
from collections.abc import Callable
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, SeatId, derived_id
from revisionist.core.realism.agenda import PlayStyle
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine import options, wake
from revisionist.engine.campaign import human_seats
from revisionist.engine.llm import TransportError
from revisionist.engine.scheduler import ScheduleTable
from revisionist.engine.store import MemoryStore
from revisionist.engine.store import load_state as store_state
from revisionist.engine.web import server, wake_api
from tests.test_engine_v2_wake import CAMPAIGN, T0, Table
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of

WORLD = "engine-v2-slice-1941"


def state_of(game: Realism) -> State:
    store = game.web.app.open()
    try:
        return store_state(store, game.campaign)
    finally:
        store.close()


def log_of(game: Realism) -> list[ev.Event]:
    store = game.web.app.open()
    try:
        return list(store.read(game.campaign))
    finally:
        store.close()


def seat_of(game: Realism, who: str) -> SeatId:
    return SeatId(derived_id(game.campaign, "seat", EntityId(game.ids[who])))


def begin(game: Realism, before: Callable[[Any], None] | None = None) -> None:
    """Open play as the server's ``begin`` does: play, then wake 0 and its offers."""
    game.open_play()
    store = game.web.app.open()
    try:
        if before is not None:
            before(store)
        app = game.web.app
        wake_api.start_play(store, game.campaign, app.clock(), tools=app._tools())
    finally:
        store.close()


@pytest.fixture
def solo(web: Web) -> tuple[Realism, Client]:  # noqa: F811
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    make_host(game, ada)
    begin(game)
    return game, ada


@pytest.fixture
def duo(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    bea = game.seat("bea", "churchill")
    make_host(game, ada)
    begin(game)
    return game, ada, bea


def test_a_solo_commit_moves_the_calendar_and_opens_the_next_wake(
    solo: tuple[Realism, Client],
) -> None:
    game, ada = solo
    assert realism_of(ada)["wake"]["wake"] == 0
    status, out = post(ada, "commit")
    assert status == 200 and not out["refused"], out
    assert out["reply"].startswith("The calendar moves")
    head = realism_of(ada)["wake"]
    assert head["wake"] == 1 and head["committed"] == 0 and head["deadline"]
    assert not head["you_committed"]
    assert state_of(game).tick == 1


def test_the_first_commit_waits_and_the_second_closes(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    status, out = post(bea, "commit")
    assert status == 200
    assert out == {
        "reply": "Your orders are sealed. Waiting for 1 other player(s).",
        "refused": False,
    }
    seen = realism_of(ada)["wake"]
    assert (seen["committed"], seen["humans"], seen["you_committed"]) == (1, 2, False)
    assert realism_of(bea)["wake"]["you_committed"] is True
    assert state_of(game).tick == 0

    _, again = post(bea, "commit")
    assert again["refused"] and "already" in again["reply"]

    _, last = post(ada, "commit")
    assert not last["refused"] and last["reply"].startswith("The calendar moves")
    assert realism_of(bea)["wake"]["wake"] == 1
    assert not any(
        isinstance(e.payload, ev.WakeCommitted) and e.payload.by_aide for e in log_of(game)
    )


def test_the_host_closes_and_the_aide_plays_the_absent_seat(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    post(ada, "commit")
    assert realism_of(ada)["wake"]["can_close"] is True
    assert realism_of(bea)["wake"]["can_close"] is False
    _, out = post(ada, "close")
    assert not out["refused"] and out["reply"].startswith("The calendar moves")
    played = [
        e.payload
        for e in log_of(game)
        if isinstance(e.payload, ev.WakeCommitted) and e.payload.by_aide
    ]
    assert [p.seat_id for p in played] == [seat_of(game, "churchill")]


def test_only_the_host_closes(duo: tuple[Realism, Client, Client]) -> None:
    game, _, bea = duo
    status, out = post(bea, "close")
    assert status == 200
    assert out == {"reply": "Only the host can close the wake.", "refused": True}
    assert wake_api._open_number(state_of(game)) == 0


def test_no_wake_open_is_a_refusal(web: Web) -> None:  # noqa: F811
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    make_host(game, ada)
    game.open_play()
    head = realism_of(ada)["wake"]
    assert (head["deadline"], head["can_close"], head["humans"]) == (None, True, 1)
    _, out = post(ada, "commit")
    assert out == {"reply": "No wake is open.", "refused": True}
    _, out = post(ada, "close")
    assert not out["refused"] and out["reply"].startswith("The calendar moves"), out
    assert realism_of(ada)["wake"]["deadline"] is not None


def test_a_committed_seat_files_nothing_more_this_wake(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, _ada, bea = duo
    assert not post(bea, "commit")[1]["refused"]
    for action in ("lever", "sign", "option", "file", "step"):
        _, out = post(bea, action)
        assert out == {"reply": server.SEALED, "refused": True}, action
    _, still = post(bea, "read")
    assert still != {"reply": server.SEALED, "refused": True}
    assert state_of(game).tick == 0


def test_advance_closes_the_wake_for_an_old_client(solo: tuple[Realism, Client]) -> None:
    _, ada = solo
    _, out = post(ada, "advance")
    assert not out["refused"] and out["reply"].startswith("The calendar moves")
    assert realism_of(ada)["wake"]["wake"] == 1


def test_a_non_host_cannot_advance_a_shared_wake(duo: tuple[Realism, Client, Client]) -> None:
    game, _, bea = duo
    _, out = post(bea, "advance")
    assert out["refused"] and state_of(game).tick == 0


def test_the_wake_hours_are_set_and_refused_out_of_range(solo: tuple[Realism, Client]) -> None:
    game, ada = solo
    tone = state_of(game).settings.tone
    for hours in (0, 169):
        status, out = ada.call("/api/game/wake-hours", {"hours": hours})
        assert status == 200 and out["refused"], out
    assert state_of(game).settings.wake_hours == 12
    status, out = ada.call("/api/game/wake-hours", {"hours": 48})
    assert status == 200 and not out["refused"], out
    settings = state_of(game).settings
    assert settings.wake_hours == 48 and settings.tone == tone


def test_a_beginner_seat_is_offered_options_when_the_wake_opens(
    web: Web,  # noqa: F811
) -> None:
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    make_host(game, ada)
    seat = seat_of(game, "roosevelt")
    begin(game, lambda store: options.set_style(store, game.campaign, seat, PlayStyle.BEGINNER))

    def offered() -> list[ev.Event]:
        return [e for e in log_of(game) if isinstance(e.payload, ev.OptionsOffered)]

    (first,) = offered()
    assert first.scope == private_to(seat)
    assert isinstance(first.payload, ev.OptionsOffered) and first.payload.wake == 0
    post(ada, "commit")
    wakes = [e.payload.wake for e in offered() if isinstance(e.payload, ev.OptionsOffered)]
    assert wakes == [0, 1]


def test_a_free_seat_is_offered_nothing(solo: tuple[Realism, Client]) -> None:
    game, _ = solo
    assert not any(isinstance(e.payload, ev.OptionsOffered) for e in log_of(game))


def test_begin_opens_the_first_wake_with_its_offers(web: Web) -> None:  # noqa: F811
    web.app.spawn = lambda run: run()
    ada, _ = web.signed_up("ada")

    def new(action: str, **body: Any) -> dict[str, Any]:
        status, out = ada.call(f"/api/new/{action}", body)
        assert status == 200 and not out.get("refused"), out
        return dict(out)

    new("ready", world=WORLD)
    new("pick", name="Franklin D. Roosevelt")
    store = web.app.open()
    try:
        cid = store.campaign_ids()[-1]
        (seat,) = human_seats(store_state(store, cid))
        options.set_style(store, cid, seat, PlayStyle.BEGINNER)  # the style route is unit S2's
        new("begin")
        assert any(isinstance(e.payload, ev.OptionsOffered) for e in store.read(cid))
    finally:
        store.close()
    head = realism_of(ada)["wake"]
    assert head["deadline"] and head["is_host"] and head["can_close"]


def test_the_header_never_names_a_seat(duo: tuple[Realism, Client, Client]) -> None:
    game, ada, bea = duo
    post(bea, "commit")
    head = realism_of(ada)["wake"]
    shown = json.dumps(head)
    for who in ("roosevelt", "churchill"):
        assert seat_of(game, who) not in shown
    state = state_of(game)
    for seat in state.seats.values():
        assert seat.name not in shown
    assert set(head) == {
        "wake",
        "deadline",
        "committed",
        "humans",
        "you_committed",
        "is_host",
        "can_close",
    }


def test_a_tick_the_scheduler_is_running_is_left_to_it(solo: tuple[Realism, Client]) -> None:
    game, ada = solo
    other = game.web.app.open()
    try:
        table = ScheduleTable(other.conn)
        assert table.try_lock(game.campaign)
        _, out = post(ada, "commit")
        table.unlock(game.campaign)
    finally:
        other.close()
    assert out == {"reply": wake_api.CLOSING, "refused": False}
    assert state_of(game).tick == 0


def test_a_late_second_close_does_not_close_the_next_wake(solo: tuple[Realism, Client]) -> None:
    game, ada = solo
    post(ada, "commit")
    store = game.web.app.open()
    try:
        app = game.web.app
        out = wake_api._play(store, game.campaign, 0, app.clock(), app._tools())
    finally:
        store.close()
    assert out == {"reply": wake_api.CLOSING, "refused": False}
    assert state_of(game).tick == 1


def test_a_failed_offer_costs_only_that_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    t = Table(MemoryStore())
    assert t.winston is not None
    options.set_style(t.store, CAMPAIGN, t.fdr, PlayStyle.BEGINNER)
    options.set_style(t.store, CAMPAIGN, t.winston, PlayStyle.BEGINNER)
    wake.open_wake(t.store, CAMPAIGN, T0)
    real = options.offer

    def offer(state: State, seat: SeatId, transport: Any) -> ev.OptionsOffered | None:
        if seat == t.fdr:
            raise TransportError("down")
        return real(state, seat, transport)

    monkeypatch.setattr(options, "offer", offer)
    assert wake.offer_all(t.store, CAMPAIGN, None) == 1
    (only,) = [e for e in t.store.read(CAMPAIGN) if isinstance(e.payload, ev.OptionsOffered)]
    assert only.scope == private_to(t.winston)
