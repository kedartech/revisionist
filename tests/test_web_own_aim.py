"""The own aim as the seat sees it, with its check and its action (OWR).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``aims`` and ``own_aim``
on, as ``tests/test_own_aim.py`` plays it: Ilse of Norra holds three aims, the third
replaceable; Tomas of Sudland one. While Ilse's window is open her seat's data carries the
ladder of patterns her post may use, each blank with the values her view allows. The check
(``aim-check``) says whether a filled pattern stands, with the sentence as it will read, or
why not, and files nothing; the set (``aim-set``) stores it and answers with the aim as
stored, and after the window or a second time is refused in fixed words. An own aim's
source reads ``player``. Nothing here reaches another seat.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import aim_patterns
from revisionist.core.ids import SeatId
from revisionist.core.ontology import Controller
from revisionist.core.state import State
from revisionist.engine.store import MemoryStore
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web import stakes
from tests import test_own_aim as oa
from tests.test_realism_aims import ILSE, ISLE, NORRA, SUDLAND, TOMAS, Game, World, rule, seat_of
from tests.test_territory_model import CAMPAIGN
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of

FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"


def tomas_replaceable(w: World) -> None:
    """Tomas's one aim made replaceable, so his seat has a ladder of its own."""
    w["cards"][1]["aim_rules"] = [
        rule(1, {"check": "holds_area", "area": "isle", "holder": "sudland"}, replaceable=True)
    ]


def both(tmp: Path, *changes: Callable[[World], None]) -> Game:
    return oa.game(tmp, oa.setup(), *changes, people=(ILSE, TOMAS))


def ilse(g: Game) -> SeatId:
    return seat_of(g.state, ILSE)


def realism(g: Game, seat: SeatId) -> dict[str, Any]:
    out = rs.seat_realism(g.state, seat, set(), set(), None, events=list(g.store.read(CAMPAIGN)))
    out["stakes"] = stakes.seat_stakes(g.state, seat, list(g.store.read(CAMPAIGN)))
    return out


def check(g: Game, key: str, **values: str | int) -> api.AimCheck:
    return stakes.aim_check(g.state, ilse(g), key, values)


def put(g: Game, key: str, **values: str | int) -> api.AimCheck:
    return stakes.aim_set(g.store, CAMPAIGN, ilse(g), key, values)


def copy(g: Game) -> Game:
    """The game in a store of its own, from the same log."""
    out = Game.__new__(Game)
    out.store = MemoryStore()
    out.store.append_all(list(g.store.read(CAMPAIGN)))
    return out


# --- rule 1: the ladder on the seat's data, while the window is open -------------------


def test_the_seat_data_carries_its_posts_ladder_with_the_values_its_view_allows(
    played: Game,
) -> None:
    block = realism(played, ilse(played))["own_aim"]
    assert block["aim"] == 3 and block["replaces"] == "Hold the plain."
    assert [p["key"] for p in block["patterns"]] == ["keep_support", "make_peace", "take_ground"]
    peace = block["patterns"][1]
    assert peace == {
        "key": "make_peace",
        "sentence": "Make peace with {foe}.",
        "blanks": [{"name": "foe", "values": [{"value": SUDLAND, "label": "Sudland"}]}],
        "difficulty": 4,
        "government": False,
    }
    ground = block["patterns"][2]
    assert ground["government"] is True
    (place,) = ground["blanks"]
    assert [v["label"] for v in place["values"]] == ["The Sudland Coast", "The Isle"]
    assert block == stakes.own_aim_block(played.state, ilse(played))


def test_the_ladder_leaves_the_seat_data_once_the_window_closes(played: Game) -> None:
    oa.close_wake(played)
    assert "own_aim" not in realism(played, ilse(played))


def test_the_ladder_leaves_the_seat_data_once_the_aim_is_set(played: Game) -> None:
    assert put(played, "take_ground", place=ISLE)["stands"]
    assert "own_aim" not in realism(played, ilse(played))


def test_a_seat_with_no_replaceable_aim_gets_no_ladder(tmp_path: Path) -> None:
    g = both(tmp_path)
    assert "own_aim" not in realism(g, seat_of(g.state, TOMAS))


def test_a_seat_code_plays_gets_no_ladder(played: Game) -> None:
    state, seat = played.state, ilse(played)
    assert stakes.own_aim_block(state, seat) is not None
    coded = state.seats[seat].model_copy(update={"controller": Controller.AI})
    state = state.model_copy(update={"seats": {**state.seats, seat: coded}})
    assert stakes.own_aim_block(state, seat) is None


def test_with_own_aim_off_the_seat_data_is_as_before(tmp_path: Path) -> None:
    on = oa.game(tmp_path / "on")
    off = oa.game(tmp_path / "off", oa.setup(on=False))
    with_rule = realism(on, ilse(on))
    without = realism(off, ilse(off))
    assert "own_aim" not in without
    assert set(with_rule) - set(without) == {"own_aim"}
    assert stakes.own_aim_block(off.state, ilse(off)) is None


# --- rule 2: the check ------------------------------------------------------------------


