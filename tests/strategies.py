"""Hypothesis strategies for every core model. Reused by Layers 2 and 3."""

from datetime import date, datetime, timedelta
from typing import Any, cast

from hypothesis import strategies as st

from revisionist.core import delta as d
from revisionist.core import events as ev
from revisionist.core import goals as g
from revisionist.core.ids import (
    AssetId,
    CampaignId,
    ClockId,
    CommitmentId,
    ContestId,
    DeltaId,
    DocumentId,
    EntityId,
    EventId,
    FactId,
    FeatureId,
    FeedId,
    GoalId,
    IntentId,
    MandateId,
    MeterId,
    OrderId,
    PipelineId,
    QuantityId,
    RelationshipId,
    ScheduledEventId,
    SeatId,
)
from revisionist.core.intent import Intent, Verb
from revisionist.core.ontology import (
    Asset,
    AssetKind,
    Character,
    Clause,
    ClauseKind,
    Clock,
    ClockKind,
    ClockStatus,
    Commitment,
    Contest,
    ContestKind,
    Controller,
    DevelopmentCategory,
    Entity,
    EntityKind,
    EntityStatus,
    Fact,
    Meter,
    Persona,
    Relationship,
    ScheduledEvent,
    ScheduleSource,
    Seat,
    SeatKind,
)
from revisionist.core.realism import agenda as ra
from revisionist.core.realism import agreement as ragr
from revisionist.core.realism import answer as rans
from revisionist.core.realism import battle as rb
from revisionist.core.realism import card as rc
from revisionist.core.realism import conference as rconf
from revisionist.core.realism import detect as rdet
from revisionist.core.realism import document as rd
from revisionist.core.realism import economy as econ
from revisionist.core.realism import effect as rx
from revisionist.core.realism import geography as rg
from revisionist.core.realism import groups as rgrp
from revisionist.core.realism import holders as rh
from revisionist.core.realism import kinds as rk
from revisionist.core.realism import offers as roff
from revisionist.core.realism import pipeline as rp
from revisionist.core.realism import stance as rs
from revisionist.core.realism import territory as tm
from revisionist.core.realism.quantity import RESOLVER_KEYS, Quantity
from revisionist.core.realism.trade import TradeLine
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.settings import Settings
from revisionist.core.state import Rule
from revisionist.core.visibility import Scope, Visibility

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ulid = st.text(alphabet=CROCKFORD, min_size=26, max_size=26)

campaign_ids = ulid.map(CampaignId)
event_ids = ulid.map(EventId)
entity_ids = ulid.map(EntityId)
asset_ids = ulid.map(AssetId)
relationship_ids = ulid.map(RelationshipId)
meter_ids = ulid.map(MeterId)
clock_ids = ulid.map(ClockId)
fact_ids = ulid.map(FactId)
scheduled_ids = ulid.map(ScheduledEventId)
contest_ids = ulid.map(ContestId)
commitment_ids = ulid.map(CommitmentId)
seat_ids = ulid.map(SeatId)
intent_ids = ulid.map(IntentId)
delta_ids = ulid.map(DeltaId)
goal_ids = ulid.map(GoalId)
document_ids = ulid.map(DocumentId)
order_ids = ulid.map(OrderId)
quantity_ids = ulid.map(QuantityId)
pipeline_ids = ulid.map(PipelineId)
feed_ids = ulid.map(FeedId)
feature_ids = ulid.map(FeatureId)
mandate_ids = ulid.map(MandateId)

short_text = st.text(min_size=1, max_size=40)
tags = st.frozensets(short_text, max_size=3)


@st.composite
def scopes(draw: st.DrawFn) -> Scope:
    vis = draw(st.sampled_from(list(Visibility)))
    if vis is Visibility.PUBLIC:
        return Scope(visibility=vis)
    holders = draw(st.frozensets(seat_ids, min_size=1, max_size=4))
    return Scope(visibility=vis, known_by=holders)


in_world_dates = st.dates(min_value=date(1, 1, 1), max_value=date(2025, 12, 31))

settings = st.builds(
    Settings,
    lines=tags.map(tuple),
    veils=tags.map(tuple),
    tone=short_text,
    end_date=st.none() | in_world_dates,
    real_days=st.none() | st.integers(1, 365),
    wake_hours=st.integers(1, 168),
)

entities = st.builds(
    Entity,
    entity_id=entity_ids,
    kind=st.sampled_from(list(EntityKind)),
    name=short_text,
    parent=st.none() | entity_ids,
    location=st.none() | entity_ids,
    tags=tags,
    theatre=st.none() | short_text,
    within=st.none() | entity_ids,
)

assets = st.builds(
    Asset,
    asset_id=asset_ids,
    kind=st.sampled_from(list(AssetKind)),
    name=short_text,
    tier=st.integers(0, 5),
    controller=entity_ids,
    location=st.none() | entity_ids,
    loyalty=st.integers(-5, 5),
    scope=scopes(),
)

relationships = st.builds(
    Relationship,
    relationship_id=relationship_ids,
    a=entity_ids,
    b=entity_ids,
    disposition=st.integers(-5, 5),
    price_tags=tags,
    leverage_tags=tags,
    scope=scopes(),
)

meters = st.builds(
    Meter,
    meter_id=meter_ids,
    owner=entity_ids,
    name=short_text,
    value=st.integers(0, 100),
    max_delta_per_tick=st.integers(1, 25),
    scope=scopes(),
)

clocks = st.builds(
    Clock,
    clock_id=clock_ids,
    kind=st.sampled_from(list(ClockKind)),
    name=short_text,
    owner=st.none() | seat_ids,
    target=st.none() | entity_ids,
    intent_id=st.none() | intent_ids,
    opened_tick=st.integers(0, 200),
    segments_total=st.integers(1, 12),
    segments_filled=st.integers(0, 12),
    eta_tick=st.none() | st.integers(0, 200),
    exposure=st.integers(0, 5),
    holds_slot=st.booleans(),
    scope=scopes(),
)

facts = st.builds(
    Fact,
    fact_id=fact_ids,
    subject=entity_ids,
    predicate=short_text,
    obj=entity_ids | asset_ids | clock_ids | short_text,
    truth=st.booleans(),
    exposure=st.integers(0, 5),
    asserted_tick=st.integers(0, 200),
    scope=scopes(),
    canary=st.none() | ulid,
)

scheduled_events = st.builds(
    ScheduledEvent,
    scheduled_id=scheduled_ids,
    fire_at_tick=st.integers(0, 500),
    name=short_text,
    source_intent=st.none() | intent_ids,
    source_clock=st.none() | clock_ids,
    scope=scopes(),
)

clauses = st.builds(
    Clause,
    kind=st.sampled_from(list(ClauseKind)),
    party=entity_ids,
    beneficiary=entity_ids,
    asset=st.none() | asset_ids,
    verb=st.none() | st.sampled_from(list(Verb)),
    amount=st.none() | st.integers(0, 5),
    until_tick=st.none() | st.integers(0, 500),
)

commitments = st.builds(
    Commitment,
    commitment_id=commitment_ids,
    parties=st.frozensets(entity_ids, min_size=2, max_size=4),
    clauses=st.lists(clauses, min_size=1, max_size=4).map(tuple),
    scope=scopes(),
)

personas = st.builds(
    Persona,
    name=short_text,
    role=short_text,
    voice=short_text,
    backstory=short_text,
    relationship=short_text,
)

seats = st.builds(
    Seat,
    seat_id=seat_ids,
    kind=st.sampled_from(list(SeatKind)),
    name=short_text,
    embodies=entity_ids,
    slots=st.integers(0, 5),
    agent=st.none() | entity_ids,
    persona=st.none() | personas,
    objectives=st.frozensets(clock_ids, max_size=3),
    standing_orders=st.lists(short_text, max_size=3).map(tuple),
    joined_tick=st.integers(0, 200),
)

world_object_ids = (
    entity_ids | asset_ids | relationship_ids | meter_ids | clock_ids | fact_ids | commitment_ids
)

intents = st.builds(
    Intent,
    intent_id=intent_ids,
    actor=seat_ids,
    verb=st.sampled_from(list(Verb)),
    targets=st.lists(world_object_ids, max_size=4).map(tuple),
    means=st.lists(asset_ids, max_size=3).map(tuple),
    counterparty=st.none() | entity_ids,
    duration_ticks=st.integers(1, 12),
    scope=scopes(),
    spin=st.none() | st.text(max_size=280),
    condition=st.none() | short_text,
    filed_tick=st.integers(0, 500),
)

_delta_common = {"delta_id": delta_ids, "reason": st.text(max_size=200)}

