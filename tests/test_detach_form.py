"""The split form and filing a detachment's moves (reach R4, unit D4; plan decisions 2 and 8).

Roosevelt and Churchill each carry "Detach part of a fleet" (``detach_fleet``): the fleets
of their own move form, a place, and a strength from 1 to 4. Once a detachment is in play,
a movement form's ``force`` takes it as well as the form's own choices: only a live
detachment of one of those choices, and never on the split form, since a detachment is
not split again.
"""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.realism.card import ParamKind
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.resolvers import movement
from revisionist.engine.realism_tick import draft_order
from tests.test_detach_split import DAY, arrive, detach, feature, fid, two_seats
from tests.test_realism_resolvers import Rig

FORMS = {
    "roosevelt": ("naval_order", ["us_atlantic_fleet", "us_pacific_fleet"]),
    "churchill": ("cos_directive", ["home_fleet"]),
}


def draft(r: Rig, seat: str, lever: str, **given: str) -> Order:
    return draft_order(r.state, r.seats[seat], lever, given)


def enact(r: Rig, drafted: Order, settled: date) -> Order:
    """The drafted order filed, through its steps and enacted on ``settled``."""
    r.add(ev.OrderDrafted(order=drafted))
    steps = len(r.state.pipelines[drafted.pipeline].steps)
    r.pass_steps(drafted, [settled - timedelta(days=steps - n - 1) for n in range(steps)])
    return r.settle(drafted)


def live_detachment(r: Rig) -> None:
    """``us_atlantic_fleet__d1`` (strength 2) standing at Argentia."""
    detach(r, "us_atlantic_fleet", "argentia", 2)
    arrive(r, "us_atlantic_fleet__d1")


# --- the world file -----------------------------------------------------------------------


@pytest.mark.parametrize("person", sorted(FORMS))
def test_each_fleet_seat_has_a_split_form_over_its_own_fleets(person: str) -> None:
    r = two_seats()
    card = r.state.cards[r.state.seats[r.seats[person]].embodies]
    levers = {x.name: x for x in card.levers}
    split, moved = levers["detach_fleet"], levers["move_fleet"]
    pipeline, fleets = FORMS[person]
    assert split.resolver == "movement" and split.pipeline == r.ids[pipeline]
    assert split.pipeline == moved.pipeline
    assert split.label == "Detach part of a fleet"
    params = {p.name: p for p in split.params}
    assert list(params) == ["force", "to", "strength"]
    assert list(params["force"].choices) == fleets == list(moved.params[0].choices)
    assert params["force"].choice_labels == moved.params[0].choice_labels
    assert params["to"].choices == moved.params[1].choices
    strength = params["strength"]
    assert (strength.kind, strength.lo, strength.hi) == (ParamKind.INT, 1, 4)


def test_no_other_card_carries_the_split_form() -> None:
    r = two_seats()
    holders = {
        r.state.entities[c.person].name
        for c in r.state.cards.values()
        if any(x.name == "detach_fleet" for x in c.levers)
    }
    assert holders == {"Franklin D. Roosevelt", "Winston Churchill"}


# --- filing the split ---------------------------------------------------------------------


def test_roosevelt_files_a_detachment_of_strength_2_to_argentia() -> None:
    r = two_seats()
    order = draft(
        r, "roosevelt", "detach_fleet", force="us_atlantic_fleet", to="argentia", strength="2"
    )
    assert order.lever == "detach_fleet" and order.pipeline == r.ids["naval_order"]
    assert order.params == {"force": "us_atlantic_fleet", "to": "argentia", "strength": 2}
    parent, part = movement.resolve(r.state, enact(r, order, DAY))
    assert (parent.tier, part.tier) == (2, 2)
    assert part.feature_id == fid(r, "us_atlantic_fleet__d1")


def test_churchill_files_a_detachment_of_the_home_fleet() -> None:
    r = two_seats()
    order = draft(r, "churchill", "detach_fleet", force="home_fleet", to="reykjavik", strength="1")
    assert order.params == {"force": "home_fleet", "to": "reykjavik", "strength": 1}


