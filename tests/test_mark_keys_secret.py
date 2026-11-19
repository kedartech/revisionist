"""Seat keys are deployment-secret MACs; stored core marks never leave as keys."""

import hashlib
import json
import re
import runpy
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist import cli
from revisionist.core.events import Event, PieceStepped
from revisionist.core.fold import replay, state_hash
from revisionist.core.ids import CampaignId, EntityId, SeatId
from revisionist.core.project import project
from revisionist.core.state import State
from revisionist.core.world_compile import object_id
from revisionist.engine.web import map_api, snapshot
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web.server import App
from tests import test_adjacency_moves as adj
from tests.test_web_theatres import seated, world

SECRET_ENV = "REVISIONIST_MARK_SECRET"
TEST_SECRET = "12" * 32
LEGACY = Path(__file__).parent / "fixtures" / "mark-keys-legacy.json"
CANNED = Path(__file__).parents[1] / "web" / "test" / "e2e" / "serve_canned.py"


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_ENV, TEST_SECRET)


def marks(state: State, seat: Any) -> dict[str, Any]:
    block = snapshot.checked(state, seat, rs.seat_realism(state, seat, set(), set(), None))
    return {m["name"]: m for m in block["map"]["marks"]}


def colleague_view(state: State, seat: Any) -> Any:
    """Another British seat with the same nation's reports, embodied by Eden."""
    view = project(state, seat)
    me = view.me.model_copy(
        update={
            "seat_id": SeatId("01ARZ3NDEKTSV4RRFFQ69G5FAW"),
            "embodies": EntityId(object_id(state.campaign_id, "entity", "eden")),
        }
    )
    return view.model_copy(update={"me": me})


def test_public_world_keys_cannot_recover_an_enemy_mark() -> None:
    decl = world()
    state, seat, _ = seated("roosevelt", decl)
    enemy = marks(state, seat)["U-boat arm"]
    assert enemy["piece"] is None and enemy["strength"] is None
    cid = state.campaign_id  # game.id, sent to every seat
    guesses = {
        "m"
        + hashlib.blake2b(
            "\x1f".join(
                (
                    cid,
                    "mark",
                    object_id(cid, "entity", nation.key),
                    object_id(cid, "feature", feature.key),
                )
            ).encode(),
            digest_size=8,
        ).hexdigest()
        for nation in decl.entities
        for feature in decl.features
    }
    assert enemy["key"] not in guesses
    assert re.fullmatch(r"m[0-9a-f]{32}", enemy["key"])


def test_keys_survive_days_reload_and_same_nation_but_need_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, seat, _ = seated("churchill", world())
    before = marks(state, seat)
    assert state.in_world_date is not None
    later = state.model_copy(update={"in_world_date": state.in_world_date + timedelta(days=1)})
    restored = State.model_validate_json(later.model_dump_json())
    colleague = rs.seat_map(colleague_view(state, seat), state=state)
    assert colleague is not None
    shared = {m["name"]: m for m in colleague["marks"]}
    foreign, foreign_seat, _ = seated("roosevelt", world())
    for name, mark in before.items():
        assert marks(restored, seat)[name]["key"] == mark["key"]
    common = set(before) & set(shared)
    assert common
    assert all(before[n]["key"] == shared[n]["key"] for n in common)
    common = set(before) & set(marks(foreign, foreign_seat))
    assert common
    assert all(before[n]["key"] != marks(foreign, foreign_seat)[n]["key"] for n in common)
    monkeypatch.setenv(SECRET_ENV, "34" * 32)
    assert all(marks(state, seat)[n]["key"] != m["key"] for n, m in before.items())


def test_label_only_marks_are_secret_and_shared_by_the_viewing_nation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, seat, _ = seated("churchill", world())
    colleague = rs.seat_map(colleague_view(state, seat))
    assert colleague is not None

    def labels(s: State, who: Any) -> dict[str, str]:
        out = rs.seat_map(project(s, who))
        assert out is not None
        return {m["name"]: m["key"] for m in out["marks"]}

    first = labels(state, seat)
    second = {m["name"]: m["key"] for m in colleague["marks"]}
    common = first.keys() & second.keys()
    assert common
    assert all(first[n] == second[n] for n in common)
    monkeypatch.setenv(SECRET_ENV, "34" * 32)
    assert all(labels(state, seat)[n] != k for n, k in first.items())


def test_mac_namespace_includes_campaign_and_viewing_nation() -> None:
    key = map_api.mark_key
    raw = "m0000000000000000"
    a, b = EntityId("viewer-a"), EntityId("viewer-b")
    campaign = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
    assert key(campaign, a, raw) != key(campaign, b, raw)
    assert key(campaign, a, raw) != key(CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAW"), a, raw)


def test_legacy_events_replay_unchanged_and_map_and_playback_share_protected_keys() -> None:
    frozen = json.loads(LEGACY.read_text())
    assert frozen["source_commit"] == "04c8310"
    events = [Event.model_validate(e) for e in frozen["events"]]
    state = replay(events)
    assert state_hash(state) == frozen["state_hash"]
    steps = [e.payload for e in events if isinstance(e.payload, PieceStepped)]
    assert len(steps) == 2
    mark = marks(state, adj.seat("ilse"))["The Norra Levy"]
    assert mark["key"] not in {s.mark for s in steps}
    assert mark["piece"]["key"] == mark["key"]
    assert {map_api.step_key(state.campaign_id, s) for s in steps} == {mark["key"]}
    assert state_hash(state) == frozen["state_hash"]
    assert [e.model_dump(mode="json") for e in events] == frozen["events"]


@pytest.mark.parametrize("value", [None, "", "not-a-secret", "12" * 31])
def test_server_refuses_missing_or_invalid_secret_before_serving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv(SECRET_ENV)
    else:
        monkeypatch.setenv(SECRET_ENV, value)
    with pytest.raises(ValueError, match=SECRET_ENV):
        App(
            "unused",
            tmp_path,
            transport_factory=lambda: pytest.fail("no model call"),
            clock=lambda: datetime.now(UTC),
            briefings=tmp_path,
            secure_cookie=True,
        )


def test_the_canned_smoke_server_starts_without_a_deployment_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CI's browser job starts the canned server with no secret in its environment."""
    started: list[bytes] = []
    monkeypatch.delenv(SECRET_ENV)
    monkeypatch.setattr(cli, "transport_factory", cli.transport_factory)
    monkeypatch.setattr(cli, "app", lambda: started.append(map_api.mark_secret()))
    monkeypatch.setattr(sys, "argv", ["serve_canned.py", "8794"])
    runpy.run_path(str(CANNED), run_name="__main__")
    assert len(started) == 1 and len(started[0]) == 32


def test_map_builder_also_refuses_a_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    state, seat, _ = seated("roosevelt", world())
    monkeypatch.delenv(SECRET_ENV)
    with pytest.raises(ValueError, match=SECRET_ENV):
        marks(state, seat)
