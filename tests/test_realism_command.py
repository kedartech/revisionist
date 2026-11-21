"""The commander's seat (CMD): switches, a card's path, his own force, and who prevails.

The toy world (``tests/worlds/territory-toy.yaml``) carries Norra's general, Kara Lind: a
military card under the chancellor, Ilse Varg, commanding the Norra Levy, which the
chancellor can order too. Every rule here is read with the ``command`` rule on; with it
off, the same script runs as it did before.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.fold import state_hash
from revisionist.core.ids import EntityId, FeatureId, OrderId, SeatId, derived_id
from revisionist.core.realism.card import CardPath, SeatCard, superiors
from revisionist.core.realism.pipeline import Order, OrderStatus, StepAction
from revisionist.core.realism.pipelines import (
    MAY_UNDER,
    REPLACED,
    held_due,
    held_paper_id,
    reply_doc_id,
)
from revisionist.core.resolution import TickStage
from revisionist.core.state import Rule, State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.store import MemoryStore, load_state
from tests.test_adjacency_moves import toy
from tests.test_territory_model import CAMPAIGN, TOY, created, refused, variant

World = dict[str, Any]


def key_id(key: str) -> str:
    return object_id(CAMPAIGN, "entity", key)


ILSE, KARA = EntityId(key_id("ilse")), EntityId(key_id("kara"))
NORRA = EntityId(key_id("norra"))
LEVY = FeatureId(object_id(CAMPAIGN, "feature", "norra_levy"))
ALL_ACTIONS = ["pass", "expedite", "stall", "amend", "refuse", "leak"]
TO = {"name": "to", "kind": "enum", "choices": ["norra_hills", "sudland_coast", "isle"]}
FORCE = {"name": "force", "kind": "enum", "choices": ["norra_levy"]}


def seat(person: EntityId) -> SeatId:
    return SeatId(derived_id(CAMPAIGN, "seat", person))


def command(w: World) -> None:
    w["rules"] = sorted({*w["rules"], "command"})


def card(w: World, person: str) -> World:
    found: World = next(c for c in w["cards"] if c["person"] == person)
    return found


def orders(w: World) -> None:
    """Forms that move the levy. The chancellor's ``move_levy`` passes a clerk; her
    ``send_levy`` waits on the general's decision, every action allowed. The general's
    ``march`` passes a clerk."""
    w["pipelines"] = [
        {
            "key": "clerks",
            "name": "The clerks",
            "source": "toy",
            "steps": [{"person": "kara", "kind": "clerical", "days": 1}],
        },
        {
            "key": "council",
            "name": "The war council",
            "source": "toy",
            "steps": [{"person": "kara", "kind": "decision", "days": 1, "allowed": ALL_ACTIONS}],
        },
    ]

    def lever(name: str, pipeline: str, label: str = "") -> World:
        out: World = {
            "name": name,
            "pipeline": pipeline,
            "resolver": "movement",
            "params": [FORCE, TO],
        }
        if label:
            out["label"] = label
        return out

    ilse, kara = card(w, "ilse"), card(w, "kara")
    ilse["pipelines"] = ["clerks", "council"]
    ilse["levers"] = [
        lever("move_levy", "clerks"),
        lever("send_levy", "council", "Declare the levy's march"),
    ]
    kara["pipelines"] = ["clerks"]
    kara["levers"] = [lever("march", "clerks")]


def disloyal(w: World) -> None:
    """A general whose card would hold anything: the lowest loyalty."""
    card(w, "kara")["loyalty"] = -5


class Game:
    """The toy game in an event store with the chancellor and the general played."""

    def __init__(self, w: WorldFile) -> None:
        self.store = MemoryStore()
        self.store.append_all(compile_world(w, CAMPAIGN, cmp.versions()))
        state = self.state
        for person in (ILSE, KARA):
            session_zero.claim(self.store, CAMPAIGN, seat(person), state.entities[person].name)
        realism_tick.open_play(self.store, CAMPAIGN)

    @property
    def state(self) -> State:
        return load_state(self.store, CAMPAIGN)

    def file(self, person: EntityId, lever: str, to: str) -> OrderId:
        order = realism_tick.file_order(
            self.store, CAMPAIGN, seat(person), lever, {"force": "norra_levy", "to": to}
        )
        return order.order_id

    def step(self, person: EntityId, order: OrderId, action: StepAction) -> Order:
        return realism_tick.take_step(self.store, CAMPAIGN, seat(person), order, action, {})

    def tick(self, stop_after: TickStage | None = None) -> None:
        realism_tick.run_realism_tick(self.store, CAMPAIGN, stop_after=stop_after)

    def order(self, order_id: OrderId) -> Order:
        return self.state.orders[order_id]

    def ticks_until_settled(self, order_id: OrderId, limit: int = 12) -> Order:
        for _ in range(limit):
            if self.order(order_id).status is not OrderStatus.MOVING:
                break
            self.tick()
        return self.order(order_id)


def game(tmp: Path, *changes: Callable[[World], None]) -> Game:
    return Game(toy(tmp, orders, *changes))


def replaced_papers(state: State) -> dict[SeatId, list[Any]]:
    """Each seat's papers that say an order of its was replaced."""
    out: dict[SeatId, list[Any]] = {}
    for doc in state.documents.values():
        if any(b.value == REPLACED for b in doc.view.body):
            for s in doc.view.scope.known_by:
                out.setdefault(s, []).append(doc.view)
    return out


