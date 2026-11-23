"""The player's own aim: patterns, the check and the stored aim (OWC).

With ``own_aim`` on, a world may carry ``aim_patterns``: each a key, the kinds of post it
suits, a sentence with named blanks, a condition built from the checks aims use with the
same blanks (``$name``; ``$nation`` and ``$person`` stand for the person's own nation and
the person), the values each blank may take (a closed list, or a kind resolved from the
seat's view), and whether the person's own government would issue it. They reach state
once, by ``aim_patterns_declared``, public.

``fill`` checks a pattern filled by a seat from that seat's view alone and returns the aim
or every reason it cannot stand; ``own_aim_set`` makes the event that stores it for the
person, replacing the card's replaceable aim, once per person and only before the first
wake his player plays has closed. ``ladder`` lists the patterns a seat's post may use,
easiest first. No model is called and no free text reaches a rule: a value is checked
against its blank, and the condition is built from the pattern's own words.

``exposure`` says whether the seat holding a person may see the fact a leaf reads, from
facts both the compiler and state carry; the compiler and ``sees`` both call it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from datetime import date
from enum import StrEnum
from itertools import islice, product
from typing import TYPE_CHECKING, Any, cast

from pydantic import Field, JsonValue, TypeAdapter, ValidationError, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.goals import (
    AgreementInForce,
    AimCondition,
    AimRule,
    AtWar,
    ContestWon,
    EntityIs,
    Exposure,
    HoldsArea,
    IncomeAt,
    Leaf,
    QuantityAt,
    RegardAt,
    SupportAt,
    WinCondition,
    leaves,
)
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.visibility import Visibility

if TYPE_CHECKING:
    from revisionist.core.events import OwnAimSet
    from revisionist.core.state import State, View

OFF = "Own aims are not part of this game."
NO_PATTERN = "There is no such pattern."
NOT_YOUR_POST = "This pattern does not suit your post."
NOT_PLAYED = "Only a player may set his own aim."
NO_REPLACEABLE = "Your card has no aim you may replace."
ALREADY_SET = "You have set your own aim already."
TOO_LATE = "The time to set your own aim has passed."
UNSEEN = "The aim reads something you cannot see."
MET = "The aim is met already: an aim has to be worked for."
SETTLED = "The aim can no longer be met."
UNCHECKABLE = "The values do not make an aim the rules can check."
TOO_LONG = "The aim's sentence is too long."

LADDER_TRIES = 400
"""The most fills ``ladder`` tries for one pattern's difficulty, in the blanks' order."""

BUILT_IN = ("nation", "person")
"""Blanks every pattern may use without declaring them."""


class BlankKind(StrEnum):
    """A blank whose values are resolved from the seat's view. ``[proposed]``"""

    TERRITORY_NOT_HELD = "territory_not_held"
    """A territory the person's nation does not hold."""
    TERRITORY_HELD = "territory_held"
    """A territory the person's nation holds."""
    OTHER_NATION = "other_nation"
    """A nation other than the person's own."""
    OWN_GROUP = "own_group"
    """A group of the person's own nation."""


KIND_FIELDS: dict[BlankKind, frozenset[str]] = {
    BlankKind.TERRITORY_NOT_HELD: frozenset({"area"}),
    BlankKind.TERRITORY_HELD: frozenset({"area"}),
    BlankKind.OTHER_NATION: frozenset({"holder", "nation", "a", "b", "side", "between", "entity"}),
    BlankKind.OWN_GROUP: frozenset({"group"}),
}
"""The fields of a check each kind of blank may stand in."""

SECTIONS: dict[str, str] = {
    "holder": "entity",
    "office": "asset",
    "asset": "asset",
    "entity": "entity",
    "meter": "meter",
    "commitment": "commitment",
    "relationship": "relationship",
    "person": "entity",
    "quantity": "quantity",
    "area": "entity",
    "nation": "entity",
    "contest": "contest",
    "side": "entity",
    "a": "entity",
    "b": "entity",
    "between": "entity",
    "group": "group",
    "value": "number",
}
"""What each field a blank may stand in names: a world section, a group key or a number."""

BlankValue = str | int


class AimBlank(Model):
    """One blank of a pattern: its name, and a closed list of values (ids, group keys or
    numbers) or a kind resolved from the seat's view."""

    name: Label
    values: tuple[BlankValue, ...] = ()
    kind: BlankKind | None = None

    @model_validator(mode="after")
    def _one(self) -> AimBlank:
        if bool(self.values) == (self.kind is not None):
            raise ValueError("a blank has a list of values or a kind, not both")
        return self


