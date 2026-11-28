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
estimator's effects; its own play style; and only its own mandates. Of the shared
wake it sees only whether it has committed itself.

In a realism game in play no seat learns which other leaders a person plays: of the
other player seats it sees no face and no claim on the roster, so a leader a person
plays reads the same as one the code runs.

Detection adds one: a seat sees enemy pieces only as the reports that have reached its
nation (``View.reports``); a pending report, and the piece a report is about, never. Every
other nation's envoy is public, an exact report of today (ENV).

A commander held to his post (PVW, ``post_view`` on, a military card) sees what the post
would: none of his nation's groups, their support or spent points; of its pools
the fuel stock only, published agreements only, no offers to its blocs, public
quantities only, and of his aims neither whether one holds nor when it was met where a
leaf on his own nation's facts could decide it.

A development is the engine's until it fires: its window, chance, condition, effects
and asks are not in a view before then, and a skipped one never is.
"""

from collections.abc import Mapping
from typing import Protocol

from revisionist.core.aim_patterns import OwnAim
from revisionist.core.goals import Goal, aim_rule, hidden_at_post, sees_goal
from revisionist.core.goals import at_post as goal_at_post
from revisionist.core.ids import (
    AssetId,
    DocumentId,
    EntityId,
    GoalId,
    QuantityId,
    ScheduledEventId,
    SeatId,
)
from revisionist.core.ontology import (
    Asset,
    Character,
    Controller,
    Phase,
    ScheduledEvent,
    ScheduleSource,
    Seat,
    SeatKind,
)
from revisionist.core.realism import (
    agreement,
    answering,
    conference,
    defiance,
    detect,
    economy,
    groups,
    offers,
)
from revisionist.core.realism.card import CardFace, CardPath, SeatCard
from revisionist.core.realism.document import DocumentView
from revisionist.core.realism.quantity import Quantity
from revisionist.core.state import Rule, SeatFace, State, View, Wake, seat_of_person
from revisionist.core.visibility import Scope, Visibility


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


def _own_aims(state: State, seat: SeatId) -> dict[EntityId, OwnAim]:
    """The own aim of the person a player holds through ``seat``, if set (OWC)."""
    return {
        person: own
        for person, own in state.own_aims.items()
        if (held := seat_of_person(state, person)) is not None
        and held.seat_id == seat
        and held.controller is Controller.HUMAN
    }


def _face(card: SeatCard, assets: Mapping[AssetId, Asset]) -> CardFace:
    """The card's public face; its post named only where the seat sees the office (PPP)."""
    face = card.face()
    if face.post is not None and face.post not in assets:
        return face.model_copy(update={"post": None})
    return face


def at_post(state: State, seat: SeatId) -> bool:
    """Whether ``seat`` sees only what its post would (PVW): ``post_view`` on and the
    person it holds on a military card."""
    if Rule.POST_VIEW not in state.rules or seat not in state.seats:
        return False
    card = state.cards.get(state.seats[seat].embodies)
    return card is not None and card.path is CardPath.MILITARY


def _goals(state: State, seat: SeatId, post: bool) -> dict[GoalId, Goal]:
    """The goals ``seat`` sees; held to his post, each as ``goals.at_post`` leaves it."""
    seen = {k: g for k, g in state.goals.items() if sees_goal(state, g, seat)}
    if not post:
        return seen
    return {k: goal_at_post(g, aim_rule(state, g)) for k, g in seen.items()}


def untold_goals(state: State, seat: SeatId) -> frozenset[GoalId]:
    """The goals in ``seat``'s view whose met, undone and progress it is not told: held to
    his post, each ``goals.at_post`` blanks. The feed and the playback both read this."""
    if not at_post(state, seat):
        return frozenset()
    return frozenset(
        k
        for k, g in state.goals.items()
        if sees_goal(state, g, seat) and hidden_at_post(g, aim_rule(state, g))
    )


