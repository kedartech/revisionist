"""The ladder of posts: moved, relieved, restored (LDR).

The toy world of ``tests/test_posts.py`` (``posts`` on: Ilse holds the chancellery, Kara
the command of the levy, Olav a colonel with no post) with two lesser offices, the
garrison of Norrhavn and a staff post at the war ministry. The command's ladder runs
garrison, then staff; the garrison's runs to staff. The chancellery moves all three.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.events import Event
from revisionist.core.fold import FoldError, apply
from revisionist.core.ids import AssetId, EntityId, EventId, SeatId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import effect as rx
from revisionist.core.realism import ladder, posts, route
from revisionist.core.realism.agenda import Ask, PlayStyle
from revisionist.core.realism.land import appointment
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.state import State
from revisionist.core.visibility import PUBLIC, Scope
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from revisionist.engine import catchup, realism_tick, session_zero, wake
from revisionist.engine.store import MemoryStore
from tests.test_posts import (
    CHANCELLERY,
    COMMAND,
    DAY,
    ILSE,
    KARA,
    OLAV,
    TOMAS,
    Game,
    asset_id,
    seat,
    world,
)
from tests.test_territory_model import CAMPAIGN

World = dict[str, Any]
GARRISON, STAFF = asset_id("garrison"), asset_id("staff")
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def ladders(w: World) -> None:
    """Two lesser offices, and who moves whom."""
    w["assets"] += [
        {
            "key": "garrison",
            "kind": "office",
            "name": "Commandant of Norrhavn",
            "controller": "norra",
        },
        {
            "key": "staff",
            "kind": "office",
            "name": "Staff of the War Ministry",
            "controller": "norra",
        },
    ]
    for a in w["assets"]:
        if a["key"] == "levy_command":
            a["ladder"] = ["garrison", "staff"]
        if a["key"] == "garrison":
            a["ladder"] = ["staff"]
        if a["key"] in ("levy_command", "garrison", "staff"):
            a["moved_by"] = ["norra_chancellery"]


def no_ladders(w: World) -> None:
    """The same offices, no ladder and no movers: the old rule."""
    ladders(w)
    for a in w["assets"]:
        a.pop("ladder", None)
        a.pop("moved_by", None)


class Ladders(Game):
    def add(self, payload: ev.Payload, scope: Scope = PUBLIC) -> None:
        state = self.state
        self.store.append_all(
            [
                Event(
                    event_id=EventId(derived_id(CAMPAIGN, "t", str(state.last_seq + 1))),
                    campaign_id=CAMPAIGN,
                    seq=state.last_seq + 1,
                    tick=state.tick,
                    scope=scope,
                    payload=payload,
                    versions=cmp.versions(),
                )
            ]
        )

    def open(self, n: int) -> None:
        self.add(ev.WakeOpened(wake=n, deadline=T0 + timedelta(days=n + 1)))

    def close(self, n: int) -> None:
        self.add(ev.WakeClosed(wake=n))

    def order(self, person: EntityId, post: AssetId, appoint: bool = True) -> list[ev.Payload]:
        """Ilse's order, landed as the engine lands it, and folded."""
        office = self.state.assets[post].name
        effect = rx.Appointment(person=person, office=office, appoint=appoint)
        out, _ = appointment.land(PassWorld(self.state), effect, seat(ILSE), ILSE, DAY)
        for p in out:
            self.add(p, _scope(self.state, p))
        return out

    def walk(self) -> list[ev.Payload]:
        """The day's walk of pending changes, folded."""
        out: list[ev.Payload] = []
        for move_id in ladder.due(self.state):
            for p in ladder.land(self.state, move_id, DAY):
                self.add(p, _scope(self.state, p))
                out.append(p)
        return out

    def held(self, post: AssetId) -> EntityId | None:
        return posts.holder(self.state, post)


def _scope(state: State, p: ev.Payload) -> Scope:
    if isinstance(p, ev.PostMoveOrdered):
        return ladder.scope_of(state, p.move.seat)
    if isinstance(p, ev.PostMoveSettled):
        return ladder.scope_of(state, p.seat)
    if isinstance(p, ev.DocumentIssued):
        return p.document.scope
    if isinstance(p, ev.RelationshipSet):
        return p.relationship.scope
    return PUBLIC


@pytest.fixture
def g(tmp_path: Path) -> Ladders:
    return Ladders(world(tmp_path, ladders))


def test_the_ladders_are_declared_once_as_public_world_data(g: Ladders) -> None:
    state = g.state
    assert state.ladders[COMMAND].ladder == (GARRISON, STAFF)
    assert state.ladders[GARRISON].moved_by == (CHANCELLERY,)
    again = ev.LaddersDeclared(ladders=tuple(state.ladders.values()))
    g.add(again)
    with pytest.raises(FoldError, match="declared once"):
        _ = g.state


