"""Peace: an armistice and terms (PEA).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``agreements``,
``locks``, ``deciders``, ``ask_answers`` and ``peace`` on. Norra (Ilse) and Sudland
(Tomas) are at war; Ostmark (Olaf) is a third power. Each nation gains a lock row of the
kind peace with no order: Ilse allows Norra's peace herself, Tomas Sudland's, Olaf
Ostmark's, unless a test puts Sudland's before a council of Tomas and Sven Dahl, a
councillor nobody plays, two of the two to agree.

Sven's card is set past the draw's reach: regard 3 for Tomas grants, -3 declines.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.ids import EntityId, FeatureId, OrderId
from revisionist.core.realism import agreement, locks, process
from revisionist.core.realism.agreement import Agreement, ClauseStatus
from revisionist.core.realism.battle import Ending
from revisionist.core.realism.effect import AgreementClause, ClauseType
from revisionist.core.realism.war import War, at_war, broke_peace, war_id_for
from revisionist.core.state import Rule
from revisionist.core.world_compile import WorldError, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup
from tests.test_adjacency_moves import START, Logged, entity, toy
from tests.test_agreements import (
    NORRA,
    OLAF,
    OSTMARK,
    SUDLAND,
    TOMAS,
    answer,
    clause,
    deal,
    made,
    of,
    offer,
    ostmark,
    ruled,
)
from tests.test_territory_model import CAMPAIGN

World = dict[str, Any]
RULES = ("holders", "agreements", "locks", "deciders", "ask_answers", "peace")
LEVY = FeatureId(entity("norra_levy"))


def day(n: int) -> date:
    return START + timedelta(days=n)


def peace_row(nation: str, decider: dict[str, Any]) -> dict[str, Any]:
    return {"key": f"{nation}_peace", "question": "peace", "decider": decider}


def peace_rows(w: World) -> None:
    """Each nation's peace is allowed by its leader."""
    w["locks"] = [
        peace_row("norra", {"person": "ilse"}),
        peace_row("sudland", {"person": "tomas"}),
        peace_row("ostmark", {"person": "olaf"}),
    ]


def council(regard: int) -> Callable[[World], None]:
    """Sudland's peace before a council of Tomas and Sven, both to agree; Sven's regard
    for Tomas is ``regard``."""

    def edit(w: World) -> None:
        w["entities"].append(
            {"key": "sven", "kind": "person", "name": "Sven Dahl", "parent": "sudland"}
        )
        w["cards"].append(
            {
                "person": "sven",
                "office": "Councillor of Sudland",
                "playable": False,
                "principals": ["sudland"],
                "horizon_days": 14,
            }
        )
        w.setdefault("relationships", []).append(
            {"key": "sven_tomas", "a": "sven", "b": "tomas", "disposition": regard}
        )
        row = next(r for r in w["locks"] if r["key"] == "sudland_peace")
        row["decider"] = {"council": {"members": ["tomas", "sven"], "needed": 2, "head": "tomas"}}

    return edit


def levy_at_sudby(w: World) -> None:
    """Norra's levy stands at Sudby, on Sudland's ground; every piece has a strength."""
    for f in w["features"]:
        f["tier"] = 5
    next(f for f in w["features"] if f["key"] == "norra_levy")["places"] = ["sudby"]


def ostmark_at_war(w: World) -> None:
    w["wars"].append({"a": "ostmark", "b": "sudland", "since": "1900-03-01", "source": "toy"})


def no_rows(w: World) -> None:
    w["locks"] = [r for r in w["locks"] if r["key"] != "sudland_peace"]


def game(
    tmp: Path, *changes: Callable[[World], None], rules: Sequence[str] = RULES, people: int = 3
) -> Logged:
    world = toy(tmp, ostmark, ruled(*rules), peace_rows, *changes)
    return Logged(world, *("ilse", "tomas", "olaf")[:people])


def ends_war(binds: EntityId = NORRA, nation: EntityId = SUDLAND) -> AgreementClause:
    return clause(ClauseType.END_WAR, binds=binds, nation=nation)


def armistice(days: int, binds: EntityId = NORRA, nation: EntityId = SUDLAND) -> AgreementClause:
    return clause(ClauseType.ARMISTICE, binds=binds, nation=nation, days=days)


