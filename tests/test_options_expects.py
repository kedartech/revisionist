"""What the staff expect a suggested action to move: ``Option.expects`` and ``Option.risks``.

Each expected move names a target the seat's view holds: a person's regard, the stance
of a leader weighed against the seat, a stake, or a reported figure. Code drops an entry
naming anything else and keeps the action. The desk's own list carries neither field,
and no rule reads them: filing an action is the same with or without them. No test here
calls a model.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.ids import ContestId, QuantityId, derived_id
from revisionist.core.ontology import Contest, ContestKind
from revisionist.core.project import project
from revisionist.core.realism.agenda import Expect, ExpectOn, Option, PlayStyle, Risks
from revisionist.core.realism.quantity import Quantity
from revisionist.core.realism.stance import Stance, StanceCause, Standing
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.engine import expects, options
from revisionist.engine import realism_tick as rt
from revisionist.engine.llm import Reply, Request
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import agenda_api
from revisionist.engine.web import realism_api as api
from tests.test_engine_v2_contract import CAMPAIGN, Slice
from tests.test_engine_v2_options import _normalised, _parts, _store

FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
SRC = Path(__file__).parents[1] / "src" / "revisionist"
LOGGER = "revisionist.engine.options"
OPEN = ContestId(derived_id(CAMPAIGN, "contest", "open"))
DECIDED = ContestId(derived_id(CAMPAIGN, "contest", "decided"))
HIDDEN = QuantityId(derived_id(CAMPAIGN, "quantity", "hidden"))
BLANK = QuantityId(derived_id(CAMPAIGN, "quantity", "blank"))


def _world() -> tuple[Slice, State]:
    """Roosevelt, beginner, one mandate; Wheeler weighed against him; an open and a
    decided stake; a figure he cannot see and one with no value."""
    sl = Slice()
    sl.add(ev.MandateIssued(mandate=sl.mandate(1, sl.fdr)), private_to(sl.fdr))
    sl.add(ev.PlayStyleSet(seat_id=sl.fdr, style=PlayStyle.BEGINNER), private_to(sl.fdr))
    state = sl.state
    today = date(1941, 9, 11)
    standing = Standing(
        on=today,
        stance=Stance.OBSTRUCTING,
        score=-4,
        side=0,
        disposition=-1,
        cause=StanceCause.START,
    )
    sides = (sl.entity("usa"), sl.entity("germany"))
    contest = {
        cid: Contest(
            contest_id=cid,
            kind=ContestKind.RIVALRY,
            name=name,
            prize="The sea lanes",
            sides=sides,
            track=0,
            momentum=0,
            countdown_days=30,
            decided=cid == DECIDED,
            scope=PUBLIC,
        )
        for cid, name in ((OPEN, "The Atlantic"), (DECIDED, "An old quarrel"))
    }
    hidden = Quantity(
        quantity_id=HIDDEN,
        name="Wheeler's private count",
        value=12,
        unit="votes",
        as_of=today,
        scope=private_to(sl.wheeler),
    )
    blank = Quantity(
        quantity_id=BLANK,
        name="An unknown figure",
        value=None,
        unit="ships",
        as_of=today,
        scope=PUBLIC,
    )
    state = state.model_copy(
        update={
            "stances": {sl.fdr: {sl.entity("wheeler"): (standing,)}},
            "contests": {**state.contests, **contest},
            "quantities": {**state.quantities, HIDDEN: hidden, BLANK: blank},
        }
    )
    return sl, state


def _house(state: State) -> QuantityId:
    return next(q for q, x in state.quantities.items() if x.name == "House Democrats")


def _move(on: str, target: str, **fields: Any) -> dict[str, Any]:
    return {"on": on, "target": target, "direction": "gain", "size": 1, "sure": "likely"} | fields


class _Same:
    """Gives the same reply to every request, and keeps what it was asked."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply, self.requests = reply, []  # type: ignore[var-annotated]

    def call(self, request: Request) -> Reply:
        self.requests.append(request)
        return Reply(self.reply, "hand", 0, 0, 0, 0.0)


def _offer(sl: Slice, state: State, first: dict[str, Any]) -> ev.OptionsOffered:
    p = _parts(sl)
    reply = {"options": [p["patrol"] | first, p["word"], p["press"]]}
    made = options.offer(state, sl.fdr, _Same(reply))
    assert made is not None
    return made


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER]


# --- the fields -------------------------------------------------------------------


