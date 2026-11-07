"""Options and play styles (engine v2, spec §8.6).

A guided or beginner seat is offered ordinary orders for its agenda; an aide
drafts asks for an absent seat. An option is a tuple of ``Ask`` that
``realism_tick.commit_order`` accepts: picking one files what a free player could
have typed. The generator reads only the seat's projected ``View``.
"""

import json
from collections.abc import Iterable
from datetime import date
from typing import Any

from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core._base import Model
from revisionist.core.canary import scan_text
from revisionist.core.events import CallCost
from revisionist.core.ids import CampaignId, EntityId, FeatureId, SeatId
from revisionist.core.ontology import Controller, ScheduleSource
from revisionist.core.project import project
from revisionist.core.realism.agenda import (
    Ask,
    Mandate,
    MandateStatus,
    Offer,
    Option,
    PlayStyle,
)
from revisionist.core.realism.effect import (
    IRREVERSIBLE,
    Effect,
    EffectKind,
    Engagement,
    MakeStatement,
    MoveForce,
    Posture,
    SetEngagement,
)
from revisionist.core.realism.route import route
from revisionist.core.state import State, View
from revisionist.core.visibility import private_to
from revisionist.engine.llm import Request, Transport, TransportError, cli_schema, prompt_text
from revisionist.engine.realism_tick import _append
from revisionist.engine.store import EventStore, load_state

OPTIONS_MODEL = "claude-haiku-5-5"
"""[proposed] The option generator's model."""
CALL_CLASS = "options"
"""``Request.call_class`` and ``CallCost.call_class`` for every options call."""
PROMPT = "options"
"""The system prompt: ``engine/prompts/options.md``."""
RECORDING = "realism-options-slice.json"
"""Recorded replies under ``tests/recordings/``, keyed by ``Request.key()``."""

MAX_OFFERS = 4
"""The event's cap: live mandates take the first slots, initiative the last."""
AIDE_ORDERS = 3  # [proposed] orders the aide files for an absent seat in one wake
STATION = "its station"  # [proposed] zone label for a template engagement ask
BEGINNER_MIN, BEGINNER_MAX = 3, 4
GUIDED_MIN, GUIDED_MAX = 3, 5

last_cost: CallCost | None = None
"""Summed cost of the model calls the latest ``offer`` or ``aide_asks`` made; None if none."""


class _Reply(Model):
    options: tuple[Option, ...]


OPTIONS_SCHEMA: dict[str, Any] = _Reply.model_json_schema()

_NAMED = ("to", "of", "toward", "person", "recipient", "audience", "target", "counterparty")


def set_style(
    store: EventStore,
    campaign_id: CampaignId,
    seat: SeatId,
    style: PlayStyle,
    standing: frozenset[EffectKind] = frozenset(),
) -> None:
    """Set ``seat``'s play style and standing orders, sealed to the seat."""
    if not standing <= IRREVERSIBLE:
        raise ValueError("a standing order names only irreversible kinds")
    state = load_state(store, campaign_id)
    payload = ev.PlayStyleSet(seat_id=seat, style=style, standing=standing)
    _append(store, state, payload, seat, private_to(seat))


# --- the prompt -------------------------------------------------------------------


def _forces(view: View) -> dict[FeatureId, str]:
    """The forces a seat's desk commands. A view holds no features, so a force is
    named by the domain that commands it."""
    found: dict[FeatureId, str] = {}
    if view.desk is not None:
        for domain in view.desk.authority:
            for fid in domain.forces:
                found.setdefault(fid, domain.name.replace("_", " "))
    return found


def _history(view: View) -> list[dict[str, str]]:
    return [
        {"name": s.name, "on": str(s.on_date)}
        for s in view.scheduled.values()
        if s.source is ScheduleSource.HISTORY and not s.fired and s.on_date is not None
    ]


