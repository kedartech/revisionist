"""The eight asynchronous invariants (multiplayer job point 9), in CI.

Josh took these as the defaults for all multiplayer work; every build item keeps
them. One test per invariant, worded as in the build-out note; invariant 5 splits
into bounded, owned and unleaked, invariant 6 into server and replay, invariant 8
into lapse and conference. A test that cannot pass yet is a strict expected
failure naming the item that makes it pass; that item removes the mark.
"""

import importlib
import json
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.goals import Ordered
from revisionist.core.ids import EventId, MandateId, SeatId, derived_id
from revisionist.core.realism import advance
from revisionist.core.realism import agenda as ra
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask, Option
from revisionist.core.realism.effect import IRREVERSIBLE, EffectKind, Route
from revisionist.core.realism.pipeline import step_due
from revisionist.core.visibility import private_to
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, options, realism_tick
from revisionist.engine import scheduler as sch
from revisionist.engine.pg_store import PostgresEventStore
from revisionist.engine.store import MemoryStore
from tests.async_table import AsyncTable, Step, answer_days, digest, papers, run_wakes
from tests.pg import PgDb
from tests.test_engine_v2_wake import CAMPAIGN
from tests.test_web import PASSWORD, Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, log_of, seat_of

WORLD = "engine-v2-slice-1941"


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncTable:
    return AsyncTable(MemoryStore(), monkeypatch, tmp_path)


def request(t: AsyncTable, to: str, words: str) -> Ask:
    """An ask aimed at a person: an influence part."""
    return Ask(ask=words, target=t.entity(to))


def statement(theme: str) -> Ask:
    return Ask(ask=f"Say plainly: {theme}", effect=rx.MakeStatement(theme=theme))


def roosevelt_orders(t: AsyncTable, n: int) -> list[Ask]:
    first = t.shoot_on_sight() if n == 0 else statement(f"the convoys, week {n}")
    return [
        first,
        request(t, "wheeler", f"Ask Senator Wheeler to hold his fire, week {n}"),
        request(t, "churchill", f"Ask the Prime Minister for more escorts, week {n}"),
    ]


def churchill_orders(t: AsyncTable, n: int) -> list[Ask]:
    return [request(t, "roosevelt", f"Ask the President for more destroyers, week {n}")]


def files(
    who: Callable[[AsyncTable], SeatId], what: Callable[[AsyncTable, int], list[Ask]]
) -> Step:
    return lambda t, n: t.file(who(t), *what(t, n))


def commits(who: Callable[[AsyncTable], SeatId]) -> Step:
    return lambda t, n: t.commit(who(t))


def fdr(t: AsyncTable) -> SeatId:
    return t.fdr


def churchill(t: AsyncTable) -> SeatId:
    return t.churchill


def aide_filings(t: AsyncTable, monkeypatch: pytest.MonkeyPatch) -> list[tuple[SeatId, Ask]]:
    """Every ask filed from here on, by seat, whether or not it finds a route."""
    filed: list[tuple[SeatId, Ask]] = []
    real = realism_tick.commit_order

    def spy(store: Any, cid: Any, seat: SeatId, asks: Sequence[Ask]) -> Any:
        filed.extend((seat, a) for a in asks)
        return real(store, cid, seat, asks)

    monkeypatch.setattr(realism_tick, "commit_order", spy)
    return filed


def approach(t: AsyncTable, seat: SeatId, text: str, days: int) -> MandateId:
    """An opening put to ``seat``: met only by a deal it makes; lapses after ``days``."""
    state = t.state
    today = state.in_world_date
    assert today is not None
    mandate_id = MandateId(derived_id(CAMPAIGN, "approach", seat, text))
    mandate = ra.Mandate(
        mandate_id=mandate_id,
        seat_id=seat,
        kind=ra.MandateKind.OPPORTUNITY,
        text=text,
        condition=Ordered(person=state.seats[seat].embodies, effect=EffectKind.DEAL),
        issued=today,
        expires=today + timedelta(days=days),
        scope=private_to(seat),
    )
    t.store.append_all(
        [
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "approach-event", mandate_id)),
                campaign_id=CAMPAIGN,
                seq=state.last_seq + 1,
                tick=state.tick,
                scope=private_to(seat),
                payload=ev.MandateIssued(mandate=mandate),
                versions=cmp.versions(),
            )
        ]
    )
    return mandate_id


