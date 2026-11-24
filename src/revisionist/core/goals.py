"""Secret goals and win conditions (spec §15, decisions 23, 36-38).

A goal compiles at Session Zero into a ``WinCondition``: a closed set of
checks over State, combined with all-of and any-of. No model ever decides
whether a goal is met; ``goal_met`` does, from State alone.

Each goal has a kind from a fixed table keyed on its condition. A Lasting
goal, once met, stays met whatever the world does later. An Undoable goal
counts only while it holds, and must hold at season end to win.

Aims become goals (AIM). With the ``aims`` rule on, a card's aim may carry an
``AimRule``: a condition over what the territory rules move (a territory's holder, a
nation's income, a group's support, an agreement in force, a contest won, a war, a
quantity, regard), its success rule in plain words, the period it is judged over, and
for each leaf whether the fact it reads is public, the seat's own nation's, or hidden
from the seat. The tick makes one goal per such aim for each person a human seat
holds, keyed to the person (``Goal.person``), so a person handed to another seat keeps
his goals and only the seat holding him sees them. Goals are checked every tick from
state alone; an aim is met while its condition holds, failed once it cannot change,
and otherwise at risk (``aim_status``).
"""

from __future__ import annotations

import math
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal

from pydantic import Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from revisionist.core._base import Model
from revisionist.core.ids import (
    AssetId,
    ClockId,
    CommitmentId,
    ContestId,
    EntityId,
    GoalId,
    MeterId,
    QuantityId,
    RelationshipId,
    SeatId,
)
from revisionist.core.ontology import (
    AssetKind,
    AssetStatus,
    CommitmentStatus,
    Controller,
    EntityStatus,
    ScheduleSource,
    regard_held,
)
from revisionist.core.realism.card import ParamValue
from revisionist.core.realism.effect import EffectKind
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.visibility import Scope

if TYPE_CHECKING:
    from revisionist.core.events import GoalMet, GoalProgressed, GoalSet, GoalUndone
    from revisionist.core.state import State, View

MAX_PARTS = 8
MAX_DEPTH = 3

Op = Literal["ge", "le"]


def _compare(value: int, op: Op, target: int) -> bool:
    return value >= target if op == "ge" else value <= target


# --- conditions ---------------------------------------------------------------


class HoldsOffice(Model):
    check: Literal["holds_office"] = "holds_office"
    holder: EntityId
    office: AssetId


class ControlsAsset(Model):
    check: Literal["controls_asset"] = "controls_asset"
    holder: EntityId
    asset: AssetId


class EntityIs(Model):
    check: Literal["entity_is"] = "entity_is"
    entity: EntityId
    status: EntityStatus


class MeterAt(Model):
    check: Literal["meter_at"] = "meter_at"
    meter: MeterId
    op: Op
    value: int


class CommitmentInForce(Model):
    check: Literal["commitment_in_force"] = "commitment_in_force"
    commitment: CommitmentId


class DispositionAt(Model):
    check: Literal["disposition_at"] = "disposition_at"
    relationship: RelationshipId
    op: Op
    value: int = Field(ge=-5, le=5)


class ActOf(Model):
    """``person`` did their historical act. Met when no human plays them (history
    follows the record); else only when an order that human filed has got there."""

    check: Literal["act_of"] = "act_of"
    person: EntityId
    lever: str | None = None
    """None: the human decides, and no lever exists for it yet, so never met."""
    params: dict[str, ParamValue] = Field(default_factory=dict)
    """A subset the order's parameters must match."""
    past_step: int | None = None
    """None: the order is enacted. An int: the order has moved past that step index."""


class Ordered(Model):
    """A seat embodying ``person`` issued a routed order with a part of this effect
    kind (given, or estimated) whose effects have landed. Never met while no human
    holds ``person``: a mandate is the seat's own work (engine v2, spec §8.5)."""

    check: Literal["ordered"] = "ordered"
    person: EntityId
    effect: EffectKind


class QuantityAt(Model):
    check: Literal["quantity_at"] = "quantity_at"
    quantity: QuantityId
    op: Op
    value: int


class HoldsArea(Model):
    """A territory's holder now is ``holder`` (THL). Public."""

    check: Literal["holds_area"] = "holds_area"
    area: EntityId
    holder: EntityId


class IncomeAt(Model):
    """A nation's war-economy figure (YLD), 0 to 100, against a line. Public."""

    check: Literal["income_at"] = "income_at"
    nation: EntityId
    op: Op
    value: int = Field(ge=0, le=1000)


class SupportAt(Model):
    """A group's support at home (GRP), 0 to 100, against a line."""

    check: Literal["support_at"] = "support_at"
    nation: EntityId
    group: str = Field(min_length=1, max_length=60)
    op: Op
    value: int = Field(ge=0, le=100)


