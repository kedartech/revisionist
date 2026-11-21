"""``project(state, seat) -> View``: the only read path for anything that writes prose.

spec §7. An item is in a seat's view when its scope is visible to that
seat. Entities have no scope and are always visible. Every seat appears only
as a ``SeatFace`` (spec §17: how a seat is run is never shown); the viewer
also gets its own seat in full as ``View.me``. Other seats' pending intents
are never in a view.

Realism adds three rules. A document is in view once its scope admits the seat
*and* it has arrived (``arrives <= in_world_date``); only its ``DocumentView``
half is copied. A seat sees its own orders only. Cards show as faces, with the
viewer's own person as a desk; AI policy fields never leave the state.

Engine v2 adds three more. A seat sees its own routed orders, never the
estimator's effects; its own play style; and only its own mandates. The shared
wake is public: who has committed, never what.

Detection adds one: a seat sees enemy pieces only as the reports that have reached its
nation (``View.reports``); a pending report, and the piece a report is about, never. Every
other nation's envoy is public, an exact report of today (ENV).

A development is the engine's until it fires: its window, chance, condition, effects
and asks are not in a view before then, and a skipped one never is.
"""

from collections.abc import Mapping
from typing import Protocol

from revisionist.core.goals import sees_goal
from revisionist.core.ids import DocumentId, ScheduledEventId, SeatId
from revisionist.core.ontology import ScheduledEvent, ScheduleSource, Seat
from revisionist.core.realism import agreement, conference, detect, economy, groups
from revisionist.core.realism.document import DocumentView
from revisionist.core.realism.war import polity_of
from revisionist.core.state import SeatFace, State, View
from revisionist.core.visibility import Scope


class HasScope(Protocol):
    @property
    def scope(self) -> Scope: ...


def _visible[K, S: HasScope](items: Mapping[K, S], seat: SeatId) -> dict[K, S]:
    return {k: v for k, v in items.items() if v.scope.visible_to(seat)}


def _scheduled(
    items: Mapping[ScheduledEventId, ScheduledEvent], seat: SeatId
) -> dict[ScheduledEventId, ScheduledEvent]:
    return {
        k: v
        for k, v in _visible(items, seat).items()
        if v.source is not ScheduleSource.DEVELOPMENT or v.fired
    }


def face(seat: Seat) -> SeatFace:
    return SeatFace(seat_id=seat.seat_id, kind=seat.kind, name=seat.name, embodies=seat.embodies)


def _arrived(state: State, seat: SeatId) -> dict[DocumentId, DocumentView]:
    today = state.in_world_date
    if today is None:
        return {}
    return {
        k: d.view
        for k, d in state.documents.items()
        if d.view.scope.visible_to(seat) and d.view.arrives <= today
    }


def project(state: State, seat: SeatId) -> View:
    if seat not in state.seats:
        raise KeyError(f"unknown seat {seat!r}")
    me = state.seats[seat]
    card = state.cards.get(me.embodies)
    return View(
        viewer=seat,
        campaign_id=state.campaign_id,
        tick=state.tick,
        settings=state.settings,
        entities=dict(state.entities),
        assets=_visible(state.assets, seat),
        relationships=_visible(state.relationships, seat),
        meters=_visible(state.meters, seat),
        clocks=_visible(state.clocks, seat),
        facts=_visible(state.facts, seat),
        scheduled=_scheduled(state.scheduled, seat),
        commitments=_visible(state.commitments, seat),
        goals={k: g for k, g in state.goals.items() if sees_goal(state, g, seat)},
        mandates=_visible(state.mandates, seat),
        wars=dict(state.wars),
        map=state.map,
        kinds=state.kinds,
        locks=state.locks,
        holders=dict(state.holders),
        economy=economy.seen_by(state, seat),
        groups=groups.seen_by(state, seat),
        agreements=agreement.seen_by(state, seat),
        conferences=conference.seen_by(state, seat),
        wake=state.wake,
        phase=state.phase,
        roster=dict(state.roster),
        contests=_visible(state.contests, seat),
        divergence=state.divergence,
        in_world_date=state.in_world_date,
        ruleset=state.ruleset,
        me=me,
        seats={k: face(v) for k, v in state.seats.items()},
        own_pending=tuple(i for i in state.pending.values() if i.actor == seat),
        cards={k: c.face() for k, c in state.cards.items()},
        desk=card.desk() if card is not None else None,
        documents=_arrived(state, seat),
        # The holder's kept choice at a step is engine side until its due day (SHS).
        orders={
            k: o.model_copy(update={"held_choice": None})
            for k, o in state.orders.items()
            if o.issuer == seat
        },
        quantities={
            k: q
            for k, q in state.quantities.items()
            if q.scope is not None and q.scope.visible_to(seat)
        },
        routed={k: o.view() for k, o in state.routed.items() if o.issuer == seat},
        held={k: h for k, h in state.held.items() if h.issuer == seat},
        asked={k: a for k, a in state.asked.items() if seat in (a.asker, a.seat)},
        style=state.styles.get(seat),
        reports={
            **detect.seen_by(state, polity_of(state, me.embodies)),
            **detect.envoys(state, polity_of(state, me.embodies)),
        },
    )
