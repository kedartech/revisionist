"""The war resolver acts on a form whose rule is ``war``, whatever the form is called."""

from datetime import date
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, PipelineId, derived_id
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import war
from revisionist.core.realism.war import War, at_war
from tests.test_war_forms_from_world import CAMPAIGN, LEVERS, Toy, toy, toy_raw

DAY = date(1900, 4, 2)


def enacted(t: Toy, lever: str, target: str) -> Order:
    """Ilse's order on ``lever``, enacted on DAY."""
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "order", lever, target)),
        issuer=t.seat,
        lever=lever,
        pipeline=PipelineId(t.ids["norra_order"]),
        params={"target": target},
        filed=DAY,
    )
    t.add(ev.OrderDrafted(order=order))
    t.add(ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED))
    return t.state.orders[order.order_id]


def test_a_war_form_of_another_name_declares_the_war() -> None:
    t = Toy()
    changes = war.resolve(t.state, enacted(t, "proclaim_war", "ostmark"))
    wars = [c for c in changes if isinstance(c, War)]
    assert [(w.a, w.b, w.since) for w in wars] == [(t.entity("norra"), t.entity("ostmark"), DAY)]


def test_the_declaration_folds_into_a_war() -> None:
    t = Toy()
    t.war_with("ostmark")
    assert at_war(t.state, t.entity("norra"), t.entity("ostmark"))
    assert war.resolve(t.state, enacted(t, "proclaim_war", "ostmark")) == ()


def test_a_form_named_declare_war_of_another_rule_declares_nothing() -> None:
    levers: list[dict[str, Any]] = [{**LEVERS[3], "name": "declare_war"}]
    t = Toy(toy(toy_raw(levers)))
    assert war.resolve(t.state, enacted(t, "declare_war", "ostmark")) == ()
