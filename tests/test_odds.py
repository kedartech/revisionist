"""The odds spread, simulated on the server from the seat's own picture (ODS).

Two toy games from ``tests/test_battles.py``: at the start, with Norra's levy (strength 5)
at Norrhavn on the Norra Plain and Sudland's levy (strength 4) at Sudby on the Sudland
Coast, so Ilse may ask the odds of sending her levy to the coast; and the coast's battle
open after its first round (``tests/test_web_battles.game``), Norra attacking. Reports are
put straight into Norra's picture, as detection would deliver them.
"""

import json
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import SeatId
from revisionist.core.realism import battle, detect
from revisionist.core.realism.battle import Decision, Fighter, SideIn
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.detect import Confidence, Report, Source
from revisionist.core.realism.document import BodyField, DocumentKind, DocumentTruth, DocumentView
from revisionist.core.state import Rule, State, Wake
from revisionist.core.visibility import private_to
from revisionist.engine import odds
from revisionist.engine.odds import BusyError, LimitedError, Service
from revisionist.engine.store import load_state
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web import server
from tests.test_adjacency_moves import START, Logged, day, entity, levers, piece
from tests.test_battle_decisions_land import army
from tests.test_battles import COAST, OPENS, no_ferry, strengths, toy
from tests.test_territory_model import CAMPAIGN
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_battles import ADA, ILSE, TOMAS, at_wake, game, ostmark, store_of, walked
from tests.test_web_phase4_contract import solo  # noqa: F401
from tests.test_web_realism import Realism, post

FIXTURES = Path(__file__).parents[1] / "web" / "test" / "fixtures"
RUNS = 300
"""Runs per request in these tests: the rules hold at any count."""
DEFAULTS = (odds.ODDS_RUNS, odds.ODDS_DAYS, odds.PER_MINUTE, odds.LOW_CENTILE, odds.HIGH_CENTILE)


@pytest.fixture(autouse=True)
def fewer_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(odds, "ODDS_RUNS", RUNS)
    monkeypatch.setattr(odds.spread, "__defaults__", (RUNS, odds.ODDS_DAYS))


def report(
    key: str = "r1",
    strength: tuple[int, int] | None = (3, 5),
    area: str = COAST,
    kind: str | None = "levy",
    seen: date = START,
) -> Report:
    return Report(
        key=key,
        kind=kind,
        strength=strength,
        area=entity(area),
        seen=seen,
        source=Source.CONTACT,
        rank=0,
        confidence=Confidence.B,
        arrives=seen,
    )


def seen(state: State, *reports: Report) -> State:
    """``state`` with reports on and Norra's picture holding ``reports``."""
    picture = detect.Picture(delivered={r.key: r for r in reports})
    return state.model_copy(
        update={
            "rules": state.rules | {Rule.REPORTS},
            "reports": {**state.reports, entity("norra"): picture},
        }
    )


def start(tmp: Path) -> State:
    """The toy world at the start, each leader commanding its own forces, wake 1 open."""
    g = Logged(toy(tmp, no_ferry, levers, army), "ilse", "tomas")
    return g.state.model_copy(
        update={"wake": Wake(number=1, deadline=time_now()), "in_world_date": START}
    )


def time_now() -> Any:
    from tests.test_web_battles import NOW

    return NOW


def ask(state: State, who: SeatId = ILSE, **body: str) -> api.OddsReply:
    p = odds.picture(state, who, body)
    return odds.spread(p, odds.seed(state.campaign_id, odds.wake_of(state), who, p))


def toward(state: State) -> api.OddsReply:
    return ask(state, force="norra_levy", to=COAST)


def text(reply: Any) -> str:
    return json.dumps(reply, sort_keys=True)


def retier(state: State, key: str, tier: int) -> State:
    f = piece(state, key)
    return state.model_copy(
        update={"features": {**state.features, f.feature_id: f.model_copy(update={"tier": tier})}}
    )


# --- Rule 1: the action takes an own piece and a destination, or a battle and a decision --


