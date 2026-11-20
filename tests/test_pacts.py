"""Pacts in force at the start (PCT).

A world may carry ``pacts``: each names its parties, its wording, its clauses, whether it
is public, and its source. With ``agreements`` on, compile makes each one an agreement in
force from the first day, through AGR's ``agreement_made``, with no offer; its clauses
are judged and a breach costed exactly as any agreement's; a clause the typed list
cannot express is kept as wording and marked unchecked. A public pact is in every
seat's view; a secret one only in its parties'.

The toy world (``tests/worlds/territory-toy.yaml``) is played as the agreement tests
play it: ``agreements`` on and a third power, Ostmark, at peace with both.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import agreement, groups
from revisionist.core.realism.agreement import BREAK_REGARD, ClauseStatus
from revisionist.core.realism.effect import AgreementClause, ClauseType
from revisionist.core.visibility import Visibility
from revisionist.core.world_compile import WorldError, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup
from tests.test_adjacency_moves import START, Logged, entity, fold
from tests.test_agreements import (
    ILSE,
    NORRA,
    OLAF,
    OSTMARK,
    TOMAS,
    World,
    broken_moves_public,
    day,
    regard,
    world,
)
from tests.test_territory_model import CAMPAIGN, created, refused

PACT_ID = derived_id(CAMPAIGN, "pact", "northern_pact")


def seat_of(person: str) -> SeatId:
    """The seat the engine gives a person it seats: named for the person's id."""
    return SeatId(derived_id(CAMPAIGN, "seat", entity(person)))


def pact(
    *clauses: dict[str, Any],
    key: str = "northern_pact",
    parties: tuple[str, ...] = ("norra", "ostmark"),
    public: bool = False,
    wording: str = "Neither shall raise a hand against the other.",
    **more: Any,
) -> Callable[[World], None]:
    """A change that adds one pact to the world."""

    def change(w: World) -> None:
        w.setdefault("pacts", []).append(
            {
                "key": key,
                "name": "The Northern Pact",
                "parties": list(parties),
                "wording": wording,
                "clauses": list(clauses),
                "public": public,
                "source": "toy",
                **more,
            }
        )

    return change


NO_ATTACK = {"type": "no_attack", "binds": "norra", "nation": "ostmark"}


def game(tmp: Path, *changes: Callable[[World], None], rules: tuple[str, ...] = ()) -> Logged:
    return Logged(world(tmp, *changes, rules=rules), "ilse", "tomas", "olaf")


# --- Rule 1: compile makes each pact an agreement in force from the first day ----------


def test_a_pact_is_an_agreement_in_force_from_the_first_day(tmp_path: Path) -> None:
    g = game(tmp_path, pact(NO_ATTACK))
    assert g.state.agreements.offers == {}
    x = g.state.agreements.made[PACT_ID]
    assert x.parties == (NORRA, OSTMARK)
    assert x.made == START
    assert x.offer_id is None
    assert x.clauses == (AgreementClause(type=ClauseType.NO_ATTACK, binds=NORRA, nation=OSTMARK),)
    assert x.statuses == (ClauseStatus.STANDING,)
    assert x.wording == "The Northern Pact. Neither shall raise a hand against the other."
    assert x.version == agreement.version(x.parties, x.wording, x.clauses)


def test_a_pact_is_compiled_as_an_agreement_made_never_as_an_offer(tmp_path: Path) -> None:
    events, _ = created(world(tmp_path, pact(NO_ATTACK)))
    kinds = [e.kind for e in events]
    assert kinds.count("agreement_made") == 1
    assert "agreement_offered" not in kinds
    assert all(e.tick == 0 for e in events)


