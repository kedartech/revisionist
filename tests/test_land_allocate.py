"""Landing an Allocate: a quantity moves between polities, or only a private record is kept."""

from datetime import date

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, QuantityId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.realism.land import allocate
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.quantity import Quantity
from revisionist.core.visibility import PUBLIC, private_to
from tests.test_engine_v2_apply import FILED
from tests.test_engine_v2_apply import land as apply_land
from tests.test_engine_v2_contract import CAMPAIGN, Slice

WHAT = "munitions"
AS_OF = date(1941, 9, 1)
ON = date(1941, 9, 11)


@pytest.fixture
def sl() -> Slice:
    return Slice()


def stock(sl: Slice, key: str, owner: str, value: int | None) -> QuantityId:
    """Fold a munitions quantity owned by the keyed entity into the slice."""
    q = Quantity(
        quantity_id=QuantityId(derived_id(CAMPAIGN, "test-quantity", key)),
        owner=sl.entity(owner),
        name=WHAT,
        value=value,
        unit="tons",
        as_of=AS_OF,
    )
    sl.add(ev.QuantitySet(quantity=q))
    return q.quantity_id


def allocate_to(sl: Slice, recipient: str, amount: int, on: date = ON) -> list[ev.Payload]:
    """Land an allocation from Roosevelt's polity, folding what comes back as the tick would."""
    effect = rx.Allocate(recipient=sl.entity(recipient), what=WHAT, amount=amount, unit="tons")
    payloads, revealed = allocate.land(
        PassWorld(sl.state), effect, sl.fdr, sl.entity("roosevelt"), on
    )
    assert revealed == []
    for p in payloads:
        sl.add(p, private_to(sl.fdr) if isinstance(p, ev.FactAsserted) else PUBLIC)
    return payloads


def test_moves_the_amount_and_clamps_at_what_the_issuer_holds(sl: Slice) -> None:
    usa = stock(sl, "usa", "usa", 100)
    uk = stock(sl, "uk", "uk", 10)
    payloads = allocate_to(sl, "churchill", 150)
    assert sl.state.quantities[usa].value == 0 and sl.state.quantities[usa].as_of == ON
    assert sl.state.quantities[uk].value == 110 and sl.state.quantities[uk].as_of == ON
    assert sum(isinstance(p, ev.QuantitySet) for p in payloads) == 2


def test_a_partial_move_leaves_the_rest_with_the_issuer(sl: Slice) -> None:
    usa = stock(sl, "usa", "usa", 100)
    uk = stock(sl, "uk", "uk", 10)
    allocate_to(sl, "uk", 40)
    assert sl.state.quantities[usa].value == 60
    assert sl.state.quantities[uk].value == 50


def test_a_recipient_with_no_value_counts_from_zero(sl: Slice) -> None:
    stock(sl, "usa", "usa", 100)
    uk = stock(sl, "uk", "uk", None)
    allocate_to(sl, "uk", 30)
    assert sl.state.quantities[uk].value == 30


def test_an_issuer_figure_still_a_gap_moves_nothing(sl: Slice) -> None:
    usa = stock(sl, "usa", "usa", None)
    uk = stock(sl, "uk", "uk", 10)
    payloads = allocate_to(sl, "uk", 30)
    assert [type(p) for p in payloads] == [ev.FactAsserted]
    assert sl.state.quantities[usa].value is None
    assert sl.state.quantities[uk].value == 10


def test_no_matching_quantity_records_a_private_fact_only(sl: Slice) -> None:
    usa = stock(sl, "usa", "usa", 100)
    (p,) = allocate_to(sl, "uk", 30)
    assert isinstance(p, ev.FactAsserted)
    assert p.fact.subject == sl.entity("uk") and p.fact.predicate == "received_from"
    assert p.fact.obj == sl.entity("roosevelt") and p.fact.scope == private_to(sl.fdr)
    assert p.fact.fact_id in sl.state.facts
    assert sl.state.quantities[usa].value == 100


def test_a_second_identical_call_adds_no_duplicate_fact(sl: Slice) -> None:
    stock(sl, "usa", "usa", 100)
    allocate_to(sl, "uk", 30)
    assert allocate_to(sl, "uk", 30) == []


def test_a_second_call_on_a_matched_pair_adds_no_duplicate_fact(sl: Slice) -> None:
    stock(sl, "usa", "usa", 100)
    stock(sl, "uk", "uk", 10)
    allocate_to(sl, "uk", 30)
    assert not any(isinstance(p, ev.FactAsserted) for p in allocate_to(sl, "uk", 30))


def test_amount_zero_changes_no_quantity(sl: Slice) -> None:
    usa = stock(sl, "usa", "usa", 100)
    uk = stock(sl, "uk", "uk", 10)
    payloads = allocate_to(sl, "uk", 0)
    assert not any(isinstance(p, ev.QuantitySet) for p in payloads)
    assert any(isinstance(p, ev.FactAsserted) for p in payloads)
    assert sl.state.quantities[usa].value == 100 and sl.state.quantities[usa].as_of == AS_OF
    assert sl.state.quantities[uk].value == 10 and sl.state.quantities[uk].as_of == AS_OF


def test_an_accepted_allocation_lands_through_apply_due(sl: Slice) -> None:
    stock(sl, "usa", "usa", 100)
    uk = stock(sl, "uk", "uk", 10)
    part = rx.RoutedPart(
        route=rx.Route.INFLUENCE,
        target=sl.entity("wheeler"),
        effect=rx.Allocate(recipient=sl.entity("uk"), what=WHAT, amount=25, unit="tons"),
    )
    order = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "allocate-inf")),
        issuer=sl.fdr,
        filed=FILED,
        parts=(part,),
    )
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(ev.EffectsEstimated(order_id=order.order_id, part=0, reason="Fine."))
    sl.add(ev.InfluenceDecided(order_id=order.order_id, part=0, on=FILED, accepted=True))
    apply_land(sl, order)
    assert sl.state.quantities[uk].value == 35 and sl.state.quantities[uk].as_of == FILED
