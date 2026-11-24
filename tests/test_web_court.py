"""The court of ``view.realism``: the paths the seat's own forms use, each person on
them with the seat's own orders waiting there, the circle and chain on no path, the
chambers of the seat's own country, and the load limit."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, OrderId, PipelineId, SeatId, derived_id
from revisionist.core.ontology import EntityStatus
from revisionist.core.realism.pipeline import Order, OrderStatus, StepAction, StepOutcome
from revisionist.core.realism.pipelines import FREE_ORDERS
from revisionist.core.realism.resolvers import qid
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.emit import Emitter
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import realism_api as api
from revisionist.engine.web.court import seat_court

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
OTHER = SeatId("01ARZ3NDEKTSV4RRFFQ69G5FB0")
"""A seat that is not the viewer's: its orders must not reach the court."""
FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
NAVAL = {"order": "escort_convoys", "zone": "western_atlantic"}
ROOSEVELT_PATHS = [
    "A bill through Congress",
    "A naval order",
    "A cable to the Prime Minister",
    "A Lend-Lease allocation",
    "A public address",
]


class Game:
    """One person seated in autumn 1941, before any wake."""

    def __init__(self, person: str = "roosevelt") -> None:
        self.store = MemoryStore()
        world = cmp.load_world(cmp.world_path("autumn-1941"))
        self.store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
        self.keys = {k: EntityId(v) for k, v in resolve_keys(world, CAMPAIGN).items()}
        realism_tick.seat_player(self.store, CAMPAIGN, self.keys[person])
        (self.seat,) = self.state.seats

    @property
    def state(self) -> State:
        return load_state(self.store, CAMPAIGN)

    @property
    def today(self) -> date:
        today = self.state.in_world_date
        assert today is not None
        return today

    def emit(self, *payloads: ev.Payload) -> None:
        em = Emitter(self.store, self.state, cmp.versions())
        em.commit([em.event(p, scope=private_to(self.seat)) for p in payloads])

    def naval(self, zone: str = "western_atlantic") -> Order:
        return realism_tick.file_order(
            self.store, CAMPAIGN, self.seat, "naval_order", NAVAL | {"zone": zone}
        )

    def take(self, order: Order, action: StepAction, on: date) -> None:
        o = self.state.orders[order.order_id]
        person = self.state.pipelines[o.pipeline].steps[o.step].person
        outcome = StepOutcome(step=o.step, person=person, action=action, on=on)
        self.emit(ev.OrderStepTaken(order_id=o.order_id, outcome=outcome))

    def court(self, state: State | None = None) -> api.Court:
        return seat_court(state or self.state, self.seat)


@pytest.fixture
def game() -> Game:
    return Game()


def path(court: api.Court, name: str) -> api.CourtPath:
    (found,) = [p for p in court["paths"] if p["name"] == name]
    return found


def step_of(court: api.Court, path_name: str, person: str) -> api.CourtStep:
    (found,) = [s for s in path(court, path_name)["steps"] if s["name"] == person]
    return found


def waiting(court: api.Court) -> list[tuple[str, str]]:
    return [(s["name"], o["id"]) for p in court["paths"] for s in p["steps"] for o in s["orders"]]


def shift(state: State, days: int) -> State:
    assert state.in_world_date is not None
    return state.model_copy(update={"in_world_date": state.in_world_date + timedelta(days=days)})


def without_levers(state: State, person: EntityId) -> State:
    card = state.cards[person].model_copy(update={"levers": ()})
    return state.model_copy(update={"cards": {**state.cards, person: card}})


# --- paths ---


def test_roosevelt_has_five_paths_in_his_cards_order(game: Game) -> None:
    court = game.court()
    assert set(court) == set(api.Court.__annotations__)
    assert [p["name"] for p in court["paths"]] == ROOSEVELT_PATHS
    assert all(set(p) == set(api.CourtPath.__annotations__) for p in court["paths"])
    naval = game.state.cards[game.keys["roosevelt"]].pipelines[1]
    assert path(court, "A naval order")["id"] == naval


def test_each_path_names_the_forms_that_travel_it(game: Game) -> None:
    court = game.court()
    assert path(court, "A naval order")["forms"] == [
        "Give a naval order",
        "Move a fleet",
        "Detach part of a fleet",
        "Fly a reconnaissance",
        "Send a fleet on patrol",
        "Fund the codebreakers",
    ]
    assert path(court, "A public address")["forms"] == ["Address the nation"]


