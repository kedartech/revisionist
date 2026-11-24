"""The replacement character: two aims, both required (RPL).

The toy world with posts and aims on: Ilse and Tomas played, Kara (Norra's general) and
Vera Saar (Sudland's admiral) on the roster, Olav a colonel with no post. Ilse holds no
authority of her own and her one confidant, Olav, holds none, so once the chancellery goes
to Olav she can no longer act through anyone, and her seat is offered a replacement at the
next wake opening. Kara's card has three aims, the second replaceable; Vera's has two.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core import roster
from revisionist.core.aim_patterns import OwnAim
from revisionist.core.fold import FoldError, replay
from revisionist.core.goals import AimStatus, Goal, GoalSource, aim_goals, season_winners
from revisionist.core.ids import EntityId, EventId, SeatId
from revisionist.core.ontology import Controller, EntityStatus
from revisionist.core.realism import posts
from revisionist.core.state import State
from revisionist.core.visibility import Scope, private_to
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick, session_zero, wake
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import stakes
from tests.test_adjacency_moves import toy
from tests.test_posts import CHANCELLERY, ILSE, KARA, OLAV, TOMAS, World, command_post, key_id, seat
from tests.test_realism_command import card, general, orders
from tests.test_territory_model import CAMPAIGN

VERA = key_id("vera")
NOW = datetime(2030, 1, 1, 12, tzinfo=UTC)
HILLS: World = {"check": "holds_area", "area": "norra_hills", "holder": "norra"}
ISLE_NORRA: World = {"check": "holds_area", "area": "isle", "holder": "norra"}
ISLE_SUDLAND: World = {"check": "holds_area", "area": "isle", "holder": "sudland"}


def rule(aim: int, condition: World, **more: Any) -> World:
    return {"aim": aim, "rule": f"Aim {aim} holds.", "condition": condition, **more}


def cast(w: World) -> None:
    w["rules"] = [*w["rules"], "holders", "posts", "aims"]
    ilse = card(w, "ilse")
    ilse.pop("authority")
    ilse["inner_circle"] = [{"person": "olav", "channel": "letter"}]
    ilse["aims"] = ["Hold the chancellery.", "Keep the hills."]
    ilse["aim_rules"] = [
        rule(1, {"check": "holds_office", "holder": "ilse", "office": "norra_chancellery"}),
        rule(2, HILLS),
    ]
    tomas = card(w, "tomas")
    tomas["inner_circle"] = [{"person": "vera", "channel": "letter"}]
    tomas["authority"] = [{"name": "the_guard", "effects": ["move_force"]}]
    tomas["aims"] = ["Hold the isle."]
    tomas["aim_rules"] = [rule(1, ISLE_SUDLAND)]
    kara = card(w, "kara")
    kara["aims"] = ["Keep the hills.", "Win the army's war.", "Take the isle."]
    kara["aim_rules"] = [rule(1, HILLS), rule(2, ISLE_NORRA, replaceable=True), rule(3, ISLE_NORRA)]
    w["entities"].append(
        {"key": "vera", "kind": "person", "name": "Vera Saar", "parent": "sudland"}
    )
    w["cards"].append(
        {
            "person": "vera",
            "office": "Admiral of Sudland",
            "playable": True,
            "principals": ["sudland"],
            "horizon_days": 14,
            "inner_circle": [{"person": "tomas", "channel": "letter"}],
            "authority": [{"name": "the_galleys", "effects": ["move_force"]}],
            "aims": ["Hold the isle.", "Keep the coast."],
            "aim_rules": [rule(1, ISLE_SUDLAND), rule(2, ISLE_SUDLAND)],
        }
    )
    w["roster"].append(
        {"entity": "vera", "pitch": "The admiral.", "reach": "The galleys.", "composite": True}
    )


def one_aim(w: World) -> None:
    vera = card(w, "vera")
    vera["aims"] = vera["aims"][:1]
    vera["aim_rules"] = vera["aim_rules"][:1]


class Game:
    """The toy game, Ilse and Tomas played, in an event store."""

    def __init__(self, w: WorldFile) -> None:
        self.store = MemoryStore()
        self.store.append_all(compile_world(w, CAMPAIGN, cmp.versions()))
        for person in (ILSE, TOMAS):
            session_zero.claim(self.store, CAMPAIGN, seat(person), self.state.entities[person].name)
        realism_tick.open_play(self.store, CAMPAIGN)

    @property
    def state(self) -> State:
        return load_state(self.store, CAMPAIGN)

    def tick(self) -> None:
        realism_tick.run_realism_tick(self.store, CAMPAIGN)

    def lose_ilse(self) -> None:
        realism_tick.change_post(self.store, CAMPAIGN, CHANCELLERY, OLAV, posts.PostCause.APPOINTED)

    def open(self) -> None:
        wake.open_wake(self.store, CAMPAIGN, NOW)

    def close(self) -> None:
        wake.close_wake(self.store, CAMPAIGN, NOW + timedelta(days=2), None)

    def take(self, person: EntityId, from_seat: SeatId | None = None) -> SeatId:
        return wake.replace(self.store, CAMPAIGN, from_seat or seat(ILSE), person, NOW)

    def goals_of(self, person: EntityId) -> list[Goal]:
        return sorted(
            (g for g in self.state.goals.values() if g.person == person), key=lambda g: g.aim or 0
        )

    def count(self) -> int:
        return len(list(self.store.read(CAMPAIGN)))


def game(tmp: Path, *changes: Callable[[World], None]) -> Game:
    return Game(toy(tmp, general, orders, command_post, cast, *changes))


def replaced(tmp: Path) -> Game:
    """Ilse lost, Kara taken in her place, the wake closed and a tick run."""
    g = game(tmp)
    g.tick()
    g.lose_ilse()
    g.open()
    g.take(KARA)
    g.close()
    g.tick()
    return g


def fold(state: State, payload: ev.Payload, scope: Scope) -> State:
    event = ev.Event(
        event_id=EventId(f"01ARZ3NDEKTSV4RRFFQ69{state.last_seq + 1:05d}"),
        campaign_id=state.campaign_id,
        seq=state.last_seq + 1,
        tick=state.tick,
        scope=scope,
        payload=payload,
        versions=cmp.versions(),
    )
    return replay([event], initial=state)


def dead(state: State, person: EntityId) -> State:
    gone = state.entities[person].model_copy(update={"status": EntityStatus.DEAD})
    return state.model_copy(update={"entities": {**state.entities, person: gone}})


def aim_goals_of(state: State, person: EntityId) -> list[Goal]:
    return [e.goal for e in aim_goals(state) if e.goal.person == person]


def holding(state: State, person: EntityId, *aims: int) -> State:
    goals = {
        gid: g.model_copy(update={"holding": g.aim in aims}) if g.person == person else g
        for gid, g in state.goals.items()
    }
    return state.model_copy(update={"goals": goals})


# --- rule 1: the offer ------------------------------------------------------------------


def test_a_person_who_can_still_act_is_offered_no_replacement(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    assert wake.replacements(g.state, seat(ILSE)) == ()


def test_a_lost_person_is_offered_the_claimable_people_his_own_nation_first(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.lose_ilse()
    assert posts.needs_replacement(g.state, ILSE)
    assert wake.replacements(g.state, seat(ILSE)) == ()
    g.open()
    assert [c.person for c in wake.replacements(g.state, seat(ILSE))] == [KARA, VERA]


def test_his_own_nation_comes_first_whatever_the_names(tmp_path: Path) -> None:
    def rename(w: World) -> None:
        next(e for e in w["entities"] if e["key"] == "kara")["name"] = "Zara Lind"

    g = game(tmp_path, rename)
    g.lose_ilse()
    g.open()
    assert [c.person for c in wake.replacements(g.state, seat(ILSE))] == [KARA, VERA]


def test_a_dead_person_is_offered_a_replacement(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    offer = wake.replacements(dead(g.state, ILSE), seat(ILSE))
    assert [c.person for c in offer] == [KARA, VERA]


def test_no_offer_with_posts_off(tmp_path: Path) -> None:
    def off(w: World) -> None:
        w["rules"] = [r for r in w["rules"] if r != "posts"]
        for c in w["cards"]:
            c.pop("post", None)
            c.pop("successor", None)

    g = game(tmp_path, off)
    g.open()
    assert wake.replacements(dead(g.state, ILSE), seat(ILSE)) == ()


def test_a_person_without_two_aims_to_hold_is_not_offered(tmp_path: Path) -> None:
    g = game(tmp_path, one_aim)
    g.lose_ilse()
    g.open()
    assert [c.person for c in wake.replacements(g.state, seat(ILSE))] == [KARA]


# --- rule 2: the claim ------------------------------------------------------------------


def test_the_claim_hands_the_old_person_to_the_code_in_the_same_step(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.lose_ilse()
    g.open()
    before = g.count()
    new = g.take(KARA)
    state = g.state
    assert state.handovers == {ILSE: Controller.AI, KARA: Controller.HUMAN}
    assert state.replaced == {KARA: ILSE}
    assert g.count() >= before + 2
    g.close()
    state = g.state
    assert state.seats[seat(ILSE)].controller is Controller.AI
    assert state.seats[new].embodies == KARA
    assert state.seats[new].controller is Controller.HUMAN


def test_a_person_not_on_the_offer_cannot_be_taken(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.lose_ilse()
    g.open()
    with pytest.raises(ValueError, match="cannot be taken"):
        g.take(TOMAS)
    with pytest.raises(ValueError, match="cannot be taken"):
        g.take(KARA, from_seat=seat(TOMAS))


def test_the_seat_cap_holds_with_every_seat_taken(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = g.state
    full = state.model_copy(
        update={"settings": state.settings.model_copy(update={"max_human_seats": 2})}
    )
    assert wake.leaders(full) == []
    g.lose_ilse()
    g.open()
    g.take(KARA)
    g.close()
    played = [s.embodies for s in g.state.seats.values() if s.controller is Controller.HUMAN]
    assert sorted(played) == sorted([KARA, TOMAS])


def test_the_fold_refuses_a_replacement_before_the_old_person_goes_to_the_code(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.lose_ilse()
    g.open()
    take = ev.SeatHandover(entity_id=KARA, controller=Controller.HUMAN, replaces=ILSE)
    with pytest.raises(FoldError, match="replaces"):
        fold(g.state, take, private_to(seat(KARA)))


def test_the_fold_refuses_a_replacement_for_a_person_who_can_act(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.open()
    state = fold(
        g.state, ev.SeatHandover(entity_id=ILSE, controller=Controller.AI), private_to(seat(ILSE))
    )
    take = ev.SeatHandover(entity_id=KARA, controller=Controller.HUMAN, replaces=ILSE)
    with pytest.raises(FoldError, match="replaces"):
        fold(state, take, private_to(seat(KARA)))


def test_the_fold_refuses_a_replacement_without_two_aims_to_hold(tmp_path: Path) -> None:
    g = game(tmp_path, one_aim)
    g.lose_ilse()
    g.open()
    state = fold(
        g.state, ev.SeatHandover(entity_id=ILSE, controller=Controller.AI), private_to(seat(ILSE))
    )
    take = ev.SeatHandover(entity_id=VERA, controller=Controller.HUMAN, replaces=ILSE)
    with pytest.raises(FoldError, match="two aims"):
        fold(state, take, private_to(seat(VERA)))


def test_a_refused_claim_stores_neither_half(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = game(tmp_path, one_aim)
    g.lose_ilse()
    g.open()
    before = g.count()
    monkeypatch.setattr(roster, "replacements", lambda state, person: roster.claimable(state))
    with pytest.raises(FoldError):
        g.take(VERA)
    assert g.count() == before


def test_the_hand_overs_are_sealed_to_the_seats_that_change_hands(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.lose_ilse()
    g.open()
    new = g.take(KARA)
    found = [e.scope for e in g.store.read(CAMPAIGN) if isinstance(e.payload, ev.SeatHandover)]
    assert found == [private_to(seat(ILSE)), private_to(new)]


# --- rule 3: two goals with the source replacement --------------------------------------


def test_the_replacement_has_two_goals_from_his_aims_that_are_not_replaceable(
    tmp_path: Path,
) -> None:
    g = replaced(tmp_path)
    made = g.goals_of(KARA)
    assert [(x.aim, x.source) for x in made] == [
        (1, GoalSource.REPLACEMENT),
        (3, GoalSource.REPLACEMENT),
    ]
    assert all(x.scope == private_to(seat(KARA)) for x in made)


def test_the_replacement_sets_no_aim_of_his_own(tmp_path: Path) -> None:
    g = replaced(tmp_path)
    state = g.state
    rule2 = state.cards[KARA].aim_rules[1]
    assert rule2 is not None
    own = OwnAim(
        person=KARA, key="take_ground", values={}, text="Mine.", rule=rule2, government=False, aim=2
    )
    stored = state.model_copy(update={"own_aims": {KARA: own}, "goals": {}})
    assert [x.source for x in aim_goals_of(stored, KARA)] == [GoalSource.REPLACEMENT] * 2


def test_the_fold_refuses_a_replacement_goal_on_the_replaceable_aim(tmp_path: Path) -> None:
    g = replaced(tmp_path)
    state = g.state
    rules = state.cards[KARA].aim_rules
    first = g.goals_of(KARA)[0]
    wrong = first.model_copy(
        update={"goal_id": "01ARZ3NDEKTSV4RRFFQ69WRONG", "aim": 2, "condition": rules[1].condition}  # type: ignore[union-attr]
    )
    state = state.model_copy(update={"goals": {k: v for k, v in state.goals.items() if v.aim != 2}})
    with pytest.raises(FoldError, match="replacement"):
        fold(state, ev.GoalSet(goal=wrong), private_to(seat(KARA)))


def test_the_fold_refuses_a_post_goal_for_a_replacement(tmp_path: Path) -> None:
    g = replaced(tmp_path)
    state = g.state
    goal = g.goals_of(KARA)[0]
    state = state.model_copy(
        update={"goals": {k: v for k, v in state.goals.items() if k != goal.goal_id}}
    )
    with pytest.raises(FoldError, match="replacement"):
        fold(
            state, ev.GoalSet(goal=goal.model_copy(update={"source": GoalSource.POST})), goal.scope
        )


def test_the_goals_are_fed_to_their_own_seat_and_the_hand_over_never(tmp_path: Path) -> None:
    g = replaced(tmp_path)
    w = g.state.wake
    assert w is not None
    mine = catchup.seat_events(g.store, CAMPAIGN, seat(KARA), 0, w.number + 1)
    kinds = [e.event.kind for e in mine]
    assert kinds.count("goal_set") == 2
    assert "seat_handover" not in kinds
    theirs = catchup.seat_events(g.store, CAMPAIGN, seat(TOMAS), 0, w.number + 1)
    assert not any(
        isinstance(e.event.payload, ev.GoalSet) and e.event.payload.goal.person == KARA
        for e in theirs
    )


# --- rule 4: both holding, a win and never a full win -----------------------------------


def test_the_season_counts_the_replacement_a_winner_only_with_both_holding(tmp_path: Path) -> None:
    g = replaced(tmp_path)
    state = g.state
    assert seat(KARA) not in season_winners(holding(state, KARA))
    assert seat(KARA) not in season_winners(holding(state, KARA, 1))
    assert seat(KARA) not in season_winners(holding(state, KARA, 3))
    assert seat(KARA) in season_winners(holding(state, KARA, 1, 3))


def test_the_degree_is_a_win_never_a_full_win(tmp_path: Path) -> None:
    g = replaced(tmp_path)
    met = [{"status": AimStatus.MET.value} for _ in g.goals_of(KARA)]
    assert stakes.degree(g.state, seat(KARA), met) == stakes.WIN  # type: ignore[arg-type]


# --- rule 5: the old goals as they stood, counting for no seat ---------------------------


def test_the_old_goals_are_unchanged_afterwards(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.tick()
    g.lose_ilse()
    g.tick()
    before = g.goals_of(ILSE)
    assert [x.source for x in before] == [GoalSource.POST, GoalSource.POST]
    assert not before[0].holding  # the chancellery is Olav's
    g.open()
    g.take(KARA)
    g.close()
    g.tick()
    realism_tick.change_post(g.store, CAMPAIGN, CHANCELLERY, ILSE, posts.PostCause.APPOINTED)
    g.tick()
    assert g.goals_of(ILSE) == before


def test_the_old_goals_count_for_no_seat_even_if_a_player_takes_him_again(tmp_path: Path) -> None:
    g = replaced(tmp_path)
    state = holding(g.state, ILSE, 1, 2)
    again = state.seats[seat(ILSE)].model_copy(update={"controller": Controller.HUMAN})
    state = state.model_copy(update={"seats": {**state.seats, seat(ILSE): again}})
    assert seat(ILSE) not in season_winners(state)


# --- rule 6: once a season --------------------------------------------------------------


def test_a_replacement_is_offered_no_second_replacement(tmp_path: Path) -> None:
    g = replaced(tmp_path)
    g.open()
    state = dead(g.state, KARA)
    assert posts.needs_replacement(state, KARA)
    assert wake.replacements(state, seat(KARA)) == ()


def test_the_fold_refuses_a_second_replacement(tmp_path: Path) -> None:
    g = replaced(tmp_path)
    g.open()
    state = fold(
        g.state, ev.SeatHandover(entity_id=KARA, controller=Controller.AI), private_to(seat(KARA))
    )
    take = ev.SeatHandover(entity_id=VERA, controller=Controller.HUMAN, replaces=KARA)
    with pytest.raises(FoldError, match="once a season"):
        fold(dead(state, KARA), take, private_to(seat(VERA)))


# --- the event --------------------------------------------------------------------------


def test_a_hand_over_without_a_replacement_dumps_as_before() -> None:
    assert (
        "replaces" not in ev.SeatHandover(entity_id=ILSE, controller=Controller.HUMAN).model_dump()
    )


def test_a_game_mid_replacement_loads_the_same(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.lose_ilse()
    g.open()
    g.take(KARA)
    assert load_state(g.store, CAMPAIGN) == g.state
