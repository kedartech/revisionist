"""1941 intelligence: sources and the people who report them; battles and reports on (ITD).

Autumn 1941 switches on ``battles`` and ``reports``. Each of the seven nations names, for
each source it has, the person who reports it and the channel; codebreaking levels and
agents carry a source line or ``gap: true``; the piece kinds name their ``detect`` and
``conceal``; the Combined Fleet's leg of 22 November is concealed; and the leaders who gave
such orders get the intelligence forms (rule name ``intel``). A source line is a comment,
``# source: <key>`` or ``# gap: true``, on the line it cites: these declarations have no
citation field of their own. The scripted game is walked day by day as a tick walks it.
"""

import re
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId, OrderId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import detect
from revisionist.core.realism.answer import ParamValue
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import ON_ORDER, apply_changes
from revisionist.core.realism.war import polity_of
from revisionist.core.state import Rule, State
from revisionist.core.visibility import private_to
from revisionist.core.world_compile import object_id
from revisionist.engine import campaign as cmp
from tests.test_adjacency_moves import Logged, fold, seat
from tests.test_territory_model import CAMPAIGN

WORLD = Path(__file__).parents[1] / "worlds" / "autumn-1941.yaml"
START, LAST = date(1941, 9, 1), date(1941, 12, 7)
SEVEN = ("usa", "uk", "ussr", "germany", "japan", "italy", "china")
LEADERS = ("roosevelt", "churchill", "stalin", "hitler", "konoe", "tojo", "mussolini", "chiang")
CITED = re.compile(r"#\s*(?:source:\s*(?P<key>[a-z0-9_]+)|gap:\s*true)")


def raw() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(WORLD.read_text())
    return doc


def section(name: str) -> list[str]:
    """The lines of the top-level section ``name``, as written."""
    lines = WORLD.read_text().splitlines()
    first = lines.index(f"{name}:")
    rest = next(i for i in range(first + 1, len(lines)) if re.match(r"[a-z_]+:", lines[i]))
    return lines[first + 1 : rest]


def cited(line: str, sources: set[str]) -> bool:
    m = CITED.search(line)
    return m is not None and (m["key"] is None or m["key"] in sources)


def entity(key: str) -> EntityId:
    return EntityId(object_id(CAMPAIGN, "entity", key))


def feature(key: str) -> FeatureId:
    return FeatureId(object_id(CAMPAIGN, "feature", key))


def intel_forms() -> Iterator[tuple[str, dict[str, Any]]]:
    for card in raw()["cards"]:
        for lever in card.get("levers") or []:
            if lever["resolver"] == "intel":
                yield card["person"], lever


FORMS = [(person, lever["name"]) for person, lever in intel_forms()]


# --- the world file ----------------------------------------------------------------


def test_the_world_switches_on_battles_and_reports() -> None:
    w = cmp.load_world(WORLD)
    assert {Rule.BATTLES, Rule.REPORTS} <= set(w.rules)


def test_each_of_the_seven_nations_names_a_person_for_each_source() -> None:
    doc = raw()
    kinds = {e["key"]: e["kind"] for e in doc["entities"]}
    intel = {d["nation"]: d for d in doc["intelligence"]}
    assert sorted(intel) == sorted(SEVEN)
    for nation, d in intel.items():
        assert d["sources"], nation
        assert d["sources"][0]["source"] == "contact", nation
        for s in d["sources"]:
            assert kinds.get(s["person"]) == "person", (nation, s)
            assert s["channel"], (nation, s)


def test_a_nation_searches_by_air_and_by_patrol_only_with_pieces_that_can() -> None:
    doc = raw()
    domain = {k["key"]: k["domain"] for k in doc["piece_kinds"]}
    has: dict[str, set[str]] = {n: set() for n in SEVEN}
    for f in doc["features"]:
        if f.get("kind") == "piece" and f.get("side") in has:
            has[f["side"]].add(domain[f["piece"]])
    for d in doc["intelligence"]:
        named = {s["source"] for s in d["sources"]}
        assert ("air" in named) == ("air" in has[d["nation"]]), d["nation"]
        assert ("patrol" in named) == ("sea" in has[d["nation"]]), d["nation"]


def test_magic_comes_by_hand_from_kramer_and_ultra_from_menzies() -> None:
    intel = {d["nation"]: d for d in raw()["intelligence"]}
    by = {n: {s["source"]: s for s in d["sources"]} for n, d in intel.items()}
    assert by["usa"]["codebreaking"] == {
        "source": "codebreaking",
        "person": "kramer",
        "channel": "in_person",
    }
    assert by["uk"]["codebreaking"]["person"] == "menzies"


def test_the_starting_levels_and_agents() -> None:
    intel = {d["nation"]: d for d in raw()["intelligence"]}
    assert {n: d.get("codebreaking", 0) for n, d in intel.items() if d.get("codebreaking")} == {
        "usa": 2,
        "uk": 1,
    }
    assert intel["ussr"]["agents"] == [{"area": "japan_east", "until": date(1941, 10, 17)}]
    assert intel["japan"]["agents"] == [{"area": "hawaii"}]


