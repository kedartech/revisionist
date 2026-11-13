"""Begin and the other Session Zero writes on the web hold one lock per game. A write
that races Begin is refused rather than landing inside it, so a begun game always
has wake 0 open and every player who joined holds a person. Each race is made
deterministic by patching a helper between the check and the write so the racing
request runs there; no model is called."""

import threading
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import SeatId
from revisionist.core.ontology import Phase
from revisionist.core.state import State
from revisionist.engine import realism_tick
from revisionist.engine import wake as wk
from revisionist.engine.pg_store import PostgresEventStore
from revisionist.engine.store import load_state
from revisionist.engine.web import agenda_api
from revisionist.engine.web.accounts import WebSeats
from revisionist.engine.web.handlers import JOINED_ZERO
from tests.test_web import Client, Web, web  # noqa: F401

BUSY = {"reply": "The game is busy with another change. Try again in a moment.", "refused": True}


def call(client: Client, action: str, /, **body: Any) -> tuple[int, Any]:
    return client.call(f"/api/new/{action}", body)


def new(client: Client, action: str, /, **body: Any) -> dict[str, Any]:
    status, out = call(client, action, **body)
    assert status == 200, out
    return dict(out)


@pytest.fixture
def chosen(web: Web) -> tuple[Web, Client, Client]:  # noqa: F811
    """Autumn 1941 with two players, each holding a person: ready to begin."""
    web.app.spawn = lambda run: run()
    host, _ = web.signed_up("hostess")
    assert not new(host, "ready", world="autumn-1941")["refused"]
    code = new(host, "invite")["code"]
    guest, _ = web.signed_up("guest")
    assert guest.seat("join", code=code) == JOINED_ZERO
    assert not new(host, "pick", name="Franklin D. Roosevelt")["refused"]
    assert not new(guest, "pick", name="Winston Churchill")["refused"]
    return web, host, guest


def settled(web: Web, host: Client) -> tuple[State, set[SeatId]]:  # noqa: F811
    """The game's state, replayed from its log, and the seats its players hold."""
    cid = host.me()["game"]["id"]
    store = web.app.open()
    try:
        state = load_state(store, cid)
        seated = {s.seat_id for s in WebSeats(store.conn).for_campaign(cid)}
    finally:
        store.close()
    return state, seated


def assert_begun(state: State, seated: set[SeatId]) -> None:
    assert state.phase is Phase.PLAY
    assert state.wake is not None and state.wake.number == 0 and not state.wake.closed
    assert seated <= set(state.seats)


def test_a_write_racing_begin_cannot_leave_a_begun_game_with_no_wake(
    chosen: tuple[Web, Client, Client], monkeypatch: pytest.MonkeyPatch
) -> None:
    web, host, guest = chosen  # noqa: F811
    checked, go = threading.Event(), threading.Event()
    styled: list[tuple[int, Any]] = []
    set_style = agenda_api.set_style

    def held(*args: Any) -> Any:  # the guest's style, checked and not yet written
        checked.set()
        go.wait(10)
        return set_style(*args)

    land = wk._land

    def style_first(store: Any, state: State, payload: ev.Payload, *rest: Any) -> None:
        if isinstance(payload, ev.WakeOpened):  # between open_wake's read and its write
            go.set()
            racer.join(10)
        land(store, state, payload, *rest)

    monkeypatch.setattr(agenda_api, "set_style", held)
    monkeypatch.setattr(wk, "_land", style_first)
    racer = threading.Thread(target=lambda: styled.append(call(guest, "style", style="guided")))
    racer.start()
    assert checked.wait(10)

    first = call(host, "begin")
    go.set()
    racer.join(10)

    assert first == (200, BUSY)
    assert styled == [(200, {"reply": "You will be offered a plan each wake.", "refused": False})]
    assert not new(host, "begin")["refused"]
    assert_begun(*settled(web, host))


def test_a_release_racing_begin_cannot_leave_a_player_with_no_person(
    chosen: tuple[Web, Client, Client], monkeypatch: pytest.MonkeyPatch
) -> None:
    web, host, guest = chosen  # noqa: F811
    released: list[tuple[int, Any]] = []
    open_play = realism_tick.open_play

    def release_first(store: Any, campaign_id: Any) -> None:  # after the waiting check
        released.append(call(guest, "unpick"))
        open_play(store, campaign_id)

    monkeypatch.setattr(realism_tick, "open_play", release_first)

    assert not new(host, "begin")["refused"]
    assert released == [(200, BUSY)]
    assert_begun(*settled(web, host))


def test_a_second_begin_while_the_first_holds_the_game_is_refused(
    chosen: tuple[Web, Client, Client], monkeypatch: pytest.MonkeyPatch
) -> None:
    web, host, _ = chosen  # noqa: F811
    again: list[tuple[int, Any]] = []
    open_play = realism_tick.open_play

    def begin_again(store: Any, campaign_id: Any) -> None:
        if not again:
            again.append((0, None))
            again[0] = call(host, "begin")
        open_play(store, campaign_id)

    monkeypatch.setattr(realism_tick, "open_play", begin_again)

    assert not new(host, "begin")["refused"]
    assert again == [(200, BUSY)]
    state, seated = settled(web, host)
    assert_begun(state, seated)
    store = web.app.open()
    try:
        log = list(store.read(state.campaign_id))
    finally:
        store.close()
    assert sum(isinstance(e.payload, ev.SessionZeroClosed) for e in log) == 1
    assert sum(isinstance(e.payload, ev.WakeOpened) for e in log) == 1


def test_no_exit_leaves_the_game_busy(
    chosen: tuple[Web, Client, Client], monkeypatch: pytest.MonkeyPatch
) -> None:
    web, host, guest = chosen  # noqa: F811
    held: list[int] = []
    close = PostgresEventStore.close

    def counted(store: PostgresEventStore) -> None:  # what each request still holds at its end
        row = store.conn.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
        ).fetchone()
        held.append(row[0] if row else -1)
        close(store)

    monkeypatch.setattr(PostgresEventStore, "close", counted)
    assert new(guest, "begin") == {"reply": "Only the host can do that.", "refused": True}
    assert call(guest, "pick")[0] == 400  # no name: an ApiError inside the lock

    def broken(store: Any, campaign_id: Any) -> None:
        raise RuntimeError("the begin broke")

    open_play = realism_tick.open_play
    monkeypatch.setattr(realism_tick, "open_play", broken)
    assert call(host, "begin")[0] == 500
    monkeypatch.setattr(realism_tick, "open_play", open_play)

    assert not new(guest, "style", style="guided")["refused"]
    assert not new(host, "begin")["refused"]
    assert held and set(held) == {0}
    assert_begun(*settled(web, host))
