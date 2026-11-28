"""A message form (IFC): a shipping form whose every parameter is free text is a message,
not a requisition.

In a territory game a shipping form that names no route, piece, waters, nation or escort
takes tonnage into its nation's lift pool. A form whose only parameters are words names
none of these either, and is read as a message instead: once enacted, the person of
another nation who decided a step of its pipeline thinks better of the issuer by
``MESSAGE_REGARD``. The toy world, with Ilse's cable decided by Sudland's Tomas.
"""

import copy
from datetime import date
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, RelationshipId, derived_id
from revisionist.core.ontology import Relationship
from revisionist.core.project import project
from revisionist.core.realism import apply
from revisionist.core.realism.effect import ShiftDisposition
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import apply_changes, shipping
from revisionist.core.realism.resolvers.shipping import MESSAGE_REGARD
from revisionist.core.visibility import private_to
from revisionist.engine import campaign as cmp
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


# --- The message's regard is its own, sealed to the sender -------------------------------
#
# Kara, Tomas's foreign minister, holds a seat too. Her influence order can shift Tomas's
# regard of Ilse, which makes that relationship sealed to her seat. Ilse's cable must not
# move it: Kara would see Ilse's private cable get through Tomas's decision, and Ilse's seat
# would see something else than in the game without Kara's shift.


def kara(w: World) -> None:
    """A third seat, Sudland's foreign minister."""
    w["entities"].append(
        {"key": "kara", "kind": "person", "name": "Kara Holm", "parent": "sudland"}
    )
    w["cards"].append(
        {
            "person": "kara",
            "office": "Foreign Minister of Sudland",
            "playable": True,
            "principals": ["sudland"],
            "horizon_days": 14,
        }
    )
    w["roster"].append(
        {"entity": "kara", "pitch": "The minister.", "reach": "The embassies.", "composite": True}
    )


def three(tmp: Path) -> Logged:
    return Logged(territories_toy(tmp, kara, cable), "ilse", "tomas", "kara")


def kara_shifts(g: Logged) -> None:
    effect = ShiftDisposition(of=entity("tomas"), toward=entity("ilse"), change=2)
    g.add([apply.shift(PassWorld(g.state), effect, seat("kara"))])


def send(g: Logged, n: int) -> list[ev.Payload]:
    """Ilse's ``n``-th cable, enacted."""
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "fmr-cable", str(n))),
        issuer=seat("ilse"),
        lever="cable",
        pipeline=next(
            p.pipeline_id for p in g.state.pipelines.values() if p.name == "The cable office"
        ),
        params={"message": "We stand with you."},
        filed=START,
    )
    g.add(
        [
            ev.OrderDrafted(order=order),
            ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
        ]
    )
    out = apply_changes(g.state, shipping.resolve(g.state, g.state.orders[order.order_id]))
    g.add(out)
    return out


def seen(g: Logged, who: str, of: str, toward: str) -> list[tuple[str, int]]:
    """Each regard ``of`` holds for ``toward`` that ``who``'s seat sees, by id."""
    return sorted(
        (r.relationship_id, r.disposition)
        for r in project(g.state, seat(who)).relationships.values()
        if (r.a, r.b) == (entity(of), entity(toward))
    )


def test_the_cable_reads_the_same_to_ilse_and_tells_the_other_seat_nothing(
    tmp_path: Path,
) -> None:
    ilse: list[list[tuple[str, int]]] = []
    for twin, shifted_first in (("a", True), ("b", False)):
        (tmp_path / twin).mkdir()
        g = three(tmp_path / twin)
        if shifted_first:
            kara_shifts(g)
        before = project(g.state, seat("kara")).relationships
        send(g, 1)
        assert project(g.state, seat("kara")).relationships == before
        ilse.append(seen(g, "ilse", "tomas", "ilse"))
    assert ilse[0] == ilse[1]
    assert [n for _, n in ilse[0]] == [MESSAGE_REGARD]


