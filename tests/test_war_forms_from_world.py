"""The war rules read which check a form takes from the world, not from its name (WRL).

In a territory game a form whose rule is ``war`` takes the declaration of war checks; a
``movement`` form with a ``strength`` takes the fleet detachment check; a choice the world
marks ``needs_war`` takes the shoot-on-sight check against the nation it names. A toy world
whose forms have other names gets the same refusals, word for word, as 1941's. A stored game
(no territory rules) keeps the checks it had by name.
"""

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.fold import apply, replay
from revisionist.core.ids import CampaignId, EntityId, EventId, FeatureId, SeatId, derived_id
from revisionist.core.realism import territory, war_rules
from revisionist.core.realism.card import ParamSpec
from revisionist.core.realism.geography import Feature, FeatureKind
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, compile_world, object_id, resolve_keys
from revisionist.engine import campaign as cmp
from tests.test_realism_resolvers import Rig

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
TOY = Path(__file__).parent / "worlds" / "territory-toy.yaml"
DAY = date(1900, 4, 2)
RAM = "so the galleys cannot be ordered to ram Ostmark's ships on sight."

LEVERS: list[dict[str, Any]] = [
    {
        "name": "proclaim_war",
        "pipeline": "norra_order",
        "resolver": "war",
        "params": [{"name": "target", "kind": "enum", "choices": ["sudland", "ostmark"]}],
    },
    {
        "name": "split_squadron",
        "pipeline": "norra_order",
        "resolver": "movement",
        "params": [
            {"name": "force", "kind": "enum", "choices": ["norra_levy"]},
            {"name": "to", "kind": "enum", "choices": ["norrhavn"]},
            {"name": "strength", "kind": "int", "lo": 1, "hi": 4},
        ],
    },
    {
        "name": "galley_orders",
        "pipeline": "norra_order",
        "resolver": "shipping",
        "params": [
            {
                "name": "stance",
                "kind": "enum",
                "choices": ["spare_them", "ram_on_sight"],
                "needs_war": {"ram_on_sight": {"nation": "ostmark", "refusal": RAM}},
            },
            {"name": "waters", "kind": "enum", "choices": ["the_gulf"]},
        ],
    },
    {
        "name": "galley_drill",
        "pipeline": "norra_order",
        "resolver": "shipping",
        "params": [
            {"name": "stance", "kind": "enum", "choices": ["spare_them", "ram_on_sight"]},
            {"name": "waters", "kind": "enum", "choices": ["the_gulf"]},
        ],
    },
]
"""Ilse's forms: a declaration, a detachment and two galley orders, one of which the world
marks as needing a war with Ostmark. No name is one of 1941's."""


def toy_raw(levers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(TOY.read_text())
    raw["rules"] = ["territories"]
    raw["entities"].append({"key": "ostmark", "kind": "polity", "name": "Ostmark"})
    raw["pipelines"] = [
        {
            "key": "norra_order",
            "name": "An order through the chancery",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "clerical", "days": 1}],
        }
    ]
    ilse = next(c for c in raw["cards"] if c["person"] == "ilse")
    ilse["pipelines"] = ["norra_order"]
    ilse["levers"] = LEVERS if levers is None else levers
    return raw


def toy(raw: dict[str, Any] | None = None) -> WorldFile:
    world = WorldFile.model_validate(toy_raw() if raw is None else raw)
    return world.model_copy(update={"map_data": cmp.load_world(TOY).map_data})


