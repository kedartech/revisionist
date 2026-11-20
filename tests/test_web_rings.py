"""An old report widens into a ring (RNG).

The toy world (``tests/worlds/territory-toy.yaml``) is played as detection's tests play it
(``tests/test_detection.py``): ``territories`` and ``reports`` on, every force given a
strength. Norra holds the Norra Hills and the Norra Plain; Sudland the Sudland Coast and
the Isle. On day 1 Norra's levy and kites, on the plain, see the Sudland galleys in the
bordering Gulf; no one is named for contact, so the report reaches Ilse at once, and no
later day is walked, so it grows older. A galley takes 2 days into shallows and 3 into
deep water; a levy 5 into a plain and 7 into hills.
"""

from datetime import date
from pathlib import Path
from typing import Any

from revisionist.core.ids import EntityId
from revisionist.core.project import project
from revisionist.core.realism import detect
from revisionist.core.realism.detect import Confidence, Report, Source
from revisionist.core.state import State, View
from revisionist.engine.web import map_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests.test_adjacency_moves import Logged, World, day, entity, seat
from tests.test_detection import NORRA, fid, game, on, place, rules, with_feature

GALLEYS = "sudland_galleys"


def block(state: State, who: str = "ilse") -> dict[str, Any]:
    return rs.seat_realism(state, seat(who), set(), set(), None)


def sent_key(state: State, piece: str, who: str = "ilse") -> str:
    nation = entity(NORRA) if who == "ilse" else entity("sudland")
    return map_api.mark_key(state.campaign_id, nation, detect.report_key(state, nation, fid(piece)))


def report(state: State, piece: str = GALLEYS) -> dict[str, Any]:
    key = sent_key(state, piece)
    (r,) = [r for r in block(state)["map"]["reports"] if r["key"] == key]
    return dict(r)


def areas(state: State, who: str = "ilse") -> dict[str, dict[str, Any]]:
    return {a["key"]: a for a in block(state, who)["map"]["areas"]}


def seen_on_day_one(tmp: Path, *more: Any) -> Logged:
    g = game(tmp, *more)
    g.walk(day(1), day(1))
    return g


def isle_to_norra(w: World) -> None:
    """The Isle, which borders only the Open Sea and (by the ferry) the Norra Plain, is
    Norra's."""
    (isle,) = [t for t in w["territories"] if t["key"] == "isle"]
    isle["holder"] = "norra"


def riders(w: World) -> None:
    """A second land kind, faster than the levy everywhere."""
    w["piece_kinds"].append(
        {
            "key": "rider",
            "name": "Rider",
            "domain": "land",
            "days_per_step": {"hills": 2, "plain": 1},
        }
    )


def crafted(g: Logged, when: date, *reports: Report) -> View:
    """Ilse's view on ``when`` holding exactly ``reports``."""
    on(g, when)
    view = project(g.state, seat("ilse"))
    return view.model_copy(update={"reports": {r.key: r for r in reports}})


def unnamed(key: str, kind: str | None, area: str, seen: date) -> Report:
    """A report no person is named for (sent with no paper)."""
    return Report(
        key=key,
        kind=kind,
        strength=(1, 2),
        area=EntityId(entity(area)),
        seen=seen,
        source=Source.CONTACT,
        rank=0,
        confidence=Confidence.B,
        arrives=seen,
    )


def ring_of(view: View, key: str) -> list[str] | None:
    (r,) = [r for r in rs.map_reports(view) if r["key"] == key]
    return r["ring"]


# --- Rule 1: a report more than a day old carries its ring ---------------------------------


def test_a_fresh_report_has_no_ring(tmp_path: Path) -> None:
    g = seen_on_day_one(tmp_path)
    for n in (1, 2):
        on(g, day(n))
        assert report(g.state)["ring"] is None, f"day {n}"


def test_a_report_more_than_a_day_old_rings_every_area_its_kind_could_have_reached(
    tmp_path: Path,
) -> None:
    g = seen_on_day_one(tmp_path)
    on(g, day(3))
    assert rs.RING_AFTER_DAYS == 1
    assert report(g.state)["ring"] == ["the_gulf"]
    on(g, day(4))
    assert report(g.state)["ring"] == ["the_gulf", "open_sea"]


def test_a_decrypt_which_gives_no_area_has_no_ring(tmp_path: Path) -> None:
    g = seen_on_day_one(tmp_path)
    decrypt = unnamed("decrypt", "galley", "the_gulf", day(1)).model_copy(
        update={"area": None, "region": "waters"}
    )
    assert ring_of(crafted(g, day(9), decrypt), "decrypt") is None


