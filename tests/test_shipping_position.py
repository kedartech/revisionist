"""Atlantic losses read where the fleets are: an escort order cuts losses only while
a fleet of the escorting side lies in the North Atlantic, and the U-boats sink
nothing while none of their side's fleets is there."""

from datetime import date, timedelta

from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism.resolvers import movement, qid, shipping, value
from tests.test_realism_resolvers import Rig, naval, rig

NAVAL = [date(1941, 9, 3), date(1941, 9, 5)]
OCT, NOV = date(1941, 10, 1), date(1941, 11, 1)


def send(r: Rig, fleet: str, to: str) -> None:
    """Roosevelt's menu order: the fleet sails on settlement and is there by October."""
    filed = NAVAL[0] - timedelta(days=2)
    order = r.enact("roosevelt", "move_fleet", "naval_order", filed, NAVAL, force=fleet, to=to)
    r.fold_changes(movement.resolve(r.state, order))
    r.fold_changes(movement.on_day(r.state, OCT))
    assert r.state.features[FeatureId(r.ids[fleet])].places == (EntityId(r.ids[to]),)


def place(r: Rig, fleet: str, at: str) -> None:
    """Put a force at a place by hand (no menu moves the U-boat arm)."""
    f = r.state.features[FeatureId(r.ids[fleet])]
    r.fold_changes((f.model_copy(update={"places": (EntityId(r.ids[at]),)}),))


def october(r: Rig) -> int | None:
    r.fold_changes(shipping.on_day(r.state, NOV))
    return value(r.state, "uboat_losses_oct")


def escorted() -> Rig:
    r = rig()
    naval(r, "escort_convoys", "western_atlantic", day=date(1941, 9, 11))
    return r


def test_an_escort_order_cuts_nothing_once_its_sides_fleets_have_left_the_atlantic() -> None:
    plain, kept, gone = rig(), escorted(), escorted()
    send(gone, "us_atlantic_fleet", "pearl_harbor_base")
    p, k, g = october(plain), october(kept), october(gone)
    assert p is not None and k is not None and k < p
    assert g == p


def test_a_fleet_moved_within_the_atlantic_still_escorts() -> None:
    kept, moved = escorted(), escorted()
    send(moved, "us_atlantic_fleet", "reykjavik")
    assert october(moved) == october(kept)


def test_any_fleet_of_the_side_in_the_atlantic_escorts() -> None:
    kept, swapped = escorted(), escorted()
    send(swapped, "us_atlantic_fleet", "pearl_harbor_base")
    send(swapped, "us_pacific_fleet", "norfolk")
    assert october(swapped) == october(kept)


def test_the_uboats_sink_nothing_while_their_sides_fleets_are_out_of_the_atlantic() -> None:
    base, away = rig(), rig()
    place(away, "uboat_arm", "kure")
    assert (october(base) or 0) > 0
    assert october(away) == 0


def test_a_side_with_no_fleet_on_the_map_keeps_the_losses_it_had() -> None:
    plain, kept, bare = rig(), escorted(), escorted()
    bare.state = bare.state.model_copy(update={"features": {}})
    p, k = october(plain), october(kept)
    assert october(bare) == k and k != p


def test_an_escort_level_with_no_owner_names_no_side_and_keeps_its_cut() -> None:
    kept, gone = escorted(), escorted()
    send(gone, "us_atlantic_fleet", "pearl_harbor_base")
    q = gone.state.quantities[qid(gone.state, "us_atlantic_escort")]
    quantities = {**gone.state.quantities, q.quantity_id: q.model_copy(update={"owner": None})}
    gone.state = gone.state.model_copy(update={"quantities": quantities})
    assert october(gone) == october(kept)
