"""Battles as the seat sees them (BTD).

The ``battles`` block of ``view.realism`` lists each battle the seat's nation is a side
of: its area, the day it opened, each round as the seat's own round reports give it (its
side's losses and the enemy's as contact saw them), its side's strength, the range its
own papers put the enemy at, the decision in force and the decisions it may still give.
A battle the seat's nation is not in is not listed: the seat knows it only from the news.

Nothing here reads a battle's true enemy figures, a round's draws or the other side's
decision. The enemy's range comes from the seat's own sighting papers; the rounds come
from the seat's own round reports, so a seat that commands none of its side's pieces
sees none.

The ``battle`` and ``contingency`` actions build the asks a seat would type (a posture or
a move for one of its pieces in the battle, an engagement with a contingency) and file
them through ``realism_tick.commit_order``; after a commit they are held for the next
wake like any other order. A battle the seat may decide and has not, by an order landed
or still on its way, is a due matter at the open wake's close (``due``, registered in
``agenda_api.DUE_KINDS``).
"""

from collections.abc import Collection, Mapping, Sequence
from datetime import date
from typing import TYPE_CHECKING, Any

from revisionist.core.ids import EntityId, FeatureId, SeatId
from revisionist.core.realism import battle, territory
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.battle import Battle, BattleSide, Decision
from revisionist.core.realism.effect import (
    Contingency,
    ContingencyKind,
    Engagement,
    MoveForce,
    Posture,
    SetEngagement,
)
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.kinds import Domain
from revisionist.core.state import State, View
from revisionist.core.world_compile import object_id
from revisionist.engine.web.destinations import latest_sightings, own_sides, reported
from revisionist.engine.web.realism_api import (
    BattlePiece,
    BattleRoundLine,
    BattleView,
    StrengthRange,
)

TIER_LOW, TIER_HIGH = 1, 5
"""[proposed] The strength an enemy piece the seat's papers place but give no figure for
may have: any tier a fighting piece can have."""
if TYPE_CHECKING:
    from revisionist.engine.odds import Ended

DECISIONS = tuple(d.value for d in Decision)
CONTINGENCIES = tuple(k.value for k in ContingencyKind)
NOT_IN = "Your nation is in no battle there."  # [proposed]
NOT_YOURS = "None of your forces in that battle is yours to order."  # [proposed]
NOT_YOURS_FORCE = "That force is not yours to order."  # [proposed]
DECIDED = "You have already given this battle its decision for this wake."  # [proposed]
_POSTURE = {Decision.PRESS: Posture.ATTACK, Decision.HOLD: Posture.HOLD}


def _keys(state: State) -> dict[EntityId, tuple[str, str]]:
    """Each area of the board: its map key and its name."""
    board = state.map
    if board is None:
        return {}
    out = {t.area: (t.key, t.name) for t in board.territories}
    out |= {z.area: (z.key, z.name) for z in board.sea_zones}
    return out


def _on(state: State, side: BattleSide, own: EntityId) -> bool:
    """``own`` leads the side, or one of the side's pieces is its own."""
    if side.nation == own:
        return True
    for fid in side.pieces:
        f = state.features.get(fid)
        if f is not None and territory.nation(state, f.side) == own:
            return True
    return False


def sides_of(state: State, b: Battle, own: EntityId) -> tuple[BattleSide, BattleSide] | None:
    """The seat's nation's side of ``b`` and the enemy's; None when it is on neither."""
    if _on(state, b.attacker, own):
        return b.attacker, b.defender
    if _on(state, b.defender, own):
        return b.defender, b.attacker
    return None


def _nation(state: State, seat: SeatId) -> EntityId | None:
    me = state.seats.get(seat)
    return territory.nation(state, me.embodies) if me is not None else None


def _open_wake(state: State) -> int | None:
    wake = state.wake
    return wake.number if wake is not None and not wake.closed else None


def _commands(state: State, seat: SeatId, side: BattleSide) -> bool:
    return seat in battle.commanders(state, side)


