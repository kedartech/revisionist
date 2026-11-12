"""People nobody plays answer what is done to them: written answers, taken up when an
act lands, made through the same routing as a player's order, at a cost in regard."""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, replay
from revisionist.core.ids import CampaignId, EntityId, FeatureId, OrderId, ScheduledEventId, SeatId
from revisionist.core.ontology import SeatKind
from revisionist.core.project import project
from revisionist.core.realism import answering, opponents
from revisionist.core.realism.agenda import MandateKind
from revisionist.core.realism.answer import AnswerAct, AnswerWhen
from revisionist.core.realism.apply import shift
from revisionist.core.realism.card import ParamKind, ParamSpec
from revisionist.core.realism.effect import Deal, MakeStatement, MoveForce, ShiftDisposition
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.stance import Stance, StanceCause
from revisionist.core.sealing import needs_admin_read
from revisionist.core.state import State
from revisionist.core.world_compile import WorldError, compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.emit import Emitter
from revisionist.engine.realism_tick import run_realism_tick
from revisionist.engine.store import EventStore, MemoryStore, load_state

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
DECL = cmp.load_world(cmp.world_path("autumn-1941"))
KEYS = {k: EntityId(v) for k, v in resolve_keys(DECL, CAMPAIGN).items()}
SHOOT = {"order": "shoot_on_sight", "zone": "western_atlantic"}


def _game(who: str, decl: object = DECL) -> tuple[MemoryStore, SeatId]:
    store = MemoryStore()
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))  # type: ignore[arg-type]
    realism_tick.seat_player(store, CAMPAIGN, KEYS[who])
    (seat,) = load_state(store, CAMPAIGN).seats
    return store, seat


def _payloads(store: EventStore) -> list[ev.Payload]:
    return [e.payload for e in store.read(CAMPAIGN)]


def _tick_until(store: EventStore, done: object, most: int = 12) -> None:
    for _ in range(most):
        run_realism_tick(store, CAMPAIGN)
        if done(load_state(store, CAMPAIGN)):  # type: ignore[operator]
            return
    raise AssertionError("never happened")


def _hitler_answered(state: State) -> bool:
    return bool(state.answers.get(KEYS["hitler"], {}).get("spare_american_ships"))


SHOT = OrderId("01M7AAAAAAAAAAAAAAAAAAAAAA")
"""A fixed id: the pipeline's friction is seeded by it, so the order goes through on
the same day every run."""


def _roosevelt_shoots() -> tuple[MemoryStore, SeatId, OrderId]:
    store, seat = _game("roosevelt")
    state = load_state(store, CAMPAIGN)
    order = realism_tick.draft_order(state, seat, "naval_order", SHOOT)
    order = order.model_copy(update={"order_id": SHOT})
    realism_tick._append(store, state, ev.OrderDrafted(order=order), seat)
    return store, seat, SHOT


# --- the world file ------------------------------------------------------------


