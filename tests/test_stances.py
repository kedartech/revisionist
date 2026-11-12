"""Where each person nobody plays stands toward a seat, and who is actively
opposing it: worked out in code from sides, allies, declared conflicts and regard."""

from datetime import date, timedelta

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import (
    CampaignId,
    DocumentId,
    EntityId,
    EventId,
    OrderId,
    RelationshipId,
    SeatId,
    derived_id,
)
from revisionist.core.ontology import Relationship
from revisionist.core.project import project
from revisionist.core.realism import opponents
from revisionist.core.realism.card import ChannelKind, Conflict
from revisionist.core.realism.document import Document, DocumentKind, DocumentTruth, DocumentView
from revisionist.core.realism.effect import Route, RoutedOrder, RoutedPart
from revisionist.core.realism.stance import Stance, StanceCause, band, step
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.emit import Emitter
from revisionist.engine.ids import new_id
from revisionist.engine.prose import TemplateProseWriter
from revisionist.engine.store import EventStore, MemoryStore, load_state
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web.threats import seat_threats

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
WORLD = "autumn-1941"
HEADS = ("roosevelt", "stalin", "hitler", "konoe", "tojo", "mussolini", "chiang")


def begun(who: str = "churchill") -> tuple[EventStore, SeatId, dict[str, EntityId]]:
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path(WORLD))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    keys = {k: EntityId(v) for k, v in resolve_keys(decl, CAMPAIGN).items()}
    realism_tick.seat_player(store, CAMPAIGN, keys[who])
    (seat,) = load_state(store, CAMPAIGN).seats
    return store, seat, keys


def bare(state: State) -> State:
    """The same game before any stance was worked out."""
    return state.model_copy(update={"stances": {}, "opponents": {}})


def regard(state: State, of: EntityId, toward: EntityId, n: int, seat: SeatId) -> State:
    rel = Relationship(
        relationship_id=RelationshipId(derived_id(state.campaign_id, "rel", of, toward)),
        a=of,
        b=toward,
        disposition=n,
        scope=private_to(seat),
    )
    return state.model_copy(
        update={"relationships": {**state.relationships, rel.relationship_id: rel}}
    )


def with_card(state: State, person: EntityId, **update: object) -> State:
    card = state.cards[person].model_copy(update=update)
    return state.model_copy(update={"cards": {**state.cards, person: card}})


def settled(state: State, day: date, **kw: object) -> State:
    made = opponents.settle(state, day, **kw)  # type: ignore[arg-type]
    return replay([_event(state, p, i) for i, p in enumerate(made)], initial=state)


def _event(state: State, payload: ev.Payload, i: int) -> ev.Event:
    return ev.Event(
        event_id=EventId(new_id()),
        campaign_id=state.campaign_id,
        seq=state.last_seq + 1 + i,
        tick=state.tick,
        scope=PUBLIC,
        versions=cmp.versions(),
        payload=payload,
    )


def now(state: State, seat: SeatId, figure: EntityId) -> Stance:
    return state.stances[seat][figure][-1].stance


@pytest.mark.parametrize(
    ("score", "stance"),
    [
        (-9, Stance.HOSTILE),
        (-5, Stance.HOSTILE),
        (-4, Stance.OBSTRUCTING),
        (-2, Stance.OBSTRUCTING),
        (-1, Stance.NEUTRAL),
        (1, Stance.NEUTRAL),
        (2, Stance.COOPERATIVE),
        (3, Stance.COOPERATIVE),
        (4, Stance.ALIGNED),
        (9, Stance.ALIGNED),
    ],
)
def test_each_score_falls_in_one_band(score: int, stance: Stance) -> None:
    assert band(score) is stance
    assert step(None, score) is stance


def test_a_stance_holds_until_the_score_is_past_the_edge_by_more_than_one() -> None:
    assert step(Stance.NEUTRAL, -2) is Stance.NEUTRAL
    assert step(Stance.NEUTRAL, -3) is Stance.OBSTRUCTING
    assert step(Stance.NEUTRAL, 2) is Stance.NEUTRAL
    assert step(Stance.NEUTRAL, 3) is Stance.COOPERATIVE
    assert step(Stance.OBSTRUCTING, -5) is Stance.OBSTRUCTING
    assert step(Stance.OBSTRUCTING, -6) is Stance.HOSTILE
    assert step(Stance.HOSTILE, -4) is Stance.HOSTILE
    assert step(Stance.HOSTILE, -3) is Stance.OBSTRUCTING


