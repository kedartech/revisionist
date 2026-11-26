"""Four fields the room's reply carries for the screens that draw them (SVF).

1. ``world_key``: the key of the world the game was compiled from, read as the dossiers
   read it, with ``nation_keys``, each nation's key in that world by the game's id for it,
   so a flag can be found for a nation.
2. Each line of the People roster carries the portrait file its dossier names, or None.
3. ``wars``: the wars as the public record has them, each a pair of nations and the day
   it began, the same for every seat.
4. Each vote of a measure on its way carries the count of yeas that carries it, as the
   votes rule decides it (more yeas than nays among those voting).

The 1941 world is seated twice, for Churchill and for Hitler, so two seats of different
nations can be set side by side; the floor is the toy world's (``tests/test_web_groups.py``).
"""

import json
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

from revisionist.core.ids import CampaignId, EntityId, SeatId, derived_id
from revisionist.core.ontology import EntityKind
from revisionist.core.realism.groups import Cause
from revisionist.core.realism.resolvers import votes
from revisionist.core.state import State
from revisionist.core.world_compile import compile_world, object_id, resolve_keys
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import dossiers, home_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests.test_votes_from_groups import _bloc
from tests.test_web_groups import ASSEMBLY, NORRA, World, bill, fixture_game, game, home, moved

CAMPAIGN = CampaignId("01JSVFB0ARDF1E1DS0000000AA")
WORLD = "autumn-1941"
FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"


@cache
def _played() -> tuple[State, tuple[Any, ...], dict[str, str]]:
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path(WORLD))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    ids = resolve_keys(decl, CAMPAIGN)
    for who in ("churchill", "hitler"):
        name = load_state(store, CAMPAIGN).entities[EntityId(ids[who])].name
        session_zero.claim(store, CAMPAIGN, seat_of(ids, who), name)
    realism_tick.open_play(store, CAMPAIGN)
    return load_state(store, CAMPAIGN), tuple(store.read(CAMPAIGN)), ids


def seat_of(ids: dict[str, str], who: str) -> SeatId:
    return SeatId(derived_id(CAMPAIGN, "seat", ids[who]))


def block(who: str) -> dict[str, Any]:
    state, log, ids = _played()
    return rs.seat_realism(state, seat_of(ids, who), set(), set(), None, events=log)


def nation(key: str) -> str:
    return object_id(CAMPAIGN, "entity", key)


# --- Rule 1: the world's key --------------------------------------------------------


def test_the_reply_carries_the_worlds_key_as_the_dossiers_read_it() -> None:
    _, log, _ = _played()
    assert block("churchill")["world_key"] == WORLD == dossiers.world_key(log)


def test_each_nation_carries_its_key_in_the_world() -> None:
    keys = block("churchill")["nation_keys"]
    assert keys[nation("germany")] == "germany"
    assert keys[nation("uk")] == "uk"
    decl = cmp.load_world(cmp.world_path(WORLD))
    polities = {e.key for e in decl.entities if e.kind is EntityKind.POLITY}
    assert set(keys.values()) == polities
    assert keys == {nation(k): k for k in polities}


def test_a_game_with_no_log_has_no_world_key() -> None:
    state, _, ids = _played()
    out = rs.seat_realism(state, seat_of(ids, "churchill"), set(), set(), None)
    assert out["world_key"] is None
    assert out["nation_keys"] == {}


# --- Rule 2: the roster's portraits -------------------------------------------------


def roster(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["person"]: p for group in out["people"].values() for p in group}


def test_each_roster_line_carries_the_portrait_its_dossier_names() -> None:
    state, log, _ = _played()
    lines = roster(block("churchill"))
    assert lines[nation("roosevelt")]["portrait"] == "roosevelt.jpg"
    assert lines[nation("hitler")]["portrait"] == "hitler.jpg"
    named = dossiers.for_people(state, log)
    for person, line in lines.items():
        dossier = named.get(EntityId(person))
        assert line["portrait"] == (dossier["portrait"] if dossier else None), line["name"]


def test_a_person_with_no_dossier_portrait_has_none() -> None:
    state, log, _ = _played()
    named = dossiers.for_people(state, log)
    plain = [p for p in roster(block("churchill")).values() if p["person"] not in named]
    assert plain
    assert all(p["portrait"] is None for p in plain)


# --- Rule 3: the public wars ---------------------------------------------------------


WARS_1941 = {
    (frozenset({"uk", "germany"}), "1939-09-03"),
    (frozenset({"italy", "uk"}), "1940-06-10"),
    (frozenset({"germany", "ussr"}), "1941-06-22"),
    (frozenset({"italy", "ussr"}), "1941-06-22"),
    (frozenset({"japan", "china"}), "1937-07-07"),
    (frozenset({"ussr", "finland_state"}), "1941-06-25"),
    # The new lands' wars (WGN).
    (frozenset({"germany", "belgium"}), "1940-05-10"),
    (frozenset({"belgium", "italy"}), "1940-11-23"),
    (frozenset({"free_france", "germany"}), "1940-06-18"),
    (frozenset({"free_france", "italy"}), "1940-06-18"),
    (frozenset({"italy", "ethiopia_state"}), "1935-10-03"),
}


