"""Running orders through their pipelines (plan, Phase 2 unit B2).

A due clerical step passes as time. A due decision step is acted on by the
person holding it: a human seat decides for itself (the order waits, and the
desk shows decision needed); anyone else follows a deterministic policy read
from their card, with seeded friction. A leak issues a press document. An
amendment is a typed edit that fits the lever's parameter spec. An order through
its last step settles as enacted; a refusal settles it as refused.

Nobody waits on a person (DUE): a decision step a human seat holds on another
seat's order puts the order before that seat as one paper, and falls due
``process.ANSWER_DAYS`` after the step's own due day. The holder's choice is kept
until then (``step_chosen``) and taken that day in the card's place; with none, the
card takes it, holding rather than passing an order that cannot be undone. A step on a seat's
own order that its own person holds still waits for that seat.

With ``command`` on (CMD), a human seat holding a step on an order issued from up his own
chain of ``principals`` may only pass or stall it, and a step he leaves unanswered passes on
its held due day, the card unconsulted, even on an order that cannot be undone. Two form
orders moving one force meet when the second is about to act: the lower one, issued from
down the other's chain, is settled as lapsed, "replaced" and the reason on its issuer's own
paper, when the superior's order acted earlier in the same walk or is at its last step and
due by the walk's end (the date the wake runs to).
"""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, DocumentId, EntityId, OrderId, SeatId, derived_id
from revisionist.core.ontology import Controller, Entity, EntityKind
from revisionist.core.realism import actors, process, resolvers
from revisionist.core.realism.card import (
    ChannelKind,
    Lever,
    ParamKind,
    ParamSpec,
    ParamValue,
    SeatCard,
    superiors,
    words,
)
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.effect import IRREVERSIBLE
from revisionist.core.realism.pipeline import (
    ADVANCES,
    Order,
    OrderStatus,
    StepAction,
    StepKind,
    StepOutcome,
    step_due,
)
from revisionist.core.realism.resolvers.movement import moved_force
from revisionist.core.state import Rule, State, View
from revisionist.core.visibility import PUBLIC, Scope, Visibility
from revisionist.core.world_compile import object_id

RealismStep = ev.OrderStepTaken | ev.OrderSettled | ev.DocumentIssued


def waiting_on_human(state: State, order: Order) -> bool:
    """True when the order is moving and its current step is a decision step held by
    a person a human seat embodies. A clerical step never waits: it passes as time."""
    steps = state.pipelines[order.pipeline].steps
    if order.status is not OrderStatus.MOVING or order.step >= len(steps):
        return False
    step = steps[order.step]
    if step.kind is StepKind.CLERICAL:
        return False
    return any(
        s.embodies == step.person and s.controller is Controller.HUMAN for s in state.seats.values()
    )


def held_by_another(state: State, order: Order) -> SeatId | None:
    """The human seat holding the decision step the order waits at, when that seat
    is not the order's issuer; None otherwise, and for an order not waiting on one."""
    if not waiting_on_human(state, order):
        return None
    seat = process.holder(state, state.pipelines[order.pipeline].steps[order.step].person)
    return seat if seat is not None and seat != order.issuer else None


SUBORDINATE: frozenset[StepAction] = frozenset({StepAction.PASS, StepAction.STALL})
"""What a seat may do at a step on an order from up his own chain (CMD)."""


def under_issuer(state: State, order: Order) -> bool:
    """With ``command`` on: the order waits at a step another human seat holds, and the
    order's issuer is on the holder's chain of ``principals`` (CMD)."""
    if Rule.COMMAND not in state.rules or held_by_another(state, order) is None:
        return False
    holder = state.pipelines[order.pipeline].steps[order.step].person
    return state.seats[order.issuer].embodies in superiors(state.cards, holder)


def step_allowed(state: State, order: Order) -> frozenset[StepAction]:
    """What a human may do at the step the order waits at: the step's own set, cut to
    pass and stall on an order from up the holder's chain (CMD)."""
    allowed = state.pipelines[order.pipeline].steps[order.step].allowed
    return allowed & SUBORDINATE if under_issuer(state, order) else allowed


