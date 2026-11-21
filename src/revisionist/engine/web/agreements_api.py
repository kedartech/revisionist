"""Offering, answering, publishing and reading agreements (AGA).

``offer_reading`` is the ``agreement-offer`` action: wording, clauses, the other parties
and an optional envoy, checked as the treaty reader checks a clause (``orders_reader``)
and held as a reading the seat signs with ``file``; the signed version is the one filed.
``publish_asks`` is the ``agreement-publish`` action's order (AGR's publishing ``Deal``).
``offer_terms`` gives an offer's terms as signing and its agenda item show them: each
clause as ``agreement.render_clause`` writes it, whether the rules check it, and whether
the aide read it from the seat's wording. ``block`` is the ``agreements`` block: every
agreement the seat's nation is party to and every public one, with each clause's state
and day, and the open offers its nation is named in. Everything in it is read from the
seat's ``View``, which holds no other nations' private agreement or offer; the seat's
own offer shows each answer only once the offer's due day has decided it.
"""

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any, Literal

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.ids import EntityId, FeatureId, OrderId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import advance, agreement, process
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.agreement import Agreement, AgreementOffer, ClauseStatus
from revisionist.core.realism.effect import AgreementClause, ClauseType, Deal
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State, View
from revisionist.core.world_compile import object_id
from revisionist.engine import orders_reader
from revisionist.engine.web.realism_api import (
    AgreementClauseLine,
    AgreementLine,
    AgreementsBlock,
    OfferAnswer,
    OfferLine,
    OfferReading,
    OfferTerms,
    OrderProposal,
    TermClause,
)

MAX_PARTIES = 8
"""The nations one agreement names, as a ``Deal`` holds them."""
MAX_CLAUSES = 8
READY = "Your offer is ready to sign. Read the terms, then sign to send it."  # [proposed]
NOTHING_OFFERED = "An offer needs wording, a clause the rules can check, or both."
CLAUSE_LEFT_OUT = (
    "Clause {n} cannot be offered: it must be one the rules can check, bind a named "
    "nation, and name only what you can see."
)
PUBLISH_ASK = "Publish the agreement."  # [proposed]
Answer = Literal["accepted", "declined"]
ClauseState = Literal["pending", "kept", "broken", "called", "void", "unchecked"]
_STATE: Mapping[ClauseStatus, ClauseState] = {
    ClauseStatus.STANDING: "pending",
    ClauseStatus.KEPT: "kept",
    ClauseStatus.BROKEN: "broken",
    ClauseStatus.CALLED: "called",
    ClauseStatus.VOID: "void",
    ClauseStatus.UNCHECKED: "unchecked",
}
"""A clause status as the seat reads it: a standing clause is pending."""


