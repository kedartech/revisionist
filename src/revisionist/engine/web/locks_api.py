"""The seat's locks and the check before sending (LKD).

With ``locks`` on, the seat's ``view.realism`` carries a ``locks`` block: its own held
orders, each with the order in plain words, who can allow it, whether it has been asked
for and the day it was held; and each ask put before it, with the asker and the order's
words. The ``check`` action answers, for a draft order, what filing it now would do:
``allowed``, ``locked`` with who can allow it, or ``beyond`` with today's refusal. It runs
the filing itself (``realism_tick.form_filing``, ``realism_tick.written_filing``) on the
game as it stands and logs nothing, so the check and the filing cannot differ. The lock
the filing reads is ``locks.seen_lock``: a lock whose condition turns on a fact the seat
cannot see holds nothing, so such an order checks as allowed. A draft offer to a bloc
(PRR) is checked by the filing's own rule (``offers.offer``): allowed, or its refusal.
Nothing here makes a model call.
"""

from collections.abc import Sequence

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, FeatureId, OrderId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import ladder, locks, offers, territory
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.card import words
from revisionist.core.realism.effect import Appointment, RoutedOrder
from revisionist.core.realism.resolvers.movement import FORCE
from revisionist.core.state import State, View
from revisionist.core.world_compile import object_id
from revisionist.engine import orders_reader, realism_tick
from revisionist.engine.web import map_api
from revisionist.engine.web.realism_api import (
    AskForm,
    AskLine,
    HeldLine,
    LockCheck,
    LocksBlock,
    OfferCheck,
)

ASK_DUE = "when you choose"  # [proposed]
"""The due words of an ask in the decider's list and wake notice: no clock ends it."""
ASKED = "Asked {who} for it."  # [proposed]
"""The reply to the ``ask`` action."""


def ask_id(campaign_id: CampaignId, order_id: OrderId) -> str:
    """The token an ask is known by to the seat it was put before: never the held
    order's own id, which only its issuer holds."""
    return derived_id(campaign_id, "ask", order_id)


def who(view: View, decider: locks.Decider) -> str:
    """Who can allow an order, named from the seat's own view, as ``locks.reason``
    names them."""
    if decider.person is not None:
        return _name(view, decider.person)
    assert decider.nation is not None
    chambers = " and ".join(c.replace("_", " ") for c in decider.chambers)
    return f"{_name(view, decider.nation)}'s {chambers}"


def _name(view: View, entity: EntityId) -> str:
    found = view.entities.get(entity)
    return found.name if found is not None else "whoever decides it"


def block(state: State, seat: SeatId) -> LocksBlock | None:
    """The seat's ``locks`` block, read from its own view; None with ``locks`` off."""
    if not locks.on(state):
        return None
    view = project(state, seat)
    held = [
        HeldLine(
            id=h.order_id,
            words=locks.held_words(state, h),
            who=who(view, h.decider),
            reason=h.reason,
            held=h.filed.isoformat(),
            asked=h.order_id in view.asked,
            piece=_piece(state, view, h),
        )
        for h in sorted(view.held.values(), key=lambda h: (h.filed, h.order_id))
    ]
    asks = [
        AskLine(
            id=ask_id(state.campaign_id, a.order_id),
            by=_name(view, a.by),
            words=a.words,
            asked=a.on.isoformat(),
            forms=_forms(state, view, a),
        )
        for a in sorted(view.asked.values(), key=lambda a: (a.on, a.order_id))
        if a.seat == seat
    ]
    return LocksBlock(held=held, asks=asks)


def _piece(state: State, view: View, held: locks.HeldOrder) -> str | None:
    """The map key of the force a held form order moves, as ``realism_snapshot`` keys
    the seat's own piece; None for a written order or a form naming no force."""
    force = held.form.params.get(FORCE) if held.form is not None else None
    if not isinstance(force, str):
        return None
    feature = state.features.get(FeatureId(object_id(state.campaign_id, "feature", force)))
    if feature is None:
        return None
    polity = territory.nation(state, view.me.embodies) or view.me.embodies
    raw = territory.mark_key(state, polity, feature)
    return map_api.mark_key(state.campaign_id, map_api.viewing_nation(view), raw)


def _forms(state: State, view: View, asked: locks.Asked) -> list[AskForm]:
    """The decider's own forms that would allow the asked order: the posture its lock's
    row names, where that form is on his own desk. The row is a public rule of the
    world; which row holds the order is engine side, and only the form it names is
    told."""
    held = state.held.get(asked.order_id)
    row = next((r for r in view.locks if held is not None and r.key == held.row), None)
    when = row.when if row is not None else None
    if not isinstance(when, locks.PostureNotSet) or when.form is None or view.desk is None:
        return []
    lever = next((x for x in view.desk.levers if x.name == when.form), None)
    if lever is None:
        return []
    terms = {**when.where, **when.posture}
    return [
        AskForm(
            lever=lever.name,
            label=lever.label or words(lever.name),
            params={k: str(v) for k, v in terms.items()},
        )
    ]


ALLOWED = LockCheck(check="allowed", who=None, reason="")


def _beyond(reason: str) -> LockCheck:
    return LockCheck(check="beyond", who=None, reason=reason)


