"""Contests that move and decide (CON).

The toy world (``tests/worlds/territory-toy.yaml``) is played with one contest added, a
rivalry of Norra (the first side, the track's top) and Sudland, with ``holders``,
``agreements``, ``groups`` and ``contests`` on. Each move lands ``contest_moved`` once,
toward its side; on the deciding day, the start date plus the countdown, the contest is
decided for the side ahead, or for nobody on a level track. With the rule off nothing
moves or decides. The score counts what happened, never the orders filed.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.fold import FoldError
from revisionist.core.ids import ContestId, EntityId, QuantityId
from revisionist.core.ontology import Contest, ContestMove, MoveKind
from revisionist.core.realism import contests
from revisionist.core.realism.agreement import Agreement, ClauseStatus
from revisionist.core.realism.battle import Ending
from revisionist.core.realism.effect import AgreementClause, ClauseType
from revisionist.core.realism.groups import Cause
from revisionist.core.realism.quantity import Quantity
from revisionist.core.state import Rule, State
from revisionist.core.visibility import PUBLIC, Scope, Visibility
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import object_id
from revisionist.engine import realism_tick
from revisionist.engine.web.stakes import seat_stakes
from tests.test_adjacency_moves import START, Logged, entity, seat, toy
from tests.test_territory_model import CAMPAIGN, created, refused

World = dict[str, Any]
NORRA, SUDLAND = entity("norra"), entity("sudland")
HILLS, PLAIN, COAST, ISLE = (
    entity(k) for k in ("norra_hills", "norra_plain", "sudland_coast", "isle")
)
BORDER = ContestId(object_id(CAMPAIGN, "contest", "border"))
LEVY_ACT = QuantityId(object_id(CAMPAIGN, "quantity", "levy_act_passed"))
SHIPPING = QuantityId(object_id(CAMPAIGN, "quantity", "norra_shipping"))
RULES = ("territories", "holders", "agreements", "groups", "contests")


def day(n: int) -> date:
    return START + timedelta(days=n)


def border(*moves: dict[str, Any], countdown: int = 30, track: int = 0) -> Callable[[World], None]:
    """The border contest, Norra against Sudland, with ``moves``; a public flag."""

    def change(w: World) -> None:
        w["contests"] = [
            {
                "key": "border",
                "kind": "rivalry",
                "name": "The Border War",
                "prize": "The hills",
                "sides": ["norra", "sudland"],
                "track": track,
                "countdown_days": countdown,
                "moves": list(moves),
            }
        ]
        w["assets"] = [  # each leader holds an office in the contest (the roster rule)
            {"key": "chancellery", "kind": "office", "name": "Chancellery", "tier": 3,
             "controller": "ilse"},
            {"key": "premiership", "kind": "office", "name": "Premiership", "tier": 3,
             "controller": "tomas"},
        ]  # fmt: skip
        w["quantities"].append(
            {
                "key": "levy_act_passed",
                "owner": "norra",
                "name": "Whether the Levy Act became law (1 yes, 0 no)",
                "value": 0,
                "unit": "flag",
                "public": True,
                "source": "toy",
            }
        )

    return change


def ruled(*rules: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = list(rules)

    return change


def world(tmp: Path, *moves: dict[str, Any], rules: Sequence[str] = RULES, **kw: Any) -> WorldFile:
    return toy(tmp, border(*moves, **kw), ruled(*rules))


def game(tmp: Path, *moves: dict[str, Any], rules: Sequence[str] = RULES, **kw: Any) -> Logged:
    return Logged(world(tmp, *moves, rules=rules, **kw), "ilse", "tomas")


def contest(state: State) -> Contest:
    return state.contests[BORDER]


def landed(g: Logged, payloads: Sequence[ev.Payload]) -> list[ev.ContestMoved]:
    """What the contests read from ``payloads``, folded in first, and then folded."""
    before = g.state
    g.add(payloads)
    out = contests.moves(g.state, before, payloads)
    g.add(out)
    return out


def held(area: EntityId, by: EntityId, was: EntityId, n: int = 1) -> ev.AreaHeld:
    return ev.AreaHeld(area=area, holder=by, was=was, on=day(n))


def won(area: EntityId, by: EntityId, n: int = 1) -> ev.BattleEnded:
    return ev.BattleEnded(area=area, on=day(n), ending=Ending.WON, winner=by)


def flag(value: int, scope: Scope | None = PUBLIC, n: int = 1) -> ev.QuantitySet:
    q = Quantity(
        quantity_id=LEVY_ACT, owner=NORRA, name="Levy Act", value=value, unit="flag",
        as_of=day(n), scope=scope,
    )  # fmt: skip
    return ev.QuantitySet(quantity=q)


def shipping(g: Logged, value: int) -> ev.QuantitySet:
    q = g.state.quantities[SHIPPING]
    return ev.QuantitySet(quantity=q.model_copy(update={"value": value, "as_of": day(1)}))


def agreement(
    parties: Sequence[EntityId] = (NORRA, SUDLAND),
    *,
    public: bool = False,
    key: str = "a1",
    clauses: Sequence[AgreementClause] = (),
) -> Agreement:
    return Agreement(
        agreement_id=key,
        version="v1",
        parties=tuple(parties),
        clauses=tuple(clauses),
        made=day(1),
        published=day(1) if public else None,
        statuses=tuple(ClauseStatus.STANDING for _ in clauses),
    )


def keep_out() -> AgreementClause:
    return AgreementClause(type=ClauseType.KEEP_OUT, binds=NORRA, area=ISLE)


# --- the world file ---------------------------------------------------------------------


def test_a_contest_compiles_its_moves_with_each_kinds_step_and_its_deciding_day(
    tmp_path: Path,
) -> None:
    _, state = created(
        world(
            tmp_path,
            {"kind": "battle", "toward": "norra", "region": "south"},
            {"kind": "holder", "toward": "sudland", "territory": "isle"},
            {"kind": "flag", "toward": "norra", "quantity": "levy_act_passed"},
            {"kind": "line", "toward": "sudland", "nation": "norra", "line": 50, "falling": True},
            {"kind": "agreement_made", "toward": "norra", "between": ["norra", "sudland"]},
            {"kind": "agreement_broken", "toward": "sudland", "between": ["norra", "sudland"]},
            {"kind": "holder", "toward": "norra", "territory": "isle", "step": 40},
            countdown=12,
        )
    )
    k = contest(state)
    assert [m.step for m in k.moves] == [10, 15, 25, 10, 15, 15, 40]
    assert [m.toward for m in k.moves] == [NORRA, SUDLAND, NORRA, SUDLAND, NORRA, SUDLAND, NORRA]
    assert k.moves[1].area == ISLE and k.moves[2].quantity == LEVY_ACT
    assert k.moves[3].nation == NORRA and k.moves[3].falling
    assert k.moves[4].between == (NORRA, SUDLAND)
    assert not any(m.landed for m in k.moves)
    assert k.decides == day(12)


def test_with_the_rule_off_a_contest_is_compiled_as_before(tmp_path: Path) -> None:
    rules = ("territories", "holders", "agreements", "groups")
    _, state = created(
        world(tmp_path, {"kind": "holder", "toward": "norra", "territory": "isle"}, rules=rules)
    )
    k = contest(state)
    assert k.moves == () and k.decides is None
    dumped = k.model_dump(mode="json")
    assert "moves" not in dumped and "decides" not in dumped


@pytest.mark.parametrize(
    ("move", "problem"),
    [
        ({"kind": "holder", "toward": "isle", "territory": "isle"}, "isle is not a side"),
        ({"kind": "battle", "toward": "norra"}, "a battle move names []"),
        ({"kind": "battle", "toward": "norra", "region": "east"}, "unknown region east"),
        ({"kind": "holder", "toward": "norra", "territory": "the_gulf"}, "unknown territory"),
        (
            {"kind": "holder", "toward": "norra", "territory": "isle", "region": "south"},
            "a holder move names ['region', 'territory']",
        ),
        ({"kind": "flag", "toward": "norra", "quantity": "nothing"}, "unknown quantity nothing"),
        ({"kind": "line", "toward": "norra", "quantity": "norra_shipping"}, "a line move"),
        (
            {"kind": "line", "toward": "norra", "nation": "ilse", "line": 3},
            "ilse is not a polity",
        ),
        (
            {"kind": "line", "toward": "norra", "nation": "sudland", "group": "smiths", "line": 3},
            "sudland has no group smiths",
        ),
        (
            {"kind": "agreement_made", "toward": "norra", "between": ["norra"]},
            "two or more nations",
        ),
        (
            {"kind": "agreement_made", "toward": "norra", "between": ["norra", "norra"]},
            "two or more nations",
        ),
        (
            {"kind": "holder", "toward": "norra", "territory": "isle", "falling": True},
            "only a line move falls",
        ),
    ],
)
def test_a_move_that_names_what_the_world_lacks_is_refused(
    tmp_path: Path, move: dict[str, Any], problem: str
) -> None:
    problems = refused(world(tmp_path, move))
    assert any(problem in p for p in problems), problems


def test_a_legacy_worlds_contest_has_no_moves() -> None:
    import yaml

    raw = yaml.safe_load((Path(__file__).parent.parent / "worlds" / "salt-strait.yaml").read_text())
    assert raw.get("ruleset", "legacy") == "legacy"
    move = {"kind": "agreement_made", "toward": "varda", "between": ["varda", "ostrel"]}
    raw["contests"] = [
        {
            "key": "strait",
            "kind": "rivalry",
            "name": "The Strait",
            "prize": "The strait",
            "sides": ["varda", "ostrel"],
            "countdown_days": 30,
            "moves": [move],
        }
    ]
    problems = refused(WorldFile.model_validate(raw))
    assert any("only a realism world's contests have moves" in p for p in problems), problems


# --- each kind of move ------------------------------------------------------------------


def test_a_battle_won_in_the_region_steps_toward_the_winners_side(tmp_path: Path) -> None:
    g = game(tmp_path, {"kind": "battle", "toward": "norra", "region": "south"})
    assert landed(g, []) == []
    assert contests.moves(g.state, g.state, [won(HILLS, NORRA)]) == []  # the north
    assert contests.moves(g.state, g.state, [won(COAST, SUDLAND)]) == []  # the wrong side
    (m,) = contests.moves(g.state, g.state, [won(COAST, NORRA)])
    assert (m.change, m.cause, m.move) == (10, "move", 0)


def test_a_battle_move_counts_the_subregions_of_its_region(tmp_path: Path) -> None:
    g = game(tmp_path, {"kind": "battle", "toward": "sudland", "region": "mainland"})
    (m,) = contests.moves(g.state, g.state, [won(HILLS, SUDLAND)])
    assert m.change == -10  # toward the second side: down the track
    assert contests.moves(g.state, g.state, [won(ISLE, SUDLAND)]) == []  # the waters


def test_a_named_territory_taken_by_the_side_steps_toward_it(tmp_path: Path) -> None:
    g = game(tmp_path, {"kind": "holder", "toward": "norra", "territory": "isle"})
    assert landed(g, [held(COAST, NORRA, SUDLAND)]) == []
    (m,) = landed(g, [held(ISLE, NORRA, SUDLAND)])
    assert m.change == 15 and contest(g.state).track == 15


def test_a_measures_flag_set_steps_toward_its_side(tmp_path: Path) -> None:
    g = game(tmp_path, {"kind": "flag", "toward": "norra", "quantity": "levy_act_passed"})
    assert landed(g, [flag(0)]) == []
    (m,) = landed(g, [flag(1)])
    assert m.change == 25 and contest(g.state).track == 25


def test_a_public_contest_does_not_move_on_a_sealed_figure(tmp_path: Path) -> None:
    g = game(tmp_path, {"kind": "line", "toward": "norra", "quantity": "norra_shipping", "line": 5})
    assert g.state.quantities[SHIPPING].scope is None  # engine only
    assert landed(g, [shipping(g, 1)]) == []
    assert landed(g, [shipping(g, 9)]) == []
    assert not contest(g.state).moves[0].landed


def test_a_quantity_crossing_its_line_upward_steps_toward_the_side(tmp_path: Path) -> None:
    g = game(
        tmp_path, {"kind": "line", "toward": "sudland", "quantity": "levy_act_passed", "line": 3}
    )
    assert landed(g, [flag(2)]) == []
    (m,) = landed(g, [flag(3)])
    assert m.change == -10


def test_a_falling_line_lands_when_the_figure_drops_below_it(tmp_path: Path) -> None:
    move = {"kind": "line", "toward": "sudland", "nation": "norra", "line": 50, "falling": True}
    g = game(tmp_path, move)
    assert landed(g, [held(HILLS, SUDLAND, NORRA)]) == []  # the hills yield nothing
    (m,) = landed(g, [held(PLAIN, SUDLAND, NORRA)])
    assert m.change == -10


def test_a_figure_crossing_as_taken_industry_comes_back_lands_on_that_day(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, {"kind": "line", "toward": "norra", "nation": "norra", "line": 100.5})
    g.add([held(COAST, NORRA, SUDLAND)])  # taken on day 1: its output pays after 30 days
    assert contests.moves(g.state, g.state, [], day(29), day(30)) == []
    (m,) = contests.moves(g.state, g.state, [], day(30), day(31))
    assert m.change == 10


def test_a_groups_support_crossing_lands_only_for_an_audience_of_its_nations_seats(
    tmp_path: Path,
) -> None:
    move = {"kind": "line", "toward": "norra", "nation": "norra", "group": "public", "line": 45}
    g = game(tmp_path, move)
    rise = ev.GroupMoved(
        polity=NORRA, group="public", support=46, change=6, cause=Cause.DRIFT, on=day(1)
    )
    before = g.state
    g.add([rise])
    assert contests.moves(g.state, before, [rise]) == []  # a public contest

    def seen_by(*people: str) -> Callable[[State], State]:
        scope = Scope(visibility=Visibility.RESTRICTED, known_by=frozenset(map(seat, people)))

        def change(s: State) -> State:
            k = contest(s).model_copy(update={"scope": scope})
            return s.model_copy(update={"contests": {BORDER: k}})

        return change

    norra = seen_by("ilse")
    (m,) = contests.moves(norra(g.state), norra(before), [rise])
    assert m.change == 10
    both = seen_by("ilse", "tomas")
    assert contests.moves(both(g.state), both(before), [rise]) == []


def test_an_agreement_among_the_named_nations_steps_toward_its_side(tmp_path: Path) -> None:
    g = game(
        tmp_path, {"kind": "agreement_made", "toward": "norra", "between": ["norra", "sudland"]}
    )
    (m,) = landed(g, [ev.AgreementMade(agreement=agreement(public=True))])
    assert m.change == 15


def test_a_sealed_agreement_moves_a_public_contest_the_day_it_is_published(
    tmp_path: Path,
) -> None:
    g = game(
        tmp_path, {"kind": "agreement_made", "toward": "norra", "between": ["norra", "sudland"]}
    )
    assert landed(g, [ev.AgreementMade(agreement=agreement())]) == []
    (m,) = landed(g, [ev.AgreementPublished(agreement_id="a1", by=NORRA, on=day(3))])
    assert m.change == 15


def test_an_agreement_short_of_the_named_nations_does_not_move_it(tmp_path: Path) -> None:
    g = game(
        tmp_path, {"kind": "agreement_made", "toward": "norra", "between": ["norra", "sudland"]}
    )
    k = contest(g.state)
    three = k.model_copy(
        update={"moves": (k.moves[0].model_copy(update={"between": (NORRA, SUDLAND, ISLE)}),)}
    )
    payload = ev.AgreementMade(agreement=agreement(public=True))
    before = g.state.model_copy(update={"contests": {BORDER: three}})
    g.add([payload])
    after = g.state.model_copy(update={"contests": {BORDER: three}})
    assert contests.moves(after, before, [payload]) == []


def test_a_broken_clause_steps_toward_the_side_and_not_on_a_kept_one(tmp_path: Path) -> None:
    move = {"kind": "agreement_broken", "toward": "sudland", "between": ["norra", "sudland"]}
    g = game(tmp_path, move)
    made = ev.AgreementMade(agreement=agreement(public=True, clauses=[keep_out()]))
    assert landed(g, [made]) == []
    kept = ev.ClauseJudged(agreement_id="a1", clause=0, status=ClauseStatus.KEPT, on=day(2))
    assert landed(g, [kept]) == []
    broke = ev.ClauseJudged(agreement_id="a1", clause=0, status=ClauseStatus.BROKEN, on=day(3))
    (m,) = landed(g, [broke])
    assert m.change == -15


def test_a_sealed_broken_clause_lands_when_the_agreement_is_published(tmp_path: Path) -> None:
    move = {"kind": "agreement_broken", "toward": "sudland", "between": ["norra", "sudland"]}
    g = game(tmp_path, move)
    landed(g, [ev.AgreementMade(agreement=agreement(clauses=[keep_out()]))])
    broke = ev.ClauseJudged(agreement_id="a1", clause=0, status=ClauseStatus.BROKEN, on=day(3))
    assert landed(g, [broke]) == []
    (m,) = landed(g, [ev.AgreementPublished(agreement_id="a1", by=SUDLAND, on=day(4))])
    assert m.change == -15


# --- once, and the track's ends ---------------------------------------------------------


def test_each_move_lands_once(tmp_path: Path) -> None:
    g = game(tmp_path, {"kind": "flag", "toward": "norra", "quantity": "levy_act_passed"})
    assert len(landed(g, [flag(1)])) == 1
    assert landed(g, [flag(0, n=2)]) == []
    assert landed(g, [flag(1, n=3)]) == []
    assert contest(g.state).track == 25 and contest(g.state).moves[0].landed


def test_the_fold_refuses_a_move_landing_twice_or_one_the_contest_lacks(tmp_path: Path) -> None:
    g = game(tmp_path, {"kind": "flag", "toward": "norra", "quantity": "levy_act_passed"})
    g.add([ev.ContestMoved(contest_id=BORDER, change=25, cause="move", move=0)])
    with pytest.raises(FoldError, match="has landed"):
        g.add([ev.ContestMoved(contest_id=BORDER, change=25, cause="move", move=0)])
    with pytest.raises(FoldError, match="no move 1"):
        g.add([ev.ContestMoved(contest_id=BORDER, change=25, cause="move", move=1)])


def test_a_moves_index_goes_with_the_cause_move() -> None:
    with pytest.raises(ValidationError):
        ev.ContestMoved(contest_id=BORDER, change=1, cause="move")
    with pytest.raises(ValidationError):
        ev.ContestMoved(contest_id=BORDER, change=1, cause="momentum", move=0)
    old = ev.ContestMoved(contest_id=BORDER, change=1).model_dump(mode="json")
    assert "move" not in old


def test_two_moves_the_same_day_add_up_and_stop_at_the_tracks_end(tmp_path: Path) -> None:
    g = game(
        tmp_path,
        {"kind": "holder", "toward": "norra", "territory": "isle", "step": 60},
        {"kind": "flag", "toward": "norra", "quantity": "levy_act_passed", "step": 60},
        track=10,
    )
    out = landed(g, [held(ISLE, NORRA, SUDLAND), flag(1)])
    assert [(m.move, m.change) for m in out] == [(0, 60), (1, 30)]
    assert contest(g.state).track == 100


def test_the_same_happenings_in_either_order_move_the_contest_the_same(tmp_path: Path) -> None:
    g = game(
        tmp_path,
        {"kind": "flag", "toward": "norra", "quantity": "levy_act_passed"},
        {"kind": "holder", "toward": "sudland", "territory": "norra_hills"},
    )
    today: list[ev.Payload] = [flag(1), held(HILLS, SUDLAND, NORRA)]
    before = g.state
    g.add(today)
    ab = contests.moves(g.state, before, today)
    ba = contests.moves(g.state, before, list(reversed(today)))
    assert ab == ba and [m.move for m in ab] == [0, 1]


def test_a_move_on_a_decided_contest_does_not_land(tmp_path: Path) -> None:
    g = game(tmp_path, {"kind": "flag", "toward": "norra", "quantity": "levy_act_passed"})
    g.add([ev.ContestDecided(contest_id=BORDER, winner=None)])
    assert landed(g, [flag(1)]) == []


def test_with_the_rule_off_nothing_moves_or_decides(tmp_path: Path) -> None:
    g = game(tmp_path, {"kind": "flag", "toward": "norra", "quantity": "levy_act_passed"})
    before = g.state.model_copy(update={"rules": g.state.rules - {Rule.CONTESTS}})
    g.add([flag(1)])
    after = g.state.model_copy(update={"rules": g.state.rules - {Rule.CONTESTS}})
    assert len(contests.moves(g.state, before, [flag(1)])) == 1  # the rule on: it lands
    assert contests.moves(after, before, [flag(1)]) == []
    assert contests.decisions(after, day(400)) == []


# --- the deciding day -------------------------------------------------------------------


def test_the_contest_is_decided_on_its_deciding_day_for_the_side_ahead(tmp_path: Path) -> None:
    g = game(tmp_path, countdown=5, track=20)
    out = g.walk(day(1), day(4))
    assert not [e for e in out if isinstance(e.payload, ev.ContestDecided)]
    out = g.walk(day(5), day(5))
    (decided,) = [e for e in out if isinstance(e.payload, ev.ContestDecided)]
    assert decided.payload.winner == NORRA  # type: ignore[union-attr]
    assert decided.scope == PUBLIC
    assert contest(g.state).decided and contest(g.state).winner == NORRA
    assert not [e for e in g.walk(day(6), day(8)) if isinstance(e.payload, ev.ContestDecided)]


def test_a_level_track_is_decided_for_nobody(tmp_path: Path) -> None:
    g = game(tmp_path, countdown=3)
    out = g.walk(day(1), day(3))
    (decided,) = [e.payload for e in out if isinstance(e.payload, ev.ContestDecided)]
    assert decided.winner is None


def test_a_walk_past_the_deciding_day_decides_it_once(tmp_path: Path) -> None:
    g = game(tmp_path, countdown=2, track=-30)
    out = g.walk(day(1), day(6))
    (decided,) = [e.payload for e in out if isinstance(e.payload, ev.ContestDecided)]
    assert decided.winner == SUDLAND


def test_in_the_day_walk_a_move_lands_once_sealed_like_its_contest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revisionist.core.realism import holders

    g = game(tmp_path, {"kind": "holder", "toward": "norra", "territory": "isle"})
    real = holders.walk

    def walk(state: State, on: date) -> list[ev.Payload]:
        if on == day(2) and holders.holder(state, ISLE) == SUDLAND:
            return [held(ISLE, NORRA, SUDLAND, 2)]
        return real(state, on)

    monkeypatch.setattr(holders, "walk", walk)
    out = g.walk(day(1), day(4))
    moved = [e for e in out if isinstance(e.payload, ev.ContestMoved)]
    assert len(moved) == 1 and moved[0].scope == contest(g.state).scope
    assert moved[0].payload.change == 15  # type: ignore[union-attr]
    stake = seat_stakes(g.state, seat("tomas"), g.log)["contests"][0]
    assert stake["lean"] is not None and stake["lean"]["favours"] == "Norra"
    today = g.state.in_world_date  # the bare walk leaves the date where it was
    assert today is not None and stake["days_left"] == (contest(g.state).decides - today).days  # type: ignore[operator]


def test_in_the_day_walk_a_figure_crossing_lands_on_the_day_it_crosses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revisionist.core.realism import holders

    move = {"kind": "line", "toward": "norra", "nation": "norra", "line": 100.5}
    g = game(tmp_path, move, countdown=60)

    def walk(state: State, on: date) -> list[ev.Payload]:  # Norra takes the coast and keeps it
        if on == day(1) and holders.holder(state, COAST) == SUDLAND:
            return [held(COAST, NORRA, SUDLAND)]
        return []

    monkeypatch.setattr(holders, "walk", walk)
    assert not [e for e in g.walk(day(1), day(30)) if isinstance(e.payload, ev.ContestMoved)]
    out = g.walk(day(31), day(31))
    assert len([e for e in out if isinstance(e.payload, ev.ContestMoved)]) == 1


def test_a_move_read_at_the_close_lands_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revisionist.core.realism import holders

    g = game(tmp_path, {"kind": "holder", "toward": "norra", "territory": "isle"})

    def close(state: State, until: date) -> list[ev.Payload]:
        return [held(ISLE, NORRA, SUDLAND, 3)] if holders.holder(state, ISLE) == SUDLAND else []

    monkeypatch.setattr(holders, "close", close)
    out = g.walk(day(1), day(3))
    assert len([e for e in out if isinstance(e.payload, ev.ContestMoved)]) == 1
    assert contest(g.state).track == 15


def test_a_contest_move_names_the_fields_of_its_kind() -> None:
    with pytest.raises(ValidationError):
        ContestMove(kind=MoveKind.LINE, toward=NORRA, step=10, quantity=LEVY_ACT)
    with pytest.raises(ValidationError):
        ContestMove(kind=MoveKind.HOLDER, toward=NORRA, step=10, area=ISLE, falling=True)
    ContestMove(kind=MoveKind.LINE, toward=NORRA, step=10, nation=NORRA, group="g", line=1)
    assert realism_tick is not None
