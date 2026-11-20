"""History steps aside (HSA).

The toy world of ``tests/test_battles.py`` (territories, holders and battles on; Norra and
Sudland at war). Norra's levy, sent to Sudby, steps into the Sudland Coast on day 12, where
Sudland's levy stands: the battle opens that day. A scripted leg is a move the record says
a piece made; a piece that has been in a battle drops the ones still to come, and the
areas a leg ``takes`` pass to its side on its date unless the rules have a say there.
"""

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId
from revisionist.core.realism import holders
from revisionist.core.realism.geography import Leg
from revisionist.core.realism.territory import StepCause
from revisionist.core.world import WorldFile
from tests.async_table import digest
from tests.test_adjacency_moves import Logged, World, day, entity, piece, set_feature, where
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_battles import payloads, strengths, to_coast, toy
from tests.test_head_on import MEETS, head_on, levy
from tests.test_holders import held
from tests.test_holders import toy as holders_toy
from tests.test_territory_model import created, refused

COAST, HILLS, ISLE = "sudland_coast", "norra_hills", "isle"
OPENS = day(12)


def problem(world: WorldFile, text: str) -> None:
    problems = refused(world)
    assert any(text in p for p in problems), problems


def iso(d: date) -> str:
    return d.isoformat()


def legs(key: str, *items: dict[str, Any]) -> Callable[[World], None]:
    return set_feature(key, legs=list(items))


def leg(on: date, *places: str, **more: Any) -> dict[str, Any]:
    return {"since": iso(on), "places": list(places), **more}


def scripted(out: Sequence[ev.Event], nation: str) -> list[tuple[EntityId, EntityId]]:
    return [
        (p.left, p.entered)
        for p in payloads(out, ev.PieceStepped)
        if p.cause is StepCause.SCRIPTED and p.nation == entity(nation)
    ]


def hill_levy(*items: dict[str, Any]) -> Callable[[World], None]:
    """A second Norra levy in the Norra Hills, next to the coast, with ``items`` as legs."""

    def change(w: World) -> None:
        w["entities"].append(
            {"key": "hill_fort", "kind": "location", "name": "Hill Fort", "at": [150, 60]}
            | {"within": HILLS}
        )
        w["features"].append(
            {
                "key": "hill_levy",
                "kind": "piece",
                "piece": "levy",
                "name": "The Hill Levy",
                "side": "norra",
                "places": ["hill_fort"],
                "tier": 5,
                "legs": list(items),
                "source": "toy",
            }
        )

    return change


# --- Rule 1: a force that has been in a battle loses its remaining scripted legs --------


def test_a_defender_in_a_battle_loses_its_scripted_legs(tmp_path: Path) -> None:
    g = to_coast(tmp_path, legs("sudland_levy", leg(day(40), "norrhavn")))
    assert piece(g.state, "sudland_levy").legs
    g.walk(day(1), OPENS)
    assert g.state.battles
    assert piece(g.state, "sudland_levy").legs == ()


def test_a_scripted_attacker_loses_the_legs_after_the_one_that_took_it_in(
    tmp_path: Path,
) -> None:
    w = toy(tmp_path, hill_levy(leg(day(1), "sudby"), leg(day(40), "hill_fort")))
    g = Logged(w, "ilse", "tomas")
    out = g.walk(day(1), day(6))
    assert scripted(out, "norra") == [(entity(HILLS), entity(COAST))]
    assert payloads(out, ev.BattleOpened)
    assert piece(g.state, "hill_levy").legs == ()
    later = g.walk(day(7), day(60))
    assert scripted(later, "norra") == []


def test_a_piece_that_joins_a_battle_loses_its_scripted_legs(tmp_path: Path) -> None:
    joins = hill_levy(leg(day(8), "sudby"), leg(day(40), "hill_fort"))
    g = to_coast(tmp_path, strengths(norra_levy=5, sudland_levy=5), joins)
    out = g.walk(day(1), day(13))
    (fought,) = g.state.battles.values()
    hill = piece(g.state, "hill_levy").feature_id
    assert payloads(out, ev.BattleDecided) and hill in fought.attacker.pieces
    assert piece(g.state, "hill_levy").legs == ()


