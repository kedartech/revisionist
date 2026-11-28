"""Acting without permission, and refusing an order from above (DFY).

The tests' own world is the locks world of ``tests/test_realism_locks.py`` (the toy world
with Ilse Varg, her general Kara Lind and Kara's aide Olaf Brun), with ``posts`` and
``defiance`` on and Norra at peace with Sudland, so the Isle and the Sudland Coast lie
across a border with a nation Norra is not at war with. Kara holds her command as a post,
``levy_command``, whose holder may cross a border without leave; any written move to the
Isle needs Ilse (the ``isle_move`` row), and a written engagement in the Gulf always
does (``gulf_fire``). Kara's command of the levy is carried out by Olav Holm, a colonel
whose loyalty each test sets.
"""

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, apply
from revisionist.core.ids import AssetId, EventId, FeatureId, OrderId, derived_id
from revisionist.core.realism import defiance, detect, locks
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.defiance import Act, Cause, Incident, Verdict
from revisionist.core.realism.detect import Confidence, Picture, Report, Source
from revisionist.core.realism.effect import Engagement, MoveForce, RoutedOrder, SetEngagement
from revisionist.core.realism.resolvers import friction
from revisionist.core.realism.route import REFUSE_PCT, carry_out
from revisionist.core.state import State
from revisionist.core.visibility import Visibility
from revisionist.core.world_compile import WorldError, compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick
from revisionist.engine.store import MemoryStore, load_state
from tests.test_realism_command import card
from tests.test_realism_locks import (
    FLAG,
    GULF,
    ILSE,
    ISLE,
    KARA,
    LEVY,
    NORRA,
    OLAF,
    World,
    commit,
    isle_move,
    key_id,
    logged,
    played,
    seat,
    tick_until,
    world,
    written,
)
from tests.test_territory_model import CAMPAIGN

ROOT = Path(__file__).resolve().parents[1]
OLAV = key_id("olav")
HILLS, COAST = key_id("norra_hills"), key_id("sudland_coast")
COMMAND = AssetId(object_id(CAMPAIGN, "asset", "levy_command"))


def defiant(*acts: str, loyalty: int = 2) -> Callable[[World], None]:
    """``posts`` and ``defiance`` on, the war ended, Kara's command a post whose holder may
    do ``acts`` without leave, and Olav, the colonel who carries out her command."""

    def change(w: World) -> None:
        w["rules"] = sorted({*w["rules"], "posts", "defiance"})
        w["wars"] = []
        office: dict[str, Any] = {
            "key": "levy_command",
            "kind": "office",
            "name": "General of the Norra Levy",
            "tier": 3,
            "controller": "kara",
        }
        if acts:
            office["without_leave"] = list(acts)
        w["assets"].append(office)
        card(w, "kara")["post"] = "levy_command"
        card(w, "kara")["authority"] = [
            {
                "name": "the_levy",
                "effects": ["move_force", "engagement"],
                "forces": ["norra_levy"],
                "executor": "olav",
            }
        ]
        w["entities"].append(
            {"key": "olav", "kind": "person", "name": "Olav Holm", "parent": "norra"}
        )
        w["cards"].append(
            {
                "person": "olav",
                "office": "Colonel of the Norra Levy",
                "principals": ["kara"],
                "horizon_days": 14,
                "loyalty": loyalty,
            }
        )

    return change


def to_isle() -> Ask:
    return written(MoveForce(force=LEVY, to=ISLE))


def held_march(store: MemoryStore) -> locks.HeldOrder:
    filed = commit(store, KARA, to_isle())
    assert isinstance(filed, locks.HeldOrder)
    return filed


def send(store: MemoryStore, held: locks.HeldOrder, person: Any = KARA) -> ev.OrderDefied:
    return realism_tick.send_anyway(store, CAMPAIGN, seat(person), held.order_id)


# --- The declaration ---------------------------------------------------------------


def test_a_post_names_the_acts_its_holder_may_do_without_leave(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move, defiant("border", "fire_first"))
    state = load_state(store, CAMPAIGN)
    assert state.ladders[COMMAND].without_leave == (Act.BORDER, Act.FIRE_FIRST)
    assert defiance.allowed(state, KARA) == frozenset({Act.BORDER, Act.FIRE_FIRST})
    assert defiance.allowed(state, ILSE) == frozenset()


