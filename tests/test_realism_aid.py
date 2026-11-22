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
from revisionist.core.ontology import Fact
from revisionist.core.realism import resolvers
from revisionist.core.realism.agenda import MANDATE_CAP, MandateKind
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import production, shipping
from revisionist.core.realism.resolvers.production import (
    AID_ANSWER_DAYS,
    AID_LEAD_DAYS,
    AID_USD_PER_POINT,
)
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import wake_report
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
    ``production``; Sudland's card has neither. The request travels through Norra's
    chancery; Vesta's ordinary form (``fit_out``) stays in Vesta's arsenal."""
    w["pipelines"] = [
        {
            "key": "chancery",
            "name": "The chancery",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        },
        {
            "key": "arsenal",
            "name": "The arsenal",
            "source": "toy",
            "steps": [{"person": "petra", "kind": "decision", "days": 1}],
        },
        {
            "key": "admiralty",
            "name": "The admiralty",
            "source": "toy",
            "steps": [{"person": "tomas", "kind": "decision", "days": 1}],
        },
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
    fit_out = {
        "name": "fit_out",
        "pipeline": "arsenal",
        "resolver": "production",
        "params": [{"name": "sector", "kind": "enum", "choices": ["galleys", "grain"]}],
    }
    for card in w["cards"]:
        card["pipelines"] = ["chancery", "arsenal", "admiralty"]
        card["levers"] = {"petra": [plead, fit_out], "ilse": [send]}.get(card["person"], [])


def sudland_gives(w: World) -> None:
    """Sudland's admiral holds an aid form that can name Vesta too."""
    (card,) = [c for c in w["cards"] if c["person"] == "tomas"]
    card["levers"].append(
        {
            "name": "lend_galleys",
            "pipeline": "admiralty",
            "resolver": "production",
            "params": [
                {"name": "to", "kind": "enum", "choices": [VESTA]},
                {"name": "pct", "kind": "int", "lo": 0, "hi": 100},
            ],
        }
    )


def world(tmp: Path, *changes: object) -> WorldFile:
    return territories_toy(tmp, vesta, chest, route, with_economy, forms, *changes)  # type: ignore[arg-type]


def galleys(tier: int) -> object:
    return set_feature("sudland_galleys", tier=tier)


def game(tmp: Path, *changes: object, people: Sequence[str] = ("ilse", "tomas", "petra")) -> Logged:
    g = Logged(world(tmp, *changes), *people)
    g.add([ev.EconomySet(polity=entity(VESTA), pools=Pools(), on=START)])
    return g


def day(n: int) -> date:
    return START + timedelta(days=n)


def enact(g: Logged, who: str, lever: str, on: date = START, n: int = 1, **params: object) -> Order:
    (form,) = [lv for lv in g.state.cards[entity(who)].levers if lv.name == lever]
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "aid-order", who, lever, n)),
        issuer=seat(who),
        lever=lever,
        pipeline=form.pipeline,
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


def _ordinary(g: Logged, n: int = 1) -> tuple[resolvers.Change, ...]:
    order = enact(g, "petra", "fit_out", n=n, sector="galleys")
    return tuple(resolvers.ON_ORDER["production"](g.state, order))