def test_an_irreducible_conflict_keeps_the_stance_at_obstructing_or_worse() -> None:
    assert step(None, 5, capped=True) is Stance.OBSTRUCTING
    assert step(Stance.OBSTRUCTING, 9, capped=True) is Stance.OBSTRUCTING
    assert step(None, -7, capped=True) is Stance.HOSTILE


def test_the_people_weighed_are_the_unplayed_ones_with_an_office_to_act_from() -> None:
    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    assert set(opponents.figures(state, seat)) == {keys[k] for k in HEADS}


def test_sides_come_from_contests_allies_and_wars() -> None:
    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    side = {k: opponents.parts(state, keys[k], seat).side for k in HEADS}
    assert side["hitler"] == side["mussolini"] == -3  # the other side of the war against Germany
    assert side["stalin"] == side["roosevelt"] == 2  # allies
    assert side["konoe"] == side["tojo"] == side["chiang"] == 0  # no contest in common
    war = War(
        war_id=war_id_for(keys["uk"], keys["ussr"]),
        a=keys["uk"],
        b=keys["ussr"],
        since=date(1941, 9, 2),
        declared_by=keys["churchill"],
    )
    fought = state.model_copy(update={"wars": {war.war_id: war}})
    assert opponents.parts(fought, keys["stalin"], seat).side == -3  # a war outweighs an alliance


def test_regard_and_declared_conflicts_move_the_score() -> None:
    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    hitler, churchill = keys["hitler"], keys["churchill"]
    assert opponents.parts(state, hitler, seat).total == -3
    liked = regard(state, hitler, churchill, 4, seat)
    assert opponents.parts(liked, hitler, seat).total == 1
    at_odds = with_card(
        liked,
        hitler,
        opposes=(
            Conflict(against=keys["uk"], over="Command of the Atlantic"),
            Conflict(against=churchill, over="The war itself", irreducible=True),
            Conflict(against=keys["ussr"], over="Living space in the east"),
        ),
    )
    got = opponents.parts(at_odds, hitler, seat)
    assert (got.conflicts, got.total, got.capped) == (2, -3, True)


def test_the_first_settling_gives_every_figure_a_stance_and_a_later_one_only_changes() -> None:
    store, seat, keys = begun()
    state = bare(load_state(store, CAMPAIGN))
    day = date(1941, 9, 2)
    first = opponents.settle(state, day)
    changed = [p for p in first if isinstance(p, ev.StanceChanged)]
    assert {p.figure for p in changed} == {keys[k] for k in HEADS}
    assert all(p.standing.cause is StanceCause.START and p.standing.on == day for p in changed)
    (ranked,) = [p for p in first if isinstance(p, ev.OpponentsRanked)]
    assert set(ranked.active) == {keys["hitler"], keys["mussolini"]}
    after = settled(state, day)
    assert now(after, seat, keys["stalin"]) is Stance.COOPERATIVE
    assert now(after, seat, keys["konoe"]) is Stance.NEUTRAL
    assert opponents.settle(after, day + timedelta(days=1)) == []


def test_a_change_of_regard_is_logged_with_the_order_that_caused_it() -> None:
    store, seat, keys = begun()
    state = settled(bare(load_state(store, CAMPAIGN)), date(1941, 9, 2))
    stalin, churchill = keys["stalin"], keys["churchill"]
    soured = regard(state, stalin, churchill, -4, seat)
    rel = next(iter(soured.relationships.values()))
    order = OrderId(derived_id(CAMPAIGN, "order", "x"))
    landed: list[ev.Payload] = [
        ev.RelationshipSet(relationship=rel),
        ev.EffectsApplied(order_id=order, part=0, on=date(1941, 9, 5)),
    ]
    (change,) = [
        p
        for p in opponents.settle(soured, date(1941, 9, 5), landed)
        if isinstance(p, ev.StanceChanged)
    ]
    assert change.figure == stalin
    assert change.standing.stance is Stance.OBSTRUCTING  # 2 - 4 = -2, past neutral's edge
    assert change.standing.cause is StanceCause.DISPOSITION
    assert change.standing.order == order
    assert opponents.settle(soured, date(1941, 9, 5))[0].standing.order is None  # type: ignore[union-attr]


