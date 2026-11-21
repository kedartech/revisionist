"""Deciders and what locks an order (DCD).

The tests' own world is the toy world (``tests/worlds/territory-toy.yaml``) with the
``locks`` rule on and three people under the chancellor, Ilse Varg: her general, Kara
Lind (a military card with the Norra Levy, from the commander tests), and Kara's aide,
Olaf Brun, who commands nothing. Ilse commands the Norra Kites and, above Kara, the levy
too. Three locks, one of each decider kind and one for each path:

- ``island_march``: Kara's march to the Isle needs Ilse (a person) while she has not set a
  watch on the Gulf, by her own form or by a written engagement.
- ``coast_march``: Kara's march to the Sudland Coast needs Norra's assembly (a body)
  while no law arming merchant ships is in force for Norra.
- ``gulf_fire``: a written engagement in the Gulf always needs Ilse.

The shared toy world is left as it is, so every other test that reads it is unchanged.
"""

import ast
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core import events as ev
from revisionist.core.fold import replay, state_hash
from revisionist.core.ids import (
    EntityId,
    FeatureId,
    OrderId,
    PipelineId,
    QuantityId,
    SeatId,
    derived_id,
)
from revisionist.core.realism import locks
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.effect import (
    Engagement,
    Fidelity,
    MoveForce,
    Route,
    RoutedOrder,
    RoutedPart,
    SetEngagement,
)
from revisionist.core.realism.locks import Decider, Lock, lock_for
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.state import Rule, State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.store import MemoryStore, load_state
from tests.test_realism_command import card, general
from tests.test_territory_model import CAMPAIGN, created, refused, variant

World = dict[str, Any]
ROOT = Path(__file__).resolve().parents[1]
DAY = date(1900, 4, 2)
LAW = "arm merchant ships"
"""A clause a law the rules know carries (``votes.in_force``, read only)."""
FLAG = "arm_merchant_ships_passed"


def key_id(key: str) -> EntityId:
    return EntityId(object_id(CAMPAIGN, "entity", key))


ILSE, KARA, OLAF = key_id("ilse"), key_id("kara"), key_id("olaf")
NORRA, GULF, ISLE = key_id("norra"), key_id("the_gulf"), key_id("isle")
LEVY = FeatureId(object_id(CAMPAIGN, "feature", "norra_levy"))
KITES = FeatureId(object_id(CAMPAIGN, "feature", "norra_kites"))


def seat(person: EntityId) -> SeatId:
    return SeatId(derived_id(CAMPAIGN, "seat", person))


def aide(w: World) -> None:
    """Olaf Brun, Kara's aide, who commands nothing; Ilse commands the kites and the levy."""
    w["entities"].append({"key": "olaf", "kind": "person", "name": "Olaf Brun", "parent": "norra"})
    w["cards"].append(
        {
            "person": "olaf",
            "office": "Aide to the General",
            "playable": True,
            "principals": ["kara"],
            "horizon_days": 14,
        }
    )
    w["roster"].append(
        {"entity": "olaf", "pitch": "The aide.", "reach": "Nothing.", "composite": True}
    )
    card(w, "ilse")["inner_circle"] = [{"person": "kara", "channel": "letter"}]
    card(w, "ilse")["authority"] = [
        {
            "name": "the_forces",
            "effects": ["move_force", "engagement"],
            "forces": ["norra_kites", "norra_levy"],
        }
    ]


def forms(w: World) -> None:
    """Kara's ``march`` moves the levy; Ilse's ``set_watch`` sets a watch on a water."""
    w["pipelines"] = [
        {
            "key": "clerks",
            "name": "The clerks",
            "source": "toy",
            "steps": [{"person": "kara", "kind": "clerical", "days": 1}],
        }
    ]
    card(w, "kara")["pipelines"] = ["clerks"]
    card(w, "kara")["levers"] = [
        {
            "name": "march",
            "pipeline": "clerks",
            "resolver": "movement",
            "params": [
                {"name": "force", "kind": "enum", "choices": ["norra_levy"]},
                {"name": "to", "kind": "enum", "choices": ["norra_hills", "sudland_coast", "isle"]},
            ],
        }
    ]
    card(w, "ilse")["pipelines"] = ["clerks"]
    card(w, "ilse")["levers"] = [
        {
            "name": "set_watch",
            "pipeline": "clerks",
            "resolver": "shipping",
            "params": [
                {"name": "zone", "kind": "enum", "choices": ["gulf", "open"]},
                {"name": "order", "kind": "enum", "choices": ["guard", "stand_down"]},
            ],
        }
    ]
    w["quantities"].append(
        {
            "key": FLAG,
            "owner": "norra",
            "name": "Arming law passed",
            "value": 0,
            "unit": "flag",
            "source": "toy",
        }
    )


