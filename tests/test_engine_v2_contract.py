"""Engine v2 contract (remediation plan, Phase 1): the new records store, project,
scan and seal as specified, and an older log hashes as it did before they existed.

No behaviour is tested here: nothing routes, executes, estimates or issues yet.
These tests pin the shapes and the fold's guards that Phase 2 builds on.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.canary import scan, surfaces_from_log
from revisionist.core.fold import FoldError, replay
from revisionist.core.goals import EntityIs
from revisionist.core.ids import (
    CampaignId,
    EntityId,
    EventId,
    FactId,
    FeatureId,
    MandateId,
    OrderId,
    SeatId,
    derived_id,
)
from revisionist.core.ontology import EntityStatus, Fact
from revisionist.core.project import project
from revisionist.core.realism import agenda as ra
from revisionist.core.realism import effect as rx
from revisionist.core.sealing import needs_admin_read, seal_holder
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, Scope, Visibility, private_to
from revisionist.core.world_compile import WorldError, compile_world, resolve_keys
from revisionist.engine import campaign as cmp

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
DEADLINE = datetime(2026, 11, 1, 12, tzinfo=UTC)
REASON_CANARY = "CANARY-V2-REASON-7f3a"
MANDATE_CANARY = "CANARY-V2-MANDATE-0b9e"


class Slice:
    """The engine-v2 slice compiled, Roosevelt and Wheeler claimed."""

    def __init__(self) -> None:
        world = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
        self.ids = resolve_keys(world, CAMPAIGN)
        self.events = compile_world(world, CAMPAIGN, cmp.versions())
        self.fdr = SeatId(derived_id(CAMPAIGN, "seat", "roosevelt"))
        self.wheeler = SeatId(derived_id(CAMPAIGN, "seat", "wheeler"))
        self.add(ev.CharacterClaimed(seat_id=self.fdr, entity_id=self.entity("roosevelt")))
        self.add(ev.CharacterClaimed(seat_id=self.wheeler, entity_id=self.entity("wheeler")))
        self.add(ev.SessionZeroClosed())

    def entity(self, key: str) -> EntityId:
        return EntityId(self.ids[key])

    def feature(self, key: str) -> FeatureId:
        return FeatureId(self.ids[key])

    def add(self, payload: ev.Payload, scope: Scope = PUBLIC) -> ev.Event:
        seq = len(self.events)
        e = ev.Event(
            event_id=EventId(derived_id(CAMPAIGN, "v2-event", seq)),
            campaign_id=CAMPAIGN,
            seq=seq,
            tick=0,
            scope=scope,
            payload=payload,
            versions=cmp.versions(),
        )
        self.events.append(e)
        return e

    @property
    def state(self) -> State:
        return replay(self.events)

    def shoot_on_sight(self, n: int = 1, **part: object) -> rx.RoutedOrder:
        fields: dict[str, object] = {
            "route": rx.Route.COMMAND,
            "domain": "naval_operations",
            "executor": self.entity("stark"),
            "effect": rx.SetEngagement(
                force=self.feature("us_atlantic_fleet"),
                zone="western Atlantic",
                rule=rx.Engagement.SHOOT_ON_SIGHT,
            ),
        }
        return rx.RoutedOrder(
            order_id=OrderId(derived_id(CAMPAIGN, "v2-order", n)),
            issuer=self.fdr,
            filed=date(1941, 9, 11),
            parts=(rx.RoutedPart.model_validate(fields | part),),
        )

    def mandate(self, n: int, seat: SeatId, **changes: object) -> ra.Mandate:
        fields: dict[str, object] = {
            "mandate_id": MandateId(derived_id(CAMPAIGN, "mandate", n)),
            "seat_id": seat,
            "kind": ra.MandateKind.CRISIS,
            "text": "Keep the convoys moving.",
            "condition": EntityIs(entity=self.entity("usa"), status=EntityStatus.ACTIVE),
            "issued": date(1941, 9, 11),
            "expires": date(1941, 10, 11),
            "scope": private_to(seat),
        }
        return ra.Mandate.model_validate(fields | changes)


@pytest.fixture
def sl() -> Slice:
    return Slice()


def _refused(sl: Slice, payload: ev.Payload, match: str, scope: Scope = PUBLIC) -> None:
    sl.add(payload, scope)
    with pytest.raises(FoldError, match=match):
        _ = sl.state
    sl.events.pop()


# --- the slice and the card -----------------------------------------------------


def test_the_slice_compiles_with_authority_and_reach(sl: Slice) -> None:
    state = sl.state
    assert state.ruleset == "realism" and len(state.cards) == 4
    fdr = state.cards[sl.entity("roosevelt")]
    naval = next(d for d in fdr.authority if d.name == "naval_operations")
    assert naval.executor == sl.entity("stark")
    assert naval.effects == {rx.EffectKind.MOVE_FORCE, rx.EffectKind.ENGAGEMENT}
    assert naval.forces == (sl.feature("us_atlantic_fleet"),)
    assert fdr.reach.rank == 5 and fdr.reach.heads
    assert [c.person for c in fdr.inner_circle] == [sl.entity("stark"), sl.entity("rayburn")]


def test_a_domain_must_name_people_and_forces_in_the_world() -> None:
    world = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
    fdr = world.cards[0]
    bad = fdr.authority[0].model_copy(update={"executor": "nobody", "forces": ("no_fleet",)})
    twice = (bad, bad.model_copy(update={"executor": "stark", "forces": ()}))
    cards = (fdr.model_copy(update={"authority": twice}), *world.cards[1:])
    with pytest.raises(WorldError) as err:
        compile_world(world.model_copy(update={"cards": cards}), CAMPAIGN, cmp.versions())
    text = str(err.value)
    assert "nobody" in text and "no_fleet" in text and "named twice" in text


def test_older_cards_hash_as_before_authority_existed(sl: Slice) -> None:
    """An empty authority and the default reach leave a card's dump unchanged."""
    card = sl.state.cards[sl.entity("rayburn")].model_copy(update={"authority": ()})
    card = card.model_copy(update={"reach": type(card.reach)()})
    dump = card.model_dump(mode="json")
    assert "authority" not in dump and "reach" not in dump


