"""The aide's bar: one list of what the aide never does for an absent seat, whatever a
standing order says, checked where its orders are chosen and again where each lands."""

from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from revisionist.core.ids import OrderId, SeatId
from revisionist.core.realism import apply, detect
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.detect import AIDE_BAR, Barred
from revisionist.core.realism.effect import (
    Appointment,
    Deal,
    EffectKind,
    MakeStatement,
    Route,
)
from revisionist.core.state import State
from revisionist.engine import options, wake
from revisionist.engine.web import server
from tests.test_engine_v2_contract import Slice

# --- every act the aide could be asked to do ----------------------------------------

AIDE_FILES = "the aide files orders: an option it picks, with the bar and its rules checked"
CLOSES = "the wake closes for the aide when the seat has not committed"
NO_DEAL = "the aide makes no deal of its own: a deal is the seat's own to strike"
BATTLE = "in a battle game the aide neither presses, withdraws nor changes a contingency"
CONFERENCE = "a seat with no vote sealed is given the aide's fallback vote"
OWN_STEP = "a seat's own choice about the game or its own view: the aide never makes it"
HARMLESS = "harmless: reads or shows, files nothing"

ACTIONS: dict[str, Barred | str] = {
    # in a game in play
    "catchup": HARMLESS,
    "map": HARMLESS,
    "check": HARMLESS,
    "odds": HARMLESS,
    "read": HARMLESS,
    "flag": HARMLESS,
    "lever": AIDE_FILES,
    "directive": AIDE_FILES,
    "sign": AIDE_FILES,
    "aide": HARMLESS,
    "consult": HARMLESS,
    "help": HARMLESS,
    "step": Barred.REFUSE,
    "advance": OWN_STEP,
    "commit": CLOSES,
    "close": CLOSES,
    "style": OWN_STEP,
    "option": AIDE_FILES,
    "answer": Barred.ANSWER,
    "order": AIDE_FILES,
    "agreement-offer": NO_DEAL,
    "file": AIDE_FILES,
    "withdraw": OWN_STEP,
    "ask": Barred.ASK_HELD,
    "battle": BATTLE,
    "contingency": BATTLE,
    "agreement-publish": NO_DEAL,
    "conference-call": CONFERENCE,
    "conference-vote": CONFERENCE,
    "report": HARMLESS,
    "reports": HARMLESS,
    "report-mark": HARMLESS,
    "aim-check": HARMLESS,
    "aim-set": OWN_STEP,
    "offer": Barred.BLOC_OFFER,
    # the game menu
    "pause": OWN_STEP,
    "resume": OWN_STEP,
    "end": OWN_STEP,
    "leave": OWN_STEP,
    "wake-hours": OWN_STEP,
    "handover-list": HARMLESS,
    "handover": OWN_STEP,
    "reveal": HARMLESS,
    "notice-address": OWN_STEP,
    # a new game
    "worlds": HARMLESS,
    "timeline": HARMLESS,
    "figures": HARMLESS,
    "ready": OWN_STEP,
    "pitch": OWN_STEP,
    "cast": OWN_STEP,
    "start": OWN_STEP,
    "pick": OWN_STEP,
    "unpick": OWN_STEP,
    "invite": OWN_STEP,
    "begin": OWN_STEP,
    "opening": OWN_STEP,
}
"""Every action the server answers a seat in a game, by what holds the aide off it."""

KINDS: dict[EffectKind, Barred | str] = {
    EffectKind.MOVE_FORCE: BATTLE,
    EffectKind.ENGAGEMENT: BATTLE,
    EffectKind.ALLOCATE: "an irreversible transfer needs a standing order naming it",
    EffectKind.APPOINTMENT: Barred.APPOINT,
    EffectKind.MEASURE: "a declaration needs a standing order, told by its title",
    EffectKind.STATEMENT: HARMLESS,
    EffectKind.INVESTIGATE: "the aide places no agent (intelligence rule 7)",
    EffectKind.DEAL: Barred.ACCEPT,
    EffectKind.DISPOSITION: HARMLESS,
    EffectKind.DISCLOSURE: HARMLESS,
    EffectKind.FIGURE: "estimated only: no seat orders it",
    EffectKind.GROUP: "estimated only: no seat orders it",
}
"""Every effect kind an order can carry, by what holds the aide to it."""

ACTS_WITH_NO_ACTION = {
    Barred.SEND_HELD: "a held order is sent anyway only by its own seat (defiance.BY_AIDE)",
    Barred.OFFICE_VOTE: "the aide files no choice at a sitting: the card decides on the day",
    Barred.BREAKAWAY: "no rule lets a seat break away yet",
    Barred.PLOT: "no rule lets a seat launch a plot yet",
    Barred.PURGE: "no rule lets a seat order a purge yet",
}
"""Acts on the bar no server action does by its own name."""


NO_AIDE = "the first game's seat calls: no aide plays a seat there"
FIRST_GAME: dict[str, Barred | str] = {
    name: NO_AIDE
    for name in (
        "agent",
        "ask",
        "bug",
        "claim",
        "confirm",
        "dispatch",
        "dossier",
        "goal",
        "history",
        "join",
        "order",
        "pick",
        "report",
        "roster",
        "search",
        "status",
    )
}
"""Every seat call of the first game, whose names the realism game reuses for other acts."""


def _answered() -> set[str]:
    return {
        *server.REALISM_ACTIONS,
        *server.GAME_ACTIONS,
        *server.GAME_OPEN,
        *server.NEW_GAME_ACTIONS,
    }


