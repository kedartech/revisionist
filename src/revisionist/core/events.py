"""The event log (spec §12, decision #19).

The log is canon. State is a projection of it. Every payload below is a kind
of event the log can hold; ``Event`` is the envelope.

State-mutating kinds (the fold in Layer 2 handles exactly these):
``CampaignCreated, SettingsSet, EntityCreated, AssetCreated, RelationshipSet,
MeterCreated, ClockCreated, FactAsserted, CommitmentCreated, SeatCreated,
AgentAssigned, SeatStatusSet, IntentFiled, IntentRejected, DeltaApplied,
ScheduledEventFired, ContestCreated, ContestMoved, ContestDecided,
ScheduledEventCreated, ScheduledEventSkipped, DivergenceChanged, DateAdvanced,
SessionZeroOpened, CharacterListed, CharacterClaimed,
CharacterReleased, SessionZeroClosed, SeasonEnded, GoalSet, GoalProgressed, GoalMet, GoalUndone,
TickOpened, TickClosed``, and for realism campaigns ``CardsDeclared,
DocumentIssued, DocumentWritten, OrderDrafted, OrderStepTaken, OrderSettled, QuantitySet,
FeatureSet, WarDeclared, MapDeclared, KindsDeclared, NewsReported, StanceChanged, OpponentsRanked,
CardAmended, AnswerPlanned, AnswerMade, AreaHeld, CaptureCounted, EconomySet, YieldChanged,
TradeSet, BattleOpened, BattleRound, BattleEnded, BattleDecided, IntelligenceDeclared,
ReportMade, AgentSet, CodebreakingSet, GroupsDeclared, GroupMoved, GroupProposed,
AgreementOffered, AgreementMade, ClauseJudged, AgreementPublished, ConferenceCalled,
VoteSealed, ConferenceTallied, LocksDeclared, LawsDeclared, OrderHeld, HeldOrderEnded,
OrderAsked, AskAnswered, MatterChosen, AimPatternsDeclared, OwnAimSet, OfferMade,
OfferSettled, LossesHeld``, and
under engine v2 ``OrderRouted, OrderExecuted,
EffectsEstimated, EffectsApplied, InfluenceDecided, MandateIssued, MandateSettled, WakeOpened,
WakeCommitted, WakeClosed, PlayStyleSet, SeatHandover, RequestAnswered, StepChosen``.

Every other kind is a record: it is replayable, searchable and shown by
``/why``, but changes no state.
"""

from datetime import date, datetime
from typing import Annotated, ClassVar, Literal

from pydantic import ConfigDict, Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.aim_patterns import AimPatterns, OwnAim
from revisionist.core.delta import Delta
from revisionist.core.goals import Goal, GoalKind, WinCondition
from revisionist.core.ids import (
    CampaignId,
    ClockId,
    ContestId,
    DeltaId,
    DocumentId,
    EntityId,
    EventId,
    FactId,
    FeatureId,
    GoalId,
    IntentId,
    MandateId,
    OrderId,
    ScheduledEventId,
    SeatId,
)
from revisionist.core.intent import Intent
from revisionist.core.ontology import (
    Asset,
    Character,
    Clock,
    Commitment,
    Contest,
    Controller,
    Entity,
    Fact,
    Meter,
    Persona,
    Relationship,
    ScheduledEvent,
    Seat,
    SeatStatus,
)
from revisionist.core.realism.agenda import (
    Mandate,
    MandateStatus,
    MandateTemplate,
    Offer,
    PlayStyle,
)
from revisionist.core.realism.agreement import Agreement, AgreementOffer, ClauseStatus
from revisionist.core.realism.answer import Answer
from revisionist.core.realism.battle import Battle, Decision, Ending
from revisionist.core.realism.card import (
    Address,
    ChannelKind,
    Conflict,
    ParamValue,
    SeatCard,
    Topic,
)
from revisionist.core.realism.conference import Conference, Tally, Vote
from revisionist.core.realism.detect import Agent, Intelligence, Report, Shift
from revisionist.core.realism.document import DocumentTruth, DocumentView, Feed
from revisionist.core.realism.economy import Amount, Pools
from revisionist.core.realism.effect import EffectKind, EstimatedEffect, Fidelity, RoutedOrder
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.groups import Cause as GroupCause
from revisionist.core.realism.groups import HeldLoss, KindClass, NationGroups, Place, Proposal
from revisionist.core.realism.holders import Capture
from revisionist.core.realism.kinds import PieceKind, Resource
from revisionist.core.realism.laws import Law
from revisionist.core.realism.locks import Asked, HeldEnd, HeldOrder, LockRow
from revisionist.core.realism.offers import OfferStanding, PricedOffer
from revisionist.core.realism.pipeline import (
    Order,
    OrderStatus,
    Pipeline,
    StepAction,
    StepOutcome,
)
from revisionist.core.realism.quantity import Quantity
from revisionist.core.realism.stance import Standing
from revisionist.core.realism.territory import StepCause, WorldMap
from revisionist.core.realism.trade import TradeLine
from revisionist.core.realism.war import NewsEvent, Outlet, War
from revisionist.core.resolution import FeasibilityBand, OutcomeTier, RejectionReason, TickStage
from revisionist.core.settings import Settings
from revisionist.core.state import Rule, Ruleset
from revisionist.core.visibility import Scope


class Versions(Model):
    engine: str
    schema_version: str
    prompt: str = ""
    model: str = ""


# --- Session Zero and world creation ----------------------------------------


class CampaignCreated(Model):
    kind: Literal["campaign_created"] = "campaign_created"
    name: str
    world: str
    """Name of the world bible this campaign was compiled from."""
    ruleset: Ruleset = "legacy"
    """Which rules resolve this campaign. Left out of a legacy log, so it hashes as before."""
    rules: frozenset[Rule] = frozenset()
    """The territory rules the world switches on. Left out when none, as in every stored log."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"ruleset", "rules"})


class SettingsSet(Model):
    kind: Literal["settings_set"] = "settings_set"
    settings: Settings


class EntityCreated(Model):
    kind: Literal["entity_created"] = "entity_created"
    entity: Entity


class AssetCreated(Model):
    kind: Literal["asset_created"] = "asset_created"
    asset: Asset


class RelationshipSet(Model):
    kind: Literal["relationship_set"] = "relationship_set"
    relationship: Relationship


class MeterCreated(Model):
    kind: Literal["meter_created"] = "meter_created"
    meter: Meter


class ClockCreated(Model):
    kind: Literal["clock_created"] = "clock_created"
    clock: Clock


class FactAsserted(Model):
    kind: Literal["fact_asserted"] = "fact_asserted"
    fact: Fact


class CommitmentCreated(Model):
    kind: Literal["commitment_created"] = "commitment_created"
    commitment: Commitment


class SeatCreated(Model):
    kind: Literal["seat_created"] = "seat_created"
    seat: Seat


class AgentAssigned(Model):
    kind: Literal["agent_assigned"] = "agent_assigned"
    seat_id: SeatId
    agent: EntityId
    persona: Persona


class SeatStatusSet(Model):
    kind: Literal["seat_status_set"] = "seat_status_set"
    seat_id: SeatId
    status: SeatStatus
    cause: str = Field(max_length=200)


# --- Orders and intents -------------------------------------------------------


class OrderReceived(Model):
    """Raw player text. Always Private to the seat. Encrypted at rest from Layer 9."""

    kind: Literal["order_received"] = "order_received"
    seat_id: SeatId
    text: str = Field(max_length=4000)


class IntentFiled(Model):
    kind: Literal["intent_filed"] = "intent_filed"
    intent: Intent
    from_order: EventId | None = None
    """``None`` when a deputy or faction filed it."""


class IntentRejected(Model):
    kind: Literal["intent_rejected"] = "intent_rejected"
    intent_id: IntentId
    reason: RejectionReason
    detail: str = Field(default="", max_length=200)


class ClarificationAsked(Model):
    kind: Literal["clarification_asked"] = "clarification_asked"
    seat_id: SeatId
    from_order: EventId
    question: str = Field(max_length=500)


# --- Resolution ---------------------------------------------------------------


class FeasibilityRated(Model):
    kind: Literal["feasibility_rated"] = "feasibility_rated"
    intent_id: IntentId
    band: FeasibilityBand
    perceived: FeasibilityBand
    """What the actor's own view would compute. Equal to ``band`` with full knowledge."""


class Rolled(Model):
    kind: Literal["rolled"] = "rolled"
    intent_id: IntentId
    seed: str
    """Hex of blake2b(campaign_id, tick, intent_id). Reproducible."""
    outcome: OutcomeTier
    exposure_roll: int = Field(ge=0, le=99)
    exposed: bool


class DeltaProposed(Model):
    kind: Literal["delta_proposed"] = "delta_proposed"
    intent_id: IntentId | None
    """``None`` for director and scheduled-event proposals."""
    deltas: tuple[Delta, ...]


class DeltaRejected(Model):
    kind: Literal["delta_rejected"] = "delta_rejected"
    delta_id: DeltaId
    reason: RejectionReason
    detail: str = Field(default="", max_length=200)


class DeltaApplied(Model):
    kind: Literal["delta_applied"] = "delta_applied"
    intent_id: IntentId | None
    delta: Delta


class OperationOpened(Model):
    kind: Literal["operation_opened"] = "operation_opened"
    intent_id: IntentId
    clock_id: ClockId
    seat_id: SeatId


class OperationResolved(Model):
    kind: Literal["operation_resolved"] = "operation_resolved"
    intent_id: IntentId
    clock_id: ClockId
    seat_id: SeatId
    outcome: OutcomeTier


class ScheduledEventFired(Model):
    kind: Literal["scheduled_event_fired"] = "scheduled_event_fired"
    scheduled_id: ScheduledEventId


# --- Narration and delivery ---------------------------------------------------


class NarrationWritten(Model):
    """Prose for exactly one seat, written from that seat's view."""

    kind: Literal["narration_written"] = "narration_written"
    seat_id: SeatId
    text: str
    from_deltas: tuple[DeltaId, ...] = ()


class StatementIssued(Model):
    """A player's spin, made public as the tick freezes (Layer 9b).

    Spin is the one free text a player addresses to the world (design §5), so
    it is logged Public whatever the order's own scope: a covert operation can
    come with a public denial. A record: it changes no state.
    """

    kind: Literal["statement_issued"] = "statement_issued"
    seat_id: SeatId
    intent_id: IntentId
    text: str = Field(max_length=280)


class BriefingDelivered(Model):
    kind: Literal["briefing_delivered"] = "briefing_delivered"
    seat_id: SeatId
    narration: EventId
    channel: str
    idempotency_key: str


class SessionZeroOpened(Model):
    """The table locked a point in history with ``/establish`` (spec §5 step 2).

    Ticks wait until Session Zero closes. ``notes`` is where the GM logs each
    reading it chose where historians disagree or the record is silent.
    """

    kind: Literal["session_zero_opened"] = "session_zero_opened"
    start: str = Field(max_length=80)
    notes: tuple[str, ...] = ()


class CharacterListed(Model):
    """One character on the Session Zero roster. Public: every player sees the roster."""

    kind: Literal["character_listed"] = "character_listed"
    character: Character


class CharacterClaimed(Model):
    """A player takes a character from the roster (spec §5 step 3).

    The fold creates the player's seat here, embodying the character. The
    engine gives this event an ID derived from the campaign and the character,
    so a second claim of the same person fails at the store, not just here.
    """

    kind: Literal["character_claimed"] = "character_claimed"
    seat_id: SeatId
    entity_id: EntityId


class CharacterReleased(Model):
    """A player gives up the character they claimed, before the game begins.

    Realism games only. The fold removes the player's seat and frees the
    character, so it can be claimed again. The engine derives this event's ID
    from the character and how many releases it has had, and each later claim's
    ID from the same count, so two players racing for a freed person still
    cannot both land.
    """

    kind: Literal["character_released"] = "character_released"
    seat_id: SeatId
    entity_id: EntityId


class SessionZeroClosed(Model):
    """Every player has a character, a goal and an agent: play begins."""

    kind: Literal["session_zero_closed"] = "session_zero_closed"


class SeasonEnded(Model):
    """The season is over and its winners decided (spec §15, decision 36).

    Logged right after the full reveal's grants, ``revealed`` of them, and it
    makes every goal public. ``winners`` is whatever ``season_winners`` says;
    the fold checks it, so a log cannot crown anyone the engine did not.
    """

    kind: Literal["season_ended"] = "season_ended"
    winners: tuple[SeatId, ...]
    revealed: int = Field(ge=0)


# --- Goals ---------------------------------------------------------------------


class GoalSet(Model):
    """A seat's secret goal, fixed at Session Zero (spec §15). Private to the owner."""

    kind: Literal["goal_set"] = "goal_set"
    goal: Goal


class GoalProgressed(Model):
    """The goal's objective clock moved: ``parts_met`` of its parts hold now."""

    kind: Literal["goal_progressed"] = "goal_progressed"
    goal_id: GoalId
    parts_met: int = Field(ge=0)


class GoalMet(Model):
    """The goal's condition holds at the end of this tick, first time or again."""

    kind: Literal["goal_met"] = "goal_met"
    goal_id: GoalId


class GoalUndone(Model):
    """An Undoable goal stopped holding. It counts as unmet until it holds again."""

    kind: Literal["goal_undone"] = "goal_undone"
    goal_id: GoalId


class GoalOption(Model):
    text: str = Field(max_length=280)
    condition: WinCondition
    kind: GoalKind


class GoalProposed(Model):
    """The goals a player's agent offered on one route (spec §5 step 4). A record,
    Private to the seat and sealed with its key: these are the player's own words."""

    kind: Literal["goal_proposed"] = "goal_proposed"
    seat_id: SeatId
    route: Literal["history", "could_have", "own"]
    options: tuple[GoalOption, ...] = Field(max_length=3)


class GoalApproved(Model):
    """The host let a goal the balance check flagged stand. The host sees the scores
    and the flag, never the goal. A record."""

    kind: Literal["goal_approved"] = "goal_approved"
    goal_id: GoalId


# --- Tick lifecycle -----------------------------------------------------------


# --- Contests and history's clock (spec §5.3-5.4) --------------------------


class ContestCreated(Model):
    kind: Literal["contest_created"] = "contest_created"
    contest: Contest


class ContestMoved(Model):
    """A contest's track moved, by momentum, by a resolved order, or by one of its own
    moves landing (CON: ``move``, the move's index, once), and its countdown ran down by
    the in-world days the tick covered (none for a move)."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"move"})

    kind: Literal["contest_moved"] = "contest_moved"
    contest_id: ContestId
    change: int = Field(ge=-200, le=200)
    days: int = Field(default=0, ge=0)
    cause: Literal["momentum", "order", "move"] = "momentum"
    move: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _shape(self) -> "ContestMoved":
        if (self.cause == "move") != (self.move is not None):
            raise ValueError("contest_moved: a move's index goes with the cause move")
        return self


class ContestDecided(Model):
    """The countdown reached zero; the track decided it. ``winner`` None is a draw
    or a failed trial. The world keeps running."""

    kind: Literal["contest_decided"] = "contest_decided"
    contest_id: ContestId
    winner: EntityId | None = None


class ScheduledEventCreated(Model):
    """An item on history's clock, written by the world draft."""

    kind: Literal["scheduled_event_created"] = "scheduled_event_created"
    scheduled: ScheduledEvent


class ScheduledEventSkipped(Model):
    """A history event came due but its condition no longer held."""

    kind: Literal["scheduled_event_skipped"] = "scheduled_event_skipped"
    scheduled_id: ScheduledEventId


class DivergenceChanged(Model):
    kind: Literal["divergence_changed"] = "divergence_changed"
    change: int = Field(ge=-100, le=100)
    reason: str = Field(max_length=200)


class DateAdvanced(Model):
    """The calendar moved today's in-world date (spec §5.7)."""

    kind: Literal["date_advanced"] = "date_advanced"
    to: date


class TickOpened(Model):
    kind: Literal["tick_opened"] = "tick_opened"
    intents_frozen: tuple[IntentId, ...]


class CallCost(Model):
    call_class: str
    """resolver | narrator | structurer | persona | press | director | prose | counsel | aide
    | estimator."""
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    usd: float = Field(ge=0)


class TickStageCompleted(Model):
    kind: Literal["tick_stage_completed"] = "tick_stage_completed"
    stage: TickStage
    costs: tuple[CallCost, ...] = ()
    """Model calls made during the stage. ``tick_closed`` sums them."""


class TickClosed(Model):
    kind: Literal["tick_closed"] = "tick_closed"
    quiet: bool = False
    """True when the resolver failed and intents carried forward."""
    quiet_reason: str = Field(default="", max_length=200)
    costs: tuple[CallCost, ...] = ()
    state_hash: str
    """blake2b of the canonical state JSON after this tick. Replay must match."""


class CostLogged(Model):
    """Model calls made outside a tick (structuring an order, a briefing, a deputy turn).

    Tick costs live on ``tick_closed``; everything else lands here so ``revisionist cost``
    can account for every call. A record kind: it changes no state.
    """

    kind: Literal["cost_logged"] = "cost_logged"
    seat_id: SeatId | None = None
    purpose: str = Field(max_length=60)
    costs: tuple[CallCost, ...]


# --- Realism (core/realism) ---------------------------------------------------


class CardsDeclared(Model):
    """The scenario's cards, feeds and pipelines, compiled from the world file.

    One event, after the entities it names, so the fold can check every
    reference at once. Engine only: cards carry the AI policy fields.
    """

    kind: Literal["cards_declared"] = "cards_declared"
    cards: tuple[SeatCard, ...] = ()
    feeds: tuple[Feed, ...] = ()
    pipelines: tuple[Pipeline, ...] = ()
    templates: tuple[MandateTemplate, ...] = ()
    """Engine v2: the mandates the world issues when their triggers fire."""
    outlets: tuple[Outlet, ...] = ()
    """Each polity's newspaper, for the press to word public news in."""
    topics: tuple[Topic, ...] = ()
    """What people want and hold to, for the cards to name."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"templates", "outlets", "topics"})


class DocumentIssued(Model):
    """A document is written. Its envelope scope is the view's; seats see it on arrival."""

    kind: Literal["document_issued"] = "document_issued"
    document: DocumentView
    truth: DocumentTruth


class DocumentWritten(Model):
    """The prose model wrote a document's page from its view and its author's voice.

    Scoped like the document. Folded into the view; a document is written at most
    once, so a resumed tick cannot write it twice."""

    kind: Literal["document_written"] = "document_written"
    doc_id: DocumentId
    prose: str = Field(min_length=1, max_length=4000)


class DocumentRead(Model):
    """A seat opened a document (the in-tray's unread mark). A record."""

    kind: Literal["document_read"] = "document_read"
    seat_id: SeatId
    doc_id: DocumentId


class DocumentFlagged(Model):
    """A seat flagged a document, or took the flag off. A record; the latest event wins."""

    kind: Literal["document_flagged"] = "document_flagged"
    seat_id: SeatId
    doc_id: DocumentId
    flagged: bool


class OrderDrafted(Model):
    """A seat pulled a lever: the order enters its pipeline at step 0."""

    kind: Literal["order_drafted"] = "order_drafted"
    order: Order


class OrderStepTaken(Model):
    """The person at the order's current step acted on it."""

    kind: Literal["order_step_taken"] = "order_step_taken"
    order_id: OrderId
    outcome: StepOutcome


class OrderSettled(Model):
    """The order left its pipeline: enacted, refused, lapsed or withdrawn."""

    kind: Literal["order_settled"] = "order_settled"
    order_id: OrderId
    status: OrderStatus


class QuantitySet(Model):
    """A quantity's value as of a date: authored at compile, computed by a resolver after."""

    kind: Literal["quantity_set"] = "quantity_set"
    quantity: Quantity


class FeatureSet(Model):
    """A force, front or route as it stands: authored at compile, moved by the
    movement resolver after. Engine only, like a quantity."""

    kind: Literal["feature_set"] = "feature_set"
    feature: Feature


class WarDeclared(Model):
    """Two polities are at war. Public."""

    kind: Literal["war_declared"] = "war_declared"
    war: War


class MapDeclared(Model):
    """The board the world file defines: areas, regions, terrain and adjacency, with
    the map file's name and hash, never its shapes. Public; once, at creation."""

    kind: Literal["map_declared"] = "map_declared"
    map: WorldMap


class KindsDeclared(Model):
    """The world's own piece kinds and resources, in the world file's order. Public; once,
    at creation, before any feature is set."""

    kind: Literal["kinds_declared"] = "kinds_declared"
    pieces: tuple[PieceKind, ...] = ()
    resources: tuple[Resource, ...] = ()


class LocksDeclared(Model):
    """The world's locks (DCD): which order, under which condition, needs which decision,
    from whom, in the world file's order. World data; once, at creation, with ``locks``
    on."""

    kind: Literal["locks_declared"] = "locks_declared"
    rows: tuple[LockRow, ...] = Field(min_length=1)


class LawsDeclared(Model):
    """The world's laws (LWC): what each binds, its clauses, the quantity that says it has
    passed, and what it does, in the world file's order. World data; once, at creation,
    with ``laws`` on."""

    kind: Literal["laws_declared"] = "laws_declared"
    laws: tuple[Law, ...] = Field(min_length=1)


class AimPatternsDeclared(Model):
    """The world's aim patterns and each card's kind of post (OWC). World data; once, at
    creation, with ``own_aim`` on. Public."""

    kind: Literal["aim_patterns_declared"] = "aim_patterns_declared"
    patterns: AimPatterns


class OwnAimSet(Model):
    """A player's own aim, filled from a pattern, stored for the person he holds in place
    of the card's replaceable aim (OWC). Sealed to the seat holding the person."""

    kind: Literal["own_aim_set"] = "own_aim_set"
    own: OwnAim


class OrderHeld(Model):
    """A lock holds a seat's order (LCK): it passed every refusal of today's and is
    stored, not carried out, with the row and the decider. Sealed to the issuer's seat;
    no clock ends it."""

    kind: Literal["order_held"] = "order_held"
    held: HeldOrder


class HeldOrderEnded(Model):
    """A held order ends (LCK): replaced by a later order from its seat to the same force
    and zone, landed, failed its re-check, or withdrawn. Sealed to the issuer's seat."""

    kind: Literal["held_order_ended"] = "held_order_ended"
    order_id: OrderId
    issuer: SeatId
    end: HeldEnd
    on: date
    by: OrderId | None = None
    """For a replacement, the later order; for a landing, the order it landed as."""
    reason: str = Field(default="", max_length=300)
    """For a failure, the words its seat is told."""

    @model_validator(mode="after")
    def _shape(self) -> "HeldOrderEnded":
        if (self.by is not None) != (self.end in (HeldEnd.REPLACED, HeldEnd.LANDED)):
            raise ValueError("a replacement or a landing, and only those, name the order")
        if bool(self.reason) != (self.end is HeldEnd.FAILED):
            raise ValueError("a failure, and only a failure, carries its reason")
        return self


class OrderAsked(Model):
    """A seat asks, once, for its held order (ASK): one paper before the seat holding the
    person who decides it, or the card when no seat does. Sealed to the asker and that
    seat. It decides nothing and opens nothing."""

    kind: Literal["order_asked"] = "order_asked"
    asked: Asked


class AskAnswered(Model):
    """The card of a person no human seat holds answers an ask on its due day (AAK):
    granted or declined, once, and final for that held order. Sealed to the asker's seat,
    which it tells in one paper. A grant opens nothing itself: the person's own order
    does, once it is enacted."""

    kind: Literal["ask_answered"] = "ask_answered"
    order_id: OrderId
    """The held order asked for."""
    asker: SeatId
    on: date
    granted: bool


class MatterChosen(Model):
    """A seat's sealed choice on a matter before it (QKD): to accept or decline the ask
    for a held order, put to a council it sits on or to the person it holds. A later
    choice before the due day replaces it. Sealed to the seat that chose: nobody else
    learns of it, not even that it was made, and the due day counts it without saying
    who agreed."""

    kind: Literal["matter_chosen"] = "matter_chosen"
    order_id: OrderId
    seat_id: SeatId
    accept: bool
    on: date


class OfferMade(Model):
    """A seat offers one price to one bloc of its own nation for one measure whose bill is
    on its way (PRC). It waits for the next day's batch, which takes or refuses it by
    content. Sealed to the seats of the bloc's nation."""

    kind: Literal["offer_made"] = "offer_made"
    offer: PricedOffer


class OfferSettled(Model):
    """Where an offer now stands (PRC): taken or refused by its day's batch, lapsed when
    its measure did not pass, due once it passed, then kept or broken on its due day.
    Sealed to the seats of the bloc's nation."""

    kind: Literal["offer_settled"] = "offer_settled"
    offer_id: Label
    standing: OfferStanding
    on: date
    due: date | None = None
    """The day the promise is read: on ``due``, ``kept`` and ``broken``."""

    @model_validator(mode="after")
    def _shape(self) -> "OfferSettled":
        if self.standing is OfferStanding.FILED:
            raise ValueError("an offer is filed only by offer_made")
        owed = self.standing in (OfferStanding.DUE, OfferStanding.KEPT, OfferStanding.BROKEN)
        if (self.due is not None) != owed:
            raise ValueError("a due day goes with due, kept and broken only")
        return self


class PieceStepped(Model):
    """A piece entered an area: one step, by order, by the record, or forced. Sealed to the
    seats of the piece's own nation, who know it by its mark (``territory.mark_key``), not
    its id. The ``feature_set`` beside it moves the piece; with ``places`` on, a step out
    of a weighted place is kept as the day the nation's piece left it (PLW)."""

    kind: Literal["piece_stepped"] = "piece_stepped"
    mark: Label
    nation: EntityId
    """The piece's nation, whose seats alone hold the event."""
    left: EntityId
    entered: EntityId
    on: date
    cause: StepCause


class AreaHeld(Model):
    """A territory changed hands (THL): its new holder, the one it was taken from, and the
    day. Public: holders are public."""

    kind: Literal["area_held"] = "area_held"
    area: EntityId
    holder: EntityId
    was: EntityId | None = None
    on: date


class CaptureCounted(Model):
    """A territory's capture count or capital mark as it stands at the end of a day in the
    walk (THL); None when it has neither. Engine only: it says where pieces stand."""

    kind: Literal["capture_counted"] = "capture_counted"
    area: EntityId
    capture: Capture | None = None


class EconomySet(Model):
    """A nation's pools after the first-of-the-month payment (YLD). Sealed to the nation's
    seats: true figures."""

    kind: Literal["economy_set"] = "economy_set"
    polity: EntityId
    pools: Pools
    on: date


class YieldChanged(Model):
    """Part of a territory's yield moved to another territory of the same holder (YLD).
    Sealed to the holder's seats: true figures."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"restart"})

    kind: Literal["yield_changed"] = "yield_changed"
    area: EntityId
    to: EntityId
    resource: Label
    amount: Amount
    on: date
    restart: date | None = None
    """The day the moved part starts to pay where it now lies (RSD); None, as in every
    move stored before it: at once."""


class TradeSet(Model):
    """A trade line as it stands from ``on`` (FUL): declared by the world, or opened or cut
    by ``trade.set``. Sealed to the seats of the two nations it joins: true figures."""

    kind: Literal["trade_set"] = "trade_set"
    line: TradeLine
    on: date


class StepRefused(Model):
    """A piece's step was refused as it was to start, and the piece holds where it stands
    (FUL: too little fuel). A record: the ``feature_set`` beside it halts the piece.
    Sealed to the seats of the piece's own nation, who know it by its mark."""

    kind: Literal["step_refused"] = "step_refused"
    mark: Label
    nation: EntityId
    area: EntityId
    """Where the piece holds."""
    to: EntityId
    """The area the refused step would have entered."""
    on: date
    reason: str = Field(max_length=300)


class BattleOpened(Model):
    """A battle opened in an area (BTL): its two sides, the pieces and the strength each
    brought. Engine only: it carries both sides' true strengths."""

    kind: Literal["battle_opened"] = "battle_opened"
    battle: Battle
    on: date


class BattleRound(Model):
    """One day's round of a battle (BTL): each side's score and draw, attacker first, and
    the steps each lost. Engine only. The ``feature_set`` beside it sets the pieces."""

    kind: Literal["battle_round"] = "battle_round"
    area: EntityId
    on: date
    scores: tuple[int, int]
    draws: tuple[int, int]
    lost: tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)]]


class BattleEnded(Model):
    """A battle ended (BTL): how, and the nation left with the field. Engine only; the
    news item beside it is public."""

    kind: Literal["battle_ended"] = "battle_ended"
    area: EntityId
    on: date
    ending: Ending
    winner: EntityId


class BattleDecided(Model):
    """A side's decision for a battle, or pieces that joined it (BDC). With ``decision``,
    the side's decision in force from ``on``, given in wake ``wake``; with ``joined``, the
    pieces that stepped in and joined the side, bringing ``added`` strength. Engine only:
    a seat's own order is fed to it already, and a join carries the true strength."""

    kind: Literal["battle_decided"] = "battle_decided"
    area: EntityId
    nation: EntityId
    """The side, by its leading nation."""
    on: date
    decision: Decision | None = None
    wake: int | None = Field(default=None, ge=0)
    joined: tuple[FeatureId, ...] = ()
    added: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _shape(self) -> "BattleDecided":
        if (self.decision is None) != (self.wake is None):
            raise ValueError("battle_decided: a decision and its wake go together")
        if self.decision is None and not self.joined:
            raise ValueError("battle_decided: a decision, or pieces that join")
        if bool(self.joined) != (self.added > 0):
            raise ValueError("battle_decided: pieces that join bring strength")
        if len(set(self.joined)) != len(self.joined):
            raise ValueError("battle_decided: a piece joins once")
        return self


class IntelligenceDeclared(Model):
    """Each nation's sources as the world declares them (DET): who reports each source and
    by what channel, the codebreaking level, and the agents by area. Engine only; once, at
    creation."""

    kind: Literal["intelligence_declared"] = "intelligence_declared"
    nations: tuple[Intelligence, ...] = ()


class ReportMade(Model):
    """A nation's source reported an enemy piece (DET). Engine only: it names the true
    piece and records whether the report is wrong (``shift``); a seat gets the report in
    its view once it arrives, and as a line of its source's page."""

    kind: Literal["report_made"] = "report_made"
    nation: EntityId
    piece: FeatureId
    report: Report
    shift: Shift | None = None


class AgentSet(Model):
    """A nation's agent placed (``index`` one past its last) or lost (IOR). Engine only:
    it says where the nation has an agent; the holder of an area where one is lost learns
    of it from its paper."""

    kind: Literal["agent_set"] = "agent_set"
    nation: EntityId
    index: int = Field(ge=0)
    agent: Agent


class CodebreakingSet(Model):
    """A nation's codebreaking level raised by one, from ``on`` (IOR). Engine only."""

    kind: Literal["codebreaking_set"] = "codebreaking_set"
    nation: EntityId
    level: int = Field(ge=1, le=3)
    on: date


class GroupsDeclared(Model):
    """Each nation's groups at home as the world declares them (GRP), by nation, in the
    world file's order. Engine only: a seat reads its own nation's groups from its own
    data; once, at creation."""

    kind: Literal["groups_declared"] = "groups_declared"
    nations: tuple[NationGroups, ...] = ()
    classes: tuple[KindClass, ...] = ()
    """With ``classes`` on, the class the world gives each kind of happening it classes
    (HCL), in the world file's order."""
    places: tuple[Place, ...] = ()
    """With ``places`` on, the places with political weight (PLW), in the world file's
    order."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"classes", "places"})


class GroupMoved(Model):
    """A nation's group's support moved (GRP): to ``support``, by ``change`` after the
    clamp to 0 to 100, for ``cause``, on world day ``on``. ``used``: the writing points
    the day's batch spent toward the week cap (absolute, never restored); 0 for any other
    cause. Sealed to the nation's seats: true support."""

    kind: Literal["group_moved"] = "group_moved"
    polity: EntityId
    group: Label
    support: int = Field(ge=0, le=100)
    change: int
    cause: GroupCause
    used: int = Field(default=0, ge=0)
    on: date


class LossesHeld(Model):
    """Battle losses held at home (LSS): each one day's losses of a nation in one battle as
    they move one of its groups, added or replaced (the felt share halved, or the battle
    ended). Entries whose battle has ended and whose felt share has landed by ``on`` are
    dropped. Engine only: it carries the nation's steps lost by the points they move."""

    kind: Literal["losses_held"] = "losses_held"
    on: date
    held: tuple[HeldLoss, ...] = Field(min_length=1)


