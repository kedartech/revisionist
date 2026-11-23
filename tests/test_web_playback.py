"""The playback feed (PBF): each page of the catch-up reply carries ``steps``, what the
seat's view held in that wake, in the order it happened.

The steps come from the catch-up seam's events alone (``catchup.seat_events``): the
seat's own order steps, its own nation's pieces stepping from area to area, its papers on
the day they arrive, holders as they change, and its stakes. Nothing says who committed
or closed a wake or how a seat was played, and a move the record made is shaped exactly
like an ordered one. There is no new endpoint: the steps ride the ``catchup`` reply.

The server cases play the territory toy (``tests/worlds/territory-toy.yaml``) with
``territories`` on, a field order on each card, a harbour count for Ilse every 13 days,
and a scripted leg for the Norra Herald and one for the Sudland Levy. The fog case plays
``autumn-1941`` with every playable leader seated, up to the game's human seats.
"""

import json
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, EventId, FeatureId, SeatId, derived_id
from revisionist.core.ontology import Controller
from revisionist.core.project import project
from revisionist.core.realism import locks
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.effect import MoveForce
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, private_to
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick, session_zero
from revisionist.engine import wake as wk
from revisionist.engine.prose import Author, Written, template_prose
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import catchup_api, map_api, playback
from revisionist.engine.web import realism_api as api
from revisionist.engine.web.record_api import _token
from tests import test_adjacency_moves as adj
from tests import test_realism_locks as lk
from tests import test_territory_model as tm
from tests.test_territory_model import CAMPAIGN as TOY
from tests.test_web import PASSWORD, Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post
from tests.test_web_wake import begin, log_of, seat_of, state_of

FIXTURES = Path(__file__).parents[1] / "web" / "test" / "fixtures"
CLOSED = ("wake_committed", "wake_closed", "seat_handover", "by_aide", "timed_out", "aide")
CAUSES = ("scripted", "ordered", "forced", "cause")
KINDS = ("order", "move", "halt", "paper", "holder", "stake", "held")
World = dict[str, Any]


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(map_api.MARK_SECRET_ENV, "34" * 32)


def shape(kind: str) -> set[str]:
    """The keys of a step of ``kind``, from its declared shape in ``realism_api``."""
    assert kind in KINDS, kind
    return set(getattr(api, f"Playback{kind.title()}").__annotations__)


def playback_steps(fed: Iterable[catchup.SeatEvent], state: State, seat: SeatId) -> Any:
    from revisionist.engine.web import playback

    return playback.steps(fed, state, seat)


# --- The territory toy, served ------------------------------------------------------------


def harbour_count(w: World) -> None:
    """A paper for Ilse arriving 3 April and 16 April, around the levy's two steps."""
    w["feeds"] = [
        {
            "key": "harbour_count",
            "name": "The harbour count",
            "author": "ilse",
            "kind": "report",
            "channel": "letter",
            "every_days": 13,
            "latency_days": 1,
            "reports": ["norra_shipping"],
            "source": "toy",
        }
    ]
    (card,) = [c for c in w["cards"] if c["person"] == "ilse"]
    card["feeds"] = ["harbour_count"]


def legs(w: World) -> None:
    """The record moves the Norra Herald to the Gulf Roads (an envoy keeps out of enemy
    ground, ENV) and the Sudland Levy to Norrhavn."""
    adj.set_feature("norra_herald", legs=[{"since": "1900-04-05", "places": ["gulf_roads"]}])(w)
    adj.set_feature("sudland_levy", legs=[{"since": "1900-04-04", "places": ["norrhavn"]}])(w)


def holders_on(w: World) -> None:
    w["rules"] = ["territories", "holders"]


def toy_game(
    web: Web,  # noqa: F811
    tmp: Path,
    *more: Callable[[World], None],
) -> tuple[Realism, Client, Client]:
    def change(w: World) -> None:
        adj.with_rule(w)
        for c in (adj.levers, harbour_count, legs, *more):
            c(w)

    tm.variant(tmp, change)
    game = Realism(web, str(tmp / "world.yaml"))
    ada = game.seat("ada", "ilse")
    bea = game.seat("bea", "tomas")
    make_host(game, bea)
    begin(game)
    return game, ada, bea


