"""The odds spread, simulated on the server from the seat's own picture (ODS).

The ``odds`` action takes one of the seat's own pieces and either a destination area or an
open battle with a decision, and answers with a spread, never one figure: the shares of
win, stalemate and loss; the likely range of steps each side loses (the 10th to the 90th
percentile); the chance of taking the territory and the median days until it is taken; the
chance of being forced back and the area that would be to; and the win share at each
strength in the enemy's reported range.

The seat's own pieces go in exactly. The enemy goes in only from the reports in
``View.reports`` for the area, each piece's strength drawn evenly across its report's range:
the truth about the enemy is never read, so swapping the enemy for one of another strength
with the reports unchanged gives the same reply byte for byte. With no report for the area
the reply says the enemy is unknown and gives the terrain facts and no figures.

Each request runs ``battle.simulate`` ``ODDS_RUNS`` times over ``ODDS_DAYS`` days, seeded
by the campaign, the wake, the seat and the request's inputs (never the clock), so asking
twice, or a hundred times, gives the same answer. It files nothing and costs nothing.
``Service`` bounds the work for the whole server: a fixed pool of simulation workers, a
bounded queue that answers busy when full, a bounded cache for the wake, one computation
for identical requests in flight whose waiters share its reply, and a per-seat rate limit.
"""

import hashlib
import json
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date
from typing import Any, Literal, NamedTuple, cast

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, FeatureId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import battle, detect, holders, kinds, territory, war_rules
from revisionist.core.realism.battle import (
    Battle,
    BattleSide,
    Decision,
    Ending,
    Fighter,
    SideIn,
)
from revisionist.core.realism.geography import Feature, in_play
from revisionist.core.realism.kinds import Domain
from revisionist.core.state import Rule, State, View
from revisionist.core.world_compile import object_id
from revisionist.engine.web.realism_api import (
    ClosingOdds,
    OddsAtStrength,
    OddsReply,
    OddsShares,
    OddsTerrain,
    StrengthRange,
)

ODDS_RUNS = 2000  # [proposed] plan, ODS Defaults; changes only after Josh sets the targets
ODDS_DAYS = 14  # [proposed] plan, ODS Defaults
LOW_CENTILE = 10  # [proposed] plan, ODS Defaults: the loss range runs from the 10th ...
HIGH_CENTILE = 90  # ... to the 90th percentile
PER_MINUTE = 30  # [proposed] plan, ODS Defaults: odds requests a minute per seat
WORKERS = 2  # [proposed] simulation workers for the whole server, from rule 9's measurement
QUEUE = 8  # [proposed] requests waiting beyond the workers before the server answers busy
CACHE = 512  # [proposed] replies kept for the wake, least recently asked dropped first

BUSY = "The odds desk is busy just now. Ask again in a moment."  # [proposed]
LIMITED = "You have asked for odds too often this minute. Ask again shortly."  # [proposed]
OFF = "Battles are not fought in this game, so there are no odds to give."  # [proposed]
NOT_YOURS = "That force is not yours to order."  # [proposed]
NOT_IN = "Your nation is in no battle there."  # [proposed]
NOT_THERE = "That force is not in the battle there."  # [proposed]
ONE_OF = "Name a destination area, or a battle and a decision."  # [proposed]


class BusyError(Exception):
    """The odds queue is full: the server answers busy."""


class LimitedError(Exception):
    """The seat has asked more than ``PER_MINUTE`` times in the last minute."""


# --- the picture: what the reply depends on ---------------------------------------


class Seen(NamedTuple):
    """One reported enemy piece that would fight: its report key and strength range."""

    key: str
    low: int
    high: int


class Picture(NamedTuple):
    """Everything the reply is computed from: the seat's own side exactly, the enemy as
    its reports give it, and the public facts of the area. Nothing else goes in."""

    area: EntityId
    side: Literal[0, 1]
    """The seat's side: 0 the attacker, 1 the defender."""
    own: SideIn
    enemy: tuple[Seen, ...]
    enemy_air: bool
    """A reported enemy air piece has the area within its kind's range."""
    enemy_ground: bool
    """The enemy defends ground its side holds (the defender's own-ground bonus)."""
    enemy_supplied: bool
    """True in every seat's picture: the reports say nothing of the enemy's supply. The
    closing truth sets it from the enemy's pieces."""
    defence: int
    presses: bool
    lull: int
    withdraw: bool
    """The decision is withdraw: the side leaves at once and no round is fought."""
    takes: bool
    """A win would start the count that takes the territory (a land attack, holders on)."""
    back: str | None
    """The area key the seat's piece would be forced back to; None: nowhere."""
    reports: tuple[str, ...]
    """Every report key used, fighters and air alike."""
    terrain: OddsTerrain


