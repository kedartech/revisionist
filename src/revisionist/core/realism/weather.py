"""Weather by season (KWX): the world's calendar of weather, by region and month.

A world with ``weather`` names its kinds of weather and, for each region and each month,
which one holds; a region with no row of its own takes the row of the nearest region it
lies in. The table is the weather: no draw is made, so the same region and month always
give the same weather, a seat can plan on it, and every view holds it with the board.

With ``weather`` switched on, a kind of weather may add days to a step into an area of its
region, by the terrain entered and by the kind or domain of the piece; close an area of
its region to the kinds or domains it names; change a kind's attack or defence; and
ground the air, so that no piece gives air support, strikes or covers in or into its
region. A step is counted with the weather of the day it begins (``territory.step_days``,
``territory.plans``), and a battle's round with the weather of its day (``battle``). No
weather, region or month is named in code: the world names each.
"""

from collections.abc import Collection
from datetime import date
from typing import TYPE_CHECKING, Annotated, Literal, get_args

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId

if TYPE_CHECKING:
    from revisionist.core.realism.kinds import Change, PieceKind
    from revisionist.core.state import State

Month = Literal["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
"""[proposed] The months a region's row names in the world file."""
MONTHS: tuple[Month, ...] = get_args(Month)
"""The months in order, January first."""
Delta = Annotated[int, Field(ge=-4, le=4)]
"""A change to a figure: as far as a kind's own changes reach, across the range 1 to 5."""


class Slow(Model):
    """Days a weather adds to a step into an area of its region: for a step into the
    terrain named (every terrain when none), by a piece of a kind or domain named (every
    piece when none)."""

    days: Annotated[int, Field(ge=1)]
    terrain: tuple[Label, ...] = ()
    pieces: tuple[Label, ...] = ()


class Shift(Model):
    """A change to the attack or defence of the kinds or domains named (every kind when
    none), held to the figures' range."""

    attack: Delta = 0
    defence: Delta = 0
    pieces: tuple[Label, ...] = ()


class Closure(Model):
    """The areas of a region closed to the kinds or domains named: those of the terrain
    named, or every area when none."""

    pieces: tuple[Label, ...] = Field(min_length=1)
    terrain: tuple[Label, ...] = ()


class WeatherKind(Model):
    """One kind of weather the world names, and what it does where it holds."""

    key: Label
    name: Label
    slows: tuple[Slow, ...] = ()
    figures: tuple[Shift, ...] = ()
    grounds_air: bool = False
    """No air support, no strike and no cover in or into the region."""
    closes: tuple[Closure, ...] = ()


class Weather(Model):
    """The world's weather: its kinds by key, and for each region with a row the kind of
    weather that holds in each month, January first."""

    kinds: dict[Label, WeatherKind]
    regions: dict[Label, tuple[Label, ...]]

    @model_validator(mode="after")
    def _rows(self) -> "Weather":
        for region, row in self.regions.items():
            if len(row) != len(MONTHS):
                raise ValueError(f"weather: region {region} names {len(row)} months, not 12")
            for key in row:
                if key not in self.kinds:
                    raise ValueError(f"weather: region {region} names unknown weather {key}")
        return self


def on(state: "State") -> bool:
    """Whether the weather acts in this game: ``weather`` on, and a board that holds it."""
    from revisionist.core.state import Rule

    return Rule.WEATHER in state.rules and state.map is not None and state.map.weather is not None


class Sky:
    """The weather of one game, read area by area and day by day."""

    def __init__(self, state: "State") -> None:
        board = state.map
        assert board is not None and board.weather is not None
        self._weather = board.weather
        self._parent = {r.key: r.parent for r in board.regions}
        self._region = {t.area: t.region for t in board.territories}
        self._region |= {z.area: z.region for z in board.sea_zones}
        self._terrain = {t.area: t.terrain for t in board.territories}
        self._terrain |= {z.area: z.terrain for z in board.sea_zones}

    def holds(self, area: EntityId, day: date) -> WeatherKind | None:
        """The weather in ``area`` on ``day``: its region's row, else the row of the
        nearest region it lies in. None for an area of no region with a row."""
        region = self._region.get(area)
        seen: set[str] = set()
        while region is not None and region not in seen:
            row = self._weather.regions.get(region)
            if row is not None:
                return self._weather.kinds[row[day.month - 1]]
            seen.add(region)
            region = self._parent.get(region)
        return None

    def closed(self, kind: "PieceKind", area: EntityId, day: date) -> WeatherKind | None:
        """The weather that closes ``area`` to ``kind`` on ``day``, or None."""
        held = self.holds(area, day)
        terrain = self._terrain.get(area)
        if held is not None and any(
            _names(kind, c.pieces) and _on(terrain, c.terrain) for c in held.closes
        ):
            return held
        return None

    def step(self, kind: "PieceKind", area: EntityId, day: date) -> int | None:
        """Days the weather adds to a step of ``kind`` into ``area`` begun on ``day``; None
        when it closes the area to the kind."""
        held = self.holds(area, day)
        if held is None:
            return 0
        if self.closed(kind, area, day) is not None:
            return None
        terrain = self._terrain.get(area)
        return sum(s.days for s in held.slows if _on(terrain, s.terrain) and _any(kind, s.pieces))

    def shift(self, kind: "PieceKind", area: EntityId, day: date) -> tuple["Change", ...]:
        """What the weather in ``area`` on ``day`` does to ``kind``'s figures: each change
        that names it, in the world file's order."""
        from revisionist.core.realism.kinds import Change

        held = self.holds(area, day)
        found = () if held is None else held.figures
        return tuple(
            Change(attack=s.attack, defence=s.defence) for s in found if _any(kind, s.pieces)
        )

    def grounded(self, area: EntityId, day: date) -> bool:
        """Whether the air is grounded in ``area`` on ``day``."""
        held = self.holds(area, day)
        return held is not None and held.grounds_air


def sky(state: "State") -> Sky | None:
    """The game's weather, or None when it does not act."""
    return Sky(state) if on(state) else None


def holds(state: "State", area: EntityId, day: date) -> WeatherKind | None:
    """The weather in ``area`` on ``day``; None when the weather does not act."""
    found = sky(state)
    return None if found is None else found.holds(area, day)


def _names(kind: "PieceKind", names: Collection[str]) -> bool:
    return kind.key in names or kind.domain.value in names


def _any(kind: "PieceKind", names: Collection[str]) -> bool:
    """Every kind when ``names`` is empty, else a kind or domain it names."""
    return not names or _names(kind, names)


def _on(terrain: str | None, names: Collection[str]) -> bool:
    return not names or terrain in names


__all__ = [
    "MONTHS",
    "Closure",
    "Month",
    "Shift",
    "Sky",
    "Slow",
    "Weather",
    "WeatherKind",
    "holds",
    "on",
    "sky",
]
