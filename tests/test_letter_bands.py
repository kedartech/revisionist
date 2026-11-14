"""Letters (train L): how long a page runs for the channel it went by and how its reader
is addressed.

A message said in person, by telephone or by radio, a cable and a letter each have a
word band; a press item and the formal kinds keep their own form and get none. The band
is a target: every line is still stated, a spoken message with many facts is written
up like any other page, and the number check still refuses a figure the page does not
carry.
"""

from collections.abc import Sequence

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EventId, derived_id
from revisionist.core.realism import effect as rx
from revisionist.core.realism.actors import readers
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import BodyField, DocumentKind, DocumentTruth, DocumentView
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine import campaign as cmp
from revisionist.engine.llm import Reply, Request, prompt_text
from revisionist.engine.prose import (
    Author,
    ClaudeProseWriter,
    Written,
    accepted,
    author_of,
    page_lines,
    template_prose,
)
from revisionist.engine.prose_context import CABLE, LETTER, MESSAGE, band
from revisionist.engine.realism_tick import run_realism_tick
from revisionist.engine.store import EventStore, MemoryStore, load_state
from tests.test_engine_v2_contract import Slice
from tests.test_prose_context import _page, _reported
from tests.test_realism_prose import Counting
from tests.test_realism_tick import CAMPAIGN, seated

FORMAL = (
    DocumentKind.POLL,
    DocumentKind.WHIP_COUNT,
    DocumentKind.INTERCEPT,
    DocumentKind.TRANSCRIPT,
    DocumentKind.PRESS,
)


def _lines(n: int) -> tuple[BodyField, ...]:
    return tuple(BodyField(label=f"Line {k}", value=k + 1) for k in range(n))


def _stark() -> tuple[State, DocumentView]:
    """Stark's report to Roosevelt on a shoot-on-sight order, one reader, a context."""
    state, _ = _reported(Slice(), fidelity=rx.Fidelity.FULL)
    return state, _page(state, "Shoot on sight")


def _as(page: DocumentView, kind: DocumentKind, channel: ChannelKind, n: int) -> DocumentView:
    return page.model_copy(update={"kind": kind, "channel": channel, "body": _lines(n)})


# --- the band by channel -------------------------------------------------------------


def test_each_channel_has_the_band_of_its_register() -> None:
    _, page = _stark()
    expected = {
        ChannelKind.IN_PERSON: MESSAGE,
        ChannelKind.TELEPHONE: MESSAGE,
        ChannelKind.RADIO: MESSAGE,
        ChannelKind.CABLE: CABLE,
        ChannelKind.LETTER: LETTER,
        ChannelKind.COURIER: LETTER,
        ChannelKind.PRESS: None,
    }
    assert set(expected) == set(ChannelKind)
    for channel, want in expected.items():
        for kind in (DocumentKind.REPORT, DocumentKind.LETTER, DocumentKind.MEMO):
            assert band(_as(page, kind, channel, 1)) == want, (kind, channel)


def test_the_bands_are_the_registers_word_counts() -> None:
    assert (MESSAGE.low, MESSAGE.high) == (10, 40)
    assert (CABLE.low, CABLE.high) == (30, 80)
    assert (LETTER.low, LETTER.high) == (80, 200)


def test_a_press_item_and_the_formal_kinds_keep_their_own_form() -> None:
    _, page = _stark()
    for kind in FORMAL:
        for channel in ChannelKind:
            assert band(_as(page, kind, channel, 2)) is None, (kind, channel)


def test_the_band_rides_on_the_page_into_the_prompt() -> None:
    state, page = _stark()
    cable = _as(page, DocumentKind.CABLE, ChannelKind.CABLE, 2)
    author = author_of(state, cable.author, [cable])
    assert page_lines(cable, author)["length"] == "30 to 80 words"
    poll = _as(page, DocumentKind.POLL, ChannelKind.LETTER, 2)
    assert "length" not in page_lines(poll, author_of(state, poll.author, [poll]))


def test_a_page_with_no_single_reader_still_gets_its_band() -> None:
    _, page = _stark()
    letter = _as(page, DocumentKind.LETTER, ChannelKind.LETTER, 2)
    two = letter.model_copy(
        update={"scope": letter.scope.model_copy(update={"known_by": frozenset({"a", "b"})})}
    )
    assert page_lines(two, Author(entity=two.author, name="x"))["length"] == "80 to 200 words"


def test_the_prompt_explains_every_field_a_page_can_carry() -> None:
    text = prompt_text("document_prose")
    for key in ("length", "to_addressed_as"):
        assert f"`{key}`" in text, key
    assert "40 to 160 words a page" not in text
    salutation = next(line for line in text.splitlines() if line.startswith("- a salutation"))
    assert "`to_addressed_as`" in salutation


# --- the form of address ---------------------------------------------------------------


