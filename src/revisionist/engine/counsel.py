"""Counsel (realism, Phase 4): a seat consults a person on its card and hears them out.

The counsel model speaks as that person from a ``PersonView`` (their face, their
voice, the pages they hold as of today, the news, and the asker's desk when they serve
the asker, from ``core.realism.person``), never from ``State``. Counsel changes nothing
in the world, costs no in-world days [proposed] and never files an order: the reply
lands as a ``counsel_held`` record private to the seat, sealed with the seat's key, and
the call's cost as ``cost_logged``.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from revisionist.core import events as ev
from revisionist.core._base import Model
from revisionist.core.events import CallCost, Event
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, EventId, SeatId
from revisionist.core.ontology import Controller, EntityKind, EntityStatus
from revisionist.core.project import project
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import BodyField
from revisionist.core.realism.person import PersonView, project_person
from revisionist.core.realism.reach import channels_to, takes_meeting
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine import campaign as cmp
from revisionist.engine.ids import new_id
from revisionist.engine.llm import Request, Transport, prompt_text, prompt_version
from revisionist.engine.store import EventStore, load_state

COUNSEL_MODEL = "claude-sonnet-5-5"
"""[proposed] ``REVISIONIST_MODEL_COUNSEL`` overrides it per call."""
QUESTION_MAX = 1000


class Asker(Model):
    """Who puts the question: the seat's person as anyone sees them."""

    name: str
    office: str = ""


class Spoken(Model):
    text: str
    cost: CallCost | None = None


class Counsellor(Protocol):
    """A person's view and a question in, their words out. Never takes a ``State``."""

    def speak(
        self, person: PersonView, asker: Asker, channel: ChannelKind, question: str
    ) -> Spoken: ...


COUNSEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


def _lines(body: Sequence[BodyField]) -> list[dict[str, Any]]:
    return [
        {
            "label": x.label,
            "value": "not stated" if x.value is None else x.value,
            **({"unit": x.unit} if x.unit else {}),
        }
        for x in body
    ]


def counsel_prompt(person: PersonView, asker: Asker, channel: ChannelKind, question: str) -> str:
    """The person first (stable across questions, so a provider cache can reuse it), then
    their papers, the news and their principal's mandates where they have any, then the
    question."""
    if not isinstance(person, PersonView):
        raise TypeError(f"counsel takes a PersonView, not {type(person).__name__}")
    office = person.face.office if person.face is not None else ""
    head = f"## You are\n{person.name}" + (f", {office}" if office else "")
    voice = f"\nVoice: {person.voice}" if person.voice else ""
    papers = [
        {
            "kind": d.kind.value,
            "title": d.title,
            "issued": d.issued.isoformat(),
            "channel": d.channel.value,
            "lines": _lines(d.body),
            **({"text": d.prose} if d.prose else {}),
        }
        for d in person.documents
    ]
    news = [
        {
            "on": n.on.isoformat(),
            "headline": n.headline,
            **({"lines": _lines(n.facts)} if n.facts else {}),
        }
        for n in person.news
    ]
    blocks = f"## Your papers\n{json.dumps(papers, ensure_ascii=False)}\n\n"
    if news:
        blocks += f"## The news\n{json.dumps(news, ensure_ascii=False)}\n\n"
    if person.mandates:
        blocks += (
            f"## Before your principal\n{json.dumps(list(person.mandates), ensure_ascii=False)}\n\n"
        )
    who = asker.name + (f", {asker.office}" if asker.office else "")
    return (
        f"{head}{voice}\n\n## Today\n{person.today.isoformat()}\n\n{blocks}"
        f"## {who} asks you, by {channel.value.replace('_', ' ')}\n{question}"
    )


@dataclass
class ClaudeCounsellor:
    transport: Transport
    model: str = COUNSEL_MODEL
    max_usd: float = 0.25
    requests: list[Request] = field(default_factory=list)

    def speak(
        self, person: PersonView, asker: Asker, channel: ChannelKind, question: str
    ) -> Spoken:
        req = Request(
            call_class="counsel",
            model=self.model,
            system=prompt_text("counsel"),
            prompt=counsel_prompt(person, asker, channel, question),
            schema=COUNSEL_SCHEMA,
            max_usd=self.max_usd,
        )
        self.requests.append(req)
        reply = self.transport.call(req)
        text = reply.output.get("text", "") if isinstance(reply.output, dict) else ""
        return Spoken(text=text.strip(), cost=reply.cost("counsel"))


class CounselRefusedError(ValueError):
    pass


class Counsel(Model):
    person: str
    channel: ChannelKind
    text: str
    event_id: EventId