def test_a_second_cable_raises_the_same_regard(tmp_path: Path) -> None:
    g = three(tmp_path)
    kara_shifts(g)
    send(g, 1)
    send(g, 2)
    assert [n for _, n in seen(g, "ilse", "tomas", "ilse")] == [2 * MESSAGE_REGARD]
    assert [n for _, n in seen(g, "kara", "tomas", "ilse")] == [2]


def test_a_regard_sealed_to_the_sender_alone_is_the_one_the_cable_raises(
    tmp_path: Path,
) -> None:
    g = three(tmp_path)
    held = Relationship(
        relationship_id=RelationshipId(
            derived_id(CAMPAIGN, "rel", entity("tomas"), entity("ilse"))
        ),
        a=entity("tomas"),
        b=entity("ilse"),
        disposition=1,
        scope=private_to(seat("ilse")),
    )
    g.add([ev.RelationshipSet(relationship=held)])
    send(g, 1)
    assert seen(g, "ilse", "tomas", "ilse") == [(held.relationship_id, 1 + MESSAGE_REGARD)]


def test_once_another_seat_knows_the_messages_regard_the_cable_leaves_it(
    tmp_path: Path,
) -> None:
    g = three(tmp_path)
    send(g, 1)
    (rel,) = [r for r in g.state.relationships.values() if r.a == entity("tomas")]
    shown = rel.model_copy(update={"scope": rel.scope.grant(seat("kara"))})
    g.add([ev.RelationshipSet(relationship=shown)])
    assert send(g, 2) == []
    assert seen(g, "kara", "tomas", "ilse") == [(rel.relationship_id, MESSAGE_REGARD)]


def test_a_message_at_the_regard_cap_still_takes_no_tonnage(tmp_path: Path) -> None:
    g = three(tmp_path)
    held = Relationship(
        relationship_id=RelationshipId(
            derived_id(CAMPAIGN, "rel", entity("tomas"), entity("ilse"))
        ),
        a=entity("tomas"),
        b=entity("ilse"),
        disposition=5,
        scope=private_to(seat("ilse")),
    )
    g.add([ev.RelationshipSet(relationship=held)])
    assert send(g, 1) == []


# In 1941 the world declares Roosevelt's regard of Churchill for every seat to see, and an
# influence order on Churchill's regard of Roosevelt lands on that record, so the cable to
# Churchill reads the same in both games there.

AUTUMN = Path(__file__).parents[1] / "worlds" / "autumn-1941.yaml"


@pytest.fixture(scope="module")
def autumn() -> Logged:
    return Logged(cmp.load_world(AUTUMN), "roosevelt", "churchill", "stalin")


def test_in_1941_the_cable_to_churchill_reads_the_same_with_or_without_stalins_shift(
    autumn: Logged,
) -> None:
    roosevelt = []
    for shifted_first in (True, False):
        g = copy.copy(autumn)
        g.log = list(autumn.log)
        if shifted_first:
            effect = ShiftDisposition(of=entity("churchill"), toward=entity("roosevelt"), change=2)
            g.add([apply.shift(PassWorld(g.state), effect, seat("stalin"))])
        before = project(g.state, seat("stalin")).relationships
        order = Order(
            order_id=OrderId(derived_id(CAMPAIGN, "fmr-cable-1941")),
            issuer=seat("roosevelt"),
            lever="cable_to_churchill",
            pipeline=next(
                p.pipeline_id
                for p in g.state.pipelines.values()
                if p.name == "A cable to the Prime Minister"
            ),
            params={"message": "The President sends his regards."},
            filed=date(1941, 9, 10),
        )
        g.add(
            [
                ev.OrderDrafted(order=order),
                ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
            ]
        )
        g.add(apply_changes(g.state, shipping.resolve(g.state, g.state.orders[order.order_id])))
        assert project(g.state, seat("stalin")).relationships == before
        roosevelt.append(seen(g, "roosevelt", "churchill", "roosevelt"))
    assert roosevelt[0] == roosevelt[1]
    assert [n for _, n in roosevelt[0]] == [MESSAGE_REGARD]
