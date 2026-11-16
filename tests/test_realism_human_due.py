"""Nobody waits on a person: a request or a held decision at a leader another human
seat holds has a due day, and the card decides it then if the holder has not (DUE).

The holder is told by one paper sealed to their seat. The card never takes an
irreversible step on the holder's behalf: it declines or holds instead.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, EventId, OrderId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import advance, pipelines, process, reach
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.pipeline import Order, OrderStatus, StepAction
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.store import MemoryStore
from tests.async_table import AsyncTable
from tests.test_engine_v2_wake import CAMPAIGN

ESCORTS = "Ask the Prime Minister for more escorts"


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncTable:
    t = AsyncTable(MemoryStore(), monkeypatch, tmp_path)
    t.open_play()
    return t


def _ask(t: AsyncTable, frm: SeatId, to: str, words: str, effect: rx.Effect | None = None) -> None:
    t.file(frm, Ask(ask=words, target=t.entity(to), effect=effect))


def _request(state: State, words: str) -> tuple[rx.RoutedOrder, int]:
    for order in state.routed.values():
        for i, part in enumerate(order.parts):
            if part.ask == words:
                return order, i
    raise AssertionError(f"no request {words!r}")


def _arrival(state: State, order: rx.RoutedOrder, i: int) -> date:
    issuer = state.seats[order.issuer].embodies
    target = order.parts[i].target
    assert target is not None
    channels = reach.channels_to(state, issuer, target)
    return order.filed + timedelta(days=reach.transit_days(channels[0]))


def _decisions(out: list[ev.Payload], order: rx.RoutedOrder) -> list[ev.InfluenceDecided]:
    return [p for p in out if isinstance(p, ev.InfluenceDecided) and p.order_id == order.order_id]


def _close_past(t: AsyncTable, day: date) -> None:
    for _ in range(12):
        if (t.state.in_world_date or day) > day:
            return
        t.close()
    raise AssertionError(f"the world never passed {day}")


# --- a request ---------------------------------------------------------------------


def test_a_request_to_an_absent_human_is_answered_on_its_due_day(table: AsyncTable) -> None:
    t = table
    _ask(t, t.fdr, "churchill", ESCORTS)
    state = t.state
    order, i = _request(state, ESCORTS)
    due = _arrival(state, order, i) + timedelta(days=process.ANSWER_DAYS)
    day = order.filed
    while day < due:
        assert _decisions(process.influence_due(state, day), order) == [], day
        day += timedelta(days=1)
    (decided,) = _decisions(process.influence_due(state, due), order)
    assert decided.on == due and decided.part == i
    # through the wakes: Churchill never commits, and the card answers on the day
    _close_past(t, due)
    stored = [
        e.payload
        for e in t.store.read(CAMPAIGN)
        if isinstance(e.payload, ev.InfluenceDecided) and e.payload.order_id == order.order_id
    ]
    assert [(d.part, d.on) for d in stored] == [(i, due)]


def test_the_answer_date_of_a_request_to_a_human_is_its_due_day_and_the_way_back(
    table: AsyncTable,
) -> None:
    t = table
    _ask(t, t.fdr, "churchill", ESCORTS)
    state = t.state
    order, i = _request(state, ESCORTS)
    due = _arrival(state, order, i) + timedelta(days=process.ANSWER_DAYS)
    answer = advance.answer_due(state, order, i)
    assert answer is not None
    assert answer[0] >= due


def test_a_request_decided_early_is_not_decided_again(table: AsyncTable) -> None:
    t = table
    _ask(t, t.fdr, "churchill", ESCORTS)
    state = t.state
    order, i = _request(state, ESCORTS)
    early = _arrival(state, order, i)
    answered = ev.InfluenceDecided(
        order_id=order.order_id, part=i, on=early, accepted=True, reason="Agreed."
    )
    realism_tick._append(t.store, state, answered, t.churchill, private_to(t.churchill))
    later = early + timedelta(days=process.ANSWER_DAYS + 5)
    assert _decisions(process.influence_due(t.state, later), order) == []
    _close_past(t, later)
    stored = [
        e.payload
        for e in t.store.read(CAMPAIGN)
        if isinstance(e.payload, ev.InfluenceDecided) and e.payload.order_id == order.order_id
    ]
    assert stored == [answered]


def test_an_irreversible_request_is_declined_not_carried(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = table
    monkeypatch.setattr(process, "decides", lambda *_a: (True, "Agreed."))
    destroyers = rx.Allocate(
        recipient=t.entity("churchill"), what="old destroyers", amount=50, unit="ships"
    )
    _ask(t, t.fdr, "churchill", "Ask the Prime Minister to take fifty destroyers", destroyers)
    _ask(t, t.fdr, "churchill", ESCORTS)
    state = t.state
    gift, _ = _request(state, "Ask the Prime Minister to take fifty destroyers")
    plain, _ = _request(state, ESCORTS)
    assert state.in_world_date is not None
    far = state.in_world_date + timedelta(days=30)
    out = process.influence_due(state, far)
    (declined,) = _decisions(out, gift)
    assert declined.accepted is False
    (agreed,) = _decisions(out, plain)
    assert agreed.accepted is True


def test_a_request_for_a_declaration_is_declined_not_carried(
    table: AsyncTable, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = table
    monkeypatch.setattr(process, "decides", lambda *_a: (True, "Agreed."))
    war = rx.ProposeMeasure(
        title="Declaration of war on Germany",
        clauses=(rx.Clause(kind=rx.ClauseKind.POWER, subject="war with Germany"),),
    )
    _ask(t, t.churchill, "roosevelt", "Ask the President to declare war on Germany", war)
    state = t.state
    order, _ = _request(state, "Ask the President to declare war on Germany")
    assert state.in_world_date is not None
    far = state.in_world_date + timedelta(days=30)
    (declined,) = _decisions(process.influence_due(state, far), order)
    assert declined.accepted is False


def test_the_paper_reaches_the_holder_only(table: AsyncTable) -> None:
    t = table
    _ask(t, t.fdr, "churchill", ESCORTS)
    state = t.state
    order, i = _request(state, ESCORTS)
    arrival = _arrival(state, order, i)
    _close_past(t, arrival)
    log = list(t.store.read(CAMPAIGN))
    issued = [
        e
        for e in log
        if isinstance(e.payload, ev.DocumentIssued)
        and e.payload.document.doc_id == process.request_paper_id(CAMPAIGN, order.order_id, i)
    ]
    assert len(issued) == 1, "one paper, once"
    (event,) = issued
    assert isinstance(event.payload, ev.DocumentIssued)
    paper = event.payload.document
    assert event.scope == private_to(t.churchill)
    assert paper.scope == private_to(t.churchill)
    assert paper.arrives == arrival
    lines = " | ".join(str(b.value) for b in paper.body)
    assert "Roosevelt" in lines and "escorts" in lines
    state = t.state
    assert paper.doc_id in project(state, t.churchill).documents
    assert paper.doc_id not in project(state, t.fdr).documents


def test_the_holder_sees_the_request_on_their_list_until_it_is_decided(
    table: AsyncTable,
) -> None:
    t = table
    _ask(t, t.fdr, "churchill", ESCORTS)
    state = t.state
    order, i = _request(state, ESCORTS)
    arrival = _arrival(state, order, i)
    due = arrival + timedelta(days=process.ANSWER_DAYS)
    assert advance.awaiting(state, t.churchill, arrival - timedelta(days=1)) == []
    (item,) = advance.awaiting(state, t.churchill, arrival)
    assert (item.order_id, item.part, item.due) == (order.order_id, i, due)
    assert "Roosevelt" in item.issuer and "escorts" in item.label
    assert advance.awaiting(state, t.fdr, arrival) == []
    _close_past(t, due)
    assert advance.awaiting(t.state, t.churchill, t.state.in_world_date) == []  # type: ignore[arg-type]


def test_the_holder_has_a_wake_with_the_paper_before_the_due_day(table: AsyncTable) -> None:
    """The clock stops once the paper is out and before the card decides, so the
    holder has a wake to answer in."""
    t = table
    _ask(t, t.fdr, "churchill", ESCORTS)
    state = t.state
    order, i = _request(state, ESCORTS)
    due = _arrival(state, order, i) + timedelta(days=process.ANSWER_DAYS)
    seen = []
    for _ in range(6):
        t.close()
        state = t.state
        today = state.in_world_date
        assert today is not None
        if today >= due:
            break
        seen.append(process.request_paper_id(CAMPAIGN, order.order_id, i) in state.documents)
    assert any(seen), "no wake before the due day held the paper"


def test_the_clock_line_for_a_request_names_nobody(table: AsyncTable) -> None:
    """Every seat's clock shows the reason the world stops; a third seat must not
    learn from it who asked whom."""
    t = table
    _ask(t, t.fdr, "churchill", ESCORTS)
    state = t.state
    today = state.in_world_date
    assert today is not None
    wake = advance.next_wake(state, today)
    assert wake.reason.what == "agenda"
    names = [e.name for e in state.entities.values()]
    assert not [n for n in names if n and n in wake.reason.label]


# --- a decision step ---------------------------------------------------------------

TOY = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")


class Toy:
    """The toy world: Ada files a levy; its decision step is Bram's. Both human."""

    def __init__(self, measure: rx.ProposeMeasure | None = None) -> None:
        world = cmp.load_world(cmp.world_path("realism-toy"))
        self.ids = resolve_keys(world, TOY)
        self.events = compile_world(world, TOY, cmp.versions())
        self.ada = SeatId(derived_id(TOY, "seat", "ada"))
        self.bram = SeatId(derived_id(TOY, "seat", "bram"))
        self.add(ev.CharacterClaimed(seat_id=self.ada, entity_id=EntityId(self.ids["ada"])))
        self.add(ev.CharacterClaimed(seat_id=self.bram, entity_id=EntityId(self.ids["bram"])))
        self.add(ev.SessionZeroClosed())
        self.order_id = OrderId(derived_id(TOY, "order", 1))
        self.filed = date(1900, 4, 2)
        ada = self.state.cards[EntityId(self.ids["ada"])]
        self.add(
            ev.OrderDrafted(
                order=Order(
                    order_id=self.order_id,
                    issuer=self.ada,
                    lever="propose_levy",
                    pipeline=ada.levers[0].pipeline,
                    params={"rate": 8, "purpose": "harbour"},
                    filed=self.filed,
                    measure=measure,
                )
            )
        )
        self.arrival = self.filed + timedelta(days=2)  # the clerk's two days
        self.due = self.arrival + timedelta(days=5 + process.ANSWER_DAYS)

    def add(self, payload: ev.Payload) -> None:
        seq = len(self.events)
        self.events.append(
            ev.Event(
                event_id=EventId(derived_id(TOY, "test-event", seq)),
                campaign_id=TOY,
                seq=seq,
                tick=0,
                scope=PUBLIC,
                payload=payload,
                versions=cmp.versions(),
            )
        )

    def run(self, day: date, seed: str = "s") -> list[pipelines.RealismStep]:
        out = pipelines.run_pipelines(self.state, day, seed)
        for p in out:
            self.add(p)
        return out

    @property
    def state(self) -> State:
        return replay(self.events)


