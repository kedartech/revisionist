"""Supply: pieces operate only within reach of the rail and ports their side holds (SUP).

With ``supply`` switched on (it needs ``territories``; it reads holders and the economy's
yields), supply is a property read from the day's state, never a stock and never stored:
``status`` is the one function later rules read.

A land piece is in supply when a chain of at most ``SUPPLY_STEPS`` steps, over land
territories each held by its side or an ally, joins the area it stands in to a source: a
territory held by its side or an ally that has a working ``supply`` yield (one whose
``economy.factor`` for the supply role is above nothing today, so a hub taken from another
holder works for its taker only after ``SUPPLY_LAG_DAYS``), or that holds a port the side
may use. The chain never runs through enemy or neutral ground, except that its last step
may enter the area the piece stands in: a piece attacking into enemy ground draws supply
from a neighbour in the network short of the step limit. A land piece at sea is carried by
its own shipping and counts as supplied.

A sea or air piece is in supply within its kind's operating radius of a base of its side
(``bases.area_reach``); a board with no bases sets no such limit. An envoy needs none.

A piece out of supply may not be ordered into a territory held by an enemy
(``war_rules`` words the refusal and names the nearest area it would be supplied in).
"""

from datetime import date
from typing import TYPE_CHECKING, NamedTuple

from revisionist.core.ids import EntityId

if TYPE_CHECKING:
    from revisionist.core.realism.geography import Feature
    from revisionist.core.state import State

SUPPLY_STEPS = 2  # [proposed] plan, SUP Defaults
"""Most steps between a land piece's area and a source, over territory its side may use."""


class Status(NamedTuple):
    """Whether a piece is in supply, and what it is supplied from."""

    supplied: bool
    source: EntityId | None
    """The source area (a hub or a port) or base place that supplies it; None when out."""
    steps: int | None
    """Steps from the source (0 at it); None when out of supply."""
    nearest: EntityId | None
    """For a land piece out of supply: the nearest area it would be supplied in."""


def on(state: "State") -> bool:
    """Whether supply acts in this game: the territory rules and holders on, and ``supply``."""
    from revisionist.core.realism import holders
    from revisionist.core.state import Rule

    return holders.on(state) and Rule.SUPPLY in state.rules


def _friendly(state: "State", own: EntityId, held: EntityId | None) -> bool:
    from revisionist.core.realism import territory

    return held is not None and (held == own or territory.allied(state, own, held))


def _has_port(state: "State", area: EntityId, own: EntityId) -> bool:
    """Whether a port in ``area`` is one ``own`` may use: no base names it, or a base serves it."""
    from revisionist.core.realism.holders import serves

    board = state.map
    assert board is not None
    for port in board.ports:
        if port.land != area:
            continue
        named = [b for b in board.bases if b.place == port.place]
        if not named or any(serves(state, b, own) for b in named):
            return True
    return False


def _working(state: "State", area: EntityId, day: date | None) -> bool:
    from revisionist.core.realism import economy
    from revisionist.core.realism.kinds import Role

    resources = state.kinds.resources if state.kinds is not None else {}
    if not any(
        (r := resources.get(k)) is not None and r.role is Role.SUPPLY and v > 0
        for k, v in sorted(economy.yields_of(state, area).items())
    ):
        return False
    return day is None or economy.factor(state, area, Role.SUPPLY, day) > 0


def sources(state: "State", own: EntityId, day: date | None = None) -> tuple[EntityId, ...]:
    """The territories that supply ``own``'s land pieces on ``day``, in id order: held by it
    or an ally, with a working supply yield or a port it may use."""
    from revisionist.core.realism import territory

    board = state.map
    if board is None:
        return ()
    return tuple(
        sorted(
            t.area
            for t in board.territories
            if _friendly(state, own, territory.holder(state, t.area))
            and (_working(state, t.area, day) or _has_port(state, t.area, own))
        )
    )


def _reach(state: "State", own: EntityId, day: date | None) -> dict[EntityId, tuple[int, EntityId]]:
    """Each land area ``own``'s pieces are supplied in, with its steps from the nearest
    source (ties to the source whose id sorts first): a search that enters only territory
    held by ``own`` or an ally."""
    from collections import deque

    from revisionist.core.realism import territory
    from revisionist.core.realism.kinds import Domain

    board = state.map
    assert board is not None
    found: dict[EntityId, tuple[int, EntityId]] = {}
    for src in sources(state, own, day):
        seen = {src: 0}
        queue = deque([src])
        while queue:
            here = queue.popleft()
            if seen[here] >= SUPPLY_STEPS:
                continue
            for n in territory.neighbours(board, here, Domain.LAND):
                if n not in seen and _friendly(state, own, territory.holder(state, n)):
                    seen[n] = seen[here] + 1
                    queue.append(n)
        for area, dist in seen.items():
            if area not in found or (dist, src) < found[area]:
                found[area] = (dist, src)
    return found


def _nearest(state: "State", frm: EntityId, supplied: set[EntityId]) -> EntityId | None:
    """Of the areas in supply, the fewest steps by land from ``frm``; ties to the area
    whose key sorts first."""
    from revisionist.core.realism import territory

    board = state.map
    assert board is not None
    far = territory.steps_from(board, "land", [frm])
    keys = {t.area: t.key for t in board.territories}
    ranked = sorted((far[a], keys.get(a, a), a) for a in supplied if a in far)
    return ranked[0][2] if ranked else None


def status(state: "State", feature: "Feature") -> Status | None:
    """The piece's supply today, from the state alone; None when ``supply`` is off or the
    feature is not a piece that moves on the map."""
    from revisionist.core.realism import bases, kinds, territory
    from revisionist.core.realism.kinds import Domain

    board, kind = state.map, kinds.of(state, feature)
    if not on(state) or board is None or kind is None:
        return None
    own = territory.nation(state, feature.side)
    if own is None or kind.domain is Domain.ENVOY:
        return Status(True, None, None, None)
    if kind.domain is not Domain.LAND:
        found = bases.area_reach(state, feature, feature.places[0])
        if found is None:
            return Status(True, None, None, None)
        ok = found.tier in (bases.Tier.SUSTAINED, bases.Tier.OPERATE)
        return Status(ok, found.base if ok else None, found.steps if ok else None, None)
    area = territory.area_of(state, feature.places[0], Domain.LAND)
    if area is None:
        return Status(False, None, None, None)
    if any(z.area == area for z in board.sea_zones):
        return Status(True, None, None, None)
    reach = _reach(state, own, state.in_world_date)
    if area in reach:
        steps, src = reach[area]
        return Status(True, src, steps, None)
    if (behind := _behind(state, area, reach)) is not None:
        steps, src = behind
        return Status(True, src, steps + 1, None)
    return Status(False, None, None, _nearest(state, area, set(reach)))


def _behind(
    state: "State", area: EntityId, reach: dict[EntityId, tuple[int, EntityId]]
) -> tuple[int, EntityId] | None:
    """For a land piece in an area outside the network: the nearest land neighbour inside
    it short of the step limit, with its steps and source (ties as ``_reach`` breaks them).
    The last step, into the piece's own area, need not be friendly."""
    from revisionist.core.realism import territory
    from revisionist.core.realism.kinds import Domain

    board = state.map
    assert board is not None
    near = [
        reach[n]
        for n in territory.neighbours(board, area, Domain.LAND)
        if n in reach and reach[n][0] < SUPPLY_STEPS
    ]
    return min(near) if near else None


__all__ = ["SUPPLY_STEPS", "Status", "on", "sources", "status"]
