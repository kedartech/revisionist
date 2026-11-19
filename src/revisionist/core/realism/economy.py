"""What a territory yields, and one war-economy figure per nation (YLD).

With ``economy`` switched on (it needs ``holders``), each land territory yields what the
world prints for it, by resource; a resource plays one of five roles. A nation's income
for a role, on a day, is the sum of that role's yields over the territories it holds that
day, each times the territory's factor (``factor``): income is counted from what is held,
never from orders filed.

A territory nobody has taken has factor 1. One taken from another holder pays its taker
nothing of its ``output`` and ``fuel`` for ``CAPTURE_LAG_DAYS``, then ``CAPTURE_SHARE``;
no ``manpower`` while occupied; its ``supply`` from ``SUPPLY_LAG_DAYS`` after it changed
hands; its ``prestige`` at once. One taken back by the holder the world gives it pays
``CAPTURE_SHARE`` of its ``output``, ``fuel`` and ``manpower`` for ``CAPTURE_LAG_DAYS``,
then all of it.

On the first day of each calendar month of the in-world date, every nation's ``output``
income is added to its output pool and its ``manpower`` income to its manpower pool
(``economy_set``, sealed to the nation's seats). A nation's pools are seen by its own
seats only (``seen_by``).

``figure`` is one number per nation, computed only from public facts (the board's printed
yields, holders and the days territories changed hands): the weighted sum of its output,
manpower and fuel incomes, scaled so that the largest nation at the start is 100.

``move_yield`` moves part of a yield between two territories of one holder and lands
``yield_changed``; the moved yield pays where it now lies.
"""

from datetime import date
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.realism.kinds import Role

if TYPE_CHECKING:
    from revisionist.core.events import Payload, YieldChanged
    from revisionist.core.realism.territory import Territory
    from revisionist.core.state import State, View, _World

CAPTURE_LAG_DAYS = 30  # [proposed] plan, YLD Defaults
"""Days a taken territory's output and fuel pay its taker nothing."""
CAPTURE_SHARE = 50  # [proposed] plan, YLD Defaults
"""The percent of a taken territory's output and fuel its taker gets after the lag."""
SUPPLY_LAG_DAYS = 7  # [proposed] plan, YLD Defaults
"""Days before a taken territory's supply works for its taker."""
WEIGHTS: dict[Role, int] = {Role.OUTPUT: 3, Role.MANPOWER: 1, Role.FUEL: 2}  # [proposed]
"""The weight of each income in the war-economy figure."""
FIGURE_TOP = 100
"""The figure of the largest nation at the start."""

Amount = Annotated[float, Field(ge=0)]


class EconomyError(ValueError):
    """A yield the rules cannot move."""


class Pools(Model):
    """A nation's pools, filled on the first of each month."""

    output: Amount = 0
    manpower: Amount = 0


class Economy(Model):
    """The war economy's truth. A seat sees its own nation's part only."""

    pools: dict[EntityId, Pools] = Field(default_factory=dict)
    """Each nation's pools, by ``economy_set``. Absent: nothing paid yet."""
    yields: dict[EntityId, dict[Label, Amount]] = Field(default_factory=dict)
    """Each territory whose yields have been moved: what it yields now, by resource key,
    by ``yield_changed``. Absent: what the board prints."""


def on(state: "_World") -> bool:
    """Whether the economy acts in this game: holders on, and ``economy`` too."""
    from revisionist.core.realism import holders
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return holders.on(state) and Rule.ECONOMY in rules


def holder(state: "State | View", area: EntityId) -> EntityId | None:
    """The polity holding a territory now."""
    from revisionist.core.realism import territory

    return territory.holder(state, area)


def _territories(state: "_World") -> tuple["Territory", ...]:
    board = state.map
    return () if board is None else tuple(sorted(board.territories, key=lambda t: t.area))


def _territory(state: "_World", area: EntityId) -> "Territory | None":
    return next((t for t in _territories(state) if t.area == area), None)


def yields_of(state: "State | View", area: EntityId) -> dict[str, float]:
    """What a territory yields now, by resource key: as moved, else as printed."""
    moved = state.economy.yields.get(area)
    if moved is not None:
        return dict(moved)
    t = _territory(state, area)
    return {} if t is None else dict(t.yields)


def _role_of(state: "_World", resource: str) -> Role | None:
    if state.kinds is None:
        return None
    found = state.kinds.resources.get(resource)
    return None if found is None else found.role


def factor(state: "State | View", area: EntityId, role: Role, day: date) -> float:
    """What share of a territory's yield of ``role`` its holder gets on ``day``."""
    held = state.holders.get(area)
    if held is None:
        return 1.0
    days = (day - held.on).days
    if role is Role.PRESTIGE:
        return 1.0
    if role is Role.SUPPLY:
        return 1.0 if days >= SUPPLY_LAG_DAYS else 0.0
    share = CAPTURE_SHARE / 100
    t = _territory(state, area)
    if t is not None and held.holder == t.holder:  # taken back by the world's holder
        return share if days < CAPTURE_LAG_DAYS else 1.0
    if role is Role.MANPOWER:
        return 0.0
    return 0.0 if days < CAPTURE_LAG_DAYS else share


def _income(
    state: "State | View", polity: EntityId, role: Role, day: date, *, printed: bool
) -> float:
    total = 0.0
    for t in _territories(state):
        if holder(state, t.area) != polity:
            continue
        found = dict(t.yields) if printed else yields_of(state, t.area)
        amount = sum(v for k, v in sorted(found.items()) if _role_of(state, k) is role)
        if amount:
            total += amount * factor(state, t.area, role, day)
    return round(total, 6)


