"""Intelligence orders: recon flight, patrol, agent, codebreaking, concealment (IOR).

The toy world (``tests/worlds/territory-toy.yaml``) with ``territories`` and ``reports`` on,
as ``tests/test_detection.py`` plays it: Norra's levy and kites on the Norra Plain, Sudland's
levy on the Sudland Coast and its galleys in the Gulf. The four rule functions are called
directly; the path from a form or a written order is the rules lane's (INT).
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import state_hash
from revisionist.core.ids import FeatureId, OrderId
from revisionist.core.realism import detect, territory
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.detect import (
    AGENT_DAYS,
    AGENTS_MAX,
    CODE_COST,
    CODE_DAYS,
    CONCEAL_BONUS,
    EXPOSE_CHANCE,
    IntelError,
    Source,
)
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.effect import (
    Allocate,
    Engagement,
    IntelOrder,
    Investigate,
    MoveForce,
    Posture,
    SetEngagement,
)
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.quantity import RESOLVER_KEYS
from revisionist.core.state import State
from revisionist.core.visibility import Visibility
from revisionist.engine import catchup, estimate, options, wake
from tests.test_adjacency_moves import Logged, World, day, entity, seat
from tests.test_adjacency_moves import fold as fold_payloads
from tests.test_detection import (
    NORRA,
    SUDLAND,
    fid,
    intelligence,
    norra_sees,
    place,
    rules,
    strengths,
    sudland_sees,
)
from tests.test_detection import toy as detection_toy

ECONOMY = rules("territories", "holders", "economy", "reports")


def game(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    tmp.mkdir(parents=True, exist_ok=True)
    return Logged(detection_toy(tmp, *changes), "ilse", "tomas")


def land(g: Logged, changes: Sequence[Any]) -> None:
    """The changes a rule function returns, landed as the rules lane lands them."""
    g.add([ev.FeatureSet(feature=c) if isinstance(c, Feature) else c for c in changes])


def air_sightings(state: State, n: int, key: str) -> list[detect.Sighting]:
    return [
        s
        for s in detect.sightings(state, state, day(n), entity(NORRA))
        if s.source is Source.AIR and s.force.feature_id == fid(key)
    ]


def air_roll(state: State, n: int, key: str) -> int:
    return detect.roll(state, day(n), entity(NORRA), "air", str(fid(key)))


def kite_range(steps: int) -> Callable[[World], None]:
    def change(w: World) -> None:
        for k in w["piece_kinds"]:
            if k["key"] == "kite":
                k["range_steps"] = steps

    return change


def pools(output: float) -> Callable[[Logged], None]:
    def give(g: Logged) -> None:
        g.add([ev.EconomySet(polity=entity(NORRA), pools=Pools(output=output), on=day(0))])

    return give


# --- Rule 1: a reconnaissance flight searches one area on the next day's roll -------------


def _recon_game(tmp: Path) -> Logged:
    return game(tmp, place("sudland_levy", "sudby"), intelligence(norra_sees("air")))


def _quiet_days(state: State, key: str, floor: int) -> int:
    """A day n whose routine air roll on ``key`` misses on n and on n + 1."""
    return next(
        n
        for n in range(1, 200)
        if air_roll(state, n, key) >= floor and air_roll(state, n + 1, key) >= floor
    )


def test_a_recon_flight_searches_its_area_on_the_next_days_roll_not_at_once(
    tmp_path: Path,
) -> None:
    g = _recon_game(tmp_path)
    n = _quiet_days(g.state, "sudland_levy", 60)  # kites detect 60, a levy conceals 0
    assert not air_sightings(g.state, n, "sudland_levy")
    land(
        g,
        detect.order_recon(
            g.state, entity(NORRA), fid("norra_kites"), entity("sudland_coast"), day(n)
        ),
    )
    assert not air_sightings(g.state, n, "sudland_levy")  # the flight reveals nothing at once
    (s,) = air_sightings(g.state, n + 1, "sudland_levy")  # 100 less conceal 0: certain
    assert s.area == entity("sudland_coast") and s.exact is False
    later = [k for k in range(n + 2, n + 40) if air_roll(g.state, k, "sudland_levy") >= 60]
    assert later and not any(air_sightings(g.state, k, "sudland_levy") for k in later)


def test_a_recon_flight_searches_at_100_less_the_targets_conceal(tmp_path: Path) -> None:
    g = game(tmp_path, intelligence(norra_sees("air")))  # the galleys conceal 10
    rolls = {n: air_roll(g.state, n, "sudland_galleys") for n in range(2, 300)}
    miss = next(n for n, r in rolls.items() if r >= 90)
    hit = next(n for n, r in rolls.items() if 60 <= r < 90)
    for n, seen in ((miss, False), (hit, True)):
        g2 = game(tmp_path / str(n), intelligence(norra_sees("air")))
        land(
            g2,
            detect.order_recon(
                g2.state, entity(NORRA), fid("norra_kites"), entity("the_gulf"), day(n - 1)
            ),
        )
        assert bool(air_sightings(g2.state, n, "sudland_galleys")) is seen


def test_a_recon_flight_is_rolled_once_with_the_routine_search(tmp_path: Path) -> None:
    g = _recon_game(tmp_path)
    n = _quiet_days(g.state, "sudland_levy", 60)
    land(
        g,
        detect.order_recon(
            g.state, entity(NORRA), fid("norra_kites"), entity("sudland_coast"), day(n)
        ),
    )
    found = [s for s in detect.sightings(g.state, g.state, day(n + 1), entity(NORRA))]
    assert [s.force.feature_id for s in found if s.source is Source.AIR].count(
        fid("sudland_levy")
    ) == 1


@pytest.mark.parametrize(
    ("polity", "piece", "area", "why"),
    [
        (SUDLAND, "norra_kites", "sudland_coast", "not sudland's"),
        (NORRA, "norra_levy", "sudland_coast", "not an air piece"),
        (NORRA, "norra_kites", "norrhavn", "not an area"),
    ],
)
def test_a_recon_flight_names_an_own_air_piece_and_an_area(
    tmp_path: Path, polity: str, piece: str, area: str, why: str
) -> None:
    g = game(tmp_path, intelligence(norra_sees("air"), sudland_sees("air")))
    with pytest.raises(IntelError, match=rf"(?i){why}"):
        detect.order_recon(g.state, entity(polity), fid(piece), entity(area), day(1))


def test_a_recon_flight_stays_within_its_pieces_range(tmp_path: Path) -> None:
    g = game(tmp_path, kite_range(1), intelligence(norra_sees("air")))
    with pytest.raises(IntelError, match="beyond"):
        detect.order_recon(
            g.state, entity(NORRA), fid("norra_kites"), entity("sudland_coast"), day(1)
        )
    assert detect.order_recon(
        g.state, entity(NORRA), fid("norra_kites"), entity("norra_hills"), day(1)
    )


def test_a_recon_flight_needs_someone_to_report_air_search(tmp_path: Path) -> None:
    g = game(tmp_path, intelligence(norra_sees("agent")))
    with pytest.raises(IntelError, match=r"(?i)no one reports air"):
        detect.order_recon(
            g.state, entity(NORRA), fid("norra_kites"), entity("sudland_coast"), day(1)
        )


def test_the_intelligence_orders_need_the_reports_rule(tmp_path: Path) -> None:
    g = Logged(
        detection_toy(tmp_path, rules("territories"), strengths), "ilse", "tomas"
    )  # reports off
    with pytest.raises(IntelError, match=r"(?i)reports rule is off"):
        detect.order_recon(
            g.state, entity(NORRA), fid("norra_kites"), entity("sudland_coast"), day(1)
        )
    with pytest.raises(IntelError, match=r"(?i)reports rule is off"):
        detect.place_agent(g.state, entity(NORRA), entity("sudland_coast"), day(1))
    with pytest.raises(IntelError, match=r"(?i)reports rule is off"):
        detect.fund_codebreaking(g.state, entity(NORRA), day(1))
    with pytest.raises(IntelError, match=r"(?i)reports rule is off"):
        detect.set_concealed(g.state, fid("norra_levy"), True, day(1))


# --- Rule 2: a patrol is the patrol posture on a sea piece ---------------------------------


def test_a_patrol_is_the_existing_posture_and_the_aide_may_file_it() -> None:
    patrol = MoveForce(force=fid("sudland_galleys"), posture=Posture.PATROL)
    assert detect.aide_may(patrol) is patrol


# --- Rule 3: agents ---------------------------------------------------------------------


def _agent_game(tmp: Path, *more: Callable[[World], None]) -> Logged:
    return game(tmp, intelligence(norra_sees("agent")), *more)


def agent_hits(state: State, days: range) -> list[int]:
    return [
        n
        for n in days
        for s in detect.sightings(state, state, day(n), entity(NORRA))
        if s.source is Source.AGENT
    ]


def test_a_placed_agent_reports_from_agent_days_after_the_order(tmp_path: Path) -> None:
    g = _agent_game(tmp_path)
    (placed,) = detect.place_agent(g.state, entity(NORRA), entity("sudland_coast"), day(1))
    assert isinstance(placed, ev.AgentSet)
    assert placed.agent.since == day(1 + AGENT_DAYS) and placed.index == 0
    assert placed.agent.area == entity("sudland_coast") and placed.agent.lost is None
    land(g, (placed,))
    hits = agent_hits(g.state, range(1, 120))
    assert hits and min(hits) >= 1 + AGENT_DAYS
    could = [
        n
        for n in range(1, 1 + AGENT_DAYS)
        if detect.roll(g.state, day(n), entity(NORRA), "agent", f"0\x1f{entity('sudland_coast')}")
        < detect.AGENT_CHANCE
    ]
    assert could  # the agent's roll would have hit before it was in place


def test_no_more_than_agents_max_agents(tmp_path: Path) -> None:
    g = _agent_game(tmp_path)
    for n in range(AGENTS_MAX):
        land(g, detect.place_agent(g.state, entity(NORRA), entity("sudland_coast"), day(n)))
    assert len(g.state.intelligence[entity(NORRA)].agents) == AGENTS_MAX
    with pytest.raises(IntelError, match="at most 3 agents"):
        detect.place_agent(g.state, entity(NORRA), entity("isle"), day(5))


def test_an_agent_declared_at_the_start_counts_toward_the_limit(tmp_path: Path) -> None:
    start = [{"area": "isle"}]
    g = game(tmp_path, intelligence(norra_sees("agent", agents=start)))
    for n in range(AGENTS_MAX - 1):
        land(g, detect.place_agent(g.state, entity(NORRA), entity("sudland_coast"), day(n)))
    with pytest.raises(IntelError, match="at most"):
        detect.place_agent(g.state, entity(NORRA), entity("sudland_coast"), day(5))


def test_a_lost_or_ended_agent_frees_its_place(tmp_path: Path) -> None:
    start = [{"area": "isle", "until": str(day(2))}]
    g = game(tmp_path, intelligence(norra_sees("agent", agents=start)))
    for n in range(AGENTS_MAX - 1):
        land(g, detect.place_agent(g.state, entity(NORRA), entity("sudland_coast"), day(n)))
    with pytest.raises(IntelError, match="at most"):
        detect.place_agent(g.state, entity(NORRA), entity("isle"), day(2))
    assert detect.place_agent(g.state, entity(NORRA), entity("isle"), day(3))


@pytest.mark.parametrize(
    ("sees", "area", "why"),
    [
        ("air", "sudland_coast", "no one reports agent"),
        ("agent", "sudby", "not an area"),
    ],
)
def test_placing_an_agent_needs_a_handler_and_an_area(
    tmp_path: Path, sees: str, area: str, why: str
) -> None:
    g = game(tmp_path, intelligence(norra_sees(sees)))
    with pytest.raises(IntelError, match=rf"(?i){why}"):
        detect.place_agent(g.state, entity(NORRA), entity(area), day(1))


def _exposed_on(state: State, first: int) -> int:
    subject = f"0\x1f{entity('sudland_coast')}"
    return next(
        n
        for n in range(first, 400)
        if detect.roll(state, day(n), entity(NORRA), "agent-exposed", subject) < EXPOSE_CHANCE
    )


def test_a_placed_agent_is_exposed_lost_and_the_holder_gets_a_paper(tmp_path: Path) -> None:
    g = _agent_game(tmp_path)
    land(g, detect.place_agent(g.state, entity(NORRA), entity("sudland_coast"), day(0)))
    lost = _exposed_on(g.state, AGENT_DAYS)
    assert lost < 300
    out = g.walk(day(1), day(lost + 3))
    sets = [e for e in out if isinstance(e.payload, ev.AgentSet)]
    (e,) = sets
    p = e.payload
    assert isinstance(p, ev.AgentSet)
    assert (p.nation, p.index, p.agent.lost) == (entity(NORRA), 0, day(lost))
    assert e.scope.visibility is Visibility.RESTRICTED
    assert not e.scope.visible_to(seat("ilse")) and not e.scope.visible_to(seat("tomas"))
    papers = [
        x.payload
        for x in out
        if isinstance(x.payload, ev.DocumentIssued)
        and x.payload.document.title.startswith("Agent caught")
    ]
    (paper,) = papers
    assert paper.document.scope.known_by == frozenset({seat("tomas")})
    assert paper.document.issued == day(lost)
    # Nothing from the agent on or after the day it was lost.
    assert not [n for n in agent_hits(g.state, range(lost, lost + 60))]
    assert detect.place_agent(g.state, entity(NORRA), entity("sudland_coast"), day(lost + 1))


def test_an_agent_declared_at_the_start_is_not_exposed(tmp_path: Path) -> None:
    g = game(tmp_path, intelligence(norra_sees("agent", agents=[{"area": "sudland_coast"}])))
    out = g.walk(day(1), day(120))
    assert not [e for e in out if isinstance(e.payload, ev.AgentSet)]


def test_an_agent_in_a_sea_zone_is_lost_with_no_paper(tmp_path: Path) -> None:
    g = _agent_game(tmp_path)
    land(g, detect.place_agent(g.state, entity(NORRA), entity("the_gulf"), day(0)))
    subject = f"0\x1f{entity('the_gulf')}"
    lost = next(
        n
        for n in range(AGENT_DAYS, 400)
        if detect.roll(g.state, day(n), entity(NORRA), "agent-exposed", subject) < EXPOSE_CHANCE
    )
    out = g.walk(day(1), day(lost))
    assert [e for e in out if isinstance(e.payload, ev.AgentSet)]
    assert not [
        e
        for e in out
        if isinstance(e.payload, ev.DocumentIssued)
        and e.payload.document.title.startswith("Agent caught")
    ]


# --- Rule 4: funding codebreaking ----------------------------------------------------------


def _code_game(tmp: Path, level: int = 0) -> Logged:
    g = game(tmp, ECONOMY, strengths, intelligence(norra_sees("codebreaking", codebreaking=level)))
    return g


def test_funding_spends_code_cost_and_raises_the_level_after_code_days(tmp_path: Path) -> None:
    g = _code_game(tmp_path, level=1)
    pools(25)(g)
    spent, raised = detect.fund_codebreaking(g.state, entity(NORRA), day(3))
    assert isinstance(spent, ev.EconomySet) and isinstance(raised, ev.CodebreakingSet)
    assert spent.pools.output == 25 - CODE_COST and spent.on == day(3)
    assert (raised.nation, raised.level, raised.on) == (entity(NORRA), 2, day(3 + CODE_DAYS))
    land(g, (spent, raised))
    assert g.state.economy.pools[entity(NORRA)].output == 25 - CODE_COST
    assert detect.level(g.state, entity(NORRA), day(2 + CODE_DAYS)) == 1
    assert detect.level(g.state, entity(NORRA), day(3 + CODE_DAYS)) == 2


def test_funding_needs_code_cost_in_the_output_pool(tmp_path: Path) -> None:
    g = _code_game(tmp_path)
    with pytest.raises(IntelError, match="output"):
        detect.fund_codebreaking(g.state, entity(NORRA), day(1))
    pools(CODE_COST - 1)(g)
    with pytest.raises(IntelError, match="output"):
        detect.fund_codebreaking(g.state, entity(NORRA), day(1))
    pools(CODE_COST)(g)
    assert detect.fund_codebreaking(g.state, entity(NORRA), day(1))


def test_funding_raises_the_level_to_at_most_three_counting_raises_to_come(
    tmp_path: Path,
) -> None:
    g = _code_game(tmp_path, level=1)
    pools(100)(g)
    land(g, detect.fund_codebreaking(g.state, entity(NORRA), day(1)))
    land(g, detect.fund_codebreaking(g.state, entity(NORRA), day(2)))
    assert detect.level(g.state, entity(NORRA), day(2 + CODE_DAYS)) == 3
    with pytest.raises(IntelError, match="level 3"):
        detect.fund_codebreaking(g.state, entity(NORRA), day(3))


def test_funding_needs_the_economy_and_someone_to_report_codebreaking(tmp_path: Path) -> None:
    g = game(tmp_path, intelligence(norra_sees("codebreaking")))  # no economy rule
    with pytest.raises(IntelError, match=r"(?i)economy rule is off"):
        detect.fund_codebreaking(g.state, entity(NORRA), day(1))
    g2 = game(tmp_path / "b", ECONOMY, strengths, intelligence(norra_sees("air")))
    pools(100)(g2)
    with pytest.raises(IntelError, match=r"(?i)no one reports codebreaking"):
        detect.fund_codebreaking(g2.state, entity(NORRA), day(1))


def test_the_codebreaking_chance_follows_the_level_on_the_day(tmp_path: Path) -> None:
    from revisionist.core.realism.resolvers import apply_changes, movement
    from tests.test_adjacency_moves import order

    g = game(tmp_path, intelligence(sudland_sees("codebreaking", codebreaking=0)))
    g.add([ev.CodebreakingSet(nation=entity(SUDLAND), level=n, on=day(50)) for n in (1, 2, 3)])
    before = g.state
    after = fold_payloads(
        before,
        apply_changes(before, movement.order_changes(before, order("ilse", "norra_levy", "sudby"))),
    )

    def hit(n: int) -> bool:
        return any(
            s.source is Source.CODEBREAKING
            for s in detect.sightings(after, before, day(n), entity(SUDLAND))
        )

    def roll(n: int) -> int:
        return detect.roll(after, day(n), entity(SUDLAND), "codebreaking", str(fid("norra_levy")))

    early = [n for n in range(1, 50) if roll(n) < 40]
    late = [n for n in range(50, 200) if roll(n) < 40]
    assert early and late
    assert not any(hit(n) for n in early)
    assert all(hit(n) for n in late)


# --- Rule 5: concealment --------------------------------------------------------------------


def test_concealment_raises_conceal_by_the_bonus_until_lifted(tmp_path: Path) -> None:
    g = game(tmp_path, place("sudland_levy", "sudby"), intelligence(norra_sees("air")))
    levy = g.state.features[fid("sudland_levy")]
    assert detect.conceal(g.state, levy) == 0
    (hid,) = detect.set_concealed(g.state, fid("sudland_levy"), True, day(1))
    assert isinstance(hid, Feature) and hid.concealed
    land(g, (hid,))
    assert detect.conceal(g.state, g.state.features[fid("sudland_levy")]) == CONCEAL_BONUS
    band = [
        n for n in range(1, 300) if 60 - CONCEAL_BONUS <= air_roll(g.state, n, "sudland_levy") < 60
    ]
    assert band and not any(air_sightings(g.state, n, "sudland_levy") for n in band)
    land(g, detect.set_concealed(g.state, fid("sudland_levy"), False, day(2)))
    assert all(air_sightings(g.state, n, "sudland_levy") for n in band)


def test_a_concealed_piece_takes_a_day_longer_each_step(tmp_path: Path) -> None:
    g = game(tmp_path)
    levy = g.state.features[fid("norra_levy")]
    plain = territory.step_days(g.state, levy, entity("norra_hills"))
    course = territory.plan(g.state, levy, entity("sudland_coast"))
    assert isinstance(course, territory.Plan) and plain is not None
    land(g, detect.set_concealed(g.state, fid("norra_levy"), True, day(1)))
    hid = g.state.features[fid("norra_levy")]
    assert territory.step_days(g.state, hid, entity("norra_hills")) == plain + 1
    slow = territory.plan(g.state, hid, entity("sudland_coast"))
    assert isinstance(slow, territory.Plan)
    assert slow.path == course.path
    assert slow.days == tuple(d + 1 for d in course.days)


def test_a_concealed_piece_is_slower_on_the_day_walk(tmp_path: Path) -> None:
    open_ = game(tmp_path / "a")
    hidden = game(tmp_path / "b")
    land(hidden, detect.set_concealed(hidden.state, fid("norra_levy"), True, day(0)))
    for g in (open_, hidden):
        g.send("ilse", "norra_levy", "sudby")
    arrived = []
    for g in (open_, hidden):
        out = g.walk(day(1), day(30))
        arrived.append(
            max(
                e.payload.on
                for e in out
                if isinstance(e.payload, ev.PieceStepped) and e.payload.nation == entity(NORRA)
            )
        )
    assert arrived[1] - arrived[0] == timedelta(days=2)  # two steps, a day longer each


def test_a_concealed_leg_conceals_the_piece_until_it_arrives(tmp_path: Path) -> None:
    from tests.test_history_steps_aside import leg, legs

    g = game(
        tmp_path,
        legs("sudland_levy", leg(day(1), "norra_hills", concealed=True)),
    )
    out = g.walk(day(1), day(2))
    assert out
    under_way = g.state.features[fid("sudland_levy")]
    assert under_way.path and detect.conceal(g.state, under_way) == CONCEAL_BONUS
    g.walk(day(3), day(20))
    there = g.state.features[fid("sudland_levy")]
    assert not there.path and detect.conceal(g.state, there) == 0


def test_a_concealed_leg_conceals_nothing_without_the_reports_rule(tmp_path: Path) -> None:
    from tests.test_history_steps_aside import leg, legs

    tmp_path.mkdir(exist_ok=True)
    g = Logged(
        detection_toy(
            tmp_path,
            rules("territories"),
            legs("sudland_levy", leg(day(1), "norra_hills", concealed=True)),
        ),
        "ilse",
        "tomas",
    )
    g.walk(day(1), day(2))
    under_way = g.state.features[fid("sudland_levy")]
    assert under_way.path and not detect.concealed(under_way)


def test_an_open_leg_conceals_nothing(tmp_path: Path) -> None:
    from tests.test_history_steps_aside import leg, legs

    g = game(tmp_path, legs("sudland_levy", leg(day(1), "norra_hills")))
    g.walk(day(1), day(2))
    assert detect.conceal(g.state, g.state.features[fid("sudland_levy")]) == 0


def test_concealment_names_a_force_in_play(tmp_path: Path) -> None:
    g = game(tmp_path)
    with pytest.raises(IntelError, match=r"(?i)no piece"):
        detect.set_concealed(g.state, FeatureId(entity("nowhere")), True, day(1))


# --- Rule 6: carried by existing effect kinds, and the rule name ---------------------------


def test_the_orders_ride_on_investigate_engagement_and_allocate() -> None:
    area, kites = entity("sudland_coast"), fid("norra_kites")
    recon = Investigate(target=area, question="recon", intel=IntelOrder.RECON, flier=kites)
    agent = Investigate(target=area, question="agent", intel=IntelOrder.AGENT)
    fund = Allocate(
        recipient=entity(NORRA),
        what="codebreaking",
        amount=CODE_COST,
        unit="points",
        intel=IntelOrder.CODEBREAKING,
    )
    hide = SetEngagement(force=kites, zone="here", rule=Engagement.DEFEND, concealed=True)
    assert (recon.flier, agent.flier, fund.intel, hide.concealed) == (
        kites,
        None,
        "codebreaking",
        True,
    )
    with pytest.raises(ValueError, match="recon"):
        Investigate(target=area, question="q", intel=IntelOrder.RECON)
    with pytest.raises(ValueError, match="flier"):
        Investigate(target=area, question="q", intel=IntelOrder.AGENT, flier=kites)
    with pytest.raises(ValueError, match="investigate"):
        Investigate(target=area, question="q", intel=IntelOrder.CODEBREAKING)
    with pytest.raises(ValueError, match="allocate"):
        Allocate(recipient=area, what="x", amount=1, unit="u", intel=IntelOrder.AGENT)


def test_an_effect_without_the_new_fields_dumps_as_before() -> None:
    plain = Investigate(target=entity("isle"), question="who holds it")
    assert set(plain.model_dump()) == {"kind", "target", "question"}
    assert set(Allocate(recipient=entity("isle"), what="x", amount=1, unit="u").model_dump()) == {
        "kind",
        "recipient",
        "what",
        "amount",
        "unit",
    }
    engagement = SetEngagement(zone="z", rule=Engagement.DEFEND)
    assert "concealed" not in engagement.model_dump()


def test_intel_is_a_rule_name_for_forms() -> None:
    assert "intel" in RESOLVER_KEYS


# --- Rule 7: the aide files a patrol or a recon flight at most ------------------------------


def _intel_effects() -> list[Any]:
    area, kites = entity("sudland_coast"), fid("norra_kites")
    return [
        Investigate(target=area, question="recon", intel=IntelOrder.RECON, flier=kites),
        MoveForce(force=fid("sudland_galleys"), posture=Posture.PATROL),
        Investigate(target=area, question="agent", intel=IntelOrder.AGENT),
        Allocate(
            recipient=entity(NORRA),
            what="codebreaking",
            amount=CODE_COST,
            unit="points",
            intel=IntelOrder.CODEBREAKING,
        ),
        SetEngagement(force=kites, zone="here", rule=Engagement.DEFEND, concealed=True),
    ]


def _bounded(effects: Sequence[Any]) -> None:
    for e in effects:
        assert not (isinstance(e, Investigate) and e.intel is IntelOrder.AGENT)
        assert not (isinstance(e, Allocate) and e.intel is not None)
        assert not (isinstance(e, SetEngagement) and e.concealed is not None)


def test_the_aide_may_file_a_patrol_or_recon_never_an_agent_funding_or_concealment() -> None:
    effects = _intel_effects()
    kept = [detect.aide_may(e) for e in effects]
    assert kept[:2] == effects[:2]
    assert kept[2:4] == [None, None]
    assert kept[4] == effects[4].model_copy(update={"concealed": None})
    plain = SetEngagement(force=fid("norra_kites"), zone="z", rule=Engagement.DEFEND)
    assert detect.aide_may(plain) is plain


def test_every_aide_filter_keeps_the_intelligence_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = game(tmp_path)
    effects = _intel_effects()
    asks = tuple(Ask(ask=f"ask {n}", effect=e) for n, e in enumerate(effects))
    standing = {seat("ilse"): frozenset({"allocate"})}  # even a standing order to allocate
    state = g.state.model_copy(update={"standing": standing})

    by_close = wake._allowed(state, seat("ilse"), asks)
    _bounded([a.effect for a in by_close])
    assert len(by_close) == 3

    monkeypatch.setattr(options, "_live", lambda view: [object()])
    monkeypatch.setattr(options, "_wants_a_deal", lambda mandate: False)
    monkeypatch.setattr(options, "_options_for", lambda *a, **k: [SimpleNamespace(asks=asks)])
    (filed,) = options.aide_asks(state, seat("ilse"), None)
    _bounded([a.effect for a in filed])
    assert len(filed) == 3

    routed = SimpleNamespace(parts=(), order_id=OrderId("o"))
    survivors, dropped = estimate.clamp(state, routed, effects, day(1), aide=True)  # type: ignore[arg-type]
    _bounded(survivors)
    assert len(survivors) == 3 and len(dropped) == 3
    own, _ = estimate.clamp(state, routed, effects, day(1))  # type: ignore[arg-type]
    assert list(own) == effects


# --- State, events, sealing and catch-up --------------------------------------------------


def _deadline() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _committed(g: Logged, *orders: OrderId) -> State:
    g.add([ev.WakeOpened(wake=0, deadline=_deadline())])
    g.add([ev.WakeCommitted(wake=0, seat_id=seat("ilse"), by_aide=True, aide_orders=orders)])
    return g.state


def test_the_aides_orders_are_kept_in_state_with_reports_on(tmp_path: Path) -> None:
    oid = OrderId(entity("an-order"))
    assert _committed(game(tmp_path), oid).aide_orders == frozenset({oid})


def test_a_game_without_reports_keeps_no_aide_orders_and_its_hash(tmp_path: Path) -> None:
    def plain(tmp: Path) -> Logged:
        tmp.mkdir()
        return Logged(detection_toy(tmp, rules("territories"), strengths), "ilse", "tomas")

    named = _committed(plain(tmp_path / "a"), OrderId("o"))
    bare = _committed(plain(tmp_path / "b"))
    assert named.aide_orders == frozenset()
    assert state_hash(named) == state_hash(bare)


def test_the_new_kinds_are_never_fed() -> None:
    assert {"agent_set", "codebreaking_set"} <= catchup.NEVER


def test_a_codebreaking_raise_is_sealed_in_the_day_walk(tmp_path: Path) -> None:
    from revisionist.engine import realism_tick

    g = _code_game(tmp_path)
    scope = realism_tick._scope_of(
        g.state, ev.CodebreakingSet(nation=entity(NORRA), level=1, on=day(2))
    )
    assert scope.visibility is Visibility.RESTRICTED
    assert not scope.visible_to(seat("ilse")) and not scope.visible_to(seat("tomas"))


def test_an_agent_set_folds_by_index_and_refuses_a_gap(tmp_path: Path) -> None:
    from revisionist.core.fold import FoldError

    g = _agent_game(tmp_path)
    (placed,) = detect.place_agent(g.state, entity(NORRA), entity("isle"), day(1))
    with pytest.raises(FoldError, match="agent"):
        g.add([placed.model_copy(update={"index": 1})])
    land(g, (placed,))
    lost = placed.agent.model_copy(update={"lost": day(9)})
    g.add([ev.AgentSet(nation=entity(NORRA), index=0, agent=lost)])
    assert g.state.intelligence[entity(NORRA)].agents == (lost,)


def test_an_intelligence_event_needs_the_reports_rule(tmp_path: Path) -> None:
    from revisionist.core.fold import FoldError

    g = Logged(detection_toy(tmp_path, rules("territories"), strengths), "ilse", "tomas")
    with pytest.raises(FoldError, match="reports rule"):
        g.add([ev.CodebreakingSet(nation=entity(NORRA), level=1, on=day(2))])