def test_with_defiance_off_no_post_names_any_act(tmp_path: Path) -> None:
    def off(w: World) -> None:
        w["rules"] = [r for r in w["rules"] if r != "defiance"]

    store = played(tmp_path, isle_move, defiant("border"), off)
    state = load_state(store, CAMPAIGN)
    assert COMMAND not in state.ladders
    assert defiance.allowed(state, KARA) == frozenset()


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (
            lambda w: w.update(rules=[r for r in w["rules"] if r != "posts"]),
            "defiance needs the posts rule",
        ),
        (
            lambda w: w.update(rules=[r for r in w["rules"] if r != "locks"]),
            "defiance needs the locks rule",
        ),
        (
            lambda w: w["assets"].append(
                {
                    "key": "levy_chest",
                    "kind": "wealth",
                    "name": "The Levy's Chest",
                    "controller": "kara",
                    "without_leave": ["border"],
                }
            ),
            "only an office names acts without leave",
        ),
    ],
)
def test_the_compiler_refuses_a_defiance_that_does_not_fit(
    tmp_path: Path, change: Callable[[World], None], problem: str
) -> None:
    with pytest.raises(WorldError, match=problem):
        compile_world(
            world(tmp_path, isle_move, defiant("border"), change), CAMPAIGN, cmp.versions()
        )


def test_the_list_is_closed_a_blockade_is_not_an_act_the_session_can_tell() -> None:
    assert {a.value for a in Act} == {"border", "fire_first"}


# --- Telling the act from the typed effect -----------------------------------------


def test_a_move_across_a_border_with_a_nation_not_at_war_is_a_border_act(tmp_path: Path) -> None:
    state = load_state(played(tmp_path, isle_move, defiant("border")), CAMPAIGN)
    assert defiance.acts(state, seat(KARA), (to_isle(),)) == frozenset({Act.BORDER})
    home = written(MoveForce(force=LEVY, to=HILLS))
    assert defiance.acts(state, seat(KARA), (home,)) == frozenset()


def test_a_move_into_a_nation_at_war_crosses_no_border_without_leave(tmp_path: Path) -> None:
    def at_war(w: World) -> None:
        w["wars"] = [{"a": "norra", "b": "sudland", "since": "1900-03-01", "source": "toy"}]

    state = load_state(played(tmp_path, isle_move, defiant("border"), at_war), CAMPAIGN)
    assert defiance.acts(state, seat(KARA), (to_isle(),)) == frozenset()


def test_shooting_on_sight_or_attacking_a_nation_not_at_war_is_firing_first(tmp_path: Path) -> None:
    state = load_state(played(tmp_path, isle_move, defiant("fire_first")), CAMPAIGN)
    shoot = written(SetEngagement(force=LEVY, zone=GULF, rule=Engagement.SHOOT_ON_SIGHT))
    assert defiance.acts(state, seat(KARA), (shoot,)) == frozenset({Act.FIRE_FIRST})
    attack = written(MoveForce(force=LEVY, to=COAST, posture="attack"))
    assert defiance.acts(state, seat(KARA), (attack,)) == frozenset({Act.BORDER, Act.FIRE_FIRST})
    calm = written(SetEngagement(force=LEVY, zone=GULF, rule=Engagement.DEFEND))
    assert defiance.acts(state, seat(KARA), (calm,)) == frozenset()


# --- Sending a held order anyway ---------------------------------------------------


def test_a_held_order_on_the_posts_list_is_sent_anyway_once_by_its_own_seat(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move, defiant("border"))
    held = held_march(store)
    sent = send(store, held)
    state = load_state(store, CAMPAIGN)
    landed = OrderId(derived_id(CAMPAIGN, "defied", held.order_id))
    assert sent.defied.order_id == held.order_id and sent.defied.landed == landed
    assert sent.defied.acts == (Act.BORDER,) and sent.defied.issuer == seat(KARA)
    assert held.order_id not in state.held
    assert isinstance(state.routed[landed], RoutedOrder)
    assert state.defied[landed] == sent.defied
    ended = logged(store, ev.HeldOrderEnded)
    assert [(e.order_id, e.end, e.by) for e in ended] == [
        (held.order_id, locks.HeldEnd.LANDED, landed)
    ]
    with pytest.raises(ValueError, match=f"^{locks.NOT_HELD}$"):
        send(store, held)


SUDLAND_LEVY = FeatureId(object_id(CAMPAIGN, "feature", "sudland_levy"))


def reporting(w: World) -> None:
    w["rules"] = sorted({*w["rules"], "territories", "reports"})


def known_in_the_gulf(state: State) -> State:
    """``state`` with a report reaching Norra that places Sudland's levy in the gulf."""
    day = state.in_world_date
    assert day is not None
    key = detect.report_key(state, NORRA, SUDLAND_LEVY)
    report = Report(
        key=key,
        area=GULF,
        seen=day,
        source=Source.CONTACT,
        rank=0,
        confidence=Confidence.A,
        arrives=day,
    )
    return state.model_copy(update={"reports": {NORRA: Picture(delivered={key: report})}})