def consult(
    store: EventStore,
    campaign_id: CampaignId,
    seat: SeatId,
    person: EntityId,
    question: str,
    counsellor: Counsellor,
) -> Counsel:
    """Put ``question`` to ``person`` over the seat's channel to them: the card's channel for
    the inner circle, else the first channel that reaches them, and then the person may
    decline as they would a meeting (one roll per tick, whatever the words). An outsider,
    or a person another seat holds, speaks only from pages the seat also holds; a person
    another human plays is never voiced, and no roll is spent on them. Raises
    ``CounselRefusedError`` for a person another human plays, anyone the seat cannot
    reach, an outsider who declines, or an empty question; ``TransportError`` propagates
    and nothing is written."""
    state = load_state(store, campaign_id)
    if state.ruleset != "realism":
        raise CounselRefusedError("counsel is for realism campaigns")
    question = question.strip()
    if not question or len(question) > QUESTION_MAX:
        raise CounselRefusedError(f"ask a question of 1 to {QUESTION_MAX} characters")
    me = state.seats[seat]
    if _played_by_another(state, seat, person):
        raise CounselRefusedError(
            f"{state.entities[person].name} speaks for themselves: write to them."
        )
    card = state.cards.get(me.embodies)
    contact = next((c for c in card.inner_circle if c.person == person), None) if card else None
    channel = contact.channel if contact is not None else _outer_channel(state, seat, person)
    if card is None or channel is None:
        names = ", ".join(state.entities[c.person].name for c in card.inner_circle) if card else ""
        raise CounselRefusedError(
            f"{state.entities[person].name if person in state.entities else person} is not "
            f"within your reach" + (f" (you can consult: {names})" if names else "")
        )
    if contact is None and not takes_meeting(state, me.embodies, person, "counsel", state.tick):
        raise CounselRefusedError(f"{state.entities[person].name} did not answer.")
    asker = Asker(name=state.entities[me.embodies].name, office=card.office)
    seen = project_person(state, person, seat)
    spoken = counsellor.speak(seen, asker, channel, question)
    if not spoken.text:
        raise CounselRefusedError(f"{state.entities[person].name} had nothing to say")
    text = f"You asked: {question}\n\n{spoken.text}"[:8000]
    versions = cmp.versions()
    versions = versions.model_copy(
        update={"prompt": f"{versions.prompt},counsel={prompt_version('counsel')}"}
    )
    held = Event(
        event_id=EventId(new_id()),
        campaign_id=campaign_id,
        seq=state.last_seq + 1,
        tick=state.tick,
        actor=seat,
        scope=private_to(seat),
        payload=ev.CounselHeld(seat_id=seat, person=person, channel=channel, text=text),
        versions=versions,
    )
    batch = [held]
    if spoken.cost is not None:
        batch.append(
            Event(
                event_id=EventId(new_id()),
                campaign_id=campaign_id,
                seq=state.last_seq + 2,
                tick=state.tick,
                actor=seat,
                scope=private_to(seat),
                payload=ev.CostLogged(seat_id=seat, purpose="counsel", costs=(spoken.cost,)),
                versions=versions,
            )
        )
    replay(batch, initial=state)
    store.append_all(batch)
    return Counsel(
        person=state.entities[person].name,
        channel=channel,
        text=text,
        event_id=held.event_id,
    )


def _played_by_another(state: State, seat: SeatId, person: EntityId) -> bool:
    """Whether a human holds ``person`` from a seat other than ``seat``."""
    return any(
        s.seat_id != seat and s.embodies == person and s.controller is Controller.HUMAN
        for s in state.seats.values()
    )


def _outer_channel(state: State, seat: SeatId, person: EntityId) -> ChannelKind | None:
    """The first channel from the seat to a living person it can see, or None."""
    me = state.seats[seat].embodies
    who = state.entities.get(person)
    if who is None or who.kind is not EntityKind.PERSON or who.status is EntityStatus.DEAD:
        return None
    if person == me or person not in project(state, seat).entities:
        return None
    channels = channels_to(state, me, person)
    return channels[0] if channels else None


def counsel_records(events: Sequence[Event], seat: SeatId) -> list[ev.CounselHeld]:
    """The seat's counsel, oldest first: its in-tray of conversations."""
    return [
        e.payload
        for e in events
        if isinstance(e.payload, ev.CounselHeld) and e.payload.seat_id == seat
    ]


__all__ = [
    "COUNSEL_MODEL",
    "Asker",
    "ClaudeCounsellor",
    "Counsel",
    "CounselRefusedError",
    "Counsellor",
    "Spoken",
    "consult",
    "counsel_prompt",
    "counsel_records",
]
