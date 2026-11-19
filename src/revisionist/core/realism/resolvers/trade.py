"""Embargo and trade orders (EMB), under the rule name ``trade``.

With ``fuel`` on, an enacted form that names a trade ``line`` cuts it (an embargo) or,
when its ``action`` is ``restore``, reopens it. Only the nation the line runs from (its
``exporter``) may do either: an order by any other nation, the one at the far end
included, moves nothing, and the issuing seat gets a report saying why.

The order lands on the day after it left its last step, through ``trade.set``: one
``trade_set``, one public news item naming the two nations and what the line carries
(never its amount), and one paper to the seats of the nation at the other end (the
importer). The paper is built from the order and the line alone, so it reads the same
whether that nation's player is present or away. Lines pay only on the first of a month
(``economy.walk``, after the day rules), so a line cut on any day pays nothing from the
next first of the month, and the month already paid stays paid: an order that settles on
a first lands on the second.

An order that would change nothing (a cut line embargoed, an open line restored) lands
nothing but the report to its issuer. The orders landing on one day are taken by settling
day, then by terms, then by id, each seeing the lines the ones before it left. No line,
nation or resource is named here; any world's card may carry the form.
"""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId, SeatId, derived_id
from revisionist.core.realism import actors
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism import trade as lines
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.trade import TradeLine
from revisionist.core.realism.war import NewsEvent, NewsTopic, polity_of
from revisionist.core.state import State
from revisionist.core.visibility import Scope, Visibility, private_to

LINE, ACTION, RESTORE = "line", "action", "restore"
TEXT = 60
"""The longest a headline or a title may be."""
NOT_YOURS = "Only the nation a line runs from can cut or reopen it"  # [proposed]
"""The same words for a line that is not the issuer's and one that does not exist, so the
report tells a nation nothing of a line it is not a party to."""


def _clip(text: str) -> str:
    return text if len(text) <= TEXT else text[: TEXT - 1] + "\N{HORIZONTAL ELLIPSIS}"


def resolve(state: State, order: Order) -> tuple["rs.Change", ...]:
    """The order changes nothing when it is enacted: it lands on the next day."""
    return ()


def cuts(order: Order) -> bool:
    """Whether the order cuts its line (an embargo): any action but ``restore`` does."""
    return str(order.params.get(ACTION, "")) != RESTORE


def _key(order: Order) -> tuple[date, list[tuple[str, str]], str]:
    terms = sorted((k, repr(v)) for k, v in order.params.items())
    return rs.settled_on(order), terms, str(order.order_id)


def due(state: State, today: date) -> list[Order]:
    """The enacted ``trade`` orders that land ``today``: those that left their last step
    the day before, in settling order."""
    found = []
    for o in state.orders.values():
        if o.status is not OrderStatus.ENACTED or LINE not in o.params:
            continue
        if rs.settled_on(o) + timedelta(days=1) != today:
            continue
        try:
            if rs.resolver_for(state, o) != "trade":
                continue
        except KeyError:
            continue
        found.append(o)
    return sorted(found, key=_key)


def _name(state: State, entity: EntityId) -> str:
    found = state.entities.get(entity)
    return entity if found is None else found.name


def _carries(state: State, line: TradeLine) -> str:
    found = None if state.kinds is None else state.kinds.resources.get(line.resource)
    return line.resource if found is None else found.name


def refusal(state: State, order: Order, nation: EntityId | None) -> str | None:
    """Why the order moves nothing; None when it cuts or reopens its line."""
    if not lines.on(state):
        return "The fuel rule is off"
    line = state.economy.lines.get(str(order.params[LINE]))
    if line is None or nation is None or nation != line.exporter:
        return NOT_YOURS
    if line.cut == cuts(order):
        return "The line is already cut" if line.cut else "The line is already open"
    return None


def _seats(state: State, nation: EntityId) -> frozenset[SeatId]:
    """The seats with a desk whose person belongs to ``nation``."""
    return frozenset(
        s for s in actors.readers(state) if polity_of(state, state.seats[s].embodies) == nation
    )


