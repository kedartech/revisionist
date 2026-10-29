"""The router and the command path (engine v2; spec §8.1-8.2).

``route`` reads one ask against the issuer's card and answers with a routed part or
the words for why no route takes it. A command goes straight to the domain's
executor, who carries it out with a fidelity set here from loyalty, competence and
workload, or refuses it under a stated rule. No approval step stands between.
Pure: the only randomness is ``friction``.
"""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.card import Domain, SeatCard
from revisionist.core.realism.effect import (
    REFUSAL_LOYALTY,
    Appointment,
    EffectKind,
    Fidelity,
    FidelityInputs,
    MoveForce,
    ProposeMeasure,
    Route,
    RoutedOrder,
    RoutedPart,
    Routing,
    SetEngagement,
)
from revisionist.core.realism.resolvers import friction
from revisionist.core.state import State

REFUSE_PCT = 50  # [proposed] chance in 100 that an executor at or below the floor refuses
FREE_COMMANDS = 2  # [proposed] commands an executor carries before the load tells
EXECUTE_DAYS: dict[Fidelity, int] = {
    Fidelity.FULL: 1,
    Fidelity.LOOSE: 1,
    Fidelity.PARTIAL: 1,
    Fidelity.SLOW: 2,
}  # [proposed] days after filing; band A needs every value, and REFUSE_DAYS, at most 2
REFUSE_DAYS = 1  # [proposed]
DEFAULT_LOYALTY, DEFAULT_COMPETENCE = 0, 3  # [proposed] a person with no card


def _name(state: State, who: EntityId) -> str:
    found = state.entities.get(who)
    return found.name if found is not None else "that person"


def _domain_for(card: SeatCard, ask: Ask) -> Domain | None:
    effect = ask.effect
    if effect is None:
        return None
    kind = EffectKind(effect.kind)
    force = effect.force if isinstance(effect, MoveForce | SetEngagement) else None
    for domain in card.authority:
        if kind not in domain.effects:
            continue
        if force is not None and force not in domain.forces:
            continue
        return domain
    return None


def _process_pipeline(card: SeatCard) -> str | None:
    """[proposed] The pipeline of the first votes lever, else the card's first pipeline."""
    for lever in card.levers:
        if lever.resolver == "votes":
            return lever.pipeline
    return card.pipelines[0] if card.pipelines else None


def _not_in_service(state: State, ask: Ask, on: date) -> str:
    effect = ask.effect
    if not isinstance(effect, MoveForce | SetEngagement) or effect.force is None:
        return ""
    feature = state.features.get(effect.force)
    if feature is None or feature.in_service is None or on >= feature.in_service:
        return ""
    return f"{feature.name} is not in service until {feature.in_service:%-d %B %Y}."


def route(state: State, issuer: SeatId, ask: Ask, on: date) -> Routing:
    """Command inside the card's authority; process for a measure; influence on a named
    person; otherwise the words for why nobody can take it."""
    card = state.cards[state.seats[issuer].embodies]
    late = _not_in_service(state, ask, on)
    if late:
        return Routing(refusal=late)
    domain = _domain_for(card, ask)
    if domain is not None:
        return Routing(
            part=RoutedPart(
                route=Route.COMMAND,
                effect=ask.effect,
                domain=domain.name,
                executor=domain.executor,
            )
        )
    if isinstance(ask.effect, ProposeMeasure):
        pipeline = _process_pipeline(card)
        if pipeline is not None:
            return Routing(
                part=RoutedPart(route=Route.PROCESS, effect=ask.effect, pipeline=pipeline)
            )
    if ask.target is not None and ask.target in state.entities:
        return Routing(part=RoutedPart(route=Route.INFLUENCE, effect=ask.effect, target=ask.target))
    if ask.effect is None and ask.target is None:
        return Routing(refusal="Name who should act on it.")
    return Routing(refusal="Nobody under you commands that. Name the person who decides it.")


def fidelity_inputs(state: State, executor: EntityId | None) -> FidelityInputs:
    """Loyalty and competence from the executor's card, and the command parts they
    already carry and have not carried out."""
    card = state.cards.get(executor) if executor is not None else None
    workload = sum(
        1
        for order in state.routed.values()
        for part in order.parts
        if executor is not None
        and part.route is Route.COMMAND
        and part.executor == executor
        and part.executed is None
    )
    return FidelityInputs(
        loyalty=card.loyalty if card else DEFAULT_LOYALTY,
        competence=card.competence if card else DEFAULT_COMPETENCE,
        workload=workload,
    )


def outside_the_law(state: State, order: RoutedOrder, part: int) -> str:
    """The words of the rule that puts a command beyond the office's lawful power, or
    "" when it is lawful. [proposed] Rules join here as they are written."""
    routed = order.parts[part]
    issuer = state.seats[order.issuer].embodies
    if isinstance(routed.effect, Appointment):
        card = state.cards.get(routed.effect.person)
        if card is None or issuer not in card.principals:
            return "outside the law: that person does not answer to your office"
    return ""


def carry_out(state: State, order: RoutedOrder, part: int) -> tuple[Fidelity | None, str]:
    """How the executor carries out a command part: ``(fidelity, "")``, or
    ``(None, the rule they refused under)``."""
    routed = order.parts[part]
    if routed.executor is None:
        return Fidelity.FULL, ""
    unlawful = outside_the_law(state, order, part)
    if unlawful:
        return None, unlawful
    inputs = fidelity_inputs(state, routed.executor)
    if inputs.loyalty <= REFUSAL_LOYALTY:
        if friction(state, order.order_id, part, "refuse", n=100) < REFUSE_PCT:
            who = _name(state, routed.executor).split()[-1]
            return None, f"loyalty {inputs.loyalty}: {who} will not carry it out"
    d = friction(state, order.order_id, part, "fidelity", n=3) - 1
    score = inputs.loyalty + (inputs.competence - 3) - max(0, inputs.workload - FREE_COMMANDS) + d
    if score >= 1:
        return Fidelity.FULL, ""
    if score == 0:
        return Fidelity.LOOSE, ""
    if score == -1:
        return Fidelity.SLOW, ""
    return Fidelity.PARTIAL, ""


def execute_on(order: RoutedOrder, part: int, fidelity: Fidelity | None) -> date:
    """The day a command part is carried out, or refused when ``fidelity`` is None."""
    del part
    days = REFUSE_DAYS if fidelity is None else EXECUTE_DAYS[fidelity]
    return order.filed + timedelta(days=days)


def due_executions(state: State, today: date) -> list[ev.OrderExecuted]:
    """Every command part whose day has come and is not yet carried out, earliest first."""
    out: list[ev.OrderExecuted] = []
    for order in state.routed.values():
        for i, part in enumerate(order.parts):
            if part.route is not Route.COMMAND or part.executed is not None:
                continue
            fidelity, refusal = carry_out(state, order, i)
            on = execute_on(order, i, fidelity)
            if on <= today:
                out.append(
                    ev.OrderExecuted(
                        order_id=order.order_id, part=i, on=on, fidelity=fidelity, refusal=refusal
                    )
                )
    return sorted(out, key=lambda e: (e.on, e.order_id, e.part))


__all__ = [
    "carry_out",
    "due_executions",
    "execute_on",
    "fidelity_inputs",
    "outside_the_law",
    "route",
]
