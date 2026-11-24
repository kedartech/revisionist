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
    assert set(shown) == api.LocksBlock.__required_keys__
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
    assert set(said) == api.LockCheck.__required_keys__


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


# --- Sending it anyway (DFR): the price in the check, and the incident ---------------
#
# The defiance world of ``tests/test_defiance.py``: ``posts`` and ``defiance`` on, Norra at
# peace with Sudland, Kara's command a post whose list of acts each case sets, and a
# written march to the Isle held for Ilse by the ``isle_move`` row.


def _to_isle() -> Ask:
    return written(MoveForce(force=LEVY, to=ISLE))


def _sent(store: MemoryStore, order_id: OrderId) -> bool:
    try:
        realism_tick.send_anyway(store, CAMPAIGN, seat(KARA), order_id)
    except ValueError:
        return False
    return True


ANYWAY_CASES = [("border", True), ("", False), ("fire_first", False)]


@pytest.mark.parametrize(("acts", "may"), ANYWAY_CASES)
def test_the_check_of_a_held_order_names_the_price_exactly_when_sending_it_anyway_goes(
    tmp_path: Path, acts: str, may: bool
) -> None:
    from tests.test_defiance import defiant

    store = played(tmp_path, isle_move, defiant(*filter(None, [acts])))
    before = list(store.read(CAMPAIGN))
    said = check(store, KARA, (_to_isle(),))
    assert list(store.read(CAMPAIGN)) == before  # the check files nothing
    assert said["check"] == "locked" and said["who"] == "Ilse Varg"
    filed = commit(store, KARA, _to_isle())
    assert isinstance(filed, locks.HeldOrder)
    (line,) = block(store, KARA)["held"]
    assert line.get("price") == said.get("price")
    assert ("price" in said) is may
    assert _sent(store, filed.order_id) is may
    if may:
        assert said["price"] == locks_api.PRICE.format(who="Ilse Varg")
        assert "incident" in said["price"] and "back or disown" in said["price"]
        assert "relieved" in said["price"]


def test_with_defiance_off_the_check_and_the_held_line_are_as_today(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move)
    said = check(store, KARA, (_to_isle(),))
    assert set(said) == api.LockCheck.__required_keys__
    commit(store, KARA, _to_isle())
    shown = block(store, KARA)
    assert set(shown) == api.LocksBlock.__required_keys__
    assert all(set(h) == api.HeldLine.__required_keys__ for h in shown["held"])


def test_a_form_order_has_no_act_so_it_never_checks_with_a_price(tmp_path: Path) -> None:
    from tests.test_defiance import defiant

    store = played(tmp_path, defiant("border", "fire_first"))
    said = check(store, KARA, ("march", TO_ISLE))
    assert said == locked_by("Ilse Varg", HELD_FOR_ILSE)
    order = file(store, "isle")
    assert "price" not in block(store, KARA)["held"][0]
    assert not _sent(store, order.order_id)


def test_the_price_is_read_from_the_seats_own_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: a price that named the superior from the true state would not follow the
    seat's view."""
    from tests.test_defiance import defiant

    store = played(tmp_path, isle_move, defiant("border"))
    from revisionist.core.project import project as real

    def seen(state: State, at: Any) -> Any:
        view = real(state, at)
        ilse = view.entities[ILSE].model_copy(update={"name": "the Chancellor"})
        return view.model_copy(update={"entities": {**view.entities, ILSE: ilse}})

    monkeypatch.setattr(locks_api, "project", seen)
    said = check(store, KARA, (_to_isle(),))
    assert said["price"] == locks_api.PRICE.format(who="the Chancellor")


def test_twin_worlds_differing_in_a_hidden_fact_price_the_same(tmp_path: Path) -> None:
    from tests.test_defiance import defiant

    a = played(tmp_path / "a", isle_move, defiant("border"))
    b = played(tmp_path / "b", isle_move, defiant("border"), law_passed)
    assert check(a, KARA, (_to_isle(),)) == check(b, KARA, (_to_isle(),))
    for store in (a, b):
        commit(store, KARA, _to_isle())
    assert no_ids(block(a, KARA)["held"]) == no_ids(block(b, KARA)["held"])
    assert [h.get("price") for h in block(a, KARA)["held"]] == [
        h.get("price") for h in block(b, KARA)["held"]
    ]


def test_another_seat_is_never_offered_ones_held_order_to_send_anyway(tmp_path: Path) -> None:
    from tests.test_defiance import defiant

    store = played(tmp_path, isle_move, defiant("border"))
    filed = commit(store, KARA, _to_isle())
    assert isinstance(filed, locks.HeldOrder)
    for person in (ILSE, OLAF):
        assert block(store, person)["held"] == []
        assert filed.order_id not in json.dumps(realism(store, person))


# --- The incident: the superior's list, the commander's list, the answer -------------


