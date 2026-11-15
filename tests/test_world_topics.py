"""A world can name topics and theatres: what people want and hold to, by topic, and
which theatre a place sits in. The holder's rule and the request rule weigh a card's
topics in place of its free-text interests; a card with no topics is weighed as before."""

from datetime import date
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import (
    CampaignId,
    EntityId,
    EventId,
    FeatureId,
    OrderId,
    PipelineId,
    SeatId,
    derived_id,
)
from revisionist.core.ontology import Entity, EntityKind
from revisionist.core.project import project
from revisionist.core.realism import effect as rx
from revisionist.core.realism import pipelines, process
from revisionist.core.realism.card import CardFace, Desk, SeatCard, Topic
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.resolvers import votes
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, Scope, private_to
from revisionist.core.world import TopicDecl, WorldFile
from revisionist.core.world_compile import WorldError, compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.realism_tick import run_realism_tick
from revisionist.engine.store import MemoryStore, load_state

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
SLICE = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
AUTUMN = cmp.load_world(cmp.world_path("autumn-1941"))
FILED = date(1941, 9, 11)
SEAS = TopicDecl(key="seas", name="Freedom of the seas", words=("seas",))
TARIFFS = TopicDecl(key="tariffs", name="Tariffs", words=("tariffs",))
STATEMENTS = TopicDecl(key="statements", name="Public statements", effects=("statement",))
BILLS = TopicDecl(key="bills", name="Bills", levers=("send_bill",))
NEUTRALITY = TopicDecl(key="neutrality", name="Neutrality", words=("neutrality",))
MEASURES = TopicDecl(key="measures", name="Measures", effects=("measure",))
ALL = (SEAS, TARIFFS, STATEMENTS, BILLS, NEUTRALITY, MEASURES)


def _world(
    base: WorldFile = SLICE,
    topics: tuple[TopicDecl, ...] = ALL,
    places: dict[str, str] | None = None,
    **cards: dict[str, Any],
) -> WorldFile:
    """``base`` with ``topics``, each named card updated, and a theatre on each named place."""
    places = places or {}
    return base.model_copy(
        update={
            "topics": topics,
            "cards": tuple(
                c.model_copy(update=cards[c.person]) if c.person in cards else c for c in base.cards
            ),
            "entities": tuple(
                e.model_copy(update={"theatre": places[e.key]}) if e.key in places else e
                for e in base.entities
            ),
        }
    )


def _problems(world: WorldFile) -> tuple[str, ...]:
    with pytest.raises(WorldError) as caught:
        compile_world(world, CAMPAIGN, cmp.versions())
    return caught.value.problems


def _state(world: WorldFile) -> State:
    return replay(compile_world(world, CAMPAIGN, cmp.versions()))


def _id(world: WorldFile, key: str) -> str:
    return resolve_keys(world, CAMPAIGN)[key]


# --- topics in the world file ---------------------------------------------------


def test_topics_reach_the_state_as_pipelines_do() -> None:
    state = _state(_world())
    assert set(state.topics) == {t.key for t in ALL}
    seas = state.topics["seas"]
    assert (seas.name, seas.levers, seas.effects, seas.words) == (
        "Freedom of the seas",
        (),
        (),
        ("seas",),
    )
    assert state.topics["bills"].levers == ("send_bill",)
    assert state.topics["statements"].effects == (rx.EffectKind.STATEMENT,)


def test_a_topic_key_is_one_key_in_the_worlds_namespace() -> None:
    problems = _problems(_world(topics=(SEAS, SEAS.model_copy(update={"name": "Again"}))))
    assert "topic seas: duplicate key" in problems
    clash = _problems(_world(topics=(SEAS.model_copy(update={"key": "wheeler"}),)))
    assert "topic wheeler: duplicate key" in clash


def test_a_topic_naming_a_lever_no_card_has_is_refused() -> None:
    problems = _problems(_world(topics=(BILLS.model_copy(update={"levers": ("no_such",)}),)))
    assert problems == ("topic bills: unknown lever no_such",)


def test_a_topic_naming_an_unknown_effect_kind_is_refused() -> None:
    problems = _problems(_world(topics=(STATEMENTS.model_copy(update={"effects": ("speech",)}),)))
    assert problems == ("topic statements: unknown effect kind speech",)


def test_a_legacy_world_has_no_topics() -> None:
    legacy = cmp.load_world(cmp.world_path("salt-strait"))
    assert legacy.ruleset == "legacy"
    problems = _problems(legacy.model_copy(update={"topics": (SEAS,)}))
    assert "topics: only a realism world has topics" in problems


# --- wants and holds to on a card ------------------------------------------------


def test_a_card_wants_and_holds_to_topics_by_key() -> None:
    state = _state(_world(wheeler={"wants": ("seas",), "holds_to": ("tariffs", "bills")}))
    card = state.cards[EntityId(_id(SLICE, "wheeler"))]
    assert (card.wants, card.holds_to) == (("seas",), ("tariffs", "bills"))


