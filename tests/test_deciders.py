"""Deciders by kind of question, and the council (QKD).

The toy world of the lock tests (``tests/test_realism_locks.py``) gains Greta Holm, a
councillor of Norra nobody plays, and one more row: Kara Lind's march to the Norra Hills
is a question of war for Norra's war council, Ilse Varg (its head, whom nobody plays
here), Olaf Brun (the second human seat) and Greta, two of the three to agree. The row
has no condition, so only the council's grant opens it.

Each code-run member's card is set past the draw's reach: regard 3 for Kara and a topic
the march touches that he wants grants; regard -3 and a topic he holds to declines.
"""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, replay, state_hash
from revisionist.core.ids import EntityId, OrderId
from revisionist.core.project import project
from revisionist.core.realism import locks
from revisionist.core.realism.process import ANSWER_DAYS
from revisionist.core.state import Rule, State
from revisionist.core.world_compile import WorldError, compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick, session_zero
from revisionist.engine.store import MemoryStore, load_state
from tests.test_realism_command import card
from tests.test_realism_locks import (
    ILSE,
    KARA,
    NORRA,
    OLAF,
    World,
    file,
    key_id,
    logged,
    seat,
    world,
)
from tests.test_territory_model import CAMPAIGN

GRETA = key_id("greta")
ROW = "hills_council"
COUNCIL = {"members": ["ilse", "olaf", "greta"], "needed": 2, "head": "ilse"}


def councillor(w: World) -> None:
    """Greta Holm, a councillor of Norra with a card, whom nobody plays."""
    w["entities"].append(
        {"key": "greta", "kind": "person", "name": "Greta Holm", "parent": "norra"}
    )
    w["cards"].append(
        {
            "person": "greta",
            "office": "Councillor of Norra",
            "playable": False,
            "principals": ["norra"],
            "horizon_days": 14,
        }
    )


def council_row(w: World) -> None:
    """The war council decides Kara's march to the hills, always."""
    councillor(w)
    w["rules"] = sorted({*w["rules"], "deciders"})
    w["locks"].append(
        {
            "key": ROW,
            "question": "war",
            "order": {"form": "march", "params": {"to": "norra_hills"}},
            "decider": {"council": dict(COUNCIL)},
        }
    )


def hills_topic(w: World) -> None:
    w.setdefault("topics", []).append(
        {"key": "the_hills", "name": "The Hills", "levers": ["march"]}
    )


def leaning(person: str, n: int) -> Callable[[World], None]:
    """``person``'s card for Kara: regard ``n``, and the march a topic he wants (n > 0)
    or holds to (n < 0)."""

    def edit(w: World) -> None:
        if not any(t["key"] == "the_hills" for t in w.get("topics", [])):
            hills_topic(w)
        w.setdefault("relationships", []).append(
            {"key": f"{person}_kara", "a": person, "b": "kara", "disposition": n}
        )
        card(w, person)["wants" if n > 0 else "holds_to"] = ["the_hills"]

    return edit


def asked_by_kind(key: str, question: str = "permission") -> Callable[[World], None]:
    """The row ``key`` names its kind of question, so it is decided by its kind."""

    def edit(w: World) -> None:
        next(r for r in w["locks"] if r["key"] == key)["question"] = question

    return edit


def answers_on(w: World) -> None:
    w["rules"] = sorted({*w["rules"], "ask_answers"})


def deciders_off(w: World) -> None:
    w["rules"] = [r for r in w["rules"] if r != "deciders"]


def game(
    tmp: Path, *changes: Callable[[World], None], claimed: tuple[EntityId, ...] = (KARA, OLAF)
) -> MemoryStore:
    tmp.mkdir(parents=True, exist_ok=True)
    store = MemoryStore()
    store.append_all(compile_world(world(tmp, *changes), CAMPAIGN, cmp.versions()))
    state = load_state(store, CAMPAIGN)
    for person in claimed:
        session_zero.claim(store, CAMPAIGN, seat(person), state.entities[person].name)
    realism_tick.open_play(store, CAMPAIGN)
    return store


def ask(store: MemoryStore, order_id: OrderId) -> locks.Asked:
    return realism_tick.ask_order(store, CAMPAIGN, seat(KARA), order_id)


def choose(store: MemoryStore, person: EntityId, order_id: OrderId, accept: bool) -> None:
    realism_tick.choose_matter(store, CAMPAIGN, seat(person), order_id, accept)


