"""Undo a pick: a player may give up their person until the host begins the game.

Fake transports answer; no model is called.
"""

from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, replay
from revisionist.core.ids import CampaignId, EntityId, EventId, SeatId, derived_id
from revisionist.core.realism.agenda import PlayStyle
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.engine import campaign as cmp
from revisionist.engine import session_zero as sz
from revisionist.engine.pg_store import PostgresEventStore
from revisionist.engine.store import EventStore, MemoryStore, StoreError, load_state
from revisionist.engine.web import reveal
from tests.test_session_zero_steps import A, Table, _florence
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_pick import HULL, PLACED, SLICE, Fake, new

CHURCHILL = "Winston Churchill"


def _host(web: Web, fake: Fake) -> Client:  # noqa: F811
    web.app.transport_factory = lambda: fake
    web.app.spawn = lambda run: run()
    client, _ = web.signed_up("ada")
    assert not new(client, "ready", world=SLICE)["refused"]
    return client


def _joined(web: Web, host: Client, name: str) -> Client:  # noqa: F811
    code = new(host, "invite")["code"]
    client, _ = web.signed_up(name)
    client.seat("join", code=code)
    assert client.me()["game"]["phase"] == "session_zero"
    return client


def _state(web: Web, client: Client) -> State:  # noqa: F811
    store = web.app.open()
    try:
        return load_state(store, client.me()["game"]["id"])
    finally:
        store.close()


def _events(web: Web, client: Client) -> list[ev.Event]:  # noqa: F811
    store = web.app.open()
    try:
        return list(store.read(client.me()["game"]["id"]))
    finally:
        store.close()


def _taken(client: Client, name: str) -> bool:
    roster = client.me()["game"]["view"]["roster"]
    return bool(next(c for c in roster if c["name"] == name)["taken"])


# --- the web call ------------------------------------------------------------------


def test_unpick_frees_the_seat_and_the_person(web: Web) -> None:  # noqa: F811
    client = _host(web, Fake(PLACED))
    assert not new(client, "pick", name=CHURCHILL)["refused"]
    assert not new(client, "style", style="beginner")["refused"]
    out = new(client, "unpick")
    assert out == {"reply": f"You no longer play {CHURCHILL}. Choose again.", "refused": False}
    assert client.me()["game"]["view"]["seat"] is None
    assert not _taken(client, CHURCHILL)
    state = _state(web, client)
    assert not state.seats and not state.styles and not state.standing
    (person,) = (c for c in state.roster.values() if state.entities[c.entity_id].name == CHURCHILL)
    assert person.claimed_by is None


def test_a_released_person_is_picked_again_with_no_model_call(web: Web) -> None:  # noqa: F811
    fake = Fake(PLACED)
    client = _host(web, fake)
    assert not new(client, "pick", name=HULL)["refused"]
    assert fake.calls == ["character_pick", "build"]
    assert not new(client, "unpick")["refused"]
    assert new(client, "pick", name=HULL) == {"reply": f"You are {HULL}.", "refused": False}
    assert fake.calls == ["character_pick", "build"]  # the card stays on the roster


def test_a_released_seat_can_take_someone_else(web: Web) -> None:  # noqa: F811
    client = _host(web, Fake(PLACED))
    assert not new(client, "pick", name=CHURCHILL)["refused"]
    assert not new(client, "unpick")["refused"]
    assert new(client, "pick", name=HULL)["reply"] == f"You are {HULL}."
    assert not _taken(client, CHURCHILL)


def test_unpick_with_no_pick_is_refused(web: Web) -> None:  # noqa: F811
    client = _host(web, Fake(PLACED))
    out = new(client, "unpick")
    assert out == {"reply": "You have not chosen anyone yet.", "refused": True}


def test_begin_waits_again_after_an_unpick(web: Web) -> None:  # noqa: F811
    client = _host(web, Fake(PLACED))
    assert not new(client, "pick", name=CHURCHILL)["refused"]
    assert not new(client, "unpick")["refused"]
    out = new(client, "begin")
    assert out == {"reply": "Still to choose: 1 player(s).", "refused": True}