def test_the_world_compiles_and_every_head_has_answers() -> None:
    state = replay(compile_world(DECL, CAMPAIGN, cmp.versions()))
    heads = ("roosevelt", "churchill", "stalin", "hitler", "konoe", "tojo", "mussolini", "chiang")
    assert all(state.cards[KEYS[h]].answers for h in heads)
    konoe = {a.key: a for a in state.cards[KEYS["konoe"]].answers}
    assert konoe["summit_offer"].until == ScheduledEventId(KEYS["konoe_resigns"])
    deal = konoe["summit_offer"].act.effect
    assert isinstance(deal, Deal) and deal.counterparty == KEYS["roosevelt"]


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"act": AnswerAct(lever="no_such_form")}, "has no form no_such_form"),
        (
            {"act": AnswerAct(effect=MakeStatement(theme="x", audience=EntityId("nobody")))},
            "unknown entity nobody",
        ),
        (
            {"act": AnswerAct(lever="naval_order", params={"order": "shoot_on_sight"})},
            "takes exactly",
        ),
        (
            {
                "when": AnswerWhen(
                    lever="uboat_directive",
                    params={"posture": ("sink_all",)},
                    by=EntityId("germany"),
                )
            },
            "fits no form",
        ),
        (
            {"when": AnswerWhen(lever="uboat_directive", by=EntityId("atlantis"))},
            "unknown entity atlantis",
        ),
        (
            {
                "act": AnswerAct(
                    effect=MoveForce(force=FeatureId("uboat_arm"), to=EntityId("reykjavik"))
                )
            },
            "uboat_arm is not under roosevelt",
        ),
        ({"aim": 3, "until": ScheduledEventId("no_such_day")}, "unknown history no_such_day"),
    ],
)
def test_a_bad_answer_is_named_by_the_compiler(change: dict[str, object], problem: str) -> None:
    cards = list(DECL.cards)
    i = next(i for i, c in enumerate(cards) if c.person == "roosevelt")
    first = cards[i].answers[0]
    cards[i] = cards[i].model_copy(update={"answers": (first.model_copy(update=change),)})
    with pytest.raises(WorldError) as err:
        compile_world(DECL.model_copy(update={"cards": tuple(cards)}), CAMPAIGN, cmp.versions())
    assert problem in str(err.value), str(err.value)


# --- taking up an answer --------------------------------------------------------


def test_an_act_sets_off_an_answer_at_a_cost_in_regard() -> None:
    store, _, order = _roosevelt_shoots()
    _tick_until(store, _hitler_answered)
    log = _payloads(store)
    planned = [p for p in log if isinstance(p, ev.AnswerPlanned)]
    hitler = next(p for p in planned if p.key == "spare_american_ships")
    assert (hitler.figure, hitler.cause, hitler.toward) == (
        KEYS["hitler"],
        order,
        KEYS["roosevelt"],
    )
    assert hitler.due == hitler.on + timedelta(days=3)
    drop = log[log.index(hitler) - 1]
    assert isinstance(drop, ev.RelationshipSet)
    rel = drop.relationship
    assert {rel.a, rel.b} == {KEYS["hitler"], KEYS["roosevelt"]} and rel.disposition == -1
    assert all(p.key != "unrestricted_after_all" for p in planned)  # gate: hostile only


def test_the_answer_is_an_order_of_the_figures_own_seat_hidden_from_the_player() -> None:
    store, seat, _ = _roosevelt_shoots()
    _tick_until(
        store,
        lambda s: (
            (log := s.answers.get(KEYS["hitler"], {}).get("spare_american_ships")) is not None
            and log.made is not None
        ),
    )
    state = load_state(store, CAMPAIGN)
    made = state.answers[KEYS["hitler"]]["spare_american_ships"]
    assert made.order is not None and made.made == made.due
    order = state.orders[made.order]
    assert order.lever == "uboat_directive"
    assert order.params == {"posture": "restrict_us_ships", "theatre": "north_atlantic"}
    ai = state.seats[order.issuer]
    assert ai.kind is SeatKind.FACTION and ai.embodies == KEYS["hitler"]
    assert made.order not in project(state, seat).orders
    drafted = next(
        e
        for e in store.read(CAMPAIGN)
        if isinstance(e.payload, ev.OrderDrafted) and e.payload.order.order_id == made.order
    )
    assert drafted.scope.known_by == frozenset({order.issuer})


@pytest.mark.parametrize("who", ["roosevelt", "churchill"])
def test_nothing_is_issued_to_a_seat_nobody_plays(who: str) -> None:
    if who == "roosevelt":
        store, seat, _ = _roosevelt_shoots()
    else:
        store, seat = _game(who)
    for _ in range(8):
        run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    issuers = [o.issuer for o in state.orders.values()] + [o.issuer for o in state.routed.values()]
    assert any(i != seat for i in issuers)  # the AI did act
    ai = {s for s, held in state.seats.items() if held.kind is SeatKind.FACTION}
    for doc in state.documents.values():
        assert not (doc.view.scope.known_by & ai), doc.view.title