def test_a_piece_in_a_meeting_battle_loses_its_scripted_legs(tmp_path: Path) -> None:
    guard = (
        levy("guard_levy", "sudland", "sudby", 3),
        legs("guard_levy", leg(day(40), "norrhavn")),
    )
    g = head_on(tmp_path, *guard)
    out = g.walk(day(1), MEETS)
    (opened,) = payloads(out, ev.BattleOpened)
    assert opened.battle.meeting
    fought = (*opened.battle.attacker.pieces, *opened.battle.defender.pieces)
    assert piece(g.state, "guard_levy").feature_id in fought
    assert piece(g.state, "guard_levy").legs == ()
    assert g.state.fought == {entity(HILLS), entity(COAST)}


def test_a_piece_in_no_battle_keeps_its_legs(tmp_path: Path) -> None:
    g = to_coast(tmp_path, legs("norra_kites", leg(day(40), "norrhavn")))
    g.walk(day(1), OPENS)
    assert g.state.battles
    assert len(piece(g.state, "norra_kites").legs) == 1


# --- Rule 2: in a territory world a leg names areas and goes by adjacency --------------


def test_a_scripted_leg_may_name_an_area_and_moves_step_by_step(tmp_path: Path) -> None:
    w = territories_toy(tmp_path, legs("norra_levy", leg(day(3), COAST)))
    g = Logged(w, "ilse", "tomas")
    out = g.walk(day(1), day(20))
    assert scripted(out, "norra") == [
        (entity("norra_plain"), entity(HILLS)),
        (entity(HILLS), entity(COAST)),
    ]
    assert where(g.state, "norra_levy") == entity(COAST)


def test_a_leg_into_an_area_its_piece_cannot_stand_in_is_refused(tmp_path: Path) -> None:
    problem(territories_toy(tmp_path, legs("norra_levy", leg(day(3), "open_sea"))), "cannot stand")


def test_a_piece_still_starts_at_a_place(tmp_path: Path) -> None:
    problem(territories_toy(tmp_path, set_feature("norra_levy", places=[HILLS])), "position")


def test_without_territories_a_leg_still_names_a_place(tmp_path: Path) -> None:
    def no_rules(w: World) -> None:
        w["rules"] = []

    world = territories_toy(tmp_path, no_rules, legs("norra_levy", leg(day(3), COAST)))
    problem(world, "not a place with a position")


# --- Rule 3: a leg's ``takes`` pass to its side on its date, unless the rules decide -----


def herald_takes(on: date, *areas: str) -> Callable[[World], None]:
    """Norra's herald, at Norrhavn, given a leg dated ``on`` that takes ``areas``."""
    return legs("norra_herald", leg(on, "norrhavn", takes=list(areas)))


def test_a_leg_takes_an_area_for_its_side_on_its_date(tmp_path: Path) -> None:
    g = Logged(holders_toy(tmp_path, herald_takes(day(3), ISLE)), "ilse", "tomas")
    assert held(g.walk(day(1), day(2))) == []
    out = g.walk(day(3), day(3))
    assert [(h.area, h.holder, h.was, h.on) for h in held(out)] == [
        (entity(ISLE), entity("norra"), entity("sudland"), day(3))
    ]
    assert piece(g.state, "norra_herald").legs == ()


def test_an_area_where_an_enemy_land_piece_stands_is_left_to_the_rules(tmp_path: Path) -> None:
    g = Logged(holders_toy(tmp_path, herald_takes(day(3), COAST, ISLE)), "ilse", "tomas")
    out = g.walk(day(1), day(5))
    assert [h.area for h in held(out)] == [entity(ISLE)]


def test_an_area_where_a_battle_was_fought_is_left_to_the_rules(tmp_path: Path) -> None:
    g = to_coast(tmp_path, strengths(norra_levy=5, sudland_levy=1), herald_takes(day(13), COAST))
    out = g.walk(day(1), OPENS)
    (ended,) = payloads(out, ev.BattleEnded)
    assert ended.on == OPENS and not g.state.battles
    assert entity(COAST) in g.state.fought
    taken = g.walk(day(13), day(13))
    assert held(taken) == []
    later = g.walk(day(14), day(14))
    assert [(h.area, h.holder) for h in held(later)] == [(entity(COAST), entity("norra"))]


