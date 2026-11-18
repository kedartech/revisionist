"""Pieces move by adjacency, a step at a time (ADJ).

With ``territories`` switched on, a piece stands in one area and an order sends it along
the course of fewest days for its domain; it enters each area on the day that step
completes, and each step lands one ``piece_stepped`` event sealed to the seats of the
piece's own nation. The toy world (``tests/worlds/territory-toy.yaml``) is played with
the rule on; every other rule of the territory game stays off.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import (
    EntityId,
    EventId,
    FeatureId,
    OrderId,
    PipelineId,
    SeatId,
    derived_id,
)
from revisionist.core.realism import bases, territory
from revisionist.core.realism.bases import RADIUS_STEPS, Radius, Tier
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import movement
from revisionist.core.realism.territory import Plan, Refused, StepCause
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.realism.war_rules import order_refusal
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, Visibility
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick
from revisionist.engine.emit import Emitter
from revisionist.engine.store import MemoryStore
from tests.test_territory_model import CAMPAIGN, claim, created, refused, variant

START = date(1900, 4, 2)
World = dict[str, Any]


def entity(key: str) -> EntityId:
    """The id a toy-world key compiles to, for keys a variant adds as well."""
    feature = key.endswith(("_levy", "_galleys", "_kites", "_herald"))
    return EntityId(object_id(CAMPAIGN, "feature" if feature else "entity", key))


def seat(person: str) -> SeatId:
    return SeatId(derived_id(CAMPAIGN, "seat", person))


def with_rule(w: World) -> None:
    w["rules"] = ["territories"]


def toy(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    """The toy world with ``territories`` on and ``changes`` applied."""

    def change(w: World) -> None:
        with_rule(w)
        for c in changes:
            c(w)

    return variant(tmp, change)


def game(world: WorldFile) -> tuple[list[ev.Event], State]:
    events, _ = created(world)
    return events, claim(events, "ilse", "tomas")


def play(tmp: Path, *changes: Callable[[World], None]) -> State:
    return game(toy(tmp, *changes))[1]


def piece(state: State, key: str) -> Feature:
    return state.features[FeatureId(entity(key))]


def where(state: State, key: str) -> EntityId:
    return piece(state, key).places[0]


def _events(last_seq: int, payloads: Sequence[ev.Payload]) -> list[ev.Event]:
    return [
        ev.Event(
            event_id=EventId(derived_id(CAMPAIGN, "adj-test", last_seq + 1 + n)),
            campaign_id=CAMPAIGN,
            seq=last_seq + 1 + n,
            tick=0,
            scope=PUBLIC,
            payload=p,
            versions=cmp.versions(),
        )
        for n, p in enumerate(payloads)
    ]


def fold(state: State, payloads: Sequence[ev.Payload]) -> State:
    batch = _events(state.last_seq, payloads)
    return replay(batch, initial=state) if batch else state


def fold_changes(state: State, changes: Sequence[Feature | QuantityChange]) -> State:
    from revisionist.core.realism.resolvers import apply_changes

    return fold(state, apply_changes(state, tuple(changes)))


def order(by: str, force: str, to: str, on: date = START, n: int = 1) -> Order:
    return Order(
        order_id=OrderId(derived_id(CAMPAIGN, "adj-order", by, n)),
        issuer=seat(by),
        lever="move_piece",
        pipeline=PipelineId(derived_id(CAMPAIGN, "adj-pipeline")),
        params={"force": force, "to": to},
        status=OrderStatus.ENACTED,
        filed=on,
    )


def send(state: State, by: str, force: str, to: str, on: date = START, n: int = 1) -> State:
    return fold_changes(state, movement.order_changes(state, order(by, force, to, on, n)))


def walk(state: State, first: date, last: date) -> tuple[State, list[ev.PieceStepped]]:
    """Every day from ``first`` to ``last`` walked; the steps taken, in order."""
    stepped: list[ev.PieceStepped] = []
    day = first
    while day <= last:
        out = movement.walk(state, day)
        stepped += [p for p in out if isinstance(p, ev.PieceStepped)]
        state = fold(state, out)
        day += timedelta(days=1)
    return state, stepped


def day(n: int) -> date:
    return START + timedelta(days=n)


def drop_link(a: str, b: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["adjacency"] = [
            x for x in w["adjacency"] if not (isinstance(x, list) and set(x) == {a, b})
        ]

    return change


def set_feature(key: str, **fields: Any) -> Callable[[World], None]:
    def change(w: World) -> None:
        (found,) = [f for f in w["features"] if f["key"] == key]
        found.update(fields)

    return change


def set_entity(key: str, **fields: Any) -> Callable[[World], None]:
    def change(w: World) -> None:
        (found,) = [e for e in w["entities"] if e["key"] == key]
        found.update(fields)

    return change


def ostmark(w: World) -> None:
    """A third power holding the isle, at war with nobody."""
    w["entities"].append({"key": "ostmark", "kind": "polity", "name": "Ostmark"})
    (isle,) = [t for t in w["territories"] if t["key"] == "isle"]
    isle["holder"] = "ostmark"


def levers(w: World) -> None:
    """A field order on each leader's card that moves a piece by the movement rule."""
    w["pipelines"] = [
        {
            "key": "field_order",
            "name": "A field order",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        }
    ]
    params = [
        {
            "name": "force",
            "kind": "enum",
            "choices": ["norra_levy", "norra_kites", "norra_herald", "sudland_levy"],
        },
        {"name": "to", "kind": "enum", "choices": ["isle", "sudby", "norrhavn", "open_sea"]},
    ]
    for card in w["cards"]:
        card["pipelines"] = ["field_order"]
        card["levers"] = [
            {
                "name": "move_piece",
                "pipeline": "field_order",
                "resolver": "movement",
                "params": params,
            }
        ]


