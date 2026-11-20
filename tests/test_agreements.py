"""Agreements with clauses the rules can check (AGR).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``agreements`` on and a
third power, Ostmark (its leader Olaf), at peace with both. Norra and Sudland are at war.
An offer is filed with ``commit_order`` as one order carrying a ``Deal`` that names its
parties, wording and clauses; each other nation's seat answers it through the answer path
(``process.answered``) before the offer's due day. Clauses of an agreement in force are
judged by ``agreement.judge`` in the day walk.
"""

import itertools
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.ids import EntityId, FeatureId, OrderId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import agreement, groups, process
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.agreement import (
    BREAK_REGARD,
    OFFER_DAYS,
    Agreement,
    ClauseStatus,
)
from revisionist.core.realism.battle import Battle, BattleSide
from revisionist.core.realism.effect import AgreementClause, ClauseType, Deal, Route
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.visibility import Visibility
from revisionist.core.world import WorldFile
from revisionist.engine import catchup, realism_tick, wake
from revisionist.engine.store import MemoryStore
from tests.test_adjacency_moves import START, Logged, entity, seat, toy
from tests.test_territory_model import CAMPAIGN

World = dict[str, Any]
NORRA, SUDLAND, OSTMARK = entity("norra"), entity("sudland"), entity("ostmark")
ILSE, TOMAS, OLAF = seat("ilse"), seat("tomas"), seat("olaf")
LEVY = FeatureId(entity("norra_levy"))
PLAIN, COAST, ISLE = entity("norra_plain"), entity("sudland_coast"), entity("isle")


def day(n: int) -> date:
    return START + timedelta(days=n)


def ostmark(w: World) -> None:
    """A third power with a playable leader, at war with nobody."""
    w["entities"] += [
        {"key": "ostmark", "kind": "polity", "name": "Ostmark"},
        {"key": "olaf", "kind": "person", "name": "Olaf Strand", "parent": "ostmark"},
    ]
    w["cards"].append(
        {
            "person": "olaf",
            "office": "Regent of Ostmark",
            "playable": True,
            "principals": ["ostmark"],
            "horizon_days": 14,
        }
    )
    w["roster"].append(
        {"entity": "olaf", "pitch": "The regent at peace.", "reach": "Ostmark.", "composite": True}
    )


