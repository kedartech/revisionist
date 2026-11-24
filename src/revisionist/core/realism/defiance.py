"""Acting without permission, and refusing an order from above (DFY).

With ``defiance`` on, a post may name the acts its holder may attempt without leave, from
a closed list. Each act is told from a written order's typed effect alone:

- ``border``: a force moved into a territory whose holder is a polity other than the
  force's own, and not at war with it.
- ``fire_first``: a force told to shoot on sight, or moved with an attack posture, where a
  polity other than its own and not at war with it holds the zone or keeps a force there.

A blockade is not on the list: no effect kind cuts a trade line by force, so it cannot be
told from a typed effect. A form order carries no typed effect and has no act.

A held order (LCK) whose acts are all on its issuer's post's list may be sent anyway,
once, by its own seat: it lands as an ordinary order, marked defiant. The executor of a
defiant order refuses it at a loyalty of ``DEFIANT_LOYALTY`` or less, by the same draw that
decides a refusal today. Nothing here calls a model, and the aide never sends an order
anyway.

Carried out, or a step on an order from above refused (CMD), it is an incident: a question
on the commander before the person who could have allowed it, answered within
``INCIDENT_DAYS`` world days as backed, disowned or dismissed, by that person's seat or,
unanswered or unplayed, by his card. One incident per order.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, FeatureId, OrderId, SeatId, derived_id
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.effect import Engagement, MoveForce, Posture, SetEngagement
from revisionist.core.realism.kinds import Domain

if TYPE_CHECKING:
    from revisionist.core import events as ev
    from revisionist.core.realism.locks import HeldOrder
    from revisionist.core.state import State, View

DEFIANT_LOYALTY = 0  # [proposed] an executor at or below this loyalty may refuse a defiant order

NOT_ON = "Nothing may be sent without leave in this game."  # [proposed]
NOT_WITHOUT_LEAVE = "Your post gives no leave to send that order without permission."  # [proposed]
NOT_YOURS = "No incident of yours is open to answer."  # [proposed]
BY_AIDE = "The aide never sends an order anyway."

INCIDENT_DAYS = 2  # [proposed] world days the person who could have allowed it has to answer
INCIDENT_REGARD = 2  # [proposed] regard lost both ways when disowned, and between heads abroad
BACK_AT = 1  # [proposed] a card backs its commander at this regard or more
DISMISS_AT = -2  # [proposed] and dismisses him at this regard or less; else it disowns


class Act(StrEnum):
    """An act a post's holder may attempt without leave: a closed list."""

    BORDER = "border"
    FIRE_FIRST = "fire_first"


class Cause(StrEnum):
    """What an incident is about."""

    DEFIED = "defied"
    """An order sent without leave was carried out."""
    REFUSED = "refused"
    """A step on an order from above was refused (CMD)."""


class Verdict(StrEnum):
    """How the person who could have allowed it answers an incident."""

    BACKED = "backed"
    DISOWNED = "disowned"
    DISMISSED = "dismissed"


class Defied(Model):
    """A held order sent anyway: the held order, the order it landed as, its seat, the
    acts it does, and the day; the person who could have allowed it, the nation it is
    done to when abroad, and the rule each force it sets a rule for held before. Sealed
    to the issuer's seat."""

    order_id: OrderId
    landed: OrderId
    issuer: SeatId
    acts: tuple[Act, ...] = Field(min_length=1, max_length=2)
    on: date
    superior: EntityId | None = None
    abroad: EntityId | None = None
    kept: dict[FeatureId, Engagement | None] = Field(default_factory=dict)


class Incident(Model):
    """An order sent anyway and carried out, or a step on an order from above refused:
    the question on the commander before his superior, and, once given, its answer.
    Sealed to the commander's seat and the superior's."""

    incident_id: Label
    order_id: OrderId
    cause: Cause
    commander: EntityId
    superior: EntityId
    seats: tuple[SeatId, ...] = Field(default=(), max_length=2)
    opened: date
    due: date
    abroad: EntityId | None = None
    verdict: Verdict | None = None
    answered: date | None = None
    by_card: bool = False


def on(state: "State") -> bool:
    from revisionist.core.state import Rule

    return Rule.DEFIANCE in state.rules


