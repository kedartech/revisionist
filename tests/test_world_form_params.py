"""Autumn 1941's forms carry the parameters the production and shipping rules read: each
production form names a force its leader commands (the forces in the card's authority, or,
on a card whose authority holds none, its nation's), Hitler's names the U-boat figure it
adds to, Churchill's convoy orders name one of Britain's convoy routes, Hitler's U-boat
directive can order attacks on American shipping, and Japan has a pool of shipping for
lifting its armies."""

from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, QuantityId
from revisionist.core.realism.card import ParamKind, ParamSpec
from revisionist.core.realism.geography import FORCES, FeatureKind
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")

PRODUCTION = {
    "hitler": "production_priority",
    "stalin": "state_defence_order",
    "mussolini": "production_priority",
    "chiang": "arsenal_output",
    "churchill": "production_priority",
}


def world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def param(w: WorldFile, person: str, lever: str, name: str) -> ParamSpec:
    card = next(c for c in w.cards if c.person == person)
    form = next(lv for lv in card.levers if lv.name == lever)
    found = next((p for p in form.params if p.name == name), None)
    assert found is not None, f"{person}'s {lever} has no {name} parameter"
    assert found.kind is ParamKind.ENUM
    assert len(found.choice_labels) == len(found.choices)
    return found


def nation(w: WorldFile, person: str) -> str | None:
    return next(e.parent for e in w.entities if e.key == person)


def test_each_production_form_offers_the_forces_its_leader_commands_and_no_other() -> None:
    """Only forces the seat already holds on its card, so the form names no force the
    seat's paper has not shown it (the fog rule of test_realism_map)."""
    w = world()
    for person, lever in PRODUCTION.items():
        card = next(c for c in w.cards if c.person == person)
        own = {f.key for f in w.features if f.kind in FORCES and f.side == nation(w, person)}
        held = {k for d in card.authority for k in d.forces}
        assert own, f"{person}'s nation fields no force"
        assert held <= own, person
        assert set(param(w, person, lever, "force").choices) == (held or own), person


def test_hitlers_production_form_adds_to_the_german_u_boat_figure() -> None:
    w = world()
    quantities = {q.key: q for q in w.quantities}
    adds_to = param(w, "hitler", "production_priority", "adds_to").choices
    assert adds_to == ("uboats_operational",)
    assert all(quantities[k].owner == "germany" for k in adds_to)


def test_churchills_convoy_orders_name_one_of_britains_convoy_routes() -> None:
    w = world()
    routes = {f.key for f in w.features if f.kind is FeatureKind.ROUTE and f.side == "uk"}
    assert set(param(w, "churchill", "convoy_orders", "route").choices) == routes


def test_hitlers_u_boat_directive_can_order_attacks_on_american_shipping() -> None:
    posture = param(world(), "hitler", "uboat_directive", "posture")
    assert "attack_us_shipping" in posture.choices


def test_japan_has_a_shipping_pool_for_lifting_its_armies() -> None:
    pool = next(q for q in world().quantities if q.key == "japan_sealift_grt")
    assert (pool.owner, pool.value, pool.unit, pool.gap) == ("japan", 200_000, "GRT", True)


def test_the_world_compiles_with_the_pool_owned_by_japan() -> None:
    w = world()
    ids = resolve_keys(w, CAMPAIGN)
    state = replay(compile_world(w, CAMPAIGN, cmp.versions()))
    pool = state.quantities[QuantityId(ids["japan_sealift_grt"])]
    assert (pool.owner, pool.value) == (EntityId(ids["japan"]), 200_000)
