"""The agenda on the web (Phase 4 unit S2): mandates, options, plans, picking, the style."""

import re
from typing import Any

from revisionist.core import events as ev
from revisionist.core.ids import SeatId
from revisionist.core.realism.agenda import PlayStyle
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine import options
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import agenda_api
from tests.test_engine_v2_contract import CAMPAIGN, Slice


def _world(style: PlayStyle | None, offered: bool = True) -> tuple[Slice, MemoryStore]:
    sl = Slice()
    sl.add(ev.MandateIssued(mandate=sl.mandate(1, sl.fdr)), private_to(sl.fdr))
    sl.add(ev.MandateIssued(mandate=sl.mandate(2, sl.wheeler)), private_to(sl.wheeler))
    if style is not None:
        sl.add(ev.PlayStyleSet(seat_id=sl.fdr, style=style), private_to(sl.fdr))
    if offered and (made := options.offer(sl.state, sl.fdr, None)) is not None:
        sl.add(made, private_to(sl.fdr))
    store = MemoryStore()
    store.append_all(sl.events)
    return sl, store


def _block(store: MemoryStore, seat: SeatId) -> Any:
    state = load_state(store, CAMPAIGN)
    return agenda_api.agenda(state, seat, list(store.read(CAMPAIGN)))


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def test_a_beginner_sees_options_on_its_mandate() -> None:
    sl, store = _world(PlayStyle.BEGINNER)
    block = _block(store, sl.fdr)
    assert block["style"] == "beginner"
    (item,) = block["items"]
    assert item["kind"] == "Crisis" and item["issuer"] is None
    assert item["issued"] == "11 September 1941" and item["deadline"] == "11 October 1941"
    assert 3 <= len(item["options"]) <= 4 and item["plan"] == []


def test_a_guided_seat_sees_a_plan() -> None:
    sl, store = _world(PlayStyle.GUIDED)
    (item,) = _block(store, sl.fdr)["items"]
    assert item["options"] == [] and 3 <= len(item["plan"]) <= 5
    assert len({step["pick"] for step in item["plan"]}) == 1


def test_a_free_seat_sees_nothing_offered() -> None:
    sl, store = _world(None)
    block = _block(store, sl.fdr)
    (item,) = block["items"]
    assert block["style"] == "free" and block["initiative"] == []
    assert item["options"] == [] and item["plan"] == []


def test_initiative_holds_the_offer_without_a_mandate() -> None:
    sl, store = _world(PlayStyle.BEGINNER)
    assert 3 <= len(_block(store, sl.fdr)["initiative"]) <= 4


def test_picking_files_a_routed_order() -> None:
    sl, store = _world(PlayStyle.BEGINNER)
    (item,) = _block(store, sl.fdr)["items"]
    chosen = item["options"][0]
    done = agenda_api.pick_option(store, CAMPAIGN, sl.fdr, chosen["pick"])
    assert done == {"reply": f"Filed: {chosen['label']}.", "refused": False}
    state: State = load_state(store, CAMPAIGN)
    assert [o.issuer for o in state.routed.values()] == [sl.fdr]


def test_picking_a_plan_files_all_its_steps_as_one_order() -> None:
    sl, store = _world(PlayStyle.GUIDED)
    (item,) = _block(store, sl.fdr)["items"]
    done = agenda_api.pick_option(store, CAMPAIGN, sl.fdr, item["plan"][0]["pick"])
    assert not done["refused"]
    (order,) = load_state(store, CAMPAIGN).routed.values()
    assert len(order.parts) == len(item["plan"])


def test_a_stale_or_unknown_pick_is_refused() -> None:
    sl, store = _world(PlayStyle.BEGINNER)
    (item,) = _block(store, sl.fdr)["items"]
    token: str = item["options"][0]["pick"]
    for bad in ("", "nonsense", token.replace("w", "w9", 1), re.sub(r"p\d+$", "p9", token)):
        assert agenda_api.pick_option(store, CAMPAIGN, sl.fdr, bad)["refused"]
    assert not load_state(store, CAMPAIGN).routed
    _, bare = _world(PlayStyle.BEGINNER, offered=False)
    assert agenda_api.pick_option(bare, CAMPAIGN, sl.fdr, token)["refused"]


def test_another_seats_mandate_never_appears() -> None:
    sl, store = _world(PlayStyle.BEGINNER)
    other = sl.mandate(2, sl.wheeler)
    assert all(i["id"] != other.mandate_id for i in _block(store, sl.fdr)["items"])
    assert [i["id"] for i in _block(store, sl.wheeler)["items"]] == [other.mandate_id]
    assert _block(store, sl.wheeler)["style"] == "free"


def test_set_style_parses_and_refuses() -> None:
    sl, store = _world(None, offered=False)
    done = agenda_api.set_style(store, CAMPAIGN, sl.fdr, "beginner")
    assert done == {"reply": "You will be offered options each wake.", "refused": False}
    assert agenda_api.seat_style(load_state(store, CAMPAIGN), sl.fdr) == "beginner"
    assert agenda_api.set_style(store, CAMPAIGN, sl.fdr, "reckless")["refused"]
    assert agenda_api.seat_style(load_state(store, CAMPAIGN), sl.fdr) == "beginner"


def test_no_player_facing_string_holds_an_underscore() -> None:
    for style in (PlayStyle.BEGINNER, PlayStyle.GUIDED):
        sl, store = _world(style)
        block = _block(store, sl.fdr)
        ids = {i["id"] for i in block["items"]}
        for line in _strings(block):
            assert line in ids or "_" not in line, line
        for reply in (
            agenda_api.pick_option(store, CAMPAIGN, sl.fdr, "bad"),
            agenda_api.set_style(store, CAMPAIGN, sl.fdr, "bad_style"),
        ):
            assert "_" not in reply["reply"]
