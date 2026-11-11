"""A card's aims: what the person was set on at the start, shown on their own desk only."""

from typing import Any

from revisionist.core.fold import replay
from revisionist.core.project import project
from revisionist.core.realism.card import CardFace
from revisionist.core.world_compile import compile_world
from revisionist.engine import build
from revisionist.engine import campaign as cmp
from revisionist.engine.store import load_state
from tests.test_build_authority import DOMAIN, kennedy_with, opened_kennedy
from tests.test_engine_v2_contract import CAMPAIGN, Slice
from tests.test_realism_cast import Fixed

AIMS = ["Hold the line.", "Keep the allies close."]
WORLDS = ("autumn-1941", "engine-v2-slice-1941")


def test_a_declared_aim_reaches_the_compiled_card() -> None:
    decl = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
    first = decl.cards[0].model_copy(update={"aims": tuple(AIMS)})
    decl = decl.model_copy(update={"cards": (first, *decl.cards[1:])})
    cards = replay(compile_world(decl, CAMPAIGN, cmp.versions())).cards
    assert any(c.aims == tuple(AIMS) for c in cards.values())


def test_the_aims_of_a_build_reply_reach_the_built_card() -> None:
    store, cid, kennedy = opened_kennedy()
    reply = kennedy_with(authority=[DOMAIN], reach={"rank": 5}, aims=AIMS)
    assert build.build_figure(store, cid, kennedy, Fixed(reply))
    assert load_state(store, cid).cards[kennedy].aims == tuple(AIMS)


def test_every_playable_card_of_the_two_1941_worlds_has_two_or_three_aims() -> None:
    for name in WORLDS:
        decl = cmp.load_world(cmp.world_path(name))
        playable = [c for c in decl.cards if c.playable]
        assert playable, name
        for c in playable:
            assert 2 <= len(c.aims) <= 3, f"{name}: {c.person}"


def test_a_seat_views_other_cards_without_aims() -> None:
    sl = Slice()
    mine = sl.state.cards[sl.entity("roosevelt")]
    cards = {
        k: c.model_copy(update={"aims": ("A secret aim.",)}) if k == mine.person else c
        for k, c in sl.state.cards.items()
    }
    state = sl.state.model_copy(update={"cards": cards})
    assert "aims" not in CardFace.model_fields
    theirs = project(state, sl.wheeler)
    assert theirs.desk is not None and "A secret aim." not in theirs.desk.aims
    seen: dict[str, Any] = theirs.model_dump(mode="json")
    assert "A secret aim." not in str(seen)
    assert project(state, sl.fdr).desk.aims == ("A secret aim.",)  # type: ignore[union-attr]
