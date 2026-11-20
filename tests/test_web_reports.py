"""Reports reach the seat through named intelligence people (RPD).

The toy world (``tests/worlds/territory-toy.yaml``) is played as detection's tests play it
(``tests/test_detection.py``): ``territories`` and ``reports`` on, every force given a
strength. Norra's levy and kites stand on the Norra Plain; Sudland's galleys in the Gulf,
which borders the plain, and its levy on the Sudland Coast. A test that needs sources
gives the world an ``intelligence``; Ilse reports for Norra and Tomas for Sudland.
"""

import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import DocumentId
from revisionist.core.project import project
from revisionist.core.realism import detect
from revisionist.core.realism.card import ChannelKind
from revisionist.core.realism.detect import Source
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.geography import Sight
from revisionist.core.state import State
from revisionist.core.visibility import private_to
from revisionist.engine import catchup
from revisionist.engine.web import map_api
from revisionist.engine.web import realism_api as api
from revisionist.engine.web import realism_snapshot as rs
from tests.test_adjacency_moves import Logged, World, day, entity, seat
from tests.test_detection import (
    NORRA,
    SUDLAND,
    fid,
    game,
    intelligence,
    made,
    norra_sees,
    on,
    place,
    roads,
    sudland_sees,
)
from tests.test_web_sighted_in_area import scouts

SEATS = ("ilse", "tomas")
ENEMIES = {"ilse": ("sudland_levy", "sudland_galleys"), "tomas": ("norra_levy", "norra_kites")}
NATION = {"ilse": NORRA, "tomas": SUDLAND}
LINE = re.compile(
    r"strength \d+( to \d+)?, [^,]+, seen \d+ [A-Z][a-z]+ \d{4}, (confirmed|probable|possible)"
)


def block(state: State, who: str = "ilse") -> dict[str, Any]:
    return rs.seat_realism(state, seat(who), set(), set(), None)


def shown(state: State, who: str = "ilse") -> list[dict[str, Any]]:
    return list(block(state, who)["map"].get("reports", []))


def sent_key(state: State, who: str, piece: str) -> str:
    """The key the web sends for the nation's report of ``piece``."""
    nation = entity(NATION[who])
    return map_api.mark_key(state.campaign_id, nation, detect.report_key(state, nation, fid(piece)))


def page(state: State, who: str, doc_id: str) -> dict[str, Any]:
    view = project(state, seat(who))
    return dict(rs.document(view, DocumentId(doc_id)))


def report_pages(state: State, who: str) -> dict[str, dict[str, Any]]:
    """The seat's arrived intelligence papers, by id."""
    view = project(state, seat(who))
    return {
        k: dict(rs.document(view, k))
        for k, d in view.documents.items()
        if d.classification is Classification.SECRET
    }


def letter_game(tmp: Path, *more: Any) -> tuple[Logged, list[ev.ReportMade]]:
    """Ilse reports Norra's contacts by letter (two days). On day 1 her levy and kites,
    on the plain, see the Sudland galleys in the bordering Gulf."""
    g = game(tmp, intelligence(norra_sees("contact", channel="letter")), *more)
    out = made(g.walk(day(1), day(1)))
    return g, [m for m in out if m.nation == entity(NORRA)]


# --- Rule 1: a report reaches the seat as a line in a paper from the named person --------


def test_a_report_is_a_line_in_a_paper_from_the_named_person_on_the_day_it_arrives(
    tmp_path: Path,
) -> None:
    g, (m,) = letter_game(tmp_path)
    assert m.report.arrives == day(3)
    on(g, day(2))
    assert not report_pages(g.state, "ilse")
    assert not shown(g.state)
    on(g, day(3))
    ((doc_id, paper),) = report_pages(g.state, "ilse").items()
    assert paper["item"]["author"] == "Ilse Varg"
    assert paper["item"]["issued"] == day(1).isoformat()
    assert paper["item"]["arrives"] == day(3).isoformat()
    assert len(paper["body"]) == 1
    (r,) = shown(g.state)
    assert r["document"] == doc_id and r["person"] == "Ilse Varg"