# --- Rule 1: a piece stands in one area ----------------------------------------------


def test_a_piece_declared_at_a_place_stands_in_the_area_the_place_lies_within(
    tmp_path: Path,
) -> None:
    state = play(tmp_path)
    assert where(state, "norra_levy") == entity("norra_plain")
    assert where(state, "sudland_levy") == entity("sudland_coast")
    assert where(state, "sudland_galleys") == entity("the_gulf")
    assert where(state, "norra_kites") == entity("norra_plain")


def test_a_sea_piece_declared_at_a_port_stands_in_the_sea_zone_the_port_names(
    tmp_path: Path,
) -> None:
    state = play(tmp_path, set_feature("sudland_galleys", places=["norrhavn"]))
    assert where(state, "sudland_galleys") == entity("the_gulf")
    # Norrhavn lies within the Norra plain; a land piece there stands on the plain.
    assert where(state, "norra_levy") == entity("norra_plain")
    # Sudby is no port: galleys declared there would stand on land.
    problems = refused(toy(tmp_path, set_feature("sudland_galleys", places=["sudby"])))
    assert "feature sudland_galleys: a sea piece cannot stand in sudland_coast" in problems


def test_without_territories_a_piece_stands_at_its_place_as_written() -> None:
    _, state = created(cmp.load_world(Path(__file__).parent / "worlds" / "territory-toy.yaml"))
    assert where(state, "norra_levy") == entity("norrhavn")
    assert where(state, "sudland_galleys") == entity("gulf_roads")


def test_with_territories_a_piece_at_a_place_in_no_area_is_refused(tmp_path: Path) -> None:
    def lost(w: World) -> None:
        w["entities"].append(
            {"key": "nowhere", "kind": "location", "name": "Nowhere", "at": [100, 100]}
        )
        set_feature("norra_levy", places=["nowhere"])(w)

    problems = refused(toy(tmp_path, lost))
    assert any("nowhere lies in no area" in p for p in problems), problems


def test_a_port_opens_on_a_sea_zone_its_territory_borders(tmp_path: Path) -> None:
    problems = refused(toy(tmp_path, set_entity("norrhavn", port_on="norra_hills")))
    assert any("port_on norra_hills is not a sea zone" in p for p in problems), problems
    problems = refused(toy(tmp_path, set_entity("sudby", port_on="open_sea")))
    assert any("sudland_coast does not border open_sea" in p for p in problems), problems


def test_the_board_holds_the_ports_and_the_pools(tmp_path: Path) -> None:
    state = play(tmp_path)
    assert state.map is not None
    ports = {(p.place, p.land, p.sea) for p in state.map.ports}
    assert ports == {(entity("norrhavn"), entity("norra_plain"), entity("the_gulf"))}
    assert set(state.map.lift_pools) == {entity("norra")}


# --- Rule 2: the course of fewest days for the piece's domain ------------------------


def test_a_land_piece_goes_over_land_territories(tmp_path: Path) -> None:
    state = play(tmp_path)
    found = territory.plan(state, piece(state, "norra_levy"), entity("sudby"))
    assert found == Plan((entity("norra_hills"), entity("sudland_coast")), (7, 5))


def test_a_land_piece_takes_a_declared_crossing(tmp_path: Path) -> None:
    state = play(tmp_path)
    found = territory.plan(state, piece(state, "norra_levy"), entity("isle"))
    assert found == Plan((entity("isle"),), (7,))