def test_a_force_is_not_used_before_it_enters_service(sl: Slice) -> None:
    """Spec §8.3: no capability before its date. Checked when the order is routed
    and when an estimate names the force."""
    fleet = sl.state.features[sl.feature("us_atlantic_fleet")]
    later = fleet.model_copy(update={"in_service": date(1941, 12, 1)})
    sl.add(ev.FeatureSet(feature=later))
    _refused(sl, ev.OrderRouted(order=sl.shoot_on_sight()), "not in service until")
    sl.add(ev.FeatureSet(feature=later.model_copy(update={"in_service": date(1941, 9, 11)})))
    sl.add(ev.OrderRouted(order=sl.shoot_on_sight()), private_to(sl.fdr))


def test_engine_v2_late_fields_leave_older_dumps_unchanged(sl: Slice) -> None:
    fleet = sl.state.features[sl.feature("us_atlantic_fleet")]
    card = sl.state.cards[sl.entity("stark")]
    assert "in_service" not in fleet.model_dump(mode="json")
    assert "competence" not in card.model_dump(mode="json")
    assert "target" not in ra.Ask(ask="x").model_dump(mode="json")
    assert card.competence == 3


def test_a_routing_is_a_part_or_a_refusal(sl: Slice) -> None:
    part = sl.shoot_on_sight().parts[0]
    assert rx.Routing(part=part).part == part
    assert rx.Routing(refusal="Nobody under you commands that.").part is None
    with pytest.raises(ValidationError):
        rx.Routing()
    with pytest.raises(ValidationError):
        rx.Routing(part=part, refusal="both")


def test_fidelity_inputs_hold_the_card_ranges() -> None:
    rx.FidelityInputs(loyalty=-5, competence=0, workload=0)
    with pytest.raises(ValidationError):
        rx.FidelityInputs(loyalty=0, competence=6, workload=0)
    with pytest.raises(ValidationError):
        rx.FidelityInputs(loyalty=0, competence=3, workload=-1)


# --- effects and parts ----------------------------------------------------------


