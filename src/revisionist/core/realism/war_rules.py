"""What a state of war allows and forbids, and what it sets in motion."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId, FeatureId, SeatId, derived_id
from revisionist.core.ontology import EntityKind
from revisionist.core.realism import reach
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.card import ChannelKind, Desk
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.effect import Engagement, SetEngagement
from revisionist.core.realism.geography import FORCES, Feature
from revisionist.core.realism.war import NewsEvent, NewsTopic, War, at_war, polity_of
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.core.world_compile import object_id

LINE = 60
REFUSAL = 200


def _clip(text: str, limit: int = LINE) -> str:
    """The text cut to ``limit`` characters."""
    return text if len(text) <= limit else text[: limit - 1] + "\N{HORIZONTAL ELLIPSIS}"


def _world_entity(state: State, key: str) -> EntityId | None:
    """The entity for a world-file key, if the world has it."""
    found = EntityId(object_id(state.campaign_id, "entity", key))
    return found if found in state.entities else None


def _own_polity(state: State, seat: SeatId) -> EntityId | None:
    """The polity of the person the seat embodies."""
    held = state.seats.get(seat)
    return polity_of(state, held.embodies) if held is not None else None


def order_refusal(state: State, seat: SeatId, lever: str, params: dict[str, str]) -> str:
    """The words for why the seat may not pull this lever now; empty if it may."""
    own = _own_polity(state, seat)
    if own is None:
        return ""
    if lever == "uboat_directive" and params.get("posture") == "attack_us_shipping":
        usa = _world_entity(state, "usa")
        if usa is None or at_war(state, own, usa):
            return ""
        return _clip(
            f"{state.entities[own].name} is not at war with {state.entities[usa].name}, "
            "so the U-boats cannot be ordered to attack American ships on sight.",
            REFUSAL,
        )
    if lever == "declare_war":
        target = _world_entity(state, params.get("target", ""))
        if target is not None and target == own:
            return _clip(f"{state.entities[own].name} cannot declare war on itself.", REFUSAL)
        if target is not None and state.entities[target].kind is not EntityKind.POLITY:
            return _clip(
                f"{state.entities[target].name} is not a power to declare war on.", REFUSAL
            )
        if target is not None and at_war(state, own, target):
            return _clip(
                f"{state.entities[own].name} is already at war with {state.entities[target].name}.",
                REFUSAL,
            )
    return ""


def _zone_place(state: State, zone: str) -> EntityId | None:
    """The place a zone names: the reader gives a place's id or its name."""
    if EntityId(zone) in state.entities:
        return EntityId(zone)
    wanted = zone.strip().casefold()
    return next((e.entity_id for e in state.entities.values() if e.name.casefold() == wanted), None)


def ask_refusal(state: State, seat: SeatId, ask: Ask) -> str:
    """The words for why a free-text order to shoot on sight may not stand; empty if it may.

    It is refused when the zone holds forces of a power the seat's polity is not at war
    with, and none of a power it is at war with: the same line ``order_refusal`` draws
    for the menu's attack order.
    """
    effect = ask.effect
    if not isinstance(effect, SetEngagement) or effect.rule is not Engagement.SHOOT_ON_SIGHT:
        return ""
    own = _own_polity(state, seat)
    place = _zone_place(state, effect.zone)
    if own is None or place is None:
        return ""
    sides = {
        polity_of(state, f.side)
        for f in state.features.values()
        if f.kind in FORCES and f.side is not None and f.places[0] == place
    }
    others = sorted(
        (s for s in sides if s is not None and s != own), key=lambda s: state.entities[s].name
    )
    if not others or any(at_war(state, own, s) for s in others):
        return ""
    return _clip(
        f"{state.entities[own].name} is not at war with {state.entities[others[0]].name}, "
        f"so forces in {state.entities[place].name} cannot be ordered to shoot on sight.",
        REFUSAL,
    )


def _in_contact(war: War, a: Feature, b: Feature) -> bool:
    """Whether two forces of the warring sides sit at one place, neither under way."""
    return (
        a.side == war.a
        and b.side == war.b
        and a.bound_for is None
        and b.bound_for is None
        and a.places[0] == b.places[0]
    )


def _commanders(state: State, fid: FeatureId) -> list[tuple[SeatId, EntityId]]:
    """Each seat that commands the force, with the person who answers for it."""
    out: list[tuple[SeatId, EntityId]] = []
    for card in state.cards.values():
        if not isinstance(card, Desk):
            continue
        domain = next((d for d in card.authority if fid in d.forces), None)
        if domain is None:
            continue
        author = domain.executor if domain.executor is not None else card.person
        out.extend(
            (seat.seat_id, author) for seat in state.seats.values() if seat.embodies == card.person
        )
    return sorted(out)


def _report(
    state: State, news: NewsEvent, mine: Feature, other: Feature, seat: SeatId, author: EntityId
) -> ev.DocumentIssued | None:
    """The page one commander gets for one contact, or None when it already has it."""
    doc_id = DocumentId(derived_id(state.campaign_id, "contact", news.news_id, seat))
    held = state.seats[seat]
    if doc_id in state.documents:
        return None
    channels = reach.channels_to(state, author, held.embodies) if author != held.embodies else ()
    channel = channels[0] if channels else ChannelKind.IN_PERSON
    place = state.entities[mine.places[0]].name
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.REPORT,
            author=author,
            issued=news.on,
            arrives=news.on + timedelta(days=reach.transit_days(channel)),
            channel=channel,
            classification=Classification.CONFIDENTIAL,  # [proposed]
            title=_clip(f"{mine.name} has met {other.name} at {place}"),
            body=(BodyField(label="Place", value=_clip(place)),),
            scope=private_to(seat),
        ),
        truth=DocumentTruth(doc_id=doc_id, news_id=news.news_id),
    )


def contacts(state: State, day: date) -> list[ev.Payload]:
    """What forces in contact do on ``day``: one news item and a report to each commander."""
    forces = sorted(
        (f for f in state.features.values() if f.kind in FORCES), key=lambda f: f.feature_id
    )
    out: list[ev.Payload] = []
    issued: set[DocumentId] = set()
    for war in sorted(state.wars.values(), key=lambda w: w.war_id):
        for a in forces:
            for b in forces:
                if not _in_contact(war, a, b):
                    continue
                place = a.places[0]
                news_id = derived_id(
                    state.campaign_id, "contact", war.war_id, a.feature_id, b.feature_id, place
                )
                if news_id in state.news:
                    continue
                powers = (state.entities[war.a].name, state.entities[war.b].name)
                news = NewsEvent(
                    news_id=news_id,
                    on=day,
                    topic=NewsTopic.CONTACT,
                    subject=war.a,
                    obj=war.b,
                    facts=(BodyField(label="Powers", value=_clip(f"{powers[0]} and {powers[1]}")),),
                    headline=_clip(f"Forces of {powers[0]} and {powers[1]} in contact"),
                )
                out.append(ev.NewsReported(news=news))
                for mine, other in ((a, b), (b, a)):
                    for seat, author in _commanders(state, mine.feature_id):
                        doc = _report(state, news, mine, other, seat, author)
                        if doc is not None and doc.document.doc_id not in issued:
                            issued.add(doc.document.doc_id)
                            out.append(doc)
    return out
