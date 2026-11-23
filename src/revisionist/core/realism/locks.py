"""Deciders and what locks an order (DCD).

A world may carry ``locks``: rows that each say which order, under which condition,
needs which decision, from whom. They reach state once, by ``locks_declared``, and are
read only with the ``locks`` rule on.

A row names its order by what the rules already know: a form (a lever's name) with some
of its parameter values, or an effect kind with a zone or a force. A form row matches a
form order; an effect row matches a written order's typed effect. Its condition is a
closed check over state, or none, when the order always needs the decision:

- ``law_not_in_force``: no passed law carrying the named clause is in force for the
  issuer's nation (``laws.in_force``: the world's declared laws with ``laws`` on).
- ``posture_not_set``: no superior of the issuer has set the named posture for the zone.
  The form path and the written path name a zone differently (a form's own parameter
  values, against a written order's ``SetEngagement.zone``), so the check carries both
  namings, and the posture counts as set when either path has set it.

Its decider is a person (the superior whose post the order belongs to), a body (a
nation's chamber or chambers that pass the law), or, with ``deciders`` on, a council: the
people who sit on it, how many must agree, and the head an ask goes to (QKD). With
``deciders`` on a row may also name its kind of question (``Question``). A row that names a
question or a council is decided by its kind; one that names neither behaves as before. On
a row decided by its kind, an ask put to a council, or to a decider a seat holds, is a
matter: each member a seat holds may choose, sealed, until the due day; then each member
with no choice kept is decided by his card, and the ask is granted when enough agree. The
grant of a matter opens the lock itself, as does any grant of such a row with no
condition.

A written order outside the issuer's domains that no row holds has a derived decider: the
nearest card up the issuer's chain of ``principals`` with a domain that covers the order's
effect.

``lock_for`` is a pure function of state. Nothing here names a place, a nation, a
person, a bill or a form: every one comes from the world file.

A held order (LCK) is an order a lock holds: stored, not carried out, with its row and
its decider, until it lands, fails its re-check, is withdrawn, or a later order from its
seat to the same force and zone replaces it. It has no clock expiry. Whether an order is
held, and the reason its seat is told, are read from what the seat can see
(``seen_lock``): a condition that turns on a fact outside the seat's view is judged as the
view shows it, so two games that differ only in such a fact hold the order alike.
"""

from collections.abc import Container, Iterable, Mapping, Sequence
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, FeatureId, OrderId, SeatId
from revisionist.core.realism import laws
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.answer import ParamValue
from revisionist.core.realism.card import Desk, Domain, superiors
from revisionist.core.realism.effect import (
    EffectKind,
    Engagement,
    Forecast,
    MoveForce,
    SetEngagement,
)
from revisionist.core.realism.pipeline import Order, OrderStatus

if TYPE_CHECKING:
    from revisionist.core.state import State, View


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


class Question(StrEnum):
    """The kind of question a lock row puts (QKD) [proposed]."""

    PERMISSION = "permission"
    WAR = "war"
    PEACE = "peace"
    MONEY = "money"
    POSTS = "posts"
    OFFICE = "office"


class Council(Model):
    """A council that decides (QKD): who sits on it, how many must agree, and the head an
    ask goes to."""

    members: tuple[EntityId, ...] = Field(min_length=1, max_length=24)
    needed: int = Field(ge=1)
    head: EntityId

    @model_validator(mode="after")
    def _shape(self) -> "Council":
        if len(set(self.members)) != len(self.members):
            raise ValueError("a council names a member twice")
        if self.needed > len(self.members):
            raise ValueError(f"a council needs {self.needed} of {len(self.members)}")
        return self


class Decider(Model):
    """Who can allow a held order: a person, a nation's chamber or chambers, with the
    head of that nation's government, to whom an ask goes (ASK), or a council (QKD)."""

    person: EntityId | None = None
    nation: EntityId | None = None
    chambers: tuple[Label, ...] = ()
    head: EntityId | None = None
    """With a body: the head of the nation's government, named by the row (the compiler
    requires it). An ask for an order the body decides goes to this person (ASK)."""
    council: Council | None = Field(default=None, exclude_if=lambda v: v is None)
    """With ``deciders`` on: a council, whose head an ask goes to (QKD). Left out of the
    dump while absent, so a stored row hashes as before."""

    @model_validator(mode="after")
    def _shape(self) -> "Decider":
        body = self.nation is not None or bool(self.chambers)
        if (self.person is not None) + body + (self.council is not None) != 1:
            raise ValueError("a decider is a person, a body or a council, one of them")
        if body and (self.nation is None or not self.chambers):
            raise ValueError("a body names its nation and its chambers")
        if self.head is not None and not body:
            raise ValueError("only a body names the head of its government")
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
    question: Question | None = Field(default=None, exclude_if=lambda v: v is None)
    """With ``deciders`` on, the kind of question the row puts (QKD); None: the row names
    none, reads as a question of permission and behaves as it did before deciders. Left out
    of the dump while None, so a stored row hashes as before."""


