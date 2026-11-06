"""The war resolver: what a declaration of war sets going.

An enacted declaration makes the war, a public fact, a hostile relationship and a news
event. A declaration on the United States also nudges American opinion toward
intervention, where the world has a figure to nudge.
"""

from datetime import date

from revisionist.core.ids import EntityId, FactId, RelationshipId, derived_id
from revisionist.core.ontology import EntityKind, Fact, Relationship
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.document import BodyField
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import votes
from revisionist.core.realism.war import NewsEvent, NewsTopic, War, at_war, polity_of, war_id_for
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.core.world_compile import object_id

WAR_DISPOSITION = -5  # [proposed]
OPINION_STEP = 5  # [proposed]
OPINION_KEYS = ("gallup_declare_war_germany", "gallup_help_britain")
HEADLINE_MAX = 60


def _headline(a_name: str, b_name: str) -> str:
    """The declaration in plain words, cut to the label limit."""
    text = f"{a_name} declares war on {b_name}"
    return text if len(text) <= HEADLINE_MAX else text[: HEADLINE_MAX - 1] + "…"


def _relationship(state: State, a: EntityId, b: EntityId) -> Relationship:
    """The a-b relationship set to open hostility, made if the world had none."""
    for rel in state.relationships.values():
        if {rel.a, rel.b} == {a, b}:
            return rel.model_copy(update={"disposition": WAR_DISPOSITION})
    return Relationship(
        relationship_id=RelationshipId(derived_id(state.campaign_id, "rel", a, b)),
        a=a,
        b=b,
        disposition=WAR_DISPOSITION,
        scope=PUBLIC,
    )


def _news(state: State, a: EntityId, b: EntityId, day: date) -> NewsEvent:
    """The public record of the declaration."""
    a_name, b_name = state.entities[a].name, state.entities[b].name
    return NewsEvent(
        news_id=derived_id(
            state.campaign_id, "news", "war_declared", war_id_for(a, b), day.isoformat()
        ),
        on=day,
        topic=NewsTopic.WAR_DECLARED,
        subject=a,
        obj=b,
        headline=_headline(a_name, b_name),
        facts=(
            BodyField(label="Declared by", value=a_name),
            BodyField(label="Against", value=b_name),
            BodyField(label="Date", value=day.isoformat()),
        ),
    )


def resolve(state: State, order: Order) -> tuple["rs.Change", ...]:
    """Changes from one enacted declaration of war."""
    if order.status is not OrderStatus.ENACTED or order.lever != "declare_war":
        return ()
    b = EntityId(object_id(state.campaign_id, "entity", str(order.params.get("target"))))
    target = state.entities.get(b)
    seat = state.seats.get(order.issuer)
    if target is None or target.kind is not EntityKind.POLITY or seat is None:
        return ()
    a = polity_of(state, seat.embodies)
    if a is None or a == b or at_war(state, a, b):
        return ()
    day = rs.settled_on(order)
    war_id = war_id_for(a, b)
    fact = Fact(
        fact_id=FactId(
            derived_id(state.campaign_id, "fact", "at_war_with", war_id, day.isoformat())
        ),
        subject=a,
        predicate="at_war_with",
        obj=b,
        scope=PUBLIC,
    )
    out: list[rs.Change] = [
        War(war_id=war_id, a=a, b=b, since=day, declared_by=seat.embodies),
        fact,
        _relationship(state, a, b),
        _news(state, a, b, day),
    ]
    if b == EntityId(object_id(state.campaign_id, "entity", "usa")):
        for key in OPINION_KEYS:
            now = rs.value(state, key)
            change = (
                None if now is None else votes.put(state, key, min(100, now + OPINION_STEP), day)
            )
            if change is not None:
                out.append(change)
    return tuple(out)


def on_day(state: State, today: date) -> tuple["rs.Change", ...]:
    """A war moves with orders only: nothing changes with time alone."""
    return ()
