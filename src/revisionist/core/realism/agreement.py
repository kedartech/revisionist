"""Agreements with clauses the rules can check (AGR).

An offer is an order carrying a ``Deal`` that names its parties, its wording and its
clauses: one influence part for each other named nation, aimed at the person who speaks
for it, answered through the answer path by the offer's due day. It becomes an agreement
only when a seat of every named nation has accepted that same version (the hash of the
parties, the wording and the clauses); a decline, or no answer by the due day, lapses it
with no obligation on anyone. The card never answers an offer, and neither does the aide.

Each typed clause is judged from the state on its date, or each day while it stands;
wording that fits no type is kept and never judged, and a vote clause is judged only
from the tally of its conference (CNF), void when that conference is cancelled or does
not invite the nation it binds. A broken clause costs the breaker's leader regard with each other
party's leader and, when the agreement is public, moves the breaker's groups at home.
Nothing enforces a clause. Every rule here acts only with ``agreements`` on.

An offer may name an envoy of the offering nation's as its carrier (ENV). It goes to one
other nation, and is delivered on the day the envoy stands in the area that holds that
nation's capital: only then is it recorded for its parties and its paper sent, and its
expiry counts from that day. One the envoy has not delivered within ``CARRY_DAYS`` of
filing lapses, told to the offering nation only.

Peace (PEA), with ``peace`` on as well. An armistice between two nations at war stops
their battles for its days; an end to a war takes the war out of the wars in force, and
the bound nation's pieces must be off the other's ground within ``WITHDRAW_DAYS``; a pact's
clause against a separate peace is broken the day a party's war with the named enemy ends
while another party's goes on. Accepting an offer that carries an armistice or an end to a
war is a question of the kind peace: each nation's acceptance is held, as an order a lock
holds, until the decider of its row of that kind allows it, unless he is the one who
accepted; a nation with no such row cannot accept one. The agreement is made only when
every held acceptance is allowed.
"""

import hashlib
import json
from collections.abc import Sequence
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from revisionist.core._base import Label, Model
from revisionist.core.ids import DocumentId, EntityId, FeatureId, OrderId, SeatId, derived_id
from revisionist.core.realism.effect import (
    PEACE_CLAUSES,
    AgreementClause,
    ClauseType,
    Deal,
    Route,
    RoutedPart,
)

if TYPE_CHECKING:
    from revisionist.core.events import Payload
    from revisionist.core.realism.effect import RoutedOrder
    from revisionist.core.realism.locks import HeldOrder
    from revisionist.core.state import State, View, _World
    from revisionist.core.visibility import Scope

OFFER_DAYS = 4  # [proposed] plan, AGR Defaults
"""World days an offer stands after it is filed, or after its envoy delivers it; its answers
are decided on the last."""
CARRY_DAYS = 30  # [proposed] ENV: an offer's envoy has this long to deliver it
"""World days from filing within which an envoy delivers the offer it carries, else it lapses."""
BREAK_REGARD = -2  # [proposed] plan, AGR Defaults
"""What a broken clause moves the regard between the breaker's leader and each other
party's leader."""
REGARD_FLOOR, REGARD_TOP = -5, 5
LINE = 60
PUBLISH_DOMAIN = "agreements"
"""The domain label of the command part that publishes an agreement: the seat acts itself."""

WITHDRAW_DAYS = 14  # [proposed] PEA Defaults
"""World days after a war ends by terms within which the bound nation's pieces leave the
other nation's ground."""

NOT_ON = "Agreements are not part of this game."
NO_PEACE = "Peace is not part of this game."  # [proposed]
NOT_ALLOWED = "Not every named nation allowed the peace."  # [proposed]
WAR_ENDED = "Another agreement ended the war it would end, the same day."  # [proposed]
TERMS = "Terms are in force."  # [proposed]
ACCEPT_PEACE = "Accept the terms of peace."  # [proposed]
ALONE = "An offer of an agreement goes in an order of its own."
NOT_A_PARTY = "Your own nation must be a party to the agreement."


class ClauseStatus(StrEnum):
    STANDING = "standing"
    """In force and not yet broken: a standing clause, or a dated one before its day."""
    KEPT = "kept"
    BROKEN = "broken"
    CALLED = "called"
    """A defence clause an attack has called on: war is due by the call's day."""
    UNCHECKED = "unchecked"
    """Wording the rules cannot check."""
    VOID = "void"
    """A vote clause whose conference was cancelled or does not invite the nation it
    binds: neither kept nor broken, and it costs nothing (CNF)."""


class AgreementOffer(Model):
    """An offer of an agreement, as its parties know it."""

    offer_id: OrderId
    """The order that carries it."""
    version: Label
    parties: tuple[EntityId, ...] = Field(min_length=2)
    by: EntityId
    """The offering nation."""
    wording: str = Field(default="", max_length=600)
    clauses: tuple[AgreementClause, ...] = ()
    filed: date
    expires: date


class Call(Model):
    """An attack that calls on a defence clause: war on ``against`` is due by ``due``."""

    clause: int = Field(ge=0)
    against: EntityId
    due: date


class Agreement(Model):
    """An agreement in force: every named nation accepted the same version."""

    agreement_id: Label
    version: Label
    parties: tuple[EntityId, ...] = Field(min_length=2)
    wording: str = Field(default="", max_length=600)
    clauses: tuple[AgreementClause, ...] = ()
    made: date
    offer_id: OrderId | None = None
    """The offer it was made from; None for one a world or a conference makes."""
    published: date | None = None
    """The day a party published it; None while only its parties know of it."""
    statuses: tuple[ClauseStatus, ...] = ()
    """Each clause's status, in the clauses' order (filled when made)."""
    calls: tuple[Call, ...] = ()

    late_fields: ClassVar[frozenset[str]] = frozenset()

    @property
    def public(self) -> bool:
        return self.published is not None


class Agreements(Model):
    """Offers and agreements (AGR). A view holds those its nation is a party to, and
    every published agreement."""

    offers: dict[OrderId, AgreementOffer] = Field(default_factory=dict)
    made: dict[Label, Agreement] = Field(default_factory=dict)


# --- reading --------------------------------------------------------------------------


def on(state: "_World") -> bool:
    """Whether agreements act in this game: the ``agreements`` rule on."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.AGREEMENTS in rules


def peace_on(state: "_World") -> bool:
    """Whether peace acts in this game: the ``peace`` rule on, with ``agreements``."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.PEACE in rules and on(state)


def carries_peace(offer: "AgreementOffer | Deal") -> bool:
    """Whether accepting the offer is a question of peace: it carries an armistice or an
    end to a war."""
    return any(c.type in PEACE_CLAUSES for c in offer.clauses)