def _locked(state: State, seat: SeatId, hold: locks.HeldOrder) -> LockCheck:
    return LockCheck(
        check="locked", who=who(project(state, seat), hold.decider), reason=hold.reason
    )


def _held_in(landing: realism_tick.Landing) -> locks.HeldOrder | None:
    return next((p.held for p, _ in landing if isinstance(p, ev.OrderHeld)), None)


def check_form(state: State, seat: SeatId, lever: str, given: dict[str, str]) -> LockCheck:
    """What filing the seat's form ``lever`` with ``given`` would do now. Logs nothing."""
    try:
        order = realism_tick.draft_order(state, seat, lever, given)
    except ValueError as exc:
        return _beyond(str(exc))
    landing, filed = realism_tick.form_filing(state, seat, order)
    hold = _held_in(landing) if landing else state.held.get(filed.order_id)
    return ALLOWED if hold is None else _locked(state, seat, hold)


def check_asks(state: State, seat: SeatId, asks: Sequence[Ask]) -> LockCheck:
    """What filing the seat's written ``asks`` would do now. Logs nothing."""
    if not asks:
        return _beyond(orders_reader.NOTHING)
    try:
        _, filed = realism_tick.written_filing(state, seat, asks)
    except ValueError as exc:
        return _beyond(str(exc))
    if isinstance(filed, locks.HeldOrder):
        return _locked(state, seat, filed)
    return _moves(state, filed) if ladder.on(state) else ALLOWED


QUESTION = "It would open the office question."  # [proposed]
"""The check's words for a move of post that would take a seat's last authority (PPR)."""


def _moves(state: State, filed: RoutedOrder) -> LockCheck:
    """With ``posts`` on, a filed move of post that would take a seat's last authority
    goes out and waits for the office question (PPR)."""
    for part in filed.parts:
        effect = part.effect
        if not isinstance(effect, Appointment):
            continue
        post = ladder.post_named(state, effect.office)
        if post is not None and ladder.takes_last(state, effect.person, post, effect.appoint):
            return LockCheck(check="question", who=None, reason=QUESTION)
    return ALLOWED


NO_POST = "There is no such post."  # [proposed]
NO_PERSON = "There is no such person."  # [proposed]
MOVES = ("appoint", "relieve", "restore")


def move_ask(state: State, seat: SeatId, person: str, post: str, move: str) -> Ask:
    """The written order a move of post is: appoint or restore ``person`` to ``post``, or
    relieve him of it. Raises ``ValueError`` in the seat's words for a post the ladder
    does not hold or a person the seat does not know."""
    found = ladder.post_named(state, post) if move in MOVES else None
    if found is None:
        raise ValueError(NO_POST)
    who = project(state, seat).entities.get(EntityId(person))
    if who is None or who.entity_id not in state.cards:
        raise ValueError(NO_PERSON)
    office = state.assets[found].name
    verb = {"appoint": "Appoint", "relieve": "Relieve", "restore": "Restore"}[move]
    words = (
        f"{verb} {who.name}: {office}" if move != "relieve" else f"Relieve {who.name} of {office}"
    )
    effect = Appointment(person=who.entity_id, office=office, appoint=move != "relieve")
    return Ask(ask=words, effect=effect)


def check_move(state: State, seat: SeatId, person: str, post: str, move: str) -> LockCheck:
    """What filing the move of post would do now, as the written order it is (PPR):
    allowed; locked, with who decides; beyond, with the refusal; or the office question.
    Logs nothing."""
    try:
        ask = move_ask(state, seat, person, post, move)
    except ValueError as exc:
        return _beyond(str(exc))
    return check_asks(state, seat, (ask,))


def check_offer(state: State, seat: SeatId, bloc: str, measure: str, key: str) -> LockCheck:
    """What filing the seat's draft offer of price ``key`` to ``bloc`` for ``measure``
    would do now (PRR rule 4): allowed, with each vote of the measure counted as it would
    stand with the offer landed (PRB rule 2), or refused in the words filing gives. No
    lock holds an offer. Logs nothing."""
    today = state.in_world_date
    if today is None:
        return _beyond(offers.NOT_ON)
    from revisionist.engine.web import home_api

    try:
        stands = home_api.would_stand(state, seat, bloc, measure, key)
    except offers.OffersError as exc:
        return _beyond(str(exc))
    return OfferCheck(**ALLOWED, stands=stands)


def ask_label(state: State, seat: SeatId, order_id: str) -> str:
    """The label of a held ask for the seat's held-orders list. Raises ``ValueError``
    with the seat's words as the ask would now."""
    today = state.in_world_date
    if today is None:
        raise ValueError(locks.NOT_HELD)
    asked = locks.ask(state, seat, OrderId(order_id), today)
    return f"Your ask for: {asked.words}"  # [proposed]


def asked_reply(state: State, seat: SeatId, asked: locks.Asked) -> str:
    return ASKED.format(who=_name(project(state, seat), asked.to))


__all__ = [
    "ALLOWED",
    "ASKED",
    "ASK_DUE",
    "ask_id",
    "ask_label",
    "asked_reply",
    "block",
    "check_asks",
    "check_form",
    "check_offer",
    "who",
]
