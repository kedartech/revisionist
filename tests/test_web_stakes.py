"""The stakes of ``view.realism``: the contests the seat's view holds, with days left
counted from the world date and a lean only once a track has moved (a decided one with
its winner), then the seat's own open mandates; then the seat's own aims with their
evidence and status, the degree of the win, the drift and the days to the season's end
(SCD)."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Literal

import pytest

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.goals import Exposure, HoldsArea, SupportAt, goal_met, season_winners
from revisionist.core.ids import CampaignId, ContestId, EntityId, MandateId, SeatId
from revisionist.core.ontology import Contest, Controller, Phase
from revisionist.core.realism import groups
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
from tests import test_realism_aims as ta
from tests import test_realism_season as sea
from tests.test_adjacency_moves import START as TOY_START
from tests.test_territory_model import CAMPAIGN as TOY_CAMPAIGN

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


def test_a_decided_contest_sends_its_winner(game: Game) -> None:
    state = game.state
    talks = state.contests[game.contest("us_japan_talks")]
    japan = next(k for k, e in state.entities.items() if e.name == "Japan")
    won = with_contest(state, talks.model_copy(update={"decided": True, "winner": japan}))
    assert game.stakes(won)["decided"] == [
        {
            "name": "The US-Japan negotiations",
            "prize": talks.prize,
            "sides": ["United States", "Japan", "China"],
            "winner": "Japan",
        }
    ]
    drawn = with_contest(state, talks.model_copy(update={"decided": True}))
    assert game.stakes(drawn)["decided"][0]["winner"] is None


def test_no_contest_is_decided_at_the_start(game: Game) -> None:
    assert game.stakes()["decided"] == []


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
    assert stakes["aims"] and all(
        set(a) == set(api.StakeAim.__annotations__) for a in stakes["aims"]
    )
    leaves = [x for a in stakes["aims"] for x in a["leaves"]]
    assert all(set(x) == set(api.StakeLeaf.__annotations__) for x in leaves)
    assert {x["seen"] for x in leaves} == {"public", "own", "uncertain"}
    assert stakes["decided"] and all(
        set(d) == set(api.StakeDecided.__annotations__) for d in stakes["decided"]
    )
    leans = [s["lean"] for s in stakes["contests"]]
    assert any(lean is None for lean in leans)
    assert any(
        lean is not None and set(lean) == set(api.StakeLean.__annotations__) for lean in leans
    )


# --- the seat's own aims (SCD) --------------------------------------------------------
#
# The toy world with the aims rule on (``tests/test_realism_aims.py``): Ilse of Norra and
# Tomas of Sudland, each card's aims ruled by conditions on what the territory rules move.

GREENS = "greens"  # Norra's own group: the Greens start at 60


def toy_stakes(g: ta.Game, person: EntityId = ta.ILSE, state: State | None = None) -> api.Stakes:
    state = state or g.state
    return seat_stakes(state, ta.seat_of(state, person), list(g.store.read(TOY_CAMPAIGN)))


def support(nation: str, group: str, op: str, value: int) -> ta.World:
    return {"check": "support_at", "nation": nation, "group": group, "op": op, "value": value}


HIDDEN_FARMERS = support("sudland", "farmers", "le", 20)
"""Sudland's Farmers: another nation's group, so hidden from Ilse's seat."""


def ruled(tmp: Path, *conditions: ta.World) -> ta.Game:
    """The toy game with Ilse's aims ruled by ``conditions``, one per aim, ticked once
    so each goal is made."""
    g = ta.Game(ta.world(tmp, sea.three(*conditions)))
    g.tick()
    return g


def with_farmers(state: State, value: int) -> State:
    """``state`` with Sudland's Farmers at ``value``: a fact hidden from Ilse."""
    sup = {**state.groups.support, ta.SUDLAND: {**state.groups.support.get(ta.SUDLAND, {}),
                                                "farmers": value}}  # fmt: skip
    return state.model_copy(update={"groups": state.groups.model_copy(update={"support": sup})})


