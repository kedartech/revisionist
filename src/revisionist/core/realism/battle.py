"""Battles that last several days, one round a day (BTL).

With ``battles`` switched on (it needs ``territories``), a battle opens in an area on the
day pieces of two powers at war stand in it: land against land in a territory, sea against
sea in a sea zone. The side that entered is the attacker and the side that stood there the
defender; there is one battle per area. An air piece does not fight: it supports its side
when the area lies within its kind's range. An envoy never fights.

One round is fought each world day the attacker presses, in the day walk, after the day's
arrivals and contacts. ``simulate`` is the one place the round, the losses, the break, the
lull and the end are written: a pure function of the two sides, a seed and a number of
days, so the walk and anything that later wants the odds call the same code. The walk seeds
each round by campaign, day, area and the sorted piece ids, never by filing order, and a
battle adds no stop to the clock.

A broken side is forced back one step (``territory.step``, cause forced) to the adjacent
area its side holds that lies the fewest steps from its capital, ties to the lowest key (a
sea piece: to the adjacent sea zone with no enemy in it nearest its capital); with nowhere
to go a piece is destroyed. A piece brought to strength 0 is out of play from that day
(``Feature.lost_on``). When no defender is left the attacker has won and the capture count
starts there (``holders.start_count``). An attacker that does not press for ``LULL_DAYS``
days in a row goes back to the area it came from when that borders the battle, else falls
back as a broken side does; with nowhere to go it stays, and the battle stays open.

The opening and the end each land one public news item; after every round each side's
commanders get a report with the steps each side lost, as contact showed them. The three
battle events are engine only: they carry both sides' true strengths and the draws.

Decisions and contingencies (BDC). In each wake a side may give one decision for its
battle: press, hold or withdraw, as the posture effect on one of its pieces there
(``land_posture``); reinforce is a move order into the area, whose pieces join their side
on the day they stand there. A decision stands until changed and applies from the first
round on or after the day it lands; with none, the attacker presses and the defender
holds. Each piece carries a contingency, set through the engagement effect
(``land_contingency``): hold, hold at all costs, fall back when outnumbered, or withdraw
below a strength. Contingencies are checked at the start of every round, in the day walk,
with no player. ``battle_decided`` records a decision and the pieces that join a side.
Two decisions for one side due in one pass, from one seat or from several (allies join a
side), settle by content, never by filing order (``twins``, BDS).

Head-on moves (HON). When pieces of two powers at war would each complete a step into the
other's area on the same day, neither enters: a meeting battle opens on that border
(``head_on`` finds them, the movement walk holds them), each side standing in its own
area. It has no terrain or own-ground bonus; its rounds otherwise follow the battle rules.
The side that breaks, withdraws or is gone keeps to its own area with its move dropped;
the other completes its step, and where enemy pieces remain a normal battle opens there
with it as the attacker. Borders met head-on on one day are settled in the order of the
lowest piece id moving across each, which no player sets; a border with an area already in
a battle is no meeting. A battle that opens drops the moves of the pieces on its sides, so
a step due later from a battle's area is cancelled.

History steps aside (HSA). A piece on a side of a battle, whether it stood there, stepped
in or joined later, drops the moves the record still had for it (``Feature.legs``) on the
first day it is in the battle, before the round; from then on only orders move it.

Kinds in battle (KBA). With ``kinds_in_battle`` on, each piece adds its strength plus its
kind's attack figure less 3 when its side attacks, or its defence figure less 3 when it
defends, the figure first changed by the terrain fought on (none on a meeting's border) and
by what is on the other side (``kinds.figure``); a piece never adds less than nothing. A kind
that strikes supports its side as an air piece in range does, from as many steps off as it
strikes, and adds no strength to a fight it stands in, where alone it takes losses. A kind
that covers cancels the other side's air support within its reach. A kind that may not
attack never opens a battle: it may step in where an enemy stands, and the enemy may attack
it from the next day. A kind that does not hold ground takes no territory by standing in it
(``holds_ground``). The loss still falls on the strongest piece, ties to the lowest id.
"""

import hashlib
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, NamedTuple, cast

from pydantic import Field, model_validator

from revisionist.core._base import Model
from revisionist.core.ids import DocumentId, EntityId, FeatureId, SeatId, derived_id

if TYPE_CHECKING:
    from revisionist.core.events import Payload
    from revisionist.core.realism.effect import Posture, SetEngagement
    from revisionist.core.realism.geography import Feature
    from revisionist.core.realism.kinds import PieceKind
    from revisionist.core.state import State, View

DRAW_TOP = 2  # [proposed] plan, BTL Defaults: a draw of 0 to 2 a side
DOUBLE_MARGIN = 3  # [proposed] plan, BTL Defaults: a margin of 3 doubles the loss
LULL_DAYS = 3  # [proposed] plan, BTL Defaults
"""Days in a row without the attacker pressing after which it goes back."""
AIR_SUPPORT = 1  # [proposed] plan, BTL Defaults
OUTNUMBERED = 1.5  # [proposed] plan, BDC Defaults
"""A falling-back contingency fires when the enemy in contact is this many times its side."""
LINE = 60


# --- the stored battle -----------------------------------------------------------


class Decision(StrEnum):
    """A side's decision for its battle (BDC). Reinforce is a move order, not stored."""

    PRESS = "press"
    HOLD = "hold"
    WITHDRAW = "withdraw"


class BattleSide(Model):
    """One side of a battle: its leading nation, the pieces it brought (in id order), the
    strength they brought and the steps they have lost; the decision in force and the wake
    it was given (BDC)."""

    nation: EntityId
    pieces: tuple[FeatureId, ...] = Field(min_length=1)
    brought: int = Field(ge=1)
    lost: int = Field(default=0, ge=0)
    decision: Decision | None = None
    """The side's decision in force. None: none given (the attacker presses, the
    defender holds)."""
    decided_wake: int | None = Field(default=None, ge=0)
    """The wake the decision in force was given in."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"decision", "decided_wake"})

    @model_validator(mode="after")
    def _decided(self) -> "BattleSide":
        if (self.decision is None) != (self.decided_wake is None):
            raise ValueError("a decision and its wake go together")
        return self


class Battle(Model):
    """A battle open in an area. Engine only."""

    area: EntityId
    opened: date
    attacker: BattleSide
    defender: BattleSide
    came_from: dict[FeatureId, EntityId] = Field(default_factory=dict)
    """Each attacking piece that stepped in on the opening day: the area it came from."""
    rounds: int = Field(default=0, ge=0)
    pressed_on: date | None = None
    """The last day a round was fought; None before the first."""
    meeting: bool = False
    """A meeting battle on a border (HON): two sides that stepped into each other's areas
    on one day, each standing in its own."""
    second: EntityId | None = None
    """A meeting battle: the other area of the border; ``area`` is the first."""
    attacker_in: EntityId | None = None
    """A meeting battle: the area of the two the attacker stands in."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"meeting", "second", "attacker_in"})

    @model_validator(mode="after")
    def _border(self) -> "Battle":
        if self.meeting != (self.second is not None) or self.meeting != (
            self.attacker_in is not None
        ):
            raise ValueError("a meeting battle, and only one, names its second area and sides")
        if self.second is not None and (
            self.second == self.area or self.attacker_in not in (self.area, self.second)
        ):
            raise ValueError("a meeting battle's sides stand in its two areas")
        return self


class Meet(NamedTuple):
    """A border met head-on today (HON): its two areas in id order, the attacker (the
    nation of the lowest-id mover with an enemy moving the other way), the defender, the
    area the attacker stands in, and the movers held on both sides."""

    border: tuple[EntityId, EntityId]
    attacker: EntityId
    defender: EntityId
    attacker_in: EntityId
    movers: tuple[FeatureId, ...]


class Ending(StrEnum):
    WON = "won"
    """No defender is left: the attacker has won."""
    HELD = "held"
    """No attacker is left, or the attacker broke."""
    LULL = "lull"
    """The attacker stopped pressing for ``LULL_DAYS`` days and went back."""
    CEASED = "ceased"
    """The two powers stopped fighting, by an armistice or an end to their war (PEA): each
    side holds where it stands, and neither has won."""


# --- the pure rule ----------------------------------------------------------------


class Fighter(NamedTuple):
    fid: str
    """The piece's feature id."""
    strength: int


class SideIn(NamedTuple):
    """One side as ``simulate`` reads it."""

    fighters: tuple[Fighter, ...]
    brought: int
    lost: int = 0
    own_ground: bool = False
    """The area is held by this side (counts for a defender only)."""
    air: bool = False
    """An air piece of this side's own has the area in range."""
    supplied: bool = True


