"""The fold: events in, state out (spec #19, build plan Layer 2).

``apply`` is total over the mutating kinds and raises ``FoldError`` on
anything it cannot honour: a sequence gap, an unknown ID, a hash mismatch at
``tick_closed``. The log is never silently skipped, because a skipped event
is a state nobody can reproduce.

Bounds applied here are the *type* bounds of the ontology (tier 0-5, meter
lo-hi, disposition -5..+5). The clamp table (Layer 3) is policy and runs
before a delta is ever logged as applied; the fold only guarantees that a
replay can never produce an invalid object.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import date, timedelta

from pydantic import JsonValue, ValidationError

from revisionist.core import delta as d
from revisionist.core import events as ev
from revisionist.core.aim_patterns import AimPattern, OwnAim
from revisionist.core.events import MUTATING_KINDS, Event
from revisionist.core.goals import (
    Goal,
    GoalKind,
    GoalSource,
    aim_goal_id,
    aim_rule,
    aims_on,
    goal_kind,
    replacement_aims,
    season_winners,
)
from revisionist.core.ids import AssetId, CampaignId, EntityId, FeatureId, SeatId, derived_id
from revisionist.core.ontology import (
    TRACK_MAX,
    Asset,
    AssetKind,
    Clock,
    ClockKind,
    ClockStatus,
    Commitment,
    CommitmentStatus,
    Controller,
    EntityKind,
    EntityStatus,
    Fact,
    Phase,
    ScheduledEvent,
    Seat,
    SeatKind,
    SeatStatus,
)
from revisionist.core.realism import (
    agreement,
    conference,
    detect,
    economy,
    elections,
    groups,
    kinds,
    locks,
    offers,
    office,
    posts,
    trade,
)
from revisionist.core.realism.agenda import MANDATE_CAP, MandateStatus, PlayStyle, opening_id
from revisionist.core.realism.answer import AnswerLog
from revisionist.core.realism.battle import Battle
from revisionist.core.realism.card import Domain, Post, PostPart, SeatCard, post_part, with_part
from revisionist.core.realism.document import Document
from revisionist.core.realism.effect import (
    IRREVERSIBLE,
    Allocate,
    Appointment,
    Deal,
    Disclosure,
    EffectKind,
    EstimatedEffect,
    Investigate,
    MakeStatement,
    MoveFigure,
    MoveForce,
    ProposeMeasure,
    Route,
    RoutedOrder,
    RoutedPart,
    SetEngagement,
    ShiftDisposition,
)
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.holders import Holding
from revisionist.core.realism.kinds import Kinds
from revisionist.core.realism.locks import PostureNotSet
from revisionist.core.realism.pipeline import (
    ADVANCES,
    SETTLED,
    HeldChoice,
    Order,
    OrderStatus,
    StepAction,
    StepKind,
)
from revisionist.core.realism.territory import holder as territory_holder
from revisionist.core.realism.war import WarEnd, at_war, polity_of
from revisionist.core.state import (
    Ladder,
    QuestionCause,
    Rule,
    State,
    Wake,
    controller_after,
    seat_of_person,
)
from revisionist.core.visibility import PUBLIC, Scope


class FoldError(ValueError):
    """The log cannot be folded. Reproduces on every replay; never caught in play."""


def _put[K, V](items: Mapping[K, V], key: K, value: V) -> dict[K, V]:
    out = dict(items)
    out[key] = value
    return out


def _need[K, V](items: Mapping[K, V], key: K, what: str) -> V:
    try:
        return items[key]
    except KeyError:
        raise FoldError(f"unknown {what} {key!r}") from None


def _fresh[K, V](items: Mapping[K, V], key: K, what: str) -> None:
    if key in items:
        raise FoldError(f"duplicate {what} {key!r}")


def _locks_declared(state: State, p: ev.LocksDeclared) -> State:
    """The world's locks, once, with ``locks`` on; each row's key once, and every person,
    nation, area and force it names already in the world (DCD)."""
    if Rule.LOCKS not in state.rules:
        raise FoldError("locks_declared needs the locks rule")
    if state.locks:
        raise FoldError("the locks are declared once")
    if len({r.key for r in p.rows}) < len(p.rows):
        raise FoldError("locks_declared: a row is named twice")
    for r in p.rows:
        posture = r.when.zone if isinstance(r.when, PostureNotSet) else None
        zone = r.order.zone if r.order is not None else None
        for who in (r.decider.person, r.decider.nation, r.decider.head, zone, posture):
            if who is not None:
                _need(state.entities, who, "entity")
        if r.order is not None and r.order.force is not None:
            _need(state.features, r.order.force, "feature")
    return state.model_copy(update={"locks": p.rows})


def _laws_declared(state: State, p: ev.LawsDeclared) -> State:
    """The world's laws, once, with ``laws`` on; each key once, and the nation each binds
    and the quantity that says it has passed already in the world (LWC)."""
    if Rule.LAWS not in state.rules:
        raise FoldError("laws_declared needs the laws rule")
    if state.laws:
        raise FoldError("the laws are declared once")
    if len({law.key for law in p.laws}) < len(p.laws):
        raise FoldError("laws_declared: a law is named twice")
    for law in p.laws:
        _need(state.entities, law.nation, "entity")
        _need(state.quantities, law.passed, "quantity")
    return state.model_copy(update={"laws": p.laws})


def _aim_patterns_declared(state: State, p: ev.AimPatternsDeclared) -> State:
    """The world's aim patterns, once, with ``own_aim`` on; each key once, and each person a
    kind of post is named for already in the world (OWC)."""
    if Rule.OWN_AIM not in state.rules:
        raise FoldError("aim_patterns_declared needs the own_aim rule")
    if state.aim_patterns is not None:
        raise FoldError("the aim patterns are declared once")
    keys = [x.key for x in p.patterns.patterns]
    if len(set(keys)) < len(keys):
        raise FoldError("aim_patterns_declared: a pattern is named twice")
    for person in p.patterns.posts:
        _need(state.entities, person, "entity")
    return state.model_copy(update={"aim_patterns": p.patterns})


def _own_aim_set(state: State, p: ev.OwnAimSet) -> State:
    """A player's own aim (OWC): own aims part of the game, a player holding the person,
    none set for him yet, his window open, and the aim it replaces his card's replaceable
    one. The goal made from that aim, if made, becomes the player's."""
    from revisionist.core.aim_patterns import on, replaceable

    own = p.own
    if not on(state):
        raise FoldError("own aims are not part of this game")
    seat = seat_of_person(state, own.person)
    if seat is None or seat.controller is not Controller.HUMAN:
        raise FoldError(f"own aim: no player holds {own.person}")
    if own.person in state.own_aims:
        raise FoldError(f"own aim: {own.person} already has an own aim")
    if own.person in state.aim_shut:
        raise FoldError(f"own aim: {own.person}'s window has closed")
    found = replaceable(state, own.person)
    if found is None or found[0] != own.aim:
        raise FoldError(f"own aim: aim {own.aim} is not the replaceable aim of {own.person}")
    assert state.aim_patterns is not None
    pattern = next((x for x in state.aim_patterns.patterns if x.key == own.key), None)
    if pattern is None:
        raise FoldError(f"own aim: no pattern {own.key}")
    if _filled_condition(state, own, pattern) != own.rule.condition:
        raise FoldError(f"own aim: the condition is not pattern {own.key}'s, filled")
    state = state.model_copy(update={"own_aims": _put(state.own_aims, own.person, own)})
    goal_id = aim_goal_id(state.campaign_id, own.person, own.aim)
    made = state.goals.get(goal_id)
    if made is None:
        return state
    goal = made.model_copy(
        update={
            "text": own.text,
            "condition": own.rule.condition,
            "kind": goal_kind(own.rule.condition),
            "source": GoalSource.PLAYER,
            "holding": False,
            "met_tick": None,
        }
    )
    return state.model_copy(update={"goals": _put(state.goals, goal_id, goal)})


def _filled_condition(state: State, own: OwnAim, pattern: AimPattern) -> object:
    """``pattern``'s condition filled with the aim's own values, or None if it makes none."""
    from revisionist.core.aim_patterns import build
    from revisionist.core.realism.war import polity_of

    given: dict[str, JsonValue] = {
        **own.values,
        "nation": polity_of(state, own.person),
        "person": own.person,
    }
    try:
        return build(pattern.condition, given)
    except ValidationError:
        return None


def _aim_shut(state: State) -> State:
    """With own aims on, every person a player holds as a wake closes: his window shuts."""
    from revisionist.core.aim_patterns import on

    if not on(state):
        return state
    played = {s.embodies for s in state.seats.values() if s.controller is Controller.HUMAN}
    if played <= state.aim_shut:
        return state
    return state.model_copy(update={"aim_shut": state.aim_shut | played})


def _order_held(state: State, p: ev.OrderHeld) -> State:
    """A held order, with ``locks`` on: its id new to every order table, its seat and, for
    a form, its pipeline known (LCK)."""
    if Rule.LOCKS not in state.rules:
        raise FoldError("order_held needs the locks rule")
    h = p.held
    for table in (state.held, state.orders, state.routed):
        _fresh(table, h.order_id, "order")
    _need(state.seats, h.issuer, "seat")
    if h.form is not None:
        _need(state.pipelines, h.form.pipeline, "pipeline")
    return state.model_copy(update={"held": _put(state.held, h.order_id, h)})


def _held_order_ended(state: State, p: ev.HeldOrderEnded) -> State:
    """A held order ends once, by its own seat's record; the order that replaced it or
    that it landed as must already be filed (LCK)."""
    h = _need(state.held, p.order_id, "held order")
    if h.issuer != p.issuer:
        raise FoldError(f"held order {p.order_id} is not that seat's")
    if p.on < h.filed:
        raise FoldError(f"held order {p.order_id} ends before it was held")
    if p.by is not None and not any(p.by in t for t in (state.held, state.orders, state.routed)):
        raise FoldError(f"held order {p.order_id}: unknown order {p.by!r}")
    return state.model_copy(
        update={
            "held": {k: v for k, v in state.held.items() if k != h.order_id},
            "asked": {k: v for k, v in state.asked.items() if k != h.order_id},
            "chosen": {k: v for k, v in state.chosen.items() if k != h.order_id},
        }
    )


def _order_asked(state: State, p: ev.OrderAsked) -> State:
    """A seat's ask for its own held order, once, with ``locks`` on; the seat it names
    holds the person asked (ASK)."""
    if Rule.LOCKS not in state.rules:
        raise FoldError("order_asked needs the locks rule")
    a = p.asked
    h = _need(state.held, a.order_id, "held order")
    if h.issuer != a.asker or state.seats[a.asker].embodies != a.by:
        raise FoldError(f"held order {a.order_id} is not that seat's")
    if a.order_id in state.asked:
        raise FoldError(f"held order {a.order_id} is asked for already")
    if a.on < h.filed:
        raise FoldError(f"held order {a.order_id} is asked for before it was held")
    _need(state.entities, a.to, "entity")
    if a.seat is not None and _need(state.seats, a.seat, "seat").embodies != a.to:
        raise FoldError(f"seat {a.seat} does not hold {a.to}")
    members = h.decider.council.members if h.decider.council is not None else ()
    for s in a.seats:
        if _need(state.seats, s, "seat").embodies not in members:
            raise FoldError(f"seat {s} holds no member of the council asked")
    return state.model_copy(update={"asked": _put(state.asked, a.order_id, a)})


def _order_defied(state: State, p: ev.OrderDefied) -> State:
    """A seat sends its own held order anyway, once, with ``defiance`` on (DFY). The order
    it lands as and the held order's end follow it."""
    if Rule.DEFIANCE not in state.rules:
        raise FoldError("order_defied needs the defiance rule")
    d = p.defied
    h = _need(state.held, d.order_id, "held order")
    if h.issuer != d.issuer:
        raise FoldError(f"held order {d.order_id} is not that seat's")
    if d.landed in state.defied or d.landed in state.routed:
        raise FoldError(f"order {d.landed} is sent already")
    if d.on < h.filed:
        raise FoldError(f"held order {d.order_id} is sent before it was held")
    if d.order_id in state.aide_orders:
        raise FoldError(f"held order {d.order_id} is the aide's: the aide never sends one anyway")
    return state.model_copy(update={"defied": {**state.defied, d.landed: d}})


def _incident_opened(state: State, p: ev.IncidentOpened) -> State:
    """An incident opens, once per order, with ``defiance`` on (DFY)."""
    if Rule.DEFIANCE not in state.rules:
        raise FoldError("incident_opened needs the defiance rule")
    i = p.incident
    if i.verdict is not None or i.answered is not None:
        raise FoldError(f"incident {i.incident_id} opens answered")
    if i.incident_id in state.incidents or any(
        o.order_id == i.order_id for o in state.incidents.values()
    ):
        raise FoldError(f"order {i.order_id} has an incident already")
    _need(state.entities, i.commander, "entity")
    _need(state.entities, i.superior, "entity")
    return state.model_copy(update={"incidents": {**state.incidents, i.incident_id: i}})


def _incident_answered(state: State, p: ev.IncidentAnswered) -> State:
    """The superior's answer to an open incident, once (DFY)."""
    i = _need(state.incidents, p.incident_id, "incident")
    if i.verdict is not None:
        raise FoldError(f"incident {i.incident_id} is answered already")
    if p.on < i.opened:
        raise FoldError(f"incident {i.incident_id} is answered before it opened")
    done = i.model_copy(update={"verdict": p.verdict, "answered": p.on, "by_card": p.by_card})
    return state.model_copy(update={"incidents": {**state.incidents, i.incident_id: done}})