def test_no_more_than_four_oppose_a_seat_and_one_joins_per_wake() -> None:
    store, seat, keys = begun()
    state = bare(load_state(store, CAMPAIGN))
    for k in HEADS:
        state = regard(state, keys[k], keys["churchill"], -5, seat)
    day = date(1941, 9, 2)
    first = settled(state, day)
    assert len(first.opponents[seat]) == opponents.CAP == 4
    left_out = [keys[k] for k in HEADS if keys[k] not in first.opponents[seat]]
    assert len(left_out) == 3
    # two of the four come round: they leave, and one of those left out joins this wake
    gone = first.opponents[seat][:2]
    eased = first
    for figure in gone:
        eased = regard(eased, figure, keys["churchill"], 5, seat)
    start = dict(first.opponents)
    second = settled(eased, day + timedelta(days=1), wake_start=start)
    assert not set(gone) & set(second.opponents[seat])
    assert len(second.opponents[seat]) == 3
    assert len(set(second.opponents[seat]) & set(left_out)) == 1
    # later the same wake: no second newcomer
    assert opponents.settle(second, day + timedelta(days=2), wake_start=start) == []
    # the next wake: one more
    third = settled(second, day + timedelta(days=3), wake_start=dict(second.opponents))
    assert len(third.opponents[seat]) == 4


def test_the_strongest_of_those_opposed_are_taken_first() -> None:
    store, seat, keys = begun()
    state = bare(load_state(store, CAMPAIGN))
    for k in HEADS:
        state = regard(state, keys[k], keys["churchill"], -5, seat)
    state = with_card(
        state, keys["chiang"], opposes=(Conflict(against=keys["uk"], over="Burma"),) * 1
    )
    first = settled(state, date(1941, 9, 2))
    weights = sorted((opponents.weight(state, keys[k], seat) for k in HEADS), reverse=True)
    assert (
        sorted((opponents.weight(state, f, seat) for f in first.opponents[seat]), reverse=True)
        == weights[:4]
    )


def test_a_world_that_declares_no_allies_or_conflicts_has_no_stances() -> None:
    store, _seat, _keys = begun()
    state = bare(load_state(store, CAMPAIGN))
    for person in list(state.cards):
        state = with_card(state, person, allies=(), opposes=())
    assert opponents.settle(state, date(1941, 9, 2)) == []


def test_a_game_with_no_stances_dumps_as_it_did_before_there_were_any() -> None:
    store, _seat, keys = begun()
    state = bare(load_state(store, CAMPAIGN))
    dumped = state.model_dump(mode="json")
    assert "stances" not in dumped and "opponents" not in dumped
    plain = with_card(state, keys["hitler"], allies=(), opposes=())
    card = plain.model_dump(mode="json")["cards"][keys["hitler"]]
    assert "allies" not in card and "opposes" not in card


def test_the_fold_refuses_a_stance_that_is_no_change() -> None:
    store, _seat, _keys = begun()
    state = bare(load_state(store, CAMPAIGN))
    made = opponents.settle(state, date(1941, 9, 2))
    after = settled(state, date(1941, 9, 2))
    again = next(p for p in made if isinstance(p, ev.StanceChanged))
    with pytest.raises(Exception, match="not a change"):
        replay([_event(after, again, 0)], initial=after)


def test_the_stances_are_worked_out_at_the_begin_and_kept_through_a_tick() -> None:
    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    assert set(state.opponents[seat]) == {keys["hitler"], keys["mussolini"]}
    assert now(state, seat, keys["roosevelt"]) is Stance.COOPERATIVE
    before = len(list(store.read(CAMPAIGN)))
    realism_tick.run_realism_tick(store, CAMPAIGN, prose=TemplateProseWriter())
    kinds = [e.payload.kind for e in list(store.read(CAMPAIGN))[before:]]
    assert "stance_changed" not in kinds and "opponents_ranked" not in kinds
    assert load_state(store, CAMPAIGN).opponents == state.opponents


