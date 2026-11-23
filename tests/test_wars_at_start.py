"""Wars in force at the start, and the rules switch.

A world file may name the wars already under way on its start date and the rules of
the territory game it switches on. A world, or a stored game, that names no rules has
none switched on.
"""

from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, SeatId, derived_id
from revisionist.core.realism import war_rules
from revisionist.core.realism.war import War, at_war, war_id_for
from revisionist.core.state import Rule, State
from revisionist.core.world import WarDecl, WorldFile
from revisionist.core.world_compile import WorldError, compile_world, resolve_keys
from revisionist.engine import campaign as cmp

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
TOY = Path(__file__).parent / "worlds" / "territory-toy.yaml"
POINTS = str(Path(__file__).parent / "worlds" / "autumn-1941-points.yaml")
RECORDING = Path(__file__).parent / "recordings" / "legacy-salt-strait.jsonl"


def toy(**changes: object) -> WorldFile:
    """The territory toy world, with top-level keys replaced, and its map file."""
    raw = yaml.safe_load(TOY.read_text())
    raw.update(changes)
    world = WorldFile.model_validate(raw)
    return world.model_copy(update={"map_data": cmp.load_world(TOY).map_data})


def created(world: WorldFile) -> tuple[list[ev.Event], State]:
    events = compile_world(world, CAMPAIGN, cmp.versions())
    return events, replay(events)


def entity(key: str) -> EntityId:
    return EntityId(resolve_keys(cmp.load_world(TOY), CAMPAIGN)[key])


def test_a_war_in_the_world_file_is_in_force_at_creation() -> None:
    events, state = created(cmp.load_world(TOY))
    norra, sudland = entity("norra"), entity("sudland")
    wars = [e.payload for e in events if isinstance(e.payload, ev.WarDeclared)]
    assert [w.war for w in wars] == [
        War(
            war_id=war_id_for(norra, sudland),
            a=norra,
            b=sudland,
            since=date(1900, 3, 1),
            declared_by=norra,
        )
    ]
    assert all(e.tick == 0 for e in events)
    assert at_war(state, sudland, norra)
    assert state.wars[war_id_for(norra, sudland)].declared is True


def test_an_undeclared_war_is_still_a_war() -> None:
    war = {"a": "norra", "b": "sudland", "since": "1900-03-01", "declared": False, "gap": True}
    _, state = created(toy(wars=[war]))
    norra, sudland = entity("norra"), entity("sudland")
    assert at_war(state, norra, sudland)
    assert state.wars[war_id_for(norra, sudland)].declared is False


def test_a_world_with_no_wars_starts_at_peace() -> None:
    events, state = created(toy(wars=[]))
    assert state.wars == {}
    assert not [e for e in events if isinstance(e.payload, ev.WarDeclared)]


def test_the_rules_named_in_the_world_are_switched_on() -> None:
    events, state = created(toy(rules=["territories", "holders"]))
    assert state.rules == frozenset({Rule.TERRITORIES, Rule.HOLDERS})
    first = events[0].payload
    assert isinstance(first, ev.CampaignCreated)
    assert first.rules == frozenset({Rule.TERRITORIES, Rule.HOLDERS})
    assert first.model_dump(mode="json")["rules"] == ["holders", "territories"]


def test_no_rules_named_means_none_switched_on() -> None:
    _, state = created(cmp.load_world(TOY))
    assert state.rules == frozenset()
    without_key = WorldFile.model_validate(
        {k: v for k, v in yaml.safe_load(TOY.read_text()).items() if k != "rules"}
    ).model_copy(update={"map_data": cmp.load_world(TOY).map_data})
    events, state = created(without_key)
    assert state.rules == frozenset()
    assert "rules" not in events[0].payload.model_dump(mode="json")
    _, shipped = created(cmp.load_world(cmp.world_path(POINTS)))
    assert shipped.rules == frozenset()


def test_the_fixed_list_of_rule_names() -> None:
    assert [r.value for r in Rule] == [
        "territories",
        "holders",
        "economy",
        "supply",
        "fuel",
        "battles",
        "reports",
        "groups",
        "agreements",
        "conference",
        "contests",
        "aims",
        "aid",
        "writing",
        "clause_reader",
        "written_orders",
        "command",
        "locks",
        "laws",
        "ask_answers",
        "deciders",
        "own_aim",
        "offers",
        "classes",
        "losses",
        "places",
        "posts",
        "office",
        "elections",
        "defiance",
        "aide_note",
        "peace",
        "post_view",
        "playable_rule",
    ]


def test_an_unknown_rule_name_is_refused_at_load(tmp_path: Path) -> None:
    raw = yaml.safe_load(TOY.read_text())
    raw["rules"] = ["territories", "teleport"]
    path = tmp_path / "territory-toy.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValidationError) as caught:
        cmp.load_world(path)
    (problem,) = caught.value.errors()
    assert problem["loc"] == ("rules", 1)
    assert problem["type"] == "enum"


