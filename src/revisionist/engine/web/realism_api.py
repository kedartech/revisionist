"""The JSON a realism campaign's web client reads (plan, Phase 1 snapshot shape).

Types only; nothing serves them yet (unit A3 does). Every shape is built from
the seat's own ``View``, so it inherits the projection's rules, and every
response passes ``snapshot.checked`` before it is sent. Further rules the
builder must keep:

- No truth. A document is its ``DocumentView``: no ``truth_refs``, no bias.
  A quantity appears only if its own scope admits the seat.
- No odds. Realism has no feasibility bands to show.
- No AI policy. A desk is the card without voice, loyalty, doctrine or interests.
- Dates are ISO ``YYYY-MM-DD`` in-world dates, never wall-clock times, except
  ``next_wake_at``.
"""

from typing import Literal, NotRequired, TypedDict


class DocumentListItem(TypedDict):
    """One row of the in-tray. No body: the list is sent without bodies."""

    id: str
    kind: str
    """``DocumentKind`` value."""
    title: str
    author: str
    """The author's name, as the seat knows it."""
    issued: str
    arrives: str
    channel: str
    """``ChannelKind`` value."""
    classification: str
    """``Classification`` value."""
    unread: bool
    """True until the seat logs ``document_read`` for it."""
    flagged: bool
    """True while the seat's latest ``document_flagged`` for it says so."""
    group: str | None
    """The feed's name when the feed files one paper a day ("MAGIC intercepts"); None
    for a one-off paper. Rows with the same group fold into one line in the tray."""
    ack: bool
    """True when the paper only acknowledges an order (``tray.acknowledgement``): it goes to
    the conversation with its author and to the tray's Acknowledgements filter."""
    answer: bool
    """True when the paper is the report on a part of one of the seat's own orders."""


class DocumentListing(TypedDict):
    documents: list[DocumentListItem]
    """Arrived documents in the seat's scope, newest arrival first."""
    unread: int
    """Unread papers that are not acknowledgements."""
    flagged: int


class BodyLine(TypedDict):
    label: str
    value: int | str | None
    """None: the author is silent on it."""
    unit: str


class DocumentPage(TypedDict):
    """A single document, fetched on its own."""

    item: DocumentListItem
    body: list[BodyLine]
    prose: str | None


class StepLine(TypedDict):
    """One step of an order as it reached the issuer."""

    step: int
    person: str
    kind: Literal["decision", "clerical"]
    action: str | None
    """``StepAction`` value once acted on; None while the order waits there."""
    on: str | None


class OrderTrack(TypedDict):
    """The pipeline tracker for one of the seat's own orders."""

    id: str
    lever: str
    label: str
    """The lever's label on the viewer's card, in words."""
    terms: list[str]
    """Each parameter as "Which bill: Revise the Neutrality Act"."""
    pipeline: str
    params: dict[str, int | str]
    status: str
    """``OrderStatus`` value."""
    filed: str
    at_step: int
    with_person: str | None
    """Who holds it now ("with Rayburn since 12 Oct"); None once settled."""
    since: str | None
    steps: list[StepLine]
    decision_needed: bool
    """True when the step it waits at is held by this seat."""


class OrderTracker(TypedDict):
    orders: list[OrderTrack]
    """The seat's own orders only, newest first."""


class Clock(TypedDict):
    """Clock and pace: replaces "N days a turn", which an event-driven clock makes false."""

    world_date: str
    next_wake_at: str | None
    """Wall-clock ISO time of the next advance; None while paused."""
    next_world_date: str | None
    """The in-world date the next advance runs to."""
    waiting_on: str | None
    """What the next advance waits for ("Rayburn's count expected ~14 Oct")."""
    days_collapsed: int
    """Quiet in-world days the last advance passed over ("9 quiet days passed")."""


class ContactLine(TypedDict):
    person: str
    title: str | None
    """The office on the person's public card face, if they have a card."""
    channel: str
    channels: list[str]
    """How a directive can reach them, their own channel first."""


class LeverChoice(TypedDict):
    value: str
    """What is posted back."""
    label: str


class PlaceReach(TypedDict):
    """How far a force's side can hold it at a place, by the reach rule."""

    tier: Literal["sustained", "operate", "raid", "refused"]
    base: str | None
    """The base the tier is measured from (the place itself when sustained); for a refusal,
    the nearest base the force can work from. None when there is none."""
    reason: str | None
    """Why the place is refused, naming that base. None for every other tier."""


class PlaceLift(TypedDict):
    """What an army's crossing by sea to a place takes, as the seat's own papers show it."""

    need: int
    """The tonnage the lift draws from its side's pool, by the sealift rule."""
    reported: int | None
    """The side's pool as the seat's latest page reporting it gave it; None before any has."""


class PlaceChoice(TypedDict):
    """One place a movement form can send a force to, as the seat's own pages show it."""

    value: str
    """What is posted back: the same value as its entry in ``choices``."""
    label: str
    group: Literal["own", "allied", "route", "contested", "other"]
    """Own: the form's own destinations and places the seat's papers put its own forces.
    Allied: an ally's force is placed there. Route: on a convoy route a page shows.
    Contested: on a front, or another side's force is placed there. Other: the rest."""
    days: dict[str, int | None]
    """For each choice of the form's ``force``: days to arrive from where the seat's
    latest page places that force (0 if it is there), by the movement resolver's route (for
    an army crossing by sealift, the march to its port and the voyage); None when no page
    places it, or when no passage open to its side reaches the place."""
    reach: dict[str, PlaceReach | None]
    """For each choice of the form's ``force``: its tier at the place, from where the seat's
    latest page places it and the forces and fronts its pages show. A refused place stays
    listed. None when no page places the force, or the world has no bases."""
    lift: dict[str, PlaceLift | None]
    """For each choice of the form's ``force``: what its crossing by sea to the place takes,
    from where the seat's latest page places it. None when it does not cross by sealift
    (another kind, its own land, a refused crossing, a side with no pool) or no page places it."""


class LeverParam(TypedDict):
    name: str
    label: str
    kind: Literal["int", "enum", "entity", "text"]
    lo: int | None
    hi: int | None
    choices: list[LeverChoice]
    places: list[PlaceChoice]
    """A movement form's destination: every place in ``choices``, grouped and with days.
    Empty for every other parameter, and when the campaign's world file cannot be read."""
    areas: dict[str, dict[str, str]]
    """A movement form's destination on a territory map: for each force in the form's
    ``force`` choices, each place in ``choices`` and the key of the area that force would
    stand in there (a sea piece at a port: the zone the port opens on). Map geography only.
    Empty for every other parameter and in a game without territories."""


class LeverLine(TypedDict):
    name: str
    label: str
    summary: str
    pipeline: str
    params: list[LeverParam]
    """The draft form is built from these."""
    rule: str
    """The rule name the lever's order is resolved by."""
    intel: str | None
    """For a form with the rule name ``intel``, which of the five intelligence orders it
    gives (``recon``, ``patrol``, ``agent``, ``codebreaking``, ``conceal``); else None."""


class DirectiveProposal(TypedDict):
    """The order the aide read a directive as, for the player to sign or revise."""

    to: str
    channel: str
    text: str
    lever: str | None
    """Posted back on signing; None when it cannot be done."""
    label: str | None
    terms: list[str]
    params: dict[str, int | str]
    reason: str | None
    """Why it cannot be done, in words."""


class Desk(TypedDict):
    """The seat's own card, without its AI policy fields."""

    office: str
    powers: list[str]
    levers: list[LeverLine]
    inner_circle: list[ContactLine]
    principals: list[str]
    constraints: list[str]
    personal: list[str]
    horizon_days: int
    aims: list[str]
    """What the person was set on at the start; not binding."""


class SituationReading(TypedDict):
    """One report of a figure by one source."""

    value: int | None
    """None: that report was silent on it."""
    issued: str
    arrives: str


class SituationSource(TypedDict):
    """What one person has reported of a figure, latest report first in the fields."""

    author: str
    doc_id: str
    """The latest report, to open it from the board."""
    value: int | None
    """The latest report's figure; None is a gap, never an estimate."""
    issued: str
    arrives: str
    last_given: str | None
    """When a figure was last given (issue date); None if never."""
    trend: Literal["up", "down", "level"] | None
    """The latest figure against the one given before it; None for a gap or a first report."""
    history: list[SituationReading]
    """This source's latest reports of it (at most six), oldest arrival first."""


class SituationFigure(TypedDict):
    """One headline figure, as each source that reports it has it."""

    label: str
    unit: str
    sources: list[SituationSource]
    """By author name. Never averaged: two sources that differ are both shown."""
    disagree: bool
    """True when the sources' latest figures differ."""


class Situation(TypedDict):
    """The situation board: figures from arrived pages only, never from the record."""

    figures: list[SituationFigure]


class Threat(TypedDict):
    """One person set against the seat, as the seat's staff believe it: the stance
    on the last day they had evidence, never the engine's score."""

    person: str
    name: str
    office: str
    stance: str
    """``hostile`` or ``obstructing``."""
    stance_label: str
    trend: Literal["worse", "better", "steady"]
    """Against the stance the staff knew before this one."""
    as_of: str
    """The last day the seat had evidence about the person (ISO date)."""
    confidence: Literal["firm", "dated", "old"]
    """From the age of that evidence."""
    over: list[str]
    """What the world file says the two are at odds over."""
    cause: str
    """Why the stance changed, in words, where the seat saw it."""


class PeopleMeter(TypedDict):
    """One staff assessment of a person in five steps, never the engine's number."""

    step: int | None
    """1 the worst to 5 the best; None when the staff have nothing to go on."""
    word: str
    as_of: str | None
    """The day of the evidence it rests on (ISO date); None with none."""
    confidence: Literal["firm", "dated", "old"] | None
    """From the age of that evidence."""


class PersonHold(TypedDict):
    """One of the seat's own orders waiting at the person's step."""

    id: str
    """The order's id, as in ``orders``."""
    label: str
    since: str
    """The in-world day it reached this step (ISO). A stall there does not move it."""
    held_days: int
    days: int | None
    """The days the step is stated to take; None while that is an unsourced gap."""
    read: Literal["likely to pass it", "may hold it", "likely to hold or refuse it"] | None
    """The staff's read of what the person will do with it, from their loyalty, the
    order's topics and the seat's own load on them, with no roll. Only for the seat's
    own chain and inner circle; None for anyone else or a step a player holds."""


class PersonTally(TypedDict):
    """What the person did with the seat's own orders at their step, by action. A hold
    or a leak counts only once the seat has the reply that says so."""

    passed: int
    hurried: int
    held: int
    amended: int
    refused: int
    leaked: int


class PersonChannel(TypedDict):
    """How the seat reaches a member of its inner circle first, and the days it takes."""

    channel: str
    """``ChannelKind`` value."""
    days: int


class PersonLine(TypedDict):
    """One person on the People roster, as the seat's staff know them."""

    person: str
    name: str
    office: str
    stance: PeopleMeter | None
    """Toward the seat, fogged as the opponents list is. Only for the people weighed
    against the seat; None for everyone else."""
    trend: Literal["worse", "better", "steady"] | None
    """The stance against the one the staff knew before it; None with no stance."""
    over: list[str]
    """What the world file says the two are at odds over."""
    at_war: bool
    """The person's country and the seat's are at war."""
    last_answer: str | None
    """Their latest answer to one of the seat's orders, in words, with its date."""
    regard: PeopleMeter
    """Their disposition toward the seat's person, where the seat knows it."""
    reliability: PeopleMeter
    """How they carried the seat's own orders: fidelity, lateness and refusals."""
    holds: list[PersonHold]
    """The seat's own orders waiting on them, oldest first. Never another seat's."""
    load: int
    """How many of the seat's own orders they hold."""
    tally: PersonTally
    pace: PeopleMeter
    """Days taken at their step against the days stated, over the seat's own orders
    they moved on; "Untested" with none."""
    standing: NotRequired[PeopleMeter]
    """Their rank in the world, in five steps. Rank is hidden card policy, so only for
    the seat's own chain and inner circle; absent for anyone else."""
    bloc: str | None
    """The name of the body they belong to (Navy Department, Senate); None with none."""
    channel: PersonChannel | None
    """For a member of the seat's inner circle; None for anyone else."""
    power: PeopleMeter | None
    """For a leader weighed against the seat: rank, a step higher once the seat's own
    pages place three forces of theirs. None for everyone else."""
    portrait: str | None
    """The file under ``/assets/portraits/`` their dossier names; None with none."""
    loyalty: NotRequired[PeopleMeter]
    """Only for the seat's own chain and inner circle; absent for anyone else."""
    competence: NotRequired[PeopleMeter]
    """Only for the seat's own chain and inner circle; absent for anyone else."""
    wants: NotRequired[list[str]]
    """The names of the topics they want. Only for the seat's own chain and inner circle."""
    holds_to: NotRequired[list[str]]
    """The names of the topics they hold to. Only for the seat's own chain and inner circle."""


class People(TypedDict):
    """The People roster: the leaders weighed against the seat, the seat's own chain
    and inner circle, and everyone else with an office."""

    opponents: list[PersonLine]
    yours: list[PersonLine]
    others: list[PersonLine]


class WorldDevelopment(TypedDict):
    """One public development that has fired, for "The world" tab of the press desk."""

    id: str
    """An opaque token."""
    on: str
    """The in-world day it happened, ISO."""
    category: str
    """In words ("Public figures", "Weather")."""
    headline: str
    asks: list[str]
    """The orders it suggests, in words; it never files one itself."""


class WarNation(TypedDict):
    """A nation at war, by the game's id for it and its name."""

    key: str
    name: str


class PublicWar(TypedDict):
    """A war as the public record has it: the same for every seat."""

    a: WarNation
    """The nation that declared it."""
    b: WarNation
    since: str
    """The day it began, ISO."""


class StakeLean(TypedDict):
    """Which way a contest's track leans, once it has moved in this game. Never the track."""

    step: int
    """1 to 10 across the track: 10 is wholly the first side's way, 1 wholly against it."""
    favours: str | None
    """The side the track favours now, by name; None when level or a trial not yet passed."""


class Stake(TypedDict):
    """One contest the seat's view holds."""

    name: str
    prize: str
    sides: list[str]
    """Each side by name, in the contest's order."""
    days_left: int
    """Days from the world date to the deciding day; 0 once it is past."""
    lean: StakeLean | None
    """None until the contest's track has moved in this game."""


class StakeDecided(TypedDict):
    """One decided contest the seat's view holds, with the side it was decided for (SCD)."""

    name: str
    prize: str
    sides: list[str]
    winner: str | None
    """The winning side by name; None when it was decided for no side."""


class StakeMandate(TypedDict):
    """One of the seat's own open mandates."""

    text: str
    days_left: int
    """Days from the world date to its deadline; 0 once it is past."""


class StakeLeaf(TypedDict):
    """One check of an aim's condition as the seat may see it (SCD)."""

    reads: str
    """What the check reads, in words."""
    seen: str
    """``public``, ``own`` (its own nation's) or ``uncertain`` (hidden from the seat)."""
    holds: bool | None
    """Whether it holds now; None for an uncertain check."""
    evidence: list[str]
    """What the seat's own view shows of it, in words: public facts and its own nation's,
    or for an uncertain check only what its own reports hold; possibly none."""


class StakeAim(TypedDict):
    """One of the seat's own aims, with its status and why (SCD)."""

    aim: int
    """Which of the card's aims, counting from 1."""
    text: str
    source: str
    """Where the aim comes from: ``post``, ``player`` or ``replacement``."""
    status: str
    """``met``, ``at_risk`` or ``failed``; never reveals a fact hidden from the seat."""
    rule: str
    """The success rule in plain words."""
    opens: str | None
    """The first day it is judged (ISO date); None: from the start."""
    deadline: str | None
    """The last day it is judged (ISO date); None: to the season's end."""
    leaves: list[StakeLeaf]
    reason: str
    """Why it has its status, in words."""


class Stakes(TypedDict):
    """What is at stake for the seat: open contests, then its own open mandates, soonest
    first; then the decided contests with their winners, its own aims, the degree of the
    win they make as they stand, the drift from history and the days to the season's end
    (SCD)."""

    contests: list[Stake]
    mandates: list[StakeMandate]
    decided: list[StakeDecided]
    aims: list[StakeAim]
    degree: str | None
    """``full win`` with three of three aims holding, ``win`` with two of three (or
    every aim of a card with fewer than two), else None. No points total."""
    drift: int
    """How far the world has drifted from history (public)."""
    season_days_left: int | None
    """Days from the world date to the season's end; None when no contest decides it."""


class AimValue(TypedDict):
    """One value a blank may take as the seat's view allows (OWR)."""

    value: str | int
    """What the seat sends back for it."""
    label: str
    """Its name, as the aim would read it."""


class AimBlankLine(TypedDict):
    """One blank of a pattern, with the values the seat may fill it with (OWR)."""

    name: str
    values: list[AimValue]


class AimPatternLine(TypedDict):
    """One pattern on the seat's ladder (OWR)."""

    key: str
    sentence: str
    """The aim in words, each blank written ``{name}``."""
    blanks: list[AimBlankLine]
    difficulty: int | None
    """Its easiest fill's, on the aims' rubric; None when no fill stands now."""
    government: bool
    """Whether the person's own government would issue it."""


class OwnAimBlock(TypedDict):
    """The patterns the seat may fill to replace its card's replaceable aim, easiest first,
    while it may still set one (OWR). Absent otherwise, and with ``own_aim`` off."""

    aim: int
    """Which of the card's aims it replaces, counting from 1."""
    replaces: str
    """That aim's words."""
    patterns: list[AimPatternLine]


class AimCheck(TypedDict):
    """What a filled pattern makes (OWR): it stands, with the sentence as it reads; or the
    reasons it cannot, in fixed words. Answered by ``aim-check`` and ``aim-set`` alike."""

    stands: bool
    text: str | None
    """The aim as it reads (as stored, after a set); None when it does not stand."""
    reasons: list[str]


class CourtOrder(TypedDict):
    """One of the seat's own orders waiting at a step."""

    id: str
    """The order's id, as in ``orders``."""
    label: str
    since: str
    """The in-world day it reached this step (ISO). A stall there does not move it."""
    held_days: int


class CourtStep(TypedDict):
    """One person on a path, in the order an order reaches them."""

    person: str
    name: str
    office: str | None
    """The office on the person's public card face; None without a card."""
    kind: Literal["decision", "clerical"]
    days: int | None
    """The days the step typically takes; None while that is an unsourced gap."""
    you: bool
    """The step is the seat's own person."""
    orders: list[CourtOrder]
    """The seat's own orders waiting here, oldest first. Never another seat's."""


class CourtPath(TypedDict):
    """One pipeline the seat's own forms use."""

    id: str
    name: str
    forms: list[str]
    """The labels of the seat's forms that travel it."""
    steps: list[CourtStep]


class CourtRing(TypedDict):
    """One of the seat's inner circle or chain who is on no path."""

    person: str
    name: str
    office: str | None
    channel: str
    """The channel the seat reaches them by first."""


class ChamberSeats(TypedDict):
    party: str
    seats: int


class ChamberVote(TypedDict):
    """A public vote in the chamber, as its yeas and nays."""

    name: str
    yeas: int
    nays: int
    as_of: str


class Chamber(TypedDict):
    """A body of the seat's own country that owns public seat figures."""

    name: str
    seats: list[ChamberSeats]
    carries: int
    """The yeas that carry a vote when every member votes: more than half the seats."""
    votes: list[ChamberVote]
    """Newest first; only votes with both figures set."""


class Court(TypedDict):
    """The seat's own people on the paths its forms travel, with its orders on them,
    the circle and chain no path reaches, and its country's chambers."""

    paths: list[CourtPath]
    ring: list[CourtRing]
    chambers: list[Chamber]
    load_limit: int
    """The orders a person carries before load counts against an order."""


class MapPlace(TypedDict):
    name: str
    lat: float
    lon: float
    theatre: str | None
    """The theatre the world file puts the place in; None when it names none."""


class PieceArea(TypedDict):
    """Where a piece stands or is going: an area of the map, or in a game without
    territories the place itself."""

    key: str | None
    """The area's key in the map file; in a game without territories, the place's world
    key (None when the caller gave no place keys)."""
    name: str
    place: MapPlace | None
    """The place it stands at when that place has a position; None in an area without one."""


class MarkArea(TypedDict):
    """The area (a territory or a sea zone) a page places a sighted piece in."""

    key: str
    """The area's key in the map file."""
    name: str


class PieceWait(TypedDict):
    """The seat's own order for the piece, still with a holder. The same words whoever
    holds it, a player or not."""

    order: str
    with_person: str | None
    until: str | None
    """The day the step it waits at falls due; None when the step has no length."""
    withdrawable: bool


