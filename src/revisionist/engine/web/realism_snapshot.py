"""Builds the realism JSON shapes from one seat's ``View``.

Every builder reads only the view, with two exceptions the caller supplies: the
pipelines an order runs through (``View`` does not carry them, and a step's holder
is not otherwise known) and the next in-world date (it needs the calendar). The map
reads the truth for two things only: the opaque key of each mark, and the seat's own
pieces (the forces its movement forms name), which it knows as they are. Names
replace ids wherever a person is shown. ``snapshot.checked`` is the caller's last step.
"""

import hashlib
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal

from revisionist.core import events as ev
from revisionist.core import history
from revisionist.core.events import Event
from revisionist.core.ids import DocumentId, EntityId, FeatureId, PipelineId, SeatId, derived_id
from revisionist.core.ontology import EntityKind
from revisionist.core.project import project
from revisionist.core.realism import detect, kinds, territory
from revisionist.core.realism.advance import next_wake
from revisionist.core.realism.card import Lever, ParamKind, ParamSpec, words
from revisionist.core.realism.document import BodyField, DocumentView
from revisionist.core.realism.effect import PartView
from revisionist.core.realism.geography import Feature, in_play
from revisionist.core.realism.pipeline import (
    Order,
    OrderStatus,
    Pipeline,
    StepAction,
    StepOutcome,
    step_due,
)
from revisionist.core.realism.pipelines import destination, place_named
from revisionist.core.realism.resolvers import intel
from revisionist.core.state import State, View
from revisionist.core.world_compile import object_id
from revisionist.engine import campaign as cmp
from revisionist.engine.aide import AideBrief
from revisionist.engine.directive import Proposal, channels
from revisionist.engine.web import (
    agreements_api,
    battles_api,
    conferences_api,
    dossiers,
    economy_api,
    home_api,
    locks_api,
    map_api,
    stakes,
)
from revisionist.engine.web.destinations import (
    FORCE,
    Known,
    force_keys,
    latest_sightings,
    lift_facts,
    own_sides,
    place_choices,
    reported,
)
from revisionist.engine.web.people import posts_block, seat_people
from revisionist.engine.web.realism_api import (
    BodyLine,
    Clock,
    ContactLine,
    CounselLine,
    Desk,
    DirectiveProposal,
    DocumentListing,
    DocumentListItem,
    DocumentPage,
    LeverChoice,
    LeverLine,
    LeverParam,
    MapCapital,
    MapMark,
    MapOrder,
    MapPiece,
    MapPlace,
    MapReport,
    MarkArea,
    OrderTrack,
    OrderTracker,
    People,
    PieceArea,
    PieceCourse,
    PieceWait,
    PublicWar,
    SeatMap,
    Situation,
    SituationFigure,
    SituationReading,
    SituationSource,
    StepLine,
    WarNation,
    WorldDevelopment,
)
from revisionist.engine.web.threats import seat_threats
from revisionist.engine.web.tray import acknowledgement, feed_group

_HIDDEN = frozenset({StepAction.STALL, StepAction.LEAK})
"""Outcomes the issuer never sees: an order that stalls is still with that person."""

if TYPE_CHECKING:
    from revisionist.engine.odds import Ended


def lever_label(lever: Lever) -> str:
    return lever.label or words(lever.name)


def _intel_form(lever: Lever) -> str | None:
    form = intel.form_of(lever)
    return None if form is None else form.value


def _param_label(spec: ParamSpec) -> str:
    return spec.label or words(spec.name)


def _choices(spec: ParamSpec) -> list[LeverChoice]:
    spoken = spec.choice_labels or tuple(words(c) for c in spec.choices)
    return [LeverChoice(value=v, label=t) for v, t in zip(spec.choices, spoken, strict=True)]


def _term(spec: ParamSpec, value: int | str, view: View | None = None) -> str:
    shown = str(value)
    if spec.kind is ParamKind.ENUM:
        place = place_named(view, shown) if view is not None else None
        named = place.name if place is not None else words(shown)
        shown = next((c["label"] for c in _choices(spec) if c["value"] == value), named)
    return f"{_param_label(spec)}: {shown}"


_TRAILING_DATE = re.compile(r", (\d{4})-(\d{2})-(\d{2})$")


def _spoken_title(title: str) -> str:
    """A trailing ISO date becomes words: "MAGIC, 1941-09-03" -> "MAGIC, 3 September 1941"."""
    found = _TRAILING_DATE.search(title)
    if found is None:
        return title
    try:
        day = date(*(int(g) for g in found.groups()))
    except ValueError:
        return title
    return f"{title[: found.start()]}, {day.day} {day:%B %Y}"


def _answers(view: View) -> dict[DocumentId, PartView]:
    """The report papers on the parts of the seat's own routed orders, each with its part."""
    return {
        DocumentId(derived_id(view.campaign_id, "report", order.order_id, i)): part
        for order in view.routed.values()
        for i, part in enumerate(order.parts)
    }


def _item(
    view: View,
    doc_id: DocumentId,
    doc: DocumentView,
    unread: bool,
    flagged: bool,
    answers: Mapping[DocumentId, PartView],
) -> DocumentListItem:
    return DocumentListItem(
        id=doc_id,
        kind=doc.kind.value,
        title=_spoken_title(doc.title),
        author=view.entities[doc.author].name,
        issued=doc.issued.isoformat(),
        arrives=doc.arrives.isoformat(),
        channel=doc.channel.value,
        classification=doc.classification.value,
        unread=unread,
        flagged=flagged,
        group=feed_group(doc.title),
        ack=acknowledgement(doc, answers.get(doc_id)),
        answer=doc_id in answers,
    )


