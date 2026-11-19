"""Production: output and manpower build strength (PRD).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories``,
``holders`` and ``economy`` on, and each leader's card holds a production form whose rule
name is ``economy``. The Norra Levy (a levy, at most 5 strength) stands at Norrhavn; the
Sudland Galleys (galleys, at most 3) in the Gulf Roads. A test gives a nation its pools
directly, so the first-of-the-month payment does not decide the result.

Worked example (rule 1): Norra, with 50 output points and 5 manpower points, enacts a
production form for its levy (strength 2) on day 0. Nothing changes until day
``LEAD_DAYS`` (30): that day Norra's pools fall to 40 and 4 and the levy stands at 3.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path

from revisionist.core import events as ev
from revisionist.core.fold import state_hash
from revisionist.core.ids import OrderId, derived_id
from revisionist.core.realism import resolvers
from revisionist.core.realism.document import DocumentView
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import production
from revisionist.core.realism.resolvers.production import (
    ADDS_PER_STEP,
    LEAD_DAYS,
    STEP_COST,
    STEP_MANPOWER,
)
from revisionist.core.world import WorldFile
from tests.test_adjacency_moves import START, Logged, World, entity, piece, seat, set_feature
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_supply import lone, with_supply
from tests.test_territory_model import CAMPAIGN

Change = Callable[[World], None]
NORRA, SUDLAND = "norra", "sudland"
LEVY, GALLEYS = "norra_levy", "sudland_galleys"
RICH = Pools(output=50, manpower=5)


def with_economy(w: World) -> None:
    w["rules"] = [*{*w.get("rules", []), "territories", "holders", "economy"}]


def forms(w: World) -> None:
    """A production form on each leader's card, by the rule name ``economy``: it names a
    force, or a figure it adds to."""
    w["pipelines"] = [
        {
            "key": "war_office",
            "name": "The war office",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        }
    ]
    force = {"name": "force", "kind": "enum", "choices": [LEVY, GALLEYS, "sudland_levy"]}
    adds_to = {"name": "adds_to", "kind": "enum", "choices": ["norra_shipping", "norra_forts"]}
    for card in w["cards"]:
        card["pipelines"] = ["war_office"]
        card["levers"] = [
            {"name": "build", "pipeline": "war_office", "resolver": "economy", "params": [force]},
            {
                "name": "build_up",
                "pipeline": "war_office",
                "resolver": "economy",
                "params": [adds_to],
            },
        ]


def forts(w: World) -> None:
    """A second figure of Norra's, which no code names."""
    w["quantities"].append(
        {"key": "norra_forts", "owner": "norra", "name": "Forts", "value": 7, "unit": "forts"}
    )
    w["quantities"][-1]["source"] = "toy"


def world(tmp: Path, *changes: Change) -> WorldFile:
    return territories_toy(tmp, with_economy, set_feature(LEVY, tier=2), *changes, forms)


def game(tmp: Path, *changes: Change, pools: dict[str, Pools] | None = None) -> Logged:
    g = Logged(world(tmp, *changes), "ilse", "tomas")
    given = {NORRA: RICH} if pools is None else pools
    g.add([ev.EconomySet(polity=entity(k), pools=p, on=START) for k, p in sorted(given.items())])
    return g


def day(n: int) -> date:
    return START + timedelta(days=n)