class AgreementInForce(Model):
    """An agreement is in force among nations that include every one ``between``
    names, none of its clauses broken (AGR)."""

    check: Literal["agreement_in_force"] = "agreement_in_force"
    between: tuple[EntityId, ...] = Field(min_length=2, max_length=8)


class ContestWon(Model):
    """A contest has been decided for ``side`` (CON)."""

    check: Literal["contest_won"] = "contest_won"
    contest: ContestId
    side: EntityId


class AtWar(Model):
    """Nations ``a`` and ``b`` are at war (``war`` true) or not (false). Public."""

    check: Literal["at_war"] = "at_war"
    a: EntityId
    b: EntityId
    war: bool = True


class RegardAt(Model):
    """How ``a`` and ``b`` regard each other (a relationship's disposition, -5 to 5)
    against a line; 0 when they have no relationship yet."""

    check: Literal["regard_at"] = "regard_at"
    a: EntityId
    b: EntityId
    op: Op
    value: int = Field(ge=-5, le=5)


class AllOf(Model):
    check: Literal["all_of"] = "all_of"
    conditions: tuple[WinCondition, ...] = Field(min_length=1, max_length=MAX_PARTS)


class AnyOf(Model):
    check: Literal["any_of"] = "any_of"
    conditions: tuple[WinCondition, ...] = Field(min_length=1, max_length=MAX_PARTS)


Leaf = (
    HoldsOffice
    | ControlsAsset
    | EntityIs
    | MeterAt
    | CommitmentInForce
    | DispositionAt
    | ActOf
    | Ordered
    | QuantityAt
    | HoldsArea
    | IncomeAt
    | SupportAt
    | AgreementInForce
    | ContestWon
    | AtWar
    | RegardAt
)

WinCondition = Annotated[
    HoldsOffice
    | ControlsAsset
    | EntityIs
    | MeterAt
    | CommitmentInForce
    | DispositionAt
    | ActOf
    | Ordered
    | QuantityAt
    | SkipJsonSchema[HoldsArea]
    | SkipJsonSchema[IncomeAt]
    | SkipJsonSchema[SupportAt]
    | SkipJsonSchema[AgreementInForce]
    | SkipJsonSchema[ContestWon]
    | SkipJsonSchema[AtWar]
    | SkipJsonSchema[RegardAt]
    | AllOf
    | AnyOf,
    Field(discriminator="check"),
]
"""Every check. The territory rules' checks (AIM) are kept out of the schema a model is
offered, like the territory rules' world keys; they validate everywhere."""

AimCondition = Annotated[
    HoldsOffice
    | ControlsAsset
    | EntityIs
    | MeterAt
    | CommitmentInForce
    | DispositionAt
    | ActOf
    | Ordered
    | QuantityAt
    | HoldsArea
    | IncomeAt
    | SupportAt
    | AgreementInForce
    | ContestWon
    | AtWar
    | RegardAt
    | AllOf
    | AnyOf,
    Field(discriminator="check"),
]
"""The same checks as ``WinCondition``, with the territory rules' checks in its schema:
the type of an aim's condition and a goal's, so the committed event schema shows them."""

AllOf.model_rebuild()
AnyOf.model_rebuild()


def depth(c: WinCondition) -> int:
    if isinstance(c, AllOf | AnyOf):
        return 1 + max(depth(x) for x in c.conditions)
    return 1


def leaves(c: WinCondition) -> tuple[Leaf, ...]:
    if isinstance(c, AllOf | AnyOf):
        return tuple(leaf for x in c.conditions for leaf in leaves(x))
    return (c,)


# --- goals --------------------------------------------------------------------


class GoalKind(StrEnum):
    LASTING = "lasting"
    """The world cannot reverse it. Once met, it stays met."""
    UNDOABLE = "undoable"
    """Counts only while it holds; must hold at season end."""


class GoalSource(StrEnum):
    """Where a goal made from an aim comes from (AIM)."""

    POST = "post"
    """The card's own aim: what the person was set on at the start."""
    PLAYER = "player"
    """The player's own aim, filled from a world's pattern (OWC)."""
    REPLACEMENT = "replacement"
    """One of the two aims a replacement person must both hold (RPL): his card's aims
    that are not replaceable."""


class Exposure(StrEnum):
    """Whether the seat may see the fact a leaf of its aim reads (AIM rule 5)."""

    PUBLIC = "public"
    OWN = "own"
    """Its own nation's: the seats of the person's nation see it."""
    HIDDEN = "hidden"
    """Hidden from the seat: shown as uncertain."""


