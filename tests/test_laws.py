"""Laws as world data (LWC).

The tests' world is the lock tests' toy world (``tests/test_realism_locks.py``): Ilse Varg
leads Norra, Kara Lind is her general, and Kara's march to the Sudland Coast is held for
Norra's assembly while no law carrying the lock's clause is in force for Norra. The toy
world declares its own law, the Barge Act (``tests/worlds/territory-toy.yaml``), whose key,
clause and flag no code table knows. The lock tests' world has ``laws`` on; ``off`` here
turns it off again.
"""

import ast
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import QuantityId
from revisionist.core.realism import locks
from revisionist.core.realism.effect import Clause, ClauseKind
from revisionist.core.realism.locks import lock_for, seen_lock
from revisionist.core.realism.resolvers import votes
from revisionist.core.state import State
from revisionist.core.world_compile import object_id
from tests.test_realism_locks import (
    KARA,
    LAW,
    NORRA,
    ROOT,
    World,
    game,
    key_id,
    march,
    seat,
    world,
)
from tests.test_territory_model import CAMPAIGN, created, refused

FLAG = "barge_act_passed"
TABLED = "arm merchant ships"
"""A clause the code table's laws carry (``votes.HISTORICAL``)."""
TABLED_FLAG = "arm_merchant_ships_passed"
SUDLAND = key_id("sudland")


def qid(key: str) -> QuantityId:
    return QuantityId(object_id(CAMPAIGN, "quantity", key))


def sub(tmp: Path, name: str) -> Path:
    (tmp / name).mkdir()
    return tmp / name


def off(w: World) -> None:
    w["rules"] = [r for r in w["rules"] if r != "laws"]


def the_law(w: World) -> World:
    law: World = next(x for x in w["laws"] if x["key"] == "barge_act")
    return law


def flag(state: State, key: str, value: int, on: date = date(1900, 4, 2)) -> State:
    q = state.quantities[qid(key)].model_copy(update={"value": value, "as_of": on})
    return state.model_copy(update={"quantities": {**state.quantities, q.quantity_id: q}})


def tabled_flag(w: World) -> None:
    """The code table's arming flag, declared by the world, as the 1941 world does."""
    w["quantities"].append(
        {"key": TABLED_FLAG, "owner": "norra", "name": "Arming", "value": 0, "unit": "flag"}
        | {"source": "toy"}
    )


def coast_clause(clause: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        row = next(r for r in w["locks"] if r["key"] == "coast_march")
        row["when"] = {"check": "law_not_in_force", "clause": clause}

    return change


# --- The declaration ---------------------------------------------------------------


def test_the_laws_reach_state_once_through_one_public_declaration(tmp_path: Path) -> None:
    from revisionist.core.realism.laws import Does, Law, LawEffect

    events, state = created(world(tmp_path))
    declared = [e for e in events if isinstance(e.payload, ev.LawsDeclared)]
    assert len(declared) == 1 and declared[0].scope.visibility.value == "public"
    assert state.laws == (
        Law(
            key="barge_act",
            title="The Barge Act",
            nation=NORRA,
            clauses=(Clause(kind=ClauseKind.POWER, subject=LAW),),
            passed=qid(FLAG),
            does=LawEffect(kind=Does.ARMS_MERCHANT_SHIPS),
        ),
    )


def test_with_laws_off_the_laws_are_checked_and_left_out(tmp_path: Path) -> None:
    from revisionist.engine import campaign as cmp

    events, state = created(world(tmp_path, off, coast_clause(TABLED), tabled_flag))
    assert not [e for e in events if isinstance(e.payload, ev.LawsDeclared)]
    assert state.laws == ()
    _, toy = created(cmp.load_world(ROOT / "tests" / "worlds" / "territory-toy.yaml"))
    assert toy.laws == () and "laws" not in toy.model_dump(mode="json")
    # Checked all the same: a law naming a nation the world lacks is refused.
    problems = refused(
        world(sub(tmp_path, "bad"), off, lambda w: the_law(w).update(nation="nowhere"))
    )
    assert any("law barge_act: unknown nation nowhere" in p for p in problems)


def test_the_declaration_folds_once_and_only_with_the_rule(tmp_path: Path) -> None:
    from revisionist.core.fold import FoldError, _laws_declared, empty

    _, state = created(world(tmp_path))
    payload = ev.LawsDeclared(laws=state.laws)
    with pytest.raises(FoldError, match="needs the laws rule"):
        _laws_declared(empty(CAMPAIGN), payload)
    with pytest.raises(FoldError, match="declared once"):
        _laws_declared(state, payload)
    twice = ev.LawsDeclared(laws=(*state.laws, *state.laws))
    with pytest.raises(FoldError, match="named twice"):
        _laws_declared(state.model_copy(update={"laws": ()}), twice)


# --- The compiler refuses what does not exist ----------------------------------------


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda w: the_law(w).update(nation="ilse"), "law barge_act: unknown nation ilse"),
        (lambda w: the_law(w).update(passed="no_flag"), "law barge_act: unknown quantity no_flag"),
        (
            lambda w: the_law(w).update(does={"kind": "sinks_the_fleet"}),
            "law barge_act: does 'sinks_the_fleet' is not an effect the rules know",
        ),
        (lambda w: the_law(w).update(does={"kind": "adds_manpower"}), "law barge_act: "),
        (lambda w: w["laws"].append(dict(the_law(w))), "law barge_act: duplicate key"),
    ],
)
def test_the_compiler_refuses_a_law_that_names_what_does_not_exist(
    tmp_path: Path, change: Callable[[World], None], problem: str
) -> None:
    problems = refused(world(tmp_path, change))
    assert any(p.startswith(problem) for p in problems), problems


