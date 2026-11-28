"""Raising a new piece (RNC): with ``raising`` on, an enacted form that names a kind and a
place raises a new piece of that kind there, the kind's lead days later, from the economy's
two pools.

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories``,
``holders``, ``economy`` and ``raising`` on, and the raising site of
``tests/test_piece_kinds.py``: the Hillfort, in the Norra Hills, is an air base of Norra's,
and the chancellor's card holds a form ``raise_piece`` that names a kind and a place. The
fire kite costs 10 output and 1 manpower and takes 30 days. A test gives a nation its pools
directly, so the first-of-the-month payment does not decide the result.

Worked example (rules 1, 3 and 5): Norra, with 50 output and 5 manpower, enacts an order to
raise fire kites at the Hillfort on day 0. Nothing changes until day 30: that day the pools
fall to 40 and 4, and the Fire Kites 1 stand at the Hillfort at strength 1, under Norra's
command.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path

from revisionist.core import events as ev
from revisionist.core.fold import state_hash
from revisionist.core.ids import EntityId, FeatureId, OrderId, PipelineId, derived_id
from revisionist.core.realism import actors, answering, resolvers
from revisionist.core.realism.answer import Answer, AnswerAct, AnswerWhen
from revisionist.core.realism.document import DocumentView
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import production
from revisionist.core.realism.war_rules import order_refusal
from revisionist.core.visibility import private_to
from revisionist.core.world import WorldFile
from tests.test_adjacency_moves import START, Logged, World, entity, seat, set_feature
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_piece_kinds import RAISE_RULES, commanded, raising_site
from tests.test_supply import hub, no_port
from tests.test_territory_model import CAMPAIGN

Change = Callable[[World], None]
NORRA, SUDLAND = "norra", "sudland"
KITE, LEVY = "fire_kite", "levy"
RICH = Pools(output=50, manpower=5)


def on(w: World) -> None:
    raising_site(w)
    w["rules"] = list(RAISE_RULES)


def off(w: World) -> None:
    raising_site(w)
    w["rules"] = [r for r in RAISE_RULES if r != "raising"]


def with_supply(w: World) -> None:
    """The supply rule on, with a railway hub in the Norra Plain and on the Sudland coast."""
    w["rules"] = [*w["rules"], "supply"]
    w["resources"].append({"key": "track", "name": "Railway", "unit": "miles", "role": "supply"})
    for t in w["territories"]:
        if t["key"] in ("norra_plain", "sudland_coast"):
            t["yields"] = {**t.get("yields", {}), "track": 1}


def cut_off(w: World) -> None:
    """Norra holds no railway hub and no port, so nothing of Norra's on land is supplied."""
    hub("norra_plain", False)(w)
    no_port(w)


def base(key: str, *domains: str, sides: Sequence[str] = (NORRA,)) -> Change:
    """A base at ``key`` (a place already in the world) for ``sides`` and ``domains``."""

    def change(w: World) -> None:
        (place,) = [e for e in w["entities"] if e["key"] == key]
        place["base"] = {"sides": list(sides), "domains": list(domains)}
        (area,) = [t for t in w["territories"] if t["key"] == place["within"]]
        if key not in area.get("sites", []):
            area["sites"] = [*area.get("sites", []), key]

    return change


def levies_raised(w: World) -> None:
    """The levy may be raised at a land base, 10 output and 1 manpower, in 20 days; Norrhavn
    is a land base of Norra's, and the chancellor's form may name it."""
    (levy,) = [k for k in w["piece_kinds"] if k["key"] == LEVY]
    levy.update({"cost": {"output": 10, "manpower": 1}, "lead_days": 20, "raised_at": "land"})
    base("norrhavn", "land")(w)
    choices("ilse", kinds=[KITE, LEVY], places=["hillfort", "norrhavn"])(w)


def choices(person: str, kinds: Sequence[str], places: Sequence[str]) -> Change:
    def change(w: World) -> None:
        (card,) = [c for c in w["cards"] if c["person"] == person]
        (lever,) = [lv for lv in card["levers"] if lv["name"] == "raise_piece"]
        lever["params"] = [
            {"name": "kind", "kind": "enum", "choices": list(kinds)},
            {"name": "place", "kind": "enum", "choices": list(places)},
        ]

    return change