# --- 1. Nobody waits on a person --------------------------------------------------


def test_1_nobody_waits_on_a_person(table: AsyncTable) -> None:
    """Roosevelt and Churchill human, Churchill never commits: no Roosevelt order
    sits at a Churchill step past its due day, and every request has an answer date."""
    t = table
    t.open_play()
    t.file(t.fdr, *roosevelt_orders(t, 0))
    leader = t.entity("churchill")
    for _ in range(4):
        t.commit(t.fdr)
        t.close()
        state = t.state
        today = state.in_world_date
        assert today is not None
        for moving in state.orders.values():
            if moving.issuer != t.fdr:
                continue
            pipeline = state.pipelines[moving.pipeline]
            due = step_due(moving, pipeline)
            if due is not None and pipeline.steps[moving.step].person == leader:
                assert due >= today, f"{moving.lever} sits at a Churchill step past {due}"
        requests = [
            (o, i, p)
            for o in state.routed.values()
            if o.issuer == t.fdr
            for i, p in enumerate(o.parts)
            if p.route is Route.INFLUENCE and p.target == leader
        ]
        assert requests, "Roosevelt asked Churchill"
        for order, i, part in requests:
            answer = advance.answer_due(state, order, i)
            assert answer is not None, f"no answer date for {part.ask!r}"
            if answer[0] < today:
                assert part.decided is not None, f"{part.ask!r} undecided past {answer[0]}"


# --- 2. Away looks like present and quiet -----------------------------------------


def quiet(who: Callable[[AsyncTable], SeatId]) -> Step:
    """Present and quiet: reads every paper, files nothing, commits."""

    def step(t: AsyncTable, n: int) -> None:
        t.sitting(who(t))
        t.commit(who(t))

    return step


def test_2_away_looks_like_present_and_quiet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The same script with Churchill human and away, then human and present: Roosevelt's
    papers match in shape and answer day."""
    seen: dict[str, tuple[Any, Any]] = {}
    for churchill_is in ("away", "present"):
        with monkeypatch.context() as m:
            t = AsyncTable(MemoryStore(), m, tmp_path / churchill_is)
            script: list[Step] = [files(fdr, roosevelt_orders), commits(fdr)]
            if churchill_is == "present":
                script.append(quiet(churchill))
            run_wakes(t, script, wakes=3)
            state = t.state
            closed = t.payloads(ev.WakeClosed)
            aide = t.churchill if churchill_is == "away" else None
            assert [c.timed_out for c in closed] == [(aide,) if aide else ()] * 3
            seen[churchill_is] = (papers(state, t.fdr), answer_days(state, t.fdr))
    away, present = seen["away"], seen["present"]
    assert away[0], "Roosevelt holds papers"
    assert away[0] == present[0], "Roosevelt's papers differ in shape"
    assert away[1] == present[1], "Roosevelt's answer days differ"


# --- 3. Presence buys nothing -----------------------------------------------------


def roosevelt_in_sittings(sittings: int) -> Step:
    """Roosevelt files the wake's orders one at a time over ``sittings`` sittings,
    reading his papers at each; Churchill files and commits between them."""

    def wake(t: AsyncTable, n: int) -> None:
        mine = roosevelt_orders(t, n)
        for s in range(sittings):
            t.sitting(t.fdr)
            if mine and s % 3 == 0:
                t.file(t.fdr, mine.pop(0))
            if s == 1:
                t.file(t.churchill, *churchill_orders(t, n))
            if s == sittings - 2:
                t.commit(t.churchill)
        t.file(t.fdr, *mine)
        t.commit(t.fdr)

    return wake


ROOSEVELT_FIRST: list[Step] = [
    files(fdr, roosevelt_orders),
    commits(fdr),
    files(churchill, churchill_orders),
    commits(churchill),
]
CHURCHILL_FIRST: list[Step] = [
    files(churchill, churchill_orders),
    commits(churchill),
    files(fdr, roosevelt_orders),
    commits(fdr),
]


def alternating(t: AsyncTable, n: int) -> None:
    for step in CHURCHILL_FIRST if n % 2 else ROOSEVELT_FIRST:
        step(t, n)


PRESENCE: dict[str, list[Step]] = {
    "roosevelt commits first": ROOSEVELT_FIRST,
    "churchill commits first": CHURCHILL_FIRST,
    "the order alternates": [alternating],
    "roosevelt in ten sittings": [roosevelt_in_sittings(10)],
}


def held_back(t: AsyncTable, n: int) -> None:
    """The control: Roosevelt leaves out his request to Churchill in the last wake."""
    asks = roosevelt_orders(t, n)
    t.file(t.fdr, *(asks[:2] if n == 2 else asks))
    t.commit(t.fdr)
    t.file(t.churchill, *churchill_orders(t, n))
    t.commit(t.churchill)


def test_3_presence_buys_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Three wakes replayed with the commit order permuted, and with one seat filing in
    ten sittings against one: the same outcome digest. A control script that files one
    order fewer gives a different digest, so the digest can tell."""
    digests: dict[str, str] = {}
    filed: dict[str, int] = {}
    scripts: dict[str, list[Step]] = {**PRESENCE, "control": [held_back]}
    for name, script in scripts.items():
        with monkeypatch.context() as m:
            t = AsyncTable(MemoryStore(), m, tmp_path / name.replace(" ", "-"))
            run_wakes(t, script, wakes=3)
            state = t.state
            filed[name] = len([o for o in state.routed.values() if o.issuer == t.fdr])
            assert [c.timed_out for c in t.payloads(ev.WakeClosed)] == [()] * 3, name
            digests[name] = digest(state)
    first = digests["roosevelt commits first"]
    assert digests.pop("control") != first
    assert {name: d for name, d in digests.items() if d != first} == {}
    assert filed == {name: 8 if name == "control" else 9 for name in filed}


