"""The opening matter: a seat that would open with an empty agenda is handed one
thing to answer, so wake 0 asks something of it."""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, replay
from revisionist.core.goals import Ordered
from revisionist.core.ids import MandateId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import mandates
from revisionist.core.realism.agenda import Mandate, MandateKind, MandateStatus, PlayStyle
from revisionist.core.realism.effect import EffectKind
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine import options, realism_tick, wake
from revisionist.engine.store import MemoryStore
from tests.test_engine_v2_contract import Slice
from tests.test_engine_v2_mandates import _fire, _issued
from tests.test_engine_v2_wake import CAMPAIGN, T0, Table


def _opening(t: Table, seat: SeatId) -> Mandate:
    return t.state.mandates[MandateId(derived_id(CAMPAIGN, "mandate", "opening", seat))]


def test_every_human_seat_opens_with_one_matter() -> None:
    t = Table(MemoryStore())
    start = t.state.in_world_date
    assert start is not None and t.winston is not None
    for seat in (t.fdr, t.winston):
        m = _opening(t, seat)
        assert m.mandate_id == MandateId(derived_id(CAMPAIGN, "mandate", "opening", seat))
        assert m.status is MandateStatus.LIVE and m.issued == start
        assert m.expires == start + timedelta(days=14)
        assert isinstance(m.condition, Ordered)
        assert m.condition.person == t.state.seats[seat].embodies
        assert "_" not in m.text and f"{m.expires.day} {m.expires:%B}" in m.text


def test_a_seat_whose_principal_is_a_country_is_given_an_opening_not_an_order() -> None:
    t = Table(MemoryStore())
    m = _opening(t, t.fdr)
    assert m.kind is MandateKind.OPPORTUNITY and m.issuer is None
    assert m.condition.effect is EffectKind.STATEMENT  # type: ignore[union-attr]


def _with_card(t: Table, **changes: object) -> State:
    """The table's state with Roosevelt's card altered."""
    state = t.state
    me = state.seats[t.fdr].embodies
    assert me is not None
    card = state.cards[me].model_copy(update=changes)
    return state.model_copy(update={"cards": {**state.cards, me: card}, "mandates": {}})


def test_a_seat_that_answers_to_a_person_is_asked_by_that_person() -> None:
    t = Table(MemoryStore())
    stark = t.entity("stark")
    state = _with_card(t, principals=(stark,))
    start = state.in_world_date
    assert start is not None
    made = mandates.opening(state, t.fdr, start)
    assert made is not None
    m = made.mandate
    assert m.kind is MandateKind.ORDER and m.issuer == stark
    assert m.text.startswith(state.entities[stark].name)


def test_a_seat_with_nothing_to_command_is_given_no_opening_matter() -> None:
    t = Table(MemoryStore())
    state = _with_card(t, authority=())
    assert state.in_world_date is not None
    assert mandates.opening(state, t.fdr, state.in_world_date) is None


def test_a_seat_that_already_has_a_matter_is_given_no_second_one() -> None:
    t = Table(MemoryStore())
    assert t.state.in_world_date is not None
    assert mandates.opening(t.state, t.fdr, t.state.in_world_date) is None


def test_the_opening_matter_is_on_the_first_offer() -> None:
    t = Table(MemoryStore())
    options.set_style(t.store, CAMPAIGN, t.fdr, PlayStyle.BEGINNER)
    wake.open_wake(t.store, CAMPAIGN, T0)
    made = options.offer(t.state, t.fdr, None)
    assert made is not None
    assert _opening(t, t.fdr).mandate_id in {o.mandate_id for o in made.offers}


def test_the_opening_matter_is_met_by_the_first_order_of_its_kind() -> None:
    t = Table(MemoryStore())
    made = options.template_options(
        project(t.state, t.fdr),
        None,
        PlayStyle.BEGINNER,
    )
    speak = next(o for o in made if o.label == "Make a public statement")
    realism_tick.commit_order(t.store, CAMPAIGN, t.fdr, speak.asks)
    for _ in range(6):
        realism_tick.run_realism_tick(t.store, CAMPAIGN)
        if _opening(t, t.fdr).status is not MandateStatus.LIVE:
            break
    assert _opening(t, t.fdr).status is MandateStatus.MET
    settled = t.payloads(ev.MandateSettled)
    assert any(p.mandate_id == _opening(t, t.fdr).mandate_id for p in settled)


GREER = date(1941, 9, 4)


def _slice_holding(opening: bool) -> Slice:
    sl = Slice()
    greer = sl.state.templates["greer_response"]
    extras = [greer.model_copy(update={"key": f"extra_{n}"}) for n in range(2)]
    sl.add(ev.CardsDeclared(templates=tuple(extras)))
    if opening:
        made = mandates.opening(sl.state, sl.fdr, GREER - timedelta(days=2))
        assert made is not None
        sl.add(made, private_to(sl.fdr))
    return sl


def _templated(sl: Slice) -> list[Mandate]:
    _fire(sl, "greer_incident")
    return _issued(sl.state, GREER)


def _issue(sl: Slice, made: list[Mandate]) -> None:
    for m in made:
        sl.add(ev.MandateIssued(mandate=m), private_to(sl.fdr))


def test_the_opening_matter_leaves_a_seat_its_three_template_slots() -> None:
    sl = _slice_holding(opening=True)
    got = _templated(sl)
    assert len(got) == 3
    _issue(sl, got)
    live = [m for m in sl.state.mandates.values() if m.status is MandateStatus.LIVE]
    assert len(live) == 4


def test_the_fold_takes_a_third_template_mandate_beside_the_opening_matter() -> None:
    sl = _slice_holding(opening=True)
    _issue(sl, _templated(sl))
    assert len(replay(sl.events).mandates) == 4


def test_the_fold_refuses_a_fourth_template_mandate_with_or_without_the_opening_matter() -> None:
    for opening in (True, False):
        sl = _slice_holding(opening)
        got = _templated(sl)
        extra = got[0].model_copy(
            update={"mandate_id": MandateId(derived_id(CAMPAIGN, "mandate", "one_more", sl.fdr))}
        )
        _issue(sl, got)
        replay(sl.events)
        _issue(sl, [extra])
        with pytest.raises(FoldError, match="already holds"):
            replay(sl.events)
