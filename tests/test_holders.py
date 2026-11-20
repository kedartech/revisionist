"""Who holds each territory, and capture that takes time (THL).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories`` and
``holders`` on. Norra and Sudland are at war. A Norra levy sent to the Isle (Sudland's,
by the ferry) stands there from the day its step completes; Sudland's levy is taken off
the board where a test needs the Isle or the coast empty of Sudland land pieces.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay, state_hash
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.project import project
from revisionist.core.realism import bases, holders, territory
from revisionist.core.realism.bases import Tier
from revisionist.core.realism.document import DocumentKind
from revisionist.core.realism.holders import CAPTURE_DAYS, Capture
from revisionist.core.realism.kinds import Domain
from revisionist.core.realism.territory import Base
from revisionist.core.realism.war import war_id_for
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, Visibility
from revisionist.core.world import WorldFile
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick
from revisionist.engine.emit import Emitter
from revisionist.engine.store import MemoryStore
from tests.async_table import digest
from tests.test_adjacency_moves import (
    START,
    Logged,
    World,
    day,
    entity,
    order,
    piece,
    seat,
    set_entity,
)
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_territory_model import CAMPAIGN, created, refused, variant

ISLE = "isle"
COAST = "sudland_coast"


def with_holders(w: World) -> None:
    w["rules"] = ["territories", "holders"]


def toy(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    """The toy world with ``territories`` and ``holders`` on and ``changes`` applied."""
    return territories_toy(tmp, with_holders, *changes)


def without(key: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["features"] = [f for f in w["features"] if f["key"] != key]

    return change


def capital(polity: str, place: str) -> Callable[[World], None]:
    return set_entity(polity, capital=place)


def add_entity(**fields: Any) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["entities"].append(fields)

    return change


def holder(state: State, area: str) -> EntityId | None:
    return territory.holder(state, entity(area))


def held(out: Sequence[ev.Event]) -> list[ev.AreaHeld]:
    return [e.payload for e in out if isinstance(e.payload, ev.AreaHeld)]


def to_isle(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    """Norra's levy sent to the Isle, which nobody defends: its step completes on day 7."""
    g = Logged(toy(tmp, *changes), "ilse", "tomas")
    g.send("ilse", "norra_levy", ISLE)
    return g


ARRIVES = day(7)


# --- Rule 1: every land territory starts with the world's holder; holders are public ----


def test_every_territory_starts_with_the_holder_the_world_gives(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path), "ilse", "tomas")
    assert holder(g.state, "norra_hills") == entity("norra")
    assert holder(g.state, "norra_plain") == entity("norra")
    assert holder(g.state, COAST) == entity("sudland")
    assert holder(g.state, ISLE) == entity("sudland")
    assert holder(g.state, "the_gulf") is None and holder(g.state, "open_sea") is None
    assert g.state.holders == {} and g.state.captures == {}


def test_holders_are_public_every_view_holds_the_same(tmp_path: Path) -> None:
    g = to_isle(tmp_path, without("sudland_levy"))
    g.walk(day(1), day(12))
    assert g.state.holders  # the Isle has changed hands
    for person in ("ilse", "tomas"):
        view = project(g.state, seat(person))
        assert view.holders == g.state.holders
        assert territory.holder(view, entity(ISLE)) == entity("norra")
        assert "captures" not in type(view).model_fields  # the count stays engine side


def test_holders_need_the_territory_rules(tmp_path: Path) -> None:
    problems = refused(variant(tmp_path, lambda w: w.update(rules=["holders"])))
    assert "rules: holders needs territories" in problems


