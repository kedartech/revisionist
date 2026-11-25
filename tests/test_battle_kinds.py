"""Battles read the kinds that fight them (KBA).

The toy world of ``tests/test_battles.py``: territories, holders and battles on, Norra and
Sudland at war, and ``kinds_in_battle`` switched on unless a test says otherwise. Norra's
levy (strength 5) steps into the Sudland Coast (plain) on day 12, where Sudland's levy
(strength 4) stands on its own ground; Norra's kites, two air steps off, support Norra.
Sudland's galleys stand in the Gulf, one step from the coast.

Each test plays twin worlds that differ in one figure or in the switch and reads the first
round: the draws are the same in both, so the scores differ only where the rule says.
"""

from collections.abc import Callable
from datetime import timedelta
from itertools import count
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.realism import battle, holders
from revisionist.core.realism.battle import Fighter, SideIn, Sides
from tests.test_adjacency_moves import Logged, World, day, entity, piece, where
from tests.test_battles import OPENS, one, payloads, rules, seed_for, strengths, to_coast, toy
from tests.test_head_on import MEETS, head_on
from tests.test_holders import ISLE, to_isle, without

COAST = "sudland_coast"
SWITCH = "kinds_in_battle"
_dirs = count()


def switched(w: World) -> None:
    w["rules"] = [*w.get("rules", ()), SWITCH]


def figures(key: str, **fields: Any) -> Callable[[World], None]:
    """The world's kind ``key`` with ``fields`` set."""

    def change(w: World) -> None:
        (found,) = [k for k in w["piece_kinds"] if k["key"] == key]
        found.update(fields)

    return change


def kind_like(base: str, key: str, **fields: Any) -> Callable[[World], None]:
    """A new kind ``key``: a copy of ``base`` with ``fields`` set."""

    def change(w: World) -> None:
        (found,) = [k for k in w["piece_kinds"] if k["key"] == base]
        w["piece_kinds"].append({**found, "key": key, "name": key.title(), **fields})

    return change