def test_the_effect_vocabulary_is_closed_and_bounded() -> None:
    kinds = {cls.model_fields["kind"].default for cls in rx.Effect.__args__[0].__args__}
    assert kinds == {k.value for k in rx.EffectKind}
    e, f = EntityId(derived_id("e")), EntityId(derived_id("f"))
    rx.ShiftDisposition(of=e, toward=f, change=rx.DISPOSITION_CAP)
    for change in (0, rx.DISPOSITION_CAP + 1, -rx.DISPOSITION_CAP - 1):
        with pytest.raises(ValidationError):
            rx.ShiftDisposition(of=e, toward=f, change=change)
    with pytest.raises(ValidationError, match="amount"):
        rx.Clause(kind=rx.ClauseKind.MONEY, subject="Lend-Lease")
    with pytest.raises(ValidationError, match="moves the force or postures it"):
        rx.MoveForce(force=FeatureId(derived_id("fleet")))


def test_a_part_names_what_its_route_needs_and_nothing_else() -> None:
    who = EntityId(derived_id("who"))
    with pytest.raises(ValidationError, match="names its domain"):
        rx.PartView(route=rx.Route.COMMAND)
    with pytest.raises(ValidationError, match="names only"):
        rx.PartView(route=rx.Route.INFLUENCE, target=who, executor=who)
    with pytest.raises(ValidationError, match="only a command is executed"):
        rx.PartView(
            route=rx.Route.INFLUENCE,
            target=who,
            fidelity=rx.Fidelity.FULL,
            executed=date(1941, 9, 1),
        )
    with pytest.raises(ValidationError, match="its date"):
        rx.PartView(route=rx.Route.COMMAND, domain="x", fidelity=rx.Fidelity.FULL)
    rx.PartView(route=rx.Route.COMMAND, domain="public_word")  # the seat acts itself


# --- the fold -------------------------------------------------------------------


def test_a_command_inside_authority_is_routed_and_executed(sl: Slice) -> None:
    order = sl.shoot_on_sight()
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(
        ev.OrderExecuted(
            order_id=order.order_id, part=0, on=date(1941, 9, 12), fidelity=rx.Fidelity.FULL
        ),
        private_to(sl.fdr),
    )
    part = sl.state.routed[order.order_id].parts[0]
    assert part.fidelity is rx.Fidelity.FULL and part.executed == date(1941, 9, 12)
    _refused(
        sl,
        ev.OrderExecuted(
            order_id=order.order_id, part=0, on=date(1941, 9, 13), refusal="loyalty -4"
        ),
        "already executed",
    )


def test_a_command_outside_authority_is_refused_by_the_fold(sl: Slice) -> None:
    statement = rx.MakeStatement(theme="freedom of the seas")
    _refused(sl, ev.OrderRouted(order=sl.shoot_on_sight(domain="war_powers")), "not in the")
    _refused(sl, ev.OrderRouted(order=sl.shoot_on_sight(executor=sl.entity("rayburn"))), "another")
    _refused(sl, ev.OrderRouted(order=sl.shoot_on_sight(effect=statement)), "does not cover")
    strange = rx.MoveForce(force=FeatureId(derived_id("ghost")), posture=rx.Posture.HOLD)
    _refused(sl, ev.OrderRouted(order=sl.shoot_on_sight(effect=strange)), "unknown feature")


def test_a_process_and_an_influence_part_name_real_objects(sl: Slice) -> None:
    order = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "v2-order", 9)),
        issuer=sl.fdr,
        filed=date(1941, 9, 11),
        parts=(
            rx.RoutedPart(
                route=rx.Route.PROCESS,
                pipeline=sl.state.cards[sl.entity("roosevelt")].pipelines[0],
                effect=rx.ProposeMeasure(
                    title="Neutrality revision",
                    clauses=(rx.Clause(kind=rx.ClauseKind.POWER, subject="arm merchant ships"),),
                ),
            ),
            rx.RoutedPart(route=rx.Route.INFLUENCE, target=sl.entity("wheeler")),
        ),
    )
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    assert len(sl.state.routed[order.order_id].parts) == 2
    _refused(
        sl,
        ev.OrderExecuted(
            order_id=order.order_id, part=1, on=date(1941, 9, 12), fidelity=rx.Fidelity.FULL
        ),
        "not a command",
    )


