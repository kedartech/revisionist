"""Hitler's army orders go through Jodl alone; the U-boat and production orders keep the
OKW directive with Raeder at its decision step."""

from revisionist.core.fold import replay
from revisionist.core.ids import CampaignId, EntityId, PipelineId
from revisionist.core.realism.pipeline import StepAction, StepKind
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, resolve_keys
from revisionist.engine import campaign as cmp

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
DECL = cmp.load_world(cmp.world_path("autumn-1941"))
KEYS = {k: EntityId(v) for k, v in resolve_keys(DECL, CAMPAIGN).items()}


def _state(decl: WorldFile = DECL) -> State:
    return replay(compile_world(decl, CAMPAIGN, cmp.versions()))


def _path(state: State, lever: str) -> list[EntityId]:
    card = state.cards[KEYS["hitler"]]
    pipeline = next(lv.pipeline for lv in card.levers if lv.name == lever)
    return [step.person for step in state.pipelines[PipelineId(pipeline)].steps]


def test_the_compiled_path_of_move_army_has_no_raeder_step() -> None:
    path = _path(_state(), "move_army")
    assert KEYS["raeder"] not in path
    assert path == [KEYS["jodl"]]


def test_jodls_step_is_a_decision_of_two_days_that_may_pass_expedite_stall_or_amend() -> None:
    state = _state()
    card = state.cards[KEYS["hitler"]]
    lever = next(lv for lv in card.levers if lv.name == "move_army")
    (step,) = state.pipelines[PipelineId(lever.pipeline)].steps
    assert step.kind is StepKind.DECISION
    assert step.days == 2
    assert step.allowed == {
        StepAction.PASS,
        StepAction.EXPEDITE,
        StepAction.STALL,
        StepAction.AMEND,
    }


def test_the_u_boat_and_production_orders_keep_the_okw_directive() -> None:
    state = _state()
    for lever in ("uboat_directive", "production_priority"):
        assert _path(state, lever) == [KEYS["jodl"], KEYS["raeder"]], lever
    card = state.cards[KEYS["hitler"]]
    army = next(lv.pipeline for lv in card.levers if lv.name == "move_army")
    kept = {lv.pipeline for lv in card.levers if lv.name != "move_army" and lv.resolver != "war"}
    assert army not in kept


def test_hitler_carries_the_army_pipeline_and_raeder_does_not() -> None:
    state = _state()
    army = next(lv.pipeline for lv in state.cards[KEYS["hitler"]].levers if lv.name == "move_army")
    assert army in state.cards[KEYS["hitler"]].pipelines
    assert army not in state.cards[KEYS["raeder"]].pipelines