def test_a_ladder_rung_must_be_an_office(tmp_path: Path) -> None:
    from revisionist.core.world_compile import WorldError, compile_world

    def bad(w: World) -> None:
        ladders(w)
        for a in w["assets"]:
            if a["key"] == "garrison":
                a["ladder"] = ["norra"]

    with pytest.raises((WorldError, ValueError)):
        compile_world(world(tmp_path, bad), CAMPAIGN, cmp.versions())


@pytest.mark.parametrize(
    ("key", "field", "value"),
    [("staff", "ladder", ["levy_command"]), ("garrison", "moved_by", ["garrison"])],
    ids=["a ladder that loops", "a post that moves itself"],
)
def test_the_compiler_refuses(tmp_path: Path, key: str, field: str, value: list[str]) -> None:
    from revisionist.core.world_compile import WorldError, compile_world

    def bad(w: World) -> None:
        ladders(w)
        for a in w["assets"]:
            if a["key"] == key:
                a[field] = value

    with pytest.raises(WorldError, match=r"loops|move itself"):
        compile_world(world(tmp_path, bad), CAMPAIGN, cmp.versions())


def test_moved_to_a_quiet_command_relieved_to_staff_and_restored(g: Ladders) -> None:
    """The commander moved to the garrison, relieved from it to the staff post, and
    restored to the command; each change lands a wake after it is ordered."""
    g.open(0)
    g.order(OLAV, COMMAND)  # Olav takes the command; Kara falls to its first free rung
    assert g.held(COMMAND) == KARA
    g.close(0)
    assert g.walk() == []  # the wake it was ordered in: not yet
    g.open(1)
    assert g.walk() == []  # the next wake, still open: not yet
    g.close(1)
    g.walk()
    assert (g.held(COMMAND), g.held(GARRISON)) == (OLAV, KARA)

    g.open(2)
    g.order(KARA, GARRISON, appoint=False)  # relieved: the garrison's ladder, staff
    g.close(2)
    g.open(3)
    g.close(3)
    g.walk()
    assert g.held(GARRISON) is None and g.held(STAFF) == KARA

    g.open(4)
    g.order(KARA, COMMAND)  # restored: an appointment like any other
    g.close(4)
    g.open(5)
    g.close(5)
    g.walk()
    assert g.held(COMMAND) == KARA
    assert g.held(STAFF) is None  # Kara gave up the staff post to rise
    assert g.held(GARRISON) == OLAV  # Olav, displaced, falls to the command's first free rung
    assert not g.state.post_moves


def test_the_notice_comes_the_day_it_is_ordered_a_wake_ahead(g: Ladders) -> None:
    g.open(0)
    out = g.order(KARA, COMMAND, appoint=False)
    (paper,) = [p.document for p in out if isinstance(p, ev.DocumentIssued)]
    assert paper.issued == DAY and paper.scope.known_by == frozenset({seat(KARA)})
    assert paper.title == "You are relieved of General of the Norra Levy"
    assert any(f.value == "At the close of the next wake" for f in paper.body)
    assert g.held(COMMAND) == KARA  # the change has not landed


def test_the_holder_an_appointment_puts_down_is_told_a_wake_ahead(g: Ladders) -> None:
    """Olav, whom no seat plays, is appointed to Kara's command: Kara, a seat, falls a
    rung when it lands, so her seat has the notice the day it is ordered. It names the
    post, the mover and the day, not who takes her place."""
    g.open(0)
    out = g.order(OLAV, COMMAND)
    (paper,) = [p.document for p in out if isinstance(p, ev.DocumentIssued)]
    assert paper.issued == DAY and paper.scope.known_by == frozenset({seat(KARA)})
    assert paper.author == ILSE
    assert paper.title == "You are relieved of General of the Norra Levy"
    assert any(f.value == "At the close of the next wake" for f in paper.body)
    assert "Olav" not in paper.model_dump_json()
    assert g.held(COMMAND) == KARA
    landed = [*_close_and_walk(g, 0), *_close_and_walk(g, 1)]
    assert (g.held(COMMAND), g.held(GARRISON)) == (OLAV, KARA)
    assert not any(isinstance(p, ev.DocumentIssued) for p in landed)


def _close_and_walk(g: Ladders, n: int) -> list[ev.Payload]:
    g.close(n)
    out = g.walk()
    g.open(n + 1)
    return out


def test_an_appointment_that_puts_down_a_holder_nobody_plays_sends_no_paper(
    tmp_path: Path,
) -> None:
    g = Unseated(world(tmp_path, ladders))
    g.open(0)
    out = g.order(OLAV, COMMAND)
    assert [type(p) for p in out] == [ev.PostMoveOrdered]


