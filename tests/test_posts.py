"""Player, person and post kept apart (PPP).

The toy world (``tests/worlds/territory-toy.yaml``) with ``posts`` on: Ilse Varg holds the
chancellery of Norra (the office asset her card names as its ``post``). Here Norra also
has its general, Kara Lind, who holds the command of the levy, and Olav Holm, a colonel
with no post whose card carries only his own. Ilse's ``send_levy`` waits at the general's
step in the war council; her own domain over the levy is carried out by the general.
Tomas Brand holds Sudland. With ``posts`` off, a card and its office are one thing.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, apply, state_hash
from revisionist.core.goals import AimStatus, Goal, GoalKind, GoalSource, HoldsOffice, aim_status
from revisionist.core.ids import AssetId, EntityId, GoalId, SeatId, derived_id
from revisionist.core.ontology import EntityStatus
from revisionist.core.project import project
from revisionist.core.realism import posts
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.resolution import TickStage
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, Scope, Visibility
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick, session_zero
from revisionist.engine.store import MemoryStore, load_state
from tests.fixtures import envelope
from tests.test_adjacency_moves import toy
from tests.test_realism_command import card, general, orders
from tests.test_territory_model import CAMPAIGN, created, refused

World = dict[str, Any]
DAY = date(1900, 4, 2)


def key_id(key: str) -> EntityId:
    return EntityId(object_id(CAMPAIGN, "entity", key))


def asset_id(key: str) -> AssetId:
    return AssetId(object_id(CAMPAIGN, "asset", key))


ILSE, KARA, OLAV, TOMAS = key_id("ilse"), key_id("kara"), key_id("olav"), key_id("tomas")
NORRA = key_id("norra")
CHANCELLERY, COMMAND = asset_id("norra_chancellery"), asset_id("levy_command")


def seat(person: EntityId) -> SeatId:
    return SeatId(derived_id(CAMPAIGN, "seat", person))


def on(w: World) -> None:
    w["rules"] = [*w["rules"], "posts"]


def command_post(w: World) -> None:
    """The general's command as an office of its own, and Olav, a colonel with no post."""
    w["assets"].append(
        {
            "key": "levy_command",
            "kind": "office",
            "name": "General of the Norra Levy",
            "tier": 3,
            "controller": "kara",
        }
    )
    kara = card(w, "kara")
    kara["post"] = "levy_command"
    kara["successor"] = "olav"
    kara["feeds"] = []
    w["entities"].append({"key": "olav", "kind": "person", "name": "Olav Holm", "parent": "norra"})
    w["cards"].append(
        {
            "person": "olav",
            "office": "Colonel of the Norra Levy",
            "principals": ["kara"],
            "horizon_days": 14,
            "inner_circle": [{"person": "tomas", "channel": "letter"}],
        }
    )
    ilse = card(w, "ilse")
    ilse["successor"] = "kara"
    ilse["inner_circle"] = [{"person": "kara", "channel": "telephone"}]
    ilse["powers"] = ["summon the assembly"]
    ilse["authority"] = [
        {
            "name": "the_levy_by_order",
            "effects": ["move_force"],
            "executor": "kara",
            "forces": ["norra_levy"],
        }
    ]


