"""A decider nobody plays answers an ask (AAK).

The toy world of the lock tests (``tests/test_realism_locks.py``): Ilse Varg, the
chancellor, decides Kara Lind's march to the Isle (a posture: Ilse's watch on the Gulf)
and, as the head of Norra's government, her march to the Sudland Coast (a body: the
assembly passes the Barge Act). Here nobody plays Ilse: Kara and Olaf are claimed, and
an ask Kara makes goes to Ilse's card, which answers it two world days later.

Ilse's regard for Kara and the topics she wants or holds to are set per test, so the
score is past the draw's reach either way: a grant at regard 3 with a wanted topic, a
decline at regard -3 with a topic she holds to.
"""

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, state_hash
from revisionist.core.ids import OrderId, SeatId, derived_id
from revisionist.core.realism import actors, answering, locks, resolvers
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.process import ANSWER_DAYS
from revisionist.core.realism.resolvers import friction
from revisionist.core.state import Rule, State
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick, season, session_zero
from revisionist.engine.store import MemoryStore, load_state
from tests.test_realism_command import card
from tests.test_realism_locks import (
    ILSE,
    KARA,
    OLAF,
    World,
    file,
    law_passed,
    logged,
    public_law,
    seat,
    world,
)
from tests.test_territory_model import CAMPAIGN

ISLE_ROW, COAST_ROW = "island_march", "coast_march"


def answers_on(w: World) -> None:
    w["rules"] = sorted({*w["rules"], "ask_answers"})


def regard(n: int) -> Callable[[World], None]:
    """Ilse's regard for Kara."""

    def edit(w: World) -> None:
        w.setdefault("relationships", []).append(
            {"key": "ilse_kara", "a": "ilse", "b": "kara", "disposition": n}
        )

    return edit


def isle_topic(field: str) -> Callable[[World], None]:
    """A topic the march touches by its form, which Ilse wants or holds to."""

    def edit(w: World) -> None:
        w.setdefault("topics", []).append(
            {"key": "the_isle", "name": "The Isle", "levers": ["march"]}
        )
        card(w, "ilse")[field] = ["the_isle"]

    return edit


def friendly(w: World) -> None:
    regard(3)(w)
    isle_topic("wants")(w)


def hostile(w: World) -> None:
    regard(-3)(w)
    isle_topic("holds_to")(w)


def bills(w: World) -> None:
    """Ilse sends bills to the assembly by her own form; the assembly passes the Barge
    Act when it is sent (groups on, the Greens voting for it)."""
    w["rules"] = sorted({*w["rules"], "groups"})
    card(w, "ilse")["levers"].append(
        {
            "name": "propose",
            "pipeline": "clerks",
            "resolver": "votes",
            "params": [
                {"name": "bill", "kind": "enum", "choices": ["barge_act"]},
                {"name": "urgency", "kind": "enum", "choices": ["ordinary", "urgent"]},
            ],
        }
    )
    norra = next(g for g in w["groups"] if g["nation"] == "norra")
    greens = next(g for g in norra["groups"] if g["key"] == "greens")
    greens["votes"]["barge_act"] = {"assembly": {"voting": 55, "yeas": 50}}


def unplayed(tmp: Path, *changes: Callable[[World], None], ilse: bool = False) -> MemoryStore:
    """The game with Kara and Olaf claimed, and Ilse too only with ``ilse``."""
    tmp.mkdir(parents=True, exist_ok=True)
    store = MemoryStore()
    store.append_all(compile_world(world(tmp, *changes), CAMPAIGN, cmp.versions()))
    state = load_state(store, CAMPAIGN)
    for person in (ILSE, KARA, OLAF) if ilse else (KARA, OLAF):
        session_zero.claim(store, CAMPAIGN, seat(person), state.entities[person].name)
    realism_tick.open_play(store, CAMPAIGN)
    return store


def ask(store: MemoryStore, order_id: OrderId) -> locks.Asked:
    return realism_tick.ask_order(store, CAMPAIGN, seat(KARA), order_id)


def tick_until(store: MemoryStore, done: Callable[[State], bool], ticks: int = 10) -> State:
    for _ in range(ticks):
        realism_tick.run_realism_tick(store, CAMPAIGN)
        state = load_state(store, CAMPAIGN)
        if done(state):
            return state
    return load_state(store, CAMPAIGN)


def landed_as(order_id: OrderId) -> OrderId:
    return OrderId(derived_id(CAMPAIGN, "landed", order_id))


def answered(store: MemoryStore) -> list[ev.AskAnswered]:
    return logged(store, ev.AskAnswered)


