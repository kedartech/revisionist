"""State and View (spec §7, §12).

``State`` is the full truth, a projection of the event log. ``View`` is what
one seat knows. They are different classes on purpose: a narrator, agent,
faction or outlet takes a ``View``, and passing a ``State`` is a type error
before it is a leak.

Layer 2 provides ``apply``, ``replay`` and ``project``; this module only
defines the shapes.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, Literal

from pydantic import Field

from revisionist.core._base import Label, Model
from revisionist.core.aim_patterns import AimPatterns, OwnAim
from revisionist.core.goals import Goal
from revisionist.core.ids import (
    AssetId,
    CampaignId,
    ClockId,
    CommitmentId,
    ContestId,
    DocumentId,
    EntityId,
    FactId,
    FeatureId,
    FeedId,
    GoalId,
    IntentId,
    MandateId,
    MeterId,
    OrderId,
    PipelineId,
    QuantityId,
    RelationshipId,
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
    Phase,
    Relationship,
    ScheduledEvent,
    Seat,
    SeatKind,
)
from revisionist.core.realism.agenda import Mandate, MandateTemplate, PlayStyle
from revisionist.core.realism.agreement import Agreements
from revisionist.core.realism.answer import AnswerLog
from revisionist.core.realism.battle import Battle
from revisionist.core.realism.card import CardFace, Desk, SeatCard, Topic
from revisionist.core.realism.conference import Conferences
from revisionist.core.realism.detect import Intelligence, Picture, Report
from revisionist.core.realism.document import Document, DocumentView, Feed
from revisionist.core.realism.economy import Economy
from revisionist.core.realism.effect import EffectKind, RoutedOrder, RoutedOrderView
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.groups import Groups
from revisionist.core.realism.holders import Capture, Holding
from revisionist.core.realism.kinds import Kinds
from revisionist.core.realism.laws import Law
from revisionist.core.realism.locks import Asked, HeldOrder, LockRow
from revisionist.core.realism.offers import PricedOffer
from revisionist.core.realism.pipeline import Order, Pipeline
from revisionist.core.realism.quantity import Quantity
from revisionist.core.realism.stance import Standing
from revisionist.core.realism.territory import WorldMap
from revisionist.core.realism.war import NewsEvent, Outlet, War
from revisionist.core.settings import Settings

Ruleset = Literal["legacy", "realism"]


class Rule(StrEnum):
    """A rule of the territory game a world switches on by name. A stored game, and a
    world that names none, has none on; every such rule checks its name before it acts."""

    TERRITORIES = "territories"
    HOLDERS = "holders"
    ECONOMY = "economy"
    SUPPLY = "supply"
    FUEL = "fuel"
    BATTLES = "battles"
    REPORTS = "reports"
    GROUPS = "groups"
    AGREEMENTS = "agreements"
    CONFERENCE = "conference"
    CONTESTS = "contests"
    AIMS = "aims"
    AID = "aid"
    WRITING = "writing"
    """Free writing moves groups: leans on a live model's reading."""
    CLAUSE_READER = "clause_reader"
    """Treaty and bill wording read into clauses by a live model."""
    WRITTEN_ORDERS = "written_orders"
    """Written orders checked against their form by a live model."""
    COMMAND = "command"
    """The commander's seat: a card's path, the superior prevailing, and the step on a
    superior's order that may only pass or stall (CMD)."""
    LOCKS = "locks"
    """Orders held until the person or body that can allow them does (DCD onward)."""
    LAWS = "laws"
    """Laws declared by the world, read by locks, votes and shipping (LWC, LAW)."""
    ASK_ANSWERS = "ask_answers"
    """An ask to a decider nobody plays is answered by its card on a due day (AAK)."""
    DECIDERS = "deciders"
    """Locks decided by the kind of question, and by a council (QKD)."""
    OWN_AIM = "own_aim"
    """The player's own aim, filled from the world's patterns and scored (OWC)."""
    OFFERS = "offers"
    """A priced offer to a bloc, with a promise that comes due (PRC)."""
    CLASSES = "classes"
    """Every happening has a class: felt, reported or secret (HCL)."""
    LOSSES = "losses"
    """The size of losses moves the mood at home (LSS)."""
    PLACES = "places"
    """Places with political weight: lost, abandoned or retaken (PLW)."""
    POSTS = "posts"
    """Player, person and post kept apart, and the ladder of posts (PPP, LDR)."""
    OFFICE = "office"
    """The office question as a formal sitting, and blocs turning on the leader (OFQ, TUR)."""
    ELECTIONS = "elections"
    """Elections redraw a chamber (ELE)."""
    DEFIANCE = "defiance"
    """Acting without permission, and refusing an order from above (DFY)."""
    AIDE_NOTE = "aide_note"
    """The aide's note of what waits for the seat (ABN)."""
    PEACE = "peace"
    """Peace: an armistice and its terms end a war (PEA)."""
    POST_VIEW = "post_view"
    """A commander's view limited to his post (PVW)."""
    PLAYABLE_RULE = "playable_rule"
    """Who can be played comes from a rule over the cards (PBR)."""


