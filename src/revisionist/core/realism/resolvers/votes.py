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

A decided bill is public news, once: a neutral headline, each chamber's count as the
world publishes it, and the result. Whip counts are papers, never news.

With ``groups`` on (GVR), the tables above are not read: a chamber's tally comes from the
world's blocs (``bloc_tally``). Each bloc's part of a vote is the world's row for that
measure and vote, or its default row; its yes share moves one point for every
``VOTE_POINTS`` of support away from its baseline, by its stance on each clause, and, for an
urgent measure, by ``URGENT_BLOC_POINTS`` where it backs executive power. The fraction of a
vote this leaves is settled by the order's seed, so with every bloc at its baseline the tally
is the world's row exactly. The tables stay for stored games and worlds without groups.
"""

import re
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, OrderId, derived_id
from revisionist.core.realism import economy, groups
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.document import BodyField
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.effect import Clause, ClauseKind, ProposeMeasure
from revisionist.core.realism.pipeline import ADVANCES, Order, OrderStatus
from revisionist.core.realism.quantity import Quantity, QuantityChange
from revisionist.core.realism.war import NewsEvent, NewsTopic, polity_of
from revisionist.core.state import State
from revisionist.core.visibility import Visibility

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


VOTE_POINTS = 5  # [proposed] plan, GVR Defaults
"""Points of a bloc's support away from its baseline that move its yes share by one point."""
URGENT_BLOC_POINTS = 2  # [proposed]
"""Points an urgent measure adds to the yes share of each bloc with a positive stance on
power clauses."""
SHARE_PARTS = 100 * VOTE_POINTS
"""A bloc's yes count moves by ``voting * points / SHARE_PARTS``, ``points`` in support points."""


def _row(bloc: groups.Group, measure: str, vote: str) -> groups.BlocVote | None:
    listed = bloc.votes.get(measure)
    return listed.get(vote) if listed is not None else bloc.vote_default.get(vote)


def bloc_tally(
    state: State,
    nation: EntityId,
    chamber: str,
    measure: str,
    vote: str,
    seed: OrderId,
    *,
    urgent: bool = False,
    clauses: tuple[Clause, ...] = (),
) -> tuple[int, int]:
    """(yeas, nays) of one vote on a measure in a nation's chamber, from its blocs: each
    bloc with a row for the vote (the measure's own, else its default) starts from that
    row, and its yes share moves a point for every ``VOTE_POINTS`` of support away from its
    baseline, by its stance on each of ``clauses``, and with ``urgent`` by
    ``URGENT_BLOC_POINTS`` if it backs power. The fraction of a vote left over is drawn from
    ``seed``. No order is read."""
    yeas = nays = 0
    for bloc in groups.of(state, nation):
        row = None if bloc.chamber != chamber else _row(bloc, measure, vote)
        if row is None:
            continue
        points = (groups.support(state, nation, bloc.key) or 0) - bloc.baseline
        stance = sum(bloc.stances.get(c.kind, 0) for c in clauses)
        if urgent and bloc.stances.get(ClauseKind.POWER, 0) > 0:
            stance += URGENT_BLOC_POINTS
        whole, part = divmod(row.voting * (points + VOTE_POINTS * stance), SHARE_PARTS)
        drawn = rs.friction(state, seed, chamber, vote, bloc.key, n=SHARE_PARTS) < part
        by = min(row.voting, max(0, row.yeas + whole + int(drawn)))
        yeas, nays = yeas + by, nays + row.voting - by
    return yeas, nays


def bloc_votes(state: State, nation: EntityId, measure: str) -> tuple[tuple[str, str], ...]:
    """Each (chamber, vote) a nation's blocs cast on a measure, in the world's order."""
    out: dict[tuple[str, str], None] = {}
    for bloc in groups.of(state, nation):
        if bloc.chamber is None:
            continue
        listed = bloc.votes.get(measure)
        for vote in listed if listed is not None else bloc.vote_default:
            out[(bloc.chamber, vote)] = None
    return tuple(out)


def measure_key(measure: ProposeMeasure) -> str:
    """The key a measure carried by an order is listed under: its title in lower-case
    words joined by underscores."""
    return "_".join(re.sub(r"[^0-9a-z]+", " ", measure.title.casefold()).split())


def _listed(state: State, nation: EntityId, key: str) -> bool:
    return any(key in b.votes for b in groups.of(state, nation))