class Sides(NamedTuple):
    attacker: SideIn
    defender: SideIn
    defence: int = 0
    """The area's terrain defence (counts for the defender only)."""
    presses: bool = True
    """Whether the attacker presses on the days simulated."""
    lull: int = 0
    """Days in a row the attacker has already not pressed."""
    edges: tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]] = ((), ())
    """Each side's pieces whose kind changes what they add (KBA): by piece id, the kind's
    figure less 3."""
    strikers: frozenset[str] = frozenset()
    """The pieces of a kind that strikes (KBA): they add no strength, and take losses."""


class Round(NamedTuple):
    day: int
    """Which of the simulated days, from 0."""
    scores: tuple[int, int]
    """The attacker's score, then the defender's."""
    draws: tuple[int, int]
    hits: tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]
    """Each side's steps lost this round, by piece, in the order taken."""

    def lost(self, side: int) -> int:
        return sum(n for _, n in self.hits[side])


class Played(NamedTuple):
    rounds: tuple[Round, ...]
    sides: Sides
    """The sides after the days played."""
    ending: Ending | None
    """None while the battle goes on."""
    broken: int | None
    """The side that broke and is forced back: 0 the attacker, 1 the defender."""


def draws(seed: str, day: int) -> tuple[int, int]:
    """The attacker's and the defender's draws, each 0 to ``DRAW_TOP``, on day ``day``."""
    out = []
    for side in ("attacker", "defender"):
        digest = hashlib.blake2b(f"{seed}\x1f{day}\x1f{side}".encode(), digest_size=8).digest()
        out.append(int.from_bytes(digest, "big") % (DRAW_TOP + 1))
    return out[0], out[1]


def score(
    side: SideIn,
    draw: int,
    defending: bool,
    defence: int,
    edges: Mapping[str, int] | None = None,
    strikers: Collection[str] = (),
) -> int:
    """A side's score for a round: its strength, the defender's terrain and own ground,
    air support, supply and the draw. With ``edges`` (KBA), a piece adds its strength plus
    its edge, never less than nothing; one of ``strikers`` adds nothing."""
    edge = edges or {}
    total = draw + sum(
        0 if f.fid in strikers else max(0, f.strength + edge.get(f.fid, 0)) for f in side.fighters
    )
    if defending:
        total += defence + (1 if side.own_ground else 0)
    if side.air:
        total += AIR_SUPPORT
    if not side.supplied:
        total -= 1
    return total


def losses(attacker: int, defender: int) -> tuple[int, int]:
    """The steps each side loses for a round's two scores: the lower loses one, two when
    the margin is ``DOUBLE_MARGIN`` or more; on a tie each loses one."""
    if attacker == defender:
        return 1, 1
    loss = 2 if abs(attacker - defender) >= DOUBLE_MARGIN else 1
    return (loss, 0) if attacker < defender else (0, loss)


def _hit(side: SideIn, steps: int) -> tuple[SideIn, tuple[tuple[str, int], ...]]:
    """``side`` after losing ``steps``, each from its strongest piece then (ties to the
    lowest id); a piece at 0 leaves the fight."""
    fighters = list(side.fighters)
    taken: dict[str, int] = {}
    for _ in range(steps):
        if not fighters:
            break
        top = min(fighters, key=lambda f: (-f.strength, f.fid))
        i = fighters.index(top)
        taken[top.fid] = taken.get(top.fid, 0) + 1
        if top.strength > 1:
            fighters[i] = top._replace(strength=top.strength - 1)
        else:
            del fighters[i]
    lost = sum(taken.values())
    return side._replace(fighters=tuple(fighters), lost=side.lost + lost), tuple(taken.items())


