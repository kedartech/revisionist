"""The world bible format (build plan Layer 7).

A world file is hand-written YAML in the fixed ontology. Everything in it is
named by a short ``key`` (``north``, ``north_levies``) instead of an ID; the
compiler (``revisionist.core.world_compile``) turns keys into IDs derived from the
campaign and the key, so the same world compiled into the same campaign yields
the same events every time.

Keys share one namespace across every section: an entity and an asset may not
both be called ``north``. A reference names a key; the compiler resolves it to
the ID of the right type and refuses a key of the wrong type.

This module only defines the shapes. It is pure: no file reading, no YAML.
``revisionist.engine.worlds.load`` reads a file into a ``WorldFile``.

A ``ruleset: realism`` world adds cards, feeds, pipelines, quantities and
sources. It names no human seat: any card marked ``playable`` may be claimed
at Session Zero, and every person left unclaimed is run by code. Every number
authored in a quantity, feed or pipeline carries ``source: <a sources key>``
or ``gap: true``, so an unsourced figure can never pass as a sourced one.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import (
    Field,
    GetJsonSchemaHandler,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    WithJsonSchema,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue, SkipJsonSchema
from pydantic_core import CoreSchema

from revisionist.core._base import Label, Model
from revisionist.core.aim_patterns import BlankKind
from revisionist.core.goals import WinCondition
from revisionist.core.intent import Verb
from revisionist.core.ontology import (
    AssetKind,
    ClauseKind,
    ClockKind,
    CommitmentStatus,
    ContestKind,
    Controller,
    DevelopmentCategory,
    EntityKind,
    MoveKind,
    SeatKind,
)
from revisionist.core.realism.agenda import MandateKind, TriggerKind
from revisionist.core.realism.answer import Answer, ParamValue
from revisionist.core.realism.card import Address, Aim, CardPath, ChannelKind, ParamSpec, WarNeed
from revisionist.core.realism.detect import Source as IntelSource
from revisionist.core.realism.document import Bias, Classification, DocumentKind
from revisionist.core.realism.effect import (
    DISPOSITION_CAP,
    FIGURE_CAP,
    MAX_PARTIES,
    Clause,
    ClauseType,
    EffectKind,
    Engagement,
)
from revisionist.core.realism.geography import FeatureKind
from revisionist.core.realism.groups import Group, Theme
from revisionist.core.realism.kinds import MAX_STRENGTH, Domain, Role
from revisionist.core.realism.pipeline import StepAction, StepKind
from revisionist.core.realism.quantity import ResolverKey
from revisionist.core.realism.territory import Coords, Sha256, TerrainKind
from revisionist.core.settings import Settings
from revisionist.core.state import Rule
from revisionist.core.visibility import Visibility

Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)]
"""A world-file name for one object. Lowercase, digits, underscores."""


Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
RosterSize = Annotated[int, Field(ge=2, le=40)]
"""How many people a world's roster may hold, at either end of its bound. [proposed]"""

_LAT_LON = TypeAdapter(tuple[Latitude, Longitude] | None)
At = Annotated[tuple[float, float] | None, WithJsonSchema(_LAT_LON.json_schema())]
"""A place's ``[y, x]``: latitude and longitude, or on a flat map units of its plane.
Offered to a model as latitude and longitude, the only kind a drafted world has."""


class ScopeDecl(Model):
    """A non-public scope. ``known_by`` names seat keys."""

    visibility: Visibility
    known_by: tuple[Key, ...] = ()


ScopeSpec = Literal["public"] | ScopeDecl
"""``public`` or a mapping ``{visibility: covert, known_by: [north]}``."""


class BaseDecl(Model):
    """A site a side's pieces work from (ADJ): polity keys, and the domains it serves."""

    sides: tuple[Key, ...] = Field(min_length=1)
    domains: tuple[Literal["land", "sea", "air"], ...] = Field(min_length=1)


class EntityDecl(Model):
    key: Key
    kind: EntityKind
    name: Label
    parent: Key | None = None
    location: Key | None = None
    tags: tuple[Label, ...] = ()
    at: At = None
    """A place's latitude and longitude, for the map; on a flat map, ``[y, x]`` in its units."""
    theatre: SkipJsonSchema[Label | None] = None
    """The theatre a place sits in, for the map. Written by hand: not offered to a
    model drafting a world."""
    within: SkipJsonSchema[Key | None] = None
    """The territory or sea zone a place lies in. Written by hand."""
    port_on: SkipJsonSchema[Key | None] = None
    """A port: the sea zone a place within a territory opens on. A sea piece declared there
    stands in that zone; a land piece embarks and lands there. Written by hand."""
    base: SkipJsonSchema[BaseDecl | None] = None
    """A base: the sides it serves and the domains of piece it serves. Written by hand."""
    lift_pool: SkipJsonSchema[Key | None] = None
    """A polity's pool of shipping for lifting its land pieces: a quantity key. Written by
    hand."""
    capital: SkipJsonSchema[Key | None] = None
    """A polity's capital site: a place within a territory, or the territory itself. With
    ``holders`` on, that territory falls only after a whole wake's notice. Written by hand."""


class AssetDecl(Model):
    key: Key
    kind: AssetKind
    name: Label
    tier: int = Field(default=1, ge=0, le=5)
    controller: Key
    """An entity key."""
    location: Key | None = None
    loyalty: int = Field(default=0, ge=-5, le=5)
    scope: ScopeSpec = "public"


class RelationshipDecl(Model):
    key: Key
    a: Key
    b: Key
    disposition: int = Field(ge=-5, le=5)
    price_tags: tuple[Label, ...] = ()
    leverage_tags: tuple[Label, ...] = ()
    scope: ScopeSpec = "public"


