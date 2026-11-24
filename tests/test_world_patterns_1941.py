"""1941 aim patterns by kind of post (OWD).

Autumn 1941 switches on ``own_aim`` and carries aim patterns for four kinds of post: a
head of government, a war minister, a fleet commander and an army commander. Each playable
card names its kind of post. No pattern names a place: a place is a blank whose values the
rules resolve from the seat's view. A blank's closed list holds no value that is met on the
first day; a value resolved from the view may be, and the check refuses it as met.

On the first day every pattern is filled with each allowed value from each playable card's
view: each fill stands or is refused for a reason the check states, and the table is
printed for Josh (``-s``). Each playable card is read for an aim its own government would
not issue; the cards that carry none are listed for Josh and are not changed here.
"""

import copy
import re
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import product
from typing import Any

import pytest
import yaml

from revisionist.core import aim_patterns
from revisionist.core.aim_patterns import Filled, Refused
from revisionist.core.ids import EntityId, SeatId, derived_id
from revisionist.core.state import Rule, State
from revisionist.core.world import AimPatternDecl, CardDecl, WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import session_zero
from revisionist.engine.store import MemoryStore, load_state
from tests import test_world_locks_1941 as locks_1941
from tests.test_rule_names import BASELINE_1941
from tests.test_territory_model import CAMPAIGN

WORLD = cmp.world_path("autumn-1941")
KINDS = ("head_of_government", "war_minister", "fleet_commander", "army_commander")
POSTS = {
    "roosevelt": "head_of_government",
    "churchill": "head_of_government",
    "stalin": "head_of_government",
    "hitler": "head_of_government",
    "konoe": "head_of_government",
    "tojo": "war_minister",
    "mussolini": "head_of_government",
    "chiang": "head_of_government",
    "king": "fleet_commander",
    "tovey": "fleet_commander",
    "doenitz": "fleet_commander",
    "yamamoto": "fleet_commander",
    "iachino": "fleet_commander",
    "timoshenko": "army_commander",
    "xue_yue": "army_commander",
    "ryti": "head_of_government",
    "mannerheim": "army_commander",
}
"""The kind of post each playable card names. [proposed]"""
STATED = frozenset(
    {
        aim_patterns.MET,
        aim_patterns.SETTLED,
        aim_patterns.UNSEEN,
        aim_patterns.UNCHECKABLE,
        aim_patterns.TOO_LONG,
    }
)
"""The reasons a fill may be refused for on the first day: its values, not the seat."""
FULL = 64
"""A pattern with this many fills or fewer is filled with every combination of values;
one with more, with each value of each blank, the other blanks at their first value."""

AFTER = BASELINE_1941
"""The scripted run's digest with ``own_aim`` on, recorded once by this item. It equals the
baseline: the script seats the President and sets no own aim, and the patterns are declared
with the world, before the payloads the digest reads."""

NOT_ISSUED: dict[str, tuple[int, str, str]] = {
    "konoe": (
        2,
        "tojo",
        "A meeting with Roosevelt before the Army's deadline runs out; his own War Minister"
        " opposes a summit that would give up China, and the card says a summit needs the"
        " services' consent.",
    ),
    "tojo": (
        2,
        "konoe",
        "Holding the government to its deadline for war; his own Prime Minister opposes him"
        " over the October deadline.",
    ),
    "yamamoto": (
        1,
        "nagano",
        "Taking Hawaii; the Chief of the Navy General Staff, his principal, opposed the Hawaii"
        " operation until Yamamoto threatened to resign.",
    ),
}
"""For each playable card that carries one, an aim its own government would not issue: the
aim's number, the member of the same government the card is set against over it, and why.
COD3's reading of the cards' own lines. [proposed]"""
LISTED_FOR_JOSH = (
    "roosevelt",
    "churchill",
    "stalin",
    "hitler",
    "mussolini",
    "chiang",
    "king",
    "tovey",
    "doenitz",
    "iachino",
    "timoshenko",
    "xue_yue",
    "ryti",
    "mannerheim",
)
"""The playable cards that carry no aim their own government would not issue (OWD rule 3):
listed for Josh, not changed here."""


def raw() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(WORLD.read_text())
    return doc


def playable(doc: dict[str, Any]) -> list[str]:
    return [r["entity"] for r in doc["roster"]]


def cards(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["person"]: c for c in doc["cards"]}


def decl(doc: dict[str, Any]) -> WorldFile:
    """The shipped world with ``doc``'s rules, cards and aim patterns."""
    return cmp.load_world(WORLD).model_copy(
        update={
            "rules": tuple(Rule(r) for r in doc["rules"]),
            "cards": tuple(CardDecl.model_validate(c) for c in doc["cards"]),
            "aim_patterns": tuple(AimPatternDecl.model_validate(p) for p in doc["aim_patterns"]),
        }
    )


