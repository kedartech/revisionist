"""Play styles and the option generator (unit B3): offers, the aide, band E and band F.

The recording is hand-written, not a model reply: ``python -m tests.test_engine_v2_options``
rebuilds it. No test here calls a model.
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.canary import scan
from revisionist.core.ids import FactId, SeatId, derived_id
from revisionist.core.ontology import Controller, Fact
from revisionist.core.project import project
from revisionist.core.realism import effect as rx
from revisionist.core.realism.agenda import Ask, PlayStyle
from revisionist.core.realism.route import route
from revisionist.core.sealing import needs_admin_read
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import options
from revisionist.engine import realism_tick as rt
from revisionist.engine.llm import RecordedTransport, Reply, Request, Transport
from revisionist.engine.store import MemoryStore, load_state
from tests.test_engine_v2_contract import CAMPAIGN, REASON_CANARY, Slice, _with_covert_fact

RECORDINGS = Path(__file__).parent / "recordings"
NOTE = "hand-written for tests; not a model reply"
OTHER_CANARY = "CANARY-V2-OPTIONS-2b9c"
TODAY = date(1941, 9, 11)
STYLES = (PlayStyle.BEGINNER, PlayStyle.GUIDED)


def _scenario(style: PlayStyle | None, canary: bool = False) -> Slice:
    """Roosevelt with one live mandate and a style. ``canary`` plants secrets, and a
    public fact so its requests key apart from the plain scenario's."""
    sl = Slice()
    if canary:
        _with_covert_fact(sl)
        secret = Fact(
            fact_id=FactId(derived_id(CAMPAIGN, "fact", "wheeler-private")),
            subject=sl.entity("wheeler"),
            predicate="fears",
            obj=sl.entity("germany"),
            scope=private_to(sl.wheeler),
            canary=OTHER_CANARY,
        )
        sl.add(ev.FactAsserted(fact=secret), secret.scope)
        marker = Fact(
            fact_id=FactId(derived_id(CAMPAIGN, "fact", "marker")),
            subject=sl.entity("usa"),
            predicate="at_peace_with",
            obj=sl.entity("germany"),
            scope=PUBLIC,
        )
        sl.add(ev.FactAsserted(fact=marker), marker.scope)
    sl.add(ev.MandateIssued(mandate=sl.mandate(1, sl.fdr)), private_to(sl.fdr))
    if style is not None:
        sl.add(ev.PlayStyleSet(seat_id=sl.fdr, style=style), private_to(sl.fdr))
    return sl


# --- hand replies ----------------------------------------------------------------


def _ask(text: str, **fields: Any) -> dict[str, Any]:
    return {"ask": text, **fields}


