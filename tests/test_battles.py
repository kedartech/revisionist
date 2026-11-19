"""Battles that last several days, one round a day (BTL).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories``,
``holders`` and ``battles`` on. Norra and Sudland are at war. Each piece is given a
strength (``tier``); a piece that fights must have one. Norra's levy, sent to Sudby, steps
into the Sudland Coast on day 12, where Sudland's levy stands on ground Sudland holds: the
battle opens that day with Norra attacking. Norra's kites, two air steps away at Norrhavn,
support Norra.
"""

from collections.abc import Callable, Sequence
from datetime import timedelta
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, replay, state_hash
from revisionist.core.ids import FeatureId
from revisionist.core.realism import battle, territory
from revisionist.core.realism.battle import (
    DOUBLE_MARGIN,
    DRAW_TOP,
    LULL_DAYS,
    Ending,
    Fighter,
    SideIn,
    Sides,
)
from revisionist.core.realism.effect import Posture
from revisionist.core.realism.geography import in_play
from revisionist.core.realism.territory import StepCause
from revisionist.core.visibility import Visibility
from revisionist.core.world import WorldFile
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup
from tests.async_table import digest
from tests.test_adjacency_moves import START, Logged, World, day, entity, order, piece, seat
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_holders import Wakes, capital, held
from tests.test_territory_model import created, refused

COAST = "sudland_coast"
OPENS = day(12)
"""The day Norra's levy steps into the coast."""

TIERS = {
    "norra_levy": 5,
    "sudland_levy": 4,
    "sudland_galleys": 3,
    "norra_kites": 1,
    "norra_herald": 1,
}


def strengths(**tiers: int) -> Callable[[World], None]:
    def change(w: World) -> None:
        for f in w["features"]:
            f["tier"] = {**TIERS, **tiers}.get(f["key"], 1)

    return change


