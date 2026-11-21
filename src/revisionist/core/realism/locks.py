"""Deciders and what locks an order (DCD).

A world may carry ``locks``: rows that each say which order, under which condition,
needs which decision, from whom. They reach state once, by ``locks_declared``, and are
read only with the ``locks`` rule on.

A row names its order by what the rules already know: a form (a lever's name) with some
of its parameter values, or an effect kind with a zone or a force. A form row matches a
form order; an effect row matches a written order's typed effect. Its condition is a
closed check over state, or none, when the order always needs the decision:

- ``law_not_in_force``: no passed law carrying the named clause is in force for the
  issuer's nation (``votes.in_force``, read only).
- ``posture_not_set``: no superior of the issuer has set the named posture for the zone.
  The form path and the written path name a zone differently (a form's own parameter
  values, against a written order's ``SetEngagement.zone``), so the check carries both
  namings, and the posture counts as set when either path has set it.

Its decider is a person (the superior whose post the order belongs to) or a body (a
nation's chamber or chambers that pass the law). A written order outside the issuer's
domains that no row holds has a derived decider: the nearest card up the issuer's chain
of ``principals`` with a domain that covers the order's effect.

``lock_for`` is a pure function of state. Nothing here names a place, a nation, a
person, a bill or a form: every one comes from the world file.
"""

from collections.abc import Iterable, Mapping
from datetime import date
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, FeatureId, OrderId, SeatId
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.answer import ParamValue
from revisionist.core.realism.card import Desk, Domain, superiors
from revisionist.core.realism.effect import (
    EffectKind,
    Engagement,
    MoveForce,
    SetEngagement,
)
from revisionist.core.realism.pipeline import Order, OrderStatus

if TYPE_CHECKING:
    from revisionist.core.state import State


class OrderMatch(Model):
    """Which order a row holds: a form with some of its parameter values, or an effect
    kind with a zone or a force."""

    form: Label | None = None
    """A lever's name. A form order matches when its lever has this name."""
    params: dict[Label, ParamValue] = Field(default_factory=dict)
    """With ``form``: the values the order's parameters must carry, as the form takes
    them. Parameters not named here may take any value."""
    effect: EffectKind | None = None
    """A written order matches when its typed effect is of this kind, and names ``zone``
    or ``force``."""
    zone: EntityId | None = None
    """With ``effect``: an area. An engagement whose zone names it, or a move to it."""
    force: FeatureId | None = None
    """With ``effect``: the force a move or an engagement names."""

    @model_validator(mode="after")
    def _shape(self) -> "OrderMatch":
        if (self.form is None) == (self.effect is None):
            raise ValueError("a lock names a form or an effect kind, not both")
        if self.form is not None and (self.zone is not None or self.force is not None):
            raise ValueError("a lock on a form names its parameter values, not a zone or force")
        if self.effect is not None:
            if self.params:
                raise ValueError("only a lock on a form names parameter values")
            if (self.zone is None) == (self.force is None):
                raise ValueError("a lock on an effect kind names a zone or a force")
        return self


class LawNotInForce(Model):
    """Holds while no passed law carrying ``clause`` is in force for the issuer's nation."""

    check: Literal["law_not_in_force"] = "law_not_in_force"
    clause: str = Field(min_length=1, max_length=200)
    """A clause's subject, as the law's clauses state it."""


