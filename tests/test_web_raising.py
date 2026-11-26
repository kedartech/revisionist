"""Raising as the seat sees it, with its check (RNR).

The toy world of ``tests/test_raising.py``: ``territories``, ``holders``, ``economy`` and
``raising`` on; the Hillfort, in the Norra Hills, is an air base of Norra's that raises fire
kites (10 output and 1 manpower, 30 days), and with ``levies_raised`` Norrhavn, in the Norra
Plain, a land base that raises levies (10 and 1, 20 days). Ilse, Norra's chancellor, holds
the form ``raise_piece``, whose order passes one step of one day. Norra's pools are 50
output and 5 manpower.

Worked example (rules 1 and 2): on day 0 Ilse's economy block lists the Hillfort, where fire
kites would arrive on day 31 (one day for the step, thirty for the kind) and leave the pools
at 40 and 4. Once an order to raise levies at Norrhavn is enacted, due on day 20, the block
lists that raising with its day, and the fire kites would leave the pools at 30 and 3.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, derived_id
from revisionist.core.realism import territory
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.resolvers import production
from revisionist.core.state import State
from revisionist.engine import catchup, realism_tick, wake_report
from revisionist.engine.web import catchup_api, locks_api, map_api, playback
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests.test_adjacency_moves import START, Logged, entity, seat
from tests.test_raising import (
    KITE,
    LEVY,
    NORRA,
    SUDLAND,
    base,
    cut_off,
    day,
    enact,
    game,
    levies_raised,
    off,
    pipeline,
    sudland_raises,
    walk_days,
    with_supply,
)
from tests.test_realism_command import general
from tests.test_territory_model import CAMPAIGN

FIXTURES = Path(__file__).parents[1] / "web" / "test" / "fixtures"
DEADLINE = datetime(2030, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(map_api.MARK_SECRET_ENV, "34" * 32)


def realism(state: State, who: str = "ilse") -> dict[str, Any]:
    return rs.seat_realism(state, seat(who), set(), set(), None)


def own(state: State, who: str = "ilse") -> dict[str, Any]:
    block = realism(state, who)["economy"]
    assert block is not None and block["own"] is not None
    return dict(block["own"])


def places(state: State, who: str = "ilse") -> dict[str, dict[str, Any]]:
    return {p["place"]: p for p in own(state, who)["places"]}


def kinds(state: State, place: str, who: str = "ilse") -> dict[str, dict[str, Any]]:
    return {k["kind"]: k for k in places(state, who)[place]["kinds"]}


def iso(n: int) -> str:
    return day(n).isoformat()


# --- Rule 1: each place that can raise, its kinds, costs, days and the pools after ---------


def test_a_seat_holding_the_form_sees_each_place_and_what_it_would_raise_there(
    tmp_path: Path,
) -> None:
    state = game(tmp_path, levies_raised).state
    shown = places(state)
    assert sorted(shown) == ["hillfort", "norrhavn"]
    hill = shown["hillfort"]
    assert (hill["name"], hill["area"], hill["form"]) == (
        "The Hillfort",
        "norra_hills",
        "raise_piece",
    )
    assert kinds(state, "hillfort") == {
        KITE: {
            "kind": KITE,
            "name": "Fire Kites",
            "cost": {"output": 10, "manpower": 1},
            "lead_days": 30,
            "arrives": iso(31),
            "pools_after": {"output": 40.0, "manpower": 4.0},
            "refusal": "",
        }
    }
    levy = kinds(state, "norrhavn")[LEVY]
    assert (levy["lead_days"], levy["arrives"], shown["norrhavn"]["area"]) == (
        20,
        iso(21),
        "norra_plain",
    )


def test_the_pools_after_take_off_an_earlier_order_still_due(tmp_path: Path) -> None:
    g = game(tmp_path, levies_raised)
    enact(g, kind=LEVY, place="norrhavn")
    kite = kinds(g.state, "hillfort")[KITE]
    assert kite["pools_after"] == {"output": 30.0, "manpower": 3.0}


def test_a_raising_due_after_the_arrival_leaves_the_pools_after_alone(tmp_path: Path) -> None:
    g = game(tmp_path, levies_raised)
    enact(g)
    g.add([ev.DateAdvanced(to=day(5))])
    levy = kinds(g.state, "norrhavn")[LEVY]
    assert levy["arrives"] == iso(26)
    assert levy["pools_after"] == {"output": 40.0, "manpower": 4.0}


def test_a_place_that_cannot_raise_now_carries_the_checks_words(tmp_path: Path) -> None:
    busy = game(tmp_path / "busy")
    enact(busy)
    assert kinds(busy.state, "hillfort")[KITE]["refusal"] == production.BUSY
    cut = game(tmp_path / "cut", levies_raised, with_supply, cut_off)
    assert kinds(cut.state, "norrhavn")[LEVY]["refusal"] == production.NO_SUPPLY


def test_a_place_with_no_base_of_the_seats_own_is_not_listed(tmp_path: Path) -> None:
    assert places(game(tmp_path / "land", base("hillfort", "land")).state) == {}
    theirs = game(tmp_path / "theirs", base("hillfort", "air", sides=[SUDLAND])).state
    assert places(theirs) == {}


def test_a_seat_without_the_form_is_shown_no_place(tmp_path: Path) -> None:
    state = game(tmp_path, general, people=("ilse", "tomas", "kara")).state
    assert own(state, "kara")["places"] == []
    assert sorted(places(state)) == ["hillfort"]


def test_with_raising_off_the_block_is_as_before(tmp_path: Path) -> None:
    state = game(tmp_path, levies_raised, rules=off).state
    assert set(own(state)) == {"nation", "income", "pools", "fuel_months", "territories"}


# --- Rules 2 and 4: the pieces being raised, each with its place and its day -------------


def test_the_block_lists_each_piece_being_raised_with_its_place_and_day(tmp_path: Path) -> None:
    g = game(tmp_path, levies_raised)
    enact(g, kind=LEVY, place="norrhavn")
    (line,) = own(g.state)["raising"]
    assert line == {
        "kind": LEVY,
        "name": "Levy",
        "place": "norrhavn",
        "place_name": "Norrhavn",
        "area": "norra_plain",
        "day": iso(20),
        "fixed": True,
        "picture": None,
    }
    assert date.fromisoformat(line["day"]) == day(20)
    walk_days(g, 1, 20)
    assert own(g.state)["raising"] == []


def test_a_piece_being_raised_carries_its_kinds_picture(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g)
    (line,) = own(g.state)["raising"]
    assert (line["kind"], line["picture"]) == (KITE, "bombers")


def test_an_order_still_on_its_way_is_listed_with_the_day_it_would_arrive(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "moving", 1)),
        issuer=seat("ilse"),
        lever="raise_piece",
        pipeline=pipeline(g, "ilse"),
        params={"kind": KITE, "place": "hillfort"},
        filed=START,
    )
    g.add([ev.OrderDrafted(order=order)])
    (line,) = own(g.state)["raising"]
    assert (line["day"], line["fixed"]) == (iso(31), False)


def test_every_seat_of_the_nation_sees_its_raisings(tmp_path: Path) -> None:
    g = game(tmp_path, general, people=("ilse", "tomas", "kara"))
    enact(g)
    assert [r["place"] for r in own(g.state, "kara")["raising"]] == ["hillfort"]


def test_no_other_nations_seat_gets_a_place_a_cost_or_a_raising(tmp_path: Path) -> None:
    g = game(tmp_path, levies_raised, sudland_raises)
    enact(g)
    enact(g, kind=LEVY, place="norrhavn", n=2)
    theirs = own(g.state, "tomas")
    assert sorted(p["place"] for p in theirs["places"]) == ["sudby"]
    assert theirs["raising"] == []
    said = json.dumps(theirs)
    for word in ("hillfort", "norrhavn", "Hillfort", "Norrhavn", LEVY):
        assert word not in said


# --- Rule 3: the check before sending, equal to what filing does --------------------------


def draft(kind: str = KITE, place: str = "hillfort") -> dict[str, str]:
    return {"kind": kind, "place": place}


def filed(g: Logged, given: dict[str, str]) -> str:
    """What filing ``given`` now does: the refusal's words, or empty when it is filed."""
    try:
        order = realism_tick.draft_order(g.state, seat("ilse"), "raise_piece", given)
    except ValueError as exc:
        return str(exc)
    landing, _ = realism_tick.form_filing(g.state, seat("ilse"), order)
    assert landing
    return ""


