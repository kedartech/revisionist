"""The effect vocabulary, routes and fidelity (engine v2; spec §8.2-8.3).

One closed set of typed effects works on any object in the world. A seat's
order is read into parts, each one effect, and each part is routed:

- ``command``: inside the seat's authority; an executor carries it out with a
  fidelity, and no one approves it;
- ``process``: it needs an institution, so it runs a pipeline;
- ``influence``: it is aimed at the person who holds the power.

Where no code rule covers a part, the estimator returns effects from this same
vocabulary, inside the bounds the types set here (a disposition moves at most
``DISPOSITION_CAP`` per order). Pure data: routing and resolving are the engine's.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated, ClassVar, Literal

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import EntityId, FactId, FeatureId, OrderId, PipelineId, SeatId

DISPOSITION_CAP = 2
"""The most one order may move a disposition, either way (spec §8.3)."""


class Route(StrEnum):
    COMMAND = "command"
    PROCESS = "process"
    INFLUENCE = "influence"


class Fidelity(StrEnum):
    """How an executor carried out a command (spec §8.2)."""

    FULL = "full"
    LOOSE = "loose"
    SLOW = "slow"
    PARTIAL = "partial"


class EffectKind(StrEnum):
    MOVE_FORCE = "move_force"
    ENGAGEMENT = "engagement"
    ALLOCATE = "allocate"
    APPOINTMENT = "appointment"
    MEASURE = "measure"
    STATEMENT = "statement"
    INVESTIGATE = "investigate"
    DEAL = "deal"
    DISPOSITION = "disposition"
    DISCLOSURE = "disclosure"


class Posture(StrEnum):
    PATROL = "patrol"
    ESCORT = "escort"
    HOLD = "hold"
    ATTACK = "attack"
    WITHDRAW = "withdraw"


class Engagement(StrEnum):
    HOLD_FIRE = "hold_fire"
    DEFEND = "defend"
    ESCORT = "escort"
    SHOOT_ON_SIGHT = "shoot_on_sight"


class MoveForce(Model):
    """Move a force, posture it, or both."""

    kind: Literal["move_force"] = "move_force"
    force: FeatureId
    to: EntityId | None = None
    """A place. None: it stays where it is."""
    posture: Posture | None = None

    @model_validator(mode="after")
    def _does_something(self) -> "MoveForce":
        if self.to is None and self.posture is None:
            raise ValueError("a force order moves the force or postures it")
        return self


class SetEngagement(Model):
    kind: Literal["engagement"] = "engagement"
    force: FeatureId | None = None
    """None: every force under the seat's command in the zone."""
    zone: Label
    rule: Engagement


class Allocate(Model):
    """Money or materiel to a recipient."""

    kind: Literal["allocate"] = "allocate"
    recipient: EntityId
    what: Label
    amount: int = Field(ge=0)
    unit: Label


class Appointment(Model):
    kind: Literal["appointment"] = "appointment"
    person: EntityId
    office: Label
    appoint: bool = True
    """False: a dismissal."""


class ClauseKind(StrEnum):
    MONEY = "money"
    POWER = "power"
    LIMIT = "limit"


class Clause(Model):
    """One clause of a measure. The votes resolver scores each bloc against each."""

    kind: ClauseKind
    subject: Label
    amount: int | None = Field(default=None, ge=0)
    """Money clauses only: the sum, in the measure's unit."""

    @model_validator(mode="after")
    def _money_has_amount(self) -> "Clause":
        if (self.kind is ClauseKind.MONEY) != (self.amount is not None):
            raise ValueError("a money clause, and only a money clause, names an amount")
        return self


class ProposeMeasure(Model):
    """A bill, treaty or declaration, as a set of clauses."""

    kind: Literal["measure"] = "measure"
    title: Label
    clauses: tuple[Clause, ...] = Field(min_length=1, max_length=12)


class MakeStatement(Model):
    kind: Literal["statement"] = "statement"
    theme: Label
    audience: EntityId | None = None
    """None: the public."""


class Investigate(Model):
    kind: Literal["investigate"] = "investigate"
    target: EntityId
    question: Label


class Deal(Model):
    """Offer a deal, or accept one."""

    kind: Literal["deal"] = "deal"
    counterparty: EntityId
    offer: tuple[Label, ...] = Field(default=(), max_length=4)
    ask: tuple[Label, ...] = Field(default=(), max_length=4)
    accept: bool = False

    @model_validator(mode="after")
    def _has_terms(self) -> "Deal":
        if not self.accept and not (self.offer or self.ask):
            raise ValueError("an offer names what is offered or asked")
        return self


class ShiftDisposition(Model):
    """How ``of`` regards ``toward``. Feeds resolvers; never sets a quantity."""

    kind: Literal["disposition"] = "disposition"
    of: EntityId
    toward: EntityId
    change: int = Field(ge=-DISPOSITION_CAP, le=DISPOSITION_CAP)

    @model_validator(mode="after")
    def _moves(self) -> "ShiftDisposition":
        if self.change == 0 or self.of == self.toward:
            raise ValueError("a disposition change moves one party toward another")
        return self


class Disclosure(Model):
    """Reveal a fact to the public, or conceal it."""

    kind: Literal["disclosure"] = "disclosure"
    fact: FactId
    reveal: bool = True


Effect = Annotated[
    MoveForce
    | SetEngagement
    | Allocate
    | Appointment
    | ProposeMeasure
    | MakeStatement
    | Investigate
    | Deal
    | ShiftDisposition
    | Disclosure,
    Field(discriminator="kind"),
]