# --- Rule 1: two rule names join the list ------------------------------------------------


def test_command_and_locks_are_rules_a_world_may_switch_on(tmp_path: Path) -> None:
    def both(w: World) -> None:
        w["rules"] = ["command", "locks"]

    _, state = created(variant(tmp_path, both))
    assert state.rules == frozenset({Rule.COMMAND, Rule.LOCKS})


def test_an_unknown_rule_name_is_still_refused(tmp_path: Path) -> None:
    def bad(w: World) -> None:
        w["rules"] = ["commanders"]

    with pytest.raises(ValueError):
        variant(tmp_path, bad)


# --- Rule 2: a card's path ---------------------------------------------------------------


def test_a_card_without_a_path_is_political_and_the_general_is_military() -> None:
    _, state = created(cmp.load_world(TOY))
    assert state.cards[ILSE].path is CardPath.POLITICAL
    assert state.cards[KARA].path is CardPath.MILITARY


def test_a_political_card_dumps_as_it_did_before() -> None:
    _, state = created(cmp.load_world(TOY))
    assert "path" not in state.cards[ILSE].model_dump(mode="json")
    assert state.cards[KARA].model_dump(mode="json")["path"] == "military"
    assert SeatCard.model_validate(state.cards[ILSE].model_dump(mode="json")) == state.cards[ILSE]


def test_the_general_answers_to_the_chancellor() -> None:
    _, state = created(cmp.load_world(TOY))
    assert superiors(state.cards, KARA) == (ILSE, NORRA)
    assert superiors(state.cards, ILSE) == (NORRA,)


# --- Rule 3: what the compiler refuses ---------------------------------------------------


def no_domain(w: World) -> None:
    card(w, "kara")["authority"] = []


def second_general(w: World) -> None:
    w["entities"].insert(
        3, {"key": "olav", "kind": "person", "name": "Olav Holm", "parent": "norra"}
    )
    w["cards"].append(
        {
            "person": "olav",
            "office": "Second General",
            "path": "military",
            "principals": ["ilse"],
            "horizon_days": 14,
            "authority": [{"name": "levy", "effects": ["move_force"], "forces": ["norra_levy"]}],
        }
    )


def test_a_playable_military_card_with_no_force_is_refused(tmp_path: Path) -> None:
    problems = refused(toy(tmp_path, command, no_domain))
    assert any(
        "card kara: a playable military card needs a domain naming a force" in p for p in problems
    )


def test_a_force_named_by_two_military_cards_is_refused(tmp_path: Path) -> None:
    problems = refused(toy(tmp_path, command, second_general))
    assert any("feature norra_levy: named by two military cards" in p for p in problems)


def test_with_command_off_the_compiler_does_not_read_the_path(tmp_path: Path) -> None:
    created(variant(tmp_path, no_domain))
    created(variant(tmp_path, second_general))


# --- Rule 4: a military card orders his own force through his own forms ----------------


def test_the_general_orders_his_own_force_through_his_own_form(tmp_path: Path) -> None:
    g = game(tmp_path, command)
    mine = g.file(KARA, "march", "norra_hills")
    assert g.ticks_until_settled(mine).status is OrderStatus.ENACTED
    assert g.state.features[LEVY].bound_for == EntityId(key_id("norra_hills"))


# --- Rule 5: the superior prevails -------------------------------------------------------


@pytest.mark.parametrize("general_first", [True, False])
def test_the_chancellors_order_stands_and_the_generals_is_replaced(
    tmp_path: Path, general_first: bool
) -> None:
    g = game(tmp_path, command)
    if general_first:
        his = g.file(KARA, "march", "sudland_coast")
        hers = g.file(ILSE, "move_levy", "norra_hills")
    else:
        hers = g.file(ILSE, "move_levy", "norra_hills")
        his = g.file(KARA, "march", "sudland_coast")
    g.tick()
    assert g.order(hers).status is OrderStatus.ENACTED
    assert g.order(his).status is OrderStatus.LAPSED
    assert g.state.features[LEVY].bound_for == EntityId(key_id("norra_hills"))


def test_the_reason_reaches_the_generals_seat_only(tmp_path: Path) -> None:
    g = game(tmp_path, command)
    his = g.file(KARA, "march", "sudland_coast")
    g.file(ILSE, "move_levy", "norra_hills")
    g.tick()
    papers = replaced_papers(g.state)
    assert set(papers) == {seat(KARA)}
    (paper,) = papers[seat(KARA)]
    assert paper.doc_id == reply_doc_id(CAMPAIGN, his, 0)
    assert any("Ilse Varg" in str(b.value) for b in paper.body)


