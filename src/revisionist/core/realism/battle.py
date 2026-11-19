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
"""

import hashlib
from collections.abc import Iterable, Sequence
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


class Ending(StrEnum):
    WON = "won"
    """No defender is left: the attacker has won."""
    HELD = "held"
    """No attacker is left, or the attacker broke."""
    LULL = "lull"
    """The attacker stopped pressing for ``LULL_DAYS`` days and went back."""


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


def score(side: SideIn, draw: int, defending: bool, defence: int) -> int:
    """A side's score for a round: its strength, the defender's terrain and own ground,
    air support, supply and the draw."""
    total = sum(f.strength for f in side.fighters) + draw
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
        sa = score(att, da, False, sides.defence)
        sd = score(dfn, dd, True, sides.defence)
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


def _opening(
    before: "State", state: "State", area: EntityId, here: Sequence["Feature"], day: date
) -> Battle | None:
    """The battle that opens in ``area`` today, or None when no two powers there are at
    war. The attacker is the nation of the first piece (in id order) that stepped in today
    with an enemy there that did not; with none, the first nation (in id order) at war
    with the area's holder, else the nation of the first piece. The defender is the
    nation of the first enemy piece that stood there, else of the first enemy piece. Each
    side takes the pieces of nations at war with the other side and not with it."""
    from revisionist.core.realism import territory
    from revisionist.core.realism.war import at_war

    nation = {f.feature_id: _nation(state, f) for f in here}
    if not any(at_war(state, a, b) for a in nation.values() for b in nation.values()):
        return None
    was = {
        f.feature_id: _area(before, b)
        for f in here
        if (b := before.features.get(f.feature_id)) is not None
    }
    entered = [f for f in here if was.get(f.feature_id) != area]
    stood = [f for f in here if was.get(f.feature_id) == area]
    attacker = next(
        (
            nation[f.feature_id]
            for f in entered
            if any(at_war(state, nation[f.feature_id], nation[g.feature_id]) for g in stood)
        ),
        None,
    )
    if attacker is None:
        held = territory.holder(state, area)
        foes = sorted(
            n for n in set(nation.values()) if held is not None and at_war(state, n, held)
        )
        attacker = foes[0] if foes else nation[here[0].feature_id]
    enemies = [f for f in here if at_war(state, attacker, nation[f.feature_id])]
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
    from revisionist.core.realism.war import at_war

    return n == own or (at_war(state, n, other) and not at_war(state, n, own))


def _present(state: "State", battle: Battle, side: BattleSide) -> list["Feature"]:
    """The side's pieces still in play with strength, standing in the battle's area."""
    from revisionist.core.realism.geography import in_play

    out = []
    for fid in side.pieces:
        f = state.features.get(fid)
        if f is not None and in_play(f) and f.tier >= 1 and _area(state, f) == battle.area:
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


def _defence(state: "State", area: EntityId) -> int:
    board = state.map
    assert board is not None
    terrain = {t.area: t.terrain for t in board.territories}
    terrain |= {z.area: z.terrain for z in board.sea_zones}
    key = terrain.get(area)
    return next((t.defence for t in board.terrain if t.key == key), 0)


def _side_in(
    state: "State", battle: Battle, side: BattleSide, pieces: Sequence["Feature"]
) -> SideIn:
    from revisionist.core.realism import territory

    return SideIn(
        fighters=tuple(Fighter(str(f.feature_id), f.tier) for f in pieces),
        brought=side.brought,
        lost=side.lost,
        own_ground=territory.holder(state, battle.area) == side.nation,
        air=_air(state, side.nation, battle.area),
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
    from revisionist.core.realism.war import at_war

    own = _nation(state, piece)
    return not any(at_war(state, own, _nation(state, f)) for f in fighting(state).get(to, []))


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
    }[ending]
    return ev.NewsReported(
        news=NewsEvent(
            news_id=news_id(state, battle, "opened" if ending is None else "ended"),
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
    for f in fighting(state).get(battle.area, []):
        if f.feature_id in ours:
            continue
        n = _nation(state, f)
        if _with(state, n, a, d):
            new[0].append(f)
        elif _with(state, n, d, a):
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

    battle, out = _joining(state, battle, day)
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
    battle = state.battles.get(area) if area is not None else None
    domain = kinds.domain(state, force)
    if battle is None or domain is None:
        return None
    dest = territory.area_of(state, to, domain) if to is not None else None
    if to is not None and dest is None:
        dest = to  # [proposed] a place on no area names nowhere a side may go
    if dest is not None and dest != battle.area:
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


def land_posture(
    state: "State", force: "Feature", posture: "Posture | None", to: EntityId | None, on: date
) -> list["Payload"] | None:
    """A posture landing on ``force`` (with the destination of its move, if any): with
    ``battles`` on and the force in a battle, the changes that land instead of today's,
    the force's ``feature_set`` first; None for a force in no battle, so the caller goes on
    as today. Press, hold and withdraw are its side's decision for the battle, from the
    first round on or after ``on`` until changed (rules 1 and 2). A second decision for the
    battle in one wake (rule 3), a piece on neither side (rule 9) and a withdrawal with
    nowhere it may go are refused: the force is left as it was. A withdrawing side leaves
    one step for the area named, losing one step if the other side presses (rule 4)."""
    from revisionist.core import events as ev

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


def won(payloads: Iterable["Payload"]) -> list[tuple[EntityId, EntityId]]:
    """Each area where a battle among ``payloads`` ended won, with the nation that won."""
    from revisionist.core import events as ev

    return [
        (p.area, p.winner)
        for p in payloads
        if isinstance(p, ev.BattleEnded) and p.ending is Ending.WON
    ]


def walk(before: "State", state: "State", day: date) -> list["Payload"]:
    """With ``battles`` on, the battles of ``day``, in area id order: each open battle's
    day, then each battle that opens today with its news and its first round. ``before``
    is the state as the day began, which tells the pieces that stepped in today."""
    from revisionist.core import events as ev

    if not on(state):
        return []
    out: list[Payload] = []
    here = fighting(state)
    for area in sorted({*state.battles, *here}):
        battle = state.battles.get(area)
        if battle is None:
            battle = _opening(before, state, area, here.get(area, []), day)
            if battle is None:
                continue
            out += [ev.BattleOpened(battle=battle, on=day), _news(state, battle, day, None)]
        out += _day(state, battle, day)
    return out


__all__ = [
    "AIR_SUPPORT",
    "DOUBLE_MARGIN",
    "DRAW_TOP",
    "LULL_DAYS",
    "OUTNUMBERED",
    "Battle",
    "BattleSide",
    "Decision",
    "Ending",
    "Fighter",
    "Played",
    "Round",
    "SideIn",
    "Sides",
    "aide_may",
    "broken",
    "commanders",
    "draws",
    "fall_back",
    "fighting",
    "land_contingency",
    "land_posture",
    "losses",
    "news_id",
    "on",
    "presses",
    "pressing",
    "report_id",
    "score",
    "seed",
    "simulate",
    "walk",
    "won",
]
