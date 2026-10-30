"""Order results (Phase 4 unit S3): each part of a seat's own orders, in words."""

import json
from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.visibility import private_to
from revisionist.engine.web.results import results
from tests.test_engine_v2_contract import CAMPAIGN, REASON_CANARY, Slice

RATIONALE_CANARY = "CANARY-V2-RATIONALE-c41d"


def _influence(sl: Slice, n: int, parts: int = 1) -> rx.RoutedOrder:
    order = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "v2-order", n)),
        issuer=sl.fdr,
        filed=date(1941, 9, 10 + n),
        parts=tuple(
            rx.RoutedPart(route=rx.Route.INFLUENCE, target=sl.entity("wheeler"))
            for _ in range(parts)
        ),
    )
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    return order


def test_a_routed_command_reads_in_words() -> None:
    sl = Slice()
    order = sl.shoot_on_sight()
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(
        ev.OrderExecuted(
            order_id=order.order_id, part=0, on=date(1941, 9, 12), fidelity=rx.Fidelity.LOOSE
        ),
        private_to(sl.fdr),
    )
    sl.add(
        ev.EffectsApplied(order_id=order.order_id, part=0, on=date(1941, 9, 13)),
        private_to(sl.fdr),
    )
    [got] = results(sl.state, sl.fdr)
    [part] = got["parts"]
    assert got["filed"] == "11 September 1941"
    assert "Stark" in str(part["to"])
    assert part["route"] == "Your command"
    assert part["fidelity"] == "Carried out loosely"
    assert part["refused_under"] is None and part["accepted"] is None
    assert part["applied"] == "13 September 1941"
    assert "shoot on sight" in part["ask"] and "western Atlantic" in part["ask"]


def test_a_refused_part_names_its_rule() -> None:
    sl = Slice()
    order = sl.shoot_on_sight()
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(
        ev.OrderExecuted(
            order_id=order.order_id, part=0, on=date(1941, 9, 12), refusal="loyalty -4"
        ),
        private_to(sl.fdr),
    )
    [part] = results(sl.state, sl.fdr)[0]["parts"]
    assert part["refused_under"] == "Refused under loyalty -4"
    assert part["fidelity"] is None and part["applied"] is None


def test_influence_is_decided_both_ways() -> None:
    sl = Slice()
    order = _influence(sl, 1, parts=2)
    for i, went in enumerate((True, False)):
        sl.add(
            ev.InfluenceDecided(
                order_id=order.order_id, part=i, on=date(1941, 9, 14), accepted=went, reason="r"
            ),
            private_to(sl.fdr),
        )
    yes, no = results(sl.state, sl.fdr)[0]["parts"]
    assert (yes["accepted"], no["accepted"]) == (True, False)
    assert yes["route"] == "Your persuasion" and "Wheeler" in str(yes["to"])
    assert yes["fidelity"] is None and yes["applied"] is None


def test_newest_first_and_only_the_seats_own() -> None:
    sl = Slice()
    old, new = _influence(sl, 1), _influence(sl, 2)
    other = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "v2-order", 3)),
        issuer=sl.wheeler,
        filed=date(1941, 9, 20),
        parts=(rx.RoutedPart(route=rx.Route.INFLUENCE, target=sl.entity("roosevelt")),),
    )
    sl.add(ev.OrderRouted(order=other), private_to(sl.wheeler))
    got = results(sl.state, sl.fdr)
    assert [g["filed"] for g in got] == ["12 September 1941", "11 September 1941"]
    assert len(got) == 2 and old.order_id != new.order_id
    mine = json.dumps(got)
    assert "20 September" not in mine
    assert len(results(sl.state, sl.wheeler)) == 1


def test_no_rationale_no_estimate_and_no_underscore() -> None:
    sl = Slice()
    order = _influence(sl, 1)
    shift = rx.ShiftDisposition(of=sl.entity("wheeler"), toward=sl.entity("roosevelt"), change=-1)
    sl.add(
        ev.EffectsEstimated(
            order_id=order.order_id,
            part=0,
            effects=(shift,),
            reason=REASON_CANARY,
            rationale=RATIONALE_CANARY,
        )
    )
    cmd = sl.shoot_on_sight(2)
    sl.add(ev.OrderRouted(order=cmd), private_to(sl.fdr))
    got = results(sl.state, sl.fdr)
    text = json.dumps(got)
    assert RATIONALE_CANARY not in text and "estimated" not in text
    assert REASON_CANARY in text
    for strings in _strings(got):
        assert "_" not in strings


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []
