"""The agenda on the web (Phase 4 unit S2): live mandates, offered options, the style.

Options come from ``OptionsOffered``, produced at wake open by ``options.offer``.
Picking one files it through the ordinary order path, so it is what a free player
could have typed.
"""

import re
from collections.abc import Iterable
from datetime import date

from revisionist.core import events as ev
from revisionist.core import record
from revisionist.core.events import Event
from revisionist.core.ids import CampaignId, EntityId, MandateId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import mandates
from revisionist.core.realism.agenda import Offer, Option, PlayStyle, TriggerKind
from revisionist.core.realism.effect import RoutedPart
from revisionist.core.state import State, View
from revisionist.engine import options, realism_tick
from revisionist.engine.store import EventStore, load_state
from revisionist.engine.web.realism_api import AgendaBlock, AgendaItem, AgendaOption, Reply

_PICK = re.compile(r"w(\d+)\.o(\d+)\.p(\d+)")
_STALE = "That offer has lapsed. Look at what you are offered now."


def _day(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def _wake(state: State) -> int:
    return state.wake.number if state.wake is not None else 0


def _latest(log: Iterable[Event], seat: SeatId, wake: int) -> ev.OptionsOffered | None:
    found: ev.OptionsOffered | None = None
    for event in log:
        p = event.payload
        if isinstance(p, ev.OptionsOffered) and p.seat_id == seat and p.wake == wake:
            found = p
    return found


def _filed(log: list[Event], seat: SeatId, wake: int) -> list[tuple[RoutedPart, ...]]:
    """The parts of each order ``seat`` routed while ``wake`` was open."""
    filed: list[tuple[RoutedPart, ...]] = []
    open_here = False
    for event in log:
        p = event.payload
        if isinstance(p, ev.WakeOpened):
            open_here = p.wake == wake
        elif open_here and isinstance(p, ev.OrderRouted) and p.order.issuer == seat:
            filed.append(p.order.parts)
    return filed


def _name(view: View, who: EntityId | None) -> str | None:
    if who is None:
        return None
    held = view.entities.get(who)
    return held.name if held is not None else "someone"


def _token(wake: int, offer: int, option: int) -> str:
    return f"w{wake}.o{offer}.p{option}"


def _shown(
    view: View, option: Option, pick: str, taken: bool, label: str | None = None
) -> AgendaOption:
    return AgendaOption(
        label=label or option.label,
        to=_name(view, option.to),
        risk=option.risk,
        historical=option.historical,
        pick=pick,
        taken=taken,
    )


def _listed(
    view: View, made: ev.OptionsOffered, index: int, filed: list[tuple[RoutedPart, ...]]
) -> tuple[list[AgendaOption], bool]:
    """The offer's options for the client; a guided plan is its asks in order, every
    step carrying the plan's one token and one taken flag. The flag: whether it is a plan."""
    offer = made.offers[index]
    if offer.style is PlayStyle.GUIDED:
        plan = offer.options[0]
        pick = _token(made.wake, index, 0)
        taken = record.taken(plan.asks, filed)
        return [_shown(view, plan, pick, taken, a.ask) for a in plan.asks], True
    return [
        _shown(view, o, _token(made.wake, index, n), record.taken(o.asks, filed))
        for n, o in enumerate(offer.options)
    ], False


def _causes(state: State, seat: SeatId, view: View) -> dict[MandateId, str]:
    """The headline behind each of the seat's mandates a history event issued, only where
    a page of that news is in the seat's view."""
    read = {
        doc.truth.news_id
        for doc in state.documents.values()
        if doc.view.doc_id in view.documents and doc.truth.news_id is not None
    }
    out: dict[MandateId, str] = {}
    for template in state.templates.values():
        trigger = template.trigger
        if trigger.on is not TriggerKind.HISTORY or trigger.history is None:
            continue
        news_id = derived_id(state.campaign_id, "news", "history", trigger.history)
        news = state.news.get(news_id)
        if news is not None and news_id in read:
            out[mandates._mandate_id(state, template, seat)] = news.headline
    return out


def agenda(state: State, seat: SeatId, log: Iterable[Event]) -> AgendaBlock:
    """Each live mandate and the seat's offers from ``log``, all from its own view."""
    view = project(state, seat)
    events = list(log)
    made = _latest(events, seat, _wake(state))
    filed = _filed(events, seat, made.wake) if made is not None else []
    causes = _causes(state, seat, view)
    items: list[AgendaItem] = []
    initiative: list[AgendaOption] = []
    by_mandate: dict[MandateId | None, int] = {}
    if made is not None:
        by_mandate = {o.mandate_id: i for i, o in enumerate(made.offers)}
        if None in by_mandate:
            initiative = _listed(view, made, by_mandate[None], filed)[0]
    for mandate in options._live(view):
        listed: list[AgendaOption] = []
        plan = False
        if made is not None and mandate.mandate_id in by_mandate:
            listed, plan = _listed(view, made, by_mandate[mandate.mandate_id], filed)
        items.append(
            AgendaItem(
                id=mandate.mandate_id,
                kind=mandate.kind.value.capitalize(),
                issuer=_name(view, mandate.issuer),
                text=mandate.text,
                issued=_day(mandate.issued),
                deadline=_day(mandate.expires),
                cause=causes.get(mandate.mandate_id),
                options=[] if plan else listed,
                plan=listed if plan else [],
            )
        )
    return AgendaBlock(style=seat_style(state, seat), items=items, initiative=initiative)


def seat_style(state: State, seat: SeatId) -> str:
    """The seat's own ``PlayStyle`` value, from its own view."""
    style = project(state, seat).style
    return (style or PlayStyle.FREE).value


def set_style(store: EventStore, campaign_id: CampaignId, seat: SeatId, style: str) -> Reply:
    """``options.set_style`` from the posted ``PlayStyle`` value. Also serves the
    style choice of a new game, once the seat holds a person."""
    try:
        chosen = PlayStyle(style.strip().lower())
    except ValueError:
        return Reply(reply="Choose free, guided or beginner.", refused=True)
    if seat not in load_state(store, campaign_id).seats:
        return Reply(reply="Take a seat first, then choose how you play.", refused=True)
    options.set_style(store, campaign_id, seat, chosen)
    said = {
        PlayStyle.FREE: "You will write your own orders.",
        PlayStyle.GUIDED: "You will be offered a plan each wake.",
        PlayStyle.BEGINNER: "You will be offered options each wake.",
    }
    return Reply(reply=said[chosen], refused=False)


def pick_option(store: EventStore, campaign_id: CampaignId, seat: SeatId, pick: str) -> Reply:
    """File the offered option ``pick`` names with ``realism_tick.commit_order``."""
    state = load_state(store, campaign_id)
    found = _PICK.fullmatch(pick)
    made = _latest(store.read(campaign_id), seat, _wake(state))
    if found is None or made is None or int(found[1]) != made.wake:
        return Reply(reply=_STALE, refused=True)
    index, n = int(found[2]), int(found[3])
    if index >= len(made.offers):
        return Reply(reply=_STALE, refused=True)
    offer: Offer = made.offers[index]
    if n >= len(offer.options):
        return Reply(reply=_STALE, refused=True)
    chosen = offer.options[n]
    try:
        realism_tick.commit_order(store, campaign_id, seat, chosen.asks)
    except ValueError as refusal:
        return Reply(reply=str(refusal), refused=True)
    return Reply(reply=f"Filed: {chosen.label}.", refused=False)


__all__ = ["agenda", "pick_option", "seat_style", "set_style"]