def test_the_readers_form_of_address_reaches_the_prompt() -> None:
    state, page = _stark()
    fdr = state.seats[next(iter(page.scope.known_by))].embodies
    card = state.cards[fdr].model_copy(update={"addressed_as": "Mr. President"})
    state = state.model_copy(update={"cards": {**state.cards, fdr: card}})
    author = author_of(state, page.author, [page])
    assert page_lines(page, author)["context"]["to_addressed_as"] == "Mr. President"


def test_a_reader_with_no_form_of_address_gets_none_in_the_prompt() -> None:
    state, page = _stark()
    author = author_of(state, page.author, [page])
    assert "to_addressed_as" not in page_lines(page, author).get("context", {})


# --- a full spoken message is written up -------------------------------------------------


class Recording:
    """A transport that keeps each request and answers with no pages."""

    def __init__(self) -> None:
        self.sent: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.sent.append(request)
        return Reply(
            output={"pages": []},
            model="m",
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            usd=0.0,
        )


def test_the_model_is_asked_to_write_a_message_with_many_facts() -> None:
    state, page = _stark()
    for channel in (ChannelKind.IN_PERSON, ChannelKind.TELEPHONE, ChannelKind.RADIO):
        full = _as(page, DocumentKind.REPORT, channel, 6)
        transport = Recording()
        ClaudeProseWriter(transport).write(author_of(state, full.author, [full]), [full])
        (req,) = transport.sent
        assert full.doc_id in req.prompt, channel


def test_a_message_with_many_facts_is_kept_or_refused_like_any_page() -> None:
    state, page = _stark()
    full = _as(page, DocumentKind.REPORT, ChannelKind.TELEPHONE, 6)
    author = author_of(state, full.author, [full])
    written = template_prose(author, full)
    keep, refused = accepted([full], Written(prose={full.doc_id: written}), author)
    assert keep == {full.doc_id: written} and refused == []
    keep, refused = accepted([full], Written(prose={}), author)
    assert keep == {} and [r.doc_id for r in refused] == [full.doc_id]


# --- the number check with the new context ----------------------------------------------


def test_the_band_and_the_address_let_no_figure_through() -> None:
    state, page = _stark()
    fdr = state.seats[next(iter(page.scope.known_by))].embodies
    card = state.cards[fdr].model_copy(update={"addressed_as": "Mr. President"})
    state = state.model_copy(update={"cards": {**state.cards, fdr: card}})
    cable = _as(page, DocumentKind.CABLE, ChannelKind.CABLE, 2)
    author = author_of(state, cable.author, [cable])
    good = "Mr. President, line 0 stands at 1 and line 1 at 2."
    assert accepted([cable], Written(prose={cable.doc_id: good}), author)[0]
    for extra in (" In 80 words or fewer.", " Also 4,321 rifles."):
        keep, refused = accepted([cable], Written(prose={cable.doc_id: good + extra}), author)
        assert not keep and "states figures not on the page" in refused[0].reason, extra


# --- the stage -----------------------------------------------------------------------------


def _plant_message(store: EventStore, facts: int) -> DocumentId:
    """A telephoned report from Cora to Ada with ``facts`` lines, dated today."""
    state = load_state(store, CAMPAIGN)
    (seat,) = readers(state)
    today = state.in_world_date
    assert today is not None
    who = next(e for e, x in state.entities.items() if x.name.startswith("Cora"))
    doc_id = DocumentId(derived_id(CAMPAIGN, "telephoned", facts))
    view = DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.REPORT,
        author=who,
        issued=today,
        arrives=today,
        channel=ChannelKind.TELEPHONE,
        title=f"Cora telephones, {facts} points",
        body=_lines(facts),
        scope=private_to(seat),
    )
    store.append_all(
        [
            ev.Event(
                event_id=EventId(derived_id(CAMPAIGN, "telephoned-event", facts)),
                campaign_id=CAMPAIGN,
                seq=state.last_seq + 1,
                tick=state.tick,
                scope=view.scope,
                payload=ev.DocumentIssued(document=view, truth=DocumentTruth(doc_id=doc_id)),
                versions=cmp.versions(),
            )
        ]
    )
    return doc_id


@pytest.mark.parametrize("facts", [3, 4, 6])
def test_the_stage_writes_up_a_telephoned_message_once(facts: int) -> None:
    store = MemoryStore()
    seated(store)
    doc = _plant_message(store, facts)
    writer = Counting()
    result = run_realism_tick(store, CAMPAIGN, prose=writer)
    prose = load_state(store, CAMPAIGN).documents[doc].view.prose
    assert prose is not None
    assert not any(d.startswith(doc) for d in result.prose_dropped)
    cora_calls: Sequence[tuple[str, tuple[DocumentId, ...]]] = [
        c for c in writer.calls if doc in c[1]
    ]
    assert len(cora_calls) == 1  # no second draft asked for