def documents(
    view: View, read_ids: set[DocumentId], flagged_ids: set[DocumentId]
) -> DocumentListing:
    """The in-tray: arrived pages, newest arrival first, ties by document ID."""
    arrived = sorted(view.documents.items(), key=lambda kv: kv[0])
    arrived.sort(key=lambda kv: kv[1].arrives, reverse=True)
    answers = _answers(view)
    rows = [
        _item(view, k, d, unread=k not in read_ids, flagged=k in flagged_ids, answers=answers)
        for k, d in arrived
    ]
    return DocumentListing(
        documents=rows,
        unread=sum(r["unread"] and not r["ack"] for r in rows),
        flagged=sum(r["flagged"] for r in rows),
    )


def document(view: View, doc_id: DocumentId, flagged: bool = False) -> DocumentPage:
    """One page. KeyError if the seat has not received it; fetching it counts as reading it.
    An intelligence paper's reports are one worded line each (``report_lines``)."""
    doc = view.documents[doc_id]
    body = report_lines(view, doc.body)
    return DocumentPage(
        item=_item(view, doc_id, doc, unread=False, flagged=flagged, answers=_answers(view)),
        body=(
            body
            if body is not None
            else [BodyLine(label=b.label, value=b.value, unit=b.unit) for b in doc.body]
        ),
        prose=doc.prose,
    )


CONFIDENCE_WORDS = {"A": "confirmed", "B": "probable", "C": "possible"}
"""[proposed] A report's confidence as its line words it."""

_REPORT_FIELDS = ("Kind", "Strength", "Area", "Bound for", "Seen", "Confidence")
"""The fields detection writes for one report, in order; ``Strength`` and one of ``Area``
and ``Bound for`` may be absent (``detect._lines``)."""


def _report_fields(body: Iterable[BodyField]) -> list[dict[str, str]] | None:
    """The page's reports, each its fields by label; None unless the whole page is
    reports as detection writes them."""
    out: list[dict[str, str]] = []
    for b in body:
        if b.sight is not None or not isinstance(b.value, str):
            return None
        if b.label == "Kind":
            out.append({})
        elif not out or b.label not in _REPORT_FIELDS or b.label in out[-1]:
            return None
        if _REPORT_FIELDS.index(b.label) < max(
            (_REPORT_FIELDS.index(k) for k in out[-1]), default=-1
        ):
            return None
        out[-1][b.label] = b.value
    whole = all(
        {"Kind", "Seen", "Confidence"} <= set(r) and ("Area" in r) != ("Bound for" in r)
        for r in out
    )
    return out if out and whole else None


def _spoken_iso(value: str) -> str:
    try:
        seen = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{seen.day} {seen:%B %Y}"


def _region_name(view: View, key: str) -> str:
    regions = view.map.regions if view.map is not None else ()
    return next((r.name for r in regions if r.key == key), words(key))


def report_lines(view: View, body: Iterable[BodyField]) -> list[BodyLine] | None:
    """An intelligence paper's reports, one line each: the kind, then the strength range,
    the area (or the region a decrypt says it is bound for), the day seen and the
    confidence in words. A wrong report is worded as a right one: nothing marks it. None
    for any other page, whose lines are shown as they are."""
    fields = _report_fields(body)
    if fields is None:
        return None
    out: list[BodyLine] = []
    for r in fields:
        kind = r["Kind"]
        strength = r.get("Strength")
        if strength is None:
            said = "strength not known"
        else:
            lo, _, hi = strength.partition(" to ")
            said = f"strength {lo}" if lo == hi else f"strength {strength}"
        where = r["Area"] if "Area" in r else f"bound for {_region_name(view, r['Bound for'])}"
        confidence = CONFIDENCE_WORDS.get(r["Confidence"], r["Confidence"])
        out.append(
            BodyLine(
                label="Unknown piece" if kind == "unknown" else kind,
                value=f"{said}, {where}, seen {_spoken_iso(r['Seen'])}, {confidence}",
                unit="",
            )
        )
    return out


_Reports = list[tuple[DocumentId, DocumentView, int | None]]
"""One source's reports of one figure, oldest arrival first."""

_HISTORY = 6  # [proposed] reports shown per source; the payload is re-sent on every refresh


def _trend(given: list[int]) -> Literal["up", "down", "level"] | None:
    if len(given) < 2:
        return None
    before, now = given[-2], given[-1]
    return "up" if now > before else "down" if now < before else "level"


def _source(view: View, author: EntityId, reports: _Reports) -> SituationSource:
    doc_id, latest, value = reports[-1]
    given = [(d.issued, v) for _, d, v in reports if v is not None]
    return SituationSource(
        author=view.entities[author].name,
        doc_id=doc_id,
        value=value,
        issued=latest.issued.isoformat(),
        arrives=latest.arrives.isoformat(),
        last_given=given[-1][0].isoformat() if given else None,
        trend=None if value is None else _trend([v for _, v in given]),
        history=[
            SituationReading(value=v, issued=d.issued.isoformat(), arrives=d.arrives.isoformat())
            for _, d, v in reports[-_HISTORY:]
        ],
    )


def situation(view: View) -> Situation:
    """Headline figures from the pages the seat has received, by arrival.

    A figure is a body line with a unit whose value is a number or silent; reply
    letters and leaks carry words and no unit, so they stay off the board. A
    silent latest report is a gap: nothing is carried forward or estimated.
    """
    lines: dict[tuple[str, str], dict[EntityId, _Reports]] = {}
    arrived = sorted(view.documents.items(), key=lambda kv: (kv[1].arrives, kv[1].issued, kv[0]))
    for doc_id, doc in arrived:
        for b in doc.body:
            if not b.unit or isinstance(b.value, str):
                continue
            by = lines.setdefault((b.label, b.unit), {})
            by.setdefault(doc.author, []).append((doc_id, doc, b.value))
    figures: list[SituationFigure] = []
    for (label, unit), by in sorted(lines.items()):
        sources = sorted(
            (_source(view, author, reports) for author, reports in by.items()),
            key=lambda s: s["author"],
        )
        latest = {s["value"] for s in sources if s["value"] is not None}
        figures.append(
            SituationFigure(label=label, unit=unit, sources=sources, disagree=len(latest) > 1)
        )
    return Situation(figures=figures)


