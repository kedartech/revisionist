"""Groups at home, defined by the world (GRP).

The toy world (``tests/worlds/territory-toy.yaml``) gives Norra four groups and Sudland
one. They are read only with ``groups`` on; every test here switches the rule on unless
it says otherwise. ``groups.shift`` is the only way support moves: writing is settled in
one batch a world day by content, each listed happening moves the groups that name it
once, and on Mondays a group drifts toward its baseline.
"""

import hashlib
import itertools
import json
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.ids import EntityId, FeatureId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import groups
from revisionist.core.realism.battle import Battle, BattleSide, Ending
from revisionist.core.realism.groups import Cause, Happening
from revisionist.core.realism.holders import Capture
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.state import State
from revisionist.core.visibility import Visibility
from revisionist.core.world import WorldFile
from revisionist.engine import realism_tick
from tests.test_adjacency_moves import START, Logged, entity, fold, seat, toy
from tests.test_battles import rules, strengths
from tests.test_battles import toy as battles_toy
from tests.test_territory_model import refused

World = dict[str, Any]
NORRA, SUDLAND = entity("norra"), entity("sudland")
ILSE, TOMAS = seat("ilse"), seat("tomas")


def ruled(*rules: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = ["territories", *rules]

    return change


def world(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    return toy(tmp, ruled("holders", "economy", "groups"), *changes)


def game(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    return Logged(world(tmp, *changes), "ilse", "tomas")


def day(n: int) -> date:
    return START + timedelta(days=n)


def wrote(
    state: State, by: SeatId, key: str, change: int, text: str, on: date, polity: EntityId = NORRA
) -> ev.GroupProposed:
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return groups.propose(state, by, polity, key, change, digest, on)


def moved(events: Sequence[ev.Event]) -> list[ev.GroupMoved]:
    return [e.payload for e in events if isinstance(e.payload, ev.GroupMoved)]


def digest(g: Logged, out: Sequence[ev.Event]) -> str:
    body = {
        "moved": [m.model_dump(mode="json") for m in moved(out)],
        "groups": g.state.groups.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


# --- rule 1: the world declares each nation's groups ----------------------------------


def test_a_world_declares_each_nations_groups_in_its_own_order(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert [x.key for x in groups.of(g.state, NORRA)] == ["smiths", "greens", "greys", "public"]
    assert [x.key for x in groups.of(g.state, SUDLAND)] == ["farmers"]
    greens = groups.group(g.state, NORRA, "greens")
    assert greens is not None and greens.chamber == "assembly" and greens.seats == 60
    assert greens.moved_by[Happening.CAPITAL_THREATENED] == -6
    assert greens.votes["levy_act"]["assembly"].yeas == 40
    assert greens.vote_default["assembly"].voting == 50
    assert groups.support(g.state, NORRA, "greens") == 60


def test_the_declaration_is_engine_only(tmp_path: Path) -> None:
    g = game(tmp_path)
    (found,) = [e for e in g.log if isinstance(e.payload, ev.GroupsDeclared)]
    assert found.scope.visibility is Visibility.RESTRICTED
    assert not found.scope.known_by & {ILSE, TOMAS}


def test_a_world_refuses_groups_of_a_place_or_twice_for_a_nation(tmp_path: Path) -> None:
    def twice(w: World) -> None:
        w["groups"].append({**w["groups"][1], "nation": "sudland"})
        w["groups"].append({**w["groups"][1], "nation": "sudby"})

    problems = refused(world(tmp_path, twice))
    assert any("sudland: declared twice" in p for p in problems)
    assert any("sudby is not a polity" in p for p in problems)


def test_a_bloc_votes_no_more_members_than_its_seats(tmp_path: Path) -> None:
    def crowded(w: World) -> None:
        w["groups"][0]["groups"][1]["vote_default"] = {"assembly": {"voting": 61, "yeas": 1}}

    assert any("more members voting than seats" in p for p in refused(world(tmp_path, crowded)))


# --- rule 8: gated by groups -----------------------------------------------------------


def test_with_the_rule_off_the_world_has_no_groups_and_none_move(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path, ruled("holders", "economy")), "ilse", "tomas")
    assert not any(isinstance(e.payload, ev.GroupsDeclared) for e in g.log)
    assert groups.of(g.state, NORRA) == ()
    with pytest.raises(groups.GroupsError):
        wrote(g.state, ILSE, "public", 2, "a speech", day(1))
    assert moved(g.walk(day(1), day(14))) == []


def test_a_world_without_groups_pays_the_same_as_before(tmp_path: Path) -> None:
    def no_groups(w: World) -> None:
        w.pop("groups")
        w.pop("places", None)

    plain = Logged(toy(tmp_path, ruled("holders", "economy"), no_groups), "ilse", "tomas")
    ruled_on = Logged(world(tmp_path, no_groups), "ilse", "tomas")
    plain.walk(day(1), date(1900, 5, 1))
    ruled_on.walk(day(1), date(1900, 5, 1))
    assert plain.state.economy.pools[NORRA].manpower == 2000
    assert ruled_on.state.economy == plain.state.economy


# --- rule 2: writing, settled in one batch a world day ---------------------------------


def test_ten_statements_in_one_world_day_move_a_group_once_to_the_cap(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.add([wrote(g.state, ILSE, "public", 5, f"speech {n}", day(1)) for n in range(10)])
    found = moved(g.walk(day(1), day(1)))
    assert [(m.group, m.change, m.cause) for m in found] == [("public", 3, Cause.WRITING)]
    assert groups.support(g.state, NORRA, "public") == 43


def test_a_seat_contributes_its_largest_proposal_not_their_sum(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.add([wrote(g.state, ILSE, "public", 2, f"speech {n}", day(1)) for n in range(10)])
    assert [m.change for m in moved(g.walk(day(1), day(1)))] == [2]


def test_a_tie_in_magnitude_goes_to_the_smaller_change(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.add([wrote(g.state, ILSE, "public", 2, "for", day(1))])
    g.add([wrote(g.state, ILSE, "public", -2, "against", day(1))])
    assert [m.change for m in moved(g.walk(day(1), day(1)))] == [-2]


def test_the_week_cap_counts_absolute_influence(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.add([wrote(g.state, ILSE, "public", 3, "for", day(1))])
    g.add([wrote(g.state, TOMAS, "public", -3, "against", day(1))])
    first = moved(g.walk(day(1), day(1)))
    assert [(m.change, m.used) for m in first] == [(0, 6)]
    g.add([wrote(g.state, ILSE, "public", 3, "again", day(2))])
    assert [m.change for m in moved(g.walk(day(2), day(2)))] == [0]
    assert groups.used(g.state, NORRA, "public", day(7)) == 6
    assert groups.used(g.state, NORRA, "public", day(8)) == 0


def test_what_is_left_of_the_week_is_shared_by_magnitude_not_by_who_filed_first(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.add([wrote(g.state, ILSE, "public", 3, "monday", day(1))])
    g.walk(day(1), day(1))
    g.add([wrote(g.state, TOMAS, "public", 3, "late", day(2))])
    g.add([wrote(g.state, ILSE, "public", 3, "early", day(2))])
    (found,) = moved(g.walk(day(2), day(2)))
    assert (found.change, found.used) == (3, 3)
    shares = groups._shared({TOMAS: 3, ILSE: 3}, 3)
    assert sorted(shares.values()) == [1, 2]
    assert shares[min(TOMAS, ILSE)] == 2


def test_writing_waits_for_its_day_and_is_settled_once(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.add([wrote(g.state, ILSE, "public", 2, "for thursday", day(3))])
    out = moved(g.walk(day(1), day(5)))
    assert [(m.on, m.change) for m in out] == [(day(3), 2)]
    assert g.state.groups.proposed == ()


def _filings() -> list[tuple[SeatId, str, int, str, EntityId]]:
    """Mixed signs, a foreign seat heard by a Norra group, and Sudland's own."""
    return [
        (ILSE, "public", 3, "rally", NORRA),
        (ILSE, "public", -1, "caution", NORRA),
        (TOMAS, "public", -3, "broadcast to Norra", NORRA),
        (ILSE, "greens", 2, "to the party", NORRA),
        (TOMAS, "greens", -2, "leaflets", NORRA),
        (TOMAS, "farmers", 3, "harvest speech", SUDLAND),
        (ILSE, "farmers", -1, "a foreign word", SUDLAND),
    ]


def _played(w: WorldFile, order: Sequence[int], sittings: int) -> str:
    g = Logged(w, "ilse", "tomas")
    # The week's budget for the public nearly spent before the day.
    g.add([wrote(g.state, ILSE, "public", 3, "earlier", day(1))])
    g.add([wrote(g.state, TOMAS, "public", -2, "earlier too", day(1))])
    g.walk(day(1), day(1))
    filed = [_filings()[i] for i in order]
    size = -(-len(filed) // sittings)
    for chunk in range(0, len(filed), size):
        g.add(
            [
                wrote(g.state, s, k, c, t, day(2), polity=p)
                for s, k, c, t, p in filed[chunk : chunk + size]
            ]
        )
    return digest(g, g.walk(day(2), day(2)))


def test_the_same_filings_in_any_order_or_over_several_sittings_give_one_outcome(
    tmp_path: Path,
) -> None:
    n = len(_filings())
    w = world(tmp_path)
    orders = [
        list(range(n)),
        list(reversed(range(n))),
        *itertools.islice(itertools.permutations(range(n)), 3, 9),
    ]
    found = {_played(w, o, s) for i, o in enumerate(orders) for s in (1, 3, n)}
    assert len(found) == 1


def test_a_proposal_names_a_group_of_the_nation(tmp_path: Path) -> None:
    g = game(tmp_path)
    with pytest.raises(groups.GroupsError):
        wrote(g.state, ILSE, "farmers", 1, "wrong nation", day(1))


# --- rule 3: each listed happening, once ------------------------------------------------


def _side(nation: EntityId, piece: str) -> BattleSide:
    return BattleSide(nation=nation, pieces=(FeatureId(entity(piece)),), brought=3)


def _battle(area: str) -> Battle:
    return Battle(
        area=entity(area),
        opened=day(1),
        attacker=_side(NORRA, "norra_levy"),
        defender=_side(SUDLAND, "sudland_levy"),
    )


def test_a_battle_won_and_lost_moves_each_sides_groups_once(tmp_path: Path) -> None:
    g = game(tmp_path)
    happened: list[ev.Payload] = [
        ev.BattleOpened(battle=_battle("sudland_coast"), on=day(1)),
        ev.BattleEnded(area=entity("sudland_coast"), on=day(1), ending=Ending.WON, winner=NORRA),
    ]
    found = groups.react(g.state, g.state, happened, day(1))
    assert sorted((m.polity, m.group, m.change, m.cause) for m in found) == sorted(
        [
            (NORRA, "smiths", 2, Cause.BATTLE_WON),
            (NORRA, "greens", 3, Cause.BATTLE_WON),
            (SUDLAND, "farmers", -3, Cause.BATTLE_LOST),
        ]
    )


def test_a_territory_changing_hands_moves_the_taker_and_the_loser(tmp_path: Path) -> None:
    g = game(tmp_path)
    took = [ev.AreaHeld(area=entity("isle"), holder=NORRA, was=SUDLAND, on=day(2))]
    found = groups.react(g.state, g.state, took, day(2))
    assert [(m.polity, m.group, m.change) for m in found] == [(NORRA, "public", 3)]
    lost = [ev.AreaHeld(area=entity("norra_hills"), holder=SUDLAND, was=NORRA, on=day(2))]
    found = groups.react(g.state, g.state, lost, day(2))
    assert {(m.polity, m.group, m.change) for m in found} == {
        (SUDLAND, "farmers", 2),
        (NORRA, "smiths", -5),
        (NORRA, "public", -3),
    }


def test_two_of_a_happening_in_a_day_move_a_group_twice_its_amount_in_one_event(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    lost = [
        ev.AreaHeld(area=entity("norra_hills"), holder=SUDLAND, was=NORRA, on=day(2)),
        ev.AreaHeld(area=entity("norra_plain"), holder=SUDLAND, was=NORRA, on=day(2)),
    ]
    found = [m for m in groups.react(g.state, g.state, lost, day(2)) if m.group == "smiths"]
    assert [(m.change, m.support) for m in found] == [(-10, 40)]


def test_a_war_declared_moves_both_nations_groups_that_name_it(tmp_path: Path) -> None:
    g = game(tmp_path)
    war = War(
        war_id=war_id_for(NORRA, SUDLAND), a=NORRA, b=SUDLAND, since=day(1), declared_by=NORRA
    )
    found = groups.react(g.state, g.state, [ev.WarDeclared(war=war)], day(1))
    assert [(m.group, m.change, m.cause) for m in found] == [("greens", 2, Cause.WAR_DECLARED)]


def test_a_capital_marked_to_fall_threatens_its_nation_once(tmp_path: Path) -> None:
    def capital(w: World) -> None:
        for e in w["entities"]:
            if e["key"] == "norra":
                e["capital"] = "norrhavn"

    g = game(tmp_path, capital)
    mark = Capture(by=SUDLAND, since=day(1), marked=1, marked_on=day(3))
    area = entity("norra_plain")
    once = [ev.CaptureCounted(area=area, capture=mark)]
    found = groups.react(g.state, g.state, once, day(3))
    assert [(m.group, m.change, m.cause) for m in found] == [
        ("greens", -6, Cause.CAPITAL_THREATENED)
    ]
    after = fold(g.state, once)
    assert groups.react(g.state, after, once, day(4)) == []


def test_a_battle_in_the_day_walk_moves_the_groups_once(tmp_path: Path) -> None:
    g = Logged(
        battles_toy(
            tmp_path,
            rules("territories", "holders", "battles", "groups"),
            strengths(norra_levy=5, sudland_levy=1),
        ),
        "ilse",
        "tomas",
    )
    g.send("ilse", "norra_levy", "sudby")
    out = g.walk(day(1), day(30))
    (ended,) = [e.payload for e in out if isinstance(e.payload, ev.BattleEnded)]
    won = [m for m in moved(out) if m.cause is Cause.BATTLE_WON]
    lost = [m for m in moved(out) if m.cause is Cause.BATTLE_LOST]
    assert sorted((m.group, m.change, m.on) for m in won) == [
        ("greens", 3, ended.on),
        ("smiths", 2, ended.on),
    ]
    assert [(m.group, m.change) for m in lost] == [("farmers", -3)]
    taken = [m for m in moved(out) if m.cause is Cause.TERRITORY_TAKEN]
    assert [(m.polity, m.group) for m in taken] == [(NORRA, "public")]


def test_losses_at_sea_in_the_month_move_the_nations_groups_on_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revisionist.core.realism.resolvers import shipping

    asked: list[date] = []

    def lost(state: State, last: date) -> dict[FeatureId, int]:
        asked.append(last)
        return {FeatureId(entity("sudland_galleys")): 0, FeatureId(entity("norra_levy")): 900}

    monkeypatch.setattr(shipping, "losses", lost)
    g = game(tmp_path)
    out = [
        m
        for m in moved(g.walk(date(1900, 4, 29), date(1900, 5, 2)))
        if m.cause is Cause.LOSSES_AT_SEA
    ]
    assert [(m.on, m.polity, m.group, m.change) for m in out] == [
        (date(1900, 5, 1), NORRA, "public", -2)
    ]
    assert set(asked) == {date(1900, 4, 30)}  # the shipping rule's own sink reads it too


def test_the_happenings_another_rule_decides_move_the_groups_that_name_them(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    found = groups.happened(g.state, NORRA, Happening.BATTLE_LOST, day(1))
    assert [(m.group, m.change) for m in found] == [("greens", -4)]


# --- rule 4: Monday drift --------------------------------------------------------------


def test_each_monday_a_group_moves_one_point_toward_its_baseline(tmp_path: Path) -> None:
    g = game(tmp_path)
    out = [m for m in moved(g.walk(day(1), day(14))) if m.cause is Cause.DRIFT]
    assert {(m.on, m.group, m.change) for m in out} == {
        (day(7), "greens", -1),
        (day(7), "public", 1),
        (day(7), "farmers", 1),
        (day(14), "greens", -1),
        (day(14), "public", 1),
        (day(14), "farmers", 1),
    }
    assert day(7).weekday() == 0


# --- rules 5 to 7: what groups feed ----------------------------------------------------


def _at(g: Logged, key: str, value: int, polity: EntityId = NORRA) -> None:
    was = groups.support(g.state, polity, key) or 0
    g.add([groups.shift(g.state, polity, key, value - was, Cause.DRIFT, START)])


def test_manpower_income_follows_the_groups_that_feed_it(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert groups.manpower_factor(g.state, NORRA) == pytest.approx(1.0)
    _at(g, "smiths", 100)
    assert groups.manpower_factor(g.state, NORRA) == pytest.approx(1.2)
    _at(g, "smiths", 0)
    assert groups.manpower_factor(g.state, NORRA) == pytest.approx(0.8)
    assert groups.manpower_factor(g.state, SUDLAND) == 1.0
    g.walk(date(1900, 5, 1), date(1900, 5, 1))  # a Tuesday: no drift
    assert g.state.economy.pools[NORRA].manpower == pytest.approx(1600)


def test_output_pays_less_while_its_groups_stand_below_the_strike_line(tmp_path: Path) -> None:
    g = game(tmp_path)
    _at(g, "smiths", 29)
    _at(g, "farmers", 30, SUDLAND)
    assert groups.output_factor(g.state, NORRA) == groups.STRIKE_SHARE
    assert groups.output_factor(g.state, SUDLAND) == 1.0
    g.walk(date(1900, 5, 1), date(1900, 5, 1))
    assert g.state.economy.pools[NORRA].output == pytest.approx(9.0)
    assert g.state.economy.pools[SUDLAND].output == pytest.approx(8.0)


def test_home_standing_is_the_weighted_mean_plus_the_prestige_held(tmp_path: Path) -> None:
    def prestige(w: World) -> None:
        w["resources"].append(
            {"key": "glory", "name": "Glory", "unit": "points", "role": "prestige"}
        )
        for t in w["territories"]:
            if t["key"] == "norra_hills":
                t["yields"] = {"glory": 4}

    g = game(tmp_path, prestige)
    # greens 60 at weight 1, the public 40 at weight 3: 45, and 4 prestige.
    assert groups.home_standing(g.state, NORRA, START) == 49.0
    assert groups.home_standing(g.state, SUDLAND, START) is None


def test_bloc_support_gives_each_bloc_of_a_chamber(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert groups.bloc_support(g.state, NORRA, "assembly") == {"greens": 60, "greys": 30}
    assert groups.bloc_support(g.state, SUDLAND, "assembly") == {}


# --- fog: a nation's groups to its own seats only --------------------------------------


def test_a_seat_sees_its_own_nations_groups_only(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.add([wrote(g.state, ILSE, "public", 2, "a speech", day(1))])
    mine = project(g.state, ILSE).groups
    assert set(mine.declared) == {NORRA} and mine.proposed == ()
    theirs = project(g.state, TOMAS).groups
    assert set(theirs.declared) == {SUDLAND}
    assert NORRA not in theirs.support and NORRA not in theirs.spent


def test_a_group_moved_is_sealed_to_its_nations_seats(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.add([wrote(g.state, TOMAS, "public", -2, "a broadcast", day(1))])
    out = g.walk(day(1), day(7))
    sealed = [e for e in out if isinstance(e.payload, ev.GroupMoved)]
    assert sealed
    for e in sealed:
        nation = e.payload.polity  # type: ignore[union-attr]
        assert e.scope.visibility is Visibility.RESTRICTED
        assert e.scope.known_by == frozenset({ILSE if nation == NORRA else TOMAS})
    (waiting,) = [e.payload for e in g.log if isinstance(e.payload, ev.GroupProposed)]
    scope = realism_tick._scope_of(g.state, waiting)
    assert scope.visibility is Visibility.RESTRICTED and not scope.known_by & {ILSE, TOMAS}


# --- the fold --------------------------------------------------------------------------


def test_the_fold_refuses_a_move_that_does_not_add_up(tmp_path: Path) -> None:
    g = game(tmp_path)
    wrong = ev.GroupMoved(
        polity=NORRA, group="public", support=45, change=3, cause=Cause.DRIFT, on=day(1)
    )
    with pytest.raises(FoldError):
        fold(g.state, [wrong])


def test_the_fold_refuses_spent_points_for_a_happening(tmp_path: Path) -> None:
    g = game(tmp_path)
    wrong = ev.GroupMoved(
        polity=NORRA, group="public", support=43, change=3, cause=Cause.DRIFT, used=3, on=day(1)
    )
    with pytest.raises(FoldError):
        fold(g.state, [wrong])


def test_support_stays_within_0_and_100(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert groups.shift(g.state, NORRA, "public", -90, Cause.DRIFT, day(1)).support == 0
    assert groups.shift(g.state, NORRA, "public", 90, Cause.DRIFT, day(1)).change == 60