def version(parties: Sequence[EntityId], wording: str, clauses: Sequence[AgreementClause]) -> str:
    """The version of an offer: the hash of its parties, its wording and its clauses."""
    body = {
        "parties": list(parties),
        "wording": wording,
        "clauses": [c.model_dump(mode="json") for c in clauses],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def agreement_id(campaign_id: str, offer_id: str) -> str:
    return derived_id(campaign_id, "agreement", offer_id)


def is_offer(part: RoutedPart) -> bool:
    """Whether a routed part is one nation's share of an offer of an agreement."""
    effect = part.effect
    return (
        part.route is Route.INFLUENCE
        and isinstance(effect, Deal)
        and bool(effect.parties)
        and effect.publish is None
    )


def is_publish(part: RoutedPart) -> bool:
    effect = part.effect
    return isinstance(effect, Deal) and effect.publish is not None


def _nation(state: "State", seat: SeatId) -> EntityId | None:
    from revisionist.core.realism.war import polity_of

    found = state.seats.get(seat)
    return None if found is None else polity_of(state, found.embodies)


def speaker(state: "State", nation: EntityId) -> EntityId | None:
    """The person who answers for ``nation``: the person of its first seat with a desk,
    a human's first. None when no seat holds a person of the nation."""
    from revisionist.core.ontology import Controller
    from revisionist.core.realism.holders import holding_seats

    seats = [state.seats[s] for s in holding_seats(state, nation)]
    if not seats:
        return None
    seats.sort(key=lambda s: (s.controller is not Controller.HUMAN, s.seat_id))
    return seats[0].embodies


def _name(state: "State | View", who: EntityId | None) -> str:
    found = state.entities.get(who) if who is not None else None
    return found.name if found is not None else "an unknown party"


def nation_name(state: "State | View", who: EntityId | None) -> str:
    """The name of a nation or person, as the terms write it."""
    return _name(state, who)


def _day(day: date) -> str:
    return f"{day.day} {day:%B} {day.year}"


def render_clause(state: "State", clause: AgreementClause) -> str:
    """One clause in fixed words, from its validated fields alone."""
    who = _name(state, clause.binds)
    when = f"by {_day(clause.on)}" if clause.on is not None else "at all times"
    until = f"until {_day(clause.on)}" if clause.on is not None else "at all times"
    match clause.type:
        case ClauseType.PLACE:
            piece = state.features.get(clause.force) if clause.force is not None else None
            where = _name(state, clause.area) if clause.area is not None else clause.region
            verb = "is in" if clause.present else "is not in"
            name = piece.name if piece is not None else "an unknown piece"
            return f"{who}: {name} {verb} {where}, {when}."
        case ClauseType.KEEP_OUT:
            return f"{who}: no piece enters {_name(state, clause.area)}, {until}."
        case ClauseType.NO_WAR:
            return f"{who}: no war declared on {_name(state, clause.nation)}, {until}."
        case ClauseType.NO_ATTACK:
            return f"{who}: no attack on {_name(state, clause.nation)}, {until}."
        case ClauseType.DEFEND:
            return (
                f"{who}: war declared within {clause.days} days on any nation that newly "
                f"attacks {_name(state, clause.nation)}, {until}."
            )
        case ClauseType.FORM:
            return f"{who}: the form {clause.form} enacted, {when}."
        case ClauseType.AID:
            to = _name(state, clause.nation)
            return f"{who}: an aid share of at least {clause.share}% to {to}, {when}."
        case ClauseType.VOTE:
            way = "for" if clause.present else "against"
            return f"{who}: a vote {way} the conference text {clause.text}."
        case ClauseType.UNCHECKED:
            return f"{who}: {clause.text} (not checked by the rules)."
        case ClauseType.ARMISTICE:
            return f"{who}: an armistice with {_name(state, clause.nation)} for {clause.days} days."
        case ClauseType.END_WAR:
            other = _name(state, clause.nation)
            return (
                f"{who}: the war with {other} ends; its pieces leave {other}'s ground "
                f"within {WITHDRAW_DAYS} days."
            )
        case ClauseType.NO_SEPARATE_PEACE:
            return f"{who}: no separate peace with {_name(state, clause.nation)}."


def term_rows(state: "State", agreement: Agreement | AgreementOffer) -> list[tuple[str, str]]:
    """The terms as labelled rows: the parties, then each clause in fixed words."""
    rows = [("Parties", ", ".join(_name(state, p) for p in agreement.parties) + ".")]
    rows += [(f"Clause {n + 1}", render_clause(state, c)) for n, c in enumerate(agreement.clauses)]
    if not agreement.clauses:
        rows.append(("Clauses", "None the rules can check."))
    return rows


def render_terms(state: "State", agreement: Agreement | AgreementOffer) -> str:
    """Every material term in fixed words, from the validated clause objects: the parties,
    each obligation with its amount, scope and date. The only text a signing view shows
    as the terms."""
    return " ".join(f"{label}: {text}" for label, text in term_rows(state, agreement))


def seen_by(state: "State", seat: SeatId, *, post: bool = False) -> Agreements:
    """What ``seat`` sees: the offers and agreements its nation is a party to, and every
    published agreement. With ``post`` (a commander held to his post, PVW): the published
    agreements and any naming a force he commands, no offers."""
    own = _nation(state, seat)
    a = state.agreements
    if post:
        return Agreements(
            made={
                k: x
                for k, x in a.made.items()
                if x.public or (own is not None and _names_his_force(state, seat, own, x))
            }
        )
    return Agreements(
        offers={k: o for k, o in a.offers.items() if own is not None and own in o.parties},
        made={
            k: x for k, x in a.made.items() if x.public or (own is not None and own in x.parties)
        },
    )


def _names_his_force(state: "State", seat: SeatId, own: EntityId, agreement: Agreement) -> bool:
    """Whether a clause of ``agreement`` binding ``own`` names a force ``seat`` commands."""
    from revisionist.core.realism.war_rules import commanders

    return any(
        c.force is not None and seat in {s for s, _ in commanders(state, c.force)}
        for c in agreement.clauses
        if c.binds == own
    )


def parties_scope(state: "State", parties: Sequence[EntityId]) -> "Scope":
    """Sealed to the seats of the parties' nations."""
    from revisionist.core.realism.holders import holding_seats
    from revisionist.core.visibility import Scope, Visibility

    seats = frozenset(s for p in parties for s in holding_seats(state, p))
    if not seats:
        seats = frozenset({SeatId(derived_id(state.campaign_id, "engine-only", "agreements"))})
    return Scope(visibility=Visibility.RESTRICTED, known_by=seats)


# --- filing ---------------------------------------------------------------------------


def clause_refusal(state: "State", clause: AgreementClause) -> str:
    """Why a clause names what the world does not have; empty when it does not."""
    from revisionist.core.ontology import EntityKind

    board = state.map
    areas = set(board.areas()) if board is not None else set()
    regions = {r.key for r in board.regions} if board is not None else set()
    if clause.nation is not None:
        found = state.entities.get(clause.nation)
        if found is None or found.kind is not EntityKind.POLITY:
            return "A clause names a nation the world does not have."
    if clause.area is not None and clause.area not in areas:
        return "A clause names an area that is not on the map."
    if clause.region is not None and clause.region not in regions:
        return "A clause names a region that is not on the map."
    if clause.force is not None and clause.force not in state.features:
        return "A clause names a piece the world does not have."
    return ""


def refusal(state: "State", seat: SeatId, deal: Deal) -> str:
    """Why an offer or a publishing order may not be filed; empty when it may."""
    if not on(state):
        return NOT_ON
    own = _nation(state, seat)
    if deal.publish is not None:
        found = state.agreements.made.get(deal.publish)
        if found is None or own not in found.parties:
            return "There is no such agreement of yours to publish."
        if found.public:
            return "That agreement is already published."
        return ""
    if own is None or own not in deal.parties:
        return NOT_A_PARTY
    from revisionist.core.ontology import EntityKind

    for party in deal.parties:
        found_party = state.entities.get(party)
        if found_party is None or found_party.kind is not EntityKind.POLITY:
            return "Every party to an agreement is a nation."
        if party != own and speaker(state, party) is None:
            return f"No one answers for {found_party.name}."
    for clause in deal.clauses:
        why = clause_refusal(state, clause) or _vote_refusal(state, seat, clause)
        if why:
            return why
    return _peace_refusal(state, deal) or _envoy_refusal(state, own, deal)


def _peace_refusal(state: "State", deal: Deal) -> str:
    """A peace clause needs ``peace`` on; an armistice or an end to a war is between two
    nations at war, and every party has a row of the kind peace (PEA rules 1 and 4)."""
    from revisionist.core.realism import locks
    from revisionist.core.realism.war import at_war

    kinds = {c.type for c in deal.clauses}
    if not kinds & {*PEACE_CLAUSES, ClauseType.NO_SEPARATE_PEACE}:
        return ""
    if not peace_on(state):
        return NO_PEACE
    for c in deal.clauses:
        if (
            c.type in PEACE_CLAUSES
            and c.nation is not None
            and not at_war(state, c.binds, c.nation)
        ):
            return f"{_name(state, c.binds)} and {_name(state, c.nation)} are not at war."
    if not carries_peace(deal):
        return ""
    for party in deal.parties:
        if locks.peace_row(state, party) is None:
            return f"No one in {_name(state, party)} may accept a peace."
    return ""


def _envoy_refusal(state: "State", own: EntityId, deal: Deal) -> str:
    """An envoy carries an offer to one other nation that has a capital, and is a piece
    of the offering nation's whose kind has the ``envoy`` domain (ENV rule 2)."""
    from revisionist.core.realism import kinds, territory
    from revisionist.core.realism.geography import in_play

    if deal.envoy is None:
        return ""
    found = state.features.get(deal.envoy)
    if (
        found is None
        or not in_play(found)
        or kinds.domain(state, found) is not kinds.Domain.ENVOY
        or territory.nation(state, found.side) != own
    ):
        return "An offer's envoy is an envoy of your own nation's."
    if len(deal.parties) != 2:
        return "An envoy carries an offer to one other nation."
    if capital_area(state, deal.counterparty) is None:
        name = _entity_name(state, deal.counterparty)
        return f"{name} has no capital for an envoy to reach."
    return ""


def _entity_name(state: "State", entity: EntityId) -> str:
    found = state.entities.get(entity)
    return found.name if found is not None else str(entity)


def capital_area(state: "State", nation: EntityId) -> EntityId | None:
    """The area that holds ``nation``'s capital, as an envoy stands there; None for a
    nation with no capital or a game with no board."""
    from revisionist.core.realism import territory
    from revisionist.core.realism.kinds import Domain

    board = state.map
    place = board.capitals.get(nation) if board is not None else None
    return None if place is None else territory.area_of(state, place, Domain.ENVOY)


def envoy_at(state: "State", envoy: FeatureId, nation: EntityId) -> date | None:
    """The day from which the envoy has stood, in play, in the area that holds
    ``nation``'s capital: the last day it was set down (``as_of``), which is never earlier
    than the day it stepped in. None while it stands elsewhere (ENV)."""
    from revisionist.core.realism.geography import in_play

    found = state.features.get(envoy)
    area = capital_area(state, nation)
    if found is None or area is None or not in_play(found) or found.places[0] != area:
        return None
    return found.as_of


def envoy_at_capital(state: "State", frm: EntityId, nation: EntityId) -> date | None:
    """The earliest day from which an envoy of ``frm``'s has stood at ``nation``'s
    capital, by the rule of ``envoy_at``; None when none stands there (ENV rule 3)."""
    from revisionist.core.realism import kinds, territory

    days = [
        since
        for f in sorted(state.features.values(), key=lambda x: x.feature_id)
        if kinds.domain(state, f) is kinds.Domain.ENVOY
        and territory.nation(state, f.side) == frm
        and (since := envoy_at(state, f.feature_id, nation)) is not None
    ]
    return min(days, default=None)


def _vote_refusal(state: "State", seat: SeatId, clause: AgreementClause) -> str:
    """A vote clause names a conference the seat knows of, and falls due no earlier than
    its voting day (rule 6, CNF)."""
    from revisionist.core.realism import conference

    if clause.type is not ClauseType.VOTE:
        return ""
    found = conference.seen_by(state, seat).held.get(clause.text)
    if found is None:
        return "A vote clause names a conference you know of."
    if clause.on is not None and clause.on < found.voting_day:
        return "A vote clause falls due no earlier than its conference's voting day."
    return ""


def offer_parts(state: "State", seat: SeatId, ask: str, deal: Deal) -> tuple[RoutedPart, ...]:
    """One influence part for each named nation but the offering one, aimed at the person
    who answers for it, in the parties' order."""
    own = _nation(state, seat)
    out: list[RoutedPart] = []
    for party in deal.parties:
        if party == own:
            continue
        target = speaker(state, party)
        assert target is not None
        out.append(
            RoutedPart(
                route=Route.INFLUENCE,
                ask=ask,
                effect=deal.model_copy(update={"counterparty": party}),
                target=target,
            )
        )
    return tuple(out)


def publish_part(ask: str, deal: Deal) -> RoutedPart:
    """The command the seat carries out itself that publishes an agreement."""
    return RoutedPart(route=Route.COMMAND, ask=ask, effect=deal, domain=PUBLISH_DOMAIN)


def due(routed: "RoutedOrder", delivered: date | None = None) -> date:
    """An offer's due day: its expiry, counted from its delivery (by default, its filing)."""
    return (delivered or routed.filed) + timedelta(days=OFFER_DAYS)


def carried(routed: "RoutedOrder") -> FeatureId | None:
    """The envoy that carries the order's offer, where one does."""
    deal = _offer_of(routed)
    return deal.envoy if deal is not None else None


def delivered_on(state: "State", routed: "RoutedOrder") -> date | None:
    """The day the order's offer reached the other nation: its filing, or for an offer an
    envoy carries the day of delivery, None before it (ENV rule 2)."""
    if carried(routed) is None:
        return routed.filed
    found = state.agreements.offers.get(routed.order_id)
    return None if found is None else found.expires - timedelta(days=OFFER_DAYS)


def lapse_day(routed: "RoutedOrder") -> date:
    """The day an offer its envoy has not delivered lapses."""
    return routed.filed + timedelta(days=CARRY_DAYS)


def make_offer(
    state: "State", routed: "RoutedOrder", deal: Deal, delivered: date | None = None
) -> AgreementOffer:
    """The offer an order carries, as its parties know it; delivered on ``delivered``
    when an envoy carries it."""
    own = _nation(state, routed.issuer)
    return AgreementOffer(
        offer_id=routed.order_id,
        version=version(deal.parties, deal.wording, deal.clauses),
        parties=deal.parties,
        by=own or deal.parties[0],
        wording=deal.wording,
        clauses=deal.clauses,
        filed=routed.filed,
        expires=due(routed, delivered),
    )


# --- the day walk ---------------------------------------------------------------------


def _offer_of(routed: "RoutedOrder") -> Deal | None:
    found = [p.effect for p in routed.parts if is_offer(p)]
    deal = found[0] if found else None
    return deal if isinstance(deal, Deal) else None


def _split(text: str) -> list[str]:
    """``text`` in lines of at most ``LINE`` characters, broken at words; never cut short."""
    out: list[str] = []
    line = ""
    for word in text.split():
        while len(word) > LINE:
            out += [line] if line else []
            out.append(word[:LINE])
            word, line = word[LINE:], ""
        if line and len(line) + 1 + len(word) > LINE:
            out.append(line)
            line = ""
        line = f"{line} {word}".strip()
    return [*out, line] if line else out


def _paper(
    state: "State",
    seat: SeatId,
    key: Sequence[str],
    day: date,
    title: str,
    rows: list[tuple[str, str]],
) -> "Payload | None":
    from revisionist.core import events as ev
    from revisionist.core.canary import scan_text
    from revisionist.core.realism.card import ChannelKind
    from revisionist.core.realism.document import (
        BodyField,
        Classification,
        DocumentKind,
        DocumentTruth,
        DocumentView,
    )
    from revisionist.core.visibility import private_to

    doc_id = DocumentId(derived_id(state.campaign_id, "agreement-paper", *key, seat))
    if doc_id in state.documents:
        return None
    body = [BodyField(label=label, value=v) for label, text in rows for v in _split(text)]
    body = [
        b.model_copy(update={"value": "Withheld."})
        if isinstance(b.value, str) and scan_text(state, seat, b.value)
        else b
        for b in body
    ]
    nation = _nation(state, seat)
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.REPORT,
            author=nation if nation is not None else state.seats[seat].embodies,
            issued=day,
            arrives=day,
            channel=ChannelKind.CABLE,
            classification=Classification.CONFIDENTIAL,  # [proposed]
            title=title[:LINE],
            body=tuple(body),
            scope=private_to(seat),
        ),
        truth=DocumentTruth(doc_id=doc_id),
    )