def test_the_price_and_the_refusal_follow_what_the_seat_knows_of_the_zone(tmp_path: Path) -> None:
    """Two games alike but for a report of a neutral force in the gulf: the order to
    shoot on sight there is priced and sent in the one, refused for want of leave in
    the other. Mutant: acts read from every force in the true state price both."""
    from revisionist.core.project import project
    from revisionist.engine.web.locks_api import price

    store = played(tmp_path, isle_move, defiant("fire_first"), reporting)
    shoot = written(SetEngagement(force=LEVY, zone=GULF, rule=Engagement.SHOOT_ON_SIGHT))
    order = held_march(store).model_copy(update={"asks": (shoot,)})
    unseen = load_state(store, CAMPAIGN)
    seen = known_in_the_gulf(unseen)
    today = unseen.in_world_date
    assert today is not None
    kara = seat(KARA)
    assert defiance.acts(seen, kara, (shoot,)) == frozenset({Act.FIRE_FIRST})
    assert defiance.acts(unseen, kara, (shoot,)) == frozenset()
    acts, _ = realism_tick.sendable(seen, kara, order, today)
    assert acts == (Act.FIRE_FIRST,)
    assert price(seen, kara, project(seen, kara), order) is not None
    with pytest.raises(ValueError, match=f"^{defiance.NOT_WITHOUT_LEAVE}$"):
        realism_tick.sendable(unseen, kara, order, today)
    assert price(unseen, kara, project(unseen, kara), order) is None


def test_the_order_sent_anyway_is_told_to_its_own_seat_alone(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move, defiant("border"))
    send(store, held_march(store))
    told = [e for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.OrderDefied)]
    assert len(told) == 1 and told[0].scope.known_by == frozenset({seat(KARA)})


def test_an_act_not_on_the_posts_list_is_refused_in_fixed_words(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move, defiant("fire_first"))
    held = held_march(store)
    with pytest.raises(ValueError, match=f"^{defiance.NOT_WITHOUT_LEAVE}$"):
        send(store, held)
    assert held.order_id in load_state(store, CAMPAIGN).held
    assert not logged(store, ev.OrderDefied)


def test_an_order_with_no_act_at_all_is_refused_in_the_same_words(tmp_path: Path) -> None:
    store = played(tmp_path, defiant("border", "fire_first"))
    held = commit(store, KARA, written(SetEngagement(zone=GULF, rule=Engagement.DEFEND)))
    assert isinstance(held, locks.HeldOrder)
    with pytest.raises(ValueError, match=f"^{defiance.NOT_WITHOUT_LEAVE}$"):
        send(store, held)


def test_only_the_orders_own_seat_may_send_it(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move, defiant("border"))
    held = held_march(store)
    for other in (ILSE, OLAF):
        with pytest.raises(ValueError, match=f"^{locks.NOT_HELD}$"):
            send(store, held, other)
    assert held.order_id in load_state(store, CAMPAIGN).held


def test_with_defiance_off_nothing_may_be_sent_anyway(tmp_path: Path) -> None:
    def off(w: World) -> None:
        w["rules"] = [r for r in w["rules"] if r != "defiance"]

    store = played(tmp_path, isle_move, defiant("border"), off)
    held = held_march(store)
    with pytest.raises(ValueError, match=f"^{defiance.NOT_ON}$"):
        send(store, held)


def test_the_aide_never_sends_an_order_anyway() -> None:
    """Nothing the aide runs names the way to send an order anyway."""
    for name in ("aide.py", "options.py", "deputy.py"):
        path = ROOT / "src" / "revisionist" / "engine" / name
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        named = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        named |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not {"send_anyway", "may_send"} & named, name


# --- The executor ------------------------------------------------------------------


def test_the_executor_refuses_an_order_sent_anyway_at_loyalty_zero(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move, defiant("border", loyalty=0))
    sent = send(store, held_march(store)).defied
    state = load_state(store, CAMPAIGN)
    order = state.routed[sent.landed]
    # The draw that decides a refusal today keys on the order's id: take an id it refuses.
    refusing = next(
        OrderId(derived_id(CAMPAIGN, "probe", str(n)))
        for n in range(200)
        if friction(state, OrderId(derived_id(CAMPAIGN, "probe", str(n))), 0, "refuse", n=100)
        < REFUSE_PCT
    )
    moved = order.model_copy(update={"order_id": refusing})
    marked = state.model_copy(
        update={"defied": {refusing: sent.model_copy(update={"landed": refusing})}}
    )
    assert carry_out(marked, moved, 0) == (None, "loyalty 0: Holm will not carry it out")
    # The same order, not sent anyway, meets only today's line of minus 4 and is carried out.
    fidelity, why = carry_out(state.model_copy(update={"defied": {}}), moved, 0)
    assert fidelity is not None and why == ""


