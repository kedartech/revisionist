"""Aid that arrives (AID).

The toy world (``tests/worlds/territory-toy.yaml``) gains a third nation, Vesta, which holds
the Isle and its harbour, and Norra a war chest in dollars. Norra's chancellor has an aid form
(``send_aid``: a nation, a route, a share in per cent) and Vesta's doge a request form
(``plead``). The form names, the route and the nations are the test's own, so a rule that
named a 1941 key could not pass. The Isle run crosses the Gulf, where the Sudland Galleys
stand: at war with Norra, they sink shipping on it.

Worked example (rule 1): Norra holds 1,000,000,000 dollars and sends Vesta 50 per cent,
enacted on day 0. Nothing reaches Vesta until day ``AID_LEAD_DAYS`` (45). That day 500,000,000
dollars arrive at ``AID_USD_PER_POINT`` (100,000,000) a point: Vesta's output pool grows by 5
points, less the share of the month's shipping the Isle run lost (its losses over Norra's
shipping).
"""

from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.goals import ActOf
from revisionist.core.ids import FeatureId, OrderId, derived_id
from revisionist.core.realism import resolvers
from revisionist.core.realism.agenda import MandateKind
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import production, shipping
from revisionist.core.realism.resolvers.production import (
    AID_ANSWER_DAYS,
    AID_LEAD_DAYS,
    AID_USD_PER_POINT,
)
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import object_id
from tests.test_adjacency_moves import START, Logged, World, entity, seat, set_feature
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_realism_production import with_economy
from tests.test_territory_model import CAMPAIGN

NORRA, VESTA = "norra", "vesta"
CHEST = 1_000_000_000
ROUTE = "isle_run"


def vesta(w: World) -> None:
    """A third nation holding the Isle, with a harbour there and a leader who can play."""
    w["entities"] += [
        {"key": VESTA, "kind": "polity", "name": "Vesta"},
        {"key": "petra", "kind": "person", "name": "Petra Vel", "parent": VESTA},
        {"key": "isleport", "kind": "location", "name": "Isleport", "at": [40, 150]},
    ]
    w["entities"][-1]["within"] = "isle"
    (isle,) = [t for t in w["territories"] if t["key"] == "isle"]
    isle["holder"] = VESTA
    w["cards"].append(
        {"person": "petra", "office": "Doge of Vesta", "playable": True, "principals": [VESTA]}
    )
    w["cards"][-1]["horizon_days"] = 14
    w["roster"].append(
        {"entity": "petra", "pitch": "The doge.", "reach": "The fleet of Vesta.", "composite": True}
    )


def chest(w: World) -> None:
    w["quantities"].append(
        {"key": "norra_chest", "owner": NORRA, "name": "War chest", "value": CHEST, "unit": "USD"}
    )
    w["quantities"][-1]["source"] = "toy"


def route(w: World) -> None:
    """Norra's run to the Isle: from Norrhavn, a port on the Gulf, to Isleport."""
    w["features"].append(
        {
            "key": ROUTE,
            "kind": "route",
            "name": "The Isle run",
            "side": NORRA,
            "places": ["norrhavn", "isleport"],
            "source": "toy",
        }
    )


def forms(w: World) -> None:
    """The aid form on Norra's card and the request form on Vesta's, both by the rule name
    ``production``; Sudland's card has neither."""
    w["pipelines"] = [
        {
            "key": "chancery",
            "name": "The chancery",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        }
    ]
    send = {
        "name": "send_aid",
        "pipeline": "chancery",
        "resolver": "production",
        "label": "Send aid",
        "params": [
            {"name": "to", "kind": "enum", "choices": [VESTA, "sudland"]},
            {"name": "by", "kind": "enum", "choices": [ROUTE]},
            {"name": "pct", "kind": "int", "lo": 0, "hi": 100},
        ],
    }
    plead = {
        "name": "plead",
        "pipeline": "chancery",
        "resolver": "production",
        "params": [{"name": "item", "kind": "enum", "choices": ["grain", "iron"]}],
    }
    for card in w["cards"]:
        card["pipelines"] = ["chancery"]
        card["levers"] = {"petra": [plead], "ilse": [send]}.get(card["person"], [])


