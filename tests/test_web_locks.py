"""The seat's locks and the check before sending (LKD).

The toy world as the lock tests play it (``tests/test_realism_locks.py``): ``locks`` on,
Ilse Varg the chancellor, Kara Lind her general, Olaf Brun Kara's aide. Kara's march to
the Isle waits on Ilse while she has set no watch on the Gulf; her march to the Sudland
Coast waits on Norra's assembly while the arming law is not in force (a flag Kara cannot
see unless it is public); any written engagement in the Gulf waits on Ilse; a move of the
kites, outside Olaf's post, waits on Ilse as the nearest card above that covers it.

The seat's ``locks`` block carries its own held orders and the asks put before it; the
``check`` action answers, for a draft order, what filing it would do, and files nothing;
the ``ask`` action files the ask.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.ids import EntityId, OrderId
from revisionist.core.project import project
from revisionist.core.realism import locks
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.effect import MoveForce
from revisionist.core.realism.route import NOBODY
from revisionist.core.state import State
from revisionist.engine import realism_tick
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import agenda_api, held, locks_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests.test_realism_locks import (
    DAY,
    HELD_FOR_ASSEMBLY,
    HELD_FOR_ILSE,
    ILSE,
    ISLE,
    KARA,
    LEVY,
    OLAF,
    World,
    ask,
    commit,
    file,
    guard_the_gulf,
    gulf_fire,
    isle_move,
    key_id,
    kites_laid_up,
    kites_to_isle,
    law_passed,
    played,
    public_law,
    seat,
    tick_until,
    unlocked,
    world,
    written,
)
from tests.test_territory_model import CAMPAIGN
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin

ISLE_WORDS = "March (Force Norra levy, To Isle)"
HILLS = {"force": "norra_levy", "to": "norra_hills"}
TO_ISLE = {"force": "norra_levy", "to": "isle"}
TO_COAST = {"force": "norra_levy", "to": "sudland_coast"}


def state_of(store: MemoryStore) -> State:
    return load_state(store, CAMPAIGN)


def realism(store: MemoryStore, person: EntityId) -> dict[str, Any]:
    state = state_of(store)
    return rs.seat_realism(state, seat(person), set(), set(), None, events=store.read(CAMPAIGN))


def block(store: MemoryStore, person: EntityId) -> api.LocksBlock:
    found = locks_api.block(state_of(store), seat(person))
    assert found is not None
    return found


def no_ids(lines: list[api.HeldLine]) -> list[tuple[Any, ...]]:
    return sorted((h["words"], h["who"], h["reason"], h["held"], h["asked"]) for h in lines)


# --- Rule 1: the seat's data carries its held orders ----------------------------------


def test_the_seat_data_carries_its_held_orders(tmp_path: Path) -> None:
    store = played(tmp_path)
    order = file(store, "isle")
    shot = commit(store, KARA, gulf_fire())
    assert isinstance(shot, locks.HeldOrder)
    ask(store, order.order_id)
    shown = realism(store, KARA)["locks"]
    assert set(shown) == set(api.LocksBlock.__annotations__)
    by_id = {h["id"]: h for h in shown["held"]}
    assert set(by_id) == {order.order_id, shot.order_id}
    assert by_id[order.order_id] == api.HeldLine(
        id=order.order_id,
        words=ISLE_WORDS,
        who="Ilse Varg",
        reason=HELD_FOR_ILSE,
        held=DAY.isoformat(),
        asked=True,
        piece=by_id[order.order_id]["piece"],
    )
    assert by_id[shot.order_id]["asked"] is False
    assert by_id[shot.order_id]["words"] == "as written"
    assert shown["asks"] == []


def test_a_held_move_names_the_piece_it_moves_by_its_map_key(tmp_path: Path) -> None:
    store = played(tmp_path)
    order = file(store, "isle")
    shot = commit(store, KARA, gulf_fire())
    assert isinstance(shot, locks.HeldOrder)
    shown = realism(store, KARA)
    pieces = {m["name"]: m["piece"]["key"] for m in shown["map"]["marks"] if m["piece"]}
    by_id = {h["id"]: h for h in shown["locks"]["held"]}
    assert by_id[order.order_id]["piece"] == pieces["The Norra Levy"]
    assert by_id[shot.order_id]["piece"] is None


def test_a_body_is_named_as_the_seat_is_told(tmp_path: Path) -> None:
    store = played(tmp_path, public_law)
    file(store, "sudland_coast")
    (line,) = block(store, KARA)["held"]
    assert (line["who"], line["reason"]) == ("Norra's assembly", HELD_FOR_ASSEMBLY)


def test_a_held_order_that_ends_leaves_the_list(tmp_path: Path) -> None:
    store = played(tmp_path)
    order = file(store, "isle")
    commit(store, ILSE, guard_the_gulf())
    tick_until(store, lambda s: order.order_id not in s.held)
    assert block(store, KARA)["held"] == []


def test_with_locks_off_the_payload_is_as_today(tmp_path: Path) -> None:
    store = played(tmp_path, unlocked)
    file(store, "isle")
    for person in (ILSE, KARA, OLAF):
        assert "locks" not in realism(store, person)
        assert locks_api.block(state_of(store), seat(person)) is None
        kinds = {m.kind for m in agenda_api.due_matters(state_of(store), seat(person))}
        assert "ask" not in kinds


# --- Fog: each seat sees its own lines only -------------------------------------------


def test_another_seats_held_orders_and_asks_are_absent(tmp_path: Path) -> None:
    store = played(tmp_path)
    kara = file(store, "isle")
    olaf = commit(store, OLAF, kites_to_isle())
    assert isinstance(olaf, locks.HeldOrder)
    made = ask(store, kara.order_id)
    asked_id = locks_api.ask_id(CAMPAIGN, made.order_id)
    assert [h["id"] for h in block(store, KARA)["held"]] == [kara.order_id]
    assert [h["id"] for h in block(store, OLAF)["held"]] == [olaf.order_id]
    assert block(store, OLAF)["asks"] == [] and block(store, KARA)["asks"] == []
    theirs = json.dumps(realism(store, OLAF))
    assert kara.order_id not in theirs and asked_id not in theirs and ISLE_WORDS not in theirs
    mine = json.dumps(realism(store, KARA))
    assert olaf.order_id not in mine and "Send the kites" not in mine
    # The decider sees the ask, and none of the held orders themselves.
    ilse = json.dumps(realism(store, ILSE))
    assert asked_id in ilse and kara.order_id not in ilse and olaf.order_id not in ilse
    assert block(store, ILSE)["held"] == []


# --- Rule 4: the decider's list carries each ask put before him ----------------------


def test_the_deciders_list_carries_each_ask_with_the_asker_and_the_words(tmp_path: Path) -> None:
    store = played(tmp_path)
    order = file(store, "isle")
    ask(store, order.order_id)
    (line,) = block(store, ILSE)["asks"]
    assert line == api.AskLine(
        id=locks_api.ask_id(CAMPAIGN, order.order_id),
        by="Kara Lind",
        words=ISLE_WORDS,
        asked=DAY.isoformat(),
        forms=[
            api.AskForm(
                lever="set_watch",
                label="Set watch",
                params={"zone": "gulf", "order": "guard"},
            )
        ],
    )
    (due,) = [m for m in agenda_api.due_matters(state_of(store), seat(ILSE)) if m.kind == "ask"]
    assert due == agenda_api.DueMatter(
        "ask", line["id"], ISLE_WORDS, "Kara Lind", locks_api.ASK_DUE
    )
    for person in (KARA, OLAF):
        kinds = {m.kind for m in agenda_api.due_matters(state_of(store), seat(person))}
        assert "ask" not in kinds


def test_an_ask_for_a_written_order_names_no_form(tmp_path: Path) -> None:
    store = played(tmp_path)
    shot = commit(store, KARA, gulf_fire())
    ask(store, shot.order_id)
    (line,) = block(store, ILSE)["asks"]
    assert (line["by"], line["words"], line["forms"]) == ("Kara Lind", "as written", [])


# --- Rules 2 and 3: the check, equal to what filing then does -------------------------

ALLOWED = api.LockCheck(check="allowed", who=None, reason="")


def locked_by(who: str, reason: str) -> api.LockCheck:
    return api.LockCheck(check="locked", who=who, reason=reason)


def beyond(reason: str) -> api.LockCheck:
    return api.LockCheck(check="beyond", who=None, reason=reason)


Draft = tuple[str, dict[str, str]] | tuple[Ask, ...]


def check(store: MemoryStore, person: EntityId, draft: Draft) -> api.LockCheck:
    state = state_of(store)
    if isinstance(draft[0], str):
        lever, given = draft
        assert isinstance(lever, str) and isinstance(given, dict)
        return locks_api.check_form(state, seat(person), lever, given)
    asks = tuple(a for a in draft if isinstance(a, Ask))
    return locks_api.check_asks(state, seat(person), asks)


def filed(store: MemoryStore, person: EntityId, draft: Draft) -> api.LockCheck:
    """What filing the draft does, in the check's words."""
    try:
        if isinstance(draft[0], str):
            lever, given = draft
            assert isinstance(lever, str) and isinstance(given, dict)
            order_id = realism_tick.file_order(store, CAMPAIGN, seat(person), lever, given).order_id
        else:
            asks = tuple(a for a in draft if isinstance(a, Ask))
            order_id = commit(store, person, *asks).order_id
    except ValueError as exc:
        return beyond(str(exc))
    hold = state_of(store).held.get(order_id)
    if hold is None:
        return ALLOWED
    view = project(state_of(store), seat(person))
    return locked_by(locks_api.who(view, hold.decider), hold.reason)


