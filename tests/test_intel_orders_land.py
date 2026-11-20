"""Intelligence orders reach the rules: forms registered, written effects landed (INT).

IOR wrote the rules as four functions in ``detect``; this file checks that both public
ways of giving an order reach them. A form is a lever with the rule name ``intel``; a
written order carries an investigate, a force order, an allocate or an engagement with
IOR's optional fields. The world is ``tests/worlds/intel-toy.yaml``: Norra's chancellor
has a form for each of the five orders and commands the same five in writing through her
chief of intelligence, and every outcome there is certain (the kites and the pickets find
nothing of their own accord; a flight or a patrol finds what it looks at).

The first half files orders as the tick leaves them and walks the days (the core path);
the second half plays twin games through the web room, one giving each order by its form
and one in writing, and compares what came of them.
"""

import ast
import hashlib
import json
import re
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId, OrderId, derived_id
from revisionist.core.realism import apply, detect, resolvers
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.effect import (
    Allocate,
    Effect,
    Engagement,
    Fidelity,
    IntelOrder,
    Investigate,
    MoveForce,
    Posture,
    Route,
    RoutedOrder,
    RoutedPart,
    SetEngagement,
)
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import RESOLVER_KEYS
from revisionist.core.realism.resolvers import intel
from revisionist.core.state import Rule, State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import orders_reader
from revisionist.engine.emit import Emitter
from revisionist.engine.llm import Reply, Request, Transport
from revisionist.engine.store import load_state as store_state
from tests.test_adjacency_moves import Logged, seat
from tests.test_territory_model import CAMPAIGN, refused
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, log_of, state_of

WORLD = Path(__file__).parent / "worlds" / "intel-toy.yaml"
START = date(1900, 4, 2)
NORRA = "norra"
SRC = Path(__file__).parents[1] / "src" / "revisionist" / "core" / "realism"


def day(n: int) -> date:
    return START + timedelta(days=n)


def entity(key: str) -> EntityId:
    return EntityId(object_id(CAMPAIGN, "entity", key))


def fid(key: str) -> FeatureId:
    return FeatureId(object_id(CAMPAIGN, "feature", key))


def world(**changes: Any) -> WorldFile:
    w = cmp.load_world(WORLD)
    return w.model_copy(update=changes) if changes else w


def game(w: WorldFile | None = None) -> Logged:
    return Logged(w or world(), "ilse", "tomas")


def with_output(g: Logged, output: float) -> None:
    g.add([ev.EconomySet(polity=entity(NORRA), pools=Pools(output=output), on=START)])


def write(g: Logged, effect: Effect, on: date, n: int = 1) -> OrderId:
    """``effect`` as one command part by Norra's chancellor, carried out in full on ``on``."""
    routed = RoutedOrder(
        order_id=OrderId(derived_id("int", "order", n)),
        issuer=seat("ilse"),
        filed=on,
        parts=(
            RoutedPart(
                route=Route.COMMAND, effect=effect, domain="intelligence", executor=entity("ansel")
            ),
        ),
    )
    g.add(
        [
            ev.OrderRouted(order=routed),
            ev.OrderExecuted(order_id=routed.order_id, part=0, on=on, fidelity=Fidelity.FULL),
        ]
    )
    return routed.order_id


def form(g: Logged, lever: str, on: date, n: int = 1, **params: str) -> OrderId:
    """The form ``lever`` with ``params``, enacted on ``on`` (it left its last step then)."""
    found = next(x for x in g.state.cards[entity("ilse")].levers if x.name == lever)
    (choice,) = next(p for p in found.params if p.name == "intel").choices
    order = Order(
        order_id=OrderId(derived_id("int", "form", n)),
        issuer=seat("ilse"),
        lever=lever,
        pipeline=found.pipeline,
        params={"intel": choice, **params},
        filed=on,
    )
    g.add(
        [
            ev.OrderDrafted(order=order),
            ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
        ]
    )
    return order.order_id


def by_aide(g: Logged, *orders: OrderId) -> None:
    """Mark ``orders`` as the aide's, as the fold keeps them from an aide's commit."""
    g.state = g.state.model_copy(update={"aide_orders": g.state.aide_orders | set(orders)})


def kinds(out: Sequence[ev.Event], kind: type) -> list[Any]:
    return [e.payload for e in out if isinstance(e.payload, kind)]


