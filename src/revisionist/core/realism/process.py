"""Process and influence parts (engine v2, spec §8.2). Wave B unit B5.

A process part opens its pipeline as an ``order_drafted`` that carries the part
(``Order.routed_from``); an influence part is decided by its target's card policy
as ``influence_decided``.

Nobody waits on a person (DUE): a request at a leader another human seat holds
reaches that seat as one paper sealed to it, and has a due day. The holder answers
before it, or the card decides on it, and never with an irreversible step.
"""

from collections.abc import Iterable, Iterator
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.canary import scan_text
from revisionist.core.ids import (
    CampaignId,
    DocumentId,
    EntityId,
    OrderId,
    PipelineId,
    SeatId,
    derived_id,
)
from revisionist.core.ontology import Controller
from revisionist.core.realism import reach
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.effect import (
    IRREVERSIBLE,
    ClauseKind,
    Effect,
    EffectKind,
    PartRef,
    ProposeMeasure,
    Route,
    RoutedOrder,
    RoutedPart,
    ShiftDisposition,
)
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.resolvers import friction
from revisionist.core.state import State
from revisionist.core.visibility import private_to

INTEREST_POINTS = 2  # [proposed] an ask that touches what the target cares about
ACCEPT_AT = 1  # [proposed] the score at which the target goes along
MIN_WORD = 4  # [proposed] shorter words ("the", "of") say nothing about an interest
WARLIKE = frozenset({"engagement", "move_force"})
NO_REACH = "You have no way to reach them."
ANSWER_DAYS = 2
"""[proposed] World days a person a human holds has to answer, after the request or
the decision reaches them; then the card decides (DUE)."""
LINE = 60
WITHHELD = "The words of this request cannot be shown to you."


def _parts(state: State, route: Route) -> Iterator[tuple[RoutedOrder, int, RoutedPart]]:
    for routed in sorted(state.routed.values(), key=lambda o: (o.filed, o.order_id)):
        for i, part in enumerate(routed.parts):
            if part.route is route:
                yield routed, i, part


def open_processes(state: State, today: date) -> list[ev.Payload]:
    """A pipeline order for each process part not yet carried."""
    carried = {o.routed_from for o in state.orders.values() if o.routed_from is not None}
    out: list[ev.Payload] = []
    for routed, i, part in _parts(state, Route.PROCESS):
        ref = PartRef(order_id=routed.order_id, part=i)
        if ref in carried or part.pipeline is None:
            continue
        measure = part.effect if isinstance(part.effect, ProposeMeasure) else None
        lever = "measure" if measure else (part.effect.kind if part.effect else "process")
        order = Order(
            order_id=OrderId(derived_id(state.campaign_id, "process", routed.order_id, i)),
            issuer=routed.issuer,
            lever=lever,
            pipeline=PipelineId(part.pipeline),
            params={},
            filed=routed.filed,
            measure=measure,
            routed_from=ref,
        )
        out.append(ev.OrderDrafted(order=order))
    return out


def _words(text: str) -> set[str]:
    return {w for w in text.lower().replace("_", " ").split() if len(w) >= MIN_WORD}


def _effect_words(effect: Effect) -> set[str]:
    texts: list[str] = [effect.kind]
    match effect.kind:
        case "measure":
            texts += [effect.title, *(c.subject for c in effect.clauses)]
        case "statement":
            texts.append(effect.theme)
        case "allocate":
            texts.append(effect.what)
        case "engagement":
            texts += [effect.zone, effect.rule]
        case "investigate":
            texts.append(effect.question)
        case "deal":
            texts += [*effect.offer, *effect.ask]
        case "appointment":
            texts.append(effect.office)
    return {w for t in texts for w in _words(str(t))}


def _warlike(effect: Effect) -> bool:
    if isinstance(effect, ProposeMeasure):
        return any(c.kind is ClauseKind.POWER for c in effect.clauses)
    return effect.kind in WARLIKE


