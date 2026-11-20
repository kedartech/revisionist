"""The intelligence orders from a form (INT): a lever whose rule name is ``intel``.

A form names which of the five orders it is in its ``intel`` parameter, and the piece
and the area by world-file key. When the order leaves its last step it becomes the
effect a written order carries for the same thing, and that effect lands on that day
through ``apply.land_effect``, the path a written order's effect lands by. So a form and
its written twin call the same rule functions in ``detect`` with the same arguments:

- a reconnaissance flight is an investigate with ``intel`` ``recon`` over the area,
  naming the air piece;
- a patrol is the patrol posture on the piece, as a force order sets it;
- placing an agent is an investigate with ``intel`` ``agent`` in the area;
- funding codebreaking is an allocate with ``intel`` ``codebreaking`` to the issuer's
  own nation;
- concealment is an engagement that keeps the piece's rule and sets ``concealed``
  (``yes``) or lifts it (``no``).

Nothing here names a chance, a cost or a limit: those are ``detect``'s. An order acts
once, on the day it is enacted; an agent's days on the way and the rise a funding buys
are carried in what lands, so the day walk has nothing more to do for one.
"""

from collections.abc import Sequence
from datetime import date
from enum import StrEnum

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.card import Lever
from revisionist.core.realism.effect import (
    Allocate,
    Engagement,
    EstimatedEffect,
    IntelOrder,
    Investigate,
    MoveForce,
    Posture,
    SetEngagement,
)
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State
from revisionist.core.world_compile import object_id

INTEL, PIECE, AREA, CONCEALED = "intel", "piece", "area", "concealed"
YES = "yes"


class Form(StrEnum):
    """Which of the five intelligence orders a form is."""

    RECON = "recon"
    PATROL = "patrol"
    AGENT = "agent"
    CODEBREAKING = "codebreaking"
    CONCEAL = "conceal"


def form_of(lever: Lever) -> Form | None:
    """The order an ``intel`` lever's form gives: the one choice of its ``intel``
    parameter. None for any other lever, or a form whose ``intel`` offers more than one."""
    if lever.resolver != "intel":
        return None
    spec = next((p for p in lever.params if p.name == INTEL), None)
    if spec is None or len(spec.choices) != 1:
        return None
    try:
        return Form(spec.choices[0])
    except ValueError:
        return None


def _feature(state: State, order: Order) -> FeatureId:
    return FeatureId(object_id(state.campaign_id, "feature", str(order.params.get(PIECE))))


def _area(state: State, order: Order) -> EntityId:
    return EntityId(object_id(state.campaign_id, "entity", str(order.params.get(AREA))))


def effect_of(state: State, order: Order) -> EstimatedEffect | None:
    """The effect a written order carries for what the form asks; None when the form
    names no order this module knows."""
    try:
        form = Form(str(order.params.get(INTEL)))
    except ValueError:
        return None
    issuer = state.seats[order.issuer].embodies
    match form:
        case Form.RECON:
            area, flier = _area(state, order), _feature(state, order)
            return Investigate(target=area, question="recon", intel=IntelOrder.RECON, flier=flier)
        case Form.PATROL:
            return MoveForce(force=_feature(state, order), posture=Posture.PATROL)
        case Form.AGENT:
            return Investigate(target=_area(state, order), question="agent", intel=IntelOrder.AGENT)
        case Form.CODEBREAKING:
            nation = polity_of(state, issuer) or issuer
            return Allocate(
                recipient=nation,
                what="codebreaking",
                amount=0,
                unit="points",
                intel=IntelOrder.CODEBREAKING,
            )
        case Form.CONCEAL:
            piece = _feature(state, order)
            found = state.features.get(piece)
            rule = found.engagement if found is not None else None
            return SetEngagement(
                force=piece,
                zone="",
                rule=rule or Engagement.DEFEND,
                concealed=str(order.params.get(CONCEALED)) == YES,
            )


def _changes(payloads: Sequence[ev.Payload]) -> tuple["rs.Change", ...]:
    """What an intelligence order's landing returns, as changes: every kind it can land."""
    out: list[rs.Change] = []
    for p in payloads:
        if isinstance(p, ev.FeatureSet):
            out.append(p.feature)
        elif isinstance(
            p,
            ev.AgentSet | ev.CodebreakingSet | ev.EconomySet | ev.DocumentIssued | ev.BattleDecided,
        ):
            out.append(p)
        else:
            raise TypeError(f"an intelligence order cannot land {p.kind}")
    return tuple(out)


def resolve(state: State, order: Order) -> tuple["rs.Change", ...]:
    """What the enacted form lands, on the day it left its last step."""
    from revisionist.core.realism import apply

    if order.status is not OrderStatus.ENACTED:
        return ()
    effect = effect_of(state, order)
    if effect is None:
        return ()
    aide = order.order_id in state.aide_orders
    on = rs.settled_on(order)
    return _changes(apply.land_effect(state, effect, order.issuer, on, order.order_id, aide=aide))


def on_day(state: State, today: date) -> tuple["rs.Change", ...]:
    """Nothing: an intelligence order acts once, on the day it is enacted."""
    del state, today
    return ()


__all__ = ["Form", "effect_of", "form_of", "on_day", "resolve"]
