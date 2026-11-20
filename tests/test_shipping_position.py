"""Atlantic losses read where the fleets are: an escort order cuts losses only while
a fleet of the escorting side lies in the North Atlantic, and the U-boats sink
nothing while none of their side's fleets is there.

In a territory game (the toy world, ``tests/worlds/territory-toy.yaml``) the shipping
forms read the board instead (SHP). Norra's two routes leave Norrhavn: the Gulf Run
crosses the Gulf; the Isle Run crosses the Gulf and the Open Sea to a cove on the Isle,
which Sudland holds. Norra's shipping is the lift pool the world names for Norra. The
Sudland Galleys (strength 2) stand in the Gulf Roads, so each month they sink Norra's
shipping on both routes; a tenth of what they sink comes off the pool.
"""

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId, OrderId, derived_id
from revisionist.core.realism import territory
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import apply_changes, movement, qid, shipping, value
from revisionist.core.realism.resolvers import production as prd
from revisionist.core.realism.resolvers import votes as vt
from revisionist.core.world_compile import object_id
from tests.test_adjacency_moves import START, Logged, entity, piece, seat, set_feature
from tests.test_realism_resolvers import POINTS, Rig, naval, rig
from tests.test_supply import hub, no_port
from tests.test_supply import toy as supply_toy
from tests.test_territory_model import CAMPAIGN

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
    r = rig(POINTS)
    naval(r, "escort_convoys", "western_atlantic", day=date(1941, 9, 11))
    return r


def test_an_escort_order_cuts_nothing_once_its_sides_fleets_have_left_the_atlantic() -> None:
    plain, kept, gone = rig(POINTS), escorted(), escorted()
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
    base, away = rig(POINTS), rig(POINTS)
    place(away, "uboat_arm", "kure")
    assert (october(base) or 0) > 0
    assert october(away) == 0


def test_a_side_with_no_fleet_on_the_map_keeps_the_losses_it_had() -> None:
    plain, kept, bare = rig(POINTS), escorted(), escorted()
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


# ================================================================ the territory game (SHP)

World = dict[str, Any]
Change = Callable[[World], None]
NORRA, SUDLAND = "norra", "sudland"
GULF_RUN, ISLE_RUN = "gulf_run", "isle_run"
POOL, LEVY, GALLEYS = "norra_shipping", "norra_levy", "sudland_galleys"
GULF, OPEN_SEA, WATERS = "the_gulf", "open_sea", "waters"
APRIL, MAY = date(1900, 4, 30), date(1900, 5, 31)


def _enum(name: str, choices: list[str]) -> dict[str, Any]:
    return {"name": name, "kind": "enum", "choices": choices}


def lanes(w: World) -> None:
    """Norra's two routes, a cove on the Isle that opens on the Open Sea, and the
    shipping forms on both leaders' cards."""
    w["entities"].append(
        {
            "key": "isle_cove",
            "kind": "location",
            "name": "Isle Cove",
            "at": [100, 250],
            "within": "isle",
            "port_on": OPEN_SEA,
        }
    )
    w["entities"].append(
        {
            "key": "open_roads",
            "kind": "location",
            "name": "Open Roads",
            "at": [180, 215],
            "within": OPEN_SEA,
        }
    )
    for key, name, places in (
        (GULF_RUN, "The Gulf Run", ["norrhavn", "gulf_roads"]),
        (ISLE_RUN, "The Isle Run", ["norrhavn", "gulf_roads", "isle_cove"]),
    ):
        w["features"].append(
            {"key": key, "kind": "route", "name": name, "side": NORRA, "places": places}
        )
        w["features"][-1]["source"] = "toy"
    w["pipelines"] = [
        {
            "key": "admiralty",
            "name": "The admiralty",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        }
    ]
    forms = {
        "convoys": [_enum("route", [GULF_RUN, ISLE_RUN])],
        "supply_run": [_enum("route", [GULF_RUN, ISLE_RUN]), _enum("force", [LEVY])],
        "requisition": [_enum("tonnage_class", ["army", "civil"])],
        "escort": [
            _enum("order", sorted(shipping.ESCORT_LEVEL)),
            _enum("zone", [GULF, OPEN_SEA, WATERS]),
        ],
        "raid": [_enum("theatre", [GULF, OPEN_SEA]), _enum("target", [NORRA])],
        "send_bill": [_enum("bill", ["draft_extension", "arm_merchant_ships"])],
    }
    for card in w["cards"]:
        card["pipelines"] = ["admiralty"]
        card["levers"] = [
            {
                "name": name,
                "pipeline": "admiralty",
                "resolver": "votes" if name == "send_bill" else "shipping",
                "params": params,
            }
            for name, params in forms.items()
        ]


