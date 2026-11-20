"""Reach: who a person can get word to, by which channel, and how fast (spec §8.1, §8.4).

Reach is derived from the cards and the world, never whitelisted. The inner circle is
always open; a person's own chain is summoned; a foreign head is reached by cable or
envoy when the sender may address one; everyone else takes a meeting only when
standing and disposition carry it. While an envoy of the sender's nation stands at a
foreign capital, the sender's word to that nation's leader arrives the same day (ENV).
"""

from collections.abc import Iterator
from datetime import date

from revisionist.core.ids import EntityId
from revisionist.core.ontology import EntityKind
from revisionist.core.realism.card import CHANNELS, ChannelKind, Tie
from revisionist.core.realism.resolvers import friction
from revisionist.core.state import State

EXPOSURE: dict[ChannelKind, int] = {  # [proposed] 0 secure .. 3 open
    ChannelKind.IN_PERSON: 0,
    ChannelKind.TELEPHONE: 2,
    ChannelKind.CABLE: 1,
    ChannelKind.LETTER: 1,
    ChannelKind.COURIER: 1,
    ChannelKind.RADIO: 2,
    ChannelKind.PRESS: 3,
}

TRANSIT_DAYS: dict[ChannelKind, int] = {  # [proposed] realism direction 2026-10-22
    ChannelKind.IN_PERSON: 1,
    ChannelKind.TELEPHONE: 0,
    ChannelKind.CABLE: 0,
    ChannelKind.LETTER: 2,
    ChannelKind.COURIER: 5,
    ChannelKind.RADIO: 0,
    ChannelKind.PRESS: 0,
}


def _known(state: State, *who: EntityId) -> None:
    for w in who:
        if w not in state.entities:
            raise KeyError(w)


def _ancestors(state: State, who: EntityId) -> Iterator[EntityId]:
    parent = state.entities[who].parent
    while parent is not None:
        yield parent
        parent = state.entities[parent].parent


def _polity(state: State, who: EntityId) -> EntityId | None:
    for node in (who, *_ancestors(state, who)):
        if state.entities[node].kind is EntityKind.POLITY:
            return node
    return None


def tie(state: State, frm: EntityId, to: EntityId) -> Tie:
    """How ``frm`` stands to ``to``. Rules are checked in order; the first that fits wins."""
    _known(state, frm, to)
    me = state.cards.get(frm)
    if me is not None:
        if any(c.person == to for c in me.inner_circle):
            return Tie.INNER
        chain = set(me.reach.chain)
        theirs = state.cards.get(to)
        if any(a in chain for a in _ancestors(state, to)) and (
            theirs is None or frm in theirs.principals or any(p in chain for p in theirs.principals)
        ):
            return Tie.CHAIN
        if theirs is not None and theirs.reach.rank == 5:
            their_polity = _polity(state, to)
            if their_polity is not None and their_polity != _polity(state, frm):
                return Tie.HEAD
    return Tie.PUBLIC


def channels_to(state: State, frm: EntityId, to: EntityId) -> tuple[ChannelKind, ...]:
    """The channels ``frm`` may send by. A person who may not address a foreign head
    cannot reach one at all."""
    t = tie(state, frm, to)
    if t is Tie.HEAD and not state.cards[frm].reach.heads:
        return ()
    if t is Tie.INNER:
        first = next(c.channel for c in state.cards[frm].inner_circle if c.person == to)
        return (first, *(c for c in CHANNELS[t] if c != first))
    return CHANNELS[t]


def takes_meeting(state: State, frm: EntityId, to: EntityId, *parts: object) -> bool:
    """Whether ``to`` takes a meeting ``frm`` asks for. Deterministic in state and parts."""
    t = tie(state, frm, to)
    if t in (Tie.INNER, Tie.CHAIN):
        return True
    if t is Tie.HEAD:
        return bool(channels_to(state, frm, to))
    mine = state.cards.get(frm)
    theirs = state.cards.get(to)
    rank_frm = mine.reach.rank if mine is not None else 0
    rank_to = theirs.reach.rank if theirs is not None else 0
    disposition = theirs.loyalty if theirs is not None and frm in theirs.principals else 0
    d = friction(state, frm, to, *parts, n=5) - 2  # [proposed] spread -2..2
    return rank_frm - rank_to + disposition + d >= 0


def transit_days(channel: ChannelKind) -> int:
    return TRANSIT_DAYS[channel]


def quickened(state: State, frm: EntityId, to: EntityId, on: date) -> bool:
    """Whether ``frm``'s word to ``to`` arrives the same day it is sent on ``on``: ``to``
    leads a foreign nation (a head of government) and an envoy of ``frm``'s nation has
    stood at that nation's capital since ``on`` or earlier (ENV rule 3)."""
    from revisionist.core.realism import agreement

    _known(state, frm, to)
    theirs = state.cards.get(to)
    if theirs is None or theirs.reach.rank != 5:
        return False
    mine, their_polity = _polity(state, frm), _polity(state, to)
    if mine is None or their_polity is None or mine == their_polity:
        return False
    since = agreement.envoy_at_capital(state, mine, their_polity)
    return since is not None and since <= on


def transit(state: State, frm: EntityId, to: EntityId, channel: ChannelKind, on: date) -> int:
    """The days ``frm``'s word sent to ``to`` on ``on`` by ``channel`` takes: none while
    ``quickened``, else the channel's."""
    return 0 if quickened(state, frm, to, on) else transit_days(channel)


__all__ = [
    "EXPOSURE",
    "TRANSIT_DAYS",
    "channels_to",
    "quickened",
    "takes_meeting",
    "tie",
    "transit",
    "transit_days",
]
