"""Free text read into engine-v2 asks (Phase 4 unit D): a cheap model proposes, the
player signs, and the order is routed and filed with ``realism_tick.commit_order``.

The model sees only the seat's own ``View``. Its asks are kept server-side; the
client is sent the proposal in words.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import zip_longest
from typing import Any

from pydantic import Field, ValidationError

from revisionist.core import events as ev
from revisionist.core._base import Model
from revisionist.core.canary import scan_text
from revisionist.core.ids import CampaignId, EntityId, SeatId
from revisionist.core.ontology import EntityKind
from revisionist.core.project import project
from revisionist.core.realism import agreement, conference
from revisionist.core.realism.agenda import Ask, Option
from revisionist.core.realism.card import ChannelKind, Lever, ParamKind, ParamSpec, words
from revisionist.core.realism.conference import Vote
from revisionist.core.realism.effect import (
    MAX_PARTIES,
    AgreementClause,
    Allocate,
    ClauseType,
    Deal,
    Effect,
    Engagement,
    IntelOrder,
    Investigate,
    MoveForce,
    Posture,
    Route,
    SetEngagement,
)
from revisionist.core.realism.locks import HeldOrder, zone_of
from revisionist.core.realism.reach import channels_to
from revisionist.core.realism.resolvers import intel
from revisionist.core.realism.resolvers.movement import FORCE, TO
from revisionist.core.realism.resolvers.production import _matter
from revisionist.core.realism.resolvers.shipping import ESCORT_LEVEL
from revisionist.core.realism.route import held, route
from revisionist.core.realism.war import polity_of
from revisionist.core.state import Rule, State, View
from revisionist.core.world_compile import object_id
from revisionist.engine import realism_tick
from revisionist.engine.aide import AIDE_MODEL
from revisionist.engine.directive import TEXT_MAX
from revisionist.engine.llm import (
    Request,
    Transport,
    cli_schema,
    prompt_text,
    quote_player,
)
from revisionist.engine.options import _forces, _named_ok
from revisionist.engine.realism_tick import commit_order
from revisionist.engine.store import EventStore, load_state
from revisionist.engine.web.realism_api import OrderProposal, Reply

CALL_CLASS = "aide"
PROMPT = "orders"

_NOT_READ = (ClauseType.VOTE, ClauseType.UNCHECKED)
"""Clause types the reader never proposes: a vote is the conference's, and wording the
rules cannot check is kept as wording."""

MAX_ASKS = 8  # [proposed] parts one order may carry; the Option cap
MAX_TEXT = TEXT_MAX  # [proposed] characters of order text, as a directive
UNREADABLE = "Your aide could not make that into an order you can sign."
NOTHING = "There is nothing to sign. Write your order again."
UNREACHED = "That person is not within your reach."
TO_THE_FORM = "Your aide does not read that kind of order from writing. Use its form."
NO_CLAUSES = (
    "Your aide could not read clauses out of your wording, so it goes as you wrote it and "
    "the rules check nothing in it."
)
CHANGED = "The terms have changed since you read them. Write your order again."
NO_PARTIES = "Name the nation or nations the agreement is with."
WORDING_MAX = 600  # the length a Deal's wording holds
LONG_WORDING = f"The wording of an agreement is at most {WORDING_MAX} characters."
READING = "the aide's reading"
OFFER_ASK = "An offer of an agreement."


@dataclass(frozen=True)
class Reading:
    """A proposal and what signing it files. The server holds it between ``order``
    and ``file``: asks carry ids, and the client is sent words."""

    shown: OrderProposal
    asks: tuple[Ask, ...]
    """Empty: it cannot be filed, and ``shown`` says why."""
    version: str = ""
    """An offer of an agreement: the version the seat reads and signs."""
    terms: str = ""
    """An offer of an agreement: its terms in fixed words, as signing shows them."""
    vote: tuple[str, conference.Vote] | None = None
    """A written vote (CNF): the conference's key and the vote. Signing seals it as the
    conference's vote action does; ``asks`` stays empty, for it is not an order."""
    forms: "tuple[Twin | None, ...]" = ()
    """One per ask: the seat's own form that gives it, as signing files it (``twin``), or
    None for an ask no form gives, routed as written."""