def test_every_level_agent_and_new_person_carries_a_source_or_a_gap() -> None:
    sources = {s["key"] for s in raw()["sources"]}
    lines = section("intelligence")
    marked = [ln for ln in lines if re.match(r"\s+codebreaking: \d", ln) or "{area:" in ln]
    assert len(marked) == 4
    assert [ln.strip() for ln in marked if not cited(ln, sources)] == []
    new = [ln for ln in section("entities") if "{key: menzies," in ln or "{key: dai_li," in ln]
    assert len(new) == 2
    assert [ln.strip() for ln in new if not cited(ln, sources)] == []


def test_every_piece_kind_names_its_detect_and_conceal() -> None:
    for k in raw()["piece_kinds"]:
        assert {"detect", "conceal"} <= set(k), k["key"]


def test_the_strike_forces_leg_of_22_november_is_concealed() -> None:
    (fleet,) = [f for f in raw()["features"] if f["key"] == "combined_fleet"]
    (leg,) = [leg for leg in fleet["legs"] if leg["since"] == date(1941, 11, 22)]
    assert leg.get("concealed") is True
    g = Logged(cmp.load_world(WORLD))
    assert [leg.concealed for leg in g.state.features[feature("combined_fleet")].legs] == [True]


def test_army_group_centres_record_takes_kiev_and_then_steps_aside() -> None:
    (agc,) = [f for f in raw()["features"] if f["key"] == "army_group_centre"]
    assert [leg.get("takes", []) for leg in agc["legs"]] == [["kiev_area"], []]


# --- the forms ----------------------------------------------------------------------


def test_the_leaders_who_gave_such_orders_have_the_forms() -> None:
    have: dict[str, set[str]] = {}
    for person, lever in intel_forms():
        (form,) = next(p for p in lever["params"] if p["name"] == "intel")["choices"]
        have.setdefault(person, set()).add(form)
    assert have == {
        "roosevelt": {"recon", "patrol", "codebreaking"},
        "churchill": {"recon", "patrol", "agent", "codebreaking"},
        "stalin": {"patrol", "agent"},
        "hitler": {"recon", "patrol"},
        "konoe": {"agent"},
        "tojo": {"recon", "patrol", "agent", "conceal"},
        "mussolini": {"patrol"},
        "chiang": {"agent"},
        "timoshenko": {"conceal"},
    }


def test_every_form_line_carries_a_source_or_a_gap() -> None:
    sources = {s["key"] for s in raw()["sources"]}
    names = {name for _, name in FORMS}
    lines = [
        ln for ln in section("cards") if (m := re.match(r"\s+- name: (\w+)", ln)) and m[1] in names
    ]
    intel = [ln for ln in lines if CITED.search(ln)]
    assert len(intel) == len(FORMS)
    assert [ln.strip() for ln in intel if not cited(ln, sources)] == []


def test_a_form_names_only_its_own_nations_pieces_and_areas_of_the_board() -> None:
    doc = raw()
    domain = {k["key"]: k["domain"] for k in doc["piece_kinds"]}
    side = {f["key"]: (f["side"], domain[f["piece"]]) for f in doc["features"] if "piece" in f}
    nation = {c["person"]: c["principals"] for c in doc["cards"]}
    areas = {a["key"] for a in [*doc["territories"], *doc["sea_zones"]]}
    holds = {"konoe": "japan", "tojo": "japan", "chiang": "china", "mussolini": "italy"}
    holds |= {"roosevelt": "usa", "churchill": "uk", "stalin": "ussr", "hitler": "germany"}
    holds |= {"timoshenko": "ussr"}
    for person, lever in intel_forms():
        params = {p["name"]: p for p in lever["params"]}
        (form,) = params["intel"]["choices"]
        want = {"recon": "air", "patrol": "sea", "conceal": None}.get(form, "none")
        for key in params.get("piece", {}).get("choices", []):
            assert side[key][0] == holds[person], (person, lever["name"], key)
            assert want in (None, side[key][1]), (person, lever["name"], key)
        assert set(params.get("area", {}).get("choices", [])) <= areas, (person, nation[person])


def test_a_reconnaissance_form_offers_only_areas_in_its_air_groups_reach() -> None:
    doc = raw()
    near: dict[str, set[str]] = {}
    for link in doc["adjacency"]:
        a, b = link if isinstance(link, list) else (link["a"], link["b"])
        near.setdefault(a, set()).add(b)
        near.setdefault(b, set()).add(a)
    within = {e["key"]: e.get("within") for e in doc["entities"]}
    rng = {k["key"]: k.get("range_steps") for k in doc["piece_kinds"]}
    pieces = {f["key"]: f for f in doc["features"] if "piece" in f}
    for person, lever in intel_forms():
        params = {p["name"]: p for p in lever["params"]}
        if params["intel"]["choices"] != ["recon"]:
            continue
        for key in params["piece"]["choices"]:
            reach = {within[pieces[key]["places"][0]]}
            for _ in range(rng[pieces[key]["piece"]]):
                reach |= {n for a in reach for n in near.get(a, ())}
            assert set(params["area"]["choices"]) <= reach, (person, key)


