"""An invite redeemed on the web takes the game's lock and is refused once the game has
begun, so a begun game never seats a player who holds no person. A refused join leaves
the code unspent. Races are made deterministic by patching a helper inside Begin's
locked span so the join runs there; no model is called."""

from typing import Any

import pytest

from revisionist.engine import realism_tick
from revisionist.engine import scheduler as sch
from revisionist.engine.discord.handlers import BAD_CODE, BROKEN
from revisionist.engine.discord.tables import Invite, Invites
from revisionist.engine.pg_store import PostgresEventStore
from revisionist.engine.web.accounts import WebSeats
from revisionist.engine.web.handlers import JOINED_ZERO
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_begin_races import BUSY, assert_begun, chosen, new, settled  # noqa: F401

BEGUN = "This game has already begun, so it cannot take a new player."


def seated(web: Web, cid: str) -> set[str]:  # noqa: F811
    store = web.app.open()
    try:
        return {s.account_id for s in WebSeats(store.conn).for_campaign(cid)}  # type: ignore[arg-type]
    finally:
        store.close()


def invites(web: Web, cid: str) -> list[Invite]:  # noqa: F811
    store = web.app.open()
    try:
        return Invites(store.conn).all(cid)  # type: ignore[arg-type]
    finally:
        store.close()


def unspent(web: Web, cid: str) -> int:  # noqa: F811
    return sum(i.used_at is None for i in invites(web, cid))


def test_a_join_before_begin_still_seats_the_player(
    chosen: tuple[Web, Client, Client],  # noqa: F811
) -> None:
    web, host, _ = chosen  # noqa: F811
    cid = host.me()["game"]["id"]
    code = new(host, "invite")["code"]
    late, _ = web.signed_up("latecomer")
    assert late.seat("join", code=code) == JOINED_ZERO
    assert len(seated(web, cid)) == 3
    assert unspent(web, cid) == 0


def test_a_code_redeemed_after_begin_is_refused_and_links_no_seat(
    chosen: tuple[Web, Client, Client],  # noqa: F811
) -> None:
    web, host, _ = chosen  # noqa: F811
    cid = host.me()["game"]["id"]
    code = new(host, "invite")["code"]
    assert not new(host, "begin")["refused"]
    late, _ = web.signed_up("latecomer")

    assert late.seat("join", code=code) == BEGUN
    assert len(seated(web, cid)) == 2
    assert unspent(web, cid) == 1  # the refusal did not spend the code
    assert_begun(*settled(web, host))


def test_a_join_racing_begin_is_refused_and_begin_completes(
    chosen: tuple[Web, Client, Client],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web, host, _ = chosen  # noqa: F811
    cid = host.me()["game"]["id"]
    code = new(host, "invite")["code"]
    late, _ = web.signed_up("latecomer")
    joined: list[str] = []
    open_play = realism_tick.open_play

    def join_first(store: Any, campaign_id: Any) -> None:  # after Begin's waiting check
        joined.append(late.seat("join", code=code))
        open_play(store, campaign_id)

    monkeypatch.setattr(realism_tick, "open_play", join_first)

    assert not new(host, "begin")["refused"]
    assert joined == [BUSY["reply"]]
    assert len(seated(web, cid)) == 2
    assert unspent(web, cid) == 1
    assert_begun(*settled(web, host))


def test_a_join_refused_busy_leaves_the_code_to_work_once(
    chosen: tuple[Web, Client, Client],  # noqa: F811
) -> None:
    web, host, _ = chosen  # noqa: F811
    cid = host.me()["game"]["id"]
    code = new(host, "invite")["code"]
    late, _ = web.signed_up("latecomer")
    other, _ = web.signed_up("other")
    holder = web.app.open()
    try:
        table = sch.ScheduleTable(holder.conn)
        assert table.try_lock(cid)
        try:
            assert late.seat("join", code=code) == BUSY["reply"]
        finally:
            table.unlock(cid)
    finally:
        holder.close()

    assert unspent(web, cid) == 1
    assert late.seat("join", code=code) == JOINED_ZERO
    assert other.seat("join", code=code) == BAD_CODE
    assert len(seated(web, cid)) == 3


def test_no_exit_of_a_join_leaves_the_game_busy(
    chosen: tuple[Web, Client, Client],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web, host, _ = chosen  # noqa: F811
    held: list[int] = []
    during: list[int] = []
    close = PostgresEventStore.close
    redeem = Invites.redeem

    def locks(conn: Any) -> int:
        row = conn.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
        ).fetchone()
        return int(row[0]) if row else -1

    def counted(store: PostgresEventStore) -> None:  # what each request still holds at its end
        held.append(locks(store.conn))
        close(store)

    def watched(self: Invites, *args: Any, **kw: Any) -> Any:  # what the join holds as it redeems
        during.append(locks(self.conn))
        return redeem(self, *args, **kw)

    monkeypatch.setattr(PostgresEventStore, "close", counted)
    monkeypatch.setattr(Invites, "redeem", watched)
    first, second, third = (new(host, "invite")["code"] for _ in range(3))
    late, _ = web.signed_up("latecomer")
    broken, _ = web.signed_up("broken")
    after, _ = web.signed_up("after")

    assert late.seat("join", code="not-a-code") == BAD_CODE
    assert late.seat("join", code=first) == JOINED_ZERO

    def fails(self: Invites, *args: Any, **kw: Any) -> Any:
        during.append(locks(self.conn))
        raise RuntimeError("the redeem broke")

    monkeypatch.setattr(Invites, "redeem", fails)
    assert broken.seat("join", code=second) == BROKEN
    monkeypatch.setattr(Invites, "redeem", watched)

    assert not new(late, "pick", name="Joseph Stalin")["refused"]
    assert not new(host, "begin")["refused"]
    assert after.seat("join", code=third) == BEGUN

    assert during == [1, 1]  # the redeem ran with the game's lock held, and only it
    assert held and set(held) == {0}
    assert_begun(*settled(web, host))
