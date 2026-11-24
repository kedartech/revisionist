"""The home front as the seat sees it (HFR).

Played on GPD's floor game (``tests/test_web_groups.py``) and PLW's places game. The
seat's last wake is its player's last commit. The ``home`` block opens on what moved
since: each group that moved, by how much and why, one line each, heaviest first. Each
vote of a measure on its way shows its count at that wake beside today's, with the blocs
that moved marked. Each place of political weight is a line with its holder, marked when
its area on the seat's map is threatened. A general's seat sees the same sheet as his
nation's politician. All of it is read from the seat's own view.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ontology import Controller
from revisionist.core.realism import groups
from revisionist.core.realism.groups import Cause, Happening
from revisionist.core.realism.holders import Capture
from revisionist.engine import catchup
from revisionist.engine.web import home_api, playback
from tests.test_adjacency_moves import START, Logged, entity, seat
from tests.test_happening_classes import classed
from tests.test_happening_classes import game as classes_game
from tests.test_losses_at_home import COAST
from tests.test_losses_at_home import game as losses_game
from tests.test_places_weight import PLAIN, day
from tests.test_places_weight import game as places_game
from tests.test_web_groups import (
    NORRA,
    SUDLAND,
    World,
    bill,
    by_key,
    fixture_game,
    game,
    home,
    moved,
    realism,
)

DEADLINE = datetime(1900, 4, 30, tzinfo=UTC)


def wake(g: Logged, n: int = 0, who: str = "ilse", by_aide: bool = False) -> None:
    """``who`` commits wake ``n``, opened first if it is not the wake open now."""
    w = g.state.wake
    if w is None or w.number != n:
        if w is not None and not w.closed:
            g.add([ev.WakeClosed(wake=w.number)])
        g.add([ev.WakeOpened(wake=n, deadline=DEADLINE)])
    g.add([ev.WakeCommitted(wake=n, seat_id=seat(who), by_aide=by_aide)])


def lines(g: Logged, who: str = "ilse") -> list[str]:
    return [m["line"] for m in home(g, who)["moved"]]


def groups_moved(g: Logged, who: str = "ilse") -> list[str]:
    return [m["group"] for m in home(g, who)["moved"]]


def the_vote(g: Logged) -> dict[str, Any]:
    (vote,) = home(g)["chambers"][0]["measures"][0]["votes"]
    return dict(vote)


# --- Rule 1: what moved since the seat's last wake ------------------------------------


def test_the_sheet_lists_only_the_moves_since_the_seats_last_wake(tmp_path: Path) -> None:
    g = game(tmp_path)
    moved(g, "greens", 5, Cause.BATTLE_WON, START)
    wake(g)
    moved(g, "public", -2, Cause.TERRITORY_LOST, date(1900, 4, 4))
    shown = home(g)
    assert [m["group"] for m in shown["moved"]] == ["public"]
    assert by_key(shown["groups"])["greens"]["since"] == []
    assert by_key(shown["groups"])["public"]["since"] == [
        {
            "cause": "territory_lost",
            "change": -2,
            "on": "1900-04-04",
            "why": "territory lost",
            "reach": "reported",
        }
    ]


def test_each_group_is_one_line_with_its_net_change_heaviest_first(tmp_path: Path) -> None:
    g = game(tmp_path)
    wake(g)
    moved(g, "greens", 2, Cause.WRITING, START)
    moved(g, "public", -6, Cause.TERRITORY_LOST, date(1900, 4, 4))
    moved(g, "greens", 3, Cause.BATTLE_WON, date(1900, 4, 5))
    moved(g, "greys", -1, Cause.DRIFT, date(1900, 4, 9))
    assert lines(g) == [
        "The Norra Public -6: territory lost",
        "The Greens +5: a battle won and 1 more",
        "The Greys -1: the weekly drift",
    ]
    assert [m["change"] for m in home(g)["moved"]] == [-6, 5, -1]


def test_a_seat_with_no_wake_yet_sees_every_move_since_the_start(tmp_path: Path) -> None:
    assert groups_moved(fixture_game(tmp_path)) == ["greens", "public"]


def test_an_aides_commit_is_not_the_seats_wake(tmp_path: Path) -> None:
    g = game(tmp_path)
    wake(g, 0)
    moved(g, "greens", 5, Cause.BATTLE_WON, START)
    wake(g, 1, by_aide=True)
    moved(g, "public", -2, Cause.TERRITORY_LOST, date(1900, 4, 4))
    assert groups_moved(g) == ["greens", "public"]


def test_a_new_player_taking_the_seat_up_starts_from_nothing_seen(tmp_path: Path) -> None:
    g = game(tmp_path)
    moved(g, "greens", 5, Cause.BATTLE_WON, START)
    wake(g)
    g.add([ev.SessionZeroClosed()])
    g.add([ev.SeatHandover(entity_id=entity("ilse"), controller=Controller.AI)])
    g.add([ev.SeatHandover(entity_id=entity("ilse"), controller=Controller.HUMAN)])
    assert groups_moved(g) == ["greens"]


def test_another_seats_wake_is_not_this_seats(tmp_path: Path) -> None:
    g = game(tmp_path)
    moved(g, "greens", 5, Cause.BATTLE_WON, START)
    wake(g, who="tomas")
    g.add([ev.SessionZeroClosed()])
    g.add([ev.SeatHandover(entity_id=entity("tomas"), controller=Controller.AI)])
    g.add([ev.SeatHandover(entity_id=entity("tomas"), controller=Controller.HUMAN)])
    assert groups_moved(g) == ["greens"]


def test_a_move_the_clamp_held_to_nothing_draws_no_line(tmp_path: Path) -> None:
    g = game(tmp_path)
    moved(g, "greens", 100, Cause.WRITING, START)
    wake(g)
    moved(g, "greens", 3, Cause.WAR_DECLARED, date(1900, 4, 6))
    assert home(g)["moved"] == []


def test_every_cause_reads_in_plain_words() -> None:
    assert set(home_api.WHY) == {c.value for c in Cause}


def test_every_cause_says_how_it_reached_the_public() -> None:
    assert set(home_api.REACH) | {h.value for h in Happening} == {c.value for c in Cause}
    # Battle losses are mixed: their move that day is the reported share, the felt share
    # lands later as its own cause.
    assert set(home_api.REACH) & {h.value for h in Happening} == {"battle_losses"}


def test_each_move_says_whether_it_was_felt_or_reported(tmp_path: Path) -> None:
    g = game(tmp_path)
    moved(g, "public", -3, Cause.BATTLE_LOSSES, date(1900, 4, 3))
    moved(g, "public", -1, Cause.LOSSES_FELT, date(1900, 4, 4))
    moved(g, "greens", 2, Cause.TERRITORY_TAKEN, date(1900, 4, 4))
    since = {g_["key"]: g_["since"] for g_ in home(g)["groups"]}
    assert [(m["cause"], m["reach"]) for m in since["public"]] == [
        ("battle_losses", "reported"),
        ("losses_felt", "felt"),
    ]
    # A happening the world does not class is reported (HCL, ``groups.cls``).
    assert [(m["cause"], m["reach"]) for m in since["greens"]] == [("territory_taken", "reported")]


def test_no_other_nations_move_reaches_the_sheet(tmp_path: Path) -> None:
    g = game(tmp_path)
    moved(g, "farmers", 7, Cause.BATTLE_WON, date(1900, 4, 5), polity=SUDLAND)
    moved(g, "greens", 1, Cause.WRITING, date(1900, 4, 5))
    assert lines(g) == ["The Greens +1: a statement"]
    assert lines(g, "tomas") == ["The Farmers +7: a battle won"]
    assert "Greens" not in json.dumps(home(g, "tomas"))
    assert "Farmers" not in json.dumps(home(g))


def test_a_moved_line_names_only_moves_the_server_logged(tmp_path: Path) -> None:
    g = game(tmp_path)
    wake(g)
    moved(g, "greys", 4, Cause.MEASURE_PASSED, date(1900, 4, 5))
    shown = home(g)
    logged = {
        (p.group, p.change)
        for p in (e.payload for e in g.log)
        if isinstance(p, ev.GroupMoved) and p.polity == NORRA
    }
    assert {(m["group"], m["change"]) for m in shown["moved"]} <= logged
    assert shown["moved"] == [
        {
            "group": "greys",
            "name": "The Greys",
            "change": 4,
            "line": "The Greys +4: a measure passed",
        }
    ]


# --- Rule 2: each measure's count now beside its count then ---------------------------


def test_a_vote_shows_its_count_at_the_last_wake_and_marks_the_blocs_that_moved(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    bill(g, "levy_act")
    wake(g)
    before = {b["group"]: [b["yeas"], b["nays"]] for b in the_vote(g)["blocs"]}
    moved(g, "greys", 25, Cause.WRITING, START)
    vote = the_vote(g)
    blocs = by_key(vote["blocs"], "group")
    assert blocs["greys"]["then"] == before["greys"]
    assert [blocs["greys"]["yeas"], blocs["greys"]["nays"]] != before["greys"]
    assert blocs["greys"]["moved"] is True
    assert blocs["greens"]["then"] == before["greens"]
    assert blocs["greens"]["moved"] is False
    assert vote["then"] == [sum(c[0] for c in before.values()), sum(c[1] for c in before.values())]


def test_a_vote_nothing_moved_since_the_wake_marks_no_bloc(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g, "levy_act")
    wake(g)
    vote = the_vote(g)
    assert vote["then"] == [vote["yeas"], vote["nays"]]
    assert not any(b["moved"] for b in vote["blocs"])


def test_a_measure_filed_after_the_last_wake_has_no_count_then(tmp_path: Path) -> None:
    g = game(tmp_path)
    wake(g)
    bill(g, "levy_act")
    vote = the_vote(g)
    assert vote["then"] is None
    assert all(b["then"] is None and b["moved"] is False for b in vote["blocs"])


def test_with_no_wake_yet_there_is_no_count_then(tmp_path: Path) -> None:
    assert the_vote(fixture_game(tmp_path))["then"] is None


# --- Rule 3: each place of political weight, its holder and the threat ----------------


def test_each_place_of_weight_is_a_line_with_its_holder(tmp_path: Path) -> None:
    (place,) = home(places_game(tmp_path))["places"]
    assert (place["key"], place["name"]) == ("norra_plain", "The Norra Plain")
    assert place["holder"] is not None and place["holder"]["key"] == NORRA
    assert place["holder"]["relation"] == "own"
    assert place["threatened"] is False


def test_a_place_marked_to_fall_is_marked_threatened(tmp_path: Path) -> None:
    g = places_game(tmp_path)
    mark = Capture(by=SUDLAND, since=day(1), marked=1, marked_on=day(3))
    g.state = g.state.model_copy(update={"captures": {**g.state.captures, PLAIN: mark}})
    (place,) = home(g)["places"]
    assert place["threatened"] is True
    area = next(a for a in realism(g)["map"]["areas"] if a["key"] == "norra_plain")
    assert area["falling"] is not None


def test_another_nations_places_are_not_on_the_sheet(tmp_path: Path) -> None:
    assert home(places_game(tmp_path), "tomas")["places"] == []


def test_without_places_the_list_is_empty(tmp_path: Path) -> None:
    assert home(fixture_game(tmp_path))["places"] == []


# --- A general sees his nation's moves -------------------------------------------------


def general(w: World) -> None:
    """Hald, a Norra general on a playable card."""
    w["entities"].append({"key": "hald", "kind": "person", "name": "Hald Rune", "parent": "norra"})
    w["cards"].append(
        {
            "person": "hald",
            "office": "General of the Norra Army",
            "playable": True,
            "principals": ["norra"],
            "horizon_days": 14,
            "post_kind": "army_commander",
        }
    )
    w["roster"].append(
        {"entity": "hald", "pitch": "The general.", "reach": "The army.", "composite": True}
    )


def test_a_generals_seat_sees_his_nations_moves_as_his_politician_does(tmp_path: Path) -> None:
    g = game(tmp_path, general)
    g.add([ev.CharacterClaimed(seat_id=seat("hald"), entity_id=entity("hald"))])
    moved(g, "greens", 5, Cause.BATTLE_WON, START)
    bill(g, "levy_act")
    wake(g)
    wake(g, who="hald")
    moved(g, "public", -2, Cause.TERRITORY_LOST, date(1900, 4, 4))
    general_sees, politician_sees = home(g, "hald"), home(g, "ilse")
    assert general_sees["moved"] != []
    for key in ("moved", "groups", "places"):
        assert general_sees[key] == politician_sees[key]


# --- Twin worlds: another nation's moves change nothing the seat reads -------------------


def hidden(g: Logged) -> None:
    """The fact Ilse may not know: Sudland's Farmers moved by a battle Norra did not see."""
    moved(g, "farmers", 9, Cause.BATTLE_WON, date(1900, 4, 3), polity=SUDLAND)
    moved(g, "farmers", -4, Cause.PLACE_LOST, date(1900, 4, 4), polity=SUDLAND)


