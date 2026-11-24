"""The commanders' games (NPG): a scripted 1941 proof for each nation with a military seat.

For each of the eight nations a game opens through the opening's three answers, claims the
commander, and files the order his nation's lock holds: it is held, he asks, and the lock
opens the way that nation decides (``tests/commanders_script.py``). With the decider
played he allows it: by setting the posture the row waits on, or by granting the matter.
With the decider run by code his card answers the ask on its due day; the campaign id
pins a granted case (``GRANTS``) and a declined one (``CAMPAIGN``). Japan's council grants
with one member human and silent. One commander sets an own aim from a pattern and the
season scores it. Each game run twice gives one digest, and so does one with a restart and
a retry in the middle; a twin world per nation shows the lock's reason carries no fact
outside the commander's view; the aide for an absent commander files nothing held and
asks for nothing.

Britain's Commons row (``home_fleet_based_at_iceland``) opens when the National Service
law is in force: the played Prime Minister puts the bill to the House, the blocs vote on
the day it settles, and the order lands once they pass it.
"""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.goals import AimStatus, Goal, aim_status
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.ontology import Controller
from revisionist.core.project import project
from revisionist.core.realism import locks
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.card import CardPath
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.process import ANSWER_DAYS
from revisionist.core.realism.quantity import Quantity
from revisionist.core.realism.war import NewsTopic, polity_of
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from tests.commanders_script import BY_KEY, NATIONS, PLAY, Game, Nation, Script, world_1941
from tests.locked_orders_script import CAMPAIGN, World, digest

GRANTS = CampaignId("MF4TEAMZ5820R9Z38F7VFR0N1B")
"""A campaign whose seed has every code-run decider grant (``CAMPAIGN`` has each decline)."""

each_nation = pytest.mark.parametrize("nation", NATIONS, ids=[n.key for n in NATIONS])
single = [n for n in NATIONS if not n.council]
each_single = pytest.mark.parametrize("nation", single, ids=[n.key for n in single])

POSTURE_REFUSED = {"germany"}
"""Nations whose code-run decider grants but whose posture form is refused at filing, so
the lock stays held: Hitler's U-boat directive against American ships needs Germany at war
with the United States first."""


SILENT = frozenset({"character_claimed", "play_style_set", "options_offered", "wake_committed"})
"""All a silent seated member logs: his claim, the options the wake puts to him, and his
wake. Nothing he chooses on the matter."""


def _played(
    nation: Nation,
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: Script = PLAY,
    campaign: CampaignId = GRANTS,
    world: WorldFile | None = None,
) -> Game:
    g = Game(
        nation, tmp, monkeypatch, campaign=campaign, head_played=script.head_played, world=world
    )
    return g.play(script)


def _own_goals(state: State, person: EntityId) -> list[Goal]:
    return sorted((g for g in state.goals.values() if g.person == person), key=lambda g: g.aim or 0)


def _halved(key: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        q = next(q for q in w["quantities"] if q["key"] == key)
        q["value"] = q["value"] // 2

    return change


# --- rule 1: the opening, the claim, the held order and the ask -----------------------


@each_nation
def test_each_game_opens_through_the_three_answers_and_claims_the_commander(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nation: Nation
) -> None:
    g = Game(nation, tmp_path, monkeypatch)
    key, path, name = g.picked
    state = g.state
    assert key == polity_of(state, g.entity(nation.commander))
    assert path == CardPath.MILITARY
    assert state.seats[g.commander].embodies == g.entity(nation.commander)
    assert state.entities[g.entity(nation.commander)].name == name


@each_nation
def test_each_commanders_order_is_held_by_his_nations_row_and_he_asks_its_decider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nation: Nation
) -> None:
    g = Game(nation, tmp_path, monkeypatch)
    g._tick(None)
    g.played.held = g.file(g.commander, nation.order, "commander:held")
    held = g.state.held[g.played.held]
    assert held.row == nation.row
    asked = g.ask("commander:ask")
    assert asked.to == g.entity(nation.head)
    if nation.council:
        assert g.seat(nation.seated_head) in asked.seats
    else:
        assert asked.seats == ()
    with pytest.raises(ValueError, match=locks.ASKED_ALREADY):
        g.ask("commander:ask-again")


# --- rule 2: the head played allows it -------------------------------------------------


