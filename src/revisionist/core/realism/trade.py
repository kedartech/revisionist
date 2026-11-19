"""Fuel and trade: oil is spent to move, and a trade line can be cut (FUL).

With ``fuel`` switched on (it needs ``economy``), each nation keeps a fuel stock in its
pools (``Pools.fuel``). It starts at the world's figure (``fuel_stocks``), or at
``STOCK_MONTHS`` of the nation's fuel income when the world gives none. On the first of
each month the stock gains the nation's ``fuel`` income, and each open trade line pays
its amount a month into the pool of the role its resource plays (``economy.walk``).

A world may carry trade lines (``trade_lines``): a key, the nation it runs from
(``exporter``) and the one it runs to (``importer``), a resource, an amount a month,
whether it starts cut, and a source or a gap. A
line pays nothing while it is cut, or while its two nations are at war with each other.
``set`` opens or cuts a line and lands ``trade_set``; the rule name ``trade`` is the
forms' way to it. Lines are sealed to the two nations a line joins.

A step by a piece whose kind has ``fuel_per_step`` spends that much from its nation's
stock when the step starts, in the day walk (``resolvers.movement.walk``); with too
little stock the step is refused with the reason (``step_refused``) and the piece holds
where it stands.
"""

from datetime import date
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId
from revisionist.core.realism.kinds import Role

if TYPE_CHECKING:
    from revisionist.core.events import TradeSet
    from revisionist.core.realism.geography import Feature
    from revisionist.core.state import State, View, _World

STOCK_MONTHS = 6  # [proposed] plan, FUL Defaults
"""Months of its fuel income a nation's stock starts at when the world gives no figure."""

PAID_ROLES = frozenset({Role.OUTPUT, Role.MANPOWER, Role.FUEL})
"""The roles a trade line may carry: the three a nation keeps a pool of."""

Amount = Annotated[float, Field(ge=0)]


class TradeError(ValueError):
    """A trade line the rules cannot open or cut."""


class TradeLine(Model):
    """A trade line: ``amount`` of ``resource`` a month from ``exporter`` to ``importer``."""

    key: Label
    exporter: EntityId
    importer: EntityId
    resource: Label
    amount: Amount
    """A month."""
    cut: bool = False
    source: Label | None = None
    """The world's source key for the line's figures; None for a gap."""


def on(state: "_World") -> bool:
    """Whether fuel and trade act in this game: the economy on, and ``fuel`` too."""
    from revisionist.core.realism import economy
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return economy.on(state) and Rule.FUEL in rules


_fuel_on = on  # ``set`` takes a parameter named ``on``


def role_of(state: "_World", resource: str) -> Role | None:
    if state.kinds is None:
        return None
    found = state.kinds.resources.get(resource)
    return None if found is None else found.role


def paying(state: "State | View", line: TradeLine) -> bool:
    """Whether a line pays: open, and its two nations not at war with each other."""
    from revisionist.core.realism.war import at_war

    return not line.cut and not at_war(state, line.exporter, line.importer)


def paid_to(state: "State | View", polity: EntityId, role: Role) -> float:
    """What the open lines into ``polity`` pay it a month for ``role``, in key order."""
    return round(
        sum(
            line.amount
            for _, line in sorted(state.economy.lines.items())
            if line.importer == polity
            and role_of(state, line.resource) is role
            and paying(state, line)
        ),
        6,
    )


def refusal(state: "State", line: TradeLine) -> str | None:
    """Why a line cannot stand as given; None when it can."""
    from revisionist.core.ontology import EntityKind

    if not on(state):
        return "the fuel rule is off"
    for polity in (line.exporter, line.importer):
        found = state.entities.get(polity)
        if found is None or found.kind is not EntityKind.POLITY:
            return f"{polity} is not a polity"
    if line.exporter == line.importer:
        return "a line runs between two nations"
    if role_of(state, line.resource) not in PAID_ROLES:
        return f"a line carries output, manpower or fuel, not {line.resource}"
    was = state.economy.lines.get(line.key)
    if was is not None and was.model_copy(update={"cut": line.cut}) != line:
        return f"line {line.key}: only whether it is cut changes"
    return None


def set(state: "State", line: str, open: bool, on: date) -> "TradeSet":
    """Open or cut the line keyed ``line`` from ``on``: the ``trade_set`` to land. Raises
    ``TradeError`` when it cannot."""
    from revisionist.core import events as ev

    if not _fuel_on(state):
        raise TradeError("the fuel rule is off")
    found = state.economy.lines.get(line)
    if found is None:
        raise TradeError(f"no trade line {line}")
    return ev.TradeSet(line=found.model_copy(update={"cut": not open}), on=on)


def seen(state: "State", polity: EntityId) -> dict[str, TradeLine]:
    """The lines ``polity`` is a party to."""
    return {k: v for k, v in state.economy.lines.items() if polity in (v.exporter, v.importer)}


def cost(state: "State", piece: "Feature") -> float:
    """The fuel a step of this piece spends when it starts; 0 with ``fuel`` off."""
    from revisionist.core.realism import kinds

    kind = kinds.of(state, piece)
    return kind.fuel_per_step if kind is not None and on(state) else 0.0


def unit(state: "_World") -> tuple[str, str]:
    """The name and unit the stock is told in: the world's first fuel resource's."""
    from revisionist.core.realism.kinds import with_role

    found = with_role(state, Role.FUEL)
    return (found[0].name, found[0].unit) if found else ("Fuel", "units")


__all__ = [
    "PAID_ROLES",
    "STOCK_MONTHS",
    "TradeError",
    "TradeLine",
    "cost",
    "on",
    "paid_to",
    "paying",
    "refusal",
    "role_of",
    "seen",
    "set",
    "unit",
]