def twin(tmp: Path, with_hidden: bool) -> Logged:
    tmp.mkdir(exist_ok=True)
    g = game(tmp)
    bill(g, "levy_act")
    wake(g)
    moved(g, "greens", 10, Cause.BATTLE_WON, date(1900, 4, 3))
    if with_hidden:
        hidden(g)
    moved(g, "public", -2, Cause.TERRITORY_LOST, date(1900, 4, 4))
    wake(g, 1)
    return g


def test_twin_worlds_differing_in_another_nations_moves_give_the_seat_the_same(
    tmp_path: Path,
) -> None:
    plain, other = twin(tmp_path / "a", False), twin(tmp_path / "b", True)
    for key in ("moved", "groups", "chambers", "places"):
        assert home(plain)[key] == home(other)[key], key
    assert played(plain) == played(other)
    assert played(plain, "tomas") == []
    assert [s["group"] for s in played(other, "tomas") if s["kind"] == "group"] == [
        "farmers",
        "farmers",
    ]


# --- Rule 4: the playback carries the home front's moves and count changes ---------------


def played(g: Logged, who: str = "ilse") -> list[dict[str, Any]]:
    """Every step of the seat's catch-up over every wake so far, in order."""
    assert g.state.wake is not None
    fed = catchup.feed(g.state, g.log, seat(who), 0, g.state.wake.number)
    by_wake = playback.steps(fed, g.state, seat(who))
    return [dict(s) for w in sorted(by_wake) for s in by_wake[w]]


