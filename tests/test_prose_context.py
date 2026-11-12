"""Letters (train L): what the prose writer is told about why each page is written.

The writer still takes views only; the context is read from state by ``author_of`` and
rides on the ``Author`` block: who the page goes to, the reader's own words for the
order it answers, what the page is for, and how the author stands to the reader.
"""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import EntityId
from revisionist.core.realism import apply
from revisionist.core.realism import effect as rx
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, Scope, Visibility, private_to
from revisionist.engine.prose import Author, Written, accepted, author_of, page_lines
from revisionist.engine.prose_context import page_context
from tests.test_engine_v2_contract import Slice
from tests.test_realism_pipelines import Rig, S, _find, _replies, _with_loyalty

ASK = "Have Stark shoot on sight west of 26 degrees"
ON = date(1941, 9, 12)


def _reported(sl: Slice, **executed: object) -> tuple[State, rx.RoutedOrder]:
    """Roosevelt's free-text command to Stark, carried out as ``executed`` says, and the
    report on it in Roosevelt's in-tray."""
    order = sl.shoot_on_sight(ask=ASK)
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(ev.OrderExecuted(order_id=order.order_id, part=0, on=ON, **executed), private_to(sl.fdr))
    report = apply.report(sl.state, sl.state.routed[order.order_id], 0, ON)
    assert report is not None
    sl.add(report, private_to(sl.fdr))
    return sl.state, order


def _page(state: State, title_start: str):  # type: ignore[no-untyped-def]
    return next(d.view for d in state.documents.values() if d.view.title.startswith(title_start))


def test_a_report_on_an_order_carries_the_readers_own_words_and_who_he_is() -> None:
    sl = Slice()
    state, _ = _reported(sl, fidelity=rx.Fidelity.FULL)
    page = _page(state, "Shoot on sight")
    ctx = page_context(state, page)
    assert ctx["asked"] == ASK
    assert ctx["to"] == {
        "name": "Franklin D. Roosevelt",
        "office": state.cards[sl.entity("roosevelt")].office,
    }
    assert ctx["purpose"] == "reply"
    assert ctx["stands"] == "answers to Franklin D. Roosevelt"


def test_the_purpose_follows_how_the_order_went() -> None:
    cases = (
        ({"fidelity": rx.Fidelity.FULL}, "reply"),
        ({"fidelity": rx.Fidelity.SLOW}, "reply"),
        ({"fidelity": rx.Fidelity.LOOSE}, "warning"),
        ({"fidelity": rx.Fidelity.PARTIAL}, "warning"),
        ({"refusal": "No shooting without a declaration"}, "refusal"),
    )
    for executed, purpose in cases:
        sl = Slice()
        state, _ = _reported(sl, **executed)
        page = _page(state, "Shoot on sight")
        assert page_context(state, page)["purpose"] == purpose, executed


def test_a_word_back_on_a_standing_form_carries_the_form_and_its_terms() -> None:
    rig = Rig()
    state = _with_loyalty(rig.state, "bram", rig.ids, 5)
    from revisionist.core.realism.pipelines import run_pipelines

    out = run_pipelines(state, rig.filed + timedelta(days=30), _find(rig, S.PASS, state))
    after = rig.add_all(out)
    _, speaker = _replies(out)
    ctx = page_context(after, after.documents[speaker.document.doc_id].view)
    assert ctx["purpose"] == "acknowledgement"
    assert ctx["asked"].startswith("Propose a levy") and "8" in ctx["asked"]
    assert ":" not in ctx["asked"]


def test_a_page_that_answers_no_order_has_no_asked_words() -> None:
    sl = Slice()
    state, _ = _reported(sl, fidelity=rx.Fidelity.FULL)
    page = _page(state, "Shoot on sight")
    other = page.model_copy(update={"doc_id": "NOT-A-REPORT"})
    ctx = page_context(state, other)
    assert "asked" not in ctx and "purpose" not in ctx
    assert ctx["to"]["name"] == "Franklin D. Roosevelt"


def test_a_public_page_has_no_context() -> None:
    sl = Slice()
    state, _ = _reported(sl, fidelity=rx.Fidelity.FULL)
    page = _page(state, "Shoot on sight")
    assert page_context(state, page.model_copy(update={"scope": PUBLIC})) == {}
    known = Scope(visibility=Visibility.PUBLIC, known_by=frozenset({sl.fdr}))
    assert page_context(state, page.model_copy(update={"scope": known})) == {}


def test_the_context_rides_on_the_author_block_and_into_the_prompt() -> None:
    sl = Slice()
    state, _ = _reported(sl, fidelity=rx.Fidelity.FULL)
    page = _page(state, "Shoot on sight")
    author = author_of(state, page.author, [page])
    assert author.context[page.doc_id]["asked"] == ASK
    assert page_lines(page, author)["context"]["asked"] == ASK
    bare = Author(entity=page.author, name="x")
    assert "context" not in page_lines(page, bare)


def test_a_figure_from_the_readers_own_words_is_not_counted_as_invented() -> None:
    sl = Slice()
    state, _ = _reported(sl, fidelity=rx.Fidelity.FULL)
    page = _page(state, "Shoot on sight")
    author = author_of(state, page.author, [page])
    text = "Mr President, the fleet will fire on sight west of 26 degrees."
    keep, dropped = accepted([page], Written(prose={page.doc_id: text}), author)
    assert keep and not dropped
    keep, dropped = accepted([page], Written(prose={page.doc_id: text + " 40 ships."}), author)
    assert not keep and "40" in dropped[0].reason
    assert accepted([page], Written(prose={page.doc_id: text}))[1]  # no author, no allowance


def test_an_order_of_another_seat_never_reaches_the_context() -> None:
    sl = Slice()
    state, order = _reported(sl, fidelity=rx.Fidelity.FULL)
    page = _page(state, "Shoot on sight")
    theirs = order.model_copy(update={"issuer": sl.wheeler})
    routed = {**state.routed, order.order_id: theirs}
    assert "asked" not in page_context(state.model_copy(update={"routed": routed}), page)


def test_the_context_carries_no_loyalty_or_hidden_card_fields() -> None:
    sl = Slice()
    state, _ = _reported(sl, fidelity=rx.Fidelity.FULL)
    page = _page(state, "Shoot on sight")
    ctx = page_context(state, page)
    assert set(ctx) <= {"to", "stands", "asked", "purpose", "author_aims"}
    stark = state.cards[EntityId(page.author)]
    assert str(stark.loyalty) not in str(ctx.get("stands", ""))