def test_an_estimate_lands_once_and_names_only_objects_in_the_world(sl: Slice) -> None:
    order = sl.shoot_on_sight(effect=None)
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    shift = rx.ShiftDisposition(of=sl.entity("wheeler"), toward=sl.entity("roosevelt"), change=-1)
    sl.add(
        ev.EffectsEstimated(
            order_id=order.order_id, part=0, effects=(shift,), reason="The Senate will notice."
        )
    )
    part = sl.state.routed[order.order_id].parts[0]
    assert part.estimated == (shift,) and part.was_estimated
    assert part.reason == "The Senate will notice."
    again = ev.EffectsEstimated(order_id=order.order_id, part=0, failed=True)
    _refused(sl, again, "already estimated")


def test_a_failed_estimate_is_recorded_and_carries_no_effects(sl: Slice) -> None:
    order = sl.shoot_on_sight(effect=None)
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(ev.EffectsEstimated(order_id=order.order_id, part=0, failed=True))
    part = sl.state.routed[order.order_id].parts[0]
    assert part.was_estimated and part.estimated == ()
    with pytest.raises(ValidationError):
        ev.EffectsEstimated(
            order_id=order.order_id,
            part=0,
            failed=True,
            effects=(rx.MakeStatement(theme="x"),),
        )
    with pytest.raises(ValidationError, match="reason"):
        ev.EffectsEstimated(order_id=order.order_id, part=0)


def test_a_seat_holds_at_most_three_live_mandates(sl: Slice) -> None:
    for n in range(ra.MANDATE_CAP):
        sl.add(ev.MandateIssued(mandate=sl.mandate(n, sl.fdr)), private_to(sl.fdr))
    _refused(sl, ev.MandateIssued(mandate=sl.mandate(9, sl.fdr)), "already holds 3")
    first = MandateId(derived_id(CAMPAIGN, "mandate", 0))
    sl.add(ev.MandateSettled(mandate_id=first, status=ra.MandateStatus.MET))
    sl.add(ev.MandateIssued(mandate=sl.mandate(9, sl.fdr)), private_to(sl.fdr))
    assert sum(m.status is ra.MandateStatus.LIVE for m in sl.state.mandates.values()) == 3
    _refused(sl, ev.MandateSettled(mandate_id=first, status=ra.MandateStatus.FAILED), "settled")


def test_mandate_kinds_carry_their_issuer_and_cause() -> None:
    sl = Slice()
    with pytest.raises(ValidationError, match="has an issuer"):
        sl.mandate(1, sl.fdr, kind=ra.MandateKind.ORDER)
    with pytest.raises(ValidationError, match="has a cause"):
        sl.mandate(1, sl.fdr, kind=ra.MandateKind.BLOWBACK)
    with pytest.raises(ValidationError, match="expires after"):
        sl.mandate(1, sl.fdr, expires=date(1941, 9, 11))
    stray = sl.mandate(
        1, sl.fdr, kind=ra.MandateKind.BLOWBACK, cause=OrderId(derived_id("no-such-order"))
    )
    _refused(sl, ev.MandateIssued(mandate=stray), "unknown order")


def test_the_shared_wake_opens_commits_and_closes_in_turn(sl: Slice) -> None:
    _refused(sl, ev.WakeOpened(wake=1, deadline=DEADLINE), "out of turn")
    sl.add(ev.WakeOpened(wake=0, deadline=DEADLINE))
    _refused(sl, ev.WakeOpened(wake=1, deadline=DEADLINE), "still open")
    sl.add(ev.WakeCommitted(wake=0, seat_id=sl.fdr))
    _refused(sl, ev.WakeCommitted(wake=0, seat_id=sl.fdr), "already committed")
    sl.add(ev.WakeCommitted(wake=0, seat_id=sl.wheeler, by_aide=True))
    sl.add(ev.WakeClosed(wake=0, timed_out=(sl.wheeler,)))
    wake = sl.state.wake
    assert wake is not None and wake.closed and wake.committed == {sl.fdr, sl.wheeler}
    _refused(sl, ev.WakeCommitted(wake=0, seat_id=sl.fdr), "not open")
    sl.add(ev.WakeOpened(wake=1, deadline=DEADLINE + timedelta(hours=12)))
    assert sl.state.wake == type(wake)(number=1, deadline=DEADLINE + timedelta(hours=12))