def _doc(
    state: State, order: Order, part: str, author: EntityId, today: date, scope: Scope
) -> tuple[DocumentId, DocumentView]:
    doc_id = DocumentId(derived_id(state.campaign_id, "trade", part, order.order_id))
    return doc_id, DocumentView(
        doc_id=doc_id,
        kind=DocumentKind.CABLE,
        author=author,
        issued=today,
        arrives=today,
        channel=ChannelKind.CABLE,
        classification=Classification.CONFIDENTIAL,  # [proposed]
        title="",
        scope=scope,
    )


def _report(
    state: State, order: Order, nation: EntityId | None, why: str, today: date
) -> list["rs.Change"]:
    """The report to the issuing seat that its order moved nothing; none for a seat with
    no desk or no nation."""
    if order.issuer not in actors.readers(state) or nation is None:
        return []
    doc_id, view = _doc(state, order, "refused", nation, today, private_to(order.issuer))
    view = view.model_copy(
        update={
            "kind": DocumentKind.REPORT,
            "title": _clip("Trade order not carried out"),
            "body": (
                BodyField(label="Line", value=str(order.params[LINE])),
                BodyField(label="Why", value=_clip(why)),
            ),
        }
    )
    return [ev.DocumentIssued(document=view, truth=DocumentTruth(doc_id=doc_id))]


def _first_paid(today: date) -> date:
    """The first payment a line landed ``today`` changes: today's on a first (lines are
    paid after the day rules), else the next first of the month."""
    if today.day == 1:
        return today
    return (today.replace(day=1) + timedelta(days=32)).replace(day=1)


def _landed(state: State, order: Order, line: TradeLine, today: date) -> list["rs.Change"]:
    """The ``trade_set``, the public news item and the paper to the importer's seats."""
    cut = cuts(order)
    frm, to = _name(state, line.exporter), _name(state, line.importer)
    carries = _carries(state, line)
    verb = "embargoes" if cut else "reopens"
    when = f"{today.day} {today:%B %Y}"
    news = NewsEvent(
        news_id=derived_id(state.campaign_id, "news", "trade", order.order_id),
        on=today,
        topic=NewsTopic.EVENT,  # [proposed] no topic is kept for trade; a new one is schema
        subject=line.exporter,
        obj=line.importer,
        headline=_clip(f"{frm} {verb} {carries.lower()} to {to}"),
        facts=(
            BodyField(label="By", value=frm),
            BodyField(label="To", value=to),
            BodyField(label="Carries", value=carries),
            BodyField(label="Date", value=when),
        ),
    )
    out: list[rs.Change] = [lines.set(state, line.key, open=not cut, on=today), news]
    readers = _seats(state, line.importer)
    if readers:
        scope = Scope(visibility=Visibility.RESTRICTED, known_by=readers)
        doc_id, view = _doc(state, order, "paper", line.exporter, today, scope)
        unit = (
            ""
            if state.kinds is None or line.resource not in state.kinds.resources
            else f" {state.kinds.resources[line.resource].unit}"
        )
        first = _first_paid(today)
        paying = f"{'Nothing' if cut else 'Again'} from {first.day} {first:%B %Y}"
        view = view.model_copy(
            update={
                "title": _clip(f"{frm} {'cuts' if cut else 'reopens'} its {carries.lower()} line"),
                "body": (
                    BodyField(label="From", value=frm),
                    BodyField(label="Carries", value=carries),
                    BodyField(label="A month", value=_clip(f"{line.amount:g}{unit}")),
                    BodyField(label="Pays", value=_clip(paying)),
                    BodyField(label="Date", value=when),
                ),
            }
        )
        out.append(ev.DocumentIssued(document=view, truth=DocumentTruth(doc_id=doc_id)))
    return out


def on_day(state: State, today: date) -> tuple["rs.Change", ...]:
    """The day's trade orders, each cutting or reopening its line, or reported as moving
    nothing. Each sees the lines the ones before it left."""
    out: list[rs.Change] = []
    now = state.economy.lines
    for order in due(state, today):
        nation = polity_of(state, state.seats[order.issuer].embodies)
        seen = state.model_copy(update={"economy": state.economy.model_copy(update={"lines": now})})
        why = refusal(seen, order, nation)
        if why is not None:
            out += _report(state, order, nation, why, today)
            continue
        line = now[str(order.params[LINE])]
        landed = _landed(seen, order, line, today)
        now = {**now, line.key: line.model_copy(update={"cut": cuts(order)})}
        out += landed
    return tuple(out)