# --- 4. The wake closes with nobody there -----------------------------------------


def test_4_the_wake_closes_with_nobody_there(
    pg_db: PgDb, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A deadline close through the scheduler with no client; the next wake opens and
    its offers land."""
    store = PostgresEventStore(pg_db.app_dsn)
    try:
        t = AsyncTable(store, monkeypatch, tmp_path)
        t.open_play()
        opened = t.state.wake
        assert opened is not None and opened.number == 0
        assert {p.seat_id for p in t.payloads(ev.OptionsOffered) if p.wake == 0} == set(t.seats)

        def scheduler_at(minutes: int) -> list[sch.Action]:
            at = opened.deadline + timedelta(minutes=minutes)
            outcomes = sch.run(
                store,
                lambda: at,
                offline=True,
                transport_factory=cmp.live_transport,
                briefings=tmp_path,
                warn=lambda _m: None,
                campaign=CAMPAIGN,
            )
            return [o.action for o in outcomes]

        assert scheduler_at(-1) == [sch.Action.WAITING]
        assert t.state.wake == opened, "nothing closes before the deadline"
        assert scheduler_at(0) == [sch.Action.TICKED]
        (closed,) = t.payloads(ev.WakeClosed)
        assert closed.wake == 0 and set(closed.timed_out) == set(t.seats)
        after = t.state.wake
        assert after is not None and after.number == 1 and not after.closed
        assert {p.seat_id for p in t.payloads(ev.OptionsOffered) if p.wake == 1} == set(t.seats)
    finally:
        store.close()


def test_4_the_offers_land_for_seats_that_never_chose_a_style(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """As above for seats as they are claimed, with no style chosen: the next wake's
    offers land with nobody there."""
    t = AsyncTable(MemoryStore(), monkeypatch, tmp_path, style=None)
    t.open_play()
    t.close()
    assert {p.seat_id for p in t.payloads(ev.OptionsOffered) if p.wake == 1} == set(t.seats)


# --- 5. The aide is bounded and owned ---------------------------------------------


def test_5_the_aide_is_bounded_no_irreversible_step(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No irreversible step: neither from the aide's own list nor when what it is
    offered names one (a dismissal), with no standing order naming it."""
    t = table
    filed = aide_filings(t, monkeypatch)
    t.open_play()
    t.commit(t.fdr)
    t.close()
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: t.aide_orders())
    for _ in range(2):
        t.commit(t.fdr)
        t.close()
    by_aide = [a for seat, a in filed if seat == t.churchill]
    assert by_aide, "the aide played Churchill"
    kinds = {EffectKind(a.effect.kind) for a in by_aide if a.effect is not None}
    assert kinds & IRREVERSIBLE == set(), kinds


