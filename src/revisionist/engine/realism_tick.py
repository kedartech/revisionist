"""The realism tick (plan, Phase 2 unit 2f): the event-driven advance, end to end.

Code walks the world from one wake to the next in stages, each landed in the log
as one atomic batch ending in ``tick_stage_completed``:

    ESTIMATE   engine v2: one estimator call per routed part no code rule covers,
               each landed as its own batch, so a resumed tick never calls twice
    ADVANCE    the opening in-tray (first tick only), then ``date_advanced`` to the wake
    PIPELINES  day by day: orders move, history fires or skips, commands are carried
               out, processes open, influence is decided, parts apply, resolvers
               compute, feeds issue, then mandates settle and issue
    RESOLVE    goal changes, each private to the goal's owner
    FEEDS      any document still owed on the new today (the walk issues each feed
               on the day it falls due, so it waits in the in-tray until read)
    PROSE      one prose call per author for the pages issued since the last tick
               closed, from the pages and the author's voice only (Phase 4)

Resuming reads the tail of the log and continues from the first stage not marked
complete, so a resumed run reaches the hash an uninterrupted one would. ESTIMATE
runs only when the caller passes an estimator, so a tick without one logs what it
always did; PROSE runs only when the caller passes a writer; a page whose prose is
refused or whose call fails keeps its body lines, and the tick still closes. Delivery comes later;
``TickResult.delivered`` is empty.
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from revisionist.core import aim_patterns, goals, history
from revisionist.core import events as ev
from revisionist.core._base import Model
from revisionist.core.events import CallCost, Event, Versions
from revisionist.core.fold import FoldError, replay, state_hash
from revisionist.core.ids import (
    AssetId,
    CampaignId,
    DocumentId,
    EntityId,
    EventId,
    FeatureId,
    OrderId,
    SeatId,
    derived_id,
)
from revisionist.core.ontology import Phase
from revisionist.core.project import project
from revisionist.core.realism import (
    actors,
    agreement,
    answering,
    apply,
    battle,
    conference,
    contests,
    detect,
    economy,
    groups,
    holders,
    locks,
    mandates,
    offers,
    opponents,
    posts,
    process,
)
from revisionist.core.realism.advance import Wake, next_wake
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.arrivals import arrivals
from revisionist.core.realism.card import Lever, ParamKind, ParamSpec, ParamValue, PostCause
from revisionist.core.realism.document import DocumentView, Feed
from revisionist.core.realism.effect import (
    Deal,
    Effect,
    Forecast,
    PartRef,
    Route,
    RoutedOrder,
    RoutedPart,
)
from revisionist.core.realism.feeds import due_feeds, issue, seed_for_day
from revisionist.core.realism.geography import in_play
from revisionist.core.realism.pipeline import SETTLED, Order, OrderStatus, StepAction
from revisionist.core.realism.pipelines import (
    checked_step,
    destination,
    held_by_another,
    held_paper_id,
    human_step,
    place_named,
    run_pipelines,
    waiting_on_human,
)
from revisionist.core.realism.press import news_pages
from revisionist.core.realism.resolvers import (
    ON_DAY,
    ON_ORDER,
    apply_changes,
    movement,
    resolver_for,
)
from revisionist.core.realism.resolvers.movement import FORCE, STRENGTH
from revisionist.core.realism.route import NOBODY, due_executions, held, route
from revisionist.core.realism.war import polity_of
from revisionist.core.realism.war_rules import contacts, order_refusal
from revisionist.core.resolution import TickStage
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, Scope, Visibility, private_to
from revisionist.core.world_compile import card_policy, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import season, session_zero
from revisionist.engine.emit import Emitter, tail
from revisionist.engine.estimate import aide_orders, estimate, reads_groups
from revisionist.engine.ids import new_id
from revisionist.engine.llm import Transport, TransportError
from revisionist.engine.prose import ProseWriter, accepted, author_of, prose_prompt_version
from revisionist.engine.store import EventStore, load_state
from revisionist.engine.tick import NotInPlayError, TickResult

log = logging.getLogger(__name__)


class RealismTickResult(TickResult):
    wake: Wake | None = None
    """Where the advance stopped. None when a resumed tick passed ADVANCE in an earlier run."""
    written: int = 0
    """Pages given prose in this run."""
    prose_dropped: tuple[str, ...] = ()
    """``doc_id: reason`` for pages left without prose in this run."""


class OpeningWritten(Model):
    written: int = 0
    """Opening pages given prose at the begin."""
    prose_dropped: tuple[str, ...] = ()
    """``doc_id: reason`` for opening pages left to the first tick's PROSE stage."""


def _opening_date(events: Sequence[Event]) -> date | None:
    """The in-world date when the tick in progress opened: the last ``date_advanced``
    before its ``tick_opened``."""
    start, opened = 0, len(events)
    for i, e in enumerate(events):
        if e.kind == "tick_closed":
            start = i + 1
    for i in range(start, len(events)):
        if events[i].kind == "tick_opened":
            opened = i
            break
    found: date | None = None
    for e in events[:opened]:
        if isinstance(e.payload, ev.DateAdvanced):
            found = e.payload.to
    return found


def _unresolved(events: Sequence[Event]) -> list[OrderId]:
    """Orders enacted since the last PIPELINES stage closed: a human's final step,
    filed between ticks, whose resolver has not run.

    ``take_step`` now resolves the order in the step's own batch and marks that
    batch with the issuer as actor, so only a settlement without an actor (a log
    written before that) is left for the tick to resolve."""
    after = 0
    for i, e in enumerate(events):
        p = e.payload
        if isinstance(p, ev.TickStageCompleted) and p.stage is TickStage.PIPELINES:
            after = i + 1
    return [
        e.payload.order_id
        for e in events[after:]
        if isinstance(e.payload, ev.OrderSettled)
        and e.payload.status is OrderStatus.ENACTED
        and e.actor is None
    ]