def put_in_force(
    g: Logged,
    *clauses: AgreementClause,
    on: date = START,
    parties: Sequence[EntityId] = (NORRA, SUDLAND),
) -> Agreement:
    x = agreement.pact(CAMPAIGN, f"t{len(made(g))}", parties, "", clauses, on, False)
    g.add([ev.AgreementMade(agreement=x)])
    return g.state.agreements.made[x.agreement_id]


def peace_offer(g: Logged, *clauses: AgreementClause) -> OrderId:
    return offer(g, deal(*clauses, wording="Peace between Norra and Sudland."))


def accepted_by_tomas(g: Logged) -> tuple[OrderId, date]:
    oid = peace_offer(g, ends_war(), ends_war(SUDLAND, NORRA))
    answer(g, oid, TOMAS, True)
    return oid, process.offer_due(g.state, g.state.routed[oid])


def statuses(g: Logged) -> list[ClauseStatus]:
    return [s for x in made(g) for s in x.statuses]


# --- Rule 1: three clause types --------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "fields", "missing"),
    [
        (ClauseType.ARMISTICE, {"nation": SUDLAND}, "days"),
        (ClauseType.ARMISTICE, {"days": 5}, "nation"),
        (ClauseType.END_WAR, {}, "nation"),
        (ClauseType.NO_SEPARATE_PEACE, {}, "nation"),
    ],
)
def test_each_peace_clause_names_what_it_needs(
    kind: ClauseType, fields: dict[str, Any], missing: str
) -> None:
    with pytest.raises(ValueError, match=missing):
        AgreementClause(type=kind, binds=NORRA, **fields)


def test_a_peace_clause_is_between_two_nations_of_the_offer() -> None:
    with pytest.raises(ValueError, match="another nation"):
        clause(ClauseType.END_WAR, binds=NORRA, nation=NORRA)
    with pytest.raises(ValueError, match="between parties"):
        deal(clause(ClauseType.END_WAR, nation=OSTMARK))
    assert deal(clause(ClauseType.NO_SEPARATE_PEACE, nation=OSTMARK)).clauses


def test_the_terms_render_each_peace_clause_in_full(tmp_path: Path) -> None:
    g = game(tmp_path)
    words = [
        agreement.render_clause(g.state, c)
        for c in (armistice(10), ends_war(), clause(ClauseType.NO_SEPARATE_PEACE, nation=OSTMARK))
    ]
    assert words == [
        "Norra: an armistice with Sudland for 10 days.",
        "Norra: the war with Sudland ends; its pieces leave Sudland's ground within 14 days.",
        "Norra: no separate peace with Ostmark.",
    ]


def test_with_peace_off_an_offer_of_peace_is_refused(tmp_path: Path) -> None:
    g = game(tmp_path, rules=("holders", "agreements", "locks", "deciders"))
    with pytest.raises(ValueError, match="Peace is not part of this game"):
        peace_offer(g, armistice(5))


def test_a_peace_between_nations_not_at_war_is_refused(tmp_path: Path) -> None:
    g = game(tmp_path)
    with pytest.raises(ValueError, match="not at war"):
        offer(g, deal(ends_war(NORRA, OSTMARK), parties=(NORRA, OSTMARK)))


# --- Rule 2: an armistice ------------------------------------------------------------


def test_an_armistice_ends_an_open_battle_and_both_hold_where_they_stand(tmp_path: Path) -> None:
    g = game(tmp_path, levy_at_sudby, rules=(*RULES, "battles"))
    g.walk(day(1), day(1))
    assert g.state.battles, "the levies at Sudby fight"
    before = g.state.features[LEVY].places
    put_in_force(g, armistice(5), on=day(1))
    out = g.walk(day(2), day(2))
    (ended,) = of(out, ev.BattleEnded)
    assert ended.ending is Ending.CEASED
    assert not g.state.battles and not of(out, ev.BattleOpened)
    assert g.state.features[LEVY].places == before
    assert at_war(g.state, NORRA, SUDLAND)


def test_no_ground_is_taken_under_an_armistice(tmp_path: Path) -> None:
    from revisionist.core.realism import holders

    def alone(w: World) -> None:
        w["features"] = [f for f in w["features"] if f["key"] != "sudland_levy"]

    g = game(tmp_path, levy_at_sudby, alone)
    coast = entity("sudland_coast")
    assert holders.takers(g.state, coast) == (NORRA,)
    put_in_force(g, armistice(5), on=START)
    assert holders.takers(g.state, coast) == ()