def recon(area: str = "sudland_coast") -> Investigate:
    return Investigate(
        target=entity(area), question="recon", intel=IntelOrder.RECON, flier=fid("norra_kites")
    )


def agent(area: str = "sudland_coast") -> Investigate:
    return Investigate(target=entity(area), question="agent", intel=IntelOrder.AGENT)


def funding() -> Allocate:
    return Allocate(
        recipient=entity(NORRA),
        what="codebreaking",
        amount=0,
        unit="points",
        intel=IntelOrder.CODEBREAKING,
    )


def conceal(on: bool = True) -> SetEngagement:
    return SetEngagement(force=fid("norra_levy"), zone="", rule=Engagement.DEFEND, concealed=on)


def patrol() -> MoveForce:
    return MoveForce(force=fid("norra_pickets"), posture=Posture.PATROL)


# --- Rule 1: the rule name is registered -------------------------------------------------


def test_intel_is_registered_for_forms_and_the_day_walk() -> None:
    assert "intel" in RESOLVER_KEYS
    assert resolvers.ON_ORDER["intel"] is intel.resolve
    assert resolvers.ON_DAY["intel"] is intel.on_day


def test_the_intel_toy_compiles_only_with_the_function_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game()  # compiles
    monkeypatch.delitem(resolvers.ON_ORDER, "intel")
    assert any("has no rule yet: intel" in p for p in refused(world()))


def test_an_agent_set_and_a_codebreaking_set_pass_through_apply_changes() -> None:
    g = game()
    placed = ev.AgentSet(nation=entity(NORRA), index=0, agent=detect.Agent(area=entity("isle")))
    raised = ev.CodebreakingSet(nation=entity(NORRA), level=1, on=day(30))
    changes: tuple[resolvers.Change, ...] = (placed, raised)
    assert resolvers.apply_changes(g.state, changes) == [placed, raised]


def test_each_intel_form_names_which_of_the_five_orders_it_is() -> None:
    g = game()
    forms = {x.name: intel.form_of(x) for x in g.state.cards[entity("ilse")].levers}
    assert forms == {
        "fly_recon": intel.Form.RECON,
        "patrol": intel.Form.PATROL,
        "place_agent": intel.Form.AGENT,
        "fund_codebreaking": intel.Form.CODEBREAKING,
        "conceal": intel.Form.CONCEAL,
    }


# --- Rules 2 and 3: each order lands from a form and from writing, through the same calls --


def _intel(state: State) -> detect.Intelligence:
    return state.intelligence[entity(NORRA)]


BY = ("written", "form")


def give(g: Logged, by: str, order: str, n: int = 1, concealed: bool = True) -> OrderId:
    """One of the five orders on day ``n``, in writing or by its form."""
    if by == "written":
        effects: dict[str, Effect] = {
            "recon": recon(),
            "patrol": patrol(),
            "agent": agent(),
            "codebreaking": funding(),
            "conceal": conceal(concealed),
        }
        effect = effects[order]
        return write(g, effect, day(n), n)
    lever, params = {
        "recon": ("fly_recon", {"piece": "norra_kites", "area": "sudland_coast"}),
        "patrol": ("patrol", {"piece": "norra_pickets"}),
        "agent": ("place_agent", {"area": "sudland_coast"}),
        "codebreaking": ("fund_codebreaking", {}),
        "conceal": ("conceal", {"piece": "norra_levy", "concealed": "yes" if concealed else "no"}),
    }[order]
    return form(g, lever, day(n), n, **params)


@pytest.mark.parametrize("by", BY)
def test_a_recon_flight_searches_its_area_on_the_next_days_roll(by: str) -> None:
    g = game()
    give(g, by, "recon")
    g.walk(day(1), day(1))
    kites = g.state.features[fid("norra_kites")]
    assert (kites.recon, kites.recon_on) == (entity("sudland_coast"), day(2))


@pytest.mark.parametrize("by", BY)
def test_a_flight_finds_the_levy_and_a_report_reaches_the_seat(by: str) -> None:
    g = game()
    give(g, by, "recon")
    out = g.walk(day(1), day(4))
    (made,) = [m for m in kinds(out, ev.ReportMade) if m.report.source is detect.Source.AIR]
    assert made.report.area == entity("sudland_coast") and made.report.seen == day(2)


