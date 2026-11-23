"""The locked-orders game (LKG): the scripted proof of the slice, on 1941, on the toy and
on Salt Strait (SSO).

The script (``tests/locked_orders_script.py``) plays a whole season with the leader and his
commander both seated, through the engine's own entry points and offline. Each test reads
one run of it. The runs are played once per module and kept, since a 1941 season takes
some seconds.

Rule 1, lock 1: the commander's order is held; he asks; the leader's naval order crosses
the middle step (pinned by the seed, below) and the commander's own desk; the held order
lands. Rule 2, lock 2: held; asked; the leader's bill passes the floor on its date by the
blocs' votes; the law is in force; the held order lands. Rule 3: without the leader's
moves both stay held to the season's end. Rule 4: both seats move the commander's force
in one wake and the leader's order stands (replacing the commander's where both first act
on the same day, as on the toy world; acting after it in 1941, see ``Cast.meets``).
Rule 5: the commander absent, his step on the leader's order passes on its day. Rule 6:
the season ends and scores by the seats' aims.
"""

from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.goals import AimStatus, season_winners
from revisionist.core.ids import FeatureId
from revisionist.core.ontology import Phase
from revisionist.core.project import project
from revisionist.core.realism import locks, process
from revisionist.core.realism.pipeline import ADVANCES, OrderStatus, StepAction
from revisionist.core.realism.pipelines import REPLACED
from revisionist.core.realism.resolvers import qid
from revisionist.core.world_compile import object_id
from revisionist.engine.web.stakes import seat_stakes
from tests.locked_orders_script import (
    CASTS,
    NINETEEN_41,
    SALT_STRAIT,
    TOY,
    Cast,
    Game,
    Script,
    digest,
    ends,
    known,
    landed_as,
    steps_at,
)

SCRIPTS: dict[str, Script] = {
    "full": Script(),
    "again": Script(),
    "restart": Script(restart_at=1, retry_at=1),
    "none": Script(posture=False, bill=False),
    "absent": Script(commander_present=False),
    "both": Script(posture=False, bill=False, both_move=True),
}
"""Every run the tests read. ``restart``: in the second wake every seat repeats what it
did, then the close stops after the pipelines and resumes from a store rebuilt from the
log."""

PINNED: dict[str, tuple[StepAction, int]] = {
    NINETEEN_41.name: (StepAction.EXPEDITE, 2),
    TOY.name: (StepAction.PASS, 2),
    SALT_STRAIT.name: (StepAction.PASS, 2),
}
"""The middle step on the leader's naval order, as the seed decides it: the action taken
and the days after filing it was taken. The middle person is code-held, so his card's
policy decides from the campaign's seed (``Cast.campaign``, fixed) and the day; the run
pins it by playing that seed, and this states the outcome. 1941: the Chief of Naval
Operations expedites it; toy: the marshal passes it; Salt Strait: the First Minister's
chief of staff passes it. Either way it advances."""


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Callable[[Cast, str], Game]]:
    kept: dict[tuple[str, str], Game] = {}

    def run(cast: Cast, name: str) -> Game:
        if (cast.name, name) not in kept:
            with pytest.MonkeyPatch.context() as mp:
                tmp = tmp_path_factory.mktemp(f"{cast.name}-{name}")
                kept[(cast.name, name)] = Game(cast, tmp, mp).play(SCRIPTS[name])
        return kept[(cast.name, name)]

    yield run


each_cast = pytest.mark.parametrize("cast", CASTS, ids=[c.name for c in CASTS])


# --- rule 1: lock 1, opened by the leader's naval order --------------------------------


