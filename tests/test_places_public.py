"""A place with a position is in every seat's view: the world file creates it in public,
no event moves or hides a place, and a seat's view holds every entity the game has. A
posted destination is checked against the game's places, and this is why that is the
same as checking it against the issuer's view."""

from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.project import project
from revisionist.core.realism.pipelines import place_named
from revisionist.core.visibility import PUBLIC
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.store import MemoryStore, load_state

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
WORLDS = sorted(Path(cmp.world_path("autumn-1941")).parent.glob("*.yaml"))


@pytest.mark.parametrize("path", WORLDS, ids=lambda p: p.stem)
def test_every_located_place_is_created_in_public(path: Path) -> None:
    events = compile_world(cmp.load_world(path), CAMPAIGN, cmp.versions())
    located = [
        e
        for e in events
        if isinstance(e.payload, ev.EntityCreated) and e.payload.entity.at is not None
    ]
    assert all(e.scope == PUBLIC for e in located)


@pytest.mark.parametrize("path", WORLDS, ids=lambda p: p.stem)
def test_every_seat_sees_every_located_place(path: Path) -> None:
    world = cmp.load_world(path)
    if world.ruleset != "realism":
        pytest.skip("places have positions only in realism worlds")
    keys = resolve_keys(world, CAMPAIGN)
    located = [e.key for e in world.entities if e.at is not None]
    store = MemoryStore()
    store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
    first = next(c for c in world.cards if c.playable)
    realism_tick.seat_player(store, CAMPAIGN, EntityId(keys[first.person]))
    state = load_state(store, CAMPAIGN)
    assert state.seats
    for seat in state.seats:
        view = project(state, seat)
        assert [k for k in located if place_named(view, k) is None] == []
        assert all(place_named(view, k) == place_named(state, k) for k in located)


def test_the_shipped_world_has_located_places() -> None:
    world = cmp.load_world(cmp.world_path("autumn-1941"))
    assert sum(e.at is not None for e in world.entities) >= 10
