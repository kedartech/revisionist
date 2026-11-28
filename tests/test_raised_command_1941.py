"""Who commands a piece that enters after the world compiles, in autumn 1941 (raising on).

A raised piece is handed to every card domain that commands another piece of its nation and
its domain. A detachment is a new piece too, but it stays under its parent's commander
through ``detached_from``: the Pacific Fleet's detachment never enters the Atlantic Fleet
card's forces, nor any other card's.
"""

from revisionist.core.ids import EntityId, FeatureId, OrderId, derived_id
from revisionist.core.realism import kinds
from revisionist.core.realism.geography import Feature, FeatureKind
from revisionist.core.realism.resolvers import production
from revisionist.core.state import Rule
from tests.test_detach_split import DAY, detach, feature, fid
from tests.test_realism_resolvers import CAMPAIGN, Rig, rig


def forces(r: Rig, person: str) -> dict[str, tuple[FeatureId, ...]]:
    card = r.state.cards[EntityId(r.ids[person])]
    return {d.name: d.forces for d in card.authority}


def holders(r: Rig, piece: FeatureId) -> set[tuple[str, str]]:
    return {
        (r.state.entities[c.person].name, d.name)
        for c in r.state.cards.values()
        for d in c.authority
        if piece in d.forces
    }


def test_1941_has_raising_on() -> None:
    assert Rule.RAISING in rig().state.rules


def test_a_pacific_fleet_detachment_enters_no_card_s_forces() -> None:
    r = rig()
    before = forces(r, "king")["atlantic_fleet"]
    _, part = detach(r, "us_pacific_fleet", "norfolk", 1)
    assert part.detached_from == fid(r, "us_pacific_fleet")
    assert part.feature_id in r.state.features
    assert forces(r, "king")["atlantic_fleet"] == before
    assert holders(r, part.feature_id) == set()


def test_a_raised_fleet_reaches_every_domain_that_commands_a_fleet_of_its_nation() -> None:
    r = rig()
    fleet = feature(r, "us_atlantic_fleet")
    raised = Feature(
        feature_id=production.raised_id(r.state, OrderId(derived_id(CAMPAIGN, "order", 99))),
        kind=FeatureKind.PIECE,
        name="Battle fleet 1",
        side=fleet.side,
        tier=production.RAISED_TIER,
        places=fleet.places,
        as_of=DAY,
        piece=fleet.piece,
    )
    sea = kinds.domain(r.state, fleet)
    expected = {
        (r.state.entities[c.person].name, d.name)
        for c in r.state.cards.values()
        for d in c.authority
        if any(
            (o := r.state.features.get(f)) is not None
            and o.side == fleet.side
            and kinds.domain(r.state, o) is sea
            for f in d.forces
        )
    }
    r.fold_changes((raised,))
    assert ("Ernest J. King", "atlantic_fleet") in expected
    assert holders(r, raised.feature_id) == expected
    assert forces(r, "king")["atlantic_fleet"][-1] == raised.feature_id
