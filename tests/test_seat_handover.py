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

import psycopg
import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, apply
from revisionist.core.ids import EntityId, EventId, OrderId, SeatId, derived_id
from revisionist.core.ontology import Controller, SeatKind
from revisionist.core.project import project
from revisionist.core.realism import actors, pipelines, process
from revisionist.core.realism.agenda import PlayStyle
from revisionist.core.realism.pipeline import StepAction
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
from tests.test_web_answer import _close, _decided, _file, _request, _until_asked
from tests.test_web_held_step import _bram_steps, _held_at_bram, _item, toy  # noqa: F401
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


def test_a_new_player_taking_up_a_seat_gets_none_of_the_last_players_held_work(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    roosevelt, cid = seat_of(game, "roosevelt"), game.campaign
    assert not post(bea, "commit")[1]["refused"]
    for _ in range(2):  # the twin no longer goes through once the first is filed
        assert post(bea, "lever", **BILL)[1]["reply"] == held.HELD
    game_call(bea, "leave")
    assert not post(ada, "commit")[1]["refused"]  # wake 1 opens: the held orders are filed
    store = game.web.app.open()
    try:
        assert held.dropped(store, cid, roosevelt), "Bea's twin was dropped"
        held.hold(store, cid, roosevelt, 1, "lever", BILL, "Bea's last order, still waiting")
    finally:
        store.close()

    code = game_call(ada, "handover", leader=game.ids["roosevelt"])["code"]
    cat, _ = game.web.signed_up("cat")
    assert "Roosevelt" in cat.seat("join", code=code)
    store = game.web.app.open()
    try:
        assert held.listing(store, cid, roosevelt) == []
        assert held.dropped(store, cid, roosevelt) == {}
    finally:
        store.close()
    assert cat.me()["game"]["held"] == []
    _, pages = post(cat, "catchup")
    assert pages["first"] == 0 and all("held_dropped" not in p for p in pages["pages"])

    store = game.web.app.open()
    try:  # what the joiner gives from now on is theirs, and is kept
        mine = held.hold(store, cid, roosevelt, 1, "lever", BILL, "Cat's own order")
    finally:
        store.close()
    assert [x["id"] for x in cat.me()["game"]["held"]] == [mine]


def test_a_seat_is_taken_up_before_db_migrate_has_made_the_held_table(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    game_call(bea, "leave")
    assert not post(ada, "commit")[1]["refused"]
    with psycopg.connect(game.web.db.admin_dsn, autocommit=True) as conn:
        conn.execute("DROP TABLE web_held_orders")
    held.forget_missing()
    try:
        code = game_call(ada, "handover", leader=game.ids["roosevelt"])["code"]
        cat, _ = game.web.signed_up("cat")
        assert "Roosevelt" in cat.seat("join", code=code)
    finally:
        held.forget_missing()
    assert list(state_of(game).handovers) == [EntityId(game.ids["roosevelt"])]


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


# --- a hand-over and the last player's sealed answers and choices ---------------------


@pytest.fixture
def asked(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    """Ada plays Roosevelt and hosts; Bea plays Churchill, whom Roosevelt asks."""
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    bea = game.seat("bea", "churchill")
    make_host(game, ada)
    begin(game)
    return game, ada, bea


def _request_items(client: Client) -> list[dict[str, Any]]:
    return [i for i in realism_of(client)["agenda"]["items"] if i["kind"] == "Request"]


def _join(game: Realism, host: Client, key: str, handle: str) -> Client:
    """A new player redeems the code the host issues for ``key``'s leader."""
    code = game_call(host, "handover", leader=game.ids[key])["code"]
    assert code, f"{key} is not free to hand over"
    player, _ = game.web.signed_up(handle)
    assert player.seat("join", code=code) != handlers.BEGUN
    return player


def _card_says(game: Realism) -> tuple[bool, str]:
    """What the card would answer to Roosevelt's request, read from the state now."""
    order, i = _request(game)
    return process._card_answer(state_of(game), order, order.parts[i])


def _answered(game: Realism, ada: Client, bea: Client) -> None:
    """Bea answers Roosevelt's request the other way from the card, so whose answer
    lands is told apart."""
    _file(game)
    item = _until_asked(game, ada, bea)
    card, _ = _card_says(game)
    status, out = post(bea, "answer", item=item["id"], accept=not card)
    assert status == 200 and not out["refused"], out
    assert _held_answer(state_of(game), game) is (not card)


def _held_answer(state: State, game: Realism) -> bool | None:
    order, i = _request(game)
    return state.routed[order.order_id].parts[i].held_answer


def _closed_with(state: State, *changes: ev.SeatHandover) -> State:
    """The open wake closed by the fold alone, with ``changes`` logged before it, and
    the next one opened."""
    w = state.wake
    assert w is not None and not w.closed
    closing: list[ev.Payload] = [*changes, ev.WakeClosed(wake=w.number)]
    for payload in closing:
        state = apply(state, _event(state, payload))
    opened = ev.WakeOpened(wake=w.number + 1, deadline=w.deadline + timedelta(days=1))
    return apply(state, _event(state, opened))


def _to(game: Realism, key: str, controller: Controller) -> ev.SeatHandover:
    return ev.SeatHandover(entity_id=EntityId(game.ids[key]), controller=controller)


def test_a_new_player_in_the_same_wake_inherits_no_sealed_answer(
    asked: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = asked
    _answered(game, ada, bea)
    (item,) = _request_items(bea)
    game_call(bea, "leave")
    cat = _join(game, ada, "churchill", "cat")
    (pending,) = _request_items(cat)
    assert pending["id"] == item["id"]
    assert pending["cause"] is None, pending["cause"]
    assert not post(ada, "commit")[1]["refused"]  # the close hands Churchill to Cat
    order, i = _request(game)
    assert _decided(game, order) == [], "the request was decided before Cat held it"
    (mine,) = _request_items(cat)
    assert mine["id"] == item["id"] and mine["cause"] is None, mine
    assert _held_answer(state_of(game), game) is None
    card = _card_says(game)
    due = process.request_due(state_of(game), order, i)
    assert due is not None
    for _ in range(6):
        today = state_of(game).in_world_date
        assert today is not None
        if today >= due:
            break
        _close(ada, cat)
    else:
        raise AssertionError("the due day never came")
    (decided,) = _decided(game, order)
    assert isinstance(decided.payload, ev.InfluenceDecided)
    assert (decided.payload.accepted, decided.payload.reason) == card


def test_a_leave_keeps_the_sealed_answer_and_a_later_join_clears_it(
    asked: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = asked
    _answered(game, ada, bea)
    given = _held_answer(state_of(game), game)
    left = _closed_with(state_of(game), _to(game, "churchill", Controller.AI))
    assert _held_answer(left, game) is given
    joined = _closed_with(left, _to(game, "churchill", Controller.HUMAN))
    assert joined.seats[seat_of(game, "churchill")].controller is Controller.HUMAN
    assert _held_answer(joined, game) is None


def test_a_hand_over_keeps_the_sealed_answers_of_the_players_who_stay(
    asked: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = asked
    _answered(game, ada, bea)
    given = _held_answer(state_of(game), game)
    state = _closed_with(state_of(game), _to(game, "wheeler", Controller.HUMAN))
    assert _held_answer(state, game) is given


def test_a_pending_hand_over_of_another_leader_leaves_the_players_answer_shown(
    asked: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = asked
    _answered(game, ada, bea)
    (before,) = _request_items(bea)
    assert before["cause"] is not None, before
    _join(game, ada, "wheeler", "dan")
    (after,) = _request_items(bea)
    assert after["cause"] == before["cause"], after


def test_a_join_keeps_the_answer_a_decided_request_was_given(
    asked: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = asked
    _answered(game, ada, bea)
    given = _held_answer(state_of(game), game)
    state = state_of(game)
    order, i = _request(game)
    assert state.in_world_date is not None
    decided = ev.InfluenceDecided(
        order_id=order.order_id, part=i, on=state.in_world_date, accepted=bool(given), reason="-"
    )
    state = apply(state, _event(state, decided))
    left = _closed_with(state, _to(game, "churchill", Controller.AI))
    joined = _closed_with(left, _to(game, "churchill", Controller.HUMAN))
    assert _held_answer(joined, game) is given


def _held_choice(state: State, order_id: OrderId) -> Any:
    return state.orders[order_id].held_choice


def _chose(game: Realism, ada: Client, bram: Client) -> OrderId:
    """Bram refuses Ada's levy at his step, where the card would pass it."""
    order_id = _held_at_bram(game, ada, bram)
    assert not post(bram, "step", order_id=_item(bram)["id"], action="refuse")[1]["refused"]
    assert _held_choice(state_of(game), order_id) is not None
    return order_id


def test_a_new_player_inherits_no_sealed_step_choice(
    toy: tuple[Realism, Client, Client],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipelines, "_policy", lambda *_a: (StepAction.PASS, {}))
    game, ada, bram = toy
    order_id = _chose(game, ada, bram)
    item = _item(bram)
    game_call(bram, "leave")
    cat = _join(game, ada, "bram", "cat")
    pending = _item(cat)
    assert pending["id"] == item["id"]
    assert pending["cause"] is None, pending["cause"]
    assert not post(ada, "commit")[1]["refused"]  # the close hands Bram to Cat
    for _ in range(6):
        if _bram_steps(game, order_id):
            break
        mine = _item(cat)
        assert mine["id"] == item["id"] and mine["cause"] is None, mine
        _close(ada, cat)
    (taken,) = _bram_steps(game, order_id)
    assert taken.outcome.action is StepAction.PASS, "the last player's choice was taken"


def test_a_leave_keeps_the_step_choice_and_a_later_join_clears_it(
    toy: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bram = toy
    order_id = _chose(game, ada, bram)
    left = _closed_with(state_of(game), _to(game, "bram", Controller.AI))
    assert _held_choice(left, order_id) is not None
    joined = _closed_with(left, _to(game, "bram", Controller.HUMAN))
    assert joined.seats[seat_of(game, "bram")].controller is Controller.HUMAN
    assert _held_choice(joined, order_id) is None


def test_a_hand_over_keeps_the_step_choices_of_the_players_who_stay(
    toy: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bram = toy
    order_id = _chose(game, ada, bram)
    chosen = _held_choice(state_of(game), order_id)
    state = _closed_with(state_of(game), _to(game, "cora", Controller.HUMAN))
    assert _held_choice(state, order_id) == chosen


def test_a_pending_hand_over_of_another_leader_leaves_the_players_choice_shown(
    toy: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bram = toy
    _chose(game, ada, bram)
    before = _item(bram)
    assert before["cause"] is not None, before
    _join(game, ada, "cora", "dan")
    after = _item(bram)
    assert after["cause"] == before["cause"], after
