"""A card whose world file leaves a late field unset keeps its own value, and the wake
does not amend it for that field again and again."""

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.realism_tick import run_realism_tick
from revisionist.engine.store import EventStore, MemoryStore, load_state

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
WORLD = cmp.load_world(cmp.world_path("autumn-1941"))
KEYS = {k: EntityId(v) for k, v in resolve_keys(WORLD, CAMPAIGN).items()}


def _cards(world: WorldFile, **fields: object) -> WorldFile:
    return world.model_copy(
        update={"cards": tuple(c.model_copy(update=fields) for c in world.cards)}
    )


UNADDRESSED = _cards(WORLD, addressed_as=None)
ADDRESSED = _cards(WORLD, addressed_as="Sir")


def _game(decl: WorldFile) -> MemoryStore:
    store = MemoryStore()
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    realism_tick.seat_player(store, CAMPAIGN, KEYS["churchill"])
    return store


def _amended(store: EventStore) -> list[ev.CardAmended]:
    return [e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.CardAmended)]


def test_a_form_of_address_the_world_file_leaves_unset_is_not_amended_at_each_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _game(ADDRESSED)
    monkeypatch.setattr(cmp, "load_world", lambda _path: UNADDRESSED)
    run_realism_tick(store, CAMPAIGN)
    run_realism_tick(store, CAMPAIGN)
    assert _amended(store) == []
    state = load_state(store, CAMPAIGN)
    assert {c.addressed_as for c in state.cards.values()} == {"Sir"}


def test_a_form_of_address_the_world_file_changes_is_amended_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _game(ADDRESSED)
    monkeypatch.setattr(cmp, "load_world", lambda _path: _cards(WORLD, addressed_as="Madam"))
    run_realism_tick(store, CAMPAIGN)
    run_realism_tick(store, CAMPAIGN)
    assert len(_amended(store)) == len(WORLD.cards)
    state = load_state(store, CAMPAIGN)
    assert {c.addressed_as for c in state.cards.values()} == {"Madam"}


def test_a_voice_the_world_file_empties_is_taken_once(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _game(WORLD)
    assert all(c.voice for c in load_state(store, CAMPAIGN).cards.values())
    monkeypatch.setattr(cmp, "load_world", lambda _path: _cards(WORLD, voice=""))
    run_realism_tick(store, CAMPAIGN)
    run_realism_tick(store, CAMPAIGN)
    assert len(_amended(store)) == len(WORLD.cards)
    assert not any(c.voice for c in load_state(store, CAMPAIGN).cards.values())
