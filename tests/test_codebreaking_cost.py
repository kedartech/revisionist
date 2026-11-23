"""What funding codebreaking costs (IFC): ``CODE_COST`` output, or a month of the nation's
output income where that is less, and never under 1 point.

A world with a small economy (Salt Strait's nations earn 3 to 5 points a month) could
otherwise never pay for its cipher clerks within a season. The toy world as
``tests/test_intel_orders_land.py`` plays it; Norra's plain yields its output.
"""

import pytest

from revisionist.core.realism import detect
from revisionist.core.world import WorldFile
from tests.test_intel_orders_land import NORRA, day, entity, game, give, with_output, world


def poorer(grain: int) -> WorldFile:
    """The world with Norra's plain yielding ``grain`` output a month."""
    w = world()
    plains = tuple(
        t.model_copy(update={"yields": {**t.yields, "grain": grain}})
        if t.key == "norra_plain"
        else t
        for t in w.territories
    )
    return w.model_copy(update={"territories": plains})


@pytest.mark.parametrize("by", ["form", "written"])
def test_a_nation_earning_less_than_the_cost_pays_a_months_output(by: str) -> None:
    g = game(poorer(4))
    with_output(g, 5)
    give(g, by, "codebreaking")
    g.walk(day(1), day(1))
    intel = g.state.intelligence[entity(NORRA)]
    assert intel.raised == (day(1 + detect.CODE_DAYS),)
    assert g.state.economy.pools[entity(NORRA)].output == 1


def test_a_nation_earning_more_pays_the_cost() -> None:
    g = game(poorer(40))
    with_output(g, 25)
    give(g, "form", "codebreaking")
    g.walk(day(1), day(1))
    assert g.state.economy.pools[entity(NORRA)].output == 25 - detect.CODE_COST


def test_a_nation_earning_nothing_pays_one_point() -> None:
    g = game(poorer(0))
    with_output(g, 5)
    give(g, "form", "codebreaking")
    g.walk(day(1), day(1))
    assert g.state.economy.pools[entity(NORRA)].output == 4