def run_realism_tick(
    store: EventStore,
    campaign_id: CampaignId,
    *,
    versions: Versions | None = None,
    stop_after: TickStage | None = None,
    prose: ProseWriter | None = None,
    estimator: Transport | None = None,
) -> RealismTickResult:
    """Run (or resume) one realism tick. Safe to call again after a crash at any point.

    ``prose`` writes the pages; with none, the tick has no PROSE stage. ``estimator``
    rules on parts no code rule covers; with none, the tick has no ESTIMATE stage."""
    versions = versions or cmp.versions()
    state = load_state(store, campaign_id)
    if state.phase is not Phase.PLAY:
        raise NotInPlayError(state.phase)
    events = list(store.read(campaign_id))
    log_tail = tail(events)
    em = Emitter(store, state, versions)
    done = set(log_tail.completed)
    result = RealismTickResult(
        tick=state.tick, resumed_from=log_tail.completed[-1] if log_tail.completed else None
    )
    today = state.in_world_date
    if state.ruleset != "realism" or today is None:
        raise ValueError("run_realism_tick needs a realism campaign with an in-world date")
    before = _opening_date(events) if log_tail.opened else today
    assert before is not None

    def stopped(stage: TickStage) -> bool:
        return stop_after is stage

    def finish(stage: TickStage) -> RealismTickResult:
        return result.model_copy(update={"stopped_after": stage})

    if not log_tail.opened:
        em.commit([em.event(ev.TickOpened(intents_frozen=()))])

    if estimator is not None and TickStage.ESTIMATE not in done:
        _estimate(em, estimator)
        em.commit([em.event(ev.TickStageCompleted(stage=TickStage.ESTIMATE))])
        done.add(TickStage.ESTIMATE)
        if stopped(TickStage.ESTIMATE):
            return finish(TickStage.ESTIMATE)

    if TickStage.ADVANCE not in done:
        batch: list[Event] = []
        if not any(d.truth.feed is not None for d in em.state.documents.values()):
            batch += _feed_documents(em, today)  # the opening in-tray, dated today
        local = replay(batch, initial=em.state) if batch else em.state
        wake = next_wake(local, today)
        batch.append(em.event(ev.DateAdvanced(to=wake.to)))
        batch.append(em.event(ev.TickStageCompleted(stage=TickStage.ADVANCE)))
        em.commit(batch)
        done.add(TickStage.ADVANCE)
        result = result.model_copy(update={"wake": wake})
        if stopped(TickStage.ADVANCE):
            return finish(TickStage.ADVANCE)

    new_today = em.state.in_world_date
    assert new_today is not None

    if TickStage.PIPELINES not in done:
        amended = _amend(em, events)
        if amended:
            em.commit(amended)
        batch = _walk(em, events, before, new_today)
        batch.append(em.event(ev.TickStageCompleted(stage=TickStage.PIPELINES)))
        em.commit(batch)
        done.add(TickStage.PIPELINES)
        if stopped(TickStage.PIPELINES):
            return finish(TickStage.PIPELINES)

    if TickStage.RESOLVE not in done:
        batch = []
        made = goals.aim_goals(em.state)
        if made:
            em.commit([em.event(g, scope=g.goal.scope) for g in made])
        for change in goals.check(em.state):
            goal = em.state.goals[change.goal_id]
            owner = goals.holder_seat(em.state, goal) or goal.seat_id
            batch.append(em.event(change, scope=private_to(owner)))
        batch.append(em.event(ev.TickStageCompleted(stage=TickStage.RESOLVE)))
        em.commit(batch)
        done.add(TickStage.RESOLVE)
        if stopped(TickStage.RESOLVE):
            return finish(TickStage.RESOLVE)

    if TickStage.FEEDS not in done:
        batch = _feed_documents(em, new_today)
        batch.append(em.event(ev.TickStageCompleted(stage=TickStage.FEEDS)))
        em.commit(batch)
        done.add(TickStage.FEEDS)
        if stopped(TickStage.FEEDS):
            return finish(TickStage.FEEDS)

    costs = list(log_tail.costs)
    if prose is not None and TickStage.PROSE not in done:
        batch, spent, dropped = _prose(em, prose)
        costs += spent
        batch.append(em.event(ev.TickStageCompleted(stage=TickStage.PROSE, costs=tuple(spent))))
        em.commit(batch)
        done.add(TickStage.PROSE)
        result = result.model_copy(
            update={"written": len(batch) - 1, "prose_dropped": tuple(dropped)}
        )
        if stopped(TickStage.PROSE):
            return finish(TickStage.PROSE)

    digest = state_hash(em.state)
    em.commit([em.event(ev.TickClosed(state_hash=digest, costs=tuple(costs)))])
    em.store.save_snapshot(em.state)
    if season.due(em.state):
        season.end_season(em.store, campaign_id)
    return result.model_copy(update={"state_hash": digest})


def _estimate(em: Emitter, transport: Transport) -> None:
    """One ``effects_estimated`` per routed part with no typed effect and no ruling, in
    (filed, order, part) order. Each lands with its cost as one batch, so a crash
    loses at most the call in flight and a resumed tick skips what is ruled."""
    todo = sorted(
        (o.filed, o.order_id, i)
        for o in em.state.routed.values()
        for i, part in enumerate(o.parts)
        if not part.was_estimated and (part.effect is None or reads_groups(em.state, o, i))
    )
    aided = aide_orders(em.store.read(em.state.campaign_id)) if todo else frozenset()
    for _, order_id, part in todo:
        ruled = estimate(em.state, order_id, part, transport, aide=order_id in aided)
        issuer = em.state.routed[order_id].issuer
        batch = [em.event(ruled.event, scope=private_to(issuer))]
        if ruled.cost is not None:
            # As ``campaign.log_cost`` records it, but inside the batch: the store
            # cannot take a second writer while the emitter holds the sequence.
            purpose = ruled.cost.call_class
            batch.append(em.event(ev.CostLogged(purpose=purpose, costs=(ruled.cost,))))
        em.commit(batch)


def _prose(em: Emitter, writer: ProseWriter) -> tuple[list[Event], list[CallCost], list[str]]:
    """``document_written`` for each page issued since the last tick closed that has no
    prose yet, one writer call per author. A page whose draft fails the check is sent
    once more, with the fault named; one that fails again keeps its lines alone. A
    failed call leaves its pages bare, and so does a page whose every line lacks a
    figure: there is nothing on it to write up."""
    log_now = list(em.store.read(em.state.campaign_id))
    start = max((i + 1 for i, e in enumerate(log_now) if e.kind == "tick_closed"), default=0)
    issued = [
        e.payload.document.doc_id
        for e in log_now[start:]
        if isinstance(e.payload, ev.DocumentIssued)
    ]
    by_author: dict[EntityId, list[DocumentView]] = {}
    for doc_id in issued:
        page = em.state.documents[doc_id].view
        if page.prose is None and not _nothing_stated(page) and _has_reader(em.state, page):
            by_author.setdefault(page.author, []).append(page)
    versions = em.versions.model_copy(
        update={"prompt": ",".join(x for x in (em.versions.prompt, prose_prompt_version()) if x)}
    )
    batch: list[Event] = []
    costs: list[CallCost] = []
    dropped: list[str] = []
    for author_id in sorted(by_author):
        pages = sorted(by_author[author_id], key=lambda v: (v.issued, v.doc_id))
        author = author_of(em.state, author_id, pages)
        try:
            written = writer.write(author, pages)
        except TransportError as exc:
            log.warning("prose call for %s failed: %s", author_id, exc)
            dropped += [f"{p.doc_id}: call failed" for p in pages]
            continue
        if written.cost is not None:
            costs.append(written.cost)
        keep, refused = accepted(pages, written, author)
        if refused:
            again = {r.doc_id: r.reason for r in refused}
            retry = author.model_copy(update={"refused": again})
            try:
                second = writer.write(retry, [p for p in pages if p.doc_id in again])
            except TransportError as exc:
                log.warning("second prose call for %s failed: %s", author_id, exc)
            else:
                if second.cost is not None:
                    costs.append(second.cost)
                more, refused = accepted([p for p in pages if p.doc_id in again], second, author)
                keep |= more
        dropped += [f"{r.doc_id}: {r.reason}" for r in refused]
        for page in pages:
            if page.doc_id in keep:
                e = em.event(
                    ev.DocumentWritten(doc_id=page.doc_id, prose=keep[page.doc_id]),
                    scope=page.scope,
                )
                batch.append(e.model_copy(update={"versions": versions}))
    return batch, costs, dropped


def _has_reader(state: State, page: DocumentView) -> bool:
    """A public page, or one a seat with a desk holds: prose is written to be read."""
    return page.scope.visibility is Visibility.PUBLIC or bool(
        page.scope.known_by & actors.readers(state)
    )


