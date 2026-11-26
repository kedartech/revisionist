"""A piece's figures as the seat sees them (KVW).

The toy world of ``tests/test_adjacency_moves.py`` with territories on, a field order on
each leader's card and ``kinds_in_battle`` switched on unless a test says otherwise. It
starts on 2 April 1900. Ilse plays Norra: its levy stands on the Norra Plain, its kites
beside it (two air steps from the Sudland Coast), its herald too. Sudland's levy stands on
the Sudland Coast. Reports are put straight into Norra's picture, as detection would
deliver them.
"""

import json
from collections.abc import Callable
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.realism import battle, kinds
from revisionist.core.realism.battle import Ending, Fighter, SideIn, Sides
from revisionist.core.state import State, Wake
from revisionist.engine import odds
from revisionist.engine.web import map_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests import test_adjacency_moves as adj
from tests.test_adjacency_moves import Logged, World, piece
from tests.test_battle_decisions_land import army
from tests.test_battle_kinds import as_kind, figures, switched
from tests.test_battles import no_ferry, toy
from tests.test_odds import RUNS, report, seen, time_now
from tests.test_weather import months, sky, weather

COAST = "sudland_coast"
HILLS = "norra_hills"
THAW = weather(
    "thaw",
    slows=[{"days": 2, "terrain": ["hills"], "pieces": ["land"]}],
    figures=[{"pieces": ["levy"], "attack": -1}],
)
FIVE = {"attack", "defence", "speed", "reach", "hidden"}
_dirs = count()


@pytest.fixture(autouse=True)
def fewer_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(odds, "ODDS_RUNS", RUNS)
    monkeypatch.setattr(odds.spread, "__defaults__", (RUNS, odds.ODDS_DAYS))


def play(tmp: Path, *changes: Callable[[World], None], on: bool = True) -> State:
    """The toy world with battles on, wake 1 open, the switch on unless ``on`` is false,
    ``changes`` applied."""
    where = tmp / f"w{next(_dirs)}"
    where.mkdir()
    world = toy(where, no_ferry, adj.levers, army, *changes, *((switched,) if on else ()))
    g = Logged(world, "ilse", "tomas")
    return g.state.model_copy(
        update={"wake": Wake(number=1, deadline=time_now()), "in_world_date": adj.START}
    )


def block(state: State, who: str = "ilse") -> dict[str, Any]:
    return dict(rs.seat_realism(state, adj.seat(who), set(), set(), None))


def own(state: State, name: str = "The Norra Levy") -> dict[str, Any]:
    (found,) = [m for m in block(state)["map"]["marks"] if m["name"] == name]
    assert found["piece"] is not None
    return dict(found["piece"])


def move(state: State, to: str, name: str = "The Norra Levy") -> dict[str, Any]:
    (found,) = [m for m in own(state, name)["moves"] if m["area"]["key"] == to]
    return dict(found)


