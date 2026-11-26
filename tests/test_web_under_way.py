"""A piece under way says how far along its step it is (MVD).

An own piece under way carries, for the step it is on, the day the step began and the days
it takes; a move in the playback feed carries the days its step took; a refused step keeps
the day it was refused. The days are the step rule's own (``territory.step_days``): the day
a step began is not stored, so it is found as the day whose step, counted with that day's
weather, falls due on the step's due day.

The cases play the territory toy (``tests/worlds/territory-toy.yaml``) as the adjacency
and weather tests play it. It starts on 2 April 1900, and April turns to May on day 29.
Norra's levy stands on the Norra Plain: a step into the Norra Hills takes it 7 days, and
from there a step into the Sudland Coast 5. Sudland's galleys stand in the Gulf, which
borders the plain; a step into the Open Sea takes them 3 days.
"""

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.realism import territory
from revisionist.core.realism.resolvers import apply_changes, movement
from revisionist.core.state import State
from revisionist.engine.catchup import SeatEvent
from revisionist.engine.web import map_api, playback
from revisionist.engine.web import realism_snapshot as rs
from tests import test_adjacency_moves as adj
from tests.test_adjacency_moves import World, day, entity, piece, seat
from tests.test_detection import game as detection_game
from tests.test_detection import intelligence, norra_sees
from tests.test_detection import on as seen_on
from tests.test_weather import APR_30, MAY_1, MONTHS, THAW_HILLS, months, sky, weather
from tests.test_web import Client, web  # noqa: F401
from tests.test_web_playback import caught_up, march  # noqa: F401
from tests.test_web_realism import Realism

KEYS = ("step_began", "step_days")
LEVY = "The Norra Levy"
MUD = weather("mud", slows=[{"days": 2, "pieces": ["land"]}])
"""Two days more on every land step, wherever it holds."""


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(map_api.MARK_SECRET_ENV, "34" * 32)


_dirs = iter(range(1000))


def play(tmp: Path, *changes: Callable[[World], None]) -> State:
    where = tmp / f"w{next(_dirs)}"
    where.mkdir()
    return adj.play(where, adj.levers, *changes)


def course(state: State, name: str = LEVY, who: str = "ilse") -> dict[str, Any]:
    block = rs.seat_realism(state, seat(who), set(), set(), None)
    (mark,) = [m for m in block["map"]["marks"] if m["name"] == name]
    assert mark["piece"] is not None and mark["piece"]["under_way"] is not None, mark
    return dict(mark["piece"]["under_way"])


def progress(state: State, name: str = LEVY) -> tuple[str | None, int | None]:
    found = course(state, name)
    return found["step_began"], found["step_days"]


def on(state: State, when: date) -> State:
    return adj.fold(state, [ev.DateAdvanced(to=when)])


# --- Rule 1: a piece under way carries the day its step began and its days -----------------


def test_a_piece_sent_carries_the_day_its_first_step_began_and_its_days(tmp_path: Path) -> None:
    state = adj.send(play(tmp_path), "ilse", "norra_levy", "sudby")
    found = course(state)
    assert found["step_due"] == day(7).isoformat()
    assert progress(state) == (day(0).isoformat(), 7)


def test_a_piece_sent_on_a_later_day_began_its_step_that_day(tmp_path: Path) -> None:
    state = adj.send(play(tmp_path), "ilse", "norra_levy", "sudby", on=day(3))
    assert progress(state) == (day(3).isoformat(), 7)


def test_each_later_step_begins_the_day_the_one_before_it_ended(tmp_path: Path) -> None:
    state = adj.send(play(tmp_path), "ilse", "norra_levy", "sudby")
    state, stepped = adj.walk(state, day(1), day(8))
    assert [s.on for s in stepped] == [day(7)]
    assert progress(on(state, day(8))) == (day(7).isoformat(), 5)


def test_a_step_the_weather_slows_carries_the_slowed_days(tmp_path: Path) -> None:
    """The plain rate into the hills is 7 days; the thaw adds 2."""
    state = play(tmp_path, sky(THAW_HILLS, mainland=months(apr="thaw")))
    state = adj.send(state, "ilse", "norra_levy", "norra_hills", on=day(3))
    assert piece(state, "norra_levy").step_due == day(3 + 9)
    assert progress(state) == (day(3).isoformat(), 9)


def test_a_step_begun_before_the_month_turns_keeps_its_start_and_days(tmp_path: Path) -> None:
    """Begun on 30 April in the thaw, the step takes 9 days and falls due on 9 May. A step
    begun on 2 May, in fair weather, would fall due that day too: the piece is not moved
    on screen when the weather turns."""
    state = play(tmp_path, sky(THAW_HILLS, mainland=months(apr="thaw")))
    begun = adj.send(state, "ilse", "norra_levy", "norra_hills", on=APR_30)
    assert piece(begun, "norra_levy").step_due == MAY_1 + timedelta(days=8)
    for today in (APR_30, MAY_1, MAY_1 + timedelta(days=3)):
        assert progress(on(begun, today)) == (APR_30.isoformat(), 9)


