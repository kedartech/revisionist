"""Churchill's army form (sealift, unit SL3; plan decision 10).

Churchill carries "Move an army" (``move_army``) for Home Forces, through the Chiefs of
Staff directive his other forms use (Pound decides, Ismay passes it on), with the
destination open as the place picker makes it. An authority domain gives him Home Forces,
carried out by Ismay. No other card offers Home Forces on a form or holds it in a domain.
"""

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId, SeatId, derived_id
from revisionist.core.realism.card import SeatCard
from revisionist.core.realism.effect import EffectKind
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.resolvers import value
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.build import LEVERS_MAX, LEVERS_MIN
from revisionist.engine.realism_tick import draft_order, file_order, run_realism_tick
from revisionist.engine.store import MemoryStore, load_state
from tests.test_detach_split import two_seats
from tests.test_realism_resolvers import Rig
from tests.test_realism_tick import CAMPAIGN

POOL = "uk_sealift_grt"


def card(r: Rig, person: str) -> SeatCard:
    return r.state.cards[EntityId(r.ids[person])]


def test_churchill_moves_home_forces_on_a_chiefs_of_staff_directive() -> None:
    r = two_seats()
    levers = {x.name: x for x in card(r, "churchill").levers}
    form = levers["move_army"]
    assert form.resolver == "movement" and form.pipeline == r.ids["cos_directive"]
    assert form.pipeline == levers["move_fleet"].pipeline
    assert form.label == "Move an army"
    params = {p.name: p for p in form.params}
    assert list(params) == ["force", "to"]
    assert list(params["force"].choices) == ["home_forces"]
    assert list(params["force"].choice_labels) == ["Home Forces"]
    assert "london" in params["to"].choices and "reykjavik" in params["to"].choices


def test_churchill_holds_home_forces_in_a_domain_carried_out_by_ismay() -> None:
    r = two_seats()
    home = FeatureId(r.ids["home_forces"])
    (domain,) = [d for d in card(r, "churchill").authority if home in d.forces]
    assert domain.forces == (home,)
    assert domain.executor == EntityId(r.ids["ismay"])
    assert EffectKind.MOVE_FORCE in domain.effects


def test_churchills_card_stays_inside_the_bounds_of_a_card() -> None:
    r = two_seats()
    levers = card(r, "churchill").levers
    assert len(levers) == 6 and LEVERS_MIN <= len(levers) <= LEVERS_MAX
    assert len({x.name for x in levers}) == len(levers)


def test_no_other_card_names_home_forces() -> None:
    r = two_seats()
    home = FeatureId(r.ids["home_forces"])
    on_forms = {
        r.state.entities[c.person].name
        for c in r.state.cards.values()
        for x in c.levers
        for p in x.params
        if p.name == "force" and "home_forces" in p.choices
    }
    in_domains = {
        r.state.entities[c.person].name
        for c in r.state.cards.values()
        for d in c.authority
        if home in d.forces
    }
    assert on_forms == in_domains == {"Winston Churchill"}


@pytest.mark.parametrize("lever", ["move_fleet", "detach_fleet"])
def test_roosevelt_cannot_name_home_forces(lever: str) -> None:
    r = two_seats()
    given = {"force": "home_forces", "to": "reykjavik"}
    if lever == "detach_fleet":
        given["strength"] = "1"
    with pytest.raises(ValueError, match="force"):
        draft_order(r.state, r.seats["roosevelt"], lever, given)


def test_churchill_files_home_forces_to_reykjavik_and_the_order_runs_its_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The order id seeds each step's friction: a random id stalled Pound's step in ~1 run in 10.
    monkeypatch.setattr(realism_tick, "new_id", lambda: "01ARZ3NDEKTSV4RRFFQ69G5FAV")
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path("autumn-1941"))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    ids = resolve_keys(decl, CAMPAIGN)
    pm = SeatId(derived_id(CAMPAIGN, "seat", ids["churchill"]))
    session_zero.claim(store, CAMPAIGN, pm, "Winston Churchill")
    realism_tick.seat_player(store, CAMPAIGN, EntityId(ids["roosevelt"]))

    order = file_order(
        store, CAMPAIGN, pm, "move_army", {"force": "home_forces", "to": "reykjavik"}
    )
    assert order.pipeline == ids["cos_directive"]
    assert order.params == {"force": "home_forces", "to": "reykjavik"}
    for _ in range(30):
        run_realism_tick(store, CAMPAIGN)
        if load_state(store, CAMPAIGN).orders[order.order_id].status is OrderStatus.ENACTED:
            break
    state = load_state(store, CAMPAIGN)
    assert state.orders[order.order_id].status is OrderStatus.ENACTED, "the order never enacted"

    steps = [
        e.payload.outcome.person
        for e in store.read(CAMPAIGN)
        if isinstance(e.payload, ev.OrderStepTaken) and e.payload.order_id == order.order_id
    ]
    assert steps == [EntityId(ids["pound"]), EntityId(ids["ismay"])]
    home = state.features[FeatureId(ids["home_forces"])]
    assert home.bound_for == EntityId(ids["reykjavik"])
    assert home.places == (EntityId(ids["london"]),)
    assert value(state, POOL) == 100_000