class GroupProposed(Model):
    """Writing by a seat proposing to move a group, waiting for its day's batch (GRP).
    Engine only: the batch, not the filing, decides what moves."""

    kind: Literal["group_proposed"] = "group_proposed"
    proposal: Proposal


class AgreementOffered(Model):
    """An offer of an agreement filed, as its parties know it (AGR). Sealed to the seats of
    its parties' nations."""

    kind: Literal["agreement_offered"] = "agreement_offered"
    offer: AgreementOffer


class AgreementMade(Model):
    """An agreement in force, in full (AGR): every named nation accepted the same version
    of an offer, or a world or a conference made it. Sealed to the seats of its parties'
    nations."""

    kind: Literal["agreement_made"] = "agreement_made"
    agreement: Agreement


class ClauseJudged(Model):
    """A clause of an agreement judged on ``on`` from the state (AGR): kept, broken, or
    called on by an attack on ``against`` with war due by ``due``. With ``against`` and
    ``kept``, the call on that attacker is answered. Sealed to the parties' seats until the
    agreement is published."""

    kind: Literal["clause_judged"] = "clause_judged"
    agreement_id: Label
    clause: int = Field(ge=0)
    status: ClauseStatus
    on: date
    reason: str = Field(default="", max_length=300)
    against: EntityId | None = None
    due: date | None = None


class AgreementPublished(Model):
    """A party published an agreement by order (AGR). Public."""

    kind: Literal["agreement_published"] = "agreement_published"
    agreement_id: Label
    by: EntityId
    on: date


class ConferenceCalled(Model):
    """A conference called by a seat, or a world's conference scheduled (at compile,
    sealed to no seat) and opened on its day (CNF). Sealed to the invited nations' seats,
    or public when the conference is."""

    kind: Literal["conference_called"] = "conference_called"
    conference: Conference


class VoteSealed(Model):
    """A seat's sealed vote in a conference, in the wake it was sealed in; a later one in
    the same wake replaces it (CNF). Sealed to the voter: nobody else learns of it, not
    even that it was filed, until the tally counts its nation."""

    kind: Literal["vote_sealed"] = "vote_sealed"
    conference: Label
    seat_id: SeatId
    vote: Vote
    wake: int = Field(ge=0)


class ConferenceTallied(Model):
    """A conference's tally on its voting day: each invited nation's counted vote and the
    outcome (CNF). Scoped as its call. Never says how a seat was run."""

    kind: Literal["conference_tallied"] = "conference_tallied"
    conference: Label
    tally: Tally


class NewsReported(Model):
    """A public event, as structured facts. Each seat's press words it later."""

    kind: Literal["news_reported"] = "news_reported"
    news: NewsEvent


class StanceChanged(Model):
    """A person nobody plays took a new stance toward a seat. Engine only: the seat
    is shown the stance as its staff last had evidence for it."""

    kind: Literal["stance_changed"] = "stance_changed"
    seat_id: SeatId
    figure: EntityId
    standing: Standing


class OpponentsRanked(Model):
    """The people actively opposing a seat, as the truth has it. Engine only."""

    kind: Literal["opponents_ranked"] = "opponents_ranked"
    seat_id: SeatId
    active: tuple[EntityId, ...] = Field(max_length=4)


class CardAmended(Model):
    """A game takes the world file's word on who a person stands with and against, how
    they answer, how they write and how they are addressed, replacing what its card held.
    Engine only: these are AI policy. ``voice`` or ``addressed_as`` None leaves the card's
    value as it was."""

    kind: Literal["card_amended"] = "card_amended"
    person: EntityId
    allies: tuple[EntityId, ...] = ()
    opposes: tuple[Conflict, ...] = Field(default=(), max_length=6)
    answers: tuple[Answer, ...] = Field(default=(), max_length=8)
    voice: str | None = Field(default=None, max_length=200)
    addressed_as: Address | None = None

    late_fields: ClassVar[frozenset[str]] = frozenset({"voice", "addressed_as"})


class AnswerPlanned(Model):
    """A person nobody plays took up one of their answers, to act on ``due``. Engine only."""

    kind: Literal["answer_planned"] = "answer_planned"
    figure: EntityId
    key: Label
    on: date
    due: date
    cause: OrderId | None = None
    toward: EntityId | None = None

    @model_validator(mode="after")
    def _after(self) -> "AnswerPlanned":
        if self.due < self.on:
            raise ValueError("an answer falls due on or after the day it is taken up")
        return self


class AnswerMade(Model):
    """The answer fell due: the order it filed, the approach it put to a player, or why
    there was neither. Engine only."""

    kind: Literal["answer_made"] = "answer_made"
    figure: EntityId
    key: Label
    on: date
    order: OrderId | None = None
    mandate: MandateId | None = None
    refusal: Label = ""

    @model_validator(mode="after")
    def _one(self) -> "AnswerMade":
        if sum((self.order is not None, self.mandate is not None, bool(self.refusal))) != 1:
            raise ValueError("an answer is made as one of an order, an approach, a refusal")
        return self


class CounselHeld(Model):
    """A seat consulted a person on its card. The words are prose and change nothing;
    a record, sealed with the seat's key like an order's text."""

    kind: Literal["counsel_held"] = "counsel_held"
    seat_id: SeatId
    person: EntityId
    channel: ChannelKind
    text: str = Field(max_length=8000)


class DirectiveGiven(Model):
    """A seat signed a directive: its own words to a contact, and the order the aide
    read them as, filed in the same batch. A record, sealed with the seat's key."""

    kind: Literal["directive_given"] = "directive_given"
    seat_id: SeatId
    person: EntityId
    channel: ChannelKind
    text: str = Field(max_length=1000)
    order_id: OrderId
    lever: Label
    params: dict[Label, ParamValue] = Field(default_factory=dict)


# --- Engine v2 (spec §4, §8) ------------------------------------------------------


class OrderRouted(Model):
    """A committed order, split into parts and each part routed (spec §8.2).

    Scoped to the issuer. A replay reads the routes from here; it never routes again."""

    kind: Literal["order_routed"] = "order_routed"
    order: RoutedOrder


class OrderExecuted(Model):
    """An executor carried out a command part, with a fidelity, or refused it under
    a stated rule (spec §8.2). Scoped to the issuer."""

    kind: Literal["order_executed"] = "order_executed"
    order_id: OrderId
    part: int = Field(ge=0, le=7)
    on: date
    fidelity: Fidelity | None = None
    refusal: Label = ""

    @model_validator(mode="after")
    def _one(self) -> "OrderExecuted":
        if (self.fidelity is None) == (not self.refusal):
            raise ValueError("an executor carries a part out or refuses it")
        return self