def test_a_loyal_executor_carries_out_an_order_sent_anyway(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move, defiant("border", loyalty=1))
    landed = send(store, held_march(store)).defied.landed
    state = load_state(store, CAMPAIGN)
    fidelity, why = carry_out(state, state.routed[landed], 0)
    assert fidelity is not None and why == ""


# --- The incident -----------------------------------------------------------------


def carried(store: MemoryStore) -> Incident:
    """Tick until the order sent anyway is carried out and its incident opens."""
    state = tick_until(store, lambda s: bool(s.incidents))
    (incident,) = state.incidents.values()
    return incident


def sent_and_carried(tmp: Path, *more: Callable[[World], None]) -> tuple[MemoryStore, Incident]:
    store = played(tmp, isle_move, defiant("border"), *more)
    send(store, held_march(store))
    return store, carried(store)


def choose(store: MemoryStore, incident: Incident, verdict: str, person: Any = ILSE) -> Any:
    """The seat's sealed answer, filed today."""
    return realism_tick.answer_incident(
        store, CAMPAIGN, seat(person), incident.incident_id, verdict
    )


def landed(store: MemoryStore, incident: Incident) -> ev.IncidentAnswered:
    """Tick until the incident's answer lands on its due day, and return it."""
    tick_until(store, lambda s: s.incidents[incident.incident_id].verdict is not None, ticks=6)
    done: list[ev.IncidentAnswered] = logged(store, ev.IncidentAnswered)
    (found,) = [e for e in done if e.incident_id == incident.incident_id]
    return found


def answer(
    store: MemoryStore, incident: Incident, verdict: str, person: Any = ILSE
) -> ev.IncidentAnswered:
    """The seat's answer, filed today and landed on the due day."""
    choose(store, incident, verdict, person)
    return landed(store, incident)


def regard(store: MemoryStore, of: Any, toward: Any) -> int:
    from revisionist.core.realism import ladder

    return ladder.regard_of(load_state(store, CAMPAIGN).relationships, of, toward)


def test_an_order_sent_anyway_and_carried_out_opens_one_incident_before_the_superior(
    tmp_path: Path,
) -> None:
    store, incident = sent_and_carried(tmp_path)
    assert incident.cause is Cause.DEFIED
    assert (incident.commander, incident.superior) == (KARA, ILSE)
    assert set(incident.seats) == {seat(KARA), seat(ILSE)}
    assert (incident.due - incident.opened).days == defiance.INCIDENT_DAYS
    assert incident.verdict is None
    opened = [e for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.IncidentOpened)]
    assert len(opened) == 1 and opened[0].scope.known_by == frozenset(incident.seats)
    # More days go by: still one incident for the order.
    tick_until(store, lambda s: False, ticks=1)
    assert len(logged(store, ev.IncidentOpened)) == 1


