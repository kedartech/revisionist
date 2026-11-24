"""The fog sweep with a commander held to his post.

With ``post_view`` on, a seat on a military card sees what his post would. Each pair is
two games that differ in one fact of the general's own nation: every read he can make
must be the same bytes in both. The same pair read with ``post_view`` off, or by a
political seat of the same nation, must read apart, which is what makes it a fact a
military seat no longer sees.

In the toy world Kara is Norra's general and Ilse its chancellor; in Salt Strait General
Aske, Ostrel's marshal, is put on the military path and no political seat of Ostrel is
played.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import goals as gl
from revisionist.core.ontology import Controller
from revisionist.core.project import project
from revisionist.core.state import State, Wake
from revisionist.engine import notice
from revisionist.engine.web import economy_api, home_api
from revisionist.engine.web.stakes import seat_stakes
from tests import fog_twins as ft
from tests import test_realism_locks as toy_locks
from tests.pg import Cluster
from tests.test_fog_sweep import FINDINGS, differences


def kesh_fodder(w: ft.World, hidden: bool) -> None:
    """The fodder Kesh sells Ostrel a month, a trade line only its parties see, with
    General Aske's card on the military path in both games."""
    ft._find(w["cards"], "general_aske")["path"] = "military"
    if hidden:
        ft._find(w["trade_lines"], "kesh_ostrel_fodder")["amount"] = 2.0


def ostrel_pact(w: ft.World, hidden: bool) -> None:
    """A secret pact of Ostrel's with Kesh, with General Aske's card on the military path
    in both games."""
    ft._find(w["cards"], "general_aske")["path"] = "military"
    ft.salt_agreement(w, hidden)


@dataclass(frozen=True)
class Own:
    """One fact of a general's own nation: the world, the edit, the general, and the
    political seat of his nation who still reads it (None where none is played)."""

    world: str
    change: ft.Change
    general: str
    minister: str | None
    wakes: int = 1
    names: Callable[[ft.Side], tuple[ft.Probe, ...]] = lambda s: ()


OWN = {
    "own groups": Own("toy", ft.toy_groups, "kara", "ilse"),
    "own trade line": Own("salt", kesh_fodder, "general_aske", None, wakes=0),
    "own secret pact": Own(
        "salt", ostrel_pact, "general_aske", None, names=ft.salt_agreement_names
    ),
}
"""The Greys' support in Norra; the fodder Kesh sells Ostrel; Ostrel's secret pact."""


def _pair(name: str, viewer: str, on: bool = True) -> ft.Pair:
    own = OWN[name]

    def change(w: ft.World, hidden: bool) -> None:
        if on:
            w["rules"] = sorted({*w["rules"], "post_view"})
        own.change(w, hidden)

    return ft.Pair(name, own.world, (viewer,), change=change, names=own.names, wakes=own.wakes)


def _held(pair: ft.Pair) -> ft.Pair:
    """``pair`` with ``post_view`` on in both games."""

    def change(w: ft.World, hidden: bool) -> None:
        w["rules"] = sorted({*w["rules"], "post_view"})
        pair.change(w, hidden)

    return replace(pair, change=change)


def _sweep_case(pair: ft.Pair) -> Any:
    fix = FINDINGS.get(pair.id)
    marks = [pytest.mark.xfail(strict=True, reason=fix)] if fix else []
    return pytest.param(_held(pair), id=pair.id, marks=marks)


@pytest.mark.parametrize("pair", [_sweep_case(p) for p in ft.PAIRS])
def test_the_sweep_reads_the_same_with_post_view_on(
    pair: ft.Pair, pg_cluster: Cluster, tmp_path: Path
) -> None:
    """Every pair of the fog sweep, with commanders held to their posts: in the toy world
    Norra's general and its chancellor are among the viewers."""
    with ft.twins(pair, pg_cluster, tmp_path) as (a, b):
        assert ft.truth(a) != ft.truth(b), "the hidden fact did not land"
        found = differences(pair, a, b)
    assert not found, "\n".join(found)


def test_the_sweep_with_post_view_on_reads_for_a_general_and_a_minister_of_one_nation() -> None:
    seen = {who for p in ft.PAIRS if p.world == "toy" for who in p.viewers}
    assert {"kara", "ilse"} <= seen


@pytest.mark.parametrize("name", sorted(OWN))
def test_the_general_held_to_his_post_reads_the_same_in_both_games(
    name: str, pg_cluster: Cluster, tmp_path: Path
) -> None:
    pair = _pair(name, OWN[name].general)
    with ft.twins(pair, pg_cluster, tmp_path) as (a, b):
        assert ft.truth(a) != ft.truth(b), "the hidden fact did not land"
        found = differences(pair, a, b)
    assert not found, "\n".join(found)


@pytest.mark.parametrize("name", sorted(OWN))
def test_with_post_view_off_the_general_reads_it(
    name: str, pg_cluster: Cluster, tmp_path: Path
) -> None:
    pair = _pair(name, OWN[name].general, on=False)
    with ft.twins(pair, pg_cluster, tmp_path) as (a, b):
        assert differences(pair, a, b), "without post_view a general reads his nation's facts"


