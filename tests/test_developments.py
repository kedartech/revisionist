"""Developments: a world's deck of dated, conditional, drawn public events.

A development is declared beside a world in ``worlds/developments/<world>.yaml``,
compiles to a scheduled event with ``source: development``, and is drawn once per
campaign: a day in its window, or none. Its effects are a figure or a disposition,
and it reaches orders only through its suggested asks.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.goals import EntityIs
from revisionist.core.history import developments_due, drawn_day, settle
from revisionist.core.ids import CampaignId, QuantityId, ScheduledEventId
from revisionist.core.ontology import (
    DevelopmentCategory,
    EntityStatus,
    ScheduledEvent,
    ScheduleSource,
)
from revisionist.core.realism.effect import MoveFigure, ShiftDisposition
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC
from revisionist.core.world import DevelopmentDecl, WorldFile
from revisionist.core.world_compile import WorldError, compile_world, object_id
from revisionist.engine import campaign as cmp
from tests import fixtures as fx

HOLDS = EntityIs(check="entity_is", entity=fx.E_NORTH, status=EntityStatus.ACTIVE)
FAILS = EntityIs(check="entity_is", entity=fx.E_SOUTH, status=EntityStatus.DEAD)
DEV = ScheduledEventId("01ARZ3NDEKTSV4RRFFQ69G5HD0")
START = date(1478, 4, 1)
END = date(1478, 4, 20)


def _development(**kw: object) -> ScheduledEvent:
    base: dict[str, object] = dict(
        scheduled_id=DEV,
        fire_at_tick=0,
        name="a development",
        scope=PUBLIC,
        source=ScheduleSource.DEVELOPMENT,
        on_date=START,
        window_end=END,
        chance=100,
        category=DevelopmentCategory.WEATHER,
        condition=HOLDS,
        headline="Rain closes the roads",
        subject=fx.E_NORTH,
    )
    return ScheduledEvent.model_validate(base | kw)


def _built(*scheduled: ScheduledEvent) -> State:
    base = fx.creation_events()
    extra = [
        fx.envelope(len(base) + i, ev.ScheduledEventCreated(scheduled=s))
        for i, s in enumerate(scheduled)
    ]
    return replay([*base, *extra])


def _decl(**kw: object) -> dict[str, object]:
    base: dict[str, object] = dict(
        key="mud",
        name="The autumn rains",
        category="weather",
        window={"start": "1941-10-05", "end": "1941-10-20"},
        headline="Rain turns the roads to mud",
        subject="ussr",
        source="Glantz and House, When Titans Clashed (1995)",
    )
    return base | kw


def _autumn() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


# --- the declaration ---------------------------------------------------------


def test_a_window_must_not_end_before_it_starts() -> None:
    with pytest.raises(ValidationError, match="window"):
        DevelopmentDecl.model_validate(_decl(window={"start": "1941-10-05", "end": "1941-10-04"}))


def test_a_development_is_cited_or_a_gap() -> None:
    DevelopmentDecl.model_validate(_decl(source=None, gap=True))
    with pytest.raises(ValidationError, match="source"):
        DevelopmentDecl.model_validate(_decl(source=None))
    with pytest.raises(ValidationError, match="source"):
        DevelopmentDecl.model_validate(_decl(gap=True))


def test_effects_are_only_a_figure_or_a_disposition() -> None:
    ok = DevelopmentDecl.model_validate(
        _decl(
            effects=[
                {"kind": "figure", "quantity": "gallup_help_britain", "percent": 5},
                {"kind": "disposition", "of": "stalin", "toward": "roosevelt", "change": 1},
            ]
        )
    )
    assert [e.kind for e in ok.effects] == ["figure", "disposition"]
    with pytest.raises(ValidationError):
        DevelopmentDecl.model_validate(
            _decl(effects=[{"kind": "statement", "theme": "peace", "audience": None}])
        )


def test_a_figure_moves_no_more_than_an_order_may() -> None:
    with pytest.raises(ValidationError):
        DevelopmentDecl.model_validate(
            _decl(effects=[{"kind": "figure", "quantity": "gallup_help_britain", "percent": 11}])
        )


def test_at_most_two_suggested_asks() -> None:
    DevelopmentDecl.model_validate(_decl(asks=["Ask Congress for funds", "Brief the press"]))
    with pytest.raises(ValidationError):
        DevelopmentDecl.model_validate(_decl(asks=["a", "b", "c"]))


def test_a_development_carries_only_development_fields() -> None:
    with pytest.raises(ValidationError, match="development"):
        _development(source=ScheduleSource.HISTORY)
    with pytest.raises(ValidationError, match="window"):
        _development(window_end=START - timedelta(days=1))
    with pytest.raises(ValidationError, match="development"):
        _development(category=None)


def test_a_compiled_development_keeps_the_figure_cap_and_its_effects() -> None:
    big = MoveFigure(quantity=QuantityId("01ARZ3NDEKTSV4RRFFQ69G5HQ0"), percent=11)
    with pytest.raises(ValidationError, match="at most"):
        _development(effects=(big,))
    with pytest.raises(ValidationError, match="only a development"):
        _development(
            source=ScheduleSource.HISTORY,
            window_end=None,
            chance=None,
            category=None,
            asks=("Brief the press",),
        )


# --- loading and compiling ---------------------------------------------------


def test_the_autumn_1941_sidecar_loads_a_deck_of_ten_to_fifteen() -> None:
    world = _autumn()
    assert 10 <= len(world.developments) <= 15
    assert {d.category for d in world.developments} == set(DevelopmentCategory)
    assert all(d.source or d.gap for d in world.developments)


def test_the_deck_compiles_to_development_events_with_ids_bound() -> None:
    world = _autumn()
    events = compile_world(world, fx.CAMPAIGN, cmp.versions())
    made = [
        e.payload.scheduled
        for e in events
        if isinstance(e.payload, ev.ScheduledEventCreated)
        and e.payload.scheduled.source is ScheduleSource.DEVELOPMENT
    ]
    assert len(made) == len(world.developments)
    first, decl = made[0], world.developments[0]
    assert first.scheduled_id == object_id(fx.CAMPAIGN, "development", decl.key)
    assert first.on_date == decl.window.start and first.window_end == decl.window.end
    assert first.asks == decl.asks
    state = replay(events)
    for s in made:
        for e in s.effects:
            if isinstance(e, MoveFigure):
                assert e.quantity in state.quantities
            if isinstance(e, ShiftDisposition):
                assert e.of in state.entities and e.toward in state.entities


def test_a_development_naming_an_unknown_key_does_not_compile() -> None:
    world = _autumn()
    bad = DevelopmentDecl.model_validate(
        _decl(effects=[{"kind": "figure", "quantity": "no_such_figure", "percent": 5}])
    )
    with pytest.raises(WorldError) as info:
        compile_world(world.model_copy(update={"developments": (bad,)}), fx.CAMPAIGN, fx.VERSIONS)
    assert any("development mud" in p and "no_such_figure" in p for p in info.value.problems)


def test_a_window_before_the_start_date_does_not_compile() -> None:
    world = _autumn()
    bad = DevelopmentDecl.model_validate(_decl(window={"start": "1941-08-01", "end": "1941-09-20"}))
    with pytest.raises(WorldError) as info:
        compile_world(world.model_copy(update={"developments": (bad,)}), fx.CAMPAIGN, fx.VERSIONS)
    assert any("development mud" in p and "start date" in p for p in info.value.problems)


def test_an_absent_or_empty_sidecar_changes_nothing(tmp_path: Path) -> None:
    src = cmp.world_path("autumn-1941")
    path = tmp_path / "autumn-1941.yaml"
    path.write_text(src.read_text())
    bare = cmp.load_world(path)
    assert bare.developments == ()
    plain = WorldFile.model_validate(yaml.safe_load(src.read_text()))
    assert bare == plain
    (tmp_path / "developments").mkdir()
    (tmp_path / "developments" / "autumn-1941.yaml").write_text("world: autumn-1941\n")
    assert cmp.load_world(path) == plain
    campaign = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
    assert compile_world(cmp.load_world(path), campaign, fx.VERSIONS) == compile_world(
        plain, campaign, fx.VERSIONS
    )


def test_a_sidecar_for_another_world_is_refused(tmp_path: Path) -> None:
    src = cmp.world_path("autumn-1941")
    path = tmp_path / "autumn-1941.yaml"
    path.write_text(src.read_text())
    (tmp_path / "developments").mkdir()
    (tmp_path / "developments" / "autumn-1941.yaml").write_text("world: salt-strait\n")
    with pytest.raises(ValueError, match="salt-strait"):
        cmp.load_world(path)


# --- the draw ----------------------------------------------------------------


def test_the_draw_is_fixed_for_a_campaign_and_inside_the_window() -> None:
    s = _development()
    day = drawn_day(fx.CAMPAIGN, s)
    assert day is not None and START <= day <= END
    assert all(drawn_day(fx.CAMPAIGN, s) == day for _ in range(5))


def test_the_draw_varies_across_campaigns() -> None:
    s = _development()
    days = {drawn_day(CampaignId(f"01ARZ3NDEKTSV4RRFFQ69G5F{i:02d}"), s) for i in range(30)}
    assert len(days) > 3


def test_chance_decides_how_often_it_happens() -> None:
    s = _development(chance=30)
    hits = sum(
        drawn_day(CampaignId(f"01ARZ3NDEKTSV4RRFF{i:08d}"), s) is not None for i in range(400)
    )
    assert 80 <= hits <= 160


def test_a_development_fires_on_its_drawn_day_when_its_condition_holds() -> None:
    drawn = (
        _development(scheduled_id=ScheduledEventId(f"01ARZ3NDEKTSV4RRFFQ69G5H{i:02d}"))
        for i in range(10, 99)
    )
    s = next(d for d in drawn if (drawn_day(fx.CAMPAIGN, d) or START) > START)
    state = _built(s)
    day = drawn_day(state.campaign_id, s)
    assert day is not None
    assert developments_due(state, day - timedelta(days=1)) == []
    assert developments_due(state, day) == [ev.ScheduledEventFired(scheduled_id=s.scheduled_id)]


def test_a_false_condition_never_fires_and_adds_no_divergence() -> None:
    state = _built(_development(condition=FAILS))
    out = developments_due(state, END)
    assert out == [ev.ScheduledEventSkipped(scheduled_id=DEV)]


def test_a_development_the_draw_rules_out_is_skipped_once_its_window_closes() -> None:
    drawn = (
        _development(chance=1, scheduled_id=ScheduledEventId(f"01ARZ3NDEKTSV4RRFFQ69G5H{i:02d}"))
        for i in range(10, 99)
    )
    s = next(d for d in drawn if drawn_day(fx.CAMPAIGN, d) is None)
    state = _built(s)
    assert developments_due(state, END - timedelta(days=1)) == []
    assert developments_due(state, END) == [ev.ScheduledEventSkipped(scheduled_id=s.scheduled_id)]


def test_a_settled_development_is_not_drawn_again() -> None:
    state = _built(_development())
    fired = fx.envelope(len(fx.creation_events()) + 1, ev.ScheduledEventFired(scheduled_id=DEV))
    assert developments_due(replay([fired], initial=state), END) == []


def test_history_settling_leaves_developments_alone() -> None:
    state = _built(_development())
    assert settle(state, END) == []
