"""Applying a part's effects to the world (engine v2, spec §8.2-8.3). Wave B unit B4.

A part is applied once it is ready: a command carried out or refused, an estimate
ruled, an influence decided. ``apply_due`` lands ``effects_applied`` for each, and
``report`` is the paper its issuer gets back. Process parts are applied by their
pipeline's resolver, not here.
"""

import math
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.canary import scan_text
from revisionist.core.ids import (
    DocumentId,
    EntityId,
    FactId,
    FeatureId,
    RelationshipId,
    SeatId,
    derived_id,
)
from revisionist.core.ontology import Relationship
from revisionist.core.realism import reach
from revisionist.core.realism.card import ChannelKind, words
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.effect import (
    Allocate,
    Appointment,
    Deal,
    Disclosure,
    Effect,
    Engagement,
    Fidelity,
    Investigate,
    MakeStatement,
    MoveForce,
    ProposeMeasure,
    Route,
    RoutedOrder,
    RoutedPart,
    SetEngagement,
    ShiftDisposition,
)
from revisionist.core.realism.geography import SPEED_KM_PER_DAY, Feature, km_between
from revisionist.core.state import State
from revisionist.core.visibility import private_to

# Copied from ``engine.estimate.REASON_WITHHELD``: the core never imports the engine.
REASON_WITHHELD = "The referee's account of this cannot be shown to you."

LINE = 60
"""A body line holds a label's worth of words."""
LINES = 6
"""The most lines of an estimator's reason a report carries. [proposed]"""

_CARRIED: dict[Fidelity, str] = {
    Fidelity.FULL: "carried out",
    Fidelity.LOOSE: "carried out loosely",
    Fidelity.SLOW: "carried out late",
    Fidelity.PARTIAL: "carried out in part",
}