def test_each_pact_compiles_in_file_order(tmp_path: Path) -> None:
    second = pact(
        {"type": "no_war", "binds": "sudland", "nation": "ostmark"},
        key="southern_pact",
        parties=("sudland", "ostmark"),
    )
    events, state = created(world(tmp_path, pact(NO_ATTACK), second))
    made = [e.payload.agreement.agreement_id for e in events if e.kind == "agreement_made"]  # type: ignore[union-attr]
    assert made == [PACT_ID, derived_id(CAMPAIGN, "pact", "southern_pact")]
    assert set(state.agreements.made) == set(made)


def test_compile_refuses_pacts_with_the_agreements_rule_off(tmp_path: Path) -> None:
    w = world(tmp_path, pact(NO_ATTACK), rules=("holders",))
    assert "pacts: needs the agreements rule" in refused(w)


def test_a_world_with_no_pacts_compiles_as_before(tmp_path: Path) -> None:
    plain, _ = created(world(tmp_path))
    assert "agreement_made" not in {e.kind for e in plain}


# --- Keeps: a public pact is seen by every seat, a secret one by its parties -----------


def test_a_secret_pact_is_seen_by_its_parties_only(tmp_path: Path) -> None:
    g = game(tmp_path, pact(NO_ATTACK))
    assert PACT_ID in project(g.state, ILSE).agreements.made
    assert PACT_ID in project(g.state, OLAF).agreements.made
    assert project(g.state, TOMAS).agreements.made == {}
    assert not [
        f for f in catchup.feed(g.state, g.log, TOMAS, 0, 10) if f.event.kind == "agreement_made"
    ]


def test_a_secret_pact_is_sealed_to_its_parties_nations_at_compile(tmp_path: Path) -> None:
    """With no seats declared, the scope holds the seat each party's person takes when
    seated (the engine's own seat name for a person), and nobody else's."""
    events, _ = created(world(tmp_path, pact(NO_ATTACK)))
    (made,) = [e for e in events if e.kind == "agreement_made"]
    assert made.scope.visibility is Visibility.RESTRICTED
    assert seat_of("ilse") in made.scope.known_by
    assert seat_of("olaf") in made.scope.known_by
    assert seat_of("tomas") not in made.scope.known_by


def test_a_secret_pact_reaches_its_parties_catch_up_feed(tmp_path: Path) -> None:
    events, _ = created(world(tmp_path, pact(NO_ATTACK)))
    state = fold(
        replay(events),
        [ev.CharacterClaimed(seat_id=seat_of(p), entity_id=entity(p)) for p in ("ilse", "tomas")],
    )
    made = [
        f
        for f in catchup.feed(state, events, seat_of("ilse"), 0, 10)
        if f.event.kind == "agreement_made"
    ]
    assert made
    assert not [
        f
        for f in catchup.feed(state, events, seat_of("tomas"), 0, 10)
        if f.event.kind == "agreement_made"
    ]


def test_a_party_with_no_person_still_gets_a_scope_of_its_own(tmp_path: Path) -> None:
    def bare(w: World) -> None:
        w["entities"].append({"key": "wendmark", "kind": "polity", "name": "Wendmark"})

    events, _ = created(world(tmp_path, bare, pact(NO_ATTACK, parties=("norra", "wendmark"))))
    (made,) = [e for e in events if e.kind == "agreement_made"]
    assert SeatId(derived_id(CAMPAIGN, "nation-seats", entity("wendmark"))) in made.scope.known_by


def test_a_secret_pact_is_sealed_to_the_seats_the_world_gives_its_parties(
    tmp_path: Path,
) -> None:
    def seats(w: World) -> None:
        w["seats"] = [
            {"key": "ilse_seat", "kind": "player", "name": "Ilse's seat", "embodies": "ilse"},
            {"key": "tomas_seat", "kind": "player", "name": "Tomas's seat", "embodies": "tomas"},
        ]

    events, _ = created(world(tmp_path, seats, pact(NO_ATTACK)))
    (made,) = [e for e in events if e.kind == "agreement_made"]
    assert SeatId(derived_id(CAMPAIGN, "seat", "ilse_seat")) in made.scope.known_by
    assert SeatId(derived_id(CAMPAIGN, "seat", "tomas_seat")) not in made.scope.known_by
    assert seat_of("olaf") in made.scope.known_by


