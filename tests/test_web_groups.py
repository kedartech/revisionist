"""Groups and the floor as the seat sees them (GPD).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``groups`` on, as
GVR's tests play it: Norra's assembly has two blocs of a hundred seats, the Greens and the
Greys, and Norra has two themes. Ilse sits for Norra, Tomas for Sudland, whose one group,
the Farmers, feeds no standing.

With ``groups`` on, the seat's ``home`` block lists its own nation's groups (support, what
last moved it and when, what it feeds), each chamber's blocs with their seats and, for each
measure the seat has open, the count by bloc as the votes rule would tally it today, the
nation's themes, every nation's standing as a public band and the seat's own as a figure.
No other nation's group reaches any payload.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import OrderId, PipelineId, derived_id
from revisionist.core.realism import groups
from revisionist.core.realism.groups import Cause
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers import votes
from revisionist.core.world_compile import object_id
from revisionist.engine.web import home_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests.test_adjacency_moves import START, Logged, entity, seat, toy
from tests.test_free_writing_groups import THEMES
from tests.test_territory_model import CAMPAIGN
from tests.test_votes_from_groups import hundred

World = dict[str, Any]
FIXTURES = Path(__file__).parents[1] / "web" / "test" / "fixtures"
NORRA, SUDLAND = entity("norra"), entity("sudland")
ASSEMBLY = "assembly"
NORRA_KEYS: tuple[str, ...] = ("smiths", "greens", "greys", "The Smiths' Guild", "The Greens")
NORRA_KEYS += ("The Greys", "The Norra Public", "Bread for All", "The Levy Act")


def floor(w: World) -> None:
    """Groups on, Norra's themes, both blocs at a hundred seats, and a ``pass_act`` lever
    on Ilse's card that the votes rule tallies, through a one-step floor pipeline."""
    w["rules"] = ["territories", "holders", "economy", "groups"]
    hundred(w)
    next(d for d in w["groups"] if d["nation"] == "norra")["themes"] = THEMES
    w["pipelines"] = [
        {
            "key": "floor",
            "name": "The floor",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        }
    ]
    card = next(c for c in w["cards"] if c["person"] == "ilse")
    card["pipelines"] = ["floor"]
    card["levers"] = [
        {
            "name": "pass_act",
            "pipeline": "floor",
            "resolver": "votes",
            "params": [
                {"name": "bill", "kind": "enum", "choices": ["levy_act", "harbour_act"]},
                {"name": "urgency", "kind": "enum", "choices": ["routine", "urgent"]},
            ],
        }
    ]


def game(tmp: Path, *changes: Callable[[World], None]) -> Logged:
    return Logged(toy(tmp, floor, *changes), "ilse", "tomas")


def off(w: World) -> None:
    w["rules"] = ["territories", "holders", "economy"]


def bill(g: Logged, key: str, n: int = 1, urgency: str = "routine") -> OrderId:
    """Ilse sends ``key`` to the floor: an open order at its first step."""
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "gpd-order", n)),
        issuer=seat("ilse"),
        lever="pass_act",
        pipeline=PipelineId(object_id(CAMPAIGN, "pipeline", "floor")),
        params={"bill": key, "urgency": urgency},
        filed=START,
    )
    g.add([ev.OrderDrafted(order=order)])
    return order.order_id


def moved(g: Logged, key: str, change: int, cause: Cause, on: date, polity: Any = NORRA) -> None:
    g.add([groups.shift(g.state, polity, key, change, cause, on)])


def realism(g: Logged, who: str = "ilse") -> dict[str, Any]:
    return rs.seat_realism(g.state, seat(who), set(), set(), None, events=g.log)


def home(g: Logged, who: str = "ilse") -> dict[str, Any]:
    out = realism(g, who)["home"]
    assert out is not None
    return dict(out)


def by_key(items: list[dict[str, Any]], field: str = "key") -> dict[str, dict[str, Any]]:
    return {i[field]: i for i in items}


def fixture_game(tmp: Path) -> Logged:
    """The game the seat fixture's ``home`` is Ilse's block of: the Greens up five after a
    battle won on the first day, the Public down two on the third from a territory lost,
    and the levy act open on the floor."""
    g = game(tmp)
    moved(g, "greens", 5, Cause.BATTLE_WON, START)
    moved(g, "public", -2, Cause.TERRITORY_LOST, date(1900, 4, 4))
    bill(g, "levy_act")
    return g


# --- Rule 1: the seat's own nation's groups -------------------------------------------