class AimPattern(Model):
    """One pattern a player may fill (OWC rule 1). ``condition`` is an aim's condition with
    ids bound and each blank written ``$name``."""

    key: Label
    posts: tuple[Label, ...] = Field(min_length=1)
    """The kinds of post it suits: a card's ``post_kind``, or its path."""
    sentence: str = Field(min_length=1, max_length=200)
    """The aim in words, each blank written ``{name}``."""
    condition: dict[str, JsonValue]
    blanks: tuple[AimBlank, ...] = Field(default=(), max_length=4)
    government: bool = True
    """Whether the person's own government would issue it."""
    deadline: date | None = None
    """The last day the filled aim is judged; None: the replaced aim's."""


class AimPatterns(Model):
    """The world's patterns, and the kind of post each card names, by person. Public."""

    patterns: tuple[AimPattern, ...] = Field(min_length=1)
    posts: dict[EntityId, Label] = Field(default_factory=dict)


class Filled(Model):
    """A pattern filled so that it stands: the aim as it will read, its rule (condition,
    period, who sees each leaf), and the card's aim it replaces."""

    key: Label
    values: dict[Label, BlankValue]
    text: str = Field(max_length=280)
    rule: AimRule
    government: bool
    aim: int = Field(ge=1, le=3)


class OwnAim(Filled):
    """The player's own aim, stored for the person (OWC rule 4): kept by whoever holds him."""

    person: EntityId


class Refused(Model):
    """Every reason a filled pattern cannot stand, in fixed words."""

    reasons: tuple[str, ...] = Field(min_length=1)


class RungBlank(Model):
    """A blank as a seat may fill it: the values its view allows and their names."""

    name: Label
    values: tuple[BlankValue, ...]
    labels: tuple[str, ...]


class Rung(Model):
    """A pattern on a seat's ladder. ``difficulty`` is its easiest fill's, on the rubric
    (``goals.difficulty``); None when no fill stands."""

    key: Label
    sentence: str
    blanks: tuple[RungBlank, ...]
    difficulty: int | None
    government: bool


_CONDITION: TypeAdapter[WinCondition] = TypeAdapter(AimCondition)
_PLACEHOLDER = re.compile(r"^\$([a-z][a-z0-9_]*)$")
_SENTENCE_BLANK = re.compile(r"\{([a-z][a-z0-9_]*)\}")


# --- who sees each leaf ------------------------------------------------------------------


def exposure(
    leaf: Leaf,
    person: str,
    nation: str | None,
    quantity: Callable[[str], tuple[bool, str | None] | None],
    contest_public: Callable[[str], bool],
) -> Exposure:
    """Whether the seat holding ``person`` (of ``nation``) may see the fact ``leaf`` reads:
    the board's holders, wars, war-economy figures and a person's state are public; a
    group's support, an agreement and regard are its own nation's when it is in them; a
    quantity by its scope (public) or owner's nation (``quantity`` gives both, or None for
    one unknown); a contest by its scope; anything else is hidden. Keys or ids alike."""
    match leaf:
        case HoldsArea() | IncomeAt() | AtWar() | EntityIs():
            return Exposure.PUBLIC
        case SupportAt():
            return Exposure.OWN if leaf.nation == nation else Exposure.HIDDEN
        case AgreementInForce():
            return Exposure.OWN if nation in leaf.between else Exposure.HIDDEN
        case RegardAt():
            return Exposure.OWN if person in (leaf.a, leaf.b) else Exposure.HIDDEN
        case QuantityAt():
            facts = quantity(leaf.quantity)
            if facts is not None and facts[0]:
                return Exposure.PUBLIC
            owner = None if facts is None else facts[1]
            return Exposure.OWN if owner is not None and owner == nation else Exposure.HIDDEN
        case ContestWon():
            return Exposure.PUBLIC if contest_public(leaf.contest) else Exposure.HIDDEN
        case _:
            return Exposure.HIDDEN


def _polity(world: State | View, entity: EntityId | None) -> EntityId | None:
    from revisionist.core.realism.war import polity_of

    return None if entity is None else polity_of(cast("State", world), entity)