def _sent(state: State, seat: SeatId, side: BattleSide) -> bool:
    """The seat has a posture or move for one of the side's pieces still on its way."""
    pieces = set(side.pieces)
    for order in state.routed.values():
        if order.issuer != seat:
            continue
        for part in order.parts:
            if part.refusal or part.applied is not None or part.accepted is False:
                continue
            if isinstance(part.effect, MoveForce) and part.effect.force in pieces:
                return True
    return False


def _decided(state: State, seat: SeatId, side: BattleSide, wake: int) -> bool:
    """The side has its decision for ``wake``: landed, or sent by the seat this wake."""
    return side.decided_wake == wake or _sent(state, seat, side)


def _rounds(
    state: State, view: View, b: Battle, seat: SeatId, until: date | None = None
) -> list[BattleRoundLine]:
    """Each round as the seat's own report of it gives it, oldest first, up to ``until``
    (an ended battle's last day: a later battle in the area has its own rounds)."""
    out: list[BattleRoundLine] = []
    today = view.in_world_date
    if today is None:
        return out
    if until is not None:
        today = min(today, until)
    for n in range((today - b.opened).days + 1):
        day = b.opened.fromordinal(b.opened.toordinal() + n)
        page = view.documents.get(battle.report_id(state, b, day, seat))
        if page is None:
            continue
        lines = {f.label: f.value for f in page.body}
        out.append(
            BattleRoundLine(
                on=day.isoformat(),
                own_lost=_steps(lines.get("Our losses")),
                enemy_lost=_steps(lines.get("Enemy losses seen")),
            )
        )
    return out


def _steps(value: object) -> int:
    """The figure of a round report's line (\"3 steps\")."""
    if isinstance(value, int):
        return value
    head = str(value or "0").split(" ", 1)[0]
    return int(head) if head.isdigit() else 0


def _enemy_range(state: State, view: View, area: EntityId, enemy: EntityId) -> StrengthRange | None:
    """The range the seat's latest papers put the enemy in ``area`` at: the figures they
    give, and for a piece placed there with no figure, any tier. None before any paper
    places an enemy piece there."""
    own = own_sides(view)
    seas = {z.area for z in state.map.sea_zones} if state.map is not None else set()
    domain = Domain.SEA if area in seas else Domain.LAND
    low = high = 0
    placed = False
    for (label, _kind), (_doc, _page, line) in sorted(latest_sightings(view).items()):
        sight = line.sight
        if sight is None or sight.side is None or sight.side in own:
            continue
        if territory.nation(state, sight.side) != enemy:
            continue
        if not any(territory.area_of(state, p, domain) == area for p in sight.places):
            continue
        placed = True
        figure = reported(view, label)
        low += figure if figure is not None else TIER_LOW
        high += figure if figure is not None else TIER_HIGH
    return StrengthRange(low=low, high=high) if placed else None


def _present(state: State, b: Battle, side: BattleSide) -> list[Feature]:
    """The side's pieces still able to fight, standing in one of the battle's areas."""
    areas = {b.area} if b.second is None else {b.area, b.second}
    out: list[Feature] = []
    for fid in side.pieces:
        f = state.features.get(fid)
        if f is not None and battle.fighting_area(state, f) in areas:
            out.append(f)
    return out


def _pieces(
    state: State, b: Battle, side: BattleSide, forces: Mapping[str, str]
) -> list[BattlePiece]:
    """The side's pieces the seat's movement forms name, standing in the battle."""
    present = {f.feature_id for f in _present(state, b, side)}
    out: list[BattlePiece] = []
    for key in sorted(forces):
        fid = FeatureId(object_id(state.campaign_id, "feature", key))
        f = state.features.get(fid)
        if f is None or fid not in present:
            continue
        c = f.contingency
        out.append(
            BattlePiece(
                force=key,
                name=f.name,
                strength=f.tier,
                contingency=c.kind.value if c is not None else None,
            )
        )
    return out