STALE_DAYS = 14
"""[proposed] A position older than this is drawn as stale."""


def _place(view: View, e: EntityId) -> MapPlace | None:
    """The place ``e`` as the map draws it; None for one with no position (an area)."""
    place = view.entities.get(e)
    if place is None or place.at is None:
        return None
    at = place.at
    return MapPlace(name=place.name, lat=at[0], lon=at[1], theatre=place.theatre)


def _positioned(view: View, ids: Iterable[EntityId]) -> list[MapPlace]:
    return [p for p in (_place(view, e) for e in ids) if p is not None]


def _mark_areas(state: State | None) -> dict[EntityId, MarkArea]:
    """Each area of a territory game's board by its entity: its map file key and name."""
    board = state.map if state is not None and territory.on(state) else None
    if board is None:
        return {}
    shapes: list[territory.Territory | territory.SeaZone] = [*board.territories, *board.sea_zones]
    return {a.area: MarkArea(key=a.key, name=a.name) for a in shapes}


def _capitals(view: View, people: People) -> list[MapCapital]:
    """Each leader the roster weighs against the seat who has a stance there and a
    placed location of their own, with the roster's own stance and war flag."""
    out: list[MapCapital] = []
    for line in people["opponents"]:
        leader = view.entities.get(EntityId(line["person"]))
        # a capital that is an area has no point to pin until capitals are drawn on the board
        home = _place(view, leader.location) if leader and leader.location else None
        if line["stance"] is None or home is None:
            continue
        out.append(
            MapCapital(
                place=home,
                name=line["name"],
                stance=line["stance"],
                at_war=line["at_war"],
            )
        )
    return out


def _map_orders(
    view: View,
    marks: list[MapMark],
    forces: Mapping[str, str],
    pipelines: Mapping[PipelineId, Pipeline],
) -> list[MapOrder]:
    """The seat's own movement orders still to show: moving, or carried out but with no
    page yet placing the force where it was sent. ``forces`` names a force key's mark."""
    levers = {x.name: x for x in view.desk.levers} if view.desk is not None else {}
    out: list[MapOrder] = []
    for order in sorted(view.orders.values(), key=lambda o: (o.filed, o.order_id)):
        lever = levers.get(order.lever)
        if lever is None or lever.resolver != "movement":
            continue
        if order.status not in (OrderStatus.MOVING, OrderStatus.ENACTED):
            continue
        key, to_key = str(order.params.get("force", "")), str(order.params.get("to", ""))
        to = view.entities.get(EntityId(object_id(view.campaign_id, "entity", to_key)))
        if to is None or to.at is None:
            continue
        spec = next((p for p in lever.params if p.name == "force"), None)
        named = forces.get(key) or (_term(spec, key).split(": ", 1)[-1] if spec else words(key))
        mark = next((m for m in marks if m["name"] == forces.get(key)), None)
        if order.status is OrderStatus.ENACTED:
            settled = (order.outcomes[-1].on if order.outcomes else order.filed).isoformat()
            arrived = (
                mark is not None
                and mark["reported"] >= settled
                and any(p["name"] == to.name for p in mark["places"])
            )
            if arrived:
                continue
        moving = order.status is OrderStatus.MOVING
        pipeline = pipelines.get(order.pipeline)
        holder = (
            pipeline.steps[order.step].person
            if moving and pipeline is not None and order.step < len(pipeline.steps)
            else None
        )
        out.append(
            MapOrder(
                order=order.order_id,
                force=named,
                mark=mark["name"] if mark is not None else None,
                to=MapPlace(name=to.name, lat=to.at[0], lon=to.at[1], theatre=to.theatre),
                status="awaiting" if moving else "under_way",
                with_person=view.entities[holder].name if holder in view.entities else None,
                filed=order.filed.isoformat(),
            )
        )
    return out


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day is not None else None


def _label_key(campaign: object, polity: EntityId, label: str, kind: str) -> str:
    """The key of a mark whose page names no feature in its truth: as opaque as
    ``territory.mark_key``, from the line instead of the feature."""
    raw = "\x1f".join((str(campaign), "mark-line", str(polity), label, kind))
    return "m" + hashlib.blake2b(raw.encode(), digest_size=8).hexdigest()


def _sighted(state: State, doc_id: DocumentId, label: str, kind: str) -> Feature | None:
    """The feature behind a page's sighting line: the page's truth names each one, in the
    order of its sighting lines; else the feature of that name and kind."""
    doc = state.documents.get(doc_id)
    if doc is not None:
        lines = [b for b in doc.view.body if b.sight is not None]
        if len(lines) == len(doc.truth.sightings):
            for b, ref in zip(lines, doc.truth.sightings, strict=True):
                if b.label == label and b.sight is not None and b.sight.kind.value == kind:
                    return state.features.get(ref.feature_id)
    return next(
        (f for f in state.features.values() if f.name == label and f.kind.value == kind), None
    )


def _area(
    state: State, view: View, keys: Mapping[EntityId, str], at: EntityId, domain: kinds.Domain
) -> PieceArea:
    """The area a piece of ``domain`` at ``at`` stands in; without territories, the place."""
    board = state.map
    if territory.on(state) and board is not None:
        area = territory.area_of(state, at, domain)
        shapes: list[territory.Territory | territory.SeaZone] = [
            *board.territories,
            *board.sea_zones,
        ]
        for a in shapes:
            if a.area == area:
                return PieceArea(key=a.key, name=a.name, place=_place(view, at))
    place = view.entities.get(at)
    return PieceArea(
        key=keys.get(at), name=place.name if place is not None else "", place=_place(view, at)
    )


