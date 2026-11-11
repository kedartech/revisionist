"""Powers and channel keys on each contact (Train 2 unit S3), from the public card face.

Spec tests written with the contract; the unit makes them pass without editing them.
"""

import json

from revisionist.core.realism.card import ChannelKind, words
from revisionist.engine.web.reach_groups import reach
from revisionist.engine.web.realism_api import ReachContact, ReachGroups
from tests.test_engine_v2_contract import Slice


def _everyone(groups: ReachGroups) -> list[ReachContact]:
    return [*groups["inner_circle"], *groups["government"], *groups["foreign"], *groups["other"]]


def _contact(sl: Slice, name: str) -> ReachContact:
    return next(c for c in _everyone(reach(sl.state, sl.fdr)) if c["name"] == name)


def test_a_contact_with_a_card_face_has_its_powers_in_words() -> None:
    sl = Slice()
    churchill = _contact(sl, "Winston Churchill")
    face = sl.state.cards[sl.entity("churchill")].face()
    assert churchill["powers"] and churchill["powers"] == [str(p) for p in face.powers]


def test_the_channel_keys_match_the_worded_channels_in_order() -> None:
    sl = Slice()
    for c in _everyone(reach(sl.state, sl.fdr)):
        assert [words(ChannelKind(k)) for k in c["channel_keys"]] == c["channels"]
    assert _contact(sl, "Winston Churchill")["channel_keys"] == ["cable", "courier"]


def test_a_person_with_no_card_has_no_powers() -> None:
    sl = Slice()
    assert _contact(sl, "Henry A. Wallace")["powers"] == []


def test_nothing_from_the_private_card_appears() -> None:
    sl = Slice()
    me = sl.state.seats[sl.fdr].embodies
    text = json.dumps(reach(sl.state, sl.fdr))
    private = [
        text
        for who, card in sl.state.cards.items()
        if who != me
        for text in map(str, card.aims)
        if len(text) > 12
    ]
    assert private and not [p for p in private if p in text]
