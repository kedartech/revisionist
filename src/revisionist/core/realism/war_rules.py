"""What a state of war allows and forbids, and what it sets in motion."""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId, FeatureId, SeatId, derived_id
from revisionist.core.ontology import EntityKind
from revisionist.core.realism import actors, reach, supply, territory
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.bases import Tier
from revisionist.core.realism.bases import reach as reach_of
from revisionist.core.realism.card import ChannelKind, Desk
from revisionist.core.realism.detachments import DETACHMENTS_PER_SIDE
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.effect import Engagement, SetEngagement
from revisionist.core.realism.geography import FORCES, Feature, FeatureKind, in_play
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


def _detach_refusal(state: State, params: dict[str, str]) -> str:
    """Why part of this force may not be detached: its side has as many detachments of its
    kind in play as it may, or the force would keep less than strength 1. Empty if it may,
    and for a force or strength the order does not name in a form the engine can read."""
    force = state.features.get(
        FeatureId(object_id(state.campaign_id, "feature", params.get("force", "")))
    )
    try:
        strength = int(params.get("strength", ""))
    except ValueError:
        return ""
    if force is None or force.kind not in FORCES or force.side is None:
        return ""
    kind = force.kind.value
    cap = DETACHMENTS_PER_SIDE[force.kind]
    if cap == 0:
        article = "an" if kind[0] in "aeiou" else "a"
        return f"No side may detach part of {article} {kind}."
    out = sum(
        f.kind is force.kind and f.side == force.side and f.detached_from is not None and in_play(f)
        for f in state.features.values()
    )
    if out >= cap:
        return _clip(
            f"{state.entities[force.side].name} already has {cap} {kind} detachments out, "
            "the most a side may have at once.",
            REFUSAL,
        )
    if force.tier - strength < 1:
        return _clip(
            f"{force.name} has strength {force.tier}, "
            f"so at most {max(force.tier - 1, 0)} of it can be detached.",
            REFUSAL,
        )
    return ""


def _reach_refusal(state: State, seat: SeatId, lever: str, params: dict[str, str]) -> str:
    """Why the seat's own force may not be sent where the order says: the place is beyond
    what its side's bases allow. Empty if it may, and for anything the movement rule does
    not act on."""
    card = state.cards.get(state.seats[seat].embodies)
    found = None if card is None else next((x for x in card.levers if x.name == lever), None)
    if found is None or found.resolver != "movement":
        return ""
    force = state.features.get(
        FeatureId(object_id(state.campaign_id, "feature", params.get("force", "")))
    )
    to = _world_entity(state, params.get("to", ""))
    if force is not None and to is not None and force.kind is FeatureKind.PIECE:
        return _step_refusal(state, force, to)
    if force is None or force.kind not in FORCES or to is None:
        return ""
    found_reach = reach_of(state, force, to)
    if found_reach is None or found_reach.tier is not Tier.REFUSED:
        return ""
    return _clip(found_reach.reason or "", REFUSAL)


def _step_refusal(state: State, piece: Feature, to: EntityId) -> str:
    """Why a piece may not be sent to ``to`` by adjacency, naming the nearest area it could be
    sent to; empty if it may, or when ``territories`` is off."""
    if not territory.on(state):
        return ""
    found = territory.plan(state, piece, to)
    if not isinstance(found, territory.Plan):
        return _clip(found.reason, REFUSAL)
    return _supply_refusal(state, piece, found)


def _supply_refusal(state: State, piece: Feature, course: territory.Plan) -> str:
    """Why a piece out of supply may not be sent into territory an enemy holds: the first
    such area on its course, and the nearest area it would be supplied in. Empty if it may."""
    found = supply.status(state, piece)
    own = territory.nation(state, piece.side)
    if found is None or found.supplied or own is None:
        return ""
    for area in course.path:
        held = territory.holder(state, area)
        if held is None or not at_war(state, own, held):
            continue
        words = (
            f"{piece.name} is out of supply, so it cannot be sent into "
            f"{state.entities[area].name}, held by {state.entities[held].name}."
        )
        if found.nearest is not None:
            near = state.entities[found.nearest].name
            words += f" The nearest area it would be supplied in is {near}."
        return _clip(words, REFUSAL)
    return ""


def order_refusal(state: State, seat: SeatId, lever: str, params: dict[str, str]) -> str:
    """The words for why the seat may not pull this lever now; empty if it may."""
    own = _own_polity(state, seat)
    if own is None:
        return ""
    if refused := _reach_refusal(state, seat, lever, params):
        return refused
    if lever == "detach_fleet":
        return _detach_refusal(state, params)
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
        if f.kind in FORCES and in_play(f) and f.side is not None and f.places[0] == place
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
    """Each seat that commands the force, with the person who answers for it. A
    detachment answers to whoever commands the force it was detached from."""
    held = state.features.get(fid)
    if held is not None and held.detached_from is not None:
        fid = held.detached_from
    out: list[tuple[SeatId, EntityId]] = []
    for card in state.cards.values():
        if not isinstance(card, Desk):
            continue
        domain = next((d for d in card.authority if fid in d.forces), None)
        if domain is None:
            continue
        author = domain.executor if domain.executor is not None else card.person
        out.extend(
            (seat.seat_id, author)
            for seat in state.seats.values()
            if seat.embodies == card.person and seat.seat_id in actors.readers(state)
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
        (f for f in state.features.values() if f.kind in FORCES and in_play(f)),
        key=lambda f: f.feature_id,
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
