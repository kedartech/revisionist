"""Autumn 1941's forces (reach R5): each major power fields three to six, each opens the game
in reach of a base of its side and kind, and the sides whose Atlantic figures read where their
fleets are keep exactly the fleets those figures were set against."""

import json
from collections import Counter
from pathlib import Path

from revisionist.core.realism import kinds
from revisionist.core.realism.bases import Tier, area_reach
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.kinds import Domain
from revisionist.core.realism.resolvers.shipping import NORTH_ATLANTIC
from tests.test_realism_resolvers import Rig, rig

MAJOR = ("usa", "uk", "ussr", "germany", "japan")
MAP = Path(__file__).resolve().parents[1] / "worlds" / "maps" / "autumn-1941.json"


def forces(r: Rig) -> list[Feature]:
    return sorted(
        (f for f in r.state.features.values() if kinds.is_force(r.state, f)),
        key=lambda f: f.feature_id,
    )


def key_of(r: Rig, id_: str | None) -> str | None:
    return next((k for k, v in r.ids.items() if v == id_), None)


def test_each_major_power_fields_three_to_six_forces() -> None:
    r = rig()
    count = Counter(key_of(r, f.side) for f in forces(r))
    assert {side: count[side] for side in MAJOR if not 3 <= count[side] <= 6} == {}


def test_every_force_opens_the_game_in_reach_of_a_base_of_its_side_and_kind() -> None:
    """At a base, but for two: the Soviet Western Front (Vyazma lies in the Smolensk territory,
    which Germany holds, so its base serves no Soviet piece and the front works from Moscow)
    and the U-boat arm, on station in the mid-ocean gap and working from Lorient."""
    r = rig()
    tiers = {}
    for f in forces(r):
        got = area_reach(r.state, f, f.places[0])
        tiers[key_of(r, f.feature_id)] = None if got is None else got.tier
    assert [k for k, t in tiers.items() if t not in (Tier.SUSTAINED, Tier.OPERATE)] == []
    assert [k for k, t in tiers.items() if t is Tier.OPERATE] == [
        "uboat_arm",
        "soviet_western_front",
    ]


def _north_atlantic_zones() -> set[str]:
    """The sea zones whose label point lies in the shipping rule's North Atlantic."""
    (south, north), (west, east) = NORTH_ATLANTIC
    areas = json.loads(MAP.read_text())["areas"]
    return {
        k
        for k, a in areas.items()
        if south <= a["label"][1] <= north and west <= a["label"][0] <= east
    }


def test_the_sides_with_atlantic_figures_keep_only_their_own_atlantic_fleets() -> None:
    """U-boat losses run while a German fleet lies in the North Atlantic, and a US escort
    cuts them while a US fleet does; a second fleet there would keep either going after a
    player had sent the first away."""
    r = rig()
    zones = _north_atlantic_zones()
    atlantic = sorted(
        (key_of(r, f.side), key_of(r, f.feature_id))
        for f in forces(r)
        if kinds.domain(r.state, f) is Domain.SEA
        and key_of(r, f.side) in ("usa", "germany")
        and key_of(r, f.places[0]) in zones
    )
    assert atlantic == [("germany", "uboat_arm"), ("usa", "us_atlantic_fleet")]