deltas = st.one_of(
    st.builds(d.AssetTierDelta, asset_id=asset_ids, change=st.integers(-2, 2), **_delta_common),
    st.builds(d.AssetStatusSet, asset_id=asset_ids, **_delta_common),
    st.builds(d.AssetControllerSet, asset_id=asset_ids, controller=entity_ids, **_delta_common),
    st.builds(
        d.AssetCreate,
        asset_id=asset_ids,
        name=short_text,
        tier=st.integers(0, 1),
        controller=entity_ids,
        scope=scopes(),
        **_delta_common,
    ),
    st.builds(d.MeterDelta, meter_id=meter_ids, change=st.integers(-50, 50), **_delta_common),
    st.builds(
        d.DispositionDelta,
        relationship_id=relationship_ids,
        change=st.integers(-2, 2),
        **_delta_common,
    ),
    st.builds(
        d.RelationshipTagSet,
        relationship_id=relationship_ids,
        add_price=tags,
        add_leverage=tags,
        remove_leverage=tags,
        **_delta_common,
    ),
    st.builds(d.ClockAdvance, clock_id=clock_ids, segments=st.integers(-2, 2), **_delta_common),
    st.builds(
        d.ClockCreate,
        clock_id=clock_ids,
        name=short_text,
        owner=st.none() | seat_ids,
        intent_id=st.none() | intent_ids,
        segments_total=st.integers(1, 12),
        exposure=st.integers(0, 5),
        scope=scopes(),
        **_delta_common,
    ),
    st.builds(
        d.ClockStatusSet,
        clock_id=clock_ids,
        status=st.sampled_from([ClockStatus.FAILED, ClockStatus.ABANDONED]),
        **_delta_common,
    ),
    st.builds(d.ClockExposureDelta, clock_id=clock_ids, change=st.integers(-2, 2), **_delta_common),
    st.builds(
        d.FactAssert,
        fact_id=fact_ids,
        subject=entity_ids,
        predicate=short_text,
        obj=entity_ids | asset_ids | clock_ids | short_text,
        exposure=st.integers(0, 5),
        scope=scopes(),
        **_delta_common,
    ),
    st.builds(
        d.KnowledgeGrant,
        target=fact_ids | asset_ids | clock_ids | commitment_ids,
        seats=st.frozensets(seat_ids, min_size=1, max_size=4),
        **_delta_common,
    ),
    st.builds(d.EntityStatusSet, entity_id=entity_ids, **_delta_common),
    st.builds(
        d.CommitmentCreate,
        commitment_id=commitment_ids,
        parties=st.frozensets(entity_ids, min_size=2, max_size=4),
        clauses=st.lists(clauses, min_size=1, max_size=6).map(tuple),
        scope=scopes(),
        **_delta_common,
    ),
    st.builds(d.CommitmentStatusSet, commitment_id=commitment_ids, **_delta_common),
    st.builds(
        d.ScheduledEventQueue,
        scheduled_id=scheduled_ids,
        fire_in_ticks=st.integers(1, 24),
        name=short_text,
        source_clock=st.none() | clock_ids,
        scope=scopes(),
        **_delta_common,
    ),
    st.builds(d.SeatSlotsDelta, seat_id=seat_ids, change=st.integers(-2, 2), **_delta_common),
)

ops = st.sampled_from(["ge", "le"])

condition_leaves = st.one_of(
    st.builds(g.HoldsOffice, holder=entity_ids, office=asset_ids),
    st.builds(g.ControlsAsset, holder=entity_ids, asset=asset_ids),
    st.builds(g.EntityIs, entity=entity_ids, status=st.sampled_from(list(EntityStatus))),
    st.builds(g.MeterAt, meter=meter_ids, op=ops, value=st.integers(-50, 150)),
    st.builds(g.CommitmentInForce, commitment=commitment_ids),
    st.builds(g.DispositionAt, relationship=relationship_ids, op=ops, value=st.integers(-5, 5)),
    st.builds(g.Ordered, person=entity_ids, effect=st.sampled_from(list(rx.EffectKind))),
)


def _combine(
    children: st.SearchStrategy[g.WinCondition],
) -> st.SearchStrategy[g.WinCondition]:
    group = st.lists(children, min_size=1, max_size=3).map(tuple)
    return st.builds(g.AllOf, conditions=group) | st.builds(g.AnyOf, conditions=group)


conditions: st.SearchStrategy[g.WinCondition] = st.recursive(
    condition_leaves, _combine, max_leaves=6
).filter(lambda c: g.depth(c) <= g.MAX_DEPTH and len(g.leaves(c)) <= g.MAX_PARTS)


@st.composite
def goals(draw: st.DrawFn) -> g.Goal:
    condition = draw(conditions)
    seat = draw(seat_ids)
    return g.Goal(
        goal_id=draw(goal_ids),
        seat_id=seat,
        text=draw(short_text),
        condition=condition,
        kind=g.goal_kind(condition),
        clock_id=draw(clock_ids),
        met_tick=draw(st.none() | st.integers(0, 500)),
        holding=draw(st.booleans()),
        scope=Scope(visibility=Visibility.PRIVATE, known_by=frozenset({seat})),
    )


versions = st.builds(ev.Versions, engine=short_text, schema_version=short_text, prompt=short_text)

call_costs = st.builds(
    ev.CallCost,
    call_class=short_text,
    model=short_text,
    input_tokens=st.integers(0, 10**6),
    output_tokens=st.integers(0, 10**6),
    cached_tokens=st.integers(0, 10**6),
    usd=st.floats(0, 100, allow_nan=False),
)


@st.composite
def contests(draw: st.DrawFn) -> Contest:
    kind = draw(st.sampled_from(list(ContestKind)))
    n = 1 if kind is ContestKind.TRIAL else draw(st.integers(2, 4))
    sides = tuple(draw(st.lists(entity_ids, min_size=n, max_size=n, unique=True)))
    lo = 0 if kind is ContestKind.TRIAL else -100
    decided = draw(st.booleans())
    winner = draw(st.none() | st.sampled_from(sides)) if decided else None
    return Contest(
        contest_id=draw(contest_ids),
        kind=kind,
        name=draw(short_text),
        prize=draw(short_text),
        sides=sides,
        track=draw(st.integers(lo, 100)),
        momentum=draw(st.integers(-20, 20)),
        countdown_days=draw(st.integers(0, 3650)),
        decided=decided,
        winner=winner,
        scope=draw(scopes()),
    )


history_events = st.builds(
    ScheduledEvent,
    scheduled_id=scheduled_ids,
    fire_at_tick=st.integers(0, 500),
    name=short_text,
    scope=scopes(),
    source=st.just(ScheduleSource.HISTORY),
    on_date=in_world_dates,
    condition=st.none() | conditions,
    weight=st.integers(1, 3),
    headline=st.none() | st.text(min_size=1, max_size=60),
    subject=st.none() | entity_ids,
    obj=st.none() | entity_ids,
)


# --- realism ------------------------------------------------------------------

channels = st.sampled_from(list(rc.ChannelKind))
labels = st.text(min_size=1, max_size=60)


@st.composite
def param_specs(draw: st.DrawFn) -> rc.ParamSpec:
    kind = draw(st.sampled_from(list(rc.ParamKind)))
    name = draw(labels)
    if kind is rc.ParamKind.INT:
        lo = draw(st.integers(-1000, 1000))
        return rc.ParamSpec(name=name, kind=kind, lo=lo, hi=lo + draw(st.integers(0, 1000)))
    if kind is rc.ParamKind.ENUM:
        choices = draw(st.lists(labels, min_size=1, max_size=4, unique=True))
        return rc.ParamSpec(name=name, kind=kind, choices=tuple(choices))
    return rc.ParamSpec(name=name, kind=kind)


levers = st.builds(
    rc.Lever,
    name=labels,
    pipeline=pipeline_ids,
    resolver=st.sampled_from(RESOLVER_KEYS),
    params=st.lists(param_specs(), max_size=3, unique_by=lambda p: p.name).map(tuple),
)

effect_kinds = st.sampled_from(list(rx.EffectKind))

domains = st.builds(
    rc.Domain,
    name=labels,
    effects=st.frozensets(effect_kinds, min_size=1, max_size=3),
    executor=st.none() | entity_ids,
    forces=st.lists(feature_ids, max_size=2).map(tuple),
)

reaches = st.builds(
    rc.Reach,
    rank=st.integers(0, 5),
    chain=st.lists(entity_ids, max_size=3).map(tuple),
    heads=st.booleans(),
)

seat_cards = st.builds(
    rc.SeatCard,
    authority=st.lists(domains, max_size=3, unique_by=lambda dm: dm.name).map(tuple),
    reach=reaches,
    person=entity_ids,
    office=labels,
    playable=st.booleans(),
    powers=st.lists(labels, max_size=3).map(tuple),
    inner_circle=st.lists(
        st.builds(rc.Contact, person=entity_ids, channel=channels), max_size=3
    ).map(tuple),
    principals=st.lists(entity_ids, max_size=2).map(tuple),
    levers=st.lists(levers, max_size=2).map(tuple),
    feeds=st.lists(feed_ids, max_size=2).map(tuple),
    pipelines=st.lists(pipeline_ids, max_size=2).map(tuple),
    constraints=st.lists(labels, max_size=2).map(tuple),
    personal=st.lists(labels, max_size=2).map(tuple),
    successor=st.none() | entity_ids,
    horizon_days=st.integers(1, 365),
    voice=st.text(max_size=200),
    loyalty=st.integers(-5, 5),
    doctrine=st.lists(labels, max_size=2).map(tuple),
    interests=st.lists(labels, max_size=2).map(tuple),
    addressed_as=st.none() | labels,
    wants=st.lists(labels, max_size=2).map(tuple),
    holds_to=st.lists(labels, max_size=2).map(tuple),
)