def test_an_appointee_who_is_his_own_holder_gets_one_notice(g: Ladders) -> None:
    """Kara appointed to the garrison, a rung of her own command's ladder: she is the
    one put down, and has the one notice of the appointee."""
    g.open(0)
    out = g.order(KARA, GARRISON)
    (paper,) = [p.document for p in out if isinstance(p, ev.DocumentIssued)]
    assert paper.title == "You are to take up Commandant of Norrhavn"


def test_a_question_the_appointment_opens_tells_the_holder_it_waits_for_the_sitting(
    g: Ladders,
) -> None:
    """Both rungs full: Ilse's appointment of herself would take Kara's last authority,
    so it waits for the office question, and each notice says so."""
    g.open(0)
    g.order(OLAV, GARRISON)
    g.order(TOMAS, STAFF)
    _close_and_walk(g, 0)
    _close_and_walk(g, 1)
    assert (g.held(GARRISON), g.held(STAFF)) == (OLAV, TOMAS)
    out = g.order(ILSE, COMMAND)
    (move,) = [p.move for p in out if isinstance(p, ev.PostMoveOrdered)]
    assert move.question
    papers = {
        s: p.document
        for p in out
        if isinstance(p, ev.DocumentIssued)
        for s in p.document.scope.known_by
    }
    assert set(papers) == {seat(ILSE), seat(KARA)}
    assert papers[seat(KARA)].title == "You are relieved of General of the Norra Levy"
    for paper in papers.values():
        assert any(f.value == "Only at the sitting of the office question" for f in paper.body)


class Unseated(Ladders):
    """The same game with Kara played by nobody."""

    def __init__(self, w: Any) -> None:
        self.store = MemoryStore()
        self.store.append_all(compile_world(w, CAMPAIGN, cmp.versions()))
        for person in (ILSE, TOMAS):
            name = self.state.entities[person].name
            session_zero.claim(self.store, CAMPAIGN, seat(person), name)
        realism_tick.open_play(self.store, CAMPAIGN)


def _seen(g: Ladders, person: EntityId) -> str:
    return project(g.state, seat(person)).model_dump_json()


@pytest.mark.parametrize("game", [Ladders, Unseated], ids=["kara seated", "kara unseated"])
def test_twin_games_with_and_without_the_appointment_read_the_same_to_other_seats(
    tmp_path: Path, game: type[Ladders]
) -> None:
    """Twin games, one where Ilse's appointment of Olav puts Kara down a wake from now and
    one where nothing is ordered: every seat but Kara's reads the same bytes."""
    for d in ("moved", "still"):
        (tmp_path / d).mkdir()
    moved, still = (
        game(world(tmp_path / "moved", ladders)),
        game(world(tmp_path / "still", ladders)),
    )
    for g in (moved, still):
        g.open(0)
    moved.order(OLAV, COMMAND)
    for person in (ILSE, TOMAS):
        assert _seen(moved, person) == _seen(still, person)
    if game is Ladders:
        assert _seen(moved, KARA) != _seen(still, KARA)


def test_a_dismissal_with_no_free_rung_leaves_no_post(g: Ladders) -> None:
    g.open(0)
    g.order(OLAV, STAFF)
    g.close(0)
    g.open(1)
    g.close(1)
    g.walk()
    assert g.held(STAFF) == OLAV
    g.open(2)
    g.order(OLAV, STAFF, appoint=False)  # staff has no ladder; Olav has no seat
    g.close(2)
    g.open(3)
    g.close(3)
    g.walk()
    assert g.held(STAFF) is None


def test_the_last_authority_opens_the_question_instead(g: Ladders) -> None:
    """Kara is a seat. Fill both rungs, then dismiss her: no rung is free, so the move
    would take her last authority. It stands as the office question's cause and never
    lands on a wake."""
    g.open(0)
    g.order(OLAV, GARRISON)
    g.order(TOMAS, STAFF)
    g.close(0)
    g.open(1)
    g.close(1)
    g.walk()
    assert (g.held(GARRISON), g.held(STAFF)) == (OLAV, TOMAS)
    g.open(2)
    out = g.order(KARA, COMMAND, appoint=False)
    (move,) = [p.move for p in out if isinstance(p, ev.PostMoveOrdered)]
    assert move.question
    for n in range(2, 6):
        g.close(n)
        g.walk()
        g.open(n + 1)
    assert g.held(COMMAND) == KARA
    assert move.move_id in g.state.post_moves