def _waiting(
    view: View,
    key: str,
    pipelines: Mapping[PipelineId, Pipeline],
    withdrawable: Collection[str],
) -> PieceWait | None:
    """The seat's latest movement order for the force ``key`` still in its pipeline."""
    movers = {x.name for x in view.desk.levers if x.resolver == "movement"} if view.desk else set()
    waiting = [
        o
        for o in view.orders.values()
        if o.status is OrderStatus.MOVING
        and o.lever in movers
        and str(o.params.get(FORCE, "")) == key
    ]
    if not waiting:
        return None
    order = max(waiting, key=lambda o: (o.filed, o.order_id))
    pipeline = pipelines.get(order.pipeline)
    holder = (
        pipeline.steps[order.step].person
        if pipeline is not None and order.step < len(pipeline.steps)
        else None
    )
    return PieceWait(
        order=order.order_id,
        with_person=view.entities[holder].name if holder in view.entities else None,
        until=_iso(step_due(order, pipeline)) if pipeline is not None else None,
        withdrawable=order.order_id in withdrawable,
    )


def _course(
    state: State, view: View, keys: Mapping[EntityId, str], f: Feature, domain: kinds.Domain
) -> PieceCourse | None:
    if f.path:
        due = f.step_due
        begun = map_api.step_began(state, f, f.path[0], due, f.as_of) if due else None
        return PieceCourse(
            path=[_area(state, view, keys, a, domain) for a in f.path],
            step_due=_iso(f.step_due),
            step_began=_iso(begun[0]) if begun is not None else None,
            step_days=begun[1] if begun is not None else None,
            arrives=_iso(f.arrives),
        )
    if f.bound_for is None:
        return None
    return PieceCourse(
        path=[_area(state, view, keys, f.bound_for, domain)],
        step_due=_iso(f.arrives),
        step_began=None,
        step_days=None,
        arrives=_iso(f.arrives),
    )


class _Sent:
    """What the map reads from the truth for one seat: mark keys and its own pieces."""

    def __init__(
        self,
        state: State,
        view: View,
        forces: Mapping[str, str],
        pipelines: Mapping[PipelineId, Pipeline],
        place_keys: Mapping[EntityId, str],
        withdrawable: Collection[str],
    ) -> None:
        self.state, self.view, self.forces = state, view, forces
        self.pipelines, self.place_keys, self.withdrawable = pipelines, place_keys, withdrawable
        self.polity = territory.nation(state, view.me.embodies) or view.me.embodies
        self.seen = map_api.seat_board(state, view) if territory.on(state) else None
        """The board the moves are lit on: only what the view holds (TMD)."""
        self.reaches: map_api.Reaches = {}

    def key(self, doc_id: DocumentId, label: str, kind: str) -> str:
        f = _sighted(self.state, doc_id, label, kind)
        if f is None:
            return _label_key(self.state.campaign_id, self.polity, label, kind)
        return territory.mark_key(self.state, self.polity, f)

    def _area_namer(self, domain: kinds.Domain) -> Callable[[EntityId], PieceArea]:
        """Names an area as the map names a piece's area."""
        return lambda at: _area(self.state, self.view, self.place_keys, at, domain)

    def pieces(self) -> list[tuple[Feature, MapPiece]]:
        """Each own force in play the seat's movement forms name, as a piece."""
        own = own_sides(self.view)
        out: list[tuple[Feature, MapPiece]] = []
        for key in self.forces:
            fid = FeatureId(object_id(self.state.campaign_id, "feature", key))
            f = self.state.features.get(fid)
            domain = kinds.domain(self.state, f) if f is not None else None
            if f is None or domain is None or f.side not in own or not in_play(f):
                continue
            kind = kinds.of(self.state, f)
            mark = territory.mark_key(self.state, self.polity, f)
            piece = MapPiece(
                key=mark,
                kind=kind.name if kind is not None else words(f.kind.value),
                domain=domain.value,
                strength=f.tier,
                posture=f.posture.value if f.posture is not None else None,
                area=_area(self.state, self.view, self.place_keys, f.places[0], domain),
                waiting=_waiting(self.view, key, self.pipelines, self.withdrawable),
                under_way=_course(self.state, self.view, self.place_keys, f, domain),
            )
            if self.seen is not None:
                piece["moves"] = map_api.lit(self.seen, f, self._area_namer(domain), self.reaches)
            out.append((f, piece))
        return out


def _own_mark(view: View, f: Feature, piece: MapPiece) -> MapMark:
    """An own piece no page has placed: known where the truth has it."""
    today = view.in_world_date
    place = _place(view, f.places[0])
    return MapMark(
        key=piece["key"],
        name=f.name,
        kind=f.kind.value,
        side="own",
        side_name=view.entities[f.side].name if f.side in view.entities else "",
        certainty="known",
        places=[place] if place is not None else [],
        area=None,
        reported=today.isoformat() if today is not None else "",
        source="",
        document="",
        strength=None,
        piece=piece,
    )


def _paper(view: View, nation: EntityId, r: detect.Report) -> DocumentId | None:
    """The paper that carried ``r`` to the seat, if it has arrived: the named person's page
    for the report's source and day (``detect.pages``)."""
    doc_id = DocumentId(
        derived_id(
            view.campaign_id, "report-page", nation, r.source.value, r.seen.isoformat(), view.viewer
        )
    )
    return doc_id if doc_id in view.documents else None


def _author(view: View, paper: DocumentId | None) -> str:
    doc = view.documents.get(paper) if paper is not None else None
    person = view.entities.get(doc.author) if doc is not None else None
    return person.name if person is not None else ""