def test_each_aim_carries_its_source_status_rule_period_evidence_and_reason(
    tmp_path: Path,
) -> None:
    g = ruled(tmp_path, ta.HILLS_HELD, ta.ISLE_HELD, support("norra", GREENS, "ge", 50))
    aims = toy_stakes(g)["aims"]
    assert [a["aim"] for a in aims] == [1, 2, 3]
    assert all(set(a) == set(api.StakeAim.__annotations__) for a in aims)
    hills, isle, greens = aims
    assert hills["text"] == "One." and hills["rule"] == "Aim 1 holds."
    assert hills["source"] == "post"
    assert (hills["status"], hills["reason"]) == ("met", "It holds now.")
    assert (hills["opens"], hills["deadline"]) == (None, None)
    assert hills["leaves"] == [
        {
            "reads": "The Norra Hills held by Norra",
            "seen": "public",
            "holds": True,
            "evidence": ["The Norra Hills is held by Norra."],
        }
    ]
    assert isle["status"] == "at_risk" and isle["leaves"][0]["holds"] is False
    assert isle["reason"] == "It does not hold now; it still can."
    (leaf,) = greens["leaves"]
    now = groups.support(g.state, ta.NORRA, GREENS)
    assert now is not None and now >= 50
    assert (leaf["seen"], leaf["holds"]) == ("own", True)
    assert leaf["evidence"] == [f"The Greens in Norra stands at {now}."]


def test_the_period_is_sent_and_an_aim_not_yet_open_is_at_risk(tmp_path: Path) -> None:
    g = ruled(tmp_path, ta.HILLS_HELD)
    state, _ = ta.with_goal(
        g.state, HoldsArea(area=ta.HILLS, holder=ta.NORRA), opens=ta.day(5), deadline=ta.day(9)
    )
    (aim,) = toy_stakes(g, state=state)["aims"]
    assert (aim["opens"], aim["deadline"]) == (ta.day(5).isoformat(), ta.day(9).isoformat())
    assert aim["status"] == "at_risk"
    assert aim["reason"] == f"It is judged from {ta.day(5).day} April 1900."


def test_another_seats_aims_are_absent(tmp_path: Path) -> None:
    g = ta.Game(ta.world(tmp_path))
    g.hand(ta.TOMAS, Controller.HUMAN)
    g.tick()
    assert {g_.person for g_ in g.state.goals.values()} == {ta.ILSE, ta.TOMAS}
    mine, theirs = toy_stakes(g, ta.ILSE), toy_stakes(g, ta.TOMAS)
    assert [a["text"] for a in mine["aims"]] == ["Keep the hills.", "Take the isle."]
    assert [a["text"] for a in theirs["aims"]] == ["Hold the isle."]
    assert "Hold the isle." not in json.dumps(mine)
    assert "Keep the hills." not in json.dumps(theirs)


def test_a_code_seat_is_sent_no_aims(tmp_path: Path) -> None:
    g = ruled(tmp_path, ta.HILLS_HELD, ta.ISLE_HELD)
    seat = ta.seat_of(g.state, ta.ILSE)
    g.hand(ta.ILSE, Controller.AI)
    stakes = seat_stakes(g.state, seat, [])
    assert (stakes["aims"], stakes["degree"]) == ([], None)


def test_a_game_without_aims_sends_none(tmp_path: Path) -> None:
    g = ta.Game(ta.world(tmp_path, ta.aims(on=False)))
    g.tick()
    stakes = toy_stakes(g)
    assert (stakes["aims"], stakes["degree"]) == ([], None)


@pytest.mark.parametrize(
    ("hidden", "status"),
    [
        ({"check": "all_of", "conditions": [ta.HILLS_HELD, HIDDEN_FARMERS]}, "at_risk"),
        ({"check": "any_of", "conditions": [ta.HILLS_HELD, HIDDEN_FARMERS]}, "met"),
        ({"check": "all_of", "conditions": [ta.ISLE_HELD, HIDDEN_FARMERS]}, "at_risk"),
        (HIDDEN_FARMERS, "at_risk"),
    ],
)
def test_two_games_that_differ_only_in_a_hidden_fact_send_the_same_aims(
    tmp_path: Path, hidden: ta.World, status: str
) -> None:
    g = ruled(tmp_path, hidden, ta.HILLS_HELD)
    low, high = with_farmers(g.state, 10), with_farmers(g.state, 90)
    farmers = SupportAt(nation=ta.SUDLAND, group="farmers", op="le", value=20)
    assert goal_met(low, farmers) and not goal_met(high, farmers)
    a, b = toy_stakes(g, state=low), toy_stakes(g, state=high)
    assert a["aims"] == b["aims"] and a["degree"] == b["degree"]
    first = a["aims"][0]
    assert first["status"] == status
    uncertain = [x for x in first["leaves"] if x["seen"] == "uncertain"]
    assert len(uncertain) == 1
    assert uncertain[0]["holds"] is None and uncertain[0]["evidence"] == []
    assert uncertain[0]["reads"] == "support for Farmers in Sudland at most 20"


def test_an_uncertain_aim_says_why(tmp_path: Path) -> None:
    g = ruled(tmp_path, HIDDEN_FARMERS)
    (aim,) = toy_stakes(g)["aims"][:1]
    assert aim["reason"] == "It is uncertain: one of its checks reads what is hidden from you."