class _Treaty(Model):
    """A written deal, treaty or bill as the reader finds it: the nations it names and
    each clause it takes the wording to hold, as loose objects code checks one by one."""

    parties: tuple[EntityId, ...] = ()
    clauses: tuple[dict[str, Any], ...] = ()


class _Reply(Model):
    asks: tuple[Ask, ...]
    reason: str = ""


class _WrittenAsk(Ask):
    """An ask as the reader gives it with written orders on: it may name the values of its
    form's parameters that its effect cannot hold."""

    detail: dict[str, str | int] = Field(default_factory=dict)


class _War(Model):
    target: EntityId


class _TreatyReply(_Reply):
    """The reply with written orders on: it may also carry a treaty, a declaration of war,
    and an ask's detail. A separate schema, so a world with the rule off sends the request
    it always sent (recordings keep their keys)."""

    asks: tuple[_WrittenAsk, ...]
    treaty: _Treaty | None = None
    war: _War | None = None


class _Ballot(Model):
    conference: str
    vote: Vote


class _VoteReply(_TreatyReply):
    """The reply with written orders and conferences on: it may also carry a vote. A
    separate schema, so a world without conferences sends the request it always sent."""

    vote: _Ballot | None = None


ORDERS_SCHEMA: dict[str, Any] = _Reply.model_json_schema()
TREATY_SCHEMA: dict[str, Any] = _TreatyReply.model_json_schema()
VOTE_SCHEMA: dict[str, Any] = _VoteReply.model_json_schema()
VOTE_PROMPT = (
    "- `vote`: only when the order is the seat's vote in one of the conferences it is "
    "given. Give `conference`, that conference's key, and `vote`: for, against or abstain; "
    "leave `asks` empty and `treaty` out. Otherwise leave `vote` out.\n"
)
TREATY_PROMPT = (
    "\n- `treaty`: only when the order is a written deal, treaty or bill between nations. "
    "Give `parties`, the entity ids of the nations it names, taken from what you are given, "
    "and leave `asks` empty. Otherwise leave `treaty` out.\n"
    "- `treaty.clauses`: only when a clause list is given. Each clause is one object with a "
    "`type` from that list, `binds` (the nation it binds), the fields that type names, and "
    "`on` (a date) when the order dates it. Propose a clause only where the words plainly "
    "say it; wording that fits no listed type is left out, and the order's own words stay "
    "as written. Never write a summary of the terms.\n"
    "- `asks[].detail`: only when the ask fills one of the seat's `forms` and the order names "
    "a value its effect cannot hold, such as a strength or a route: that parameter's name and "
    "the value as the form takes it. Otherwise leave it out.\n"
    "- `war`: only when the order declares war: `target`, the entity id of the nation. Leave "
    "`asks` empty. Otherwise leave `war` out.\n"
)


def _unfileable(
    text: str, reason: str, person: str | None = None, ch: str | None = None
) -> Reading:
    shown = OrderProposal(person=person, channel=ch, text=text, parts=[], reason=reason)
    return Reading(shown=shown, asks=())


def _reachable(state: State, me: EntityId, view: View) -> dict[EntityId, str]:
    """Every person the seat could write to, by id; a person with no channel is not one."""
    return {
        e.entity_id: e.name
        for e in view.entities.values()
        if e.kind is EntityKind.PERSON and e.entity_id != me and channels_to(state, me, e.entity_id)
    }


def _called(name: str, said: str) -> bool:
    """Whether ``said`` names the person: the whole name, or the surname as a word."""
    low = said.lower()
    return name.lower() in low or name.split()[-1].lower() in re.findall(r"[a-z'.-]+", low)


def _addressee(reach: dict[EntityId, str], to: str, text: str) -> EntityId | None:
    """The person ``to`` names, else the one ``text`` names; None when nobody, or when
    the words fit two people."""
    found = [i for i, n in reach.items() if _called(n, to or text)]
    return found[0] if len(found) == 1 else None