RING_AFTER_DAYS = 1
"""[proposed] A report older than this many days carries a ring, so a fresh contact stays
a point (RNG)."""


def _ring(
    view: View, r: detect.Report, shapes: list[territory.Territory | territory.SeaZone]
) -> list[str] | None:
    """Every area a piece of the report's kind could have reached from the reported area
    since the day seen, the area included, in the board's order; an unknown kind moves as
    every kind of the area's domain, so the fastest bounds it (sea kinds in a sea zone,
    else land kinds).
    Read from the report and the board alone. None while fresh, and for a decrypt."""
    board, today = view.map, view.in_world_date
    if board is None or today is None or r.area is None:
        return None
    days = (today - r.seen).days
    if days <= RING_AFTER_DAYS:
        return None
    pieces = view.kinds.pieces if view.kinds is not None else {}
    known = pieces.get(r.kind) if r.kind is not None else None
    if known is not None:
        movers = [known]
    else:
        sea = any(z.area == r.area for z in board.sea_zones)
        domain = kinds.Domain.SEA if sea else kinds.Domain.LAND
        movers = [k for k in pieces.values() if k.domain is domain]
    reach = {r.area}
    for k in movers:
        reach |= set(territory.steps_within(board, k, r.area, days))
    return [a.key for a in shapes if a.area in reach]


def map_reports(view: View) -> list[MapReport]:
    """Each report of an enemy piece that has reached the seat's nation, by its core key
    (``protect_marks`` keys it again before it leaves). A report a named person made is
    sent only with its paper; a contact no one is named for comes with none. Read from
    the view alone: a wrong report is sent as a right one."""
    nation = map_api.viewing_nation(view)
    board = view.map
    shapes: list[territory.Territory | territory.SeaZone] = (
        [*board.territories, *board.sea_zones] if board is not None else []
    )
    areas = {a.area: MarkArea(key=a.key, name=a.name) for a in shapes}
    pieces = view.kinds.pieces if view.kinds is not None else {}
    out: list[MapReport] = []
    for key, r in sorted(view.reports.items()):
        paper = _paper(view, nation, r) if r.rank > 0 else None
        if r.rank > 0 and paper is None:
            continue
        kind = pieces.get(r.kind) if r.kind is not None else None
        out.append(
            MapReport(
                key=key,
                kind=r.kind,
                kind_name=kind.name if kind is not None else "unknown",
                strength_low=r.strength[0] if r.strength is not None else None,
                strength_high=r.strength[1] if r.strength is not None else None,
                area=areas.get(r.area) if r.area is not None else None,
                bound_for=r.region if r.area is None else None,
                seen=r.seen.isoformat(),
                source=r.source.value,
                person=_author(view, paper),
                confidence=r.confidence.value,
                document=paper,
                ring=_ring(view, r, shapes),
            )
        )
    return out


def seat_map(
    view: View,
    forces: Mapping[str, str] | None = None,
    pipelines: Mapping[PipelineId, Pipeline] | None = None,
    people: People | None = None,
    state: State | None = None,
    place_keys: Mapping[EntityId, str] | None = None,
    withdrawable: Collection[str] = (),
) -> SeatMap | None:
    """Every placed feature as the latest arrived page has it, the seat's own movement
    orders and the capitals of the leaders ``people`` (the roster) weighs against it;
    None for a world with no positions (the client hides the map). ``forces`` names the
    mark for each force key an order can name (the caller's, as ``pipelines`` is).
    With ``state``, each own force ``forces`` names is sent as a piece on its mark, and
    marks and pieces share the web MAC of ``territory.mark_key``; ``withdrawable`` (``withdraw``)
    marks the orders the seat may still take back. In a game with ``reports`` on, the
    enemy pieces the seat's nation holds reports of are ``reports`` (``map_reports``), and
    no mark of another side's piece is sent."""
    places = _positioned(
        view,
        (
            k
            for k, e in sorted(view.entities.items(), key=lambda kv: (kv[1].name, kv[0]))
            if e.kind is EntityKind.LOCATION
        ),
    )
    if not places:
        return None
    today = view.in_world_date
    own = own_sides(view)
    latest = latest_sightings(view)
    sent = (
        _Sent(state, view, forces or {}, pipelines or {}, place_keys or {}, withdrawable)
        if state is not None
        else None
    )
    areas = _mark_areas(state)
    marks: list[MapMark] = []
    for (label, kind), (doc_id, doc, b) in sorted(latest.items(), key=lambda kv: kv[0]):
        sight = b.sight
        assert sight is not None
        side: Literal["own", "other", "none"] = (
            "none" if sight.side is None else "own" if sight.side in own else "other"
        )
        stale = today is not None and (today - doc.issued).days > STALE_DAYS
        marks.append(
            MapMark(
                key=(
                    sent.key(doc_id, label, kind)
                    if sent is not None
                    else _label_key(view.campaign_id, map_api.viewing_nation(view), label, kind)
                ),
                name=label,
                kind=sight.kind.value,
                side=side,
                side_name=view.entities[sight.side].name if sight.side in view.entities else "",
                certainty="stale" if stale else "known" if side == "own" else "reported",
                places=_positioned(view, sight.places),
                area=next(
                    (areas[p] for p in sight.places if p in areas and _place(view, p) is None),
                    None,
                ),
                reported=doc.issued.isoformat(),
                source=view.entities[doc.author].name,
                document=doc_id,
                strength=reported(view, label),
                piece=None,
            )
        )
    reporting = state is not None and detect.on(state)
    if reporting:  # another side's pieces are known only as reports (RPD)
        marks = [m for m in marks if m["side"] != "other"]
    orders = _map_orders(view, marks, forces or {}, pipelines or {})
    for f, piece in sent.pieces() if sent is not None else ():
        mark = next((m for m in marks if m["key"] == piece["key"]), None)
        if mark is not None:
            mark["piece"] = piece
        else:
            marks.append(_own_mark(view, f, piece))
    marks.sort(key=lambda m: (m["name"], m["kind"]))
    capitals = _capitals(view, people) if people is not None else []
    out = SeatMap(places=places, marks=marks, orders=orders, capitals=capitals)
    if reporting:
        out["reports"] = map_reports(view)
    map_api.protect_marks(out, view)
    return map_api.add_board(out, state, view) if state is not None else out