def papers(
    state: "State",
    parties: Sequence[EntityId],
    key: Sequence[str],
    day: date,
    title: str,
    rows: list[tuple[str, str]],
    about: "Agreement | AgreementOffer | None" = None,
) -> list["Payload"]:
    """A paper to every seat of each of ``parties``. One ``about`` an offer or an agreement
    skips a seat held to his post that would not see it (``seen_by`` with ``post``)."""
    from revisionist.core.project import at_post
    from revisionist.core.realism.holders import holding_seats

    out: list[Payload] = []
    for party in parties:
        for seat in holding_seats(state, party):
            if about is not None and at_post(state, seat) and not _post_sees(state, seat, about):
                continue
            paper = _paper(state, seat, key, day, title, rows)
            if paper is not None:
                out.append(paper)
    return out


def _post_sees(state: "State", seat: SeatId, about: "Agreement | AgreementOffer") -> bool:
    """Whether a commander held to his post sees ``about``: no offer, and an agreement
    only when published or naming a force he commands, as ``seen_by`` has it."""
    if not isinstance(about, Agreement):
        return False
    own = _nation(state, seat)
    return about.public or (own is not None and _names_his_force(state, seat, own, about))


def statuses(clauses: Sequence[AgreementClause]) -> tuple[ClauseStatus, ...]:
    """Each clause's status when an agreement is made: unchecked for wording, standing
    for every other (a vote clause stands until its conference's tally judges it)."""
    return tuple(
        ClauseStatus.UNCHECKED if c.type is ClauseType.UNCHECKED else ClauseStatus.STANDING
        for c in clauses
    )


