"""Production forms that act (IFC): a form whose rule name is ``production`` and that is
not an aid finding or an aid order builds, asks abroad or mobilises, with ``economy`` on.

The toy world as ``tests/test_realism_production.py`` plays it, with the leaders' forms
carrying the rule name ``production``. What a form does is read from what its parameters
and its pipeline name in the world, never from its name:

- one naming a ``force`` or a figure it ``adds_to`` builds a step as the economy rule's
  forms do, ``LEAD_DAYS`` after it leaves its last step;
- one whose pipeline has a decision by a person of another nation is a request granted
  once enacted: ``AID_LEAD_DAYS`` later that nation's aid fund sends ``REQUEST_SHARE_PCT``
  of itself, as aid, to the asker's output pool;
- one naming none of these mobilises: ``LEAD_DAYS`` later its nation spends
  ``STEP_MANPOWER`` manpower for ``MOBILISE_OUTPUT`` output.
"""

from pathlib import Path

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, derived_id
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers.production import (
    AID_LEAD_DAYS,
    AID_USD_PER_POINT,
    LEAD_DAYS,
    MOBILISE_OUTPUT,
    REQUEST_SHARE_PCT,
    STEP_COST,
    STEP_MANPOWER,
)
from revisionist.core.state import Rule
from tests.test_adjacency_moves import START, Logged, entity, seat, set_feature
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_realism_production import (
    LEVY,
    NORRA,
    RICH,
    SUDLAND,
    World,
    forms,
    forts,
    papers,
    pools,
    said,
    tier,
    walk_days,
    with_economy,
)
from tests.test_territory_model import CAMPAIGN

FUND = 3_000_000_000


def production_forms(w: World) -> None:
    """The economy rule's two forms under the rule name ``production``, a form naming
    nothing the world knows, and a request whose pipeline a Sudland person decides; and a
    Sudland fund in dollars."""
    forms(w)
    w["pipelines"].append(
        {
            "key": "envoy",
            "name": "The envoy",
            "source": "toy",
            "steps": [
                {"person": "ilse", "kind": "decision", "days": 1},
                {"person": "tomas", "kind": "decision", "days": 1},
            ],
        }
    )
    sector = {"name": "sector", "kind": "enum", "choices": ["steel", "oil"]}
    for card in w["cards"]:
        card["pipelines"] = ["war_office", "envoy"]
        for lever in card["levers"]:
            lever["resolver"] = "production"
        card["levers"] += [
            {
                "name": "plan",
                "pipeline": "war_office",
                "resolver": "production",
                "params": [sector],
            },
            {"name": "ask", "pipeline": "envoy", "resolver": "production", "params": [sector]},
        ]
    w["quantities"].append(
        {"key": "sudland_fund", "owner": "sudland", "name": "Fund", "value": FUND, "unit": "USD"}
    )
    w["quantities"][-1]["source"] = "toy"


def game(tmp: Path, pools_: dict[str, Pools] | None = None) -> Logged:
    world = territories_toy(tmp, with_economy, set_feature(LEVY, tier=2), forts, production_forms)
    g = Logged(world, "ilse", "tomas")
    given = {NORRA: RICH} if pools_ is None else pools_
    g.add(
        [
            ev.EconomySet(polity=entity(k), pools=p, on=g.state.in_world_date)
            for k, p in given.items()
        ]
    )
    return g


def enact(g: Logged, lever: str, pipeline: str, **params: str) -> Order:
    """Ilse's order for ``lever``, enacted on the first day."""
    on = START
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "ifc-order", lever)),
        issuer=seat("ilse"),
        lever=lever,
        pipeline=next(p.pipeline_id for p in g.state.pipelines.values() if p.name == pipeline),
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


def test_a_production_form_naming_a_force_builds_a_step_after_the_lead_time(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, "build", "The war office", force=LEVY)
    walk_days(g, 1, LEAD_DAYS - 1)
    assert tier(g, LEVY) == 2
    out = walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert tier(g, LEVY) == 3
    assert pools(g, NORRA) == Pools(
        output=RICH.output - STEP_COST, manpower=RICH.manpower - STEP_MANPOWER
    )
    (paper,) = papers(out)
    assert "The Norra Levy" in said(paper)


def test_a_production_form_naming_a_figure_adds_to_it(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, "build_up", "The war office", adds_to="norra_forts")
    walk_days(g, 1, LEAD_DAYS)
    forts_now = next(q for q in g.state.quantities.values() if q.name == "Forts")
    assert forts_now.value == 8


def test_a_production_form_naming_nothing_mobilises_after_the_lead_time(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, "plan", "The war office", sector="steel")
    walk_days(g, 1, LEAD_DAYS - 1)
    assert pools(g, NORRA) == RICH
    out = walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert pools(g, NORRA) == Pools(
        output=RICH.output + MOBILISE_OUTPUT, manpower=RICH.manpower - STEP_MANPOWER
    )
    (paper,) = papers(out)
    assert paper.scope.known_by == frozenset({seat("ilse")})


def test_a_mobilisation_with_no_manpower_raises_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, {NORRA: Pools(output=5, manpower=0)})
    enact(g, "plan", "The war office", sector="oil")
    out = walk_days(g, 1, LEAD_DAYS)
    assert pools(g, NORRA) == Pools(output=5, manpower=0)
    (paper,) = papers(out)
    assert "manpower" in said(paper)


def test_a_request_another_nation_decides_sends_its_aid_once_enacted(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, "ask", "The envoy", sector="oil")
    walk_days(g, 1, AID_LEAD_DAYS - 1)
    assert pools(g, NORRA) == RICH
    walk_days(g, AID_LEAD_DAYS, AID_LEAD_DAYS)
    sent = FUND * REQUEST_SHARE_PCT / 100 / AID_USD_PER_POINT
    assert pools(g, NORRA).output == RICH.output + sent
    assert pools(g, SUDLAND) == Pools()


def test_a_request_is_not_a_mobilisation(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, "ask", "The envoy", sector="oil")
    walk_days(g, 1, LEAD_DAYS)
    assert pools(g, NORRA) == RICH


def test_with_economy_off_no_production_form_builds_or_mobilises(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.state = g.state.model_copy(update={"rules": g.state.rules - {Rule.ECONOMY}})
    enact(g, "plan", "The war office", sector="steel")
    enact(g, "build", "The war office", force=LEVY)
    walk_days(g, 1, LEAD_DAYS)
    assert tier(g, LEVY) == 2
    assert pools(g, NORRA) == RICH


def test_the_defaults() -> None:
    assert (MOBILISE_OUTPUT, REQUEST_SHARE_PCT) == (5, 10)
