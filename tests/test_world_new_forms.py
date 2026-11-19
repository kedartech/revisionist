"""The Mediterranean and China feeds and move forms (MCF), as a staging file.

``worlds/maps/src/autumn-1941/cards-part.yaml`` holds what the territory world of autumn 1941
adds to today's cards: the feeds that report the Mediterranean and China forces, and the move
forms that order them. The item that converts the world (FLP) folds it into the world file, so the
game plays as today until then. These tests read it against today's world file and the 1941 start
(``start.yaml``, the new forces, places and wars) and the map's world fragment (the areas).

Two blocks: ``feeds``, each shaped as the world file has a feed (a key today's world already has
is that feed restated whole, and replaces it); and ``cards``, each a part of one card: the feeds the
card gains, and its move forms, each shaped as the world file has a lever (a name the card already
has is that lever restated whole, and replaces it).
"""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core.world import FeedDecl, LeverDecl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "worlds" / "maps" / "src" / "autumn-1941"
PART = SRC / "cards-part.yaml"
START = SRC / "start.yaml"
FRAGMENT = ROOT / "worlds" / "maps" / "autumn-1941.world.yaml"
WORLD = ROOT / "tests" / "worlds" / "autumn-1941-points.yaml"
"""The world before territories, which the staging files were written against."""

MEDITERRANEAN = (
    "mediterranean_fleet",
    "western_desert_force",
    "italian_fleet",
    "italian_army_libya",
    "afrika_korps",
)
"""The Mediterranean forces the 1941 start adds."""

CHINA = ("ninth_war_area", "eleventh_army")
"""The China forces the 1941 start adds."""

DOMAIN_OF = {"army": "land", "fleet": "sea", "air": "air"}
"""Today's force kinds by domain."""


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def part() -> dict[str, Any]:
    return dict(_yaml(PART))


@pytest.fixture(scope="module")
def world() -> dict[str, Any]:
    return dict(_yaml(WORLD))


@pytest.fixture(scope="module")
def start() -> dict[str, Any]:
    return dict(_yaml(START))


@pytest.fixture(scope="module")
def fragment() -> dict[str, Any]:
    return dict(_yaml(FRAGMENT))


# ---------------------------------------------------------------- the files, merged


