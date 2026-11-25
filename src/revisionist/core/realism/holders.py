"""Who holds each territory, and capture that takes time (THL).

With ``holders`` switched on (it needs ``territories``), every land territory starts with
the holder the world gives it; sea zones have none. Holders are public: every view holds
them, and each change lands one public ``area_held`` event with the new holder, the old
one and the day.

A territory is taken in the day walk, never on a filing: a land piece that has stood for
``CAPTURE_DAYS`` full days in a territory held by a polity at war with its side, with no
land piece there of a polity at war with its own, takes it for its side. The count is kept
per territory, engine only (``capture_counted``), from the end of the first day the walk
sees the condition: the day a piece steps in is not a full day, and a condition that
began between wakes (a war filed, a piece placed) counts from the end of the next walked
day, so a territory is never taken early. The count stops the day the condition fails.

A territory holding a polity's capital site does not change at once. When the count is
full it is marked as falling: each seat of the holder gets a paper that day, and a matter
due on its agenda while the mark stands (``falling``). At the close of the wake after the
one it was marked in, it changes only if the count is still full; otherwise the mark is
dropped. So a capital falls only after a whole wake's notice.

A base serves a side only while that side or an ally holds the territory it lies in
(``serves``); a base within a sea zone has no holder and serves as declared.
"""

from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING

from pydantic import model_validator

from revisionist.core._base import Model
from revisionist.core.ids import DocumentId, EntityId, SeatId, derived_id

if TYPE_CHECKING:
    from revisionist.core.events import Payload
    from revisionist.core.realism.territory import Base
    from revisionist.core.state import State, View, _World

CAPTURE_DAYS = 2  # [proposed] plan, THL Defaults
"""Full days a land piece stands in an enemy territory, unopposed, before it takes it."""

LINE = 60


class Holding(Model):
    """A territory that has changed hands: its holder now, the one it was taken from, and
    the day it was taken. Public."""

    holder: EntityId
    taken_from: EntityId | None = None
    on: date


class Capture(Model):
    """A territory's capture count and capital mark. Engine only.

    ``by`` and ``since``: the polity whose land pieces have stood there unopposed, and the
    first day they did; None while nobody counts. ``marked``: the tick of the wake in which
    a capital's territory was marked as falling, and ``marked_on`` its day; None unmarked."""

    by: EntityId | None = None
    since: date | None = None
    marked: int | None = None
    marked_on: date | None = None

    @model_validator(mode="after")
    def _shape(self) -> "Capture":
        if (self.by is None) != (self.since is None):
            raise ValueError("a capture count names its side and its first day together")
        if (self.marked is None) != (self.marked_on is None):
            raise ValueError("a capital mark names its wake and its day together")
        if self.by is None and self.marked is None:
            raise ValueError("a capture with no count and no mark is no capture")
        return self

    def full(self, day: date) -> bool:
        """Whether the count has run ``CAPTURE_DAYS`` full days by the end of ``day``."""
        return self.since is not None and (day - self.since).days >= CAPTURE_DAYS


def on(state: "_World") -> bool:
    """Whether holders act in this game: the territory rules on, and ``holders`` too."""
    from revisionist.core.realism import territory
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return territory.on(state) and Rule.HOLDERS in rules  # type: ignore[arg-type]


def holder(state: "State | View", area: EntityId) -> EntityId | None:
    """The polity holding a territory now; None for a sea zone or one nobody holds."""
    from revisionist.core.realism import territory

    return territory.holder(state, area)


def capitals_in(state: "State | View", area: EntityId) -> tuple[EntityId, ...]:
    """The polities whose capital site lies in ``area``, in id order."""
    board = state.map
    if board is None:
        return ()
    return tuple(
        sorted(
            polity
            for polity, place in board.capitals.items()
            if place == area or ((e := state.entities.get(place)) is not None and e.within == area)
        )
    )


def _land_nations(state: "State", area: EntityId, taking: bool = False) -> set[EntityId]:
    """The polities with a land piece standing in ``area``; with ``taking``, only pieces
    that take ground by standing in it (``battle.holds_ground``)."""
    from revisionist.core.realism import battle, kinds, territory
    from revisionist.core.realism.geography import FeatureKind, in_play
    from revisionist.core.realism.kinds import Domain

    out: set[EntityId] = set()
    for f in state.features.values():
        if f.kind is not FeatureKind.PIECE or f.side is None or not in_play(f):
            continue
        if kinds.domain(state, f) is not Domain.LAND:
            continue
        if territory.area_of(state, f.places[0], Domain.LAND) != area:
            continue
        if taking and not battle.holds_ground(state, f):
            continue
        own = territory.nation(state, f.side)
        if own is not None:
            out.add(own)
    return out