def tick_until(store: MemoryStore, done: Callable[[State], bool], ticks: int = 10) -> State:
    for _ in range(ticks):
        realism_tick.run_realism_tick(store, CAMPAIGN)
        state = load_state(store, CAMPAIGN)
        if done(state):
            return state
    return load_state(store, CAMPAIGN)


def answered(store: MemoryStore) -> list[ev.AskAnswered]:
    return logged(store, ev.AskAnswered)


def asked_hills(
    tmp: Path, *changes: Callable[[World], None], olaf: bool | None = None
) -> tuple[MemoryStore, OrderId]:
    """Kara files the march to the hills and asks for it; Olaf chooses, or stays silent."""
    store = game(tmp, council_row, *changes)
    order = file(store, "norra_hills")
    assert order.order_id in load_state(store, CAMPAIGN).held
    ask(store, order.order_id)
    if olaf is not None:
        choose(store, OLAF, order.order_id, olaf)
    return store, order.order_id


def outcome(store: MemoryStore, order_id: OrderId) -> tuple[bool, State]:
    state = tick_until(store, lambda s: bool(answered(store)))
    (answer,) = answered(store)
    assert answer.order_id == order_id
    return answer.granted, state


# --- rule 1: a row names its kind of question ---------------------------------------


def test_a_row_names_its_kind_of_question_and_permission_is_the_default(tmp_path: Path) -> None:
    state = load_state(game(tmp_path, council_row), CAMPAIGN)
    rows = {r.key: r for r in state.locks}
    assert rows[ROW].question is locks.Question.WAR
    assert rows["island_march"].question is None
    assert "question" not in rows["island_march"].model_dump(mode="json")
    permission = locks.rows_on(state, NORRA, locks.Question.PERMISSION)
    assert "island_march" in [r.key for r in permission] and ROW not in [r.key for r in permission]
    assert {q.value for q in locks.Question} == {
        "permission",
        "war",
        "peace",
        "money",
        "posts",
        "office",
    }


def test_the_rows_on_a_question_are_found_by_nation_and_kind(tmp_path: Path) -> None:
    state = load_state(game(tmp_path, council_row), CAMPAIGN)
    assert [r.key for r in locks.rows_on(state, NORRA, locks.Question.WAR)] == [ROW]
    assert locks.rows_on(state, NORRA, locks.Question.PEACE) == []
    sudland = key_id("sudland")
    assert locks.rows_on(state, sudland, locks.Question.WAR) == []


def test_with_deciders_off_no_row_answers_a_question(tmp_path: Path) -> None:
    state = load_state(game(tmp_path, council_row, deciders_off), CAMPAIGN)
    assert locks.rows_on(state, NORRA, locks.Question.WAR) == []


def test_an_unknown_kind_of_question_is_refused(tmp_path: Path) -> None:
    def bad(w: World) -> None:
        next(r for r in w["locks"] if r["key"] == ROW)["question"] = "norra"

    # Checked with the switch off as well, where the row's question is otherwise dropped.
    with pytest.raises(WorldError, match="unknown question norra"):
        compile_world(world(tmp_path, council_row, bad, deciders_off), CAMPAIGN, cmp.versions())
    with pytest.raises(WorldError, match="unknown question norra"):
        compile_world(world(tmp_path, council_row, bad), CAMPAIGN, cmp.versions())


# --- rule 2: the council, and what the compiler refuses -----------------------------


def test_the_council_reaches_state_with_its_members_count_and_head(tmp_path: Path) -> None:
    state = load_state(game(tmp_path, council_row), CAMPAIGN)
    row = next(r for r in state.locks if r.key == ROW)
    assert row.decider.council == locks.Council(members=(ILSE, OLAF, GRETA), needed=2, head=ILSE)
    assert locks.asked_of(row.decider) == ILSE


def test_a_member_with_no_card_is_refused(tmp_path: Path) -> None:
    def stranger(w: World) -> None:
        w["entities"].append(
            {"key": "nils", "kind": "person", "name": "Nils Berg", "parent": "norra"}
        )
        council = next(r for r in w["locks"] if r["key"] == ROW)["decider"]["council"]
        council["members"] = ["ilse", "olaf", "nils"]

    with pytest.raises(WorldError, match="nils has no card"):
        compile_world(world(tmp_path, council_row, stranger), CAMPAIGN, cmp.versions())