def sees(world: State | View, person: EntityId, condition: WinCondition) -> tuple[Exposure, ...]:
    """``exposure`` for each leaf of ``condition``, in ``leaves`` order, from ``world``."""

    def quantity(qid: str) -> tuple[bool, str | None] | None:
        q = world.quantities.get(cast("Any", qid))
        if q is None:
            return None
        public = q.scope is not None and q.scope.visibility is Visibility.PUBLIC
        return public, _polity(world, q.owner)

    def contest_public(cid: str) -> bool:
        k = world.contests.get(cast("Any", cid))
        return k is not None and k.scope.visibility is Visibility.PUBLIC

    nation = _polity(world, person)
    return tuple(exposure(x, person, nation, quantity, contest_public) for x in leaves(condition))


# --- patterns as written -------------------------------------------------------------------


def slots(template: Mapping[str, JsonValue]) -> dict[str, set[str]]:
    """Each blank a condition names (without its ``$``), with the fields it stands in."""
    out: dict[str, set[str]] = {}

    def walk(node: JsonValue, field: str | None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, field)
        elif isinstance(node, str) and field is not None and field != "check":
            m = _PLACEHOLDER.match(node)
            if m is not None:
                out.setdefault(m.group(1), set()).add(field)

    walk(dict(template), None)
    return out


def substitute(template: Mapping[str, JsonValue], values: Mapping[str, JsonValue]) -> JsonValue:
    """The condition with each ``$name`` replaced by its value; other text left as it is."""

    def walk(node: JsonValue) -> JsonValue:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            m = _PLACEHOLDER.match(node)
            if m is not None and m.group(1) in values:
                return values[m.group(1)]
        return node

    return walk(dict(template))


def sentence_blanks(sentence: str) -> set[str]:
    return set(_SENTENCE_BLANK.findall(sentence))


def build(template: Mapping[str, JsonValue], values: Mapping[str, JsonValue]) -> WinCondition:
    """The condition filled with ``values``. Raises ``ValidationError``."""
    return _CONDITION.validate_python(substitute(template, values))


# --- the seat, its post and its card --------------------------------------------------------


def on(state: State | View) -> bool:
    """Whether own aims are part of this game: the rule on and the patterns declared."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.OWN_AIM in rules and state.aim_patterns is not None


def suits(state: State, person: EntityId, pattern: AimPattern) -> bool:
    """Whether ``pattern`` suits the post of ``person``: the kind his card names, or its path."""
    kinds: set[str] = set()
    if state.aim_patterns is not None and person in state.aim_patterns.posts:
        kinds.add(state.aim_patterns.posts[person])
    card = state.cards.get(person)
    if card is not None:
        kinds.add(card.path.value)
    return bool(kinds & set(pattern.posts))


def replaceable(state: State, person: EntityId) -> tuple[int, AimRule] | None:
    """The card's replaceable aim, by its index from 1, with its rule; None if it has none."""
    card = state.cards.get(person)
    if card is None:
        return None
    for i, r in enumerate(card.aim_rules, start=1):
        if r is not None and r.replaceable and i <= len(card.aims):
            return i, r
    return None


def window_open(state: State, person: EntityId) -> bool:
    """Whether ``person``'s own aim may still be set: none set, and no wake has closed
    while a player held him."""
    return person not in state.own_aims and person not in state.aim_shut


def _pattern(state: State, key: str) -> AimPattern | None:
    if state.aim_patterns is None:
        return None
    return next((p for p in state.aim_patterns.patterns if p.key == key), None)


def _person_reasons(state: State, seat: SeatId) -> list[str]:
    from revisionist.core.ontology import Controller

    me = state.seats[seat]
    out: list[str] = []
    if me.controller is not Controller.HUMAN:
        out.append(NOT_PLAYED)
    if replaceable(state, me.embodies) is None:
        out.append(NO_REPLACEABLE)
    if me.embodies in state.own_aims:
        out.append(ALREADY_SET)
    if me.embodies in state.aim_shut:
        out.append(TOO_LATE)
    return out


# --- the seat's view: values, names, what it sees ------------------------------------------


def _allowed(view: View, nation: EntityId | None, blank: AimBlank, fields: set[str]) -> list[Any]:
    """The values ``blank`` may take as the seat's view allows."""
    from revisionist.core.ontology import EntityKind
    from revisionist.core.realism import groups, holders

    match blank.kind:
        case BlankKind.TERRITORY_NOT_HELD | BlankKind.TERRITORY_HELD:
            if view.map is None:
                return []
            held = blank.kind is BlankKind.TERRITORY_HELD
            return [
                t.area
                for t in view.map.territories
                if (holders.holder(view, t.area) == nation) is held
            ]
        case BlankKind.OTHER_NATION:
            return [
                e.entity_id
                for e in view.entities.values()
                if e.kind is EntityKind.POLITY and e.entity_id != nation
            ]
        case BlankKind.OWN_GROUP:
            return [] if nation is None else [g.key for g in groups.of(view, nation)]
    return [v for v in blank.values if _seen_value(view, nation, v, fields)]