def test_an_answer_is_taken_up_once_per_act() -> None:
    store, _, _ = _roosevelt_shoots()
    _tick_until(store, _hitler_answered)
    state = load_state(store, CAMPAIGN)
    log = state.answers[KEYS["hitler"]]["spare_american_ships"]
    for later in (log.planned, log.due, log.due + timedelta(days=40)):
        again = answering.plan(state, later, since=log.planned)
        assert all(
            not (isinstance(p, ev.AnswerPlanned) and p.key == "spare_american_ships") for p in again
        )


def _with_answer(state: State, figure: EntityId, key: str, **change: object) -> State:
    answers = tuple(
        a.model_copy(update=change) if a.key == key else a for a in state.cards[figure].answers
    )
    card = state.cards[figure].model_copy(update={"answers": answers})
    return state.model_copy(update={"cards": {**state.cards, figure: card}})


def _fold(state: State, *payloads: ev.Payload) -> State:
    em = Emitter(MemoryStore(), state, cmp.versions())
    return replay([em.event(p) for p in payloads], initial=state)


def test_an_answer_waits_out_its_cooldown() -> None:
    store, _ = _game("roosevelt")
    run_realism_tick(store, CAMPAIGN)
    konoe, start = KEYS["konoe"], date(1941, 9, 6)
    state = _with_answer(load_state(store, CAMPAIGN), konoe, "summit_offer", cooldown_days=21)
    state = _with_answer(state, konoe, "summit_offer", when=AnswerWhen(every_days=7, start=start))
    state = state.model_copy(update={"answers": {}})
    state = _fold(
        state,
        ev.AnswerPlanned(figure=konoe, key="summit_offer", on=start, due=start),
        ev.AnswerMade(figure=konoe, key="summit_offer", on=start, refusal="x"),
    )

    def offered(day: date) -> bool:
        return any(
            isinstance(p, ev.AnswerPlanned) and p.key == "summit_offer"
            for p in answering.plan(state, day)
        )

    assert not offered(start + timedelta(days=7))
    assert not offered(start + timedelta(days=14))
    assert offered(start + timedelta(days=21))


def test_a_good_turn_costs_no_regard() -> None:
    store, _, order = _roosevelt_shoots()
    _tick_until(store, lambda s: s.orders[order].status is OrderStatus.ENACTED)
    state = load_state(store, CAMPAIGN)
    hitler = KEYS["hitler"]
    on = state.orders[order]
    day = on.outcomes[-1].on
    kind = state.cards[hitler].answers
    kind = tuple(a.model_copy(update={"helps": True}) for a in kind)
    state = state.model_copy(
        update={
            "cards": {
                **state.cards,
                hitler: state.cards[hitler].model_copy(update={"answers": kind}),
            },
            "answers": {},
        }
    )
    planned = answering.plan(state, day)
    assert any(isinstance(p, ev.AnswerPlanned) and p.figure == hitler for p in planned)
    assert not any(isinstance(p, ev.RelationshipSet) for p in planned)


def test_an_answer_for_players_only_is_not_set_off_by_a_figure_nobody_plays() -> None:
    store, _, order = _roosevelt_shoots()
    _tick_until(store, lambda s: s.orders[order].status is OrderStatus.ENACTED)
    state = load_state(store, CAMPAIGN)
    act = next(a for a in answering.acts_on(state, state.orders[order].outcomes[-1].on))
    when = AnswerWhen(lever="naval_order", by=EntityId(KEYS["usa"]), human=True)
    assert answering.matches(state, when, act)
    ai = SeatId("ai-roosevelt")
    held = state.seats[act.seat].model_copy(update={"seat_id": ai, "kind": SeatKind.FACTION})
    state = state.model_copy(update={"seats": {**state.seats, ai: held}})
    assert not answering.matches(state, when, act._replace(seat=ai))


# --- a deal put to a player ---------------------------------------------------


