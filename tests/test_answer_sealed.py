"""An answer stays with its holder until the card's due day (ANS, sealed).

The holder of a leader another seat asked something of answers it on their agenda.
Nothing the issuer can read moves while the wake is open: the answer is kept sealed to
the holder, who sees it and may change it until the due day. On the request's due
day the decision lands in the card's place, dated and signed as the card's would be, so
the issuer cannot tell whether the other player answered or was away.
"""

from datetime import date
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism import effect as rx
from revisionist.core.realism import process
from revisionist.core.realism.agenda import Ask
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine import catchup, realism_tick
from revisionist.engine.web import results
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_answer import _close, _decided, _file, _request, _until_asked
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import WORLD, begin, duo, log_of, seat_of, state_of  # noqa: F401


def _seen_by_issuer(game: Realism, ada: Client) -> tuple[dict[str, Any], list[Any]]:
    """Everything the issuer's seat is served: its realism block and its catch-up feed."""
    state = state_of(game)
    seat = seat_of(game, "roosevelt")
    fed = catchup.feed(state, log_of(game), seat, 0, state.wake.number if state.wake else 0)
    return realism_of(ada), [(f.wake, f.event.event_id) for f in fed]


def _request_items(client: Client) -> list[dict[str, Any]]:
    return [i for i in realism_of(client)["agenda"]["items"] if i["kind"] == "Request"]


def _accepted(game: Realism) -> list[bool | None]:
    """What the issuer's results say of its request to Churchill."""
    return [
        p["accepted"]
        for r in results.results(state_of(game), seat_of(game, "roosevelt"))
        for p in r["parts"]
        if p["route"] == "Your persuasion" and p["to"] == "Winston Churchill"
    ]


def _due(game: Realism) -> date:
    order, i = _request(game)
    due = process.request_due(state_of(game), order, i)
    assert due is not None
    return due


def _until_due(game: Realism, ada: Client, bea: Client, due: date) -> None:
    """Close wakes until the world reaches the due day, checking before each that the
    issuer holds no decision yet."""
    order, _ = _request(game)
    for _ in range(6):
        today = state_of(game).in_world_date
        assert today is not None
        if today >= due:
            return
        assert _decided(game, order) == [], f"decided before the due day, on {today}"
        assert _accepted(game) == [None], f"the issuer read an answer on {today}"
        _close(ada, bea)
    raise AssertionError("the due day never came")


