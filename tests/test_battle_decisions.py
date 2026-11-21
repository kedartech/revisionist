"""One decision a wake, and a standing contingency for each force (BDC).

The toy world of ``tests/test_battles.py``: territories, holders and battles on, Norra and
Sudland at war. Norra's levy, sent to Sudby, steps into the Sudland Coast on day 12 and
attacks Sudland's levy there. ``link(COAST, "isle")`` gives Sudland somewhere of its own
to go; ``no_ferry`` keeps Norra's levy off the Isle on its way in.

The seam is two functions in ``battle.py``: ``land_posture`` and ``land_contingency``. The
path from a filed order through ``apply.py`` is DLN's; these tests call the seam directly
and set a force's fields where an order would have set them.
"""

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.ids import FeatureId, OrderId
from revisionist.core.project import project
from revisionist.core.realism import battle
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.battle import OUTNUMBERED, Battle, BattleSide, Decision, Ending
from revisionist.core.realism.effect import (
    Contingency,
    ContingencyKind,
    Deal,
    Engagement,
    MoveForce,
    Posture,
    SetEngagement,
)
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.resolvers import apply_changes, movement
from revisionist.core.realism.territory import StepCause
from revisionist.core.state import State, Wake
from revisionist.engine import estimate, options, wake
from tests.test_adjacency_moves import Logged, World, day, entity, order, piece, seat
from tests.test_battles import (
    COAST,
    OPENS,
    horizon,
    link,
    no_ferry,
    payloads,
    strengths,
    to_coast,
    toy,
)
from tests.test_holders import Wakes, capital

ISLE = "isle"


def second_levy(w: World) -> None:
    """A second Norra levy at Norrhavn, strength 3: on neither side until it joins."""
    w["features"].append(
        {
            "key": "second_levy",
            "kind": "piece",
            "piece": "levy",
            "name": "The Second Levy",
            "side": "norra",
            "places": ["norrhavn"],
            "tier": 3,
            "source": "toy",
        }
    )


