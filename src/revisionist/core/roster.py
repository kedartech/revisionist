"""The character rule, in code (spec §5.5). Phase 2 unit.

A playable character controls a force, office or network asset of tier 2 or
more that bears on a contest. Money, information or facilities alone do not
qualify. A world with ``playable_rule`` on uses the playable rule instead
(``admits``, PBR): the card commands something outright and can be played.
"""

from typing import NamedTuple

from revisionist.core import contest
from revisionist.core._base import Model
from revisionist.core.goals import replacement_aims
from revisionist.core.ids import ContestId, EntityId
from revisionist.core.ontology import AssetKind, AssetStatus, Controller, EntityKind
from revisionist.core.realism.card import CardPath, SeatCard
from revisionist.core.state import Rule, State, controller_after

QUALIFYING_TIER = 2
QUALIFYING_KINDS = frozenset({AssetKind.FORCE, AssetKind.OFFICE, AssetKind.NETWORK})


class Floor(NamedTuple):
    """The lines of the playable rule's floor (PBR): a card's rank, or the tier of a force
    it commands. A world that sets none takes these."""

    rank: int = 2
    tier: int = 3


def admits(state: State, card: SeatCard, floor: Floor | None) -> tuple[str, ...]:
    """Why the playable rule (PBR) does not admit ``card``, in plain words; none when it
    does. It commands something outright and can be played: an authority domain, a form
    of its own through one of its pipelines, someone other than the person in its inner
    circle, three aims with conditions, and with ``command`` on, for a commander, a domain
    that names a force. With a ``floor``, its rank or a force it commands reaches a line."""
    why: list[str] = []
    if not card.authority:
        why.append("it commands nothing outright")
    if not any(lv.pipeline in card.pipelines for lv in card.levers):
        why.append("it has no form of its own")
    if not any(k.person != card.person for k in card.inner_circle):
        why.append("it has no one in its inner circle")
    held = sum(r is not None for r in card.aim_rules[: len(card.aims)])
    if held < 3:
        why.append(f"it has {held} of three aims with conditions")
    forces = [f for d in card.authority for f in d.forces]
    if Rule.COMMAND in state.rules and card.path is CardPath.MILITARY and not forces:
        why.append("it is a commander with no force named in a domain")
    if floor is not None and card.reach.rank < floor.rank:
        tiers = [state.features[f].tier for f in forces if f in state.features]
        if not any(t >= floor.tier for t in tiers):
            why.append(
                f"it is under the floor: rank {card.reach.rank}, no force of tier {floor.tier}"
            )
    return tuple(why)


def qualifies(state: State, entity: EntityId) -> bool:
    """True when ``entity`` meets the character rule in ``state``."""
    found = state.entities.get(entity)
    if found is None or found.kind is not EntityKind.PERSON:
        return False
    holds = any(
        a.controller == entity
        and a.kind in QUALIFYING_KINDS
        and a.tier >= QUALIFYING_TIER
        and a.status is not AssetStatus.LOST
        for a in state.assets.values()
    )
    if not holds:
        return False
    return not state.contests or bool(_bearing(state, entity))


def _bearing(state: State, entity: EntityId) -> tuple[ContestId, ...]:
    """Undecided contests ``entity`` stands in: through its ``parent`` chain, or
    by the side its roster entry declares (spec §5.5, "their side in each
    contest"). A governor or envoy under no side can still declare one."""
    found = set(contest.bearing(state, entity))
    listed = state.roster.get(entity)
    if listed is not None:
        for s in listed.sides:
            k = state.contests.get(s.contest_id)
            if k is not None and not k.decided and s.side in k.sides:
                found.add(s.contest_id)
    return tuple(sorted(found))


def nearest(state: State, entity: EntityId) -> EntityId | None:
    """The nearest qualified person to offer instead of one who fails the rule.

    Same parent first, then any shared contest; ties go by name. None when
    neither group has anyone.
    """
    people = _open(state, entity)
    found = state.entities.get(entity)
    if found is None:
        return min(people, key=lambda c: _order(state, c), default=None)
    same_parent = [
        c for c in people if found.parent is not None and state.entities[c].parent == found.parent
    ]
    mine = set(_bearing(state, entity))
    shared = [c for c in people if mine & set(_bearing(state, c))]
    for group in (same_parent, shared):
        if group:
            return min(group, key=lambda c: _order(state, c))
    return None