def _clause_list(view: View) -> dict[str, Any]:
    """The clause types the reader may propose, with the fields each names, and the
    places and forms the seat can see."""
    from revisionist.core.realism.effect import _CLAUSE_NEEDS

    board = view.map
    return {
        "types": {t.value: list(_CLAUSE_NEEDS[t]) for t in ClauseType if t not in _NOT_READ},
        "areas": sorted(board.areas()) if board is not None else [],
        "regions": [r.key for r in board.regions] if board is not None else [],
        "forms": [x.name for x in view.desk.levers] if view.desk is not None else [],
    }


def orders_prompt(
    view: View,
    person: str,
    channel: str,
    text: str,
    *,
    clauses: bool = False,
    conferences: bool = False,
    forms: bool = False,
) -> str:
    """The seat's own view, compact: desk, date, the objects it may name, then the words.
    A player's words, the order's and each conference text's, stand only in quoted blocks."""
    desk = view.desk
    seat: dict[str, Any] = {"name": view.me.name, "entity": view.me.embodies}
    if desk is not None:
        seat |= {
            "office": desk.office,
            "authority": [
                {
                    "domain": d.name,
                    "effects": sorted(k.value for k in d.effects),
                    "executor": d.executor,
                    "forces": list(d.forces),
                }
                for d in desk.authority
            ],
        }
    world = {
        "date": str(view.in_world_date),
        "seat": seat,
        "entities": [
            {"id": e.entity_id, "name": e.name, "kind": e.kind.value}
            for e in view.entities.values()
        ],
        "features": [{"id": fid, "domain": name} for fid, name in _forces(view).items()],
        "facts": [
            {"id": x.fact_id, "subject": x.subject, "predicate": x.predicate, "obj": x.obj}
            for x in view.facts.values()
        ],
    }
    if clauses:
        world["clause_list"] = _clause_list(view)
    if forms and desk is not None:
        world["forms"] = [
            {"name": x.name, "params": {p.name: list(p.choices) or p.kind.value for p in x.params}}
            for x in desk.levers
        ]
    held = [
        c
        for c in (view.conferences.held.values() if conferences else ())
        if c.tally is None and _nation_of(view) in c.invited
    ]
    if conferences:
        world["conferences"] = [{"key": c.key, "voting_day": str(c.voting_day)} for c in held]
    texts = "".join(
        f"\n\n## The text of conference {c.key}\n{quote_player(c.text.wording)}" for c in held
    )
    to = f"To {person}, by {channel}" if person else "No one named"
    return (
        "## What the seat can see\n"
        + json.dumps(world, separators=(",", ":"), default=str)
        + texts
        + f"\n\n## {to}\n{quote_player(text)}"
    )


def _nation_of(view: View) -> EntityId | None:
    """The seat's own nation, as its view has it."""
    seen: set[EntityId] = set()
    here = view.entities.get(view.me.embodies)
    while here is not None and here.entity_id not in seen:
        if here.kind is EntityKind.POLITY:
            return here.entity_id
        seen.add(here.entity_id)
        here = view.entities.get(here.parent) if here.parent is not None else None
    return None


def _asked(raw: object, written: bool = False) -> list[tuple[Ask, dict[str, str]]]:
    """Asks the reply holds that fit the schema, each with its detail (written orders on
    only); the rest, an unknown effect kind among them, are dropped."""
    out: list[tuple[Ask, dict[str, str]]] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            if written and isinstance(item, dict) and "detail" in item:
                read = _WrittenAsk.model_validate(item)
                extra = {k: str(v) for k, v in read.detail.items()}
                out.append((Ask.model_validate(read.model_dump(exclude={"detail"})), extra))
            else:
                out.append((Ask.model_validate(item), {}))
        except ValidationError:
            continue
    return out[:MAX_ASKS]


def _new_order(ask: Ask) -> bool:
    """Whether the ask is one of the orders written orders add: a contingency, a
    concealment, an intelligence order, an offer of an agreement."""
    e = ask.effect
    return (
        (isinstance(e, SetEngagement) and (e.contingency is not None or e.concealed is not None))
        or (isinstance(e, Investigate | Allocate) and e.intel is not None)
        or (isinstance(e, Deal) and bool(e.parties or e.publish))
    )