def test_a_deal_with_a_player_reaches_them_as_an_approach() -> None:
    store, seat = _game("roosevelt")
    _tick_until(store, lambda s: KEYS["konoe"] in s.answers)
    state = load_state(store, CAMPAIGN)
    made = state.answers[KEYS["konoe"]]["summit_offer"]
    assert made.planned == date(1941, 9, 6) and made.mandate is not None
    mandate = state.mandates[made.mandate]
    assert (mandate.seat_id, mandate.kind) == (seat, MandateKind.OPPORTUNITY)
    assert mandate.text.startswith("Fumimaro Konoe asks for") or "Konoe" in mandate.text
    assert "withdrawal from southern Indochina" in mandate.text
    assert made.mandate in project(state, seat).mandates


def test_a_retired_answer_is_not_taken_up() -> None:
    store, _ = _game("roosevelt")
    run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN).model_copy(update={"answers": {}})
    assert any(
        isinstance(p, ev.AnswerPlanned) and p.key == "summit_offer"
        for p in answering.plan(state, date(1941, 9, 6))
    )
    gone = ScheduledEventId(KEYS["konoe_resigns"])
    item = state.scheduled[gone].model_copy(update={"fired": True})
    state = state.model_copy(update={"scheduled": {**state.scheduled, gone: item}})
    planned = answering.plan(state, date(1941, 9, 6))
    assert not any(isinstance(p, ev.AnswerPlanned) and p.key == "summit_offer" for p in planned)


def test_an_approach_waits_for_room_on_the_desk() -> None:
    store, _ = _game("roosevelt")
    state = load_state(store, CAMPAIGN)
    konoe = KEYS["konoe"]
    answer = next(a for a in state.cards[konoe].answers if a.key == "summit_offer")
    deal = answer.act.effect
    assert isinstance(deal, Deal)
    put = answering._approach(state, konoe, answer, deal, date(1941, 9, 6))
    assert isinstance(put, ev.MandateIssued)
    full = state
    for n in range(3):
        m = put.mandate.model_copy(update={"mandate_id": f"m{n}", "text": "x"})
        full = full.model_copy(update={"mandates": {**full.mandates, m.mandate_id: m}})
    assert answering._approach(full, konoe, answer, deal, date(1941, 9, 6)) == "their desk is full"


# --- caps and replay ------------------------------------------------------------


def _due(state: State, figures: list[EntityId], on: date) -> State:
    batch = []
    for figure in figures:
        key = state.cards[figure].answers[0].key
        batch.append(ev.AnswerPlanned(figure=figure, key=key, on=on, due=on))
    em = Emitter(MemoryStore(), state, cmp.versions())
    return replay([em.event(p) for p in batch], initial=state)


def test_one_answer_per_figure_and_six_per_game_on_one_day() -> None:
    store, _ = _game("roosevelt")
    state = load_state(store, CAMPAIGN)
    run_realism_tick(store, CAMPAIGN)  # seats the heads nobody plays
    state = load_state(store, CAMPAIGN)
    figures = answering.answerers(state)
    assert len(figures) == 7
    day = date(1941, 9, 10)
    state = _due(state, figures, day)
    em = Emitter(MemoryStore(), state, cmp.versions())
    made: list[ev.AnswerMade] = []
    while batch := answering.make(state, day):
        state = replay([em.event(p) for p in batch], initial=state)
        made += [p for p in batch if isinstance(p, ev.AnswerMade)]
    assert len(made) == answering.DAILY
    assert len({m.figure for m in made}) == answering.DAILY
    left = [f for f in figures if state.answers[f][state.cards[f].answers[0].key].made is None]
    assert len(left) == 1
    nxt = answering.make(state, day + timedelta(days=1))
    assert any(isinstance(p, ev.AnswerMade) and p.figure == left[0] for p in nxt)