def _ask_answered(state: State, p: ev.AskAnswered) -> State:
    """The card's answer to an ask, once, with ``ask_answers`` on, for a person no seat
    with a desk holds (AAK); or, with ``deciders`` on, a matter's answer on its due day
    (QKD). The matter's kept choices go with it."""
    a = _need(state.asked, p.order_id, "ask")
    h = state.held.get(a.order_id)
    matter = h is not None and locks.is_matter(state, h, a)
    if not matter and (Rule.ASK_ANSWERS not in state.rules or Rule.LOCKS not in state.rules):
        raise FoldError("ask_answered needs the locks and ask_answers rules")
    if a.asker != p.asker:
        raise FoldError(f"the ask for {p.order_id} is not that seat's")
    if a.answered is not None:
        raise FoldError(f"the ask for {p.order_id} is answered already")
    if p.on < a.on:
        raise FoldError(f"the ask for {p.order_id} is answered before it was made")
    if not matter and any(
        s.embodies == a.to and s.kind is not SeatKind.FACTION for s in state.seats.values()
    ):
        raise FoldError(f"the ask for {p.order_id} went to a person a seat holds")
    answered = a.model_copy(update={"answered": p.on, "granted": p.granted})
    chosen = {k: v for k, v in state.chosen.items() if k != p.order_id}
    return state.model_copy(
        update={"asked": {**state.asked, p.order_id: answered}, "chosen": chosen}
    )


def _matter_chosen(state: State, p: ev.MatterChosen) -> State:
    """A seat's sealed choice on an open matter before it, with ``deciders`` on (QKD); a
    later one replaces it."""
    if Rule.DECIDERS not in state.rules or Rule.LOCKS not in state.rules:
        raise FoldError("matter_chosen needs the locks and deciders rules")
    try:
        locks.may_choose(state, p.seat_id, p.order_id)
    except ValueError as exc:
        raise FoldError(f"matter_chosen: {p.seat_id} on {p.order_id}: {exc}") from exc
    if p.on < state.asked[p.order_id].on:
        raise FoldError(f"matter_chosen: {p.order_id} is chosen on before it was asked")
    kept = _put(state.chosen.get(p.order_id, {}), p.seat_id, p.accept)
    return state.model_copy(update={"chosen": _put(state.chosen, p.order_id, kept)})


def _groups_declared(state: State, p: ev.GroupsDeclared) -> State:
    if not groups.on(state):
        raise FoldError("groups_declared needs the groups rule")
    if state.groups.declared:
        raise FoldError("groups are declared once")
    found: dict[EntityId, tuple[groups.Group, ...]] = {}
    themes: dict[EntityId, tuple[groups.Theme, ...]] = {}
    for nation in p.nations:
        _fresh(found, nation.nation, "groups of nation")
        if _need(state.entities, nation.nation, "entity").kind is not EntityKind.POLITY:
            raise FoldError(f"groups_declared: {nation.nation} is not a polity")
        found[nation.nation] = nation.groups
        if nation.themes:
            themes[nation.nation] = nation.themes
    classes: dict[groups.Happening, groups.KindClass] = {}
    for c in p.classes:
        _fresh(classes, c.kind, "class of happening")
        classes[c.kind] = c
    if p.places and not groups.places_on(state):
        raise FoldError("groups_declared: places need the places rule")
    weighed: set[tuple[EntityId, EntityId]] = set()
    for place in p.places:
        if (place.territory, place.nation) in weighed:
            raise FoldError(f"groups_declared: {place.territory} weighed twice")
        weighed.add((place.territory, place.nation))
        _need(state.entities, place.territory, "entity")
        keys = {g.key for g in found.get(place.nation, ())}
        if not set(place.moves) <= keys:
            raise FoldError(f"groups_declared: a place names a group {place.nation} lacks")
    if p.elections and Rule.ELECTIONS not in state.rules:
        raise FoldError("groups_declared: elections need the elections rule")
    for election in p.elections:
        chambers = {g.chamber for g in found.get(election.nation, ()) if g.seats}
        if not set(election.chambers) <= chambers:
            raise FoldError(f"groups_declared: an election names a chamber {election.nation} lacks")
        if election.post is not None and Rule.OFFICE not in state.rules:
            raise FoldError("groups_declared: an election names a post; that needs the office rule")
    g = state.groups.model_copy(
        update={
            "declared": found,
            "themes": themes,
            "classes": classes,
            "places": p.places,
            "elections": p.elections,
        }
    )
    return state.model_copy(update={"groups": g})


def _seats_redrawn(state: State, p: ev.SeatsRedrawn) -> State:
    """An election redrew a chamber (ELE): every bloc of it named, the total kept, and each
    row of a bloc's votes scaled by its new seats over its old."""
    if not elections.on(state):
        raise FoldError("seats_redrawn needs the groups and elections rules")
    held = elections.blocs(state, p.polity, p.chamber)
    if not held or set(p.seats) != {g.key for g in held}:
        raise FoldError(f"seats_redrawn: {p.chamber} of {p.polity} has other blocs")
    if sum(p.seats.values()) != sum(g.seats or 0 for g in held):
        raise FoldError(f"seats_redrawn: {p.chamber} of {p.polity} changed its total")
    redrawn = tuple(
        groups.reseated(g, p.seats[g.key]) if g.key in p.seats and g.chamber == p.chamber else g
        for g in groups.of(state, p.polity)
    )
    declared = {**state.groups.declared, p.polity: redrawn}
    return state.model_copy(
        update={"groups": state.groups.model_copy(update={"declared": declared})}
    )


def _piece_stepped(state: State, p: ev.PieceStepped) -> State:
    """With ``places`` on, a step out of a weighted place kept as the day the nation's
    piece left it (PLW); any other step changes nothing here."""
    weighted = {place.territory for place in state.groups.places}
    if not groups.places_on(state) or p.left not in weighted:
        return state
    g = state.groups
    by = _put(g.left.get(p.left, {}), p.nation, p.on)
    return state.model_copy(
        update={"groups": g.model_copy(update={"left": _put(g.left, p.left, by)})}
    )


def _losses_held(state: State, p: ev.LossesHeld) -> State:
    """Battle losses held, added or replaced by their nation, group, battle and day; those
    whose battle has ended and whose felt share has landed by the event's day dropped."""
    if not groups.on(state) or not groups.losses_on(state):
        raise FoldError("losses_held needs the groups and losses rules")
    held = {h.key(): h for h in state.groups.held}
    for h in p.held:
        if groups.group(state, h.polity, h.group) is None:
            raise FoldError(f"losses_held: {h.polity} has no group {h.group}")
        if h.on < h.opened:
            raise FoldError(f"losses_held: losses at {h.area} before its battle opened")
        held[h.key()] = h
    kept = tuple(
        h
        for _, h in sorted(held.items())
        if not (h.ended and (p.on - h.on).days >= groups.FELT_DAYS)
    )
    return state.model_copy(update={"groups": state.groups.model_copy(update={"held": kept})})


def _group_moved(state: State, p: ev.GroupMoved) -> State:
    """A group's support set; for writing, the points spent kept for the week cap and the
    writing settled taken out of waiting."""
    if not groups.on(state):
        raise FoldError("group_moved needs the groups rule")
    was = groups.support(state, p.polity, p.group)
    if was is None:
        raise FoldError(f"group_moved: {p.polity} has no group {p.group}")
    if p.support - was != p.change:
        raise FoldError(f"group_moved: {p.group} at {was} does not move by {p.change}")
    g = state.groups
    held = _put(g.support.get(p.polity, {}), p.group, p.support)
    update: dict[str, object] = {"support": _put(g.support, p.polity, held)}
    if p.cause is groups.Cause.WRITING:
        first = p.on - timedelta(days=groups.WEEK_DAYS - 1)
        kept = [s for s in g.spent.get(p.polity, {}).get(p.group, ()) if s.on >= first]
        if p.used:
            kept.append(groups.Spent(on=p.on, points=p.used))
        spent = _put(g.spent.get(p.polity, {}), p.group, tuple(kept))
        update["spent"] = _put(g.spent, p.polity, spent)
        update["proposed"] = tuple(
            q
            for q in g.proposed
            if not (q.polity == p.polity and q.group == p.group and q.on <= p.on)
        )
    elif p.used:
        raise FoldError("group_moved: only writing spends points")
    return state.model_copy(update={"groups": g.model_copy(update=update)})


def _offer_made(state: State, p: ev.OfferMade) -> State:
    """A seat's offer of a price to a bloc of its own nation for a measure the world
    declares, waiting for its batch, with ``offers`` on (PRC)."""
    o = p.offer
    if not offers.on(state):
        raise FoldError("offer_made needs the offers rule")
    if o.standing is not offers.OfferStanding.FILED:
        raise FoldError("offer_made: an offer is made filed")
    _need(state.seats, o.seat, "seat")
    if polity_of(state, state.seats[o.seat].embodies) != o.nation:
        raise FoldError(f"offer_made: {o.seat} is not a seat of {o.nation}")
    if offers.price(state, o.nation, o.bloc, o.price) is None:
        raise FoldError(f"offer_made: {o.nation} {o.bloc} has no price {o.price}")
    if offers.law(state, o.nation, o.measure) is None:
        raise FoldError(f"offer_made: {o.nation} has no law {o.measure}")
    if any(x.offer_id == o.offer_id for x in state.offers):
        raise FoldError(f"offer_made: {o.offer_id} is made twice")
    return state.model_copy(update={"offers": (*state.offers, o)})


def _offer_settled(state: State, p: ev.OfferSettled) -> State:
    """An offer moves on from where it stands, once a day at most and never back; one
    offer at most holds a bloc on a measure (PRC)."""
    if not offers.on(state):
        raise FoldError("offer_settled needs the offers rule")
    found = next((o for o in state.offers if o.offer_id == p.offer_id), None)
    if found is None:
        raise FoldError(f"offer_settled: no offer {p.offer_id}")
    if p.standing not in offers.NEXT.get(found.standing, frozenset()):
        raise FoldError(
            f"offer_settled: {p.offer_id} cannot go from {found.standing} to {p.standing}"
        )
    if p.on < (found.on or found.filed):
        raise FoldError(f"offer_settled: {p.offer_id} moves before it last moved")
    if found.due is not None and (p.due != found.due or p.on < found.due):
        raise FoldError(f"offer_settled: {p.offer_id} is judged only on or after its due day")
    if p.standing in offers.LIVE_STANDINGS and found.standing not in offers.LIVE_STANDINGS:
        held = offers.live(state, found.nation, found.bloc, found.measure)
        if held is not None:
            raise FoldError(f"offer_settled: {found.bloc} is held on {found.measure} already")
    moved = found.model_copy(update={"standing": p.standing, "on": p.on, "due": p.due})
    out = tuple(moved if o.offer_id == p.offer_id else o for o in state.offers)
    return state.model_copy(update={"offers": out})


def _commanded(state: State, piece: Feature) -> State:
    """A piece that enters after the world compiles (a raising): every domain of a card
    that commands another piece of its nation and its domain commands it too."""
    where = kinds.domain(state, piece)

    def alike(fid: FeatureId) -> bool:
        other = state.features.get(fid)
        return (
            other is not None
            and other.feature_id != piece.feature_id
            and other.side == piece.side
            and kinds.domain(state, other) is where
        )

    cards = dict(state.cards)
    for person, card in state.cards.items():
        authority = tuple(
            dm.model_copy(update={"forces": (*dm.forces, piece.feature_id)})
            if piece.feature_id not in dm.forces and any(alike(f) for f in dm.forces)
            else dm
            for dm in card.authority
        )
        if authority != card.authority:
            cards[person] = card.model_copy(update={"authority": authority})
    return state.model_copy(update={"cards": cards})


def _card_post(state: State, cards: Mapping[EntityId, SeatCard], c: SeatCard) -> None:
    """A card's post is an office its person holds, no other card's, with ``posts`` on."""
    if Rule.POSTS not in state.rules:
        raise FoldError(f"card {c.person}: a post needs the posts rule")
    assert c.post is not None
    office = _need(state.assets, c.post, "asset")
    if office.kind is not AssetKind.OFFICE or office.controller != c.person:
        raise FoldError(f"card {c.person}: {c.post} is not an office the person holds")
    if any(other.post == c.post for other in cards.values()):
        raise FoldError(f"card {c.person}: {c.post} is another card's post")


def _office(state: State, post: AssetId, what: str) -> None:
    asset = _need(state.assets, post, "asset")
    if asset.kind is not AssetKind.OFFICE:
        raise FoldError(f"{what}: {post} is not an office")


def _on_a_ladder(state: State, post: AssetId) -> bool:
    """Whether the world names ``post`` in a ladder, as a post or a rung (LDR)."""
    return any(post == lad.post or post in lad.ladder for lad in state.ladders.values())


def _ladders_declared(state: State, p: ev.LaddersDeclared) -> State:
    """Each post's ladder, once, with ``posts`` on: every post, rung and mover an office,
    each post once, no post on its own ladder (LDR)."""
    if Rule.POSTS not in state.rules:
        raise FoldError("ladders_declared needs the posts rule")
    if state.ladders:
        raise FoldError("the ladders are declared once")
    out: dict[AssetId, Ladder] = {}
    for ladder in p.ladders:
        _fresh(out, ladder.post, "ladder")
        for post in (ladder.post, *ladder.ladder, *ladder.moved_by):
            _office(state, post, "ladders_declared")
        if ladder.post in ladder.ladder or len(set(ladder.ladder)) < len(ladder.ladder):
            raise FoldError(f"ladders_declared: {ladder.post}'s ladder repeats a post")
        if ladder.post in ladder.moved_by:
            raise FoldError(f"ladders_declared: {ladder.post} may not move itself")
        if (ladder.rests_on or ladder.removed_by) and Rule.OFFICE not in state.rules:
            raise FoldError("ladders_declared: what a post rests on needs the office rule")
        way = ladder.removed_by
        for person in (
            *(way.members if way else ()),
            *([way.person] if way and way.person else []),
        ):
            _need(state.entities, person, "entity")
        out[ladder.post] = ladder
    return state.model_copy(update={"ladders": out})