def problems(state: State) -> list[str]:
    """Why each roster character fails the rule, in name order; none without contests."""
    if not state.contests:
        return []
    failing = [c for c in state.roster if not qualifies(state, c)]
    return [
        f"character {state.entities[c].name}: controls no force, office or network "
        f"of tier {QUALIFYING_TIER}+ in a contest"
        for c in sorted(failing, key=lambda c: _order(state, c))
    ]


class Candidate(Model):
    """One roster person as the opening offers him: public, the same for every caller."""

    person: EntityId
    name: str
    nation: EntityId | None
    """The polity above the person in the parent chain; None when there is none."""
    path: CardPath | None
    """The card's path; None while the person has no card."""
    office: str
    pitch: str
    taken: bool
    reason: str | None
    """Why the person may not be taken, in plain words; None when he may."""


def claimable(state: State) -> tuple[Candidate, ...]:
    """Every roster person, in name order, with whether a player may take him and why not.

    The test is the claim's: unclaimed, the character rule where the world has contests,
    and in a realism world a playable card; with ``playable_rule`` on, the playable rule
    alone. It reads the state alone, never a seat.
    """
    return tuple(_candidate(state, c) for c in sorted(state.roster, key=lambda c: _order(state, c)))


def replacements(state: State, person: EntityId) -> tuple[Candidate, ...]:
    """The people a seat that can no longer play ``person`` may take in his place (RPL):
    those ``claimable`` lets a player take, whom nobody plays once the open wake closes,
    who can act, have not been replaced, and have the two aims a replacement must hold;
    ``person``'s own nation's first, each group in ``claimable``'s order."""
    from revisionist.core.realism import posts  # posts reaches the roster through state

    nation = _nation(state, person)
    found = [
        c
        for c in claimable(state)
        if c.reason is None
        and c.person != person
        and controller_after(state, c.person) is Controller.AI
        and posts.can_act(state, c.person)
        and c.person not in state.replaced.values()
        and replacement_aims(state.cards[c.person].aim_rules, len(state.cards[c.person].aims))
    ]
    return tuple(sorted(found, key=lambda c: nation is None or c.nation != nation))


def _candidate(state: State, entity: EntityId) -> Candidate:
    name = state.entities[entity].name
    card = state.cards.get(entity)
    taken = state.roster[entity].claimed_by is not None
    reason: str | None = None
    if taken:
        reason = f"{name} is already taken."
    elif Rule.PLAYABLE_RULE in state.rules:
        reason = _by_rule(state, name, card)
    elif state.contests and not qualifies(state, entity):
        reason = (
            f"{name} does not meet the character rule: a playable character needs a force, "
            f"office or network of tier {QUALIFYING_TIER} or more in one of the world's contests."
        )
    elif state.ruleset == "realism" and (card is None or not card.playable):
        reason = f"{name} is not ready to be played yet."
    return Candidate(
        person=entity,
        name=name,
        nation=_nation(state, entity),
        path=card.path if card is not None else None,
        office=card.office if card is not None else "",
        pitch=state.roster[entity].pitch,
        taken=taken,
        reason=reason,
    )


def _by_rule(state: State, name: str, card: SeatCard | None) -> str | None:
    """With ``playable_rule`` on, the rule in place of the character rule: the card the
    compiler admitted (its floor and the world's hold-back are read there), as it stands."""
    if card is None or not card.playable:
        return f"{name} is not ready to be played yet."
    why = admits(state, card, None)
    return f"{name} cannot be played: {why[0]}." if why else None


def refusal(state: State, entity: EntityId) -> str | None:
    """Why a player may not take the roster person ``entity``, as ``claimable`` says it;
    None when he may."""
    return _candidate(state, entity).reason


def _nation(state: State, entity: EntityId) -> EntityId | None:
    seen: set[EntityId] = set()
    at = state.entities[entity].parent
    while at is not None and at not in seen and at in state.entities:
        if state.entities[at].kind is EntityKind.POLITY:
            return at
        seen.add(at)
        at = state.entities[at].parent
    return None


def _open(state: State, entity: EntityId) -> list[EntityId]:
    """Qualified, unclaimed roster people other than ``entity``."""
    return [
        c
        for c, ch in state.roster.items()
        if c != entity and ch.claimed_by is None and qualifies(state, c)
    ]


def _order(state: State, entity: EntityId) -> tuple[str, str]:
    return (state.entities[entity].name, entity)