def test_no_shipped_world_switches_on_a_rule_read_by_a_model() -> None:
    for path in sorted(cmp.WORLDS_DIR.glob("*.yaml")):
        world = cmp.load_world(path)
        assert not {Rule.WRITING, Rule.CLAUSE_READER, Rule.WRITTEN_ORDERS} & set(world.rules)


def test_a_stored_game_replays_with_no_rules_and_dumps_as_before() -> None:
    stored = ev.CampaignCreated(name="Old", world="realism-toy", ruleset="realism")
    assert stored.model_dump(mode="json") == {
        "kind": "campaign_created",
        "name": "Old",
        "world": "realism-toy",
        "ruleset": "realism",
    }
    old_war = {
        "war_id": "a|b",
        "a": "a",
        "b": "b",
        "since": "1941-12-08",
        "declared_by": "p",
    }
    war = War.model_validate(old_war)
    assert war.declared is True
    assert war.model_dump(mode="json") == old_war
    fresh = State(campaign_id=CAMPAIGN)
    assert fresh.rules == frozenset()
    assert "rules" not in fresh.model_dump(mode="json")
    lines = RECORDING.read_text().splitlines()
    replayed = replay(ev.Event.model_validate_json(line) for line in lines if line)
    assert replayed.rules == frozenset()
    assert "rules" not in replayed.model_dump(mode="json")


def test_the_same_pair_twice_is_refused_with_a_reason() -> None:
    wars = [
        {"a": "norra", "b": "sudland", "since": "1900-03-01", "source": "toy"},
        {"a": "sudland", "b": "norra", "since": "1900-03-02", "source": "toy"},
    ]
    with pytest.raises(WorldError) as caught:
        compile_world(toy(wars=wars), CAMPAIGN, cmp.versions())
    assert caught.value.problems == ("war sudland-norra: Sudland and Norra are already at war",)


@pytest.mark.parametrize(
    ("war", "problem"),
    [
        ({"a": "norra", "b": "norra"}, "war norra-norra: a power cannot be at war with itself"),
        ({"a": "norra", "b": "ilse"}, "war norra-ilse: ilse is not a polity"),
        ({"a": "norra", "b": "nowhere"}, "war norra-nowhere: unknown entity nowhere"),
        ({"a": "norra", "b": "sudland", "source": "tox"}, "war norra-sudland: unknown source tox"),
        (
            {"a": "norra", "b": "sudland", "since": "1900-04-03"},
            "war norra-sudland: begins after the start date",
        ),
    ],
)
def test_a_bad_war_is_refused(war: dict[str, str], problem: str) -> None:
    decl = {"since": "1900-03-01", "source": "toy", **war}
    with pytest.raises(WorldError) as caught:
        compile_world(toy(wars=[decl]), CAMPAIGN, cmp.versions())
    assert problem in caught.value.problems


def test_a_rule_named_twice_is_refused() -> None:
    with pytest.raises(WorldError) as caught:
        compile_world(toy(rules=["battles", "battles"]), CAMPAIGN, cmp.versions())
    assert caught.value.problems == ("rules: a rule is named twice",)


def test_only_a_realism_world_has_wars_or_rules() -> None:
    world = cmp.load_world(cmp.world_path("salt-strait"))
    polities = [e.key for e in world.entities if e.kind.value == "polity"][:2]
    war = WarDecl(a=polities[0], b=polities[1], since=date(1900, 1, 1), gap=True)
    legacy = world.model_copy(update={"wars": (war,), "rules": (Rule.TERRITORIES,)})
    with pytest.raises(WorldError) as caught:
        compile_world(legacy, CAMPAIGN, cmp.versions())
    assert "wars: only a realism world has wars" in caught.value.problems
    assert "rules: only a realism world has rules" in caught.value.problems


def test_a_declaration_on_a_power_already_at_war_from_the_start_is_refused() -> None:
    events, _ = created(cmp.load_world(TOY))
    seat = SeatId(derived_id(CAMPAIGN, "seat", "ilse"))
    claim = ev.CharacterClaimed(seat_id=seat, entity_id=entity("ilse"))
    last = events[-1]
    state = replay(
        [
            *events,
            last.model_copy(
                update={
                    "seq": last.seq + 1,
                    "event_id": derived_id(CAMPAIGN, "event", str(last.seq + 1)),
                    "payload": claim,
                }
            ),
        ]
    )
    text = war_rules.order_refusal(state, seat, "declare_war", {"target": "sudland"})
    assert text == "Norra is already at war with Sudland."


def test_the_world_schema_offered_to_a_model_names_neither_key() -> None:
    props = WorldFile.model_json_schema()["properties"]
    assert "wars" not in props
    assert "rules" not in props
