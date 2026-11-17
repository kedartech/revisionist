"""Orders after you commit join the next wake (HLD).

A sealed action given after the seat has committed, or while its wake is closing, is
held in ``web_held_orders`` and filed when the next wake opens, in the order given and
before that wake's offers. One that no longer goes through is dropped, with a line on
the seat's catch-up page for that wake. Same harness as ``tests/test_web_wake.py``.
"""

import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, cast

import psycopg
import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, SeatId
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.pipeline import StepAction
from revisionist.engine import campaign as cmp
from revisionist.engine import directive, orders_reader, realism_tick
from revisionist.engine import scheduler as sch
from revisionist.engine import wake as wk
from revisionist.engine.store import EventStore
from revisionist.engine.web import held, server
from revisionist.engine.web.realism_api import OrderProposal
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, log_of, seat_of, state_of

WORLD = "engine-v2-slice-1941"
BILL = {"lever": "send_bill", "params": {"bill": "neutrality_revision"}}


@pytest.fixture
def duo(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    bea = game.seat("bea", "churchill")
    make_host(game, ada)
    begin(game)
    return game, ada, bea


def both_commit(ada: Client, bea: Client) -> None:
    for who in (ada, bea):
        status, out = post(who, "commit")
        assert status == 200 and not out["refused"], out


def held_of(client: Client) -> list[dict[str, Any]]:
    return list(client.me()["game"]["held"])


def bills(game: Realism) -> list[int]:
    """The position in the log of each send_bill order drafted."""
    return [
        i
        for i, e in enumerate(log_of(game))
        if isinstance(e.payload, ev.OrderDrafted) and e.payload.order.lever == "send_bill"
    ]


def position(game: Realism, kind: type, **match: Any) -> int:
    for i, e in enumerate(log_of(game)):
        p = e.payload
        if isinstance(p, kind) and all(getattr(p, k) == v for k, v in match.items()):
            return i
    raise AssertionError(f"no {kind.__name__} {match}")


def scheduler_close(game: Realism) -> None:
    """The deadline close, with no client: the scheduler alone."""
    wake = state_of(game).wake
    assert wake is not None and not wake.closed
    store = game.web.app.open()
    try:
        at = wake.deadline + timedelta(minutes=1)
        out = sch.run(
            store,
            lambda: at,
            offline=True,
            transport_factory=cmp.live_transport,
            briefings=game.web.app.briefings,
            warn=lambda _m: None,
            campaign=game.campaign,
        )
    finally:
        store.close()
    assert [o.action for o in out] == [sch.Action.TICKED], out


# --- held after commit, filed at the next opening -------------------------------------


def test_an_order_held_in_wake_4_is_filed_at_wake_5s_opening_with_nobody_present(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    for _ in range(4):
        both_commit(ada, bea)
    assert realism_of(ada)["wake"]["wake"] == 4
    assert not post(ada, "commit")[1]["refused"]
    status, out = post(ada, "lever", **BILL)
    assert status == 200 and out["reply"] == held.HELD and out["refused"] is False, out
    assert isinstance(out["held"], int)
    assert bills(game) == [], "nothing is filed into a wake the seat has sealed"
    (listed,) = held_of(ada)
    assert listed == {"id": out["held"], "label": "Send a bill to Congress", "wake": 4}
    assert held_of(bea) == [], "only the seat's own payload lists its held orders"

    scheduler_close(game)

    (filed,) = bills(game)
    assert filed > position(game, ev.WakeClosed, wake=4)
    assert filed > position(game, ev.WakeOpened, wake=5)
    assert filed < position(game, ev.OptionsOffered, wake=5), "filed before the offers"
    order = log_of(game)[filed]
    assert order.actor == seat_of(game, "roosevelt")
    assert held_of(ada) == []


def mark_closing(conn: psycopg.Connection[Any], campaign: CampaignId) -> None:
    """Hold the close's own mark on ``conn``, as a running close does."""
    conn.execute("SELECT pg_advisory_lock(%s, hashtext(%s))", (held.CLOSE_CLASS, campaign))


def test_a_held_order_arriving_while_the_close_lock_is_held_is_not_lost(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    with psycopg.connect(game.web.db.app_dsn, autocommit=True) as other:
        closer = sch.ScheduleTable(other)
        assert closer.try_lock(game.campaign)
        mark_closing(other, game.campaign)
        try:
            _, out = post(ada, "lever", **BILL)
            assert out["reply"] == held.HELD and out["refused"] is False, out
            assert bills(game) == [], "nothing lands in a wake while it is closing"
        finally:
            closer.unlock(game.campaign)
    assert len(held_of(ada)) == 1
    both_commit(ada, bea)
    (filed,) = bills(game)
    assert filed > position(game, ev.WakeOpened, wake=1)
    assert held_of(ada) == []


def test_an_order_given_while_a_leave_or_a_join_holds_the_game_lock_is_filed_now(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, _bea = duo
    with psycopg.connect(game.web.db.app_dsn, autocommit=True) as other:
        leaving = sch.ScheduleTable(other)
        assert leaving.try_lock(game.campaign)  # a leave or a join's redeem holds this alone
        try:
            _, out = post(ada, "lever", **BILL)
        finally:
            leaving.unlock(game.campaign)
    assert out["reply"] != held.HELD and out["refused"] is False, out
    assert held_of(ada) == []
    (filed,) = bills(game)  # in wake 0, which is still open
    opened = state_of(game).wake
    assert opened is not None and opened.number == 0 and not opened.closed
    assert log_of(game)[filed].actor == seat_of(game, "roosevelt")


def test_the_close_is_marked_closing_while_it_runs_and_not_after(
    duo: tuple[Realism, Client, Client], monkeypatch: pytest.MonkeyPatch
) -> None:
    game, _ada, _bea = duo
    seen: list[bool] = []
    close_wake = wk.close_wake

    def watched(*args: Any, **kwargs: Any) -> Any:
        other = game.web.app.open()
        try:
            seen.append(held.closing(other, game.campaign))
        finally:
            other.close()
        return close_wake(*args, **kwargs)

    monkeypatch.setattr(wk, "close_wake", watched)
    scheduler_close(game)
    assert seen == [True]
    store = game.web.app.open()
    try:
        assert not held.closing(store, game.campaign)
    finally:
        store.close()


def test_a_committed_seat_files_nothing_more_this_wake_and_its_orders_are_held(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, _bea = duo
    assert not post(ada, "commit")[1]["refused"]
    _, out = post(ada, "lever", lever="no_such_lever", params={})
    assert out["refused"] is True and "no lever" in out["reply"], "checked as it is held"
    _, out = post(ada, "step", order_id="nope", action="pass")
    assert out["refused"] is True and held_of(ada) == []
    _, out = post(ada, "file")
    assert out == {"reply": orders_reader.NOTHING, "refused": True}
    _, out = post(ada, "option", pick="w0.o9.p9")
    assert out["refused"] is True
    assert state_of(game).tick == 0 and bills(game) == []


# --- order, drops, withdraw -------------------------------------------------------------


def test_an_offered_option_picked_after_commit_is_filed_at_the_next_opening(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    fdr = seat_of(game, "roosevelt")
    block = realism_of(ada)["agenda"]
    picks = [o for item in block["items"] for o in item["options"]] + block["initiative"]
    chosen = picks[0]
    assert not post(ada, "commit")[1]["refused"]
    _, out = post(ada, "option", pick=chosen["pick"])
    assert out["reply"] == held.HELD, out
    assert held_of(ada)[0]["label"] == chosen["label"]
    assert [o for o in state_of(game).routed.values() if o.issuer == fdr] == []
    post(bea, "commit")
    (order,) = [o for o in state_of(game).routed.values() if o.issuer == fdr]
    filed = position(game, ev.OrderRouted, order=order)
    assert filed > position(game, ev.WakeOpened, wake=1)


def test_each_held_action_is_filed_as_the_seat_would_have(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        directive, "sign", lambda _s, _c, seat, p: calls.append(("sign", (seat, p)))
    )
    monkeypatch.setattr(
        realism_tick,
        "take_step",
        lambda _s, _c, who, ref, action, given: calls.append(("step", (who, ref, action, given))),
    )
    store, cid, seat = cast(EventStore, None), CampaignId("c"), SeatId("s")
    signed = {
        "lever": "send_bill",
        "params": {"bill": "x"},
        "to": "e1",
        "channel": "letter",
        "text": "Please",
    }
    assert held.file_one(store, cid, seat, "sign", signed) is None
    step = {"order_id": "o1", "action": "expedite", "params": {"rate": "3"}}
    assert held.file_one(store, cid, seat, "step", step) is None
    assert held.file_one(store, cid, seat, "bogus", {}) == "No such order as bogus."
    (_, (who, proposal)), (_, taken) = calls
    assert who == seat and proposal == directive.Proposal(
        person=EntityId("e1"),
        channel=ChannelKind.LETTER,
        text="Please",
        lever="send_bill",
        params={"bill": "x"},
    )
    assert taken == (seat, "o1", StepAction.EXPEDITE, {"rate": "3"})


class Recorder:
    def __init__(self, refuse: frozenset[str] = frozenset()) -> None:
        self.calls: list[tuple[SeatId, str, str]] = []
        self.refuse = refuse

    def __call__(
        self,
        store: EventStore,
        campaign_id: CampaignId,
        seat: SeatId,
        action: str,
        args: dict[str, Any],
    ) -> str | None:
        self.calls.append((seat, action, args["n"]))
        return "It no longer fits." if args["n"] in self.refuse else None


def test_held_orders_are_filed_in_the_order_given_and_only_from_earlier_wakes(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, _, _ = duo
    fdr, wsc = seat_of(game, "roosevelt"), seat_of(game, "churchill")
    store = game.web.app.open()
    try:
        cid = game.campaign
        for seat, n, wake in ((wsc, "a", 3), (fdr, "b", 3), (wsc, "c", 4), (fdr, "d", 5)):
            assert held.hold(store, cid, seat, wake, "lever", {"n": n}, n) is not None
        recorder = Recorder()
        assert held.file_held(store, cid, 5, filer=recorder) == 3
        assert recorder.calls == [(wsc, "lever", "a"), (fdr, "lever", "b"), (wsc, "lever", "c")]
        assert [x["label"] for x in held.listing(store, cid, fdr)] == ["d"]
        again = Recorder()
        assert held.file_held(store, cid, 5, filer=again) == 0 and again.calls == []
    finally:
        store.close()


def test_a_second_run_filing_at_the_same_time_files_each_order_once(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, _, _ = duo
    fdr = seat_of(game, "roosevelt")
    store = game.web.app.open()
    try:
        cid = game.campaign
        for n in ("a", "b", "c"):
            held.hold(store, cid, fdr, 0, "lever", {"n": n}, n)
        filed: list[str] = []

        def racing(
            store: EventStore, campaign_id: CampaignId, seat: SeatId, action: str, args: Any
        ) -> str | None:
            filed.append(args["n"])
            if len(filed) == 1:  # a resumed tick opens the same wake while this one files
                held.file_held(store, campaign_id, 1, filer=racing)
            return None

        held.file_held(store, cid, 1, filer=racing)
        assert sorted(filed) == ["a", "b", "c"]
    finally:
        store.close()


def test_one_that_no_longer_goes_through_is_dropped_with_a_line_on_its_catchup_page(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    fdr = seat_of(game, "roosevelt")
    store = game.web.app.open()
    try:
        cid = game.campaign
        held.hold(store, cid, fdr, 0, "lever", {"n": "kept"}, "Kept")
        held.hold(store, cid, fdr, 0, "lever", {"n": "gone"}, "Revise the Neutrality Act")
        assert held.file_held(store, cid, 1, filer=Recorder(frozenset({"gone"}))) == 2
    finally:
        store.close()
    both_commit(ada, bea)  # wake 1 closes; its page is on the catch-up
    _, mine = post(ada, "catchup", first=1, last=1)
    (page,) = mine["pages"]
    assert page["held_dropped"] == ["Revise the Neutrality Act was not filed: It no longer fits."]
    _, theirs = post(bea, "catchup", first=1, last=1)
    assert all("held_dropped" not in p for p in theirs["pages"])


def test_a_twin_held_twice_files_once_and_the_second_is_dropped(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    assert not post(ada, "commit")[1]["refused"]
    for _ in range(2):
        _, out = post(ada, "lever", **BILL)
        assert out["reply"] == held.HELD, out
    assert len(held_of(ada)) == 2
    post(bea, "commit")
    assert len(bills(game)) == 1
    both_commit(ada, bea)
    _, out = post(ada, "catchup", first=1, last=1)
    (page,) = out["pages"]
    (line,) = page["held_dropped"]
    assert line.startswith("Send a bill to Congress was not filed: ")


def default_pages(client: Client) -> dict[int, dict[str, Any]]:
    """The seat's catch-up with no range named, by wake."""
    status, out = post(client, "catchup")
    assert status == 200, out
    return {p["number"]: p for p in out["pages"]}


def test_a_held_order_dropped_at_the_opening_is_shown_in_that_wake_and_by_default(
    duo: tuple[Realism, Client, Client],
) -> None:
    _game, ada, bea = duo
    assert not post(ada, "commit")[1]["refused"]
    for _ in range(2):  # the twin no longer goes through once the first is filed
        assert post(ada, "lever", **BILL)[1]["reply"] == held.HELD
    assert not post(bea, "commit")[1]["refused"]  # wake 0 closes; wake 1 opens and files

    (shown,) = held_of(ada)
    line = shown.pop("dropped")
    assert line.startswith("Send a bill to Congress was not filed: "), line
    assert shown == {"id": shown["id"], "label": "Send a bill to Congress", "wake": 0}
    assert held_of(bea) == []
    assert default_pages(ada)[1]["held_dropped"] == [line], "the open wake's page says so"
    assert all("held_dropped" not in p for p in default_pages(bea).values())

    both_commit(ada, bea)  # wake 1 closes: Ada committed it herself
    assert held_of(ada) == [], "listed only while the wake it was due in is open"
    assert default_pages(ada)[1]["held_dropped"] == [line], "still there by default"

    both_commit(ada, bea)  # Ada has played on past it
    assert all("held_dropped" not in p for p in default_pages(ada).values())


def test_a_held_order_can_be_dropped_by_its_own_seat_before_it_is_filed(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    assert not post(ada, "commit")[1]["refused"]
    _, out = post(ada, "lever", **BILL)
    store = game.web.app.open()
    try:
        cid = game.campaign
        assert not held.drop(store, cid, seat_of(game, "churchill"), out["held"])
        assert held.drop(store, cid, seat_of(game, "roosevelt"), out["held"])
        assert not held.drop(store, cid, seat_of(game, "roosevelt"), out["held"])
    finally:
        store.close()
    post(bea, "commit")
    assert bills(game) == [] and held_of(ada) == []


def test_a_signed_reading_is_held_and_filed_from_its_asks(
    duo: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = duo
    fdr = seat_of(game, "roosevelt")
    churchill = EntityId(game.ids["churchill"])
    words = "Ask the Prime Minister to take fifty old destroyers"
    gift = rx.Allocate(recipient=churchill, what="old destroyers", amount=50, unit="ships")
    shown = OrderProposal(
        person="Winston Churchill", channel=None, text=words, parts=[words], reason=""
    )
    reading = orders_reader.Reading(
        shown=shown, asks=(Ask(ask=words, target=churchill, effect=gift),)
    )
    assert not post(ada, "commit")[1]["refused"]
    game.web.app._readings[(game.campaign, fdr)] = reading
    _, out = post(ada, "file")
    assert out["reply"] == held.HELD, out
    assert (game.campaign, fdr) not in game.web.app._readings
    post(bea, "commit")
    routed = [
        e.payload.order
        for e in log_of(game)
        if isinstance(e.payload, ev.OrderRouted) and e.payload.order.issuer == fdr
    ]
    assert [p.ask for o in routed for p in o.parts] == [words]


# --- before db migrate -----------------------------------------------------------------


@pytest.fixture
def no_table(web: Web) -> Iterator[None]:  # noqa: F811
    """The room before ``db migrate`` has run 0013."""
    with psycopg.connect(web.db.admin_dsn, autocommit=True) as conn:
        conn.execute("DROP TABLE web_held_orders")
    held.forget_missing()
    yield
    held.forget_missing()


def test_a_missing_table_reads_as_empty_logs_once_and_seals_as_before(
    duo: tuple[Realism, Client, Client],
    no_table: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    game, ada, bea = duo
    with caplog.at_level(logging.WARNING, logger="revisionist.engine.web.held"):
        assert not post(ada, "commit")[1]["refused"]
        _, out = post(ada, "lever", **BILL)
        assert out == {"reply": server.SEALED, "refused": True}
        assert held_of(ada) == []
        post(bea, "commit")
        both_commit(ada, bea)
        _, page = post(ada, "catchup")
        assert all("held_dropped" not in p for p in page["pages"])
    assert realism_of(ada)["wake"]["wake"] == 2 and bills(game) == []
    missing = [r for r in caplog.records if "web_held_orders" in r.getMessage()]
    assert len(missing) == 1
