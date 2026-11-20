"""Written statements land on groups, once a world day (GWA).

The toy world of ``test_free_writing_groups`` with ``groups`` on: a ruling's nudges are
proposed through ``groups.propose`` and the day's batch moves each group once, whatever the
number or the order of the statements. Every reply here is canned; no test calls a model.
"""

import json
from collections.abc import Callable, Sequence
from datetime import date
from itertools import permutations
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import apply, groups
from revisionist.core.realism.document import DocumentView
from revisionist.core.realism.effect import GroupNudge
from revisionist.core.realism.land import statement
from revisionist.core.realism.pass_world import PassWorld
from tests.test_adjacency_moves import Logged, day
from tests.test_free_writing_groups import (
    ILSE,
    NORRA,
    Canned,
    World,
    far_roads,
    filed,
    game,
    nudge,
    nudging,
    said,
    stage,
)

DAY = day(1)


def walk(g: Logged, first: date = DAY, last: date | None = None) -> list[ev.Event]:
    return g.walk(first, last or first)


def moved(out: Sequence[ev.Event], key: str) -> list[ev.GroupMoved]:
    return [
        e.payload for e in out if isinstance(e.payload, ev.GroupMoved) and e.payload.group == key
    ]


def proposed(out: Sequence[ev.Event]) -> list[ev.GroupProposed]:
    return [e.payload for e in out if isinstance(e.payload, ev.GroupProposed)]


def papers(out: Sequence[ev.Event], by: SeatId = ILSE) -> list[DocumentView]:
    return [
        e.payload.document
        for e in out
        if isinstance(e.payload, ev.DocumentIssued)
        and e.payload.document.title.startswith("Statement on")
        and e.scope.visible_to(by)
    ]


def lines(doc: DocumentView) -> list[str]:
    return [str(f.value) for f in doc.body if f.label == "Group"]


def by_theme(out: Sequence[ev.Event]) -> dict[str, str]:
    """Each statement's own report line, keyed by the theme it was ordered under."""
    return {
        next(str(f.value) for f in d.body if f.label == "Ordered"): lines(d)[0] for d in papers(out)
    }


def support(g: Logged, key: str) -> int | None:
    return groups.support(g.state, NORRA, key)


def file_all(g: Logged, statements: Sequence[tuple[str, str, int]]) -> list[OrderId]:
    """One statement each: its theme words, its text and the public's nudge, filed in
    order and ruled on at one sitting."""
    ids = [filed(g, n, said(theme), text) for n, (theme, text, _) in enumerate(statements, 1)]
    canned = Canned(
        lambda r: {
            "effects": [nudge("public", next(c for _, t, c in statements if t in r.prompt))],
            "reason": "The street took it.",
            "rationale": "canned",
        }
    )
    stage(g, canned)
    return ids


# --- rule 1: a listed theme lands through the batch -------------------------------------


