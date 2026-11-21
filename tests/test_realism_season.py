"""The season ends on the last deciding day (SEA).

The toy world (``tests/worlds/territory-toy.yaml``) is played with the ``contests`` and
``aims`` rules on. The tick that reaches the latest deciding day among the world's
contests ends the season. With aims on, the winners are the human seats with two of their
three aims holding (every aim when the card has fewer than two), any number of them or
none; a code seat never wins. A game without aims keeps the rule it had: any seat with a
holding goal.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.goals import Goal, GoalKind, HoldsArea, season_winners
from revisionist.core.ids import ClockId, GoalId
from revisionist.core.ontology import Controller, Phase
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from tests.test_realism_aims import (
    HILLS_HELD,
    ILSE,
    ISLE_HELD,
    TOMAS,
    Game,
    aims,
    border,
    own_goals,
    rule,
    seat_of,
    world,
)

World = dict[str, Any]
THIRD: World = {"check": "holds_area", "area": "norra_plain", "holder": "norra"}
SUDLAND_HILLS: World = {**HILLS_HELD, "holder": "sudland"}


def later(countdown: int) -> Callable[[World], None]:
    """A second contest, between the same sides, deciding ``countdown`` days in."""

    def change(w: World) -> None:
        w["contests"].append({**w["contests"][0], "key": "second", "countdown_days": countdown})

    return change


def counting(days: int) -> Callable[[World], None]:
    """The border contest deciding ``days`` days in."""

    def change(w: World) -> None:
        w["contests"][0]["countdown_days"] = days

    return change


def three(*conditions: World) -> Callable[[World], None]:
    """Ilse's card with three aims ruled by ``conditions``."""

    def change(w: World) -> None:
        aims(ilse=tuple(rule(i, c) for i, c in enumerate(conditions, start=1)))(w)
        w["cards"][0]["aims"] = ["One.", "Two.", "Three."]

    return change


def played_to_the_end(g: Game, limit: int = 60) -> int:
    for n in range(limit):
        if g.state.phase is not Phase.PLAY:
            return n
        g.tick()
    raise AssertionError("the season never ended")


def winners(g: Game) -> frozenset[Any]:
    played_to_the_end(g)
    ended = [
        e.payload
        for e in g.store.read(g.state.campaign_id)
        if isinstance(e.payload, ev.SeasonEnded)
    ]
    assert len(ended) == 1
    return frozenset(ended[0].winners)


def test_the_tick_that_reaches_the_deciding_day_ends_the_season(tmp_path: Path) -> None:
    g = Game(world(tmp_path, border, aims(), counting(100)))
    (contest,) = g.state.contests.values()
    assert contest.decides is not None
    for _ in range(30):
        before = g.state.in_world_date
        if g.state.phase is not Phase.PLAY:
            break
        assert before is not None and before < contest.decides
        g.tick()
    after = g.state.in_world_date
    assert after is not None and after >= contest.decides
    assert g.state.phase is Phase.SEASON_OVER


def test_the_season_waits_for_the_latest_of_the_contests(tmp_path: Path) -> None:
    g = Game(world(tmp_path, border, aims(), counting(100), later(300)))
    first, second = sorted(g.state.contests.values(), key=lambda k: k.decides or k.countdown_days)
    assert first.decides is not None and second.decides is not None
    ended_on = None
    for _ in range(40):
        if g.state.phase is not Phase.PLAY:
            break
        g.tick()
        ended_on = g.state.in_world_date
    assert g.state.phase is Phase.SEASON_OVER
    assert ended_on is not None and ended_on >= second.decides
    assert all(k.decided for k in g.state.contests.values())


def test_a_game_without_contests_never_ends_on_its_own(tmp_path: Path) -> None:
    def no_contests(w: World) -> None:
        w["rules"] = [r for r in w["rules"] if r != "contests"]

    g = Game(world(tmp_path, border, aims(), no_contests))
    for _ in range(20):
        g.tick()
    assert g.state.phase is Phase.PLAY