def test_a_contact_no_one_is_named_for_comes_with_no_paper(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.walk(day(1), day(1))
    on(g, day(1))
    assert not report_pages(g.state, "ilse")
    (r,) = shown(g.state)
    assert (r["source"], r["person"], r["document"]) == ("contact", "", None)


# --- Rule 2: the line gives kind, strength range, area, day seen, confidence in words ----


def test_the_line_gives_the_kind_the_range_the_area_the_day_and_the_confidence_in_words(
    tmp_path: Path,
) -> None:
    g, (m,) = letter_game(tmp_path)
    on(g, day(3))
    ((_, paper),) = report_pages(g.state, "ilse").items()
    lo, hi = m.report.strength or (0, 0)
    seen = day(1)
    assert paper["body"] == [
        {
            "label": "Galley",
            "value": f"strength {lo} to {hi}, The Gulf, seen {seen.day} {seen:%B %Y}, probable",
            "unit": "",
        }
    ]


def test_a_decrypt_gives_the_region_and_no_strength(tmp_path: Path) -> None:
    """A decrypt's line, from its fields as detection writes them."""
    g = game(tmp_path, intelligence(norra_sees("codebreaking", codebreaking=3)))
    view = project(g.state, seat("ilse"))
    fields = (
        BodyField(label="Kind", value="Levy"),
        BodyField(label="Bound for", value="north"),
        BodyField(label="Seen", value="1900-04-03"),
        BodyField(label="Confidence", value="C"),
        BodyField(label="Kind", value="unknown"),
        BodyField(label="Strength", value="2 to 2"),
        BodyField(label="Area", value="The Isle"),
        BodyField(label="Seen", value="1900-04-04"),
        BodyField(label="Confidence", value="A"),
    )
    assert rs.report_lines(view, fields) == [
        {
            "label": "Levy",
            "value": "strength not known, bound for The North, seen 3 April 1900, possible",
            "unit": "",
        },
        {
            "label": "Unknown piece",
            "value": "strength 2, The Isle, seen 4 April 1900, confirmed",
            "unit": "",
        },
    ]


def test_a_page_of_other_lines_is_left_as_it_is(tmp_path: Path) -> None:
    g = game(tmp_path)
    view = project(g.state, seat("ilse"))
    fields = (BodyField(label="Kind", value="Levy"), BodyField(label="Place", value="Sudby"))
    assert rs.report_lines(view, fields) is None


# --- Rule 3: the map block gains reports; they replace enemy sighting marks ---------------


def test_the_map_block_carries_each_arrived_report(tmp_path: Path) -> None:
    g, (m,) = letter_game(tmp_path)
    on(g, day(3))
    ((doc_id, _),) = report_pages(g.state, "ilse").items()
    (r,) = shown(g.state)
    lo, hi = m.report.strength or (0, 0)
    assert r == {
        "key": sent_key(g.state, "ilse", "sudland_galleys"),
        "kind": "galley",
        "kind_name": "Galley",
        "strength_low": lo,
        "strength_high": hi,
        "area": {"key": "the_gulf", "name": "The Gulf"},
        "bound_for": None,
        "seen": day(1).isoformat(),
        "source": "contact",
        "person": "Ilse Varg",
        "confidence": "B",
        "document": doc_id,
        "ring": ["the_gulf"],
    }
    assert set(r) == set(api.MapReport.__annotations__)
    assert r["key"] != m.report.key  # the core key never leaves the server


def test_report_keys_go_out_under_the_deployment_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = game(tmp_path)
    g.walk(day(1), day(1))
    on(g, day(1))
    first = {r["key"] for r in shown(g.state)}
    monkeypatch.setenv(map_api.MARK_SECRET_ENV, "34" * 32)
    assert first.isdisjoint({r["key"] for r in shown(g.state)})


def _enemy_sighting(g: Logged) -> State:
    """A page sighting the Sudland galleys and the Norra levy reaches Ilse, as a feed page
    does without ``reports``."""
    state = g.state
    doc_id = DocumentId("stored-sighting-page")
    galleys = state.features[fid("sudland_galleys")]
    levy = state.features[fid("norra_levy")]
    body = tuple(
        BodyField(
            label=f.name,
            value=state.entities[f.places[0]].name,
            sight=Sight(kind=f.kind, side=f.side, places=f.places),
        )
        for f in (galleys, levy)
    )
    page = ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.REPORT,
            author=entity("ilse"),
            issued=day(1),
            arrives=day(1),
            channel=ChannelKind.IN_PERSON,
            classification=Classification.CONFIDENTIAL,
            title="Scouts",
            body=body,
            scope=private_to(seat("ilse")),
        ),
        truth=DocumentTruth(doc_id=doc_id),
    )
    g.add([page])
    return g.state