def test_each_step_has_its_person_office_kind_and_days_in_order(game: Game) -> None:
    steps = path(game.court(), "A bill through Congress")["steps"]
    assert all(set(s) == set(api.CourtStep.__annotations__) for s in steps)
    assert [(s["name"], s["kind"], s["days"], s["you"]) for s in steps] == [
        ("Sam Rayburn", "decision", 8, False),
        ("House committee clerk", "clerical", 1, False),
        ("Alben W. Barkley", "decision", 20, False),
        ("Franklin D. Roosevelt", "decision", 10, True),
    ]
    assert steps[0]["person"] == game.keys["rayburn"]
    assert steps[0]["office"] == game.state.cards[game.keys["rayburn"]].office


def test_a_step_with_no_card_has_no_office(game: Game) -> None:
    state = game.state
    rayburn = game.keys["rayburn"]
    cards = {k: c for k, c in state.cards.items() if k != rayburn}
    court = game.court(state.model_copy(update={"cards": cards}))
    assert step_of(court, "A bill through Congress", "Sam Rayburn")["office"] is None


def test_a_step_whose_days_are_a_gap_sends_none(game: Game) -> None:
    state = game.state
    pid = PipelineId(state.cards[game.keys["roosevelt"]].pipelines[1])
    pl = state.pipelines[pid]
    first = pl.steps[0].model_copy(update={"days": None})
    gap = pl.model_copy(update={"steps": (first, *pl.steps[1:])})
    state = state.model_copy(update={"pipelines": {**state.pipelines, pid: gap}})
    assert step_of(game.court(state), "A naval order", "Harold R. Stark")["days"] is None


def test_tojo_has_two_paths_and_no_chamber() -> None:
    court = Game("tojo").court()
    assert [p["name"] for p in court["paths"]] == [
        "Liaison Conference to Imperial sanction",
        "A cabinet statement",
    ]
    assert court["chambers"] == []


def test_a_pipeline_on_the_card_that_no_form_uses_is_not_a_path() -> None:
    court = Game("churchill").court()
    assert [p["name"] for p in court["paths"]] == [
        "A Chiefs of Staff directive",
        "A broadcast to the nation",
        "A bill through the Commons",
    ]


def test_a_seat_with_no_forms_gets_empty_paths(game: Game) -> None:
    court = game.court(without_levers(game.state, game.keys["roosevelt"]))
    assert court["paths"] == []
    assert waiting(court) == []


def test_a_pipeline_an_own_order_runs_off_the_forms_is_added_last(game: Game) -> None:
    order = game.naval()
    state = game.state
    foreign = next(p for p in state.pipelines.values() if p.name == "A Chiefs of Staff directive")
    moved = state.orders[order.order_id].model_copy(update={"pipeline": foreign.pipeline_id})
    state = state.model_copy(update={"orders": {order.order_id: moved}})
    court = game.court(state)
    assert [p["name"] for p in court["paths"]] == [*ROOSEVELT_PATHS, "A Chiefs of Staff directive"]
    assert court["paths"][-1]["forms"] == []
    assert waiting(court) == [("Sir Dudley Pound", order.order_id)]


# --- orders waiting at a step ---


def test_a_filed_order_waits_with_the_first_person_on_its_path(game: Game) -> None:
    order = game.naval()
    court = game.court()
    (held,) = step_of(court, "A naval order", "Harold R. Stark")["orders"]
    assert set(held) == set(api.CourtOrder.__annotations__)
    assert held == {
        "id": order.order_id,
        "label": "Give a naval order",
        "since": game.today.isoformat(),
        "held_days": 0,
    }
    assert waiting(court) == [("Harold R. Stark", order.order_id)]


def test_held_days_count_from_the_world_date(game: Game) -> None:
    game.naval()
    court = game.court(shift(game.state, 5))
    (held,) = step_of(court, "A naval order", "Harold R. Stark")["orders"]
    assert (held["held_days"], held["since"]) == (5, game.today.isoformat())


def test_an_order_dated_after_the_world_date_shows_no_negative_days(game: Game) -> None:
    order = game.naval()
    state = game.state
    late = state.orders[order.order_id].model_copy(update={"filed": game.today + timedelta(days=2)})
    state = state.model_copy(update={"orders": {order.order_id: late}})
    (held,) = step_of(game.court(state), "A naval order", "Harold R. Stark")["orders"]
    assert held["held_days"] == 0