def test_two_nations_taking_one_area_on_one_day_leave_it_to_the_rules(tmp_path: Path) -> None:
    g = Logged(holders_toy(tmp_path), "ilse", "tomas")
    norra, sudland = entity("norra"), entity("sudland")
    claims = [(entity("norra_hills"), sudland), (entity("norra_hills"), norra)]
    assert holders.record_takes(g.state, claims, day(1)) == []
    claims = [(entity(ISLE), norra), (entity(ISLE), norra)]
    (one,) = holders.record_takes(g.state, claims, day(1))
    assert isinstance(one, ev.AreaHeld) and one.holder == norra


def test_an_area_its_side_already_holds_lands_nothing(tmp_path: Path) -> None:
    g = Logged(holders_toy(tmp_path, herald_takes(day(3), HILLS)), "ilse", "tomas")
    assert held(g.walk(day(1), day(5))) == []


def test_without_holders_takes_are_refused_at_compile(tmp_path: Path) -> None:
    problem(territories_toy(tmp_path, herald_takes(day(3), ISLE)), "takes")


def test_only_a_pieces_leg_takes(tmp_path: Path) -> None:
    def front(w: World) -> None:
        w["features"].append(
            {
                "key": "the_front",
                "kind": "front",
                "name": "The Front",
                "places": ["norrhavn", "sudby"],
                "legs": [leg(day(3), "norrhavn", "sudby", takes=[ISLE])],
                "source": "toy",
            }
        )

    problem(holders_toy(tmp_path, front), "only a piece")


def test_a_leg_takes_only_territories(tmp_path: Path) -> None:
    problem(holders_toy(tmp_path, herald_takes(day(3), "the_gulf")), "not a territory")


# --- The stored shape: takes and concealed on a leg ----------------------------------


def compiled_legs(world: WorldFile, key: str) -> tuple[Leg, ...]:
    events, _ = created(world)
    for e in events:
        p = e.payload
        if isinstance(p, ev.FeatureSet) and p.feature.feature_id == FeatureId(entity(key)):
            return p.feature.legs
    raise AssertionError(key)  # pragma: no cover


def test_a_leg_carries_its_takes_and_concealed_mark(tmp_path: Path) -> None:
    w = holders_toy(
        tmp_path, legs("norra_levy", leg(day(3), "norrhavn", takes=[ISLE], concealed=True))
    )
    (one,) = compiled_legs(w, "norra_levy")
    assert one.takes == (entity(ISLE),) and one.concealed is True


def test_a_leg_with_neither_dumps_as_before(tmp_path: Path) -> None:
    w = holders_toy(tmp_path, legs("norra_levy", leg(day(3), "norrhavn")))
    (one,) = compiled_legs(w, "norra_levy")
    assert set(one.model_dump(mode="json")) == {"since", "places"}


@pytest.mark.parametrize("field", ["takes", "concealed"])
def test_the_new_leg_keys_are_not_offered_to_a_model(field: str) -> None:
    schema = WorldFile.model_json_schema()
    assert field not in schema["$defs"]["LegDecl"]["properties"]


# --- Invariant: the walk cut into any sittings gives one world -------------------------


def history_game(tmp: Path) -> Logged:
    tmp.mkdir()
    joins = hill_levy(leg(day(8), "sudby"), leg(day(40), "hill_fort"))
    return to_coast(
        tmp,
        joins,
        legs("sudland_levy", leg(day(30), "norrhavn")),
        herald_takes(day(13), COAST, ISLE),
    )


@pytest.mark.parametrize("cuts", [(), (11, 12), tuple(range(1, 30))])
def test_the_walk_cut_into_sittings_gives_one_world(tmp_path: Path, cuts: tuple[int, ...]) -> None:
    whole = history_game(tmp_path / "whole")
    whole.walk(day(1), day(30))
    cut = history_game(tmp_path / "cut")
    first = day(1)
    for n in (*cuts, 30):
        cut.walk(first, day(n))
        first = day(n + 1)
    assert digest(cut.state) == digest(whole.state)
    assert [type(e.payload) for e in cut.log] == [type(e.payload) for e in whole.log]
