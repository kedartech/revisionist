"""Battle decisions and contingencies land on the force from a filed order (DLN).

BDC's seam (``battle.land_posture`` and ``battle.land_contingency``) is called from
``apply.py`` where a posture or an engagement effect lands. These tests file an order
(routed and carried out, as the tick leaves it) and walk the days, so each effect reaches
the force through ``apply_due`` and the day walk, not by a direct call to the seam. The
toy world is that of ``tests/test_battle_decisions.py``.
"""

import re
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, derived_id
from revisionist.core.realism import apply, battle
from revisionist.core.realism.battle import Decision, Ending
from revisionist.core.realism.effect import (
    Contingency,
    ContingencyKind,
    Effect,
    Engagement,
    Fidelity,
    MoveForce,
    Posture,
    Route,
    RoutedOrder,
    RoutedPart,
    SetEngagement,
)
from revisionist.core.state import State
from tests.test_adjacency_moves import Logged, World, entity, piece, seat
from tests.test_battle_decisions import ISLE, at_wake, fight, opened, second_levy
from tests.test_battles import COAST, OPENS, horizon, link, no_ferry, payloads, to_coast

NEXT = OPENS + timedelta(days=1)


def army(w: World) -> None:
    """Each leader commands "army": moves and engagement for the nation's own forces, carried
    out by the seat itself, with an aide to sign its reports."""
    have = {f["key"] for f in w["features"]}
    own = {"ilse": ["norra_levy", "second_levy"], "tomas": ["sudland_levy"]}
    for who in own:
        w["entities"].append({"key": f"{who}_aide", "kind": "person", "name": f"Aide of {who}"})
    for card in w["cards"]:
        if card["person"] in own:
            forces = [k for k in own[card["person"]] if k in have]
            card["authority"] = [
                {"name": "army", "effects": ["move_force", "engagement"], "forces": forces}
            ]
            card["inner_circle"] = [{"person": f"{card['person']}_aide", "channel": "courier"}]


def file(g: Logged, by: str, effect: Effect, on: date, n: int = 1) -> None:
    """File ``effect`` as one command part by ``by``, carried out in full on ``on``."""
    routed = RoutedOrder(
        order_id=OrderId(derived_id("dln", "order", by, n)),
        issuer=seat(by),
        filed=on,
        parts=(RoutedPart(route=Route.COMMAND, effect=effect, domain="army"),),
    )
    g.add(
        [
            ev.OrderRouted(order=routed),
            ev.OrderExecuted(order_id=routed.order_id, part=0, on=on, fidelity=Fidelity.FULL),
        ]
    )


def move(g: Logged, key: str, p: Posture | None, to: str | None = None) -> MoveForce:
    return MoveForce(force=piece(g.state, key).feature_id, to=entity(to) if to else None, posture=p)


def rounds(out: Sequence[ev.Event]) -> list[Any]:
    return payloads(out, ev.BattleRound)


# --- Rule 1: a posture lands through the battle seam -------------------------------------


def test_a_hold_order_reaches_the_battle_on_the_first_round_after_the_close(
    tmp_path: Path,
) -> None:
    g = opened(tmp_path, army)
    file(g, "ilse", move(g, "norra_levy", Posture.HOLD), NEXT)
    out = g.walk(NEXT, NEXT)
    assert fight(g).attacker.decision is Decision.HOLD
    assert payloads(out, ev.BattleDecided)
    assert not rounds(out)  # the attacker holds: no round


def test_a_press_order_reaches_the_battle(tmp_path: Path) -> None:
    g = opened(tmp_path, army)
    file(g, "ilse", move(g, "norra_levy", Posture.HOLD), NEXT)
    g.walk(NEXT, NEXT)
    again = NEXT + timedelta(days=1)
    g.state = at_wake(g.state, 1)
    file(g, "ilse", move(g, "norra_levy", Posture.ATTACK), again, n=2)
    out = g.walk(again, again)
    assert fight(g).attacker.decision is Decision.PRESS
    assert rounds(out)


def test_a_withdrawal_order_takes_the_force_out_and_ends_the_battle(tmp_path: Path) -> None:
    g = opened(tmp_path, army)
    before = piece(g.state, "sudland_levy").tier
    file(g, "tomas", move(g, "sudland_levy", Posture.WITHDRAW, ISLE), NEXT)
    out = g.walk(NEXT, NEXT)
    assert fight(g).defender.decision is Decision.WITHDRAW if COAST in g.state.battles else True
    levy = piece(g.state, "sudland_levy")
    assert levy.places == (entity(ISLE),) and levy.tier == before - 1
    (ended,) = payloads(out, ev.BattleEnded)
    assert (ended.ending, ended.winner) == (Ending.WON, entity("norra"))