def test_a_change_of_regard_between_wakes_is_settled_in_the_next_tick() -> None:
    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    soured = regard(state, keys["stalin"], keys["churchill"], -4, seat)
    rel = next(iter(soured.relationships.values()))
    em = Emitter(store, state, cmp.versions())
    em.commit([em.event(ev.RelationshipSet(relationship=rel), scope=rel.scope)])
    realism_tick.run_realism_tick(store, CAMPAIGN, prose=TemplateProseWriter())
    after = load_state(store, CAMPAIGN)
    assert now(after, seat, keys["stalin"]) is Stance.OBSTRUCTING
    assert after.opponents[seat][-1] == keys["stalin"] and len(after.opponents[seat]) == 3


def test_no_regard_lifts_a_person_with_an_irreducible_conflict_above_obstructing() -> None:
    store, seat, keys = begun()
    state = bare(load_state(store, CAMPAIGN))
    hitler = keys["hitler"]
    state = with_card(
        state, hitler, opposes=(Conflict(against=keys["uk"], over="The war", irreducible=True),)
    )
    warm = settled(regard(state, hitler, keys["churchill"], 5, seat), date(1941, 9, 2))
    assert opponents.parts(warm, hitler, seat).total == 0
    assert now(warm, seat, hitler) is Stance.OBSTRUCTING and hitler in warm.opponents[seat]


def test_a_seat_for_a_person_nobody_plays_is_weighed_by_nobody_and_weighs_no_one() -> None:
    from revisionist.core.realism import actors

    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    em = Emitter(store, state, cmp.versions())
    made = actors.unseated(state, [keys["hitler"]])
    em.commit([em.event(m, scope=PUBLIC) for m in made])
    state = bare(load_state(store, CAMPAIGN))
    out = opponents.settle(state, date(1941, 9, 2))
    assert {p.seat_id for p in out} == {seat}  # type: ignore[union-attr]
    assert keys["hitler"] in opponents.figures(state, seat)


# --- what the seat is shown ------------------------------------------------------

START = date(1941, 9, 1)


def shown(state: State, seat: SeatId) -> dict[str, dict[str, object]]:
    return {t["name"]: dict(t) for t in seat_threats(state, seat, project(state, seat))}


def on_day(state: State, day: date) -> State:
    return state.model_copy(update={"in_world_date": day})


def letter_from(state: State, author: EntityId, seat: SeatId, issued: date) -> State:
    doc_id = DocumentId(derived_id(state.campaign_id, "doc", author, issued.isoformat()))
    page = DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.LETTER,
        author=author,
        issued=issued,
        arrives=issued,
        channel=ChannelKind.CABLE,
        title="A reply",
        scope=private_to(seat),
    )
    doc = Document(view=page, truth=DocumentTruth(doc_id=doc_id))
    return state.model_copy(update={"documents": {**state.documents, doc_id: doc}})


def test_the_seat_is_shown_its_opponents_as_they_stood_at_the_start() -> None:
    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    got = shown(state, seat)
    assert list(got) == ["Adolf Hitler", "Benito Mussolini"]
    hitler = got["Adolf Hitler"]
    assert hitler == {
        "person": keys["hitler"],
        "name": "Adolf Hitler",
        "office": state.cards[keys["hitler"]].office,
        "stance": "obstructing",
        "stance_label": "Obstructing",
        "trend": "steady",
        "as_of": "1941-09-01",
        "confidence": "firm",
        "over": [],
        "cause": "As things stood at the start.",
    }
    block = rs.seat_realism(state, seat, set(), set(), None)
    assert [t["name"] for t in block["threats"]] == list(got)