MODEL_READ_RULES = frozenset({Rule.WRITING, Rule.CLAUSE_READER, Rule.WRITTEN_ORDERS})
"""The rules that lean on a live model's reading: off in every shipped world."""


class Wake(Model):
    """The table's shared wake (spec §4). Public: who has committed, never what."""

    number: int = Field(ge=0)
    deadline: datetime
    committed: frozenset[SeatId] = frozenset()
    closed: bool = False


class _World(Model):
    """Fields common to truth and view."""

    campaign_id: CampaignId
    tick: int = 0
    settings: Settings = Settings()
    entities: dict[EntityId, Entity] = Field(default_factory=dict)
    assets: dict[AssetId, Asset] = Field(default_factory=dict)
    relationships: dict[RelationshipId, Relationship] = Field(default_factory=dict)
    meters: dict[MeterId, Meter] = Field(default_factory=dict)
    clocks: dict[ClockId, Clock] = Field(default_factory=dict)
    facts: dict[FactId, Fact] = Field(default_factory=dict)
    scheduled: dict[ScheduledEventId, ScheduledEvent] = Field(default_factory=dict)
    commitments: dict[CommitmentId, Commitment] = Field(default_factory=dict)
    goals: dict[GoalId, Goal] = Field(default_factory=dict)
    """Secret goals (Layer 10). A view holds only its own seat's."""
    phase: Phase = Phase.PLAY
    """A campaign from a hand-written world is in play from tick 0."""
    roster: dict[EntityId, Character] = Field(default_factory=dict)
    """The characters Session Zero offers. Public."""
    contests: dict[ContestId, Contest] = Field(default_factory=dict)
    """The pressures that keep the world moving (spec §5.3)."""
    divergence: int = Field(default=0, ge=0)
    """How far the world has drifted from the record (spec §5.4). Public."""
    in_world_date: date | None = None
    """Today in the world. None for a campaign with no start date."""
    ruleset: Ruleset = "legacy"
    """Set once, by ``campaign_created``. Public: the client hides odds under realism."""
    wake: Wake | None = None
    """Engine v2: the current or last shared wake. None before the first opens."""
    mandates: dict[MandateId, Mandate] = Field(default_factory=dict)
    """Engine v2: issued goals. A view holds only its own seat's."""
    wars: dict[Label, War] = Field(default_factory=dict, exclude_if=lambda v: not v)
    """Who is at war with whom, by ``war_id_for``. Public."""
    map: WorldMap | None = None
    """The board, set once by ``map_declared``: the same in every view. None for a world
    with no map, where every territory rule is off."""
    kinds: Kinds | None = None
    """The world's piece kinds and resources, set once by ``kinds_declared``: public rules
    of the world, the same in every view. None for a world that names neither."""
    locks: tuple[LockRow, ...] = ()
    """With ``locks`` on, the world's rows saying which order, under which condition,
    needs which decision, from whom, set once by ``locks_declared`` (DCD): public rules of
    the world, the same in every view. Read through ``locks.lock_for``."""
    laws: tuple[Law, ...] = ()
    """With ``laws`` on, the laws the world declares, set once by ``laws_declared`` (LWC):
    public rules of the world, the same in every view. Read through ``laws.in_force``."""
    aim_patterns: AimPatterns | None = None
    """With ``own_aim`` on, the world's aim patterns and each card's kind of post, set once
    by ``aim_patterns_declared`` (OWC): public rules of the world, the same in every view."""
    own_aims: dict[EntityId, OwnAim] = Field(default_factory=dict)
    """Each person's own aim, set by ``own_aim_set`` (OWC), kept by whoever holds him. A
    view holds only the aim of the person a player holds through it."""
    holders: dict[EntityId, Holding] = Field(default_factory=dict)
    """With ``holders`` on, each territory that has changed hands: its holder now, by
    ``area_held``. A territory not here has the holder the board gives. Public (THL)."""
    economy: Economy = Field(default_factory=Economy)
    """With ``economy`` on, each nation's pools (``economy_set``) and each territory whose
    yields were moved (``yield_changed``) (YLD); with ``fuel`` on, each nation's fuel
    stock in its pools and each trade line (``trade_set``) (FUL). True figures: a view
    holds its own nation's part only, and the lines it is a party to."""
    groups: Groups = Field(default_factory=Groups)
    """With ``groups`` on, each nation's groups at home as the world declares them
    (``groups_declared``), their support (``group_moved``) and the writing in waiting
    (``group_proposed``) (GRP); with ``losses`` on, the battle losses held
    (``losses_held``) (LSS). True support: a view holds its own nation's groups only, and
    never the writing in waiting or the losses held."""
    offers: tuple[PricedOffer, ...] = ()
    """With ``offers`` on, every offer of a price to a bloc and where it stands
    (``offer_made``, ``offer_settled``) (PRC). A view holds those to its own nation's
    blocs only."""
    agreements: Agreements = Field(default_factory=Agreements)
    """With ``agreements`` on, the offers (``agreement_offered``) and the agreements in
    force (``agreement_made``), with each clause's status (``clause_judged``) (AGR). A view
    holds those its nation is a party to, and every published agreement."""
    conferences: Conferences = Field(default_factory=Conferences)
    """With ``conference`` on, each conference called or scheduled
    (``conference_called``), its sealed votes (``vote_sealed``) and its tally
    (``conference_tallied``) (CNF). A view holds the opened conferences its nation is
    invited to and every opened public one, and its own votes only."""

    late_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "groups",
            "offers",
            "agreements",
            "conferences",
            "goals",
            "phase",
            "roster",
            "contests",
            "divergence",
            "in_world_date",
            "ruleset",
            "wake",
            "mandates",
            "wars",
            "map",
            "kinds",
            "locks",
            "laws",
            "aim_patterns",
            "own_aims",
            "holders",
            "economy",
        }
    )