class EffectsEstimated(Model):
    """The estimator's ruling on one part no code rule covers (spec §8.3).

    The effects are engine-only; ``reason`` is the issuer's, written from its view
    and leak-scanned. ``rationale`` is sealed for the end-of-game reveal. A replay
    reads this event and never calls the model. ``failed``: the model gave nothing
    usable, the part stays unresolved, and the paper says so."""

    kind: Literal["effects_estimated"] = "effects_estimated"
    order_id: OrderId
    part: int = Field(ge=0, le=7)
    effects: tuple[EstimatedEffect, ...] = Field(default=(), max_length=8)
    reason: str = Field(default="", max_length=600)
    rationale: str = Field(default="", max_length=2000)
    failed: bool = False

    @model_validator(mode="after")
    def _shape(self) -> "EffectsEstimated":
        if self.failed and (self.effects or self.rationale):
            raise ValueError("a failed estimate carries no effects")
        if not self.failed and not self.reason:
            raise ValueError("an estimate states its reason")
        return self


class EffectsApplied(Model):
    """A part's effects landed in the world (spec §8.2-8.3): an executed command, an
    estimate, or a decided influence. A refusal applies nothing but still closes the
    part. ``revealed`` facts become public. Scoped to the issuer."""

    kind: Literal["effects_applied"] = "effects_applied"
    order_id: OrderId
    part: int = Field(ge=0, le=7)
    on: date
    revealed: tuple[FactId, ...] = ()


class InfluenceDecided(Model):
    """The person an influence part was aimed at decided, under their card's policy
    (spec §8.2). ``reason`` is read by the issuer and leak-scanned. Scoped to the issuer."""

    kind: Literal["influence_decided"] = "influence_decided"
    order_id: OrderId
    part: int = Field(ge=0, le=7)
    on: date
    accepted: bool
    reason: str = Field(default="", max_length=300)


class RequestAnswered(Model):
    """The holder of a person another seat asked something of gives their answer (ANS).
    The fold keeps it on the part, engine side, and the request's due-day pass decides
    with it in the card's place, so the issuer learns nothing before that day and the
    decision reads the same as the card's. Given again, the later answer stands. Scoped
    to the holder."""

    kind: Literal["request_answered"] = "request_answered"
    order_id: OrderId
    part: int = Field(ge=0, le=7)
    accepted: bool


