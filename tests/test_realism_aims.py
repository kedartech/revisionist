"""Aims become goals (AIM).

The toy world (``tests/worlds/territory-toy.yaml``) is played with the ``aims`` rule on
and rules added to the cards' aims: Ilse of Norra and Tomas of Sudland each get aims
whose conditions read what the territory rules move. When a player holds a person, the
tick makes one goal per aim with a rule, keyed to the person and private to the seat
that holds him; a person handed on keeps his goals, none made twice. Goals are checked
every tick from state alone, whoever played the wake; an aim is met while its condition
holds, failed once it cannot change, and otherwise at risk.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.goals import (
    AgreementInForce,
    AimRule,
    AimStatus,
    AtWar,
    ContestWon,
    Exposure,
    Goal,
    GoalKind,
    GoalSource,
    HoldsArea,
    IncomeAt,
    QuantityAt,
    RegardAt,
    SupportAt,
    WinCondition,
    aim_goals,
    aim_status,
    check,
    goal_met,
    judged,
)
from revisionist.core.ids import (
    ContestId,
    EntityId,
    GoalId,
    OrderId,
    PipelineId,
    QuantityId,
    RelationshipId,
    SeatId,
    derived_id,
)
from revisionist.core.ontology import Controller, Relationship, Seat, SeatKind
from revisionist.core.project import project
from revisionist.core.realism import economy
from revisionist.core.realism.agreement import Agreement, ClauseStatus
from revisionist.core.realism.card import SeatCard
from revisionist.core.realism.effect import AgreementClause, ClauseType
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.war import war_id_for
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.emit import Emitter
from revisionist.engine.store import MemoryStore, load_state
from tests.test_adjacency_moves import START, fold, toy
from tests.test_territory_model import CAMPAIGN, refused

World = dict[str, Any]
RULES = ("territories", "holders", "agreements", "groups", "contests", "aims")
DEADLINE = datetime(2030, 1, 1, tzinfo=UTC)


def key_id(key: str, section: str = "entity") -> str:
    return object_id(CAMPAIGN, section, key)


NORRA, SUDLAND = EntityId(key_id("norra")), EntityId(key_id("sudland"))
ILSE, TOMAS = EntityId(key_id("ilse")), EntityId(key_id("tomas"))
HILLS, ISLE = EntityId(key_id("norra_hills")), EntityId(key_id("isle"))
BORDER = ContestId(key_id("border", "contest"))
SHIPPING = QuantityId(key_id("norra_shipping", "quantity"))
HILLS_HELD: World = {"check": "holds_area", "area": "norra_hills", "holder": "norra"}
ISLE_HELD: World = {"check": "holds_area", "area": "isle", "holder": "norra"}


def day(n: int) -> date:
    return START + timedelta(days=n)


def rule(aim: int, condition: World, **more: Any) -> World:
    return {"aim": aim, "rule": f"Aim {aim} holds.", "condition": condition, **more}


def aims(
    ilse: tuple[World, ...] = (rule(1, HILLS_HELD), rule(2, ISLE_HELD, replaceable=True)),
    tomas: tuple[World, ...] = (rule(1, {**ISLE_HELD, "holder": "sudland"}),),
    on: bool = True,
) -> Callable[[World], None]:
    """The aims rule (unless ``on`` is false) and the cards' aims with these rules."""

    def change(w: World) -> None:
        w["rules"] = list(RULES if on else RULES[:-1])
        w["cards"][0]["aims"] = ["Keep the hills.", "Take the isle.", "End the war."]
        w["cards"][0]["aim_rules"] = list(ilse)
        w["cards"][1]["aims"] = ["Hold the isle."]
        w["cards"][1]["aim_rules"] = list(tomas)

    return change


def border(w: World) -> None:
    """A rivalry over the border, Norra against Sudland, so a contest can be won."""
    w["contests"] = [
        {"key": "border", "kind": "rivalry", "name": "The Border War", "prize": "The hills",
         "sides": ["norra", "sudland"], "countdown_days": 30},
    ]  # fmt: skip
    w["assets"] = [
        {"key": "chancellery", "kind": "office", "name": "Chancellery", "tier": 3,
         "controller": "ilse"},
        {"key": "premiership", "kind": "office", "name": "Premiership", "tier": 3,
         "controller": "tomas"},
    ]  # fmt: skip