def test_a_play_style_and_standing_orders_are_stored(sl: Slice) -> None:
    style = ev.PlayStyleSet(
        seat_id=sl.fdr,
        style=ra.PlayStyle.BEGINNER,
        standing=frozenset({rx.EffectKind.APPOINTMENT}),
    )
    sl.add(style, private_to(sl.fdr))
    assert sl.state.styles[sl.fdr] is ra.PlayStyle.BEGINNER
    assert sl.state.standing[sl.fdr] == {rx.EffectKind.APPOINTMENT}
    reversible = ev.PlayStyleSet(
        seat_id=sl.fdr, style=ra.PlayStyle.FREE, standing=frozenset({rx.EffectKind.STATEMENT})
    )
    _refused(sl, reversible, "only irreversible")


def test_engine_v2_records_are_refused_in_a_legacy_campaign() -> None:
    legacy = compile_world(cmp.load_world(cmp.world_path("salt-strait")), CAMPAIGN, cmp.versions())
    stray = legacy[-1].model_copy(
        update={
            "seq": len(legacy),
            "event_id": EventId(derived_id(CAMPAIGN, "stray-v2")),
            "payload": ev.WakeOpened(wake=0, deadline=DEADLINE),
        }
    )
    with pytest.raises(FoldError, match="realism campaign"):
        replay([*legacy, stray])


# --- offers ---------------------------------------------------------------------


def _option(n: int, *, asks: int = 1, historical: bool = False) -> ra.Option:
    return ra.Option(
        label=f"option {n}",
        asks=tuple(ra.Ask(ask=f"ask {i}") for i in range(asks)),
        historical=historical,
    )


def test_offers_have_the_shape_each_style_promises() -> None:
    ra.Offer(style=ra.PlayStyle.BEGINNER, options=tuple(_option(n) for n in range(3)))
    ra.Offer(style=ra.PlayStyle.GUIDED, options=(_option(0, asks=4),))
    with pytest.raises(ValidationError, match="3 or 4"):
        ra.Offer(style=ra.PlayStyle.BEGINNER, options=(_option(0), _option(1)))
    with pytest.raises(ValidationError, match="what history did"):
        ra.Offer(
            style=ra.PlayStyle.BEGINNER,
            options=tuple(_option(n, historical=True) for n in range(3)),
        )
    with pytest.raises(ValidationError, match="3 to 5"):
        ra.Offer(style=ra.PlayStyle.GUIDED, options=(_option(0, asks=2),))
    with pytest.raises(ValidationError, match="offered nothing"):
        ra.Offer(style=ra.PlayStyle.FREE, options=(_option(0),))


# --- views, sealing and leaks ---------------------------------------------------


def test_a_seat_sees_its_own_routed_orders_without_the_estimate(sl: Slice) -> None:
    order = sl.shoot_on_sight(effect=None)
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    shift = rx.ShiftDisposition(of=sl.entity("wheeler"), toward=sl.entity("roosevelt"), change=-1)
    sl.add(ev.EffectsEstimated(order_id=order.order_id, part=0, effects=(shift,), reason="r"))
    sl.add(ev.PlayStyleSet(seat_id=sl.fdr, style=ra.PlayStyle.GUIDED), private_to(sl.fdr))
    sl.add(ev.MandateIssued(mandate=sl.mandate(1, sl.fdr)), private_to(sl.fdr))
    sl.add(ev.WakeOpened(wake=0, deadline=DEADLINE))
    mine, theirs = project(sl.state, sl.fdr), project(sl.state, sl.wheeler)
    seen = mine.routed[order.order_id]
    assert seen.parts[0].reason == "r" and "estimated" not in seen.parts[0].model_dump()
    assert (
        "estimated" not in mine.model_dump_json() and "was_estimated" not in mine.model_dump_json()
    )
    assert mine.style is ra.PlayStyle.GUIDED and len(mine.mandates) == 1
    assert not theirs.routed and theirs.style is None and not theirs.mandates
    assert mine.wake == theirs.wake == sl.state.wake