def _made(state: "State", offer: AgreementOffer, day: date) -> "Agreement":
    return Agreement(
        agreement_id=agreement_id(state.campaign_id, offer.offer_id),
        version=offer.version,
        parties=offer.parties,
        wording=offer.wording,
        clauses=offer.clauses,
        made=day,
        offer_id=offer.offer_id,
        statuses=statuses(offer.clauses),
    )


def pact(
    campaign_id: str,
    key: str,
    parties: Sequence[EntityId],
    wording: str,
    clauses: Sequence[AgreementClause],
    start: date,
    public: bool,
) -> Agreement:
    """A world's pact (PCT): an agreement in force from ``start``, made with no offer, its
    clauses judged as any agreement's. A public pact is published on ``start``."""
    return Agreement(
        agreement_id=derived_id(campaign_id, "pact", key),
        version=version(parties, wording, clauses),
        parties=tuple(parties),
        wording=wording,
        clauses=tuple(clauses),
        made=start,
        published=start if public else None,
        statuses=statuses(clauses),
    )


def offers_due(state: "State", day: date) -> list["Payload"]:
    """With ``agreements`` on: each offer filed by ``day`` recorded for its parties; each
    offer whose every part is decided closed, before any part's effect could land: made
    when every named nation accepted it, else lapsed, a paper to every party's seats
    either way; and each publishing order carried out, published."""
    if not on(state):
        return []
    from revisionist.core import events as ev

    out: list[Payload] = []
    done: set[str] = set()
    for routed in sorted(state.routed.values(), key=lambda o: (o.filed, o.order_id)):
        deal = _offer_of(routed)
        if deal is not None:
            out += _offer_day(state, routed, deal, day, done)
            continue
        for i, part in enumerate(routed.parts):
            if not is_publish(part) or part.applied is not None or part.executed is None:
                continue
            if part.executed > day:
                continue
            assert isinstance(part.effect, Deal) and part.effect.publish is not None
            found = state.agreements.made.get(part.effect.publish)
            if found is not None and not found.public:
                out.append(
                    ev.AgreementPublished(
                        agreement_id=found.agreement_id,
                        by=_nation(state, routed.issuer) or found.parties[0],
                        on=day,
                    )
                )
            out.append(ev.EffectsApplied(order_id=routed.order_id, part=i, on=day))
    return out + _separate_peaces(state, done, day)