def sudland_raises(w: World) -> None:
    """Sudby is an air base of Sudland's, and the premier holds the same form for it."""
    base("sudby", "air", sides=[SUDLAND])(w)
    (card,) = [c for c in w["cards"] if c["person"] == "tomas"]
    w["pipelines"].append(
        {
            "key": "sud_raise_order",
            "name": "A Sudland order to raise",
            "source": "toy",
            "steps": [{"person": "tomas", "kind": "decision", "days": 1}],
        }
    )
    card["pipelines"] = [*card.get("pipelines", []), "sud_raise_order"]
    card["levers"] = [
        *card.get("levers", []),
        {
            "name": "raise_piece",
            "pipeline": "sud_raise_order",
            "resolver": "economy",
            "params": [
                {"name": "kind", "kind": "enum", "choices": [KITE]},
                {"name": "place", "kind": "enum", "choices": ["sudby"]},
            ],
        },
    ]


def world(tmp: Path, *changes: Change, rules: Change = on) -> WorldFile:
    tmp.mkdir(parents=True, exist_ok=True)
    return territories_toy(tmp, rules, *changes)


def game(
    tmp: Path,
    *changes: Change,
    rules: Change = on,
    pools: dict[str, Pools] | None = None,
    people: Sequence[str] = ("ilse", "tomas"),
) -> Logged:
    g = Logged(world(tmp, *changes, rules=rules), *people)
    given = {NORRA: RICH} if pools is None else pools
    g.add([ev.EconomySet(polity=entity(k), pools=p, on=START) for k, p in sorted(given.items())])
    return g


def day(n: int) -> date:
    return START + timedelta(days=n)


def pipeline(g: Logged, by: str) -> PipelineId:
    card = g.state.cards[entity("tomas" if by == "tomas" else "ilse")]
    (lever,) = [lv for lv in card.levers if lv.name == "raise_piece"]
    return lever.pipeline


def enact(
    g: Logged,
    by: str = "ilse",
    on: date = START,
    n: int = 1,
    kind: str = KITE,
    place: str = "hillfort",
) -> Order:
    """An order to raise ``kind`` at ``place``, enacted on ``on``."""
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "rnc-order", by, n)),
        issuer=seat(by),
        lever="raise_piece",
        pipeline=pipeline(g, by),
        params={"kind": kind, "place": place},
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
    """``production.economy_day`` for each day from ``first`` to ``last``, folded in turn."""
    out: list[ev.Payload] = []
    for n in range(first, last + 1):
        changes = resolvers.apply_changes(g.state, production.economy_day(g.state, day(n)))
        g.add(changes)
        out += changes
    return out


def raised(g: Logged, kind: str = KITE) -> list[Feature]:
    """The pieces of ``kind`` that entered after the world compiled, by name."""
    return sorted(
        (f for f in g.state.features.values() if f.piece == kind and f.as_of > START),
        key=lambda f: f.name,
    )


def pools(g: Logged, polity: str = NORRA) -> Pools:
    return g.state.economy.pools.get(entity(polity), Pools())


def papers(out: Sequence[ev.Payload]) -> list[DocumentView]:
    return [p.document for p in out if isinstance(p, ev.DocumentIssued)]


def body(doc: DocumentView) -> dict[str, str]:
    return {f.label: str(f.value) for f in doc.body}


def check(g: Logged, by: str = "ilse", kind: str = KITE, place: str = "hillfort") -> str:
    return order_refusal(g.state, seat(by), "raise_piece", {"kind": kind, "place": place})


# --- Rule 1: the switch, the kind and the place --------------------------------------


def test_an_order_to_raise_brings_a_new_piece_of_its_kind_to_its_place(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g)
    walk_days(g, 1, 29)
    assert raised(g) == []
    walk_days(g, 30, 30)
    (new,) = raised(g)
    assert (new.piece, new.side, new.places, new.tier, new.as_of) == (
        KITE,
        entity(NORRA),
        (entity("hillfort"),),
        1,
        day(30),
    )
    assert new.feature_id == FeatureId(derived_id(CAMPAIGN, "raised", new_order_id()))