HILLS_MOVE = written(MoveForce(force=LEVY, to=key_id("norra_hills")))
Case = tuple[tuple[Callable[[World], None], ...], EntityId, Draft, api.LockCheck | None]
CASES: list[Case] = [
    ((), KARA, ("march", HILLS), ALLOWED),
    ((), KARA, ("march", TO_ISLE), locked_by("Ilse Varg", HELD_FOR_ILSE)),
    # The arming law is hidden from Kara: the march to the coast checks as allowed.
    ((), KARA, ("march", TO_COAST), ALLOWED),
    ((law_passed,), KARA, ("march", TO_COAST), ALLOWED),
    ((public_law,), KARA, ("march", TO_COAST), locked_by("Norra's assembly", HELD_FOR_ASSEMBLY)),
    ((public_law, law_passed), KARA, ("march", TO_COAST), ALLOWED),
    ((), KARA, ("march", {"force": "norra_levy"}), beyond("march takes exactly: force, to")),
    ((), KARA, ("set_watch", {"zone": "gulf", "order": "guard"}), None),
    ((), ILSE, ("set_watch", {"zone": "gulf", "order": "guard"}), ALLOWED),
    ((), KARA, (gulf_fire(),), locked_by("Ilse Varg", HELD_FOR_ILSE)),
    ((), OLAF, (kites_to_isle(),), locked_by("Ilse Varg", HELD_FOR_ILSE)),
    ((), KARA, (HILLS_MOVE,), ALLOWED),
    ((isle_move,), KARA, (written(MoveForce(force=LEVY, to=ISLE)),), None),
    ((kites_laid_up,), OLAF, (kites_to_isle(),), None),
    ((unlocked,), OLAF, (kites_to_isle(),), None),
    ((unlocked,), KARA, ("march", TO_ISLE), ALLOWED),
    ((unlocked,), KARA, (gulf_fire(),), None),
]


