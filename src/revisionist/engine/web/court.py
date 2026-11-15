"""The court of ``view.realism``: the seat's own people on the paths its forms use
(plan item "the court's data"; board design §3).

Read from the seat's ``View``, with one exception taken as the order tracker takes
it: the pipelines, which ``View`` does not carry. Paths are the pipelines the seat's
forms use, in the card's order, then any other pipeline one of the seat's own orders
runs, so an order always has a step to wait at. Each step names its person and
office, its kind and its typical days, and lists the seat's own orders waiting
there. The day an order reached a step is the day it moved there, never the day of
a stall: the issuer does not see a stall (``realism_snapshot._HIDDEN``), and a later
day would give it away. Another seat's orders are not in the view and never counted.

The ring is the seat's inner circle, then its chain by name, who stand on no path,
each with the channel the seat reaches them by first. Chambers are the bodies of the
seat's own country that own seat figures in its view, with the yeas that carry a
vote (the votes rule passes a measure on more yeas than nays) and their public votes.
"""

import re
from datetime import date

from revisionist.core.ids import EntityId, PipelineId, SeatId
from revisionist.core.ontology import EntityKind, EntityStatus
from revisionist.core.project import project
from revisionist.core.realism.card import Tie, words
from revisionist.core.realism.pipeline import Order, OrderStatus, Pipeline, StepKind
from revisionist.core.realism.pipelines import FREE_ORDERS
from revisionist.core.realism.quantity import Quantity
from revisionist.core.realism.reach import channels_to, tie
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State, View
from revisionist.engine.web.realism_api import (
    Chamber,
    ChamberSeats,
    ChamberVote,
    Court,
    CourtOrder,
    CourtPath,
    CourtRing,
    CourtStep,
)
from revisionist.engine.web.realism_snapshot import lever_label

SEATS = "seats"
VOTES = "votes"
_YEAS = re.compile(r"\byeas\b")


def _name(view: View, person: EntityId) -> str:
    found = view.entities.get(person)
    return str(found.name) if found is not None else "someone unknown"


def _office(view: View, person: EntityId) -> str | None:
    face = view.cards.get(person)
    return str(face.office) if face is not None else None


def _arrived(order: Order) -> date:
    """The day the order reached the step it is at: the outcome that moved it there,
    or the filing date at the first step."""
    moved = [o.on for o in order.outcomes if o.step < order.step]
    return moved[-1] if moved else order.filed


def _path_ids(view: View, pipelines: dict[PipelineId, Pipeline]) -> list[PipelineId]:
    used = {lever.pipeline for lever in view.desk.levers} if view.desk is not None else set()
    listed = list(view.desk.pipelines) if view.desk is not None else []
    ids = [p for p in listed if p in used]
    ids += sorted(used - set(ids))
    for order in sorted(view.orders.values(), key=lambda o: (o.filed, o.order_id)):
        if order.pipeline not in ids:
            ids.append(order.pipeline)
    return [p for p in ids if p in pipelines]


def _waiting(
    view: View, pipelines: dict[PipelineId, Pipeline], today: date | None
) -> dict[tuple[PipelineId, int], list[CourtOrder]]:
    """The seat's moving orders by (pipeline, step index). One through its last step
    is keyed past every step, so no step lists it."""
    out: dict[tuple[PipelineId, int], list[CourtOrder]] = {}
    if today is None:
        return out
    levers = {x.name: x for x in view.desk.levers} if view.desk is not None else {}
    held = [
        o
        for o in view.orders.values()
        if o.status is OrderStatus.MOVING and o.pipeline in pipelines
    ]
    for order in sorted(held, key=lambda o: (_arrived(o), o.order_id)):
        since = _arrived(order)
        lever = levers.get(order.lever)
        out.setdefault((order.pipeline, order.step), []).append(
            CourtOrder(
                id=order.order_id,
                label=lever_label(lever) if lever is not None else words(order.lever),
                since=since.isoformat(),
                held_days=max(0, (today - since).days),
            )
        )
    return out


