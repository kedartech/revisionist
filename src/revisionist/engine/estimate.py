"""The estimator (engine v2, spec §8.3): the free-play rule.

For a routed part no code rule covers (``RoutedPart.effect`` is None), one
engine-side call returns typed effects from the closed vocabulary
(``core.realism.effect``) and a reason written from the issuer's view. Code clamps
the effects to the bounds and lands them as ``EffectsEstimated``; a replay reads
that event and never calls the model again.

Contract names only (engine-v2 addendum). Wave A4 builds the prompt, transport,
clamp, failure path and recording under these names.

Free writing (FWG). With ``groups`` on, a statement or a measure is ruled on for the
groups at home: its ruling holds group nudges. Words that name one of the issuer's
nation's themes take the theme's moves, and no model reads them. Words that name none are
read only with ``writing`` on, by one call per part (``GROUP_CALL_CLASS``) whose request
is built from the issuer's own view and the words alone (``group_prompt``), never from the
truth, so no nudge can follow a fact the issuer cannot see. With ``writing`` off, or when
that call fails, no group moves and the reason says so. The referee's own request and
schema hold no nudge.
"""

import json
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any, Literal

from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core._base import Model
from revisionist.core.canary import scan_text
from revisionist.core.events import CallCost, Event
from revisionist.core.fold import FoldError, _check_effect
from revisionist.core.ids import EntityId, OrderId, QuantityId
from revisionist.core.project import project
from revisionist.core.realism import battle, detect, groups
from revisionist.core.realism.apply import account_by
from revisionist.core.realism.effect import (
    DISPOSITION_CAP,
    FIGURE_CAP,
    GROUP_DAY_CAP,
    Deal,
    EffectKind,
    EstimatedEffect,
    GroupNudge,
    MakeStatement,
    MoveFigure,
    ProposeMeasure,
    RoutedOrder,
    RoutedPart,
    RulingEffect,
    ShiftDisposition,
)
from revisionist.core.realism.war import polity_of
from revisionist.core.state import Rule, State, View
from revisionist.engine.llm import Request, Transport, TransportError, cli_schema, prompt_text

ESTIMATOR_MODEL = "claude-sonnet-5-5"
"""[proposed] ``REVISIONIST_MODEL_ESTIMATOR`` overrides it per call."""
CALL_CLASS = "estimator"
"""``Request.call_class`` and ``CallCost.call_class`` for every estimator call."""
PROMPT = "estimator"
"""The system prompt: ``engine/prompts/estimator.md``, read by ``prompt_text``."""
RECORDING = "realism-estimator-autumn.json"
"""Recorded replies under ``tests/recordings/``, keyed by ``Request.key()``."""

REASON_WITHHELD = "The referee's account of this cannot be shown to you."
"""[proposed] Stands in for a reason that named something the issuer must not know."""
FAILED_REASON = "No ruling came back on this; it stands as you gave it, unresolved."
"""[proposed] What the paper says when the estimate failed."""

GROUP_CALL_CLASS = "group_nudge"
"""``Request.call_class`` for the call that reads free writing for the groups at home."""
GROUP_PROMPT = "group_nudge"
"""Its system prompt: ``engine/prompts/group_nudge.md``."""
GROUPS_UNHEARD = "None of our groups at home will take these words as meant for them."
"""[proposed] Words that name no theme, with ``writing`` off, or a measure's title that
names none: no group moves."""
GROUPS_FAILED = "No word has come of how our groups at home took this; none of them moved."
"""[proposed] The groups call failed or gave nothing usable: no group moved."""
GROUPS_HEARD = "Our groups at home have taken up the words."
"""[proposed] Words that name a theme the nation lists: its groups move by the table."""

MAX_EFFECTS = 8
"""The event's cap on effects per part."""
REASON_CHARS = 600
RATIONALE_CHARS = 2000