@pytest.mark.parametrize("field", ["wants", "holds_to"])
def test_a_card_naming_an_unknown_topic_is_refused(field: str) -> None:
    assert _problems(_world(wheeler={field: ("piracy",)})) == (
        "card wheeler: unknown topic piracy",
    )
    assert _problems(_world(wheeler={field: ("roosevelt",)})) == (
        "card wheeler: roosevelt is a entity, not a topic",
    )


def test_wants_and_holds_to_are_left_out_of_a_stored_card_while_empty() -> None:
    state = _state(_world(wheeler={"wants": ("seas",)}))
    wheeler = state.cards[EntityId(_id(SLICE, "wheeler"))].model_dump(mode="json")
    assert wheeler["wants"] == ["seas"] and "holds_to" not in wheeler
    roosevelt = state.cards[EntityId(_id(SLICE, "roosevelt"))].model_dump()
    assert not {"wants", "holds_to"} & set(roosevelt)


def test_a_world_without_topics_stores_nothing_new() -> None:
    events = compile_world(SLICE, CAMPAIGN, cmp.versions())
    (declared,) = [e.payload for e in events if isinstance(e.payload, ev.CardsDeclared)]
    assert "topics" not in declared.model_dump()
    assert "topics" not in replay(events).model_dump()


def test_the_new_world_fields_are_not_offered_to_a_model_drafting_a_world() -> None:
    schema = WorldFile.model_json_schema()["$defs"]
    assert not {"wants", "holds_to"} & set(schema["CardDecl"]["properties"])
    assert "theatre" not in schema["EntityDecl"]["properties"]


# --- an order touching a topic -------------------------------------------------


def _topic(**fields: object) -> Topic:
    return Topic.model_validate({"key": "t", "name": "T", **fields})


def test_an_order_touches_a_topic_by_lever_effect_kind_or_word() -> None:
    assert _topic(levers=("send_bill",)).touched("send_bill", set(), set())
    assert not _topic(levers=("send_bill",)).touched(None, {"send_bill"}, {"send_bill"})
    assert _topic(effects=("measure",)).touched(None, {"measure"}, set())
    assert not _topic(effects=("measure",)).touched("measure", set(), {"measure"})
    assert _topic(words=("neutrality",)).touched(None, set(), {"neutrality", "act"})
    assert not _topic(words=("neutrality",)).touched("neutrality", {"neutrality"}, {"act"})


# --- the request rule ------------------------------------------------------------


def _event(n: int, payload: ev.Payload, scope: Scope = PUBLIC) -> ev.Event:
    return ev.Event(
        event_id=EventId(derived_id(CAMPAIGN, "topic-event", n)),
        campaign_id=CAMPAIGN,
        seq=n,
        tick=0,
        scope=scope,
        payload=payload,
        versions=cmp.versions(),
    )


def _request(world: WorldFile, effect: rx.Effect) -> int:
    """The interest points Wheeler gives a request from Roosevelt carrying ``effect``."""
    events = compile_world(world, CAMPAIGN, cmp.versions())
    fdr = SeatId(derived_id(CAMPAIGN, "seat", "roosevelt"))
    wheeler = EntityId(_id(world, "wheeler"))
    part = rx.RoutedPart(route=rx.Route.INFLUENCE, target=wheeler, effect=effect)
    order = rx.RoutedOrder(
        order_id=OrderId(derived_id(CAMPAIGN, "ask")), issuer=fdr, filed=FILED, parts=(part,)
    )
    for payload, scope in (
        (ev.CharacterClaimed(seat_id=fdr, entity_id=EntityId(_id(world, "roosevelt"))), PUBLIC),
        (ev.SessionZeroClosed(), PUBLIC),
        (ev.OrderRouted(order=order), private_to(fdr)),
    ):
        events.append(_event(len(events), payload, scope))
    state = replay(events)
    routed = state.routed[order.order_id]
    _, interest, _, _ = process._score(state, routed, routed.parts[0])
    return interest


SPEECH = rx.MakeStatement(theme="freedom of the seas")
FREE_TEXT: dict[str, Any] = {"interests": ("freedom of the seas",)}


def test_a_request_touching_a_topic_the_target_wants_gains_the_points() -> None:
    assert _request(_world(wheeler={"wants": ("seas",)}), SPEECH) == process.INTEREST_POINTS
    assert _request(_world(wheeler={"holds_to": ("statements",)}), SPEECH) == 2


def test_a_tagged_card_never_gains_points_from_its_free_text_interests() -> None:
    world = _world(wheeler={"wants": ("tariffs",), **FREE_TEXT})
    assert _request(world, SPEECH) == 0


def test_a_card_with_no_topics_is_weighed_on_its_free_text_interests_as_before() -> None:
    assert _request(_world(wheeler=FREE_TEXT), SPEECH) == 2
    assert _request(_world(wheeler={"interests": ("tariffs",)}), SPEECH) == 0