def test_a_count_above_the_membership_is_refused(tmp_path: Path) -> None:
    def four(w: World) -> None:
        next(r for r in w["locks"] if r["key"] == ROW)["decider"]["council"]["needed"] = 4

    with pytest.raises(WorldError, match="needs 4 of 3"):
        compile_world(world(tmp_path, council_row, four), CAMPAIGN, cmp.versions())


# --- rules 5 and 6: the council decides on the due day ------------------------------


def test_granted_by_two_the_lock_opens_itself_on_the_due_day(tmp_path: Path) -> None:
    store, order_id = asked_hills(tmp_path, leaning("ilse", 3), leaning("greta", -3), olaf=True)
    made = load_state(store, CAMPAIGN).asked[order_id]
    granted, _ = outcome(store, order_id)
    assert granted
    (answer,) = answered(store)
    assert answer.on == made.on + timedelta(days=ANSWER_DAYS)
    (end,) = [e for e in logged(store, ev.HeldOrderEnded) if e.order_id == order_id]
    assert end.end is locks.HeldEnd.LANDED and end.on == answer.on
    # No member files anything: the grant itself opened the lock.
    drafted = [p.order.issuer for p in logged(store, ev.OrderDrafted)]
    assert seat(ILSE) not in drafted and seat(OLAF) not in drafted


def test_a_councils_grant_opens_a_row_whose_condition_still_holds(tmp_path: Path) -> None:
    def isle_council(w: World) -> None:
        isle = next(r for r in w["locks"] if r["key"] == "island_march")
        isle["decider"] = {"council": dict(COUNCIL)}

    store = game(tmp_path, council_row, isle_council, leaning("greta", 3), leaning("ilse", -3))
    order = file(store, "isle")
    ask(store, order.order_id)
    choose(store, OLAF, order.order_id, True)
    granted, state = outcome(store, order.order_id)
    assert granted and order.order_id not in state.held
    # Nobody set the watch the row's condition reads: the grant alone opened it.
    assert not [p for p in logged(store, ev.OrderDrafted) if p.order.lever == "set_watch"]


def test_declined_by_two_the_order_stays_held(tmp_path: Path) -> None:
    store, order_id = asked_hills(tmp_path, leaning("ilse", -3), leaning("greta", 3), olaf=False)
    granted, state = outcome(store, order_id)
    assert not granted
    state = tick_until(store, lambda s: False, ticks=3)
    assert order_id in state.held
    assert not [e for e in logged(store, ev.HeldOrderEnded) if e.order_id == order_id]


@pytest.mark.parametrize(("lean", "granted"), [(3, True), (-3, False)])
def test_a_silent_human_member_is_decided_by_his_card(
    tmp_path: Path, lean: int, granted: bool
) -> None:
    store, order_id = asked_hills(
        tmp_path, leaning("ilse", 3), leaning("greta", -3), leaning("olaf", lean)
    )
    assert outcome(store, order_id)[0] is granted


def test_a_human_members_kept_choice_outweighs_his_card(tmp_path: Path) -> None:
    store, order_id = asked_hills(
        tmp_path, leaning("ilse", 3), leaning("greta", -3), leaning("olaf", -3), olaf=True
    )
    assert outcome(store, order_id)[0] is True


def test_a_later_choice_before_the_due_day_replaces_the_first(tmp_path: Path) -> None:
    store, order_id = asked_hills(tmp_path, leaning("ilse", 3), leaning("greta", -3), olaf=True)
    choose(store, OLAF, order_id, False)
    assert outcome(store, order_id)[0] is False


# --- the sealed choice, and rule 7 --------------------------------------------------


def test_a_members_choice_is_absent_from_every_other_seats_data(tmp_path: Path) -> None:
    store, order_id = asked_hills(tmp_path, leaning("ilse", 3), leaning("greta", -3), olaf=True)
    state = load_state(store, CAMPAIGN)
    assert state.chosen[order_id] == {seat(OLAF): True}
    (chosen,) = [e for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.MatterChosen)]
    assert chosen.scope.visibility.value != "public"
    assert chosen.scope.known_by == frozenset({seat(OLAF)})
    for other in (seat(KARA),):
        view = project(state, other)
        assert "chosen" not in view.model_dump(mode="json")
        kinds = [f.event.kind for f in catchup.seat_events(store, CAMPAIGN, other, 0, 99)]
        assert "matter_chosen" not in kinds
    assert "matter_chosen" in catchup.NEVER