def _steps(out: list[pipelines.RealismStep]) -> list[ev.OrderStepTaken]:
    return [p for p in out if isinstance(p, ev.OrderStepTaken) and p.outcome.step == 1]


def test_a_decision_held_on_another_seats_order_is_taken_by_the_card_on_its_due_day() -> None:
    toy = Toy()
    toy.run(toy.arrival)
    assert pipelines.waiting_on_human(toy.state, toy.state.orders[toy.order_id])
    assert _steps(pipelines.run_pipelines(toy.state, toy.due - timedelta(days=1), "s")) == []
    (taken,) = _steps(toy.run(toy.due))
    assert taken.outcome.on == toy.due


def test_the_holder_of_a_step_gets_one_paper_when_the_order_reaches_them() -> None:
    toy = Toy()
    out = toy.run(toy.arrival)
    papers = [p for p in out if isinstance(p, ev.DocumentIssued)]
    held = [p for p in papers if p.document.scope == private_to(toy.bram)]
    assert len(held) == 1
    paper = held[0].document
    assert paper.arrives == toy.arrival
    lines = " | ".join(str(b.value) for b in paper.body)
    assert "Ada" in lines
    assert not [p for p in papers if p.document.scope.visibility.value == "public"]
    again = toy.run(toy.arrival + timedelta(days=1))
    assert [p for p in again if isinstance(p, ev.DocumentIssued)] == [], "one paper, once"
    (item,) = advance.awaiting(toy.state, toy.bram, toy.arrival)
    assert item.part is None and item.due == toy.due