class MeterDecl(Model):
    key: Key
    owner: Key
    """An entity key."""
    name: Label
    value: int
    lo: int = 0
    hi: int = 100
    max_delta_per_tick: int = Field(default=10, ge=1)
    scope: ScopeSpec = "public"


class ClockDecl(Model):
    key: Key
    kind: ClockKind
    name: Label
    owner: Key | None = None
    """A seat key."""
    target: Key | None = None
    """An entity key."""
    segments_total: int = Field(ge=1, le=12)
    segments_filled: int = Field(default=0, ge=0)
    exposure: int = Field(default=0, ge=0, le=5)
    holds_slot: bool = False
    scope: ScopeSpec = "public"


class FactDecl(Model):
    key: Key
    subject: Key
    """An entity key."""
    predicate: Label
    obj: str = Field(max_length=60)
    """An entity, asset or clock key if one exists by that name; otherwise a literal label."""
    truth: bool = True
    exposure: int = Field(default=0, ge=0, le=5)
    scope: ScopeSpec = "public"
    canary: str | None = Field(default=None, max_length=60)
    """A unique string that must never reach a seat outside ``scope``."""


class ClauseDecl(Model):
    kind: ClauseKind
    party: Key
    beneficiary: Key
    asset: Key | None = None
    verb: Verb | None = None
    amount: int | None = None
    until_tick: int | None = None


class CommitmentDecl(Model):
    key: Key
    parties: tuple[Key, ...] = Field(min_length=2)
    clauses: tuple[ClauseDecl, ...] = Field(min_length=1)
    status: CommitmentStatus = CommitmentStatus.ACCEPTED
    scope: ScopeSpec = "public"


class AgentDecl(Model):
    """The seat's chief of staff. ``entity`` is a person entity key."""

    entity: Key
    name: Label
    role: Label
    voice: str = Field(default="", max_length=200)
    backstory: str = Field(default="", max_length=400)
    relationship: str = Field(default="", max_length=200)


class SeatDecl(Model):
    key: Key
    kind: SeatKind
    name: Label
    embodies: Key
    """An entity key."""
    controller: Controller = Controller.AI
    slots: int | None = Field(default=None, ge=0, le=5)
    """None means ``settings.starting_slots``."""
    objectives: tuple[Key, ...] = ()
    """Clock keys."""
    standing_orders: tuple[str, ...] = ()
    agent: AgentDecl | None = None


class ContestMoveDecl(Model):
    """A move of a contest (CON): what happened, and the side it steps toward.

    ``kind: battle`` names a ``region``; ``holder`` a ``territory``; ``flag`` a
    ``quantity``; ``line`` a ``line`` and one of a ``quantity``, a ``nation`` (its
    war-economy figure) or a ``nation`` and its ``group`` (the group's support), with
    ``falling: true`` to count a crossing downward; ``agreement_made`` and
    ``agreement_broken`` name two or more nations in ``between``. ``step`` defaults by
    kind (``contests.STEPS``)."""

    kind: MoveKind
    toward: Key
    """One of the contest's sides."""
    step: int | None = Field(default=None, ge=1, le=100)
    region: Key | None = None
    territory: Key | None = None
    quantity: Key | None = None
    nation: Key | None = None
    group: Key | None = None
    line: float | None = None
    falling: bool = False
    between: tuple[Key, ...] = ()


class ContestDecl(Model):
    """A contest (spec §5.3). ``sides`` names entity keys: a rivalry's 2-4 sides,
    or a trial's one power under trial. With the ``contests`` rule on, ``moves`` say
    what moves its track (CON) and it is decided ``countdown_days`` after the start."""

    key: Key
    kind: ContestKind
    name: Label
    prize: str = Field(max_length=200)
    sides: tuple[Key, ...] = Field(min_length=1, max_length=4)
    track: int = Field(default=0, ge=-100, le=100)
    momentum: int = Field(default=0, ge=-20, le=20)
    countdown_days: int = Field(ge=1)
    scope: ScopeSpec = "public"
    moves: SkipJsonSchema[tuple[ContestMoveDecl, ...]] = ()
    """Kept out of the draft's schema, like the other keys of the territory rules."""


class HistoryDecl(Model):
    """An item on history's clock (spec §5.4): what really followed the start date.

    The condition names keys, like a goal's. ``weight`` is how central it was.
    With a ``headline``, the event is reported as news when it fires in public.
    """

    key: Key
    name: str = Field(max_length=120)
    on_date: date
    condition: WinCondition
    weight: int = Field(default=1, ge=1, le=3)
    scope: ScopeSpec = "public"
    headline: Label | None = None
    """Plain words, no date."""
    subject: Key | None = None
    """An entity key: who the news is about."""
    obj: Key | None = None
    """An entity key: who it was done to, if anyone."""

    @model_validator(mode="after")
    def _headline_has_a_subject(self) -> "HistoryDecl":
        if self.headline is not None and self.subject is None:
            raise ValueError("a headline needs a subject")
        return self


class WindowDecl(Model):
    """The days a development may fall on, both inclusive."""

    start: date
    end: date

    @model_validator(mode="after")
    def _in_order(self) -> "WindowDecl":
        if self.end < self.start:
            raise ValueError("a window ends on or after it starts")
        return self


class FigureDecl(Model):
    """Move a figure by a percent of its value. ``quantity`` is a quantity key."""

    kind: Literal["figure"] = "figure"
    quantity: Key
    percent: int = Field(ge=-FIGURE_CAP, le=FIGURE_CAP)

    @model_validator(mode="after")
    def _moves(self) -> "FigureDecl":
        if self.percent == 0:
            raise ValueError("a figure change moves the figure")
        return self