@pytest.mark.parametrize("by", BY)
def test_a_patrol_sets_the_patrol_posture_and_reports_the_galleys(by: str) -> None:
    g = game()
    give(g, by, "patrol")
    out = g.walk(day(1), day(4))
    assert g.state.features[fid("norra_pickets")].posture is Posture.PATROL
    found = [m for m in kinds(out, ev.ReportMade) if m.report.source is detect.Source.PATROL]
    assert found and {m.report.area for m in found} == {entity("open_sea")}


@pytest.mark.parametrize("by", BY)
def test_an_agent_is_placed_after_the_agents_days(by: str) -> None:
    g = game()
    give(g, by, "agent")
    g.walk(day(1), day(1))
    (placed,) = _intel(g.state).agents
    assert placed.area == entity("sudland_coast")
    assert placed.since == day(1 + detect.AGENT_DAYS)


@pytest.mark.parametrize("by", BY)
def test_a_funding_raises_the_level_and_spends_output(by: str) -> None:
    g = game()
    with_output(g, 25)
    give(g, by, "codebreaking")
    g.walk(day(1), day(1))
    assert _intel(g.state).raised == (day(1 + detect.CODE_DAYS),)
    assert g.state.economy.pools[entity(NORRA)].output == 25 - detect.CODE_COST


@pytest.mark.parametrize("by", BY)
def test_a_concealment_conceals_and_a_second_lifts_it(by: str) -> None:
    g = game()
    give(g, by, "conceal", 1, concealed=True)
    g.walk(day(1), day(1))
    assert g.state.features[fid("norra_levy")].concealed is True
    give(g, by, "conceal", 2, concealed=False)
    g.walk(day(2), day(2))
    assert g.state.features[fid("norra_levy")].concealed is False


def test_an_engagement_without_concealed_leaves_concealment_as_it_was() -> None:
    g = game()
    write(g, conceal(True), day(1), 1)
    write(g, SetEngagement(force=fid("norra_levy"), zone="", rule=Engagement.HOLD_FIRE), day(2), 2)
    g.walk(day(1), day(2))
    levy = g.state.features[fid("norra_levy")]
    assert levy.concealed is True and levy.engagement is Engagement.HOLD_FIRE


# --- refusals: the rules' own words reach the seat, and nothing else lands ---------------


def _papers(out: Sequence[ev.Event]) -> list[ev.DocumentIssued]:
    return [p for p in kinds(out, ev.DocumentIssued) if p.document.scope.visible_to(seat("ilse"))]


def _words(out: Sequence[ev.Event]) -> str:
    return " ".join(
        f"{d.document.title} {' '.join(str(f.value) for f in d.document.body)}"
        for d in _papers(out)
    )


def short_range() -> WorldFile:
    """The toy with the kites reaching one step: the Sudland Coast is two away."""
    w = world()
    kinds = tuple(
        k.model_copy(update={"range_steps": 1}) if k.key == "kite" else k for k in w.piece_kinds
    )
    return w.model_copy(update={"piece_kinds": kinds})


def test_a_flight_beyond_its_range_is_refused_in_the_rules_words() -> None:
    g = game(short_range())
    write(g, recon(), day(1))
    out = g.walk(day(1), day(1))
    assert g.state.features[fid("norra_kites")].recon is None
    assert "beyond The Norra Kites's range" in _words(out)


@pytest.mark.parametrize("by", BY)
def test_funding_with_too_little_output_is_refused_in_the_rules_words(by: str) -> None:
    g = game()
    give(g, by, "codebreaking")
    out = g.walk(day(1), day(1))
    assert _intel(g.state).raised == ()
    assert f"needs {detect.CODE_COST} points of output" in _words(out)


def test_a_refused_form_and_a_refused_writing_send_the_same_words() -> None:
    texts = []
    for by in BY:
        g = game()
        give(g, by, "codebreaking")
        out = g.walk(day(1), day(1))
        texts.append([d.document.body for d in _papers(out) if d.document.title == apply.REFUSED])
    assert texts[0] and texts[0] == texts[1]