topics = st.builds(
    rc.Topic,
    key=labels,
    name=labels,
    levers=st.lists(labels, max_size=2).map(tuple),
    effects=st.lists(effect_kinds, max_size=2).map(tuple),
    words=st.lists(labels, max_size=2).map(tuple),
)

biases = st.builds(
    rd.Bias,
    skew_pct=st.integers(-100, 100),
    noise_pct=st.integers(0, 100),
    omit_pct=st.integers(0, 100),
    delay_days=st.integers(0, 365),
)

feeds = st.builds(
    rd.Feed,
    feed_id=feed_ids,
    name=labels,
    author=entity_ids,
    kind=st.sampled_from(list(rd.DocumentKind)),
    channel=channels,
    classification=st.sampled_from(list(rd.Classification)),
    every_days=st.none() | st.integers(1, 365),
    latency_days=st.none() | st.integers(0, 365),
    reports=st.lists(quantity_ids, max_size=3).map(tuple),
    bias=biases,
)


@st.composite
def steps(draw: st.DrawFn) -> rp.Step:
    kind = draw(st.sampled_from(list(rp.StepKind)))
    allowed = frozenset({rp.StepAction.PASS})
    if kind is rp.StepKind.DECISION:
        allowed |= draw(st.frozensets(st.sampled_from(list(rp.StepAction))))
    return rp.Step(
        person=draw(entity_ids),
        kind=kind,
        days=draw(st.none() | st.integers(0, 365)),
        allowed=allowed,
    )


pipelines = st.builds(
    rp.Pipeline,
    pipeline_id=pipeline_ids,
    name=labels,
    steps=st.lists(steps(), min_size=1, max_size=4).map(tuple),
)

param_values = st.integers(-1000, 1000) | st.text(max_size=200)
param_maps = st.dictionaries(labels, param_values, max_size=3)


@st.composite
def step_outcomes(draw: st.DrawFn) -> rp.StepOutcome:
    action = draw(st.sampled_from(list(rp.StepAction)))
    amended = draw(st.dictionaries(labels, param_values, min_size=1, max_size=2))
    return rp.StepOutcome(
        step=draw(st.integers(0, 11)),
        person=draw(entity_ids),
        action=action,
        on=draw(in_world_dates),
        amended=amended if action is rp.StepAction.AMEND else {},
    )


@st.composite
def held_choices(draw: st.DrawFn) -> rp.HeldChoice:
    action = draw(st.sampled_from(list(rp.StepAction)))
    amended = draw(st.dictionaries(labels, param_values, min_size=1, max_size=2))
    return rp.HeldChoice(
        step=draw(st.integers(0, 11)),
        action=action,
        amended=amended if action is rp.StepAction.AMEND else {},
    )


part_refs = st.builds(rx.PartRef, order_id=order_ids, part=st.integers(0, 7))

measures = st.builds(
    rx.ProposeMeasure,
    title=labels,
    clauses=st.lists(
        st.builds(rx.Clause, kind=st.just(rx.ClauseKind.POWER), subject=labels),
        min_size=1,
        max_size=3,
    ).map(tuple),
)

orders = st.builds(
    rp.Order,
    order_id=order_ids,
    issuer=seat_ids,
    lever=labels,
    pipeline=pipeline_ids,
    params=param_maps,
    status=st.sampled_from(list(rp.OrderStatus)),
    step=st.integers(0, 12),
    filed=in_world_dates,
    outcomes=st.lists(step_outcomes(), max_size=3).map(tuple),
    routed_from=st.none() | part_refs,
    measure=st.none() | measures,
    held_choice=st.none() | held_choices(),
)


@st.composite
def document_views(draw: st.DrawFn) -> rd.DocumentView:
    issued = draw(in_world_dates)
    return rd.DocumentView(
        doc_id=draw(document_ids),
        kind=draw(st.sampled_from(list(rd.DocumentKind))),
        author=draw(entity_ids),
        issued=issued,
        arrives=issued + draw(st.timedeltas(min_value=timedelta(0), max_value=timedelta(60))),
        channel=draw(channels),
        classification=draw(st.sampled_from(list(rd.Classification))),
        title=draw(st.text(max_size=60)),
        body=tuple(
            draw(
                st.lists(
                    st.builds(
                        rd.BodyField,
                        label=labels,
                        value=st.none() | st.integers(-(10**6), 10**6) | labels,
                        unit=st.text(max_size=60),
                    ),
                    max_size=3,
                )
            )
        ),
        prose=draw(st.none() | st.text(max_size=400)),
        scope=draw(scopes()),
    )


truth_refs = st.builds(
    rd.TruthRef,
    quantity_id=quantity_ids,
    value=st.none() | st.integers(-(10**6), 10**6),
    canary=st.none() | ulid,
)


@st.composite
def documents_issued(draw: st.DrawFn) -> ev.DocumentIssued:
    view = draw(document_views())
    truth = rd.DocumentTruth(
        doc_id=view.doc_id,
        feed=draw(st.none() | feed_ids),
        truth_refs=tuple(draw(st.lists(truth_refs, max_size=3))),
        bias=draw(biases),
    )
    return ev.DocumentIssued(document=view, truth=truth)


quantities = st.builds(
    Quantity,
    quantity_id=quantity_ids,
    owner=st.none() | entity_ids,
    name=labels,
    value=st.none() | st.integers(-(10**9), 10**9),
    unit=labels,
    as_of=in_world_dates,
    scope=st.none() | scopes(),
)


@st.composite
def features(draw: st.DrawFn) -> rg.Feature:
    kind = draw(st.sampled_from(list(rg.FeatureKind)))
    force = kind in rg.AT_ONE_PLACE
    places = draw(st.lists(entity_ids, min_size=1 if force else 2, max_size=1 if force else 3))
    moving = force and draw(st.booleans())
    stepping = moving and draw(st.booleans())
    as_of = draw(in_world_dates)
    recon = draw(st.none() | entity_ids) if force else None
    return rg.Feature(
        feature_id=draw(feature_ids),
        kind=kind,
        name=draw(labels),
        side=draw(st.none() | entity_ids),
        tier=draw(st.integers(0, 5)),
        places=tuple(places),
        as_of=as_of,
        bound_for=draw(entity_ids) if moving else None,
        arrives=as_of if moving else None,
        in_service=draw(st.none() | in_world_dates),
        posture=draw(st.none() | st.sampled_from(list(rx.Posture))) if force else None,
        engagement=draw(st.none() | st.sampled_from(list(rx.Engagement))) if force else None,
        detached_from=draw(st.none() | feature_ids) if force else None,
        rejoined_on=draw(st.none() | in_world_dates) if force else None,
        piece=draw(labels) if kind is rg.FeatureKind.PIECE else None,
        path=tuple(draw(st.lists(entity_ids, min_size=1, max_size=3))) if stepping else (),
        step_due=as_of if stepping else None,
        lost_on=draw(st.none() | in_world_dates) if kind is rg.FeatureKind.PIECE else None,
        contingency=draw(st.none() | contingencies()) if kind is rg.FeatureKind.PIECE else None,
        concealed=draw(st.booleans()) if force else False,
        concealed_leg=stepping and draw(st.booleans()),
        recon=recon,
        recon_on=None if recon is None else draw(in_world_dates),
    )


@st.composite
def contingencies(draw: st.DrawFn) -> rx.Contingency:
    """A battle contingency of any kind, with the fields its kind takes (BDC)."""
    kind = draw(st.sampled_from(list(rx.ContingencyKind)))
    to = None
    if kind is rx.ContingencyKind.FALL_BACK:
        to = draw(entity_ids)
    elif kind is rx.ContingencyKind.WITHDRAW_BELOW:
        to = draw(st.none() | entity_ids)
    below = draw(st.integers(1, 5)) if kind is rx.ContingencyKind.WITHDRAW_BELOW else None
    return rx.Contingency(kind=kind, to=to, below=below)


@st.composite
def triggers(draw: st.DrawFn) -> ra.Trigger:
    on = draw(st.sampled_from(list(ra.TriggerKind)))
    if on is ra.TriggerKind.HISTORY:
        return ra.Trigger(on=on, history=draw(scheduled_ids))
    if on is ra.TriggerKind.QUANTITY:
        return ra.Trigger(
            on=on, quantity=draw(quantity_ids), op=draw(ops), value=draw(st.integers(-1000, 1000))
        )
    return ra.Trigger(on=on, effect=draw(st.sampled_from(list(rx.EffectKind))))


@st.composite
def mandate_templates(draw: st.DrawFn) -> ra.MandateTemplate:
    kind = draw(st.sampled_from(list(ra.MandateKind)))
    return ra.MandateTemplate(
        key=draw(labels),
        kind=kind,
        trigger=draw(triggers()),
        to=tuple(draw(st.lists(entity_ids, min_size=1, max_size=3))),
        issuer=draw(entity_ids) if kind is ra.MandateKind.ORDER else None,
        text=draw(short_text),
        condition=draw(conditions),
        days=draw(st.integers(1, 90)),
    )