class AimRule(Model):
    """What makes a card's aim a goal (AIM): its condition, in plain words, over the
    period it is judged in. ``sees`` holds one exposure per leaf, in ``leaves`` order,
    set by the compiler from the world. Engine only, on the card."""

    condition: AimCondition
    rule: str = Field(min_length=1, max_length=280)
    """The success rule in plain words."""
    opens: date | None = None
    """The first day the aim is judged; None: from the start."""
    deadline: date | None = None
    """The last day the aim is judged; after it, its status holds as it stood. None:
    judged to the season's end."""
    sees: tuple[Exposure, ...] = ()
    replaceable: bool = False
    """The aim a player's own aim would replace in a later run; at most one per card."""

    @model_validator(mode="after")
    def _shape(self) -> AimRule:
        if depth(self.condition) > MAX_DEPTH or len(leaves(self.condition)) > MAX_PARTS:
            raise ValueError(f"an aim's condition has at most {MAX_PARTS} checks, {MAX_DEPTH} deep")
        if len(self.sees) != len(leaves(self.condition)):
            raise ValueError("an aim says who sees each leaf of its condition, once each")
        if self.opens is not None and self.deadline is not None and self.opens > self.deadline:
            raise ValueError("an aim opens on or before its deadline")
        return self


class Goal(Model):
    """One player seat's secret goal. Private to its owner (decision 37).

    A goal made from a card's aim (AIM) is keyed to the person whose aim it is
    (``person``, ``source``, ``aim``): it is reached through the seat holding that
    person at the time, has no objective clock, and ``seat_id`` names the seat it was
    made for. A legacy goal has none of the three and keeps its seat and clock."""

    goal_id: GoalId
    seat_id: SeatId
    text: str = Field(max_length=280)
    """The goal as the player agreed it, in words. Never shown to another seat."""
    condition: AimCondition
    kind: GoalKind
    clock_id: ClockId | None
    """The objective clock that shows progress to the owner. None for an aim's goal."""
    met_tick: int | None = None
    """The first tick the goal held, if it ever has."""
    holding: bool = False
    """Met now, as far as winning goes: always true once a Lasting goal is met."""
    scope: Scope
    canary: str | None = None
    """Test-only unique marker, as on Fact."""
    person: EntityId | None = None
    """AIM: the person whose aim it is; None for a legacy goal."""
    source: GoalSource | None = None
    aim: int | None = Field(default=None, ge=1, le=3)
    """Which of the person's card's aims, counting from 1."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"person", "source", "aim"})

    @model_validator(mode="after")
    def _shape(self) -> Goal:
        if depth(self.condition) > MAX_DEPTH:
            raise ValueError(f"a win condition nests at most {MAX_DEPTH} deep")
        if len(leaves(self.condition)) > MAX_PARTS:
            raise ValueError(f"a win condition has at most {MAX_PARTS} checks")
        if self.kind is not goal_kind(self.condition):
            raise ValueError("a goal's kind comes from its condition")
        keyed = (self.person is not None, self.source is not None, self.aim is not None)
        if any(keyed) and not all(keyed):
            raise ValueError("an aim's goal names its person, its source and its aim")
        if self.person is None and self.clock_id is None:
            raise ValueError("a goal that is not an aim's has an objective clock")
        return self


_LASTING_STATUSES = frozenset({EntityStatus.DEAD, EntityStatus.DISSOLVED})


def _rebuild_users() -> None:
    """Resolve the ``WinCondition`` and ``AimRule`` forward references in the ontology
    and on the seat card."""
    from revisionist.core.ontology import ScheduledEvent
    from revisionist.core.realism.card import SeatCard

    ScheduledEvent.model_rebuild(_types_namespace={"WinCondition": WinCondition})
    SeatCard.model_rebuild(_types_namespace={"AimRule": AimRule})


_rebuild_users()


def goal_kind(c: WinCondition) -> GoalKind:
    """The fixed table (spec §15). Only death and dissolution cannot be undone."""
    if isinstance(c, AllOf | AnyOf):
        kinds = {goal_kind(x) for x in c.conditions}
        return GoalKind.LASTING if kinds == {GoalKind.LASTING} else GoalKind.UNDOABLE
    if isinstance(c, EntityIs) and c.status in _LASTING_STATUSES:
        return GoalKind.LASTING
    if isinstance(c, Ordered):
        return GoalKind.LASTING  # an order given stays given
    return GoalKind.UNDOABLE


# --- checks -------------------------------------------------------------------


def goal_met(world: State | View, c: WinCondition) -> bool:
    """Whether ``c`` holds in ``world``. An ID the world does not hold is unmet."""
    match c:
        case HoldsOffice():
            office = world.assets.get(c.office)
            return (
                office is not None
                and office.kind is AssetKind.OFFICE
                and office.controller == c.holder
                and office.status is not AssetStatus.LOST
            )
        case ControlsAsset():
            asset = world.assets.get(c.asset)
            return (
                asset is not None
                and asset.controller == c.holder
                and asset.status is not AssetStatus.LOST
            )
        case EntityIs():
            entity = world.entities.get(c.entity)
            return entity is not None and entity.status is c.status
        case MeterAt():
            meter = world.meters.get(c.meter)
            return meter is not None and _compare(meter.value, c.op, c.value)
        case CommitmentInForce():
            commitment = world.commitments.get(c.commitment)
            return commitment is not None and commitment.status is CommitmentStatus.ACCEPTED
        case DispositionAt():
            rel = world.relationships.get(c.relationship)
            return rel is not None and _compare(rel.disposition, c.op, c.value)
        case ActOf():
            return _acted(world, c)
        case Ordered():
            return _ordered(world, c)
        case QuantityAt():
            quantity = world.quantities.get(c.quantity)
            return (
                quantity is not None
                and quantity.value is not None
                and _compare(quantity.value, c.op, c.value)
            )
        case HoldsArea():
            from revisionist.core.realism import holders

            return holders.holder(world, c.area) == c.holder
        case IncomeAt():
            from revisionist.core.realism import economy

            return _compare_figure(economy.figure(world, c.nation), c.op, c.value)
        case SupportAt():
            from revisionist.core.realism import groups

            support = groups.support(world, c.nation, c.group)
            return support is not None and _compare(support, c.op, c.value)
        case AgreementInForce():
            return _in_force(world, c)
        case ContestWon():
            contest = world.contests.get(c.contest)
            return contest is not None and contest.decided and contest.winner == c.side
        case AtWar():
            from revisionist.core.realism.war import at_war

            return at_war(world, c.a, c.b) is c.war
        case RegardAt():
            return _compare(_regard(world, c.a, c.b), c.op, c.value)
        case AllOf():
            return all(goal_met(world, x) for x in c.conditions)
        case AnyOf():
            return any(goal_met(world, x) for x in c.conditions)


def _compare_figure(value: float, op: Op, target: int) -> bool:
    return value >= target if op == "ge" else value <= target


def _in_force(world: State | View, c: AgreementInForce) -> bool:
    from revisionist.core.realism.agreement import ClauseStatus

    wanted = set(c.between)
    return any(
        wanted <= set(a.parties) and ClauseStatus.BROKEN not in a.statuses
        for a in world.agreements.made.values()
    )


def _regard(world: State | View, a: EntityId, b: EntityId) -> int:
    """The disposition between ``a`` and ``b``, either way round; 0 with none."""
    found = regard_held(world.relationships, a, b, either=True)
    return 0 if found is None else found.disposition


def _acted(world: State | View, c: ActOf) -> bool:
    from revisionist.core.state import State  # state imports us

    if not isinstance(world, State):
        return False  # a View hides who is human (spec §17)
    humans = {
        s.seat_id
        for s in world.seats.values()
        if s.embodies == c.person and s.controller is Controller.HUMAN
    }
    if not humans:
        return True
    if c.lever is None:
        return False
    return any(
        o.issuer in humans
        and o.lever == c.lever
        and all(o.params.get(k) == v for k, v in c.params.items())
        and (o.status is OrderStatus.ENACTED or (c.past_step is not None and o.step > c.past_step))
        for o in world.orders.values()
    )


def _ordered(world: State | View, c: Ordered) -> bool:
    from revisionist.core.state import State  # state imports us

    if not isinstance(world, State):
        return False  # a View hides who is human (spec §17)
    humans = {
        s.seat_id
        for s in world.seats.values()
        if s.embodies == c.person and s.controller is Controller.HUMAN
    }
    return any(
        part.applied is not None
        and any(
            EffectKind(e.kind) is c.effect
            for e in (*([part.effect] if part.effect is not None else []), *part.estimated)
        )
        for o in world.routed.values()
        if o.issuer in humans
        for part in o.parts
    )


def parts(c: WinCondition) -> int:
    """How many parts the objective clock counts: the top-level checks of an all-of."""
    return len(c.conditions) if isinstance(c, AllOf) else 1


def progress(world: State | View, c: WinCondition) -> int:
    """Parts met now, out of ``parts(c)``. Shown to the owner as "2 of 3"."""
    if isinstance(c, AllOf):
        return sum(goal_met(world, x) for x in c.conditions)
    return int(goal_met(world, c))


def check(state: State) -> list[GoalProgressed | GoalMet | GoalUndone]:
    """What changed for every goal since the last check, in goal order.

    Runs at the end of APPLY, so a goal is met when its condition holds at the
    end of a tick. A Lasting goal stops being checked once met. A replaced person's
    goals are not checked: they stay as they stood when he was replaced (RPL).
    """
    from revisionist.core.events import GoalMet, GoalProgressed, GoalUndone  # events imports us

    out: list[GoalProgressed | GoalMet | GoalUndone] = []
    gone = set(state.replaced.values())
    for goal in sorted(state.goals.values(), key=lambda g: g.goal_id):
        if (goal.holding and goal.kind is GoalKind.LASTING) or goal.person in gone:
            continue
        if goal.person is not None and not judged(state, goal):
            continue
        clock = state.clocks.get(goal.clock_id) if goal.clock_id is not None else None
        now = progress(state, goal.condition)
        if clock is not None and clock.segments_filled != now:
            out.append(GoalProgressed(goal_id=goal.goal_id, parts_met=now))
        met = goal_met(state, goal.condition)
        if met and not goal.holding:
            out.append(GoalMet(goal_id=goal.goal_id))
        elif not met and goal.holding:
            out.append(GoalUndone(goal_id=goal.goal_id))
    return out


# --- aims become goals (AIM) ------------------------------------------------------


class AimStatus(StrEnum):
    MET = "met"
    """The condition holds now, or held when the aim's period closed."""
    AT_RISK = "at_risk"
    """It does not hold now, and still can."""
    FAILED = "failed"
    """It does not hold, and can no longer change."""


