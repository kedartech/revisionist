"""Every Autumn 1941 card says how its holder is addressed, and a game begun before the
forms were written takes them at its next wake, once."""

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.realism_tick import run_realism_tick
from revisionist.engine.store import EventStore, MemoryStore, load_state

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
DECL = cmp.load_world(cmp.world_path("autumn-1941"))
KEYS = {k: EntityId(v) for k, v in resolve_keys(DECL, CAMPAIGN).items()}
BARE = DECL.model_copy(
    update={"cards": tuple(c.model_copy(update={"addressed_as": None}) for c in DECL.cards)}
)


def _fresh(decl: WorldFile = DECL) -> State:
    return replay(compile_world(decl, CAMPAIGN, cmp.versions()))


def _amended(store: EventStore) -> list[ev.CardAmended]:
    return [e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.CardAmended)]


def test_every_autumn_1941_card_says_how_its_holder_is_addressed() -> None:
    unaddressed = [c.person for c in DECL.cards if not (c.addressed_as or "").strip()]
    assert unaddressed == []
    assert len(DECL.cards) == 52
    state = _fresh()
    assert {state.cards[KEYS[c.person]].addressed_as for c in DECL.cards} == {
        c.addressed_as for c in DECL.cards
    }
    assert all(card.addressed_as for card in state.cards.values())


def test_the_heads_take_the_forms_the_plan_names() -> None:
    forms = {c.person: c.addressed_as for c in DECL.cards}
    assert forms["roosevelt"] == "Mr. President"
    assert forms["churchill"] == "Prime Minister"
    assert forms["hitler"] == "Mein Führer"


def test_a_game_begun_before_the_forms_is_amended_once_at_its_next_wake() -> None:
    store = MemoryStore()
    store.append_all(compile_world(BARE, CAMPAIGN, cmp.versions()))
    realism_tick.seat_player(store, CAMPAIGN, KEYS["churchill"])
    assert not any(c.addressed_as for c in load_state(store, CAMPAIGN).cards.values())
    run_realism_tick(store, CAMPAIGN)
    assert len(_amended(store)) == len(DECL.cards)
    state, fresh = load_state(store, CAMPAIGN), _fresh()
    assert {p: c.addressed_as for p, c in state.cards.items()} == {
        p: c.addressed_as for p, c in fresh.cards.items()
    }
    run_realism_tick(store, CAMPAIGN)
    assert len(_amended(store)) == len(DECL.cards)
