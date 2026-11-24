"""Offering, answering, publishing and reading agreements (AGA).

The toy world (``tests/worlds/territory-toy.yaml``) is played as AGR's tests play it
(``tests/test_agreements.py``): ``agreements`` on, Ilse for Norra, Tomas for Sudland and
Olaf for Ostmark, a third power at peace with both. An offer of agreement reaches each
other named nation's seat as an agenda item of kind "Offer" with its terms, answered with
the answer action; the wake notice lists it once. The seat's ``agreements`` block lists
every agreement its nation is party to and every public one, read from its own view.
The web cases play the same world through the server: ``agreement-offer`` reads an offer
the seat signs with ``file``, and ``agreement-publish`` files the order that publishes one.
"""

import dataclasses
import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, OrderId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import agreement, process
from revisionist.core.realism.agreement import ClauseStatus
from revisionist.core.realism.effect import ClauseType, Deal
from revisionist.engine import notice
from revisionist.engine.store import MemoryStore
from revisionist.engine.web import agenda_api, agreements_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests import test_agreements
from tests import test_peace as tp
from tests.test_adjacency_moves import START, Logged
from tests.test_agreements import (
    ILSE,
    ISLE,
    LEVY,
    NORRA,
    OLAF,
    OSTMARK,
    PLAIN,
    SUDLAND,
    TOMAS,
    clause,
    day,
    deal,
    file,
    game,
    in_force,
    judged,
    made,
    of,
    offer,
    world,
)
from tests.test_due_matters import opened
from tests.test_notice import GAME
from tests.test_territory_model import CAMPAIGN
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin, state_of

FIXTURES = Path(__file__).parents[1] / "web" / "test" / "fixtures"


def keep_out() -> Any:
    return clause(ClauseType.KEEP_OUT, area=ISLE)


def words(text: str = "Friendship for ever.") -> Any:
    return clause(ClauseType.UNCHECKED, text=text)


def block(g: Logged, who: SeatId) -> dict[str, Any] | None:
    out = rs.seat_realism(g.state, who, set(), set(), None, events=g.log)["agreements"]
    return None if out is None else dict(out)


def offer_items(g: Logged, who: SeatId) -> list[api.AgendaItem]:
    return [i for i in agenda_api.agenda(g.state, who, g.log)["items"] if i["kind"] == "Offer"]


def answer(g: Logged, who: SeatId, item: str, accept: bool) -> dict[str, Any]:
    """The answer action, on the game's log: what it landed is folded in."""
    store = MemoryStore()
    store.append_all(g.log)
    reply = agenda_api.answer(store, CAMPAIGN, who, item, accept)
    new = list(store.read(CAMPAIGN))[len(g.log) :]
    g.add([e.payload for e in new])
    return dict(reply)


def compose(g: Logged, who: SeatId) -> tuple[str, str]:
    """The seat's wake notice, as ``tests/test_due_matters.py`` composes one."""
    return notice.compose(opened(g.state), who, None, GAME)


def due_day(g: Logged, oid: OrderId) -> Any:
    return process.offer_due(g.state, g.state.routed[oid])


# --- Rule 2: the offer is an agenda item with its terms, answered as a request is -------