def _offer_day(
    state: "State", routed: "RoutedOrder", deal: Deal, day: date, done: set[str]
) -> list["Payload"]:
    from revisionist.core import events as ev

    out: list[Payload] = []
    offer = state.agreements.offers.get(routed.order_id)
    if offer is None and deal.envoy is not None:
        return _undelivered(state, routed, deal, day)
    if offer is None:
        if routed.filed > day:
            return []
        offer = make_offer(state, routed, deal)
        out.append(ev.AgreementOffered(offer=offer))
    parts = [(i, p) for i, p in enumerate(routed.parts) if is_offer(p)]
    if any(p.decided is None for _, p in parts) or all(p.applied is not None for _, p in parts):
        return out
    out += [
        ev.EffectsApplied(order_id=routed.order_id, part=i, on=day)
        for i, p in parts
        if p.applied is None
    ]
    terms = term_rows(state, offer)
    if all(p.accepted for _, p in parts):
        if carries_peace(offer) and peace_on(state):
            out += _peace_close(state, routed, offer, day, done)
        else:
            out += made_now(state, offer, day, done)
    else:
        out += papers(
            state,
            offer.parties,
            ("lapsed", offer.offer_id),
            day,
            "An offer of agreement lapsed",
            [("Why", "Not every named nation accepted it."), *terms],
            offer,
        )
    return out


def made_now(
    state: "State", offer: AgreementOffer, day: date, done: set[str] | None = None
) -> list["Payload"]:
    """The agreement made from ``offer`` on ``day``, with a paper to every party's seats,
    and, with ``peace`` on, each war its terms end (``wars_ended``). Within a pass that
    carries ``done``, the wars ended already that day, an offer that would end one of
    them lapses instead, and the separate peaces are left to the end of the pass."""
    from revisionist.core import events as ev

    if done is not None and _ends_ended(state, offer, done):
        rows = [("Why", WAR_ENDED), *term_rows(state, offer)]
        title = "An offer of agreement lapsed"
        return papers(state, offer.parties, ("lapsed", offer.offer_id), day, title, rows, offer)
    made = _made(state, offer, day)
    out: list[Payload] = [ev.AgreementMade(agreement=made)]
    terms = term_rows(state, offer)
    out += papers(
        state,
        offer.parties,
        ("made", made.agreement_id),
        day,
        "An agreement is in force",
        terms,
        made,
    )
    if done is None:
        return out + wars_ended(state, made, day)
    return out + wars_ended(state, made, day, done, separate=False)


def _ends_ended(state: "State", offer: AgreementOffer, done: set[str]) -> bool:
    """Whether an end-to-the-war clause of ``offer`` names a war in ``done``."""
    from revisionist.core.realism.war import war_id_for

    if not peace_on(state):
        return False
    return any(
        c.type is ClauseType.END_WAR
        and c.nation is not None
        and war_id_for(c.binds, c.nation) in done
        for c in offer.clauses
    )


# --- peace: the held acceptance (PEA rule 4) -------------------------------------------


def hold_id(campaign_id: str, offer_id: str, nation: EntityId) -> OrderId:
    """The id of ``nation``'s held acceptance of the offer ``offer_id``."""
    return OrderId(derived_id(campaign_id, "peace-hold", offer_id, nation))


def _acceptors(state: "State", routed: "RoutedOrder") -> list[tuple[EntityId, EntityId]]:
    """Each party nation with the person who accepted for it: the offering seat's person
    for the offering nation, the person each part went to for the others."""
    deal = _offer_of(routed)
    assert deal is not None
    out = [(_nation(state, routed.issuer) or deal.parties[0], state.seats[routed.issuer].embodies)]
    for part in routed.parts:
        if is_offer(part) and part.target is not None and isinstance(part.effect, Deal):
            out.append((part.effect.counterparty, part.target))
    return out


def _held_nations(state: "State", routed: "RoutedOrder") -> list[EntityId] | None:
    """The nations whose acceptance waits on their row of the kind peace: each whose row's
    decider is not the person who accepted. None when a nation has no such row."""
    from revisionist.core.realism import locks

    out: list[EntityId] = []
    for nation, person in _acceptors(state, routed):
        row = locks.peace_row(state, nation)
        if row is None:
            return None
        if row.decider.person != person:
            out.append(nation)
    return out


def _peace_close(
    state: "State", routed: "RoutedOrder", offer: AgreementOffer, day: date, done: set[str]
) -> list["Payload"]:
    """Every nation accepted an offer of peace: the agreement is made at once when each
    nation's row of the kind peace names the person who accepted; else each other
    acceptance is held for its row's decider and asked for, the same day. A nation with no
    such row lapses the offer."""
    from revisionist.core import events as ev
    from revisionist.core.realism import locks
    from revisionist.core.realism.agenda import Ask
    from revisionist.core.realism.process import holder

    held = _held_nations(state, routed)
    terms = term_rows(state, offer)
    if held is None:
        why = [("Why", NOT_ALLOWED), *terms]
        title = "An offer of agreement lapsed"
        return papers(state, offer.parties, ("lapsed", offer.offer_id), day, title, why, offer)
    if not held:
        return made_now(state, offer, day, done)
    deal = _offer_of(routed)
    assert deal is not None
    accepted = dict(_acceptors(state, routed))
    out: list[Payload] = []
    seats = {n: routed.issuer if n == offer.by else holder(state, accepted[n]) for n in held}
    if any(s is None for s in seats.values()):
        why = [("Why", NOT_ALLOWED), *terms]
        title = "An offer of agreement lapsed"
        return papers(state, offer.parties, ("lapsed", offer.offer_id), day, title, why, offer)
    for nation in held:
        row = locks.peace_row(state, nation)
        seat = seats[nation]
        assert row is not None and seat is not None
        lock = locks.Lock(row=row, decider=row.decider)
        hold = locks.HeldOrder(
            order_id=hold_id(state.campaign_id, offer.offer_id, nation),
            issuer=seat,
            filed=day,
            asks=(Ask(ask=ACCEPT_PEACE, effect=deal),),
            row=row.key,
            decider=row.decider,
            reason=locks.reason(state, lock),
        )
        asked = locks.asked_for(state, hold, day)
        out.append(ev.OrderHeld(held=hold))
        if asked is not None:
            out.append(ev.OrderAsked(asked=asked))
    return out


