"""The player's own aim: patterns, the check and the stored aim (OWC).

The toy world (``tests/worlds/territory-toy.yaml``) declares aim patterns, each a key, the
kinds of post it suits, a sentence with named blanks, a condition over the checks aims use
with the same blanks, the values each blank may take, and whether the person's own
government would issue it. Here it is played with ``aims`` and ``own_aim`` on. Ilse of
Norra, head of government, has three aims with rules, the third replaceable; Tomas of
Sudland has one aim and none replaceable. A player fills a pattern from his seat's view
only; the filled aim replaces the card's replaceable aim, once per person, before the
first wake his player plays has closed.
"""

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import aim_patterns
from revisionist.core import events as ev
from revisionist.core.aim_patterns import AimPatterns, Filled, OwnAim, Refused
from revisionist.core.fold import FoldError, state_hash
from revisionist.core.goals import (
    AimStatus,
    AtWar,
    ContestWon,
    Exposure,
    GoalSource,
    HoldsArea,
    SupportAt,
    aim_goals,
    aim_rule,
    aim_status,
    check,
    difficulty,
    season_winners,
)
from revisionist.core.ids import EntityId, SeatId, derived_id
from revisionist.core.ontology import Controller
from revisionist.core.project import project
from revisionist.core.realism.holders import Holding
from revisionist.core.state import Rule, State
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick, session_zero
from revisionist.engine.store import MemoryStore, SqliteStore, load_state
from tests.test_adjacency_moves import fold, toy
from tests.test_realism_aims import (
    BORDER,
    DEADLINE,
    HILLS,
    HILLS_HELD,
    ILSE,
    ISLE,
    NORRA,
    SUDLAND,
    TOMAS,
    Game,
    World,
    border,
    key_id,
    own_goals,
    rule,
    seat_of,
)
from tests.test_territory_model import CAMPAIGN, refused

RULES = ("territories", "holders", "agreements", "groups", "contests", "aims", "own_aim")
COAST = EntityId(key_id("sudland_coast"))
PLAIN = EntityId(key_id("norra_plain"))
PLAIN_HELD: World = {"check": "holds_area", "area": "norra_plain", "holder": "norra"}
WON: World = {"check": "contest_won", "contest": "border", "side": "norra"}
THIRD_DEADLINE = date(1900, 9, 1)


def setup(on: bool = True, ilse_rules: tuple[World, ...] | None = None) -> Callable[[World], None]:
    """Both rules (``own_aim`` unless ``on`` is false), Ilse's three aims with the third
    replaceable, Tomas's one aim with none."""

    def change(w: World) -> None:
        w["rules"] = list(RULES if on else RULES[:-1])
        w["cards"][0]["aims"] = ["Keep the hills.", "Win the border war.", "Hold the plain."]
        w["cards"][0]["aim_rules"] = list(
            ilse_rules
            or (
                rule(1, HILLS_HELD),
                rule(2, WON),
                rule(3, PLAIN_HELD, replaceable=True, deadline=THIRD_DEADLINE.isoformat()),
            )
        )
        w["cards"][1]["aims"] = ["Hold the isle."]
        w["cards"][1]["aim_rules"] = [
            rule(1, {"check": "holds_area", "area": "isle", "holder": "sudland"})
        ]

    return change


def pattern(**fields: Any) -> Callable[[World], None]:
    """One more aim pattern in the world."""

    def change(w: World) -> None:
        w["aim_patterns"] = [*w.get("aim_patterns", []), fields]

    return change


FOREIGN_MOOD = pattern(
    key="foreign_mood",
    posts=["political"],
    sentence="Bring {group} of Sudland down to {line}.",
    condition={"check": "support_at", "nation": "sudland", "group": "$group", "op": "le",
               "value": "$line"},
    blanks=[{"name": "group", "values": ["farmers"]}, {"name": "line", "values": [40]}],
)  # fmt: skip
WIN_WAR = pattern(
    key="win_war",
    posts=["political"],
    sentence="Win {contest}.",
    condition={"check": "contest_won", "contest": "$contest", "side": "$nation"},
    blanks=[{"name": "contest", "values": ["border"]}],
)