def send_the_levy(game: Realism, ada: Client) -> None:
    """Ilse sends the Norra Levy to Sudby and passes her own step on the order."""
    status, out = post(
        ada, "lever", lever="move_piece", params={"force": "norra_levy", "to": "sudby"}
    )
    assert status == 200 and not out["refused"], out
    (drafted,) = [e.payload for e in log_of(game) if isinstance(e.payload, ev.OrderDrafted)]
    status, out = post(ada, "step", order_id=str(drafted.order.order_id), action="pass")
    assert status == 200 and not out["refused"], out


def away_for_the_march(game: Realism, ada: Client, bea: Client, web: Web) -> Client:  # noqa: F811
    """Wake 0: Ilse sends the levy and commits. Wake 1, while it marches, Ilse is away:
    Tomas commits and closes, and the aide plays her. Her player comes back in a fresh
    browser."""
    send_the_levy(game, ada)
    for who in (ada, bea, bea):
        status, out = post(who, "commit")
        assert status == 200 and not out["refused"], out
    status, out = post(bea, "close")
    assert status == 200 and not out["refused"], out
    fresh = web.client()
    status, out = fresh.call("/api/signin", {"handle": "ada", "password": PASSWORD})
    assert status == 200, out
    return fresh


def caught_up(client: Client, **body: Any) -> list[dict[str, Any]]:
    status, out = post(client, "catchup", **body)
    assert status == 200 and "pages" in out, (status, out)
    return list(out["pages"])


def stepped(game: Realism) -> list[ev.PieceStepped]:
    return [e.payload for e in log_of(game) if isinstance(e.payload, ev.PieceStepped)]


def keys_of(game: Realism, nation: str) -> set[str]:
    """The seat keys of every step a nation's pieces took, as its own seats know them."""
    own = EntityId(game.ids[nation])
    return {map_api.step_key(game.campaign, p) for p in stepped(game) if p.nation == own}


@pytest.fixture
def march(web: Web, tmp_path: Path) -> tuple[Realism, Client]:  # noqa: F811
    game, ada, bea = toy_game(web, tmp_path)
    return game, away_for_the_march(game, ada, bea, web)


# --- Rule 1: the missed wake's steps, in order --------------------------------------------


def test_a_missed_wake_plays_both_own_moves_between_two_papers_and_no_enemy_move(
    march: tuple[Realism, Client],
) -> None:
    game, fresh = march
    (page,) = caught_up(fresh)
    assert page["number"] == 1
    steps = page["steps"]
    kinds = [s["kind"] for s in steps]
    (sent,) = {map_api.step_key(game.campaign, p) for p in stepped(game) if p.cause == "ordered"}
    levy = [s for s in steps if s["kind"] == "move" and s["piece"] == sent]
    assert [(m["left"], m["entered"]) for m in levy] == [
        ("norra_plain", "norra_hills"),
        ("norra_hills", "sudland_coast"),
    ]
    papers = [i for i, k in enumerate(kinds) if k == "paper"]
    assert len(papers) == 2, kinds
    assert papers[0] < steps.index(levy[0]) < steps.index(levy[1]) < papers[1], kinds
    assert [s["on"] for s in steps] == sorted(s["on"] for s in steps)
    assert keys_of(game, "sudland"), "the Sudland Levy stepped in this wake"
    moved = {s["piece"] for s in steps if s["kind"] == "move"}
    assert moved == keys_of(game, "norra")
    assert not moved & keys_of(game, "sudland")


def test_the_seats_own_order_steps_are_played_against_its_record_line(
    march: tuple[Realism, Client],
) -> None:
    _, fresh = march
    (zero,) = caught_up(fresh, first=0, last=0)
    orders = [s for s in zero["steps"] if s["kind"] == "order"]
    assert [s["what"] for s in orders] == ["filed", "pass", "enacted"]
    assert {s["order"] for s in orders} == set(zero["filed"])


# --- Rule 3: a scripted move is shaped exactly like a player's ----------------------------


