"""Votes and opinion read the groups (GVR).

With ``groups`` on, a chamber's tally comes from its blocs as the world declares them: each
bloc's yes share starts from the world's row for that measure and vote (or its default row),
moves one point for every ``VOTE_POINTS`` of support away from the bloc's baseline, and by
the bloc's stance on each clause. The opinion figure a nation publishes is the support of the
group the world names for it. A declaration of war moves groups through the happening only.
No bill, chamber, party or poll is named on this path; stored games and worlds without groups
keep today's tables.

The toy world (``tests/worlds/territory-toy.yaml``) gives Norra a two-bloc chamber, the
assembly; the tests here give both blocs a hundred seats so a point of share is one vote.
"""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, OrderId, PipelineId, derived_id
from revisionist.core.realism import groups
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.effect import Clause, ClauseKind, ProposeMeasure
from revisionist.core.realism.groups import Cause, Happening
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import opinion, votes, war
from revisionist.core.realism.war import NewsEvent, NewsTopic, War
from revisionist.core.state import State
from tests.test_adjacency_moves import START, Logged, entity, seat, toy
from tests.test_territory_model import CAMPAIGN

World = dict[str, Any]
NORRA, SUDLAND = entity("norra"), entity("sudland")
ASSEMBLY = "assembly"
MONDAY = START + timedelta(days=7)
CITED = {"unit": "percent", "source": "toy"}
assert START.weekday() == 0


def _bloc(w: World, key: str) -> dict[str, Any]:
    nation = next(n for n in w["groups"] if n["nation"] == "norra")
    return next(g for g in nation["groups"] if g["key"] == key)


def hundred(w: World) -> None:
    """Both blocs of the assembly at a hundred seats, every vote a hundred strong."""
    greens, greys = _bloc(w, "greens"), _bloc(w, "greys")
    greens.update(
        seats=100,
        baseline=55,
        start=55,
        votes={"levy_act": {ASSEMBLY: {"voting": 100, "yeas": 70}}},
        vote_default={ASSEMBLY: {"voting": 100, "yeas": 50}},
        stances={"power": 1, "money": -1},
    )
    greys.update(
        seats=100,
        votes={"levy_act": {ASSEMBLY: {"voting": 100, "yeas": 20}}},
        vote_default={ASSEMBLY: {"voting": 100, "yeas": 40}},
        stances={"limit": 2},
    )


def published(w: World) -> None:
    """Public quantities for the assembly's counts on the levy act and the act's result."""
    w["quantities"] += [
        {"key": k, "owner": "norra", "name": k, "unit": "votes", "public": True, "computed": True}
        for k in ("levy_act_assembly_yeas", "levy_act_assembly_nays", "levy_act_passed")
    ]


def ruled(w: World) -> None:
    w["rules"] = ["territories", "holders", "economy", "groups"]


def game(tmp: Path, *changes: Callable[[World], None], on: bool = True) -> Logged:
    def change(w: World) -> None:
        if on:
            ruled(w)
        hundred(w)
        published(w)
        for c in changes:
            c(w)

    return Logged(toy(tmp, change), "ilse", "tomas")


def at(g: Logged, key: str, value: int, polity: EntityId = NORRA) -> None:
    was = groups.support(g.state, polity, key) or 0
    g.add([groups.shift(g.state, polity, key, value - was, Cause.DRIFT, START)])


SEED = OrderId(derived_id(CAMPAIGN, "gvr-order", 1))


def tally(state: State, measure: str = "levy_act", **kw: Any) -> tuple[int, int]:
    return votes.bloc_tally(state, NORRA, ASSEMBLY, measure, ASSEMBLY, SEED, **kw)


def order(bill: str = "levy_act", measure: ProposeMeasure | None = None, n: int = 1) -> Order:
    return Order(
        order_id=OrderId(derived_id(CAMPAIGN, "gvr-order", n)),
        issuer=seat("ilse"),
        lever="pass_act",
        pipeline=PipelineId(derived_id(CAMPAIGN, "gvr-pipeline")),
        params={} if measure is not None else {"bill": bill},
        status=OrderStatus.ENACTED,
        filed=START,
        measure=measure,
    )


def changes(state: State, o: Order) -> dict[str, int]:
    """The quantity changes the votes rule makes for ``o``, by world key."""
    keys = {rs.qid(state, k): k for k in ("levy_act_assembly_yeas", "levy_act_assembly_nays")}
    keys[rs.qid(state, "levy_act_passed")] = "levy_act_passed"
    out = rs.ON_ORDER["votes"](state, o)
    return {keys[c.quantity_id]: c.value for c in out if isinstance(c, QuantityChange)}


