"""Joining and leaving at a wake boundary (JNL).

A leader changes hands only when a wake closes. ``SeatHandover`` lands when a player
leaves, or when a new player redeems the code the host issued for a code-run leader;
the fold holds it and applies it at ``WakeClosed``. A leaver's seat is run by the code
from the next wake on, keeps its orders in flight and holds no wake open; a joiner
counts from the next wake and reads a catch-up from wake 0. The engine half plays on
the async table; the web half on the test server, as ``tests/test_web_held_orders.py``.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, apply
from revisionist.core.ids import EntityId, EventId, SeatId, derived_id
from revisionist.core.ontology import Controller, SeatKind
from revisionist.core.project import project
from revisionist.core.realism import actors
from revisionist.core.realism.agenda import PlayStyle
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, wake
from revisionist.engine.discord.tables import Invites
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import dossiers, handlers, held, wake_api
from tests.async_table import AsyncTable
from tests.test_engine_v2_wake import CAMPAIGN
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, log_of, seat_of, state_of

WORLD = "engine-v2-slice-1941"
BILL = {"lever": "send_bill", "params": {"bill": "neutrality_revision"}}


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncTable:
    return AsyncTable(MemoryStore(), monkeypatch, tmp_path)


def leave(t: AsyncTable, seat: SeatId) -> None:
    with t.ids_drawn.drawn_by(seat):
        wake.leave(t.store, CAMPAIGN, seat, t.now)


def hand_over(t: AsyncTable, key: str) -> SeatId:
    return wake.hand_over(t.store, CAMPAIGN, t.entity(key))


def early(t: AsyncTable) -> Any:
    """A time well before the open wake's deadline."""
    open_wake = t.state.wake
    assert open_wake is not None and not open_wake.closed
    return open_wake.deadline - timedelta(hours=6)


def handovers(t: AsyncTable) -> list[ev.Event]:
    return [e for e in t.store.read(CAMPAIGN) if isinstance(e.payload, ev.SeatHandover)]


# --- leaving ---------------------------------------------------------------------------


def test_a_leave_lands_at_the_close_not_before(table: AsyncTable) -> None:
    t = table
    t.open_play()
    leave(t, t.churchill)
    mid = t.state
    assert mid.seats[t.churchill].controller is Controller.HUMAN
    assert t.churchill in cmp.human_seats(mid)
    t.close()
    after = t.state
    assert after.seats[t.churchill].controller is Controller.AI
    assert after.seats[t.churchill].kind is SeatKind.PLAYER
    assert cmp.human_seats(after) == [t.fdr]
    assert not after.handovers


def test_a_leavers_later_wakes_close_without_waiting_on_them(table: AsyncTable) -> None:
    t = table
    t.open_play()
    leave(t, t.churchill)
    t.close()
    for _ in range(2):
        t.commit(t.fdr)
        assert wake.wake_due(t.state, early(t))
        t.close(early(t))
        closing = [
            p for p in (e.payload for e in t.store.read(CAMPAIGN)) if isinstance(p, ev.WakeClosed)
        ][-1]
        assert closing.timed_out == () and closing.how == "all_committed", closing
    aide = [
        p
        for p in (e.payload for e in t.store.read(CAMPAIGN))
        if isinstance(p, ev.WakeCommitted) and p.by_aide and p.seat_id == t.churchill
    ]
    assert aide == []


def test_leaving_seals_the_open_wake_for_the_leaver(table: AsyncTable) -> None:
    t = table
    t.open_play()
    leave(t, t.churchill)
    open_wake = t.state.wake
    assert open_wake is not None and open_wake.committed == {t.churchill}
    t.commit(t.fdr)
    assert wake.wake_due(t.state, early(t))


def test_a_leaver_keeps_its_orders_in_flight(table: AsyncTable) -> None:
    t = table
    t.open_play()
    t.file(t.churchill, *t.aide_orders()[0])
    (order,) = [o for o in t.state.routed.values() if o.issuer == t.churchill]
    leave(t, t.churchill)
    t.close()
    t.commit(t.fdr)
    t.close(early(t))
    state = t.state
    assert order.order_id in state.routed
    assert t.churchill in actors.readers(state)