def test_a_strength_outside_1_to_4_or_not_a_number_is_refused() -> None:
    r = two_seats()
    for bad in ("0", "5", "two"):
        with pytest.raises(ValueError, match="strength"):
            draft(
                r,
                "roosevelt",
                "detach_fleet",
                force="us_atlantic_fleet",
                to="argentia",
                strength=bad,
            )


def test_a_split_leaving_the_fleet_below_strength_1_is_refused_in_words() -> None:
    r = two_seats()
    with pytest.raises(ValueError, match="at most 3 of it can be detached"):
        draft(
            r, "roosevelt", "detach_fleet", force="us_atlantic_fleet", to="argentia", strength="4"
        )


def test_roosevelt_cannot_split_the_home_fleet() -> None:
    r = two_seats()
    with pytest.raises(ValueError, match="force"):
        draft(r, "roosevelt", "detach_fleet", force="home_fleet", to="reykjavik", strength="1")


def test_a_detachment_is_not_offered_to_the_split_form() -> None:
    r = two_seats()
    live_detachment(r)
    with pytest.raises(ValueError, match="force"):
        draft(
            r,
            "roosevelt",
            "detach_fleet",
            force="us_atlantic_fleet__d1",
            to="norfolk",
            strength="1",
        )


# --- moving a detachment ------------------------------------------------------------------


def test_once_live_a_detachment_is_drafted_on_the_move_form_and_moves() -> None:
    r = two_seats()
    live_detachment(r)
    order = draft(r, "roosevelt", "move_fleet", force="us_atlantic_fleet__d1", to="reykjavik")
    assert order.params == {"force": "us_atlantic_fleet__d1", "to": "reykjavik"}
    (sent,) = movement.resolve(r.state, enact(r, order, DAY + timedelta(days=20)))
    assert sent.feature_id == fid(r, "us_atlantic_fleet__d1")
    assert sent.bound_for == r.ids["reykjavik"]


def test_a_detachment_not_yet_made_is_refused() -> None:
    r = two_seats()
    with pytest.raises(ValueError, match="force"):
        draft(r, "roosevelt", "move_fleet", force="us_atlantic_fleet__d1", to="reykjavik")


def test_an_unknown_force_key_is_refused() -> None:
    r = two_seats()
    live_detachment(r)
    for bad in ("us_atlantic_fleet__d2", "atlantic", ""):
        with pytest.raises(ValueError, match="force"):
            draft(r, "roosevelt", "move_fleet", force=bad, to="reykjavik")


def test_another_sides_detachment_is_refused() -> None:
    r = two_seats()
    detach(r, "home_fleet", "reykjavik", 1, seat="churchill")
    assert feature(r, "home_fleet__d1").detached_from == fid(r, "home_fleet")
    with pytest.raises(ValueError, match="force"):
        draft(r, "roosevelt", "move_fleet", force="home_fleet__d1", to="scapa_flow")
    order = draft(r, "churchill", "move_fleet", force="home_fleet__d1", to="scapa_flow")
    assert order.params["force"] == "home_fleet__d1"


def test_a_rejoined_detachment_is_refused() -> None:
    r = two_seats()
    live_detachment(r)
    back = draft(r, "roosevelt", "move_fleet", force="us_atlantic_fleet__d1", to="norfolk")
    r.fold_changes(movement.resolve(r.state, enact(r, back, DAY + timedelta(days=20))))
    arrive(r, "us_atlantic_fleet__d1")
    assert feature(r, "us_atlantic_fleet__d1").rejoined_on is not None
    with pytest.raises(ValueError, match="force"):
        draft(r, "roosevelt", "move_fleet", force="us_atlantic_fleet__d1", to="reykjavik")


def test_only_a_movement_form_takes_a_detachment() -> None:
    r = two_seats()
    live_detachment(r)
    person = r.state.seats[r.seats["roosevelt"]].embodies
    card = r.state.cards[person]
    levers = tuple(
        x.model_copy(update={"resolver": "shipping"}) if x.name == "move_fleet" else x
        for x in card.levers
    )
    r.state = r.state.model_copy(
        update={"cards": {**r.state.cards, person: card.model_copy(update={"levers": levers})}}
    )
    with pytest.raises(ValueError, match="force"):
        draft(r, "roosevelt", "move_fleet", force="us_atlantic_fleet__d1", to="reykjavik")