class Lock(Model):
    """What ``lock_for`` returns: the row that holds the order, or None for a written
    order outside the issuer's domains, and who can allow it."""

    row: LockRow | None = None
    decider: Decider


class HeldEnd(StrEnum):
    """How a held order ends."""

    REPLACED = "replaced"
    """A later order from its seat to the same force and zone took its place."""
    LANDED = "landed"
    """Its lock opened and it passed its re-check: it landed as an ordinary order."""
    FAILED = "failed"
    """Its lock opened and it failed its re-check."""
    WITHDRAWN = "withdrawn"
    """Its seat took it back."""


class HeldOrder(Model):
    """An order a lock holds: a form order as drafted, or a written order's asks, with
    the row that holds it (none for a derived decider), its decider, and the reason its
    seat was told. No clock ends it."""

    order_id: OrderId
    issuer: SeatId
    filed: date
    form: Order | None = None
    """A form order, as it would have entered its pipeline."""
    asks: tuple[Ask, ...] = Field(default=(), max_length=8)
    """A written order's asks, every one, as filed."""
    forecast: Forecast | None = None
    """A written order's forecast, as it would have been stored with it (FCS)."""
    row: Label | None = None
    decider: Decider
    reason: str = Field(min_length=1, max_length=300)
    """The words its seat was told, built from that seat's view only."""

    @model_validator(mode="after")
    def _shape(self) -> "HeldOrder":
        if (self.form is None) == (not self.asks):
            raise ValueError("a held order is a form order or a written order, not both")
        form = self.form
        if form is not None and (
            (form.order_id, form.issuer, form.filed) != (self.order_id, self.issuer, self.filed)
            or form.status is not OrderStatus.MOVING
            or form.step
            or form.outcomes
        ):
            raise ValueError("a held form order is the order as drafted, under the same id")
        if form is not None and self.forecast is not None:
            raise ValueError("only a written order carries a forecast")
        return self


def on(state: "State") -> bool:
    from revisionist.core.state import Rule

    return Rule.LOCKS in state.rules


def lock_for(
    state: "State", seat: SeatId, order: Order | Ask, opened: Container[str] = ()
) -> Lock | None:
    """The lock that holds ``order``, filed by ``seat``, or None. A form order is held by
    the first form row it matches whose condition holds; a written order by the first
    effect row, else, outside the issuer's domains, by the derived decider. A row never
    holds its own decider's order, nor a row keyed in ``opened`` (opened by a grant).
    Nothing with ``locks`` off. A pure function of state."""
    if not on(state) or seat not in state.seats:
        return None
    issuer = state.seats[seat].embodies
    for row in state.locks:
        if row.key in opened or row.decider.person == issuer:
            continue
        if not _matches(state, row.order, order):
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
        from revisionist.core.realism.war import polity_of

        nation = polity_of(state, issuer)
        return nation is None or nation not in laws.in_force(state, when.clause)
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


# --- The held order (LCK) ------------------------------------------------------------


def seen_lock(state: "State", seat: SeatId, order: Order | Ask) -> Lock | None:
    """The lock that holds the seat's order, or None. A lock whose condition turns on a
    fact the seat cannot see holds nothing: the order goes on as an ordinary order, so
    two games that differ only in that fact treat the seat's order alike."""
    if not on(state) or seat not in state.seats:
        return None
    found = lock_for(state, seat, order)
    if found is None or (found.row is not None and _hidden(state, seat, found.row.when)):
        return None
    return found


def _hidden(state: "State", seat: SeatId, when: Condition | None) -> bool:
    """Whether the condition reads a fact outside the seat's view. A law's passed flags
    are hidden unless their scope admits the seat. A posture is set by the seat's own
    superiors, whose orders come down its chain, so the seat knows it."""  # [proposed]
    if not isinstance(when, LawNotInForce):
        return False
    read = laws.flags(state, when.clause)
    return any(q.scope is None or not q.scope.visible_to(seat) for q in read)


