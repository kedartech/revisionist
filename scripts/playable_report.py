"""The playable report: whom the playable rule admits in a world, card by card (PBR).

For each card of the world, in name order, one line: admitted or not, and why not, in the
rule's own words; whether the world holds it back; and whether the card is flagged
playable by hand today. Then the differences: admitted and not flagged, flagged and not
admitted, held back. The rule is read whether or not the world switches it on, against
the world's floor or the default lines. Nothing is written and no model is called.

Usage::

    python scripts/playable_report.py WORLD [WORLD ...]

``WORLD`` is a bundled world's name (``autumn-1941``) or a path. The exit status is 1
when a world does not compile.
"""

import argparse
import sys
from collections.abc import Sequence

from revisionist.core import roster
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId
from revisionist.core.state import Rule
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import WorldError, compile_world, floor, resolve_keys
from revisionist.engine.campaign import load_world, versions, world_path

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
"""Any fixed id: the report reads no id."""


def _today(world: WorldFile) -> WorldFile:
    """The world as it compiles by its hand flags: a world that switches the rule on has
    its roster's cards flagged, and the rule taken out."""
    if Rule.PLAYABLE_RULE not in world.rules:
        return world
    listed = {ch.entity for ch in world.roster}
    return world.model_copy(
        update={
            "rules": tuple(r for r in world.rules if r is not Rule.PLAYABLE_RULE),
            "cards": tuple(
                c.model_copy(update={"playable": c.person in listed}) for c in world.cards
            ),
        }
    )


def report(world: WorldFile) -> list[str]:
    """The report's lines for ``world``. Raises ``WorldError``."""
    state = replay(compile_world(_today(world), CAMPAIGN, versions()))
    ids = resolve_keys(world, CAMPAIGN)
    line = floor(world)
    named = "set by the world" if world.playable_floor is not None else "the default"
    switched = "on" if Rule.PLAYABLE_RULE in world.rules else "off"
    out = [
        f"Playable report: {world.name} ({world.world})",
        f"The playable rule is {switched} in this world.",
        f"Floor: rank {line.rank}, force tier {line.tier} ({named})",
    ]
    admitted: list[str] = []
    flagged_out: list[str] = []
    unflagged_in: list[str] = []
    held: list[str] = []
    for c in sorted(world.cards, key=lambda c: state.entities[EntityId(ids[c.person])].name):
        name = state.entities[EntityId(ids[c.person])].name
        why = roster.admits(state, state.cards[EntityId(ids[c.person])], line)
        verdict = "admitted" if not why else f"not admitted: {'; '.join(why)}"
        marks = [verdict]
        if c.held_back:
            marks.append("held back")
            held.append(name)
        marks.append("flagged by hand" if c.playable else "not flagged by hand")
        out.append(f"{name} ({c.person}): {'; '.join(marks)}")
        if not why and c.playable:
            admitted.append(name)
        elif not why:
            unflagged_in.append(name)
        elif c.playable:
            flagged_out.append(name)
    out += [
        "",
        f"Admitted and flagged by hand: {_names(admitted)}",
        f"Admitted and not flagged by hand: {_names(unflagged_in)}",
        f"Flagged by hand and not admitted: {_names(flagged_out)}",
        f"Held back: {_names(held)}",
    ]
    return out


def _names(names: Sequence[str]) -> str:
    return ", ".join(names) if names else "none"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Whom the playable rule admits in a world.")
    parser.add_argument("worlds", nargs="+", metavar="WORLD")
    args = parser.parse_args(argv)
    status = 0
    for n, name in enumerate(args.worlds):
        if n:
            print()
        try:
            print("\n".join(report(load_world(world_path(name)))))
        except WorldError as exc:
            print(f"{name}: does not compile", *exc.problems, sep="\n  ")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
