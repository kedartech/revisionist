"""HFG: the home-front game, the scripted proof.

Roosevelt and Admiral King play the 1941 season through the engine's entry points
(``tests/home_front_script.py``). Roosevelt sends the Neutrality revision and prices it
with the House Democrats (``britain_supplied``); once it is law he keeps the promise with
a Lend-Lease finding for Britain, or files nothing and lets it come due unmet.
"""

from functools import cache
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.realism.groups import Cause
from revisionist.core.realism.offers import OfferStanding
from tests import home_front_script as hf
from tests.locked_orders_script import digest

KEPT = hf.FULL
UNMET = hf.HomeScript(keep=False)
NONE = hf.HomeScript(offer=False, keep=False)
RESTART = hf.HomeScript(restart_at=1, retry_at=1)

RUNS: dict[str, hf.HomeScript] = {
    "kept": KEPT,
    "again": KEPT,
    "unmet": UNMET,
    "none": NONE,
    "restart": RESTART,
}


@cache
def _run(name: str, base: Path) -> hf.HomeGame:
    mp = pytest.MonkeyPatch()
    tmp = base / name
    tmp.mkdir(parents=True, exist_ok=True)
    return hf.home_game(hf.NINETEEN_41, tmp, mp, RUNS[name])


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.mktemp("hfg")
    return lambda name: _run(name, base)


def standings(g: hf.HomeGame) -> list[OfferStanding]:
    return [e.standing for e in g.logged(ev.OfferSettled)]


def bloc_moves(g: hf.HomeGame, cause: Cause) -> list[int]:
    return [m.change for m in g.moved(cause) if m.group == g.home.bloc]


# --- rule 1: the priced revision passes and the promise is kept --------------------------


def test_the_president_prices_the_revision_and_the_bloc_takes_it(runs) -> None:
    g = runs("kept")
    assert g.kept.refused is None
    assert g.kept.offer_id is not None
    assert standings(g)[:1] == [OfferStanding.TAKEN]


def test_the_price_moves_the_count_for_the_revision(runs) -> None:
    priced, bare = runs("kept"), runs("none")
    yeas = "neutrality_revision_house_yeas"
    assert priced.quantity(yeas) > bare.quantity(yeas)


def test_the_revision_resolves_on_its_date_and_passes(runs) -> None:
    g = runs("kept")
    assert g.passed(g.state)


def test_the_promise_comes_due_and_is_kept(runs) -> None:
    g = runs("kept")
    assert standings(g) == [OfferStanding.TAKEN, OfferStanding.DUE, OfferStanding.KEPT]
    assert bloc_moves(g, Cause.PROMISE_KEPT) and all(c > 0 for c in bloc_moves(g, Cause.PROMISE_KEPT))
    assert not bloc_moves(g, Cause.PROMISE_BROKEN)


# --- rule 2: the promise unmet ----------------------------------------------------------


def test_the_promise_unmet_is_broken_on_its_due_day(runs) -> None:
    g = runs("unmet")
    assert standings(g) == [OfferStanding.TAKEN, OfferStanding.DUE, OfferStanding.BROKEN]
    broken = [e for e in g.logged(ev.OfferSettled) if e.standing is OfferStanding.BROKEN]
    assert broken[0].on == broken[0].due


def test_the_bloc_support_falls_when_the_promise_is_broken(runs) -> None:
    kept, unmet = runs("kept"), runs("unmet")
    assert bloc_moves(unmet, Cause.PROMISE_BROKEN)
    assert all(c < 0 for c in bloc_moves(unmet, Cause.PROMISE_BROKEN))
    due = [e.due for e in unmet.logged(ev.OfferSettled) if e.standing is OfferStanding.BROKEN][0]
    assert [m.on for m in unmet.moved(Cause.PROMISE_BROKEN) if m.group == unmet.home.bloc] == [due]
    # weekly drift pulls both back toward the baseline by the season's end, so the fall
    # is read on the due day itself: the kept run rises there, the unmet run falls
    assert sum(bloc_moves(kept, Cause.PROMISE_KEPT)) > 0 > sum(bloc_moves(unmet, Cause.PROMISE_BROKEN))


# --- determinism and restart ------------------------------------------------------------


def test_the_script_run_twice_gives_one_digest(runs) -> None:
    assert digest(runs("kept").state) == digest(runs("again").state)


def test_a_restart_mid_game_gives_the_same_digest(runs) -> None:
    assert digest(runs("restart").state) == digest(runs("kept").state)