class PieceCourse(TypedDict):
    """A piece under way."""

    path: list[PieceArea]
    """The areas still to enter, in order; the first is the step it is on. Without
    territories, the one place it is bound for."""
    step_due: str | None
    """The day the step into ``path[0]`` completes."""
    step_began: str | None
    """The day the step into ``path[0]`` began: the day whose step, counted by the step
    rule with that day's weather, falls due on ``step_due``. None without territories, or
    when no such day is found."""
    step_days: int | None
    """The days the step into ``path[0]`` takes, by the step rule on ``step_began``."""
    arrives: str | None


class PieceFigures(TypedDict):
    """A piece's five figures, each a step from 1 to 5 (KVW)."""

    attack: int
    defence: int
    speed: int
    """From the days a step takes: the fewer, the higher."""
    reach: int
    """The steps it acts at from where it stands: an air kind's range or a striking kind's
    strike steps; 1 for a kind that acts only where it stands."""
    hidden: int
    """From its kind's concealment."""


FigureName = Literal["attack", "defence", "speed", "reach", "hidden"]
FigureCause = Literal[
    "terrain", "weather", "out_of_supply", "out_of_fuel", "air_cover", "enemy_kind"
]


class FigureChange(TypedDict):
    """One thing changing a piece's figure where it stands or would stand: the figure,
    the direction and the cause, in fixed words. Never the amount."""

    figure: FigureName
    direction: Literal["up", "down"]
    cause: FigureCause
    words: str
    """The cause as the seat reads it: the ground, the weather's name, the enemy kind
    reported there, or the cause's own fixed words."""


class PieceKindView(TypedDict):
    """An own piece's kind and its figures as the seat sees them (KVW): sent only with
    ``kinds_in_battle`` on, for a piece of a kind the world names."""

    key: str
    name: str
    picture: str | None
    """The key of the picture the client draws the kind with; None when the world names none."""
    figures: PieceFigures
    """The kind's own figures."""
    here: PieceFigures
    """The figures where the piece stands, today."""
    changes: list[FigureChange]
    """What changes them there, in the order applied."""


class WeatherEffect(TypedDict):
    """One thing a kind of weather does to one of the seat's own kinds."""

    kind: str
    """The own kind's key."""
    figure: FigureName
    direction: Literal["up", "down", "closed"]
    """Closed: the areas are shut to the kind while the weather holds."""
    terrain: list[str]
    """The terrain keys it acts on; empty for every terrain."""


class WeatherKindView(TypedDict):
    key: str
    name: str
    does: list[WeatherEffect]
    """What it does to each of the seat's own kinds; the rest of the block is the same
    for every seat."""


class RegionWeather(TypedDict):
    region: str
    now: str | None
    """The key of the weather this month; None for a region the table does not reach."""
    next: str | None


class WeatherBlock(TypedDict):
    """Every region's weather this month and next (KVW): the calendar's, public, the same
    for every seat apart from what each weather does to its own kinds."""

    month: str
    next_month: str
    regions: list[RegionWeather]
    kinds: list[WeatherKindView]
    """The kinds of weather that hold somewhere this month or next."""


class OddsCause(TypedDict):
    """The cause that moved the odds most: the one whose absence changes the win share
    most, and whether it is for the seat's side or against it."""

    cause: FigureCause
    words: str
    direction: Literal["for", "against"]


class MapLift(TypedDict):
    """The lift a move by sea draws for a land piece."""

    tons: int
    """What the move takes from its nation's shipping the day it sets out."""
    carrier: str
    """The world's name for the kind that carries it."""


class MapMove(TypedDict):
    """One area an own piece can be sent to, lit from the seat's own view (TMD): the
    movement rule's own course, planned on a board holding only what the view holds."""

    area: PieceArea
    path: list[PieceArea]
    """The areas entered, in order; the last is ``area``."""
    step_days: list[int]
    """The days each step of ``path`` takes."""
    days: int
    reach: Literal["sustained", "operate", "raid"] | None
    """The reach tier of ``area`` from the bases of the piece's side; None where no reach
    rule applies (a board with no bases, or an envoy)."""
    lift: MapLift | None
    """The lift the move draws; None when it draws none."""
    figures: NotRequired[PieceFigures]
    """With ``kinds_in_battle`` on: the piece's figures as they would stand in ``area`` on
    the day it would arrive, from the seat's reports alone."""
    changes: NotRequired[list[FigureChange]]


class MapPiece(TypedDict):
    """One of the seat's own pieces, from the truth: only on the marks of forces the
    seat's own movement forms name."""

    key: str
    """The mark's own key."""
    kind: str
    """The world's name for its kind, or the force kind in words."""
    domain: str
    """``land``, ``sea``, ``air`` or ``envoy``."""
    strength: int
    posture: str | None
    area: PieceArea
    waiting: PieceWait | None
    under_way: PieceCourse | None
    moves: NotRequired[list[MapMove]]
    """In a territory game only: every area the piece can be sent to, by area key."""
    figures: NotRequired[PieceKindView]
    """With ``kinds_in_battle`` on, for a piece of a kind the world names."""


class MapMark(TypedDict):
    """One force, front or route as the seat's latest page about it places it, or one of
    the seat's own pieces no page has placed yet (``reported`` is then today, ``source``
    and ``document`` empty, and ``places`` empty in an area without a position)."""

    key: str
    """Opaque and stable: the same for every seat of one nation, different for another
    nation's: a deployment-secret MAC (``map_api.mark_key``), never a raw core mark or id."""
    name: str
    kind: Literal["fleet", "army", "air", "front", "route", "piece"]
    """Piece: one of the world's own kinds, in a world with ``piece_kinds``."""
    side: Literal["own", "other", "none"]
    """Own: the seat's own polity or body. None: a front, which is both sides'."""
    side_name: str
    certainty: Literal["known", "reported", "stale"]
    """Known: the seat's own side, freshly reported. Stale: the page is older than
    ``STALE_DAYS``. A feature no page has placed is not on the map at all."""
    places: list[MapPlace]
    """The places the page names that have a position."""
    area: MarkArea | None
    """The area without a position the page names, in a territory game; None when the
    page names only places with a position."""
    reported: str
    """The page's issue date: where it was then, not now."""
    source: str
    """The author's name."""
    document: str
    """The page's id, to open it from the map."""
    strength: int | None
    """The strength a line of the seat's latest page gives under the mark's name; None
    while no page has stated one, whatever the truth."""
    piece: MapPiece | None
    """The seat's own piece behind the mark; None for every other mark."""


class MapReport(TypedDict):
    """One report of an enemy piece that has reached the seat's nation (RPD), as its view
    holds it: a wrong report is worded and shaped exactly like a right one."""

    key: str
    """Opaque and stable for one piece: the same for every seat of one nation, whichever
    source made the report and whether it is right; the web MAC of the nation's report key."""
    kind: str | None
    """The world's piece kind key; None: the report does not know it."""
    kind_name: str
    """The kind as the world names it, or "unknown"."""
    strength_low: int | None
    strength_high: int | None
    """The range the report gives; both None when it gives no strength (a decrypt)."""
    area: MarkArea | None
    """The area the report places the piece in; None for a decrypt, which gives a region."""
    bound_for: str | None
    """A decrypt: the region key the piece is bound for; else None."""
    seen: str
    source: Literal["contact", "air", "patrol", "codebreaking", "agent"]
    person: str
    """The name of the person the world names for the source; "" for a contact no one is
    named for, which comes with no paper."""
    confidence: Literal["A", "B", "C"]
    document: str | None
    """The id of the paper that carried the report; None for a contact no one is named for."""
    ring: list[str] | None
    """Once the report is more than ``RING_AFTER_DAYS`` days old: the keys of every area a
    piece of its kind could have reached from its area since the day seen, its own area
    included, in the board's order (an unknown kind moves as every kind of its area's
    domain, so the fastest bounds it). Worked out from the report and the board alone.
    None while the report is fresh, and for a decrypt, which gives no area (RNG)."""
    picture: NotRequired[str]
    """With ``kinds_in_battle`` on, for a report that names a kind the world gives a
    picture: the picture's key, the kind's as every seat has it (KPC)."""


class MapOrder(TypedDict):
    """One of the seat's own orders to move a force, drawn until a page shows it arrived."""

    order: str
    force: str
    """The force as the order names it."""
    mark: str | None
    """The name of that force's mark on this map, when a page has placed it."""
    to: MapPlace
    status: Literal["awaiting", "under_way"]
    """Awaiting: still in its pipeline. Under way: carried out, not yet reported there."""
    with_person: str | None
    filed: str


class MapCapital(TypedDict):
    """A leader the People roster weighs against the seat, at their own place."""

    place: MapPlace
    name: str
    stance: PeopleMeter
    """The roster's stance for them, fogged as the roster fogs it."""
    at_war: bool
    """Their country and the seat's are at war."""


class MapNation(TypedDict):
    """A nation as the seat names it: its entity id, its name, and how it stands to the
    seat's own nation (an ally is at war with a common enemy and not with the seat's)."""

    key: str
    name: str
    relation: Literal["own", "ally", "enemy", "neutral"]


class MapArea(TypedDict):
    """One area of the board: its key in the map file, its name and who it borders; for
    a land area with ``holders`` on, who holds it. A sea zone has no holder."""

    key: str
    name: str
    kind: Literal["land", "sea"]
    region: str
    """The region's key."""
    terrain: str
    """The terrain's key."""
    neighbours: list[str]
    """The keys of the areas it borders or is joined to by a crossing, sorted."""
    holder: MapNation | None
    """The nation holding it now; None for a sea zone, with ``holders`` off, or held by
    nobody. Public."""
    held_since: str | None
    """The day it last changed hands; None while it has the holder the world gives it."""
    taken_from: MapNation | None
    """The holder it was last taken from; None while it never changed hands."""
    falling: str | None
    """For the holding nation's seats only: the day a capital in it was marked to fall
    (it falls at the close of the wake after that day's, unless relieved). None
    otherwise."""
    yields: dict[str, float]
    """What the board prints it yields, by resource key; a moved yield is not shown here.
    Empty for a sea zone."""
    threatened_from: list[str] | None
    """In a game with ``reports`` on, for a territory the seat's nation holds: the keys of
    the reports whose area or ring takes in this area or one next to it, sorted. None for
    every other area, and in a game without ``reports`` (RNG)."""


class MapRegion(TypedDict):
    key: str
    name: str
    parent: str | None
    """The key of the region it lies within; None for a top region."""


class MapFile(TypedDict):
    """The map file the game was started on: the shapes the ``map`` action serves."""

    name: str
    sha256: str