@st.composite
def wars(draw: st.DrawFn) -> War:
    a, b = draw(st.lists(entity_ids, min_size=2, max_size=2, unique=True))
    return War(
        war_id=war_id_for(a, b),
        a=a,
        b=b,
        since=draw(in_world_dates),
        declared_by=draw(entity_ids),
        declared=draw(st.booleans()),
    )


labels = st.text(min_size=1, max_size=20)
sha256s = st.binary(min_size=1, max_size=8).map(lambda b: tm.file_hash(b))
boxes = st.tuples(*[st.floats(-180, 180, allow_nan=False)] * 4)


@st.composite
def battle_sides(draw: st.DrawFn) -> rb.BattleSide:
    pieces = draw(st.lists(feature_ids, min_size=1, max_size=3, unique=True))
    decided = draw(st.booleans())
    return rb.BattleSide(
        nation=draw(entity_ids),
        pieces=tuple(pieces),
        brought=draw(st.integers(1, 15)),
        lost=draw(st.integers(0, 15)),
        decision=draw(st.sampled_from(list(rb.Decision))) if decided else None,
        decided_wake=draw(st.integers(0, 50)) if decided else None,
    )


@st.composite
def battles(draw: st.DrawFn) -> rb.Battle:
    """An open battle; one in three a meeting battle on a border (BDC's fields for HON)."""
    area = draw(entity_ids)
    meeting = draw(st.integers(0, 2)) == 0
    second = draw(entity_ids.filter(lambda a: a != area)) if meeting else None
    return rb.Battle(
        area=area,
        opened=draw(in_world_dates),
        attacker=draw(battle_sides()),
        defender=draw(battle_sides()),
        came_from=draw(st.dictionaries(feature_ids, entity_ids, max_size=2)),
        rounds=draw(st.integers(0, 30)),
        pressed_on=draw(st.none() | in_world_dates),
        meeting=meeting,
        second=second,
        attacker_in=draw(st.sampled_from([area, second])) if second is not None else None,
    )


@st.composite
def home_groups(draw: st.DrawFn) -> rgrp.Group:
    """A group at home (GRP): a bloc with its chamber and seats, or none."""
    bloc = draw(st.booleans())
    seats = draw(st.integers(1, 400))
    votes = st.builds(rgrp.BlocVote, voting=st.just(seats), yeas=st.integers(0, seats))
    return rgrp.Group(
        key=draw(labels),
        name=draw(labels),
        kind=draw(labels),
        start=draw(st.integers(0, 100)),
        baseline=draw(st.integers(0, 100)),
        chamber=draw(labels) if bloc else None,
        seats=seats if bloc else None,
        feeds=draw(
            st.dictionaries(
                st.sampled_from(list(rgrp.Feeds)), st.floats(0.1, 5, allow_nan=False), max_size=2
            )
        ),
        moved_by=draw(
            st.dictionaries(st.sampled_from(list(rgrp.Happening)), st.integers(-9, 9), max_size=2)
        ),
        votes=draw(st.dictionaries(labels, st.dictionaries(labels, votes, max_size=2), max_size=1))
        if bloc
        else {},
        vote_default=draw(st.dictionaries(labels, votes, max_size=2)) if bloc else {},
        stances=draw(
            st.dictionaries(st.sampled_from(list(rx.ClauseKind)), st.integers(-3, 3), max_size=2)
        )
        if bloc
        else {},
        abroad=draw(st.booleans()),
    )


@st.composite
def nation_groups(draw: st.DrawFn) -> rgrp.NationGroups:
    found = draw(st.lists(home_groups(), min_size=1, max_size=2, unique_by=lambda g: g.key))
    keys = [g.key for g in found]
    moves = st.dictionaries(
        st.sampled_from(keys), st.sampled_from([-3, -1, 1, 3]), min_size=1, max_size=2
    )
    themes = draw(
        st.lists(
            st.builds(rgrp.Theme, key=labels, name=labels, moves=moves),
            max_size=2,
            unique_by=lambda t: t.key,
        )
    )
    return rgrp.NationGroups(nation=draw(entity_ids), groups=tuple(found), themes=tuple(themes))


priced_offers = st.builds(
    roff.PricedOffer,
    offer_id=labels,
    seat=seat_ids,
    nation=entity_ids,
    bloc=labels,
    measure=labels,
    price=labels,
    bill=order_ids,
    filed=in_world_dates,
)
"""An offer as made: filed, not yet moved."""


def offer_settlements() -> st.SearchStrategy[ev.OfferSettled]:
    """Where an offer goes, with a due day exactly when its measure passed."""
    owed = [roff.OfferStanding.DUE, roff.OfferStanding.KEPT, roff.OfferStanding.BROKEN]
    free = [roff.OfferStanding.TAKEN, roff.OfferStanding.REFUSED, roff.OfferStanding.LAPSED]
    return st.one_of(
        st.builds(
            ev.OfferSettled,
            offer_id=labels,
            standing=st.sampled_from(owed),
            on=in_world_dates,
            due=in_world_dates,
        ),
        st.builds(
            ev.OfferSettled, offer_id=labels, standing=st.sampled_from(free), on=in_world_dates
        ),
    )


proposals = st.builds(
    rgrp.Proposal,
    seat=seat_ids,
    polity=entity_ids,
    group=labels,
    change=st.integers(-9, 9),
    text_hash=labels,
    on=in_world_dates,
)


@st.composite
def agreement_clauses(draw: st.DrawFn) -> rx.AgreementClause:
    """A clause of an agreement (AGR), with the fields its type needs."""
    kind = draw(st.sampled_from(list(rx.ClauseType)))
    fields: dict[str, Any] = {"type": kind, "binds": draw(entity_ids)}
    if kind in (rx.ClauseType.PLACE, rx.ClauseType.FORM, rx.ClauseType.AID) or draw(st.booleans()):
        fields["on"] = draw(in_world_dates)
    if kind is rx.ClauseType.PLACE:
        fields["force"] = draw(feature_ids)
        fields["present"] = draw(st.booleans())
        if draw(st.booleans()):
            fields["area"] = draw(entity_ids)
        else:
            fields["region"] = draw(labels)
    if kind is rx.ClauseType.KEEP_OUT:
        fields["area"] = draw(entity_ids)
    if kind in (
        rx.ClauseType.NO_WAR,
        rx.ClauseType.NO_ATTACK,
        rx.ClauseType.DEFEND,
        rx.ClauseType.AID,
    ):
        fields["nation"] = draw(entity_ids)
    if kind is rx.ClauseType.DEFEND:
        fields["days"] = draw(st.integers(0, 60))
    if kind is rx.ClauseType.FORM:
        fields["form"] = draw(labels)
    if kind is rx.ClauseType.AID:
        fields["share"] = draw(st.integers(1, 100))
    if kind in (rx.ClauseType.VOTE, rx.ClauseType.UNCHECKED):
        fields["text"] = draw(st.text(min_size=1, max_size=300))
    return rx.AgreementClause(**fields)


@st.composite
def agreement_deals(draw: st.DrawFn) -> rx.Deal:
    """An offer of an agreement (AGR): parties, wording and clauses binding the parties."""
    parties = tuple(draw(st.lists(entity_ids, min_size=2, max_size=3, unique=True)))
    clauses = tuple(
        c.model_copy(update={"binds": draw(st.sampled_from(parties))})
        for c in draw(st.lists(agreement_clauses(), max_size=2))
    )
    return rx.Deal(
        counterparty=draw(st.sampled_from(parties)),
        parties=parties,
        wording=draw(st.text(min_size=1, max_size=600).filter(str.strip)),
        clauses=clauses,
        envoy=draw(st.none() | feature_ids),
    )


@st.composite
def agreement_offers(draw: st.DrawFn) -> ragr.AgreementOffer:
    parties = tuple(draw(st.lists(entity_ids, min_size=2, max_size=3, unique=True)))
    filed = draw(in_world_dates)
    return ragr.AgreementOffer(
        offer_id=draw(order_ids),
        version=draw(labels),
        parties=parties,
        by=parties[0],
        wording=draw(st.text(max_size=600)),
        clauses=tuple(draw(st.lists(agreement_clauses(), max_size=2))),
        filed=filed,
        expires=filed,
    )


@st.composite
def agreements(draw: st.DrawFn) -> ragr.Agreement:
    offer = draw(agreement_offers())
    return ragr.Agreement(
        agreement_id=draw(labels),
        version=offer.version,
        parties=offer.parties,
        wording=offer.wording,
        clauses=offer.clauses,
        made=offer.filed,
        offer_id=draw(st.none() | order_ids),
        published=draw(st.none() | in_world_dates),
        statuses=tuple(draw(st.sampled_from(list(ragr.ClauseStatus))) for _ in offer.clauses),
        calls=tuple(
            draw(
                st.lists(
                    st.builds(
                        ragr.Call, clause=st.integers(0, 7), against=entity_ids, due=in_world_dates
                    ),
                    max_size=1,
                )
            )
        ),
    )