def home_steps(g: Logged, who: str = "ilse") -> list[dict[str, Any]]:
    return [s for s in played(g, who) if s["kind"] in ("group", "count")]


def test_the_playback_carries_each_own_group_move_and_the_count_it_changed(
    tmp_path: Path,
) -> None:
    g = twin(tmp_path, False)
    order_id = next(iter(g.state.orders))
    assert home_steps(g) == [
        {
            "kind": "group",
            "on": "1900-04-03",
            "group": "greens",
            "name": "The Greens",
            "change": 10,
            "support": 65,
            "why": "a battle won",
            "reach": "reported",
        },
        {
            "kind": "count",
            "on": "1900-04-03",
            "order_id": order_id,
            "key": "levy_act",
            "title": "Levy act",
            "vote": "assembly",
            "yeas": 92,
            "nays": 108,
            "was": [90, 110],
        },
        # The Public is no bloc: its move changes no count.
        {
            "kind": "group",
            "on": "1900-04-04",
            "group": "public",
            "name": "The Norra Public",
            "change": -2,
            "support": 38,
            "why": "territory lost",
            "reach": "reported",
        },
    ]


def test_each_count_step_is_the_votes_rules_count_then_and_now(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g, "levy_act")
    wake(g)
    moved(g, "greens", 10, Cause.BATTLE_WON, date(1900, 4, 3))
    moved(g, "greys", 15, Cause.WRITING, date(1900, 4, 4))
    counts = [s for s in home_steps(g) if s["kind"] == "count"]
    vote = the_vote(g)
    assert counts[0]["was"] == vote["then"]
    assert [counts[-1]["yeas"], counts[-1]["nays"]] == [vote["yeas"], vote["nays"]]
    assert [c["was"] for c in counts[1:]] == [[c["yeas"], c["nays"]] for c in counts[:-1]]


