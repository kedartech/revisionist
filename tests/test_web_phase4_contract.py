"""The Phase 4 seams: every new route answers in its declared shape, the fixture matches
the API's shapes, and an ended game keeps its seats. Same harness as ``tests/test_web.py``.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, is_typeddict

import pytest

from revisionist.engine.web import realism_api as api
from revisionist.engine.web.accounts import WebSeats
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of

FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
DATE = "1941-12-07"


@pytest.fixture
def solo(web: Web) -> Iterator[tuple[Realism, Client]]:  # noqa: F811
    game = Realism(web, world="engine-v2-slice-1941")
    client = game.seat("ada", "roosevelt")
    make_host(game, client)
    game.open_play()
    game.first_tick()
    yield game, client


def _in_game(client: Client, action: str, /, **body: Any) -> dict[str, Any]:
    status, out = client.call(f"/api/game/{action}", body)
    assert status == 200, out
    return dict(out)


def _new(client: Client, action: str, /, **body: Any) -> dict[str, Any]:
    status, out = client.call(f"/api/new/{action}", body)
    assert status == 200, out
    return dict(out)


def _seat_row(game: Realism) -> list[tuple[Any, ...]]:
    store = game.web.app.open()
    try:
        return store.conn.execute(
            "SELECT finished_at FROM web_seats WHERE campaign_id = %s", (game.campaign,)
        ).fetchall()
    finally:
        store.close()


def _same_shape(example: Any, shape: Any) -> None:
    """Every key the TypedDict declares, recursively through its nested shapes."""
    assert set(example) == set(shape.__annotations__), shape
    for key, kind in shape.__annotations__.items():
        args = getattr(kind, "__args__", ())
        if args and is_typeddict(args[0]):
            assert example[key], f"{shape.__name__}.{key} needs an example"
            for item in example[key]:
                _same_shape(item, args[0])


@pytest.mark.parametrize(
    ("key", "shape"),
    [
        ("wake", api.WakeHeader),
        ("agenda", api.AgendaBlock),
        ("reach", api.ReachGroups),
        ("proposal", api.OrderProposal),
        ("reveal", api.Reveal),
    ],
)
def test_the_web_fixture_has_the_api_shape(key: str, shape: Any) -> None:
    _same_shape(json.loads(FIXTURE.read_text())[key], shape)


@pytest.mark.parametrize(
    ("key", "shape"),
    [
        ("results", api.OrderResult),
        ("timeline", api.TimelinePoint),
        ("figures", api.FigureGroup),
    ],
)
def test_the_web_fixture_lists_have_the_api_shape(key: str, shape: Any) -> None:
    examples = json.loads(FIXTURE.read_text())[key]
    assert examples
    for example in examples:
        _same_shape(example, shape)


def test_the_seat_block_carries_the_stub_shapes(solo: tuple[Realism, Client]) -> None:
    _, ada = solo
    block = realism_of(ada)
    assert set(block["wake"]) == set(api.WakeHeader.__annotations__)
    assert block["wake"]["is_host"] is True
    assert set(block["agenda"]) == set(api.AgendaBlock.__annotations__)
    assert block["results"] == []
    assert set(block["reach"]) == set(api.ReachGroups.__annotations__)
    assert block["style"] == "free"


@pytest.mark.parametrize(
    ("action", "body"),
    [
        ("commit", {}),
        ("close", {}),
        ("style", {"style": "guided"}),
        ("option", {"pick": "p1"}),
        ("file", {}),
    ],
)
def test_each_seat_action_answers_with_a_reply(
    solo: tuple[Realism, Client], action: str, body: dict[str, Any]
) -> None:
    _, ada = solo
    status, out = post(ada, action, **body)
    assert status == 200, out
    assert set(out) == set(api.Reply.__annotations__)


def test_an_order_is_read_into_a_proposal(solo: tuple[Realism, Client]) -> None:
    _, ada = solo
    status, out = post(ada, "order", text="Move the escorts to Iceland.")
    assert status == 200, out
    assert set(out["proposal"]) == set(api.OrderProposal.__annotations__)
    assert out["proposal"]["text"] == "Move the escorts to Iceland."


def test_advance_still_moves_the_calendar(solo: tuple[Realism, Client]) -> None:
    _, ada = solo
    status, out = post(ada, "advance")
    assert status == 200 and not out["refused"], out
    assert out["reply"].startswith("The calendar moves")


def test_the_host_sets_the_wake_hours(solo: tuple[Realism, Client]) -> None:
    _, ada = solo
    assert set(_in_game(ada, "wake-hours", hours=24)) == set(api.Reply.__annotations__)
    assert _in_game(ada, "wake-hours", hours="soon")["refused"]


class _HeldPower:
    """Answers the figure-list call with two people; no model is called."""

    def call(self, request: Any) -> Any:
        from revisionist.engine.llm import Reply

        people = [
            {"name": "Ernest King", "title": "Admiral", "side": "United States", "power": "Navy"},
            {"name": "Erich Raeder", "title": "Grand Admiral", "side": "Germany", "power": "Navy"},
        ]
        return Reply({"people": people}, request.model, 8, 4, 0, 0.0)


def test_a_new_game_answers_with_the_timeline_and_figures(web: Web) -> None:  # noqa: F811
    from revisionist.engine import timeline

    timeline._held.clear()
    web.app.transport_factory = _HeldPower
    client, _ = web.signed_up("ada")
    points = _new(client, "timeline")["timeline"]
    assert points and all(set(p) == set(api.TimelinePoint.__annotations__) for p in points)
    groups = _new(client, "figures", date=DATE)["figures"]
    assert groups and all(set(g) == set(api.FigureGroup.__annotations__) for g in groups)
    assert set(_new(client, "start", date=DATE)) == set(api.Reply.__annotations__)
    status, out = client.call("/api/new/figures", {"date": "soon"})
    assert status == 400, out


def test_the_slice_can_be_started_by_name(web: Web) -> None:  # noqa: F811
    client, _ = web.signed_up("ada")
    assert not _new(client, "ready", world="engine-v2-slice-1941")["refused"]
    assert set(_new(client, "style", style="beginner")) == set(api.Reply.__annotations__)


def test_ending_a_game_keeps_its_seats_as_finished(solo: tuple[Realism, Client]) -> None:
    game, ada = solo
    assert ada.me()["finished"] == []
    assert _seat_row(game) == [(None,)]
    assert not _in_game(ada, "end")["refused"]
    rows = _seat_row(game)
    assert len(rows) == 1 and rows[0][0] is not None
    me = ada.me()
    assert me["game"] is None
    assert me["finished"] == [{"id": game.campaign, "name": game.decl.name}]


def test_a_finished_seat_is_no_longer_held(solo: tuple[Realism, Client]) -> None:
    game, ada = solo
    _in_game(ada, "end")
    store = game.web.app.open()
    try:
        seats = WebSeats(store.conn)
        assert seats.for_campaign(game.campaign) == []
        assert seats.accounts(game.campaign) == {}
    finally:
        store.close()
    # free to start again: "already seated" reads only seats in play
    assert not _new(ada, "ready", world="autumn-1941")["refused"]
    assert len(ada.me()["finished"]) == 1
    assert ada.me()["game"] is not None


def test_the_reveal_opens_only_for_an_ended_game_the_account_held(
    solo: tuple[Realism, Client],
) -> None:
    game, ada = solo
    assert _in_game(ada, "reveal", game=game.campaign)["refused"]  # still in play
    _in_game(ada, "end")
    assert set(_in_game(ada, "reveal", game=game.campaign)) == set(api.Reveal.__annotations__)
    stranger, _ = game.web.signed_up("stranger")
    assert _in_game(stranger, "reveal", game=game.campaign)["refused"]