@each_cast
def test_lock_1_holds_the_order_and_the_commander_asks_the_leader(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g = runs(cast, "full")
    p = g.played
    (held,) = [h.held for h in g.logged(ev.OrderHeld) if h.held.order_id == p.lock1]
    assert held.row == cast.lock1_row and held.issuer == g.commander
    assert held.decider == locks.Decider(person=cast.entity(cast.leader))
    asked = p.asked[p.lock1]
    assert (asked.asker, asked.to, asked.seat) == (
        g.commander,
        cast.entity(cast.leader),
        g.leader,
    )


@each_cast
def test_lock_1_the_naval_order_crosses_the_middle_step_then_the_commanders_desk(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g = runs(cast, "full")
    p = g.played
    order = g.state.orders[known(p.posture)]
    assert order.status is OrderStatus.ENACTED
    middle, desk = order.outcomes
    action, days = PINNED[cast.name]
    assert (middle.person, middle.action) == (cast.entity(cast.middle), action)
    assert middle.action in ADVANCES and middle.on == order.filed + timedelta(days=days)
    assert desk.person == cast.entity(cast.commander) and desk.action is StepAction.PASS
    # The commander kept his choice in the wake the order reached his desk. He tried to
    # refuse it first: an order from up his chain may only be passed or stalled.
    assert p.desk_taken == middle.on
    assert len(p.refusals) == 1 and p.refusals[0] != ""


@each_cast
def test_lock_1_the_held_order_lands_the_day_the_posture_is_set(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g = runs(cast, "full")
    p = g.played
    set_on = g.state.orders[known(p.posture)].outcomes[-1].on
    (end,) = ends(g, p.lock1)
    assert end.end is locks.HeldEnd.LANDED and end.on == set_on
    landed = g.state.orders[landed_as(cast, p.lock1)]
    assert landed.status is OrderStatus.ENACTED and landed.filed == set_on
    assert (landed.lever, landed.params) == (cast.lock1[0], cast.lock1[1])
    assert p.lock1 not in g.state.held


# --- rule 2: lock 2, opened by the law -------------------------------------------------


@each_cast
def test_lock_2_holds_the_order_for_the_chambers_and_the_ask_goes_to_the_head(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g = runs(cast, "full")
    p = g.played
    (held,) = [h.held for h in g.logged(ev.OrderHeld) if h.held.order_id == p.lock2]
    assert held.row == cast.lock2_row
    assert held.decider.person is None and held.decider.head == cast.entity(cast.leader)
    assert p.asked[p.lock2].seat == g.leader


@each_cast
def test_lock_2_the_bill_passes_on_its_date_by_the_blocs_votes(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g = runs(cast, "full")
    state = g.state
    bill = state.orders[known(g.played.bill)]
    assert bill.status is OrderStatus.ENACTED
    settled = bill.outcomes[-1].on
    flag = state.quantities[qid(state, cast.passed)]
    assert flag.value == 1 and flag.as_of == settled
    # Each vote's yeas and nays together are every voting member of the blocs that sit in
    # that chamber: the count came from the blocs, and each vote passed.
    nation = state.seats[g.leader].embodies
    blocs = state.groups.declared[state.entities[nation].parent or nation]
    measure = str(cast.bill[1]["bill"])
    votes = dict(zip(cast.votes, (g.quantity(k) for k in cast.votes), strict=True))
    for yeas_key in cast.votes[::2]:
        vote = yeas_key.removeprefix(f"{measure}_").removesuffix("_yeas")
        yeas, nays = votes[yeas_key], votes[yeas_key.replace("_yeas", "_nays")]
        assert yeas is not None and nays is not None and yeas > nays
        voting = sum(
            row.voting
            for b in blocs
            if (row := (b.votes.get(measure) or b.vote_default).get(vote)) is not None
        )
        assert yeas + nays == voting


@each_cast
def test_lock_2_opens_once_the_law_is_in_force_and_the_order_lands(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g = runs(cast, "full")
    p = g.played
    state = g.state
    passed_on = state.quantities[qid(state, cast.passed)].as_of
    (end,) = ends(g, p.lock2)
    assert end.end is locks.HeldEnd.LANDED and end.on == passed_on + timedelta(days=1)
    landed = state.orders[landed_as(cast, p.lock2)]
    assert landed.status is OrderStatus.ENACTED and landed.params == cast.lock2[1]


# --- rule 3: without the leader's moves, both stay held --------------------------------


@each_cast
def test_without_the_leaders_moves_both_orders_are_held_at_the_seasons_end(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g = runs(cast, "none")
    p = g.played
    state = g.state
    assert state.phase is Phase.SEASON_OVER
    assert {p.lock1, p.lock2} <= set(state.held)
    assert ends(g, p.lock1) == [] and ends(g, p.lock2) == []
    assert not any(o.issuer == g.leader and o.lever == cast.bill[0] for o in state.orders.values())
    assert g.quantity(cast.passed) is None  # the vote was never held
    assert len(g.logged(ev.OrderAsked)) == 2


# --- rule 4: both seats move the commander's force; the leader's order stands ----------


@each_cast
def test_both_seats_move_the_force_and_the_leaders_order_stands(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g = runs(cast, "both")
    p = g.played
    state = g.state
    assert p.leader_move is not None and p.commander_move is not None
    assert state.orders[known(p.leader_move)].status is OrderStatus.ENACTED
    force = state.features[FeatureId(object_id(cast.campaign, "feature", cast.force))]
    assert force.bound_for == cast.entity(cast.leader_bound)
    mine = cast.entity(cast.commander_move[1]["to"])
    assert force.bound_for not in (mine, state.entities[mine].within)
    leader_on = state.orders[known(p.leader_move)].outcomes[-1].on
    his = state.orders[known(p.commander_move)]
    if cast.meets:
        # Both first acted in one wake: the commander's is settled as replaced, and the
        # reason reaches his seat only.
        assert his.status is OrderStatus.LAPSED and his.outcomes == ()
        papers = [
            d.view
            for d in state.documents.values()
            if any(b.value == REPLACED for b in d.view.body)
        ]
        assert [paper.scope.known_by for paper in papers] == [frozenset({g.commander})]
    else:
        # Filed in one wake, the commander's acted first (see ``Cast.meets``); the leader's
        # acted after it and the force went where the leader sent it.
        assert his.status is OrderStatus.ENACTED
        assert leader_on > his.outcomes[-1].on


# --- rule 5: the commander absent ------------------------------------------------------


@each_cast
def test_the_absent_commanders_step_on_the_leaders_order_passes_on_its_day(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g = runs(cast, "absent")
    state = g.state
    order = state.orders[known(g.played.posture)]
    middle, desk = order.outcomes
    step = state.pipelines[order.pipeline].steps[1]
    assert step.days is not None
    assert desk.person == cast.entity(cast.commander) and desk.action is StepAction.PASS
    assert desk.on == middle.on + timedelta(days=step.days + process.ANSWER_DAYS)
    assert not [c for c in g.logged(ev.StepChosen) if c.order_id == order.order_id]
    # The lock it opened still lands, though nobody sat in the commander's chair.
    (end,) = ends(g, g.played.lock1)
    assert end.end is locks.HeldEnd.LANDED


@each_cast
def test_the_aide_for_the_absent_commander_files_no_held_order(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g = runs(cast, "absent")
    aide = [c for c in g.logged(ev.WakeCommitted) if c.by_aide and c.seat_id == g.commander]
    assert aide, "the aide played the absent seat"
    held = {h.held.order_id for h in g.logged(ev.OrderHeld)}
    assert held == {g.played.lock1, g.played.lock2}  # only the commander's own, before he left
    filed = {o for c in aide for o in c.aide_orders}
    assert not filed & held


# --- rule 6: the season ends and scores -------------------------------------------------


@each_cast
@pytest.mark.parametrize("name", ["full", "none"])
def test_the_season_ends_and_scores_by_each_seats_aims(
    runs: Callable[[Cast, str], Game], cast: Cast, name: str
) -> None:
    g = runs(cast, name)
    state = g.state
    (ended,) = g.logged(ev.SeasonEnded)
    assert frozenset(ended.winners) == season_winners(state)
    events = g.events()
    for seat in (g.leader, g.commander):
        stakes = seat_stakes(state, seat, events)
        card = state.cards[state.seats[seat].embodies]
        assert [a["aim"] for a in stakes["aims"]] == list(range(1, len(card.aims) + 1))
        assert all(a["status"] != AimStatus.AT_RISK.value for a in stakes["aims"])
        assert (seat in ended.winners) == (stakes["degree"] is not None)
    # The law aim is the commander's last: met when the bill passed, failed when it never ran.
    law = seat_stakes(state, g.commander, events)["aims"][-1]
    want = AimStatus.MET if name == "full" else AimStatus.FAILED
    assert law["status"] == want.value


# --- the script: one digest -------------------------------------------------------------


@each_cast
def test_the_script_run_twice_gives_one_digest(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    assert digest(runs(cast, "full").state) == digest(runs(cast, "again").state)


@each_cast
def test_a_restart_and_retry_mid_game_give_one_decision_one_unlock_and_the_same_digest(
    runs: Callable[[Cast, str], Game], cast: Cast
) -> None:
    g, full = runs(cast, "restart"), runs(cast, "full")
    p = g.played
    assert digest(g.state) == digest(full.state)
    assert p.refused_retries == [locks.ASKED_ALREADY] * 2  # both asks, retried, refused
    assert len(g.logged(ev.OrderAsked)) == 2
    assert len(g.logged(ev.OrderHeld)) == 2
    assert len(steps_at(g, p.posture, cast.commander)) == 1  # one decision at his desk
    for held in (p.lock1, p.lock2):
        assert len(ends(g, held)) == 1  # one unlock each


# --- the seat's view: twin worlds -------------------------------------------------------


@each_cast
def test_a_lock_reason_carries_no_fact_outside_the_commanders_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cast: Cast
) -> None:
    """Two games differing only in a fact the commander cannot see: each lock holds his
    order with the same reason, the ask reads the same, and his whole view is the same."""
    seen = []
    for twin, changes in (("a", ()), ("b", (cast.hidden,))):
        world = cast.world(tmp_path / twin / "world", changes)
        g = Game(cast, tmp_path / twin, monkeypatch, world=world)
        g._tick(None)
        held = [
            g.file(g.commander, form, f"file:{n}")
            for n, form in enumerate((cast.lock1, cast.lock2))
        ]
        asked = [g.ask(o.order_id, f"ask:{n}") for n, o in enumerate(held)]
        state = g.state
        assert {state.held[o.order_id].row for o in held} == {cast.lock1_row, cast.lock2_row}
        seen.append(
            (
                [state.held[o.order_id].reason for o in held],
                [a.words for a in asked],
                project(state, g.commander).model_dump(mode="json"),
                digest(state),
            )
        )
    (reasons_a, words_a, view_a, world_a), (reasons_b, words_b, view_b, world_b) = seen
    assert world_a != world_b  # the hidden fact differs in the world
    assert reasons_a == reasons_b and words_a == words_b
    assert view_a == view_b