def holding(state: State, *goals: Any) -> State:
    """``state`` with exactly ``goals`` holding."""
    made = {k: v.model_copy(update={"holding": k in goals}) for k, v in state.goals.items()}
    return state.model_copy(update={"goals": made})


def aim_lines(state: State, person: Any, *lines: str) -> State:
    card = state.cards[person].model_copy(update={"aims": lines})
    return state.model_copy(update={"cards": {**state.cards, person: card}})


def test_two_of_three_aims_win_and_one_of_three_does_not(tmp_path: Path) -> None:
    g = Game(world(tmp_path, border, three(HILLS_HELD, ISLE_HELD, SUDLAND_HILLS)))
    g.tick()
    state = g.state
    a, b, c = (x.goal_id for x in own_goals(state, ILSE))
    seat = seat_of(state, ILSE)
    assert season_winners(holding(state, a, b)) == {seat}
    assert season_winners(holding(state, a, c)) == {seat}
    assert season_winners(holding(state, c)) == frozenset()
    assert season_winners(holding(state)) == frozenset()


def test_a_card_with_fewer_than_three_aims_needs_two_or_all(tmp_path: Path) -> None:
    g = Game(world(tmp_path, border, aims(ilse=(rule(1, HILLS_HELD), rule(2, ISLE_HELD)))))
    g.tick()
    state = aim_lines(g.state, ILSE, "One.", "Two.")
    a, b = (x.goal_id for x in own_goals(state, ILSE))
    seat = seat_of(state, ILSE)
    assert season_winners(holding(state, a)) == frozenset()
    assert season_winners(holding(state, a, b)) == {seat}
    lone = aim_lines(state, ILSE, "One.")
    lone = lone.model_copy(update={"goals": {a: lone.goals[a]}})
    assert season_winners(holding(lone, a)) == {seat}
    assert season_winners(holding(lone)) == frozenset()


def test_a_code_seat_never_wins(tmp_path: Path) -> None:
    g = Game(world(tmp_path, border, aims(ilse=(rule(1, HILLS_HELD), rule(2, ISLE_HELD)))))
    g.tick()
    mine = [x.goal_id for x in own_goals(g.state, ILSE)]
    assert season_winners(holding(g.state, *mine)) == {seat_of(g.state, ILSE)}
    g.hand(ILSE, Controller.AI)
    state = holding(g.state, *mine)
    assert all(x.holding for x in own_goals(state, ILSE))
    assert season_winners(state) == frozenset()


def test_any_number_of_seats_can_win(tmp_path: Path) -> None:
    both = aims(
        ilse=(rule(1, HILLS_HELD), rule(2, ISLE_HELD)),
        tomas=(rule(1, HILLS_HELD), rule(2, ISLE_HELD)),
    )

    def tomas_has_two(w: World) -> None:
        w["cards"][1]["aims"] = ["One.", "Two."]

    g = Game(world(tmp_path, border, both, tomas_has_two))
    g.hand(TOMAS, Controller.HUMAN)
    g.tick()
    state = g.state
    every = [x.goal_id for x in state.goals.values() if x.person in (ILSE, TOMAS)]
    assert len(every) == 4
    assert season_winners(holding(state, *every)) == {seat_of(state, ILSE), seat_of(state, TOMAS)}
    assert season_winners(holding(state, every[0])) == frozenset()
    assert season_winners(holding(state)) == frozenset()


def test_a_game_without_aims_keeps_the_old_rule(tmp_path: Path) -> None:
    g = Game(world(tmp_path, border, aims(on=False)))
    state = g.state
    seat = seat_of(state, ILSE)
    place = next(iter(state.entities))
    legacy = Goal(
        goal_id=GoalId("legacy"),
        seat_id=seat,
        text="Win.",
        condition=HoldsArea(area=place, holder=place),
        kind=GoalKind.UNDOABLE,
        clock_id=ClockId("clock"),
        scope=PUBLIC,
        holding=True,
    )
    state = state.model_copy(update={"goals": {legacy.goal_id: legacy}})
    assert season_winners(state) == {seat}
    g.hand(ILSE, Controller.AI)
    assert season_winners(g.state.model_copy(update={"goals": state.goals})) == {seat}