def aims_on(state: State | View) -> bool:
    """Whether aims become goals in this game: the ``aims`` rule on."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.AIMS in rules


def aim_rule(state: State, goal: Goal) -> AimRule | None:
    """The rule on the card of ``goal``'s person that it was made from, or for the
    player's own aim the rule stored for the person (OWC); None for a legacy goal or a
    card that has lost it."""
    if goal.person is None or goal.aim is None:
        return None
    if goal.source is GoalSource.PLAYER:
        own = state.own_aims.get(goal.person)
        return own.rule if own is not None and own.aim == goal.aim else None
    card = state.cards.get(goal.person)
    if card is None or goal.aim > len(card.aim_rules):
        return None
    return card.aim_rules[goal.aim - 1]


def post_sees(condition: WinCondition, sees: tuple[Exposure, ...]) -> tuple[Exposure, ...]:
    """``sees`` as a commander held to his post reads it (PVW): a leaf on his own nation's
    facts is hidden from him, unless it is a regard he is party to; public leaves stay
    public. ``sees`` is returned as given when it does not match ``condition``."""
    found = leaves(condition)
    if len(sees) != len(found):
        return sees
    return tuple(
        Exposure.HIDDEN if e is Exposure.OWN and not isinstance(leaf, RegardAt) else e
        for leaf, e in zip(found, sees, strict=True)
    )


def at_post(goal: Goal, rule: AimRule | None) -> Goal:
    """``goal`` as a commander held to his post holds it (PVW): where a leaf he no longer
    sees could decide it, whether it holds and the tick it was met are not his to know.
    A goal not made from an aim is returned as it is."""
    if goal.person is None:
        return goal
    if rule is None or len(rule.sees) != len(leaves(goal.condition)):
        hidden = True
    else:
        hidden = post_sees(goal.condition, rule.sees) != rule.sees
    if not hidden:
        return goal
    return goal.model_copy(update={"holding": False, "met_tick": None})


def judged(state: State, goal: Goal) -> bool:
    """Whether an aim's goal is checked today: inside its period, from its opening day
    to its deadline. A legacy goal is always checked."""
    rule = aim_rule(state, goal)
    today = state.in_world_date
    if rule is None or today is None:
        return goal.person is None
    if rule.opens is not None and today < rule.opens:
        return False
    return rule.deadline is None or today <= rule.deadline


def _settled(world: State | View, c: WinCondition) -> bool:
    """Whether ``c``, not holding, can no longer come to hold: a contest decided for
    another side, a person dead or a body dissolved when the check wants otherwise."""
    match c:
        case AllOf():
            return any(_settled(world, x) for x in c.conditions if not goal_met(world, x))
        case AnyOf():
            return all(_settled(world, x) for x in c.conditions)
        case ContestWon():
            contest = world.contests.get(c.contest)
            return contest is not None and contest.decided and contest.winner != c.side
        case EntityIs():
            entity = world.entities.get(c.entity)
            return entity is not None and entity.status in _FINAL and entity.status is not c.status
        case _:
            return False


def aim_status(state: State, goal: Goal) -> AimStatus:
    """An aim's status, from state and its period alone: met while its condition holds
    (after the deadline, as it stood on the last day judged), failed when it does not
    hold and can no longer change (the deadline passed, or the world settled it), and
    otherwise at risk. Never reads an order or who played a wake. Reads the goal as
    ``state`` holds it."""
    goal = state.goals.get(goal.goal_id, goal)
    rule = aim_rule(state, goal)
    today = state.in_world_date
    closed = (
        rule is not None
        and rule.deadline is not None
        and today is not None
        and today > rule.deadline
    )
    if closed:
        return AimStatus.MET if goal.holding else AimStatus.FAILED
    opened = rule is None or rule.opens is None or (today is not None and today >= rule.opens)
    if opened and goal_met(state, goal.condition):
        return AimStatus.MET
    if _settled(state, goal.condition):
        return AimStatus.FAILED
    return AimStatus.AT_RISK


def holder_seat(state: State, goal: Goal) -> SeatId | None:
    """The seat ``goal`` is reached through: for an aim's goal, the seat holding its
    person now, while a player holds it; None while the code runs the person. For a
    legacy goal, its own seat."""
    if goal.person is None:
        return goal.seat_id
    if goal.person in state.replaced.values():
        return None
    from revisionist.core.state import seat_of_person  # state imports us

    seat = seat_of_person(state, goal.person)
    if seat is None or seat.controller is not Controller.HUMAN:
        return None
    return seat.seat_id


def sees_goal(state: State, goal: Goal, seat: SeatId) -> bool:
    """Whether ``seat`` sees ``goal``: an aim's goal only from the seat holding its
    person, or once the season has made every goal public; a legacy goal by its scope."""
    from revisionist.core.visibility import Visibility

    if goal.person is None or goal.scope.visibility is Visibility.PUBLIC:
        return goal.scope.visible_to(seat)
    return holder_seat(state, goal) == seat


def aim_goal_id(campaign_id: str, person: EntityId, aim: int) -> GoalId:
    from revisionist.core.ids import derived_id

    return GoalId(derived_id(campaign_id, "aim-goal", person, aim))


REPLACEMENT_AIMS = 2
"""The aims a replacement person is given, every one required (RPL)."""


def replacement_aims(rules: tuple[AimRule | None, ...], aims: int) -> tuple[int, ...]:
    """The aims, numbered from 1, a replacement person is given: the first two of his
    card's ``aims`` with a rule that are not replaceable; none when he has fewer."""
    found = tuple(
        i
        for i, rule in enumerate(rules[:aims], start=1)
        if rule is not None and not rule.replaceable
    )
    return found[:REPLACEMENT_AIMS] if len(found) >= REPLACEMENT_AIMS else ()