def enact(g: Logged, by: str, on: date = START, n: int = 1, **params: str) -> Order:
    """An order for one of the production forms, enacted on ``on``."""
    lever = "build_up" if "adds_to" in params else "build"
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "prd-order", by, n)),
        issuer=seat(by),
        lever=lever,
        pipeline=next(
            p.pipeline_id for p in g.state.pipelines.values() if p.name == "The war office"
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


def walk_days(g: Logged, first: int, last: int) -> list[ev.Payload]:
    """``production.on_day`` for each day from ``first`` to ``last``, folded in turn."""
    out: list[ev.Payload] = []
    for n in range(first, last + 1):
        changes = resolvers.apply_changes(g.state, production.economy_day(g.state, day(n)))
        g.add(changes)
        out += changes
    return out


def tier(g: Logged, key: str) -> int:
    return piece(g.state, key).tier


def pools(g: Logged, polity: str) -> Pools:
    return g.state.economy.pools.get(entity(polity), Pools())


def papers(out: Sequence[ev.Payload]) -> list[DocumentView]:
    return [p.document for p in out if isinstance(p, ev.DocumentIssued)]


def said(doc: DocumentView) -> str:
    return " ".join(f"{b.label} {b.value}" for b in doc.body)


# --- Rule 1: a step costs output and manpower and lands after the lead time ----------


def test_a_step_lands_after_the_lead_time_and_is_paid_from_both_pools(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, "ilse", force=LEVY)
    walk_days(g, 1, LEAD_DAYS - 1)
    assert tier(g, LEVY) == 2
    assert pools(g, NORRA) == RICH
    out = walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert tier(g, LEVY) == 3
    assert pools(g, NORRA) == Pools(
        output=RICH.output - STEP_COST, manpower=RICH.manpower - STEP_MANPOWER
    )
    (paper,) = papers(out)
    assert paper.scope.known_by == frozenset({seat("ilse")})
    assert "The Norra Levy" in said(paper)


def test_the_defaults() -> None:
    assert (STEP_COST, STEP_MANPOWER, LEAD_DAYS) == (10, 1, 30)


def test_the_lead_time_runs_from_the_day_the_order_left_its_last_step(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, "ilse", on=day(5), force=LEVY)
    walk_days(g, 1, LEAD_DAYS + 4)
    assert tier(g, LEVY) == 2
    walk_days(g, LEAD_DAYS + 5, LEAD_DAYS + 5)
    assert tier(g, LEVY) == 3


def test_no_step_past_the_kinds_maximum_and_nothing_spent(tmp_path: Path) -> None:
    g = game(tmp_path, set_feature(GALLEYS, tier=3), pools={SUDLAND: RICH})
    enact(g, "tomas", force=GALLEYS)
    out = walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert tier(g, GALLEYS) == 3
    assert pools(g, SUDLAND) == RICH
    (paper,) = papers(out)
    assert "full strength" in said(paper)


def test_a_galley_below_its_maximum_gains_a_step(tmp_path: Path) -> None:
    g = game(tmp_path, set_feature(GALLEYS, tier=2), pools={SUDLAND: RICH})
    enact(g, "tomas", force=GALLEYS)
    walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert tier(g, GALLEYS) == 3


def test_a_force_of_another_nation_gains_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, pools={NORRA: RICH, SUDLAND: RICH})
    enact(g, "ilse", force="sudland_levy")
    out = walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert piece(g.state, "sudland_levy").tier == 0
    assert pools(g, NORRA) == RICH and pools(g, SUDLAND) == RICH
    (paper,) = papers(out)
    assert "not a force of" in said(paper)


def test_each_enacted_order_counts_once(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, "ilse", force=LEVY, n=1)
    enact(g, "ilse", force=LEVY, n=2)
    walk_days(g, 1, 3 * LEAD_DAYS)
    assert tier(g, LEVY) == 4
    assert pools(g, NORRA).output == RICH.output - 2 * STEP_COST


def test_more_sittings_give_the_same_outcome(tmp_path: Path) -> None:
    """Invariant 3: walking the same days in one go or in three gives the same state."""
    one, three = game(tmp_path), game(tmp_path)
    for g in (one, three):
        enact(g, "ilse", force=LEVY)
    walk_days(one, 1, 45)
    for first, last in ((1, 10), (11, 30), (31, 45)):
        walk_days(three, first, last)
    assert state_hash(one.state) == state_hash(three.state)
    assert tier(one, LEVY) == 3


# --- Rule 2: short pools or no supply on the due day add nothing, and the report says which


def test_a_short_output_pool_adds_nothing_and_the_report_says_output(tmp_path: Path) -> None:
    short = Pools(output=STEP_COST - 1, manpower=5)
    g = game(tmp_path, pools={NORRA: short})
    enact(g, "ilse", force=LEVY)
    out = walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert tier(g, LEVY) == 2
    assert pools(g, NORRA) == short
    (paper,) = papers(out)
    assert "output" in said(paper) and "manpower" not in said(paper)