@pytest.mark.parametrize("case", range(len(CASES)))
def test_the_check_is_what_filing_then_does(tmp_path: Path, case: int) -> None:
    changes, person, draft, expected = CASES[case]
    store = played(tmp_path, *changes)
    before = list(store.read(CAMPAIGN))
    said = check(store, person, draft)
    assert list(store.read(CAMPAIGN)) == before  # the check files nothing
    assert said == filed(store, person, draft)
    if expected is not None:
        assert said == expected
    assert set(said) == set(api.LockCheck.__annotations__)


def test_the_check_of_a_refused_order_gives_todays_refusal_words(tmp_path: Path) -> None:
    store = played(tmp_path, kites_laid_up)
    said = check(store, OLAF, (kites_to_isle(),))
    assert said["check"] == "beyond"
    assert said["reason"].startswith("The Norra Kites is not in service until 1 September")
    off = played(tmp_path / "off", unlocked)
    assert check(off, OLAF, (kites_to_isle(),)) == beyond(NOBODY)


def test_the_check_of_a_filing_already_held_is_locked_and_files_nothing(tmp_path: Path) -> None:
    store = played(tmp_path)
    first = file(store, "isle")
    before = list(store.read(CAMPAIGN))
    assert check(store, KARA, ("march", TO_ISLE)) == locked_by("Ilse Varg", HELD_FOR_ILSE)
    assert list(store.read(CAMPAIGN)) == before
    assert file(store, "isle") == first