def test_a_battle_that_ceased_is_neither_won_nor_lost_at_home(tmp_path: Path) -> None:
    from revisionist.core.realism import groups

    g = game(tmp_path, levy_at_sudby, rules=(*RULES, "battles", "groups"))
    g.walk(day(1), day(1))
    put_in_force(g, armistice(5), on=day(1))
    start = g.state
    out = g.walk(day(2), day(2))
    assert of(out, ev.BattleEnded)
    happened = groups._held_happenings(start, [e.payload for e in out], day(2))
    kinds = {h for _, h in happened}
    assert groups.Happening.BATTLE_WON not in kinds and groups.Happening.BATTLE_LOST not in kinds


def test_no_battle_opens_under_an_armistice_and_it_lapses_on_its_last_day(tmp_path: Path) -> None:
    g = game(tmp_path, levy_at_sudby, rules=(*RULES, "battles"))
    put_in_force(g, armistice(4), on=START)
    out = g.walk(day(1), day(4))
    assert not of(out, ev.BattleOpened)
    judged = [(p.status, p.on) for p in of(out, ev.ClauseJudged)]
    assert judged == [(ClauseStatus.KEPT, day(4))]
    assert not agreement.armistice(g.state, NORRA, SUDLAND)
    out = g.walk(day(5), day(5))
    assert of(out, ev.BattleOpened), "the armistice has lapsed: the levies fight"


def test_an_armistice_does_not_lapse_into_war_once_terms_are_in_force(tmp_path: Path) -> None:
    g = game(tmp_path, levy_at_sudby, rules=(*RULES, "battles"))
    put_in_force(g, armistice(3), on=START)
    put_in_force(g, ends_war(), ends_war(SUDLAND, NORRA), on=START)
    out = g.walk(day(1), day(4))
    assert not of(out, ev.BattleOpened)
    (kept,) = [p for p in of(out, ev.ClauseJudged) if p.status is ClauseStatus.KEPT]
    assert kept.reason == "Terms are in force."


# --- Rule 3: an end to the war ---------------------------------------------------------


def test_a_war_ended_leaves_the_wars_in_force_and_the_pieces_leave(tmp_path: Path) -> None:
    g = game(tmp_path, levy_at_sudby)
    _, due = accepted_by_tomas(g)
    out = g.walk(day(1), due)
    (x,) = of(out, ev.AgreementMade)
    (ended,) = of(out, ev.WarEnded)
    assert ended.war_id == war_id_for(NORRA, SUDLAND) and ended.on == due
    assert ended.agreement_id == x.agreement.agreement_id
    assert not at_war(g.state, NORRA, SUDLAND)
    (record,) = g.state.ended_wars
    assert record.on == due and record.war.war_id == ended.war_id
    at_sudby = g.state.features[LEVY].places[0]
    g.send("ilse", "norra_levy", "norrhavn")
    out = g.walk(due + timedelta(days=1), due + timedelta(days=agreement.WITHDRAW_DAYS + 2))
    assert g.state.features[LEVY].places[0] != at_sudby
    assert not [p for p in of(out, ev.ClauseJudged) if p.status is ClauseStatus.BROKEN]


def test_a_piece_staying_on_the_others_ground_breaks_the_clause(tmp_path: Path) -> None:
    g = game(tmp_path, levy_at_sudby)
    _, due = accepted_by_tomas(g)
    g.walk(day(1), due)
    last = due + timedelta(days=agreement.WITHDRAW_DAYS)
    out = g.walk(due + timedelta(days=1), last - timedelta(days=1))
    assert not of(out, ev.ClauseJudged)
    out = g.walk(last, last)
    (broken,) = of(out, ev.ClauseJudged)
    assert broken.status is ClauseStatus.BROKEN and broken.clause == 0
    assert "Norra" in broken.reason and "Sudland" in broken.reason


def test_a_war_ended_is_fed_to_every_seat(tmp_path: Path) -> None:
    assert "war_ended" in catchup.FEED_KINDS
    g = game(tmp_path)
    _, due = accepted_by_tomas(g)
    out = g.walk(day(1), due)
    (ended,) = [e for e in out if isinstance(e.payload, ev.WarEnded)]
    assert ended.scope.visibility.value == "public"
    assert g.state.ended_wars == agreement_view_wars(g)