def test_a_law_that_adds_manpower_names_its_amount(tmp_path: Path) -> None:
    from revisionist.core.realism.laws import Does, LawEffect

    def manpower(w: World) -> None:
        the_law(w)["does"] = {"kind": "adds_manpower", "amount": 4}

    _, state = created(world(tmp_path, manpower))
    assert state.laws[0].does == LawEffect(kind=Does.ADDS_MANPOWER, amount=4)


def test_with_laws_on_a_lock_names_only_a_clause_a_declared_law_carries(tmp_path: Path) -> None:
    # The code table's clause, with its flag declared, is no longer enough.
    problems = refused(world(tmp_path, coast_clause(TABLED), tabled_flag))
    assert any("no law the world declares carries the clause" in p for p in problems), problems
    # With laws off, the toy law's clause is one no code table carries: refused as today.
    problems = refused(world(sub(tmp_path, "off"), off))
    assert any("no law the world declares carries the clause" in p for p in problems), problems


# --- in_force -------------------------------------------------------------------------


def test_in_force_reads_the_declared_laws_with_laws_on(tmp_path: Path) -> None:
    from revisionist.core.realism import laws

    state = game(tmp_path)
    assert laws.in_force(state, LAW) == {}
    passed = flag(state, FLAG, 1, date(1900, 4, 9))
    assert laws.in_force(passed, LAW) == {NORRA: date(1900, 4, 9)}
    assert laws.in_force(passed, "another clause") == {}
    assert laws.in_force(flag(state, FLAG, 2), LAW) == {}


def test_with_laws_off_in_force_is_what_the_votes_table_gives(tmp_path: Path) -> None:
    from revisionist.core.realism import laws

    state = game(tmp_path, off, coast_clause(TABLED), tabled_flag)
    for s in (state, flag(state, TABLED_FLAG, 1), flag(state, FLAG, 1)):
        for clause in (TABLED, LAW):
            assert laws.in_force(s, clause) == votes.in_force(s, clause)
    assert laws.in_force(flag(state, TABLED_FLAG, 1), TABLED) == {NORRA: date(1900, 4, 2)}
    assert laws.in_force(flag(state, FLAG, 1), LAW) == {}


# --- The lock reads the declared law -------------------------------------------------


def test_a_law_shaped_lock_is_held_and_opened_by_a_law_no_code_table_knows(
    tmp_path: Path,
) -> None:
    assert "barge_act" not in votes.HISTORICAL and "barge_act" not in votes.TALLIES
    assert all(LAW not in {c.subject for c in m.clauses} for m in votes.HISTORICAL.values())
    state = game(tmp_path)
    found = lock_for(state, seat(KARA), march("sudland_coast"))
    assert found is not None and found.row is not None and found.row.key == "coast_march"
    assert lock_for(flag(state, FLAG, 1), seat(KARA), march("sudland_coast")) is None


