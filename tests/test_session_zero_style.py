"""BGS: a realism claim lands the Beginner play style with the claim.

The style is the seat's own (sealed to it), so the aide, which plays an absent seat
down the same Beginner path, is offered options without the player ever choosing a
style. A legacy game and a stored game are left as they are.
"""

from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, SeatId, derived_id
from revisionist.core.realism.agenda import PlayStyle
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import options
from revisionist.engine import session_zero as sz
from revisionist.engine.store import EventStore, MemoryStore, load_state
from tests.test_session_zero_steps import A, Table, _florence

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
SLICE = "engine-v2-slice-1941"


def _slice(store: EventStore) -> dict[str, str]:
    decl = cmp.load_world(cmp.world_path(SLICE))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    return resolve_keys(decl, CAMPAIGN)


def _seat(ids: dict[str, str], key: str) -> SeatId:
    return SeatId(derived_id(CAMPAIGN, "seat", ids[key]))


def test_a_realism_claim_lands_beginner_with_the_claim() -> None:
    store = MemoryStore()
    ids = _slice(store)
    seat = _seat(ids, "roosevelt")
    sz.claim(store, CAMPAIGN, seat, "Roosevelt")

    state = load_state(store, CAMPAIGN)
    assert state.styles[seat] is PlayStyle.BEGINNER
    assert state.standing[seat] == frozenset()
    log = list(store.read(CAMPAIGN))
    claimed = next(i for i, e in enumerate(log) if isinstance(e.payload, ev.CharacterClaimed))
    style = log[claimed + 1]
    assert isinstance(style.payload, ev.PlayStyleSet)
    assert style.payload.seat_id == seat and style.payload.style is PlayStyle.BEGINNER
    assert style.scope.known_by == frozenset({seat}), "the style is the seat's own"


def test_each_seat_gets_its_own_style_and_the_claim_race_still_refuses_the_second() -> None:
    store = MemoryStore()
    ids = _slice(store)
    fdr, winston = _seat(ids, "roosevelt"), _seat(ids, "churchill")
    sz.claim(store, CAMPAIGN, fdr, "Roosevelt")
    with pytest.raises(sz.StepRefusedError, match="already taken"):
        sz.claim(store, CAMPAIGN, winston, "Roosevelt")
    sz.claim(store, CAMPAIGN, winston, "Churchill")
    state = load_state(store, CAMPAIGN)
    assert state.styles == {fdr: PlayStyle.BEGINNER, winston: PlayStyle.BEGINNER}
    styles = [e for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.PlayStyleSet)]
    assert len(styles) == 2, "a refused claim leaves no style behind"


def test_a_style_chosen_after_the_claim_still_wins() -> None:
    store = MemoryStore()
    ids = _slice(store)
    seat = _seat(ids, "roosevelt")
    sz.claim(store, CAMPAIGN, seat, "Roosevelt")
    options.set_style(store, CAMPAIGN, seat, PlayStyle.FREE)
    assert load_state(store, CAMPAIGN).styles[seat] is PlayStyle.FREE


def test_giving_the_person_up_and_claiming_again_lands_beginner_again() -> None:
    store = MemoryStore()
    ids = _slice(store)
    seat = _seat(ids, "roosevelt")
    sz.claim(store, CAMPAIGN, seat, "Roosevelt")
    options.set_style(store, CAMPAIGN, seat, PlayStyle.FREE)
    sz.release(store, CAMPAIGN, seat)
    assert seat not in load_state(store, CAMPAIGN).styles
    sz.claim(store, CAMPAIGN, seat, "Roosevelt")
    assert load_state(store, CAMPAIGN).styles[seat] is PlayStyle.BEGINNER


def test_a_legacy_claim_lands_no_style() -> None:
    store = MemoryStore()
    table = Table()
    c = _florence(store, table)
    sz.claim(store, c, A, "Lorenzo de' Medici")
    assert load_state(store, c).styles == {}
    assert not [e for e in store.read(c) if isinstance(e.payload, ev.PlayStyleSet)]


def test_a_stored_game_keeps_the_styles_it_has() -> None:
    """Nothing re-derives a style on load: reading a log writes nothing, and the style
    the player chose is the one it replays to."""
    store = MemoryStore()
    ids = _slice(store)
    seat = _seat(ids, "roosevelt")
    sz.claim(store, CAMPAIGN, seat, "Roosevelt")
    options.set_style(store, CAMPAIGN, seat, PlayStyle.GUIDED)
    before = list(store.read(CAMPAIGN))
    assert load_state(store, CAMPAIGN).styles == {seat: PlayStyle.GUIDED}
    assert list(store.read(CAMPAIGN)) == before


def test_the_aide_is_offered_options_for_a_seat_that_never_chose(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Invariant 2's path: the style the aide reads is Beginner, whoever holds the seat."""
    from tests.async_table import AsyncTable

    t = AsyncTable(MemoryStore(), monkeypatch, tmp_path, style=None)
    assert set(t.state.styles.values()) == {PlayStyle.BEGINNER}
    assert set(t.state.styles) == set(t.seats)
