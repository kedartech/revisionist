"""1941 pacts, capitals, envoys and the two conferences (PCW).

Autumn 1941 switches on ``agreements`` and ``conference``. It carries four pacts in force on
the start date, each cited (the fourth, Mongolia's with the Soviet Union, came with the new
lands); a capital for each nation; two envoys with scripted missions as ``legs``, each cited;
and two scheduled conferences whose sourced last day is the voting day, called ``CONF_DAYS``
earlier. A source line is a comment, ``# source: <key>``, on the line it
cites where the declaration has no citation field of its own (a leg).

With ``peace`` on (PED), each of the eight nations with a seat has one row of the kind peace
naming who allows it to accept a peace, someone with a card, and the Anglo-Soviet agreement
bars each party a separate peace with Germany. With ``peace`` out of a copy's rules the
scripted run's digest is the third run's baseline.
"""

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core import events as ev
from revisionist.core.fold import replay
from revisionist.core.ids import FeatureId, derived_id
from revisionist.core.realism import locks, territory
from revisionist.core.realism.conference import CONF_DAYS
from revisionist.core.realism.effect import ClauseType
from revisionist.core.realism.locks import Question
from revisionist.core.state import Rule
from revisionist.core.world import ConferenceDecl, LockDeciderDecl, LockDecl, PactDecl, WorldFile
from revisionist.core.world_compile import WorldError, compile_world, object_id
from revisionist.engine import campaign as cmp
from tests import test_world_locks_1941 as locks_1941
from tests.test_adjacency_moves import entity
from tests.test_conference import Game
from tests.test_rule_names import SHIPPED_1941
from tests.test_territory_model import CAMPAIGN

WORLD = Path(__file__).parents[1] / "worlds" / "autumn-1941.yaml"
START, LAST = date(1941, 9, 1), date(1941, 12, 7)
SEVEN = ("usa", "uk", "ussr", "germany", "japan", "italy", "china")


def raw() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(WORLD.read_text())
    return doc


def sources() -> set[str]:
    return {s["key"] for s in raw()["sources"]}


def pacts() -> dict[str, dict[str, Any]]:
    return {p["key"]: p for p in raw().get("pacts") or []}


def conferences() -> dict[str, dict[str, Any]]:
    return {c["key"]: c for c in raw().get("conferences") or []}


def test_the_world_switches_on_agreements_and_conference() -> None:
    w = cmp.load_world(WORLD)
    assert {Rule.AGREEMENTS, Rule.CONFERENCE} <= set(w.rules)


# --- pacts ------------------------------------------------------------------------------


def test_four_pacts_each_between_named_nations_with_a_source() -> None:
    found = pacts()
    assert {k: (tuple(p["parties"]), p["public"]) for k, p in found.items()} == {
        "tripartite_pact": (("japan", "germany", "italy"), True),
        "anglo_soviet_agreement": (("uk", "ussr"), True),
        "soviet_japanese_neutrality": (("ussr", "japan"), True),
        "soviet_mongolian_protocol": (("ussr", "mongolia_state"), True),
    }
    for key, p in found.items():
        assert p["source"] in sources(), key
        assert not p.get("gap"), key


def test_the_tripartite_pact_defends_each_party_against_a_new_attacker() -> None:
    clauses = pacts()["tripartite_pact"]["clauses"]
    assert {(c["type"], c["binds"], c["nation"]) for c in clauses} == {
        ("defend", a, b)
        for a in ("japan", "germany", "italy")
        for b in ("japan", "germany", "italy")
        if a != b
    }
    assert all(c["days"] > 0 for c in clauses)


def test_the_anglo_soviet_agreement_bars_each_a_separate_peace_with_germany() -> None:
    clauses = pacts()["anglo_soviet_agreement"]["clauses"]
    assert {(c["type"], c["binds"], c["nation"]) for c in clauses} == {
        ("no_separate_peace", "uk", "germany"),
        ("no_separate_peace", "ussr", "germany"),
    }


def test_the_soviet_japanese_pact_forbids_an_attack_either_way() -> None:
    clauses = pacts()["soviet_japanese_neutrality"]["clauses"]
    assert {(c["type"], c["binds"], c["nation"]) for c in clauses} == {
        ("no_attack", "ussr", "japan"),
        ("no_attack", "japan", "ussr"),
    }


def test_the_pacts_are_agreements_in_force_on_the_first_day() -> None:
    w = cmp.load_world(WORLD)
    state = replay(compile_world(w, CAMPAIGN, cmp.versions()))
    made = state.agreements.made
    for key, p in pacts().items():
        x = made[derived_id(CAMPAIGN, "pact", key)]
        assert x.made == START and x.offer_id is None
        assert set(x.parties) == {entity(k) for k in p["parties"]}
        assert [c.type is ClauseType.UNCHECKED for c in x.clauses] == [
            c["type"] == "unchecked" for c in p["clauses"]
        ]
    assert state.agreements.offers == {}