def test_with_laws_off_the_lock_reads_the_code_table_as_today(tmp_path: Path) -> None:
    state = game(tmp_path, off, coast_clause(TABLED), tabled_flag)
    assert lock_for(state, seat(KARA), march("sudland_coast")) is not None
    assert lock_for(flag(state, TABLED_FLAG, 1), seat(KARA), march("sudland_coast")) is None


def test_with_laws_on_the_code_tables_flag_opens_nothing(tmp_path: Path) -> None:
    def both(w: World) -> None:
        the_law(w)["clauses"].append({"kind": "power", "subject": TABLED})

    state = game(tmp_path, both, coast_clause(TABLED), tabled_flag)
    tabled = flag(state, TABLED_FLAG, 1)
    assert lock_for(tabled, seat(KARA), march("sudland_coast")) is not None
    assert lock_for(flag(state, FLAG, 1), seat(KARA), march("sudland_coast")) is None


def test_a_law_of_another_nation_does_not_open_the_lock(tmp_path: Path) -> None:
    def sudland_law(w: World) -> None:
        w["quantities"].append(
            {"key": "sud_act_passed", "owner": "norra", "name": "Sud", "value": 0, "unit": "flag"}
            | {"source": "toy"}
        )
        w["laws"].append(
            {
                "key": "sud_act",
                "title": "The Sud Act",
                "nation": "sudland",
                "clauses": [{"kind": "power", "subject": LAW}],
                "passed": "sud_act_passed",
            }
        )

    state = flag(game(tmp_path, sudland_law), "sud_act_passed", 1)
    from revisionist.core.realism import laws

    assert laws.in_force(state, LAW) == {SUDLAND: date(1900, 4, 2)}
    assert lock_for(state, seat(KARA), march("sudland_coast")) is not None


def test_a_hidden_passed_flag_is_not_shown_through_the_lock(tmp_path: Path) -> None:
    # The Barge Act's flag is not public: Kara cannot see whether it passed, so the lock
    # that turns on it holds nothing for her and tells her nothing.
    state = game(tmp_path)
    assert lock_for(state, seat(KARA), march("sudland_coast")) is not None
    assert seen_lock(state, seat(KARA), march("sudland_coast")) is None

    def public(w: World) -> None:
        next(q for q in w["quantities"] if q["key"] == FLAG)["public"] = True

    shown = seen_lock(game(sub(tmp_path, "public"), public), seat(KARA), march("sudland_coast"))
    assert shown is not None and shown.row is not None and shown.row.key == "coast_march"


def test_lock_for_is_the_same_for_two_calls_on_one_state(tmp_path: Path) -> None:
    state = game(tmp_path)
    for s in (state, flag(state, FLAG, 1)):
        order = march("sudland_coast")
        assert lock_for(s, seat(KARA), order) == lock_for(s, seat(KARA), order)
        assert seen_lock(s, seat(KARA), order) == seen_lock(s, seat(KARA), order)


def test_the_laws_module_names_nothing_from_any_world() -> None:
    from tests.test_realism_locks import _world_words

    source = (ROOT / "src" / "revisionist" / "core" / "realism" / "laws.py").read_text()
    literals = {
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    named = sorted(literals & (_world_words() | {LAW, TABLED, "barge_act", FLAG}))
    assert not named, f"laws.py names world data: {named}"


def test_the_view_holds_the_laws(tmp_path: Path) -> None:
    from revisionist.core.project import project

    state = game(tmp_path)
    assert project(state, seat(KARA)).laws == state.laws != ()
    assert locks.on(state)


def test_the_toy_worlds_own_law_names_a_key_no_code_table_has() -> None:
    import yaml

    raw = yaml.safe_load((ROOT / "tests" / "worlds" / "territory-toy.yaml").read_text())
    keys = {law["key"] for law in raw["laws"]}
    assert keys == {"barge_act"} and not keys & set(votes.HISTORICAL)