def test_a_scripted_move_is_shaped_exactly_like_an_ordered_one(
    march: tuple[Realism, Client],
) -> None:
    game, fresh = march
    (page,) = caught_up(fresh)
    moves = [s for s in page["steps"] if s["kind"] == "move"]
    cause = {map_api.step_key(game.campaign, p): p.cause.value for p in stepped(game)}
    assert {cause[m["piece"]] for m in moves} == {"scripted", "ordered"}
    shapes = {tuple((k, type(v).__name__) for k, v in sorted(m.items())) for m in moves}
    assert len(shapes) == 1, shapes
    assert set(moves[0]) == shape("move")
    sent = json.dumps(moves)
    for word in CAUSES:
        assert word not in sent, word


# --- Rule 2: nothing of commits, closes or who played the seat ----------------------------


def test_no_commit_close_or_mark_of_who_played_reaches_the_steps(
    march: tuple[Realism, Client],
) -> None:
    game, fresh = march
    aide = [p for e in log_of(game) if isinstance(p := e.payload, ev.WakeCommitted) and p.by_aide]
    assert [p.seat_id for p in aide] == [seat_of(game, "ilse")], "the aide played wake 1"
    sent = json.dumps([p["steps"] for p in caught_up(fresh, first=0, last=1)])
    for word in CLOSED:
        assert word not in sent, word


def test_commit_close_and_hand_over_events_make_no_step_even_when_handed_in(
    tmp_path: Path,
) -> None:
    state = adj.play(tmp_path)
    seat = adj.seat("ilse")
    ilse = state.seats[seat].embodies
    payloads: list[Any] = [
        ev.WakeCommitted(wake=1, seat_id=seat, by_aide=True, aide_orders=()),
        ev.WakeClosed(wake=1, timed_out=(seat,)),
        ev.SeatHandover(entity_id=ilse, controller=Controller.AI),
        ev.FeatureSet(feature=adj.piece(state, "norra_levy")),
        ev.DateAdvanced(to=date(1900, 4, 16)),
        ev.WakeOpened(wake=1, deadline=datetime(2026, 11, 19, tzinfo=UTC)),
    ]
    fed = [
        catchup.SeatEvent(
            wake=1,
            event=ev.Event(
                event_id=EventId(derived_id(state.campaign_id, "pbf", n)),
                campaign_id=state.campaign_id,
                seq=state.last_seq + 1 + n,
                tick=0,
                scope=private_to(seat),
                payload=p,
                versions=cmp.versions(),
            ),
        )
        for n, p in enumerate(payloads)
    ]
    assert playback_steps(fed, state, seat) == {}


# --- Rule 1: from the seam's events, never from state --------------------------------------


def test_a_past_step_plays_where_the_piece_went_then_not_where_it_stands_now(
    march: tuple[Realism, Client],
) -> None:
    game, fresh = march
    state = state_of(game)
    assert state.map is not None
    keys = {t.area: t.key for t in state.map.territories}
    levy = state.features[FeatureId(game.ids["norra_levy"])]
    assert keys[levy.places[0]] == "sudland_coast"
    (page,) = caught_up(fresh)
    entered = [s["entered"] for s in page["steps"] if s["kind"] == "move"]
    assert entered[-2:] == ["norra_hills", "sudland_coast"], "the levy's road, not its place now"


def test_a_holder_change_is_played_with_both_nations(tmp_path: Path) -> None:
    state = adj.play(tmp_path)
    seat = adj.seat("ilse")
    coast, norra, sudland = (adj.entity(k) for k in ("sudland_coast", "norra", "sudland"))
    held = ev.AreaHeld(area=coast, holder=norra, was=sudland, on=date(1900, 4, 20))
    fed = [
        catchup.SeatEvent(
            wake=2,
            event=ev.Event(
                event_id=EventId(derived_id(state.campaign_id, "pbf-held")),
                campaign_id=state.campaign_id,
                seq=state.last_seq + 1,
                tick=0,
                scope=PUBLIC,
                payload=held,
                versions=cmp.versions(),
            ),
        )
    ]
    ((step,),) = playback_steps(fed, state, seat).values()
    assert step == {
        "kind": "holder",
        "on": "1900-04-20",
        "area": "sudland_coast",
        "holder": {"key": norra, "name": "Norra", "relation": "own"},
        "was": {"key": sudland, "name": "Sudland", "relation": "enemy"},
    }


