"""Landing a Deal effect: an offer is recorded to its issuer, an accepted deal records its
terms and moves the relationship between the two parties (engine v2, realism land)."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import RelationshipId, derived_id
from revisionist.core.ontology import Relationship
from revisionist.core.realism import effect as rx
from revisionist.core.realism.land import deal
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.visibility import PUBLIC, private_to
from tests.test_engine_v2_contract import CAMPAIGN, Slice

ON = date(1941, 9, 11)


def fold(sl: Slice, payloads: list[ev.Payload]) -> None:
    for p in payloads:
        sl.add(p, PUBLIC if isinstance(p, ev.RelationshipSet) else private_to(sl.fdr))


def land(sl: Slice, effect: rx.Deal, on: date = ON) -> list[ev.Payload]:
    out, revealed = deal.land(PassWorld(sl.state), effect, sl.fdr, sl.entity("roosevelt"), on)
    assert revealed == []
    fold(sl, out)
    return out


def seed_relationship(sl: Slice, disposition: int) -> None:
    sl.add(
        ev.RelationshipSet(
            relationship=Relationship(
                relationship_id=RelationshipId(
                    derived_id(CAMPAIGN, "rel", sl.entity("roosevelt"), sl.entity("churchill"))
                ),
                a=sl.entity("roosevelt"),
                b=sl.entity("churchill"),
                disposition=disposition,
                scope=private_to(sl.fdr),
            )
        ),
        PUBLIC,
    )


def accepted(sl: Slice, offer: tuple[str, ...] = (), ask: tuple[str, ...] = ()) -> rx.Deal:
    return rx.Deal(counterparty=sl.entity("churchill"), offer=offer, ask=ask, accept=True)


def test_offer_lands_one_private_fact() -> None:
    sl = Slice()
    effect = rx.Deal(counterparty=sl.entity("churchill"), offer=("destroyers",))
    out = land(sl, effect)
    assert len(out) == 1 and isinstance(out[0], ev.FactAsserted)
    (fact,) = sl.state.facts.values()
    assert fact.predicate == "offered_deal"
    assert fact.subject == sl.entity("roosevelt") and fact.obj == sl.entity("churchill")
    assert fact.scope == private_to(sl.fdr)
    assert sl.state.relationships == {}


def test_accepted_deal_lands_a_fact_per_term_and_a_relationship() -> None:
    sl = Slice()
    out = land(sl, accepted(sl, offer=("destroyers", "convoy"), ask=("bases",)))
    facts = {(f.subject, f.predicate, f.obj) for f in sl.state.facts.values()}
    roosevelt, churchill = sl.entity("roosevelt"), sl.entity("churchill")
    assert facts == {
        (roosevelt, "agreed_to_give", "destroyers"),
        (roosevelt, "agreed_to_give", "convoy"),
        (churchill, "agreed_to_give", "bases"),
    }
    assert all(f.scope == private_to(sl.fdr) for f in sl.state.facts.values())
    (rel_event,) = [p for p in out if isinstance(p, ev.RelationshipSet)]
    assert rel_event.relationship.disposition == 1


def test_accepted_deal_without_terms_lands_deal_accepted() -> None:
    sl = Slice()
    land(sl, accepted(sl))
    (fact,) = sl.state.facts.values()
    assert fact.predicate == "deal_accepted"
    assert fact.subject == sl.entity("roosevelt") and fact.obj == sl.entity("churchill")


def test_existing_relationship_is_raised_and_clamped_at_five() -> None:
    sl = Slice()
    seed_relationship(sl, 4)
    land(sl, accepted(sl, offer=("destroyers",)))
    rel = sl.state.relationships[
        RelationshipId(derived_id(CAMPAIGN, "rel", sl.entity("roosevelt"), sl.entity("churchill")))
    ]
    assert rel.disposition == 5

    land(sl, accepted(sl, offer=("bases",)))
    rel = next(iter(sl.state.relationships.values()))
    assert rel.disposition == 5


def test_two_deals_the_same_day_see_each_other() -> None:
    sl = Slice()
    world = PassWorld(sl.state)
    effect = accepted(sl, offer=("destroyers",))
    first, _ = deal.land(world, effect, sl.fdr, sl.entity("roosevelt"), ON)
    second, _ = deal.land(
        world, effect.model_copy(update={"offer": ("bases",)}), sl.fdr, sl.entity("roosevelt"), ON
    )
    fold(sl, first + second)
    (rel,) = sl.state.relationships.values()
    assert rel.disposition == 2


def test_landing_the_same_deal_twice_changes_nothing() -> None:
    sl = Slice()
    effect = accepted(sl, offer=("destroyers",), ask=("bases",))
    land(sl, effect)
    before = (dict(sl.state.facts), dict(sl.state.relationships))
    again = land(sl, effect)
    assert again == []
    assert (dict(sl.state.facts), dict(sl.state.relationships)) == before