def test_a_land_ring_never_crosses_water(tmp_path: Path) -> None:
    """A levy on the Sudland Coast could be lifted over the Gulf to the Norra Plain in
    far fewer days; the ring counts land steps only (``territory.steps_within`` reads no
    lift), so the plain is in it only after the hills and the plain on foot."""
    g = seen_on_day_one(tmp_path)
    levy = unnamed("levy", "levy", "sudland_coast", day(1))
    assert ring_of(crafted(g, day(7), levy), "levy") == ["sudland_coast"]
    assert ring_of(crafted(g, day(12), levy), "levy") == ["norra_hills", "sudland_coast"]
    assert ring_of(crafted(g, day(13), levy), "levy") == [
        "norra_hills",
        "norra_plain",
        "sudland_coast",
    ]


# --- Rule 2: a report of unknown kind uses the fastest kind of the area's domain -----------


def test_an_unknown_piece_on_land_rings_as_the_fastest_land_kind(tmp_path: Path) -> None:
    g = seen_on_day_one(tmp_path, riders)
    unknown = unnamed("unknown", None, "sudland_coast", day(1))
    assert ring_of(crafted(g, day(4), unknown), "unknown") == [
        "norra_hills",
        "norra_plain",
        "sudland_coast",
    ]


def test_an_unknown_piece_at_sea_rings_as_a_sea_kind_not_an_air_one(tmp_path: Path) -> None:
    """The Kite Wing crosses any area in a day; it is no sea kind, so it sets no sea ring."""
    g = seen_on_day_one(tmp_path)
    unknown = unnamed("unknown", None, "the_gulf", day(1))
    assert ring_of(crafted(g, day(3), unknown), "unknown") == ["the_gulf"]
    assert ring_of(crafted(g, day(4), unknown), "unknown") == ["the_gulf", "open_sea"]


# --- Rule 3: each of the seat's own areas names the reports next to it ---------------------


def test_an_own_area_bordering_a_reports_area_is_threatened_from_it(tmp_path: Path) -> None:
    g = seen_on_day_one(tmp_path, isle_to_norra)
    on(g, day(3))
    key = sent_key(g.state, GALLEYS)
    seen = areas(g.state)
    assert seen["norra_plain"]["threatened_from"] == [key]
    assert seen["norra_hills"]["threatened_from"] == []
    assert seen["isle"]["threatened_from"] == []


def test_an_own_area_bordering_only_the_ring_is_threatened_from_it(tmp_path: Path) -> None:
    """On day 4 the galleys' ring takes in the Open Sea, which borders the Isle."""
    g = seen_on_day_one(tmp_path, isle_to_norra)
    on(g, day(4))
    assert areas(g.state)["isle"]["threatened_from"] == [sent_key(g.state, GALLEYS)]


def test_an_own_area_a_report_stands_in_is_threatened_from_it(tmp_path: Path) -> None:
    g = seen_on_day_one(tmp_path, place("sudland_levy", "norrhavn"))
    on(g, day(1))
    levy = sent_key(g.state, "sudland_levy")
    seen = areas(g.state)
    assert levy in seen["norra_plain"]["threatened_from"]
    assert levy in seen["norra_hills"]["threatened_from"]


def test_only_the_seats_own_areas_carry_threats(tmp_path: Path) -> None:
    g = seen_on_day_one(tmp_path)
    on(g, day(4))
    seen = areas(g.state)
    for key in ("sudland_coast", "isle", "the_gulf", "open_sea"):
        assert seen[key]["threatened_from"] is None, key
    assert seen["norra_plain"]["threatened_from"] == [sent_key(g.state, GALLEYS)]


def test_threats_are_listed_by_key(tmp_path: Path) -> None:
    g = seen_on_day_one(tmp_path, place("sudland_levy", "norrhavn"))
    on(g, day(1))
    listed = areas(g.state)["norra_plain"]["threatened_from"]
    assert listed == sorted(listed) and len(listed) == 2


def test_a_game_without_reports_carries_no_threats(tmp_path: Path) -> None:
    g = seen_on_day_one(tmp_path, rules("territories"))
    on(g, day(4))
    assert all(a["threatened_from"] is None for a in areas(g.state).values())


# --- Rule 4: moving the true piece changes no ring -----------------------------------------


def test_moving_the_true_piece_changes_no_ring_and_no_threat(tmp_path: Path) -> None:
    g = seen_on_day_one(tmp_path, isle_to_norra)
    on(g, day(4))
    before = block(g.state)["map"]
    galleys = g.state.features[fid(GALLEYS)]
    for where in ("open_sea", "sudland_coast"):
        moved = with_feature(g.state, GALLEYS, places=[entity(where)])
        assert moved.features[fid(GALLEYS)].places != galleys.places
        assert block(moved)["map"] == before, where


# --- the seat fixture -----------------------------------------------------------------------


def test_the_snapshot_shape_declares_the_ring_and_the_threats() -> None:
    assert "ring" in api.MapReport.__annotations__
    assert "threatened_from" in api.MapArea.__annotations__