def new_order_id() -> OrderId:
    return OrderId(derived_id(CAMPAIGN, "rnc-order", "ilse", 1))


def test_with_raising_off_the_same_order_raises_nothing_and_spends_nothing(tmp_path: Path) -> None:
    worlds = {}
    for name, rules in (("off", off), ("on", on)):
        g = game(tmp_path / name, rules=rules)
        enact(g)
        walk_days(g, 1, 30)
        worlds[name] = g
    assert raised(worlds["off"]) == [] and pools(worlds["off"]) == RICH
    assert len(raised(worlds["on"])) == 1 and pools(worlds["on"]) == Pools(output=40, manpower=4)


def test_with_no_order_to_raise_the_switch_changes_no_day(tmp_path: Path) -> None:
    days = {}
    for name, rules in (("off", off), ("on", on)):
        g = game(tmp_path / name, rules=rules)
        days[name] = [production.economy_day(g.state, day(n)) for n in range(0, 40)]
    assert days["off"] == days["on"]


def by_production(w: World) -> None:
    """The form to raise goes by the rule name ``production``, decided by Sudland's premier."""
    (ilse,) = [c for c in w["cards"] if c["person"] == "ilse"]
    (lever,) = [lv for lv in ilse["levers"] if lv["name"] == "raise_piece"]
    lever["resolver"] = "production"
    (step,) = next(p for p in w["pipelines"] if p["key"] == "raise_order")["steps"]
    step["person"] = "tomas"


def test_a_production_form_that_names_a_kind_and_a_place_raises_and_asks_nothing(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, by_production)
    order = enact(g)
    assert production.resolve(g.state, order) == ()
    out = walk_days(g, 1, production.AID_LEAD_DAYS)
    assert [p.title for p in papers(out)] == ["Raised: Fire Kites 1"]
    assert pools(g) == Pools(output=40, manpower=4)


def test_a_strength_step_for_a_force_that_exists_is_built_as_before(tmp_path: Path) -> None:
    def build_form(w: World) -> None:
        (ilse,) = [c for c in w["cards"] if c["person"] == "ilse"]
        force = {"name": "force", "kind": "enum", "choices": ["norra_levy"]}
        ilse["levers"].append(
            {"name": "build", "pipeline": "raise_order", "resolver": "economy", "params": [force]}
        )

    hashes = []
    for name, rules in (("off", off), ("on", on)):
        g = game(tmp_path / name, build_form, set_feature("norra_levy", tier=2), rules=rules)
        order = Order(
            order_id=OrderId(derived_id(CAMPAIGN, "build", 1)),
            issuer=seat("ilse"),
            lever="build",
            pipeline=pipeline(g, "ilse"),
            params={"force": "norra_levy"},
            filed=START,
        )
        g.add(
            [
                ev.OrderDrafted(order=order),
                ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
            ]
        )
        walk_days(g, 1, production.LEAD_DAYS)
        assert g.state.features[FeatureId(entity("norra_levy"))].tier == 3
        hashes.append(state_hash(g.state.model_copy(update={"rules": frozenset()})))
    assert hashes[0] == hashes[1]


# --- Rule 2: the place ------------------------------------------------------------


def test_a_place_with_no_base_for_the_kinds_domain_raises_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, base("hillfort", "land"))
    assert check(g) == production.NO_BASE
    enact(g)
    out = walk_days(g, 1, 30)
    assert raised(g) == [] and pools(g) == RICH
    (paper,) = papers(out)
    assert body(paper)["Why"] == production.NO_BASE


def test_a_base_of_another_nation_is_not_the_nations_own(tmp_path: Path) -> None:
    g = game(tmp_path, base("hillfort", "air", sides=[SUDLAND]))
    assert check(g) == production.NOT_YOURS
    enact(g)
    walk_days(g, 1, 30)
    assert raised(g) == [] and pools(g) == RICH