class Estimate(Model):
    """Engine-side result of one estimator call. Never stored."""

    event: ev.EffectsEstimated
    cost: CallCost | None = None
    dropped: tuple[str, ...] = ()
    """Why each proposed effect was cut, for logs and tests."""


class _Ruling(Model):
    """The model's reply. No cap on effects: the clamp cuts and says so."""

    effects: tuple[RulingEffect, ...]
    reason: str
    rationale: str


class _Nudge(Model):
    """One group nudge as the model gives it. ``nation`` None: the issuer's own. The change
    is not bounded here: the clamp drops what is past the cap and says so."""

    kind: Literal["group"] = "group"
    group: str
    change: int
    nation: EntityId | None = None


class _Nudges(Model):
    """The model's reply on how the groups take the words."""

    effects: tuple[_Nudge, ...]
    reason: str
    rationale: str


GROUP_SCHEMA: dict[str, Any] = _Nudges.model_json_schema()
"""The group nudge only."""

ESTIMATOR_SCHEMA: dict[str, Any] = _Ruling.model_json_schema()
"""Closed vocabulary only: a quantity has no kind here but a figure's bounded move, so a
reply that sets one fails."""

_NAMED = ("of", "toward", "person", "recipient", "audience", "target", "counterparty")


def _named(part: RoutedPart) -> list[EntityId]:
    found: list[EntityId | None] = [part.target, part.executor]
    if part.effect is not None:
        found += [getattr(part.effect, f, None) for f in _NAMED]
    return [e for e in dict.fromkeys(found) if e is not None]


def estimator_prompt(state: State, order_id: OrderId, part: int) -> str:
    """Truth the referee needs, compact: the part, the cards involved, the world's objects."""
    order = state.routed[order_id]
    routed = order.parts[part]
    issuer = state.seats[order.issuer]
    reported_by = account_by(state, order, part)
    cards = {
        str(who): state.cards[who].model_dump(mode="json", exclude={"voice"}, exclude_none=True)
        for who in dict.fromkeys([issuer.embodies, *_named(routed)])
        if who in state.cards
    }
    on_cards = {f for c in cards.values() for f in c.get("feeds", ())}
    reported = {q for f in on_cards if f in state.feeds for q in state.feeds[f].reports}
    world = {
        "date": str(state.in_world_date or order.filed),
        "order": {
            "id": order_id,
            "issuer": issuer.name,
            "issuer_entity": issuer.embodies,
            "filed": str(order.filed),
            "part": routed.view().model_dump(mode="json", exclude_none=True),
            "asked": routed.ask,
            "reported_by": (
                state.entities[reported_by].name
                if reported_by != issuer.embodies
                else "the issuer's own staff"
            ),
        },
        "cards": cards,
        "entities": [
            {"id": e.entity_id, "name": e.name, "kind": e.kind.value}
            for e in state.entities.values()
        ],
        "features": [
            {
                "id": f.feature_id,
                "name": f.name,
                "kind": f.kind.value,
                "places": f.places,
                "in_service": str(f.in_service) if f.in_service else None,
            }
            for f in state.features.values()
        ],
        "facts": [
            {
                "id": x.fact_id,
                "subject": x.subject,
                "predicate": x.predicate,
                "obj": x.obj,
                "truth": x.truth,
            }
            for x in state.facts.values()
        ],
        "figures": [
            {"id": q.quantity_id, "name": q.name, "value": q.value, "unit": q.unit}
            for q in sorted(state.quantities.values(), key=lambda q: q.quantity_id)
            if q.estimable and q.value is not None and q.quantity_id in reported
        ],
        "rules": {
            "effect_kinds": sorted(k.value for k in EffectKind if k is not EffectKind.GROUP),
            "disposition_cap": DISPOSITION_CAP,
            "figure_cap": FIGURE_CAP,
            "max_effects": MAX_EFFECTS,
        },
    }
    return (
        "## World (truth) and the part to rule on\n"
        + json.dumps(world, separators=(",", ":"), default=str)
        + "\n\nReturn effects, a reason for the issuer and your rationale. Echo ids exactly."
    )


