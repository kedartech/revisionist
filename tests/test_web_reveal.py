"""The end-of-game reveal (Phase 4, S5): goals, covert acts, style history and the
estimator's rulings, in words, for each seat with a person."""

import re
from datetime import date

import pytest

from revisionist.core import events as ev
from revisionist.core.goals import EntityIs, Goal, goal_kind
from revisionist.core.ids import ClockId, GoalId, OrderId, derived_id
from revisionist.core.ontology import Clock, ClockKind, EntityStatus
from revisionist.core.realism import agenda as ra
from revisionist.core.realism import effect as rx
from revisionist.core.state import State
from revisionist.core.visibility import Visibility, private_to
from revisionist.engine.web import reveal
from tests.test_engine_v2_contract import CAMPAIGN, Slice


@pytest.fixture
def sl() -> Slice:
    return Slice()


def _with_goal(sl: Slice, text: str) -> State:
    state = sl.state
    condition = EntityIs(entity=sl.entity("usa"), status=EntityStatus.ACTIVE)
    clock = ClockId(derived_id(CAMPAIGN, "clock", "goal"))
    objective = Clock(
        clock_id=clock,
        kind=ClockKind.OBJECTIVE,
        name="Goal",
        owner=sl.fdr,
        segments_total=1,
        scope=private_to(sl.fdr),
    )
    goal = Goal(
        goal_id=GoalId(derived_id(CAMPAIGN, "goal", 1)),
        seat_id=sl.fdr,
        text=text,
        condition=condition,
        kind=goal_kind(condition),
        clock_id=clock,
        scope=private_to(sl.fdr),
    )
    return state.model_copy(
        update={
            "clocks": {**state.clocks, clock: objective},
            "goals": {goal.goal_id: goal},
        }
    )


def _estimate(sl: Slice, n: int, part: rx.RoutedPart, rationale: str) -> None:
    order = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "v2-order", n)),
        issuer=sl.fdr,
        filed=date(1941, 9, 11),
        parts=(part,),
    )
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(
        ev.EffectsEstimated(
            order_id=order.order_id, part=0, reason="It was noted.", rationale=rationale
        ),
        private_to(sl.fdr),
    )


def test_everything_appears_in_order_and_in_words(sl: Slice) -> None:
    sl.add(ev.PlayStyleSet(seat_id=sl.fdr, style=ra.PlayStyle.BEGINNER), private_to(sl.fdr))
    _estimate(
        sl,
        1,
        rx.RoutedPart(route=rx.Route.INFLUENCE, target=sl.entity("wheeler")),
        "Wheeler resents the White House; he would stall.",
    )
    sl.add(
        ev.PlayStyleSet(
            seat_id=sl.fdr,
            style=ra.PlayStyle.GUIDED,
            standing=frozenset({rx.EffectKind.APPOINTMENT}),
        ),
        private_to(sl.fdr),
    )
    _estimate(
        sl,
        2,
        rx.RoutedPart(
            route=rx.Route.COMMAND,
            domain="naval_operations",
            executor=sl.entity("stark"),
        ),
        "Stark would read it as leave to escort convoys.",
    )
    order = sl.shoot_on_sight(3)
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr, covert=True))
    assert sl.events[-1].scope.visibility is Visibility.COVERT

    out = reveal.build(_with_goal(sl, "Bring the nation into the convoy war."), sl.events)

    assert out["name"]
    me = next(s for s in out["seats"] if s["person"] == "Franklin D. Roosevelt")
    assert me["goals"] == ["Bring the nation into the convoy war."]
    assert me["styles"] == ["Beginner", "Guided, standing orders for appointment"]
    assert [r["rationale"] for r in me["rulings"]] == [
        "Wheeler resents the White House; he would stall.",
        "Stark would read it as leave to escort convoys.",
    ]
    assert [r["on"] for r in me["rulings"]] == ["Burton K. Wheeler", "Harold R. Stark"]
    assert me["rulings"][0]["ask"] == "Press Burton K. Wheeler to go along"
    assert me["rulings"][1]["ask"] == "Have Harold R. Stark act on naval operations"
    assert me["covert"] == ["Have Harold R. Stark act on naval operations"]
    spoken = [*me["goals"], *me["covert"], *me["styles"]]
    spoken += [r[k] for r in me["rulings"] for k in ("on", "ask")]
    assert not any("_" in t or re.search(r"[0-9A-Z]{26}", t) for t in spoken)


def test_a_seat_with_nothing_gets_empty_lists(sl: Slice) -> None:
    out = reveal.build(sl.state, sl.events)
    assert {s["person"] for s in out["seats"]} == {"Franklin D. Roosevelt", "Burton K. Wheeler"}
    for seat in out["seats"]:
        assert (seat["goals"], seat["covert"], seat["styles"], seat["rulings"]) == ([], [], [], [])


def test_a_failed_estimate_and_another_seat_s_style_stay_out(sl: Slice) -> None:
    order = sl.shoot_on_sight(1, effect=None)
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(ev.EffectsEstimated(order_id=order.order_id, part=0, failed=True), private_to(sl.fdr))
    sl.add(ev.PlayStyleSet(seat_id=sl.wheeler, style=ra.PlayStyle.FREE), private_to(sl.wheeler))
    out = reveal.build(sl.state, sl.events)
    by = {s["person"]: s for s in out["seats"]}
    assert by["Franklin D. Roosevelt"]["rulings"] == []
    assert by["Franklin D. Roosevelt"]["styles"] == []
    assert by["Burton K. Wheeler"]["styles"] == ["Free play"]