def test_a_sea_piece_goes_over_sea_zones_only(tmp_path: Path) -> None:
    state = play(tmp_path)
    galleys = piece(state, "sudland_galleys")
    assert territory.plan(state, galleys, entity("open_sea")) == Plan((entity("open_sea"),), (3,))
    found = territory.plan(state, galleys, entity("isle"))
    assert isinstance(found, Refused)
    assert "cannot stand in The Isle" in found.reason


def test_an_envoy_goes_over_any_area(tmp_path: Path) -> None:
    state = play(tmp_path)
    found = territory.plan(state, piece(state, "norra_herald"), entity("the_gulf"))
    assert found == Plan((entity("the_gulf"),), (2,))


def test_an_air_piece_goes_over_any_area_within_its_range_of_a_base(tmp_path: Path) -> None:
    def short(w: World) -> None:
        (kite,) = [k for k in w["piece_kinds"] if k["key"] == "kite"]
        kite["range_steps"] = 1
        set_entity("norrhavn", base={"sides": ["norra"], "domains": ["air"]})(w)

    state = play(tmp_path, short)
    kites = piece(state, "norra_kites")
    assert territory.plan(state, kites, entity("the_gulf")) == Plan((entity("the_gulf"),), (1,))
    found = territory.plan(state, kites, entity("sudby"))
    assert isinstance(found, Refused)
    assert "beyond The Norra Kites's range of 1 steps" in found.reason


def test_equal_courses_go_to_the_one_whose_area_keys_sort_first(tmp_path: Path) -> None:
    # The kites reach the Sudland coast in two days by the hills or by the gulf.
    state = play(tmp_path)
    found = territory.plan(state, piece(state, "norra_kites"), entity("sudby"))
    assert found == Plan((entity("norra_hills"), entity("sudland_coast")), (1, 1))


def test_neighbours_by_domain(tmp_path: Path) -> None:
    from revisionist.core.realism.kinds import Domain

    board = play(tmp_path).map
    assert board is not None
    plain = entity("norra_plain")
    assert set(territory.neighbours(board, plain, Domain.LAND)) == {
        entity("norra_hills"),
        entity("isle"),
    }
    assert set(territory.neighbours(board, plain, Domain.SEA)) == {
        entity("the_gulf"),
        entity("open_sea"),
    }
    assert len(territory.neighbours(board, plain, Domain.ENVOY)) == 4


# --- Rules 3 and 4: days by the terrain entered; the piece enters each area on time --


def test_a_step_takes_the_days_of_the_terrain_entered(tmp_path: Path) -> None:
    state = send(play(tmp_path), "ilse", "norra_levy", "sudby")
    levy = piece(state, "norra_levy")
    assert levy.path == (entity("norra_hills"), entity("sudland_coast"))
    assert levy.step_due == day(7)  # hills, entered first
    assert levy.arrives == day(12)


def test_the_piece_enters_each_area_on_the_day_that_step_completes(tmp_path: Path) -> None:
    state = send(play(tmp_path), "ilse", "norra_levy", "sudby")
    seen: dict[int, EntityId] = {}
    d = 1
    while d <= 13:
        state, _ = walk(state, day(d), day(d))
        seen[d] = where(state, "norra_levy")
        d += 1
    assert {n for n, a in seen.items() if a == entity("norra_plain")} == set(range(1, 7))
    assert {n for n, a in seen.items() if a == entity("norra_hills")} == set(range(7, 12))
    assert {n for n, a in seen.items() if a == entity("sudland_coast")} == {12, 13}
    levy = piece(state, "norra_levy")
    assert (levy.path, levy.step_due, levy.bound_for, levy.arrives) == ((), None, None, None)


def test_a_piece_under_way_shows_the_rest_of_its_course(tmp_path: Path) -> None:
    state = send(play(tmp_path), "ilse", "norra_levy", "sudby")
    state, _ = walk(state, day(1), day(8))
    levy = piece(state, "norra_levy")
    assert levy.places == (entity("norra_hills"),)
    assert levy.path == (entity("sudland_coast"),)
    assert levy.step_due == day(12)


def test_a_walk_over_several_days_at_once_takes_every_step_due(tmp_path: Path) -> None:
    state = send(play(tmp_path), "ilse", "norra_levy", "sudby")
    state, stepped = walk(state, day(20), day(20))
    assert where(state, "norra_levy") == entity("sudland_coast")
    assert [(s.entered, s.on) for s in stepped] == [
        (entity("norra_hills"), day(7)),
        (entity("sudland_coast"), day(12)),
    ]


