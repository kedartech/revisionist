"""What a suggested action may say the staff expect it to move (plan item "suggested
actions say what the staff expect").

A model option may carry ``expects``, up to four moves, each naming a target the
seat's view holds, and ``risks``, three levels. This module lists those targets and
screens a reply's entries against them: an entry that is malformed, names anything
else, or comes past the fourth is left out and the action is kept. No rule reads
either field; they are staff talk shown beside the action.
"""

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from revisionist.core.ontology import EntityKind, EntityStatus
from revisionist.core.realism.agenda import EXPECTS_MAX, Expect, ExpectOn, Risks
from revisionist.core.state import State, View

Targets = dict[ExpectOn, dict[str, str]]
"""For each kind of target, the keys the seat may name, each with its name."""

Left = Callable[[str], None]
"""Told why each entry was left out. Never told the entry's text."""


def targets(state: State, view: View) -> Targets:
    """What the seat's view holds that an expected move may name: the regard of every
    living person with a card face but the seat's own; the stance of each leader
    weighed against the seat, as the People roster groups them; each undecided stake;
    each reported figure that has a value."""
    me = view.me.embodies
    people: dict[str, str] = {
        person: entity.name
        for person in view.cards
        if (entity := view.entities.get(person)) is not None
        and person != me
        and entity.kind is EntityKind.PERSON
        and entity.status is not EntityStatus.DEAD
    }
    weighed = state.stances.get(view.viewer, {})
    return {
        ExpectOn.REGARD: people,
        ExpectOn.STANCE: {p: name for p, name in people.items() if p in weighed},
        ExpectOn.STAKE: {str(c): x.name for c, x in view.contests.items() if not x.decided},
        ExpectOn.FIGURE: {
            str(q): x.name for q, x in view.quantities.items() if x.value is not None
        },
    }


def prompt_targets(found: Targets) -> dict[str, list[Any]]:
    """The targets as the options prompt lists them. People are the prompt's own
    entities, so only their ids are repeated."""
    return {
        "people": sorted(found[ExpectOn.REGARD]),
        "leaders_weighed": [
            {"id": k, "name": v} for k, v in sorted(found[ExpectOn.STANCE].items())
        ],
        "stakes": [{"id": k, "name": v} for k, v in sorted(found[ExpectOn.STAKE].items())],
        "figures": [{"id": k, "name": v} for k, v in sorted(found[ExpectOn.FIGURE].items())],
    }


def screen(raw: object, found: Targets, left: Left) -> tuple[Expect, ...]:
    """The reply's expected moves that are well formed and name a target in ``found``,
    the first four of them."""
    if not isinstance(raw, list):
        if raw is not None:
            left("an expected move left out: not valid against the schema")
        return ()
    kept: list[Expect] = []
    for item in raw:
        try:
            move = Expect.model_validate(item)
        except ValidationError:
            left("an expected move left out: not valid against the schema")
            continue
        if move.target not in found[move.on]:
            left("an expected move left out: names something the seat cannot see")
        elif len(kept) == EXPECTS_MAX:
            left("an expected move left out: more than four")
        else:
            kept.append(move)
    return tuple(kept)


def risks(raw: object, left: Left) -> Risks | None:
    """The reply's risks if they are well formed, else none."""
    if raw is None:
        return None
    try:
        return Risks.model_validate(raw)
    except ValidationError:
        left("risks left out: not valid against the schema")
        return None


def name(found: Targets, move: Expect) -> str | None:
    """The name of what ``move`` points at, or None once it has left the view."""
    return found[move.on].get(move.target)


__all__ = ["Left", "Targets", "name", "prompt_targets", "risks", "screen", "targets"]