def test_the_reply_carries_every_war_of_the_record_with_the_day_it_began() -> None:
    out = block("churchill")
    keys = out["nation_keys"]
    found = {
        (frozenset({keys[w["a"]["key"]], keys[w["b"]["key"]]}), w["since"]) for w in out["wars"]
    }
    assert found == WARS_1941
    assert len(out["wars"]) == len(WARS_1941)
    state = _played()[0]
    names = {w["a"]["name"] for w in out["wars"]} | {w["b"]["name"] for w in out["wars"]}
    assert state.entities[EntityId(nation("germany"))].name in names
    assert all(set(w) == set(api.PublicWar.__annotations__) for w in out["wars"])


def test_the_wars_are_oldest_first() -> None:
    days = [w["since"] for w in block("hitler")["wars"]]
    assert days == sorted(days)
    assert days[0] == "1935-10-03"


# --- Rule 4: the count that carries a vote ------------------------------------------


def fewer_greys_voting(w: World) -> None:
    """Eighty of the Greys' hundred seats vote on the levy act, so the votes cast (180)
    are not the chamber's seats (200)."""
    _bloc(w, "greys")["votes"]["levy_act"][ASSEMBLY]["voting"] = 80


def test_a_vote_carries_its_carrying_count(tmp_path: Path) -> None:
    g = fixture_game(tmp_path)
    (vote,) = home(g)["chambers"][0]["measures"][0]["votes"]
    assert (vote["yeas"], vote["nays"]) == (91, 109)
    assert vote["carries"] == 101


def test_the_carrying_count_is_of_those_voting_not_of_the_seats(tmp_path: Path) -> None:
    g = game(tmp_path, fewer_greys_voting)
    moved(g, "greens", 5, Cause.BATTLE_WON, date(1900, 4, 2))
    bill(g, "levy_act")
    (chamber,) = home(g)["chambers"]
    assert sum(b["seats"] for b in chamber["blocs"]) == 200
    (vote,) = chamber["measures"][0]["votes"]
    assert vote["yeas"] + vote["nays"] == 180
    assert vote["carries"] == 91


def test_the_carrying_count_is_where_the_votes_rule_passes_a_vote() -> None:
    for voting in range(0, 12):
        n = home_api.carries(voting)
        assert n > voting - n, voting
        assert not (n - 1 > voting - (n - 1)), voting


def test_a_vote_at_its_carrying_count_passes_by_the_votes_rule(tmp_path: Path) -> None:
    g = fixture_game(tmp_path)
    order = next(iter(g.state.orders.values()))
    (vote,) = home(g)["chambers"][0]["measures"][0]["votes"]
    for yeas, passes in ((vote["carries"], True), (vote["carries"] - 1, False)):
        nays = vote["yeas"] + vote["nays"] - yeas
        assert (yeas > nays) is passes
    cast = votes.floor_counts(g.state, NORRA, order, "levy_act", None)
    ((_, _, parts),) = cast
    voting = sum(y + n for _, y, n in parts)
    assert vote["carries"] == home_api.carries(voting)


# --- Fog -------------------------------------------------------------------------------


def test_no_new_field_differs_between_seats_of_two_nations_but_the_roster() -> None:
    briton, german = block("churchill"), block("hitler")
    for key in ("world_key", "nation_keys", "wars"):
        assert briton[key] == german[key], key
    assert roster(briton) != roster(german)


def test_a_seat_of_a_nation_with_no_chamber_counts_nothing(tmp_path: Path) -> None:
    g = fixture_game(tmp_path)
    assert home(g, "tomas")["chambers"] == []


# --- The client fixture ---------------------------------------------------------------


def test_the_client_fixture_carries_the_four_fields_in_the_servers_shape() -> None:
    fixture = json.loads(FIXTURE.read_text())
    assert isinstance(fixture["world_key"], str)
    assert fixture["nation_keys"] and all(
        isinstance(k, str) and isinstance(v, str) for k, v in fixture["nation_keys"].items()
    )
    assert fixture["wars"]
    for war in fixture["wars"]:
        assert set(war) == set(api.PublicWar.__annotations__)
        assert set(war["a"]) == set(war["b"]) == set(api.WarNation.__annotations__)
    lines = [p for group in fixture["people"].values() for p in group]
    assert lines and all("portrait" in p for p in lines)
    assert any(p["portrait"] for p in lines)
    votes_ = [v for c in fixture["home"]["chambers"] for m in c["measures"] for v in m["votes"]]
    assert votes_ and all(v["carries"] == home_api.carries(v["yeas"] + v["nays"]) for v in votes_)
