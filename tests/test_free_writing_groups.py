"""Free writing moves groups, within a cap (FWG).

The toy world (``tests/worlds/territory-toy.yaml``) with ``groups`` on, as GRP's tests
play it, gives Norra a ``public_word`` office for Ilse and two themes. A statement or a
measure that names a theme takes the theme's table and calls no model; one that names
none is read, with ``writing`` on, by one call built from Ilse's own view and the words.
Every reply here is hand-written and canned: no test calls a model.
"""

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import OrderId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import effect as rx
from revisionist.core.realism import groups
from revisionist.core.realism.effect import GroupNudge
from revisionist.core.world import WorldFile
from revisionist.engine import campaign as cmp
from revisionist.engine import estimate as es
from revisionist.engine import realism_tick
from revisionist.engine.emit import Emitter
from revisionist.engine.llm import Reply, Request, TransportError, prompt_text
from revisionist.engine.store import MemoryStore
from tests.test_adjacency_moves import START, Logged, entity, seat, toy
from tests.test_territory_model import refused

World = dict[str, Any]
NORRA, SUDLAND = entity("norra"), entity("sudland")
ILSE, TOMAS = seat("ilse"), seat("tomas")

THEMES = [
    {"key": "bread", "name": "Bread for All", "moves": {"public": 2, "smiths": -1}},
    {"key": "levy", "name": "The Levy Act", "moves": {"greens": 1}},
]


def _norra(w: World) -> dict[str, Any]:
    return next(d for d in w["groups"] if d["nation"] == "norra")