@pytest.mark.parametrize(
    ("op", "off", "status"),
    [("ge", -1, "met"), ("ge", 0, "met"), ("ge", 1, "at_risk"),
     ("le", -1, "at_risk"), ("le", 0, "met"), ("le", 1, "met")],
)  # fmt: skip
def test_a_condition_just_below_at_and_just_above_its_threshold(
    tmp_path: Path, op: Literal["ge", "le"], off: int, status: str
) -> None:
    g = ruled(tmp_path, ta.HILLS_HELD)
    now = groups.support(g.state, ta.NORRA, GREENS)
    assert now is not None
    line = SupportAt(nation=ta.NORRA, group=GREENS, op=op, value=now + off)
    state, _ = ta.with_goal(g.state, line)
    assert toy_stakes(g, state=state)["aims"][0]["status"] == status


def test_a_condition_on_its_end_date_and_after(tmp_path: Path) -> None:
    g = ruled(tmp_path, ta.HILLS_HELD)
    now = groups.support(g.state, ta.NORRA, GREENS)
    assert now is not None
    greens = SupportAt(nation=ta.NORRA, group=GREENS, op="ge", value=now)
    state, goal = ta.with_goal(g.state, greens, deadline=TOY_START)
    (aim,) = toy_stakes(g, state=state)["aims"]
    assert (aim["status"], aim["reason"]) == ("met", "It holds now.")
    after = state.model_copy(update={"in_world_date": ta.day(1)})
    kept_goal = after.goals[goal.goal_id].model_copy(update={"holding": True})
    held = after.model_copy(update={"goals": {goal.goal_id: kept_goal}})
    missed = toy_stakes(g, state=after)["aims"][0]
    kept = toy_stakes(g, state=held)["aims"][0]
    assert (missed["status"], kept["status"]) == ("failed", "met")
    assert missed["reason"] == "Its last day, 2 April 1900, passed without it holding."
    assert kept["reason"] == "It held on its last day, 2 April 1900."


def test_a_hidden_aim_past_its_end_date_stays_uncertain(tmp_path: Path) -> None:
    g = ruled(tmp_path, ta.HILLS_HELD)
    farmers = SupportAt(nation=ta.SUDLAND, group="farmers", op="le", value=20)
    state, goal = ta.with_goal(g.state, farmers, deadline=TOY_START)
    card = state.cards[ta.ILSE]
    rule = card.aim_rules[0]
    assert rule is not None
    hidden_rule = rule.model_copy(update={"sees": (Exposure.HIDDEN,)})
    card = card.model_copy(update={"aim_rules": (hidden_rule,)})
    after = state.model_copy(
        update={"cards": {**state.cards, ta.ILSE: card}, "in_world_date": ta.day(1)}
    )
    for holding in (True, False):
        g_ = after.goals[goal.goal_id].model_copy(update={"holding": holding})
        twin = after.model_copy(update={"goals": {goal.goal_id: g_}})
        (aim,) = toy_stakes(g, state=twin)["aims"]
        assert aim["status"] == "at_risk"
        assert aim["leaves"][0]["seen"] == "uncertain"


# --- the degree of the win ------------------------------------------------------------

TRUE_INCOME: ta.World = {"check": "income_at", "nation": "norra", "op": "ge", "value": 0}


@pytest.mark.parametrize(
    ("conditions", "degree"),
    [
        ((ta.ISLE_HELD, sea.SUDLAND_HILLS, sea.SUDLAND_HILLS), None),
        ((ta.HILLS_HELD, sea.SUDLAND_HILLS, ta.ISLE_HELD), None),
        ((ta.HILLS_HELD, sea.THIRD, ta.ISLE_HELD), "win"),
        ((ta.HILLS_HELD, sea.THIRD, TRUE_INCOME), "full win"),
    ],
)
def test_the_degree_at_none_one_two_and_three_of_three(
    tmp_path: Path, conditions: tuple[ta.World, ...], degree: str | None
) -> None:
    g = ruled(tmp_path, *conditions)
    stakes = toy_stakes(g)
    assert len(stakes["aims"]) == 3
    assert stakes["degree"] == degree
    assert "points" not in json.dumps(stakes) and "score" not in stakes