def _path(
    view: View, pl: Pipeline, waiting: dict[tuple[PipelineId, int], list[CourtOrder]]
) -> CourtPath:
    me = view.me.embodies
    forms = view.desk.levers if view.desk is not None else ()
    return CourtPath(
        id=pl.pipeline_id,
        name=pl.name,
        forms=[lever_label(x) for x in forms if x.pipeline == pl.pipeline_id],
        steps=[
            CourtStep(
                person=s.person,
                name=_name(view, s.person),
                office=_office(view, s.person),
                kind="clerical" if s.kind is StepKind.CLERICAL else "decision",
                days=s.days,
                you=s.person == me,
                orders=waiting.get((pl.pipeline_id, i), []),
            )
            for i, s in enumerate(pl.steps)
        ],
    )


def _alive(view: View, person: EntityId) -> bool:
    entity = view.entities.get(person)
    return (
        entity is not None
        and entity.kind is EntityKind.PERSON
        and entity.status is not EntityStatus.DEAD
    )


def _ring(state: State, view: View, on_a_path: set[str]) -> list[CourtRing]:
    me = view.me.embodies
    circle = [c.person for c in view.desk.inner_circle] if view.desk is not None else []
    chain = sorted(
        (p for p in view.cards if p not in circle and p != me and tie(state, me, p) is Tie.CHAIN),
        key=lambda p: _name(view, p),
    )
    out: list[CourtRing] = []
    for person in [*circle, *chain]:
        if person in on_a_path or person == me or not _alive(view, person):
            continue
        reach = channels_to(state, me, person)
        out.append(
            CourtRing(
                person=person,
                name=_name(view, person),
                office=_office(view, person),
                channel=reach[0].value if reach else "",
            )
        )
    return out


def _party(body: str, name: str) -> str:
    first, _, rest = name.partition(" ")
    party = rest if rest and first == body.split(" ")[0] else name
    return party[:1].upper() + party[1:]


def _votes(figures: list[Quantity]) -> list[ChamberVote]:
    nays = {(q.name, q.as_of): q for q in figures if q.value is not None}
    out: list[ChamberVote] = []
    for q in figures:
        if q.value is None or not _YEAS.search(q.name):
            continue
        twin = nays.get((_YEAS.sub("nays", q.name), q.as_of))
        if twin is None or twin.value is None:
            continue
        out.append(
            ChamberVote(
                name=_YEAS.sub("vote", q.name),
                yeas=q.value,
                nays=twin.value,
                as_of=q.as_of.isoformat(),
            )
        )
    out.sort(key=lambda v: (v["as_of"], v["name"]), reverse=True)
    return out


def _chambers(state: State, view: View) -> list[Chamber]:
    mine = polity_of(state, view.me.embodies)
    owned: dict[EntityId, list[Quantity]] = {}
    for q in view.quantities.values():
        if q.owner is not None:
            owned.setdefault(q.owner, []).append(q)
    out: list[Chamber] = []
    for body, figures in owned.items():
        seats = [q for q in figures if q.unit == SEATS and q.value is not None]
        if not seats or mine is None or polity_of(state, body) != mine:
            continue
        name = _name(view, body)
        out.append(
            Chamber(
                name=name,
                seats=sorted(
                    (ChamberSeats(party=_party(name, q.name), seats=q.value or 0) for q in seats),
                    key=lambda s: (-s["seats"], s["party"]),
                ),
                carries=sum(q.value or 0 for q in seats) // 2 + 1,
                votes=_votes([q for q in figures if q.unit == VOTES]),
            )
        )
    out.sort(key=lambda c: c["name"])
    return out


def seat_court(state: State, seat: SeatId) -> Court:
    """The seat's court: its paths with its orders on them, its ring and its chambers."""
    view = project(state, seat)
    pipelines = dict(state.pipelines)
    waiting = _waiting(view, pipelines, view.in_world_date)
    paths = [_path(view, pipelines[p], waiting) for p in _path_ids(view, pipelines)]
    on_a_path = {s["person"] for p in paths for s in p["steps"]}
    return Court(
        paths=paths,
        ring=_ring(state, view, on_a_path),
        chambers=_chambers(state, view),
        load_limit=FREE_ORDERS,
    )


__all__ = ["seat_court"]
