"""The odds name a report by the seat's own key, the one the map gives it.

A core report key is a digest of public inputs (``detect.report_key``: the campaign, the
nation and the piece's id, itself a digest of the campaign and the piece's world key), so
a seat holding one can tell which enemy piece a report is of. The map keys every report
again under the deployment's secret, by viewing nation (``map_api.protect_marks``); the
odds reply and the closing odds send that key and never the core one.

The toy games of ``tests/test_odds.py``: Ilse (Norra) asks the odds of sending her levy to
the Sudland Coast, or of a decision in the coast's open battle.
"""

from pathlib import Path
from typing import Any

import pytest

from revisionist.core.ids import FeatureId
from revisionist.core.realism import detect
from revisionist.core.realism.detect import Report
from revisionist.core.state import Rule, State
from revisionist.engine import odds
from revisionist.engine.odds import Service
from revisionist.engine.web import map_api
from revisionist.engine.web import realism_snapshot as rs
from tests.test_adjacency_moves import entity, piece
from tests.test_battles import COAST
from tests.test_odds import RUNS, fought_out, report, start
from tests.test_web_battles import ILSE, TOMAS, at_wake, game, walked

TOWARD = {"force": "norra_levy", "to": COAST}
IN_BATTLE = {"force": "norra_levy", "battle": COAST, "decision": "hold"}


@pytest.fixture(autouse=True)
def fewer_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(odds, "ODDS_RUNS", RUNS)
    monkeypatch.setattr(odds.spread, "__defaults__", (RUNS, odds.ODDS_DAYS))


def core_key(state: State, nation: str = "norra", of: str = "sudland_levy") -> str:
    """The core key a nation holds its report of an enemy piece by."""
    return detect.report_key(state, entity(nation), piece(state, of).feature_id)


def holding(state: State, nation: str, *reports: Report) -> State:
    """``state`` with reports on and ``nation``'s picture holding ``reports``."""
    picture = detect.Picture(delivered={r.key: r for r in reports})
    return state.model_copy(
        update={
            "rules": state.rules | {Rule.REPORTS},
            "reports": {**state.reports, entity(nation): picture},
        }
    )


def candidates(state: State) -> set[str]:
    """Every core report key a seat can compute from public inputs: each nation's key for
    each piece of the world, the piece ids derived from the campaign id and world keys."""
    return {
        detect.report_key(state, nation, FeatureId(f))
        for f in state.features
        for nation in state.entities
    }


def sent(state: State, seat: Any = ILSE, **body: str) -> list[str]:
    out = odds.reply(Service(), state, seat, body)
    assert out["refused"] is False, out
    return list(out["odds"]["reports"])


def opened_battle(tmp: Path) -> State:
    g = game(tmp)
    state = at_wake(g, 1)
    return holding(state, "norra", report(key=core_key(state), seen=walked(g)))


# --- Accept: the reviewer's attack ---------------------------------------------------------


def test_the_reviewers_attack_finds_no_enemy_piece_from_an_odds_reply(tmp_path: Path) -> None:
    """From the reply and the public campaign id, recompute the core key of each piece;
    none of them is in the reply."""
    state = start(tmp_path)
    state = holding(state, "norra", report(key=core_key(state)))
    keys = sent(state, **TOWARD)
    assert len(keys) == 1
    assert not set(keys) & candidates(state)


def test_the_attack_fails_on_an_open_battles_odds_too(tmp_path: Path) -> None:
    state = opened_battle(tmp_path)
    keys = sent(state, **IN_BATTLE)
    assert len(keys) == 1
    assert not set(keys) & candidates(state)


# --- Rule 1: every report reference is the seat's protected key ----------------------------


@pytest.mark.parametrize("body", [TOWARD, IN_BATTLE], ids=["toward", "in battle"])
def test_the_odds_name_a_report_by_the_key_map_api_gives_it(
    tmp_path: Path, body: dict[str, str]
) -> None:
    state = opened_battle(tmp_path) if "battle" in body else start(tmp_path)
    raw = core_key(state)
    state = holding(state, "norra", report(key=raw))
    want = map_api.mark_key(state.campaign_id, entity("norra"), raw)
    assert sent(state, **body) == [want]


def test_the_closing_odds_name_a_report_by_the_seats_key(tmp_path: Path) -> None:
    state = opened_battle(tmp_path)
    raw = core_key(state)
    closing = odds._closing(state, ILSE, entity(COAST))
    want = map_api.mark_key(state.campaign_id, entity("norra"), raw)
    assert closing["seen"]["reports"] == [want]
    assert closing["truly"]["reports"] == []


# --- Rule 2: one key for a report in the map and in the odds; one per nation ---------------


def test_a_report_has_the_same_key_in_the_map_and_in_the_odds(tmp_path: Path) -> None:
    state = start(tmp_path)
    state = holding(state, "norra", report(key=core_key(state)))
    on_map = [r["key"] for r in rs.seat_realism(state, ILSE, set(), set(), None)["map"]["reports"]]
    assert len(on_map) == 1
    assert sent(state, **TOWARD) == on_map


def test_two_nations_hold_one_report_key_under_different_keys(tmp_path: Path) -> None:
    """Norra's report at the coast and Sudland's at the plain share a core key here, so
    only the viewing nation in the key keeps them apart."""
    state = start(tmp_path)
    state = holding(state, "norra", report(key="r1"))
    state = holding(state, "sudland", report(key="r1", area="norra_plain"))
    norra = sent(state, ILSE, **TOWARD)
    sudland = sent(state, TOMAS, force="sudland_levy", to="norra_plain")
    assert len(norra) == len(sudland) == 1
    assert norra != sudland


# --- Rule 3: closing odds no client draws are not sent -------------------------------------


def test_closing_odds_are_not_computed_or_sent_while_no_client_draws_them(
    tmp_path: Path,
) -> None:
    assert odds.SEND_CLOSING is False
    g = fought_out(tmp_path)
    service = Service()
    (e,) = odds.ended(service, g.state, ILSE, g.log)
    assert e.closing is None
    assert service.computed == 0
    (b,) = rs.seat_realism(at_wake(g, 2), ILSE, set(), set(), None, ended_battles=[e])["battles"]
    assert b["ended"] is not None and b["closing"] is None