def _seen(view: View, clause: AgreementClause) -> bool:
    """Whether every id the clause names is something the seat's view holds."""
    board = view.map
    ids = [clause.binds, clause.nation, clause.area]
    if any(i is not None and i not in view.entities for i in ids):
        return False
    if clause.area is not None and (board is None or clause.area not in set(board.areas())):
        return False
    if clause.region is not None and (
        board is None or clause.region not in {r.key for r in board.regions}
    ):
        return False
    return clause.force is None or clause.force in _forces(view)


def _checked(
    state: State,
    view: View,
    seat: SeatId,
    parties: tuple[EntityId, ...],
    raw: tuple[dict[str, Any], ...],
) -> tuple[tuple[AgreementClause, ...], int]:
    """The proposed clauses that are valid clauses the seat may offer, and how many were
    dropped. A clause is kept only if it fits the clause list, binds a named party, names
    only what the seat's view holds, and is one the filing rules accept."""
    kept: list[AgreementClause] = []
    dropped = 0
    for item in raw[:8]:
        try:
            clause = AgreementClause.model_validate(item)
        except ValidationError:
            dropped += 1
            continue
        if clause.type in _NOT_READ or clause.binds not in parties or not _seen(view, clause):
            dropped += 1
            continue
        alone = Deal(counterparty=parties[-1], parties=parties, clauses=(clause,))
        if agreement.refusal(state, seat, alone):
            dropped += 1
            continue
        kept.append(clause)
    return tuple(kept), dropped + max(0, len(raw) - 8)


def _offer_of(state: State, me: EntityId, deal: Deal) -> agreement.AgreementOffer:
    """The offer as signing shows it: for its terms only; it is never filed."""
    today = state.in_world_date or date.min
    return agreement.AgreementOffer(
        offer_id="proposed",
        version=agreement.version(deal.parties, deal.wording, deal.clauses),
        parties=deal.parties,
        by=polity_of(state, me) or deal.parties[0],
        wording=deal.wording,
        clauses=deal.clauses,
        filed=today,
        expires=today,
    )


def _treaty_reading(
    state: State,
    view: View,
    seat: SeatId,
    text: str,
    parties: tuple[EntityId, ...],
    raw: tuple[dict[str, Any], ...],
    *,
    note: str = "",
    person: str | None = None,
    channel: str | None = None,
) -> Reading:
    """An offer of an agreement from the player's own wording, with the clauses the reader
    proposed that survived the checks. The player signs the terms rendered from those
    clauses, and the reader's own summary is never shown."""
    me = view.me.embodies
    own = polity_of(state, me)
    if len(text) > WORDING_MAX:
        return _unfileable(text, LONG_WORDING, person, channel)
    parties = tuple(dict.fromkeys(p for p in ((own,) if own else ()) + parties))[:MAX_PARTIES]
    others = tuple(p for p in parties if p != own)
    if own is None or not others or any(p not in view.entities for p in parties):
        return _unfileable(text, NO_PARTIES, person, channel)
    why = agreement.refusal(
        state, seat, Deal(counterparty=others[0], parties=parties, wording=text)
    )
    if why:
        return _unfileable(text, why, person, channel)
    clauses, dropped = _checked(state, view, seat, parties, raw)
    deal = Deal(counterparty=others[0], parties=parties, wording=text, clauses=clauses)
    offer = _offer_of(state, me, deal)
    parts = [
        f"{label} ({READING}): {words}" if label.startswith("Clause ") else f"{label}: {words}"
        for label, words in agreement.term_rows(state, offer)
    ]
    parts.append(f"Your wording, which the rules do not check: {text}")
    if dropped:
        parts.append(
            f"Left out, because it did not fit the clauses the rules can check: {dropped}."
        )
    if note:
        parts.append(note)
    ask = Ask(ask=OFFER_ASK, effect=deal)
    shown = OrderProposal(person=person, channel=channel, text=text, parts=parts, reason=None)
    return Reading(
        shown=shown,
        asks=(ask,),
        version=offer.version,
        terms=agreement.render_terms(state, offer),
    )