class Toy:
    """The toy world compiled with Ilse seated, folded event by event."""

    def __init__(self, world: WorldFile | None = None) -> None:
        world = toy() if world is None else world
        self.ids = resolve_keys(world, CAMPAIGN)
        events = compile_world(world, CAMPAIGN, cmp.versions())
        self.state: State = replay(events)
        self.seq = len(events)
        self.seat = SeatId(derived_id(CAMPAIGN, "seat", "ilse"))
        self.add(ev.CharacterClaimed(seat_id=self.seat, entity_id=self.entity("ilse")))
        self.add(ev.SessionZeroClosed())

    def entity(self, key: str) -> EntityId:
        return EntityId(self.ids[key])

    def add(self, payload: ev.Payload) -> None:
        event = ev.Event(
            event_id=EventId(derived_id(CAMPAIGN, "test-event", self.seq)),
            campaign_id=CAMPAIGN,
            seq=self.seq,
            tick=0,
            scope=PUBLIC,
            payload=payload,
            versions=cmp.versions(),
        )
        self.seq += 1
        self.state = apply(self.state, event)

    def war_with(self, key: str) -> None:
        a, b = self.entity("norra"), self.entity(key)
        war = War(war_id=war_id_for(a, b), a=a, b=b, since=DAY, declared_by=self.entity("ilse"))
        self.add(ev.WarDeclared(war=war))

    def force(self, key: str, kind: FeatureKind, tier: int) -> None:
        """A force of Norra's at Norrhavn: a fleet or an army, as a stored-games force."""
        self.add(
            ev.FeatureSet(
                feature=Feature(
                    feature_id=FeatureId(object_id(CAMPAIGN, "feature", key)),
                    kind=kind,
                    name=f"The Norra {key.split('_')[-1].title()}",
                    side=self.entity("norra"),
                    tier=tier,
                    places=(self.entity("norrhavn"),),
                    as_of=DAY,
                )
            )
        )

    def refusal(self, lever: str, **params: str) -> str:
        return war_rules.order_refusal(self.state, self.seat, lever, params)


def test_the_toy_is_a_territory_game() -> None:
    assert territory.on(Toy().state)


# --- the declaration of war checks ---------------------------------------------------------


def test_a_war_form_of_another_name_takes_the_declaration_checks() -> None:
    t = Toy()
    assert t.refusal("proclaim_war", target="sudland") == "Norra is already at war with Sudland."
    assert t.refusal("proclaim_war", target="norra") == "Norra cannot declare war on itself."
    assert t.refusal("proclaim_war", target="norrhavn") == (
        "Norrhavn is not a power to declare war on."
    )
    assert t.refusal("proclaim_war", target="ostmark") == ""
    t.war_with("ostmark")
    assert t.refusal("proclaim_war", target="ostmark") == "Norra is already at war with Ostmark."


def test_a_form_named_declare_war_that_is_not_a_war_form_takes_no_declaration_check() -> None:
    levers = [{**LEVERS[3], "name": "declare_war"}]
    t = Toy(toy(toy_raw(levers)))
    assert t.refusal("declare_war", target="sudland") == ""


# --- the fleet detachment check -----------------------------------------------------------


def test_a_movement_form_with_a_strength_takes_the_detachment_check() -> None:
    t = Toy()
    t.force("norra_squadron", FeatureKind.FLEET, 2)
    t.force("norra_host", FeatureKind.ARMY, 3)
    detach = "split_squadron"
    assert t.refusal(detach, force="norra_squadron", to="norrhavn", strength="1") == ""
    assert t.refusal(detach, force="norra_squadron", to="norrhavn", strength="2") == (
        "The Norra Squadron has strength 2, so at most 1 of it can be detached."
    )
    assert t.refusal(detach, force="norra_host", to="norrhavn", strength="1") == (
        "No side may detach part of an army."
    )


def test_a_form_named_detach_fleet_without_a_strength_takes_no_detachment_check() -> None:
    plain = {**LEVERS[1], "name": "detach_fleet", "params": LEVERS[1]["params"][:2]}
    t = Toy(toy(toy_raw([plain])))
    t.force("norra_host", FeatureKind.ARMY, 3)
    assert t.refusal("detach_fleet", force="norra_host", to="norrhavn", strength="1") == ""


# --- the shoot-on-sight check -------------------------------------------------------------


def test_a_choice_the_world_marks_needs_the_war_it_names() -> None:
    t = Toy()
    text = t.refusal("galley_orders", stance="ram_on_sight", waters="the_gulf")
    assert text == f"Norra is not at war with Ostmark, {RAM}"
    assert t.refusal("galley_orders", stance="spare_them", waters="the_gulf") == ""
    t.war_with("ostmark")
    assert t.refusal("galley_orders", stance="ram_on_sight", waters="the_gulf") == ""