def ruled(*rules: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = ["territories", *rules]

    return change


def broken_moves_public(w: World) -> None:
    """Norra's public sours by 4 at a broken agreement."""
    (norra,) = [n for n in w["groups"] if n["nation"] == "norra"]
    (public,) = [g for g in norra["groups"] if g["key"] == "public"]
    public["moved_by"]["agreement_broken"] = -4


def world(tmp: Path, *changes: Callable[[World], None], rules: Sequence[str] = ()) -> WorldFile:
    on = rules or ("holders", "agreements")
    return toy(tmp, ostmark, ruled(*on), *changes)


def game(
    tmp: Path, *changes: Callable[[World], None], rules: Sequence[str] = (), people: int = 3
) -> Logged:
    return Logged(world(tmp, *changes, rules=rules), *("ilse", "tomas", "olaf")[:people])


def clause(kind: ClauseType, binds: EntityId = NORRA, **fields: Any) -> AgreementClause:
    return AgreementClause(type=kind, binds=binds, **fields)


def deal(
    *clauses: AgreementClause,
    parties: Sequence[EntityId] = (NORRA, SUDLAND),
    wording: str = "Peace on the isle.",
) -> Deal:
    return Deal(
        counterparty=parties[1], parties=tuple(parties), wording=wording, clauses=tuple(clauses)
    )


def file(g: Logged, by: SeatId, *asks: Ask) -> OrderId:
    """``commit_order`` on the game's log: the routed order it lands."""
    store = MemoryStore()
    store.append_all(g.log)
    order = realism_tick.commit_order(store, CAMPAIGN, by, list(asks))
    new = list(store.read(CAMPAIGN))[len(g.log) :]
    g.add([e.payload for e in new])
    return order.order_id


def offer(g: Logged, d: Deal, by: SeatId = ILSE) -> OrderId:
    return file(g, by, Ask(ask="An offer of agreement.", effect=d))


def answer(g: Logged, oid: OrderId, by: SeatId, accept: bool) -> None:
    routed = g.state.routed[oid]
    for i, part in enumerate(routed.parts):
        if process.held_by_another(g.state, routed, part) == by:
            g.add([process.answered(g.state, routed, i, accept)])


def made(g: Logged) -> list[Agreement]:
    return list(g.state.agreements.made.values())


def of(out: Sequence[ev.Event], kind: type) -> list[Any]:
    return [e.payload for e in out if isinstance(e.payload, kind)]


def in_force(
    g: Logged,
    *clauses: AgreementClause,
    parties: Sequence[EntityId] = (NORRA, SUDLAND),
    public: bool = False,
) -> Agreement:
    """An agreement put in force directly, as a world or a conference makes one."""
    statuses = tuple(
        ClauseStatus.UNCHECKED
        if c.type in (ClauseType.UNCHECKED, ClauseType.VOTE)
        else ClauseStatus.STANDING
        for c in clauses
    )
    x = Agreement(
        agreement_id=f"agr-{len(made(g))}",
        version=agreement.version(parties, "", clauses),
        parties=tuple(parties),
        clauses=tuple(clauses),
        made=START,
        statuses=statuses,
        published=START if public else None,
    )
    g.add([ev.AgreementMade(agreement=x)])
    return g.state.agreements.made[x.agreement_id]


def judged(g: Logged, first: date, last: date, today: Sequence[ev.Payload] = ()) -> list[Any]:
    """``agreement.judge`` for each day, folded in turn: what it landed."""
    out: list[ev.Payload] = []
    n = first
    while n <= last:
        found = agreement.judge(g.state, n, today)
        g.add(found)
        out += found
        n += timedelta(days=1)
    return out


def verdicts(out: Sequence[ev.Payload]) -> list[tuple[int, ClauseStatus, date]]:
    return [(p.clause, p.status, p.on) for p in out if isinstance(p, ev.ClauseJudged)]


def regard(g: Logged, a: str, b: str) -> int | None:
    x, y = entity(a), entity(b)
    found = [r for r in g.state.relationships.values() if {r.a, r.b} == {x, y}]
    return found[0].disposition if found else None


# --- Rule 1 and 2: parties, wording and typed clauses -------------------------------


@pytest.mark.parametrize(
    ("kind", "fields", "missing"),
    [
        (ClauseType.PLACE, {"on": START}, "force"),
        (ClauseType.KEEP_OUT, {}, "area"),
        (ClauseType.NO_WAR, {}, "nation"),
        (ClauseType.NO_ATTACK, {}, "nation"),
        (ClauseType.DEFEND, {"nation": SUDLAND}, "days"),
        (ClauseType.FORM, {"on": START}, "form"),
        (ClauseType.AID, {"nation": SUDLAND}, "share"),
        (ClauseType.VOTE, {}, "text"),
        (ClauseType.UNCHECKED, {}, "text"),
    ],
)
def test_each_clause_type_names_what_it_needs(
    kind: ClauseType, fields: dict[str, Any], missing: str
) -> None:
    with pytest.raises(ValueError, match=missing):
        AgreementClause(type=kind, binds=NORRA, **fields)


def test_a_place_clause_names_an_area_or_a_region_not_both() -> None:
    with pytest.raises(ValueError, match="area or a region"):
        clause(ClauseType.PLACE, force=LEVY, on=START)
    with pytest.raises(ValueError, match="area or a region"):
        clause(ClauseType.PLACE, force=LEVY, on=START, area=PLAIN, region="north")


def test_an_agreement_names_two_nations_and_binds_only_its_parties() -> None:
    with pytest.raises(ValueError, match="two or more"):
        Deal(counterparty=SUDLAND, parties=(SUDLAND,), wording="x")
    with pytest.raises(ValueError, match="binds one of the parties"):
        deal(clause(ClauseType.NO_WAR, binds=OSTMARK, nation=SUDLAND))
    with pytest.raises(ValueError):
        Deal(counterparty=SUDLAND, parties=tuple(entity(f"n{n}") for n in range(9)), wording="x")
    plain = Deal(counterparty=SUDLAND, offer=("grain",))
    assert plain.parties == () and plain.clauses == ()


# --- Rule 3: wording that fits no type is kept and never judged ----------------------


def test_wording_that_fits_no_type_is_kept_and_marked_unchecked(tmp_path: Path) -> None:
    g = game(tmp_path)
    words = clause(ClauseType.UNCHECKED, text="Friendship for ever.")
    vote = clause(ClauseType.VOTE, text="the_charter")
    x = in_force(g, words, vote)
    assert x.statuses == (ClauseStatus.UNCHECKED, ClauseStatus.UNCHECKED)
    assert verdicts(judged(g, START, day(30))) == []
    assert "Friendship for ever." in agreement.render_clause(g.state, words)


# --- Rule 4 and 5: an offer, its answers and its consent ------------------------------


def test_an_offer_puts_one_request_to_each_other_nations_leader(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = offer(
        g, deal(clause(ClauseType.NO_WAR, nation=OSTMARK), parties=(NORRA, SUDLAND, OSTMARK))
    )
    parts = g.state.routed[oid].parts
    assert [p.route for p in parts] == [Route.INFLUENCE, Route.INFLUENCE]
    assert [p.target for p in parts] == [entity("tomas"), entity("olaf")]
    assert [p.effect.counterparty for p in parts] == [SUDLAND, OSTMARK]  # type: ignore[union-attr]
    due = process.request_due(g.state, g.state.routed[oid], 0)
    assert due is not None and due >= START + timedelta(days=OFFER_DAYS)


def test_each_named_nations_seat_gets_a_paper_with_the_terms_and_an_answer_day(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    oid = offer(g, deal(clause(ClauseType.KEEP_OUT, area=ISLE)))
    out = g.walk(day(1), day(1))
    (paper,) = [p.document for p in of(out, ev.DocumentIssued)]
    assert paper.scope.known_by == frozenset({TOMAS})
    text = " ".join(str(b.value) for b in paper.body)
    assert "Norra: no piece enters The Isle, at all times." in text
    assert "Answer by" in [b.label for b in paper.body]
    assert g.state.agreements.offers[oid].parties == (NORRA, SUDLAND)


def test_both_accepting_the_same_version_makes_the_agreement_on_the_due_day(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    oid = offer(g, deal(clause(ClauseType.KEEP_OUT, area=ISLE)))
    due = process.offer_due(g.state, g.state.routed[oid])
    answer(g, oid, TOMAS, True)
    g.walk(day(1), due - timedelta(days=1))
    assert made(g) == []
    out = g.walk(due, due)
    (x,) = of(out, ev.AgreementMade)
    assert x.agreement.parties == (NORRA, SUDLAND) and x.agreement.made == due
    assert x.agreement.version == g.state.agreements.offers[oid].version
    titles = [p.document.title for p in of(out, ev.DocumentIssued)]
    assert titles.count("An agreement is in force") == 2


def test_an_accepted_offer_lands_no_deal_of_the_old_kind(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = offer(g, deal(clause(ClauseType.KEEP_OUT, area=ISLE)))
    answer(g, oid, TOMAS, True)
    out = g.walk(day(1), day(12))
    assert not [f for f in of(out, ev.FactAsserted) if "deal" in f.fact.predicate]
    assert regard(g, "ilse", "tomas") is None
    assert all(p.applied is not None for p in g.state.routed[oid].parts)


@pytest.mark.parametrize("answered", [False, None])
def test_a_decline_or_no_answer_lapses_the_offer_with_no_obligation(
    tmp_path: Path, answered: bool | None
) -> None:
    g = game(tmp_path)
    oid = offer(g, deal(clause(ClauseType.KEEP_OUT, area=ISLE)))
    if answered is not None:
        answer(g, oid, TOMAS, answered)
    out = g.walk(day(1), day(12))
    assert made(g) == [] and not of(out, ev.ClauseJudged)
    titles = [p.document.title for p in of(out, ev.DocumentIssued)]
    assert titles.count("An offer of agreement lapsed") == 2
    (decided,) = of(out, ev.InfluenceDecided)
    assert decided.accepted is False and decided.reason == "Tomas Brand did not accept the offer."


def test_the_card_never_answers_an_offer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    g = game(tmp_path)
    monkeypatch.setattr(process, "decides", lambda *a: (True, "Agreed."))
    offer(g, deal(clause(ClauseType.KEEP_OUT, area=ISLE)))
    g.walk(day(1), day(12))
    assert made(g) == []


def three_way(g: Logged, n: int = 1) -> OrderId:
    words = "Peace on the isle." if n == 1 else f"Peace on the isle, take {n}."
    return offer(
        g,
        deal(
            clause(ClauseType.KEEP_OUT, area=ISLE), parties=(NORRA, SUDLAND, OSTMARK), wording=words
        ),
    )


@pytest.mark.parametrize("order", list(itertools.permutations([(TOMAS, 1), (OLAF, 2)])))
def test_a_three_nation_offer_binds_only_when_all_accept_in_any_order(
    tmp_path: Path, order: tuple[tuple[SeatId, int], ...]
) -> None:
    g = game(tmp_path)
    oid = three_way(g)
    due = process.offer_due(g.state, g.state.routed[oid])
    for who, n in order:
        g.walk(day(n), day(n))
        answer(g, oid, who, True)
        if who != order[-1][0]:
            assert made(g) == []
    g.walk(day(3), due)
    (x,) = made(g)
    assert x.parties == (NORRA, SUDLAND, OSTMARK)


@pytest.mark.parametrize("silent", [TOMAS, OLAF])
@pytest.mark.parametrize("declines", [True, False])
def test_one_nation_declining_or_silent_binds_no_one(
    tmp_path: Path, silent: SeatId, declines: bool
) -> None:
    g = game(tmp_path)
    oid = three_way(g)
    other = OLAF if silent == TOMAS else TOMAS
    answer(g, oid, other, True)
    if declines:
        answer(g, oid, silent, False)
    out = g.walk(day(1), day(20))
    assert made(g) == []
    assert not of(out, ev.ClauseJudged) and not of(out, ev.RelationshipSet)


def test_a_changed_clause_is_a_new_version_and_old_acceptances_do_not_carry_over(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    first = three_way(g)
    answer(g, first, TOMAS, True)
    second = three_way(g, 2)
    answer(g, second, OLAF, True)
    g.walk(day(1), day(20))
    one, two = g.state.agreements.offers[first], g.state.agreements.offers[second]
    assert one.version != two.version
    assert made(g) == []
    g.send("ilse", "norra_levy", "isle")
    out = g.walk(day(21), day(40))
    assert not of(out, ev.ClauseJudged) and regard(g, "ilse", "tomas") is None


def test_the_aide_never_offers_nor_accepts(tmp_path: Path) -> None:
    g = game(tmp_path)
    d = deal(clause(ClauseType.KEEP_OUT, area=ISLE))
    kept = wake._allowed(g.state, ILSE, (Ask(ask="An offer.", effect=d),))
    assert kept == ()


# --- Filing refusals ----------------------------------------------------------------


def test_an_offer_is_refused_with_the_rule_off(tmp_path: Path) -> None:
    g = game(tmp_path, rules=("holders",))
    with pytest.raises(ValueError, match="not part of this game"):
        offer(g, deal(clause(ClauseType.KEEP_OUT, area=ISLE)))


def test_an_offer_naming_a_nation_no_seat_holds_is_refused(tmp_path: Path) -> None:
    g = game(tmp_path, people=2)
    with pytest.raises(ValueError, match="No one answers for Ostmark"):
        offer(g, deal(parties=(NORRA, OSTMARK)))


def test_an_offer_must_name_the_offering_nation(tmp_path: Path) -> None:
    g = game(tmp_path)
    with pytest.raises(ValueError, match="Your own nation"):
        offer(g, deal(parties=(SUDLAND, OSTMARK)))


def test_an_offer_goes_alone_in_its_order(tmp_path: Path) -> None:
    g = game(tmp_path)
    with pytest.raises(ValueError, match="order of its own"):
        file(g, ILSE, Ask(ask="offer", effect=deal()), Ask(ask="and more", target=entity("tomas")))


def test_a_clause_naming_what_the_world_lacks_is_refused(tmp_path: Path) -> None:
    g = game(tmp_path)
    with pytest.raises(ValueError, match="region"):
        offer(g, deal(clause(ClauseType.PLACE, force=LEVY, on=day(5), region="atlantis")))


# --- Rule 2 and 7: each clause type judged on its date from the state ----------------


def test_a_dated_place_clause_is_judged_on_its_date_and_not_a_day_early(tmp_path: Path) -> None:
    g = game(tmp_path)
    in_force(g, clause(ClauseType.PLACE, force=LEVY, area=PLAIN, on=day(5)))
    assert verdicts(judged(g, START, day(4))) == []
    assert verdicts(judged(g, day(5), day(9))) == [(0, ClauseStatus.KEPT, day(5))]


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({"area": COAST}, ClauseStatus.BROKEN),
        ({"area": COAST, "present": False}, ClauseStatus.KEPT),
        ({"region": "north"}, ClauseStatus.KEPT),
        ({"region": "south"}, ClauseStatus.BROKEN),
    ],
)
def test_a_place_clause_reads_where_the_piece_stands(
    tmp_path: Path, fields: dict[str, Any], status: ClauseStatus
) -> None:
    g = game(tmp_path)
    in_force(g, clause(ClauseType.PLACE, force=LEVY, on=day(1), **fields))
    assert verdicts(judged(g, day(1), day(1))) == [(0, status, day(1))]


def test_a_keep_out_clause_is_broken_the_day_a_piece_enters_and_nothing_stops_it(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    in_force(g, clause(ClauseType.KEEP_OUT, area=entity("norra_hills")))
    g.send("ilse", "norra_levy", "norra_hills")
    out = g.walk(day(1), day(12))
    steps = of(out, ev.PieceStepped)
    assert steps and steps[0].entered == entity("norra_hills")
    (found,) = of(out, ev.ClauseJudged)
    assert found.status is ClauseStatus.BROKEN and found.on == steps[0].on


def test_a_no_war_clause_is_broken_by_a_new_declaration(tmp_path: Path) -> None:
    g = game(tmp_path)
    in_force(g, clause(ClauseType.NO_WAR, nation=OSTMARK), parties=(NORRA, OSTMARK))
    assert verdicts(judged(g, START, day(2))) == []
    war = War(
        war_id=war_id_for(NORRA, OSTMARK),
        a=NORRA,
        b=OSTMARK,
        since=day(3),
        declared_by=entity("ilse"),
    )
    g.add([ev.WarDeclared(war=war)])
    assert verdicts(judged(g, day(3), day(3))) == [(0, ClauseStatus.BROKEN, day(3))]


def battle_opened(attacker: EntityId, defender: EntityId, on: date) -> ev.BattleOpened:
    return ev.BattleOpened(
        battle=Battle(
            area=COAST,
            opened=on,
            attacker=BattleSide(nation=attacker, pieces=(LEVY,), brought=2),
            defender=BattleSide(
                nation=defender, pieces=(FeatureId(entity("sudland_levy")),), brought=2
            ),
        ),
        on=on,
    )


def test_a_no_attack_clause_is_broken_by_a_battle_the_party_opens(tmp_path: Path) -> None:
    g = game(tmp_path)
    in_force(g, clause(ClauseType.NO_ATTACK, nation=SUDLAND))
    assert verdicts(judged(g, day(1), day(1), [battle_opened(SUDLAND, NORRA, day(1))])) == []
    found = verdicts(judged(g, day(2), day(2), [battle_opened(NORRA, SUDLAND, day(2))]))
    assert found == [(0, ClauseStatus.BROKEN, day(2))]


def defend(g: Logged) -> Agreement:
    return in_force(
        g,
        clause(ClauseType.DEFEND, binds=OSTMARK, nation=SUDLAND, days=3),
        parties=(SUDLAND, OSTMARK),
    )


def test_a_defence_clause_is_called_by_an_attack_and_broken_when_no_war_follows(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    defend(g)
    called = judged(g, day(1), day(1), [battle_opened(NORRA, SUDLAND, day(1))])
    (call,) = [p for p in called if isinstance(p, ev.ClauseJudged)]
    assert call.status is ClauseStatus.CALLED and call.against == NORRA and call.due == day(4)
    assert verdicts(judged(g, day(2), day(4))) == []
    assert verdicts(judged(g, day(5), day(5))) == [(0, ClauseStatus.BROKEN, day(5))]


def test_a_defence_clause_called_is_kept_by_a_declaration_in_time(tmp_path: Path) -> None:
    g = game(tmp_path)
    x = defend(g)
    judged(g, day(1), day(1), [battle_opened(NORRA, SUDLAND, day(1))])
    war = War(
        war_id=war_id_for(OSTMARK, NORRA), a=OSTMARK, b=NORRA, since=day(2), declared_by=OSTMARK
    )
    g.add([ev.WarDeclared(war=war)])
    assert verdicts(judged(g, day(2), day(2))) == [(0, ClauseStatus.KEPT, day(2))]
    assert g.state.agreements.made[x.agreement_id].statuses == (ClauseStatus.STANDING,)
    assert verdicts(judged(g, day(3), day(9))) == []


def aid_form(w: World) -> None:
    w["pipelines"] = [
        {
            "key": "war_office",
            "name": "The war office",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        }
    ]
    for card in w["cards"]:
        card["pipelines"] = ["war_office"]
        card["levers"] = [
            {
                "name": "send_aid",
                "pipeline": "war_office",
                "resolver": "production",
                "params": [
                    {"name": "to", "kind": "enum", "choices": ["sudland", "ostmark"]},
                    {"name": "share", "kind": "int", "lo": 1, "hi": 100},
                ],
            },
            {"name": "levy_act", "pipeline": "war_office", "resolver": "production", "params": []},
        ]


def enact(g: Logged, lever: str, on: date, **params: Any) -> None:
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "agr-order", lever, on.isoformat())),
        issuer=ILSE,
        lever=lever,
        pipeline=next(iter(g.state.pipelines)),
        params=params,
        filed=on,
    )
    g.add(
        [
            ev.OrderDrafted(order=order),
            ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
        ]
    )


@pytest.mark.parametrize(("share", "status"), [(20, ClauseStatus.KEPT), (10, ClauseStatus.BROKEN)])
def test_an_aid_clause_reads_the_share_the_party_sends(
    tmp_path: Path, share: int, status: ClauseStatus
) -> None:
    g = game(tmp_path, aid_form)
    in_force(
        g, clause(ClauseType.AID, nation=OSTMARK, share=15, on=day(5)), parties=(NORRA, OSTMARK)
    )
    enact(g, "send_aid", day(1), to="ostmark", share=share)
    assert verdicts(judged(g, day(5), day(5))) == [(0, status, day(5))]


@pytest.mark.parametrize(("when", "status"), [(3, ClauseStatus.KEPT), (6, ClauseStatus.BROKEN)])
def test_a_form_clause_is_kept_when_the_form_is_enacted_by_its_date(
    tmp_path: Path, when: int, status: ClauseStatus
) -> None:
    g = game(tmp_path, aid_form)
    in_force(g, clause(ClauseType.FORM, form="levy_act", on=day(5)))
    enact(g, "levy_act", day(when))
    assert verdicts(judged(g, day(5), day(5))) == [(0, status, day(5))]


def test_each_judgement_reaches_every_partys_seats_as_a_paper(tmp_path: Path) -> None:
    g = game(tmp_path)
    in_force(g, clause(ClauseType.PLACE, force=LEVY, area=PLAIN, on=day(1)))
    out = judged(g, day(1), day(1))
    papers = [p.document for p in out if isinstance(p, ev.DocumentIssued)]
    assert {d.scope.known_by for d in papers} == {frozenset({ILSE}), frozenset({TOMAS})}
    assert all(d.title == "A clause of an agreement was kept" for d in papers)


# --- Rule 8: what a broken clause costs ---------------------------------------------


def test_a_broken_clause_costs_regard_between_the_leaders(tmp_path: Path) -> None:
    g = game(tmp_path)
    in_force(g, clause(ClauseType.PLACE, force=LEVY, area=COAST, on=day(1)))
    judged(g, day(1), day(1))
    assert regard(g, "ilse", "tomas") == BREAK_REGARD


@pytest.mark.parametrize("public", [True, False])
def test_a_public_agreement_broken_moves_the_breakers_groups(tmp_path: Path, public: bool) -> None:
    g = game(tmp_path, broken_moves_public, rules=("holders", "economy", "groups", "agreements"))
    was = groups.support(g.state, NORRA, "public")
    in_force(g, clause(ClauseType.PLACE, force=LEVY, area=COAST, on=day(1)), public=public)
    out = judged(g, day(1), day(1))
    moved = [p for p in out if isinstance(p, ev.GroupMoved)]
    if public:
        assert [(m.group, m.change) for m in moved] == [("public", -4)]
        assert groups.support(g.state, NORRA, "public") == (was or 0) - 4
    else:
        assert moved == []


def test_a_kept_clause_costs_nothing(tmp_path: Path) -> None:
    g = game(tmp_path)
    in_force(g, clause(ClauseType.PLACE, force=LEVY, area=PLAIN, on=day(1)))
    judged(g, day(1), day(3))
    assert regard(g, "ilse", "tomas") is None


# --- Rule 9: seen by its parties only, until published --------------------------------


def test_a_private_agreement_is_in_no_third_seats_view(tmp_path: Path) -> None:
    g = game(tmp_path)
    x = in_force(g, clause(ClauseType.KEEP_OUT, area=ISLE))
    assert x.agreement_id in project(g.state, ILSE).agreements.made
    assert x.agreement_id in project(g.state, TOMAS).agreements.made
    assert project(g.state, OLAF).agreements.made == {}


def test_an_offer_is_in_no_third_seats_view_nor_feed(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = offer(g, deal(clause(ClauseType.KEEP_OUT, area=ISLE)))
    answer(g, oid, TOMAS, True)
    g.walk(day(1), day(12))
    assert project(g.state, OLAF).agreements == agreement.Agreements()
    kinds = {"agreement_offered", "agreement_made", "clause_judged"}
    theirs = catchup.feed(g.state, g.log, OLAF, 0, 10)
    assert not [f for f in theirs if f.event.kind in kinds]
    mine = catchup.feed(g.state, g.log, TOMAS, 0, 10)
    assert {f.event.kind for f in mine} >= {"agreement_offered", "agreement_made"}


def test_a_party_publishes_an_agreement_by_order(tmp_path: Path) -> None:
    g = game(tmp_path)
    x = in_force(g, clause(ClauseType.KEEP_OUT, area=ISLE))
    oid = file(
        g, TOMAS, Ask(ask="Publish it.", effect=Deal(counterparty=NORRA, publish=x.agreement_id))
    )
    with pytest.raises(ValueError, match="no such agreement"):
        file(
            g, OLAF, Ask(ask="Publish it.", effect=Deal(counterparty=NORRA, publish=x.agreement_id))
        )
    out = g.walk(day(1), day(3))
    (pub,) = of(out, ev.AgreementPublished)
    assert pub.by == SUDLAND
    assert x.agreement_id in project(g.state, OLAF).agreements.made
    assert g.state.routed[oid].parts[0].applied is not None
    (published,) = [e for e in out if e.kind == "agreement_published"]
    assert published.scope.visibility is Visibility.PUBLIC


def test_clause_judgements_are_sealed_to_the_parties_until_published(tmp_path: Path) -> None:
    g = game(tmp_path)
    in_force(g, clause(ClauseType.PLACE, force=LEVY, area=PLAIN, on=day(1)))
    out = g.walk(day(1), day(1))
    (j,) = [e for e in out if e.kind == "clause_judged"]
    assert j.scope.known_by == frozenset({ILSE, TOMAS})


# --- Rule 11: gated ------------------------------------------------------------------


def test_with_the_rule_off_nothing_is_judged_and_the_fold_refuses(tmp_path: Path) -> None:
    g = game(tmp_path, rules=("holders",))
    x = Agreement(agreement_id="a", version="v", parties=(NORRA, SUDLAND), made=START, statuses=())
    with pytest.raises(FoldError, match="agreements rule"):
        g.add([ev.AgreementMade(agreement=x)])
    assert agreement.judge(g.state, day(1), []) == []
    assert agreement.offers_due(g.state, day(1)) == []


def test_the_fold_refuses_an_agreement_made_from_another_version(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = offer(g, deal(clause(ClauseType.KEEP_OUT, area=ISLE)))
    g.walk(day(1), day(1))
    x = Agreement(
        agreement_id="a", version="other", parties=(NORRA, SUDLAND), made=day(1), offer_id=oid
    )
    with pytest.raises(FoldError, match="version"):
        g.add([ev.AgreementMade(agreement=x)])


# --- Rule 12: the terms in fixed words ----------------------------------------------


def test_the_terms_render_every_material_term_in_fixed_words(tmp_path: Path) -> None:
    g = game(tmp_path)
    x = in_force(
        g,
        clause(ClauseType.AID, nation=OSTMARK, share=15, on=date(1900, 5, 1)),
        clause(ClauseType.DEFEND, binds=OSTMARK, nation=NORRA, days=7),
        parties=(NORRA, OSTMARK),
    )
    assert agreement.render_terms(g.state, x) == (
        "Parties: Norra, Ostmark. "
        "Clause 1: Norra: an aid share of at least 15% to Ostmark, by 1 May 1900. "
        "Clause 2: Ostmark: war declared within 7 days on any nation that newly attacks "
        "Norra, at all times."
    )


# --- Invariant 8: an offer to an absent seat lapses with no change ---------------------


def test_an_offer_with_clauses_to_an_absent_seat_lapses_with_no_change(tmp_path: Path) -> None:
    g = game(tmp_path)
    before = (dict(g.state.relationships), g.state.groups)
    offer(
        g, deal(clause(ClauseType.KEEP_OUT, area=ISLE), clause(ClauseType.NO_WAR, nation=OSTMARK))
    )
    g.walk(day(1), day(20))
    assert made(g) == []
    assert (dict(g.state.relationships), g.state.groups) == before