def test_the_leader_looks_the_same_to_the_others(table: AsyncTable) -> None:
    t = table
    t.open_play()
    before = project(t.state, t.fdr).seats[t.churchill]
    leave(t, t.churchill)
    pending = project(t.state, t.fdr)
    assert "handovers" not in pending.model_dump()
    t.close()
    assert project(t.state, t.fdr).seats[t.churchill] == before
    (landed,) = handovers(t)
    assert landed.scope.known_by == frozenset({t.churchill})
    seen = catchup.seat_events(t.store, CAMPAIGN, t.fdr, 0, 0)
    assert not [s for s in seen if isinstance(s.event.payload, ev.SeatHandover)]


def test_leave_refuses_a_seat_nobody_plays(table: AsyncTable) -> None:
    t = table
    t.open_play()
    leave(t, t.churchill)
    logged = len(list(t.store.read(CAMPAIGN)))
    with pytest.raises(ValueError):
        leave(t, t.churchill)
    assert len(list(t.store.read(CAMPAIGN))) == logged  # refused before anything is logged
    assert t.state.seats[t.churchill].controller is Controller.HUMAN


# --- joining ---------------------------------------------------------------------------


def test_a_joiner_counts_from_the_next_wake(table: AsyncTable) -> None:
    t = table
    t.open_play()
    joiner = hand_over(t, "wheeler")
    assert joiner == SeatId(derived_id(CAMPAIGN, "seat", t.entity("wheeler")))
    assert wake.from_wake(t.state) == 1
    held_seat = t.state.seats.get(joiner)
    assert held_seat is None or held_seat.controller is Controller.AI
    t.commit(t.fdr)
    t.commit(t.churchill)
    assert wake.wake_due(t.state, early(t))  # the joiner holds this wake open for no one
    t.close(early(t))
    state = t.state
    seat = state.seats[joiner]
    assert (seat.controller, seat.kind) == (Controller.HUMAN, SeatKind.PLAYER)
    assert seat.embodies == t.entity("wheeler")
    assert joiner in cmp.human_seats(state)
    assert state.styles[joiner] is PlayStyle.BEGINNER
    t.commit(t.fdr)
    t.commit(t.churchill)
    assert not wake.wake_due(t.state, early(t))  # from here the wake waits for them too
    with t.ids_drawn.drawn_by(joiner):
        assert wake.commit(t.store, CAMPAIGN, joiner, t.now)
    assert wake.wake_due(t.state, early(t))


def test_the_leaders_free_to_hand_over_are_the_code_run_ones(table: AsyncTable) -> None:
    t = table
    t.open_play()
    assert wake.leaders(t.state) == [t.entity("wheeler")]
    with pytest.raises(ValueError):
        hand_over(t, "roosevelt")
    leave(t, t.churchill)
    assert set(wake.leaders(t.state)) == {t.entity("wheeler"), t.entity("churchill")}
    hand_over(t, "wheeler")
    assert wake.leaders(t.state) == [t.entity("churchill")]


def test_a_left_seat_handed_on_goes_back_to_human(table: AsyncTable) -> None:
    t = table
    t.open_play()
    leave(t, t.churchill)
    t.close()
    assert hand_over(t, "churchill") == t.churchill
    assert wake.from_wake(t.state) == 2
    t.commit(t.fdr)
    t.close(early(t))
    state = t.state
    assert state.seats[t.churchill].controller is Controller.HUMAN
    assert cmp.human_seats(state) == sorted([t.fdr, t.churchill])


def _event(state: State, payload: ev.Payload) -> ev.Event:
    return ev.Event(
        event_id=EventId(derived_id(state.campaign_id, "probe", state.last_seq)),
        campaign_id=state.campaign_id,
        seq=state.last_seq + 1,
        tick=state.tick,
        scope=PUBLIC,
        payload=payload,
        versions=cmp.versions(),
    )


