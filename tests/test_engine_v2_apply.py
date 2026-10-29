"""Engine v2 wave B4: effects land in the world, and the order report (spec §8.3, §4 2.1).

A part is applied once it is ready; the effect lands as world events the fold already
knows, ``effects_applied`` closes it, and a private document tells the issuer how it went."""

import itertools
from datetime import date, timedelta
from unittest import mock

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FactId, FeatureId, OrderId, RelationshipId, derived_id
from revisionist.core.ontology import Relationship
from revisionist.core.realism import effect as rx
from revisionist.core.realism import reach
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.apply import REASON_WITHHELD, apply_due, as_carried, report
from revisionist.core.realism.geography import SPEED_KM_PER_DAY, Feature, km_between
from revisionist.core.realism.resolvers import movement
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, Visibility, private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.realism_tick import commit_order, run_realism_tick, seat_player
from revisionist.engine.store import MemoryStore, load_state
from tests.test_engine_v2_contract import CAMPAIGN, REASON_CANARY, Slice, _with_covert_fact

FILED = date(1941, 9, 11)
WORLD = "engine-v2-slice-1941"


@pytest.fixture
def sl() -> Slice:
    return Slice()


def shoot_effect(sl: Slice) -> rx.SetEngagement:
    return rx.SetEngagement(
        force=sl.feature("us_atlantic_fleet"),
        zone="western Atlantic",
        rule=rx.Engagement.SHOOT_ON_SIGHT,
    )


def land(sl: Slice, order: rx.RoutedOrder, today: date = FILED) -> list[ev.Payload]:
    """Apply what is due and fold it onto the slice, as the tick would."""
    out = apply_due(sl.state, today)
    for p in out:
        scope = p.document.scope if isinstance(p, ev.DocumentIssued) else private_to(sl.fdr)
        sl.add(p, scope if not isinstance(p, ev.FeatureSet | ev.RelationshipSet) else PUBLIC)
    return out


def executed(
    sl: Slice, order: rx.RoutedOrder, fidelity: rx.Fidelity | None, refusal: str = ""
) -> None:
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(
        ev.OrderExecuted(
            order_id=order.order_id, part=0, on=FILED, fidelity=fidelity, refusal=refusal
        ),
        private_to(sl.fdr),
    )


def fleet(sl: Slice) -> Feature:
    return sl.state.features[sl.feature("us_atlantic_fleet")]


# --- through the real entry points ------------------------------------------------


def play(loyalty: int = 2) -> tuple[State, OrderId]:
    """One run to the first wake, with order ids pinned so a rerun rolls the same dice."""
    ids = itertools.count()
    with mock.patch.object(
        realism_tick, "new_id", lambda: derived_id(CAMPAIGN, "b4-new-id", next(ids))
    ):
        return _play(loyalty)


def _play(loyalty: int) -> tuple[State, OrderId]:
    world = cmp.load_world(cmp.world_path(WORLD))
    cards = tuple(
        c.model_copy(update={"loyalty": loyalty}) if c.person == "stark" else c for c in world.cards
    )
    world = world.model_copy(update={"cards": cards})
    ids = resolve_keys(world, CAMPAIGN)
    store = MemoryStore()
    store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
    seat_player(store, CAMPAIGN, EntityId(ids["roosevelt"]))
    (seat,) = load_state(store, CAMPAIGN).seats
    order = commit_order(
        store,
        CAMPAIGN,
        seat,
        [
            Ask(
                ask="Shoot on sight.",
                effect=rx.SetEngagement(
                    force=FeatureId(ids["us_atlantic_fleet"]),
                    zone="western Atlantic",
                    rule=rx.Engagement.SHOOT_ON_SIGHT,
                ),
            )
        ],
    )
    run_realism_tick(store, CAMPAIGN)
    return load_state(store, CAMPAIGN), order.order_id


def test_shoot_on_sight_lands_and_is_reported() -> None:
    state, oid = play(2)
    fid = next(f for f in state.features.values() if f.name == "US Atlantic Fleet")
    part = state.routed[oid].parts[0]
    assert part.executed is not None and part.applied is not None
    assert fid.engagement is rx.Engagement.SHOOT_ON_SIGHT
    (seat,) = state.seats
    docs = [
        d
        for d in state.documents.values()
        if d.view.doc_id == derived_id(CAMPAIGN, "report", oid, 0)
    ]
    assert len(docs) == 1
    view = docs[0].view
    assert view.scope == private_to(seat)
    assert view.title == "Shoot on sight in western Atlantic: carried out"
    assert "_" not in view.title
    channel = reach.channels_to(state, state.seats[seat].embodies, view.author)[0]
    assert view.channel is channel
    assert view.arrives == view.issued + timedelta(days=reach.transit_days(channel))


def test_replay_reaches_the_same_hash() -> None:
    a, _ = play(2)
    b, _ = play(2)
    assert a.model_dump_json() == b.model_dump_json()


# --- fidelity ---------------------------------------------------------------------


