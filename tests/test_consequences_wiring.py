"""Gate for the consequences build: Hitler's declaration of war leaves a visible mark.

Drives the real path on autumn-1941 (file the order, carry it through its pipeline,
run the realism tick past its settlement) and asserts what the world and each seat's
press then show. Fails until every worker's piece is in."""

from revisionist.core.ids import EntityId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism.document import DocumentKind
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.war import NewsTopic, at_war
from revisionist.core.visibility import Visibility
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.realism_tick import draft_order, file_order, run_realism_tick
from revisionist.engine.store import MemoryStore, load_state
from tests.test_realism_tick import CAMPAIGN

ATTACK = {"posture": "attack_us_shipping", "theatre": "north_atlantic"}


def test_a_declaration_of_war_leaves_a_visible_mark() -> None:
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path("autumn-1941"))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    ids = resolve_keys(decl, CAMPAIGN)
    fdr = SeatId(derived_id(CAMPAIGN, "seat", ids["roosevelt"]))
    hitler = SeatId(derived_id(CAMPAIGN, "seat", ids["hitler"]))
    session_zero.claim(store, CAMPAIGN, fdr, "Franklin D. Roosevelt")
    realism_tick.seat_player(store, CAMPAIGN, EntityId(ids["hitler"]))
    germany, usa = EntityId(ids["germany"]), EntityId(ids["usa"])

    # 1. no shooting war before one is declared
    state = load_state(store, CAMPAIGN)
    try:
        draft_order(state, hitler, "uboat_directive", ATTACK)
    except ValueError:
        pass
    else:
        raise AssertionError("attack_us_shipping was draftable before any declaration of war")

    # 2. the declaration, carried through its pipeline and past its settlement
    order = file_order(store, CAMPAIGN, hitler, "declare_war", {"target": "usa"})
    for _ in range(30):
        run_realism_tick(store, CAMPAIGN)
        if load_state(store, CAMPAIGN).orders[order.order_id].status is OrderStatus.ENACTED:
            break
    state = load_state(store, CAMPAIGN)
    assert state.orders[order.order_id].status is OrderStatus.ENACTED, "the order never enacted"

    # 3. the war is on the record, publicly
    assert at_war(state, germany, usa), "no war between Germany and the United States"
    marks = [f for f in state.facts.values() if f.predicate == "at_war_with"]
    assert marks and all(f.scope.visibility is Visibility.PUBLIC for f in marks), (
        "no public at_war_with fact"
    )

    # 4. a day on, each side's press has printed the same news in its own voice
    run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    press = {
        seat: [
            d
            for d in project(state, seat).documents.values()
            if d.kind is DocumentKind.PRESS and d.author == EntityId(ids[paper])
        ]
        for seat, paper in ((fdr, "washington_ledger"), (hitler, "reichsbote"))
    }
    assert press[fdr], "Roosevelt sees no page from the Washington Ledger"
    assert press[hitler], "Hitler sees no page from Der Reichsbote"
    news = {n.news_id for n in state.news.values() if n.topic is NewsTopic.WAR_DECLARED}
    assert news, "no war_declared NewsEvent in state.news"
    # both pages were written from the one event, not from two
    pages = {
        seat: {state.documents[d.doc_id].truth.news_id for d in docs}
        for seat, docs in press.items()
    }
    assert pages[fdr] == pages[hitler] <= news and len(pages[fdr]) == 1, (
        f"the two papers did not report the same event: {pages}"
    )

    # 5. now the U-boats may be told to attack
    assert draft_order(load_state(store, CAMPAIGN), hitler, "uboat_directive", ATTACK)