def test_home_lists_the_seats_own_groups_with_support_and_what_they_feed(
    tmp_path: Path,
) -> None:
    shown = home(fixture_game(tmp_path))
    assert [g["key"] for g in shown["groups"]] == ["smiths", "greens", "greys", "public"]
    greens = by_key(shown["groups"])["greens"]
    assert (greens["name"], greens["kind"], greens["support"]) == ("The Greens", "party", 60)
    assert greens["feeds"] == {"votes": 1, "standing": 1}
    assert by_key(shown["groups"])["public"]["support"] == 38
    assert by_key(shown["groups"])["smiths"]["feeds"] == {"output": 1, "manpower": 1}
    assert shown["nation"] == {"key": NORRA, "name": "Norra", "relation": "own"}


def test_each_group_names_what_last_moved_it_and_when(tmp_path: Path) -> None:
    g = fixture_game(tmp_path)
    shown = by_key(home(g)["groups"])
    assert shown["greens"]["last_moved"] == {
        "cause": "battle_won",
        "change": 5,
        "on": START.isoformat(),
    }
    assert shown["public"]["last_moved"] == {
        "cause": "territory_lost",
        "change": -2,
        "on": "1900-04-04",
    }
    assert shown["smiths"]["last_moved"] is None
    moved(g, "greens", -1, Cause.DRIFT, date(1900, 4, 9))
    assert by_key(home(g)["groups"])["greens"]["last_moved"] == {
        "cause": "drift",
        "change": -1,
        "on": "1900-04-09",
    }


def test_a_move_the_clamp_held_to_nothing_is_not_what_last_moved_a_group(
    tmp_path: Path,
) -> None:
    g = fixture_game(tmp_path)
    moved(g, "greens", 40, Cause.WRITING, date(1900, 4, 5))
    moved(g, "greens", 3, Cause.WAR_DECLARED, date(1900, 4, 6))  # at 100 already
    assert by_key(home(g)["groups"])["greens"]["last_moved"] == {
        "cause": "writing",
        "change": 40,
        "on": "1900-04-05",
    }


# --- Rule 2: each chamber's blocs, and the count by bloc of an open measure -----------


def test_each_chamber_lists_its_blocs_with_their_seats_and_support(tmp_path: Path) -> None:
    (chamber,) = home(fixture_game(tmp_path))["chambers"]
    assert chamber["key"] == ASSEMBLY
    assert chamber["blocs"] == [
        {"group": "greens", "name": "The Greens", "seats": 100, "support": 60},
        {"group": "greys", "name": "The Greys", "seats": 100, "support": 30},
    ]


def test_an_open_measure_is_counted_by_bloc_as_the_votes_rule_tallies_it_today(
    tmp_path: Path,
) -> None:
    g = fixture_game(tmp_path)
    order_id = next(iter(g.state.orders))
    (measure,) = home(g)["chambers"][0]["measures"]
    assert (measure["order_id"], measure["key"], measure["title"]) == (
        order_id,
        "levy_act",
        "Levy act",
    )
    (vote,) = measure["votes"]
    # The Greens five points over their baseline: one point of yes share on a hundred.
    assert vote["blocs"] == [
        {"group": "greens", "yeas": 71, "nays": 29},
        {"group": "greys", "yeas": 20, "nays": 80},
    ]
    assert (vote["vote"], vote["yeas"], vote["nays"]) == (ASSEMBLY, 91, 109)
    tallied = votes.bloc_tally(g.state, NORRA, ASSEMBLY, "levy_act", ASSEMBLY, order_id)
    assert (vote["yeas"], vote["nays"]) == tallied


def test_the_count_moves_with_support_and_reads_urgency(tmp_path: Path) -> None:
    g = fixture_game(tmp_path)
    moved(g, "greys", 25, Cause.WRITING, START)
    urgent = bill(g, "harbour_act", n=2, urgency="urgent")
    measures = by_key(home(g)["chambers"][0]["measures"])
    assert by_key(measures["levy_act"]["votes"][0]["blocs"], "group")["greys"]["yeas"] == 25
    # harbour act: no bloc lists it, so the default rows; the Greens back power, so urgent
    # adds two points to their yes share.
    harbour = by_key(measures["harbour_act"]["votes"][0]["blocs"], "group")
    tallied = votes.bloc_tally(
        g.state, NORRA, ASSEMBLY, "harbour_act", ASSEMBLY, urgent, urgent=True
    )
    assert harbour["greens"]["yeas"] + harbour["greys"]["yeas"] == tallied[0]
    assert harbour["greens"]["yeas"] == 53