class StepChosen(Model):
    """The holder of a decision step on another seat's order chooses what to do there.
    The fold keeps it on the order, engine side, and on the step's held due day the
    runner takes the step with it in the card's place, so the issuer learns nothing
    before that day and the step reads the same as the card's. Chosen again, the later
    choice stands. Scoped to the holder."""

    kind: Literal["step_chosen"] = "step_chosen"
    order_id: OrderId
    step: int = Field(ge=0)
    action: StepAction
    amended: dict[Label, ParamValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _amend_has_edits(self) -> "StepChosen":
        if (self.action is StepAction.AMEND) != bool(self.amended):
            raise ValueError("an amendment, and only an amendment, edits parameters")
        return self


class MandateIssued(Model):
    """A mandate lands on a seat's agenda (spec §8.5). Scoped to the seat."""

    kind: Literal["mandate_issued"] = "mandate_issued"
    mandate: Mandate


class MandateSettled(Model):
    kind: Literal["mandate_settled"] = "mandate_settled"
    mandate_id: MandateId
    status: MandateStatus

    @model_validator(mode="after")
    def _settles(self) -> "MandateSettled":
        if self.status is MandateStatus.LIVE:
            raise ValueError("a mandate settles met, failed or expired")
        return self


class WakeOpened(Model):
    """A shared wake opens for the table (spec §4). Public."""

    kind: Literal["wake_opened"] = "wake_opened"
    wake: int = Field(ge=0)
    deadline: datetime
    """Real time. The wake closes at commit-of-all or here, whichever comes first."""
    opened_at: datetime | None = None
    """Real time it opened. None in a wake logged before the record had it."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"opened_at"})


class WakeCommitted(Model):
    """A seat sealed its orders for the wake. Public that it committed, never what.

    The aide's commit for an absent seat is sealed to that seat: it names the orders
    the aide filed, which no other seat may learn."""

    kind: Literal["wake_committed"] = "wake_committed"
    wake: int = Field(ge=0)
    seat_id: SeatId
    by_aide: bool = False
    """The seat had not committed by the deadline; its aide played it."""
    at: datetime | None = None
    """Real time of the commit. None in a commit logged before the record had it."""
    aide_orders: tuple[OrderId, ...] = ()
    """The orders the aide filed for the seat, in filing order. Empty for a person's commit."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"at", "aide_orders"})


WakeCloseHow = Literal["all_committed", "deadline", "host"]
"""How a wake closed: every human had committed; its deadline had passed; the host
closed it early with a seat still out."""


class WakeClosed(Model):
    kind: Literal["wake_closed"] = "wake_closed"
    wake: int = Field(ge=0)
    timed_out: tuple[SeatId, ...] = ()
    """Human seats the aide played."""
    how: WakeCloseHow | None = None
    """None in a close logged before the record had it."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"how"})


class PlayStyleSet(Model):
    """A seat's play style (spec §8.6). Sealed to the seat; shown at the reveal."""

    kind: Literal["play_style_set"] = "play_style_set"
    seat_id: SeatId
    style: PlayStyle
    standing: frozenset[EffectKind] = frozenset()
    """Standing orders: the irreversible kinds the aide may order while the seat is absent."""


class SeatHandover(Model):
    """A leader changes hands at the next wake boundary: ``HUMAN`` when a new player
    takes up a leader nobody plays, ``AI`` when the leader's player leaves. The fold holds
    the change in ``State.handovers`` and applies it when the open wake closes. Sealed to
    the seat that changes hands: how a seat is run is never shown."""

    kind: Literal["seat_handover"] = "seat_handover"
    entity_id: EntityId
    controller: Controller


class OptionsOffered(Model):
    """What the option generator offered a seat this wake. A record, sealed to the seat."""

    kind: Literal["options_offered"] = "options_offered"
    seat_id: SeatId
    wake: int = Field(ge=0)
    offers: tuple[Offer, ...] = Field(max_length=4)


# --- Admin --------------------------------------------------------------------


class AdminRead(Model):
    kind: Literal["admin_read"] = "admin_read"
    actor: str
    """Admin identity, not a seat."""
    events: tuple[EventId, ...]
    purpose: str = Field(max_length=200)


# --- At rest -------------------------------------------------------------------


class Sealed(Model):
    """What a sealed event looks like at rest (Layer 9b): the real event, whole,
    is encrypted into the envelope's ``payload_enc``.

    The store unseals on read, so the tick, the fold and every reader see the
    plaintext event. A ``seat``-held event whose key was destroyed (erasure)
    stays sealed: it is prose the fold never needed. A ``campaign``-held one
    that reaches the fold is an error: its key is missing.
    """

    kind: Literal["sealed"] = "sealed"
    key_id: str = Field(max_length=64)
    holder: Literal["campaign", "seat"]


Payload = Annotated[
    CampaignCreated
    | SettingsSet
    | EntityCreated
    | AssetCreated
    | RelationshipSet
    | MeterCreated
    | ClockCreated
    | FactAsserted
    | CommitmentCreated
    | SeatCreated
    | AgentAssigned
    | SeatStatusSet
    | OrderReceived
    | IntentFiled
    | IntentRejected
    | ClarificationAsked
    | FeasibilityRated
    | Rolled
    | DeltaProposed
    | DeltaRejected
    | DeltaApplied
    | OperationOpened
    | OperationResolved
    | ScheduledEventFired
    | ContestCreated
    | ContestMoved
    | ContestDecided
    | ScheduledEventCreated
    | ScheduledEventSkipped
    | DivergenceChanged
    | DateAdvanced
    | NarrationWritten
    | StatementIssued
    | SessionZeroOpened
    | CharacterListed
    | CharacterClaimed
    | CharacterReleased
    | SessionZeroClosed
    | SeasonEnded
    | GoalSet
    | GoalProgressed
    | GoalMet
    | GoalUndone
    | GoalProposed
    | GoalApproved
    | BriefingDelivered
    | TickOpened
    | TickStageCompleted
    | TickClosed
    | CostLogged
    | AdminRead
    | CardsDeclared
    | DocumentIssued
    | DocumentWritten
    | DocumentRead
    | DocumentFlagged
    | OrderDrafted
    | OrderStepTaken
    | OrderSettled
    | QuantitySet
    | FeatureSet
    | WarDeclared
    | MapDeclared
    | KindsDeclared
    | LocksDeclared
    | LawsDeclared
    | AimPatternsDeclared
    | OwnAimSet
    | OrderHeld
    | HeldOrderEnded
    | OrderAsked
    | AskAnswered
    | MatterChosen
    | OfferMade
    | OfferSettled
    | PieceStepped
    | AreaHeld
    | CaptureCounted
    | EconomySet
    | YieldChanged
    | TradeSet
    | StepRefused
    | BattleOpened
    | BattleRound
    | BattleEnded
    | BattleDecided
    | IntelligenceDeclared
    | ReportMade
    | AgentSet
    | CodebreakingSet
    | GroupsDeclared
    | GroupMoved
    | GroupProposed
    | LossesHeld
    | AgreementOffered
    | AgreementMade
    | ClauseJudged
    | AgreementPublished
    | ConferenceCalled
    | VoteSealed
    | ConferenceTallied
    | NewsReported
    | StanceChanged
    | OpponentsRanked
    | CardAmended
    | AnswerPlanned
    | AnswerMade
    | CounselHeld
    | DirectiveGiven
    | OrderRouted
    | OrderExecuted
    | EffectsEstimated
    | EffectsApplied
    | InfluenceDecided
    | MandateIssued
    | MandateSettled
    | WakeOpened
    | WakeCommitted
    | WakeClosed
    | PlayStyleSet
    | SeatHandover
    | RequestAnswered
    | StepChosen
    | OptionsOffered
    | Sealed,
    Field(discriminator="kind"),
]

MUTATING_KINDS: frozenset[str] = frozenset(
    {
        "campaign_created",
        "settings_set",
        "entity_created",
        "asset_created",
        "relationship_set",
        "meter_created",
        "clock_created",
        "fact_asserted",
        "commitment_created",
        "seat_created",
        "agent_assigned",
        "seat_status_set",
        "intent_filed",
        "intent_rejected",
        "delta_applied",
        "scheduled_event_fired",
        "contest_created",
        "contest_moved",
        "contest_decided",
        "scheduled_event_created",
        "scheduled_event_skipped",
        "divergence_changed",
        "date_advanced",
        "session_zero_opened",
        "character_listed",
        "character_claimed",
        "character_released",
        "session_zero_closed",
        "season_ended",
        "goal_set",
        "goal_progressed",
        "goal_met",
        "goal_undone",
        "tick_opened",
        "tick_closed",
        "cards_declared",
        "document_issued",
        "document_written",
        "order_drafted",
        "order_step_taken",
        "order_settled",
        "quantity_set",
        "feature_set",
        "war_declared",
        "map_declared",
        "kinds_declared",
        "locks_declared",
        "laws_declared",
        "aim_patterns_declared",
        "own_aim_set",
        "order_held",
        "held_order_ended",
        "order_asked",
        "ask_answered",
        "matter_chosen",
        "offer_made",
        "offer_settled",
        "piece_stepped",
        "area_held",
        "capture_counted",
        "economy_set",
        "yield_changed",
        "trade_set",
        "battle_opened",
        "battle_round",
        "battle_ended",
        "battle_decided",
        "intelligence_declared",
        "report_made",
        "agent_set",
        "codebreaking_set",
        "groups_declared",
        "group_moved",
        "group_proposed",
        "losses_held",
        "agreement_offered",
        "agreement_made",
        "clause_judged",
        "agreement_published",
        "conference_called",
        "vote_sealed",
        "conference_tallied",
        "stance_changed",
        "opponents_ranked",
        "card_amended",
        "answer_planned",
        "answer_made",
        "news_reported",
        "order_routed",
        "order_executed",
        "effects_estimated",
        "effects_applied",
        "influence_decided",
        "mandate_issued",
        "mandate_settled",
        "wake_opened",
        "wake_committed",
        "wake_closed",
        "play_style_set",
        "seat_handover",
        "request_answered",
        "step_chosen",
    }
)


class Event(Model):
    model_config = ConfigDict(
        frozen=True, extra="forbid", ser_json_bytes="base64", val_json_bytes="base64"
    )

    event_id: EventId
    campaign_id: CampaignId
    seq: int = Field(ge=0)
    """Dense, per campaign. The store refuses gaps and repeats."""
    tick: int = Field(ge=0)
    actor: SeatId | None = None
    scope: Scope
    payload: Payload
    versions: Versions
    payload_enc: bytes | None = None
    """At rest only: nonce and AES-GCM ciphertext of the whole event when ``payload``
    is ``Sealed`` (Layer 9b). Empty on every event a reader sees."""

    @property
    def kind(self) -> str:
        return self.payload.kind

    @property
    def mutates(self) -> bool:
        return self.kind in MUTATING_KINDS