def income(state: "State | View", polity: EntityId, role: Role, day: date) -> float:
    """A nation's income for ``role`` on ``day``: the role's yields over the territories it
    holds, each times its factor."""
    return _income(state, polity, role, day, printed=False)


def _weighted(state: "State | View", polity: EntityId, day: date, *, start: bool) -> float:
    total = 0.0
    for role, weight in WEIGHTS.items():
        if start:
            total += weight * sum(
                v
                for t in _territories(state)
                if t.holder == polity
                for k, v in sorted(t.yields.items())
                if _role_of(state, k) is role
            )
        else:
            total += weight * _income(state, polity, role, day, printed=True)
    return total


def _polities(state: "_World") -> list[EntityId]:
    from revisionist.core.ontology import EntityKind

    return sorted(k for k, e in state.entities.items() if e.kind is EntityKind.POLITY)


def figure(state: "State | View", polity: EntityId, day: date | None = None) -> float:
    """A nation's war-economy figure on ``day`` (default: the in-world date), from public
    facts only: the board's printed yields, holders and the days they changed hands. The
    weighted sum of its output, manpower and fuel incomes, scaled so that the largest
    nation at the start is 100; 0 when no nation had any at the start. One decimal."""
    today = state.in_world_date if day is None else day
    if today is None:
        return 0.0
    top = max((_weighted(state, p, today, start=True) for p in _polities(state)), default=0.0)
    if top <= 0:
        return 0.0
    return round(FIGURE_TOP * _weighted(state, polity, today, start=False) / top, 1)


def _pay(state: "State", polity: EntityId, day: date) -> Pools | None:
    """The polity's pools after the month's payment; None when it earns nothing."""
    earned = Pools(
        output=income(state, polity, Role.OUTPUT, day),
        manpower=income(state, polity, Role.MANPOWER, day),
    )
    if not earned.output and not earned.manpower:
        return None
    was = state.economy.pools.get(polity, Pools())
    return Pools(
        output=round(was.output + earned.output, 6),
        manpower=round(was.manpower + earned.manpower, 6),
    )


def walk(state: "State", day: date) -> list["Payload"]:
    """With ``economy`` on, the first of a month: every nation's pools paid, in id order."""
    from revisionist.core import events as ev

    if not on(state) or day.day != 1:
        return []
    out: list[Payload] = []
    for polity in _polities(state):
        paid = _pay(state, polity, day)
        if paid is not None:
            out.append(ev.EconomySet(polity=polity, pools=paid, on=day))
    return out


def refusal(
    state: "State", frm: EntityId, to: EntityId, resource: str, amount: float
) -> str | None:
    """Why a yield cannot be moved; None when it can."""
    if not on(state):
        return "the economy rule is off"
    if _territory(state, frm) is None or _territory(state, to) is None:
        return "a yield moves only between territories"
    if frm == to:
        return "a yield moves to another territory"
    owner = holder(state, frm)
    if owner is None or holder(state, to) != owner:
        return "a yield moves only between territories of one holder"
    if state.kinds is None or resource not in state.kinds.resources:
        return f"no resource {resource}"
    if not 0 < amount <= yields_of(state, frm).get(resource, 0):
        return "a move takes more than nothing and no more than the yield"
    return None


def move_yield(
    state: "State", frm: EntityId, to: EntityId, resource: str, amount: float, on: date
) -> "YieldChanged":
    """Move ``amount`` of ``resource``'s yield from ``frm`` to ``to``, two territories of
    one holder; the ``yield_changed`` to land. Raises ``EconomyError`` when it cannot."""
    from revisionist.core import events as ev

    why = refusal(state, frm, to, resource, amount)
    if why is not None:
        raise EconomyError(why)
    return ev.YieldChanged(area=frm, to=to, resource=resource, amount=amount, on=on)


def moved(state: "State", frm: EntityId, to: EntityId, resource: str, amount: float) -> Economy:
    """The economy after a move ``refusal`` allows."""
    out = dict(state.economy.yields)
    there = yields_of(state, frm)
    there[resource] = round(there[resource] - amount, 6)
    out[frm] = {k: v for k, v in there.items() if v}
    here = yields_of(state, to)
    here[resource] = round(here.get(resource, 0) + amount, 6)
    out[to] = here
    return state.economy.model_copy(update={"yields": out})


def seen_by(state: "State", seat: SeatId) -> Economy:
    """What ``seat`` sees of the economy: its own nation's pools, and the moved yields of
    the territories its nation holds. Nothing for a seat of no nation."""
    from revisionist.core.realism.war import polity_of

    me = state.seats.get(seat)
    own = polity_of(state, me.embodies) if me is not None else None
    if own is None:
        return Economy()
    return Economy(
        pools={k: v for k, v in state.economy.pools.items() if k == own},
        yields={k: v for k, v in state.economy.yields.items() if holder(state, k) == own},
    )


__all__ = [
    "CAPTURE_LAG_DAYS",
    "CAPTURE_SHARE",
    "SUPPLY_LAG_DAYS",
    "WEIGHTS",
    "Economy",
    "EconomyError",
    "Pools",
    "factor",
    "figure",
    "holder",
    "income",
    "move_yield",
    "moved",
    "on",
    "refusal",
    "seen_by",
    "walk",
    "yields_of",
]
