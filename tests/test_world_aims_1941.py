"""1941 aims as conditions, and what moves each contest (AMC).

Autumn 1941 switches on ``contests`` and ``aims``. Each playable card gives
each of its three aims a condition over what the rules move, a success rule in plain words
and a deadline; two aims are from the post and one is marked ``replaceable``, the default
a player's own aim would replace. Each of the three contests names its moves.

A condition counts as one a rule can change when every check in it reads something a rule
of this world moves: a computed figure (a resolver writes it), a territory's holder, a
war-economy figure, a group's support that happenings move, an agreement, the regard
between two people, a war not yet begun, or a contest with moves.
"""

import copy
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core.fold import replay
from revisionist.core.goals import AimRule, leaves
from revisionist.core.ids import EntityId
from revisionist.core.state import Rule
from revisionist.core.world import CardDecl, ContestDecl
from revisionist.core.world_compile import WorldError, compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from tests.test_territory_model import CAMPAIGN

WORLD = Path(__file__).parents[1] / "worlds" / "autumn-1941.yaml"
START, SEASON_END = date(1941, 9, 1), date(1941, 12, 7)


def raw() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(WORLD.read_text())
    return doc


def playable(doc: dict[str, Any]) -> list[str]:
    return [r["entity"] for r in doc["roster"]]


def cards(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["person"]: c for c in doc["cards"]}


def _leaves(c: dict[str, Any]) -> list[dict[str, Any]]:
    if c["check"] in ("all_of", "any_of"):
        return [x for sub in c["conditions"] for x in _leaves(sub)]
    return [c]


def changeable(doc: dict[str, Any], leaf: dict[str, Any]) -> bool:
    """Whether a rule of the world can change what ``leaf`` reads."""
    rules = set(doc["rules"])
    polities = {e["key"] for e in doc["entities"] if e["kind"] == "polity"}
    territories = {t["key"] for t in doc["territories"]}
    computed = {q["key"] for q in doc["quantities"] if q.get("computed")}
    moved = {
        (g["nation"], x["key"]) for g in doc["groups"] for x in g["groups"] if x.get("moved_by")
    }
    wars = {frozenset((w["a"], w["b"])) for w in doc["wars"]}
    contests = {k["key"] for k in doc["contests"] if k.get("moves")}
    match leaf["check"]:
        case "quantity_at":
            return leaf["quantity"] in computed
        case "holds_area":
            return "holders" in rules and leaf["area"] in territories and leaf["holder"] in polities
        case "income_at":
            return "economy" in rules and leaf["nation"] in polities
        case "support_at":
            return "groups" in rules and (leaf["nation"], leaf["group"]) in moved
        case "agreement_in_force":
            return "agreements" in rules
        case "regard_at":
            return bool(leaf["a"] != leaf["b"])
        case "at_war":
            return frozenset((leaf["a"], leaf["b"])) not in wars  # no rule makes peace
        case "contest_won":
            return "contests" in rules and leaf["contest"] in contests
        case _:
            return False  # an order count, an office or a status no rule here moves


def problems(doc: dict[str, Any]) -> list[str]:
    """What breaks the item's rules for aims: each playable card's three aims each with a
    condition, a rule in plain words and a deadline in the season; exactly one replaceable;
    every check one a rule can change."""
    out: list[str] = []
    by_person = cards(doc)
    for person in playable(doc):
        card = by_person[person]
        rules = {r["aim"]: r for r in card.get("aim_rules") or []}
        for n in range(1, len(card["aims"]) + 1):
            r = rules.get(n)
            if r is None:
                out.append(f"{person} aim {n}: no condition")
                continue
            if not str(r.get("rule", "")).strip():
                out.append(f"{person} aim {n}: no rule in words")
            if not START <= r.get("deadline", date.max) <= SEASON_END:
                out.append(f"{person} aim {n}: no deadline in the season")
            out += [
                f"{person} aim {n}: no rule can change {leaf}"
                for leaf in _leaves(r["condition"])
                if not changeable(doc, leaf)
            ]
        if sum(bool(r.get("replaceable")) for r in rules.values()) != 1:
            out.append(f"{person}: not exactly one replaceable aim")
    return out