def test_a_place_lost_before_the_day_raises_nothing_and_spends_nothing(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert check(g) == ""
    enact(g)
    walk_days(g, 1, 10)
    hills = entity("norra_hills")
    g.add([ev.AreaHeld(area=hills, holder=entity(SUDLAND), was=entity(NORRA), on=day(11))])
    assert check(g) == production.NOT_YOURS
    out = walk_days(g, 11, 30)
    assert raised(g) == [] and pools(g) == RICH
    (paper,) = papers(out)
    assert body(paper)["Why"] == production.NOT_YOURS


def test_a_place_out_of_supply_on_the_day_raises_nothing_and_spends_nothing(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, levies_raised, with_supply, cut_off)
    assert check(g, kind=LEVY, place="norrhavn") == production.NO_SUPPLY
    enact(g, kind=LEVY, place="norrhavn")
    out = walk_days(g, 1, 20)
    assert raised(g, LEVY) == [] and pools(g) == RICH
    (paper,) = papers(out)
    assert body(paper)["Why"] == production.NO_SUPPLY


def test_a_place_in_supply_raises(tmp_path: Path) -> None:
    g = game(tmp_path, levies_raised, with_supply)
    assert check(g, kind=LEVY, place="norrhavn") == ""
    enact(g, kind=LEVY, place="norrhavn")
    walk_days(g, 1, 20)
    (new,) = raised(g, LEVY)
    assert new.places == (entity("norrhavn"),)


# --- Rule 3: the day, the pools, the command and the report --------------------------


def test_the_cost_is_spent_on_the_kinds_lead_day(tmp_path: Path) -> None:
    g = game(tmp_path, levies_raised)
    enact(g, kind=LEVY, place="norrhavn")
    walk_days(g, 1, 19)
    assert pools(g) == RICH
    walk_days(g, 20, 20)
    assert pools(g) == Pools(output=40, manpower=4)
    assert len(raised(g, LEVY)) == 1


def test_a_short_pool_raises_nothing_and_spends_nothing(tmp_path: Path) -> None:
    for short in (Pools(output=9, manpower=5), Pools(output=50, manpower=0)):
        g = game(tmp_path / str(short.output), pools={NORRA: short})
        enact(g)
        out = walk_days(g, 1, 30)
        assert raised(g) == [] and pools(g) == short
        (paper,) = papers(out)
        assert "short" in body(paper)["Why"]


def test_the_new_piece_is_commanded_as_its_nations_other_pieces_of_its_domain(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, commanded)
    enact(g)
    walk_days(g, 1, 30)
    (new,) = raised(g)
    authority = {d.name: d.forces for d in g.state.cards[entity("ilse")].authority}
    assert authority["the_wings"] == (FeatureId(entity("norra_kites")), new.feature_id)
    assert new.feature_id not in authority["the_levy"]


def test_the_issuing_seat_gets_one_report_that_day_raised_or_not(tmp_path: Path) -> None:
    for name, given in (("rich", RICH), ("poor", Pools())):
        g = game(tmp_path / name, pools={NORRA: given})
        enact(g)
        out = walk_days(g, 1, 40)
        (paper,) = papers(out)
        assert paper.issued == day(30)
        assert paper.scope == private_to(seat("ilse"))
    rich = papers(walk_days(raise_once(tmp_path / "again"), 30, 30))[0]
    assert body(rich)["At"] == "The Hillfort"
    assert body(rich)["Spent"] == "10 output, 1 manpower"


def raise_once(tmp: Path) -> Logged:
    g = game(tmp)
    enact(g)
    walk_days(g, 1, 29)
    return g


# --- Rule 4: one at a place at a time ----------------------------------------------


def test_a_second_order_for_the_same_place_is_refused_at_the_check(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g)
    assert check(g) == production.BUSY
    walk_days(g, 1, 30)
    assert check(g) == ""


def test_an_order_still_moving_for_the_place_counts_as_a_raising(tmp_path: Path) -> None:
    g = game(tmp_path)
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "moving", 1)),
        issuer=seat("ilse"),
        lever="raise_piece",
        pipeline=pipeline(g, "ilse"),
        params={"kind": KITE, "place": "hillfort"},
        filed=START,
    )
    g.add([ev.OrderDrafted(order=order)])
    assert check(g) == production.BUSY
    g.add([ev.OrderSettled(order_id=order.order_id, status=OrderStatus.REFUSED)])
    assert check(g) == ""