class SeatMap(TypedDict):
    """The map: places are public; marks come from arrived pages only, never the record."""

    places: list[MapPlace]
    marks: list[MapMark]
    orders: list[MapOrder]
    """The seat's own movement orders: what it has ordered, not where anything is."""
    capitals: list[MapCapital]
    """For each leader on the roster's opponents with a stance and a place, most hostile
    first. A leader with no stance or no place has none."""
    reports: NotRequired[list[MapReport]]
    """In a game with ``reports`` on only: each enemy piece the seat's nation holds a
    report of, by key. They replace the marks of other sides' pieces, which are not sent."""
    areas: NotRequired[list[MapArea]]
    """In a territory game only (as the four keys after it): every territory and sea
    zone of the board, territories first, in the world file's order. The same for every
    seat; the shapes come from the ``map`` action."""
    regions: NotRequired[list[MapRegion]]
    coords: NotRequired[Literal["lonlat", "flat"]]
    box: NotRequired[list[float] | None]
    """``[west, south, east, north]``; None when the world names none."""
    file: NotRequired[MapFile]
    weather: NotRequired[WeatherBlock]
    """With ``weather`` on, in a territory game whose board holds a weather table."""


class EconomyFigure(TypedDict):
    """One nation's public war-economy figure: the same for every seat."""

    nation: MapNation
    figure: float
    """The weighted sum of its output, manpower and fuel incomes from what it holds, the
    largest nation at the start being 100."""


class EconomyIncome(TypedDict):
    """The seat's own nation's income of one resource, by the world's name and unit."""

    key: str
    name: str
    unit: str
    role: Literal["output", "manpower", "fuel", "supply", "prestige"]
    amount: float
    """The sum of the resource's yield over the territories it holds, each times its
    factor for the resource's role, on the block's day."""


class EconomyTerritory(TypedDict):
    """A territory the seat's own nation holds: what it yields now and what share of it
    the nation gets, by role (0 to 1)."""

    area: str
    """The area's key in the map file."""
    name: str
    yields: dict[str, float]
    """What it yields now, by resource key: as moved, else as printed."""
    factors: dict[str, float]
    """By role: ``output``, ``manpower``, ``fuel``, ``supply``, ``prestige``."""


class EconomyPools(TypedDict):
    output: NotRequired[float]
    manpower: NotRequired[float]
    """Output and manpower: not sent to a commander held to his post."""
    fuel: NotRequired[float]
    """The fuel stock; sent only in a game with ``fuel`` on."""


class RaiseCost(TypedDict):
    output: float
    manpower: float


class RaiseKind(TypedDict):
    """A kind of piece a place can raise, as filing an order for it today would go."""

    kind: str
    """The kind's key, the value the form's ``kind`` takes."""
    name: str
    cost: RaiseCost
    lead_days: int
    arrives: str
    """The day the piece would arrive if each step of the order is taken on its day."""
    pools_after: EconomyPools
    """Output and manpower after its cost, and after the cost of every raising of the
    nation due on or before that day."""
    refusal: str
    """Why the check refuses it now, in its fixed words; empty when it may be filed."""


class RaisePlace(TypedDict):
    """A place of the nation's own where the seat's form can raise a piece."""

    place: str
    """The place's key, the value the form's ``place`` takes."""
    name: str
    area: str
    """The key in the map file of the territory it stands in."""
    form: str
    """The form that raises there."""
    kinds: list[RaiseKind]


class RaisingLine(TypedDict):
    """A piece the seat's nation is raising."""

    kind: str
    name: str
    """The kind's name."""
    place: str
    place_name: str
    area: str
    day: str
    """The day it arrives: the day the rule decides it once the order is enacted, else the
    day it would if each step is taken on its day."""
    fixed: bool
    """Whether the order is enacted, so the day is the rule's."""
    picture: str | None
    """The key of the picture the client draws the kind with; None when the world names none."""


class EconomyOwn(TypedDict):
    """The seat's own nation's economy. No other nation's is ever sent."""

    nation: MapNation
    income: list[EconomyIncome]
    """Every resource the world names, in the world file's order."""
    pools: EconomyPools
    """What the first of each month has paid in so far."""
    fuel_months: float | None
    """Months its fuel stock lasts at its monthly fuel income, trade lines included; None while
    the game keeps no stock or the nation has no fuel income."""
    territories: list[EconomyTerritory]
    """Every territory it holds, by area key."""
    places: NotRequired[list[RaisePlace]]
    """With ``raising`` on: each place where the seat's own forms can raise, by key; empty
    for a seat with no such form or held to its post."""
    raising: NotRequired[list[RaisingLine]]
    """With ``raising`` on: every piece the nation is raising, by day."""


class EconomyBlock(TypedDict):
    """The war economy as the seat sees it, with ``economy`` on."""

    day: str
    """The in-world day the figures and incomes are counted for."""
    figures: list[EconomyFigure]
    """Every nation's figure, highest first, then by name."""
    own: EconomyOwn | None
    """None for a seat of no nation."""


class GroupMove(TypedDict):
    """What last moved a group: the cause, by how much after the clamp, and the day."""

    cause: Literal[
        "battle_won",
        "battle_lost",
        "territory_taken",
        "territory_lost",
        "capital_threatened",
        "losses_at_sea",
        "agreement_broken",
        "measure_passed",
        "war_declared",
        "daily_life_passed",
        "writing",
        "drift",
        "offer_taken",
        "promise_kept",
        "promise_broken",
        "battle_losses",
        "losses_felt",
        "losses_halved",
        "place_lost",
        "place_abandoned",
        "place_retaken",
    ]
    change: int
    on: str


class HomeMove(TypedDict):
    """A move of a group since the seat's last wake (HFR): the cause, by how much after
    the clamp, the day and the cause in plain words."""

    cause: str
    """A ``GroupMove`` cause."""
    change: int
    on: str
    why: str
    """The cause in plain words (``home_api.WHY``)."""
    reach: Literal["felt", "reported"]
    """How it reached the public (``home_api.reach``)."""


class HomeMoved(TypedDict):
    """One line of what moved at home since the seat's last wake: a group, its net
    change and the line the seat reads (HFR)."""

    group: str
    name: str
    change: int
    line: str


class HomePlace(TypedDict):
    """A place of political weight of the seat's nation, as its map shows it (HFR)."""

    key: str
    """The territory's key in the map file."""
    name: str
    holder: MapNation | None
    threatened: bool
    """Its area on the seat's map is marked to fall or named by a report (``MapArea``)."""


class HomeGroup(TypedDict):
    """One of the seat's own nation's groups at home (GPD)."""

    key: str
    name: str
    kind: str
    """The world's free label: a party, a union, a service, the public."""
    support: int
    """0 to 100, now."""
    last_moved: GroupMove | None
    """None while nothing has moved it."""
    since: list[HomeMove]
    """Every move since the seat's last wake, in the order they happened."""
    feeds: dict[str, float]
    """What its support feeds (``votes``, ``standing``, ``manpower``, ``output``,
    ``opinion``), each with its weight."""


class FloorBloc(TypedDict):
    """A bloc of a chamber: one of the seat's own nation's groups that sits in it."""

    group: str
    name: str
    seats: int
    support: int


class BlocCount(TypedDict):
    """A bloc's part of one vote."""

    group: str
    yeas: int
    nays: int
    then: list[int] | None
    """Its yeas and nays at the seat's last wake; None when the measure was not then on
    its way, or the seat has had no wake."""
    moved: bool
    """Its count differs from ``then``."""


class FloorVote(TypedDict):
    """One vote of an open measure in a chamber, counted by bloc."""

    vote: str
    """The vote's key in the world file (for example the chamber's own key)."""
    yeas: int
    nays: int
    blocs: list[BlocCount]
    """Each bloc with a row for the vote, in the world's order."""
    carries: int
    """The yeas that carry the vote: more yeas than nays among those voting, as the votes
    rule decides it."""
    then: list[int] | None
    """The vote's yeas and nays at the seat's last wake, as ``BlocCount.then``."""


class OpenMeasure(TypedDict):
    """A measure the seat has sent that is still on its way, counted as the votes rule
    would tally it if it reached the floor today."""

    order_id: str
    key: str
    """The measure's key: the bill named, or the carried measure's title as a key."""
    title: str
    votes: list[FloorVote]
    """The votes of this chamber the measure faces."""


class FloorChamber(TypedDict):
    """A chamber of the seat's own nation: its blocs and the seat's open measures."""

    key: str
    blocs: list[FloorBloc]
    measures: list[OpenMeasure]


class HomeTheme(TypedDict):
    """A theme the nation's writing may name, and the points it moves each group by."""

    key: str
    name: str
    moves: dict[str, int]


class NationStanding(TypedDict):
    """A nation's standing at home as a public band, the same for every seat."""

    nation: MapNation
    band: Literal["collapsing", "shaken", "steady", "firm", "united"] | None
    """None for a nation with no group that feeds standing."""


class OfferPrice(TypedDict):
    """One thing a bloc would take for its votes (PRR rule 2)."""

    key: str
    sentence: str
    """What is promised, as the seat reads it."""
    points: int
    """Points the offer moves the bloc's yes share by on the measure."""
    days: int
    """World days after the measure passes on which the promise is read."""
    loss: int
    """Support the bloc loses when the promise is broken."""


class LiveOffer(TypedDict):
    """The offer that holds a bloc on a measure."""

    price: str
    points: int
    mine: bool
    """Whether the seat itself made it."""


class OfferBloc(TypedDict):
    """One bloc of a chamber, for a measure on its way: what it would take, and the offer
    that holds it if one does."""

    group: str
    name: str
    prices: list[OfferPrice]
    """In the world's order; empty for a bloc that names no price."""
    live: LiveOffer | None


class OfferMeasure(TypedDict):
    """A law of the seat's own nation whose bill is on its way, with each bloc that votes
    on it."""

    key: str
    title: str
    blocs: list[OfferBloc]
    """In the world's order."""


class OfferPromise(TypedDict):
    """One offer the seat itself made, and where it stands (PRR rule 2)."""

    offer_id: str
    group: str
    name: str
    measure: str
    title: str
    price: str
    sentence: str
    standing: Literal["filed", "taken", "refused", "lapsed", "due", "kept", "broken"]
    filed: str
    due: str | None
    """The world day the promise is read; None until the measure has passed."""


class OfficeCount(TypedDict):
    """A body's count on an office question as it would fall today."""

    yeas: int
    nays: int


OfficeWay = Literal["vote", "council", "person", "term", "election"]
"""Who decides an office question: a post that may never be removed has none."""