def _keeps_out(interest: str) -> bool:
    low = interest.lower()
    return "out of the war" in low or ("keep" in low and " out" in low)


def _person(state: State, routed: RoutedOrder) -> EntityId:
    return state.seats[routed.issuer].embodies


def _name(state: State, who: EntityId) -> str:
    return state.entities[who].name


def decides(state: State, routed: RoutedOrder, part: RoutedPart) -> tuple[bool, str]:
    """The target's card policy [proposed]: accepted when the score reaches
    ``ACCEPT_AT``. One rule, so a model-backed policy can replace it."""
    disposition, interest, leverage, d = _score(state, routed, part)
    accepted = disposition + interest + leverage + d >= ACCEPT_AT
    assert part.target is not None
    if accepted:
        return True, answer_reason(_name(state, part.target), True)
    return False, _declined(_name(state, part.target), interest)


def declined(state: State, routed: RoutedOrder, part: RoutedPart) -> str:
    """The issuer's line when ``part`` is declined, whoever declines it: the words hang
    on the request alone, so they say nothing of whether the card or a holder decided."""
    assert part.target is not None
    _, interest, _, _ = _score(state, routed, part)
    return _declined(_name(state, part.target), interest)


def _declined(name: str, interest: int) -> str:
    if interest < 0:
        return f"{name} would not be moved: it would take the country nearer the war."
    return answer_reason(name, False)


def answer_reason(name: str, accepted: bool) -> str:
    """The issuer's line for a decided request, in the card's plain words. A decline
    goes through ``declined``, which picks the line the request calls for."""
    return f"{name} agreed to what you asked." if accepted else f"{name} would not be moved."


REFUSED_HINT = (
    "Were we on better terms, or were something offered in return, I might see it differently."
)
"""The same words on every refusal, in the target's own voice: a hint tuned to the score
would tell the issuer something about the target's card, which the issuer cannot see."""


def _score(state: State, routed: RoutedOrder, part: RoutedPart) -> tuple[int, int, int, int]:
    """Disposition, interest, leverage and the seeded roll, as ``decides`` weighs them."""
    assert part.target is not None
    target, issuer = part.target, _person(state, routed)
    card = state.cards.get(target)
    effects = (*((part.effect,) if part.effect else ()), *part.estimated)
    # disposition: loyalty to a principal, else the relationship (0 if none)
    if card is not None and issuer in card.principals:
        disposition = card.loyalty
    else:
        disposition = next(
            (r.disposition for r in state.relationships.values() if {r.a, r.b} == {target, issuer}),
            0,
        )
    # interest: the typed effects against the card's topics when it names any, else
    # against its interests and doctrine; never ask words
    held = (*card.interests, *card.doctrine) if card else ()
    mine = {w for e in effects for w in _effect_words(e)}
    if any(_keeps_out(i) for i in held) and any(_warlike(e) for e in effects):
        interest = -INTEREST_POINTS
    elif card is not None and card.topics():
        kinds = {e.kind for e in effects}
        topics = [state.topics[k] for k in card.topics() if k in state.topics]
        touched = any(t.touched(None, kinds, mine) for t in topics)
        interest = INTEREST_POINTS if touched else 0
    elif mine & _words(" ".join(held)):
        interest = INTEREST_POINTS
    else:
        interest = 0
    # leverage: estimated disposition shifts that touch the target, one point each way
    leverage = sum(
        (e.change > 0) - (e.change < 0)
        for e in part.estimated
        if isinstance(e, ShiftDisposition) and target in (e.of, e.toward)
    )
    # d: the seeded roll, -2..+2
    index = next(i for i, p in enumerate(routed.parts) if p is part)
    d = friction(state, routed.order_id, index, "influence", n=5) - 2
    return disposition, interest, leverage, d


