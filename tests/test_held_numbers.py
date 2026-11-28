"""A seat's held orders are numbered for that seat in that game alone.

The number a seat is shown for an order it holds, and withdraws by, counts its own held
orders only: orders other seats hold, and orders held in other games, never move it.
Same harness as ``tests/test_web_held_orders.py``.
"""

from typing import Any

from revisionist.core.ids import CampaignId, SeatId
from revisionist.engine.web import held
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_held_orders import BILL, duo, held_of  # noqa: F401
from tests.test_web_realism import Realism, post
from tests.test_web_wake import seat_of


def someone_else_holds(game: Realism, *, campaign: str | None = None) -> None:
    """An order held by another seat of this game, or by a seat of another game."""
    store = game.web.app.open()
    try:
        cid = CampaignId(campaign or game.campaign)
        other = seat_of(game, "churchill") if campaign is None else SeatId("seat-elsewhere")
        assert held.hold(store, cid, other, 0, "lever", {}, "Something else") is not None
    finally:
        store.close()


def hold_bill(client: Client) -> int:
    status, out = post(client, "lever", **BILL)
    assert status == 200 and out["reply"] == held.HELD, out
    return int(out["held"])


def ids(client: Client) -> list[Any]:
    return [x["id"] for x in held_of(client)]


def test_a_seats_held_orders_count_only_its_own(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, _ = duo
    assert not post(ada, "commit")[1]["refused"]
    someone_else_holds(game)
    someone_else_holds(game, campaign="another-game")
    assert hold_bill(ada) == 1
    someone_else_holds(game)
    someone_else_holds(game, campaign="another-game")
    assert hold_bill(ada) == 2
    assert ids(ada) == [1, 2]


def test_a_withdrawn_number_is_not_given_again(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    _, ada, _ = duo
    assert not post(ada, "commit")[1]["refused"]
    assert [hold_bill(ada) for _ in range(3)] == [1, 2, 3]
    _, out = post(ada, "withdraw", held_id=2)
    assert out == {"reply": "Withdrawn. It will not be filed.", "refused": False}
    assert ids(ada) == [1, 3]
    assert hold_bill(ada) == 4
    _, again = post(ada, "withdraw", held_id=2)
    assert again["refused"], again
    assert ids(ada) == [1, 3, 4]


def test_another_seat_withdraws_only_its_own_numbers(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bea = duo
    assert not post(ada, "commit")[1]["refused"]
    assert hold_bill(ada) == 1
    _, out = post(bea, "withdraw", held_id=1)
    assert out["refused"], out
    assert ids(ada) == [1]
    store = game.web.app.open()
    try:
        assert not held.drop(store, game.campaign, seat_of(game, "churchill"), 1)
        assert held.drop(store, game.campaign, seat_of(game, "roosevelt"), 1)
    finally:
        store.close()
    assert ids(ada) == []