# --- No new endpoint: an optional key on the first run's page ------------------------------


def test_steps_ride_the_catchup_page_and_no_playback_endpoint_answers(
    march: tuple[Realism, Client],
) -> None:
    _, fresh = march
    pages = caught_up(fresh, first=0, last=1)
    assert [p["number"] for p in pages] == [0, 1]
    assert all(isinstance(p["steps"], list) for p in pages)
    from revisionist.engine.web.catchup_api import CatchupPage

    assert "steps" in CatchupPage.__optional_keys__
    status, _ = post(fresh, "playback")
    assert status != 200


# --- The fog, over a whole game and every playable seat ----------------------------------

AUTUMN = "autumn-1941"
CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAW")


class Templates:
    def write(self, author: Author, pages: Any) -> Written:
        return Written(prose={p.doc_id: template_prose(author, p) for p in pages})


def held(state: State, events: list[ev.Event], seat: SeatId) -> dict[str, set[str]]:
    """What each kind of step may point at for ``seat``, read from its own view and from
    the events whose envelope it may open."""
    view = project(state, seat)
    parts = {f"{o}.{n}" for o, r in view.routed.items() for n in range(len(r.parts))}
    open_ = [e.payload for e in events if e.scope.visible_to(seat)]
    return {
        "paper": {str(d) for d in view.documents},
        "order": {_token(str(o)) for o in view.orders} | {_token(k) for k in parts},
        "move": {
            map_api.step_key(state.campaign_id, p) for p in open_ if isinstance(p, ev.PieceStepped)
        },
        "halt": {
            map_api.mark_key(state.campaign_id, p.nation, p.mark)
            for p in open_
            if isinstance(p, ev.StepRefused)
        },
        "holder": {"*"},
        "stake": {c.name for c in view.contests.values()}
        | {m.text for m in view.mandates.values()}
        | {g.text for g in view.goals.values()},
    }


POINTS = {"paper": "paper", "order": "order", "move": "piece", "halt": "piece", "stake": "name"}


def assert_fogged(state: State, events: list[ev.Event], seat: SeatId, last: int) -> int:
    allowed = held(state, events, seat)
    fed = catchup.feed(state, events, seat, 0, last)
    n = 0
    for wake, steps in playback_steps(fed, state, seat).items():
        for step in steps:
            kind = step["kind"]
            assert set(step) == shape(kind), step
            if kind not in ("holder", "held"):
                assert step[POINTS[kind]] in allowed[kind], (seat, wake, step)
            n += 1
    return n


def test_no_playable_seat_gets_a_step_its_view_does_not_hold() -> None:
    store = MemoryStore()
    decl = cmp.load_world(cmp.world_path(AUTUMN))
    store.append_all(compile_world(decl, CAMPAIGN, cmp.versions()))
    state = load_state(store, CAMPAIGN)
    people = sorted(p for p, c in state.cards.items() if c.playable)
    people = people[: state.settings.max_human_seats]
    assert len(people) >= 2
    for person in people:
        name = state.entities[person].name
        session_zero.claim(store, CAMPAIGN, SeatId(derived_id(CAMPAIGN, "seat", person)), name)
    realism_tick.open_play(store, CAMPAIGN)
    for _ in range(6):
        realism_tick.run_realism_tick(store, CAMPAIGN, prose=Templates())
    state, events = load_state(store, CAMPAIGN), list(store.read(CAMPAIGN))
    assert {s.embodies for s in state.seats.values()} >= set(people)
    counts = {seat: assert_fogged(state, events, seat, 99) for seat in state.seats}
    assert all(counts.values()), counts
    everything = [catchup.SeatEvent(wake=0, event=e) for e in events]
    leaks = [
        seat
        for seat in state.seats
        for step in playback_steps(everything, state, seat).get(0, [])
        if step["kind"] == "paper" and step["paper"] not in held(state, events, seat)["paper"]
    ]
    assert len(set(leaks)) == len(state.seats), (
        "the check bites: the whole log would leak to every seat"
    )