def takers(state: "State", area: EntityId) -> tuple[EntityId, ...]:
    """The polities whose land pieces in ``area`` would take it: at war with its holder
    and no armistice between them (PEA), and with no land piece there of a polity at war
    with them; a piece whose kind does not hold ground takes nothing (KBA). In id order."""
    from revisionist.core.realism.war import at_war, hostile

    held = holder(state, area)
    if held is None:
        return ()
    here = _land_nations(state, area)
    return tuple(
        sorted(
            n
            for n in _land_nations(state, area, taking=True)
            if hostile(state, n, held) and not any(at_war(state, n, m) for m in here)
        )
    )


def _counted(state: "State", area: EntityId, day: date) -> "Capture | None":
    """The area's count at the end of ``day``: kept while its side still takes, else
    started by the first taker in id order, else stopped. A mark stays either way."""
    was = state.captures.get(area)
    found = takers(state, area)
    mark = {} if was is None else {"marked": was.marked, "marked_on": was.marked_on}
    if was is not None and was.by is not None and was.by in found:
        return was
    if found:
        return Capture(by=found[0], since=day, **mark)
    return Capture(**mark) if mark.get("marked") is not None else None


def _clip(text: str) -> str:
    return text if len(text) <= LINE else text[: LINE - 1] + "\N{HORIZONTAL ELLIPSIS}"


def holding_seats(state: "State", polity: EntityId) -> tuple[SeatId, ...]:
    """The seats with a desk whose person belongs to ``polity``, played or not, in id order
    (invariant 2: the paper goes whether or not the player is present)."""
    from revisionist.core.realism import actors
    from revisionist.core.realism.war import polity_of

    readers = actors.readers(state)
    return tuple(
        sorted(
            s.seat_id
            for s in state.seats.values()
            if s.seat_id in readers and polity_of(state, s.embodies) == polity
        )
    )


def paper_id(state: "State", area: EntityId, day: date, seat: SeatId) -> DocumentId:
    return DocumentId(derived_id(state.campaign_id, "falling", area, day.isoformat(), seat))


def _papers(state: "State", area: EntityId, day: date) -> list["Payload"]:
    """A paper to each seat of the holder: its capital's territory is marked to fall."""
    from revisionist.core import events as ev
    from revisionist.core.realism.card import ChannelKind
    from revisionist.core.realism.document import (
        BodyField,
        Classification,
        DocumentKind,
        DocumentTruth,
        DocumentView,
    )
    from revisionist.core.visibility import private_to

    held = holder(state, area)
    if held is None:
        return []
    name = state.entities[area].name
    out: list[Payload] = []
    for seat in holding_seats(state, held):
        doc_id = paper_id(state, area, day, seat)
        if doc_id in state.documents:
            continue
        out.append(
            ev.DocumentIssued(
                document=DocumentView(
                    doc_id=doc_id,
                    kind=DocumentKind.REPORT,
                    author=held,
                    issued=day,
                    arrives=day,
                    channel=ChannelKind.CABLE,
                    classification=Classification.CONFIDENTIAL,  # [proposed]
                    title=_clip(f"{name} will fall at the next close"),
                    body=(
                        BodyField(label="Territory", value=_clip(name)),
                        BodyField(label="Falls", value="At the close of the next wake"),
                        BodyField(label="Unless", value="No enemy holds it unopposed then"),
                    ),
                    scope=private_to(seat),
                ),
                truth=DocumentTruth(doc_id=doc_id),
            )
        )
    return out


def _land_areas(state: "State") -> list[EntityId]:
    board = state.map
    assert board is not None
    return sorted(t.area for t in board.territories)


def _taken(state: "State", area: EntityId, by: EntityId, day: date) -> "Payload":
    from revisionist.core import events as ev

    return ev.AreaHeld(area=area, holder=by, was=holder(state, area), on=day)


def walk(state: "State", day: date) -> list["Payload"]:
    """With ``holders`` on, the end of ``day`` in every land territory, in id order: each
    count kept, started or stopped (``capture_counted``), each territory whose count is
    full taken (``area_held``), and each capital's territory whose count is full marked as
    falling, with a paper to each seat of its holder."""
    from revisionist.core import events as ev

    if not on(state):
        return []
    out: list[Payload] = []
    for area in _land_areas(state):
        was = state.captures.get(area)
        now = _counted(state, area, day)
        papers: list[Payload] = []
        if now is not None and now.by is not None and now.full(day):
            if not capitals_in(state, area):
                out.append(_taken(state, area, now.by, day))
                continue
            if now.marked is None:
                now = now.model_copy(update={"marked": state.tick, "marked_on": day})
                papers = _papers(state, area, day)
        if now != was:
            out.append(ev.CaptureCounted(area=area, capture=now))
        out += papers
    return out


