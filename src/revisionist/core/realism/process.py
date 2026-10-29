"""Process and influence parts (engine v2, spec §8.2). Wave B unit B5.

A process part opens its pipeline as an ``order_drafted`` that carries the part
(``Order.routed_from``); an influence part is decided by its target's card policy
as ``influence_decided``.
"""

from collections.abc import Iterator
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, OrderId, PipelineId, derived_id
from revisionist.core.ontology import Controller
from revisionist.core.realism import reach
from revisionist.core.realism.effect import (
    ClauseKind,
    Effect,
    PartRef,
    ProposeMeasure,
    Route,
    RoutedOrder,
    RoutedPart,
    ShiftDisposition,
)
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.resolvers import friction
from revisionist.core.state import State

INTEREST_POINTS = 2  # [proposed] an ask that touches what the target cares about
ACCEPT_AT = 1  # [proposed] the score at which the target goes along
MIN_WORD = 4  # [proposed] shorter words ("the", "of") say nothing about an interest
WARLIKE = frozenset({"engagement", "move_force"})
NO_REACH = "You have no way to reach them."


def _parts(state: State, route: Route) -> Iterator[tuple[RoutedOrder, int, RoutedPart]]:
    for routed in sorted(state.routed.values(), key=lambda o: (o.filed, o.order_id)):
        for i, part in enumerate(routed.parts):
            if part.route is route:
                yield routed, i, part


def open_processes(state: State, today: date) -> list[ev.Payload]:
    """A pipeline order for each process part not yet carried."""
    carried = {o.routed_from for o in state.orders.values() if o.routed_from is not None}
    out: list[ev.Payload] = []
    for routed, i, part in _parts(state, Route.PROCESS):
        ref = PartRef(order_id=routed.order_id, part=i)
        if ref in carried or part.pipeline is None:
            continue
        measure = part.effect if isinstance(part.effect, ProposeMeasure) else None
        lever = "measure" if measure else (part.effect.kind if part.effect else "process")
        order = Order(
            order_id=OrderId(derived_id(state.campaign_id, "process", routed.order_id, i)),
            issuer=routed.issuer,
            lever=lever,
            pipeline=PipelineId(part.pipeline),
            params={},
            filed=routed.filed,
            measure=measure,
            routed_from=ref,
        )
        out.append(ev.OrderDrafted(order=order))
    return out


def _words(text: str) -> set[str]:
    return {w for w in text.lower().replace("_", " ").split() if len(w) >= MIN_WORD}


def _effect_words(effect: Effect) -> set[str]:
    texts: list[str] = [effect.kind]
    match effect.kind:
        case "measure":
            texts += [effect.title, *(c.subject for c in effect.clauses)]
        case "statement":
            texts.append(effect.theme)
        case "allocate":
            texts.append(effect.what)
        case "engagement":
            texts += [effect.zone, effect.rule]
        case "investigate":
            texts.append(effect.question)
        case "deal":
            texts += [*effect.offer, *effect.ask]
        case "appointment":
            texts.append(effect.office)
    return {w for t in texts for w in _words(str(t))}


def _warlike(effect: Effect) -> bool:
    if isinstance(effect, ProposeMeasure):
        return any(c.kind is ClauseKind.POWER for c in effect.clauses)
    return effect.kind in WARLIKE


def _keeps_out(interest: str) -> bool:
    low = interest.lower()
    return "out of the war" in low or ("keep" in low and " out" in low)


def _person(state: State, routed: RoutedOrder) -> EntityId:
    return state.seats[routed.issuer].embodies


def _name(state: State, who: EntityId) -> str:
    return state.entities[who].name


def decides(state: State, routed: RoutedOrder, part: RoutedPart) -> tuple[bool, str]:
    """The target's card policy [proposed]: accepted when the score reaches
    ``ACCEPT_AT``. One rule, so a model-backed policy can replace it."""
    assert part.target is not None
    target, issuer = part.target, _person(state, routed)
    card = state.cards.get(target)
    effects = (*((part.effect,) if part.effect else ()), *part.estimated)
    # disposition: loyalty to a principal, else the relationship (0 if none)
    if card is not None and issuer in card.principals:
        disposition = card.loyalty
    else:
        disposition = next(
            (r.disposition for r in state.relationships.values() if {r.a, r.b} == {target, issuer}),
            0,
        )
    # interest: the typed effects against the card's interests and doctrine, never ask words
    held = (*card.interests, *card.doctrine) if card else ()
    if any(_keeps_out(i) for i in held) and any(_warlike(e) for e in effects):
        interest = -INTEREST_POINTS
    elif {w for e in effects for w in _effect_words(e)} & _words(" ".join(held)):
        interest = INTEREST_POINTS
    else:
        interest = 0
    # leverage: estimated disposition shifts that touch the target, one point each way
    leverage = sum(
        (e.change > 0) - (e.change < 0)
        for e in part.estimated
        if isinstance(e, ShiftDisposition) and target in (e.of, e.toward)
    )
    # d: the seeded roll, -2..+2
    index = next(i for i, p in enumerate(routed.parts) if p is part)
    d = friction(state, routed.order_id, index, "influence", n=5) - 2
    accepted = disposition + interest + leverage + d >= ACCEPT_AT
    name = _name(state, target)
    if accepted:
        return True, f"{name} agreed to what you asked."
    if interest < 0:
        return False, f"{name} would not be moved: it would take the country nearer the war."
    return False, f"{name} would not be moved."


def _human(state: State, who: EntityId) -> bool:
    return any(s.embodies == who and s.controller is Controller.HUMAN for s in state.seats.values())


def influence_due(state: State, today: date) -> list[ev.Payload]:
    """A decision for each influence part due by ``today``. A target a human holds
    is left for that player and blocks nothing else."""
    out: list[ev.Payload] = []
    for routed, i, part in _parts(state, Route.INFLUENCE):
        if part.decided is not None or part.target is None or _human(state, part.target):
            continue
        channels = reach.channels_to(state, _person(state, routed), part.target)
        if not channels:
            if routed.filed <= today:
                out.append(
                    ev.InfluenceDecided(
                        order_id=routed.order_id,
                        part=i,
                        on=routed.filed,
                        accepted=False,
                        reason=NO_REACH,
                    )
                )
            continue
        on = routed.filed + timedelta(days=reach.transit_days(channels[0]))
        if on > today:
            continue
        accepted, reason = decides(state, routed, part)
        out.append(
            ev.InfluenceDecided(
                order_id=routed.order_id, part=i, on=on, accepted=accepted, reason=reason
            )
        )
    return out


__all__ = ["decides", "influence_due", "open_processes"]