def world(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    return toy(tmp, border, *(changes or (setup(),)))


def game(tmp: Path, *changes: Callable[[World], None], people: tuple[EntityId, ...] = ()) -> Game:
    """The game with each of ``people`` (Ilse alone by default) held by a player, ticked once."""
    tmp.mkdir(parents=True, exist_ok=True)
    g = Game.__new__(Game)
    g.store = MemoryStore()
    g.store.append_all(compile_world(world(tmp, *changes), CAMPAIGN, cmp.versions()))
    for person in people or (ILSE,):
        name = g.state.entities[person].name
        session_zero.claim(g.store, CAMPAIGN, SeatId(derived_id(CAMPAIGN, "seat", person)), name)
    realism_tick.open_play(g.store, CAMPAIGN)
    g.tick()
    return g


@pytest.fixture
def played(tmp_path: Path) -> Game:
    return game(tmp_path)


def ilse_seat(state: State) -> SeatId:
    return seat_of(state, ILSE)


def filled(state: State, key: str, **values: str | int) -> Filled:
    out = aim_patterns.fill(state, ilse_seat(state), key, values)
    assert isinstance(out, Filled), out
    return out


def reasons(state: State, key: str, seat: SeatId | None = None, **values: str | int) -> set[str]:
    out = aim_patterns.fill(state, seat or ilse_seat(state), key, values)
    assert isinstance(out, Refused), out
    return set(out.reasons)


def set_aim(g: Game, key: str, **values: str | int) -> None:
    out = realism_tick.set_own_aim(g.store, CAMPAIGN, ilse_seat(g.state), key, values)
    assert isinstance(out, OwnAim), out


def close_wake(g: Game) -> None:
    w = g.state.wake
    n = 0 if w is None else w.number + 1
    g.land(ev.WakeOpened(wake=n, deadline=DEADLINE))
    g.land(ev.WakeClosed(wake=n))


def take(state: State, area: EntityId, holder: EntityId) -> State:
    today = state.in_world_date
    assert today is not None
    held = {**state.holders, area: Holding(holder=holder, on=today)}
    return state.model_copy(update={"holders": held})


# --- rule 1: the world's patterns reach state once, public -----------------------------


def test_the_patterns_reach_state_once_by_a_public_event(played: Game) -> None:
    (declared,) = [e for e in played.store.read(CAMPAIGN) if e.kind == "aim_patterns_declared"]
    assert declared.scope == PUBLIC
    assert isinstance(declared.payload, ev.AimPatternsDeclared)
    patterns = played.state.aim_patterns
    assert isinstance(patterns, AimPatterns)
    keys = [p.key for p in patterns.patterns]
    assert keys == ["take_ground", "keep_support", "make_peace", "hold_the_line"]
    hold = patterns.patterns[3]
    (place,) = hold.blanks
    assert place.values == (key_id("norra_hills"), key_id("sudland_coast"))  # bound to ids
    assert hold.condition["area"] == "$place" and hold.condition["holder"] == "$nation"
    assert patterns.posts == {ILSE: "head_of_government"}
    assert [p.government for p in patterns.patterns] == [True, False, False, True]


def test_with_the_rule_off_the_patterns_are_checked_and_left_out(tmp_path: Path) -> None:
    g = game(tmp_path, setup(on=False))
    assert g.state.aim_patterns is None
    assert "aim_patterns_declared" not in [e.kind for e in g.store.read(CAMPAIGN)]
    out = aim_patterns.fill(g.state, ilse_seat(g.state), "take_ground", {"place": "isle"})
    assert out == Refused(reasons=(aim_patterns.OFF,))


def test_the_compiler_refuses_a_pattern_the_rules_cannot_check(tmp_path: Path) -> None:
    bad = (
        pattern(key="take_ground", posts=["political"], sentence="Again {place}.",
                condition={"check": "holds_area", "area": "$place", "holder": "$nation"},
                blanks=[{"name": "place", "kind": "territory_not_held"}]),
        pattern(key="loose", posts=["political"], sentence="Take {place}.",
                condition={"check": "holds_area", "area": "$where", "holder": "$nation"},
                blanks=[{"name": "place", "values": ["isle"]}]),
        pattern(key="nowhere", posts=["political"], sentence="Take {place}.",
                condition={"check": "holds_area", "area": "$place", "holder": "$nation"},
                blanks=[{"name": "place", "values": ["nowhere"]}]),
        pattern(key="unsaid", posts=["political"], sentence="Take it.",
                condition={"check": "holds_area", "area": "$place", "holder": "$nation"},
                blanks=[{"name": "place", "values": ["isle"]}]),
        pattern(key="wrong_kind", posts=["political"], sentence="Win {place}.",
                condition={"check": "contest_won", "contest": "$place", "side": "$nation"},
                blanks=[{"name": "place", "kind": "territory_not_held"}]),
        pattern(key="nocheck", posts=["political"], sentence="Do {x}.",
                condition={"check": "holds_nothing", "area": "$x"},
                blanks=[{"name": "x", "values": ["isle"]}]),
    )  # fmt: skip
    problems = refused(world(tmp_path, setup(), *bad))
    assert "aim pattern take_ground: duplicate key" in problems
    assert "aim pattern loose: blank $where is not declared" in problems
    assert "aim pattern loose: blank place is not in the condition" in problems
    assert "aim pattern nowhere: unknown entity nowhere" in problems
    assert "aim pattern unsaid: blank place is not in the sentence" in problems
    assert "aim pattern wrong_kind: blank place: a territory_not_held cannot stand for contest" in (
        problems
    )
    checked = "aim pattern nocheck: not a condition the rules check"
    assert any(p.startswith(checked) for p in problems)


def test_a_blank_has_either_a_list_or_a_kind(tmp_path: Path) -> None:
    blank = {"name": "place", "values": ["isle"], "kind": "territory_not_held"}
    both = pattern(key="both", posts=["political"], sentence="Take {place}.",
                   condition={"check": "holds_area", "area": "$place", "holder": "$nation"},
                   blanks=[blank])  # fmt: skip
    with pytest.raises(ValueError, match="a blank has a list of values or a kind"):
        world(tmp_path, setup(), both)


def test_the_fold_takes_the_patterns_once_and_only_with_the_rule(played: Game) -> None:
    (declared,) = [e for e in played.store.read(CAMPAIGN) if e.kind == "aim_patterns_declared"]
    with pytest.raises(FoldError, match="declared once"):
        fold(played.state, [declared.payload])
    off = played.state.model_copy(
        update={"rules": played.state.rules - {Rule.OWN_AIM}, "aim_patterns": None}
    )
    with pytest.raises(FoldError, match="needs the own_aim rule"):
        fold(off, [declared.payload])


# --- rule 2: fill, from the seat's own view ---------------------------------------------


def test_a_filled_pattern_gives_its_sentence_condition_period_and_who_sees_each_leaf(
    played: Game,
) -> None:
    out = filled(played.state, "take_ground", place=ISLE)
    assert out.text == "Take The Isle for Norra."
    assert out.rule.condition == HoldsArea(area=ISLE, holder=NORRA)
    assert out.rule.rule == out.text
    assert out.rule.deadline == THIRD_DEADLINE  # the replaced aim's period
    assert out.rule.sees == (Exposure.PUBLIC,)
    assert out.aim == 3 and out.key == "take_ground" and out.government
    assert out.values == {"place": ISLE}


def test_a_value_outside_the_blanks_list_is_refused(played: Game) -> None:
    state = played.state
    assert reasons(state, "take_ground", place=HILLS) == {
        "place: The Norra Hills is not a value this blank takes."
    }  # Norra holds the hills already
    assert reasons(state, "keep_support", group="greens", line=60) == {
        "line: 60 is not a value this blank takes."
    }
    assert reasons(state, "keep_support", group="farmers", line=65) == {
        "group: farmers is not a value this blank takes."
    }  # a group of Sudland, not of Norra


def test_a_missing_or_unknown_blank_and_an_unknown_pattern_are_refused(played: Game) -> None:
    state = played.state
    assert reasons(state, "keep_support", group="greens") == {"line: give a value."}
    assert reasons(state, "make_peace", foe=SUDLAND, extra=1) == {"extra: there is no such blank."}
    assert reasons(state, "no_such") == {aim_patterns.NO_PATTERN}


def test_a_pattern_for_another_post_is_refused(played: Game) -> None:
    assert reasons(played.state, "hold_the_line", place=COAST) == {aim_patterns.NOT_YOUR_POST}


def test_an_aim_already_met_is_refused(played: Game) -> None:
    state = played.state  # the Greens stand at 60
    assert reasons(state, "keep_support", group="greens", line=55) == {aim_patterns.MET}
    assert filled(state, "keep_support", group="greens", line=65).text == (
        "Keep The Greens at 65 or more."
    )


def test_an_aim_that_can_no_longer_be_met_is_refused(tmp_path: Path) -> None:
    g = game(tmp_path, setup(), WIN_WAR)
    assert filled(g.state, "win_war", contest=BORDER).rule.condition == ContestWon(
        contest=BORDER, side=NORRA
    )
    lost = g.state.contests[BORDER].model_copy(update={"decided": True, "winner": SUDLAND})
    decided = g.state.model_copy(update={"contests": {**g.state.contests, BORDER: lost}})
    assert reasons(decided, "win_war", contest=BORDER) == {aim_patterns.SETTLED}
    late = g.state.model_copy(update={"in_world_date": THIRD_DEADLINE + timedelta(days=1)})
    assert reasons(late, "win_war", contest=BORDER) == {aim_patterns.SETTLED}


def test_an_aim_over_what_the_seat_cannot_see_is_refused(tmp_path: Path) -> None:
    g = game(tmp_path, setup(), FOREIGN_MOOD)
    assert reasons(g.state, "foreign_mood", group="farmers", line=40) == {aim_patterns.UNSEEN}


def test_two_worlds_that_differ_in_a_hidden_fact_give_the_same_reasons(tmp_path: Path) -> None:
    def farmers(start: int) -> Callable[[World], None]:
        def change(w: World) -> None:
            sud = next(n for n in w["groups"] if n["nation"] == "sudland")
            sud["groups"][0]["start"] = start

        return change

    low = game(tmp_path / "low", setup(), FOREIGN_MOOD, farmers(30))
    high = game(tmp_path / "high", setup(), FOREIGN_MOOD, farmers(80))
    asked: dict[str, str | int] = {"group": "farmers", "line": 40}
    assert aim_patterns.fill(low.state, ilse_seat(low.state), "foreign_mood", asked) == (
        aim_patterns.fill(high.state, ilse_seat(high.state), "foreign_mood", asked)
    )
    assert aim_patterns.ladder(low.state, ilse_seat(low.state)) == aim_patterns.ladder(
        high.state, ilse_seat(high.state)
    )


def test_every_reason_is_given_at_once(played: Game) -> None:
    state = played.state.model_copy(update={"aim_shut": frozenset({ILSE})})
    assert reasons(state, "hold_the_line", place=COAST) == {
        aim_patterns.NOT_YOUR_POST,
        aim_patterns.TOO_LATE,
    }


# --- rule 3: who sees each leaf, one function for the compiler and state ----------------


def test_the_shared_exposure_gives_the_compilers_answer_for_every_1941_card_rule() -> None:
    world_1941 = cmp.load_world(cmp.world_path("autumn-1941"))
    from revisionist.core.fold import replay

    state = replay(compile_world(world_1941, CAMPAIGN, cmp.versions()))
    checked = 0
    for person, card in state.cards.items():
        for r in card.aim_rules:
            if r is None:
                continue
            assert aim_patterns.sees(state, person, r.condition) == r.sees, person
            checked += 1
    assert checked >= 24


def test_the_shared_exposure_reads_a_quantitys_scope_and_owner(played: Game) -> None:
    from revisionist.core.goals import QuantityAt, RegardAt
    from revisionist.core.ids import QuantityId

    shipping = QuantityId(key_id("norra_shipping", "quantity"))
    state = played.state
    leaf = QuantityAt(quantity=shipping, op="ge", value=1)
    assert aim_patterns.sees(state, ILSE, leaf) == (Exposure.OWN,)
    assert aim_patterns.sees(state, TOMAS, leaf) == (Exposure.HIDDEN,)
    regard = RegardAt(a=TOMAS, b=SUDLAND, op="ge", value=1)
    assert aim_patterns.sees(state, ILSE, regard) == (Exposure.HIDDEN,)
    assert aim_patterns.sees(state, ILSE, AtWar(a=NORRA, b=SUDLAND)) == (Exposure.PUBLIC,)


# --- rule 4: the stored aim replaces the card's replaceable aim -------------------------


def test_the_set_stores_the_aim_and_replaces_the_replaceable_aims_goal(played: Game) -> None:
    before = {g.aim: g for g in own_goals(played.state, ILSE)}
    assert before[3].source is GoalSource.POST
    set_aim(played, "take_ground", place=ISLE)
    state = played.state
    stored = state.own_aims[ILSE]
    assert isinstance(stored, OwnAim)
    assert (
        stored.aim == 3
        and stored.key == "take_ground"
        and stored.text == ("Take The Isle for Norra.")
    )
    after = {g.aim: g for g in own_goals(state, ILSE)}
    assert set(after) == {1, 2, 3} and len(state.goals) == 3
    third = after[3]
    assert third.goal_id == before[3].goal_id
    assert third.source is GoalSource.PLAYER and third.text == stored.text
    assert third.condition == HoldsArea(area=ISLE, holder=NORRA)
    assert not third.holding and third.met_tick is None
    assert aim_rule(state, third) == stored.rule
    assert after[1] == before[1] and after[2] == before[2]


def test_an_own_aim_set_before_the_goals_are_made_makes_the_players_goal(tmp_path: Path) -> None:
    g = Game(world(tmp_path))  # no tick yet: no goals
    assert own_goals(g.state, ILSE) == []
    set_aim(g, "take_ground", place=ISLE)
    made = {m.goal.aim: m.goal for m in aim_goals(g.state)}
    assert made[3].source is GoalSource.PLAYER and made[3].condition == HoldsArea(
        area=ISLE, holder=NORRA
    )
    assert made[1].source is GoalSource.POST
    g.tick()
    assert [x.source for x in own_goals(g.state, ILSE)] == [
        GoalSource.POST,
        GoalSource.POST,
        GoalSource.PLAYER,
    ]


def test_the_stored_aim_is_judged_like_any_aim(played: Game) -> None:
    set_aim(played, "take_ground", place=ISLE)
    third = own_goals(played.state, ILSE)[2]
    assert aim_status(played.state, third) is AimStatus.AT_RISK
    played.land(ev.AreaHeld(area=ISLE, holder=NORRA, was=SUDLAND, on=played.state.in_world_date))
    landed = played.tick()
    assert [e.payload.goal_id for e in landed if isinstance(e.payload, ev.GoalMet)] == [
        third.goal_id
    ]
    assert aim_status(played.state, own_goals(played.state, ILSE)[2]) is AimStatus.MET


def test_the_fold_refuses_an_own_aim_it_cannot_take(played: Game) -> None:
    out = aim_patterns.own_aim_set(played.state, ilse_seat(played.state), "take_ground",
                                   {"place": ISLE})  # fmt: skip
    assert isinstance(out, ev.OwnAimSet)
    off = played.state.model_copy(update={"rules": played.state.rules - {Rule.OWN_AIM}})
    with pytest.raises(FoldError, match="own aims are not part of this game"):
        fold(off, [out])
    wrong = out.model_copy(update={"own": out.own.model_copy(update={"aim": 2})})
    with pytest.raises(FoldError, match="not the replaceable aim"):
        fold(played.state, [wrong])
    tomas = out.model_copy(update={"own": out.own.model_copy(update={"person": TOMAS})})
    with pytest.raises(FoldError, match="no player holds"):
        fold(played.state, [tomas])
    shut = played.state.model_copy(update={"aim_shut": frozenset({ILSE})})
    with pytest.raises(FoldError, match="window has closed"):
        fold(shut, [out])
    other = out.own.rule.model_copy(update={"condition": HoldsArea(area=COAST, holder=NORRA)})
    forged = out.model_copy(update={"own": out.own.model_copy(update={"rule": other})})
    with pytest.raises(FoldError, match="not pattern take_ground's, filled"):
        fold(played.state, [forged])
    fold(played.state, [out])  # the event as made folds


def test_the_own_aim_is_private_to_the_seat_holding_the_person(tmp_path: Path) -> None:
    g = game(tmp_path, people=(ILSE, TOMAS))
    set_aim(g, "take_ground", place=ISLE)
    (logged,) = [e for e in g.store.read(CAMPAIGN) if e.kind == "own_aim_set"]
    mine, theirs = ilse_seat(g.state), seat_of(g.state, TOMAS)
    assert logged.scope == private_to(mine)
    assert set(project(g.state, mine).own_aims) == {ILSE}
    assert project(g.state, theirs).own_aims == {}
    third = own_goals(g.state, ILSE)[2]
    assert third.goal_id not in project(g.state, theirs).goals
    assert project(g.state, theirs).aim_patterns == g.state.aim_patterns  # public rules


def test_catch_up_feeds_the_patterns_to_all_and_the_own_aim_to_its_seat(tmp_path: Path) -> None:
    g = game(tmp_path, people=(ILSE, TOMAS))
    set_aim(g, "take_ground", place=ISLE)
    events = list(g.store.read(CAMPAIGN))

    def kinds(seat: SeatId) -> list[str]:
        return [f.event.kind for f in catchup.feed(g.state, events, seat, 0, 99)]

    mine, theirs = kinds(ilse_seat(g.state)), kinds(seat_of(g.state, TOMAS))
    assert "aim_patterns_declared" in mine and "aim_patterns_declared" in theirs
    assert "own_aim_set" in mine and "own_aim_set" not in theirs


def test_catch_up_drops_an_own_aim_whose_person_the_seat_no_longer_holds(played: Game) -> None:
    set_aim(played, "take_ground", place=ISLE)
    (logged,) = [e for e in played.store.read(CAMPAIGN) if e.kind == "own_aim_set"]
    seat = ilse_seat(played.state)
    moved = played.state.model_copy(update={"own_aims": {}})
    view = project(moved, seat)
    assert not catchup._visible(logged, view)


# --- rule 5: the ladder ------------------------------------------------------------------


def test_the_ladder_lists_the_posts_patterns_easiest_first(played: Game) -> None:
    rungs = aim_patterns.ladder(played.state, ilse_seat(played.state))
    assert [(r.key, r.difficulty) for r in rungs] == [
        ("keep_support", 3),
        ("make_peace", 4),
        ("take_ground", 4),
    ]
    take = rungs[2]
    (place,) = take.blanks
    assert place.name == "place" and set(place.values) == {COAST, ISLE}
    assert take.sentence == "Take {place} for {nation}." and take.government
    support = rungs[0]
    assert [b.name for b in support.blanks] == ["group", "line"]
    assert support.blanks[1].values == (55, 65, 75)
    assert set(support.blanks[0].values) == {"smiths", "greens", "greys", "public"}


def test_the_ladder_puts_a_pattern_nothing_can_fill_last(tmp_path: Path) -> None:
    g = game(tmp_path, setup(), FOREIGN_MOOD)
    rungs = aim_patterns.ladder(g.state, ilse_seat(g.state))
    assert rungs[-1].key == "foreign_mood" and rungs[-1].difficulty is None


def test_the_territory_checks_score_by_how_far_they_are(played: Game) -> None:
    state, seat = played.state, ilse_seat(played.state)
    assert difficulty(state, seat, HoldsArea(area=ISLE, holder=NORRA)) == 4
    assert difficulty(state, seat, HoldsArea(area=HILLS, holder=NORRA)) == 0
    assert difficulty(state, seat, SupportAt(nation=NORRA, group="greens", op="ge", value=65)) == 3
    assert difficulty(state, seat, SupportAt(nation=NORRA, group="public", op="ge", value=55)) == 4
    assert difficulty(state, seat, AtWar(a=NORRA, b=SUDLAND, war=False)) == 4
    assert difficulty(state, seat, ContestWon(contest=BORDER, side=NORRA)) == 4


# --- rule 6: once per person, inside the window, kept by whoever takes him over ---------


def test_a_second_own_aim_is_refused(played: Game) -> None:
    set_aim(played, "take_ground", place=ISLE)
    assert reasons(played.state, "make_peace", foe=SUDLAND) == {aim_patterns.ALREADY_SET}
    unset = played.state.model_copy(update={"own_aims": {}})
    out = aim_patterns.own_aim_set(unset, ilse_seat(played.state), "make_peace", {"foe": SUDLAND})
    assert isinstance(out, ev.OwnAimSet)
    with pytest.raises(FoldError, match="already has an own aim"):
        fold(played.state, [out])


def test_the_window_closes_with_the_first_wake_the_player_plays(played: Game) -> None:
    assert isinstance(aim_patterns.fill(played.state, ilse_seat(played.state), "make_peace",
                                        {"foe": SUDLAND}), Filled)  # fmt: skip
    close_wake(played)
    assert played.state.aim_shut == frozenset({ILSE})
    assert reasons(played.state, "make_peace", foe=SUDLAND) == {aim_patterns.TOO_LATE}


def test_a_wake_closing_before_anyone_plays_the_person_leaves_his_window_open(
    played: Game,
) -> None:
    close_wake(played)
    assert TOMAS not in played.state.aim_shut


def test_with_the_rule_off_a_closing_wake_records_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, setup(on=False))
    close_wake(g)
    assert g.state.aim_shut == frozenset()