def agreement_view_wars(g: Logged) -> Any:
    from revisionist.core.project import project

    return project(g.state, OLAF).ended_wars


def test_the_war_ends_only_when_every_party_accepted(tmp_path: Path) -> None:
    g = game(tmp_path)
    peace_offer(g, ends_war(), ends_war(SUDLAND, NORRA))
    g.walk(day(1), day(12))
    assert at_war(g.state, NORRA, SUDLAND) and not g.state.ended_wars


# --- Rule 4: accepting is a question of peace --------------------------------------------


def test_an_acceptance_is_held_and_then_allowed_by_a_council(tmp_path: Path) -> None:
    g = game(tmp_path, council(3))
    oid, due = accepted_by_tomas(g)
    out = g.walk(day(1), due)
    assert not of(out, ev.AgreementMade) and at_war(g.state, NORRA, SUDLAND)
    (held,) = of(out, ev.OrderHeld)
    assert held.held.issuer == TOMAS and held.held.decider.council is not None
    assert held.held.order_id == agreement.hold_id(CAMPAIGN, oid, SUDLAND)
    assert held.held.reason == "Held until the council under Tomas Brand allows it."
    (asked,) = of(out, ev.OrderAsked)
    g.add([ev.MatterChosen(order_id=asked.asked.order_id, seat_id=TOMAS, accept=True, on=due)])
    out = g.walk(due + timedelta(days=1), due + timedelta(days=process.ANSWER_DAYS))
    (answered,) = of(out, ev.AskAnswered)
    assert answered.granted
    (x,) = of(out, ev.AgreementMade)
    assert x.agreement.made == due + timedelta(days=process.ANSWER_DAYS)
    assert of(out, ev.WarEnded) and not at_war(g.state, NORRA, SUDLAND)
    assert not g.state.held


def test_a_council_that_declines_lapses_the_peace(tmp_path: Path) -> None:
    g = game(tmp_path, council(-3))
    _, due = accepted_by_tomas(g)
    g.walk(day(1), due)
    (hold,) = g.state.held
    g.add([ev.MatterChosen(order_id=hold, seat_id=TOMAS, accept=True, on=due)])
    out = g.walk(due + timedelta(days=1), due + timedelta(days=6))
    assert not made(g) and at_war(g.state, NORRA, SUDLAND)
    titles = [p.document.title for p in of(out, ev.DocumentIssued)]
    assert titles.count("An offer of agreement lapsed") == 2
    assert not g.state.held


def test_a_withdrawn_acceptance_lapses_the_peace(tmp_path: Path) -> None:
    g = game(tmp_path, council(3))
    _, due = accepted_by_tomas(g)
    g.walk(day(1), due)
    (hold,) = g.state.held
    g.add([ev.HeldOrderEnded(order_id=hold, issuer=TOMAS, on=due, end=locks.HeldEnd.WITHDRAWN)])
    out = g.walk(due + timedelta(days=1), due + timedelta(days=6))
    assert not made(g) and at_war(g.state, NORRA, SUDLAND)
    titles = [p.document.title for p in of(out, ev.DocumentIssued)]
    assert titles.count("An offer of agreement lapsed") == 2


def test_a_held_acceptance_never_lands_as_an_order(tmp_path: Path) -> None:
    from revisionist.engine import realism_tick

    g = game(tmp_path, council(3))
    _, due = accepted_by_tomas(g)
    g.walk(day(1), due)
    (hold,) = g.state.held
    g.add([ev.AskAnswered(order_id=hold, asker=TOMAS, on=due, granted=True)])
    assert realism_tick._unlocked(g.state, due) == []
    out = g.walk(due + timedelta(days=1), due + timedelta(days=6))
    assert not of(out, ev.OrderRouted) and len(made(g)) == 1


def test_a_nation_with_no_peace_row_cannot_accept_one(tmp_path: Path) -> None:
    g = game(tmp_path, no_rows)
    with pytest.raises(ValueError, match="No one in Sudland may accept a peace"):
        peace_offer(g, armistice(5))


def test_the_aide_never_accepts_a_peace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    g = game(tmp_path)
    monkeypatch.setattr(process, "decides", lambda *a: (True, "Agreed."))
    peace_offer(g, ends_war(), ends_war(SUDLAND, NORRA))
    out = g.walk(day(1), day(12))
    assert not made(g) and not of(out, ev.WarEnded)
    assert at_war(g.state, NORRA, SUDLAND)


