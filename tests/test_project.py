"""Layer 2: projection soundness. The type-level leak test."""

from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st

from revisionist.core.fold import replay
from revisionist.core.goals import (
    AimRule,
    AllOf,
    Exposure,
    Goal,
    GoalKind,
    GoalSource,
    HoldsArea,
    RegardAt,
    SupportAt,
    post_sees,
)
from revisionist.core.goals import at_post as goal_at_post
from revisionist.core.ids import EntityId, GoalId, QuantityId, SeatId
from revisionist.core.ontology import Controller, SeatStatus
from revisionist.core.project import HasScope, at_post, project
from revisionist.core.realism import agreement, detect, economy, groups
from revisionist.core.realism.agreement import Agreement, Agreements
from revisionist.core.realism.detect import Confidence, Picture, Report, Source
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.effect import AgreementClause, ClauseType
from revisionist.core.realism.groups import Spent
from revisionist.core.realism.quantity import Quantity
from revisionist.core.state import SeatFace, State
from revisionist.core.visibility import Scope, Visibility
from tests import fixtures as fx
from tests import strategies as s
from tests import test_realism_locks as toy_locks


def test_south_cannot_see_norths_secrets() -> None:
    state = replay(fx.creation_events())
    view = project(state, fx.SOUTH)
    assert fx.A_NORTH_SECRET_ARMY not in view.assets
    assert fx.F_NORTH_PLOT not in view.facts
    assert fx.C_NORTH_PLOT not in view.clocks
    assert fx.A_NORTH_ARMY in view.assets
    assert fx.F_PUBLIC_TREATY in view.facts
    assert fx.M_NORTH_STABILITY in view.meters  # restricted to north+south
    assert fx.CANARY not in view.model_dump_json()


def test_north_sees_its_own_secrets_and_guild_does_not_see_the_meter() -> None:
    state = replay(fx.creation_events())
    north = project(state, fx.NORTH)
    assert fx.A_NORTH_SECRET_ARMY in north.assets
    assert fx.F_NORTH_PLOT in north.facts
    guild = project(state, fx.GUILD)
    assert fx.M_NORTH_STABILITY not in guild.meters
    assert fx.A_GUILD_NETWORK in guild.assets
    assert fx.A_GUILD_NETWORK not in project(state, fx.HERALD).assets


def test_other_seats_show_only_their_face() -> None:
    state = replay(fx.creation_events())
    south = project(state, fx.SOUTH)
    assert set(SeatFace.model_fields) == {"seat_id", "kind", "name", "embodies"}
    assert isinstance(south.seats[fx.NORTH], SeatFace)
    assert south.seats[fx.NORTH].name == state.seats[fx.NORTH].name
    assert south.me == state.seats[fx.SOUTH]
    north = project(state, fx.NORTH)
    assert north.me.objectives == {fx.C_NORTH_PLOT}
    for word in ("controller", "persona", "objectives", "standing_orders", '"agent"'):
        assert word not in north.seats[fx.SOUTH].model_dump_json()


@h_settings(max_examples=200, deadline=None)
@given(
    controller=st.sampled_from(Controller),
    status=st.sampled_from(SeatStatus),
    blinded=st.booleans(),
    slots=st.integers(0, 5),
)
def test_how_another_seat_is_run_never_changes_a_view(
    controller: Controller, status: SeatStatus, blinded: bool, slots: int
) -> None:
    """spec §17: human or AI, agent, persona, status and deputy stay hidden."""
    state = replay(fx.creation_events())
    before = project(state, fx.SOUTH).model_dump_json()
    north = state.seats[fx.NORTH].model_copy(
        update={
            "controller": controller,
            "status": status,
            "agent": None if blinded else state.seats[fx.NORTH].agent,
            "persona": None,
            "slots": slots,
            "standing_orders": ("march at dawn",),
        }
    )
    changed = state.model_copy(update={"seats": {**state.seats, fx.NORTH: north}})
    assert project(changed, fx.SOUTH).model_dump_json() == before


def test_unknown_seat_is_refused() -> None:
    with pytest.raises(KeyError):
        project(replay(fx.creation_events()), SeatId("01ARZ3NDEKTSV4RRFFQ69G5ZZZ"))


@st.composite
def states_and_seats(draw: st.DrawFn) -> tuple[State, SeatId]:
    seats = draw(st.lists(s.seats, min_size=1, max_size=4, unique_by=lambda x: x.seat_id))
    state = State(
        campaign_id=draw(s.campaign_ids),
        assets={a.asset_id: a for a in draw(st.lists(s.assets, max_size=6))},
        relationships={r.relationship_id: r for r in draw(st.lists(s.relationships, max_size=4))},
        meters={m.meter_id: m for m in draw(st.lists(s.meters, max_size=4))},
        clocks={c.clock_id: c for c in draw(st.lists(s.clocks, max_size=6))},
        facts={f.fact_id: f for f in draw(st.lists(s.facts, max_size=8))},
        scheduled={e.scheduled_id: e for e in draw(st.lists(s.scheduled_events, max_size=3))},
        commitments={c.commitment_id: c for c in draw(st.lists(s.commitments, max_size=3))},
        seats={x.seat_id: x for x in seats},
    )
    return state, draw(st.sampled_from(seats)).seat_id


