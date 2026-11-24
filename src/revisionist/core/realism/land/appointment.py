"""Landing an Appointment effect in the world: a public office fact and public news, and
with ``posts`` on the change of post itself (PPR)."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import AssetId, EntityId, FactId, SeatId, derived_id
from revisionist.core.ontology import AssetKind, EntityStatus, Fact
from revisionist.core.realism import ladder, posts
from revisionist.core.realism.card import PostCause
from revisionist.core.realism.document import BodyField
from revisionist.core.realism.effect import Appointment
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.war import NewsEvent, NewsTopic, polity_of
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC


def land(
    world: PassWorld, effect: Appointment, issuer_seat: SeatId, issuer: EntityId, on: date
) -> tuple[list[ev.Payload], list[FactId]]:
    """The office as a public fact and the appointment as public news, each folded once.
    With ``posts`` on and an office that is a post, the pending change instead (LDR): the
    post moves at the close of the next wake, and its news with it. With ``posts`` on and
    an office that is a post with no ladder, the post moves the day it lands (PPR)."""
    state = world.state
    pending = ladder.order(state, effect.person, effect.office, effect.appoint, issuer, on)
    if pending is not None:
        first = pending[0]
        if isinstance(first, ev.PostMoveOrdered) and not world.claim(
            first.move.move_id, state.post_moves
        ):
            return [], []
        return pending, []
    verb = "appoint" if effect.appoint else "dismiss"
    fact_id = FactId(
        derived_id(
            state.campaign_id,
            "fact",
            "appointment",
            effect.person,
            effect.office,
            verb,
            on.isoformat(),
        )
    )
    news_id = derived_id(
        state.campaign_id, "news", "appointment", effect.person, effect.office, verb, on.isoformat()
    )
    out: list[ev.Payload] = []
    if world.claim(fact_id, state.facts):
        out += _moved(state, effect, on)
        predicate = "holds_office" if effect.appoint else "dismissed_from"
        out.append(
            ev.FactAsserted(
                fact=Fact(
                    fact_id=fact_id,
                    subject=effect.person,
                    predicate=predicate,
                    obj=effect.office,
                    scope=PUBLIC,
                )
            )
        )
    if world.claim(news_id, state.news):
        entity = state.entities.get(effect.person)
        name = _cut(entity.name) if entity is not None else "someone"
        past = "appointed" if effect.appoint else "dismissed"
        out.append(
            ev.NewsReported(
                news=NewsEvent(
                    news_id=news_id,
                    on=on,
                    topic=NewsTopic.APPOINTMENT,
                    subject=effect.person,
                    obj=polity_of(state, issuer),
                    facts=(
                        BodyField(label="Office", value=effect.office),
                        BodyField(label="Appointed" if effect.appoint else "Dismissed", value=name),
                    ),
                    headline=_cut(f"{name} {past}: {effect.office}"),
                )
            )
        )
    return out, []


def _post(state: State, office: str) -> AssetId | None:
    """The office asset an order names, by its id or its name; None when none or two."""
    if AssetId(office) in state.assets:
        return AssetId(office) if state.assets[AssetId(office)].kind is AssetKind.OFFICE else None
    wanted = office.strip().casefold()
    found = [
        a.asset_id
        for a in state.assets.values()
        if a.kind is AssetKind.OFFICE and a.name.strip().casefold() == wanted
    ]
    return found[0] if len(found) == 1 else None


def _moved(state: State, effect: Appointment, on: date) -> list[ev.Payload]:
    """The change of post an appointment or dismissal makes the day it lands. Nothing with
    ``posts`` off; for an office no card holds or kept; for an appointee with no card or
    dead; or for a dismissal of someone who does not hold it."""
    post = _post(state, effect.office) if ladder.on(state) else None
    if post is None or (posts.holder(state, post) is None and post not in state.posts):
        return []
    if effect.appoint:
        card, entity = state.cards.get(effect.person), state.entities.get(effect.person)
        if card is None or entity is None or entity.status is EntityStatus.DEAD:
            return []
        return [*posts.change(state, post, effect.person, on, PostCause.APPOINTED)]
    if posts.holder(state, post) != effect.person:
        return []
    return [*posts.change(state, post, None, on, PostCause.APPOINTED)]


def _cut(text: str) -> str:
    """Capped at the 60-char label limit, with a trailing ellipsis when cut."""
    return text if len(text) <= 60 else text[:59] + "…"
