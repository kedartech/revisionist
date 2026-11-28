"""Laws as world data (LWC).

A world may carry ``laws``: each a key, a title, the nation it binds, its clauses, the
quantity that says it has passed, and optionally what it does, from a closed set the rules
know, and whether it touches daily life. They reach state once, by ``laws_declared``, and
are read only with the ``laws`` rule on. With it off every reader here returns what the
code tables give today (``votes.in_force``, read only), so a stored game and a world that
declares no law behave as before.

No rule reads a clause's wording to decide what a law does: that is ``does``. A clause's
subject is only matched, as a lock's condition names it. Nothing here names a law, a
clause, a nation or a quantity: every one comes from the world file.
"""

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, QuantityId
from revisionist.core.realism.effect import Clause
from revisionist.core.realism.quantity import Quantity

if TYPE_CHECKING:
    from revisionist.core.state import State


class Does(StrEnum):
    """What a passed law does, from the closed set the rules know [proposed]."""

    ARMS_MERCHANT_SHIPS = "arms_merchant_ships"
    """Its nation's merchant ships are armed (shipping's losses, LAW)."""
    ADDS_MANPOWER = "adds_manpower"
    """Its nation's manpower pool gains the effect's amount (LAW)."""


class LawEffect(Model):
    """What a law does once passed: a kind, and for ``adds_manpower`` its amount."""

    kind: Does
    amount: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _amount(self) -> "LawEffect":
        if (self.kind is Does.ADDS_MANPOWER) != (self.amount is not None):
            raise ValueError("adds_manpower, and only adds_manpower, names an amount")
        return self


class Law(Model):
    """One law the world declares: public rules of the world."""

    key: Label
    title: Label
    nation: EntityId
    """The nation the law binds."""
    clauses: tuple[Clause, ...] = Field(min_length=1, max_length=12)
    passed: QuantityId
    """The quantity that reads 1 once the law has passed."""
    does: LawEffect | None = None
    daily_life: bool = False
    """Whether the law touches daily life (read by HCL)."""


def on(state: "State") -> bool:
    from revisionist.core.state import Rule

    return Rule.LAWS in state.rules


def carrying(state: "State", subject: str) -> tuple[Law, ...]:
    """The declared laws with a clause on ``subject``, in the world's order."""
    return tuple(law for law in state.laws if subject in {c.subject for c in law.clauses})


def in_force(state: "State", subject: str) -> dict[EntityId, date]:
    """Each nation bound by a passed law carrying the clause ``subject``, and the first day
    its passed quantity read 1. With ``laws`` on only the declared laws are read; with it
    off, what ``votes.in_force`` returns."""
    if not on(state):
        from revisionist.core.realism.resolvers.votes import in_force as tabled

        return tabled(state, subject)
    out: dict[EntityId, date] = {}
    for law in carrying(state, subject):
        q = state.quantities.get(law.passed)
        if q is None or q.value != 1:
            continue
        out[law.nation] = min(out.get(law.nation, q.as_of), q.as_of)
    return out


def flags(state: "State", subject: str) -> tuple[Quantity, ...]:
    """The quantities that say whether a law carrying ``subject`` has passed: the declared
    laws' with ``laws`` on, else the code table's passed flags the world declares."""
    if on(state):
        found = (state.quantities.get(law.passed) for law in carrying(state, subject))
    else:
        from revisionist.core.realism.resolvers import qid
        from revisionist.core.realism.resolvers.votes import HISTORICAL

        found = (
            state.quantities.get(qid(state, f"{bill}_passed"))
            for bill, measure in sorted(HISTORICAL.items())
            if subject in {c.subject for c in measure.clauses}
        )
    return tuple(q for q in found if q is not None)


__all__ = ["Does", "Law", "LawEffect", "carrying", "flags", "in_force", "on"]