def test_reports_replace_the_sighting_marks_of_other_sides_pieces(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.walk(day(1), day(1))
    on(g, day(1))
    state = _enemy_sighting(g)
    marks = block(state)["map"]["marks"]
    assert [m["side"] for m in marks] == ["own"]
    assert {r["kind"] for r in shown(state)} == {"galley"}


def test_a_game_without_reports_keeps_its_sighting_marks_and_has_no_reports_key(
    tmp_path: Path,
) -> None:
    def off(w: World) -> None:
        w["rules"] = ["territories"]

    g = game(tmp_path, off)
    on(g, day(1))
    state = _enemy_sighting(g)
    m = block(state)["map"]
    assert "reports" not in m
    assert {x["side"] for x in m["marks"]} == {"own", "other"}


# --- Rule 4: a seat's own pieces never appear as reports ----------------------------------


def test_a_seats_own_pieces_never_appear_as_reports(tmp_path: Path) -> None:
    g = game(
        tmp_path,
        place("sudland_levy", "norrhavn"),
        intelligence(norra_sees("contact"), sudland_sees("contact")),
    )
    g.walk(day(1), day(3))
    on(g, day(3))
    for who in SEATS:
        keys = {r["key"] for r in shown(g.state, who)}
        enemies = {sent_key(g.state, who, k) for k in ENEMIES[who]}
        own = {sent_key(g.state, who, k) for k in ENEMIES[next(s for s in SEATS if s != who)]}
        assert keys and keys <= enemies and keys.isdisjoint(own)


def _careless(w: World) -> None:
    for c in w["cards"]:
        c["competence"] = 0


# --- Keeps: a wrong report is worded and shaped exactly like a right one -------------------


def test_a_wrong_report_has_the_same_key_and_shape_as_a_right_one(tmp_path: Path) -> None:
    """Careless Ilse reports the galleys by contact every day; some reports are shifted.
    The map key, the fields sent and the line's wording are the same either way."""
    g = game(tmp_path, intelligence(norra_sees("contact")), _careless)
    seen: dict[bool, list[tuple[str, tuple[str, ...]]]] = {True: [], False: []}
    for n in range(1, 61):
        (m,) = [m for m in made(g.walk(day(n), day(n))) if m.nation == entity(NORRA)]
        on(g, day(n))
        (r,) = shown(g.state)
        assert r["seen"] == day(n).isoformat()
        (line,) = page(g.state, "ilse", str(r["document"]))["body"]
        assert LINE.fullmatch(line["value"]), line
        seen[m.shift is not None].append((r["key"], tuple(sorted(r))))
    assert seen[True] and seen[False]
    assert set(seen[True]) == set(seen[False])


# --- Accept: the fog test over a full scripted game for every seat -------------------------


def _scripted(tmp: Path, *more: Any, norra: tuple[str, ...] = ("contact", "air")) -> Logged:
    """Ilse reports Norra's ``norra`` sources by letter; Tomas reports Sudland's contacts
    and an agent on the Norra Plain; each seat reads a scouting feed naming every piece."""

    def both_scout(w: World) -> None:
        names = ["norra_levy", "norra_kites", "sudland_levy", "sudland_galleys"]
        scouts(*names)(w)
        feed = dict(w["feeds"][-1], key="sudland_scouts", name="Sudland scouts", author="tomas")
        w["feeds"].append(feed)
        (card,) = [c for c in w["cards"] if c["person"] == "tomas"]
        card["feeds"] = ["sudland_scouts"]

    return game(
        tmp,
        roads,
        both_scout,
        intelligence(
            norra_sees(*norra, channel="letter"),
            sudland_sees("contact", "agent", agents=[{"area": "norra_plain"}]),
        ),
        *more,
    )


def payloads(state: State, who: str) -> str:
    """Everything the seat is sent: its realism block, every paper it holds and its
    catch-up reply."""
    view = project(state, seat(who))
    out: dict[str, Any] = {"block": block(state, who)}
    out["papers"] = {k: rs.document(view, k) for k in sorted(view.documents)}
    return json.dumps(out, sort_keys=True, default=str)


def _moved_far(tier: int) -> Any:
    def change(w: World) -> None:
        (f,) = [f for f in w["features"] if f["key"] == "sudland_levy"]
        f["tier"] = tier
        f["places"] = ["sudby"]

    return change


@pytest.mark.parametrize("tier", [1, 5])
def test_no_payload_holds_an_enemy_pieces_strength_no_arrived_report_gave(
    tmp_path: Path, tier: int
) -> None:
    """The Sudland levy, on the Sudland Coast, is never seen by Norra, which searches by
    contact only: its strength changes nothing Ilse is sent on any day, papers included."""
    base = _scripted(tmp_path / "base", norra=("contact",))
    other = _scripted(tmp_path / f"t{tier}", _moved_far(tier), norra=("contact",))
    for n in range(1, 13):
        seen = []
        for g in (base, other):
            g.walk(day(n), day(n))
            on(g, day(n))
            seen.append(payloads(g.state, "ilse"))
            assert detect.report_key(g.state, entity(NORRA), fid("sudland_levy")) not in (
                project(g.state, seat("ilse")).reports
            )
        assert seen[0] == seen[1], f"day {n}"


def test_no_payload_holds_a_reported_pieces_strength_before_its_report_arrives(
    tmp_path: Path,
) -> None:
    """The Sudland galleys are seen by Ilse's letters on day 1 and reach her on day 3:
    their strength changes nothing she is sent before then, and only the report's
    strength after."""

    def stronger(w: World) -> None:
        (f,) = [f for f in w["features"] if f["key"] == "sudland_galleys"]
        f["tier"] = 4

    base, other = _scripted(tmp_path / "a"), _scripted(tmp_path / "b", stronger)
    for n in (1, 2):
        for g in (base, other):
            g.walk(day(n), day(n))
            on(g, day(n))
        assert payloads(base.state, "ilse") == payloads(other.state, "ilse")
    for g in (base, other):
        g.walk(day(3), day(3))
        on(g, day(3))
    key = sent_key(other.state, "ilse", "sudland_galleys")
    (r,) = [r for r in shown(other.state) if r["key"] == key]
    held = project(other.state, seat("ilse")).reports
    (true,) = [x for x in held.values() if x.kind == "galley"]
    assert (r["strength_low"], r["strength_high"]) == true.strength


@pytest.mark.parametrize("who", SEATS)
def test_every_enemy_fact_a_seat_is_sent_came_from_an_arrived_report(
    tmp_path: Path, who: str
) -> None:
    """Over the scripted game, each day: every report on the map is one the seat's nation
    holds, as it holds it, and no payload names an enemy piece."""
    g = _scripted(tmp_path)
    names = [g.state.features[fid(k)].name for k in ENEMIES[who]]
    for n in range(1, 13):
        g.walk(day(n), day(n))
        on(g, day(n))
        held = project(g.state, seat(who)).reports
        sent = {r["key"]: r for r in shown(g.state, who)}
        nation = entity(NATION[who])
        want = {map_api.mark_key(g.state.campaign_id, nation, k): x for k, x in held.items()}
        assert set(sent) <= set(want)
        for k, r in sent.items():
            assert (r["strength_low"], r["strength_high"]) == (want[k].strength or (None, None))
            assert r["seen"] == want[k].seen.isoformat()
        text = payloads(g.state, who)
        for name in names:
            assert name not in text, (n, name)


def test_the_catch_up_reply_holds_no_report_event(tmp_path: Path) -> None:
    g = _scripted(tmp_path)
    g.walk(day(1), day(5))
    on(g, day(5))
    for who in SEATS:
        kinds = {f.event.kind for f in catchup.feed(g.state, g.log, seat(who), 0, 10_000)}
        assert "report_made" not in kinds


# --- the seat fixture -----------------------------------------------------------------------


FIXTURES = Path(__file__).parents[1] / "web" / "test" / "fixtures"


def fixture_game(tmp: Path) -> State:
    """The game the seat fixture's ``reports_map`` is Ilse's map of: her letters on Norra's
    contacts arrived on day 3."""
    g, _ = letter_game(tmp)
    on(g, day(3))
    return g.state


def test_the_seat_fixture_carries_a_reports_map_in_the_snapshot_shape(tmp_path: Path) -> None:
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["reports_map"]
    assert fixture == block(fixture_game(tmp_path))["map"]
    assert set(fixture) == set(api.SeatMap.__annotations__)
    reports = fixture["reports"]
    assert reports and all(set(r) == set(api.MapReport.__annotations__) for r in reports)
    sources = get_args(api.MapReport.__annotations__["source"])
    assert set(sources) == {s.value for s in Source}