def test_a_tagged_card_set_against_the_war_still_refuses_warlike_requests() -> None:
    shoot = rx.SetEngagement(
        force=FeatureId(_id(SLICE, "us_atlantic_fleet")),
        zone="western Atlantic",
        rule=rx.Engagement.SHOOT_ON_SIGHT,
    )
    world = _world(wheeler={"wants": ("seas",)})
    assert SLICE.cards[[c.person for c in SLICE.cards].index("wheeler")].interests == (
        "keep the United States out of the war",
    )
    assert _request(world, shoot) == -process.INTEREST_POINTS


# --- the holder's rule ------------------------------------------------------------


def _holder(world: WorldFile, card: dict[str, Any], order: dict[str, Any]) -> int:
    """The interest points the House holder gives Roosevelt's bill, with ``card`` on the
    holder and ``order`` on the order."""
    state = _state(world)
    pipeline = PipelineId(_id(world, "bill_through_congress"))
    holder = state.pipelines[pipeline].steps[0].person
    held = state.cards[holder].model_copy(update=card)
    fields: dict[str, object] = {
        "order_id": OrderId(derived_id(CAMPAIGN, "bill")),
        "issuer": SeatId(derived_id(CAMPAIGN, "seat", "roosevelt")),
        "lever": "send_bill",
        "pipeline": pipeline,
        "params": {"bill": "neutrality_revision"},
        "filed": FILED,
    }
    return pipelines._interest(state, Order.model_validate(fields | order), held)


def test_the_holder_gains_points_from_a_topic_by_lever_word_or_effect_kind() -> None:
    world = _world()
    assert _holder(world, {"wants": ("bills",), "interests": (), "doctrine": ()}, {}) == 2
    assert _holder(world, {"holds_to": ("neutrality",)}, {}) == 2
    measure = {"lever": "measure", "params": {}, "measure": votes.HISTORICAL["neutrality_revision"]}
    assert _holder(world, {"wants": ("measures",)}, measure) == 2
    assert _holder(world, {"wants": ("measures",)}, {}) == 0


def test_a_tagged_holder_never_gains_points_from_free_text_interests() -> None:
    card = {"wants": ("tariffs",), "interests": ("neutrality",), "doctrine": ("revision",)}
    assert _holder(_world(), card, {}) == 0


def test_a_holder_with_no_topics_is_weighed_on_free_text_as_before() -> None:
    assert _holder(_world(), {"interests": ("neutrality",), "doctrine": ()}, {}) == 2
    assert _holder(_world(), {"interests": (), "doctrine": ("send",)}, {}) == 2
    assert _holder(_world(), {"interests": ("tariffs",), "doctrine": ()}, {}) == 0


# --- theatres --------------------------------------------------------------------


def test_a_place_carries_its_theatre_into_every_seats_view() -> None:
    world = _world(topics=(), places={"washington": "North America"})
    events = compile_world(world, CAMPAIGN, cmp.versions())
    fdr = SeatId(derived_id(CAMPAIGN, "seat", "roosevelt"))
    claim = ev.CharacterClaimed(seat_id=fdr, entity_id=EntityId(_id(world, "roosevelt")))
    state = replay([*events, _event(len(events), claim)])
    place = EntityId(_id(world, "washington"))
    assert state.entities[place].theatre == "North America"
    assert project(state, fdr).entities[place].theatre == "North America"


def test_only_a_place_has_a_theatre() -> None:
    assert _problems(_world(topics=(), places={"wheeler": "North America"})) == (
        "entity wheeler: only a place has a theatre",
    )


def test_a_place_without_a_theatre_stores_as_before() -> None:
    plain = Entity(entity_id=EntityId("p"), kind=EntityKind.LOCATION, name="Washington")
    assert "theatre" not in plain.model_dump()
    assert plain.model_copy(update={"theatre": "North America"}).model_dump()["theatre"]


# --- stored games ------------------------------------------------------------------


def test_a_stored_game_is_not_amended_with_topics_wants_or_theatres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = AUTUMN.model_copy(
        update={"entities": tuple(e.model_copy(update={"theatre": None}) for e in AUTUMN.entities)}
    )
    store = MemoryStore()
    store.append_all(compile_world(stored, CAMPAIGN, cmp.versions()))
    roosevelt = EntityId(resolve_keys(AUTUMN, CAMPAIGN)["roosevelt"])
    realism_tick.seat_player(store, CAMPAIGN, roosevelt)
    tagged = _world(
        AUTUMN,
        topics=(BILLS, NEUTRALITY),
        places={"washington": "North America"},
        roosevelt={"wants": ("bills",)},
        hull={"holds_to": ("neutrality",)},
    )
    assert compile_world(tagged, CAMPAIGN, cmp.versions())
    monkeypatch.setattr(cmp, "load_world", lambda _path: tagged)
    run_realism_tick(store, CAMPAIGN)
    state = load_state(store, CAMPAIGN)
    assert state.topics == {}
    assert not any(c.wants or c.holds_to for c in state.cards.values())
    assert not any(e.theatre for e in state.entities.values())


def test_seat_card_fields_are_policy_and_absent_from_the_face() -> None:
    assert {"wants", "holds_to"} <= set(SeatCard.model_fields)
    assert not {"wants", "holds_to"} & (set(CardFace.model_fields) | set(Desk.model_fields))