def test_a_peace_row_names_no_order_and_holds_none(tmp_path: Path) -> None:
    g = game(tmp_path)
    (row,) = locks.rows_on(g.state, SUDLAND, locks.Question.PEACE)
    assert row.order is None and row.when is None
    assert locks.peace_row(g.state, SUDLAND) == row


def test_a_row_with_no_order_must_be_a_question_of_peace(tmp_path: Path) -> None:
    def no_order_war(w: World) -> None:
        w["locks"].append({"key": "odd", "question": "war", "decider": {"person": "ilse"}})

    world = toy(tmp_path, ostmark, ruled(*RULES), peace_rows, no_order_war)
    with pytest.raises(WorldError) as caught:
        compile_world(world, CAMPAIGN, cmp.versions())
    assert any("lock odd" in p and "order" in p for p in caught.value.problems)


# --- Rule 5: a separate peace breaks a pact ----------------------------------------------


def test_a_separate_peace_breaks_the_pact(tmp_path: Path) -> None:
    g = game(tmp_path, ostmark_at_war)
    pact = put_in_force(
        g,
        clause(ClauseType.NO_SEPARATE_PEACE, binds=NORRA, nation=SUDLAND),
        clause(ClauseType.NO_SEPARATE_PEACE, binds=OSTMARK, nation=SUDLAND),
        parties=(NORRA, OSTMARK),
    )
    _, due = accepted_by_tomas(g)
    out = g.walk(day(1), due)
    judged = [(p.agreement_id, p.clause, p.status, p.on) for p in of(out, ev.ClauseJudged)]
    assert judged == [(pact.agreement_id, 0, ClauseStatus.BROKEN, due)]
    assert of(out, ev.RelationshipSet), "the broken clause costs regard"


def test_a_peace_made_together_breaks_no_pact(tmp_path: Path) -> None:
    g = game(tmp_path, ostmark_at_war)
    put_in_force(
        g,
        clause(ClauseType.NO_SEPARATE_PEACE, binds=NORRA, nation=SUDLAND),
        parties=(NORRA, OSTMARK),
    )
    oid = offer(
        g,
        deal(
            ends_war(),
            ends_war(OSTMARK, SUDLAND),
            parties=(NORRA, SUDLAND, OSTMARK),
            wording="A general peace.",
        ),
    )
    answer(g, oid, TOMAS, True)
    answer(g, oid, OLAF, True)
    out = g.walk(day(1), day(12))
    assert len(of(out, ev.WarEnded)) == 2
    assert not of(out, ev.ClauseJudged)


# --- Rule 6: a war ended can be declared again ------------------------------------------


def test_a_war_ended_can_be_declared_again_and_the_record_keeps_who_broke_the_peace(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    _, due = accepted_by_tomas(g)
    g.walk(day(1), due)
    again = due + timedelta(days=3)
    war = War(
        war_id=war_id_for(SUDLAND, NORRA), a=SUDLAND, b=NORRA, since=again, declared_by=SUDLAND
    )
    g.add([ev.WarDeclared(war=war)])
    assert at_war(g.state, NORRA, SUDLAND)
    assert broke_peace(g.state, g.state.wars[war.war_id]) == SUDLAND
    out = g.walk(again, again)
    (broken,) = of(out, ev.ClauseJudged)
    assert broken.status is ClauseStatus.BROKEN and broken.clause == 1


def test_a_war_never_ended_was_broken_by_nobody(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert broke_peace(g.state, g.state.wars[war_id_for(NORRA, SUDLAND)]) is None


# --- Stored shape ---------------------------------------------------------------------


def test_a_war_ended_needs_the_rule_and_a_war_in_force(tmp_path: Path) -> None:
    g = game(tmp_path, rules=("holders", "agreements"))
    with pytest.raises(FoldError, match="peace"):
        g.add([ev.WarEnded(war_id=war_id_for(NORRA, SUDLAND), on=day(1))])
    (tmp_path / "on").mkdir()
    g = game(tmp_path / "on")
    with pytest.raises(FoldError, match="not at war"):
        g.add([ev.WarEnded(war_id=war_id_for(NORRA, OSTMARK), on=day(1))])
    assert Rule.PEACE in g.state.rules