def test_another_nations_move_is_never_fed_nor_a_step(tmp_path: Path) -> None:
    g = game(tmp_path)
    wake(g)
    # Logged under a public envelope here, so the seam's own guard is what holds.
    moved(g, "farmers", 7, Cause.BATTLE_WON, date(1900, 4, 3), polity=SUDLAND)
    wake(g, 1)
    assert g.state.wake is not None
    fed = catchup.feed(g.state, g.log, seat("ilse"), 0, g.state.wake.number)
    assert [f for f in fed if f.event.kind == "group_moved"] == []
    assert home_steps(g) == []
    assert "Farmers" not in json.dumps(played(g))
    assert [s["group"] for s in home_steps(g, "tomas")] == ["farmers"]


def test_a_move_the_clamp_held_to_nothing_is_no_step(tmp_path: Path) -> None:
    g = game(tmp_path)
    moved(g, "greens", 100, Cause.WRITING, START)
    wake(g)
    moved(g, "greens", 3, Cause.WAR_DECLARED, date(1900, 4, 6))
    wake(g, 1)
    assert [s for s in home_steps(g) if s["on"] == "1900-04-06"] == []


# --- A cause is worded from the move alone, never from a hidden battle's truth -----------


def battle(tmp: Path, reported: int, felt: int) -> Logged:
    """Norra's losses in a battle at the coast: the move the public saw (three points by
    report) is the same; the losses the engine holds (engine only) are not."""
    g = losses_game(tmp)
    wake(g)
    held = groups.HeldLoss(
        polity=NORRA,
        group="public",
        area=COAST,
        opened=day(1),
        on=day(1),
        reported=reported,
        felt=felt,
    )
    g.add([ev.LossesHeld(on=day(1), held=(held,))])
    moved(g, "public", -3, Cause.BATTLE_LOSSES, day(1))
    return g