class OfficeQuestionLine(TypedDict):
    """An office question open on a post of the seat's own nation: sent to every seat of
    that nation and to no other."""

    question_id: str
    office: str
    holder: str
    cause: str
    sits: str
    """The world day it sits."""
    way: OfficeWay
    """Who decides it: a body's vote, a council, one person, the end of a term, or, for a
    question an election opened, the base of the post on the day."""
    chamber: str | None
    """The body that votes, for a question decided by ``vote``."""
    deciders: list[str]
    """The names of those who choose, for a council or one person; else empty."""
    mine: bool
    """Whether the seat's person is one of them."""
    choice: bool | None
    """The seat's own sealed choice, True to remove; None if none, or if it is not its to make."""
    count: OfficeCount | None
    """For a body's vote, the count as it would fall today; else None."""


class BaseUnder(TypedDict):
    """A post of the seat's person whose base stands under its line, before any question
    opens on it."""

    office: str
    groups: list[str]
    support: float
    """The mean support of the groups it rests on."""
    line: int
    under: float
    """How far under the line it stands."""
    days: int
    """World days running, today included."""
    opens: str
    """The day the question would open, if it stays under."""


class FootingLine(TypedDict):
    """A post of the seat's person that may be put to an office question: the base it
    rests on as it stands today, at, above or under its line."""

    office: str
    groups: list[str]
    support: float
    """The mean support of the groups it rests on."""
    line: int
    days: int
    """World days running, today included, its base has stood under the line; 0 when at
    or above it."""
    question: str | None
    """The office question open on it, if any."""


class OfficeResult(TypedDict):
    """An office question of the seat's own nation decided at its sitting: public news,
    kept in the home block for ``home_api.RESULT_DAYS`` world days."""

    question_id: str
    office: str
    holder: str
    on: str
    removed: bool
    rests_until: str | None
    """For a holder kept, the day before which no question on the post opens."""


class ElectionBloc(TypedDict):
    group: str
    name: str
    seats: int
    would: int
    """Its seats were the chamber redrawn today."""


class ElectionChamber(TypedDict):
    key: str
    blocs: list[ElectionBloc]


class ElectionAhead(TypedDict):
    """An election of the seat's own nation that has not yet been held."""

    day: str
    office: str | None
    """The post whose term ends that day, if any."""
    chambers: list[ElectionChamber]


class HomeBlock(TypedDict):
    """Groups at home and the floor as the seat sees them, with ``groups`` on (GPD). Only
    the seat's own nation's groups, chambers and themes are sent; another nation shows
    only its band. With ``offers`` on, also each measure on its way with the prices its
    blocs would take, and the promises the seat has made (PRR)."""

    day: str
    nation: MapNation
    groups: list[HomeGroup]
    """In the world file's order."""
    chambers: list[FloorChamber]
    """Each chamber the nation's blocs sit in, in the world's order."""
    themes: list[HomeTheme]
    standing: float | None
    """The seat's own nation's standing at home, 0 to 100; None when no group feeds it."""
    standings: list[NationStanding]
    """Every nation's band, by name."""
    moved: list[HomeMoved]
    """Each group that moved since the seat's last wake, heaviest net change first (HFR)."""
    places: list[HomePlace]
    """Each place of political weight of the nation, in the world file's order (HFR)."""
    offers: NotRequired[list[OfferMeasure]]
    """With ``offers`` on: each law of the nation whose bill is on its way, by law key."""
    promises: NotRequired[list[OfferPromise]]
    """With ``offers`` on: the offers the seat itself made, by filing day and id."""
    office: NotRequired[list[OfficeQuestionLine]]
    """With ``office`` on: each question open on a post of the seat's nation, by sitting day."""
    turning: NotRequired[list[BaseUnder]]
    """With ``office`` on: each post of the seat's person whose base stands under its line."""
    footing: NotRequired[list[FootingLine]]
    """With ``office`` on: each post of the seat's person that may be put to a question."""
    results: NotRequired[list[OfficeResult]]
    """With ``office`` on: each question of the seat's nation decided lately, by day."""
    elections: NotRequired[list[ElectionAhead]]
    """With ``elections`` on: each election of the seat's nation ahead, by day."""


CapitalShape = Literal["body", "council", "person"]
"""The shape of who decides a capital's question, so the client draws a track of blocs, a
table of members or one person."""


class CapitalDecider(TypedDict):
    """Who decides a question in a capital: a body (its blocs or chambers), a council (its
    members) or one person (``members`` that person alone)."""

    shape: CapitalShape
    who: str
    members: list[str]


CapitalKind = Literal[
    "measure", "offer", "office", "election", "held", "ask", "peace", "agreement", "vote", "result"
]
"""What a capital's question is: in the seat's own nation, a measure on its way, offers to
its blocs on one, a sitting on an office, an election ahead, an order held for a decider,
an ask or matter before the seat, a peace before it to answer; in another, a published
agreement, a reported vote, a public sitting's result."""

CapitalAt = Literal[
    "home.chambers",
    "home.offers",
    "home.office",
    "home.elections",
    "locks.held",
    "locks.asks",
    "agreements.offers",
    "agreements.agreements",
    "conferences.conferences",
    "news",
]
"""Where the question's own data already sits in the seat's payload; ``news`` is the
public news of a sitting's result."""


class CapitalQuestion(TypedDict):
    """One live question of a capital: nothing in it the seat is not already sent."""

    kind: CapitalKind
    title: str
    day: str | None
    """The world day it falls on, sits, lapses or was decided; None for none."""
    decider: CapitalDecider
    at: CapitalAt
    ref: str
    """The key of the line at ``at``: an order id, a measure key, a question id, an
    election's day, an ask's token, an offer's item, an agreement's id, a conference's key."""


class CapitalLine(TypedDict):
    """A nation's capital as the seat may know it: its own nation's live questions, or
    only what another nation's public record gives."""

    nation: MapNation
    place: MapPlace | None
    """The nation's capital as the map draws it; None for a nation with none, or one
    with no position (an area)."""
    questions: list[CapitalQuestion]


class BattleRoundLine(TypedDict):
    """One round of a battle as the seat's own report of it gives it (BTD)."""

    on: str
    own_lost: int
    """The steps the seat's side lost that day."""
    enemy_lost: int
    """The steps the report saw the enemy lose: what contact reported, not the truth."""


class StrengthRange(TypedDict):
    low: int
    high: int


class BattlePiece(TypedDict):
    """One of the seat's own pieces in a battle, as its movement forms name it."""

    force: str
    """The force key the movement forms and the ``contingency`` action take."""
    name: str
    strength: int
    contingency: Literal["hold", "hold_fast", "fall_back", "withdraw_below"] | None
    """Its standing order for a battle; None: hold (the default)."""


class BattleView(TypedDict):
    """One battle the seat's nation is a side of (BTD). Built from the seat's own side and
    its own papers: never the enemy's true strength, a round's draws or the enemy's
    decision. A battle the seat's nation is not in is not listed."""

    area: str
    """The area's map key; the ``battle`` action names the battle by it."""
    name: str
    opened: str
    side: Literal["attacker", "defender"]
    enemy: str
    """The enemy nation's name, as the battle's news gives it."""
    rounds: list[BattleRoundLine]
    """Each round the seat has a report of, oldest first."""
    strength: int
    """The seat's side's strength now: what it brought less the steps it lost."""
    enemy_strength: StrengthRange | None
    """The range the seat's latest papers put the enemy there at; None before any paper
    places an enemy piece there."""
    decision: Literal["press", "hold", "withdraw"] | None
    """The side's decision in force; None: none given (the attacker presses, the
    defender holds)."""
    decided: bool
    """The side has its decision for the open wake, landed or on its way, or the seat has
    one held for the next wake."""
    held: bool
    """The seat has a decision for it held for the next wake (given after its commit)."""
    decisions: list[str]
    """The decisions the seat may give now: empty once decided this wake, between wakes
    and for a seat that commands none of the side's pieces."""
    contingencies: list[str]
    """The contingency kinds the seat may give its pieces there."""
    pieces: list[BattlePiece]
    ended: str | None
    """The day the battle ended; None while it is open. An ended battle gives no
    decisions, contingencies or pieces."""
    closing: "ClosingOdds | None"
    """An ended battle's closing odds (ODS); None while it is open, and while the odds
    desk is busy."""


class OddsShares(TypedDict):
    """The share of runs, in percent, that end in each way for the seat's side (ODS)."""

    win: float
    stalemate: float
    """Still fought, or the attacker went back after a lull, when the days run out."""
    loss: float


class OddsTerrain(TypedDict):
    """The public facts of the area the odds are for."""

    area: str
    name: str
    terrain: str
    """The terrain's key in the world file."""
    defence: int
    """What the terrain adds to a defender's score."""
    holder: str | None
    """The name of the nation holding it; None for a sea zone or nobody's ground."""


class OddsAtStrength(TypedDict):
    strength: int
    """One total enemy strength the reports allow."""
    win: float | None
    """The win share, in percent, of the runs that drew that strength; None: none did."""


class OddsOutcome(TypedDict):
    """How a battle comes out over the runs: the shares, the loss ranges, the taking and
    the falling back, with no enemy strength in it. The truth half of an ended battle's
    closing odds is this alone."""

    known: bool
    area: str
    terrain: OddsTerrain
    runs: int
    days: int
    shares: OddsShares | None
    own_lost: StrengthRange | None
    """The likely range of steps the seat's side loses: the 10th to the 90th percentile."""
    enemy_lost: StrengthRange | None
    taken: float | None
    """The chance, in percent, of taking the territory; None where no win takes it."""
    taken_days: int | None
    """The median days until it is taken, over the runs that take it."""
    forced_back: float | None
    """The chance, in percent, that the seat's side breaks and is forced back."""
    back_to: str | None
    """The area key the seat's piece would be forced back to; None: nowhere."""
    reports: list[str]
    """The keys of the reports the enemy was read from."""


class OddsReply(OddsOutcome):
    """The ``odds`` action's spread (ODS), simulated from the seat's own picture: its own
    pieces exactly, the enemy only as its reports put it. Never one figure. With no report
    of the enemy there, ``known`` is false and only the terrain facts are given."""

    by_strength: list[OddsAtStrength]
    moved_by: NotRequired[OddsCause | None]
    """With ``kinds_in_battle`` on and the enemy known: the cause that moved the odds most;
    None when no cause there moves them."""


class ClosingOdds(TypedDict):
    """An ended battle's odds on its first day (ODS rule 7): as they truly stood, with
    both sides exactly, beside what the seat's own picture said that day. The truth
    half gives no win share by enemy strength: each row would name the enemy's exact
    total, and the round reports give its losses exactly."""

    truly: OddsOutcome
    seen: OddsReply


class MapReply(TypedDict):
    """The ``map`` action: the map object the game's stored hash names, the same for every
    seat. Refused, with one line, when no object has that hash or the game has no
    territory map."""

    reply: str
    refused: bool
    file: MapFile | None
    map: dict[str, object] | None
    """The map file's JSON as stored (``format``, ``coords``, ``box``, ``vertices``,
    ``areas``, ``backdrop``)."""


