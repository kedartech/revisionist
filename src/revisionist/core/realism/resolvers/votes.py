"""The votes resolver (plan, Phase 2 unit B3).

Floor tallies per party bloc; whip counts stay documents.

Each bloc's members voting are fixed at the Voteview record, and its yes-rate is
that record's rate. The base rates are [fitted] to the record they are tested
against, so the autumn-1941 bands test that the machinery (urgency, opinion,
friction) keeps outcomes in range, not that it predicts them. Prediction is
Phase 6.

Votes are computed at settlement, so a bill that fails the House still reached
the President's desk in the pipeline (2f: moving the floor vote into the step is
later work).
"""

from datetime import date, timedelta

from revisionist.core.ids import OrderId
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.effect import Clause, ClauseKind, ProposeMeasure
from revisionist.core.realism.pipeline import ADVANCES, Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.state import State

LEVER = "send_bill"

# (bloc, yeas, nays) among members voting. Voteview RH0770068 / RS0770084 / RH0770070 /
# RH0770063 / RS0770064 / RH0770066 / RS0770079.
Rows = tuple[tuple[str, int, int], ...]
NEUTRALITY_HOUSE: Rows = (("D", 218, 21), ("R", 39, 113), ("other", 2, 4))
NEUTRALITY_SENATE: Rows = (("D", 43, 15), ("R", 6, 21), ("other", 1, 1))
NEUTRALITY_CONCUR: Rows = (("D", 188, 53), ("R", 22, 137), ("other", 2, 4))
TALLIES: dict[str, dict[str, Rows]] = {
    "neutrality_revision": {
        "house": NEUTRALITY_HOUSE,
        "senate": NEUTRALITY_SENATE,
        "concur": NEUTRALITY_CONCUR,
    },
    "draft_extension": {
        "house": (("D", 181, 65), ("R", 21, 133), ("other", 1, 4)),
        "senate": (("D", 38, 16), ("R", 7, 13), ("other", 0, 1)),
    },
    "lend_lease_appropriation": {
        "house": (("D", 229, 8), ("R", 96, 56), ("other", 3, 3)),
        "senate": (("D", 43, 3), ("R", 15, 9), ("other", 1, 1)),
    },
    # [fitted, borrowed]: no record of its own, so it takes the neutrality rows.
    "arm_merchant_ships": {"house": NEUTRALITY_HOUSE, "senate": NEUTRALITY_SENATE},
}

URGENT_D_POINTS = 2  # [proposed]
OPINION_NEUTRAL = 57  # [proposed] the 8 Oct "about right" the shifts are measured from
FRICTION_POINTS = (
    1  # [proposed] per-bloc shift is drawn from -1..+1 points; chosen so the bands pass
)
BASE_OFFSET_POINTS = {"D": 4, "R": 2, "other": 0}
"""[fitted] to the 17 Oct to 13 Nov record: the points urgency (D +2) and opinion at 61 in the
historical run add, taken off the base rate so that run lands on the record."""
CONCUR_LAG_DAYS = 6  # [fitted] Senate 7 Nov to House concurrence 13 Nov


def _half_points(state: State, order_id: OrderId, chamber: str, bloc: str, urgent: bool) -> int:
    """The bloc's total shift in half-points, so the opinion term stays integral."""
    shift = -2 * BASE_OFFSET_POINTS[bloc]
    if bloc in ("D", "R"):
        about = rs.value(state, "gallup_fdr_about_right")
        shift += (OPINION_NEUTRAL if about is None else about) - OPINION_NEUTRAL
    if urgent and bloc == "D":
        shift += 2 * URGENT_D_POINTS
    draw = rs.friction(state, order_id, chamber, bloc, n=2 * FRICTION_POINTS + 1)
    return shift + 2 * (draw - FRICTION_POINTS)


def _clause(kind: ClauseKind, subject: str, amount: int | None = None) -> Clause:
    return Clause(kind=kind, subject=subject, amount=amount)


HISTORICAL: dict[str, ProposeMeasure] = {
    "neutrality_revision": ProposeMeasure(
        title="Neutrality Act revision",
        clauses=(
            _clause(ClauseKind.POWER, "arm merchant ships"),
            _clause(ClauseKind.LIMIT, "war zones closed to American ships"),
        ),
    ),
    "draft_extension": ProposeMeasure(
        title="Selective Service extension",
        clauses=(_clause(ClauseKind.POWER, "hold draftees beyond twelve months"),),
    ),
    "lend_lease_appropriation": ProposeMeasure(
        title="Lend-Lease appropriation",
        clauses=(_clause(ClauseKind.MONEY, "lend-lease supplies", 7_000_000_000),),
    ),
    "arm_merchant_ships": ProposeMeasure(
        title="Arming of merchant ships",
        clauses=(_clause(ClauseKind.POWER, "arm merchant ships"),),
    ),
}
"""Each key of TALLIES as its clause set [proposed]."""

