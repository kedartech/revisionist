"""Reach R4, the picker: a movement form offers a fleet's detachments in play, placed
and timed from the seat's own pages only, and a split form offers its own fleets only."""

import json
from datetime import date
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId, EntityId, EventId, FeatureId, FeedId, derived_id
from revisionist.core.realism import bases, routing
from revisionist.core.realism import feeds as rf
from revisionist.core.realism.geography import Feature
from revisionist.core.visibility import PUBLIC
from revisionist.core.world_compile import object_id
from revisionist.engine import campaign as cmp
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_destinations import FIXTURE, fdr, param, places, state_of  # noqa: F401
from tests.test_web_realism import Realism, realism_of

D1 = "us_atlantic_fleet__d1"
HOME_D1 = "home_fleet__d1"


def append(game: Realism, tag: str, payload: ev.Payload) -> None:
    store = game.web.app.open()
    try:
        state = state_of(game)
        store.append_all(
            [
                ev.Event(
                    event_id=EventId(derived_id(game.campaign, "test-picker", tag)),
                    campaign_id=game.campaign,
                    seq=state.last_seq + 1,
                    tick=state.tick,
                    scope=PUBLIC,
                    payload=payload,
                    versions=cmp.versions(),
                )
            ]
        )
    finally:
        store.close()


def detach(
    game: Realism, parent: str, at: str, n: int = 1, rejoined: date | None = None
) -> Feature:
    """The parent's detachment ``n`` at ``at`` in the truth, as a split would leave it."""
    state = state_of(game)
    base = state.features[FeatureId(game.ids[parent])]
    det = base.model_copy(
        update={
            "feature_id": FeatureId(object_id(game.campaign, "feature", f"{parent}__d{n}")),
            "name": f"{base.name} detachment {n}",
            "tier": 2,
            "places": (EntityId(game.ids[at]),),
            "legs": (),
            "detached_from": base.feature_id,
            "rejoined_on": rejoined,
        }
    )
    append(game, f"{parent}-{n}", ev.FeatureSet(feature=det))
    return det


def page(game: Realism, feed: str) -> list[str]:
    """The feed's page as it would be issued today, arrived today; returns its sighting labels."""
    state = state_of(game)
    today = state.in_world_date
    assert today is not None
    issued = rf.issue(state, state.feeds[FeedId(game.ids[feed])], today, "picker")
    assert issued is not None
    doc_id = DocumentId(derived_id(game.campaign, "test-picker-page", feed))
    append(
        game,
        f"page-{feed}",
        ev.DocumentIssued(
            document=issued.document.model_copy(update={"doc_id": doc_id, "arrives": today}),
            truth=issued.truth.model_copy(update={"doc_id": doc_id}),
        ),
    )
    return [b.label for b in issued.document.body if b.sight is not None]


def choices(client: Client, lever: str) -> list[tuple[str, str]]:
    return [(c["value"], c["label"]) for c in param(client, lever, "force")["choices"]]


def to_places(client: Client, lever: str) -> list[dict[str, Any]]:
    return list(param(client, lever, "to")["places"])


def test_the_move_form_lists_a_live_detachment_with_no_days_before_a_page_places_it(
    fdr: tuple[Realism, Client],  # noqa: F811
) -> None:
    game, ada = fdr
    before = to_places(ada, "move_fleet")
    detach(game, "us_atlantic_fleet", "argentia")
    assert choices(ada, "move_fleet") == [
        ("us_atlantic_fleet", "The Atlantic Fleet"),
        (D1, "US Atlantic Fleet detachment 1"),
        ("us_pacific_fleet", "The Pacific Fleet"),
    ]
    after = to_places(ada, "move_fleet")
    assert [p["value"] for p in after] == [p["value"] for p in before]
    for old, new in zip(before, after, strict=True):
        assert new["days"] == {**old["days"], D1: None}, new["label"]
        assert new["reach"] == {**old["reach"], D1: None}, new["label"]