class Reply(TypedDict):
    """What a seat action answers. A refusal is a reply, not an error."""

    reply: str
    refused: bool


class WakeHeader(TypedDict):
    """The shared wake, as the room's header shows it. Counts only: never who has
    committed, never a style, and nothing that tells an aide from a person."""

    wake: int
    """The wake's number; 0 too while none has opened (``deadline`` is then None)."""
    deadline: str | None
    """Wall-clock ISO time it closes by; None when no wake is open."""
    committed: int
    humans: int
    you_committed: bool
    is_host: bool
    can_close: bool
    """True when this account may press "Close the wake now"."""


class AgendaExpect(TypedDict):
    """One move the seat's staff expect an offered order to make. Staff opinion: no rule
    reads it."""

    on: str
    """What it points at: "regard", "stance", "stake" or "figure"."""
    name: str
    """The person, leader, stake or figure, by name."""
    direction: str
    """"gain" for the seat, "cost" against it."""
    size: int
    """One step or two."""
    sure: str
    """How sure the staff are: "firm", "likely" or "guess"."""


class AgendaRisks(TypedDict):
    """How much the staff think an offered order risks, each 0 (none) to 3."""

    escalation: int
    refusal: int
    exposure: int


class AgendaOption(TypedDict):
    """One offered order, as the seat understands it."""

    label: str
    to: str | None
    """Who it goes to, by name; None: the seat acts itself."""
    risk: str
    historical: bool
    """What history did; the client labels it so."""
    pick: str
    """An opaque token, posted back to ``option``."""
    taken: bool
    """True once the seat has filed exactly this option's asks in the open wake. The
    steps of a guided plan share one value."""
    expects: list[AgendaExpect]
    """What the staff expect it to move, only what is still in the seat's view; empty
    for the desk's own list. The steps of a guided plan share the plan's."""
    risks: AgendaRisks | None
    """None where the staff gave no levels. The steps of a guided plan share the plan's."""


class TermClause(TypedDict):
    """One clause of an offer or agreement, in the fixed words ``agreement.render_clause``
    gives it (AGA)."""

    text: str
    checked: bool
    """False for wording the rules cannot check: it is never judged."""
    interpretation: bool
    """True when the aide read the clause from the seat's own wording (TRT): the seat
    signs the rendered words, and its wording stands beside them unchecked."""


class OfferTerms(TypedDict):
    """The terms of an offer of agreement as signing and its agenda item show them (AGA)."""

    parties: list[str]
    """The named nations, by name, in the offer's order."""
    clauses: list[TermClause]
    wording: str
    """The offer's own wording, which the rules do not check; empty when it has none."""
    text: str
    """Every term in one line: ``agreement.render_terms``."""


class AgendaItem(TypedDict):
    """One live mandate with what the seat is offered for it."""

    id: str
    """An opaque token."""
    kind: str
    """In words ("Order", "Crisis")."""
    issuer: str | None
    """The issuer's name; None: the world itself."""
    text: str
    issued: str
    deadline: str
    cause: str | None
    """The headline of the news behind the history event that issued it, once a page of
    that news has reached the seat; None otherwise."""
    options: list[AgendaOption]
    """Beginner: what to choose from. Empty otherwise."""
    plan: list[AgendaOption]
    """Guided: the plan's steps, in order. Empty otherwise."""
    actions: list[str]
    """A held decision: the step actions its step allows, less ``amend``, in the order of
    ``StepAction``; the ``step`` action takes one. Empty for every other kind."""


class AgreementClauseLine(TypedDict):
    """One clause of an agreement in force, with its state (AGA rule 4)."""

    text: str
    checked: bool
    state: Literal["pending", "kept", "broken", "called", "void", "unchecked"]
    """``pending``: in force and not yet judged; ``unchecked``: wording never judged."""
    on: str | None
    """The day it was last judged; for a pending dated clause, the day it is judged on;
    None for a standing or unchecked clause not yet judged."""


class AgreementLine(TypedDict):
    """An agreement the seat's nation is party to, or a public one (AGA rule 4)."""

    id: str
    """The ``agreement-publish`` action takes it."""
    parties: list[str]
    wording: str
    made: str
    published: str | None
    """The day a party published it; None while only its parties know of it."""
    party: bool
    """Whether the seat's own nation is a party: only a party may publish it."""
    clauses: list[AgreementClauseLine]


class OfferAnswer(TypedDict):
    """One named nation's answer to the seat's own offer, as the seat knows it: None
    until the offer's due day decides it (AGA rule 3)."""

    nation: str
    answer: Literal["accepted", "declined"] | None


class OfferLine(TypedDict):
    """An open offer of agreement the seat's nation is named in (AGA)."""

    by: str
    """The offering nation, by name."""
    terms: OfferTerms
    filed: str
    expires: str
    answers: list[OfferAnswer]
    """The seat's own offer: each other nation's answer. Empty for an offer to the seat."""
    item: str | None
    """An offer before the seat to answer: the id of its "Offer" item on the agenda, which
    the ``answer`` action takes. None once answered on its due day, and for its own offer."""
    accept: NotRequired["LockCheck"]
    """With ``peace`` on, for an offer of peace before the seat to answer: what accepting
    it would do (PER rule 3): ``allowed``, the acceptance stands; ``locked``, it is held
    for who decides, with the reason the seat would be told; ``beyond``, his nation has no
    one who may accept a peace, so accepting lapses the offer. Absent otherwise."""


class PeaceClause(TypedDict):
    """One clause of peace the offer builder may add (PER rule 1), with the nations the
    seat may name in it: those at war with its nation, as its view holds them."""

    type: Literal["armistice", "end_war", "no_separate_peace"]
    label: str
    nations: list[WarNation]


class ArmisticeLine(TypedDict):
    """An armistice in force (PER rule 4): the agreement, the two nations, and the world
    day its days run out."""

    agreement: str
    nations: list[str]
    last_day: str


class AgreementsBlock(TypedDict):
    """Agreements as the seat sees them, with ``agreements`` on (AGA rule 4): every
    agreement its nation is party to and every public one, and its open offers. Read
    from the seat's view, which holds no private agreement of other nations."""

    agreements: list[AgreementLine]
    offers: list[OfferLine]
    peace: NotRequired[list[PeaceClause]]
    """With ``peace`` on, the clauses of peace the offer builder adds (PER). Absent off."""
    armistices: NotRequired[list[ArmisticeLine]]
    """With ``peace`` on, each armistice in force among the agreements the seat sees: its
    nation's, and once published, every one (PER). Absent off."""


class ConferenceVoteLine(TypedDict):
    """One invited nation's counted vote, as the tally gives it (CNA rule 3): never which
    seat cast it, or whether it was a person's or the aide's."""

    nation: str
    vote: Literal["for", "against", "abstain"]


class ConferenceLine(TypedDict):
    """A conference the seat's nation is invited to, or a public one (CNA rule 3)."""

    key: str
    """The ``conference-vote`` action takes it; also the id of its "Vote" agenda item."""
    called_by: str
    invited: list[str]
    """The invited nations, by name, the caller's first."""
    text: str
    clauses: list[TermClause]
    """The text's clauses in the rules' fixed words; empty for a text of wording only."""
    unanimous: bool
    called: str
    """The day it was called, or a world's conference opened."""
    voting_day: str
    public: bool
    vote: Literal["for", "against", "abstain"] | None
    """The seat's own sealed vote; None while it has sealed none."""
    can_vote: bool
    """Whether ``conference-vote`` would take a vote now: invited, not yet tallied, and no
    vote sealed in an earlier wake."""
    tallied: str | None
    result: Literal["agreement", "resolution", "failed", "cancelled"] | None
    """None until the tally."""
    votes: list[ConferenceVoteLine]
    """Each invited nation's counted vote, after the tally only; empty before it."""
    agreement: str | None
    """The agreement a passed text made, when it made one."""


class ConferencesBlock(TypedDict):
    """Conferences as the seat sees them, with ``conference`` on (CNA rule 3). Read from
    the seat's view, which holds no other seat's vote."""

    conferences: list[ConferenceLine]


class HeldLine(TypedDict):
    """One of the seat's own held orders (LKD rule 1), read from its own view."""

    id: str
    """The held order's id, which the ``ask`` action takes."""
    words: str
    """The order in plain words."""
    who: str
    """Who can allow it: a person's name, or a nation's chambers."""
    reason: str
    """What the seat was told when it was held."""
    held: str
    """The world day it was held."""
    asked: bool
    """Whether the seat has asked for it."""
    piece: str | None
    """The map key of the seat's own piece the held form order moves, as the seat's map
    keys that piece; None for a written order or a form that moves no piece."""
    price: NotRequired[str]
    """With ``defiance`` on, for an order its seat may send anyway (the ``send-anyway``
    action), the price in plain words: the incident, who will be asked to back or disown
    it, and that he may be relieved. Absent otherwise (DFR)."""


class AskForm(TypedDict):
    """One of the decider's own forms whose filing would allow the asked order: the
    row's posture, with the terms that set it."""

    lever: str
    label: str
    params: dict[str, str]


class AskLine(TypedDict):
    """An ask put before the seat (LKD rule 4): who asked and the order's plain words."""

    id: str
    """An opaque token for the ask."""
    by: str
    """The asker's name."""
    words: str
    asked: str
    """The world day it was asked."""
    forms: list[AskForm]
    """The seat's own forms that would allow it; empty where it has none."""
    terms: NotRequired["OfferTerms"]
    """For a nation's held acceptance of an offer of peace, the offer's terms in full, as
    its parties read them before accepting (PER rule 2). Absent otherwise."""


class WaitLine(TypedDict):
    """One line of the aide's note of what waits (ABN): something the seat left alone
    while away, read from its own view at the moment it reads the note."""

    kind: str
    """``held`` (its own held order not asked for), ``bloc`` (a bloc that would take an
    offer on a measure on its way), ``aim`` (its own aim still open), or a due kind's
    name (``agenda_api.DUE_KINDS``)."""
    what: str
    """The line in plain words."""
    who: str | None
    """Who it is from or who can allow it, by name; None where no one is named."""
    day: str
    """Its day: the world day it was held, the day it falls due, or a phrase such as
    "at this wake's close"."""


class LocksBlock(TypedDict):
    """The seat's locks, with ``locks`` on: its own held orders and the asks put
    before it. Absent with the rule off."""

    held: list[HeldLine]
    asks: list[AskLine]
    incidents: NotRequired[list["IncidentLine"]]
    """With ``defiance`` on, each incident the seat is party to, as commander or as the
    superior who answers it (DFR). Absent with the rule off."""