def options_prompt(view: View, mandate: Mandate | None, style: PlayStyle) -> str:
    """The seat's own view, compact: desk, mandate, date, the objects it may name."""
    desk = view.desk
    names = {e.entity_id: e.name for e in view.entities.values()}
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
            "inner_circle": [
                {"person": c.person, "name": names.get(c.person), "channel": c.channel.value}
                for c in desk.inner_circle
            ],
            "reach": desk.reach.model_dump(mode="json"),
        }
    world = {
        "date": str(view.in_world_date),
        "style": style.value,
        "seat": seat,
        "mandate": None
        if mandate is None
        else {"text": mandate.text, "expires": str(mandate.expires), "issuer": mandate.issuer},
        "history_schedule": _history(view),
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
    wanted = "3 or 4 options" if style is PlayStyle.BEGINNER else "one plan of 3 to 5 asks"
    return (
        "## What the seat can see\n"
        + json.dumps(world, separators=(",", ":"), default=str)
        + f"\n\nReturn {wanted}. Echo ids exactly."
    )


# --- the offline fallback ----------------------------------------------------------


def _candidates(view: View, mandate: Mandate | None) -> list[Option]:
    """Every option the desk suggests, in a fixed order; not yet checked for a route."""
    out: list[Option] = []
    desk = view.desk
    if desk is None:
        return out
    names = {e.entity_id: e.name for e in view.entities.values()}
    for domain in desk.authority:
        label = domain.name.replace("_", " ")
        for fid in domain.forces:
            go = domain.executor
            out.append(
                Option(
                    label=f"Order the {label} forces to patrol",
                    asks=(
                        Ask(
                            ask=f"Put the {_forces(view)[fid]} forces on patrol",
                            effect=MoveForce(force=fid, posture=Posture.PATROL),
                        ),
                    ),
                    to=go,
                    risk="A show of readiness that may be read as a step toward war.",
                )
            )
            out.append(
                Option(
                    label=f"Set the {label} forces to defend",
                    asks=(
                        Ask(
                            ask=f"Have the {_forces(view)[fid]} forces defend themselves",
                            effect=SetEngagement(force=fid, zone=STATION, rule=Engagement.DEFEND),
                        ),
                    ),
                    to=go,
                    risk="If it is attacked the fight is yours, and the order cannot be recalled.",
                )
            )
    if any(EffectKind.STATEMENT in d.effects for d in desk.authority):
        out.append(
            Option(
                label="Make a public statement",
                asks=(
                    Ask(
                        ask="State our position plainly", effect=MakeStatement(theme="our position")
                    ),
                ),
                risk="Words are held against you later, and rivals answer them.",
            )
        )
    aimed: list[EntityId] = []
    if mandate is not None and mandate.issuer is not None:
        aimed.append(mandate.issuer)
    aimed += [c.person for c in desk.inner_circle]
    aimed += list(desk.principals)
    for who in dict.fromkeys(aimed):
        if who in names and who != view.me.embodies:
            out.append(
                Option(
                    label=f"Press {names[who]} for support",
                    asks=(Ask(ask=f"Ask {names[who]} to back our course", target=who),),
                    to=who,
                    risk="They may refuse, and they will remember being asked.",
                )
            )
    return out


def _pick(options: list[Option], style: PlayStyle) -> tuple[Option, ...]:
    if style is PlayStyle.BEGINNER:
        return tuple(options[:BEGINNER_MAX]) if len(options) >= BEGINNER_MIN else ()
    asks = tuple(a for o in options for a in o.asks)[:GUIDED_MAX]
    if style is PlayStyle.GUIDED and len(asks) >= GUIDED_MIN:
        return (Option(label="A plan in several steps", asks=asks, risk=options[0].risk),)
    return ()


def template_options(view: View, mandate: Mandate | None, style: PlayStyle) -> tuple[Option, ...]:
    """No model: options built from the desk, in a fixed order. Empty when the desk
    offers too few asks for the style."""
    return _pick(_candidates(view, mandate), style)


# --- validation -------------------------------------------------------------------


def _objects(effect: Effect | None) -> list[str]:
    if effect is None:
        return []
    return [v for f in (*_NAMED, "force", "fact") if isinstance(v := getattr(effect, f, None), str)]


def _named_ok(view: View, option: Option) -> bool:
    """Every id the option names is something the view holds."""
    forces, facts = _forces(view), view.facts
    ids = [option.to, *(a.target for a in option.asks)]
    for ask in option.asks:
        effect = ask.effect
        force = getattr(effect, "force", None)
        if force is not None and force not in forces:
            return False
        fact = getattr(effect, "fact", None)
        if fact is not None and fact not in facts:
            return False
        ids += [getattr(effect, f, None) for f in _NAMED]
    return all(i is None or i in view.entities for i in ids)


def _routes(state: State, seat: SeatId, option: Option, today: date) -> bool:
    return all(route(state, seat, a, today).part is not None for a in option.asks)


def _clean(state: State, seat: SeatId, view: View, options: Iterable[Option]) -> list[Option]:
    today = view.in_world_date
    if today is None:
        return []
    kept: list[Option] = []
    for option in options:
        if not _named_ok(view, option) or not _routes(state, seat, option, today):
            continue
        if scan_text(state, seat, option.model_dump_json()):
            continue
        kept.append(option)
    return kept


def _history_marked(view: View, options: list[Option]) -> list[Option]:
    """At most one option claims to be what history did, and only if the view's own
    schedule names a history event."""
    allowed = bool(_history(view))
    seen = False
    out: list[Option] = []
    for o in options:
        if o.historical and not (allowed and not seen):
            o = o.model_copy(update={"historical": False})
        seen = seen or o.historical
        out.append(o)
    return out


def _ask_model(
    state: State, view: View, mandate: Mandate | None, style: PlayStyle, transport: Transport
) -> list[Option]:
    global last_cost
    request = Request(
        call_class=CALL_CLASS,
        model=OPTIONS_MODEL,
        system=prompt_text(PROMPT),
        prompt=options_prompt(view, mandate, style),
        schema=cli_schema(OPTIONS_SCHEMA),
    )
    try:
        reply = transport.call(request)
    except TransportError:
        return []
    cost = reply.cost(CALL_CLASS)
    last_cost = (
        cost
        if last_cost is None
        else last_cost.model_copy(
            update={
                "input_tokens": last_cost.input_tokens + cost.input_tokens,
                "output_tokens": last_cost.output_tokens + cost.output_tokens,
                "cached_tokens": last_cost.cached_tokens + cost.cached_tokens,
                "usd": last_cost.usd + cost.usd,
            }
        )
    )
    raw = reply.output.get("options") if isinstance(reply.output, dict) else None
    parsed: list[Option] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            parsed.append(Option.model_validate(item))
        except ValidationError:
            continue
    return _history_marked(view, _clean(state, view.viewer, view, parsed))


def _options_for(
    state: State, view: View, mandate: Mandate | None, style: PlayStyle, transport: Transport | None
) -> tuple[Option, ...]:
    """Model options when a transport is given and enough survive; else the template."""
    if transport is not None:
        got = _pick_valid(_ask_model(state, view, mandate, style, transport), style)
        if got:
            return got
    pool = _clean(state, view.viewer, view, _candidates(view, mandate))
    return _pick(pool, style)


def _pick_valid(options: list[Option], style: PlayStyle) -> tuple[Option, ...]:
    if style is PlayStyle.BEGINNER:
        return tuple(options[:BEGINNER_MAX]) if len(options) >= BEGINNER_MIN else ()
    for o in options:
        if GUIDED_MIN <= len(o.asks) <= GUIDED_MAX:
            return (o,)
    return ()


# --- what the seat and its aide are given -----------------------------------------


def _live(view: View) -> list[Mandate]:
    mine = [m for m in view.mandates.values() if m.status is MandateStatus.LIVE]
    return sorted(mine, key=lambda m: (m.expires, m.mandate_id))


def offer(state: State, seat: SeatId, transport: Transport | None) -> ev.OptionsOffered | None:
    """What ``seat`` is offered this wake, or None for a free or AI seat."""
    global last_cost
    last_cost = None
    held = state.seats.get(seat)
    style = state.styles.get(seat)
    if held is None or held.controller is Controller.AI or style in (None, PlayStyle.FREE):
        return None
    assert style is not None
    view = project(state, seat)
    asked: list[Mandate | None] = [*_live(view)[: MAX_OFFERS - 1], None]
    offers: list[Offer] = []
    for mandate in asked:
        options = _options_for(state, view, mandate, style, transport)
        if options:
            offers.append(
                Offer(
                    mandate_id=mandate.mandate_id if mandate is not None else None,
                    style=style,
                    options=options,
                )
            )
    if not offers:
        return None
    return ev.OptionsOffered(
        seat_id=seat, wake=state.wake.number if state.wake is not None else 0, offers=tuple(offers)
    )


def aide_asks(state: State, seat: SeatId, transport: Transport | None) -> list[tuple[Ask, ...]]:
    """The orders an aide files for an absent seat, one per live mandate: its first
    beginner option, less any irreversible ask the seat has not put in a standing order."""
    global last_cost
    last_cost = None
    if seat not in state.seats:
        return []
    view = project(state, seat)
    allowed = state.standing.get(seat, frozenset())
    orders: list[tuple[Ask, ...]] = []
    for mandate in _live(view):
        options = _options_for(state, view, mandate, PlayStyle.BEGINNER, transport)
        if not options:
            continue
        asks = tuple(
            a
            for a in options[0].asks
            if a.effect is None
            or EffectKind(a.effect.kind) not in IRREVERSIBLE
            or EffectKind(a.effect.kind) in allowed
        )
        if asks:
            orders.append(asks)
        if len(orders) == AIDE_ORDERS:
            break
    return orders


__all__ = [
    "CALL_CLASS",
    "OPTIONS_MODEL",
    "OPTIONS_SCHEMA",
    "PROMPT",
    "RECORDING",
    "aide_asks",
    "last_cost",
    "offer",
    "options_prompt",
    "set_style",
    "template_options",
]