def _vote_reading(
    state: State,
    seat: SeatId,
    text: str,
    raw: dict[str, Any],
    person: str | None,
    channel: str | None,
) -> Reading:
    """A written vote (CNF), read into the sealed vote the conference's action files.
    Shown with the conference's text and the vote, in fixed words."""
    try:
        ballot = _Ballot.model_validate(raw)
    except ValidationError:
        return _unfileable(text, UNREADABLE, person, channel)
    why = conference.vote_refusal(state, seat, ballot.conference)
    if why:
        return _unfileable(text, why, person, channel)
    held = state.conferences.held[ballot.conference]
    parts = [
        f"Conference: {held.key}",
        f"Text: {held.text.wording}",
        f"Your vote, sealed until the tally: {ballot.vote.value}",
    ]
    shown = OrderProposal(person=person, channel=channel, text=text, parts=parts, reason=None)
    return Reading(shown=shown, asks=(), vote=(ballot.conference, ballot.vote))


def _fallback_parties(state: State, me: EntityId, who: EntityId | None) -> tuple[EntityId, ...]:
    """The nation of the person written to, when it is not the seat's own."""
    other = polity_of(state, who) if who is not None else None
    return (other,) if other is not None and other != polity_of(state, me) else ()


Twin = tuple[str, dict[str, str]]
"""A form of the seat's own and its parameters as the form takes them."""

RULE_LEVEL = {Engagement.HOLD_FIRE: 0, Engagement.ESCORT: 1, Engagement.SHOOT_ON_SIGHT: 2}
"""[proposed] The escort level an engagement's rule stands for, as a naval order's choice
marks it (ESC): holding fire is no escort."""


def _choice(state: State, spec: ParamSpec | None, kind: str, value: str | None) -> str | None:
    """The choice of ``spec`` whose world key compiles to ``value``."""
    if spec is None or value is None:
        return None
    return next((c for c in spec.choices if object_id(state.campaign_id, kind, c) == value), None)


def _moved(state: State, lever: Lever, effect: Effect) -> dict[str, str] | None:
    """A movement form's force and destination: a move with no posture."""
    if not isinstance(effect, MoveForce) or effect.to is None or effect.posture is not None:
        return None
    params = {p.name: p for p in lever.params}
    force = _choice(state, params.get(FORCE), "feature", effect.force)
    to = _choice(state, params.get(TO), "entity", effect.to)
    return None if force is None or to is None else {FORCE: force, TO: to}


def _intel(state: State, seat: SeatId, lever: Lever, effect: Effect) -> dict[str, str] | None:
    """An intelligence form's parameters, for the order its effect stands for: the effect
    ``intel.effect_of`` gives, and for a concealment, whichever rule it names."""
    form = intel.form_of(lever)
    params = {p.name: p for p in lever.params}
    piece, area = params.get(intel.PIECE), params.get(intel.AREA)
    found: dict[str, str | None] | None = None
    if form is intel.Form.RECON and isinstance(effect, Investigate):
        if effect.intel is IntelOrder.RECON:
            found = {
                intel.PIECE: _choice(state, piece, "feature", effect.flier),
                intel.AREA: _choice(state, area, "entity", effect.target),
            }
    elif form is intel.Form.AGENT and isinstance(effect, Investigate):
        if effect.intel is IntelOrder.AGENT:
            found = {intel.AREA: _choice(state, area, "entity", effect.target)}
    elif form is intel.Form.PATROL and isinstance(effect, MoveForce):
        if effect.posture is Posture.PATROL and effect.to is None:
            found = {intel.PIECE: _choice(state, piece, "feature", effect.force)}
    elif form is intel.Form.CODEBREAKING and isinstance(effect, Allocate):
        own = polity_of(state, state.seats[seat].embodies)
        if effect.intel is IntelOrder.CODEBREAKING and effect.recipient == own:
            found = {}
    elif form is intel.Form.CONCEAL and isinstance(effect, SetEngagement):
        if effect.concealed is not None and effect.contingency is None:
            shown = intel.YES if effect.concealed else "no"
            hidden = params.get(intel.CONCEALED)
            found = {
                intel.PIECE: _choice(state, piece, "feature", effect.force),
                intel.CONCEALED: shown if hidden is not None and shown in hidden.choices else None,
            }
    if form is None or found is None or any(v is None for v in found.values()):
        return None
    return {intel.INTEL: form.value} | {k: v for k, v in found.items() if v is not None}


