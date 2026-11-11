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

from typing import Literal, TypedDict


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


class LeverParam(TypedDict):
    name: str
    label: str
    kind: Literal["int", "enum", "entity", "text"]
    lo: int | None
    hi: int | None
    choices: list[LeverChoice]


class LeverLine(TypedDict):
    name: str
    label: str
    summary: str
    pipeline: str
    params: list[LeverParam]
    """The draft form is built from these."""


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


class MapPlace(TypedDict):
    name: str
    lat: float
    lon: float


class MapMark(TypedDict):
    """One force, front or route as the seat's latest page about it places it."""

    name: str
    kind: Literal["fleet", "army", "air", "front", "route"]
    side: Literal["own", "other", "none"]
    """Own: the seat's own polity or body. None: a front, which is both sides'."""
    side_name: str
    certainty: Literal["known", "reported", "stale"]
    """Known: the seat's own side, freshly reported. Stale: the page is older than
    ``STALE_DAYS``. A feature no page has placed is not on the map at all."""
    places: list[MapPlace]
    reported: str
    """The page's issue date: where it was then, not now."""
    source: str
    """The author's name."""
    document: str
    """The page's id, to open it from the map."""


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


class SeatMap(TypedDict):
    """The map: places are public; marks come from arrived pages only, never the record."""

    places: list[MapPlace]
    marks: list[MapMark]
    orders: list[MapOrder]
    """The seat's own movement orders: what it has ordered, not where anything is."""


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
    options: list[AgendaOption]
    """Beginner: what to choose from. Empty otherwise."""
    plan: list[AgendaOption]
    """Guided: the plan's steps, in order. Empty otherwise."""


class AgendaBlock(TypedDict):
    style: str
    """``PlayStyle`` value; the client words it. The seat's own, sent to it alone."""
    items: list[AgendaItem]
    initiative: list[AgendaOption]
    """Options offered outside the agenda."""


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
    "BodyLine",
    "Clock",
    "ContactLine",
    "Desk",
    "DirectiveProposal",
    "DocumentListItem",
    "DocumentListing",
    "DocumentPage",
    "Dossier",
    "Figure",
    "FigureGroup",
    "LeverChoice",
    "LeverLine",
    "LeverParam",
    "MapMark",
    "MapOrder",
    "MapPlace",
    "OrderProposal",
    "OrderResult",
    "OrderTrack",
    "OrderTracker",
    "ReachContact",
    "ReachGroups",
    "RecordBlock",
    "RecordOrder",
    "RecordWake",
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
    "StepLine",
    "TimelinePoint",
    "WakeHeader",
]