def test_without_reports_an_investigate_lands_an_inquiry_as_before() -> None:
    rules = tuple(r for r in game().state.rules if r is not Rule.REPORTS)
    plain = Investigate(target=entity("sudland"), question="strength")
    outs = []
    for w in (world(), world(rules=[r.value for r in rules], intelligence=())):
        g = game(w)
        write(g, plain, day(1))
        outs.append([d.document.title for d in _papers(g.walk(day(1), day(3)))])
    assert any(t.startswith("Inquiry into Sudland") for t in outs[0])
    assert outs[0] == outs[1]


def test_an_allocate_without_intel_moves_nothing_from_the_pools() -> None:
    g = game()
    with_output(g, 25)
    write(g, Allocate(recipient=entity("sudland"), what="grain", amount=5, unit="tons"), day(1))
    g.walk(day(1), day(1))
    assert g.state.economy.pools[entity(NORRA)].output == 25
    assert _intel(g.state).raised == ()


# --- two orders in one day see each other ------------------------------------------------


def test_two_fundings_landing_on_one_day_raise_the_level_twice() -> None:
    g = game()
    with_output(g, 25)
    write(g, funding(), day(1), 1)
    write(g, funding(), day(1), 2)
    g.walk(day(1), day(1))
    assert _intel(g.state).raised == (day(1 + detect.CODE_DAYS),) * 2
    assert g.state.economy.pools[entity(NORRA)].output == 25 - 2 * detect.CODE_COST


def test_four_agents_on_one_day_place_the_most_a_nation_may_have() -> None:
    g = game()
    for n in range(1, detect.AGENTS_MAX + 2):
        write(g, agent("isle" if n % 2 else "sudland_coast"), day(1), n)
    out = g.walk(day(1), day(1))
    assert len(_intel(g.state).agents) == detect.AGENTS_MAX
    assert f"at most {detect.AGENTS_MAX} agents" in _words(out)


# --- invariant 5: the aide's limits hold where the effect lands --------------------------


def test_an_agent_the_aide_filed_in_writing_is_not_placed() -> None:
    g = game()
    oid = write(g, agent(), day(1))
    by_aide(g, oid)
    g.walk(day(1), day(1))
    assert entity(NORRA) not in g.state.intelligence or not _intel(g.state).agents


def test_an_agent_the_aide_filed_by_form_is_not_placed() -> None:
    g = game()
    oid = form(g, "place_agent", day(1), area="sudland_coast")
    by_aide(g, oid)
    g.walk(day(1), day(1))
    assert not _intel(g.state).agents


def test_a_concealment_the_aide_filed_lands_its_engagement_but_conceals_nothing() -> None:
    g = game()
    oid = write(g, conceal(True), day(1))
    by_aide(g, oid)
    g.walk(day(1), day(1))
    levy = g.state.features[fid("norra_levy")]
    assert levy.concealed is False and levy.engagement is Engagement.DEFEND


def test_a_recon_flight_the_aide_filed_still_flies() -> None:
    g = game()
    oid = write(g, recon(), day(1))
    by_aide(g, oid)
    g.walk(day(1), day(1))
    assert g.state.features[fid("norra_kites")].recon == entity("sudland_coast")


# --- Rule 4: each call is one line, and no chance or limit is named outside detect --------


LIMITS = sorted(
    name
    for name, value in vars(detect).items()
    if re.fullmatch(r"[A-Z][A-Z_]+", name) and isinstance(value, int | dict)
)


@pytest.mark.parametrize(
    "path",
    [
        SRC / "apply.py",
        SRC / "resolvers" / "intel.py",
        SRC / "land" / "investigate.py",
        SRC / "land" / "allocate.py",
    ],
    ids=lambda p: p.name,
)
def test_no_landing_site_names_a_chance_or_a_limit(path: Path) -> None:
    text = path.read_text()
    assert LIMITS and not [n for n in LIMITS if re.search(rf"\b{n}\b", text)]


