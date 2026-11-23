"""The agenda on the web (Phase 4 unit S2): live mandates, offered options, the style,
and the requests another seat has put to this seat's person (ANS), each answered with
``answer``. ``due_matters`` is the one list of what waits on a seat, which the wake
notice reads (DMN).

Options come from ``OptionsOffered``, produced at wake open by ``options.offer``.
Picking one files it through the ordinary order path, so it is what a free player
could have typed. A beginner is also offered the asks of the developments that just
fired; those are written as orders, never filed from the offer.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

from revisionist.core import events as ev
from revisionist.core import history, record
from revisionist.core.canary import scan_text
from revisionist.core.events import Event
from revisionist.core.ids import CampaignId, EntityId, MandateId, OrderId, SeatId, derived_id
from revisionist.core.ontology import Controller
from revisionist.core.project import project
from revisionist.core.realism import advance, agreement, holders, mandates, pipelines, process
from revisionist.core.realism.agenda import Offer, Option, PlayStyle, TriggerKind
from revisionist.core.realism.effect import Forecast, RoutedPart
from revisionist.core.realism.pipeline import StepAction
from revisionist.core.state import State, View
from revisionist.core.visibility import private_to
from revisionist.engine import expects, options, realism_tick
from revisionist.engine.store import EventStore, load_state
from revisionist.engine.web import agreements_api, battles_api, conferences_api, forecast
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
HELD_STEP = "Decision"  # [proposed] the kind of a held step on its holder's agenda
OFFER_KIND = "Offer"  # [proposed] plan, AGA Defaults: an offer of agreement on the agenda
_GIVEN = {True: "You have agreed to it.", False: "You have declined it."}  # [proposed]
"""A request's line on its holder's agenda once they have answered it."""
_CHOSEN = "You have chosen to {action}."  # [proposed]
"""A held decision's line on its holder's agenda once they have chosen."""
_ANSWERED = {  # [proposed]
    True: "You agree to {issuer}'s request. Your answer goes out on the day it is due.",
    False: "You decline {issuer}'s request. Your answer goes out on the day it is due.",
}
_ANSWERED_OFFER = {  # [proposed]
    True: "You accept {issuer}'s offer. Your answer counts on the day the offer is due.",
    False: "You decline {issuer}'s offer. Your answer counts on the day the offer is due.",
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
    """Each live mandate and the seat's offers from ``log``, all from its own view, and
    the seat's own forecasts, checked (``forecast.block``)."""
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
                actions=[],
            )
        )
    items += requests(state, seat)
    items += offers(state, seat)
    items += held_steps(state, seat)
    items += conferences_api.items(state, seat)
    style = seat_style(state, seat)
    if style == PlayStyle.BEGINNER.value:
        initiative += _news_asks(view, events)
    return AgendaBlock(
        style=style,
        items=items,
        initiative=initiative,
        forecast=forecast.block(state, seat, events),
    )


def _awaiting(state: State, seat: SeatId) -> list[advance.Awaiting]:
    """What another seat has put before ``seat`` today, reached and not yet decided."""
    today = state.in_world_date
    return [] if today is None else advance.awaiting(state, seat, today)


def _asked(state: State, seat: SeatId) -> list[advance.Awaiting]:
    """The requests before ``seat`` today: another seat's asks at its person that have
    reached it and are not yet decided. Held decisions at a step are ``held_steps``."""
    return [a for a in _awaiting(state, seat) if a.part is not None]


def _item_id(state: State, asked: advance.Awaiting) -> str:
    """The request's opaque token: the id of the paper that brought it, which the
    holder already holds."""
    assert asked.part is not None
    return process.request_paper_id(state.campaign_id, asked.order_id, asked.part)


def _is_offer(state: State, asked: advance.Awaiting) -> bool:
    """Whether ``asked`` is one nation's share of an offer of agreement (AGR)."""
    assert asked.part is not None
    return agreement.is_offer(state.routed[asked.order_id].parts[asked.part])