def _step_lines(order: Order, pipeline: Pipeline, view: View) -> list[StepLine]:
    last: dict[int, StepOutcome] = {}
    for taken in order.outcomes:
        last[taken.step] = taken
    indices = set(last)
    if order.status is OrderStatus.MOVING:
        indices.add(order.step)
    lines = []
    for index in sorted(indices):
        step = pipeline.steps[index]
        outcome = last.get(index)
        action = outcome.action if outcome is not None else None
        lines.append(
            StepLine(
                step=index,
                person=view.entities[step.person].name,
                kind=step.kind.value,
                action=action.value if action is not None and action not in _HIDDEN else None,
                on=outcome.on.isoformat() if outcome is not None else None,
            )
        )
    return lines


def _track(view: View, order: Order, pipeline: Pipeline) -> OrderTrack:
    moving = order.status is OrderStatus.MOVING
    holder = pipeline.steps[order.step].person if moving else None
    lever = (
        next((x for x in view.desk.levers if x.name == order.lever), None) if view.desk else None
    )
    specs = {p.name: p for p in lever.params} if lever is not None else {}
    return OrderTrack(
        id=order.order_id,
        lever=order.lever,
        label=lever_label(lever) if lever is not None else words(order.lever),
        terms=[
            _term(specs[k], v, view) if k in specs else f"{words(k)}: {v}"
            for k, v in order.params.items()
        ],
        pipeline=pipeline.name,
        params=dict(order.params),
        status=order.status.value,
        filed=order.filed.isoformat(),
        at_step=order.step,
        with_person=view.entities[holder].name if holder is not None else None,
        since=(order.outcomes[-1].on if order.outcomes else order.filed).isoformat(),
        steps=_step_lines(order, pipeline, view),
        decision_needed=holder is not None and holder == view.me.embodies,
    )


def orders(view: View, pipelines: Mapping[PipelineId, Pipeline]) -> OrderTracker:
    """The viewer's own orders, newest first, each trimmed to what reached the issuer."""
    own = sorted(view.orders.values(), key=lambda o: o.order_id)
    own.sort(key=lambda o: o.filed, reverse=True)
    return OrderTracker(orders=[_track(view, o, pipelines[o.pipeline]) for o in own])


def clock(
    view: View,
    next_wake_at: str | None,
    waiting_on: str | None,
    days_collapsed: int,
    next_world_date: str | None = None,
) -> Clock:
    """Clock and pace. The wake time and next date come from the caller (schedule and calendar)."""
    if view.in_world_date is None:
        raise ValueError("a realism campaign has an in-world date")
    return Clock(
        world_date=view.in_world_date.isoformat(),
        next_wake_at=next_wake_at,
        next_world_date=next_world_date,
        waiting_on=waiting_on,
        days_collapsed=days_collapsed,
    )


def _force_choices(lever: Lever, p: ParamSpec, known: Known) -> list[LeverChoice]:
    """A form's forces: its own choices, each followed on a movement form by that force's
    detachments in play, under the names the state gives them."""
    own = {c["value"]: c for c in _choices(p)}
    return [
        own.get(k) or LeverChoice(value=k, label=known.forces.get(k, words(k)))
        for k in force_keys(lever, p, known)
    ]


def _lever_param(view: View, lever: Lever, p: ParamSpec, known: Known) -> LeverParam:
    places = place_choices(view, lever, p, known) if p is destination(lever) else []
    own = _force_choices(lever, p, known) if p.name == FORCE else _choices(p)
    return LeverParam(
        name=p.name,
        label=_param_label(p),
        kind=p.kind.value,
        lo=p.lo,
        hi=p.hi,
        choices=[LeverChoice(value=x["value"], label=x["label"]) for x in places]
        if places
        else own,
        places=places,
        areas={},
    )


def _place_areas(state: State, out: Desk) -> Desk:
    """``out`` with each movement form's destination ``areas`` filled from the map: for each
    force the form offers, the area each offered place puts it in. Unchanged without
    territories, so a point game's forms read as before."""
    board = state.map
    if not territory.on(state) or board is None:
        return out
    keys = {t.area: t.key for t in board.territories} | {z.area: z.key for z in board.sea_zones}
    for line in out["levers"]:
        force = next((p for p in line["params"] if p["name"] == FORCE), None)
        domains: dict[str, kinds.Domain] = {}
        for c in force["choices"] if force is not None else []:
            f = state.features.get(FeatureId(object_id(state.campaign_id, "feature", c["value"])))
            domain = kinds.domain(state, f) if f is not None else None
            if domain is not None:
                domains[c["value"]] = domain
        for p in line["params"]:
            if p["name"] != "to" or p["kind"] != "enum" or not domains:
                continue
            found = {c["value"]: place_named(state, c["value"]) for c in p["choices"]}
            p["areas"] = {
                force_key: {
                    value: keys[area]
                    for value, place in found.items()
                    if place is not None
                    and (area := territory.area_of(state, place.entity_id, domain)) is not None
                    and area in keys
                }
                for force_key, domain in domains.items()
            }
    return out


