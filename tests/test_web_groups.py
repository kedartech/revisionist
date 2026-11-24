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
        {"group": "greens", "yeas": 71, "nays": 29, "then": None, "moved": False},
        {"group": "greys", "yeas": 20, "nays": 80, "then": None, "moved": False},
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
    from tests.test_places_weight import game as places_game

    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["home"]
    priced = {"offers", "promises"}  # with offers on: tests/test_web_offers.py, its own game
    weighed = {"places"}  # with places of weight: tests/test_places_weight.py, its own game
    asked = {
        "office",
        "turning",
        "footing",
        "results",
        "elections",
    }  # test_web_office.py, its games
    ours = {k: v for k, v in fixture.items() if k not in priced | weighed | asked}
    assert ours == {k: v for k, v in home(fixture_game(tmp_path)).items() if k not in weighed}
    (tmp_path / "places").mkdir()
    assert fixture["places"] == home(places_game(tmp_path / "places"))["places"] != []
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
    shape(fixture["moved"], api.HomeMoved)
    shape(fixture["places"], api.HomePlace)
    shape([m for g in fixture["groups"] for m in g["since"]], api.HomeMove)


# --- A capital's live questions, as the seat may know them --------------------------------


def sent_to(state: Any, who: Any, log: list[Any]) -> dict[str, Any]:
    return rs.seat_realism(state, who, set(), set(), None, events=log)


