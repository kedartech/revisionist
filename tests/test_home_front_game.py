"""HFG: the home-front game, the scripted proof.

Roosevelt and Admiral King play the 1941 season through the engine's entry points
(``tests/home_front_script.py``). Roosevelt sends the Neutrality revision and prices it
with the House Democrats (``britain_supplied``); once it is law he keeps the promise with
a Lend-Lease finding for Britain, or files nothing and lets it come due unmet. On Salt
Strait Oren Vale sends the Salt Convoy Act, prices it with the Free Traders
(``open_strait_word``) and keeps it by speaking for the open strait.

The world as shipped puts the United States at peace and Salt Strait's nations at peace,
so nothing either home nation loses can move its groups. The 1941 games here are played on
a copy at war with Germany, the HX convoys under American escort (``hf.WAR``); the Salt
Strait loss game on a copy at war with Ostrel, Ostrel's galleys waiting at the free port
where Varda's commander sails. No chamber bloc in either world is moved by losses (HFD and
SSH name the public, the press and the yeomanry), so the heavy-losses game adds the
chambers to the groups losses move, on a copy (``hf.felt_in_the_chambers``).
"""

from collections.abc import Callable
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.project import project
from revisionist.core.realism import groups
from revisionist.core.realism.groups import Cause, Happening
from revisionist.core.realism.offers import OfferStanding
from revisionist.core.state import State
from revisionist.engine import catchup
from tests import home_front_script as hf
from tests.locked_orders_script import digest

World = dict[str, Any]
Change = Callable[[World], None]

KEPT = hf.FULL
UNMET = hf.HomeScript(keep=False)
NONE = hf.HomeScript(offer=False, keep=False)
RESTART = hf.HomeScript(restart_at=1, retry_at=1)


def _stop_on(day: date) -> Callable[[State], bool]:
    return lambda s: s.in_world_date is not None and s.in_world_date >= day


# --- the Salt Strait war copy -----------------------------------------------------------


def strait_war(w: World) -> None:
    """Ostrel at war with Varda from the season's first day, its galleys at the free port."""
    w.setdefault("wars", []).append(
        {"a": "ostrel", "b": "varda", "since": "1900-03-31", "gap": True}
    )
    for f in w["features"]:
        if f.get("key") == "ostrel_galleys":
            f["places"], f["tier"] = ["free_port"], 4


# name -> (home, script, world changes)
RUNS: dict[str, tuple[hf.Home, hf.HomeScript, tuple[Change, ...]]] = {
    "kept": (hf.NINETEEN_41, KEPT, hf.WAR),
    "again": (hf.NINETEEN_41, KEPT, hf.WAR),
    "unmet": (hf.NINETEEN_41, UNMET, hf.WAR),
    "none": (hf.NINETEEN_41, NONE, hf.WAR),
    "restart": (hf.NINETEEN_41, RESTART, hf.WAR),
    "heavy": (hf.NINETEEN_41, NONE, (*hf.WAR, hf.felt_in_the_chambers(hf.HEAVY))),
    "twin_with": (
        hf.NINETEEN_41,
        hf.HomeScript(keep=False, stop=_stop_on(date(1941, 9, 10))),
        hf.WAR,
    ),
    "twin_without": (
        hf.NINETEEN_41,
        hf.HomeScript(offer=False, keep=False, stop=_stop_on(date(1941, 9, 10))),
        hf.WAR,
    ),
    "ss_kept": (hf.SALT_STRAIT, KEPT, ()),
    "ss_again": (hf.SALT_STRAIT, KEPT, ()),
    "ss_restart": (hf.SALT_STRAIT, RESTART, ()),
    "ss_unmet": (hf.SALT_STRAIT, UNMET, ()),
    "ss_none": (hf.SALT_STRAIT, NONE, ()),
    "ss_war": (hf.SALT_STRAIT, KEPT, (strait_war,)),
    "ss_twin_with": (
        hf.SALT_STRAIT,
        hf.HomeScript(keep=False, stop=_stop_on(date(1900, 4, 11))),
        (),
    ),
    "ss_twin_without": (
        hf.SALT_STRAIT,
        hf.HomeScript(offer=False, keep=False, stop=_stop_on(date(1900, 4, 11))),
        (),
    ),
}


Runs = Callable[[str], hf.HomeGame]


@cache
def _run(name: str, base: Path) -> hf.HomeGame:
    home, script, changes = RUNS[name]
    tmp = base / name
    tmp.mkdir(parents=True, exist_ok=True)
    return hf.home_game(home, tmp, pytest.MonkeyPatch(), script, changes)


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> Runs:
    base = tmp_path_factory.mktemp("hfg")
    return lambda name: _run(name, base)