# --- Rule 5: a land piece crosses the sea only by lift --------------------------------


def lift_world(w: World) -> None:
    """The border closed, Sudby a port, and a levy whose lift takes 50,000 tons."""
    drop_link("norra_hills", "sudland_coast")(w)
    set_feature("norra_levy", tier=1)(w)
    set_entity("sudby", port_on="the_gulf")(w)


def clear_gulf(state: State) -> State:
    """The Sudland galleys out of the gulf, so nothing at war stands on the lift's way."""
    away = piece(state, "sudland_galleys").model_copy(update={"places": (entity("open_sea"),)})
    return fold(state, [ev.FeatureSet(feature=away)])


def pool(state: State) -> int | None:
    q = state.quantities[territory.lift_pool(state, piece(state, "norra_levy"))]  # type: ignore[index]
    return q.value


def test_a_land_piece_crosses_by_lift_from_port_to_port(tmp_path: Path) -> None:
    state = clear_gulf(play(tmp_path, lift_world))
    assert pool(state) == 100_000
    state = send(state, "ilse", "norra_levy", "sudby")
    levy = piece(state, "norra_levy")
    assert levy.path == (entity("the_gulf"), entity("sudland_coast"))
    assert levy.step_due == day(2)  # the galley's days for shallows
    assert levy.arrives == day(7)
    assert pool(state) == 50_000  # drawn the day it sets out
    state, _ = walk(state, day(1), day(3))
    assert where(state, "norra_levy") == entity("the_gulf")
    assert pool(state) == 50_000
    state, _ = walk(state, day(4), day(7))
    assert where(state, "norra_levy") == entity("sudland_coast")
    assert pool(state) == 100_000  # given back the day it lands


def test_no_lift_without_a_kind_that_carries_it(tmp_path: Path) -> None:
    def no_carrier(w: World) -> None:
        (galley,) = [k for k in w["piece_kinds"] if k["key"] == "galley"]
        galley["carries"] = []

    state = play(tmp_path, lift_world, no_carrier)
    assert isinstance(territory.plan(state, piece(state, "norra_levy"), entity("sudby")), Refused)
    assert send(state, "ilse", "norra_levy", "sudby") == state


def test_no_lift_without_a_pool_or_with_one_too_small(tmp_path: Path) -> None:
    state = play(tmp_path, lift_world, set_entity("norra", lift_pool=None))
    assert isinstance(territory.plan(state, piece(state, "norra_levy"), entity("sudby")), Refused)
    state = play(tmp_path, lift_world, set_feature("norra_levy", tier=3))
    assert isinstance(territory.plan(state, piece(state, "norra_levy"), entity("sudby")), Refused)
    assert send(state, "ilse", "norra_levy", "sudby") == state


def test_a_lift_lands_only_at_a_port(tmp_path: Path) -> None:
    def no_port(w: World) -> None:
        lift_world(w)
        set_entity("sudby", port_on=None)(w)

    state = clear_gulf(play(tmp_path, no_port))
    assert isinstance(territory.plan(state, piece(state, "norra_levy"), entity("sudby")), Refused)


def test_a_lift_embarks_only_at_a_port(tmp_path: Path) -> None:
    # From the hills, with no port there, the levy marches to Norrhavn first.
    state = play(tmp_path, lift_world, set_feature("norra_levy", places=["norrhavn"]))
    state = send(state, "ilse", "norra_levy", "isle")  # by the ferry: no lift
    state, _ = walk(state, day(1), day(7))
    state = send(state, "ilse", "norra_levy", "sudby", on=day(7), n=2)
    levy = piece(state, "norra_levy")
    assert levy.path == (
        entity("norra_plain"),
        entity("the_gulf"),
        entity("sudland_coast"),
    )


def test_a_land_piece_marches_where_land_reaches(tmp_path: Path) -> None:
    # With the border open the levy marches, though the lift would be quicker.
    state = play(tmp_path, set_feature("norra_levy", tier=1))
    state = send(state, "ilse", "norra_levy", "sudby")
    assert piece(state, "norra_levy").path[0] == entity("norra_hills")
    assert pool(state) == 100_000


# --- Rule 6: a neutral's territory is closed ------------------------------------------


def test_a_step_into_a_neutrals_territory_is_refused(tmp_path: Path) -> None:
    state = play(tmp_path, ostmark)
    found = territory.plan(state, piece(state, "norra_levy"), entity("isle"))
    assert isinstance(found, Refused)
    assert "held by Ostmark, neither Norra's ally nor at war with it" in found.reason
    assert send(state, "ilse", "norra_levy", "isle") == state


