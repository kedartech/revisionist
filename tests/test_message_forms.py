"""A message form (IFC): a shipping form whose every parameter is free text is a message,
not a requisition.

In a territory game a shipping form that names no route, piece, waters, nation or escort
takes tonnage into its nation's lift pool. A form whose only parameters are words names
none of these either, and is read as a message instead: once enacted, the person of
another nation who decided a step of its pipeline thinks better of the issuer by
``MESSAGE_REGARD``. The toy world, with Ilse's cable decided by Sudland's Tomas.
"""

from pathlib import Path

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, derived_id
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import apply_changes, shipping
from revisionist.core.realism.resolvers.shipping import MESSAGE_REGARD
from tests.test_adjacency_moves import START, Logged, World, entity, seat
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_territory_model import CAMPAIGN


def cable(w: World) -> None:
    """A cable on Ilse's card (free text, decided by Tomas), and a requisition beside it."""
    w["pipelines"] = [
        {
            "key": "cable_office",
            "name": "The cable office",
            "source": "toy",
            "steps": [
                {"person": "ilse", "kind": "decision", "days": 1},
                {"person": "tomas", "kind": "decision", "days": 1},
            ],
        },
        {
            "key": "ministry",
            "name": "The ministry",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        },
    ]
    for card in w["cards"]:
        card["pipelines"] = ["cable_office", "ministry"]
        card["levers"] = [
            {
                "name": "cable",
                "pipeline": "cable_office",
                "resolver": "shipping",
                "params": [{"name": "message", "kind": "text"}],
            },
            {
                "name": "requisition",
                "pipeline": "ministry",
                "resolver": "shipping",
                "params": [{"name": "whose", "kind": "enum", "choices": ["army", "navy"]}],
            },
        ]


def enact(g: Logged, lever: str, pipeline: str, **params: str) -> list[ev.Payload]:
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "ifc-message", lever)),
        issuer=seat("ilse"),
        lever=lever,
        pipeline=next(p.pipeline_id for p in g.state.pipelines.values() if p.name == pipeline),
        params=dict(params),
        filed=START,
    )
    g.add(
        [
            ev.OrderDrafted(order=order),
            ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
        ]
    )
    found = g.state.orders[order.order_id]
    out = apply_changes(g.state, shipping.resolve(g.state, found))
    g.add(out)
    return out


def regard(g: Logged, of: str, toward: str) -> int | None:
    return next(
        (
            r.disposition
            for r in g.state.relationships.values()
            if (r.a, r.b) == (entity(of), entity(toward))
        ),
        None,
    )


def test_a_message_decided_abroad_raises_the_deciders_regard_for_the_issuer(
    tmp_path: Path,
) -> None:
    g = Logged(territories_toy(tmp_path, cable), "ilse", "tomas")
    before = regard(g, "tomas", "ilse") or 0
    out = enact(g, "cable", "The cable office", message="We stand with you.")
    assert regard(g, "tomas", "ilse") == before + MESSAGE_REGARD
    assert not [p for p in out if isinstance(p, ev.QuantitySet)]


def test_a_requisition_still_fills_the_lift_pool(tmp_path: Path) -> None:
    g = Logged(territories_toy(tmp_path, cable), "ilse", "tomas")
    out = enact(g, "requisition", "The ministry", whose="army")
    assert [p for p in out if isinstance(p, ev.QuantitySet)]
    assert regard(g, "tomas", "ilse") is None


def test_the_default() -> None:
    assert MESSAGE_REGARD == 1