def flag(key: str, owner: str = NORRA) -> Change:
    def change(w: World) -> None:
        w["quantities"].append(
            {"key": key, "owner": owner, "name": key, "unit": "flag", "computed": True}
        )

    return change


def hulls(w: World) -> None:
    """Norra lifts from a pool of another name; its shipping figure stays."""
    w["quantities"].append(
        {"key": "norra_hulls", "owner": NORRA, "name": "Hulls", "value": 50000, "unit": "tons"}
    )
    w["quantities"][-1]["source"] = "toy"
    for e in w["entities"]:
        if e["key"] == NORRA:
            e["lift_pool"] = "norra_hulls"


STANDING = 61
"""The record's standing in the autumn of 1941: at it a draft bill sometimes carries."""


def popular(w: World) -> None:
    """The leader's standing the votes rule reads, high enough to carry a close bill."""
    w["quantities"].append(
        {"key": "gallup_fdr_about_right", "name": "Standing", "value": STANDING, "unit": "percent"}
    )
    w["quantities"][-1]["source"] = "toy"


def no_war(w: World) -> None:
    w["wars"] = []


def isle_held_by_norra(w: World) -> None:
    for t in w["territories"]:
        if t["key"] == "isle":
            t["holder"] = NORRA


def sea_game(tmp: Path, *changes: Change) -> Logged:
    tmp.mkdir(parents=True, exist_ok=True)
    return Logged(supply_toy(tmp, lanes, set_feature(GALLEYS, tier=2), *changes), "ilse", "tomas")


def enact(g: Logged, by: str, lever: str, n: int = 1, on: date = START, **params: str) -> Order:
    """A shipping form enacted on ``on``, its changes folded."""
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "shp-order", by, lever, n)),
        issuer=seat(by),
        lever=lever,
        pipeline=next(
            p.pipeline_id for p in g.state.pipelines.values() if p.name == "The admiralty"
        ),
        params=dict(params),
        filed=on,
    )
    g.add(
        [
            ev.OrderDrafted(order=order),
            ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
        ]
    )
    return g.state.orders[order.order_id]


def resolved(g: Logged, order: Order) -> None:
    g.add(apply_changes(g.state, shipping.resolve(g.state, order)))


def route(key: str) -> FeatureId:
    return FeatureId(object_id(CAMPAIGN, "feature", key))


def feature(g: Logged, key: str) -> Feature:
    return g.state.features[route(key)]


def lost(g: Logged, last: date = APRIL) -> dict[FeatureId, int]:
    return shipping.losses(g.state, last)


def sunk(g: Logged, first: date) -> int:
    """What the 1st of the month takes off Norra's pool."""
    before = value(g.state, POOL) or 0
    g.add(apply_changes(g.state, shipping.on_day(g.state, first)))
    return before - (value(g.state, POOL) or 0)


def test_the_sea_zones_a_route_crosses_come_from_the_places_it_joins(tmp_path: Path) -> None:
    g = sea_game(tmp_path)
    gulf, open_sea = entity(GULF), entity(OPEN_SEA)
    assert shipping.zones(g.state, feature(g, ISLE_RUN)) == (gulf, open_sea)
    assert shipping.zones(g.state, feature(g, GULF_RUN)) == (gulf,)


def test_raiders_sink_shipping_on_the_routes_that_cross_their_waters(tmp_path: Path) -> None:
    g = sea_game(tmp_path)
    found = lost(g)
    assert found[route(GULF_RUN)] > 0 and found[route(ISLE_RUN)] > 0
    out = sea_game(tmp_path / "out", set_feature(GALLEYS, places=["open_roads"]))
    found = lost(out)
    assert found.get(route(GULF_RUN), 0) == 0 and found[route(ISLE_RUN)] > 0


def test_the_month_s_losses_come_off_the_pool_the_world_names(tmp_path: Path) -> None:
    g = sea_game(tmp_path)
    total = sum(lost(g).values())
    assert sunk(g, APRIL + timedelta(days=1)) == total * shipping.LOSS_SHARE_PCT // 100 > 0
    other = sea_game(tmp_path / "other", hulls)
    before = value(other.state, "norra_hulls") or 0
    other.add(apply_changes(other.state, shipping.on_day(other.state, date(1900, 5, 1))))
    assert value(other.state, POOL) == 100_000
    assert (value(other.state, "norra_hulls") or 0) < before