def day_one(doc: dict[str, Any], people: Sequence[str]) -> tuple[State, dict[str, SeatId]]:
    """The game on its first day with each of ``people`` held by a player."""
    world = decl(doc)
    ids = resolve_keys(world, CAMPAIGN)
    store = MemoryStore()
    store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
    seats: dict[str, SeatId] = {}
    for person in people:
        pid = EntityId(ids[person])
        seats[person] = SeatId(derived_id(CAMPAIGN, "seat", pid))
        name = load_state(store, CAMPAIGN).entities[pid].name
        session_zero.claim(store, CAMPAIGN, seats[person], name)
    return load_state(store, CAMPAIGN), seats


def days_one(doc: dict[str, Any]) -> list[tuple[State, dict[str, SeatId]]]:
    """The first day of as many games as it takes to hold every playable card, each with no
    more players than a game seats."""
    people = playable(doc)
    most = decl(doc).settings.max_human_seats
    return [day_one(doc, people[n : n + most]) for n in range(0, len(people), most)]


# --- the sweep ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Fill:
    person: str
    pattern: str
    values: tuple[tuple[str, str | int], ...]
    stands: bool
    reasons: tuple[str, ...]


def _combos(names: list[str], allowed: list[tuple[Any, ...]]) -> Iterator[dict[str, Any]]:
    total = 1
    for values in allowed:
        total *= len(values)
    if total <= FULL:
        for combo in product(*allowed):
            yield dict(zip(names, combo, strict=True))
        return
    first = {n: v[0] for n, v in zip(names, allowed, strict=True) if v}
    for name, values in zip(names, allowed, strict=True):
        for v in values:
            yield {**first, name: v}


def sweep(doc: dict[str, Any], only: str | None = None) -> list[Fill]:
    """Every pattern (or ``only``), filled from each playable card's view on the first day
    with each value its view allows, by the check a player's fill goes through."""
    out: list[Fill] = []
    for state, seats in days_one(doc):
        out += _sweep_game(state, seats, only)
    return out


def _sweep_game(state: State, seats: dict[str, SeatId], only: str | None) -> list[Fill]:
    assert state.aim_patterns is not None
    out: list[Fill] = []
    for person, seat in seats.items():
        rungs = {r.key: r for r in aim_patterns.ladder(state, seat)}
        for key, rung in rungs.items():
            if only is not None and key != only:
                continue
            names = [b.name for b in rung.blanks]
            allowed = [b.values for b in rung.blanks]
            for values in _combos(names, allowed):
                got = aim_patterns.fill(state, seat, key, values)
                out.append(
                    Fill(
                        person=person,
                        pattern=key,
                        values=tuple(sorted(values.items())),
                        stands=isinstance(got, Filled),
                        reasons=got.reasons if isinstance(got, Refused) else (),
                    )
                )
    return out


def met_problems(doc: dict[str, Any], fills: list[Fill]) -> list[str]:
    """Each fill of a pattern with a closed list that is refused as met on the first day."""
    with_lists = {p["key"] for p in doc["aim_patterns"] if any("values" in b for b in p["blanks"])}
    return [
        f"{f.person} {f.pattern} {dict(f.values)}: met on the first day"
        for f in fills
        if f.pattern in with_lists and aim_patterns.MET in f.reasons
    ]


def table(fills: list[Fill]) -> str:
    """By card and pattern: the fills that stand, and those refused by reason."""
    rows: dict[tuple[str, str], Counter[str]] = {}
    for f in fills:
        c = rows.setdefault((f.person, f.pattern), Counter())
        if f.stands:
            c["stands"] += 1
        for r in f.reasons:
            c[r] += 1
    lines = ["card | pattern | fills | stand | refused, by reason"]
    for (person, key), c in rows.items():
        n = sum(1 for f in fills if (f.person, f.pattern) == (person, key))
        why = "; ".join(f"{r} {k}" for r, k in sorted(c.items()) if r != "stands") or "-"
        lines.append(f"{person} | {key} | {n} | {c['stands']} | {why}")
    return "\n".join(lines)


@pytest.fixture(scope="module")
def fills() -> list[Fill]:
    return sweep(raw())


# --- places -------------------------------------------------------------------------------


def place_problems(doc: dict[str, Any]) -> list[str]:
    """Each pattern whose condition or sentence names a place of the map."""
    places: dict[str, str] = {}
    for section in ("territories", "regions", "sea_zones"):
        for x in doc.get(section) or ():
            places[x["key"]] = str(x.get("name", x["key"]))

    def strings(node: Any) -> Iterator[str]:
        if isinstance(node, dict):
            for v in node.values():
                yield from strings(v)
        elif isinstance(node, list):
            for v in node:
                yield from strings(v)
        elif isinstance(node, str):
            yield node

    out: list[str] = []
    for p in doc["aim_patterns"]:
        named = [s for s in strings(p["condition"]) if s in places]
        named += [
            k
            for k, name in places.items()
            if re.search(rf"\b{re.escape(name)}\b", p["sentence"], re.IGNORECASE)
        ]
        out += [f"aim pattern {p['key']} names {k}" for k in named]
    return out