def as_carried(effect: Effect, fidelity: Fidelity) -> Effect | None:
    """What an executor of this fidelity actually lands; None when nothing does."""
    match fidelity, effect:
        # FULL and SLOW: as ordered (SLOW only lands later, already in the date).
        case Fidelity.FULL | Fidelity.SLOW, _:
            return effect
        # LOOSE: a move keeps its destination and drops its posture.
        case Fidelity.LOOSE, MoveForce(to=None):
            return None
        case Fidelity.LOOSE, MoveForce():
            return effect.model_copy(update={"posture": None})
        # LOOSE: shoot on sight is read as defend.
        case Fidelity.LOOSE, SetEngagement(rule=Engagement.SHOOT_ON_SIGHT):
            return effect.model_copy(update={"rule": Engagement.DEFEND})
        # PARTIAL: a move lands its posture only, the force stays where it is.
        case Fidelity.PARTIAL, MoveForce(posture=None):
            return None
        case Fidelity.PARTIAL, MoveForce():
            return effect.model_copy(update={"to": None})
        # PARTIAL: an allocation lands half, rounded down.
        case Fidelity.PARTIAL, Allocate():
            return effect.model_copy(update={"amount": effect.amount // 2})
        # Everything else, as ordered.
        case _:
            return effect


def _ready(order: RoutedOrder, part: RoutedPart) -> date | None:
    """The day the fold would accept ``EffectsApplied`` for this part, or None."""
    if part.route is Route.PROCESS:
        return None
    if part.effect is None and (not part.was_estimated or not (part.estimated or part.reason)):
        # Not yet ruled on, or the estimate failed: the part stays unresolved.
        return None
    if part.route is Route.COMMAND:
        done = part.executed
    else:
        done = part.decided
    if done is None:
        return None
    return max(done, order.filed)


class _World:
    """Features and relationships as they stand mid-pass, so two parts landing on the
    same force or relationship on one day see each other."""

    def __init__(self, state: State) -> None:
        self.state = state
        self.features: dict[FeatureId, Feature] = dict(state.features)
        self.relationships: dict[RelationshipId, Relationship] = dict(state.relationships)

    def relationship(self, a: EntityId, b: EntityId) -> Relationship | None:
        return next(
            (r for r in self.relationships.values() if {r.a, r.b} == {a, b}),
            None,
        )


def _move(world: _World, effect: MoveForce, on: date) -> list[ev.Payload]:
    force = world.features.get(effect.force)
    if force is None:
        return []
    as_of = max(on, force.as_of)
    update: dict[str, object] = {"as_of": as_of}
    if effect.posture is not None:
        update["posture"] = effect.posture
    here = force.places[0]
    if effect.to is not None and effect.to != here:
        # Travel as ``resolvers.movement.resolve`` computes it: great-circle distance
        # at the kind's pace, at least a day.
        origin = world.state.entities[here].at
        dest = world.state.entities[effect.to].at
        km = 0 if origin is None or dest is None else km_between(origin, dest)
        days = max(1, math.ceil(km / SPEED_KM_PER_DAY[force.kind]))
        update |= {"bound_for": effect.to, "arrives": as_of + timedelta(days=days), "legs": ()}
    elif effect.to is not None:
        update |= {"bound_for": None, "arrives": None, "legs": ()}
    moved = force.model_copy(update=update)
    world.features[effect.force] = moved
    return [ev.FeatureSet(feature=moved)]


def _engage(world: _World, effect: SetEngagement, issuer: EntityId, on: date) -> list[ev.Payload]:
    if effect.force is not None:
        named = [effect.force]
    else:
        # [proposed] no force named: every force in the issuer's authority domains.
        card = world.state.cards.get(issuer)
        named = sorted({f for d in card.authority for f in d.forces}) if card else []
    out: list[ev.Payload] = []
    for fid in named:
        force = world.features.get(fid)
        if force is None:
            continue
        set_ = force.model_copy(update={"engagement": effect.rule, "as_of": max(on, force.as_of)})
        world.features[fid] = set_
        out.append(ev.FeatureSet(feature=set_))
    return out


def _shift(world: _World, effect: ShiftDisposition, issuer_seat: SeatId) -> ev.Payload:
    now = world.relationship(effect.of, effect.toward)
    if now is None:
        rel = Relationship(
            relationship_id=RelationshipId(
                derived_id(world.state.campaign_id, "rel", effect.of, effect.toward)
            ),
            a=effect.of,
            b=effect.toward,
            disposition=max(-5, min(5, effect.change)),
            scope=private_to(issuer_seat),  # [proposed]
        )
    else:
        rel = now.model_copy(
            update={"disposition": max(-5, min(5, now.disposition + effect.change))}
        )
    world.relationships[rel.relationship_id] = rel
    return ev.RelationshipSet(relationship=rel)


# Recorded, no resolver yet: MakeStatement, Investigate, Deal, Allocate, Appointment and
# ProposeMeasure outside a process change nothing in the world beyond the report; the
# record is the routed part and its ``applied`` date. Card loyalty has no event, so a
# shift of disposition toward a principal moves the relationship only. [proposed]
def _land(
    world: _World, effect: Effect, issuer_seat: SeatId, issuer: EntityId, on: date
) -> tuple[list[ev.Payload], list[FactId]]:
    match effect:
        case MoveForce():
            return _move(world, effect, on), []
        case SetEngagement():
            return _engage(world, effect, issuer, on), []
        case ShiftDisposition():
            return [_shift(world, effect, issuer_seat)], []
        case Disclosure(reveal=True) if effect.fact in world.state.facts:
            return [], [effect.fact]
        case _:
            # Disclosure(reveal=False) changes nothing in this wave. [proposed]
            return [], []


def apply_due(state: State, today: date) -> list[ev.Payload]:
    """Every part ready to apply on ``today``, earliest filed first, each once."""
    world = _World(state)
    out: list[ev.Payload] = []
    for order in sorted(state.routed.values(), key=lambda o: (o.filed, o.order_id)):
        issuer_seat = order.issuer
        issuer = state.seats[issuer_seat].embodies
        for i, part in enumerate(order.parts):
            ready = _ready(order, part)
            if ready is None or part.applied is not None:
                continue
            on = max(today, ready)
            effects: list[Effect] = []
            if part.refusal:
                pass  # a refusal applies nothing, but still closes the part
            elif part.route is Route.COMMAND:
                if part.effect is not None and part.fidelity is not None:
                    carried = as_carried(part.effect, part.fidelity)
                    effects += [carried] if carried is not None else []
                effects += part.estimated
            elif part.accepted:
                effects += [part.effect] if part.effect is not None else []
                effects += part.estimated
            else:
                # A rebuffed approach can still sour a relation.
                effects += [e for e in part.estimated if isinstance(e, ShiftDisposition)]
            events: list[ev.Payload] = []
            revealed: list[FactId] = []
            for effect in effects:
                landed, facts = _land(world, effect, issuer_seat, issuer, on)
                events += landed
                revealed += [f for f in facts if f not in revealed]
            out += events
            out.append(
                ev.EffectsApplied(order_id=order.order_id, part=i, on=on, revealed=tuple(revealed))
            )
            doc = report(state, order, i, on)
            if doc is not None:
                out.append(doc)
    return out


def _name(state: State, who: EntityId | FeatureId) -> str:
    if who in state.entities:
        return state.entities[EntityId(who)].name
    if who in state.features:
        return state.features[FeatureId(who)].name
    return "someone"


def _describe(state: State, part: RoutedPart) -> str:
    """What was ordered, in plain words."""
    match part.effect:
        case None:
            return "Your request"
        case SetEngagement(rule=rule, zone=zone):
            return f"{words(rule.value)} in {zone}"
        case MoveForce(force=force, to=to):
            if to is None:
                return f"Orders to {_name(state, force)}"
            return f"Move {_name(state, force)} to {_name(state, to)}"
        case Allocate(what=what, recipient=recipient):
            return f"Allocate {what} to {_name(state, recipient)}"
        case Appointment(person=person, office=office, appoint=appoint):
            return f"{'Appoint' if appoint else 'Remove'} {_name(state, person)}: {office}"
        case ProposeMeasure(title=title):
            return title
        case MakeStatement(theme=theme):
            return f"Statement on {theme}"
        case Investigate(target=target):
            return f"Inquiry into {_name(state, target)}"
        case Deal(counterparty=who):
            return f"Deal with {_name(state, who)}"
        case ShiftDisposition(of=of, toward=toward):
            return f"Word to {_name(state, of)} about {_name(state, toward)}"
        case Disclosure():
            return "Disclosure"
    return "Your request"


def _outcome(part: RoutedPart) -> str:
    if part.route is Route.INFLUENCE:
        return "agreed" if part.accepted else "rebuffed"
    if part.refusal:
        return "refused"
    return _CARRIED[part.fidelity] if part.fidelity is not None else "carried out"


def _lines(text: str, label: str) -> list[BodyField]:
    """``text`` in body lines of at most ``LINE`` characters, broken at words."""
    out: list[str] = []
    line = ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > LINE:
            out.append(line)
            line = ""
        line = f"{line} {word}".strip()[:LINE]
    if line:
        out.append(line)
    return [
        BodyField(label=label if k == 0 else f"{label} (cont.)", value=v)
        for k, v in enumerate(out[:LINES])
    ]


def report(state: State, order: RoutedOrder, part: int, on: date) -> ev.DocumentIssued | None:
    """The paper the issuer gets for one applied part."""
    if part >= len(order.parts) or order.issuer not in state.seats:
        return None
    routed = order.parts[part]
    if _ready(order, routed) is None:
        return None
    issuer = state.seats[order.issuer].embodies

    def safe(text: str) -> str:
        return REASON_WITHHELD if scan_text(state, order.issuer, text) else text

    if routed.route is Route.INFLUENCE and routed.target is not None:
        author = routed.target
        title = f"Your approach to {_name(state, author)}: {_outcome(routed)}"
    else:
        author = routed.executor if routed.executor is not None else issuer
        title = f"{_describe(state, routed)}: {_outcome(routed)}"
    if len(title) > LINE:
        title = title[: LINE - 1].rsplit(" ", 1)[0].rstrip(" ,:;") + "…"
    body = [BodyField(label="Ordered", value=safe(_describe(state, routed))[:LINE])]
    if routed.refusal:
        body.append(BodyField(label="Refused under", value=safe(routed.refusal)[:LINE]))
    elif routed.fidelity is not None:
        body.append(BodyField(label="Carried out", value=routed.fidelity.value))
    if routed.reason:
        body += _lines(safe(routed.reason), "Account")
    channels = reach.channels_to(state, issuer, author) if author != issuer else ()
    channel = channels[0] if channels else ChannelKind.IN_PERSON
    doc_id = DocumentId(derived_id(state.campaign_id, "report", order.order_id, part))
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.MEMO if routed.route is Route.COMMAND else DocumentKind.LETTER,
            author=author,
            issued=on,
            arrives=on + timedelta(days=reach.transit_days(channel)),
            channel=channel,
            classification=Classification.CONFIDENTIAL,  # [proposed]
            title=safe(title),
            body=tuple(body),
            scope=private_to(order.issuer),
        ),
        truth=DocumentTruth(doc_id=doc_id),
    )


__all__ = ["apply_due", "as_carried", "report"]