# --- rule 1: a chamber's tally comes from its blocs -----------------------------------


def test_the_tally_reads_each_blocs_row_for_a_listed_measure_with_no_order_in_state(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    assert not g.state.orders
    assert tally(g.state) == (70 + 20, 30 + 80)


def test_a_measure_no_bloc_lists_takes_each_blocs_default_row(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert tally(g.state, "harbour_act") == (50 + 40, 50 + 60)


def test_a_blocs_share_moves_a_point_for_every_vote_points_of_support(tmp_path: Path) -> None:
    g = game(tmp_path)
    at(g, "greens", 55 + 4 * votes.VOTE_POINTS)
    at(g, "greys", 30 - 2 * votes.VOTE_POINTS)
    assert tally(g.state) == (74 + 18, 26 + 82)


def test_a_blocs_stance_on_each_clause_moves_its_share(tmp_path: Path) -> None:
    g = game(tmp_path)
    clauses = (
        Clause(kind=ClauseKind.POWER, subject="raise levies"),
        Clause(kind=ClauseKind.LIMIT, subject="a year at most"),
    )
    # greens: power +1, limit 0; greys: power 0, limit +2
    assert tally(g.state, "harbour_act", clauses=clauses) == (51 + 42, 49 + 58)


def test_an_urgent_measure_moves_the_blocs_that_back_executive_power(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert tally(g.state, urgent=True) == (70 + votes.URGENT_BLOC_POINTS + 20, 30 - 2 + 80)


def test_a_bloc_with_no_row_for_the_vote_casts_none(tmp_path: Path) -> None:
    def greys_silent(w: World) -> None:
        _bloc(w, "greys").update(votes={}, vote_default={})

    g = game(tmp_path, greys_silent)
    assert tally(g.state) == (70, 30)


def test_the_fraction_of_a_vote_is_drawn_from_the_seed_and_the_same_every_time(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    at(g, "greens", 55 + 2)  # 0.4 of a point of share: 0.4 of a vote
    seen = set()
    for n in range(40):
        seed = OrderId(derived_id(CAMPAIGN, "gvr-seed", n))
        once = votes.bloc_tally(g.state, NORRA, ASSEMBLY, "levy_act", ASSEMBLY, seed)
        assert once == votes.bloc_tally(g.state, NORRA, ASSEMBLY, "levy_act", ASSEMBLY, seed)
        seen.add(once)
    assert seen == {(90, 110), (91, 109)}


def test_an_enacted_bill_writes_each_vote_and_the_result_from_the_blocs(tmp_path: Path) -> None:
    g = game(tmp_path)
    at(g, "greys", 30 + 10 * votes.VOTE_POINTS)  # greys from 20 to 30 yeas
    assert changes(g.state, order()) == {
        "levy_act_assembly_yeas": 100,
        "levy_act_assembly_nays": 100,
        "levy_act_passed": 0,
    }
    at(g, "greys", 30 + 11 * votes.VOTE_POINTS)
    assert changes(g.state, order())["levy_act_passed"] == 1


def test_a_measure_carried_by_an_order_is_tallied_from_the_blocs(tmp_path: Path) -> None:
    g = game(tmp_path)
    listed = ProposeMeasure(
        title="Levy Act", clauses=(Clause(kind=ClauseKind.POWER, subject="raise levies"),)
    )
    assert changes(g.state, order(measure=listed))["levy_act_assembly_yeas"] == 90


def test_a_measure_passed_moves_the_groups_that_name_it(tmp_path: Path) -> None:
    def moved_by_a_law(w: World) -> None:
        _bloc(w, "greens")["moved_by"]["measure_passed"] = 2

    g = game(tmp_path, moved_by_a_law)
    at(g, "greys", 30 + 11 * votes.VOTE_POINTS)
    out = rs.ON_ORDER["votes"](g.state, order())
    moved = [c for c in out if isinstance(c, ev.GroupMoved)]
    assert [(m.group, m.change, m.cause) for m in moved] == [("greens", 2, Cause.MEASURE_PASSED)]
    at(g, "greys", 30)
    assert not [c for c in rs.ON_ORDER["votes"](g.state, order()) if isinstance(c, ev.GroupMoved)]


def test_a_measure_passed_moves_the_groups_where_the_world_keeps_no_count(tmp_path: Path) -> None:
    def unrecorded(w: World) -> None:
        _bloc(w, "greens")["moved_by"]["measure_passed"] = 2
        w["quantities"] = [q for q in w["quantities"] if not q["key"].startswith("levy_act")]

    g = game(tmp_path, unrecorded)
    at(g, "greys", 30 + 11 * votes.VOTE_POINTS)
    out = rs.ON_ORDER["votes"](g.state, order())
    assert [(c.group, c.change) for c in out if isinstance(c, ev.GroupMoved)] == [("greens", 2)]
    assert not [c for c in out if isinstance(c, QuantityChange)]


def test_a_decided_bill_is_news_with_each_vote_from_the_blocs(tmp_path: Path) -> None:
    g = game(tmp_path)
    o = order()
    g.add(rs.apply_changes(g.state, rs.ON_ORDER["votes"](g.state, o)))
    item = votes.news(g.state, o, START)
    assert item is not None and item.subject == NORRA
    assert item.headline == "Levy act fails in the assembly"
    assert [(f.label, f.value) for f in item.facts][:2] == [
        ("Assembly", "90 to 110"),
        ("Result", "Failed"),
    ]


# --- rule 5: every bloc at its baseline gives the baseline exactly ----------------------


@pytest.mark.parametrize("measure", ["levy_act", "harbour_act"])
def test_every_bloc_at_its_baseline_gives_the_baseline_tally_exactly(
    tmp_path: Path, measure: str
) -> None:
    def odd(w: World) -> None:
        _bloc(w, "greens").update(
            seats=60,
            votes={"levy_act": {ASSEMBLY: {"voting": 57, "yeas": 41}}},
            vote_default={ASSEMBLY: {"voting": 53, "yeas": 26}},
        )
        _bloc(w, "greys").update(
            seats=40,
            votes={"levy_act": {ASSEMBLY: {"voting": 37, "yeas": 9}}},
            vote_default={ASSEMBLY: {"voting": 39, "yeas": 17}},
        )

    g = game(tmp_path, odd)
    at(g, "greys", 30)
    expected = (41 + 9, 16 + 28) if measure == "levy_act" else (26 + 17, 27 + 22)
    for n in range(20):
        seed = OrderId(derived_id(CAMPAIGN, "gvr-seed", n))
        assert votes.bloc_tally(g.state, NORRA, ASSEMBLY, measure, ASSEMBLY, seed) == expected


# --- rule 4: the new path names no bill, chamber, party or poll --------------------------


def test_the_groups_path_reads_no_table_in_code(tmp_path: Path, monkeypatch: Any) -> None:
    g = game(tmp_path)
    at(g, "greens", 70)
    before = (tally(g.state), changes(g.state, order()), tally(g.state, "x", urgent=True))
    for name in ("TALLIES", "HISTORICAL", "NOVEL_ROWS", "CLAUSE_POINTS", "BASE_OFFSET_POINTS"):
        monkeypatch.setattr(votes, name, {})
    monkeypatch.setattr(votes, "OPINION_NEUTRAL", 0)
    monkeypatch.setattr(votes, "URGENT_D_POINTS", 40)
    assert (tally(g.state), changes(g.state, order()), tally(g.state, "x", urgent=True)) == before


def test_with_groups_off_a_bill_the_tables_do_not_know_moves_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, on=False)
    assert not groups.on(g.state)
    assert changes(g.state, order()) == {}


# --- rule 2: the opinion figure is the support of the group the world names -------------


def _polls(out: tuple[rs.Change, ...]) -> list[NewsEvent]:
    return [c for c in out if isinstance(c, NewsEvent) and c.topic is NewsTopic.POLL]


def test_on_a_monday_the_opinion_group_is_published_when_it_moved(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert _polls(opinion.on_day(g.state, MONDAY)) == []
    at(g, "public", 47)
    assert _polls(opinion.on_day(g.state, MONDAY + timedelta(days=1))) == []
    (poll,) = _polls(opinion.on_day(g.state, MONDAY))
    assert poll.subject == NORRA and poll.on == MONDAY
    assert poll.headline == "Poll: The Norra Public up to 47%"
    assert [(f.label, f.value) for f in poll.facts][:2] == [
        ("The Norra Public", 47),
        ("Previous poll", 40),
    ]


def test_the_next_poll_is_measured_from_the_last_one_published(tmp_path: Path) -> None:
    g = game(tmp_path)
    at(g, "public", 47)
    g.add(rs.apply_changes(g.state, opinion.on_day(g.state, MONDAY)))
    later = MONDAY + timedelta(days=7)
    assert _polls(opinion.on_day(g.state, later)) == []
    at(g, "public", 44)
    (poll,) = _polls(opinion.on_day(g.state, later))
    assert poll.headline == "Poll: The Norra Public down to 44%"
    assert [(f.label, f.value) for f in poll.facts][1] == ("Previous poll", 47)


def test_the_published_figure_is_the_weighted_support_of_every_group_that_feeds_it(
    tmp_path: Path,
) -> None:
    def two_feed(w: World) -> None:
        _bloc(w, "smiths")["feeds"]["opinion"] = 3

    g = game(tmp_path, two_feed)
    at(g, "smiths", 60)
    (poll,) = _polls(opinion.on_day(g.state, MONDAY))
    assert poll.facts[0].value == (60 * 3 + 40) // 4


def test_with_groups_on_the_old_opinion_figures_do_not_move(tmp_path: Path) -> None:
    def old_figures(w: World) -> None:
        w["quantities"] += [
            {
                "key": "gallup_fdr_about_right",
                "owner": "norra",
                "name": "About right",
                "value": 50,
                "unit": "percent",
                "source": "toy",
                "public": True,
            },
            {"key": "opinion_target", "owner": "norra", "name": "Target", "value": 60, **CITED},
        ]

    g = game(tmp_path, old_figures)
    theme = {"theme": "national_unity"}
    address = order().model_copy(update={"lever": "public_address", "params": theme})
    assert opinion.resolve(g.state, address) == ()
    assert [c for c in opinion.on_day(g.state, MONDAY) if isinstance(c, QuantityChange)] == []
    (tmp_path / "off").mkdir()
    off = game(tmp_path / "off", old_figures, on=False)
    assert [c for c in opinion.on_day(off.state, MONDAY) if isinstance(c, QuantityChange)]


# --- rule 3: a declaration of war moves groups through the happening only ---------------


def _usa(w: World) -> None:
    w["entities"].append({"key": "usa", "kind": "polity", "name": "Usonia"})
    help_ = {"key": "gallup_help_britain", "owner": "usa", "name": "Help", "value": 50}
    w["quantities"].append({**help_, "unit": "percent", "source": "toy"})
    w["pipelines"] = [
        {
            "key": "proclamation",
            "name": "A proclamation",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        }
    ]
    card = next(c for c in w["cards"] if c["person"] == "ilse")
    card["pipelines"] = ["proclamation"]
    card["levers"] = [
        {
            "name": "declare_war",
            "pipeline": "proclamation",
            "resolver": "war",
            "params": [{"name": "target", "kind": "enum", "choices": ["usa"]}],
        }
    ]


def _declaration() -> Order:
    return order().model_copy(update={"lever": "declare_war", "params": {"target": "usa"}})


def test_with_groups_on_a_declaration_moves_no_opinion_figure(tmp_path: Path) -> None:
    g = game(tmp_path, _usa)
    out = war.resolve(g.state, _declaration())
    assert any(isinstance(c, War) for c in out)
    assert [c for c in out if isinstance(c, QuantityChange)] == []
    (tmp_path / "off").mkdir()
    off = game(tmp_path / "off", _usa, on=False)
    out = war.resolve(off.state, _declaration())
    assert [c for c in out if isinstance(c, QuantityChange)]


def test_a_declaration_moves_the_groups_that_name_it_once(tmp_path: Path) -> None:
    g = game(tmp_path, _usa)
    out = war.resolve(g.state, _declaration())
    declared = [ev.WarDeclared(war=c) for c in out if isinstance(c, War)]
    moved = groups.react(g.state, g.state, declared, START)
    assert [(m.polity, m.group, m.change) for m in moved] == [(NORRA, "greens", 2)]
    assert moved[0].cause is Cause(Happening.WAR_DECLARED.value)


# --- PRR rule 1: an offer's points count on its own measure only -------------------------


def _greens_count(state: State, measure: str) -> int:
    (_, yeas, _) = next(
        c
        for c in votes.bloc_counts(state, NORRA, ASSEMBLY, measure, "assembly", OrderId("seed"))
        if c[0] == "greens"
    )
    return yeas


def test_an_offer_counts_on_its_own_measure_and_no_other(tmp_path: Path) -> None:
    from tests import test_offers as to

    g = to.game(tmp_path)
    to.bill(g)
    assert _greens_count(g.state, to.MEASURE) == 25  # at its baseline: the world's row
    assert _greens_count(g.state, "levy_act") == 40  # its own row
    to.offer(g, to.ILSE)
    g.walk(to.day(1), to.day(1))
    assert _greens_count(g.state, to.MEASURE) == 26
    assert _greens_count(g.state, "levy_act") == 40