def test_a_turn_the_seat_has_no_evidence_of_is_not_shown_until_evidence_comes() -> None:
    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    stalin = keys["stalin"]
    soured = regard(state, stalin, keys["churchill"], -4, seat)
    theirs: list[ev.Payload] = [  # another seat's order did it
        ev.RelationshipSet(relationship=next(iter(soured.relationships.values()))),
        ev.EffectsApplied(
            order_id=OrderId(derived_id(CAMPAIGN, "order", "theirs")), part=0, on=date(1941, 9, 5)
        ),
    ]
    turned = settled(soured, date(1941, 9, 5), landed=theirs)
    assert now(turned, seat, stalin) is Stance.OBSTRUCTING and stalin in turned.opponents[seat]
    assert turned.stances[seat][stalin][-1].order is not None
    assert "Joseph Stalin" not in shown(on_day(turned, date(1941, 9, 8)), seat)
    heard = letter_from(on_day(turned, date(1941, 9, 8)), stalin, seat, date(1941, 9, 6))
    line = shown(heard, seat)["Joseph Stalin"]
    assert (line["stance"], line["trend"], line["as_of"]) == ("obstructing", "worse", "1941-09-06")
    assert line["cause"] == "Cause not known."
    # a paper written before the turn is no evidence of it
    early = letter_from(on_day(turned, date(1941, 9, 8)), stalin, seat, date(1941, 9, 4))
    assert "Joseph Stalin" not in shown(early, seat)


def test_an_opponent_who_came_round_unseen_is_still_shown_as_one() -> None:
    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    hitler = keys["hitler"]
    eased = settled(regard(state, hitler, keys["churchill"], 5, seat), date(1941, 9, 5))
    assert now(eased, seat, hitler) is Stance.COOPERATIVE and hitler not in eased.opponents[seat]
    line = shown(on_day(eased, date(1941, 10, 20)), seat)["Adolf Hitler"]
    assert (line["stance"], line["as_of"], line["confidence"]) == (
        "obstructing",
        "1941-09-01",
        "old",
    )
    assert shown(on_day(eased, date(1941, 9, 20)), seat)["Adolf Hitler"]["confidence"] == "dated"


def test_a_turn_the_seats_own_order_brought_on_is_shown_with_its_cause() -> None:
    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    stalin = keys["stalin"]
    order = RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "order", "x")),
        issuer=seat,
        filed=date(1941, 9, 3),
        parts=(RoutedPart(route=Route.INFLUENCE, target=stalin),),
    )
    state = state.model_copy(update={"routed": {order.order_id: order}})
    soured = regard(state, stalin, keys["churchill"], -4, seat)
    rel = next(iter(soured.relationships.values()))
    landed: list[ev.Payload] = [
        ev.RelationshipSet(relationship=rel),
        ev.EffectsApplied(order_id=order.order_id, part=0, on=date(1941, 9, 5)),
    ]
    turned = on_day(settled(soured, date(1941, 9, 5), landed=landed), date(1941, 9, 6))
    line = shown(turned, seat)["Joseph Stalin"]
    assert (line["stance"], line["trend"], line["as_of"]) == ("obstructing", "worse", "1941-09-05")
    assert line["cause"] == "After your order of 3 September 1941."


def test_the_list_names_what_the_two_are_at_odds_over_and_nothing_of_the_card() -> None:
    store, seat, keys = begun()
    state = load_state(store, CAMPAIGN)
    hitler = keys["hitler"]
    state = with_card(
        state,
        hitler,
        opposes=(
            Conflict(against=keys["uk"], over="Command of the Atlantic"),
            Conflict(against=keys["ussr"], over="Living space in the east"),
        ),
    )
    text = str(rs.seat_realism(state, seat, set(), set(), None)["threats"])
    assert "Command of the Atlantic" in text and "Living space" not in text
    card = state.cards[hitler]
    assert card.aims and not any(aim in text for aim in card.aims)
    assert not any(word in text for word in ("score", "disposition", "side", *card.doctrine))


def test_the_client_fixture_carries_a_threat_in_the_servers_shape() -> None:
    import json
    from pathlib import Path

    from revisionist.engine.web.realism_api import Threat

    fixture = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
    threats = json.loads(fixture.read_text())["threats"]
    assert threats and all(set(t) == set(Threat.__annotations__) for t in threats)