def _day(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def checked(clause: AgreementClause) -> bool:
    """Whether the rules judge ``clause``: wording that fits no type is never judged."""
    return clause.type is not ClauseType.UNCHECKED


def offer_terms(
    state: State, offer: AgreementOffer | Agreement, interpretation: bool = False
) -> OfferTerms:
    """The terms of ``offer`` as signing and its agenda item show them: the parties, each
    clause in ``agreement.render_clause``'s fixed words with whether the rules check it,
    the offer's own wording (never checked), and the whole as ``agreement.render_terms``.
    ``interpretation``: the clauses are the aide's reading of the seat's wording."""
    return OfferTerms(
        parties=[agreement.nation_name(state, p) for p in offer.parties],
        clauses=[
            TermClause(
                text=agreement.render_clause(state, c),
                checked=checked(c),
                interpretation=interpretation and checked(c),
            )
            for c in offer.clauses
        ],
        wording=offer.wording,
        text=agreement.render_terms(state, offer),
    )


def _signed(state: State, seat: SeatId, deal: Deal) -> AgreementOffer:
    """The offer as signing shows it, as ``orders_reader.file_order`` checks it again."""
    return orders_reader._offer_of(state, state.seats[seat].embodies, deal)


def reading_reply(
    state: State,
    seat: SeatId,
    reading: orders_reader.Reading,
    interpretation: bool,
    reply: str = READY,
) -> OfferReading:
    """The reply to a reading of an offer: the proposal and, when it can be signed, its
    terms. ``interpretation``: the aide read the clauses from the seat's wording."""
    deal = reading.asks[0].effect if reading.version and reading.asks else None
    terms = None
    if isinstance(deal, Deal):
        terms = offer_terms(state, _signed(state, seat, deal), interpretation)
    shown = reading.shown
    return OfferReading(
        reply=shown["reason"] or reply,
        refused=not reading.asks,
        proposal=shown,
        terms=terms,
    )


def _texts(body: Mapping[str, Any], key: str, most: int) -> list[str]:
    value = body.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{key} is a list of names.")
    if len(value) > most:
        raise ValueError(f"{key} holds at most {most}.")
    return [v.strip() for v in value]


def _clauses(body: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    value = body.get("clauses", [])
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise ValueError("clauses is a list of clauses.")
    if len(value) > MAX_CLAUSES:
        raise ValueError(f"An agreement holds at most {MAX_CLAUSES} clauses.")
    return tuple(value)


def _envoy(state: State, body: Mapping[str, Any]) -> FeatureId | None:
    """The envoy named, by its piece id or its world key; None when none is."""
    value = body.get("envoy")
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("envoy must be text.")
    if FeatureId(value) in state.features:
        return FeatureId(value)
    return FeatureId(object_id(state.campaign_id, "feature", value))


def _wording(body: Mapping[str, Any]) -> str:
    value = body.get("wording", "")
    if not isinstance(value, str):
        raise ValueError("wording must be text.")
    value = value.strip()
    if len(value) > orders_reader.WORDING_MAX:
        raise ValueError(orders_reader.LONG_WORDING)
    return value


def offer_reading(state: State, seat: SeatId, body: Mapping[str, Any]) -> orders_reader.Reading:
    """The ``agreement-offer`` action: the offer of ``body``'s wording, clauses, other
    parties (nation ids) and optional envoy, as a reading the seat signs with ``file``.
    Each clause is checked as the treaty reader checks one, against the clause list and
    the seat's own view; one that fails refuses the whole offer rather than being left
    out. Raises ``ValueError`` with the reason."""
    view = project(state, seat)
    me = view.me.embodies
    own = polity_of(state, me)
    wording = _wording(body)
    named = [EntityId(p) for p in _texts(body, "parties", MAX_PARTIES)]
    parties = tuple(dict.fromkeys(((own,) if own else ()) + tuple(named)))
    others = tuple(p for p in parties if p != own)
    if own is None or not others or any(p not in view.entities for p in parties):
        raise ValueError(orders_reader.NO_PARTIES)
    if len(parties) > MAX_PARTIES:
        raise ValueError(f"An agreement names at most {MAX_PARTIES} nations.")
    raw = _clauses(body)
    if not wording and not raw:
        raise ValueError(NOTHING_OFFERED)
    # the rule and the parties first, so a clause is never blamed for them; the wording
    # stands in only to make a Deal (the refusal reads neither wording nor clauses here)
    why = agreement.refusal(
        state, seat, Deal(counterparty=others[0], parties=parties, wording=wording or "-")
    )
    if why:
        raise ValueError(why)
    for n, item in enumerate(raw, start=1):
        if orders_reader._checked(state, view, seat, parties, (item,))[1]:
            raise ValueError(CLAUSE_LEFT_OUT.format(n=n))
    clauses, _ = orders_reader._checked(state, view, seat, parties, raw)
    deal = Deal(
        counterparty=others[0],
        parties=parties,
        wording=wording,
        clauses=clauses,
        envoy=_envoy(state, body),
    )
    why = agreement.refusal(state, seat, deal)
    if why:
        raise ValueError(why)
    offer = _signed(state, seat, deal)
    parts = [f"{label}: {words}" for label, words in agreement.term_rows(state, offer)]
    if wording:
        parts.append(f"Your wording, which the rules do not check: {wording}")
    if deal.envoy is not None:
        parts.append(f"Carried by {state.features[deal.envoy].name}.")
    shown = OrderProposal(person=None, channel=None, text=wording, parts=parts, reason=None)
    return orders_reader.Reading(
        shown=shown,
        asks=(Ask(ask=orders_reader.OFFER_ASK, effect=deal),),
        version=offer.version,
        terms=agreement.render_terms(state, offer),
    )


def publish_asks(state: State, seat: SeatId, body: Mapping[str, Any]) -> tuple[list[Ask], str]:
    """The ``agreement-publish`` action: the order that makes the agreement ``body``
    names (its id, from the ``agreements`` block) public, and its label. Raises
    ``ValueError`` when the seat may not publish it."""
    key = body.get("agreement")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("agreement is empty.")
    key = key.strip()
    own = polity_of(state, state.seats[seat].embodies)
    found = state.agreements.made.get(key)
    other = next((p for p in found.parties if p != own), None) if found is not None else None
    deal = Deal(counterparty=other or own or EntityId(key), publish=key)
    why = agreement.refusal(state, seat, deal)
    if why:
        raise ValueError(why)
    return [Ask(ask=PUBLISH_ASK, effect=deal)], PUBLISH_ASK.rstrip(".")


# --- the block ------------------------------------------------------------------------


def _judged(events: Iterable[Event], seen: Mapping[str, Agreement]) -> dict[tuple[str, int], date]:
    """The day each clause of an agreement in ``seen`` was last judged."""
    out: dict[tuple[str, int], date] = {}
    for e in events:
        p = e.payload
        if isinstance(p, ev.ClauseJudged) and p.agreement_id in seen:
            out[(p.agreement_id, p.clause)] = p.on
    return out


def _clause_line(
    state: State, x: Agreement, n: int, judged: Mapping[tuple[str, int], date]
) -> AgreementClauseLine:
    c = x.clauses[n]
    status = x.statuses[n] if n < len(x.statuses) else agreement.statuses(x.clauses)[n]
    on = judged.get((x.agreement_id, n))
    if on is None and status is ClauseStatus.STANDING:
        on = c.on
    return AgreementClauseLine(
        text=agreement.render_clause(state, c),
        checked=checked(c),
        state=_STATE[status],
        on=on.isoformat() if on is not None else None,
    )


def _answers(view: View, offer: AgreementOffer) -> list[OfferAnswer]:
    """Each other nation's answer to the seat's own offer, from its own record of the
    order: a part is decided only on the offer's due day, so until then every answer
    is None, whatever the other seat has said."""
    routed = view.routed.get(offer.offer_id)
    if routed is None:
        return []
    out: list[OfferAnswer] = []
    for p in routed.parts:
        effect = p.effect
        if not isinstance(effect, Deal) or not effect.parties or effect.publish is not None:
            continue
        answer: Answer | None = None
        if p.decided is not None:
            answer = "accepted" if p.accepted else "declined"
        out.append(
            OfferAnswer(nation=agreement.nation_name(view, effect.counterparty), answer=answer)
        )
    return out


def _before(state: State, seat: SeatId, today: date | None) -> dict[OrderId, str]:
    """The agenda item id of each offer before ``seat`` to answer, by its order: what the
    agenda lists as an "Offer" (``advance.awaiting``, the request paper's id)."""
    if today is None:
        return {}
    return {
        a.order_id: process.request_paper_id(state.campaign_id, a.order_id, a.part)
        for a in advance.awaiting(state, seat, today)
        if a.part is not None and agreement.is_offer(state.routed[a.order_id].parts[a.part])
    }


def _open(state: State, offer: AgreementOffer) -> bool:
    """Whether the offer is still before its parties: not yet closed on its due day."""
    routed = state.routed.get(offer.offer_id)
    return routed is not None and any(
        agreement.is_offer(p) and p.applied is None for p in routed.parts
    )


def block(
    state: State, seat: SeatId, view: View, events: Iterable[Event] = ()
) -> AgreementsBlock | None:
    """The ``agreements`` block with the rule on: every agreement in the seat's view (its
    nation's and the public ones), each clause with its state and day, and the open
    offers its nation is named in. None with the rule off."""
    if not agreement.on(state):
        return None
    own = polity_of(state, view.me.embodies)
    seen = view.agreements.made
    judged = _judged(events, seen)
    made = sorted(seen.values(), key=lambda x: (x.made, x.agreement_id))
    offers = sorted(view.agreements.offers.values(), key=lambda o: (o.filed, o.offer_id))
    before = _before(state, seat, view.in_world_date)
    return AgreementsBlock(
        agreements=[
            AgreementLine(
                id=x.agreement_id,
                parties=[agreement.nation_name(view, p) for p in x.parties],
                wording=x.wording,
                made=x.made.isoformat(),
                published=x.published.isoformat() if x.published is not None else None,
                party=own is not None and own in x.parties,
                clauses=[_clause_line(state, x, n, judged) for n in range(len(x.clauses))],
            )
            for x in made
        ],
        offers=[
            OfferLine(
                by=agreement.nation_name(view, o.by),
                terms=offer_terms(state, o),
                filed=o.filed.isoformat(),
                expires=o.expires.isoformat(),
                answers=_answers(view, o),
                item=before.get(o.offer_id),
            )
            for o in offers
            if _open(state, o)
        ],
    )


def offer_of(state: State, order_id: Any, effect: object) -> AgreementOffer | None:
    """The offer an order carries, as its parties know it: recorded once the day walk
    has seen it, else as it will be recorded."""
    found = state.agreements.offers.get(order_id)
    if found is not None:
        return found
    routed = state.routed.get(order_id)
    if routed is None or not isinstance(effect, Deal):
        return None
    return agreement.make_offer(state, routed, effect)


__all__ = [
    "CLAUSE_LEFT_OUT",
    "NOTHING_OFFERED",
    "PUBLISH_ASK",
    "READY",
    "block",
    "checked",
    "offer_of",
    "offer_reading",
    "offer_terms",
    "publish_asks",
    "reading_reply",
]