# --- rule 4: the world's rules gain own_aim -----------------------------------------------


def test_the_world_switches_on_own_aim_and_its_patterns_reach_state() -> None:
    w = cmp.load_world(WORLD)
    assert Rule.OWN_AIM in w.rules
    state, _ = day_one(raw(), ())
    assert aim_patterns.on(state)
    assert state.aim_patterns is not None
    ids = resolve_keys(w, CAMPAIGN)
    assert state.aim_patterns.posts == {EntityId(ids[p]): k for p, k in POSTS.items()}


# --- rule 1: four kinds of post, at least four patterns each, no place named ---------------


def test_every_playable_card_names_its_kind_of_post() -> None:
    doc = raw()
    assert {p: cards(doc)[p].get("post_kind") for p in playable(doc)} == POSTS


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_of_post_has_at_least_four_patterns(kind: str) -> None:
    suits = [p["key"] for p in raw()["aim_patterns"] if kind in p["posts"]]
    assert len(suits) >= 4, suits


def test_no_pattern_names_a_place() -> None:
    assert place_problems(raw()) == []


def test_every_pattern_suits_one_of_the_four_kinds() -> None:
    for p in raw()["aim_patterns"]:
        assert set(p["posts"]) <= set(KINDS), p["key"]


# --- rule 2: no value is met on the first day; every fill stands or is refused -----------


def test_no_blank_with_a_closed_list_holds_a_value_met_on_the_first_day(
    fills: list[Fill],
) -> None:
    assert met_problems(raw(), fills) == []


def test_every_fill_on_the_first_day_stands_or_is_refused_for_a_stated_reason(
    fills: list[Fill],
) -> None:
    print("\n" + table(fills))
    assert fills
    for f in fills:
        assert f.stands or (f.reasons and set(f.reasons) <= STATED), f


def test_every_playable_card_has_a_pattern_and_a_fill_that_stands(fills: list[Fill]) -> None:
    doc = raw()
    standing = {f.person for f in fills if f.stands}
    assert standing == set(playable(doc))


# --- rule 3: an aim the card's own government would not issue -----------------------------


def test_the_cards_without_an_aim_their_government_would_not_issue_are_listed() -> None:
    doc = raw()
    by_person = cards(doc)
    missing = tuple(p for p in playable(doc) if p not in NOT_ISSUED)
    print("\nNo aim its own government would not issue:", ", ".join(missing))
    assert missing == LISTED_FOR_JOSH
    for person, (aim, against, _) in NOT_ISSUED.items():
        card = by_person[person]
        assert 1 <= aim <= len(card["aims"]), person
        rule = next(r for r in card["aim_rules"] if r["aim"] == aim)
        assert not rule.get("replaceable"), person  # an own aim may not drop it
        assert against in {o["against"] for o in card["opposes"]}, person
        same_government = against in card["principals"] or person in by_person[against].get(
            "principals", ()
        )
        assert same_government, person


def test_every_playable_card_may_take_an_own_aim_its_government_would_not_issue(
    fills: list[Fill],
) -> None:
    doc = raw()
    not_government = {p["key"] for p in doc["aim_patterns"] if p.get("government") is False}
    may = {f.person for f in fills if f.stands and f.pattern in not_government}
    assert may == set(playable(doc))


# --- rule 5 and the digest ----------------------------------------------------------------


def test_with_own_aim_out_of_a_copys_rules_the_digest_is_the_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = locks_1941._world()
    off = w.model_copy(update={"rules": tuple(r for r in w.rules if r is not Rule.OWN_AIM)})
    assert locks_1941.run_digest(off, monkeypatch) == BASELINE_1941


def test_the_digest_with_own_aim_on_is_the_one_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    assert locks_1941.run_digest(locks_1941._world(), monkeypatch) == AFTER


# --- mutants ------------------------------------------------------------------------------


def test_mutant_a_pattern_that_names_a_place_is_caught() -> None:
    doc = copy.deepcopy(raw())
    take = next(p for p in doc["aim_patterns"] if p["key"] == "take_ground")
    take["condition"]["area"] = "iceland"
    take["blanks"] = []
    assert "aim pattern take_ground names iceland" in place_problems(doc)


def test_mutant_a_place_named_in_a_sentence_is_caught() -> None:
    doc = copy.deepcopy(raw())
    take = next(p for p in doc["aim_patterns"] if p["key"] == "take_ground")
    take["sentence"] = "Take {place} for {nation}, as Iceland was taken."
    assert "aim pattern take_ground names iceland" in place_problems(doc)


def test_mutant_a_blank_whose_values_include_one_met_on_the_first_day_is_caught() -> None:
    doc = copy.deepcopy(raw())
    raise_group = next(p for p in doc["aim_patterns"] if p["key"] == "raise_group")
    line = next(b for b in raise_group["blanks"] if b["name"] == "line")
    line["values"] = [60, *line["values"]]
    found = met_problems(doc, sweep(doc, only="raise_group"))
    assert found and all(": met on the first day" in f for f in found)