def test_the_fold_refuses_a_handover_that_changes_nothing(table: AsyncTable) -> None:
    t = table
    t.open_play()
    state = t.state
    to_human = ev.SeatHandover(entity_id=t.entity("roosevelt"), controller=Controller.HUMAN)
    with pytest.raises(FoldError):
        apply(state, _event(state, to_human))
    to_code = ev.SeatHandover(entity_id=t.entity("wheeler"), controller=Controller.AI)
    with pytest.raises(FoldError):
        apply(state, _event(state, to_code))
    nobody = ev.SeatHandover(entity_id=EntityId("no-such-person"), controller=Controller.HUMAN)
    with pytest.raises(FoldError):
        apply(state, _event(state, nobody))


# --- the human-seat cap ----------------------------------------------------------------


def capped(state: State, seats: int) -> ev.Event:
    """The table's human-seat cap set to ``seats``, as a settings change lands it."""
    settings = state.settings.model_copy(update={"max_human_seats": seats})
    return _event(state, ev.SettingsSet(settings=settings))


def logged(t: AsyncTable) -> int:
    return len(list(t.store.read(CAMPAIGN)))


def test_a_table_at_the_cap_has_no_leader_to_hand_over(table: AsyncTable) -> None:
    t = table
    t.open_play()
    t.store.append_all([capped(t.state, 2)])  # Roosevelt and Churchill fill it
    assert wake.leaders(t.state) == []
    before = logged(t)
    with pytest.raises(ValueError):
        hand_over(t, "wheeler")
    assert logged(t) == before  # refused before anything is logged
    assert not t.state.handovers  # and the game still loads


def test_the_cap_counts_the_players_after_the_close(table: AsyncTable) -> None:
    t = table
    t.open_play()
    t.store.append_all([capped(t.state, 2)])
    leave(t, t.churchill)  # one player once this wake closes
    assert set(wake.leaders(t.state)) == {t.entity("wheeler"), t.entity("churchill")}
    hand_over(t, "wheeler")  # two again
    assert wake.leaders(t.state) == []
    before = logged(t)
    with pytest.raises(ValueError):
        hand_over(t, "churchill")
    assert logged(t) == before
    t.commit(t.fdr)
    t.close(early(t))
    state = t.state
    assert cmp.human_seats(state) == sorted([t.fdr, wake.seat_for(state, t.entity("wheeler"))])
    assert state.seats[t.churchill].controller is Controller.AI


def test_an_event_the_fold_refuses_is_never_stored(table: AsyncTable) -> None:
    t = table
    t.open_play()
    state = t.state
    before = logged(t)
    played = ev.SeatHandover(entity_id=t.entity("roosevelt"), controller=Controller.HUMAN)
    with pytest.raises(FoldError):
        wake._land(t.store, state, played)
    assert logged(t) == before
    assert t.state.last_seq == state.last_seq  # the game still loads


# --- on the web ------------------------------------------------------------------------


@pytest.fixture
def duo(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    """Ada plays Churchill and hosts; Bea plays Roosevelt."""
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "churchill")
    bea = game.seat("bea", "roosevelt")
    make_host(game, ada)
    begin(game)
    return game, ada, bea


def game_call(client: Client, action: str, **body: Any) -> dict[str, Any]:
    status, out = client.call(f"/api/game/{action}", body)
    assert status == 200, out
    return dict(out)