def standings(g: hf.HomeGame) -> list[OfferStanding]:
    return [e.standing for e in g.logged(ev.OfferSettled)]


def bloc_moves(g: hf.HomeGame, cause: Cause) -> list[int]:
    return [m.change for m in g.moved(cause) if m.group == g.home.bloc]


def moved_by(g: hf.HomeGame, happening: Happening) -> dict[str, int]:
    """The home nation's groups the world says ``happening`` moves, with their amounts."""
    nation = g.cast.entity(g.home.nation)
    return {
        grp.key: grp.moved_by[happening]
        for grp in groups.of(g.state, nation)
        if grp.moved_by.get(happening)
    }


def yeas(g: hf.HomeGame) -> int:
    """The first chamber's ayes on the measure, as the game ends."""
    found = g.quantity(next(q for q in g.cast.votes if q.endswith("_yeas")))
    assert found is not None
    return found


# --- rule 1: losses move the groups; the priced revision passes; the promise is kept ------


def test_battle_losses_move_only_the_groups_the_world_names_by_their_sign(runs: Runs) -> None:
    for g in (runs("kept"), runs("ss_war")):
        named = moved_by(g, Happening.BATTLE_LOSSES)
        moves = g.moved(Cause.BATTLE_LOSSES)
        assert moves, g.home.nation
        assert {m.group for m in moves} <= set(named)
        assert all((m.change < 0) == (named[m.group] < 0) for m in moves if m.change)


def test_battle_losses_are_held_and_felt_later(runs: Runs) -> None:
    for g in (runs("kept"), runs("ss_war")):
        nation = g.cast.entity(g.home.nation)
        held = [h for e in g.logged(ev.LossesHeld) for h in e.held if h.polity == nation]
        assert held and all(h.group in moved_by(g, Happening.BATTLE_LOSSES) for h in held)
        assert g.moved(Cause.LOSSES_FELT)


def test_losses_at_sea_move_the_groups_monthly_by_their_sign(runs: Runs) -> None:
    g = runs("kept")
    named = moved_by(g, Happening.LOSSES_AT_SEA)
    moves = g.moved(Cause.LOSSES_AT_SEA)
    assert moves
    assert {m.group for m in moves} <= set(named)
    assert all(m.on.day == 1 for m in moves)
    assert all((m.change < 0) == (named[m.group] < 0) for m in moves if m.change)


def test_the_world_as_shipped_lets_no_loss_reach_a_chamber_bloc(runs: Runs) -> None:
    """Recorded, not wished: losses reach the vote only where a chamber bloc is named."""
    for g in (runs("kept"), runs("ss_war")):
        chambers = {
            grp.key for grp in groups.of(g.state, g.cast.entity(g.home.nation)) if grp.chamber
        }
        for happening in (Happening.BATTLE_LOSSES, Happening.LOSSES_AT_SEA):
            assert not chambers & set(moved_by(g, happening))


@pytest.mark.parametrize("kept, bare", [("kept", "none"), ("ss_kept", "ss_none")])
def test_the_leader_prices_the_measure_and_the_bloc_takes_it(
    runs: Runs, kept: str, bare: str
) -> None:
    g = runs(kept)
    assert g.kept.refused is None
    assert g.kept.offer_id is not None
    assert standings(g)[:1] == [OfferStanding.TAKEN]
    assert not runs(bare).logged(ev.OfferMade)


@pytest.mark.parametrize("kept, bare", [("kept", "none"), ("ss_kept", "ss_none")])
def test_the_price_moves_the_count(runs: Runs, kept: str, bare: str) -> None:
    priced, plain = runs(kept), runs(bare)
    assert yeas(priced) > yeas(plain)


@pytest.mark.parametrize("name", ["kept", "ss_kept"])
def test_the_measure_resolves_on_its_date_and_passes(runs: Runs, name: str) -> None:
    g = runs(name)
    assert g.passed(g.state)


@pytest.mark.parametrize("name", ["kept", "ss_kept"])
def test_the_promise_comes_due_and_is_kept(runs: Runs, name: str) -> None:
    g = runs(name)
    assert standings(g) == [OfferStanding.TAKEN, OfferStanding.DUE, OfferStanding.KEPT]
    kept = bloc_moves(g, Cause.PROMISE_KEPT)
    assert kept and all(c > 0 for c in kept)
    assert not bloc_moves(g, Cause.PROMISE_BROKEN)


# --- rule 2: the promise unmet ----------------------------------------------------------