def test_an_allys_territory_is_open(tmp_path: Path) -> None:
    def ally(w: World) -> None:
        w["wars"].append({"a": "ostmark", "b": "sudland", "since": "1900-03-15", "source": "toy"})

    state = play(tmp_path, ostmark, ally)
    found = territory.plan(state, piece(state, "norra_levy"), entity("isle"))
    assert found == Plan((entity("isle"),), (7,))


def test_an_enemys_territory_is_open(tmp_path: Path) -> None:
    state = play(tmp_path, ostmark)
    state = fold(
        state,
        [
            ev.WarDeclared(
                war=War(
                    war_id=war_id_for(entity("norra"), entity("ostmark")),
                    a=entity("norra"),
                    b=entity("ostmark"),
                    since=START,
                    declared_by=entity("norra"),
                )
            )
        ],
    )
    assert isinstance(territory.plan(state, piece(state, "norra_levy"), entity("isle")), Plan)


def test_a_piece_under_way_stops_short_of_a_closed_area(tmp_path: Path) -> None:
    state = send(play(tmp_path), "ilse", "norra_levy", "isle")
    # The isle passes to a holder neither Norra's ally nor at war with it while the levy is
    # on the ferry.
    assert state.map is not None
    held = tuple(
        t.model_copy(update={"holder": entity("ilse")}) if t.area == entity("isle") else t
        for t in state.map.territories
    )
    state = state.model_copy(update={"map": state.map.model_copy(update={"territories": held})})
    state, stepped = walk(state, day(1), day(10))
    assert where(state, "norra_levy") == entity("norra_plain")
    assert stepped == []
    assert piece(state, "norra_levy").path == ()


# --- Rule 7: an enemy at war ends the move --------------------------------------------


def test_a_step_into_an_area_an_enemy_stands_in_ends_the_move_there(tmp_path: Path) -> None:
    state = play(tmp_path)
    blocker = piece(state, "sudland_levy").model_copy(update={"places": (entity("norra_hills"),)})
    state = fold(state, [ev.FeatureSet(feature=blocker)])
    state = send(state, "ilse", "norra_levy", "sudby")
    state, stepped = walk(state, day(1), day(20))
    assert where(state, "norra_levy") == entity("norra_hills")
    assert [s.entered for s in stepped] == [entity("norra_hills")]
    assert piece(state, "norra_levy").path == ()


def test_an_envoy_of_a_power_at_war_does_not_stop_a_move(tmp_path: Path) -> None:
    def herald(w: World) -> None:
        w["features"].append(
            {
                "key": "sudland_herald",
                "kind": "piece",
                "piece": "herald",
                "name": "The Sudland Herald",
                "side": "sudland",
                "places": ["sudby"],
                "source": "toy",
            }
        )

    state = play(tmp_path, herald)
    envoy = piece(state, "sudland_herald").model_copy(update={"places": (entity("norra_hills"),)})
    state = fold(state, [ev.FeatureSet(feature=envoy)])
    state = send(state, "ilse", "norra_levy", "sudby")
    state, _ = walk(state, day(1), day(20))
    assert where(state, "norra_levy") == entity("sudland_coast")


# --- Rule 8: bases and reach in steps -------------------------------------------------


def based(w: World) -> None:
    set_entity("norrhavn", base={"sides": ["norra"], "domains": ["land", "sea", "air"]})(w)
    set_entity("sudby", base={"sides": ["sudland"], "domains": ["sea"]}, port_on="the_gulf")(w)


def test_reach_is_counted_in_steps_from_the_nearest_base(tmp_path: Path) -> None:
    state = play(tmp_path, based)
    kites = piece(state, "norra_kites")
    tiers = {
        k: bases.area_reach(state, kites, entity(k))
        for k in ("norra_plain", "norra_hills", "the_gulf", "sudland_coast")
    }
    assert {k: (r.tier, r.steps) for k, r in tiers.items() if r is not None} == {
        "norra_plain": (Tier.SUSTAINED, 0),
        "norra_hills": (Tier.OPERATE, 1),
        "the_gulf": (Tier.OPERATE, 1),
        "sudland_coast": (Tier.RAID, 2),
    }
    assert tiers["norra_hills"] is not None and tiers["norra_hills"].base == entity("norrhavn")


