"""A written order gets the same result as its form, for the forms the third run added (TFA).

The second run's table (``tests/written_order_cases.py``) holds one sentence for every
form in Autumn 1941 and in Salt Strait, the third run's commanders' forms among them, and
``tests/test_written_order_parity.py`` plays each as twin games. This file plays the third
run's own world, the Civil War, the same way: for each form on its playable cards, one
written sentence and the reading it stands for, filed in twin games from one opened world
with written orders on in the test's copy, both played to the season's close, and the
outcome digests compared. It also holds every commander's locked order, in 1941 and in the
Civil War, held in writing as its form is held, and an order the rules refuse refused in
writing in the form's words.

No live model is called: the aide's reading is the table's, through the second run's
canned transport.
"""

import functools
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from revisionist.core.ids import AssetId
from revisionist.core.realism import locks
from revisionist.core.state import State
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, session_zero
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import locks_api
from tests.commanders_script import NATIONS
from tests.locked_orders_script import Ids, table
from tests.test_written_order_parity import (
    CAMPAIGN,
    Canned,
    Game,
    Kept,
    Opened,
    _offer_form,
    _offer_written,
    _offered,
    entity,
    opened,
    seat,
    written_orders_on,
)
from tests.test_written_order_parity import outcome as world_outcome
from tests.written_order_cases import Case, Effect, agent, detail, move, patrol, war

CIVIL = "civil-war-1862"
POSTS = ("posts", "post_moves", "ended_wars")
"""The parts of the state the third run added that an order may change, beside the second
run's outcome: the holders of posts, the moves of post pending, the wars ended."""


def outcome(state: State) -> dict[str, str]:
    dumped = state.model_dump(mode="json")
    return world_outcome(state) | {k: json.dumps(dumped.get(k), sort_keys=True) for k in POSTS}


def fcivil(
    person: str, lever: str, params: dict[str, str], sentence: str, *reading: Effect, **kw: Any
) -> Case:
    return Case("civil", person, lever, params, sentence, tuple(reading), **kw)


def _measure(title: str, subject: str) -> Effect:
    """A nation's own law as a written bill: its title and its one clause, as declared. The
    form's urgency, which a measure cannot hold, is named beside it."""
    return {"kind": "measure", "title": title, "clauses": [{"kind": "power", "subject": subject}]}


CIVIL_WAR: tuple[Case, ...] = (
    # President Lincoln
    fcivil(
        "lincoln",
        "move_force",
        {"force": "north_atlantic_squadron", "to": "fort_monroe"},
        "Take the North Atlantic Squadron to Fort Monroe.",
        move("north_atlantic_squadron", "fort_monroe"),
    ),
    fcivil(
        "lincoln",
        "declare_war",
        {"target": "french_empire"},
        "Declare war on the French Empire.",
        war("french_empire"),
    ),
    fcivil(
        "lincoln",
        "place_a_spy",
        {"intel": "agent", "area": "virginia"},
        "Put a spy in Virginia.",
        agent("virginia"),
    ),
    fcivil(
        "lincoln",
        "send_bill",
        {"bill": "us_emancipation_measure", "urgency": "ordinary"},
        "Send the emancipation measure to Congress.",
        detail(
            _measure("The emancipation measure", "free the slaves held in the states in rebellion"),
            urgency="ordinary",
        ),
    ),
    fcivil(
        "lincoln",
        "set_campaign",
        {
            "intel": "patrol",
            "piece": "army_of_the_potomac",
            "order": "advance",
            "theatre": "eastern_theatre",
        },
        "The Army of the Potomac is to advance in the eastern theatre.",
        detail(patrol("army_of_the_potomac"), order="advance", theatre="eastern_theatre"),
    ),
    # President Davis
    fcivil(
        "davis",
        "move_force",
        {"force": "james_river_squadron", "to": "fort_monroe"},
        "Take the James River Squadron down to Fort Monroe.",
        move("james_river_squadron", "fort_monroe"),
    ),
    fcivil(
        "davis",
        "place_a_spy",
        {"intel": "agent", "area": "maryland"},
        "Put a spy in Maryland.",
        agent("maryland"),
    ),
    fcivil(
        "davis",
        "send_bill",
        {"bill": "cs_draft_law", "urgency": "ordinary"},
        "Send the draft law to Congress.",
        detail(
            _measure("The draft law", "extend conscription to men of 35 to 45"), urgency="ordinary"
        ),
    ),
    # The generals: the moves no lock holds
    fcivil(
        "mcclellan",
        "march",
        {"force": "army_of_the_potomac", "to": "fort_monroe"},
        "March the Army of the Potomac to Fort Monroe.",
        move("army_of_the_potomac", "fort_monroe"),
    ),
    fcivil(
        "buell",
        "march_west",
        {"force": "army_of_the_ohio", "to": "nashville"},
        "March the Army of the Ohio to Nashville.",
        move("army_of_the_ohio", "nashville"),
    ),
    fcivil(
        "lee",
        "advance",
        {"force": "army_of_northern_virginia", "to": "manassas"},
        "Advance the Army of Northern Virginia to Manassas.",
        move("army_of_northern_virginia", "manassas"),
    ),
    fcivil(
        "bragg",
        "invade",
        {"force": "army_of_mississippi", "to": "chattanooga"},
        "Bring the Army of Mississippi to Chattanooga.",
        move("army_of_mississippi", "chattanooga"),
    ),
)
"""Every form on every playable card of the Civil War, each where no lock holds it."""