def test_an_offer_is_an_offer_item_on_the_other_seats_agenda_with_terms_and_expiry(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    oid = offer(g, deal(keep_out(), words()))
    (item,) = offer_items(g, TOMAS)
    g.walk(day(1), day(1))  # the day walk records the offer for its parties
    found = g.state.agreements.offers[oid]
    theirs = block(g, TOMAS)
    assert theirs is not None
    (line,) = theirs["offers"]
    assert line["item"] == item["id"] and line["answers"] == []
    terms = line["terms"]
    assert item["issuer"] == "Ilse Varg" and line["by"] == "Norra"
    assert terms["parties"] == ["Norra", "Sudland"]
    assert [c["text"] for c in terms["clauses"]] == [
        agreement.render_clause(g.state, c) for c in found.clauses
    ]
    assert [c["checked"] for c in terms["clauses"]] == [True, False]
    assert terms["wording"] == "Peace on the isle."
    assert terms["text"] == agreement.render_terms(g.state, found)
    assert terms["text"] in item["text"] and "(not checked by the rules)" in item["text"]
    due = due_day(g, oid)
    assert item["deadline"] == f"{due.day} {due:%B %Y}" and line["expires"] == due.isoformat()
    assert offer_items(g, ILSE) == [] and offer_items(g, OLAF) == []
    mine = block(g, ILSE)
    assert mine is not None and mine["offers"][0]["item"] is None


def test_an_offer_is_not_listed_as_a_request(tmp_path: Path) -> None:
    g = game(tmp_path)
    offer(g, deal(keep_out()))
    assert agenda_api.requests(g.state, TOMAS) == []
    assert [i["kind"] for i in agenda_api.agenda(g.state, TOMAS, g.log)["items"]] == ["Offer"]


def test_the_notice_lists_an_open_offer_once(tmp_path: Path) -> None:
    g = game(tmp_path)
    offer(g, deal(keep_out()))
    matters = agenda_api.due_matters(g.state, TOMAS)
    assert [m.kind for m in matters] == ["offer"]
    _, body = compose(g, TOMAS)
    (line,) = [x for x in body.splitlines() if "An offer of agreement" in x]
    assert line.startswith("- Ilse Varg: An offer of agreement.")
    assert agenda_api.due_matters(g.state, ILSE) == []


def test_the_offer_is_answered_with_the_answer_action(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = offer(g, deal(keep_out()))
    (item,) = offer_items(g, TOMAS)
    reply = answer(g, TOMAS, item["id"], True)
    assert not reply["refused"] and "offer" in reply["reply"]
    (again,) = offer_items(g, TOMAS)
    assert again["cause"] is not None  # the seat sees its own answer
    g.walk(day(1), due_day(g, oid))
    (x,) = made(g)
    assert x.offer_id == oid


def test_an_answer_given_is_not_in_the_notice(tmp_path: Path) -> None:
    g = game(tmp_path)
    offer(g, deal(keep_out()))
    before = compose(g, TOMAS)
    (item,) = offer_items(g, TOMAS)
    answer(g, TOMAS, item["id"], False)
    assert compose(g, TOMAS) == before


# --- Rule 3: made only when every named nation accepts; answers shown on the due day ----


def test_the_issuers_view_shows_each_answer_only_on_the_due_day(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = offer(g, deal(keep_out()))
    (item,) = offer_items(g, TOMAS)
    answer(g, TOMAS, item["id"], True)
    due = due_day(g, oid)
    g.walk(day(1), due - timedelta(days=1))
    mine = block(g, ILSE)
    assert mine is not None
    (line,) = mine["offers"]
    assert line["answers"] == [{"nation": "Sudland", "answer": None}]
    g.walk(due, due)
    after = block(g, ILSE)
    assert after is not None
    assert after["offers"] == []  # closed on its due day: the agreement is in force
    routed = g.state.routed[oid]
    assert [p.accepted for p in routed.parts] == [True]


def test_the_issuers_offer_line_reads_a_decided_answer(tmp_path: Path) -> None:
    """A three-nation offer: Sudland's part decided, Ostmark's still open."""
    g = game(tmp_path)
    oid = offer(g, deal(keep_out(), parties=(NORRA, SUDLAND, OSTMARK)))
    g.walk(day(1), day(1))  # the day walk records the offer for its parties
    g.add([ev.InfluenceDecided(order_id=oid, part=0, on=START, accepted=False, reason="No.")])
    assert g.state.routed[oid].parts[1].decided is None
    mine = block(g, ILSE)
    assert mine is not None
    (line,) = mine["offers"]
    assert line["answers"] == [
        {"nation": "Sudland", "answer": "declined"},
        {"nation": "Ostmark", "answer": None},
    ]


def test_an_offer_to_two_nations_accepted_by_one_and_declined_by_the_other_makes_nothing(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    oid = offer(g, deal(keep_out(), parties=(NORRA, SUDLAND, OSTMARK)))
    (to_tomas,) = offer_items(g, TOMAS)
    (to_olaf,) = offer_items(g, OLAF)
    answer(g, TOMAS, to_tomas["id"], True)
    answer(g, OLAF, to_olaf["id"], False)
    out = g.walk(day(1), due_day(g, oid) + timedelta(days=2))
    assert made(g) == []
    assert not [e for e in out if isinstance(e.payload, ev.AgreementMade)]
    titles = [e.payload.document.title for e in out if isinstance(e.payload, ev.DocumentIssued)]
    assert "An offer of agreement lapsed" in titles


def test_the_signing_reading_shows_the_terms_render_terms_gives(tmp_path: Path) -> None:
    g = game(tmp_path)
    reading = agreements_api.offer_reading(
        g.state,
        ILSE,
        {"parties": [SUDLAND], "wording": "Peace.", "clauses": [keep_out().model_dump()]},
    )
    d = reading.asks[0].effect
    assert isinstance(d, Deal)
    reply = agreements_api.reading_reply(g.state, ILSE, reading, False)
    terms = reply["terms"]
    assert terms is not None and terms["text"] == reading.terms
    assert reading.terms == agreement.render_terms(
        g.state, agreements_api._signed(g.state, ILSE, d)
    )
    assert [c["interpretation"] for c in terms["clauses"]] == [False]
    assert agreement.render_clause(g.state, keep_out()) in reply["proposal"]["parts"][1]
    assert any("Peace." in p for p in reply["proposal"]["parts"])


def test_a_treaty_the_aide_read_marks_its_clauses_as_the_aides_interpretation(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    reading = agreements_api.offer_reading(
        g.state,
        ILSE,
        {"parties": [SUDLAND], "wording": "Keep off.", "clauses": [keep_out().model_dump()]},
    )
    read = agreements_api.reading_reply(g.state, ILSE, reading, True, "Read.")
    assert read["reply"] == "Read." and read["terms"] is not None
    assert [c["interpretation"] for c in read["terms"]["clauses"]] == [True]
    unsigned = agreements_api.reading_reply(
        g.state, ILSE, dataclasses.replace(reading, asks=(), version=""), True
    )
    assert unsigned["terms"] is None and unsigned["refused"]


# --- Rule 1: the offer action's checks --------------------------------------------------


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ({"parties": [], "wording": "Peace."}, "Name the nation"),
        ({"parties": [SUDLAND]}, "needs wording"),
        (
            {"parties": [SUDLAND], "clauses": [{"type": "no_war", "binds": OSTMARK}]},
            "Clause 1 cannot be offered",
        ),
        (
            {
                "parties": [SUDLAND],
                "clauses": [
                    {"type": "keep_out", "binds": NORRA, "area": ISLE},
                    {"type": "no_war", "binds": OSTMARK, "nation": SUDLAND},
                ],
            },
            "Clause 2 cannot be offered",
        ),
        (
            {"parties": [SUDLAND], "clauses": [{"type": "unchecked", "binds": NORRA}]},
            "Clause 1 cannot be offered",
        ),
        ({"parties": [SUDLAND], "wording": "x" * 601}, "at most 600"),
        ({"parties": [SUDLAND], "wording": "Peace.", "envoy": "nobody"}, "envoy"),
    ],
)
def test_an_offer_the_rules_refuse_is_refused_whole(
    tmp_path: Path, body: dict[str, Any], why: str
) -> None:
    g = game(tmp_path)
    with pytest.raises(ValueError, match=why):
        agreements_api.offer_reading(g.state, ILSE, body)


def test_with_the_rule_off_no_offer_is_read_and_there_is_no_block(tmp_path: Path) -> None:
    g = game(tmp_path, rules=("holders",))
    with pytest.raises(ValueError, match="not part of this game"):
        agreements_api.offer_reading(g.state, ILSE, {"parties": [SUDLAND], "wording": "Peace."})
    assert block(g, ILSE) is None


# --- Rule 4: the agreements block, from the seat's view ---------------------------------


def test_the_block_lists_the_seats_agreements_with_each_clauses_state_and_day(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    dated = clause(ClauseType.PLACE, force=LEVY, area=PLAIN, on=day(2))
    x = in_force(g, dated, keep_out(), words())
    mine = block(g, ILSE)
    assert mine is not None
    (line,) = mine["agreements"]
    assert line["id"] == x.agreement_id and line["parties"] == ["Norra", "Sudland"]
    assert line["party"] is True and line["published"] is None
    assert [(c["state"], c["on"], c["checked"]) for c in line["clauses"]] == [
        ("pending", day(2).isoformat(), True),
        ("pending", None, True),
        ("unchecked", None, False),
    ]
    judged(g, day(1), day(2))
    after = block(g, ILSE)
    assert after is not None
    (line,) = after["agreements"]
    states = [(c["state"], c["on"]) for c in line["clauses"]]
    assert states[0] == ("kept", day(2).isoformat())
    assert states[2] == ("unchecked", None)  # wording is never judged, never kept


def test_a_broken_clause_shows_broken_with_its_day(tmp_path: Path) -> None:
    g = game(tmp_path)
    in_force(g, clause(ClauseType.PLACE, force=LEVY, area=ISLE, on=day(1)))
    judged(g, day(1), day(1))
    mine = block(g, TOMAS)
    assert mine is not None
    ((c,),) = [line["clauses"] for line in mine["agreements"]]
    assert (c["state"], c["on"]) == (ClauseStatus.BROKEN.value, day(1).isoformat())


def test_a_third_seat_holds_nothing_of_a_private_agreement_before_or_after_judging(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    secret = "Sealed wording only Norra and Sudland know."
    x = agreement.pact(
        CAMPAIGN,
        "secret",
        (NORRA, SUDLAND),
        secret,
        (clause(ClauseType.PLACE, force=LEVY, area=PLAIN, on=day(1)), keep_out()),
        START,
        False,
    )
    g.add([ev.AgreementMade(agreement=x)])
    oid = offer(g, deal(keep_out(), wording="An offer sealed to its parties."))
    for when in ("before", "after"):
        if when == "after":
            judged(g, day(1), day(1))
        third = rs.seat_realism(g.state, OLAF, set(), set(), None, events=g.log)
        text = json.dumps(third)
        assert third["agreements"] == {"agreements": [], "offers": []}, when
        for leak in (secret, x.agreement_id, "An offer sealed to its parties.", str(oid)):
            assert leak not in text, (when, leak)
        mine = block(g, TOMAS)
        assert mine is not None and [a["id"] for a in mine["agreements"]] == [x.agreement_id]


def test_a_public_agreement_is_listed_for_every_seat(tmp_path: Path) -> None:
    g = game(tmp_path)
    x = in_force(g, keep_out(), public=True)
    third = block(g, OLAF)
    assert third is not None
    (line,) = third["agreements"]
    assert line["id"] == x.agreement_id and line["party"] is False
    assert line["published"] == START.isoformat()


# --- Rule 5: publishing ------------------------------------------------------------------


def test_the_publish_order_makes_the_agreement_public(tmp_path: Path) -> None:
    g = game(tmp_path)
    x = in_force(g, keep_out())
    asks, label = agreements_api.publish_asks(g.state, TOMAS, {"agreement": x.agreement_id})
    assert label == "Publish the agreement"
    file(g, TOMAS, *asks)
    g.walk(day(1), day(3))
    third = block(g, OLAF)
    assert third is not None and [a["id"] for a in third["agreements"]] == [x.agreement_id]


@pytest.mark.parametrize("who", ["olaf", "missing", "public"])
def test_only_a_party_publishes_an_agreement_not_yet_public(tmp_path: Path, who: str) -> None:
    g = game(tmp_path)
    x = in_force(g, keep_out(), public=who == "public")
    by = OLAF if who == "olaf" else TOMAS
    key = "nope" if who == "missing" else x.agreement_id
    with pytest.raises(ValueError, match=r"no such agreement|already published"):
        agreements_api.publish_asks(g.state, by, {"agreement": key})


# --- The fixture -------------------------------------------------------------------------


def test_the_seat_fixture_carries_the_block_and_an_offer_reading() -> None:
    """The block holds an agreement, the seat's own offer (with answers) and an offer
    before it (with its agenda item); the reading holds the structured terms DPL reads."""
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())
    shown = fixture["agreements"]
    assert set(shown) == set(api.AgreementsBlock.__annotations__)
    assert shown["agreements"] and {c["state"] for c in shown["agreements"][0]["clauses"]} >= {
        "kept",
        "pending",
        "unchecked",
    }
    assert [o["item"] is None for o in shown["offers"]] == [True, False, False]
    assert shown["offers"][0]["answers"] and shown["offers"][1]["answers"] == []
    (peace,) = [o for o in shown["offers"] if "accept" in o]
    assert set(peace["accept"]) == set(api.LockCheck.__required_keys__)
    assert [c["type"] for c in shown["peace"]] == [t for t, _ in agreements_api.PEACE_LABELS]
    for c in shown["peace"]:
        assert set(c) == set(api.PeaceClause.__annotations__) and c["nations"]
        assert all(set(n) == set(api.WarNation.__annotations__) for n in c["nations"])
    (line,) = shown["armistices"]
    assert set(line) == set(api.ArmisticeLine.__annotations__)
    reading = fixture["offer_reading"]
    assert set(reading) == set(api.OfferReading.__annotations__)
    assert reading["terms"]["clauses"] and reading["terms"]["wording"]


# --- Rules 1 and 5 through the server ------------------------------------------------------


@pytest.fixture
def trio(web: Web, tmp_path: Path) -> Iterator[tuple[Realism, Client, Client, Client]]:  # noqa: F811
    world(tmp_path)
    game_ = Realism(web, str(tmp_path / "world.yaml"))
    ada = game_.seat("ada", "ilse")
    bea = game_.seat("bea", "tomas")
    cy = game_.seat("cyd", "olaf")
    make_host(game_, ada)
    begin(game_)
    yield game_, ada, bea, cy


def _ids(game_: Realism) -> tuple[str, str, str]:
    return (game_.ids["norra"], game_.ids["sudland"], game_.ids["isle"])


def test_the_offer_action_reads_an_offer_the_seat_signs_with_file(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, ada, _, _ = trio
    norra, sudland, isle = _ids(game_)
    body = {
        "parties": [sudland],
        "wording": "Peace on the isle.",
        "clauses": [{"type": "keep_out", "binds": norra, "area": isle}],
    }
    status, out = post(ada, "agreement-offer", **body)
    assert status == 200 and not out["refused"], out
    assert set(out) >= set(api.OfferReading.__annotations__)
    assert out["terms"]["clauses"] == [
        {
            "text": "Norra: no piece enters The Isle, at all times.",
            "checked": True,
            "interpretation": False,
        }
    ]
    assert out["terms"]["wording"] == "Peace on the isle."
    before = set(state_of(game_).routed)
    status, filed = post(ada, "file")
    assert status == 200 and not filed["refused"], filed
    (new,) = set(state_of(game_).routed) - before
    d = state_of(game_).routed[new].parts[0].effect
    assert isinstance(d, Deal) and d.parties == (EntityId(norra), EntityId(sudland))
    assert d.wording == "Peace on the isle."
    status, again = post(ada, "file")
    assert again["refused"]  # the reading is spent once signed


def test_a_refused_offer_files_nothing(trio: tuple[Realism, Client, Client, Client]) -> None:
    game_, ada, _, _ = trio
    _, sudland, isle = _ids(game_)
    ostmark = game_.ids["ostmark"]
    body = {"parties": [sudland], "clauses": [{"type": "keep_out", "binds": ostmark, "area": isle}]}
    status, out = post(ada, "agreement-offer", **body)
    assert status == 200 and out["refused"], out
    assert "Clause 1 cannot be offered" in out["reply"]
    status, filed = post(ada, "file")
    assert filed["refused"]


def test_the_publish_action_files_the_publishing_order(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, _, bea, cy = trio
    norra, sudland, isle = _ids(game_)
    x = agreement.pact(
        game_.campaign,
        "web",
        (EntityId(norra), EntityId(sudland)),
        "Kept quiet.",
        (clause(ClauseType.KEEP_OUT, binds=EntityId(norra), area=EntityId(isle)),),
        START,
        False,
    )
    _append(game_, ev.AgreementMade(agreement=x))
    assert [a["id"] for a in realism_of(bea)["agreements"]["agreements"]] == [x.agreement_id]
    assert realism_of(cy)["agreements"]["agreements"] == []
    status, out = post(cy, "agreement-publish", agreement=x.agreement_id)
    assert status == 200 and out["refused"], out
    status, out = post(bea, "agreement-publish", agreement=x.agreement_id)
    assert status == 200 and not out["refused"], out
    (order,) = [
        o
        for o in state_of(game_).routed.values()
        if isinstance(o.parts[0].effect, Deal) and o.parts[0].effect.publish == x.agreement_id
    ]
    assert order.parts[0].ask == agreements_api.PUBLISH_ASK


def test_a_publish_after_the_seats_commit_is_held_for_the_next_wake(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    game_, _, bea, _ = trio
    norra, sudland, isle = _ids(game_)
    x = agreement.pact(
        game_.campaign,
        "held",
        (EntityId(norra), EntityId(sudland)),
        "",
        (clause(ClauseType.KEEP_OUT, binds=EntityId(norra), area=EntityId(isle)),),
        START,
        False,
    )
    _append(game_, ev.AgreementMade(agreement=x))
    status, out = post(bea, "commit")
    assert status == 200 and not out["refused"], out
    status, out = post(bea, "agreement-publish", agreement=x.agreement_id)
    assert status == 200 and not out["refused"] and "held" in out, out


def _append(game_: Realism, payload: ev.Payload) -> None:
    from revisionist.core.visibility import PUBLIC
    from revisionist.engine import realism_tick

    store = game_.web.app.open()
    try:
        state = state_of(game_)
        realism_tick._append(store, state, payload, SeatId(""), PUBLIC)
    finally:
        store.close()


# --- Peace as the seat sees it (PER) ---------------------------------------------------


def peace_block(g: Logged, who: SeatId) -> dict[str, Any]:
    out = block(g, who)
    assert out is not None
    return out


def test_with_peace_off_the_block_is_as_before(tmp_path: Path) -> None:
    g = tp.game(tmp_path, rules=tp.RULES[:-1])
    tp.put_in_force(g, tp.armistice(10))
    assert set(peace_block(g, ILSE)) == {"agreements", "offers"}


def test_the_builder_offers_each_peace_clause_with_the_nations_at_war_with_the_seats(
    tmp_path: Path,
) -> None:
    g = tp.game(tmp_path, tp.ostmark_at_war)
    norra = peace_block(g, ILSE)["peace"]
    assert [c["type"] for c in norra] == ["armistice", "end_war", "no_separate_peace"]
    assert all(c["nations"] == [{"key": SUDLAND, "name": "Sudland"}] for c in norra)
    sudland = peace_block(g, TOMAS)["peace"]
    assert all([n["name"] for n in c["nations"]] == ["Norra", "Ostmark"] for c in sudland)


def test_a_nation_at_war_with_nobody_may_name_nobody(tmp_path: Path) -> None:
    g = tp.game(tmp_path)
    assert all(c["nations"] == [] for c in peace_block(g, OLAF)["peace"])


def test_the_decider_reads_every_clause_of_the_peace_before_allowing_it(
    tmp_path: Path,
) -> None:
    from revisionist.engine.web import locks_api

    g = tp.game(tmp_path, tp.council(3))
    oid, due = tp.accepted_by_tomas(g)
    g.walk(day(1), due)
    found = g.state.agreements.offers[oid]
    out = locks_api.block(g.state, TOMAS)
    assert out is not None
    (ask,) = out["asks"]
    assert ask["terms"] == agreements_api.offer_terms(g.state, found)
    assert len(ask["terms"]["clauses"]) == len(found.clauses) == 2
    assert ask["terms"]["text"] == agreement.render_terms(g.state, found)


def accept_check(g: Logged, who: SeatId) -> dict[str, Any]:
    (line,) = peace_block(g, who)["offers"]
    assert line["item"] is not None
    return dict(line["accept"])


def offered(g: Logged) -> tuple[OrderId, Any]:
    oid = tp.peace_offer(g, tp.ends_war(), tp.ends_war(SUDLAND, NORRA))
    g.walk(day(1), day(1))
    return oid, due_day(g, oid)


def test_the_check_says_an_acceptance_the_seat_may_give_goes_out(tmp_path: Path) -> None:
    g = tp.game(tmp_path)
    oid, due = offered(g)
    assert accept_check(g, TOMAS) == {"check": "allowed", "who": None, "reason": ""}
    (own,) = peace_block(g, ILSE)["offers"]
    assert "accept" not in own
    test_agreements.answer(g, oid, TOMAS, True)
    out = g.walk(day(2), due)
    assert of(out, ev.AgreementMade) and not of(out, ev.OrderHeld)


def test_the_check_says_who_holds_an_acceptance_as_accepting_then_holds_it(
    tmp_path: Path,
) -> None:
    from revisionist.engine.web import locks_api

    g = tp.game(tmp_path, tp.council(3))
    oid, due = offered(g)
    check = accept_check(g, TOMAS)
    test_agreements.answer(g, oid, TOMAS, True)
    out = g.walk(day(2), due)
    (held,) = of(out, ev.OrderHeld)
    view = project(g.state, TOMAS)
    assert check == {
        "check": "locked",
        "who": locks_api.who(view, held.held.decider),
        "reason": held.held.reason,
    }
    assert check["who"] == "the council under Tomas Brand"


def test_the_check_says_an_acceptance_beyond_the_seat_lapses_the_peace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revisionist.core.realism import locks

    g = tp.game(tmp_path)
    oid, due = offered(g)
    real = locks.peace_row
    monkeypatch.setattr(locks, "peace_row", lambda s, n: None if n == SUDLAND else real(s, n))
    check = accept_check(g, TOMAS)
    assert check == {
        "check": "beyond",
        "who": None,
        "reason": "No one in Sudland may accept a peace.",
    }
    test_agreements.answer(g, oid, TOMAS, True)
    out = g.walk(day(2), due)
    assert not of(out, ev.AgreementMade)
    titles = [p.document.title for p in of(out, ev.DocumentIssued)]
    assert "An offer of agreement lapsed" in titles


def test_an_offer_that_is_no_peace_carries_no_check(tmp_path: Path) -> None:
    g = tp.game(tmp_path)
    offer(g, deal(keep_out()))
    g.walk(day(1), day(1))
    (line,) = peace_block(g, TOMAS)["offers"]
    assert "accept" not in line


def test_an_unpublished_peace_offer_is_nowhere_in_a_third_nations_data(
    tmp_path: Path,
) -> None:
    g = tp.game(tmp_path)
    offered(g)
    third = rs.seat_realism(g.state, OLAF, set(), set(), None, events=g.log)
    text = json.dumps(third, default=str)
    assert "Peace between Norra and Sudland." not in text
    assert peace_block(g, OLAF)["offers"] == []
    assert "Peace between Norra and Sudland." in json.dumps(peace_block(g, TOMAS))


def test_an_armistice_in_force_and_its_last_day_reach_its_parties_only_until_published(
    tmp_path: Path,
) -> None:
    g = tp.game(tmp_path)
    x = tp.put_in_force(g, tp.armistice(10))
    line = {
        "agreement": x.agreement_id,
        "nations": ["Norra", "Sudland"],
        "last_day": (START + timedelta(days=10)).isoformat(),
    }
    assert peace_block(g, ILSE)["armistices"] == [line]
    assert peace_block(g, TOMAS)["armistices"] == [line]
    assert peace_block(g, OLAF)["armistices"] == []
    g.add([ev.AgreementPublished(agreement_id=x.agreement_id, by=NORRA, on=START)])
    assert peace_block(g, OLAF)["armistices"] == [line]


def test_an_armistice_whose_days_ran_out_is_not_listed(tmp_path: Path) -> None:
    g = tp.game(tmp_path)
    tp.put_in_force(g, tp.armistice(3))
    g.walk(day(1), day(4))
    assert peace_block(g, ILSE)["armistices"] == []
