"""Landing an Appointment effect in the world: a public office fact and public news."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FactId, SeatId, derived_id
from revisionist.core.ontology import Fact
from revisionist.core.realism.document import BodyField
from revisionist.core.realism.effect import Appointment
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.war import NewsEvent, NewsTopic, polity_of
from revisionist.core.visibility import PUBLIC


def land(
    world: PassWorld, effect: Appointment, issuer_seat: SeatId, issuer: EntityId, on: date
) -> tuple[list[ev.Payload], list[FactId]]:
    """The office as a public fact and the appointment as public news, each folded once."""
    state = world.state
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
    if fact_id not in state.facts:
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
    if news_id not in state.news:
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


def _cut(text: str) -> str:
    """Capped at the 60-char label limit, with a trailing ellipsis when cut."""
    return text if len(text) <= 60 else text[:59] + "…"