def _quantities(state: State, seat: SeatId, post: bool) -> dict[QuantityId, Quantity]:
    """The quantities ``seat`` sees; held to his post, the public ones only."""
    return {
        k: q
        for k, q in state.quantities.items()
        if q.scope is not None
        and q.scope.visible_to(seat)
        and (not post or q.scope.visibility is Visibility.PUBLIC)
    }


def _wake(state: State, seat: SeatId) -> Wake | None:
    """The shared wake with only ``seat``'s own commit in it."""
    wake = state.wake
    if wake is None:
        return None
    return wake.model_copy(update={"committed": wake.committed & {seat}})


def _unplayed(state: State) -> bool:
    """A realism game in play: the seats people hold are not shown to one another."""
    return state.ruleset == "realism" and state.phase is Phase.PLAY


def _roster(state: State, seat: SeatId) -> dict[EntityId, Character]:
    """The roster, with no claim but ``seat``'s own once play has begun."""
    if not _unplayed(state):
        return dict(state.roster)
    return {
        k: c if c.claimed_by in (None, seat) else c.model_copy(update={"claimed_by": None})
        for k, c in state.roster.items()
    }


def _faces(state: State, seat: SeatId) -> dict[SeatId, SeatFace]:
    """Every seat's face; once play has begun, of the player seats only ``seat``'s own."""
    hide = _unplayed(state)
    return {
        k: face(v)
        for k, v in state.seats.items()
        if not hide or k == seat or v.kind is not SeatKind.PLAYER
    }


def project(state: State, seat: SeatId) -> View:
    if seat not in state.seats:
        raise KeyError(f"unknown seat {seat!r}")
    me = state.seats[seat]
    card = state.cards.get(me.embodies)
    assets = _visible(state.assets, seat)
    post = at_post(state, seat)
    return View(
        viewer=seat,
        campaign_id=state.campaign_id,
        tick=state.tick,
        settings=state.settings,
        entities=dict(state.entities),
        assets=assets,
        relationships=_visible(state.relationships, seat),
        meters=_visible(state.meters, seat),
        clocks=_visible(state.clocks, seat),
        facts=_visible(state.facts, seat),
        scheduled=_scheduled(state.scheduled, seat),
        commitments=_visible(state.commitments, seat),
        goals=_goals(state, seat, post),
        mandates=_visible(state.mandates, seat),
        wars=dict(state.wars),
        ended_wars=state.ended_wars,
        map=state.map,
        kinds=state.kinds,
        locks=state.locks,
        laws=state.laws,
        aim_patterns=state.aim_patterns,
        own_aims=_own_aims(state, seat),
        holders=dict(state.holders),
        economy=economy.seen_by(state, seat, post=post),
        groups=groups.seen_by(state, seat, post=post),
        offers=() if post else offers.seen_by(state, seat),
        agreements=agreement.seen_by(state, seat, post=post),
        conferences=conference.seen_by(state, seat),
        wake=_wake(state, seat),
        phase=state.phase,
        roster=_roster(state, seat),
        contests=_visible(state.contests, seat),
        divergence=state.divergence,
        in_world_date=state.in_world_date,
        ruleset=state.ruleset,
        me=me,
        seats=_faces(state, seat),
        own_pending=tuple(i for i in state.pending.values() if i.actor == seat),
        cards={k: _face(c, assets) for k, c in state.cards.items()},
        desk=card.desk() if card is not None else None,
        documents=_arrived(state, seat),
        # The holder's kept choice at a step is engine side until its due day (SHS).
        orders={
            k: o.model_copy(update={"held_choice": None})
            for k, o in state.orders.items()
            if o.issuer == seat
        },
        quantities=_quantities(state, seat, post),
        routed={k: o.view() for k, o in state.routed.items() if o.issuer == seat},
        held={k: h for k, h in state.held.items() if h.issuer == seat},
        asked={
            k: answering.as_asked(state, a, seat)
            for k, a in state.asked.items()
            if seat in (a.asker, a.seat, *a.seats)
        },
        incidents=defiance.as_seen(state.incidents, seat),
        style=state.styles.get(seat),
        reports={
            **detect.seen_by(state, seat, post=post),
            **detect.envoys(state, seat),
        },
    )
