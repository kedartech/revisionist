"""The treaty and bill reader (TRT): free wording read into an offer of an agreement.

The reader's reply is canned and an instrumented transport counts every request. The
reader proposes; code checks each clause against the clause list and the seat's view,
the signing view shows the terms rendered from the validated clauses, and the signed
version is the one filed.
"""

import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.ids import EntityId
from revisionist.core.realism import agreement
from revisionist.core.realism.effect import Deal
from revisionist.engine import orders_reader as orr
from revisionist.engine.llm import Reply, Request, TransportError
from revisionist.engine.store import MemoryStore, load_state
from tests.test_adjacency_moves import Logged, entity
from tests.test_agreements import ILSE, NORRA, SUDLAND, TOMAS, game
from tests.test_territory_model import CAMPAIGN

ON = ("holders", "agreements", "written_orders", "clause_reader")
WORDING = "Norra will keep out of the isle, and neither side will attack the other."
KEEP_OUT = {"type": "keep_out", "binds": NORRA, "area": entity("isle")}
NO_ATTACK = {"type": "no_attack", "binds": SUDLAND, "nation": NORRA}


class Canned:
    """Answers with ``output`` or fails; counts every request."""

    def __init__(self, output: dict[str, Any] | None = None, fail: bool = False) -> None:
        self.output = output or {}
        self.fail = fail
        self.requests: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.requests.append(request)
        if self.fail:
            raise TransportError("quota exhausted")
        return Reply(self.output, request.model, 10, 10, 0, 0.0)


def treaty(
    *clauses: dict[str, Any], parties: Sequence[EntityId] = (NORRA, SUDLAND)
) -> dict[str, Any]:
    return {
        "asks": [],
        "reason": "",
        "treaty": {"parties": list(parties), "clauses": list(clauses)},
    }


def played(tmp_path: Path, rules: Sequence[str] = ON) -> Logged:
    return game(tmp_path, rules=rules)


def read(g: Logged, canned: Canned, text: str = WORDING, to: str = "Brand") -> orr.Reading:
    return orr.read_order(g.state, ILSE, to, "", text, canned)


def store_of(g: Logged) -> MemoryStore:
    store = MemoryStore()
    store.append_all(g.log)
    return store


def shown(reading: orr.Reading) -> str:
    return " | ".join(reading.shown["parts"])


def test_wording_is_read_into_an_offer_with_its_clauses(tmp_path: Path) -> None:
    g = played(tmp_path)
    canned = Canned(treaty(KEEP_OUT, NO_ATTACK))
    reading = read(g, canned)
    assert reading.shown["reason"] is None and len(reading.asks) == 1
    deal = reading.asks[0].effect
    assert isinstance(deal, Deal) and deal.parties == (NORRA, SUDLAND)
    assert deal.wording == WORDING and len(deal.clauses) == 2
    assert len(canned.requests) == 1
    done = orr.file_order(store_of(g), CAMPAIGN, ILSE, reading)
    assert done["refused"] is False


def test_the_signing_view_is_the_rendered_terms_and_not_the_readers_summary(
    tmp_path: Path,
) -> None:
    g = played(tmp_path)
    out = treaty(KEEP_OUT)
    out["summary"] = "Norra gives away everything and owes nothing."
    out["treaty"]["summary"] = "Norra gives away everything and owes nothing."
    reading = read(g, Canned(out))
    deal = reading.asks[0].effect
    assert isinstance(deal, Deal)
    offer = orr._offer_of(g.state, g.state.seats[ILSE].embodies, deal)
    rendered = agreement.render_terms(g.state, offer)
    assert reading.terms == rendered
    assert "gives away everything" not in shown(reading)
    for _label, words in agreement.term_rows(g.state, offer):
        assert words in shown(reading)
    assert "the aide's reading" in shown(reading)
    assert "do not check" in shown(reading)


