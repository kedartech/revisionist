"""Phase 4 unit C4: a seat may play someone the roster leaves out, if the record places
them at the start. Fake transports answer; no model is called."""

from typing import Any

from revisionist.engine.llm import Reply, Request, TransportError
from revisionist.engine.store import load_state
from tests.cast_scenario import _clerical, _text_lever
from tests.test_web import Client, Web, web  # noqa: F401

HULL = "Cordell Hull"
SLICE = "engine-v2-slice-1941"

PLACED: dict[str, Any] = {
    "existed": True,
    "placed": True,
    "note": "Secretary of State.",
    "name": HULL,
    "pitch": "Secretary of State, wary of Tokyo.",
    "reach": "The State Department and its cables.",
    "means": [{"name": "State Department", "kind": "office", "tier": 3}],
}
CARD: dict[str, Any] = {
    "pipelines": [
        {"key": "hull_note", "name": "A note", "gap": True, "steps": [_clerical("cordell_hull")]},
        {"key": "hull_talk", "name": "A talk", "gap": True, "steps": [_clerical("cordell_hull")]},
    ],
    "cards": [
        {
            "person": "cordell_hull",
            "reach": {"rank": 4, "heads": False},
            "office": "Secretary of State",
            "principals": ["united_states"],
            "pipelines": ["hull_note", "hull_talk"],
            "powers": ["conduct diplomacy"],
            "levers": [
                _text_lever("note", "hull_note", "opinion", "Send a note"),
                _text_lever("talk", "hull_talk", "opinion", "Open talks"),
            ],
            "horizon_days": 7,
            "voice": "Measured.",
            "loyalty": 3,
            "interests": [],
        }
    ],
}


class Fake:
    def __init__(self, pick: dict[str, Any], builds: list[Any] | None = None) -> None:
        self.pick = pick
        self.builds = list(builds if builds is not None else [CARD])
        self.calls: list[str] = []

    def call(self, request: Request) -> Reply:
        self.calls.append(request.call_class)
        if request.call_class == "character_pick":
            return Reply(self.pick, request.model, 5, 5, 0, 0.0)
        if request.call_class == "build":
            out = self.builds.pop(0) if len(self.builds) > 1 else self.builds[0]
            if isinstance(out, Exception):
                raise out
            return Reply(out, request.model, 5, 5, 0, 0.0)
        raise AssertionError(request.call_class)


def new(client: Client, action: str, /, **body: Any) -> dict[str, Any]:
    status, out = client.call(f"/api/new/{action}", body)
    assert status == 200, out
    return dict(out)


def seated(web: Web, fake: Fake) -> Client:  # noqa: F811
    web.app.transport_factory = lambda: fake
    web.app.spawn = lambda run: run()
    client, _ = web.signed_up("ada")
    assert not new(client, "ready", world=SLICE)["refused"]
    return client


def test_a_roster_name_claims_without_a_pick_call(web: Web) -> None:  # noqa: F811
    fake = Fake(PLACED)
    client = seated(web, fake)
    assert new(client, "pick", name="winston churchill")["reply"] == "You are Winston Churchill."
    assert "character_pick" not in fake.calls


def test_a_placed_name_is_added_claimed_and_given_a_card(web: Web) -> None:  # noqa: F811
    fake = Fake(PLACED)
    client = seated(web, fake)
    out = new(client, "pick", name="Cordell Hull")
    assert out == {"reply": f"You are {HULL}.", "refused": False}
    assert fake.calls.count("character_pick") == 1 and fake.calls.count("build") == 1
    store = web.app.open()
    try:
        state = load_state(store, client.me()["game"]["id"])
    finally:
        store.close()
    (seat,) = state.seats.values()
    card = state.cards[seat.embodies]
    assert state.entities[seat.embodies].name == HULL
    assert card.authority or card.reach.rank > 0


def test_a_name_the_record_does_not_place_is_refused(web: Web) -> None:  # noqa: F811
    fake = Fake({"existed": True, "placed": False, "note": "Out of office by then."})
    client = seated(web, fake)
    before = client.me()["game"]["view"]["roster"]
    out = new(client, "pick", name="Henry Stimson")
    assert out["refused"] and "does not place Henry Stimson" in out["reply"]
    assert "Out of office by then." in out["reply"]
    assert client.me()["game"]["view"]["roster"] == before
    assert "build" not in fake.calls


def test_the_model_being_down_is_a_reply(web: Web) -> None:  # noqa: F811
    class Down:
        def call(self, request: Request) -> Reply:
            raise TransportError("down")

    client = seated(web, Fake(PLACED))
    web.app.transport_factory = lambda: Down()
    out = new(client, "pick", name=HULL)
    assert out["refused"] and "cannot be reached" in out["reply"]


def test_a_failed_build_leaves_the_game_beginnable(web: Web) -> None:  # noqa: F811
    bad: dict[str, Any] = {"pipelines": [], "cards": []}
    fake = Fake(PLACED, builds=[bad])
    client = seated(web, fake)
    out = new(client, "pick", name=HULL)
    assert out["refused"] and "could not be drawn up" in out["reply"]
    assert client.me()["game"]["view"]["seat"] is None
    # The person is on the roster without a card: a retry takes the roster path and builds.
    fake.builds = [CARD]
    out = new(client, "pick", name=HULL)
    assert out == {"reply": f"You are {HULL}.", "refused": False}
    assert fake.calls.count("character_pick") == 1
    assert not new(client, "begin")["refused"]
    assert client.me()["game"]["phase"] == "play"


def test_begin_draws_up_a_missing_card(web: Web) -> None:  # noqa: F811
    fake = Fake(PLACED, builds=[{"pipelines": [], "cards": []}])
    client = seated(web, fake)
    assert new(client, "pick", name=HULL)["refused"]
    assert not new(client, "pick", name="Winston Churchill")["refused"]
    fake.builds = [CARD]
    assert not new(client, "begin")["refused"]
    store = web.app.open()
    try:
        state = load_state(store, client.me()["game"]["id"])
    finally:
        store.close()
    assert set(state.roster) <= set(state.cards)
