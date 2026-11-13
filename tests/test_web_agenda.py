"""The agenda on the web (Phase 4 unit S2): mandates, options, plans, picking, the style."""

import re
from datetime import date
from typing import Any

from revisionist.core import events as ev
from revisionist.core import history
from revisionist.core.ids import SeatId
from revisionist.core.project import project
from revisionist.core.realism import mandates, press
from revisionist.core.realism.agenda import PlayStyle
from revisionist.core.realism.document import DocumentKind
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


GREER_DAY = date(1941, 9, 4)
GREER = "USS Greer and U-652 exchange fire south of Iceland"
GREER_CRISIS = "After the Greer, set the Navy's rules in the western Atlantic."


def _greer(printed: bool, wheeler_only: bool = False) -> tuple[Slice, MemoryStore]:
    """The slice on the Greer's day: the event fires and is news, its crisis reaches
    Roosevelt beside a crisis no template issued. ``printed``: the press pages of that
    news are issued to their readers, or with ``wheeler_only`` to Wheeler alone."""
    sl = Slice()
    sl.add(ev.DateAdvanced(to=GREER_DAY))
    sl.add(ev.MandateIssued(mandate=sl.mandate(1, sl.fdr, issued=GREER_DAY)), private_to(sl.fdr))
    settled = history.settle(sl.state, GREER_DAY)
    for fired in settled:
        sl.add(fired)
    for reported in history.news(sl.state, settled, GREER_DAY):
        sl.add(reported)
    for page in press.news_pages(sl.state, GREER_DAY) if printed else []:
        if wheeler_only:
            scope = private_to(sl.wheeler)
            page = page.model_copy(
                update={"document": page.document.model_copy(update={"scope": scope})}
            )
        sl.add(page, page.document.scope)
    for issued in mandates.issue_due(sl.state, GREER_DAY):
        assert isinstance(issued, ev.MandateIssued)
        sl.add(issued, issued.mandate.scope)
    store = MemoryStore()
    store.append_all(sl.events)
    return sl, store


def _causes(store: MemoryStore, seat: SeatId) -> dict[str, str | None]:
    return {i["text"]: i["cause"] for i in _block(store, seat)["items"]}


def test_a_history_crisis_carries_the_headline_the_seat_read() -> None:
    sl, store = _greer(printed=True)
    assert _causes(store, sl.fdr) == {GREER_CRISIS: GREER, "Keep the convoys moving.": None}


def test_a_mandate_no_history_issued_has_no_cause() -> None:
    sl, store = _world(PlayStyle.BEGINNER)
    assert [i["cause"] for i in _block(store, sl.fdr)["items"]] == [None]


def test_no_cause_until_the_seat_holds_the_news() -> None:
    for sl, store in (_greer(printed=False), _greer(printed=True, wheeler_only=True)):
        state = load_state(store, CAMPAIGN)
        assert [n.headline for n in state.news.values()] == [GREER]
        assert _causes(store, sl.fdr) == {GREER_CRISIS: None, "Keep the convoys moving.": None}
    assert any(d.kind is DocumentKind.PRESS for d in project(state, sl.wheeler).documents.values())


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
