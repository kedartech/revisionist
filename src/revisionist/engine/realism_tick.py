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
from collections.abc import Sequence
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core import goals, history
from revisionist.core._base import Model
from revisionist.core.events import CallCost, Event, Versions
from revisionist.core.fold import FoldError, replay, state_hash
from revisionist.core.ids import (
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
from revisionist.core.realism import actors, answering, apply, mandates, opponents, process
from revisionist.core.realism.advance import Wake, next_wake
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.arrivals import arrivals
from revisionist.core.realism.card import Lever, ParamKind, ParamSpec, ParamValue
from revisionist.core.realism.document import DocumentView, Feed
from revisionist.core.realism.effect import Effect, PartRef, Route, RoutedOrder, RoutedPart
from revisionist.core.realism.feeds import due_feeds, issue, seed_for_day
from revisionist.core.realism.geography import in_play
from revisionist.core.realism.pipeline import SETTLED, Order, OrderStatus, StepAction
from revisionist.core.realism.pipelines import (
    destination,
    human_step,
    place_named,
    run_pipelines,
)
from revisionist.core.realism.press import news_pages
from revisionist.core.realism.resolvers import (
    ON_DAY,
    ON_ORDER,
    apply_changes,
    resolver_for,
)
from revisionist.core.realism.resolvers.movement import FORCE, STRENGTH
from revisionist.core.realism.route import due_executions, route
from revisionist.core.realism.war_rules import contacts, order_refusal
from revisionist.core.resolution import TickStage
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, Scope, Visibility, private_to
from revisionist.core.world_compile import card_policy, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import session_zero
from revisionist.engine.emit import Emitter, tail
from revisionist.engine.estimate import CALL_CLASS, estimate
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
        for change in goals.check(em.state):
            owner = em.state.goals[change.goal_id].seat_id
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
    return result.model_copy(update={"state_hash": digest})


def _estimate(em: Emitter, transport: Transport) -> None:
    """One ``effects_estimated`` per routed part with no typed effect and no ruling, in
    (filed, order, part) order. Each lands with its cost as one batch, so a crash
    loses at most the call in flight and a resumed tick skips what is ruled."""
    todo = sorted(
        (o.filed, o.order_id, i)
        for o in em.state.routed.values()
        for i, part in enumerate(o.parts)
        if part.effect is None and not part.was_estimated
    )
    for _, order_id, part in todo:
        ruled = estimate(em.state, order_id, part, transport)
        issuer = em.state.routed[order_id].issuer
        batch = [em.event(ruled.event, scope=private_to(issuer))]
        if ruled.cost is not None:
            # As ``campaign.log_cost`` records it, but inside the batch: the store
            # cannot take a second writer while the emitter holds the sequence.
            batch.append(em.event(ev.CostLogged(purpose=CALL_CLASS, costs=(ruled.cost,))))
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
    if isinstance(payload, ev.AnswerPlanned | ev.AnswerMade):
        seat = actors.seat_of(state, payload.figure)
        return private_to(seat) if seat is not None else PUBLIC
    if isinstance(payload, ev.OrderDrafted) and payload.order.issuer not in actors.readers(state):
        return private_to(payload.order.issuer)
    return PUBLIC  # a player's ``order_drafted`` too, as ``file_order`` lands it


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
        if card is None or (
            card.allies,
            card.opposes,
            card.answers,
            card.voice,
            card.addressed_as,
        ) == (
            amendment.allies,
            amendment.opposes,
            amendment.answers,
            amendment.voice,
            amendment.addressed_as,
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
    (opinion reads fired incidents),
    commands fall due, processes open, influence is decided, ready parts apply, the
    orders enacted that day are resolved, then what moves with time, then arrivals, contacts and the
    press, then the feeds that fall due issue, dated that day, then mandates settle and
    issue, then the people nobody plays take up and make their answers, then stances
    and each seat's opponents are worked out. Each step sees the state after the ones
    before it."""
    state = em.state
    out: list[Event] = []

    def add(payloads: Sequence[ev.Payload]) -> None:
        nonlocal state
        batch = [em.event(p, scope=_scope_of(state, p)) for p in payloads]
        state = replay(batch, initial=state)
        out.extend(batch)

    add(actors.unseated(state, answering.answerers(state)))
    wake_start = dict(state.opponents)
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
        steps = run_pipelines(state, day, seed_for_day(state.campaign_id, day))
        add(steps)
        settled = history.settle(state, day)
        add(settled)
        add(history.news(state, settled, day))
        add(due_executions(state, day))
        add(process.open_processes(state, day))
        add(process.influence_due(state, day))
        landed = apply.apply_due(state, day)
        add(landed)
        for step in steps:
            if isinstance(step, ev.OrderSettled) and step.status is OrderStatus.ENACTED:
                order = state.orders[step.order_id]
                add(apply_changes(state, ON_ORDER[resolver_for(state, order)](state, order)))
        before_on_day = state
        for on_day in ON_DAY.values():
            add(apply_changes(state, on_day(state, day)))
        add(arrivals(before_on_day, state, day))
        add(contacts(state, day))
        add(news_pages(state, day))
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
    return out


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


def file_order(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, lever: str, given: dict[str, str]
) -> Order:
    """Draft the seat's order for ``lever`` dated today. Every parameter must be given
    and fit its spec. Raises ``ValueError``."""
    state = load_state(store, campaign_id)
    order = draft_order(state, seat, lever, given)
    _append(store, state, ev.OrderDrafted(order=order), seat)
    return order


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
    store: EventStore, campaign_id: CampaignId, seat: SeatId, asks: Sequence[Ask]
) -> RoutedOrder:
    """Route every ask on today's date and land them as one order. If any ask has no
    route, raises ``ValueError`` with its words and nothing is logged."""
    state = load_state(store, campaign_id)
    today = state.in_world_date
    assert today is not None
    pending = _pending_effects(state, seat)
    said = _pending_words(state, seat)
    parts: list[RoutedPart] = []
    for ask in asks:
        if ask.effect is not None:
            if ask.effect in pending:
                raise ValueError(
                    f"You already sent that order and it is still on its way: {ask.ask}"
                )
            pending.append(ask.effect)
        routing = route(state, seat, ask, today)
        if routing.part is None:
            raise ValueError(routing.refusal)
        part = routing.part
        if part.effect is None:
            words = (_words(part.ask), part.target or part.executor)
            if words in said:
                raise ValueError(
                    f"You already sent that order and it is still on its way: {ask.ask}"
                )
            said.add(words)
        parts.append(part)
    order = RoutedOrder(order_id=OrderId(new_id()), issuer=seat, filed=today, parts=tuple(parts))
    _append(store, state, ev.OrderRouted(order=order), seat, private_to(seat))
    return order


def take_step(
    store: EventStore,
    campaign_id: CampaignId,
    order_id: OrderId,
    action: StepAction,
    given: dict[str, str],
) -> Order:
    """The human acts at the step they hold, dated today. Raises ``ValueError``."""
    state = load_state(store, campaign_id)
    order = state.orders.get(order_id)
    if order is None:
        raise ValueError(f"no order {order_id}")
    assert state.in_world_date is not None
    levers = state.cards[state.seats[order.issuer].embodies].levers
    specs = {p.name: p for lever in levers if lever.name == order.lever for p in lever.params}
    amended: dict[str, ParamValue] = {}
    for name, raw in given.items():
        if name not in specs:
            raise ValueError(f"order has no parameter {name}")
        amended[name] = _fits(specs[name], raw)
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
    "OpeningWritten",
    "RealismTickResult",
    "commit_order",
    "draft_order",
    "file_order",
    "mark_read",
    "open_play",
    "run_realism_tick",
    "seat_player",
    "set_flag",
    "take_step",
    "wake_line",
    "write_opening",
]