def causes(lines: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    return {(c["figure"], c["direction"], c["cause"]) for c in lines}


def toward(state: State) -> api.OddsReply:
    p = odds.picture(state, adj.seat("ilse"), {"force": "norra_levy", "to": COAST})
    return odds.spread(p, odds.seed(state.campaign_id, odds.wake_of(state), adj.seat("ilse"), p))


# --- rule 1: each own piece carries its kind and its five figures --------------------------


def test_each_own_piece_carries_its_kind_and_five_figures(tmp_path: Path) -> None:
    state = play(tmp_path, figures("levy", attack=4))
    levy = own(state)["figures"]
    assert (levy["key"], levy["name"], levy["picture"]) == ("levy", "Levy", None)
    assert set(levy["figures"]) == FIVE
    # a step of 5 days or more is speed 1; it acts only where it stands; no concealment
    assert levy["figures"] == {"attack": 4, "defence": 3, "speed": 1, "reach": 1, "hidden": 1}
    kites = own(state, "The Norra Kites")["figures"]["figures"]
    assert (kites["speed"], kites["reach"]) == (5, 2)
    for name in ("The Norra Levy", "The Norra Kites", "The Norra Herald"):
        for f in own(state, name)["figures"]["figures"].values():
            assert kinds.FIGURE_LOW <= f <= kinds.FIGURE_HIGH


def test_with_the_switch_off_a_piece_is_sent_as_today(tmp_path: Path) -> None:
    off = own(play(tmp_path, on=False))
    assert "figures" not in off
    assert all("figures" not in m and "changes" not in m for m in off["moves"])


# --- rule 2: what changes the figures where the piece stands -------------------------------


def test_the_ground_and_the_weather_change_a_figure_where_it_stands(tmp_path: Path) -> None:
    state = play(
        tmp_path,
        figures("levy", on_terrain={"plain": {"defence": 1}}),
        sky(THAW, mainland=months(apr="thaw")),
    )
    levy = own(state)["figures"]
    assert causes(levy["changes"]) >= {
        ("defence", "up", "terrain"),
        ("attack", "down", "weather"),
        ("attack", "up", "air_cover"),  # its own kites stand beside it
    }
    assert (levy["here"]["attack"], levy["here"]["defence"]) == (3 - 1 + 1, 3 + 1 + 1)
    weather_line = next(c for c in levy["changes"] if c["cause"] == "weather")
    assert weather_line["words"] == "Thaw"


def test_a_change_names_no_amount(tmp_path: Path) -> None:
    state = play(tmp_path, figures("levy", on_terrain={"plain": {"defence": 2}}))
    for line in own(state)["figures"]["changes"]:
        assert set(line) == {"figure", "direction", "cause", "words"}
        assert not any(ch.isdigit() for ch in line["words"])


# --- rule 3: each lit area carries the days with the weather and the figures there ---------


def test_a_lit_area_carries_the_days_with_the_weather(tmp_path: Path) -> None:
    fair = move(play(tmp_path), HILLS)
    thaw = move(play(tmp_path, sky(THAW, mainland=months(apr="thaw"))), HILLS)
    assert (fair["days"], thaw["days"]) == (7, 7 + 2)
    assert ("speed", "down", "weather") in causes(thaw["changes"])


def test_a_lit_area_carries_the_figures_as_they_would_stand_there(tmp_path: Path) -> None:
    state = play(tmp_path, figures("levy", on_terrain={"hills": {"defence": 2}}))
    hills = move(state, HILLS)
    assert set(hills["figures"]) == FIVE
    assert hills["figures"]["defence"] == 5
    assert ("defence", "up", "terrain") in causes(hills["changes"])
    # own kites two air steps off give air cover at the coast
    assert ("attack", "up", "air_cover") in causes(move(state, COAST)["changes"])


# --- rule 4: an enemy kind only as a report names it ---------------------------------------

AGAINST_LEVY = figures("levy", against=[{"facing": "levy", "attack": 2}])


def test_an_enemy_kind_changes_a_figure_only_when_a_report_names_it(tmp_path: Path) -> None:
    state = play(tmp_path, AGAINST_LEVY)
    named = move(seen(state, report(kind="levy")), COAST)
    unnamed = move(seen(state, report(kind=None)), COAST)
    unseen = move(state, COAST)
    assert ("attack", "up", "enemy_kind") in causes(named["changes"])
    (line,) = [c for c in named["changes"] if c["cause"] == "enemy_kind"]
    assert line["words"] == "Levy reported there"
    for other in (unnamed, unseen):
        assert "enemy_kind" not in {c["cause"] for c in other["changes"]}


def test_a_report_naming_no_kind_gives_no_kind_on_the_map(tmp_path: Path) -> None:
    state = seen(play(tmp_path, AGAINST_LEVY), report(kind=None))
    (r,) = block(state)["map"]["reports"]
    assert (r["kind"], r["kind_name"]) == (None, "unknown")


def test_a_hidden_enemy_fighter_in_range_changes_nothing(tmp_path: Path) -> None:
    """Sudland's levy made a covering air kind in the coast: unreported, the lit area
    shows the same figures as with the plain levy there."""
    plain = move(play(tmp_path), COAST)
    hidden = move(play(tmp_path, as_kind("sudland_levy", "fire_kite")), COAST)
    assert (hidden["figures"], hidden["changes"]) == (plain["figures"], plain["changes"])


# --- fog: another nation's seat gets no figure, cause or kind beyond a report's ------------


def test_another_seat_gets_no_figure_of_norras_pieces(tmp_path: Path) -> None:
    state = play(tmp_path, figures("levy", on_terrain={"plain": {"defence": 1}}))
    tomas = block(state, "tomas")
    for m in tomas["map"]["marks"]:
        if m["side"] != "own":
            assert m["piece"] is None
    for m in tomas["map"]["marks"]:
        if m["piece"] is not None:
            assert "Norra" not in m["name"]
    words = json.dumps(tomas)
    assert "The Norra Levy" not in words


# --- rule 5: the odds are the battle's own, with the kinds as the seat knows them ----------


def _simulated(state: State, edges: tuple[int, int]) -> float:
    """The win share of ``battle.simulate`` on the same inputs as the odds, the levy's
    and the reported enemy's figures less 3 given as ``edges``."""
    p = odds.picture(state, adj.seat("ilse"), {"force": "norra_levy", "to": COAST})
    base = odds.seed(state.campaign_id, odds.wake_of(state), adj.seat("ilse"), p)
    assert p.kinded is not None
    v = p.kinded[0]
    wins = 0
    for run in range(RUNS):
        fighters = tuple(Fighter(s.key, odds._draw(base, run, s)) for s in p.enemy)
        enemy = SideIn(
            fighters=fighters,
            brought=sum(f.strength for f in fighters),
            own_ground=p.enemy_ground,
            air=v.enemy_air,
            supplied=p.enemy_supplied,
        )
        mine = p.own._replace(air=v.own_air, supplied=v.supplied)
        sides = Sides(
            mine,
            enemy,
            v.defence,
            p.presses,
            p.lull,
            (
                ((str(piece(state, "norra_levy").feature_id), edges[0]),),
                tuple((s.key, edges[1]) for s in p.enemy),
            ),
        )
        played = battle.simulate(sides, f"{base}\x1f{run}", odds.ODDS_DAYS)
        wins += played.ending is Ending.WON
    return round(100 * wins / RUNS, 1)


def test_the_odds_equal_a_battle_simulated_on_the_same_inputs(tmp_path: Path) -> None:
    state = seen(play(tmp_path, figures("levy", attack=5)), report(kind="levy"))
    reply = toward(state)
    assert reply["shares"] is not None
    # the levy attacks at 5 (+2); the reported levy defends at its plain 3 (+0)
    assert reply["shares"]["win"] == _simulated(state, (2, 0))


def test_the_odds_read_the_enemy_as_reported_or_as_its_domains_plain_kind(
    tmp_path: Path,
) -> None:
    strong = figures("levy", defence=5)
    named = toward(seen(play(tmp_path, strong), report(kind="levy")))
    plain = toward(seen(play(tmp_path, strong), report(kind=None)))
    flat = toward(seen(play(tmp_path), report(kind="levy")))
    assert named["shares"] is not None and plain["shares"] is not None
    assert flat["shares"] is not None
    # a named levy defends at 5; an unnamed piece is the plain land kind, every figure 3
    assert named["shares"]["win"] < plain["shares"]["win"]
    assert plain["shares"]["win"] == flat["shares"]["win"]


def test_with_the_switch_off_the_odds_are_as_today(tmp_path: Path) -> None:
    reply = toward(seen(play(tmp_path, figures("levy", attack=5), on=False), report()))
    assert set(reply) == api.OddsReply.__required_keys__


# --- rule 6: every region's weather this month and next, the same for every seat ----------


def test_the_reply_holds_every_regions_weather_this_month_and_next(tmp_path: Path) -> None:
    state = play(tmp_path, sky(THAW, mainland=months(apr="thaw")))
    found = block(state)["map"]["weather"]
    assert (found["month"], found["next_month"]) == ("apr", "may")
    rows = {r["region"]: (r["now"], r["next"]) for r in found["regions"]}
    assert rows["mainland"] == rows["north"] == rows["south"] == ("thaw", "fair")
    assert rows["waters"] == ("fair", "fair")
    (thaw,) = [k for k in found["kinds"] if k["key"] == "thaw"]
    assert {(e["kind"], e["figure"], e["direction"]) for e in thaw["does"]} == {
        ("levy", "speed", "down"),
        ("levy", "attack", "down"),
    }


def test_every_seat_gets_the_same_weather_but_what_it_does_to_its_own(tmp_path: Path) -> None:
    state = play(tmp_path, sky(THAW, mainland=months(apr="thaw")))

    def public(b: dict[str, Any]) -> Any:
        w = dict(b["map"]["weather"])
        w["kinds"] = [{k: v for k, v in kind.items() if k != "does"} for kind in w["kinds"]]
        return w

    assert public(block(state, "ilse")) == public(block(state, "tomas"))


def test_with_the_weather_off_the_reply_has_no_weather(tmp_path: Path) -> None:
    assert "weather" not in block(play(tmp_path))["map"]


# --- rule 7: the odds name the cause that moved them most ---------------------------------


def test_the_odds_name_the_cause_that_moved_them_most(tmp_path: Path) -> None:
    state = seen(play(tmp_path, AGAINST_LEVY), report(kind="levy"))
    moved = toward(state).get("moved_by")
    assert moved is not None
    assert (moved["cause"], moved["direction"], moved["words"]) == (
        "enemy_kind",
        "for",
        "Levy reported there",
    )


def test_the_odds_name_no_cause_with_the_switch_off(tmp_path: Path) -> None:
    reply = toward(seen(play(tmp_path, AGAINST_LEVY, on=False), report(kind="levy")))
    assert "moved_by" not in reply


def test_the_figure_words_are_the_fixed_ones() -> None:
    assert set(map_api.CAUSE_WORDS) == {
        "terrain",
        "weather",
        "out_of_supply",
        "out_of_fuel",
        "air_cover",
        "enemy_kind",
    }
