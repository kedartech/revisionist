"""The 44 people of autumn 1941 who are not playable carry the rank, loyalty and
competence of the people authoring sheets, and the two heads of state are reached as
heads. Roosevelt's people want and hold to the world's topics and start with a regard
toward him; the eight leaders start with a regard toward each other."""

from datetime import date
from itertools import combinations

from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, OrderId, PipelineId, SeatId, derived_id
from revisionist.core.realism import pipelines
from revisionist.core.realism.card import ChannelKind, Tie
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.reach import channels_to, tie
from revisionist.core.state import State
from revisionist.core.visibility import Visibility
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")

# person: (rank, loyalty, competence)
SHEET = {
    "wallace": (4, 0, 3),
    "hull": (4, 1, 3),
    "stimson": (4, 1, 4),
    "knox": (4, 1, 3),
    "rayburn": (4, 1, 4),
    "barkley": (4, 2, 3),
    "marshall": (3, 1, 5),
    "stark": (3, 1, 3),
    "morgenthau": (3, 2, 3),
    "stettinius": (3, 1, 4),
    "mccormack": (3, 2, 3),
    "welles": (2, 0, 4),
    "grew": (2, 0, 3),
    "king": (2, 0, 4),
    "wheeler": (2, 0, 3),
    "nye": (2, 0, 3),
    "kramer": (1, 0, 4),
    "hopkins": (1, 3, 4),
    "early": (1, 2, 3),
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

# Roosevelt's people: his inner circle, those who answer to him, and King on the
# naval path. Churchill is in the circle too, but his card is a seat's own; his
# regard toward Roosevelt is one of the leaders' pairs.
# person: (wants, holds to, regard between Roosevelt and them)
ROOSEVELTS = {
    "hull": (("japan_talks", "diplomacy"), ("free_trade",), 1),
    "hopkins": (("lend_lease", "aid_soviet"), ("aid_britain",), 2),
    "stimson": (("rearmament", "atlantic_escort"), ("aid_britain",), 1),
    "knox": (("atlantic_escort", "naval_engagement"), ("freedom_of_seas",), 1),
    "marshall": (("rearmament", "the_draft"), ("europe_first",), 1),
    "stark": (("atlantic_escort", "pacific_fleet"), ("europe_first",), 1),
    "king": (("naval_engagement", "fleet_movements"), ("atlantic_escort",), 0),
    "early": (("public_opinion",), ("national_unity",), 2),
    "rayburn": (("the_draft", "neutrality_repeal"), ("legislation",), 1),
    "barkley": (("neutrality_repeal", "lend_lease"), ("legislation",), 2),
    "morgenthau": (("aid_china", "finance"), ("embargo",), 2),
    "stettinius": (("rearmament", "aid_soviet"), ("lend_lease",), 1),
    "wh_clerk": ((), (), 0),
}

LEADERS = ("roosevelt", "churchill", "stalin", "hitler", "konoe", "tojo", "mussolini", "chiang")

# two leaders: the regard between them
PAIRS = {
    frozenset(("roosevelt", "churchill")): 2,
    frozenset(("roosevelt", "stalin")): 1,
    frozenset(("roosevelt", "hitler")): -2,
    frozenset(("roosevelt", "konoe")): -1,
    frozenset(("roosevelt", "tojo")): -2,
    frozenset(("roosevelt", "mussolini")): -2,
    frozenset(("roosevelt", "chiang")): 1,
    frozenset(("churchill", "stalin")): 1,
    frozenset(("churchill", "hitler")): -2,
    frozenset(("churchill", "konoe")): -1,
    frozenset(("churchill", "tojo")): -2,
    frozenset(("churchill", "mussolini")): -2,
    frozenset(("churchill", "chiang")): 0,
    frozenset(("stalin", "hitler")): -2,
    frozenset(("stalin", "konoe")): 0,
    frozenset(("stalin", "tojo")): -1,
    frozenset(("stalin", "mussolini")): -2,
    frozenset(("stalin", "chiang")): 0,
    frozenset(("hitler", "konoe")): 1,
    frozenset(("hitler", "tojo")): 1,
    frozenset(("hitler", "mussolini")): 2,
    frozenset(("hitler", "chiang")): -1,
    frozenset(("konoe", "tojo")): -1,
    frozenset(("konoe", "mussolini")): 1,
    frozenset(("konoe", "chiang")): -2,
    frozenset(("tojo", "mussolini")): 1,
    frozenset(("tojo", "chiang")): -2,
    frozenset(("mussolini", "chiang")): -1,
}

WORLD = cmp.load_world(cmp.world_path("autumn-1941"))


def _state() -> tuple[State, dict[str, str]]:
    return replay(compile_world(WORLD, CAMPAIGN, cmp.versions())), resolve_keys(WORLD, CAMPAIGN)


def test_every_person_who_is_not_playable_carries_the_sheet_values() -> None:
    state, ids = _state()
    assert {c.person for c in WORLD.cards if not c.playable} == set(SHEET)
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


def test_roosevelts_people_are_his_circle_those_who_answer_to_him_and_king() -> None:
    state, ids = _state()
    me = EntityId(ids["roosevelt"])
    circle = {c.person for c in state.cards[me].inner_circle}
    under = {p for p, c in state.cards.items() if me in c.principals}
    people = (circle | under | {EntityId(ids["king"])}) - {EntityId(ids["churchill"])}
    assert EntityId(ids["churchill"]) in circle
    assert people == {EntityId(ids[k]) for k in ROOSEVELTS}


def test_the_world_names_about_twenty_topics_each_with_something_to_match() -> None:
    assert 18 <= len(WORLD.topics) <= 24
    for t in WORLD.topics:
        assert t.levers or t.effects or t.words, t.key
        assert all(w == w.lower() for w in t.words), t.key


def test_roosevelts_people_want_and_hold_to_topics_and_no_one_else_does() -> None:
    state, ids = _state()
    got = {}
    for key in (*SHEET, *LEADERS):
        card = state.cards[EntityId(ids[key])]
        if card.wants or card.holds_to:
            got[key] = (card.wants, card.holds_to)
    assert got == {k: (w, h) for k, (w, h, _) in ROOSEVELTS.items() if w or h}


def _regard(state: State, ids: dict[str, str]) -> dict[frozenset[str], int]:
    keys = {EntityId(v): k for k, v in ids.items()}
    return {frozenset((keys[r.a], keys[r.b])): r.disposition for r in state.relationships.values()}


def test_roosevelt_and_each_of_his_people_start_with_a_regard() -> None:
    state, ids = _state()
    regard = _regard(state, ids)
    got = {k: regard.get(frozenset(("roosevelt", k))) for k in ROOSEVELTS}
    assert got == {k: v for k, (_, _, v) in ROOSEVELTS.items()}


def test_each_pair_of_leaders_starts_with_a_regard() -> None:
    state, ids = _state()
    regard = _regard(state, ids)
    assert set(PAIRS) == {frozenset(p) for p in combinations(LEADERS, 2)}
    assert {p: regard.get(p) for p in PAIRS} == PAIRS


def test_every_starting_regard_is_public_and_within_two_steps() -> None:
    state, _ = _state()
    rels = list(state.relationships.values())
    assert len(rels) == len(ROOSEVELTS) + len(PAIRS)
    for r in rels:
        assert -2 <= r.disposition <= 2
        assert r.scope.visibility is Visibility.PUBLIC


def _order(lever: str, **params: str | int) -> Order:
    return Order(
        order_id=OrderId(derived_id(CAMPAIGN, "order", lever)),
        issuer=SeatId(derived_id(CAMPAIGN, "seat", "roosevelt")),
        lever=lever,
        pipeline=PipelineId(derived_id(CAMPAIGN, "pipeline", lever)),
        params=dict(params),
        filed=date(1941, 9, 11),
    )


def _touched(state: State, order: Order) -> set[str]:
    """The topics the order touches, each asked of the holder's rule through a card that
    wants that topic alone."""
    card = next(iter(state.cards.values()))
    return {
        key
        for key in state.topics
        if pipelines._interest(state, order, card.model_copy(update={"wants": (key,)})) == 2
    }


def test_each_scripted_order_touches_exactly_its_topics() -> None:
    state, _ = _state()
    orders = {
        "neutrality bill": (
            _order("send_bill", bill="neutrality_revision", urgency="urgent"),
            {"legislation", "neutrality_repeal"},
        ),
        "draft bill": (
            _order("send_bill", bill="draft_extension", urgency="ordinary"),
            {"legislation", "the_draft"},
        ),
        "finding for Britain": (
            _order("lend_lease_finding", recipient="uk", share_pct=10),
            {"lend_lease", "aid_britain"},
        ),
        "finding for the Soviet Union": (
            _order("lend_lease_finding", recipient="ussr", share_pct=10),
            {"lend_lease", "aid_soviet"},
        ),
        "shoot on sight": (
            _order("naval_order", order="shoot_on_sight", zone="western_atlantic"),
            {"naval_engagement", "atlantic_escort"},
        ),
        "address on the seas": (
            _order("public_address", theme="freedom_of_the_seas"),
            {"public_opinion", "freedom_of_seas"},
        ),
    }
    assert {k: _touched(state, o) for k, (o, _) in orders.items()} == {
        k: want for k, (_, want) in orders.items()
    }


def test_an_order_touches_what_the_holder_wants_and_not_what_they_do_not() -> None:
    state, ids = _state()
    rayburn = state.cards[EntityId(ids["rayburn"])]
    hopkins = state.cards[EntityId(ids["hopkins"])]
    bill = _order("send_bill", bill="neutrality_revision", urgency="urgent")
    finding = _order("lend_lease_finding", recipient="uk", share_pct=10)
    assert pipelines._interest(state, bill, rayburn) == 2
    assert pipelines._interest(state, finding, rayburn) == 0
    assert pipelines._interest(state, finding, hopkins) == 2
