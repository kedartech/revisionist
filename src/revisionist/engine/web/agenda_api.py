"""The agenda on the web (Phase 4 unit S2): live mandates, offered options, the style,
and the requests another seat has put to this seat's person (ANS), each answered with
``answer``.

Options come from ``OptionsOffered``, produced at wake open by ``options.offer``.
Picking one files it through the ordinary order path, so it is what a free player
could have typed. A beginner is also offered the asks of the developments that just
fired; those are written as orders, never filed from the offer.
"""

import re
from collections.abc import Iterable
from datetime import date

from revisionist.core import events as ev
from revisionist.core import history, record
from revisionist.core.canary import scan_text
from revisionist.core.events import Event
from revisionist.core.ids import CampaignId, EntityId, MandateId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import advance, mandates, process
from revisionist.core.realism.agenda import Offer, Option, PlayStyle, TriggerKind
from revisionist.core.realism.effect import RoutedPart
from revisionist.core.state import State, View
from revisionist.core.visibility import private_to
from revisionist.engine import expects, options, realism_tick
from revisionist.engine.store import EventStore, load_state
from revisionist.engine.web.realism_api import (
    AgendaBlock,
    AgendaExpect,
    AgendaItem,
    AgendaOption,
    AgendaRisks,
    Reply,
)

_PICK = re.compile(r"w(\d+)\.o(\d+)\.p(\d+)")
_STALE = "That offer has lapsed. Look at what you are offered now."
_NEWS = re.compile(r"n\.[0-9A-Z]{26}\.\d")
_WRITE_IT = "Write it as an order to the person who should carry it out."
_GONE = "That request is no longer before you."
_ANSWERED = {  # [proposed]
    True: "You agree to {issuer}'s request. Your answer goes out when the wake closes.",
    False: "You decline {issuer}'s request. Your answer goes out when the wake closes.",
}


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


def _moves(found: expects.Targets, option: Option) -> list[AgendaExpect]:
    """The option's expected moves by name, less any whose target has left the view."""
    out: list[AgendaExpect] = []
    for move in option.expects:
        name = expects.name(found, move)
        if name is not None:
            out.append(
                AgendaExpect(
                    on=move.on.value,
                    name=name,
                    direction=move.direction.value,
                    size=move.size,
                    sure=move.sure.value,
                )
            )
    return out


def _shown(
    view: View,
    found: expects.Targets,
    option: Option,
    pick: str,
    taken: bool,
    label: str | None = None,
) -> AgendaOption:
    return AgendaOption(
        label=label or option.label,
        to=_name(view, option.to),
        risk=option.risk,
        historical=option.historical,
        pick=pick,
        taken=taken,
        expects=_moves(found, option),
        risks=None
        if option.risks is None
        else AgendaRisks(
            escalation=option.risks.escalation,
            refusal=option.risks.refusal,
            exposure=option.risks.exposure,
        ),
    )