def desk(view: View, known: Known | None = None) -> Desk:
    """The viewer's own card, without its AI policy fields (they are not in a view).
    With ``known``, a movement form's destination offers every place on the map."""
    card = view.desk
    if card is None:
        raise ValueError(f"no card for the person {view.me.embodies}")
    return Desk(
        office=card.office,
        powers=list(card.powers),
        levers=[
            LeverLine(
                name=lever.name,
                label=lever_label(lever),
                summary=lever.summary,
                pipeline=lever.pipeline,
                params=[_lever_param(view, lever, p, known or Known()) for p in lever.params],
                rule=lever.resolver,
                intel=_intel_form(lever),
            )
            for lever in card.levers
        ],
        inner_circle=[
            ContactLine(
                person=view.entities[c.person].name,
                title=view.cards[c.person].office if c.person in view.cards else None,
                channel=c.channel.value,
                channels=[x.value for x in channels(c)],
            )
            for c in card.inner_circle
        ],
        principals=[
            view.entities[p].name
            for p in card.principals
            if view.entities[p].kind is not EntityKind.POLITY
        ],
        constraints=list(card.constraints),
        personal=list(card.personal),
        horizon_days=card.horizon_days,
        aims=list(card.aims),
    )


def proposal(view: View, p: Proposal) -> DirectiveProposal:
    """A directive as the aide read it, in the desk's own words."""
    lever = next((x for x in view.desk.levers if x.name == p.lever), None) if view.desk else None
    specs = {s.name: s for s in lever.params} if lever is not None else {}
    return DirectiveProposal(
        to=view.entities[p.person].name,
        channel=p.channel.value,
        text=p.text,
        lever=lever.name if lever is not None else None,
        label=lever_label(lever) if lever is not None else None,
        terms=[_term(specs[k], v) for k, v in p.params.items() if k in specs],
        params=dict(p.params) if lever is not None else {},
        reason=p.reason or None,
    )


def aide_brief(view: View, brief: AideBrief) -> dict[str, Any]:
    """The aide's brief in the desk's words: the summary, how many decisions wait,
    and each draft as its form's label and terms. Drafts are never filed here."""
    levers = {x.name: x for x in view.desk.levers} if view.desk is not None else {}
    drafts = []
    for d in brief.drafts:
        lever = levers.get(d.lever)
        if lever is None:
            continue
        specs = {s.name: s for s in lever.params}
        drafts.append(
            {
                "lever": lever.name,
                "label": lever_label(lever),
                "terms": [_term(specs[k], v) for k, v in d.params.items() if k in specs],
                "params": dict(d.params),
            }
        )
    summary = _ISO_DATE.sub(lambda m: _spoken_day(date.fromisoformat(m.group(0))), brief.summary)
    return {"summary": summary, "decisions": len(brief.decisions), "drafts": drafts}


