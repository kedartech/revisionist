"""Every Autumn 1941 card carries a voice for the letter writer, and a game begun
before a voice was written takes it at its next wake."""

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.state import State
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.emit import Emitter
from revisionist.engine.realism_tick import run_realism_tick
from revisionist.engine.store import EventStore, MemoryStore, load_state

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
DECL = cmp.load_world(cmp.world_path("autumn-1941"))
KEYS = {k: EntityId(v) for k, v in resolve_keys(DECL, CAMPAIGN).items()}


def _fresh() -> State:
    return replay(compile_world(DECL, CAMPAIGN, cmp.versions()))


def _game(decl: object) -> MemoryStore:
    store = MemoryStore()
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))  # type: ignore[arg-type]
    realism_tick.seat_player(store, CAMPAIGN, KEYS["churchill"])
    return store


def _amended(store: EventStore) -> list[ev.CardAmended]:
    return [e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.CardAmended)]


def test_every_autumn_1941_card_has_a_voice() -> None:
    silent = [c.person for c in DECL.cards if not c.voice.strip()]
    assert silent == []
    assert all(card.voice for card in _fresh().cards.values())


def test_a_game_begun_before_the_voices_takes_them_at_its_next_wake() -> None:
    bare = DECL.model_copy(
        update={"cards": tuple(c.model_copy(update={"voice": ""}) for c in DECL.cards)}
    )
    store = _game(bare)
    assert not any(c.voice for c in load_state(store, CAMPAIGN).cards.values())
    run_realism_tick(store, CAMPAIGN)
    assert len(_amended(store)) == len(DECL.cards)
    state, fresh = load_state(store, CAMPAIGN), _fresh()
    hull = KEYS["hull"]
    assert state.cards[hull].voice == fresh.cards[hull].voice
    assert {p: c.voice for p, c in state.cards.items()} == {
        p: c.voice for p, c in fresh.cards.items()
    }
    assert state.cards[KEYS["hitler"]].answers == fresh.cards[KEYS["hitler"]].answers
    run_realism_tick(store, CAMPAIGN)
    assert len(_amended(store)) == len(DECL.cards)


def test_a_game_with_its_voices_is_not_amended_for_them() -> None:
    store = _game(DECL)
    run_realism_tick(store, CAMPAIGN)
    assert _amended(store) == []


def test_an_amendment_with_no_voice_leaves_the_card_voice_alone() -> None:
    state = _fresh()
    hull = KEYS["hull"]
    card = state.cards[hull]
    old = ev.CardAmended(person=hull, allies=card.allies, opposes=card.opposes, answers=())
    assert "voice" not in old.model_dump()
    em = Emitter(MemoryStore(), state, cmp.versions())
    after = replay([em.event(old)], initial=state)
    assert after.cards[hull].voice == card.voice != ""


def test_an_amendment_with_a_voice_sets_it() -> None:
    state = _fresh()
    hull = KEYS["hull"]
    card = state.cards[hull]
    new = ev.CardAmended(
        person=hull, allies=card.allies, opposes=card.opposes, answers=card.answers, voice="Terse."
    )
    em = Emitter(MemoryStore(), state, cmp.versions())
    after = replay([em.event(new)], initial=state)
    assert after.cards[hull].voice == "Terse."
    assert after.cards[hull].answers == card.answers