def allowed(state: "State", person: EntityId) -> frozenset[Act]:
    """The acts ``person``'s post lets him attempt without leave; none with the rule off."""
    if not on(state):
        return frozenset()
    card = state.cards.get(person)
    post = card.post if card is not None else None
    found = state.ladders.get(post) if post is not None else None
    return frozenset(found.without_leave) if found is not None else frozenset()


def acts(state: "State", seat: SeatId, asks: Iterable[Ask]) -> frozenset[Act]:
    """The acts a written order's asks do, told from their typed effects alone."""
    from revisionist.core.realism.war import polity_of

    issuer = state.seats[seat].embodies if seat in state.seats else None
    home = polity_of(state, issuer) if issuer is not None else None
    found: set[Act] = set()
    for ask in asks:
        effect = ask.effect
        if isinstance(effect, MoveForce):
            mover = _side(state, effect.force) or home
            if effect.to is not None and _foreign(state, mover, _held_by(state, effect.to)):
                found.add(Act.BORDER)
            if effect.posture is Posture.ATTACK:
                at = effect.to if effect.to is not None else _place(state, effect.force)
                if at is not None and _peaceful_near(state, mover, at):
                    found.add(Act.FIRE_FIRST)
        elif isinstance(effect, SetEngagement) and effect.rule is Engagement.SHOOT_ON_SIGHT:
            from revisionist.core.realism.locks import zone_of

            mover = (_side(state, effect.force) if effect.force is not None else None) or home
            zone = zone_of(state, effect.zone)
            if zone is not None and _peaceful_near(state, mover, zone):
                found.add(Act.FIRE_FIRST)
    return frozenset(found)


def may_send(state: "State", seat: SeatId, held: "HeldOrder") -> tuple[Act, ...]:
    """The acts of ``held`` when its own seat may send it anyway, in list order. Raises
    ``ValueError`` with the seat's words when the rule is off, or when an act is not on
    the issuer's post's list, or the order does no act at all."""
    if not on(state):
        raise ValueError(NOT_ON)
    done = acts(state, seat, held.asks) if held.form is None else frozenset()
    leave = allowed(state, state.seats[seat].embodies)
    if not done or not done <= leave:
        raise ValueError(NOT_WITHOUT_LEAVE)
    return tuple(a for a in Act if a in done)


def defiant(state: "State", order_id: OrderId) -> bool:
    """Whether a routed order was sent anyway and not since backed: once backed, the
    permission is treated as given for that order."""
    if not on(state) or order_id not in state.defied:
        return False
    found = state.incidents.get(incident_id(state.campaign_id, order_id))
    return found is None or found.verdict is not Verdict.BACKED


def superior(held: "HeldOrder") -> EntityId | None:
    """The person who could have allowed a held order: its deciding person, the head an
    ask goes to for a body, or a council's head."""
    d = held.decider
    if d.person is not None:
        return d.person
    if d.council is not None:
        return d.council.head
    return d.head


def abroad(state: "State", seat: SeatId, asks: Iterable[Ask]) -> EntityId | None:
    """The first polity, not the issuer's and not at war with it, an order's acts are
    done to; None when they are done at home."""
    from revisionist.core.realism.war import polity_of

    home = polity_of(state, state.seats[seat].embodies)
    for ask in asks:
        effect = ask.effect
        if isinstance(effect, MoveForce) and effect.to is not None:
            mover = _side(state, effect.force) or home
            other = _held_by(state, effect.to)
            if _foreign(state, mover, other):
                return other
    return None


def kept(state: "State", asks: Iterable[Ask]) -> dict[FeatureId, Engagement | None]:
    """The rule each force an order names in a rule of engagement holds now."""
    out: dict[FeatureId, Engagement | None] = {}
    for ask in asks:
        effect = ask.effect
        if isinstance(effect, SetEngagement) and effect.force is not None:
            found = state.features.get(effect.force)
            if found is not None:
                out.setdefault(effect.force, found.engagement)
    return out


def incident_id(campaign_id: str, order_id: OrderId) -> Label:
    return derived_id(campaign_id, "incident", order_id)


def _seats(state: "State", *people: EntityId) -> tuple[SeatId, ...]:
    from revisionist.core.state import seat_of_person

    out: list[SeatId] = []
    for who in people:
        seat = seat_of_person(state, who)
        if seat is not None and seat.seat_id not in out:
            out.append(seat.seat_id)
    return tuple(out)