def _option(label: str, asks: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    return {"label": label, "asks": asks, "risk": "It may go badly.", **fields}


def _parts(sl: Slice) -> dict[str, dict[str, Any]]:
    fleet = sl.feature("us_atlantic_fleet")
    stark, rayburn = sl.entity("stark"), sl.entity("rayburn")
    patrol = _ask("Patrol", effect={"kind": "move_force", "force": fleet, "posture": "patrol"})
    escort = _ask(
        "Escort",
        effect={"kind": "engagement", "force": fleet, "zone": "convoy lanes", "rule": "escort"},
    )
    word = _ask("Speak to the nation", effect={"kind": "statement", "theme": "convoys"})
    press = _ask("Ask Rayburn to hold the House", target=rayburn)
    return {
        "patrol": _option("Patrol the sea lanes", [patrol], to=stark, historical=True),
        "escort": _option("Escort the convoys", [escort], to=stark),
        "word": _option("Speak to the nation", [word]),
        "press": _option("Press Rayburn", [press], to=rayburn),
        # names a person the view does not hold
        "ghost": _option("Press a stranger", [_ask("Ask them", target="no-such-person")]),
        # a transfer the office has no domain for, and no target to persuade
        "unroutable": _option(
            "Hand over oil",
            [
                _ask(
                    "Ship oil",
                    effect={
                        "kind": "allocate",
                        "recipient": rayburn,
                        "what": "oil",
                        "amount": 5,
                        "unit": "tons",
                    },
                )
            ],
        ),
    }


def _replies(sl: Slice, canary: bool) -> dict[tuple[str, bool], dict[str, Any]]:
    """Reply by (style in the prompt, mandate in the prompt)."""
    p = _parts(sl)
    ask_word = p["word"]["asks"][0]

    def plan(*parts: dict[str, Any]) -> dict[str, Any]:
        return _option("A plan", [x for o in parts for x in o["asks"]])

    if not canary:
        return {
            ("beginner", True): {
                "options": [p["patrol"], p["ghost"], p["word"], p["unroutable"], p["press"]]
            },
            # only two survive: the template fills in
            ("beginner", False): {"options": [p["patrol"], p["ghost"], p["unroutable"], p["word"]]},
            ("guided", True): {"options": [plan(p["patrol"], p["escort"], p["word"], p["press"])]},
            ("guided", False): {"options": [plan(p["patrol"], p["word"], p["unroutable"])]},
        }
    leaky_label = _option(f"Quiet word about {REASON_CANARY}", [ask_word])
    leaky_risk = _option("Speak out", [ask_word], risk=f"They know of {REASON_CANARY}.")
    leaky_ask = _option("Another word", [_ask(f"Say {OTHER_CANARY}", effect=ask_word["effect"])])
    base = [p["patrol"], leaky_label, p["escort"], leaky_risk, leaky_ask, p["word"]]
    return {
        ("beginner", True): {"options": base},
        ("beginner", False): {"options": base},
        ("guided", True): {
            "options": [_option(f"A plan ({REASON_CANARY})", p["word"]["asks"] * 3)]
        },
        ("guided", False): {"options": [plan(p["patrol"], p["escort"], p["word"], p["press"])]},
    }


class _Script:
    """Answers each request from the table, and keeps what it was asked."""

    def __init__(self, table: dict[tuple[str, bool], dict[str, Any]]) -> None:
        self.table, self.requests = table, []  # type: ignore[var-annotated]

    def call(self, request: Request) -> Reply:
        self.requests.append(request)
        style = "guided" if '"style":"guided"' in request.prompt else "beginner"
        return Reply(
            self.table[(style, '"mandate":null' not in request.prompt)], "hand", 0, 0, 0, 0.0
        )


def _write() -> None:
    entries: dict[str, dict[str, Any]] = {}
    for canary in (False, True):
        for style in STYLES:
            sl = _scenario(style, canary)
            script = _Script(_replies(sl, canary))
            options.offer(sl.state, sl.fdr, script)
            for request in script.requests:
                key = (
                    "guided" if '"style":"guided"' in request.prompt else "beginner",
                    '"mandate":null' not in request.prompt,
                )
                entries[request.key()] = {
                    "call_class": options.CALL_CLASS,
                    "model": options.OPTIONS_MODEL,
                    "prompt_head": request.prompt[:120],
                    "hand_written": True,
                    "note": f"{NOTE} ({'canary' if canary else 'plain'} {key})",
                    "reply": Reply(script.table[key], "hand", 0, 0, 0, 0.0).__dict__,
                }
    (RECORDINGS / options.RECORDING).write_text(
        json.dumps(entries, indent=1, sort_keys=True) + "\n"
    )


@pytest.fixture
def recorded() -> RecordedTransport:
    return RecordedTransport(RECORDINGS / options.RECORDING)


def _routes(state: State, seat: SeatId, asks: tuple[Ask, ...]) -> bool:
    return all(route(state, seat, a, TODAY).part is not None for a in asks)


# --- set_style --------------------------------------------------------------------


def test_set_style_lands_sealed_to_the_seat() -> None:
    store = MemoryStore()
    sl = Slice()
    store.append_all(sl.events)
    options.set_style(
        store, CAMPAIGN, sl.fdr, PlayStyle.GUIDED, frozenset({rx.EffectKind.ALLOCATE})
    )
    landed = list(store.read(CAMPAIGN))[-1]
    assert isinstance(landed.payload, ev.PlayStyleSet) and landed.scope == private_to(sl.fdr)
    assert needs_admin_read(landed)
    state = load_state(store, CAMPAIGN)
    assert state.styles[sl.fdr] is PlayStyle.GUIDED
    assert project(state, sl.fdr).style is PlayStyle.GUIDED
    assert project(state, sl.wheeler).style is None
    assert "guided" not in project(state, sl.wheeler).model_dump_json()
    with pytest.raises(ValueError, match="irreversible"):
        options.set_style(
            store, CAMPAIGN, sl.fdr, PlayStyle.GUIDED, frozenset({rx.EffectKind.DEAL})
        )


# --- offer ------------------------------------------------------------------------


def test_beginner_offers_three_or_four_options_that_route(recorded: RecordedTransport) -> None:
    sl = _scenario(PlayStyle.BEGINNER)
    got = options.offer(sl.state, sl.fdr, recorded)
    assert got is not None
    assert [o.mandate_id for o in got.offers] == [sl.mandate(1, sl.fdr).mandate_id, None]
    for offer in got.offers:
        assert 3 <= len(offer.options) <= 4 and sum(o.historical for o in offer.options) <= 1
        assert any(o.risk for o in offer.options)
        for option in offer.options:
            assert _routes(sl.state, sl.fdr, option.asks)
    sl.add(got, private_to(sl.fdr))
    assert sl.state.routed == {}


def test_the_bad_recorded_options_are_dropped(recorded: RecordedTransport) -> None:
    sl = _scenario(PlayStyle.BEGINNER)
    offered = options.offer(sl.state, sl.fdr, recorded)
    assert offered is not None
    mandated, initiative = offered.offers
    labels = {o.label for o in mandated.options}
    assert labels == {"Patrol the sea lanes", "Speak to the nation", "Press Rayburn"}
    # two survived on the initiative reply: the template stands in
    assert {o.label for o in initiative.options} == {
        o.label
        for o in options.template_options(project(sl.state, sl.fdr), None, PlayStyle.BEGINNER)
    }
    assert options.last_cost is not None


def test_guided_offers_one_plan_of_three_to_five(recorded: RecordedTransport) -> None:
    sl = _scenario(PlayStyle.GUIDED)
    offered = options.offer(sl.state, sl.fdr, recorded)
    assert offered is not None
    mandated, initiative = offered.offers
    for offer in (mandated, initiative):
        (plan,) = offer.options
        assert 3 <= len(plan.asks) <= 5 and _routes(sl.state, sl.fdr, plan.asks)
    assert len(mandated.options[0].asks) == 4
    # the initiative plan held an unroutable ask: the template plan stands in
    assert len(initiative.options[0].asks) == 5


def test_free_and_ai_seats_are_offered_nothing(recorded: RecordedTransport) -> None:
    free, styled = _scenario(None), _scenario(PlayStyle.BEGINNER)
    assert options.offer(free.state, free.fdr, recorded) is None
    seat = styled.state.seats[styled.fdr]
    ai = styled.state.model_copy(
        update={"seats": {styled.fdr: seat.model_copy(update={"controller": Controller.AI})}}
    )
    assert options.offer(ai, styled.fdr, recorded) is None


def test_the_template_path_needs_no_model_and_is_deterministic() -> None:
    a, b = _scenario(PlayStyle.BEGINNER), _scenario(PlayStyle.GUIDED)
    first = options.offer(a.state, a.fdr, None)
    again = options.offer(_scenario(PlayStyle.BEGINNER).state, a.fdr, None)
    assert first is not None and first == again and options.last_cost is None
    assert all(3 <= len(o.options) <= 4 for o in first.offers)
    plan = options.offer(b.state, b.fdr, None)
    assert plan is not None and all(len(o.options) == 1 for o in plan.offers)
    assert all(_routes(a.state, a.fdr, x.asks) for o in first.offers for x in o.options)
    kinds = [
        x.asks[0].effect.kind if x.asks[0].effect else "influence" for x in first.offers[0].options
    ]
    assert kinds[:3] == ["move_force", "engagement", "statement"]


def test_the_prompt_holds_only_the_seats_view() -> None:
    sl = _scenario(PlayStyle.BEGINNER, canary=True)
    view = project(sl.state, sl.fdr)
    prompt = options.options_prompt(
        view, sl.state.mandates[sl.mandate(1, sl.fdr).mandate_id], PlayStyle.BEGINNER
    )
    assert sl.feature("us_atlantic_fleet") in prompt and "Keep the convoys moving." in prompt
    assert REASON_CANARY not in prompt and OTHER_CANARY not in prompt
    assert options.OPTIONS_SCHEMA["properties"]["options"] and "additionalProperties" in json.dumps(
        options.OPTIONS_SCHEMA
    )


# --- band E -----------------------------------------------------------------------


def _store(style: PlayStyle | None) -> tuple[MemoryStore, SeatId]:
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path("engine-v2-slice-1941"))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    sl = Slice()
    entity = sl.entity("roosevelt")
    rt.seat_player(store, CAMPAIGN, entity)
    state = load_state(store, CAMPAIGN)
    (seat,) = [s.seat_id for s in state.seats.values() if s.embodies == entity]
    if style is not None:
        options.set_style(store, CAMPAIGN, seat, style)
    return store, seat