def is_peace_hold(state: "State", held: "HeldOrder") -> bool:
    """Whether ``held`` is a nation's held acceptance of an offer of peace."""
    deal = held.asks[0].effect if held.asks else None
    if not isinstance(deal, Deal) or held.asks[0].ask != ACCEPT_PEACE:
        return False
    return any(
        held.order_id == hold_id(state.campaign_id, o.offer_id, n)
        for o in state.agreements.offers.values()
        for n in o.parties
    )


def peace_due(state: "State", day: date) -> list["Payload"]:
    """With ``peace`` on, each offer of peace whose acceptances are held, once a day after
    the day's asks are answered: made when every held acceptance is allowed; lapsed, with a
    paper to every party's seats, when one is declined or taken back, or when another
    offer ended its war earlier in the pass. Each held acceptance ends either way."""
    if not peace_on(state):
        return []
    from revisionist.core import events as ev
    from revisionist.core.realism.locks import HeldEnd

    out: list[Payload] = []
    done: set[str] = set()
    for offer in sorted(state.agreements.offers.values(), key=lambda o: (o.filed, o.offer_id)):
        routed = state.routed.get(offer.offer_id)
        if routed is None or not carries_peace(offer):
            continue
        if agreement_id(state.campaign_id, offer.offer_id) in state.agreements.made:
            continue
        parts = [p for p in routed.parts if is_offer(p)]
        if any(p.applied is None or not p.accepted for p in parts):
            continue  # still before its parties, or not accepted by every one
        nations = _held_nations(state, routed) or []
        ids = [hold_id(state.campaign_id, offer.offer_id, n) for n in nations]
        present = [state.held[i] for i in ids if i in state.held]
        if not ids:
            continue
        answers = [
            state.asked[h.order_id].granted if h.order_id in state.asked else None for h in present
        ]
        allowed = bool(present) and len(present) == len(ids) and all(answers)
        if allowed and not _ends_ended(state, offer, done):
            out += [
                ev.HeldOrderEnded(
                    order_id=h.order_id,
                    issuer=h.issuer,
                    on=day,
                    end=HeldEnd.LANDED,
                    by=offer.offer_id,
                )
                for h in present
            ]
            out += made_now(state, offer, day, done)
        elif allowed or len(present) < len(ids) or False in answers:
            why = WAR_ENDED if allowed else NOT_ALLOWED
            out += [
                ev.HeldOrderEnded(
                    order_id=h.order_id,
                    issuer=h.issuer,
                    on=day,
                    end=HeldEnd.FAILED,
                    reason=why,
                )
                for h in present
            ]
            rows = [("Why", why), *term_rows(state, offer)]
            title = "An offer of agreement lapsed"
            out += papers(state, offer.parties, ("lapsed", offer.offer_id), day, title, rows, offer)
    return out + _separate_peaces(state, done, day)


# --- peace: wars ended, the armistice and the separate peace (PEA rules 2, 3, 5) --------


def armistice(state: "State", a: EntityId, b: EntityId) -> bool:
    """Whether an armistice between ``a`` and ``b`` is in force: a standing armistice
    clause of an agreement made, between the two, with ``peace`` on."""
    if not peace_on(state):
        return False
    pair = {a, b}
    return any(
        c.type is ClauseType.ARMISTICE
        and x.statuses[n] is ClauseStatus.STANDING
        and {c.binds, c.nation} == pair
        for x in state.agreements.made.values()
        for n, c in enumerate(x.clauses)
    )


def wars_ended(
    state: "State",
    x: Agreement,
    day: date,
    done: set[str] | None = None,
    separate: bool = True,
) -> list["Payload"]:
    """With ``peace`` on, each war in force since before ``x`` was made that a standing
    end-to-the-war clause of ``x`` ends, once (``done`` holds the wars ended already in
    the same pass), then, when ``separate``, every pact's clause against a separate peace
    that it breaks."""
    from revisionist.core import events as ev
    from revisionist.core.realism.war import war_id_for

    if not peace_on(state):
        return []
    done = set() if done is None else done
    out: list[Payload] = []
    pairs: list[tuple[EntityId, EntityId]] = []
    for n, c in enumerate(x.clauses):
        if c.type is not ClauseType.END_WAR or c.nation is None:
            continue
        if x.statuses and x.statuses[n] is not ClauseStatus.STANDING:
            continue
        found = state.wars.get(war_id_for(c.binds, c.nation))
        if found is None or found.since >= x.made or found.war_id in done:
            continue
        done.add(found.war_id)
        pairs.append((c.binds, c.nation))
        out.append(ev.WarEnded(war_id=found.war_id, on=day, agreement_id=x.agreement_id))
    if not separate:
        return out
    return out + _separate_peace(state, pairs, day)


def _separate_peaces(state: "State", done: set[str], day: date) -> list["Payload"]:
    """The separate peaces broken by every war a pass ended (``done``), judged once."""
    pairs = [(state.wars[w].a, state.wars[w].b) for w in sorted(done)]
    return _separate_peace(state, pairs, day) if pairs else []


def _separate_peace(
    state: "State", pairs: Sequence[tuple[EntityId, EntityId]], day: date
) -> list["Payload"]:
    """Each standing clause against a separate peace that the wars ending in ``pairs``
    break: its party's war with the named enemy ends while another party's goes on (rule 5)."""
    from revisionist.core.realism.war import at_war

    ending = {frozenset(p) for p in pairs}
    out: list[Payload] = []
    for x in sorted(state.agreements.made.values(), key=lambda a: (a.made, a.agreement_id)):
        for n, c in enumerate(x.clauses):
            if c.type is not ClauseType.NO_SEPARATE_PEACE or c.nation is None:
                continue
            if x.statuses[n] is not ClauseStatus.STANDING or x.made > day:
                continue
            if frozenset((c.binds, c.nation)) not in ending:
                continue
            fighting = [
                p
                for p in x.parties
                if p != c.binds
                and at_war(state, p, c.nation)
                and frozenset((p, c.nation)) not in ending
            ]
            if fighting:
                why = (
                    f"{_name(state, c.binds)} made peace with {_name(state, c.nation)} while "
                    f"{_name(state, fighting[0])} fights on."
                )
                out += _judged(state, x, n, ClauseStatus.BROKEN, why, day)
    return out


def _on_ground(state: "State", nation: EntityId, other: EntityId) -> str | None:
    """The name of the first piece of ``nation``'s, in id order, standing in play on ground
    ``other`` holds; an envoy is not counted. None when there is none."""
    from revisionist.core.realism import kinds, territory

    for f in sorted(state.features.values(), key=lambda x: x.feature_id):
        if territory.nation(state, f.side) != nation:
            continue
        if kinds.domain(state, f) is kinds.Domain.ENVOY:
            continue
        area = _area_of_piece(state, f.feature_id)
        if area is not None and territory.holder(state, area) == other:
            return f.name
    return None