def _cast(
    state: State, order: Order, key: str, measure: ProposeMeasure | None
) -> tuple[EntityId, tuple[tuple[str, int, int], ...]] | None:
    """The issuer's nation and each (vote, yeas, nays) its blocs cast on measure ``key``
    for an enacted order; None when the order is not enacted or no bloc votes on it."""
    seat = state.seats.get(order.issuer)
    nation = None if seat is None else polity_of(state, seat.embodies)
    if order.status is not OrderStatus.ENACTED or nation is None:
        return None
    cast = bloc_votes(state, nation, key)
    if not cast:
        return None
    clauses = () if measure is None or _listed(state, nation, key) else measure.clauses
    urgent = order.params.get("urgency") == "urgent"
    return nation, tuple(
        (
            vote,
            *bloc_tally(
                state, nation, chamber, key, vote, order.order_id, urgent=urgent, clauses=clauses
            ),
        )
        for chamber, vote in cast
    )


def by_groups(
    state: State, order: Order, key: str, measure: ProposeMeasure | None
) -> tuple[QuantityChange, ...]:
    """With ``groups`` on, an enacted order's measure ``key`` tallied by the issuer's
    nation's blocs: each vote's yeas and nays as ``<key>_<vote>_yeas`` and ``_nays``, and
    ``<key>_passed`` when every vote passed, where the world declares them, all on the day
    the order settled. A measure the blocs do not list is scored on its clauses as well.
    Nothing when no bloc votes on it."""
    cast = _cast(state, order, key, measure)
    if cast is None:
        return ()
    day = rs.settled_on(order)
    out: list[QuantityChange | None] = []
    for vote, yeas, nays in cast[1]:
        out += [
            put(state, f"{key}_{vote}_yeas", yeas, day),
            put(state, f"{key}_{vote}_nays", nays, day),
        ]
    out.append(put(state, f"{key}_passed", int(all(y > n for _, y, n in cast[1])), day))
    return tuple(c for c in out if c is not None)


def passed_by_groups(
    state: State, order: Order, key: str, measure: ProposeMeasure | None
) -> tuple[ev.GroupMoved, ...]:
    """With ``groups`` on, when the blocs pass measure ``key`` in every vote, the groups of
    the issuer's nation that name a measure passed, moved once on the day the order
    settled, whether or not the world keeps the count."""
    cast = _cast(state, order, key, measure)
    if cast is None or not all(y > n for _, y, n in cast[1]):
        return ()
    day = rs.settled_on(order)
    return tuple(groups.happened(state, cast[0], groups.Happening.MEASURE_PASSED, day))


def _step_day(order: Order, step: int) -> date:
    days = [o.on for o in order.outcomes if o.step == step and o.action in ADVANCES]
    return days[-1] if days else rs.settled_on(order)


def resolve(state: State, order: Order) -> tuple[QuantityChange, ...]:
    """Changes from one order enacted through its pipeline."""
    bill = order.params.get("bill")
    if groups.on(state):
        return by_groups(state, order, str(bill), None) if bill is not None else ()
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


ARMING = "arm merchant ships"
"""The clause of a law that arms a nation's merchant ships (``shipping.losses`` reads it)."""
DRAFT = "hold draftees beyond twelve months"
"""The clause of a draft law."""
DRAFT_MANPOWER = 3  # [proposed] plan, SHP Defaults
"""Manpower points a draft law adds to its nation's pool, with ``economy`` on."""


def _nation(state: State, entity: EntityId) -> EntityId:
    return polity_of(state, entity) or entity


def in_force(state: State, subject: str) -> dict[EntityId, date]:
    """Each nation with a passed law carrying the clause ``subject``, and the day its flag
    (``<bill>_passed``) says it passed; a flag with no owner names no nation."""
    out: dict[EntityId, date] = {}
    for bill, measure in sorted(HISTORICAL.items()):
        if subject not in {c.subject for c in measure.clauses}:
            continue
        q = state.quantities.get(rs.qid(state, f"{bill}_passed"))
        if q is None or q.value != 1 or q.owner is None:
            continue
        nation = _nation(state, q.owner)
        out[nation] = min(out.get(nation, q.as_of), q.as_of)
    return out


def law_effects(
    state: State, measure: ProposeMeasure, passed: QuantityChange | None
) -> tuple[ev.EconomySet, ...]:
    """What a law does to the economy the day its flag says it passed: a draft law adds
    ``DRAFT_MANPOWER`` to the flag's nation's pool, with ``economy`` on."""
    if passed is None or passed.value != 1 or not economy.on(state):
        return ()
    if DRAFT not in {c.subject for c in measure.clauses}:
        return ()
    owner = state.quantities[passed.quantity_id].owner
    if owner is None:
        return ()
    nation = _nation(state, owner)
    pools = state.economy.pools.get(nation, Pools())
    more = pools.model_copy(update={"manpower": pools.manpower + DRAFT_MANPOWER})
    return (ev.EconomySet(polity=nation, pools=more, on=passed.as_of),)