def _escort(state: State, lever: Lever, effect: Effect) -> dict[str, str] | None:
    """A naval order's escort value and waters: an engagement in a zone, its rule read as
    the escort level the world marks on the choice."""
    if not isinstance(effect, SetEngagement) or len(lever.params) != 2:
        return None
    if effect.concealed is not None or effect.contingency is not None:
        return None
    levels = lever.escort_levels or ESCORT_LEVEL
    order = next((p for p in lever.params if p.choices and set(p.choices) <= set(levels)), None)
    waters = next((p for p in lever.params if p is not order), None)
    want = RULE_LEVEL.get(effect.rule)
    if order is None or waters is None or want is None:
        return None
    zone = zone_of(state, effect.zone)
    where = next(
        (
            c
            for c in waters.choices
            if c == effect.zone or object_id(state.campaign_id, "entity", c) == zone
        ),
        None,
    )
    chosen = next((c for c in order.choices if levels.get(c) == want), None)
    return None if where is None or chosen is None else {order.name: chosen, waters.name: where}


def _aid(state: State, lever: Lever, effect: Effect) -> dict[str, str] | None:
    """An aid finding's recipient and share: an allocation, in per cent, of what the
    finding's receipt names."""
    keys = state.map.production if state.map is not None else None
    if keys is None or not any(f.form == lever.name for f in keys.findings):
        return None
    if not isinstance(effect, Allocate) or effect.intel is not None or effect.unit != "percent":
        return None
    if effect.what != _matter(state, lever.name):
        return None
    out: dict[str, str] = {}
    for spec in lever.params:
        if (c := _choice(state, spec, "entity", effect.recipient)) is not None:
            out[spec.name] = c
        elif spec.kind is ParamKind.INT and spec.lo is not None and spec.hi is not None:
            if spec.lo <= effect.amount <= spec.hi:
                out[spec.name] = str(effect.amount)
    return out if len(out) == 2 else None


def _filled(state: State, seat: SeatId, lever: Lever, effect: Effect) -> dict[str, str] | None:
    """The parameters of ``lever`` the effect names, when its form gives that effect."""
    if lever.resolver == "movement":
        return _moved(state, lever, effect)
    if lever.resolver == "intel":
        return _intel(state, seat, lever, effect)
    if lever.resolver == "shipping":
        return _escort(state, lever, effect)
    if lever.resolver == "production":
        return _aid(state, lever, effect)
    return None


def twin(state: State, seat: SeatId, ask: Ask, detail: dict[str, str]) -> Twin | None:
    """The one form on the seat's card that gives the ask's effect, with every parameter
    filled: from the effect, and from ``detail`` for what the effect cannot hold. A detail
    never names what the effect fills. None when no form, or more than one, fits."""
    card = state.cards.get(state.seats[seat].embodies)
    if card is None or ask.effect is None:
        return None
    found: list[Twin] = []
    for lever in card.levers:
        filled = _filled(state, seat, lever, ask.effect)
        if filled is None or set(filled) & set(detail):
            continue
        given = filled | detail
        if set(given) == {p.name for p in lever.params}:
            found.append((lever.name, given))
    return found[0] if len(found) == 1 else None


def _war_reading(
    state: State, seat: SeatId, text: str, raw: object, person: str | None, channel: str | None
) -> Reading:
    """A written declaration of war, read into the seat's own form that declares it on
    that nation; refused when the card has none."""
    try:
        war = _War.model_validate(raw)
    except ValidationError:
        return _unfileable(text, UNREADABLE, person, channel)
    nation = state.entities.get(war.target)
    card = state.cards.get(state.seats[seat].embodies)
    for lever in card.levers if card is not None and nation is not None else ():
        params = [p for p in lever.params if p.kind is ParamKind.ENUM]
        target = [(p.name, c) for p in params if (c := _choice(state, p, "entity", war.target))]
        if lever.resolver == "war" and len(target) == 1 and len(lever.params) == 1:
            assert nation is not None
            ask = Ask(ask=f"Declare war on {nation.name}.", target=war.target)
            shown = OrderProposal(
                person=person, channel=channel, text=text, parts=[ask.ask], reason=None
            )
            return Reading(shown=shown, asks=(ask,), forms=((lever.name, dict(target)),))
    return _unfileable(text, TO_THE_FORM, person, channel)