def _undelivered(state: "State", routed: "RoutedOrder", deal: Deal, day: date) -> list["Payload"]:
    """An offer its envoy has not delivered: once its parts are decided on the lapse day,
    closed with a paper to the offering nation's seats only; the other nation never knew
    of it (ENV rule 2)."""
    from revisionist.core import events as ev

    parts = [(i, p) for i, p in enumerate(routed.parts) if is_offer(p)]
    if any(p.decided is None for _, p in parts) or all(p.applied is not None for _, p in parts):
        return []
    out: list[Payload] = [
        ev.EffectsApplied(order_id=routed.order_id, part=i, on=day)
        for i, p in parts
        if p.applied is None
    ]
    offer = make_offer(state, routed, deal)
    why = "Its envoy did not reach the capital in time."
    out += papers(
        state,
        (offer.by,),
        ("lapsed", offer.offer_id),
        day,
        "An offer of agreement lapsed",
        [("Why", why), *term_rows(state, offer)],
        offer,
    )
    return out


def deliveries(state: "State", day: date) -> list["Payload"]:
    """With ``agreements`` on, each offer an envoy carries delivered on ``day``, read after
    the day's moves: recorded for its parties, its expiry counted from the day the envoy
    came to stand at the other nation's capital, never before it nor before the filing,
    and before the lapse day (ENV rule 2)."""
    if not on(state):
        return []
    from revisionist.core import events as ev

    out: list[Payload] = []
    for routed in sorted(state.routed.values(), key=lambda o: (o.filed, o.order_id)):
        deal = _offer_of(routed)
        if deal is None or deal.envoy is None or routed.order_id in state.agreements.offers:
            continue
        if routed.filed > day or lapse_day(routed) <= day:
            continue
        if any(p.decided is not None for p in routed.parts if is_offer(p)):
            continue
        since = envoy_at(state, deal.envoy, deal.counterparty)
        if since is None:
            continue
        delivered = min(day, max(routed.filed, since))
        out.append(ev.AgreementOffered(offer=make_offer(state, routed, deal, delivered)))
    return out


# --- judging --------------------------------------------------------------------------


def _area_of_piece(state: "State", piece: FeatureId) -> EntityId | None:
    from revisionist.core.realism import kinds, territory
    from revisionist.core.realism.geography import in_play
    from revisionist.core.realism.kinds import Domain

    found = state.features.get(piece)
    if found is None or not in_play(found):
        return None
    domain = kinds.domain(state, found) or Domain.LAND
    return territory.area_of(state, found.places[0], domain)


def _in_region(state: "State", area: EntityId | None, region: str) -> bool:
    board = state.map
    if area is None or board is None:
        return False
    found = {t.area: t.region for t in board.territories}
    found.update({z.area: z.region for z in board.sea_zones})
    return found.get(area) == region


def _place_kept(state: "State", c: AgreementClause) -> bool:
    assert c.force is not None
    area = _area_of_piece(state, c.force)
    here = area == c.area if c.area is not None else _in_region(state, area, c.region or "")
    return here == c.present


def _form_kept(state: "State", c: AgreementClause) -> bool:
    from revisionist.core.realism.pipeline import OrderStatus
    from revisionist.core.realism.resolvers import settled_on

    assert c.on is not None
    return any(
        o.lever == c.form
        and o.status is OrderStatus.ENACTED
        and settled_on(o) <= c.on
        and _nation(state, o.issuer) == c.binds
        for o in state.orders.values()
    )


def _aid_kept(state: "State", c: AgreementClause) -> bool:
    from revisionist.core.realism.resolvers.production import aid_shares

    assert c.on is not None and c.nation is not None and c.share is not None
    return aid_shares(state, c.binds, c.on).get(c.nation, 0) >= c.share


def _attacks(today: Sequence["Payload"]) -> list[tuple[EntityId, EntityId]]:
    """Each (attacker, attacked) pair a battle opened today, in the battles' order. A
    meeting battle is an attack by each side on the other."""
    from revisionist.core import events as ev

    out: list[tuple[EntityId, EntityId]] = []
    for p in today:
        if isinstance(p, ev.BattleOpened):
            a, d = p.battle.attacker.nation, p.battle.defender.nation
            out.append((a, d))
            if p.battle.meeting:
                out.append((d, a))
    return out


def _entered(today: Sequence["Payload"], nation: EntityId, area: EntityId) -> bool:
    from revisionist.core import events as ev

    return any(
        isinstance(p, ev.PieceStepped) and p.nation == nation and p.entered == area for p in today
    )


def _declared(state: "State", a: EntityId, b: EntityId, since: date) -> bool:
    from revisionist.core.realism.war import war_id_for

    war = state.wars.get(war_id_for(a, b))
    return war is not None and war.a == a and war.b == b and war.since >= since


def _verdict(
    state: "State", x: Agreement, n: int, day: date, today: Sequence["Payload"]
) -> "list[tuple[ClauseStatus, EntityId | None, date | None, str]]":
    """What judging clause ``n`` of ``x`` on ``day`` finds: (status, against, due,
    reason) for each change; none when it stands as it was."""
    from revisionist.core.realism.war import at_war

    c = x.clauses[n]
    status = x.statuses[n]
    if status not in (ClauseStatus.STANDING, ClauseStatus.CALLED):
        return []
    dated = c.on is not None
    if dated and c.type in (ClauseType.PLACE, ClauseType.FORM, ClauseType.AID):
        assert c.on is not None
        if day < c.on:
            return []
        kept = {
            ClauseType.PLACE: _place_kept,
            ClauseType.FORM: _form_kept,
            ClauseType.AID: _aid_kept,
        }[c.type](state, c)
        return [(ClauseStatus.KEPT if kept else ClauseStatus.BROKEN, None, None, "On its day.")]
    broken = ""
    out: list[tuple[ClauseStatus, EntityId | None, date | None, str]] = []
    match c.type:
        case ClauseType.KEEP_OUT:
            assert c.area is not None
            if _entered(today, c.binds, c.area):
                broken = f"A piece of {_name(state, c.binds)} entered {_name(state, c.area)}."
        case ClauseType.NO_WAR:
            assert c.nation is not None
            if _declared(state, c.binds, c.nation, x.made):
                broken = f"{_name(state, c.binds)} declared war on {_name(state, c.nation)}."
        case ClauseType.NO_ATTACK:
            if (c.binds, c.nation) in _attacks(today):
                broken = f"{_name(state, c.binds)} attacked {_name(state, c.nation)}."
        case ClauseType.DEFEND:
            assert c.nation is not None and c.days is not None
            calls = [k for k in x.calls if k.clause == n]
            for k in calls:
                if at_war(state, c.binds, k.against):
                    out.append((ClauseStatus.KEPT, k.against, None, "War was declared."))
                elif day > k.due:
                    broken = f"No war declared on {_name(state, k.against)} in time."
            called = {k.against for k in calls}
            for attacker, attacked in _attacks(today):
                if attacked != c.nation or attacker in (c.binds, c.nation) or attacker in called:
                    continue
                if at_war(state, c.binds, attacker):
                    continue
                called.add(attacker)
                when = day + timedelta(days=c.days)
                why = f"{_name(state, attacker)} attacked {_name(state, c.nation)}."
                out.append((ClauseStatus.CALLED, attacker, when, why))
        case ClauseType.ARMISTICE if peace_on(state):
            assert c.days is not None and c.nation is not None
            if day < x.made + timedelta(days=c.days):
                return []
            over = not at_war(state, c.binds, c.nation)
            return [(ClauseStatus.KEPT, None, None, TERMS if over else "Its days ran out.")]
        case ClauseType.END_WAR if peace_on(state):
            assert c.nation is not None
            piece = _on_ground(state, c.binds, c.nation)
            if _declared(state, c.binds, c.nation, x.made):
                broken = f"{_name(state, c.binds)} declared war on {_name(state, c.nation)}."
            elif day >= x.made + timedelta(days=WITHDRAW_DAYS) and piece is not None:
                who, other = _name(state, c.binds), _name(state, c.nation)
                broken = f"{piece} of {who} stands on {other}'s ground."
            else:
                return []
        case _:
            return []
    if broken:
        return [(ClauseStatus.BROKEN, None, None, broken)]
    still_called = any(
        k.clause == n and not at_war(state, c.binds, k.against) for k in x.calls
    ) or any(o[0] is ClauseStatus.CALLED for o in out)
    if c.on is not None and day >= c.on and not still_called:
        out.append((ClauseStatus.KEPT, None, None, "Kept to its last day."))
    return out