def test_a_figure_makes_one_answer_a_day() -> None:
    store, _ = _game("roosevelt")
    run_realism_tick(store, CAMPAIGN)
    hitler, day = KEYS["hitler"], date(1941, 9, 10)
    state = load_state(store, CAMPAIGN)
    first, second = (a.key for a in state.cards[hitler].answers[:2])
    state = _fold(
        state,
        ev.AnswerPlanned(figure=hitler, key=first, on=day, due=day),
        ev.AnswerPlanned(figure=hitler, key=second, on=day, due=day),
    )
    made = answering.make(state, day)
    state = _fold(state, *made)
    assert answering.make(state, day) == []
    assert answering.make(state, day + timedelta(days=1))


def test_the_same_game_answers_the_same_way() -> None:
    runs = []
    for _ in range(2):
        store, _, _ = _roosevelt_shoots()
        for _ in range(6):
            run_realism_tick(store, CAMPAIGN)
        runs.append(
            [
                p.model_dump()
                for p in _payloads(store)
                if isinstance(p, ev.AnswerPlanned | ev.AnswerMade | ev.OrderDrafted)
                and not (isinstance(p, ev.OrderDrafted) and p.order.lever == "naval_order")
            ]
        )
    assert runs[0] == runs[1] and runs[0]


# --- older games, the fold, the seal --------------------------------------------


def test_a_game_begun_before_the_answers_takes_them_at_its_next_wake() -> None:
    bare = DECL.model_copy(
        update={
            "cards": tuple(
                c.model_copy(update={"answers": (), "opposes": (), "allies": ()})
                for c in DECL.cards
            )
        }
    )
    store, _ = _game("churchill", bare)
    assert not any(c.answers for c in load_state(store, CAMPAIGN).cards.values())
    run_realism_tick(store, CAMPAIGN)
    amended = [p for p in _payloads(store) if isinstance(p, ev.CardAmended)]
    assert len(amended) == 8
    state = load_state(store, CAMPAIGN)
    assert state.cards[KEYS["hitler"]].answers == load_state_fresh().cards[KEYS["hitler"]].answers
    assert len(answering.answerers(state)) == 7
    run_realism_tick(store, CAMPAIGN)
    assert not [p for p in _payloads(store) if isinstance(p, ev.CardAmended)][8:]


def load_state_fresh() -> State:
    return replay(compile_world(DECL, CAMPAIGN, cmp.versions()))


def test_a_game_from_a_world_with_no_file_is_left_alone() -> None:
    store, _ = _game("churchill", DECL.model_copy(update={"world": "no-such-world"}))
    run_realism_tick(store, CAMPAIGN)
    assert not any(isinstance(p, ev.CardAmended) for p in _payloads(store))


def test_the_fold_refuses_an_answer_out_of_turn() -> None:
    state = load_state_fresh()
    hitler = KEYS["hitler"]
    em = Emitter(MemoryStore(), state, cmp.versions())
    made = ev.AnswerMade(
        figure=hitler, key="spare_american_ships", on=date(1941, 9, 9), refusal="x"
    )
    with pytest.raises(FoldError):
        replay([em.event(made)], initial=state)
    plan = ev.AnswerPlanned(
        figure=hitler, key="spare_american_ships", on=date(1941, 9, 9), due=date(1941, 9, 12)
    )
    again = plan.model_copy(update={"on": date(1941, 9, 10)})
    em = Emitter(MemoryStore(), state, cmp.versions())
    with pytest.raises(FoldError):
        replay([em.event(plan), em.event(again)], initial=state)
    em = Emitter(MemoryStore(), state, cmp.versions())
    with pytest.raises(FoldError):
        replay([em.event(plan.model_copy(update={"key": "no_such_answer"}))], initial=state)


def test_answers_and_amendments_need_an_admin_read() -> None:
    state = load_state_fresh()
    em = Emitter(MemoryStore(), state, cmp.versions())
    hitler = KEYS["hitler"]
    for payload in (
        ev.AnswerPlanned(figure=hitler, key="k", on=date(1941, 9, 9), due=date(1941, 9, 9)),
        ev.AnswerMade(figure=hitler, key="k", on=date(1941, 9, 9), refusal="x"),
        ev.CardAmended(person=hitler),
    ):
        assert needs_admin_read(em.event(payload))