def test_a_settled_measure_is_not_open(tmp_path: Path) -> None:
    g = fixture_game(tmp_path)
    order_id = next(iter(g.state.orders))
    g.add([ev.OrderSettled(order_id=order_id, status=OrderStatus.WITHDRAWN)])
    assert home(g)["chambers"][0]["measures"] == []


# --- Rule 3: the nation's themes ------------------------------------------------------


def test_home_lists_the_nations_themes_and_the_groups_each_speaks_to(tmp_path: Path) -> None:
    shown = home(fixture_game(tmp_path))
    assert shown["themes"] == [
        {"key": "bread", "name": "Bread for All", "moves": {"public": 2, "smiths": -1}},
        {"key": "levy", "name": "The Levy Act", "moves": {"greens": 1}},
    ]
    assert home(fixture_game(tmp_path), "tomas")["themes"] == []


# --- Rule 4: every nation's standing as a band, the seat's own as a figure -------------


def test_every_nation_has_a_public_band_and_the_seat_its_own_figure(tmp_path: Path) -> None:
    g = fixture_game(tmp_path)
    figure = groups.home_standing(g.state, NORRA)
    assert figure == 43.5  # (60 + 3 * 38) / 4
    mine, theirs = home(g), home(g, "tomas")
    assert mine["standing"] == figure
    assert theirs["standing"] is None  # the Farmers feed no standing
    for shown in (mine, theirs):
        assert {s["nation"]["key"]: s["band"] for s in shown["standings"]} == {
            NORRA: "steady",
            SUDLAND: None,
        }


@pytest.mark.parametrize(
    ("figure", "band"),
    [
        (0, "collapsing"),
        (19.9, "collapsing"),
        (20, "shaken"),
        (39.9, "shaken"),
        (40, "steady"),
        (60, "firm"),
        (79.9, "firm"),
        (80, "united"),
        (100, "united"),
    ],
)
def test_the_five_bands(figure: float, band: str) -> None:
    assert home_api.standing_band(figure) == band


def test_the_band_follows_the_standing(tmp_path: Path) -> None:
    g = fixture_game(tmp_path)
    moved(g, "public", 50, Cause.WRITING, START)
    moved(g, "greens", 40, Cause.WRITING, START)
    assert groups.home_standing(g.state, NORRA) == 91.0
    standings = home(g, "tomas")["standings"]
    assert {s["nation"]["key"]: s["band"] for s in standings}[NORRA] == "united"


# --- The fog: no other nation's group in any payload ----------------------------------


def test_no_other_nations_group_reaches_the_seat(tmp_path: Path) -> None:
    g = fixture_game(tmp_path)
    moved(g, "farmers", 7, Cause.BATTLE_WON, date(1900, 4, 5), polity=SUDLAND)
    mine, theirs = json.dumps(realism(g, "ilse")), json.dumps(realism(g, "tomas"))
    for secret in NORRA_KEYS:
        assert secret in mine
        assert secret not in theirs
    assert '"standing": 43.5' in mine and "43.5" not in theirs
    for secret in ("farmers", "The Farmers"):
        assert secret in theirs
        assert secret not in mine
    assert by_key(home(g, "tomas")["groups"])["farmers"]["support"] == 37


# --- Off, and the shapes ----------------------------------------------------------------


def test_without_groups_there_is_no_home_block(tmp_path: Path) -> None:
    assert realism(game(tmp_path, off))["home"] is None


def shape(examples: list[Any], kind: Any) -> None:
    assert examples
    for example in examples:
        assert set(example) == set(kind.__annotations__), kind.__name__


def test_the_seat_fixture_carries_the_home_block_in_the_snapshot_shape(tmp_path: Path) -> None:
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["home"]
    priced = {"offers", "promises"}  # with offers on: tests/test_web_offers.py, its own game
    assert {k: v for k, v in fixture.items() if k not in priced} == home(fixture_game(tmp_path))
    shape([fixture], api.HomeBlock)
    shape(fixture["groups"], api.HomeGroup)
    shape([g["last_moved"] for g in fixture["groups"] if g["last_moved"]], api.GroupMove)
    shape(fixture["chambers"], api.FloorChamber)
    shape(fixture["chambers"][0]["blocs"], api.FloorBloc)
    shape(fixture["chambers"][0]["measures"], api.OpenMeasure)
    shape(fixture["chambers"][0]["measures"][0]["votes"], api.FloorVote)
    shape(fixture["chambers"][0]["measures"][0]["votes"][0]["blocs"], api.BlocCount)
    shape(fixture["themes"], api.HomeTheme)
    shape(fixture["standings"], api.NationStanding)