def block(
    state: State,
    seat: SeatId,
    view: View,
    forces: Mapping[str, str],
    held: Collection[str] = (),
    ended: Sequence["Ended"] = (),
) -> list[BattleView]:
    """Each battle the seat's nation is a side of, by area name. ``forces`` (the force
    keys the seat's movement forms name) picks the pieces it may give a contingency;
    ``held`` are the area keys of battles it has a decision held for the next wake;
    ``ended`` (``odds.ended``) the battles it fought that have ended, each listed after
    the open ones with its closing odds."""
    own = _nation(state, seat)
    if own is None or not battle.on(state):
        return []
    keys = _keys(state)
    wake = _open_wake(state)
    out: list[BattleView] = []
    for area, b in state.battles.items():
        sides = sides_of(state, b, own)
        if sides is None or area not in keys:
            continue
        mine, theirs = sides
        key, name = keys[area]
        commands = _commands(state, seat, mine)
        held_here = key in held
        decided = held_here or (wake is not None and _decided(state, seat, mine, wake))
        enemy = state.entities.get(theirs.nation)
        out.append(
            BattleView(
                area=key,
                name=name,
                opened=b.opened.isoformat(),
                side="attacker" if mine is b.attacker else "defender",
                enemy=enemy.name if enemy is not None else "",
                rounds=_rounds(state, view, b, seat),
                strength=max(0, mine.brought - mine.lost),
                enemy_strength=_enemy_range(state, view, area, theirs.nation),
                decision=mine.decision.value if mine.decision is not None else None,
                decided=decided,
                held=held_here,
                decisions=list(DECISIONS) if commands and wake is not None and not decided else [],
                contingencies=list(CONTINGENCIES) if commands else [],
                pieces=_pieces(state, b, mine, forces),
                ended=None,
                closing=None,
            )
        )
    out.sort(key=lambda v: (v["name"], v["area"]))
    return out + sorted(
        (v for v in (_ended(state, seat, view, e, own) for e in ended) if v is not None),
        key=lambda v: (v["ended"] or "", v["name"], v["area"]),
    )


def _ended(state: State, seat: SeatId, view: View, e: "Ended", own: EntityId) -> BattleView | None:
    """An ended battle as the seat sees it: its own reports of the rounds, no orders to
    give, and the closing odds."""
    keys = _keys(state)
    b = e.battle
    sides = sides_of(state, b, own)
    if sides is None or b.area not in keys:
        return None
    mine, theirs = sides
    key, name = keys[b.area]
    rounds = _rounds(state, view, b, seat, e.ended)
    enemy = state.entities.get(theirs.nation)
    return BattleView(
        area=key,
        name=name,
        opened=b.opened.isoformat(),
        side="attacker" if mine is b.attacker else "defender",
        enemy=enemy.name if enemy is not None else "",
        rounds=rounds,
        strength=max(0, mine.brought - mine.lost - sum(r["own_lost"] for r in rounds)),
        enemy_strength=None,
        decision=None,
        decided=False,
        held=False,
        decisions=[],
        contingencies=[],
        pieces=[],
        ended=e.ended.isoformat(),
        closing=e.closing,
    )


def due(state: State, seat: SeatId) -> list[tuple[str, str]]:
    """Each battle that waits on ``seat`` in the open wake, as (subject, words): one its
    nation is a side of, whose pieces it commands, with no decision for this wake. The
    subject is the battle's opening news, which every seat holds."""
    own, wake = _nation(state, seat), _open_wake(state)
    if own is None or wake is None or not battle.on(state):
        return []
    keys = _keys(state)
    out: list[tuple[str, str]] = []
    for area, b in sorted(state.battles.items(), key=lambda kv: keys.get(kv[0], ("", ""))[1]):
        sides = sides_of(state, b, own)
        if sides is None or area not in keys:
            continue
        mine = sides[0]
        if not _commands(state, seat, mine) or _decided(state, seat, mine, wake):
            continue
        subject = battle.news_id(state, b, ("meeting " if b.meeting else "") + "opened")
        out.append((subject, f"The battle at {keys[area][1]} awaits your decision"))
    return out


# --- the battle and contingency actions -------------------------------------------------