def test_a_public_pact_is_seen_by_every_seat(tmp_path: Path) -> None:
    g = game(tmp_path, pact(NO_ATTACK, public=True))
    for s in (ILSE, TOMAS, OLAF):
        assert PACT_ID in project(g.state, s).agreements.made
    assert g.state.agreements.made[PACT_ID].published == START
    (made,) = [e for e in g.log if e.kind == "agreement_made"]
    assert made.scope.visibility is Visibility.PUBLIC
    assert [
        f for f in catchup.feed(g.state, g.log, TOMAS, 0, 10) if f.event.kind == "agreement_made"
    ]


# --- Rule 2: judged and costed exactly as any agreement's ------------------------------


def levy_on_the_coast(when: int = 1) -> dict[str, Any]:
    return {
        "type": "place",
        "binds": "norra",
        "force": "norra_levy",
        "area": "sudland_coast",
        "on": day(when),
    }


def test_a_pact_clause_is_judged_on_its_day_in_the_day_walk(tmp_path: Path) -> None:
    g = game(tmp_path, pact(levy_on_the_coast(2), parties=("norra", "sudland")))
    assert [e for e in g.walk(day(1), day(1)) if e.kind == "clause_judged"] == []
    out = g.walk(day(2), day(2))
    (j,) = [e.payload for e in out if isinstance(e.payload, ev.ClauseJudged)]
    assert (j.agreement_id, j.clause, j.status, j.on) == (PACT_ID, 0, ClauseStatus.BROKEN, day(2))
    papers = [e.payload.document for e in out if isinstance(e.payload, ev.DocumentIssued)]
    assert {d.scope.known_by for d in papers if d.title.startswith("A clause")} == {
        frozenset({ILSE}),
        frozenset({TOMAS}),
    }


def test_a_broken_pact_clause_costs_regard_between_the_leaders(tmp_path: Path) -> None:
    g = game(tmp_path, pact(levy_on_the_coast(), parties=("norra", "sudland")))
    g.walk(day(1), day(1))
    assert regard(g, "ilse", "tomas") == BREAK_REGARD


def test_a_kept_pact_clause_costs_nothing(tmp_path: Path) -> None:
    kept = {
        "type": "place",
        "binds": "norra",
        "force": "norra_levy",
        "area": "norra_plain",
        "on": day(1),
    }
    g = game(tmp_path, pact(kept, parties=("norra", "sudland")))
    out = g.walk(day(1), day(1))
    (j,) = [e.payload for e in out if isinstance(e.payload, ev.ClauseJudged)]
    assert j.status is ClauseStatus.KEPT
    assert regard(g, "ilse", "tomas") is None


@pytest.mark.parametrize("public", [True, False])
def test_a_public_pact_broken_moves_the_breakers_groups(tmp_path: Path, public: bool) -> None:
    g = game(
        tmp_path,
        broken_moves_public,
        pact(levy_on_the_coast(), parties=("norra", "sudland"), public=public),
        rules=("holders", "economy", "groups", "agreements"),
    )
    was = groups.support(g.state, NORRA, "public")
    out = g.walk(day(1), day(1))
    moved = [e.payload for e in out if isinstance(e.payload, ev.GroupMoved)]
    mine = [(m.group, m.change) for m in moved if m.polity == NORRA and m.change == -4]
    if public:
        assert mine == [("public", -4)]
        assert groups.support(g.state, NORRA, "public") is not None
        assert was is not None
    else:
        assert mine == []


def test_a_pact_in_force_is_judged_with_the_offered_ones(tmp_path: Path) -> None:
    g = game(tmp_path, pact(levy_on_the_coast(), parties=("norra", "sudland")))
    found = agreement.judge(g.state, day(1), [])
    assert [p.agreement_id for p in found if isinstance(p, ev.ClauseJudged)] == [PACT_ID]