def _open(
    state: "State",
    order_id: OrderId,
    cause: Cause,
    commander: EntityId,
    over: EntityId,
    day: date,
    nation: EntityId | None,
) -> "ev.IncidentOpened":
    from revisionist.core import events as ev

    return ev.IncidentOpened(
        incident=Incident(
            incident_id=incident_id(state.campaign_id, order_id),
            order_id=order_id,
            cause=cause,
            commander=commander,
            superior=over,
            seats=_seats(state, commander, over),
            opened=day,
            due=day + timedelta(days=INCIDENT_DAYS),
            abroad=nation,
        )
    )


def arising(state: "State", payloads: Sequence["ev.Payload"], day: date) -> list["ev.Payload"]:
    """The incidents a day's executions and steps open: an order sent anyway that its
    executor carried out, and a step on an order from up the holder's chain that he
    refused (CMD). One per order; none with the rule off, or with no one above."""
    from revisionist.core import events as ev
    from revisionist.core.realism.card import superiors
    from revisionist.core.realism.pipeline import StepAction
    from revisionist.core.state import Rule

    if not on(state):
        return []
    out: list[ev.Payload] = []
    seen: set[OrderId] = set()
    for p in payloads:
        oid = p.order_id if isinstance(p, ev.OrderExecuted | ev.OrderStepTaken) else None
        if oid is None or oid in seen:
            continue
        if incident_id(state.campaign_id, oid) in state.incidents:
            continue
        if isinstance(p, ev.OrderExecuted) and p.fidelity is not None:
            d = state.defied.get(oid)
            if d is None or d.superior is None or d.issuer not in state.seats:
                continue
            commander = state.seats[d.issuer].embodies
            if commander == d.superior:
                continue
            seen.add(oid)
            out.append(_open(state, oid, Cause.DEFIED, commander, d.superior, day, d.abroad))
            out += _abroad(state, commander, d.abroad, day)
        elif (
            isinstance(p, ev.OrderStepTaken)
            and p.outcome.action is StepAction.REFUSE
            and Rule.COMMAND in state.rules
            and oid in state.orders
        ):
            order = state.orders[oid]
            issuer = state.seats[order.issuer].embodies
            holder = p.outcome.person
            if holder == issuer or issuer not in superiors(state.cards, holder):
                continue
            seen.add(oid)
            out.append(_open(state, oid, Cause.REFUSED, holder, issuer, day, None))
    return out


def _abroad(
    state: "State", commander: EntityId, nation: EntityId | None, day: date
) -> list["ev.Payload"]:
    """Abroad: the regard between the two nations' heads falls."""
    from revisionist.core.realism.conference import head
    from revisionist.core.realism.ladder import regard
    from revisionist.core.realism.war import polity_of

    if nation is None:
        return []
    home = polity_of(state, commander)
    ours = head(state, home) if home is not None else None
    theirs = head(state, nation)
    if ours is None or theirs is None or ours == theirs:
        return []
    return [
        regard(state, ours, theirs, INCIDENT_REGARD),
        regard(state, theirs, ours, INCIDENT_REGARD),
    ]


def due(state: "State", day: date) -> list[Label]:
    """The incidents left unanswered past their due day, oldest first: the card answers."""
    if not on(state):
        return []
    late = (i for i in state.incidents.values() if i.verdict is None and i.due < day)
    return [i.incident_id for i in sorted(late, key=lambda i: (i.opened, i.incident_id))]


def card_verdict(state: "State", incident: Incident) -> Verdict:
    """The superior's card's answer, by how he regards the commander [proposed]."""
    regard = next(
        (
            r.disposition
            for r in state.relationships.values()
            if r.a == incident.superior and r.b == incident.commander
        ),
        0,
    )
    if regard >= BACK_AT:
        return Verdict.BACKED
    if regard <= DISMISS_AT:
        return Verdict.DISMISSED
    return Verdict.DISOWNED