def _nothing_stated(page: DocumentView) -> bool:
    return bool(page.body) and all(line.value is None for line in page.body)


def _feed_documents(em: Emitter, today: date) -> list[Event]:
    """A document from every feed due on or before ``today``, dated ``today``.

    A feed that fell due during a collapsed stretch issues once, today, not once
    per skipped period."""
    seed = seed_for_day(em.state.campaign_id, today)
    out: list[Event] = []
    for feed in sorted(due_feeds(em.state, today), key=lambda f: f.feed_id):
        doc = issue(em.state, feed, today, seed)
        if doc is not None:
            out.append(em.event(doc, scope=doc.document.scope))
    return out


def _scope_of(state: State, payload: ev.Payload) -> Scope:
    if isinstance(payload, ev.DocumentIssued):
        return payload.document.scope
    if isinstance(payload, ev.OrderExecuted | ev.EffectsApplied | ev.InfluenceDecided):
        return private_to(state.routed[payload.order_id].issuer)
    if isinstance(payload, ev.MandateIssued):
        return payload.mandate.scope
    if isinstance(payload, ev.MandateSettled):
        return private_to(state.mandates[payload.mandate_id].seat_id)
    if isinstance(payload, ev.OrderRouted):
        return private_to(payload.order.issuer)
    if isinstance(payload, ev.OrderHeld):
        return private_to(payload.held.issuer)
    if isinstance(payload, ev.HeldOrderEnded):
        return private_to(payload.issuer)
    if isinstance(payload, ev.OrderAsked):
        return _asked_scope(payload.asked)
    if isinstance(payload, ev.AskAnswered):
        return private_to(payload.asker)
    if isinstance(payload, ev.AnswerPlanned | ev.AnswerMade):
        seat = actors.seat_of(state, payload.figure)
        return private_to(seat) if seat is not None else PUBLIC
    if isinstance(payload, ev.OrderDrafted) and payload.order.issuer not in actors.readers(state):
        return private_to(payload.order.issuer)
    if isinstance(payload, ev.PieceStepped):
        return _nation_scope(state, payload.nation)
    if isinstance(payload, ev.EconomySet):
        return _nation_scope(state, payload.polity)
    if isinstance(payload, ev.GroupMoved):
        return _nation_scope(state, payload.polity)  # true support: the nation's seats (GRP)
    if isinstance(payload, ev.OfferMade):
        return _nation_scope(state, payload.offer.nation)  # PRC: the bloc's nation's seats
    if isinstance(payload, ev.OfferSettled):
        settled = next(o for o in state.offers if o.offer_id == payload.offer_id)
        return _nation_scope(state, settled.nation)
    if isinstance(payload, ev.GroupProposed | ev.LossesHeld):
        # Engine only: the writing in waiting, the battle losses held (LSS).
        held = SeatId(derived_id(state.campaign_id, "engine-only", "groups"))
        return Scope(visibility=Visibility.RESTRICTED, known_by=frozenset({held}))
    if isinstance(payload, ev.ContestMoved | ev.ContestDecided):
        return state.contests[payload.contest_id].scope  # CON: the contest's own audience
    if isinstance(payload, ev.StepRefused):
        return _nation_scope(state, payload.nation)
    if isinstance(payload, ev.AgreementOffered):
        return agreement.parties_scope(state, payload.offer.parties)
    if isinstance(payload, ev.AgreementMade):
        if payload.agreement.public:  # CNF: a public conference's agreement
            return PUBLIC
        return agreement.parties_scope(state, payload.agreement.parties)
    if isinstance(payload, ev.ClauseJudged):
        found = state.agreements.made[payload.agreement_id]
        return PUBLIC if found.public else agreement.parties_scope(state, found.parties)
    if isinstance(payload, ev.ConferenceCalled):
        return conference.scope(state, payload.conference)  # CNF: the invited, or public
    if isinstance(payload, ev.ConferenceTallied):
        return conference.scope(state, state.conferences.held[payload.conference])
    if isinstance(payload, ev.VoteSealed):
        return private_to(payload.seat_id)  # CNF: the voter's alone
    if isinstance(payload, ev.TradeSet):
        # True figures: sealed to the seats of the two nations the line joins.
        a = _nation_scope(state, payload.line.exporter).known_by
        b = _nation_scope(state, payload.line.importer).known_by
        return Scope(visibility=Visibility.RESTRICTED, known_by=a | b)
    if isinstance(payload, ev.YieldChanged):
        # True figures: sealed to the holder's seats, or to no seat if it has none.
        owner = economy.holder(state, payload.area)
        if owner is not None:
            return _nation_scope(state, owner)
        held = SeatId(derived_id(state.campaign_id, "engine-only", "yield"))
        return Scope(visibility=Visibility.RESTRICTED, known_by=frozenset({held}))
    if isinstance(payload, ev.CaptureCounted):
        # Engine only: a count says where pieces stand. Sealed to a seat nobody holds.
        held = SeatId(derived_id(state.campaign_id, "engine-only", "capture"))
        return Scope(visibility=Visibility.RESTRICTED, known_by=frozenset({held}))
    if isinstance(payload, ev.AgentSet | ev.CodebreakingSet):
        # Engine only: where a nation has agents and how well it reads codes (IOR). The
        # holder of an area where an agent is lost learns of it from its paper.
        held = SeatId(derived_id(state.campaign_id, "engine-only", "intelligence"))
        return Scope(visibility=Visibility.RESTRICTED, known_by=frozenset({held}))
    if isinstance(payload, ev.ReportMade):
        # Engine only: it names the true piece and whether the report is wrong (DET). A
        # seat gets the report in its view once it arrives, and on its source's page.
        held = SeatId(derived_id(state.campaign_id, "engine-only", "report"))
        return Scope(visibility=Visibility.RESTRICTED, known_by=frozenset({held}))
    if isinstance(payload, ev.BattleOpened | ev.BattleRound | ev.BattleEnded):
        # Engine only: both sides' true strengths and the draws (BTL). Sealed to a seat
        # nobody holds; a seat learns of a battle from the news and its reports.
        held = SeatId(derived_id(state.campaign_id, "engine-only", "battle"))
        return Scope(visibility=Visibility.RESTRICTED, known_by=frozenset({held}))
    return PUBLIC  # a player's ``order_drafted`` too, as ``file_order`` lands it


def _asked_scope(asked: locks.Asked) -> Scope:
    """An ask is sealed to the asker and the seat asked, if a seat holds that person, and
    the seats holding a council's members (QKD)."""
    seats = {asked.asker, *asked.seats} | ({asked.seat} if asked.seat is not None else set())
    return Scope(visibility=Visibility.RESTRICTED, known_by=frozenset(seats))


def _nation_scope(state: State, nation: EntityId) -> Scope:
    """Sealed to the seats of ``nation``: every seat whose person belongs to it. A nation no
    seat holds gets a scope no seat holds either (its own derived name)."""
    seats = frozenset(
        s.seat_id for s in state.seats.values() if polity_of(state, s.embodies) == nation
    )
    held = seats or frozenset({SeatId(derived_id(state.campaign_id, "nation-seats", nation))})
    return Scope(visibility=Visibility.RESTRICTED, known_by=held)