def requests(state: State, seat: SeatId) -> list[AgendaItem]:
    """Each request another seat has put to ``seat``'s person, as an agenda item of kind
    "Request", answered with ``answer``. An offer of agreement is an "Offer" instead."""
    return [
        _awaiting_item(state, seat, asked, "Request", _item_id(state, asked))
        for asked in _asked(state, seat)
        if not _is_offer(state, asked)
    ]


def offers(state: State, seat: SeatId) -> list[AgendaItem]:
    """Each offer of agreement before ``seat``'s nation, as an agenda item of kind
    "Offer" (AGA): who offers, the terms as ``agreement.render_terms`` gives them (a clause
    the rules do not check says so), and the offer's due day, its expiry. The ``agreements``
    block carries the same terms clause by clause under the item's id. Answered with
    ``answer``, which keeps the answer sealed to the seat until that day."""
    out: list[AgendaItem] = []
    for asked in _asked(state, seat):
        if not _is_offer(state, asked):
            continue
        assert asked.part is not None
        part = state.routed[asked.order_id].parts[asked.part]
        offer = agreements_api.offer_of(state, asked.order_id, part.effect)
        if offer is None:
            continue
        item = _awaiting_item(state, seat, asked, OFFER_KIND, _item_id(state, asked))
        text = f"{asked.label} {agreement.render_terms(state, offer)}"
        item["text"] = process.WITHHELD if scan_text(state, seat, text) else text
        out.append(item)
    return out


def _step_actions(state: State, order_id: OrderId) -> list[str]:
    """What a human may do at the step ``order_id`` waits at: what the step allows the
    seat (pass and stall only on an order from up its chain), without ``amend`` (the room
    has no terms editor), in ``StepAction`` order."""
    allowed = pipelines.step_allowed(state, state.orders[order_id])
    return [a.value for a in StepAction if a in allowed and a is not StepAction.AMEND]


def _taken_up(state: State, seat: SeatId) -> bool:
    """A new player has taken up ``seat``'s person, from the next close. The answers and
    step choices the last player kept are not theirs, so their agenda shows none; the
    close clears them."""
    held = state.seats.get(seat)
    return held is not None and state.handovers.get(held.embodies) is Controller.HUMAN


def _awaiting_item(
    state: State, seat: SeatId, asked: advance.Awaiting, kind: str, item_id: str
) -> AgendaItem:
    """One thing another seat put before ``seat``, as an agenda item: who asks, the words
    and terms, and the due day, after which the card decides. Words a canary would catch
    for this seat are withheld, as on the paper."""
    text = f"{asked.label} ({asked.terms})" if asked.terms else asked.label
    if scan_text(state, seat, text):
        text = process.WITHHELD
    cause = None
    actions: list[str] = []
    kept = not _taken_up(state, seat)
    if asked.part is not None:
        given = state.routed[asked.order_id].parts[asked.part].held_answer
        cause = None if given is None or not kept else _GIVEN[given]
    else:
        order = state.orders[asked.order_id]
        chosen = order.held_choice
        if chosen is not None and chosen.step == order.step and kept:
            cause = _CHOSEN.format(action=chosen.action.value)
        actions = _step_actions(state, asked.order_id)
    return AgendaItem(
        id=item_id,
        kind=kind,
        issuer=asked.issuer,
        text=text,
        issued=_day(asked.arrived),
        deadline=_day(asked.due),
        cause=cause,
        options=[],
        plan=[],
        actions=actions,
    )


def held_steps(state: State, seat: SeatId) -> list[AgendaItem]:
    """Each decision step ``seat``'s person holds on another seat's order, as an agenda
    item of kind "Decision". Its id is the paper that brought it, which the ``step``
    action takes in place of an order id; the order id itself never leaves the engine."""
    return [
        _awaiting_item(
            state,
            seat,
            held,
            HELD_STEP,
            pipelines.held_paper_id(
                state.campaign_id, held.order_id, state.orders[held.order_id].step
            ),
        )
        for held in _awaiting(state, seat)
        if held.part is None
    ]