def ilses_orders(store: MemoryStore) -> list[Order]:
    return [p.order for p in logged(store, ev.OrderDrafted) if p.order.issuer == seat(ILSE)]


def settled_on(store: MemoryStore, order_id: OrderId) -> date:
    order = load_state(store, CAMPAIGN).orders[order_id]
    assert order.status is OrderStatus.ENACTED
    return resolvers.settled_on(order)


# --- rule 1: the ask falls due two world days after it was made ----------------------


def test_an_ask_to_a_person_nobody_plays_is_answered_two_world_days_later(tmp_path: Path) -> None:
    store = unplayed(tmp_path, answers_on, friendly)
    order = file(store, "isle")
    made = ask(store, order.order_id)
    assert made.seat is None
    tick_until(store, lambda s: bool(answered(store)))
    (answer,) = answered(store)
    assert answer.on == made.on + timedelta(days=ANSWER_DAYS)
    assert (answer.order_id, answer.asker) == (order.order_id, seat(KARA))


# --- rules 2 and 3: a grant on a posture, and the person's order opens the lock --------


def test_granted_on_a_posture_the_decider_files_the_form_and_the_order_lands(
    tmp_path: Path,
) -> None:
    store = unplayed(tmp_path, answers_on, friendly)
    order = file(store, "isle")
    ask(store, order.order_id)
    state = tick_until(store, lambda s: order.order_id not in s.held)
    (answer,) = answered(store)
    assert answer.granted
    (watch,) = ilses_orders(store)
    assert (watch.lever, watch.params) == ("set_watch", {"zone": "gulf", "order": "guard"})
    # The lock opens only once Ilse's own order is enacted, never on the grant.
    enacted = settled_on(store, watch.order_id)
    (end,) = [e for e in logged(store, ev.HeldOrderEnded) if e.order_id == order.order_id]
    assert end.end is locks.HeldEnd.LANDED and end.on >= enacted > answer.on
    landed = state.orders[landed_as(order.order_id)]
    assert (landed.lever, landed.params, landed.issuer) == ("march", order.params, seat(KARA))


def watch_held(w: World) -> None:
    """Ilse's watch is itself always held for the assembly, so her card cannot file it."""
    w["locks"].append(
        {
            "key": "watch_needs_assembly",
            "order": {"form": "set_watch"},
            "decider": {"nation": "norra", "chambers": ["assembly"], "head": "ilse"},
        }
    )