class DispositionDecl(Model):
    """Move how ``of`` regards ``toward``. Both are entity keys."""

    kind: Literal["disposition"] = "disposition"
    of: Key
    toward: Key
    change: int = Field(ge=-DISPOSITION_CAP, le=DISPOSITION_CAP)

    @model_validator(mode="after")
    def _moves(self) -> "DispositionDecl":
        if self.change == 0 or self.of == self.toward:
            raise ValueError("a disposition change moves one party toward another")
        return self


DevelopmentEffectDecl = Annotated[FigureDecl | DispositionDecl, Field(discriminator="kind")]


class DevelopmentDecl(Model):
    """A public development from the world's deck (``worlds/developments/<world>.yaml``).

    Drawn once per campaign to a day in ``window``, or to none, as ``chance`` gives;
    on that day it fires if ``condition`` holds and is skipped otherwise. When it
    fires it is reported as news and its effects apply. ``asks`` are orders it
    suggests to the seats; it never files one.
    """

    key: Key
    name: str = Field(max_length=120)
    category: DevelopmentCategory
    window: WindowDecl
    chance: int = Field(default=100, ge=1, le=100)
    condition: WinCondition | None = None
    headline: Label
    """Plain words, no date."""
    subject: Key
    """An entity key: who the news is about."""
    obj: Key | None = None
    effects: tuple[DevelopmentEffectDecl, ...] = Field(default=(), max_length=4)
    asks: tuple[Label, ...] = Field(default=(), max_length=2)
    source: str | None = Field(default=None, max_length=200)
    """A citation in words."""
    gap: bool = False

    @model_validator(mode="after")
    def _cited_or_gap(self) -> "DevelopmentDecl":
        if (self.source is None) == (not self.gap):
            raise ValueError("give exactly one of source: <citation> or gap: true")
        return self


class SideDecl(Model):
    """Where a roster character stands in one contest."""

    contest: Key
    side: Key
    """An entity key: one of the contest's sides."""


class GoalDecl(Model):
    """A player seat's secret goal. In a world file the condition names keys, not IDs.

    The compiler gives the goal its objective clock and its kind; neither is
    written here, because the kind comes from a fixed table (spec §15).
    """

    key: Key
    seat: Key
    text: str = Field(max_length=280)
    condition: WinCondition
    canary: str | None = Field(default=None, max_length=60)


class CharacterDecl(Model):
    """A character on the Session Zero roster. ``entity`` is a person key.

    ``composite`` has no default on purpose: whoever writes the roster must say
    whether the record names this person or the character is built from a role.
    """

    entity: Key
    pitch: str = Field(max_length=200)
    reach: str = Field(max_length=200)
    composite: bool
    means: tuple[Key, ...] = ()
    """Asset keys the character controls at the start date."""
    sides: tuple[SideDecl, ...] = ()
    """The character's side in each contest they bear on. Public."""
    aliases: tuple[Annotated[str, StringConstraints(max_length=60)], ...] = Field(
        default=(), max_length=6
    )
    """Other names people use for this person. Public."""


# --- realism ---------------------------------------------------------------------


class SourceDecl(Model):
    """A published source numbers are cited to. ``verified`` stays false until its
    coverage and licence are checked (plan, 0b)."""

    key: Key
    title: str = Field(max_length=200)
    note: str = Field(default="", max_length=400)
    verified: bool = False


class Cited(Model):
    """A declaration holding authored numbers: cited to a source, or marked a gap."""

    source: Key | None = None
    gap: bool = False

    @model_validator(mode="after")
    def _cited_or_gap(self) -> "Cited":
        if getattr(self, "computed", False):
            if self.source is not None or self.gap:
                raise ValueError("a computed figure has no source and is not a gap")
            return self
        if (self.source is None) == (not self.gap):
            raise ValueError("give exactly one of source: <key> or gap: true")
        return self


class QuantityDecl(Cited):
    key: Key
    owner: Key | None = None
    """An entity key."""
    name: Label
    value: int | None = None
    """Left out only for a gap."""
    unit: Label
    as_of: date | None = None
    """None means the world's start date."""
    public: bool = False
    """Public quantities are in every view; the rest reach seats only as documents."""
    computed: bool = False
    """A resolver's output: no value until code computes one, so neither cited nor a gap."""

    @model_validator(mode="after")
    def _gap_has_no_value(self) -> "QuantityDecl":
        if self.computed and self.value is not None:
            raise ValueError(f"quantity {self.key}: a computed figure starts with no value")
        if self.value is None and not (self.gap or self.computed):
            raise ValueError(f"quantity {self.key}: a value, gap: true or computed: true")
        return self


class FeedDecl(Cited):
    key: Key
    name: Label
    author: Key
    """A person key."""
    kind: DocumentKind
    channel: ChannelKind
    classification: Classification = Classification.OPEN
    every_days: int | None = Field(default=None, ge=1, le=365)
    latency_days: int | None = Field(default=None, ge=0, le=365)
    assumed: bool = False
    """The cadence and latency are a labelled default by document kind, not sourced."""
    reports: tuple[Key, ...] = ()
    """Quantity keys."""
    sights: tuple[Key, ...] = ()
    """Feature keys."""
    bias: Bias = Bias()

    @model_validator(mode="after")
    def _assumed_is_set(self) -> "FeedDecl":
        if self.assumed and (self.every_days is None or self.latency_days is None):
            raise ValueError(f"feed {self.key}: an assumed timing still needs its numbers")
        return self


class StepDecl(Model):
    person: Key
    kind: StepKind
    days: int | None = Field(default=None, ge=0, le=365)
    assumed: bool = False
    """``days`` is a labelled default by step kind, not sourced."""
    allowed: tuple[StepAction, ...] = (StepAction.PASS,)

    @model_validator(mode="after")
    def _assumed_is_set(self) -> "StepDecl":
        if self.assumed and self.days is None:
            raise ValueError(f"step at {self.person}: an assumed length still needs its days")
        return self