def _normalised(store: MemoryStore) -> list[str]:
    """The log from the first order on, minus the style records, order ids by index."""
    events = list(store.read(CAMPAIGN))
    start = next(i for i, e in enumerate(events) if isinstance(e.payload, ev.OrderRouted))
    kept = [
        e.payload
        for e in events[start:]
        if not isinstance(e.payload, ev.PlayStyleSet | ev.OptionsOffered)
    ]
    text = "\n".join(p.model_dump_json() for p in kept)
    for n, oid in enumerate(dict.fromkeys(o for p in kept for o in _order_ids(p))):
        text = text.replace(oid, f"ORDER{n}")
    # the state hash covers the style and the order ids, which the comparison sets aside;
    # a report's id is derived from its order's id, so it is set aside with it
    text = re.sub(r'"doc_id":"[0-9A-Z]{26}"', '"doc_id":"-"', text)
    return re.sub(r'"state_hash":"[0-9a-f]+"', '"state_hash":"-"', text).split("\n")


def _order_ids(p: ev.Payload) -> list[str]:
    if isinstance(p, ev.OrderRouted):
        return [p.order.order_id]
    found = getattr(p, "order_id", None)
    return [found] if found else []


def test_band_e_equivalence() -> None:
    logs: list[list[str]] = []
    first_asks: tuple[Ask, ...] = ()
    for style in (PlayStyle.BEGINNER, None, PlayStyle.GUIDED):
        store, seat = _store(style)
        state = load_state(store, CAMPAIGN)
        if style is PlayStyle.BEGINNER:
            offered = options.offer(state, seat, None)
            assert offered is not None
            rt._append(store, state, offered, seat, private_to(seat))
            first_asks = offered.offers[-1].options[0].asks
            asks = first_asks
        elif style is None:
            asks = first_asks
        else:
            offered = options.offer(state, seat, None)
            assert offered is not None
            plan = offered.offers[-1].options[0]
            assert first_asks[0] in plan.asks
            asks = (first_asks[0],)
        rt.commit_order(store, CAMPAIGN, seat, asks)
        rt.run_realism_tick(store, CAMPAIGN)
        logs.append(_normalised(store))
    assert logs[0] == logs[1] == logs[2]
    assert any("order_executed" in row for row in logs[0])