def aim_goals(state: State) -> list[GoalSet]:
    """With ``aims`` on, a ``GoalSet`` for each aim with a rule on the card of each
    person a human seat holds whose aims have no goals yet, in seat order: once per
    person, so a claim and a hand-over make them and a later seat for the same person
    makes none. A code seat's person gets none. A replacement person gets two, from
    ``replacement_aims``, with the source ``replacement`` and never his own aim."""
    from revisionist.core.events import GoalSet  # events imports us
    from revisionist.core.visibility import private_to

    if not aims_on(state):
        return []
    has = {g.person for g in state.goals.values() if g.person is not None}
    out: list[GoalSet] = []
    for seat in sorted(state.seats.values(), key=lambda s: s.seat_id):
        person = seat.embodies
        if seat.controller is not Controller.HUMAN or person in has:
            continue
        card = state.cards.get(person)
        if card is None:
            continue
        has.add(person)
        stand_in = person in state.replaced
        own = None if stand_in else state.own_aims.get(person)
        given = replacement_aims(card.aim_rules, len(card.aims))
        for i, rule in enumerate(card.aim_rules, start=1):
            if rule is None or i > len(card.aims) or (stand_in and i not in given):
                continue
            mine = own is not None and own.aim == i
            condition = own.rule.condition if own is not None and mine else rule.condition
            out.append(
                GoalSet(
                    goal=Goal(
                        goal_id=aim_goal_id(state.campaign_id, person, i),
                        seat_id=seat.seat_id,
                        text=own.text if own is not None and mine else card.aims[i - 1],
                        condition=condition,
                        kind=goal_kind(condition),
                        clock_id=None,
                        scope=private_to(seat.seat_id),
                        person=person,
                        source=(
                            GoalSource.REPLACEMENT
                            if stand_in
                            else GoalSource.PLAYER
                            if mine
                            else GoalSource.POST
                        ),
                        aim=i,
                    )
                )
            )
    return out