def read_order(
    state: State, seat: SeatId, to: str, channel: str, text: str, transport: Transport
) -> Reading:
    """Read ``text`` from the seat's view. ``to`` and ``channel`` are as posted and may
    be empty. A failed model call raises ``TransportError``."""
    text = text.strip()
    if not text or len(text) > MAX_TEXT:
        return _unfileable(text, f"Write an order of 1 to {MAX_TEXT} characters.")
    view = project(state, seat)
    today = view.in_world_date
    if today is None:
        return _unfileable(text, NOTHING)
    me = view.me.embodies
    reach = _reachable(state, me, view)
    who = _addressee(reach, to.strip(), text)
    if to.strip() and who is None:
        return _unfileable(text, UNREACHED)
    name = reach[who] if who is not None else None
    written = Rule.WRITTEN_ORDERS in state.rules
    reads_clauses = Rule.CLAUSE_READER in state.rules
    votes = written and conference.on(state)
    schema = VOTE_SCHEMA if votes else TREATY_SCHEMA if written else ORDERS_SCHEMA
    system = prompt_text(PROMPT) + (TREATY_PROMPT if written else "")
    system += VOTE_PROMPT if votes else ""
    if who is None and not (written and agreement.on(state)):
        return _unfileable(text, "Name who should act on it.")
    how: ChannelKind | None = None
    if who is not None:
        open_to = channels_to(state, me, who)
        try:
            how = ChannelKind(channel) if channel else open_to[0]
        except ValueError:
            return _unfileable(text, "Choose how the order is to travel.", name)
        if how not in open_to:
            return _unfileable(text, f"You cannot reach {name} that way.", name)
    said = words(how.value) if how is not None else None

    reply = transport.call(
        Request(
            call_class=CALL_CLASS,
            model=AIDE_MODEL,
            system=system,
            prompt=orders_prompt(
                view,
                name or "",
                (said or "").lower(),
                text,
                clauses=reads_clauses,
                conferences=votes,
                forms=written,
            ),
            schema=cli_schema(schema),
            player_text=True,
        )
    )
    out = reply.output if isinstance(reply.output, dict) else {}
    if votes and isinstance(out.get("vote"), dict):
        return _vote_reading(state, seat, text, out["vote"], name, said)
    if written and out.get("war") is not None and not out.get("asks"):
        return _war_reading(state, seat, text, out["war"], name, said)
    found = out.get("treaty")
    if isinstance(found, dict) and found.get("parties"):
        if not written:
            return _unfileable(text, TO_THE_FORM, name, said)
        try:
            treaty = _Treaty.model_validate(
                {k: v for k, v in found.items() if k in _Treaty.model_fields}
            )
        except ValidationError:
            return _treaty_reading(
                state,
                view,
                seat,
                text,
                _fallback_parties(state, me, who),
                (),
                note=NO_CLAUSES,
                person=name,
                channel=said,
            )
        if len(_asked(out.get("asks"))) > 0:
            return _unfileable(text, agreement.ALONE, name, said)
        return _treaty_reading(
            state,
            view,
            seat,
            text,
            treaty.parties,
            treaty.clauses if reads_clauses else (),
            person=name,
            channel=said,
        )
    if who is None:
        return _unfileable(text, "Name who should act on it.")
    read = _asked(out.get("asks"), written)
    asks = [
        a if a.effect is not None or a.target is not None else a.model_copy(update={"target": who})
        for a, _ in read
    ]
    if not asks:
        return _unfileable(text, UNREADABLE, name, said)
    if not written and any(_new_order(a) for a in asks):
        return _unfileable(text, TO_THE_FORM, name, said)
    check = Option(label="order", asks=tuple(asks), to=who)
    details = json.dumps([d for _, d in read])
    if not _named_ok(view, check) or scan_text(state, seat, check.model_dump_json() + details):
        return _unfileable(text, UNREADABLE, name, said)

    parts: list[str] = []
    routed_asks: list[bool] = []
    for ask in asks:
        routed = route(state, seat, ask, today)
        part = routed.part
        routed_asks.append(part is not None)
        if part is None and held(state, seat, ask, today) is not None:
            parts.append(ask.ask.replace("_", " "))
            continue
        if part is None:
            return _unfileable(text, routed.refusal or UNREADABLE, name, said)
        if part.route is Route.INFLUENCE and (
            part.target is None or not channels_to(state, me, part.target)
        ):
            return _unfileable(text, UNREACHED, name, said)
        parts.append(ask.ask.replace("_", " "))
    forms = tuple(
        twin(state, seat, ask, detail) if ok else None
        for ask, (_, detail), ok in zip(asks, read, routed_asks, strict=True)
    )
    if any(f is None and detail for f, (_, detail) in zip(forms, read, strict=True)):
        return _unfileable(text, TO_THE_FORM, name, said)
    shown = OrderProposal(person=name, channel=said, text=text, parts=parts, reason=None)
    return Reading(shown=shown, asks=tuple(asks), forms=forms if any(forms) else ())


