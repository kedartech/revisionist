"""Embargo and trade orders (EMB).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories``,
``holders``, ``economy`` and ``fuel`` on, Norra and Sudland at peace, and a third power,
Ost, that no seat plays. Pitch plays the ``fuel`` role. Two lines run into Sudland:
Norra's, 3 barrels a month, and Ost's, 2. Each leader's card holds a trade form under the
rule name ``trade``: it names a line and whether to embargo or restore it. The game starts
on 2 April 1900, so day 29 is 1 May and day 60 is 1 June.

Worked example (rules 1 and 3): Sudland starts with no pitch. Norra's embargo of its line
leaves its last step on day 10 and lands on day 11. On 1 May Sudland gains only Ost's 2
barrels, and on 1 June 2 more: 4 in all, where the open line would have made 10. An
embargo that leaves its last step on 1 May lands on 2 May, after May's payment: May's 5
barrels stay paid, and from 1 June the line pays nothing.
"""

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, derived_id
from revisionist.core.realism import economy, resolvers
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import trade as orders
from revisionist.core.realism.war import NewsTopic
from revisionist.core.visibility import Visibility
from revisionist.core.world import WorldFile
from tests.test_adjacency_moves import START, Logged, World, day, entity, seat
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_territory_model import CAMPAIGN, refused

NORRA, SUDLAND, OST = "norra", "sudland", "ost"
NORRA_LINE, OST_LINE = "norra_pitch", "ost_pitch"
MAY_1, JUNE_1 = day(29), day(60)


def at_peace(w: World) -> None:
    w["rules"] = ["territories", "holders", "economy", "fuel"]
    w["wars"] = []
    w["entities"].append({"key": OST, "kind": "polity", "name": "Ost"})
    w["fuel_stocks"] = [{"polity": p, "amount": 0, "source": "toy"} for p in (NORRA, SUDLAND)]


def lines(norra_cut: bool = False) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["trade_lines"] = [
            {
                "key": NORRA_LINE,
                "exporter": NORRA,
                "importer": SUDLAND,
                "resource": "pitch",
                "amount": 3,
                "cut": norra_cut,
                "source": "toy",
            },
            {
                "key": OST_LINE,
                "exporter": OST,
                "importer": SUDLAND,
                "resource": "pitch",
                "amount": 2,
                "source": "toy",
            },
        ]

    return change


def forms(w: World) -> None:
    """A trade form on each leader's card, by the rule name ``trade``."""
    w["pipelines"] = [
        {
            "key": "board_of_trade",
            "name": "The board of trade",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        }
    ]
    params = [
        {"name": "line", "kind": "enum", "choices": [NORRA_LINE, OST_LINE]},
        {"name": "action", "kind": "enum", "choices": ["embargo", "restore"]},
    ]
    for card in w["cards"]:
        card["pipelines"] = ["board_of_trade"]
        card["levers"] = [
            {"name": "trade", "pipeline": "board_of_trade", "resolver": "trade", "params": params}
        ]


Change = Callable[[World], None]


def toy(tmp: Path, *changes: Change) -> WorldFile:
    return territories_toy(tmp, at_peace, *changes)


def game(tmp: Path, *changes: Change, norra_cut: bool = False) -> Logged:
    return Logged(toy(tmp, lines(norra_cut), forms, *changes), "ilse", "tomas")


def enact(
    g: Logged,
    by: str = "ilse",
    line: str = NORRA_LINE,
    action: str = "embargo",
    on: date = START,
    n: int = 1,
) -> Order:
    """A trade order on ``line`` that leaves its last step on ``on``."""
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "emb-order", by, n)),
        issuer=seat(by),
        lever="trade",
        pipeline=next(
            p.pipeline_id for p in g.state.pipelines.values() if p.name == "The board of trade"
        ),
        params={"line": line, "action": action},
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
    """``trade.on_day`` and then ``economy.walk`` for each day, folded in turn: the order
    the day walk runs them in."""
    out: list[ev.Payload] = []
    for n in range(first, last + 1):
        landed = resolvers.apply_changes(g.state, orders.on_day(g.state, day(n)))
        g.add(landed)
        paid = economy.walk(g.state, day(n))
        g.add(paid)
        out += [*landed, *paid]
    return out


def stock(g: Logged, polity: str = SUDLAND) -> float:
    return economy.stock(g.state, entity(polity))