def _order(state: State, person: str, lever: str, n: int) -> Order:
    found = next(x for x in state.cards[entity(person)].levers if x.name == lever)
    params: dict[str, ParamValue] = {p.name: p.choices[0] for p in found.params}
    return Order(
        order_id=OrderId(derived_id("itd", "form", n)),
        issuer=seat(person),
        lever=lever,
        pipeline=found.pipeline,
        params=params,
        filed=START,
    )


@pytest.fixture(scope="module")
def opened() -> State:
    """The game on 1 September with every leader and the Western Front's commander seated."""
    g = Logged(cmp.load_world(WORLD), *LEADERS, "timoshenko")
    g.add([ev.EconomySet(polity=entity(n), pools=Pools(output=100.0), on=START) for n in SEVEN])
    return g.state


@pytest.mark.parametrize(("person", "lever"), FORMS)
def test_each_intelligence_form_filed_changes_state(opened: State, person: str, lever: str) -> None:
    order = _order(opened, person, lever, FORMS.index((person, lever)))
    state = fold(
        opened,
        [
            ev.OrderDrafted(order=order),
            ev.OrderSettled(order_id=order.order_id, status=OrderStatus.ENACTED),
        ],
    )
    landed = apply_changes(state, ON_ORDER["intel"](state, state.orders[order.order_id]))
    assert {p.kind for p in landed} - {"document_issued"}, (person, lever)  # not a refusal
    after = fold(state, landed)
    assert after.model_dump() != state.model_dump(), (person, lever)
    assert [p.kind for p in landed if "refused" in p.kind] == [], (person, lever)


# --- the scripted game, walked as a tick walks it -----------------------------------


@pytest.fixture(scope="module")
def walked() -> tuple[Logged, list[ev.Event]]:
    g = Logged(cmp.load_world(WORLD), *LEADERS)
    out = g.walk(START + timedelta(days=1), LAST)
    return g, out


def _key(g: Logged, id_: str) -> str:
    del g
    doc = raw()
    keys: list[str] = [e["key"] for e in doc["entities"]] + [a["key"] for a in doc["territories"]]
    return next(k for k in keys if entity(k) == id_)


def test_typhoon_opens_a_battle_on_7_october_under_the_battle_rules(
    walked: tuple[Logged, list[ev.Event]],
) -> None:
    g, out = walked
    opened = [
        (e.payload.on, _key(g, e.payload.battle.area), _key(g, e.payload.battle.attacker.nation))
        for e in out
        if isinstance(e.payload, ev.BattleOpened)
    ]
    assert (date(1941, 10, 7), "moscow_area", "germany") in opened
    assert (date(1941, 9, 27), "hunan", "japan") in opened
    assert all(on > START for on, _, _ in opened)


def test_kiev_passes_to_germany_on_19_september(walked: tuple[Logged, list[ev.Event]]) -> None:
    g, out = walked
    held = [
        (e.payload.on, _key(g, e.payload.area), _key(g, e.payload.holder))
        for e in out
        if isinstance(e.payload, ev.AreaHeld)
    ]
    assert (date(1941, 9, 19), "kiev_area", "germany") in held


def test_magic_delivers_a_decrypt_and_sorge_stops_after_his_arrest(
    walked: tuple[Logged, list[ev.Event]],
) -> None:
    _, out = walked
    made = [e.payload for e in out if isinstance(e.payload, ev.ReportMade)]
    decrypts = [p for p in made if p.nation == entity("usa") and p.report.source == "codebreaking"]
    assert decrypts
    sorge = [
        p.report.seen for p in made if p.nation == entity("ussr") and p.report.source == "agent"
    ]
    assert sorge and max(sorge) <= date(1941, 10, 17)


def test_no_nations_paper_carries_another_nations_source(
    walked: tuple[Logged, list[ev.Event]],
) -> None:
    """Every report page goes to one seat, from a person that seat's nation named; and no
    seat's view holds a page another nation's person wrote."""
    g, out = walked
    intel = {d["nation"]: d for d in raw()["intelligence"]}
    own = {entity(n): {entity(s["person"]) for s in d["sources"]} for n, d in intel.items()}
    nation_of = {seat(p): polity_of(g.state, entity(p)) for p in LEADERS}
    titles = set(detect._TITLES.values())
    pages = [
        e.payload.document
        for e in out
        if isinstance(e.payload, ev.DocumentIssued)
        and e.payload.document.title.split(",")[0] in titles
    ]
    assert len({nation_of[s] for d in pages for s in nation_of if d.scope == private_to(s)}) >= 5
    for d in pages:
        (to,) = [s for s in nation_of if d.scope == private_to(s)]
        sender = nation_of[to]
        assert sender is not None
        assert d.author in own[sender], d.title
    for person in LEADERS:
        view = project(g.state, seat(person))
        nation = nation_of[seat(person)]
        assert nation is not None
        for d in view.documents.values():
            if d.title.split(",")[0] in titles:
                assert d.author in own[nation], (person, d.title)