def capital(sent: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """The questions of the nation ``name`` in the seat's ``capitals``."""
    (found,) = [c for c in sent["capitals"] if c["nation"]["name"] == name]
    return list(found["questions"])


REFS = {
    "home.chambers": lambda s: [
        m["order_id"] for c in s["home"]["chambers"] for m in c["measures"]
    ],
    "home.offers": lambda s: [o["key"] for o in s["home"]["offers"]],
    "home.office": lambda s: [q["question_id"] for q in s["home"]["office"]],
    "home.elections": lambda s: [e["day"] for e in s["home"]["elections"]],
    "locks.asks": lambda s: [a["id"] for a in s["locks"]["asks"]],
    "locks.held": lambda s: [h["id"] for h in s["locks"]["held"]],
    "agreements.offers": lambda s: [o["item"] for o in s["agreements"]["offers"]],
    "agreements.agreements": lambda s: [a["id"] for a in s["agreements"]["agreements"]],
    "conferences.conferences": lambda s: [c["key"] for c in s["conferences"]["conferences"]],
}


def points_home(sent: dict[str, Any], log: list[Any]) -> None:
    """Rule 4: each line points at data the seat is already sent, or, for a sitting's
    result, at the public news of it in the log."""
    decided = {
        e.payload.question_id
        for e in log
        if isinstance(e.payload, ev.OfficeQuestionDecided) and e.scope.visibility.value == "public"
    }
    for line in sent["capitals"]:
        for q in line["questions"]:
            assert set(q) == set(api.CapitalQuestion.__annotations__)
            assert set(q["decider"]) == set(api.CapitalDecider.__annotations__)
            if q["at"] == "news":
                assert q["ref"] in decided, q
            else:
                assert q["ref"] in REFS[q["at"]](sent), q


def test_the_seats_own_capital_comes_first_and_lists_a_measure_before_its_chamber(
    tmp_path: Path,
) -> None:
    g = fixture_game(tmp_path)
    sent = realism(g)
    own, other = sent["capitals"]
    assert own["nation"]["relation"] == "own" and own["nation"]["name"] == "Norra"
    assert other["nation"]["name"] == "Sudland"
    (q,) = own["questions"]
    assert (q["kind"], q["title"], q["day"], q["at"]) == (
        "measure",
        "Levy act",
        None,
        "home.chambers",
    )
    assert q["decider"] == {
        "shape": "body",
        "who": "assembly",
        "members": ["The Greens", "The Greys"],
    }
    assert other["questions"] == []
    points_home(sent, g.log)


def test_another_nations_measure_is_not_in_its_capital(tmp_path: Path) -> None:
    g = fixture_game(tmp_path)
    assert capital(realism(g, "tomas"), "Norra") == []


def office_game(tmp: Path, *changes: Callable[[World], None]) -> Any:
    from tests.test_blocs_turn import greens_at
    from tests.test_web_office import built

    g = built(tmp, *changes, greens_at(60))
    g.ask()
    return g


@pytest.mark.parametrize(
    ("way", "shape", "who", "members"),
    [
        ({"by": "vote", "chamber": "assembly"}, "body", "assembly", ["The Greens", "The Greys"]),
        (
            {"by": "council", "members": ["ilse", "kara"], "needed": 1},
            "council",
            "the council",
            ["Ilse Varg", "Kara Lind"],
        ),
        ({"by": "person", "person": "ilse"}, "person", "Ilse Varg", ["Ilse Varg"]),
    ],
)
def test_an_office_sitting_says_the_shape_of_who_decides_it(
    tmp_path: Path, way: dict[str, Any], shape: str, who: str, members: list[str]
) -> None:
    from tests.test_office_question import office_on
    from tests.test_posts import ILSE

    g = office_game(tmp_path, office_on(way))
    log = list(g.store.read(CAMPAIGN))
    sent = sent_to(g.state, seat_of_(g, ILSE), log)
    (q,) = [q for q in capital(sent, "Norra") if q["kind"] == "office"]
    (line,) = sent["home"]["office"]
    assert (q["title"], q["day"], q["at"], q["ref"]) == (
        line["office"],
        line["sits"],
        "home.office",
        line["question_id"],
    )
    assert (q["decider"]["shape"], q["decider"]["who"], q["decider"]["members"]) == (
        shape,
        who,
        members,
    )
    points_home(sent, log)


def seat_of_(g: Any, who: Any) -> Any:
    from tests.test_office_question import seat_of

    return seat_of(g.state, who)


def test_an_election_ahead_is_listed_before_its_chambers(tmp_path: Path) -> None:
    from tests.test_elections import DAY, support, with_post
    from tests.test_posts import ILSE
    from tests.test_web_office import built

    g = built(tmp_path, support(80, 10), with_post)
    log = list(g.store.read(CAMPAIGN))
    sent = sent_to(g.state, seat_of_(g, ILSE), log)
    (q,) = [q for q in capital(sent, "Norra") if q["kind"] == "election"]
    assert (q["day"], q["at"], q["ref"]) == (DAY.isoformat(), "home.elections", DAY.isoformat())
    assert q["decider"] == {"shape": "body", "who": "assembly", "members": ["assembly"]}
    points_home(sent, log)


def test_a_foreign_capital_lists_a_sittings_result_once_it_is_news(tmp_path: Path) -> None:
    from tests.test_office_question import BY_PERSON, office_on
    from tests.test_posts import ILSE, TOMAS

    g = office_game(tmp_path, office_on(BY_PERSON))
    log = list(g.store.read(CAMPAIGN))
    assert capital(sent_to(g.state, seat_of_(g, TOMAS), log), "Norra") == []
    g.choose(ILSE, False)
    g.until_decided()
    log = list(g.store.read(CAMPAIGN))
    sent = sent_to(g.state, seat_of_(g, TOMAS), log)
    (q,) = capital(sent, "Norra")
    assert (q["kind"], q["at"], q["title"]) == ("result", "news", "General of the Norra Levy")
    assert q["decider"] == {"shape": "person", "who": "Ilse Varg", "members": ["Ilse Varg"]}
    points_home(sent, log)
    assert capital(sent, "Sudland") == []


def test_a_foreign_capital_is_the_same_whatever_its_private_questions(tmp_path: Path) -> None:
    """The fog: twin games, one with an office question open on Norra's command, read the
    same to Sudland's seat, byte for byte, in Norra's capital and in its whole list."""
    from tests.test_blocs_turn import greens_at
    from tests.test_office_question import BY_PERSON, office_on
    from tests.test_posts import ILSE, TOMAS
    from tests.test_web_office import built

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    plain = built(tmp_path / "a", office_on(BY_PERSON), greens_at(60))
    asked = office_game(tmp_path / "b", office_on(BY_PERSON))
    sent = [
        sent_to(g.state, seat_of_(g, TOMAS), list(g.store.read(CAMPAIGN))) for g in (plain, asked)
    ]
    assert json.dumps(sent[0]["capitals"]) == json.dumps(sent[1]["capitals"])
    mine = sent_to(asked.state, seat_of_(asked, ILSE), list(asked.store.read(CAMPAIGN)))
    assert [q["kind"] for q in capital(mine, "Norra")] == ["office"]


def test_a_peace_before_the_seat_is_listed_with_who_may_accept_it(tmp_path: Path) -> None:
    from tests import test_peace as tp
    from tests.test_agreements import ILSE, TOMAS
    from tests.test_web_agreements import offered

    g = tp.game(tmp_path)
    offered(g)
    sent = sent_to(g.state, TOMAS, g.log)
    (q,) = capital(sent, "Sudland")
    (line,) = sent["agreements"]["offers"]
    assert (q["kind"], q["at"], q["ref"], q["day"]) == (
        "peace",
        "agreements.offers",
        line["item"],
        line["expires"],
    )
    assert q["title"] == "Peace offered by Norra"
    assert q["decider"] == {"shape": "person", "who": "Tomas Brand", "members": ["Tomas Brand"]}
    points_home(sent, g.log)
    assert capital(sent_to(g.state, ILSE, g.log), "Norra") == []


def test_an_offer_that_carries_no_peace_is_not_a_peace_before_the_seat(tmp_path: Path) -> None:
    from tests import test_peace as tp
    from tests.test_agreements import TOMAS, day, deal, offer
    from tests.test_web_agreements import keep_out

    g = tp.game(tmp_path)
    offer(g, deal(keep_out()))
    g.walk(day(1), day(1))
    sent = sent_to(g.state, TOMAS, g.log)
    assert [o["item"] is not None for o in sent["agreements"]["offers"]] == [True]
    assert capital(sent, "Sudland") == []


def test_a_peace_held_for_a_council_is_listed_before_the_council(tmp_path: Path) -> None:
    from tests import test_peace as tp
    from tests.test_agreements import TOMAS
    from tests.test_web_agreements import offered

    g = tp.game(tmp_path, tp.council(3))
    offered(g)
    (q,) = capital(sent_to(g.state, TOMAS, g.log), "Sudland")
    assert q["decider"] == {
        "shape": "council",
        "who": "the council under Tomas Brand",
        "members": ["Tomas Brand", "Sven Dahl"],
    }


def test_an_ask_before_a_council_and_the_seats_own_held_order_are_listed(tmp_path: Path) -> None:
    from tests import test_peace as tp
    from tests.test_agreements import TOMAS, day

    g = tp.game(tmp_path, tp.council(3))
    _, due = tp.accepted_by_tomas(g)
    g.walk(day(1), due)
    sent = sent_to(g.state, TOMAS, g.log)
    kinds = {q["kind"]: q for q in capital(sent, "Sudland")}
    assert kinds["ask"]["decider"]["shape"] == "council"
    assert kinds["ask"]["at"] == "locks.asks"
    points_home(sent, g.log)


def test_a_foreign_capital_lists_a_published_agreement_and_no_private_one(tmp_path: Path) -> None:
    from tests.test_agreements import ILSE, OLAF, game, in_force
    from tests.test_web_agreements import keep_out

    g = game(tmp_path, rules=("agreements",))
    in_force(g, keep_out())
    private = sent_to(g.state, OLAF, g.log)
    assert capital(private, "Norra") == capital(private, "Sudland") == []
    party = sent_to(g.state, ILSE, g.log)
    assert [a["published"] for a in party["agreements"]["agreements"]] == [None]
    assert capital(party, "Sudland") == []
    x = in_force(g, keep_out(), public=True)
    sent = sent_to(g.state, OLAF, g.log)
    for name in ("Norra", "Sudland"):
        (q,) = capital(sent, name)
        assert (q["kind"], q["ref"], q["at"]) == (
            "agreement",
            x.agreement_id,
            "agreements.agreements",
        )
        assert q["decider"] == {
            "shape": "council",
            "who": "Norra and Sudland",
            "members": ["Norra", "Sudland"],
        }
    points_home(sent, g.log)


def test_a_foreign_capital_lists_a_public_vote_once_reported(tmp_path: Path) -> None:
    from tests.test_conference import NORRA, OSTMARK, TOMAS, game, run_until_tallied

    g = game(tmp_path)
    g.open()
    g.call(invited=(NORRA, OSTMARK), public=True)
    assert capital(sent_to(g.state, TOMAS, g.log), "Ostmark") == []
    run_until_tallied(g)
    sent = sent_to(g.state, TOMAS, g.log)
    (q,) = capital(sent, "Ostmark")
    assert (q["kind"], q["at"]) == ("vote", "conferences.conferences")
    assert q["decider"]["shape"] == "council" and q["decider"]["members"] == ["Norra", "Ostmark"]
    assert capital(sent, "Norra") == [q]
    points_home(sent, g.log)


def test_a_private_vote_is_in_no_foreign_capital_even_for_a_nation_invited(tmp_path: Path) -> None:
    from tests.test_conference import ILSE, NORRA, OSTMARK, game, run_until_tallied

    g = game(tmp_path)
    g.open()
    g.call(invited=(NORRA, OSTMARK))
    run_until_tallied(g)
    sent = sent_to(g.state, ILSE, g.log)
    assert [c["tallied"] is not None for c in sent["conferences"]["conferences"]] == [True]
    assert capital(sent, "Ostmark") == []
