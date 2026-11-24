"""A card weighs an offer it is asked to allow by the offer's typed terms only.

A held acceptance of peace carries the offering seat's ``Deal``. The card of the
person who decides it scores the ask by the topics that person wants or holds to;
those topics are read from the deal's clause types and the nations it names, never
from the wording the offering player wrote, an unchecked clause's text, or the short
offer and ask labels of a deal of the old kind. Two offers that differ only in such
words get the same score.
"""

from pathlib import Path

import pytest

from revisionist.core.ids import EntityId
from revisionist.core.realism import answering, locks
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.card import Topic
from revisionist.core.realism.effect import (
    AgreementClause,
    ClauseType,
    Deal,
    EffectKind,
)
from revisionist.core.state import State
from tests.test_ask_answers import _asked_state
from tests.test_realism_locks import ILSE

NORRA, VELL = EntityId("norra"), EntityId("vell")
TOPIC = "the_oilfields"


def _peace(wording: str = "", text: str = "") -> Deal:
    clauses = [AgreementClause(type=ClauseType.END_WAR, binds=NORRA, nation=VELL)]
    if text:
        clauses.append(AgreementClause(type=ClauseType.UNCHECKED, binds=VELL, text=text))
    return Deal(
        counterparty=VELL,
        parties=(NORRA, VELL),
        wording=wording,
        clauses=tuple(clauses),
    )


Asked = tuple[State, locks.Asked]


@pytest.fixture
def asked(tmp_path: Path) -> Asked:
    """Kara's march, held for Ilse and asked for; nobody plays Ilse."""
    return _asked_state(tmp_path)


def _scored(
    asked: Asked, deal: Deal, field: str = "wants", topic: Topic | None = None
) -> tuple[int, int]:
    """The ask's score when the held order is an acceptance of ``deal``, with Ilse
    wanting (or holding to) ``topic``, and without the topic."""
    state, made = asked
    held = state.held[made.order_id]
    hold = locks.HeldOrder(
        order_id=held.order_id,
        issuer=held.issuer,
        filed=held.filed,
        asks=(Ask(ask="accept the peace", effect=deal),),
        row=held.row,
        decider=held.decider,
        reason=held.reason,
    )
    topic = topic or Topic(key=TOPIC, name="The oilfields", words=("oilfields", "tanker"))
    card = state.cards[ILSE].model_copy(update={field: (topic.key,)})
    base = state.model_copy(update={"held": {**state.held, made.order_id: hold}})
    with_topic = base.model_copy(
        update={"topics": {**state.topics, topic.key: topic}, "cards": {**state.cards, ILSE: card}}
    )
    return answering.ask_score(with_topic, made), answering.ask_score(base, made)


@pytest.mark.parametrize("field", ["wants", "holds_to"])
def test_the_offers_wording_does_not_move_the_score(asked: Asked, field: str) -> None:
    plain, _ = _scored(asked, _peace("Peace, now."), field)
    worded, untouched = _scored(asked, _peace("Peace, and the oilfields return by tanker."), field)
    assert worded == plain == untouched


def test_an_unchecked_clauses_text_does_not_move_the_score(asked: Asked) -> None:
    plain, _ = _scored(asked, _peace(text="Both sides keep the peace."))
    worded, untouched = _scored(asked, _peace(text="Vell gives up the oilfields to Norra"))
    assert worded == plain == untouched


def test_a_deals_offer_and_ask_labels_do_not_move_the_score(asked: Asked) -> None:
    def old(*labels: str) -> Deal:
        return Deal(counterparty=VELL, offer=labels, ask=("a truce",))

    plain, _ = _scored(asked, old("grain"))
    worded, untouched = _scored(asked, old("send the oilfields east"))
    assert worded == plain == untouched


def _armistice() -> Deal:
    clause = AgreementClause(type=ClauseType.ARMISTICE, binds=NORRA, nation=VELL, days=30)
    return Deal(counterparty=VELL, parties=(NORRA, VELL), clauses=(clause,))


TYPED = {
    "clause type": Topic(key="t", name="Truce", words=("armistice",)),
    "named nation": Topic(key="t", name="Vell", words=("vell",)),
    "deal kind": Topic(key="t", name="Deals", effects=(EffectKind.DEAL,)),
}


@pytest.mark.parametrize("name", list(TYPED))
def test_the_offers_typed_terms_still_move_the_score(asked: Asked, name: str) -> None:
    wanted, untouched = _scored(asked, _armistice(), "wants", TYPED[name])
    held, _ = _scored(asked, _armistice(), "holds_to", TYPED[name])
    assert wanted - untouched == answering.TOPIC_POINTS
    assert held - untouched == -answering.TOPIC_POINTS