_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _spoken_day(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def counsel_lines(view: View, events: Iterable[Event], seat: SeatId) -> list[CounselLine]:
    """The seat's own consultations, newest first: who, how, the question, the answer, the
    in-world day each was held (the last ``date_advanced`` before it) and the tie."""
    card = view.cards.get(view.me.embodies)
    inner = {c.person for c in card.inner_circle} if card is not None else set()
    out: list[CounselLine] = []
    day: date | None = None
    for e in events:
        p = e.payload
        if isinstance(p, ev.DateAdvanced):
            day = p.to
        if not isinstance(p, ev.CounselHeld) or p.seat_id != seat:
            continue
        asked, _, answer = p.text.partition("\n\n")
        question = asked.removeprefix("You asked: ") if asked.startswith("You asked: ") else ""
        out.append(
            {
                "person": view.entities[p.person].name if p.person in view.entities else "",
                "channel": p.channel.value,
                "question": question,
                "answer": answer if question else p.text,
                "day": _spoken_day(day) if day is not None else "",
                "day_iso": day.isoformat() if day is not None else "",
                "tie": "inner" if p.person in inner else "outer",
            }
        )
    return out[::-1]


def read_ids(events: Iterable[Event], seat: SeatId) -> set[DocumentId]:
    return {
        e.payload.doc_id
        for e in events
        if isinstance(e.payload, ev.DocumentRead) and e.payload.seat_id == seat
    }


def flagged_ids(events: Iterable[Event], seat: SeatId) -> set[DocumentId]:
    """The documents ``seat`` has flagged: its latest ``document_flagged`` for each wins."""
    standing: dict[DocumentId, bool] = {}
    for e in events:
        if isinstance(e.payload, ev.DocumentFlagged) and e.payload.seat_id == seat:
            standing[e.payload.doc_id] = e.payload.flagged
    return {k for k, v in standing.items() if v}


def _detachments(state: State, key: str) -> list[tuple[str, str]]:
    """The key and name of each detachment in play of the force ``key``, by slot."""
    parent = FeatureId(object_id(state.campaign_id, "feature", key))
    out: list[tuple[str, str]] = []
    for n in range(1, len(state.features) + 1):
        slot = f"{key}__d{n}"
        f = state.features.get(FeatureId(object_id(state.campaign_id, "feature", slot)))
        if f is not None and f.detached_from == parent and in_play(f):
            out.append((slot, f.name))
    return out


def _force_names(state: State, view: View) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Each force key the seat's movement levers offer, with its detachments in play, and
    that force's name; then the keys of each offered force's detachments."""
    names: dict[str, str] = {}
    held: dict[str, tuple[str, ...]] = {}
    for x in view.desk.levers if view.desk is not None else ():
        if x.resolver != "movement":
            continue
        for p in x.params:
            if p.name != FORCE:
                continue
            for key in p.choices:
                f = state.features.get(FeatureId(object_id(state.campaign_id, "feature", key)))
                if f is not None:
                    names[key] = f.name
                    found = _detachments(state, key)
                    held[key] = tuple(k for k, _ in found)
                    names.update(found)
    return names, held


def world_news(view: View) -> list[WorldDevelopment]:
    """The public developments that have fired, newest first: "The world" tab."""
    return [
        WorldDevelopment(
            id=s.scheduled_id,
            on=day.isoformat(),
            category=s.category.value.replace("_", " ").capitalize() if s.category else "",
            headline=s.headline or s.name,
            asks=list(s.asks),
        )
        for day, s in history.fired_developments(view)
    ]


def public_wars(view: View) -> list[PublicWar]:
    """Every war as the public record has it, oldest first: the same for every seat."""

    def side(polity: EntityId) -> WarNation:
        e = view.entities.get(polity)
        return WarNation(key=polity, name=e.name if e is not None else "")

    return [
        PublicWar(a=side(w.a), b=side(w.b), since=w.since.isoformat())
        for w in sorted(view.wars.values(), key=lambda w: (w.since, w.war_id))
    ]


@lru_cache(maxsize=16)
def _nation_keys(world: str) -> tuple[str, ...]:
    decl = cmp.load_world(cmp.world_path(world))
    return tuple(e.key for e in decl.entities if e.kind is EntityKind.POLITY)


def nation_keys(state: State, world: str | None) -> dict[str, str]:
    """Each nation's key in the world file ``world``, by the game's id for it; ``{}``
    with no world or when its file is gone or no longer loads."""
    if world is None:
        return {}
    try:
        keys = _nation_keys(world)
    except (OSError, ValueError):
        return {}
    return {object_id(state.campaign_id, "entity", k): k for k in keys}


def seat_realism(
    state: State,
    seat: SeatId,
    read: set[DocumentId],
    flagged: set[DocumentId],
    next_wake_at: str | None,
    place_keys: Mapping[EntityId, str] | None = None,
    withdrawable: Collection[str] = (),
    held_battles: Collection[str] = (),
    ended_battles: Sequence["Ended"] = (),
    events: Iterable[Event] = (),
) -> dict[str, Any]:
    """The ``view.realism`` block of ``/api/me``: tray, desk, situation, orders, clock, map,
    threats, people, the world's developments, the world's key and its nations' keys, the
    public wars, the war economy, the seat's battles, its groups at home, its agreements,
    its conferences, and its own aim's ladder while it may set one. ``place_keys``
    (``destinations.place_keys``) opens movement forms to every place; ``withdrawable``
    (``withdraw.withdrawable``) are the orders the seat may take back; ``held_battles``
    the area keys of battles it has a decision held for the next wake; ``ended_battles``
    (``odds.ended``) the battles it fought that have ended;
    ``events`` the game's log, for what last moved each of its groups and the day each
    clause of its agreements was judged."""
    view = project(state, seat)
    log = list(events)
    forces, held = _force_names(state, view)
    card = state.cards.get(view.me.embodies)
    needs, pools = lift_facts(state, forces)
    known = Known(
        keys=place_keys or {},
        forces=forces,
        detachments=held,
        allies=frozenset(card.allies if card is not None else ()),
        needs=needs,
        pools=pools,
    )
    today = view.in_world_date
    if today is None:
        raise ValueError("a realism campaign has an in-world date")
    wake = next_wake(state, today)
    # the horizon is not a thing anyone is waiting on: the client says nothing is due
    waiting_on = None if wake.reason.what == "horizon" else wake.reason.label
    portraits = {
        person: d["portrait"]
        for person, d in dossiers.for_people(state, log).items()
        if d["portrait"]
    }
    people = seat_people(state, seat, view, portraits)
    world = dossiers.world_key(log)
    shown = seat_map(view, forces, state.pipelines, people, state, place_keys or {}, withdrawable)
    out = {
        "documents": documents(view, read, flagged),
        "desk": _place_areas(state, desk(view, known)),
        "situation": situation(view),
        "orders": orders(view, state.pipelines),
        "clock": clock(view, next_wake_at, waiting_on, 0, wake.to.isoformat()),
        "map": shown,
        "threats": seat_threats(state, seat, view),
        "people": people,
        "world": world_news(view),
        "world_key": world,
        "nation_keys": nation_keys(state, world),
        "wars": public_wars(view),
        "economy": economy_api.block(state, view),
        "battles": battles_api.block(state, seat, view, forces, held_battles, ended_battles),
        "home": home_api.block(state, view, log, shown.get("areas", ()) if shown else ()),
        "agreements": agreements_api.block(state, seat, view, log),
        "conferences": conferences_api.block(state, seat, view),
        **_locks(state, seat),
        **_posts(state, seat),
        **_own_aim(state, seat),
    }
    out["capitals"] = home_api.capitals(state, view, out, log)
    return out


def _posts(state: State, seat: SeatId) -> dict[str, Any]:
    """The seat's ``posts`` block (PPR); no key at all with ``posts`` off, so a game
    without the rule is sent what it was before."""
    found = posts_block(state, seat)
    return {} if found is None else {"posts": found}


def _locks(state: State, seat: SeatId) -> dict[str, Any]:
    """The seat's ``locks`` block (LKD); no key at all with ``locks`` off, so a game
    without the rule is sent what it was before."""
    found = locks_api.block(state, seat)
    return {} if found is None else {"locks": found}


def _own_aim(state: State, seat: SeatId) -> dict[str, Any]:
    """The seat's ``own_aim`` block (OWR), while it may still set one; no key at all
    otherwise, so a game without own aims is sent what it was before."""
    found = stakes.own_aim_block(state, seat)
    return {} if found is None else {"own_aim": found}


__all__ = [
    "aide_brief",
    "clock",
    "counsel_lines",
    "desk",
    "document",
    "documents",
    "flagged_ids",
    "lever_label",
    "nation_keys",
    "orders",
    "proposal",
    "public_wars",
    "read_ids",
    "seat_map",
    "seat_realism",
    "situation",
    "words",
    "world_news",
]
