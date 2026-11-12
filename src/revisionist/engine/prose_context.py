"""Why a page is written, for the prose writer (letters, train L).

The writer takes views only, so what it may know about a page beyond its lines is read
from state here and handed over as plain data on the ``Author`` block: who the page goes
to, the reader's own words for the order the page answers, what the page is for, how the
author stands to the reader, and the author's own aims (an author may give a view only
where it follows from them).

Only a private page held by one seat gets a context: a public page is addressed to no
one. An order's words reach a page only when the page is the paper on that order and the
order is the holder's own, so nothing another seat asked can reach a reader.
"""

from typing import Any

from revisionist.core.ids import DocumentId
from revisionist.core.realism.apply import outcome, report_doc_id
from revisionist.core.realism.document import DocumentView
from revisionist.core.realism.effect import Fidelity, Route, RoutedPart
from revisionist.core.realism.pipelines import order_words, reply_doc_id
from revisionist.core.state import State
from revisionist.core.visibility import Visibility

_WARNS = {Fidelity.LOOSE, Fidelity.PARTIAL}


def _purpose(part: RoutedPart) -> str:
    """What a paper on a routed part is for, from how the part went."""
    if part.route is Route.INFLUENCE:
        return "reply" if outcome(part) == "agreed" else "refusal"
    if part.refusal:
        return "refusal"
    return "warning" if part.fidelity in _WARNS else "reply"


def _answered(state: State, page: DocumentView) -> tuple[str, str] | None:
    """The holder's own words for the order ``page`` is the paper on, and the page's
    purpose; None when the page answers no order of the holder's."""
    (holder,) = page.scope.known_by
    for order in state.routed.values():
        if order.issuer != holder:
            continue
        for n, part in enumerate(order.parts):
            if report_doc_id(state.campaign_id, order.order_id, n) == page.doc_id:
                return part.ask, _purpose(part)
    for drafted in state.orders.values():
        if drafted.issuer != holder:
            continue
        ids = {
            reply_doc_id(state.campaign_id, drafted.order_id, n)
            for n in range(len(drafted.outcomes) + 1)
        }
        if page.doc_id in ids:
            ref = drafted.routed_from
            words = (
                state.routed[ref.order_id].parts[ref.part].ask
                if ref is not None and ref.order_id in state.routed
                else ""
            )
            return words or order_words(state, drafted), "acknowledgement"
    return None


def page_context(state: State, page: DocumentView) -> dict[str, Any]:
    """The context for one page, or an empty dict when it has no single reader."""
    if page.scope.visibility is Visibility.PUBLIC or len(page.scope.known_by) != 1:
        return {}
    (holder,) = page.scope.known_by
    reader = state.seats[holder].embodies
    reader_card = state.cards.get(reader)
    name = state.entities[reader].name
    ctx: dict[str, Any] = {
        "to": {"name": name, **({"office": reader_card.office} if reader_card else {})}
    }
    card = state.cards.get(page.author)
    if card is not None and reader in card.principals:
        ctx["stands"] = f"answers to {name}"
    elif reader_card is not None and any(c.person == page.author for c in reader_card.inner_circle):
        ctx["stands"] = f"in {name}'s inner circle"
    if (answered := _answered(state, page)) is not None:
        asked, purpose = answered
        if asked:
            ctx["asked"] = asked
        ctx["purpose"] = purpose
    elif (doc := state.documents.get(DocumentId(page.doc_id))) is not None and doc.truth.feed:
        ctx["purpose"] = "report"
    if card is not None and card.aims:
        ctx["author_aims"] = list(card.aims)
    return ctx


__all__ = ["page_context"]
