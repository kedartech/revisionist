"""``project_person(state, person, asker) -> PersonView``: what one person on a card knows
when a seat consults them.

Counsel speaks as a person who need not hold a seat (Hopkins, Hull), so the seat
projection does not fit. A person holds the pages they wrote, the pages from
the feeds on their own card and any page whose scope admits a seat that
embodies them, each once it has arrived. A person outside the asker's inner
circle, or one any other seat holds (a human's or an AI's), speaks only from the
pages the asker also holds, so no seat's papers reach another through counsel;
the asker's own person is never narrowed. Everyone knows the public news to date,
and a person who serves the asker (the asker's person is among their card's
principals) also knows the asker's desk: its pages and its live mandates. Only
``DocumentView`` halves are copied, and the card shows as its face plus its
voice: loyalty, doctrine and interests never leave the state.
"""

from datetime import date

from pydantic import Field

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.realism.agenda import MandateStatus
from revisionist.core.realism.card import CardFace
from revisionist.core.realism.document import DocumentView
from revisionist.core.realism.war import NewsEvent
from revisionist.core.state import State


class PersonView(Model):
    """One person's knowledge, as the counsel model may read it. Never truth."""

    person: EntityId
    name: Label
    face: CardFace | None = None
    voice: str = Field(default="", max_length=200)
    today: date
    documents: tuple[DocumentView, ...] = ()
    """Arrived pages this person holds, oldest first."""
    news: tuple[NewsEvent, ...] = ()
    """Public news to date, oldest first."""
    mandates: tuple[str, ...] = ()
    """The asker's live mandates, only when this person serves the asker."""


def project_person(state: State, person: EntityId, asker: SeatId) -> PersonView:
    """What ``person`` knows today when the seat ``asker`` consults them. Which seats
    hold the person is read from ``state`` as it stands."""
    if person not in state.entities:
        raise KeyError(f"unknown person {person!r}")
    today = state.in_world_date
    if today is None:
        raise ValueError("a person projection needs an in-world date")
    card = state.cards.get(person)
    feeds = set(card.feeds) if card is not None else set()
    seats = {s.seat_id for s in state.seats.values() if s.embodies == person}
    me = state.seats[asker].embodies
    mine = state.cards.get(me)
    inner = mine is not None and any(c.person == person for c in mine.inner_circle)
    narrow = person != me and (not inner or bool(seats - {asker}))
    serves = card is not None and me in card.principals
    held = [
        d.view
        for d in state.documents.values()
        if d.view.arrives <= today
        and (
            (serves and d.view.scope.visible_to(asker))
            or (
                (not narrow or d.view.scope.visible_to(asker))
                and (
                    d.view.author == person
                    or (d.truth.feed is not None and d.truth.feed in feeds)
                    or any(d.view.scope.visible_to(s) for s in seats)
                )
            )
        )
    ]
    desk = sorted(
        (
            m
            for m in state.mandates.values()
            if serves and m.status is MandateStatus.LIVE and m.scope.visible_to(asker)
        ),
        key=lambda m: (m.issued, m.mandate_id),
    )
    return PersonView(
        person=person,
        name=state.entities[person].name,
        face=card.face() if card is not None else None,
        voice=card.voice if card is not None else "",
        today=today,
        documents=tuple(sorted(held, key=lambda v: (v.issued, v.doc_id))),
        news=tuple(
            sorted(
                (n for n in state.news.values() if n.on <= today),
                key=lambda n: (n.on, n.news_id),
            )
        ),
        mandates=tuple(m.text for m in desk),
    )


__all__ = ["PersonView", "project_person"]
