"""A card can carry how its holder is addressed ("Mr. President"), written by hand in the
world file, for the prose writer to use in a salutation. A game begun before the field
was written takes it at its next wake; a card without it dumps and hashes as before."""

import hashlib
import json
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay, state_hash
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.realism.card import SeatCard
from revisionist.core.realism.effect import Fidelity
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import card_policy, compile_world, resolve_keys
from revisionist.engine import build, realism_tick
from revisionist.engine import campaign as cmp
from revisionist.engine.emit import Emitter
from revisionist.engine.prose_context import page_context
from revisionist.engine.realism_tick import run_realism_tick
from revisionist.engine.store import EventStore, MemoryStore, load_state
from tests.test_engine_v2_contract import Slice
from tests.test_prose_context import _page, _reported

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
WORLD = cmp.load_world(cmp.world_path("autumn-1941"))
DECL = WORLD.model_copy(
    update={"cards": tuple(c.model_copy(update={"addressed_as": None}) for c in WORLD.cards)}
)
KEYS = {k: EntityId(v) for k, v in resolve_keys(DECL, CAMPAIGN).items()}
FORMS = {"roosevelt": "Mr. President", "churchill": "Prime Minister", "hitler": "Mein Führer"}
ADDRESSED = DECL.model_copy(
    update={
        "cards": tuple(
            c.model_copy(update={"addressed_as": FORMS.get(c.person, "Sir")}) for c in DECL.cards
        )
    }
)


def _fresh(decl: WorldFile = DECL) -> State:
    return replay(compile_world(decl, CAMPAIGN, cmp.versions()))


def _game(decl: WorldFile) -> MemoryStore:
    store = MemoryStore()
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    realism_tick.seat_player(store, CAMPAIGN, KEYS["churchill"])
    return store


def _amended(store: EventStore) -> list[ev.CardAmended]:
    return [e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.CardAmended)]


def _fold(state: State, amendment: ev.CardAmended) -> State:
    stored = Emitter(MemoryStore(), state, cmp.versions()).event(amendment)
    return replay([ev.Event.model_validate_json(stored.model_dump_json())], initial=state)


def _amendment(state: State, person: EntityId, **form: Any) -> ev.CardAmended:
    card = state.cards[person]
    return ev.CardAmended(
        person=person, allies=card.allies, opposes=card.opposes, answers=card.answers, **form
    )


def test_an_amendment_with_a_form_of_address_sets_it_through_the_stored_log() -> None:
    state = _fresh()
    fdr = KEYS["roosevelt"]
    after = _fold(state, _amendment(state, fdr, addressed_as="Mr. President"))
    assert after.cards[fdr].addressed_as == "Mr. President"
    assert after.cards[fdr].answers == state.cards[fdr].answers
    again = State.model_validate_json(after.model_dump_json())
    assert again.cards[fdr].addressed_as == "Mr. President"
    assert state_hash(again) == state_hash(after)


def test_an_amendment_without_one_keeps_the_cards_form_of_address() -> None:
    state = _fresh()
    fdr = KEYS["roosevelt"]
    addressed = _fold(state, _amendment(state, fdr, addressed_as="Mr. President"))
    old = _amendment(addressed, fdr)
    assert "addressed_as" not in old.model_dump()
    after = _fold(addressed, old)
    assert after.cards[fdr].addressed_as == "Mr. President"


def test_a_card_without_a_form_of_address_dumps_and_hashes_as_before() -> None:
    assert "addressed_as" in SeatCard.model_fields
    state = _fresh()
    assert all(card.addressed_as is None for card in state.cards.values())
    dumped = state.model_dump(mode="json")
    assert not any("addressed_as" in card for card in dumped["cards"].values())
    canon = json.dumps(dumped, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert state_hash(state) == hashlib.blake2b(canon.encode(), digest_size=16).hexdigest()
    assert state_hash(_fresh(ADDRESSED)) != state_hash(state)


def test_the_world_file_takes_it_and_a_built_card_is_never_asked_for_it() -> None:
    declared = WorldFile.model_json_schema()["$defs"]["CardDecl"]["properties"]
    assert "addressed_as" in declared
    assert "addressed_as" not in build.BUILD_SCHEMA["$defs"]["CardDecl"]["properties"]
    assert "addressed_as" not in json.dumps(build.BUILD_SCHEMA)


def test_card_policy_carries_the_world_files_form_of_address() -> None:
    policy = {a.person: a.addressed_as for a in card_policy(ADDRESSED, CAMPAIGN)}
    assert policy[KEYS["roosevelt"]] == "Mr. President"
    assert {a.addressed_as for a in card_policy(DECL, CAMPAIGN)} == {None}


def test_a_game_begun_before_the_forms_of_address_takes_them_at_its_next_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _game(DECL)
    monkeypatch.setattr(cmp, "load_world", lambda _path: ADDRESSED)
    run_realism_tick(store, CAMPAIGN)
    assert len(_amended(store)) == len(DECL.cards)
    state, full = load_state(store, CAMPAIGN), _fresh(ADDRESSED)
    assert {p: c.addressed_as for p, c in state.cards.items()} == {
        p: c.addressed_as for p, c in full.cards.items()
    }
    assert state.cards[KEYS["roosevelt"]].addressed_as == "Mr. President"
    run_realism_tick(store, CAMPAIGN)
    assert len(_amended(store)) == len(DECL.cards)


def test_a_game_with_its_forms_of_address_is_not_amended_for_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _game(ADDRESSED)
    monkeypatch.setattr(cmp, "load_world", lambda _path: ADDRESSED)
    run_realism_tick(store, CAMPAIGN)
    assert _amended(store) == []


def _with_form(state: State, person: EntityId, form: str | None) -> State:
    card = state.cards[person].model_copy(update={"addressed_as": form})
    return state.model_copy(update={"cards": {**state.cards, person: card}})


def test_a_page_tells_the_writer_how_its_reader_is_addressed() -> None:
    sl = Slice()
    state, _ = _reported(sl, fidelity=Fidelity.FULL)
    page = _page(state, "Shoot on sight")
    assert page.author != sl.entity("roosevelt")
    state = _with_form(state, page.author, "Admiral")
    assert page_context(state, page).get("to_addressed_as") is None
    assert "to_addressed_as" not in page_context(state, page)
    addressed = _with_form(state, sl.entity("roosevelt"), "Mr. President")
    assert page_context(addressed, page)["to_addressed_as"] == "Mr. President"