def _keys(view: View) -> dict[EntityId, tuple[str, str]]:
    board = view.map
    if board is None:
        return {}
    out = {t.area: (t.key, t.name) for t in board.territories}
    return out | {z.area: (z.key, z.name) for z in board.sea_zones}


def _area_of_key(view: View, key: str) -> EntityId:
    found = next((a for a, (k, _) in _keys(view).items() if k == key), None)
    if found is None:
        raise ValueError(f"There is no area {key}.")
    return found


def _domain_of_area(view: View, area: EntityId) -> Domain:
    board = view.map
    seas = {z.area for z in board.sea_zones} if board is not None else set()
    return Domain.SEA if area in seas else Domain.LAND


def _terrain(view: View, area: EntityId) -> OddsTerrain:
    """The public facts of an area: its key and name, terrain, defence and holder."""
    board = view.map
    assert board is not None
    key, name = _keys(view)[area]
    found = [t.terrain for t in board.territories if t.area == area]
    terrain = (found or [z.terrain for z in board.sea_zones if z.area == area] or [""])[0]
    defence = next((t.defence for t in board.terrain if t.key == terrain), 0)
    held = territory.holder(view, area)
    holder = view.entities.get(held) if held is not None else None
    return OddsTerrain(
        area=key,
        name=name,
        terrain=terrain,
        defence=defence,
        holder=holder.name if holder is not None else None,
    )


def _range(view: View, r: detect.Report) -> tuple[int, int]:
    """A report's strength range; with none given, any strength its kind allows."""
    if r.strength is not None:
        return r.strength
    kind = view.kinds.pieces.get(r.kind) if view.kinds is not None and r.kind else None
    return 1, kind.max_strength if kind is not None else kinds.MAX_STRENGTH  # [proposed]


def _enemy(view: View, area: EntityId) -> tuple[tuple[Seen, ...], bool, tuple[str, ...]]:
    """The reported enemy pieces that would fight in ``area`` (those of its domain, and
    those of unknown kind), whether a reported air piece has it in range, and the keys
    of every report used. Reads ``view.reports`` only."""
    board = view.map
    assert board is not None
    domain = _domain_of_area(view, area)
    pieces = view.kinds.pieces if view.kinds is not None else {}
    seen: list[Seen] = []
    air = False
    used: list[str] = []
    for key, r in sorted(view.reports.items()):
        if r.area is None:
            continue
        kind = pieces.get(r.kind) if r.kind is not None else None
        if kind is not None and kind.domain is Domain.AIR:
            far = territory.steps_from(board, "air", [r.area]).get(area)
            if far is not None and far <= (kind.range_steps or 0):
                air = True  # [proposed] an enemy air piece supports its side as the truth's would
                used.append(key)
            continue
        if r.area != area or (kind is not None and kind.domain is not domain):
            continue
        low, high = _range(view, r)
        seen.append(Seen(key, low, high))
        used.append(key)
    return tuple(seen), air, tuple(sorted(used))


def _nation(state: State, seat: SeatId) -> EntityId | None:
    me = state.seats.get(seat)
    return territory.nation(state, me.embodies) if me is not None else None


def _piece(state: State, seat: SeatId, key: str) -> Feature:
    """The seat's own force ``key``, in play: one the seat commands."""
    fid = FeatureId(object_id(state.campaign_id, "feature", key))
    f = state.features.get(fid)
    if f is None or not in_play(f) or not kinds.is_force(state, f):
        raise ValueError(NOT_YOURS)
    if not any(s == seat for s, _ in war_rules.commanders(state, fid)):
        raise ValueError(NOT_YOURS)
    return f