def _maybe(body: Mapping[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 120:
        raise ValueError(f"{key} must be text of at most 120 characters.")
    return value.strip()


def _need(body: Mapping[str, Any], key: str) -> str:
    value = _maybe(body, key)
    if value is None:
        raise ValueError(f"{key} is empty.")
    return value


def _area(state: State, key: str) -> EntityId:
    found = next((a for a, (k, _) in _keys(state).items() if k == key), None)
    if found is None:
        raise ValueError(f"There is no area {key}.")
    return found


def _battle(state: State, seat: SeatId, key: str) -> tuple[Battle, BattleSide]:
    own = _nation(state, seat)
    b = battle.at(state, _area(state, key)) if battle.on(state) else None
    sides = sides_of(state, b, own) if b is not None and own is not None else None
    if b is None or sides is None:
        raise ValueError(NOT_IN)
    return b, sides[0]


def _piece(state: State, seat: SeatId, b: Battle, side: BattleSide) -> Feature:
    """The first of the side's pieces in the battle that the seat commands."""
    from revisionist.core.realism import war_rules

    for f in _present(state, b, side):
        if any(s == seat for s, _ in war_rules.commanders(state, f.feature_id)):
            return f
    raise ValueError(NOT_YOURS)


def battle_asks(state: State, seat: SeatId, body: Mapping[str, Any]) -> tuple[list[Ask], str, str]:
    """The asks a ``battle`` action files: press or hold as a posture of one of the seat's
    pieces there, withdraw as its move (to the area named, else back the way it would be
    forced). Returns the asks, the label and the battle's area key; raises ``ValueError``."""
    key = _need(body, "area")
    try:
        decision = Decision(_need(body, "decision"))
    except ValueError:
        raise ValueError(f"The decision is one of {', '.join(DECISIONS)}.") from None
    b, side = _battle(state, seat, key)
    wake = _open_wake(state)
    if wake is not None and _decided(state, seat, side, wake):
        raise ValueError(DECIDED)
    f = _piece(state, seat, b, side)
    to_key = _maybe(body, "to")
    place = state.entities[b.area].name
    if decision is Decision.WITHDRAW:
        to = _area(state, to_key) if to_key is not None else None
        effect = MoveForce(force=f.feature_id, to=to, posture=Posture.WITHDRAW)
    else:
        effect = MoveForce(force=f.feature_id, posture=_POSTURE[decision])
    label = f"The battle at {place}: {decision.value}"
    return [Ask(ask=label, effect=effect)], label, key


def contingency_asks(state: State, seat: SeatId, body: Mapping[str, Any]) -> tuple[list[Ask], str]:
    """The asks a ``contingency`` action files: an engagement for one of the seat's own
    forces that keeps its rule and sets its standing order for a battle. Raises
    ``ValueError``."""
    from revisionist.core.realism import war_rules

    key = _need(body, "force")
    fid = FeatureId(object_id(state.campaign_id, "feature", key))
    f = state.features.get(fid)
    if f is None or not any(s == seat for s, _ in war_rules.commanders(state, fid)):
        raise ValueError(NOT_YOURS_FORCE)
    try:
        kind = ContingencyKind(_need(body, "kind"))
    except ValueError:
        raise ValueError(f"The contingency is one of {', '.join(CONTINGENCIES)}.") from None
    to_key = _maybe(body, "to")
    below = body.get("below")
    if below is not None and (isinstance(below, bool) or not isinstance(below, int)):
        raise ValueError("below is a number.")
    contingency = Contingency(
        kind=kind, to=_area(state, to_key) if to_key is not None else None, below=below
    )
    effect = SetEngagement(
        force=f.feature_id,
        zone=f.name,
        rule=f.engagement or Engagement.DEFEND,
        contingency=contingency,
    )
    label = f"{f.name}: {kind.value.replace('_', ' ')}"
    return [Ask(ask=label, effect=effect)], label


__all__ = [
    "CONTINGENCIES",
    "DECISIONS",
    "battle_asks",
    "block",
    "contingency_asks",
    "due",
    "sides_of",
]