def file_order(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, reading: Reading | None
) -> Reply:
    """File a signed reading; a refusal when ``reading`` is None or empty, or when a
    part has no route."""
    if reading is not None and reading.vote is not None:
        from revisionist.engine import wake

        try:
            wake.seal_vote(store, campaign_id, seat, *reading.vote)
        except ValueError as exc:
            return Reply(reply=str(exc), refused=True)
        return Reply(reply="Your vote is sealed.", refused=False)
    if reading is None or not reading.asks:
        return Reply(reply=NOTHING, refused=True)
    if reading.version:
        state = load_state(store, campaign_id)
        deal = reading.asks[0].effect
        view = project(state, seat)
        if not isinstance(deal, Deal):
            return Reply(reply=CHANGED, refused=True)
        again = _checked(
            state, view, seat, deal.parties, tuple(c.model_dump(mode="json") for c in deal.clauses)
        )
        offer = _offer_of(state, view.me.embodies, deal)
        if (
            again != (deal.clauses, 0)
            or offer.version != reading.version
            or agreement.render_terms(state, offer) != reading.terms
        ):
            return Reply(reply=CHANGED, refused=True)
    try:
        if reading.forms:
            reason = file_written(store, campaign_id, seat, reading.asks, reading.forms)
        else:
            filed = commit_order(store, campaign_id, seat, reading.asks)
            reason = filed.reason if isinstance(filed, HeldOrder) else None
    except ValueError as exc:
        return Reply(reply=str(exc), refused=True)
    if reason is not None:
        return Reply(reply=reason, refused=False)
    who = reading.shown["person"]
    return Reply(reply=f"Sent to {who}." if who else "Your order is filed.", refused=False)


def file_written(
    store: EventStore,
    campaign_id: CampaignId,
    seat: SeatId,
    asks: Sequence[Ask],
    forms: Sequence[Twin | None],
) -> str | None:
    """File a signed written order: each ask a form of the seat's gives as that form, by
    every check the form takes and on the day it would land; the rest as one routed order.
    The reason a lock gave the seat, or None. Raises ``ValueError``, logging nothing."""
    state = load_state(store, campaign_id)
    landing: realism_tick.Landing = []
    rest: list[Ask] = []
    for ask, form in zip_longest(asks, forms[: len(asks)]):
        if form is None:
            rest.append(ask)
            continue
        order = realism_tick.draft_order(state, seat, form[0], dict(form[1]))
        landing += realism_tick.form_filing(state, seat, order)[0]
    if rest:
        landing += realism_tick.written_filing(state, seat, rest)[0]
    realism_tick._append_all(store, state, landing, seat)
    reasons = [p.held.reason for p, _ in landing if isinstance(p, ev.OrderHeld)]
    return reasons[0] if reasons else None


__all__ = ["Reading", "file_order", "file_written", "orders_prompt", "read_order", "twin"]
