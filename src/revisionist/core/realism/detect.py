"""Detection: every known enemy piece is a report (DET).

With ``reports`` switched on (it needs ``territories``), a nation knows an enemy piece
only as a report: the piece's kind or "unknown", a strength range, the area, the day seen,
the source, a confidence of A, B or C, and the day the report reaches the nation's seats.
An enemy piece is a force of any polity that is not the nation's own or an ally.

Each world day, in the day walk and for every nation at once, every source rolls once for
each enemy piece in its cover, seeded by campaign, day, nation, source and piece:

- contact: an own force in the same area sees every enemy piece there exactly (A); in a
  bordering area it sees the kind and the strength within 1 (B). No roll.
- air search: each own air piece covers the areas within its range; the chance is the
  searcher's ``detect`` less the target's ``conceal``; strength within 1 (B).
- patrol: each own sea piece on patrol covers its zone and the zones next to it, by the
  same chance (B).
- codebreaking: each enemy piece that begins a move that day, at the nation's level's
  chance; the kind and the region it is bound for, no strength (C).
- agents: each agent reports one piece in its area a day at ``AGENT_CHANCE``, exactly (A).

A world's ``intelligence`` names, per nation and source, the person who reports it and
the channel; the report reaches the seats after that channel's days, and a page from the
person, dated the day made, carries it. A source no one is named for does not search,
except contact, which then reaches the seats the day it is made with no page. A world with
no ``intelligence`` has contact only.

A report can be wrong: at ``WRONG_BASE`` less ``WRONG_PER_COMPETENCE`` for each point of
the person's competence, its strength range is shifted by 2 or it names a bordering area;
the person's ``skew`` shifts every range one way. Nothing in a report says it is wrong.

A nation holds at most one delivered report per enemy piece, keyed by an opaque key of
its own, and the reports made but not yet arrived apart from it. On its arrival day a
pending report replaces the delivered one only when it is newer (day seen, then source
rank, then key); an older one that arrives late replaces nothing. A delivered report older
than ``STALE_DAYS`` is dropped. ``report_made`` events, engine only, are the history.

Five orders work the sources (IOR), each taking effect in the day walk after the close: a
reconnaissance flight (``order_recon``) searches one area in its air piece's range on the
next day's roll at ``RECON_CHANCE`` less each target's ``conceal``; a patrol is the patrol
posture on a sea piece; placing an agent (``place_agent``) puts one in an area after
``AGENT_DAYS``, up to ``AGENTS_MAX``, and a placed agent is exposed and lost at
``EXPOSE_CHANCE`` a day, its area's holder told by a paper; funding codebreaking
(``fund_codebreaking``) spends ``CODE_COST`` output, or a month of the nation's output
income where that is less (``code_cost``), and raises the level by one after
``CODE_DAYS``; concealment (``set_concealed``) adds ``CONCEAL_BONUS`` to a piece's
``conceal`` and a day to each of its steps until lifted. The aide files a patrol or a
flight at most (``aide_may``).
"""

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, ClassVar, NamedTuple

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import DocumentId, EntityId, FeatureId, derived_id
from revisionist.core.realism.card import ChannelKind

if TYPE_CHECKING:
    from revisionist.core import events as ev
    from revisionist.core.realism.geography import Feature
    from revisionist.core.state import State

AGENT_CHANCE = 30  # [proposed] percent a day that an agent reports a piece in its area
CODEBREAKING_CHANCE: Mapping[int, int] = {0: 0, 1: 10, 2: 25, 3: 40}  # [proposed] by level
WRONG_BASE = 10  # [proposed] percent a report is wrong, less ...
WRONG_PER_COMPETENCE = 2  # [proposed] ... this for each point of the person's competence
WRONG_SHIFT = 2  # a wrong report's strength range is shifted by this
STALE_DAYS = 14  # [proposed] a delivered report older than this is dropped
ORDINARY_COMPETENCE = 3  # a person with no card reports as an ordinary one
MAX_LEVEL = 3
AGENT_DAYS = 7  # [proposed] days from the order until a placed agent is in its area
AGENTS_MAX = 3  # [proposed] agents a nation has at once
EXPOSE_CHANCE = 5  # [proposed] percent a day that a placed agent is exposed and lost
CODE_COST = 10  # [proposed] output points funding codebreaking spends
CODE_DAYS = 30  # [proposed] days from the funding until the level rises
CONCEAL_BONUS = 30  # [proposed] what concealment adds to a piece's ``conceal``
RECON_CHANCE = 100  # a reconnaissance flight's search, less the target's ``conceal``