def reason(view: "View", lock: Lock) -> str:
    """What the seat is told of its held order, from its own view: who can allow it, and
    nothing of the condition behind it."""
    decider = lock.decider
    if decider.person is not None:
        who = _name(view, decider.person)
    elif decider.council is not None:
        who = f"the council under {_name(view, decider.council.head)}"  # [proposed]
    else:
        assert decider.nation is not None
        chambers = " and ".join(c.replace("_", " ") for c in decider.chambers)
        who = f"{_name(view, decider.nation)}'s {chambers}"
    return f"Held until {who} allows it."  # [proposed]


def _name(view: "View", who: EntityId) -> str:
    found = view.entities.get(who)
    return found.name if found is not None else "whoever decides it"


Aim = tuple[FeatureId | None, EntityId | None]
"""A force and a zone an order is aimed at; either may be missing, not both."""


def aims(state: "State", seat: SeatId, order: Order | Sequence[Ask]) -> frozenset[Aim]:
    """The forces and zones an order is aimed at: a movement form's force and where it
    goes; a written move's force and where it goes; an engagement's force and zone."""
    found: set[Aim] = set()
    if isinstance(order, Order):
        found.add(_form_aim(state, seat, order))
    else:
        for ask in order:
            effect = ask.effect
            if isinstance(effect, MoveForce):
                found.add((effect.force, effect.to))
            elif isinstance(effect, SetEngagement):
                found.add((effect.force, zone_of(state, effect.zone)))
    return frozenset(a for a in found if a != (None, None))


def _form_aim(state: "State", seat: SeatId, order: Order) -> Aim:
    from revisionist.core.realism.pipelines import destination
    from revisionist.core.realism.resolvers.movement import FORCE
    from revisionist.core.world_compile import object_id

    held = state.seats.get(seat)
    card = state.cards.get(held.embodies) if held is not None else None
    lever = next((x for x in card.levers if x.name == order.lever), None) if card else None
    to = destination(lever) if lever is not None else None
    if to is None:
        return (None, None)

    def keyed(value: ParamValue | None, kind: str, known: Container[str]) -> str | None:
        """The id a form's value names: the id itself, or the object a world key names."""
        if not isinstance(value, str):
            return None
        ids = (value, object_id(state.campaign_id, kind, value))
        return next((v for v in ids if v in known), None)

    force = keyed(order.params.get(FORCE), "feature", state.features)
    place = keyed(order.params.get(to.name), "entity", state.entities)
    return (
        FeatureId(force) if force is not None else None,
        EntityId(place) if place is not None else None,
    )


def same_filing(held: HeldOrder, order: Order | Sequence[Ask]) -> bool:
    """Whether ``order`` is the filing ``held`` already holds, retried: the same form
    with the same terms, or the same asks."""
    if isinstance(order, Order):
        form = held.form
        return form is not None and (form.lever, form.params) == (order.lever, order.params)
    return held.form is None and held.asks == tuple(order)


def retried(state: "State", seat: SeatId, order: Order | Sequence[Ask]) -> HeldOrder | None:
    """The seat's held order that ``order`` repeats, if any."""
    return next(
        (
            h
            for h in sorted(state.held.values(), key=lambda h: h.order_id)
            if h.issuer == seat and same_filing(h, order)
        ),
        None,
    )


def replaced(state: "State", seat: SeatId, order: Order | Sequence[Ask]) -> list[HeldOrder]:
    """The seat's held orders a later ``order`` from it replaces: those aimed at a force
    and zone it is aimed at too, in id order."""
    mine = aims(state, seat, order)
    return [
        h
        for h in sorted(state.held.values(), key=lambda h: h.order_id)
        if h.issuer == seat and mine & aims(state, seat, h.form or h.asks)
    ]


# --- The ask, and the lock opening from state (ASK) -----------------------------------