def test_no_unpick_once_the_game_has_begun(web: Web) -> None:  # noqa: F811
    client = _host(web, Fake(PLACED))
    assert not new(client, "pick", name=CHURCHILL)["refused"]
    assert not new(client, "begin")["refused"]
    status, out = client.call("/api/new/unpick", {})
    assert status == 400 and "not choosing its people" in str(out)
    assert client.me()["game"]["view"]["seat"]["name"] == CHURCHILL


def test_the_host_can_release_another_players_pick(web: Web) -> None:  # noqa: F811
    host = _host(web, Fake(PLACED))
    guest = _joined(web, host, "bram")
    assert not new(guest, "pick", name=CHURCHILL)["refused"]
    out = new(host, "unpick", name=CHURCHILL)
    assert out == {"reply": f"{CHURCHILL} is free again.", "refused": False}
    assert guest.me()["game"]["view"]["seat"] is None


def test_only_the_host_releases_someone_else(web: Web) -> None:  # noqa: F811
    host = _host(web, Fake(PLACED))
    guest = _joined(web, host, "bram")
    assert not new(host, "pick", name=CHURCHILL)["refused"]
    out = new(guest, "unpick", name=CHURCHILL)
    assert out == {"reply": "Only the host can do that.", "refused": True}
    assert host.me()["game"]["view"]["seat"]["name"] == CHURCHILL


def test_the_host_naming_someone_no_player_holds_is_refused(web: Web) -> None:  # noqa: F811
    host = _host(web, Fake(PLACED))
    out = new(host, "unpick", name=CHURCHILL)
    assert out == {"reply": f"No player holds {CHURCHILL}.", "refused": True}


# --- the engine --------------------------------------------------------------------


def test_claim_ids_count_the_releases_so_a_race_still_fails_at_the_store(
    web: Web,  # noqa: F811
) -> None:
    host = _host(web, Fake(PLACED))
    guest = _joined(web, host, "bram")
    assert not new(host, "pick", name=CHURCHILL)["refused"]
    assert not new(host, "unpick")["refused"]
    assert not new(guest, "pick", name=CHURCHILL)["refused"]
    log = _events(web, host)
    cid = CampaignId(host.me()["game"]["id"])
    claims = [e for e in log if isinstance(e.payload, ev.CharacterClaimed)]
    (release,) = [e for e in log if isinstance(e.payload, ev.CharacterReleased)]
    assert isinstance(release.payload, ev.CharacterReleased)
    person = release.payload.entity_id
    first = claims[0].payload
    assert isinstance(first, ev.CharacterClaimed)
    assert [e.event_id for e in claims] == [
        EventId(derived_id(cid, "claim", person)),  # an old game's first claim keeps its id
        EventId(derived_id(cid, "claim", person, 1)),
    ]
    assert release.event_id == EventId(derived_id(cid, "release", person, 0))
    state = _state(web, host)
    racer = claims[-1].model_copy(
        update={
            "seq": state.last_seq + 1,
            "payload": ev.CharacterClaimed(seat_id=first.seat_id, entity_id=person),
        }
    )
    store = web.app.open()
    try:
        with pytest.raises(StoreError):
            store.append(racer)  # a second writer who saw the same release
    finally:
        store.close()


def _released(state: State, seat: SeatId, person: EntityId) -> ev.Event:
    return ev.Event(
        event_id=EventId(derived_id(state.campaign_id, "release", person, 0)),
        campaign_id=state.campaign_id,
        seq=state.last_seq + 1,
        tick=state.tick,
        actor=seat,
        scope=PUBLIC,
        payload=ev.CharacterReleased(seat_id=seat, entity_id=person),
        versions=cmp.versions(),
    )


def test_the_fold_refuses_a_release_that_names_the_wrong_person(web: Web) -> None:  # noqa: F811
    client = _host(web, Fake(PLACED))
    assert not new(client, "pick", name=CHURCHILL)["refused"]
    state = _state(web, client)
    (seat,) = state.seats.values()
    other = next(c for c in state.roster if c != seat.embodies)
    with pytest.raises(FoldError, match="does not play"):
        replay([_released(state, seat.seat_id, other)], initial=state)


