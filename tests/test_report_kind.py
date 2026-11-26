"""A sighting names a kind only when it is seen well enough (KRP).

The toy world (``tests/worlds/territory-toy.yaml``) with ``territories``, ``reports`` and
``kinds_in_battle`` on, every force given a strength, as in ``tests/test_detection.py``.
Norra's kites (``detect`` 60) stand on the Norra Plain; Sudland's galleys (``conceal``
10) stand in the Gulf, which borders the plain, and its levy (``conceal`` 0) on the
Sudland Coast.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.ids import FeatureId
from revisionist.core.realism import detect
from revisionist.core.realism.detect import KIND_MARGIN, Confidence, Sighting, Source
from revisionist.core.realism.effect import Posture
from revisionist.core.state import State
from tests.test_adjacency_moves import Logged, World, day, entity
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_detection import (
    NORRA,
    SUDLAND,
    fid,
    intelligence,
    made,
    norra_sees,
    place,
    rules,
    strengths,
    sudland_sees,
    with_feature,
)
from tests.test_detection import open_roads as norra_galleys_at_sea

SWITCH = "kinds_in_battle"
GALLEY_CONCEAL = 10


def game(tmp: Path, *changes: Callable[[World], None], switch: bool = True) -> Logged:
    tmp.mkdir(parents=True, exist_ok=True)
    names = ("territories", "reports", SWITCH) if switch else ("territories", "reports")
    return Logged(territories_toy(tmp, rules(*names), strengths, *changes), "ilse", "tomas")


def kite_detect(value: int) -> Callable[[World], None]:
    def change(w: World) -> None:
        (kite,) = [k for k in w["piece_kinds"] if k["key"] == "kite"]
        kite["detect"] = value

    return change


def sighting(
    state: State, key: str, source: Source, confidence: Confidence, seen_by: int | None
) -> Sighting:
    piece = state.features[fid(key)]
    return Sighting(source, piece, confidence, piece.places[0], None, False, seen_by)


def kind_of(state: State, s: Sighting, nation: str = NORRA, on: date | None = None) -> str | None:
    return detect.report(state, on or day(1), entity(nation), s)[0].kind


def reports_of(out: list[Any], key: str, source: Source, nation: str = NORRA) -> list[Any]:
    return [
        m.report
        for m in made(out)
        if m.piece == fid(key) and m.report.source is source and m.nation == entity(nation)
    ]


def test_the_margin_is_twenty() -> None:
    assert KIND_MARGIN == 20


# --- Rule 1: a searching piece names the kind only past the margin ------------------------


@pytest.mark.parametrize(
    ("over", "named"), [(-1, False), (0, True), (1, True)], ids=["under", "at", "over"]
)
def test_a_search_names_the_kind_from_the_margin_up(tmp_path: Path, over: int, named: bool) -> None:
    state = game(tmp_path).state
    s = sighting(
        state, "sudland_galleys", Source.AIR, Confidence.B, GALLEY_CONCEAL + KIND_MARGIN + over
    )
    assert kind_of(state, s) == ("galley" if named else None)


@pytest.mark.parametrize("over", [-1, 0, 1], ids=["under", "at", "over"])
def test_with_the_switch_off_a_search_names_the_kind_as_today(tmp_path: Path, over: int) -> None:
    state = game(tmp_path, switch=False).state
    s = sighting(
        state, "sudland_galleys", Source.AIR, Confidence.B, GALLEY_CONCEAL + KIND_MARGIN + over
    )
    assert kind_of(state, s) == "galley"


def test_concealment_by_order_counts_against_the_margin(tmp_path: Path) -> None:
    state = with_feature(game(tmp_path).state, "sudland_galleys", concealed=True)
    clear = GALLEY_CONCEAL + KIND_MARGIN
    s = sighting(state, "sudland_galleys", Source.AIR, Confidence.B, clear)
    assert kind_of(state, s) is None
    s = sighting(state, "sudland_galleys", Source.AIR, Confidence.B, clear + detect.CONCEAL_BONUS)
    assert kind_of(state, s) == "galley"


@pytest.mark.parametrize(
    ("value", "named"),
    [
        (GALLEY_CONCEAL + KIND_MARGIN - 1, False),
        (GALLEY_CONCEAL + KIND_MARGIN, True),
        (GALLEY_CONCEAL + KIND_MARGIN + 1, True),
    ],
    ids=["under", "at", "over"],
)
def test_an_air_search_reports_the_kind_by_its_searchers_detect(
    tmp_path: Path, value: int, named: bool
) -> None:
    g = game(tmp_path, kite_detect(value), intelligence(norra_sees("air")))
    out = g.walk(day(1), day(30))
    found = reports_of(out, "sudland_galleys", Source.AIR)
    assert found
    assert {r.kind for r in found} == {"galley" if named else None}
    # The levy, with no concealment, is past the margin at every one of these.
    levy = reports_of(out, "sudland_levy", Source.AIR)
    assert levy and {r.kind for r in levy} == {"levy"}


def test_a_sighting_carries_its_best_searchers_detect(tmp_path: Path) -> None:
    g = game(tmp_path, intelligence(norra_sees("air")))
    got = {
        s.detect
        for n in range(1, 30)
        for s in detect.sightings(g.state, g.state, day(n), entity(NORRA))
        if s.source is Source.AIR
    }
    assert got == {60}


def test_a_patrol_short_of_the_margin_names_no_kind(tmp_path: Path) -> None:
    """A galley on patrol (``detect`` 20) against Norra's galleys (``conceal`` 10)."""

    def patrol(switch: bool) -> list[str | None]:
        g = game(
            tmp_path / str(switch),
            norra_galleys_at_sea,
            intelligence(sudland_sees("patrol")),
            switch=switch,
        )
        state = with_feature(g.state, "sudland_galleys", posture=Posture.PATROL)
        return [
            kind_of(state, s, SUDLAND, day(n))
            for n in range(1, 120)
            for s in detect.sightings(state, state, day(n), entity(SUDLAND))
            if s.source is Source.PATROL
        ]

    on, off = patrol(True), patrol(False)
    assert on and set(on) == {None}
    assert off and set(off) == {"galley"}


