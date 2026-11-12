"""What a person nobody plays does back (strategy step 2).

An answer is written per person in the world file: when an act of a given kind lands
from a given quarter (or on a fixed cadence), the person files an order of their own
some days later, through the same routing as a player's. Code decides; no model is asked.
"""

from datetime import date
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, MandateId, OrderId, ScheduledEventId
from revisionist.core.realism.effect import Effect, EffectKind
from revisionist.core.realism.stance import Stance

ParamValue = int | Annotated[str, StringConstraints(max_length=200)]
"""An int, an enum choice, an entity ID or a short text, as a lever's spec says."""

ENTITY_FIELDS = ("counterparty", "person", "recipient", "audience", "target", "to", "of", "toward")
"""The fields of an effect that name a person, polity or place."""


class AnswerWhen(Model):
    """What sets an answer off: a form filed through to the end (``lever``), a typed
    act that landed (``effect``), or a date on a cadence (``every_days``)."""

    lever: Label | None = None
    params: dict[Label, tuple[ParamValue, ...]] = Field(default_factory=dict)
    """Only acts whose form had one of these values for each name."""
    effect: EffectKind | None = None
    party: EntityId | None = None
    """For an effect: the person or polity it names, such as a deal's other side."""
    by: EntityId | None = None
    """The person, or polity for everyone in it, whose act it must be."""
    human: bool = False
    """Only an act a seat with a desk filed."""
    every_days: int | None = Field(default=None, ge=1, le=365)
    start: date | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        kinds = [self.lever is not None, self.effect is not None, self.every_days is not None]
        if sum(kinds) != 1:
            raise ValueError("an answer is set off by exactly one of lever, effect, every_days")
        if self.params and self.lever is None:
            raise ValueError("params belong to a lever")
        if self.party is not None and self.effect is None:
            raise ValueError("party belongs to an effect")
        if self.every_days is None:
            if self.by is None or self.start is not None:
                raise ValueError("an act sets an answer off only with by, and no start")
        elif self.start is None or self.by is not None or self.human:
            raise ValueError("a cadence needs start, and no by or human")
        return self


class AnswerAct(Model):
    """What the person does: one of their own forms, or a typed effect inside their
    authority."""

    lever: Label | None = None
    params: dict[Label, ParamValue] = Field(default_factory=dict)
    effect: Effect | None = None

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.lever is None) == (self.effect is None):
            raise ValueError("an answer acts by exactly one of lever, effect")
        if self.params and self.lever is None:
            raise ValueError("params belong to a lever")
        return self


class Answer(Model):
    """One thing a person does back, with when, how soon and how often."""

    key: Label
    aim: int = Field(ge=1, le=3)
    """Which of the card's aims it serves, counting from 1."""
    when: AnswerWhen
    gate: frozenset[Stance] = frozenset()
    """The person's stance toward the one who acted must be one of these. Empty: any."""
    act: AnswerAct
    delay_days: int = Field(ge=0, le=30)
    cooldown_days: int = Field(ge=1, le=365)
    until: ScheduledEventId | None = None
    """A history item; once it has fired the answer is retired."""
    helps: bool = False
    """A good turn: it costs no regard toward the one it answers."""


class AnswerLog(Model):
    """The last time a person took up one answer, and what came of it."""

    planned: date
    due: date
    cause: OrderId | None = None
    """The act it answers. None for a cadence."""
    toward: EntityId | None = None
    """Who acted, or for a cadence the person the act is meant for."""
    made: date | None = None
    order: OrderId | None = None
    mandate: MandateId | None = None
    """For a deal with a person a player holds: the approach put to that player."""
    refusal: Label = ""
    """Why nothing was filed, when nothing was."""


__all__ = ["ENTITY_FIELDS", "Answer", "AnswerAct", "AnswerLog", "AnswerWhen", "ParamValue"]