def record_takes(
    state: "State", claims: Sequence[tuple[EntityId, EntityId]], day: date
) -> list["Payload"]:
    """With ``holders`` on, the territories scripted legs falling due on ``day`` pass to
    their pieces' nations (HSA rule 3): ``claims`` are (territory, nation) pairs. A claim
    lands ``area_held`` unless a battle has been fought there, a land piece of a polity at
    war with the nation stands there as the day began, the nation already holds it, or
    another nation claims it the same day; there the rules decide. In territory id order."""
    from revisionist.core.realism.war import at_war

    if not on(state):
        return []
    by: dict[EntityId, set[EntityId]] = {}
    for area, nation in claims:
        by.setdefault(area, set()).add(nation)
    out: list[Payload] = []
    for area, nations in sorted(by.items()):
        if len(nations) != 1 or area in state.fought or area in state.battles:
            continue
        (nation,) = nations
        if holder(state, area) == nation:
            continue
        if any(at_war(state, nation, n) for n in _land_nations(state, area)):
            continue
        out.append(_taken(state, area, nation, day))
    return out


def start_count(
    state: "State", won: Sequence[tuple[EntityId, EntityId]], day: date
) -> list["Payload"]:
    """With ``holders`` on, the count a won battle starts (BTL): for each territory and the
    nation that won the battle in it, a count from ``day`` when that nation now takes it
    (rule 2: at war with its holder, no enemy land piece left). A count it already keeps,
    and a capital mark, stay. Read after the battle's events have landed."""
    from revisionist.core import events as ev

    if not on(state):
        return []
    board = state.map
    assert board is not None
    land = {t.area for t in board.territories}
    out: list[Payload] = []
    for area, by in sorted(won):
        if area not in land or by not in takers(state, area):
            continue
        was = state.captures.get(area)
        if was is not None and was.by == by:
            continue
        mark = {} if was is None else {"marked": was.marked, "marked_on": was.marked_on}
        out.append(ev.CaptureCounted(area=area, capture=Capture(by=by, since=day, **mark)))
    return out


def close(state: "State", day: date) -> list["Payload"]:
    """With ``holders`` on, the close of a wake on ``day``: each capital's territory marked
    in an earlier wake falls if its count is still full, else loses its mark."""
    from revisionist.core import events as ev

    if not on(state):
        return []
    out: list[Payload] = []
    for area in sorted(state.captures):
        c = state.captures[area]
        if c.marked is None or c.marked >= state.tick:
            continue
        if c.by is not None and c.full(day):
            out.append(_taken(state, area, c.by, day))
            continue
        kept = c.model_copy(update={"marked": None, "marked_on": None}) if c.by else None
        out.append(ev.CaptureCounted(area=area, capture=kept))
    return out


def falling(state: "State", seat: SeatId) -> list[tuple[EntityId, date]]:
    """Each territory marked to fall that ``seat``'s polity holds, with the day it was
    marked: a matter due on that seat's agenda at this wake's close, named by its paper
    (``paper_id``). Built from the state alone, so it reads the same whether or not the
    seat's player is present."""
    from revisionist.core.realism.war import polity_of

    held = state.seats.get(seat)
    own = polity_of(state, held.embodies) if held is not None else None
    if own is None:
        return []
    return [
        (area, c.marked_on)
        for area, c in sorted(state.captures.items())
        if c.marked_on is not None and holder(state, area) == own
    ]


def serves(state: "State | View", base: "Base", polity: EntityId | None) -> bool:
    """Whether ``base`` serves ``polity``: named among its sides and, with ``holders`` on,
    its territory held by that polity or an ally. A base within a sea zone has no holder."""
    from revisionist.core.realism import territory

    if polity is None or polity not in base.sides:
        return False
    if not on(state) or base.land is None:
        return True
    held = holder(state, base.land)
    return held is not None and (held == polity or territory.allied(state, polity, held))  # type: ignore[arg-type]


__all__ = [
    "CAPTURE_DAYS",
    "Capture",
    "Holding",
    "capitals_in",
    "close",
    "falling",
    "holder",
    "holding_seats",
    "on",
    "paper_id",
    "serves",
    "start_count",
    "takers",
    "walk",
]