class IncidentLine(TypedDict):
    """An incident in the seat's list (DFR), read from its own view: before the superior,
    a matter with three answers until it is answered; to the commander, what he is told
    of it and then its answer."""

    id: str
    """The incident's id, which the ``answer`` action takes as ``item``."""
    words: str
    """The incident in plain words, from the seat's own view."""
    due: str
    """The world day it is to be answered by; the superior's card answers after it."""
    verdict: str | None
    """``backed``, ``disowned`` or ``dismissed`` once answered; None while open."""
    answers: list[str]
    """The answers the seat may file now: the three for the superior while it is open;
    empty otherwise."""


class LockCheck(TypedDict):
    """The check before sending (LKD rule 2): what filing the draft would do now."""

    check: Literal["allowed", "locked", "beyond", "question"]
    """``allowed``: it goes out; ``locked``: a lock holds it; ``beyond``: it is refused;
    ``question``: with ``posts`` on, a move of post that would take a seat's last
    authority, so it goes out and waits for the office question's sitting (PPR)."""
    who: str | None
    """For ``locked``, who can allow it; None otherwise."""
    reason: str
    """For ``locked`` and ``question``, what the seat would be told; for ``beyond``,
    today's refusal."""
    price: NotRequired[str]
    """With ``defiance`` on, for a ``locked`` order its seat could then send anyway, the
    price in plain words, as the held line will give it (DFR). Absent otherwise."""


class PostName(TypedDict):
    """A post: the office asset's id and name."""

    id: str
    name: str


class LadderRung(TypedDict):
    """One rung of the seat's own ladder, in order; ``free`` when nobody holds it."""

    id: str
    name: str
    free: bool


class PendingPost(TypedDict):
    """A change of post pending on the seat (LDR), sealed to it until it lands."""

    id: str
    """The notice the seat was sent, a document it holds."""
    post: str
    move: Literal["appoint", "relieve"]
    lands: str
    """When it lands, in words."""
    wake: int | None
    """The wake at whose close it lands; None when it waits for the office question."""
    rung: str | None
    """The post the seat lands on; None for none or while it waits for the question."""


class PostMoveLine(TypedDict):
    """A move the seat may make on another person: appoint, relieve or restore, with the
    rung the person it puts down lands on."""

    person: str
    name: str
    post: str
    office: str
    move: Literal["appoint", "relieve", "restore"]
    down: str | None
    """Who the move puts down, by name; None for no one."""
    rung: str | None
    """The post that person lands on; None for none."""
    question: bool
    """It would take a seat's last authority: it waits for the office question."""


class Through(TypedDict):
    """Someone in the seat's inner circle whose card holds an authority."""

    person: str
    name: str
    authority: list[str]


class Letter(TypedDict):
    id: str
    title: str


class PostRoom(TypedDict):
    """What a seat with no post may still do."""

    inner_circle: list[str]
    letters: list[Letter]
    aims: list[str]
    through: list[Through]


class PostsBlock(TypedDict):
    """The seat's post as it sees it, with ``posts`` on (PPR): its post and ladder, who
    may move it, each change pending on it, the moves it may make on others, and with no
    post, the room it still has. Absent with the rule off."""

    post: PostName | None
    ladder: list[LadderRung]
    moved_by: list[str]
    pending: list[PendingPost]
    moves: list[PostMoveLine]
    room: NotRequired[PostRoom]


class StandingVote(FloorVote):
    """One vote of a measure on its way, counted as it would stand, in its chamber."""

    chamber: str


class OfferCheck(LockCheck):
    """The check of a draft offer to a bloc that filing would allow (PRB rule 2)."""

    stands: list[StandingVote]
    """Each vote of the measure's bill counted as the votes rule would tally it with the
    offer landed, in the world's order: the count as it would stand."""


class ForecastMove(TypedDict):
    """One move the staff expected a picked suggestion to make, and how it came out (FCK)."""

    on: str
    """What it points at: "regard", "stance", "stake" or "figure"."""
    name: str
    """The person, leader, stake or figure, by name."""
    direction: str
    """"gain" for the seat, "cost" against it."""
    size: int
    sure: str
    outcome: Literal["held", "missed", "open"]
    """It moved the expected way by the settling day; it did not; not settled yet."""


class ForecastOrder(TypedDict):
    """One of the seat's own orders that came from a suggested action, with its forecast."""

    id: str
    """The order's opaque token, the same as its ``results`` entry's."""
    filed: str
    asked: str
    """The order's own words."""
    aide: bool
    """True when the seat's aide chose it. The seat's own, sent to it alone."""
    settles: str | None
    """The day its forecast settles; None until the order is enacted."""
    moves: list[ForecastMove]
    """Only moves the seat could see at filing and, once settled, on the settling day."""
    risks: AgendaRisks | None


class ForecastBlock(TypedDict):
    """The seat's own forecasts and its record: how many moves were checked (held or
    missed) and how many held (FCK)."""

    checked: int
    held: int
    orders: list[ForecastOrder]
    """Newest first."""


class AgendaBlock(TypedDict):
    style: str
    """``PlayStyle`` value; the client words it. The seat's own, sent to it alone."""
    items: list[AgendaItem]
    initiative: list[AgendaOption]
    """Options offered outside the agenda."""
    forecast: ForecastBlock
    """The seat's own forecasts, checked (FCK)."""


class ResultPart(TypedDict):
    """One part of a routed order, as its issuer knows it. Never the estimator's
    rationale, never its engine-only effects."""

    ask: str
    """What the part asked for, in words."""
    to: str | None
    """Who carries it out or decides, by name; None: the seat acts itself."""
    route: str
    """In words ("Your command", "Through Congress", "Your persuasion")."""
    fidelity: str | None
    """In words, once carried out."""
    refused_under: str | None
    """In words: the stated rule an executor refused under."""
    reason: str
    """The issuer-facing reason; leak-scanned."""
    accepted: bool | None
    """Influence: whether the target went along; None until decided."""
    applied: str | None
    """The in-world date it landed; None until then."""


class OrderResult(TypedDict):
    """One of the seat's own routed orders, with how each part landed."""

    id: str
    """An opaque token."""
    filed: str
    parts: list[ResultPart]


class CounselLine(TypedDict):
    """One consultation, as the seat saw it: who, how, the words, the in-world day it was
    held (in words and ISO, empty before the calendar has a date) and whether the person
    is in the seat's inner circle."""

    person: str
    channel: str
    question: str
    answer: str
    day: str
    day_iso: str
    tie: Literal["inner", "outer"]


class ReachContact(TypedDict):
    name: str
    title: str | None
    """The office on the person's public card face, if they have a card."""
    channels: list[str]
    """How the seat can reach them, in words, nearest first."""
    powers: list[str]
    """The powers on the person's public card face, in words; empty with no card face."""
    channel_keys: list[str]
    """The ``ChannelKind`` value behind each of ``channels``, in the same order."""


class ReachGroups(TypedDict):
    """Who the seat can reach and how."""

    inner_circle: list[ReachContact]
    government: list[ReachContact]
    foreign: list[ReachContact]
    other: list[ReachContact]


class OrderProposal(TypedDict):
    """The engine-v2 order the aide read free text as, for the player to sign or
    revise. The server holds what is filed; signing posts nothing of it back."""

    person: str | None
    """Who it is addressed to, by name; None: the seat acts itself."""
    channel: str | None
    """How it travels, in words."""
    text: str
    parts: list[str]
    """Each part in words; empty when it cannot be filed."""
    reason: str | None
    """Why it cannot be filed, in words."""


class OfferReading(TypedDict):
    """The reply to ``agreement-offer`` (and to ``order`` when the aide read a treaty):
    the proposal to sign and its terms (AGA)."""

    reply: str
    refused: bool
    proposal: OrderProposal
    terms: OfferTerms | None
    """None when nothing can be signed; ``proposal.reason`` says why."""


class TimelinePoint(TypedDict):
    """A date a new game can start on."""

    date: str
    label: str
    curated: bool
    """True for a curated start point; the timeline marks these."""
    world: str | None
    """The ready-made world to start, for a curated point that has one."""


class Figure(TypedDict):
    """Someone who held real power on the chosen date."""

    name: str
    """Posted back to ``pick``."""
    title: str


class FigureGroup(TypedDict):
    side: str
    power: str
    """The kind of power, in words ("Head of government", "Military command")."""
    figures: list[Figure]


class OpeningPerson(TypedDict):
    """Someone a player may take, or one already taken; nothing says who plays him."""

    name: str
    """Posted back to ``pick``."""
    office: str
    pitch: str
    taken: bool


class OpeningPath(TypedDict):
    path: str | None
    """The ladder the office stands on (``political``, ``military``); None for no card."""
    persons: list[OpeningPerson]


class OpeningNation(TypedDict):
    key: str | None
    """None for the people the world places under no nation."""
    name: str
    paths: list[OpeningPath]


class Opening(TypedDict):
    """``/api/new/opening``: the nations with someone left to take, their open paths and
    the persons on each, from ``roster.claimable``; and the game's human seats."""

    nations: list[OpeningNation]
    seats_left: int
    seats_max: int


class RevealRuling(TypedDict):
    """The estimator's ruling on one part, shown only once the game has ended."""

    on: str
    ask: str
    rationale: str


class RevealSeat(TypedDict):
    person: str
    goals: list[str]
    covert: list[str]
    """Each covert act, in words."""
    styles: list[str]
    """The seat's play style over the game, in words, oldest first."""
    rulings: list[RevealRuling]


class Reveal(TypedDict):
    """The end-of-game reveal. The one read that shows what was hidden: it is served
    for an ended game only, so it does not pass ``snapshot.checked``."""

    name: str
    seats: list[RevealSeat]


class Receipt(TypedDict):
    """The paper that only said an order went through as given, folded into its ledger line
    (``tray.receipt_word``). A paper that is news is never a receipt."""

    word: str
    """What it said, in words: "Carried out in full", "Passed on", "Pressed forward"."""
    day: str
    """The in-world day the paper arrived, in words."""
    doc: str
    """The paper's own id, so the line can open it."""