def test_a_player_who_takes_over_inherits_the_own_aim(played: Game) -> None:
    set_aim(played, "take_ground", place=ISLE)
    stored = played.state.own_aims[ILSE]
    played.hand(ILSE, Controller.AI)
    played.tick()
    played.hand(ILSE, Controller.HUMAN)
    played.tick()
    state = played.state
    assert state.own_aims[ILSE] == stored
    assert own_goals(state, ILSE)[2].source is GoalSource.PLAYER
    assert reasons(state, "make_peace", foe=SUDLAND) >= {aim_patterns.ALREADY_SET}


def test_silence_keeps_the_cards_aim(played: Game) -> None:
    close_wake(played)
    played.tick()
    third = own_goals(played.state, ILSE)[2]
    assert third.source is GoalSource.POST and third.text == "Hold the plain."
    assert played.state.own_aims == {}


def test_a_code_seat_cannot_set_an_own_aim(played: Game) -> None:
    played.hand(ILSE, Controller.AI)
    assert aim_patterns.NOT_PLAYED in reasons(played.state, "make_peace", foe=SUDLAND)


# --- rule 7: no replaceable aim, no own aim ---------------------------------------------


def test_a_person_with_no_replaceable_aim_cannot_set_one(tmp_path: Path) -> None:
    g = game(tmp_path, people=(ILSE, TOMAS))
    seat = seat_of(g.state, TOMAS)
    out = aim_patterns.fill(g.state, seat, "make_peace", {"foe": NORRA})
    assert isinstance(out, Refused) and aim_patterns.NO_REPLACEABLE in out.reasons