def test_no_seat_of_the_toy_gets_a_step_its_view_does_not_hold(
    web: Web,  # noqa: F811
    tmp_path: Path,
) -> None:
    game, ada, bea = toy_game(web, tmp_path, holders_on)
    send_the_levy(game, ada)
    for _ in range(4):
        for who in (ada, bea):
            status, out = post(who, "commit")
            assert status == 200 and not out["refused"], out
    state, events = state_of(game), log_of(game)
    assert state.wake is not None
    counts = {s: assert_fogged(state, events, s, state.wake.number) for s in state.seats}
    assert all(counts.values()), counts


# --- The seat fixture -----------------------------------------------------------------


def test_the_seat_fixture_carries_a_catchup_page_with_steps_of_the_reply_shape(
    march: tuple[Realism, Client],
) -> None:
    _, fresh = march
    (page,) = caught_up(fresh)
    fixture = json.loads((FIXTURES / "realism-seat.json").read_text())["catchup_page"]
    assert set(fixture) == set(page)
    for step in fixture["steps"]:
        assert set(step) == shape(step["kind"]), step
    assert [s["kind"] for s in fixture["steps"]] == [s["kind"] for s in page["steps"]]


# --- Held orders: each end told to its own seat ----------------------------------------
#
# The lock tests' world (``tests/test_realism_locks.py``): the toy with ``locks`` on,
# Ilse Varg the chancellor, her general Kara Lind and Kara's aide Olaf Brun. A written
# move of the Norra Levy to the Isle needs Ilse while she has not set a watch on the Gulf.

NOW = datetime(2026, 1, 5, 9, tzinfo=UTC)
LEVY_TO_ISLE = MoveForce(force=lk.LEVY, to=lk.ISLE)
OLD_KINDS = frozenset(
    {
        "order_drafted",
        "order_routed",
        "order_step_taken",
        "order_settled",
        "order_executed",
        "piece_stepped",
        "step_refused",
        "document_issued",
        "area_held",
        "contest_moved",
        "contest_decided",
        "mandate_issued",
        "mandate_settled",
        "goal_progressed",
        "goal_met",
        "goal_undone",
    }
)


def watched_move(w: World) -> None:
    w["locks"].append(
        {
            "key": "levy_to_isle",
            "order": {"effect": "move_force", "zone": "isle"},
            "when": dict(lk.ROWS[0]["when"]),
            "decider": {"person": "ilse"},
        }
    )


def lock_game(tmp: Path, *changes: Callable[[World], None]) -> MemoryStore:
    store = lk.played(tmp, watched_move, *changes)
    wk.open_wake(store, TOY, NOW)
    return store


def wake_tick(store: MemoryStore, *present: EntityId) -> None:
    """The open wake closes (the aide plays every seat not ``present``), the world ticks
    and the next wake opens."""
    for person in present:
        wk.commit(store, TOY, lk.seat(person), NOW)
    wk.close_wake(store, TOY, NOW, None)
    realism_tick.run_realism_tick(store, TOY)
    wk.open_wake(store, TOY, NOW)


def stand_down_the_levy(store: MemoryStore) -> None:
    """The levy is out of service until 1901, as a resolver would set it."""
    state = load_state(store, TOY)
    levy = state.features[lk.LEVY].model_copy(update={"in_service": date(1901, 1, 1)})
    realism_tick._append(store, state, ev.FeatureSet(feature=levy), lk.seat(lk.ILSE))


def until_ended(store: MemoryStore, order_id: Any, *present: EntityId) -> None:
    for _ in range(8):
        if lk.ends(store, order_id):
            return
        wake_tick(store, *present)
    raise AssertionError("the held order never ended")


def failing(tmp: Path, *present: EntityId, olaf_held: bool = False) -> tuple[MemoryStore, Any]:
    """Kara's written move to the Isle is held; the levy stands down; Ilse sets the watch
    and the lock opens, but the re-check fails."""
    store = lock_game(tmp)
    held = lk.commit(store, lk.KARA, lk.written(LEVY_TO_ISLE))
    assert isinstance(held, locks.HeldOrder)
    if olaf_held:
        assert isinstance(lk.commit(store, lk.OLAF, lk.gulf_fire()), locks.HeldOrder)
    stand_down_the_levy(store)
    lk.commit(store, lk.ILSE, lk.guard_the_gulf())
    until_ended(store, held.order_id, lk.ILSE, *present)
    return store, held


