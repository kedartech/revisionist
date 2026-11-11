"""A figure no resolver computes may be moved by the estimator, by a bounded percent that
code clamps; the next report shows the new value. No test here calls a model."""

import json
from datetime import date
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import OrderId, QuantityId, derived_id
from revisionist.core.realism import apply
from revisionist.core.realism import effect as rx
from revisionist.core.realism.feeds import issue
from revisionist.core.state import State
from revisionist.core.world import DomainDecl
from revisionist.core.world_compile import WorldError, compile_world
from revisionist.engine import build
from revisionist.engine import campaign as cmp
from revisionist.engine import estimate as es
from revisionist.engine.llm import RecordedTransport
from revisionist.engine.store import load_state
from tests.test_build_authority import DOMAIN, kennedy_with, opened_kennedy
from tests.test_engine_v2_contract import CAMPAIGN, Slice
from tests.test_engine_v2_estimate import FIGURE, RECORDINGS, _scenario, figure_of
from tests.test_realism_cast import Fixed

FILED = date(1941, 9, 11)
LANDS = date(1941, 9, 12)


def _rig(value: int | None = 22000) -> tuple[Slice, OrderId, QuantityId]:
    sl, oid = _scenario(n=FIGURE)
    qid = figure_of(Slice())
    if value != 22000:
        q = sl.state.quantities[qid]
        sl.add(ev.QuantitySet(quantity=q.model_copy(update={"value": value})))
    return sl, oid, qid


def _more(sl: Slice, oid: OrderId, percent: int, qid: QuantityId, accepted: bool = True) -> State:
    """The order ruled on with one figure move, the target's answer in, as of today."""
    effects = (rx.MoveFigure(quantity=qid, percent=percent),)
    sl.add(ev.EffectsEstimated(order_id=oid, part=0, effects=effects, reason="Noted."))
    sl.add(ev.InfluenceDecided(order_id=oid, part=0, on=FILED, accepted=accepted))
    return sl.state


def _apply(sl: Slice, today: date = LANDS) -> list[ev.Payload]:
    out = apply.apply_due(sl.state, today)
    for payload in out:
        sl.add(payload)
    return out


def _sets(out: list[ev.Payload]) -> list[ev.QuantitySet]:
    return [p for p in out if isinstance(p, ev.QuantitySet)]


def test_a_quantity_a_built_figure_declares_is_estimable_and_a_world_files_is_not() -> None:
    store, cid, kennedy = opened_kennedy()
    assert build.build_figure(
        store, cid, kennedy, Fixed(kennedy_with(authority=[DOMAIN], reach={"rank": 5}))
    )
    made = [q for q in load_state(store, cid).quantities.values() if q.name.startswith("Missile")]
    assert len(made) == 1 and made[0].estimable
    assert not any(q.estimable for q in Slice().state.quantities.values())


def test_a_recorded_figure_ruling_is_kept_lands_and_replays() -> None:
    sl, oid, qid = _rig()
    got = es.estimate(sl.state, oid, 0, RecordedTransport(RECORDINGS / es.RECORDING))
    assert not got.event.failed and got.dropped == ()
    assert got.event.effects == (rx.MoveFigure(quantity=qid, percent=10),)
    sl.add(got.event)
    sl.add(ev.InfluenceDecided(order_id=oid, part=0, on=FILED, accepted=True))
    (landed,) = _sets(_apply(sl))
    assert landed.quantity.value == 24200 and landed.quantity.as_of == LANDS
    state = replay(sl.events)
    assert state.quantities[qid].value == 24200 and state.quantities[qid].as_of == LANDS
    assert state == replay(sl.events)


def _order(sl: Slice, carried: tuple[int, ...]) -> rx.RoutedOrder:
    qid = figure_of(Slice())
    parts = [
        rx.RoutedPart(
            route=rx.Route.INFLUENCE,
            target=sl.entity("wheeler"),
            estimated=tuple(rx.MoveFigure(quantity=qid, percent=p) for p in carried),
        ),
        rx.RoutedPart(route=rx.Route.INFLUENCE, target=sl.entity("wheeler")),
    ]
    return rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "figures", 1)),
        issuer=sl.fdr,
        filed=FILED,
        parts=tuple(parts),
    )


