"""Fuel and trade: oil is spent to move, and a trade line can be cut (FUL).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories``,
``holders``, ``economy`` and ``fuel`` on, and a third power, Ost, at peace with both.
Pitch plays the ``fuel`` role; the Sudland Galleys spend 1 barrel a step. The galleys
stand in the Gulf: a step out to the Open Sea (deep) takes 3 days, one back (shallows) 2.
The game starts on 2 April 1900, so day 29 is 1 May and day 60 is 1 June.

Worked example (rules 1 to 4): Sudland starts with 2 barrels, and the Ost line brings it 3
barrels a month. Each month the galleys go out and back: 2 steps, 2 barrels. With the
line open the stock reads 2, 0 after April's sortie, 3 on 1 May, 1 after May's sortie and
4 on 1 June. Cut on day 0, the line pays nothing on 1 May: the April sortie empties the
stock, and the first step of May's is refused, so the galleys hold in the Gulf.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.project import project
from revisionist.core.realism import economy, trade
from revisionist.core.realism.quantity import RESOLVER_KEYS
from revisionist.core.realism.resolvers import movement
from revisionist.core.realism.trade import STOCK_MONTHS, TradeError, TradeLine
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.state import State
from revisionist.core.visibility import Visibility
from revisionist.core.world import WorldFile
from revisionist.engine import catchup
from tests.test_adjacency_moves import (
    START,
    Logged,
    World,
    day,
    entity,
    fold,
    piece,
    seat,
    send,
    where,
)
from tests.test_adjacency_moves import game as claimed
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_territory_model import refused

SUDLAND, NORRA, OST = "sudland", "norra", "ost"
GALLEYS, GULF, OPEN_SEA = "sudland_galleys", "the_gulf", "open_sea"
MAY_1, JUNE_1 = day(29), day(60)


def with_fuel(w: World) -> None:
    w["rules"] = ["territories", "holders", "economy", "fuel"]
    w["entities"].append({"key": OST, "kind": "polity", "name": "Ost"})


def stocks(**amounts: float) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["fuel_stocks"] = [{"polity": k, "amount": v, "source": "toy"} for k, v in amounts.items()]

    return change


def line(
    key: str = "ost_pitch",
    exporter: str = OST,
    importer: str = SUDLAND,
    resource: str = "pitch",
    amount: float = 3,
    cut: bool = False,
) -> Callable[[World], None]:
    def change(w: World) -> None:
        w.setdefault("trade_lines", []).append(
            {
                "key": key,
                "exporter": exporter,
                "importer": importer,
                "resource": resource,
                "amount": amount,
                "cut": cut,
                "source": "toy",
            }
        )

    return change


def yields(area: str, **amounts: float) -> Callable[[World], None]:
    def change(w: World) -> None:
        (t,) = [t for t in w["territories"] if t["key"] == area]
        t["yields"] = amounts

    return change


def toy(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    return territories_toy(tmp, with_fuel, *changes)


def play(tmp: Path, *changes: Callable[[World], None]) -> State:
    return claimed(toy(tmp, *changes))[1]


def worked(tmp: Path, *changes: Callable[[World], None]) -> State:
    """The worked example's world: Sudland's 2 barrels and the Ost line, 3 a month."""
    return play(tmp, stocks(sudland=2), line(), *changes)


def stock(state: State, polity: str = SUDLAND) -> float:
    return economy.stock(state, entity(polity))


def days(state: State, first: date, last: date) -> tuple[State, list[ev.Payload]]:
    """Every day from ``first`` to ``last``: the pieces' steps, then the 1st's payments,
    as the day walk lands them."""
    out: list[ev.Payload] = []
    d = first
    while d <= last:
        for walk in (movement.walk, economy.walk):
            landed = walk(state, d)
            state = fold(state, landed)
            out += landed
        d += timedelta(days=1)
    return state, out


def sortie(state: State, first: int, n: int) -> tuple[State, list[ev.Payload]]:
    """The galleys out to the Open Sea on day ``first`` and back to the Gulf: a step on
    ``first`` + 3 and one on ``first`` + 5, both walked."""
    state = send(state, "tomas", GALLEYS, OPEN_SEA, on=day(first), n=n)
    state, out = days(state, day(first), day(first + 3))
    state = send(state, "tomas", GALLEYS, GULF, on=day(first + 3), n=n + 1)
    state, back = days(state, day(first + 4), day(first + 5))
    return state, out + back


def refusals(out: Sequence[ev.Payload]) -> list[ev.StepRefused]:
    return [p for p in out if isinstance(p, ev.StepRefused)]


def steps(out: Sequence[ev.Payload]) -> list[ev.PieceStepped]:
    return [p for p in out if isinstance(p, ev.PieceStepped)]


# --- Rule 1: each nation's stock starts at the world's figure, or STOCK_MONTHS of income --


def test_a_nations_stock_starts_at_the_worlds_figure(tmp_path: Path) -> None:
    state = play(tmp_path, stocks(sudland=7.5, norra=0))
    assert stock(state) == 7.5
    assert stock(state, NORRA) == 0


def test_a_stock_the_world_gives_no_figure_starts_at_months_of_fuel_income(
    tmp_path: Path,
) -> None:
    assert STOCK_MONTHS == 6
    state = play(tmp_path, yields("isle", pitch=2), yields("norra_hills", pitch=0.5))
    assert stock(state) == 12  # Sudland holds the Isle: 2 barrels a month
    assert stock(state, NORRA) == 3
    assert stock(state, OST) == 0


def test_the_worlds_figure_wins_over_the_months_of_income(tmp_path: Path) -> None:
    state = play(tmp_path, yields("isle", pitch=2), stocks(sudland=1))
    assert stock(state) == 1


def test_fuel_needs_the_economy_and_a_fuel_resource(tmp_path: Path) -> None:
    def no_economy(w: World) -> None:
        w["rules"] = ["territories", "holders", "fuel"]

    def no_pitch(w: World) -> None:
        w["resources"] = [r for r in w["resources"] if r["role"] != "fuel"]
        for k in w["piece_kinds"]:
            k.pop("fuel_per_step", None)

    assert "rules: fuel needs economy" in refused(toy(tmp_path, no_economy))
    assert "rules: fuel needs a resource with the fuel role" in refused(toy(tmp_path, no_pitch))


def test_stocks_and_lines_need_the_fuel_rule(tmp_path: Path) -> None:
    def economy_only(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy"]

    problems = refused(toy(tmp_path, stocks(sudland=1), economy_only))
    assert "rules: fuel stocks and trade lines need fuel" in problems


def test_a_stock_names_a_polity_once(tmp_path: Path) -> None:
    def twice(w: World) -> None:
        w["fuel_stocks"] = [
            {"polity": SUDLAND, "amount": 1, "source": "toy"},
            {"polity": SUDLAND, "amount": 2, "source": "toy"},
            {"polity": "ilse", "amount": 2, "source": "toy"},
        ]

    problems = refused(toy(tmp_path, twice))
    assert f"fuel stock {SUDLAND}: named twice" in problems
    assert "fuel stock ilse: ilse is not a polity" in problems


# --- Rule 2: the 1st adds the month's fuel income and what open lines pay -----------------


def test_the_first_of_the_month_adds_fuel_income_and_the_open_lines(tmp_path: Path) -> None:
    state = play(tmp_path, stocks(sudland=2), yields("isle", pitch=1.5), line())
    state, _ = days(state, day(1), MAY_1 - timedelta(days=1))
    assert stock(state) == 2
    state, _ = days(state, MAY_1, MAY_1)
    assert stock(state) == 2 + 1.5 + 3
    state, _ = days(state, MAY_1 + timedelta(days=1), JUNE_1)
    assert stock(state) == 2 + 2 * 4.5


def test_a_line_pays_into_the_pool_of_its_resources_role(tmp_path: Path) -> None:
    state = play(tmp_path, line(resource="grain", amount=40), line("ost_men", resource="levies"))
    was = state.economy.pools.get(entity(SUDLAND), economy.Pools())
    state, _ = days(state, MAY_1, MAY_1)
    pools = state.economy.pools[entity(SUDLAND)]
    assert pools.output == was.output + 8 + 40  # the coast's grain and iron, and the line
    assert pools.manpower == was.manpower + 3
    assert pools.fuel == was.fuel


def test_the_exporter_pays_nothing_out_of_its_own_pools(tmp_path: Path) -> None:
    state = worked(tmp_path, stocks(sudland=2, ost=5))
    state, _ = days(state, MAY_1, MAY_1)
    assert stock(state, OST) == 5


def test_without_fuel_the_pools_hold_no_fuel_and_lines_pay_nothing(tmp_path: Path) -> None:
    def economy_only(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy"]

    state = play(tmp_path, yields("isle", pitch=2), economy_only)
    state, _ = days(state, MAY_1, MAY_1)
    assert stock(state) == 0


# --- Rule 3: a line pays nothing while cut or while its nations are at war --------------


def test_a_line_that_starts_cut_pays_nothing(tmp_path: Path) -> None:
    state = play(tmp_path, stocks(sudland=2), line(cut=True))
    state, _ = days(state, MAY_1, JUNE_1)
    assert stock(state) == 2


def test_a_line_between_nations_at_war_pays_nothing(tmp_path: Path) -> None:
    state = play(tmp_path, stocks(norra=2), line(exporter=SUDLAND, importer=NORRA))
    state, _ = days(state, MAY_1, MAY_1)
    assert stock(state, NORRA) == 2


def test_a_war_begun_between_the_two_nations_stops_the_line(tmp_path: Path) -> None:
    state = worked(tmp_path)
    a, b = entity(OST), entity(SUDLAND)
    war = War(war_id=war_id_for(a, b), a=a, b=b, since=day(10), declared_by=a)
    state = fold(state, [ev.WarDeclared(war=war)])
    state, _ = days(state, MAY_1, MAY_1)
    assert stock(state) == 2


def test_the_worked_example_open(tmp_path: Path) -> None:
    state = worked(tmp_path)
    state, out = sortie(state, 0, 1)
    assert len(steps(out)) == 2 and stock(state) == 0
    state, _ = days(state, day(6), MAY_1)
    assert stock(state) == 3
    state, out = sortie(state, 30, 3)
    assert len(steps(out)) == 2 and not refusals(out)
    assert stock(state) == 1
    state, _ = days(state, day(36), JUNE_1)
    assert stock(state) == 4


def test_the_worked_example_cut(tmp_path: Path) -> None:
    state = worked(tmp_path)
    state = fold(state, [trade.set(state, "ost_pitch", open=False, on=START)])
    state, out = sortie(state, 0, 1)
    assert len(steps(out)) == 2 and stock(state) == 0
    state, _ = days(state, day(6), MAY_1)
    assert stock(state) == 0
    state, out = sortie(state, 30, 3)
    assert not steps(out)
    no = refusals(out)[0]
    assert no.on == day(33) and no.to == entity(OPEN_SEA)
    assert where(state, GALLEYS) == entity(GULF)


def test_a_line_is_checked_at_compile(tmp_path: Path) -> None:
    problems = refused(
        toy(
            tmp_path,
            line(),
            line(),
            line("self", exporter=OST, importer=OST),
            line("person", exporter="ilse"),
            line("rails", resource="nothing"),
        )
    )
    assert "trade line ost_pitch: duplicate key" in problems
    assert "trade line self: a line runs between two nations" in problems
    assert "trade line person: ilse is not a polity" in problems
    assert "trade line rails: nothing is not output, manpower or fuel" in problems


# --- Rule 4: a step spends fuel_per_step as it starts; too little stock refuses it --------


def test_a_step_spends_the_kinds_fuel_on_the_day_it_falls_due(tmp_path: Path) -> None:
    state = play(tmp_path, stocks(sudland=5))
    state = send(state, "tomas", GALLEYS, OPEN_SEA)
    assert stock(state) == 5  # filing and setting out spend nothing
    state, _ = days(state, day(1), day(2))
    assert stock(state) == 5
    state, out = days(state, day(3), day(3))
    assert len(steps(out)) == 1 and stock(state) == 4
    spent = [p for p in out if isinstance(p, ev.EconomySet)]
    assert [(p.polity, p.pools.fuel, p.on) for p in spent] == [(entity(SUDLAND), 4, day(3))]


def test_a_kind_with_no_fuel_per_step_spends_nothing(tmp_path: Path) -> None:
    state = play(tmp_path, stocks(norra=0))
    state = send(state, "ilse", "norra_levy", "norra_hills")
    state, out = days(state, day(1), day(10))
    assert steps(out) and not refusals(out)
    assert stock(state, NORRA) == 0


def test_too_little_stock_refuses_the_step_with_the_reason_and_the_piece_holds(
    tmp_path: Path,
) -> None:
    state = play(tmp_path, stocks(sudland=0.5))
    state = send(state, "tomas", GALLEYS, OPEN_SEA)
    state, out = days(state, day(1), day(10))
    assert not steps(out)
    (no,) = refusals(out)
    assert no.nation == entity(SUDLAND) and no.area == entity(GULF)
    assert no.on == day(3)
    assert no.reason == "too little pitch: the step needs 1 barrels, the stock holds 0.5"
    galleys = piece(state, GALLEYS)
    assert galleys.places == (entity(GULF),) and not galleys.path
    assert stock(state) == 0.5


def test_a_nations_pieces_share_its_stock_on_one_day(tmp_path: Path) -> None:
    def second(w: World) -> None:
        w["features"].append(
            {
                "key": "sudland_galleys_two",
                "kind": "piece",
                "piece": "galley",
                "name": "The Second Galleys",
                "side": SUDLAND,
                "places": ["gulf_roads"],
                "source": "toy",
            }
        )

    state = play(tmp_path, stocks(sudland=1), second)
    state = send(state, "tomas", GALLEYS, OPEN_SEA)
    state = send(state, "tomas", "sudland_galleys_two", OPEN_SEA, n=2)
    state, out = days(state, day(3), day(3))
    assert len(steps(out)) == 1 and len(refusals(out)) == 1
    assert stock(state) == 0


def test_without_fuel_a_step_spends_nothing_and_is_never_refused(tmp_path: Path) -> None:
    def economy_only(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy"]

    state = play(tmp_path, economy_only)
    state = send(state, "tomas", GALLEYS, OPEN_SEA)
    state, out = days(state, day(1), day(3))
    assert len(steps(out)) == 1 and not refusals(out)
    assert not [p for p in out if isinstance(p, ev.EconomySet)]


# --- Rule 5: trade.set lands trade_set; ``trade`` is a rule name for forms ----------------


def test_set_cuts_and_opens_a_line(tmp_path: Path) -> None:
    state = worked(tmp_path)
    cut = trade.set(state, "ost_pitch", open=False, on=day(4))
    assert cut.kind == "trade_set" and cut.on == day(4) and cut.line.cut
    state = fold(state, [cut])
    assert state.economy.lines["ost_pitch"].cut
    state = fold(state, [trade.set(state, "ost_pitch", open=True, on=day(9))])
    state, _ = days(state, MAY_1, MAY_1)
    assert stock(state) == 5


def test_set_refuses_an_unknown_line_and_a_game_without_fuel(tmp_path: Path) -> None:
    state = worked(tmp_path)
    with pytest.raises(TradeError, match="no trade line nope"):
        trade.set(state, "nope", open=False, on=START)

    def economy_only(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy"]

    off = play(tmp_path, economy_only)
    with pytest.raises(TradeError, match="the fuel rule is off"):
        trade.set(off, "ost_pitch", open=False, on=START)


def test_the_fold_lets_only_cut_change(tmp_path: Path) -> None:
    state = worked(tmp_path)
    was = state.economy.lines["ost_pitch"]
    with pytest.raises(FoldError, match="only whether it is cut changes"):
        fold(state, [ev.TradeSet(line=was.model_copy(update={"amount": 99}), on=START)])
    bad = TradeLine(
        key="x", exporter=entity(OST), importer=entity(SUDLAND), resource="glory", amount=1
    )
    with pytest.raises(FoldError, match="a line carries output, manpower or fuel"):
        fold(state, [ev.TradeSet(line=bad, on=START)])


def test_trade_is_a_rule_name_for_forms_with_no_function_yet(tmp_path: Path) -> None:
    assert "trade" in RESOLVER_KEYS

    from tests.test_adjacency_moves import levers

    def trade_lever(w: World) -> None:
        levers(w)
        for c in w["cards"]:
            for lv in c.get("levers", []):
                lv["resolver"] = "trade"

    assert any(
        "the rule name has no rule yet: trade" in p for p in refused(toy(tmp_path, trade_lever))
    )


# --- Rule 6: gated by ``fuel``; seats see only their own -----------------------------------


def test_the_fold_refuses_a_trade_set_with_fuel_off(tmp_path: Path) -> None:
    def economy_only(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy"]

    state = play(tmp_path, economy_only)
    line_ = TradeLine(
        key="x", exporter=entity(OST), importer=entity(SUDLAND), resource="pitch", amount=1
    )
    with pytest.raises(FoldError, match="the fuel rule is off"):
        fold(state, [ev.TradeSet(line=line_, on=START)])


def test_a_game_without_fuel_hashes_as_before(tmp_path: Path) -> None:
    def economy_only(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy"]

    state = play(tmp_path, economy_only)
    assert "economy" not in state.model_dump(mode="json")
    state, _ = days(state, MAY_1, MAY_1)
    dumped = state.model_dump(mode="json")
    assert dumped["economy"]["pools"] and "lines" not in dumped["economy"]
    assert all("fuel" not in p for p in dumped["economy"]["pools"].values())


def test_a_seat_sees_its_own_stock_and_only_the_lines_its_nation_is_party_to(
    tmp_path: Path,
) -> None:
    state = play(tmp_path, stocks(sudland=2, norra=4), line(), line("ost_norra", importer=NORRA))
    tomas = project(state, seat("tomas"))
    assert economy.stock(tomas, entity(SUDLAND)) == 2
    assert economy.stock(tomas, entity(NORRA)) == 0
    assert set(tomas.economy.lines) == {"ost_pitch"}
    assert set(project(state, seat("ilse")).economy.lines) == {"ost_norra"}


def test_trade_set_is_never_fed_and_a_refused_step_reaches_its_own_seats_only(
    tmp_path: Path,
) -> None:
    assert "trade_set" in catchup.NEVER
    assert "step_refused" in catchup.FEED_KINDS
    g = Logged(toy(tmp_path, stocks(sudland=0), line()), "ilse", "tomas")
    g.send("tomas", GALLEYS, OPEN_SEA)
    out = g.walk(day(1), day(5))
    (no,) = [e for e in out if isinstance(e.payload, ev.StepRefused)]
    assert no.scope.visibility is Visibility.RESTRICTED
    assert no.scope.known_by == frozenset({seat("tomas")})
    mine = catchup.feed(g.state, g.log, seat("tomas"), 0, 10)
    theirs = catchup.feed(g.state, g.log, seat("ilse"), 0, 10)
    assert [f.event.kind for f in mine].count("step_refused") == 1
    assert not [f for f in theirs if f.event.kind == "step_refused"]
    assert not [f for f in mine if f.event.kind == "trade_set"]


def test_a_trade_set_landed_in_the_day_walk_is_sealed_to_the_two_nations(
    tmp_path: Path,
) -> None:
    from revisionist.engine import realism_tick

    g = Logged(toy(tmp_path, stocks(sudland=0), line()), "ilse", "tomas")
    scope = realism_tick._scope_of(g.state, trade.set(g.state, "ost_pitch", False, START))
    assert scope.visibility is Visibility.RESTRICTED
    assert seat("tomas") in scope.known_by and seat("ilse") not in scope.known_by