class PipelineDecl(Cited):
    key: Key
    name: Label
    steps: tuple[StepDecl, ...] = Field(min_length=1, max_length=12)


class LegDecl(Model):
    """A move the record says a feature made: where it was from ``since``. In a world with
    ``territories`` on, a place may be an area."""

    since: date
    places: tuple[Key, ...] = Field(min_length=1)
    takes: SkipJsonSchema[tuple[Key, ...]] = ()
    """With ``holders`` on, territory keys that pass to the feature's side on ``since``,
    but where a battle has been fought or an enemy land piece stands. Written by hand: not
    offered to a model."""
    concealed: SkipJsonSchema[bool] = False
    """The piece is concealed from ``since`` until it arrives. Written by hand."""


class FeatureDecl(Cited):
    """A force, front or route on the map. Positions are approximate."""

    key: Key
    kind: FeatureKind
    name: Label
    side: Key | None = None
    """A polity or body key. A front has none."""
    tier: int = Field(default=0, ge=0, le=5)
    places: tuple[Key, ...] = Field(min_length=1)
    """Place keys: one for a force, two or more for a front or route."""
    as_of: date | None = None
    """None means the world's start date."""
    legs: tuple[LegDecl, ...] = ()
    in_service: date | None = None
    """Engine v2: the day the capability enters service. None: from the start."""
    piece: SkipJsonSchema[Key | None] = None
    """A ``piece``: the key of one of the world's ``piece_kinds``. Written by hand: not
    offered to a model."""

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        """A model drafting a world is offered the five fixed kinds, never ``piece``: a
        piece needs ``piece_kinds``, which are written by hand."""
        schema = handler(core_schema)
        kind = handler.resolve_ref_schema(handler.resolve_ref_schema(schema)["properties"]["kind"])
        kind["enum"] = [k for k in kind["enum"] if k != FeatureKind.PIECE.value]
        return schema


class WarDecl(Cited):
    """A war already under way on the start date. ``a`` and ``b`` are polity keys;
    ``a`` is the side that began it."""

    a: Key
    b: Key
    since: date
    declared: bool = True
    """False for a war fought without a formal declaration. Either way it is a war."""


MapFile = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\.json$", max_length=60)
]
"""A map file's name, found under ``maps/`` beside the world file, or beside it."""


class MapDecl(Model):
    """The map file a world's board is drawn from, named by its file and its hash."""

    coords: Coords
    file: MapFile
    sha256: Sha256
    box: tuple[float, float, float, float] | None = None
    """``[west, south, east, north]``; a ``flat`` map needs one."""


class TerrainDecl(Model):
    key: Key
    kind: TerrainKind
    defence: int = Field(default=0, ge=0, le=2)
    """What the terrain adds to a defender's score in battle: 0 to 2."""


class PieceKindDecl(Model):
    """A kind of piece the world names: a levy, a galley, a panzer corps. Its domain is
    one of the engine's four; every other figure is the world's."""

    key: Key
    name: Label
    domain: Domain
    days_per_step: dict[Key, Annotated[int, Field(ge=1)]]
    """Days a step takes, by the terrain key of the area entered: one for every terrain
    its domain can enter (land kinds land terrain, sea kinds sea terrain, air and envoys
    both)."""
    max_strength: int = Field(default=MAX_STRENGTH, ge=1)
    fuel_per_step: float = Field(default=0, ge=0)
    range_steps: int | None = Field(default=None, ge=1)
    """An air kind's reach from its base, in steps; only an air kind has one."""
    detect: Annotated[int, Field(ge=0, le=100)] = 0
    conceal: Annotated[int, Field(ge=0, le=100)] = 0
    carries: tuple[Key, ...] = ()
    """The kinds it can lift, by key."""


class IntelSourceDecl(Model):
    """One source a nation searches with, and the person who reports it (DET). A source's
    rank is its place in the nation's list, the first highest."""

    source: IntelSource
    person: Key
    """A person entity key."""
    channel: ChannelKind
    """How the person's reports travel; they arrive after the channel's days."""
    skew: int = Field(default=0, ge=-5, le=5)
    """A bias that shifts every strength range the person reports one way."""


class IntelAgentDecl(Model):
    area: Key
    """A territory or sea zone key."""
    until: date | None = None
    """The last day the agent reports. None: no end."""


class IntelligenceDecl(Model):
    """A nation's intelligence on the start date (DET), with ``reports`` on."""

    nation: Key
    """A polity key."""
    sources: tuple[IntelSourceDecl, ...] = ()
    codebreaking: int = Field(default=0, ge=0, le=3)
    agents: tuple[IntelAgentDecl, ...] = ()


class GroupsDecl(Model):
    """A nation's groups at home on the start date (GRP), with ``groups`` on, in the
    order the world gives them."""

    nation: Key
    """A polity key."""
    groups: tuple[Group, ...] = Field(min_length=1)
    themes: tuple[Theme, ...] = ()
    """The themes the nation's writing may name, each with the points it moves the
    nation's groups by (FWG). Writing that names one moves the groups by this table."""


class LockOrderDecl(Model):
    """Which order a lock holds (DCD), in world-file keys: ``form`` a lever's name with
    some of its parameter values as the form takes them, or ``effect`` an effect kind
    with ``zone`` (a territory, sea zone or place key) or ``force`` (a feature key)."""

    form: Label | None = None
    params: dict[Label, ParamValue] = Field(default_factory=dict)
    effect: EffectKind | None = None
    zone: Key | None = None
    force: Key | None = None