def test_a_card_with_fewer_than_three_aims_wins_but_never_fully(tmp_path: Path) -> None:
    two = ta.aims(ilse=(ta.rule(1, ta.HILLS_HELD), ta.rule(2, sea.THIRD)))
    g = ta.Game(ta.world(tmp_path, two))
    g.tick()
    state = sea.aim_lines(g.state, ta.ILSE, "One.", "Two.")
    assert [a["status"] for a in toy_stakes(g, state=state)["aims"]] == ["met", "met"]
    assert toy_stakes(g, state=state)["degree"] == "win"
    a, _ = (x.goal_id for x in ta.own_goals(state, ta.ILSE))
    lone = sea.aim_lines(state, ta.ILSE, "One.")
    lone = lone.model_copy(update={"goals": {a: lone.goals[a]}})
    assert toy_stakes(g, state=lone)["degree"] == "win"


def test_the_drift_and_the_days_to_the_seasons_end_follow_the_aims(tmp_path: Path) -> None:
    g = ruled(tmp_path, ta.HILLS_HELD)
    state = g.state
    stakes = toy_stakes(g)
    assert list(stakes)[-4:] == ["aims", "degree", "drift", "season_days_left"]
    assert stakes["drift"] == state.divergence
    drifted = state.model_copy(update={"divergence": 7})
    assert toy_stakes(g, state=drifted)["drift"] == 7
    (border,) = state.contests.values()
    assert border.decides is not None and state.in_world_date is not None
    assert stakes["season_days_left"] == (border.decides - state.in_world_date).days


def test_no_contest_no_season_days(tmp_path: Path) -> None:
    def no_contests(w: ta.World) -> None:
        w["rules"] = [r for r in w["rules"] if r != "contests"]

    g = ta.Game(ta.world(tmp_path, ta.aims(), no_contests))
    g.tick()
    assert toy_stakes(g)["season_days_left"] is None


@pytest.mark.parametrize(
    "conditions",
    [
        (ta.HILLS_HELD, sea.THIRD, TRUE_INCOME),
        (ta.HILLS_HELD, sea.THIRD, ta.ISLE_HELD),
        (ta.HILLS_HELD, sea.SUDLAND_HILLS, ta.ISLE_HELD),
    ],
)
def test_at_the_seasons_end_the_degree_crowns_exactly_the_seasons_winners(
    tmp_path: Path, conditions: tuple[ta.World, ...]
) -> None:
    def tomas_holds(w: ta.World) -> None:  # one aim, held from the start
        ta.aims(
            ilse=tuple(ta.rule(i, c) for i, c in enumerate(conditions, start=1)),
            tomas=(ta.rule(1, {**ta.ISLE_HELD, "holder": "sudland"}),),
        )(w)
        w["cards"][0]["aims"] = ["One.", "Two.", "Three."]

    g = ta.Game(ta.world(tmp_path, ta.border, tomas_holds, sea.counting(10)))
    g.hand(ta.TOMAS, Controller.HUMAN)
    won = sea.winners(g)
    state = g.state
    assert state.phase is Phase.SEASON_OVER
    seats = [ta.seat_of(state, p) for p in (ta.ILSE, ta.TOMAS)]
    degrees = {s: seat_stakes(state, s, [])["degree"] for s in seats}
    assert {s for s, d in degrees.items() if d in ("win", "full win")} == won
    assert degrees[ta.seat_of(state, ta.TOMAS)] == "win"  # one aim: a win, never a full win


def test_at_the_seasons_end_each_aim_is_its_stored_record(tmp_path: Path) -> None:
    """Once the season is over an aim's status is the record the winners are read from
    (``Goal.holding``), so the degree matches the winners however the record stands."""
    g = ta.Game(ta.world(tmp_path, ta.border, sea.three(ta.HILLS_HELD, sea.THIRD, ta.ISLE_HELD),
                         sea.counting(10)))  # fmt: skip
    sea.played_to_the_end(g)
    state = g.state
    assert state.phase is Phase.SEASON_OVER
    seat = ta.seat_of(state, ta.ILSE)
    a, b, c = (x.goal_id for x in ta.own_goals(state, ta.ILSE))
    for held, degree in (((), None), ((c,), None), ((a, c), "win"), ((a, b, c), "full win")):
        record = sea.holding(state, *held)
        stakes = seat_stakes(record, seat, [])
        assert [x["status"] == "met" for x in stakes["aims"]] == [k in held for k in (a, b, c)]
        assert stakes["degree"] == degree
        assert (degree is not None) == (seat in season_winners(record))


def test_at_the_seasons_end_a_hidden_check_is_shown_as_public(tmp_path: Path) -> None:
    g = ruled(tmp_path, HIDDEN_FARMERS)
    over = g.state.model_copy(update={"phase": Phase.SEASON_OVER})
    (leaf,) = toy_stakes(g, state=over)["aims"][0]["leaves"]
    assert leaf["seen"] == "public" and leaf["holds"] is not None
