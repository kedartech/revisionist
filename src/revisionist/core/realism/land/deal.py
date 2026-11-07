"""Landing a Deal effect in the world: an offer is recorded to its issuer; an accepted deal
records its terms and moves the relationship between the two parties."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FactId, RelationshipId, SeatId, derived_id
from revisionist.core.ontology import Fact, Relationship
from revisionist.core.realism.effect import Deal
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.visibility import Scope, private_to


def land(
    world: PassWorld, effect: Deal, issuer_seat: SeatId, issuer: EntityId, on: date
) -> tuple[list[ev.Payload], list[FactId]]:
    """Private facts for the deal's terms, plus a disposition shift when accepted."""
    unique = {f.fact_id: f for f in _facts(world, effect, issuer_seat, issuer, on)}
    fresh = [f for f in unique.values() if world.claim(f.fact_id, world.state.facts)]
    if len(fresh) < len(unique):
        # some term is already on record: this deal, or part of it, has landed before
        return [ev.FactAsserted(fact=f) for f in fresh], []
    out: list[ev.Payload] = [ev.FactAsserted(fact=f) for f in fresh]
    if effect.accept:
        out.append(_shift(world, issuer_seat, issuer, effect.counterparty))
    return out, []


def _facts(
    world: PassWorld, effect: Deal, issuer_seat: SeatId, issuer: EntityId, on: date
) -> list[Fact]:
    scope = private_to(issuer_seat)
    if not effect.accept:
        return [_fact(world, issuer, "offered_deal", effect.counterparty, scope, on)]
    if not effect.offer and not effect.ask:
        return [_fact(world, issuer, "deal_accepted", effect.counterparty, scope, on)]
    given = [_fact(world, issuer, "agreed_to_give", t, scope, on) for t in effect.offer]
    asked = [_fact(world, effect.counterparty, "agreed_to_give", t, scope, on) for t in effect.ask]
    return given + asked


def _fact(
    world: PassWorld, subject: EntityId, predicate: str, obj: str, scope: Scope, on: date
) -> Fact:
    fact_id = FactId(
        derived_id(world.state.campaign_id, "fact", "deal", subject, predicate, obj, on.isoformat())
    )
    return Fact(fact_id=fact_id, subject=subject, predicate=predicate, obj=obj, scope=scope)


def _shift(
    world: PassWorld, issuer_seat: SeatId, issuer: EntityId, counterparty: EntityId
) -> ev.Payload:
    now = world.relationship(issuer, counterparty)
    if now is None:
        rel = Relationship(
            relationship_id=RelationshipId(
                derived_id(world.state.campaign_id, "rel", issuer, counterparty)
            ),
            a=issuer,
            b=counterparty,
            disposition=1,
            scope=private_to(issuer_seat),
        )
    else:
        rel = now.model_copy(update={"disposition": max(-5, min(5, now.disposition + 1))})
    world.relationships[rel.relationship_id] = rel
    return ev.RelationshipSet(relationship=rel)