def _amend(em: Emitter, events: Sequence[Event]) -> list[Event]:
    """Bring each card's allies, conflicts, answers, voice and form of address up to the
    world file the game was compiled from, so a game begun before they were written takes
    them at its next wake. Nothing when the file is gone or no longer compiles, and nothing
    for a card the game could not take (it names something the game does not have)."""
    name = next(
        (e.payload.world for e in events if isinstance(e.payload, ev.CampaignCreated)), None
    )
    if name is None:
        return []
    try:
        policy = card_policy(cmp.load_world(cmp.world_path(name)), em.state.campaign_id)
    except (OSError, ValueError) as exc:
        log.debug("no card amendments from world %s: %s", name, exc)
        return []
    out: list[Event] = []
    state = em.state
    for amendment in policy:
        card = state.cards.get(amendment.person)
        # A late field the world file leaves unset keeps the card's value in the fold,
        # so it is compared only when set.
        late = [k for k in sorted(ev.CardAmended.late_fields) if getattr(amendment, k) is not None]
        if card is None or (
            card.allies,
            card.opposes,
            card.answers,
            *(getattr(card, k) for k in late),
        ) == (
            amendment.allies,
            amendment.opposes,
            amendment.answers,
            *(getattr(amendment, k) for k in late),
        ):
            continue
        probe = Emitter(em.store, state, em.versions).event(amendment)
        try:
            state = replay([probe], initial=state)
        except FoldError as exc:
            log.warning("card %s not amended: %s", amendment.person, exc)
            continue
        out.append(em.event(amendment))
    return out


def _due_again_by(feed: Feed, day: date, until: date) -> bool:
    """Issued on ``day``, the feed would fall due again on or before ``until``."""
    return feed.every_days is not None and day + timedelta(days=feed.every_days) <= until


def _walk(em: Emitter, events: Sequence[Event], before: date, until: date) -> list[Event]:
    """Every day from ``before`` + 1 to ``until``, earliest first. Each day: orders
    move, history fires or skips what fell due and reports what fired in public as news
    (opinion reads fired incidents), the developments drawn to that day fire or skip, with
    their news and effects,
    commands fall due, processes open, influence is decided, ready parts apply, the
    orders enacted that day are resolved, then what moves with time, then arrivals, contacts and the
    press, then the feeds that fall due issue, dated that day, then mandates settle and
    issue, then the people nobody plays take up and make their answers, then stances
    and each seat's opponents are worked out. Pieces' steps are followed by the day's
    capture counts (THL); the day's battle rounds follow its contacts, with the count a won
    battle starts (BTL), then the press, then every nation's reports and their pages
    (DET); after the groups, each contest's moves land on the day's happenings and a
    contest is decided on its deciding day (CON); after the last day, the close, a capital
    marked in an earlier wake falls or loses its mark, and the contests read what the
    close did. Each step sees the state after the ones before it."""
    state = em.state
    out: list[Event] = []

    def add(payloads: Sequence[ev.Payload]) -> None:
        nonlocal state
        batch = [em.event(p, scope=_scope_of(state, p)) for p in payloads]
        state = replay(batch, initial=state)
        out.extend(batch)

    add(actors.unseated(state, [*answering.answerers(state), *answering.askable(state)]))
    begun: State | None = state  # moves the carried-in orders start begin on the first day
    wake_start = dict(state.opponents)
    walk_from, walk_mark = state, len(out)  # CON: each move reads from the last read on
    pending = _unresolved(events)
    for oid in pending:
        order = state.orders[oid]
        add(apply_changes(state, ON_ORDER[resolver_for(state, order)](state, order)))
    closed = max((i + 1 for i, e in enumerate(events) if e.kind == "tick_closed"), default=0)
    between = frozenset(  # forms a player carried through between ticks, dated ``before``
        e.payload.order_id
        for e in events[closed:]
        if isinstance(e.payload, ev.OrderSettled) and e.payload.status is OrderStatus.ENACTED
    )
    day = before
    while day < until:
        day += timedelta(days=1)
        start, begun = begun or state, None
        day_from, day_mark = state, len(out)  # GRP: the day's happenings are read from here
        add(posts.walk(state, day))  # PPP: a vacant post to its successor, before any step
        add(offers.batch(state, day))  # PRC: the wake's offers, settled before a vote
        steps = run_pipelines(state, day, seed_for_day(state.campaign_id, day))
        add(steps)
        settled = history.settle(state, day)
        add(settled)
        add(history.news(state, settled, day))
        drawn = history.developments_due(state, day)
        add(drawn)
        add(history.news(state, drawn, day))
        add(apply.developed(state, drawn, day))
        add(due_executions(state, day))
        add(process.open_processes(state, day))
        add(process.influence_due(state, day))
        add(agreement.offers_due(state, day))  # AGR: before a part's effect could land
        add(conference.walk(state, day))  # CNF: calls go out, voting days are tallied
        landed = apply.apply_due(state, day)
        add(landed)
        for step in steps:
            if isinstance(step, ev.OrderSettled) and step.status is OrderStatus.ENACTED:
                order = state.orders[step.order_id]
                add(apply_changes(state, ON_ORDER[resolver_for(state, order)](state, order)))
        before_on_day = state
        for on_day in ON_DAY.values():
            add(apply_changes(state, on_day(state, day)))
        met = movement.head_on(state, day)  # HON: borders met head-on, read before the steps
        add(movement.walk(state, day))
        add(agreement.deliveries(state, day))  # ENV: an envoy at a capital delivers its offer
        add(process.influence_due(state, day))  # ENV: the delivered offer's paper, the same day
        add(holders.walk(state, day))
        add(economy.walk(state, day))  # the 1st: pools paid from what is held today
        add(arrivals(before_on_day, state, day))
        add(contacts(state, day))
        open_before = state.battles
        fought = battle.walk(before_on_day, state, day, met)  # BTL: rounds after contacts
        add(fought)
        add(holders.start_count(state, battle.won(fought, open_before), day))
        today = [e.payload for e in out[day_mark:]]
        add(agreement.judge(state, day, today))  # AGR: each clause on its day, from the state
        add(groups.react(state, day_from, today, day, sea=before_on_day))
        add(groups.losses(state, day_from, today, day))  # LSS: the day's losses, by size
        add(groups.batch(state, day))  # GRP: the day's writing, settled in one batch
        add(groups.drift(state, day))  # GRP: on a Monday, toward the baseline
        add(offers.walk(state, day))  # PRC: a measure decided, a promise on its due day
        read = [e.payload for e in out[walk_mark:]]
        add(contests.moves(state, walk_from, read, day - timedelta(days=1), day))  # CON
        walk_from, walk_mark = state, len(out)
        add(contests.decisions(state, day))  # CON: on the deciding day, after its moves
        add(news_pages(state, day))
        add(detect.walk(state, start, day))  # DET: every nation's reports, before the feeds
        seed = seed_for_day(state.campaign_id, day)
        docs: list[Event] = []
        for feed in sorted(due_feeds(state, day), key=lambda f: f.feed_id):
            if _due_again_by(feed, day, until):
                continue  # one issue per stretch: the last day it falls due
            doc = issue(state, feed, day, seed)
            if doc is not None:
                docs.append(em.event(doc, scope=doc.document.scope))
        state = replay(docs, initial=state) if docs else state
        out.extend(docs)
        add(mandates.settle_due(state, day))
        add(mandates.issue_due(state, day))
        planned = answering.plan(state, day, since=before, between=between)
        add(planned)
        while made := answering.make(state, day):
            add(made)
        add(opponents.settle(state, day, [*landed, *planned], wake_start))
        while matter := _matter_answered(state, day):  # QKD: before a card answers an ask
            add(matter)
        while answer := answering.answer_ask(state, day):
            add(answer)
        add(_unlocked(state, day))  # ASK: each held order once a day, after the day's acts
    close_from, close_mark = state, len(out)
    add(holders.close(state, until))  # the wake's close: a capital marked before falls
    closing = [e.payload for e in out[close_mark:]]
    add(groups.react(state, close_from, closing, until))  # GRP: the close's happenings
    add(contests.moves(state, walk_from, [e.payload for e in out[walk_mark:]], until, until))
    return out