# --- the season, the restart, the engine's write ----------------------------------------


def test_the_seasons_winners_count_the_own_aim_met_and_unmet(played: Game) -> None:
    set_aim(played, "take_ground", place=ISLE)
    state = played.state
    seat = ilse_seat(state)
    plain_held = {g.aim: g.holding for g in own_goals(state, ILSE)}
    assert plain_held == {1: True, 2: False, 3: False}  # the plain is held, but replaced
    assert seat not in season_winners(state)
    taken = take(state, ISLE, NORRA)
    met = fold(taken, check(taken))
    assert {g.aim: g.holding for g in own_goals(met, ILSE)} == {1: True, 2: False, 3: True}
    assert seat in season_winners(met)


def test_a_restart_between_the_check_and_the_set_gives_one_stored_aim_and_one_digest(
    tmp_path: Path,
) -> None:
    def run(name: str, restart: bool) -> State:
        path = tmp_path / f"{name}.db"
        (tmp_path / name).mkdir()
        store = SqliteStore(path)
        store.append_all(compile_world(world(tmp_path / name), CAMPAIGN, cmp.versions()))
        realism_tick.seat_player(store, CAMPAIGN, ILSE)
        seat = ilse_seat(load_state(store, CAMPAIGN))
        checked = aim_patterns.fill(load_state(store, CAMPAIGN), seat, "make_peace",
                                    {"foe": SUDLAND})  # fmt: skip
        assert isinstance(checked, Filled)
        if restart:
            store.close()
            store = SqliteStore(path)
        stored = realism_tick.set_own_aim(store, CAMPAIGN, seat, "make_peace", {"foe": SUDLAND})
        assert isinstance(stored, OwnAim) and stored.rule == checked.rule
        again = realism_tick.set_own_aim(store, CAMPAIGN, seat, "make_peace", {"foe": SUDLAND})
        assert again == Refused(reasons=(aim_patterns.ALREADY_SET,))
        kinds = [e.kind for e in store.read(CAMPAIGN)]
        assert kinds.count("own_aim_set") == 1
        state = load_state(store, CAMPAIGN)
        store.close()
        return state

    straight, restarted = run("straight", False), run("restarted", True)
    assert len(restarted.own_aims) == 1
    assert state_hash(straight) == state_hash(restarted)


