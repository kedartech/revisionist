"""Detachments (reach R4): part of a force sent off as a force of its own, and its return.

A split takes some of a force's strength (its ``tier``) to another place as a
detachment; the rest stays where it is. The detachment is a feature of its own, with
``detached_from`` naming the force it came from, and it moves, raids and keeps its raid
clock as any force does. A side may have only so many detachments of a kind in play
at once, and a force keeps at least strength 1. A detachment is not split again.

A detachment that stands where its parent stands, with neither under way, merges back
on that day: its strength returns to the parent (to at most 5) and it leaves play
(``rejoined_on``). Its slot is free again, and the next split of that parent takes the
lowest free slot.
"""

from collections.abc import Mapping
from datetime import date

from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism.answer import ParamValue
from revisionist.core.realism.geography import Feature, FeatureKind, in_play
from revisionist.core.state import State
from revisionist.core.world_compile import object_id

DETACHMENTS_PER_SIDE = {FeatureKind.FLEET: 2, FeatureKind.ARMY: 0, FeatureKind.AIR: 1}
"""[proposed] The most detachments of each kind of force a side may have in play at once.
An army detachment would make every front place it stood on a base for its side."""
MAX_TIER = 5
NAME = 60
"""The longest name a feature may carry."""


def live(features: Mapping[FeatureId, Feature], kind: FeatureKind, side: EntityId) -> int:
    """How many detachments of ``kind`` ``side`` has in play."""
    return sum(
        f.kind is kind and f.side == side and f.detached_from is not None and in_play(f)
        for f in features.values()
    )


def slot(state: State, key: str) -> tuple[FeatureId, int]:
    """The id and number of the lowest slot free for a detachment of the force ``key``."""
    n = 1
    while True:
        fid = FeatureId(object_id(state.campaign_id, "feature", f"{key}__d{n}"))
        held = state.features.get(fid)
        if held is None or not in_play(held):
            return fid, n
        n += 1


def _strength(value: ParamValue | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def split(
    state: State, parent: Feature, key: str, strength: ParamValue | None, sent: Feature
) -> tuple[Feature, ...]:
    """The parent left behind and the detachment under way, or nothing when the split is
    refused. ``sent`` is the parent as a move to the detachment's destination would leave
    it; the detachment takes its course, its clock and the day it sets out."""
    n = _strength(strength)
    if sent.bound_for is None or parent.detached_from is not None or parent.side is None:
        return ()
    if n is None or not 1 <= n < parent.tier:
        return ()
    if live(state.features, parent.kind, parent.side) >= DETACHMENTS_PER_SIDE.get(parent.kind, 0):
        return ()
    fid, number = slot(state, key)
    suffix = f" detachment {number}"
    part = sent.model_copy(
        update={
            "feature_id": fid,
            "name": parent.name[: NAME - len(suffix)] + suffix,
            "tier": n,
            "detached_from": parent.feature_id,
            "rejoined_on": None,
        }
    )
    return parent.model_copy(update={"tier": parent.tier - n, "as_of": sent.as_of}), part


def rejoin(features: Mapping[FeatureId, Feature], today: date) -> dict[FeatureId, Feature]:
    """Each detachment in play that stands still today where its parent stands still,
    merged back, with the parent it returned its strength to."""
    out: dict[FeatureId, Feature] = {}
    for part in sorted(features.values(), key=lambda f: f.feature_id):
        if part.detached_from is None or not in_play(part) or part.bound_for is not None:
            continue
        parent = out.get(part.detached_from) or features.get(part.detached_from)
        if parent is None or parent.bound_for is not None or parent.places != part.places:
            continue
        out[parent.feature_id] = parent.model_copy(
            update={
                "tier": min(MAX_TIER, parent.tier + part.tier),
                "as_of": max(today, parent.as_of),
            }
        )
        out[part.feature_id] = part.model_copy(
            update={"rejoined_on": today, "as_of": max(today, part.as_of)}
        )
    return out


__all__ = ["DETACHMENTS_PER_SIDE", "live", "rejoin", "slot", "split"]