def merged_feeds(world: dict[str, Any], part: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Today's feeds with the part's: a key already there is replaced, a new one added."""
    out = {str(f["key"]): f for f in world["feeds"]}
    out.update({str(f["key"]): f for f in part["feeds"]})
    return out


def merged_cards(world: dict[str, Any], part: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Today's cards with the part's feeds added and its levers put in by name."""
    cards = {str(c["person"]): copy.deepcopy(c) for c in world["cards"]}
    for p in part["cards"]:
        card = cards[str(p["person"])]
        card["feeds"] = [*card.get("feeds", []), *p.get("feeds", [])]
        levers = list(card.get("levers", []))
        for lv in p.get("levers", []):
            at = [i for i, old in enumerate(levers) if old["name"] == lv["name"]]
            if at:
                levers[at[0]] = lv
            else:
                levers.append(lv)
        card["levers"] = levers
    return cards


def _entities(world: dict[str, Any], start: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {str(e["key"]): e for e in world["entities"]}
    out.update({str(e["key"]): e for e in start["entities"]})
    return out


def _nation(key: str, entities: dict[str, dict[str, Any]]) -> str | None:
    """The polity a person, body or polity belongs to, up its parents."""
    at: str | None = key
    for _ in range(8):
        if at is None or at not in entities:
            return None
        if entities[at]["kind"] == "polity":
            return at
        at = entities[at].get("parent")
    return None


def _forces(world: dict[str, Any], start: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every force by key, with its side and its domain."""
    out: dict[str, dict[str, Any]] = {}
    for f in world["features"]:
        if f["kind"] in DOMAIN_OF:
            out[str(f["key"])] = {"side": f["side"], "domain": DOMAIN_OF[f["kind"]]}
    kinds = {str(k["key"]): k["domain"] for k in start["piece_kinds"]}
    for f in start["features"]:
        out[str(f["key"])] = {"side": f["side"], "domain": kinds[f["piece"]]}
    return out


def _wars(start: dict[str, Any]) -> set[frozenset[str]]:
    return {frozenset((str(w["a"]), str(w["b"]))) for w in start["wars"]}


def _may_know(own: str, other: str, wars: set[frozenset[str]]) -> bool:
    """Whether a nation's reports may name another's force: its own, an enemy's at war with
    it, or an ally's (not at war with it, and at war with a common enemy)."""
    if own == other or frozenset((own, other)) in wars:
        return True
    foes = {x for w in wars if own in w for x in w if x != own}
    return any(frozenset((other, foe)) in wars for foe in foes)


def _placed(world: dict[str, Any], start: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Places with a position, by key."""
    return {
        k: e
        for k, e in _entities(world, start).items()
        if e["kind"] == "location" and e.get("at") is not None
    }


def _areas(fragment: dict[str, Any]) -> dict[str, str]:
    """Every area by key: ``land`` for a territory, ``sea`` for a sea zone."""
    out = {str(t["key"]): "land" for t in fragment["territories"]}
    out.update({str(z["key"]): "sea" for z in fragment["sea_zones"]})
    return out


def _param(lever: dict[str, Any], name: str) -> dict[str, Any]:
    return next(p for p in lever["params"] if p["name"] == name)


def _movement(card: dict[str, Any]) -> list[dict[str, Any]]:
    return [lv for lv in card.get("levers", []) if lv["resolver"] == "movement"]


# ---------------------------------------------------------------- the checker


def problems(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any], fragment: dict[str, Any]
) -> list[str]:
    """What is wrong with the part read against today's world, the start and the map."""
    out: list[str] = []
    entities = _entities(world, start)
    forces = _forces(world, start)
    wars = _wars(start)
    places = _placed(world, start)
    areas = _areas(fragment)
    feeds = merged_feeds(world, part)
    cards = merged_cards(world, part)
    held = {f for c in cards.values() for f in c.get("feeds", [])}
    # Today's destinations on a restated form are left to the item that places them (FLP).
    kept = {
        (str(c["person"]), str(lv["name"])): set(_param(lv, "to")["choices"])
        for c in world["cards"]
        for lv in _movement(c)
    }
    for f in part["feeds"]:
        key = str(f["key"])
        if key not in held:
            out.append(f"feed {key}: no card holds it")
        author = entities.get(str(f["author"]))
        if author is None or author["kind"] != "person":
            out.append(f"feed {key}: author {f['author']} is not a person")
            continue
        own = _nation(str(f["author"]), entities)
        for s in f.get("sights", []):
            if s not in forces:
                if s not in {str(x["key"]) for x in world["features"]}:
                    out.append(f"feed {key}: sights {s}, not a feature")
                continue
            if own is None or not _may_know(own, str(forces[s]["side"]), wars):
                out.append(f"feed {key}: {own} would not see {s}")
    for p in part["cards"]:
        person = str(p["person"])
        card = cards[person]
        own = _nation(person, entities)
        for k in p.get("feeds", []):
            if k not in feeds:
                out.append(f"card {person}: feed {k} is not declared")
        for lv in p.get("levers", []):
            where = f"card {person}: lever {lv['name']}"
            if lv["pipeline"] not in card.get("pipelines", []):
                out.append(f"{where}: pipeline {lv['pipeline']} is not on the card")
            if lv["resolver"] != "movement":
                continue
            domains = set()
            for k in _param(lv, "force")["choices"]:
                if k not in forces:
                    out.append(f"{where}: {k} is not a force")
                    continue
                domains.add(forces[k]["domain"])
                if forces[k]["side"] != own:
                    out.append(f"{where}: {k} is not {own}'s force")
            for k in _param(lv, "to")["choices"]:
                if k in kept.get((person, str(lv["name"])), set()):
                    continue
                if k in places:
                    stands = "sea" if places[k].get("port_on") else areas.get(places[k]["within"])
                    land = areas.get(places[k]["within"]) == "land"
                elif k in areas:
                    stands, land = areas[k], areas[k] == "land"
                else:
                    out.append(f"{where}: {k} is not a place or an area")
                    continue
                if domains == {"sea"} and stands != "sea":
                    out.append(f"{where}: a fleet cannot go to {k}")
                if domains == {"land"} and not land:
                    out.append(f"{where}: an army cannot stand at {k}")
    return out


# ---------------------------------------------------------------- the shape


def test_every_feed_is_shaped_as_the_world_file_has_one(part: dict[str, Any]) -> None:
    for f in part["feeds"]:
        FeedDecl.model_validate(f)


def test_every_lever_is_shaped_as_the_world_file_has_one(part: dict[str, Any]) -> None:
    levers = [lv for p in part["cards"] for lv in p.get("levers", [])]
    assert levers
    for lv in levers:
        LeverDecl.model_validate(lv)


def test_the_part_has_no_problems(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    assert problems(part, world, start, fragment) == []


def test_each_card_part_names_a_card_of_today(part: dict[str, Any], world: dict[str, Any]) -> None:
    carded = {c["person"] for c in world["cards"]}
    assert {p["person"] for p in part["cards"]} <= carded
    assert len({p["person"] for p in part["cards"]}) == len(part["cards"])


# ---------------------------------------------------------------- rule 1: the feeds


def test_mussolini_reads_comando_supremo_reports_from_cavallero(
    part: dict[str, Any], world: dict[str, Any]
) -> None:
    feeds = merged_feeds(world, part)
    feed = feeds["comando_supremo_reports"]
    assert feed["author"] == "cavallero"
    assert "comando_supremo_reports" in merged_cards(world, part)["mussolini"]["feeds"]
    assert set(feed["sights"]) >= {"italian_fleet", "italian_army_libya", "italian_army"}


def test_chiang_reads_military_affairs_commission_reports_from_he_yingqin(
    part: dict[str, Any], world: dict[str, Any]
) -> None:
    feed = merged_feeds(world, part)["mac_reports"]
    assert feed["author"] == "he_yingqin"
    assert "mac_reports" in merged_cards(world, part)["chiang"]["feeds"]
    assert set(feed["sights"]) >= {"chinese_army", *CHINA}


def test_the_new_feeds_report_every_three_days_a_day_late_as_a_labelled_default(
    part: dict[str, Any], world: dict[str, Any]
) -> None:
    today = {f["key"] for f in world["feeds"]}
    new = [f for f in part["feeds"] if f["key"] not in today]
    assert {f["key"] for f in new} == {"comando_supremo_reports", "mac_reports"}
    for f in new:
        assert (f["every_days"], f["latency_days"], f["assumed"]) == (3, 1, True), f["key"]


@pytest.mark.parametrize("key", ["admiralty_reports", "okw_situation"])
def test_the_admiralty_and_okw_reports_gain_the_mediterranean_forces_and_keep_the_rest(
    key: str, part: dict[str, Any], world: dict[str, Any]
) -> None:
    old = next(f for f in world["feeds"] if f["key"] == key)
    new = next(f for f in part["feeds"] if f["key"] == key)
    assert set(new["sights"]) == set(old["sights"]) | set(MEDITERRANEAN)
    assert new["sights"][: len(old["sights"])] == old["sights"]
    assert {k: v for k, v in new.items() if k != "sights"} == {
        k: v for k, v in old.items() if k != "sights"
    }


def test_every_seated_nation_sees_its_own_new_forces(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any]
) -> None:
    entities = _entities(world, start)
    feeds = merged_feeds(world, part)
    forces = _forces(world, start)
    seen: dict[str, set[str]] = {}
    for c in merged_cards(world, part).values():
        if not c.get("playable"):
            continue
        own = _nation(str(c["person"]), entities)
        assert own is not None
        for k in c.get("feeds", []):
            seen.setdefault(own, set()).update(feeds[k].get("sights", []))
    for key in (*MEDITERRANEAN, "ninth_war_area", "italian_army", "chinese_army"):
        side = str(forces[key]["side"])
        assert key in seen.get(side, set()), f"{side} does not see its own {key}"


def test_chiangs_feed_sights_no_italian_piece(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any]
) -> None:
    feeds = merged_feeds(world, part)
    forces = _forces(world, start)
    chiang = merged_cards(world, part)["chiang"]
    for k in chiang["feeds"]:
        for s in feeds[k].get("sights", []):
            assert forces.get(s, {}).get("side") != "italy", (k, s)


# ---------------------------------------------------------------- rule 2: the move forms


def _lever(cards: dict[str, dict[str, Any]], person: str, name: str) -> dict[str, Any]:
    return next(lv for lv in cards[person]["levers"] if lv["name"] == name)


def test_mussolini_moves_the_fleet_and_the_armies_through_the_comando_supremo(
    part: dict[str, Any], world: dict[str, Any]
) -> None:
    cards = merged_cards(world, part)
    fleet = _lever(cards, "mussolini", "move_fleet")
    army = _lever(cards, "mussolini", "move_army")
    for lv in (fleet, army):
        assert (lv["pipeline"], lv["resolver"]) == ("comando_supremo_order", "movement")
    assert _param(fleet, "force")["choices"] == ["italian_fleet"]
    assert set(_param(army, "force")["choices"]) == {"italian_army", "italian_army_libya"}


def test_chiang_moves_his_armies_through_the_military_affairs_commission(
    part: dict[str, Any], world: dict[str, Any]
) -> None:
    army = _lever(merged_cards(world, part), "chiang", "move_army")
    assert (army["pipeline"], army["resolver"]) == ("mac_order", "movement")
    assert set(_param(army, "force")["choices"]) == {"chinese_army", "ninth_war_area"}


@pytest.mark.parametrize(
    ("person", "lever", "added"),
    [
        ("churchill", "move_fleet", "mediterranean_fleet"),
        ("churchill", "detach_fleet", "mediterranean_fleet"),
        ("churchill", "move_army", "western_desert_force"),
        ("hitler", "move_army", "afrika_korps"),
    ],
)
def test_churchills_and_hitlers_move_forms_gain_their_mediterranean_forces_and_keep_the_rest(
    person: str, lever: str, added: str, part: dict[str, Any], world: dict[str, Any]
) -> None:
    old = _lever({str(c["person"]): c for c in world["cards"]}, person, lever)
    new = _lever(merged_cards(world, part), person, lever)
    assert (new["pipeline"], new["resolver"]) == (old["pipeline"], old["resolver"])
    old_params = {p["name"]: p for p in old["params"]}
    new_params = {p["name"]: p for p in new["params"]}
    assert new_params.keys() == old_params.keys()
    for name, p in old_params.items():
        q = new_params[name]
        for field in ("choices", "choice_labels"):
            was = p.get(field, [])
            assert q.get(field, [])[: len(was)] == was, (name, field)
        assert {k: v for k, v in q.items() if k not in ("choices", "choice_labels", "label")} == {
            k: v for k, v in p.items() if k not in ("choices", "choice_labels", "label")
        }, name
    assert added in new_params["force"]["choices"]


def test_hitlers_army_form_stays_on_the_army_path(
    part: dict[str, Any], world: dict[str, Any]
) -> None:
    army = _lever(merged_cards(world, part), "hitler", "move_army")
    assert army["pipeline"] == "okw_army_directive"


def test_no_other_card_changes_and_no_other_lever_is_touched(
    part: dict[str, Any], world: dict[str, Any]
) -> None:
    today = {str(c["person"]): c for c in world["cards"]}
    merged = merged_cards(world, part)
    touched = {str(p["person"]) for p in part["cards"]}
    assert touched == {"churchill", "hitler", "mussolini", "chiang"}
    for person, card in today.items():
        if person not in touched:
            assert merged[person] == card, person
            continue
        named = {lv["name"] for p in part["cards"] if p["person"] == person for lv in p["levers"]}
        for lv in card.get("levers", []):
            if lv["name"] not in named:
                assert lv in merged[person]["levers"], (person, lv["name"])
        for lv in merged[person]["levers"]:
            if lv["name"] in named:
                assert lv["resolver"] == "movement", (person, lv["name"])


def test_every_seat_with_a_new_force_has_a_form_that_moves_it(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any]
) -> None:
    entities = _entities(world, start)
    forces = _forces(world, start)
    offered: dict[str, set[str]] = {}
    for c in merged_cards(world, part).values():
        own = _nation(str(c["person"]), entities)
        for lv in _movement(c):
            offered.setdefault(str(own), set()).update(_param(lv, "force")["choices"])
    for key in (*MEDITERRANEAN, "ninth_war_area", "italian_army", "chinese_army"):
        assert key in offered.get(str(forces[key]["side"]), set()), key


# ---------------------------------------------------------------- the checker bites


def _mutated(part: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(part)


def test_a_feed_no_card_holds_is_a_problem(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    bad = _mutated(part)
    for p in bad["cards"]:
        if p["person"] == "chiang":
            p["feeds"] = []
    assert "feed mac_reports: no card holds it" in problems(bad, world, start, fragment)


def test_a_move_form_offering_an_enemy_force_is_a_problem(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    bad = _mutated(part)
    p = next(p for p in bad["cards"] if p["person"] == "churchill")
    lv = next(lv for lv in p["levers"] if lv["name"] == "move_army")
    _param(lv, "force")["choices"].append("afrika_korps")
    _param(lv, "force")["choice_labels"].append("The Afrika Korps")
    found = problems(bad, world, start, fragment)
    assert "card churchill: lever move_army: afrika_korps is not uk's force" in found


def test_a_feed_sighting_a_force_its_author_would_not_see_is_a_problem(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    bad = _mutated(part)
    feed = next(f for f in bad["feeds"] if f["key"] == "mac_reports")
    feed["sights"].append("italian_fleet")
    assert "feed mac_reports: china would not see italian_fleet" in problems(
        bad, world, start, fragment
    )


def test_a_fleet_sent_inland_is_a_problem(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    bad = _mutated(part)
    p = next(p for p in bad["cards"] if p["person"] == "mussolini")
    lv = next(lv for lv in p["levers"] if lv["name"] == "move_fleet")
    _param(lv, "to")["choices"].append("rome")
    _param(lv, "to")["choice_labels"].append("Rome")
    found = problems(bad, world, start, fragment)
    assert "card mussolini: lever move_fleet: a fleet cannot go to rome" in found


def test_an_army_sent_to_sea_is_a_problem(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    bad = _mutated(part)
    p = next(p for p in bad["cards"] if p["person"] == "chiang")
    lv = next(lv for lv in p["levers"] if lv["name"] == "move_army")
    _param(lv, "to")["choices"].append("east_china_sea")
    _param(lv, "to")["choice_labels"].append("The East China Sea")
    found = problems(bad, world, start, fragment)
    assert "card chiang: lever move_army: an army cannot stand at east_china_sea" in found


def test_a_form_on_a_path_the_card_does_not_have_is_a_problem(
    part: dict[str, Any], world: dict[str, Any], start: dict[str, Any], fragment: dict[str, Any]
) -> None:
    bad = _mutated(part)
    p = next(p for p in bad["cards"] if p["person"] == "chiang")
    p["levers"][0]["pipeline"] = "comando_supremo_order"
    found = problems(bad, world, start, fragment)
    assert any("pipeline comando_supremo_order is not on the card" in x for x in found)