def test_a_capital_is_a_place_in_a_territory_of_a_polity(tmp_path: Path) -> None:
    assert "entity ilse: only a polity has a capital" in refused(
        toy(tmp_path, capital("ilse", "sudby"))
    )
    assert "entity sudland: capital gulf_roads lies within no territory" in refused(
        toy(tmp_path, capital("sudland", "gulf_roads"))
    )
    assert "entity sudland: capital tomas is not a place" in refused(
        toy(tmp_path, capital("sudland", "tomas"))
    )
    _, state = created(toy(tmp_path, capital("sudland", "sudby")))
    assert state.map is not None
    assert state.map.capitals == {entity("sudland"): entity("sudby")}
    assert holders.capitals_in(state, entity(COAST)) == (entity("sudland"),)
    assert holders.capitals_in(state, entity(ISLE)) == ()


# --- Rule 2: a land piece that stands CAPTURE_DAYS full days unopposed takes it -----------


def test_the_default_capture_days() -> None:
    assert CAPTURE_DAYS == 2


def test_a_levy_takes_an_undefended_enemy_territory_after_two_full_days(
    tmp_path: Path,
) -> None:
    g = to_isle(tmp_path, without("sudland_levy"))
    g.walk(day(1), ARRIVES)
    assert territory.area_of(
        g.state, piece(g.state, "norra_levy").places[0], Domain.LAND
    ) == entity(ISLE)
    assert holder(g.state, ISLE) == entity("sudland")
    assert g.state.captures[entity(ISLE)] == Capture(by=entity("norra"), since=ARRIVES)
    g.walk(ARRIVES + timedelta(days=1), ARRIVES + timedelta(days=1))
    assert holder(g.state, ISLE) == entity("sudland")  # one full day is not enough
    out = g.walk(ARRIVES + timedelta(days=2), ARRIVES + timedelta(days=2))
    assert holder(g.state, ISLE) == entity("norra")
    assert held(out) == [
        ev.AreaHeld(
            area=entity(ISLE),
            holder=entity("norra"),
            was=entity("sudland"),
            on=ARRIVES + timedelta(days=CAPTURE_DAYS),
        )
    ]
    assert entity(ISLE) not in g.state.captures


def test_no_territory_is_taken_while_an_enemy_land_piece_stands_there(tmp_path: Path) -> None:
    # Sudland's levy stands at Sudby, on the coast; Norra's levy marches in and stops there.
    g = Logged(toy(tmp_path), "ilse", "tomas")
    g.send("ilse", "norra_levy", "sudby")
    out = g.walk(day(1), day(40))
    assert piece(g.state, "norra_levy").places == (entity(COAST),)
    assert piece(g.state, "sudland_levy").places == (entity(COAST),)
    assert held(out) == []
    assert holder(g.state, COAST) == entity("sudland")
    assert entity(COAST) not in g.state.captures


def test_an_enemy_land_piece_arriving_stops_the_count(tmp_path: Path) -> None:
    g = to_isle(tmp_path, without("sudland_levy"))
    g.walk(day(1), ARRIVES + timedelta(days=1))
    assert g.state.captures[entity(ISLE)].since == ARRIVES
    # A Sudland levy is raised on the Isle: the count stops, and nothing is taken.
    levy = piece(g.state, "norra_levy").model_copy(
        update={
            "feature_id": FeatureId(entity("sudland_levy")),
            "name": "The Sudland Levy",
            "side": entity("sudland"),
            "places": (entity(ISLE),),
            "path": (),
            "step_due": None,
            "bound_for": None,
            "arrives": None,
        }
    )
    g.add([ev.FeatureSet(feature=levy)])
    out = g.walk(ARRIVES + timedelta(days=2), ARRIVES + timedelta(days=10))
    assert held(out) == []
    assert entity(ISLE) not in g.state.captures
    assert holder(g.state, ISLE) == entity("sudland")


