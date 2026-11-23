"""The fog sweep: one twin-world test across every reply (FOG).

For the toy world and Salt Strait, each pair in ``tests/fog_twins.py`` is two games that
differ in exactly one fact the viewing seat may not know. Every read the seat can make
(the snapshot with every sheet's data, each page, the map, catch-up, the check, the odds
and the wake notice), before and after a wake closes, and every refusal it can provoke by
naming the hidden thing, must be the same bytes in both games. A difference is a finding:
its case is marked strict expected-to-fail, naming the fix in the lane that owns the file.
With ``FOG_SHOW=1`` each difference is printed where the two replies part.
"""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.fold import state_hash
from revisionist.engine.web import realism_snapshot
from tests import fog_twins as ft
from tests.pg import Cluster

KINDS = (
    "enemy piece",
    "other economy",
    "other groups",
    "sealed vote",
    "private agreement",
    "held order and ask",
    "other aims",
    "report not arrived",
    "person or code",
    "hidden law",
    "written order awaiting the close",
)
"""The contract's eleven kinds of hidden fact, in its order."""

HUMANS = (
    "rules lane fix: the wake header's human count and the commit reply's 'waiting for N "
    "other player(s)' tell whether a seat is played by a person or by code "
    "(src/revisionist/engine/web/wake_api.py, wake_header and commit)"
)
HELD = (
    "rules lane fix: held orders are numbered in one sequence for the whole game, so a "
    "seat's own held order's number, and a withdraw by number, show another seat's "
    "order waiting for the close (src/revisionist/engine/web/held.py, server.py _hold "
    "and _withdraw)"
)
FINDINGS: dict[str, str] = {
    "toy-person-or-code": HUMANS,
    "salt-person-or-code": HUMANS,
    "toy-written-order-awaiting-the-close": HELD,
}
"""Pairs that differ today: the pair's id and the fix it waits on, in the owner's lane."""


def differences(pair: ft.Pair, a: ft.Side, b: ft.Side) -> list[str]:
    """Each read or refusal of ``pair``'s viewers whose bytes differ between the games."""
    found: list[str] = []

    def compare(moment: str, take: Callable[[ft.Side, str], dict[str, bytes]]) -> None:
        for who in pair.viewers:
            x, y = ft.canonical(take(a, who)), ft.canonical(take(b, who))
            for key in sorted({*x, *y}):
                if x.get(key) != y.get(key):
                    found.append(f"{who}, {moment}: {key}")
                    if os.environ.get("FOG_SHOW"):
                        print(pair.id, who, moment, ft.where(key, x.get(key, b""), y.get(key, b"")))

    def read(s: ft.Side, who: str) -> dict[str, bytes]:
        return ft.reads(s, who, ft.READS[pair.world])

    compare("wake 0", read)
    for n in range(pair.wakes):
        ft.close_wake(a)
        ft.close_wake(b)
        compare(f"after wake {n}", read)
    names = pair.names(b)

    compare("naming it", lambda s, who: ft.refusals(s, who, names))
    return found


def _case(pair: ft.Pair) -> Any:
    fix = FINDINGS.get(pair.id)
    marks = [pytest.mark.xfail(strict=True, reason=fix)] if fix else []
    return pytest.param(pair, id=pair.id, marks=marks)


@pytest.mark.parametrize("pair", [_case(p) for p in ft.PAIRS])
def test_the_seat_reads_and_is_refused_the_same_in_both_games(
    pair: ft.Pair, pg_cluster: Cluster, tmp_path: Path
) -> None:
    with ft.twins(pair, pg_cluster, tmp_path) as (a, b):
        assert ft.truth(a) != ft.truth(b), "the hidden fact did not land"
        found = differences(pair, a, b)
    assert not found, "\n".join(found)


@pytest.mark.parametrize("world", ["toy", "salt"])
def test_two_games_with_nothing_hidden_read_the_same_across_a_wake(
    world: str, pg_cluster: Cluster, tmp_path: Path
) -> None:
    """The control: built alike, the two games give every seat the same bytes."""
    viewers = ft.TOY_SEATS if world == "toy" else ft.SALT_SEATS
    pair = ft.Pair("nothing", world, viewers)
    with ft.twins(pair, pg_cluster, tmp_path) as (a, b):
        assert ft.truth(a) == ft.truth(b)
        assert not differences(pair, a, b)


def test_the_sweep_is_red_on_a_planted_leak(
    pg_cluster: Cluster, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A snapshot that carries one bit of the truth the seat may not see is found."""
    (pair,) = [p for p in ft.PAIRS if p.id == "salt-other-economy"]
    seat_realism = realism_snapshot.seat_realism

    def leaky(state: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        out = seat_realism(state, *args, **kwargs)
        return out | {"planted": state_hash(state)}

    with ft.twins(pair, pg_cluster, tmp_path) as (a, b):
        assert not differences(pair, a, b)
        monkeypatch.setattr(realism_snapshot, "seat_realism", leaky)
        found = differences(pair, a, b)
    assert found and all(line.endswith(": me") for line in found), found


def test_the_reads_cover_every_read_the_seat_can_make(pg_cluster: Cluster, tmp_path: Path) -> None:
    (pair,) = [p for p in ft.PAIRS if p.id == "salt-report-not-arrived"]
    with ft.twins(pair, pg_cluster, tmp_path) as (a, _):
        got = ft.reads(a, "oren_vale", ft.READS["salt"])
    heads = {key.split(" ", 1)[0] for key in got}
    assert heads == {"me", "read", "map", "catchup", "check", "odds", "notice"}, heads
    assert json.loads(got["me"])["game"]["view"]["realism"]["home"] is not None


def test_every_kind_is_paired_in_both_worlds_or_listed_as_not_buildable() -> None:
    built = {(p.world, p.kind) for p in ft.PAIRS}
    for world in ("toy", "salt"):
        for kind in KINDS:
            listed = f"{world}-{kind.replace(' ', '-')}" in ft.NOT_BUILT
            assert ((world, kind) in built) != listed, (world, kind)
    assert {p.kind for p in ft.PAIRS} <= set(KINDS)


def test_every_finding_names_a_pair_and_a_fix_and_is_strict() -> None:
    ids = {p.id for p in ft.PAIRS}
    assert set(FINDINGS) <= ids
    lanes = ("core", "rules", "data", "scenario", "board", "surface", "guard")
    assert all(fix.split(" lane fix: ")[0] in lanes for fix in FINDINGS.values())
    for pair in ft.PAIRS:
        marks = _case(pair).marks
        assert [m.kwargs.get("strict") for m in marks] == ([True] if pair.id in FINDINGS else [])