@st.composite
def conference_texts(draw: st.DrawFn) -> rconf.ConferenceText:
    return rconf.ConferenceText(
        wording=draw(st.text(min_size=1, max_size=600)),
        clauses=tuple(draw(st.lists(agreement_clauses(), max_size=2))),
        topics=tuple(draw(st.lists(labels, max_size=2))),
        unanimous=draw(st.booleans()),
    )


@st.composite
def conference_tallies(draw: st.DrawFn) -> rconf.Tally:
    return rconf.Tally(
        on=draw(in_world_dates),
        outcome=draw(st.sampled_from(list(rconf.Outcome))),
        votes=tuple(
            draw(
                st.lists(
                    st.builds(
                        rconf.NationVote,
                        nation=entity_ids,
                        vote=st.sampled_from(list(rconf.Vote)),
                    ),
                    max_size=3,
                )
            )
        ),
        agreement_id=draw(st.none() | labels),
    )


@st.composite
def conferences(draw: st.DrawFn) -> rconf.Conference:
    """A conference (CNF): two or more nations invited, the caller among them, and a voting
    day at least ``CONF_DAYS`` after it opens."""
    invited = tuple(draw(st.lists(entity_ids, min_size=2, max_size=3, unique=True)))
    opens = draw(st.dates(min_value=date(1, 1, 1), max_value=date(2025, 12, 1)))
    later = draw(st.integers(rconf.CONF_DAYS, 20))
    return rconf.Conference(
        key=draw(labels),
        caller=draw(st.sampled_from(invited)),
        invited=invited,
        text=draw(conference_texts()),
        opens=opens,
        voting_day=opens + timedelta(days=later),
        tally_wake=draw(st.none() | st.integers(0, 50)),
        public=draw(st.booleans()),
        tally=draw(st.none() | conference_tallies()),
    )


@st.composite
def intelligences(draw: st.DrawFn) -> rdet.Intelligence:
    """A nation's sources (DET): each source once, ranked from 1."""
    kinds = draw(st.lists(st.sampled_from(list(rdet.Source)), max_size=3, unique=True))
    level = draw(st.integers(0, 3))
    return rdet.Intelligence(
        nation=draw(entity_ids),
        sources=tuple(
            rdet.Informant(
                source=k,
                person=draw(entity_ids),
                channel=draw(channels),
                rank=n + 1,
                skew=draw(st.integers(-5, 5)),
            )
            for n, k in enumerate(kinds)
        ),
        codebreaking=level,
        agents=tuple(
            draw(
                st.lists(
                    agents(),
                    max_size=2,
                )
            )
        ),
        raised=tuple(draw(st.lists(in_world_dates, max_size=3 - level))),
    )


def agents() -> st.SearchStrategy[rdet.Agent]:
    """An agent declared at the start, or placed and perhaps lost (IOR)."""
    return st.builds(
        rdet.Agent,
        area=entity_ids,
        until=st.none() | in_world_dates,
        since=st.none() | in_world_dates,
        lost=st.none() | in_world_dates,
    )


@st.composite
def reports(draw: st.DrawFn) -> rdet.Report:
    """A report (DET): an area with a strength range, or a region with none."""
    seen = draw(st.dates(min_value=date(1, 1, 1), max_value=date(2025, 1, 1)))
    lo = draw(st.integers(0, 5))
    by_area = draw(st.booleans())
    return rdet.Report(
        key=draw(st.text(min_size=1, max_size=20)),
        kind=draw(st.none() | st.text(min_size=1, max_size=20)),
        strength=(lo, lo + draw(st.integers(0, 2))) if by_area else None,
        area=draw(entity_ids) if by_area else None,
        region=None if by_area else draw(st.text(min_size=1, max_size=20)),
        seen=seen,
        source=draw(st.sampled_from(list(rdet.Source))),
        rank=draw(st.integers(0, 5)),
        confidence=draw(st.sampled_from(list(rdet.Confidence))),
        arrives=seen + timedelta(days=draw(st.integers(0, 5))),
    )


@st.composite
def battle_decisions(draw: st.DrawFn) -> ev.BattleDecided:
    """A decision, pieces joining, or both (BDC)."""
    decided, joins = draw(st.sampled_from([(True, False), (False, True), (True, True)]))
    joined = (
        tuple(draw(st.lists(feature_ids, min_size=1, max_size=3, unique=True))) if joins else ()
    )
    return ev.BattleDecided(
        area=draw(entity_ids),
        nation=draw(entity_ids),
        on=draw(in_world_dates),
        decision=draw(st.sampled_from(list(rb.Decision))) if decided else None,
        wake=draw(st.integers(0, 50)) if decided else None,
        joined=joined,
        added=draw(st.integers(len(joined), 15)) if joins else 0,
    )


@st.composite
def captures(draw: st.DrawFn) -> rh.Capture:
    """A capture count, a capital mark, or both."""
    counted, marked = draw(st.sampled_from([(True, False), (False, True), (True, True)]))
    return rh.Capture(
        by=draw(entity_ids) if counted else None,
        since=draw(in_world_dates) if counted else None,
        marked=draw(st.integers(min_value=0, max_value=50)) if marked else None,
        marked_on=draw(in_world_dates) if marked else None,
    )


world_maps = st.builds(
    tm.WorldMap,
    file=labels,
    sha256=sha256s,
    coords=st.sampled_from(["lonlat", "flat"]),
    box=st.none() | boxes,
    terrain=st.lists(
        st.builds(
            tm.Terrain,
            key=labels,
            kind=st.sampled_from(tm.TerrainKind),
            defence=st.integers(0, 2),
        ),
        max_size=2,
    ).map(tuple),
    regions=st.lists(
        st.builds(tm.Region, key=labels, name=labels, parent=st.none() | labels), max_size=2
    ).map(tuple),
    territories=st.lists(
        st.builds(
            tm.Territory,
            area=entity_ids,
            key=labels,
            name=labels,
            region=labels,
            terrain=labels,
            holder=st.none() | entity_ids,
            yields=st.dictionaries(labels, st.floats(0, 100, allow_nan=False), max_size=2),
            sites=st.lists(entity_ids, max_size=2).map(tuple),
            districts=st.lists(labels, max_size=2).map(tuple),
        ),
        max_size=2,
    ).map(tuple),
    sea_zones=st.lists(
        st.builds(
            tm.SeaZone, area=entity_ids, key=labels, name=labels, region=labels, terrain=labels
        ),
        max_size=2,
    ).map(tuple),
    adjacency=st.lists(
        st.builds(tm.Link, a=entity_ids, b=entity_ids, crossing=st.none() | labels), max_size=3
    ).map(tuple),
    ports=st.lists(
        st.builds(tm.Port, place=entity_ids, land=entity_ids, sea=entity_ids), max_size=2
    ).map(tuple),
    bases=st.lists(
        st.builds(
            tm.Base,
            place=entity_ids,
            land=st.none() | entity_ids,
            sea=st.none() | entity_ids,
            sides=st.lists(entity_ids, min_size=1, max_size=2).map(tuple),
            domains=st.lists(st.sampled_from(["land", "sea", "air"]), min_size=1, max_size=3).map(
                lambda d: tuple(dict.fromkeys(d))
            ),
        ),
        max_size=2,
    ).map(tuple),
    lift_pools=st.dictionaries(entity_ids, quantity_ids, max_size=2),
    capitals=st.dictionaries(entity_ids, entity_ids, max_size=2),
)


@st.composite
def piece_kinds(draw: st.DrawFn) -> rk.PieceKind:
    domain = draw(st.sampled_from(rk.Domain))
    return rk.PieceKind(
        key=draw(labels),
        name=draw(labels),
        domain=domain,
        days_per_step=draw(st.dictionaries(labels, st.integers(1, 30), max_size=3)),
        max_strength=draw(st.integers(1, 9)),
        fuel_per_step=draw(st.floats(0, 10, allow_nan=False)),
        range_steps=draw(st.integers(1, 6)) if domain is rk.Domain.AIR else None,
        detect=draw(st.integers(0, 100)),
        conceal=draw(st.integers(0, 100)),
        carries=tuple(draw(st.lists(labels, max_size=2))),
    )


resources = st.builds(
    rk.Resource, key=labels, name=labels, unit=labels, role=st.sampled_from(rk.Role)
)