# --- band F -----------------------------------------------------------------------


def test_band_f_fog(recorded: RecordedTransport) -> None:
    for _ in range(3):
        for style in (*STYLES, None):
            sl = _scenario(style, canary=True)
            state = sl.state
            got = options.offer(state, sl.fdr, recorded)
            if style is None:
                assert got is None
            else:
                assert got is not None
                text = got.model_dump_json()
                assert REASON_CANARY not in text and OTHER_CANARY not in text
                assert all(
                    o.label and "CANARY" not in o.label + o.risk
                    for of in got.offers
                    for o in of.options
                )
                sl.add(got, private_to(sl.fdr))
            for order in options.aide_asks(state, sl.fdr, recorded):
                assert "CANARY" not in json.dumps([a.model_dump(mode="json") for a in order])
            assert scan(sl.state, sl.events) == []
    # the reply really did carry the canary: nothing was dropped by accident
    assert any(REASON_CANARY in json.dumps(e["reply"]) for e in recorded.entries.values())


# --- the aide ---------------------------------------------------------------------


def _with_appointment_reply(sl: Slice) -> Transport:
    appoint = _option(
        "Dismiss Stark",
        [
            _ask(
                "Replace Stark",
                effect={
                    "kind": "appointment",
                    "person": sl.entity("stark"),
                    "office": "CNO",
                    "appoint": False,
                },
            ),
            _ask("Speak", effect={"kind": "statement", "theme": "convoys"}),
        ],
    )
    return _Script(
        {(s, m): {"options": [appoint] * 4} for s in ("beginner", "guided") for m in (True, False)}
    )


def test_the_aide_drops_an_irreversible_ask_without_a_standing_order() -> None:
    sl = _scenario(PlayStyle.BEGINNER)
    state = sl.state
    card = state.cards[sl.entity("roosevelt")]
    word = next(d for d in card.authority if d.name == "public_word")
    widened = word.model_copy(update={"effects": word.effects | {rx.EffectKind.APPOINTMENT}})
    authority = tuple(widened if d.name == "public_word" else d for d in card.authority)
    cards = {**state.cards, card.person: card.model_copy(update={"authority": authority})}
    script = _with_appointment_reply(sl)
    for standing, kept in ((frozenset(), 1), (frozenset({rx.EffectKind.APPOINTMENT}), 2)):
        s = state.model_copy(
            update={"cards": cards, "standing": {sl.fdr: standing}},
        )
        orders = options.aide_asks(s, sl.fdr, script)
        assert len(orders) == 1 and len(orders[0]) == kept
        first = orders[0][0].effect
        assert first is not None
        assert (first.kind == "appointment") == (kept == 2)
        assert orders == options.aide_asks(s, sl.fdr, script)


def test_the_aide_files_nothing_without_a_mandate() -> None:
    sl = Slice()
    sl.add(ev.PlayStyleSet(seat_id=sl.fdr, style=PlayStyle.BEGINNER), private_to(sl.fdr))
    assert options.aide_asks(sl.state, sl.fdr, None) == []


def test_the_aide_files_the_first_option_of_each_mandate_at_most_three() -> None:
    sl = _scenario(None)
    state = sl.state
    orders = options.aide_asks(state, sl.fdr, None)
    assert len(orders) == 1 and len(orders[0]) == 1
    assert _routes(state, sl.fdr, orders[0])
    assert orders == options.aide_asks(state, sl.fdr, None)


if __name__ == "__main__":
    _write()