def _unlocked(state: State, day: date) -> list[ev.Payload]:
    """Each held order, once a world day, in id order (ASK): when its lock is open from
    state, it is re-checked against today's refusals and lands as an ordinary order dated
    ``day``, or ends failed with the reason. One still held by another lock stays held.
    An ask plays no part."""
    out: list[ev.Payload] = []
    for h in sorted(state.held.values(), key=lambda h: h.order_id):
        if not locks.open_now(state, h) or _locked_still(state, h, day):
            continue
        landed_id = OrderId(derived_id(state.campaign_id, "landed", h.order_id))
        landing, refusal = _relanded(state, h, landed_id, day)
        end = dict(order_id=h.order_id, issuer=h.issuer, on=day)
        if landing is None:
            failed = refusal[:300] or NOBODY
            out.append(ev.HeldOrderEnded(**end, end=locks.HeldEnd.FAILED, reason=failed))
            continue
        out += [landing, ev.HeldOrderEnded(**end, end=locks.HeldEnd.LANDED, by=landed_id)]
    return out


def _matter_answered(state: State, day: date) -> list[ev.Payload]:
    """The oldest matter due by ``day``, answered (QKD): granted or declined, told to the
    asker alone. Call again on the state after it until it returns nothing."""
    due = locks.matters_due(state, day)
    if not due:
        return []
    asked = due[0]
    granted = locks.matter_granted(state, asked)
    return [ev.AskAnswered(order_id=asked.order_id, asker=asked.asker, on=day, granted=granted)]


def _locked_still(state: State, h: locks.HeldOrder, day: date) -> bool:
    """Whether another lock holds the order now that its own has opened."""
    opened = {h.row} if h.row is not None and locks.opened_by_grant(state, h) else set()
    if h.form is not None:
        return locks.lock_for(state, h.issuer, h.form, opened) is not None
    found = [held(state, h.issuer, ask, day) for ask in h.asks]
    return any(f is not None and (f.row is None or f.row.key not in opened) for f in found)


def _relanded(
    state: State, held: locks.HeldOrder, landed_id: OrderId, day: date
) -> tuple[ev.OrderDrafted | ev.OrderRouted | None, str]:
    """The held order as an ordinary order dated ``day``, under ``landed_id``, once it
    passes today's refusals; else None and the first refusal's words."""
    seat = held.issuer
    form = held.form
    if form is not None:
        card = state.cards[state.seats[seat].embodies]
        if not any(x.name == form.lever for x in card.levers):
            return None, f"no lever {form.lever!r} on your card"
        given = {k: v if isinstance(v, str) else str(v) for k, v in form.params.items()}
        refused = order_refusal(state, seat, form.lever, given)
        if not refused:
            try:
                _refuse_twin_form(state, seat, form.lever, dict(form.params))
            except ValueError as exc:
                refused = str(exc)
        if refused:
            return None, refused
        landed = form.model_copy(update={"order_id": landed_id, "filed": day})
        return ev.OrderDrafted(order=landed), ""
    parts: list[RoutedPart] = []
    for ask in held.asks:
        routing = route(state, seat, ask, day)
        if routing.part is None:
            return None, routing.refusal
        parts.append(routing.part)
    order = RoutedOrder(
        order_id=landed_id, issuer=seat, filed=day, parts=tuple(parts), forecast=held.forecast
    )
    return ev.OrderRouted(order=order), ""


def ask_order(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, order_id: OrderId
) -> locks.Asked:
    """The seat asks, once, for its held order (ASK): one paper before the seat holding
    the person who decides it, or the card when no seat does, dated today. It decides
    nothing and opens nothing. Raises ``ValueError`` with the seat's words."""
    state = load_state(store, campaign_id)
    today = state.in_world_date
    if today is None:
        raise ValueError(locks.NOT_HELD)
    asked = locks.ask(state, seat, order_id, today)
    _append_all(store, state, [(ev.OrderAsked(asked=asked), _asked_scope(asked))], seat)
    return asked


def choose_matter(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, order_id: OrderId, accept: bool
) -> None:
    """The seat's sealed choice on the matter before it (QKD): to accept or decline the
    ask for the held order ``order_id``, dated today; a later choice before the due day
    replaces it. Raises ``ValueError`` with the seat's words."""
    state = load_state(store, campaign_id)
    today = state.in_world_date
    if today is None:
        raise ValueError(locks.NOT_A_MEMBER)
    locks.may_choose(state, seat, order_id)
    chosen = ev.MatterChosen(order_id=order_id, seat_id=seat, accept=accept, on=today)
    _append_all(store, state, [(chosen, private_to(seat))], seat)


def make_offer(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, bloc: str, measure: str, price: str
) -> offers.PricedOffer:
    """The seat offers ``price`` to ``bloc`` of its own nation for ``measure`` (PRC), dated
    today and sealed to the seats of that nation; the next day's batch takes or refuses it.
    Raises ``ValueError`` with the seat's words."""
    state = load_state(store, campaign_id)
    today = state.in_world_date
    if today is None:
        raise ValueError(offers.NOT_ON)
    made = offers.offer(state, seat, bloc, measure, price, today)
    _append_all(store, state, [(made, _nation_scope(state, made.offer.nation))], seat)
    return made.offer


def change_post(
    store: EventStore,
    campaign_id: CampaignId,
    post: AssetId,
    to: EntityId | None,
    cause: PostCause,
) -> list[ev.PostChanged]:
    """Give ``post`` to ``to``, or to nobody, today (PPP), as ``posts.change`` words it, in
    one batch checked by the fold first. Nothing with ``posts`` off."""
    state = load_state(store, campaign_id)
    today = state.in_world_date
    if today is None:
        raise ValueError("a post changes hands only in a game under way")
    made = posts.change(state, post, to, today, cause)
    if made:
        versions = cmp.versions()
        batch = [
            Event(
                event_id=EventId(new_id()),
                campaign_id=campaign_id,
                seq=state.last_seq + i,
                tick=state.tick,
                actor=None,
                scope=PUBLIC,
                payload=p,
                versions=versions,
            )
            for i, p in enumerate(made, start=1)
        ]
        replay(batch, initial=state)
        store.append_all(batch)
    return made


def set_own_aim(
    store: EventStore,
    campaign_id: CampaignId,
    seat: SeatId,
    key: str,
    values: Mapping[str, aim_patterns.BlankValue],
) -> aim_patterns.OwnAim | aim_patterns.Refused:
    """The seat sets its person's own aim from the pattern ``key`` filled with ``values``
    (OWC): checked as ``aim_patterns.fill`` checks it, from the state it is numbered from,
    and logged sealed to the seat; or the reasons it cannot stand, logging nothing."""
    state = load_state(store, campaign_id)
    out = aim_patterns.own_aim_set(state, seat, key, values)
    if isinstance(out, aim_patterns.Refused):
        return out
    _append_all(store, state, [(out, private_to(seat))], seat)
    return out.own