def group_prompt(view: View, words: str) -> str:
    """What the groups call reads: the issuer's own view, never the truth, and the words.
    From the view: the date, the issuer and its nation, and that nation's groups by name."""
    own = next(iter(view.groups.declared.items()), None)
    nation = view.entities.get(own[0]) if own is not None else None
    asked = {
        "date": str(view.in_world_date) if view.in_world_date else None,
        "issuer": view.me.name,
        "nation": {"id": nation.entity_id, "name": nation.name} if nation is not None else None,
        "groups": [{"key": g.key, "name": g.name, "kind": g.kind} for g in own[1]] if own else [],
        "words": words,
        "rules": {"group_cap": GROUP_DAY_CAP, "max_effects": groups.MAX_GROUP_EFFECTS},
    }
    return (
        "## The issuer's own view and its words\n"
        + json.dumps(asked, separators=(",", ":"), default=str)
        + "\n\nReturn the group nudges these words earn, a reason for the issuer and your"
        " rationale. Echo group keys exactly."
    )


def aide_orders(events: Iterable[Event]) -> frozenset[OrderId]:
    """The orders an aide filed for an absent seat, from the commits that name them."""
    return frozenset(
        o
        for e in events
        if isinstance(e.payload, ev.WakeCommitted) and e.payload.by_aide
        for o in e.payload.aide_orders
    )


def clamp(
    state: State,
    order: RoutedOrder,
    effects: Sequence[EstimatedEffect],
    on: date,
    *,
    aide: bool = False,
) -> tuple[tuple[EstimatedEffect, ...], tuple[str, ...]]:
    """Code bounds on whatever the model proposed. Returns the survivors and a line per cut.

    An order the aide filed keeps no deal: a deal is the seat's own to strike; in a battle
    game it keeps no press, withdrawal or change of contingency (BDC rule 8).

    The disposition cap is per order (spec §8.3): what the order's other parts
    already move, given or estimated, counts against it. A figure's percent is held
    to ``FIGURE_CAP`` per order the same way."""
    kept: list[EstimatedEffect] = []
    dropped: list[str] = []
    nudges = 0
    moved: dict[tuple[EntityId, EntityId], int] = {}
    scaled: dict[QuantityId, int] = {}
    for other in order.parts:
        for given in (other.effect, *other.estimated):
            if isinstance(given, ShiftDisposition):
                pair = (given.of, given.toward)
                total = moved.get(pair, 0) + given.change
                moved[pair] = max(-DISPOSITION_CAP, min(DISPOSITION_CAP, total))
            elif isinstance(given, MoveFigure):
                scaled[given.quantity] = scaled.get(given.quantity, 0) + given.percent
    for effect in effects:
        if aide and isinstance(effect, Deal):
            dropped.append("deal: the aide makes no deal")
            continue
        if aide:  # BDC rule 8: in a battle game the aide neither presses nor withdraws
            kept_ = battle.aide_may(state, effect)
            if kept_ is None:
                dropped.append(f"{effect.kind}: the aide neither presses nor withdraws")
                continue
            if kept_ is not effect:
                dropped.append(f"{effect.kind}: the aide's press, withdrawal or contingency")
                effect = kept_
        if aide:  # IOR rule 7: the aide places no agent, funds nothing, conceals nothing
            spy = detect.aide_may(effect)
            if spy is None:
                dropped.append(f"{effect.kind}: the aide places no agent and funds nothing")
                continue
            if spy is not effect:
                dropped.append(f"{effect.kind}: the aide conceals nothing")
                effect = spy
        try:
            # The fold's own guard, so nothing lands that the fold would refuse.
            _check_effect(state, effect, f"order {order.order_id}", on)
        except FoldError as exc:
            dropped.append(f"{effect.kind}: {exc}")
            continue
        if isinstance(effect, ShiftDisposition):
            pair = (effect.of, effect.toward)
            before = moved.get(pair, 0)
            after = max(-DISPOSITION_CAP, min(DISPOSITION_CAP, before + effect.change))
            if after == before:
                dropped.append(f"disposition: {effect.of} toward {effect.toward} is at the cap")
                continue
            moved[pair] = after
            if after - before != effect.change:
                dropped.append(f"disposition: {effect.change:+d} cut to {after - before:+d}")
                effect = effect.model_copy(update={"change": after - before})
        if isinstance(effect, GroupNudge):
            issuer = polity_of(state, state.seats[order.issuer].embodies)
            problem = groups.nudge_problem(state, issuer, effect)
            if problem:
                dropped.append(f"group: {problem}")
                continue
            if nudges == groups.MAX_GROUP_EFFECTS:
                dropped.append(f"group: over the {groups.MAX_GROUP_EFFECTS}-nudge cap")
                continue
            nudges += 1
        if isinstance(effect, MoveFigure):
            before = scaled.get(effect.quantity, 0)
            after = max(-FIGURE_CAP, min(FIGURE_CAP, before + effect.percent))
            if after == before:
                dropped.append(f"figure: {effect.quantity} is at the cap")
                continue
            scaled[effect.quantity] = after
            if after - before != effect.percent:
                dropped.append(f"figure: {effect.percent:+d} cut to {after - before:+d}")
                effect = effect.model_copy(update={"percent": after - before})
        kept.append(effect)
    for effect in kept[MAX_EFFECTS:]:
        dropped.append(f"{effect.kind}: over the {MAX_EFFECTS}-effect cap")
    return tuple(kept[:MAX_EFFECTS]), tuple(dropped)