def test_the_count_starts_again_when_the_piece_leaves_and_comes_back(tmp_path: Path) -> None:
    g = to_isle(tmp_path, without("sudland_levy"))
    g.walk(day(1), ARRIVES + timedelta(days=1))
    assert g.state.captures[entity(ISLE)].since == ARRIVES

    def put(area: str, on: date) -> None:
        moved = piece(g.state, "norra_levy").model_copy(
            update={"places": (entity(area),), "as_of": on}
        )
        g.add([ev.FeatureSet(feature=moved)])

    put("norra_plain", ARRIVES + timedelta(days=2))
    g.walk(ARRIVES + timedelta(days=2), ARRIVES + timedelta(days=2))
    assert entity(ISLE) not in g.state.captures  # gone a day: the count stops
    put(ISLE, ARRIVES + timedelta(days=3))
    out = g.walk(ARRIVES + timedelta(days=3), ARRIVES + timedelta(days=4))
    assert held(out) == []
    assert g.state.captures[entity(ISLE)].since == ARRIVES + timedelta(days=3)
    out = g.walk(ARRIVES + timedelta(days=5), ARRIVES + timedelta(days=5))
    assert [h.on for h in held(out)] == [ARRIVES + timedelta(days=5)]


def test_sea_air_and_envoy_pieces_take_nothing(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path, without("sudland_levy")), "ilse", "tomas")
    herald = piece(g.state, "norra_herald")  # an envoy may not step into enemy ground (ENV)
    g.add([ev.FeatureSet(feature=herald.model_copy(update={"places": (entity(ISLE),)}))])
    g.send("tomas", "sudland_galleys", "open_sea")
    out = g.walk(day(1), day(30))
    assert piece(g.state, "norra_herald").places == (entity(ISLE),)
    assert held(out) == [] and g.state.captures == {}


def test_a_polity_never_takes_its_own_territory(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path), "ilse", "tomas")
    out = g.walk(day(1), day(30))  # Norra's levy at home, Sudland's at Sudby
    assert held(out) == [] and g.state.captures == {}


def test_a_polity_at_peace_with_the_holder_takes_nothing(tmp_path: Path) -> None:
    g = to_isle(tmp_path, without("sudland_levy"))
    peace = {
        k: v for k, v in g.state.wars.items() if k != war_id_for(entity("norra"), entity("sudland"))
    }
    g.state = g.state.model_copy(update={"wars": peace})
    assert holders.takers(g.state, entity(ISLE)) == ()
    piece_on_isle = piece(g.state, "norra_levy").model_copy(
        update={"places": (entity(ISLE),), "path": (), "step_due": None}
    )
    g.state = g.state.model_copy(
        update={"features": {**g.state.features, piece_on_isle.feature_id: piece_on_isle}}
    )
    assert holders.takers(g.state, entity(ISLE)) == ()
    assert holders.walk(g.state, day(30)) == []


# --- Rule 3: each change lands one area_held, public, fed to every seat -----------------


def test_each_change_lands_one_public_area_held_fed_to_every_seat(tmp_path: Path) -> None:
    g = to_isle(tmp_path, without("sudland_levy"))
    out = g.walk(day(1), day(20))
    changes = [e for e in out if isinstance(e.payload, ev.AreaHeld)]
    assert len(changes) == 1
    assert changes[0].scope == PUBLIC
    assert g.state.holders[entity(ISLE)] == holders.Holding(
        holder=entity("norra"), taken_from=entity("sudland"), on=ARRIVES + timedelta(days=2)
    )
    for person in ("ilse", "tomas"):
        fed = catchup.feed(g.state, g.log, seat(person), 0, 10_000)
        assert [f.event.kind for f in fed].count("area_held") == 1
        assert not [f for f in fed if f.event.kind == "capture_counted"]


def test_the_count_is_engine_only(tmp_path: Path) -> None:
    assert "area_held" in catchup.FEED_KINDS
    assert "capture_counted" in catchup.NEVER
    g = to_isle(tmp_path, without("sudland_levy"))
    out = g.walk(day(1), day(20))
    counts = [e for e in out if isinstance(e.payload, ev.CaptureCounted)]
    assert counts
    for e in counts:
        assert e.scope.visibility is Visibility.RESTRICTED
        assert not e.scope.visible_to(seat("ilse")) and not e.scope.visible_to(seat("tomas"))