def test_the_days_are_the_step_rules_own(tmp_path: Path) -> None:
    state = play(tmp_path, sky(MUD, mainland=months(apr="mud")))
    state = adj.send(state, "ilse", "norra_levy", "sudby", on=day(2))
    levy = piece(state, "norra_levy")
    began, days = progress(state)
    assert began == day(2).isoformat()
    assert days == territory.step_days(state, levy, levy.path[0], day(2)) == 9


def test_a_piece_concealed_on_its_way_keeps_the_start_and_days_it_set_out_with(
    tmp_path: Path,
) -> None:
    """Concealed on day 2 (as ``detect.set_concealed`` does it), the levy would take 8
    days a step from now on; the step it is on began on day 0 and takes 7."""
    state = adj.send(play(tmp_path), "ilse", "norra_levy", "sudby")
    levy = piece(state, "norra_levy")
    hidden = levy.model_copy(update={"concealed": True, "as_of": day(2)})
    state = adj.fold(on(state, day(2)), [ev.FeatureSet(feature=hidden)])
    assert territory.step_days(state, hidden, entity("norra_hills"), day(0)) == 8
    assert progress(state) == (day(0).isoformat(), 7)


def test_a_piece_concealed_before_it_set_out_takes_a_day_more(tmp_path: Path) -> None:
    state = play(tmp_path)
    levy = piece(state, "norra_levy")
    state = adj.fold(state, [ev.FeatureSet(feature=levy.model_copy(update={"concealed": True}))])
    state = adj.send(state, "ilse", "norra_levy", "sudby", on=day(1))
    assert piece(state, "norra_levy").step_due == day(1 + 8)
    assert progress(state) == (day(1).isoformat(), 8)


def test_a_piece_standing_still_carries_no_course(tmp_path: Path) -> None:
    block = rs.seat_realism(play(tmp_path), seat("ilse"), set(), set(), None)
    (mark,) = [m for m in block["map"]["marks"] if m["name"] == LEVY]
    assert mark["piece"] is not None and mark["piece"]["under_way"] is None


def test_a_step_no_day_reaches_sends_no_start(tmp_path: Path) -> None:
    """A piece set by hand under way into the hills, which the flood closes to a levy
    every month: no day's step falls due, so neither the start nor the days is sent."""
    flood = weather("flood", closes=[{"pieces": ["levy"], "terrain": ["hills"]}])
    state = play(tmp_path, sky(flood, mainland=months(**dict.fromkeys(MONTHS, "flood"))))
    levy = piece(state, "norra_levy")
    hills = entity("norra_hills")
    under_way = levy.model_copy(
        update={"path": (hills,), "step_due": day(7), "bound_for": hills, "arrives": day(7)}
    )
    state = state.model_copy(update={"features": {**state.features, levy.feature_id: under_way}})
    assert course(state)["step_due"] == day(7).isoformat()
    assert progress(state) == (None, None)


# --- Rule 2: a move in the playback feed carries the days its step took --------------------


def fed(out: list[ev.Event], who: str = "ilse") -> list[SeatEvent]:
    """The events of ``out`` the seat's envelope opens, as the catch-up seam feeds them."""
    return [SeatEvent(wake=1, event=e) for e in out if e.scope.visible_to(seat(who))]


def moves(g: adj.Logged, out: list[ev.Event], who: str = "ilse") -> list[dict[str, Any]]:
    (steps,) = playback.steps(fed(out, who), g.state, seat(who)).values()
    return [dict(s) for s in steps if s["kind"] == "move"]


def logged(tmp: Path, *changes: Callable[[World], None]) -> adj.Logged:
    where = tmp / f"w{next(_dirs)}"
    where.mkdir()
    return adj.Logged(adj.toy(where, *changes), "ilse", "tomas")


def test_each_move_in_the_playback_carries_the_days_its_step_took(tmp_path: Path) -> None:
    g = logged(tmp_path)
    g.send("ilse", "norra_levy", "sudby")
    out = g.walk(day(1), day(13))
    shown = moves(g, out)
    assert [(m["entered"], m["on"], m["days"]) for m in shown] == [
        ("norra_hills", day(7).isoformat(), 7),
        ("sudland_coast", day(12).isoformat(), 5),
    ]


def test_a_move_the_weather_slowed_carries_the_slowed_days(tmp_path: Path) -> None:
    g = logged(tmp_path, sky(THAW_HILLS, mainland=months(apr="thaw")))
    g.send("ilse", "norra_levy", "sudby")
    out = g.walk(day(1), day(16))
    shown = moves(g, out)
    assert [(m["entered"], m["on"], m["days"]) for m in shown] == [
        ("norra_hills", day(9).isoformat(), 9),
        ("sudland_coast", day(14).isoformat(), 5),
    ]