class LockWhenDecl(Model):
    """A lock's condition (DCD): ``law_not_in_force`` with ``clause`` (a law's clause
    subject); or ``posture_not_set`` with the written naming (``zone`` a territory, sea
    zone or place key, and ``rule``), the form naming (``form``, ``where`` the zone's
    values and ``posture`` the posture's), or both."""

    check: Literal["law_not_in_force", "posture_not_set"]
    clause: str | None = Field(default=None, max_length=200)
    zone: Key | None = None
    rule: Engagement | None = None
    form: Label | None = None
    where: dict[Label, ParamValue] = Field(default_factory=dict)
    posture: dict[Label, ParamValue] = Field(default_factory=dict)


class CouncilDecl(Model):
    """A council that decides (QKD): ``members`` the person keys of who sits on it, each
    with a card; ``needed`` how many must agree, no more than the members; ``head`` the
    person key an ask goes to."""

    members: tuple[Key, ...] = Field(min_length=1, max_length=24)
    needed: int = Field(ge=1)
    head: Key


class LockDeciderDecl(Model):
    """Who can allow a held order (DCD): ``person`` a person key, or a body: ``nation`` a
    polity key, ``chambers`` the keys of its chambers that pass the law, and ``head`` the
    person key of the head of its government, to whom an ask goes (ASK); or, with
    ``deciders`` on, a ``council`` (QKD). With ``deciders`` off a council's head decides
    alone."""

    person: Key | None = None
    nation: Key | None = None
    chambers: tuple[Label, ...] = ()
    head: Key | None = None
    council: CouncilDecl | None = None


class LockDecl(Model):
    """One lock (DCD), with ``locks`` on: which order, under which condition (none: always),
    needs which decision, from whom."""

    key: Key
    order: LockOrderDecl
    when: LockWhenDecl | None = None
    decider: LockDeciderDecl
    question: str | None = Field(default=None, max_length=40)
    """With ``deciders`` on, the kind of question (``locks.Question``); absent: a question
    of permission (QKD)."""


class LawDoesDecl(Model):
    """What a passed law does (LWC): ``kind`` one of the effects the rules know
    (``laws.Does``), and for ``adds_manpower`` its ``amount``."""

    kind: str = Field(min_length=1, max_length=40)
    amount: int | None = None


class LawDecl(Model):
    """One law (LWC), read with ``laws`` on: ``nation`` the polity key it binds,
    ``passed`` the key of the quantity that reads 1 once it has passed."""

    key: Key
    title: Label
    nation: Key
    clauses: tuple[Clause, ...] = Field(min_length=1, max_length=12)
    passed: Key
    does: LawDoesDecl | None = None
    daily_life: bool = False


class PactClauseDecl(Model):
    """One clause of a pact (PCT), as AGR's typed list has it, in world-file keys:
    ``binds``, ``nation`` polity keys; ``force`` a feature key; ``area`` a territory or sea
    zone key; ``region`` a region key; ``form`` a lever name. A clause with no ``type``
    is wording the list cannot express: kept as ``text`` and marked unchecked."""

    type: ClauseType = ClauseType.UNCHECKED
    binds: Key
    on: date | None = None
    """The day it is judged; none: standing, judged each day."""
    force: Key | None = None
    area: Key | None = None
    region: Key | None = None
    present: bool = True
    nation: Key | None = None
    days: int | None = Field(default=None, ge=0, le=60)
    form: Label | None = None
    share: int | None = Field(default=None, ge=1, le=100)
    text: str = Field(default="", max_length=300)


class PactDecl(Cited):
    """A pact in force on the start date (PCT): with ``agreements`` on, compile makes it
    an agreement from the first day, with no offer. ``parties`` are polity keys. A
    public pact is seen by every seat; a secret one by its parties only."""

    key: Key
    name: Label
    parties: tuple[Key, ...] = Field(max_length=MAX_PARTIES)
    wording: str = Field(default="", max_length=500)
    clauses: tuple[PactClauseDecl, ...] = ()
    public: bool = False


class ConferenceDecl(Cited):
    """A conference the world schedules (CNF): with ``conference`` on, it opens on
    ``opens`` as if ``caller`` had called it then, and votes on ``voting_day``.
    ``caller`` and ``invited`` are polity keys; the caller is among the invited. Its
    clauses are a pact's, and each binds a nation invited."""

    key: Key
    caller: Key
    invited: tuple[Key, ...] = Field(max_length=MAX_PARTIES)
    wording: str = Field(min_length=1, max_length=600)
    clauses: tuple[PactClauseDecl, ...] = Field(default=(), max_length=8)
    opens: date
    voting_day: date
    public: bool = False
    unanimous: bool = False


class ResourceDecl(Model):
    """A resource the world names, and the one role it plays."""

    key: Key
    name: Label
    unit: Label
    role: Role


class FuelStockDecl(Cited):
    """A nation's fuel stock on the start date (FUL), in the unit of its fuel resource."""

    polity: Key
    amount: float = Field(ge=0)


class TradeLineDecl(Cited):
    """A trade line in force on the start date (FUL): ``amount`` of ``resource`` a month,
    from ``exporter`` to ``importer``; ``cut`` when it starts cut."""

    key: Key
    exporter: Key
    importer: Key
    resource: Key
    amount: float = Field(ge=0)
    cut: bool = False


class AidFindingDecl(Model):
    """An aid finding (PRL): the form (a lever name) that allocates a share of the figure
    ``draws_on``, the figure each recipient's share is written to (``shares``, by polity),
    and the flag a finding naming a recipient sets to 1 (``eligible``, by polity)."""

    form: Label
    draws_on: Key
    shares: dict[Key, Key] = Field(default_factory=dict)
    eligible: dict[Key, Key] = Field(default_factory=dict)


class LiftPriorityDecl(Model):
    """The production priority (PRL): the form (a lever name) a nation's latest enacted
    order of which, while it names the choice ``grows_lift_on``, grows the nation's lift pool
    on each 1st."""

    form: Label
    grows_lift_on: Label


