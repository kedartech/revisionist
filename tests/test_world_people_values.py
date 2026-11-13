"""The 44 people of autumn 1941 who are not playable carry the rank, loyalty and
competence of the people authoring sheet, and the two heads of state are reached as
heads."""

from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.realism.card import ChannelKind, Tie
from revisionist.core.realism.reach import channels_to, tie
from revisionist.core.state import State
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")

# person: (rank, loyalty, competence)
SHEET = {
    "wallace": (4, 0, 3),
    "hull": (4, 1, 3),
    "stimson": (4, 1, 3),
    "knox": (4, 1, 3),
    "rayburn": (4, 0, 3),
    "barkley": (4, 1, 3),
    "marshall": (3, 1, 4),
    "stark": (3, 1, 3),
    "morgenthau": (3, 2, 3),
    "stettinius": (3, 0, 3),
    "mccormack": (3, 2, 3),
    "welles": (2, 0, 4),
    "grew": (2, 0, 3),
    "king": (2, 0, 3),
    "wheeler": (2, 0, 3),
    "nye": (2, 0, 3),
    "kramer": (1, 0, 4),
    "hopkins": (1, 2, 3),
    "early": (1, 1, 3),
    "wh_clerk": (0, 0, 3),
    "cable_clerk": (0, 0, 3),
    "house_clerk": (0, 0, 3),
    "eden": (4, 1, 3),
    "pound": (3, 1, 3),
    "halifax": (2, 0, 3),
    "ismay": (2, 1, 3),
    "uk_cipher_clerk": (0, 0, 3),
    "bbc_clerk": (0, 0, 3),
    "hirohito": (5, 0, 3),
    "sugiyama": (3, 0, 2),
    "nagano": (3, 0, 3),
    "nomura": (2, 1, 2),
    "kurusu": (2, 0, 4),
    "cabinet_clerk": (0, 0, 3),
    "goering": (4, 1, 2),
    "ribbentrop": (4, 1, 3),
    "raeder": (3, 2, 3),
    "jodl": (3, 2, 4),
    "victor_emmanuel": (5, 0, 3),
    "cavallero": (3, 1, 2),
    "molotov": (4, 2, 3),
    "shaposhnikov": (3, 2, 4),
    "he_yingqin": (3, 1, 3),
    "soong": (2, 1, 3),
}


def _state() -> tuple[State, dict[str, str]]:
    world = cmp.load_world(cmp.world_path("autumn-1941"))
    return replay(compile_world(world, CAMPAIGN, cmp.versions())), resolve_keys(world, CAMPAIGN)


def test_every_person_who_is_not_playable_carries_the_sheet_values() -> None:
    state, ids = _state()
    world = cmp.load_world(cmp.world_path("autumn-1941"))
    assert {c.person for c in world.cards if not c.playable} == set(SHEET)
    got = {}
    for key in SHEET:
        card = state.cards[EntityId(ids[key])]
        got[key] = (card.reach.rank, card.loyalty, card.competence)
    assert got == SHEET


def test_the_emperor_and_the_king_are_heads_to_a_foreign_asker() -> None:
    state, ids = _state()

    def e(key: str) -> EntityId:
        return EntityId(ids[key])

    for head in ("hirohito", "victor_emmanuel"):
        assert tie(state, e("roosevelt"), e(head)) is Tie.HEAD
        assert channels_to(state, e("roosevelt"), e(head)) == (
            ChannelKind.CABLE,
            ChannelKind.COURIER,
        )
    assert tie(state, e("konoe"), e("hirohito")) is not Tie.HEAD
    assert channels_to(state, e("konoe"), e("victor_emmanuel")) == ()
    assert channels_to(state, e("tojo"), e("victor_emmanuel")) == ()