def _incident(tmp: Path, *more: Callable[[World], None]) -> tuple[MemoryStore, Any]:
    from tests.test_defiance import defiant

    store = played(tmp, isle_move, defiant("border"), *more)
    filed = commit(store, KARA, _to_isle())
    assert isinstance(filed, locks.HeldOrder)
    realism_tick.send_anyway(store, CAMPAIGN, seat(KARA), filed.order_id)
    state = tick_until(store, lambda s: bool(s.incidents))
    (incident,) = state.incidents.values()
    return store, incident


def _incidents(store: MemoryStore, person: EntityId) -> list[api.IncidentLine]:
    return block(store, person)["incidents"]


def test_the_incident_is_before_the_superior_with_three_answers_and_in_his_notice(
    tmp_path: Path,
) -> None:
    from revisionist.engine import notice

    store, incident = _incident(tmp_path)
    state = state_of(store)
    (line,) = _incidents(store, ILSE)
    assert line["id"] == incident.incident_id
    assert line["answers"] == ["backed", "disowned", "dismissed"]
    assert line["verdict"] is None and line["due"] == incident.due.isoformat()
    assert "Kara Lind" in line["words"]
    (due,) = [m for m in agenda_api.due_matters(state, seat(ILSE)) if m.kind == "incident"]
    assert due == agenda_api.DueMatter(
        "incident",
        incident.incident_id,
        locks_api.SENT_WITHOUT_LEAVE,
        "Kara Lind",
        incident.due.isoformat(),
    )
    line_ = f"- Kara Lind: {locks_api.SENT_WITHOUT_LEAVE}. Due {incident.due.isoformat()}."
    assert line_ in notice._waiting(state, seat(ILSE))
    assert line_ not in notice._waiting(state, seat(KARA))
    for person in (KARA, OLAF):
        kinds = {m.kind for m in agenda_api.due_matters(state, seat(person))}
        assert "incident" not in kinds


def test_the_commanders_seat_sees_the_incident_and_then_its_answer(tmp_path: Path) -> None:
    from revisionist.core.realism import defiance

    store, incident = _incident(tmp_path)
    (line,) = _incidents(store, KARA)
    view = project(state_of(store), seat(KARA))
    assert line["words"] == defiance.told(view, view.incidents[incident.incident_id])
    assert line["answers"] == [] and line["verdict"] is None
    done = agenda_api.answer_incident(store, CAMPAIGN, seat(ILSE), incident.incident_id, "backed")
    assert done == {"reply": "You have backed Kara Lind.", "refused": False}
    (line,) = _incidents(store, KARA)
    assert line["verdict"] == "backed" and "Ilse Varg has backed you" in line["words"]
    (theirs,) = _incidents(store, ILSE)
    assert theirs["verdict"] == "backed" and theirs["answers"] == []
    assert not [
        m for m in agenda_api.due_matters(state_of(store), seat(ILSE)) if m.kind == "incident"
    ]


def test_only_the_superiors_seat_answers_the_incident_and_with_one_of_three(
    tmp_path: Path,
) -> None:
    from revisionist.core.realism import defiance

    store, incident = _incident(tmp_path)
    for person in (KARA, OLAF):
        done = agenda_api.answer_incident(
            store, CAMPAIGN, seat(person), incident.incident_id, "backed"
        )
        assert done == {"reply": defiance.NOT_YOURS, "refused": True}
    done = agenda_api.answer_incident(store, CAMPAIGN, seat(ILSE), incident.incident_id, "maybe")
    assert done["refused"] and "backed, disowned, dismissed" in done["reply"]
    assert state_of(store).incidents[incident.incident_id].verdict is None


def test_the_incident_is_absent_from_every_other_seats_data(tmp_path: Path) -> None:
    store, incident = _incident(tmp_path)
    for person in (ILSE, KARA, OLAF):
        data = json.dumps(realism(store, person))
        assert (incident.incident_id in data) is (person in (ILSE, KARA))
    assert _incidents(store, OLAF) == []


def test_unanswered_by_its_day_the_superiors_card_answers_and_both_lists_show_it(
    tmp_path: Path,
) -> None:
    store, incident = _incident(tmp_path)
    tick_until(store, lambda s: s.incidents[incident.incident_id].verdict is not None)
    (kara,) = _incidents(store, KARA)
    (ilse,) = _incidents(store, ILSE)
    assert kara["verdict"] is not None and kara["verdict"] == ilse["verdict"]
    assert ilse["answers"] == []


def test_with_defiance_off_no_incident_kind_is_due(tmp_path: Path) -> None:
    store = played(tmp_path)
    for person in (ILSE, KARA, OLAF):
        kinds = {m.kind for m in agenda_api.due_matters(state_of(store), seat(person))}
        assert "incident" not in kinds
        assert "incidents" not in block(store, person)