def test_two_orders_for_one_place_raise_one_piece(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, n=1)
    enact(g, n=2)
    out = walk_days(g, 1, 30)
    assert len(raised(g)) == 1
    assert pools(g) == Pools(output=40, manpower=4)
    whys = sorted(body(p).get("Why", "") for p in papers(out))
    assert whys == ["", production.BUSY]


def test_with_raising_off_the_check_refuses_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, base("hillfort", "land"), rules=off)
    assert check(g) == ""


# --- Rule 5: the name -----------------------------------------------------------


def test_the_new_piece_takes_the_kinds_name_and_the_next_number_its_nation_has_not_used(
    tmp_path: Path,
) -> None:
    def third(w: World) -> None:
        w["features"].append(
            {
                "key": "norra_third_kites",
                "kind": "piece",
                "piece": "kite",
                "name": "Fire Kites 3",
                "side": NORRA,
                "places": ["norrhavn"],
                "source": "toy",
            }
        )

    g = game(tmp_path, sudland_raises, pools={NORRA: RICH, SUDLAND: RICH})
    enact(g)
    enact(g, by="tomas", place="sudby")
    walk_days(g, 1, 30)
    enact(g, on=day(31), n=2)
    walk_days(g, 31, 61)
    assert sorted((f.name, f.side) for f in raised(g)) == [
        ("Fire Kites 1", entity(NORRA)),
        ("Fire Kites 1", entity(SUDLAND)),
        ("Fire Kites 2", entity(NORRA)),
    ]
    h = game(tmp_path / "third", third)
    enact(h)
    walk_days(h, 1, 30)
    assert [f.name for f in raised(h)] == ["Fire Kites 4"]


# --- Rule 6: a nation run by code ---------------------------------------------------


def answer_to_raise(place: str) -> Answer:
    return Answer(
        key="raise_kites",
        aim=1,
        when=AnswerWhen(every_days=30, start=START),
        act=AnswerAct(lever="raise_piece", params={"kind": KITE, "place": place}),
        delay_days=0,
        cooldown_days=30,
    )


def coded(tmp: Path) -> Logged:
    g = game(tmp, sudland_raises, people=("ilse",), pools={SUDLAND: RICH})
    g.add(actors.unseated(g.state, [entity("tomas")]))
    return g


def test_a_nation_run_by_code_raises_nothing_its_card_does_not_answer_for(tmp_path: Path) -> None:
    g = coded(tmp_path)
    walk_days(g, 0, 60)
    assert raised(g) == [] and pools(g, SUDLAND) == RICH


def test_a_nation_run_by_code_raises_where_its_cards_answer_says(tmp_path: Path) -> None:
    g = coded(tmp_path)
    tomas = entity("tomas")
    made = answering._make(g.state, tomas, answer_to_raise("sudby"), START)
    (drafted,) = [p for p in made if isinstance(p, ev.OrderDrafted)]
    assert drafted.order.params == {"kind": KITE, "place": "sudby"}
    g.add([drafted, ev.OrderSettled(order_id=drafted.order.order_id, status=OrderStatus.ENACTED)])
    again = answering._make(g.state, tomas, answer_to_raise("sudby"), day(1))
    assert not any(isinstance(p, ev.OrderDrafted) for p in again)
    out = walk_days(g, 1, 30)
    (new,) = raised(g)
    assert (new.side, new.places) == (entity(SUDLAND), (entity("sudby"),))
    assert papers(out) == []


# --- Rule 7: the order due orders are taken in ---------------------------------------


