"""Catch-up: the events a seat's view holds, wake by wake (the catch-up seam).

``seat_events`` is the one fog path every feed reads: the ``catchup`` action's pages
now, the second run's playback later. An event is kept only if all three hold:

1. its scope, and every scope nested in its payload, is visible to the seat, and what
   it names is in ``project(state, seat)``: an order, a goal, a contest, a mandate or a
   history event another seat holds is never in the feed, whatever the envelope says;
2. its kind is in ``FEED_KINDS``;
3. for a document, it has arrived (``arrives`` on or before today's in-world date).

The feed carries nothing the seat's own papers have not: news reaches a seat only as
its press paper, so ``news_reported`` is never fed; a routed order is fed as its
issuer's view (``RoutedOrderView``'s fields), never the engine's ``ask``, estimate or
held answer.

Every kind in ``events.Payload`` is in exactly one of ``FEED_KINDS`` or ``NEVER``; a
test fails on a kind in neither, so a new event kind must be classified here.

Each event belongs to the wake whose record page shows it (``core/record.py``): wake N
covers the in-world days after wake N-1 opened, up to the day wake N opened. A document
belongs to the wake in which it arrives; any other event to the later of the wake open
when it was logged and the wake that holds its day. A document's truth half never
leaves: the feed carries its view only, and a routed order's engine-side fields go
the same way.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.ids import CampaignId, DocumentId, OrderId, SeatId
from revisionist.core.project import project, untold_goals
from revisionist.core.realism import answering
from revisionist.core.realism.document import DocumentTruth
from revisionist.core.realism.effect import RoutedOrder
from revisionist.core.sealing import scopes_in
from revisionist.core.state import State, View
from revisionist.engine.store import EventStore, load_state

FEED_KINDS: frozenset[str] = frozenset(
    {
        # The world as every view holds it.
        "entity_created",
        "asset_created",
        "relationship_set",
        "meter_created",
        "clock_created",
        "fact_asserted",
        "commitment_created",
        "contest_created",
        "contest_moved",
        "contest_decided",
        "scheduled_event_fired",
        "divergence_changed",
        "date_advanced",
        "war_declared",
        "war_ended",
        "map_declared",
        "kinds_declared",
        # Which orders need whose decision (DCD): public rules of the world.
        "locks_declared",
        # The laws a world declares (LWC): public rules of the world.
        "laws_declared",
        # The aim patterns a world declares (OWC): public rules of the world.
        "aim_patterns_declared",
        # A player's own aim (OWC): sealed to the seat holding the person, and kept only
        # while that seat's view holds it.
        "own_aim_set",
        # A seat's own nation's pieces, step by step (sealed to its seats): playback's source.
        "piece_stepped",
        # A move of its own nation's group (sealed to its seats, HFR): its home block shows
        # it already; playback's source for the home front.
        "group_moved",
        # A step of its own nation's piece refused for want of fuel, with the reason (FUL).
        "step_refused",
        # Who holds each territory, as it changes (THL): public.
        "area_held",
        "season_ended",
        "quantity_set",
        "wake_opened",
        # The seat's own goals, mandates, papers and orders.
        "goal_set",
        "goal_progressed",
        "goal_met",
        "goal_undone",
        "mandate_issued",
        "mandate_settled",
        "document_issued",
        "document_written",
        "narration_written",
        "statement_issued",
        "briefing_delivered",
        "order_drafted",
        "order_step_taken",
        "order_settled",
        "order_routed",
        "order_executed",
        # A held order and its end (LCK): sealed to the issuer's seat, and kept only while
        # the order is the seat's own.
        "order_held",
        "held_order_ended",
        # An ask for a held order (ASK): sealed to the asker and the seat asked.
        "order_asked",
        # The answer to an ask (AAK, QKD): sealed to the asker's seat alone, and fed only on
        # a row answered on its due day whoever holds the decider (``answering.told``).
        "ask_answered",
        # An order sent anyway (DFY): sealed to the issuer's seat alone.
        "order_defied",
        # An incident and its answer (DFY): sealed to the commander's seat and the
        # superior's, and fed to both.
        "incident_opened",
        "incident_answered",
        # An offer of a price to a bloc and where it stands (PRC): sealed to the seats of
        # the bloc's nation, and kept only while the offer is in the seat's view.
        "offer_made",
        "offer_settled",
        # A post changing hands (PPP): public, as an appointment is news; never its part.
        "post_changed",
        # Who may move a post and where its holder falls (LDR): public rules of the world.
        "ladders_declared",
        # The pending change of post (LDR): sealed to the seat of the person moved alone.
        "post_move_ordered",
        "post_move_settled",
        # An office question (OFQ): its opening sealed to every seat of the holder's
        # nation, whoever plays it; its decision public, as news.
        "office_question_opened",
        "office_question_decided",
        "seats_redrawn",
        "influence_decided",
        "effects_applied",
        # Offers and agreements (AGR): sealed to the parties' seats, public once published,
        # and kept only when the agreement is in the seat's view.
        "agreement_offered",
        "agreement_made",
        "clause_judged",
        "agreement_published",
        # A conference's call and tally (CNF): sealed to the invited seats, or public, and
        # kept only when the conference is in the seat's view.
        "conference_called",
        "conference_tallied",
    }
)

NEVER: frozenset[str] = frozenset(
    {
        # Who sealed the wake, how it closed, and who the aide played (invariant 5).
        "wake_committed",
        "wake_closed",
        # How a seat is run is never shown (spec section 17; decision A).
        "seat_handover",
        # A holder's answer is theirs until the due day decides with it; the seat that
        # asked reads only that decision (ANS).
        "request_answered",
        # A seat's sealed vote is its own until the tally counts its nation (CNF).
        "vote_sealed",
        # A seat's choice on a matter is its own until the due day counts it, and the
        # asker reads only the answer (QKD).
        "matter_chosen",
        # A member's sealed choice on an office question is his until the sitting counts
        # it, and nobody reads who chose what (OFQ).
        "office_choice_filed",
        # A holder's choice at a step on another seat's order is theirs until the
        # step's held due day takes it (SHS).
        "step_chosen",
        "seat_created",
        "agent_assigned",
        "seat_status_set",
        "session_zero_opened",
        "character_listed",
        "character_claimed",
        "character_released",
        "session_zero_closed",
        "play_style_set",
        # The structured news item: ``State.news`` is engine-only, and a seat learns the
        # news from its press paper when that arrives (``press.py``), which is fed.
        "news_reported",
        # Engine only: the estimator's effects, policy, truth and the people's plans.
        "effects_estimated",
        "cards_declared",
        "card_amended",
        "stance_changed",
        "opponents_ranked",
        "answer_planned",
        "answer_made",
        "feature_set",
        # A territory's capture count and capital mark: where pieces stand (THL). The
        # holder's seats learn of a mark from its paper.
        "capture_counted",
        # A nation's pools and a moved yield: true figures (YLD). A seat reads its own
        # economy from its own data and learns of damage from its papers.
        "economy_set",
        "yield_changed",
        # A trade line opened or cut: true figures (FUL). A seat learns of a cut line from
        # the news paper, and from the paper to the nation it hits.
        "trade_set",
        # A battle's opening, rounds and end: both sides' true strengths and the draws (BTL).
        # A seat learns of a battle from the news and its commanders' reports, which are fed.
        "battle_opened",
        "battle_round",
        "battle_ended",
        # A side's decision and the pieces that join it (BDC): the decision is the seat's
        # own order, already fed; a join carries the true strength brought.
        "battle_decided",
        # Detection (DET): engine only. A report names the true piece and whether it is
        # wrong; the seat gets it as a line of its source's page and in its own reports.
        "intelligence_declared",
        "report_made",
        # Intelligence orders (IOR): engine only. Where a nation has agents and its
        # codebreaking level; the holder learns of a caught agent from its paper.
        "agent_set",
        "codebreaking_set",
        # Groups at home (GRP): true support. A seat reads its own nation's groups from its
        # own data and others' from the press; the declaration, the writing in waiting and
        # the battle losses held (LSS) are engine only. A move is fed (HFR).
        "groups_declared",
        "group_proposed",
        "losses_held",
        "scheduled_event_created",
        "scheduled_event_skipped",
        # Costs, ticks and admin.
        "cost_logged",
        "tick_opened",
        "tick_stage_completed",
        "tick_closed",
        "admin_read",
        "campaign_created",
        "settings_set",
        # The first engine's pipeline, whose deltas can carry covert facts under a
        # public envelope.
        "order_received",
        "intent_filed",
        "intent_rejected",
        "clarification_asked",
        "feasibility_rated",
        "rolled",
        "delta_proposed",
        "delta_rejected",
        "delta_applied",
        "operation_opened",
        "operation_resolved",
        # The seat's own acts as records: they change nothing the world holds.
        "document_read",
        "document_flagged",
        "goal_proposed",
        "goal_approved",
        "counsel_held",
        "directive_given",
        "options_offered",
        # A sealed event whose key is gone stays unreadable.
        "sealed",
    }
)


GOAL_NEWS = (ev.GoalProgressed, ev.GoalMet, ev.GoalUndone)
"""The news of a goal: none is told of one in ``untold_goals``."""


@dataclass(frozen=True)
class SeatEvent:
    wake: int
    event: Event


def _named(p: ev.Payload, view: View) -> bool:
    """What the event names is in the seat's view. Several kinds land under a public
    envelope while what they name is the issuer's or the owner's alone."""
    match p:
        case ev.OrderDrafted():
            return p.order.order_id in view.orders
        case ev.OrderStepTaken() | ev.OrderSettled():
            return p.order_id in view.orders
        case ev.OrderRouted():
            return p.order.order_id in view.routed
        case ev.OrderHeld():
            return p.held.issuer == view.viewer
        case ev.HeldOrderEnded():
            return p.issuer == view.viewer
        case ev.OrderAsked():
            return view.viewer in (p.asked.asker, p.asked.seat, *p.asked.seats)
        case ev.OrderDefied():
            return p.defied.issuer == view.viewer
        case ev.IncidentOpened():
            return view.viewer in p.incident.seats
        case ev.IncidentAnswered():
            return view.viewer in p.seats
        case ev.AskAnswered():
            return p.asker == view.viewer
        case ev.OfferMade():
            return any(o.offer_id == p.offer.offer_id for o in view.offers)
        case ev.OfferSettled():
            return any(o.offer_id == p.offer_id for o in view.offers)
        case ev.OrderExecuted() | ev.EffectsApplied() | ev.InfluenceDecided():
            return p.order_id in view.routed
        case ev.GoalProgressed() | ev.GoalMet() | ev.GoalUndone():
            return p.goal_id in view.goals
        case ev.OwnAimSet():
            return p.own.person in view.own_aims
        case ev.PostChanged():
            return p.post in view.assets
        case ev.ContestMoved() | ev.ContestDecided():
            return p.contest_id in view.contests
        case ev.ScheduledEventFired():
            return p.scheduled_id in view.scheduled
        case ev.MandateSettled():
            return p.mandate_id in view.mandates
        case ev.QuantitySet():
            return p.quantity.quantity_id in view.quantities
        case ev.NarrationWritten() | ev.BriefingDelivered():
            return p.seat_id == view.viewer
        case ev.AgreementOffered():
            return p.offer.offer_id in view.agreements.offers
        case ev.AgreementMade():
            return p.agreement.agreement_id in view.agreements.made
        case ev.ClauseJudged() | ev.AgreementPublished():
            return p.agreement_id in view.agreements.made
        case ev.ConferenceCalled():
            return p.conference.key in view.conferences.held
        case ev.ConferenceTallied():
            return p.conference in view.conferences.held
        case ev.GroupMoved():
            return p.polity in view.groups.declared  # a view holds its own nation's only
    return True


def _visible(event: Event, view: View) -> bool:
    scopes = [event.scope, *scopes_in(event.payload)]
    return all(s.visible_to(view.viewer) for s in scopes) and _named(event.payload, view)


def _wake_of_day(opened: Sequence[tuple[int, date]], day: date | None) -> int:
    """The wake whose page holds ``day``: the first opened on or after it."""
    if day is None:
        return 0
    for number, on in opened:
        if day <= on:
            return number
    return opened[-1][0] + 1 if opened else 0


def _view_only(event: Event, payload: ev.DocumentIssued) -> Event:
    blank = DocumentTruth(doc_id=payload.document.doc_id)
    return event.model_copy(update={"payload": payload.model_copy(update={"truth": blank})})


def _routed_view(event: Event, payload: ev.OrderRouted) -> Event:
    """The order as its issuer knows it: ``RoutedOrderView``'s fields, with the engine's
    ``ask``, ``estimated``, ``was_estimated`` and ``held_answer`` at their defaults. The
    payload stays an ``OrderRouted`` so the event keeps its type and serialises cleanly."""
    order = RoutedOrder.model_validate(payload.order.view().model_dump())
    return event.model_copy(update={"payload": payload.model_copy(update={"order": order})})


def _as_asked(state: State, event: Event, payload: ev.OrderAsked, seat: SeatId) -> Event:
    asked = answering.as_asked(state, payload.asked, seat)
    return event.model_copy(update={"payload": payload.model_copy(update={"asked": asked})})


def feed(
    state: State, events: Iterable[Event], seat: SeatId, first: int, last: int
) -> tuple[SeatEvent, ...]:
    """``seat_events`` over a log already read, ``state`` being its fold."""
    view = project(state, seat)
    untold = untold_goals(state, seat)
    log = list(events)
    opened: list[tuple[int, date]] = []
    rows: dict[OrderId, str | None] = {}
    today: date | None = None
    for e in log:
        if isinstance(e.payload, ev.DateAdvanced):
            today = e.payload.to
        elif isinstance(e.payload, ev.WakeOpened) and today is not None:
            opened.append((e.payload.wake, today))
        elif isinstance(e.payload, ev.OrderHeld):
            rows[e.payload.held.order_id] = e.payload.held.row
    final = state.in_world_date

    out: list[SeatEvent] = []
    arrived: dict[DocumentId, int] = {}
    current = 0
    today = None
    for e in log:
        p = e.payload
        if isinstance(p, ev.DateAdvanced):
            today = p.to
        elif isinstance(p, ev.WakeOpened):
            current = p.wake
        if e.kind not in FEED_KINDS or not _visible(e, view):
            continue
        if isinstance(p, GOAL_NEWS) and p.goal_id in untold:
            continue
        if isinstance(p, ev.AskAnswered) and not answering.told(state, rows.get(p.order_id)):
            continue
        if isinstance(p, ev.DocumentIssued):
            if final is None or p.document.arrives > final:
                continue
            wake = arrived[p.document.doc_id] = _wake_of_day(opened, p.document.arrives)
            e = _view_only(e, p)
        elif isinstance(p, ev.OrderRouted):
            e = _routed_view(e, p)
            wake = max(current, _wake_of_day(opened, today))
        elif isinstance(p, ev.OrderAsked):
            e = _as_asked(state, e, p, seat)
            wake = max(current, _wake_of_day(opened, today))
        elif isinstance(p, ev.DocumentWritten):
            if p.doc_id not in arrived:
                continue
            wake = max(current, arrived[p.doc_id])
        else:
            wake = max(current, _wake_of_day(opened, today))
        if first <= wake <= last:
            out.append(SeatEvent(wake=wake, event=e))
    return tuple(sorted(out, key=lambda f: (f.wake, f.event.seq)))


def seat_events(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, first: int, last: int
) -> tuple[SeatEvent, ...]:
    """The events ``seat``'s view holds for wakes ``first..last`` inclusive, in order."""
    state = load_state(store, campaign_id)
    return feed(state, store.read(campaign_id, 0), seat, first, last)


__all__ = ["FEED_KINDS", "NEVER", "SeatEvent", "feed", "seat_events"]