def answer(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, item: str, accept: bool
) -> Reply:
    """The seat answers the request or offer of agreement ``item`` names: a
    ``request_answered`` sealed to the seat, so nothing the issuer reads moves. The seat
    sees it on its agenda and may give it again; on the due day it decides the request in
    the card's place, and an offer by AGR's rule."""
    state = load_state(store, campaign_id)
    asked = next((a for a in _asked(state, seat) if _item_id(state, a) == item), None)
    if asked is None or asked.part is None:
        return Reply(reply=_GONE, refused=True)
    given = process.answered(state, state.routed[asked.order_id], asked.part, accept)
    realism_tick._append(store, state, given, seat, private_to(seat))
    said = _ANSWERED_OFFER if _is_offer(state, asked) else _ANSWERED
    return Reply(reply=said[accept].format(issuer=asked.issuer), refused=False)


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


def offered(store: EventStore, campaign_id: CampaignId, seat: SeatId, pick: str) -> Option:
    """The option ``pick`` names among the seat's offers for the open wake. Raises
    ``ValueError`` with the player's words when it names none."""
    if _NEWS.fullmatch(pick):
        raise ValueError(_WRITE_IT)
    state = load_state(store, campaign_id)
    found = _PICK.fullmatch(pick)
    made = _latest(store.read(campaign_id), seat, _wake(state))
    if found is None or made is None or int(found[1]) != made.wake:
        raise ValueError(_STALE)
    index, n = int(found[2]), int(found[3])
    if index >= len(made.offers):
        raise ValueError(_STALE)
    offer: Offer = made.offers[index]
    if n >= len(offer.options):
        raise ValueError(_STALE)
    return offer.options[n]


def told(option: Option) -> Forecast:
    """What the staff told the seat about ``option``: its expected moves and risks, the
    forecast the order it files carries (FCK rule 1)."""
    return Forecast(expects=option.expects, risks=option.risks)


def pick_option(store: EventStore, campaign_id: CampaignId, seat: SeatId, pick: str) -> Reply:
    """File the offered option ``pick`` names with ``realism_tick.commit_order``, with
    the option's expected moves and risks as the order's forecast (FCK rule 1)."""
    try:
        chosen = offered(store, campaign_id, seat, pick)
    except ValueError as stale:
        return Reply(reply=str(stale), refused=True)
    try:
        realism_tick.commit_order(store, campaign_id, seat, chosen.asks, told(chosen))
    except ValueError as refusal:
        return Reply(reply=str(refusal), refused=True)
    return Reply(reply=f"Filed: {chosen.label}.", refused=False)


# --- what waits on a seat (DMN) --------------------------------------------------

AT_CLOSE = "at this wake's close"  # [proposed]
"""The due day of a matter that is decided when the open wake closes."""


@dataclass(frozen=True)
class DueMatter:
    """One thing that waits on a seat, as its notice lists it: what it is, who it is
    from, and when it falls due. ``kind`` and ``subject`` name it, so a matter reached
    by two paths is listed once; ``subject`` is an id the seat already holds."""

    kind: str
    subject: str
    what: str
    issuer: str | None
    due: str


DueKind = Callable[[State, SeatId], list[DueMatter]]
"""A kind of due matter: the lines of that kind waiting on a seat, built only from what
that seat may see, and never a sealed choice (an answer or decision kept before its due
day, a filed vote) or any mark of the aide."""


def _due_items(kind: str, items: list[AgendaItem]) -> list[DueMatter]:
    """Agenda items as due matters: the words, who asks and the due day. The item's
    ``cause`` (the seat's own answer or choice, sealed until its due day) is left out."""
    return [DueMatter(kind, i["id"], i["text"], i["issuer"], i["deadline"]) for i in items]


def _due_requests(state: State, seat: SeatId) -> list[DueMatter]:
    return _due_items("request", requests(state, seat))


