"""The Civil War plays a whole season under the same rules (CWP).

A scripted two-seat Union game on the shipped ``worlds/civil-war-1862.yaml``: Lincoln at the
head and McClellan with the Army of the Potomac. The script body is the 1941 commanders'
script (``tests/commanders_script.py``) with only the data changed: the opening's three
answers, the order the lock holds, and the head's order that opens it. Every reply is canned;
no model is reached. This file changes no rule: a failure here is a finding against the rule
that fails, not a change to make in it.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import SeatId
from revisionist.core.ontology import Phase
from revisionist.core.realism import territory
from tests import test_salt_strait_plays as ssp
from tests.async_table import answer_days, digest, papers
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


# --- Rule 3: invariants 2, 3 and 4 on the Civil War ------------------------------------
# The same checks ``tests/test_salt_strait_plays.py`` plays on Salt Strait, through its
# ``Game`` and the Civil War cast; only each seat's three forms are this world's.

Step = ssp.Step
WAKES = ssp.INVARIANT_WAKES
CAST = ssp.CIVIL_WAR


def attacker_files(g: ssp.Game, n: int) -> None:
    """Wake 0 the march on Washington, wake 1 the balloon to cover, wake 2 its recall."""
    form = (CAST.march, CAST.cover, CAST.recall)[n]
    assert form is not None
    g.form(g.attacker, form, f"attacker:{n}")


def defender_files(g: ssp.Game, n: int) -> None:
    """Wake 0 the balloon, wake 1 the army's standing order, wake 2 a bill to Congress."""
    if n == 0:
        g.form(g.defender, CAST.recon, "defender:0")
    elif n == 1:
        body = {"force": CAST.defender_force, "kind": "withdraw_below", "below": 3}
        g.contingency(g.defender, body, "defender:1")
    else:
        bill = ("send_bill", {"bill": "us_emancipation_measure", "urgency": "ordinary"})
        g.form(g.defender, bill, "defender:2")


def files(who: Callable[[ssp.Game], SeatId]) -> Step:
    return lambda g, n: (attacker_files if who(g) == g.attacker else defender_files)(g, n)


def commits(who: Callable[[ssp.Game], SeatId]) -> Step:
    return lambda g, n: g.commit(who(g))


def attacker(g: ssp.Game) -> SeatId:
    return g.attacker


def defender(g: ssp.Game) -> SeatId:
    return g.defender


def test_2_away_looks_like_present_and_quiet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Davis files the same three wakes with Lincoln away, then present and quiet: Davis's
    papers match in shape and his answers in day."""
    seen: dict[str, tuple[Any, Any]] = {}
    for lincoln_is in ("away", "present"):
        with monkeypatch.context() as m:
            g = ssp.Game(CAST, tmp_path / lincoln_is, m)
            script: list[Step] = [files(attacker), commits(attacker)]
            if lincoln_is == "present":
                script.append(ssp.quiet(defender))
            ssp.run_wakes(g, script)
            aide = (g.defender,) if lincoln_is == "away" else ()
            assert [c.timed_out for c in g.logged(ev.WakeClosed)] == [aide] * WAKES
            seen[lincoln_is] = (papers(g.state, g.attacker), answer_days(g.state, g.attacker))
    away, present = seen["away"], seen["present"]
    assert away[0], "Davis holds papers"
    assert away[0] == present[0], "Davis's papers differ in shape"
    assert away[1] == present[1], "Davis's answer days differ"


def attacker_in_sittings(sittings: int) -> Step:
    """Davis reads his papers at each of ``sittings`` sittings and files his form at the
    fourth; Lincoln files and commits between them."""

    def wake(g: ssp.Game, n: int) -> None:
        for s in range(sittings):
            g.sitting(g.attacker)
            if s == 3:
                attacker_files(g, n)
            if s == 1:
                defender_files(g, n)
            if s == sittings - 2:
                g.commit(g.defender)
        g.commit(g.attacker)

    return wake


ATTACKER_FIRST: list[Step] = [
    files(attacker),
    commits(attacker),
    files(defender),
    commits(defender),
]
DEFENDER_FIRST: list[Step] = [
    files(defender),
    commits(defender),
    files(attacker),
    commits(attacker),
]


def alternating(g: ssp.Game, n: int) -> None:
    for step in DEFENDER_FIRST if n % 2 else ATTACKER_FIRST:
        step(g, n)


def held_back(g: ssp.Game, n: int) -> None:
    """The control: Davis leaves out his last wake's form."""
    if n < WAKES - 1:
        attacker_files(g, n)
    g.commit(g.attacker)
    defender_files(g, n)
    g.commit(g.defender)


PRESENCE: dict[str, list[Step]] = {
    "attacker commits first": ATTACKER_FIRST,
    "defender commits first": DEFENDER_FIRST,
    "the order alternates": [alternating],
    "attacker in ten sittings": [attacker_in_sittings(10)],
}


def test_3_presence_buys_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Three wakes with the commit order permuted, and with Davis filing over ten sittings:
    the same outcome digest. The control files one form fewer and differs."""
    digests: dict[str, str] = {}
    filed: dict[str, int] = {}
    for name, script in {**PRESENCE, "control": [held_back]}.items():
        with monkeypatch.context() as m:
            g = ssp.run_wakes(ssp.Game(CAST, tmp_path / name.replace(" ", "-"), m), script)
            filed[name] = len([o for o in g.state.orders.values() if o.issuer == g.attacker])
            assert [c.timed_out for c in g.logged(ev.WakeClosed)] == [()] * WAKES
            digests[name] = digest(g.state)
    first = digests["attacker commits first"]
    assert digests.pop("control") != first
    assert {name: d for name, d in digests.items() if d != first} == {}
    assert filed == {name: 2 if name == "control" else 3 for name in filed}


def test_4_the_offers_land_with_nobody_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The deadline tick closes the first wake with both seats played by the aide, and the
    next wake's offers land for both."""
    g = ssp.Game(CAST, tmp_path, monkeypatch, offline=True)
    g._tick()
    g.deadline()
    (closed,) = g.logged(ev.WakeClosed)
    assert set(closed.timed_out) == {g.defender, g.attacker}
    assert {p.seat_id for p in g.logged(ev.OptionsOffered) if p.wake == 1} == {
        g.defender,
        g.attacker,
    }