def _arrived(order: Order) -> date:
    """The day the order reached the step it is at."""
    return order.outcomes[-1].on if order.outcomes else order.filed


def held_due(state: State, order: Order) -> date | None:
    """The day the card takes a decision step another human seat holds on this order:
    the step's due day plus ``ANSWER_DAYS`` (from its arrival when the step has no
    length). None when the order is not waiting on another seat."""
    if held_by_another(state, order) is None:
        return None
    due = step_due(order, state.pipelines[order.pipeline]) or _arrived(order)
    return due + timedelta(days=process.ANSWER_DAYS)


def held_paper_id(campaign_id: CampaignId, order_id: OrderId, step: int) -> DocumentId:
    """The id of the paper that puts an order before the seat holding its step."""
    return DocumentId(derived_id(campaign_id, "held-paper", order_id, step))


STALLS_TO_LAPSE = 3  # [proposed] the third stall at one step lapses the order
LEAK_DELAY_DAYS = 1  # [proposed] a leak reaches the press a day after the step
LEAK_BELOW = 5  # [proposed] leak when a draw in [0, 100) falls under this
REFUSE_AT = -6  # [proposed] policy score thresholds
STALL_AT = -2
AMEND_AT = -1
EXPEDITE_AT = 5
FREE_ORDERS = 2  # [proposed] orders a person carries before workload bites


def _lever(state: State, order: Order) -> Lever:
    seat = state.seats[order.issuer]
    for lever in state.cards[seat.embodies].levers:
        if lever.name == order.lever:
            return lever
    if order.routed_from is not None:
        # A process part carried from a routed order (engine v2, spec §8.2) is not a
        # card lever: stand one in so replies, leaks and amends read it in words.
        return Lever(
            name=order.lever,
            pipeline=order.pipeline,
            resolver=resolvers.resolver_for(state, order),
            label=order.measure.title if order.measure is not None else "",
        )
    raise KeyError(f"order {order.order_id}: lever {order.lever} is not on the issuer's card")


def _specs(state: State, order: Order) -> dict[str, ParamSpec]:
    return {p.name: p for p in _lever(state, order).params}


def _check_amended(state: State, order: Order, amended: dict[str, ParamValue]) -> None:
    specs = _specs(state, order)
    for name, val in amended.items():
        spec = specs.get(name)
        if name not in order.params or spec is None:
            raise ValueError(f"order has no parameter {name}")
        if spec.kind is ParamKind.INT:
            if (
                not isinstance(val, int)
                or spec.lo is None
                or spec.hi is None
                or not spec.lo <= val <= spec.hi
            ):
                raise ValueError(f"{name}: {val!r} is outside the lever's range")
        elif spec.kind is ParamKind.ENUM:
            if val not in spec.choices:
                raise ValueError(f"{name}: {val!r} is not a choice")
        elif not isinstance(val, str):
            raise ValueError(f"{name}: {val!r} does not fit the lever")


def _words(text: str) -> set[str]:
    return set(text.lower().replace("_", " ").split())


def _kinds(state: State, order: Order) -> set[str]:
    """The kinds of the typed effects the order carries."""
    kinds = {"measure"} if order.measure is not None else set()
    ref = order.routed_from
    routed = state.routed.get(ref.order_id) if ref is not None else None
    if ref is not None and routed is not None and ref.part < len(routed.parts):
        effect = routed.parts[ref.part].effect
        kinds |= {effect.kind} if effect is not None else set()
    return kinds


def _interest(state: State, order: Order, card: SeatCard | None) -> int:
    """2 when the order touches what the holder cares about: the topics on the card
    when it names any, else its interests and doctrine read as words. [proposed]"""
    mine = _words(order.lever) | {
        w for v in order.params.values() if isinstance(v, str) for w in _words(v)
    }
    if card is not None and card.topics():
        kinds = _kinds(state, order)
        topics = [state.topics[k] for k in card.topics() if k in state.topics]
        return 2 if any(t.touched(order.lever, kinds, mine) for t in topics) else 0
    held = _words(" ".join((*card.interests, *card.doctrine))) if card else set()
    return 2 if mine & held else 0