def is_cut(g: Logged, line: str = NORRA_LINE) -> bool:
    return g.state.economy.lines[line].cut


def sets(out: Sequence[ev.Payload]) -> list[ev.TradeSet]:
    return [p for p in out if isinstance(p, ev.TradeSet)]


def news(out: Sequence[ev.Payload]) -> list[ev.NewsReported]:
    return [p for p in out if isinstance(p, ev.NewsReported)]


def papers(out: Sequence[ev.Payload]) -> list[ev.DocumentIssued]:
    return [p for p in out if isinstance(p, ev.DocumentIssued)]


def test_trade_is_registered_for_orders_and_the_day_walk(tmp_path: Path) -> None:
    assert resolvers.ON_ORDER["trade"] is orders.resolve
    assert resolvers.ON_DAY["trade"] is orders.on_day
    g = game(tmp_path)  # a world whose form names ``trade`` now compiles
    assert g.state.cards


# --- Rule 1: an embargo cuts the issuer's own line; a restore reopens it -----------------


def test_an_embargo_cuts_the_issuers_line_the_day_after_it_is_enacted(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g)
    assert walk_days(g, 0, 0) == [] and not is_cut(g)
    (landed,) = sets(walk_days(g, 1, 1))
    assert landed.line.key == NORRA_LINE and landed.line.cut and landed.on == day(1)
    assert is_cut(g) and not is_cut(g, OST_LINE)


def test_a_restore_reopens_the_issuers_line(tmp_path: Path) -> None:
    g = game(tmp_path, norra_cut=True)
    enact(g, action="restore")
    (landed,) = sets(walk_days(g, 0, 3))
    assert not landed.line.cut and not is_cut(g)


def test_the_worked_example(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, on=day(10))
    walk_days(g, 0, 60)
    assert stock(g) == 4
    open_ = game(tmp_path)
    walk_days(open_, 0, 60)
    assert stock(open_) == 10


# --- Rule 2: one public news item and one paper to the nation at the other end ----------


def test_an_embargo_lands_one_public_news_item(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g)
    before = len(g.log)
    out = g.walk(day(1), day(1))
    items = [e for e in out if isinstance(e.payload, ev.NewsReported)]
    assert len(items) == 1 and len(g.log) > before
    (item,) = items
    assert item.scope.visibility is Visibility.PUBLIC
    assert isinstance(item.payload, ev.NewsReported)
    told = item.payload.news
    assert told.topic is NewsTopic.EVENT
    assert (told.subject, told.obj) == (entity(NORRA), entity(SUDLAND))
    assert told.headline == "Norra embargoes pitch to Sudland"
    assert [f.label for f in told.facts] == ["By", "To", "Carries", "Date"]  # never the amount


def test_an_embargo_lands_one_paper_to_the_seats_of_the_nation_it_hits(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g)
    out = g.walk(day(1), day(1))
    docs = [e for e in out if isinstance(e.payload, ev.DocumentIssued)]
    assert len(docs) == 1
    (doc,) = docs
    assert isinstance(doc.payload, ev.DocumentIssued)
    paper = doc.payload.document
    assert paper.scope.visibility is Visibility.RESTRICTED
    assert paper.scope.known_by == frozenset({seat("tomas")})
    assert doc.scope == paper.scope
    assert paper.title == "Norra cuts its pitch line"
    body = {f.label: f.value for f in paper.body}
    assert body["A month"] == "3 barrels"
    assert body["Pays"] == "Nothing from 1 May 1900"


def test_a_restore_lands_its_own_news_item_and_paper(tmp_path: Path) -> None:
    g = game(tmp_path, norra_cut=True)
    enact(g, action="restore")
    out = walk_days(g, 1, 1)
    assert [n.news.headline for n in news(out)] == ["Norra reopens pitch to Sudland"]
    (paper,) = papers(out)
    assert paper.document.scope.known_by == frozenset({seat("tomas")})
    assert {f.label: f.value for f in paper.document.body}["Pays"] == "Again from 1 May 1900"