@pytest.mark.parametrize("kept, unmet", [("kept", "unmet"), ("ss_kept", "ss_unmet")])
def test_the_bloc_support_falls_on_the_due_day_when_the_promise_is_unmet(
    runs: Runs, kept: str, unmet: str
) -> None:
    k, u = runs(kept), runs(unmet)
    assert standings(u) == [OfferStanding.TAKEN, OfferStanding.DUE, OfferStanding.BROKEN]
    broken = [e for e in u.logged(ev.OfferSettled) if e.standing is OfferStanding.BROKEN]
    assert broken[0].on == broken[0].due
    falls = [m for m in u.moved(Cause.PROMISE_BROKEN) if m.group == u.home.bloc]
    assert [m.on for m in falls] == [broken[0].due]
    assert all(m.change < 0 for m in falls)
    # weekly drift pulls both back toward the baseline by the season's end, so the fall
    # is read on the due day itself: the kept run rises there, the unmet run falls
    assert sum(bloc_moves(k, Cause.PROMISE_KEPT)) > 0 > sum(m.change for m in falls)


# --- rule 3: heavy losses and no offer ---------------------------------------------------


def test_heavy_losses_without_an_offer_fail_the_vote(runs: Runs) -> None:
    light, heavy = runs("none"), runs("heavy")
    assert light.passed(light.state)
    assert not heavy.passed(heavy.state)
    assert yeas(heavy) < yeas(light)
    sea = [m for m in heavy.moved(Cause.LOSSES_AT_SEA) if m.group == heavy.home.bloc]
    assert sea and sum(m.change for m in sea) < 0


# --- rule 4: a place abandoned costs more than a place lost in a fight -------------------


PLACES: dict[str, tuple[str, str]] = {
    "usa": ("hawaii", "japan"),
    "varda": ("varda_saltworks", "ostrel"),
}
"""Each home nation's weighted place, and the nation that takes it."""


def _place_cost(g: hf.HomeGame, fought: bool) -> dict[str, int]:
    """What the home nation's groups lose when its place changes hands on the season's last
    day: after a battle fought there, or with none (abandoned)."""
    area_key, taker = PLACES[g.home.nation]
    area, nation = g.cast.entity(area_key), g.cast.entity(g.home.nation)
    state = g.state
    start = state.model_copy(update={"fought": state.fought | {area}}) if fought else state
    day = state.in_world_date
    assert day is not None
    lost = ev.AreaHeld(area=area, holder=g.cast.entity(taker), was=nation, on=day)
    return {
        m.group: m.change
        for m in groups.places(start, start, [lost], day)
        if isinstance(m, ev.GroupMoved) and m.polity == nation
    }


@pytest.mark.parametrize("name", ["kept", "ss_kept"])
def test_a_place_abandoned_costs_more_at_home_than_lost_in_a_fight(runs: Runs, name: str) -> None:
    g = runs(name)
    fought, abandoned = _place_cost(g, True), _place_cost(g, False)
    assert fought and set(fought) == set(abandoned)
    assert sum(abandoned.values()) < sum(fought.values()) < 0
    assert all(abandoned[k] < fought[k] for k in fought)


# --- determinism, restart, the twin world --------------------------------------------------


@pytest.mark.parametrize("one, two", [("kept", "again"), ("ss_kept", "ss_again")])
def test_the_script_run_twice_gives_one_digest(runs: Runs, one: str, two: str) -> None:
    assert digest(runs(one).state) == digest(runs(two).state)


@pytest.mark.parametrize("kept, restart", [("kept", "restart"), ("ss_kept", "ss_restart")])
def test_a_restart_mid_game_gives_the_same_digest(runs: Runs, kept: str, restart: str) -> None:
    assert digest(runs(restart).state) == digest(runs(kept).state)


def _seen(g: hf.HomeGame, seat: Any) -> tuple[str, list[Any]]:
    fed = [
        f.event.payload.model_dump(mode="json")
        for f in catchup.feed(g.state, g.events(), seat, 0, 10**9)
    ]
    return project(g.state, seat).model_dump_json(), fed


@pytest.mark.parametrize(
    "with_, without", [("twin_with", "twin_without"), ("ss_twin_with", "ss_twin_without")]
)
def test_a_seat_of_another_nation_learns_nothing_of_the_offer_or_the_groups(
    runs: Runs, with_: str, without: str
) -> None:
    offered, plain = runs(with_), runs(without)
    assert offered.kept.offer_id is not None and plain.kept.offer_id is None
    home = {offered.leader, offered.commander}
    abroad = sorted(s for s in offered.state.seats if s not in home)
    assert abroad
    for seat in abroad:
        assert _seen(offered, seat) == _seen(plain, seat), seat
    # the home seats do see it: the twin is not equal for want of a difference
    assert _seen(offered, offered.leader) != _seen(plain, plain.leader)