@each_single
def test_with_the_head_played_he_allows_it_and_the_order_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nation: Nation
) -> None:
    g = _played(nation, tmp_path, monkeypatch, campaign=CAMPAIGN)
    (end,) = g.ends()
    assert end.end is locks.HeldEnd.LANDED
    assert g.landed() in g.state.orders
    if nation.allow:
        assert len(g.played.allowed) == len(nation.allow)
        assert g.played.chose is None  # the posture opened it; nobody chose on the matter
    else:
        assert g.played.chose is not None
    assert not g.logged(ev.AskAnswered) or nation.allow == ()


@each_single
def test_with_the_head_played_and_silent_nothing_opens_before_the_due_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nation: Nation
) -> None:
    g = Game(nation, tmp_path, monkeypatch, campaign=GRANTS)
    g.play(Script(allows=False))
    asked = g.played.asked
    assert asked is not None and g.head is not None
    assert g.state.seats[g.head].controller is Controller.HUMAN
    due = asked.on + timedelta(days=ANSWER_DAYS)
    assert all(a.on >= due for a in g.logged(ev.AskAnswered))
    assert all(e.on >= due for e in g.ends())


# --- rule 3: the head run by code answers on the due day ------------------------------


@each_single
@pytest.mark.parametrize("campaign", [GRANTS, CAMPAIGN], ids=["granted", "declined"])
def test_with_the_head_run_by_code_his_card_answers_on_the_due_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nation: Nation, campaign: CampaignId
) -> None:
    g = _played(nation, tmp_path, monkeypatch, Script(head_played=False), campaign)
    asked = g.played.asked
    assert asked is not None and asked.seat is not None
    assert g.state.seats[asked.seat].controller is Controller.AI
    (answer,) = [a for a in g.logged(ev.AskAnswered) if a.order_id == g.played.held]
    assert answer.on >= asked.on + timedelta(days=ANSWER_DAYS)
    ticks = [e.to for e in g.logged(ev.DateAdvanced)]
    assert not [d for d in ticks if asked.on + timedelta(days=ANSWER_DAYS) <= d < answer.on]
    granted = campaign == GRANTS
    assert answer.granted is granted
    if granted and nation.key not in POSTURE_REFUSED:
        (end,) = g.ends()
        assert end.end is locks.HeldEnd.LANDED
    else:
        assert not g.ends()
        assert g.played.held in g.state.held


# --- rule 4: Japan's council -----------------------------------------------------------


def test_japans_council_grants_with_one_member_human_and_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    japan = BY_KEY["japan"]
    g = _played(japan, tmp_path, monkeypatch)
    assert g.head == g.seat("tojo")
    asked = g.played.asked
    assert asked is not None and g.seat("tojo") in asked.seats
    assert g.state.seats[g.head].controller is Controller.HUMAN
    acts = {e.payload.kind for e in g.events() if e.actor == g.head}
    assert acts <= SILENT, acts
    (end,) = g.ends()
    assert end.end is locks.HeldEnd.LANDED


def test_japans_council_declines_on_a_seed_where_its_cards_do_not_agree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = _played(BY_KEY["japan"], tmp_path, monkeypatch, campaign=CAMPAIGN)
    assert [a.granted for a in g.logged(ev.AskAnswered)] == [False]
    assert not g.ends()


# --- rule 5: Britain's Commons ---------------------------------------------------------


COMMONS_VOTING = 330 + 120 + 22
"""The members the three Commons blocs' rows put to vote on the National Service bill."""


def _commons_yeas(bloc: str, yeas: int) -> Callable[[World], None]:
    def change(w: World) -> None:
        (uk,) = [n for n in w["groups"] if n["nation"] == "uk"]
        (row,) = [b for b in uk["groups"] if b["key"] == bloc]
        row["votes"]["national_service"]["commons"]["yeas"] = yeas

    return change


def _quantity(state: State, key: str) -> Quantity:
    return state.quantities[rs.qid(state, key)]


def test_britains_commons_vote_resolves_on_its_date_from_the_blocs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = _played(BY_KEY["uk_commons"], tmp_path, monkeypatch, campaign=CAMPAIGN)
    state = g.state
    (bill,) = [state.orders[o] for o in g.played.allowed]
    assert bill.status is OrderStatus.ENACTED
    day = rs.settled_on(bill)
    yeas = _quantity(state, "national_service_commons_yeas")
    nays = _quantity(state, "national_service_commons_nays")
    passed = _quantity(state, "national_service_passed")
    assert yeas.as_of == nays.as_of == passed.as_of == day
    assert yeas.value is not None and nays.value is not None
    assert yeas.value + nays.value == COMMONS_VOTING
    assert yeas.value > nays.value and passed.value == 1
    (end,) = g.ends()
    assert end.end is locks.HeldEnd.LANDED and end.on >= day
    assert [n for n in state.news.values() if n.topic is NewsTopic.VOTE and n.on == day]


