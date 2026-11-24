"""Every happening has a class: felt, reported or secret (HCL).

With ``classes`` on, a world may give each kind of happening a class, and for a mixed kind
the share of it that is felt. The classes reach state with the groups' declaration and are
read in one place, ``groups.cls``. A kind the world does not class is reported, which is
how every happening reaches the groups with the rule off. A secret happening moves no
group. A measure passed splits in two: a law the world marks as touching daily life raises
the felt kind, any other law the reported kind, and a group may weigh them differently.

The toy world (``tests/worlds/territory-toy.yaml``) classes a few kinds; the tests here
change its table where they need another.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism import groups
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.battle import Battle, BattleSide, Ending
from revisionist.core.realism.groups import Cause, Class, Happening
from revisionist.core.realism.resolvers import votes
from revisionist.core.state import Rule
from tests.test_adjacency_moves import Logged, entity, seat, toy
from tests.test_groups import day
from tests.test_territory_model import refused
from tests.test_votes_from_groups import at, hundred, order, published

World = dict[str, Any]
NORRA, SUDLAND = entity("norra"), entity("sudland")


def ruled(*extra: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy", "groups", *extra]

    return change


def classed(*rows: dict[str, Any]) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["happenings"] = list(rows)

    return change


def game(tmp: Path, *changes: Callable[[World], None], on: bool = True) -> Logged:
    tmp.mkdir(parents=True, exist_ok=True)
    rules = ruled("classes") if on else ruled()
    return Logged(toy(tmp, rules, *changes), "ilse", "tomas")


def _side(nation: EntityId, piece: str) -> BattleSide:
    return BattleSide(nation=nation, pieces=(FeatureId(entity(piece)),), brought=3)


def _battle_won_by_norra() -> list[ev.Payload]:
    fought = Battle(
        area=entity("sudland_coast"),
        opened=day(1),
        attacker=_side(NORRA, "norra_levy"),
        defender=_side(SUDLAND, "sudland_levy"),
    )
    return [
        ev.BattleOpened(battle=fought, on=day(1)),
        ev.BattleEnded(area=entity("sudland_coast"), on=day(1), ending=Ending.WON, winner=NORRA),
    ]


def moves(out: list[ev.GroupMoved]) -> list[tuple[Any, str, int, Cause]]:
    return sorted((m.polity, m.group, m.change, m.cause) for m in out)


# --- rule 1: the world classes each kind; the classes ride the groups' declaration -----


def test_the_world_classes_reach_state_with_the_groups_declaration(tmp_path: Path) -> None:
    g = game(tmp_path)
    (found,) = [e.payload for e in g.log if isinstance(e.payload, ev.GroupsDeclared)]
    assert {c.kind: c.reach for c in found.classes} == {
        Happening.CAPITAL_THREATENED: Class.FELT,
        Happening.BATTLE_LOST: Class.REPORTED,
        Happening.AGREEMENT_BROKEN: Class.SECRET,
    }
    assert groups.cls(g.state, Happening.CAPITAL_THREATENED).reach is Class.FELT
    assert groups.cls(g.state, Happening.CAPITAL_THREATENED).felt == 1
    mixed = groups.cls(g.state, Happening.BATTLE_LOST)
    assert (mixed.reach, mixed.felt, mixed.mixed) == (Class.REPORTED, 0.4, True)
    assert groups.cls(g.state, Happening.AGREEMENT_BROKEN).reach is Class.SECRET


def test_a_kind_the_world_does_not_class_is_reported(tmp_path: Path) -> None:
    g = game(tmp_path)
    found = groups.cls(g.state, Happening.BATTLE_WON)
    assert (found.reach, found.felt, found.mixed) == (Class.REPORTED, 0, False)
    out = groups.react(g.state, g.state, _battle_won_by_norra(), day(1))
    assert (NORRA, "greens", 3, Cause.BATTLE_WON) in moves(out)


def test_the_class_is_read_from_the_world_never_from_the_kinds_name(tmp_path: Path) -> None:
    g = game(
        tmp_path,
        classed(
            {"kind": "daily_life_passed", "reach": "secret"},
            {"kind": "measure_passed", "reach": "felt"},
            {"kind": "losses_at_sea", "reach": "reported", "felt": 0.25},
        ),
    )
    assert groups.cls(g.state, Happening.DAILY_LIFE_PASSED).reach is Class.SECRET
    assert groups.cls(g.state, Happening.MEASURE_PASSED).reach is Class.FELT
    assert groups.cls(g.state, Happening.LOSSES_AT_SEA).felt == 0.25
    assert groups.cls(g.state, Happening.CAPITAL_THREATENED).reach is Class.REPORTED


def test_with_classes_off_every_kind_is_reported_and_the_classes_stay_out(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, on=False)
    (found,) = [e.payload for e in g.log if isinstance(e.payload, ev.GroupsDeclared)]
    assert found.classes == ()
    assert g.state.groups.classes == {}
    assert groups.cls(g.state, Happening.AGREEMENT_BROKEN).reach is Class.REPORTED


def test_with_classes_off_the_class_is_not_read_from_a_state_that_holds_one(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    off = g.state.model_copy(update={"rules": g.state.rules - {Rule.CLASSES}})
    assert off.groups.classes[Happening.AGREEMENT_BROKEN].reach is Class.SECRET
    assert groups.cls(off, Happening.AGREEMENT_BROKEN).reach is Class.REPORTED


def test_a_seat_reads_the_classes_from_its_own_nations_groups(tmp_path: Path) -> None:
    g = game(tmp_path)
    seen = groups.seen_by(g.state, seat("ilse"))
    assert seen.classes == g.state.groups.classes
    assert seen.classes[Happening.AGREEMENT_BROKEN].reach is Class.SECRET


def test_the_compiler_refuses_a_kind_classed_twice_or_a_share_on_a_secret_kind(
    tmp_path: Path,
) -> None:
    twice = classed(
        {"kind": "battle_won", "reach": "felt"}, {"kind": "battle_won", "reach": "secret"}
    )
    assert any(
        "battle_won is classed twice" in p for p in refused(toy(tmp_path, ruled("classes"), twice))
    )
    for bad in (
        {"kind": "battle_won", "reach": "secret", "felt": 0.5},
        {"kind": "battle_won", "reach": "felt", "felt": 0.5},
        {"kind": "battle_won", "reach": "reported", "felt": 1},
        {"kind": "battle_won", "reach": "whispered"},
        {"kind": "rumour", "reach": "felt"},
    ):
        with pytest.raises(ValidationError):
            toy(tmp_path, ruled("classes"), classed(bad))


def test_a_classed_kind_survives_the_round_trip_a_stored_game_makes() -> None:
    for raw in (
        {"kind": "agreement_broken", "reach": "secret"},
        {"kind": "battle_lost", "reach": "reported", "felt": 0.4},
        {"kind": "capital_threatened", "reach": "felt"},
    ):
        c = groups.KindClass.model_validate(raw)
        assert groups.KindClass.model_validate(c.model_dump(mode="json")) == c


# --- rule 2: a secret happening moves no group ------------------------------------------


def test_a_secret_kind_moves_nobody(tmp_path: Path) -> None:
    g = game(tmp_path, classed({"kind": "battle_won", "reach": "secret"}))
    out = groups.react(g.state, g.state, _battle_won_by_norra(), day(1))
    assert moves(out) == [(SUDLAND, "farmers", -3, Cause.BATTLE_LOST)]


def test_a_secret_kind_another_rule_decides_moves_nobody(tmp_path: Path) -> None:
    g = game(tmp_path, classed({"kind": "battle_lost", "reach": "secret"}))
    assert groups.happened(g.state, NORRA, Happening.BATTLE_LOST, day(1)) == []
    assert [m.group for m in groups.happened(g.state, NORRA, Happening.BATTLE_WON, day(1))] == [
        "smiths",
        "greens",
    ]


def test_with_classes_off_a_secret_kind_moves_groups_as_today(tmp_path: Path) -> None:
    g = game(tmp_path, classed({"kind": "battle_won", "reach": "secret"}), on=False)
    out = groups.react(g.state, g.state, _battle_won_by_norra(), day(1))
    assert moves(out) == [
        (NORRA, "greens", 3, Cause.BATTLE_WON),
        (NORRA, "smiths", 2, Cause.BATTLE_WON),
        (SUDLAND, "farmers", -3, Cause.BATTLE_LOST),
    ]


# --- rule 3: a measure passed splits in two ---------------------------------------------


def _bloc(w: World, key: str) -> dict[str, Any]:
    nation = next(n for n in w["groups"] if n["nation"] == "norra")
    return next(g for g in nation["groups"] if g["key"] == key)


def levy_law(daily: bool) -> Callable[[World], None]:
    """The levy act as a declared law of Norra, touching daily life or not; the greens weigh
    a measure passed and the public a law felt at home."""

    def change(w: World) -> None:
        hundred(w)
        published(w)
        w["rules"] = [*w["rules"], "laws"]
        w["laws"].append(
            {
                "key": "levy_act",
                "title": "The Levy Act",
                "nation": "norra",
                "clauses": [{"kind": "power", "subject": "raise levies"}],
                "passed": "levy_act_passed",
                "daily_life": daily,
            }
        )
        _bloc(w, "greens")["moved_by"]["measure_passed"] = 2
        _bloc(w, "public")["moved_by"]["daily_life_passed"] = 3

    return change


def passed(g: Logged) -> list[ev.GroupMoved]:
    at(g, "greys", 30 + 11 * votes.VOTE_POINTS)
    return [c for c in rs.ON_ORDER["votes"](g.state, order()) if isinstance(c, ev.GroupMoved)]


def test_a_daily_life_law_and_another_law_move_different_groups(tmp_path: Path) -> None:
    felt = passed(game(tmp_path / "felt", levy_law(daily=True)))
    assert [(m.group, m.change, m.cause) for m in felt] == [("public", 3, Cause.DAILY_LIFE_PASSED)]
    reported = passed(game(tmp_path / "reported", levy_law(daily=False)))
    assert [(m.group, m.change, m.cause) for m in reported] == [("greens", 2, Cause.MEASURE_PASSED)]


def test_a_law_of_another_nation_with_the_measures_key_is_not_read(tmp_path: Path) -> None:
    def abroad(w: World) -> None:
        levy_law(daily=True)(w)
        w["laws"][-1]["nation"] = "sudland"

    out = passed(game(tmp_path, abroad))
    assert [(m.group, m.cause) for m in out] == [("greens", Cause.MEASURE_PASSED)]


def test_with_classes_off_a_daily_life_law_moves_groups_as_today(tmp_path: Path) -> None:
    out = passed(game(tmp_path, levy_law(daily=True), on=False))
    assert [(m.group, m.change, m.cause) for m in out] == [("greens", 2, Cause.MEASURE_PASSED)]


def test_a_secret_daily_life_kind_moves_nobody_when_the_law_passes(tmp_path: Path) -> None:
    g = game(
        tmp_path, levy_law(daily=True), classed({"kind": "daily_life_passed", "reach": "secret"})
    )
    assert passed(g) == []


def test_the_classes_change_no_group_at_the_start(tmp_path: Path) -> None:
    on, off = game(tmp_path / "on"), game(tmp_path / "off", on=False)
    assert on.state.groups.support == off.state.groups.support
    assert on.state.groups.declared == off.state.groups.declared