def world(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    return toy(tmp, general, orders, command_post, on, *changes)


class Game:
    """The toy game in an event store, Ilse, Kara and Tomas played; Olav has no seat."""

    def __init__(self, w: WorldFile) -> None:
        self.store = MemoryStore()
        self.store.append_all(compile_world(w, CAMPAIGN, cmp.versions()))
        for person in (ILSE, KARA, TOMAS):
            name = self.state.entities[person].name
            session_zero.claim(self.store, CAMPAIGN, seat(person), name)
        realism_tick.open_play(self.store, CAMPAIGN)

    @property
    def state(self) -> State:
        return load_state(self.store, CAMPAIGN)

    def move(self, post: AssetId, to: EntityId | None) -> None:
        realism_tick.change_post(self.store, CAMPAIGN, post, to, posts.PostCause.APPOINTED)

    def tick(self, stop_after: TickStage | None = None) -> None:
        realism_tick.run_realism_tick(self.store, CAMPAIGN, stop_after=stop_after)

    def changes(self) -> list[ev.PostChanged]:
        return [
            e.payload for e in self.store.read(CAMPAIGN) if isinstance(e.payload, ev.PostChanged)
        ]


def game(tmp: Path, *changes: Callable[[World], None]) -> Game:
    return Game(world(tmp, *changes))


def forms(state: State, person: EntityId) -> set[str]:
    view = project(state, seat(person))
    assert view.desk is not None
    return {lever.name for lever in view.desk.levers}


# --- the post on a card ------------------------------------------------------------


def test_a_card_names_its_post_only_with_posts_on(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _, with_on = created(world(tmp_path / "a"))
    _, with_off = created(toy(tmp_path / "b", general, orders, command_post))
    assert with_on.cards[ILSE].post == CHANCELLERY
    assert with_on.cards[KARA].post == COMMAND
    assert with_on.cards[OLAV].post is None
    assert with_off.cards[ILSE].post is None
    assert "post" not in with_off.cards[ILSE].model_dump(mode="json")


def test_the_toy_world_names_the_chancellery_as_ilses_post(tmp_path: Path) -> None:
    _, state = created(toy(tmp_path, on))
    assert state.cards[ILSE].post == CHANCELLERY
    assert posts.holder(state, CHANCELLERY) == ILSE


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda w: card(w, "olav").update(post="nowhere"), "unknown asset nowhere"),
        (lambda w: card(w, "olav").update(post="levy_command"), "does not hold levy_command"),
        (lambda w: card(w, "ilse").update(post="norra_shipping_office"), "is not an office"),
    ],
)
def test_the_compiler_refuses_a_post_that_is_not_the_persons_office(
    tmp_path: Path, change: Callable[[World], None], problem: str
) -> None:
    def extra(w: World) -> None:
        w["assets"].append(
            {
                "key": "norra_shipping_office",
                "kind": "force",
                "name": "Yard",
                "controller": "ilse",
                "location": "norrhavn",
            }
        )
        change(w)

    found = refused(world(tmp_path, extra))
    assert any(problem in p for p in found), found


# --- rule 1 and 2: the post moves, the person's own stays ----------------------------


def test_a_moved_post_takes_its_forms_and_leaves_the_persons_own(tmp_path: Path) -> None:
    g = game(tmp_path)
    before = g.state
    g.move(CHANCELLERY, OLAV)
    after = g.state
    ilse, olav = after.cards[ILSE], after.cards[OLAV]
    assert forms(before, ILSE) == {"move_levy", "send_levy"}
    assert forms(after, ILSE) == set()
    assert {lv.name for lv in olav.levers} == {"move_levy", "send_levy"}
    assert after.assets[CHANCELLERY].controller == OLAV
    assert (ilse.post, olav.post) == (None, CHANCELLERY)
    assert ilse.authority == () and ilse.pipelines == () and ilse.powers == ()
    assert ilse.principals == () and ilse.successor is None
    assert ilse.office == "Without office"
    assert olav.powers == ("summon the assembly",)
    assert olav.office == "Chancellor of Norra"
    assert olav.successor == KARA
    assert olav.principals == (KARA, NORRA)
    # what is the person's own stays with the person
    assert ilse.inner_circle == before.cards[ILSE].inner_circle
    assert olav.inner_circle == before.cards[OLAV].inner_circle
    assert ilse.voice == before.cards[ILSE].voice
    assert ilse.horizon_days == before.cards[ILSE].horizon_days