def test_a_passed_step_moves_the_order_to_the_next_person_from_that_day(game: Game) -> None:
    order = game.naval()
    on = game.today + timedelta(days=1)
    game.take(order, StepAction.PASS, on)
    court = game.court(shift(game.state, 3))
    assert waiting(court) == [("Ernest J. King", order.order_id)]
    (held,) = step_of(court, "A naval order", "Ernest J. King")["orders"]
    assert (held["since"], held["held_days"]) == (on.isoformat(), 2)


def test_a_stall_is_not_seen(game: Game) -> None:
    order = game.naval()
    before = game.court(shift(game.state, 4))
    game.take(order, StepAction.STALL, game.today + timedelta(days=2))
    assert game.court(shift(game.state, 4)) == before


def test_a_stall_at_a_later_step_keeps_the_day_it_arrived(game: Game) -> None:
    order = game.naval()
    on = game.today + timedelta(days=1)
    game.take(order, StepAction.PASS, on)
    game.take(order, StepAction.STALL, on + timedelta(days=2))
    court = game.court(shift(game.state, 5))
    (held,) = step_of(court, "A naval order", "Ernest J. King")["orders"]
    assert held["since"] == on.isoformat()


def test_a_settled_order_waits_nowhere(game: Game) -> None:
    order = game.naval()
    game.emit(ev.OrderSettled(order_id=order.order_id, status=OrderStatus.WITHDRAWN))
    assert waiting(game.court()) == []


def test_an_order_past_its_last_step_waits_nowhere(game: Game) -> None:
    order = game.naval()
    game.take(order, StepAction.PASS, game.today)
    game.take(order, StepAction.PASS, game.today)
    assert waiting(game.court()) == []


def test_orders_at_one_step_run_oldest_first(game: Game) -> None:
    first = game.naval()
    second = game.naval("iceland_route")
    state = game.state
    early = state.orders[second.order_id].model_copy(
        update={"filed": game.today - timedelta(days=2)}
    )
    state = state.model_copy(update={"orders": {**state.orders, second.order_id: early}})
    held = step_of(game.court(state), "A naval order", "Harold R. Stark")["orders"]
    assert [o["id"] for o in held] == [second.order_id, first.order_id]
    earlier = state.orders[first.order_id].model_copy(
        update={"filed": game.today - timedelta(days=3)}
    )
    state = state.model_copy(update={"orders": {**state.orders, first.order_id: earlier}})
    held = step_of(game.court(state), "A naval order", "Harold R. Stark")["orders"]
    assert [o["id"] for o in held] == [first.order_id, second.order_id]


def test_before_the_calendar_the_paths_show_and_nothing_waits(game: Game) -> None:
    game.naval()
    court = game.court(game.state.model_copy(update={"in_world_date": None}))
    assert [p["name"] for p in court["paths"]] == ROOSEVELT_PATHS
    assert waiting(court) == []


def test_a_second_seats_order_is_absent(game: Game) -> None:
    state = game.state
    pid = PipelineId(state.cards[game.keys["roosevelt"]].pipelines[1])
    theirs = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "court-order", 99)),
        issuer=OTHER,
        lever="naval_order",
        pipeline=pid,
        params=dict(NAVAL),
        filed=game.today,
    )
    state = state.model_copy(update={"orders": {theirs.order_id: theirs}})
    court = game.court(state)
    assert waiting(court) == []
    assert theirs.order_id not in json.dumps(court)


def test_the_load_limit_is_the_pipeline_rules(game: Game) -> None:
    assert game.court()["load_limit"] == FREE_ORDERS == 2


# --- the ring ---


def test_the_ring_is_the_circle_then_the_chain_on_no_path_with_a_channel(game: Game) -> None:
    ring = game.court()["ring"]
    assert all(set(r) == set(api.CourtRing.__annotations__) for r in ring)
    assert [(r["name"], r["channel"]) for r in ring] == [
        ("Cordell Hull", "in_person"),
        ("Henry L. Stimson", "in_person"),
        ("Frank Knox", "in_person"),
        ("George C. Marshall", "in_person"),
        ("Henry A. Wallace", "in_person"),
        ("Henry Morgenthau Jr.", "in_person"),
        ("White House executive clerk", "in_person"),
    ]
    assert ring[0]["person"] == game.keys["hull"]
    assert ring[0]["office"] == game.state.cards[game.keys["hull"]].office


def test_the_ring_gives_a_circle_member_their_own_channel() -> None:
    ring = Game("mussolini").court()["ring"]
    assert [(r["name"], r["channel"]) for r in ring] == [
        ("Adolf Hitler", "courier"),
        ("King Victor Emmanuel III", "in_person"),
    ]