def holder(state: State, who: EntityId) -> SeatId | None:
    """The human seat that holds ``who``, or None when no human does."""
    return next(
        (
            s.seat_id
            for s in sorted(state.seats.values(), key=lambda s: s.seat_id)
            if s.embodies == who and s.controller is Controller.HUMAN
        ),
        None,
    )


def declares(title: str) -> bool:
    """A measure or a form titled as a declaration (spec §4: checked by title)."""
    return "declar" in title.lower()


def irreversible(effects: Iterable[Effect]) -> bool:
    """True when carrying ``effects`` would take a step that cannot be undone: an
    ``IRREVERSIBLE`` kind, or a measure titled as a declaration."""
    return any(
        EffectKind(e.kind) in IRREVERSIBLE or (isinstance(e, ProposeMeasure) and declares(e.title))
        for e in effects
    )


def _effects(part: RoutedPart) -> tuple[Effect, ...]:
    return (*((part.effect,) if part.effect else ()), *part.estimated)


def held_by_another(state: State, routed: RoutedOrder, part: RoutedPart) -> SeatId | None:
    """The human seat a request is put to, when that is not the issuer's own seat."""
    if part.route is not Route.INFLUENCE or part.target is None:
        return None
    seat = holder(state, part.target)
    return seat if seat is not None and seat != routed.issuer else None


def arrives(state: State, routed: RoutedOrder, part: RoutedPart) -> date | None:
    """The day a request reaches its target, or None when no channel reaches them."""
    assert part.target is not None
    channels = reach.channels_to(state, _person(state, routed), part.target)
    if not channels:
        return None
    return routed.filed + timedelta(days=reach.transit_days(channels[0]))


def request_due(state: State, routed: RoutedOrder, i: int) -> date | None:
    """The due day of a request at a leader another human seat holds: filed, plus the
    way there, plus ``ANSWER_DAYS``. None for any other part, or one that never arrives."""
    part = routed.parts[i]
    if held_by_another(state, routed, part) is None:
        return None
    on = arrives(state, routed, part)
    return None if on is None else on + timedelta(days=ANSWER_DAYS)


def request_paper_id(campaign_id: CampaignId, order_id: OrderId, part: int) -> DocumentId:
    """The id of the paper that puts a request before the seat that holds its target."""
    return DocumentId(derived_id(campaign_id, "request-paper", order_id, part))


def day_words(day: date) -> str:
    return f"{day.day} {day:%B} {day.year}"


def held_paper(
    state: State,
    doc_id: DocumentId,
    seat: SeatId,
    *,
    issuer: EntityId,
    title: str,
    said: list[tuple[str, str]],
    issued: date,
    arrives_on: date,
    due: date,
) -> ev.DocumentIssued:
    """The one paper that puts another seat's request or order before ``seat``, sealed
    to it, from its own staff: who asks, what (``said``: label and words), and by when."""
    from revisionist.core.realism.apply import _aide, _lines  # apply imports us

    person = state.seats[seat].embodies
    rows = [
        BodyField(label="From", value=state.entities[issuer].name[:LINE]),
        *(row for label, text in said for row in _lines(text, label)),
        BodyField(label="Answer by", value=day_words(due)),
    ]
    safe = [
        b.model_copy(update={"value": WITHHELD[:LINE]})
        if isinstance(b.value, str) and scan_text(state, seat, b.value)
        else b
        for b in rows
    ]
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.MEMO,
            author=_aide(state, person),
            issued=issued,
            arrives=max(issued, arrives_on),
            channel=ChannelKind.IN_PERSON,
            classification=Classification.CONFIDENTIAL,  # [proposed]
            title=title[:LINE],
            body=tuple(safe),
            scope=private_to(seat),
        ),
        truth=DocumentTruth(doc_id=doc_id),
    )


