"""1941: a card's authority covers every order its forms give (CAU).

A written order is routed by the card's authority before it is filed as the form that gives
it, so a form whose order no domain of its card covers could be filed and could not be
written. Each head of government below holds a form of that kind: a reconnaissance flight,
an agent, a patrol, a concealment, a production priority, or a move of a force no domain
named. Each card gains the domain the form's order needs, carried out by the person the
world's intelligence lines name for that source where it has one, so the written order is a
command where the form is.

The scripted run's digest (``run_digest``) with the third-run switches taken out of a copy's
rules is the baseline; with them on it is the one the commanders' items recorded.
"""

from datetime import date

import pytest

from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.effect import Route
from revisionist.core.realism.reach import channels_to
from revisionist.core.realism.route import route
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.store import MemoryStore, load_state
from tests.test_rule_names import BASELINE_1941
from tests.test_world_forces import parts
from tests.test_world_locks_1941 import run_digest
from tests.test_world_locks_uk_1941 import without_third_run
from tests.test_written_order_parity import CAMPAIGN, _ask, entity, feature, seat
from tests.written_order_cases import CASES, Case

ON = "5cb9d48860d1833b119a377cd7b0863d"
"""The scripted run's digest with the 1941 world's third-run switches on, as the commanders'
items recorded it: the script files none of the forms below."""

FILED = date(1941, 9, 20)
HEADS = ("roosevelt", "churchill", "stalin", "hitler", "konoe", "tojo", "mussolini", "chiang")

COVERED = {
    "roosevelt": {"fly_recon": "reconnaissance"},
    "churchill": {
        "production_priority": "war_production",
        "move_army": "army_operations",
        "fly_recon": "intelligence",
        "send_an_agent": "intelligence",
        "fund_the_codebreakers": "war_production",
    },
    "stalin": {"send_on_patrol": "military_operations", "send_an_agent": "intelligence"},
    "hitler": {"production_priority": "war_production", "fly_recon": "air_reconnaissance"},
    "konoe": {"send_an_agent": "intelligence"},
    "tojo": {
        "fly_recon": "intelligence",
        "send_on_patrol": "naval_operations",
        "send_an_agent": "intelligence",
        "hide_a_force": "naval_operations",
    },
    "mussolini": {
        "move_fleet": "supreme_command",
        "move_army": "supreme_command",
        "send_on_patrol": "supreme_command",
    },
    "chiang": {"move_army": "military_affairs", "send_an_agent": "intelligence"},
}
"""The twenty forms whose written orders the second run's close found unrouted, and the
domain of the card's that covers each. Mussolini's three and Chiang's move were inside
their cards' domains already: they failed only beside the others in a shared batch."""

EXECUTORS = {
    ("roosevelt", "reconnaissance"): "marshall",
    ("churchill", "intelligence"): "menzies",
    ("stalin", "intelligence"): "shaposhnikov",
    ("hitler", "air_reconnaissance"): "goering",
    ("konoe", "intelligence"): "nagano",
    ("tojo", "intelligence"): "nagano",
    ("tojo", "naval_operations"): "nagano",
    ("chiang", "intelligence"): "dai_li",
}
"""Who carries out each new domain: the person the world's intelligence lines name for the
nation's source (air, agent or patrol). [proposed]"""


def _case(person: str, lever: str) -> Case:
    return next(c for c in CASES if (c.world, c.person, c.lever) == ("1941", person, lever))


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


@pytest.fixture(scope="module")
def state() -> State:
    """The 1941 world compiled, the eight heads claimed and play opened."""
    store = MemoryStore()
    store.append_all(compile_world(_world(), CAMPAIGN, cmp.versions()))
    names = load_state(store, CAMPAIGN).entities
    for person in HEADS:
        session_zero.claim(store, CAMPAIGN, seat(person), names[entity(person)].name)
    realism_tick.open_play(store, CAMPAIGN)
    return load_state(store, CAMPAIGN)


FORMS = [(p, lv, d) for p, levers in COVERED.items() for lv, d in levers.items()]


@pytest.mark.parametrize(("person", "lever", "domain"), FORMS, ids=lambda v: str(v))
def test_each_form_s_order_is_a_command_inside_its_card_s_domain(
    state: State, person: str, lever: str, domain: str
) -> None:
    case = _case(person, lever)
    assert len(case.reading) == 1
    read = _ask(case.sentence, case.reading[0])
    ask = Ask.model_validate({k: v for k, v in read.items() if k != "detail"})
    routed = route(state, seat(person), ask, FILED)
    assert routed.part is not None, routed.refusal
    assert routed.part.route is Route.COMMAND
    assert routed.part.domain == domain


def test_the_twenty_forms_are_the_heads_forms_the_close_listed() -> None:
    assert len(FORMS) == 20
    assert all(p in HEADS for p, _, _ in FORMS)


@pytest.mark.parametrize(("person", "domain"), sorted(EXECUTORS), ids=lambda v: str(v))
def test_each_new_domain_is_carried_out_by_someone_the_head_can_reach(
    state: State, person: str, domain: str
) -> None:
    card = state.cards[entity(person)]
    found = next(d for d in card.authority if d.name == domain)
    assert found.executor is not None
    assert found.executor == entity(EXECUTORS[person, domain])
    assert channels_to(state, card.person, found.executor)


def test_a_new_force_in_a_domain_is_one_the_form_names() -> None:
    """Each force a domain gained is a choice of the form that moves it, and no domain of
    another head names it."""
    gained = {
        ("churchill", "army_operations"): "western_desert_force",
        ("stalin", "military_operations"): "baltic_fleet",
        ("tojo", "naval_operations"): "combined_fleet",
    }
    cards = {c.person: c for c in _world().cards}
    for (person, domain), force in gained.items():
        card = cards[person]
        assert force in next(d for d in card.authority if d.name == domain).forces
        others = [
            c.person
            for c in cards.values()
            if c.person in HEADS and c.person != person
            for d in c.authority
            if force in d.forces
        ]
        assert others == [], (force, others)


def test_tojo_s_naval_domain_names_the_combined_fleet_alone(state: State) -> None:
    card = state.cards[entity("tojo")]
    found = next(d for d in card.authority if d.name == "naval_operations")
    # the Combined Fleet and the parts split from it (KDA)
    assert found.forces == tuple(feature(k) for k in parts("combined_fleet"))


# --- the scripted run ---------------------------------------------------------------------


def test_the_scripted_run_with_the_third_run_switches_off_equals_the_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(without_third_run(_world()), monkeypatch) == BASELINE_1941


def test_the_scripted_run_with_the_third_run_switches_on_is_as_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert run_digest(_world(), monkeypatch) == ON
