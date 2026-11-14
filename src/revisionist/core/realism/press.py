"""Each seat's press: public news worded in its own outlet's voice (engine v2, consequences)."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId, SeatId, derived_id
from revisionist.core.realism import actors
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.war import (
    NEUTRAL,
    OPPOSITION,
    NewsEvent,
    Outlet,
    paper_of,
    polity_of,
    tagged,
)
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


def _adversary(state: State, person: EntityId, polity: EntityId) -> Outlet | None:
    """The home paper of the first power the person's card opposes that is not their own
    and has a paper; failing that, of a power at war with theirs."""
    card = state.cards.get(person)
    against = [polity_of(state, c.against) for c in card.opposes] if card is not None else []
    for war in sorted(state.wars.values(), key=lambda w: w.war_id):
        if polity in (war.a, war.b):
            against.append(war.b if war.a == polity else war.a)
    for other in against:
        if other is not None and other != polity:
            paper = paper_of(state, other)
            if paper is not None:
                return paper
    return None


def papers(state: State, person: EntityId) -> tuple[Outlet, ...]:
    """The papers a person's desk reads: home, then the domestic opposition's or else a
    neutral one, then an adversary's. None at all where their country has no paper."""
    polity = polity_of(state, person)
    home = paper_of(state, polity) if polity is not None else None
    if polity is None or home is None:
        return ()
    second = tagged(state, OPPOSITION, polity) or tagged(state, NEUTRAL)
    out: list[Outlet] = []
    for paper in (home, second, _adversary(state, person, polity)):
        if paper is not None and paper not in out:
            out.append(paper)
    return tuple(out)


def news_pages(state: State, day: date) -> list[ev.DocumentIssued]:
    """One page per reported event per outlet that some seat reads, once the event is due."""
    readers: dict[EntityId, set[SeatId]] = {}
    for seat in sorted(actors.readers(state)):
        for outlet in papers(state, state.seats[seat].embodies):
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