def cases(tmp: Path) -> list[tuple[Logged, dict[str, str], str]]:
    busy = game(tmp / "busy")
    enact(busy)
    return [
        (game(tmp / "ok"), draft(), ""),
        (game(tmp / "land", base("hillfort", "land")), draft(), production.NO_BASE),
        (
            game(tmp / "theirs", base("hillfort", "air", sides=[SUDLAND])),
            draft(),
            production.NOT_YOURS,
        ),
        (
            game(tmp / "cut", levies_raised, with_supply, cut_off),
            draft(LEVY, "norrhavn"),
            production.NO_SUPPLY,
        ),
        (busy, draft(), production.BUSY),
    ]


def test_the_check_answers_allowed_or_why_not_in_fixed_words(tmp_path: Path) -> None:
    for g, given, why in cases(tmp_path):
        got = locks_api.check_form(g.state, seat("ilse"), "raise_piece", given)
        want = {"check": "allowed" if not why else "beyond", "who": None, "reason": why}
        assert got == want, why


def test_the_check_and_the_block_say_what_filing_then_does_in_every_case(
    tmp_path: Path,
) -> None:
    for g, given, why in cases(tmp_path):
        assert locks_api.check_form(g.state, seat("ilse"), "raise_piece", given)["reason"] == why
        listed = places(g.state).get(given["place"])
        if listed is not None:
            (shown,) = [k for k in listed["kinds"] if k["kind"] == given["kind"]]
            assert shown["refusal"] == why
        assert filed(g, given) == why