def _policy(
    state: State,
    orders: dict[OrderId, Order],
    order: Order,
    seed: str,
    allowed: frozenset[StepAction],
) -> tuple[StepAction, dict[str, ParamValue]]:
    """What an AI-held decision step does with the order. [proposed] throughout."""
    steps = state.pipelines[order.pipeline].steps
    person = steps[order.step].person
    card = state.cards.get(person)
    loyalty = card.loyalty if card else 0
    interest = _interest(state, order, card)
    n = sum(
        1
        for o in orders.values()
        if o.order_id != order.order_id
        and o.status is OrderStatus.MOVING
        and o.step < len(state.pipelines[o.pipeline].steps)
        and state.pipelines[o.pipeline].steps[o.step].person == person
    )
    stalls = _stalls_here(order)
    f = resolvers.friction(state, seed, order.order_id, order.step, stalls, n=10) - 3
    score = loyalty + interest + f - max(0, n - FREE_ORDERS)

    amended: dict[str, ParamValue] = {}
    if score <= REFUSE_AT:
        action = StepAction.REFUSE
    elif score <= STALL_AT:
        action = StepAction.STALL
    elif resolvers.friction(state, seed, order.order_id, order.step, "leak", n=100) < LEAK_BELOW:
        action = StepAction.LEAK
    elif score == AMEND_AT and (amended := _trim(state, order)):
        action = StepAction.AMEND
    elif score >= EXPEDITE_AT:
        action = StepAction.EXPEDITE
    else:
        action = StepAction.PASS
    if action not in allowed:
        # A refusal the step does not allow holds the order instead, where a hold is allowed.
        held = StepAction.STALL if action is StepAction.REFUSE else StepAction.PASS
        return (held if held in allowed else StepAction.PASS), {}
    return action, amended


def irreversible(state: State, order: Order) -> bool:
    """True when the order, carried through, takes a step that cannot be undone: an
    ``IRREVERSIBLE`` kind, or a form or measure titled as a declaration."""
    lever = _lever(state, order)
    titles = (lever.name, lever.label, order.measure.title if order.measure else "")
    return bool(_kinds(state, order) & {k.value for k in IRREVERSIBLE}) or any(
        process.declares(t) for t in titles
    )


def _held_policy(
    state: State, orders: dict[OrderId, Order], order: Order, seed: str
) -> tuple[StepAction, dict[str, ParamValue]] | None:
    """The card's decision for a human-held step that fell due unanswered. It never
    moves on an order that cannot be undone: it holds it, else refuses it. None when
    the step allows neither, so the order waits for its holder."""
    allowed = state.pipelines[order.pipeline].steps[order.step].allowed
    action, amended = _policy(state, orders, order, seed, allowed)
    if action not in ADVANCES or not irreversible(state, order):
        return action, amended
    held = next((a for a in (StepAction.STALL, StepAction.REFUSE) if a in allowed), None)
    return None if held is None else (held, {})


def _held(
    state: State, orders: dict[OrderId, Order], order: Order, seed: str
) -> tuple[StepAction, dict[str, ParamValue]] | None:
    """The decision taken on a held step's due day: the holder's choice when one is kept
    for this step, else the card's. The card's guard on an order that cannot be undone
    binds only the card."""
    chosen = order.held_choice
    if chosen is not None and chosen.step == order.step:
        return chosen.action, dict(chosen.amended)
    if under_issuer(state, order):
        return StepAction.PASS, {}
    return _held_policy(state, orders, order, seed)