@pytest.mark.parametrize("name", sorted(n for n, o in OWN.items() if o.minister))
def test_a_political_seat_of_the_same_nation_still_reads_it(
    name: str, pg_cluster: Cluster, tmp_path: Path
) -> None:
    minister = OWN[name].minister
    assert minister is not None
    pair = _pair(name, minister)
    with ft.twins(pair, pg_cluster, tmp_path) as (a, b):
        assert differences(pair, a, b), "a political seat of the nation reads its own facts"


def _at_wake(tmp_path: Path, number: int, *rules: str) -> State:
    def on(w: dict[str, Any]) -> None:
        w["rules"] = sorted({*w["rules"], "groups", *rules})

    tmp_path.mkdir()
    state = toy_locks.game(tmp_path, on)
    close = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=24)
    return state.model_copy(update={"wake": Wake(number=number, deadline=close)})


def test_a_commander_held_to_his_post_is_told_so_once_on_his_first_wake(tmp_path: Path) -> None:
    kara, ilse = toy_locks.seat(toy_locks.KARA), toy_locks.seat(toy_locks.ILSE)
    first = _at_wake(tmp_path / "first", 1, "post_view")
    later = _at_wake(tmp_path / "later", 2, "post_view")
    off = _at_wake(tmp_path / "off", 1)
    assert notice.POST_CLAUSE in notice.compose(first, kara, None, "G")[1]
    assert notice.POST_CLAUSE not in notice.compose(later, kara, None, "G")[1]
    assert notice.POST_CLAUSE not in notice.compose(first, ilse, None, "G")[1]
    assert notice.POST_CLAUSE not in notice.compose(off, kara, None, "G")[1]


def _aske_checks(pg: Cluster, tmp_path: Path, on: bool) -> list[str]:
    """How each of General Aske's aims' checks is seen on the score, aim by aim, with his
    seat a player's and his aims made goals (contests are read from no events, which the
    aims do not need)."""
    with ft.twins(_pair("own trade line", "general_aske", on=on), pg, tmp_path) as (a, _):
        state, aske = a.state(), a.seat("general_aske")
    human = state.seats[aske].model_copy(update={"controller": Controller.HUMAN})
    state = state.model_copy(update={"seats": {**state.seats, aske: human}})
    made = {s.goal.goal_id: s.goal for s in gl.aim_goals(state) if s.goal.seat_id == aske}
    state = state.model_copy(update={"goals": {**state.goals, **made}})
    aims = seat_stakes(state, aske, [])["aims"]
    return [leaf["seen"] for aim in aims for leaf in aim["leaves"]]


def test_the_score_marks_his_own_nations_checks_uncertain_at_his_post(
    pg_cluster: Cluster, tmp_path: Path
) -> None:
    off = _aske_checks(pg_cluster, tmp_path / "off", on=False)
    on = _aske_checks(pg_cluster, tmp_path / "on", on=True)
    assert "own" in off, "the marshal's aims read a fact of Ostrel's own"
    assert "own" not in on
    for was, now in zip(off, on, strict=True):
        assert now == ("uncertain" if was == "own" else was)


def test_the_home_sheet_at_his_post_holds_the_public_band_and_his_places_only(
    tmp_path: Path,
) -> None:
    state = _at_wake(tmp_path / "on", 1, "post_view")
    plain = _at_wake(tmp_path / "off", 1)
    kara, ilse = toy_locks.seat(toy_locks.KARA), toy_locks.seat(toy_locks.ILSE)
    at_post = home_api.block(state, project(state, kara))
    minister = home_api.block(state, project(state, ilse))
    before = home_api.block(plain, project(plain, kara))
    assert at_post is not None and minister is not None and before is not None
    assert minister["groups"], "the chancellor reads Norra's groups"
    assert at_post["groups"] == [] and at_post["chambers"] == [] and at_post["themes"] == []
    assert at_post["standing"] is None
    assert at_post["standings"] == minister["standings"]
    assert at_post["places"] == minister["places"]
    assert not {"offers", "promises", "office", "turning", "elections"} & at_post.keys()
    assert before == home_api.block(plain, project(plain, kara))
    assert before["groups"] == minister["groups"]


def test_the_economy_sheet_at_his_post_holds_his_fuel_and_the_public_figures(
    tmp_path: Path,
) -> None:
    state = _at_wake(tmp_path / "on", 1, "territories", "holders", "economy", "fuel", "post_view")
    kara, ilse = toy_locks.seat(toy_locks.KARA), toy_locks.seat(toy_locks.ILSE)
    at_post = economy_api.block(state, project(state, kara))
    minister = economy_api.block(state, project(state, ilse))
    assert at_post is not None and minister is not None
    assert at_post["own"] is not None and minister["own"] is not None
    assert minister["own"]["income"] and minister["own"]["territories"]
    assert "output" in minister["own"]["pools"]
    assert at_post["own"]["income"] == [] and at_post["own"]["territories"] == []
    assert at_post["own"]["pools"] == {
        k: v for k, v in minister["own"]["pools"].items() if k == "fuel"
    }
    assert at_post["own"]["fuel_months"] == minister["own"]["fuel_months"]
    assert at_post["figures"] == minister["figures"]