# --- what a human does between ticks ---------------------------------------------


def wake_line(result: RealismTickResult, today: date | None) -> str:
    """The line the CLI and the web print after a realism tick."""
    woke = f"{result.wake.reason.label}, " if result.wake is not None else ""
    return f"tick {result.tick}: woke on {woke}now {today}"


def seat_player(store: EventStore, campaign_id: CampaignId, entity: EntityId) -> str:
    """Seat the human as ``entity``, then close Session Zero. Returns the person's
    name. Raises ``StepRefusedError``."""
    name = load_state(store, campaign_id).entities[entity].name
    seat = SeatId(derived_id(campaign_id, "seat", entity))
    session_zero.claim(store, campaign_id, seat, name)
    open_play(store, campaign_id)
    return name


def open_play(store: EventStore, campaign_id: CampaignId) -> None:
    """Close a realism Session Zero: no goals or agents to wait for. The opening
    in-tray and each human seat's opening matter land in the same batch, so wake 0
    has papers to read and something to answer. Raises
    ``StepRefusedError`` when no one holds a person yet."""
    state = load_state(store, campaign_id)
    if not cmp.human_seats(state):
        raise session_zero.StepRefusedError("No one has chosen a person yet.")
    em = Emitter(store, state, cmp.versions())
    batch = [em.event(ev.SessionZeroClosed())]
    if state.in_world_date is not None:
        batch += _opening_in_tray(em, state.in_world_date)
        for seat in cmp.human_seats(state):
            matter = mandates.opening(state, seat, state.in_world_date)
            if matter is not None:
                batch.append(em.event(matter, scope=matter.mandate.scope))
        batch += [em.event(p) for p in opponents.settle(state, state.in_world_date)]
    em.commit(batch)


def _opening_in_tray(em: Emitter, today: date) -> list[Event]:
    """The feeds due at the start, each arrived on the start date: the pile on the
    desk when the person takes office. Later issues keep their latency."""
    out: list[Event] = []
    for e in _feed_documents(em, today):
        assert isinstance(e.payload, ev.DocumentIssued)
        page = e.payload.document.model_copy(update={"arrives": today})
        out.append(
            e.model_copy(update={"payload": e.payload.model_copy(update={"document": page})})
        )
    return out


def write_opening(
    store: EventStore, campaign_id: CampaignId, writer: ProseWriter
) -> OpeningWritten:
    """Prose for the opening papers at the begin, so the first paper on each desk reads
    as a paper: the same calls the first tick's PROSE stage would make, one per author,
    made now. Costs land as one ``cost_logged``. A page the writer fails or refuses stays
    bare and the first tick writes it. Does nothing once a tick has opened: later pages
    belong to that tick, and if another writer moves the log while the calls are out the
    pages stay bare for the first tick (the calls' cost goes unlogged)."""
    seen = store.last_seq(campaign_id)
    state = load_state(store, campaign_id)
    if state.tick or tail(list(store.read(campaign_id))).opened:
        return OpeningWritten()
    em = Emitter(store, state, cmp.versions())
    batch, spent, dropped = _prose(em, writer)
    if store.last_seq(campaign_id) != seen:
        return OpeningWritten()
    if spent:
        batch.append(em.event(ev.CostLogged(purpose="prose", costs=tuple(spent))))
    if batch:
        em.commit(batch)
    written = sum(isinstance(e.payload, ev.DocumentWritten) for e in batch)
    return OpeningWritten(written=written, prose_dropped=tuple(dropped))


def _fits(spec: ParamSpec, raw: str) -> ParamValue:
    if spec.kind is ParamKind.INT:
        try:
            value = int(raw)
        except ValueError:
            raise ValueError(f"{spec.name}: {raw!r} is not a whole number") from None
        if spec.lo is None or spec.hi is None or not spec.lo <= value <= spec.hi:
            raise ValueError(f"{spec.name}: {raw} is outside {spec.lo}..{spec.hi}")
        return value
    if spec.kind is ParamKind.ENUM and raw not in spec.choices:
        raise ValueError(f"{spec.name}: {raw!r} is not one of {', '.join(spec.choices)}")
    if spec.kind is ParamKind.TEXT and not raw.strip():
        raise ValueError(f"{spec.name}: give it some words")
    return raw


def _place(state: State, spec: ParamSpec, raw: str) -> str:
    """A destination: one of the form's own choices, or any place with a position."""
    if raw in spec.choices or place_named(state, raw) is not None:
        return raw
    raise ValueError(f"{spec.name}: {raw!r} is not a place on the map")


def _force(state: State, spec: ParamSpec, raw: str) -> str:
    """A force to move: one of the form's own choices, or a detachment of one in play."""
    found = state.features.get(FeatureId(object_id(state.campaign_id, "feature", raw)))
    parents = {FeatureId(object_id(state.campaign_id, "feature", c)) for c in spec.choices}
    if found is not None and in_play(found) and found.detached_from in parents:
        return raw
    return str(_fits(spec, raw))


def _widened(state: State, found: Lever, spec: ParamSpec, raw: str) -> ParamValue:
    """A parameter's value. The destination takes any place and a movement form's force a
    detachment of its choices; a split form's force takes only its choices, since a
    detachment is not split again."""
    if spec is destination(found):
        return _place(state, spec, raw)
    if (
        found.resolver == "movement"
        and spec.name == FORCE
        and all(p.name != STRENGTH for p in found.params)
    ):
        return _force(state, spec, raw)
    return _fits(spec, raw)


Landing = list[tuple[ev.Payload, Scope]]
"""What a filing logs, in order, each event with its scope."""


def file_order(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, lever: str, given: dict[str, str]
) -> Order:
    """Draft the seat's order for ``lever`` dated today and file it: it lands, or a lock
    holds it (``form_filing``). Every parameter must be given and fit its spec. Raises
    ``ValueError``."""
    state = load_state(store, campaign_id)
    order = draft_order(state, seat, lever, given)
    landing, filed = form_filing(state, seat, order)
    _append_all(store, state, landing, seat)
    return filed


def form_filing(state: State, seat: SeatId, order: Order) -> tuple[Landing, Order]:
    """What filing the drafted ``order`` logs, and the order as filed. It lands, or, when
    a lock holds it as the seat's view shows it, it is held with the row and the decider
    (LCK); then each of the seat's held orders aimed at the same force and zone ends,
    replaced. Nothing, and the order already held, when the seat's same filing is held."""
    lock = locks.seen_lock(state, seat, order)
    again = locks.retried(state, seat, order) if lock is not None else None
    if again is not None and again.form is not None:
        return [], again.form
    if lock is None:
        first: tuple[ev.Payload, Scope] = (ev.OrderDrafted(order=order), PUBLIC)
    else:
        hold = locks.HeldOrder(
            order_id=order.order_id,
            issuer=seat,
            filed=order.filed,
            form=order,
            **_lock(state, seat, lock),
        )
        first = (ev.OrderHeld(held=hold), private_to(seat))
    return [first, *_replacing(state, seat, order, order.order_id, order.filed)], order