def test_the_issuer_is_served_nothing_new_while_the_wake_is_open(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bea = duo
    _file(game)
    item = _until_asked(game, ada, bea)
    order, _ = _request(game)
    before = _seen_by_issuer(game, ada)
    status, out = post(bea, "answer", item=item["id"], accept=True)
    assert status == 200 and not out["refused"], out
    assert _seen_by_issuer(game, ada) == before, "the issuer saw the answer before the close"
    assert _decided(game, order) == [], "the decision was logged before the close"
    _until_due(game, ada, bea, _due(game))
    assert _accepted(game) == [True]


def test_the_holders_answer_lands_signed_and_dated_as_the_cards_would(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bea = duo
    _file(game)
    item = _until_asked(game, ada, bea)
    order, _ = _request(game)
    due = _due(game)
    status, out = post(bea, "answer", item=item["id"], accept=False)
    assert status == 200 and not out["refused"], out
    _until_due(game, ada, bea, due)
    (decided,) = _decided(game, order)
    assert isinstance(decided.payload, ev.InfluenceDecided)
    assert decided.actor is None, "the answer names the seat that gave it"
    assert decided.payload.on == due, "the answer is dated apart from the card's due day"
    assert decided.scope == private_to(seat_of(game, "roosevelt"))
    assert decided.payload.accepted is False
    assert decided.payload.reason == process.answer_reason("Winston Churchill", False)


def test_the_card_decides_on_the_same_day_with_the_same_envelope(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    """The twin of the test above with the holder away: what the card lands."""
    game, ada, bea = duo
    _file(game)
    _until_asked(game, ada, bea)
    order, _ = _request(game)
    due = _due(game)
    _until_due(game, ada, bea, due)
    (decided,) = _decided(game, order)
    assert isinstance(decided.payload, ev.InfluenceDecided)
    assert decided.actor is None
    assert decided.payload.on == due
    assert decided.scope == private_to(seat_of(game, "roosevelt"))


def test_the_fold_refuses_an_answer_to_a_decided_request(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bea = duo
    _file(game)
    _until_asked(game, ada, bea)
    order, i = _request(game)
    _until_due(game, ada, bea, _due(game))
    store = game.web.app.open()
    try:
        state = state_of(game)
        late = ev.RequestAnswered(order_id=order.order_id, part=i, accepted=True)
        with pytest.raises(FoldError, match="already decided"):
            realism_tick._append(store, state, late, seat_of(game, "churchill"))
    finally:
        store.close()
    assert not [e for e in log_of(game) if isinstance(e.payload, ev.RequestAnswered)]


def test_the_holder_sees_the_answer_and_may_change_it_until_the_due_day(
    duo: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bea = duo
    _file(game)
    item = _until_asked(game, ada, bea)
    order, _ = _request(game)
    due = _due(game)
    _, first = post(bea, "answer", item=item["id"], accept=True)
    assert not first["refused"], first
    (kept,) = _request_items(bea)
    assert kept["id"] == item["id"] and kept["cause"] == "You have agreed to it."
    _, second = post(bea, "answer", item=item["id"], accept=False)
    assert not second["refused"], second
    (kept,) = _request_items(bea)
    assert kept["cause"] == "You have declined it."
    assert _request_items(ada) == []
    _close(ada, bea)
    if state_of(game).in_world_date < due:  # type: ignore[operator]
        (kept,) = _request_items(bea)
        assert kept["cause"] == "You have declined it.", "the answer is kept into the next wake"
    _until_due(game, ada, bea, due)
    (decided,) = _decided(game, order)
    assert isinstance(decided.payload, ev.InfluenceDecided)
    assert decided.payload.accepted is False, "the last answer before Done stands"
    assert _request_items(bea) == []


WAR = "Ask Senator Wheeler to back the Home Fleet escorting convoys to Iceland"


@pytest.fixture
def senate(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    """Roosevelt and Wheeler, whose card keeps the country out of the war."""
    game = Realism(web, world=WORLD)
    ada = game.seat("ada", "roosevelt")
    bea = game.seat("bea", "wheeler")
    make_host(game, ada)
    begin(game)
    return game, ada, bea


def _file_war(game: Realism) -> None:
    wheeler = EntityId(game.ids["wheeler"])
    fleet = FeatureId(game.ids["home_fleet"])
    move = rx.MoveForce(force=fleet, posture=rx.Posture.ESCORT)
    store = game.web.app.open()
    try:
        realism_tick.commit_order(
            store,
            game.campaign,
            seat_of(game, "roosevelt"),
            [Ask(ask=WAR, target=wheeler, effect=move)],
        )
    finally:
        store.close()


def _war_request(state: State) -> tuple[rx.RoutedOrder, int]:
    for order in state.routed.values():
        for i, part in enumerate(order.parts):
            if part.ask == WAR:
                return order, i
    raise AssertionError("no request")


def _with_part(state: State, **update: Any) -> State:
    """``state`` with the request's part changed as ``update`` says."""
    order, i = _war_request(state)
    parts = list(order.parts)
    parts[i] = parts[i].model_copy(update=update)
    routed = {**state.routed, order.order_id: order.model_copy(update={"parts": tuple(parts)})}
    return state.model_copy(update={"routed": routed})


def _decline_on_the_due_day(state: State, held_answer: bool | None) -> str:
    """The reason the issuer is sent on the due day, with ``held_answer`` as kept."""
    state = _with_part(state, held_answer=held_answer)
    order, i = _war_request(state)
    due = process.request_due(state, order, i)
    assert due is not None
    (decided,) = [
        p
        for p in process.influence_due(state, due)
        if isinstance(p, ev.InfluenceDecided) and p.order_id == order.order_id
    ]
    assert decided.accepted is False
    return decided.reason


NEARER = "Burton K. Wheeler would not be moved: it would take the country nearer the war."


def test_a_holders_decline_against_the_cards_interest_reads_as_the_cards(
    senate: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = senate
    _file_war(game)
    item = _until_asked(game, ada, bea)
    state = state_of(game)
    order, i = _war_request(state)
    card_accepts, card_reason = process.decides(state, order, order.parts[i])
    assert (card_accepts, card_reason) == (False, NEARER), "the card declines it on war grounds"
    due = process.request_due(state, order, i)
    assert due is not None
    status, out = post(bea, "answer", item=item["id"], accept=False)
    assert status == 200 and not out["refused"], out
    for _ in range(6):
        if state_of(game).in_world_date >= due:  # type: ignore[operator]
            break
        _close(ada, bea)
    (decided,) = _decided(game, order)
    assert isinstance(decided.payload, ev.InfluenceDecided)
    assert decided.payload.accepted is False
    assert decided.payload.reason == card_reason


def test_the_card_and_the_holder_decline_an_irreversible_request_in_the_same_words(
    senate: tuple[Realism, Client, Client],
) -> None:
    """A card that would agree still declines an irreversible step for a held person;
    that decline reads as the holder's own decline of the same request."""
    game, ada, bea = senate
    _file_war(game)
    _until_asked(game, ada, bea)
    state = state_of(game)
    wheeler = EntityId(game.ids["wheeler"])
    roosevelt = EntityId(game.ids["roosevelt"])
    card = state.cards[wheeler]
    loyal = card.model_copy(update={"loyalty": 5, "principals": (*card.principals, roosevelt)})
    state = state.model_copy(update={"cards": {**state.cards, wheeler: loyal}})
    ships = rx.Allocate(recipient=wheeler, what="old destroyers", amount=50, unit="ships")
    state = _with_part(state, estimated=(ships,))
    order, i = _war_request(state)
    part = order.parts[i]
    assert process.decides(state, order, part)[0], "the card would agree"
    assert process.irreversible((ships,)), "but the step cannot be undone"
    by_card = _decline_on_the_due_day(state, None)
    assert by_card == _decline_on_the_due_day(state, False)
    assert by_card == NEARER