def _trim(state: State, order: Order) -> dict[str, ParamValue]:
    """The first int parameter cut by a quarter of its range, or empty if it cannot move."""
    for spec in _specs(state, order).values():
        cur = order.params.get(spec.name)
        if (
            spec.kind is ParamKind.INT
            and isinstance(cur, int)
            and spec.lo is not None
            and spec.hi is not None
        ):
            new = max(spec.lo, cur - max(1, (spec.hi - spec.lo) // 4))
            return {spec.name: new} if new != cur else {}
    return {}


def _stalls_here(order: Order) -> int:
    return sum(1 for o in order.outcomes if o.step == order.step and o.action is StepAction.STALL)


def _param_label(spec: ParamSpec | None, name: str) -> str:
    return (spec.label if spec is not None else "") or words(name)


DESTINATION = {"movement": "to"}
"""For each resolver that sends a force somewhere, the parameter that names where. It
takes any place with a position, not only the choices its form was written with."""


def destination(lever: Lever) -> ParamSpec | None:
    """The lever's parameter naming where a force is sent; None when it has none."""
    name = DESTINATION.get(lever.resolver)
    return next((p for p in lever.params if p.name == name and p.kind is ParamKind.ENUM), None)


def place_named(where: State | View, key: str) -> Entity | None:
    """The place a world key names, if the campaign has it and it has a position."""
    found = where.entities.get(EntityId(object_id(where.campaign_id, "entity", key)))
    if found is None or found.kind is not EntityKind.LOCATION or found.at is None:
        return None
    return found


def _param_value(
    spec: ParamSpec | None, value: ParamValue, where: State | View | None = None
) -> int | str:
    """A parameter's value in words: an enum choice by its label, a place by its name,
    never its key."""
    if isinstance(value, int):
        return value
    if spec is not None and spec.kind is ParamKind.ENUM and value in spec.choices:
        if spec.choice_labels:
            return spec.choice_labels[spec.choices.index(value)]
        return words(value)[:60]
    if spec is not None and spec.kind is ParamKind.ENUM and where is not None:
        place = place_named(where, value)
        if place is not None:
            return place.name[:60]
    return value[:60]


def _leak(state: State, order: Order, author: EntityId, on: date) -> ev.DocumentIssued:
    doc_id = DocumentId(derived_id(state.campaign_id, "leak", order.order_id, order.step))
    lever = _lever(state, order)
    specs = {p.name: p for p in lever.params}
    body = tuple(
        BodyField(label=_param_label(specs.get(k), k), value=_param_value(specs.get(k), v, state))
        for k, v in order.params.items()
    )
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.PRESS,
            author=author,
            issued=on,
            arrives=on + timedelta(days=LEAK_DELAY_DAYS),
            channel=ChannelKind.PRESS,
            title=f"Leaked: {lever.label or words(lever.name)}"[:60],
            body=body,
            scope=PUBLIC,
        ),
        truth=DocumentTruth(doc_id=doc_id),
    )


_DONE: dict[StepAction, str] = {
    StepAction.PASS: "passed it on",
    StepAction.EXPEDITE: "pressed it forward",
    StepAction.STALL: "held it",
    StepAction.AMEND: "amended it",
    StepAction.REFUSE: "refused it",
    StepAction.LEAK: "leaked it",
}

_REPLY_KIND: dict[ChannelKind, DocumentKind] = {
    ChannelKind.CABLE: DocumentKind.CABLE,
    ChannelKind.LETTER: DocumentKind.LETTER,
    ChannelKind.COURIER: DocumentKind.LETTER,
    ChannelKind.TELEPHONE: DocumentKind.MEMO,
    ChannelKind.IN_PERSON: DocumentKind.MEMO,
    ChannelKind.RADIO: DocumentKind.MEMO,
    ChannelKind.PRESS: DocumentKind.PRESS,
}
"""A call or a meeting reaches the page as a note of it."""


def _trim_title(text: str, limit: int = 60) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,:;") + "…"


def reply_doc_id(campaign_id: CampaignId, order_id: OrderId, n: int) -> DocumentId:
    """The id of the word that comes back on the ``n``th step outcome of an order."""
    return DocumentId(derived_id(campaign_id, "reply", order_id, n))