def test_the_asker_learns_only_granted_or_declined(tmp_path: Path) -> None:
    store, order_id = asked_hills(tmp_path, leaning("ilse", 3), leaning("greta", -3), olaf=True)
    outcome(store, order_id)
    (answer,) = [e for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.AskAnswered)]
    assert set(answer.payload.model_dump(mode="json")) == {
        "kind",
        "order_id",
        "asker",
        "on",
        "granted",
    }
    assert answer.scope.known_by == frozenset({seat(KARA)})
    assert seat(KARA) not in {k for c in load_state(store, CAMPAIGN).chosen.values() for k in c}


def test_the_matter_is_before_each_human_member(tmp_path: Path) -> None:
    store, order_id = asked_hills(tmp_path, leaning("ilse", 3), leaning("greta", -3))
    state = load_state(store, CAMPAIGN)
    assert seat(OLAF) in state.asked[order_id].seats
    assert order_id in project(state, seat(OLAF)).asked


def test_only_a_member_may_choose_and_only_before_the_answer(tmp_path: Path) -> None:
    store, order_id = asked_hills(tmp_path, leaning("ilse", 3), leaning("greta", -3), olaf=True)
    with pytest.raises(ValueError):
        choose(store, KARA, order_id, True)
    outcome(store, order_id)
    with pytest.raises(ValueError):
        choose(store, OLAF, order_id, False)


def test_the_choice_folds_only_for_a_member_of_an_open_matter(tmp_path: Path) -> None:
    store, order_id = asked_hills(tmp_path, leaning("ilse", 3), leaning("greta", -3))
    events = list(store.read(CAMPAIGN))
    last = events[-1]

    def bump(p: ev.Payload) -> list[ev.Event]:
        return [*events, last.model_copy(update={"seq": last.seq + 1, "payload": p})]

    day = load_state(store, CAMPAIGN).in_world_date
    assert day is not None
    with pytest.raises(FoldError):
        replay(bump(ev.MatterChosen(order_id=order_id, seat_id=seat(KARA), accept=True, on=day)))
    replay(bump(ev.MatterChosen(order_id=order_id, seat_id=seat(OLAF), accept=True, on=day)))


def test_a_restart_before_the_due_day_gives_one_answer_and_one_digest(tmp_path: Path) -> None:
    store, _ = asked_hills(tmp_path, leaning("ilse", 3), leaning("greta", -3), olaf=True)
    twin = MemoryStore()
    twin.append_all(list(store.read(CAMPAIGN)))
    for s in (store, twin):
        tick_until(s, lambda st: False, ticks=3)
    assert len(answered(store)) == len(answered(twin)) == 1
    assert state_hash(load_state(twin, CAMPAIGN)) == state_hash(load_state(store, CAMPAIGN))


# --- rule 4: a single human decider ---------------------------------------------------


@pytest.mark.parametrize("accept", [True, False])
def test_a_human_decider_answers_the_matter_himself(tmp_path: Path, accept: bool) -> None:
    store = game(
        tmp_path,
        council_row,
        asked_by_kind("island_march"),
        leaning("ilse", -3),
        claimed=(ILSE, KARA, OLAF),
    )
    order = file(store, "isle")
    made = ask(store, order.order_id)
    assert made.seat == seat(ILSE)
    choose(store, ILSE, order.order_id, accept)
    granted, state = outcome(store, order.order_id)
    assert granted is accept
    (answer,) = answered(store)
    assert answer.on == made.on + timedelta(days=ANSWER_DAYS)
    assert (order.order_id in state.held) is not accept


@pytest.mark.parametrize(("lean", "granted"), [(3, True), (-3, False)])
def test_a_silent_human_decider_is_decided_by_his_card(
    tmp_path: Path, lean: int, granted: bool
) -> None:
    def isle(w: World) -> None:
        w.setdefault("topics", []).append(
            {"key": "the_isle", "name": "The Isle", "levers": ["march"]}
        )
        w.setdefault("relationships", []).append(
            {"key": "ilse_kara", "a": "ilse", "b": "kara", "disposition": lean}
        )
        card(w, "ilse")["wants" if lean > 0 else "holds_to"] = ["the_isle"]

    store = game(
        tmp_path, council_row, asked_by_kind("island_march"), isle, claimed=(ILSE, KARA, OLAF)
    )
    order = file(store, "isle")
    ask(store, order.order_id)
    assert outcome(store, order.order_id)[0] is granted