def rules(*names: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = list(names)

    return change


def link(a: str, b: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["adjacency"].append([a, b])

    return change


def horizon(days: int) -> Callable[[World], None]:
    """Every card's horizon set to ``days``: the first wake closes ``days`` days in."""

    def change(w: World) -> None:
        for c in w["cards"]:
            c["horizon_days"] = days

    return change


def no_ferry(w: World) -> None:
    """The Isle cut off from the Norra Plain, so Norra's levy goes by the hills."""
    w["adjacency"] = [x for x in w["adjacency"] if not isinstance(x, dict)]


def toy(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    """The toy world with territories, holders and battles on, every piece given a
    strength, and ``changes`` applied."""
    return territories_toy(tmp, rules("territories", "holders", "battles"), strengths(), *changes)


def payloads(out: Sequence[ev.Event], kind: type) -> list[Any]:
    return [e.payload for e in out if isinstance(e.payload, kind)]


def to_coast(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    """Norra's levy sent to Sudby, into Sudland's levy on the coast."""
    g = Logged(toy(tmp, *changes), "ilse", "tomas")
    g.send("ilse", "norra_levy", "sudby")
    return g


def seed_for(want: tuple[int, int]) -> str:
    """A seed whose first day's draws are ``want``."""
    for n in count():
        if battle.draws(f"s{n}", 0) == want:
            return f"s{n}"
    raise AssertionError  # pragma: no cover


def one(strength: int, **flags: Any) -> SideIn:
    return SideIn(fighters=(Fighter("p", strength),), brought=strength, **flags)


# --- Rule 1: a battle opens where two powers at war stand; entered attacks, stood defends --


def test_a_battle_opens_the_day_the_attacker_steps_in(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    assert not payloads(g.walk(day(1), day(11)), ev.BattleOpened)
    out = g.walk(OPENS, OPENS)
    (opened,) = payloads(out, ev.BattleOpened)
    b = opened.battle
    assert (b.area, b.opened, opened.on) == (entity(COAST), OPENS, OPENS)
    assert b.attacker.nation == entity("norra") and b.defender.nation == entity("sudland")
    assert b.attacker.pieces == (entity("norra_levy"),)
    assert b.defender.pieces == (entity("sudland_levy"),)
    assert (b.attacker.brought, b.defender.brought) == (5, 4)
    assert b.came_from == {entity("norra_levy"): entity("norra_hills")}
    assert list(g.state.battles) == [entity(COAST)]


def test_one_battle_per_area(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    out = g.walk(day(1), day(30))
    opened = payloads(out, ev.BattleOpened)
    ended = payloads(out, ev.BattleEnded)
    assert len(opened) == 1 and len(ended) == 1
    assert len({p.on for p in payloads(out, ev.BattleRound)}) == len(payloads(out, ev.BattleRound))


def test_the_side_that_stood_there_defends_whoever_holds_the_ground(tmp_path: Path) -> None:
    """Sudland's levy marches by the hills into the Norra Plain, where Norra's levy stands."""
    g = Logged(toy(tmp_path), "ilse", "tomas")
    g.send("tomas", "sudland_levy", "norrhavn")
    out = g.walk(day(1), day(15))
    (opened,) = payloads(out, ev.BattleOpened)
    assert opened.battle.attacker.nation == entity("sudland")
    assert opened.battle.defender.nation == entity("norra")
    assert opened.battle.area == entity("norra_plain")


def test_the_side_that_steps_in_attacks_on_its_own_ground(tmp_path: Path) -> None:
    """Sudland's levy stands at a fort in the Norra Hills; Norra's levy steps in. Norra
    attacks, though it holds the hills: the side that entered attacks."""

    def fort(w: World) -> None:
        w["entities"].append(
            {
                "key": "hill_fort",
                "kind": "location",
                "name": "Hill Fort",
                "at": [150, 50],
                "within": "norra_hills",
            }
        )
        (levy,) = [f for f in w["features"] if f["key"] == "sudland_levy"]
        levy["places"] = ["hill_fort"]

    # Without holders, so Sudland's levy does not take the hills while it waits there.
    g = Logged(toy(tmp_path, fort, rules("territories", "battles")), "ilse", "tomas")
    assert territory.holder(g.state, entity("norra_hills")) == entity("norra")
    g.send("ilse", "norra_levy", "hill_fort")
    out = g.walk(day(1), day(8))
    (opened,) = payloads(out, ev.BattleOpened)
    assert opened.battle.area == entity("norra_hills")
    assert opened.battle.attacker.nation == entity("norra")
    assert opened.battle.defender.nation == entity("sudland")


def test_sea_fights_sea_and_an_air_piece_alone_does_not_fight(tmp_path: Path) -> None:
    def norra_galley(w: World) -> None:
        w["entities"].append(
            {
                "key": "far_reach",
                "kind": "location",
                "name": "The Far Reach",
                "at": [180, 250],
                "within": "open_sea",
            }
        )
        w["features"].append(
            {
                "key": "norra_galleys",
                "kind": "piece",
                "piece": "galley",
                "name": "The Norra Galleys",
                "side": "norra",
                "places": ["far_reach"],
                "tier": 2,
                "source": "toy",
            }
        )

    g = Logged(toy(tmp_path, norra_galley), "ilse", "tomas")
    # A broken sea piece falls back to a sea zone with no enemy sea piece in it.
    galleys = piece(g.state, "sudland_galleys")
    assert battle.fall_back(g.state, galleys, entity("the_gulf")) is None  # Norra's in the open sea
    g.send("ilse", "norra_galleys", "the_gulf")
    g.send("ilse", "norra_kites", "sudland_coast")
    out = g.walk(day(1), day(4))
    opened = payloads(out, ev.BattleOpened)
    assert [o.battle.area for o in opened] == [entity("the_gulf")]
    assert opened[0].battle.attacker.pieces == (entity("norra_galleys"),)
    assert opened[0].battle.defender.pieces == (entity("sudland_galleys"),)
    assert battle.fall_back(g.state, galleys, entity("the_gulf")) == entity("open_sea")


def test_a_land_piece_and_a_sea_piece_never_meet(tmp_path: Path) -> None:
    """Sudland's galleys stand at the Gulf Roads; a levy in the Norra Plain borders the
    gulf, but a battle needs land against land or sea against sea in one area."""
    g = Logged(toy(tmp_path), "ilse", "tomas")
    assert battle.fighting(g.state)[entity("the_gulf")] == [piece(g.state, "sudland_galleys")]
    assert not payloads(g.walk(day(1), day(3)), ev.BattleOpened)


def test_a_piece_that_fights_needs_a_strength(tmp_path: Path) -> None:
    assert "feature norra_levy: a piece that fights starts at strength 1 or more" in refused(
        toy(tmp_path, strengths(norra_levy=0))
    )
    created(toy(tmp_path, strengths(norra_herald=0)))  # an envoy never fights


# --- Rule 2: one round a world day, in the day walk after arrivals and contacts --------


def test_one_round_each_day_the_attacker_presses(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    out = g.walk(day(1), day(30))
    rounds = payloads(out, ev.BattleRound)
    (ended,) = payloads(out, ev.BattleEnded)
    assert [r.on for r in rounds] == [OPENS + timedelta(days=n) for n in range(len(rounds))]
    assert rounds[-1].on == ended.on


def test_the_round_follows_the_days_steps_and_comes_before_the_feeds(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    g.walk(day(1), day(11))
    out = g.walk(OPENS, OPENS)
    kinds = [e.kind for e in out]
    assert kinds.index("piece_stepped") < kinds.index("battle_opened")
    assert kinds.index("battle_opened") < kinds.index("battle_round")


def test_a_battle_adds_no_stop_to_the_clock(tmp_path: Path) -> None:
    """The wakes close on the same days with battles on as with them off."""
    closes = []
    for rule_set in (("territories", "holders", "battles"), ("territories", "holders")):
        (tmp_path / rule_set[-1]).mkdir()
        w = Wakes(to_coast(tmp_path / rule_set[-1], rules(*rule_set)))
        days = []
        for _ in range(3):
            w.close()
            days.append(w.state.in_world_date)
        closes.append(days)
        if "battles" in rule_set:
            assert w.state.battles == {} and payloads(w.log, ev.BattleEnded)
    assert closes[0] == closes[1]


# --- Rule 3: the score -------------------------------------------------------------------


def test_the_score_adds_strength_ground_terrain_air_supply_and_the_draw() -> None:
    assert battle.score(one(5), 2, defending=False, defence=2) == 7
    assert battle.score(one(4), 1, defending=True, defence=2) == 7
    assert battle.score(one(4, own_ground=True), 0, defending=True, defence=1) == 6
    assert battle.score(one(5, air=True), 0, defending=False, defence=0) == 6
    assert battle.score(one(5, supplied=False), 0, defending=False, defence=0) == 4
    two = SideIn(fighters=(Fighter("a", 3), Fighter("b", 2)), brought=5)
    assert battle.score(two, 1, defending=False, defence=0) == 6


def test_the_own_ground_bonus_is_the_defenders_only() -> None:
    assert battle.score(one(5, own_ground=True), 0, defending=False, defence=2) == 5


def test_draws_run_from_0_to_2() -> None:
    seen = {battle.draws(f"x{n}", d) for n in range(40) for d in range(3)}
    assert {a for a, _ in seen} == {b for _, b in seen} == set(range(DRAW_TOP + 1))


def test_the_worked_example_five_attack_four_on_their_own_forest() -> None:
    """A force of 5 attacks a force of 4 on its own forest (defence 1). Every pair of
    draws: the scores, each side's loss, and the result after the round."""
    table = {
        # (attacker draw, defender draw): (attacker score, defender score, steps lost)
        (0, 0): (5, 6, (1, 0)),
        (0, 1): (5, 7, (1, 0)),
        (0, 2): (5, 8, (2, 0)),
        (1, 0): (6, 6, (1, 1)),
        (1, 1): (6, 7, (1, 0)),
        (1, 2): (6, 8, (1, 0)),
        (2, 0): (7, 6, (0, 1)),
        (2, 1): (7, 7, (1, 1)),
        (2, 2): (7, 8, (1, 0)),
    }
    for want, (sa, sd, lost) in table.items():
        sides = Sides(attacker=one(5), defender=one(4, own_ground=True), defence=1)
        played = battle.simulate(sides, seed_for(want), 1)
        (r,) = played.rounds
        assert (r.draws, r.scores, (r.lost(0), r.lost(1))) == (want, (sa, sd), lost), want
        assert played.sides.attacker.fighters[0].strength == 5 - lost[0]
        assert played.sides.defender.fighters[0].strength == 4 - lost[1]
        assert played.ending is None  # nobody has lost half yet


def test_the_round_in_the_game_scores_by_the_rule(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    (first, *_) = payloads(g.walk(day(1), day(30)), ev.BattleRound)
    da, dd = first.draws
    # Norra: 5, its kites in range; Sudland: 4 on its own plain (defence 0).
    assert first.scores == (5 + da + 1, 4 + dd + 1)


def test_air_counts_only_within_its_range(tmp_path: Path) -> None:
    def far_kites(w: World) -> None:
        w["piece_kinds"] = [
            {**k, "range_steps": 1} if k["key"] == "kite" else k for k in w["piece_kinds"]
        ]

    g = to_coast(tmp_path, far_kites)
    (first, *_) = payloads(g.walk(day(1), day(30)), ev.BattleRound)
    da, dd = first.draws
    assert first.scores == (5 + da, 4 + dd + 1)


def test_a_side_out_of_supply_scores_one_less(tmp_path: Path) -> None:
    """With supply on and no source in the toy, every land piece is out of supply."""
    g = to_coast(tmp_path, rules("territories", "holders", "supply", "battles"))
    (first, *_) = payloads(g.walk(day(1), day(30)), ev.BattleRound)
    da, dd = first.draws
    assert first.scores == (5 + da + 1 - 1, 4 + dd + 1 - 1)


# --- Rule 4: the lower score loses a step from its strongest piece -------------------


def test_the_loss_for_each_margin() -> None:
    assert battle.losses(5, 5) == (1, 1)
    assert battle.losses(5, 6) == (1, 0)
    assert battle.losses(6, 5) == (0, 1)
    assert battle.losses(5, 5 + DOUBLE_MARGIN - 1) == (1, 0)
    assert battle.losses(5, 5 + DOUBLE_MARGIN) == (2, 0)
    assert battle.losses(5 + DOUBLE_MARGIN, 5) == (0, 2)


def test_the_step_comes_off_the_strongest_piece_then_the_lowest_id() -> None:
    att = SideIn(fighters=(Fighter("a", 2), Fighter("b", 3)), brought=5)
    played = battle.simulate(Sides(att, one(9)), seed_for((0, 0)), 1)
    # 5 against 9, a margin of 4: b drops to 2, then a and b tie and a has the lower id.
    assert played.rounds[0].hits[0] == (("b", 1), ("a", 1))
    even = SideIn(fighters=(Fighter("b", 2), Fighter("a", 2)), brought=4)
    played = battle.simulate(Sides(even, one(5)), seed_for((0, 0)), 1)
    assert played.rounds[0].hits[0] == (("a", 1),)


def test_the_game_takes_the_steps_off_the_pieces(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    g.walk(day(1), day(11))
    out = g.walk(OPENS, OPENS)
    (r,) = payloads(out, ev.BattleRound)
    assert piece(g.state, "norra_levy").tier == 5 - r.lost[0]
    assert piece(g.state, "sudland_levy").tier == 4 - r.lost[1]
    b = g.state.battles[entity(COAST)]
    assert (b.attacker.lost, b.defender.lost, b.rounds, b.pressed_on) == (*r.lost, 1, OPENS)


# --- Rule 5: a side breaks at half; forced back, or destroyed ---------------------------


def test_a_side_breaks_when_it_has_lost_half_rounded_up() -> None:
    assert not battle.broken(SideIn(fighters=(), brought=5, lost=2))
    assert battle.broken(SideIn(fighters=(), brought=5, lost=3))
    assert not battle.broken(SideIn(fighters=(), brought=4, lost=1))
    assert battle.broken(SideIn(fighters=(), brought=4, lost=2))


def test_the_broken_attacker_is_forced_back_to_ground_it_holds(tmp_path: Path) -> None:
    """In the toy's draws Norra's levy loses three of its five steps by day 14 and breaks;
    the only land next to the coast is the Norra Hills, which Norra holds."""
    g = to_coast(tmp_path)
    out = g.walk(day(1), day(30))
    (ended,) = payloads(out, ev.BattleEnded)
    assert (ended.ending, ended.winner, ended.on) == (Ending.HELD, entity("sudland"), day(14))
    forced = [p for p in payloads(out, ev.PieceStepped) if p.cause is StepCause.FORCED]
    assert [(p.left, p.entered, p.on) for p in forced] == [
        (entity(COAST), entity("norra_hills"), day(14))
    ]
    levy = piece(g.state, "norra_levy")
    assert levy.places == (entity("norra_hills"),) and levy.tier == 2 and in_play(levy)
    assert not levy.path and levy.bound_for is None
    assert g.state.battles == {}


def test_a_broken_defender_falls_back_nearest_its_capital_ties_to_the_lowest_key(
    tmp_path: Path,
) -> None:
    g = Logged(
        toy(
            tmp_path,
            link(COAST, "isle"),
            link(COAST, "norra_plain"),
            capital("sudland", "sudby"),
        ),
        "ilse",
        "tomas",
    )
    sudland = piece(g.state, "sudland_levy")
    assert battle.fall_back(g.state, sudland, entity(COAST)) == entity("isle")
    with_two = g.state.model_copy(
        update={
            "holders": {
                entity("norra_hills"): territory_holding("sudland"),
                entity("norra_plain"): territory_holding("sudland"),
            }
        }
    )
    # Hills, isle and plain are each one step from Sudby's coast: the lowest key wins.
    keys = sorted(["isle", "norra_hills", "norra_plain"])
    assert battle.fall_back(with_two, sudland, entity(COAST)) == entity(keys[0])
    # With the capital at Norrhavn, the plain (0 steps from it) beats the isle (1 step).
    board = with_two.map
    assert board is not None
    moved = board.model_copy(update={"capitals": {entity("sudland"): entity("norrhavn")}})
    far = with_two.model_copy(update={"map": moved})
    assert battle.fall_back(far, sudland, entity(COAST)) == entity("norra_plain")


def territory_holding(polity: str) -> Any:
    from revisionist.core.realism.holders import Holding

    return Holding(holder=entity(polity), on=START)


def test_with_nowhere_to_go_a_broken_piece_is_destroyed(tmp_path: Path) -> None:
    g = to_coast(tmp_path, strengths(norra_levy=5, sudland_levy=3))
    out = g.walk(day(1), day(30))
    (ended,) = payloads(out, ev.BattleEnded)
    assert ended.ending is Ending.WON
    levy = piece(g.state, "sudland_levy")
    assert levy.lost_on == ended.on and not in_play(levy)
    assert not [p for p in payloads(out, ev.PieceStepped) if p.cause is StepCause.FORCED]


def test_a_broken_defender_with_somewhere_to_go_steps_there(tmp_path: Path) -> None:
    g = to_coast(tmp_path, strengths(norra_levy=5, sudland_levy=3), link(COAST, "isle"), no_ferry)
    out = g.walk(day(1), day(30))
    forced = [p for p in payloads(out, ev.PieceStepped) if p.cause is StepCause.FORCED]
    assert [(p.nation, p.left, p.entered) for p in forced] == [
        (entity("sudland"), entity(COAST), entity("isle"))
    ]
    assert piece(g.state, "sudland_levy").places == (entity("isle"),)


# --- Rule 6: a piece at strength 0 is out of play; no defender left, the attacker wins ---


def test_a_piece_at_strength_0_is_out_of_play_and_the_count_starts(tmp_path: Path) -> None:
    g = to_coast(tmp_path, strengths(norra_levy=5, sudland_levy=1))
    out = g.walk(day(1), day(30))
    (ended,) = payloads(out, ev.BattleEnded)
    assert (ended.ending, ended.winner) == (Ending.WON, entity("norra"))
    levy = piece(g.state, "sudland_levy")
    assert levy.tier == 0 and levy.lost_on == ended.on and not in_play(levy)
    counted = [p for p in payloads(out, ev.CaptureCounted) if p.capture is not None]
    assert counted[0].capture.by == entity("norra") and counted[0].capture.since == ended.on
    (taken,) = held(out)
    assert (taken.area, taken.holder) == (entity(COAST), entity("norra"))
    assert taken.on == ended.on + timedelta(days=2)
    assert territory.holder(g.state, entity(COAST)) == entity("norra")


def test_a_lost_piece_never_moves_again(tmp_path: Path) -> None:
    g = to_coast(tmp_path, strengths(norra_levy=5, sudland_levy=1))
    g.walk(day(1), day(30))
    g.send("tomas", "sudland_levy", "norra_hills")
    g.walk(day(31), day(45))
    assert piece(g.state, "sudland_levy").places == (entity(COAST),)
    assert battle.fighting(g.state).get(entity(COAST), []) == [piece(g.state, "norra_levy")]


# --- Rule 7: a day without the attacker pressing; after LULL_DAYS it goes back ---------


def hold(g: Logged, key: str, posture: Posture | None = Posture.HOLD) -> None:
    f = piece(g.state, key)
    g.add([ev.FeatureSet(feature=f.model_copy(update={"posture": posture}))])


def test_no_round_on_a_day_the_attacker_does_not_press(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    g.walk(day(1), OPENS)
    hold(g, "norra_levy")
    out = g.walk(OPENS + timedelta(days=1), OPENS + timedelta(days=LULL_DAYS - 1))
    assert not payloads(out, ev.BattleRound)
    assert not payloads(out, ev.BattleEnded)
    hold(g, "norra_levy", None)
    out = g.walk(OPENS + timedelta(days=LULL_DAYS), OPENS + timedelta(days=LULL_DAYS))
    assert [r.on for r in payloads(out, ev.BattleRound)] == [OPENS + timedelta(days=LULL_DAYS)]


def test_after_the_lull_the_attacker_goes_back_where_it_came_from(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    g.walk(day(1), OPENS)
    hold(g, "norra_levy")
    out = g.walk(OPENS + timedelta(days=1), OPENS + timedelta(days=LULL_DAYS))
    (ended,) = payloads(out, ev.BattleEnded)
    assert (ended.ending, ended.on) == (Ending.LULL, OPENS + timedelta(days=LULL_DAYS))
    (back,) = payloads(out, ev.PieceStepped)
    assert (back.entered, back.cause) == (entity("norra_hills"), StepCause.FORCED)
    assert piece(g.state, "norra_levy").places == (entity("norra_hills"),)


def lulled(g: Logged, came_from: str) -> None:
    """The coast's battle open, its attacker recorded as come from ``came_from``, and Norra's
    levy put on hold."""
    g.walk(day(1), OPENS)
    b = g.state.battles[entity(COAST)]
    fid = FeatureId(entity("norra_levy"))
    b = b.model_copy(update={"came_from": {fid: entity(came_from)}})
    g.state = g.state.model_copy(update={"battles": {entity(COAST): b}})
    hold(g, "norra_levy")


def test_after_the_lull_an_attacker_from_a_non_bordering_area_falls_back(tmp_path: Path) -> None:
    """The area it came from does not border the battle (a landing, or a move the record
    made): it falls back by rule 5 instead, to the hills."""
    for came in ("norra_plain", "the_gulf"):
        (tmp_path / came).mkdir()
        g = to_coast(tmp_path / came)
        lulled(g, came)
        out = g.walk(OPENS + timedelta(days=1), OPENS + timedelta(days=LULL_DAYS))
        (ended,) = payloads(out, ev.BattleEnded)
        assert ended.ending is Ending.LULL
        assert piece(g.state, "norra_levy").places == (entity("norra_hills"),)


def test_after_the_lull_an_attacker_with_nowhere_to_go_stays_in_the_battle(
    tmp_path: Path,
) -> None:
    """With nowhere to go back to, the attacker stays and the battle stays open: no end,
    and no battle reopened every few days."""
    g = to_coast(tmp_path)
    lulled(g, "norra_plain")
    hills = entity("norra_hills")
    g.add([ev.AreaHeld(area=hills, holder=entity("sudland"), was=entity("norra"), on=OPENS)])
    out = g.walk(OPENS + timedelta(days=1), OPENS + timedelta(days=4 * LULL_DAYS))
    assert not [e for e in out if e.kind.startswith("battle_")]
    assert not payloads(out, ev.NewsReported)
    assert piece(g.state, "norra_levy").places == (entity(COAST),)
    assert list(g.state.battles) == [entity(COAST)]
    hold(g, "norra_levy", None)
    out = g.walk(
        OPENS + timedelta(days=4 * LULL_DAYS + 1), OPENS + timedelta(days=4 * LULL_DAYS + 1)
    )
    assert payloads(out, ev.BattleRound)  # pressing again, it fights on


def test_the_lull_in_simulate() -> None:
    sides = Sides(one(5), one(4), presses=False)
    played = battle.simulate(sides, "s", LULL_DAYS - 1)
    assert played.rounds == () and played.ending is None
    played = battle.simulate(sides, "s", LULL_DAYS)
    assert played.rounds == () and played.ending is Ending.LULL
    assert battle.simulate(sides._replace(lull=LULL_DAYS - 1), "s", 1).ending is Ending.LULL


# --- Rule 8: simulate is pure and the only place rules 3 to 7 are written --------------


def test_simulate_is_a_pure_function() -> None:
    sides = Sides(one(5, air=True), one(4, own_ground=True), defence=1)
    assert battle.simulate(sides, "seed", 10) == battle.simulate(sides, "seed", 10)
    played = battle.simulate(sides, "seed", 10)
    assert played.ending is not None and len(played.rounds) <= 10


def test_the_walk_plays_its_rounds_through_simulate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Sides, int]] = []
    real = battle.simulate

    def spy(sides: Sides, seed: str, days: int) -> battle.Played:
        calls.append((sides, days))
        return real(sides, seed, days)

    monkeypatch.setattr(battle, "simulate", spy)
    g = to_coast(tmp_path)
    out = g.walk(day(1), day(30))
    assert len(calls) == len(payloads(out, ev.BattleRound)) and calls
    assert all(days == 1 for _, days in calls)


def test_the_seed_is_the_campaign_day_area_and_sorted_pieces(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    a, b = FeatureId(entity("norra_levy")), FeatureId(entity("sudland_levy"))
    area = entity(COAST)
    s = battle.seed(g.state, area, OPENS, [a, b])
    assert s == battle.seed(g.state, area, OPENS, [b, a])
    assert s != battle.seed(g.state, area, OPENS + timedelta(days=1), [a, b])
    assert s != battle.seed(g.state, entity("isle"), OPENS, [a, b])


# --- Rule 9: news for the opening and the end; a report to each commander per round ----


def test_one_public_news_item_for_the_opening_and_one_for_the_end(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    out = g.walk(day(1), day(30))
    news = [p.news for p in payloads(out, ev.NewsReported)]
    assert [n.headline for n in news] == [
        "Battle at The Sudland Coast: Norra attacks Sudland",
        "Battle at The Sudland Coast ends: Sudland holds",
    ]
    for e in out:
        if isinstance(e.payload, ev.NewsReported):
            assert e.scope.visibility is Visibility.PUBLIC


def test_each_side_gets_a_report_after_every_round(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    out = g.walk(day(1), day(30))
    rounds = payloads(out, ev.BattleRound)
    for person, side in (("ilse", 0), ("tomas", 1)):
        mine = [
            e.payload.document
            for e in out
            if isinstance(e.payload, ev.DocumentIssued)
            and e.payload.document.title.startswith("Battle at")
            and e.scope.known_by == frozenset({seat(person)})
        ]
        assert [d.issued for d in mine] == [r.on for r in rounds]
        for d, r in zip(mine, rounds, strict=True):
            body = {line.label: line.value for line in d.body}
            assert body["Our losses"] == f"{r.lost[side]} steps"
            assert body["Enemy losses seen"] == f"{r.lost[1 - side]} steps"
            assert "strength" not in str(body).lower()


def test_the_battle_events_are_engine_only(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    out = g.walk(day(1), day(30))
    secret = [e for e in out if e.kind.startswith("battle_")]
    assert secret
    for e in secret:
        assert e.scope.visibility is Visibility.RESTRICTED
        assert not e.scope.known_by & {seat("ilse"), seat("tomas")}
    for kind in ("battle_opened", "battle_round", "battle_ended"):
        assert kind in catchup.NEVER
    for person in ("ilse", "tomas"):
        fed = catchup.feed(g.state, g.log, seat(person), 0, 10)
        assert not [f for f in fed if f.event.kind.startswith("battle_")]


# --- Rule 10: gated by battles ------------------------------------------------------------


def test_without_the_rule_no_battle(tmp_path: Path) -> None:
    g = to_coast(tmp_path, rules("territories", "holders"))
    out = g.walk(day(1), day(30))
    assert not [e for e in out if e.kind.startswith("battle_")]
    assert piece(g.state, "sudland_levy").tier == 4
    assert battle.walk(g.state, g.state, day(31)) == []


def test_a_stored_game_gains_no_battles() -> None:
    world = cmp.load_world(Path(__file__).parent / "worlds" / "territory-toy.yaml")
    events, state = created(world)
    dumped = state.model_dump(mode="json")
    assert "battles" not in dumped
    assert all("lost_on" not in f for f in dumped["features"].values())
    assert state_hash(replay(events)) == state_hash(state)


def test_the_fold_refuses_battle_events_the_walk_would_never_land(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    g.walk(day(1), day(11))
    out = g.walk(OPENS, OPENS)
    (opened,) = payloads(out, ev.BattleOpened)
    coast = entity(COAST)
    for bad in (
        ev.BattleOpened(battle=opened.battle, on=OPENS),  # already open
        ev.BattleRound(area=coast, on=OPENS, scores=(1, 1), draws=(0, 0), lost=(1, 1)),
        ev.BattleRound(area=entity("isle"), on=day(13), scores=(1, 1), draws=(0, 0), lost=(1, 1)),
        ev.BattleEnded(area=coast, on=day(13), ending=Ending.WON, winner=entity("ilse")),
        ev.BattleEnded(area=entity("isle"), on=day(13), ending=Ending.WON, winner=entity("norra")),
    ):
        with pytest.raises(FoldError):
            g.add([bad])
    (tmp_path / "off").mkdir()
    off = Logged(toy(tmp_path / "off", rules("territories", "holders")), "ilse", "tomas")
    with pytest.raises(FoldError):
        off.add([ev.BattleOpened(battle=opened.battle, on=OPENS)])


# --- Invariant 3: the same filings in any order or sittings give the same battle -------


def test_filings_in_either_order_give_the_same_battle_across_two_wakes(tmp_path: Path) -> None:
    """Two seats' moves filed in either order, or over more sittings, give the same battle,
    round for round, though it opens in the first wake and runs into the second."""
    world = toy(tmp_path, strengths(norra_levy=5, sudland_levy=5), horizon(12))
    north = order("ilse", "norra_levy", "sudby")
    kites = order("ilse", "norra_kites", "norra_hills", n=2)
    south = order("tomas", "sudland_galleys", "open_sea")

    def run(batches: Sequence[Sequence[Any]]) -> tuple[str, list[tuple[Any, ...]]]:
        from revisionist.core.realism.resolvers import apply_changes, movement

        g = Logged(world, "ilse", "tomas")
        for batch in batches:
            for o in batch:
                g.add(apply_changes(g.state, movement.order_changes(g.state, o)))
            # A sitting that changes nothing but the record count.
            g.add([ev.FeatureSet(feature=piece(g.state, "norra_herald"))])
        w = Wakes(g)
        found: list[tuple[Any, ...]] = []
        for wake in range(2):
            out = w.close()
            found += [
                (wake, e.kind, e.payload.model_dump_json())
                for e in out
                if e.kind.startswith("battle_")
            ]
        return digest(w.state), found

    a = run([[north, kites, south]])
    b = run([[south], [kites], [north]])
    assert a == b
    wakes = {wake for wake, _, _ in a[1]}
    assert wakes == {0, 1}  # the battle runs across the two wakes