def _writing(part: RoutedPart) -> tuple[str, str] | None:
    """A part read for the groups at home: (the words a theme is looked for in, the words
    the groups call reads). A statement, or a measure, which is read for its title only."""
    match part.effect:
        case MakeStatement(theme=theme):
            return f"{theme} {part.ask}", part.ask or theme
        case ProposeMeasure(title=title):
            return title, ""
    return None


def reads_groups(state: State, order: RoutedOrder, part: int) -> bool:
    """Whether a part is read for the groups at home: ``groups`` on, a refusal aside, and
    writing from an issuer whose nation has groups."""
    routed = order.parts[part]
    if not groups.on(state) or routed.refusal or _writing(routed) is None:
        return False
    nation = polity_of(state, state.seats[order.issuer].embodies)
    return nation is not None and bool(groups.of(state, nation))


class GroupReading(Model):
    """How a part's words reach the groups at home. Engine side; never stored."""

    effects: tuple[GroupNudge, ...] = ()
    reason: str = ""
    cost: CallCost | None = None
    dropped: tuple[str, ...] = ()


def _as_nudges(nation: EntityId, raw: Sequence[_Nudge]) -> tuple[list[EstimatedEffect], list[str]]:
    """The model's nudges as typed effects: the issuer's nation where it names none, and
    a change past ``GROUP_DAY_CAP``, or none, dropped."""
    kept: list[EstimatedEffect] = []
    dropped: list[str] = []
    for n in raw:
        if n.change == 0 or abs(n.change) > GROUP_DAY_CAP:
            dropped.append(f"group: {n.change:+d} on {n.group} is past the {GROUP_DAY_CAP} cap")
            continue
        kept.append(GroupNudge(nation=n.nation or nation, group=n.group, change=n.change))
    return kept, dropped