# --- rule 3: a row with no condition opens on a grant --------------------------------


def hills_for_ilse(w: World) -> None:
    """Kara's march to the hills always needs Ilse, whom nobody plays."""
    w["locks"].append(
        {
            "key": "hills_ilse",
            "order": {"form": "march", "params": {"to": "norra_hills"}},
            "decider": {"person": "ilse"},
        }
    )


def test_a_row_with_no_condition_opens_on_the_cards_grant(tmp_path: Path) -> None:
    store = game(
        tmp_path,
        hills_for_ilse,
        asked_by_kind("hills_ilse"),
        answers_on,
        leaning("ilse", 3),
        deciders_on,
    )
    order = file(store, "norra_hills")
    ask(store, order.order_id)
    state = tick_until(store, lambda s: order.order_id not in s.held)
    (answer,) = answered(store)
    assert answer.granted
    (end,) = [e for e in logged(store, ev.HeldOrderEnded) if e.order_id == order.order_id]
    assert end.end is locks.HeldEnd.LANDED and end.on == answer.on
    assert order.order_id not in state.held


# --- a row without the new keys behaves as today, with deciders on --------------------


def test_with_deciders_on_a_granted_row_naming_no_question_stays_shut(tmp_path: Path) -> None:
    store = game(tmp_path, hills_for_ilse, answers_on, leaning("ilse", 3), deciders_on)
    order = file(store, "norra_hills")
    ask(store, order.order_id)
    state = tick_until(store, lambda s: bool(answered(store)))
    (answer,) = answered(store)
    assert answer.granted
    state = tick_until(store, lambda s: False, ticks=3)
    assert order.order_id in state.held


def test_with_deciders_on_a_human_decider_of_a_plain_row_is_asked_as_today(
    tmp_path: Path,
) -> None:
    store = game(tmp_path, council_row, leaning("ilse", -3), claimed=(ILSE, KARA, OLAF))
    order = file(store, "isle")
    ask(store, order.order_id)
    with pytest.raises(ValueError):
        choose(store, ILSE, order.order_id, True)
    state = tick_until(store, lambda s: False, ticks=3)
    assert not answered(store) and order.order_id in state.held


def deciders_on(w: World) -> None:
    w["rules"] = sorted({*w["rules"], "deciders"})


# --- with deciders off, the same scripts behave as today -----------------------------


def as_today(w: World) -> None:
    """The council row written as today's world would: its head decides, no question."""
    councillor(w)
    w["locks"].append(
        {
            "key": ROW,
            "order": {"form": "march", "params": {"to": "norra_hills"}},
            "decider": {"person": "ilse"},
        }
    )


def test_with_deciders_off_a_council_row_compiles_as_its_head_alone(tmp_path: Path) -> None:
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
    off = compile_world(world(tmp_path / "a", council_row, deciders_off), CAMPAIGN, cmp.versions())
    today = compile_world(world(tmp_path / "b", as_today), CAMPAIGN, cmp.versions())
    assert [e.payload for e in off] == [e.payload for e in today]


def test_with_deciders_off_the_same_script_behaves_as_today(tmp_path: Path) -> None:
    def script(*changes: Callable[[World], None], tmp: Path) -> tuple[State, str]:
        """The state after the script, and its dump with the filed order's id (drawn
        afresh each run) written as ``ORDER``."""
        store = game(tmp, *changes, claimed=(ILSE, KARA, OLAF))
        order = file(store, "norra_hills")
        ask(store, order.order_id)
        with pytest.raises(ValueError):
            choose(store, ILSE, order.order_id, True)
        state = tick_until(store, lambda s: False, ticks=3)
        return state, state.model_dump_json().replace(order.order_id, "ORDER")

    off, off_dump = script(council_row, deciders_off, tmp=tmp_path / "a")
    _, today_dump = script(as_today, tmp=tmp_path / "b")
    assert not off.chosen and all(a.answered is None for a in off.asked.values())
    assert off_dump == today_dump


def test_the_rule_is_named_deciders() -> None:
    assert Rule.DECIDERS.value == "deciders"