@h_settings(max_examples=300, deadline=None)
@given(states_and_seats())
def test_projection_is_sound(case: tuple[State, SeatId]) -> None:
    """Nothing in a view has a scope that excludes the viewer."""
    state, seat = case
    view = project(state, seat)
    scoped: list[HasScope] = [
        *view.assets.values(),
        *view.relationships.values(),
        *view.meters.values(),
        *view.clocks.values(),
        *view.facts.values(),
        *view.scheduled.values(),
        *view.commitments.values(),
    ]
    for item in scoped:
        assert item.scope.visible_to(seat)
    hidden = [
        f
        for f in state.facts.values()
        if f.scope.visibility is not Visibility.PUBLIC and seat not in f.scope.known_by
    ]
    for f in hidden:
        assert f.fact_id not in view.facts
    assert view.viewer == seat


# --- a commander held to his post (PVW) -----------------------------------------------


def _post_game(tmp_path: Path, *rules: str) -> State:
    """The lock tests' toy game (Ilse, Norra's chancellor, political; Kara, its general,
    military; Olaf, Kara's aide, political) with the groups rule and ``rules`` on."""

    def on(w: dict[str, Any]) -> None:
        w["rules"] = sorted({*w["rules"], "groups", *rules})

    tmp_path.mkdir(parents=True, exist_ok=True)
    return toy_locks.game(tmp_path, on)


def test_post_view_holds_only_military_seats_and_only_with_the_rule_on(tmp_path: Path) -> None:
    off = _post_game(tmp_path / "off")
    on = _post_game(tmp_path / "on", "post_view")
    assert not any(at_post(off, s) for s in off.seats)
    assert at_post(on, toy_locks.seat(toy_locks.KARA))
    assert not at_post(on, toy_locks.seat(toy_locks.ILSE))
    assert not at_post(on, toy_locks.seat(toy_locks.OLAF))


def test_post_view_off_leaves_every_view_as_it_was(tmp_path: Path) -> None:
    off = _post_game(tmp_path / "off")
    for seat in off.seats:
        assert at_post(off, seat) is False
        view = project(off, seat)
        assert view.groups == groups.seen_by(off, seat)
        assert view.economy == economy.seen_by(off, seat)
        assert view.agreements == agreement.seen_by(off, seat)
        assert view.reports == {**detect.seen_by(off, seat), **detect.envoys(off, seat)}


def test_the_home_sheet_post_sees_none_of_his_nations_groups_or_their_support(
    tmp_path: Path,
) -> None:
    base = _post_game(tmp_path, "post_view")
    norra = toy_locks.NORRA
    assert base.groups.declared.get(norra), "the toy declares Norra's groups"
    day = base.in_world_date
    assert day is not None
    held = base.groups.model_copy(
        update={
            "support": {norra: {"smiths": 61}},
            "spent": {norra: {"smiths": (Spent(on=day, points=2),)}},
        }
    )
    state = base.model_copy(update={"groups": held})
    ilse = project(state, toy_locks.seat(toy_locks.ILSE)).groups
    kara = project(state, toy_locks.seat(toy_locks.KARA)).groups
    assert ilse.support[norra] == state.groups.support[norra]
    assert ilse.declared[norra]
    assert kara.declared == {} and kara.themes == {}
    assert kara.support == {} and kara.spent == {}
    assert kara.classes == ilse.classes and kara.places == ilse.places


def test_the_economy_sheet_post_sees_the_fuel_stock_only(tmp_path: Path) -> None:
    base = _post_game(tmp_path, "post_view")
    norra = toy_locks.NORRA
    pools = {norra: Pools(output=11, manpower=12, fuel=13)}
    lines = base.economy.model_copy(update={"pools": pools})
    state = base.model_copy(update={"economy": lines})
    ilse = project(state, toy_locks.seat(toy_locks.ILSE)).economy
    kara = project(state, toy_locks.seat(toy_locks.KARA)).economy
    assert ilse.pools == pools
    assert kara.pools == {norra: Pools(fuel=13)}
    assert kara.yields == {} and kara.pending == {} and kara.lines == {}