def compiled(doc: dict[str, Any]) -> Any:
    """The world with ``doc``'s cards and contests, compiled and folded."""
    w = cmp.load_world(WORLD)
    w = w.model_copy(
        update={
            "cards": tuple(CardDecl.model_validate(c) for c in doc["cards"]),
            "contests": tuple(ContestDecl.model_validate(k) for k in doc["contests"]),
        }
    )
    return replay(compile_world(w, CAMPAIGN, cmp.versions()))


# --- the rules ---------------------------------------------------------------------------


def test_the_world_switches_on_contests_and_aims() -> None:
    w = cmp.load_world(WORLD)
    assert {Rule.CONTESTS, Rule.AIMS} <= set(w.rules)


def test_every_playable_card_holds_three_aims() -> None:
    doc = raw()
    flagged = [c["person"] for c in doc["cards"] if c.get("playable")]
    assert sorted(playable(doc)) == sorted(flagged)
    assert [p for p in playable(doc) if len(cards(doc)[p]["aims"]) != 3] == []


def test_every_aim_has_a_condition_a_rule_can_change() -> None:
    assert problems(raw()) == []


def test_each_playable_card_has_exactly_one_replaceable_aim() -> None:
    doc = raw()
    for person in playable(doc):
        flagged = [r["aim"] for r in cards(doc)[person]["aim_rules"] if r.get("replaceable")]
        assert len(flagged) == 1, person


def test_every_condition_compiles_and_names_only_keys_that_exist() -> None:
    doc = raw()
    state = compiled(doc)
    ids = resolve_keys(cmp.load_world(WORLD), CAMPAIGN)
    for person in playable(doc):
        card = state.cards[EntityId(ids[person])]
        assert len(card.aim_rules) == 3 and all(isinstance(r, AimRule) for r in card.aim_rules)
        for r in card.aim_rules:
            assert r is not None and len(r.sees) == len(leaves(r.condition))


def test_a_condition_naming_an_unknown_key_does_not_compile() -> None:
    doc = raw()
    rule = cards(doc)["stalin"]["aim_rules"][0]
    rule["condition"]["conditions"][0]["area"] = "atlantis"
    with pytest.raises(WorldError, match="atlantis"):
        compiled(doc)


# --- mutants ------------------------------------------------------------------------------


def test_mutant_an_aim_with_no_condition_is_caught() -> None:
    doc = copy.deepcopy(raw())
    card = cards(doc)["konoe"]
    card["aim_rules"] = [r for r in card["aim_rules"] if r["aim"] != 2]
    assert "konoe aim 2: no condition" in problems(doc)


def test_mutant_a_condition_no_rule_can_change_is_caught() -> None:
    doc = copy.deepcopy(raw())
    rule = cards(doc)["roosevelt"]["aim_rules"][1]
    rule["condition"] = {
        "check": "quantity_at",
        "quantity": "senate_democrats",
        "op": "ge",
        "value": 60,
    }
    assert any(p.startswith("roosevelt aim 2: no rule can change") for p in problems(doc))


def test_mutant_a_war_already_begun_is_not_a_condition_a_rule_can_change() -> None:
    doc = copy.deepcopy(raw())
    rule = cards(doc)["chiang"]["aim_rules"][0]
    rule["condition"] = {"check": "at_war", "a": "japan", "b": "china"}
    assert any(p.startswith("chiang aim 1: no rule can change") for p in problems(doc))


def test_mutant_two_replaceable_aims_are_caught() -> None:
    doc = copy.deepcopy(raw())
    for r in cards(doc)["hitler"]["aim_rules"]:
        r["replaceable"] = True
    assert "hitler: not exactly one replaceable aim" in problems(doc)


# --- contests -----------------------------------------------------------------------------


def test_each_contest_has_its_moves_and_its_deciding_day() -> None:
    doc = raw()
    assert {k["key"] for k in doc["contests"]} == {
        "neutrality_revision",
        "us_japan_talks",
        "atlantic_war",
    }
    state = compiled(doc)
    for k in state.contests.values():
        decl = next(d for d in doc["contests"] if d["name"] == k.name)
        assert len(k.moves) == len(decl["moves"]) >= 4, decl["key"]
        assert k.decides == START + timedelta(days=decl["countdown_days"])


def test_every_contest_side_has_a_move_toward_it() -> None:
    for k in raw()["contests"]:
        assert {m["toward"] for m in k["moves"]} == set(k["sides"]), k["key"]