def test_an_earlier_order_spends_first(tmp_path: Path) -> None:
    g = game(tmp_path, levies_raised, pools={NORRA: Pools(output=15, manpower=5)})
    enact(g, n=2, on=day(10), kind=LEVY, place="norrhavn")
    enact(g, n=1, on=START, kind=KITE, place="hillfort")
    walk_days(g, 1, 30)
    assert [f.piece for f in raised(g, KITE) + raised(g, LEVY)] == [KITE]
    assert pools(g) == Pools(output=5, manpower=4)


# --- An enemy where the piece would arrive ------------------------------------------


def enemy_at_the_hillfort(w: World) -> None:
    (levy,) = [f for f in w["features"] if f["key"] == "sudland_levy"]
    levy["places"] = ["hillfort"]


def test_a_piece_raised_where_an_enemy_stands_arrives_at_the_nearest_base_of_its_side(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, base("norrhavn", "air"))
    enact(g)
    g.add(
        [
            ev.FeatureSet(
                feature=g.state.features[FeatureId(entity("sudland_levy"))].model_copy(
                    update={"places": (entity("hillfort"),), "as_of": day(5)}
                )
            )
        ]
    )
    out = walk_days(g, 1, 30)
    (new,) = raised(g)
    assert new.places == (entity("norrhavn"),)
    assert pools(g) == Pools(output=40, manpower=4)
    (paper,) = papers(out)
    words = " ".join([paper.title, *body(paper).values()])
    assert "Norrhavn" in words
    assert "Sudland" not in words and "enemy" not in words.lower() and "Hillfort" not in words


def isle_fort(w: World) -> None:
    """Norra holds the Isle, two steps from the hills, with an air base at its fort."""
    (isle,) = [t for t in w["territories"] if t["key"] == "isle"]
    isle["holder"] = NORRA
    w["entities"].append(
        {"key": "isle_fort", "kind": "location", "name": "The Isle Fort", "at": [40, 180]}
    )
    w["entities"][-1]["within"] = "isle"
    base("isle_fort", "air")(w)


def test_the_arrival_is_the_nearest_base_by_steps(tmp_path: Path) -> None:
    g = game(tmp_path, enemy_at_the_hillfort, isle_fort, base("norrhavn", "air"))
    enact(g)
    walk_days(g, 1, 30)
    (new,) = raised(g)
    assert new.places == (entity("norrhavn"),)


def test_with_no_base_to_arrive_at_nothing_is_raised_and_nothing_spent(tmp_path: Path) -> None:
    g = game(tmp_path, enemy_at_the_hillfort)
    enact(g)
    out = walk_days(g, 1, 30)
    assert raised(g) == [] and pools(g) == RICH
    (paper,) = papers(out)
    assert body(paper)["Why"] == production.NO_ARRIVAL


def test_an_enemy_elsewhere_does_not_move_the_arrival(tmp_path: Path) -> None:
    g = game(tmp_path, base("norrhavn", "air"))
    enact(g)
    walk_days(g, 1, 30)
    (new,) = raised(g)
    assert new.places == (entity("hillfort"),)


def a_neutral_at_the_hillfort(w: World) -> None:
    """Ostmark, at war with nobody, has a levy at the Hillfort."""
    w["entities"].append({"key": "ostmark", "kind": "polity", "name": "Ostmark"})
    w["features"].append(
        {
            "key": "ostmark_levy",
            "kind": "piece",
            "piece": LEVY,
            "name": "The Ostmark Levy",
            "side": "ostmark",
            "places": ["hillfort"],
            "source": "toy",
        }
    )


def test_a_piece_of_a_nation_at_peace_does_not_move_the_arrival(tmp_path: Path) -> None:
    g = game(tmp_path, a_neutral_at_the_hillfort, base("norrhavn", "air"))
    enact(g)
    walk_days(g, 1, 30)
    (new,) = raised(g)
    assert new.places == (entity("hillfort"),)


def test_the_check_and_the_day_name_a_place_by_its_key(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert check(g, place="nowhere") == production.NO_BASE
    assert check(g, kind="levy") == production.NOT_RAISED
    assert EntityId(entity("hillfort")) in {b.place for b in g.state.map.bases}  # type: ignore[union-attr]