def test_a_listed_theme_is_proposed_for_the_seat_and_moved_once_by_the_batch(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    filed(g, 1, said("bread for all"), "We will see every table set.")
    stage(g, nudging())
    out = walk(g)
    wrote = proposed(out)
    assert [(p.proposal.group, p.proposal.change, p.proposal.seat) for p in wrote] == [
        ("public", 2, ILSE),
        ("smiths", -1, ILSE),
    ]
    assert [m.change for m in moved(out, "public")] == [2]
    assert [m.cause for m in moved(out, "public")] == [groups.Cause.WRITING]
    assert support(g, "public") == 42 and support(g, "smiths") == 49


def test_an_applied_statement_never_moves_a_group_itself(tmp_path: Path) -> None:
    g = game(tmp_path)
    filed(g, 1, said("bread for all"), "We will see every table set.")
    stage(g, nudging())
    state = g.state
    out = apply.apply_due(state, DAY)
    assert [type(p) for p in out if isinstance(p, ev.GroupMoved)] == []
    assert groups.support(state, NORRA, "public") == 40


# --- rule 2: a ruling's nudge lands the same way -----------------------------------------


def test_a_nudge_from_the_estimator_is_proposed_and_batched(tmp_path: Path) -> None:
    g = game(tmp_path)
    filed(g, 1, said("the harvest"), "The mills will run all winter.")
    stage(g, nudging(nudge("public", 1)))
    out = walk(g)
    assert [(p.proposal.group, p.proposal.change) for p in proposed(out)] == [("public", 1)]
    assert support(g, "public") == 41


# --- rule 3: once a day for a seat, whichever statement counts ---------------------------

SAID = [("the harvest", "mills run", 1), ("the frontier", "frontier holds", 3)]
SAID += [("the winter", "winter stands", -2)]


def three(tmp: Path, order: Sequence[int], sittings: bool = False) -> tuple[Logged, list[ev.Event]]:
    g = game(tmp)
    if sittings:
        for n, i in enumerate(order, 1):
            file_all_one(g, n, SAID[i])
    else:
        file_all(g, [SAID[i] for i in order])
    return g, walk(g)


def file_all_one(g: Logged, n: int, one: tuple[str, str, int]) -> None:
    theme, text, change = one
    filed(g, n, said(theme), text)
    stage(g, nudging(nudge("public", change)))


def test_many_statements_in_a_day_move_a_group_once_by_the_largest(tmp_path: Path) -> None:
    g, out = three(tmp_path, (0, 1, 2))
    assert len(proposed(out)) == 3
    assert [m.change for m in moved(out, "public")] == [3]
    assert support(g, "public") == 43


def test_one_outcome_whatever_the_order_of_filing_and_the_sittings(tmp_path: Path) -> None:
    seen: set[str] = set()
    for n, order in enumerate(permutations(range(3))):
        for sittings in (False, True):
            sub = tmp_path / f"{n}-{sittings}"
            sub.mkdir()
            _, out = three(sub, order, sittings)
            seen.add(
                json.dumps(
                    [
                        [m.model_dump(mode="json") for m in moved(out, "public")],
                        by_theme(out),
                    ],
                    sort_keys=True,
                )
            )
    assert len(seen) == 1


def test_a_second_statement_says_the_group_has_already_heard_from_the_seat(
    tmp_path: Path,
) -> None:
    _, out = three(tmp_path, (0, 1, 2))
    said_lines = sorted(lines(d)[0] for d in papers(out))
    assert said_lines == [
        "The Norra Public +3",
        f"The Norra Public {apply.ALREADY_HEARD}",
        f"The Norra Public {apply.ALREADY_HEARD}",
    ]


def test_the_statement_the_batch_counts_gets_the_line_not_the_first_filed(
    tmp_path: Path,
) -> None:
    _, out = three(tmp_path, (0, 1, 2))
    assert by_theme(out) == {
        "Statement on the frontier": "The Norra Public +3",
        "Statement on the harvest": f"The Norra Public {apply.ALREADY_HEARD}",
        "Statement on the winter": f"The Norra Public {apply.ALREADY_HEARD}",
    }


def test_two_equal_statements_are_told_apart_by_their_words_in_any_order(
    tmp_path: Path,
) -> None:
    seen = []
    for n, order in enumerate(permutations(range(2))):
        sub = tmp_path / str(n)
        sub.mkdir()
        g = game(sub)
        for k, i in enumerate(order, 1):
            file_all_one(
                g, k, [("the harvest", "mills run", 2), ("the frontier", "frontier", 2)][i]
            )
        seen.append(by_theme(walk(g)))
    assert seen[0] == seen[1]
    assert sorted(seen[0].values()) == [
        "The Norra Public +2",
        f"The Norra Public {apply.ALREADY_HEARD}",
    ]


def test_filing_more_statements_wins_nothing(tmp_path: Path) -> None:
    (tmp_path / "one").mkdir()
    (tmp_path / "many").mkdir()
    one, _ = three(tmp_path / "one", (1,))
    many, _ = three(tmp_path / "many", (0, 1, 2))
    assert support(one, "public") == support(many, "public") == 43


def test_a_second_day_moves_the_group_again_within_the_week_cap(tmp_path: Path) -> None:
    g = game(tmp_path)
    file_all_one(g, 1, SAID[1])
    walk(g)
    file_all_one(g, 2, ("the harvest", "second day", 3))
    out = walk(g, day(2))
    assert [m.change for m in moved(out, "public")] == [3]
    assert support(g, "public") == 46


# --- rule 4: the report names each group moved and never says no change when one did -------


def test_the_report_names_each_group_that_moved_and_by_how_much(tmp_path: Path) -> None:
    g = game(tmp_path)
    filed(g, 1, said("bread for all"), "We will see every table set.")
    stage(g, nudging())
    out = walk(g)
    [paper] = papers(out)
    assert lines(paper) == ["The Norra Public +2", "The Smiths' Guild -1"]
    assert all("no change" not in str(f.value).casefold() for f in paper.body)


def test_a_group_whose_week_cap_is_spent_says_so_not_no_change(tmp_path: Path) -> None:
    g = game(tmp_path)
    file_all_one(g, 1, ("a", "first", 3))
    walk(g, day(1))
    file_all_one(g, 2, ("b", "second", 3))
    walk(g, day(2))
    file_all_one(g, 3, ("c", "third", 3))
    out = walk(g, day(3))
    [late] = [d for d in papers(out) if d.issued == day(3)]
    assert lines(late) == [f"The Norra Public {apply.NO_MOVE}"]


def test_a_nudge_for_a_game_without_groups_proposes_nothing(tmp_path: Path) -> None:
    def off(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy", "writing"]

    g = game(tmp_path, off)
    world = PassWorld(g.state)
    effect = GroupNudge(nation=NORRA, group="public", change=1)
    assert statement.nudge(world, effect, ILSE, "h", DAY) == []


# --- rule 5: with groups off, today's opinion path is unchanged --------------------------


def test_with_groups_off_a_statement_proposes_nothing(tmp_path: Path) -> None:
    def off(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy", "writing"]

    g = game(tmp_path, off)
    filed(g, 1, said("bread for all"), "We will see every table set.")
    stage(g, nudging(nudge("public", 1)))
    out = walk(g)
    assert proposed(out) == [] and moved(out, "public") == []
    assert all(lines(d) == [] for d in papers(out))


# --- the twin worlds, end to end -------------------------------------------------------------


def _mine(events: Sequence[ev.Event], who: SeatId) -> list[str]:
    return [
        json.dumps([e.payload.model_dump(mode="json"), e.scope.model_dump(mode="json")])
        for e in events
        if e.scope.visible_to(who) and not isinstance(e.payload, ev.CostLogged)
    ]


def _twin(
    tmp: Path, at: str, extra: Callable[[Logged], None] | None = None
) -> tuple[Logged, list[ev.Event]]:
    tmp.mkdir()
    g = game(tmp, far_roads(at))
    filed(g, 1, said("the enemy fleet"), "Tell the public where the Sudland galleys lie now.")
    filed(g, 2, said("the harvest"), "The mills will run all winter.")
    stage(g, nudging(nudge("public", 2)))
    return g, walk(g)


def test_twin_worlds_give_the_issuer_the_same_papers_notices_and_playback(tmp_path: Path) -> None:
    near, near_out = _twin(tmp_path / "near", "gulf_roads")
    far, far_out = _twin(tmp_path / "far", "far_roads")
    assert near.state.features != far.state.features
    assert _mine(near_out, ILSE) == _mine(far_out, ILSE)
    assert [m.change for m in moved(near_out, "public")] == [
        m.change for m in moved(far_out, "public")
    ]
    assert project(near.state, ILSE).model_dump_json() == project(far.state, ILSE).model_dump_json()


@pytest.mark.parametrize("key", ["smiths", "greens"])
def test_a_group_nobody_wrote_to_does_not_move(tmp_path: Path, key: str) -> None:
    g = game(tmp_path)
    filed(g, 1, said("the harvest"), "The mills will run all winter.")
    stage(g, nudging(nudge("public", 1)))
    out = walk(g)
    assert moved(out, key) == []
