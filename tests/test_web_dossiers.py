"""Spec for Train 3 unit S4, written with contract K3: the sidecar loader and the dossier
and setting blocks it feeds. The unit makes these pass and never edits them."""

import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core.state import State
from revisionist.core.world_compile import object_id
from revisionist.engine import campaign as cmp
from revisionist.engine.llm import RecordedTransport
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import dossiers
from revisionist.engine.web import realism_api as api
from revisionist.engine.web.dossiers import SidecarError
from tests.handwritten import CAST
from tests.test_web import Client, Web, web  # noqa: F401

READY = ["autumn-1941", "engine-v2-slice-1941"]


def sidecar(tmp: Path, people: dict[str, Any] | None = None, **setting: Any) -> Path:
    base = {
        "situation": "Autumn 1941.",
        "sides": ["The Allies"],
        "crawl": ["One.", "Two.", "Three."],
        "facts": ["A fact."],
        "dates": [{"on": "1941-09-04", "what": "The Greer is fired on."}],
    }
    doc = {
        "world": "toy",
        "setting": base | setting,
        "people": people
        if people is not None
        else {
            "roosevelt": {
                "bio": "A bio.",
                "arena": "An arena.",
                "history": ["Did a thing."],
                "quote": "Words.",
                "source": "A speech, 1941",
                "fact": "A fact.",
                "portrait": None,
                "credit": None,
            }
        },
    }
    (tmp / "toy.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    return tmp


def person(**over: Any) -> dict[str, Any]:
    return {
        "bio": "A bio.",
        "arena": None,
        "history": [],
        "quote": None,
        "source": None,
        "fact": None,
        "portrait": None,
        "credit": None,
    } | over


def problems(tmp: Path, portraits: Path | None = None) -> str:
    with pytest.raises(SidecarError) as caught:
        dossiers.load("toy", tmp, portraits or tmp)
    return str(caught.value)


def campaign(world: str) -> tuple[State, list[Any]]:
    store = MemoryStore()
    cid = cmp.new_campaign(store, cmp.load_world(cmp.world_path(world)))
    return load_state(store, cid), list(store.read(cid))


# --- load ---------------------------------------------------------------------------


@pytest.mark.parametrize("world", READY)
def test_each_ready_world_loads_and_covers_its_roster(world: str) -> None:
    people, setting = dossiers.load(world)
    decl = cmp.load_world(cmp.world_path(world))
    keys = {r.entity for r in decl.roster}
    assert keys <= set(people), keys - set(people)
    for key in keys:
        d = people[key]
        assert set(d) == set(api.Dossier.__annotations__)
        assert d["bio"] and d["arena"] and d["history"]
        assert d["quote"] is None or d["source"], key
    assert set(setting) == set(api.Setting.__annotations__)
    assert setting["situation"] and setting["sides"] and setting["facts"]
    assert len(setting["crawl"]) == dossiers.CRAWL_PARAGRAPHS


def test_dates_are_served_in_words_oldest_first(tmp_path: Path) -> None:
    root = sidecar(
        tmp_path,
        dates=[
            {"on": "1941-10-17", "what": "The Kearny is hit."},
            {"on": "1941-09-04", "what": "The Greer is fired on."},
        ],
    )
    _, setting = dossiers.load("toy", root, root)
    assert setting["dates"] == [
        {"on": "4 September 1941", "what": "The Greer is fired on."},
        {"on": "17 October 1941", "what": "The Kearny is hit."},
    ]


def test_a_world_with_no_sidecar_is_empty_not_an_error(tmp_path: Path) -> None:
    assert dossiers.load("nowhere", tmp_path, tmp_path) == ({}, dossiers.empty_setting())


def test_missing_optional_fields_come_back_empty(tmp_path: Path) -> None:
    root = sidecar(tmp_path, people={"wheeler": {"bio": "A senator."}})
    people, _ = dossiers.load("toy", root, root)
    assert people["wheeler"] == person(bio="A senator.")


@pytest.mark.parametrize(
    ("field", "value", "cap"),
    [
        ("bio", "x" * (dossiers.BIO_MAX + 1), "bio"),
        ("arena", "x" * (dossiers.ARENA_MAX + 1), "arena"),
        ("history", ["x" * (dossiers.LINE_MAX + 1)], "history"),
        ("fact", "x" * (dossiers.LINE_MAX + 1), "fact"),
    ],
    ids=["bio", "arena", "history", "fact"],
)
def test_a_field_over_its_cap_is_refused(tmp_path: Path, field: str, value: Any, cap: str) -> None:
    root = sidecar(tmp_path, people={"roosevelt": {"bio": "A bio.", field: value}})
    out = problems(root)
    assert "roosevelt" in out and cap in out


def test_a_quote_over_its_cap_is_refused(tmp_path: Path) -> None:
    long = "x" * (dossiers.QUOTE_MAX + 1)
    root = sidecar(tmp_path, people={"roosevelt": {"quote": long, "source": "A speech"}})
    assert "quote" in problems(root)


def test_a_quote_with_no_source_is_refused(tmp_path: Path) -> None:
    root = sidecar(tmp_path, people={"roosevelt": {"bio": "A bio.", "quote": "Words."}})
    out = problems(root)
    assert "roosevelt" in out and "source" in out


@pytest.mark.parametrize(
    "setting",
    [
        {"crawl": ["One.", "Two.", "Three.", "Four."]},
        {"crawl": ["x" * (dossiers.CRAWL_MAX + 1)]},
        {"situation": "x" * (dossiers.SITUATION_MAX + 1)},
        {"sides": ["x" * (dossiers.LINE_MAX + 1)]},
        {"facts": ["x" * (dossiers.LINE_MAX + 1)]},
        {"dates": [{"on": "1941-09-04", "what": "x" * (dossiers.LINE_MAX + 1)}]},
        {"dates": [{"on": "early autumn", "what": "Something."}]},
    ],
    ids=["four-paragraphs", "long-paragraph", "situation", "side", "fact", "date-what", "date-on"],
)
def test_a_bad_setting_is_refused(tmp_path: Path, setting: dict[str, Any]) -> None:
    assert problems(sidecar(tmp_path, **setting))


def test_every_problem_is_listed_at_once(tmp_path: Path) -> None:
    root = sidecar(
        tmp_path,
        people={
            "roosevelt": {"bio": "x" * (dossiers.BIO_MAX + 1)},
            "wheeler": {"quote": "Words."},
        },
        crawl=["1", "2", "3", "4"],
    )
    with pytest.raises(SidecarError) as caught:
        dossiers.load("toy", root, root)
    assert len(caught.value.problems) >= 3


@pytest.mark.parametrize(
    "name", ["../secrets.jpg", "/etc/passwd", "sub/roosevelt.jpg", "Roosevelt.JPG", "fdr.gif", ""]
)
def test_a_portrait_must_be_a_bare_image_file_name(tmp_path: Path, name: str) -> None:
    (tmp_path / "fdr.gif").write_bytes(b"x")
    root = sidecar(tmp_path, people={"roosevelt": {"bio": "A bio.", "portrait": name}})
    assert "portrait" in problems(root, tmp_path)


def test_a_named_portrait_file_must_exist(tmp_path: Path) -> None:
    shots = tmp_path / "portraits"
    shots.mkdir()
    root = sidecar(tmp_path, people={"roosevelt": {"bio": "A bio.", "portrait": "roosevelt.jpg"}})
    assert "roosevelt.jpg" in problems(root, shots)
    (shots / "roosevelt.jpg").write_bytes(b"\xff\xd8")
    people, _ = dossiers.load("toy", root, shots)
    assert people["roosevelt"]["portrait"] == "roosevelt.jpg"


@pytest.mark.parametrize("world", READY)
def test_every_portrait_named_in_a_ready_sidecar_is_in_the_repo(world: str) -> None:
    people, _ = dossiers.load(world)
    for key, d in people.items():
        if d["portrait"]:
            assert (dossiers.PORTRAITS_DIR / d["portrait"]).is_file(), key
            assert d["credit"], f"{key}: a portrait is shown with its credit"


@pytest.mark.parametrize("world", READY)
def test_every_playable_person_in_a_ready_sidecar_has_a_portrait(world: str) -> None:
    people, _ = dossiers.load(world)
    assert [key for key, d in people.items() if not d["portrait"]] == []


def test_every_portrait_file_is_a_small_jpeg_with_its_source_recorded() -> None:
    sources = (dossiers.PORTRAITS_DIR / "SOURCES.md").read_text()
    shots = sorted(dossiers.PORTRAITS_DIR.glob("*.jpg"))
    assert shots
    for shot in shots:
        data = shot.read_bytes()
        assert data[:3] == b"\xff\xd8\xff", shot.name
        assert len(data) <= 64_000, shot.name
        assert f"`{shot.name}`" in sources, f"{shot.name}: source and licence not recorded"


# --- the blocks a campaign serves ----------------------------------------------------


def test_world_key_is_the_campaigns_world() -> None:
    _, events = campaign("autumn-1941")
    assert dossiers.world_key(events) == "autumn-1941"
    assert dossiers.world_key([]) is None


@pytest.mark.parametrize("world", READY)
def test_for_people_keys_each_roster_person_by_entity(world: str) -> None:
    state, events = campaign(world)
    people, _ = dossiers.load(world)
    out = dossiers.for_people(state, events)
    assert set(out) == {ch.entity_id for ch in state.roster.values()}
    for key, d in people.items():
        eid = object_id(state.campaign_id, "entity", key)
        if eid in state.entities:
            assert out[eid] == d  # type: ignore[index]


def test_each_roster_side_names_the_country_it_belongs_to() -> None:
    from revisionist.engine.web.snapshot import roster

    state, _ = campaign("autumn-1941")
    by_name = {c["name"]: c["sides"] for c in roster(state)}
    assert by_name["Franklin D. Roosevelt"] == [
        {
            "contest": "Revising the Neutrality Act",
            "side": "Aid-to-Britain bloc",
            "polity": "United States",
        },
        {
            "contest": "The US-Japan negotiations",
            "side": "United States",
            "polity": "United States",
        },
    ]
    assert {s["polity"] for s in by_name["Hideki Tojo"]} == {"Japan"}


def test_for_people_skips_sidecar_people_not_in_the_campaign() -> None:
    state, events = campaign("engine-v2-slice-1941")
    out = dossiers.for_people(state, events)
    names = {state.entities[e].name for e in out}
    assert "Joseph Stalin" not in names and "Winston Churchill" in names


def test_setting_is_the_worlds_setting() -> None:
    state, events = campaign("engine-v2-slice-1941")
    _, expected = dossiers.load("engine-v2-slice-1941")
    out = dossiers.setting(state, events)
    assert out == expected
    assert out["dates"][0]["on"] == "4 September 1941"


def test_a_broken_sidecar_never_breaks_the_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, events = campaign("engine-v2-slice-1941")
    (tmp_path / "engine-v2-slice-1941.yaml").write_text(
        textwrap.dedent("""\
            world: engine-v2-slice-1941
            people:
              roosevelt: {quote: Words with no source.}
            """)
    )
    monkeypatch.setattr(dossiers, "SIDECAR_DIR", tmp_path)
    assert dossiers.for_people(state, events) == {}
    assert dossiers.setting(state, events) == dossiers.empty_setting()


def test_a_campaign_with_no_sidecar_gets_empty_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, events = campaign("autumn-1941")
    monkeypatch.setattr(dossiers, "SIDECAR_DIR", tmp_path)
    assert dossiers.for_people(state, events) == {}
    assert dossiers.setting(state, events) == dossiers.empty_setting()


# --- served by the web room ------------------------------------------------------------


def new(client: Client, action: str, /, **body: Any) -> dict[str, Any]:
    status, out = client.call(f"/api/new/{action}", body)
    assert status == 200, out
    return dict(out)


@pytest.fixture
def cast_web(web: Web) -> Web:  # noqa: F811
    transport = RecordedTransport(CAST)
    web.app.transport_factory = lambda: transport
    web.app.spawn = lambda run: run()
    return web


def test_the_cast_screen_serves_each_dossier_and_the_setting(cast_web: Web) -> None:
    client, _ = cast_web.signed_up("ada")
    assert not new(client, "ready", world="autumn-1941")["refused"]
    view = client.me()["game"]["view"]
    people, setting = dossiers.load("autumn-1941")
    roster = {c["name"]: c for c in view["roster"]}
    assert roster["Franklin D. Roosevelt"]["dossier"] == people["roosevelt"]
    assert roster["Joseph Stalin"]["dossier"]["bio"] == people["stalin"]["bio"]
    assert view["setting"] == setting


def test_the_room_serves_the_seats_own_dossier(cast_web: Web) -> None:
    client, _ = cast_web.signed_up("ada")
    assert not new(client, "ready", world="autumn-1941")["refused"]
    assert not new(client, "pick", name="Winston Churchill")["refused"]
    assert not new(client, "begin")["refused"]
    game = client.me()["game"]
    assert game["phase"] == "play"
    people, setting = dossiers.load("autumn-1941")
    block = game["view"]["realism"]
    assert block["dossier"] == people["churchill"]
    assert block["setting"] == setting


def test_sidecars_sit_outside_the_world_list() -> None:
    assert dossiers.SIDECAR_DIR != cmp.WORLDS_DIR
    assert not list(cmp.WORLDS_DIR.glob("*dossiers*.yaml"))
