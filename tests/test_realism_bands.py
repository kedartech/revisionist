"""The Phase 0c historical run: the first gate of the realism build.

Ten campaign ids play autumn 1941 with the scripted orders of the record. The base
rates in the resolvers are [fitted] to this record, so a pass shows the machinery
(urgency, opinion, friction) keeps outcomes in range, not that it predicts them.
Prediction is Phase 6. Pass rule (BANDS.md): at least 80% of assertions in band,
none outside twice its band, votes 1-3 pass in every seed.

With ``groups`` on (GRD), the votes are the blocs' tallies, opinion is the figure the
American groups publish, and the day walk moves the groups as a tick does: the day's
happenings, the writing batch and the Monday drift.

With ``contests`` and ``aims`` on (AMC), the walk runs on to the last deciding day: each
day the contests take their moves and are decided on their day, and every aim on the
nine playable cards is checked from state. Each aim's status and each contest's end
are printed, for reading, not asserted.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core import goals
from revisionist.core.goals import Goal, GoalSource
from revisionist.core.ids import CampaignId, EntityId, ScheduledEventId, derived_id
from revisionist.core.ontology import Contest
from revisionist.core.realism import battle, contests, groups, holders
from revisionist.core.realism.pipeline import Order, StepAction, StepOutcome
from revisionist.core.realism.resolvers import (
    ON_DAY,
    ON_ORDER,
    movement,
    opinion,
    resolver_for,
    settled_on,
    shipping,
    value,
)
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from tests.test_realism_resolvers import Rig

SEEDS = [
    CampaignId(derived_id(CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV"), "seed", n)) for n in range(10)
]
START, END = date(1941, 9, 1), date(1941, 12, 1)
SEASON_END = date(1941, 12, 7)
"""The last deciding day: the walk runs on to it for the aims and contests (AMC)."""
ROSTER = (
    "roosevelt",
    "churchill",
    "stalin",
    "hitler",
    "konoe",
    "tojo",
    "mussolini",
    "chiang",
    "king",
)
"""The nine playable cards, in the world's roster order."""
FIRED = {
    date(1941, 9, 4): "greer_incident",
    date(1941, 10, 17): "kearny_hit",
    date(1941, 10, 31): "reuben_james_sunk",
}


@dataclass
class Script:
    person: str
    lever: str
    pipeline: str
    filed: date
    steps: list[date]
    settled: date
    params: dict[str, object]


SCRIPT = [
    Script("roosevelt", "public_address", "public_address", date(1941, 9, 9),
           [date(1941, 9, 10)], date(1941, 9, 10), {"theme": "freedom_of_the_seas"}),
    Script("roosevelt", "naval_order", "naval_order", date(1941, 9, 11),
           [date(1941, 9, 13), date(1941, 9, 15)], date(1941, 9, 15),
           {"order": "shoot_on_sight", "zone": "western_atlantic"}),
    Script("roosevelt", "send_bill", "bill_through_congress", date(1941, 10, 9),
           [date(1941, 10, 17), date(1941, 10, 18), date(1941, 11, 7), date(1941, 11, 17)],
           date(1941, 11, 17), {"bill": "neutrality_revision", "urgency": "urgent"}),
    Script("roosevelt", "lend_lease_finding", "lend_lease_allocation", date(1941, 10, 30),
           [date(1941, 11, 1), date(1941, 11, 3), date(1941, 11, 5)], date(1941, 11, 5),
           {"recipient": "ussr", "share_pct": 10}),
]  # fmt: skip


@dataclass
class Run:
    house: tuple[int, int]
    senate: tuple[int, int]
    concur: tuple[int, int]
    passed: int
    losses: tuple[int, int, int]
    finding_days: int
    eligible: int
    about_24sep: int
    about_end: int
    """The American opinion figure on the last day."""
    battles: list[tuple[date, str, str]]
    """Each battle that opened: the day, the area's key and the attacker's key (ITD)."""
    aims: dict[tuple[str, int], str]
    """Each playable card's aim, by person key and number: its status on the last day."""
    contests: dict[str, tuple[int, str]]
    """Each contest by key: its track and its winner's key (or "none") on the last day."""