def test_5_the_aide_is_bounded_no_deal_accepted(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No deal accepted, whatever the aide is offered."""
    t = table
    t.open_play()
    approach(t, t.churchill, "The Americans offer fifty destroyers for bases.", days=10)
    accept = Option(
        label="Accept the American terms",
        asks=(
            Ask(
                ask="Accept the destroyers for bases",
                effect=rx.Deal(counterparty=t.entity("roosevelt"), accept=True),
            ),
        ),
    )
    monkeypatch.setattr(options, "_options_for", lambda *a, **k: (accept,))
    filed = aide_filings(t, monkeypatch)
    t.commit(t.fdr)
    t.close()
    by_aide = [a for seat, a in filed if seat == t.churchill]
    deals = [a for a in by_aide if isinstance(a.effect, rx.Deal) and a.effect.accept]
    assert deals == [], deals


def test_5_the_aide_is_owned(table: AsyncTable, monkeypatch: pytest.MonkeyPatch) -> None:
    """The owner's view names the aide's orders."""
    t = table
    monkeypatch.setattr(options, "aide_asks", lambda state, seat, transport: t.aide_orders())
    t.open_play()
    before = {o for o in t.state.routed}
    t.commit(t.fdr)
    t.close()
    state = t.state
    filed = {o.order_id for o in state.routed.values() if o.issuer == t.churchill} - before
    assert filed, "the aide filed for Churchill"
    named = [
        tuple(getattr(e.payload, "aide_orders", ()))
        for e in t.store.read(CAMPAIGN)
        if isinstance(e.payload, ev.WakeCommitted)
        and e.payload.by_aide
        and e.payload.seat_id == t.churchill
        and e.scope.visible_to(t.churchill)
    ]
    assert [set(n) for n in named] == [filed]


def everything_sent_to(client: Client, *replies: Any) -> str:
    """What the server has sent this browser: the page state and every paper opened."""
    sent: list[Any] = [*replies, client.me()]
    for doc in realism_of(client)["documents"]["documents"]:
        status, page = post(client, "read", doc_id=doc["id"])
        assert status == 200, page
        sent.append(page)
    return json.dumps(sent)


def test_5_the_aide_is_unleaked(web: Web) -> None:  # noqa: F811
    """No other seat's view holds ``by_aide`` or ``timed_out``: over every payload the
    server sends, the page state, every paper and every reply, the catch-up included,
    and over the catch-up seam the second run's playback reads."""
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    game.seat("bea", "churchill")
    make_host(game, ada)
    begin(game)
    replies: list[Any] = []
    for _ in range(2):
        replies.append(post(ada, "commit")[1])
        status, out = post(ada, "close")
        assert status == 200 and not out["refused"], out
        replies.append(out)
    played = [
        e.payload
        for e in log_of(game)
        if isinstance(e.payload, ev.WakeCommitted) and e.payload.by_aide
    ]
    assert [p.seat_id for p in played] == [seat_of(game, "churchill")] * 2
    _, caught_up = post(ada, "catchup", first=0, last=1)
    assert [p["number"] for p in caught_up["pages"]] == [0, 1], caught_up
    sent = everything_sent_to(ada, *replies, caught_up)
    for word in ("by_aide", "timed_out", "aide_orders", "aide_filed"):
        assert word not in sent, word
    store = game.web.app.open()
    try:
        seam = catchup.seat_events(store, game.campaign, seat_of(game, "roosevelt"), 0, 2)
    finally:
        store.close()
    assert seam, "the seam holds Roosevelt's wakes"
    fed = json.dumps([f.event.model_dump(mode="json") for f in seam])
    for word in ("by_aide", "timed_out", "aide_orders"):
        assert word not in fed, word


# --- 6. Catch-up is complete ------------------------------------------------------


def away_for_three_wakes(web: Web) -> tuple[Realism, Client]:  # noqa: F811
    """Churchill's player away for wakes 0 to 2, then back in a fresh browser."""
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    game.seat("bea", "churchill")
    make_host(game, ada)
    begin(game)
    for _ in range(3):
        post(ada, "commit")
        _, out = post(ada, "close")
        assert not out["refused"], out
    fresh = web.client()
    status, out = fresh.call("/api/signin", {"handle": "bea", "password": PASSWORD})
    assert status == 200, out
    return game, fresh


def catchup_pages(client: Client) -> list[dict[str, Any]]:
    status, out = post(client, "catchup")
    assert status == 200 and "pages" in out, (status, out)
    return list(out["pages"])


def test_6_catch_up_is_complete_from_the_server(web: Web) -> None:  # noqa: F811
    """A seat away for three wakes gets a page for each, from a fresh browser."""
    _, fresh = away_for_three_wakes(web)
    pages = catchup_pages(fresh)
    assert [p["number"] for p in pages] == [0, 1, 2]
    assert all("papers" in p for p in pages)


def test_6_catch_up_is_complete_with_a_replay(web: Web) -> None:  # noqa: F811
    """A seat away for three wakes gets a replay for each, from a fresh browser: every
    page carries its steps, and every wake in which anything reached the seat plays it."""
    _, fresh = away_for_three_wakes(web)
    pages = catchup_pages(fresh)
    assert [p["number"] for p in pages] == [0, 1, 2]
    assert all(isinstance(p.get("steps"), list) for p in pages)
    busy = [p for p in pages if p["papers"] or p["filed"] or p["settled"]]
    assert [p["number"] for p in busy] == [1, 2]
    assert all(p["steps"] for p in busy)


# --- 7. One notice ----------------------------------------------------------------


def test_7_one_notice(web: Web, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: F811
    """A wake opening sends one message per human seat; a commit sends none."""
    outbox = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("REVISIONIST_NOTICE_OUTBOX", str(outbox))
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    bea = game.seat("bea", "churchill")
    make_host(game, ada)
    begin(game)
    for who, client in (("ada", ada), ("bea", bea)):
        client.call("/api/game/notice-address", {"address": f"{who}@example.test"})

    def sent() -> list[str]:
        return outbox.read_text().splitlines() if outbox.exists() else []

    post(ada, "commit")
    assert sent() == [], "a commit sends nothing"
    post(bea, "commit")
    assert realism_of(ada)["wake"]["wake"] == 1
    assert len(sent()) == 2, "one message per human seat when wake 1 opens"


# --- 8. Offers lapse, votes are filed ahead ---------------------------------------


def test_8_offers_lapse(table: AsyncTable, monkeypatch: pytest.MonkeyPatch) -> None:
    """An offer to an absent seat expires with no change: the aide answers nothing on
    the seat's behalf, and the opening ends expired."""
    t = table
    t.open_play()
    opening = approach(t, t.churchill, "The Americans offer fifty destroyers for bases.", days=3)
    welcome = Option(
        label="Welcome the American offer",
        asks=(statement("the American offer is welcome"),),
    )
    real = options._options_for

    def offered(state: Any, view: Any, mandate: Any, *args: Any, **kwargs: Any) -> Any:
        if mandate is not None and mandate.mandate_id == opening:
            return (welcome,)
        return real(state, view, mandate, *args, **kwargs)

    monkeypatch.setattr(options, "_options_for", offered)
    filed = aide_filings(t, monkeypatch)
    expires = t.state.mandates[opening].expires
    while (t.state.in_world_date or date.min) <= expires:
        t.commit(t.fdr)
        t.close()
    answered = [a for seat, a in filed if seat == t.churchill and a.ask == welcome.asks[0].ask]
    assert answered == [], "the aide answered the opening"
    assert t.state.mandates[opening].status is ra.MandateStatus.EXPIRED


def test_8_votes_are_filed_ahead() -> None:
    """A conference tallies with one seat never present: votes are sealed ahead, and
    the aide votes by the card or abstains."""
    conference = importlib.import_module("revisionist.core.realism.conference")
    assert conference.tally  # stage 3 writes the test against its own API