class ProductionDecl(Model):
    """What the production rules read from the world instead of a name of their own (PRL).
    Read in a game with a map."""

    findings: tuple[AidFindingDecl, ...] = ()
    priority: LiftPriorityDecl | None = None


class RegionDecl(Model):
    key: Key
    name: Label
    parent: Key | None = None
    """The region this one lies in. Regions nest to any depth, never in a cycle."""


class TerritoryDecl(Cited):
    """A land area of the map. Its holder and yields are cited, or marked a gap."""

    key: Key
    name: Label
    region: Key
    terrain: Key
    holder: Key | None = None
    """The polity holding it at the start."""
    yields: dict[Key, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)
    """What it yields, by resource key."""
    sites: tuple[Key, ...] = ()
    """Places in it, each a location entity."""
    districts: tuple[Key, ...] = ()
    """Finer shapes in the map file, for drawing only."""


class SeaZoneDecl(Model):
    key: Key
    name: Label
    region: Key
    terrain: Key


class LinkDecl(Model):
    """Two areas joined where they share no border: a strait, a ferry, a causeway."""

    a: Key
    b: Key
    crossing: Label


AdjacencyDecl = tuple[Key, Key] | LinkDecl


class LeverDecl(Model):
    name: Label
    pipeline: Key
    resolver: ResolverKey
    params: tuple[ParamSpec, ...] = ()
    label: Label = ""
    summary: str = Field(default="", max_length=300)
    needs_war: SkipJsonSchema[dict[Label, dict[Label, WarNeed]]] = Field(default_factory=dict)
    """The choices a seat's nation may take only at war with a nation, by parameter and
    choice, each naming the nation's key and the words of the refusal (WRL)."""
    escort_level: SkipJsonSchema[dict[Label, dict[Label, int]]] = Field(default_factory=dict)
    """The escort level each choice of one parameter stands for, by parameter and choice
    (ESC): 0 none, 1 escort, 2 shoot on sight. The compiler checks the range and that every
    choice of the parameter is marked."""


class ContactDecl(Model):
    person: Key
    channel: ChannelKind


class DomainDecl(Model):
    """One authority domain. ``executor`` and ``forces`` are keys."""

    name: Label
    effects: tuple[EffectKind, ...] = Field(min_length=1)
    executor: Key | None = None
    forces: tuple[Key, ...] = ()
    summary: str = Field(default="", max_length=300)


class ReachDecl(Model):
    rank: int = Field(default=0, ge=0, le=5)
    chain: tuple[Key, ...] = ()
    heads: bool = False


class ConflictDecl(Model):
    """Something a person is set against. ``against`` is a person or polity key."""

    against: Key
    over: Label
    irreducible: bool = False


class AimRuleDecl(Model):
    """What makes a card's aim a goal (AIM). ``aim`` counts the card's aims from 1; the
    condition names keys, like a goal's (a group by its key in the nation's groups).
    Who may see each leaf is worked out by the compiler from the world."""

    aim: int = Field(ge=1, le=3)
    condition: WinCondition
    rule: str = Field(min_length=1, max_length=280)
    """The success rule in plain words."""
    opens: date | None = None
    deadline: date | None = None
    replaceable: bool = False


class AimBlankDecl(Model):
    """One blank of an aim pattern (OWC): ``values`` a closed list (world keys, group keys
    or numbers), or ``kind`` resolved from the seat's view; one of the two."""

    name: Key
    values: tuple[Key | int, ...] = ()
    kind: BlankKind | None = None

    @model_validator(mode="after")
    def _one(self) -> "AimBlankDecl":
        if bool(self.values) == (self.kind is not None):
            raise ValueError("a blank has a list of values or a kind, not both")
        return self


class AimPatternDecl(Model):
    """One aim pattern (OWC), read with ``own_aim`` on: ``posts`` the kinds of post it
    suits (a card's ``post_kind``, or its path), ``sentence`` the aim in words with each
    blank as ``{name}``, ``condition`` an aim's condition in world keys with each blank as
    ``$name`` (``$nation`` and ``$person`` stand for the person's own nation and the person),
    and ``government`` whether the person's own government would issue it."""

    key: Key
    posts: tuple[Key, ...] = Field(min_length=1, max_length=8)
    sentence: str = Field(min_length=1, max_length=200)
    condition: dict[str, JsonValue]
    blanks: tuple[AimBlankDecl, ...] = Field(default=(), max_length=4)
    government: bool = True
    deadline: date | None = None


class CardDecl(Model):
    """A person's seat card. ``person`` is a person key; the card has no key of its own."""

    person: Key
    office: Label
    playable: bool = False
    principals: tuple[Key, ...] = ()
    powers: tuple[Label, ...] = ()
    levers: tuple[LeverDecl, ...] = ()
    inner_circle: tuple[ContactDecl, ...] = ()
    feeds: tuple[Key, ...] = ()
    pipelines: tuple[Key, ...] = ()
    constraints: tuple[Label, ...] = ()
    personal: tuple[Label, ...] = ()
    successor: Key | None = None
    horizon_days: int = Field(ge=1, le=365)
    voice: str = Field(default="", max_length=200)
    loyalty: int = Field(default=0, ge=-5, le=5)
    competence: int = Field(default=3, ge=0, le=5)
    doctrine: tuple[Label, ...] = ()
    interests: tuple[Label, ...] = ()
    authority: tuple[DomainDecl, ...] = ()
    reach: ReachDecl = ReachDecl()
    aims: tuple[Aim, ...] = Field(default=(), max_length=3)
    allies: tuple[Key, ...] = ()
    """Polity or person keys this person stands with."""
    opposes: tuple[ConflictDecl, ...] = Field(default=(), max_length=6)
    answers: tuple[Answer, ...] = Field(default=(), max_length=8)
    """What the person does back while nobody plays them. Keys stand where ids go:
    ``by``, ``party``, ``until`` and the people and places an act's effect names."""
    addressed_as: Address | None = None
    """How a letter to the person opens ("Mr. President")."""
    wants: SkipJsonSchema[tuple[Key, ...]] = ()
    """Topic keys. Written by hand, like ``holds_to``: not offered to a model."""
    holds_to: SkipJsonSchema[tuple[Key, ...]] = ()
    aim_rules: SkipJsonSchema[tuple[AimRuleDecl, ...]] = Field(default=(), max_length=3)
    """Read with the ``aims`` rule on (AIM). Written by hand: not offered to a model."""
    path: SkipJsonSchema[CardPath] = CardPath.POLITICAL
    """Political or military (CMD), read with the ``command`` rule on. Written by hand:
    not offered to a model."""
    post_kind: SkipJsonSchema[Key | None] = None
    """The kind of post the card holds, matched against an aim pattern's ``posts`` with
    ``own_aim`` on (OWC). Written by hand: not offered to a model."""