def test_loose_turns_shoot_on_sight_into_defend(sl: Slice) -> None:
    order = sl.shoot_on_sight()
    executed(sl, order, rx.Fidelity.LOOSE)
    land(sl, order)
    assert fleet(sl).engagement is rx.Engagement.DEFEND
    assert sl.state.routed[order.order_id].parts[0].applied == FILED


def test_as_carried_table(sl: Slice) -> None:
    f = sl.feature("us_atlantic_fleet")
    move = rx.MoveForce(force=f, to=sl.entity("argentia"), posture=rx.Posture.ESCORT)
    assert as_carried(move, rx.Fidelity.FULL) == move
    assert as_carried(move, rx.Fidelity.SLOW) == move
    assert as_carried(move, rx.Fidelity.LOOSE) == move.model_copy(update={"posture": None})
    assert as_carried(move, rx.Fidelity.PARTIAL) == move.model_copy(update={"to": None})
    only = rx.MoveForce(force=f, to=sl.entity("argentia"))
    assert as_carried(only, rx.Fidelity.PARTIAL) is None
    pose = rx.MoveForce(force=f, posture=rx.Posture.HOLD)
    assert as_carried(pose, rx.Fidelity.LOOSE) is None
    cash = rx.Allocate(recipient=sl.entity("uk"), what="tonnage", amount=7, unit="tons")
    assert as_carried(cash, rx.Fidelity.PARTIAL) == cash.model_copy(update={"amount": 3})
    assert as_carried(cash, rx.Fidelity.LOOSE) == cash


def test_partial_move_keeps_the_force_in_place_with_the_posture(sl: Slice) -> None:
    move = rx.MoveForce(
        force=sl.feature("us_atlantic_fleet"), to=sl.entity("argentia"), posture=rx.Posture.ESCORT
    )
    order = sl.shoot_on_sight(effect=move)
    executed(sl, order, rx.Fidelity.PARTIAL)
    land(sl, order)
    ft = sl.state.features[sl.feature("us_atlantic_fleet")]
    assert ft.posture is rx.Posture.ESCORT and ft.bound_for is None
    assert ft.places == (sl.entity("norfolk"),)


def test_a_refusal_applies_nothing_and_names_the_rule(sl: Slice) -> None:
    order = sl.shoot_on_sight()
    executed(sl, order, None, refusal="loyalty -4: Stark will not carry it out")
    out = land(sl, order)
    assert [type(p) for p in out] == [ev.EffectsApplied, ev.DocumentIssued]
    assert fleet(sl).engagement is None
    doc = out[1]
    assert isinstance(doc, ev.DocumentIssued)
    assert doc.document.title.endswith(": refused")
    assert any(b.value == "loyalty -4: Stark will not carry it out" for b in doc.document.body)


# --- moving a force ---------------------------------------------------------------


def test_a_move_sets_the_voyage_as_the_movement_resolver_would(sl: Slice) -> None:
    f, argentia = sl.feature("us_atlantic_fleet"), sl.entity("argentia")
    order = sl.shoot_on_sight(effect=rx.MoveForce(force=f, to=argentia))
    executed(sl, order, rx.Fidelity.FULL)
    land(sl, order)
    ft = sl.state.features[f]
    origin = sl.state.entities[sl.entity("norfolk")].at
    dest = sl.state.entities[argentia].at
    assert origin is not None and dest is not None
    days = max(1, -(-km_between(origin, dest) // SPEED_KM_PER_DAY[ft.kind]))
    assert ft.bound_for == argentia and ft.arrives == FILED + timedelta(days=int(days))
    assert ft.places == (sl.entity("norfolk"),)
    (arrived,) = movement.on_day(sl.state, ft.arrives)
    assert arrived.places == (argentia,) and arrived.bound_for is None


def test_a_force_sent_where_it_is_only_changes_posture(sl: Slice) -> None:
    f = sl.feature("us_atlantic_fleet")
    move = rx.MoveForce(force=f, to=sl.entity("norfolk"), posture=rx.Posture.PATROL)
    order = sl.shoot_on_sight(effect=move)
    executed(sl, order, rx.Fidelity.FULL)
    land(sl, order)
    ft = sl.state.features[f]
    assert ft.posture is rx.Posture.PATROL and ft.bound_for is None


# --- estimated and influence parts ------------------------------------------------


def estimated(sl: Slice, *effects: rx.Effect, reason: str = "It will sour him.") -> rx.RoutedOrder:
    order = sl.shoot_on_sight(effect=None)
    executed(sl, order, rx.Fidelity.FULL)
    sl.add(
        ev.EffectsEstimated(order_id=order.order_id, part=0, effects=effects, reason=reason),
        private_to(sl.fdr),
    )
    return order


def test_an_estimated_shift_creates_then_moves_then_clamps(sl: Slice) -> None:
    shift = rx.ShiftDisposition(of=sl.entity("wheeler"), toward=sl.entity("roosevelt"), change=2)
    order = estimated(sl, shift)
    land(sl, order)
    rid = RelationshipId(derived_id(CAMPAIGN, "rel", sl.entity("wheeler"), sl.entity("roosevelt")))
    rel = sl.state.relationships[rid]
    assert rel.disposition == 2 and rel.scope == private_to(sl.fdr)
    # a second order moves the same relationship, from the other side, clamped at 5
    for n in (2, 3):
        o = sl.shoot_on_sight(
            n,
            effect=None,
        )
        sl.add(ev.OrderRouted(order=o), private_to(sl.fdr))
        sl.add(ev.OrderExecuted(order_id=o.order_id, part=0, on=FILED, fidelity=rx.Fidelity.FULL))
        back = shift.model_copy(update={"of": shift.toward, "toward": shift.of})
        sl.add(ev.EffectsEstimated(order_id=o.order_id, part=0, effects=(back,), reason="Yes."))
    land(sl, order)
    assert sl.state.relationships[rid].disposition == 5
    assert len([r for r in sl.state.relationships.values() if rid == r.relationship_id]) == 1


def test_an_existing_relationship_is_moved_in_either_order(sl: Slice) -> None:
    a, b = sl.entity("wheeler"), sl.entity("roosevelt")
    rid = RelationshipId(derived_id(CAMPAIGN, "rel", "old"))
    sl.add(
        ev.RelationshipSet(
            relationship=Relationship(relationship_id=rid, a=b, b=a, disposition=-4, scope=PUBLIC)
        )
    )
    order = estimated(sl, rx.ShiftDisposition(of=a, toward=b, change=-2))
    land(sl, order)
    assert sl.state.relationships[rid].disposition == -5
    assert len(sl.state.relationships) == 1


def test_a_disclosure_makes_the_fact_public(sl: Slice) -> None:
    _with_covert_fact(sl)
    fid = FactId(derived_id(CAMPAIGN, "fact", "covert"))
    order = estimated(sl, rx.Disclosure(fact=fid))
    out = land(sl, order)
    applied = next(p for p in out if isinstance(p, ev.EffectsApplied))
    assert applied.revealed == (fid,)
    assert sl.state.facts[fid].scope.visibility is Visibility.PUBLIC


def influence(sl: Slice, accepted: bool, effect: rx.Effect | None = None) -> rx.RoutedOrder:
    part = rx.RoutedPart(route=rx.Route.INFLUENCE, target=sl.entity("wheeler"), effect=effect)
    order = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "inf")), issuer=sl.fdr, filed=FILED, parts=(part,)
    )
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    return order