def season_winners(state: State) -> frozenset[SeatId]:
    """Every seat that wins at season end (decision 36). With ``aims`` on, the human
    seats holding a person with two of his aims holding, or all of them when his card
    has fewer than two (a replacement person has two goals, so both); any number win, or
    none. A replaced person's goals count for no seat. Otherwise any seat whose goal holds."""
    if not aims_on(state):
        return frozenset(g.seat_id for g in state.goals.values() if g.holding)
    holding: dict[EntityId, int] = {}
    for g in state.goals.values():
        if g.person is not None:
            holding[g.person] = holding.get(g.person, 0) + int(g.holding)
    won: set[SeatId] = set()
    for person, met in holding.items():
        card = state.cards.get(person)
        aims = (
            len(card.aims)
            if card is not None
            else sum(1 for g in state.goals.values() if g.person == person)
        )
        seat = holder_seat(state, next(g for g in state.goals.values() if g.person == person))
        if seat is not None and met >= max(1, min(2, aims)):
            won.add(seat)
    return frozenset(won)


# --- Session Zero: vetting and balance ----------------------------------------------

_REFS: tuple[tuple[str, str], ...] = (
    ("holder", "entities"),
    ("office", "assets"),
    ("asset", "assets"),
    ("entity", "entities"),
    ("meter", "meters"),
    ("commitment", "commitments"),
    ("relationship", "relationships"),
    ("person", "entities"),
    ("quantity", "quantities"),
)
_FINAL = frozenset({EntityStatus.DEAD, EntityStatus.DISSOLVED})


