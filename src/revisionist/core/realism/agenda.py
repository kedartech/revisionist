"""The agenda, play styles and the options a seat is offered (engine v2; spec §8.5-8.6).

A mandate is an issued goal: code fills the template and compiles its success
condition; the model only words it. A seat holds at most ``MANDATE_CAP`` live
mandates. A play style is a private setting of the seat; options are ordinary
orders, so picking one files exactly what a free player could have typed.
"""

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from revisionist.core._base import Model
from revisionist.core.goals import WinCondition
from revisionist.core.ids import EntityId, MandateId, OrderId, SeatId
from revisionist.core.realism.effect import Effect, EffectKind
from revisionist.core.visibility import Scope

MANDATE_CAP = 3
"""Live mandates per seat (spec §8.5)."""


class MandateKind(StrEnum):
    ORDER = "order"
    """From a principal. Pays standing or means on success."""
    CRISIS = "crisis"
    """From the state of the world. Pays nothing; success avoids loss."""
    BLOWBACK = "blowback"
    """From the seat's own earlier act. Pays nothing."""
    OPPORTUNITY = "opportunity"
    """A window. Ignoring it costs nothing."""


class MandateStatus(StrEnum):
    LIVE = "live"
    MET = "met"
    FAILED = "failed"
    EXPIRED = "expired"


class Mandate(Model):
    mandate_id: MandateId
    seat_id: SeatId
    kind: MandateKind
    issuer: EntityId | None = None
    """Who issued it: a principal for an order. None: the world itself."""
    text: str = Field(min_length=1, max_length=400)
    """The model's wording. Scanned for leaks like any page."""
    condition: WinCondition
    issued: date
    expires: date
    cause: OrderId | None = None
    """Blowback only: the seat's own order it came from."""
    status: MandateStatus = MandateStatus.LIVE
    scope: Scope
    canary: str | None = None
    """Test-only unique marker, as on Fact."""

    @model_validator(mode="after")
    def _shape(self) -> "Mandate":
        if self.expires <= self.issued:
            raise ValueError(f"mandate {self.mandate_id}: expires after it is issued")
        if (self.kind is MandateKind.BLOWBACK) != (self.cause is not None):
            raise ValueError(f"mandate {self.mandate_id}: blowback, and only blowback, has a cause")
        if (self.kind is MandateKind.ORDER) != (self.issuer is not None):
            raise ValueError(
                f"mandate {self.mandate_id}: an order, and only an order, has an issuer"
            )
        return self


class PlayStyle(StrEnum):
    FREE = "free"
    GUIDED = "guided"
    BEGINNER = "beginner"


class Ask(Model):
    """One part of an order before it is routed: what the seat wants, in short words,
    and the typed effect where the reader found one."""

    ask: str = Field(min_length=1, max_length=300)
    effect: Effect | None = None


class Option(Model):
    """A guided step or a beginner option: an ordinary order and what it risks,
    as the seat understands it."""

    label: str = Field(min_length=1, max_length=120)
    asks: tuple[Ask, ...] = Field(min_length=1, max_length=8)
    to: EntityId | None = None
    """Who it goes to. None: the seat acts itself."""
    risk: str = Field(default="", max_length=300)
    historical: bool = False
    """What history did. Labelled so in the client (spec §8.6)."""


class Offer(Model):
    """What a seat is offered for one agenda item."""

    mandate_id: MandateId | None = None
    """None: for the seat's initiative, outside the agenda."""
    style: PlayStyle
    options: tuple[Option, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def _shape(self) -> "Offer":
        if self.style is PlayStyle.FREE:
            raise ValueError("a free seat is offered nothing")
        if self.style is PlayStyle.BEGINNER:
            if not 3 <= len(self.options) <= 4:
                raise ValueError("a beginner is offered 3 or 4 options")
            if sum(o.historical for o in self.options) > 1:
                raise ValueError("at most one option is what history did")
        elif len(self.options) != 1 or not 3 <= len(self.options[0].asks) <= 5:
            raise ValueError("a guided plan is one option of 3 to 5 orders")
        return self


STANDING_DEFAULT: frozenset[EffectKind] = frozenset()
"""Irreversible kinds an aide may order for an absent seat when the seat has named none."""


__all__ = [
    "MANDATE_CAP",
    "STANDING_DEFAULT",
    "Ask",
    "Mandate",
    "MandateKind",
    "MandateStatus",
    "Offer",
    "Option",
    "PlayStyle",
]
