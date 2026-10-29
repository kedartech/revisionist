"""The estimator (engine v2, spec §8.3): the free-play rule.

For a routed part no code rule covers (``RoutedPart.effect`` is None), one
engine-side call returns typed effects from the closed vocabulary
(``core.realism.effect``) and a reason written from the issuer's view. Code clamps
the effects to the bounds and lands them as ``EffectsEstimated``; a replay reads
that event and never calls the model again.

Contract names only (engine-v2 addendum). Wave A4 builds the prompt, transport,
clamp, failure path and recording under these names.
"""

import json
from collections.abc import Sequence
from datetime import date
from typing import Any

from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core._base import Model
from revisionist.core.canary import scan_text
from revisionist.core.events import CallCost
from revisionist.core.fold import FoldError, _check_effect
from revisionist.core.ids import EntityId, OrderId
from revisionist.core.realism.effect import (
    DISPOSITION_CAP,
    Effect,
    EffectKind,
    RoutedOrder,
    RoutedPart,
    ShiftDisposition,
)
from revisionist.core.state import State
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

    effects: tuple[Effect, ...]
    reason: str
    rationale: str


ESTIMATOR_SCHEMA: dict[str, Any] = _Ruling.model_json_schema()
"""Closed vocabulary only: a quantity has no kind here, so a reply that sets one fails."""

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
    cards = {
        str(who): state.cards[who].model_dump(mode="json", exclude={"voice"}, exclude_none=True)
        for who in dict.fromkeys([issuer.embodies, *_named(routed)])
        if who in state.cards
    }
    world = {
        "date": str(state.in_world_date or order.filed),
        "order": {
            "id": order_id,
            "issuer": issuer.name,
            "issuer_entity": issuer.embodies,
            "filed": str(order.filed),
            "part": routed.view().model_dump(mode="json", exclude_none=True),
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
        "rules": {
            "effect_kinds": sorted(k.value for k in EffectKind),
            "disposition_cap": DISPOSITION_CAP,
            "max_effects": MAX_EFFECTS,
        },
    }
    return (
        "## World (truth) and the part to rule on\n"
        + json.dumps(world, separators=(",", ":"), default=str)
        + "\n\nReturn effects, a reason for the issuer and your rationale. Echo ids exactly."
    )


def clamp(
    state: State, order: RoutedOrder, effects: Sequence[Effect], on: date
) -> tuple[tuple[Effect, ...], tuple[str, ...]]:
    """Code bounds on whatever the model proposed. Returns the survivors and a line per cut."""
    kept: list[Effect] = []
    dropped: list[str] = []
    moved: dict[tuple[EntityId, EntityId], int] = {}
    for effect in effects:
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
        kept.append(effect)
    for effect in kept[MAX_EFFECTS:]:
        dropped.append(f"{effect.kind}: over the {MAX_EFFECTS}-effect cap")
    return tuple(kept[:MAX_EFFECTS]), tuple(dropped)


def estimate(state: State, order_id: OrderId, part: int, transport: Transport) -> Estimate:
    """Rule on one part. Any failure is a recorded, empty, failed estimate."""
    order = state.routed[order_id]
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
    effects, dropped = clamp(state, order, ruling.effects, state.in_world_date or order.filed)
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
