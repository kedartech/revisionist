"""Head-on moves meet by a fixed rule (HON).

The toy world of ``tests/test_battles.py`` (territories, holders and battles on; Norra and
Sudland at war) with Norra's kites off the board, so no air support enters the sums.
Norra's levy (strength 5) stands at a fort in the Norra Hills and Sudland's levy (strength
4) at Sudby on the Sudland Coast, which borders the hills; each is sent into the other's
area. With ``even`` a levy takes 5 days a step on any land, so both steps fall due on day
5; without it Norra's step into the coast (plain, 5 days) falls due before Sudland's into
the hills (7 days).

Piece ids, which no player sets, decide who attacks a meeting battle and the order borders
are settled in: Sudland's levy has a lower id than Norra's, and the raider levy the lowest
of all. The coast's id is lower than the hills', so a meeting on that border is kept under
the coast.
"""

from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, derived_id
from revisionist.core.realism import battle
from revisionist.core.realism.battle import Decision, Ending
from revisionist.core.realism.effect import Contingency, ContingencyKind, Posture
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import apply_changes, movement
from revisionist.core.realism.territory import StepCause
from tests.async_table import digest, orderings
from tests.test_adjacency_moves import (
    Logged,
    World,
    day,
    entity,
    levers,
    order,
    piece,
    seat,
    where,
)
from tests.test_battles import horizon, payloads, rules, strengths, toy
from tests.test_holders import Wakes, without
from tests.test_territory_model import CAMPAIGN

HILLS, COAST, PLAIN = "norra_hills", "sudland_coast", "norra_plain"
MEETS = day(5)
"""The day both steps fall due with ``even``."""


def fort(w: World) -> None:
    """A fort in the Norra Hills, where Norra's levy stands."""
    w["entities"].append(
        {"key": "hill_fort", "kind": "location", "name": "Hill Fort", "at": [150, 60]}
        | {"within": HILLS}
    )
    (levy,) = [f for f in w["features"] if f["key"] == "norra_levy"]
    levy["places"] = ["hill_fort"]


def even(w: World) -> None:
    """A levy takes 5 days a step on any land."""
    (levy,) = [k for k in w["piece_kinds"] if k["key"] == "levy"]
    levy["days_per_step"] = {"hills": 5, "plain": 5}


def levy(key: str, side: str, at: str, tier: int) -> Callable[[World], None]:
    """Another levy of ``side`` at ``at``."""

    def change(w: World) -> None:
        w["features"].append(
            {
                "key": key,
                "kind": "piece",
                "piece": "levy",
                "name": key.replace("_", " ").title(),
                "side": side,
                "places": [at],
                "tier": tier,
                "source": "toy",
            }
        )

    return change


