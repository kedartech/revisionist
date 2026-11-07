"""Two parts landing on one day in one pass must fold: no id twice, no lost update."""

from datetime import date

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import QuantityId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.realism.apply import _land
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.quantity import Quantity
from revisionist.core.visibility import PUBLIC
from tests.test_engine_v2_contract import CAMPAIGN, Slice

ON = date(1941, 9, 11)


@pytest.fixture
def sl() -> Slice:
    return Slice()


def land_all(sl: Slice, *effects: rx.Effect) -> list[ev.Payload]:
    """Land the effects in one pass over one PassWorld, as ``apply_due`` does."""
    world = PassWorld(sl.state)
    out: list[ev.Payload] = []
    for effect in effects:
        landed, _ = _land(world, effect, sl.fdr, sl.entity("roosevelt"), ON)
        out += landed
    return out


def fold(sl: Slice, payloads: list[ev.Payload]) -> None:
    """Fold the payloads in order; a duplicate id raises."""
    for p in payloads:
        sl.add(p, PUBLIC)
    replay(sl.events)


def stock(sl: Slice, key: str, owner: str, value: int) -> QuantityId:
    q = Quantity(
        quantity_id=QuantityId(derived_id(CAMPAIGN, "test-quantity", key)),
        owner=sl.entity(owner),
        name="munitions",
        value=value,
        unit="tons",
        as_of=date(1941, 9, 1),
    )
    sl.add(ev.QuantitySet(quantity=q))
    return q.quantity_id


@pytest.mark.parametrize(
    "effect",
    [
        rx.Appointment(person="wallace", office="envoy"),
        rx.MakeStatement(theme="freedom_of_the_seas"),
        rx.MakeStatement(theme="freedom_of_the_seas", audience="churchill"),
        rx.Deal(counterparty="churchill", offer=("ships",), accept=True),
        rx.Deal(counterparty="churchill", offer=("ships", "ships"), accept=True),
        rx.Allocate(recipient="uk", what="munitions", amount=5, unit="tons"),
    ],
)
def test_the_same_effect_twice_in_one_pass_folds(sl: Slice, effect: rx.Effect) -> None:
    fields = {
        k: sl.entity(v) if k in {"person", "audience", "counterparty", "recipient"} and v else v
        for k, v in effect.model_dump().items()
        if k != "kind"
    }
    twice = type(effect)(**fields)
    stock(sl, "usa", "usa", 100)
    stock(sl, "uk", "uk", 10)
    fold(sl, land_all(sl, twice, twice))


def test_a_deal_shifts_the_relationship_once(sl: Slice) -> None:
    deal = rx.Deal(counterparty=sl.entity("churchill"), offer=("ships", "ships"), accept=True)
    landed = land_all(sl, deal)
    assert sum(isinstance(p, ev.RelationshipSet) for p in landed) == 1
    fold(sl, landed)
    [rel] = sl.state.relationships.values()
    assert rel.disposition == 1


def test_two_allocations_from_one_stock_compose(sl: Slice) -> None:
    usa = stock(sl, "usa", "usa", 100)
    uk = stock(sl, "uk", "uk", 10)
    first = rx.Allocate(recipient=sl.entity("uk"), what="munitions", amount=80, unit="tons")
    second = rx.Allocate(recipient=sl.entity("uk"), what="munitions", amount=70, unit="tons")
    fold(sl, land_all(sl, first, second))
    assert sl.state.quantities[usa].value == 0
    assert sl.state.quantities[uk].value == 110