def _lock(state: State, issuer: SeatId, lock: locks.Lock) -> dict[str, Any]:
    """What a held order keeps of ``lock``: its row, its decider and the reason its seat
    is told."""
    row = lock.row.key if lock.row is not None else None
    view = project(state, issuer)
    return {"row": row, "decider": lock.decider, "reason": locks.reason(view, lock)}


def _replacing(
    state: State, seat: SeatId, order: Order | Sequence[Ask], by: OrderId, on: date
) -> Landing:
    """An end for each of the seat's held orders that a later ``order`` replaces."""
    return [
        (
            ev.HeldOrderEnded(
                order_id=h.order_id, issuer=seat, end=locks.HeldEnd.REPLACED, on=on, by=by
            ),
            private_to(seat),
        )
        for h in locks.replaced(state, seat, order)
    ]


def draft_order(state: State, seat: SeatId, lever: str, given: dict[str, str]) -> Order:
    """The seat's order for ``lever`` dated today, checked against its card but not
    filed. Raises ``ValueError``."""
    card = state.cards[state.seats[seat].embodies]
    found = next((x for x in card.levers if x.name == lever), None)
    if found is None:
        names = ", ".join(x.name for x in card.levers)
        raise ValueError(f"no lever {lever!r} on your card (levers: {names})")
    wanted = {p.name for p in found.params}
    if set(given) != wanted:
        raise ValueError(f"{lever} takes exactly: {', '.join(sorted(wanted)) or 'no parameters'}")
    params = {p.name: _widened(state, found, p, given[p.name]) for p in found.params}
    refused = order_refusal(state, seat, lever, given)
    if refused:
        raise ValueError(refused)
    _refuse_twin_form(state, seat, lever, params)
    assert state.in_world_date is not None
    return Order(
        order_id=OrderId(new_id()),
        issuer=seat,
        lever=lever,
        pipeline=found.pipeline,
        params=params,
        filed=state.in_world_date,
    )


def _refuse_twin_form(
    state: State, seat: SeatId, lever: str, params: dict[str, ParamValue]
) -> None:
    """Raise ``ValueError`` when the seat's same form, with the same terms, is still
    moving, saying who holds it now."""
    for order in state.orders.values():
        if (
            order.issuer != seat
            or order.routed_from is not None
            or order.status in SETTLED
            or (order.lever, order.params) != (lever, params)
        ):
            continue
        steps = state.pipelines[order.pipeline].steps
        where = (
            f"it is with {state.entities[steps[order.step].person].name}"
            if order.step < len(steps)
            else "it is through every step and waits to be settled"
        )
        raise ValueError(f"You already sent that and {where}.")


def _words(text: str) -> str:
    return " ".join(text.casefold().split())


def _pending_words(state: State, seat: SeatId) -> set[tuple[str, EntityId | None]]:
    """Free-text asks the seat has sent that are still on their way: the words and who
    they went to. A part is on its way until it is applied or, for a process, settled."""
    carried = {o.routed_from: o for o in state.orders.values() if o.routed_from is not None}
    out: set[tuple[str, EntityId | None]] = set()
    for order in state.routed.values():
        if order.issuer != seat:
            continue
        for i, part in enumerate(order.parts):
            if part.effect is not None or part.applied is not None or not part.ask.strip():
                continue
            if part.route is Route.PROCESS:
                carrier = carried.get(PartRef(order_id=order.order_id, part=i))
                if carrier is not None and carrier.status in SETTLED:
                    continue
            out.add((_words(part.ask), part.target or part.executor))
    return out


def _pending_effects(state: State, seat: SeatId) -> list[Effect]:
    """The typed asks the seat has sent that are still on their way: not refused,
    not turned down, not yet landed. Free-text asks carry no effect and are not compared."""
    carried = {o.routed_from: o for o in state.orders.values() if o.routed_from is not None}
    out: list[Effect] = []
    for order in state.routed.values():
        if order.issuer != seat:
            continue
        for i, part in enumerate(order.parts):
            if part.effect is None or part.refusal or part.applied is not None:
                continue
            if part.accepted is False:
                continue
            if part.route is Route.PROCESS:
                carrier = carried.get(PartRef(order_id=order.order_id, part=i))
                if carrier is not None and carrier.status in SETTLED:
                    continue
            out.append(part.effect)
    return out


def commit_order(
    store: EventStore,
    campaign_id: CampaignId,
    seat: SeatId,
    asks: Sequence[Ask],
    forecast: Forecast | None = None,
) -> RoutedOrder | locks.HeldOrder:
    """Route every ask on today's date and land them as one order, or hold it
    (``written_filing``). If any ask has no route and no lock holds it, raises
    ``ValueError`` with its words and nothing is logged. ``forecast``: the picked
    suggestion's expected moves and risks, stored on the routed order (an empty one as
    none); no rule reads it."""
    state = load_state(store, campaign_id)
    landing, filed = written_filing(state, seat, asks, forecast)
    _append_all(store, state, landing, seat)
    return filed


def written_filing(
    state: State, seat: SeatId, asks: Sequence[Ask], forecast: Forecast | None = None
) -> tuple[Landing, RoutedOrder | locks.HeldOrder]:
    """What filing the written ``asks`` logs, and the order as filed. Every refusal of
    today's comes first. Then, when a lock holds any ask as the seat's view shows it, the
    whole order is held with the first such lock's row and decider (LCK); else it lands as
    one routed order. Each of the seat's held orders aimed at the same force and zone
    ends, replaced. Nothing, and the order already held, when the same asks are held."""
    today = state.in_world_date
    assert today is not None
    pending = _pending_effects(state, seat)
    said = _pending_words(state, seat)
    parts: list[RoutedPart] = []
    found: list[locks.Lock] = []
    deals = [
        a for a in asks if isinstance(a.effect, Deal) and (a.effect.parties or a.effect.publish)
    ]
    for ask in deals:
        assert isinstance(ask.effect, Deal)
        if len(asks) > 1:
            raise ValueError(agreement.ALONE)
        why = agreement.refusal(state, seat, ask.effect)
        if why:
            raise ValueError(why)
        if ask.effect.publish is not None:
            parts.append(agreement.publish_part(ask.ask, ask.effect))
        else:
            parts += agreement.offer_parts(state, seat, ask.ask, ask.effect)
    for ask in asks if not deals else ():
        if ask.effect is not None:
            if ask.effect in pending:
                raise ValueError(
                    f"You already sent that order and it is still on its way: {ask.ask}"
                )
            pending.append(ask.effect)
        routing = route(state, seat, ask, today)
        lock = held(state, seat, ask, today)
        if lock is not None:
            found.append(lock)
        if routing.part is None:
            if lock is None:
                raise ValueError(routing.refusal)
            continue
        part = routing.part
        if part.effect is None:
            words = (_words(part.ask), part.target or part.executor)
            if words in said:
                raise ValueError(
                    f"You already sent that order and it is still on its way: {ask.ask}"
                )
            said.add(words)
        parts.append(part)
    kept = None if forecast is None or forecast.empty() else forecast
    if found:
        again = locks.retried(state, seat, asks)
        if again is not None:
            return [], again
        hold = locks.HeldOrder(
            order_id=OrderId(new_id()),
            issuer=seat,
            filed=today,
            asks=tuple(asks),
            forecast=kept,
            **_lock(state, seat, found[0]),
        )
        return [
            (ev.OrderHeld(held=hold), private_to(seat)),
            *_replacing(state, seat, asks, hold.order_id, today),
        ], hold
    order = RoutedOrder(
        order_id=OrderId(new_id()), issuer=seat, filed=today, parts=tuple(parts), forecast=kept
    )
    return [
        (ev.OrderRouted(order=order), private_to(seat)),
        *_replacing(state, seat, asks, order.order_id, today),
    ], order


