"""The character rule in code (spec §5.5): who may be offered a character."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, SeatId, derived_id
from revisionist.core.ontology import AssetKind, AssetStatus, Character, CharacterSide, EntityKind
from revisionist.core.realism.card import CardPath
from revisionist.core.roster import claimable, nearest, problems, qualifies
from revisionist.core.state import State
from revisionist.core.world import AssetDecl, CharacterDecl, EntityDecl, WorldFile
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import session_zero
from revisionist.engine.session_zero import StepRefusedError
from revisionist.engine.store import MemoryStore, load_state
from tests import fixtures as fx

SALT_STRAIT = Path(__file__).resolve().parents[1] / "worlds" / "salt-strait.yaml"
WAR = {
    "key": "war",
    "kind": "rivalry",
    "name": "War",
    "prize": "the strait",
    "sides": ["varda", "ostrel"],
    "countdown_days": 30,
}


def _state(
    *,
    assets: tuple[AssetDecl, ...] = (),
    people: tuple[EntityDecl, ...] = (),
    contests: bool = True,
) -> State:
    raw: dict[str, object] = yaml.safe_load(SALT_STRAIT.read_text())
    raw["start_date"] = "1500-03-01"
    raw["contests"] = [WAR] if contests else []
    world = WorldFile.model_validate(raw)
    world = world.model_copy(
        update={
            "assets": (*world.assets, *assets),
            "entities": (*world.entities, *people),
        }
    )
    return replay(compile_world(world, fx.CAMPAIGN, fx.VERSIONS))


def _force(key: str, controller: str, tier: int = 2) -> AssetDecl:
    return AssetDecl(key=key, kind=AssetKind.FORCE, name=key, tier=tier, controller=controller)


def _id(state: State, name: str) -> EntityId:
    return next(e.entity_id for e in state.entities.values() if e.name == name)


def _roster(state: State, *names: str, claimed: tuple[str, ...] = ()) -> State:
    chars = {}
    for name in names:
        who = _id(state, name)
        claimed_by = SeatId("seat-claiming") if name in claimed else None
        chars[who] = Character(
            entity_id=who, pitch="p", reach="r", composite=False, claimed_by=claimed_by
        )
    return state.model_copy(update={"roster": chars})


def test_a_tier_two_force_under_a_side_qualifies() -> None:
    state = _state(assets=(_force("aske_host", "general_aske"),))
    assert qualifies(state, _id(state, "General Aske"))


def test_money_information_and_facilities_alone_do_not_qualify() -> None:
    assets = tuple(
        AssetDecl(key=f"mira_{k.value}", kind=k, name=k.value, tier=3, controller="mira")
        for k in (AssetKind.WEALTH, AssetKind.INFO, AssetKind.FACILITY)
    )
    state = _state(assets=assets)
    assert not qualifies(state, _id(state, "Mira Toll"))


def test_tier_one_does_not_qualify() -> None:
    state = _state(assets=(_force("aske_band", "general_aske", tier=1),))
    assert not qualifies(state, _id(state, "General Aske"))


def test_a_lost_asset_does_not_qualify() -> None:
    state = _state(assets=(_force("aske_host", "general_aske"),))
    host = next(a for a in state.assets.values() if a.name == "aske_host")
    lost = host.model_copy(update={"status": AssetStatus.LOST})
    state = state.model_copy(update={"assets": {host.asset_id: lost}})
    assert not qualifies(state, _id(state, "General Aske"))


def test_a_person_outside_every_contest_does_not_qualify() -> None:
    state = _state(assets=(_force("abbess_host", "abbess_ren"),))
    assert not qualifies(state, _id(state, "Abbess Ren"))


def test_with_no_contests_any_person_with_such_an_asset_qualifies() -> None:
    state = _state(assets=(_force("abbess_host", "abbess_ren"),), contests=False)
    assert not state.contests
    assert qualifies(state, _id(state, "Abbess Ren"))
    assert not qualifies(state, _id(state, "Mira Toll"))


def test_nearest_prefers_the_same_parent() -> None:
    teo = EntityDecl(key="teo", kind=EntityKind.PERSON, name="Lord Teo", parent="ostrel")
    state = _state(
        assets=(
            _force("aske_host", "general_aske"),
            _force("teo_host", "teo"),
            _force("m", "mira"),
        ),
        people=(teo,),
    )
    state = _roster(state, "General Aske", "Lord Teo", "Mira Toll")
    assert nearest(state, _id(state, "General Aske")) == _id(state, "Lord Teo")


def test_nearest_falls_back_to_a_shared_contest() -> None:
    state = _state(assets=(_force("aske_host", "general_aske"), _force("m", "mira")))
    state = _roster(state, "General Aske", "Mira Toll")
    assert nearest(state, _id(state, "Mira Toll")) == _id(state, "General Aske")


def test_nearest_skips_the_claimed_and_returns_none_when_no_one_qualifies() -> None:
    teo = EntityDecl(key="teo", kind=EntityKind.PERSON, name="Lord Teo", parent="ostrel")
    state = _state(
        assets=(
            _force("aske_host", "general_aske"),
            _force("teo_host", "teo"),
            _force("m", "mira"),
        ),
        people=(teo,),
    )
    state = _roster(state, "General Aske", "Lord Teo", "Mira Toll", claimed=("General Aske",))
    assert nearest(state, _id(state, "Lord Teo")) == _id(state, "Mira Toll")
    assert nearest(state, _id(state, "Mira Toll")) == _id(state, "Lord Teo")
    empty = _roster(state, "Mira Toll", "Abbess Ren")
    assert nearest(empty, _id(empty, "Mira Toll")) is None


def test_nearest_for_an_unknown_entity_is_the_first_qualified_by_name() -> None:
    state = _state(assets=(_force("aske_host", "general_aske"), _force("m", "mira")))
    state = _roster(state, "Mira Toll", "General Aske")
    assert nearest(state, EntityId("nobody")) == _id(state, "General Aske")


def test_problems_name_each_character_who_fails_in_name_order() -> None:
    state = _state(assets=(_force("aske_host", "general_aske"),))
    state = _roster(state, "Mira Toll", "General Aske", "Abbess Ren")
    assert problems(state) == [
        "character Abbess Ren: controls no force, office or network of tier 2+ in a contest",
        "character Mira Toll: controls no force, office or network of tier 2+ in a contest",
    ]


def test_problems_are_empty_without_contests() -> None:
    state = _state(contests=False)
    state = _roster(state, "Mira Toll")
    assert problems(state) == []


def _declared(state: State, name: str, side: str | None) -> State:
    who = _id(state, name)
    contest_id = next(iter(state.contests))
    sides = (CharacterSide(contest_id=contest_id, side=_id(state, side)),) if side else ()
    char = Character(entity_id=who, pitch="p", reach="r", composite=False, sides=sides)
    return state.model_copy(update={"roster": {who: char}})


def test_a_declared_side_counts_for_a_person_under_no_side() -> None:
    gov = EntityDecl(key="gov", kind=EntityKind.PERSON, name="Governor Border")
    state = _state(
        assets=(
            AssetDecl(key="gov_office", kind=AssetKind.OFFICE, name="o", tier=3, controller="gov"),
        ),
        people=(gov,),
    )
    assert not qualifies(_declared(state, "Governor Border", None), _id(state, "Governor Border"))
    declared = _declared(state, "Governor Border", "Varda")
    assert qualifies(declared, _id(state, "Governor Border"))
    assert problems(declared) == []


def test_a_declared_side_still_needs_a_qualifying_asset() -> None:
    gov = EntityDecl(key="gov", kind=EntityKind.PERSON, name="Governor Border")
    state = _state(
        assets=(
            AssetDecl(key="gov_ledger", kind=AssetKind.WEALTH, name="w", tier=4, controller="gov"),
        ),
        people=(gov,),
    )
    assert not qualifies(
        _declared(state, "Governor Border", "Varda"), _id(state, "Governor Border")
    )


# --- who can be claimed -----------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
CLAIM_CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
FIRST = SeatId(derived_id(CLAIM_CAMPAIGN, "seat", "first"))
LATER = SeatId(derived_id(CLAIM_CAMPAIGN, "seat", "later"))


def _legacy_with_contest() -> list[ev.Event]:
    """Legacy Salt Strait in a contest, every seat run by code so Session Zero can open.
    General Aske meets the character rule; Mira Toll's
    force is cut to tier 1 after the world compiled, so she no longer does."""
    raw: dict[str, Any] = yaml.safe_load(SALT_STRAIT.read_text())
    raw.update(
        seats=[{**s, "controller": "ai"} for s in raw["seats"]],
        goals=[],
        start="The Salt Strait, spring 1500",
        start_date="1500-03-01",
        contests=[WAR],
        roster=[
            {"entity": k, "pitch": "p", "reach": "r", "composite": True}
            for k in ("general_aske", "mira", "teo")
        ],
    )
    raw["entities"].append({"key": "teo", "kind": "person", "name": "Lord Teo", "parent": "ostrel"})
    world = WorldFile.model_validate(raw)
    forces = tuple(_force(f"{k}_host", k) for k in ("general_aske", "mira", "teo"))
    world = world.model_copy(update={"assets": (*world.assets, *forces)})
    return [_cut(e) for e in compile_world(world, CLAIM_CAMPAIGN, cmp.versions())]


def _cut(e: ev.Event) -> ev.Event:
    if isinstance(e.payload, ev.AssetCreated) and e.payload.asset.name == "mira_host":
        asset = e.payload.asset.model_copy(update={"tier": 1})
        return e.model_copy(update={"payload": e.payload.model_copy(update={"asset": asset})})
    return e


def _toy_with_an_uncarded_person() -> list[ev.Event]:
    """The toy world with a third roster person whose card is built only when picked."""
    world = cmp.load_world(ROOT / "tests" / "worlds" / "territory-toy.yaml")
    petra = EntityDecl(key="petra", kind=EntityKind.PERSON, name="Petra Holm", parent="norra")
    listed = CharacterDecl(entity="petra", pitch="p", reach="r", composite=True)
    world = world.model_copy(
        update={"entities": (*world.entities, petra), "roster": (*world.roster, listed)}
    )
    return compile_world(world, CLAIM_CAMPAIGN, cmp.versions())


def _shipped(path: str) -> Callable[[], list[ev.Event]]:
    return lambda: compile_world(cmp.load_world(ROOT / path), CLAIM_CAMPAIGN, cmp.versions())


WORLDS: dict[str, Callable[[], list[ev.Event]]] = {
    "autumn-1941": _shipped("worlds/autumn-1941.yaml"),
    "salt-strait-realism": _shipped("worlds/salt-strait-realism.yaml"),
    "territory-toy": _shipped("tests/worlds/territory-toy.yaml"),
    "toy-uncarded": _toy_with_an_uncarded_person,
    "legacy-contest": _legacy_with_contest,
}


def _compiled(world: str) -> State:
    store = MemoryStore()
    store.append_all(WORLDS[world]())
    return load_state(store, CLAIM_CAMPAIGN)


def _opened(world: str) -> MemoryStore:
    """The world in Session Zero with its first roster person, by name, already taken."""
    store = MemoryStore()
    store.append_all(WORLDS[world]())
    state = load_state(store, CLAIM_CAMPAIGN)
    first = min(state.roster, key=lambda c: state.entities[c].name)
    session_zero.claim(store, CLAIM_CAMPAIGN, FIRST, state.entities[first].name)
    return store


def _copy(store: MemoryStore) -> MemoryStore:
    again = MemoryStore()
    again.append_all(list(store.read(CLAIM_CAMPAIGN)))
    return again


def _claim_accepts(store: MemoryStore, name: str) -> bool:
    try:
        session_zero.claim(_copy(store), CLAIM_CAMPAIGN, LATER, name)
    except StepRefusedError:
        return False
    return True


@pytest.mark.parametrize("world", sorted(WORLDS))
def test_claimable_is_the_set_the_claim_accepts_person_by_person(world: str) -> None:
    store = _opened(world)
    state = load_state(store, CLAIM_CAMPAIGN)
    listed = {c.person: c for c in claimable(state)}
    assert set(listed) == set(state.roster)
    for person, candidate in listed.items():
        accepted = _claim_accepts(store, state.entities[person].name)
        assert (candidate.reason is None) == accepted, (world, candidate)
    assert any(c.taken for c in listed.values())
    assert sum(c.reason is None for c in listed.values()) >= 1


def test_a_taken_person_is_listed_as_taken_with_the_reason() -> None:
    state = load_state(_opened("territory-toy"), CLAIM_CAMPAIGN)
    by_name = {c.name: c for c in claimable(state)}
    assert by_name["Ilse Varg"].taken
    assert by_name["Ilse Varg"].reason == "Ilse Varg is already taken."
    assert not by_name["Tomas Brand"].taken
    assert by_name["Tomas Brand"].reason is None


def test_a_person_who_fails_the_character_rule_says_why() -> None:
    by_name = {c.name: c for c in claimable(_compiled("legacy-contest"))}
    assert by_name["General Aske"].reason is None
    assert by_name["Mira Toll"].reason == (
        "Mira Toll does not meet the character rule: a playable character needs a force, "
        "office or network of tier 2 or more in one of the world's contests."
    )
    assert by_name["Mira Toll"].office == "" and by_name["Mira Toll"].path is None


def test_a_person_with_no_card_yet_says_why() -> None:
    by_name = {c.name: c for c in claimable(_compiled("toy-uncarded"))}
    assert by_name["Petra Holm"].reason == "Petra Holm is not ready to be played yet."
    assert by_name["Petra Holm"].nation == by_name["Ilse Varg"].nation


def test_a_card_not_marked_playable_is_not_claimable() -> None:
    state = _compiled("territory-toy")
    tomas = _id(state, "Tomas Brand")
    card = state.cards[tomas].model_copy(update={"playable": False})
    state = state.model_copy(update={"cards": {**state.cards, tomas: card}})
    by_name = {c.name: c for c in claimable(state)}
    assert by_name["Tomas Brand"].reason == "Tomas Brand is not ready to be played yet."


def test_each_candidate_carries_nation_path_office_and_pitch() -> None:
    state = _compiled("autumn-1941")
    by_name = {c.name: c for c in claimable(state)}
    churchill = by_name["Winston Churchill"]
    assert state.entities[churchill.nation].name == "United Kingdom"  # type: ignore[index]
    assert churchill.path is CardPath.POLITICAL
    assert churchill.office == state.cards[churchill.person].office
    assert churchill.pitch == state.roster[churchill.person].pitch
    assert not churchill.taken and churchill.reason is None
    king = by_name["Ernest J. King"]
    assert king.path is CardPath.MILITARY
    assert state.entities[king.nation].name == "United States"  # type: ignore[index]
    assert [c.name for c in claimable(state)] == sorted(by_name)


def test_claimable_is_the_same_for_every_call_and_leaves_the_state_alone() -> None:
    state = load_state(_opened("salt-strait-realism"), CLAIM_CAMPAIGN)
    before = state.model_dump_json()
    assert claimable(state) == claimable(state)
    assert state.model_dump_json() == before