def test_engine_v2_records_seal_and_count_as_admin_reads(sl: Slice) -> None:
    order = sl.shoot_on_sight()
    offers = ev.OptionsOffered(
        seat_id=sl.fdr,
        wake=0,
        offers=(
            ra.Offer(style=ra.PlayStyle.BEGINNER, options=tuple(_option(n) for n in range(3))),
        ),
    )
    routed = sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    estimate = sl.add(
        ev.EffectsEstimated(order_id=order.order_id, part=0, reason="r", rationale="sealed")
    )
    style = sl.add(ev.PlayStyleSet(seat_id=sl.fdr, style=ra.PlayStyle.FREE), private_to(sl.fdr))
    offered = sl.add(offers, private_to(sl.fdr))
    opened = sl.add(ev.WakeOpened(wake=0, deadline=DEADLINE))
    committed = sl.add(ev.WakeCommitted(wake=0, seat_id=sl.fdr))
    assert seal_holder(offered) == sl.fdr
    assert all(seal_holder(e) is None for e in (routed, estimate, style, opened, committed))
    assert all(needs_admin_read(e) for e in (routed, estimate, style, offered))
    assert not needs_admin_read(opened) and not needs_admin_read(committed)
    assert offers.kind not in ev.MUTATING_KINDS


def _with_covert_fact(sl: Slice) -> None:
    fact = Fact(
        fact_id=FactId(derived_id(CAMPAIGN, "fact", "covert")),
        subject=sl.entity("wheeler"),
        predicate="took_money_from",
        obj=sl.entity("germany"),
        scope=Scope(visibility=Visibility.COVERT, known_by=frozenset({sl.wheeler})),
        canary=REASON_CANARY,
    )
    sl.add(ev.FactAsserted(fact=fact), fact.scope)


def test_a_canary_in_an_estimator_reason_is_caught(sl: Slice) -> None:
    _with_covert_fact(sl)
    order = sl.shoot_on_sight(effect=None)
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(
        ev.EffectsEstimated(
            order_id=order.order_id, part=0, reason=f"Wheeler is compromised ({REASON_CANARY})."
        )
    )
    leaks = scan(sl.state, sl.events)
    assert [(lk.seat_id, lk.kind) for lk in leaks] == [(sl.fdr, "effects_estimated")]


def test_canaries_in_mandates_and_offers_are_caught(sl: Slice) -> None:
    _with_covert_fact(sl)
    sl.add(
        ev.MandateIssued(mandate=sl.mandate(1, sl.fdr, text=f"Expose {REASON_CANARY}.")),
        private_to(sl.fdr),
    )
    option = ra.Option(label="Leak it", asks=(ra.Ask(ask=f"Leak {REASON_CANARY}"),))
    sl.add(
        ev.OptionsOffered(
            seat_id=sl.fdr,
            wake=0,
            offers=(
                ra.Offer(style=ra.PlayStyle.BEGINNER, options=(option, _option(1), _option(2))),
            ),
        ),
        private_to(sl.fdr),
    )
    kinds = sorted(lk.kind for lk in scan(sl.state, sl.events))
    assert kinds == ["mandate_issued", "options_offered"]


def test_a_mandate_canary_is_a_secret_from_other_seats(sl: Slice) -> None:
    sl.add(
        ev.MandateIssued(mandate=sl.mandate(1, sl.fdr, canary=MANDATE_CANARY)),
        private_to(sl.fdr),
    )
    sl.add(
        ev.MandateIssued(mandate=sl.mandate(2, sl.wheeler, text=f"Ask about {MANDATE_CANARY}.")),
        private_to(sl.wheeler),
    )
    assert [lk.seat_id for lk in scan(sl.state, sl.events)] == [sl.wheeler]


def test_a_human_reads_their_own_engine_v2_texts_in_the_log(sl: Slice) -> None:
    order = sl.shoot_on_sight(effect=None)
    sl.add(ev.OrderRouted(order=order), private_to(sl.fdr))
    sl.add(ev.EffectsEstimated(order_id=order.order_id, part=0, reason="Stark will grumble."))
    sl.add(ev.MandateIssued(mandate=sl.mandate(1, sl.wheeler)), private_to(sl.wheeler))
    holdings = {"josh": frozenset({sl.fdr}), "macy": frozenset({sl.wheeler})}
    seen = surfaces_from_log(sl.events, holdings, sl.state)
    assert [text for _, text in seen["josh"]] == ["Stark will grumble."]
    assert [text for _, text in seen["macy"]] == ["Keep the convoys moving."]
    assert surfaces_from_log(sl.events, holdings) == {"josh": [], "macy": []}