def _post_move_ordered(state: State, p: ev.PostMoveOrdered) -> State:
    """A pending change of post, with ``posts`` on: its id once, its person a card, its
    post an office (LDR)."""
    if Rule.POSTS not in state.rules:
        raise FoldError("post_move_ordered needs the posts rule")
    m = p.move
    _fresh(state.post_moves, m.move_id, "post move")
    _need(state.cards, m.person, "card")
    _need(state.entities, m.by, "entity")
    _office(state, m.post, "post_move_ordered")
    seat = seat_of_person(state, m.person)
    if m.seat != (seat.seat_id if seat is not None else None):
        raise FoldError(f"post_move_ordered: {m.move_id} names a seat its person has not")
    return state.model_copy(update={"post_moves": _put(state.post_moves, m.move_id, m)})


def _post_move_settled(state: State, p: ev.PostMoveSettled) -> State:
    """The pending change ends (LDR); one that stands as the office question's cause is
    not settled by a wake."""
    _need(state.post_moves, p.move_id, "post move")
    if p.seat != state.post_moves[p.move_id].seat:
        raise FoldError(f"post_move_settled: {p.move_id} names another seat")
    moves = dict(state.post_moves)
    del moves[p.move_id]
    return state.model_copy(update={"post_moves": moves})


def _office_question_opened(state: State, p: ev.OfficeQuestionOpened) -> State:
    """An office question opens, with ``office`` on (OFQ): its id once, one open on a
    post at a time, its holder holding the post, its post one a holder may be removed
    from, not inside a kept holder's rest, its sitting dated ahead."""
    if not office.on(state):
        raise FoldError("office_question_opened needs the office and posts rules")
    q = p.question
    _fresh(state.office_questions, q.question_id, "office question")
    why = office.refusal(state, q.post, q.opened, q.cause)
    if why:
        raise FoldError(f"office_question_opened: {q.post}: {why}")
    if posts.holder(state, q.post) != q.holder:
        raise FoldError(f"office_question_opened: {q.holder} does not hold {q.post}")
    if q.sits < q.opened + timedelta(days=office.SITTING_DAYS):
        raise FoldError(f"office_question_opened: {q.question_id} sits too soon")
    if q.tick not in (office.first_wake(state, False), office.first_wake(state, True)):
        raise FoldError(f"office_question_opened: {q.question_id} names another tick")
    update: dict[str, object] = {"office_questions": _put(state.office_questions, q.question_id, q)}
    if q.cause is QuestionCause.BASE and q.post in state.office_base_fell:
        update["office_base_fell"] = _put(
            state.office_base_fell, q.post, q.opened + timedelta(days=1)
        )
    return state.model_copy(update=update)


def _rebased(state: State, day: date | None) -> State:
    """The day each post's base fell under its line, read again after what it rests on
    moved (TUR): kept while it stays under, cleared at or above the line."""
    if day is None or not office.on(state):
        return state
    fell = office.base_fell(state, day)
    if fell == state.office_base_fell:
        return state
    return state.model_copy(update={"office_base_fell": fell})


def _office_choice_filed(state: State, p: ev.OfficeChoiceFiled) -> State:
    """A member's sealed choice on an open office question (OFQ); a later one replaces it."""
    try:
        office.may_choose(state, p.seat_id, p.question_id)
    except ValueError as exc:
        raise FoldError(f"office_choice_filed: {p.seat_id} on {p.question_id}: {exc}") from exc
    kept = _put(state.office_choices.get(p.question_id, {}), p.seat_id, p.remove)
    return state.model_copy(
        update={"office_choices": _put(state.office_choices, p.question_id, kept)}
    )


def _office_question_decided(state: State, p: ev.OfficeQuestionDecided) -> State:
    """The sitting decides the question (OFQ): never before its day, and once; a holder
    kept rests until ``rests_until``."""
    q = _need(state.office_questions, p.question_id, "office question")
    if (p.post, p.holder) != (q.post, q.holder):
        raise FoldError(f"office_question_decided: {p.question_id} names another post or holder")
    if not office.sits(state, q, p.on):
        raise FoldError(f"office_question_decided: {p.question_id} is decided before its day")
    if p.removed == (p.rests_until is not None):
        raise FoldError("office_question_decided: a holder kept rests, and only he")
    open_now = {k: v for k, v in state.office_questions.items() if k != p.question_id}
    choices = {k: v for k, v in state.office_choices.items() if k != p.question_id}
    rests = dict(state.office_rests)
    if p.rests_until is not None:
        rests[p.post] = p.rests_until
    return state.model_copy(
        update={"office_questions": open_now, "office_choices": choices, "office_rests": rests}
    )


def _post_changed(state: State, p: ev.PostChanged) -> State:
    """The post moves (PPP): the old holder's card is left with his own, the new holder's
    takes the post's part over his own, and every step, executor and command part not yet
    carried out that named the old holder names the new one."""
    if Rule.POSTS not in state.rules:
        raise FoldError("post_changed needs the posts rule")
    asset = _need(state.assets, p.post, "asset")
    if asset.kind is not AssetKind.OFFICE:
        raise FoldError(f"post_changed: {p.post} is not an office")
    current = posts.holder(state, p.post)
    if p.holder != current:
        raise FoldError(f"post_changed: {p.post} is held by {current}, not {p.holder}")
    kept = state.posts.get(p.post)
    cards = dict(state.cards)
    if kept is not None:
        part = kept.part
    elif current is not None:
        part = post_part(cards[current])
    elif _on_a_ladder(state, p.post):
        part = PostPart()  # LDR: a lesser post no card named starts with no part
    else:
        raise FoldError(f"post_changed: {p.post} is no card's post")
    if current is not None:
        card = cards[current]
        cards[current] = with_part(card, card.own or PostPart(), None)
    new = cards.get(p.to) if p.to is not None else None
    if p.to is not None:
        if new is None:
            raise FoldError(f"post_changed: {p.to} has no card")
        if new.post is not None:
            raise FoldError(f"post_changed: {p.to} holds another post")
        if state.entities[p.to].status is EntityStatus.DEAD:
            raise FoldError(f"post_changed: {p.to} is dead")
    old = current if current is not None else kept.last if kept is not None else None
    pipelines, routed, held = state.pipelines, state.routed, dict(state.posts)
    if p.to is not None and old is not None:
        to = p.to
        part = _part_renamed(part, old, to, to)
        cards = {k: _card_renamed(c, old, to) for k, c in cards.items()}
        held = {
            k: v.model_copy(update={"part": _part_renamed(v.part, old, to, v.holder)})
            for k, v in held.items()
        }
        pipelines = {
            k: pl.model_copy(
                update={
                    "steps": tuple(
                        st.model_copy(update={"person": to}) if st.person == old else st
                        for st in pl.steps
                    )
                }
            )
            for k, pl in pipelines.items()
        }
        routed = {k: _routed_renamed(o, old, to) for k, o in routed.items()}
    if p.to is not None:
        cards[p.to] = with_part(cards[p.to], part, p.post)
    if p.to is not None:
        controller = p.to
    else:
        assert current is not None
        controller = state.entities[current].parent or asset.controller
    held[p.post] = Post(holder=p.to, part=part, last=current if p.to is None else None)
    return state.model_copy(
        update={
            "cards": cards,
            "pipelines": pipelines,
            "routed": routed,
            "posts": held,
            "assets": _put(
                state.assets, p.post, asset.model_copy(update={"controller": controller})
            ),
        }
    )


def _domains_renamed(
    domains: tuple[Domain, ...], old: EntityId, new: EntityId, owner: EntityId | None
) -> tuple[Domain, ...]:
    """Each domain carried out by ``old`` carried out by ``new``; by nobody (the holder
    acts himself) where that is ``owner``, the person whose card holds it."""
    out: list[Domain] = []
    for dm in domains:
        executor = new if dm.executor == old else dm.executor
        if executor is not None and executor == owner:
            executor = None
        out.append(dm if executor == dm.executor else dm.model_copy(update={"executor": executor}))
    return tuple(out)


def _part_renamed(part: PostPart, old: EntityId, new: EntityId, owner: EntityId | None) -> PostPart:
    return part.model_copy(update={"authority": _domains_renamed(part.authority, old, new, owner)})


def _card_renamed(card: SeatCard, old: EntityId, new: EntityId) -> SeatCard:
    update: dict[str, object] = {
        "authority": _domains_renamed(card.authority, old, new, card.person)
    }
    if card.own is not None:
        update["own"] = _part_renamed(card.own, old, new, card.person)
    return card.model_copy(update=update)


def _routed_renamed(order: RoutedOrder, old: EntityId, new: EntityId) -> RoutedOrder:
    """The command parts ``old`` was to carry out and has not, to be carried out by ``new``."""
    parts = tuple(
        part.model_copy(update={"executor": new})
        if part.route is Route.COMMAND
        and part.executor == old
        and part.fidelity is None
        and not part.refusal
        else part
        for part in order.parts
    )
    return order if parts == order.parts else order.model_copy(update={"parts": parts})


def _agreement_event(state: State, p: ev.Payload) -> State:
    """An offer recorded, an agreement made, a clause judged or an agreement published
    (AGR), each only with the ``agreements`` rule on."""
    if not agreement.on(state):
        raise FoldError(f"{p.kind} needs the agreements rule")
    a = state.agreements
    match p:
        case ev.AgreementOffered():
            o = p.offer
            _fresh(a.offers, o.offer_id, "offer")
            if o.version != agreement.version(o.parties, o.wording, o.clauses):
                raise FoldError(f"agreement_offered: {o.offer_id} has the wrong version")
            a = a.model_copy(update={"offers": _put(a.offers, o.offer_id, o)})
        case ev.AgreementMade():
            x = p.agreement
            _fresh(a.made, x.agreement_id, "agreement")
            for party in x.parties:
                if _need(state.entities, party, "entity").kind is not EntityKind.POLITY:
                    raise FoldError(f"agreement_made: {party} is not a polity")
            if len(x.statuses) != len(x.clauses):
                raise FoldError("agreement_made: one status for each clause")
            if x.offer_id is not None:
                offer = _need(a.offers, x.offer_id, "offer")
                if offer.version != x.version:
                    raise FoldError("agreement_made: not the version that was offered")
            a = a.model_copy(update={"made": _put(a.made, x.agreement_id, x)})
        case ev.ClauseJudged():
            x = _need(a.made, p.agreement_id, "agreement")
            if p.clause >= len(x.clauses):
                raise FoldError(f"clause_judged: {x.agreement_id} has no clause {p.clause}")
            statuses = list(x.statuses)
            calls = list(x.calls)
            if p.status is agreement.ClauseStatus.CALLED:
                if p.against is None or p.due is None:
                    raise FoldError("clause_judged: a call names its attacker and due day")
                calls.append(agreement.Call(clause=p.clause, against=p.against, due=p.due))
                statuses[p.clause] = p.status
            elif p.against is not None:
                calls = [c for c in calls if (c.clause, c.against) != (p.clause, p.against)]
                if not any(c.clause == p.clause for c in calls):
                    statuses[p.clause] = agreement.ClauseStatus.STANDING
            else:
                statuses[p.clause] = p.status
                calls = [c for c in calls if c.clause != p.clause]
            x = x.model_copy(update={"statuses": tuple(statuses), "calls": tuple(calls)})
            a = a.model_copy(update={"made": _put(a.made, x.agreement_id, x)})
        case ev.AgreementPublished():
            x = _need(a.made, p.agreement_id, "agreement")
            if x.published is not None:
                raise FoldError(f"agreement_published: {x.agreement_id} is already published")
            if p.by not in x.parties:
                raise FoldError("agreement_published: only a party publishes")
            x = x.model_copy(update={"published": p.on})
            a = a.model_copy(update={"made": _put(a.made, x.agreement_id, x)})
    return state.model_copy(update={"agreements": a})


def _conference_event(state: State, p: ev.Payload) -> State:
    """A conference called or opened, a vote sealed, or a tally (CNF), each only with the
    ``conference`` rule on."""
    if not conference.on(state):
        raise FoldError(f"{p.kind} needs the conference rule")
    c = state.conferences
    match p:
        case ev.ConferenceCalled():
            x = p.conference
            for nation in (x.caller, *x.invited):
                if _need(state.entities, nation, "entity").kind is not EntityKind.POLITY:
                    raise FoldError(f"conference_called: {nation} is not a polity")
            if x.caller not in x.invited:
                raise FoldError("conference_called: the caller is invited")
            if x.tally is not None:
                raise FoldError("conference_called: a conference is called before its tally")
            found = c.held.get(x.key)
            if found is not None:
                waiting = found.tally_wake is None and x.tally_wake is not None
                if not waiting or found.model_copy(update={"tally_wake": x.tally_wake}) != x:
                    raise FoldError(f"conference_called: {x.key} is already called")
            c = c.model_copy(update={"held": _put(c.held, x.key, x)})
        case ev.VoteSealed():
            x = _need(c.held, p.conference, "conference")
            _need(state.seats, p.seat_id, "seat")
            if x.tally is not None or x.tally_wake is None:
                raise FoldError(f"vote_sealed: {x.key} is not open to votes")
            held = c.votes.get(x.key, {})
            if p.seat_id in held and held[p.seat_id].wake != p.wake:
                raise FoldError(f"vote_sealed: {p.seat_id} already voted in an earlier wake")
            ballot = conference.Ballot(vote=p.vote, wake=p.wake)
            votes = _put(c.votes, x.key, _put(held, p.seat_id, ballot))
            c = c.model_copy(update={"votes": votes})
        case ev.ConferenceTallied():
            x = _need(c.held, p.conference, "conference")
            if x.tally is not None:
                raise FoldError(f"conference_tallied: {x.key} is already tallied")
            if p.tally.on < x.voting_day:
                raise FoldError(f"conference_tallied: {x.key} tallied before its voting day")
            x = x.model_copy(update={"tally": p.tally})
            c = c.model_copy(update={"held": _put(c.held, x.key, x)})
    return state.model_copy(update={"conferences": c})


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def empty(campaign_id: CampaignId) -> State:
    return State(campaign_id=campaign_id)