ROWS: list[World] = [
    {
        "key": "island_march",
        "order": {"form": "march", "params": {"to": "isle"}},
        "when": {
            "check": "posture_not_set",
            "zone": "the_gulf",
            "rule": "shoot_on_sight",
            "form": "set_watch",
            "where": {"zone": "gulf"},
            "posture": {"order": "guard"},
        },
        "decider": {"person": "ilse"},
    },
    {
        "key": "coast_march",
        "order": {"form": "march", "params": {"to": "sudland_coast"}},
        "when": {"check": "law_not_in_force", "clause": LAW},
        "decider": {"nation": "norra", "chambers": ["assembly"]},
    },
    {
        "key": "gulf_fire",
        "order": {"effect": "engagement", "zone": "the_gulf"},
        "decider": {"person": "ilse"},
    },
]


def locked(w: World) -> None:
    w["rules"] = sorted({*w["rules"], "locks"})
    w["locks"] = [dict(r) for r in ROWS]


def world(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    def change(w: World) -> None:
        for c in (general, aide, forms, locked, *changes):
            c(w)

    return variant(tmp, change)


def game(tmp: Path, *changes: Callable[[World], None]) -> State:
    """The game with Ilse, Kara and Olaf each claimed by a seat of their own."""
    events, _ = created(world(tmp, *changes))
    more = list(events)
    for person in (ILSE, KARA, OLAF):
        last = more[-1]
        claimed = ev.CharacterClaimed(seat_id=seat(person), entity_id=person)
        more.append(
            last.model_copy(
                update={
                    "seq": last.seq + 1,
                    "event_id": derived_id(CAMPAIGN, "event", str(last.seq + 1)),
                    "payload": claimed,
                }
            )
        )
    return replay(more)


def march(to: str, issuer: EntityId = KARA) -> Order:
    return Order(
        order_id=OrderId(derived_id(CAMPAIGN, "order", to)),
        issuer=seat(issuer),
        lever="march",
        pipeline=PipelineId(object_id(CAMPAIGN, "pipeline", "clerks")),
        params={"force": "norra_levy", "to": to},
        filed=DAY,
    )


def written(effect: MoveForce | SetEngagement) -> Ask:
    return Ask(ask="as written", effect=effect)


def gulf_fire(zone: str = GULF) -> Ask:
    return written(SetEngagement(zone=zone, rule=Engagement.SHOOT_ON_SIGHT))


def row(state: State, key: str) -> locks.LockRow:
    return next(r for r in state.locks if r.key == key)


# --- The declaration ---------------------------------------------------------------


def test_the_locks_reach_state_once_through_one_public_declaration(tmp_path: Path) -> None:
    events, state = created(world(tmp_path))
    declared = [e for e in events if isinstance(e.payload, ev.LocksDeclared)]
    assert len(declared) == 1 and declared[0].scope.visibility.value == "public"
    assert [r.key for r in state.locks] == ["island_march", "coast_march", "gulf_fire"]
    assert row(state, "island_march").decider == Decider(person=ILSE)
    assert row(state, "coast_march").decider == Decider(nation=NORRA, chambers=("assembly",))
    assert row(state, "gulf_fire").order.zone == GULF


def test_with_locks_off_the_rows_are_checked_and_left_out(tmp_path: Path) -> None:
    def off(w: World) -> None:
        w["rules"] = [r for r in w["rules"] if r != "locks"]

    events, state = created(world(tmp_path, off))
    assert not [e for e in events if isinstance(e.payload, ev.LocksDeclared)]
    assert state.locks == ()

    def unlocked(w: World) -> None:
        for c in (general, aide, forms):
            c(w)

    plain, _ = created(variant(tmp_path, unlocked))
    assert [e.payload for e in events] == [e.payload for e in plain]


def test_a_world_without_locks_compiles_as_before(tmp_path: Path) -> None:
    _, state = created(cmp.load_world(ROOT / "tests" / "worlds" / "territory-toy.yaml"))
    assert state.locks == ()
    assert "locks" not in state.model_dump(mode="json")


def test_the_declaration_folds_once_and_only_with_the_rule() -> None:
    from revisionist.core.fold import FoldError, _locks_declared, empty

    lock = locks.LockRow(key="k", order=locks.OrderMatch(form="f"), decider=Decider(person=ILSE))
    blank = empty(CAMPAIGN)
    with pytest.raises(FoldError, match="needs the locks rule"):
        _locks_declared(blank, ev.LocksDeclared(rows=(lock,)))


# --- A person decides, by form, with a posture condition ----------------------------


def test_a_form_row_holds_the_order_for_its_person(tmp_path: Path) -> None:
    state = game(tmp_path)
    assert lock_for(state, seat(KARA), march("isle")) == Lock(
        row=row(state, "island_march"), decider=Decider(person=ILSE)
    )
    assert lock_for(state, seat(KARA), march("norra_hills")) is None


def test_a_superiors_watch_set_by_her_form_opens_the_posture(tmp_path: Path) -> None:
    state = game(tmp_path)

    def watch(order: str, n: int, on: date) -> Order:
        return Order(
            order_id=OrderId(derived_id(CAMPAIGN, "watch", str(n))),
            issuer=seat(ILSE),
            lever="set_watch",
            pipeline=PipelineId(object_id(CAMPAIGN, "pipeline", "clerks")),
            params={"zone": "gulf", "order": order},
            filed=on,
            status=OrderStatus.ENACTED,
        )

    guard = watch("guard", 1, DAY)
    set_ = state.model_copy(update={"orders": {**state.orders, guard.order_id: guard}})
    assert lock_for(set_, seat(KARA), march("isle")) is None
    later = watch("stand_down", 2, date(1900, 4, 5))
    undone = set_.model_copy(update={"orders": {**set_.orders, later.order_id: later}})
    assert lock_for(undone, seat(KARA), march("isle")) is not None
    moving = guard.model_copy(update={"status": OrderStatus.MOVING})
    pending = state.model_copy(update={"orders": {**state.orders, moving.order_id: moving}})
    assert lock_for(pending, seat(KARA), march("isle")) is not None


def test_a_superiors_written_engagement_opens_the_posture_too(tmp_path: Path) -> None:
    state = game(tmp_path)

    def engaged(issuer: EntityId, rule: Engagement) -> State:
        part = RoutedPart(
            route=Route.COMMAND,
            effect=SetEngagement(zone="The Gulf", rule=rule),
            domain="the_forces",
            fidelity=Fidelity.FULL,
            executed=DAY,
            applied=DAY,
        )
        routed = RoutedOrder(
            order_id=OrderId(derived_id(CAMPAIGN, "routed", str(issuer))),
            issuer=seat(issuer),
            filed=DAY,
            parts=(part,),
        )
        return state.model_copy(update={"routed": {routed.order_id: routed}})

    assert lock_for(engaged(ILSE, Engagement.SHOOT_ON_SIGHT), seat(KARA), march("isle")) is None
    assert lock_for(engaged(ILSE, Engagement.DEFEND), seat(KARA), march("isle")) is not None
    # Only a superior sets it: the aide's own engagement does not open the general's march.
    assert lock_for(engaged(OLAF, Engagement.SHOOT_ON_SIGHT), seat(KARA), march("isle"))


# --- A body decides, with a law condition --------------------------------------------


def test_a_law_row_holds_the_order_for_the_chamber_until_the_law_is_in_force(
    tmp_path: Path,
) -> None:
    state = game(tmp_path)
    found = lock_for(state, seat(KARA), march("sudland_coast"))
    assert found is not None and found.decider == Decider(nation=NORRA, chambers=("assembly",))
    qid = QuantityId(object_id(CAMPAIGN, "quantity", FLAG))
    passed = state.quantities[qid].model_copy(update={"value": 1})
    law = state.model_copy(update={"quantities": {**state.quantities, qid: passed}})
    assert lock_for(law, seat(KARA), march("sudland_coast")) is None


# --- Written orders: a row, or the derived decider -----------------------------------


def test_a_written_order_matching_an_effect_row_is_held_by_it(tmp_path: Path) -> None:
    state = game(tmp_path)
    assert lock_for(state, seat(KARA), gulf_fire()) == Lock(
        row=row(state, "gulf_fire"), decider=Decider(person=ILSE)
    )
    assert lock_for(state, seat(KARA), gulf_fire("The Gulf")) is not None
    # The decider's own order is never held by the row: Ilse commands the kites herself.
    mine = written(SetEngagement(force=KITES, zone=GULF, rule=Engagement.SHOOT_ON_SIGHT))
    assert lock_for(state, seat(ILSE), mine) is None


def test_the_derived_decider_is_the_nearest_card_up_the_chain_that_covers_it(
    tmp_path: Path,
) -> None:
    state = game(tmp_path)
    levy = written(MoveForce(force=LEVY, to=ISLE))
    kites = written(MoveForce(force=KITES, to=ISLE))
    # One step: the aide's order to the levy belongs to the general, the nearest of the
    # two cards above him that command it.
    assert lock_for(state, seat(OLAF), levy) == Lock(decider=Decider(person=KARA))
    # Two steps: the kites belong to neither the aide nor the general, but to Ilse.
    assert lock_for(state, seat(OLAF), kites) == Lock(decider=Decider(person=ILSE))
    assert lock_for(state, seat(KARA), kites) == Lock(decider=Decider(person=ILSE))


def test_a_written_order_inside_the_issuers_domains_or_above_every_card_is_not_held(
    tmp_path: Path,
) -> None:
    state = game(tmp_path)
    assert lock_for(state, seat(KARA), written(MoveForce(force=LEVY, to=ISLE))) is None
    sudland_levy = FeatureId(object_id(CAMPAIGN, "feature", "sudland_levy"))
    assert lock_for(state, seat(OLAF), written(MoveForce(force=sudland_levy, to=ISLE))) is None
    assert lock_for(state, seat(OLAF), Ask(ask="words only", target=KARA)) is None


def test_with_locks_off_nothing_is_held_even_with_rows_in_state(tmp_path: Path) -> None:
    state = game(tmp_path)
    off = state.model_copy(update={"rules": state.rules - {Rule.LOCKS}})
    assert off.locks
    for order in (march("isle"), march("sudland_coast")):
        assert lock_for(off, seat(KARA), order) is None
    assert lock_for(off, seat(KARA), gulf_fire()) is None
    assert lock_for(off, seat(OLAF), written(MoveForce(force=KITES, to=ISLE))) is None


def test_lock_for_is_a_pure_function_of_state(tmp_path: Path) -> None:
    state = game(tmp_path)
    again = game(tmp_path)
    for who, order in (
        (KARA, march("isle")),
        (KARA, march("sudland_coast")),
        (KARA, gulf_fire()),
        (OLAF, written(MoveForce(force=KITES, to=ISLE))),
    ):
        first = lock_for(state, seat(who), order)
        assert first is not None
        assert first == lock_for(state, seat(who), order) == lock_for(again, seat(who), order)


def test_the_seats_view_holds_the_same_public_rows(tmp_path: Path) -> None:
    from revisionist.core.project import project

    state = game(tmp_path)
    assert project(state, seat(KARA)).locks == state.locks == project(state, seat(OLAF)).locks


# --- The compiler refuses a row that names what does not exist -----------------------


def only(r: World) -> Callable[[World], None]:
    def edit(w: World) -> None:
        w["locks"] = [r]

    return edit


@pytest.mark.parametrize(
    ("bad", "problem"),
    [
        (
            {"key": "x", "order": {"form": "sail"}, "decider": {"person": "ilse"}},
            "lock x: no card carries the form sail",
        ),
        (
            {
                "key": "x",
                "order": {"form": "march", "params": {"pace": 3}},
                "decider": {"person": "ilse"},
            },
            "lock x: the form march has no parameter pace",
        ),
        (
            {
                "key": "x",
                "order": {"form": "march", "params": {"to": "atlantis"}},
                "decider": {"person": "ilse"},
            },
            "lock x: 'atlantis' does not fit march's to",
        ),
        (
            {
                "key": "x",
                "order": {"effect": "engagement", "zone": "the_sound"},
                "decider": {"person": "ilse"},
            },
            "lock x: unknown area or place the_sound",
        ),
        (
            {
                "key": "x",
                "order": {"effect": "move_force", "force": "norra_fleet"},
                "decider": {"person": "ilse"},
            },
            "lock x: unknown feature norra_fleet",
        ),
        (
            {
                "key": "x",
                "order": {"form": "march"},
                "when": {"check": "law_not_in_force", "clause": "hold the passes"},
                "decider": {"person": "ilse"},
            },
            "lock x: no law the world declares carries the clause 'hold the passes'",
        ),
        (
            {"key": "x", "order": {"form": "march"}, "decider": {"person": "greta"}},
            "lock x: unknown person greta",
        ),
        (
            {"key": "x", "order": {"form": "march"}, "decider": {"person": "norra"}},
            "lock x: unknown person norra",
        ),
        (
            {
                "key": "x",
                "order": {"form": "march"},
                "decider": {"nation": "ostmark", "chambers": ["assembly"]},
            },
            "lock x: unknown nation ostmark",
        ),
        (
            {
                "key": "x",
                "order": {"form": "march"},
                "decider": {"nation": "norra", "chambers": ["senate"]},
            },
            "lock x: norra has no chamber senate",
        ),
        (
            {
                "key": "x",
                "order": {"form": "march"},
                "decider": {"nation": "sudland", "chambers": ["assembly"]},
            },
            "lock x: sudland has no chamber assembly",
        ),
        (
            {"key": "x", "order": {"form": "march"}, "decider": {"person": "kara"}},
            "lock x: kara carries the form and would decide an order of their own",
        ),
        (
            {
                "key": "x",
                "order": {"form": "march"},
                "when": {"check": "posture_not_set", "zone": "the_sound", "rule": "defend"},
                "decider": {"person": "ilse"},
            },
            "lock x: unknown area or place the_sound",
        ),
        (
            {
                "key": "x",
                "order": {"form": "march"},
                "when": {
                    "check": "posture_not_set",
                    "form": "set_watch",
                    "where": {"zone": "fjord"},
                    "posture": {"order": "guard"},
                },
                "decider": {"person": "ilse"},
            },
            "lock x: 'fjord' does not fit set_watch's zone",
        ),
        (
            {
                "key": "x",
                "order": {"form": "march", "effect": "engagement"},
                "decider": {"person": "ilse"},
            },
            "lock x: a lock names a form or an effect kind, not both",
        ),
    ],
)
def test_a_row_naming_what_does_not_exist_is_refused(
    tmp_path: Path, bad: World, problem: str
) -> None:
    assert problem in refused(world(tmp_path, only(bad)))


def test_a_repeated_row_key_is_refused(tmp_path: Path) -> None:
    def twice(w: World) -> None:
        w["locks"] = [ROWS[2], ROWS[2]]

    assert "lock gulf_fire: duplicate key" in refused(world(tmp_path, twice))


def test_a_legacy_world_may_not_carry_locks(tmp_path: Path) -> None:
    def legacy(w: World) -> None:
        w["ruleset"] = "legacy"

    problems = refused(world(tmp_path, legacy))
    assert "locks: only a realism world has locks" in problems


# --- No rule names a place, a nation, a person, a bill or a form ---------------------


def _world_words() -> set[str]:
    words: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in {"key", "name", "person", "nation", "office", "title"} and isinstance(
                    v, str
                ):
                    words.add(v)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for path in [
        *(ROOT / "worlds").glob("*.yaml"),
        ROOT / "tests" / "worlds" / "territory-toy.yaml",
    ]:
        walk(yaml.safe_load(path.read_text()))
    return words


def test_the_lock_rules_name_nothing_from_any_world() -> None:
    source = (ROOT / "src" / "revisionist" / "core" / "realism" / "locks.py").read_text()
    literals = {
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    named = sorted(literals & (_world_words() | {"set_watch", "march", "assembly", LAW}))
    assert not named, f"locks.py names world data: {named}"


# --- The held order (LCK) ------------------------------------------------------------
#
# The game in an event store, with Ilse, Kara and Olaf each played. Kara's march to the
# Isle is held for Ilse by form; her shot in the Gulf is held for Ilse by a written row;
# Olaf's order to the kites, which nobody under him commands, is held for Ilse, the
# nearest card above him that does.

HELD_FOR_ILSE = "Held until Ilse Varg allows it."
HELD_FOR_ASSEMBLY = "Held until Norra's assembly allows it."


def isle_move(w: World) -> None:
    """A written row: any move to the Isle needs Ilse."""
    w["locks"].append(
        {
            "key": "isle_move",
            "order": {"effect": "move_force", "zone": "isle"},
            "decider": {"person": "ilse"},
        }
    )


def public_law(w: World) -> None:
    """The arming law's passed flag is public, so every seat can see whether it passed."""
    next(q for q in w["quantities"] if q["key"] == FLAG)["public"] = True


def law_passed(w: World) -> None:
    next(q for q in w["quantities"] if q["key"] == FLAG)["value"] = 1


def kites_laid_up(w: World) -> None:
    next(f for f in w["features"] if f["key"] == "norra_kites")["in_service"] = "1900-09-01"


def unlocked(w: World) -> None:
    w["rules"] = [r for r in w["rules"] if r != "locks"]


def played(tmp: Path, *changes: Callable[[World], None]) -> MemoryStore:
    tmp.mkdir(parents=True, exist_ok=True)
    store = MemoryStore()
    store.append_all(compile_world(world(tmp, *changes), CAMPAIGN, cmp.versions()))
    state = load_state(store, CAMPAIGN)
    for person in (ILSE, KARA, OLAF):
        session_zero.claim(store, CAMPAIGN, seat(person), state.entities[person].name)
    realism_tick.open_play(store, CAMPAIGN)
    return store


def file(store: MemoryStore, to: str, person: EntityId = KARA) -> Order:
    params = {"force": "norra_levy", "to": to}
    return realism_tick.file_order(store, CAMPAIGN, seat(person), "march", params)


def commit(store: MemoryStore, person: EntityId, *asks: Ask) -> RoutedOrder | locks.HeldOrder:
    return realism_tick.commit_order(store, CAMPAIGN, seat(person), asks)


def kites_to_isle(words: str = "Send the kites to the Isle.") -> Ask:
    return Ask(ask=words, effect=MoveForce(force=KITES, to=ISLE))


def logged(store: MemoryStore, kind: type[Any]) -> list[Any]:
    return [e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, kind)]


def test_a_form_order_a_lock_holds_is_stored_held_not_carried_out(tmp_path: Path) -> None:
    store = played(tmp_path)
    order = file(store, "isle")
    state = load_state(store, CAMPAIGN)
    held = state.held[order.order_id]
    assert held.form == order and held.row == "island_march"
    assert held.decider == Decider(person=ILSE) and held.reason == HELD_FOR_ILSE
    assert order.order_id not in state.orders and not logged(store, ev.OrderDrafted)
    plain = file(store, "norra_hills")
    assert plain.order_id in load_state(store, CAMPAIGN).orders


def test_a_written_order_a_lock_holds_is_stored_held_with_every_ask(tmp_path: Path) -> None:
    store = played(tmp_path)
    shot = commit(store, KARA, gulf_fire())
    assert isinstance(shot, locks.HeldOrder)
    assert (shot.row, shot.decider, shot.asks) == (
        "gulf_fire",
        Decider(person=ILSE),
        (gulf_fire(),),
    )
    derived = commit(store, OLAF, kites_to_isle())
    assert isinstance(derived, locks.HeldOrder)
    assert (derived.row, derived.decider, derived.reason) == (
        None,
        Decider(person=ILSE),
        HELD_FOR_ILSE,
    )
    state = load_state(store, CAMPAIGN)
    assert set(state.held) == {shot.order_id, derived.order_id} and not state.routed
    # A command the issuer's own domain takes, and no row holds, lands as before.
    landed = commit(store, KARA, written(MoveForce(force=LEVY, to=key_id("norra_hills"))))
    assert isinstance(landed, RoutedOrder)


def test_a_routed_command_a_written_row_holds_is_held(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move)
    filed = commit(store, KARA, written(MoveForce(force=LEVY, to=ISLE)))
    assert isinstance(filed, locks.HeldOrder) and filed.row == "isle_move"


def test_with_locks_off_every_order_is_refused_or_carried_out_as_before(tmp_path: Path) -> None:
    store = played(tmp_path, unlocked)
    assert file(store, "isle").order_id in load_state(store, CAMPAIGN).orders
    for person, ask in ((KARA, gulf_fire()), (OLAF, kites_to_isle())):
        with pytest.raises(ValueError, match="Nobody under you commands that"):
            commit(store, person, ask)
    assert not load_state(store, CAMPAIGN).held


def test_a_refusal_of_todays_still_refuses_first_in_its_own_words(tmp_path: Path) -> None:
    store = played(tmp_path, kites_laid_up)
    with pytest.raises(ValueError, match=r"^The Norra Kites is not in service until 1 September"):
        commit(store, OLAF, kites_to_isle())
    with pytest.raises(ValueError) as caught:
        realism_tick.file_order(store, CAMPAIGN, seat(KARA), "march", {"force": "norra_levy"})
    unlocked_store = played(tmp_path / "off", kites_laid_up, unlocked)
    with pytest.raises(ValueError) as before:
        realism_tick.file_order(
            unlocked_store, CAMPAIGN, seat(KARA), "march", {"force": "norra_levy"}
        )
    assert str(caught.value) == str(before.value)
    assert not load_state(store, CAMPAIGN).held


def test_the_reason_names_the_body_when_the_seat_can_see_the_law(tmp_path: Path) -> None:
    store = played(tmp_path, public_law)
    order = file(store, "sudland_coast")
    held = load_state(store, CAMPAIGN).held[order.order_id]
    assert held.decider == Decider(nation=NORRA, chambers=("assembly",))
    assert held.reason == HELD_FOR_ASSEMBLY
    passed = played(tmp_path / "passed", public_law, law_passed)
    assert file(passed, "sudland_coast").order_id in load_state(passed, CAMPAIGN).orders


def _seen(store: MemoryStore, person: EntityId) -> tuple[Any, ...]:
    """What the seat holds of its orders and papers: its held orders, with their ids left
    out, and its documents' words."""
    from revisionist.core.project import project

    view = project(load_state(store, CAMPAIGN), seat(person))
    held = sorted(
        (h.row, h.decider, h.reason, h.form and h.form.params) for h in view.held.values()
    )
    papers = sorted((d.title, d.kind) for d in view.documents.values())
    return tuple(held), tuple(papers), len(view.orders), len(view.routed)


def test_two_games_differing_only_in_a_hidden_fact_give_the_seat_the_same(tmp_path: Path) -> None:
    def run(tmp: Path, *changes: Callable[[World], None]) -> tuple[MemoryStore, Order, Order]:
        store = played(tmp, *changes)
        isle = file(store, "isle")
        coast = file(store, "sudland_coast")
        realism_tick.run_realism_tick(store, CAMPAIGN)
        return store, isle, coast

    # The arming law's flag is hidden from Kara: passed in one game, not in the other.
    a, a_isle, a_coast = run(tmp_path / "a")
    b, b_isle, b_coast = run(tmp_path / "b", law_passed)
    assert _seen(a, KARA) == _seen(b, KARA)
    # The march to the Isle is held in both, for the same reason.
    for store, isle in ((a, a_isle), (b, b_isle)):
        assert load_state(store, CAMPAIGN).held[isle.order_id].reason == HELD_FOR_ILSE
    # The march to the coast turns on the hidden law, so it goes on as an ordinary order.
    for store, coast in ((a, a_coast), (b, b_coast)):
        state = load_state(store, CAMPAIGN)
        assert coast.order_id in state.orders and coast.order_id not in state.held


def test_a_held_order_has_no_clock_expiry(tmp_path: Path) -> None:
    store = played(tmp_path)
    order = file(store, "isle")
    shot = commit(store, KARA, gulf_fire())
    for _ in range(40):
        realism_tick.run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    assert state.in_world_date is not None and state.in_world_date > DAY + timedelta(days=30)
    assert {order.order_id, shot.order_id} <= set(state.held)
    assert not logged(store, ev.HeldOrderEnded)


def test_a_later_order_to_the_same_force_and_zone_replaces_it(tmp_path: Path) -> None:
    store = played(tmp_path)
    form = file(store, "isle")
    # Another zone for the same force leaves it held.
    file(store, "norra_hills")
    assert form.order_id in load_state(store, CAMPAIGN).held
    # A written order to the same force and zone lands, and the held form order ends.
    later = commit(store, KARA, written(MoveForce(force=LEVY, to=ISLE)))
    assert isinstance(later, RoutedOrder)
    (ended,) = logged(store, ev.HeldOrderEnded)
    assert (ended.order_id, ended.end, ended.by) == (
        form.order_id,
        locks.HeldEnd.REPLACED,
        later.order_id,
    )
    assert form.order_id not in load_state(store, CAMPAIGN).held
    # A held written order is replaced by a later held one in other words.
    first = commit(store, OLAF, kites_to_isle())
    second = commit(store, OLAF, kites_to_isle("The kites to the Isle, now."))
    assert set(load_state(store, CAMPAIGN).held) == {second.order_id}
    assert logged(store, ev.HeldOrderEnded)[-1].by == second.order_id != first.order_id


def test_a_retried_filing_makes_no_second_held_order(tmp_path: Path) -> None:
    store = played(tmp_path)
    first = file(store, "isle")
    again = file(store, "isle")
    shot = commit(store, KARA, gulf_fire())
    shot_again = commit(store, KARA, gulf_fire())
    assert (again, shot_again) == (first, shot)
    assert len(logged(store, ev.OrderHeld)) == 2


def test_the_same_filing_after_the_lock_opens_lands_and_replaces_the_held_one(
    tmp_path: Path,
) -> None:
    store = played(tmp_path)
    first = file(store, "isle")
    watch = Ask(
        ask="Guard the Gulf.",
        effect=SetEngagement(force=KITES, zone=GULF, rule=Engagement.SHOOT_ON_SIGHT),
    )
    assert isinstance(commit(store, ILSE, watch), RoutedOrder)
    for _ in range(5):
        realism_tick.run_realism_tick(store, CAMPAIGN)
        if lock_for(load_state(store, CAMPAIGN), seat(KARA), march("isle")) is None:
            break
    assert lock_for(load_state(store, CAMPAIGN), seat(KARA), march("isle")) is None
    again = file(store, "isle")
    state = load_state(store, CAMPAIGN)
    assert again.order_id != first.order_id and again.order_id in state.orders
    assert first.order_id not in state.held
    assert logged(store, ev.HeldOrderEnded)[-1].by == again.order_id


def test_a_filing_retried_after_a_restart_gives_one_held_order_and_one_digest(
    tmp_path: Path,
) -> None:
    store = played(tmp_path)
    file(store, "isle")
    commit(store, OLAF, kites_to_isle())
    twin = MemoryStore()
    twin.append_all(list(store.read(CAMPAIGN)))
    file(twin, "isle")
    commit(twin, OLAF, kites_to_isle())
    assert len(logged(twin, ev.OrderHeld)) == 2
    assert state_hash(load_state(twin, CAMPAIGN)) == state_hash(load_state(store, CAMPAIGN))


def test_each_seat_sees_its_own_held_orders_only(tmp_path: Path) -> None:
    from revisionist.core.project import project
    from revisionist.engine import catchup

    store = played(tmp_path)
    order = file(store, "isle")
    state = load_state(store, CAMPAIGN)
    assert set(project(state, seat(KARA)).held) == {order.order_id}
    assert not project(state, seat(ILSE)).held and not project(state, seat(OLAF)).held

    def kinds(person: EntityId) -> list[str]:
        return [f.event.kind for f in catchup.seat_events(store, CAMPAIGN, seat(person), 0, 9)]

    assert "order_held" in kinds(KARA)
    assert "order_held" not in kinds(ILSE) and "order_held" not in kinds(OLAF)


def test_the_held_order_event_folds_only_with_the_rule_and_once(tmp_path: Path) -> None:
    from revisionist.core.fold import FoldError

    store = played(tmp_path)
    order = file(store, "isle")
    state = load_state(store, CAMPAIGN)
    held = state.held[order.order_id]
    with pytest.raises(FoldError, match="duplicate order"):
        realism_tick._append(store, state, ev.OrderHeld(held=held), seat(KARA))
    off = state.model_copy(update={"rules": state.rules - {Rule.LOCKS}, "held": {}})
    with pytest.raises(FoldError, match="needs the locks rule"):
        realism_tick._append(store, off, ev.OrderHeld(held=held), seat(KARA))


def test_the_written_reader_files_a_held_order_and_tells_the_seat_why(tmp_path: Path) -> None:
    from revisionist.engine import orders_reader
    from revisionist.engine.web.realism_api import OrderProposal

    store = played(tmp_path)
    shown = OrderProposal(
        person="Ilse Varg", channel="letter", text="Fire.", parts=["fire"], reason=None
    )
    reply = orders_reader.file_order(
        store, CAMPAIGN, seat(KARA), orders_reader.Reading(shown=shown, asks=(gulf_fire(),))
    )
    assert (reply["reply"], reply["refused"]) == (HELD_FOR_ILSE, False)
    assert len(load_state(store, CAMPAIGN).held) == 1


# --- Code seats and aides never file a held order ------------------------------------


def test_a_code_seats_answer_that_would_be_held_is_dropped_with_the_refusal(
    tmp_path: Path,
) -> None:
    from revisionist.core.realism import actors, answering
    from revisionist.core.realism.answer import Answer, AnswerAct, AnswerWhen
    from revisionist.core.realism.route import NOBODY

    def answer(act: AnswerAct) -> Answer:
        when = AnswerWhen(every_days=7, start=DAY)
        return Answer(key="k", aim=1, when=when, act=act, delay_days=0, cooldown_days=7)

    events, _ = created(world(tmp_path, isle_move))
    (unplayed,) = actors.unseated(replay(events), [KARA])
    last = events[-1]
    state = replay(
        [
            *events,
            last.model_copy(
                update={
                    "seq": last.seq + 1,
                    "event_id": derived_id(CAMPAIGN, "event", "kara-ai"),
                    "payload": unplayed,
                }
            ),
        ]
    )
    march_isle = AnswerAct(lever="march", params={"force": "norra_levy", "to": "isle"})
    move_isle = AnswerAct(effect=MoveForce(force=LEVY, to=ISLE))
    for act in (march_isle, move_isle):
        (made,) = answering._make(state, KARA, answer(act), DAY)
        assert isinstance(made, ev.AnswerMade) and made.refusal == NOBODY[:60]
    hills = AnswerAct(lever="march", params={"force": "norra_levy", "to": "norra_hills"})
    drafted, made = answering._make(state, KARA, answer(hills), DAY)
    assert isinstance(drafted, ev.OrderDrafted) and isinstance(made, ev.AnswerMade)
    assert made.order == drafted.order.order_id


def test_the_aide_passes_over_a_holdable_option_at_the_head_of_its_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revisionist.core.realism.agenda import Option
    from revisionist.engine import options

    state = load_state(played(tmp_path, isle_move), CAMPAIGN)
    to_isle = Option(label="To the Isle", asks=(written(MoveForce(force=LEVY, to=ISLE)),))
    hills = Option(
        label="To the hills", asks=(written(MoveForce(force=LEVY, to=key_id("norra_hills"))),)
    )

    def offered(*listed: Option) -> list[options.AideOrder]:
        monkeypatch.setattr(options, "_live", lambda view: [object()])
        monkeypatch.setattr(options, "_wants_a_deal", lambda mandate: False)
        monkeypatch.setattr(
            options,
            "_options_for",
            lambda state, view, *rest: tuple(options._clean(state, view.viewer, view, listed)),
        )
        return options.aide_asks(state, seat(KARA), None)

    assert [tuple(o) for o in offered(to_isle, hills)] == [hills.asks]
    assert offered(to_isle) == []
