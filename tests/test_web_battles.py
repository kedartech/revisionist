"""Battles as the seat sees them (BTD).

The toy world of ``tests/test_battle_decisions.py``: Norra's levy steps into the Sudland
Coast on day 12, where Sudland's levy stands, and the battle opens with Norra attacking;
its first round is fought that day. Ilse sits for Norra, Tomas for Sudland. Each leader
commands "army" (moves and engagement for its own forces, ``test_battle_decisions_land``)
and has the field-order form that names the forces (``test_adjacency_moves.levers``).

The ``battles`` block lists each battle the seat's nation is a side of, from its own side
and its own papers; the ``battle`` and ``contingency`` actions file the decision as an
order; an undecided battle is a due matter at the open wake's close; ``db wake-report``
counts battles opened, rounds fought and battles ended per wake (its tests are in
``tests/test_wake_report.py``).
"""

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, SeatId
from revisionist.core.realism import battle, detect, kinds
from revisionist.core.realism.battle import Decision
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.detect import Confidence, Report, Source
from revisionist.core.realism.document import (
    BodyField,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.effect import (
    ContingencyKind,
    Engagement,
    MoveForce,
    Posture,
    SetEngagement,
)
from revisionist.core.realism.geography import FeatureKind, Sight
from revisionist.core.state import Rule, State, Wake
from revisionist.core.visibility import private_to
from revisionist.engine import notice, realism_tick, wake
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import agenda_api, held, server
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web.agenda_api import AT_CLOSE
from tests import test_adjacency_moves as adj
from tests.test_adjacency_moves import Logged, World, entity, piece, seat
from tests.test_battle_decisions import decide, fight, opened
from tests.test_battle_decisions_land import army
from tests.test_battles import COAST, OPENS, payloads
from tests.test_holders import Wakes
from tests.test_territory_model import CAMPAIGN
from tests.test_web import Web, web  # noqa: F401
from tests.test_web_realism import Realism

FIXTURES = Path(__file__).parents[1] / "web" / "test" / "fixtures"
ILSE, TOMAS, ADA = seat("ilse"), seat("tomas"), seat("ada")
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
GAME = "The toy war"


def ostmark(w: World) -> None:
    """A third power, Ostmark, at war with nobody, with Ada as its playable leader."""
    w["entities"] += [
        {"key": "ostmark", "kind": "polity", "name": "Ostmark"},
        {"key": "ada", "kind": "person", "name": "Ada Ost", "parent": "ostmark"},
    ]
    w["roster"].append(
        {"entity": "ada", "pitch": "The regent.", "reach": "Ostmark.", "composite": True}
    )
    w["cards"].append(
        {
            "person": "ada",
            "office": "Regent of Ostmark",
            "playable": True,
            "principals": ["ostmark"],
            "horizon_days": 14,
        }
    )


def game(tmp: Path, *changes: Any) -> Logged:
    """The coast's battle open after its first round, both leaders commanding their own."""
    return opened(tmp, adj.levers, army, *changes)


def at_wake(g: Logged, n: int) -> State:
    """The game with wake ``n`` open on the last day walked, as the state a payload is
    built from."""
    return g.state.model_copy(
        update={
            "wake": Wake(number=n, deadline=NOW + timedelta(hours=24)),
            "in_world_date": walked(g),
        }
    )


def walked(g: Logged) -> date:
    """The last day the game's day walk fought a round on."""
    rounds: list[ev.BattleRound] = payloads(g.log, ev.BattleRound)
    return max(r.on for r in rounds)


def battles(state: State, who: SeatId = ILSE) -> list[dict[str, Any]]:
    return list(rs.seat_realism(state, who, set(), set(), None)["battles"])


def one(state: State, who: SeatId = ILSE) -> dict[str, Any]:
    (found,) = battles(state, who)
    return found


def sighting(g: Logged, figure: int | None, on: date = OPENS) -> None:
    """A paper to Ilse placing Sudland's levy at Sudby, with its strength when given."""
    body = [
        BodyField(
            label="The Sudland Levy",
            value="Sudby",
            sight=Sight(kind=FeatureKind.PIECE, side=entity("sudland"), places=(entity("sudby"),)),
        )
    ]
    if figure is not None:
        body.append(BodyField(label="The Sudland Levy", value=figure, unit="strength"))
    doc_id = DocumentId(f"sighting-{figure}-{on.isoformat()}")
    g.add(
        [
            ev.DocumentIssued(
                document=DocumentView(
                    doc_id=doc_id,
                    kind=DocumentKind.REPORT,
                    author=entity("ilse"),
                    issued=on,
                    arrives=on,
                    channel=ChannelKind.CABLE,
                    title="Scouts at Sudby",
                    body=tuple(body),
                    scope=private_to(ILSE),
                ),
                truth=DocumentTruth(doc_id=doc_id),
            )
        ]
    )


def store_of(g: Logged) -> MemoryStore:
    """The game in a store with wake 0 open on the last day walked, for the order path."""
    g.add(
        [
            ev.DateAdvanced(to=walked(g)),
            ev.WakeOpened(wake=0, deadline=NOW + timedelta(hours=24), opened_at=NOW),
        ]
    )
    store = MemoryStore()
    store.append_all(g.log)
    return store


def file(store: MemoryStore, who: SeatId, action: str, **body: Any) -> str:
    """File ``action`` as the server does, through the ordinary order path."""
    asks, label = server._battle_asks(load_state(store, CAMPAIGN), who, action, body)
    realism_tick.commit_order(store, CAMPAIGN, who, asks)
    return label


def routed(store: MemoryStore, who: SeatId) -> list[Any]:
    state = load_state(store, CAMPAIGN)
    return [p.effect for o in state.routed.values() if o.issuer == who for p in o.parts]


# --- Rule 1: the battles block -----------------------------------------------------------


def test_the_block_lists_the_battle_with_its_area_day_sides_and_strength(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    b = fight(g)
    state = at_wake(g, 1)
    mine, theirs = one(state, ILSE), one(state, TOMAS)
    assert (mine["area"], mine["name"], mine["opened"]) == (
        COAST,
        "The Sudland Coast",
        OPENS.isoformat(),
    )
    assert (mine["side"], mine["enemy"]) == ("attacker", "Sudland")
    assert (theirs["side"], theirs["enemy"]) == ("defender", "Norra")
    assert mine["strength"] == b.attacker.brought - b.attacker.lost
    assert theirs["strength"] == b.defender.brought - b.defender.lost
    assert mine["decision"] is None and mine["decided"] is False and mine["held"] is False
    assert mine["decisions"] == ["press", "hold", "withdraw"]
    assert mine["contingencies"] == ["hold", "hold_fast", "fall_back", "withdraw_below"]
    assert mine["pieces"] == [
        {
            "force": "norra_levy",
            "name": "The Norra Levy",
            "strength": piece(g.state, "norra_levy").tier,
            "contingency": None,
        }
    ]


def test_each_round_is_the_seats_own_report_of_it(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.walk(OPENS + timedelta(days=1), OPENS + timedelta(days=1))
    rounds = payloads(g.log, ev.BattleRound)
    assert len(rounds) == 2
    state = at_wake(g, 1)
    for who, i in ((ILSE, 0), (TOMAS, 1)):
        assert one(state, who)["rounds"] == [
            {"on": r.on.isoformat(), "own_lost": r.lost[i], "enemy_lost": r.lost[1 - i]}
            for r in rounds
        ]


def test_a_seat_without_the_round_reports_sees_no_rounds(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = at_wake(g, 1)
    gone = {k: d for k, d in state.documents.items() if not d.view.title.startswith("Battle at")}
    assert one(state.model_copy(update={"documents": gone}))["rounds"] == []


def test_the_enemy_range_comes_from_the_seats_own_papers(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert one(at_wake(g, 1))["enemy_strength"] is None
    sighting(g, None, OPENS - timedelta(days=1))
    assert one(at_wake(g, 1))["enemy_strength"] == {"low": 1, "high": 5}
    sighting(g, 2)
    assert one(at_wake(g, 1))["enemy_strength"] == {"low": 2, "high": 2}
    assert one(at_wake(g, 1), TOMAS)["enemy_strength"] is None


def report(
    key: str,
    strength: tuple[int, int] | None,
    area: str = COAST,
    kind: str | None = None,
    seen: date = OPENS,
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


def reporting(state: State, *reports: Report) -> State:
    """``state`` with reports on and Norra's picture holding ``reports``."""
    picture = detect.Picture(delivered={r.key: r for r in reports})
    return state.model_copy(
        update={
            "rules": state.rules | {Rule.REPORTS},
            "reports": {**state.reports, entity("norra"): picture},
        }
    )


def test_with_reports_on_the_enemy_range_comes_from_the_seats_reports(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = reporting(at_wake(g, 1), report("r1", (2, 3)))
    assert one(state)["enemy_strength"] == {"low": 2, "high": 3}
    assert one(state, TOMAS)["enemy_strength"] is None


def test_with_reports_on_the_papers_sightings_are_not_read(tmp_path: Path) -> None:
    g = game(tmp_path)
    sighting(g, 2)
    assert one(at_wake(g, 1))["enemy_strength"] == {"low": 2, "high": 2}
    assert one(reporting(at_wake(g, 1)))["enemy_strength"] is None
    assert one(reporting(at_wake(g, 1), report("r1", (3, 4))))["enemy_strength"] == {
        "low": 3,
        "high": 4,
    }


def test_the_reported_range_sums_the_reports_in_the_area_and_its_domain(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    state = at_wake(g, 1)
    most = kinds.MAX_STRENGTH
    sheet = reporting(
        state,
        report("r1", (2, 3)),
        report("r2", None),
        report("r3", (4, 4), area="norra_plain"),
        report("r4", (1, 2), kind="galley"),
    )
    assert one(sheet)["enemy_strength"] == {"low": 3, "high": 3 + most}


def test_a_report_gone_stale_leaves_the_sheet_without_a_range(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = at_wake(g, 1)
    today = walked(g)
    old = today - timedelta(days=detect.STALE_DAYS + 1)
    assert one(reporting(state, report("r1", (2, 3), seen=old)))["enemy_strength"] is None


def test_with_reports_on_the_range_reads_no_truth(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = reporting(at_wake(g, 1), report("r1", (2, 3)))
    b = fight(g)
    truer = b.model_copy(
        update={"defender": b.defender.model_copy(update={"brought": b.defender.brought + 3})}
    )
    levy = piece(state, "sudland_levy")
    changed = state.model_copy(
        update={
            "battles": {**state.battles, entity(COAST): truer},
            "features": {
                **state.features,
                levy.feature_id: levy.model_copy(update={"tier": 5 if levy.tier != 5 else 1}),
            },
        }
    )
    assert one(changed)["enemy_strength"] == one(state)["enemy_strength"] == {"low": 2, "high": 3}


def test_the_decision_in_force_is_the_sides_stored_decision(tmp_path: Path) -> None:
    g = game(tmp_path)
    decide(g, "norra_levy", Posture.HOLD)
    assert fight(g).attacker.decision is Decision.HOLD
    given = fight(g).attacker.decided_wake
    assert given is not None
    now = one(at_wake(g, given))
    assert (now["decision"], now["decided"], now["decisions"]) == ("hold", True, [])
    later = one(at_wake(g, given + 1))
    assert (later["decision"], later["decided"]) == ("hold", False)
    assert later["decisions"] == ["press", "hold", "withdraw"]
    assert one(at_wake(g, given + 1), TOMAS)["decision"] is None


def test_between_wakes_no_decision_is_open(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert g.state.wake is None
    assert one(g.state)["decisions"] == []


def test_a_held_decision_marks_only_the_seats_own_battle(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = at_wake(g, 1)
    held_view = rs.seat_realism(state, ILSE, set(), set(), None, held_battles={COAST})
    assert [(b["held"], b["decided"], b["decisions"]) for b in held_view["battles"]] == [
        (True, True, [])
    ]
    assert one(state, TOMAS)["held"] is False


def test_the_battles_block_is_in_the_snapshot_shape(tmp_path: Path) -> None:
    g = game(tmp_path)
    sighting(g, 2)
    (b,) = battles(at_wake(g, 1))
    assert set(b) == set(api.BattleView.__annotations__)
    assert set(b["rounds"][0]) == set(api.BattleRoundLine.__annotations__)
    assert set(b["pieces"][0]) == set(api.BattlePiece.__annotations__)
    assert set(b["enemy_strength"]) == set(api.StrengthRange.__annotations__)


def fixture_state(tmp: Path) -> State:
    """The game the seat fixture's ``battles`` is Ilse's block of: the coast's battle after
    two rounds, a paper placing Sudland's levy at strength 2, and wake 1 open."""
    g = game(tmp)
    g.walk(OPENS + timedelta(days=1), OPENS + timedelta(days=1))
    sighting(g, 2, OPENS + timedelta(days=1))
    return at_wake(g, 1)


def test_the_seat_fixture_carries_the_battles_block(tmp_path: Path) -> None:
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["battles"]
    assert fixture == battles(fixture_state(tmp_path))
    assert fixture and fixture[0]["rounds"] and fixture[0]["pieces"]


# --- Rule 2: the battle and contingency actions file an order ----------------------------


def test_the_battle_action_files_the_decision_as_an_order(tmp_path: Path) -> None:
    g = game(tmp_path)
    store = store_of(g)
    levy = piece(g.state, "norra_levy").feature_id
    assert file(store, ILSE, "battle", area=COAST, decision="hold").endswith("hold")
    assert routed(store, ILSE) == [MoveForce(force=levy, posture=Posture.HOLD)]


@pytest.mark.parametrize(
    ("decision", "to", "want"),
    [
        ("press", None, {"posture": Posture.ATTACK, "to": None}),
        ("withdraw", None, {"posture": Posture.WITHDRAW, "to": None}),
        ("withdraw", "norra_hills", {"posture": Posture.WITHDRAW, "to": "norra_hills"}),
    ],
)
def test_each_decision_is_the_order_a_seat_would_type(
    tmp_path: Path, decision: str, to: str | None, want: dict[str, Any]
) -> None:
    g = game(tmp_path)
    store = store_of(g)
    body = {"area": COAST, "decision": decision} | ({"to": to} if to else {})
    file(store, ILSE, "battle", **body)
    (effect,) = routed(store, ILSE)
    assert isinstance(effect, MoveForce)
    assert effect.posture is want["posture"]
    assert effect.to == (entity(want["to"]) if want["to"] else None)


def test_a_sent_decision_closes_the_battle_for_the_wake(tmp_path: Path) -> None:
    g = game(tmp_path)
    store = store_of(g)
    file(store, ILSE, "battle", area=COAST, decision="press")
    state = load_state(store, CAMPAIGN)
    mine = one(state)
    assert (mine["decided"], mine["decisions"], mine["decision"]) == (True, [], None)
    with pytest.raises(ValueError, match="already given"):
        file(store, ILSE, "battle", area=COAST, decision="hold")


def test_the_battle_action_refuses_a_battle_the_seats_nation_is_not_in(tmp_path: Path) -> None:
    g = game(tmp_path, ostmark)
    g.add([ev.CharacterClaimed(seat_id=ADA, entity_id=entity("ada"))])
    store = store_of(g)
    with pytest.raises(ValueError, match="no battle"):
        file(store, ADA, "battle", area=COAST, decision="press")
    with pytest.raises(ValueError, match="no battle"):
        file(store, ILSE, "battle", area="isle", decision="press")
    with pytest.raises(ValueError, match="decision is one of"):
        file(store, ILSE, "battle", area=COAST, decision="charge")


def test_the_contingency_action_files_an_engagement_that_keeps_the_rule(tmp_path: Path) -> None:
    g = game(tmp_path)
    store = store_of(g)
    levy = piece(g.state, "norra_levy")
    file(store, ILSE, "contingency", force="norra_levy", kind="withdraw_below", below=2)
    (effect,) = routed(store, ILSE)
    assert isinstance(effect, SetEngagement)
    assert effect.force == levy.feature_id
    assert effect.rule is (levy.engagement or Engagement.DEFEND)
    assert effect.contingency is not None
    assert (effect.contingency.kind, effect.contingency.below) == (
        ContingencyKind.WITHDRAW_BELOW,
        2,
    )
    with pytest.raises(ValueError, match="not yours"):
        file(store, ILSE, "contingency", force="sudland_levy", kind="hold")


def test_both_actions_are_held_after_a_commit_and_filed_as_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert {"battle", "contingency"} <= server.SEALED_BY_COMMIT
    calls: list[Any] = []
    monkeypatch.setattr(
        realism_tick, "commit_order", lambda _s, _c, who, asks: calls.append((who, asks))
    )
    effect = MoveForce(force=piece_id(), posture=Posture.HOLD)
    args = {"asks": [{"ask": "hold", "effect": effect.model_dump(mode="json")}], "area": COAST}
    for action in ("battle", "contingency"):
        assert held.file_one(MemoryStore(), CAMPAIGN, ILSE, action, args) is None
    assert [(who, [a.effect for a in asks]) for who, asks in calls] == [
        (ILSE, [effect]),
        (ILSE, [effect]),
    ]


def piece_id() -> Any:
    from revisionist.core.ids import FeatureId

    return FeatureId("f1")


def test_a_held_battle_keeps_its_area_for_the_seats_own_payload(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = at_wake(g, 1)
    args, label = server._held_args(
        None,  # type: ignore[arg-type]
        state,
        ILSE,
        "battle",
        {"area": COAST, "decision": "hold"},
        None,
    )
    assert args["area"] == COAST and label == "The battle at The Sudland Coast: hold"
    assert [a["effect"]["posture"] for a in args["asks"]] == ["hold"]


def test_the_held_battles_are_read_from_the_seats_own_held_rows(
    web: Web,  # noqa: F811
) -> None:
    game = Realism(web)
    store = web.app.open()
    try:
        cid = game.campaign
        battle_args = {"asks": [], "area": COAST}
        held.hold(store, cid, ILSE, 1, "battle", battle_args, "The battle: hold")
        held.hold(store, cid, ILSE, 1, "contingency", {"asks": []}, "A contingency")
        held.hold(store, cid, TOMAS, 1, "battle", battle_args | {"area": "isle"}, "Another")
        assert held.held_battles(store, cid, ILSE) == {COAST}
        assert held.held_battles(store, cid, TOMAS) == {"isle"}
        assert held.held_battles(store, cid, ADA) == set()
        assert held.file_held(store, cid, 2, filer=lambda *_: None) == 3
        assert held.held_battles(store, cid, ILSE) == set(), "filed rows are no longer held"
    finally:
        store.close()


# --- Rule 3: an undecided battle is due at the open wake's close -------------------------


def test_an_undecided_battle_is_due_to_both_sides_at_the_close(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = at_wake(g, 1)
    subject = battle.news_id(state, fight(g), "opened")
    for who in (ILSE, TOMAS):
        assert [m for m in agenda_api.due_matters(state, who) if m.kind == "battle"] == [
            agenda_api.DueMatter(
                "battle",
                subject,
                "The battle at The Sudland Coast awaits your decision",
                None,
                AT_CLOSE,
            )
        ]
    assert "battle" in agenda_api.DUE_KINDS


def test_a_battle_decided_this_wake_is_not_due(tmp_path: Path) -> None:
    g = game(tmp_path)
    decide(g, "norra_levy", Posture.HOLD)
    given = fight(g).attacker.decided_wake
    assert given is not None
    kinds = [m.kind for m in agenda_api.due_matters(at_wake(g, given), ILSE)]
    assert "battle" not in kinds
    assert "battle" in [m.kind for m in agenda_api.due_matters(at_wake(g, given + 1), ILSE)]


def test_a_decision_on_its_way_takes_the_battle_off_the_list(tmp_path: Path) -> None:
    g = game(tmp_path)
    store = store_of(g)
    file(store, ILSE, "battle", area=COAST, decision="withdraw")
    state = load_state(store, CAMPAIGN)
    assert "battle" not in [m.kind for m in agenda_api.due_matters(state, ILSE)]
    assert "battle" in [m.kind for m in agenda_api.due_matters(state, TOMAS)]


def test_no_battle_is_due_between_wakes(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert g.state.wake is None
    assert agenda_api.due_matters(g.state, ILSE) == []


def test_the_notice_lists_the_battle_due(tmp_path: Path) -> None:
    said = notice.compose(at_wake(game(tmp_path), 1), ILSE, None, GAME)[1]
    assert (
        "- The battle at The Sudland Coast awaits your decision. Due at this wake's close." in said
    )


def _ilse_notice(tmp: Path, tomas_present: bool, ilse_holds: bool = False) -> tuple[str, str]:
    """Ilse's notice for a wake opened with the battle undecided, with Tomas at the table
    (his papers read and his Done pressed) or away; and Tomas's own notice. With
    ``ilse_holds``, Ilse's decision given after her commit is filed as the next wake opens,
    as ``held.file_held`` files it, before the notices are composed."""
    w = Wakes(game(tmp))
    wake.open_wake(w.store, CAMPAIGN, NOW)
    if tomas_present:
        for d in w.state.documents.values():
            if d.view.scope.visible_to(TOMAS):
                realism_tick.mark_read(w.store, CAMPAIGN, TOMAS, d.view.doc_id)
        assert wake.commit(w.store, CAMPAIGN, TOMAS, NOW)
    if ilse_holds:
        asks, _ = server._battle_asks(w.state, ILSE, "battle", {"area": COAST, "decision": "hold"})
        realism_tick.commit_order(w.store, CAMPAIGN, ILSE, asks)
    state = w.state
    return notice.compose(state, ILSE, None, GAME)[1], notice.compose(state, TOMAS, None, GAME)[1]


def test_the_battle_notice_reads_the_same_with_the_other_side_present_or_away(
    tmp_path: Path,
) -> None:
    (tmp_path / "present").mkdir()
    (tmp_path / "away").mkdir()
    present = _ilse_notice(tmp_path / "present", tomas_present=True)
    away = _ilse_notice(tmp_path / "away", tomas_present=False)
    assert present[0] == away[0]
    assert "The battle at The Sudland Coast awaits your decision" in present[0]
    print(present[0])


def test_a_held_decision_is_in_no_notice(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    (tmp_path / "held").mkdir()
    plain = _ilse_notice(tmp_path / "plain", tomas_present=False)
    given = _ilse_notice(tmp_path / "held", tomas_present=False, ilse_holds=True)
    assert "The battle at The Sudland Coast" not in given[0]
    for said in given:
        assert not re.search(r"\b(hold|press|withdraw)\b", said.lower())
    assert given[1] == plain[1], "the other side's notice does not change"
    print(given[0])


def test_another_seats_payload_does_not_show_the_decision_sent(tmp_path: Path) -> None:
    g = game(tmp_path)
    store = store_of(g)
    before = load_state(store, CAMPAIGN)
    file(store, ILSE, "battle", area=COAST, decision="press")
    after = load_state(store, CAMPAIGN)
    assert one(before, TOMAS) == one(after, TOMAS)
    assert agenda_api.due_matters(before, TOMAS) == agenda_api.due_matters(after, TOMAS)


# --- Rule 4: a battle the seat's nation is not in is only news ---------------------------


def test_a_battle_the_seats_nation_is_not_in_is_not_listed(tmp_path: Path) -> None:
    g = game(tmp_path, ostmark)
    g.add([ev.CharacterClaimed(seat_id=ADA, entity_id=entity("ada"))])
    state = at_wake(g, 1)
    assert battles(state, ADA) == []
    assert [m for m in agenda_api.due_matters(state, ADA) if m.kind == "battle"] == []
    assert battle.news_id(state, fight(g), "opened") in state.news, "it is news"


def test_a_battle_one_of_the_nations_pieces_fights_in_is_listed(tmp_path: Path) -> None:
    g = game(tmp_path, ostmark, ostmark_levy_piece)
    g.add([ev.CharacterClaimed(seat_id=ADA, entity_id=entity("ada"))])
    b = fight(g)
    guard = piece(g.state, "ostmark_levy").feature_id
    joined = b.attacker.model_copy(update={"pieces": (*b.attacker.pieces, guard)})
    state = at_wake(g, 1).model_copy(
        update={"battles": {entity(COAST): b.model_copy(update={"attacker": joined})}}
    )
    (seen,) = battles(state, ADA)
    assert (seen["side"], seen["enemy"], seen["decisions"]) == ("attacker", "Sudland", [])


def ostmark_levy_piece(w: World) -> None:
    """An Ostmark piece at Norrhavn."""
    w["features"].append(
        {
            "key": "ostmark_levy",
            "kind": "piece",
            "piece": "levy",
            "name": "The Ostmark Guard",
            "side": "ostmark",
            "places": ["norrhavn"],
            "tier": 2,
            "source": "toy",
        }
    )


# --- Accept: fog ------------------------------------------------------------------------


def _payloads(state: State, who: SeatId) -> str:
    """Everything a seat is sent about battles: its block, its due matters, its notice."""
    block = battles(state, who)
    due = [m.__dict__ for m in agenda_api.due_matters(state, who)]
    said = notice.compose(state, who, None, GAME)[1]
    return json.dumps([block, due, said], sort_keys=True, default=str)


def test_no_payload_carries_the_enemys_true_strength_a_draw_or_its_decision(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    sighting(g, 2)
    state = at_wake(g, 1)
    b = fight(g)
    truer = b.model_copy(
        update={
            "defender": b.defender.model_copy(
                update={
                    "brought": b.defender.brought + 3,
                    "lost": b.defender.lost + 1,
                    "decision": Decision.PRESS,
                    "decided_wake": 1,
                }
            )
        }
    )
    levy = piece(state, "sudland_levy")
    changed = state.model_copy(
        update={
            "battles": {**state.battles, entity(COAST): truer},
            "features": {
                **state.features,
                levy.feature_id: levy.model_copy(update={"tier": 5 if levy.tier != 5 else 1}),
            },
        }
    )
    assert _payloads(state, ILSE) == _payloads(changed, ILSE)
    for who in (ILSE, TOMAS):
        sent = _payloads(state, who)
        assert '"draws"' not in sent and '"scores"' not in sent
    norra = b.attacker.model_copy(update={"decision": Decision.WITHDRAW, "decided_wake": 1})
    withdrawn = state.model_copy(
        update={
            "battles": {**state.battles, entity(COAST): b.model_copy(update={"attacker": norra})}
        }
    )
    assert one(withdrawn, TOMAS) == one(state, TOMAS)