# --- peace: who may accept one, and the pact it breaks ----------------------------------


def test_the_world_switches_on_peace() -> None:
    assert Rule.PEACE in cmp.load_world(WORLD).rules


def peace_rows(world: WorldFile) -> list[LockDecl]:
    return [r for r in world.locks if r.question == Question.PEACE.value]


def uncarded(world: WorldFile) -> list[str]:
    """The peace rows whose decider, or a member or head of whose council, has no card."""
    carded = {c.person for c in world.cards}
    out = []
    for row in peace_rows(world):
        d = row.decider
        who = {
            d.person,
            d.head,
            *(d.council.members if d.council else ()),
            *((d.council.head,) if d.council else ()),
        } - {None}
        if not who or not who <= carded:
            out.append(row.key)
    return out


def test_each_nation_with_a_seat_has_one_peace_row_decided_by_someone_with_a_card() -> None:
    w = cmp.load_world(WORLD)
    state = replay(compile_world(w, CAMPAIGN, cmp.versions()))
    seated = {territory.nation(state, entity(c.person)) for c in w.cards if c.playable}
    assert seated == {entity(k) for k in (*SEVEN, "finland_state")}
    for nation in seated:
        assert nation is not None
        rows = locks.rows_on(state, nation, Question.PEACE)
        assert len(rows) == 1, nation
        assert rows[0].order is None and rows[0].when is None, nation
    assert len(peace_rows(w)) == len(seated)
    assert uncarded(w) == []


def test_a_peace_row_whose_decider_has_no_card_is_caught() -> None:
    w = cmp.load_world(WORLD)
    carded = {c.person for c in w.cards}
    nobody = next(e.key for e in w.entities if e.kind == "person" and e.key not in carded)
    rows = tuple(
        r.model_copy(update={"decider": LockDeciderDecl(person=nobody)})
        if r.key == "italy_peace"
        else r
        for r in w.locks
    )
    assert uncarded(w.model_copy(update={"locks": rows})) == ["italy_peace"]


def test_with_peace_out_of_a_copys_rules_the_scripted_digest_is_the_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = locks_1941._world()
    off = w.model_copy(update={"rules": tuple(r for r in w.rules if r != Rule.PEACE.value)})
    assert Rule.PEACE.value not in off.rules
    assert locks_1941.run_digest(off, monkeypatch) == SHIPPED_1941


# --- capitals ---------------------------------------------------------------------------


def test_each_of_the_seven_nations_has_a_capital_site_in_a_territory_it_holds() -> None:
    doc = raw()
    entities = {e["key"]: e for e in doc["entities"]}
    held = {t["key"]: t["holder"] for t in doc["territories"]}
    for nation in SEVEN:
        site = entities[nation]["capital"]
        assert entities[site]["kind"] == "location", nation
        assert held[entities[site]["within"]] == nation, nation


def test_every_polity_with_a_territory_has_a_capital() -> None:
    doc = raw()
    holders = {t["holder"] for t in doc["territories"]}
    polities = {e["key"] for e in doc["entities"] if e["kind"] == "polity"}
    held = {k for k in polities if k in holders}
    assert {e["key"] for e in doc["entities"] if e.get("capital")} == held


def test_the_capitals_are_the_seats_of_government() -> None:
    entities = {e["key"]: e for e in raw()["entities"]}
    assert {n: entities[n]["capital"] for n in SEVEN} == {
        "usa": "washington",
        "uk": "london",
        "ussr": "moscow",
        "germany": "berlin",
        "japan": "tokyo",
        "italy": "rome",
        "china": "chungking",
    }


# --- envoys -----------------------------------------------------------------------------

CITED = re.compile(r"#\s*source:\s*(?P<key>[a-z0-9_]+)")


def test_the_envoy_kind_moves_by_envoy_domain() -> None:
    kinds = {k["key"]: k for k in raw()["piece_kinds"]}
    assert kinds["envoy"]["domain"] == "envoy"


def test_two_envoy_missions_are_scripted_as_legs() -> None:
    feats = {f["key"]: f for f in raw()["features"] if f.get("piece") == "envoy"}
    assert {
        k: (f["side"], f["places"], [(g["since"], g["places"]) for g in f["legs"]])
        for k, f in feats.items()
    } == {
        "moscow_mission": ("uk", ["london"], [(date(1941, 9, 16), ["moscow"])]),
        "kurusu_mission": ("japan", ["tokyo"], [(date(1941, 11, 5), ["washington"])]),
    }