def test_an_invalid_clause_is_dropped_and_said(tmp_path: Path) -> None:
    g = played(tmp_path)
    bad_shape = {"type": "keep_out", "binds": NORRA}
    no_such_area = {"type": "keep_out", "binds": NORRA, "area": "nowhere"}
    foreign = {"type": "no_war", "binds": entity("ostmark"), "nation": NORRA}
    vote = {"type": "vote", "binds": NORRA, "text": "t", "present": True}
    reading = read(g, Canned(treaty(KEEP_OUT, bad_shape, no_such_area, foreign, vote)))
    deal = reading.asks[0].effect
    assert isinstance(deal, Deal) and len(deal.clauses) == 1
    assert "Left out" in shown(reading) and "4" in shown(reading)


def test_a_valid_clause_the_text_does_not_support_is_kept_and_labelled_as_a_reading(
    tmp_path: Path,
) -> None:
    g = played(tmp_path)
    unsupported = {"type": "no_war", "binds": NORRA, "nation": SUDLAND}
    reading = read(g, Canned(treaty(unsupported)), text="Our two realms will talk again.")
    assert len(reading.asks) == 1
    assert "(the aide's reading)" in shown(reading)
    assert "Our two realms will talk again." in shown(reading)


def test_wording_that_fits_no_clause_stays_as_wording_marked_unchecked(tmp_path: Path) -> None:
    g = played(tmp_path)
    reading = read(g, Canned(treaty()))
    deal = reading.asks[0].effect
    assert isinstance(deal, Deal) and deal.clauses == ()
    assert "None the rules can check" in shown(reading)
    assert f"which the rules do not check: {WORDING}" in shown(reading)


def test_with_clause_reader_off_no_clause_is_proposed(tmp_path: Path) -> None:
    g = played(tmp_path, ("holders", "agreements", "written_orders"))
    canned = Canned(treaty(KEEP_OUT))
    reading = read(g, canned)
    deal = reading.asks[0].effect
    assert isinstance(deal, Deal) and deal.clauses == ()
    assert "clause_list" not in canned.requests[0].prompt


def test_the_clause_list_is_in_the_prompt_only_with_clause_reader_on(tmp_path: Path) -> None:
    g = played(tmp_path)
    canned = Canned(treaty())
    read(g, canned)
    assert "clause_list" in canned.requests[0].prompt


def test_with_written_orders_off_the_reader_points_to_the_form(tmp_path: Path) -> None:
    g = played(tmp_path, ("holders", "agreements", "clause_reader"))
    reading = read(g, Canned(treaty(KEEP_OUT)))
    assert not reading.asks and reading.shown["reason"] == orr.TO_THE_FORM


@pytest.mark.parametrize("fail", [True])
def test_a_failed_read_offers_the_wording_with_no_clauses_and_says_so(
    tmp_path: Path, fail: bool
) -> None:
    g = played(tmp_path)
    canned = Canned(fail=fail)
    reading = read(g, canned)
    deal = reading.asks[0].effect
    assert isinstance(deal, Deal) and deal.clauses == () and deal.wording == WORDING
    assert orr.NO_CLAUSES in shown(reading)
    assert len(canned.requests) == 1


def test_a_failed_read_with_no_foreign_addressee_is_still_an_error(tmp_path: Path) -> None:
    g = played(tmp_path)
    with pytest.raises(TransportError):
        read(g, Canned(fail=True), text="Do it.", to="")


def test_a_failed_read_files_nothing_until_signed(tmp_path: Path) -> None:
    g = played(tmp_path)
    store = store_of(g)
    read(g, Canned(fail=True))
    assert not load_state(store, CAMPAIGN).routed


def test_a_version_changed_after_signing_cannot_be_filed(tmp_path: Path) -> None:
    g = played(tmp_path)
    reading = read(g, Canned(treaty(KEEP_OUT)))
    deal = reading.asks[0].effect
    assert isinstance(deal, Deal)
    other = deal.model_copy(update={"clauses": (*deal.clauses, _clause(NO_ATTACK))})
    swapped = dataclasses.replace(
        reading, asks=(reading.asks[0].model_copy(update={"effect": other}),)
    )
    store = store_of(g)
    done = orr.file_order(store, CAMPAIGN, ILSE, swapped)
    assert done["refused"] is True and done["reply"] == orr.CHANGED
    assert not load_state(store, CAMPAIGN).routed


