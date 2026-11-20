"""After Hitler's declaration on autumn-1941, through the real tick: forces that meet
report contact to their own side, and the Gallup questions on war move only where a
reading exists. No model call."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId, QuantityId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.war import NewsTopic
from revisionist.core.state import State
from revisionist.core.world_compile import compile_world, object_id, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.realism_tick import file_order, run_realism_tick
from revisionist.engine.store import MemoryStore, load_state
from tests.test_realism_tick import CAMPAIGN

OPINION = ("gallup_declare_war_germany", "gallup_help_britain")


class War:
    """autumn-1941 with Roosevelt and Hitler seated and Germany at war with the US."""

    def __init__(self, seed_opinion: int | None = None) -> None:
        self.store = MemoryStore()
        decl = cmp.load_world(cmp.world_path("autumn-1941"))
        self.store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
        self.ids = resolve_keys(decl, CAMPAIGN)
        self.fdr = SeatId(derived_id(CAMPAIGN, "seat", self.ids["roosevelt"]))
        self.hitler = SeatId(derived_id(CAMPAIGN, "seat", self.ids["hitler"]))
        session_zero.claim(self.store, CAMPAIGN, self.fdr, "Franklin D. Roosevelt")
        realism_tick.seat_player(self.store, CAMPAIGN, EntityId(self.ids["hitler"]))
        if seed_opinion is not None:
            for key in OPINION:
                self.put(key, seed_opinion)
        self.before = {k: self.value(k) for k in OPINION}
        for _ in range(5):  # an order's id is random, and about one in a hundred lapses
            order = file_order(self.store, CAMPAIGN, self.hitler, "declare_war", {"target": "usa"})
            for _ in range(30):
                run_realism_tick(self.store, CAMPAIGN)
                status = self.state.orders[order.order_id].status
                if status is OrderStatus.ENACTED:
                    return
                if status is not OrderStatus.MOVING:
                    break
        raise AssertionError("the declaration never enacted")

    @property
    def state(self) -> State:
        """The campaign as the log stands now."""
        return load_state(self.store, CAMPAIGN)

    def value(self, key: str) -> int | None:
        """The quantity's current value; None while it is unread."""
        q = self.state.quantities[QuantityId(object_id(CAMPAIGN, "quantity", key))]
        return None if q.value is None else int(q.value)

    def put(self, key: str, v: int) -> None:
        """Seed a reading for the quantity, dated today."""
        q = self.state.quantities[QuantityId(object_id(CAMPAIGN, "quantity", key))]
        on = self.state.in_world_date or date(1941, 9, 1)
        self.append(ev.QuantitySet(quantity=q.model_copy(update={"value": v, "as_of": on})))

    def append(self, payload: ev.Payload) -> None:
        """Log ``payload`` publicly, as the engine would, between ticks."""
        realism_tick._append(self.store, self.state, payload, self.hitler)


def test_forces_that_meet_report_contact_to_their_own_side() -> None:
    w = War()
    uboats = w.state.features[FeatureId(object_id(CAMPAIGN, "feature", "uboat_arm"))]
    norfolk = EntityId(w.ids["norfolk"])
    w.append(ev.FeatureSet(feature=uboats.model_copy(update={"places": (norfolk,)})))
    run_realism_tick(w.store, CAMPAIGN)
    state = w.state
    contact = [n for n in state.news.values() if n.topic is NewsTopic.CONTACT]
    assert len(contact) == 1, contact
    assert "Norfolk" not in contact[0].headline
    for seat in (w.fdr, w.hitler):
        mine = [
            d
            for d in project(state, seat).documents.values()
            if state.documents[d.doc_id].truth.news_id == contact[0].news_id
        ]
        assert mine, f"{seat} got no report of the contact"
    run_realism_tick(w.store, CAMPAIGN)
    again = [n for n in w.state.news.values() if n.topic is NewsTopic.CONTACT]
    assert len(again) == 1, "the same contact was reported twice"


def test_the_gallup_questions_on_war_rise_after_the_declaration() -> None:
    w = War(seed_opinion=40)
    assert w.before == {k: 40 for k in OPINION}
    after = {k: w.value(k) for k in OPINION}
    assert all(v is not None and v > 40 for v in after.values()), after


def test_an_unread_gallup_question_is_left_unread() -> None:
    w = War()
    assert w.before == {k: None for k in OPINION}
    assert {k: w.value(k) for k in OPINION} == w.before