def vet(view: View, state: State, c: WinCondition) -> list[str]:
    """Why ``c`` cannot be this seat's goal, or nothing (spec §5 step 4).

    A goal names only what the seat knows of, is not met already, and is not
    impossible from the start: no reviving the dead, no holding a lost office,
    no keeping a treaty already broken.
    """
    problems: list[str] = []
    if depth(c) > MAX_DEPTH or len(leaves(c)) > MAX_PARTS:
        problems.append(f"at most {MAX_PARTS} checks, {MAX_DEPTH} deep")
    for leaf in leaves(c):
        for name, table in _REFS:
            ref = getattr(leaf, name, None)
            if ref is not None and ref not in getattr(view, table):
                problems.append(f"{leaf.check}: {name} {ref} is not something you know of")
        match leaf:
            case HoldsOffice() if leaf.office in state.assets:
                if state.assets[leaf.office].kind is not AssetKind.OFFICE:
                    problems.append(f"holds_office: {leaf.office} is not an office")
                elif state.assets[leaf.office].status is AssetStatus.LOST:
                    problems.append(f"holds_office: {leaf.office} is lost")
            case ControlsAsset() if leaf.asset in state.assets:
                if state.assets[leaf.asset].status is AssetStatus.LOST:
                    problems.append(f"controls_asset: {leaf.asset} is lost")
            case EntityIs() if leaf.entity in state.entities:
                now = state.entities[leaf.entity].status
                if now in _FINAL and now is not leaf.status:
                    problems.append(f"entity_is: {leaf.entity} is already {now.value}")
            case CommitmentInForce() if leaf.commitment in state.commitments:
                status = state.commitments[leaf.commitment].status
                if status not in (CommitmentStatus.OFFERED, CommitmentStatus.ACCEPTED):
                    problems.append(f"commitment_in_force: it is already {status.value}")
            case _:
                pass
    if not problems and goal_met(state, c):
        problems.append("already met: a goal has to be worked for")
    return problems


POWERFUL, WEAK = 8, 3
"""Power at or above, or at or below, these is flagged against an easy or hard goal."""
EASY, HARD = 3, 8


class Balance(Model):
    """One character and goal scored on a fixed rubric (spec §5). Private: never logged."""

    power: int
    difficulty: int
    flag: Literal["too_easy", "too_hard"] | None = None
    suggestion: str = ""


def power(state: State, seat: SeatId) -> int:
    """Means and reach: the tiers the character controls, plus the warm ties it has."""
    me = state.seats[seat].embodies
    tiers = sum(
        a.tier
        for a in state.assets.values()
        if a.controller == me and a.status is not AssetStatus.LOST
    )
    ties = sum(1 for r in state.relationships.values() if me in (r.a, r.b) and r.disposition >= 2)
    return tiers + ties


def _rival_held(state: State | View, seat: SeatId, holder: EntityId) -> bool:
    return any(s.embodies == holder and s.seat_id != seat for s in state.seats.values())


TAKE = 4
"""The difficulty of a territory check not yet holding that turns on the board or another
nation: a holder to change, an agreement to make, a contest to win, a war to start or end.
``[proposed]``"""