def test_each_mission_names_its_source_on_its_line() -> None:
    lines = [ln for ln in WORLD.read_text().splitlines() if "piece: envoy" in ln]
    assert len(lines) == 2
    block = WORLD.read_text().splitlines()
    for i, ln in enumerate(block):
        if "piece: envoy" in ln:
            above = " ".join(block[max(0, i - 4) : i + 1])
            keys = CITED.findall(above)
            assert keys and set(keys) <= sources(), ln


@pytest.fixture(scope="module")
def walked() -> tuple[Game, list[ev.Event]]:
    """The scripted game: a wake opens and closes every third day, the days walked between."""
    g = Game(cmp.load_world(WORLD), "roosevelt", "churchill", "stalin", "hitler", "konoe")
    out: list[ev.Event] = []
    day = START
    while day < LAST:
        g.open()
        g.close()
        day = min(day + timedelta(days=3), LAST)
        out += g.tick(day)
    return g, out


def _arrival(walk: tuple[Game, list[ev.Event]], piece: str, area: str) -> date | None:
    g, out = walk
    feature = g.state.features[FeatureId(object_id(CAMPAIGN, "feature", piece))]
    assert feature.side is not None
    mark = territory.mark_key(g.state, feature.side, feature)
    found = [
        e.payload.on
        for e in out
        if isinstance(e.payload, ev.PieceStepped)
        and e.payload.mark == mark
        and e.payload.entered == entity(area)
    ]
    return min(found) if found else None


def test_the_anglo_american_mission_stands_in_moscow_on_the_record_day(
    walked: tuple[Game, list[ev.Event]],
) -> None:
    on = _arrival(walked, "moscow_mission", "moscow_area")
    assert on is not None
    assert abs((on - date(1941, 9, 28)).days) <= 2


def test_kurusu_stands_in_washington_on_the_record_day(walked: tuple[Game, list[ev.Event]]) -> None:
    on = _arrival(walked, "kurusu_mission", "us_east")
    assert on is not None
    assert abs((on - date(1941, 11, 15)).days) <= 2


# --- conferences ------------------------------------------------------------------------


def test_two_conferences_each_with_a_source_and_a_voting_day() -> None:
    found = conferences()
    assert {
        k: (c["caller"], tuple(c["invited"]), c["opens"], c["voting_day"], c["public"])
        for k, c in found.items()
    } == {
        "moscow_supply_conference": (
            "ussr",
            ("ussr", "uk", "usa"),
            date(1941, 9, 27),
            date(1941, 10, 1),
            True,
        ),
        "anti_comintern_renewal": (
            "germany",
            ("germany", "japan", "italy", "hungary", "romania_state", "finland_state", "spain"),
            date(1941, 11, 21),
            date(1941, 11, 25),
            True,
        ),
    }
    for key, c in found.items():
        assert c["source"] in sources(), key
        assert (c["voting_day"] - c["opens"]).days >= CONF_DAYS, key


def test_the_conferences_are_scheduled_at_the_start() -> None:
    w = cmp.load_world(WORLD)
    state = replay(compile_world(w, CAMPAIGN, cmp.versions()))
    held = state.conferences.held
    assert set(held) == set(conferences())
    for key, c in conferences().items():
        assert held[key].voting_day == c["voting_day"]
        assert held[key].opens == c["opens"]


def test_each_conference_is_tallied_on_its_voting_day(walked: tuple[Game, list[ev.Event]]) -> None:
    tallied = {
        e.payload.conference: e.payload.tally.on
        for e in walked[1]
        if isinstance(e.payload, ev.ConferenceTallied)
    }
    assert set(tallied) == set(conferences())
    for key, c in conferences().items():
        assert tallied[key] >= c["voting_day"], key


# --- what the world refuses (mutants) ---------------------------------------------------


def test_a_pact_with_one_party_is_refused() -> None:
    w = cmp.load_world(WORLD)
    one = PactDecl.model_validate({**pacts()["soviet_japanese_neutrality"], "parties": ["ussr"]})
    bad = w.model_copy(update={"pacts": (*w.pacts[:-1], one)})
    with pytest.raises(WorldError) as caught:
        compile_world(bad, CAMPAIGN, cmp.versions())
    assert "pact soviet_japanese_neutrality: names at least two nations" in caught.value.problems


def test_a_conference_with_no_voting_day_is_refused() -> None:
    body = {k: v for k, v in conferences()["moscow_supply_conference"].items() if k != "voting_day"}
    with pytest.raises(ValueError, match="voting_day"):
        ConferenceDecl.model_validate(body)
    w = cmp.load_world(WORLD)
    early = ConferenceDecl.model_validate({**body, "voting_day": body["opens"]})
    bad = w.model_copy(update={"conferences": (early, *w.conferences[1:])})
    with pytest.raises(WorldError) as caught:
        compile_world(bad, CAMPAIGN, cmp.versions())
    assert any("votes less than" in p for p in caught.value.problems)