def world(tmp: Path, *changes: object) -> WorldFile:
    return territories_toy(tmp, vesta, chest, route, with_economy, *changes, forms)  # type: ignore[arg-type]


def galleys(tier: int) -> object:
    return set_feature("sudland_galleys", tier=tier)


def game(tmp: Path, *changes: object, people: Sequence[str] = ("ilse", "tomas", "petra")) -> Logged:
    g = Logged(world(tmp, *changes), *people)
    g.add([ev.EconomySet(polity=entity(VESTA), pools=Pools(), on=START)])
    return g


def day(n: int) -> date:
    return START + timedelta(days=n)


def enact(g: Logged, who: str, lever: str, on: date = START, n: int = 1, **params: object) -> Order:
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "aid-order", who, n)),
        issuer=seat(who),
        lever=lever,
        pipeline=next(
            p.pipeline_id for p in g.state.pipelines.values() if p.name == "The chancery"
        ),
        params=dict(params),
        filed=on,
    )
    g.add(
        [
            ev.OrderDrafted(order=order),
            ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
        ]
    )
    return g.state.orders[order.order_id]


def send(g: Logged, to: str = VESTA, pct: int = 50, on: date = START) -> Order:
    return enact(g, "ilse", "send_aid", on=on, to=to, by=ROUTE, pct=pct)


def walk_days(g: Logged, first: int, last: int) -> list[ev.Payload]:
    out: list[ev.Payload] = []
    for n in range(first, last + 1):
        changes = resolvers.apply_changes(g.state, production.economy_day(g.state, day(n)))
        g.add(changes)
        out += changes
    return out


def output(g: Logged, polity: str) -> float:
    return g.state.economy.pools.get(entity(polity), Pools()).output


def lost_share(g: Logged, on: date) -> float:
    lost = shipping.losses(g.state, on).get(FeatureId(object_id(CAMPAIGN, "feature", ROUTE)), 0)
    pool = resolvers.value(g.state, "norra_shipping")
    assert pool
    return min(1.0, lost / pool)


# --- Rule 1: a share arrives as output after the lead time, cut by the route's losses ---


def test_the_defaults() -> None:
    assert (AID_USD_PER_POINT, AID_LEAD_DAYS) == (100_000_000, 45)


def test_a_share_arrives_as_output_points_after_the_lead_time(tmp_path: Path) -> None:
    g = game(tmp_path)
    send(g, pct=50)
    walk_days(g, 1, AID_LEAD_DAYS - 1)
    assert output(g, VESTA) == 0
    walk_days(g, AID_LEAD_DAYS, AID_LEAD_DAYS)
    assert output(g, VESTA) == pytest.approx(CHEST * 50 / 100 / AID_USD_PER_POINT)


def test_the_lead_time_runs_from_the_day_the_order_settled(tmp_path: Path) -> None:
    g = game(tmp_path)
    send(g, on=day(5))
    walk_days(g, 1, AID_LEAD_DAYS + 4)
    assert output(g, VESTA) == 0
    walk_days(g, AID_LEAD_DAYS + 5, AID_LEAD_DAYS + 5)
    assert output(g, VESTA) > 0


def test_the_share_is_cut_by_the_share_of_the_months_shipping_lost_on_the_route(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, galleys(1))
    send(g, pct=50)
    walk_days(g, 1, AID_LEAD_DAYS - 1)
    share = lost_share(g, day(AID_LEAD_DAYS))
    assert 0 < share < 1
    walk_days(g, AID_LEAD_DAYS, AID_LEAD_DAYS)
    assert output(g, VESTA) == pytest.approx(5 * (1 - share))


def test_a_route_that_loses_everything_delivers_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, galleys(3))
    send(g, pct=50)
    walk_days(g, 1, AID_LEAD_DAYS)
    assert lost_share(g, day(AID_LEAD_DAYS)) == 1
    assert output(g, VESTA) == 0