class RecordOrder(TypedDict):
    """One ledger line of the seat's record (``core.record``): a part of a routed order
    or a standard form, in the seat's own words. No entity id, and no order id outside
    ``track``, which repeats the seat's own tracker id."""

    id: str
    """An opaque token: the first 12 hex of the sha256 of the ledger key."""
    wake: int
    filed: str
    """The in-world day it was filed, in words (1 September 1941)."""
    settled: str | None
    """The in-world day it settled, in words; None while it is moving."""
    asked: str
    to: str | None
    """Who it was sent to, by name; None: the seat acts itself or it runs a pipeline."""
    holder: str | None
    """Who has it now, by name, while it is moving."""
    status: str
    """In words, as the ledger has it."""
    moving: bool
    track: str | None
    """The ``OrderTrack.id`` of the matching tracker entry for a standard form; else None."""
    due: str | None
    """For a routed part still moving: the day its answer reaches the seat, in words."""
    said: str | None
    """The answer the issued paper gives, else the part's issuer-facing reason, else None."""
    receipt: Receipt | None
    """Set when every paper that answers the order only acknowledges it (the latest one);
    None while any of them is news or none has arrived."""


class RecordWake(TypedDict):
    """The latest wake's page of the record."""

    number: int
    opened: str
    """The in-world day it opened, in words."""
    days_passed: int
    papers: int
    """How many papers reached the desk since the wake before."""
    filed: list[str]
    """``RecordOrder.id`` of each entry filed in this wake."""
    settled: list[str]
    """``RecordOrder.id`` of each entry settled since the wake before."""


class PlaybackOrder(TypedDict):
    """A step on one of the seat's own orders (PBF)."""

    kind: Literal["order"]
    on: str
    order: str
    """``RecordOrder.id`` of the record line it moves."""
    what: str
    """``filed``; a ``StepAction`` value for a step taken; an ``OrderStatus`` value once
    it settles; ``carried_out`` or ``refused`` for a routed part."""


class PlaybackMove(TypedDict):
    """One of the seat's own nation's pieces entered an area. The same shape however the
    piece was sent: a seat's order, the aide's, the record or a battle."""

    kind: Literal["move"]
    on: str
    piece: str
    """The piece's key, as ``MapMark.key`` names it."""
    left: str
    """The area's key in the map file."""
    entered: str
    days: int | None
    """The days the step took, by the step rule on the day it began
    (``map_api.step_began``); None when that day is not found."""


class PlaybackHalt(TypedDict):
    """A step of the seat's own nation's piece was refused, and it holds where it stands."""

    kind: Literal["halt"]
    on: str
    piece: str
    area: str
    to: str
    reason: str


class PlaybackRaised(TypedDict):
    """A piece of the seat's own nation was raised."""

    kind: Literal["raised"]
    on: str
    """The day it entered."""
    piece: str
    """The piece's key, as ``MapMark.key`` names it."""
    name: str
    place: str
    """The name of the place it entered at."""
    area: str
    """The key in the map file of the territory that place stands in."""


class PlaybackPaper(TypedDict):
    """A paper reached the seat: a report, the press, a battle report."""

    kind: Literal["paper"]
    on: str
    """The day it arrived."""
    paper: str
    """``DocumentListItem.id``."""
    title: str


class PlaybackHolder(TypedDict):
    """A territory changed hands. Public."""

    kind: Literal["holder"]
    on: str
    area: str
    holder: MapNation
    was: MapNation | None


class PlaybackStake(TypedDict):
    """A contest, mandate or goal of the seat's view moved or settled."""

    kind: Literal["stake"]
    on: str
    name: str
    """The contest's name, the mandate's text or the goal's text."""
    what: str
    """``moved`` or ``decided`` for a contest; ``issued`` or a ``MandateStatus`` value
    for a mandate;
    ``progressed``, ``met`` or ``undone`` for a goal."""


class PlaybackHeld(TypedDict):
    """One of the seat's own held orders was held or ended (LCK, ASK). Only its issuer's
    seat is given it."""

    kind: Literal["held"]
    on: str
    what: str
    """``held``, or a ``HeldEnd`` value: ``landed``, ``failed``, ``replaced``,
    ``withdrawn``."""
    line: str
    """The plain line the seat reads: who can allow it, the reason it failed, the later
    order's words."""


class PlaybackGroup(TypedDict):
    """One of the seat's own nation's groups moved (HFR): as ``HomeMove`` words it, with
    the support it moved to. Only its own nation's seats are given it."""

    kind: Literal["group"]
    on: str
    group: str
    name: str
    change: int
    support: int
    why: str
    reach: Literal["felt", "reported"]


class PlaybackCount(TypedDict):
    """The count of a vote on one of the seat's measures on its way changed with a group's
    move (HFR): the votes rule's count after the move beside the one before it."""

    kind: Literal["count"]
    on: str
    order_id: str
    """``OpenMeasure.order_id``."""
    key: str
    title: str
    vote: str
    yeas: int
    nays: int
    was: list[int]
    """Its yeas and nays before the move."""


PlaybackStep = (
    PlaybackOrder
    | PlaybackMove
    | PlaybackHalt
    | PlaybackPaper
    | PlaybackHolder
    | PlaybackStake
    | PlaybackHeld
    | PlaybackGroup
    | PlaybackCount
    | PlaybackRaised
)
"""One step of a missed wake's playback, in the order it happened (``on`` is ISO)."""


class RecordBlock(TypedDict):
    orders: list[RecordOrder]
    """Newest filed first."""
    wake: RecordWake | None
    """None before any wake opens."""


class Dossier(TypedDict):
    """A person's dossier text from the world's sidecar file. Read-only, public text:
    nothing in it comes from a card's private side. Empty fields hide their section."""

    bio: str | None
    arena: str | None
    """The seat's own stage in two or three sentences: what it commands and who it must carry."""
    history: list[str]
    """As history had it: what the person did in the record, one line each. Not binding."""
    quote: str | None
    source: str | None
    """Where the quote is from; a quote is never served without one."""
    fact: str | None
    portrait: str | None
    """A file name under ``/assets/portraits/``; None: the client draws a monogram."""
    credit: str | None
    """The portrait's author and licence, shown under it."""


class SettingDate(TypedDict):
    on: str
    """The in-world day, in words."""
    what: str


class Setting(TypedDict):
    """The world's setting dossier from the sidecar file. Empty fields hide their section."""

    situation: str | None
    sides: list[str]
    """Each side of the world's main contest, as a short line."""
    crawl: list[str]
    """The opening crawl, one paragraph each."""
    facts: list[str]
    """Short period lines for the overlay while a wake runs."""
    dates: list[SettingDate]
    """The dates history has on its clock, oldest first."""


__all__ = [
    "AgendaBlock",
    "AgendaItem",
    "AgendaOption",
    "AgreementClauseLine",
    "AgreementLine",
    "AgreementsBlock",
    "AimBlankLine",
    "AimCheck",
    "AimPatternLine",
    "AimValue",
    "ArmisticeLine",
    "AskForm",
    "AskLine",
    "BattlePiece",
    "BattleRoundLine",
    "BattleView",
    "BlocCount",
    "BodyLine",
    "Chamber",
    "ChamberSeats",
    "ChamberVote",
    "Clock",
    "ClosingOdds",
    "ConferenceLine",
    "ConferenceVoteLine",
    "ConferencesBlock",
    "ContactLine",
    "Court",
    "CourtOrder",
    "CourtPath",
    "CourtRing",
    "CourtStep",
    "Desk",
    "DirectiveProposal",
    "DocumentListItem",
    "DocumentListing",
    "DocumentPage",
    "Dossier",
    "EconomyBlock",
    "EconomyFigure",
    "EconomyIncome",
    "EconomyOwn",
    "EconomyPools",
    "EconomyTerritory",
    "Figure",
    "FigureCause",
    "FigureChange",
    "FigureGroup",
    "FigureName",
    "FloorBloc",
    "FloorChamber",
    "FloorVote",
    "ForecastBlock",
    "ForecastMove",
    "ForecastOrder",
    "GroupMove",
    "HeldLine",
    "HomeBlock",
    "HomeGroup",
    "HomeMove",
    "HomeMoved",
    "HomePlace",
    "HomeTheme",
    "LadderRung",
    "Letter",
    "LeverChoice",
    "LeverLine",
    "LeverParam",
    "LiveOffer",
    "LockCheck",
    "LocksBlock",
    "MapArea",
    "MapCapital",
    "MapFile",
    "MapLift",
    "MapMark",
    "MapMove",
    "MapNation",
    "MapOrder",
    "MapPiece",
    "MapPlace",
    "MapRegion",
    "MapReply",
    "MapReport",
    "MarkArea",
    "NationStanding",
    "OddsAtStrength",
    "OddsCause",
    "OddsOutcome",
    "OddsReply",
    "OddsShares",
    "OddsTerrain",
    "OfferAnswer",
    "OfferBloc",
    "OfferCheck",
    "OfferLine",
    "OfferMeasure",
    "OfferPrice",
    "OfferPromise",
    "OfferReading",
    "OfferTerms",
    "OpenMeasure",
    "Opening",
    "OpeningNation",
    "OpeningPath",
    "OpeningPerson",
    "OrderProposal",
    "OrderResult",
    "OrderTrack",
    "OrderTracker",
    "OwnAimBlock",
    "PeaceClause",
    "PendingPost",
    "People",
    "PeopleMeter",
    "PersonChannel",
    "PersonHold",
    "PersonLine",
    "PersonTally",
    "PieceArea",
    "PieceCourse",
    "PieceFigures",
    "PieceKindView",
    "PieceWait",
    "PlaceChoice",
    "PlaceLift",
    "PlaceReach",
    "PlaybackCount",
    "PlaybackGroup",
    "PlaybackHalt",
    "PlaybackHeld",
    "PlaybackHolder",
    "PlaybackMove",
    "PlaybackOrder",
    "PlaybackPaper",
    "PlaybackRaised",
    "PlaybackStake",
    "PlaybackStep",
    "PostMoveLine",
    "PostName",
    "PostRoom",
    "PostsBlock",
    "PublicWar",
    "RaiseCost",
    "RaiseKind",
    "RaisePlace",
    "RaisingLine",
    "ReachContact",
    "ReachGroups",
    "Receipt",
    "RecordBlock",
    "RecordOrder",
    "RecordWake",
    "RegionWeather",
    "Reply",
    "ResultPart",
    "Reveal",
    "RevealRuling",
    "RevealSeat",
    "SeatMap",
    "Setting",
    "SettingDate",
    "Situation",
    "SituationFigure",
    "SituationReading",
    "SituationSource",
    "Stake",
    "StakeLean",
    "StakeMandate",
    "Stakes",
    "StandingVote",
    "StepLine",
    "StrengthRange",
    "TermClause",
    "Threat",
    "Through",
    "TimelinePoint",
    "WaitLine",
    "WakeHeader",
    "WarNation",
    "WeatherBlock",
    "WeatherEffect",
    "WeatherKindView",
]