def test_a_fleet_at_its_port_is_sustained_in_the_sea_zone(tmp_path: Path) -> None:
    state = play(tmp_path, based)
    found = bases.area_reach(state, piece(state, "sudland_galleys"), entity("the_gulf"))
    assert found is not None and (found.tier, found.base) == (Tier.SUSTAINED, entity("sudby"))
    found = bases.area_reach(state, piece(state, "sudland_galleys"), entity("open_sea"))
    assert found is not None and (found.tier, found.steps) == (Tier.OPERATE, 1)


def test_the_default_radii_in_steps() -> None:
    assert RADIUS_STEPS == {
        "land": Radius(2, None),
        "sea": Radius(3, 6),
        "air": Radius(1, 2),
    }


def test_past_the_radius_a_move_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(RADIUS_STEPS, "land", Radius(1, None))
    state = play(tmp_path, based)
    levy = piece(state, "norra_levy")
    found = bases.area_reach(state, levy, entity("sudland_coast"))
    assert found is not None and found.tier is Tier.REFUSED
    refusal = territory.plan(state, levy, entity("sudby"))
    assert isinstance(refusal, Refused)
    assert "2 steps from Norrhavn, past 1" in refusal.reason
    assert send(state, "ilse", "norra_levy", "sudby") == state


def test_no_reach_rule_for_a_board_with_no_bases_or_for_an_envoy(tmp_path: Path) -> None:
    state = play(tmp_path)
    assert bases.area_reach(state, piece(state, "norra_levy"), entity("isle")) is None
    state = play(tmp_path, based)
    assert bases.area_reach(state, piece(state, "norra_herald"), entity("isle")) is None


def test_a_base_is_a_place_within_an_area_serving_polities(tmp_path: Path) -> None:
    problems = refused(
        toy(tmp_path, set_entity("norrhavn", base={"sides": ["ilse"], "domains": ["land"]}))
    )
    assert any("base side ilse is not a polity" in p for p in problems), problems


# --- Rule 9: a refusal names its reason and the nearest area --------------------------


def test_a_refusal_names_the_nearest_area_the_piece_could_be_sent_to(tmp_path: Path) -> None:
    state = play(tmp_path)
    found = territory.plan(state, piece(state, "norra_levy"), entity("open_sea"))
    assert isinstance(found, Refused)
    assert found.reason.startswith("The Norra Levy cannot stand in The Open Sea.")
    assert found.nearest == entity("isle")
    assert found.reason.endswith("The nearest area it could be sent to is The Isle.")


def test_the_order_is_refused_at_filing_with_those_words(tmp_path: Path) -> None:
    state = play(tmp_path, ostmark, levers)
    words = order_refusal(state, seat("ilse"), "move_piece", {"force": "norra_levy", "to": "isle"})
    assert "held by Ostmark" in words
    assert "The nearest area it could be sent to is" in words
    assert (
        order_refusal(state, seat("ilse"), "move_piece", {"force": "norra_levy", "to": "sudby"})
        == ""
    )


# --- Rule 10: an order to a piece under way re-plans from where it is ------------------


def test_an_order_to_a_piece_under_way_replans_from_the_area_it_is_in(tmp_path: Path) -> None:
    state = send(play(tmp_path), "ilse", "norra_levy", "sudby")
    state, _ = walk(state, day(1), day(8))
    assert where(state, "norra_levy") == entity("norra_hills")
    state = send(state, "ilse", "norra_levy", "isle", on=day(8), n=2)
    levy = piece(state, "norra_levy")
    assert levy.path == (entity("norra_plain"), entity("isle"))
    assert levy.step_due == day(13)  # five days on the plain from the hills
    assert levy.arrives == day(20)


def test_an_order_to_where_the_piece_stands_halts_it(tmp_path: Path) -> None:
    state = send(play(tmp_path), "ilse", "norra_levy", "sudby")
    state, _ = walk(state, day(1), day(8))
    state = send(state, "ilse", "norra_levy", "norra_hills", on=day(8), n=2)
    levy = piece(state, "norra_levy")
    assert (levy.places, levy.path, levy.step_due) == ((entity("norra_hills"),), (), None)


def test_only_the_issuers_own_side_moves(tmp_path: Path) -> None:
    state = play(tmp_path)
    assert send(state, "tomas", "norra_levy", "sudby") == state


# --- Rule 11: steps_within ------------------------------------------------------------


def test_steps_within_returns_every_area_reachable_in_the_days(tmp_path: Path) -> None:
    state = play(tmp_path)
    assert state.kinds is not None and state.map is not None
    levy, galley = state.kinds.pieces["levy"], state.kinds.pieces["galley"]
    plain, gulf = entity("norra_plain"), entity("the_gulf")
    assert territory.steps_within(state.map, levy, plain, 6) == {plain: 0}
    assert territory.steps_within(state.map, levy, plain, 7) == {
        plain: 0,
        entity("norra_hills"): 7,
        entity("isle"): 7,
    }
    assert territory.steps_within(state.map, levy, plain, 12)[entity("sudland_coast")] == 12
    assert territory.steps_within(state.map, galley, gulf, 3) == {gulf: 0, entity("open_sea"): 3}