def test_the_fold_refuses_a_release_once_play_has_begun(web: Web) -> None:  # noqa: F811
    client = _host(web, Fake(PLACED))
    assert not new(client, "pick", name=CHURCHILL)["refused"]
    assert not new(client, "begin")["refused"]
    state = _state(web, client)
    (seat,) = (s for s in state.seats.values() if state.entities[s.embodies].name == CHURCHILL)
    with pytest.raises(FoldError, match="Session Zero"):
        replay([_released(state, seat.seat_id, seat.embodies)], initial=state)


def test_a_pick_is_final_outside_a_realism_game() -> None:
    store, table = MemoryStore(), Table()
    c = _florence(store, table)
    sz.claim(store, c, A, "Lorenzo de' Medici")
    with pytest.raises(sz.StepRefusedError, match="final"):
        sz.release(store, c, A)
    state = load_state(store, c)
    with pytest.raises(FoldError, match="realism"):
        replay([_released(state, A, state.seats[A].embodies)], initial=state)


# --- races (each lands another writer's event between the check and the write) -------


def _race(monkeypatch: pytest.MonkeyPatch, store: EventStore, cid: CampaignId, racer: Any) -> None:
    """Make ``racer(state)`` land just after ``release`` reads the game, before it writes."""
    real = sz._releases

    def late(store_: EventStore, campaign_id: CampaignId, entity: EntityId) -> int:
        count = real(store_, campaign_id, entity)
        state = load_state(store, cid)
        store.append_all(sz._events(state, cid, [racer(state)]))
        return count

    monkeypatch.setattr(sz, "_releases", late)


def _seated_store(web: Web) -> tuple[Client, PostgresEventStore, CampaignId, SeatId]:  # noqa: F811
    client = _host(web, Fake(PLACED))
    assert not new(client, "pick", name=CHURCHILL)["refused"]
    cid = CampaignId(client.me()["game"]["id"])
    store = web.app.open()
    (seat,) = load_state(store, cid).seats
    return client, store, cid, seat


def test_a_release_racing_begin_is_refused_and_the_game_still_loads(
    web: Web,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store, cid, seat = _seated_store(web)
    try:
        _race(monkeypatch, store, cid, lambda state: (ev.SessionZeroClosed(), PUBLIC, None))
        with pytest.raises(sz.StepRefusedError, match="has begun"):
            sz.release(store, cid, seat)
        state = load_state(store, cid)  # no release after the close
        assert seat in state.seats
    finally:
        store.close()


def test_two_releases_of_one_pick_land_once(
    web: Web,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store, cid, seat = _seated_store(web)
    try:
        person = load_state(store, cid).seats[seat].embodies
        _race(
            monkeypatch,
            store,
            cid,
            lambda state: (ev.CharacterReleased(seat_id=seat, entity_id=person), PUBLIC, seat),
        )
        with pytest.raises(sz.StepRefusedError, match="already given up"):
            sz.release(store, cid, seat)
        state = load_state(store, cid)
        assert seat not in state.seats
        log = list(store.read(cid))
        assert sum(isinstance(e.payload, ev.CharacterReleased) for e in log) == 1
    finally:
        store.close()


def test_a_release_racing_an_unrelated_write_asks_for_a_retry(
    web: Web,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store, cid, seat = _seated_store(web)
    try:
        _race(
            monkeypatch,
            store,
            cid,
            lambda state: (ev.PlayStyleSet(seat_id=seat, style=PlayStyle.GUIDED), PUBLIC, seat),
        )
        with pytest.raises(sz.StepRefusedError, match="Try again"):
            sz.release(store, cid, seat)
        assert seat in load_state(store, cid).seats
    finally:
        store.close()


def test_the_reveal_credits_no_style_from_a_released_pick(web: Web) -> None:  # noqa: F811
    client = _host(web, Fake(PLACED))
    assert not new(client, "pick", name=CHURCHILL)["refused"]
    assert not new(client, "style", style="beginner")["refused"]
    assert not new(client, "unpick")["refused"]
    assert not new(client, "pick", name=HULL)["refused"]
    store = web.app.open()
    try:
        cid = CampaignId(client.me()["game"]["id"])
        (seat,) = reveal.build(load_state(store, cid), store.read(cid))["seats"]
    finally:
        store.close()
    assert seat["person"] == HULL and seat["styles"] == []