IRREVERSIBLE: frozenset[EffectKind] = frozenset({EffectKind.APPOINTMENT, EffectKind.ALLOCATE})
"""Kinds an aide never orders for an absent seat without a standing order naming
them (spec §4): a dismissal and a transfer. Declarations are measures, checked by title."""


REFUSAL_LOYALTY = -4
"""At or below this loyalty an executor may refuse a lawful command (spec §8.2)."""


class PartRef(Model):
    """One part of one routed order: what a pipeline order carries (wave B)."""

    order_id: OrderId
    part: int = Field(ge=0, le=7)


class PartView(Model):
    """One part of a routed order, as its issuer knows it."""

    route: Route
    effect: Effect | None = None
    """What the seat asked for. None: no code rule covers it; the estimator reads it."""
    domain: Label | None = None
    """Command: the authority it falls under."""
    executor: EntityId | None = None
    """Command: who carries it out. None: the seat acts itself."""
    pipeline: PipelineId | None = None
    """Process: the pipeline it runs."""
    target: EntityId | None = None
    """Influence: the person who decides."""
    reason: str = Field(default="", max_length=600)
    """The estimator's reason, written from the issuer's view. Leak-scanned."""
    fidelity: Fidelity | None = None
    refusal: Label = ""
    """The stated rule an executor refused under. Empty unless refused."""
    executed: date | None = None
    """The day the executor carried it out or refused it."""
    decided: date | None = None
    """Influence: the day the target decided (``influence_decided``)."""
    accepted: bool | None = None
    """Influence: whether the target went along. Set with ``decided``."""
    applied: date | None = None
    """The day the part's effects landed in the world (``effects_applied``)."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"decided", "accepted", "applied"})

    @model_validator(mode="after")
    def _route_fields(self) -> "PartView":
        allowed = {
            Route.COMMAND: {"domain", "executor"},
            Route.PROCESS: {"pipeline"},
            Route.INFLUENCE: {"target"},
        }[self.route]
        required = {Route.COMMAND: "domain", Route.PROCESS: "pipeline", Route.INFLUENCE: "target"}
        if getattr(self, required[self.route]) is None:
            raise ValueError(f"a {self.route.value} part names its {required[self.route]}")
        stray = [f for f in ("domain", "executor", "pipeline", "target") if f not in allowed]
        if any(getattr(self, f) is not None for f in stray):
            raise ValueError(f"a {self.route.value} part names only {', '.join(sorted(allowed))}")
        done = self.fidelity is not None or bool(self.refusal)
        if done and self.route is not Route.COMMAND:
            raise ValueError("only a command is executed")
        if self.fidelity is not None and self.refusal:
            raise ValueError("a part is carried out or refused, not both")
        if done != (self.executed is not None):
            raise ValueError("an executed part, and only one, has its date")
        if (self.decided is None) != (self.accepted is None):
            raise ValueError("an influence part is decided and accepted together")
        if self.decided is not None and self.route is not Route.INFLUENCE:
            raise ValueError("only an influence part is decided")
        return self


class RoutedPart(PartView):
    """The whole part. ``estimated`` never leaves the engine."""

    estimated: tuple[Effect, ...] = Field(default=(), max_length=8)
    was_estimated: bool = False
    """The estimator has ruled on this part; it rules once. Its effects may be none."""

    def view(self) -> PartView:
        return PartView.model_validate(self.model_dump(include=set(PartView.model_fields)))


class FidelityInputs(Model):
    """What sets an executor's fidelity, read from state when a command is carried
    out (spec §8.2). The router (wave A1) fills it; the seeded roll lives there too."""

    loyalty: int = Field(ge=-5, le=5)
    competence: int = Field(ge=0, le=5)
    workload: int = Field(ge=0)
    """Command parts the executor already carries and has not carried out."""


class Routing(Model):
    """The router's answer for one part: the routed part, or why no route takes it.

    Shared by the router (wave A1) and the estimator (wave A4): a part routed with
    no ``effect`` is the estimator's to rule on. Engine-side, never stored; the
    routed parts land as ``OrderRouted``."""

    part: RoutedPart | None = None
    refusal: str = Field(default="", max_length=300)
    """Words the issuer can read: why nobody can carry this part out."""

    @model_validator(mode="after")
    def _one(self) -> "Routing":
        if (self.part is None) == (not self.refusal):
            raise ValueError("a part is routed or refused, not both or neither")
        return self


class RoutedOrderView(Model):
    """An engine-v2 order as its issuer knows it."""

    order_id: OrderId
    issuer: SeatId
    filed: date
    parts: tuple[PartView, ...] = Field(min_length=1, max_length=8)


class RoutedOrder(Model):
    """A committed order, split into routed parts (spec §8.2)."""

    order_id: OrderId
    issuer: SeatId
    filed: date
    parts: tuple[RoutedPart, ...] = Field(min_length=1, max_length=8)

    def view(self) -> RoutedOrderView:
        return RoutedOrderView(
            order_id=self.order_id,
            issuer=self.issuer,
            filed=self.filed,
            parts=tuple(p.view() for p in self.parts),
        )


__all__ = [
    "DISPOSITION_CAP",
    "IRREVERSIBLE",
    "REFUSAL_LOYALTY",
    "Allocate",
    "Appointment",
    "Clause",
    "ClauseKind",
    "Deal",
    "Disclosure",
    "Effect",
    "EffectKind",
    "Engagement",
    "Fidelity",
    "FidelityInputs",
    "Investigate",
    "MakeStatement",
    "MoveForce",
    "PartRef",
    "PartView",
    "Posture",
    "ProposeMeasure",
    "Route",
    "RoutedOrder",
    "RoutedOrderView",
    "RoutedPart",
    "Routing",
    "SetEngagement",
    "ShiftDisposition",
]