def play(seed: CampaignId) -> Run:
    """One campaign from 1 Sep to 1 Dec; the figures the bands read."""
    r = Rig("autumn-1941", seed)
    r.seat("roosevelt")
    r.close_session_zero()
    aims = _aim_goals(r)
    orders: dict[int, Order] = {}
    about: dict[date, int | None] = {}
    sunk: list[int] = []
    battles: list[tuple[date, str, str]] = []
    day = START
    while day <= SEASON_END:
        if day > START:
            r.add(ev.DateAdvanced(to=day))
        day_from = r.state
        settled: list[Order] = []
        for n, s in enumerate(SCRIPT):
            if s.filed == day:
                orders[n] = r.draft(s.person, s.lever, s.pipeline, s.filed, **s.params)
            if n in orders and day in s.steps:
                k = s.steps.index(day)
                done = r.state.orders[orders[n].order_id]
                step = r.state.pipelines[done.pipeline].steps[k]
                r.add(
                    ev.OrderStepTaken(
                        order_id=done.order_id,
                        outcome=StepOutcome(
                            step=k, person=step.person, action=StepAction.PASS, on=day
                        ),
                    )
                )
            if n in orders and s.settled == day:
                settled.append(r.settle(orders[n]))
        if day in FIRED:
            r.add(ev.ScheduledEventFired(scheduled_id=ScheduledEventId(r.ids[FIRED[day]])))
        for order in settled:
            key = resolver_for(r.state, order)
            r.fold_changes(ON_ORDER[key](r.state, order))
        if day.day == 1 and day > START:
            sunk.append(sum(shipping.losses(r.state, day - timedelta(days=1)).values()))
        before = r.state
        for fn in ON_DAY.values():
            r.fold_changes(fn(r.state, day))
        opened, happened = _steps_and_battles(r, before, day)
        battles += opened
        _groups_walk(r, day_from, before, happened, day)
        _contests_and_aims(r, day_from, happened, day, aims)
        about[day] = _opinion(r)
        day += timedelta(days=1)

    def v(k: str) -> int:
        got = value(r.state, k)
        assert got is not None, k
        return got

    return Run(
        house=(v("neutrality_revision_house_yeas"), v("neutrality_revision_house_nays")),
        senate=(v("neutrality_revision_senate_yeas"), v("neutrality_revision_senate_nays")),
        concur=(v("neutrality_revision_concur_yeas"), v("neutrality_revision_concur_nays")),
        passed=v("neutrality_revision_passed"),
        losses=(sunk[0], sunk[1], sunk[2]),
        finding_days=(settled_on(r.state.orders[orders[3].order_id]) - SCRIPT[3].filed).days,
        eligible=v("soviet_lend_lease_eligible"),
        about_24sep=v_on(about, date(1941, 9, 24)),
        about_end=v_on(about, END),
        battles=battles,
        aims={k: goals.aim_status(r.state, g).value for k, g in aims.items()},
        contests={
            key: (k.track, "none" if k.winner is None else _key(r, k.winner))
            for key, k in _contests(r).items()
        },
    )


def _steps_and_battles(
    r: Rig, before: State, day: date
) -> tuple[list[tuple[date, str, str]], list[ev.Payload]]:
    """The day walk's territory steps, holders and battles, in its order (ITD): pieces met
    head-on, the steps, the holders, then the day's battle rounds and the count a won battle
    starts. The battles that opened today, by area and attacker key, and every payload
    folded, in order."""
    met = movement.head_on(r.state, day)
    folded: list[ev.Payload] = []

    def fold(payloads: Iterable[ev.Payload]) -> None:
        for payload in payloads:
            r.add(payload)
            folded.append(payload)

    fold(movement.walk(r.state, day))
    fold(holders.walk(r.state, day))
    open_before = r.state.battles
    fought = battle.walk(before, r.state, day, met)
    fold(fought)
    fold(holders.start_count(r.state, battle.won(fought, open_before), day))
    key = {EntityId(v): k for k, v in r.ids.items()}
    opened = [
        (day, key[p.battle.area], key[p.battle.attacker.nation])
        for p in fought
        if isinstance(p, ev.BattleOpened)
    ]
    return opened, folded


def _groups_walk(
    r: Rig, day_from: State, sea: State, happened: list[ev.Payload], day: date
) -> None:
    """The groups' part of the day walk, as a tick runs it (GRD): the day's happenings
    (``day_from`` is the state the day began from, ``sea`` the one the shipping rule sank
    from), then the writing batch and the Monday drift. Nothing with ``groups`` off."""
    for payload in groups.react(r.state, day_from, happened, day, sea=sea):
        r.add(payload)
    for payload in groups.batch(r.state, day):
        r.add(payload)
    for payload in groups.drift(r.state, day):
        r.add(payload)


def _aim_goals(r: Rig) -> dict[tuple[str, int], Goal]:
    """A goal for every aim with a rule on each playable card (AMC), as a claim makes one
    for its person. Kept beside the game, not folded: the run seats one person only, and
    an aim's status reads state and the goal alone."""
    seat = r.seats["roosevelt"]
    made: dict[tuple[str, int], Goal] = {}
    for key in ROSTER:
        person = EntityId(r.ids[key])
        card = r.state.cards[person]
        for i, rule in enumerate(card.aim_rules, start=1):
            if rule is None:
                continue
            made[(key, i)] = Goal(
                goal_id=goals.aim_goal_id(r.campaign, person, i),
                seat_id=seat,
                text=card.aims[i - 1],
                condition=rule.condition,
                kind=goals.goal_kind(rule.condition),
                clock_id=None,
                scope=private_to(seat),
                person=person,
                source=GoalSource.POST,
                aim=i,
            )
    return made