FIXES: dict[str, str] = {}
"""Each case whose written order and form still differ, and the fix item that owns it."""

CASES: tuple[Case, ...] = tuple(replace(c, fix=FIXES.get(c.name)) for c in CIVIL_WAR)


# --- the Civil War opened -------------------------------------------------------------


@functools.cache
def civil_opened(who: str) -> Opened:
    """The Civil War compiled with written orders on, the people ``who`` plays beside
    claimed, and play opened: the log both twins start from."""
    world = written_orders_on(cmp.load_world(cmp.world_path(CIVIL)))
    people = table(world, who)
    ids = Ids(CAMPAIGN)
    with pytest.MonkeyPatch.context() as mp:
        ids.install(mp)
        store = Kept()
        store.append_all(compile_world(world, CAMPAIGN, cmp.versions()))
        names = load_state(store, CAMPAIGN).entities
        for person in people:
            with ids.drawn_by("claim:" + person):
                session_zero.claim(store, CAMPAIGN, seat(person), names[entity(person)].name)
        with ids.drawn_by("open"):
            realism_tick.open_play(store, CAMPAIGN)
    return Opened(world, list(store.read(CAMPAIGN)), list(people))


def base_of(case: Case) -> Opened:
    return (
        civil_opened(case.person) if case.world == "civil" else opened(case.world, who=case.person)
    )


def play_twins(cases: Sequence[Case]) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """The cases' forms filed in one game and their sentences signed in a twin, both on
    the first wake and both played to the season's close: the notes of anything refused,
    and each twin's outcome."""
    base = base_of(cases[0])
    notes: list[str] = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cmp, "load_world", functools.cache(cmp.load_world))
        by_form = Game(base, mp, Canned())
        notes += [f"{c.name}: {n}" for c in cases if (n := by_form.form(c))]
        form_end = by_form.play()
        in_writing = Game(base, mp, Canned())
        notes += [f"{c.name}: {n}" for c in cases if (n := in_writing.written(c))]
        written_end = in_writing.play()
    return notes, outcome(form_end), outcome(written_end)


def _pieces(case: Case) -> set[str]:
    return {v for k, v in case.params.items() if k in ("force", "piece")}


def batches(cases: Sequence[Case]) -> list[tuple[Case, ...]]:
    """The cases played together: one fix to a batch, and at most one case per person and
    per piece, so no order in a batch replaces or redirects another. Every Civil War seat
    with a form sits at one table."""
    out: list[list[Case]] = []
    for case in cases:
        home = next(
            (
                b
                for b in out
                if b[0].fix == case.fix
                and all(c.person != case.person and not _pieces(c) & _pieces(case) for c in b)
            ),
            None,
        )
        if home is None:
            out.append([case])
        else:
            home.append(case)
    return [tuple(b) for b in out]


def _batch(batch: tuple[Case, ...]) -> Any:
    fix = batch[0].fix
    marks = [pytest.mark.xfail(strict=True, reason=fix)] if fix else []
    return pytest.param(batch, marks=marks, id="+".join(c.name for c in batch))


def _forms() -> set[tuple[str, str, str]]:
    world = cmp.load_world(cmp.world_path(CIVIL))
    return {("civil", c.person, lv.name) for c in world.cards if c.playable for lv in c.levers}


def test_the_table_has_a_sentence_for_every_civil_war_form_and_no_other() -> None:
    assert {(c.world, c.person, c.lever) for c in CASES} == _forms()
    assert len({c.name for c in CASES}) == len(CASES)
    assert set(FIXES) <= {c.name for c in CASES}


def test_every_civil_war_seat_with_a_form_sits_at_one_table() -> None:
    people = {c.person for c in CASES}
    assert people <= set(civil_opened(CASES[0].person).people)
    played = batches(CASES)
    assert sorted(c.name for b in played for c in b) == sorted(c.name for c in CASES)


@pytest.mark.parametrize("batch", [_batch(b) for b in batches(CASES)])
def test_a_written_civil_war_order_gets_the_same_outcome_as_its_form(
    batch: tuple[Case, ...],
) -> None:
    notes, by_form, in_writing = play_twins(batch)
    assert notes == []
    assert [k for k in by_form if by_form[k] != in_writing[k]] == []


