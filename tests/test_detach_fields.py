"""Detachment fields on a force (reach R4, unit D1): stored, folded, and left out while empty."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.fold import replay, state_hash
from revisionist.core.ids import FeatureId
from revisionist.core.realism import geography as rg
from revisionist.core.realism.geography import FORCES, Feature, FeatureKind
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from tests.test_realism_resolvers import CAMPAIGN, START, Rig

LATE = ("detached_from", "rejoined_on")


def feature(r: Rig, key: str) -> Feature:
    return r.state.features[FeatureId(r.ids[key])]


def detachment(r: Rig, parent_key: str, n: int = 1) -> Feature:
    parent = feature(r, parent_key)
    return parent.model_copy(
        update={
            "feature_id": FeatureId(object_id(CAMPAIGN, "feature", f"{parent_key}__d{n}")),
            "name": f"{parent.name} detachment {n}",
            "tier": 1,
            "as_of": START + timedelta(days=3),
            "legs": (),
            "detached_from": parent.feature_id,
        }
    )


def test_a_detachment_round_trips_through_feature_set_and_the_fold() -> None:
    r = Rig()
    det = detachment(r, "home_fleet")
    sent = ev.FeatureSet(feature=det)
    assert ev.FeatureSet.model_validate_json(sent.model_dump_json()) == sent
    assert (
        sent.model_dump(mode="json")["feature"]["detached_from"]
        == feature(r, "home_fleet").feature_id
    )
    r.add(sent)
    assert r.state.features[det.feature_id] == det

    back = det.model_copy(
        update={"as_of": START + timedelta(days=9), "rejoined_on": START + timedelta(days=9)}
    )
    rejoined = ev.FeatureSet(feature=back)
    assert ev.FeatureSet.model_validate_json(rejoined.model_dump_json()) == rejoined
    assert rejoined.model_dump(mode="json")["feature"]["rejoined_on"] == "1941-09-10"
    r.add(rejoined)
    folded = r.state.features[det.feature_id]
    assert folded.detached_from == feature(r, "home_fleet").feature_id
    assert folded.rejoined_on == START + timedelta(days=9)


def test_an_old_game_folds_and_hashes_as_before() -> None:
    """No stored feature carries the fields, so every logged FeatureSet reads back to the
    same bytes and the folded state's dump holds no new key."""
    world = cmp.load_world(cmp.world_path("autumn-1941"))
    events = compile_world(world, CAMPAIGN, cmp.versions())
    sets = [e for e in events if isinstance(e.payload, ev.FeatureSet)]
    assert sets
    for e in sets:
        text = e.model_dump_json()
        assert not any(f'"{k}"' in text for k in LATE)
        assert ev.Event.model_validate_json(text).model_dump_json() == text
    state = replay(events)
    for f in state.features.values():
        assert f.detached_from is None and f.rejoined_on is None
        assert not set(LATE) & set(f.model_dump(mode="json"))
    assert state_hash(replay(events)) == state_hash(state)


def test_an_empty_field_is_left_out_of_the_dump() -> None:
    r = Rig()
    plain = feature(r, "home_fleet").model_copy(update={"detached_from": None, "rejoined_on": None})
    assert not set(LATE) & set(plain.model_dump(mode="json"))
    assert plain.model_dump(mode="json") == feature(r, "home_fleet").model_dump(mode="json")


@pytest.mark.parametrize("key", ["hx_route", "eastern_front"])
def test_a_front_or_route_with_detached_from_is_refused(key: str) -> None:
    r = Rig()
    line = feature(r, key)
    assert line.kind in (FeatureKind.FRONT, FeatureKind.ROUTE)
    data = {**line.model_dump(mode="json"), "detached_from": feature(r, "home_fleet").feature_id}
    with pytest.raises(ValidationError, match="only a force"):
        Feature.model_validate(data)
    payload = {"kind": "feature_set", "feature": data}
    with pytest.raises(ValidationError, match="only a force"):
        ev.FeatureSet.model_validate(payload)


def test_every_force_kind_may_be_detached() -> None:
    r = Rig()
    det = detachment(r, "home_fleet")
    for kind in FORCES:
        data = {**det.model_dump(mode="json"), "kind": kind.value}
        assert Feature.model_validate(data).detached_from == det.detached_from


def test_a_rejoined_detachment_is_out_of_play() -> None:
    r = Rig()
    det = detachment(r, "home_fleet")
    assert rg.in_play(feature(r, "home_fleet"))
    assert rg.in_play(det)
    assert not rg.in_play(det.model_copy(update={"rejoined_on": START + timedelta(days=9)}))