def answer(
    state: "State", incident: Incident, verdict: Verdict, day: date, *, by_card: bool
) -> list["ev.Payload"]:
    """The events an answer lands. Backed: the order is no longer defiant. Disowned:
    where the order set a rule of engagement the force's old rule is put back, and the
    regard between the two falls both ways. Dismissed: a step down the commander's
    ladder, by its rules and with its notice."""
    from revisionist.core import events as ev
    from revisionist.core.realism import ladder

    out: list[ev.Payload] = [
        ev.IncidentAnswered(
            incident_id=incident.incident_id,
            verdict=verdict,
            on=day,
            by_card=by_card,
            seats=incident.seats,
        )
    ]
    c, s = incident.commander, incident.superior
    if verdict is Verdict.DISOWNED:
        d = state.defied.get(incident.order_id) if incident.cause is Cause.DEFIED else None
        for fid, rule in (d.kept if d is not None else {}).items():
            force = state.features.get(fid)
            if force is not None and force.engagement != rule:
                out.append(ev.FeatureSet(feature=force.model_copy(update={"engagement": rule})))
        out += [
            ladder.regard(state, c, s, INCIDENT_REGARD),
            ladder.regard(state, s, c, INCIDENT_REGARD),
        ]
    elif verdict is Verdict.DISMISSED:
        card = state.cards.get(c)
        post = card.post if card is not None else None
        moved = ladder.order(state, c, post, False, s, day) if post is not None else None
        out += moved or []
    return out


def told(view: "View", incident: Incident) -> str:
    """What a seat is told of an incident, built from its own view alone."""

    def name(who: EntityId) -> str:
        found = view.entities.get(who)
        return found.name if found is not None else "your superior"

    what = (
        "the order you sent without leave"
        if incident.cause is Cause.DEFIED
        else ("your refusal of an order from above")
    )
    if incident.verdict is not None:
        return f"{name(incident.superior)} has {incident.verdict.value} you over {what}."
    return (
        f"{name(incident.superior)} is to answer for {what} by "
        f"{incident.due.isoformat()}: backed, disowned or dismissed."
    )


def as_seen(incidents: Mapping[Label, Incident], seat: SeatId) -> dict[Label, Incident]:
    return {k: i for k, i in incidents.items() if seat in i.seats}


def _held_by(state: "State", place: EntityId) -> EntityId | None:
    from revisionist.core.realism import territory

    area = territory.area_of(state, place, Domain.LAND)
    return territory.holder(state, area) if area is not None else None


def _foreign(state: "State", mover: EntityId | None, other: EntityId | None) -> bool:
    """Whether ``other`` is a polity other than ``mover`` and not at war with it."""
    from revisionist.core.realism.war import at_war

    return (
        mover is not None
        and other is not None
        and other != mover
        and not at_war(state, mover, other)
    )


def _peaceful_near(state: "State", mover: EntityId | None, area: EntityId) -> bool:
    """Whether a polity not at war with ``mover`` holds ``area`` or keeps a force there."""
    from revisionist.core.realism import territory

    if _foreign(state, mover, _held_by(state, area)):
        return True
    for f in state.features.values():
        side = territory.nation(state, f.side)
        if side is None or not f.places:
            continue
        here = territory.area_of(state, f.places[0], Domain.LAND)
        sea = territory.area_of(state, f.places[0], Domain.SEA)
        if area in (here, sea, f.places[0]) and _foreign(state, mover, side):
            return True
    return False


def _side(state: "State", force: FeatureId) -> EntityId | None:
    from revisionist.core.realism import territory

    found = state.features.get(force)
    return territory.nation(state, found.side) if found is not None else None


def _place(state: "State", force: FeatureId) -> EntityId | None:
    found = state.features.get(force)
    return found.places[0] if found is not None and found.places else None


__all__ = [
    "BACK_AT",
    "BY_AIDE",
    "DEFIANT_LOYALTY",
    "DISMISS_AT",
    "INCIDENT_DAYS",
    "INCIDENT_REGARD",
    "NOT_ON",
    "NOT_WITHOUT_LEAVE",
    "NOT_YOURS",
    "Act",
    "Cause",
    "Defied",
    "Incident",
    "Verdict",
    "abroad",
    "acts",
    "allowed",
    "answer",
    "arising",
    "as_seen",
    "card_verdict",
    "defiant",
    "due",
    "incident_id",
    "kept",
    "may_send",
    "on",
    "superior",
    "told",
]