def test_the_post_reads_only_reports_within_reach_of_his_forces(tmp_path: Path) -> None:
    base = _post_game(tmp_path / "on", "post_view")
    plain = _post_game(tmp_path / "off")
    day = base.in_world_date
    assert day is not None
    near, far = toy_locks.key_id("norrhavn"), toy_locks.key_id("sudby")
    kara = toy_locks.seat(toy_locks.KARA)
    assert near in detect.post_reach(base, kara) and far not in detect.post_reach(base, kara)

    def report(key: str, area: EntityId) -> Report:
        return Report(
            key=key,
            area=area,
            seen=day,
            source=Source.CONTACT,
            rank=0,
            confidence=Confidence.A,
            arrives=day,
        )

    seen = Picture(delivered={"near": report("near", near), "far": report("far", far)})
    pictures = {toy_locks.NORRA: seen}
    state = base.model_copy(update={"reports": pictures})
    before = plain.model_copy(update={"reports": pictures})
    assert set(project(state, kara).reports) == {"near"}
    assert set(project(state, toy_locks.seat(toy_locks.ILSE)).reports) == {"near", "far"}
    assert set(project(before, kara).reports) == {"near", "far"}


def test_the_post_sees_published_agreements_and_public_quantities_only(tmp_path: Path) -> None:
    base = _post_game(tmp_path, "post_view")
    norra, sudland = toy_locks.NORRA, toy_locks.key_id("sudland")
    day = base.in_world_date
    assert day is not None
    secret = Agreement(agreement_id="truce", version="1", parties=(norra, sudland), made=day)
    public = secret.model_copy(update={"agreement_id": "border", "published": day})
    held = AgreementClause(type=ClauseType.ARMISTICE, binds=norra, nation=sudland, days=10)
    front = secret.model_copy(update={"agreement_id": "armistice", "clauses": (held,)})
    placed = AgreementClause(
        type=ClauseType.PLACE, binds=norra, force=toy_locks.LEVY, area=norra, on=day
    )
    levy = secret.model_copy(update={"agreement_id": "levy", "clauses": (placed,)})
    made = Agreements(made={"truce": secret, "border": public, "armistice": front, "levy": levy})
    sealed_scope = Scope(
        visibility=Visibility.RESTRICTED,
        known_by=frozenset({toy_locks.seat(toy_locks.ILSE), toy_locks.seat(toy_locks.KARA)}),
    )
    figure = Quantity(
        quantity_id=QuantityId("treasury"),
        owner=norra,
        name="Norra's treasury",
        value=7,
        unit="crowns",
        as_of=day,
        scope=sealed_scope,
    )
    quantities = {**base.quantities, figure.quantity_id: figure}
    state = base.model_copy(update={"agreements": made, "quantities": quantities})
    ilse = project(state, toy_locks.seat(toy_locks.ILSE))
    kara = project(state, toy_locks.seat(toy_locks.KARA))
    assert set(ilse.agreements.made) == {"truce", "border", "armistice", "levy"}
    assert set(kara.agreements.made) == {"border", "levy"}
    sealed = {
        k
        for k, q in ilse.quantities.items()
        if q.scope is not None and q.scope.visibility is not Visibility.PUBLIC
    }
    assert QuantityId("treasury") in sealed
    assert not sealed & set(kara.quantities)
    assert kara.offers == ()


def test_the_score_post_cannot_tell_whether_an_aim_on_his_nations_facts_holds() -> None:
    norra, sudland = EntityId("norra"), EntityId("sudland")
    support = SupportAt(nation=norra, group="greys", op="ge", value=50)
    held = HoldsArea(area=EntityId("isle"), holder=norra)
    regard = RegardAt(a=EntityId("kara"), b=EntityId("ilse"), op="ge", value=1)
    both = AllOf(conditions=(held, support, regard))
    sees = (Exposure.PUBLIC, Exposure.OWN, Exposure.OWN)
    assert post_sees(both, sees) == (Exposure.PUBLIC, Exposure.HIDDEN, Exposure.OWN)
    assert post_sees(both, sees[:2]) == sees[:2]
    goal = Goal(
        goal_id=GoalId("g"),
        seat_id=SeatId("s"),
        text="t",
        condition=both,
        kind=GoalKind.UNDOABLE,
        clock_id=None,
        met_tick=3,
        holding=True,
        scope=Scope(visibility=Visibility.PUBLIC),
        person=EntityId("kara"),
        source=GoalSource.POST,
        aim=1,
    )
    rule = AimRule(condition=both, rule="r", sees=sees)
    assert (goal_at_post(goal, rule).holding, goal_at_post(goal, rule).met_tick) == (False, None)
    public = AimRule(condition=held, rule="r", sees=(Exposure.PUBLIC,))
    plain = goal.model_copy(update={"condition": held})
    assert goal_at_post(plain, public) == plain
    legacy = goal.model_copy(update={"person": None, "source": None, "aim": None})
    assert goal_at_post(legacy, None).holding is True
    assert sudland != norra