def test_a_holder_given_another_post_leaves_his_own_first(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.move(CHANCELLERY, KARA)
    state = g.state
    assert [(c.post, c.holder, c.to, c.cause) for c in g.changes()] == [
        (COMMAND, KARA, None, posts.PostCause.VACATED),
        (CHANCELLERY, ILSE, KARA, posts.PostCause.APPOINTED),
    ]
    assert forms(state, KARA) == {"move_levy", "send_levy"}
    assert posts.holder(state, COMMAND) is None


def test_a_post_moved_back_restores_both_cards(tmp_path: Path) -> None:
    g = game(tmp_path)
    before = g.state
    g.move(CHANCELLERY, OLAV)
    g.move(CHANCELLERY, ILSE)
    after = g.state
    for person in (ILSE, OLAV):
        assert after.cards[person].desk() == before.cards[person].desk()
    assert after.assets[CHANCELLERY].controller == ILSE


def test_a_post_left_to_nobody_is_held_by_the_nation(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.move(CHANCELLERY, None)
    state = g.state
    assert posts.holder(state, CHANCELLERY) is None
    assert state.assets[CHANCELLERY].controller == NORRA
    assert forms(state, ILSE) == set()


def test_a_card_with_no_post_is_unchanged_by_a_change_elsewhere(tmp_path: Path) -> None:
    g = game(tmp_path)
    tomas = g.state.cards[TOMAS]
    g.move(CHANCELLERY, OLAV)
    assert g.state.cards[TOMAS] == tomas


def test_the_change_is_one_public_event_without_the_posts_part(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.move(CHANCELLERY, OLAV)
    (found,) = g.changes()
    assert (found.post, found.holder, found.to) == (CHANCELLERY, ILSE, OLAV)
    (event,) = [e for e in g.store.read(CAMPAIGN) if e.kind == "post_changed"]
    assert event.scope == PUBLIC
    assert "send_levy" not in event.model_dump_json()


# --- what the fold refuses ------------------------------------------------------------


def _change(state: State, **kw: Any) -> ev.PostChanged:
    base: dict[str, Any] = dict(
        post=CHANCELLERY, holder=ILSE, to=KARA, on=DAY, cause=posts.PostCause.APPOINTED
    )
    return ev.PostChanged(**{**base, **kw})


def _fold(state: State, p: ev.Payload) -> State:
    event = envelope(state.last_seq + 1, p).model_copy(update={"campaign_id": CAMPAIGN})
    return apply(state, event)


def test_a_change_names_two_people() -> None:
    with pytest.raises(ValueError, match="changes hands"):
        ev.PostChanged(
            post=CHANCELLERY, holder=ILSE, to=ILSE, on=DAY, cause=posts.PostCause.APPOINTED
        )


def test_the_fold_refuses_a_change_with_posts_off(tmp_path: Path) -> None:
    _, state = created(toy(tmp_path, general, orders, command_post))
    with pytest.raises(FoldError, match="posts rule"):
        _fold(state, _change(state))


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"holder": TOMAS}, "held by"),
        ({"post": asset_id("nowhere")}, "asset"),
        ({"to": NORRA}, "card"),
    ],
)
def test_the_fold_refuses_a_change_that_does_not_fit(
    tmp_path: Path, kw: dict[str, Any], match: str
) -> None:
    _, state = created(world(tmp_path))
    with pytest.raises(FoldError, match=match):
        _fold(state, _change(state, **kw))


def test_the_fold_refuses_a_post_given_to_someone_holding_another(tmp_path: Path) -> None:
    _, state = created(world(tmp_path))
    with pytest.raises(FoldError, match="holds another post"):
        _fold(state, _change(state, post=COMMAND, holder=KARA, to=ILSE))


def test_the_fold_refuses_a_post_given_to_the_dead(tmp_path: Path) -> None:
    _, state = created(world(tmp_path))
    dead = state.entities[OLAV].model_copy(update={"status": EntityStatus.DEAD})
    state = state.model_copy(update={"entities": {**state.entities, OLAV: dead}})
    with pytest.raises(FoldError, match="is dead"):
        _fold(state, _change(state, to=OLAV))


