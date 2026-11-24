"""The opening: a game's people by nation, then path, then person, from the roster's own
list of who can be claimed. A ready-made world opens and claims with no model call; the
transport here counts requests and answers none."""

import json
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import roster
from revisionist.core.ids import CampaignId, SeatId
from revisionist.engine import campaign as cmp
from revisionist.engine import session_zero
from revisionist.engine.ids import new_id
from revisionist.engine.llm import Reply, Request, TransportError
from revisionist.engine.store import load_state
from revisionist.engine.web import new_game_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web.accounts import WebSeats
from revisionist.engine.web.handlers import JOINED_ZERO
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_phase4_contract import _same_shape

AUTUMN = "autumn-1941"
SALT = "salt-strait-realism"
FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-cast.json"


class Counting:
    """A transport that counts what it is asked and answers nothing."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def call(self, request: Request) -> Reply:
        self.calls.append(request.call_class)
        raise TransportError("no model in this test")


def new(client: Client, action: str, /, **body: Any) -> dict[str, Any]:
    status, out = client.call(f"/api/new/{action}", body)
    assert status == 200, out
    return dict(out)


def hosted(web: Web, world: str, handle: str = "ada") -> tuple[Client, CampaignId]:  # noqa: F811
    """``handle`` signed up and made host of a new game of ``world``, holding nobody yet."""
    client, _ = web.signed_up(handle)
    store = web.app.open()
    try:
        cid = cmp.new_campaign(store, cmp.load_world(cmp.world_path(world)))
        row = store.conn.execute(
            "SELECT account_id FROM web_accounts WHERE handle = %s", (handle,)
        ).fetchone()
        assert row is not None
        WebSeats(store.conn).start(cid, SeatId(new_id()), row[0])
    finally:
        store.close()
    return client, cid


def joined(host: Client, web: Web, handle: str) -> Client:  # noqa: F811
    code = new(host, "invite")["code"]
    guest, _ = web.signed_up(handle)
    assert guest.seat("join", code=code) == JOINED_ZERO
    return guest


def state_of(web: Web, cid: CampaignId) -> Any:  # noqa: F811
    store = web.app.open()
    try:
        return load_state(store, cid)
    finally:
        store.close()


def people(opening: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        p["name"]: p for n in opening["nations"] for path in n["paths"] for p in path["persons"]
    }


@pytest.fixture
def counting(web: Web) -> Counting:  # noqa: F811
    transport = Counting()
    web.app.transport_factory = lambda: transport
    web.app.spawn = lambda run: run()
    return transport


def test_the_opening_is_every_claimable_person_by_nation_and_path(
    web: Web,  # noqa: F811
    counting: Counting,
) -> None:
    client, cid = hosted(web, AUTUMN)
    out = new(client, "opening")
    assert out["refused"] is False
    opening = out["opening"]
    free = {c.name for c in roster.claimable(state_of(web, cid)) if c.reason is None}
    assert set(people(opening)) == free
    assert opening["seats_left"] == opening["seats_max"] == 10
    nations = {n["name"]: n for n in opening["nations"]}
    usa = {
        path["path"]: [p["name"] for p in path["persons"]]
        for path in nations["United States"]["paths"]
    }
    assert usa == {"political": ["Franklin D. Roosevelt"], "military": ["Ernest J. King"]}
    assert [path["path"] for path in nations["United States"]["paths"]] == ["political", "military"]
    assert list(nations) == sorted(nations)
    assert people(opening)["Franklin D. Roosevelt"] == {
        "name": "Franklin D. Roosevelt",
        "office": "President of the United States",
        "pitch": people(opening)["Franklin D. Roosevelt"]["pitch"],
        "taken": False,
    }
    _same_shape(opening, api.Opening)
    assert counting.calls == []


def test_a_taken_person_is_marked_for_every_player_and_a_joiner(
    web: Web,  # noqa: F811
    counting: Counting,
) -> None:
    host, _ = hosted(web, AUTUMN)
    guest = joined(host, web, "bea")
    assert new(host, "pick", name="Fumimaro Konoe")["reply"] == "You are Fumimaro Konoe."
    assert new(guest, "pick", name="Adolf Hitler")["reply"] == "You are Adolf Hitler."
    third = joined(host, web, "cyd")
    seen = new(third, "opening")["opening"]
    assert seen == new(host, "opening")["opening"] == new(guest, "opening")["opening"]
    japan = next(n for n in seen["nations"] if n["name"] == "Japan")
    marks = {p["name"]: p["taken"] for path in japan["paths"] for p in path["persons"]}
    assert marks == {"Fumimaro Konoe": True, "Hideki Tojo": False, "Isoroku Yamamoto": False}
    assert people(seen)["Adolf Hitler"]["taken"] is True
    assert sum(p["taken"] for p in people(seen).values()) == 2
    assert seen["seats_left"] == 8
    assert counting.calls == []


@pytest.mark.parametrize(("world", "who"), [(AUTUMN, "Winston Churchill"), (SALT, "Oren Vale")])
def test_opening_and_claiming_a_ready_made_world_make_no_model_call(
    web: Web,  # noqa: F811
    counting: Counting,
    world: str,
    who: str,
) -> None:
    client, cid = hosted(web, world)
    assert who in people(new(client, "opening")["opening"])
    assert new(client, "pick", name=who) == {"reply": f"You are {who}.", "refused": False}
    assert people(new(client, "opening")["opening"])[who]["taken"] is True
    assert counting.calls == []
    assert state_of(web, cid).seats


def test_a_ready_made_world_refuses_a_person_off_its_roster(
    web: Web,  # noqa: F811
    counting: Counting,
) -> None:
    client, cid = hosted(web, AUTUMN)
    before = set(state_of(web, cid).roster)
    out = new(client, "pick", name="Cordell Hull")
    assert out == {"reply": new_game_api.OFF_ROSTER, "refused": True}
    assert set(state_of(web, cid).roster) == before
    assert counting.calls == []


def test_a_ready_made_world_refuses_the_who_held_power_list(
    web: Web,  # noqa: F811
    counting: Counting,
) -> None:
    client, _ = hosted(web, AUTUMN)
    out = new(client, "figures", date="1941-09-01")
    assert out["refused"] and out["reply"] == new_game_api.SET_BY_WORLD
    assert counting.calls == []


def test_two_seats_racing_for_one_person_cannot_both_land(
    web: Web,  # noqa: F811
    counting: Counting,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, cid = hosted(web, AUTUMN)
    rival = SeatId(new_id())
    real = session_zero._releases
    raced: list[bool] = []

    def first_the_rival(store: Any, campaign_id: CampaignId, entity: Any) -> int:
        if not raced:
            raced.append(True)
            session_zero.claim(store, campaign_id, rival, "Joseph Stalin")
        return real(store, campaign_id, entity)

    monkeypatch.setattr(session_zero, "_releases", first_the_rival)
    out = new(host, "pick", name="Joseph Stalin")
    assert out == {"reply": "Joseph Stalin is already taken.", "refused": True}
    state = state_of(web, cid)
    assert [s.seat_id for s in state.seats.values()] == [rival]
    assert people(new(host, "opening")["opening"])["Joseph Stalin"]["taken"] is True
    assert counting.calls == []


NOT_CHOOSING = "This game is not choosing its people."


def test_the_opening_is_refused_once_the_game_is_in_play(web: Web) -> None:  # noqa: F811
    web.app.spawn = lambda run: None
    host, _ = hosted(web, AUTUMN)
    assert not new(host, "pick", name="Winston Churchill")["refused"]
    assert new(host, "opening")["opening"]["seats_left"] == 9
    assert not new(host, "begin")["refused"]
    assert host.me()["game"]["phase"] == "play"
    transport = Counting()
    web.app.transport_factory = lambda: transport
    assert host.call("/api/new/opening", {}) == (400, {"error": NOT_CHOOSING})
    status, listed = host.call("/api/game/handover-list", {})
    assert status == 200, listed
    stalin = next(x["key"] for x in listed["leaders"] if x["name"] == "Joseph Stalin")
    status, out = host.call("/api/game/handover", {"leader": stalin})
    assert status == 200 and not out["refused"], out
    newcomer, _ = web.signed_up("bea")
    newcomer.seat("join", code=out["code"])
    assert newcomer.call("/api/new/opening", {}) == (400, {"error": NOT_CHOOSING})
    assert transport.calls == []


def test_a_nation_with_nobody_playable_is_not_listed() -> None:
    from revisionist.core.world_compile import compile_world
    from revisionist.engine.store import MemoryStore

    store = MemoryStore()
    cid = CampaignId("opening-unplayable")
    store.append_all(compile_world(cmp.load_world(cmp.world_path(AUTUMN)), cid, cmp.versions()))
    state = load_state(store, cid)
    italy = {
        c.person
        for c in roster.claimable(state)
        if c.name in {"Benito Mussolini", "Angelo Iachino"}
    }
    cards = {
        p: c.model_copy(update={"playable": False}) if p in italy else c
        for p, c in state.cards.items()
    }
    shown = new_game_api.opening(state.model_copy(update={"cards": cards}))
    assert "Italy" not in {n["name"] for n in shown["nations"]}
    assert "Italy" in {n["name"] for n in new_game_api.opening(state)["nations"]}


def test_the_cast_fixture_carries_the_opening_shape() -> None:
    _same_shape(json.loads(FIXTURE.read_text())["opening"], api.Opening)


@pytest.mark.parametrize(("world", "nation"), [(AUTUMN, "United States"), (SALT, None)])
def test_the_opening_says_a_ready_made_game_and_names_each_nation_by_its_world_key(
    web: Web,  # noqa: F811
    counting: Counting,
    world: str,
    nation: str | None,
) -> None:
    client, _ = hosted(web, world)
    out = new(client, "opening")
    assert out["ready_made"] is True
    assert out["world"] == world
    decl = cmp.load_world(cmp.world_path(world))
    polities = {e.key for e in decl.entities if e.kind.value == "polity"}
    listed = [n["key"] for n in out["opening"]["nations"] if n["key"] is not None]
    assert listed and set(listed) <= set(out["nation_keys"])
    assert set(out["nation_keys"].values()) <= polities
    if nation is not None:
        usa = next(n["key"] for n in out["opening"]["nations"] if n["name"] == nation)
        assert out["nation_keys"][usa] == "usa"
    assert counting.calls == []


def test_the_opening_says_a_pitched_game_is_not_ready_made(web: Web) -> None:  # noqa: F811
    from tests.test_web_pick import PLACED, Fake, seated

    fake = Fake(PLACED)
    client = seated(web, fake)
    out = new(client, "opening")
    assert out["refused"] is False
    assert out["ready_made"] is False
    assert fake.calls == []