def opened(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    """The coast's battle open after its first round (day 12), Sudland able to reach the
    Isle."""
    g = to_coast(tmp, link(COAST, ISLE), no_ferry, *changes)
    g.walk(day(1), OPENS)
    assert entity(COAST) in g.state.battles
    return g


def fight(g: Logged) -> Battle:
    return g.state.battles[entity(COAST)]


def at_wake(state: State, n: int) -> State:
    return state.model_copy(update={"wake": Wake(number=n, deadline=datetime(1900, 5, 1, 12, 0))})


def contingent(g: Logged, key: str, c: Contingency, on: date = OPENS) -> None:
    """Set ``key``'s contingency as an engagement order would (``land_contingency``)."""
    f = piece(g.state, key)
    effect = SetEngagement(force=f.feature_id, zone="here", rule=Engagement.DEFEND, contingency=c)
    g.add([ev.FeatureSet(feature=battle.land_contingency(f, effect, on))])


def decide(g: Logged, key: str, posture: Posture | None, to: str | None = None) -> list[Any]:
    """Land a posture on ``key`` through ``land_posture`` the day after the last walked."""
    on = (fight(g).pressed_on or OPENS) + timedelta(days=1)
    landed = battle.land_posture(
        g.state, piece(g.state, key), posture, entity(to) if to else None, on
    )
    assert landed is not None
    g.add(landed)
    return landed


def walk_day(g: Logged, d: date) -> list[ev.Event]:
    return g.walk(d, d)


def steps_of(out: Sequence[ev.Event], nation: str) -> list[ev.PieceStepped]:
    return [p for p in payloads(out, ev.PieceStepped) if p.nation == entity(nation)]


# --- Rule 10: the seam returns None for a force in no battle -----------------------------


def test_land_posture_is_none_for_a_force_in_no_battle(tmp_path: Path) -> None:
    g = to_coast(tmp_path, second_levy)
    levy = piece(g.state, "norra_levy")
    assert battle.land_posture(g.state, levy, Posture.HOLD, None, day(1)) is None  # no battle
    g.walk(day(1), OPENS)
    home = piece(g.state, "second_levy")  # at Norrhavn, far from the battle
    for posture in (*Posture, None):
        assert battle.land_posture(g.state, home, posture, None, OPENS) is None


def test_land_posture_is_none_without_the_battles_rule(tmp_path: Path) -> None:
    g = opened(tmp_path)
    off = g.state.model_copy(
        update={"rules": g.state.rules - {r for r in g.state.rules if r.value == "battles"}}
    )
    assert battle.land_posture(off, piece(off, "norra_levy"), Posture.HOLD, None, OPENS) is None


def test_patrol_and_escort_are_no_battle_decision(tmp_path: Path) -> None:
    g = opened(tmp_path)
    for posture in (Posture.PATROL, Posture.ESCORT):
        assert (
            battle.land_posture(g.state, piece(g.state, "norra_levy"), posture, None, OPENS) is None
        )


# --- Rules 1 and 2: one decision, from the first round on or after its day ---------------


def test_a_hold_decision_stops_the_attacker_pressing_from_its_day(tmp_path: Path) -> None:
    g = opened(tmp_path)
    landed = decide(g, "norra_levy", Posture.HOLD)
    assert isinstance(landed[0], ev.FeatureSet)  # the force's feature_set first
    (decided,) = [p for p in landed if isinstance(p, ev.BattleDecided)]
    assert (decided.decision, decided.nation, decided.on) == (
        Decision.HOLD,
        entity("norra"),
        OPENS + timedelta(days=1),
    )
    assert fight(g).attacker.decision is Decision.HOLD
    assert piece(g.state, "norra_levy").posture is Posture.HOLD
    out = walk_day(g, OPENS + timedelta(days=1))
    assert not payloads(out, ev.BattleRound)  # held: no round
    assert fight(g).rounds == 1


def test_the_rounds_before_a_decisions_day_are_fought_as_before(tmp_path: Path) -> None:
    """A decision is not applied mid-wake: walking the day before it lands gives a round."""
    g = opened(tmp_path)
    out = walk_day(g, OPENS + timedelta(days=1))
    assert len(payloads(out, ev.BattleRound)) == 1  # no decision yet: the attacker presses
    decide(g, "norra_levy", Posture.HOLD)
    out = walk_day(g, OPENS + timedelta(days=2))
    assert not payloads(out, ev.BattleRound)


def test_a_decision_stands_until_changed(tmp_path: Path) -> None:
    g = opened(tmp_path)
    decide(g, "norra_levy", Posture.HOLD)
    out = g.walk(OPENS + timedelta(days=1), OPENS + timedelta(days=2))
    assert not payloads(out, ev.BattleRound)
    g.state = at_wake(g.state, 1)
    decide(g, "norra_levy", Posture.ATTACK)
    assert fight(g).attacker.decision is Decision.PRESS
    out = walk_day(g, OPENS + timedelta(days=3))
    assert payloads(out, ev.BattleRound)


def test_a_posture_set_outside_a_decision_changes_nothing_in_the_battle(
    tmp_path: Path,
) -> None:
    """Only a recorded decision acts, from its day: a force's posture set mid-wake by any
    other path leaves the attacker pressing."""
    g = opened(tmp_path)
    levy = piece(g.state, "norra_levy")
    g.add([ev.FeatureSet(feature=levy.model_copy(update={"posture": Posture.HOLD}))])
    out = walk_day(g, OPENS + timedelta(days=1))
    assert payloads(out, ev.BattleRound)


# --- Rule 3: a twin in one wake is refused ----------------------------------------------


def test_a_second_decision_in_one_wake_is_refused_as_a_twin(tmp_path: Path) -> None:
    g = opened(tmp_path)
    g.state = at_wake(g.state, 4)
    decide(g, "norra_levy", Posture.HOLD)
    levy = piece(g.state, "norra_levy")
    again = battle.land_posture(g.state, levy, Posture.ATTACK, None, OPENS + timedelta(days=1))
    assert again is not None
    assert not [p for p in again if isinstance(p, ev.BattleDecided)]
    (kept,) = again
    assert isinstance(kept, ev.FeatureSet) and kept.feature.posture is Posture.HOLD
    assert fight(g).attacker.decision is Decision.HOLD
    with pytest.raises(FoldError, match="decided in wake 4"):
        g.add(
            [
                ev.BattleDecided(
                    area=entity(COAST),
                    nation=entity("norra"),
                    on=OPENS + timedelta(days=1),
                    decision=Decision.PRESS,
                    wake=4,
                )
            ]
        )
    g.state = at_wake(g.state, 5)
    decide(g, "norra_levy", Posture.ATTACK)  # the next wake may change it
    assert fight(g).attacker.decision is Decision.PRESS
    assert fight(g).attacker.decided_wake == 5


def test_each_side_has_its_own_decision_in_a_wake(tmp_path: Path) -> None:
    g = opened(tmp_path)
    decide(g, "norra_levy", Posture.HOLD)
    decide(g, "sudland_levy", Posture.ATTACK)
    b = fight(g)
    assert (b.attacker.decision, b.defender.decision) == (Decision.HOLD, Decision.PRESS)


# --- Rule 4: a withdrawal leaves for the named area, losing a step to a pressing side ----


def test_a_withdrawing_side_leaves_for_the_area_it_names_and_loses_a_step(
    tmp_path: Path,
) -> None:
    g = opened(tmp_path)
    before = piece(g.state, "sudland_levy").tier
    landed = decide(g, "sudland_levy", Posture.WITHDRAW, ISLE)
    assert isinstance(landed[0], ev.FeatureSet)
    (step,) = [p for p in landed if isinstance(p, ev.PieceStepped)]
    assert (step.left, step.entered, step.cause) == (entity(COAST), entity(ISLE), StepCause.ORDERED)
    levy = piece(g.state, "sudland_levy")
    assert levy.places == (entity(ISLE),) and levy.tier == before - 1  # Norra presses
    assert fight(g).defender.decision is Decision.WITHDRAW
    out = walk_day(g, OPENS + timedelta(days=1))
    (ended,) = payloads(out, ev.BattleEnded)
    assert (ended.ending, ended.winner) == (Ending.WON, entity("norra"))


def test_a_withdrawal_loses_no_step_when_the_other_side_holds(tmp_path: Path) -> None:
    g = opened(tmp_path)
    decide(g, "norra_levy", Posture.HOLD)
    before = piece(g.state, "sudland_levy").tier
    decide(g, "sudland_levy", Posture.WITHDRAW, ISLE)
    assert piece(g.state, "sudland_levy").tier == before


def test_a_withdrawal_to_ground_its_side_does_not_hold_is_refused(tmp_path: Path) -> None:
    g = opened(tmp_path)
    levy = piece(g.state, "sudland_levy")
    landed = battle.land_posture(
        g.state, levy, Posture.WITHDRAW, entity("norra_hills"), OPENS + timedelta(days=1)
    )
    assert landed is not None and len(landed) == 1  # only the force, as it was
    assert not [p for p in landed if isinstance(p, ev.BattleDecided)]
    assert landed[0].feature.places == levy.places  # type: ignore[union-attr]


def test_a_move_out_of_the_battle_is_a_withdrawal(tmp_path: Path) -> None:
    g = opened(tmp_path)
    landed = decide(g, "sudland_levy", None, ISLE)
    assert [p.decision for p in landed if isinstance(p, ev.BattleDecided)] == [Decision.WITHDRAW]
    assert piece(g.state, "sudland_levy").places == (entity(ISLE),)


# --- Rule 5: each force carries a contingency -------------------------------------------


def test_land_contingency_sets_the_rule_and_the_contingency(tmp_path: Path) -> None:
    g = opened(tmp_path)
    f = piece(g.state, "sudland_levy")
    c = Contingency(kind=ContingencyKind.WITHDRAW_BELOW, below=2, to=entity(ISLE))
    set_ = battle.land_contingency(
        f,
        SetEngagement(force=f.feature_id, zone="z", rule=Engagement.DEFEND, contingency=c),
        day(20),
    )
    assert (set_.engagement, set_.contingency, set_.as_of) == (Engagement.DEFEND, c, day(20))
    # An engagement order with no contingency leaves the force's as it was.
    plain = battle.land_contingency(
        set_, SetEngagement(force=f.feature_id, zone="z", rule=Engagement.HOLD_FIRE), day(21)
    )
    assert (plain.engagement, plain.contingency) == (Engagement.HOLD_FIRE, c)


def test_a_contingencys_fields_fit_its_kind() -> None:
    with pytest.raises(ValueError, match="names area"):
        Contingency(kind=ContingencyKind.FALL_BACK)
    with pytest.raises(ValueError, match="names figure"):
        Contingency(kind=ContingencyKind.WITHDRAW_BELOW)
    with pytest.raises(ValueError, match="has no area"):
        Contingency(kind=ContingencyKind.HOLD, to=entity(ISLE))
    with pytest.raises(ValueError, match="has no figure"):
        Contingency(kind=ContingencyKind.HOLD_FAST, below=2)
    Contingency(kind=ContingencyKind.WITHDRAW_BELOW, below=3)  # an area is optional


def test_hold_at_all_costs_is_never_forced_back(tmp_path: Path) -> None:
    """Norra's levy, 5 against 4, is broken on day 14 and would go back to the hills."""
    g = to_coast(tmp_path)
    contingent(g, "norra_levy", Contingency(kind=ContingencyKind.HOLD_FAST), day(1))
    out = g.walk(day(1), day(14))
    assert not payloads(out, ev.BattleEnded)
    assert not [p for p in payloads(out, ev.PieceStepped) if p.cause is StepCause.FORCED]
    assert piece(g.state, "norra_levy").places == (entity(COAST),)
    assert entity(COAST) in g.state.battles


def test_a_contingency_to_fall_back_when_outnumbered_fires_at_the_rounds_start(
    tmp_path: Path,
) -> None:
    """Sudland's 3 against Norra's 5: 5 is at least ``OUTNUMBERED`` times 3."""
    assert 5 >= OUTNUMBERED * 3 and 4 < OUTNUMBERED * 3
    g = to_coast(tmp_path, strengths(sudland_levy=3), link(COAST, ISLE), no_ferry)
    contingent(
        g, "sudland_levy", Contingency(kind=ContingencyKind.FALL_BACK, to=entity(ISLE)), day(1)
    )
    out = g.walk(day(1), OPENS)
    assert not payloads(out, ev.BattleRound)  # it left before the first round
    (step,) = steps_of(out, "sudland")
    assert (step.entered, step.on, step.cause) == (entity(ISLE), OPENS, StepCause.ORDERED)
    assert piece(g.state, "sudland_levy").tier == 2  # Norra presses: one step lost
    (ended,) = payloads(out, ev.BattleEnded)
    assert ended.ending is Ending.WON


def test_a_contingency_to_withdraw_below_a_strength(tmp_path: Path) -> None:
    """5 against 4: Sudland loses a step in the first round, so at 3 it is below 4."""
    g = to_coast(tmp_path, link(COAST, ISLE), no_ferry)
    contingent(g, "sudland_levy", Contingency(kind=ContingencyKind.WITHDRAW_BELOW, below=4), day(1))
    out = g.walk(day(1), OPENS)
    assert len(payloads(out, ev.BattleRound)) == 1 and not steps_of(out, "sudland")
    out = walk_day(g, OPENS + timedelta(days=1))
    assert not payloads(out, ev.BattleRound)
    (step,) = steps_of(out, "sudland")
    assert (step.entered, step.cause) == (entity(ISLE), StepCause.ORDERED)


def test_a_falling_back_piece_goes_to_the_area_its_contingency_names(tmp_path: Path) -> None:
    """BTL's fall-back rule reads the contingency's area first, when the side may go there."""
    g = Logged(
        toy(tmp_path, link(COAST, ISLE), link(COAST, "norra_plain"), capital("sudland", "sudby")),
        "ilse",
        "tomas",
    )
    levy = piece(g.state, "sudland_levy")
    assert battle.fall_back(g.state, levy, entity(COAST)) == entity(ISLE)
    plain = levy.model_copy(
        update={
            "contingency": Contingency(kind=ContingencyKind.FALL_BACK, to=entity("norra_plain"))
        }
    )
    assert battle.fall_back(g.state, plain, entity(COAST)) == entity(ISLE)  # Norra's ground
    from revisionist.core.realism.holders import Holding

    held = g.state.model_copy(
        update={"holders": {entity("norra_plain"): Holding(holder=entity("sudland"), on=day(1))}}
    )
    assert battle.fall_back(held, plain, entity(COAST)) == entity("norra_plain")


def test_fall_back_reads_a_seats_view_the_same_as_the_truth(tmp_path: Path) -> None:
    """For the odds (ODS): public data only, the board, holders, capitals and wars."""
    g = Logged(toy(tmp_path, link(COAST, ISLE), capital("sudland", "sudby")), "ilse", "tomas")
    levy = piece(g.state, "sudland_levy")
    for who in ("ilse", "tomas"):
        view = project(g.state, seat(who))
        assert battle.fall_back(view, levy, entity(COAST)) == entity(ISLE)


# --- Rule 6: the contingency acts in the day walk, with nobody there ---------------------


def test_an_absent_defenders_contingency_fires_on_day_three_of_a_two_wake_battle(
    tmp_path: Path,
) -> None:
    """Norra's levy, sent two days late, opens the battle on day 14, and the first wake
    closes that day after the first round. Sudland's seat is never there and gives no
    decision. Its levy, at 3 after the second round, withdraws below 4 at the start of the
    third, on the battle's third day, in the day walk of the second wake."""
    g = Logged(toy(tmp_path, link(COAST, ISLE), no_ferry, horizon(16)), "ilse", "tomas")
    sent = order("ilse", "norra_levy", "sudby", on=day(2))
    g.add(apply_changes(g.state, movement.order_changes(g.state, sent)))
    contingent(g, "sudland_levy", Contingency(kind=ContingencyKind.WITHDRAW_BELOW, below=4), day(1))
    w = Wakes(g)
    first = w.close()
    assert w.state.in_world_date == day(14)
    (opened_,) = payloads(first, ev.BattleOpened)
    assert opened_.on == day(14)
    assert [r.on for r in payloads(first, ev.BattleRound)] == [day(14)]
    assert not steps_of(first, "sudland")
    second = w.close()
    assert [r.on for r in payloads(second, ev.BattleRound)] == [day(15)]
    (step,) = steps_of(second, "sudland")
    assert (step.on, step.entered, step.cause) == (day(16), entity(ISLE), StepCause.ORDERED)
    (ended,) = payloads(second, ev.BattleEnded)
    assert (ended.on, ended.ending) == (day(16), Ending.WON)
    assert not [p for p in payloads(second, ev.BattleDecided) if p.decision is not None]


# --- Rule 7: with no decision, the attacker presses and the defender holds ---------------


def test_with_no_decision_the_attacker_presses_and_the_defender_holds(tmp_path: Path) -> None:
    g = opened(tmp_path)
    b = fight(g)
    assert b.attacker.decision is None and b.defender.decision is None
    assert battle.pressing(b, 0) and not battle.pressing(b, 1)
    out = walk_day(g, OPENS + timedelta(days=1))
    assert payloads(out, ev.BattleRound)


def test_a_defender_that_presses_costs_a_withdrawing_attacker_a_step(tmp_path: Path) -> None:
    g = opened(tmp_path)
    decide(g, "sudland_levy", Posture.ATTACK)
    assert battle.pressing(fight(g), 1)
    before = piece(g.state, "norra_levy").tier
    decide(g, "norra_levy", Posture.WITHDRAW, "norra_hills")
    after = piece(g.state, "norra_levy")
    assert after.places == (entity("norra_hills"),) and after.tier == before - 1


# --- Rule 8 (invariant 5): the aide never presses, withdraws or changes a contingency -----


def _aide_effects(g: Logged) -> list[Any]:
    levy = FeatureId(entity("norra_levy"))
    c = Contingency(kind=ContingencyKind.HOLD_FAST)
    return [
        MoveForce(force=levy, posture=Posture.ATTACK),
        MoveForce(force=levy, posture=Posture.WITHDRAW),
        MoveForce(force=levy, to=entity("norrhavn")),  # out of the battle: a withdrawal
        MoveForce(force=levy, posture=Posture.HOLD),
        SetEngagement(force=levy, zone="here", rule=Engagement.DEFEND, contingency=c),
    ]


def _bounded(effects: Sequence[Any]) -> None:
    for e in effects:
        assert not (isinstance(e, MoveForce) and e.posture in (Posture.ATTACK, Posture.WITHDRAW))
        assert not (isinstance(e, MoveForce) and e.to is not None)
        assert not (isinstance(e, SetEngagement) and e.contingency is not None)


def test_5_the_aide_is_bounded_no_press_withdrawal_or_contingency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All three aide filters: ``options.aide_asks``, the close's ``wake._allowed`` and the
    estimator's ``estimate.clamp``."""
    g = opened(tmp_path)
    effects = _aide_effects(g)
    asks = tuple(Ask(ask=f"ask {n}", effect=e) for n, e in enumerate(effects))
    kept = [battle.aide_may(g.state, e) for e in effects]
    assert kept[:3] == [None, None, None]
    assert kept[3] == effects[3]
    assert kept[4] == effects[4].model_copy(update={"contingency": None})

    by_close = wake._allowed(g.state, seat("ilse"), asks)
    _bounded([a.effect for a in by_close])
    assert len(by_close) == 2

    monkeypatch.setattr(options, "_live", lambda view: [object()])
    monkeypatch.setattr(options, "_wants_a_deal", lambda mandate: False)
    monkeypatch.setattr(
        options,
        "_options_for",
        lambda *a, **k: [SimpleNamespace(asks=asks, expects=(), risks=None)],
    )
    (filed,) = options.aide_asks(g.state, seat("ilse"), None)
    _bounded([a.effect for a in filed])
    assert len(filed) == 2

    routed = SimpleNamespace(parts=(), order_id=OrderId("o"))
    survivors, dropped = estimate.clamp(g.state, routed, effects, OPENS, aide=True)  # type: ignore[arg-type]
    _bounded(survivors)
    assert len(survivors) == 2 and len(dropped) == 4
    seat_own, _ = estimate.clamp(g.state, routed, effects, OPENS)  # type: ignore[arg-type]
    assert list(seat_own) == effects  # the seat's own order keeps them all


def test_the_aide_filter_leaves_a_game_without_battles_as_it_was(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path), "ilse", "tomas")
    rules = frozenset(r for r in g.state.rules if r.value != "battles")
    off = g.state.model_copy(update={"rules": rules})
    for e in _aide_effects(g):
        assert battle.aide_may(off, e) is e
    deal = Deal(counterparty=entity("sudland"), offer=("peace",))
    assert battle.aide_may(g.state, deal) is deal