def test_a_convoy_priority_raises_the_escort_level_on_the_named_route(tmp_path: Path) -> None:
    plain, g = sea_game(tmp_path), sea_game(tmp_path / "g")
    enact(g, "ilse", "convoys", route=ISLE_RUN)
    isle, gulf = feature(g, ISLE_RUN), feature(g, GULF_RUN)
    assert shipping.escort_level(g.state, isle, APRIL) == shipping.ESCORT_RAISE == 1
    assert shipping.escort_level(g.state, gulf, APRIL) == 0
    p, e = lost(plain), lost(g)
    assert e[route(ISLE_RUN)] < p[route(ISLE_RUN)]
    assert e[route(GULF_RUN)] == p[route(GULF_RUN)]


def test_a_requisition_adds_to_the_lift_pool_the_world_names(tmp_path: Path) -> None:
    g = sea_game(tmp_path)
    resolved(g, enact(g, "ilse", "requisition", tonnage_class="army"))
    assert value(g.state, POOL) == 100_000 + shipping.REQUISITION_GRT
    other = sea_game(tmp_path / "other", hulls)
    resolved(other, enact(other, "ilse", "requisition", tonnage_class="civil"))
    assert value(other.state, POOL) == 100_000
    assert value(other.state, "norra_hulls") == 50_000 + shipping.REQUISITION_GRT
    poolless = sea_game(tmp_path / "sudland")
    assert shipping.resolve(poolless.state, enact(poolless, "tomas", "requisition")) == ()


def test_a_supply_convoy_supplies_the_pieces_it_names(tmp_path: Path) -> None:
    from revisionist.core.realism import supply

    g = sea_game(tmp_path, hub("norra_hills", False), no_port)
    levy = piece(g.state, LEVY)
    found = supply.status(g.state, levy)
    assert found is not None and not found.supplied
    assert shipping.supplied(g.state, levy, START) is False
    enact(g, "ilse", "supply_run", route=GULF_RUN, force=LEVY)
    assert shipping.supplied(g.state, levy, START) is True
    last = START + timedelta(days=shipping.CONVOY_DAYS)
    assert shipping.supplied(g.state, levy, last - timedelta(days=1)) is True
    assert shipping.supplied(g.state, levy, last) is False
    assert prd._force(g.state, entity(NORRA), LEVY)[1] is None


def test_without_a_convoy_production_still_refuses_a_piece_out_of_supply(tmp_path: Path) -> None:
    g = sea_game(tmp_path, hub("norra_hills", False), no_port)
    assert prd._force(g.state, entity(NORRA), LEVY)[1] == "The Norra Levy is out of supply"


def test_a_convoy_is_cut_only_while_an_enemy_holds_a_territory_on_its_route(
    tmp_path: Path,
) -> None:
    g = sea_game(tmp_path)
    held = sea_game(tmp_path / "held", isle_held_by_norra)
    isle = [enact(g, "ilse", "supply_run", n, route=ISLE_RUN, force=LEVY) for n in range(20)]
    gulf = [enact(g, "ilse", "supply_run", 100 + n, route=GULF_RUN, force=LEVY) for n in range(20)]
    calm = [enact(held, "ilse", "supply_run", n, route=ISLE_RUN, force=LEVY) for n in range(20)]
    cuts = [shipping.cut(g.state, o, START) for o in isle]
    assert any(cuts) and not all(cuts)
    assert not any(shipping.cut(g.state, o, START) for o in gulf)
    assert not any(shipping.cut(held.state, o, START) for o in calm)


def test_a_cut_convoy_supplies_nothing(tmp_path: Path) -> None:
    lone = (hub("norra_hills", False), no_port)
    probe = sea_game(tmp_path / "probe", *lone)
    convoys = [enact(probe, "ilse", "supply_run", n, route=ISLE_RUN, force=LEVY) for n in range(20)]
    n = next(n for n, o in enumerate(convoys) if shipping.cut(probe.state, o, START))
    g = sea_game(tmp_path / "g", *lone)
    enact(g, "ilse", "supply_run", n, route=ISLE_RUN, force=LEVY)
    assert shipping.supplied(g.state, piece(g.state, LEVY), START) is False


def test_an_arming_law_cuts_losses_from_the_month_after_it_passes(tmp_path: Path) -> None:
    plain = sea_game(tmp_path)
    g = sea_game(tmp_path / "armed", flag("arm_merchant_ships_passed"))
    q = g.state.quantities[qid(g.state, "arm_merchant_ships_passed")]
    g.add([ev.QuantitySet(quantity=q.model_copy(update={"value": 1, "as_of": date(1900, 4, 10)}))])
    assert lost(g, APRIL) == lost(plain, APRIL)
    armed, unarmed = lost(g, MAY), lost(plain, MAY)
    for key, n in unarmed.items():
        assert abs(armed[key] - n * (100 - shipping.ARMING_CUT_PCT) / 100) <= 1