# --- Rule 3: a clause the list cannot express is kept as wording, unchecked -------------


def test_a_clause_the_list_cannot_express_is_kept_as_wording_and_never_judged(
    tmp_path: Path,
) -> None:
    peace = {"binds": "norra", "text": "No separate peace with the common enemy."}
    g = game(tmp_path, pact(peace, NO_ATTACK))
    x = g.state.agreements.made[PACT_ID]
    assert x.clauses[0] == AgreementClause(
        type=ClauseType.UNCHECKED, binds=NORRA, text="No separate peace with the common enemy."
    )
    assert x.statuses == (ClauseStatus.UNCHECKED, ClauseStatus.STANDING)
    out = g.walk(day(1), day(5))
    assert [
        e for e in out if isinstance(e.payload, ev.ClauseJudged) and e.payload.clause == 0
    ] == []
    assert "(not checked by the rules)" in agreement.render_terms(g.state, x)


# --- What compile refuses --------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (pact(NO_ATTACK, parties=("norra",)), "pact northern_pact: names at least two nations"),
        (pact(NO_ATTACK, parties=("norra", "norra")), "pact northern_pact: names a nation twice"),
        (pact(NO_ATTACK, parties=("norra", "ilse")), "pact northern_pact: ilse is not a polity"),
        (
            pact(NO_ATTACK, parties=("norra", "nowhere")),
            "pact northern_pact: unknown entity nowhere",
        ),
        (
            pact({"type": "no_attack", "binds": "sudland", "nation": "ostmark"}),
            "pact northern_pact: clause 1 binds sudland, which is not a party",
        ),
        (
            pact({"type": "keep_out", "binds": "norra", "area": "norrhavn"}),
            "pact northern_pact: clause 1: norrhavn is not a territory or sea zone",
        ),
        (
            pact(
                {
                    "type": "place",
                    "binds": "norra",
                    "force": "norra_levy",
                    "region": "nowhere",
                    "on": day(1),
                }
            ),
            "pact northern_pact: clause 1: unknown region nowhere",
        ),
        (
            pact({"type": "no_war", "binds": "norra", "nation": "norrhavn"}),
            "pact northern_pact: clause 1: norrhavn is not a polity",
        ),
        (
            pact(
                {"type": "place", "binds": "norra", "force": "ilse", "area": "isle", "on": day(1)}
            ),
            "pact northern_pact: clause 1: ilse is a entity, not a feature",
        ),
        (
            pact({"type": "place", "binds": "norra", "area": "isle", "on": day(1)}),
            "pact northern_pact: clause 1: a place clause names its force",
        ),
        (
            pact({"type": "form", "binds": "norra", "form": "levy_act", "on": day(-1)}),
            "pact northern_pact: clause 1: dated before the start",
        ),
        (pact(NO_ATTACK, source="nowhere"), "pact northern_pact: unknown source nowhere"),
    ],
)
def test_compile_refuses_a_pact_that_does_not_hold(
    tmp_path: Path, change: Callable[[World], None], problem: str
) -> None:
    assert problem in refused(world(tmp_path, change))


def test_compile_refuses_a_pact_key_twice(tmp_path: Path) -> None:
    w = world(tmp_path, pact(NO_ATTACK), pact(NO_ATTACK))
    assert "pact northern_pact: duplicate key" in refused(w)


def test_a_legacy_world_has_no_pacts() -> None:
    from revisionist.core.world import PactDecl, WorldFile

    w = WorldFile(
        world="old",
        name="Old",
        pacts=(PactDecl(key="p", name="P", parties=("a", "b"), gap=True),),
    )
    with pytest.raises(WorldError, match="only a realism world has pacts"):
        compile_world(w, CAMPAIGN, cmp.versions())