# --- Rule 9: a decision by a seat with no piece in the battle is refused -----------------


def test_a_piece_on_neither_side_gives_no_decision(tmp_path: Path) -> None:
    g = opened(tmp_path, second_levy)
    other = piece(g.state, "second_levy").model_copy(update={"places": (entity(COAST),)})
    g.add([ev.FeatureSet(feature=other)])  # standing there, not yet joined
    landed = battle.land_posture(g.state, other, Posture.ATTACK, None, OPENS)
    assert landed is not None and len(landed) == 1
    assert isinstance(landed[0], ev.FeatureSet) and landed[0].feature.posture is None
    with pytest.raises(FoldError, match="leads no side"):
        g.add(
            [
                ev.BattleDecided(
                    area=entity(COAST),
                    nation=entity("ilse"),
                    on=OPENS,
                    decision=Decision.HOLD,
                    wake=0,
                )
            ]
        )


# --- Rule 1: reinforce is a move into the area; the piece joins its side -----------------


def test_a_piece_that_steps_in_joins_its_side(tmp_path: Path) -> None:
    g = opened(tmp_path, second_levy)
    b = fight(g)
    other = piece(g.state, "second_levy").model_copy(update={"places": (entity(COAST),)})
    g.add([ev.FeatureSet(feature=other)])
    out = walk_day(g, OPENS + timedelta(days=1))
    (joined,) = payloads(out, ev.BattleDecided)
    assert joined.joined == (other.feature_id,) and joined.added == 3
    assert joined.decision is None and joined.nation == entity("norra")
    after = g.state.battles.get(entity(COAST))
    if after is not None:
        assert other.feature_id in after.attacker.pieces
        assert after.attacker.brought == b.attacker.brought + 3
    kinds = [e.kind for e in out]
    assert kinds.index("battle_decided") < kinds.index("battle_round")


