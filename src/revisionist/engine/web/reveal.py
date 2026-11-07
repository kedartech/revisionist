"""The end-of-game reveal (Phase 4 unit S5): secret goals, covert acts, each seat's
style history and the estimator's full rationale.

The server calls this for an ended game only, and only for an account that held a
seat in it. It is the one read that does not pass ``snapshot.checked``.
"""

from collections.abc import Iterable

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.ontology import Controller
from revisionist.core.realism.card import words
from revisionist.core.realism.effect import Route, RoutedPart
from revisionist.core.state import State
from revisionist.core.visibility import Visibility
from revisionist.engine.web.realism_api import Reveal, RevealRuling, RevealSeat

STYLES = {
    "free": "Free play",
    "guided": "Guided",
    "beginner": "Beginner",
}


def _who(state: State, entity: EntityId | None) -> str:
    found = state.entities.get(entity) if entity is not None else None
    return found.name if found is not None else "someone"


def _concerns(state: State, part: RoutedPart) -> str:
    return _who(state, part.target if part.route is Route.INFLUENCE else part.executor)


def _part_words(state: State, part: RoutedPart) -> str:
    """The ask is not kept on the part; this is what its route says it was."""
    if part.route is Route.INFLUENCE:
        return f"Press {_who(state, part.target)} to go along"
    if part.route is Route.COMMAND:
        domain = words(part.domain).lower() if part.domain else "orders"
        return f"Have {_who(state, part.executor)} act on {domain}"
    return "Put a matter through its process"


def _style_words(p: ev.PlayStyleSet) -> str:
    said = STYLES.get(p.style.value, words(p.style.value))
    if not p.standing:
        return said
    kinds = ", ".join(sorted(words(k.value).lower() for k in p.standing))
    return f"{said}, standing orders for {kinds}"


def build(state: State, log: Iterable[Event]) -> Reveal:
    """The whole table's record, from the truth and the full log."""
    people = [s for s in state.seats.values() if s.controller is Controller.HUMAN]
    covert: dict[SeatId, list[str]] = {s.seat_id: [] for s in people}
    styles: dict[SeatId, list[str]] = {s.seat_id: [] for s in people}
    rulings: dict[SeatId, list[RevealRuling]] = {s.seat_id: [] for s in people}
    name = ""
    for e in log:
        p = e.payload
        if isinstance(p, ev.CampaignCreated):
            name = p.name
        elif isinstance(p, ev.PlayStyleSet) and p.seat_id in styles:
            styles[p.seat_id].append(_style_words(p))
        elif isinstance(p, ev.OrderRouted) and e.scope.visibility is Visibility.COVERT:
            if p.order.issuer in covert:
                covert[p.order.issuer].extend(_part_words(state, x) for x in p.order.parts)
        elif isinstance(p, ev.EffectsEstimated) and not p.failed:
            order = state.routed.get(p.order_id)
            if order is not None and order.issuer in rulings and p.part < len(order.parts):
                rulings[order.issuer].append(
                    RevealRuling(
                        on=_concerns(state, order.parts[p.part]),
                        ask=_part_words(state, order.parts[p.part]),
                        rationale=p.rationale,
                    )
                )
    seats = [
        RevealSeat(
            person=s.name,
            goals=[g.text for g in state.goals.values() if g.seat_id == s.seat_id],
            covert=covert[s.seat_id],
            styles=styles[s.seat_id],
            rulings=rulings[s.seat_id],
        )
        for s in people
    ]
    return Reveal(name=name, seats=seats)


__all__ = ["build"]