# --- The actions through the server ---------------------------------------------------


@pytest.fixture
def defiers(web: Web, tmp_path: Path) -> Iterator[tuple[Realism, Client, Client, Client]]:  # noqa: F811
    from tests.test_defiance import defiant

    world(tmp_path, isle_move, defiant("border"))
    game_ = Realism(web, str(tmp_path / "world.yaml"))
    ada = game_.seat("ada", "kara")
    bea = game_.seat("bea", "ilse")
    cyd = game_.seat("cyd", "olaf")
    make_host(game_, ada)
    begin(game_)
    yield game_, ada, bea, cyd


def _web_held(game_: Realism) -> locks.HeldOrder:
    from revisionist.core.ids import SeatId, derived_id

    store = game_.web.app.open()
    try:
        kara = SeatId(derived_id(game_.campaign, "seat", EntityId(game_.ids["kara"])))
        asks = (written(MoveForce(force=game_.ids["norra_levy"], to=game_.ids["isle"])),)
        filed = realism_tick.commit_order(store, game_.campaign, kara, asks)
    finally:
        store.close()
    assert isinstance(filed, locks.HeldOrder)
    return filed


def test_the_send_anyway_action_sends_the_held_order(
    defiers: tuple[Realism, Client, Client, Client],
) -> None:
    from revisionist.core.realism import defiance

    game_, ada, _, cyd = defiers
    filed = _web_held(game_)
    (line,) = realism_of(ada)["locks"]["held"]
    assert line["id"] == filed.order_id and line["price"] == locks_api.PRICE.format(who="Ilse Varg")
    status, out = post(cyd, "send-anyway", order_id=filed.order_id)
    assert status == 200 and out == {"reply": locks.NOT_HELD, "refused": True}, out
    status, out = post(ada, "send-anyway", order_id=filed.order_id)
    assert status == 200 and not out["refused"], out
    assert out["reply"] == locks_api.SENT_ANYWAY.format(words=line["words"])
    assert realism_of(ada)["locks"]["held"] == []
    status, out = post(ada, "send-anyway", order_id=filed.order_id)
    assert status == 200 and out == {"reply": locks.NOT_HELD, "refused": True}, out
    assert defiance.NOT_WITHOUT_LEAVE  # the refusal words when the post gives no leave


def test_send_anyway_after_the_commit_is_held_for_the_next_wake(
    defiers: tuple[Realism, Client, Client, Client],
) -> None:
    game_, ada, _, _ = defiers
    filed = _web_held(game_)
    status, out = post(ada, "commit")
    assert status == 200 and not out["refused"], out
    status, out = post(ada, "send-anyway", order_id=filed.order_id)
    assert status == 200 and not out["refused"] and "held" in out, out
    status, out = post(ada, "send-anyway", order_id="nothing-held")
    assert status == 200 and out["refused"], out


def test_send_anyway_is_sealed_by_a_commit() -> None:
    from revisionist.engine.web.server import REALISM_ACTIONS, SEALED_BY_COMMIT

    assert "send-anyway" in REALISM_ACTIONS and "send-anyway" in SEALED_BY_COMMIT


def test_a_held_send_anyway_is_sent_when_the_next_wake_opens(tmp_path: Path) -> None:
    from tests.test_defiance import defiant

    store = played(tmp_path, isle_move, defiant("border"))
    filed = commit(store, KARA, _to_isle())
    assert isinstance(filed, locks.HeldOrder)
    args = {"order_id": filed.order_id}
    assert held.file_one(store, CAMPAIGN, seat(KARA), "send-anyway", args) is None
    assert [d.order_id for d in state_of(store).defied.values()] == [filed.order_id]
    again = held.file_one(store, CAMPAIGN, seat(KARA), "send-anyway", args)
    assert again == locks.NOT_HELD


def test_a_held_send_anyway_the_post_gives_no_leave_for_is_dropped_in_fixed_words(
    tmp_path: Path,
) -> None:
    from revisionist.core.realism import defiance
    from tests.test_defiance import defiant

    store = played(tmp_path, isle_move, defiant("fire_first"))
    filed = commit(store, KARA, _to_isle())
    assert isinstance(filed, locks.HeldOrder)
    args = {"order_id": filed.order_id}
    said = held.file_one(store, CAMPAIGN, seat(KARA), "send-anyway", args)
    assert said == defiance.NOT_WITHOUT_LEAVE
    assert state_of(store).defied == {}


def test_the_answer_action_carries_the_verdict_for_an_incident(tmp_path: Path) -> None:
    store, incident = _incident(tmp_path)
    args = {"item": incident.incident_id, "verdict": "disowned"}
    assert held.file_one(store, CAMPAIGN, seat(ILSE), "answer", args) is None
    verdict = state_of(store).incidents[incident.incident_id].verdict
    assert verdict is not None and verdict.value == "disowned"
