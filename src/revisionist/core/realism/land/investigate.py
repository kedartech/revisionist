"""Landing an Investigate effect: a private report of what the issuing seat already sees."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId, FactId, SeatId, derived_id
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.effect import Investigate
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.state import State
from revisionist.core.visibility import private_to

REPORT_FACTS = 5  # [proposed]
TRANSIT_DAYS = 2  # [proposed]
TITLE = 60


def land(
    world: PassWorld, effect: Investigate, issuer_seat: SeatId, issuer: EntityId, on: date
) -> tuple[list[ev.Payload], list[FactId]]:
    """The issuer's own report on the target, built from facts the issuer can see."""
    state = world.state
    doc_id = DocumentId(
        derived_id(
            state.campaign_id, "inquiry", issuer, effect.target, effect.question, on.isoformat()
        )
    )
    if not world.claim(doc_id, state.documents):
        return [], []
    seen = sorted(
        (
            f
            for f in state.facts.values()
            if f.subject == effect.target and f.scope.visible_to(issuer_seat)
        ),
        key=lambda f: f.fact_id,
    )[:REPORT_FACTS]
    body = tuple(BodyField(label=f.predicate, value=_words(state, f.obj)) for f in seen) or (
        BodyField(label="Found", value="Nothing yet"),
    )
    name = state.entities[effect.target].name if effect.target in state.entities else "someone"
    title = f"Inquiry into {name}"
    if len(title) > TITLE:
        title = title[: TITLE - 1] + "…"
    document = DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.REPORT,
        author=issuer,
        issued=on,
        arrives=on + timedelta(days=TRANSIT_DAYS),
        channel=ChannelKind.IN_PERSON,
        classification=Classification.CONFIDENTIAL,  # [proposed]
        title=title,
        body=body,
        scope=private_to(issuer_seat),
    )
    return [ev.DocumentIssued(document=document, truth=DocumentTruth(doc_id=doc_id))], []


def _words(state: State, obj: str) -> str:
    """An entity id in words; any other label as it is."""
    if obj in state.entities:
        return state.entities[EntityId(obj)].name
    return obj