# --- Rule 5: the wake report ---------------------------------------------------------


def wakes(g: Logged, last: int) -> None:
    """Wake 0 opens and closes, the world walks to day ``last`` and wake 1 opens."""
    g.add([ev.WakeOpened(wake=0, deadline=DEADLINE), ev.WakeClosed(wake=0)])
    g.add([ev.DateAdvanced(to=day(last))])
    g.walk(day(1), day(last))
    g.add([ev.WakeOpened(wake=1, deadline=DEADLINE)])


def test_the_wake_report_counts_pieces_raised_and_raisings_that_failed(tmp_path: Path) -> None:
    g = game(tmp_path, levies_raised)
    enact(g)
    enact(g, place="norrhavn", n=2)
    wakes(g, 35)
    report = wake_report.build(g.log)
    assert [(r.number, r.raised, r.failed) for r in report.raising] == [(0, 1, 1), (1, 0, 0)]
    assert "    raising: 1 raised, 1 failed" in wake_report.render(report)


def test_with_raising_off_the_wake_report_has_no_raising_line(tmp_path: Path) -> None:
    g = game(tmp_path, rules=off)
    enact(g)
    wakes(g, 35)
    report = wake_report.build(g.log)
    assert report.raising == ()
    assert not any("raising" in line for line in wake_report.render(report))


# --- Rule 6: a piece raised is a step in the playback ------------------------------------


def played(g: Logged, who: str) -> dict[int, list[Any]]:
    fed = catchup.feed(g.state, g.log, seat(who), 0, 1)
    return playback.steps(fed, g.state, seat(who), None, playback.raised(g.log, g.state, seat(who)))


def raised_steps(steps: dict[int, list[Any]]) -> list[tuple[int, dict[str, Any]]]:
    return [(w, s) for w, found in steps.items() for s in found if s["kind"] == "raised"]


def test_a_piece_raised_is_a_step_with_its_place_and_day_for_its_nations_seats(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, general, people=("ilse", "tomas", "kara"))
    enact(g)
    wakes(g, 35)
    (new,) = [f for f in g.state.features.values() if f.name == "Fire Kites 1"]
    norra = entity(NORRA)
    key = map_api.mark_key(CAMPAIGN, norra, territory.mark_key(g.state, norra, new))
    for who in ("ilse", "kara"):
        ((wake, step),) = raised_steps(played(g, who))
        assert wake == 1
        assert step == {
            "kind": "raised",
            "on": iso(30),
            "piece": key,
            "name": "Fire Kites 1",
            "place": "The Hillfort",
            "area": "norra_hills",
        }
    assert raised_steps(played(g, "tomas")) == []


def test_the_raised_step_is_in_the_wake_of_its_report(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g)
    wakes(g, 35)
    steps = played(g, "ilse")
    ((wake, step),) = raised_steps(steps)
    papers = [(w, s) for w, found in steps.items() for s in found if s["kind"] == "paper"]
    assert [(w, s["title"]) for w, s in papers] == [(wake, "Raised: Fire Kites 1")]
    assert papers[0][1]["on"] == step["on"]


def test_the_raised_step_rides_the_catchup_page(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g)
    wakes(g, 35)
    pages = catchup_api.reply(g.state, g.log, seat("ilse"), {"first": 0, "last": 1})["pages"]
    steps = {p["number"]: [s["kind"] for s in p["steps"]] for p in pages}
    assert "raised" in steps[1]


def test_a_raising_that_failed_makes_no_raised_step(tmp_path: Path) -> None:
    g = game(tmp_path, levies_raised, with_supply, cut_off)
    enact(g, kind=LEVY, place="norrhavn")
    wakes(g, 35)
    assert raised_steps(played(g, "ilse")) == []


# --- The shapes --------------------------------------------------------------------


def fixture_game(tmp: Path) -> State:
    """The game the seat fixture's ``raising_economy`` is Ilse's block of: both bases, an
    order to raise levies at Norrhavn enacted on day 0."""
    g = game(tmp, levies_raised)
    enact(g, kind=LEVY, place="norrhavn")
    return g.state


def shape(examples: list[Any], kind: Any) -> None:
    assert examples
    for example in examples:
        assert set(example) == set(kind.__annotations__), kind.__name__


def test_the_seat_fixture_carries_a_raising_economy_block_in_the_snapshot_shape(
    tmp_path: Path,
) -> None:
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["raising_economy"]
    assert fixture == realism(fixture_game(tmp_path))["economy"]
    mine = fixture["own"]
    assert {"places", "raising"} <= set(mine)
    shape(mine["places"], api.RaisePlace)
    shape([k for p in mine["places"] for k in p["kinds"]], api.RaiseKind)
    shape(mine["raising"], api.RaisingLine)
    assert api.EconomyOwn.__optional_keys__ == {"places", "raising"}
    assert set(api.PlaybackRaised.__annotations__) == {
        "kind",
        "on",
        "piece",
        "name",
        "place",
        "area",
    }
