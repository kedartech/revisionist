"""A piece's detachment in a territory game (IFC): a movement form naming a ``strength``
splits the piece as a force's detachment splits it.

With ``territories`` on, an order to a piece that names a strength sends that much of it
on the course a move would take, as a detachment of its own, and the rest stays where it
stands. The limits are the detachments rule's, read by the piece's domain: a sea piece as
a fleet, an air piece as an air force, a land piece as an army (none). The piece keeps at
least strength 1, and a detachment standing still where its piece stands merges back.
"""

from pathlib import Path

from revisionist.core.ids import FeatureId
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.resolvers import movement
from revisionist.core.state import State
from revisionist.core.world_compile import object_id
from tests.test_adjacency_moves import (
    day,
    entity,
    fold_changes,
    order,
    piece,
    play,
    set_feature,
    walk,
)
from tests.test_territory_model import CAMPAIGN

GALLEYS = "sudland_galleys"


def detach(state: State, by: str, force: str, to: str, strength: str, n: int = 1) -> State:
    sent = order(by, force, to, n=n)
    sent = sent.model_copy(update={"params": {**sent.params, "strength": strength}})
    return fold_changes(state, movement.order_changes(state, sent))


def part(state: State, key: str, number: int = 1) -> Feature | None:
    return state.features.get(FeatureId(object_id(CAMPAIGN, "feature", f"{key}__d{number}")))


def test_a_sea_piece_sends_the_strength_named_and_keeps_the_rest(tmp_path: Path) -> None:
    state = play(tmp_path, set_feature(GALLEYS, tier=3))
    after = detach(state, "tomas", GALLEYS, "open_sea", "1")
    kept, sent = piece(after, GALLEYS), part(after, GALLEYS)
    assert sent is not None
    assert (kept.tier, kept.bound_for, kept.places) == (2, None, piece(state, GALLEYS).places)
    assert (sent.tier, sent.bound_for, sent.detached_from) == (
        1,
        entity("open_sea"),
        kept.feature_id,
    )
    walked, _ = walk(after, day(1), day(5))
    arrived = part(walked, GALLEYS)
    assert arrived is not None and arrived.places == (entity("open_sea"),)
    assert piece(walked, GALLEYS).places == piece(state, GALLEYS).places


def test_a_piece_keeps_at_least_strength_one(tmp_path: Path) -> None:
    state = play(tmp_path, set_feature(GALLEYS, tier=3))
    after = detach(state, "tomas", GALLEYS, "open_sea", "3")
    assert part(after, GALLEYS) is None
    assert piece(after, GALLEYS) == piece(state, GALLEYS)


def test_a_land_piece_sends_no_detachment(tmp_path: Path) -> None:
    state = play(tmp_path, set_feature("norra_levy", tier=3))
    after = detach(state, "ilse", "norra_levy", "isle", "1")
    assert part(after, "norra_levy") is None
    assert piece(after, "norra_levy") == piece(state, "norra_levy")


def test_a_side_holds_two_sea_detachments_at_once(tmp_path: Path) -> None:
    state = play(tmp_path, set_feature(GALLEYS, tier=3))
    state = detach(state, "tomas", GALLEYS, "open_sea", "1", n=1)
    state = detach(state, "tomas", GALLEYS, "open_sea", "1", n=2)
    assert part(state, GALLEYS, 2) is not None
    assert piece(state, GALLEYS).tier == 1
    third = detach(state, "tomas", GALLEYS, "open_sea", "1", n=3)
    assert part(third, GALLEYS, 3) is None


def test_a_detachment_back_where_its_piece_stands_merges(tmp_path: Path) -> None:
    state = play(tmp_path, set_feature(GALLEYS, tier=3))
    state = detach(state, "tomas", GALLEYS, "open_sea", "1")
    state, _ = walk(state, day(1), day(5))
    back = order("tomas", f"{GALLEYS}__d1", "gulf_roads", on=day(5), n=2)
    state = fold_changes(state, movement.order_changes(state, back))
    state, _ = walk(state, day(6), day(12))
    state = fold_changes(state, movement.day_changes(state, day(12)))
    sent = part(state, GALLEYS)
    assert sent is not None and sent.rejoined_on == day(12)
    assert piece(state, GALLEYS).tier == 3
