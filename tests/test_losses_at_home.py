"""The size of losses moves the mood at home (LSS).

With ``losses`` on, the steps a nation lost in a day's battle rounds are a happening of
their own kind, ``battle_losses``: each group that names it moves by its amount times the
steps, capped at ``LOSSES_DAY_CAP`` points a day. The kind is mixed unless the world
classes it: the reported share lands that day, the felt share in equal parts over the
``FELT_DAYS`` days after, held in state. When a battle ends, the losses its winner took in
it count half, as a correction that day. Losses at sea keep their own monthly kind.

The toy world (``tests/worlds/territory-toy.yaml``) has the Norra public and the Sudland
farmers moved by one point a step lost. A battle on the Sudland coast is folded day by day
here, with the losses rule run over each day as the day walk runs it.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.project import project
from revisionist.core.realism import groups
from revisionist.core.realism.battle import Battle, BattleSide, Ending
from revisionist.core.realism.groups import (
    FELT_DAYS,
    LOSSES_DAY_CAP,
    Cause,
    Class,
    Happening,
    HeldLoss,
)
from revisionist.core.state import State
from revisionist.core.visibility import Visibility
from revisionist.engine import catchup
from tests.test_adjacency_moves import Logged, entity, seat
from tests.test_battles import strengths
from tests.test_battles import toy as battles_toy
from tests.test_groups import day

World = dict[str, Any]
NORRA, SUDLAND = entity("norra"), entity("sudland")
COAST = entity("sudland_coast")
LOSS = (Cause.BATTLE_LOSSES, Cause.LOSSES_FELT, Cause.LOSSES_HALVED)


def ruled(*extra: str, on: bool = True) -> Callable[[World], None]:
    def change(w: World) -> None:
        base = ["territories", "holders", "economy", "battles", "groups"]
        w["rules"] = [*base, *(["losses"] if on else []), *extra]

    return change


def classed(*rows: dict[str, Any]) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["happenings"] = list(rows)

    return change


def weighs(nation: str, key: str, points: int | None) -> Callable[[World], None]:
    """``key`` of ``nation`` moved by ``points`` a step lost; None: by none."""

    def change(w: World) -> None:
        found = next(n for n in w["groups"] if n["nation"] == nation)
        g = next(g for g in found["groups"] if g["key"] == key)
        g["moved_by"].pop("battle_losses", None)
        if points is not None:
            g["moved_by"]["battle_losses"] = points

    return change


def game(tmp: Path, *changes: Callable[[World], None], on: bool = True) -> Logged:
    tmp.mkdir(parents=True, exist_ok=True)
    return Logged(battles_toy(tmp, ruled(on=on), *changes), "ilse", "tomas")


def _side(nation: EntityId, piece: str) -> BattleSide:
    return BattleSide(nation=nation, pieces=(FeatureId(entity(piece)),), brought=9)


def opened(n: int = 1, area: EntityId = COAST) -> ev.Payload:
    fought = Battle(
        area=area,
        opened=day(n),
        attacker=_side(NORRA, "norra_levy"),
        defender=_side(SUDLAND, "sudland_levy"),
    )
    return ev.BattleOpened(battle=fought, on=day(n))


def rnd(n: int, norra: int, sudland: int, area: EntityId = COAST) -> ev.Payload:
    return ev.BattleRound(area=area, on=day(n), scores=(0, 0), draws=(0, 0), lost=(norra, sudland))


def ended(n: int, winner: EntityId, area: EntityId = COAST) -> ev.Payload:
    how = Ending.WON if winner == NORRA else Ending.HELD
    return ev.BattleEnded(area=area, on=day(n), ending=how, winner=winner)


def played(g: Logged, plan: Mapping[int, Sequence[ev.Payload]], last: int) -> list[ev.GroupMoved]:
    """Each world day from 1 to ``last``: the day's battle events folded, then the losses
    rule run over them, as the day walk runs it. The group moves it made, in order."""
    out: list[ev.GroupMoved] = []
    for n in range(1, last + 1):
        start, happened = g.state, list(plan.get(n, ()))
        g.add(happened)
        made = groups.losses(g.state, start, happened, day(n))
        g.add(made)
        out += [m for m in made if isinstance(m, ev.GroupMoved)]
    return out


def total(moves: Sequence[ev.GroupMoved], polity: EntityId, key: str) -> int:
    return sum(m.change for m in moves if (m.polity, m.group) == (polity, key) and m.cause in LOSS)


def lost(tmp: Path, steps: int, *changes: Callable[[World], None]) -> list[ev.GroupMoved]:
    """Norra loses ``steps`` steps on the coast on day 1 and Sudland holds; the days up to
    the last felt part."""
    g = game(tmp, *changes)
    plan = {1: [opened(), rnd(1, steps, 0), ended(1, SUDLAND)]}
    return played(g, plan, 1 + FELT_DAYS)


# --- rule 1: a day's steps lost, scaled by size, capped by the day ------------------------


def test_a_three_step_loss_moves_a_group_three_times_a_one_step_loss(tmp_path: Path) -> None:
    one = total(lost(tmp_path / "one", 1), NORRA, "public")
    three = total(lost(tmp_path / "three", 3), NORRA, "public")
    assert (one, three) == (-1, -3)


def test_a_days_losses_move_a_group_no_more_than_the_cap(tmp_path: Path) -> None:
    assert LOSSES_DAY_CAP == 3
    assert total(lost(tmp_path / "five", 5), NORRA, "public") == -3
    g = game(tmp_path / "two", weighs("norra", "public", -2))
    plan = {1: [opened(), rnd(1, 2, 0)], 2: [rnd(2, 2, 0), ended(2, SUDLAND)]}
    moves = played(g, plan, 2 + FELT_DAYS)
    assert total(moves, NORRA, "public") == -6


def test_two_battles_on_one_day_share_the_cap(tmp_path: Path) -> None:
    other = entity("isle")
    g = game(tmp_path)
    plan = {
        1: [
            opened(),
            opened(area=other),
            rnd(1, 2, 0),
            rnd(1, 2, 0, area=other),
            ended(1, SUDLAND),
            ended(1, SUDLAND, area=other),
        ]
    }
    assert total(played(g, plan, 1 + FELT_DAYS), NORRA, "public") == -3


def test_each_side_moves_its_own_groups_by_its_own_steps(tmp_path: Path) -> None:
    g = game(tmp_path)
    plan = {1: [opened(), rnd(1, 1, 2), ended(1, SUDLAND)]}
    moves = played(g, plan, 1 + FELT_DAYS)
    assert total(moves, NORRA, "public") == -1
    assert total(moves, SUDLAND, "farmers") == -1  # Sudland held: its two count half
    assert {m.group for m in moves} == {"public", "farmers"}


def test_with_losses_off_no_loss_moves_a_group_and_nothing_is_held(tmp_path: Path) -> None:
    g = game(tmp_path, on=False)
    plan = {1: [opened(), rnd(1, 3, 3), ended(1, SUDLAND)]}
    assert played(g, plan, 3) == []
    assert g.state.groups.held == ()
    assert not [e for e in g.log if isinstance(e.payload, ev.LossesHeld)]


def test_a_secret_losses_kind_moves_nobody(tmp_path: Path) -> None:
    secret = classed({"kind": "battle_losses", "reach": "secret"})
    g = Logged(battles_toy(tmp_path, ruled("classes"), secret), "ilse", "tomas")
    plan = {1: [opened(), rnd(1, 3, 3), ended(1, SUDLAND)]}
    assert played(g, plan, 3) == []


# --- rule 3: mixed by default; the felt share over the days after ------------------------


def test_unclassed_losses_are_mixed_half_felt(tmp_path: Path) -> None:
    g = game(tmp_path)
    found = groups.cls(g.state, Happening.BATTLE_LOSSES)
    assert (found.reach, found.felt) == (Class.REPORTED, 0.5)
    moves = lost(tmp_path / "half", 3)
    first = [(m.cause, m.change) for m in moves if m.on == day(1) and m.group == "public"]
    assert first == [(Cause.BATTLE_LOSSES, -2)]
    later = [m.change for m in moves if m.cause is Cause.LOSSES_FELT and m.group == "public"]
    assert later == [-1]


def felt_most(tmp: Path) -> Logged:
    tmp.mkdir(parents=True, exist_ok=True)
    classes = classed({"kind": "battle_losses", "reach": "reported", "felt": 0.67})
    return Logged(battles_toy(tmp, ruled("classes"), classes), "ilse", "tomas")


def test_the_felt_share_arrives_in_equal_parts_over_three_weeks(tmp_path: Path) -> None:
    assert FELT_DAYS == 21
    g = felt_most(tmp_path)
    plan = {1: [opened(), rnd(1, 3, 0), ended(1, SUDLAND)]}
    moves = [m for m in played(g, plan, 30) if m.group == "public"]
    assert [(m.on, m.cause, m.change) for m in moves if m.on == day(1)] == [
        (day(1), Cause.BATTLE_LOSSES, -1)
    ]
    felt = [(m.on, m.change) for m in moves if m.cause is Cause.LOSSES_FELT]
    assert [c for _, c in felt] == [-1, -1]
    first, second = (on for on, _ in felt)
    assert day(2) < first < second <= day(1 + FELT_DAYS)
    assert (first - day(1)).days < 11 < (second - day(1)).days
    assert total(moves, NORRA, "public") == -3


def test_the_felt_share_is_held_in_state_until_it_has_landed(tmp_path: Path) -> None:
    g = felt_most(tmp_path)
    played(g, {1: [opened(), rnd(1, 3, 0), ended(1, SUDLAND)]}, 1)
    (held,) = [h for h in g.state.groups.held if h.group == "public"]
    assert (held.polity, held.on, held.reported, held.felt) == (NORRA, day(1), -1, -2)
    assert groups.landed(-2, 0) == 0 and groups.landed(-2, FELT_DAYS) == -2
    assert groups.landed(-2, FELT_DAYS + 5) == -2


def test_the_felt_share_arrives_with_nobody_online(tmp_path: Path) -> None:
    g = felt_most(tmp_path)
    played(g, {1: [opened(), rnd(1, 3, 0), ended(1, SUDLAND)]}, 1)
    out = g.walk(day(2), day(1 + FELT_DAYS))
    felt = [
        e.payload
        for e in out
        if isinstance(e.payload, ev.GroupMoved) and e.payload.cause is Cause.LOSSES_FELT
    ]
    assert [(m.group, m.change) for m in felt] == [("public", -1), ("public", -1)]
    assert not [e for e in out if e.kind.startswith("order_")]


def test_a_restart_between_the_loss_and_its_felt_days_gives_one_outcome(tmp_path: Path) -> None:
    def walked(tmp: Path, stops: Sequence[int]) -> list[tuple[date, int]]:
        g = felt_most(tmp)
        played(g, {1: [opened(), rnd(1, 3, 0), ended(1, SUDLAND)]}, 1)
        out: list[ev.Event] = []
        first = 2
        for last in stops:
            out += g.walk(day(first), day(last))
            first = last + 1
        return [
            (e.payload.on, e.payload.change)
            for e in out
            if isinstance(e.payload, ev.GroupMoved) and e.payload.cause is Cause.LOSSES_FELT
        ]

    assert walked(tmp_path / "one", [25]) == walked(tmp_path / "three", [5, 11, 25])


# --- rule 2: the losses of a battle won count half ----------------------------------------


def _won_or_lost(tmp: Path, winner: EntityId) -> list[ev.GroupMoved]:
    g = game(tmp)
    plan = {1: [opened(), rnd(1, 2, 0)], 2: [rnd(2, 2, 0)], 3: [ended(3, winner)]}
    return played(g, plan, 3 + FELT_DAYS)


def test_the_losses_of_a_battle_won_count_half_from_the_day_it_ends(tmp_path: Path) -> None:
    won = _won_or_lost(tmp_path / "won", NORRA)
    lost_it = _won_or_lost(tmp_path / "lost", SUDLAND)
    assert total(lost_it, NORRA, "public") == -4
    assert total(won, NORRA, "public") == -2
    back = [(m.on, m.change) for m in won if m.cause is Cause.LOSSES_HALVED]
    assert back == [(day(3), 2)]
    before = [m for m in won if m.on < day(3)]
    assert before == [m for m in lost_it if m.on < day(3)]


def test_a_won_battles_correction_reaches_its_felt_share_still_held(tmp_path: Path) -> None:
    g = felt_most(tmp_path)
    plan = {1: [opened(), rnd(1, 3, 0)], 2: [ended(2, NORRA)]}
    moves = [m for m in played(g, plan, 2 + FELT_DAYS) if m.group == "public"]
    assert total(moves, NORRA, "public") == -2
    assert [m.change for m in moves if m.cause is Cause.LOSSES_FELT] == [-1]
    assert all(h.ended for h in g.state.groups.held if h.group == "public")


def test_a_battle_lost_gets_no_correction(tmp_path: Path) -> None:
    moves = _won_or_lost(tmp_path, SUDLAND)
    assert not [m for m in moves if m.cause is Cause.LOSSES_HALVED]


# --- rule 4: losses at sea keep their monthly kind ---------------------------------------


def test_losses_at_sea_keep_their_own_monthly_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revisionist.core.realism.resolvers import shipping

    def sunk(state: State, last: date) -> dict[FeatureId, int]:
        return {FeatureId(entity("norra_levy")): 900}

    monkeypatch.setattr(shipping, "losses", sunk)

    def at_sea(tmp: Path, on: bool) -> list[tuple[Any, ...]]:
        g = game(tmp, on=on)
        out = g.walk(date(1900, 4, 29), date(1900, 5, 2))
        return [
            (e.payload.on, e.payload.group, e.payload.change, e.payload.cause)
            for e in out
            if isinstance(e.payload, ev.GroupMoved)
        ]

    with_losses = at_sea(tmp_path / "on", True)
    assert (date(1900, 5, 1), "public", -2, Cause.LOSSES_AT_SEA) in with_losses
    assert with_losses == at_sea(tmp_path / "off", False)


# --- the day walk, fog and the stored shape ----------------------------------------------


def test_the_day_walk_moves_groups_by_the_steps_its_battles_cost(tmp_path: Path) -> None:
    def change(w: World) -> None:
        ruled()(w)
        strengths()(w)

    g = Logged(battles_toy(tmp_path, change), "ilse", "tomas")
    g.send("ilse", "norra_levy", "sudby")
    out = g.walk(day(1), day(40))
    rounds = [e.payload for e in out if isinstance(e.payload, ev.BattleRound)]
    assert rounds and any(r.lost[0] for r in rounds)
    moved = [
        e.payload
        for e in out
        if isinstance(e.payload, ev.GroupMoved) and e.payload.cause is Cause.BATTLE_LOSSES
    ]
    first = next(r for r in rounds if r.lost[0])
    (on_day,) = [m for m in moved if m.on == first.on and m.polity == NORRA]
    assert on_day.change == -(
        min(first.lost[0], LOSSES_DAY_CAP) - int(min(first.lost[0], LOSSES_DAY_CAP) * 0.5)
    )
    held = [e for e in out if isinstance(e.payload, ev.LossesHeld)]
    assert held
    for e in held:
        assert e.scope.visibility is Visibility.RESTRICTED
        assert not e.scope.known_by & set(g.state.seats)


def _abroad(tmp: Path, weighed: bool) -> tuple[str, list[Any]]:
    g = game(tmp, weighs("norra", "public", -1 if weighed else None))
    played(g, {1: [opened(), rnd(1, 3, 1), ended(1, SUDLAND)]}, 1)
    g.walk(day(2), day(1 + FELT_DAYS))
    tomas = seat("tomas")
    view = project(g.state, tomas).model_dump_json()
    fed = [
        f.event.payload.model_dump(mode="json") for f in catchup.feed(g.state, g.log, tomas, 0, 99)
    ]
    return view, fed


def test_the_other_side_sees_nothing_of_its_enemys_groups_moving(tmp_path: Path) -> None:
    assert _abroad(tmp_path / "with", True) == _abroad(tmp_path / "without", False)


def test_a_nations_own_seat_sees_its_groups_moved_and_nothing_held(tmp_path: Path) -> None:
    g = game(tmp_path)
    played(g, {1: [opened(), rnd(1, 3, 0), ended(1, SUDLAND)]}, 1)
    mine = project(g.state, seat("ilse"))
    assert mine.groups.support[NORRA]["public"] == 40 - 2
    assert mine.groups.held == ()
    assert g.state.groups.held


def test_held_losses_need_the_losses_rule_and_a_group_of_the_nation(tmp_path: Path) -> None:
    held = HeldLoss(
        polity=NORRA, group="public", area=COAST, opened=day(1), on=day(1), reported=-1, felt=-1
    )
    off = game(tmp_path / "off", on=False)
    with pytest.raises(FoldError, match="losses rule"):
        off.add([ev.LossesHeld(on=day(1), held=(held,))])
    g = game(tmp_path / "on")
    with pytest.raises(FoldError, match="no group"):
        g.add([ev.LossesHeld(on=day(1), held=(held.model_copy(update={"group": "nobody"}),))])
    g.add([ev.LossesHeld(on=day(1), held=(held,))])
    g.add([ev.LossesHeld(on=day(2), held=(held.model_copy(update={"felt": -2}),))])
    assert [h.felt for h in g.state.groups.held] == [-2]


def test_held_losses_are_dropped_once_their_battle_ended_and_their_felt_share_landed(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    first = HeldLoss(
        polity=NORRA, group="public", area=COAST, opened=day(1), on=day(1), reported=-1, felt=-1
    )
    open_still = first.model_copy(update={"group": "greens"})
    g.add([ev.LossesHeld(on=day(2), held=(first.model_copy(update={"ended": True}), open_still))])
    later = first.model_copy(update={"on": day(FELT_DAYS), "opened": day(FELT_DAYS)})
    g.add([ev.LossesHeld(on=day(FELT_DAYS), held=(later,))])
    assert len(g.state.groups.held) == 3
    g.add([ev.LossesHeld(on=day(1 + FELT_DAYS), held=(later,))])
    assert [(h.group, h.on) for h in g.state.groups.held] == [
        ("greens", day(1)),
        ("public", day(FELT_DAYS)),
    ]