def test_the_odds_of_sending_a_piece_into_an_area(tmp_path: Path) -> None:
    reply = toward(seen(start(tmp_path), report()))
    assert reply["known"] is True
    assert reply["area"] == COAST


def test_the_odds_of_a_decision_in_an_open_battle(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = seen(at_wake(g, 1), report(seen=walked(g)))
    held = ask(state, force="norra_levy", battle=COAST, decision="hold")
    pressed = ask(state, force="norra_levy", battle=COAST, decision="press")
    assert held["known"] and pressed["known"]
    assert held != pressed


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ({"force": "sudland_levy", "to": "norra_plain"}, odds.NOT_YOURS),
        ({"force": "norra_levy"}, odds.ONE_OF),
        ({"force": "norra_levy", "to": COAST, "battle": COAST}, odds.ONE_OF),
        ({"force": "norra_levy", "to": "atlantis"}, "There is no area atlantis."),
        ({"force": "norra_levy", "battle": COAST, "decision": "charge"}, "The decision is one"),
        ({"force": "norra_levy", "battle": "norra_plain", "decision": "hold"}, odds.NOT_IN),
    ],
)
def test_a_request_the_seat_may_not_make_is_refused(
    tmp_path: Path, body: dict[str, Any], why: str
) -> None:
    g = game(tmp_path)
    with pytest.raises(ValueError, match=why[:20]):
        odds.picture(at_wake(g, 1), ILSE, body)


def test_a_game_without_battles_gives_no_odds(tmp_path: Path) -> None:
    state = start(tmp_path)
    off = state.model_copy(update={"rules": state.rules - {Rule.BATTLES}})
    with pytest.raises(ValueError, match="Battles are not fought"):
        toward(off)


# --- Rule 2: a spread, never one figure ----------------------------------------------------


def test_the_reply_is_a_spread_with_every_part(tmp_path: Path) -> None:
    reply = toward(seen(start(tmp_path), report()))
    assert set(reply) == set(api.OddsReply.__annotations__)
    shares = reply["shares"]
    assert shares is not None
    assert set(shares) == {"win", "stalemate", "loss"}
    assert abs(shares["win"] + shares["stalemate"] + shares["loss"] - 100) < 0.5
    for lost in (reply["own_lost"], reply["enemy_lost"]):
        assert lost is not None and 0 <= lost["low"] <= lost["high"]
    assert reply["own_lost"] is not None and reply["own_lost"]["low"] < reply["own_lost"]["high"]
    assert reply["taken"] is not None and reply["forced_back"] is not None
    assert reply["back_to"] == "norra_hills"  # the coast borders the hills (no ferry)
    assert [s["strength"] for s in reply["by_strength"]] == [3, 4, 5]
    assert reply["reports"] == ["r1"]


def test_the_reply_has_no_single_headline_number(tmp_path: Path) -> None:
    reply = toward(seen(start(tmp_path), report()))
    numbers = {k for k, v in reply.items() if isinstance(v, float)}
    assert numbers <= {"taken", "forced_back"}  # each a part of the spread, beside the shares
    assert not {"odds", "chance", "percent", "headline", "score"} & set(reply)
    assert isinstance(reply["shares"], dict) and len(reply["shares"]) == 3


def test_the_loss_range_runs_from_the_10th_to_the_90th_percentile() -> None:
    assert odds._centile(list(range(101)), odds.LOW_CENTILE) == 10
    assert odds._centile(list(range(101)), odds.HIGH_CENTILE) == 90


def test_a_win_takes_the_territory_after_the_capture_days(tmp_path: Path) -> None:
    reply = toward(seen(start(tmp_path), report(strength=(1, 1))))
    assert reply["taken"] is not None and reply["taken"] > 50
    assert reply["taken_days"] is not None and reply["taken_days"] >= 1 + 2


