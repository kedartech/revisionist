"""Player, person and post kept apart (PPP), read with the ``posts`` rule on.

A post is an office asset and the part of its holder's card that goes with it
(``card.PostPart``): the office's name, its powers, authority, forms, pipelines and feeds,
the bodies that answer its summons, whom it answers to and its designated successor. The
rest of the card is the person's own and stays with him. ``post_changed`` moves a post to
another person or to nobody; a seat goes on playing its person wherever the post goes.

Other items call ``holder`` and ``change``; the wake calls ``walk``.
"""

from collections.abc import Iterator
from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import AssetId, EntityId
from revisionist.core.ontology import EntityStatus
from revisionist.core.realism.card import PostCause, PostPart, post_part
from revisionist.core.state import Rule, State


def holder(state: State, post: AssetId) -> EntityId | None:
    """Who holds ``post`` now: the person whose card names it, or nobody."""
    kept = state.posts.get(post)
    if kept is not None:
        return kept.holder
    return next((c.person for c in state.cards.values() if c.post == post), None)


def _part(state: State, post: AssetId) -> PostPart | None:
    kept = state.posts.get(post)
    if kept is not None:
        return kept.part
    who = holder(state, post)
    return post_part(state.cards[who]) if who is not None else None


def _all(state: State) -> Iterator[AssetId]:
    seen = {*state.posts, *(c.post for c in state.cards.values() if c.post is not None)}
    yield from sorted(seen)


def change(
    state: State, post: AssetId, to: EntityId | None, on: date, cause: PostCause
) -> list[ev.PostChanged]:
    """The events that give ``post`` to ``to`` (None: to nobody). A new holder who holds
    another post leaves it first, to nobody. Nothing with ``posts`` off, or when ``to``
    holds it already."""
    if Rule.POSTS not in state.rules:
        return []
    current = holder(state, post)
    if to == current:
        return []
    out: list[ev.PostChanged] = []
    card = state.cards.get(to) if to is not None else None
    if card is not None and card.post is not None:
        out.append(
            ev.PostChanged(post=card.post, holder=to, to=None, on=on, cause=PostCause.VACATED)
        )
    out.append(ev.PostChanged(post=post, holder=current, to=to, on=on, cause=cause))
    return out


def _alive(state: State, person: EntityId) -> bool:
    entity = state.entities.get(person)
    return entity is not None and entity.status is not EntityStatus.DEAD


def walk(state: State, day: date) -> list[ev.PostChanged]:
    """The day's successions: a post nobody holds, or whose holder is dead, goes to its
    designated successor, if he is alive, has a card and was not its last holder. A dead
    holder with no successor leaves the post to nobody. Each person and post once a day:
    a successor who leaves his own post to take another fills it on a later day."""
    if Rule.POSTS not in state.rules:
        return []
    out: list[ev.PostChanged] = []
    used: set[str] = set()
    for post in _all(state):
        if post in used:
            continue
        current = holder(state, post)
        dead = current is not None and not _alive(state, current)
        if current is not None and not dead:
            continue
        part = _part(state, post)
        kept = state.posts.get(post)
        last = current if current is not None else kept.last if kept is not None else None
        heir = part.successor if part is not None else None
        able = (
            heir is not None
            and heir not in used
            and heir != last
            and heir in state.cards
            and _alive(state, heir)
        )
        if not able and not dead:
            continue
        to = heir if able else None
        found = change(state, post, to, day, PostCause.SUCCEEDED)
        if any(p.post in used for p in found):
            continue
        out += found
        used.update(p.post for p in found)
        used.update(p for p in (to, current) if p is not None)
    return out


def can_act(state: State, person: EntityId) -> bool:
    """Whether ``person`` can still act: alive, and holding a post, an authority of his
    own, or someone in his inner circle whose card holds an authority."""
    card = state.cards.get(person)
    if card is None or not _alive(state, person):
        return False
    if card.post is not None or card.authority:
        return True
    return any(
        (other := state.cards.get(c.person)) is not None and bool(other.authority)
        for c in card.inner_circle
    )


def needs_replacement(state: State, person: EntityId) -> bool:
    """With ``posts`` on, whether the seat playing ``person`` is to be offered another
    person (RPL): he is dead, or cannot act (``can_act``)."""
    return Rule.POSTS in state.rules and not can_act(state, person)


__all__ = ["PostCause", "can_act", "change", "holder", "needs_replacement", "walk"]