def test_each_rule_function_is_called_on_one_line() -> None:
    calls = {"order_recon", "place_agent", "fund_codebreaking", "set_concealed"}
    seen: dict[str, int] = {}
    for path in (SRC / "apply.py", SRC / "land" / "investigate.py", SRC / "land" / "allocate.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in calls:
                    assert node.lineno == node.end_lineno, f"{path.name}:{node.lineno}"
                    seen[node.func.attr] = seen.get(node.func.attr, 0) + 1
    assert seen == dict.fromkeys(calls, 1)


def test_the_form_reaches_the_same_landing_as_a_written_order() -> None:
    text = (SRC / "resolvers" / "intel.py").read_text()
    assert "apply.land_effect(" in text and "detect." not in text
    assert set(apply.__all__) >= {"land_effect"}


# --- Accept: twin games through the web room, one by form and one in writing --------------


class Reader:
    """The aide reading a written order into ``asks``; every other call to ``table``."""

    def __init__(self, table: Transport, asks: list[dict[str, Any]]) -> None:
        self.table = table
        self.asks = asks

    def call(self, request: Request) -> Reply:
        if request.call_class == orders_reader.CALL_CLASS:
            return Reply({"asks": self.asks, "reason": ""}, request.model, 10, 10, 0, 0.0)
        return self.table.call(request)


def seeded(game: Realism) -> None:
    """Norra's output pool holds 25 points when play opens, so a funding is paid."""
    store = game.web.app.open()
    try:
        em = Emitter(store, store_state(store, game.campaign), cmp.versions())
        nation = EntityId(game.ids[NORRA])
        em.commit([em.event(ev.EconomySet(polity=nation, pools=Pools(output=25), on=START))])
    finally:
        store.close()


def twin(web: Web, handle: str) -> tuple[Realism, Client]:  # noqa: F811
    game = Realism(web, world=str(WORLD))
    ada = game.seat(handle, "ilse")
    make_host(game, ada)
    begin(game)
    seeded(game)
    return game, ada


ORDERS: dict[str, tuple[str, dict[str, str], str, dict[str, Any]]] = {
    # name: (form, its params, the written order, the effect the aide reads it as)
    "recon": (
        "fly_recon",
        {"piece": "norra_kites", "area": "sudland_coast"},
        "Fly the kites over the Sudland Coast",
        {
            "kind": "investigate",
            "target": "sudland_coast",
            "question": "recon",
            "intel": "recon",
            "flier": "norra_kites",
        },
    ),
    "patrol": (
        "patrol",
        {"piece": "norra_pickets"},
        "Put the pickets on patrol",
        {"kind": "move_force", "force": "norra_pickets", "posture": "patrol"},
    ),
    "agent": (
        "place_agent",
        {"area": "sudland_coast"},
        "Place an agent on the Sudland Coast",
        {"kind": "investigate", "target": "sudland_coast", "question": "agent", "intel": "agent"},
    ),
    "codebreaking": (
        "fund_codebreaking",
        {},
        "Fund the codebreakers",
        {
            "kind": "allocate",
            "recipient": NORRA,
            "what": "codebreaking",
            "amount": 0,
            "unit": "points",
            "intel": "codebreaking",
        },
    ),
    "conceal": (
        "conceal",
        {"piece": "norra_levy", "concealed": "yes"},
        "Hide the levy",
        {
            "kind": "engagement",
            "force": "norra_levy",
            "zone": "",
            "rule": "defend",
            "concealed": True,
        },
    ),
}
KEYED = {"target", "flier", "force", "recipient"}
STRENGTH = re.compile(r"strength \d+ to \d+")
"""A report's strength range is drawn per campaign; the twins compare all else."""
SEEN = START + timedelta(days=4)
"""Each game is played to this day: the flight's search (day 2) and its report are past."""


def by_form(game: Realism, ada: Client, name: str) -> None:
    lever, params, _, _ = ORDERS[name]
    status, out = post(ada, "lever", lever=lever, params={"intel": name, **params})
    assert status == 200 and not out.get("refused"), out


def in_writing(game: Realism, ada: Client, name: str) -> None:
    _, _, text, effect = ORDERS[name]
    keyed = {k: game.ids[v] if k in KEYED else v for k, v in effect.items()}
    game.web.game.transport = Reader(game.web.game.transport, [{"ask": text, "effect": keyed}])
    status, out = post(ada, "order", to="Ansel Dorn", channel="", text=text)
    assert status == 200 and not out["refused"], out
    status, out = post(ada, "file")
    assert status == 200 and not out["refused"], out


def outcome(game: Realism, ada: Client) -> dict[str, Any]:
    """What came of the orders, by name: Norra's pieces, agents, codebreaking and pools,
    the reports it made, and the lines of the papers Ansel Dorn sent the seat."""
    state = state_of(game)
    name = {v: k for k, v in game.ids.items()}
    nation = EntityId(game.ids[NORRA])
    pieces = {
        name[f]: (
            p.posture,
            p.concealed,
            name.get(str(p.recon)),
            p.recon_on,
        )
        for f, p in state.features.items()
        if name.get(f, "").startswith("norra_")
    }
    intel = state.intelligence[nation]
    made = sorted(
        (e.payload.report.source, name.get(str(e.payload.report.area)), e.payload.report.seen)
        for e in log_of(game)
        if isinstance(e.payload, ev.ReportMade) and e.payload.nation == nation
    )
    rows = [
        d
        for d in realism_of(ada)["documents"]["documents"]
        if d["author"] == "Ansel Dorn"
        and not d["answer"]
        and not d["ack"]
        and "your order" not in d["title"]
    ]
    papers = sorted((d["title"], _body(ada, d["id"])) for d in rows)
    return {
        "date": state.in_world_date,
        "pieces": pieces,
        "agents": [(name[a.area], a.since) for a in intel.agents],
        "raised": intel.raised,
        "output": state.economy.pools[nation].output,
        "made": made,
        "papers": papers,
    }


def _body(ada: Client, doc_id: str) -> tuple[tuple[str, str], ...]:
    status, page = post(ada, "read", doc_id=doc_id)
    assert status == 200, page
    return tuple((f["label"], STRENGTH.sub("strength", str(f["value"]))) for f in page["body"])


def digest(out: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(out, default=str, sort_keys=True).encode()).hexdigest()


def played(
    web: Web,  # noqa: F811
    handle: str,
    give: Callable[[Realism, Client, str], None],
) -> dict[str, Any]:
    game, ada = twin(web, handle)
    for name in ORDERS:
        give(game, ada, name)
    while (today := state_of(game).in_world_date) is not None and today < SEEN:
        status, out = post(ada, "commit")
        assert status == 200 and not out["refused"], out
    return outcome(game, ada)


def test_each_order_by_form_and_in_writing_comes_to_the_same(web: Web) -> None:  # noqa: F811
    form_game = played(web, "ada", by_form)
    written = played(web, "bea", in_writing)
    assert form_game == written
    assert digest(form_game) == digest(written)
    pieces = form_game["pieces"]
    assert pieces["norra_kites"][2:] == ("sudland_coast", START + timedelta(days=2))
    assert pieces["norra_pickets"][0] is Posture.PATROL
    assert pieces["norra_levy"][1] is True
    assert form_game["agents"] == [("sudland_coast", START + timedelta(days=1 + detect.AGENT_DAYS))]
    assert form_game["raised"] == (START + timedelta(days=1 + detect.CODE_DAYS),)
    assert form_game["output"] == 25 - detect.CODE_COST
    assert {(s, a) for s, a, _ in form_game["made"]} >= {
        (detect.Source.AIR, "sudland_coast"),
        (detect.Source.PATROL, "open_sea"),
    }
    titles = [t for t, _ in form_game["papers"]]
    assert any(t.startswith("Air reconnaissance report") for t in titles), titles
    assert any(t.startswith("Patrol report") for t in titles), titles


# --- the desk names each form's rule and, for an intel form, which order it gives ---------


FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"


def test_the_desk_names_each_levers_rule_and_intel_order(web: Web) -> None:  # noqa: F811
    _, ada = twin(web, "cyd")
    levers = {x["name"]: (x["rule"], x["intel"]) for x in realism_of(ada)["desk"]["levers"]}
    assert levers == {
        "fly_recon": ("intel", "recon"),
        "patrol": ("intel", "patrol"),
        "place_agent": ("intel", "agent"),
        "fund_codebreaking": ("intel", "codebreaking"),
        "conceal": ("intel", "conceal"),
    }


def test_the_fixture_desk_has_the_api_shape_and_one_form_of_each_order() -> None:
    from revisionist.engine.web.realism_api import LeverLine

    levers = json.loads(FIXTURE.read_text())["desk"]["levers"]
    for lever in levers:
        assert set(lever) == set(LeverLine.__annotations__), lever["name"]
    forms = sorted(x["intel"] for x in levers if x["rule"] == "intel")
    assert forms == sorted(f.value for f in intel.Form)
    assert all(x["intel"] is None for x in levers if x["rule"] != "intel")