def test_a_fall_in_regard_names_the_act_that_caused_it() -> None:
    store, seat, order = _roosevelt_shoots()
    run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    hitler, roosevelt = KEYS["hitler"], KEYS["roosevelt"]
    assert state.stances[seat][hitler][-1].stance is Stance.OBSTRUCTING
    ai = next(s for s, h in state.seats.items() if h.embodies == hitler)
    fall = ShiftDisposition(of=hitler, toward=roosevelt, change=-1)
    drop = shift(PassWorld(state), fall, ai)
    assert isinstance(drop, ev.RelationshipSet)
    drop = ev.RelationshipSet(relationship=drop.relationship.model_copy(update={"disposition": -5}))
    day = date(1941, 9, 9)
    plan = ev.AnswerPlanned(
        figure=hitler, key="spare_american_ships", on=day, due=day, cause=order, toward=roosevelt
    )
    em = Emitter(MemoryStore(), state, cmp.versions())
    after = replay([em.event(drop), em.event(plan)], initial=state)
    changed = [
        p
        for p in opponents.settle(after, day, [drop, plan])
        if isinstance(p, ev.StanceChanged) and p.figure == hitler
    ]
    assert changed and changed[0].standing.stance is Stance.HOSTILE
    assert changed[0].standing.cause is StanceCause.DISPOSITION
    assert changed[0].standing.order == order


def test_an_answer_may_not_name_an_entity_parameter() -> None:
    cards = list(DECL.cards)
    i = next(i for i, c in enumerate(cards) if c.person == "roosevelt")
    lever = cards[i].levers[0]
    who = ParamSpec(name="whom", kind=ParamKind.ENTITY)
    named = lever.model_copy(update={"name": "name_someone", "params": (who,)})
    act = AnswerAct(lever="name_someone", params={"whom": "stalin"})
    answer = cards[i].answers[0].model_copy(update={"act": act})
    cards[i] = cards[i].model_copy(
        update={"levers": (*cards[i].levers, named), "answers": (answer,)}
    )
    with pytest.raises(WorldError) as err:
        compile_world(DECL.model_copy(update={"cards": tuple(cards)}), CAMPAIGN, cmp.versions())
    assert "names a person or place" in str(err.value), str(err.value)


def test_what_an_ai_head_plans_is_scoped_to_its_own_seat() -> None:
    store, _, _ = _roosevelt_shoots()
    _tick_until(
        store,
        lambda s: (
            (log := s.answers.get(KEYS["hitler"], {}).get("spare_american_ships")) is not None
            and log.made is not None
        ),
    )
    state = load_state(store, CAMPAIGN)
    seen = 0
    for e in store.read(CAMPAIGN):
        if isinstance(e.payload, ev.AnswerPlanned | ev.AnswerMade):
            seat = next(s for s, h in state.seats.items() if h.embodies == e.payload.figure)
            assert e.scope.known_by == frozenset({seat}), e.payload.kind
            seen += 1
    assert seen


def test_an_act_from_the_last_wake_is_read_again_only_if_it_landed_between_ticks() -> None:
    store, _, order = _roosevelt_shoots()
    _tick_until(store, lambda s: s.orders[order].status is OrderStatus.ENACTED)
    state = load_state(store, CAMPAIGN).model_copy(update={"answers": {}})
    landed = state.orders[order].outcomes[-1].on
    after = landed + timedelta(days=1)

    def hitler_plans(between: frozenset[OrderId]) -> bool:
        return any(
            isinstance(p, ev.AnswerPlanned) and p.figure == KEYS["hitler"]
            for p in answering.plan(state, after, since=landed, between=between)
        )

    assert not hitler_plans(frozenset())
    assert hitler_plans(frozenset({order}))