def test_a_failed_arming_law_cuts_nothing(tmp_path: Path) -> None:
    plain = sea_game(tmp_path)
    g = sea_game(tmp_path / "failed", flag("arm_merchant_ships_passed"))
    q = g.state.quantities[qid(g.state, "arm_merchant_ships_passed")]
    g.add([ev.QuantitySet(quantity=q.model_copy(update={"value": 0, "as_of": date(1900, 4, 10)}))])
    assert lost(g, MAY) == lost(plain, MAY)


def _draft(g: Logged, n: int) -> tuple[bool, list[ev.EconomySet]]:
    from revisionist.core.realism import resolvers as rs

    order = enact(g, "ilse", "send_bill", n, bill="draft_extension", urgency="urgent")
    changes = rs.ON_ORDER["votes"](g.state, order)
    flag = qid(g.state, "draft_extension_passed")
    passed = [c for c in changes if isinstance(c, QuantityChange) and c.quantity_id == flag]
    return bool(passed and passed[0].value), [c for c in changes if isinstance(c, ev.EconomySet)]


def test_a_draft_law_adds_manpower_points_when_it_passes(tmp_path: Path) -> None:
    g = sea_game(tmp_path, flag("draft_extension_passed"), popular)
    g.add([ev.EconomySet(polity=entity(NORRA), pools=Pools(output=5, manpower=1), on=START)])
    seen = set()
    for n in range(30):
        passed, paid = _draft(g, n)
        seen.add(passed)
        assert len(paid) == int(passed)
        if passed:
            assert paid[0].polity == entity(NORRA)
            assert paid[0].pools == Pools(output=5, manpower=1 + vt.DRAFT_MANPOWER)
    assert seen == {True, False}
    assert vt.DRAFT_MANPOWER == 3


def test_a_draft_law_adds_nothing_without_its_flag_or_the_economy(tmp_path: Path) -> None:
    bare = sea_game(tmp_path, popular)
    off = sea_game(
        tmp_path / "off",
        flag("draft_extension_passed"),
        popular,
        lambda w: w.update(rules=["territories"]),
    )
    for n in range(30):
        assert _draft(bare, n)[1] == []
        assert _draft(off, n)[1] == []


def test_raiders_press_harder_in_the_waters_their_directive_names(tmp_path: Path) -> None:
    plain, there, elsewhere = (sea_game(tmp_path / k) for k in ("p", "t", "e"))
    enact(there, "tomas", "raid", theatre=GULF)
    enact(elsewhere, "tomas", "raid", theatre=OPEN_SEA)
    p, t, e = lost(plain), lost(there), lost(elsewhere)
    assert t[route(GULF_RUN)] > p[route(GULF_RUN)]
    assert e == p


def test_raiders_sink_a_named_nation_s_shipping_they_are_not_at_war_with(tmp_path: Path) -> None:
    peace, named = sea_game(tmp_path / "p", no_war), sea_game(tmp_path / "n", no_war)
    assert sum(lost(peace).values()) == 0
    enact(named, "tomas", "raid", target=NORRA)
    assert lost(named)[route(GULF_RUN)] > 0


def test_the_escort_order_sets_the_level_on_routes_crossing_its_waters(tmp_path: Path) -> None:
    for order, level in shipping.ESCORT_LEVEL.items():
        for zone, gulf_level, isle_level in (
            (GULF, level, level),
            (OPEN_SEA, 0, level),
            (WATERS, level, level),
        ):
            g = sea_game(tmp_path / f"{order}-{zone}")
            enact(g, "ilse", "escort", order=order, zone=zone)
            assert shipping.escort_level(g.state, feature(g, GULF_RUN), APRIL) == gulf_level
            assert shipping.escort_level(g.state, feature(g, ISLE_RUN), APRIL) == isle_level
    plain, shot = sea_game(tmp_path / "plain"), sea_game(tmp_path / "shot")
    enact(shot, "ilse", "escort", order="shoot_on_sight", zone=GULF)
    assert lost(shot)[route(GULF_RUN)] < lost(plain)[route(GULF_RUN)]


def test_the_territory_rules_leave_a_world_without_them_alone(tmp_path: Path) -> None:
    g = sea_game(tmp_path, lambda w: w.update(rules=[]))
    assert shipping.losses(g.state, APRIL) == {}
    assert shipping.resolve(g.state, enact(g, "ilse", "requisition", tonnage_class="army")) == ()
    assert territory.on(g.state) is False