def test_once_a_page_places_it_the_detachment_has_days_and_reach_per_place(
    fdr: tuple[Realism, Client],  # noqa: F811
) -> None:
    game, ada = fdr
    det = detach(game, "us_atlantic_fleet", "argentia")
    assert "US Atlantic Fleet detachment 1" in page(game, "atlantic_reports")
    state = state_of(game)
    key = {v: k for k, v in game.ids.items()}
    found = to_places(ada, "move_fleet")
    for p in found:
        to = EntityId(game.ids[p["value"]])
        want_days = 0 if to == det.places[0] else routing.travel_days(state, det, to)
        assert p["days"][D1] == want_days, p["label"]
        want = bases.reach(state, det, to)
        assert want is not None
        assert p["reach"][D1] == {
            "tier": want.tier.value,
            "base": key[want.base] if want.base is not None else None,
            "reason": want.reason,
        }, p["label"]
    shown = {p["label"]: p for p in found}
    assert shown["Argentia"]["days"][D1] == 0
    assert shown["Norfolk"]["days"][D1] > 0 and shown["Norfolk"]["days"]["us_atlantic_fleet"] == 0


def test_a_rejoined_detachment_is_not_offered(fdr: tuple[Realism, Client]) -> None:  # noqa: F811
    game, ada = fdr
    today = state_of(game).in_world_date
    detach(game, "us_atlantic_fleet", "norfolk", rejoined=today)
    page(game, "atlantic_reports")
    assert D1 not in dict(choices(ada, "move_fleet"))
    assert all(D1 not in p["days"] and D1 not in p["reach"] for p in to_places(ada, "move_fleet"))


def test_the_split_form_carries_reach_for_its_parent_only(fdr: tuple[Realism, Client]) -> None:  # noqa: F811
    game, ada = fdr
    detach(game, "us_atlantic_fleet", "argentia")
    page(game, "atlantic_reports")
    parents = ["us_atlantic_fleet", "us_pacific_fleet"]
    assert [v for v, _ in choices(ada, "detach_fleet")] == parents
    moves = {p["value"]: p for p in to_places(ada, "move_fleet")}
    split = to_places(ada, "detach_fleet")
    assert split
    for p in split:
        assert list(p["reach"]) == parents and list(p["days"]) == parents, p["label"]
        for force in parents:
            assert p["reach"][force] == moves[p["value"]]["reach"][force], (force, p["label"])
            assert p["days"][force] == moves[p["value"]]["days"][force], (force, p["label"])
    assert {p["label"]: p for p in split}["Argentia"]["reach"]["us_atlantic_fleet"] is not None


@pytest.fixture
def two(web: Web) -> tuple[Realism, Client, Client]:  # noqa: F811
    game = Realism(web, "autumn-1941")
    ada = game.seat("ada", "roosevelt")
    bea = game.seat("bea", "churchill")
    game.open_play()
    game.first_tick()
    return game, ada, bea


def offered(client: Client) -> set[str]:
    """Every force key and label the seat's forms carry, in choices, days or reach."""
    out: set[str] = set()
    for lever in realism_of(client)["desk"]["levers"]:
        for p in lever["params"]:
            out |= {c["value"] for c in p["choices"]} | {c["label"] for c in p["choices"]}
            for place in p["places"]:
                out |= set(place["days"]) | set(place["reach"])
    return out


def test_no_other_sides_detachment_appears_in_the_seats_forms(
    two: tuple[Realism, Client, Client],
) -> None:
    game, ada, bea = two
    detach(game, "us_atlantic_fleet", "argentia")
    detach(game, "home_fleet", "reykjavik")
    assert "Home Fleet detachment 1" in page(game, "churchill_cables")  # Roosevelt holds it
    assert "US Atlantic Fleet detachment 1" in page(game, "atlantic_reports")
    roosevelt, churchill = offered(ada), offered(bea)
    assert D1 in roosevelt and HOME_D1 in churchill
    assert HOME_D1 not in roosevelt and "Home Fleet detachment 1" not in roosevelt
    assert D1 not in churchill and "US Atlantic Fleet detachment 1" not in churchill


def test_the_fixture_move_form_lists_a_detachment_no_page_has_placed() -> None:
    """The shared fixture carries the case the client draws: a detachment offered after its
    parent, with no days and no reach anywhere yet."""
    levers = {x["name"]: x for x in json.loads(FIXTURE.read_text())["desk"]["levers"]}
    params = {p["name"]: p for p in levers["move_fleet"]["params"]}
    values = [c["value"] for c in params["force"]["choices"]]
    assert values.index(D1) == values.index("us_atlantic_fleet") + 1
    for place in params["to"]["places"]:
        assert set(place["days"]) == set(values) == set(place["reach"])
        assert place["days"][D1] is None and place["reach"][D1] is None
