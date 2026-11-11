"""Order results (Phase 4 unit S3): each part of a seat's own orders, in words."""

import json
from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, RelationshipId, derived_id
from revisionist.core.ontology import Relationship
from revisionist.core.realism import effect as rx
from revisionist.core.visibility import private_to
from revisionist.engine.web.results import results
from tests.test_engine_v2_contract import CAMPAIGN, REASON_CANARY, Slice

RATIONALE_CANARY = "CANARY-V2-RATIONALE-c41d"


def _influence(sl: Slice, n: int, parts: int = 1, ask: str = "") -> rx.RoutedOrder:
    order = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "v2-order", n)),
        issuer=sl.fdr,
        filed=date(1941, 9, 10 + n),
        parts=tuple(
            rx.RoutedPart(route=rx.Route.INFLUENCE, target=sl.entity("wheeler"), ask=ask)
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


def test_a_zone_given_as_a_place_id_reads_as_its_name() -> None:
    sl = Slice()
    zone = sl.entity("argentia")
    effect = rx.SetEngagement(
        force=sl.feature("us_atlantic_fleet"), zone=zone, rule=rx.Engagement.SHOOT_ON_SIGHT
    )
    order = sl.shoot_on_sight(effect=effect)
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    [part] = results(sl.state, sl.fdr)[0]["parts"]
    assert part["ask"] == "Order the rule shoot on sight in Argentia"


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


def test_a_free_text_ask_is_shown_in_the_seats_own_words() -> None:
    sl = Slice()
    words = "Ask Wheeler to back the bill quietly"
    _influence(sl, 1, ask=words)
    [part] = results(sl.state, sl.fdr)[0]["parts"]
    assert part["ask"] == words


def test_another_seats_results_do_not_hold_a_free_text_ask_own_words() -> None:
    sl = Slice()
    words = "Tell Roosevelt nothing about the convoy"
    other = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "v2-order", 3)),
        issuer=sl.wheeler,
        filed=date(1941, 9, 20),
        parts=(rx.RoutedPart(route=rx.Route.INFLUENCE, target=sl.entity("roosevelt"), ask=words),),
    )
    sl.add(ev.OrderRouted(order=other), private_to(sl.wheeler))
    _influence(sl, 1)
    assert words not in json.dumps(results(sl.state, sl.fdr))
    [part] = results(sl.state, sl.wheeler)[0]["parts"]
    assert part["ask"] == words


def test_an_empty_ask_keeps_the_fallback_own_words() -> None:
    sl = Slice()
    _influence(sl, 1, ask="   ")
    [part] = results(sl.state, sl.fdr)[0]["parts"]
    assert part["ask"] == "A request in your own words"


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def test_a_decided_approach_reads_as_the_decision_not_the_estimate() -> None:
    sl = Slice()
    order = _influence(sl, 1)
    sl.add(
        ev.EffectsEstimated(order_id=order.order_id, part=0, reason="He is receptive."),
        private_to(sl.fdr),
    )
    sl.add(
        ev.InfluenceDecided(
            order_id=order.order_id,
            part=0,
            on=date(1941, 9, 14),
            accepted=False,
            reason="Burton K. Wheeler would not be moved.",
        ),
        private_to(sl.fdr),
    )
    _land_reports(sl, date(1941, 9, 14))
    [part] = results(sl.state, sl.fdr)[0]["parts"]
    assert part["accepted"] is False
    assert "receptive" not in str(part["reason"]) and "would not be moved" in str(part["reason"])


def _land_reports(sl: Slice, on: date) -> None:
    """Apply what is due, then let a month pass so every report has arrived."""
    from datetime import timedelta

    from revisionist.core.realism.apply import apply_due

    for p in apply_due(sl.state, on):
        scope = p.document.scope if isinstance(p, ev.DocumentIssued) else private_to(sl.fdr)
        sl.add(p, scope)
    sl.add(ev.DateAdvanced(to=on + timedelta(days=30)))


def test_the_log_line_is_the_issued_papers_answer_and_does_not_drift() -> None:
    sl = Slice()
    order = _influence(sl, 1)
    sl.add(ev.EffectsEstimated(order_id=order.order_id, part=0, reason="r"), private_to(sl.fdr))
    sl.add(
        ev.InfluenceDecided(order_id=order.order_id, part=0, on=date(1941, 9, 14), accepted=False),
        private_to(sl.fdr),
    )
    _land_reports(sl, date(1941, 9, 14))
    before = results(sl.state, sl.fdr)[0]["parts"][0]["reason"]
    warm = Relationship(
        relationship_id=RelationshipId("01ARZ3NDEKTSV4RRFFQ69GWARM0"),
        a=sl.entity("wheeler"),
        b=sl.entity("roosevelt"),
        disposition=5,
        scope=private_to(sl.fdr),
    )
    later = sl.state.model_copy(update={"relationships": {warm.relationship_id: warm}})
    assert before and results(later, sl.fdr)[0]["parts"][0]["reason"] == before