class SeatFace(Model):
    """What any seat may know about another: who it is, never how it is run.

    spec §17: whether a seat is human or AI, its agent, its persona, its
    status (blinded, fallen) and its deputy are never shown to other seats.
    """

    seat_id: SeatId
    kind: SeatKind
    name: str
    embodies: EntityId


class State(_World):
    """The full truth. Only the referee and the resolver ever hold one."""

    seats: dict[SeatId, Seat] = Field(default_factory=dict)
    last_seq: int = -1
    pending: dict[IntentId, Intent] = Field(default_factory=dict)
    """Filed, not yet frozen into a tick."""
    frozen: tuple[IntentId, ...] = ()
    """Intents in the tick being resolved."""
    cards: dict[EntityId, SeatCard] = Field(default_factory=dict)
    """Realism: one card per person, policy fields included."""
    feeds: dict[FeedId, Feed] = Field(default_factory=dict)
    pipelines: dict[PipelineId, Pipeline] = Field(default_factory=dict)
    documents: dict[DocumentId, Document] = Field(default_factory=dict)
    """Both halves of every document issued, arrived or not."""
    orders: dict[OrderId, Order] = Field(default_factory=dict)
    quantities: dict[QuantityId, Quantity] = Field(default_factory=dict)
    features: dict[FeatureId, Feature] = Field(default_factory=dict)
    """Engine only: seats learn of features from documents that sight them."""
    routed: dict[OrderId, RoutedOrder] = Field(default_factory=dict)
    """Engine v2 orders, with the estimator's effects."""
    held: dict[OrderId, HeldOrder] = Field(default_factory=dict, exclude_if=lambda v: not v)
    """With ``locks`` on, every order a lock holds and that has not ended, form or written
    (``order_held``, until ``held_order_ended``). Each seat sees its own (LCK)."""
    asked: dict[OrderId, Asked] = Field(default_factory=dict, exclude_if=lambda v: not v)
    """Each held order its seat has asked for, by its id, until it ends (ASK). The asker
    and the seat asked see it."""
    chosen: dict[OrderId, dict[SeatId, bool]] = Field(
        default_factory=dict, exclude_if=lambda v: not v
    )
    """With ``deciders`` on, each open matter's kept choices, by seat: whether that seat
    accepts (``matter_chosen``), until the due day counts them (QKD). Engine only: a
    choice is sealed to the seat that made it."""
    styles: dict[SeatId, PlayStyle] = Field(default_factory=dict)
    """Each seat's play style. Private to the seat; absent means free."""
    standing: dict[SeatId, frozenset[EffectKind]] = Field(default_factory=dict)
    """Irreversible kinds each seat lets its aide order while it is absent."""
    templates: dict[str, MandateTemplate] = Field(default_factory=dict)
    """Engine v2: mandate templates by key. Engine only; never in a view."""
    news: dict[Label, NewsEvent] = Field(default_factory=dict, exclude_if=lambda v: not v)
    """Public events, as structured facts. Engine only: seats read them in the press."""
    outlets: dict[EntityId, Outlet] = Field(default_factory=dict, exclude_if=lambda v: not v)
    """Each polity's newspaper. Engine only."""
    stances: dict[SeatId, dict[EntityId, tuple[Standing, ...]]] = Field(
        default_factory=dict, exclude_if=lambda v: not v
    )
    """Each unplayed person's stance toward each seat, every change kept, oldest
    first. Engine only: a seat is shown what its staff last had evidence for."""
    opponents: dict[SeatId, tuple[EntityId, ...]] = Field(
        default_factory=dict, exclude_if=lambda v: not v
    )
    """The people actively opposing each seat. Engine only."""
    answers: dict[EntityId, dict[str, AnswerLog]] = Field(
        default_factory=dict, exclude_if=lambda v: not v
    )
    """The last time each unplayed person took up each answer. Engine only."""
    topics: dict[Label, Topic] = Field(default_factory=dict, exclude_if=lambda v: not v)
    """What people want and hold to, by key. Engine only."""
    handovers: dict[EntityId, Controller] = Field(default_factory=dict, exclude_if=lambda v: not v)
    """Leaders changing hands when the open wake closes: ``HUMAN`` for a joiner, ``AI``
    for a leaver. Engine only, never in a view or the wake: how a seat is run is never
    shown."""
    rules: frozenset[Rule] = frozenset()
    """The territory rules switched on, set once by ``campaign_created``. Engine only
    here; a seat's view gains them when a rule it shows needs them."""
    captures: dict[EntityId, Capture] = Field(default_factory=dict)
    """With ``holders`` on, each territory's capture count and capital mark, by
    ``capture_counted``. Engine only: it says where pieces stand (THL)."""
    battles: dict[EntityId, Battle] = Field(default_factory=dict)
    """With ``battles`` on, each battle open, by its area (``battle_opened``, until
    ``battle_ended``). Engine only: it holds both sides' true strengths (BTL)."""
    fought: frozenset[EntityId] = frozenset()
    """With ``battles`` on, every area a battle has opened in, both areas of a meeting,
    kept after it ends (``battle_opened``). Engine only: a scripted leg takes none of them
    (HSA)."""
    intelligence: dict[EntityId, Intelligence] = Field(default_factory=dict)
    """With ``reports`` on, each nation's sources as the world declares them, by nation
    (``intelligence_declared``). Engine only (DET)."""
    reports: dict[EntityId, Picture] = Field(default_factory=dict)
    """With ``reports`` on, each nation's reports on enemy pieces, delivered and pending,
    by nation (``report_made``). Engine only: a report links to the true piece (DET)."""
    aide_orders: frozenset[OrderId] = frozenset()
    """With ``reports`` on, every order an aide filed for an absent seat
    (``wake_committed``), so the rules where an effect lands can hold the aide to its
    limits (IOR). Engine only: how a seat is run is never shown."""
    aim_shut: frozenset[EntityId] = frozenset()
    """With own aims on, each person a player held when a wake closed: his own aim may no
    longer be set (OWC). Engine only."""
    late_fields: ClassVar[frozenset[str]] = _World.late_fields | {
        "aim_shut",
        "held",
        "asked",
        "chosen",
        "rules",
        "intelligence",
        "reports",
        "aide_orders",
        "captures",
        "battles",
        "fought",
        "routed",
        "styles",
        "standing",
        "templates",
        "news",
        "outlets",
        "stances",
        "opponents",
        "answers",
        "topics",
        "handovers",
        "cards",
        "feeds",
        "pipelines",
        "documents",
        "orders",
        "quantities",
        "features",
    }