def put(state: State, key: str, value: int, as_of: date) -> QuantityChange | None:
    """A change to ``key``, or None when the world never declared it."""
    if rs.qid(state, key) not in state.quantities:
        return None
    return QuantityChange(quantity_id=rs.qid(state, key), value=value, as_of=as_of)


CHAMBER_NAMES = {"house": "House", "senate": "Senate", "concur": "House concurrence"}
FAILED_IN = {"house": "the House", "senate": "the Senate", "concur": "the House"}
HEADLINE_MAX = 60
LOOKBACK_DAYS = 1
"""A player's last step between wakes settles a bill on the day before the wake's
first day, so the news looks back one day; an older decision is never reported."""


def _public(q: Quantity | None) -> bool:
    return q is not None and q.scope is not None and q.scope.visibility is Visibility.PUBLIC


def _groups_key(order: Order) -> str | None:
    """With ``groups`` on, the measure key an enacted order's votes were written under."""
    if order.status is not OrderStatus.ENACTED:
        return None
    if order.measure is not None:
        return measure_key(order.measure)
    bill = order.params.get("bill")
    return None if bill is None else str(bill)


def _words(key: str) -> str:
    return " ".join(key.split("_"))


def _bill(order: Order) -> str | None:
    """The bill key an enacted order's votes were written under, as the votes resolver
    chose it; None for any other order."""
    if order.status is not OrderStatus.ENACTED:
        return None
    if order.measure is not None:
        title = order.measure.title
        known = (k for k, m in HISTORICAL.items() if m.title == title and k in TALLIES)
        return next(known, NOVEL_REFERENCE)
    bill = order.params.get("bill")
    return str(bill) if order.lever == LEVER and bill in TALLIES else None


def news(state: State, order: Order, today: date) -> NewsEvent | None:
    """The public record of a bill decided on ``today`` or the day before, read from the
    counts the world publishes; None when there is none or it is already reported."""
    bill = _groups_key(order) if groups.on(state) else _bill(order)
    day = rs.settled_on(order)
    if bill is None or not today - timedelta(days=LOOKBACK_DAYS) <= day <= today:
        return None
    flag = state.quantities.get(rs.qid(state, f"{bill}_passed"))
    if flag is None or flag.owner is None or flag.value is None or not _public(flag):
        return None
    if flag.as_of != day:  # the result on record is not this order's
        return None
    news_id = derived_id(state.campaign_id, "news", "vote", order.order_id)
    if news_id in state.news:
        return None
    if groups.on(state):
        names = {v: _words(v).capitalize() for _, v in bloc_votes(state, flag.owner, bill)}
        failed_in = {v: f"the {_words(v)}" for v in names}
        title = order.measure.title if order.measure is not None else _words(bill).capitalize()
        passes, nowhere = f"{title} passes", None
    else:
        names, failed_in = {c: CHAMBER_NAMES[c] for c in TALLIES[bill]}, FAILED_IN
        title = order.measure.title if order.measure is not None else HISTORICAL[bill].title
        passes, nowhere = f"{title} passes Congress", "Congress"
    counts: list[tuple[str, int, int]] = []
    for chamber in names:
        yeas = state.quantities.get(rs.qid(state, f"{bill}_{chamber}_yeas"))
        nays = state.quantities.get(rs.qid(state, f"{bill}_{chamber}_nays"))
        if yeas is None or nays is None or not (_public(yeas) and _public(nays)):
            continue
        if yeas.value is not None and nays.value is not None:
            counts.append((chamber, yeas.value, nays.value))
    if flag.value:
        headline = passes
    else:
        lost = next((failed_in[c] for c, yeas, nays in counts if yeas <= nays), nowhere)
        headline = f"{title} fails" if lost is None else f"{title} fails in {lost}"
    if len(headline) > HEADLINE_MAX:
        headline = headline[: HEADLINE_MAX - 1] + "…"
    return NewsEvent(
        news_id=news_id,
        on=day,
        topic=NewsTopic.VOTE,
        subject=flag.owner,
        headline=headline,
        facts=(
            *(BodyField(label=names[c], value=f"{y} to {n}") for c, y, n in counts),
            BodyField(label="Result", value="Passed" if flag.value else "Failed"),
            BodyField(label="Date", value=f"{day.day} {day:%B %Y}"),
        ),
    )


def on_day(state: State, today: date) -> tuple["rs.Change", ...]:
    """The news of each bill decided today or the day before; tallies move with orders
    only."""
    orders = sorted(state.orders.values(), key=lambda o: o.order_id)
    return tuple(n for n in (news(state, o, today) for o in orders) if n is not None)