NOT_YOURS = "That decision is not yours to take."  # [proposed]
NO_AMEND = "That step cannot be amended here."  # [proposed]


def held_step_order(state: State, seat: SeatId, ref: str) -> OrderId | None:
    """The order another seat's step waits on at ``seat``'s person, named by ``ref``:
    the id of the paper that brought it. None when ``ref`` names no such step."""
    return next(
        (
            order.order_id
            for order in state.orders.values()
            if held_by_another(state, order) == seat
            and held_paper_id(state.campaign_id, order.order_id, order.step) == ref
        ),
        None,
    )


def stepped_order(state: State, seat: SeatId, ref: str) -> Order:
    """The order ``seat`` would act at: ``ref`` is an order id, or the id of the paper
    that put another seat's order before it. Raises ``ValueError(NOT_YOURS)`` for
    anything but the seat's own order or one waiting at a step it holds, whether or not
    the order exists, and for its own order waiting on another human seat."""
    order = state.orders.get(OrderId(ref))
    if order is None:
        found = held_step_order(state, seat, ref)
        order = state.orders.get(found) if found is not None else None
    if order is None or (order.issuer != seat and held_by_another(state, order) != seat):
        raise ValueError(NOT_YOURS)
    if waiting_on_human(state, order):
        person = state.pipelines[order.pipeline].steps[order.step].person
        if process.holder(state, person) != seat:
            raise ValueError(NOT_YOURS)
    return order


def take_step(
    store: EventStore,
    campaign_id: CampaignId,
    seat: SeatId,
    ref: str,
    action: StepAction,
    given: dict[str, str],
) -> Order:
    """``seat`` acts at the step it holds; ``ref`` as ``stepped_order`` takes it. On its
    own order the step is taken today. On another seat's order the choice is kept,
    sealed to ``seat``, and taken on the step's held due day in the card's place.
    There an amend is refused (``NO_AMEND``): the card's only amend has a fixed shape
    (``pipelines._trim``), and the issuer's paper prints every change, so any other
    would tell the issuer a person decided. Raises ``ValueError``."""
    state = load_state(store, campaign_id)
    order = stepped_order(state, seat, ref)
    if order.issuer != seat and action is StepAction.AMEND:
        raise ValueError(NO_AMEND)
    order_id = order.order_id
    assert state.in_world_date is not None
    levers = state.cards[state.seats[order.issuer].embodies].levers
    specs = {p.name: p for lever in levers if lever.name == order.lever for p in lever.params}
    amended: dict[str, ParamValue] = {}
    for name, raw in given.items():
        if name not in specs:
            raise ValueError(f"order has no parameter {name}")
        amended[name] = _fits(specs[name], raw)
    if order.issuer != seat:
        checked_step(state, order_id, action, amended)
        chosen = ev.StepChosen(order_id=order_id, step=order.step, action=action, amended=amended)
        _append(store, state, chosen, seat, private_to(seat))
        return load_state(store, campaign_id).orders[order_id]
    steps = human_step(state, order_id, action, state.in_world_date, amended)
    batch: list[Event] = []
    seq = state.last_seq

    def add(payloads: Sequence[ev.Payload]) -> State:
        nonlocal seq
        added: list[Event] = []
        for payload in payloads:
            seq += 1
            added.append(
                Event(
                    event_id=EventId(new_id()),
                    campaign_id=campaign_id,
                    seq=seq,
                    tick=state.tick,
                    actor=order.issuer,
                    scope=(
                        payload.document.scope if isinstance(payload, ev.DocumentIssued) else PUBLIC
                    ),
                    payload=payload,
                    versions=cmp.versions(),
                )
            )
        batch.extend(added)
        # fold first so a bad step never reaches the store
        return replay(batch, initial=state)

    after = add(steps)
    if any(isinstance(p, ev.OrderSettled) and p.status is OrderStatus.ENACTED for p in steps):
        # The votes are counted at once, in the same batch as the final step.
        enacted = after.orders[order_id]
        add(apply_changes(after, ON_ORDER[resolver_for(after, enacted)](after, enacted)))
    store.append_all(batch)
    return load_state(store, campaign_id).orders[order_id]


def mark_read(store: EventStore, campaign_id: CampaignId, seat: SeatId, doc_id: DocumentId) -> bool:
    """Log that ``seat`` opened ``doc_id``, once. False if it was already marked."""
    for e in store.read(campaign_id):
        if (
            isinstance(e.payload, ev.DocumentRead)
            and e.payload.seat_id == seat
            and e.payload.doc_id == doc_id
        ):
            return False
    state = load_state(store, campaign_id)
    _append(store, state, ev.DocumentRead(seat_id=seat, doc_id=doc_id), seat, private_to(seat))
    return True


def set_flag(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, doc_id: DocumentId, flagged: bool
) -> bool:
    """Flag ``doc_id`` for ``seat``, or take the flag off. False if it already stood so."""
    standing = False
    for e in store.read(campaign_id):
        if (
            isinstance(e.payload, ev.DocumentFlagged)
            and e.payload.seat_id == seat
            and e.payload.doc_id == doc_id
        ):
            standing = e.payload.flagged
    if standing == flagged:
        return False
    state = load_state(store, campaign_id)
    event = ev.DocumentFlagged(seat_id=seat, doc_id=doc_id, flagged=flagged)
    _append(store, state, event, seat, private_to(seat))
    return True


def _append_all(store: EventStore, state: State, landing: Landing, actor: SeatId) -> None:
    """Log ``landing`` as one batch numbered from ``state``, checked by the fold first."""
    if not landing:
        return
    versions = cmp.versions()
    batch = [
        Event(
            event_id=EventId(new_id()),
            campaign_id=state.campaign_id,
            seq=state.last_seq + i,
            tick=state.tick,
            actor=actor,
            scope=scope,
            payload=payload,
            versions=versions,
        )
        for i, (payload, scope) in enumerate(landing, start=1)
    ]
    replay(batch, initial=state)
    store.append_all(batch)


def _append(
    store: EventStore,
    state: State,
    payload: ev.Payload,
    actor: SeatId,
    scope: Scope = PUBLIC,
) -> None:
    event = Event(
        event_id=EventId(new_id()),
        campaign_id=state.campaign_id,
        seq=state.last_seq + 1,
        tick=state.tick,
        actor=actor,
        scope=scope,
        payload=payload,
        versions=cmp.versions(),
    )
    replay([event], initial=state)
    store.append_all([event])


__all__ = [
    "NOT_YOURS",
    "NO_AMEND",
    "Landing",
    "OpeningWritten",
    "RealismTickResult",
    "ask_order",
    "commit_order",
    "draft_order",
    "file_order",
    "form_filing",
    "held_step_order",
    "mark_read",
    "open_play",
    "run_realism_tick",
    "seat_player",
    "set_flag",
    "set_own_aim",
    "stepped_order",
    "take_step",
    "wake_line",
    "write_opening",
    "written_filing",
]