class Source(StrEnum):
    CONTACT = "contact"
    AIR = "air"
    PATROL = "patrol"
    CODEBREAKING = "codebreaking"
    AGENT = "agent"


class Confidence(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class Shift(StrEnum):
    """How a wrong report is wrong. Engine only: never in a report or a view."""

    STRENGTH = "strength"
    AREA = "area"


class Informant(Model):
    """The person who reports one source for a nation, the channel, and the source's rank
    (its place in the world's list, from 1, the first highest). Contact no one is named
    for reports with rank 0, above every listed source."""

    source: Source
    person: EntityId
    channel: ChannelKind
    rank: int = Field(ge=1)
    skew: int = Field(default=0, ge=-5, le=5)
    """A bias that shifts every strength range this person reports one way."""


class Agent(Model):
    area: EntityId
    until: date | None = None
    """The last day the agent reports. None: no end."""
    since: date | None = None
    """A placed agent: the first day it is in its area (IOR). None: declared at the start,
    there from the start and never exposed."""
    lost: date | None = None
    """A placed agent exposed: the day it was lost (IOR). None while it works."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"since", "lost"})

    def works(self, day: date) -> bool:
        """In its area and reporting on ``day``."""
        return (
            (self.since is None or self.since <= day)
            and (self.lost is None or day < self.lost)
            and (self.until is None or day <= self.until)
        )


class Intelligence(Model):
    """A nation's sources as declared at the start."""

    nation: EntityId
    sources: tuple[Informant, ...] = ()
    codebreaking: int = Field(default=0, ge=0, le=MAX_LEVEL)
    agents: tuple[Agent, ...] = ()
    raised: tuple[date, ...] = ()
    """Each day the codebreaking level rises by one, by funding (IOR)."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"raised"})

    @model_validator(mode="after")
    def _one_each(self) -> "Intelligence":
        kinds = [s.source for s in self.sources]
        if len(set(kinds)) != len(kinds):
            raise ValueError("intelligence: one person per source")
        ranks = [s.rank for s in self.sources]
        if len(set(ranks)) != len(ranks):
            raise ValueError("intelligence: one source per rank")
        return self


Strength = tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)]]


class Report(Model):
    """What a nation believes about one enemy piece, from one source on one day."""

    key: Label
    """Opaque and per nation; never the piece's id."""
    kind: Label | None = None
    """The piece kind's key; None: unknown."""
    strength: Strength | None = None
    """The lowest and highest strength the report allows; None: not known."""
    area: EntityId | None = None
    region: Label | None = None
    """A codebreaking report: the region the piece is bound for, in place of an area."""
    seen: date
    source: Source
    rank: int = Field(ge=0)
    confidence: Confidence
    arrives: date

    @model_validator(mode="after")
    def _shape(self) -> "Report":
        if self.arrives < self.seen:
            raise ValueError("report: arrives before it was seen")
        if self.strength is not None and self.strength[0] > self.strength[1]:
            raise ValueError("report: strength range runs backwards")
        if (self.area is None) == (self.region is None):
            raise ValueError("report: an area or a region")
        return self

    def order(self) -> tuple[date, int, str]:
        """Newer sorts later: day seen, then source rank (the world's first ranks highest),
        then key."""
        return (self.seen, -self.rank, self.key)


class Picture(Model):
    """A nation's reports: the delivered one per enemy piece, by key, and those made but
    not yet arrived."""

    delivered: dict[Label, Report] = Field(default_factory=dict)
    pending: tuple[Report, ...] = ()


def received(picture: Picture, today: date) -> Picture:
    """``picture`` on ``today``: every pending report that has arrived judged against the
    delivered one (the newer stays), and every delivered report older than
    ``STALE_DAYS`` dropped. The order the reports were made in changes nothing."""
    delivered = dict(picture.delivered)
    pending: list[Report] = []
    for r in sorted(picture.pending, key=Report.order):
        if r.arrives > today:
            pending.append(r)
            continue
        held = delivered.get(r.key)
        if held is None or r.order() > held.order():
            delivered[r.key] = r
    fresh = {k: r for k, r in delivered.items() if (today - r.seen).days <= STALE_DAYS}
    return Picture(delivered=fresh, pending=tuple(pending))


def made(picture: Picture, report: Report) -> Picture:
    """``picture`` with ``report`` added, as of the day it was seen."""
    added = picture.model_copy(update={"pending": (*picture.pending, report)})
    return received(added, report.seen)


# --- what a seat sees -----------------------------------------------------------


def seen_by(state: "State", nation: EntityId | None) -> dict[Label, Report]:
    """The reports that have reached ``nation``'s seats by the game's date, by key."""
    today = state.in_world_date
    picture = state.reports.get(nation) if nation is not None else None
    if picture is None or today is None:
        return {}
    return dict(sorted(received(picture, today).delivered.items()))


def envoys(state: "State", nation: EntityId | None) -> dict[Label, Report]:
    """With ``territories`` on, every other nation's envoy in play, as an exact report of
    today: an envoy is an accredited mission, public to every seat, and no roll is made
    on it (ENV). Made at projection only, never stored."""
    from revisionist.core.realism import kinds, territory
    from revisionist.core.realism.geography import in_play

    today = state.in_world_date
    if today is None or not territory.on(state) or state.map is None:
        return {}
    out: dict[Label, Report] = {}
    for f in sorted(state.features.values(), key=lambda x: x.feature_id):
        kind = kinds.of(state, f)
        if kind is None or kind.domain is not kinds.Domain.ENVOY or not in_play(f):
            continue
        if territory.nation(state, f.side) in (None, nation):
            continue
        key = report_key(state, nation if nation is not None else EntityId(""), f.feature_id)
        out[key] = Report(
            key=key,
            kind=kind.key,
            area=f.places[0],
            seen=today,
            source=Source.CONTACT,
            rank=0,
            confidence=Confidence.A,
            arrives=today,
        )
    return out


# --- the day's rolls --------------------------------------------------------------


def on(state: "State") -> bool:
    from revisionist.core.state import Rule

    return Rule.REPORTS in state.rules and Rule.TERRITORIES in state.rules and state.map is not None


def report_key(state: "State", nation: EntityId, piece: FeatureId) -> str:
    """A nation's key for an enemy piece. The web boundary keys it again under a
    deployment secret before a seat sees it, as it does a mark."""
    raw = "\x1f".join((str(state.campaign_id), "report", str(nation), str(piece)))
    return "r" + hashlib.blake2b(raw.encode(), digest_size=8).hexdigest()


def roll(state: "State", day: date, nation: EntityId, source: str, subject: str) -> int:
    """0 to 99, from the campaign, the day, the nation, the source and the subject only."""
    raw = "\x1f".join(
        (str(state.campaign_id), "detect", day.isoformat(), str(nation), source, subject)
    )
    return int.from_bytes(hashlib.blake2b(raw.encode(), digest_size=8).digest(), "big") % 100


class Sighting(NamedTuple):
    """One source's sighting of one piece, before it becomes a report."""

    source: Source
    force: "Feature"
    confidence: Confidence
    area: EntityId | None
    region: str | None
    exact: bool
    """True: the true strength; False: within 1; with no area, no strength."""


def _forces(state: "State") -> list["Feature"]:
    from revisionist.core.realism import kinds
    from revisionist.core.realism.geography import in_play

    return sorted(
        (f for f in state.features.values() if in_play(f) and kinds.is_force(state, f)),
        key=lambda f: f.feature_id,
    )


def _enemy(state: "State", nation: EntityId, piece: "Feature") -> bool:
    from revisionist.core.realism import territory

    theirs = territory.nation(state, piece.side)
    return theirs is not None and theirs != nation and not territory.allied(state, nation, theirs)


def nations(state: "State") -> list[EntityId]:
    """Every nation that searches: one with a force in play or a declared intelligence."""
    from revisionist.core.realism import territory

    found = {territory.nation(state, f.side) for f in _forces(state)} | set(state.intelligence)
    return sorted(n for n in found if n is not None)


def _chance(state: "State", searcher: "Feature", target: "Feature") -> int:
    from revisionist.core.realism import kinds

    a = kinds.of(state, searcher)
    return max(0, (a.detect if a else 0) - conceal(state, target))


def concealed(piece: "Feature") -> bool:
    """Concealed by order, or on the course of a concealed leg of the record (IOR)."""
    return piece.concealed or (piece.concealed_leg and bool(piece.path))


def conceal(state: "State", piece: "Feature") -> int:
    """The piece's ``conceal``: its kind's, and ``CONCEAL_BONUS`` while it is concealed."""
    from revisionist.core.realism import kinds

    kind = kinds.of(state, piece)
    return (kind.conceal if kind else 0) + (CONCEAL_BONUS if concealed(piece) else 0)


def level(state: "State", nation: EntityId, day: date) -> int:
    """The nation's codebreaking level on ``day``: the declared one, and one for each
    funded rise due by then, to at most ``MAX_LEVEL``."""
    intel = state.intelligence.get(nation)
    if intel is None:
        return 0
    return min(MAX_LEVEL, intel.codebreaking + sum(1 for d in intel.raised if d <= day))


def _informant(state: "State", nation: EntityId, source: Source) -> Informant | None:
    intel = state.intelligence.get(nation)
    return next((s for s in intel.sources if s.source is source), None) if intel else None


def _covered(
    state: "State", own: list["Feature"], source: Source
) -> dict[EntityId, list["Feature"]]:
    """Each area the source covers, with the searchers that cover it."""
    from revisionist.core.realism import kinds, territory
    from revisionist.core.realism.effect import Posture

    board = state.map
    assert board is not None
    out: dict[EntityId, list[Feature]] = {}
    for f in own:
        here = f.places[0]
        domain = kinds.domain(state, f)
        kind = kinds.of(state, f)
        if source is Source.AIR and domain is kinds.Domain.AIR and kind is not None:
            reach = territory.steps_from(board, "air", [here])
            areas = [a for a, n in reach.items() if n <= (kind.range_steps or 0)]
        elif source is Source.PATROL and domain is kinds.Domain.SEA and f.posture is Posture.PATROL:
            areas = [here, *territory.neighbours(board, here, kinds.Domain.SEA)]
        else:
            continue
        for a in areas:
            out.setdefault(a, []).append(f)
    return out


def _flown(own: list["Feature"], day: date) -> set[EntityId]:
    """The areas the nation's ordered reconnaissance flights search on ``day``."""
    return {f.recon for f in own if f.recon is not None and f.recon_on == day}


def exposed(state: "State", day: date, nation: EntityId, n: int, agent: Agent) -> bool:
    """Whether the nation's placed agent ``n`` is exposed on ``day``, at
    ``EXPOSE_CHANCE``. An agent declared at the start never is."""
    if agent.since is None or not agent.works(day):
        return False
    subject = f"{n}\x1f{agent.area}"
    return roll(state, day, nation, "agent-exposed", subject) < EXPOSE_CHANCE


def _region(state: "State", area: EntityId) -> str | None:
    board = state.map
    assert board is not None
    for t in board.territories:
        if t.area == area:
            return t.region
    for z in board.sea_zones:
        if z.area == area:
            return z.region
    return None


def _target(piece: "Feature") -> EntityId | None:
    return piece.path[-1] if piece.path else None


def sightings(state: "State", start: "State", day: date, nation: EntityId) -> list[Sighting]:
    """Every sighting ``nation``'s sources make on ``day``, each piece once per source.
    ``start`` is the state as the day began, to tell which pieces began a move."""
    from revisionist.core.realism import territory

    board = state.map
    assert board is not None
    forces = _forces(state)
    own = [f for f in forces if territory.nation(state, f.side) == nation]
    enemies = [f for f in forces if _enemy(state, nation, f)]
    out: list[Sighting] = []
    here = {f.places[0] for f in own}
    near = {n for a in here for n in _borders(state, a)}
    for e in enemies:
        area = e.places[0]
        if area in here:
            out.append(Sighting(Source.CONTACT, e, Confidence.A, area, None, True))
        elif area in near:
            out.append(Sighting(Source.CONTACT, e, Confidence.B, area, None, False))
    for source in (Source.AIR, Source.PATROL):
        if _informant(state, nation, source) is None:
            continue
        cover = _covered(state, own, source)
        flown = _flown(own, day) if source is Source.AIR else set()
        for e in enemies:
            searchers = cover.get(e.places[0], [])
            if not searchers and e.places[0] not in flown:
                continue
            chances = [_chance(state, s, e) for s in searchers]
            if e.places[0] in flown:
                chances.append(max(0, RECON_CHANCE - conceal(state, e)))
            if roll(state, day, nation, source.value, str(e.feature_id)) < max(chances):
                out.append(Sighting(source, e, Confidence.B, e.places[0], None, False))
    intel = state.intelligence.get(nation)
    if intel is not None and _informant(state, nation, Source.CODEBREAKING) is not None:
        chance = CODEBREAKING_CHANCE[level(state, nation, day)]
        for e in enemies:
            was = start.features.get(e.feature_id)
            bound = _target(e)
            if bound is None or (was is not None and _target(was) == bound):
                continue
            if roll(state, day, nation, Source.CODEBREAKING.value, str(e.feature_id)) < chance:
                out.append(
                    Sighting(
                        Source.CODEBREAKING, e, Confidence.C, None, _region(state, bound), False
                    )
                )
    if intel is not None and _informant(state, nation, Source.AGENT) is not None:
        seen: set[FeatureId] = set()
        for n, agent in enumerate(intel.agents):
            if not agent.works(day) or exposed(state, day, nation, n, agent):
                continue
            there = [e for e in enemies if e.places[0] == agent.area and e.feature_id not in seen]
            subject = f"{n}\x1f{agent.area}"
            if not there or roll(state, day, nation, Source.AGENT.value, subject) >= AGENT_CHANCE:
                continue
            pick = there[roll(state, day, nation, "agent-pick", subject) % len(there)]
            seen.add(pick.feature_id)
            out.append(Sighting(Source.AGENT, pick, Confidence.A, agent.area, None, True))
    return out


def _borders(state: "State", area: EntityId) -> list[EntityId]:
    board = state.map
    assert board is not None
    return sorted(
        {
            link.b if link.a == area else link.a
            for link in board.adjacency
            if area in (link.a, link.b)
        }
    )


def _competence(state: "State", person: EntityId) -> int:
    card = state.cards.get(person)
    return card.competence if card is not None else ORDINARY_COMPETENCE


def _clamp(lo: int, hi: int, top: int) -> tuple[int, int]:
    return (min(max(lo, 0), top), min(max(hi, 0), top))


def report(state: "State", day: date, nation: EntityId, s: Sighting) -> tuple[Report, Shift | None]:
    """The report a sighting makes, and how it is wrong, if it is."""
    from revisionist.core.realism import kinds
    from revisionist.core.realism.reach import transit_days

    piece = s.force
    kind = kinds.of(state, piece)
    top = kind.max_strength if kind is not None else kinds.MAX_STRENGTH
    subject = str(piece.feature_id)
    who = _informant(state, nation, s.source)
    tag = s.source.value
    strength: tuple[int, int] | None = None
    if s.area is not None:
        if s.exact:
            strength = (piece.tier, piece.tier)
        else:
            centre = piece.tier + roll(state, day, nation, f"{tag}-estimate", subject) % 3 - 1
            strength = (centre - 1, centre + 1)
    area, region = s.area, s.region
    shift: Shift | None = None
    if who is not None:
        chance = max(0, WRONG_BASE - WRONG_PER_COMPETENCE * _competence(state, who.person))
        if roll(state, day, nation, f"{tag}-wrong", subject) < chance:
            how = roll(state, day, nation, f"{tag}-how", subject)
            moved = _borders(state, s.area or _target(piece) or piece.places[0])
            if strength is not None and (how % 2 == 0 or not moved):
                d = WRONG_SHIFT if how % 4 < 2 else -WRONG_SHIFT
                strength = (strength[0] + d, strength[1] + d)
                shift = Shift.STRENGTH
            elif moved:
                other = moved[how % len(moved)]
                if area is not None:
                    area = other
                else:
                    region = _region(state, other)
                shift = Shift.AREA
        if strength is not None:
            strength = (strength[0] + who.skew, strength[1] + who.skew)
    if strength is not None:
        strength = _clamp(strength[0], strength[1], top)
    arrives = day + timedelta(days=transit_days(who.channel) if who is not None else 0)
    made_report = Report(
        key=report_key(state, nation, piece.feature_id),
        kind=None if kind is None else kind.key,
        strength=strength,
        area=area,
        region=region if area is None else None,
        seen=day,
        source=s.source,
        rank=who.rank if who is not None else 0,
        confidence=s.confidence,
        arrives=arrives,
    )
    return made_report, shift


def walk(state: "State", start: "State", day: date) -> list["ev.Payload"]:
    """Every nation's reports for ``day``, then each source's page to the nation's seats.
    ``start`` is the state as the day began."""
    from revisionist.core import events as ev

    if not on(state):
        return []
    out: list[ev.Payload] = []
    for nation in nations(state):
        out.extend(_exposures(state, day, nation))
        made_today: list[Report] = []
        for s in sightings(state, start, day, nation):
            r, shift = report(state, day, nation, s)
            made_today.append(r)
            out.append(
                ev.ReportMade(nation=nation, piece=s.force.feature_id, report=r, shift=shift)
            )
        out.extend(pages(state, day, nation, made_today))
    return out


def _exposures(state: "State", day: date, nation: EntityId) -> list["ev.Payload"]:
    """Each of the nation's placed agents exposed on ``day``: lost, and a paper to each
    seat of the holder of its area (none for a sea zone, nor for the nation's own)."""
    from revisionist.core import events as ev

    intel = state.intelligence.get(nation)
    out: list[ev.Payload] = []
    for n, agent in enumerate(intel.agents if intel is not None else ()):
        if exposed(state, day, nation, n, agent):
            lost = agent.model_copy(update={"lost": day})
            out.append(ev.AgentSet(nation=nation, index=n, agent=lost))
            out.extend(_caught(state, day, nation, n, agent.area))
    return out


def _caught(
    state: "State", day: date, nation: EntityId, n: int, area: EntityId
) -> list["ev.Payload"]:
    from revisionist.core import events as ev
    from revisionist.core.realism import actors, territory
    from revisionist.core.realism.card import ChannelKind
    from revisionist.core.realism.document import (
        BodyField,
        Classification,
        DocumentKind,
        DocumentTruth,
        DocumentView,
    )
    from revisionist.core.realism.war import polity_of
    from revisionist.core.visibility import private_to

    held = territory.holder(state, area)
    if held is None or held == nation:
        return []
    where = state.entities[area].name[:60]
    spy = state.entities[nation].name[:60]
    out: list[ev.Payload] = []
    for s in sorted(state.seats.values(), key=lambda s: s.seat_id):
        if s.seat_id not in actors.readers(state) or polity_of(state, s.embodies) != held:
            continue
        doc_id = DocumentId(
            derived_id(state.campaign_id, "agent-caught", nation, n, day.isoformat(), s.seat_id)
        )
        out.append(
            ev.DocumentIssued(
                document=DocumentView(
                    doc_id=doc_id,
                    kind=DocumentKind.REPORT,
                    author=held,
                    issued=day,
                    arrives=day,
                    channel=ChannelKind.CABLE,
                    classification=Classification.SECRET,  # [proposed]
                    title=f"Agent caught in {where}"[:60],
                    body=(
                        BodyField(label="Area", value=where),
                        BodyField(label="Working for", value=spy),
                        BodyField(label="Caught", value=day.isoformat()),
                    ),
                    scope=private_to(s.seat_id),
                ),
                truth=DocumentTruth(doc_id=doc_id),
            )
        )
    return out


# --- the intelligence orders (IOR) ----------------------------------------------------


class IntelError(ValueError):
    """An intelligence order the rules refuse, with the reason in plain words."""


def _need_on(state: "State") -> None:
    if not on(state):
        raise IntelError("The reports rule is off in this game.")


def _name(state: "State", entity: EntityId) -> str:
    found = state.entities.get(entity)
    return found.name if found is not None else str(entity)


def _need_informant(state: "State", nation: EntityId, source: Source) -> None:
    if _informant(state, nation, source) is None:
        raise IntelError(f"No one reports {source.value} for {_name(state, nation)}.")


def _need_area(state: "State", area: EntityId) -> None:
    board = state.map
    assert board is not None
    if area not in set(board.areas()):
        raise IntelError(f"{_name(state, area)} is not an area of the map.")


def order_recon(
    state: "State", polity: EntityId, piece: FeatureId, area: EntityId, on: date
) -> tuple["Feature", ...]:
    """A reconnaissance flight: ``piece``, an own air piece, searches ``area``, within its
    range, on the next day's roll at ``RECON_CHANCE`` less each target's ``conceal``.
    Raises ``IntelError`` when the rules refuse it."""
    from revisionist.core.realism import kinds, territory
    from revisionist.core.realism.geography import in_play

    _need_on(state)
    _need_informant(state, polity, Source.AIR)
    flier = state.features.get(piece)
    if flier is None or not in_play(flier):
        raise IntelError("There is no piece to fly.")
    if territory.nation(state, flier.side) != polity:
        raise IntelError(f"{flier.name} is not {_name(state, polity)}'s.")
    kind = kinds.of(state, flier)
    if kind is None or kind.domain is not kinds.Domain.AIR:
        raise IntelError(f"{flier.name} is not an air piece.")
    _need_area(state, area)
    board = state.map
    assert board is not None
    steps = territory.steps_from(board, "air", [flier.places[0]]).get(area)
    if steps is None or steps > (kind.range_steps or 0):
        raise IntelError(f"{_name(state, area)} is beyond {flier.name}'s range.")
    return (flier.model_copy(update={"recon": area, "recon_on": on + timedelta(days=1)}),)


def _working(intel: Intelligence | None, on: date) -> int:
    """The nation's agents in place or on their way on ``on``: neither lost nor ended."""
    if intel is None:
        return 0
    return sum(1 for a in intel.agents if a.lost is None and (a.until is None or a.until >= on))


def place_agent(
    state: "State", polity: EntityId, area: EntityId, on: date
) -> tuple["ev.AgentSet", ...]:
    """An agent placed in ``area``: there from ``AGENT_DAYS`` after ``on``, while the
    nation has fewer than ``AGENTS_MAX``. Raises ``IntelError`` when the rules refuse it."""
    from revisionist.core import events as ev

    _need_on(state)
    _need_informant(state, polity, Source.AGENT)
    _need_area(state, area)
    intel = state.intelligence.get(polity)
    if _working(intel, on) >= AGENTS_MAX:
        raise IntelError(f"{_name(state, polity)} has at most {AGENTS_MAX} agents at once.")
    agent = Agent(area=area, since=on + timedelta(days=AGENT_DAYS))
    index = len(intel.agents) if intel is not None else 0
    return (ev.AgentSet(nation=polity, index=index, agent=agent),)


def code_cost(state: "State", polity: EntityId, on: date) -> float:
    """What funding codebreaking costs ``polity`` on ``on``: ``CODE_COST`` output, or a
    month of its output income where that is less, never under 1 point."""
    from revisionist.core.realism import economy
    from revisionist.core.realism.kinds import Role

    month = round(economy.income(state, polity, Role.OUTPUT, on), 6)
    return float(max(1.0, min(float(CODE_COST), month)))


def fund_codebreaking(
    state: "State", polity: EntityId, on: date
) -> tuple["ev.EconomySet", "ev.CodebreakingSet"]:
    """``code_cost`` spent from the output pool, and the codebreaking level one higher from
    ``CODE_DAYS`` after ``on``, to at most ``MAX_LEVEL`` counting rises still to come.
    Raises ``IntelError`` when the rules refuse it."""
    from revisionist.core import events as ev
    from revisionist.core.state import Rule

    _need_on(state)
    if Rule.ECONOMY not in state.rules:
        raise IntelError("The economy rule is off in this game.")
    _need_informant(state, polity, Source.CODEBREAKING)
    intel = state.intelligence.get(polity)
    assert intel is not None  # an informant is named in it
    reached = intel.codebreaking + len(intel.raised)
    if reached >= MAX_LEVEL:
        raise IntelError(f"Codebreaking is at level {MAX_LEVEL} already, or will be.")
    cost = code_cost(state, polity, on)
    pools = state.economy.pools.get(polity)
    if pools is None or pools.output < cost:
        raise IntelError(f"Funding codebreaking needs {cost:g} points of output.")
    spent = pools.model_copy(update={"output": round(pools.output - cost, 6)})
    return (
        ev.EconomySet(polity=polity, pools=spent, on=on),
        ev.CodebreakingSet(nation=polity, level=reached + 1, on=on + timedelta(days=CODE_DAYS)),
    )


def set_concealed(
    state: "State", piece: FeatureId, concealed: bool, on: date
) -> tuple["Feature", ...]:
    """The piece concealed (its ``conceal`` up by ``CONCEAL_BONUS``, each step a day
    longer) or the concealment lifted. Raises ``IntelError`` when the rules refuse it."""
    from revisionist.core.realism import kinds
    from revisionist.core.realism.geography import in_play

    _need_on(state)
    found = state.features.get(piece)
    if found is None or not in_play(found) or not kinds.is_force(state, found):
        raise IntelError("There is no piece to conceal.")
    return (found.model_copy(update={"concealed": concealed, "as_of": max(on, found.as_of)}),)


def aide_may[E: Model](effect: E) -> E | None:
    """What of ``effect`` the aide may file for an absent seat (IOR rule 7): a patrol or a
    reconnaissance flight at most, never an agent, funding or a concealment. None when
    nothing is left."""
    from revisionist.core.realism.effect import Allocate, IntelOrder, Investigate, SetEngagement

    if isinstance(effect, Investigate) and effect.intel is IntelOrder.AGENT:
        return None
    if isinstance(effect, Allocate) and effect.intel is not None:
        return None
    if isinstance(effect, SetEngagement) and effect.concealed is not None:
        return effect.model_copy(update={"concealed": None})
    return effect


class Barred(StrEnum):
    """An act the aide never does for an absent seat, whatever a standing order says.

    Most are seat actions the aide has no path to; ``barred`` tells the two an order's
    typed effect can carry. A breakaway, a plot and a purge are listed by name ahead of
    any rule that lets a seat do one."""

    SEND_HELD = "send a held order anyway"
    REFUSE = "refuse an order from above"
    ASK_HELD = "ask for a held order"
    ANSWER = "answer an ask or a matter as a decider or a council member"
    BLOC_OFFER = "make an offer to a bloc"
    OFFICE_VOTE = "vote at a sitting on an office"
    ACCEPT = "accept an agreement, a peace among them"
    APPOINT = "appoint or dismiss anyone not named in a standing order"
    BREAKAWAY = "break away"
    PLOT = "launch a plot"
    PURGE = "order a purge"


AIDE_BAR: frozenset[Barred] = frozenset(Barred)
"""The aide's bar: checked where the aide's orders are chosen and again where each lands."""

BAR_RULES: frozenset[str] = frozenset({"appointment"})
"""Irreversible effect kinds the bar rules on, ahead of the standing-order rule."""


def barred[E: Model](effect: E, standing: frozenset[str]) -> Barred | None:
    """The act on the bar ``effect`` would do for an absent seat whose standing order
    names the effect kinds ``standing``, or None. A standing order names kinds, not
    people, so one naming appointments names every appointment."""
    from revisionist.core.realism.effect import Appointment, Deal, EffectKind

    act = None
    if isinstance(effect, Deal) and effect.accept:
        act = Barred.ACCEPT
    elif isinstance(effect, Appointment) and EffectKind.APPOINTMENT not in standing:
        act = Barred.APPOINT
    return act if act in AIDE_BAR else None


_TITLES = {
    Source.CONTACT: "Contact report",
    Source.AIR: "Air reconnaissance report",
    Source.PATROL: "Patrol report",
    Source.CODEBREAKING: "Decrypt",
    Source.AGENT: "Agent's report",
}


def _lines(state: "State", r: Report) -> Iterable[tuple[str, int | str | None]]:
    kind = state.kinds.pieces.get(r.kind) if state.kinds is not None and r.kind else None
    yield "Kind", kind.name[:60] if kind is not None else "unknown"
    if r.strength is not None:
        yield "Strength", f"{r.strength[0]} to {r.strength[1]}"
    if r.area is not None:
        yield "Area", state.entities[r.area].name[:60]
    if r.region is not None:
        yield "Bound for", r.region
    yield "Seen", r.seen.isoformat()
    yield "Confidence", r.confidence.value


def pages(
    state: "State", day: date, nation: EntityId, made_today: Sequence[Report]
) -> list["ev.DocumentIssued"]:
    """One page a source a day to each seat of ``nation``, from the person named for the
    source, dated ``day`` and arriving with the reports: each report's fields as lines. No
    page for a source no one is named for."""
    from revisionist.core import events as ev
    from revisionist.core.realism import actors
    from revisionist.core.realism.document import (
        BodyField,
        Classification,
        DocumentKind,
        DocumentTruth,
        DocumentView,
    )
    from revisionist.core.realism.war import polity_of
    from revisionist.core.visibility import private_to

    readers = sorted(
        s.seat_id
        for s in state.seats.values()
        if s.seat_id in actors.readers(state) and polity_of(state, s.embodies) == nation
    )
    out: list[ev.DocumentIssued] = []
    for source in Source:
        who = _informant(state, nation, source)
        mine = sorted((r for r in made_today if r.source is source), key=lambda r: r.key)
        if who is None or not mine:
            continue
        body = tuple(
            BodyField(label=label, value=value) for r in mine for label, value in _lines(state, r)
        )
        kind = DocumentKind.INTERCEPT if source is Source.CODEBREAKING else DocumentKind.REPORT
        for seat in readers:
            doc_id = DocumentId(
                derived_id(
                    state.campaign_id, "report-page", nation, source.value, day.isoformat(), seat
                )
            )
            out.append(
                ev.DocumentIssued(
                    document=DocumentView(
                        doc_id=doc_id,
                        kind=kind,
                        author=who.person,
                        issued=day,
                        arrives=mine[0].arrives,
                        channel=who.channel,
                        classification=Classification.SECRET,  # [proposed]
                        title=f"{_TITLES[source]}, {day.isoformat()}",
                        body=body,
                        scope=private_to(seat),
                    ),
                    truth=DocumentTruth(doc_id=doc_id),
                )
            )
    return out


__all__ = [
    "AGENTS_MAX",
    "AGENT_CHANCE",
    "AGENT_DAYS",
    "AIDE_BAR",
    "BAR_RULES",
    "CODEBREAKING_CHANCE",
    "CODE_COST",
    "CODE_DAYS",
    "CONCEAL_BONUS",
    "EXPOSE_CHANCE",
    "RECON_CHANCE",
    "STALE_DAYS",
    "WRONG_BASE",
    "WRONG_PER_COMPETENCE",
    "Agent",
    "Barred",
    "Confidence",
    "Informant",
    "IntelError",
    "Intelligence",
    "Picture",
    "Report",
    "Shift",
    "Sighting",
    "Source",
    "aide_may",
    "barred",
    "code_cost",
    "conceal",
    "concealed",
    "exposed",
    "fund_codebreaking",
    "level",
    "made",
    "nations",
    "on",
    "order_recon",
    "pages",
    "place_agent",
    "received",
    "report",
    "report_key",
    "roll",
    "seen_by",
    "set_concealed",
    "sightings",
    "walk",
]