def test_a_recipient_no_route_reaches_gets_its_share_uncut(tmp_path: Path) -> None:
    g = game(tmp_path, galleys(1))
    g.add([ev.EconomySet(polity=entity("sudland"), pools=Pools(), on=START)])
    send(g, to="sudland", pct=20)
    walk_days(g, 1, AID_LEAD_DAYS)
    assert lost_share(g, day(AID_LEAD_DAYS)) > 0
    assert output(g, "sudland") == pytest.approx(2)


def test_the_giver_gets_a_report_and_spends_no_pool(tmp_path: Path) -> None:
    g = game(tmp_path)
    send(g, pct=50)
    out = walk_days(g, AID_LEAD_DAYS, AID_LEAD_DAYS)
    (paper,) = [p.document for p in out if isinstance(p, ev.DocumentIssued)]
    assert paper.scope.known_by == frozenset({seat("ilse")})
    assert "Vesta" in paper.title
    assert entity(NORRA) not in g.state.economy.pools


def test_each_share_arrives_once(tmp_path: Path) -> None:
    g = game(tmp_path)
    send(g, pct=50)
    walk_days(g, 1, 3 * AID_LEAD_DAYS)
    assert output(g, VESTA) == pytest.approx(5)


def test_without_economy_nothing_arrives(tmp_path: Path) -> None:
    def holders_only(w: World) -> None:
        w["rules"] = ["territories", "holders"]

    g = Logged(world(tmp_path, holders_only), "ilse", "tomas", "petra")
    send(g)
    assert production.economy_day(g.state, day(AID_LEAD_DAYS)) == ()


# --- Rule 2: a request raises the share on the giver's agenda --------------------------


def _request(g: Logged) -> tuple[resolvers.Change, ...]:
    order = enact(g, "petra", "plead", item="grain")
    return tuple(resolvers.ON_ORDER["production"](g.state, order))


def test_a_request_puts_the_share_on_the_givers_agenda_with_a_due_day(tmp_path: Path) -> None:
    g = game(tmp_path)
    (put,) = _request(g)
    assert isinstance(put, ev.MandateIssued)
    m = put.mandate
    assert m.seat_id == seat("ilse")
    assert m.kind is MandateKind.OPPORTUNITY
    assert (m.issued, m.expires) == (START, START + timedelta(days=AID_ANSWER_DAYS))
    assert m.scope.known_by == frozenset({seat("ilse")})
    assert m.condition == ActOf(person=entity("ilse"), lever="send_aid", params={"to": VESTA})
    assert "Vesta" in m.text


def test_the_request_lands_on_the_agenda_and_is_met_by_the_aid_form(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.add(resolvers.apply_changes(g.state, _request(g)))
    (m,) = g.state.mandates.values()
    assert m.seat_id == seat("ilse")


def test_no_agenda_item_when_nobody_holds_the_giver(tmp_path: Path) -> None:
    g = game(tmp_path, people=("tomas", "petra"))
    assert _request(g) == ()


def test_the_aid_form_itself_puts_nothing_on_an_agenda(tmp_path: Path) -> None:
    g = game(tmp_path)
    order = send(g)
    assert not any(
        isinstance(c, ev.MandateIssued) for c in resolvers.ON_ORDER["production"](g.state, order)
    )


def test_without_economy_a_request_puts_nothing_on_the_agenda(tmp_path: Path) -> None:
    def holders_only(w: World) -> None:
        w["rules"] = ["territories", "holders"]

    g = Logged(world(tmp_path, holders_only), "ilse", "tomas", "petra")
    assert _request(g) == ()


# --- Rule 3: the quantity, the route and the recipients come from the form and the world


def test_the_quantity_is_the_givers_figure_in_dollars_times_the_share(tmp_path: Path) -> None:
    def richer(w: World) -> None:
        (q,) = [q for q in w["quantities"] if q["key"] == "norra_chest"]
        q["value"] = 3 * CHEST

    g = game(tmp_path, richer)
    send(g, pct=10)
    walk_days(g, AID_LEAD_DAYS, AID_LEAD_DAYS)
    assert output(g, VESTA) == pytest.approx(3)


def test_a_form_naming_no_nation_sends_nothing(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, "ilse", "send_aid", pct=50, by=ROUTE)
    walk_days(g, AID_LEAD_DAYS, AID_LEAD_DAYS)
    assert output(g, VESTA) == 0