def test_every_action_and_effect_kind_is_barred_ruled_or_harmless() -> None:
    assert set(ACTIONS) == _answered()
    assert set(FIRST_GAME) == set(server.SEAT_ACTIONS)
    assert set(KINDS) == set(EffectKind)
    held_off = {*ACTIONS.values(), *KINDS.values(), *ACTS_WITH_NO_ACTION}
    for act in (v for v in held_off if isinstance(v, Barred)):
        assert act in AIDE_BAR, act
    assert set(AIDE_BAR) <= held_off


def test_breakaways_plots_and_purges_are_on_the_bar_by_name() -> None:
    assert {Barred.BREAKAWAY, Barred.PLOT, Barred.PURGE} <= AIDE_BAR


# --- an option on the bar at the head of the aide's list ----------------------------


def _deal(sl: Slice) -> Deal:
    return Deal(counterparty=sl.entity("germany"), accept=True)


def _appointment(sl: Slice) -> Appointment:
    return Appointment(person=sl.entity("stark"), office="CNO", appoint=False)


BARRED_EFFECTS: dict[Barred, Callable[[Slice], Deal | Appointment]] = {
    Barred.ACCEPT: _deal,
    Barred.APPOINT: _appointment,
}


def _statement() -> MakeStatement:
    return MakeStatement(theme="convoys")


def _choosing(monkeypatch: pytest.MonkeyPatch, *heads: Any) -> None:
    """The aide's list is ``heads`` as one-ask options, then a statement."""
    picks = [*heads, _statement()]
    listed = [
        SimpleNamespace(asks=(Ask(ask=f"ask {n}", effect=e),), expects=(), risks=None)
        for n, e in enumerate(picks)
    ]
    monkeypatch.setattr(options, "_live", lambda view: [object()])
    monkeypatch.setattr(options, "_wants_a_deal", lambda mandate: False)
    monkeypatch.setattr(options, "_options_for", lambda *a, **k: listed)


def _filed(state: State, seat: SeatId) -> list[Any]:
    """Every effect the aide files for ``seat``: nothing, or something other than the head."""
    return [a.effect for order in options.aide_asks(state, seat, None) for a in order]


@pytest.mark.parametrize("act", sorted(BARRED_EFFECTS))
def test_an_option_on_the_bar_at_the_head_is_passed_over(
    act: Barred, monkeypatch: pytest.MonkeyPatch
) -> None:
    sl = Slice()
    head = BARRED_EFFECTS[act](sl)
    assert detect.barred(head, frozenset()) is act
    _choosing(monkeypatch, head)
    assert head not in _filed(sl.state, sl.fdr)


@pytest.mark.parametrize("act", sorted(BARRED_EFFECTS))
def test_the_wake_close_keeps_the_bar_too(act: Barred) -> None:
    sl = Slice()
    asks = (Ask(ask="head", effect=BARRED_EFFECTS[act](sl)), Ask(ask="s", effect=_statement()))
    kept = wake._allowed(sl.state, sl.fdr, asks)
    assert [a.effect for a in kept] == [_statement()]


def test_a_standing_order_naming_appointments_lets_one_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sl = Slice()
    state = sl.state.model_copy(update={"standing": {sl.fdr: frozenset({"appointment"})}})
    _choosing(monkeypatch, _appointment(sl))
    (filed,) = options.aide_asks(state, sl.fdr, None)
    assert [a.effect for a in filed] == [_appointment(sl)]


def test_no_standing_order_lets_the_aide_accept_an_agreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sl = Slice()
    every = frozenset(EffectKind)
    state = sl.state.model_copy(update={"standing": {sl.fdr: every}})
    _choosing(monkeypatch, _deal(sl))
    assert _deal(sl) not in _filed(state, sl.fdr)
    assert detect.barred(_deal(sl), every) is Barred.ACCEPT


def test_an_offer_of_a_deal_is_still_the_seats_own(monkeypatch: pytest.MonkeyPatch) -> None:
    sl = Slice()
    offer = Deal(counterparty=sl.entity("germany"), offer=("oil",))
    assert detect.barred(offer, frozenset(EffectKind)) is None
    _choosing(monkeypatch, offer)
    assert offer not in _filed(sl.state, sl.fdr)


# --- the second check, where each lands ---------------------------------------------


def _today(state: State) -> date:
    assert state.in_world_date is not None
    return state.in_world_date


@pytest.mark.parametrize("act", sorted(BARRED_EFFECTS))
def test_an_act_on_the_bar_never_lands_for_the_aide(act: Barred) -> None:
    sl = Slice()
    effect = BARRED_EFFECTS[act](sl)
    on = _today(sl.state)
    assert apply.land_effect(sl.state, effect, sl.fdr, on, "r", aide=False)
    assert apply.land_effect(sl.state, effect, sl.fdr, on, "r", aide=True) == []


@pytest.mark.parametrize("act", sorted(BARRED_EFFECTS))
def test_an_aide_orders_part_on_the_bar_carries_nothing(act: Barred) -> None:
    sl = Slice()
    effect = BARRED_EFFECTS[act](sl)
    oid = OrderId("aide-order")
    part = SimpleNamespace(
        refusal=False, route=Route.PROCESS, accepted=True, effect=effect, estimated=()
    )
    order = SimpleNamespace(order_id=oid, issuer=sl.fdr)
    own = apply._carried(sl.state, order, part)  # type: ignore[arg-type]
    assert own == [effect]
    aides = sl.state.model_copy(update={"aide_orders": frozenset({oid})})
    assert apply._carried(aides, order, part) == []  # type: ignore[arg-type]


def test_a_held_option_at_the_head_is_passed_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """The aide neither asks for a held order nor sends one anyway: it files the next."""
    sl = Slice()
    head = MakeStatement(theme="the held one")
    _choosing(monkeypatch, head)
    monkeypatch.setattr(
        options, "held", lambda state, seat, ask, today: "lock" if ask.effect == head else None
    )
    assert _filed(sl.state, sl.fdr) == [_statement()]