def _gap(now: float | None, line: int) -> int:
    """2, plus one for every 10 points (or part) between ``now`` and the line. ``[proposed]``"""
    gap = 0 if now is None else math.ceil(abs(now - line))
    return 2 + -(-gap // 10)


def difficulty(state: State | View, seat: SeatId, c: WinCondition) -> int:
    """How far the goal is from holding now, from the world given (the truth for everyone
    at Session Zero, a seat's view for its own aim's ladder)."""
    match c:
        case AllOf():
            return sum(difficulty(state, seat, x) for x in c.conditions)
        case AnyOf():
            return min(difficulty(state, seat, x) for x in c.conditions)
        case _ if goal_met(state, c):
            return 0
        case HoldsOffice() | ControlsAsset():
            ref = c.office if isinstance(c, HoldsOffice) else c.asset
            asset = state.assets.get(ref)
            if asset is None:
                return 2
            return 2 + asset.tier + (2 if _rival_held(state, seat, asset.controller) else 0)
        case EntityIs():
            return 2 + (2 if _rival_held(state, seat, c.entity) else 0)
        case MeterAt():
            meter = state.meters.get(c.meter)
            gap = abs(meter.value - c.value) if meter is not None else 0
            return 2 + -(-gap // 10)
        case DispositionAt():
            rel = state.relationships.get(c.relationship)
            return 2 + (abs(rel.disposition - c.value) if rel is not None else 0)
        case CommitmentInForce() | ActOf() | Ordered() | QuantityAt():
            return 2
        case HoldsArea() | AgreementInForce() | ContestWon() | AtWar():
            return TAKE
        case IncomeAt():
            from revisionist.core.realism import economy

            return _gap(economy.figure(state, c.nation), c.value)
        case SupportAt():
            from revisionist.core.realism import groups

            return _gap(groups.support(state, c.nation, c.group), c.value)
        case RegardAt():
            return 2 + abs(_regard(state, c.a, c.b) - c.value)


def balance(state: State, seat: SeatId, c: WinCondition) -> Balance:
    p, diff = power(state, seat), difficulty(state, seat, c)
    if p >= POWERFUL and diff <= EASY:
        return Balance(
            power=p,
            difficulty=diff,
            flag="too_easy",
            suggestion="A strong character with an easy goal: add a second part, or aim higher.",
        )
    if p <= WEAK and diff >= HARD:
        return Balance(
            power=p,
            difficulty=diff,
            flag="too_hard",
            suggestion="A weak character with a hard goal: keep one part, or aim nearer.",
        )
    return Balance(power=p, difficulty=diff)


_UNTIED = (
    "This goal ties to none of the world's contests or coming events. "
    "You can keep it, but it may sit outside the main action."
)


def _touches(state: State, leaf: Leaf) -> tuple[set[EntityId], set[str]]:
    """The entities a check stands on (its holder, controller, parties, ends), and
    every object ID it names directly."""
    people: set[EntityId] = set()
    named: set[str] = set()
    match leaf:
        case HoldsOffice() | ControlsAsset():
            ref = leaf.office if isinstance(leaf, HoldsOffice) else leaf.asset
            people.add(leaf.holder)
            named.update((leaf.holder, ref))
            if (asset := state.assets.get(ref)) is not None:
                people.add(asset.controller)
        case EntityIs():
            people.add(leaf.entity)
            named.add(leaf.entity)
        case MeterAt():
            named.add(leaf.meter)
            if (meter := state.meters.get(leaf.meter)) is not None:
                people.add(meter.owner)
        case CommitmentInForce():
            named.add(leaf.commitment)
            if (commitment := state.commitments.get(leaf.commitment)) is not None:
                people |= commitment.parties
        case DispositionAt():
            named.add(leaf.relationship)
            if (rel := state.relationships.get(leaf.relationship)) is not None:
                people |= {rel.a, rel.b}
        case ActOf() | Ordered():
            people.add(leaf.person)
            named.add(leaf.person)
        case QuantityAt():
            named.add(leaf.quantity)
            if (quantity := state.quantities.get(leaf.quantity)) is not None and quantity.owner:
                people.add(quantity.owner)
    return people, named


def pressure_warning(state: State, seat: SeatId, c: WinCondition) -> str | None:
    """A plain warning when ``c`` bears on no contest and no item on history's
    clock, or None. Warn only: the player may confirm anyway (spec §5.6)."""
    from revisionist.core import contest  # contest imports state, which imports us

    history = [s for s in state.scheduled.values() if s.source is ScheduleSource.HISTORY]
    if not state.contests and not history:
        return None

    people: set[EntityId] = set()
    named: set[str] = set()
    for leaf in leaves(c):
        leaf_people, leaf_named = _touches(state, leaf)
        people |= leaf_people
        named |= leaf_named
    if any(contest.bearing(state, entity) for entity in people):
        return None

    coming: set[str] = set()
    for event in history:
        if event.fired or event.skipped or event.condition is None:
            continue
        for leaf in leaves(event.condition):
            coming |= _touches(state, leaf)[1]
    if named & coming:
        return None
    return _UNTIED
