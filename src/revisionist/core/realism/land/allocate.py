"""Landing an Allocate effect in the world: a quantity moves between polities, and the
recipient's receipt is always recorded as a private fact."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FactId, SeatId, derived_id
from revisionist.core.ontology import Fact
from revisionist.core.realism.effect import Allocate
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.quantity import Quantity
from revisionist.core.realism.war import polity_of
from revisionist.core.visibility import private_to


def land(
    world: PassWorld, effect: Allocate, issuer_seat: SeatId, issuer: EntityId, on: date
) -> tuple[list[ev.Payload], list[FactId]]:
    """Move what the issuer's polity holds of ``what`` to the recipient's polity, up to the
    amount, and record the receipt. A pair of distinct quantities is needed to move anything."""
    state = world.state
    payloads: list[ev.Payload] = []
    giver = _held(world, polity_of(state, issuer), effect.what)
    taker = _held(world, polity_of(state, effect.recipient), effect.what)
    if (
        giver is not None
        and taker is not None
        and giver.quantity_id != taker.quantity_id
        and giver.value is not None
    ):
        moved = max(0, min(effect.amount, giver.value))
        if moved:
            less = giver.model_copy(update={"value": giver.value - moved, "as_of": on})
            more = taker.model_copy(update={"value": (taker.value or 0) + moved, "as_of": on})
            world.quantities[less.quantity_id] = less
            world.quantities[more.quantity_id] = more
            payloads += [ev.QuantitySet(quantity=less), ev.QuantitySet(quantity=more)]
    fact = Fact(
        fact_id=FactId(
            derived_id(
                state.campaign_id,
                "fact",
                "allocate",
                effect.recipient,
                issuer,
                effect.what,
                effect.amount,
                on.isoformat(),
            )
        ),
        subject=effect.recipient,
        predicate="received_from",
        obj=issuer,
        scope=private_to(issuer_seat),
    )
    if world.claim(fact.fact_id, state.facts):
        payloads.append(ev.FactAsserted(fact=fact))
    return payloads, []


def _held(world: PassWorld, polity: EntityId | None, name: str) -> Quantity | None:
    """The first quantity the polity owns under this name."""
    if polity is None:
        return None
    return next(
        (q for q in world.quantities.values() if q.owner == polity and q.name == name), None
    )
