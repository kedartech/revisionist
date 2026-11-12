"""What a force's arrival sets going: the commanding seat's report of it (spec §8.3)."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId, FeatureId, SeatId, derived_id
from revisionist.core.realism import actors, reach
from revisionist.core.realism.card import ChannelKind, Desk, words
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.geography import Sight, SightRef
from revisionist.core.state import State
from revisionist.core.visibility import private_to

LINE = 60


def _clip(text: str) -> str:
    return text if len(text) <= LINE else text[: LINE - 1] + "…"


def _arrived(before: State, after: State) -> list[FeatureId]:
    """The forces that reached the place they were bound for between the two states."""
    out: list[FeatureId] = []
    for fid, ft in after.features.items():
        was = before.features.get(fid)
        if was is None or was.bound_for is None or ft.bound_for is not None:
            continue
        if ft.places == (was.bound_for,):
            out.append(fid)
    return out


def _report(
    after: State, fid: FeatureId, person: EntityId, author: EntityId, seat: SeatId, day: date
) -> ev.DocumentIssued | None:
    """The page one seat gets for one arrival, or None when it already has it."""
    doc_id = DocumentId(derived_id(after.campaign_id, "arrival", fid, day.isoformat(), seat))
    if doc_id in after.documents:
        return None
    ft = after.features[fid]
    where = " \N{EN DASH} ".join(after.entities[p].name for p in ft.places)
    body = [BodyField(label="Position", value=_clip(where))]
    if ft.posture is not None:
        body.append(BodyField(label="Posture", value=words(ft.posture.value)))
    if ft.engagement is not None:
        body.append(BodyField(label="Rule", value=words(ft.engagement.value)))
    body.append(
        BodyField(
            label=ft.name,
            value=_clip(where),
            sight=Sight(kind=ft.kind, side=ft.side, places=ft.places),
        )
    )
    channels = reach.channels_to(after, author, person) if author != person else ()
    channel = channels[0] if channels else ChannelKind.IN_PERSON
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.REPORT,
            author=author,
            issued=day,
            arrives=day + timedelta(days=reach.transit_days(channel)),
            channel=channel,
            classification=Classification.CONFIDENTIAL,  # [proposed]
            title=_clip(f"{ft.name} has reached {where}"),
            body=tuple(body),
            scope=private_to(seat),
        ),
        truth=DocumentTruth(doc_id=doc_id, sightings=(SightRef(feature_id=fid, places=ft.places),)),
    )


def arrivals(before: State, after: State, day: date) -> list[ev.Payload]:
    """One report per arrival per seat that commands the force, on the day it lands."""
    out: list[ev.Payload] = []
    for fid in _arrived(before, after):
        for card in after.cards.values():
            if not isinstance(card, Desk):
                continue
            domain = next((d for d in card.authority if fid in d.forces), None)
            if domain is None:
                continue
            author = domain.executor if domain.executor is not None else card.person
            for seat in after.seats.values():
                if seat.embodies != card.person or seat.seat_id not in actors.readers(after):
                    continue
                doc = _report(after, fid, card.person, author, seat.seat_id, day)
                if doc is not None:
                    out.append(doc)
    return out