def _seen_value(view: View, nation: EntityId | None, value: BlankValue, fields: set[str]) -> bool:
    from revisionist.core.realism import groups

    if isinstance(value, int):
        return True
    tables: dict[str, Mapping[Any, object]] = {
        "entity": view.entities,
        "asset": view.assets,
        "meter": view.meters,
        "commitment": view.commitments,
        "relationship": view.relationships,
        "quantity": view.quantities,
        "contest": view.contests,
    }
    for field in fields:
        section = SECTIONS.get(field)
        if section == "group":
            if nation is None or groups.group(view, nation, value) is None:
                return False
        elif section in tables and value not in tables[section]:
            return False
    return True


def _label(view: View, nation: EntityId | None, value: Any) -> str:
    from revisionist.core.realism import groups

    if isinstance(value, int):
        return str(value)
    for table in (view.entities, view.contests, view.quantities, view.assets):
        found = table.get(value)
        if found is not None:
            return str(found.name)
    if nation is not None and (g := groups.group(view, nation, value)) is not None:
        return g.name
    return str(value)


def _unseen(view: View, person: EntityId, nation: EntityId | None, c: WinCondition) -> bool:
    """Whether a leaf of ``c`` names something the seat's view lacks, or reads a fact the
    seat cannot see."""
    if any(e is Exposure.HIDDEN for e in sees(view, person, c)):
        return True
    for leaf in leaves(c):
        dumped = leaf.model_dump(mode="json")
        for field, value in dumped.items():
            if field not in SECTIONS or field == "value":
                continue
            items = value if isinstance(value, list) else [value]
            if not all(_seen_value(view, nation, v, {field}) for v in items):
                return True
        if isinstance(leaf, SupportAt):
            from revisionist.core.realism import groups

            if groups.group(view, leaf.nation, leaf.group) is None:
                return True
    return False


def _settled(view: View, c: WinCondition) -> bool:
    from revisionist.core.goals import _settled as settled

    return settled(view, c)


# --- fill, the event, the ladder ------------------------------------------------------------


def _fill(
    state: State,
    view: View,
    pattern: AimPattern,
    values: Mapping[str, BlankValue],
) -> Filled | list[str]:
    """``pattern`` filled with ``values`` from ``view``, or the reasons it cannot stand
    (the seat's own state aside)."""
    from revisionist.core.goals import goal_met

    person = view.me.embodies
    nation = _polity(view, person)
    reasons: list[str] = []
    fields = slots(pattern.condition)
    given: dict[str, JsonValue] = {"nation": nation, "person": person}
    for blank in pattern.blanks:
        if blank.name not in values:
            reasons.append(f"{blank.name}: give a value.")
            continue
        v = values[blank.name]
        allowed = (
            blank.values
            if blank.kind is None
            else tuple(_allowed(view, nation, blank, fields.get(blank.name, set())))
        )
        if v not in allowed:
            reasons.append(
                f"{blank.name}: {_label(view, nation, v)} is not a value this blank takes."
            )
        given[blank.name] = v
    names = {b.name for b in pattern.blanks}
    reasons += [f"{k}: there is no such blank." for k in values if k not in names]
    if reasons:
        return reasons
    try:
        condition = build(pattern.condition, given)
    except ValidationError:
        return [UNCHECKABLE]
    if _unseen(view, person, nation, condition):
        reasons.append(UNSEEN)
    if goal_met(view, condition):
        reasons.append(MET)
    found = replaceable(state, person)
    opens = found[1].opens if found is not None else None
    deadline = pattern.deadline or (found[1].deadline if found is not None else None)
    today = view.in_world_date
    if _settled(view, condition) or (
        deadline is not None and today is not None and today > deadline
    ):
        reasons.append(SETTLED)
    words = {k: _label(view, nation, v) for k, v in given.items()}
    text = _SENTENCE_BLANK.sub(lambda m: words.get(m.group(1), m.group(0)), pattern.sentence)
    if len(text) > 280:
        reasons.append(TOO_LONG)
    if reasons:
        return reasons
    rule = AimRule(
        condition=condition,
        rule=text,
        opens=opens,
        deadline=deadline,
        sees=sees(view, person, condition),
    )
    return Filled(
        key=pattern.key,
        values=dict(values),
        text=text,
        rule=rule,
        government=pattern.government,
        aim=found[0] if found is not None else 1,
    )


