"""Free text read into engine-v2 asks (Phase 4 unit D): a cheap model proposes, the
player signs, and the order is routed and filed with ``realism_tick.commit_order``.

The model sees only the seat's own ``View``. Its asks are kept server-side; the
client is sent the proposal in words.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from revisionist.core._base import Model
from revisionist.core.canary import scan_text
from revisionist.core.ids import CampaignId, EntityId, SeatId
from revisionist.core.ontology import EntityKind
from revisionist.core.project import project
from revisionist.core.realism.agenda import Ask, Option
from revisionist.core.realism.card import ChannelKind, words
from revisionist.core.realism.effect import Route
from revisionist.core.realism.reach import channels_to
from revisionist.core.realism.route import route
from revisionist.core.state import State, View
from revisionist.engine.aide import AIDE_MODEL
from revisionist.engine.directive import TEXT_MAX
from revisionist.engine.llm import Request, Transport, cli_schema, prompt_text
from revisionist.engine.options import _forces, _named_ok
from revisionist.engine.realism_tick import commit_order
from revisionist.engine.store import EventStore
from revisionist.engine.web.realism_api import OrderProposal, Reply

CALL_CLASS = "aide"
PROMPT = "orders"

MAX_ASKS = 8  # [proposed] parts one order may carry; the Option cap
MAX_TEXT = TEXT_MAX  # [proposed] characters of order text, as a directive
UNREADABLE = "Your aide could not make that into an order you can sign."
NOTHING = "There is nothing to sign. Write your order again."
UNREACHED = "That person is not within your reach."


@dataclass(frozen=True)
class Reading:
    """A proposal and what signing it files. The server holds it between ``order``
    and ``file``: asks carry ids, and the client is sent words."""

    shown: OrderProposal
    asks: tuple[Ask, ...]
    """Empty: it cannot be filed, and ``shown`` says why."""


class _Reply(Model):
    asks: tuple[Ask, ...]
    reason: str = ""


ORDERS_SCHEMA: dict[str, Any] = _Reply.model_json_schema()


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


def orders_prompt(view: View, person: str, channel: str, text: str) -> str:
    """The seat's own view, compact: desk, date, the objects it may name, then the words."""
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
    to = f"To {person}, by {channel}" if person else "No one named"
    return (
        "## What the seat can see\n"
        + json.dumps(world, separators=(",", ":"), default=str)
        + f"\n\n## {to}\n{text}"
    )


def _asked(raw: object) -> list[Ask]:
    """Asks the reply holds that fit the schema; the rest, an unknown effect kind among
    them, are dropped."""
    out: list[Ask] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append(Ask.model_validate(item))
        except ValidationError:
            continue
    return out[:MAX_ASKS]


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
    if who is None:
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
            system=prompt_text(PROMPT),
            prompt=orders_prompt(view, name or "", (said or "").lower(), text),
            schema=cli_schema(ORDERS_SCHEMA),
        )
    )
    out = reply.output if isinstance(reply.output, dict) else {}
    asks = [
        a if a.effect is not None or a.target is not None else a.model_copy(update={"target": who})
        for a in _asked(out.get("asks"))
    ]
    if not asks:
        return _unfileable(text, UNREADABLE, name, said)
    check = Option(label="order", asks=tuple(asks), to=who)
    if not _named_ok(view, check) or scan_text(state, seat, check.model_dump_json()):
        return _unfileable(text, UNREADABLE, name, said)

    parts: list[str] = []
    for ask in asks:
        routed = route(state, seat, ask, today)
        part = routed.part
        if part is None:
            return _unfileable(text, routed.refusal or UNREADABLE, name, said)
        if part.route is Route.INFLUENCE and (
            part.target is None or not channels_to(state, me, part.target)
        ):
            return _unfileable(text, UNREACHED, name, said)
        parts.append(ask.ask.replace("_", " "))
    shown = OrderProposal(person=name, channel=said, text=text, parts=parts, reason=None)
    return Reading(shown=shown, asks=tuple(asks))


def file_order(
    store: EventStore, campaign_id: CampaignId, seat: SeatId, reading: Reading | None
) -> Reply:
    """File a signed reading; a refusal when ``reading`` is None or empty, or when a
    part has no route."""
    if reading is None or not reading.asks:
        return Reply(reply=NOTHING, refused=True)
    try:
        commit_order(store, campaign_id, seat, reading.asks)
    except ValueError as exc:
        return Reply(reply=str(exc), refused=True)
    who = reading.shown["person"]
    return Reply(reply=f"Sent to {who}." if who else "Your order is filed.", refused=False)


__all__ = ["Reading", "file_order", "orders_prompt", "read_order"]