def test_a_taken_territory_can_be_taken_back(tmp_path: Path) -> None:
    g = to_isle(tmp_path, without("sudland_levy"))
    g.walk(day(1), day(10))
    assert holder(g.state, ISLE) == entity("norra")
    g.send("ilse", "norra_levy", "norrhavn")
    g.walk(day(11), day(30))
    assert holder(g.state, ISLE) == entity("norra")  # empty, it stays with its holder
    # A Sudland piece lands on the Isle and stands there: it takes it back.
    back = piece(g.state, "norra_herald").model_copy(
        update={
            "feature_id": FeatureId(entity("sudland_levy")),
            "piece": "levy",
            "side": entity("sudland"),
            "places": (entity(ISLE),),
            "as_of": day(30),
        }
    )
    g.add([ev.FeatureSet(feature=back)])
    out = g.walk(day(31), day(33))
    assert [(h.holder, h.was, h.on) for h in held(out)] == [
        (entity("sudland"), entity("norra"), day(33))
    ]


# --- Rule 4: a capital's territory falls only after a whole wake's notice ---------------


class Wakes:
    """The toy game run through ``run_realism_tick``: each call is one close."""

    def __init__(self, g: Logged) -> None:
        self.store = MemoryStore()
        g.add([ev.SessionZeroClosed()])
        self.store.append_all(g.log)

    @property
    def log(self) -> list[ev.Event]:
        return list(self.store.read(CAMPAIGN))

    @property
    def state(self) -> State:
        return replay(self.log)

    def close(self) -> list[ev.Event]:
        before = len(self.log)
        realism_tick.run_realism_tick(self.store, CAMPAIGN)
        return self.log[before:]

    def add(self, payloads: Sequence[ev.Payload]) -> None:
        em = Emitter(self.store, self.state, cmp.versions())
        em.commit([em.event(p) for p in payloads])


def to_capital(tmp: Path, *changes: Callable[[World], None]) -> Wakes:
    """Norra's levy sent to Sudby, Sudland's capital, which nobody defends: it enters the
    coast on day 12, and the count is full at the end of day 14, inside the first wake."""
    g = Logged(
        toy(tmp, without("sudland_levy"), capital("sudland", "sudby"), *changes), "ilse", "tomas"
    )
    g.send("ilse", "norra_levy", "sudby")
    return Wakes(g)


def test_a_capitals_territory_is_not_taken_at_once_but_marked(tmp_path: Path) -> None:
    w = to_capital(tmp_path)
    out = w.close()
    state = w.state
    assert state.in_world_date == date(1900, 4, 16)
    assert held(out) == []
    assert holder(state, COAST) == entity("sudland")
    mark = state.captures[entity(COAST)]
    assert mark.by == entity("norra") and mark.marked_on == date(1900, 4, 16)
    assert mark.marked is not None and mark.marked < state.tick


def test_the_holding_seat_gets_a_paper_and_a_matter_due(tmp_path: Path) -> None:
    w = to_capital(tmp_path)
    out = w.close()
    state = w.state
    papers = [e for e in out if isinstance(e.payload, ev.DocumentIssued)]
    falling = [e for e in papers if e.payload.document.title.startswith("The Sudland Coast")]  # type: ignore[union-attr]
    assert len(falling) == 1
    page = falling[0].payload.document  # type: ignore[union-attr]
    assert page.kind is DocumentKind.REPORT and page.author == entity("sudland")
    assert page.scope.known_by == frozenset({seat("tomas")})
    assert page.arrives == date(1900, 4, 16)
    # The matter the holding seat's agenda lists (the rules lane's due-matters registry
    # reads it), named by the paper that brought it.
    assert holders.falling(state, seat("tomas")) == [(entity(COAST), date(1900, 4, 16))]
    assert holders.paper_id(state, entity(COAST), date(1900, 4, 16), seat("tomas")) == page.doc_id
    assert holders.falling(state, seat("ilse")) == []