# --- The fold and the shapes (schema 49) -------------------------------------------------


def test_battle_decided_needs_an_open_battle(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    with pytest.raises(FoldError):
        g.add(
            [
                ev.BattleDecided(
                    area=entity(COAST),
                    nation=entity("norra"),
                    on=day(1),
                    decision=Decision.HOLD,
                    wake=0,
                )
            ]
        )


def test_a_joining_piece_is_not_already_in_the_battle(tmp_path: Path) -> None:
    g = opened(tmp_path)
    levy = FeatureId(entity("norra_levy"))
    with pytest.raises(FoldError, match="already in the battle"):
        g.add(
            [
                ev.BattleDecided(
                    area=entity(COAST), nation=entity("norra"), on=OPENS, joined=(levy,), added=5
                )
            ]
        )


def test_battle_decided_shapes() -> None:
    a = entity(COAST)
    n = entity("norra")
    with pytest.raises(ValueError, match="go together"):
        ev.BattleDecided(area=a, nation=n, on=OPENS, decision=Decision.HOLD)
    with pytest.raises(ValueError, match="pieces that join"):
        ev.BattleDecided(area=a, nation=n, on=OPENS)
    with pytest.raises(ValueError, match="bring strength"):
        ev.BattleDecided(area=a, nation=n, on=OPENS, joined=(FeatureId(n),))
    with pytest.raises(ValueError, match="go together"):
        BattleSide(nation=n, pieces=(FeatureId(n),), brought=1, decision=Decision.HOLD)


def test_a_meeting_battle_names_its_second_area_and_where_the_attacker_stands() -> None:
    side = BattleSide(nation=entity("norra"), pieces=(FeatureId(entity("norra_levy")),), brought=5)
    other = side.model_copy(update={"nation": entity("sudland")})
    base: dict[str, Any] = {
        "area": entity(COAST),
        "opened": OPENS,
        "attacker": side,
        "defender": other,
    }
    Battle(**base)
    Battle(**base, meeting=True, second=entity("norra_hills"), attacker_in=entity("norra_hills"))
    bads: list[dict[str, Any]] = [
        {"meeting": True},
        {"second": entity("norra_hills"), "attacker_in": entity(COAST)},
        {"meeting": True, "second": entity(COAST), "attacker_in": entity(COAST)},
        {"meeting": True, "second": entity("norra_hills"), "attacker_in": entity(ISLE)},
    ]
    for bad in bads:
        with pytest.raises(ValueError, match="meeting battle"):
            Battle(**base, **bad)


def test_a_stored_battle_and_feature_serialise_as_before() -> None:
    """The late fields are left out at their defaults, so schema 48 logs hash the same."""
    side = BattleSide(nation=entity("norra"), pieces=(FeatureId(entity("norra_levy")),), brought=5)
    assert "decision" not in side.model_dump(mode="json")
    b = Battle(area=entity(COAST), opened=OPENS, attacker=side, defender=side)
    assert not {"meeting", "second", "attacker_in"} & set(b.model_dump(mode="json"))
    e = SetEngagement(zone="z", rule=Engagement.DEFEND)
    assert "contingency" not in e.model_dump(mode="json")


def test_a_feature_keeps_its_contingency_through_the_fold(tmp_path: Path) -> None:
    g = to_coast(tmp_path)
    c = Contingency(kind=ContingencyKind.FALL_BACK, to=entity("norra_hills"))
    contingent(g, "norra_levy", c, day(1))
    f: Feature = piece(g.state, "norra_levy")
    assert f.contingency == c