class PostureNotSet(Model):
    """Holds while no superior of the issuer has set the named posture for the zone.

    Two namings, at least one given. The written path: the latest engagement a superior
    landed whose zone names ``zone`` carries ``rule``. The form path: the latest enacted
    order of ``form`` a superior issued whose parameters carry ``where`` (the zone, as the
    form names it) also carries ``posture``."""

    check: Literal["posture_not_set"] = "posture_not_set"
    zone: EntityId | None = None
    rule: Engagement | None = None
    form: Label | None = None
    where: dict[Label, ParamValue] = Field(default_factory=dict)
    posture: dict[Label, ParamValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _shape(self) -> "PostureNotSet":
        if (self.zone is None) != (self.rule is None):
            raise ValueError("a posture's written naming gives its zone and rule together")
        if self.form is None and (self.where or self.posture):
            raise ValueError("a posture's form naming names its form")
        if self.form is not None and (not self.where or not self.posture):
            raise ValueError("a posture's form naming gives the zone's and the posture's values")
        if self.zone is None and self.form is None:
            raise ValueError("a posture names its zone on the written path, the form path or both")
        return self


Condition = Annotated[LawNotInForce | PostureNotSet, Field(discriminator="check")]


class Decider(Model):
    """Who can allow a held order: a person, or a nation's chamber or chambers."""

    person: EntityId | None = None
    nation: EntityId | None = None
    chambers: tuple[Label, ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> "Decider":
        body = self.nation is not None or bool(self.chambers)
        if (self.person is None) == (not body):
            raise ValueError("a decider is a person or a body, not both")
        if body and (self.nation is None or not self.chambers):
            raise ValueError("a body names its nation and its chambers")
        if len(set(self.chambers)) != len(self.chambers):
            raise ValueError("a body names a chamber twice")
        return self


class LockRow(Model):
    """One row of the world's ``locks``: which order, under which condition, needs
    which decision, from whom."""

    key: Label
    order: OrderMatch
    when: Condition | None = None
    """None: the order always needs the decision."""
    decider: Decider


class Lock(Model):
    """What ``lock_for`` returns: the row that holds the order, or None for a written
    order outside the issuer's domains, and who can allow it."""

    row: LockRow | None = None
    decider: Decider


def on(state: "State") -> bool:
    from revisionist.core.state import Rule

    return Rule.LOCKS in state.rules


def lock_for(state: "State", seat: SeatId, order: Order | Ask) -> Lock | None:
    """The lock that holds ``order``, filed by ``seat``, or None. A form order is held by
    the first form row it matches whose condition holds; a written order by the first
    effect row, else, outside the issuer's domains, by the derived decider. A row never
    holds its own decider's order. Nothing with ``locks`` off. A pure function of state."""
    if not on(state) or seat not in state.seats:
        return None
    issuer = state.seats[seat].embodies
    for row in state.locks:
        if row.decider.person == issuer or not _matches(state, row.order, order):
            continue
        if row.when is None or _holds(state, issuer, row.when):
            return Lock(row=row, decider=row.decider)
    if isinstance(order, Ask):
        derived = decider_for(state, issuer, order)
        if derived is not None:
            return Lock(decider=Decider(person=derived))
    return None


def decider_for(state: "State", issuer: EntityId, ask: Ask) -> EntityId | None:
    """For a written order outside the issuer's domains: the nearest card up the
    issuer's chain of ``principals`` with a domain covering its effect. None when the
    order has no typed effect, lies inside the issuer's own domains, or no card above
    covers it."""
    card = state.cards.get(issuer)
    if card is None or ask.effect is None or covering(card, ask) is not None:
        return None
    for up in superiors(state.cards, issuer):
        above = state.cards.get(up)
        if above is not None and covering(above, ask) is not None:
            return up
    return None


def covering(card: Desk, ask: Ask) -> Domain | None:
    """The card's first domain that covers the ask's effect: its kind, and the force it
    names where it names one."""
    effect = ask.effect
    if effect is None:
        return None
    force = effect.force if isinstance(effect, MoveForce | SetEngagement) else None
    for domain in card.authority:
        if EffectKind(effect.kind) in domain.effects and (force is None or force in domain.forces):
            return domain
    return None


def _matches(state: "State", match: OrderMatch, order: Order | Ask) -> bool:
    if isinstance(order, Order):
        return match.form == order.lever and _carries(order.params, match.params)
    effect = order.effect
    if match.effect is None or effect is None or EffectKind(effect.kind) is not match.effect:
        return False
    if match.force is not None:
        return isinstance(effect, MoveForce | SetEngagement) and effect.force == match.force
    if isinstance(effect, SetEngagement):
        return zone_of(state, effect.zone) == match.zone
    return isinstance(effect, MoveForce) and effect.to == match.zone


def _carries(params: Mapping[str, ParamValue], wanted: Mapping[str, ParamValue]) -> bool:
    return all(k in params and params[k] == v for k, v in wanted.items())


def zone_of(state: "State", zone: str) -> EntityId | None:
    """The entity an engagement's zone names: its id, or its name in any case."""
    if EntityId(zone) in state.entities:
        return EntityId(zone)
    wanted = zone.strip().casefold()
    return next((e.entity_id for e in state.entities.values() if e.name.casefold() == wanted), None)


def _holds(state: "State", issuer: EntityId, when: LawNotInForce | PostureNotSet) -> bool:
    if isinstance(when, LawNotInForce):
        from revisionist.core.realism.resolvers.votes import in_force
        from revisionist.core.realism.war import polity_of

        nation = polity_of(state, issuer)
        return nation is None or nation not in in_force(state, when.clause)
    return not posture_set(state, issuer, when)


def posture_set(state: "State", issuer: EntityId, when: PostureNotSet) -> bool:
    """Whether a superior of ``issuer`` has set the posture, on either path."""
    above = set(superiors(state.cards, issuer))
    by = {s for s, seat in state.seats.items() if seat.embodies in above}
    return _written_set(state, by, when) or _form_set(state, by, when)


def _written_set(state: "State", by: set[SeatId], when: PostureNotSet) -> bool:
    if when.zone is None:
        return False
    landed: list[tuple[date, OrderId, int, Engagement]] = []
    for order in state.routed.values():
        if order.issuer not in by:
            continue
        for n, part in enumerate(order.parts):
            effect = part.effect
            if (
                part.applied is not None
                and isinstance(effect, SetEngagement)
                and zone_of(state, effect.zone) == when.zone
            ):
                landed.append((part.applied, order.order_id, n, effect.rule))
    return bool(landed) and max(landed)[3] is when.rule


def _form_set(state: "State", by: set[SeatId], when: PostureNotSet) -> bool:
    if when.form is None:
        return False
    enacted = [
        (_settled(o), o.order_id, o)
        for o in _orders(state, by)
        if o.lever == when.form and _carries(o.params, when.where)
    ]
    return bool(enacted) and _carries(max(enacted)[2].params, when.posture)


def _orders(state: "State", by: set[SeatId]) -> Iterable[Order]:
    return (o for o in state.orders.values() if o.issuer in by and o.status is OrderStatus.ENACTED)


def _settled(order: Order) -> date:
    return order.outcomes[-1].on if order.outcomes else order.filed


__all__ = [
    "Condition",
    "Decider",
    "LawNotInForce",
    "Lock",
    "LockRow",
    "OrderMatch",
    "PostureNotSet",
    "covering",
    "decider_for",
    "lock_for",
    "on",
    "posture_set",
    "zone_of",
]