def _request_paper(state: State, routed: RoutedOrder, i: int, seat: SeatId) -> ev.DocumentIssued:
    part = routed.parts[i]
    on = arrives(state, routed, part)
    due = request_due(state, routed, i)
    assert on is not None and due is not None
    issuer = _person(state, routed)
    said = [("Request", part.ask)]
    if part.effect is not None:
        from revisionist.core.realism.apply import describe  # apply imports us

        said.append(("Terms", describe(state, part)))
    return held_paper(
        state,
        request_paper_id(state.campaign_id, routed.order_id, i),
        seat,
        issuer=issuer,
        title=f"A request from {_name(state, issuer)}",
        said=said,
        issued=routed.filed,
        arrives_on=on,
        due=due,
    )


def _card_answer(state: State, routed: RoutedOrder, part: RoutedPart) -> tuple[bool, str]:
    """The card's answer on the due day: ``decides``, except that it never agrees to an
    irreversible step for the person a human holds; it declines it instead."""
    accepted, reason = decides(state, routed, part)
    if accepted and irreversible(_effects(part)):
        return False, declined(state, routed, part)
    return accepted, reason


def answered(state: State, routed: RoutedOrder, i: int, accepted: bool) -> ev.RequestAnswered:
    """The holder's own answer to a request at their person (ANS). It is kept, sealed
    to the holder, until the request's due day, when ``influence_due`` decides with it
    in the card's place: the issuer learns nothing before then, and the decision is
    dated and worded as the card's would be. Raises ``ValueError`` when the part is not
    a request another seat put to a human, or it is already decided."""
    part = routed.parts[i]
    if held_by_another(state, routed, part) is None or part.decided is not None:
        raise ValueError("That request is no longer before you.")
    return ev.RequestAnswered(order_id=routed.order_id, part=i, accepted=accepted)


def _holders_answer(state: State, routed: RoutedOrder, part: RoutedPart) -> tuple[bool, str]:
    """The decision on the due day: the holder's own answer when they gave one, in the
    words the card would use; else the card's."""
    if part.held_answer is None:
        return _card_answer(state, routed, part)
    if not part.held_answer:
        return False, declined(state, routed, part)
    assert part.target is not None
    return True, answer_reason(_name(state, part.target), True)


def influence_due(state: State, today: date) -> list[ev.Payload]:
    """A decision for each influence part due by ``today``. A target another human
    seat holds gets the request as a paper when it arrives; on its due day the holder's
    own answer decides it, or the card when they gave none. A target the issuer's own
    seat holds is left alone."""
    out: list[ev.Payload] = []
    for routed, i, part in _parts(state, Route.INFLUENCE):
        if part.decided is not None or part.target is None:
            continue
        seat = holder(state, part.target)
        if seat is not None and seat == routed.issuer:
            continue
        channels = reach.channels_to(state, _person(state, routed), part.target)
        if not channels:
            if routed.filed <= today:
                out.append(
                    ev.InfluenceDecided(
                        order_id=routed.order_id,
                        part=i,
                        on=routed.filed,
                        accepted=False,
                        reason=NO_REACH,
                    )
                )
            continue
        on = routed.filed + timedelta(days=reach.transit_days(channels[0]))
        if on > today:
            continue
        if seat is not None:
            if request_paper_id(state.campaign_id, routed.order_id, i) not in state.documents:
                out.append(_request_paper(state, routed, i, seat))
            on += timedelta(days=ANSWER_DAYS)
            if on > today:
                continue
            accepted, reason = _holders_answer(state, routed, part)
        else:
            accepted, reason = decides(state, routed, part)
        out.append(
            ev.InfluenceDecided(
                order_id=routed.order_id, part=i, on=on, accepted=accepted, reason=reason
            )
        )
    return out


__all__ = [
    "ANSWER_DAYS",
    "NO_REACH",
    "REFUSED_HINT",
    "answer_reason",
    "answered",
    "arrives",
    "day_words",
    "decides",
    "declares",
    "declined",
    "held_by_another",
    "held_paper",
    "holder",
    "influence_due",
    "irreversible",
    "open_processes",
    "request_due",
    "request_paper_id",
]