# --- Rule 12: one function completes a step; one event a step --------------------------


def test_each_step_lands_one_piece_stepped_event(tmp_path: Path) -> None:
    state = send(play(tmp_path), "ilse", "norra_levy", "sudby")
    state, stepped = walk(state, day(1), day(13))
    mark = territory.mark_key(state, entity("norra"), piece(state, "norra_levy"))
    assert [(s.mark, s.nation, s.left, s.entered, s.on, s.cause) for s in stepped] == [
        (
            mark,
            entity("norra"),
            entity("norra_plain"),
            entity("norra_hills"),
            day(7),
            StepCause.ORDERED,
        ),
        (
            mark,
            entity("norra"),
            entity("norra_hills"),
            entity("sudland_coast"),
            day(12),
            StepCause.ORDERED,
        ),
    ]


def test_a_scripted_leg_moves_step_by_step(tmp_path: Path) -> None:
    state = play(
        tmp_path, set_feature("norra_levy", legs=[{"since": "1900-04-05", "places": ["sudby"]}])
    )
    state, stepped = walk(state, day(1), day(20))
    assert where(state, "norra_levy") == entity("sudland_coast")
    assert [(s.entered, s.on, s.cause) for s in stepped] == [
        (entity("norra_hills"), day(10), StepCause.SCRIPTED),
        (entity("sudland_coast"), day(15), StepCause.SCRIPTED),
    ]
    assert piece(state, "norra_levy").legs == ()


def test_a_piece_sent_by_an_effect_takes_its_course_step_by_step(tmp_path: Path) -> None:
    # An effect (``apply._move``) sets only where it is bound and when it arrives.
    state = play(tmp_path)
    levy = piece(state, "norra_levy")
    from revisionist.core.realism.routing import travel_days

    days = travel_days(state, levy, entity("sudland_coast"))
    assert days == 12
    sent = levy.model_copy(
        update={"bound_for": entity("sudland_coast"), "arrives": START + timedelta(days=12)}
    )
    state = fold(state, [ev.FeatureSet(feature=sent)])
    state, stepped = walk(state, day(1), day(12))
    assert where(state, "norra_levy") == entity("sudland_coast")
    assert [s.on for s in stepped] == [day(7), day(12)]


def test_a_forced_step_goes_through_the_same_function(tmp_path: Path) -> None:
    state = play(tmp_path)
    moved, stepped = territory.step(
        state, piece(state, "sudland_levy"), entity("norra_hills"), day(3), StepCause.FORCED
    )
    assert moved.places == (entity("norra_hills"),)
    assert (stepped.left, stepped.cause, stepped.nation) == (
        entity("sudland_coast"),
        StepCause.FORCED,
        entity("sudland"),
    )
    with pytest.raises(ValueError, match="does not border"):
        territory.step(
            state, piece(state, "sudland_levy"), entity("isle"), day(3), StepCause.FORCED
        )


def test_the_mark_key_is_opaque_and_per_nation(tmp_path: Path) -> None:
    state = play(tmp_path)
    levy = piece(state, "norra_levy")
    mine = territory.mark_key(state, entity("norra"), levy)
    assert mine == territory.mark_key(state, entity("norra"), levy)
    assert mine != territory.mark_key(state, entity("sudland"), levy)
    assert str(levy.feature_id) not in mine and str(levy.feature_id).lower() not in mine


# --- Sealed to the piece's own nation, in the day walk ---------------------------------


class Logged:
    """A game whose every event is kept, for the day walk and the catch-up feed."""

    def __init__(self, world: WorldFile, *people: str) -> None:
        self.log, _ = created(world)
        self.state = replay(self.log)
        self.add([ev.CharacterClaimed(seat_id=seat(p), entity_id=entity(p)) for p in people])

    def add(self, payloads: Sequence[ev.Payload]) -> None:
        before = self.state.last_seq
        self.state = fold(self.state, payloads)
        self.log += [e.model_copy() for e in _events(before, payloads)]

    def send(self, by: str, force: str, to: str) -> None:
        from revisionist.core.realism.resolvers import apply_changes

        self.add(
            apply_changes(self.state, movement.order_changes(self.state, order(by, force, to)))
        )

    def walk(self, first: date, last: date) -> list[ev.Event]:
        store = MemoryStore()
        store.append_all(self.log)
        em = Emitter(store, self.state, cmp.versions())
        out = realism_tick._walk(em, self.log, first - timedelta(days=1), last)
        self.log += out
        self.state = replay(out, initial=self.state)
        return out