def test_a_rebuffed_approach_lands_only_the_souring(sl: Slice) -> None:
    sour = rx.ShiftDisposition(of=sl.entity("wheeler"), toward=sl.entity("roosevelt"), change=-1)
    order = influence(sl, False)
    sl.add(
        ev.EffectsEstimated(order_id=order.order_id, part=0, effects=(sour,), reason="He bristles.")
    )
    sl.add(ev.InfluenceDecided(order_id=order.order_id, part=0, on=FILED, accepted=False))
    out = land(sl, order)
    assert sum(isinstance(p, ev.RelationshipSet) for p in out) == 1
    doc = next(p for p in out if isinstance(p, ev.DocumentIssued))
    assert doc.document.title == "Your approach to Burton K. Wheeler: rebuffed"
    assert doc.document.kind.value == "letter" and doc.document.author == sl.entity("wheeler")


def test_an_accepted_approach_lands_its_effect(sl: Slice) -> None:
    order = influence(sl, True, shoot_effect(sl))
    sl.add(ev.EffectsEstimated(order_id=order.order_id, part=0, reason="Fine."))
    sl.add(ev.InfluenceDecided(order_id=order.order_id, part=0, on=FILED, accepted=True))
    land(sl, order)
    assert fleet(sl).engagement is rx.Engagement.SHOOT_ON_SIGHT


# --- once, leak-safe --------------------------------------------------------------


def test_every_part_is_applied_once(sl: Slice) -> None:
    order = sl.shoot_on_sight()
    executed(sl, order, rx.Fidelity.FULL)
    assert len([p for p in land(sl, order) if isinstance(p, ev.EffectsApplied)]) == 1
    assert apply_due(sl.state, FILED + timedelta(days=3)) == []


def test_a_part_not_ready_or_in_a_process_is_left_alone(sl: Slice) -> None:
    order = sl.shoot_on_sight()
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    assert apply_due(sl.state, FILED) == []


def test_the_report_holds_no_rationale_and_no_canary(sl: Slice) -> None:
    _with_covert_fact(sl)
    order = sl.shoot_on_sight(effect=None)
    executed(sl, order, rx.Fidelity.FULL)
    sl.add(
        ev.EffectsEstimated(
            order_id=order.order_id,
            part=0,
            reason=f"Wheeler is compromised ({REASON_CANARY}).",
            rationale="The referee's private rationale.",
        ),
        private_to(sl.fdr),
    )
    out = land(sl, order)
    doc = next(p for p in out if isinstance(p, ev.DocumentIssued))
    text = doc.document.model_dump_json()
    assert REASON_CANARY not in text and "private rationale" not in text
    assert REASON_WITHHELD in text


def test_report_is_none_for_a_missing_part(sl: Slice) -> None:
    order = sl.shoot_on_sight()
    assert report(sl.state, order, 3, FILED) is None