class Asked(Model):
    """A held order asked for, once, by its own seat (ASK): who asked, the person the ask
    went to and the seat that holds that person, if any, and the order's plain words. It
    decides nothing and opens nothing. The person asked learns only this."""

    order_id: OrderId
    asker: SeatId
    by: EntityId
    """The asker's person."""
    to: EntityId
    """The decider, or for a body the head of the nation's government the row names."""
    seat: SeatId | None = None
    """The seat holding ``to`` when the ask was made; None: the ask reached the card."""
    words: str = Field(min_length=1, max_length=300)
    """The order in plain words."""
    on: date
    seats: tuple[SeatId, ...] = ()
    """With a council (QKD): the seats holding its members when the ask was made, each of
    which the matter is put before."""
    answered: date | None = None
    """The day the card of a person no human seat holds answered it (AAK); None: not
    answered, as an ask to a person a seat holds always is."""
    granted: bool | None = None
    """With ``answered``: whether the card granted it."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"answered", "granted", "seats"})

    @model_validator(mode="after")
    def _answer(self) -> "Asked":
        if (self.answered is None) != (self.granted is None):
            raise ValueError("an answered ask says whether it was granted, and only then")
        if self.answered is not None and self.answered < self.on:
            raise ValueError("an ask is answered on or after the day it was made")
        return self


def asked_of(decider: Decider) -> EntityId | None:
    """The person an ask goes to: the decider, the council's head, or the head of the
    body's government; None for a body whose row named no head."""
    if decider.council is not None:
        return decider.council.head
    return decider.person if decider.person is not None else decider.head


ASKED_ALREADY = "You have already asked for that order."  # [proposed]
NOT_HELD = "That order is not held."  # [proposed]
NOBODY_TO_ASK = "Nobody can be asked for that order."  # [proposed]


def ask(state: "State", seat: SeatId, order_id: OrderId, day: date) -> Asked:
    """The seat's ask for its held order ``order_id``, dated ``day``: one paper before the
    seat holding the person who decides it, or the card when no seat does, with the
    order's plain words. Raises ``ValueError`` with the seat's words when the order is not
    its own held order, or it has asked for it already. Opens nothing."""
    held = state.held.get(order_id) if on(state) else None
    if held is None or held.issuer != seat or seat not in state.seats:
        raise ValueError(NOT_HELD)
    if order_id in state.asked:
        raise ValueError(ASKED_ALREADY)
    to = asked_of(held.decider)
    if to is None:
        raise ValueError(NOBODY_TO_ASK)
    at = next((s for s, x in sorted(state.seats.items()) if x.embodies == to), None)
    council = held.decider.council if deciders_on(state) else None
    members = set(council.members) if council is not None else set()
    return Asked(
        order_id=order_id,
        asker=seat,
        by=state.seats[seat].embodies,
        to=to,
        seat=at,
        words=held_words(state, held),
        on=day,
        seats=tuple(s for s, x in sorted(state.seats.items()) if x.embodies in members),
    )


def held_words(state: "State", held: HeldOrder) -> str:
    """A held order in plain words: a form's label and terms, or a written order's asks."""
    from revisionist.core.realism.pipelines import order_words

    said = order_words(state, held.form) if held.form else " ".join(a.ask for a in held.asks)
    return " ".join(said.split())[:300] or "An order."


def open_now(state: "State", held: HeldOrder) -> bool:
    """Whether the held order's lock is open: with ``deciders`` on, a grant opened it
    (``opened_by_grant``); else its row's condition, read from state, no longer holds. A
    row with no condition, a derived decider, or a row the state no longer carries never
    opens from state. Nothing with ``locks`` off."""
    if not on(state) or held.row is None:
        return False
    if opened_by_grant(state, held):
        return True
    row = next((r for r in state.locks if r.key == held.row), None)
    if row is None or row.when is None:
        return False
    issuer = state.seats[held.issuer].embodies
    return not _holds(state, issuer, row.when)


# --- Deciders by kind of question, and the council (QKD) -------------------------------


def deciders_on(state: "State") -> bool:
    from revisionist.core.state import Rule

    return Rule.DECIDERS in state.rules and on(state)


def nation_of(state: "State", decider: Decider) -> EntityId | None:
    """The nation a decider belongs to: the body's, or that of the person or the
    council's head."""
    from revisionist.core.realism.war import polity_of

    if decider.nation is not None:
        return decider.nation
    who = asked_of(decider)
    return polity_of(state, who) if who is not None else None


def rows_on(state: "State", nation: EntityId, question: Question) -> list[LockRow]:
    """The rows that put ``question`` to a decider of ``nation``, in the world's order.
    None with ``deciders`` off: a missing decider gives nobody an authority."""
    if not deciders_on(state):
        return []
    return [
        r
        for r in state.locks
        if (r.question or Question.PERMISSION) is question and nation_of(state, r.decider) == nation
    ]


def by_kind(state: "State", row: LockRow) -> bool:
    """With ``deciders`` on, whether the row is decided by its kind of question: it names
    a question or a council. A row that names neither behaves as it did before."""
    return deciders_on(state) and (row.question is not None or row.decider.council is not None)


def _row(state: "State", held: HeldOrder) -> LockRow | None:
    return next((r for r in state.locks if r.key == held.row), None)