def test_a_later_steps_days_are_counted_from_the_step_before_it(tmp_path: Path) -> None:
    """Sent on 22 April, the levy reaches the hills on 29 April, in the thaw on the plain,
    so the step into the coast takes 7 days and ends on 6 May. A 5-day step begun on
    1 May, in fair weather, would end that day too: the step before it says which."""
    thaw_plain = weather("thaw", slows=[{"days": 2, "terrain": ["plain"]}])
    g = logged(tmp_path, sky(thaw_plain, mainland=months(apr="thaw")))
    g.add([ev.DateAdvanced(to=day(20))])
    sent = adj.order("ilse", "norra_levy", "sudby", day(20))
    g.add(apply_changes(g.state, movement.order_changes(g.state, sent)))
    out = g.walk(day(20), day(40))
    shown = moves(g, out)
    assert [(m["entered"], m["on"], m["days"]) for m in shown] == [
        ("norra_hills", day(27).isoformat(), 7),
        ("sudland_coast", day(34).isoformat(), 7),
    ]


def test_each_piece_carries_its_own_kinds_days(tmp_path: Path) -> None:
    """Norra's levy and kites step into the hills, 7 days and 1; Sudland's galleys into
    the open sea, 3."""
    g = logged(tmp_path)
    g.send("ilse", "norra_levy", "norra_hills")
    g.send("ilse", "norra_kites", "norra_hills")
    g.send("tomas", "sudland_galleys", "open_sea")
    out = g.walk(day(1), day(8))
    assert [(m["on"], m["days"]) for m in moves(g, out, "ilse")] == [
        (day(1).isoformat(), 1),
        (day(7).isoformat(), 7),
    ]
    assert [m["days"] for m in moves(g, out, "tomas")] == [3]


def test_the_catch_up_plays_every_held_wakes_moves_with_their_days(
    march: tuple[Realism, Client],  # noqa: F811
) -> None:
    """Served: Ilse's player comes back after a wake away and reads its moves, the herald's
    record leg and the levy's two steps, each with its days."""
    _, fresh = march
    (page,) = caught_up(fresh)
    shown = [(s["entered"], s["days"]) for s in page["steps"] if s["kind"] == "move"]
    assert shown == [("the_gulf", 2), ("norra_hills", 7), ("sudland_coast", 5)]


# --- Rule 3: a refused step carries the day it was refused ---------------------------------


def test_a_refused_step_carries_the_day_it_was_refused(tmp_path: Path) -> None:
    g = logged(tmp_path)
    g.send("ilse", "norra_levy", "sudby")
    out = g.walk(day(1), day(7))
    levy = piece(g.state, "norra_levy")
    mark = territory.mark_key(g.state, entity("norra"), levy)
    refused = ev.StepRefused(
        mark=mark,
        nation=entity("norra"),
        area=levy.places[0],
        to=entity("sudland_coast"),
        on=day(9),
        reason="Too little fuel.",
    )
    g.add([ev.DateAdvanced(to=day(9)), refused])
    (steps,) = playback.steps(fed([*out, g.log[-1]]), g.state, seat("ilse")).values()
    (halt,) = [dict(s) for s in steps if s["kind"] == "halt"]
    assert halt["on"] == day(9).isoformat()
    assert halt["to"] == "sudland_coast"
    assert not set(KEYS) & set(halt) and "days" not in halt


# --- The fog: another nation's piece gains nothing ------------------------------------------


def _carriers(node: Any, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """The paths in ``node`` of every object carrying a progress key."""
    found: list[tuple[str, ...]] = []
    if isinstance(node, dict):
        if set(KEYS) & set(node) or ("days" in node and node.get("kind") == "move"):
            found.append(path)
        for k, v in node.items():
            found += _carriers(v, (*path, str(k)))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += _carriers(v, (*path, str(i)))
    return found


def test_a_report_of_another_nations_piece_under_way_carries_no_progress(tmp_path: Path) -> None:
    """Norra's levy and kites, on the plain, see Sudland's galleys in the bordering Gulf
    on day 1, the day after both nations set a piece under way."""
    g = detection_game(tmp_path / "fog", adj.levers, intelligence(norra_sees("contact")))
    g.send("ilse", "norra_levy", "sudby")
    g.send("tomas", "sudland_galleys", "open_sea")
    g.walk(day(1), day(1))
    seen_on(g, day(2))
    assert piece(g.state, "sudland_galleys").path, "the galleys are under way"
    shown = rs.seat_realism(g.state, seat("ilse"), set(), set(), None)["map"]
    (report,) = shown.get("reports", [])
    assert report["kind"] == "galley"
    assert not set(KEYS) & set(report) and "days" not in report
    for p in _carriers(json.loads(json.dumps(shown))):
        assert p[0] == "marks", p
        mark = shown["marks"][int(p[1])]
        assert mark["side"] == "own", p
    (levy,) = [m for m in shown["marks"] if m["name"] == LEVY]
    assert levy["piece"]["under_way"]["step_began"] == day(0).isoformat()
    assert all(m["piece"] is None for m in shown["marks"] if m["side"] != "own")