def test_an_ordinary_production_order_puts_nothing_on_the_givers_agenda(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert _ordinary(g) == ()


def test_a_request_reaches_only_the_seats_of_the_nation_it_passes_through(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, sudland_gives)
    assert [c.mandate.seat_id for c in _request(g) if isinstance(c, ev.MandateIssued)] == [
        seat("ilse")
    ]


def test_a_full_desk_gets_no_request(tmp_path: Path) -> None:
    g = game(tmp_path)
    for n in range(MANDATE_CAP):
        g.add(resolvers.apply_changes(g.state, _request_n(g, n)))
    assert _request_n(g, MANDATE_CAP) == ()


def _request_n(g: Logged, n: int) -> tuple[resolvers.Change, ...]:
    order = enact(g, "petra", "plead", n=n, item="grain")
    return tuple(resolvers.ON_ORDER["production"](g.state, order))


def _giver_sees(g: Logged) -> tuple[object, ...]:
    """The giver's agenda, the papers it can read, and the wake report, as payloads."""
    ilse = seat("ilse")
    agenda = sorted(m.model_dump_json() for m in g.state.mandates.values() if m.seat_id == ilse)
    papers = [
        e.payload.model_dump_json()
        for e in g.log
        if isinstance(e.payload, ev.DocumentIssued) and e.scope.visible_to(ilse)
    ]
    report = wake_report.render(wake_report.build(g.log))
    return agenda, papers, report


def test_twin_games_differing_in_an_ordinary_order_look_the_same_to_the_giver(
    tmp_path: Path,
) -> None:
    seen = []
    for twin, ordinary in (("a", False), ("b", True)):
        (tmp_path / twin).mkdir()
        g = game(tmp_path / twin)
        enact(g, "petra", "plead", item="grain")
        if ordinary:
            enact(g, "petra", "fit_out", sector="galleys")
        g.walk(day(1), day(AID_ANSWER_DAYS))
        seen.append(_giver_sees(g))
    assert seen[0][0], "the request reached the giver in both games"
    assert seen[0] == seen[1]


# --- The 1941 world: only the request form asks for aid ----------------------------------

AUTUMN = Path(__file__).parents[1] / "worlds" / "autumn-1941.yaml"


@pytest.fixture(scope="module")
def autumn() -> Logged:
    return Logged(cmp.load_world(AUTUMN), "roosevelt", "churchill", "stalin")


@pytest.mark.parametrize(
    ("who", "lever", "params", "asks"),
    [
        ("churchill", "production_priority", {"sector": "escorts", "force": "home_fleet"}, False),
        ("stalin", "state_defence_order", {"sector": "tanks"}, False),
        ("stalin", "aid_request", {"item": "tanks"}, True),
    ],
)
def test_in_1941_only_the_request_form_asks_roosevelt_for_aid(
    autumn: Logged, who: str, lever: str, params: dict[str, str], asks: bool
) -> None:
    order = enact(autumn, who, lever, date(1941, 9, 10), 1, **params)
    out = resolvers.ON_ORDER["production"](autumn.state, order)
    seats = [c.mandate.seat_id for c in out if isinstance(c, ev.MandateIssued)]
    assert seats == ([seat("roosevelt")] if asks else [])
    assert len(out) == len(seats)


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


# --- PRL: the finding and the priority read the world, never a 1941 name ----------------
#
# The toy's finding is ``send_aid``, it draws on Norra's war chest, writes Vesta's share to
# ``vesta_allotment`` and clears Vesta through ``vesta_cleared``; its priority form is
# ``set_course``, whose choice ``hulls`` grows Norra's shipping. None of these is a 1941 key,
# so a rule that named ``lend_lease_finding``, ``soviet_lend_lease_eligible`` or ``ussr``
# could not pass.

ALLOTMENT, SUDLAND_ALLOTMENT, CLEARED = "vesta_allotment", "sudland_allotment", "vesta_cleared"
POOL = "norra_shipping"


def finding_keys(w: World) -> None:
    """The world names its finding, the figure it draws on, each nation's share figure and
    the one nation it clears."""
    for key, name, unit in (
        (ALLOTMENT, "Aid allotted to Vesta", "USD"),
        (SUDLAND_ALLOTMENT, "Aid allotted to Sudland", "USD"),
        (CLEARED, "Vesta cleared for aid (1 yes, 0 no)", "flag"),
    ):
        w["quantities"].append(
            {"key": key, "owner": NORRA, "name": name, "unit": unit, "computed": True}
        )
    w["production"] = {
        "findings": [
            {
                "form": "send_aid",
                "draws_on": "norra_chest",
                "shares": {VESTA: ALLOTMENT, "sudland": SUDLAND_ALLOTMENT},
                "eligible": {VESTA: CLEARED},
            }
        ],
    }


def priority_keys(w: World) -> None:
    """The world names the priority form and the choice of it that grows the lift pool."""
    w.setdefault("production", {})["priority"] = {"form": "set_course", "grows_lift_on": "hulls"}


def priority_form(w: World) -> None:
    """A priority form on Norra's card: ``hulls`` grows its shipping, ``galleys`` does not."""
    (card,) = [c for c in w["cards"] if c["person"] == "ilse"]
    card["levers"].append(
        {
            "name": "set_course",
            "pipeline": "chancery",
            "resolver": "production",
            "params": [{"name": "yard", "kind": "enum", "choices": ["hulls", "galleys"]}],
        }
    )


def _outcome(
    g: Logged, order: Order, fund: int, flag: str, shares: Sequence[str]
) -> list[tuple[object, ...]]:
    """What a finding changed, in order, by role: the eligibility flag's value, each share
    figure's value as a fraction of the fund, and a receipt to its recipient."""
    roles = {resolvers.qid(g.state, flag): "flag"}
    roles |= {resolvers.qid(g.state, s): "share" for s in shares}
    out: list[tuple[object, ...]] = []
    for c in resolvers.ON_ORDER["production"](g.state, order):
        if isinstance(c, QuantityChange):
            role = roles.get(c.quantity_id, "other")
            out.append((role, c.value / fund if role == "share" else c.value))
        elif isinstance(c, Fact):
            out.append(("receipt", c.predicate, c.obj == g.state.seats[order.issuer].embodies))
        else:
            out.append((type(c).__name__,))
    return out


TOY_SHARES = (ALLOTMENT, SUDLAND_ALLOTMENT)
AUTUMN_SHARES = ("lend_lease_share_uk", "lend_lease_share_ussr", "lend_lease_share_china")
AUTUMN_FUND = 5_985_000_000


@pytest.mark.parametrize(("toy_to", "autumn_to"), [(VESTA, "ussr"), ("sudland", "uk")])
def test_a_finding_under_other_keys_plays_as_the_1941_finding(
    tmp_path: Path, autumn: Logged, toy_to: str, autumn_to: str
) -> None:
    g = game(tmp_path, finding_keys)
    toy = _outcome(g, send(g, to=toy_to, pct=10), CHEST, CLEARED, TOY_SHARES)
    n = 2 if autumn_to == "ussr" else 3
    order = enact(
        autumn,
        "roosevelt",
        "lend_lease_finding",
        date(1941, 10, 30),
        n,
        recipient=autumn_to,
        share_pct=10,
        route="arctic_route",
    )
    real = _outcome(autumn, order, AUTUMN_FUND, "soviet_lend_lease_eligible", AUTUMN_SHARES)
    assert toy == real
    assert toy[0] == (("flag", 1) if toy_to == VESTA else ("share", 0.1))


def test_the_finding_writes_the_share_figure_the_world_names(tmp_path: Path) -> None:
    g = game(tmp_path, finding_keys)
    g.add(resolvers.apply_changes(g.state, production.resolve(g.state, send(g, pct=10))))
    assert resolvers.value(g.state, ALLOTMENT) == CHEST // 10
    assert resolvers.value(g.state, CLEARED) == 1
    assert resolvers.value(g.state, SUDLAND_ALLOTMENT) is None


def test_another_recipient_is_not_made_eligible(tmp_path: Path) -> None:
    g = game(tmp_path, finding_keys)
    g.add(resolvers.apply_changes(g.state, production.resolve(g.state, send(g, to="sudland"))))
    assert resolvers.value(g.state, CLEARED) is None
    assert resolvers.value(g.state, SUDLAND_ALLOTMENT) == CHEST // 2


def test_a_world_without_the_keys_runs_no_finding(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert production.resolve(g.state, send(g, pct=10)) == ()


def test_a_world_without_the_figure_the_finding_draws_on_writes_no_share(tmp_path: Path) -> None:
    def no_chest(w: World) -> None:
        w["quantities"] = [q for q in w["quantities"] if q["key"] != "norra_chest"]
        w["production"]["findings"][0]["draws_on"] = CLEARED

    g = game(tmp_path, finding_keys, no_chest)
    out = _outcome(g, send(g, pct=10), CHEST, CLEARED, TOY_SHARES)
    assert out == [("flag", 1), ("receipt", "received_from", True)]


def _set_course(g: Logged, yard: str, on: date, n: int) -> None:
    enact(g, "ilse", "set_course", on=on, n=n, yard=yard)


def _gain(g: Logged, on: date) -> int:
    before = resolvers.value(g.state, POOL)
    g.add(resolvers.apply_changes(g.state, production.on_day(g.state, on)))
    after = resolvers.value(g.state, POOL)
    assert before is not None and after is not None
    return after - before


MAY, JUNE = date(1900, 5, 1), date(1900, 6, 1)


def test_the_priority_the_world_names_grows_the_lift_pool_on_the_1st(tmp_path: Path) -> None:
    g = game(tmp_path, priority_form, finding_keys, priority_keys)
    _set_course(g, "hulls", START, 1)
    assert _gain(g, MAY) == production.MERCHANT_GRT_PM
    _set_course(g, "galleys", MAY, 2)
    assert _gain(g, JUNE) == 0


def test_without_the_keys_the_priority_grows_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, priority_form)
    _set_course(g, "hulls", START, 1)
    assert _gain(g, MAY) == 0