def test_the_ring_leaves_out_the_dead(game: Game) -> None:
    state = game.state
    hull = game.keys["hull"]
    dead = state.entities[hull].model_copy(update={"status": EntityStatus.DEAD})
    state = state.model_copy(update={"entities": {**state.entities, hull: dead}})
    assert "Cordell Hull" not in [r["name"] for r in game.court(state)["ring"]]


def test_a_seat_with_no_forms_has_its_whole_circle_and_chain_in_the_ring(game: Game) -> None:
    ring = game.court(without_levers(game.state, game.keys["roosevelt"]))["ring"]
    assert len(ring) == 10 + 4


# --- chambers ---


def test_roosevelt_has_a_senate_and_a_house_with_seats_by_party(game: Game) -> None:
    chambers = game.court()["chambers"]
    assert all(set(c) == set(api.Chamber.__annotations__) for c in chambers)
    assert [(c["name"], c["seats"], c["carries"]) for c in chambers] == [
        (
            "House of Representatives",
            [
                {"party": "Democrats", "seats": 267},
                {"party": "Republicans", "seats": 162},
                {"party": "Other members", "seats": 5},
            ],
            218,
        ),
        (
            "Senate",
            [
                {"party": "Democrats", "seats": 66},
                {"party": "Republicans", "seats": 28},
                {"party": "Other members", "seats": 2},
            ],
            49,
        ),
    ]


def test_a_chamber_pairs_its_public_votes_as_yeas_and_nays(game: Game) -> None:
    (house, senate) = game.court()["chambers"]
    assert house["votes"] == [
        {"name": "House vote on draft extension", "yeas": 203, "nays": 202, "as_of": "1941-08-12"}
    ]
    assert senate["votes"] == []


def test_a_vote_once_counted_joins_newest_first(game: Game) -> None:
    on = game.today + timedelta(days=3)
    state = game.state
    quantities = dict(state.quantities)
    for key, value in (
        ("neutrality_revision_house_yeas", 212),
        ("neutrality_revision_house_nays", 194),
    ):
        q = quantities[qid(state, key)]
        quantities[q.quantity_id] = q.model_copy(update={"value": value, "as_of": on})
    state = state.model_copy(update={"quantities": quantities})
    (house, _) = game.court(state)["chambers"]
    assert [(v["name"], v["yeas"], v["nays"], v["as_of"]) for v in house["votes"]] == [
        ("House vote on Neutrality revision", 212, 194, on.isoformat()),
        ("House vote on draft extension", 203, 202, "1941-08-12"),
    ]


def test_a_vote_with_one_figure_missing_is_left_out(game: Game) -> None:
    state = game.state
    q = state.quantities[qid(state, "neutrality_revision_house_yeas")]
    quantities = {**state.quantities, q.quantity_id: q.model_copy(update={"value": 212})}
    (house, _) = game.court(state.model_copy(update={"quantities": quantities}))["chambers"]
    assert [v["name"] for v in house["votes"]] == ["House vote on draft extension"]


def test_a_seat_figure_the_view_does_not_hold_makes_no_chamber(game: Game) -> None:
    state = game.state
    senate = game.keys["senate"]
    quantities = {
        k: q.model_copy(update={"scope": None}) if q.owner == senate else q
        for k, q in state.quantities.items()
    }
    chambers = game.court(state.model_copy(update={"quantities": quantities}))["chambers"]
    assert [c["name"] for c in chambers] == ["House of Representatives"]


def test_another_countrys_chambers_are_not_the_seats() -> None:
    assert Game("churchill").court()["chambers"] == []


# --- the client fixture ---


def test_the_client_fixture_carries_the_court_in_the_servers_shape() -> None:
    fixture = json.loads(FIXTURE.read_text())
    court = fixture["court"]
    assert set(court) == set(api.Court.__annotations__)
    assert court["paths"] and court["ring"] and court["chambers"]
    assert all(set(p) == set(api.CourtPath.__annotations__) for p in court["paths"])
    steps = [s for p in court["paths"] for s in p["steps"]]
    assert all(set(s) == set(api.CourtStep.__annotations__) for s in steps)
    held = [o for s in steps for o in s["orders"]]
    assert held and all(set(o) == set(api.CourtOrder.__annotations__) for o in held)
    assert all(set(r) == set(api.CourtRing.__annotations__) for r in court["ring"])
    assert all(set(c) == set(api.Chamber.__annotations__) for c in court["chambers"])
    assert {o["id"] for o in held} <= {o["id"] for o in fixture["orders"]["orders"]}