def _regard(state: "State", breaker: EntityId, wronged: EntityId) -> "list[Payload]":
    from revisionist.core import events as ev
    from revisionist.core.ids import RelationshipId
    from revisionist.core.ontology import Relationship

    a, b = speaker(state, wronged), speaker(state, breaker)
    if a is None or b is None or a == b:
        return []
    found = [r for r in state.relationships.values() if {r.a, r.b} == {a, b}]
    if not found:
        rel = Relationship(
            relationship_id=RelationshipId(derived_id(state.campaign_id, "rel", a, b)),
            a=a,
            b=b,
            disposition=max(REGARD_FLOOR, BREAK_REGARD),
            scope=parties_scope(state, (wronged, breaker)),
        )
        return [ev.RelationshipSet(relationship=rel)]
    return [
        ev.RelationshipSet(
            relationship=r.model_copy(
                update={
                    "disposition": max(REGARD_FLOOR, min(REGARD_TOP, r.disposition + BREAK_REGARD))
                }
            )
        )
        for r in found
    ]


def broken_costs(state: "State", x: Agreement, n: int, day: date) -> list["Payload"]:
    """What a broken clause costs: regard between the breaker's leader and each other
    party's leader, and, when the agreement is public, the breaker's groups."""
    from revisionist.core.realism import groups
    from revisionist.core.realism.groups import Happening

    breaker = x.clauses[n].binds
    out: list[Payload] = []
    for party in x.parties:
        if party == breaker:
            continue
        out += _regard(state, breaker, party)
    if x.public and groups.on(state):
        out += groups.happened(state, breaker, Happening.AGREEMENT_BROKEN, day)
    return out


_TITLES = {
    ClauseStatus.KEPT: "A clause of an agreement was kept",
    ClauseStatus.BROKEN: "A clause of an agreement was broken",
    ClauseStatus.CALLED: "A clause of an agreement is called on",
    ClauseStatus.VOID: "A clause of an agreement is void",
}


def title_of(status: ClauseStatus) -> str:
    """The title of the paper a clause judged ``status`` sends."""
    return _TITLES[status]


def judge(state: "State", day: date, today: Sequence["Payload"]) -> list["Payload"]:
    """With ``agreements`` on, each agreement's typed clauses judged on ``day`` from the
    state and the day's events (``today``): a dated clause on its date, a standing one
    each day. Each judgement is a ``clause_judged`` with a paper to every party's seats;
    a broken clause also costs what ``broken_costs`` says. Unchecked and vote clauses are
    never judged here: a vote clause is judged by its conference's tally."""
    if not on(state):
        return []
    out: list[Payload] = []
    done: set[str] = set()
    for x in sorted(state.agreements.made.values(), key=lambda a: (a.made, a.agreement_id)):
        if x.made > day:
            continue
        out += wars_ended(state, x, day, done)
        for n in range(len(x.clauses)):
            for status, against, when, why in _verdict(state, x, n, day, today):
                out += _judged(state, x, n, status, why, day, against, when)
    return out


def _judged(
    state: "State",
    x: Agreement,
    n: int,
    status: ClauseStatus,
    why: str,
    day: date,
    against: EntityId | None = None,
    when: date | None = None,
) -> list["Payload"]:
    """Clause ``n`` of ``x`` judged ``status`` on ``day``: the ``clause_judged``, a paper to
    every party's seats, and for a broken clause what ``broken_costs`` says."""
    from revisionist.core import events as ev

    out: list[Payload] = [
        ev.ClauseJudged(
            agreement_id=x.agreement_id,
            clause=n,
            status=status,
            on=day,
            reason=why[:300],
            against=against,
            due=when,
        )
    ]
    rows = [("Clause", render_clause(state, x.clauses[n])), ("Finding", why)]
    if when is not None:
        rows.append(("War due by", _day(when)))
    key = ("judged", x.agreement_id, str(n), status.value, str(against), day.isoformat())
    out += papers(state, x.parties, key, day, _TITLES[status], rows, x)
    if status is ClauseStatus.BROKEN:
        out += broken_costs(state, x, n, day)
    return out


__all__ = [
    "BREAK_REGARD",
    "NO_PEACE",
    "OFFER_DAYS",
    "PUBLISH_DOMAIN",
    "WITHDRAW_DAYS",
    "Agreement",
    "AgreementOffer",
    "Agreements",
    "Call",
    "ClauseStatus",
    "agreement_id",
    "armistice",
    "broken_costs",
    "carries_peace",
    "clause_refusal",
    "due",
    "hold_id",
    "is_offer",
    "is_peace_hold",
    "is_publish",
    "judge",
    "made_now",
    "make_offer",
    "nation_name",
    "offer_parts",
    "offers_due",
    "on",
    "pact",
    "papers",
    "parties_scope",
    "peace_due",
    "peace_on",
    "publish_part",
    "refusal",
    "render_clause",
    "render_terms",
    "seen_by",
    "speaker",
    "statuses",
    "term_rows",
    "title_of",
    "version",
    "wars_ended",
]