# --- Rule 1: a sighting with no searching piece, by its confidence -----------------------


def test_contact_in_the_same_area_names_the_kind(tmp_path: Path) -> None:
    g = game(tmp_path, place("sudland_levy", "norrhavn"))
    (r,) = reports_of(g.walk(day(1), day(1)), "sudland_levy", Source.CONTACT)
    assert (r.confidence, r.kind) == (Confidence.A, "levy")


def test_contact_from_a_bordering_area_names_no_kind(tmp_path: Path) -> None:
    g = game(tmp_path)
    found = reports_of(g.walk(day(1), day(5)), "sudland_galleys", Source.CONTACT)
    assert len(found) == 5
    assert {(r.confidence, r.kind) for r in found} == {(Confidence.B, None)}
    assert all(r.strength is not None for r in found)


def test_an_agent_names_the_kind(tmp_path: Path) -> None:
    agents = [{"area": "sudland_coast"}]
    g = game(tmp_path, intelligence(norra_sees("agent", agents=agents)))
    found = reports_of(g.walk(day(1), day(40)), "sudland_levy", Source.AGENT)
    assert found and {(r.confidence, r.kind) for r in found} == {(Confidence.A, "levy")}


def test_a_flight_alone_names_no_kind(tmp_path: Path) -> None:
    """Kites that search nothing by themselves (``detect`` 0) fly a reconnaissance over
    the Gulf: what the flight finds is a sighting at B with no searcher's detect."""
    g = game(tmp_path, kite_detect(0), intelligence(norra_sees("air")))
    gulf = entity("the_gulf")
    hits = []
    for n in range(1, 10):
        state = with_feature(g.state, "norra_kites", recon=gulf, recon_on=day(n))
        hits += [
            s
            for s in detect.sightings(state, state, day(n), entity(NORRA))
            if s.source is Source.AIR
        ]
    assert hits
    assert {(s.confidence, s.detect) for s in hits} == {(Confidence.B, None)}
    assert {kind_of(g.state, s) for s in hits} == {None}


@pytest.mark.parametrize(
    ("confidence", "named"), [(Confidence.A, True), (Confidence.B, False), (Confidence.C, False)]
)
def test_with_no_searcher_the_confidence_decides(
    tmp_path: Path, confidence: Confidence, named: bool
) -> None:
    state = game(tmp_path).state
    s = sighting(state, "sudland_galleys", Source.CONTACT, confidence, None)
    assert kind_of(state, s) == ("galley" if named else None)


# --- Rule 2: broken codes name the kind their source names --------------------------------


def test_a_report_from_broken_codes_names_the_kind(tmp_path: Path) -> None:
    state = game(tmp_path, intelligence(sudland_sees("codebreaking", codebreaking=3))).state
    piece = state.features[fid("norra_levy")]
    s = Sighting(Source.CODEBREAKING, piece, Confidence.C, None, "south", False, None)
    r = detect.report(state, day(1), entity(SUDLAND), s)[0]
    assert (r.confidence, r.kind, r.region) == (Confidence.C, "levy", "south")


# --- Rule 3: the same sighting, the same answer -------------------------------------------


def test_the_same_sighting_names_the_same_kind_every_time(tmp_path: Path) -> None:
    state = game(tmp_path).state
    for over in (-1, 0):
        s = sighting(
            state, "sudland_galleys", Source.AIR, Confidence.B, GALLEY_CONCEAL + KIND_MARGIN + over
        )
        kinds = {kind_of(state, s, on=day(n)) for n in range(1, 120)}
        assert len(kinds) == 1


def test_a_replayed_game_reports_the_same_kinds(tmp_path: Path) -> None:
    def run(name: str) -> list[tuple[FeatureId, str | None]]:
        g = game(tmp_path / name, kite_detect(29), intelligence(norra_sees("air")))
        return [(m.piece, m.report.kind) for m in made(g.walk(day(1), day(20)))]

    first = run("a")
    assert first == run("b")
    assert {k for _, k in first} == {None, "levy"}