# --- the locked orders ------------------------------------------------------------------


def _reading(world: str, params: dict[str, str]) -> tuple[Effect, ...]:
    """The reading of a commander's movement form: the move, and any strength beside it."""
    moved = move(params["force"], params["to"])
    if "strength" in params:
        return (detail(moved, strength=params["strength"]),)
    return (moved,)


LOCKED: tuple[Case, ...] = (
    *(
        Case(
            "1941",
            n.commander,
            n.order[0],
            dict(n.order[1]),
            f"{n.commander}: {n.order[0]}.",
            _reading("1941", dict(n.order[1])),
        )
        for n in NATIONS
        if n.commander != "king"
    ),
    fcivil(
        "mcclellan",
        "march",
        {"force": "army_of_the_potomac", "to": "manassas"},
        "March the Army of the Potomac to Manassas.",
        move("army_of_the_potomac", "manassas"),
    ),
    fcivil(
        "lincoln",
        "declare_war",
        {"target": "uk"},
        "Declare war on Britain.",
        war("uk"),
    ),
)
"""Each commander's order a lock holds, 1941's (Admiral King's are the second run's) and
the Civil War's, and the President's declaration the cabinet decides."""


def _held(state: State, person: str) -> list[tuple[Any, ...]]:
    """Each held order of ``person``'s: its filing day, decider and held words."""
    return [
        (h.filed, h.decider, locks.held_words(state, h))
        for h in state.held.values()
        if h.issuer == seat(person)
    ]


