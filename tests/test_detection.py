"""Detection: every known enemy piece is a report (DET).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories`` and
``reports`` on, every force given a strength. Norra's levy and kites stand on the Norra
Plain; Sudland's levy stands on the Sudland Coast and its galleys in the Gulf, which
borders the plain. A test that needs sources gives the world an ``intelligence``.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.project import project
from revisionist.core.realism import detect
from revisionist.core.realism.detect import (
    STALE_DAYS,
    Confidence,
    Picture,
    Report,
    Shift,
    Source,
)
from revisionist.core.realism.effect import Posture
from revisionist.core.state import State, View
from revisionist.core.visibility import Visibility
from revisionist.core.world import WorldFile
from revisionist.engine import catchup
from tests.test_adjacency_moves import (
    START,
    Logged,
    World,
    day,
    entity,
    order,
    piece,
    seat,
)
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_territory_model import refused

TIERS = {"norra_levy": 4, "sudland_levy": 3, "sudland_galleys": 2, "norra_kites": 1}
NORRA, SUDLAND = "norra", "sudland"


def rules(*names: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = list(names)

    return change


def strengths(w: World) -> None:
    for f in w["features"]:
        f["tier"] = TIERS.get(f["key"], 1)


def intelligence(*decls: dict[str, Any]) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["intelligence"] = list(decls)

    return change


def place(key: str, at: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        (found,) = [f for f in w["features"] if f["key"] == key]
        found["places"] = [at]

    return change


def roads(w: World) -> None:
    """A place in the Open Sea."""
    w["entities"].append(
        {"key": "open_roads", "kind": "location", "name": "The Open Roads", "at": [180, 215]}
    )
    w["entities"][-1]["within"] = "open_sea"


def open_roads(w: World) -> None:
    """A place in the Open Sea, and a Norra galley there."""
    roads(w)
    w["features"].append(
        {
            "key": "norra_galleys",
            "kind": "piece",
            "piece": "galley",
            "name": "The Norra Galleys",
            "side": "norra",
            "places": ["open_roads"],
            "tier": 2,
            "source": "toy",
        }
    )


def toy(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    """The toy world with territories and reports on, every force given a strength."""
    return territories_toy(tmp, rules("territories", "reports"), strengths, *changes)


def norra_sees(*sources: str, channel: str = "telephone", **more: Any) -> dict[str, Any]:
    return {
        "nation": NORRA,
        "sources": [{"source": s, "person": "ilse", "channel": channel} for s in sources],
        **more,
    }


def sudland_sees(*sources: str, channel: str = "telephone", **more: Any) -> dict[str, Any]:
    return {
        "nation": SUDLAND,
        "sources": [{"source": s, "person": "tomas", "channel": channel} for s in sources],
        **more,
    }


def game(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    tmp.mkdir(parents=True, exist_ok=True)
    return Logged(toy(tmp, *changes), "ilse", "tomas")


def made(out: list[ev.Event]) -> list[ev.ReportMade]:
    return [e.payload for e in out if isinstance(e.payload, ev.ReportMade)]


def on(g: Logged, when: date) -> None:
    """The game's date moved to ``when``, as a wake's advance moves it."""
    g.add([ev.DateAdvanced(to=when)])


def view(g: Logged, person: str) -> View:
    return project(g.state, seat(person))


def fid(key: str) -> FeatureId:
    return FeatureId(entity(key))


def sightings_over(
    state: State, nation: str, days: range, start: State | None = None
) -> list[tuple[int, Source, FeatureId]]:
    out = []
    for n in days:
        for s in detect.sightings(state, start or state, day(n), entity(nation)):
            out.append((n, s.source, s.force.feature_id))
    return out


def with_feature(state: State, key: str, **update: Any) -> State:
    f = state.features[fid(key)]
    return state.model_copy(
        update={"features": {**state.features, f.feature_id: f.model_copy(update=update)}}
    )


# --- Rule 1: at most one report per enemy piece, with its fields -------------------------


def test_a_piece_in_the_same_area_is_reported_exactly_with_confidence_a(tmp_path: Path) -> None:
    g = game(tmp_path, place("sudland_levy", "norrhavn"))
    (r,) = [m.report for m in made(g.walk(day(1), day(1))) if m.piece == fid("sudland_levy")]
    assert r.source is Source.CONTACT and r.confidence is Confidence.A
    assert (r.kind, r.strength, r.area) == ("levy", (3, 3), entity("norra_plain"))
    assert r.seen == day(1) and r.arrives == day(1)


def test_a_nation_holds_one_report_per_enemy_piece(tmp_path: Path) -> None:
    g = game(tmp_path, place("sudland_levy", "norrhavn"), intelligence(norra_sees("air")))
    g.walk(day(1), day(6))
    on(g, day(6))
    mine = view(g, "ilse").reports
    keys = [detect.report_key(g.state, entity(NORRA), fid(k)) for k in TIERS if "sudland" in k]
    assert sorted(mine) == sorted(keys)


# --- Rule 2: the key is opaque and per nation -------------------------------------------


def test_a_reports_key_never_carries_the_pieces_id_and_differs_by_nation(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.walk(day(1), day(1))
    on(g, day(1))
    norra_key = detect.report_key(g.state, entity(NORRA), fid("sudland_galleys"))
    other = detect.report_key(g.state, entity("sudland"), fid("sudland_galleys"))
    assert norra_key != other
    seen = view(g, "ilse")
    assert norra_key in seen.reports
    text = seen.model_dump_json()
    assert str(fid("sudland_galleys")) not in text


# --- Rule 4: contact ----------------------------------------------------------------


def test_a_piece_in_a_bordering_area_is_reported_by_kind_and_strength_within_one(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    reports = [m.report for m in made(g.walk(day(1), day(8))) if m.piece == fid("sudland_galleys")]
    assert len(reports) == 8
    for r in reports:
        assert r.confidence is Confidence.B and r.kind == "galley"
        lo, hi = r.strength or (0, 0)
        assert lo <= 2 <= hi and 1 <= hi - lo <= 2  # never the true figure alone
    assert any(r.strength != (1, 3) for r in reports)  # the range is not always centred


def test_a_far_piece_no_source_covers_is_not_reported(tmp_path: Path) -> None:
    g = game(tmp_path)
    out = made(g.walk(day(1), day(5)))
    assert not [m for m in out if m.piece == fid("sudland_levy") and m.nation == entity(NORRA)]


# --- Rule 5: air search ---------------------------------------------------------------


def test_air_search_reports_a_piece_in_range_at_detect_less_conceal(tmp_path: Path) -> None:
    g = game(tmp_path, intelligence(norra_sees("air")))
    state = g.state
    got = [(n, p) for n, s, p in sightings_over(state, NORRA, range(1, 61)) if s is Source.AIR]
    want = []
    for n in range(1, 61):
        for key, chance in (("sudland_galleys", 60 - 10), ("sudland_levy", 60)):
            if detect.roll(state, day(n), entity(NORRA), "air", str(fid(key))) < chance:
                want.append((n, fid(key)))
    assert sorted(got) == sorted(want) and got


def test_air_search_needs_a_named_person(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert not [x for x in sightings_over(g.state, NORRA, range(1, 30)) if x[1] is Source.AIR]


# --- Rule 6: patrol -------------------------------------------------------------------


def test_a_sea_piece_on_patrol_covers_its_zone_and_the_zones_beside_it(tmp_path: Path) -> None:
    g = game(tmp_path, open_roads, intelligence(sudland_sees("patrol")))
    resting = sightings_over(g.state, SUDLAND, range(1, 200))
    assert not [x for x in resting if x[1] is Source.PATROL]
    state = with_feature(g.state, "sudland_galleys", posture=Posture.PATROL)
    got = [
        (n, p) for n, s, p in sightings_over(state, SUDLAND, range(1, 200)) if s is Source.PATROL
    ]
    want = [
        (n, fid("norra_galleys"))
        for n in range(1, 200)
        if detect.roll(state, day(n), entity(SUDLAND), "patrol", str(fid("norra_galleys"))) < 10
    ]
    assert got == want and got


# --- Rule 7: codebreaking --------------------------------------------------------------


def test_codebreaking_reports_a_move_begun_that_day_with_its_region_and_no_strength(
    tmp_path: Path,
) -> None:
    from revisionist.core.realism.resolvers import apply_changes, movement

    g = game(tmp_path, intelligence(sudland_sees("codebreaking", codebreaking=3)))
    before = g.state
    from tests.test_adjacency_moves import fold

    after = fold(
        before,
        apply_changes(before, movement.order_changes(before, order("ilse", "norra_levy", "sudby"))),
    )
    hits = []
    for n in range(1, 120):
        found = [
            s
            for s in detect.sightings(after, before, day(n), entity(SUDLAND))
            if s.source is Source.CODEBREAKING
        ]
        roll = detect.roll(after, day(n), entity(SUDLAND), "codebreaking", str(fid("norra_levy")))
        assert bool(found) == (roll < 40)
        hits += found
    assert hits
    r, _ = detect.report(after, day(1), entity(SUDLAND), hits[0])
    assert (r.confidence, r.strength, r.area, r.region) == (Confidence.C, None, None, "south")
    # A piece already under way as the day began has begun no move.
    assert not [
        s
        for n in range(1, 120)
        for s in detect.sightings(after, after, day(n), entity(SUDLAND))
        if s.source is Source.CODEBREAKING
    ]


@pytest.mark.parametrize(("level", "chance"), [(0, 0), (1, 10), (2, 25), (3, 40)])
def test_the_codebreaking_chance_is_set_by_the_level(level: int, chance: int) -> None:
    assert detect.CODEBREAKING_CHANCE[level] == chance


# --- Rule 8: agents -------------------------------------------------------------------


def test_an_agent_reports_one_piece_in_its_area_a_day_exactly(tmp_path: Path) -> None:
    agents = [{"area": "sudland_coast"}]
    g = game(tmp_path, intelligence(norra_sees("agent", agents=agents)))
    state = g.state
    got = [(n, p) for n, s, p in sightings_over(state, NORRA, range(1, 60)) if s is Source.AGENT]
    rolls = [
        n
        for n in range(1, 60)
        if detect.roll(state, day(n), entity(NORRA), "agent", f"0\x1f{entity('sudland_coast')}")
        < detect.AGENT_CHANCE
    ]
    assert got == [(n, fid("sudland_levy")) for n in rolls] and got
    s = next(
        s
        for s in detect.sightings(state, state, day(rolls[0]), entity(NORRA))
        if s.source is Source.AGENT
    )
    assert (s.confidence, s.exact) == (Confidence.A, True)


def test_an_agent_reports_nothing_after_its_last_day(tmp_path: Path) -> None:
    agents = [{"area": "sudland_coast", "until": str(day(0))}]
    g = game(tmp_path, intelligence(norra_sees("agent", agents=agents)))
    assert not [x for x in sightings_over(g.state, NORRA, range(1, 60)) if x[1] is Source.AGENT]


# --- Rule 9: the named person, the channel and the page ----------------------------------


def test_a_report_arrives_after_its_channels_days_on_a_page_from_the_person(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, intelligence(norra_sees("contact", channel="letter")))
    out = g.walk(day(1), day(1))
    (m,) = [m for m in made(out) if m.nation == entity(NORRA)]
    assert m.report.arrives == day(3) and m.report.rank == 1
    pages = [e for e in out if isinstance(e.payload, ev.DocumentIssued)]
    (page,) = pages
    doc = page.payload.document  # type: ignore[union-attr]
    assert doc.author == entity("ilse") and doc.issued == day(1) and doc.arrives == day(3)
    assert page.scope.known_by == frozenset({seat("ilse")})
    labels = [b.label for b in doc.body]
    assert labels == ["Kind", "Strength", "Area", "Seen", "Confidence"]
    assert doc.body[0].value == "Galley"


def test_the_world_checks_its_intelligence(tmp_path: Path) -> None:
    bad = refused(
        toy(
            tmp_path,
            intelligence(
                {
                    "nation": "ilse",
                    "sources": [{"source": "air", "person": "norra", "channel": "radio"}],
                },
                {"nation": NORRA, "agents": [{"area": "norrhavn"}]},
            ),
        )
    )
    assert "intelligence ilse: ilse is not a polity" in bad
    assert "intelligence ilse: norra is not a person" in bad
    assert "intelligence norra: agent in norrhavn, not an area of the board" in bad
    off = refused(territories_toy(tmp_path, rules("territories"), intelligence(norra_sees("air"))))
    assert "intelligence: needs the reports rule" in off
    alone = refused(territories_toy(tmp_path, rules("reports")))
    assert "rules: reports needs territories" in alone


# --- Rule 10: a report can be wrong -----------------------------------------------------


def _wrong_game(tmp: Path, skew: int = 0) -> Logged:
    def careless(w: World) -> None:
        for c in w["cards"]:
            c["competence"] = 0
        w["intelligence"][0]["sources"][0]["skew"] = skew

    return game(tmp, intelligence(norra_sees("contact")), careless)


def test_a_careless_persons_report_is_sometimes_shifted_and_nothing_in_it_says_so(
    tmp_path: Path,
) -> None:
    g = _wrong_game(tmp_path)
    state = g.state
    (s,) = detect.sightings(state, state, day(1), entity(NORRA))
    results = [detect.report(state, day(n), entity(NORRA), s._replace()) for n in range(1, 300)]
    shifts = [shift for _, shift in results if shift is not None]
    assert Shift.STRENGTH in shifts and Shift.AREA in shifts
    assert 0.03 < len(shifts) / len(results) < 0.2  # 10 percent at competence 0
    wrong = next(r for r, shift in results if shift is Shift.AREA)
    assert wrong.area != entity("the_gulf")
    assert "shift" not in Report.model_fields
    assert "shift" not in View.model_fields


def test_a_competent_persons_reports_are_never_wrong(tmp_path: Path) -> None:
    def able(w: World) -> None:
        for c in w["cards"]:
            c["competence"] = 5

    g = game(tmp_path, intelligence(norra_sees("contact")), able)
    (s,) = detect.sightings(g.state, g.state, day(1), entity(NORRA))
    assert all(detect.report(g.state, day(n), entity(NORRA), s)[1] is None for n in range(1, 200))


def test_a_persons_skew_shifts_every_range_one_way(tmp_path: Path) -> None:
    plain, skewed = _wrong_game(tmp_path / "a"), _wrong_game(tmp_path / "b", skew=1)
    (s,) = detect.sightings(plain.state, plain.state, day(1), entity(NORRA))
    (t,) = detect.sightings(skewed.state, skewed.state, day(1), entity(NORRA))
    for n in range(1, 60):
        a, sa = detect.report(plain.state, day(n), entity(NORRA), s)
        b, _ = detect.report(skewed.state, day(n), entity(NORRA), t)
        if sa is None and a.strength is not None and b.strength is not None:
            assert b.strength[1] == min(a.strength[1] + 1, 3)


# --- Rule 11: pending and delivered ------------------------------------------------------


def _r(key: str, seen: int, arrives: int, source: Source = Source.AIR, rank: int = 1) -> Report:
    return Report(
        key=key,
        kind="levy",
        strength=(1, 3),
        area=EntityId("a" * 26),
        seen=day(seen),
        source=source,
        rank=rank,
        confidence=Confidence.B,
        arrives=day(arrives),
    )


def _picture(*reports: Report) -> Picture:
    p = Picture()
    for r in reports:
        p = detect.made(p, r)
    return p


def test_a_slower_newer_sighting_replaces_the_delivered_one_only_on_arrival() -> None:
    old = _r("k", 1, 1, Source.CONTACT, 0)
    slow = _r("k", 2, 5)
    p = _picture(old, slow)
    for n in (2, 3, 4):
        assert detect.received(p, day(n)).delivered == {"k": old}
    assert detect.received(p, day(5)).delivered == {"k": slow}


def test_an_older_report_arriving_late_replaces_nothing() -> None:
    late = _r("k", 1, 6)
    fresh = _r("k", 3, 3, Source.CONTACT, 0)
    p = _picture(late, fresh)
    for n in range(3, 10):
        assert detect.received(p, day(n)).delivered == {"k": fresh}


def test_two_sources_on_one_day_keep_the_higher_ranked_whatever_the_order() -> None:
    first, second = _r("k", 2, 2, Source.AIR, 1), _r("k", 2, 2, Source.PATROL, 2)
    assert _picture(first, second).delivered == {"k": first}
    assert _picture(second, first).delivered == {"k": first}


def test_a_pending_report_never_removes_an_arrived_one() -> None:
    held = _r("k", 1, 1, Source.CONTACT, 0)
    p = _picture(held, _r("j", 2, 9))
    for n in range(1, 9):
        assert detect.received(p, day(n)).delivered == {"k": held}


def test_a_delivered_report_older_than_the_stale_days_is_dropped() -> None:
    p = _picture(_r("k", 1, 1))
    assert detect.received(p, day(1 + STALE_DAYS)).delivered
    assert not detect.received(p, day(2 + STALE_DAYS)).delivered


def test_the_view_is_byte_identical_until_a_pending_report_arrives(tmp_path: Path) -> None:
    quiet = game(tmp_path / "a")
    heard = game(
        tmp_path / "b",
        intelligence(norra_sees("agent", channel="courier", agents=[{"area": "sudland_coast"}])),
    )
    rolls = [
        n
        for n in range(1, 30)
        if detect.roll(
            heard.state, day(n), entity(NORRA), "agent", f"0\x1f{entity('sudland_coast')}"
        )
        < detect.AGENT_CHANCE
    ]
    first = rolls[0]
    quiet.walk(day(1), day(first))
    out = heard.walk(day(1), day(first))
    (m,) = [m for m in made(out) if m.report.source is Source.AGENT]
    assert m.report.arrives == day(first + 5)
    for n in range(first, first + 5):
        on(quiet, day(n))
        on(heard, day(n))
        assert view(heard, "ilse").reports == view(quiet, "ilse").reports
        a = project(quiet.state, seat("ilse")).model_dump_json()
        b = project(heard.state, seat("ilse")).model_dump_json()
        assert a == b
    on(heard, day(first + 5))
    key = detect.report_key(heard.state, entity(NORRA), fid("sudland_levy"))
    assert view(heard, "ilse").reports[key].source is Source.AGENT
    assert key not in view(quiet, "ilse").reports


# --- Rule 12: the view holds nothing else about enemy pieces -------------------------------


def test_the_view_has_no_field_for_pieces() -> None:
    assert "features" not in View.model_fields and "reports" in View.model_fields


@settings(
    max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(tier=st.integers(1, 3), far=st.booleans())
def test_an_undetected_pieces_strength_and_area_change_no_view(
    tmp_path: Path, tier: int, far: bool
) -> None:
    """Norra's forces in the hills see the plain and the coast; Sudland's galleys, in the
    Gulf or the Open Sea, border neither."""

    def hillfort(w: World) -> None:
        w["entities"].append(
            {"key": "hillfort", "kind": "location", "name": "Hillfort", "at": [150, 100]}
        )
        w["entities"][-1]["within"] = "norra_hills"
        for f in w["features"]:
            if f["key"] in ("norra_levy", "norra_kites"):
                f["places"] = ["hillfort"]

    def moved(w: World) -> None:
        (f,) = [f for f in w["features"] if f["key"] == "sudland_galleys"]
        f["tier"] = tier
        f["places"] = ["open_roads" if far else "gulf_roads"]

    base = game(tmp_path / "base", roads, hillfort)
    other = game(tmp_path / f"o{tier}{far}", roads, hillfort, moved)
    for g in (base, other):
        g.walk(day(1), day(4))
        on(g, day(4))
    assert view(base, "ilse").model_dump_json() == view(other, "ilse").model_dump_json()


# --- Rule 13: gated by reports; no intelligence, contact only --------------------------------


def test_a_world_without_the_reports_rule_makes_no_report(tmp_path: Path) -> None:
    g = Logged(territories_toy(tmp_path, rules("territories"), strengths), "ilse", "tomas")
    out = g.walk(day(1), day(5))
    assert not made(out)
    on(g, day(5))
    assert view(g, "ilse").reports == {}
    assert "reports" not in json.loads(g.state.model_dump_json())


def test_a_world_with_no_intelligence_has_contact_only(tmp_path: Path) -> None:
    g = game(tmp_path)
    sources = {m.report.source for m in made(g.walk(day(1), day(10)))}
    assert sources == {Source.CONTACT}


# --- Invariant 3: filing order and sittings change no report -----------------------------


def test_filing_order_and_sittings_change_no_report(tmp_path: Path) -> None:
    sources = intelligence(norra_sees("air"), sudland_sees("codebreaking", codebreaking=3))

    def run(order_: list[tuple[str, str, str]], cuts: list[int]) -> list[Any]:
        g = game(tmp_path / f"{len(cuts)}{order_[0][0]}", sources)
        for by, force, to in order_:
            g.send(by, force, to)
        first = 1
        out: list[Any] = []
        for last in cuts:
            out += [m.model_dump() for m in made(g.walk(day(first), day(last)))]
            first = last + 1
        return out

    a = [("ilse", "norra_levy", "sudby"), ("tomas", "sudland_galleys", "open_sea")]
    one = run(a, [12])
    assert one == run(list(reversed(a)), [12])
    assert one == run(a, [3, 7, 12])


def test_the_roll_reads_only_the_campaign_the_day_the_nation_the_source_and_the_piece(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    args = (g.state, day(3), entity(NORRA), "air", "x")
    assert detect.roll(*args) == detect.roll(*args)
    assert detect.roll(g.state.model_copy(update={"last_seq": 999}), *args[1:]) == detect.roll(
        *args
    )


# --- The day walk and catch-up -----------------------------------------------------------


def test_reports_are_engine_only_and_never_fed(tmp_path: Path) -> None:
    g = game(tmp_path, intelligence(norra_sees("contact")))
    out = g.walk(day(1), day(2))
    for e in out:
        if isinstance(e.payload, ev.ReportMade):
            assert e.scope.visibility is Visibility.RESTRICTED
            assert not e.scope.visible_to(seat("ilse")) and not e.scope.visible_to(seat("tomas"))
    assert "report_made" in catchup.NEVER and "intelligence_declared" in catchup.NEVER
    on(g, day(2))
    fed = catchup.feed(g.state, g.log, seat("ilse"), 0, 50)
    kinds = {f.event.kind for f in fed}
    assert "report_made" not in kinds and "document_issued" in kinds


def test_the_intelligence_is_declared_once_and_sealed(tmp_path: Path) -> None:
    g = game(tmp_path, intelligence(norra_sees("air", "agent", codebreaking=2)))
    (e,) = [e for e in g.log if isinstance(e.payload, ev.IntelligenceDeclared)]
    assert e.scope.visibility is Visibility.RESTRICTED
    assert not e.scope.visible_to(seat("ilse"))
    intel = g.state.intelligence[entity(NORRA)]
    assert [(s.source, s.rank) for s in intel.sources] == [(Source.AIR, 1), (Source.AGENT, 2)]
    assert intel.codebreaking == 2


def test_the_day_walk_rolls_after_the_press_and_moves_the_piece_first(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.send("tomas", "sudland_levy", "norrhavn")
    out = g.walk(day(1), day(20))
    entered = next(
        e.payload.on
        for e in out
        if isinstance(e.payload, ev.PieceStepped) and e.payload.entered == entity("norra_hills")
    )
    seen = [
        m.report
        for m in made(out)
        if m.piece == fid("sudland_levy") and m.nation == entity(NORRA) and m.report.seen == entered
    ]
    assert seen and seen[0].area == entity("norra_hills")
    assert piece(g.state, "sudland_levy").places[0] in {
        entity("norra_hills"),
        entity("norra_plain"),
    }
    assert START < entered