realism_payloads = st.one_of(
    st.builds(
        ev.CampaignCreated,
        name=short_text,
        world=short_text,
        ruleset=st.just("realism"),
        rules=st.frozensets(st.sampled_from(Rule)),
    ),
    st.builds(ev.WarDeclared, war=wars()),
    st.builds(ev.MapDeclared, map=world_maps),
    st.builds(
        ev.KindsDeclared,
        pieces=st.lists(piece_kinds(), max_size=2).map(tuple),
        resources=st.lists(resources, max_size=2).map(tuple),
    ),
    st.builds(
        ev.CardsDeclared,
        cards=st.lists(seat_cards, max_size=2).map(tuple),
        feeds=st.lists(feeds, max_size=2).map(tuple),
        pipelines=st.lists(pipelines, max_size=2).map(tuple),
        templates=st.lists(mandate_templates(), max_size=2).map(tuple),
        topics=st.lists(topics, max_size=2).map(tuple),
    ),
    st.builds(ev.FeatureSet, feature=features()),
    st.builds(
        ev.PieceStepped,
        mark=labels,
        nation=entity_ids,
        left=entity_ids,
        entered=entity_ids,
        on=in_world_dates,
        cause=st.sampled_from(tm.StepCause),
    ),
    st.builds(
        ev.AreaHeld,
        area=entity_ids,
        holder=entity_ids,
        was=st.none() | entity_ids,
        on=in_world_dates,
    ),
    st.builds(
        ev.CaptureCounted,
        area=entity_ids,
        capture=st.none() | captures(),
    ),
    st.builds(
        ev.EconomySet,
        polity=entity_ids,
        pools=st.builds(
            econ.Pools,
            output=st.floats(0, 1e6, allow_nan=False),
            manpower=st.floats(0, 1e6, allow_nan=False),
        ),
        on=in_world_dates,
    ),
    st.builds(
        ev.YieldChanged,
        area=entity_ids,
        to=entity_ids,
        resource=labels,
        amount=st.floats(0, 100, allow_nan=False),
        on=in_world_dates,
        restart=st.none() | in_world_dates,
    ),
    st.builds(
        ev.TradeSet,
        line=st.builds(
            TradeLine,
            key=labels,
            exporter=entity_ids,
            importer=entity_ids,
            resource=labels,
            amount=st.floats(0, 100, allow_nan=False),
            cut=st.booleans(),
            source=st.none() | labels,
        ),
        on=in_world_dates,
    ),
    st.builds(
        ev.BattleOpened,
        battle=battles(),
        on=in_world_dates,
    ),
    battle_decisions(),
    st.builds(ev.IntelligenceDeclared, nations=st.lists(intelligences(), max_size=2).map(tuple)),
    st.builds(
        ev.GroupsDeclared,
        nations=st.lists(nation_groups(), max_size=2, unique_by=lambda n: n.nation).map(tuple),
    ),
    st.builds(
        ev.GroupMoved,
        polity=entity_ids,
        group=labels,
        support=st.integers(0, 100),
        change=st.integers(-100, 100),
        cause=st.sampled_from(list(rgrp.Cause)),
        used=st.integers(0, 6),
        on=in_world_dates,
    ),
    st.builds(ev.GroupProposed, proposal=proposals),
    st.builds(ev.OfferMade, offer=priced_offers),
    offer_settlements(),
    st.builds(
        ev.PostChanged,
        post=asset_ids,
        holder=entity_ids,
        to=st.none(),
        on=in_world_dates,
        cause=st.sampled_from(list(rc.PostCause)),
    ),
    st.builds(ev.AgreementOffered, offer=agreement_offers()),
    st.builds(ev.AgreementMade, agreement=agreements()),
    st.builds(
        ev.ClauseJudged,
        agreement_id=labels,
        clause=st.integers(0, 7),
        status=st.sampled_from(list(ragr.ClauseStatus)),
        on=in_world_dates,
        reason=st.text(max_size=300),
        against=st.none() | entity_ids,
        due=st.none() | in_world_dates,
    ),
    st.builds(ev.AgreementPublished, agreement_id=labels, by=entity_ids, on=in_world_dates),
    st.builds(ev.ConferenceCalled, conference=conferences()),
    st.builds(
        ev.VoteSealed,
        conference=labels,
        seat_id=seat_ids,
        vote=st.sampled_from(list(rconf.Vote)),
        wake=st.integers(0, 50),
    ),
    st.builds(ev.ConferenceTallied, conference=labels, tally=conference_tallies()),
    st.builds(
        ev.ReportMade,
        nation=entity_ids,
        piece=feature_ids,
        report=reports(),
        shift=st.none() | st.sampled_from(list(rdet.Shift)),
    ),
    st.builds(ev.AgentSet, nation=entity_ids, index=st.integers(0, 3), agent=agents()),
    st.builds(ev.CodebreakingSet, nation=entity_ids, level=st.integers(1, 3), on=in_world_dates),
    st.builds(
        ev.BattleRound,
        area=entity_ids,
        on=in_world_dates,
        scores=st.tuples(st.integers(-1, 30), st.integers(-1, 30)),
        draws=st.tuples(st.integers(0, 2), st.integers(0, 2)),
        lost=st.tuples(st.integers(0, 2), st.integers(0, 2)),
    ),
    st.builds(
        ev.BattleEnded,
        area=entity_ids,
        on=in_world_dates,
        ending=st.sampled_from(list(rb.Ending)),
        winner=entity_ids,
    ),
    st.builds(
        ev.StepRefused,
        mark=labels,
        nation=entity_ids,
        area=entity_ids,
        to=entity_ids,
        on=in_world_dates,
        reason=st.text(max_size=300),
    ),
    documents_issued(),
    st.builds(ev.DocumentWritten, doc_id=document_ids, prose=st.text(min_size=1, max_size=400)),
    st.builds(ev.DocumentRead, seat_id=seat_ids, doc_id=document_ids),
    st.builds(ev.DocumentFlagged, seat_id=seat_ids, doc_id=document_ids, flagged=st.booleans()),
    st.builds(ev.OrderDrafted, order=orders),
    st.builds(ev.OrderStepTaken, order_id=order_ids, outcome=step_outcomes()),
    st.builds(ev.OrderSettled, order_id=order_ids, status=st.sampled_from(sorted(rp.SETTLED))),
    st.builds(ev.QuantitySet, quantity=quantities),
    st.builds(
        ev.StanceChanged,
        seat_id=seat_ids,
        figure=entity_ids,
        standing=st.builds(
            rs.Standing,
            on=in_world_dates,
            stance=st.sampled_from(rs.Stance),
            score=st.integers(-20, 20),
            side=st.integers(-5, 5),
            disposition=st.integers(-5, 5),
            cause=st.sampled_from(rs.StanceCause),
            order=st.none() | order_ids,
        ),
    ),
    st.builds(
        ev.OpponentsRanked,
        seat_id=seat_ids,
        active=st.lists(entity_ids, max_size=4, unique=True).map(tuple),
    ),
    st.builds(
        ev.CardAmended,
        person=entity_ids,
        allies=st.lists(entity_ids, max_size=3).map(tuple),
        opposes=st.lists(
            st.builds(rc.Conflict, against=entity_ids, over=labels, irreducible=st.booleans()),
            max_size=3,
        ).map(tuple),
        answers=st.lists(
            st.builds(
                rans.Answer,
                key=labels,
                aim=st.integers(1, 3),
                when=st.builds(
                    rans.AnswerWhen,
                    lever=labels,
                    by=entity_ids,
                    human=st.booleans(),
                ),
                gate=st.frozensets(st.sampled_from(rs.Stance)),
                act=st.builds(rans.AnswerAct, lever=labels),
                delay_days=st.integers(0, 30),
                cooldown_days=st.integers(1, 365),
                helps=st.booleans(),
            ),
            max_size=2,
            unique_by=lambda a: a.key,
        ).map(tuple),
        voice=st.none() | st.text(max_size=200),
        addressed_as=st.none() | labels,
    ),
    in_world_dates.flatmap(
        lambda on: st.builds(
            ev.AnswerPlanned,
            figure=entity_ids,
            key=labels,
            on=st.just(on),
            due=st.integers(0, 30).map(lambda n: on + timedelta(days=n)),
            cause=st.none() | order_ids,
            toward=st.none() | entity_ids,
        )
    ),
    st.builds(
        ev.AnswerMade,
        figure=entity_ids,
        key=labels,
        on=in_world_dates,
        order=order_ids,
    ),
    st.builds(
        ev.CounselHeld,
        seat_id=seat_ids,
        person=entity_ids,
        channel=channels,
        text=st.text(max_size=400),
    ),
    st.builds(
        ev.DirectiveGiven,
        seat_id=seat_ids,
        person=entity_ids,
        channel=channels,
        text=st.text(max_size=400),
        order_id=order_ids,
        lever=labels,
        params=param_maps,
    ),
)


# --- engine v2 ------------------------------------------------------------------


@st.composite
def measure_clauses(draw: st.DrawFn) -> rx.Clause:
    kind = draw(st.sampled_from(list(rx.ClauseKind)))
    amount = draw(st.integers(0, 10**9)) if kind is rx.ClauseKind.MONEY else None
    return rx.Clause(kind=kind, subject=draw(labels), amount=amount)


@st.composite
def dispositions(draw: st.DrawFn) -> rx.ShiftDisposition:
    of, toward = draw(st.lists(entity_ids, min_size=2, max_size=2, unique=True))
    change = draw(st.sampled_from([-2, -1, 1, 2]))
    return rx.ShiftDisposition(of=of, toward=toward, change=change)