NOVEL_ROWS: dict[str, Rows] = {
    "house": NEUTRALITY_HOUSE,
    "senate": NEUTRALITY_SENATE,
    "concur": NEUTRALITY_CONCUR,
}
"""[fitted, borrowed] rows a measure with no record of its own takes."""
NOVEL_REFERENCE = "neutrality_revision"
MONEY_STEP = 500_000_000  # [proposed] each started step of money moves R by one half-point
MONEY_CAP = 4  # [proposed]
# [proposed] Democrats back executive power and spending, Republicans resist both and favour limits.
CLAUSE_POINTS = {
    ("D", ClauseKind.POWER): 1,
    ("D", ClauseKind.LIMIT): -1,
    ("R", ClauseKind.POWER): -2,
    ("R", ClauseKind.LIMIT): 2,
}


def clause_points(bloc: str, clause: Clause) -> int:
    """A bloc's stance on one clause, in half-points (+ toward yes). [proposed]"""
    if clause.kind is ClauseKind.MONEY:
        if bloc == "D":
            return 1
        started = -(-(clause.amount or 0) // MONEY_STEP)
        return -min(MONEY_CAP, started) if bloc == "R" else 0
    return CLAUSE_POINTS.get((bloc, clause.kind), 0)


def measure_half_points(bloc: str, measure: ProposeMeasure) -> int:
    """Sum of clause_points over the clauses."""
    return sum(clause_points(bloc, c) for c in measure.clauses)


def _base(measure: ProposeMeasure, chamber: str) -> tuple[Rows, ProposeMeasure]:
    """The rows a measure starts from, and the historical measure they belong to."""
    for key, known in HISTORICAL.items():
        if known.title == measure.title and chamber in TALLIES[key]:
            return TALLIES[key][chamber], known
    return NOVEL_ROWS[chamber], HISTORICAL[NOVEL_REFERENCE]


def _tally(
    state: State, order_id: OrderId, chamber: str, rows: Rows, urgent: bool, extra: dict[str, int]
) -> tuple[int, int]:
    yeas = nays = 0
    for bloc, y, n in rows:
        voters = y + n
        half = _half_points(state, order_id, chamber, bloc, urgent) + extra.get(bloc, 0)
        by = min(voters, max(0, y + (voters * half + 100) // 200))
        yeas, nays = yeas + by, nays + voters - by
    return yeas, nays


def tally_measure(
    state: State, order_id: OrderId, measure: ProposeMeasure, chamber: str, urgent: bool
) -> tuple[int, int]:
    """(yeas, nays) for a measure in one chamber."""
    rows, reference = _base(measure, chamber)
    extra = {
        bloc: measure_half_points(bloc, measure) - measure_half_points(bloc, reference)
        for bloc, _, _ in rows
    }
    return _tally(state, order_id, chamber, rows, urgent, extra)


def tally(state: State, order: Order, chamber: str, rows: Rows) -> tuple[int, int]:
    """(yeas, nays) for one chamber vote under the order's parameters."""
    urgent = order.params.get("urgency") == "urgent"
    return _tally(state, order.order_id, chamber, rows, urgent, {})


def _step_day(order: Order, step: int) -> date:
    days = [o.on for o in order.outcomes if o.step == step and o.action in ADVANCES]
    return days[-1] if days else rs.settled_on(order)


def resolve(state: State, order: Order) -> tuple[QuantityChange, ...]:
    """Changes from one order enacted through its pipeline."""
    bill = order.params.get("bill")
    if order.status is not OrderStatus.ENACTED or order.lever != LEVER or bill not in TALLIES:
        return ()
    house_day, senate_day = _step_day(order, 0), _step_day(order, 2)
    days = {
        "house": house_day,
        "senate": senate_day,
        "concur": senate_day + timedelta(days=CONCUR_LAG_DAYS),
    }
    out: list[QuantityChange | None] = []
    passed = 1
    urgent = order.params.get("urgency") == "urgent"
    for chamber in TALLIES[str(bill)]:
        yeas, nays = tally_measure(state, order.order_id, HISTORICAL[str(bill)], chamber, urgent)
        out += [
            put(state, f"{bill}_{chamber}_yeas", yeas, days[chamber]),
            put(state, f"{bill}_{chamber}_nays", nays, days[chamber]),
        ]
        passed &= int(yeas > nays)
    out.append(put(state, f"{bill}_passed", passed, rs.settled_on(order)))
    return tuple(c for c in out if c is not None)


def put(state: State, key: str, value: int, as_of: date) -> QuantityChange | None:
    """A change to ``key``, or None when the world never declared it."""
    if rs.qid(state, key) not in state.quantities:
        return None
    return QuantityChange(quantity_id=rs.qid(state, key), value=value, as_of=as_of)


def on_day(state: State, today: date) -> tuple[QuantityChange, ...]:
    """Votes move with orders only: nothing changes with time alone."""
    return ()