def test_the_engines_write_refuses_with_the_reasons_and_logs_nothing(tmp_path: Path) -> None:
    g = Game(world(tmp_path))
    before = len(list(g.store.read(CAMPAIGN)))
    out = realism_tick.set_own_aim(g.store, CAMPAIGN, ilse_seat(g.state), "take_ground",
                                   {"place": HILLS})  # fmt: skip
    assert out == Refused(reasons=("place: The Norra Hills is not a value this blank takes.",))
    assert len(list(g.store.read(CAMPAIGN))) == before


def test_no_rule_reads_free_text_and_status_never_reads_an_order(played: Game) -> None:
    set_aim(played, "take_ground", place=ISLE)
    third = own_goals(played.state, ILSE)[2]
    renamed = played.state.model_copy(
        update={"goals": {**played.state.goals,
                          third.goal_id: third.model_copy(update={"text": "Anything at all."})}}
    )  # fmt: skip
    assert aim_status(renamed, third) is aim_status(played.state, third)


def test_the_1941_digest_is_the_baseline_with_own_aim_off_and_on_without_patterns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests import test_world_locks_1941 as locks_1941
    from tests.test_rule_names import BASELINE_1941

    plain = locks_1941._world()
    assert Rule.OWN_AIM not in plain.rules and plain.aim_patterns == ()
    assert locks_1941.run_digest(plain, monkeypatch) == BASELINE_1941
    on = plain.model_copy(update={"rules": (*plain.rules, Rule.OWN_AIM)})
    assert locks_1941.run_digest(on, monkeypatch) == BASELINE_1941