def fill(
    state: State, seat: SeatId, key: str, values: Mapping[str, BlankValue]
) -> Filled | Refused:
    """OWC rule 2: the aim ``key`` filled with ``values`` makes, built from ``seat``'s view
    only, or every reason it cannot stand: own aims off, no such pattern, one for another
    post, the seat's own aim set or its window closed, no aim to replace, a value outside a
    blank's list, a thing the seat cannot see, a condition met already or that can no
    longer be met."""
    from revisionist.core.project import project

    if not on(state):
        return Refused(reasons=(OFF,))
    view = project(state, seat)
    person = view.me.embodies
    reasons = _person_reasons(state, seat)
    pattern = _pattern(state, key)
    if pattern is None:
        return Refused(reasons=tuple(dict.fromkeys([*reasons, NO_PATTERN])))
    if not suits(state, person, pattern):
        reasons.insert(0, NOT_YOUR_POST)
    out = _fill(state, view, pattern, values)
    if isinstance(out, list):
        reasons += out
    if reasons:
        return Refused(reasons=tuple(dict.fromkeys(reasons)))
    assert isinstance(out, Filled)
    return out


def own_aim_set(
    state: State, seat: SeatId, key: str, values: Mapping[str, BlankValue]
) -> OwnAimSet | Refused:
    """OWC rule 4: the event that stores the filled aim for the person ``seat`` holds, or
    the reasons ``fill`` gives."""
    from revisionist.core.events import OwnAimSet

    out = fill(state, seat, key, values)
    if isinstance(out, Refused):
        return out
    person = state.seats[seat].embodies
    return OwnAimSet(own=OwnAim(person=person, **out.model_dump()))


def _fills(
    view: View, pattern: AimPattern, blanks: tuple[RungBlank, ...]
) -> Iterator[dict[str, Any]]:
    names = [b.name for b in blanks]
    for combo in islice(product(*(b.values for b in blanks)), LADDER_TRIES):
        yield dict(zip(names, combo, strict=True))


def ladder(state: State, seat: SeatId) -> tuple[Rung, ...]:
    """OWC rule 5: the patterns ``seat``'s post may use, each with the values its view
    allows for each blank and the difficulty of its easiest fill that stands, easiest
    first; a pattern no fill of which stands comes last. From the seat's view only."""
    from revisionist.core.goals import difficulty
    from revisionist.core.project import project

    if not on(state) or state.aim_patterns is None:
        return ()
    view = project(state, seat)
    person = view.me.embodies
    nation = _polity(view, person)
    rungs: list[Rung] = []
    for pattern in state.aim_patterns.patterns:
        if not suits(state, person, pattern):
            continue
        fields = slots(pattern.condition)
        blanks = []
        for b in pattern.blanks:
            allowed = tuple(_allowed(view, nation, b, fields.get(b.name, set())))
            blanks.append(
                RungBlank(
                    name=b.name,
                    values=allowed,
                    labels=tuple(_label(view, nation, v) for v in allowed),
                )
            )
        best: int | None = None
        for values in _fills(view, pattern, tuple(blanks)):
            out = _fill(state, view, pattern, values)
            if isinstance(out, Filled):
                d = difficulty(view, seat, out.rule.condition)
                best = d if best is None else min(best, d)
        rungs.append(
            Rung(
                key=pattern.key,
                sentence=pattern.sentence,
                blanks=tuple(blanks),
                difficulty=best,
                government=pattern.government,
            )
        )
    return tuple(sorted(rungs, key=lambda r: (r.difficulty is None, r.difficulty or 0, r.key)))


__all__ = [
    "ALREADY_SET",
    "MET",
    "NOT_PLAYED",
    "NOT_YOUR_POST",
    "NO_PATTERN",
    "NO_REPLACEABLE",
    "OFF",
    "SETTLED",
    "TOO_LATE",
    "UNSEEN",
    "AimBlank",
    "AimPattern",
    "AimPatterns",
    "BlankKind",
    "BlankValue",
    "Filled",
    "OwnAim",
    "Refused",
    "Rung",
    "RungBlank",
    "build",
    "exposure",
    "fill",
    "ladder",
    "on",
    "own_aim_set",
    "replaceable",
    "sees",
    "slots",
    "substitute",
    "suits",
    "window_open",
]