def _listed(
    view: View,
    found: expects.Targets,
    made: ev.OptionsOffered,
    index: int,
    filed: list[tuple[RoutedPart, ...]],
) -> tuple[list[AgendaOption], bool]:
    """The offer's options for the client; a guided plan is its asks in order, every
    step carrying the plan's one token and one taken flag. The flag: whether it is a plan."""
    offer = made.offers[index]
    if offer.style is PlayStyle.GUIDED:
        plan = offer.options[0]
        pick = _token(made.wake, index, 0)
        taken = record.taken(plan.asks, filed)
        return [_shown(view, found, plan, pick, taken, a.ask) for a in plan.asks], True
    return [
        _shown(view, found, o, _token(made.wake, index, n), record.taken(o.asks, filed))
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


def _news_asks(view: View, events: list[Event]) -> list[AgendaOption]:
    """The asks of each public development that fired in the latest stretch (since the
    tick before the last closed), offered as ideas. Choosing one files nothing: the seat
    writes it as an order to whoever should carry it out."""
    closed = [i for i, e in enumerate(events) if e.kind == "tick_closed"]
    since = closed[-2] + 1 if len(closed) > 1 else 0
    fresh = {
        e.payload.scheduled_id
        for e in events[since:]
        if isinstance(e.payload, ev.ScheduledEventFired)
    }
    return [
        AgendaOption(
            label=text,
            to=None,
            risk=f"From the news: {s.headline or s.name}.",
            historical=False,
            pick=f"n.{s.scheduled_id}.{k}",
            taken=False,
            expects=[],
            risks=None,
        )
        for _, s in history.fired_developments(view)
        if s.scheduled_id in fresh
        for k, text in enumerate(s.asks)
    ]


def agenda(state: State, seat: SeatId, log: Iterable[Event]) -> AgendaBlock:
    """Each live mandate and the seat's offers from ``log``, all from its own view."""
    view = project(state, seat)
    events = list(log)
    made = _latest(events, seat, _wake(state))
    filed = _filed(events, seat, made.wake) if made is not None else []
    causes = _causes(state, seat, view)
    found = expects.targets(state, view)
    items: list[AgendaItem] = []
    initiative: list[AgendaOption] = []
    by_mandate: dict[MandateId | None, int] = {}
    if made is not None:
        by_mandate = {o.mandate_id: i for i, o in enumerate(made.offers)}
        if None in by_mandate:
            initiative = _listed(view, found, made, by_mandate[None], filed)[0]
    for mandate in options._live(view):
        listed: list[AgendaOption] = []
        plan = False
        if made is not None and mandate.mandate_id in by_mandate:
            listed, plan = _listed(view, found, made, by_mandate[mandate.mandate_id], filed)
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
    items += requests(state, seat)
    style = seat_style(state, seat)
    if style == PlayStyle.BEGINNER.value:
        initiative += _news_asks(view, events)
    return AgendaBlock(style=style, items=items, initiative=initiative)


def _asked(state: State, seat: SeatId) -> list[advance.Awaiting]:
    """The requests before ``seat`` today: another seat's asks at its person that have
    reached it and are not yet decided. Held decisions at a step are answered at the step."""
    today = state.in_world_date
    if today is None:
        return []
    return [a for a in advance.awaiting(state, seat, today) if a.part is not None]


def _item_id(state: State, asked: advance.Awaiting) -> str:
    """The request's opaque token: the id of the paper that brought it, which the
    holder already holds."""
    assert asked.part is not None
    return process.request_paper_id(state.campaign_id, asked.order_id, asked.part)


def requests(state: State, seat: SeatId) -> list[AgendaItem]:
    """Each request another seat has put to ``seat``'s person, as an agenda item: who
    asks, the words and terms, and the due day, after which the card decides. Words a
    canary would catch for this seat are withheld, as on the paper."""
    out: list[AgendaItem] = []
    for asked in _asked(state, seat):
        text = f"{asked.label} ({asked.terms})" if asked.terms else asked.label
        if scan_text(state, seat, text):
            text = process.WITHHELD
        out.append(
            AgendaItem(
                id=_item_id(state, asked),
                kind="Request",
                issuer=asked.issuer,
                text=text,
                issued=_day(asked.arrived),
                deadline=_day(asked.due),
                cause=None,
                options=[],
                plan=[],
            )
        )
    return out


def answer(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, item: str, accept: bool
) -> Reply:
    """The seat answers the request ``item`` names: an ``influence_decided`` dated today,
    seen by the issuer and the holder. Its effect lands at the next close."""
    state = load_state(store, campaign_id)
    today = state.in_world_date
    asked = next((a for a in _asked(state, seat) if _item_id(state, a) == item), None)
    if asked is None or asked.part is None or today is None:
        return Reply(reply=_GONE, refused=True)
    routed = state.routed[asked.order_id]
    decided = process.answered(state, routed, asked.part, accept, today)
    scope = private_to(routed.issuer).grant(seat)
    realism_tick._append(store, state, decided, seat, scope)
    return Reply(reply=_ANSWERED[accept].format(issuer=asked.issuer), refused=False)


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
    if _NEWS.fullmatch(pick):
        return Reply(reply=_WRITE_IT, refused=True)
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


__all__ = ["agenda", "answer", "pick_option", "requests", "seat_style", "set_style"]