def test_an_empty_manpower_pool_adds_nothing_and_the_report_says_manpower(
    tmp_path: Path,
) -> None:
    empty = Pools(output=50, manpower=0)
    g = game(tmp_path, pools={NORRA: empty})
    enact(g, "ilse", force=LEVY)
    out = walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert tier(g, LEVY) == 2
    assert pools(g, NORRA) == empty
    (paper,) = papers(out)
    assert "manpower" in said(paper) and "output" not in said(paper)


def test_the_pools_are_read_on_the_due_day(tmp_path: Path) -> None:
    g = game(tmp_path, pools={NORRA: Pools()})
    enact(g, "ilse", force=LEVY)
    walk_days(g, 1, LEAD_DAYS - 1)
    g.add([ev.EconomySet(polity=entity(NORRA), pools=RICH, on=day(LEAD_DAYS - 1))])
    walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert tier(g, LEVY) == 3


def test_a_second_order_finds_the_pool_the_first_spent(tmp_path: Path) -> None:
    g = game(tmp_path, pools={NORRA: Pools(output=STEP_COST, manpower=5)})
    enact(g, "ilse", force=LEVY, n=1)
    enact(g, "ilse", force=LEVY, n=2)
    out = walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert tier(g, LEVY) == 3
    assert [("short" in said(p)) for p in papers(out)].count(True) == 1


def test_out_of_supply_on_the_due_day_adds_nothing_and_the_report_says_supply(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, with_supply, *lone())
    enact(g, "ilse", force=LEVY)
    out = walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert tier(g, LEVY) == 2
    assert pools(g, NORRA) == RICH
    (paper,) = papers(out)
    assert "supply" in said(paper)


def test_in_supply_with_the_rule_on_a_step_lands(tmp_path: Path) -> None:
    g = game(tmp_path, with_supply)
    enact(g, "ilse", force=LEVY)
    walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert tier(g, LEVY) == 3


# --- Rule 3: a form may name a world figure it adds to instead -------------------------


def test_a_form_naming_a_figure_adds_to_it_instead_of_a_piece(tmp_path: Path) -> None:
    g = game(tmp_path, forts)
    enact(g, "ilse", adds_to="norra_forts")
    out = walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert resolvers.value(g.state, "norra_forts") == 7 + ADDS_PER_STEP
    assert resolvers.value(g.state, "norra_shipping") == 100000
    assert tier(g, LEVY) == 2
    assert pools(g, NORRA) == Pools(
        output=RICH.output - STEP_COST, manpower=RICH.manpower - STEP_MANPOWER
    )
    (paper,) = papers(out)
    assert "Forts" in said(paper)


def test_a_figure_is_short_of_pools_like_a_piece(tmp_path: Path) -> None:
    g = game(tmp_path, forts, pools={NORRA: Pools(output=50, manpower=0)})
    enact(g, "ilse", adds_to="norra_forts")
    walk_days(g, LEAD_DAYS, LEAD_DAYS)
    assert resolvers.value(g.state, "norra_forts") == 7


# --- Rule 4: registered under ``economy`` for orders and for the daily walk ------------


def test_the_day_walk_lands_the_step(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, "ilse", force=LEVY)
    g.walk(day(1), day(LEAD_DAYS - 1))
    assert tier(g, LEVY) == 2
    g.walk(day(LEAD_DAYS), day(LEAD_DAYS))
    assert tier(g, LEVY) == 3


def test_the_order_itself_changes_nothing_at_once(tmp_path: Path) -> None:
    g = game(tmp_path)
    order = enact(g, "ilse", force=LEVY)
    assert resolvers.ON_ORDER["economy"](g.state, order) == ()


# --- Rule 5: gated by ``economy`` -----------------------------------------------------


def test_without_economy_nothing_is_built(tmp_path: Path) -> None:
    def holders_only(w: World) -> None:
        w["rules"] = ["territories", "holders"]

    g = Logged(world(tmp_path, holders_only), "ilse", "tomas")
    enact(g, "ilse", force=LEVY)
    assert production.economy_day(g.state, day(LEAD_DAYS)) == ()
    assert tier(g, LEVY) == 2
