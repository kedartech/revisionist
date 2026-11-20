"""Autumn 1941's forces (reach R5): each major power fields three to five, each stands at a
base of its side and kind when the game opens, and the sides whose Atlantic figures read
where their fleets are keep exactly the fleets those figures were set against."""

from collections import Counter

from revisionist.core.realism.bases import Tier, reach
from revisionist.core.realism.geography import FORCES, Feature, FeatureKind
from revisionist.core.realism.resolvers.shipping import _in_north_atlantic
from tests.test_realism_resolvers import Rig, rig

MAJOR = ("usa", "uk", "ussr", "germany", "japan")


def forces(r: Rig) -> list[Feature]:
    return sorted(
        (f for f in r.state.features.values() if f.kind in FORCES), key=lambda f: f.feature_id
    )


def key_of(r: Rig, id_: str | None) -> str | None:
    return next((k for k, v in r.ids.items() if v == id_), None)


def test_each_major_power_fields_three_to_five_forces() -> None:
    r = rig()
    count = Counter(key_of(r, f.side) for f in forces(r))
    assert {side: count[side] for side in MAJOR if not 3 <= count[side] <= 5} == {}


def test_every_force_opens_the_game_at_a_base_of_its_side_and_kind() -> None:
    r = rig()
    away = []
    for f in forces(r):
        got = reach(r.state, f, f.places[0])
        if got is None or got.tier is not Tier.SUSTAINED:
            away.append((key_of(r, f.feature_id), key_of(r, f.places[0])))
    assert away == []


def test_the_sides_with_atlantic_figures_keep_only_their_own_atlantic_fleets() -> None:
    """U-boat losses run while a German fleet lies in the North Atlantic, and a US escort
    cuts them while a US fleet does; a second fleet there would keep either going after a
    player had sent the first away."""
    r = rig()
    atlantic = sorted(
        (key_of(r, f.side), key_of(r, f.feature_id))
        for f in forces(r)
        if f.kind is FeatureKind.FLEET
        and key_of(r, f.side) in ("usa", "germany")
        and _in_north_atlantic(r.state, f.places[0])
    )
    assert atlantic == [("germany", "uboat_arm"), ("usa", "us_atlantic_fleet")]
