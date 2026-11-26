"""The ladder of posts: moved, relieved, restored (LDR), read with the ``posts`` rule on.

A post may carry a ladder, the lesser posts its holder falls to when he is put out of it,
and ``moved_by``, the posts whose holders may move him on their own order
(``ladders_declared``). An appointment or a dismissal to a post does not land the day it
is ordered: it is a pending change (``post_move_ordered``), sealed to the seat of the
person moved, that lands at the close of the wake after the one it was ordered in. A
dismissal puts the person on the first free rung of his ladder, or leaves him with no post
when it has none. A move that would take a seat's last authority, leaving the person a
seat plays with no post, is not done on order: it stands as the office question's cause
(OFQ) and never lands by itself. A restoration is an appointment like any other. The
price: the person moved down thinks the worse of the one who moved him, by
``REGARD_COST`` points of disposition.

``order`` is called where an appointment lands, ``due`` and ``land`` by the day's walk.
"""

from collections.abc import Mapping
from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import AssetId, DocumentId, EntityId, RelationshipId, SeatId, derived_id
from revisionist.core.ontology import EntityStatus, Relationship, regard_held
from revisionist.core.realism import posts
from revisionist.core.realism.card import ChannelKind, PostCause
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.state import PostMove, Rule, State, seat_of_person
from revisionist.core.visibility import Scope, Visibility, private_to

REGARD_COST = 2  # [proposed] disposition the person moved down loses toward his mover


def on(state: State) -> bool:
    return Rule.POSTS in state.rules


def post_named(state: State, office: str) -> AssetId | None:
    """The post an order names, by its id or its name, or None: only an office the world
    gave a ladder or movers takes a pending change; any other keeps the old landing, its
    fact and its news."""
    if not on(state):
        return None
    if AssetId(office) in state.ladders:
        return AssetId(office)
    wanted = office.strip().casefold()
    found = sorted(
        a.asset_id
        for a in state.assets.values()
        if a.asset_id in state.ladders and a.name.strip().casefold() == wanted
    )
    return found[0] if len(found) == 1 else None


def movers(state: State, post: AssetId) -> tuple[AssetId, ...]:
    """The posts whose holders may move ``post``'s holder on their own order; () when the
    world names none, and the old rule (an order from a principal) holds."""
    ladder = state.ladders.get(post)
    return ladder.moved_by if ladder is not None else ()


def may_move(state: State, issuer: EntityId, post: AssetId) -> bool | None:
    """Whether ``issuer`` holds a post the world lets move ``post``; None when the world
    names no mover for it."""
    names = movers(state, post)
    if not names:
        return None
    return any(posts.holder(state, m) == issuer for m in names)


def _alive(state: State, person: EntityId) -> bool:
    entity = state.entities.get(person)
    return entity is not None and entity.status is not EntityStatus.DEAD


def rung(state: State, post: AssetId, leaving: frozenset[EntityId] = frozenset()) -> AssetId | None:
    """The first free rung of ``post``'s ladder: one nobody holds, or held by someone in
    ``leaving``, who gives it up in the same move."""
    ladder = state.ladders.get(post)
    for step in ladder.ladder if ladder is not None else ():
        held = posts.holder(state, step)
        if held is None or held in leaving:
            return step
    return None


def _seated(state: State, person: EntityId) -> bool:
    return seat_of_person(state, person) is not None


def _down(state: State, person: EntityId, post: AssetId, appoint: bool) -> EntityId | None:
    """Who a move puts down: the person dismissed, the holder an appointment displaces,
    or the person appointed to a rung of his own post's ladder; None for no one."""
    current = posts.holder(state, post)
    if not appoint:
        return person if current == person else None
    if current is not None and current != person:
        return current
    card = state.cards.get(person)
    own = card.post if card is not None else None
    ladder = state.ladders.get(own) if own is not None else None
    return person if ladder is not None and post in ladder.ladder else None


def takes_last(state: State, person: EntityId, post: AssetId, appoint: bool) -> bool:
    """Whether the move would leave a person a seat plays with no post: his last
    authority, taken only at the office question's sitting (OFQ)."""
    current = posts.holder(state, post)
    if appoint:
        out = current if current is not None and current != person else None
        leaving = frozenset({person})
    else:
        out = person if current == person else None
        leaving = frozenset()
    if out is None or not _seated(state, out):
        return False
    return rung(state, post, leaving) is None


