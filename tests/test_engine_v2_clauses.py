"""Bills as clause sets (engine v2, unit A3): the votes resolver scores each bloc per clause."""

from datetime import date

import pytest

from revisionist.core.ids import CampaignId, OrderId, PipelineId, SeatId, derived_id
from revisionist.core.realism.effect import Clause, ClauseKind, ProposeMeasure
from revisionist.core.realism.pipeline import Order
from revisionist.core.realism.resolvers import votes
from tests.test_realism_bands import SEEDS
from tests.test_realism_resolvers import Rig

CASES = [(b, c) for b, chambers in votes.TALLIES.items() for c in chambers]
MEMBERS = {"house": 435, "senate": 96, "concur": 435}


def legacy(seed: CampaignId, urgent: bool) -> Order:
    return Order(
        order_id=OrderId(derived_id(seed, "order", 1)),
        issuer=SeatId(derived_id(seed, "seat", "roosevelt")),
        lever=votes.LEVER,
        pipeline=PipelineId(derived_id(seed, "pipeline", "bill")),
        params={"urgency": "urgent"} if urgent else {},
        filed=date(1941, 10, 9),
    )


def novel(*extra: Clause, title: str = "Novel measure") -> ProposeMeasure:
    base = votes.HISTORICAL["neutrality_revision"].clauses
    return ProposeMeasure(title=title, clauses=base + extra)


def yeas_by_bloc(r: Rig, measure: ProposeMeasure, chamber: str = "house") -> dict[str, int]:
    """Yeas per bloc, by tallying the rows one bloc at a time."""
    order_id = OrderId(derived_id(r.campaign, "order", 1))
    rows, reference = votes._base(measure, chamber)
    out = {}
    for row in rows:
        extra = {
            row[0]: votes.measure_half_points(row[0], measure)
            - votes.measure_half_points(row[0], reference)
        }
        out[row[0]] = votes._tally(r.state, order_id, chamber, (row,), False, extra)[0]
    return out


@pytest.mark.parametrize("urgent", [False, True])
@pytest.mark.parametrize(("bill", "chamber"), CASES)
def test_historical_clause_sets_reproduce_the_fitted_tallies(
    bill: str, chamber: str, urgent: bool
) -> None:
    for seed in SEEDS:
        r = Rig("autumn-1941", seed)
        order = legacy(seed, urgent)
        expected = votes.tally(r.state, order, chamber, votes.TALLIES[bill][chamber])
        got = votes.tally_measure(r.state, order.order_id, votes.HISTORICAL[bill], chamber, urgent)
        assert got == expected


@pytest.mark.parametrize(
    ("chamber", "record"),
    [("house", (259, 138)), ("senate", (50, 37)), ("concur", (212, 194))],
)
def test_neutrality_rows_still_sum_to_the_record(chamber: str, record: tuple[int, int]) -> None:
    # The record sums pinned in test_realism_resolvers are the rows, not tally outputs.
    for rows in (votes.NOVEL_ROWS[chamber], votes.TALLIES["neutrality_revision"][chamber]):
        assert (sum(y for _, y, _ in rows), sum(n for _, _, n in rows)) == record


def test_a_limit_clause_moves_republicans_up_and_democrats_down() -> None:
    limit = Clause(kind=ClauseKind.LIMIT, subject="no convoys")
    for seed in SEEDS:
        r = Rig("autumn-1941", seed)
        before, after = yeas_by_bloc(r, novel()), yeas_by_bloc(r, novel(limit))
        assert after["R"] > before["R"]
        assert after["D"] < before["D"]
        assert yeas_by_bloc(r, novel(limit)) == after


def test_a_power_clause_does_the_reverse() -> None:
    power = Clause(kind=ClauseKind.POWER, subject="convoy authority")
    for seed in SEEDS:
        r = Rig("autumn-1941", seed)
        before, after = yeas_by_bloc(r, novel()), yeas_by_bloc(r, novel(power))
        assert after["R"] < before["R"]
        assert after["D"] > before["D"]


def test_a_large_money_clause_lowers_republican_yeas() -> None:
    money = Clause(kind=ClauseKind.MONEY, subject="fleet", amount=10_000_000_000)
    for seed in SEEDS:
        r = Rig("autumn-1941", seed)
        assert yeas_by_bloc(r, novel(money))["R"] < yeas_by_bloc(r, novel())["R"]


def test_money_points_count_started_steps_and_cap() -> None:
    def pts(bloc: str, amount: int) -> int:
        return votes.clause_points(bloc, Clause(kind=ClauseKind.MONEY, subject="x", amount=amount))

    assert pts("R", 1) == -1
    assert pts("R", 500_000_000) == -1
    assert pts("R", 500_000_001) == -2
    assert pts("R", 10**12) == -4
    assert pts("D", 10**9) == 1
    assert pts("other", 10**9) == 0


@pytest.mark.parametrize("chamber", ["house", "senate", "concur"])
def test_a_novel_measure_takes_the_neutrality_rows(chamber: str) -> None:
    for seed in SEEDS:
        r = Rig("autumn-1941", seed)
        oid = OrderId(derived_id(seed, "order", 1))
        measure = novel()
        yeas, nays = votes.tally_measure(r.state, oid, measure, chamber, False)
        rows = votes.NOVEL_ROWS[chamber]
        assert yeas + nays == sum(y + n for _, y, n in rows) <= MEMBERS[chamber]
        hist = votes.HISTORICAL["neutrality_revision"]
        same = votes.tally_measure(r.state, oid, hist, chamber, False)
        assert (yeas, nays) == same


def test_historical_has_one_distinct_entry_per_tally_key() -> None:
    assert set(votes.HISTORICAL) == set(votes.TALLIES)
    titles = [m.title for m in votes.HISTORICAL.values()]
    assert len(set(titles)) == len(titles)