@st.composite
def development_events(draw: st.DrawFn) -> ScheduledEvent:
    start = draw(in_world_dates)
    figures = st.builds(
        rx.MoveFigure, quantity=quantity_ids, percent=st.sampled_from([-10, -3, 1, 10])
    )
    return ScheduledEvent(
        scheduled_id=draw(scheduled_ids),
        fire_at_tick=0,
        name=draw(short_text),
        scope=draw(scopes()),
        source=ScheduleSource.DEVELOPMENT,
        on_date=start,
        window_end=start + timedelta(days=draw(st.integers(0, 60))),
        chance=draw(st.integers(1, 100)),
        category=draw(st.sampled_from(list(DevelopmentCategory))),
        condition=draw(st.none() | conditions),
        headline=draw(st.none() | st.text(min_size=1, max_size=60)),
        subject=draw(st.none() | entity_ids),
        effects=tuple(draw(st.lists(figures | dispositions(), max_size=4))),
        asks=tuple(draw(st.lists(labels, max_size=2))),
    )


any_scheduled_events = scheduled_events | history_events | development_events()


move_forces = st.one_of(
    st.builds(
        rx.MoveForce,
        force=feature_ids,
        to=entity_ids,
        posture=st.none() | st.sampled_from(list(rx.Posture)),
    ),
    st.builds(
        rx.MoveForce, force=feature_ids, to=st.none(), posture=st.sampled_from(list(rx.Posture))
    ),
)

effects: st.SearchStrategy[rx.Effect] = st.one_of(
    move_forces,
    st.builds(
        rx.SetEngagement,
        force=st.none() | feature_ids,
        zone=labels,
        rule=st.sampled_from(list(rx.Engagement)),
        contingency=st.none() | contingencies(),
        concealed=st.none() | st.booleans(),
    ),
    st.builds(
        rx.Allocate,
        recipient=entity_ids,
        what=labels,
        amount=st.integers(0, 10**9),
        unit=labels,
        intel=st.none() | st.just(rx.IntelOrder.CODEBREAKING),
    ),
    st.builds(rx.Appointment, person=entity_ids, office=labels, appoint=st.booleans()),
    st.builds(
        rx.ProposeMeasure,
        title=labels,
        clauses=st.lists(measure_clauses(), min_size=1, max_size=4).map(tuple),
    ),
    st.builds(rx.MakeStatement, theme=labels, audience=st.none() | entity_ids),
    st.builds(rx.Investigate, target=entity_ids, question=labels),
    st.builds(
        rx.Investigate,
        target=entity_ids,
        question=labels,
        intel=st.just(rx.IntelOrder.RECON),
        flier=feature_ids,
    ),
    st.builds(
        rx.Investigate, target=entity_ids, question=labels, intel=st.just(rx.IntelOrder.AGENT)
    ),
    st.builds(
        rx.Deal,
        counterparty=entity_ids,
        offer=st.lists(labels, min_size=1, max_size=3).map(tuple),
        ask=st.lists(labels, max_size=3).map(tuple),
        accept=st.booleans(),
    ),
    agreement_deals(),
    st.builds(rx.Deal, counterparty=entity_ids, publish=labels),
    dispositions(),
    st.builds(rx.Disclosure, fact=fact_ids, reveal=st.booleans()),
)


@st.composite
def routed_parts(draw: st.DrawFn) -> rx.RoutedPart:
    route = draw(st.sampled_from(list(rx.Route)))
    fields: dict[str, object] = {"route": route, "effect": draw(st.none() | effects)}
    if route is rx.Route.COMMAND:
        fields |= {"domain": draw(labels), "executor": draw(st.none() | entity_ids)}
        done = draw(st.sampled_from(["no", "done", "refused"]))
        if done != "no":
            fields["executed"] = draw(in_world_dates)
            if done == "done":
                fields["fidelity"] = draw(st.sampled_from(list(rx.Fidelity)))
            else:
                fields["refusal"] = draw(labels)
    elif route is rx.Route.PROCESS:
        fields["pipeline"] = draw(pipeline_ids)
    else:
        fields["target"] = draw(entity_ids)
        if draw(st.booleans()):
            fields |= {"decided": draw(in_world_dates), "accepted": draw(st.booleans())}
    fields["applied"] = draw(st.none() | in_world_dates)
    fields["estimated"] = tuple(draw(st.lists(effects, max_size=2)))
    fields["reason"] = draw(st.text(max_size=100))
    return rx.RoutedPart.model_validate(fields)


routed_orders = st.builds(
    rx.RoutedOrder,
    order_id=order_ids,
    issuer=seat_ids,
    filed=in_world_dates,
    parts=st.lists(routed_parts(), min_size=1, max_size=3).map(tuple),
)


@st.composite
def mandates(draw: st.DrawFn) -> ra.Mandate:
    kind = draw(st.sampled_from(list(ra.MandateKind)))
    seat = draw(seat_ids)
    issued = draw(st.dates(min_value=date(1, 1, 1), max_value=date(2025, 1, 1)))
    return ra.Mandate(
        mandate_id=draw(mandate_ids),
        seat_id=seat,
        kind=kind,
        issuer=draw(entity_ids) if kind is ra.MandateKind.ORDER else None,
        text=draw(short_text),
        condition=draw(conditions),
        issued=issued,
        expires=issued + timedelta(days=draw(st.integers(1, 365))),
        cause=draw(order_ids) if kind is ra.MandateKind.BLOWBACK else None,
        status=draw(st.sampled_from(list(ra.MandateStatus))),
        scope=Scope(visibility=Visibility.PRIVATE, known_by=frozenset({seat})),
    )


asks = st.builds(ra.Ask, ask=short_text, effect=st.none() | effects)


def _options(n_asks: tuple[int, int]) -> st.SearchStrategy[ra.Option]:
    return st.builds(
        ra.Option,
        label=short_text,
        asks=st.lists(asks, min_size=n_asks[0], max_size=n_asks[1]).map(tuple),
        to=st.none() | entity_ids,
        risk=st.text(max_size=60),
        historical=st.just(False),
    )


offers = st.one_of(
    st.builds(
        ra.Offer,
        mandate_id=st.none() | mandate_ids,
        style=st.just(ra.PlayStyle.BEGINNER),
        options=st.lists(_options((1, 2)), min_size=3, max_size=4).map(tuple),
    ),
    st.builds(
        ra.Offer,
        mandate_id=st.none() | mandate_ids,
        style=st.just(ra.PlayStyle.GUIDED),
        options=st.lists(_options((3, 5)), min_size=1, max_size=1).map(tuple),
    ),
)


group_nudges = st.builds(
    rx.GroupNudge, nation=entity_ids, group=labels, change=st.sampled_from([-3, -1, 1, 3])
)


@st.composite
def effects_estimated(draw: st.DrawFn) -> ev.EffectsEstimated:
    failed = draw(st.booleans())
    return ev.EffectsEstimated(
        order_id=draw(order_ids),
        part=draw(st.integers(0, 7)),
        effects=() if failed else tuple(draw(st.lists(effects | group_nudges, max_size=3))),
        reason=draw(st.text(max_size=100)) if failed else draw(st.text(min_size=1, max_size=100)),
        rationale="" if failed else draw(st.text(max_size=100)),
        failed=failed,
    )


@st.composite
def orders_executed(draw: st.DrawFn) -> ev.OrderExecuted:
    done = draw(st.booleans())
    return ev.OrderExecuted(
        order_id=draw(order_ids),
        part=draw(st.integers(0, 7)),
        on=draw(in_world_dates),
        fidelity=draw(st.sampled_from(list(rx.Fidelity))) if done else None,
        refusal="" if done else draw(labels),
    )


effects_applied = st.builds(
    ev.EffectsApplied,
    order_id=order_ids,
    part=st.integers(0, 7),
    on=in_world_dates,
    revealed=st.lists(fact_ids, max_size=3).map(tuple),
)

influence_decided = st.builds(
    ev.InfluenceDecided,
    order_id=order_ids,
    part=st.integers(0, 7),
    on=in_world_dates,
    accepted=st.booleans(),
    reason=st.text(max_size=100),
)

request_answered = st.builds(
    ev.RequestAnswered,
    order_id=order_ids,
    part=st.integers(0, 7),
    accepted=st.booleans(),
)


@st.composite
def steps_chosen(draw: st.DrawFn) -> ev.StepChosen:
    action = draw(st.sampled_from(list(rp.StepAction)))
    amended = draw(st.dictionaries(labels, param_values, min_size=1, max_size=2))
    return ev.StepChosen(
        order_id=draw(order_ids),
        step=draw(st.integers(0, 11)),
        action=action,
        amended=amended if action is rp.StepAction.AMEND else {},
    )


deadlines = st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2040, 1, 1))

engine_v2_payloads = st.one_of(
    st.builds(ev.OrderRouted, order=routed_orders),
    orders_executed(),
    effects_estimated(),
    effects_applied,
    influence_decided,
    request_answered,
    steps_chosen(),
    st.builds(ev.MandateIssued, mandate=mandates()),
    st.builds(
        ev.MandateSettled,
        mandate_id=mandate_ids,
        status=st.sampled_from([s for s in ra.MandateStatus if s is not ra.MandateStatus.LIVE]),
    ),
    st.builds(
        ev.WakeOpened,
        wake=st.integers(0, 500),
        deadline=deadlines,
        opened_at=st.none() | deadlines,
    ),
    st.builds(
        ev.WakeCommitted,
        wake=st.integers(0, 500),
        seat_id=seat_ids,
        by_aide=st.booleans(),
        at=st.none() | deadlines,
        aide_orders=st.lists(order_ids, max_size=3).map(tuple),
    ),
    st.builds(
        ev.WakeClosed,
        wake=st.integers(0, 500),
        timed_out=st.lists(seat_ids, max_size=3).map(tuple),
        how=st.none() | st.sampled_from(["all_committed", "deadline", "host"]),
    ),
    st.builds(
        ev.PlayStyleSet,
        seat_id=seat_ids,
        style=st.sampled_from(list(ra.PlayStyle)),
        standing=st.frozensets(st.sampled_from(sorted(rx.IRREVERSIBLE)), max_size=2),
    ),
    st.builds(
        ev.SeatHandover,
        entity_id=entity_ids,
        controller=st.sampled_from(list(Controller)),
    ),
    st.builds(
        ev.OptionsOffered,
        seat_id=seat_ids,
        wake=st.integers(0, 500),
        offers=st.lists(offers, max_size=2).map(tuple),
    ),
)