def test_leaving_on_the_web_hands_the_leader_to_the_code(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    roosevelt = seat_of(game, "roosevelt")
    assert not post(ada, "commit")[1]["refused"]
    out = game_call(bea, "leave")
    assert not out["refused"] and out["reply"].startswith("You have left")
    assert bea.me()["game"] is None
    state = state_of(game)
    assert state.wake is not None and state.wake.number == 1  # the leave sealed wake 0
    assert state.seats[roosevelt].controller is Controller.AI
    assert realism_of(ada)["wake"]["humans"] == 1
    assert not post(ada, "commit")[1]["refused"]
    assert realism_of(ada)["wake"]["wake"] == 2  # wake 1 closed without waiting


def test_only_the_host_lists_and_hands_over_leaders(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    for action, body in (("handover-list", {}), ("handover", {"leader": "x"})):
        out = game_call(bea, action, **body)
        assert out["refused"], out
    out = game_call(ada, "handover-list")
    assert set(out) == {"reply", "refused", "leaders"} and not out["refused"]
    wheeler = EntityId(game.ids["wheeler"])
    assert out["leaders"] == [
        {
            "key": wheeler,
            "name": state_of(game).entities[wheeler].name,
            "office": state_of(game).cards[wheeler].office,
        }
    ]
    refused = game_call(ada, "handover", leader=game.ids["roosevelt"])
    assert refused["refused"] and refused["code"] is None and refused["from_wake"] is None


def test_a_handed_leader_joins_at_the_next_wake_with_a_catch_up_from_wake_0(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    roosevelt = seat_of(game, "roosevelt")
    game_call(bea, "leave")  # wake 0: Bea's leave seals it for her
    assert not post(ada, "commit")[1]["refused"]  # wake 1 opens, Roosevelt code-run
    listed = game_call(ada, "handover-list")["leaders"]
    assert game.ids["roosevelt"] in [x["key"] for x in listed]
    out = game_call(ada, "handover", leader=game.ids["roosevelt"])
    assert set(out) == {"reply", "refused", "code", "from_wake"}
    assert not out["refused"] and out["from_wake"] == 2
    cat, _ = game.web.signed_up("cat")
    joined = cat.seat("join", code=out["code"])
    assert "Roosevelt" in joined, joined
    assert realism_of(ada)["wake"]["humans"] == 1  # not counted in wake 1
    _, early_done = post(cat, "commit")
    assert early_done == {"reply": wake_api.JOINING, "refused": True}
    status, filed = post(cat, "lever", **BILL)
    assert status == 200 and filed["reply"] == held.HELD, filed  # held for wake 2
    assert not post(ada, "commit")[1]["refused"]  # wake 1 closes without the joiner
    state = state_of(game)
    assert state.wake is not None and state.wake.number == 2
    assert state.seats[roosevelt].controller is Controller.HUMAN
    assert realism_of(ada)["wake"]["humans"] == 2
    bills = [
        e
        for e in log_of(game)
        if isinstance(e.payload, ev.OrderDrafted) and e.payload.order.lever == "send_bill"
    ]
    assert len(bills) == 1
    _, pages = post(cat, "catchup")
    assert (pages["first"], pages["last"]) == (0, 1)
    expected = dossiers.for_people(state_of(game), log_of(game)).get(
        EntityId(game.ids["roosevelt"]), dossiers.empty_dossier()
    )
    assert realism_of(cat)["dossier"] == expected
    assert not post(ada, "commit")[1]["refused"]
    assert realism_of(ada)["wake"]["wake"] == 2  # wake 2 waits for the joiner
    assert not post(cat, "commit")[1]["refused"]
    assert realism_of(ada)["wake"]["wake"] == 3


def test_a_code_spent_once_the_table_is_full_is_refused_and_stores_nothing(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    roosevelt = seat_of(game, "roosevelt")
    game_call(bea, "leave")  # wake 0: Bea's leave seals it for her
    assert not post(ada, "commit")[1]["refused"]  # wake 1 opens, Roosevelt code-run
    store = game.web.app.open()
    try:
        store.append_all([capped(load_state(store, game.campaign), 2)])
    finally:
        store.close()
    codes = {
        who: game_call(ada, "handover", leader=game.ids[who])["code"]
        for who in ("wheeler", "roosevelt")
    }
    assert all(codes.values()), codes  # one seat is left, and either leader may take it
    cat, _ = game.web.signed_up("cat")
    assert "Wheeler" in cat.seat("join", code=codes["wheeler"])
    listed = game_call(ada, "handover-list")
    assert listed["leaders"] == [] and not listed["refused"]
    refused = game_call(ada, "handover", leader=game.ids["roosevelt"])
    assert refused == {
        "reply": wake_api.NOT_FREE,
        "refused": True,
        "code": None,
        "from_wake": None,
    }
    dan, _ = game.web.signed_up("dan")
    assert dan.seat("join", code=codes["roosevelt"]) == handlers.BEGUN
    state = state_of(game)  # the game still loads
    assert list(state.handovers) == [EntityId(game.ids["wheeler"])]
    store = game.web.app.open()
    try:
        issued = Invites(store.conn).all(game.campaign)
    finally:
        store.close()
    assert [i.used_at for i in issued if i.seat_id == roosevelt][-1] is None  # not spent