def test_britains_commons_vote_lost_on_its_blocs_leaves_the_order_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = world_1941((_commons_yeas("commons_government", 100),))
    g = Game(BY_KEY["uk_commons"], tmp_path, monkeypatch, campaign=CAMPAIGN, world=world)
    g.play(Script(to_season_end=True))
    state = g.state
    (bill,) = [state.orders[o] for o in g.played.allowed]
    assert bill.status is OrderStatus.ENACTED
    assert _quantity(state, "national_service_passed").value == 0
    assert not g.ends()
    assert g.played.held in state.held


# --- rule 6: an own aim the season scores ---------------------------------------------


def test_a_commander_sets_an_own_aim_from_a_pattern_and_the_season_scores_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    germany = BY_KEY["germany"]
    g = Game(germany, tmp_path, monkeypatch, campaign=CAMPAIGN)
    usa = g.entity("usa")
    g.play(Script(own_aim=("war_with", {"foe": usa}), to_season_end=True))
    (own,) = g.logged(ev.OwnAimSet)
    assert own.own.key == "war_with" and own.own.values == {"foe": usa}
    state = g.state
    goal = _own_goals(state, g.entity(germany.commander))[own.own.aim - 1]
    assert goal.text == own.own.text
    assert aim_status(state, goal) is AimStatus.MET
    assert goal.goal_id in {e.goal_id for e in g.logged(ev.GoalMet)}
    assert g.logged(ev.SeasonEnded)


# --- determinism: twice, a restart, a retry ---------------------------------------------


@each_nation
def test_each_nations_game_run_twice_gives_one_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nation: Nation
) -> None:
    a = _played(nation, tmp_path / "a", monkeypatch)
    b = _played(nation, tmp_path / "b", monkeypatch)
    assert a.ends() or nation.key in POSTURE_REFUSED
    assert digest(a.state) == digest(b.state)


@each_nation
def test_a_restart_and_a_retry_mid_game_give_the_same_digest_and_one_unlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nation: Nation
) -> None:
    full = _played(nation, tmp_path / "full", monkeypatch)
    g = _played(nation, tmp_path / "restart", monkeypatch, Script(restart_at=0, retry_at=0))
    assert digest(g.state) == digest(full.state)
    assert locks.ASKED_ALREADY in g.played.refused_retries
    assert len([e for e in g.logged(ev.OrderAsked) if e.asked.order_id == g.played.held]) == 1
    assert len(g.ends()) == 1


# --- the commander's view: twin worlds -------------------------------------------------


@each_nation
def test_a_lock_reason_carries_no_fact_outside_the_commanders_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nation: Nation
) -> None:
    """Two games differing only in a figure the commander cannot see: his order is held
    with the same reason, the ask reads the same, and his whole view is the same."""
    hidden = _halved("uk_sealift_grt" if nation.key == "japan" else "japan_sealift_grt")
    seen = []
    for twin, changes in (("a", ()), ("b", (hidden,))):
        g = Game(nation, tmp_path / twin, monkeypatch, world=world_1941(changes))
        g._tick(None)
        g.played.held = g.file(g.commander, nation.order, "commander:held")
        asked = g.ask("commander:ask")
        state = g.state
        seen.append(
            (
                state.held[g.played.held].reason,
                asked.words,
                project(state, g.commander).model_dump(mode="json"),
                digest(state),
            )
        )
    (reason_a, words_a, view_a, world_a), (reason_b, words_b, view_b, world_b) = seen
    assert world_a != world_b  # the hidden figure differs in the world
    assert reason_a == reason_b and words_a == words_b
    assert view_a == view_b


# --- the aide -------------------------------------------------------------------------


@each_nation
def test_the_aide_for_an_absent_commander_files_no_held_order_and_makes_no_ask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nation: Nation
) -> None:
    g = Game(nation, tmp_path, monkeypatch)
    g.script = Script(commander_present=False)
    g._tick(None)
    for _ in range(3):
        g.close()
    state = g.state
    assert not [h for h, held in state.held.items() if state.orders[h].issuer == g.commander]
    assert not [a for a in g.logged(ev.OrderAsked) if a.asked.asker == g.commander]
    assert not state.asked
