"""Reach (spec §8.1, §8.4): ties, channels and meetings on the engine-v2 slice."""

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, derived_id
from revisionist.core.ontology import Entity, EntityKind
from revisionist.core.realism.card import CHANNELS, ChannelKind, Reach, SeatCard, Tie
from revisionist.core.realism.reach import (
    EXPOSURE,
    TRANSIT_DAYS,
    channels_to,
    takes_meeting,
    tie,
    transit_days,
)
from revisionist.core.state import State
from tests.test_engine_v2_contract import CAMPAIGN, Slice
from tests.test_realism_bands import SEEDS


@pytest.fixture
def sl() -> Slice:
    return Slice()


def _clerk(sl: Slice) -> EntityId:
    """A navy clerk with no card, under the Navy Department."""
    clerk = EntityId(derived_id(CAMPAIGN, "entity", "clerk"))
    sl.add(
        ev.EntityCreated(
            entity=Entity(
                entity_id=clerk,
                kind=EntityKind.PERSON,
                name="A navy clerk",
                parent=sl.entity("navy_dept"),
            )
        )
    )
    return clerk


def _with_head(sl: Slice, rank: int = 5) -> tuple[State, EntityId]:
    """A German head of government, with a card, added to a copy of the slice's state."""
    head = EntityId(derived_id(CAMPAIGN, "entity", "chancellor"))
    state = sl.state
    entity = Entity(
        entity_id=head, kind=EntityKind.PERSON, name="The Chancellor", parent=sl.entity("germany")
    )
    card = SeatCard(
        person=head,
        office="Chancellor of the Reich",
        horizon_days=7,
        reach=Reach(rank=rank),
    )
    return (
        state.model_copy(
            update={
                "entities": {**state.entities, head: entity},
                "cards": {**state.cards, head: card},
            }
        ),
        head,
    )


def test_roosevelt_reaches_stark_inside_the_inner_circle(sl: Slice) -> None:
    fdr, stark = sl.entity("roosevelt"), sl.entity("stark")
    assert tie(sl.state, fdr, stark) is Tie.INNER
    channels = channels_to(sl.state, fdr, stark)
    assert channels[0] is ChannelKind.IN_PERSON
    assert set(channels) == set(ChannelKind)


def test_roosevelt_reaches_wheeler_only_as_a_public_figure(sl: Slice) -> None:
    fdr, wheeler = sl.entity("roosevelt"), sl.entity("wheeler")
    assert tie(sl.state, fdr, wheeler) is Tie.PUBLIC
    assert channels_to(sl.state, fdr, wheeler) == CHANNELS[Tie.PUBLIC]


def test_a_navy_clerk_without_a_card_is_in_stark_chain(sl: Slice) -> None:
    stark, clerk = sl.entity("stark"), _clerk(sl)
    assert sl.state.cards.get(clerk) is None
    assert tie(sl.state, stark, clerk) is Tie.CHAIN
    assert channels_to(sl.state, stark, clerk) == CHANNELS[Tie.CHAIN]
    assert takes_meeting(sl.state, stark, clerk)


def test_a_person_without_a_card_reaches_everyone_as_public(sl: Slice) -> None:
    clerk = _clerk(sl)
    assert tie(sl.state, clerk, sl.entity("stark")) is Tie.PUBLIC
    assert tie(sl.state, clerk, sl.entity("wheeler")) is Tie.PUBLIC


def test_legislators_are_not_in_a_chain_they_do_not_answer_to(sl: Slice) -> None:
    # Rayburn answers to the House and Wheeler to the Senate; both sit under usa.
    assert tie(sl.state, sl.entity("stark"), sl.entity("rayburn")) is Tie.PUBLIC
    assert tie(sl.state, sl.entity("roosevelt"), sl.entity("wheeler")) is Tie.PUBLIC


def test_a_foreign_head_is_reached_by_cable_or_courier_when_the_sender_may(sl: Slice) -> None:
    state, head = _with_head(sl)
    fdr = sl.entity("roosevelt")
    assert tie(state, fdr, head) is Tie.HEAD
    assert channels_to(state, fdr, head) == (ChannelKind.CABLE, ChannelKind.COURIER)
    assert takes_meeting(state, fdr, head)


def test_a_sender_who_may_not_address_a_head_reaches_none(sl: Slice) -> None:
    state, head = _with_head(sl)
    stark = sl.entity("stark")
    assert tie(state, stark, head) is Tie.HEAD
    assert channels_to(state, stark, head) == ()
    assert not takes_meeting(state, stark, head)


def test_a_head_at_home_is_not_a_foreign_head(sl: Slice) -> None:
    state, head = _with_head(sl)
    fdr = sl.entity("roosevelt")
    polity_home = state.model_copy(
        update={
            "entities": {
                **state.entities,
                head: state.entities[head].model_copy(update={"parent": sl.entity("usa")}),
            }
        }
    )
    assert tie(polity_home, fdr, head) is Tie.PUBLIC


def test_a_rank_five_caller_is_taken_by_a_rank_two_legislator_in_every_seed(sl: Slice) -> None:
    fdr, wheeler = sl.entity("roosevelt"), sl.entity("wheeler")
    for seed in SEEDS:
        state = sl.state.model_copy(update={"campaign_id": CampaignId(seed)})
        assert takes_meeting(state, fdr, wheeler, seed), seed


def test_a_meeting_gives_the_same_answer_for_the_same_state_and_parts(sl: Slice) -> None:
    fdr, wheeler = sl.entity("roosevelt"), sl.entity("wheeler")
    clerk = _clerk(sl)
    for who in (clerk, fdr):
        first = takes_meeting(sl.state, who, wheeler, "ask", 1)
        assert all(takes_meeting(sl.state, who, wheeler, "ask", 1) == first for _ in range(3))


def test_every_channel_has_an_exposure_and_a_transit_time() -> None:
    assert set(EXPOSURE) == set(ChannelKind)
    assert set(TRANSIT_DAYS) == set(ChannelKind)
    assert all(0 <= v <= 3 for v in EXPOSURE.values())
    assert {c: transit_days(c) for c in ChannelKind} == TRANSIT_DAYS
    assert transit_days(ChannelKind.COURIER) == 5


def test_an_unknown_entity_raises_key_error(sl: Slice) -> None:
    ghost = EntityId(derived_id(CAMPAIGN, "entity", "ghost"))
    with pytest.raises(KeyError):
        tie(sl.state, sl.entity("roosevelt"), ghost)
    with pytest.raises(KeyError):
        tie(sl.state, ghost, sl.entity("roosevelt"))
    with pytest.raises(KeyError):
        takes_meeting(sl.state, ghost, sl.entity("wheeler"))