class TopicDecl(Model):
    """A matter people want or hold to. ``levers`` are lever names on cards in this
    world, ``effects`` effect kinds, ``words`` lower-case words."""

    key: Key
    name: Label
    levers: tuple[Label, ...] = ()
    effects: tuple[Label, ...] = ()
    words: tuple[Label, ...] = ()


class TriggerDecl(Model):
    """A mandate's trigger. ``history`` and ``quantity`` are keys."""

    on: TriggerKind
    history: Key | None = None
    quantity: Key | None = None
    op: Literal["ge", "le"] | None = None
    value: int | None = None
    effect: EffectKind | None = None


class MandateDecl(Model):
    """A mandate template (engine v2, spec §8.5). ``to`` and ``issuer`` are entity keys;
    the condition names keys, like a goal's."""

    key: Key
    kind: MandateKind
    trigger: TriggerDecl
    to: tuple[Key, ...] = Field(min_length=1)
    issuer: Key | None = None
    text: str = Field(min_length=1, max_length=400)
    condition: WinCondition
    days: int = Field(ge=1, le=90)


class OutletDecl(Model):
    """A polity's newspaper. ``key`` is also declared in ``entities`` (an org under
    ``polity``); both are entity keys."""

    key: Key
    polity: Key
    name: Label
    voice: str = Field(min_length=1, max_length=300)


Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*$", max_length=40)]
"""A world's file name: lowercase, digits, underscores and hyphens."""


class DevelopmentDeck(Model):
    """The sidecar file beside a world: its deck of developments."""

    world: Slug
    developments: tuple[DevelopmentDecl, ...] = ()