class View(_World):
    """One seat's knowledge. The only input to anything that writes prose."""

    viewer: SeatId
    me: Seat
    """The viewer's own seat, in full."""
    seats: dict[SeatId, SeatFace] = Field(default_factory=dict)
    """Every seat, the viewer's included, as others see it."""
    own_pending: tuple[Intent, ...] = ()
    """The viewer's own filed intents; others' intents are never in a view."""
    cards: dict[EntityId, CardFace] = Field(default_factory=dict)
    """Realism: every card's public face."""
    desk: Desk | None = None
    """Realism: the card of the person the viewer embodies, without its AI policy."""
    documents: dict[DocumentId, DocumentView] = Field(default_factory=dict)
    """Pages in scope that have arrived by today. Never a ``DocumentTruth``."""
    orders: dict[OrderId, Order] = Field(default_factory=dict)
    """The viewer's own orders only."""
    quantities: dict[QuantityId, Quantity] = Field(default_factory=dict)
    """Only quantities whose scope admits the viewer."""
    routed: dict[OrderId, RoutedOrderView] = Field(default_factory=dict)
    """The viewer's own engine-v2 orders, without the estimator's effects."""
    held: dict[OrderId, HeldOrder] = Field(default_factory=dict, exclude_if=lambda v: not v)
    """The viewer's own held orders only (LCK)."""
    asked: dict[OrderId, Asked] = Field(default_factory=dict, exclude_if=lambda v: not v)
    """The asks the viewer made, and those put before the viewer's seat (ASK)."""
    style: PlayStyle | None = None
    """The viewer's own play style. None: free."""
    reports: dict[Label, Report] = Field(default_factory=dict)
    """The reports on enemy pieces that have reached the viewer's nation, by the nation's
    opaque key: the only enemy-piece data a view holds (DET)."""

    late_fields: ClassVar[frozenset[str]] = _World.late_fields | {
        "held",
        "asked",
        "routed",
        "style",
        "reports",
        "cards",
        "desk",
        "documents",
        "orders",
        "quantities",
    }


def seat_of_person(state: State, person: EntityId) -> Seat | None:
    """The seat that acts as ``person``: a player's seat before an AI seat; None if none."""
    held = sorted(
        (s for s in state.seats.values() if s.embodies == person),
        key=lambda s: (s.kind is not SeatKind.PLAYER, s.seat_id),
    )
    return held[0] if held else None


def controller_after(state: State, person: EntityId) -> Controller:
    """Who runs ``person`` once the open wake closes: the change waiting for the close,
    else whoever runs the person's seat now. AI for a person with no seat."""
    if person in state.handovers:
        return state.handovers[person]
    seat = seat_of_person(state, person)
    return Controller.AI if seat is None else seat.controller