def broken(side: SideIn) -> bool:
    """Whether a side has lost half the strength it brought, rounded up."""
    return side.lost >= -(-side.brought // 2)


def simulate(sides: Sides, seed: str, days: int) -> Played:
    """Play up to ``days`` days of a battle from ``sides``, drawing from ``seed``; stop on
    the day it ends. A pure function: the same arguments give the same result."""
    rounds: list[Round] = []
    for d in range(days):
        if not sides.presses:
            sides = sides._replace(lull=sides.lull + 1)
            if sides.lull >= LULL_DAYS:
                return Played(tuple(rounds), sides, Ending.LULL, None)
            continue
        att, dfn = sides.attacker, sides.defender
        da, dd = draws(seed, d)
        ea, ed = dict(sides.edges[0]), dict(sides.edges[1])
        sa = score(att, da, False, sides.defence, ea, sides.strikers)
        sd = score(dfn, dd, True, sides.defence, ed, sides.strikers)
        lost_a, lost_d = losses(sa, sd)
        att, ha = _hit(att, lost_a)
        dfn, hd = _hit(dfn, lost_d)
        sides = sides._replace(attacker=att, defender=dfn, lull=0)
        rounds.append(Round(d, (sa, sd), (da, dd), (ha, hd)))
        if not att.fighters:
            return Played(tuple(rounds), sides, Ending.HELD, None)
        if not dfn.fighters:
            return Played(tuple(rounds), sides, Ending.WON, None)
        if broken(att):
            return Played(tuple(rounds), sides, Ending.HELD, 0)
        if broken(dfn):
            return Played(tuple(rounds), sides, Ending.WON, 1)
    return Played(tuple(rounds), sides, None, None)


# --- the battle in the game -------------------------------------------------------


def on(state: "State") -> bool:
    """Whether battles act in this game: the territory rules on, and ``battles``."""
    from revisionist.core.realism import territory
    from revisionist.core.state import Rule

    return territory.on(state) and Rule.BATTLES in state.rules


def _clip(text: str) -> str:
    return text if len(text) <= LINE else text[: LINE - 1] + "\N{HORIZONTAL ELLIPSIS}"


def _area(state: "State", f: "Feature") -> EntityId | None:
    from revisionist.core.realism import kinds, territory

    domain = kinds.domain(state, f)
    return None if domain is None else territory.area_of(state, f.places[0], domain)


def _nation(state: "State", f: "Feature") -> EntityId:
    from revisionist.core.realism import territory

    own = territory.nation(state, f.side)
    assert own is not None, "a piece that fights belongs to a side"
    return own


def _fights_in(state: "State", f: "Feature") -> EntityId | None:
    """The area a piece can fight in: a land piece's territory or a sea piece's sea zone,
    when it is in play with a side and a strength; else None."""
    from revisionist.core.realism import kinds
    from revisionist.core.realism.geography import FeatureKind, in_play
    from revisionist.core.realism.kinds import Domain

    board = state.map
    if board is None or f.kind is not FeatureKind.PIECE or f.side is None:
        return None
    if not in_play(f) or f.tier < 1:
        return None
    domain, area = kinds.domain(state, f), _area(state, f)
    if area is None:
        return None
    if domain is Domain.LAND and area in {t.area for t in board.territories}:
        return area
    if domain is Domain.SEA and area in {z.area for z in board.sea_zones}:
        return area
    return None


def fighting_area(state: "State", f: "Feature") -> EntityId | None:
    """The area ``f`` can fight in (``fighting``'s rule), or None."""
    return _fights_in(state, f)


def fighting(state: "State") -> dict[EntityId, list["Feature"]]:
    """The pieces that can fight, by the area they stand in: land pieces in a territory and
    sea pieces in a sea zone, in play, with a side and a strength, in id order."""
    assert state.map is not None
    out: dict[EntityId, list[Feature]] = {}
    for f in sorted(state.features.values(), key=lambda x: x.feature_id):
        area = _fights_in(state, f)
        if area is not None:
            out.setdefault(area, []).append(f)
    return out


def at(state: "State", area: EntityId) -> Battle | None:
    """The battle ``area`` is in: one open there, or a meeting battle it is the second area
    of; None when there is none."""
    found = state.battles.get(area)
    if found is not None:
        return found
    return next((b for b in state.battles.values() if b.second == area), None)


def _areas(battle: Battle) -> tuple[EntityId, ...]:
    return (battle.area,) if battle.second is None else (battle.area, battle.second)


def _side_area(battle: Battle, i: int) -> EntityId:
    """Where side ``i`` (0 the attacker) stands: the battle's area, or in a meeting battle
    the attacker's area and the other one of the border."""
    if not battle.meeting or battle.second is None or battle.attacker_in is None:
        return battle.area
    if i == 0:
        return battle.attacker_in
    return battle.second if battle.attacker_in == battle.area else battle.area


def _index(battle: Battle, side: BattleSide) -> int:
    return 0 if side.nation == battle.attacker.nation else 1


def busy(state: "State") -> set[EntityId]:
    """Every area in an open battle, a meeting battle's two."""
    return {a for b in state.battles.values() for a in _areas(b)}


def pinned(state: "State") -> set[FeatureId]:
    """The pieces on a side of an open meeting battle standing in their side's area: they
    do not step while it lasts."""
    out: set[FeatureId] = set()
    for b in state.battles.values():
        if b.meeting:
            for side in (b.attacker, b.defender):
                out |= {f.feature_id for f in _present(state, b, side)}
    return out


def closed(state: "State", met: Sequence[Meet]) -> dict[EntityId, EntityId]:
    """Each area of a meeting battle, open or opening today, with the nation of the side
    standing there: a piece at war with it does not step in while the meeting lasts."""
    out: dict[EntityId, EntityId] = {}
    for b in state.battles.values():
        if b.meeting:
            for i, side in enumerate((b.attacker, b.defender)):
                out[_side_area(b, i)] = side.nation
    for m in met:
        out[m.attacker_in] = m.attacker
        out[m.border[1] if m.attacker_in == m.border[0] else m.border[0]] = m.defender
    return out


def meetings(state: "State", movers: Sequence[tuple["Feature", EntityId, EntityId]]) -> list[Meet]:
    """The borders met head-on (rule 1), from ``movers``: each piece whose next step falls
    due today, with the area it fights in and the area it steps into. A border is met when a
    piece steps across it each way and the two powers are at war. Borders are settled in the
    order of the lowest piece id moving across each (rule 5); one with an area already in a
    battle, or in a meeting settled before it, is no meeting and its pieces move as moves
    do. Filing order is read nowhere."""
    from revisionist.core.realism.war import hostile

    if not on(state):
        return []
    used = busy(state)
    across: dict[frozenset[EntityId], list[tuple[Feature, EntityId, EntityId]]] = {}
    for f, frm, to in sorted(movers, key=lambda m: m[0].feature_id):
        if frm != to and frm not in used and to not in used:
            across.setdefault(frozenset((frm, to)), []).append((f, frm, to))
    out: list[Meet] = []
    for border, ms in sorted(across.items(), key=lambda kv: kv[1][0][0].feature_id):
        if border & used:
            continue
        nation = {f.feature_id: _nation(state, f) for f, _, _ in ms}
        lead = next(
            (
                (m, o)
                for m in ms
                for o in ms
                if o[1] != m[1]
                and hostile(state, nation[m[0].feature_id], nation[o[0].feature_id])
                and may_attack(state, m[0])
            ),
            None,
        )
        if lead is None:
            continue
        a, d = nation[lead[0][0].feature_id], nation[lead[1][0].feature_id]
        a_in = lead[0][1]
        held = tuple(
            f.feature_id
            for f, frm, _ in ms
            if (frm == a_in and _with(state, nation[f.feature_id], a, d))
            or (frm != a_in and _with(state, nation[f.feature_id], d, a))
        )
        first, second = sorted(border)
        out.append(Meet((first, second), a, d, a_in, held))
        used |= border
    return out


def _meeting(state: "State", m: Meet, here: dict[EntityId, list["Feature"]], day: date) -> Battle:
    """The meeting battle that opens on ``m``'s border today: each side every piece of its
    coalition that can fight in its own area."""
    d_in = m.border[1] if m.attacker_in == m.border[0] else m.border[0]
    ours = [
        f
        for f in here.get(m.attacker_in, [])
        if _with(state, _nation(state, f), m.attacker, m.defender)
    ]
    theirs = [
        f for f in here.get(d_in, []) if _with(state, _nation(state, f), m.defender, m.attacker)
    ]
    return Battle(
        area=m.border[0],
        opened=day,
        attacker=BattleSide(
            nation=m.attacker,
            pieces=tuple(f.feature_id for f in ours),
            brought=sum(f.tier for f in ours),
        ),
        defender=BattleSide(
            nation=m.defender,
            pieces=tuple(f.feature_id for f in theirs),
            brought=sum(f.tier for f in theirs),
        ),
        meeting=True,
        second=m.border[1],
        attacker_in=m.attacker_in,
    )


def _still(piece: "Feature", day: date) -> "Feature":
    """The piece standing where it is from ``day``, its move dropped."""
    return piece.model_copy(
        update={
            "path": (),
            "step_due": None,
            "bound_for": None,
            "arrives": None,
            "as_of": max(day, piece.as_of),
        }
    )


def _pin(state: "State", battle: Battle, keep: Iterable[FeatureId], day: date) -> list["Payload"]:
    """A battle opening drops the moves of the pieces on its sides (rule 4), but for
    ``keep``: a meeting's movers keep theirs, to complete the step if they win."""
    from revisionist.core import events as ev

    kept = set(keep)
    out: list[Payload] = []
    for side in (battle.attacker, battle.defender):
        for f in _present(state, battle, side):
            if f.feature_id not in kept and (f.path or f.bound_for is not None):
                out.append(ev.FeatureSet(feature=_still(f, day)))
    return out


def _opening(
    before: "State", state: "State", area: EntityId, here: Sequence["Feature"], day: date
) -> Battle | None:
    """The battle that opens in ``area`` today, or None when no two powers there are at
    war with no armistice between them (PEA). The attacker is the nation of the first piece
    (in id order) that stepped in today with an enemy there that did not; with none, the
    first nation (in id order) at war with the area's holder, else the nation of the first
    piece. The defender is the nation of the first enemy piece that stood there, else of the
    first enemy piece. Each side takes the pieces of nations at war with the other side and
    not with it."""
    from revisionist.core.realism import territory
    from revisionist.core.realism.war import hostile

    nation = {f.feature_id: _nation(state, f) for f in here}
    if not any(hostile(state, a, b) for a in nation.values() for b in nation.values()):
        return None
    can = {f.feature_id: may_attack(state, f) for f in here}
    was = {
        f.feature_id: _area(before, b)
        for f in here
        if (b := before.features.get(f.feature_id)) is not None
    }
    entered = [f for f in here if was.get(f.feature_id) != area]
    stood = [f for f in here if was.get(f.feature_id) == area]
    facing = [
        f
        for f in entered
        if any(hostile(state, nation[f.feature_id], nation[g.feature_id]) for g in stood)
    ]
    attacker = next((nation[f.feature_id] for f in facing if can[f.feature_id]), None)
    if attacker is None and facing:
        return None  # KBA rule 4: a kind that may not attack steps in and opens no battle
    if attacker is None:
        held = territory.holder(state, area)
        able = {nation[f.feature_id] for f in here if can[f.feature_id]}
        foes = sorted(n for n in able if held is not None and hostile(state, n, held))
        lead = next((f for f in here if can[f.feature_id]), None)
        if foes:
            attacker = foes[0]
        elif lead is not None:
            attacker = nation[lead.feature_id]
        else:
            return None
    enemies = [f for f in here if hostile(state, attacker, nation[f.feature_id])]
    if not enemies:
        return None
    defender = nation[([f for f in enemies if f in stood] or enemies)[0].feature_id]

    ours = [f for f in here if _with(state, nation[f.feature_id], attacker, defender)]
    theirs = [f for f in here if _with(state, nation[f.feature_id], defender, attacker)]
    came = {
        f.feature_id: w for f in ours if f in entered and (w := was.get(f.feature_id)) is not None
    }
    return Battle(
        area=area,
        opened=day,
        attacker=BattleSide(
            nation=attacker,
            pieces=tuple(f.feature_id for f in ours),
            brought=sum(f.tier for f in ours),
        ),
        defender=BattleSide(
            nation=defender,
            pieces=tuple(f.feature_id for f in theirs),
            brought=sum(f.tier for f in theirs),
        ),
        came_from=came,
    )


def _with(state: "State", n: EntityId, own: EntityId, other: EntityId) -> bool:
    """Whether nation ``n`` fights on ``own``'s side against ``other``: it is ``own``, or
    at war with ``other`` and not with ``own``."""
    from revisionist.core.realism.war import hostile

    return n == own or (hostile(state, n, other) and not hostile(state, n, own))


def _present(state: "State", battle: Battle, side: BattleSide) -> list["Feature"]:
    """The side's pieces still in play with strength, standing in the battle's area."""
    from revisionist.core.realism.geography import in_play

    where = _side_area(battle, _index(battle, side))
    out = []
    for fid in side.pieces:
        f = state.features.get(fid)
        if f is not None and in_play(f) and f.tier >= 1 and _area(state, f) == where:
            out.append(f)
    return out


def _air(state: "State", own: EntityId, area: EntityId) -> bool:
    """Whether an air piece of ``own``'s, in play, has ``area`` within its kind's range."""
    from revisionist.core.realism import kinds, territory
    from revisionist.core.realism.geography import FeatureKind, in_play
    from revisionist.core.realism.kinds import Domain

    board = state.map
    assert board is not None
    for f in sorted(state.features.values(), key=lambda x: x.feature_id):
        if f.kind is not FeatureKind.PIECE or f.side is None or not in_play(f):
            continue
        kind = kinds.of(state, f)
        if kind is None or kind.domain is not Domain.AIR:
            continue
        if territory.nation(state, f.side) != own or (frm := _area(state, f)) is None:
            continue
        far = territory.steps_from(board, "air", [frm]).get(area)
        if far is not None and far <= (kind.range_steps or 0):
            return True
    return False


def _supplied(state: "State", pieces: Sequence["Feature"]) -> bool:
    """A side is out of supply when every piece of it is (SUP); with supply off, in."""
    from revisionist.core.realism import supply

    found = [supply.status(state, f) for f in pieces]
    return any(s is None or s.supplied for s in found)


def _terrain(state: "State", area: EntityId) -> str | None:
    """The terrain key of ``area``."""
    board = state.map
    assert board is not None
    terrain = {t.area: t.terrain for t in board.territories}
    terrain |= {z.area: z.terrain for z in board.sea_zones}
    return terrain.get(area)


def _defence(state: "State", area: EntityId) -> int:
    board = state.map
    assert board is not None
    key = _terrain(state, area)
    return next((t.defence for t in board.terrain if t.key == key), 0)


# --- kinds in battle (KBA) ----------------------------------------------------------


def kinds_count(state: "State") -> bool:
    """Whether a piece's kind counts in this game's battles: ``kinds_in_battle`` on."""
    from revisionist.core.state import Rule

    return Rule.KINDS_IN_BATTLE in state.rules


def may_attack(state: "State", f: "Feature") -> bool:
    """Whether ``f`` may open a battle (rule 4): with the switch off, or a kind that may
    attack, or a piece of no kind."""
    from revisionist.core.realism import kinds

    kind = kinds.of(state, f)
    return not kinds_count(state) or kind is None or kind.may_attack


def holds_ground(state: "State", f: "Feature") -> bool:
    """Whether ``f`` takes a territory by standing in it (rule 5): with the switch off, or
    a kind that holds ground, or a piece of no kind."""
    from revisionist.core.realism import kinds

    kind = kinds.of(state, f)
    return not kinds_count(state) or kind is None or kind.holds_ground


def _reach(kind: "PieceKind") -> int | None:
    """The steps from a fight within which a piece of ``kind`` supports it: an air kind's
    range (none: its own area) or its strike steps, whichever is the longer; another kind's
    strike steps; None for a kind that gives no support."""
    from revisionist.core.realism.kinds import Domain

    found = [n for n in (kind.strike_steps,) if n is not None]
    if kind.domain is Domain.AIR:
        found.append(kind.range_steps or 0)
    return max(found) if found else None


def _within(
    state: "State", own: EntityId, area: EntityId, reach: "Callable[[PieceKind], int | None]"
) -> list["Feature"]:
    """The pieces of ``own``'s, in play, in id order, whose kind's ``reach`` takes in
    ``area`` by air steps from the area each stands in."""
    from revisionist.core.realism import kinds, territory
    from revisionist.core.realism.geography import FeatureKind, in_play

    board = state.map
    assert board is not None
    out: list[Feature] = []
    for f in sorted(state.features.values(), key=lambda x: x.feature_id):
        if f.kind is not FeatureKind.PIECE or f.side is None or not in_play(f):
            continue
        kind = kinds.of(state, f)
        steps = None if kind is None else reach(kind)
        if steps is None or territory.nation(state, f.side) != own:
            continue
        if (frm := _area(state, f)) is None:
            continue
        far = territory.steps_from(board, "air", [frm]).get(area)
        if far is not None and far <= steps:
            out.append(f)
    return out


def _support(state: "State", own: EntityId, area: EntityId) -> list["Feature"]:
    """``own``'s pieces that give air support in ``area`` (rule 2): an air piece within
    its range, and a striking piece within its strike steps."""
    return _within(state, own, area, _reach)


def _covers(state: "State", own: EntityId, area: EntityId) -> bool:
    """Whether a covering piece of ``own``'s has ``area`` within its reach (rule 3): its
    range or strike steps, else its own area only."""
    return bool(_within(state, own, area, lambda k: (_reach(k) or 0) if k.covers else None))


def _with_kinds(
    state: "State",
    battle: Battle,
    pieces: tuple[Sequence["Feature"], Sequence["Feature"]],
    sides: Sides,
) -> Sides:
    """With ``kinds_in_battle`` on, ``sides`` as the kinds that fight read them: each
    fighter's figure less 3 (the attacker's attack, the defender's defence) changed by the
    terrain and by what the other side brings, its fighters and the pieces that support
    it; a striking kind marked; each side's air support from its supporting pieces unless
    the other side covers. ``pieces`` are the sides' fighters in ``sides``' order. With the
    switch off, ``sides`` as they are."""
    from revisionist.core.realism import kinds
    from revisionist.core.realism.kinds import Condition, Figure

    if not kinds_count(state):
        return sides
    ins = (sides.attacker, sides.defender)
    nations = (battle.attacker.nation, battle.defender.nation)
    areas = (_side_area(battle, 0), _side_area(battle, 1))
    support = tuple(_support(state, nations[i], areas[i]) for i in (0, 1))
    terrain = None if battle.meeting else _terrain(state, battle.area)
    out: list[SideIn] = []
    edges: list[tuple[tuple[str, int], ...]] = []
    strikers: set[str] = set()
    for i, which in enumerate((Figure.ATTACK, Figure.DEFENCE)):
        named = kinds.facing(state, (*pieces[1 - i], *support[1 - i]))
        holds = {Condition.NO_ENEMY_AIR} if not support[1 - i] else set()
        if not ins[1 - i].supplied:
            holds.add(Condition.ENEMY_OUT_OF_SUPPLY)
        edge: list[tuple[str, int]] = []
        for f in pieces[i]:
            kind = kinds.of(state, f)
            if kind is None:
                continue
            value = kinds.figure(kind, which, terrain=terrain, facing=named, holds=holds)
            edge.append((str(f.feature_id), value - kinds.FIGURE))
            if kind.strike_steps is not None:
                strikers.add(str(f.feature_id))
        edges.append(tuple(edge))
        air = bool(support[i]) and not _covers(state, nations[1 - i], areas[i])
        out.append(ins[i]._replace(air=air))
    return sides._replace(
        attacker=out[0],
        defender=out[1],
        edges=(edges[0], edges[1]),
        strikers=frozenset(strikers),
    )


def _side_in(
    state: "State", battle: Battle, side: BattleSide, pieces: Sequence["Feature"]
) -> SideIn:
    from revisionist.core.realism import territory

    where = _side_area(battle, _index(battle, side))
    return SideIn(
        fighters=tuple(Fighter(str(f.feature_id), f.tier) for f in pieces),
        brought=side.brought,
        lost=side.lost,
        own_ground=not battle.meeting and territory.holder(state, battle.area) == side.nation,
        air=_air(state, side.nation, where),
        supplied=_supplied(state, pieces),
    )


def presses(side: BattleSide) -> bool:
    """The attacker presses unless its decision in force is hold or withdraw; with no
    decision ever given it presses (BDC rule 7)."""
    return side.decision in (None, Decision.PRESS)


def pressing(battle: Battle, i: int) -> bool:
    """Whether side ``i`` (0 the attacker, 1 the defender) presses: the attacker as
    ``presses`` says, the defender only on a press decision (with none, it holds)."""
    if i == 0:
        return presses(battle.attacker)
    return battle.defender.decision is Decision.PRESS


def seed(state: "State", area: EntityId, day: date, pieces: Iterable[FeatureId]) -> str:
    """A round's seed: the campaign, the day, the area and the sorted piece ids."""
    raw = "\x1f".join((str(state.campaign_id), day.isoformat(), str(area), *sorted(pieces)))
    return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()


def _may_go(world: "State | View", piece: "Feature", area: EntityId, to: EntityId) -> bool:
    """Whether ``piece`` may go back from ``area`` to ``to``: an area that borders it for
    the piece's domain and is held by its side or an ally (a sea zone: with no enemy sea
    piece in it, which only the truth tells; a seat's view reads public data only)."""
    from revisionist.core.realism import kinds, territory
    from revisionist.core.realism.kinds import Domain
    from revisionist.core.state import State

    board, domain = world.map, kinds.domain(world, piece)
    if board is None or domain is None or to not in territory.neighbours(board, area, domain):
        return False
    if domain is Domain.SEA:
        return not isinstance(world, State) or _open_to(world, piece, to)
    truth = cast("State", world)  # the helpers read the public map, holders and wars only
    own = territory.nation(truth, piece.side)
    held = territory.holder(world, to)
    return (
        own is not None and held is not None and (held == own or territory.allied(truth, own, held))
    )


def fall_back(world: "State | View", piece: "Feature", area: EntityId) -> EntityId | None:
    """Where a piece is forced back from ``area``: the area its contingency names when it
    may go there (BDC), else the adjacent area its side holds (a sea piece: an adjacent sea
    zone with no enemy sea piece) that lies the fewest steps from its capital, ties to the
    lowest key. None when there is nowhere to go. Callable with a seat's ``View`` for the
    odds: it then reads public data only (the board, holders, capitals and wars)."""
    from revisionist.core.realism import kinds, territory
    from revisionist.core.realism.kinds import Domain
    from revisionist.core.state import State

    named = piece.contingency.to if piece.contingency is not None else None
    if named is not None and _may_go(world, piece, area, named):
        return named
    board = world.map
    domain = kinds.domain(world, piece)
    truth = cast("State", world)  # area_of and nation read the public board and entities
    own = territory.nation(truth, piece.side)
    if board is None or domain is None or own is None:
        return None
    near = territory.neighbours(board, area, domain)
    if domain is Domain.SEA:  # [proposed] a sea zone with no enemy sea piece
        if isinstance(world, State):
            near = tuple(a for a in near if _open_to(world, piece, a))
    else:
        near = tuple(a for a in near if territory.holder(world, a) == own)
    keys = {t.area: t.key for t in board.territories} | {z.area: z.key for z in board.sea_zones}
    capital = board.capitals.get(own)
    home = None if capital is None else territory.area_of(truth, capital, domain)
    far = territory.steps_from(board, domain, [home]) if home is not None else {}
    ranked = sorted((far.get(a, len(keys) + 1), keys.get(a, a), a) for a in near)
    return ranked[0][2] if ranked else None


def _went_back(state: "State", battle: Battle, piece: "Feature") -> EntityId | None:
    """Where an attacker goes back to after the lull: the area it came from, when that
    borders the battle's area for its domain and holds no enemy piece; else None."""
    from revisionist.core.realism import kinds, territory

    back = battle.came_from.get(piece.feature_id)
    domain = kinds.domain(state, piece)
    if back is None or domain is None or state.map is None:
        return None
    if back not in territory.neighbours(state.map, battle.area, domain):
        return None
    return back if _open_to(state, piece, back) else None


def _open_to(state: "State", piece: "Feature", to: EntityId) -> bool:
    """Whether an area holds no piece at war with ``piece``'s side that can fight there."""
    from revisionist.core.realism.war import hostile

    own = _nation(state, piece)
    return not any(hostile(state, own, _nation(state, f)) for f in fighting(state).get(to, []))


def _sent_back(
    state: "State", piece: "Feature", area: EntityId, to: EntityId | None, day: date
) -> list["Payload"]:
    """The piece forced one step to ``to`` (``piece_stepped``, cause forced), its course
    dropped; destroyed (out of play from ``day``) when ``to`` is None."""
    from revisionist.core import events as ev
    from revisionist.core.realism import territory

    still = piece.model_copy(
        update={
            "places": (area,),
            "path": (),
            "step_due": None,
            "bound_for": None,
            "arrives": None,
            "as_of": max(day, piece.as_of),
        }
    )
    if to is None:
        return [ev.FeatureSet(feature=still.model_copy(update={"lost_on": day}))]
    moved, stepped = territory.step(state, still, to, day, territory.StepCause.FORCED)
    return [ev.FeatureSet(feature=moved), stepped]


def news_id(state: "State", battle: Battle, what: str) -> str:
    return derived_id(state.campaign_id, "battle", battle.area, battle.opened.isoformat(), what)


def _news(state: "State", battle: Battle, day: date, ending: Ending | None) -> "Payload":
    """The public news item for a battle's opening (``ending`` None) or its end."""
    from revisionist.core import events as ev
    from revisionist.core.realism.document import BodyField
    from revisionist.core.realism.war import NewsEvent, NewsTopic

    place = state.entities[battle.area].name
    a = state.entities[battle.attacker.nation].name
    d = state.entities[battle.defender.nation].name
    headline = {
        None: f"Battle at {place}: {a} attacks {d}",
        Ending.WON: f"Battle at {place} ends: {a} has won",
        Ending.HELD: f"Battle at {place} ends: {d} holds",
        Ending.LULL: f"Battle at {place} ends: {a} draws off",
        Ending.CEASED: f"Battle at {place} ends: {a} and {d} cease fighting",
    }[ending]
    return ev.NewsReported(
        news=NewsEvent(
            news_id=news_id(
                state,
                battle,
                ("meeting " if battle.meeting else "") + ("opened" if ending is None else "ended"),
            ),
            on=day,
            topic=NewsTopic.EVENT,  # [proposed] no topic is kept for battles
            subject=battle.attacker.nation,
            obj=battle.defender.nation,
            facts=(
                BodyField(label="Place", value=_clip(place)),
                BodyField(label="Powers", value=_clip(f"{a} and {d}")),
            ),
            headline=_clip(headline),
        )
    )


def commanders(state: "State", side: BattleSide) -> list[SeatId]:
    """The seats that command any of the side's pieces; with none, every seat with a desk
    whose person belongs to the side's nation."""
    from revisionist.core.realism import holders, war_rules

    seats = sorted({s for fid in side.pieces for s, _ in war_rules.commanders(state, fid)})
    return seats or list(holders.holding_seats(state, side.nation))


def report_id(state: "State", battle: Battle, day: date, seat: SeatId) -> DocumentId:
    return DocumentId(derived_id(state.campaign_id, "battle", battle.area, day.isoformat(), seat))


def _reports(
    state: "State", battle: Battle, day: date, number: int, lost: tuple[int, int]
) -> list["Payload"]:
    """After a round: each commander of each side gets a report of it, with the steps its
    side lost and the steps it saw the enemy lose. Never a strength."""
    from revisionist.core import events as ev
    from revisionist.core.realism.card import ChannelKind
    from revisionist.core.realism.document import (
        BodyField,
        Classification,
        DocumentKind,
        DocumentTruth,
        DocumentView,
    )
    from revisionist.core.visibility import private_to

    place = state.entities[battle.area].name
    out: list[Payload] = []
    for i, side in enumerate((battle.attacker, battle.defender)):
        for seat in commanders(state, side):
            doc_id = report_id(state, battle, day, seat)
            if doc_id in state.documents:
                continue
            out.append(
                ev.DocumentIssued(
                    document=DocumentView(
                        doc_id=doc_id,
                        kind=DocumentKind.REPORT,
                        author=side.nation,
                        issued=day,
                        arrives=day,
                        channel=ChannelKind.CABLE,
                        classification=Classification.CONFIDENTIAL,  # [proposed]
                        title=_clip(f"Battle at {place}: day {number}"),
                        body=(
                            BodyField(label="Place", value=_clip(place)),
                            BodyField(label="Our losses", value=f"{lost[i]} steps"),
                            BodyField(label="Enemy losses seen", value=f"{lost[1 - i]} steps"),
                        ),
                        scope=private_to(seat),
                    ),
                    truth=DocumentTruth(doc_id=doc_id),
                )
            )
    return out


def _end(state: "State", battle: Battle, day: date, ending: Ending) -> list["Payload"]:
    from revisionist.core import events as ev

    winner = battle.attacker.nation if ending is Ending.WON else battle.defender.nation
    return [
        _news(state, battle, day, ending),
        ev.BattleEnded(area=battle.area, on=day, ending=ending, winner=winner),
    ]


def _wake(state: "State") -> int:
    """The wake whose close the day walk runs in: the current or last wake, else 0."""
    return state.wake.number if state.wake is not None else 0


def _leave(
    state: "State",
    area: EntityId,
    pieces: Sequence["Feature"],
    to: dict[FeatureId, EntityId],
    day: date,
    lose: bool,
) -> dict[FeatureId, list["Payload"]]:
    """``pieces`` leave ``area`` one step, each for its area in ``to`` (cause ordered: a
    decision or a standing contingency), losing one step from the strongest of them (ties
    to the lowest id) when ``lose``, since the other side presses (BDC rule 4); a piece
    that loses its last step is out of play and does not move. The payloads, by piece."""
    from revisionist.core import events as ev
    from revisionist.core.realism import territory

    hit: FeatureId | None = None
    if lose and pieces:
        hit = min(pieces, key=lambda f: (-f.tier, f.feature_id)).feature_id
    out: dict[FeatureId, list[Payload]] = {}
    for f in sorted(pieces, key=lambda x: x.feature_id):
        update: dict[str, object] = {
            "places": (area,),
            "path": (),
            "step_due": None,
            "bound_for": None,
            "arrives": None,
            "as_of": max(day, f.as_of),
        }
        if f.feature_id == hit:
            update["tier"] = f.tier - 1
            if f.tier - 1 == 0:
                update["lost_on"] = day
        still = f.model_copy(update=update)
        if still.lost_on is not None:
            out[f.feature_id] = [ev.FeatureSet(feature=still)]
            continue
        moved, stepped = territory.step(
            state, still, to[f.feature_id], day, territory.StepCause.ORDERED
        )
        out[f.feature_id] = [ev.FeatureSet(feature=moved), stepped]
    return out


def _joining(state: "State", battle: Battle, day: date) -> tuple[Battle, list["Payload"]]:
    """Pieces standing in the battle's area on neither side whose nation fights on one
    of them join it (reinforce is a move order into the area): the battle with them in,
    and one ``battle_decided`` per side that gained pieces. A join gives no decision."""
    from revisionist.core import events as ev

    ours = {*battle.attacker.pieces, *battle.defender.pieces}
    new: tuple[list[Feature], list[Feature]] = ([], [])
    a, d = battle.attacker.nation, battle.defender.nation
    here = fighting(state)
    for f in here.get(_side_area(battle, 0), []):
        if f.feature_id not in ours and _with(state, _nation(state, f), a, d):
            new[0].append(f)
    for f in here.get(_side_area(battle, 1), []):
        if f.feature_id not in ours and _with(state, _nation(state, f), d, a):
            new[1].append(f)
    out: list[Payload] = []
    sides = [battle.attacker, battle.defender]
    for i, joined in enumerate(new):
        if not joined:
            continue
        added = sum(f.tier for f in joined)
        ids = tuple(f.feature_id for f in joined)
        out.append(
            ev.BattleDecided(
                area=battle.area, nation=sides[i].nation, on=day, joined=ids, added=added
            )
        )
        sides[i] = sides[i].model_copy(
            update={
                "pieces": tuple(sorted((*sides[i].pieces, *ids))),
                "brought": sides[i].brought + added,
            }
        )
    return battle.model_copy(update={"attacker": sides[0], "defender": sides[1]}), out


def _legs_dropped(state: "State", battle: Battle) -> tuple["State", list["Payload"]]:
    """History steps aside (HSA rule 1): each piece on a side of the battle, the ones that
    joined today included, drops the moves the record still had for it. The state with
    them dropped, and one ``feature_set`` for each piece that had any."""
    from revisionist.core import events as ev

    features = dict(state.features)
    out: list[Payload] = []
    for fid in (*battle.attacker.pieces, *battle.defender.pieces):
        f = features.get(fid)
        if f is not None and f.legs:
            features[fid] = f.model_copy(update={"legs": ()})
            out.append(ev.FeatureSet(feature=features[fid]))
    if not out:
        return state, out
    return state.model_copy(update={"features": features}), out


def _fires(f: "Feature", own: int, enemy: int) -> bool:
    """Whether a piece's contingency acts at the start of a round, its side standing at
    ``own`` against ``enemy`` in contact (BDC rule 5)."""
    from revisionist.core.realism.effect import ContingencyKind

    c = f.contingency
    if c is None:
        return False
    if c.kind is ContingencyKind.FALL_BACK:
        return enemy >= OUTNUMBERED * own
    if c.kind is ContingencyKind.WITHDRAW_BELOW:
        return c.below is not None and f.tier < c.below
    return False


def _contingencies(
    state: "State", battle: Battle, sides: tuple[list["Feature"], list["Feature"]], day: date
) -> tuple[list["Payload"], set[FeatureId]]:
    """At the start of a round, with no player: each piece whose contingency fires leaves
    for the area it names, else as a broken side would; with nowhere to go it stays. Both
    sides are read as the round began. The payloads and the pieces that left."""
    strength = tuple(sum(f.tier for f in pieces) for pieces in sides)
    out: list[Payload] = []
    gone: set[FeatureId] = set()
    for i, pieces in enumerate(sides):
        to: dict[FeatureId, EntityId] = {}
        for f in pieces:
            if _fires(f, strength[i], strength[1 - i]):
                dest = fall_back(state, f, battle.area)
                if dest is not None:
                    to[f.feature_id] = dest
        leaving = [f for f in pieces if f.feature_id in to]
        for moved in _leave(state, battle.area, leaving, to, day, pressing(battle, 1 - i)).values():
            out += moved
        gone |= set(to)
    return out, gone


def _holds_fast(f: "Feature") -> bool:
    from revisionist.core.realism.effect import ContingencyKind

    return f.contingency is not None and f.contingency.kind is ContingencyKind.HOLD_FAST


def _day(state: "State", battle: Battle, day: date) -> list["Payload"]:
    """One day of an open battle: the pieces that join it, its round if the attacker
    presses (each piece's contingency checked first), the steps lost, the reports, and
    when it ends, the side forced back and the end."""
    from revisionist.core import events as ev

    if battle.meeting:
        return _meeting_day(state, battle, day)
    battle, out = _joining(state, battle, day)
    state, dropped = _legs_dropped(state, battle)
    out += dropped
    att = _present(state, battle, battle.attacker)
    dfn = _present(state, battle, battle.defender)
    if att and dfn and presses(battle.attacker):  # rule 6: at the start of every round
        moved, gone = _contingencies(state, battle, (att, dfn), day)
        out += moved
        att = [f for f in att if f.feature_id not in gone]
        dfn = [f for f in dfn if f.feature_id not in gone]
    if not att or not dfn:  # a side left or was destroyed outside the battle
        return out + _end(state, battle, day, Ending.WON if att else Ending.HELD)
    last = battle.pressed_on or battle.opened - timedelta(days=1)
    sides = Sides(
        attacker=_side_in(state, battle, battle.attacker, att),
        defender=_side_in(state, battle, battle.defender, dfn),
        defence=_defence(state, battle.area),
        presses=presses(battle.attacker),
        lull=max(0, (day - last).days - 1),
    )
    sides = _with_kinds(state, battle, (att, dfn), sides)
    played = simulate(sides, seed(state, battle.area, day, (f.feature_id for f in (*att, *dfn))), 1)
    was = {str(f.feature_id): f for f in (*att, *dfn)}
    now = dict(was)
    lost = (0, 0)
    if played.rounds:
        r = played.rounds[0]
        for hits in r.hits:
            for pid, steps in hits:
                f = now[pid]
                tier = max(0, f.tier - steps)
                update: dict[str, object] = {"tier": tier, "as_of": max(day, f.as_of)}
                if tier == 0:
                    update["lost_on"] = day
                now[pid] = f.model_copy(update=update)
        lost = (r.lost(0), r.lost(1))
        out.append(
            ev.BattleRound(area=battle.area, on=day, scores=r.scores, draws=r.draws, lost=lost)
        )
    leaving: list[Feature] = []
    if played.ending is Ending.LULL or played.broken == 0:
        leaving = [now[str(f.feature_id)] for f in att]
    elif played.broken == 1:
        leaving = [now[str(f.feature_id)] for f in dfn]
    moves: list[Payload] = []
    sent: set[FeatureId] = set()
    stays = False
    for f in leaving:
        if f.lost_on is not None:
            continue
        if played.ending is not Ending.LULL and _holds_fast(f):
            stays = True  # hold at all costs: never forced back (BDC rule 5)
            continue
        to = _went_back(state, battle, f) if played.ending is Ending.LULL else None
        to = to or fall_back(state, f, battle.area)
        if to is None and played.ending is Ending.LULL:
            stays = True  # [proposed] an attacker with nowhere to go back to stays
            continue
        moves += _sent_back(state, f, battle.area, to, day)
        sent.add(f.feature_id)
    for pid in sorted(now):
        if now[pid] != was[pid] and now[pid].feature_id not in sent:
            out.append(ev.FeatureSet(feature=now[pid]))
    if played.rounds:
        out += _reports(state, battle, day, battle.rounds + 1, lost)
    if played.ending is None:
        return out
    out += moves
    if stays:  # the battle stays open while a piece of the side stands there
        return out
    return out + _end(state, battle, day, played.ending)


def _meeting_day(state: "State", battle: Battle, day: date) -> list["Payload"]:
    """One day of a meeting battle (HON rules 2 and 3): the pieces that join each side in
    its own area; the side that withdrew, whose contingency fires or that is gone yields at
    once; else a round with no terrain or own-ground bonus, and the side that breaks (or the
    attacker after a lull) yields."""
    from revisionist.core import events as ev

    battle, out = _joining(state, battle, day)
    state, dropped = _legs_dropped(state, battle)
    out += dropped
    sides = (_present(state, battle, battle.attacker), _present(state, battle, battle.defender))
    gives: int | None = None
    for i, side in enumerate((battle.attacker, battle.defender)):
        if side.decision is Decision.WITHDRAW and gives is None:
            gives = i
    if gives is None and not all(sides):
        gives = 0 if not sides[0] else 1
    if gives is None and presses(battle.attacker):
        strength = tuple(sum(f.tier for f in pieces) for pieces in sides)
        for i, pieces in enumerate(sides):
            if gives is None and any(_fires(f, strength[i], strength[1 - i]) for f in pieces):
                gives = i  # [proposed] a contingency fired in a meeting: its side keeps home
    now = {f.feature_id: f for f in (*sides[0], *sides[1])}
    if gives is not None:
        ending = Ending.WON if gives == 1 else Ending.LULL
        if gives == 0 and battle.attacker.decision is not Decision.WITHDRAW:
            ending = Ending.HELD
        return out + _meeting_end(state, battle, day, now, ending)
    last = battle.pressed_on or battle.opened - timedelta(days=1)
    played = simulate(
        _with_kinds(
            state,
            battle,
            sides,
            Sides(
                attacker=_side_in(state, battle, battle.attacker, sides[0]),
                defender=_side_in(state, battle, battle.defender, sides[1]),
                defence=0,  # rule 2: no terrain bonus on a border
                presses=presses(battle.attacker),
                lull=max(0, (day - last).days - 1),
            ),
        ),
        seed(state, battle.area, day, now),
        1,
    )
    lost = (0, 0)
    if played.rounds:
        r = played.rounds[0]
        for hits in r.hits:
            for pid, steps in hits:
                f = now[FeatureId(pid)]
                tier = max(0, f.tier - steps)
                update: dict[str, object] = {"tier": tier, "as_of": max(day, f.as_of)}
                if tier == 0:
                    update["lost_on"] = day
                now[f.feature_id] = f.model_copy(update=update)
        lost = (r.lost(0), r.lost(1))
        out.append(
            ev.BattleRound(area=battle.area, on=day, scores=r.scores, draws=r.draws, lost=lost)
        )
        out += _reports(state, battle, day, battle.rounds + 1, lost)
    if played.ending is None:
        return out + [
            ev.FeatureSet(feature=f) for fid, f in sorted(now.items()) if f != state.features[fid]
        ]
    return out + _meeting_end(state, battle, day, now, played.ending)


def _meeting_end(
    state: "State", battle: Battle, day: date, now: dict[FeatureId, "Feature"], ending: Ending
) -> list["Payload"]:
    """A meeting battle ends (rule 3): the side that yields keeps to its own area with its
    moves dropped; each piece of the other whose step across the border has fallen due
    completes it, cause ordered, unless its side withdrew. Where pieces of the side that yielded
    remain, a normal battle opens there with the movers attacking, its first round the next
    day [proposed]; else each mover goes on with its course."""
    from revisionist.core import events as ev
    from revisionist.core.realism import territory

    loser = 1 if ending is Ending.WON else 0
    sides = (battle.attacker, battle.defender)
    win, lose = sides[1 - loser], sides[loser]
    home, into = _side_area(battle, 1 - loser), _side_area(battle, loser)
    left: list[Feature] = []
    movers: list[Feature] = []
    for fid in sorted(now):
        f = now[fid]
        if f.lost_on is not None:
            continue
        if fid in lose.pieces:
            now[fid] = _still(f, day) if f.path or f.bound_for is not None else f
            left.append(now[fid])
        elif (
            f.path[:1] == (into,)
            and f.step_due is not None
            and f.step_due <= day
            and win.decision is not Decision.WITHDRAW
        ):
            movers.append(f)
    steps: list[Payload] = []
    for f in movers:
        moved, stepped = territory.step(state, f, into, day, territory.StepCause.ORDERED)
        days = territory.step_days(state, moved, moved.path[0]) if moved.path else None
        if left or days is None:
            moved = _still(moved, day)
        else:
            moved = moved.model_copy(update={"step_due": day + timedelta(days=days)})
        now[f.feature_id] = moved
        steps.append(stepped)
    out: list[Payload] = [
        ev.FeatureSet(feature=f) for fid, f in sorted(now.items()) if f != state.features[fid]
    ]
    out += steps
    out += _end(state, battle, day, ending)
    entered = [now[f.feature_id] for f in movers]
    if left and any(may_attack(state, f) for f in entered):
        follow = Battle(
            area=into,
            opened=day,
            attacker=BattleSide(
                nation=win.nation,
                pieces=tuple(f.feature_id for f in entered),
                brought=sum(f.tier for f in entered),
            ),
            defender=BattleSide(
                nation=lose.nation,
                pieces=tuple(f.feature_id for f in left),
                brought=sum(f.tier for f in left),
            ),
            came_from=dict.fromkeys((f.feature_id for f in entered), home),
        )
        out += [ev.BattleOpened(battle=follow, on=day), _news(state, follow, day, None)]
    return out


# --- decisions and contingencies (BDC) ---------------------------------------------


def _reading(
    state: "State", force: "Feature", posture: "Posture | None", to: EntityId | None
) -> tuple[Battle, Decision, EntityId | None] | None:
    """The battle ``force`` stands in and the decision a posture and a destination give
    there, with the area a withdrawal names; None for a force in no battle, or for a
    posture that is no battle decision (patrol, escort), which lands as today. A move to
    another area is a withdrawal toward it, whatever its posture."""
    from revisionist.core.realism import kinds, territory
    from revisionist.core.realism.effect import Posture

    if not on(state):
        return None
    area = _fights_in(state, force)
    battle = at(state, area) if area is not None else None
    domain = kinds.domain(state, force)
    if battle is None or area is None or domain is None:
        return None
    dest = territory.area_of(state, to, domain) if to is not None else None
    if to is not None and dest is None:
        dest = to  # [proposed] a place on no area names nowhere a side may go
    if battle.meeting and dest is not None and dest in _areas(battle) and dest != area:
        return battle, Decision.PRESS, None  # HON: a move across the border presses
    if dest is not None and dest != area:
        return battle, Decision.WITHDRAW, dest
    decision = (
        {
            Posture.ATTACK: Decision.PRESS,
            Posture.HOLD: Decision.HOLD,
            Posture.WITHDRAW: Decision.WITHDRAW,
        }.get(posture)
        if posture is not None
        else None
    )
    return None if decision is None else (battle, decision, None)


def _withdrawal(
    state: "State", battle: Battle, force: "Feature", named: EntityId | None
) -> EntityId | None:
    """Where a side withdraws to: the area named, when it borders the battle and its side
    or an ally holds it; one named farther off, the first area of the force's course to
    it; none named, where the force would be forced back. None: nowhere it may go."""
    from revisionist.core.realism import kinds, territory

    area, board, domain = battle.area, state.map, kinds.domain(state, force)
    if named is None:
        return fall_back(state, force, area)
    if board is None or domain is None:
        return None
    if named not in territory.neighbours(board, area, domain):
        course = territory.path(state, force, named)
        named = course[0] if course else None  # [proposed] the first step toward it
    return named if named is not None and _may_go(state, force, area, named) else None


CAUTION = (Decision.WITHDRAW, Decision.HOLD, Decision.PRESS)  # [proposed] BDS
"""The most cautious decision first: the order a seat's own competing decisions settle in."""


def twins(state: "State", wanted: Iterable[tuple[SeatId, str, object, date]]) -> frozenset[str]:
    """Of the parts landing in one pass, the refs of those that are a second decision for
    a side's battle and so are refused as twins (rule 3; BDS). Each part is (issuing seat,
    ref, effect as carried, day it lands). One decision lands per side, chosen by content,
    never by filing order: a seat whose person belongs to the side's own nation first, then
    the lowest seat key, then the most cautious decision (``CAUTION``), then the lowest
    force id, destination and day. Parts equal in all of these are the same decision; the
    ref only names which of them is counted. Empty with ``battles`` off, where no posture is
    a decision (``_reading``)."""
    from revisionist.core.realism.effect import MoveForce
    from revisionist.core.realism.war import polity_of

    chosen: dict[tuple[EntityId, int], tuple[tuple[object, ...], str]] = {}
    out: set[str] = set()
    for seat, ref, effect, day in wanted:
        force = state.features.get(effect.force) if isinstance(effect, MoveForce) else None
        if force is None or not isinstance(effect, MoveForce):
            continue
        read = _reading(state, force, effect.posture, effect.to)
        if read is None:
            continue
        fought, decision, _ = read
        sides = (fought.attacker, fought.defender)
        i = next((n for n, side in enumerate(sides) if force.feature_id in side.pieces), None)
        if i is None:
            continue  # rule 9: refused by ``land_posture`` itself
        person = state.seats[seat].embodies if seat in state.seats else None
        lead = person is not None and polity_of(state, person) == sides[i].nation
        rank: tuple[object, ...] = (not lead, str(seat), CAUTION.index(decision))
        rank += (str(force.feature_id), str(effect.to or ""), day, ref)
        key = (fought.area, i)
        held = chosen.get(key)
        if held is None or rank < held[0]:
            if held is not None:
                out.add(held[1])
            chosen[key] = (rank, ref)
        else:
            out.add(ref)
    return frozenset(out)


def land_posture(
    state: "State",
    force: "Feature",
    posture: "Posture | None",
    to: EntityId | None,
    on: date,
    *,
    twin: bool = False,
) -> list["Payload"] | None:
    """A posture landing on ``force`` (with the destination of its move, if any): with
    ``battles`` on and the force in a battle, the changes that land instead of today's,
    the force's ``feature_set`` first; None for a force in no battle, so the caller goes on
    as today. Press, hold and withdraw are its side's decision for the battle, from the
    first round on or after ``on`` until changed (rules 1 and 2). A second decision for the
    battle in one wake (rule 3), a piece on neither side (rule 9) and a withdrawal with
    nowhere it may go are refused: the force is left as it was. A withdrawing side leaves
    one step for the area named, losing one step if the other side presses (rule 4).
    ``twin``: a decision ``twins`` refused for this pass, left as it was the same way."""
    from revisionist.core import events as ev

    if twin:
        return [ev.FeatureSet(feature=force.model_copy(update={"as_of": max(on, force.as_of)}))]
    read = _reading(state, force, posture, to)
    if read is None:
        return None
    battle, decision, named = read
    kept: list[Payload] = [
        ev.FeatureSet(feature=force.model_copy(update={"as_of": max(on, force.as_of)}))
    ]
    sides = (battle.attacker, battle.defender)
    i = next((n for n, side in enumerate(sides) if force.feature_id in side.pieces), None)
    if i is None:
        return kept  # rule 9: no piece of the seat's in the battle
    side, wake = sides[i], _wake(state)
    if side.decided_wake == wake:
        return kept  # rule 3: a twin
    update: dict[str, object] = {"as_of": max(on, force.as_of)}
    if posture is not None:
        update["posture"] = posture
    posed = force.model_copy(update=update)
    decided = ev.BattleDecided(
        area=battle.area, nation=side.nation, on=on, decision=decision, wake=wake
    )
    if decision is not Decision.WITHDRAW:
        return [ev.FeatureSet(feature=posed), decided]
    if battle.meeting:  # HON rule 3: a side withdrawing from a meeting keeps its own area
        stay: list[Payload] = [ev.FeatureSet(feature=_still(posed, on)), decided]
        for f in _present(state, battle, side):
            if f.feature_id != force.feature_id and (f.path or f.bound_for is not None):
                stay.append(ev.FeatureSet(feature=_still(f, on)))
        return stay
    dest = _withdrawal(state, battle, force, named)
    if dest is None:
        return kept
    pieces = [
        posed if f.feature_id == force.feature_id else f for f in _present(state, battle, side)
    ]
    if force.feature_id not in {f.feature_id for f in pieces}:
        pieces.append(posed)
    left = _leave(
        state,
        battle.area,
        pieces,
        dict.fromkeys((f.feature_id for f in pieces), dest),
        on,
        pressing(battle, 1 - i),
    )
    own = left.pop(force.feature_id)
    out: list[Payload] = [own[0], decided, *own[1:]]
    for fid in sorted(left):
        out += left[fid]
    return out


def land_contingency(force: "Feature", effect: "SetEngagement", on: date) -> "Feature":
    """The force with an engagement effect landed: its rule, and its contingency when the
    effect carries one (rule 5); a contingency is otherwise left as it was."""
    update: dict[str, object] = {"engagement": effect.rule, "as_of": max(on, force.as_of)}
    if effect.contingency is not None:
        update["contingency"] = effect.contingency
    return force.model_copy(update=update)


def aide_may[E: Model](state: "State", effect: E) -> E | None:
    """What of ``effect`` the aide may file for an absent seat with ``battles`` on (rule
    8): never an attack or withdraw posture (a move keeps its destination), never a move
    that takes a force out of its battle, never a change of contingency. None when nothing
    is left. With ``battles`` off, the effect as it is."""
    from revisionist.core.realism.effect import MoveForce, Posture, SetEngagement

    if not on(state):
        return effect
    if isinstance(effect, MoveForce):
        force = state.features.get(effect.force)
        read = None if force is None else _reading(state, force, None, effect.to)
        if read is not None and read[1] is Decision.WITHDRAW:
            return None
        if effect.posture in (Posture.ATTACK, Posture.WITHDRAW):
            return None if effect.to is None else effect.model_copy(update={"posture": None})
    if isinstance(effect, SetEngagement) and effect.contingency is not None:
        return effect.model_copy(update={"contingency": None})
    return effect


def won(
    payloads: Iterable["Payload"], battles: "Mapping[EntityId, Battle] | None" = None
) -> list[tuple[EntityId, EntityId]]:
    """Each area where a battle among ``payloads`` ended won, with the nation that won. A
    meeting battle (read from ``battles``, as they stood before) counts in the area its
    winner stepped into, whichever side won; one that opened among ``payloads`` is read
    there."""
    from revisionist.core import events as ev

    out: list[tuple[EntityId, EntityId]] = []
    known = dict(battles or {})
    for p in payloads:
        if isinstance(p, ev.BattleOpened):
            known[p.battle.area] = p.battle
        if not isinstance(p, ev.BattleEnded):
            continue
        fought = known.pop(p.area, None)
        if p.ending is Ending.CEASED:
            continue
        if fought is not None and fought.meeting:
            out.append(
                (_side_area(fought, 0 if p.winner == fought.defender.nation else 1), p.winner)
            )
        elif p.ending is Ending.WON:
            out.append((p.area, p.winner))
    return out


def walk(before: "State", state: "State", day: date, met: Sequence[Meet] = ()) -> list["Payload"]:
    """With ``battles`` on, the battles of ``day``, in area id order: each open battle's
    day, then each battle that opens today with its news and its first round: a meeting
    battle on each border in ``met`` (HON), else where enemies stand together. A battle
    that opens drops the moves of the pieces on its sides but a meeting's movers (rule 4).
    ``before`` is the state as the day began, which tells the pieces that stepped in."""
    from revisionist.core import events as ev

    if not on(state):
        return []
    out: list[Payload] = []
    here = fighting(state)
    new = {m.border[0]: m for m in met}
    seconds = {b.second for b in state.battles.values() if b.second is not None}
    seconds |= {m.border[1] for m in met}
    for area in sorted({*state.battles, *here, *new} - seconds):
        battle = state.battles.get(area)
        if battle is None:
            m = new.get(area)
            battle = (
                _meeting(state, m, here, day)
                if m is not None
                else _opening(before, state, area, here.get(area, []), day)
            )
            if battle is None:
                continue
            out += [ev.BattleOpened(battle=battle, on=day), _news(state, battle, day, None)]
            pins = _pin(state, battle, m.movers if m is not None else (), day)
            out += pins
            if pins:
                features = dict(state.features)
                for p in pins:
                    assert isinstance(p, ev.FeatureSet)
                    features[p.feature.feature_id] = p.feature
                out += _day(state.model_copy(update={"features": features}), battle, day)
                continue
        elif _ceased(state, battle):
            out += _end(state, battle, day, Ending.CEASED)
            continue
        out += _day(state, battle, day)
    return out


def _ceased(state: "State", battle: Battle) -> bool:
    """Whether an open battle's two powers no longer fight: an armistice between them is
    in force, or their war has ended (PEA). Each side holds where it stands."""
    from revisionist.core.realism.war import hostile

    return not hostile(state, battle.attacker.nation, battle.defender.nation)


__all__ = [
    "AIR_SUPPORT",
    "CAUTION",
    "DOUBLE_MARGIN",
    "DRAW_TOP",
    "LULL_DAYS",
    "OUTNUMBERED",
    "Battle",
    "BattleSide",
    "Decision",
    "Ending",
    "Fighter",
    "Meet",
    "Played",
    "Round",
    "SideIn",
    "Sides",
    "aide_may",
    "at",
    "broken",
    "busy",
    "closed",
    "commanders",
    "draws",
    "fall_back",
    "fighting",
    "fighting_area",
    "holds_ground",
    "kinds_count",
    "land_contingency",
    "land_posture",
    "losses",
    "may_attack",
    "meetings",
    "news_id",
    "on",
    "pinned",
    "presses",
    "pressing",
    "report_id",
    "score",
    "seed",
    "simulate",
    "twins",
    "walk",
    "won",
]