class WorldFile(Model):
    world: Slug
    """Slug. Becomes ``CampaignCreated.world``."""
    name: Label
    """Becomes ``CampaignCreated.name``."""
    settings: Settings = Settings()
    entities: tuple[EntityDecl, ...] = ()
    assets: tuple[AssetDecl, ...] = ()
    relationships: tuple[RelationshipDecl, ...] = ()
    meters: tuple[MeterDecl, ...] = ()
    clocks: tuple[ClockDecl, ...] = ()
    facts: tuple[FactDecl, ...] = ()
    commitments: tuple[CommitmentDecl, ...] = ()
    seats: tuple[SeatDecl, ...] = ()
    goals: tuple[GoalDecl, ...] = ()
    start: str = Field(default="", max_length=80)
    """A point in history, "Florence, April 1478". Set, it opens Session Zero."""
    roster: tuple[CharacterDecl, ...] = ()
    roster_limit: SkipJsonSchema[tuple[RosterSize, RosterSize] | None] = None
    """The least and most people the roster holds, in place of 8 and 12. Written by hand:
    not offered to a model, so a drafted world keeps 8 to 12."""
    notes: tuple[Annotated[str, StringConstraints(max_length=200)], ...] = ()
    """Readings the GM chose where the record is disputed or silent (spec §5)."""
    start_date: date | None = None
    """The in-world start date (Session Zero v3). Set, the draft needs contests."""
    contests: tuple[ContestDecl, ...] = ()
    schedule: tuple[HistoryDecl, ...] = ()
    """History's clock: the key events that really followed ``start_date``."""
    ruleset: Literal["legacy", "realism"] = "legacy"
    cards: tuple[CardDecl, ...] = ()
    feeds: tuple[FeedDecl, ...] = ()
    pipelines: tuple[PipelineDecl, ...] = ()
    quantities: tuple[QuantityDecl, ...] = ()
    features: tuple[FeatureDecl, ...] = ()
    sources: tuple[SourceDecl, ...] = ()
    mandates: tuple[MandateDecl, ...] = ()
    """Engine v2: mandate templates. Realism only."""
    outlets: tuple[OutletDecl, ...] = ()
    """Each polity's newspaper. Realism only."""
    developments: tuple[DevelopmentDecl, ...] = ()
    """The deck, read from the sidecar file, not from the world file itself."""
    topics: tuple[TopicDecl, ...] = ()
    """What people want and hold to, named once. Realism only."""
    wars: SkipJsonSchema[tuple[WarDecl, ...]] = ()
    """Wars in force on the start date. Realism only. Written by hand: not offered to a model."""
    rules: SkipJsonSchema[tuple[Rule, ...]] = ()
    """The territory rules this world switches on, by name; none when left out. Realism
    only. Written by hand: not offered to a model."""
    map: SkipJsonSchema[MapDecl | None] = None
    """The map file the board is drawn from. Realism only. The board's keys below are
    written by hand, or by the map build: none is offered to a model."""
    terrain: SkipJsonSchema[tuple[TerrainDecl, ...]] = ()
    regions: SkipJsonSchema[tuple[RegionDecl, ...]] = ()
    territories: SkipJsonSchema[tuple[TerritoryDecl, ...]] = ()
    sea_zones: SkipJsonSchema[tuple[SeaZoneDecl, ...]] = ()
    adjacency: SkipJsonSchema[tuple[AdjacencyDecl, ...]] = ()
    """Each bordering pair once, in either order."""
    resources: SkipJsonSchema[tuple[ResourceDecl, ...]] = ()
    """The resources territories yield, each with its role. Realism only. Written by hand:
    not offered to a model."""
    fuel_stocks: SkipJsonSchema[tuple[FuelStockDecl, ...]] = ()
    """Each nation's fuel stock on the start date, with ``fuel`` on. A nation not named
    starts at ``trade.STOCK_MONTHS`` of its fuel income. Written by hand: not offered to a
    model."""
    trade_lines: SkipJsonSchema[tuple[TradeLineDecl, ...]] = ()
    """The trade lines in force on the start date, with ``fuel`` on. Written by hand: not
    offered to a model."""
    piece_kinds: SkipJsonSchema[tuple[PieceKindDecl, ...]] = ()
    """The world's own kinds of piece. With any, every force is a ``piece`` of one of
    them. Realism only, and only with a map. Written by hand: not offered to a model."""
    intelligence: SkipJsonSchema[tuple[IntelligenceDecl, ...]] = ()
    """Each nation's sources, with ``reports`` on: who reports each and by what channel,
    the codebreaking level and the agents. A world with none has contact only. Written by
    hand: not offered to a model."""
    groups: SkipJsonSchema[tuple[GroupsDecl, ...]] = ()
    """Each nation's groups at home, with ``groups`` on: support, baseline, what each
    feeds and what moves it. A world with none is unchanged. Written by hand: not offered
    to a model."""
    pacts: SkipJsonSchema[tuple[PactDecl, ...]] = ()
    """The pacts in force on the start date, with ``agreements`` on (PCT). Written by
    hand: not offered to a model."""
    conferences: SkipJsonSchema[tuple[ConferenceDecl, ...]] = ()
    """The conferences the world schedules, with ``conference`` on (CNF). Written by
    hand: not offered to a model."""
    locks: SkipJsonSchema[tuple[LockDecl, ...]] = ()
    """Which orders need whose decision, and when, with ``locks`` on (DCD). A world with
    none is unchanged. Written by hand: not offered to a model."""
    aim_patterns: SkipJsonSchema[tuple[AimPatternDecl, ...]] = ()
    """The patterns a player may fill for his own aim, with ``own_aim`` on (OWC). With the
    rule off they are checked and left out of the game. Written by hand: not offered to a
    model."""
    laws: SkipJsonSchema[tuple[LawDecl, ...]] = ()
    """The laws the world declares, with ``laws`` on (LWC): what each binds, its clauses,
    the quantity that says it has passed, and what it does. With the rule off they are
    checked and left out of the game. Written by hand: not offered to a model."""
    production: SkipJsonSchema[ProductionDecl | None] = None
    """The aid finding and the production priority the production rules read (PRL), with a
    map. A world with none runs no finding and grows no lift pool by a priority. Written by
    hand: not offered to a model."""
    map_data: SkipJsonSchema[bytes | None] = Field(default=None, exclude=True)
    """The bytes of the map file ``map`` names, read by the world loader from beside
    the world file, not from the world file itself. None when no file was found."""

    @model_validator(mode="after")
    def _roster_limit_in_order(self) -> "WorldFile":
        if self.roster_limit is not None and self.roster_limit[0] > self.roster_limit[1]:
            raise ValueError(f"roster_limit: {list(self.roster_limit)} is not least, most")
        return self

    @model_validator(mode="after")
    def _places_on_the_globe(self) -> "WorldFile":
        if self.map is not None and self.map.coords == "flat":
            return self
        for e in self.entities:
            if e.at is not None and not (-90 <= e.at[0] <= 90 and -180 <= e.at[1] <= 180):
                raise ValueError(f"entity {e.key}: at {list(e.at)} is not latitude, longitude")
        return self


__all__ = [
    "AdjacencyDecl",
    "AgentDecl",
    "AimBlankDecl",
    "AimPatternDecl",
    "AssetDecl",
    "CardDecl",
    "CharacterDecl",
    "Cited",
    "ClauseDecl",
    "ClockDecl",
    "CommitmentDecl",
    "ConferenceDecl",
    "ConflictDecl",
    "ContactDecl",
    "ContestDecl",
    "ContestMoveDecl",
    "CouncilDecl",
    "DevelopmentDeck",
    "DevelopmentDecl",
    "DevelopmentEffectDecl",
    "DispositionDecl",
    "EntityDecl",
    "FactDecl",
    "FeatureDecl",
    "FeedDecl",
    "FigureDecl",
    "GoalDecl",
    "GroupsDecl",
    "HistoryDecl",
    "IntelAgentDecl",
    "IntelSourceDecl",
    "IntelligenceDecl",
    "Key",
    "LawDecl",
    "LawDoesDecl",
    "LegDecl",
    "LeverDecl",
    "LinkDecl",
    "LockDeciderDecl",
    "LockDecl",
    "LockOrderDecl",
    "LockWhenDecl",
    "MandateDecl",
    "MapDecl",
    "MeterDecl",
    "OutletDecl",
    "PactClauseDecl",
    "PactDecl",
    "PipelineDecl",
    "QuantityDecl",
    "RegionDecl",
    "RelationshipDecl",
    "ScopeDecl",
    "ScopeSpec",
    "SeaZoneDecl",
    "SeatDecl",
    "SideDecl",
    "Slug",
    "SourceDecl",
    "StepDecl",
    "TerrainDecl",
    "TerritoryDecl",
    "TopicDecl",
    "TriggerDecl",
    "WarDecl",
    "WindowDecl",
    "WorldFile",
]