def border(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    """The two levies on either side of the hills-coast border, kites off the board."""
    return Logged(toy(tmp, fort, without("norra_kites"), *changes), "ilse", "tomas")


NORTH = order("ilse", "norra_levy", "sudby")
SOUTH = order("tomas", "sudland_levy", "hill_fort")
RESERVE = order("tomas", "reserve_levy", "hill_fort", n=2)
RAIDER = order("tomas", "raider_levy", "hill_fort", n=3)
PICKET = order("ilse", "picket_levy", "norrhavn", n=2)


def file(g: Logged, *orders: Order) -> None:
    for o in orders:
        g.add(apply_changes(g.state, movement.order_changes(g.state, o)))


def head_on(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    """Both levies sent into each other's area, both steps due on day 5."""
    g = border(tmp, even, *changes)
    file(g, NORTH, SOUTH)
    return g


def moves(out: Sequence[ev.Event]) -> list[tuple[Any, Any, Any, StepCause]]:
    """Every step in ``out``: the nation, the area left, the area entered and the cause."""
    return [(p.nation, p.left, p.entered, p.cause) for p in payloads(out, ev.PieceStepped)]


def until_ended(g: Logged, first: Any) -> list[ev.Event]:
    """Walk day by day from ``first`` until a battle ends; the events of every day walked."""
    out: list[ev.Event] = []
    d = first
    while not payloads(out, ev.BattleEnded):
        out += g.walk(d, d)
        d += timedelta(days=1)
        assert d < day(40)
    return out


# --- Rule 1: neither enters; a meeting battle opens on that border ---------------------


def test_two_head_on_steps_on_one_day_enter_neither_area(tmp_path: Path) -> None:
    g = head_on(tmp_path)
    out = g.walk(day(1), MEETS)
    assert moves(out) == []
    assert where(g.state, "norra_levy") == entity(HILLS)
    assert where(g.state, "sudland_levy") == entity(COAST)


def test_a_meeting_battle_opens_on_the_border_and_fights_that_day(tmp_path: Path) -> None:
    g = head_on(tmp_path)
    out = g.walk(day(1), MEETS)
    (opened,) = payloads(out, ev.BattleOpened)
    b = opened.battle
    assert b.meeting and b.opened == MEETS
    assert (b.area, b.second) == (entity(COAST), entity(HILLS))
    # Sudland's levy has the lower id of the two movers: Sudland attacks, from the coast.
    assert entity("sudland_levy") < entity("norra_levy")
    assert (b.attacker.nation, b.attacker_in) == (entity("sudland"), entity(COAST))
    assert b.attacker.pieces == (entity("sudland_levy"),)
    assert b.defender.pieces == (entity("norra_levy"),)
    assert (b.attacker.brought, b.defender.brought) == (4, 5)
    assert b.came_from == {}
    assert [r.on for r in payloads(out, ev.BattleRound)] == [MEETS]
    assert battle.at(g.state, entity(HILLS)) == battle.at(g.state, entity(COAST))


def test_the_movers_keep_their_courses_and_stand_while_they_meet(tmp_path: Path) -> None:
    g = head_on(tmp_path, strengths(norra_levy=5, sudland_levy=5))
    g.walk(day(1), MEETS + timedelta(days=1))
    assert battle.at(g.state, entity(COAST)) is not None  # still fighting on day 6
    assert piece(g.state, "norra_levy").path == (entity(COAST),)
    assert piece(g.state, "sudland_levy").path == (entity(HILLS),)
    assert where(g.state, "norra_levy") == entity(HILLS)
    assert where(g.state, "sudland_levy") == entity(COAST)


def test_without_battles_the_two_pieces_still_pass_each_other(tmp_path: Path) -> None:
    g = head_on(tmp_path, rules("territories", "holders"))
    g.walk(day(1), MEETS)
    assert where(g.state, "norra_levy") == entity(COAST)
    assert where(g.state, "sudland_levy") == entity(HILLS)


def test_steps_into_one_area_from_two_sides_are_no_meeting(tmp_path: Path) -> None:
    """Norra's levy holds still in the hills; Sudland's levy steps in: a normal battle."""
    g = border(tmp_path, even)
    file(g, SOUTH)
    out = g.walk(day(1), MEETS)
    (opened,) = payloads(out, ev.BattleOpened)
    assert not opened.battle.meeting and opened.battle.area == entity(HILLS)


def test_an_enemy_does_not_step_into_a_meeting_battles_area(tmp_path: Path) -> None:
    """A Sudland raider at Norrhavn sent into the hills is due there on day 6, the meeting
    still on: its step is not taken and its move is dropped."""
    g = head_on(
        tmp_path,
        strengths(norra_levy=5, sudland_levy=5),
        levy("raider_levy", "sudland", "norrhavn", 1),
    )
    file(g, order("tomas", "raider_levy", "hill_fort", on=day(1), n=3))
    assert piece(g.state, "raider_levy").step_due == MEETS + timedelta(days=1)
    g.walk(day(1), MEETS + timedelta(days=1))
    assert battle.at(g.state, entity(HILLS)) is not None
    assert where(g.state, "raider_levy") == entity(PLAIN)
    assert piece(g.state, "raider_levy").path == ()


# --- Rule 2: no terrain or own-ground bonus in a meeting battle ------------------------


def test_a_meeting_round_scores_strength_and_draw_only(tmp_path: Path) -> None:
    """Norra defends from the hills it holds (terrain defence 1, its own ground): neither
    counts; Sudland's coast gives nothing either."""
    g = head_on(tmp_path, strengths(norra_levy=5, sudland_levy=5))
    out = g.walk(day(1), MEETS)
    (r,) = payloads(out, ev.BattleRound)
    assert r.scores == (5 + r.draws[0], 5 + r.draws[1])


def test_a_normal_battle_on_the_same_hills_counts_both() -> None:
    """The control: the same sides in a normal battle in the hills score the terrain and
    the own ground for the defender."""
    side = battle.SideIn(fighters=(battle.Fighter("p", 5),), brought=5, own_ground=True)
    assert battle.score(side, 0, True, 1) == 5 + 1 + 1


# --- Rule 3: the side that breaks or withdraws keeps home; the other completes its step --


def test_the_side_that_breaks_keeps_home_and_the_winner_steps_in_and_attacks(
    tmp_path: Path,
) -> None:
    g = head_on(tmp_path)
    out = until_ended(g, day(1))
    (ended,) = payloads(out, ev.BattleEnded)
    assert ended.area == entity(COAST) and ended.ending is Ending.HELD  # Sudland broke
    assert ended.winner == entity("norra")
    assert where(g.state, "sudland_levy") == entity(COAST)
    assert piece(g.state, "sudland_levy").path == ()
    assert [m for m in moves(out) if m[0] == entity("sudland")] == []
    assert moves(out) == [(entity("norra"), entity(HILLS), entity(COAST), StepCause.ORDERED)]
    (stepped,) = payloads(out, ev.PieceStepped)
    assert stepped.on == ended.on
    follow = [p.battle for p in payloads(out, ev.BattleOpened)][-1]
    assert not follow.meeting and follow.area == entity(COAST)
    assert follow.opened == ended.on
    assert follow.attacker.nation == entity("norra")
    assert follow.attacker.pieces == (entity("norra_levy"),)
    assert follow.defender.pieces == (entity("sudland_levy"),)
    assert follow.came_from == {entity("norra_levy"): entity(HILLS)}
    assert piece(g.state, "norra_levy").path == ()  # it stopped where the enemy stands
    assert g.state.battles == {entity(COAST): follow}


def test_a_winner_with_no_enemy_left_steps_in_and_the_count_starts(tmp_path: Path) -> None:
    """Sudland's levy at strength 1 is destroyed in the first round."""
    g = head_on(tmp_path, strengths(norra_levy=5, sudland_levy=1))
    out = g.walk(day(1), MEETS)
    (ended,) = payloads(out, ev.BattleEnded)
    assert ended.winner == entity("norra")
    assert piece(g.state, "sudland_levy").lost_on == MEETS
    assert where(g.state, "norra_levy") == entity(COAST)
    assert [p.battle.meeting for p in payloads(out, ev.BattleOpened)] == [True]
    assert g.state.battles == {}
    assert g.state.captures[entity(COAST)].by == entity("norra")
    assert g.state.captures[entity(COAST)].since == MEETS


def test_the_winner_goes_on_with_its_course_when_no_enemy_is_left(tmp_path: Path) -> None:
    """Sudland's levy, sent through the hills to Norrhavn, destroys Norra's levy (strength
    1) on the border: it steps into the hills that day and goes on to the plain."""
    g = border(tmp_path, even, strengths(norra_levy=1, sudland_levy=5))
    file(g, NORTH, order("tomas", "sudland_levy", "norrhavn"))
    out = g.walk(day(1), MEETS)
    (ended,) = payloads(out, ev.BattleEnded)
    assert (ended.ending, ended.winner) == (Ending.WON, entity("sudland"))
    sudland = piece(g.state, "sudland_levy")
    assert sudland.places == (entity(HILLS),)
    assert (sudland.path, sudland.step_due) == ((entity(PLAIN),), MEETS + timedelta(days=5))
    out = g.walk(MEETS + timedelta(days=1), MEETS + timedelta(days=5))
    assert moves(out) == [(entity("sudland"), entity(HILLS), entity(PLAIN), StepCause.ORDERED)]


def test_a_withdrawal_in_a_meeting_keeps_home_and_concedes_the_border(tmp_path: Path) -> None:
    g = head_on(tmp_path, strengths(norra_levy=5, sudland_levy=5))
    g.walk(day(1), MEETS)
    on = MEETS + timedelta(days=1)
    landed = battle.land_posture(g.state, piece(g.state, "norra_levy"), Posture.WITHDRAW, None, on)
    assert landed is not None
    decided = [p for p in landed if isinstance(p, ev.BattleDecided)]
    assert [(d.area, d.decision) for d in decided] == [(entity(COAST), Decision.WITHDRAW)]
    assert not [p for p in landed if isinstance(p, ev.PieceStepped)]
    g.add(landed)
    assert where(g.state, "norra_levy") == entity(HILLS)
    assert piece(g.state, "norra_levy").path == ()
    out = g.walk(on, on)
    (ended,) = payloads(out, ev.BattleEnded)
    assert (ended.area, ended.ending, ended.winner) == (
        entity(COAST),
        Ending.WON,
        entity("sudland"),
    )
    assert payloads(out, ev.BattleRound) == []
    assert moves(out) == [(entity("sudland"), entity(COAST), entity(HILLS), StepCause.ORDERED)]
    (follow,) = [p.battle for p in payloads(out, ev.BattleOpened)]
    assert (follow.area, follow.attacker.nation, follow.meeting) == (
        entity(HILLS),
        entity("sudland"),
        False,
    )
    assert follow.defender.pieces == (entity("norra_levy"),)


def test_a_move_across_the_border_presses_and_a_move_elsewhere_withdraws(
    tmp_path: Path,
) -> None:
    g = head_on(tmp_path, strengths(norra_levy=5, sudland_levy=5))
    g.walk(day(1), MEETS)
    on = MEETS + timedelta(days=1)
    norra = piece(g.state, "norra_levy")
    pressed = battle.land_posture(g.state, norra, None, entity(COAST), on)
    assert pressed is not None
    assert [p.decision for p in pressed if isinstance(p, ev.BattleDecided)] == [Decision.PRESS]
    went = battle.land_posture(g.state, norra, None, entity(PLAIN), on)
    assert went is not None
    assert [p.decision for p in went if isinstance(p, ev.BattleDecided)] == [Decision.WITHDRAW]
    assert not [p for p in went if isinstance(p, ev.PieceStepped)]


def test_a_contingency_that_fires_in_a_meeting_keeps_its_side_home(tmp_path: Path) -> None:
    """Sudland's levy (strength 4) set to withdraw below strength 5: it fires before the
    first round, and Norra completes its step with no round fought."""
    g = head_on(tmp_path)
    c = Contingency(kind=ContingencyKind.WITHDRAW_BELOW, below=5)
    g.add(
        [
            ev.FeatureSet(
                feature=piece(g.state, "sudland_levy").model_copy(update={"contingency": c})
            )
        ]
    )
    out = g.walk(day(1), MEETS)
    assert payloads(out, ev.BattleRound) == []
    (ended,) = payloads(out, ev.BattleEnded)
    assert (ended.ending, ended.winner) == (Ending.HELD, entity("norra"))
    assert moves(out) == [(entity("norra"), entity(HILLS), entity(COAST), StepCause.ORDERED)]
    assert where(g.state, "sudland_levy") == entity(COAST)


# --- Rule 4: steps on different days: the earlier enters, the later move is cancelled ----


def test_the_earlier_step_enters_and_attacks_and_the_later_move_is_cancelled(
    tmp_path: Path,
) -> None:
    g = border(tmp_path)
    file(g, NORTH, SOUTH)
    assert piece(g.state, "sudland_levy").step_due == day(7)
    out = g.walk(day(1), MEETS)
    (opened,) = payloads(out, ev.BattleOpened)
    assert not opened.battle.meeting
    assert (opened.battle.area, opened.battle.attacker.nation) == (entity(COAST), entity("norra"))
    sudland = piece(g.state, "sudland_levy")
    assert (sudland.path, sudland.step_due, sudland.bound_for) == ((), None, None)
    out = g.walk(day(6), day(12))
    assert [m for m in moves(out) if m[3] is StepCause.ORDERED] == []


# --- Rule 5: more movers settled in the order of their piece ids ------------------------


def three(tmp: Path) -> Logged:
    """A second Sudland levy at Sudby, sent to the hills with the first."""
    g = border(tmp, even, levy("reserve_levy", "sudland", "sudby", 3))
    file(g, NORTH, SOUTH, RESERVE)
    return g


def test_three_movers_on_one_border_meet_as_two_sides(tmp_path: Path) -> None:
    g = three(tmp_path)
    out = g.walk(day(1), MEETS)
    (opened,) = payloads(out, ev.BattleOpened)
    b = opened.battle
    assert b.meeting and b.attacker.nation == entity("sudland")
    assert b.attacker.pieces == tuple(sorted((entity("sudland_levy"), entity("reserve_levy"))))
    assert b.attacker.brought == 7
    assert moves(out) == []


def two_borders(tmp: Path) -> Logged:
    """Two borders of the hills met head-on on one day: hills-coast by the two levies, and
    plain-hills by Sudland's raider from Norrhavn and a Norra picket from the fort. The
    hills can be in one battle only."""
    g = border(
        tmp,
        even,
        levy("raider_levy", "sudland", "norrhavn", 3),
        levy("picket_levy", "norra", "hill_fort", 3),
    )
    file(g, NORTH, SOUTH, RAIDER, PICKET)
    return g


def test_borders_that_share_an_area_are_settled_by_the_lowest_piece_id(tmp_path: Path) -> None:
    g = two_borders(tmp_path)
    ids = {k: entity(k) for k in ("norra_levy", "sudland_levy", "raider_levy", "picket_levy")}
    assert min(ids.values()) == ids["raider_levy"]
    met = movement.head_on(g.state, MEETS)
    assert [(set(m.border), m.attacker, {str(f) for f in m.movers}) for m in met] == [
        (
            {entity(HILLS), entity(PLAIN)},
            entity("sudland"),
            {str(ids["raider_levy"]), str(ids["picket_levy"])},
        )
    ]
    out = g.walk(day(1), MEETS)
    opened = {p.battle.area: p.battle for p in payloads(out, ev.BattleOpened)}
    meeting = opened[entity(HILLS)]
    assert meeting.meeting and meeting.second == entity(PLAIN)
    # The other pair goes as moves do: Norra's levy steps into the coast and attacks;
    # Sudland's, bound for the hills where the meeting stands, does not step.
    assert opened[entity(COAST)].attacker.nation == entity("norra")
    assert where(g.state, "sudland_levy") == entity(COAST)
    assert piece(g.state, "sudland_levy").path == ()


def test_a_border_with_an_area_in_a_battle_is_no_meeting(tmp_path: Path) -> None:
    g = head_on(tmp_path, strengths(norra_levy=5, sudland_levy=5))
    g.walk(day(1), MEETS)
    assert (
        battle.meetings(g.state, [(piece(g.state, "norra_levy"), entity(HILLS), entity(COAST))])
        == []
    )


# --- Invariant 3: every filing order, and many sittings, give one world -------------------


def filed(g: Logged, o: Order, n: int) -> None:
    """File ``o`` as the engine does at the close: drafted as the seat's ``n``-th order (its
    id from the seat's own stream, as ``SeatIds`` draws it), settled enacted, and its
    changes landed. The orders map keeps the filing order."""
    pipeline = next(iter(g.state.pipelines))
    o = o.model_copy(
        update={
            "order_id": OrderId(derived_id(CAMPAIGN, "seat-order", o.issuer, n)),
            "pipeline": pipeline,
            "status": OrderStatus.MOVING,
        }
    )
    g.add([ev.OrderDrafted(order=o)])
    g.add([ev.OrderSettled(order_id=o.order_id, status=OrderStatus.ENACTED)])
    g.add(apply_changes(g.state, movement.order_changes(g.state, o)))


def outcome(tmp: Path, extra: Sequence[Callable[[World], None]], batches: Any) -> str:
    """The world two wakes on, with ``batches`` filed in that order, a sitting each. Norra's
    kites stay on the board here: the field order's lever names them."""
    g = Logged(toy(tmp, fort, even, levers, horizon(12), *extra), "ilse", "tomas")
    count: dict[Any, int] = {}
    for batch in batches:
        for o in batch:
            count[o.issuer] = count.get(o.issuer, 0) + 1
            filed(g, o, count[o.issuer])
        # A sitting that changes nothing but the record count.
        g.add([ev.FeatureSet(feature=piece(g.state, "norra_herald"))])
    w = Wakes(g)
    w.close()
    w.close()
    assert [k for k in (e.kind for e in w.log) if k == "battle_opened"]
    # Which id a seat's order drew follows the seat's filing order, as in the engine; the
    # world is everything else, and the orders as what they say.
    state = w.state
    said = sorted(
        (o.issuer, sorted(o.params.items()), o.status.value) for o in state.orders.values()
    )
    return digest(state.model_copy(update={"orders": {}})) + repr(said)


def test_every_filing_order_and_sitting_gives_one_world_for_two_movers(tmp_path: Path) -> None:
    seen = set()
    runs = list(enumerate(orderings([NORTH, SOUTH], sittings=10)))
    for n, batches in runs:
        (tmp_path / str(n)).mkdir()
        seen.add(outcome(tmp_path / str(n), (), batches))
    assert len(runs) == 6 and len(seen) == 1


def test_every_filing_order_and_sitting_gives_one_world_for_three_movers(tmp_path: Path) -> None:
    seen = set()
    reserve = levy("reserve_levy", "sudland", "sudby", 3)
    runs = list(enumerate(orderings([NORTH, SOUTH, RESERVE], sittings=10)))
    for n, batches in runs:
        (tmp_path / str(n)).mkdir()
        seen.add(outcome(tmp_path / str(n), (reserve,), batches))
    assert len(runs) == 18 and len(seen) == 1


def test_one_seat_filing_its_movers_in_ten_sittings_gives_one_world(tmp_path: Path) -> None:
    """Tomas files his two levies' moves, and Ilse hers, one a sitting over ten sittings,
    in every order."""
    seen = set()
    reserve = levy("reserve_levy", "sudland", "sudby", 3)
    for n, (a, b) in enumerate(((SOUTH, RESERVE), (RESERVE, SOUTH))):
        batches = [[a], [], [], [NORTH], [], [], [], [b], [], []]
        (tmp_path / str(n)).mkdir()
        seen.add(outcome(tmp_path / str(n), (reserve,), batches))
    assert len(seen) == 1


def test_the_seat_ids_record_the_filing_order(tmp_path: Path) -> None:
    """The harness is fair: two filing orders give different order records, so a rule
    reading them would show in the digest."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    g1 = Logged(toy(tmp_path / "a", fort, levers), "ilse", "tomas")
    g2 = Logged(toy(tmp_path / "b", fort, levers), "ilse", "tomas")
    filed(g1, NORTH, 1)
    filed(g1, SOUTH, 1)
    filed(g2, SOUTH, 1)
    filed(g2, NORTH, 1)
    assert list(g1.state.orders) != list(g2.state.orders)
    assert seat("ilse") in {o.issuer for o in g1.state.orders.values()}