def test_the_win_share_at_each_strength_falls_as_the_enemy_grows(tmp_path: Path) -> None:
    reply = toward(seen(start(tmp_path), report(strength=(1, 9))))
    wins = [s["win"] for s in reply["by_strength"]]
    assert wins[0] is not None and wins[-1] is not None and wins[0] > wins[-1]


def test_withdraw_gives_up_the_field_without_a_round(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = seen(at_wake(g, 1), report(seen=walked(g)))
    reply = ask(state, force="norra_levy", battle=COAST, decision="withdraw")
    assert reply["shares"] == {"win": 0.0, "stalemate": 0.0, "loss": 100.0}
    assert reply["forced_back"] == 100.0


# --- Rule 3: own pieces exactly; the enemy only from the reports ----------------------------


def test_fog_the_true_enemy_changes_nothing_while_the_reports_stand(tmp_path: Path) -> None:
    state = seen(start(tmp_path), report())
    weak, strong = retier(state, "sudland_levy", 1), retier(state, "sudland_levy", 9)
    assert text(toward(weak)) == text(toward(strong)) == text(toward(state))


def test_fog_in_an_open_battle_too(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = seen(at_wake(g, 1), report(seen=walked(g)))
    body = {"force": "norra_levy", "battle": COAST, "decision": "press"}
    weak, strong = retier(state, "sudland_levy", 1), retier(state, "sudland_levy", 9)
    assert text(ask(weak, ILSE, **body)) == text(ask(strong, ILSE, **body))


def test_the_own_piece_goes_in_exactly(tmp_path: Path) -> None:
    state = seen(start(tmp_path), report())
    assert text(toward(retier(state, "norra_levy", 2))) != text(toward(state))


def test_the_enemy_is_drawn_across_its_reported_range(tmp_path: Path) -> None:
    state = start(tmp_path)
    low = toward(seen(state, report(strength=(1, 1))))
    high = toward(seen(state, report(strength=(8, 8))))
    assert low["shares"] is not None and high["shares"] is not None
    assert low["shares"]["win"] > high["shares"]["win"]
    spread = toward(seen(state, report(strength=(1, 8))))
    tried = [s for s in spread["by_strength"] if s["win"] is not None]
    assert len(tried) == 8  # every strength in the range was drawn


def test_a_report_elsewhere_or_of_another_domain_is_not_an_enemy_there(tmp_path: Path) -> None:
    state = start(tmp_path)
    away = toward(seen(state, report(area="isle")))
    galley = toward(seen(state, report(kind="galley")))
    assert away["known"] is False and galley["known"] is False


def test_a_report_with_no_strength_spans_its_kinds_range(tmp_path: Path) -> None:
    reply = toward(seen(start(tmp_path), report(strength=None)))
    assert reply["by_strength"][0]["strength"] == 1


# --- Rule 4: with no report, the enemy is unknown -----------------------------------------


def test_with_no_report_the_enemy_is_unknown_and_only_the_terrain_is_given(
    tmp_path: Path,
) -> None:
    reply = toward(seen(start(tmp_path)))
    assert reply["known"] is False
    assert reply["terrain"] == {
        "area": COAST,
        "name": "The Sudland Coast",
        "terrain": "plain",
        "defence": 0,
        "holder": "Sudland",
    }
    for k in ("shares", "own_lost", "enemy_lost", "taken", "taken_days", "forced_back"):
        assert dict(reply)[k] is None, k
    assert reply["by_strength"] == [] and reply["runs"] == 0


# --- Rule 5: seeded runs, the same reply each time -----------------------------------------


def test_each_request_runs_the_set_number_of_runs_over_the_set_days(tmp_path: Path) -> None:
    reply = toward(seen(start(tmp_path), report()))
    assert (reply["runs"], reply["days"]) == (RUNS, odds.ODDS_DAYS)
    assert odds.ODDS_RUNS == RUNS


def test_the_defaults_are_the_plans() -> None:
    assert DEFAULTS == (2000, 14, 30, 10, 90)


def test_repeat_two_requests_one_reply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = seen(start(tmp_path), report())
    first = text(toward(state))
    monkeypatch.setattr(time, "time", lambda: 1e9)
    monkeypatch.setattr(time, "monotonic", lambda: 1e9)
    monkeypatch.setattr(time, "time_ns", lambda: 10**18)
    assert text(toward(state)) == first


def test_the_seed_is_the_campaign_the_wake_the_seat_and_the_inputs(tmp_path: Path) -> None:
    state = seen(start(tmp_path), report())
    p = odds.picture(state, ILSE, {"force": "norra_levy", "to": COAST})
    base = odds.seed(state.campaign_id, 1, ILSE, p)
    assert base == odds.seed(state.campaign_id, 1, ILSE, p)
    assert base != odds.seed(state.campaign_id, 2, ILSE, p)
    assert base != odds.seed(state.campaign_id, 1, TOMAS, p)
    other = odds.picture(retier(state, "norra_levy", 2), ILSE, {"force": "norra_levy", "to": COAST})
    assert base != odds.seed(state.campaign_id, 1, ILSE, other)


def test_the_reply_is_cached_for_the_wake(tmp_path: Path) -> None:
    service = Service(workers=1, queue=1)
    state = seen(start(tmp_path), report())
    body = {"force": "norra_levy", "to": COAST}
    first = odds.reply(service, state, ILSE, body)
    again = odds.reply(service, state, ILSE, body)
    assert first == again and service.computed == 1
    later = state.model_copy(update={"wake": Wake(number=2, deadline=time_now())})
    odds.reply(service, later, ILSE, body)
    assert service.computed == 2
    service.close()


# --- Rule 6: files nothing; bounded as a whole ---------------------------------------------


def _empty() -> Any:
    return {"known": False}


def _slow(gate: threading.Event, calls: list[int]) -> Any:
    def compute() -> Any:
        calls.append(1)
        gate.wait(5)
        return {"known": False}

    return compute


def test_two_identical_cold_requests_at_once_are_computed_once() -> None:
    service = Service(workers=2, queue=0)
    gate, calls = threading.Event(), list[int]()
    got: list[Any] = []

    def asks(who: str) -> None:
        got.append(service.ask("k", ("c", who), _slow(gate, calls)))

    threads = [threading.Thread(target=asks, args=(s,)) for s in ("a", "b")]
    for t in threads:
        t.start()
    time.sleep(0.2)
    gate.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1 and service.computed == 1
    assert len(got) == 2 and got[0] is got[1]
    service.close()


def test_a_full_queue_answers_busy() -> None:
    service = Service(workers=1, queue=1)
    gate, calls = threading.Event(), list[int]()
    threads = [
        threading.Thread(target=service.ask, args=(k, ("c", k), _slow(gate, calls)))
        for k in ("a", "b")
    ]
    for t in threads:
        t.start()
    time.sleep(0.2)
    with pytest.raises(BusyError):
        service.ask("c", ("c", "c"), _slow(gate, calls))
    gate.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 2  # one running, one waiting: both answered once there was room
    service.close()


def test_busy_is_a_refused_reply_that_names_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = Service()

    def full(*_: Any) -> Any:
        raise BusyError

    monkeypatch.setattr(service, "ask", full)
    state = seen(start(tmp_path), report())
    out = odds.reply(service, state, ILSE, {"force": "norra_levy", "to": COAST})
    assert out == {"reply": odds.BUSY, "refused": True, "busy": True}


def test_each_seat_may_ask_thirty_times_a_minute() -> None:
    now = [0.0]
    service = Service(clock=lambda: now[0])
    for _ in range(odds.PER_MINUTE):
        service.ask("k", ("c", "ilse"), _empty)
    with pytest.raises(LimitedError):
        service.ask("k", ("c", "ilse"), _empty)
    service.ask("k", ("c", "tomas"), _empty)
    now[0] = 60.0
    service.ask("k", ("c", "ilse"), _empty)
    service.close()


def test_the_cache_is_bounded() -> None:
    service = Service(cache=2)
    for k in ("a", "b", "c"):
        service.ask(k, ("c", k), _empty)
    assert service.computed == 3
    service.ask("a", ("c", "a2"), _empty)
    assert service.computed == 4  # the oldest was dropped
    service.close()


def test_asking_files_nothing(tmp_path: Path) -> None:
    state = seen(start(tmp_path), report())
    before = state.model_dump_json()
    odds.reply(Service(), state, ILSE, {"force": "norra_levy", "to": COAST})
    assert state.model_dump_json() == before


def test_the_room_answers_odds_and_appends_no_event(
    solo: tuple[Realism, Client],  # noqa: F811
) -> None:
    game, ada = solo
    store = game.web.app.open()
    try:
        before = len(list(store.read(game.campaign)))
        status, out = post(ada, "odds", force="anything", to="anywhere")
        after = len(list(store.read(game.campaign)))
    finally:
        store.close()
    assert status == 200
    assert out == {"reply": odds.OFF, "refused": True}  # the 1941 slice fights no battles
    assert after == before


# --- Rule 7: the closing odds of an ended battle --------------------------------------------


def fought_out(tmp: Path, *changes: Any) -> Logged:
    """The coast's battle walked to its end: Norra's levy breaks on day 14."""
    g = game(tmp, *changes)
    g.walk(OPENS + timedelta(days=1), day(30))
    assert not g.state.battles
    return g


def test_an_ended_battle_gives_the_odds_as_they_truly_stood_beside_the_seats_own(
    tmp_path: Path,
) -> None:
    g = fought_out(tmp_path)
    (e,) = odds.ended(Service(), g.state, ILSE, g.log)
    assert e.ended == day(14)
    assert e.closing is not None
    truly, own = e.closing["truly"], e.closing["seen"]
    assert truly["known"] is True
    assert truly["reports"] == []
    assert own["known"] is False  # Norra had no report of the coast that day
    assert set(e.closing) == set(api.ClosingOdds.__annotations__)
    assert set(truly) == set(api.OddsOutcome.__annotations__)


def keys_in(value: Any) -> set[str]:
    """Every key of every mapping inside ``value``."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_in(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_in(v)}
    return set()


def test_the_closing_truth_names_no_enemy_strength_and_keeps_its_shares(tmp_path: Path) -> None:
    """The truth half gives how the first day truly stood as shares, never the enemy's
    exact strength: the round reports give the enemy's losses exactly, so a true total
    would tell the seat what is left of the enemy."""
    g = fought_out(tmp_path)
    (mine,) = odds.ended(Service(), g.state, ILSE, g.log)
    (theirs,) = odds.ended(Service(), g.state, TOMAS, g.log)
    assert mine.closing is not None and theirs.closing is not None
    for closing in (mine.closing, theirs.closing):
        assert not any("strength" in k for k in keys_in(closing["truly"]))
    assert mine.closing["truly"]["shares"] == {"win": 91.7, "stalemate": 0.0, "loss": 8.3}
    assert theirs.closing["truly"]["shares"] == {"win": 10.0, "stalemate": 0.0, "loss": 90.0}


def test_each_side_gets_its_own_closing_odds(tmp_path: Path) -> None:
    g = fought_out(tmp_path)
    (mine,) = odds.ended(Service(), g.state, ILSE, g.log)
    (theirs,) = odds.ended(Service(), g.state, TOMAS, g.log)
    assert mine.closing is not None and theirs.closing is not None
    win, loss = mine.closing["truly"]["shares"], theirs.closing["truly"]["shares"]
    assert win is not None and loss is not None
    assert abs(win["win"] - loss["loss"]) < 10  # the same truth from either side, own seeds


def test_the_seats_own_picture_ignores_the_truth_while_the_truth_moves(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    weak = fought_out(tmp_path / "a", strengths(sudland_levy=3))
    strong = fought_out(tmp_path / "b")
    (w,) = odds.ended(Service(), weak.state, ILSE, weak.log)
    (s,) = odds.ended(Service(), strong.state, ILSE, strong.log)
    assert w.closing is not None and s.closing is not None
    assert text(w.closing["seen"]) == text(s.closing["seen"])
    assert text(w.closing["truly"]) != text(s.closing["truly"])
    a, b = dict(w.closing["truly"]), dict(s.closing["truly"])
    moved = {k for k in a if a[k] != b[k]}
    assert "shares" in moved
    assert moved <= {"shares", "own_lost", "enemy_lost", "taken", "taken_days", "forced_back"}


def test_no_closing_odds_before_the_battle_ends(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert g.state.battles
    assert odds.ended(Service(), g.state, ILSE, g.log) == []
    (b,) = rs.seat_realism(at_wake(g, 1), ILSE, set(), set(), None)["battles"]
    assert b["ended"] is None and b["closing"] is None


def test_no_closing_odds_with_battles_off_or_in_a_stored_game(tmp_path: Path) -> None:
    """A stored game's rules are empty, so battles are off there as in a game without them."""
    g = fought_out(tmp_path)
    off = g.state.model_copy(update={"rules": g.state.rules - {Rule.BATTLES}})
    stored = g.state.model_copy(update={"rules": g.state.rules - g.state.rules})
    assert odds.ended(Service(), off, ILSE, g.log) == []
    assert odds.ended(Service(), stored, ILSE, g.log) == []


def test_a_battle_the_seats_nation_did_not_fight_has_no_closing_odds(tmp_path: Path) -> None:
    g = fought_out(tmp_path, ostmark)
    assert odds.ended(Service(), g.state, ADA, g.log) == []


def test_the_battles_block_lists_the_ended_battle_after_the_open_ones(tmp_path: Path) -> None:
    g = fought_out(tmp_path)
    state = at_wake(g, 2)
    ended = odds.ended(Service(), state, ILSE, g.log)
    (b,) = rs.seat_realism(state, ILSE, set(), set(), None, ended_battles=ended)["battles"]
    assert b["ended"] == day(14).isoformat() and b["closing"] == ended[0].closing
    assert [r["own_lost"] for r in b["rounds"]] == [1, 1, 1]  # its own reports of the rounds
    assert b["strength"] == 2
    assert b["decisions"] == [] and b["pieces"] == [] and b["contingencies"] == []
    assert set(b) == set(api.BattleView.__annotations__)


def test_the_closing_odds_are_computed_once_and_kept(tmp_path: Path) -> None:
    g = fought_out(tmp_path)
    service = Service()
    first = odds.ended(service, g.state, ILSE, g.log)
    again = odds.ended(service, g.state, ILSE, g.log)
    assert first == again and service.computed == 1


def test_a_busy_desk_leaves_the_closing_odds_for_the_next_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = fought_out(tmp_path)
    service = Service()

    def full(*_: Any) -> Any:
        raise BusyError

    monkeypatch.setattr(service, "ask", full)
    (e,) = odds.ended(service, g.state, ILSE, g.log)
    assert e.closing is None


# --- Rule 9: the offline measurement for Josh at gate 3 -------------------------------------


def _timed(n: int, act: Any) -> list[float]:
    out: list[float] = []
    for _ in range(n):
        a = time.perf_counter()
        act()
        out.append(time.perf_counter() - a)
    return out


def _ms(times: list[float]) -> dict[str, float]:
    ordered = sorted(times)
    return {
        "median_ms": round(1000 * ordered[len(ordered) // 2], 2),
        "p90_ms": round(1000 * ordered[(9 * (len(ordered) - 1)) // 10], 2),
        "max_ms": round(1000 * ordered[-1], 2),
    }


def _largest(p: odds.Picture) -> odds.Picture:
    """Ten pieces a side at full strength and ten reports: more in one area than any
    test world stands there."""
    own = SideIn(fighters=tuple(Fighter(f"own{n}", 5) for n in range(10)), brought=50)
    return p._replace(own=own, enemy=tuple(odds.Seen(f"r{n}", 1, 5) for n in range(10)))


def test_rule_9_measures_odds_and_room_latency_under_concurrent_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cold cache, the plan's ``ODDS_RUNS`` and the server's pool: 16 distinct odds
    requests at once on the toy coast and on the largest picture, while the room is
    loaded and a battle decision filed. Reports the figures; asserts only that every
    request was answered. Set ``ODDS_MEASURE_OUT`` to keep them as JSON."""
    import os

    monkeypatch.setattr(odds, "ODDS_RUNS", DEFAULTS[0])
    monkeypatch.setattr(odds.spread, "__defaults__", (DEFAULTS[0], DEFAULTS[1]))
    (tmp_path / "a").mkdir()
    state = seen(start(tmp_path / "a"), report())
    base = odds.picture(state, ILSE, {"force": "norra_levy", "to": COAST})
    g = game(tmp_path)
    room_state = at_wake(g, 1)
    store = store_of(g)

    def load_room() -> None:
        rs.seat_realism(room_state, ILSE, set(), set(), None)

    def file_order() -> None:
        server._battle_asks(
            load_state(store, CAMPAIGN), ILSE, "battle", {"area": COAST, "decision": "hold"}
        )

    alone = {"load_room": _ms(_timed(10, load_room)), "file_order": _ms(_timed(10, file_order))}
    figures: dict[str, Any] = {
        "runs": DEFAULTS[0],
        "days": DEFAULTS[1],
        "workers": odds.WORKERS,
        "queue": odds.QUEUE,
        "room_alone": alone,
    }
    for name, picture in (("representative", base), ("largest", _largest(base))):
        service = Service(per_minute=1000)
        latencies: list[float] = []
        answered: list[bool] = []

        def one(
            n: int,
            p: odds.Picture = picture,
            service: Service = service,
            answered: list[bool] = answered,
            latencies: list[float] = latencies,
        ) -> None:
            q = p._replace(lull=n)  # sixteen distinct requests: nothing is shared
            key = odds.seed(state.campaign_id, 1, ILSE, q)
            a = time.perf_counter()
            try:
                service.ask(key, ("c", f"s{n}"), lambda: odds.spread(q, key))
                answered.append(True)
            except BusyError:
                answered.append(False)
            latencies.append(time.perf_counter() - a)

        threads = [threading.Thread(target=one, args=(n,)) for n in range(16)]
        for th in threads:
            th.start()
        room = {"load_room": _ms(_timed(5, load_room)), "file_order": _ms(_timed(5, file_order))}
        for th in threads:
            th.join(120)
        service.close()
        figures[name] = {
            "requests": 16,
            "answered": answered.count(True),
            "busy": answered.count(False),
            "odds": _ms(latencies),
            "room_meanwhile": room,
        }
        assert len(answered) == 16
    out = os.environ.get("ODDS_MEASURE_OUT")
    if out:
        Path(out).write_text(json.dumps(figures, indent=2) + "\n")
    with capsys.disabled():
        print("\nodds measurement:", json.dumps(figures))


# --- review findings ------------------------------------------------------------------------


def test_fog_a_defenders_odds_do_not_read_the_attackers_decision(tmp_path: Path) -> None:
    """The attacker's decision is engine only: Tomas, defending, gets the same reply
    whether Norra has decided to press or to hold."""
    g = game(tmp_path)
    state = at_wake(g, 1)
    sudland = detect.Picture(delivered={"r1": report(seen=walked(g))})
    state = state.model_copy(
        update={"rules": state.rules | {Rule.REPORTS}, "reports": {entity("sudland"): sudland}}
    )
    body = {"force": "sudland_levy", "battle": COAST, "decision": "hold"}
    b = state.battles[entity(COAST)]
    replies = []
    for d in (Decision.PRESS, Decision.HOLD, Decision.WITHDRAW):
        side = b.attacker.model_copy(update={"decision": d, "decided_wake": 1})
        moved = state.model_copy(
            update={"battles": {b.area: b.model_copy(update={"attacker": side})}}
        )
        replies.append(text(ask(moved, TOMAS, **body)))
    assert replies[0] == replies[1] == replies[2]


def test_an_ended_battles_rounds_stop_at_its_end(tmp_path: Path) -> None:
    """A later round report for the same area (a battle fought there later) is not one
    of the ended battle's rounds."""
    g = fought_out(tmp_path)
    (e,) = odds.ended(Service(), g.state, ILSE, g.log)
    later = e.ended + timedelta(days=5)
    doc_id = battle.report_id(g.state, e.battle, later, ILSE)
    body = (BodyField(label="Our losses", value="2 steps"),)
    g.add(
        [
            ev.DocumentIssued(
                document=DocumentView(
                    doc_id=doc_id,
                    kind=DocumentKind.REPORT,
                    author=entity("ilse"),
                    issued=later,
                    arrives=later,
                    channel=ChannelKind.CABLE,
                    title="Battle report",
                    body=body,
                    scope=private_to(ILSE),
                ),
                truth=DocumentTruth(doc_id=doc_id),
            )
        ]
    )
    state = g.state.model_copy(update={"in_world_date": later})
    (b,) = rs.seat_realism(state, ILSE, set(), set(), None, ended_battles=[e])["battles"]
    assert [r["on"] for r in b["rounds"]] == [
        day(12).isoformat(),
        day(13).isoformat(),
        day(14).isoformat(),
    ]


def test_a_reply_of_none_is_kept_and_not_computed_again() -> None:
    service = Service()
    calls: list[int] = []

    def nothing() -> None:
        calls.append(1)

    service.ask("k", None, nothing)
    service.ask("k", None, nothing)
    assert len(calls) == 1
    service.close()


def test_the_truth_takes_the_enemys_own_supply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = fought_out(tmp_path)
    sudland = {piece(g.state, "sudland_levy").feature_id}

    def supplied(state: State, pieces: Any) -> bool:
        return not {f.feature_id for f in pieces} & sudland

    monkeypatch.setattr(battle, "_supplied", supplied)
    seen_p, truth = odds.closing_pictures(replay(g.log[: _opened_at(g)]), ILSE, entity(COAST))
    assert truth.enemy_supplied is False and seen_p.enemy_supplied is True


def _opened_at(g: Logged) -> int:
    return next(n for n, e in enumerate(g.log) if isinstance(e.payload, ev.BattleOpened)) + 1


def test_the_rate_limit_is_checked_before_the_picture_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = Service(per_minute=1)
    state = seen(start(tmp_path), report())
    odds.reply(service, state, ILSE, {"force": "norra_levy", "to": COAST})
    built: list[int] = []
    monkeypatch.setattr(odds, "picture", lambda *a: built.append(1))
    out = odds.reply(service, state, ILSE, {"force": "nobody", "to": COAST})
    assert out["refused"] is True and out["reply"] == odds.LIMITED and built == []


# --- the seat fixture ---------------------------------------------------------------------


def test_the_seat_fixture_carries_an_ended_battle_with_its_closing_odds(tmp_path: Path) -> None:
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["battles_ended"]
    g = fought_out(tmp_path)
    state = at_wake(g, 2)
    ended = odds.ended(Service(), state, ILSE, g.log)
    block = rs.seat_realism(state, ILSE, set(), set(), None, ended_battles=ended)
    assert fixture == block["battles"]
    assert fixture[0]["closing"]["truly"]["known"] is True


def test_the_seat_fixture_carries_an_odds_reply_in_the_api_shape(tmp_path: Path) -> None:
    """Under ``spread``: the client's fixture never carries the word for chances."""
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["spread"]
    assert fixture == toward(seen(start(tmp_path), report()))
    assert set(fixture) == set(api.OddsReply.__annotations__)
    assert set(fixture["terrain"]) == set(api.OddsTerrain.__annotations__)
    assert set(fixture["shares"]) == set(api.OddsShares.__annotations__)
    assert set(fixture["by_strength"][0]) == set(api.OddsAtStrength.__annotations__)