def as_kind(feature: str, kind: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        (found,) = [f for f in w["features"] if f["key"] == feature]
        found["piece"] = kind

    return change


def galleys_at_sea(w: World) -> None:
    """Sudland's galleys out in the Open Sea, two steps from the coast."""
    w["entities"].append(
        {"key": "far_reach", "kind": "location", "name": "The Far Reach", "at": [180, 250]}
        | {"within": "open_sea"}
    )
    (galleys,) = [f for f in w["features"] if f["key"] == "sudland_galleys"]
    galleys["places"] = ["far_reach"]


def coast(tmp: Path, *changes: Callable[[World], None], on: bool = True) -> Logged:
    """Norra's levy sent into the coast, the switch on or off, ``changes`` applied."""
    where = tmp / f"w{next(_dirs)}"
    where.mkdir()
    return to_coast(where, *changes, *((switched,) if on else ()))


def first(tmp: Path, *changes: Callable[[World], None], on: bool = True) -> ev.BattleRound:
    """The coast battle's first round."""
    rounds: list[ev.BattleRound] = payloads(
        coast(tmp, *changes, on=on).walk(day(1), OPENS), ev.BattleRound
    )
    assert rounds and rounds[0].on == OPENS
    return rounds[0]


def shift(tmp: Path, *changes: Callable[[World], None]) -> tuple[int, int]:
    """How far ``changes`` move each side's first-round score, the switch on, against
    the same world with the switch on and no change."""
    base, changed = first(tmp), first(tmp, *changes)
    assert changed.draws == base.draws
    return changed.scores[0] - base.scores[0], changed.scores[1] - base.scores[1]


def battle_events(out: list[ev.Event]) -> list[Any]:
    kinds = (ev.BattleOpened, ev.BattleRound, ev.BattleEnded, ev.PieceStepped, ev.AreaHeld)
    return [e.payload for e in out if isinstance(e.payload, kinds)]


# --- the pure rule: a piece adds its strength and its figure less 3 -----------------------


def test_a_piece_adds_its_strength_and_its_figure_less_3() -> None:
    side = SideIn(fighters=(Fighter("a", 3), Fighter("b", 2)), brought=5)
    edges = {"a": 2, "b": -1}
    assert battle.score(side, 1, False, 0, edges) == (3 + 2) + (2 - 1) + 1


def test_a_piece_with_no_figure_adds_its_strength_as_before() -> None:
    side = SideIn(fighters=(Fighter("a", 3), Fighter("b", 2)), brought=5)
    assert battle.score(side, 1, defending=False, defence=0) == 6
    assert battle.score(side, 1, False, 0, {"a": 0}) == 6


def test_a_piece_never_takes_away_from_its_side() -> None:
    """[proposed] A weak piece of a poor kind adds nothing, never less than nothing."""
    side = SideIn(fighters=(Fighter("a", 1), Fighter("b", 2)), brought=3)
    assert battle.score(side, 0, False, 0, {"a": -2}) == 2


def test_a_striking_piece_in_the_fight_adds_no_strength() -> None:
    side = SideIn(fighters=(Fighter("a", 3), Fighter("c", 4)), brought=7)
    assert battle.score(side, 0, False, 0, {"c": 1}, frozenset({"c"})) == 3


def test_simulate_scores_each_side_with_its_own_edges() -> None:
    sides = Sides(attacker=one(4), defender=one(4), edges=((("p", 1),), (("p", -2),)))
    (r,) = battle.simulate(sides, seed_for((0, 0)), 1).rounds
    assert r.scores == (5, 2)


# --- keeps: with the switch off a battle is today's; on with no figures, the same --------


def test_with_the_switch_off_the_figures_change_nothing(tmp_path: Path) -> None:
    plain = coast(tmp_path, on=False).walk(day(1), day(30))
    shaped = (
        figures("levy", attack=5, defence=1, on_terrain={"plain": {"defence": 2}}),
        figures("galley", strike_steps=1, covers=True),
        figures("kite", against=[{"facing": "levy", "attack": 2}]),
    )
    out = coast(tmp_path, *shaped, on=False).walk(day(1), day(30))
    assert payloads(out, ev.BattleEnded)
    assert battle_events(out) == battle_events(plain)


def test_with_no_figures_the_switch_on_plays_as_off(tmp_path: Path) -> None:
    off = coast(tmp_path, on=False).walk(day(1), day(30))
    on = coast(tmp_path).walk(day(1), day(30))
    assert payloads(on, ev.BattleEnded)
    assert battle_events(on) == battle_events(off)


def test_a_battle_with_the_switch_on_is_the_same_from_the_same_seed(tmp_path: Path) -> None:
    shaped = figures("levy", attack=4, against=[{"facing": "air", "defence": -1}])
    one = coast(tmp_path, shaped).walk(day(1), day(30))
    two = coast(tmp_path, shaped).walk(day(1), day(30))
    assert battle_events(one) == battle_events(two)


# --- rule 1: attack for the side that attacks, defence for the side that defends ---------


def test_the_attacker_reads_its_attack_and_the_defender_its_defence(tmp_path: Path) -> None:
    assert shift(tmp_path, figures("levy", attack=5)) == (2, 0)
    assert shift(tmp_path, figures("levy", defence=1)) == (0, -2)
    assert shift(tmp_path, figures("levy", attack=1, defence=4)) == (-2, 1)


def test_the_switch_off_reads_no_figure(tmp_path: Path) -> None:
    base = first(tmp_path, on=False)
    off = first(tmp_path, figures("levy", attack=5, defence=1), on=False)
    assert off.scores == base.scores


def test_the_terrain_fought_on_changes_the_figure_it_names(tmp_path: Path) -> None:
    """The coast is plain."""
    assert shift(tmp_path, figures("levy", on_terrain={"plain": {"defence": 2}})) == (0, 2)
    assert shift(tmp_path, figures("levy", on_terrain={"plain": {"attack": -1}})) == (-1, 0)
    assert shift(tmp_path, figures("levy", on_terrain={"hills": {"attack": 2}})) == (0, 0)


def test_the_terrain_changes_the_figure_before_it_is_held_to_the_range(
    tmp_path: Path,
) -> None:
    shaped = figures("levy", attack=5, on_terrain={"plain": {"attack": 2}})
    assert shift(tmp_path, shaped) == (2, 0)


def test_what_stands_on_the_other_side_changes_the_figure(tmp_path: Path) -> None:
    """Each side faces the other's levy; Sudland also faces Norra's kites, whose support
    puts them on Norra's side."""
    against = [{"facing": "levy", "attack": 1}]
    assert shift(tmp_path, figures("levy", against=against)) == (1, 0)
    assert shift(tmp_path, figures("levy", against=[{"facing": "kite", "defence": -1}])) == (
        0,
        -1,
    )
    assert shift(tmp_path, figures("levy", against=[{"facing": "air", "defence": -2}])) == (
        0,
        -2,
    )
    assert shift(tmp_path, figures("levy", against=[{"facing": "galley", "attack": 2}])) == (
        0,
        0,
    )


def test_a_change_for_no_enemy_air_holds_only_where_the_enemy_has_none(
    tmp_path: Path,
) -> None:
    """Sudland has no air piece; Norra's kites have the coast in range."""
    against = [{"facing": "levy", "attack": 1, "defence": 1, "when": "no_enemy_air"}]
    assert shift(tmp_path, figures("levy", against=against)) == (1, 0)


def test_a_change_for_an_enemy_out_of_supply_holds_only_then(tmp_path: Path) -> None:
    """With supply on, Sudland's levy on the coast is out of supply and Norra's is in it
    (``tests/test_battles.py``); with supply off, both are in it."""
    supplied = rules("territories", "holders", "supply", "battles")
    against = [{"facing": "levy", "attack": 1, "defence": 1, "when": "enemy_out_of_supply"}]
    base = first(tmp_path, supplied)
    changed = first(tmp_path, supplied, figures("levy", against=against))
    assert (changed.scores[0] - base.scores[0], changed.scores[1] - base.scores[1]) == (1, 0)
    assert shift(tmp_path, figures("levy", against=against)) == (0, 0)


# --- rule 2: a striking kind supports from afar and is no fighter there ------------------


def test_a_striking_kind_within_its_steps_gives_its_side_air_support(tmp_path: Path) -> None:
    assert shift(tmp_path, figures("galley", strike_steps=1)) == (0, battle.AIR_SUPPORT)


def test_a_striking_kind_beyond_its_steps_gives_nothing(tmp_path: Path) -> None:
    base = first(tmp_path, galleys_at_sea)
    near = first(tmp_path, galleys_at_sea, figures("galley", strike_steps=1))
    far = first(tmp_path, galleys_at_sea, figures("galley", strike_steps=2))
    assert near.scores == base.scores
    assert far.scores[1] - base.scores[1] == battle.AIR_SUPPORT


def test_with_the_switch_off_a_striking_kind_gives_nothing(tmp_path: Path) -> None:
    base = first(tmp_path, on=False)
    assert first(tmp_path, figures("galley", strike_steps=1), on=False).scores == base.scores


def test_a_striking_kind_takes_no_loss_from_afar(tmp_path: Path) -> None:
    """Sudland's levy at strength 2, so the galleys (3) would be its strongest piece."""
    g = coast(tmp_path, figures("galley", strike_steps=1), strengths(sudland_levy=2))
    out = g.walk(day(1), day(30))
    (opened,) = payloads(out, ev.BattleOpened)
    assert entity("sudland_galleys") not in opened.battle.defender.pieces
    assert payloads(out, ev.BattleEnded)
    galleys = piece(g.state, "sudland_galleys")
    assert galleys.tier == 3 and galleys.lost_on is None


def flattop(tmp: Path, on: bool = True) -> Logged:
    """Norra's flattop (a sea kind that strikes one step) sent from the Open Sea into the
    Gulf, where Sudland's galleys stand; Norra's kites off the board."""

    def norra_flattop(w: World) -> None:
        w["entities"].append(
            {"key": "far_reach", "kind": "location", "name": "The Far Reach", "at": [180, 250]}
            | {"within": "open_sea"}
        )
        w["features"].append(
            {"key": "norra_galleys", "kind": "piece", "piece": "flattop"}
            | {"name": "The Norra Flattop", "side": "norra", "places": ["far_reach"]}
            | {"tier": 2, "source": "toy"}
        )

    where = tmp / f"w{next(_dirs)}"
    where.mkdir()
    changes = (without("norra_kites"), kind_like("galley", "flattop", strike_steps=1))
    world = toy(where, *changes, norra_flattop, *((switched,) if on else ()))
    g = Logged(world, "ilse", "tomas")
    g.send("ilse", "norra_galleys", "gulf_roads")
    return g


def test_a_striking_kind_in_the_fight_supports_and_adds_no_strength(tmp_path: Path) -> None:
    out = flattop(tmp_path).walk(day(1), day(6))
    (opened,) = payloads(out, ev.BattleOpened)
    assert opened.battle.attacker.pieces == (entity("norra_galleys"),)
    r = payloads(out, ev.BattleRound)[0]
    assert r.scores[0] == r.draws[0] + battle.AIR_SUPPORT
    off = payloads(flattop(tmp_path, on=False).walk(day(1), day(6)), ev.BattleRound)[0]
    assert off.draws == r.draws
    assert off.scores[0] == 2 + off.draws[0]


def test_a_striking_kind_in_the_fight_takes_its_losses(tmp_path: Path) -> None:
    g = flattop(tmp_path)
    out = g.walk(day(1), day(6))
    lost = sum(r.lost[0] for r in payloads(out, ev.BattleRound))
    assert lost >= 1
    ships = piece(g.state, "norra_galleys")
    assert ships.tier == max(0, 2 - lost)


# --- rule 3: a kind that covers, in range, cancels the other side's air ------------------


def test_a_covering_kind_in_range_cancels_the_other_sides_air(tmp_path: Path) -> None:
    base = first(tmp_path, figures("galley", strike_steps=1))
    covered = first(tmp_path, figures("galley", strike_steps=1, covers=True))
    assert covered.draws == base.draws
    assert (covered.scores[0] - base.scores[0], covered.scores[1] - base.scores[1]) == (
        -battle.AIR_SUPPORT,
        0,
    )


def test_a_covering_kind_out_of_range_cancels_nothing(tmp_path: Path) -> None:
    """The galleys strike nothing, so their range is their own sea zone; the coast is a
    step away."""
    assert shift(tmp_path, figures("galley", covers=True)) == (0, 0)


def test_with_the_switch_off_a_covering_kind_cancels_nothing(tmp_path: Path) -> None:
    base = first(tmp_path, on=False)
    shaped = figures("galley", strike_steps=1, covers=True)
    assert first(tmp_path, shaped, on=False).scores == base.scores


# --- rule 4: a kind that may not attack never opens a battle -----------------------------

PORTER = kind_like("levy", "porter", may_attack=False)


def test_a_kind_that_may_not_attack_enters_and_opens_no_battle_that_day(
    tmp_path: Path,
) -> None:
    g = coast(tmp_path, PORTER, as_kind("norra_levy", "porter"))
    out = g.walk(day(1), OPENS)
    assert where(g.state, "norra_levy") == entity(COAST)  # the step is not refused
    assert payloads(out, ev.BattleOpened) == []
    after = OPENS + timedelta(days=1)
    (opened,) = payloads(g.walk(after, after), ev.BattleOpened)
    assert opened.battle.attacker.nation == entity("sudland")
    assert opened.battle.defender.pieces == (entity("norra_levy"),)


def test_with_the_switch_off_the_same_kind_attacks_on_the_day(tmp_path: Path) -> None:
    g = coast(tmp_path, PORTER, as_kind("norra_levy", "porter"), on=False)
    (opened,) = payloads(g.walk(day(1), OPENS), ev.BattleOpened)
    assert opened.battle.attacker.nation == entity("norra")


def test_two_kinds_that_may_not_attack_never_fight(tmp_path: Path) -> None:
    g = coast(tmp_path, PORTER, as_kind("norra_levy", "porter"), as_kind("sudland_levy", "porter"))
    assert payloads(g.walk(day(1), day(30)), ev.BattleOpened) == []


def meeting(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    where = tmp / f"w{next(_dirs)}"
    where.mkdir()
    return head_on(where, switched, *changes)


def test_a_kind_that_may_not_attack_does_not_lead_a_meeting(tmp_path: Path) -> None:
    """Sudland's levy has the lower id and leads the meeting on the border; as a kind that
    may not attack it leaves the lead to Norra's."""
    (led,) = payloads(meeting(tmp_path).walk(day(1), MEETS), ev.BattleOpened)
    assert led.battle.attacker.nation == entity("sudland")
    g = meeting(tmp_path, PORTER, as_kind("sudland_levy", "porter"))
    (opened,) = payloads(g.walk(day(1), MEETS), ev.BattleOpened)
    assert opened.battle.meeting and opened.battle.attacker.nation == entity("norra")


def test_a_meeting_on_a_border_reads_no_terrain(tmp_path: Path) -> None:
    """The meeting is kept under the coast (plain); the border has no terrain."""
    rounds = [
        payloads(g.walk(day(1), MEETS), ev.BattleRound)[0]
        for g in (
            meeting(tmp_path),
            meeting(tmp_path, figures("levy", on_terrain={"plain": {"attack": 2, "defence": 2}})),
        )
    ]
    assert rounds[0].draws == rounds[1].draws
    assert rounds[0].scores == rounds[1].scores
    shaped = meeting(tmp_path, figures("levy", attack=5))
    assert payloads(shaped.walk(day(1), MEETS), ev.BattleRound)[0].scores[0] == (
        rounds[0].scores[0] + 2
    )


def test_two_kinds_that_may_not_attack_meet_no_battle_on_a_border(tmp_path: Path) -> None:
    g = meeting(
        tmp_path, PORTER, as_kind("sudland_levy", "porter"), as_kind("norra_levy", "porter")
    )
    assert payloads(g.walk(day(1), day(20)), ev.BattleOpened) == []


def test_a_winner_that_may_not_attack_steps_in_and_opens_no_battle(tmp_path: Path) -> None:
    """Norra leads the meeting and withdraws from it; Sudland's porter completes its step
    into the hills, where Norra's levy stands, and no battle opens that day."""
    from revisionist.core.realism.effect import Posture

    g = meeting(tmp_path, PORTER, as_kind("sudland_levy", "porter"))
    g.walk(day(1), MEETS)
    on = MEETS + timedelta(days=1)
    landed = battle.land_posture(g.state, piece(g.state, "norra_levy"), Posture.WITHDRAW, None, on)
    assert landed is not None
    g.add(landed)
    out = g.walk(on, on)
    assert payloads(out, ev.BattleEnded)
    assert where(g.state, "sudland_levy") == entity("norra_hills")
    assert payloads(out, ev.BattleOpened) == []


# --- rule 5: a kind that does not hold ground takes no territory -------------------------

RAIDER = kind_like("levy", "raider", holds_ground=False)


def isle(tmp: Path, *changes: Callable[[World], None], on: bool = True) -> Logged:
    where = tmp / f"w{next(_dirs)}"
    where.mkdir()
    return to_isle(where, *changes, *((switched,) if on else ()))


def test_a_kind_that_does_not_hold_ground_never_takes_a_territory(tmp_path: Path) -> None:
    g = isle(tmp_path, RAIDER, as_kind("norra_levy", "raider"))
    out = g.walk(day(1), day(20))
    assert where(g.state, "norra_levy") == entity(ISLE)
    assert [p for p in payloads(out, ev.AreaHeld)] == []
    assert holders.takers(g.state, entity(ISLE)) == ()
    assert g.state.captures.get(entity(ISLE)) is None


def test_with_the_switch_off_the_same_kind_takes_it(tmp_path: Path) -> None:
    g = isle(tmp_path, RAIDER, as_kind("norra_levy", "raider"), on=False)
    out = g.walk(day(1), day(20))
    assert [(p.area, p.holder) for p in payloads(out, ev.AreaHeld)] == [
        (entity(ISLE), entity("norra"))
    ]


def test_a_kind_that_holds_ground_takes_it_with_the_switch_on(tmp_path: Path) -> None:
    out = isle(tmp_path).walk(day(1), day(20))
    assert [p.holder for p in payloads(out, ev.AreaHeld)] == [entity("norra")]


# --- rule 6: the loss falls on the strongest piece, ties to the lowest id -----------------


def test_the_loss_falls_on_the_strongest_piece_not_the_best_figure() -> None:
    """Piece ``a`` is stronger and adds less; the attacker loses the round."""
    att = SideIn(fighters=(Fighter("a", 3), Fighter("b", 2)), brought=5)
    dfn = SideIn(fighters=(Fighter("d", 9),), brought=9)
    edges = ((("a", -2), ("b", 2)), ())
    played = battle.simulate(Sides(attacker=att, defender=dfn, edges=edges), "seed", 1)
    (r,) = played.rounds
    assert {h for h, _ in r.hits[0]} == {"a"}
    assert played.sides.attacker.fighters[1] == Fighter("b", 2)


def test_equal_strengths_lose_from_the_lowest_id_whatever_the_figure() -> None:
    att = SideIn(fighters=(Fighter("a", 2), Fighter("b", 2)), brought=4)
    dfn = SideIn(fighters=(Fighter("d", 9),), brought=9)
    edges = ((("a", 2), ("b", -1)), ())
    (r,) = battle.simulate(Sides(attacker=att, defender=dfn, edges=edges), "seed", 1).rounds
    assert r.hits[0][0][0] == "a"