def test_a_face_names_a_post_only_where_the_seat_sees_the_office(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = g.state
    secret = Scope(visibility=Visibility.PRIVATE, known_by=frozenset({seat(KARA)}))
    hidden = state.assets[COMMAND].model_copy(update={"scope": secret})
    state = state.model_copy(update={"assets": {**state.assets, COMMAND: hidden}})
    assert project(state, seat(KARA)).cards[KARA].post == COMMAND
    assert project(state, seat(TOMAS)).cards[KARA].post is None
    assert project(state, seat(TOMAS)).cards[ILSE].post == CHANCELLERY


def test_change_vacates_the_new_holders_own_post_first(tmp_path: Path) -> None:
    _, state = created(world(tmp_path))
    out = posts.change(state, CHANCELLERY, KARA, DAY, posts.PostCause.APPOINTED)
    assert [(p.post, p.holder, p.to) for p in out] == [
        (COMMAND, KARA, None),
        (CHANCELLERY, ILSE, KARA),
    ]
    after = state
    for p in out:
        after = _fold(after, p)
    assert posts.holder(after, COMMAND) is None
    assert posts.holder(after, CHANCELLERY) == KARA


# --- rule 3: steps and executors name the new holder; an order goes on ----------------


def test_an_order_waiting_at_the_old_holders_step_goes_on_with_the_new(tmp_path: Path) -> None:
    g = game(tmp_path)
    order = realism_tick.file_order(
        g.store, CAMPAIGN, seat(ILSE), "send_levy", {"force": "norra_levy", "to": "norra_hills"}
    )
    assert g.state.orders[order.order_id].status is OrderStatus.MOVING
    g.move(COMMAND, OLAV)
    state = g.state
    pipeline = state.pipelines[order.pipeline]
    assert [s.person for s in pipeline.steps] == [OLAV]
    assert order.order_id in state.orders
    for _ in range(6):
        if g.state.orders[order.order_id].status is not OrderStatus.MOVING:
            break
        g.tick()
    done = g.state.orders[order.order_id]
    assert done.status is not OrderStatus.MOVING
    assert done.outcomes and {o.person for o in done.outcomes} == {OLAV}


def test_an_executor_that_named_the_old_holder_names_the_new(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.move(COMMAND, OLAV)
    (domain,) = g.state.cards[ILSE].authority
    assert domain.executor == OLAV


def test_a_domain_whose_executor_takes_the_post_is_carried_out_by_himself(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.move(CHANCELLERY, None)
    g.move(COMMAND, None)
    g.move(CHANCELLERY, KARA)
    domain = next(d for d in g.state.cards[KARA].authority if d.name == "the_levy_by_order")
    assert domain.executor is None


# --- rule 4: the seat plays its person; the successor takes a vacated post -------------


def test_a_seat_still_plays_its_person_after_the_post_goes(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.move(CHANCELLERY, KARA)
    state = g.state
    assert state.seats[seat(ILSE)].embodies == ILSE
    assert state.seats[seat(KARA)].embodies == KARA


def test_a_vacated_post_goes_to_its_designated_successor_at_the_wake(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.move(COMMAND, None)
    g.tick()
    assert posts.holder(g.state, COMMAND) == OLAV
    assert [(c.holder, c.to, c.cause) for c in g.changes()] == [
        (KARA, None, posts.PostCause.APPOINTED),
        (None, OLAV, posts.PostCause.SUCCEEDED),
    ]


def test_a_dead_holders_post_goes_to_his_successor(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = g.state
    dead = state.entities[KARA].model_copy(update={"status": EntityStatus.DEAD})
    state = state.model_copy(update={"entities": {**state.entities, KARA: dead}})
    found = posts.walk(state, DAY)
    assert [(p.post, p.holder, p.to) for p in found] == [(COMMAND, KARA, OLAV)]


def test_the_successor_is_not_offered_a_post_with_posts_off(tmp_path: Path) -> None:
    _, state = created(toy(tmp_path, general, orders, command_post))
    assert posts.walk(state, DAY) == []


# --- rule 5: an aim that reads the office is at risk, not failed -----------------------


def test_an_aim_on_the_office_is_at_risk_while_lost_and_met_once_restored(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    goal = Goal(
        goal_id=GoalId(derived_id(CAMPAIGN, "goal", "ilse-office")),
        seat_id=seat(ILSE),
        text="Hold the chancellery.",
        condition=HoldsOffice(holder=ILSE, office=CHANCELLERY),
        kind=GoalKind.UNDOABLE,
        clock_id=None,
        scope=Scope(visibility=Visibility.PRIVATE, known_by=frozenset({seat(ILSE)})),
        person=ILSE,
        source=GoalSource.POST,
        aim=1,
    )
    assert aim_status(g.state, goal) is AimStatus.MET
    g.move(CHANCELLERY, KARA)
    assert aim_status(g.state, goal) is AimStatus.AT_RISK
    g.move(CHANCELLERY, None)
    assert aim_status(g.state, goal) is AimStatus.AT_RISK
    g.move(CHANCELLERY, ILSE)
    assert aim_status(g.state, goal) is AimStatus.MET


# --- rule 6: a person with no post acts through someone, or is offered a replacement ----


def test_a_person_with_no_post_acts_through_an_inner_circle_with_authority(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    assert posts.can_act(g.state, ILSE)
    g.move(CHANCELLERY, OLAV)
    state = g.state
    # Ilse's inner circle is Kara, whose card holds the levy's authority.
    assert posts.can_act(state, ILSE)
    assert not posts.needs_replacement(state, ILSE)
    g.move(COMMAND, None)
    state = g.state
    assert not posts.can_act(state, ILSE)
    assert posts.needs_replacement(state, ILSE)


def test_a_dead_person_needs_a_replacement(tmp_path: Path) -> None:
    g = game(tmp_path)
    state = g.state
    dead = state.entities[ILSE].model_copy(update={"status": EntityStatus.DEAD})
    state = state.model_copy(update={"entities": {**state.entities, ILSE: dead}})
    assert posts.needs_replacement(state, ILSE)


# --- fog: a seat that cannot see the change gets the same data -------------------------


def hidden_feed(w: World) -> None:
    """A post whose private part carries one more form: nothing another seat can see."""
    ilse = card(w, "ilse")
    ilse["levers"] = [*ilse["levers"], {**ilse["levers"][0], "name": "secret_levy"}]


def test_a_seat_that_cannot_see_the_posts_part_gets_the_same_data(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    (tmp_path / "hidden").mkdir()
    plain, hidden = game(tmp_path / "plain"), game(tmp_path / "hidden", hidden_feed)
    for g in (plain, hidden):
        g.move(CHANCELLERY, OLAV)
        g.tick()
    for watcher in (TOMAS,):
        a = project(plain.state, seat(watcher)).model_dump(mode="json")
        b = project(hidden.state, seat(watcher)).model_dump(mode="json")
        assert a == b
        fa = catchup.seat_events(plain.store, CAMPAIGN, seat(watcher), 0, 9)
        fb = catchup.seat_events(hidden.store, CAMPAIGN, seat(watcher), 0, 9)
        assert [e.event.payload for e in fa] == [e.event.payload for e in fb]
    assert "secret_levy" in {lv.name for lv in hidden.state.cards[OLAV].levers}


def test_every_seat_is_fed_the_change(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.move(CHANCELLERY, OLAV)
    for who in (ILSE, KARA, TOMAS):
        fed = catchup.seat_events(g.store, CAMPAIGN, seat(who), 0, 9)
        assert [e.event.kind for e in fed].count("post_changed") == 1
    assert "post_changed" in catchup.FEED_KINDS


# --- a restart in the middle: one change, one digest -----------------------------------


def test_a_restart_mid_wake_gives_one_change_and_one_digest(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.move(COMMAND, None)
    twin = MemoryStore()
    twin.append_all(list(g.store.read(CAMPAIGN)))
    g.tick()
    realism_tick.run_realism_tick(twin, CAMPAIGN, stop_after=TickStage.ADVANCE)
    realism_tick.run_realism_tick(twin, CAMPAIGN)
    assert state_hash(load_state(twin, CAMPAIGN)) == state_hash(g.state)
    succeeded = [
        e
        for e in twin.read(CAMPAIGN)
        if isinstance(e.payload, ev.PostChanged) and e.payload.to == OLAV
    ]
    assert len(succeeded) == 1