def read_groups(state: State, order: RoutedOrder, part: int, transport: Transport) -> GroupReading:
    """The group nudges a part's words earn (rules 3 to 7). A theme the issuer's nation
    lists, named in the words, gives its table and calls no model. Words with no theme
    are read by one call with ``writing`` on, from the issuer's view and the words alone;
    with it off, or when that call fails, no group moves and the reason says so."""
    routed = order.parts[part]
    found = _writing(routed)
    nation = polity_of(state, state.seats[order.issuer].embodies)
    if found is None or nation is None:
        return GroupReading()
    named, words = found
    theme = groups.named_theme(state, nation, named)
    if theme is not None:
        return GroupReading(effects=groups.theme_nudges(nation, theme), reason=GROUPS_HEARD)
    if not words.strip() or Rule.WRITING not in state.rules:
        return GroupReading(reason=GROUPS_UNHEARD)
    request = Request(
        call_class=GROUP_CALL_CLASS,
        model=ESTIMATOR_MODEL,
        system=prompt_text(GROUP_PROMPT),
        prompt=group_prompt(project(state, order.issuer), words),
        schema=cli_schema(GROUP_SCHEMA),
    )
    try:
        reply = transport.call(request)
    except TransportError as exc:
        return GroupReading(reason=GROUPS_FAILED, dropped=(f"transport: {exc}"[:300],))
    cost = reply.cost(GROUP_CALL_CLASS)
    try:
        ruling = _Nudges.model_validate(reply.output)
    except ValidationError as exc:
        return GroupReading(
            reason=GROUPS_FAILED, cost=cost, dropped=(f"invalid reply: {exc.error_count()}",)
        )
    typed, cut = _as_nudges(nation, ruling.effects)
    kept, dropped = clamp(state, order, typed, state.in_world_date or order.filed)
    reason = ruling.reason.strip()
    if not reason or scan_text(state, order.issuer, reason):
        reason = REASON_WITHHELD
    return GroupReading(
        effects=tuple(e for e in kept if isinstance(e, GroupNudge)),
        reason=reason[:REASON_CHARS],
        cost=cost,
        dropped=(*cut, *dropped),
    )


def estimate(
    state: State, order_id: OrderId, part: int, transport: Transport, *, aide: bool = False
) -> Estimate:
    """Rule on one part; ``aide`` is true for an order the aide filed. Any failure is a
    recorded, empty, failed estimate. A statement or a measure, with ``groups`` on, is
    ruled on for the groups at home only (``read_groups``)."""
    order = state.routed[order_id]
    if order.parts[part].effect is not None:
        reading = read_groups(state, order, part, transport)
        event = ev.EffectsEstimated(
            order_id=order_id,
            part=part,
            effects=reading.effects,
            reason=reading.reason or GROUPS_UNHEARD,
        )
        return Estimate(event=event, cost=reading.cost, dropped=reading.dropped)
    failed = ev.EffectsEstimated(order_id=order_id, part=part, failed=True, reason=FAILED_REASON)
    request = Request(
        call_class=CALL_CLASS,
        model=ESTIMATOR_MODEL,
        system=prompt_text(PROMPT),
        prompt=estimator_prompt(state, order_id, part),
        schema=cli_schema(ESTIMATOR_SCHEMA),
    )
    try:
        reply = transport.call(request)
    except TransportError as exc:
        return Estimate(event=failed, dropped=(f"transport: {exc}"[:300],))
    cost = reply.cost(CALL_CLASS)
    try:
        ruling = _Ruling.model_validate(reply.output)
    except ValidationError as exc:
        return Estimate(event=failed, cost=cost, dropped=(f"invalid reply: {exc.error_count()}",))
    effects, dropped = clamp(
        state, order, ruling.effects, state.in_world_date or order.filed, aide=aide
    )
    reason = ruling.reason.strip()
    if not reason or scan_text(state, order.issuer, reason):
        reason = REASON_WITHHELD
    event = ev.EffectsEstimated(
        order_id=order_id,
        part=part,
        effects=effects,
        reason=reason[:REASON_CHARS],
        rationale=ruling.rationale[:RATIONALE_CHARS],
    )
    return Estimate(event=event, cost=cost, dropped=dropped)