def opened_by_grant(state: "State", held: HeldOrder) -> bool:
    """With ``deciders`` on and the held order's row decided by its kind, whether a grant
    of its ask opened its lock: any grant of a matter (a council, or a decider a seat
    holds), or of a row with no condition."""
    row = _row(state, held)
    asked = state.asked.get(held.order_id)
    if row is None or asked is None or not asked.granted or not by_kind(state, row):
        return False
    return row.when is None or is_matter(state, held, asked)


def is_matter(state: "State", held: HeldOrder, asked: Asked) -> bool:
    """With ``deciders`` on and a row decided by its kind, whether the ask is a matter: put
    to a council, or to a person a seat with a desk holds when it was made."""
    row = _row(state, held)
    if row is None or not by_kind(state, row):
        return False
    single = asked.seat is not None and _played(state, asked.seat)
    return held.decider.council is not None or single


def _played(state: "State", seat: SeatId) -> bool:
    from revisionist.core.realism import actors

    return seat in actors.readers(state)


NOT_A_MEMBER = "That matter is not before you."  # [proposed]


def choosers(state: "State", asked: Asked) -> frozenset[SeatId]:
    """The seats that may choose on a matter: each seat that still holds a council member
    it held when asked, or the seat holding the single decider."""
    held = state.held.get(asked.order_id)
    if held is None:
        return frozenset()
    council = held.decider.council
    if council is not None:
        return frozenset(
            s
            for s in asked.seats
            if s in state.seats and state.seats[s].embodies in council.members
        )
    seat = asked.seat
    return (
        frozenset({seat})
        if seat is not None and state.seats[seat].embodies == asked.to
        else frozenset()
    )


def may_choose(state: "State", seat: SeatId, order_id: OrderId) -> None:
    """Raises ``ValueError`` with the seat's words unless the matter on ``order_id`` is
    open and before ``seat``."""
    asked = state.asked.get(order_id)
    held = state.held.get(order_id)
    if (
        asked is None
        or held is None
        or asked.answered is not None
        or not is_matter(state, held, asked)
        or seat not in choosers(state, asked)
    ):
        raise ValueError(NOT_A_MEMBER)


def matters_due(state: "State", day: date) -> list[Asked]:
    """The matters due by ``day`` and not yet answered, oldest first: each falls due
    ``ANSWER_DAYS`` world days after its ask was made."""
    from revisionist.core.realism.process import ANSWER_DAYS

    if not deciders_on(state):
        return []
    return sorted(
        (
            a
            for a in state.asked.values()
            if a.answered is None
            and a.order_id in state.held
            and a.on + timedelta(days=ANSWER_DAYS) <= day
            and is_matter(state, state.held[a.order_id], a)
        ),
        key=lambda a: (a.on, a.order_id),
    )


def matter_granted(state: "State", asked: Asked) -> bool:
    """The matter's answer on its due day: for a council, whether the members agreeing
    reach the number needed; for a single decider, his own choice. A member's kept choice
    counts as made; every other member is decided by his card (``answering.grants``)."""
    from revisionist.core.realism import answering

    held = state.held[asked.order_id]
    kept = state.chosen.get(asked.order_id, {})
    by_person = {state.seats[s].embodies: kept[s] for s in choosers(state, asked) if s in kept}

    def agrees(person: EntityId) -> bool:
        if person in by_person:
            return by_person[person]
        return answering.grants(state, asked.model_copy(update=dict(to=person)))

    council = held.decider.council
    if council is None:
        return agrees(asked.to)
    return sum(agrees(m) for m in council.members) >= council.needed


__all__ = [
    "ASKED_ALREADY",
    "NOBODY_TO_ASK",
    "NOT_A_MEMBER",
    "NOT_HELD",
    "Aim",
    "Asked",
    "Condition",
    "Council",
    "Decider",
    "HeldEnd",
    "HeldOrder",
    "LawNotInForce",
    "Lock",
    "LockRow",
    "OrderMatch",
    "PostureNotSet",
    "Question",
    "aims",
    "ask",
    "asked_of",
    "by_kind",
    "choosers",
    "covering",
    "decider_for",
    "deciders_on",
    "held_words",
    "is_matter",
    "lock_for",
    "matter_granted",
    "matters_due",
    "may_choose",
    "nation_of",
    "on",
    "open_now",
    "opened_by_grant",
    "posture_set",
    "reason",
    "replaced",
    "retried",
    "rows_on",
    "same_filing",
    "seen_lock",
    "zone_of",
]