def order_words(state: State, order: Order) -> str:
    """What a standing-form order asked, in words: the form's label and its terms
    ("Propose a levy (Rate 8, Purpose For the harbour)")."""
    lever = _lever(state, order)
    specs = {p.name: p for p in lever.params}
    terms = ", ".join(
        f"{_param_label(specs.get(k), k)} {_param_value(specs.get(k), v, state)}"
        for k, v in order.params.items()
    )
    label = lever.label or words(lever.name)
    return f"{label} ({terms})" if terms else label


def _reply(
    state: State, order: Order, outcome: StepOutcome, status: OrderStatus | None
) -> ev.DocumentIssued | None:
    """The word that comes back to the issuer from the person at the step, or None
    when that person is the issuer's own or nobody plays the issuer."""
    seat = state.seats[order.issuer]
    if outcome.person == seat.embodies or order.issuer not in actors.readers(state):
        return None
    lever = _lever(state, order)
    specs = {p.name: p for p in lever.params}
    channel = next(
        (c.channel for c in state.cards[seat.embodies].inner_circle if c.person == outcome.person),
        ChannelKind.LETTER,
    )
    label = lever.label or words(lever.name)
    lead = lever.params[0] if lever.params else None
    given = order.params.get(lead.name) if lead is not None else None
    if lead is not None and lead.choice_labels and isinstance(given, str):
        title = f"On your order: {_param_value(lead, given, state)}"
    else:
        title = f"On your order: {label}"
    body = [
        BodyField(label="What was done", value=_DONE[outcome.action]),
        BodyField(label="Order", value=label[:60]),
        *(
            BodyField(
                label=f"Changed: {_param_label(specs.get(k), k)}"[:60],
                value=_param_value(specs.get(k), v, state),
            )
            for k, v in outcome.amended.items()
        ),
    ]
    if status is not None:
        body.append(BodyField(label="Outcome", value=status.value))
    doc_id = reply_doc_id(state.campaign_id, order.order_id, len(order.outcomes))
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=_REPLY_KIND[channel],
            author=outcome.person,
            issued=outcome.on,
            arrives=outcome.on,  # [proposed] no channel delay yet
            channel=channel,
            classification=Classification.CONFIDENTIAL,  # [proposed]
            title=_trim_title(title),
            body=tuple(body),
            scope=Scope(visibility=Visibility.PRIVATE, known_by=frozenset({order.issuer})),
        ),
        truth=DocumentTruth(doc_id=doc_id),
    )


def _held_paper(state: State, order: Order, seat: SeatId) -> ev.DocumentIssued:
    """The one paper that puts another seat's order before the seat holding its step."""
    due = held_due(state, order)
    assert due is not None
    issuer = state.seats[order.issuer].embodies
    label = _lever(state, order).label or words(order.lever)
    on = _arrived(order)
    said = [("Order", order_words(state, order))]
    if under_issuer(state, order):
        said.append(("You may", MAY_UNDER))
    return process.held_paper(
        state,
        held_paper_id(state.campaign_id, order.order_id, order.step),
        seat,
        issuer=issuer,
        title=f"For your decision: {label}",
        said=said,
        issued=on,
        arrives_on=on,
        due=due,
    )


MAY_UNDER = "Pass it on or hold it: it comes from above you."
REPLACED = "replaced"
"""The reason a lower order on a force is settled: a superior's order stands (CMD)."""


def _superior_order(state: State, orders: dict[OrderId, Order], order: Order) -> Order | None:
    """With ``command`` on, the order of a person up ``order``'s issuer's chain that moves
    the same force and acted in this walk (``orders`` holds the walk's own), or is at its
    last step and due by the walk's end: both first act on the force in one wake. None
    when there is none (CMD)."""
    if Rule.COMMAND not in state.rules:
        return None
    force = moved_force(state, order)
    if force is None:
        return None
    above = superiors(state.cards, state.seats[order.issuer].embodies)
    end = state.in_world_date
    current = {**state.orders, **orders}
    for other in sorted(current.values(), key=lambda o: (o.filed, o.order_id)):
        walked = other.order_id in orders
        if other.order_id == order.order_id or state.seats[other.issuer].embodies not in above:
            continue
        if moved_force(state, other) != force:
            continue
        steps = state.pipelines[other.pipeline].steps
        if other.status is OrderStatus.ENACTED:
            if walked:
                return other
        elif other.status is OrderStatus.MOVING and other.step == len(steps) - 1:
            due = _due(state, other)
            if due is not None and end is not None and due <= end:
                return other
    return None