def test_a_clause_that_stopped_being_valid_before_filing_is_refused(tmp_path: Path) -> None:
    g = played(tmp_path)
    reading = read(g, Canned(treaty(KEEP_OUT)))
    deal = reading.asks[0].effect
    assert isinstance(deal, Deal)
    gone = deal.clauses[0].model_copy(update={"area": entity("nowhere")})
    forged = reading.asks[0].model_copy(
        update={"effect": deal.model_copy(update={"clauses": (gone,)})}
    )
    done = orr.file_order(store_of(g), CAMPAIGN, ILSE, dataclasses.replace(reading, asks=(forged,)))
    assert done["refused"] is True


def test_a_treaty_with_other_asks_is_refused(tmp_path: Path) -> None:
    g = played(tmp_path)
    out = treaty(KEEP_OUT)
    out["asks"] = [{"ask": "Also talk to him", "target": g.state.seats[TOMAS].embodies}]
    reading = read(g, Canned(out))
    assert not reading.asks and reading.shown["reason"] == agreement.ALONE


def test_the_offer_is_filed_as_an_offer_to_each_other_nation(tmp_path: Path) -> None:
    g = played(tmp_path)
    store = store_of(g)
    reading = read(g, Canned(treaty(KEEP_OUT)))
    assert orr.file_order(store, CAMPAIGN, ILSE, reading)["refused"] is False
    state = load_state(store, CAMPAIGN)
    (order,) = state.routed.values()
    assert any(agreement.is_offer(p) for p in order.parts)


def _clause(raw: dict[str, Any]) -> Any:
    from revisionist.core.realism.effect import AgreementClause

    return AgreementClause.model_validate(raw)


def test_a_reply_the_code_cannot_parse_gives_the_no_clauses_reading(tmp_path: Path) -> None:
    g = played(tmp_path)
    out = treaty(KEEP_OUT)
    out["treaty"]["clauses"] = "not a list"
    canned = Canned(out)
    reading = read(g, canned)
    deal = reading.asks[0].effect
    assert isinstance(deal, Deal) and deal.clauses == ()
    assert orr.NO_CLAUSES in shown(reading) and len(canned.requests) == 1


def test_a_clause_naming_something_that_is_not_a_nation_is_dropped(tmp_path: Path) -> None:
    g = played(tmp_path)
    not_a_nation = {"type": "no_war", "binds": NORRA, "nation": entity("isle")}
    deal = read(g, Canned(treaty(not_a_nation))).asks[0].effect
    assert isinstance(deal, Deal) and deal.clauses == ()


def test_a_clause_naming_a_piece_the_seat_does_not_command_is_dropped(tmp_path: Path) -> None:
    g = played(tmp_path)
    galleys = {
        "type": "place",
        "binds": SUDLAND,
        "force": entity("sudland_galleys"),
        "area": entity("isle"),
        "on": "2026-01-01",
    }
    deal = read(g, Canned(treaty(galleys))).asks[0].effect
    assert isinstance(deal, Deal) and deal.clauses == ()


def test_a_changed_wording_is_a_new_version_and_needs_a_new_signature(tmp_path: Path) -> None:
    g = played(tmp_path)
    reading = read(g, Canned(treaty(KEEP_OUT)))
    deal = reading.asks[0].effect
    assert isinstance(deal, Deal)
    other = deal.model_copy(update={"wording": "Norra will keep out of the isle forever."})
    swapped = dataclasses.replace(
        reading, asks=(reading.asks[0].model_copy(update={"effect": other}),)
    )
    done = orr.file_order(store_of(g), CAMPAIGN, ILSE, swapped)
    assert done["refused"] is True and done["reply"] == orr.CHANGED


def test_terms_that_differ_from_the_signed_ones_cannot_be_filed(tmp_path: Path) -> None:
    g = played(tmp_path)
    reading = read(g, Canned(treaty(KEEP_OUT)))
    stale = dataclasses.replace(reading, terms="Parties: Norra, Sudland. Clauses: None.")
    done = orr.file_order(store_of(g), CAMPAIGN, ILSE, stale)
    assert done["refused"] is True and done["reply"] == orr.CHANGED