def test_the_grant_alone_opens_nothing(tmp_path: Path) -> None:
    store = unplayed(tmp_path, answers_on, friendly, watch_held)
    order = file(store, "isle")
    ask(store, order.order_id)
    tick_until(store, lambda s: False, ticks=4)
    season.end_season(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    (answer,) = answered(store)
    assert answer.granted and not ilses_orders(store)
    assert order.order_id in state.held
    assert landed_as(order.order_id) not in state.orders


# --- rule 4: a grant on a body: the head sends the bill ------------------------------


def test_granted_on_a_body_the_head_sends_the_bill_and_the_vote_opens_the_lock(
    tmp_path: Path,
) -> None:
    store = unplayed(tmp_path, answers_on, friendly, public_law, bills)
    order = file(store, "sudland_coast")
    assert order.order_id in load_state(store, CAMPAIGN).held
    ask(store, order.order_id)
    state = tick_until(store, lambda s: order.order_id not in s.held, ticks=12)
    (answer,) = answered(store)
    assert answer.granted
    (bill,) = ilses_orders(store)
    assert (bill.lever, bill.params) == ("propose", {"bill": "barge_act", "urgency": "ordinary"})
    enacted = settled_on(store, bill.order_id)
    (end,) = [e for e in logged(store, ev.HeldOrderEnded) if e.order_id == order.order_id]
    assert end.end is locks.HeldEnd.LANDED and end.on >= enacted
    assert state.orders[landed_as(order.order_id)].params["to"] == "sudland_coast"


# --- rule 5: a decline -------------------------------------------------------------


def test_declined_the_order_is_still_held_at_the_seasons_end(tmp_path: Path) -> None:
    store = unplayed(tmp_path, answers_on, hostile)
    order = file(store, "isle")
    made = ask(store, order.order_id)
    tick_until(store, lambda s: False, ticks=4)
    season.end_season(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    (answer,) = answered(store)
    assert not answer.granted and not ilses_orders(store)
    assert order.order_id in state.held
    kept = state.asked[order.order_id]
    assert (kept.answered, kept.granted) == (made.on + timedelta(days=ANSWER_DAYS), False)
    # Final: the seat cannot ask again.
    with pytest.raises(ValueError, match=locks.ASKED_ALREADY):
        ask(store, order.order_id)


def test_the_answer_is_sealed_to_the_asker_and_fed_to_no_seat(tmp_path: Path) -> None:
    # A person a seat holds is never answered for, so the card's answer is not fed even
    # to the asker, whose record of the ask shows no answer (catch-up's ``told``).
    from revisionist.core.project import project

    store = unplayed(tmp_path, answers_on, hostile)
    order = file(store, "isle")
    ask(store, order.order_id)
    tick_until(store, lambda s: bool(answered(store)))
    (e,) = [e for e in store.read(CAMPAIGN) if e.kind == "ask_answered"]
    assert e.scope.known_by == frozenset({seat(KARA)})

    def fed(person: SeatId) -> list[str]:
        return [f.event.kind for f in catchup.seat_events(store, CAMPAIGN, person, 0, 99)]

    assert "ask_answered" not in fed(seat(KARA))
    assert "ask_answered" not in fed(seat(OLAF))
    state = load_state(store, CAMPAIGN)
    assert state.asked[order.order_id].granted is False
    assert project(state, seat(KARA)).asked[order.order_id].granted is None
    assert order.order_id not in project(state, seat(OLAF)).asked


# --- rule 6 and the keeps: a human-held decider, the switch off ---------------------


def test_an_ask_to_a_person_a_seat_holds_is_never_answered_for(tmp_path: Path) -> None:
    store = unplayed(tmp_path, answers_on, friendly, ilse=True)
    order = file(store, "isle")
    made = ask(store, order.order_id)
    assert made.seat == seat(ILSE)
    tick_until(store, lambda s: False, ticks=4)
    state = load_state(store, CAMPAIGN)
    assert not answered(store) and not ilses_orders(store)
    assert state.asked[order.order_id] == made


def test_with_ask_answers_off_the_ask_is_left_unread_as_today(tmp_path: Path) -> None:
    store = unplayed(tmp_path, friendly)
    order = file(store, "isle")
    made = ask(store, order.order_id)
    tick_until(store, lambda s: False, ticks=4)
    season.end_season(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    assert not answered(store) and not ilses_orders(store)
    assert order.order_id in state.held and state.asked[order.order_id] == made
    assert "answered" not in state.asked[order.order_id].model_dump(mode="json")


# --- one answer, the same on replay -------------------------------------------------


def test_a_restart_between_the_ask_and_its_due_day_gives_one_answer_and_one_digest(
    tmp_path: Path,
) -> None:
    store = unplayed(tmp_path, answers_on, friendly)
    order = file(store, "isle")
    ask(store, order.order_id)
    twin = MemoryStore()
    twin.append_all(list(store.read(CAMPAIGN)))
    for s in (store, twin):
        tick_until(s, lambda st: order.order_id not in st.held)
    assert len(answered(store)) == len(answered(twin)) == 1
    assert state_hash(load_state(twin, CAMPAIGN)) == state_hash(load_state(store, CAMPAIGN))


def test_the_answer_folds_once_and_only_for_a_person_no_seat_holds(tmp_path: Path) -> None:
    store = unplayed(tmp_path, answers_on, friendly)
    order = file(store, "isle")
    made = ask(store, order.order_id)
    state = load_state(store, CAMPAIGN)
    due = made.on + timedelta(days=ANSWER_DAYS)
    answer = ev.AskAnswered(order_id=order.order_id, asker=seat(KARA), on=due, granted=True)
    with pytest.raises(FoldError, match="not that seat's"):
        realism_tick._append(
            store, state, answer.model_copy(update={"asker": seat(OLAF)}), seat(KARA)
        )
    early = answer.model_copy(update={"on": made.on - timedelta(days=1)})
    with pytest.raises(FoldError, match="before it was made"):
        realism_tick._append(store, state, early, seat(KARA))
    off = state.model_copy(update={"rules": state.rules - {Rule.ASK_ANSWERS}})
    with pytest.raises(FoldError, match="needs the locks and ask_answers rules"):
        realism_tick._append(store, off, answer, seat(KARA))
    realism_tick._append(store, state, answer, seat(KARA))
    with pytest.raises(FoldError, match="answered already"):
        realism_tick._append(store, load_state(store, CAMPAIGN), answer, seat(KARA))
    held = unplayed(tmp_path / "held", answers_on, friendly, ilse=True)
    order = file(held, "isle")
    ask(held, order.order_id)
    theirs = answer.model_copy(update={"order_id": order.order_id})
    with pytest.raises(FoldError, match="a person a seat holds"):
        realism_tick._append(held, load_state(held, CAMPAIGN), theirs, seat(KARA))


# --- the fog: two games differing only in a hidden fact -----------------------------


def _seen(store: MemoryStore) -> tuple[Any, ...]:
    from revisionist.core.project import project

    view = project(load_state(store, CAMPAIGN), seat(KARA))
    asked = sorted((a.words, a.on, a.answered, a.granted) for a in view.asked.values())
    held = sorted((h.row, h.reason) for h in view.held.values())
    papers = sorted((d.title, d.kind) for d in view.documents.values())
    fed = [
        (f.event.kind, getattr(f.event.payload, "granted", None))
        for f in catchup.seat_events(store, CAMPAIGN, seat(KARA), 0, 99)
        if f.event.kind in {"ask_answered", "order_asked", "held_order_ended"}
    ]
    return tuple(asked), tuple(held), tuple(papers), tuple(fed), len(view.orders)


@pytest.mark.parametrize("mood", [friendly, hostile], ids=["granted", "declined"])
def test_two_games_differing_only_in_a_hidden_fact_give_the_asker_the_same_papers(
    tmp_path: Path, mood: Callable[[World], None]
) -> None:
    def run(tmp: Path, *changes: Callable[[World], None]) -> MemoryStore:
        store = unplayed(tmp, answers_on, mood, *changes)
        order = file(store, "isle")
        ask(store, order.order_id)
        tick_until(store, lambda s: False, ticks=4)
        return store

    # The Barge Act's flag is hidden from Kara: passed in one game, not in the other.
    a, b = run(tmp_path / "a"), run(tmp_path / "b", law_passed)
    assert answered(a) and _seen(a) == _seen(b)


# --- rule 2: the score -------------------------------------------------------------


def _asked_state(tmp: Path, *changes: Callable[[World], None]) -> tuple[State, locks.Asked]:
    store = unplayed(tmp, answers_on, *changes)
    order = file(store, "isle")
    made = ask(store, order.order_id)
    return load_state(store, CAMPAIGN), made


def _draw(made: locks.Asked) -> int:
    return friction_for(made.order_id)


def friction_for(order_id: OrderId) -> int:
    from types import SimpleNamespace
    from typing import cast

    return friction(cast(State, SimpleNamespace(campaign_id=CAMPAIGN)), order_id, "ask", n=5) - 2


@pytest.mark.parametrize(
    ("changes", "base"),
    [
        ((), 0),
        ((regard(2),), 2),
        ((regard(-1),), -1),
        ((isle_topic("wants"),), 2),
        ((isle_topic("holds_to"),), -2),
        ((regard(1), isle_topic("holds_to")), -1),
    ],
    ids=["nothing", "regard", "ill", "wants", "holds_to", "both"],
)
def test_the_score_is_regard_and_topics_and_the_draw(
    tmp_path: Path, changes: tuple[Callable[[World], None], ...], base: int
) -> None:
    state, made = _asked_state(tmp_path, *changes)
    assert answering.ask_score(state, made) == base + _draw(made)
    assert answering.grants(state, made) is (base + _draw(made) >= answering.GRANT_AT)


def test_each_order_the_decider_carries_past_two_takes_a_point(tmp_path: Path) -> None:
    state, made = _asked_state(tmp_path, regard(2))
    (created,) = actors.unseated(state, [ILSE])
    state = state.model_copy(update={"seats": {**state.seats, created.seat.seat_id: created.seat}})
    base = answering.ask_score(state, made)

    def carrying(n: int) -> State:
        orders = {
            OrderId(f"busy-{i}"): Order(
                order_id=OrderId(f"busy-{i}"),
                issuer=seat(ILSE),
                lever="set_watch",
                pipeline=next(iter(state.pipelines)),
                params={"zone": "open", "order": "stand_down"},
                filed=made.on,
            )
            for i in range(n)
        }
        return state.model_copy(update={"orders": {**state.orders, **orders}})

    assert answering.ask_score(carrying(2), made) == base
    assert answering.ask_score(carrying(5), made) == base - 3


def test_the_draw_is_seeded_by_the_campaign_and_the_order_not_the_clock(tmp_path: Path) -> None:
    state, made = _asked_state(tmp_path)
    scores = set()
    for days in range(12):
        later = made.model_copy(update={"on": made.on + timedelta(days=days)})
        assert state.in_world_date is not None
        moved = state.model_copy(
            update={
                "in_world_date": state.in_world_date + timedelta(days=days),
                "asked": {made.order_id: later},
            }
        )
        scores.add(answering.ask_score(moved, later))
    assert scores == {_draw(made)}
