"""Places with political weight: lost, abandoned or retaken (PLW).

The toy world (``tests/worlds/territory-toy.yaml``) weighs the Norra Plain for Norra,
moving the Greys by -4 and the Norra Public by -2 when it is lost. Read only with
``places`` on; every test here switches it on with ``holders`` and ``groups`` unless it
says otherwise. Lost after a battle fought there moves the groups by the listed amounts,
abandoned (a change of holder where no battle has opened) by twice them, three times when
a piece of the holder's stood there within the last week and left; retaken undoes a loss.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism import groups
from revisionist.core.realism.groups import Cause, Happening
from revisionist.core.realism.holders import Capture
from revisionist.core.realism.territory import StepCause
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from tests.test_adjacency_moves import START, Logged, entity, fold, toy
from tests.test_battles import rules, strengths
from tests.test_battles import toy as battles_toy
from tests.test_territory_model import refused

World = dict[str, Any]
NORRA, SUDLAND = entity("norra"), entity("sudland")
PLAIN, HILLS = entity("norra_plain"), entity("norra_hills")


def ruled(*names: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = ["territories", *names]

    return change


def world(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    return toy(tmp, ruled("holders", "economy", "groups", "places"), *changes)


def game(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    return Logged(world(tmp, *changes), "ilse", "tomas")


def day(n: int) -> date:
    return START + timedelta(days=n)


def moves(found: Sequence[ev.Payload]) -> list[tuple[str, int, Cause]]:
    return [(m.group, m.change, m.cause) for m in found if isinstance(m, ev.GroupMoved)]


def held(area: EntityId, holder: EntityId, was: EntityId, n: int) -> ev.AreaHeld:
    return ev.AreaHeld(area=area, holder=holder, was=was, on=day(n))


def fought_at(state: State, *areas: EntityId) -> State:
    return state.model_copy(update={"fought": state.fought | set(areas)})


def left(area: EntityId, nation: EntityId, n: int) -> ev.PieceStepped:
    return ev.PieceStepped(
        mark="levy-1", nation=nation, left=area, entered=HILLS, on=day(n), cause=StepCause.ORDERED
    )


# --- the three happenings ----------------------------------------------------------


def test_a_place_lost_after_a_battle_fought_there_moves_its_groups_by_the_amounts(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    start = fought_at(g.state, PLAIN)
    found = groups.places(start, start, [held(PLAIN, SUDLAND, NORRA, 4)], day(4))
    assert moves(found) == [("greys", -4, Cause.PLACE_LOST), ("public", -2, Cause.PLACE_LOST)]


def test_a_place_abandoned_with_no_battle_costs_twice_a_loss(tmp_path: Path) -> None:
    g = game(tmp_path)
    found = groups.places(g.state, g.state, [held(PLAIN, SUDLAND, NORRA, 4)], day(4))
    assert moves(found) == [
        ("greys", -8, Cause.PLACE_ABANDONED),
        ("public", -4, Cause.PLACE_ABANDONED),
    ]


def test_a_place_abandoned_a_week_after_the_holders_piece_left_costs_three_times(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    after = fold(g.state, [left(PLAIN, NORRA, 1)])
    found = groups.places(after, after, [held(PLAIN, SUDLAND, NORRA, 8)], day(8))
    assert moves(found) == [
        ("greys", -12, Cause.PLACE_ABANDONED),
        ("public", -6, Cause.PLACE_ABANDONED),
    ]
    late = groups.places(after, after, [held(PLAIN, SUDLAND, NORRA, 9)], day(9))
    assert moves(late) == [
        ("greys", -8, Cause.PLACE_ABANDONED),
        ("public", -4, Cause.PLACE_ABANDONED),
    ]


def test_a_piece_of_another_nation_leaving_does_not_raise_the_cost(tmp_path: Path) -> None:
    g = game(tmp_path)
    after = fold(g.state, [left(PLAIN, SUDLAND, 1)])
    found = groups.places(after, after, [held(PLAIN, SUDLAND, NORRA, 3)], day(3))
    assert moves(found) == [
        ("greys", -8, Cause.PLACE_ABANDONED),
        ("public", -4, Cause.PLACE_ABANDONED),
    ]


def test_a_battle_opened_there_the_same_day_before_the_change_makes_it_a_loss(
    tmp_path: Path,
) -> None:
    from revisionist.core.realism.battle import Battle, BattleSide

    g = game(tmp_path)
    battle = Battle(
        area=PLAIN,
        opened=day(4),
        attacker=BattleSide(nation=SUDLAND, pieces=(FeatureId("a"),), brought=1),
        defender=BattleSide(nation=NORRA, pieces=(FeatureId("d"),), brought=1),
    )
    opened = ev.BattleOpened(battle=battle, on=day(4))
    found = groups.places(g.state, g.state, [opened, held(PLAIN, SUDLAND, NORRA, 4)], day(4))
    assert moves(found) == [("greys", -4, Cause.PLACE_LOST), ("public", -2, Cause.PLACE_LOST)]


def test_a_place_retaken_moves_its_groups_back_by_the_amounts(tmp_path: Path) -> None:
    g = game(tmp_path)
    found = groups.places(g.state, g.state, [held(PLAIN, NORRA, SUDLAND, 9)], day(9))
    assert moves(found) == [("greys", 4, Cause.PLACE_RETAKEN), ("public", 2, Cause.PLACE_RETAKEN)]


def test_a_territory_not_on_the_list_moves_no_group(tmp_path: Path) -> None:
    g = game(tmp_path)
    taken = [held(HILLS, SUDLAND, NORRA, 4), held(HILLS, NORRA, SUDLAND, 6)]
    assert groups.places(g.state, g.state, taken, day(6)) == []


def test_a_place_changing_hands_between_others_moves_nobody(tmp_path: Path) -> None:
    def theirs(w: World) -> None:
        w["entities"].append({"key": "osten", "kind": "polity", "name": "Osten"})
        w["places"] = [{"territory": "isle", "nation": "norra", "moves": {"greys": -4}}]

    g = game(tmp_path, theirs)
    isle, osten = entity("isle"), entity("osten")
    assert groups.places(g.state, g.state, [held(isle, osten, SUDLAND, 4)], day(4)) == []


def test_places_off_the_list_is_read_and_nothing_moves(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path, ruled("holders", "economy", "groups")), "ilse", "tomas")
    assert g.state.groups.places == ()
    assert groups.places(g.state, g.state, [held(PLAIN, SUDLAND, NORRA, 4)], day(4)) == []
    after = fold(g.state, [left(PLAIN, NORRA, 1)])
    assert after.groups.left == {}


def test_each_happening_is_reported_by_default(tmp_path: Path) -> None:
    g = game(tmp_path)
    for kind in (Happening.PLACE_LOST, Happening.PLACE_ABANDONED, Happening.PLACE_RETAKEN):
        assert groups.cls(g.state, kind).reach is groups.Class.REPORTED


def test_a_place_kind_the_world_makes_secret_moves_no_group(tmp_path: Path) -> None:
    def secret(w: World) -> None:
        w["rules"] = [*w["rules"], "classes"]
        w["happenings"] = [*w["happenings"], {"kind": "place_abandoned", "reach": "secret"}]

    g = game(tmp_path, secret)
    assert groups.places(g.state, g.state, [held(PLAIN, SUDLAND, NORRA, 4)], day(4)) == []


# --- the seat of government ----------------------------------------------------------


def test_a_seat_that_is_also_weighted_raises_both_happenings_once_each(tmp_path: Path) -> None:
    def capital(w: World) -> None:
        for e in w["entities"]:
            if e["key"] == "norra":
                e["capital"] = "norrhavn"

    g = game(tmp_path, capital)
    start = fought_at(g.state, PLAIN)
    mark = Capture(by=SUDLAND, since=day(1), marked=1, marked_on=day(3))
    day_of: list[ev.Payload] = [
        ev.CaptureCounted(area=PLAIN, capture=mark),
        held(PLAIN, SUDLAND, NORRA, 3),
    ]
    found = [
        *groups.react(start, start, day_of, day(3)),
        *groups.places(start, start, day_of, day(3)),
    ]
    causes = [m.cause for m in found if m.group in ("greens", "greys")]
    assert causes == [Cause.CAPITAL_THREATENED, Cause.PLACE_LOST]


# --- the world file -----------------------------------------------------------------


def test_the_world_must_name_a_known_territory_nation_and_its_own_groups(tmp_path: Path) -> None:
    def bad(w: World) -> None:
        w["places"] = [
            {"territory": "nowhere", "nation": "norra", "moves": {"greys": -1}},
            {"territory": "isle", "nation": "sudland", "moves": {"greys": -1}},
            {"territory": "isle", "nation": "ilse", "moves": {"greys": -1}},
            {"territory": "norra_plain", "nation": "norra", "moves": {"public": -1}},
            {"territory": "norra_plain", "nation": "norra", "moves": {"greys": -1}},
        ]

    problems = refused(world(tmp_path, bad))
    assert "places nowhere: not a territory" in problems
    assert "places isle: greys is not a group of sudland" in problems
    assert "places isle: ilse is not a polity" in problems
    assert "places norra_plain: weighted twice for norra" in problems


def test_places_needs_groups_and_holders(tmp_path: Path) -> None:
    problems = refused(toy(tmp_path, ruled("places")))
    assert "rules: places needs groups" in problems
    assert "rules: places needs holders" in problems


def test_a_place_kind_is_not_named_in_moved_by(tmp_path: Path) -> None:
    def named(w: World) -> None:
        w["groups"][0]["groups"][0]["moved_by"]["place_lost"] = -1

    problems = refused(world(tmp_path, named))
    assert "groups norra smiths: place_lost is moved by places, not moved_by" in problems


# --- the day walk -------------------------------------------------------------------


def test_a_place_taken_without_a_fight_in_the_day_walk_is_abandoned(tmp_path: Path) -> None:
    def hills(w: World) -> None:
        w["places"] = [{"territory": "norra_hills", "nation": "norra", "moves": {"greys": -3}}]

    g = Logged(
        battles_toy(
            tmp_path,
            rules("territories", "holders", "battles", "groups", "places"),
            strengths(norra_levy=1, sudland_levy=1),
            hills,
        ),
        "ilse",
        "tomas",
    )
    g.send("tomas", "sudland_levy", "norra_hills")
    out = g.walk(day(1), day(30))
    taken = [e.payload for e in out if isinstance(e.payload, ev.AreaHeld)]
    assert [(p.area, p.holder) for p in taken] == [(HILLS, SUDLAND)]
    placed = [m for m in moves([e.payload for e in out]) if m[2] is not Cause.DRIFT]
    assert [m for m in placed if m[0] == "greys"] == [("greys", -6, Cause.PLACE_ABANDONED)]