def test_an_order_sent_anyway_its_executor_refused_opens_no_incident(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    state = load_state(store, CAMPAIGN)
    (done,) = [e for e in logged(store, ev.OrderExecuted) if e.order_id == incident.order_id]
    refused = done.model_copy(update={"fidelity": None})
    fresh = state.model_copy(update={"incidents": {}})
    assert defiance.arising(fresh, [refused], incident.opened) == []
    again, *abroad = defiance.arising(fresh, [done], incident.opened)
    assert isinstance(again, ev.IncidentOpened) and again.incident == incident
    # Abroad: the regard between the two nations' heads falls, both ways.
    assert len(abroad) == 2 and all(isinstance(p, ev.RelationshipSet) for p in abroad)


def test_backed_the_order_is_no_longer_defiant(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    before = regard(store, KARA, ILSE), regard(store, ILSE, KARA)
    done = answer(store, incident, "backed")
    state = load_state(store, CAMPAIGN)
    assert done.verdict is Verdict.BACKED and not done.by_card
    assert state.incidents[incident.incident_id].verdict is Verdict.BACKED
    assert not defiance.defiant(state, incident.order_id)
    assert (regard(store, KARA, ILSE), regard(store, ILSE, KARA)) == before
    assert not logged(store, ev.PostMoveOrdered)


def test_disowned_the_regard_between_them_falls_both_ways(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    before = regard(store, KARA, ILSE), regard(store, ILSE, KARA)
    answer(store, incident, "disowned")
    state = load_state(store, CAMPAIGN)
    assert state.incidents[incident.incident_id].verdict is Verdict.DISOWNED
    assert defiance.defiant(state, incident.order_id)
    after = regard(store, KARA, ILSE), regard(store, ILSE, KARA)
    assert after == tuple(max(-5, b - defiance.INCIDENT_REGARD) for b in before)


def test_disowned_puts_back_the_rule_an_order_sent_anyway_set(tmp_path: Path) -> None:
    store = played(tmp_path, defiant("fire_first"))
    was = load_state(store, CAMPAIGN).features[LEVY].engagement
    shoot = written(SetEngagement(force=LEVY, zone=GULF, rule=Engagement.SHOOT_ON_SIGHT))
    held = commit(store, KARA, shoot)
    assert isinstance(held, locks.HeldOrder)
    sent = send(store, held).defied
    assert sent.kept == {LEVY: was}
    incident = carried(store)
    assert load_state(store, CAMPAIGN).features[LEVY].engagement is Engagement.SHOOT_ON_SIGHT
    answer(store, incident, "disowned")
    assert load_state(store, CAMPAIGN).features[LEVY].engagement == was


def test_dismissed_a_step_down_the_commanders_ladder_by_its_rules(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    answer(store, incident, "dismissed")
    (move,) = [p.move for p in logged(store, ev.PostMoveOrdered)]
    assert (move.person, move.post, move.appoint, move.by) == (KARA, COMMAND, False, ILSE)


def _log(store: MemoryStore, payload: Any) -> None:
    """``payload`` logged after the store's last event, in its scope."""
    last = list(store.read(CAMPAIGN))[-1]
    seq = last.seq + 1
    event_id = EventId(derived_id(CAMPAIGN, "test", str(seq)))
    store.append_all(
        [last.model_copy(update={"payload": payload, "seq": seq, "event_id": event_id})]
    )


def two_on_one_day(tmp: Path) -> tuple[MemoryStore, Incident, Incident]:
    """Kara's incident, and a second against her opened the same day on another order."""
    store, first = sent_and_carried(tmp)
    second = first.model_copy(
        update={
            "incident_id": derived_id(CAMPAIGN, "incident", "second"),
            "order_id": OrderId(derived_id(CAMPAIGN, "order", "second")),
        }
    )
    _log(store, ev.IncidentOpened(incident=second))
    return store, first, second


def test_two_incidents_dismissed_on_one_day_order_one_step_down(tmp_path: Path) -> None:
    store, first, second = two_on_one_day(tmp_path)
    choose(store, first, "dismissed")
    choose(store, second, "dismissed")
    landed(store, first)
    done = landed(store, second)
    assert done.verdict is Verdict.DISMISSED
    (move,) = [p.move for p in logged(store, ev.PostMoveOrdered)]
    assert (move.person, move.post, move.appoint) == (KARA, COMMAND, False)


def test_the_card_dismissing_twice_on_one_day_leaves_the_walk_going(tmp_path: Path) -> None:
    from revisionist.core.realism import ladder

    store, first, second = two_on_one_day(tmp_path)
    state = load_state(store, CAMPAIGN)
    for lowered in ladder.regard(
        state, ILSE, KARA, regard(store, ILSE, KARA) - defiance.DISMISS_AT
    ):
        _log(store, lowered)
    state = tick_until(store, lambda s: all(i.verdict for i in s.incidents.values()), ticks=6)
    assert [state.incidents[i.incident_id].verdict for i in (first, second)] == [
        Verdict.DISMISSED,
        Verdict.DISMISSED,
    ]
    assert len(logged(store, ev.PostMoveOrdered)) == 1
    day = state.in_world_date
    after = tick_until(store, lambda s: s.in_world_date != day, ticks=1)
    assert after.in_world_date is not None and day is not None and after.in_world_date > day


def test_an_answer_the_log_refuses_is_told_in_words_and_stores_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, incident = sent_and_carried(tmp_path)
    chosen = defiance.choose

    def as_kara(*args: Any, **kw: Any) -> ev.IncidentChoiceFiled:
        return chosen(*args, **kw).model_copy(update={"seat_id": seat(KARA)})

    monkeypatch.setattr(defiance, "choose", as_kara)
    before = len(list(store.read(CAMPAIGN)))
    with pytest.raises(ValueError, match=f"^{defiance.NOT_LANDED}$"):
        choose(store, incident, "dismissed")
    assert len(list(store.read(CAMPAIGN))) == before


def test_abroad_the_incident_names_the_nation_it_was_done_to(tmp_path: Path) -> None:
    _, incident = sent_and_carried(tmp_path)
    assert incident.abroad == key_id("sudland")


def regarded(w: World) -> None:
    """Public regard, as a world declares it, between Ilse and Kara and between the two
    nations' heads, Ilse and Tomas."""
    w["relationships"] = [
        *w.get("relationships", []),
        *(
            {"key": f"{a}_{b}", "a": a, "b": b, "disposition": 0}
            for a, b in (("ilse", "kara"), ("kara", "ilse"), ("ilse", "tomas"), ("tomas", "ilse"))
        ),
    ]


def third_seat(store: MemoryStore) -> tuple[Any, list[Any]]:
    """What Olaf, party to no incident, holds of the game: his view's relationships and
    every event the catch-up seam feeds him."""
    from revisionist.core.project import project
    from revisionist.engine import catchup

    view = project(load_state(store, CAMPAIGN), seat(OLAF))
    fed = catchup.seat_events(store, CAMPAIGN, seat(OLAF), 0, 999)
    return view.relationships, [
        (f.event.kind, f.event.payload.model_dump(mode="json")) for f in fed
    ]


def test_twin_games_answered_two_ways_read_the_same_to_a_third_seat(tmp_path: Path) -> None:
    from collections import Counter

    from tests.fog_twins import drawn_from

    seen, held = [], []
    for verdict in ("backed", "disowned"):
        with drawn_from(Counter()):
            store, incident = sent_and_carried(tmp_path / verdict, regarded)
            answer(store, incident, verdict)
        seen.append(third_seat(store))
        held.append((regard(store, ILSE, KARA), regard(store, KARA, ILSE)))
    assert held[1] == tuple(b - defiance.INCIDENT_REGARD for b in held[0])
    assert seen[0] == seen[1]


def test_an_incidents_change_of_regard_is_sealed_to_the_two_parties(tmp_path: Path) -> None:
    from revisionist.core.project import project

    store, incident = sent_and_carried(tmp_path, regarded)
    answer(store, incident, "disowned")
    changed = [
        e
        for e in store.read(CAMPAIGN)
        if isinstance(e.payload, ev.RelationshipSet)
        and {e.payload.relationship.a, e.payload.relationship.b} == {ILSE, KARA}
        and e.payload.relationship.disposition < 0
    ]
    assert len(changed) == 2
    for e in changed:
        assert isinstance(e.payload, ev.RelationshipSet)
        assert (
            e.scope.known_by == frozenset(incident.seats) == e.payload.relationship.scope.known_by
        )
    state = load_state(store, CAMPAIGN)
    for person in (ILSE, KARA):
        mine = project(state, seat(person)).relationships.values()
        sealed = {
            (r.a, r.disposition)
            for r in mine
            if {r.a, r.b} == {ILSE, KARA} and r.scope.visibility is not Visibility.PUBLIC
        }
        assert sealed == {(ILSE, -defiance.INCIDENT_REGARD), (KARA, -defiance.INCIDENT_REGARD)}


def test_the_engine_reads_the_sealed_regard_and_a_third_seat_the_world_s(
    tmp_path: Path,
) -> None:
    from revisionist.core import goals
    from revisionist.core.project import project
    from revisionist.core.realism.ladder import regard_of

    store, incident = sent_and_carried(tmp_path, regarded)
    answer(store, incident, "disowned")
    state = load_state(store, CAMPAIGN)
    fell = -defiance.INCIDENT_REGARD
    assert regard_of(state.relationships, ILSE, KARA) == fell
    assert goals._regard(state, KARA, ILSE) == fell
    assert goals._regard(project(state, seat(ILSE)), ILSE, KARA) == fell
    assert goals._regard(project(state, seat(OLAF)), ILSE, KARA) == 0


def test_a_later_public_fall_lowers_the_sealed_regard_as_well(tmp_path: Path) -> None:
    from revisionist.core.realism import ladder

    store, incident = sent_and_carried(tmp_path, regarded)
    answer(store, incident, "disowned")
    state = load_state(store, CAMPAIGN)
    moved = ladder.regard(state, ILSE, KARA, 1)
    fell = {e.relationship.scope.visibility: e.relationship.disposition for e in moved}
    assert fell == {Visibility.PUBLIC: -1, Visibility.RESTRICTED: -defiance.INCIDENT_REGARD - 1}


def test_abroad_the_heads_change_of_regard_is_sealed_to_their_seats(tmp_path: Path) -> None:
    store, _ = sent_and_carried(tmp_path, regarded)
    heads = {ILSE, key_id("tomas")}
    fallen = [
        e
        for e in store.read(CAMPAIGN)
        if isinstance(e.payload, ev.RelationshipSet)
        and {e.payload.relationship.a, e.payload.relationship.b} == heads
        and e.payload.relationship.disposition < 0
    ]
    assert len(fallen) == 2
    assert all(not e.scope.visible_to(seat(OLAF)) for e in fallen)
    relationships, fed = third_seat(store)
    assert all(r.disposition == 0 for r in relationships.values() if {r.a, r.b} == heads)
    assert not [
        p for k, p in fed if k == "relationship_set" and p["relationship"]["disposition"] < 0
    ]


def test_only_the_superiors_seat_answers_and_only_once(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    for other in (KARA, OLAF):
        with pytest.raises(ValueError, match=f"^{defiance.NOT_YOURS}$"):
            answer(store, incident, "backed", other)
    with pytest.raises(ValueError, match=r"^answer one of: backed, disowned, dismissed$"):
        answer(store, incident, "pardoned")
    answer(store, incident, "disowned")
    with pytest.raises(ValueError, match=f"^{defiance.NOT_YOURS}$"):
        answer(store, incident, "backed")
    assert len(logged(store, ev.IncidentAnswered)) == 1


def test_unanswered_past_its_day_the_superiors_card_answers(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    expected = defiance.card_verdict(load_state(store, CAMPAIGN), incident)
    state = tick_until(
        store, lambda s: s.incidents[incident.incident_id].verdict is not None, ticks=6
    )
    done = state.incidents[incident.incident_id]
    assert done.by_card and done.answered is not None and done.answered > incident.due
    assert done.verdict is expected
    assert [e.by_card for e in logged(store, ev.IncidentAnswered)] == [True]


def test_the_card_answers_by_how_the_superior_regards_the_commander(tmp_path: Path) -> None:
    from revisionist.core.realism import ladder

    store, incident = sent_and_carried(tmp_path)
    state = load_state(store, CAMPAIGN)
    base = regard(store, ILSE, KARA)

    def at(n: int) -> Verdict:
        (lowered,) = ladder.regard(state, ILSE, KARA, base - n)
        moved = apply(state, _event(store, lowered))
        return defiance.card_verdict(moved, incident)

    assert at(defiance.BACK_AT) is Verdict.BACKED
    assert at(defiance.BACK_AT - 1) is Verdict.DISOWNED
    assert at(defiance.DISMISS_AT + 1) is Verdict.DISOWNED
    assert at(defiance.DISMISS_AT) is Verdict.DISMISSED


def test_the_incident_is_fed_to_the_commanders_seat_and_the_superiors_alone(
    tmp_path: Path,
) -> None:
    from revisionist.core.project import project

    store, incident = sent_and_carried(tmp_path)
    answer(store, incident, "backed")
    state = load_state(store, CAMPAIGN)
    for person, sees in ((KARA, True), (ILSE, True), (OLAF, False)):
        assert (incident.incident_id in project(state, seat(person)).incidents) is sees
    answered = [e for e in store.read(CAMPAIGN) if isinstance(e.payload, ev.IncidentAnswered)]
    assert answered[0].scope.known_by == frozenset(incident.seats)


def test_the_commanders_reason_is_built_from_his_own_view(tmp_path: Path) -> None:
    """Two games differing only in a fact Kara cannot see tell her the same."""
    from revisionist.core.project import project

    def law_passed(w: World) -> None:
        next(q for q in w["quantities"] if q["key"] == FLAG)["value"] = 1

    words = []
    for sub, more in (("a", ()), ("b", (law_passed,))):
        store, incident = sent_and_carried(tmp_path / sub, *more)
        view = project(load_state(store, CAMPAIGN), seat(KARA))
        words.append(defiance.told(view, view.incidents[incident.incident_id]))
    assert words[0] == words[1]
    assert "Ilse" in words[0] and "backed, disowned or dismissed" in words[0]


# --- Mutants ----------------------------------------------------------------------


def test_the_incident_is_never_opened_twice(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    state = load_state(store, CAMPAIGN)
    again = incident.model_copy(update={"incident_id": "another"})
    for twin in (incident, again):
        with pytest.raises(FoldError, match="has an incident already"):
            apply(state, _event(store, ev.IncidentOpened(incident=twin)))
    assert defiance.arising(state, logged(store, ev.OrderExecuted), incident.opened) == []


def test_backed_needs_the_superiors_answer(tmp_path: Path) -> None:
    store, incident = sent_and_carried(tmp_path)
    state = load_state(store, CAMPAIGN)
    assert defiance.defiant(state, incident.order_id)
    # Only an answer backs it: the incident opens unanswered, and may not open answered.
    backed = incident.model_copy(update={"verdict": Verdict.BACKED, "answered": incident.opened})
    with pytest.raises(FoldError, match="opens answered"):
        apply(
            state.model_copy(update={"incidents": {}}),
            _event(store, ev.IncidentOpened(incident=backed)),
        )


def test_the_aide_never_sends_one_even_by_the_engine(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move, defiant("border"))
    held = held_march(store)
    state = load_state(store, CAMPAIGN)
    marked = state.model_copy(update={"aide_orders": state.aide_orders | {held.order_id}})
    sent = defiance.Defied(
        order_id=held.order_id,
        landed=OrderId(derived_id(CAMPAIGN, "defied", held.order_id)),
        issuer=seat(KARA),
        acts=(Act.BORDER,),
        on=held.filed,
    )
    with pytest.raises(FoldError, match="the aide never sends one anyway"):
        apply(marked, _event(store, ev.OrderDefied(defied=sent)))


def test_the_engine_refuses_the_aide_its_own_held_order_in_fixed_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = played(tmp_path, isle_move, defiant("border"))
    held = held_march(store)
    state = load_state(store, CAMPAIGN)
    marked = state.model_copy(update={"aide_orders": state.aide_orders | {held.order_id}})
    monkeypatch.setattr(realism_tick, "load_state", lambda *_: marked)
    with pytest.raises(ValueError, match=f"^{defiance.BY_AIDE}$"):
        send(store, held)
    assert not logged(store, ev.OrderDefied)


def test_another_seat_never_sends_ones_held_order_even_by_the_engine(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move, defiant("border"))
    held = held_march(store)
    state = load_state(store, CAMPAIGN)
    forged = defiance.Defied(
        order_id=held.order_id,
        landed=OrderId(derived_id(CAMPAIGN, "defied", held.order_id)),
        issuer=seat(OLAF),
        acts=(Act.BORDER,),
        on=held.filed,
    )
    with pytest.raises(FoldError, match="is not that seat's"):
        apply(state, _event(store, ev.OrderDefied(defied=forged)))


def test_an_act_outside_the_list_is_never_sent(tmp_path: Path) -> None:
    store = played(tmp_path, isle_move, defiant("border", "fire_first"))
    held = commit(store, KARA, written(MoveForce(force=LEVY, to=HILLS)), to_isle())
    assert isinstance(held, locks.HeldOrder)
    # A march home with the border act is still only the border act; an order that does
    # nothing on the list is never sent.
    home = commit(store, KARA, written(SetEngagement(zone=GULF, rule=Engagement.DEFEND)))
    assert isinstance(home, locks.HeldOrder)
    with pytest.raises(ValueError, match=f"^{defiance.NOT_WITHOUT_LEAVE}$"):
        send(store, home)
    assert all(d.order_id != home.order_id for d in load_state(store, CAMPAIGN).defied.values())


def _event(store: MemoryStore, payload: Any) -> Any:
    """The store's last event carrying ``payload`` instead."""
    last = list(store.read(CAMPAIGN))[-1]
    return last.model_copy(update={"payload": payload, "seq": last.seq + 1})


# --- Refusing an order from above (CMD's step) ------------------------------------


def _king(*, defy: bool = True) -> tuple[Any, Any]:
    from revisionist.core.state import Rule
    from tests.test_commander_step_actions import _at_king

    r, order = _at_king()
    rules = r.state.rules | {Rule.DEFIANCE} if defy else r.state.rules - {Rule.DEFIANCE}
    r.state = r.state.model_copy(update={"rules": rules})
    return r, order


def test_with_defiance_on_a_seat_may_refuse_a_step_on_an_order_from_above() -> None:
    from revisionist.core.realism import pipelines
    from revisionist.core.realism.pipeline import StepAction

    r, order = _king()
    assert pipelines.step_allowed(r.state, order) == frozenset(
        {StepAction.PASS, StepAction.STALL, StepAction.REFUSE}
    )
    assert pipelines.checked_step(r.state, order.order_id, StepAction.REFUSE) == order
    off, order = _king(defy=False)
    with pytest.raises(ValueError, match="does not allow refuse"):
        pipelines.checked_step(off.state, order.order_id, StepAction.REFUSE)


def test_the_refusal_of_a_superiors_order_opens_an_incident_before_him() -> None:
    from revisionist.core.realism.pipeline import StepAction, StepOutcome

    r, order = _king()
    king = r.state.seats[r.seats["king"]].embodies
    fdr = r.state.seats[r.seats["roosevelt"]].embodies
    day = r.state.in_world_date
    refused = ev.OrderStepTaken(
        order_id=order.order_id,
        outcome=StepOutcome(step=order.step, person=king, action=StepAction.REFUSE, on=day),
    )
    (opened,) = defiance.arising(r.state, [refused], day)
    assert isinstance(opened, ev.IncidentOpened)
    i = opened.incident
    assert (i.cause, i.commander, i.superior) == (Cause.REFUSED, king, fdr)
    assert set(i.seats) == {r.seats["king"], r.seats["roosevelt"]}
    passed = refused.model_copy(
        update={"outcome": refused.outcome.model_copy(update={"action": StepAction.PASS})}
    )
    assert defiance.arising(r.state, [passed], day) == []
    off, _ = _king(defy=False)
    assert defiance.arising(off.state, [refused], day) == []


def test_the_absent_commanders_step_still_passes_and_never_refuses() -> None:
    from datetime import timedelta

    from revisionist.core.realism import pipelines
    from revisionist.core.realism.pipeline import StepAction

    r, order = _king()
    day = r.state.in_world_date + timedelta(days=90)
    taken = [
        p
        for p in pipelines.run_pipelines(r.state, day, "s")
        if isinstance(p, ev.OrderStepTaken)
        and p.order_id == order.order_id
        and p.outcome.step == order.step
    ]
    assert [t.outcome.action for t in taken] == [StepAction.PASS]
    assert defiance.arising(r.state, taken, day) == []