def _replaced(state: State, order: Order, by: Order, on: date) -> tuple[Order, list[RealismStep]]:
    """``order`` settled as lapsed in favour of ``by``, with the reason on a paper sealed
    to its issuer when a player reads it (CMD)."""
    out: list[RealismStep] = [ev.OrderSettled(order_id=order.order_id, status=OrderStatus.LAPSED)]
    if order.issuer in actors.readers(state):
        superior = state.seats[by.issuer].embodies
        label = _lever(state, order).label or words(order.lever)
        doc_id = reply_doc_id(state.campaign_id, order.order_id, len(order.outcomes))
        reason = (
            f"{_trim_title(state.entities[superior].name, 40)}'s order for the same force stands."
        )
        out.append(
            ev.DocumentIssued(
                document=DocumentView(
                    doc_id=doc_id,
                    kind=DocumentKind.MEMO,
                    author=superior,
                    issued=on,
                    arrives=on,
                    channel=ChannelKind.LETTER,
                    classification=Classification.CONFIDENTIAL,
                    title=_trim_title(f"On your order: {label}"),
                    body=(
                        BodyField(label="What was done", value=REPLACED),
                        BodyField(label="Order", value=label[:60]),
                        BodyField(label="Why", value=reason[:60]),
                        BodyField(label="Outcome", value=OrderStatus.LAPSED.value),
                    ),
                    scope=Scope(visibility=Visibility.PRIVATE, known_by=frozenset({order.issuer})),
                ),
                truth=DocumentTruth(doc_id=doc_id),
            )
        )
    return order.model_copy(update={"status": OrderStatus.LAPSED}), out


def _acts(order: Order, action: StepAction, steps: int) -> bool:
    """True when ``action`` carries the order through its last step."""
    return action in ADVANCES and order.step + 1 >= steps


def _act(
    state: State,
    order: Order,
    action: StepAction,
    on: date,
    amended: dict[str, ParamValue],
) -> tuple[Order, list[RealismStep]]:
    """One step taken on ``order`` on ``on``: the events and the order as fold leaves it."""
    steps = state.pipelines[order.pipeline].steps
    step = steps[order.step]
    outcome = StepOutcome(
        step=order.step, person=step.person, action=action, on=on, amended=amended
    )
    out: list[RealismStep] = [ev.OrderStepTaken(order_id=order.order_id, outcome=outcome)]
    if action is StepAction.LEAK:
        out.append(_leak(state, order, step.person, on))
    status: OrderStatus | None = None
    stalls = _stalls_here(order) + (action is StepAction.STALL)
    nxt = order.step + (action in ADVANCES)
    if action is StepAction.REFUSE:
        status = OrderStatus.REFUSED
    elif action is StepAction.STALL and stalls >= STALLS_TO_LAPSE:
        status = OrderStatus.LAPSED
    elif nxt >= len(steps):
        status = OrderStatus.ENACTED
    if status is not None:
        out.append(ev.OrderSettled(order_id=order.order_id, status=status))
    if (reply := _reply(state, order, outcome, status)) is not None:
        out.append(reply)
    moved = order.model_copy(
        update={
            "params": {**order.params, **amended},
            "step": nxt,
            "outcomes": (*order.outcomes, outcome),
            "status": status or order.status,
        }
    )
    return moved, out


