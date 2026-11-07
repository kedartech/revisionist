"""Phase 4 unit E1: the timeline and the generated list of who held power."""

from datetime import date
from typing import Any

import pytest

from revisionist.engine import timeline as tl
from revisionist.engine.llm import Reply, Request
from revisionist.engine.web import new_game_api
from revisionist.engine.web.server import ApiError


class Fake:
    def __init__(self, people: list[dict[str, Any]]) -> None:
        self.people = people
        self.requests: list[Request] = []

    def call(self, request: Request) -> Reply:
        self.requests.append(request)
        return Reply({"people": self.people}, request.model, 8, 4, 0, 0.0)


def person(name: str, side: str = "Germany", power: str = "Military command") -> dict[str, str]:
    return {"name": name, "title": f"Chief {name}", "side": side, "power": power}


@pytest.fixture(autouse=True)
def fresh() -> None:
    tl._held.clear()


def test_the_list_is_grouped_by_side_then_power() -> None:
    fake = Fake(
        [
            person("Halder"),
            person("Hitler", power="Head of state"),
            person("Marshall", side="United States"),
            person("Keitel"),
        ]
    )
    groups = new_game_api.figures(date(1941, 9, 3), "", fake)
    assert [(g["side"], g["power"], [f["name"] for f in g["figures"]]) for g in groups] == [
        ("Germany", "Head of state", ["Hitler"]),
        ("Germany", "Military command", ["Halder", "Keitel"]),
        ("United States", "Military command", ["Marshall"]),
    ]


def test_search_matches_name_or_title_without_case() -> None:
    fake = Fake([person("Halder"), person("Keitel")])
    (group,) = new_game_api.figures(date(1941, 9, 3), "  KEIT", fake)
    assert [f["name"] for f in group["figures"]] == ["Keitel"]
    (group,) = new_game_api.figures(date(1941, 9, 3), "chief hal", fake)
    assert [f["name"] for f in group["figures"]] == ["Halder"]
    assert new_game_api.figures(date(1941, 9, 3), "nobody", fake) == []


def test_one_call_per_date() -> None:
    fake = Fake([person("Halder")])
    tl.held_power(date(1941, 9, 3), fake)
    tl.held_power(date(1941, 9, 3), fake)
    assert len(fake.requests) == 1
    tl.held_power(date(1941, 9, 4), fake)
    assert len(fake.requests) == 2


def test_the_list_is_clipped_and_cleaned() -> None:
    many = [person(f"Person {i}") for i in range(60)]
    bad = [person("Person 0"), {**person("Empty"), "title": " "}, {"name": "Short"}]
    assert len(tl.held_power(date(1941, 9, 3), Fake([*bad, *many]))) == tl.HELD_MAX
    names = [p.name for p in tl._held[date(1941, 9, 3)]]
    assert len(set(names)) == len(names) and "Empty" not in names and "Short" not in names


def test_a_date_outside_the_war_is_refused_without_a_call() -> None:
    fake = Fake([person("Halder")])
    with pytest.raises(tl.OutsideWarError):
        tl.held_power(date(1950, 1, 1), fake)
    with pytest.raises(ApiError) as caught:
        new_game_api.figures(date(1939, 8, 31), "", fake)
    assert "inside it" in caught.value.message
    assert not fake.requests
    tl.held_power(date(1939, 9, 1), fake)
    tl.held_power(date(1945, 9, 2), fake)


def test_the_timeline_marks_the_curated_worlds() -> None:
    points = new_game_api.timeline()
    assert [p["date"] for p in points] == sorted(p["date"] for p in points)
    worlds = {p["world"] for p in points if p["world"]}
    assert worlds == {"autumn-1941", "engine-v2-slice-1941"}
    autumn = next(p for p in points if p["world"] == "autumn-1941")
    assert autumn["date"] == "1941-09-01" and autumn["curated"]
    assert any(p["world"] is None for p in points)