def test_with_command_off_both_orders_are_carried_out(tmp_path: Path) -> None:
    g = game(tmp_path)
    his = g.file(KARA, "march", "sudland_coast")
    hers = g.file(ILSE, "move_levy", "norra_hills")
    g.tick()
    assert g.order(hers).status is OrderStatus.ENACTED
    assert g.order(his).status is OrderStatus.ENACTED
    assert replaced_papers(g.state) == {}


def test_an_order_the_superior_gave_in_an_earlier_wake_does_not_replace_a_later_one(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, command)
    hers = g.file(ILSE, "move_levy", "norra_hills")
    g.tick()
    assert g.order(hers).status is OrderStatus.ENACTED
    his = g.file(KARA, "march", "sudland_coast")
    assert g.ticks_until_settled(his).status is OrderStatus.ENACTED


# --- Rule 6: pass or stall on an order from above ---------------------------------------


def test_the_general_may_pass_or_stall_his_superiors_order_only(tmp_path: Path) -> None:
    g = game(tmp_path, command)
    hers = g.file(ILSE, "send_levy", "norra_hills")
    allowed = g.state.pipelines[g.order(hers).pipeline].steps[0].allowed
    assert {StepAction.REFUSE, StepAction.AMEND, StepAction.EXPEDITE} <= allowed
    for action in (StepAction.REFUSE, StepAction.EXPEDITE):
        with pytest.raises(ValueError, match="does not allow"):
            g.step(KARA, hers, action)
    g.step(KARA, hers, StepAction.STALL)
    assert g.order(hers).held_choice is not None
    g.step(KARA, hers, StepAction.PASS)


def test_with_command_off_the_general_may_refuse(tmp_path: Path) -> None:
    g = game(tmp_path)
    hers = g.file(ILSE, "send_levy", "norra_hills")
    g.step(KARA, hers, StepAction.REFUSE)
    chosen = g.order(hers).held_choice
    assert chosen is not None and chosen.action is StepAction.REFUSE


def test_the_held_paper_offers_pass_or_hold_only_with_command_on(tmp_path: Path) -> None:
    for on, changes in ((True, (command,)), (False, ())):
        (tmp_path / str(on)).mkdir()
        g = game(tmp_path / str(on), *changes)
        hers = g.file(ILSE, "send_levy", "norra_hills")
        g.tick(stop_after=TickStage.PIPELINES)
        doc = g.state.documents[held_paper_id(CAMPAIGN, hers, 0)]
        values = [b.value for b in doc.view.body]
        assert (MAY_UNDER in values) is on


# --- Rule 7: unanswered, the step passes ------------------------------------------------


def test_an_unanswered_step_on_a_superiors_order_passes_on_its_day(tmp_path: Path) -> None:
    g = game(tmp_path, command, disloyal)
    hers = g.file(ILSE, "send_levy", "norra_hills")
    due = held_due(g.state, g.order(hers))
    assert due is not None
    settled = g.ticks_until_settled(hers)
    assert settled.status is OrderStatus.ENACTED
    (outcome,) = settled.outcomes
    assert outcome.action is StepAction.PASS and outcome.on == due


def test_with_command_off_the_cards_policy_decides(tmp_path: Path) -> None:
    g = game(tmp_path, disloyal)
    hers = g.file(ILSE, "send_levy", "norra_hills")
    for _ in range(4):
        g.tick()
        if g.order(hers).outcomes:
            break
    first = g.order(hers).outcomes[0]
    assert first.action in {StepAction.STALL, StepAction.REFUSE}


def test_a_kept_stall_is_taken_in_place_of_the_pass(tmp_path: Path) -> None:
    g = game(tmp_path, command)
    hers = g.file(ILSE, "send_levy", "norra_hills")
    g.step(KARA, hers, StepAction.STALL)
    for _ in range(4):
        g.tick()
        if g.order(hers).outcomes:
            break
    assert g.order(hers).outcomes[0].action is StepAction.STALL


# --- Keeps: a restart mid-wake --------------------------------------------------------


def test_a_restart_mid_wake_gives_the_same_digest(tmp_path: Path) -> None:
    g = game(tmp_path, command)
    g.file(KARA, "march", "sudland_coast")
    g.file(ILSE, "move_levy", "norra_hills")
    g.file(ILSE, "send_levy", "isle")
    twin = MemoryStore()
    twin.append_all(list(g.store.read(CAMPAIGN)))
    g.tick()
    realism_tick.run_realism_tick(twin, CAMPAIGN, stop_after=TickStage.PIPELINES)
    realism_tick.run_realism_tick(twin, CAMPAIGN)
    assert state_hash(load_state(twin, CAMPAIGN)) == state_hash(g.state)
