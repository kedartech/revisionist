"""Every placed location in Autumn 1941 sits in a theatre, and each theatre groups places."""

from collections import Counter

from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.ontology import EntityKind
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
AUTUMN = cmp.load_world(cmp.world_path("autumn-1941"))
MAX_THEATRES = 12
"""The eight theatres of the five war regions and the four the whole globe adds [proposed] (WGD)."""
PLACED = [d for d in AUTUMN.entities if d.kind is EntityKind.LOCATION and d.at is not None]


def test_every_placed_location_has_a_theatre() -> None:
    assert [d.key for d in PLACED if not d.theatre] == []


def test_every_placed_location_lies_within_an_area() -> None:
    areas = {t.key for t in AUTUMN.territories} | {z.key for z in AUTUMN.sea_zones}
    assert PLACED
    assert [d.key for d in PLACED if d.within not in areas] == []


def test_between_five_and_twelve_theatres_and_none_with_fewer_than_two_places() -> None:
    counts = Counter(d.theatre for d in PLACED)
    assert 5 <= len(counts) <= MAX_THEATRES
    assert {t: n for t, n in counts.items() if n < 2} == {}


def test_only_places_carry_a_theatre() -> None:
    assert [d.key for d in AUTUMN.entities if d.theatre and d not in PLACED] == []


def test_the_world_compiles_and_each_place_keeps_its_theatre() -> None:
    state = replay(compile_world(AUTUMN, CAMPAIGN, cmp.versions()))
    ids = resolve_keys(AUTUMN, CAMPAIGN)
    for d in PLACED:
        assert state.entities[EntityId(ids[d.key])].theatre == d.theatre