def test_the_day_walk_seals_each_step_to_the_seats_of_the_pieces_nation(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path), "ilse", "tomas")
    g.send("ilse", "norra_levy", "sudby")
    g.send("tomas", "sudland_galleys", "open_sea")
    out = g.walk(day(1), day(13))
    steps = [e for e in out if isinstance(e.payload, ev.PieceStepped)]
    norra = [e for e in steps if e.payload.nation == entity("norra")]  # type: ignore[union-attr]
    sudland = [e for e in steps if e.payload.nation == entity("sudland")]  # type: ignore[union-attr]
    assert len(norra) == 2 and len(sudland) == 1
    for e in norra:
        assert e.scope.visibility is Visibility.RESTRICTED
        assert e.scope.known_by == frozenset({seat("ilse")})
    for e in sudland:
        assert e.scope.known_by == frozenset({seat("tomas")})
    assert where(g.state, "norra_levy") == entity("sudland_coast")


def test_an_enemy_pieces_step_is_not_in_another_nations_seat_events(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path), "ilse", "tomas")
    g.send("ilse", "norra_levy", "sudby")
    g.walk(day(1), day(13))
    theirs = catchup.feed(g.state, g.log, seat("tomas"), 0, 10)
    mine = catchup.feed(g.state, g.log, seat("ilse"), 0, 10)
    assert not [f for f in theirs if f.event.kind == "piece_stepped"]
    assert len([f for f in mine if f.event.kind == "piece_stepped"]) == 2


def test_a_nation_no_seat_holds_has_its_steps_sealed_from_every_seat(tmp_path: Path) -> None:
    events, state = game(toy(tmp_path))
    nobody = realism_tick._nation_scope(state, entity("sudland"))
    assert seat("tomas") in nobody.known_by
    events, _ = created(toy(tmp_path))
    bare = claim(events, "ilse")
    nobody = realism_tick._nation_scope(bare, entity("sudland"))
    assert nobody.visibility is Visibility.RESTRICTED
    assert not nobody.visible_to(seat("ilse")) and not nobody.visible_to(seat("tomas"))


# --- Invariant 3: the same filings in either order give the same positions -------------


def test_two_seats_orders_in_either_order_give_the_same_positions_day_by_day(
    tmp_path: Path,
) -> None:
    state = play(tmp_path)
    north = order("ilse", "norra_levy", "sudby")
    south = order("tomas", "sudland_levy", "norrhavn")

    def run(first: Order, second: Order) -> list[tuple[EntityId, EntityId]]:
        s = fold_changes(state, movement.order_changes(state, first))
        s = fold_changes(s, movement.order_changes(s, second))
        seen = []
        for n in range(1, 21):
            s, _ = walk(s, day(n), day(n))
            seen.append((where(s, "norra_levy"), where(s, "sudland_levy")))
        return seen

    ab, ba = run(north, south), run(south, north)
    assert ab == ba
    # They meet in the hills, where each move ends.
    assert ab[-1] == (entity("norra_hills"), entity("norra_hills"))


# --- The old rule stays for games without territories --------------------------------


def test_without_territories_no_piece_walks_and_no_order_moves_one() -> None:
    events, _ = created(cmp.load_world(Path(__file__).parent / "worlds" / "territory-toy.yaml"))
    state = claim(events, "ilse", "tomas")
    assert movement.walk(state, day(5)) == []
    assert movement.order_changes(state, order("ilse", "norra_levy", "sudby")) == ()


def test_a_stored_feature_dumps_as_before() -> None:
    f = Feature.model_validate(
        {
            "feature_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "kind": "army",
            "name": "An army",
            "side": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
            "places": ["01ARZ3NDEKTSV4RRFFQ69G5FAX"],
            "as_of": "1941-09-01",
        }
    )
    assert "path" not in f.model_dump() and "step_due" not in f.model_dump()


def test_path_and_step_due_go_together() -> None:
    with pytest.raises(ValueError, match="path and step_due go together"):
        Feature.model_validate(
            {
                "feature_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "kind": "army",
                "name": "An army",
                "side": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
                "places": ["01ARZ3NDEKTSV4RRFFQ69G5FAX"],
                "as_of": "1941-09-01",
                "path": ["01ARZ3NDEKTSV4RRFFQ69G5FAY"],
            }
        )