def test_a_move_that_comes_to_take_the_last_authority_stands_instead(g: Ladders) -> None:
    """Kara is dismissed while the staff post is free; before it lands, Tomas takes it.
    The move would now take her last authority: it is not done, and stands as the office
    question's cause, with a second notice saying so."""
    g.open(0)
    g.order(OLAV, GARRISON)
    g.close(0)
    g.open(1)
    g.order(TOMAS, STAFF)
    g.close(1)
    g.walk()
    g.open(2)
    (first,) = [
        p.move for p in g.order(KARA, COMMAND, appoint=False) if isinstance(p, ev.PostMoveOrdered)
    ]
    assert not first.question
    g.close(2)
    g.walk()
    assert g.held(STAFF) == TOMAS
    g.open(3)
    g.close(3)
    out = g.walk()
    assert g.held(COMMAND) == KARA
    (stands,) = [p.move for p in out if isinstance(p, ev.PostMoveOrdered)]
    assert stands.question and first.move_id not in g.state.post_moves
    (paper,) = [p.document for p in out if isinstance(p, ev.DocumentIssued)]
    assert any(f.value == "Only at the sitting of the office question" for f in paper.body)


def test_an_appointment_by_someone_the_world_does_not_allow_is_refused(g: Ladders) -> None:
    """Only the chancellery moves the command: Kara's own order to put Olav in it is
    outside the law; Ilse's is lawful. (Where no mover is named, a lock row of the kind
    posts holds it as a question, QKD.)"""
    effect = rx.Appointment(person=OLAV, office="General of the Norra Levy")
    assert route.outside_the_law(g.state, routed(effect, KARA), 0).startswith("outside the law")
    assert route.outside_the_law(g.state, routed(effect, ILSE), 0) == ""
    assert ladder.may_move(g.state, TOMAS, COMMAND) is False


def routed(effect: rx.Appointment, by: EntityId) -> Any:
    return SimpleNamespace(parts=[SimpleNamespace(effect=effect)], issuer=seat(by))


def test_the_aide_files_none_of_it_without_a_standing_order(g: Ladders) -> None:
    order = (
        Ask(ask="relieve Kara", effect=rx.Appointment(person=KARA, office="x", appoint=False)),
    )
    assert wake._allowed(g.state, seat(ILSE), order) == ()
    g.add(
        ev.PlayStyleSet(
            seat_id=seat(ILSE),
            style=PlayStyle.FREE,
            standing=frozenset({rx.EffectKind.APPOINTMENT}),
        ),
        Scope.model_validate({"visibility": "restricted", "known_by": [seat(ILSE)]}),
    )
    assert wake._allowed(g.state, seat(ILSE), order) == order


def test_the_price_is_regard(g: Ladders) -> None:
    g.open(0)
    g.order(KARA, COMMAND, appoint=False)
    g.close(0)
    g.open(1)
    g.close(1)
    out = g.walk()
    (rel,) = [p.relationship for p in out if isinstance(p, ev.RelationshipSet)]
    assert (rel.a, rel.b, rel.disposition) == (KARA, ILSE, -ladder.REGARD_COST)


def test_the_pending_change_reaches_the_seat_of_the_person_moved_only(g: Ladders) -> None:
    g.open(0)
    g.order(KARA, COMMAND, appoint=False)
    assert "post_move_ordered" in catchup.FEED_KINDS

    def kinds(s: SeatId) -> set[str]:
        return {e.kind for e in g.store.read(CAMPAIGN) if s in e.scope.known_by}

    assert "post_move_ordered" in kinds(seat(KARA))
    assert "post_move_ordered" not in kinds(seat(ILSE))
    assert "post_move_ordered" not in kinds(seat(TOMAS))


def test_without_ladders_the_old_landing_holds(tmp_path: Path) -> None:
    g = Ladders(world(tmp_path, no_ladders))
    """An office the world gave no ladder and no movers keeps the old landing, its fact
    and its news, with posts on."""
    out = g.order(OLAV, GARRISON)
    assert not any(isinstance(p, ev.PostMoveOrdered) for p in out)
    assert ladder.post_named(g.state, "garrison") is None
    assert ladder.may_move(g.state, KARA, GARRISON) is None


def test_a_move_fold_needs_the_posts_rule(g: Ladders) -> None:
    state = g.state.model_copy(update={"rules": frozenset()})
    g.open(0)
    (moved,) = [p for p in g.order(OLAV, GARRISON) if isinstance(p, ev.PostMoveOrdered)]
    with pytest.raises(FoldError):
        apply(state, _event(state, moved))


def _event(state: State, p: ev.Payload) -> Event:
    return Event(
        event_id=EventId(derived_id(CAMPAIGN, "x", str(state.last_seq + 1))),
        campaign_id=CAMPAIGN,
        seq=state.last_seq + 1,
        tick=state.tick,
        scope=PUBLIC,
        payload=p,
        versions=cmp.versions(),
    )
