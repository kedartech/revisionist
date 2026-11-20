"""Two oddities seen in stored transcripts, driven on autumn-1941 through the real path.

Hitler's army order to Moscow came back "enacted" while every later report still put
Army Group Centre at Smolensk, and a declaration of war on the United States appeared to
be filed a second time after the first had been enacted.
"""

from datetime import date

import pytest

from revisionist.core.ids import EntityId, FeatureId, SeatId, derived_id
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.war import NewsTopic, at_war
from revisionist.core.state import State
from revisionist.core.world_compile import compile_world, object_id, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.realism_tick import file_order, run_realism_tick
from revisionist.engine.store import MemoryStore, load_state
from tests.test_realism_tick import CAMPAIGN

DECLARE = {"target": "usa"}
ARMY = "army_group_centre"


class Game:
    """A fresh autumn-1941 campaign with Hitler as the human seat."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        decl = cmp.load_world(cmp.world_path("autumn-1941"))
        self.store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
        self.ids = resolve_keys(decl, CAMPAIGN)
        fdr = SeatId(derived_id(CAMPAIGN, "seat", self.ids["roosevelt"]))
        self.hitler = SeatId(derived_id(CAMPAIGN, "seat", self.ids["hitler"]))
        session_zero.claim(self.store, CAMPAIGN, fdr, "Franklin D. Roosevelt")
        realism_tick.seat_player(self.store, CAMPAIGN, EntityId(self.ids["hitler"]))

    @property
    def state(self) -> State:
        return load_state(self.store, CAMPAIGN)

    def file(self, lever: str, **params: str) -> OrderStatus:
        """File Hitler's order and run wakes until it settles."""
        order = file_order(self.store, CAMPAIGN, self.hitler, lever, params)
        for _ in range(40):
            run_realism_tick(self.store, CAMPAIGN)
            if self.state.orders[order.order_id].status is OrderStatus.ENACTED:
                break
        return self.state.orders[order.order_id].status

    def tick_to(self, day: date) -> None:
        while (self.state.in_world_date or day) < day:
            run_realism_tick(self.store, CAMPAIGN)

    def army_at(self) -> str:
        """The key of the place Army Group Centre stands at."""
        state = self.state
        here = state.features[FeatureId(self.ids[ARMY])].places[0]
        return next(k for k, v in self.ids.items() if v == here and k in PLACES)


PLACES = ("smolensk", "vyazma", "kalinin", "mozhaisk", "moscow")


def test_a_second_declaration_of_war_on_the_usa_is_refused_once_the_first_is_enacted() -> None:
    g = Game()
    germany, usa = EntityId(g.ids["germany"]), EntityId(g.ids["usa"])
    assert g.file("declare_war", **DECLARE) is OrderStatus.ENACTED
    assert at_war(g.state, germany, usa)
    for day in (date(1941, 9, 3), date(1941, 9, 22), date(1941, 10, 20)):
        g.tick_to(day)
        with pytest.raises(ValueError, match="already at war"):
            file_order(g.store, CAMPAIGN, g.hitler, "declare_war", DECLARE)
    state = g.state
    assert len(state.wars) == 1
    declared = [n for n in state.news.values() if n.topic is NewsTopic.WAR_DECLARED]
    assert len(declared) == 1


def test_a_second_declaration_filed_before_the_first_settles_is_refused() -> None:
    g = Game()
    file_order(g.store, CAMPAIGN, g.hitler, "declare_war", DECLARE)
    with pytest.raises(ValueError, match="already sent that"):
        file_order(g.store, CAMPAIGN, g.hitler, "declare_war", DECLARE)


def test_an_army_order_beyond_reach_is_refused_when_given() -> None:
    g = Game()
    assert g.army_at() == "smolensk"
    before = len(g.state.orders)
    with pytest.raises(ValueError, match="Moscow") as why:
        file_order(g.store, CAMPAIGN, g.hitler, "move_army", {"force": ARMY, "to": "moscow"})
    assert "15 days" in str(why.value) and "nearest base" in str(why.value)
    assert len(g.state.orders) == before
    assert g.army_at() == "smolensk"


def test_an_army_order_within_reach_still_moves_and_is_reported() -> None:
    g = Game()
    assert g.file("move_army", force=ARMY, to="mozhaisk") is OrderStatus.ENACTED
    g.tick_to(date(1941, 9, 16))
    assert g.army_at() == "mozhaisk"
    place = EntityId(object_id(CAMPAIGN, "entity", "mozhaisk"))
    held = g.state.features[FeatureId(g.ids[ARMY])]
    assert held.places == (place,) and held.bound_for is None