def test_the_capital_falls_at_the_close_of_the_next_wake(tmp_path: Path) -> None:
    w = to_capital(tmp_path)
    w.close()
    out = w.close()
    state = w.state
    assert [(h.holder, h.was, h.on) for h in held(out)] == [
        (entity("norra"), entity("sudland"), date(1900, 4, 30))
    ]
    assert holder(state, COAST) == entity("norra")
    assert entity(COAST) not in state.captures
    assert holders.falling(state, seat("tomas")) == []


def test_a_relieved_capital_does_not_fall_and_loses_its_mark(tmp_path: Path) -> None:
    w = to_capital(tmp_path)
    w.close()
    # In the second wake a Sudland levy stands on the coast again.
    levy = w.state.features[FeatureId(entity("norra_levy"))].model_copy(
        update={
            "feature_id": FeatureId(entity("sudland_levy")),
            "name": "The Sudland Levy",
            "side": entity("sudland"),
            "places": (entity(COAST),),
            "path": (),
            "step_due": None,
            "bound_for": None,
            "arrives": None,
        }
    )
    w.add([ev.FeatureSet(feature=levy)])
    out = w.close()
    assert held(out) == []
    assert holder(w.state, COAST) == entity("sudland")
    assert entity(COAST) not in w.state.captures


def test_a_mark_is_not_judged_in_the_wake_that_made_it(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path, without("sudland_levy"), capital("sudland", "sudby")), "ilse", "tomas")
    g.send("ilse", "norra_levy", "sudby")
    g.walk(day(1), day(20))
    c = g.state.captures[entity(COAST)]
    assert c.marked == g.state.tick and c.full(day(20))
    assert holders.close(g.state, day(20)) == []
    later = g.state.model_copy(update={"tick": g.state.tick + 1})
    assert holders.close(later, day(21)) == [
        ev.AreaHeld(area=entity(COAST), holder=entity("norra"), was=entity("sudland"), on=day(21))
    ]


def test_away_and_present_read_the_same_capital_warning(tmp_path: Path) -> None:
    """Invariant 2: the holding seat's paper and agenda item do not depend on whether its
    player is there to read them."""
    seen: list[object] = []
    for present in (True, False):
        (tmp_path / str(present)).mkdir()
        w = to_capital(tmp_path / str(present))
        w.close()
        if present:
            state = w.state
            w.add(
                [
                    ev.DocumentRead(seat_id=seat("tomas"), doc_id=d)
                    for d in state.documents
                    if state.documents[d].view.scope.visible_to(seat("tomas"))
                ]
            )
        state = w.state
        papers = sorted(
            (d.view.title, d.view.issued, d.view.arrives)
            for d in state.documents.values()
            if d.view.scope.visible_to(seat("tomas"))
        )
        seen.append((papers, holders.falling(state, seat("tomas"))))
        w.close()
        seen.append((holder(w.state, COAST), w.state.holders))
    assert seen[0] == seen[2] and seen[1] == seen[3]


# --- Invariant 3: the same filings in either order give the same captures --------------


def test_two_seats_orders_in_either_order_give_the_same_capture(tmp_path: Path) -> None:
    world = toy(tmp_path, without("sudland_levy"), capital("sudland", "sudby"))
    north = order("ilse", "norra_levy", "sudby")
    south = order("tomas", "sudland_galleys", "open_sea")
    north_isle = order("ilse", "norra_kites", ISLE, n=2)

    def run(*orders: Any) -> tuple[str, list[tuple[Any, ...]]]:
        from revisionist.core.realism.resolvers import apply_changes, movement

        g = Logged(world, "ilse", "tomas")
        for o in orders:
            g.add(apply_changes(g.state, movement.order_changes(g.state, o)))
        w = Wakes(g)
        found: list[tuple[Any, ...]] = []
        for _ in range(3):
            found += [(h.area, h.holder, h.was, h.on) for h in held(w.close())]
        return digest(w.state), found

    a = run(north, south, north_isle)
    b = run(south, north_isle, north)
    assert a == b
    assert a[1] == [(entity(COAST), entity("norra"), entity("sudland"), date(1900, 4, 30))]


