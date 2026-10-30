"""How each routed order landed (Phase 4 unit S3), built from the seat's own view.

Never the estimator's ``rationale``, never its engine-only effects: ``View.routed``
carries neither, and this module reads nothing else about the order. The view keeps
no free text for an ask, so each ask is spoken from its typed effect.
"""

from datetime import date
from hashlib import sha256

from revisionist.core.ids import SeatId
from revisionist.core.project import project
from revisionist.core.realism import effect as rx
from revisionist.core.realism.card import words
from revisionist.core.state import State, View
from revisionist.engine.web.realism_api import OrderResult, ResultPart

_FIDELITY = {
    rx.Fidelity.FULL: "Carried out as ordered",
    rx.Fidelity.LOOSE: "Carried out loosely",
    rx.Fidelity.SLOW: "Carried out, but slowly",
    rx.Fidelity.PARTIAL: "Only partly carried out",
}


def _day(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def _who(view: View, who: str) -> str:
    found = view.entities.get(who)  # type: ignore[call-overload]
    return str(found.name) if found is not None else "someone unknown"


def _ask(state: State, view: View, effect: rx.Effect | None) -> str:
    match effect:
        case None:
            return "A request in your own words"
        case rx.MoveForce():
            f = state.features.get(effect.force)
            how = effect.posture.value if effect.posture else "move"
            return f"Move {f.name if f else 'a force'} ({how})"
        case rx.SetEngagement():
            return f"Order the rule {words(effect.rule.value).lower()} in {effect.zone}"
        case rx.Allocate():
            return (
                f"Allocate {effect.amount} {effect.unit} of {effect.what} "
                f"to {_who(view, effect.recipient)}"
            )
        case rx.Appointment():
            verb = "Appoint" if effect.appoint else "Dismiss"
            return f"{verb} {_who(view, effect.person)}: {effect.office}"
        case rx.ProposeMeasure():
            return f"Put forward {effect.title}"
        case rx.MakeStatement():
            return f"Make a statement on {effect.theme}"
        case rx.Investigate():
            return f"Look into {_who(view, effect.target)}: {effect.question}"
        case rx.Deal():
            verb = "Accept" if effect.accept else "Offer"
            return f"{verb} a deal with {_who(view, effect.counterparty)}"
        case rx.ShiftDisposition():
            return f"Change how {_who(view, effect.of)} feels about {_who(view, effect.toward)}"
        case rx.Disclosure():
            return "Reveal a fact" if effect.reveal else "Keep a fact quiet"
    return "A request in your own words"


def _part(state: State, view: View, p: rx.PartView) -> ResultPart:
    to: str | None = None
    match p.route:
        case rx.Route.COMMAND:
            route = "Your command"
            to = _who(view, p.executor) if p.executor is not None else None
        case rx.Route.PROCESS:
            line = state.pipelines.get(p.pipeline) if p.pipeline is not None else None
            route = f"Through {line.name if line else 'the proper channel'}"
        case rx.Route.INFLUENCE:
            route = "Your persuasion"
            to = _who(view, p.target) if p.target is not None else None
    return ResultPart(
        ask=_ask(state, view, p.effect),
        to=to,
        route=route,
        fidelity=_FIDELITY[p.fidelity] if p.fidelity is not None else None,
        refused_under=f"Refused under {p.refusal.replace('_', ' ')}" if p.refusal else None,
        reason=p.reason,
        accepted=p.accepted,
        applied=_day(p.applied) if p.applied is not None else None,
    )


def results(state: State, seat: SeatId) -> list[OrderResult]:
    """Phase 4 unit S3: the seat's routed orders, newest first, each part in words."""
    view = project(state, seat)
    mine = list(view.routed.values())
    out: list[OrderResult] = []
    for order in sorted(reversed(mine), key=lambda o: o.filed, reverse=True):
        token = sha256(str(order.order_id).encode()).hexdigest()[:12]
        out.append(
            OrderResult(
                id=token,
                filed=_day(order.filed),
                parts=[_part(state, view, p) for p in order.parts],
            )
        )
    return out


__all__ = ["results"]