def test_the_check_says_a_filled_pattern_stands_with_its_sentence(played: Game) -> None:
    before = list(played.store.read(CAMPAIGN))
    assert check(played, "take_ground", place=ISLE) == {
        "stands": True,
        "text": "Take The Isle for Norra.",
        "reasons": [],
    }
    assert list(played.store.read(CAMPAIGN)) == before  # files nothing


def test_the_check_gives_every_reason_a_filled_pattern_cannot_stand(played: Game) -> None:
    out = check(played, "keep_support", group="greens", line=55)
    assert out == {"stands": False, "text": None, "reasons": [aim_patterns.MET]}
    assert check(played, "army_peace", foe=SUDLAND)["reasons"] == [aim_patterns.NOT_YOUR_POST]
    assert check(played, "no_such")["reasons"] == [aim_patterns.NO_PATTERN]


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ({}, "key"),
        ({"key": "take_ground", "values": ["isle"]}, "values"),
        ({"key": "take_ground", "values": {"place": True}}, "values"),
        ({"key": "take_ground", "values": {"place": ["isle"]}}, "values"),
    ],
)
def test_a_malformed_body_is_refused_before_any_rule_reads_it(
    body: dict[str, Any], said: str
) -> None:
    with pytest.raises(ValueError, match=said):
        stakes.aim_args(body)


def test_the_args_read_a_key_and_its_values() -> None:
    assert stakes.aim_args({"key": "keep_support", "values": {"group": "greens", "line": 65}}) == (
        "keep_support",
        {"group": "greens", "line": 65},
    )
    assert stakes.aim_args({"key": "no_blanks"}) == ("no_blanks", {})


# --- rule 3: the set ---------------------------------------------------------------------


def test_the_set_stores_the_aim_and_answers_with_it_as_stored(played: Game) -> None:
    out = put(played, "take_ground", place=ISLE)
    stored = played.state.own_aims[ILSE]
    assert out == {"stands": True, "text": stored.text, "reasons": []}
    assert stored.text == "Take The Isle for Norra."


def test_a_second_set_is_refused_in_fixed_words(played: Game) -> None:
    put(played, "take_ground", place=ISLE)
    before = list(played.store.read(CAMPAIGN))
    out = put(played, "make_peace", foe=SUDLAND)
    assert out == {"stands": False, "text": None, "reasons": [aim_patterns.ALREADY_SET]}
    assert list(played.store.read(CAMPAIGN)) == before
    assert stakes.aim_reply(out, setting=True) == {
        "reply": stakes.AIM_NOT_SET,
        "refused": True,
        "aim": out,
    }


def test_a_set_after_the_window_is_refused_in_fixed_words(played: Game) -> None:
    oa.close_wake(played)
    before = list(played.store.read(CAMPAIGN))
    out = put(played, "take_ground", place=ISLE)
    assert out == {"stands": False, "text": None, "reasons": [aim_patterns.TOO_LATE]}
    assert list(played.store.read(CAMPAIGN)) == before
    assert played.state.own_aims == {}


def test_the_replies_are_in_fixed_words() -> None:
    stands: api.AimCheck = {"stands": True, "text": "Take The Isle for Norra.", "reasons": []}
    falls: api.AimCheck = {"stands": False, "text": None, "reasons": [aim_patterns.MET]}
    assert stakes.aim_reply(stands, setting=False)["reply"] == stakes.AIM_STANDS.format(
        text="Take The Isle for Norra."
    )
    assert stakes.aim_reply(stands, setting=True)["reply"] == stakes.AIM_SET.format(
        text="Take The Isle for Norra."
    )
    assert stakes.aim_reply(falls, setting=False) == {
        "reply": stakes.AIM_CANNOT,
        "refused": True,
        "aim": falls,
    }


def _cases(state: State, seat: SeatId) -> list[tuple[str, dict[str, str | int]]]:
    """Every filling of every pattern the seat's ladder offers, each blank's every value,
    and a value outside each blank, a pattern for another post and one that is not."""
    out: list[tuple[str, dict[str, str | int]]] = [("army_peace", {"foe": SUDLAND}), ("none", {})]
    for rung in aim_patterns.ladder(state, seat):
        names = [b.name for b in rung.blanks]
        combos: list[dict[str, str | int]] = [{}]
        for b in rung.blanks:
            combos = [{**c, b.name: v} for c in combos for v in b.values]
        out += [(rung.key, c) for c in combos]
        out.append((rung.key, {names[0]: NORRA}))
    return out


def test_the_check_equals_what_the_set_then_does_for_every_case(played: Game) -> None:
    seat = ilse(played)
    cases = _cases(played.state, seat)
    assert len(cases) > 12
    oa.close_wake(shut := copy(played))
    put(done := copy(played), "take_ground", place=ISLE)
    for g in (played, shut, done):
        for key, values in cases:
            checked = stakes.aim_check(g.state, seat, key, values)
            trial = copy(g)
            assert stakes.aim_set(trial.store, CAMPAIGN, seat, key, values) == checked, key
            stored = trial.state.own_aims.get(ILSE)
            if g is not done:
                assert (stored is not None) == checked["stands"], key
                assert stored is None or stored.text == checked["text"]