# --- Rule 5: a base serves a side only while it or an ally holds its territory ----------


def isle_base(*sides: str) -> Callable[[World], None]:
    """A base on the Isle for ``sides``, and one at Norrhavn for Norra, so that naming bases
    (which switches the reach rule on) leaves Norra's levy free to cross."""

    def change(w: World) -> None:
        add_entity(
            key="isle_keep",
            kind="location",
            name="Isle Keep",
            at=[100, 250],
            within=ISLE,
            base={"sides": list(sides), "domains": ["land", "air"]},
        )(w)
        set_entity("norrhavn", base={"sides": ["norra"], "domains": ["land", "air"]})(w)

    return change


def isle_keep(state: State) -> Base:
    (base,) = [b for b in state.map.bases if b.place == entity("isle_keep")]  # type: ignore[union-attr]
    return base


def osterland(w: World) -> None:
    """A third polity at war with Norra: Sudland's ally under the plan's definition."""
    w["entities"].append({"key": "osterland", "kind": "polity", "name": "Osterland"})
    w["wars"].append({"a": "norra", "b": "osterland", "since": "1900-03-01", "source": "toy"})


def test_a_base_serves_its_side_while_that_side_holds_its_territory(tmp_path: Path) -> None:
    g = to_isle(tmp_path, without("sudland_levy"), isle_base("sudland"))
    galleys = piece(g.state, "sudland_galleys")
    levy = galleys.model_copy(update={"piece": "levy", "places": (entity("sudby"),)})
    assert bases.area_reach(g.state, levy, entity(ISLE)).tier is Tier.SUSTAINED  # type: ignore[union-attr]
    g.walk(day(1), day(10))
    assert holder(g.state, ISLE) == entity("norra")
    reach = bases.area_reach(g.state, levy, entity(ISLE))
    assert reach is not None and reach.tier is Tier.REFUSED and reach.base is None
    assert bases.within_reach(g.state, levy) == set()


def test_a_taken_base_does_not_serve_the_taker_either(tmp_path: Path) -> None:
    g = to_isle(tmp_path, without("sudland_levy"), isle_base("sudland"))
    g.walk(day(1), day(10))
    base = isle_keep(g.state)
    assert not holders.serves(g.state, base, entity("norra"))  # not among its sides
    assert not holders.serves(g.state, base, entity("sudland"))


def test_a_base_serves_an_ally_holding_it_and_not_a_neutral(tmp_path: Path) -> None:
    def sides(w: World) -> None:
        isle_base("osterland")(w)

    g = Logged(toy(tmp_path, osterland, sides), "ilse", "tomas")
    base = isle_keep(g.state)
    # Osterland and Sudland are both at war with Norra and not with each other: allies.
    assert holders.serves(g.state, base, entity("osterland"))
    peace = {
        k: v
        for k, v in g.state.wars.items()
        if k != war_id_for(entity("norra"), entity("osterland"))
    }
    neutral = g.state.model_copy(update={"wars": peace})
    assert not holders.serves(neutral, base, entity("osterland"))


def test_a_base_in_a_sea_zone_serves_as_declared(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path), "ilse", "tomas")
    base = Base(
        place=entity("gulf_roads"),
        land=None,
        sea=entity("the_gulf"),
        sides=(entity("sudland"),),
        domains=("sea",),
    )
    assert holders.serves(g.state, base, entity("sudland"))
    assert not holders.serves(g.state, base, entity("norra"))


def test_an_air_wings_range_counts_only_bases_that_serve(tmp_path: Path) -> None:
    g = to_isle(tmp_path, without("sudland_levy"), isle_base("sudland"))
    kite = piece(g.state, "norra_kites").model_copy(
        update={"side": entity("sudland"), "places": (entity(ISLE),)}
    )
    assert territory._air_range(g.state, kite, territory._kind_of(g.state, kite))  # type: ignore[arg-type]
    g.walk(day(1), day(10))
    assert territory._air_range(g.state, kite, territory._kind_of(g.state, kite)) == set()  # type: ignore[arg-type]


