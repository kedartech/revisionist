"""A held step is decided in the card's place on its due day.

When a seat decides a step its leader holds on another seat's order, the choice is
kept as a ``step_chosen`` sealed to that seat, and nothing the issuer reads moves. The
fold keeps it on the order (``Order.held_choice``), engine side; the issuer's view
never carries it. On the step's held due day the runner takes the step with that
choice where the card's policy would have acted, dated the same day, so the issuer
cannot tell whether the other player chose or was away. A later choice replaces an
earlier one, and any step taken on the order clears it. A step on a seat's own order
at its own leader still lands at once.

Pure cases use the toy of ``tests/test_realism_human_due.py`` (Ada files a levy; its
decision step is Bram's); the web cases use the harness of
``tests/test_web_held_step.py``.
"""

import json
from datetime import timedelta
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.project import project
from revisionist.core.realism import effect as rx
from revisionist.core.realism import pipelines
from revisionist.core.realism.pipeline import OrderStatus, StepAction
from revisionist.core.visibility import private_to
from revisionist.engine import catchup
from tests.test_realism_human_due import Toy, _steps
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_held_step import (
    LEVY,
    NOT_YOURS,
    _bram_steps,
    _close,
    _decisions,
    _held_at_bram,
    _item,
    toy,  # noqa: F401
)
from tests.test_web_realism import Realism, post, realism_of
from tests.test_web_wake import log_of, seat_of, state_of


def _card_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card's policy passes every step, so a holder's other choice is told apart."""
    monkeypatch.setattr(pipelines, "_policy", lambda *_a: (StepAction.PASS, {}))


def _chosen(t: Toy, action: StepAction, step: int = 1, **amended: Any) -> None:
    t.add(ev.StepChosen(order_id=t.order_id, step=step, action=action, amended=amended))


# --- the runner and the fold -------------------------------------------------------


def test_the_holders_choice_is_taken_on_the_held_due_day_in_the_cards_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _card_passes(monkeypatch)
    t = Toy()
    t.run(t.arrival)
    _chosen(t, StepAction.REFUSE)
    assert _steps(t.run(t.due - timedelta(days=1))) == [], "taken before the due day"
    (taken,) = _steps(t.run(t.due))
    assert (taken.outcome.action, taken.outcome.on) == (StepAction.REFUSE, t.due)
    assert t.state.orders[t.order_id].status is OrderStatus.REFUSED


def test_a_choice_given_twice_applies_the_last(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipelines, "_policy", lambda *_a: (StepAction.STALL, {}))
    t = Toy()
    t.run(t.arrival)
    _chosen(t, StepAction.REFUSE)
    _chosen(t, StepAction.AMEND, rate=5)
    (taken,) = _steps(t.run(t.due))
    assert (taken.outcome.action, taken.outcome.amended) == (StepAction.AMEND, {"rate": 5})
    assert t.state.orders[t.order_id].params["rate"] == 5


def test_a_step_taken_clears_the_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stall keeps the order at the step; the choice that made it is spent, and the
    next held due day is the card's again."""
    t = Toy()
    t.run(t.arrival)
    _chosen(t, StepAction.STALL)
    assert t.state.orders[t.order_id].held_choice is not None
    (stalled,) = _steps(t.run(t.due))
    assert stalled.outcome.action is StepAction.STALL
    order = t.state.orders[t.order_id]
    assert order.step == 1 and order.held_choice is None
    _card_passes(monkeypatch)
    later = pipelines.held_due(t.state, order)
    assert later is not None
    (passed,) = _steps(t.run(later))
    assert passed.outcome.action is StepAction.PASS


def test_a_holders_pass_on_an_irreversible_order_stands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The card holds an order that cannot be undone; the holder's own pass carries it."""
    _card_passes(monkeypatch)
    war = rx.ProposeMeasure(
        title="A declaration of war on Ostra",
        clauses=(rx.Clause(kind=rx.ClauseKind.POWER, subject="war with Ostra"),),
    )
    t = Toy(measure=war)
    t.run(t.arrival)
    _chosen(t, StepAction.PASS)
    (taken,) = _steps(t.run(t.due))
    assert taken.outcome.action is StepAction.PASS