def test_twin_worlds_differing_in_a_hidden_fact_check_and_list_the_same(tmp_path: Path) -> None:
    a = played(tmp_path / "a")
    b = played(tmp_path / "b", law_passed)
    for draft in (("march", TO_COAST), ("march", TO_ISLE), ("march", HILLS)):
        assert check(a, KARA, draft) == check(b, KARA, draft)
    for store in (a, b):
        file(store, "isle")
        file(store, "sudland_coast")
    assert no_ids(block(a, KARA)["held"]) == no_ids(block(b, KARA)["held"])
    assert len(block(a, KARA)["held"]) == 1


# --- Rule 5: a new action files the ask -----------------------------------------------


def test_a_held_ask_is_filed_when_the_next_wake_opens(tmp_path: Path) -> None:
    store = played(tmp_path)
    order = file(store, "isle")
    assert held.file_one(store, CAMPAIGN, seat(KARA), "ask", {"order_id": order.order_id}) is None
    assert set(state_of(store).asked) == {order.order_id}
    again = held.file_one(store, CAMPAIGN, seat(KARA), "ask", {"order_id": order.order_id})
    assert again == locks.ASKED_ALREADY


@pytest.fixture
def trio(web: Web, tmp_path: Path) -> Iterator[tuple[Realism, Client, Client, Client]]:  # noqa: F811
    world(tmp_path)
    game_ = Realism(web, str(tmp_path / "world.yaml"))
    ada = game_.seat("ada", "kara")
    bea = game_.seat("bea", "ilse")
    cyd = game_.seat("cyd", "olaf")
    make_host(game_, ada)
    begin(game_)
    yield game_, ada, bea, cyd


def test_the_check_and_ask_actions_through_the_server(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    _, ada, bea, cyd = trio
    status, out = post(ada, "check", lever="march", params=TO_ISLE)
    assert status == 200, out
    assert out == {"check": "locked", "who": "Ilse Varg", "reason": HELD_FOR_ILSE}
    status, out = post(ada, "check", lever="march", params=HILLS)
    assert status == 200 and out == {"check": "allowed", "who": None, "reason": ""}, out
    assert "locks" in realism_of(ada) and realism_of(ada)["locks"]["held"] == []
    status, out = post(ada, "lever", lever="march", params=TO_ISLE)
    assert status == 200 and not out["refused"], out
    (line,) = realism_of(ada)["locks"]["held"]
    assert line["asked"] is False and line["reason"] == HELD_FOR_ILSE
    assert realism_of(cyd)["locks"] == {"held": [], "asks": []}
    status, out = post(ada, "ask", order_id=line["id"])
    assert status == 200 and not out["refused"], out
    assert out["reply"] == locks_api.ASKED.format(who="Ilse Varg")
    assert realism_of(ada)["locks"]["held"][0]["asked"] is True
    (asked,) = realism_of(bea)["locks"]["asks"]
    assert (asked["by"], asked["words"]) == ("Kara Lind", ISLE_WORDS)
    status, out = post(ada, "ask", order_id=line["id"])
    assert status == 200 and out == {"reply": locks.ASKED_ALREADY, "refused": True}, out
    status, out = post(cyd, "ask", order_id=line["id"])
    assert status == 200 and out == {"reply": locks.NOT_HELD, "refused": True}, out


def test_the_check_of_a_written_order_reads_the_seats_latest_reading(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    _, ada, _, _ = trio
    status, out = post(ada, "check")
    assert status == 200, out
    assert out["check"] == "beyond" and out["reason"], out


def test_an_ask_after_the_commit_is_held_for_the_next_wake(
    trio: tuple[Realism, Client, Client, Client],
) -> None:
    _, ada, _, _ = trio
    post(ada, "lever", lever="march", params=TO_ISLE)
    (line,) = realism_of(ada)["locks"]["held"]
    status, out = post(ada, "commit")
    assert status == 200 and not out["refused"], out
    status, out = post(ada, "ask", order_id=line["id"])
    assert status == 200 and not out["refused"] and "held" in out, out
    status, out = post(ada, "ask", order_id=OrderId("nothing-held"))
    assert status == 200 and out["refused"], out


def test_ask_is_sealed_by_a_commit_and_check_is_not() -> None:
    from revisionist.engine.web.server import SEALED_BY_COMMIT

    assert "ask" in SEALED_BY_COMMIT and "check" not in SEALED_BY_COMMIT