def caught(store: MemoryStore, person: EntityId, **body: Any) -> list[dict[str, Any]]:
    state, events = load_state(store, TOY), list(store.read(TOY))
    return list(catchup_api.reply(state, events, lk.seat(person), body)["pages"])


def held_lines(pages: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    return [(p["number"], s) for p in pages for s in p["steps"] if s["kind"] == "held"]


def everything(store: MemoryStore) -> int:
    state = load_state(store, TOY)
    assert state.wake is not None
    return state.wake.number


FAILED = "Your held order failed: The Norra Levy is not in service until 1 January 1901."


def test_a_held_order_whose_re_check_fails_is_told_to_its_seat_with_the_reason(
    tmp_path: Path,
) -> None:
    store, held = failing(tmp_path)
    (end,) = lk.ends(store, held.order_id)
    lines = held_lines(caught(store, lk.KARA, first=0, last=everything(store)))
    assert [s["what"] for _, s in lines] == ["held", "failed"]
    (wake, failed) = lines[-1]
    assert set(failed) == shape("held")
    assert failed["line"] == FAILED and failed["on"] == end.on.isoformat()
    # On the page of the wake it happened in, as the seat's seam places the end.
    state, events = load_state(store, TOY), list(store.read(TOY))
    fed = catchup.feed(state, events, lk.seat(lk.KARA), 0, everything(store))
    (where,) = [f.wake for f in fed if isinstance(f.event.payload, ev.HeldOrderEnded)]
    assert wake == where
    held_line = lines[0][1]
    assert held_line["line"] == "Held until Ilse Varg allows it: as written."
    assert held_line["on"] == held.filed.isoformat()


def test_a_held_order_that_lands_is_told_with_its_day_and_words(tmp_path: Path) -> None:
    store = lock_game(tmp_path)
    order = lk.file(store, "isle")
    lk.commit(store, lk.ILSE, lk.guard_the_gulf())
    until_ended(store, order.order_id, lk.ILSE, lk.KARA)
    (end,) = lk.ends(store, order.order_id)
    assert end.end is locks.HeldEnd.LANDED
    lines = held_lines(caught(store, lk.KARA, first=0, last=everything(store)))
    assert [(s["what"], s["on"], s["line"]) for _, s in lines] == [
        (
            "held",
            order.filed.isoformat(),
            "Held until Ilse Varg allows it: March (Force Norra levy, To Isle).",
        ),
        (
            "landed",
            end.on.isoformat(),
            "Your held order went ahead: March (Force Norra levy, To Isle).",
        ),
    ]


def test_a_replaced_held_order_is_told_with_the_later_orders_words(tmp_path: Path) -> None:
    store = lock_game(tmp_path)
    lk.file(store, "isle")
    lk.commit(store, lk.KARA, Ask(ask="The levy to the Isle.", effect=LEVY_TO_ISLE))
    first = lk.commit(store, lk.OLAF, lk.kites_to_isle())
    lk.commit(store, lk.OLAF, lk.kites_to_isle("The kites to the Isle, now."))
    last = everything(store)
    kara = [s["line"] for _, s in held_lines(caught(store, lk.KARA, first=0, last=last))]
    assert kara[-1] == "Your held order was replaced by a later one: The levy to the Isle."
    olaf = [
        (s["what"], s["line"]) for _, s in held_lines(caught(store, lk.OLAF, first=0, last=last))
    ]
    assert olaf == [
        ("held", "Held until Ilse Varg allows it: Send the kites to the Isle."),
        ("held", "Held until Ilse Varg allows it: The kites to the Isle, now."),
        ("replaced", "Your held order was replaced by a later one: The kites to the Isle, now."),
    ]
    assert isinstance(first, locks.HeldOrder)


def test_no_other_seat_is_told_of_a_held_order_or_its_end(tmp_path: Path) -> None:
    store, _ = failing(tmp_path)
    last = everything(store)
    for person in (lk.ILSE, lk.OLAF):
        pages = caught(store, person, first=0, last=last)
        assert not held_lines(pages), person
        assert "not in service" not in json.dumps(pages)
    # The playback refuses the lines itself, even given the whole log as one wake.
    state, events = load_state(store, TOY), list(store.read(TOY))
    whole = [catchup.SeatEvent(wake=0, event=e) for e in events]
    for person in (lk.ILSE, lk.OLAF):
        steps = playback_steps(whole, state, lk.seat(person)).get(0, [])
        assert not [s for s in steps if s["kind"] == "held"], person
    mine = playback_steps(whole, state, lk.seat(lk.KARA)).get(0, [])
    assert [s["what"] for s in mine if s["kind"] == "held"] == ["held", "failed"]


def untokened(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pages without order and paper ids: one more event in a twin shifts every
    later id."""
    out = []
    for page in pages:
        kept = {k: v for k, v in page.items() if k not in ("filed", "settled")}
        kept["steps"] = [
            {k: v for k, v in s.items() if k not in ("order", "paper")} for s in page["steps"]
        ]
        out.append(kept)
    return out


def test_another_seats_held_order_leaves_a_seats_catch_up_as_it_was(tmp_path: Path) -> None:
    plain, _ = failing(tmp_path / "plain")
    twin, _ = failing(tmp_path / "twin", olaf_held=True)
    last = everything(plain)
    assert everything(twin) == last
    for person in (lk.KARA, lk.ILSE):
        a = untokened(caught(plain, person, first=0, last=last))
        assert a == untokened(caught(twin, person, first=0, last=last)), person
    olaf = held_lines(caught(twin, lk.OLAF, first=0, last=last))
    assert [s["what"] for _, s in olaf] == ["held"]


def test_a_seat_that_was_away_reads_the_same_lines_as_one_that_was_present(
    tmp_path: Path,
) -> None:
    away, _ = failing(tmp_path / "away")
    here, _ = failing(tmp_path / "here", lk.KARA)
    last = everything(away)
    assert everything(here) == last
    seen = held_lines(caught(here, lk.KARA, first=0, last=last))
    assert [s["what"] for _, s in seen] == ["held", "failed"]
    assert held_lines(caught(away, lk.KARA, first=0, last=last)) == seen
    # Coming back once the wake that holds the end has closed, with no range named, the
    # away seat reads the end and its reason.
    wake_tick(away, lk.ILSE)
    back = held_lines(caught(away, lk.KARA))
    assert back[-1][1]["line"] == FAILED


def unchanged(store: MemoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every seat's catch-up is what the playback gave before held orders had steps."""
    last = everything(store)
    now = {p: caught(store, p, first=0, last=last) for p in (lk.ILSE, lk.KARA, lk.OLAF)}
    with monkeypatch.context() as m:
        m.setattr(playback, "STEP_KINDS", OLD_KINDS)
        before = {p: caught(store, p, first=0, last=last) for p in now}
    assert now == before
    assert any(p["steps"] for pages in now.values() for p in pages)
    made = {s["kind"] for pages in now.values() for p in pages for s in p["steps"]}
    assert "held" not in made and made <= set(KINDS), made


def test_with_locks_off_the_catch_up_and_playback_are_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = lock_game(tmp_path, lk.unlocked)
    lk.file(store, "isle")
    lk.commit(store, lk.KARA, lk.written(LEVY_TO_ISLE))
    lk.commit(store, lk.ILSE, lk.guard_the_gulf())
    for _ in range(3):
        wake_tick(store, lk.ILSE)
    assert not lk.logged(store, ev.OrderHeld)
    unchanged(store, monkeypatch)


def test_a_game_with_locks_on_and_no_held_order_is_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = lock_game(tmp_path)
    lk.file(store, "norra_hills")
    lk.commit(store, lk.ILSE, lk.guard_the_gulf())
    for _ in range(3):
        wake_tick(store, lk.ILSE)
    assert not lk.logged(store, ev.OrderHeld)
    unchanged(store, monkeypatch)
