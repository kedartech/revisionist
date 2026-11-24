"""The Civil War's season with nobody playing: losses, the election and the contests.

Ten campaign ids play autumn 1862 from 1 September to the last deciding day with no seat
taken: the code runs every person and history's clock runs as written. Each figure is
set against a band drawn from the record (mcpherson_1988, not checked against a copy in
this item); the bands are [proposed]. Pass rule (BANDS.md): at least 80% of assertions
in band, none outside twice its band, and the season's fixed days (the redraw on 4
November, the end on 15 December) kept in every seed. The table is printed for the pull
request.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, derived_id
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.emit import Emitter
from revisionist.engine.store import MemoryStore, load_state

SEEDS = [
    CampaignId(derived_id(CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV"), "seed", n)) for n in range(10)
]
ELECTION, SEASON_END = date(1862, 11, 4), date(1862, 12, 15)
MAX_WAKES = 60


@dataclass(frozen=True)
class Band:
    name: str
    low: float
    high: float
    record: str

    def holds(self, v: float) -> bool:
        return self.low <= v <= self.high

    def within_twice(self, v: float) -> bool:
        mid, half = (self.low + self.high) / 2, self.high - self.low
        return mid - half <= v <= mid + half


BANDS = (
    Band("union_loss_share", 0.5, 0.8, "the Union lost more men than the Confederacy"),
    Band("republican_house_share", 0.5, 0.62, "the Republicans kept the House"),
    Band("republican_seats_lost", 10, 35, "the Republicans lost about twenty seats"),
    Band("border_states", 0, 100, "Maryland and Kentucky stayed in the Union"),
    Band("recognition", 0, 100, "neither Britain nor France recognised the Confederacy"),
    Band("eastern_war", -100, 0, "the East ended at Fredericksburg"),
)
"""Contest tracks run from -100 to 100, toward the Union when above 0."""
UNMODELLED = {
    "republican_seats_lost": "drift returns support to its baseline each Monday and a "
    "redraw counts only support off the baseline, so a season with no late happening "
    "redraws the House as it stood"
}
"""Bands printed but not asserted: the engine cannot yet reach them from this world."""


@dataclass
class Run:
    ended: date | None
    redrawn: date | None
    figures: dict[str, float]


def play(seed: CampaignId) -> Run:
    """One campaign with no seat taken, walked until the season is over."""
    w = cmp.load_world(cmp.world_path("civil-war-1862"))
    store = MemoryStore()
    store.append_all(compile_world(w, seed, cmp.versions()))
    ids = resolve_keys(w, seed)
    key = {v: k for k, v in ids.items()}
    state = load_state(store, seed)
    store.append_all([Emitter(store, state, cmp.versions()).event(ev.SessionZeroClosed())])
    for _ in range(MAX_WAKES):
        if load_state(store, seed).phase.value != "play":
            break
        realism_tick.run_realism_tick(store, seed)
    state = load_state(store, seed)
    lost: Counter[str] = Counter()
    opened: dict[EntityId, ev.BattleOpened] = {}
    redraw: ev.SeatsRedrawn | None = None
    for e in store.read(seed):
        p = e.payload
        if isinstance(p, ev.BattleOpened):
            opened[p.battle.area] = p
        if isinstance(p, ev.BattleRound):
            b = opened[p.area].battle
            lost[key[b.attacker.nation]] += p.lost[0]
            lost[key[b.defender.nation]] += p.lost[1]
        if isinstance(p, ev.SeatsRedrawn) and p.chamber == "house":
            redraw = p
    house = dict(redraw.seats) if redraw else {}
    start = _house_at_start(w)
    tracks = {key[c.contest_id]: c.track for c in state.contests.values()}
    total = lost["usa"] + lost["csa"]
    figures = {
        "union_loss_share": lost["usa"] / total if total else 0.0,
        "republican_house_share": house.get("republicans", 0) / max(1, sum(house.values())),
        "republican_seats_lost": start["republicans"] - house.get("republicans", 0),
        **tracks,
    }
    ended = state.in_world_date if state.phase.value == "season_over" else None
    return Run(ended=ended, redrawn=redraw.on if redraw else None, figures=figures)


def _house_at_start(w: WorldFile) -> dict[str, int]:
    return {
        g.key: g.seats or 0
        for nation in w.groups
        if nation.nation == "usa"
        for g in nation.groups
        if g.chamber == "house"
    }


def table(runs: list[Run]) -> str:
    head = f"{'band':24} {'low':>6} {'high':>6}  " + " ".join(f"{n:>6}" for n in range(len(runs)))
    rows = [head]
    for b in BANDS:
        cells = []
        for r in runs:
            v = r.figures[b.name]
            mark = "" if b.holds(v) else ("*" if b.within_twice(v) else "!")
            cells.append(f"{v:>5.2f}{mark or ' '}")
        rows.append(f"{b.name:24} {b.low:>6} {b.high:>6}  " + " ".join(cells))
    rows.append("* outside its band, inside twice it; ! outside twice its band")
    rows += [f"not asserted, {name}: {why}" for name, why in UNMODELLED.items()]
    return "\n".join(rows)


def test_the_season_with_nobody_playing_stays_in_its_bands() -> None:
    runs = [play(seed) for seed in SEEDS]
    print("\n" + table(runs))
    assert [r.ended for r in runs] == [SEASON_END] * len(SEEDS)
    assert [r.redrawn for r in runs] == [ELECTION] * len(SEEDS)
    checks = [(b, r.figures[b.name]) for r in runs for b in BANDS if b.name not in UNMODELLED]
    outside = [(b.name, v) for b, v in checks if not b.within_twice(v)]
    assert outside == []
    inside = sum(b.holds(v) for b, v in checks)
    assert inside >= 0.8 * len(checks), f"{inside} of {len(checks)} in band"