def order(
    state: State, person: EntityId, office: str, appoint: bool, by: EntityId, on_day: date
) -> list[ev.Payload] | None:
    """The pending change an appointment or dismissal makes, or None when the ladder does
    not take it (``posts`` off, an office that is no post, a person with no card): the old
    landing holds."""
    post = post_named(state, office)
    if post is None or person not in state.cards:
        return None
    verb = "appoint" if appoint else "dismiss"
    wake = state.wake.number if state.wake is not None else -1
    move_id = derived_id(state.campaign_id, "move", person, post, verb, on_day.isoformat(), wake)
    seat = seat_of_person(state, person)
    move = PostMove(
        move_id=move_id,
        person=person,
        seat=seat.seat_id if seat is not None else None,
        by=by,
        post=post,
        appoint=appoint,
        ordered=on_day,
        wake=wake,
        question=takes_last(state, person, post, appoint),
    )
    return [ev.PostMoveOrdered(move=move), *_notice(state, move)]


LINE = 120
TITLE = 60
"""The longest a paper's title may be (``Label``)."""


def _clip(text: str, at: int = LINE) -> str:
    return text if len(text) <= at else text[: at - 1] + "\N{HORIZONTAL ELLIPSIS}"


def notice_id(state: State, move_id: str) -> DocumentId:
    return DocumentId(derived_id(state.campaign_id, "move-notice", move_id))


def _notice(state: State, move: PostMove) -> list[ev.Payload]:
    """One paper, the day it is ordered, to the seat of the person moved: the notice a
    wake ahead. None for a person no seat plays."""
    if move.seat is None:
        return []
    doc_id = notice_id(state, move.move_id)
    if doc_id in state.documents:
        return []
    office = state.assets[move.post].name
    when = (
        "Only at the sitting of the office question"
        if move.question
        else "At the close of the next wake"
    )
    title = f"You are to take up {office}" if move.appoint else f"You are relieved of {office}"
    return [
        ev.DocumentIssued(
            document=DocumentView(
                doc_id=doc_id,
                kind=DocumentKind.REPORT,
                author=move.by,
                issued=move.ordered,
                arrives=move.ordered,
                channel=ChannelKind.CABLE,
                classification=Classification.CONFIDENTIAL,  # [proposed]
                title=_clip(title, TITLE),
                body=(
                    BodyField(label="Post", value=_clip(office)),
                    BodyField(label="Takes effect", value=when),
                ),
                scope=private_to(move.seat),
            ),
            truth=DocumentTruth(doc_id=doc_id),
        )
    ]


def due(state: State) -> list[str]:
    """The pending changes that land now: ordered in a wake before the last one closed,
    and not the office question's cause. Earliest ordered first."""
    wake = state.wake
    if not on(state) or wake is None or not wake.closed:
        return []
    ready = (m for m in state.post_moves.values() if not m.question and m.wake < wake.number)
    return [m.move_id for m in sorted(ready, key=lambda m: (m.ordered, m.move_id))]


def land(state: State, move_id: str, day: date) -> list[ev.Payload]:
    """The events that land a pending change: the posts it moves, the regard it costs and
    its settling. Void, with no post moved, when the person or the post is no longer as it
    was, or the move would now take a seat's last authority."""
    m = state.post_moves[move_id]
    settled = ev.PostMoveSettled(move_id=m.move_id, seat=m.seat, on=day, landed=False)
    current = posts.holder(state, m.post)
    void = (
        not _alive(state, m.person)
        or m.person not in state.cards
        or (m.appoint and current == m.person)
        or (not m.appoint and current != m.person)
    )
    if void:
        return [settled]
    if takes_last(state, m.person, m.post, m.appoint):
        # The world moved under it: it would now take a seat's last authority, so it is
        # not done on order but stands, a fresh pending change, as the question's cause.
        wake = state.wake.number if state.wake is not None else -1
        seat = seat_of_person(state, m.person)
        stand = m.model_copy(
            update={
                "move_id": derived_id(state.campaign_id, "move-stands", m.move_id),
                "seat": seat.seat_id if seat is not None else None,
                "ordered": day,
                "wake": wake,
                "question": True,
            }
        )
        return [settled, ev.PostMoveOrdered(move=stand), *_notice(state, stand)]
    down = _down(state, m.person, m.post, m.appoint)
    out: list[ev.Payload] = []
    if m.appoint:
        out += posts.change(state, m.post, m.person, day, PostCause.APPOINTED)
        if current is not None:
            out += _fall(state, current, m.post, frozenset({m.person}), day)
    else:
        out.append(
            ev.PostChanged(post=m.post, holder=m.person, to=None, on=day, cause=PostCause.APPOINTED)
        )
        out += _fall(state, m.person, m.post, frozenset(), day)
    if down is not None and down != m.by:
        out += _regard(state, down, m.by)
    return [*out, settled.model_copy(update={"landed": True})]