def test_the_fold_refuses_a_choice_at_a_step_not_held_by_another_seat() -> None:
    t = Toy()
    _chosen(t, StepAction.PASS, step=0)
    with pytest.raises(FoldError):  # still at the clerk's step
        _ = t.state
    t.events.pop()
    t.run(t.arrival)
    for bad in (
        ev.StepChosen(order_id=t.order_id, step=0, action=StepAction.PASS),
        ev.StepChosen(order_id=t.order_id, step=1, action=StepAction.EXPEDITE),
        ev.StepChosen(order_id=t.order_id, step=1, action=StepAction.AMEND, amended={"toll": 2}),
    ):
        t.add(bad)
        with pytest.raises(FoldError):
            _ = t.state
        t.events.pop()


def test_the_choice_never_reaches_the_issuers_view() -> None:
    t = Toy()
    t.run(t.arrival)
    _chosen(t, StepAction.REFUSE)
    state = t.state
    assert state.orders[t.order_id].held_choice is not None
    seen = project(state, t.ada).orders[t.order_id]
    assert seen.held_choice is None
    assert "held_choice" not in seen.model_dump(mode="json")


def test_a_step_choice_is_never_fed() -> None:
    assert "step_chosen" in catchup.NEVER


# --- the web -----------------------------------------------------------------------


def _seen_by_issuer(game: Realism, ada: Client) -> tuple[dict[str, Any], list[Any]]:
    """Everything the issuer's seat is served: its realism block and its catch-up feed."""
    state = state_of(game)
    seat = seat_of(game, "ada")
    fed = catchup.feed(state, log_of(game), seat, 0, state.wake.number if state.wake else 0)
    return realism_of(ada), [(f.wake, f.event.event_id) for f in fed]


def _day(game: Realism, order_id: Any) -> str:
    state = state_of(game)
    due = pipelines.held_due(state, state.orders[order_id])
    assert due is not None
    return f"{due.day} {due:%B %Y}"


def test_the_holders_choice_is_kept_for_them_and_lands_on_the_due_day(
    toy: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bram = toy
    order_id = _held_at_bram(game, ada, bram)
    state = state_of(game)
    due = pipelines.held_due(state, state.orders[order_id])
    assert due is not None
    before = _seen_by_issuer(game, ada)
    status, out = post(bram, "step", order_id=_item(bram)["id"], action="refuse")
    assert status == 200 and out == {
        "reply": f"Your decision is kept until {_day(game, order_id)}. "
        "You can change it until then.",
        "refused": False,
    }, out
    assert _seen_by_issuer(game, ada) == before, "the issuer was served the choice"
    (chosen,) = [e for e in log_of(game) if isinstance(e.payload, ev.StepChosen)]
    assert chosen.scope == private_to(seat_of(game, "bram"))
    assert _bram_steps(game, order_id) == []
    for _ in range(6):
        today = state_of(game).in_world_date
        assert today is not None
        if today >= due:
            break
        assert _bram_steps(game, order_id) == [], f"the step landed on {today}"
        assert "held_choice" not in json.dumps(ada.me())
        _close(ada, bram)
    else:
        raise AssertionError("the due day never came")
    (taken,) = _bram_steps(game, order_id)
    assert (taken.outcome.action, taken.outcome.on) == (StepAction.REFUSE, due)


def test_the_holder_sees_the_choice_on_their_agenda_and_may_change_it(
    toy: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    game, ada, bram = toy
    _held_at_bram(game, ada, bram)
    item = _item(bram)
    assert post(bram, "step", order_id=item["id"], action="stall")[1]["refused"] is False
    assert _item(bram)["cause"] == "You have chosen to stall."
    assert post(bram, "step", order_id=item["id"], action="pass")[1]["refused"] is False
    again = _item(bram)
    assert again["id"] == item["id"] and again["cause"] == "You have chosen to pass."
    assert _decisions(ada) == []


def test_a_refusal_to_a_seat_that_holds_no_step_reads_the_same(
    toy: tuple[Realism, Client, Client],  # noqa: F811
) -> None:
    """An unknown id, another seat's order still at the clerk, and a step another seat
    holds: one text, so a seat cannot tell which ids exist or where an order stands."""
    game, ada, bram = toy
    status, out = post(ada, "lever", **LEVY)
    assert status == 200 and not out["refused"], out
    (order_id,) = state_of(game).orders
    assert not pipelines.waiting_on_human(state_of(game), state_of(game).orders[order_id])
    unknown = post(bram, "step", order_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", action="pass")[1]
    not_waiting = post(bram, "step", order_id=str(order_id), action="pass")[1]
    for _ in range(6):
        if pipelines.held_by_another(state_of(game), state_of(game).orders[order_id]):
            break
        _close(ada, bram)
    not_held = post(ada, "step", order_id=str(order_id), action="pass")[1]
    assert unknown == not_waiting == not_held == {"reply": NOT_YOURS, "refused": True}
