"""Battle decisions and contingencies land on the force from a filed order (DLN).

BDC's seam (``battle.land_posture`` and ``battle.land_contingency``) is called from
``apply.py`` where a posture or an engagement effect lands. These tests file an order
(routed and carried out, as the tick leaves it) and walk the days, so each effect reaches
the force through ``apply_due`` and the day walk, not by a direct call to the seam. The
toy world is that of ``tests/test_battle_decisions.py``.
"""

import re
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from itertools import permutations
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
from tests.async_table import digest, papers
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


# --- BDS: a side's decisions in one wake settle by content ------------------------------
#
# Order ids are ULIDs in play, so the order of filing is the order of the ids. These tests
# give the ids by hand in the order each run files them: ``FIRST`` to the first filed.

FIRST = ("bds-order-0", "bds-order-1", "bds-order-2")


def officer(person: str, polity: str, office: str) -> Callable[[World], None]:
    """A second playable seat whose card commands Norra's levy: ``person`` of ``polity``."""

    def change(w: World) -> None:
        if polity not in {e["key"] for e in w["entities"]}:
            w["entities"].append({"key": polity, "kind": "polity", "name": polity.title()})
        w["entities"] += [
            {"key": person, "kind": "person", "name": person.title(), "parent": polity},
            {"key": f"{person}_aide", "kind": "person", "name": f"Aide of {person}"},
        ]
        w["cards"].append(
            {
                "person": person,
                "office": office,
                "playable": True,
                "principals": [polity],
                "horizon_days": 14,
                "authority": [
                    {
                        "name": "army",
                        "effects": ["move_force", "engagement"],
                        "forces": ["norra_levy"],
                    }
                ],
                "inner_circle": [{"person": f"{person}_aide", "channel": "courier"}],
            }
        )
        w["roster"].append(
            {"entity": person, "pitch": office, "reach": "The army of Norra.", "composite": True}
        )

    return change


DEPUTY = officer("ivar", "norra", "Marshal of Norra")
"""A second seat of Norra, the side's own nation; its seat key sorts after Ilse's."""
ALLY = officer("otto", "vesta", "Envoy-general of Vesta")
"""A seat of another nation on Norra's side; its seat key sorts before Ilse's."""

Filing = tuple[str, Posture]
"""Who files, and the posture on Norra's levy (no destination)."""


def wake_of(tmp: Path, filings: Sequence[Filing], *extra: Callable[[World], None]) -> Logged:
    """The coast's battle open, each filing made in the order given (``FIRST`` ids in that
    order), all in one wake on ``NEXT``, and the day walked."""
    tmp.mkdir()
    g = opened(tmp, army, *extra)
    claims = {by for by, _ in filings} - {"ilse", "tomas"}
    g.add([ev.CharacterClaimed(seat_id=seat(p), entity_id=entity(p)) for p in sorted(claims)])
    for n, (by, posture) in enumerate(filings):
        routed = RoutedOrder(
            order_id=OrderId(FIRST[n]),
            issuer=seat(by),
            filed=NEXT,
            parts=(
                RoutedPart(
                    route=Route.COMMAND, effect=move(g, "norra_levy", posture), domain="army"
                ),
            ),
        )
        g.add(
            [
                ev.OrderRouted(order=routed),
                ev.OrderExecuted(order_id=routed.order_id, part=0, on=NEXT, fidelity=Fidelity.FULL),
            ]
        )
    g.walk(NEXT, NEXT)
    return g


def outcome(g: Logged) -> tuple[Any, ...]:
    """The outcome digest (``tests/async_table.digest``) and every seat's papers. The
    routed orders and the documents are keyed by order id, which is the filing order by
    construction here, so the digest leaves those two maps out; ``papers`` gives each
    seat's papers by their shape, with no id."""
    world = g.state.model_copy(update={"routed": {}, "documents": {}})
    return digest(world), repr([papers(g.state, s) for s in sorted(g.state.seats)])


def test_two_seats_of_a_side_settle_the_same_whoever_filed_first(tmp_path: Path) -> None:
    a = wake_of(tmp_path / "a", [("ilse", Posture.ATTACK), ("ivar", Posture.WITHDRAW)], DEPUTY)
    b = wake_of(tmp_path / "b", [("ivar", Posture.WITHDRAW), ("ilse", Posture.ATTACK)], DEPUTY)
    for g in (a, b):
        assert fight(g).attacker.decision is Decision.PRESS  # Ilse's seat key sorts first
        assert fight(g).attacker.decided_wake == 0
        assert piece(g.state, "norra_levy").places == (entity(COAST),)
    assert outcome(a) == outcome(b)


def test_three_decisions_for_one_side_in_any_order_give_one_outcome(tmp_path: Path) -> None:
    three: list[Filing] = [
        ("ilse", Posture.ATTACK),
        ("ilse", Posture.HOLD),
        ("ivar", Posture.WITHDRAW),
    ]
    seen = set()
    for n, order in enumerate(permutations(three)):
        g = wake_of(tmp_path / str(n), list(order), DEPUTY)
        # Ilse's seat first; of her two, the more cautious: hold.
        assert fight(g).attacker.decision is Decision.HOLD
        seen.add(outcome(g))
    assert len(seen) == 1


def test_the_seat_of_the_sides_own_nation_comes_before_an_ally(tmp_path: Path) -> None:
    assert str(seat("otto")) < str(seat("ilse"))
    for n, order in enumerate(
        (
            [("otto", Posture.WITHDRAW), ("ilse", Posture.ATTACK)],
            [("ilse", Posture.ATTACK), ("otto", Posture.WITHDRAW)],
        )
    ):
        g = wake_of(tmp_path / str(n), order, ALLY)
        assert fight(g).attacker.decision is Decision.PRESS


def test_twins_settle_no_decision_without_battles(tmp_path: Path) -> None:
    g = opened(tmp_path, army)
    off = g.state.model_copy(
        update={"rules": g.state.rules - {r for r in g.state.rules if r.value == "battles"}}
    )
    wanted = [
        (seat("ilse"), "a", move(g, "norra_levy", Posture.ATTACK), NEXT),
        (seat("ilse"), "b", move(g, "norra_levy", Posture.WITHDRAW), NEXT),
    ]
    assert battle.twins(off, wanted) == frozenset()
    assert battle.twins(g.state, wanted) == {"a"}
