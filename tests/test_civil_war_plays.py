"""The Civil War plays a whole season under the same rules (CWP).

A scripted two-seat Union game on the shipped ``worlds/civil-war-1862.yaml``: Lincoln at the
head and McClellan with the Army of the Potomac. The script body is the 1941 commanders'
script (``tests/commanders_script.py``) with only the data changed: the opening's three
answers, the order the lock holds, and the head's order that opens it. Every reply is canned;
no model is reached. This file changes no rule: a failure here is a finding against the rule
that fails, not a change to make in it.
"""

from collections.abc import Iterator

import pytest

from revisionist.core import events as ev
from revisionist.core.ontology import Phase
from revisionist.core.realism import territory
from tests.commanders_script import Game, Nation, Script
from tests.locked_orders_script import shipped

WORLD = "civil-war-1862"

UNION = Nation(
    key="usa",
    commander="mcclellan",
    head="lincoln",
    order=("march", {"force": "army_of_the_potomac", "to": "manassas"}),
    row="potomac_advance",
    allow=(("send_bill", {"bill": "us_emancipation_measure", "urgency": "ordinary"}),),
)
"""The Union cast: the commander files the march the Potomac lock holds; the head's
posture order for the eastern theatre opens it."""


@pytest.fixture(scope="module")
def union(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Game]:
    """The Union season, played once for the module."""
    with pytest.MonkeyPatch.context() as m:
        g = Game(UNION, tmp_path_factory.mktemp("union"), m, world=shipped(WORLD))
        g.play(Script(to_season_end=True))
        yield g


def test_the_opening_seats_the_general_by_name(union: Game) -> None:
    _, path, name = union.picked
    assert (path, name) == ("military", "George B. McClellan")


def test_the_season_runs_from_its_first_day_to_its_end(union: Game) -> None:
    s = union.state
    assert s.phase is Phase.SEASON_OVER
    assert s.in_world_date is not None and s.in_world_date.isoformat() == "1862-12-15"
    assert len(union.logged(ev.SeasonEnded)) == 1


def test_pieces_move_by_adjacency(union: Game) -> None:
    board = union.state.map
    assert board is not None
    stepped = union.logged(ev.PieceStepped)
    assert stepped
    assert all(territory.adjacent(board, p.left, p.entered) for p in stepped)


def test_battles_are_fought_and_their_losses_move_the_groups(union: Game) -> None:
    assert union.logged(ev.BattleOpened)
    assert union.logged(ev.BattleEnded)
    held = union.logged(ev.LossesHeld)
    assert held
    moved = {str(m.cause) for m in union.logged(ev.GroupMoved)}
    assert {"battle_losses", "battle_won"} & moved, moved


def test_the_locked_order_is_held_and_asked_for(union: Game) -> None:
    (held,) = union.logged(ev.OrderHeld)
    (asked,) = union.logged(ev.OrderAsked)
    assert asked.asked.order_id == held.held.order_id
    assert union.played.allowed, "the head files the order that opens the lock"


def test_the_election_redraws_the_chamber(union: Game) -> None:
    assert union.logged(ev.SeatsRedrawn)


def test_aims_are_scored_at_the_seasons_end(union: Game) -> None:
    assert union.logged(ev.GoalSet)
    assert union.logged(ev.GoalMet)