def ruled(*rules: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy", "groups", *rules]
        _norra(w)["themes"] = THEMES
        w["entities"].append(
            {"key": "karl", "kind": "person", "name": "Karl Rook", "parent": "norra"}
        )
        card = next(c for c in w["cards"] if c["person"] == "ilse")
        card["inner_circle"] = [{"person": "karl", "channel": "in_person"}]
        card["authority"] = [
            {"name": "public_word", "effects": ["statement", "measure"], "summary": "Speak."}
        ]

    return change


def abroad(w: World) -> None:
    sud = next(d for d in w["groups"] if d["nation"] == "sudland")
    sud["groups"][0]["abroad"] = True


def world(tmp: Path, *changes: Callable[[World], None], writing: bool = True) -> WorldFile:
    return toy(tmp, ruled(*(["writing"] if writing else [])), *changes)


def game(tmp: Path, *changes: Callable[[World], None], writing: bool = True) -> Logged:
    return Logged(world(tmp, *changes, writing=writing), "ilse", "tomas")


def said(theme: str) -> rx.MakeStatement:
    return rx.MakeStatement(theme=theme)


def filed(g: Logged, n: int, effect: rx.Effect | None, words: str, by: SeatId = ILSE) -> OrderId:
    """A routed order of one part: Ilse's own word, or free words with no typed effect."""
    part: dict[str, object] = {"route": rx.Route.COMMAND, "domain": "public_word", "ask": words}
    if effect is not None:
        part["effect"] = effect
    order = rx.RoutedOrder(
        order_id=OrderId(f"fwg-order-{n}"),
        issuer=by,
        filed=START,
        parts=(rx.RoutedPart.model_validate(part),),
    )
    g.add([ev.OrderRouted(order=order)])
    return order.order_id


class Canned:
    """A canned transport that counts every request by call class. ``reply`` gives the
    output for a request; raising ``TransportError`` stands in for a failure."""

    def __init__(self, reply: Callable[[Request], dict[str, Any]]) -> None:
        self.reply = reply
        self.requests: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.requests.append(request)
        return Reply(self.reply(request), "canned", 0, 0, 0, 0.0)

    def count(self, call_class: str) -> int:
        return sum(r.call_class == call_class for r in self.requests)


def nudging(*effects: dict[str, Any], reason: str = "The street took it well.") -> Canned:
    def reply(request: Request) -> dict[str, Any]:
        if request.call_class == es.GROUP_CALL_CLASS:
            return {"effects": list(effects), "reason": reason, "rationale": "canned"}
        return {"effects": [], "reason": "Done.", "rationale": "canned"}

    return Canned(reply)


def nudge(key: str, change: int, nation: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": "group", "group": key, "change": change}
    if nation is not None:
        out["nation"] = str(entity(nation))
    return out


def ruled_on(g: Logged, oid: OrderId, transport: Any) -> es.Estimate:
    return es.estimate(g.state, oid, 0, transport)


def stage(g: Logged, transport: Any) -> list[ev.Event]:
    """The tick's estimate stage on ``g``: the events it logs."""
    store = MemoryStore()
    store.append_all(g.log)
    em = Emitter(store, g.state, cmp.versions())
    realism_tick._estimate(em, transport)
    out = list(store.read(g.state.campaign_id))[len(g.log) :]
    g.log += out
    g.state = em.state
    return out


def estimated(events: Sequence[ev.Event]) -> list[ev.EffectsEstimated]:
    return [e.payload for e in events if isinstance(e.payload, ev.EffectsEstimated)]


# --- rule 1: one new kind, estimated only, held to the day cap ------------------------


def test_the_group_nudge_is_a_kind_only_a_ruling_gives() -> None:
    assert rx.EffectKind.GROUP in rx.ESTIMATED_ONLY
    GroupNudge(nation=NORRA, group="public", change=rx.GROUP_DAY_CAP)
    for change in (0, rx.GROUP_DAY_CAP + 1, -rx.GROUP_DAY_CAP - 1):
        with pytest.raises(ValidationError):
            GroupNudge(nation=NORRA, group="public", change=change)
    assert rx.GROUP_DAY_CAP == groups.GROUP_DAY_CAP


def test_no_office_may_order_a_group_nudge(tmp_path: Path) -> None:
    def office(w: World) -> None:
        card = next(c for c in w["cards"] if c["person"] == "ilse")
        card["authority"] = [{"name": "rally", "effects": ["group"]}]

    assert refused(world(tmp_path, office))


def test_a_ruling_past_the_day_cap_is_dropped_by_the_clamp(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = filed(g, 1, said("the harvest"), "To the people of Norra: hold fast.")
    got = ruled_on(g, oid, nudging(nudge("public", 5), nudge("greens", -4), nudge("greys", 3)))
    assert got.event.effects == (GroupNudge(nation=NORRA, group="greys", change=3),)
    assert sum("past the 3 cap" in d for d in got.dropped) == 2


# --- rule 2: another nation's group only where it hears abroad, by at most 1 ----------


def test_a_foreign_group_not_marked_is_never_moved(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = filed(g, 1, said("the harvest"), "Farmers of Sudland, lay down your tools.")
    got = ruled_on(g, oid, nudging(nudge("farmers", -1, "sudland")))
    assert got.event.effects == ()
    assert any("does not hear writing from abroad" in d for d in got.dropped)


def test_a_foreign_group_marked_abroad_moves_by_one_at_most(tmp_path: Path) -> None:
    g = game(tmp_path, abroad)
    oid = filed(g, 1, said("the harvest"), "Farmers of Sudland, lay down your tools.")
    got = ruled_on(g, oid, nudging(nudge("farmers", -2, "sudland")))
    assert got.event.effects == ()
    got = ruled_on(g, oid, nudging(nudge("farmers", -1, "sudland")))
    assert got.event.effects == (GroupNudge(nation=SUDLAND, group="farmers", change=-1),)


# --- rule 3: a world's themes, by nation -----------------------------------------------


def test_a_world_lists_each_nations_themes_and_a_seat_sees_its_own(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert [t.key for t in g.state.groups.themes[NORRA]] == ["bread", "levy"]
    assert g.state.groups.themes[NORRA][0].moves == {"public": 2, "smiths": -1}
    assert NORRA in project(g.state, ILSE).groups.themes
    assert project(g.state, TOMAS).groups.themes == {}


def test_a_theme_moves_only_its_own_nations_groups_by_the_cap(tmp_path: Path) -> None:
    def foreign(w: World) -> None:
        _norra(w)["themes"] = [{"key": "x", "name": "X", "moves": {"farmers": 1}}]

    assert any("farmers is not a group" in p for p in refused(world(tmp_path, foreign)))

    def twice(w: World) -> None:
        _norra(w)["themes"] = [THEMES[0], THEMES[0]]

    assert any("theme key is given twice" in p for p in refused(world(tmp_path, twice)))
    with pytest.raises(ValidationError):
        groups.Theme(key="x", name="X", moves={"public": groups.GROUP_DAY_CAP + 1})


def test_a_world_without_themes_has_none(tmp_path: Path) -> None:
    def none(w: World) -> None:
        _norra(w).pop("themes")

    assert game(tmp_path, none).state.groups.themes == {}


# --- rule 4: a theme named uses the table and calls no model ---------------------------


def test_a_statement_naming_a_theme_takes_its_table_and_calls_no_model(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = filed(g, 1, said("bread for all"), "We will see every table set.")
    canned = nudging(nudge("public", -3))
    got = ruled_on(g, oid, canned)
    assert canned.requests == []
    assert got.event.effects == (
        GroupNudge(nation=NORRA, group="public", change=2),
        GroupNudge(nation=NORRA, group="smiths", change=-1),
    )
    assert got.event.reason == es.GROUPS_HEARD


def test_a_theme_named_in_the_words_counts_as_named(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = filed(g, 1, said("the harvest"), "And so, Bread for all: the mills run tonight.")
    canned = nudging(nudge("public", -3))
    assert ruled_on(g, oid, canned).event.effects[0].change == 2  # type: ignore[union-attr]
    assert canned.requests == []


def test_a_measure_whose_title_is_a_theme_takes_its_table(tmp_path: Path) -> None:
    g = game(tmp_path)
    act = rx.ProposeMeasure(
        title="The Levy Act", clauses=(rx.Clause(kind=rx.ClauseKind.POWER, subject="levy"),)
    )
    canned = nudging(nudge("public", 1))
    got = ruled_on(g, filed(g, 1, act, ""), canned)
    assert got.event.effects == (GroupNudge(nation=NORRA, group="greens", change=1),)
    assert canned.requests == []


# --- rule 5: only a text with no theme is read, once, and only with `writing` on -------


def test_a_text_with_no_theme_is_read_by_one_call(tmp_path: Path) -> None:
    g = game(tmp_path)
    filed(g, 1, said("the harvest"), "The mills will run all winter.")
    filed(g, 2, said("the frontier"), "No step back on the frontier.")
    canned = nudging(nudge("public", 1))
    out = stage(g, canned)
    assert canned.count(es.GROUP_CALL_CLASS) == 2 and len(canned.requests) == 2
    assert [e.effects for e in estimated(out)] == [
        (GroupNudge(nation=NORRA, group="public", change=1),)
    ] * 2
    assert stage(g, canned) == [] and len(canned.requests) == 2
    costs = [e.payload for e in out if isinstance(e.payload, ev.CostLogged)]
    assert [c.purpose for c in costs] == [es.GROUP_CALL_CLASS] * 2


def test_with_writing_off_a_text_with_no_theme_moves_nothing_and_says_so(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, writing=False)
    oid = filed(g, 1, said("the harvest"), "The mills will run all winter.")
    canned = nudging(nudge("public", 1))
    got = ruled_on(g, oid, canned)
    assert canned.requests == []
    assert got.event.effects == () and got.event.reason == es.GROUPS_UNHEARD


def test_a_measure_with_no_theme_moves_nothing_and_says_so(tmp_path: Path) -> None:
    g = game(tmp_path)
    act = rx.ProposeMeasure(
        title="The Canal Bill", clauses=(rx.Clause(kind=rx.ClauseKind.LIMIT, subject="canal"),)
    )
    canned = nudging(nudge("public", 1))
    got = ruled_on(g, filed(g, 1, act, ""), canned)
    assert canned.requests == [] and got.event.effects == ()
    assert got.event.reason == es.GROUPS_UNHEARD


def test_with_groups_off_a_statement_is_not_read_at_all(tmp_path: Path) -> None:
    def off(w: World) -> None:
        w["rules"] = ["territories", "holders", "economy", "writing"]

    g = game(tmp_path, off)
    filed(g, 1, said("the harvest"), "The mills will run all winter.")
    canned = nudging(nudge("public", 1))
    assert stage(g, canned) == [] and canned.requests == []


# --- the ruling is kept: a replay calls no model --------------------------------------


def test_a_replay_of_the_log_holds_the_ruling_and_calls_nothing(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = filed(g, 1, said("the harvest"), "The mills will run all winter.")
    stage(g, nudging(nudge("public", 1), nudge("greens", -2)))
    again = replay(g.log)
    part = again.routed[oid].parts[0]
    assert part.was_estimated
    assert part.estimated == (
        GroupNudge(nation=NORRA, group="public", change=1),
        GroupNudge(nation=NORRA, group="greens", change=-2),
    )
    assert again.model_dump_json() == g.state.model_dump_json()


# --- rule 6: the request is the issuer's view and the words; twin worlds ---------------


def far_roads(at: str) -> Callable[[World], None]:
    """Sudland's galleys at ``at``: a place Norra's seats have no report of."""

    def change(w: World) -> None:
        w["entities"].append(
            {
                "key": "far_roads",
                "kind": "location",
                "name": "The Far Roads",
                "at": [180, 215],
                "within": "open_sea",
            }
        )
        galleys = next(f for f in w["features"] if f["key"] == "sudland_galleys")
        galleys["places"] = [at]

    return change


def adversarial() -> Canned:
    """Asks the groups to react to where the enemy galleys stand, and answers by whatever
    the request lets it learn of them."""
    near = (str(entity("gulf_roads")), "Gulf Roads")

    def reply(request: Request) -> dict[str, Any]:
        seen = any(n in request.prompt for n in near)
        change = 3 if seen else -1
        reason = "The galleys at the Gulf Roads alarm them." if seen else "They are uneasy."
        if request.call_class == es.GROUP_CALL_CLASS:
            return {"effects": [nudge("public", change)], "reason": reason, "rationale": "x"}
        return {"effects": [], "reason": "Noted.", "rationale": "x"}

    return Canned(reply)


def _twin(tmp: Path, at: str) -> tuple[Logged, Canned, list[ev.Event]]:
    tmp.mkdir()
    g = game(tmp, far_roads(at))
    filed(g, 1, said("the enemy fleet"), "Tell the public where the Sudland galleys lie now.")
    filed(g, 2, None, "Let the public know how near the enemy galleys have come.")
    canned = adversarial()
    return g, canned, stage(g, canned)


def _mine(events: Sequence[ev.Event], who: SeatId) -> list[str]:
    return [
        json.dumps([e.payload.model_dump(mode="json"), e.scope.model_dump(mode="json")])
        for e in events
        if e.scope.visible_to(who) and not isinstance(e.payload, ev.CostLogged)
    ]


def test_twin_worlds_differing_in_a_hidden_piece_send_and_give_the_same(
    tmp_path: Path,
) -> None:
    near, near_canned, near_out = _twin(tmp_path / "near", "gulf_roads")
    far, far_canned, far_out = _twin(tmp_path / "far", "far_roads")
    assert near.state.features != far.state.features
    groups_near = [r for r in near_canned.requests if r.call_class == es.GROUP_CALL_CLASS]
    groups_far = [r for r in far_canned.requests if r.call_class == es.GROUP_CALL_CLASS]
    assert len(groups_near) == 1
    assert [(r.system, r.prompt, r.schema) for r in groups_near] == [
        (r.system, r.prompt, r.schema) for r in groups_far
    ]
    near_groups = [[x for x in e.effects if isinstance(x, GroupNudge)] for e in estimated(near_out)]
    far_groups = [[x for x in e.effects if isinstance(x, GroupNudge)] for e in estimated(far_out)]
    assert near_groups == far_groups == [[GroupNudge(nation=NORRA, group="public", change=-1)], []]
    statement_near, statement_far = estimated(near_out)[0], estimated(far_out)[0]
    assert statement_near == statement_far
    assert _mine(near_out[:2], ILSE) == _mine(far_out[:2], ILSE)
    for who in (ILSE, TOMAS):
        assert (
            project(near.state, who).model_dump_json() == project(far.state, who).model_dump_json()
        )


def test_the_group_request_holds_no_truth_the_issuer_cannot_see(tmp_path: Path) -> None:
    _, canned, _ = _twin(tmp_path / "near", "gulf_roads")
    for request in canned.requests:
        if request.call_class == es.GROUP_CALL_CLASS:
            assert str(entity("sudland_galleys")) not in request.prompt
            assert "Gulf Roads" not in request.prompt
            assert "Sudland Galleys" not in request.prompt


# --- rule 7: at most MAX_GROUP_EFFECTS nudges; an unknown group dropped -----------------


def test_a_ruling_holds_at_most_three_nudges_and_no_unknown_group(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = filed(g, 1, said("the harvest"), "To every guild, party and street of Norra.")
    got = ruled_on(
        g,
        oid,
        nudging(
            nudge("guilds", 1),
            nudge("public", 1),
            nudge("greens", 1),
            nudge("greys", -1),
            nudge("smiths", 2),
        ),
    )
    assert [(e.group, e.change) for e in got.event.effects] == [  # type: ignore[union-attr]
        ("public", 1),
        ("greens", 1),
        ("greys", -1),
    ]
    assert any("no group guilds" in d for d in got.dropped)
    assert any(f"over the {groups.MAX_GROUP_EFFECTS}-nudge cap" in d for d in got.dropped)


# --- rule 8: the groups prompt names the new kind and the issuer's own groups ------------


def test_the_groups_request_names_the_kind_and_the_issuers_own_groups(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = filed(g, 1, said("the harvest"), "The mills will run all winter.")
    canned = nudging()
    ruled_on(g, oid, canned)
    (request,) = canned.requests
    for name in ("The Smiths' Guild", "The Greens", "The Greys", "The Norra Public"):
        assert json.dumps(name)[1:-1] in request.prompt
    assert "The Farmers" not in request.prompt
    assert '"group"' in json.dumps(request.schema)
    assert "group" in prompt_text(es.GROUP_PROMPT)


# --- failures: counted, no retry, no fallback, no group moved ------------------------------


def _failing(exc: Exception) -> Canned:
    def reply(request: Request) -> dict[str, Any]:
        raise exc

    return Canned(reply)


@pytest.mark.parametrize(
    "failure",
    [TransportError("day quota exhausted until 00:00 UTC"), TransportError("model unreachable")],
)
def test_a_failed_call_moves_no_group_and_says_so(tmp_path: Path, failure: Exception) -> None:
    g = game(tmp_path)
    oid = filed(g, 1, said("the harvest"), "The mills will run all winter.")
    canned = _failing(failure)
    out = stage(g, canned)
    (ruling,) = estimated(out)
    assert ruling.effects == () and ruling.reason == es.GROUPS_FAILED and not ruling.failed
    assert len(canned.requests) == 1
    assert g.state.routed[oid].parts[0].was_estimated


def test_an_invalid_reply_moves_no_group_and_says_so(tmp_path: Path) -> None:
    g = game(tmp_path)
    oid = filed(g, 1, said("the harvest"), "The mills will run all winter.")
    canned = Canned(lambda request: {"effects": [{"kind": "votes"}], "reason": "x"})
    got = ruled_on(g, oid, canned)
    assert got.event.effects == () and got.event.reason == es.GROUPS_FAILED
    assert len(canned.requests) == 1


def test_words_with_no_typed_effect_stay_the_referees_alone(tmp_path: Path) -> None:
    g = game(tmp_path)
    filed(g, 1, None, "Let the bakers know the mills will run all winter.")
    canned = nudging(nudge("public", 1))
    (ruling,) = estimated(stage(g, canned))
    assert canned.count(es.CALL_CLASS) == 1 and canned.count(es.GROUP_CALL_CLASS) == 0
    assert ruling.effects == () and ruling.reason == "Done."