@pytest.mark.parametrize(
    ("carried", "proposed", "kept", "cut"),
    [
        ((), 25, 10, True),
        ((6,), 10, 4, True),
        ((10,), 10, None, True),
        ((10,), -10, -10, False),
        ((), 10, 10, False),
    ],
)
def test_clamp_holds_the_percent_an_order_moves_a_figure(
    carried: tuple[int, ...], proposed: int, kept: int | None, cut: bool
) -> None:
    sl, _, qid = _rig()
    order = _order(sl, carried)
    asked = rx.MoveFigure(quantity=qid, percent=proposed)
    got, dropped = es.clamp(sl.state, order, [asked], FILED)
    if kept is None:
        assert got == ()
    else:
        assert got == (rx.MoveFigure(quantity=qid, percent=kept),)
    assert bool(dropped) is cut
    if cut:
        assert "figure" in dropped[0]


def test_clamp_drops_a_figure_move_that_is_not_one_the_referee_may_make() -> None:
    sl, _, qid = _rig()
    order = _order(sl, ())
    (feed,) = (sl.state.feeds[f] for f in sl.state.cards[sl.entity("roosevelt")].feeds)
    fixed = feed.reports[1]
    sl.add(ev.QuantitySet(quantity=sl.state.quantities[qid].model_copy(update={"value": None})))
    for q in (QuantityId("nothing-here"), fixed, qid):
        got, dropped = es.clamp(sl.state, order, [rx.MoveFigure(quantity=q, percent=5)], FILED)
        assert got == () and len(dropped) == 1, q


def test_a_rebuffed_approach_moves_no_figure() -> None:
    sl, oid, qid = _rig()
    _more(sl, oid, 10, qid, accepted=False)
    out = _apply(sl)
    assert _sets(out) == []
    assert sl.state.quantities[qid].value == 22000


@pytest.mark.parametrize(("value", "percent", "after"), [(40, 1, None), (22000, -10, 19800)])
def test_the_change_is_whole_and_truncated_toward_zero(
    value: int, percent: int, after: int | None
) -> None:
    sl, oid, qid = _rig(value)
    _more(sl, oid, percent, qid)
    got = _sets(_apply(sl))
    if after is None:
        assert got == []
    else:
        assert [s.quantity.value for s in got] == [after]


def test_the_next_report_carries_the_new_value() -> None:
    sl, oid, qid = _rig()
    (feed,) = (sl.state.feeds[f] for f in sl.state.cards[sl.entity("roosevelt")].feeds)
    assert feed.bias.skew_pct == feed.bias.noise_pct == feed.bias.omit_pct == 0
    _more(sl, oid, 10, qid)
    _apply(sl)
    doc = issue(sl.state, feed, date(1941, 9, 20), "s")
    assert doc is not None
    assert doc.document.body[0].value == 24200


def _world(sl: Slice, oid: OrderId) -> dict[str, Any]:
    prompt = es.estimator_prompt(sl.state, oid, 0)
    return json.loads(prompt.split("\n", 1)[1].rsplit("\n\n", 1)[0])  # type: ignore[no-any-return]


def test_the_prompt_lists_the_issuers_figures_and_the_cap() -> None:
    sl, oid, qid = _rig()
    off = Slice()
    other = off.state.quantities[qid].model_copy(
        update={"quantity_id": QuantityId("unreported"), "estimable": True}
    )
    sl.add(ev.QuantitySet(quantity=other))
    world = _world(sl, oid)
    q = sl.state.quantities[qid]
    assert world["figures"] == [{"id": qid, "name": q.name, "value": 22000, "unit": q.unit}]
    assert world["rules"]["figure_cap"] == rx.FIGURE_CAP == 10


def test_a_world_with_no_figure_lists_none() -> None:
    sl, oid = _scenario()
    assert _world(sl, oid)["figures"] == []


def test_an_office_cannot_be_given_the_power_to_move_a_figure() -> None:
    decl = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
    card = decl.cards[0]
    domain = DomainDecl(name="Numbers", effects=(rx.EffectKind.FIGURE,))
    bad = card.model_copy(update={"authority": (*card.authority, domain)})
    decl = decl.model_copy(update={"cards": (bad, *decl.cards[1:])})
    with pytest.raises(WorldError, match="figure is not something an office orders"):
        compile_world(decl, CAMPAIGN, cmp.versions())
