"""Answering another seat's request (ANS).

A request at a leader another human seat holds reaches that seat's agenda as an item
of kind "Request": who asks, the words and terms, and the due day. The holder answers
it with ``/api/realism/answer`` ``{item, accept}``. The answer is recorded as an
``influence_decided`` at once; its effect lands when the wake closes, never at once.
Like any order, an answer is sealed once the seat has committed the wake.
"""

from datetime import date
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import EntityId
from revisionist.core.realism import effect as rx
from revisionist.core.realism import process
from revisionist.core.realism.agenda import Ask
from revisionist.core.visibility import Visibility
from revisionist.engine import realism_tick
from revisionist.engine.web import server
from tests.test_web import Client, web  # noqa: F401
from tests.test_web_realism import Realism, post, realism_of
from tests.test_web_wake import duo, log_of, seat_of, state_of  # noqa: F401

DESTROYERS = "Ask the Prime Minister to take fifty old destroyers"


def _file(game: Realism, words: str = DESTROYERS) -> None:
    """Roosevelt asks Churchill, typed so the answer has an effect to land."""
    churchill = EntityId(game.ids["churchill"])
    gift = rx.Allocate(recipient=churchill, what="old destroyers", amount=50, unit="ships")
    store = game.web.app.open()
    try:
        realism_tick.commit_order(
            store,
            game.campaign,
            seat_of(game, "roosevelt"),
            [Ask(ask=words, target=churchill, effect=gift)],
        )
    finally:
        store.close()


def _requests(client: Client) -> list[dict[str, Any]]:
    return [i for i in realism_of(client)["agenda"]["items"] if i["kind"] == "Request"]


def _close(ada: Client, bea: Client) -> None:
    for who in (ada, bea):
        status, out = post(who, "commit")
        assert status == 200 and not out["refused"], out


def _until_asked(game: Realism, ada: Client, bea: Client) -> dict[str, Any]:
    """Close wakes until the request is on Churchill's agenda; that item."""
    for _ in range(6):
        found = _requests(bea)
        if found:
            (item,) = found
            return item
        _close(ada, bea)
    raise AssertionError("the request never reached the holder's agenda")


def _request(game: Realism) -> tuple[rx.RoutedOrder, int]:
    for order in state_of(game).routed.values():
        for i, part in enumerate(order.parts):
            if part.ask == DESTROYERS:
                return order, i
    raise AssertionError("no request")


def _decided(game: Realism, order: rx.RoutedOrder) -> list[ev.Event]:
    return [
        e
        for e in log_of(game)
        if isinstance(e.payload, ev.InfluenceDecided) and e.payload.order_id == order.order_id
    ]


def _landed(game: Realism, order: rx.RoutedOrder, i: int) -> list[ev.EffectsApplied]:
    return [
        e.payload
        for e in log_of(game)
        if isinstance(e.payload, ev.EffectsApplied)
        and e.payload.order_id == order.order_id
        and e.payload.part == i
    ]


def _day(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def test_the_request_is_on_the_holders_agenda_with_its_terms_and_due_day(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bea = duo
    _file(game)
    item = _until_asked(game, ada, bea)
    state = state_of(game)
    order, i = _request(game)
    due = process.request_due(state, order, i)
    assert due is not None
    assert item["issuer"] == "Franklin D. Roosevelt"
    assert DESTROYERS in item["text"] and "Allocate old destroyers" in item["text"]
    assert item["deadline"] == _day(due)
    assert item["options"] == [] and item["plan"] == [] and item["cause"] is None
    assert str(order.order_id) not in item["id"]
    assert _requests(ada) == []


def test_an_answer_is_recorded_at_once_and_lands_at_the_close(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bea = duo
    _file(game)
    item = _until_asked(game, ada, bea)
    order, i = _request(game)
    today = state_of(game).in_world_date
    status, out = post(bea, "answer", item=item["id"], accept=True)
    assert status == 200 and not out["refused"], out
    assert set(out) == {"reply", "refused"}
    (decided,) = _decided(game, order)
    assert isinstance(decided.payload, ev.InfluenceDecided)
    assert (decided.payload.part, decided.payload.accepted, decided.payload.on) == (
        i,
        True,
        today,
    )
    assert decided.payload.reason == "Winston Churchill agreed to what you asked."
    assert decided.scope.visibility is Visibility.PRIVATE
    assert decided.scope.known_by == {seat_of(game, "roosevelt"), seat_of(game, "churchill")}
    assert _requests(bea) == []
    assert _landed(game, order, i) == [], "the answer took effect before the close"
    _close(ada, bea)
    (landed,) = _landed(game, order, i)
    assert today is not None and landed.on > today
    assert len(_decided(game, order)) == 1, "the card decided again"


def test_a_declined_request_is_not_decided_again_by_the_card(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bea = duo
    _file(game)
    item = _until_asked(game, ada, bea)
    order, _ = _request(game)
    status, out = post(bea, "answer", item=item["id"], accept=False)
    assert status == 200 and not out["refused"], out
    for _ in range(3):
        _close(ada, bea)
    (decided,) = _decided(game, order)
    assert isinstance(decided.payload, ev.InfluenceDecided)
    assert decided.payload.accepted is False
    assert decided.payload.reason == "Winston Churchill would not be moved."


def test_an_answer_is_sealed_once_the_seat_has_committed(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bea = duo
    _file(game)
    item = _until_asked(game, ada, bea)
    order, _ = _request(game)
    status, out = post(bea, "commit")
    assert status == 200 and not out["refused"], out
    _, sealed = post(bea, "answer", item=item["id"], accept=True)
    assert sealed == {"reply": server.SEALED, "refused": True}
    assert _decided(game, order) == []


def test_only_the_holder_answers_and_only_once(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bea = duo
    _file(game)
    item = _until_asked(game, ada, bea)
    order, _ = _request(game)
    _, by_issuer = post(ada, "answer", item=item["id"], accept=True)
    assert by_issuer["refused"], by_issuer
    _, unknown = post(bea, "answer", item="no-such-item", accept=True)
    assert unknown["refused"], unknown
    status, loose = post(bea, "answer", item=item["id"], accept="yes")
    assert status == 400 or loose["refused"], loose
    assert _decided(game, order) == []
    _, first = post(bea, "answer", item=item["id"], accept=True)
    assert not first["refused"], first
    _, again = post(bea, "answer", item=item["id"], accept=False)
    assert again["refused"], again
    assert len(_decided(game, order)) == 1


def test_the_holders_answer_reads_as_the_card_would_put_it() -> None:
    """The issuer reads the same words whether the holder answered or the card did."""
    assert process.answer_reason("Winston Churchill", True) == (
        "Winston Churchill agreed to what you asked."
    )
    assert process.answer_reason("Winston Churchill", False) == (
        "Winston Churchill would not be moved."
    )