def test_the_paper_reads_the_same_whether_the_nation_it_hits_is_present_or_away(
    tmp_path: Path,
) -> None:
    """Away: Tomas files nothing. Present: he files a trade order of his own the same day
    (refused, since the line is not his). Norra's paper to him is the same."""
    seen = []
    for tomas_is in ("away", "present"):
        g = game(tmp_path)
        enact(g)
        if tomas_is == "present":
            enact(g, by="tomas", n=2)
        out = walk_days(g, 1, 1)
        seen.append([p for p in papers(out) if p.document.author == entity(NORRA)])
    assert seen[0] and seen[0] == seen[1]


# --- Rule 3: a cut line pays nothing from the next first of the month --------------------


def test_a_line_cut_before_the_first_pays_nothing_on_it(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, on=day(27))  # lands on day 28, 30 April
    walk_days(g, 0, 29)
    assert stock(g) == 2


def test_a_cut_on_the_first_leaves_that_months_payment_paid(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, on=MAY_1)
    out = walk_days(g, 0, 60)
    (landed,) = sets(out)
    assert landed.on == day(30)
    assert stock(g) == 5 + 2
    (paper,) = papers(out)
    assert {f.label: f.value for f in paper.document.body}["Pays"] == "Nothing from 1 June 1900"


def test_the_whole_day_walk_cuts_from_the_next_first(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, on=day(10))
    g.walk(day(1), JUNE_1)
    assert stock(g) == 4


# --- Rule 4: no nation can cut a line it is not the ``from`` of --------------------------


def test_a_third_nation_cannot_cut_a_line(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, by="ilse", line=OST_LINE)
    out = walk_days(g, 0, 29)
    assert sets(out) == [] and news(out) == [] and not is_cut(g, OST_LINE)
    (report,) = papers(out)
    assert report.document.scope.known_by == frozenset({seat("ilse")})
    why = {f.label: f.value for f in report.document.body}["Why"]
    assert why == orders.NOT_YOURS and "Ost" not in why  # nothing of a line it is not party to
    assert stock(g) == 5


def test_the_nation_at_the_far_end_cannot_cut_a_line(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, by="tomas")
    out = walk_days(g, 0, 29)
    assert sets(out) == [] and news(out) == [] and not is_cut(g)
    (report,) = papers(out)
    assert report.document.scope.known_by == frozenset({seat("tomas")})
    assert stock(g) == 5


def test_a_line_that_does_not_exist_is_reported_in_the_same_words(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, line="no_such_line")
    (report,) = papers(walk_days(g, 0, 3))
    assert {f.label: f.value for f in report.document.body}["Why"] == orders.NOT_YOURS


def test_nor_can_it_reopen_one(tmp_path: Path) -> None:
    g = game(tmp_path, norra_cut=True)
    enact(g, by="tomas", action="restore")
    assert sets(walk_days(g, 0, 29)) == [] and is_cut(g)


# --- What changes nothing ---------------------------------------------------------------


def test_an_embargo_of_a_cut_line_lands_only_a_report(tmp_path: Path) -> None:
    g = game(tmp_path, norra_cut=True)
    enact(g)
    out = walk_days(g, 0, 3)
    assert sets(out) == [] and news(out) == []
    (report,) = papers(out)
    assert {f.label: f.value for f in report.document.body}["Why"] == "The line is already cut"


def test_two_orders_landing_on_one_day_each_see_the_one_before(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g, n=1)
    enact(g, n=2)
    out = walk_days(g, 0, 3)
    assert len(sets(out)) == 1 and len(news(out)) == 1
    assert len(papers(out)) == 2  # the paper to Sudland and the report of the second


def test_each_order_lands_once(tmp_path: Path) -> None:
    g = game(tmp_path)
    enact(g)
    enact(g, action="restore", on=day(5), n=2)
    out = walk_days(g, 0, 40)
    assert [s.line.cut for s in sets(out)] == [True, False]
    assert not is_cut(g) and stock(g) == 5


def test_nothing_lands_with_fuel_off(tmp_path: Path) -> None:
    def no_fuel(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy"]
        w.pop("fuel_stocks", None)

    g = Logged(toy(tmp_path, no_fuel, forms), "ilse", "tomas")
    enact(g)
    out = resolvers.apply_changes(g.state, orders.on_day(g.state, day(1)))
    assert sets(out) == [] and news(out) == []


def test_a_form_naming_trade_compiles_only_with_the_function_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(resolvers.ON_ORDER, "trade")
    assert any("has no rule yet: trade" in p for p in refused(toy(tmp_path, lines(), forms)))