# --- rule 4: an own aim's source ---------------------------------------------------------


def test_an_own_aims_source_reads_player(played: Game) -> None:
    def third() -> dict[str, Any]:
        return dict(realism(played, ilse(played))["stakes"]["aims"][2])

    assert third()["source"] == "post"
    put(played, "take_ground", place=ISLE)
    assert third()["source"] == "player"
    assert third()["text"] == "Take The Isle for Norra."


# --- fog -----------------------------------------------------------------------------


def test_another_seats_patterns_and_own_aim_never_reach_a_seat(tmp_path: Path) -> None:
    g = both(tmp_path, tomas_replaceable)
    tomas = seat_of(g.state, TOMAS)
    block = realism(g, tomas)["own_aim"]
    assert [p["key"] for p in block["patterns"]] == ["keep_support"]
    (group, _) = block["patterns"][0]["blanks"]
    assert [v["label"] for v in group["values"]] == ["The Farmers"]
    put(g, "take_ground", place=ISLE)
    seen = json.dumps(realism(g, tomas))
    assert "Take The Isle for Norra." not in seen
    assert "Make peace with" not in seen and "Take {place}" not in seen
    assert "Hold the plain." not in seen  # the aim Ilse's replaced
    refused = stakes.aim_check(g.state, tomas, "take_ground", {"place": ISLE})
    assert refused["reasons"][0] == aim_patterns.NOT_YOUR_POST


def test_two_games_differing_in_a_hidden_fact_give_the_same_check_and_ladder(
    tmp_path: Path,
) -> None:
    def farmers(start: int) -> Callable[[World], None]:
        def change(w: World) -> None:
            sud = next(n for n in w["groups"] if n["nation"] == "sudland")
            sud["groups"][0]["start"] = start

        return change

    low = oa.game(tmp_path / "low", oa.setup(), oa.FOREIGN_MOOD, farmers(30))
    high = oa.game(tmp_path / "high", oa.setup(), oa.FOREIGN_MOOD, farmers(80))
    asked: dict[str, str | int] = {"group": "farmers", "line": 40}
    assert stakes.aim_check(low.state, ilse(low), "foreign_mood", asked) == stakes.aim_check(
        high.state, ilse(high), "foreign_mood", asked
    )
    assert stakes.own_aim_block(low.state, ilse(low)) == stakes.own_aim_block(
        high.state, ilse(high)
    )


# --- the server: both actions, the fixture ---------------------------------------------


@pytest.fixture
def played(tmp_path: Path) -> Game:
    return oa.game(tmp_path)


def test_the_server_answers_the_check_and_the_set(
    web: Web,  # noqa: F811
    tmp_path: Path,
) -> None:
    oa.world(tmp_path)
    game = Realism(web, world=str(tmp_path / "world.yaml"))
    client: Client = game.seat("ilse", "ilse")
    make_host(game, client)
    game.open_play()
    game.first_tick()
    block = realism_of(client)["own_aim"]
    (ground,) = [p for p in block["patterns"] if p["key"] == "take_ground"]
    isle = next(v["value"] for v in ground["blanks"][0]["values"] if v["label"] == "The Isle")
    status, out = post(client, "aim-check", key="take_ground", values={"place": isle})
    assert status == 200, out
    assert out == {
        "reply": stakes.AIM_STANDS.format(text="Take The Isle for Norra."),
        "refused": False,
        "aim": {"stands": True, "text": "Take The Isle for Norra.", "reasons": []},
    }
    assert "own_aim" in realism_of(client)  # the check set nothing
    status, out = post(client, "aim-set", key="take_ground", values={"place": isle})
    assert status == 200 and not out["refused"], out
    seen = realism_of(client)
    assert "own_aim" not in seen
    assert seen["stakes"]["aims"][2]["source"] == "player"
    status, out = post(client, "aim-set", key="take_ground", values={"place": isle})
    assert status == 200 and out["refused"] and out["reply"] == stakes.AIM_NOT_SET, out
    assert out["aim"]["reasons"] == [aim_patterns.ALREADY_SET]
    status, out = post(client, "aim-check", key="take_ground", values=["isle"])
    assert status == 200 and out["refused"], out


def test_the_fixture_carries_the_ladder_and_a_check_as_the_api_shapes_them(played: Game) -> None:
    fixture = json.loads(FIXTURE.read_text())
    block = fixture["own_aim"]
    assert set(block) == set(api.OwnAimBlock.__annotations__)
    for p in block["patterns"]:
        assert set(p) == set(api.AimPatternLine.__annotations__)
        for b in p["blanks"]:
            assert set(b) == set(api.AimBlankLine.__annotations__)
            assert all(set(v) == set(api.AimValue.__annotations__) for v in b["values"])
    assert set(fixture["aim_check"]) == set(api.AimCheck.__annotations__)
    shown = stakes.own_aim_block(played.state, ilse(played))
    assert shown is not None
    assert [p["key"] for p in block["patterns"]] == [p["key"] for p in shown["patterns"]]