def _fall(
    state: State, person: EntityId, post: AssetId, leaving: frozenset[EntityId], day: date
) -> list[ev.Payload]:
    step = rung(state, post, leaving)
    if step is None:
        return []
    held = posts.holder(state, step)
    # A rung the appointee gave up is vacated by the appointment's own events.
    was = None if held in leaving else held
    return [ev.PostChanged(post=step, holder=was, to=person, on=day, cause=PostCause.APPOINTED)]


def regard_of(
    relationships: Mapping[RelationshipId, Relationship], of: EntityId, toward: EntityId
) -> int:
    """``of``'s regard for ``toward`` as ``regard_held`` reads it; nothing when he has none."""
    held = regard_held(relationships, of, toward)
    return held.disposition if held is not None else 0


def _regard(state: State, of: EntityId, toward: EntityId) -> list[ev.Payload]:
    return list(regard(state, of, toward, REGARD_COST))


def regard(
    state: State,
    of: EntityId,
    toward: EntityId,
    cost: int,
    seats: frozenset[SeatId] | None = None,
) -> list[ev.RelationshipSet]:
    """``of``'s regard for ``toward`` lowered by ``cost``, from nothing when he has none:
    a moved post's cost here, and an incident's.

    Without ``seats`` every record of it is lowered, each in its own scope. With ``seats``
    the change is known to those seats alone: a regard others can see is left as it
    stands and the lowered one is kept apart, sealed to ``seats``, so no other seat learns
    from it that anything passed between the two."""
    if seats is None:
        found = [r for r in state.relationships.values() if r.a == of and r.b == toward]
        if found:
            return [
                ev.RelationshipSet(
                    relationship=r.model_copy(update={"disposition": max(-5, r.disposition - cost)})
                )
                for r in found
            ]
        seat = seat_of_person(state, of)
        scope = scope_of(state, seat.seat_id if seat is not None else None)
        rid = RelationshipId(derived_id(state.campaign_id, "rel", of, toward))
        return [_lowered(rid, of, toward, 0, cost, scope)]
    now = regard_held(state.relationships, of, toward)
    scope = _sealed(state, seats)
    rid = RelationshipId(derived_id(state.campaign_id, "rel", of, toward))
    if now is not None:
        if now.scope.visibility is Visibility.RESTRICTED and now.scope.known_by <= scope.known_by:
            scope, rid = now.scope, now.relationship_id
        else:
            rid = RelationshipId(derived_id(state.campaign_id, "rel", of, toward, "sealed"))
    return [_lowered(rid, of, toward, now.disposition if now is not None else 0, cost, scope)]


def _lowered(
    rid: RelationshipId, of: EntityId, toward: EntityId, was: int, cost: int, scope: Scope
) -> ev.RelationshipSet:
    return ev.RelationshipSet(
        relationship=Relationship(
            relationship_id=rid, a=of, b=toward, disposition=max(-5, was - cost), scope=scope
        )
    )


def _sealed(state: State, seats: frozenset[SeatId]) -> Scope:
    if seats:
        return Scope(visibility=Visibility.RESTRICTED, known_by=seats)
    held = SeatId(derived_id(state.campaign_id, "engine-only", "regard"))
    return Scope(visibility=Visibility.RESTRICTED, known_by=frozenset({held}))


def scope_of(state: State, seat: SeatId | None) -> Scope:
    """A pending change and its settling: sealed to the seat of the person moved, or to
    no seat."""
    if seat is not None:
        return private_to(seat)
    held = SeatId(derived_id(state.campaign_id, "engine-only", "post-moves"))
    return Scope(visibility=Visibility.RESTRICTED, known_by=frozenset({held}))


__all__ = [
    "REGARD_COST",
    "due",
    "land",
    "may_move",
    "movers",
    "order",
    "post_named",
    "regard",
    "regard_of",
    "rung",
    "scope_of",
    "takes_last",
]