def test_an_option_without_the_fields_dumps_as_before() -> None:
    plain = Option(label="Patrol", asks=({"ask": "Patrol"},))
    dumped = plain.model_dump(mode="json")
    assert "expects" not in dumped and "risks" not in dumped
    full = plain.model_copy(
        update={
            "expects": (Expect.model_validate(_move("figure", "q1")),),
            "risks": Risks(escalation=3, refusal=0, exposure=1),
        }
    )
    assert full.model_dump(mode="json")["risks"] == {"escalation": 3, "refusal": 0, "exposure": 1}


@pytest.mark.parametrize(
    "bad",
    [
        _move("figure", "q1", size=0),
        _move("figure", "q1", size=3),
        _move("figure", "q1", direction="up"),
        _move("figure", "q1", sure="certain"),
        _move("mood", "q1"),
    ],
)
def test_an_expected_move_is_one_or_two_steps_of_a_known_kind(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Expect.model_validate(bad)


@pytest.mark.parametrize("level", [-1, 4])
def test_each_risk_runs_from_zero_to_three(level: int) -> None:
    with pytest.raises(ValidationError):
        Risks(escalation=level, refusal=0, exposure=0)


def test_an_option_holds_at_most_four_expected_moves() -> None:
    move = Expect.model_validate(_move("figure", "q1"))
    with pytest.raises(ValidationError):
        Option(label="P", asks=({"ask": "P"},), expects=(move,) * 5)


# --- what the seat's view holds -----------------------------------------------------


def test_the_targets_are_what_the_seats_view_holds() -> None:
    sl, state = _world()
    found = expects.targets(state, project(state, sl.fdr))
    people = {sl.entity(k) for k in ("stark", "rayburn", "wheeler", "churchill", "pound")}
    assert set(found[ExpectOn.REGARD]) == people  # every person with a card but his own
    assert found[ExpectOn.STANCE] == {sl.entity("wheeler"): "Burton K. Wheeler"}
    assert found[ExpectOn.STAKE] == {OPEN: "The Atlantic"}
    figures = found[ExpectOn.FIGURE]
    assert _house(state) in figures and HIDDEN not in figures and BLANK not in figures


def test_a_target_outside_the_view_is_dropped_logged_and_the_option_kept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sl, state = _world()
    house = _house(state)
    wanted = [
        _move("figure", house),
        _move("figure", HIDDEN),  # another seat's figure
        _move("figure", BLANK),  # no value reported
        _move("stake", DECIDED),
        _move("stance", sl.entity("stark")),  # not weighed against him
        _move("regard", sl.entity("roosevelt")),  # his own person
        _move("regard", "no-such-person"),
    ]
    with caplog.at_level(logging.INFO, logger=LOGGER):
        made = _offer(
            sl, state, {"expects": wanted, "risks": {"escalation": 2, "refusal": 1, "exposure": 0}}
        )
    first = made.offers[0].options[0]
    assert first.label == "Patrol the sea lanes"
    assert [(m.on.value, m.target) for m in first.expects] == [("figure", house)]
    assert first.risks == Risks(escalation=2, refusal=1, exposure=0)
    left = [line for line in _lines(caplog) if "expected move" in line]
    head = f"options for {sl.fdr} on 1941-09-01: an expected move left out"
    assert left.count(f"{head}: names something the seat cannot see") == 6 * len(made.offers)
    assert HIDDEN not in caplog.text and "no-such-person" not in caplog.text


def test_each_kind_the_view_holds_is_kept() -> None:
    sl, state = _world()
    wanted = [
        _move("regard", sl.entity("rayburn"), direction="cost", size=2, sure="firm"),
        _move("stance", sl.entity("wheeler"), sure="guess"),
        _move("stake", OPEN),
        _move("figure", _house(state)),
    ]
    first = _offer(sl, state, {"expects": wanted}).offers[0].options[0]
    assert [m.model_dump(mode="json") for m in first.expects] == wanted
    assert first.risks is None


def test_a_malformed_entry_or_a_fifth_is_dropped_not_the_option(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sl, state = _world()
    house = _house(state)
    good = [_move("figure", house, size=n % 2 + 1) for n in range(5)]
    wanted = [_move("figure", house, size=3), "a line of prose", *good]
    with caplog.at_level(logging.INFO, logger=LOGGER):
        first = (
            _offer(sl, state, {"expects": wanted, "risks": {"escalation": 9}}).offers[0].options[0]
        )
    assert first.label == "Patrol the sea lanes"
    assert [m.model_dump(mode="json") for m in first.expects] == good[:4]
    assert first.risks is None
    lines = _lines(caplog)
    head = f"options for {sl.fdr} on 1941-09-01"
    assert f"{head}: an expected move left out: not valid against the schema" in lines
    assert f"{head}: an expected move left out: more than four" in lines
    assert f"{head}: risks left out: not valid against the schema" in lines
    assert not [line for line in lines if "dropped" in line]


def test_expects_that_are_not_a_list_are_left_out() -> None:
    sl, state = _world()
    first = _offer(sl, state, {"expects": "none", "risks": "high"}).offers[0].options[0]
    assert first.label == "Patrol the sea lanes" and first.expects == () and first.risks is None


def test_the_desks_own_list_carries_neither() -> None:
    sl, state = _world()
    view = project(state, sl.fdr)
    for style in (PlayStyle.BEGINNER, PlayStyle.GUIDED):
        made = options.template_options(view, None, style)
        assert made and all(o.expects == () and o.risks is None for o in made)
    offline = options.offer(state, sl.fdr, None)
    assert offline is not None
    assert all(o.expects == () and o.risks is None for of in offline.offers for o in of.options)


def test_the_prompt_lists_what_the_seat_may_name() -> None:
    sl, state = _world()
    script = _Same({"options": []})
    options.offer(state, sl.fdr, script)
    prompt = script.requests[0].prompt
    wheeler = {"id": sl.entity("wheeler"), "name": "Burton K. Wheeler"}
    stake = {"id": OPEN, "name": "The Atlantic"}
    assert f'"leaders_weighed":[{json.dumps(wheeler, separators=(",", ":"))}]' in prompt
    assert f'"stakes":[{json.dumps(stake, separators=(",", ":"))}]' in prompt
    assert _house(state) in prompt
    assert HIDDEN not in prompt and BLANK not in prompt and DECIDED not in prompt
    schema = json.dumps(options.OPTIONS_SCHEMA)
    assert '"expects"' in schema and '"risks"' in schema


# --- no rule reads them -------------------------------------------------------------


def _with_moves(made: ev.OptionsOffered, state: State) -> ev.OptionsOffered:
    move = Expect.model_validate(_move("figure", _house(state), direction="cost", size=2))
    risks = Risks(escalation=3, refusal=3, exposure=3)
    offers = tuple(
        of.model_copy(
            update={
                "options": tuple(
                    o.model_copy(update={"expects": (move,) * 4, "risks": risks})
                    for o in of.options
                )
            }
        )
        for of in made.offers
    )
    return made.model_copy(update={"offers": offers})


@pytest.mark.parametrize("style", [PlayStyle.BEGINNER, PlayStyle.GUIDED])
def test_filing_an_action_is_the_same_with_and_without_the_fields(style: PlayStyle) -> None:
    """The order filed is the same. A beginner's single-ask option is also ticked through
    and the whole log compared; a guided plan's later rolls are seeded by its fresh order
    id, so two filings of one plan differ there with or without the fields."""
    filed: list[list[str]] = []
    logs: list[list[str]] = []
    for moves in (False, True):
        store, seat = _store(style)
        state = load_state(store, CAMPAIGN)
        made = options.offer(state, seat, None)
        assert made is not None
        if moves:
            made = _with_moves(made, state)
        rt._append(store, state, made, seat, private_to(seat))
        block = agenda_api.agenda(load_state(store, CAMPAIGN), seat, list(store.read(CAMPAIGN)))
        pick = block["initiative"][0]["pick"]
        assert bool(block["initiative"][0]["expects"]) is moves
        done = agenda_api.pick_option(store, CAMPAIGN, seat, pick)
        assert not done["refused"]
        filed.append(_normalised(store))
        if style is PlayStyle.BEGINNER:
            rt.run_realism_tick(store, CAMPAIGN)
            logs.append(_normalised(store))
    assert filed[0] == filed[1] and '"kind":"order_routed"' in filed[0][0]
    if style is PlayStyle.GUIDED:
        assert filed[0][0].count('"route":') >= 3
    else:
        assert logs[0] == logs[1]
        assert any("order_executed" in row for row in logs[0])


def test_no_rule_reads_expects_or_risks() -> None:
    allowed = {
        "core/realism/agenda.py",
        "engine/expects.py",
        "engine/options.py",
        "engine/web/agenda_api.py",
        "engine/web/realism_api.py",
    }
    read = re.compile(r"\.(expects|risks)\b|\[\"(expects|risks)\"\]")
    readers = sorted(
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if read.search(path.read_text()) and str(path.relative_to(SRC)) not in allowed
    )
    assert readers == []


# --- the agenda block ---------------------------------------------------------------


def _block_with(sl: Slice, state: State, made: ev.OptionsOffered) -> Any:
    sl.add(made, private_to(sl.fdr))
    return agenda_api.agenda(state, sl.fdr, sl.events)


def test_the_agenda_shows_each_move_by_name_with_the_risks() -> None:
    sl, state = _world()
    wanted = [
        _move("regard", sl.entity("stark"), sure="firm"),
        _move("stance", sl.entity("wheeler"), direction="cost", size=2, sure="guess"),
        _move("stake", OPEN),
        _move("figure", _house(state)),
    ]
    risks = {"escalation": 2, "refusal": 0, "exposure": 1}
    made = _offer(sl, state, {"expects": wanted, "risks": risks})
    block = _block_with(sl, state, made)
    first, *rest = block["items"][0]["options"]
    assert first["expects"] == [
        {"on": "regard", "name": "Harold R. Stark", "direction": "gain", "size": 1, "sure": "firm"},
        {
            "on": "stance",
            "name": "Burton K. Wheeler",
            "direction": "cost",
            "size": 2,
            "sure": "guess",
        },
        {"on": "stake", "name": "The Atlantic", "direction": "gain", "size": 1, "sure": "likely"},
        {
            "on": "figure",
            "name": "House Democrats",
            "direction": "gain",
            "size": 1,
            "sure": "likely",
        },
    ]
    assert first["risks"] == risks and first["risk"] == "It may go badly."
    assert all(o["expects"] == [] and o["risks"] is None for o in rest)
    assert set(first) == set(api.AgendaOption.__annotations__)
    assert set(first["expects"][0]) == set(api.AgendaExpect.__annotations__)
    assert set(first["risks"]) == set(api.AgendaRisks.__annotations__)


def test_a_move_whose_target_has_left_the_view_is_not_shown() -> None:
    sl, state = _world()
    made = _offer(
        sl, state, {"expects": [_move("stake", OPEN), _move("stance", sl.entity("wheeler"))]}
    )
    later = state.model_copy(
        update={
            "contests": {
                **state.contests,
                OPEN: state.contests[OPEN].model_copy(update={"decided": True}),
            },
            "stances": {},
        }
    )
    first = _block_with(sl, later, made)["items"][0]["options"][0]
    assert first["label"] == "Patrol the sea lanes" and first["expects"] == []


def test_a_guided_plans_steps_share_its_moves() -> None:
    sl, state = _world()
    state = state.model_copy(update={"styles": {sl.fdr: PlayStyle.GUIDED}})
    p = _parts(sl)
    plan = {
        "label": "A plan",
        "asks": [x for k in ("patrol", "word", "press") for x in p[k]["asks"]],
        "risk": "-",
        "expects": [_move("stake", OPEN)],
        "risks": {"escalation": 1, "refusal": 1, "exposure": 1},
    }
    made = options.offer(state, sl.fdr, _Same({"options": [plan]}))
    assert made is not None
    steps = _block_with(sl, state, made)["items"][0]["plan"]
    assert len(steps) == 3
    assert all(
        s["expects"][0]["name"] == "The Atlantic" and s["risks"]["refusal"] == 1 for s in steps
    )


def test_the_fixtures_options_have_the_blocks_keys() -> None:
    agenda = json.loads(FIXTURE.read_text())["agenda"]
    shown = [o for item in agenda["items"] for o in item["options"] + item["plan"]]
    shown += agenda["initiative"]
    assert all(set(o) == set(api.AgendaOption.__annotations__) for o in shown)
    moves = [m for o in shown for m in o["expects"]]
    assert {m["on"] for m in moves} == {"regard", "stance", "stake", "figure"}
    assert all(set(m) == set(api.AgendaExpect.__annotations__) for m in moves)
    assert all(set(o["risks"]) == set(api.AgendaRisks.__annotations__) for o in shown)


def test_the_seats_stored_offer_replays_with_its_moves() -> None:
    sl, state = _world()
    made = _offer(sl, state, {"expects": [_move("stake", OPEN)]})
    store = MemoryStore()
    store.append_all(sl.events)
    rt._append(store, load_state(store, CAMPAIGN), made, sl.fdr, private_to(sl.fdr))
    (stored,) = [
        e.payload for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.OptionsOffered)
    ]
    assert stored == made and stored.offers[0].options[0].expects[0].target == OPEN