# --- Rule 6: gated by ``holders``; stored games unchanged -------------------------------


def test_without_holders_nothing_is_counted_or_taken(tmp_path: Path) -> None:
    g = Logged(territories_toy(tmp_path, without("sudland_levy")), "ilse", "tomas")
    g.send("ilse", "norra_levy", ISLE)
    out = g.walk(day(1), day(30))
    assert piece(g.state, "norra_levy").places == (entity(ISLE),)
    assert held(out) == []
    assert not [e for e in out if isinstance(e.payload, ev.CaptureCounted)]
    assert g.state.holders == {} and g.state.captures == {}
    assert holders.walk(g.state, day(31)) == [] and holders.close(g.state, day(31)) == []


def test_without_holders_a_base_serves_as_declared(tmp_path: Path) -> None:
    g = Logged(territories_toy(tmp_path, isle_base("sudland")), "ilse", "tomas")
    base = isle_keep(g.state)
    taken = g.state.model_copy(
        update={"holders": {entity(ISLE): holders.Holding(holder=entity("norra"), on=START)}}
    )
    assert holders.serves(taken, base, entity("sudland"))


def test_a_stored_game_gains_no_holders() -> None:
    world = cmp.load_world(Path(__file__).parent / "worlds" / "territory-toy.yaml")
    events, state = created(world)
    dumped = state.model_dump(mode="json")
    assert "holders" not in dumped and "captures" not in dumped
    assert state.map is not None and "capitals" not in state.map.model_dump(mode="json")
    assert holders.walk(state, day(5)) == []
    assert state_hash(replay(events)) == state_hash(state)


# --- The fold refuses what the walk would never land -------------------------------------


def test_the_fold_refuses_a_change_that_does_not_follow_the_holder(tmp_path: Path) -> None:
    from revisionist.core.fold import FoldError

    g = Logged(toy(tmp_path), "ilse", "tomas")
    isle, norra, sudland = entity(ISLE), entity("norra"), entity("sudland")
    for bad in (
        ev.AreaHeld(area=isle, holder=norra, was=norra, on=START),  # not its holder
        ev.AreaHeld(area=isle, holder=sudland, was=sudland, on=START),  # no change
        ev.AreaHeld(area=entity("the_gulf"), holder=norra, was=None, on=START),  # a sea zone
        ev.AreaHeld(area=isle, holder=entity("ilse"), was=sudland, on=START),  # a person
        ev.CaptureCounted(area=isle, capture=Capture(by=entity("ilse"), since=START)),
    ):
        with pytest.raises(FoldError):
            g.add([bad])
    g.add([ev.AreaHeld(area=isle, holder=norra, was=sudland, on=START)])
    assert holder(g.state, ISLE) == norra


def test_the_fold_refuses_holders_events_with_the_rule_off(tmp_path: Path) -> None:
    from revisionist.core.fold import FoldError

    g = Logged(territories_toy(tmp_path), "ilse", "tomas")
    with pytest.raises(FoldError):
        g.add(
            [
                ev.AreaHeld(
                    area=entity(ISLE), holder=entity("norra"), was=entity("sudland"), on=START
                )
            ]
        )
    with pytest.raises(FoldError):
        g.add(
            [ev.CaptureCounted(area=entity(ISLE), capture=Capture(by=entity("norra"), since=START))]
        )


def test_a_mark_is_judged_at_a_close_with_no_day_walked(tmp_path: Path) -> None:
    g = Logged(toy(tmp_path, without("sudland_levy"), capital("sudland", "sudby")), "ilse", "tomas")
    g.send("ilse", "norra_levy", "sudby")
    g.walk(day(1), day(20))
    assert g.state.captures[entity(COAST)].marked == g.state.tick
    g.state = g.state.model_copy(update={"tick": g.state.tick + 1})
    out = g.walk(day(21), day(20))  # a close on the day already walked
    assert [h.on for h in held(out)] == [day(20)]
