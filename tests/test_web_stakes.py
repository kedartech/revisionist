"""The stakes of ``view.realism``: the contests the seat's view holds, with days left
counted from the world date and a lean only once a track has moved, then the seat's
own open mandates."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.ids import CampaignId, ContestId, EntityId, MandateId, SeatId
from revisionist.core.ontology import Contest
from revisionist.core.realism.agenda import MandateStatus
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.emit import Emitter
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import realism_api as api
from revisionist.engine.web.stakes import seat_stakes

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
OTHER = SeatId("01ARZ3NDEKTSV4RRFFQ69G5FB0")
"""A seat that is not the viewer's: its contests and mandates must not reach the stakes."""
FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
START = cmp.load_world(cmp.world_path("autumn-1941")).start_date


class Game:
    """Roosevelt seated in autumn 1941, before any wake."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        world = cmp.load_world(cmp.world_path("autumn-1941"))
        self.store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
        self.keys = {k: EntityId(v) for k, v in resolve_keys(world, CAMPAIGN).items()}
        realism_tick.seat_player(self.store, CAMPAIGN, self.keys["roosevelt"])
        (self.seat,) = self.state.seats

    @property
    def state(self) -> State:
        return load_state(self.store, CAMPAIGN)

    @property
    def events(self) -> list[Event]:
        return list(self.store.read(CAMPAIGN))

    def contest(self, key: str) -> ContestId:
        return ContestId(self.keys[key])

    def move(self, key: str, change: int, days: int = 0) -> None:
        em = Emitter(self.store, self.state, cmp.versions())
        em.commit(
            [
                em.event(
                    ev.ContestMoved(
                        contest_id=self.contest(key), change=change, days=days, cause="momentum"
                    )
                )
            ]
        )

    def stakes(self, state: State | None = None) -> api.Stakes:
        return seat_stakes(state or self.state, self.seat, self.events)


@pytest.fixture
def game() -> Game:
    return Game()


def by_name(stakes: api.Stakes) -> dict[str, api.Stake]:
    return {s["name"]: s for s in stakes["contests"]}


def with_contest(state: State, contest: Contest) -> State:
    return state.model_copy(update={"contests": {**state.contests, contest.contest_id: contest}})


# --- contests -------------------------------------------------------------------


def test_each_contest_the_seat_holds_has_its_name_prize_and_sides(game: Game) -> None:
    stakes = game.stakes()
    assert set(stakes) == set(api.Stakes.__annotations__)
    assert all(set(s) == set(api.Stake.__annotations__) for s in stakes["contests"])
    named = by_name(stakes)
    assert set(named) == {
        "Revising the Neutrality Act",
        "The US-Japan negotiations",
        "The war against Germany",
    }
    talks = named["The US-Japan negotiations"]
    assert talks["prize"] == "Whether talks end in a modus vivendi or in war in the Pacific."
    assert talks["sides"] == ["United States", "Japan", "China"]


def test_days_left_count_from_the_world_date(game: Game) -> None:
    assert START is not None
    named = by_name(game.stakes())
    assert named["Revising the Neutrality Act"]["days_left"] == 73
    later = game.state.model_copy(update={"in_world_date": START + timedelta(days=10)})
    assert by_name(game.stakes(later))["Revising the Neutrality Act"]["days_left"] == 63
    past = game.state.model_copy(update={"in_world_date": START + timedelta(days=80)})
    assert by_name(game.stakes(past))["Revising the Neutrality Act"]["days_left"] == 0


def test_days_left_follow_the_date_after_a_wake(game: Game) -> None:
    realism_tick.run_realism_tick(game.store, CAMPAIGN)
    state = game.state
    assert state.in_world_date is not None and START is not None
    gone = (state.in_world_date - START).days
    assert gone > 0
    assert by_name(game.stakes())["The war against Germany"]["days_left"] == 97 - gone


def test_contests_run_soonest_first_then_by_name(game: Game) -> None:
    assert [s["name"] for s in game.stakes()["contests"]] == [
        "Revising the Neutrality Act",
        "The US-Japan negotiations",
        "The war against Germany",
    ]
    state = game.state
    war = state.contests[game.contest("atlantic_war")]
    sooner = with_contest(state, war.model_copy(update={"countdown_days": 10}))
    names = [s["name"] for s in seat_stakes(sooner, game.seat, [])["contests"]]
    assert names[0] == "The war against Germany"


def test_a_contest_the_view_does_not_hold_is_absent(game: Game) -> None:
    state = game.state
    talks = state.contests[game.contest("us_japan_talks")]
    hidden = with_contest(state, talks.model_copy(update={"scope": private_to(OTHER)}))
    assert "The US-Japan negotiations" not in by_name(game.stakes(hidden))
    assert len(game.stakes(hidden)["contests"]) == 2


def test_a_decided_contest_is_no_longer_at_stake(game: Game) -> None:
    state = game.state
    talks = state.contests[game.contest("us_japan_talks")]
    decided = with_contest(state, talks.model_copy(update={"decided": True, "countdown_days": 0}))
    assert set(by_name(game.stakes(decided))) == {
        "Revising the Neutrality Act",
        "The war against Germany",
    }


# --- the lean -------------------------------------------------------------------


def test_no_contest_carries_a_lean_before_its_track_moves(game: Game) -> None:
    contests = game.stakes()["contests"]
    assert len(contests) == 3 and all(s["lean"] is None for s in contests)


def test_a_wake_moves_no_track_so_no_lean_is_sent(game: Game) -> None:
    realism_tick.run_realism_tick(game.store, CAMPAIGN)
    contests = game.stakes()["contests"]
    assert len(contests) == 3 and all(s["lean"] is None for s in contests)


def test_a_moved_track_sends_a_lean_toward_the_side_it_favours(game: Game) -> None:
    game.move("neutrality_revision", 30)
    named = by_name(game.stakes())
    assert named["Revising the Neutrality Act"]["lean"] == {
        "step": 7,
        "favours": "Aid-to-Britain bloc",
    }
    assert named["The war against Germany"]["lean"] is None


def test_a_countdown_only_move_sends_no_lean(game: Game) -> None:
    game.move("neutrality_revision", 0, days=7)
    assert by_name(game.stakes())["Revising the Neutrality Act"]["lean"] is None


def test_a_track_moved_back_to_level_still_leans_with_no_side(game: Game) -> None:
    game.move("neutrality_revision", -40)
    game.move("neutrality_revision", 40)
    lean = by_name(game.stakes())["Revising the Neutrality Act"]["lean"]
    assert lean == {"step": 6, "favours": None}


@pytest.mark.parametrize(
    ("change", "step", "favours"),
    [
        (-100, 1, "Non-interventionist bloc"),
        (-81, 1, "Non-interventionist bloc"),
        (-80, 2, "Non-interventionist bloc"),
        (-1, 5, "Non-interventionist bloc"),
        (1, 6, "Aid-to-Britain bloc"),
        (20, 7, "Aid-to-Britain bloc"),
        (79, 9, "Aid-to-Britain bloc"),
        (100, 10, "Aid-to-Britain bloc"),
    ],
)
def test_the_lean_has_ten_steps_across_the_track(
    game: Game, change: int, step: int, favours: str
) -> None:
    game.move("neutrality_revision", change)
    lean = by_name(game.stakes())["Revising the Neutrality Act"]["lean"]
    assert lean == {"step": step, "favours": favours}


def test_the_lean_carries_no_number_from_the_track(game: Game) -> None:
    game.move("neutrality_revision", 37)
    stake = by_name(game.stakes())["Revising the Neutrality Act"]
    assert "37" not in json.dumps(stake)
    assert "track" not in json.dumps(stake)


# --- mandates -------------------------------------------------------------------


def test_the_seats_open_mandates_follow_with_text_and_days_left(game: Game) -> None:
    state = game.state
    (mandate,) = state.mandates.values()
    stakes = game.stakes()
    assert stakes["mandates"] == [
        {"text": mandate.text, "days_left": (mandate.expires - START).days if START else -1}
    ]
    assert all(set(m) == set(api.StakeMandate.__annotations__) for m in stakes["mandates"])


def test_mandates_run_soonest_first(game: Game) -> None:
    state = game.state
    (first,) = state.mandates.values()
    sooner = first.model_copy(
        update={
            "mandate_id": MandateId("7ZZZZZZZZZZZZZZZZZZZZZZZZZ"),  # sorts after the first by id
            "text": "Sooner",
            "expires": first.expires - timedelta(days=5),
        }
    )
    both = state.model_copy(update={"mandates": {**state.mandates, sooner.mandate_id: sooner}})
    assert [m["text"] for m in game.stakes(both)["mandates"]] == ["Sooner", first.text]


@pytest.mark.parametrize("status", [MandateStatus.MET, MandateStatus.FAILED, MandateStatus.EXPIRED])
def test_a_closed_mandate_is_not_listed(game: Game, status: MandateStatus) -> None:
    state = game.state
    (mandate,) = state.mandates.values()
    closed = state.model_copy(
        update={"mandates": {mandate.mandate_id: mandate.model_copy(update={"status": status})}}
    )
    assert game.stakes(closed)["mandates"] == []


def test_another_seats_mandate_is_absent(game: Game) -> None:
    state = game.state
    (mandate,) = state.mandates.values()
    theirs = mandate.model_copy(
        update={
            "mandate_id": MandateId("01ARZ3NDEKTSV4RRFFQ69G5FC2"),
            "seat_id": OTHER,
            "text": "Not yours",
            "scope": private_to(OTHER),
        }
    )
    both = state.model_copy(update={"mandates": {**state.mandates, theirs.mandate_id: theirs}})
    assert [m["text"] for m in game.stakes(both)["mandates"]] == [mandate.text]


def test_a_past_deadline_counts_as_no_days_left(game: Game) -> None:
    state = game.state
    (mandate,) = state.mandates.values()
    late = state.model_copy(update={"in_world_date": mandate.expires + timedelta(days=3)})
    assert [m["days_left"] for m in game.stakes(late)["mandates"]] == [0]


# --- the block ------------------------------------------------------------------


def test_the_client_fixture_carries_the_stakes_in_the_servers_shape() -> None:
    stakes = json.loads(FIXTURE.read_text())["stakes"]
    assert set(stakes) == set(api.Stakes.__annotations__)
    assert stakes["contests"] and stakes["mandates"]
    assert all(set(s) == set(api.Stake.__annotations__) for s in stakes["contests"])
    assert all(set(m) == set(api.StakeMandate.__annotations__) for m in stakes["mandates"])
    leans = [s["lean"] for s in stakes["contests"]]
    assert any(lean is None for lean in leans)
    assert any(
        lean is not None and set(lean) == set(api.StakeLean.__annotations__) for lean in leans
    )
