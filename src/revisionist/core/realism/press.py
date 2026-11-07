"""Each seat's press: public news worded in its own outlet's voice (engine v2, consequences)."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId, SeatId, derived_id
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.war import NewsEvent, Outlet, outlet_for
from revisionist.core.state import State
from revisionist.core.visibility import Scope, Visibility

LINE = 60


def _clip(text: str) -> str:
    """Cut to the label limit with a trailing ellipsis."""
    return text if len(text) <= LINE else text[: LINE - 1] + "…"


def _page(
    state: State, news: NewsEvent, outlet: Outlet, readers: frozenset[SeatId], day: date
) -> ev.DocumentIssued | None:
    """The outlet's page for one event, or None when it is already printed."""
    doc_id = DocumentId(derived_id(state.campaign_id, "press", news.news_id, outlet.outlet_id))
    if doc_id in state.documents:
        return None
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.PRESS,
            author=outlet.outlet_id,
            issued=day,
            arrives=day,
            channel=ChannelKind.PRESS,
            classification=Classification.OPEN,
            title=_clip(f"{outlet.name}: {news.headline}"),
            body=news.facts,
            scope=Scope(visibility=Visibility.PRIVATE, known_by=readers),
        ),
        truth=DocumentTruth(doc_id=doc_id, news_id=news.news_id),
    )


def news_pages(state: State, day: date) -> list[ev.DocumentIssued]:
    """One page per reported event per outlet that some seat reads, once the event is due."""
    readers: dict[EntityId, set[SeatId]] = {}
    for seat in state.seats:
        outlet = outlet_for(state, seat)
        if outlet is not None:
            readers.setdefault(outlet.outlet_id, set()).add(seat)
    out: list[ev.DocumentIssued] = []
    for news_id in sorted(state.news):
        news = state.news[news_id]
        if news.on > day:
            continue
        for outlet_id in sorted(readers):
            page = _page(state, news, state.outlets[outlet_id], frozenset(readers[outlet_id]), day)
            if page is not None:
                out.append(page)
    return out