def test_a_form_the_world_marks_with_no_check_is_not_refused() -> None:
    t = Toy()
    assert t.refusal("galley_drill", stance="ram_on_sight", waters="the_gulf") == ""


def test_a_form_named_uboat_directive_with_no_mark_is_not_refused() -> None:
    levers = [{**LEVERS[3], "name": "uboat_directive"}]
    t = Toy(toy(toy_raw(levers)))
    assert t.refusal("uboat_directive", stance="attack_us_shipping", waters="the_gulf") == ""
    assert t.refusal("uboat_directive", posture="attack_us_shipping") == ""


def test_a_mark_naming_no_nation_of_the_world_is_refused_at_compile() -> None:
    galley = LEVERS[2]
    stance = {
        **galley["params"][0],
        "needs_war": {"ram_on_sight": {"nation": "usa", "refusal": RAM}},
    }
    lever = {**galley, "params": [stance, galley["params"][1]]}
    with pytest.raises(WorldError) as caught:
        compile_world(toy(toy_raw([lever])), CAMPAIGN, cmp.versions())
    assert any("needs_war" in p and "usa is not a nation" in p for p in caught.value.problems)
    stance["needs_war"] = {"ram_on_sight": {"nation": "norrhavn", "refusal": RAM}}
    with pytest.raises(WorldError) as caught:
        compile_world(toy(toy_raw([lever])), CAMPAIGN, cmp.versions())
    assert any("norrhavn is not a nation" in p for p in caught.value.problems)


@pytest.mark.parametrize(
    "spec",
    [
        {"kind": "enum", "choices": ["a"], "needs_war": {"b": {"nation": "x", "refusal": "so."}}},
        {"kind": "int", "lo": 1, "hi": 2, "needs_war": {"a": {"nation": "x", "refusal": "so."}}},
        {"kind": "enum", "choices": ["a"], "needs_war": {"a": {"nation": "x", "refusal": ""}}},
    ],
)
def test_a_mark_on_no_choice_of_the_form_is_refused(spec: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ParamSpec.model_validate({"name": "stance", **spec})


def test_a_spec_without_a_mark_dumps_as_before() -> None:
    spec = ParamSpec.model_validate({"name": "stance", "kind": "enum", "choices": ["a"]})
    assert "needs_war" not in spec.model_dump(mode="json")


# --- 1941, a territory game: the same words as before --------------------------------------


def test_1941_marks_attack_us_shipping_as_needing_the_war_with_the_united_states() -> None:
    world = cmp.load_world(cmp.world_path("autumn-1941"))
    hitler = next(c for c in world.cards if c.person == "hitler")
    lever = next(lv for lv in hitler.levers if lv.resolver == "shipping" and lv.params)
    marks = {p.name: p.needs_war for p in lever.params if p.needs_war}
    assert {k: {c: n.nation for c, n in v.items()} for k, v in marks.items()} == {
        "posture": {"attack_us_shipping": "usa"}
    }


def test_1941_refusals_are_word_for_word_as_before() -> None:
    r = Rig()
    assert territory.on(r.state)
    hitler = r.seat("hitler")
    r.close_session_zero()
    shoot = {"posture": "attack_us_shipping", "theatre": "north_atlantic"}
    text = war_rules.order_refusal(r.state, hitler, "uboat_directive", shoot)
    assert text == (
        "Germany is not at war with United States, "
        "so the U-boats cannot be ordered to attack American ships on sight."
    )
    spare = {"posture": "unrestricted_atlantic", "theatre": "north_atlantic"}
    assert war_rules.order_refusal(r.state, hitler, "uboat_directive", spare) == ""
    assert war_rules.order_refusal(r.state, hitler, "declare_war", {"target": "usa"}) == ""
    a, b = EntityId(r.ids["germany"]), EntityId(r.ids["usa"])
    war = War(war_id=war_id_for(a, b), a=a, b=b, since=date(1941, 9, 2), declared_by=a)
    r.add(ev.WarDeclared(war=war))
    assert war_rules.order_refusal(r.state, hitler, "uboat_directive", shoot) == ""
    assert war_rules.order_refusal(r.state, hitler, "declare_war", {"target": "usa"}) == (
        "Germany is already at war with United States."
    )