def _contests_and_aims(
    r: Rig,
    day_from: State,
    happened: list[ev.Payload],
    day: date,
    aims: dict[tuple[str, int], Goal],
) -> None:
    """The contests' part of the day walk (CON): the day's moves read from the state the
    day began from, then the deciding day; then every aim inside its period checked from
    state (AIM), its goal holding what the check found."""
    for moved in contests.moves(r.state, day_from, happened, day - timedelta(days=1), day):
        r.add(moved)
    for decided in contests.decisions(r.state, day):
        r.add(decided)
    for key, goal in aims.items():
        if goals.judged(r.state, goal):
            aims[key] = goal.model_copy(update={"holding": goals.goal_met(r.state, goal.condition)})


def _key(r: Rig, some_id: str) -> str:
    return next(k for k, v in r.ids.items() if v == some_id)


def _contests(r: Rig) -> dict[str, Contest]:
    return {_key(r, k.contest_id): k for k in r.state.contests.values()}


def _opinion(r: Rig) -> int | None:
    """The American opinion figure: with ``groups`` on, what the groups publish, else the
    Gallup "about right" quantity."""
    if groups.on(r.state):
        return opinion.figure(r.state, EntityId(r.ids["usa"]))
    return value(r.state, "gallup_fdr_about_right")


def v_on(series: dict[date, int | None], day: date) -> int:
    got = series[day]
    assert got is not None
    return got


@dataclass
class Check:
    seed: int
    band: str
    got: float
    lo: float
    hi: float

    @property
    def inside(self) -> bool:
        return self.lo <= self.got <= self.hi

    @property
    def twice(self) -> bool:
        mid, half = (self.lo + self.hi) / 2, (self.hi - self.lo) / 2
        return abs(self.got - mid) <= 2 * half


def margin(t: tuple[int, int]) -> int:
    return t[0] - t[1]


def checks_for(seed: int, f: Run) -> list[Check]:
    total = sum(f.losses)
    return [
        Check(seed, "1 House margin 121+-20", margin(f.house), 101, 141),
        Check(seed, "2 Senate margin 13+-6", margin(f.senate), 7, 19),
        Check(seed, "3 concurrence margin 18+-10", margin(f.concur), 8, 28),
        Check(seed, "4 losses 507k+-25%", total, 507_000 * 0.75, 507_000 * 1.25),
        Check(seed, "4 Oct above Nov", f.losses[1] - f.losses[2], 1, 10**9),
        Check(seed, "5 Soviet finding within 21 days", f.finding_days, 0, 21),
        Check(seed, "6 about right 24 Sep 57+-7", f.about_24sep, 50, 64),
    ]


def table(results: list[Run], checks: list[Check]) -> str:
    rows = [
        "seed  house      senate    concur      losses(Sep,Oct,Nov)      find  24Sep  1Dec  passed"
    ]
    for i, f in enumerate(results):
        rows.append(
            f"{i:>4}  {f.house!s:<10} {f.senate!s:<9} {f.concur!s:<11} "
            f"{f.losses!s:<24} {f.finding_days:>4}  {f.about_24sep:>5}  {f.about_end:>4}  "
            f"{f.passed}"
        )
    bad = [f"  seed {c.seed} {c.band}: {c.got}" for c in checks if not c.inside]
    fought = sorted({b for f in results for b in f.battles})
    opened = [
        f"  {b[0]} {b[1]}, {b[2]} attacking: in {sum(b in f.battles for f in results)} of"
        f" {len(results)} seeds"
        for b in fought
    ]
    return "\n".join(
        [
            *rows,
            "out of band:",
            *(bad or ["  none"]),
            "battles opened:",
            *(opened or ["  none"]),
            *ends(results),
        ]
    )


def ends(results: list[Run]) -> list[str]:
    """Each aim's status and each contest's end on the last deciding day, counted over the
    seeds (AMC): printed for reading, not a band."""
    rows = [f"aims on {SEASON_END} (seeds met / at risk / failed):"]
    for aim in sorted(results[0].aims, key=lambda k: (ROSTER.index(k[0]), k[1])):
        got = [f.aims[aim] for f in results]
        rows.append(
            f"  {aim[0]:<10} {aim[1]}  {got.count('met'):>2} / {got.count('at_risk'):>2} /"
            f" {got.count('failed'):>2}"
        )
    rows.append("contests (track, winner) per seed:")
    for key in sorted(results[0].contests):
        rows.append(f"  {key:<20} " + " ".join(f"{f.contests[key]}" for f in results))
    return rows


def test_the_historical_run_stays_in_its_bands() -> None:
    results = [play(s) for s in SEEDS]
    checks = [c for i, f in enumerate(results) for c in checks_for(i, f)]
    report = table(results, checks)
    print(report)
    for f in results:
        assert f.house[0] > f.house[1] and f.senate[0] > f.senate[1], report
        assert f.concur[0] > f.concur[1], report
        assert f.passed == 1 and f.eligible == 1, report
    assert all(c.twice for c in checks), report
    for f in results:  # ITD: Typhoon's battle runs under the battle rules in every seed
        assert (date(1941, 10, 7), "moscow_area", "germany") in f.battles, report
    share = sum(c.inside for c in checks) / len(checks)
    assert share >= 0.8, f"{share:.0%} in band\n{report}"
