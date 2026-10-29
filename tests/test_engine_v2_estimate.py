"""The estimator (unit A4): prompt, clamp, failure path and canary, on recorded replies.

The recording is hand-written, not a model reply: ``python -m tests.test_engine_v2_estimate``
rebuilds it. No test here calls a model.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.canary import scan
from revisionist.core.fold import replay
from revisionist.core.ids import EntityId, OrderId
from revisionist.core.realism import effect as rx
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine import estimate as es
from revisionist.engine.llm import RecordedTransport, Reply, Request, TransportError
from tests.test_engine_v2_contract import REASON_CANARY, Slice, _with_covert_fact

RECORDINGS = Path(__file__).parent / "recordings"
QUANTITY = 2  # a second order, so its request key is its own
NOTE = "hand-written for tests; not a model reply"


def _scenario(covert: bool = False, n: int = 1) -> tuple[Slice, OrderId]:
    sl = Slice()
    if covert:
        _with_covert_fact(sl)
    order = sl.shoot_on_sight(
        n,
        route=rx.Route.INFLUENCE,
        domain=None,
        executor=None,
        target=sl.entity("wheeler"),
        effect=None,
    )
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    return sl, order.order_id


def _shift(sl: Slice, change: int) -> dict[str, Any]:
    return {
        "kind": "disposition",
        "of": sl.entity("wheeler"),
        "toward": sl.entity("roosevelt"),
        "change": change,
    }


def _replies(sl: Slice, covert: bool, n: int) -> dict[str, dict[str, Any]]:
    if n == QUANTITY:
        return {
            "quantity": {
                "effects": [{"kind": "set_votes", "bloc": "isolationists", "count": 40}],
                "reason": "Forty votes fall away.",
                "rationale": "A count, which no effect may carry.",
            }
        }
    if covert:
        return {
            "canary": {
                "effects": [_shift(sl, -1)],
                "reason": f"Wheeler is compromised ({REASON_CANARY}).",
                "rationale": f"Referee only: {REASON_CANARY}.",
            }
        }
    return {
        "shift": {
            "effects": [_shift(sl, -1)],
            "reason": "The Senate will notice.",
            "rationale": "Wheeler resents being lobbied; one step down.",
        },
    }


class _Hand:
    """Returns one hand reply and keeps the request, so the generator can key it."""

    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.request: Request | None = None

    def call(self, request: Request) -> Reply:
        self.request = request
        return Reply(self.output, "hand", 0, 0, 0, 0.0)


def _write() -> None:
    entries: dict[str, dict[str, Any]] = {}
    for covert, n in ((False, 1), (True, 1), (False, QUANTITY)):
        sl, oid = _scenario(covert, n)
        for name, output in _replies(sl, covert, n).items():
            hand = _Hand(output)
            es.estimate(sl.state, oid, 0, hand)
            assert hand.request is not None
            entries[hand.request.key()] = {
                "call_class": es.CALL_CLASS,
                "model": es.ESTIMATOR_MODEL,
                "prompt_head": hand.request.prompt[:120],
                "hand_written": True,
                "note": f"{NOTE} ({name})",
                "reply": Reply(output, "hand", 0, 0, 0, 0.0).__dict__,
            }
    path = RECORDINGS / es.RECORDING
    path.write_text(json.dumps(entries, indent=1, sort_keys=True) + "\n")


@pytest.fixture
def recorded() -> RecordedTransport:
    return RecordedTransport(RECORDINGS / es.RECORDING)


def _land(sl: Slice, event: ev.EffectsEstimated) -> State:
    sl.add(event)
    return sl.state


def test_a_valid_shift_lands_and_folds(recorded: RecordedTransport) -> None:
    sl, oid = _scenario()
    got = es.estimate(sl.state, oid, 0, recorded)
    assert not got.event.failed and got.dropped == () and got.cost is not None
    assert got.event.reason == "The Senate will notice."
    part = _land(sl, got.event).routed[oid].parts[0]
    assert part.estimated == got.event.effects and part.was_estimated
    assert replay([*sl.events], initial=None).routed[oid].parts[0].reason == got.event.reason


def test_clamp_drops_what_is_not_in_the_world() -> None:
    sl, oid = _scenario()
    state, order = sl.state, sl.state.routed[oid]
    ghost = rx.ShiftDisposition(of=EntityId("nobody"), toward=sl.entity("roosevelt"), change=1)
    kept, dropped = es.clamp(state, order, [ghost], date(1941, 9, 11))
    assert kept == () and len(dropped) == 1 and "nobody" in dropped[0]


def test_clamp_drops_a_force_before_its_in_service_date() -> None:
    sl, oid = _scenario()
    fleet = sl.feature("us_atlantic_fleet")
    late = state = sl.state
    late = state.model_copy(
        update={
            "features": {
                **state.features,
                fleet: state.features[fleet].model_copy(update={"in_service": date(1942, 1, 1)}),
            }
        }
    )
    move = rx.MoveForce(force=fleet, posture=rx.Posture.PATROL)
    assert es.clamp(late, late.routed[oid], [move], date(1941, 9, 11))[0] == ()
    assert es.clamp(late, late.routed[oid], [move], date(1942, 1, 1))[0] == (move,)


def test_clamp_holds_a_pair_to_the_disposition_cap() -> None:
    sl, oid = _scenario()
    up = rx.ShiftDisposition(of=sl.entity("wheeler"), toward=sl.entity("roosevelt"), change=2)
    kept, dropped = es.clamp(sl.state, sl.state.routed[oid], [up, up], date(1941, 9, 11))
    assert kept == (up,) and len(dropped) == 1
    one = up.model_copy(update={"change": 1})
    kept, dropped = es.clamp(sl.state, sl.state.routed[oid], [up, one], date(1941, 9, 11))
    assert kept == (up,) and "cap" in dropped[0]
    kept, _ = es.clamp(sl.state, sl.state.routed[oid], [one, up], date(1941, 9, 11))
    assert kept == (one, one.model_copy(update={"change": 1}))


def test_clamp_cuts_to_eight_effects() -> None:
    sl, oid = _scenario()
    said = [rx.MakeStatement(theme=f"theme {n}") for n in range(10)]
    kept, dropped = es.clamp(sl.state, sl.state.routed[oid], said, date(1941, 9, 11))
    assert kept == tuple(said[:8]) and len(dropped) == 2


def test_a_quantity_like_effect_fails_the_estimate(recorded: RecordedTransport) -> None:
    sl, oid = _scenario(n=QUANTITY)
    got = es.estimate(sl.state, oid, 0, recorded)
    assert got.event.failed and got.event.effects == () and got.event.reason == es.FAILED_REASON
    _land(sl, got.event)


class _Down:
    def call(self, request: Request) -> Reply:
        raise TransportError("model unreachable")


def test_a_transport_error_fails_the_estimate() -> None:
    sl, oid = _scenario()
    got = es.estimate(sl.state, oid, 0, _Down())
    assert got.event.failed and got.event.reason == es.FAILED_REASON and got.cost is None
    assert _land(sl, got.event).routed[oid].parts[0].was_estimated


def test_a_leaking_reason_is_withheld(recorded: RecordedTransport) -> None:
    sl, oid = _scenario(covert=True)
    got = es.estimate(sl.state, oid, 0, recorded)
    assert got.event.reason == es.REASON_WITHHELD
    assert REASON_CANARY in got.event.rationale
    _land(sl, got.event)
    assert scan(sl.state, sl.events) == []


def test_the_same_state_gives_the_same_request_and_event(recorded: RecordedTransport) -> None:
    a, oid_a = _scenario()
    b, oid_b = _scenario()
    assert es.estimator_prompt(a.state, oid_a, 0) == es.estimator_prompt(b.state, oid_b, 0)
    assert (
        es.estimate(a.state, oid_a, 0, recorded).event
        == es.estimate(b.state, oid_b, 0, recorded).event
    )


def test_the_prompt_names_ids_and_leaves_out_the_voice() -> None:
    sl, oid = _scenario()
    prompt = es.estimator_prompt(sl.state, oid, 0)
    assert sl.entity("wheeler") in prompt and sl.feature("us_atlantic_fleet") in prompt
    assert '"voice"' not in prompt and "disposition_cap" in prompt


if __name__ == "__main__":
    _write()