def test_twin_battles_differing_in_their_hidden_losses_give_the_same_words(
    tmp_path: Path,
) -> None:
    small, large = battle(tmp_path / "a", -3, -1), battle(tmp_path / "b", -3, -9)
    words = [m for g in home(small)["groups"] for m in g["since"]]
    assert words == [
        {
            "cause": "battle_losses",
            "change": -3,
            "on": day(1).isoformat(),
            "why": "battle losses reported",
            "reach": "reported",
        }
    ]
    assert [m for g in home(large)["groups"] for m in g["since"]] == words
    for g in (small, large):
        wake(g, 1)
    assert home(small)["moved"] == home(large)["moved"]
    assert home_steps(small) == home_steps(large) != []


def test_a_move_by_a_happening_the_world_classes_as_felt_says_felt(tmp_path: Path) -> None:
    g = classes_game(tmp_path, classed({"kind": "territory_lost", "reach": "felt"}))
    moved(g, "public", -2, Cause.TERRITORY_LOST, START)
    moved(g, "public", 1, Cause.BATTLE_WON, START)
    since = [(m["cause"], m["reach"]) for gr in home(g)["groups"] for m in gr["since"]]
    assert since == [("territory_lost", "felt"), ("battle_won", "reported")]
    wake(g)
    wake(g, 1)
    assert [s["reach"] for s in home_steps(g) if s["kind"] == "group"] == ["felt", "reported"]


def test_the_playback_drops_another_nations_move_its_seam_let_through(tmp_path: Path) -> None:
    """The playback's own guard: given the whole log, unfiltered, as the seam's twin does
    (``tests/test_web_playback.py``), it still makes no step of Sudland's move for Ilse."""
    g = game(tmp_path)
    wake(g)
    moved(g, "farmers", 7, Cause.BATTLE_WON, date(1900, 4, 3), polity=SUDLAND)
    moved(g, "greens", 2, Cause.BATTLE_WON, date(1900, 4, 3))
    everything = [catchup.SeatEvent(wake=0, event=e) for e in g.log]
    steps = playback.steps(everything, g.state, seat("ilse")).get(0, [])
    assert [s["group"] for s in steps if s["kind"] == "group"] == ["greens"]