def world(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    return toy(tmp, border, *(changes or (aims(),)))


class Game:
    """A toy game in an event store, played through the realism tick."""

    def __init__(self, w: WorldFile, *people: EntityId) -> None:
        self.store = MemoryStore()
        self.store.append_all(compile_world(w, CAMPAIGN, cmp.versions()))
        for person in people or (ILSE,):
            realism_tick.seat_player(self.store, CAMPAIGN, person)

    @property
    def state(self) -> State:
        return load_state(self.store, CAMPAIGN)

    def land(self, *payloads: ev.Payload) -> None:
        em = Emitter(self.store, self.state, cmp.versions())
        em.commit([em.event(p) for p in payloads])

    def tick(self) -> list[ev.Event]:
        before = len(list(self.store.read(CAMPAIGN)))
        realism_tick.run_realism_tick(self.store, CAMPAIGN)
        return list(self.store.read(CAMPAIGN))[before:]

    def hand(self, person: EntityId, to: Controller) -> None:
        """``person`` changes hands at a wake boundary: the change lands, the wake closes."""
        w = self.state.wake
        n = 0 if w is None else w.number + 1
        self.land(ev.WakeOpened(wake=n, deadline=DEADLINE))
        self.land(ev.SeatHandover(entity_id=person, controller=to))
        self.land(ev.WakeClosed(wake=n))


def seat_of(state: State, person: EntityId) -> SeatId:
    return next(s.seat_id for s in state.seats.values() if s.embodies == person)


def own_goals(state: State, person: EntityId) -> list[Goal]:
    return sorted((g for g in state.goals.values() if g.person == person), key=lambda g: g.aim or 0)


def with_goal(state: State, condition: WinCondition, **rule_fields: Any) -> tuple[State, Goal]:
    """``state`` with Ilse's first aim ruled by ``condition`` and its goal made."""
    card = state.cards[ILSE]
    from revisionist.core.goals import leaves

    aim = AimRule(
        condition=condition,
        rule="As written.",
        sees=tuple(Exposure.PUBLIC for _ in leaves(condition)),
        **rule_fields,
    )
    card = card.model_copy(update={"aim_rules": (aim,)})
    state = state.model_copy(
        update={"cards": {**state.cards, ILSE: card}, "goals": {}, "in_world_date": START}
    )
    (made,) = [g for g in aim_goals(state) if g.goal.person == ILSE]
    return fold(state, [made]), made.goal


@pytest.fixture
def played(tmp_path: Path) -> Game:
    return Game(world(tmp_path))


# --- rule 1 and 5: the card carries each aim's rule ------------------------------------


def test_each_aim_rule_compiles_onto_the_card_by_its_aims_index(played: Game) -> None:
    card = played.state.cards[ILSE]
    assert card.aims[:2] == ("Keep the hills.", "Take the isle.")
    first, second = card.aim_rules
    assert first is not None and second is not None
    assert first.condition == HoldsArea(area=HILLS, holder=NORRA)
    assert second.condition == HoldsArea(area=ISLE, holder=NORRA)
    assert first.rule == "Aim 1 holds." and (first.replaceable, second.replaceable) == (False, True)
    assert first.sees == (Exposure.PUBLIC,)


def test_a_gap_in_the_aims_rules_is_kept_by_index(tmp_path: Path) -> None:
    g = Game(world(tmp_path, aims(ilse=(rule(2, ISLE_HELD),))))
    assert g.state.cards[ILSE].aim_rules[0] is None
    assert [x.aim for x in g.state.goals.values() if x.person == ILSE] == []
    g.tick()
    assert [x.aim for x in own_goals(g.state, ILSE)] == [2]


def test_each_leaf_says_whether_the_seat_may_see_what_it_reads(tmp_path: Path) -> None:
    leaves_: World = {
        "check": "all_of",
        "conditions": [
            HILLS_HELD,
            {"check": "support_at", "nation": "norra", "group": "greens", "op": "ge", "value": 50},
            {"check": "support_at", "nation": "sudland", "group": "farmers", "op": "le",
             "value": 20},
            {"check": "quantity_at", "quantity": "norra_shipping", "op": "ge", "value": 1},
            {"check": "regard_at", "a": "tomas", "b": "sudland", "op": "ge", "value": 1},
            {"check": "contest_won", "contest": "border", "side": "norra"},
            {"check": "agreement_in_force", "between": ["norra", "sudland"]},
        ],
    }  # fmt: skip
    g = Game(world(tmp_path, aims(ilse=(rule(1, leaves_),))))
    first = g.state.cards[ILSE].aim_rules[0]
    assert first is not None
    assert first.sees == (
        Exposure.PUBLIC,
        Exposure.OWN,
        Exposure.HIDDEN,
        Exposure.OWN,
        Exposure.HIDDEN,
        Exposure.PUBLIC,
        Exposure.OWN,
    )


def test_a_card_with_two_replaceable_aims_is_refused(tmp_path: Path) -> None:
    two = (rule(1, HILLS_HELD, replaceable=True), rule(2, ISLE_HELD, replaceable=True))
    assert "card ilse: at most one aim is replaceable" in refused(world(tmp_path, aims(ilse=two)))
    aim = AimRule(condition=HoldsArea(area=HILLS, holder=NORRA), rule="x", sees=(Exposure.PUBLIC,))
    with pytest.raises(ValidationError, match="at most one aim is replaceable"):
        SeatCard(
            person=ILSE,
            office="Chancellor",
            horizon_days=14,
            aims=("a", "b"),
            aim_rules=(
                aim.model_copy(update={"replaceable": True}),
                aim.model_copy(update={"replaceable": True}),
            ),
        )


def test_an_aim_rule_names_what_the_world_declares(tmp_path: Path) -> None:
    bad = (
        rule(3, HILLS_HELD),
        rule(1, {"check": "support_at", "nation": "norra", "group": "farmers", "op": "ge",
                 "value": 1}),
        rule(2, {"check": "contest_won", "contest": "nowhere", "side": "norra"},
             opens="1900-05-01", deadline="1900-04-20"),
    )  # fmt: skip
    one_card = aims(ilse=bad, tomas=(rule(1, ISLE_HELD), rule(1, ISLE_HELD)))
    problems = refused(world(tmp_path, one_card))
    assert "card ilse aim 3: the card has no aim 3" not in problems  # it has three aims
    assert "card ilse aim 1: norra has no group farmers" in problems
    assert "card ilse aim 2: unknown contest nowhere" in problems
    assert "card ilse aim 2: opens after its deadline" in problems
    assert "card tomas: an aim has two rules" in problems


def test_an_aim_rule_for_an_aim_the_card_lacks_is_refused(tmp_path: Path) -> None:
    problems = refused(world(tmp_path, aims(tomas=(rule(2, ISLE_HELD),))))
    assert "card tomas aim 2: the card has no aim 2" in problems


# --- rule 6: gated by aims --------------------------------------------------------------


def test_with_the_rule_off_no_rule_reaches_the_card_and_no_goal_is_made(tmp_path: Path) -> None:
    g = Game(world(tmp_path, aims(on=False)))
    assert g.state.cards[ILSE].aim_rules == ()
    g.tick()
    assert g.state.goals == {}


def test_the_fold_refuses_an_aims_goal_with_the_rule_off(tmp_path: Path, played: Game) -> None:
    state = played.state
    (made, *_) = aim_goals(state)
    off = state.model_copy(update={"rules": state.rules - {r for r in state.rules if r == "aims"}})
    with pytest.raises(FoldError, match="aims are not part of this game"):
        fold(off, [made])


# --- rule 2: one goal per aim, keyed to the person ------------------------------------


def test_the_tick_makes_one_private_goal_per_aim_for_the_person_a_player_holds(
    played: Game,
) -> None:
    played.tick()
    state = played.state
    seat = seat_of(state, ILSE)
    first, second = own_goals(state, ILSE)
    assert (first.aim, second.aim) == (1, 2)
    assert first.text == "Keep the hills." and first.source is GoalSource.POST
    assert first.person == ILSE and first.seat_id == seat and first.clock_id is None
    assert first.scope == private_to(seat)
    assert first.kind is GoalKind.UNDOABLE
    assert len(state.goals) == 2  # Tomas is code-run: his aim makes no goal
    assert set(project(state, seat).goals) == {first.goal_id, second.goal_id}


def test_a_code_seats_person_gets_no_goals_and_no_view_of_them(played: Game) -> None:
    state = played.state
    code = Seat(seat_id=SeatId("01ARZ3NDEKTSV4RRFFQ69G5FC0"), kind=SeatKind.PLAYER,
                name="Tomas Brand", embodies=TOMAS, controller=Controller.AI)  # fmt: skip
    state = state.model_copy(update={"seats": {**state.seats, code.seat_id: code}})
    assert [g.goal.person for g in aim_goals(state)] == [ILSE, ILSE]
    state = fold(state, aim_goals(state))
    assert project(state, code.seat_id).goals == {}
    made = aim_goals(state.model_copy(update={"goals": {}}))
    forged = made[0].goal.model_copy(
        update={"goal_id": GoalId("01ARZ3NDEKTSV4RRFFQ69G5FC1"), "seat_id": code.seat_id,
                "person": TOMAS}
    )  # fmt: skip
    with pytest.raises(FoldError, match="no player holding"):
        fold(state, [ev.GoalSet(goal=forged)])


def test_a_second_tick_makes_no_goal_twice(played: Game) -> None:
    played.tick()
    assert aim_goals(played.state) == []
    played.tick()
    assert len(own_goals(played.state, ILSE)) == 2
    (made, *_) = aim_goals(played.state.model_copy(update={"goals": {}}))
    with pytest.raises(FoldError, match="already has a goal"):
        fold(played.state, [made.model_copy(update={"goal": made.goal.model_copy(
            update={"goal_id": GoalId("01ARZ3NDEKTSV4RRFFQ69G5FC2")})})])  # fmt: skip


def test_goals_follow_the_person_through_a_hand_over(played: Game) -> None:
    played.tick()
    state = played.state
    seat = seat_of(state, ILSE)
    made = {g.goal_id for g in own_goals(state, ILSE)}
    played.hand(ILSE, Controller.AI)  # the player leaves: the code runs Ilse
    state = played.state
    assert state.seats[seat].controller is Controller.AI
    assert project(state, seat).goals == {}  # the seat the code runs sees none of them
    played.tick()
    played.hand(ILSE, Controller.HUMAN)  # a new player takes Ilse up
    played.tick()
    state = played.state
    assert {g.goal_id for g in own_goals(state, ILSE)} == made  # kept, none made twice
    assert set(project(state, seat_of(state, ILSE)).goals) == made


def test_goals_are_reached_through_the_seat_holding_the_person_not_their_seat_id(
    played: Game,
) -> None:
    played.tick()
    state = played.state
    old = seat_of(state, ILSE)
    new = SeatId(derived_id(CAMPAIGN, "another seat", ILSE))
    seats = {
        old: state.seats[old].model_copy(update={"embodies": TOMAS}),
        new: state.seats[old].model_copy(update={"seat_id": new}),
    }
    state = state.model_copy(update={"seats": seats})
    made = {g.goal_id for g in own_goals(state, ILSE)}
    assert set(project(state, new).goals) == made
    assert project(state, old).goals == {}


# --- rule 3: checked every tick from state, whoever played -----------------------------


def test_the_tick_meets_an_aim_and_reports_it_to_the_seat_holding_the_person(
    played: Game,
) -> None:
    landed = played.tick()
    seat = seat_of(played.state, ILSE)
    met = [e for e in landed if isinstance(e.payload, ev.GoalMet)]
    hills = own_goals(played.state, ILSE)[0]
    assert [e.payload.goal_id for e in met if isinstance(e.payload, ev.GoalMet)] == [
        hills.goal_id
    ]  # Norra holds the hills
    assert met[0].scope == private_to(seat)
    assert hills.holding


def test_goals_are_checked_through_a_wake_the_code_played(tmp_path: Path) -> None:
    g = Game(world(tmp_path, aims(ilse=(rule(1, {**HILLS_HELD, "holder": "sudland"}),))))
    g.tick()
    (goal,) = own_goals(g.state, ILSE)
    assert not goal.holding
    g.hand(ILSE, Controller.AI)
    today = g.state.in_world_date
    assert today is not None
    g.land(ev.AreaHeld(area=HILLS, holder=SUDLAND, was=NORRA, on=today))
    landed = g.tick()
    met = [e.payload.goal_id for e in landed if isinstance(e.payload, ev.GoalMet)]
    assert met == [goal.goal_id]
    assert own_goals(g.state, ILSE)[0].holding


# --- each new kind of leaf, below, at and above its line ------------------------------


def test_a_territorys_holder(played: Game) -> None:
    state = played.state
    assert goal_met(state, HoldsArea(area=HILLS, holder=NORRA))
    assert not goal_met(state, HoldsArea(area=ISLE, holder=NORRA))


def test_a_nations_income_below_at_and_above_its_line(played: Game) -> None:
    state = played.state
    now = economy.figure(state, NORRA)
    assert now == int(now) and now > 1
    line = int(now)
    assert goal_met(state, IncomeAt(nation=NORRA, op="ge", value=line - 1))
    assert goal_met(state, IncomeAt(nation=NORRA, op="ge", value=line))
    assert not goal_met(state, IncomeAt(nation=NORRA, op="ge", value=line + 1))
    assert not goal_met(state, IncomeAt(nation=NORRA, op="le", value=line - 1))
    assert goal_met(state, IncomeAt(nation=NORRA, op="le", value=line))


def test_a_groups_support_below_at_and_above_its_line(played: Game) -> None:
    state = played.state  # the Greens start at 60
    assert goal_met(state, SupportAt(nation=NORRA, group="greens", op="ge", value=59))
    assert goal_met(state, SupportAt(nation=NORRA, group="greens", op="ge", value=60))
    assert not goal_met(state, SupportAt(nation=NORRA, group="greens", op="ge", value=61))
    assert goal_met(state, SupportAt(nation=NORRA, group="greens", op="le", value=60))
    assert not goal_met(state, SupportAt(nation=NORRA, group="greens", op="le", value=59))
    assert not goal_met(state, SupportAt(nation=SUDLAND, group="greens", op="ge", value=0))


def test_a_quantity_below_at_and_above_its_line(played: Game) -> None:
    state = played.state  # Norra's shipping is 100000 tons
    assert goal_met(state, QuantityAt(quantity=SHIPPING, op="ge", value=99_999))
    assert goal_met(state, QuantityAt(quantity=SHIPPING, op="ge", value=100_000))
    assert not goal_met(state, QuantityAt(quantity=SHIPPING, op="ge", value=100_001))


def test_regard_below_at_and_above_its_line(played: Game) -> None:
    state = played.state
    assert goal_met(state, RegardAt(a=ILSE, b=TOMAS, op="le", value=0))  # none yet: 0
    rel = Relationship(relationship_id=RelationshipId("01ARZ3NDEKTSV4RRFFQ69G5FC3"),
                       a=TOMAS, b=ILSE, disposition=2, scope=PUBLIC)  # fmt: skip
    state = state.model_copy(update={"relationships": {rel.relationship_id: rel}})
    assert goal_met(state, RegardAt(a=ILSE, b=TOMAS, op="ge", value=1))
    assert goal_met(state, RegardAt(a=ILSE, b=TOMAS, op="ge", value=2))
    assert not goal_met(state, RegardAt(a=ILSE, b=TOMAS, op="ge", value=3))


def test_an_agreement_in_force_and_one_broken(played: Game) -> None:
    state = played.state
    leaf = AgreementInForce(between=(NORRA, SUDLAND))
    assert not goal_met(state, leaf)
    clause = AgreementClause(type=ClauseType.NO_ATTACK, binds=NORRA, nation=SUDLAND)
    pact = Agreement(agreement_id="pact", version="v1", parties=(SUDLAND, NORRA),
                     clauses=(clause,), made=START, statuses=(ClauseStatus.STANDING,))  # fmt: skip
    made = state.agreements.model_copy(update={"made": {"pact": pact}})
    assert goal_met(state.model_copy(update={"agreements": made}), leaf)
    broken = pact.model_copy(update={"statuses": (ClauseStatus.BROKEN,)})
    made = state.agreements.model_copy(update={"made": {"pact": broken}})
    assert not goal_met(state.model_copy(update={"agreements": made}), leaf)


def test_a_contest_won(played: Game) -> None:
    state = played.state
    leaf = ContestWon(contest=BORDER, side=NORRA)
    assert not goal_met(state, leaf)
    won = state.contests[BORDER].model_copy(update={"decided": True, "winner": NORRA})
    assert goal_met(state.model_copy(update={"contests": {BORDER: won}}), leaf)
    lost = won.model_copy(update={"winner": SUDLAND})
    assert not goal_met(state.model_copy(update={"contests": {BORDER: lost}}), leaf)


def test_a_war(played: Game) -> None:
    state = played.state  # Norra and Sudland start at war
    assert goal_met(state, AtWar(a=SUDLAND, b=NORRA))
    assert not goal_met(state, AtWar(a=NORRA, b=SUDLAND, war=False))
    peace = state.model_copy(
        update={"wars": {k: v for k, v in state.wars.items() if k != war_id_for(NORRA, SUDLAND)}}
    )
    assert goal_met(peace, AtWar(a=NORRA, b=SUDLAND, war=False))


# --- rule 4: met, failed, at risk ------------------------------------------------------


def test_an_aim_is_met_while_it_holds_and_at_risk_while_it_can_still_come(played: Game) -> None:
    state, goal = with_goal(played.state, HoldsArea(area=HILLS, holder=NORRA))
    assert aim_status(state, goal) is AimStatus.MET
    state, goal = with_goal(played.state, HoldsArea(area=ISLE, holder=NORRA))
    assert aim_status(state, goal) is AimStatus.AT_RISK


def test_an_aim_fails_when_the_world_settles_it(played: Game) -> None:
    state, goal = with_goal(played.state, ContestWon(contest=BORDER, side=NORRA))
    assert aim_status(state, goal) is AimStatus.AT_RISK
    lost = state.contests[BORDER].model_copy(update={"decided": True, "winner": SUDLAND})
    assert aim_status(state.model_copy(update={"contests": {BORDER: lost}}), goal) is (
        AimStatus.FAILED
    )


def test_an_aim_on_its_end_date_and_after_it(played: Game) -> None:
    end = day(10)
    state, goal = with_goal(played.state, HoldsArea(area=ISLE, holder=NORRA), deadline=end)
    on_end = state.model_copy(update={"in_world_date": end})
    assert judged(on_end, goal) and aim_status(on_end, goal) is AimStatus.AT_RISK
    taken = on_end.model_copy(
        update={"holders": {**on_end.holders, **_holding(played, ISLE, NORRA, end)}}
    )
    assert [c.kind for c in check(taken)] == ["goal_met"]  # judged on its last day
    held = fold(taken, check(taken))
    assert aim_status(held, goal) is AimStatus.MET
    after = held.model_copy(update={"in_world_date": end + timedelta(days=1)})
    assert not judged(after, goal)
    lost = after.model_copy(update={"holders": state.holders})
    assert check(lost) == []  # past its deadline it is no longer checked
    assert aim_status(lost, goal) is AimStatus.MET  # as it stood on its last day
    never = after.model_copy(update={"holders": state.holders, "goals": state.goals})
    assert aim_status(never, goal) is AimStatus.FAILED


def test_an_aim_is_not_judged_before_it_opens(played: Game) -> None:
    state, goal = with_goal(played.state, HoldsArea(area=HILLS, holder=NORRA), opens=day(5))
    assert not judged(state, goal) and check(state) == []
    assert aim_status(state, goal) is AimStatus.AT_RISK
    opened = state.model_copy(update={"in_world_date": day(5)})
    assert judged(opened, goal) and aim_status(opened, goal) is AimStatus.MET


def test_status_reads_the_world_never_the_orders_filed(played: Game) -> None:
    state, goal = with_goal(played.state, HoldsArea(area=ISLE, holder=NORRA))
    seat = seat_of(state, ILSE)
    filed = {
        OrderId(derived_id(CAMPAIGN, "aim-order", n)): Order(
            order_id=OrderId(derived_id(CAMPAIGN, "aim-order", n)),
            issuer=seat,
            lever="move_piece",
            pipeline=PipelineId(derived_id(CAMPAIGN, "aim-pipeline")),
            params={"force": "norra_levy", "to": "isle"},
            status=OrderStatus.ENACTED,
            filed=START,
        )
        for n in range(3)
    }
    busy = state.model_copy(update={"orders": filed})
    assert aim_status(busy, goal) is aim_status(state, goal) is AimStatus.AT_RISK
    assert check(busy) == check(state) == []


def _holding(g: Game, area: EntityId, holder: EntityId, since: date) -> dict[EntityId, Any]:
    from revisionist.core.realism.holders import Holding

    return {area: Holding(holder=holder, on=since)}