def test_a_loose_executor_drops_the_posture_and_gives_no_decision(tmp_path: Path) -> None:
    g = opened(tmp_path, army)
    order = RoutedOrder(
        order_id=OrderId(derived_id("dln", "loose")),
        issuer=seat("ilse"),
        filed=NEXT,
        parts=(
            RoutedPart(
                route=Route.COMMAND,
                effect=move(g, "norra_levy", Posture.HOLD, COAST),
                domain="army",
            ),
        ),
    )
    g.add(
        [
            ev.OrderRouted(order=order),
            ev.OrderExecuted(order_id=order.order_id, part=0, on=NEXT, fidelity=Fidelity.LOOSE),
        ]
    )
    out = g.walk(NEXT, NEXT)
    assert not payloads(out, ev.BattleDecided)
    assert fight(g).attacker.decision is None
    assert rounds(out)


# --- Rule 2: a contingency set by order fires in a later round ---------------------------


def test_a_contingency_set_by_order_fires_in_a_later_round(tmp_path: Path) -> None:
    g = to_coast(tmp_path, army, link(COAST, ISLE), no_ferry, horizon(20))
    c = Contingency(kind=ContingencyKind.WITHDRAW_BELOW, below=4)
    sud = piece(g.state, "sudland_levy")
    file(
        g,
        "tomas",
        SetEngagement(force=sud.feature_id, zone="here", rule=Engagement.DEFEND, contingency=c),
        OPENS - timedelta(days=11),
    )
    out = g.walk(OPENS - timedelta(days=11), OPENS + timedelta(days=4))
    assert piece(g.state, "sudland_levy").contingency == c
    assert any(s.entered == entity(ISLE) for s in payloads(out, ev.PieceStepped))
    assert payloads(out, ev.BattleEnded)


def test_an_engagement_order_without_a_contingency_leaves_the_contingency(
    tmp_path: Path,
) -> None:
    g = opened(tmp_path, army)
    c = Contingency(kind=ContingencyKind.HOLD_FAST)
    sud = piece(g.state, "sudland_levy").feature_id
    file(
        g,
        "tomas",
        SetEngagement(force=sud, zone="here", rule=Engagement.DEFEND, contingency=c),
        NEXT,
    )
    file(g, "tomas", SetEngagement(force=sud, zone="here", rule=Engagement.HOLD_FIRE), NEXT, n=2)
    g.walk(NEXT, NEXT)
    assert piece(g.state, "sudland_levy").contingency == c


# --- Rule 4: no battle rule is written in apply.py ---------------------------------------


def test_apply_py_names_no_battle_decision_or_contingency_kind() -> None:
    text = Path(apply.__file__).read_text()
    for banned in (
        r"\bDecision\b",
        r"\bContingencyKind\b",
        r"\bPRESS\b",
        r"\bHOLD_FAST\b",
        r"\bWITHDRAW_BELOW\b",
        r"\bFALL_BACK\b",
        r"\bBattleDecided\b",
    ):
        assert not re.search(banned, text), banned
    assert len(re.findall(r"battle\.land_posture\(", text)) == 1
    assert len(re.findall(r"battle\.land_contingency\(", text)) == 1


# --- The same orders where there is no battle land as today ------------------------------


def _landed(state: State, day: date) -> list[Any]:
    return [p.model_dump_json() for p in apply.apply_due(state, day)]


def _as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(battle, "land_posture", lambda *a, **k: None)
    monkeypatch.setattr(
        battle,
        "land_contingency",
        lambda f, e, on: f.model_copy(update={"engagement": e.rule, "as_of": max(on, f.as_of)}),
    )


def test_a_force_in_no_battle_lands_today_s_events_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = to_coast(tmp_path, second_levy, army, link(COAST, ISLE), no_ferry)
    g.walk(OPENS - timedelta(days=11), OPENS)
    home = piece(g.state, "second_levy").feature_id
    file(g, "ilse", MoveForce(force=home, to=None, posture=Posture.HOLD), NEXT)
    file(
        g,
        "ilse",
        SetEngagement(
            force=home,
            zone="here",
            rule=Engagement.DEFEND,
        ),
        NEXT,
        n=2,
    )
    seamed = _landed(g.state, NEXT)
    _as_before(monkeypatch)
    assert seamed == _landed(g.state, NEXT)
    assert len(seamed) >= 4


def test_a_game_without_battles_lands_today_s_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = opened(tmp_path, army)
    file(g, "ilse", move(g, "norra_levy", Posture.HOLD), NEXT)
    off = g.state.model_copy(
        update={"rules": g.state.rules - {r for r in g.state.rules if r.value == "battles"}}
    )
    seamed = _landed(off, NEXT)
    _as_before(monkeypatch)
    assert seamed == _landed(off, NEXT)
    assert not [e for e in seamed if '"battle_decided"' in e]