def _due_offers(state: State, seat: SeatId) -> list[DueMatter]:
    """Each offer of agreement before the seat (AGA), once: the request line skips it."""
    return _due_items("offer", offers(state, seat))


def _due_decisions(state: State, seat: SeatId) -> list[DueMatter]:
    return _due_items("decision", held_steps(state, seat))


def _due_capitals(state: State, seat: SeatId) -> list[DueMatter]:
    """Each territory of the seat's polity marked to fall at this wake's close (THL),
    named by the paper that warned the seat. A seat that does not hold that paper is
    told nothing: the mark itself is engine only."""
    falling = holders.falling(state, seat)
    if not falling:
        return []
    view = project(state, seat)
    out: list[DueMatter] = []
    for area, marked_on in falling:
        doc_id = holders.paper_id(state, area, marked_on, seat)
        page = view.documents.get(doc_id)
        if page is None:
            continue
        out.append(DueMatter("capital", doc_id, page.title, _name(view, page.author), AT_CLOSE))
    return out


def _due_battles(state: State, seat: SeatId) -> list[DueMatter]:
    """Each battle that waits on the seat's decision in the open wake (BTD), named by its
    opening news. One decided this wake, by an order landed or still on its way, is not
    listed, and no line says what was decided."""
    return [
        DueMatter("battle", subject, what, None, AT_CLOSE)
        for subject, what in battles_api.due(state, seat)
    ]


def _due_votes(state: State, seat: SeatId) -> list[DueMatter]:
    """Each conference the seat's nation votes in, due on its voting day (CNA): never the
    vote the seat has sealed, nor what the aide would vote."""
    return _due_items("vote", conferences_api.items(state, seat))


def _due_asks(state: State, seat: SeatId) -> list[DueMatter]:
    """Each ask put before the seat for another seat's held order (LKD rule 4): the
    order's words and the asker, read from its own view. No clock ends an ask."""
    from revisionist.engine.web import locks_api

    found = locks_api.block(state, seat)
    asks = found["asks"] if found is not None else []
    return [DueMatter("ask", a["id"], a["words"], a["by"], locks_api.ASK_DUE) for a in asks]


PROMISE = "Your promise to {bloc}: {sentence}"  # [proposed]


def _due_promises(state: State, seat: SeatId) -> list[DueMatter]:
    """Each promise the seat made whose measure has passed, due on the day it is read
    (PRR rule 5), from the seat's own view: only its own offers."""
    from revisionist.engine.web import home_api

    return [
        DueMatter(
            "promise",
            p["offer_id"],
            PROMISE.format(bloc=p["name"], sentence=p["sentence"].rstrip(".")),
            None,
            p["due"],
        )
        for p in home_api.promises(project(state, seat))
        if p["standing"] == "due" and p["due"] is not None
    ]


DUE_KINDS: dict[str, DueKind] = {
    "request": _due_requests,
    "offer": _due_offers,
    "decision": _due_decisions,
    "capital": _due_capitals,
    "battle": _due_battles,
    "vote": _due_votes,
    "ask": _due_asks,
    "promise": _due_promises,
}
"""The registry of due kinds, in the order a notice lists them."""


def due_matters(state: State, seat: SeatId) -> list[DueMatter]:
    """Everything that waits on ``seat`` now: each registered kind's lines in registry
    order, a matter reached by two paths listed once (by kind and subject). Built from
    the state alone, so it reads the same whether any other seat is present or away."""
    seen: set[tuple[str, str]] = set()
    out: list[DueMatter] = []
    for kind in DUE_KINDS.values():
        for matter in kind(state, seat):
            key = (matter.kind, matter.subject)
            if key not in seen:
                seen.add(key)
                out.append(matter)
    return out


__all__ = [
    "AT_CLOSE",
    "DUE_KINDS",
    "OFFER_KIND",
    "DueKind",
    "DueMatter",
    "agenda",
    "answer",
    "due_matters",
    "offered",
    "offers",
    "pick_option",
    "requests",
    "seat_style",
    "set_style",
    "told",
]