def test_a_held_step_on_an_irreversible_order_is_held_not_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipelines, "_policy", lambda *_a: (StepAction.PASS, {}))
    war = rx.ProposeMeasure(
        title="A declaration of war on Ostra",
        clauses=(rx.Clause(kind=rx.ClauseKind.POWER, subject="war with Ostra"),),
    )
    toy = Toy(measure=war)
    toy.run(toy.arrival)
    (taken,) = _steps(toy.run(toy.due))
    assert taken.outcome.action is StepAction.STALL
    plain = Toy()
    plain.run(plain.arrival)
    (passed,) = _steps(plain.run(plain.due))
    assert passed.outcome.action is StepAction.PASS
    assert plain.state.orders[plain.order_id].status is OrderStatus.ENACTED


def test_a_step_on_a_seats_own_order_its_own_leader_holds_still_waits(
    table: AsyncTable,
) -> None:
    """Roosevelt's bill passes Rayburn and reaches Roosevelt's own step: it waits for
    him, with no due day and no paper, as before."""
    t = table
    with t.ids_drawn.drawn_by(t.fdr):
        order = realism_tick.file_order(
            t.store, CAMPAIGN, t.fdr, "send_bill", {"bill": "neutrality_revision"}
        )
    state = t.state
    far = order.filed + timedelta(days=90)
    for n in range(200):
        out = pipelines.run_pipelines(state, far, f"s{n}")
        mine = [p for p in out if isinstance(p, ev.OrderStepTaken) and p.order_id == order.order_id]
        if mine and mine[0].outcome.action in (StepAction.PASS, StepAction.EXPEDITE):
            break
    else:
        raise AssertionError("no seed passes Rayburn's step")
    assert [p.outcome.step for p in mine] == [0]
    moved = replay(
        [
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "due-test", k)),
                campaign_id=CAMPAIGN,
                seq=state.last_seq + 1 + k,
                tick=state.tick,
                scope=PUBLIC,
                payload=p,
                versions=cmp.versions(),
            )
            for k, p in enumerate(out)
        ],
        initial=state,
    )
    assert pipelines.waiting_on_human(moved, moved.orders[order.order_id])
    assert pipelines.held_due(moved, moved.orders[order.order_id]) is None
    later = pipelines.run_pipelines(moved, far + timedelta(days=90), "s")
    held = pipelines.held_paper_id(CAMPAIGN, order.order_id, 1)
    assert not [
        p
        for p in later
        if (isinstance(p, ev.OrderStepTaken) and p.order_id == order.order_id)
        or (isinstance(p, ev.DocumentIssued) and p.document.doc_id == held)
    ]
    assert advance.awaiting(moved, t.fdr, far) == []