def _text(body: Mapping[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 120:
        raise ValueError(f"{key} must be text of at most 120 characters.")
    return value.strip()


def _back(view: View, piece: Feature, area: EntityId) -> str | None:
    """The area key ``piece`` would be forced back to from ``area``, read from the view."""
    to = battle.fall_back(view, piece, area)
    return _keys(view)[to][0] if to is not None and to in _keys(view) else None


def _toward(state: State, view: View, seat: SeatId, f: Feature, area: EntityId) -> Picture:
    """The picture for sending ``f`` into ``area``: it would attack whatever the reports
    put there, alone, on the terrain there."""
    seen, air, used = _enemy(view, area)
    own_nation = territory.nation(state, f.side)
    held = territory.holder(view, area)
    enemy_ground = (
        held is not None
        and own_nation is not None
        and held != own_nation
        and not territory.allied(state, own_nation, held)
    )
    terrain = _terrain(view, area)
    land = _domain_of_area(view, area) is Domain.LAND
    own = SideIn(
        fighters=(Fighter(str(f.feature_id), f.tier),),
        brought=f.tier,
        air=own_nation is not None and battle._air(state, own_nation, area),
        supplied=battle._supplied(state, [f]),
    )
    return Picture(
        area=area,
        side=0,
        own=own,
        enemy=seen,
        enemy_air=air,
        enemy_ground=enemy_ground,
        enemy_supplied=True,  # [proposed] the reports say nothing of the enemy's supply
        defence=terrain["defence"],
        presses=True,
        lull=0,
        withdraw=False,
        takes=land and Rule.HOLDERS in state.rules,
        back=_back(view, f, area),
        reports=used,
        terrain=terrain,
    )


def _decision(b: Battle, mine: BattleSide) -> Decision:
    """The side's decision in force: the one given, else press for the attacker and hold
    for the defender."""
    if mine.decision is not None:
        return mine.decision
    return Decision.PRESS if mine is b.attacker else Decision.HOLD


def _in_battle(
    state: State,
    view: View,
    seat: SeatId,
    f: Feature | None,
    area: EntityId,
    decision: Decision | None,
) -> Picture:
    """The picture for an open battle with a decision (None: the side's own in force):
    the seat's side as it stands, the enemy as the reports put it in the area it stands
    in. ``f`` is the seat's piece asked about; None: the first of its side there."""
    from revisionist.engine.web.battles_api import sides_of

    own_nation = _nation(state, seat)
    b = battle.at(state, area)
    sides = sides_of(state, b, own_nation) if b is not None and own_nation is not None else None
    if b is None or sides is None:
        raise ValueError(NOT_IN)
    mine, theirs = sides
    i: Literal[0, 1] = 0 if mine is b.attacker else 1
    present = battle._present(state, b, mine)
    if f is None and present:
        f = present[0]
    if f is None or f.feature_id not in {p.feature_id for p in present}:
        raise ValueError(NOT_THERE)
    decision = decision or _decision(b, mine)
    where, enemy_at = battle._side_area(b, i), battle._side_area(b, 1 - i)
    seen, air, used = _enemy(view, enemy_at)
    terrain = _terrain(view, b.area)
    defence = 0 if b.meeting else terrain["defence"]
    own = SideIn(
        fighters=tuple(Fighter(str(p.feature_id), p.tier) for p in present),
        brought=mine.brought,
        lost=mine.lost,
        own_ground=not b.meeting and territory.holder(view, b.area) == mine.nation,
        air=battle._air(state, mine.nation, where),
        supplied=battle._supplied(state, present),
    )
    # The attacker's decision is engine only: a defender's odds take it as pressing.
    presses = decision is Decision.PRESS if i == 0 else True
    today = view.in_world_date
    last = b.pressed_on or b.opened.fromordinal(b.opened.toordinal() - 1)
    lull = max(0, (today - last).days - 1) if today is not None and not presses else 0
    land = _domain_of_area(view, b.area) is Domain.LAND
    return Picture(
        area=b.area,
        side=i,
        own=own,
        enemy=seen,
        enemy_air=air,
        enemy_ground=(not b.meeting and i == 0 and territory.holder(view, b.area) == theirs.nation),
        enemy_supplied=True,  # [proposed] the reports say nothing of the enemy's supply
        defence=defence,
        presses=presses,
        lull=lull,
        withdraw=decision is Decision.WITHDRAW,
        takes=i == 0 and land and not b.meeting and Rule.HOLDERS in state.rules,
        back=_back(view, f, where),
        reports=used,
        terrain=terrain,
    )


def picture(state: State, seat: SeatId, body: Mapping[str, Any]) -> Picture:
    """The picture an ``odds`` request is answered from. ``body`` names the seat's own
    ``force`` and either ``to`` (a destination area key) or ``battle`` (the area key of an
    open battle) with ``decision``. Raises ``ValueError`` with the reason it cannot be."""
    if not battle.on(state):
        raise ValueError(OFF)
    force = _text(body, "force")
    if force is None:
        raise ValueError("Name the force.")
    to, at = _text(body, "to"), _text(body, "battle")
    if (to is None) == (at is None):
        raise ValueError(ONE_OF)
    f = _piece(state, seat, force)
    view = project(state, seat)
    if to is not None:
        return _toward(state, view, seat, f, _area_of_key(view, to))
    assert at is not None
    raw = _text(body, "decision")
    try:
        decision = Decision(raw or "")
    except ValueError:
        choices = ", ".join(d.value for d in Decision)
        raise ValueError(f"The decision is one of {choices}.") from None
    return _in_battle(state, view, seat, f, _area_of_key(view, at), decision)


# --- the spread: a pure function of the picture and its seed ----------------------


def seed(campaign: CampaignId, wake: int, seat: SeatId, p: Picture) -> str:
    """The request's seed: the campaign, the wake, the seat and the picture. No clock."""
    raw = json.dumps([str(campaign), wake, str(seat), p], sort_keys=True, default=str)
    return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()


def _draw(base: str, run: int, s: Seen) -> int:
    """An enemy piece's strength for one run, drawn evenly across its report's range."""
    digest = hashlib.blake2b(f"{base}\x1f{run}\x1f{s.key}".encode(), digest_size=8).digest()
    return s.low + int.from_bytes(digest, "big") % (s.high - s.low + 1)


def _centile(values: Sequence[int], pct: int) -> int:
    ordered = sorted(values)
    return ordered[(pct * (len(ordered) - 1)) // 100]


def _share(n: int, of: int) -> float:
    return round(100 * n / of, 1) if of else 0.0


def _unknown(p: Picture) -> OddsReply:
    return OddsReply(
        known=False,
        area=p.terrain["area"],
        terrain=p.terrain,
        runs=0,
        days=ODDS_DAYS,
        shares=None,
        own_lost=None,
        enemy_lost=None,
        taken=None,
        taken_days=None,
        forced_back=None,
        back_to=p.back,
        by_strength=[],
        reports=list(p.reports),
    )


def spread(p: Picture, base: str, runs: int = ODDS_RUNS, days: int = ODDS_DAYS) -> OddsReply:
    """The reply for ``p``: ``runs`` battles of up to ``days`` days, each run seeded from
    ``base``. A pure function: the same arguments give the same reply."""
    if not p.enemy:
        return _unknown(p)
    low = sum(s.low for s in p.enemy)
    high = sum(s.high for s in p.enemy)
    if p.withdraw:  # [proposed] the side leaves at once: no round, the field given up
        return OddsReply(
            known=True,
            area=p.terrain["area"],
            terrain=p.terrain,
            runs=runs,
            days=days,
            shares=OddsShares(win=0.0, stalemate=0.0, loss=100.0),
            own_lost=StrengthRange(low=0, high=0),
            enemy_lost=StrengthRange(low=0, high=0),
            taken=0.0 if p.takes else None,
            taken_days=None,
            forced_back=100.0,
            back_to=p.back,
            by_strength=[OddsAtStrength(strength=s, win=0.0) for s in range(low, high + 1)],
            reports=list(p.reports),
        )
    i = p.side
    outcomes = [0, 0, 0]  # win, stalemate, loss
    own_lost: list[int] = []
    enemy_lost: list[int] = []
    taken_on: list[int] = []
    back = 0
    tried = dict.fromkeys(range(low, high + 1), 0)
    won = dict.fromkeys(range(low, high + 1), 0)
    for run in range(runs):
        fighters = tuple(Fighter(s.key, _draw(base, run, s)) for s in p.enemy)
        total = sum(f.strength for f in fighters)
        enemy = SideIn(
            fighters=fighters,
            brought=total,
            own_ground=p.enemy_ground,
            air=p.enemy_air,
            supplied=p.enemy_supplied,
        )
        pair = (p.own, enemy) if i == 0 else (enemy, p.own)
        played = battle.simulate(
            battle.Sides(pair[0], pair[1], p.defence, p.presses, p.lull), f"{base}\x1f{run}", days
        )
        after = (played.sides.attacker, played.sides.defender)
        own_lost.append(after[i].lost - p.own.lost)
        enemy_lost.append(after[1 - i].lost)
        tried[total] += 1
        winner = {Ending.WON: 0, Ending.HELD: 1}.get(played.ending) if played.ending else None
        if winner is None:
            outcomes[1] += 1
        elif winner == i:
            outcomes[0] += 1
            won[total] += 1
            if p.takes and played.rounds:
                taken_on.append(played.rounds[-1].day + 1 + holders.CAPTURE_DAYS)
        else:
            outcomes[2] += 1
        if played.broken == i:
            back += 1
    return OddsReply(
        known=True,
        area=p.terrain["area"],
        terrain=p.terrain,
        runs=runs,
        days=days,
        shares=OddsShares(
            win=_share(outcomes[0], runs),
            stalemate=_share(outcomes[1], runs),
            loss=_share(outcomes[2], runs),
        ),
        own_lost=StrengthRange(
            low=_centile(own_lost, LOW_CENTILE), high=_centile(own_lost, HIGH_CENTILE)
        ),
        enemy_lost=StrengthRange(
            low=_centile(enemy_lost, LOW_CENTILE), high=_centile(enemy_lost, HIGH_CENTILE)
        ),
        taken=_share(len(taken_on), runs) if p.takes else None,
        taken_days=_centile(taken_on, 50) if taken_on else None,
        forced_back=_share(back, runs),
        back_to=p.back,
        by_strength=[
            OddsAtStrength(strength=s, win=_share(won[s], tried[s]) if tried[s] else None)
            for s in range(low, high + 1)
        ],
        reports=list(p.reports),
    )


def wake_of(state: State) -> int:
    return state.wake.number if state.wake is not None else 0


# --- the server's bound on odds work ----------------------------------------------


class Service:
    """Odds work for the whole server: ``workers`` simulation threads; at most ``queue``
    requests waiting beyond them, after which it answers busy; ``cache`` replies kept,
    keyed by the wake among the rest, so a new wake asks afresh; one computation for
    identical requests in flight, whose waiters share its reply; and ``per_minute``
    requests a minute per seat."""

    def __init__(
        self,
        workers: int = WORKERS,
        queue: int = QUEUE,
        cache: int = CACHE,
        per_minute: int = PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.workers, self.queue, self.cache_size = workers, queue, cache
        self.per_minute, self.clock = per_minute, clock
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="odds")
        self._lock = threading.RLock()
        """Re-entrant: a computation that finishes before its callback is added lands
        at once, in the asking thread, which holds the lock."""
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._flying: dict[str, Future[Any]] = {}
        self._asked: dict[tuple[str, str], deque[float]] = {}
        self.computed = 0
        """Computations started: identical requests in flight count once."""

    def _limit(self, who: tuple[str, str]) -> None:
        now = self.clock()
        asked = self._asked.setdefault(who, deque())
        while asked and now - asked[0] >= 60:
            asked.popleft()
        if len(asked) >= self.per_minute:
            raise LimitedError
        asked.append(now)

    def _landed(self, key: str, done: Future[Any]) -> None:
        with self._lock:
            if not done.cancelled() and done.exception() is None:
                self._cache[key] = done.result()
                self._cache.move_to_end(key)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
            self._flying.pop(key, None)

    def limit(self, who: tuple[str, str]) -> None:
        """Count one request by the seat ``who``; ``LimitedError`` past its rate."""
        with self._lock:
            self._limit(who)

    def ask[R](self, key: str, who: tuple[str, str] | None, compute: Callable[[], R]) -> R:
        """The reply for ``key``: from the cache, from the computation in flight, or from
        a new one. Raises ``LimitedError`` past the rate of the seat ``who`` (None: counted
        already, or the server's own asking) and ``BusyError`` when full."""
        with self._lock:
            if who is not None:
                self._limit(who)
            if key in self._cache:
                self._cache.move_to_end(key)
                return cast("R", self._cache[key])
            flying = self._flying.get(key)
            if flying is None:
                if len(self._flying) >= self.workers + self.queue:
                    raise BusyError
                flying = self._pool.submit(compute)
                self.computed += 1
                self._flying[key] = flying
                flying.add_done_callback(lambda f: self._landed(key, f))
        return cast("R", flying.result())

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


# --- the closing odds: how the odds truly stood on a battle's first day ----------------


def _true_enemy(state: State, b: Battle, theirs: BattleSide, at: EntityId) -> tuple[Seen, ...]:
    """The enemy's pieces in the battle as they truly stood: each its exact strength."""
    return tuple(
        Seen(f"piece {n}", f.tier, f.tier)
        for n, f in enumerate(battle._present(state, b, theirs), start=1)
    )


def closing_pictures(then: State, seat: SeatId, area: EntityId) -> tuple[Picture, Picture]:
    """The two pictures of the battle in ``area`` on its first day, from ``then`` (the
    game just after its ``battle_opened``): the seat's own (its side exactly, the enemy as
    its reports stood that day) and the truth (both sides exactly). Engine only: the true
    one is shown only once the battle has ended."""
    from revisionist.engine.web.battles_api import sides_of

    b = battle.at(then, area)
    own_nation = _nation(then, seat)
    sides = sides_of(then, b, own_nation) if b is not None and own_nation is not None else None
    if b is None or sides is None:
        raise ValueError(NOT_IN)
    day_one = then.model_copy(update={"in_world_date": b.opened})
    view = project(day_one, seat)
    seen = _in_battle(day_one, view, seat, None, area, None)
    i = seen.side
    enemy_at = battle._side_area(b, 1 - i)
    truth = seen._replace(
        enemy=_true_enemy(then, b, sides[1], enemy_at),
        enemy_supplied=battle._supplied(then, battle._present(then, b, sides[1])),
        enemy_air=battle._air(then, sides[1].nation, enemy_at),
        reports=(),
    )
    return seen, truth


def _closing(then: State, seat: SeatId, area: EntityId) -> ClosingOdds:
    seen, truth = closing_pictures(then, seat, area)
    wake = wake_of(then)
    return ClosingOdds(
        seen=spread(seen, seed(then.campaign_id, wake, seat, seen)),
        truly=spread(truth, seed(then.campaign_id, wake, seat, truth)),
    )


class Ended(NamedTuple):
    """A battle the seat's nation fought that has ended, as the log has it."""

    battle: Battle
    """The battle as it opened (``battle_opened``)."""
    ended: date
    closing: ClosingOdds | None
    """None: the odds desk was busy; the next refresh asks again."""


def ended(service: Service, state: State, seat: SeatId, log: Sequence[Event]) -> list[Ended]:
    """Each battle the seat's nation was a side of that has ended, with its closing odds
    (rule 7): the odds as they truly stood on its first day beside what the seat's own
    picture said. Computed on request from the log's ``battle_opened`` and the reports as
    they stood that day; kept in ``service``'s cache, never in the log. A battle still open
    is not here."""
    from revisionist.engine.web.battles_api import sides_of

    own_nation = _nation(state, seat)
    if own_nation is None or not battle.on(state):
        return []
    opened: dict[EntityId, int] = {}
    out: list[Ended] = []
    for n, e in enumerate(log):
        p = e.payload
        if isinstance(p, ev.BattleOpened):
            opened[p.battle.area] = n
        elif isinstance(p, ev.BattleEnded) and p.area in opened:
            first = opened.pop(p.area)
            o = log[first].payload
            assert isinstance(o, ev.BattleOpened)
            if sides_of(state, o.battle, own_nation) is None:
                continue
            key = f"closing\x1f{state.campaign_id}\x1f{seat}\x1f{log[first].seq}"
            head = log[: first + 1]

            def compute(
                head: Sequence[Event] = head, area: EntityId = p.area
            ) -> ClosingOdds | None:
                try:
                    return _closing(replay(head), seat, area)
                except ValueError:  # [proposed] no piece of the side stood there: no odds
                    return None

            try:
                found: ClosingOdds | None = service.ask(key, None, compute)
            except BusyError:
                found = None
            out.append(Ended(o.battle, p.on, found))
    return out


def reply(service: Service, state: State, seat: SeatId, body: Mapping[str, Any]) -> dict[str, Any]:
    """The ``odds`` action: the spread for the seat's request, or busy. Files nothing.
    Raises ``ValueError`` with the reason a request cannot be answered."""
    try:
        service.limit((str(state.campaign_id), str(seat)))
    except LimitedError:
        return {"reply": LIMITED, "refused": True, "busy": True}
    p = picture(state, seat, body)
    base = seed(state.campaign_id, wake_of(state), seat, p)
    try:
        odds = service.ask(base, None, lambda: spread(p, base))
    except BusyError:
        return {"reply": BUSY, "refused": True, "busy": True}
    return {"reply": "The odds as your own picture has them.", "refused": False, "odds": odds}


__all__ = [
    "BUSY",
    "CACHE",
    "HIGH_CENTILE",
    "LIMITED",
    "LOW_CENTILE",
    "ODDS_DAYS",
    "ODDS_RUNS",
    "PER_MINUTE",
    "QUEUE",
    "WORKERS",
    "BusyError",
    "Ended",
    "LimitedError",
    "Picture",
    "Seen",
    "Service",
    "closing_pictures",
    "ended",
    "picture",
    "reply",
    "seed",
    "spread",
    "wake_of",
]