def run_pipelines(state: State, today: date, seed: str) -> list[RealismStep]:
    """Every AI and clerical step due on or before ``today``, in date order, each
    dated the day it fell due, plus the settlements and leaks they cause. A step a
    human holds on another seat's order is put before that seat as a paper, and taken
    on its held due day with the holder's kept choice, else by the card; one on the
    seat's own order waits. Pure: same
    state, day and seed, same list.

    ``expedite`` advances like ``pass``: it has no timing effect yet."""
    orders = {o.order_id: o for o in state.orders.values() if o.status is OrderStatus.MOVING}
    events: list[RealismStep] = []
    told = set(state.documents)

    def tell(order: Order) -> None:
        seat = held_by_another(state, order)
        if seat is None or order.status is not OrderStatus.MOVING:
            return
        doc_id = held_paper_id(state.campaign_id, order.order_id, order.step)
        if doc_id not in told and _arrived(order) <= today:
            told.add(doc_id)
            events.append(_held_paper(state, order, seat))

    for oid in sorted(orders):
        tell(orders[oid])
    while True:
        due = sorted(
            (d, oid)
            for oid, o in orders.items()
            if o.status is OrderStatus.MOVING and (d := _due(state, o)) is not None and d <= today
        )
        if not due:
            return events
        on, oid = due[0]
        order = orders[oid]
        step = state.pipelines[order.pipeline].steps[order.step]
        amended: dict[str, ParamValue] = {}
        if waiting_on_human(state, order):
            decided = _held(state, orders, order, seed)
            if decided is None:
                del orders[oid]
                continue
            action, amended = decided
        elif step.kind is StepKind.CLERICAL:
            action = StepAction.PASS
        else:
            action, amended = _policy(state, orders, order, seed, step.allowed)
        steps_n = len(state.pipelines[order.pipeline].steps)
        superior = _superior_order(state, orders, order) if _acts(order, action, steps_n) else None
        if superior is not None:
            orders[oid], out = _replaced(state, order, superior, on)
        else:
            orders[oid], out = _act(state, order, action, on, amended)
        events += out
        tell(orders[oid])


def _due(state: State, order: Order) -> date | None:
    """When the runner next acts on a moving order: its step's due day; for a step a
    human holds, the held due day on another seat's order, else never."""
    if waiting_on_human(state, order):
        return held_due(state, order)
    return step_due(order, state.pipelines[order.pipeline])


def human_step(
    state: State,
    order_id: OrderId,
    action: StepAction,
    today: date,
    amended: dict[str, ParamValue] | None = None,
) -> list[RealismStep]:
    """A human's decision at the step they hold, with what it causes. Raises
    ``ValueError`` when the order is not waiting on them or the action is not allowed."""
    order = checked_step(state, order_id, action, amended)
    acts = _acts(order, action, len(state.pipelines[order.pipeline].steps))
    superior = _superior_order(state, {}, order) if acts else None
    if superior is not None:
        return _replaced(state, order, superior, today)[1]
    return _act(state, order, action, today, amended or {})[1]


def checked_step(
    state: State,
    order_id: OrderId,
    action: StepAction,
    amended: dict[str, ParamValue] | None = None,
) -> Order:
    """The order a human may take ``action`` at, with ``amended`` fitting its terms.
    Raises ``ValueError`` when the order is not waiting on a human or the action is
    not allowed there."""
    order = state.orders.get(order_id)
    if order is None or not waiting_on_human(state, order):
        raise ValueError(f"order {order_id} is not waiting on a human")
    if action not in step_allowed(state, order):
        raise ValueError(f"step {order.step} does not allow {action.value}")
    if (action is StepAction.AMEND) != bool(amended):
        raise ValueError("an amendment, and only an amendment, carries edits")
    if amended:
        _check_amended(state, order, amended)
    return order


__all__ = [
    "DESTINATION",
    "MAY_UNDER",
    "REPLACED",
    "SUBORDINATE",
    "RealismStep",
    "checked_step",
    "destination",
    "held_by_another",
    "held_due",
    "held_paper_id",
    "human_step",
    "irreversible",
    "order_words",
    "place_named",
    "reply_doc_id",
    "run_pipelines",
    "step_allowed",
    "under_issuer",
    "waiting_on_human",
]