def state_hash(state: State) -> str:
    """blake2b-128 over canonical JSON. Set fields serialise sorted (see ``_base``)."""
    canon = json.dumps(
        state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.blake2b(canon.encode(), digest_size=16).hexdigest()


def apply(state: State, event: Event) -> State:
    if event.campaign_id != state.campaign_id:
        raise FoldError(f"event {event.event_id} belongs to campaign {event.campaign_id}")
    if event.seq != state.last_seq + 1:
        raise FoldError(f"sequence gap: expected {state.last_seq + 1}, got {event.seq}")
    if isinstance(event.payload, ev.Sealed) and event.payload.holder == "campaign":
        raise FoldError(f"event {event.event_id} is still sealed: its campaign key is missing")
    if event.kind in MUTATING_KINDS:
        state = _mutate(state, event)
    return state.model_copy(update={"last_seq": event.seq})


def replay(events: Iterable[Event], *, initial: State | None = None) -> State:
    state = initial
    for event in events:
        if state is None:
            state = empty(event.campaign_id)
        state = apply(state, event)
    if state is None:
        raise FoldError("nothing to replay")
    return state


def replay_to(events: Iterable[Event], tick: int, *, initial: State | None = None) -> State:
    """State at the end of ``tick`` (every event with ``event.tick <= tick``)."""
    return replay((e for e in events if e.tick <= tick), initial=initial)


# --- payloads -----------------------------------------------------------------


def _mutate(state: State, event: Event) -> State:
    p = event.payload
    match p:
        case ev.CampaignCreated():
            return state.model_copy(update={"ruleset": p.ruleset, "rules": p.rules})
        case ev.SettingsSet():
            return state.model_copy(update={"settings": p.settings})
        case ev.EntityCreated():
            _fresh(state.entities, p.entity.entity_id, "entity")
            return state.model_copy(
                update={"entities": _put(state.entities, p.entity.entity_id, p.entity)}
            )
        case ev.AssetCreated():
            _fresh(state.assets, p.asset.asset_id, "asset")
            return state.model_copy(
                update={"assets": _put(state.assets, p.asset.asset_id, p.asset)}
            )
        case ev.RelationshipSet():
            r = p.relationship
            return state.model_copy(
                update={"relationships": _put(state.relationships, r.relationship_id, r)}
            )
        case ev.MeterCreated():
            _fresh(state.meters, p.meter.meter_id, "meter")
            return state.model_copy(
                update={"meters": _put(state.meters, p.meter.meter_id, p.meter)}
            )
        case ev.ClockCreated():
            _fresh(state.clocks, p.clock.clock_id, "clock")
            return state.model_copy(
                update={"clocks": _put(state.clocks, p.clock.clock_id, p.clock)}
            )
        case ev.FactAsserted():
            _fresh(state.facts, p.fact.fact_id, "fact")
            return state.model_copy(update={"facts": _put(state.facts, p.fact.fact_id, p.fact)})
        case ev.CommitmentCreated():
            c = p.commitment
            _fresh(state.commitments, c.commitment_id, "commitment")
            return state.model_copy(
                update={"commitments": _put(state.commitments, c.commitment_id, c)}
            )
        case ev.SeatCreated():
            _fresh(state.seats, p.seat.seat_id, "seat")
            return state.model_copy(update={"seats": _put(state.seats, p.seat.seat_id, p.seat)})
        case ev.AgentAssigned():
            seat = _need(state.seats, p.seat_id, "seat")
            _need(state.entities, p.agent, "agent entity")
            seat = seat.model_copy(
                update={"agent": p.agent, "persona": p.persona, "status": SeatStatus.ACTIVE}
            )
            return state.model_copy(update={"seats": _put(state.seats, seat.seat_id, seat)})
        case ev.SeatStatusSet():
            seat = _need(state.seats, p.seat_id, "seat")
            update: dict[str, object] = {"status": p.status}
            if p.status is SeatStatus.BLINDED:
                update["agent"] = None
            seat = seat.model_copy(update=update)
            return state.model_copy(update={"seats": _put(state.seats, seat.seat_id, seat)})
        case ev.IntentFiled():
            i = p.intent
            _fresh(state.pending, i.intent_id, "intent")
            _need(state.seats, i.actor, "seat")
            return state.model_copy(update={"pending": _put(state.pending, i.intent_id, i)})
        case ev.IntentRejected():
            if p.intent_id not in state.pending:
                return state  # rejected at filing: a record, nothing to remove
            pending = {k: v for k, v in state.pending.items() if k != p.intent_id}
            frozen = tuple(i for i in state.frozen if i != p.intent_id)
            return state.model_copy(update={"pending": pending, "frozen": frozen})
        case ev.DeltaApplied():
            return _apply_delta(state, p.delta, event.tick)
        case ev.ScheduledEventFired():
            s = _need(state.scheduled, p.scheduled_id, "scheduled event")
            if s.skipped:
                raise FoldError(f"scheduled event {s.scheduled_id!r} was skipped")
            s = s.model_copy(update={"fired": True})
            return state.model_copy(update={"scheduled": _put(state.scheduled, s.scheduled_id, s)})
        case ev.ScheduledEventCreated():
            s = p.scheduled
            _fresh(state.scheduled, s.scheduled_id, "scheduled event")
            if s.fired or s.skipped:
                raise FoldError(f"scheduled event {s.scheduled_id!r} must start pending")
            return state.model_copy(update={"scheduled": _put(state.scheduled, s.scheduled_id, s)})
        case ev.ScheduledEventSkipped():
            s = _need(state.scheduled, p.scheduled_id, "scheduled event")
            if s.fired or s.skipped:
                raise FoldError(f"scheduled event {s.scheduled_id!r} is already settled")
            s = s.model_copy(update={"skipped": True})
            return state.model_copy(update={"scheduled": _put(state.scheduled, s.scheduled_id, s)})
        case ev.ContestCreated():
            k = p.contest
            _fresh(state.contests, k.contest_id, "contest")
            for side in k.sides:
                _need(state.entities, side, "entity")
            if k.decided:
                raise FoldError(f"contest {k.contest_id!r} must start undecided")
            return state.model_copy(update={"contests": _put(state.contests, k.contest_id, k)})
        case ev.ContestMoved():
            k = _need(state.contests, p.contest_id, "contest")
            if k.decided:
                raise FoldError(f"contest {k.contest_id!r} is decided")
            moves = k.moves
            if p.move is not None:  # CON: one of the contest's own moves, landing once
                if p.move >= len(moves):
                    raise FoldError(f"contest {k.contest_id!r} has no move {p.move}")
                if moves[p.move].landed:
                    raise FoldError(f"contest {k.contest_id!r}: move {p.move} has landed")
                landed = moves[p.move].model_copy(update={"landed": True})
                moves = (*moves[: p.move], landed, *moves[p.move + 1 :])
            k = k.model_copy(
                update={
                    "track": _clamp(k.track + p.change, k.floor, TRACK_MAX),
                    "countdown_days": max(0, k.countdown_days - p.days),
                    "moves": moves,
                }
            )
            return state.model_copy(update={"contests": _put(state.contests, k.contest_id, k)})
        case ev.ContestDecided():
            k = _need(state.contests, p.contest_id, "contest")
            if k.decided:
                raise FoldError(f"contest {k.contest_id!r} is already decided")
            if p.winner is not None and p.winner not in k.sides:
                raise FoldError(f"contest {k.contest_id!r}: winner is not a side")
            k = k.model_copy(update={"decided": True, "winner": p.winner, "countdown_days": 0})
            return state.model_copy(update={"contests": _put(state.contests, k.contest_id, k)})
        case ev.DivergenceChanged():
            return state.model_copy(update={"divergence": max(0, state.divergence + p.change)})
        case ev.DateAdvanced():
            if state.in_world_date is not None and p.to < state.in_world_date:
                raise FoldError("the in-world date never runs backwards")
            return state.model_copy(update={"in_world_date": p.to})
        case ev.SessionZeroOpened():
            humans = any(x.controller is Controller.HUMAN for x in state.seats.values())
            if state.tick != 0 or state.phase is not Phase.PLAY or humans:
                raise FoldError("Session Zero opens once, before anyone plays")
            return state.model_copy(update={"phase": Phase.SESSION_ZERO})
        case ev.CharacterListed():
            ch = p.character
            _fresh(state.roster, ch.entity_id, "character")
            person = _need(state.entities, ch.entity_id, "entity")
            if person.kind is not EntityKind.PERSON:
                raise FoldError(f"character {ch.entity_id} is not a person")
            for asset_id in ch.means:
                if _need(state.assets, asset_id, "asset").controller != ch.entity_id:
                    raise FoldError(f"character {ch.entity_id} does not control {asset_id}")
            return state.model_copy(update={"roster": _put(state.roster, ch.entity_id, ch)})
        case ev.CharacterClaimed():
            if state.phase is not Phase.SESSION_ZERO:
                raise FoldError("a character is claimed during Session Zero")
            ch = _need(state.roster, p.entity_id, "character")
            if ch.claimed_by is not None:
                raise FoldError(f"character {p.entity_id} is already claimed")
            _fresh(state.seats, p.seat_id, "seat")
            taken = sum(x.controller is Controller.HUMAN for x in state.seats.values())
            if taken >= state.settings.max_human_seats:
                raise FoldError("every human seat is taken")
            seat = Seat(
                seat_id=p.seat_id,
                kind=SeatKind.PLAYER,
                name=state.entities[p.entity_id].name,
                embodies=p.entity_id,
                controller=Controller.HUMAN,
                slots=state.settings.starting_slots,
                joined_tick=state.tick,
            )
            ch = ch.model_copy(update={"claimed_by": p.seat_id})
            return state.model_copy(
                update={
                    "seats": _put(state.seats, seat.seat_id, seat),
                    "roster": _put(state.roster, ch.entity_id, ch),
                }
            )
        case ev.CharacterReleased():
            if state.ruleset != "realism":
                raise FoldError("a pick is released only in a realism campaign")
            if state.phase is not Phase.SESSION_ZERO:
                raise FoldError("a character is released during Session Zero")
            seat = _need(state.seats, p.seat_id, "seat")
            ch = _need(state.roster, p.entity_id, "character")
            if seat.embodies != p.entity_id or ch.claimed_by != p.seat_id:
                raise FoldError(f"seat {p.seat_id} does not play {p.entity_id}")
            ch = ch.model_copy(update={"claimed_by": None})
            return state.model_copy(
                update={
                    "seats": {k: v for k, v in state.seats.items() if k != p.seat_id},
                    "roster": _put(state.roster, ch.entity_id, ch),
                    "styles": {k: v for k, v in state.styles.items() if k != p.seat_id},
                    "standing": {k: v for k, v in state.standing.items() if k != p.seat_id},
                }
            )
        case ev.SessionZeroClosed():
            if state.phase is not Phase.SESSION_ZERO:
                raise FoldError("Session Zero is not open")
            return state.model_copy(update={"phase": Phase.PLAY})
        case ev.SeasonEnded():
            if state.phase is not Phase.PLAY or state.frozen:
                raise FoldError("a season ends between ticks, in play")
            if p.winners != tuple(sorted(season_winners(state))):
                raise FoldError("season_ended names other winners than the goals do")
            public = {k: g.model_copy(update={"scope": PUBLIC}) for k, g in state.goals.items()}
            return state.model_copy(update={"phase": Phase.SEASON_OVER, "goals": public})
        case ev.GoalSet():
            g = p.goal
            _fresh(state.goals, g.goal_id, "goal")
            seat = _need(state.seats, g.seat_id, "seat")
            if g.person is not None:
                _aim_goal(state, g, seat)
                return state.model_copy(update={"goals": _put(state.goals, g.goal_id, g)})
            if g.clock_id is None:
                raise FoldError(f"goal {g.goal_id} has no objective clock")
            clock = _need(state.clocks, g.clock_id, "clock")
            if clock.kind is not ClockKind.OBJECTIVE or clock.owner != seat.seat_id:
                raise FoldError(f"goal {g.goal_id}: clock {g.clock_id} is not its objective")
            if any(o.seat_id == g.seat_id and o.person is None for o in state.goals.values()):
                raise FoldError(f"seat {g.seat_id} already has a goal")
            return state.model_copy(update={"goals": _put(state.goals, g.goal_id, g)})
        case ev.GoalProgressed():
            g = _need(state.goals, p.goal_id, "goal")
            if g.clock_id is None:
                raise FoldError(f"goal {g.goal_id} has no objective clock")
            objective = _need(state.clocks, g.clock_id, "clock")
            if p.parts_met > objective.segments_total:
                raise FoldError(f"goal {g.goal_id}: {p.parts_met} parts on a clock that has fewer")
            objective = objective.model_copy(update={"segments_filled": p.parts_met})
            return state.model_copy(
                update={"clocks": _put(state.clocks, objective.clock_id, objective)}
            )
        case ev.GoalMet():
            g = _need(state.goals, p.goal_id, "goal")
            first = g.met_tick if g.met_tick is not None else event.tick
            g = g.model_copy(update={"holding": True, "met_tick": first})
            return state.model_copy(update={"goals": _put(state.goals, g.goal_id, g)})
        case ev.GoalUndone():
            g = _need(state.goals, p.goal_id, "goal")
            if g.kind is GoalKind.LASTING:
                raise FoldError(f"goal {g.goal_id} is lasting and cannot be undone")
            g = g.model_copy(update={"holding": False})
            return state.model_copy(update={"goals": _put(state.goals, g.goal_id, g)})
        case ev.TickOpened():
            for intent_id in p.intents_frozen:
                _need(state.pending, intent_id, "intent")
            return state.model_copy(update={"tick": event.tick, "frozen": p.intents_frozen})
        case ev.TickClosed():
            actual = state_hash(state)
            if actual != p.state_hash:
                raise FoldError(
                    f"state hash mismatch at tick {event.tick}: log says {p.state_hash}, "
                    f"replay gives {actual}"
                )
            done = set(state.frozen)
            if p.quiet:
                pending = dict(state.pending)  # nothing resolved; intents carry forward
            else:
                # An intent with an operation still running stays pending, so the
                # next tick can re-rate and re-roll it (design: the world keeps moving).
                running = {
                    c.intent_id
                    for c in state.clocks.values()
                    if (
                        c.kind is ClockKind.OPERATION
                        and c.status is ClockStatus.OPEN
                        and c.intent_id
                    )
                }
                pending = {k: v for k, v in state.pending.items() if k not in done or k in running}
            return state.model_copy(
                update={"pending": pending, "frozen": (), "tick": event.tick + 1}
            )
        case (
            ev.CardsDeclared()
            | ev.DocumentIssued()
            | ev.DocumentWritten()
            | ev.OrderDrafted()
            | ev.OrderStepTaken()
            | ev.OrderSettled()
            | ev.QuantitySet()
            | ev.FeatureSet()
            | ev.WarDeclared()
            | ev.WarEnded()
            | ev.MapDeclared()
            | ev.KindsDeclared()
            | ev.LocksDeclared()
            | ev.LawsDeclared()
            | ev.AimPatternsDeclared()
            | ev.OwnAimSet()
            | ev.OrderHeld()
            | ev.HeldOrderEnded()
            | ev.OrderAsked()
            | ev.AskAnswered()
            | ev.OrderDefied()
            | ev.IncidentOpened()
            | ev.IncidentAnswered()
            | ev.MatterChosen()
            | ev.OfferMade()
            | ev.OfferSettled()
            | ev.PostChanged()
            | ev.LaddersDeclared()
            | ev.PostMoveOrdered()
            | ev.PostMoveSettled()
            | ev.OfficeQuestionOpened()
            | ev.OfficeChoiceFiled()
            | ev.OfficeQuestionDecided()
            | ev.SeatsRedrawn()
            | ev.PieceStepped()
            | ev.AreaHeld()
            | ev.CaptureCounted()
            | ev.EconomySet()
            | ev.YieldChanged()
            | ev.TradeSet()
            | ev.BattleOpened()
            | ev.BattleRound()
            | ev.BattleEnded()
            | ev.BattleDecided()
            | ev.IntelligenceDeclared()
            | ev.ReportMade()
            | ev.AgentSet()
            | ev.CodebreakingSet()
            | ev.GroupsDeclared()
            | ev.GroupMoved()
            | ev.GroupProposed()
            | ev.LossesHeld()
            | ev.AgreementOffered()
            | ev.AgreementMade()
            | ev.ClauseJudged()
            | ev.AgreementPublished()
            | ev.ConferenceCalled()
            | ev.VoteSealed()
            | ev.ConferenceTallied()
            | ev.NewsReported()
            | ev.StanceChanged()
            | ev.OpponentsRanked()
            | ev.CardAmended()
            | ev.AnswerPlanned()
            | ev.AnswerMade()
            | ev.StepChosen()
        ):
            if state.ruleset != "realism":
                raise FoldError(f"{event.kind} belongs to a realism campaign")
            return _realism(state, p)
        case (
            ev.OrderRouted()
            | ev.OrderExecuted()
            | ev.EffectsEstimated()
            | ev.EffectsApplied()
            | ev.InfluenceDecided()
            | ev.MandateIssued()
            | ev.MandateSettled()
            | ev.WakeOpened()
            | ev.WakeCommitted()
            | ev.WakeClosed()
            | ev.PlayStyleSet()
            | ev.SeatHandover()
            | ev.RequestAnswered()
        ):
            if state.ruleset != "realism":
                raise FoldError(f"{event.kind} belongs to a realism campaign")
            return _engine_v2(state, p)
        case _:
            raise FoldError(f"mutating kind {event.kind!r} has no fold case")


# --- realism --------------------------------------------------------------------


def _battle_opened(state: State, p: ev.BattleOpened) -> State:
    """A battle opens: the rule is on, the area is on the board with no battle open, and
    each side's pieces are pieces of the game; the two leading nations are at war."""
    b = p.battle
    if Rule.BATTLES not in state.rules or state.map is None:
        raise FoldError("battle_opened: the battles rule is off")
    if b.area not in state.map.areas():
        raise FoldError(f"battle_opened: {b.area} is not an area")
    if b.area in state.battles:
        raise FoldError(f"battle_opened: a battle is already open at {b.area}")
    if b.opened != p.on:
        raise FoldError("battle_opened: a battle opens on its own day")
    for side in (b.attacker, b.defender):
        if _need(state.entities, side.nation, "entity").kind is not EntityKind.POLITY:
            raise FoldError(f"battle_opened: {side.nation} is not a polity")
        for fid in side.pieces:
            _need(state.features, fid, "feature")
    if not at_war(state, b.attacker.nation, b.defender.nation):
        raise FoldError("battle_opened: the two sides are not at war")
    fought = state.fought | {b.area, *([b.second] if b.second is not None else [])}
    return state.model_copy(update={"battles": _put(state.battles, b.area, b), "fought": fought})


def _battle_decided(state: State, p: ev.BattleDecided) -> State:
    """A side's decision, or pieces joining it (BDC): the battle is open, the nation leads
    one of its sides, no second decision in one wake, and each piece that joins is a piece
    of the game on neither side yet."""
    fought = _open_battle(state, p.area, p.on, "battle_decided")
    if p.nation == fought.attacker.nation:
        which = "attacker"
    elif p.nation == fought.defender.nation:
        which = "defender"
    else:
        raise FoldError(f"battle_decided: {p.nation} leads no side at {p.area}")
    side = getattr(fought, which)
    update: dict[str, object] = {}
    if p.decision is not None:
        if side.decided_wake == p.wake:
            raise FoldError(f"battle_decided: {p.nation} has decided in wake {p.wake}")
        update |= {"decision": p.decision, "decided_wake": p.wake}
    if p.joined:
        ours = {*fought.attacker.pieces, *fought.defender.pieces}
        for fid in p.joined:
            _need(state.features, fid, "feature")
            if fid in ours:
                raise FoldError(f"battle_decided: {fid} is already in the battle")
        update |= {
            "pieces": tuple(sorted((*side.pieces, *p.joined))),
            "brought": side.brought + p.added,
        }
    fought = fought.model_copy(update={which: side.model_copy(update=update)})
    return state.model_copy(update={"battles": _put(state.battles, p.area, fought)})


def _open_battle(state: State, area: EntityId, on: date, what: str) -> Battle:
    fought = state.battles.get(area)
    if fought is None:
        raise FoldError(f"{what}: no battle is open at {area}")
    if on < fought.opened:
        raise FoldError(f"{what}: {area}'s battle opened after {on}")
    return fought


def _realism(state: State, p: ev.Payload) -> State:
    """Store and update realism records. Deciding what they say is the engine's job."""
    match p:
        case ev.CardsDeclared():
            topics = dict(state.topics)
            for topic in p.topics:
                _fresh(topics, topic.key, "topic")
                topics[topic.key] = topic
            pipelines = dict(state.pipelines)
            for pl in p.pipelines:
                _fresh(pipelines, pl.pipeline_id, "pipeline")
                for step in pl.steps:
                    _need(state.entities, step.person, "entity")
                pipelines[pl.pipeline_id] = pl
            feeds = dict(state.feeds)
            for f in p.feeds:
                _fresh(feeds, f.feed_id, "feed")
                _need(state.entities, f.author, "entity")
                for qid in f.reports:
                    _need(state.quantities, qid, "quantity")
                for sighted in f.sights:
                    _need(state.features, sighted, "feature")
                feeds[f.feed_id] = f
            cards = dict(state.cards)
            for c in p.cards:
                _fresh(cards, c.person, "card")
                person = _need(state.entities, c.person, "entity")
                if person.kind is not EntityKind.PERSON:
                    raise FoldError(f"card {c.person} is not a person")
                named = [
                    *c.principals,
                    *(k.person for k in c.inner_circle),
                    *(dm.executor for dm in c.authority if dm.executor is not None),
                    *c.reach.chain,
                    *c.allies,
                    *(x.against for x in c.opposes),
                ]
                for entity in [*named, *([c.successor] if c.successor else [])]:
                    _need(state.entities, entity, "entity")
                for dm in c.authority:
                    for force in dm.forces:
                        _need(state.features, force, "feature")
                for fid in c.feeds:
                    _need(feeds, fid, "feed")
                for pid in c.pipelines:
                    _need(pipelines, pid, "pipeline")
                for key in c.topics():
                    _need(topics, key, "topic")
                for lever in c.levers:
                    if lever.pipeline not in c.pipelines:
                        raise FoldError(
                            f"card {c.person}: lever {lever.name} names another pipeline"
                        )
                if c.post is not None:
                    _card_post(state, cards, c)
                cards[c.person] = c
            templates = dict(state.templates)
            for t in p.templates:
                _fresh(templates, t.key, "mandate template")
                for entity in [*t.to, *([t.issuer] if t.issuer else [])]:
                    _need(state.entities, entity, "entity")
                templates[t.key] = t
            outlets = dict(state.outlets)
            for outlet in p.outlets:
                _fresh(outlets, outlet.outlet_id, "outlet")
                _need(state.entities, outlet.outlet_id, "entity")
                if _need(state.entities, outlet.polity, "entity").kind is not EntityKind.POLITY:
                    raise FoldError(f"outlet {outlet.outlet_id}: {outlet.polity} is not a polity")
                outlets[outlet.outlet_id] = outlet
            return state.model_copy(
                update={
                    "cards": cards,
                    "feeds": feeds,
                    "pipelines": pipelines,
                    "templates": templates,
                    "outlets": outlets,
                    "topics": topics,
                }
            )
        case ev.DocumentIssued():
            doc = Document(view=p.document, truth=p.truth)
            _fresh(state.documents, doc.view.doc_id, "document")
            _need(state.entities, doc.view.author, "entity")
            if doc.truth.feed is not None:
                _need(state.feeds, doc.truth.feed, "feed")
            for ref in doc.truth.truth_refs:
                _need(state.quantities, ref.quantity_id, "quantity")
            for sighting in doc.truth.sightings:
                _need(state.features, sighting.feature_id, "feature")
            return state.model_copy(
                update={"documents": _put(state.documents, doc.view.doc_id, doc)}
            )
        case ev.DocumentWritten():
            doc = _need(state.documents, p.doc_id, "document")
            if doc.view.prose is not None:
                raise FoldError(f"document {p.doc_id} is already written")
            view = doc.view.model_copy(update={"prose": p.prose})
            return state.model_copy(
                update={
                    "documents": _put(
                        state.documents, p.doc_id, doc.model_copy(update={"view": view})
                    )
                }
            )
        case ev.OrderDrafted():
            o = p.order
            _fresh(state.orders, o.order_id, "order")
            _need(state.seats, o.issuer, "seat")
            _need(state.pipelines, o.pipeline, "pipeline")
            if o.status is not OrderStatus.MOVING or o.step or o.outcomes or o.held_choice:
                raise FoldError(f"order {o.order_id} must start at its first step")
            if o.routed_from is not None:
                carried = o.routed_from
                routed = _need(state.routed, carried.order_id, "order")
                part = _part_at(routed, carried.part)
                if part.route is not Route.PROCESS or part.pipeline != o.pipeline:
                    raise FoldError(f"order {o.order_id}: part {carried.part} is not that process")
                if any(x.routed_from == carried for x in state.orders.values()):
                    raise FoldError(
                        f"order {carried.order_id} part {carried.part} is already carried"
                    )
            return state.model_copy(update={"orders": _put(state.orders, o.order_id, o)})
        case ev.OrderStepTaken():
            o = _need(state.orders, p.order_id, "order")
            steps = state.pipelines[o.pipeline].steps
            out = p.outcome
            if o.status in SETTLED:
                raise FoldError(f"order {o.order_id} is settled")
            if out.step != o.step or o.step >= len(steps):
                raise FoldError(f"order {o.order_id} is not at step {out.step}")
            if out.person != steps[o.step].person or out.action not in steps[o.step].allowed:
                raise FoldError(f"order {o.order_id}: step {o.step} does not allow that")
            params = dict(o.params)
            if out.action is StepAction.AMEND:
                if not set(out.amended) <= set(params):
                    raise FoldError(f"order {o.order_id}: an amendment names a new parameter")
                params.update(out.amended)
            o = o.model_copy(
                update={
                    "params": params,
                    "step": o.step + 1 if out.action in ADVANCES else o.step,
                    "outcomes": (*o.outcomes, out),
                    "held_choice": None,
                }
            )
            return state.model_copy(update={"orders": _put(state.orders, o.order_id, o)})
        case ev.StepChosen():
            o = _need(state.orders, p.order_id, "order")
            if p.step != o.step or not _held_elsewhere(state, o):
                raise FoldError(
                    f"order {o.order_id} does not wait at step {p.step} on another seat"
                )
            if p.action not in state.pipelines[o.pipeline].steps[o.step].allowed:
                raise FoldError(f"order {o.order_id}: step {o.step} does not allow that")
            if not set(p.amended) <= set(o.params):
                raise FoldError(f"order {o.order_id}: an amendment names a new parameter")
            choice = HeldChoice(step=p.step, action=p.action, amended=p.amended)
            o = o.model_copy(update={"held_choice": choice})
            return state.model_copy(update={"orders": _put(state.orders, o.order_id, o)})
        case ev.OrderSettled():
            o = _need(state.orders, p.order_id, "order")
            if o.status in SETTLED or p.status not in SETTLED:
                raise FoldError(f"order {o.order_id} cannot settle as {p.status.value}")
            o = o.model_copy(update={"status": p.status})
            return state.model_copy(update={"orders": _put(state.orders, o.order_id, o)})
        case ev.QuantitySet():
            q = p.quantity
            if q.owner is not None:
                _need(state.entities, q.owner, "entity")
            old = state.quantities.get(q.quantity_id)
            if old is not None and q.as_of < old.as_of:
                raise FoldError(f"quantity {q.quantity_id} is already set as of {old.as_of}")
            return state.model_copy(update={"quantities": _put(state.quantities, q.quantity_id, q)})
        case ev.FeatureSet():
            ft = p.feature
            if ft.side is not None:
                _need(state.entities, ft.side, "entity")
            for place in (*ft.places, *([ft.bound_for] if ft.bound_for else [])):
                if _need(state.entities, place, "entity").kind is not EntityKind.LOCATION:
                    raise FoldError(f"feature {ft.feature_id}: {place} is not a place")
            if ft.piece is not None and (state.kinds is None or ft.piece not in state.kinds.pieces):
                raise FoldError(f"feature {ft.feature_id}: unknown piece kind {ft.piece}")
            was = state.features.get(ft.feature_id)
            if was is not None and (
                ft.as_of < was.as_of or ft.kind is not was.kind or ft.piece != was.piece
            ):
                raise FoldError(f"feature {ft.feature_id} cannot go back or change kind")
            state = state.model_copy(update={"features": _put(state.features, ft.feature_id, ft)})
            if was is None and ft.piece is not None and Rule.RAISING in state.rules:
                return _commanded(state, ft)
            return state
        case ev.WarDeclared():
            w = p.war
            for side in (w.a, w.b):
                if _need(state.entities, side, "entity").kind is not EntityKind.POLITY:
                    raise FoldError(f"war {w.war_id}: {side} is not a polity")
            if at_war(state, w.a, w.b):
                raise FoldError(f"{w.a} and {w.b} are already at war")
            return state.model_copy(update={"wars": _put(state.wars, w.war_id, w)})
        case ev.WarEnded():
            if Rule.PEACE not in state.rules:
                raise FoldError("war_ended needs the peace rule")
            ended = state.wars.get(p.war_id)
            if ended is None:
                raise FoldError(f"{p.war_id}: not at war")
            if p.on < ended.since:
                raise FoldError(f"{p.war_id}: a war ends after it began")
            wars = {k: v for k, v in state.wars.items() if k != p.war_id}
            record = WarEnd(war=ended, on=p.on, agreement_id=p.agreement_id)
            return state.model_copy(
                update={"wars": wars, "ended_wars": (*state.ended_wars, record)}
            )
        case ev.MapDeclared():
            if state.map is not None:
                raise FoldError("the map is declared once")
            for area in p.map.areas():
                if _need(state.entities, area, "entity").kind is not EntityKind.LOCATION:
                    raise FoldError(f"area {area} is not a place")
            return state.model_copy(update={"map": p.map})
        case ev.AreaHeld():
            board = state.map
            if Rule.HOLDERS not in state.rules:
                raise FoldError("area_held: the holders rule is off")
            if board is None or p.area not in {t.area for t in board.territories}:
                raise FoldError(f"area_held: {p.area} is not a territory")
            if _need(state.entities, p.holder, "entity").kind is not EntityKind.POLITY:
                raise FoldError(f"area_held: {p.holder} is not a polity")
            if p.was != territory_holder(state, p.area) or p.was == p.holder:
                raise FoldError(f"area_held: {p.area} is not held by {p.was}, or not changing")
            holding = Holding(holder=p.holder, taken_from=p.was, on=p.on)
            captures = {k: v for k, v in state.captures.items() if k != p.area}
            return state.model_copy(
                update={"holders": _put(state.holders, p.area, holding), "captures": captures}
            )
        case ev.BattleOpened():
            return _battle_opened(state, p)
        case ev.BattleRound():
            fought = _open_battle(state, p.area, p.on, "battle_round")
            if fought.pressed_on is not None and p.on <= fought.pressed_on:
                raise FoldError(f"battle_round: {p.area} has had its round on {p.on}")
            fought = fought.model_copy(
                update={
                    "attacker": fought.attacker.model_copy(
                        update={"lost": fought.attacker.lost + p.lost[0]}
                    ),
                    "defender": fought.defender.model_copy(
                        update={"lost": fought.defender.lost + p.lost[1]}
                    ),
                    "rounds": fought.rounds + 1,
                    "pressed_on": p.on,
                }
            )
            return state.model_copy(update={"battles": _put(state.battles, p.area, fought)})
        case ev.BattleDecided():
            return _battle_decided(state, p)
        case ev.BattleEnded():
            fought = _open_battle(state, p.area, p.on, "battle_ended")
            if p.winner not in (fought.attacker.nation, fought.defender.nation):
                raise FoldError(f"battle_ended: {p.winner} fought no side at {p.area}")
            battles = {k: v for k, v in state.battles.items() if k != p.area}
            return state.model_copy(update={"battles": battles})
        case ev.CaptureCounted():
            board = state.map
            if Rule.HOLDERS not in state.rules:
                raise FoldError("capture_counted: the holders rule is off")
            if board is None or p.area not in {t.area for t in board.territories}:
                raise FoldError(f"capture_counted: {p.area} is not a territory")
            by = p.capture.by if p.capture is not None else None
            if by is not None and _need(state.entities, by, "entity").kind is not EntityKind.POLITY:
                raise FoldError(f"capture_counted: {by} is not a polity")
            captures = {k: v for k, v in state.captures.items() if k != p.area}
            if p.capture is not None:
                captures[p.area] = p.capture
            return state.model_copy(update={"captures": captures})
        case ev.EconomySet():
            if not economy.on(state):
                raise FoldError("economy_set: the economy rule is off")
            if _need(state.entities, p.polity, "entity").kind is not EntityKind.POLITY:
                raise FoldError(f"economy_set: {p.polity} is not a polity")
            pools = _put(state.economy.pools, p.polity, p.pools)
            return state.model_copy(
                update={"economy": state.economy.model_copy(update={"pools": pools})}
            )
        case ev.YieldChanged():
            why = economy.refusal(
                state, p.area, p.to, p.resource, p.amount, moved_on=p.on, restart=p.restart
            )
            if why is not None:
                raise FoldError(f"yield_changed: {why}")
            return state.model_copy(
                update={
                    "economy": economy.moved(
                        state, p.area, p.to, p.resource, p.amount, restart=p.restart
                    )
                }
            )
        case ev.TradeSet():
            why = trade.refusal(state, p.line)
            if why is not None:
                raise FoldError(f"trade_set: {why}")
            lines = {**state.economy.lines, p.line.key: p.line}
            return state.model_copy(
                update={"economy": state.economy.model_copy(update={"lines": lines})}
            )
        case ev.KindsDeclared():
            if state.kinds is not None:
                raise FoldError("the kinds are declared once")
            pieces = {k.key: k for k in p.pieces}
            resources = {r.key: r for r in p.resources}
            if len(pieces) < len(p.pieces) or len(resources) < len(p.resources):
                raise FoldError("a piece kind or resource is declared twice")
            for k in p.pieces:
                for lifted in k.carries:
                    if lifted not in pieces:
                        raise FoldError(f"piece kind {k.key}: carries unknown kind {lifted}")
            kinds = Kinds(pieces=pieces, resources=resources)
            return state.model_copy(update={"kinds": kinds})
        case ev.LocksDeclared():
            return _locks_declared(state, p)
        case ev.LawsDeclared():
            return _laws_declared(state, p)
        case ev.AimPatternsDeclared():
            return _aim_patterns_declared(state, p)
        case ev.OwnAimSet():
            return _own_aim_set(state, p)
        case ev.OrderHeld():
            return _order_held(state, p)
        case ev.HeldOrderEnded():
            return _held_order_ended(state, p)
        case ev.OrderAsked():
            return _order_asked(state, p)
        case ev.AskAnswered():
            return _ask_answered(state, p)
        case ev.OrderDefied():
            return _order_defied(state, p)
        case ev.IncidentOpened():
            return _incident_opened(state, p)
        case ev.IncidentAnswered():
            return _incident_answered(state, p)
        case ev.MatterChosen():
            return _matter_chosen(state, p)
        case ev.OfferMade():
            return _offer_made(state, p)
        case ev.OfferSettled():
            return _offer_settled(state, p)
        case ev.PostChanged():
            return _post_changed(state, p)
        case ev.LaddersDeclared():
            return _rebased(_ladders_declared(state, p), state.in_world_date)
        case ev.PostMoveOrdered():
            return _post_move_ordered(state, p)
        case ev.PostMoveSettled():
            return _post_move_settled(state, p)
        case ev.OfficeQuestionOpened():
            return _office_question_opened(state, p)
        case ev.OfficeChoiceFiled():
            return _office_choice_filed(state, p)
        case ev.OfficeQuestionDecided():
            return _office_question_decided(state, p)
        case ev.SeatsRedrawn():
            return _seats_redrawn(state, p)
        case ev.IntelligenceDeclared():
            if Rule.REPORTS not in state.rules:
                raise FoldError("intelligence_declared needs the reports rule")
            if state.intelligence:
                raise FoldError("intelligence is declared once")
            found: dict[EntityId, detect.Intelligence] = {}
            for intel in p.nations:
                _fresh(found, intel.nation, "intelligence")
                for entity in [intel.nation, *(s.person for s in intel.sources)]:
                    _need(state.entities, entity, "entity")
                for agent in intel.agents:
                    _need(state.entities, agent.area, "entity")
                found[intel.nation] = intel
            return state.model_copy(update={"intelligence": found})
        case ev.ReportMade():
            if Rule.REPORTS not in state.rules:
                raise FoldError("report_made needs the reports rule")
            _need(state.entities, p.nation, "entity")
            _need(state.features, p.piece, "feature")
            picture = detect.made(state.reports.get(p.nation, detect.Picture()), p.report)
            return state.model_copy(update={"reports": _put(state.reports, p.nation, picture)})
        case ev.AgentSet():
            if Rule.REPORTS not in state.rules:
                raise FoldError("agent_set needs the reports rule")
            _need(state.entities, p.agent.area, "entity")
            intel = state.intelligence.get(p.nation) or detect.Intelligence(nation=p.nation)
            agents = list(intel.agents)
            if p.index > len(agents):
                raise FoldError(f"agent_set: {p.nation} has no agent {p.index - 1}")
            agents[p.index : p.index + 1] = [p.agent]
            intel = intel.model_copy(update={"agents": tuple(agents)})
            return state.model_copy(
                update={"intelligence": _put(state.intelligence, p.nation, intel)}
            )
        case ev.CodebreakingSet():
            if Rule.REPORTS not in state.rules:
                raise FoldError("codebreaking_set needs the reports rule")
            intel = state.intelligence.get(p.nation) or detect.Intelligence(nation=p.nation)
            if p.level != intel.codebreaking + len(intel.raised) + 1:
                raise FoldError(f"codebreaking_set: {p.nation} is not raised to {p.level}")
            intel = intel.model_copy(update={"raised": (*intel.raised, p.on)})
            return state.model_copy(
                update={"intelligence": _put(state.intelligence, p.nation, intel)}
            )
        case ev.GroupsDeclared():
            return _rebased(_groups_declared(state, p), state.in_world_date)
        case ev.PieceStepped():
            return _piece_stepped(state, p)
        case ev.GroupMoved():
            return _rebased(_group_moved(state, p), p.on)
        case ev.GroupProposed():
            wrote = p.proposal
            if not groups.on(state):
                raise FoldError("group_proposed needs the groups rule")
            _need(state.seats, wrote.seat, "seat")
            if groups.group(state, wrote.polity, wrote.group) is None:
                raise FoldError(f"group_proposed: {wrote.polity} has no group {wrote.group}")
            g = state.groups.model_copy(update={"proposed": (*state.groups.proposed, wrote)})
            return state.model_copy(update={"groups": g})
        case ev.LossesHeld():
            return _losses_held(state, p)
        case (
            ev.AgreementOffered() | ev.AgreementMade() | ev.ClauseJudged() | ev.AgreementPublished()
        ):
            return _agreement_event(state, p)
        case ev.ConferenceCalled() | ev.VoteSealed() | ev.ConferenceTallied():
            return _conference_event(state, p)
        case ev.NewsReported():
            _fresh(state.news, p.news.news_id, "news")
            return state.model_copy(update={"news": _put(state.news, p.news.news_id, p.news)})
        case ev.StanceChanged():
            _need(state.seats, p.seat_id, "seat")
            _need(state.cards, p.figure, "card")
            held = state.stances.get(p.seat_id, {})
            past = held.get(p.figure, ())
            if past and (p.standing.on < past[-1].on or p.standing.stance is past[-1].stance):
                raise FoldError(f"stance of {p.figure}: not a change, or dated before the last")
            held = _put(held, p.figure, (*past, p.standing))
            return state.model_copy(update={"stances": _put(state.stances, p.seat_id, held)})
        case ev.CardAmended():
            card = _need(state.cards, p.person, "card")
            for entity in [*p.allies, *(x.against for x in p.opposes)]:
                _need(state.entities, entity, "entity")
            try:
                policy = {"allies": p.allies, "opposes": p.opposes, "answers": p.answers}
                late = {k: v for k in ("voice", "addressed_as") if (v := getattr(p, k)) is not None}
                amended = SeatCard.model_validate(card.model_dump() | policy | late)
            except ValidationError as exc:
                raise FoldError(f"card {p.person}: {exc.errors()[0]['msg']}") from None
            return state.model_copy(update={"cards": _put(state.cards, p.person, amended)})
        case ev.AnswerPlanned():
            card = _need(state.cards, p.figure, "card")
            if all(a.key != p.key for a in card.answers):
                raise FoldError(f"{p.figure} has no answer {p.key!r}")
            taken = state.answers.get(p.figure, {})
            last = taken.get(p.key)
            if last is not None and (last.made is None or p.on < last.planned):
                raise FoldError(f"answer {p.key} of {p.figure}: one is still to be made")
            log = AnswerLog(planned=p.on, due=p.due, cause=p.cause, toward=p.toward)
            return state.model_copy(
                update={"answers": _put(state.answers, p.figure, _put(taken, p.key, log))}
            )
        case ev.AnswerMade():
            taken = state.answers.get(p.figure, {})
            last = taken.get(p.key)
            if last is None or last.made is not None or p.on < last.due:
                raise FoldError(f"answer {p.key} of {p.figure}: nothing due to be made")
            if p.order is not None and p.order not in state.orders and p.order not in state.routed:
                raise FoldError(f"answer {p.key} of {p.figure}: no order {p.order}")
            if p.mandate is not None:
                _need(state.mandates, p.mandate, "mandate")
            made = last.model_copy(
                update={"made": p.on, "order": p.order, "mandate": p.mandate, "refusal": p.refusal}
            )
            return state.model_copy(
                update={"answers": _put(state.answers, p.figure, _put(taken, p.key, made))}
            )
        case ev.OpponentsRanked():
            _need(state.seats, p.seat_id, "seat")
            if len(set(p.active)) != len(p.active):
                raise FoldError(f"opponents of {p.seat_id}: a person is listed twice")
            for figure in p.active:
                _need(state.cards, figure, "card")
            return state.model_copy(
                update={"opponents": _put(state.opponents, p.seat_id, p.active)}
            )
        case _:
            raise FoldError(f"kind {p.kind!r} is not a realism record")


# --- engine v2 ------------------------------------------------------------------


def _check_effect(state: State, effect: EstimatedEffect, where: str, on: date | None) -> None:
    """Every object an effect names must already be in the world, and no force is
    used before it enters service on ``on`` (spec §8.3)."""
    match effect:
        case MoveForce():
            _in_service(_need(state.features, effect.force, "feature"), on, where)
            if effect.to is not None:
                if _need(state.entities, effect.to, "entity").kind is not EntityKind.LOCATION:
                    raise FoldError(f"{where}: {effect.to} is not a place")
        case SetEngagement():
            if effect.force is not None:
                _in_service(_need(state.features, effect.force, "feature"), on, where)
        case Allocate():
            _need(state.entities, effect.recipient, "entity")
        case Appointment():
            _need(state.entities, effect.person, "entity")
        case MakeStatement():
            if effect.audience is not None:
                _need(state.entities, effect.audience, "entity")
        case Investigate():
            _need(state.entities, effect.target, "entity")
        case Deal():
            _need(state.entities, effect.counterparty, "entity")
        case ShiftDisposition():
            _need(state.entities, effect.of, "entity")
            _need(state.entities, effect.toward, "entity")
        case Disclosure():
            _need(state.facts, effect.fact, "fact")
        case MoveFigure():
            q = _need(state.quantities, effect.quantity, "quantity")
            if not q.estimable or q.value is None:
                raise FoldError(f"{where}: {q.name} is not a figure that can be moved")
        case ProposeMeasure():
            pass


def _in_service(feature: Feature, on: date | None, where: str) -> None:
    if on is not None and feature.in_service is not None and on < feature.in_service:
        raise FoldError(f"{where}: {feature.name} is not in service until {feature.in_service}")


def _check_part(state: State, issuer: SeatId, part: RoutedPart, where: str, on: date) -> None:
    if part.fidelity is not None or part.refusal or part.estimated or part.was_estimated:
        raise FoldError(f"{where}: a part is routed before anyone acts on it")
    if part.effect is not None:
        _check_effect(state, part.effect, where, on)
    match part.route:
        case Route.COMMAND if agreement.is_publish(part):
            # The seat publishes an agreement itself: no office is needed (AGR rule 9).
            if part.domain != agreement.PUBLISH_DOMAIN or part.executor is not None:
                raise FoldError(f"{where}: a publishing order is the seat's own")
        case Route.COMMAND:
            card = state.cards.get(state.seats[issuer].embodies)
            domain = next(
                (dm for dm in (card.authority if card else ()) if dm.name == part.domain), None
            )
            if domain is None:
                raise FoldError(f"{where}: {part.domain!r} is not in the issuer's authority")
            if part.executor != domain.executor:
                raise FoldError(f"{where}: the {domain.name} domain is carried out by another")
            if part.effect is not None and EffectKind(part.effect.kind) not in domain.effects:
                raise FoldError(f"{where}: the {domain.name} domain does not cover that")
        case Route.PROCESS if part.pipeline is not None:
            _need(state.pipelines, part.pipeline, "pipeline")
        case Route.INFLUENCE if part.target is not None:
            _need(state.entities, part.target, "entity")


def _part_at(order: RoutedOrder, index: int) -> RoutedPart:
    if index >= len(order.parts):
        raise FoldError(f"order {order.order_id} has no part {index}")
    return order.parts[index]


def _with_part(state: State, order: RoutedOrder, index: int, part: RoutedPart) -> State:
    parts = (*order.parts[:index], part, *order.parts[index + 1 :])
    order = order.model_copy(update={"parts": parts})
    return state.model_copy(update={"routed": _put(state.routed, order.order_id, order)})


def _engine_v2(state: State, p: ev.Payload) -> State:
    """Store engine-v2 records: routed orders, the agenda, the wake, play styles."""
    match p:
        case ev.OrderRouted():
            o = p.order
            if o.order_id in state.orders:
                raise FoldError(f"duplicate order {o.order_id!r}")
            _fresh(state.routed, o.order_id, "order")
            _need(state.seats, o.issuer, "seat")
            for i, part in enumerate(o.parts):
                _check_part(state, o.issuer, part, f"order {o.order_id} part {i}", o.filed)
            return state.model_copy(update={"routed": _put(state.routed, o.order_id, o)})
        case ev.OrderExecuted():
            o = _need(state.routed, p.order_id, "order")
            part = _part_at(o, p.part)
            if part.route is not Route.COMMAND:
                raise FoldError(f"order {o.order_id} part {p.part} is not a command")
            if part.executed is not None:
                raise FoldError(f"order {o.order_id} part {p.part} is already executed")
            if p.on < o.filed:
                raise FoldError(f"order {o.order_id} is executed before it is filed")
            part = part.model_copy(
                update={"fidelity": p.fidelity, "refusal": p.refusal, "executed": p.on}
            )
            return _with_part(state, o, p.part, part)
        case ev.EffectsEstimated():
            o = _need(state.routed, p.order_id, "order")
            part = _part_at(o, p.part)
            if part.was_estimated:
                raise FoldError(f"order {o.order_id} part {p.part} is already estimated")
            for effect in p.effects:
                _check_effect(
                    state, effect, f"order {o.order_id} part {p.part}", state.in_world_date
                )
            part = part.model_copy(
                update={"estimated": p.effects, "reason": p.reason, "was_estimated": True}
            )
            return _with_part(state, o, p.part, part)
        case ev.EffectsApplied():
            o = _need(state.routed, p.order_id, "order")
            part = _part_at(o, p.part)
            where = f"order {o.order_id} part {p.part}"
            if part.applied is not None:
                raise FoldError(f"{where} is already applied")
            # A refused command applies nothing, but its being applied closes it.
            ready = (
                (part.route is Route.COMMAND and part.executed is not None)
                or part.was_estimated
                or (part.route is Route.INFLUENCE and part.decided is not None)
            )
            if not ready:
                raise FoldError(f"{where} is not ready to apply")
            if p.on < o.filed:
                raise FoldError(f"order {o.order_id} is applied before it is filed")
            facts = dict(state.facts)
            for fid in p.revealed:
                fact = _need(facts, fid, "fact")
                facts[fid] = fact.model_copy(update={"scope": PUBLIC})
            state = state.model_copy(update={"facts": facts})
            return _with_part(state, o, p.part, part.model_copy(update={"applied": p.on}))
        case ev.InfluenceDecided():
            o = _need(state.routed, p.order_id, "order")
            part = _part_at(o, p.part)
            if part.route is not Route.INFLUENCE:
                raise FoldError(f"order {o.order_id} part {p.part} is not influence")
            if part.decided is not None:
                raise FoldError(f"order {o.order_id} part {p.part} is already decided")
            part = part.model_copy(update={"decided": p.on, "accepted": p.accepted})
            return _with_part(state, o, p.part, part)
        case ev.RequestAnswered():
            o = _need(state.routed, p.order_id, "order")
            part = _part_at(o, p.part)
            if part.route is not Route.INFLUENCE:
                raise FoldError(f"order {o.order_id} part {p.part} is not influence")
            if part.decided is not None:
                raise FoldError(f"order {o.order_id} part {p.part} is already decided")
            part = part.model_copy(update={"held_answer": p.accepted})
            return _with_part(state, o, p.part, part)
        case ev.MandateIssued():
            m = p.mandate
            _fresh(state.mandates, m.mandate_id, "mandate")
            _need(state.seats, m.seat_id, "seat")
            if m.issuer is not None:
                _need(state.entities, m.issuer, "entity")
            if m.cause is not None and m.cause not in state.routed and m.cause not in state.orders:
                raise FoldError(f"mandate {m.mandate_id}: unknown order {m.cause!r}")
            if m.status is not MandateStatus.LIVE:
                raise FoldError(f"mandate {m.mandate_id} must start live")
            held_open = opening_id(state.campaign_id, m.seat_id)
            live = sum(
                1
                for x in state.mandates.values()
                if x.seat_id == m.seat_id
                and x.status is MandateStatus.LIVE
                and x.mandate_id != held_open
            )
            if m.mandate_id != held_open and live >= MANDATE_CAP:
                raise FoldError(f"seat {m.seat_id} already holds {MANDATE_CAP} live mandates")
            return state.model_copy(update={"mandates": _put(state.mandates, m.mandate_id, m)})
        case ev.MandateSettled():
            m = _need(state.mandates, p.mandate_id, "mandate")
            if m.status is not MandateStatus.LIVE:
                raise FoldError(f"mandate {m.mandate_id} is already settled")
            m = m.model_copy(update={"status": p.status})
            return state.model_copy(update={"mandates": _put(state.mandates, m.mandate_id, m)})
        case ev.WakeOpened():
            w = state.wake
            expected = 0 if w is None else w.number + 1
            if w is not None and not w.closed:
                raise FoldError(f"wake {w.number} is still open")
            if p.wake != expected:
                raise FoldError(f"wake {p.wake} opens out of turn: expected {expected}")
            return state.model_copy(update={"wake": Wake(number=p.wake, deadline=p.deadline)})
        case ev.WakeCommitted():
            w = _open_wake(state, p.wake)
            _need(state.seats, p.seat_id, "seat")
            if p.seat_id in w.committed:
                raise FoldError(f"seat {p.seat_id} has already committed in wake {p.wake}")
            w = w.model_copy(update={"committed": w.committed | {p.seat_id}})
            if Rule.REPORTS in state.rules and p.aide_orders:
                aided = state.aide_orders | frozenset(p.aide_orders)
                return state.model_copy(update={"wake": w, "aide_orders": aided})
            return state.model_copy(update={"wake": w})
        case ev.WakeClosed():
            w = _open_wake(state, p.wake)
            for seat in p.timed_out:
                _need(state.seats, seat, "seat")
            state = _hand_over(_aim_shut(state))
            return state.model_copy(update={"wake": w.model_copy(update={"closed": True})})
        case ev.PlayStyleSet():
            _need(state.seats, p.seat_id, "seat")
            if not p.standing <= IRREVERSIBLE:
                raise FoldError("a standing order names only irreversible kinds")
            return state.model_copy(
                update={
                    "styles": _put(state.styles, p.seat_id, p.style),
                    "standing": _put(state.standing, p.seat_id, p.standing),
                }
            )
        case ev.SeatHandover():
            if state.phase is not Phase.PLAY:
                raise FoldError("a leader changes hands only in play")
            _need(state.entities, p.entity_id, "entity")
            if controller_after(state, p.entity_id) is p.controller:
                raise FoldError(f"{p.entity_id} is already {p.controller.value}-run at the close")
            if p.controller is Controller.HUMAN:
                _need(state.cards, p.entity_id, "card")
                humans = {s.embodies for s in state.seats.values()} | set(state.handovers)
                after = [e for e in humans if controller_after(state, e) is Controller.HUMAN]
                if len(after) >= state.settings.max_human_seats:
                    raise FoldError("every human seat is taken")
            handovers = _put(state.handovers, p.entity_id, p.controller)
            if p.replaces is None:
                return state.model_copy(update={"handovers": handovers})
            _replacement(state, p.entity_id, p.replaces, p.controller)
            replaced = _put(state.replaced, p.entity_id, p.replaces)
            return state.model_copy(update={"handovers": handovers, "replaced": replaced})
        case _:
            raise FoldError(f"kind {p.kind!r} is not an engine-v2 record")


def _held_elsewhere(state: State, o: Order) -> bool:
    """The moving order waits at a decision step whose person a human seat other than
    its issuer embodies (``pipelines.held_by_another``, which the fold cannot import)."""
    steps = state.pipelines[o.pipeline].steps
    if o.status is not OrderStatus.MOVING or o.step >= len(steps):
        return False
    step = steps[o.step]
    return step.kind is StepKind.DECISION and any(
        s.embodies == step.person and s.controller is Controller.HUMAN and s.seat_id != o.issuer
        for s in state.seats.values()
    )


def _aim_goal(state: State, g: Goal, seat: Seat) -> None:
    """An aim's goal (AIM): made for a human seat holding its person, from an aim with a
    rule on the person's card, the aims rule on, and once per person and aim."""
    if not aims_on(state):
        raise FoldError("aims are not part of this game")
    if seat.embodies != g.person or seat.controller is not Controller.HUMAN:
        raise FoldError(f"goal {g.goal_id}: seat {seat.seat_id} is no player holding {g.person}")
    rule = aim_rule(state, g)
    if rule is None or rule.condition != g.condition:
        raise FoldError(f"goal {g.goal_id}: not an aim on {g.person}'s card")
    stand_in = g.person in state.replaced
    if stand_in != (g.source is GoalSource.REPLACEMENT):
        raise FoldError(
            f"goal {g.goal_id}: a replacement person's goals, and only his, are replacement"
        )
    card = state.cards[seat.embodies]
    if stand_in and g.aim not in replacement_aims(card.aim_rules, len(card.aims)):
        raise FoldError(f"goal {g.goal_id}: aim {g.aim} is not one a replacement person holds")
    if any(o.person == g.person and o.aim == g.aim for o in state.goals.values()):
        raise FoldError(f"goal {g.goal_id}: {g.person}'s aim {g.aim} already has a goal")


def _replacement(state: State, person: EntityId, old: EntityId, controller: Controller) -> None:
    """A player takes ``person`` in place of ``old`` (RPL): ``old`` can no longer act and
    is already handed to the code, has not himself replaced anyone this season, and
    ``person`` has the two aims he must hold."""
    if controller is not Controller.HUMAN:
        raise FoldError("replaces: only a player takes a replacement")
    if state.handovers.get(old) is not Controller.AI or not posts.needs_replacement(state, old):
        raise FoldError(f"replaces: {old} is not a person his player can no longer play")
    if old in state.replaced:
        raise FoldError(
            f"replaces: a seat is replaced once a season, and {old} was its replacement"
        )
    if old in state.replaced.values() or person in state.replaced.values():
        raise FoldError(f"replaces: {old} or {person} has been replaced already")
    card = state.cards[person]
    if not replacement_aims(card.aim_rules, len(card.aims)):
        raise FoldError(f"replaces: {person} has no two aims he must hold")


def _hand_over(state: State) -> State:
    """Apply the leaders' changes of hands at the close. A leaver's seat is run by the
    code and keeps its kind, so its orders stay in flight. A joiner takes the leader's
    seat, or a new one with the id a claim would give, and starts on Beginner, with none
    of the answers or step choices the leader's last player kept sealed."""
    seats, styles, standing = dict(state.seats), dict(state.styles), dict(state.standing)
    for person, controller in sorted(state.handovers.items()):
        seat = seat_of_person(state, person)
        if controller is Controller.AI:
            if seat is not None:
                seats[seat.seat_id] = seat.model_copy(update={"controller": Controller.AI})
            continue
        if seat is None:
            seat = Seat(
                seat_id=SeatId(derived_id(state.campaign_id, "seat", person)),
                kind=SeatKind.PLAYER,
                name=state.entities[person].name,
                embodies=person,
                slots=state.settings.starting_slots,
            )
        slots = seat.slots if seat.kind is SeatKind.PLAYER else state.settings.starting_slots
        seats[seat.seat_id] = seat.model_copy(
            update={
                "kind": SeatKind.PLAYER,
                "controller": Controller.HUMAN,
                "slots": slots,
                "joined_tick": state.tick,
            }
        )
        styles[seat.seat_id] = PlayStyle.BEGINNER
        standing.pop(seat.seat_id, None)
        state = _unsealed(state, person)
    return state.model_copy(
        update={"seats": seats, "styles": styles, "standing": standing, "handovers": {}}
    )


def _unsealed(state: State, person: EntityId) -> State:
    """``state`` without the answers to undecided requests at ``person`` and the choices
    at steps ``person`` holds that a last player kept sealed: a new player has given
    none, so the card decides on the due day unless they do."""
    routed = dict(state.routed)
    for oid, o in state.routed.items():
        parts = tuple(
            p.model_copy(update={"held_answer": None})
            if p.target == person and p.decided is None and p.held_answer is not None
            else p
            for p in o.parts
        )
        if parts != o.parts:
            routed[oid] = o.model_copy(update={"parts": parts})
    orders = dict(state.orders)
    for oid, order in state.orders.items():
        steps = state.pipelines[order.pipeline].steps
        if (
            order.held_choice is not None
            and order.step < len(steps)
            and steps[order.step].person == person
        ):
            orders[oid] = order.model_copy(update={"held_choice": None})
    return state.model_copy(update={"routed": routed, "orders": orders})


def _open_wake(state: State, number: int) -> Wake:
    w = state.wake
    if w is None or w.closed or w.number != number:
        raise FoldError(f"wake {number} is not open")
    return w


# --- deltas -------------------------------------------------------------------


def apply_delta(state: State, delta: d.Delta, tick: int) -> State:
    """Fold one delta as ``delta_applied`` at ``tick`` would. Raises ``FoldError`` if it cannot."""
    return _apply_delta(state, delta, tick)


def _apply_delta(state: State, delta: d.Delta, tick: int) -> State:
    match delta:
        case d.AssetTierDelta():
            a = _need(state.assets, delta.asset_id, "asset")
            a = a.model_copy(update={"tier": _clamp(a.tier + delta.change, 0, 5)})
            return state.model_copy(update={"assets": _put(state.assets, a.asset_id, a)})
        case d.AssetStatusSet():
            a = _need(state.assets, delta.asset_id, "asset")
            a = a.model_copy(update={"status": delta.status})
            return state.model_copy(update={"assets": _put(state.assets, a.asset_id, a)})
        case d.AssetControllerSet():
            a = _need(state.assets, delta.asset_id, "asset")
            _need(state.entities, delta.controller, "entity")
            a = a.model_copy(update={"controller": delta.controller})
            return state.model_copy(update={"assets": _put(state.assets, a.asset_id, a)})
        case d.AssetCreate():
            _fresh(state.assets, delta.asset_id, "asset")
            _need(state.entities, delta.controller, "entity")
            a = Asset(
                asset_id=delta.asset_id,
                kind=delta.asset_kind,
                name=delta.name,
                tier=delta.tier,
                controller=delta.controller,
                scope=delta.scope,
            )
            return state.model_copy(update={"assets": _put(state.assets, a.asset_id, a)})
        case d.MeterDelta():
            m = _need(state.meters, delta.meter_id, "meter")
            m = m.model_copy(update={"value": _clamp(m.value + delta.change, m.lo, m.hi)})
            return state.model_copy(update={"meters": _put(state.meters, m.meter_id, m)})
        case d.DispositionDelta():
            r = _need(state.relationships, delta.relationship_id, "relationship")
            r = r.model_copy(update={"disposition": _clamp(r.disposition + delta.change, -5, 5)})
            return state.model_copy(
                update={"relationships": _put(state.relationships, r.relationship_id, r)}
            )
        case d.RelationshipTagSet():
            r = _need(state.relationships, delta.relationship_id, "relationship")
            r = r.model_copy(
                update={
                    "price_tags": r.price_tags | delta.add_price,
                    "leverage_tags": (r.leverage_tags | delta.add_leverage) - delta.remove_leverage,
                }
            )
            return state.model_copy(
                update={"relationships": _put(state.relationships, r.relationship_id, r)}
            )
        case d.ClockAdvance():
            c = _need(state.clocks, delta.clock_id, "clock")
            filled = _clamp(c.segments_filled + delta.segments, 0, c.segments_total)
            status = c.status
            # Resolves on the tick the segment fills it, not the tick after.
            fills = c.segments_filled + delta.segments >= c.segments_total
            if status is ClockStatus.OPEN and fills:
                status = ClockStatus.RESOLVED
            c = c.model_copy(
                update={
                    "segments_filled": filled,
                    "status": status,
                    "holds_slot": c.holds_slot and status is ClockStatus.OPEN,
                }
            )
            return state.model_copy(update={"clocks": _put(state.clocks, c.clock_id, c)})
        case d.ClockCreate():
            _fresh(state.clocks, delta.clock_id, "clock")
            if delta.owner is not None:
                _need(state.seats, delta.owner, "seat")
            c = Clock(
                clock_id=delta.clock_id,
                kind=delta.clock_kind,
                name=delta.name,
                owner=delta.owner,
                target=delta.target,
                intent_id=delta.intent_id,
                segments_total=delta.segments_total,
                exposure=delta.exposure,
                opened_tick=tick,
                holds_slot=delta.clock_kind is ClockKind.OPERATION and delta.owner is not None,
                scope=delta.scope,
            )
            return state.model_copy(update={"clocks": _put(state.clocks, c.clock_id, c)})
        case d.ClockStatusSet():
            c = _need(state.clocks, delta.clock_id, "clock")
            c = c.model_copy(update={"status": delta.status, "holds_slot": False})
            return state.model_copy(update={"clocks": _put(state.clocks, c.clock_id, c)})
        case d.ClockExposureDelta():
            c = _need(state.clocks, delta.clock_id, "clock")
            c = c.model_copy(update={"exposure": _clamp(c.exposure + delta.change, 0, 5)})
            return state.model_copy(update={"clocks": _put(state.clocks, c.clock_id, c)})
        case d.FactAssert():
            _fresh(state.facts, delta.fact_id, "fact")
            _need(state.entities, delta.subject, "entity")
            f = Fact(
                fact_id=delta.fact_id,
                subject=delta.subject,
                predicate=delta.predicate,
                obj=delta.obj,
                truth=delta.truth,
                exposure=delta.exposure,
                asserted_tick=tick,
                scope=delta.scope,
            )
            return state.model_copy(update={"facts": _put(state.facts, f.fact_id, f)})
        case d.KnowledgeGrant():
            return _grant(state, delta)
        case d.EntityStatusSet():
            e = _need(state.entities, delta.entity_id, "entity")
            e = e.model_copy(update={"status": delta.status})
            return state.model_copy(update={"entities": _put(state.entities, e.entity_id, e)})
        case d.CommitmentCreate():
            _fresh(state.commitments, delta.commitment_id, "commitment")
            for party in delta.parties:
                _need(state.entities, party, "entity")
            c2 = Commitment(
                commitment_id=delta.commitment_id,
                parties=delta.parties,
                clauses=delta.clauses,
                scope=delta.scope,
            )
            return state.model_copy(
                update={"commitments": _put(state.commitments, c2.commitment_id, c2)}
            )
        case d.CommitmentStatusSet():
            c2 = _need(state.commitments, delta.commitment_id, "commitment")
            c2 = c2.model_copy(update={"status": CommitmentStatus(delta.status)})
            return state.model_copy(
                update={"commitments": _put(state.commitments, c2.commitment_id, c2)}
            )
        case d.ScheduledEventQueue():
            _fresh(state.scheduled, delta.scheduled_id, "scheduled event")
            s = ScheduledEvent(
                scheduled_id=delta.scheduled_id,
                fire_at_tick=tick + delta.fire_in_ticks,
                name=delta.name,
                source_clock=delta.source_clock,
                scope=delta.scope,
            )
            return state.model_copy(update={"scheduled": _put(state.scheduled, s.scheduled_id, s)})
        case d.SeatSlotsDelta():
            seat = _need(state.seats, delta.seat_id, "seat")
            cap = state.settings.slot_cap
            seat = seat.model_copy(update={"slots": _clamp(seat.slots + delta.change, 0, cap)})
            return state.model_copy(update={"seats": _put(state.seats, seat.seat_id, seat)})
        case _:
            raise FoldError(f"delta kind {delta.kind!r} has no fold case")


def _widen(scope: Scope, grant: d.KnowledgeGrant) -> Scope:
    return PUBLIC if grant.make_public else scope.grant(*grant.seats)


def _grant(state: State, grant: d.KnowledgeGrant) -> State:
    target = grant.target
    if target in state.facts:
        f = state.facts[target]  # type: ignore[index]
        f = f.model_copy(update={"scope": _widen(f.scope, grant)})
        return state.model_copy(update={"facts": _put(state.facts, f.fact_id, f)})
    if target in state.assets:
        a = state.assets[target]  # type: ignore[index]
        a = a.model_copy(update={"scope": _widen(a.scope, grant)})
        return state.model_copy(update={"assets": _put(state.assets, a.asset_id, a)})
    if target in state.clocks:
        c = state.clocks[target]  # type: ignore[index]
        c = c.model_copy(update={"scope": _widen(c.scope, grant)})
        return state.model_copy(update={"clocks": _put(state.clocks, c.clock_id, c)})
    if target in state.commitments:
        cm = state.commitments[target]  # type: ignore[index]
        cm = cm.model_copy(update={"scope": _widen(cm.scope, grant)})
        return state.model_copy(
            update={"commitments": _put(state.commitments, cm.commitment_id, cm)}
        )
    raise FoldError(f"knowledge grant target {target!r} is not a fact, asset, clock or commitment")