@pytest.mark.parametrize("case", LOCKED, ids=lambda c: c.name)
def test_a_locked_written_order_is_held_as_its_form_is(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same decider named in the same held words, on the same filing day."""
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    by_form = Game(base_of(case), monkeypatch, Canned())
    in_writing = Game(base_of(case), monkeypatch, Canned())
    assert by_form.form(case) == in_writing.written(case) == ""
    held = _held(by_form.state, case.person)
    assert len(held) == 1
    assert held[0][0] == by_form.state.in_world_date
    assert _held(in_writing.state, case.person) == held


# --- an order the rules refuse ----------------------------------------------------------

BEYOND_REACH = fcivil(
    "mcclellan",
    "march",
    {"force": "army_of_the_potomac", "to": "port_royal"},
    "March the Army of the Potomac to Port Royal.",
    move("army_of_the_potomac", "port_royal"),
)
"""An army sent past the reach of its nation's bases."""


def test_a_written_order_the_rules_refuse_is_refused_in_the_forms_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    by_form = Game(base_of(BEYOND_REACH), monkeypatch, Canned())
    before = by_form.store.last_seq(CAMPAIGN)
    told = by_form.form(BEYOND_REACH)
    assert told.startswith("form refused: ") and "beyond the reach" in told
    assert by_form.store.last_seq(CAMPAIGN) == before
    in_writing = Game(base_of(BEYOND_REACH), monkeypatch, Canned())
    written = in_writing.written(BEYOND_REACH)
    assert written == "written refused: " + told.removeprefix("form refused: ")
    assert outcome(in_writing.state) == outcome(by_form.state)


# --- the move of post: the appointment and the dismissal -------------------------------

MOVES = (
    ("civil", "lincoln", "mcclellan", "potomac_command"),
    ("civil", "davis", "lee", "northern_virginia_command"),
    ("salt", "oren_vale", "brask", "varda_galley_command"),
)
"""Each head who moves a commander's post, in each world: the head, the holder, the post."""


def _relief(move: tuple[str, str, str, str]) -> Case:
    return Case(move[0], move[1], "move", {}, "Relieve the commander.", ())


@pytest.mark.parametrize("move", MOVES, ids=lambda m: f"{m[0]}.{m[1]}.relieves.{m[2]}")
def test_a_head_relieves_a_commander_and_the_written_order_does_the_same(
    move: tuple[str, str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The move of post's form, the written order it is filed as, and the same order in
    the head's own words: the post changes hands, and both twins end alike."""
    _, head, holder, key = move
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    base = base_of(_relief(move))
    post = AssetId(object_id(CAMPAIGN, "asset", key))
    still = outcome(Game(base, monkeypatch, Canned()).play())
    by_form = Game(base, monkeypatch, Canned())
    ask = locks_api.move_ask(by_form.state, seat(head), entity(holder), post, "relieve")
    with by_form.ids.drawn_by("order:move"):
        try:
            realism_tick.commit_order(by_form.store, CAMPAIGN, seat(head), (ask,))
        except ValueError as exc:
            pytest.fail(f"form refused: {exc}")
    by_form_end = outcome(by_form.play())
    assert ask.effect is not None
    reading = ask.effect.model_dump(mode="json") | {"person": holder}
    in_writing = Game(base, monkeypatch, Canned())
    written = replace(_relief(move), sentence=ask.ask, reading=(reading,))
    assert in_writing.written(written) == ""
    in_writing_end = outcome(in_writing.play())
    assert by_form_end["posts"] != still["posts"]
    assert [k for k in by_form_end if by_form_end[k] != in_writing_end[k]] == []


NO_REMOVAL = ("1941", "roosevelt", "king", "atlantic_fleet_command")
"""A seated commander whose post has no lesser post and no way its holder is put out of
it, as every commander's post in 1941 is: a relief would take his last authority, and no
office question may open on it."""


def test_a_relief_no_office_question_may_follow_is_refused_in_writing_alike(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refused when filed, in the office question's own words, and logged nowhere; not
    filed and then let fall void unseen the day after."""
    _, head, holder, key = NO_REMOVAL
    monkeypatch.setattr(cmp, "load_world", functools.cache(cmp.load_world))
    base = base_of(_relief(NO_REMOVAL))
    post = AssetId(object_id(CAMPAIGN, "asset", key))
    by_form = Game(base, monkeypatch, Canned())
    before = by_form.store.last_seq(CAMPAIGN)
    ask = locks_api.move_ask(by_form.state, seat(head), entity(holder), post, "relieve")
    assert locks_api.check_asks(by_form.state, seat(head), (ask,))["check"] == "beyond"
    with pytest.raises(ValueError, match=r"Nobody can put the holder of .* out of it") as told:
        realism_tick.commit_order(by_form.store, CAMPAIGN, seat(head), (ask,))
    assert by_form.store.last_seq(CAMPAIGN) == before
    assert ask.effect is not None
    reading = ask.effect.model_dump(mode="json") | {"person": holder}
    in_writing = Game(base, monkeypatch, Canned())
    written = replace(_relief(NO_REMOVAL), sentence=ask.ask, reading=(reading,))
    assert in_writing.written(written) == f"written refused: {told.value}"


# --- the peace clauses, in the toy world of the peace tests -----------------------------


def _peace(tmp: Path) -> MemoryStore:
    """The peace toy world, Norra and Sudland at war, with written orders and the clause
    reader on."""
    from tests.test_peace import RULES
    from tests.test_peace import game as peace_game

    tmp.mkdir(exist_ok=True)
    store = MemoryStore()
    store.append_all(peace_game(tmp, rules=(*RULES, "written_orders", "clause_reader")).log)
    return store


def _peace_clauses(*keys: str) -> list[dict[str, Any]]:
    from tests.test_agreements import NORRA, SUDLAND

    known: dict[str, dict[str, Any]] = {
        "armistice": {"type": "armistice", "binds": NORRA, "nation": SUDLAND, "days": 10},
        "end_war": {"type": "end_war", "binds": NORRA, "nation": SUDLAND},
        "end_war_back": {"type": "end_war", "binds": SUDLAND, "nation": NORRA},
    }
    return [dict(known[k]) for k in keys]


PEACES = [("armistice",), ("end_war", "end_war_back"), ("armistice", "end_war", "end_war_back")]


@pytest.mark.parametrize("clauses", PEACES, ids=["armistice", "end-war", "armistice-and-end-war"])
def test_a_written_offer_of_peace_files_what_its_form_files(
    tmp_path: Path, clauses: tuple[str, ...]
) -> None:
    by_form, in_writing = _peace(tmp_path / "form"), _peace(tmp_path / "written")
    told, form = _offer_form(by_form, _peace_clauses(*clauses))
    written_told, written = _offer_written(in_writing, _peace_clauses(*clauses))
    assert (told, written_told) == ("", "")
    assert written.asks[0].effect == form.asks[0].effect
    assert (written.version, written.terms) == (form.version, form.terms)
    assert _offered(in_writing) == _offered(by_form) != []


def test_with_peace_off_a_written_offer_of_peace_is_refused_as_its_form_is(
    tmp_path: Path,
) -> None:
    from tests.test_peace import RULES
    from tests.test_peace import game as peace_game

    def store(tmp: Path) -> MemoryStore:
        tmp.mkdir(exist_ok=True)
        rules = (*(r for r in RULES if r != "peace"), "written_orders", "clause_reader")
        out = MemoryStore()
        out.append_all(peace_game(tmp, rules=rules).log)
        return out

    by_form, in_writing = store(tmp_path / "form"), store(tmp_path / "written")
    told, _ = _offer_form(by_form, _peace_clauses("armistice"))
    written_told, _ = _offer_written(in_writing, _peace_clauses("armistice"))
    assert told.startswith("form refused: ")
    assert written_told == told.replace("form refused", "written unreadable", 1)
    assert _offered(in_writing) == _offered(by_form) == []