payloads = st.one_of(
    realism_payloads,
    engine_v2_payloads,
    st.builds(ev.CampaignCreated, name=short_text, world=short_text),
    st.builds(ev.SettingsSet, settings=settings),
    st.builds(ev.EntityCreated, entity=entities),
    st.builds(ev.AssetCreated, asset=assets),
    st.builds(ev.RelationshipSet, relationship=relationships),
    st.builds(ev.MeterCreated, meter=meters),
    st.builds(ev.ClockCreated, clock=clocks),
    st.builds(ev.FactAsserted, fact=facts),
    st.builds(ev.CommitmentCreated, commitment=commitments),
    st.builds(ev.SeatCreated, seat=seats),
    st.builds(ev.AgentAssigned, seat_id=seat_ids, agent=entity_ids, persona=personas),
    st.builds(ev.SeatStatusSet, seat_id=seat_ids, cause=short_text),
    st.builds(ev.OrderReceived, seat_id=seat_ids, text=st.text(max_size=400)),
    st.builds(ev.IntentFiled, intent=intents, from_order=st.none() | event_ids),
    st.builds(ev.IntentRejected, intent_id=intent_ids, detail=short_text),
    st.builds(ev.ClarificationAsked, seat_id=seat_ids, from_order=event_ids, question=short_text),
    st.builds(ev.FeasibilityRated, intent_id=intent_ids),
    st.builds(
        ev.Rolled,
        intent_id=intent_ids,
        seed=ulid,
        exposure_roll=st.integers(0, 99),
        exposed=st.booleans(),
    ),
    st.builds(
        ev.DeltaProposed,
        intent_id=st.none() | intent_ids,
        deltas=st.lists(deltas, max_size=4).map(tuple),
    ),
    st.builds(ev.DeltaRejected, delta_id=delta_ids, detail=short_text),
    st.builds(ev.DeltaApplied, intent_id=st.none() | intent_ids, delta=deltas),
    st.builds(ev.OperationOpened, intent_id=intent_ids, clock_id=clock_ids, seat_id=seat_ids),
    st.builds(ev.OperationResolved, intent_id=intent_ids, clock_id=clock_ids, seat_id=seat_ids),
    st.builds(ev.ScheduledEventFired, scheduled_id=scheduled_ids),
    st.builds(ev.ContestCreated, contest=contests()),
    st.builds(
        ev.ContestMoved,
        contest_id=contest_ids,
        change=st.integers(-200, 200),
        days=st.integers(0, 400),
        cause=st.sampled_from(["momentum", "order"]),
    ),
    st.builds(ev.ContestDecided, contest_id=contest_ids, winner=st.none() | entity_ids),
    st.builds(ev.ScheduledEventCreated, scheduled=any_scheduled_events),
    st.builds(ev.ScheduledEventSkipped, scheduled_id=scheduled_ids),
    st.builds(ev.DivergenceChanged, change=st.integers(-100, 100), reason=short_text),
    st.builds(ev.DateAdvanced, to=in_world_dates),
    st.builds(
        ev.NarrationWritten,
        seat_id=seat_ids,
        text=st.text(max_size=400),
        from_deltas=st.lists(delta_ids, max_size=4).map(tuple),
    ),
    st.builds(ev.StatementIssued, seat_id=seat_ids, intent_id=intent_ids, text=short_text),
    st.builds(
        ev.SessionZeroOpened, start=short_text, notes=st.lists(short_text, max_size=2).map(tuple)
    ),
    st.builds(
        ev.CharacterListed,
        character=st.builds(
            Character,
            entity_id=entity_ids,
            pitch=short_text,
            reach=short_text,
            composite=st.booleans(),
            means=st.frozensets(asset_ids, max_size=3),
            claimed_by=st.none() | seat_ids,
        ),
    ),
    st.builds(ev.CharacterClaimed, seat_id=seat_ids, entity_id=entity_ids),
    st.builds(ev.CharacterReleased, seat_id=seat_ids, entity_id=entity_ids),
    st.builds(ev.SessionZeroClosed),
    st.builds(
        ev.SeasonEnded,
        winners=st.lists(seat_ids, max_size=3).map(tuple),
        revealed=st.integers(0, 50),
    ),
    st.builds(ev.GoalSet, goal=goals()),
    st.builds(ev.GoalProgressed, goal_id=goal_ids, parts_met=st.integers(0, 8)),
    st.builds(ev.GoalMet, goal_id=goal_ids),
    st.builds(ev.GoalUndone, goal_id=goal_ids),
    st.builds(
        ev.GoalProposed,
        seat_id=seat_ids,
        route=st.sampled_from(["history", "could_have", "own"]),
        options=st.lists(
            conditions.map(lambda c: ev.GoalOption(text="goal", condition=c, kind=g.goal_kind(c))),
            max_size=3,
        ).map(tuple),
    ),
    st.builds(ev.GoalApproved, goal_id=goal_ids),
    st.builds(
        ev.BriefingDelivered,
        seat_id=seat_ids,
        narration=event_ids,
        channel=short_text,
        idempotency_key=ulid,
    ),
    st.builds(ev.TickOpened, intents_frozen=st.lists(intent_ids, max_size=6).map(tuple)),
    st.builds(ev.TickStageCompleted),
    st.builds(
        ev.TickClosed,
        quiet=st.booleans(),
        costs=st.lists(call_costs, max_size=3).map(tuple),
        state_hash=ulid,
    ),
    st.builds(
        ev.CostLogged,
        seat_id=st.none() | seat_ids,
        purpose=short_text,
        costs=st.lists(call_costs, max_size=3).map(tuple),
    ),
    st.builds(ev.Sealed, key_id=short_text),
    st.builds(
        ev.AdminRead,
        actor=short_text,
        events=st.lists(event_ids, max_size=4).map(tuple),
        purpose=short_text,
    ),
)

events = st.builds(
    ev.Event,
    event_id=event_ids,
    campaign_id=campaign_ids,
    seq=st.integers(0, 10**6),
    tick=st.integers(0, 500),
    actor=st.none() | seat_ids,
    scope=scopes(),
    payload=payloads,
    versions=versions,
    payload_enc=st.none() | st.binary(max_size=32),
)

ALL_MODEL_STRATEGIES: dict[str, st.SearchStrategy[object]] = {
    "Settings": cast(st.SearchStrategy[object], settings),
    "Entity": cast(st.SearchStrategy[object], entities),
    "Asset": cast(st.SearchStrategy[object], assets),
    "Relationship": cast(st.SearchStrategy[object], relationships),
    "Meter": cast(st.SearchStrategy[object], meters),
    "Clock": cast(st.SearchStrategy[object], clocks),
    "Fact": cast(st.SearchStrategy[object], facts),
    "ScheduledEvent": cast(st.SearchStrategy[object], any_scheduled_events),
    "Contest": cast(st.SearchStrategy[object], contests()),
    "Commitment": cast(st.SearchStrategy[object], commitments),
    "Seat": cast(st.SearchStrategy[object], seats),
    "Intent": cast(st.SearchStrategy[object], intents),
    "Goal": cast(st.SearchStrategy[object], goals()),
    "Event": cast(st.SearchStrategy[object], events),
    "SeatCard": cast(st.SearchStrategy[object], seat_cards),
    "Topic": cast(st.SearchStrategy[object], topics),
    "Feed": cast(st.SearchStrategy[object], feeds),
    "Pipeline": cast(st.SearchStrategy[object], pipelines),
    "Order": cast(st.SearchStrategy[object], orders),
    "DocumentView": cast(st.SearchStrategy[object], document_views()),
    "Quantity": cast(st.SearchStrategy[object], quantities),
    "RoutedOrder": cast(st.SearchStrategy[object], routed_orders),
    "Mandate": cast(st.SearchStrategy[object], mandates()),
    "Offer": cast(st.SearchStrategy[object], offers),
    "Domain": cast(st.SearchStrategy[object], domains),
    "Feature": cast(st.SearchStrategy[object], features()),
    "WorldMap": cast(st.SearchStrategy[object], world_maps),
    "PieceKind": cast(st.SearchStrategy[object], piece_kinds()),
    "Resource": cast(st.SearchStrategy[object], resources),
    "MandateTemplate": cast(st.SearchStrategy[object], mandate_templates()),
}
