"""Envoys as pieces (ENV).

The toy world (``tests/worlds/territory-toy.yaml``) is played with ``territories``,
``holders`` and ``agreements`` on, and a third power, Ostmark (its leader Olaf, a head of
government), at peace with both, holding the Isle as its capital. Norra and Sudland are at
war. The Norra Herald, an envoy, stands at Norrhavn on the Norra Plain; the Isle is one
crossing away, three days for a herald.
"""

from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FeatureId, OrderId, SeatId
from revisionist.core.project import project
from revisionist.core.realism import agreement, battle, detect, process, territory
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.agreement import OFFER_DAYS
from revisionist.core.realism.effect import Deal
from revisionist.core.realism.geography import in_play
from revisionist.core.realism.territory import Plan, Refused
from revisionist.core.realism.war import War, war_id_for
from revisionist.core.world import WorldFile
from tests.test_adjacency_moves import START, Logged, entity, piece, seat, set_entity
from tests.test_adjacency_moves import toy as territories_toy
from tests.test_agreements import file, ostmark
from tests.test_battles import strengths

World = dict[str, Any]
NORRA, SUDLAND, OSTMARK = entity("norra"), entity("sudland"), entity("ostmark")
ILSE, TOMAS, OLAF = seat("ilse"), seat("tomas"), seat("olaf")
HERALD = FeatureId(entity("norra_herald"))
ISLE, PLAIN, HILLS, COAST = (
    entity("isle"),
    entity("norra_plain"),
    entity("norra_hills"),
    entity("sudland_coast"),
)
ARRIVES = START + timedelta(days=3)
"""The day the herald, sent to the Isle at the start, stands there."""


def day(n: int) -> Any:
    return START + timedelta(days=n)


def isle_to_ostmark(w: World) -> None:
    """Ostmark holds the Isle, its capital; Olaf is a head of government."""
    for t in w["territories"]:
        if t["key"] == "isle":
            t["holder"] = "ostmark"
    for e in w["entities"]:
        if e["key"] == "ostmark":
            e["capital"] = "isle"
    for c in w["cards"]:
        if c["person"] == "olaf":
            c["reach"] = {"rank": 5}


def rules(*names: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = ["territories", *names]

    return change


def world(tmp: Path, *changes: Callable[[World], None], on: Sequence[str] = ()) -> WorldFile:
    names = on or ("holders", "agreements")
    return territories_toy(tmp, ostmark, isle_to_ostmark, rules(*names), *changes)


def game(tmp: Path, *changes: Callable[[World], None], on: Sequence[str] = ()) -> Logged:
    return Logged(world(tmp, *changes, on=on), "ilse", "tomas", "olaf")


def courier_to_olaf(w: World) -> None:
    """Ilse's word reaches Olaf by courier: five days."""
    for c in w["cards"]:
        if c["person"] == "ilse":
            c["inner_circle"] = [{"person": "olaf", "channel": "courier"}]


def offer(g: Logged, envoy: FeatureId | None = HERALD, **fields: Any) -> OrderId:
    d = Deal(
        counterparty=OSTMARK,
        parties=fields.pop("parties", (NORRA, OSTMARK)),
        wording="Friendship between Norra and Ostmark.",
        envoy=envoy,
        **fields,
    )
    return file(g, ILSE, Ask(ask="An offer of agreement.", effect=d))


def refused_offer(g: Logged, d: Deal) -> str:
    with pytest.raises(ValueError) as e:
        file(g, ILSE, Ask(ask="An offer of agreement.", effect=d))
    return str(e.value)


def stand(g: Logged, key: str, area: EntityId) -> None:
    f = piece(g.state, key).model_copy(update={"places": (area,), "path": (), "step_due": None})
    g.add([ev.FeatureSet(feature=f)])


def papers_to(g: Logged, who: SeatId) -> list[Any]:
    """The offer papers issued to ``who``'s seat, arrived or not."""
    return [
        d.view
        for d in g.state.documents.values()
        if d.view.scope.visible_to(who) and "offer" in d.view.title.lower()
    ]


# --- Rule 1: an envoy moves by adjacency, opens no battle, is never destroyed, is public --


def test_an_envoy_steps_by_adjacency_into_a_neutral_capital(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert territory.plan(g.state, piece(g.state, "norra_herald"), ISLE) == Plan((ISLE,), (3,))
    g.send("ilse", "norra_herald", "isle")
    out = g.walk(day(1), day(2))
    assert piece(g.state, "norra_herald").places == (PLAIN,)
    out = g.walk(day(3), day(3))
    (step,) = [e.payload for e in out if isinstance(e.payload, ev.PieceStepped)]
    assert (step.left, step.entered, step.on) == (PLAIN, ISLE, ARRIVES)


def test_an_envoy_opens_no_battle_and_is_never_destroyed(tmp_path: Path) -> None:
    """Sudland's levy marches into the Norra Hills, where the herald stands alone."""
    g = game(tmp_path, strengths(), on=("holders", "battles"))
    stand(g, "norra_herald", HILLS)
    assert battle.fighting_area(g.state, piece(g.state, "norra_herald")) is None
    g.send("tomas", "sudland_levy", "norra_hills")
    out = g.walk(day(1), day(30))
    assert piece(g.state, "sudland_levy").places == (HILLS,)
    assert not [e for e in out if isinstance(e.payload, ev.BattleOpened)]
    herald = piece(g.state, "norra_herald")
    assert in_play(herald) and herald.lost_on is None and herald.places == (HILLS,)


def test_an_envoy_beside_a_force_takes_no_part_in_its_battle(tmp_path: Path) -> None:
    g = game(tmp_path, strengths(norra_levy=1), on=("holders", "battles"))
    stand(g, "norra_herald", HILLS)
    stand(g, "norra_levy", HILLS)
    g.send("tomas", "sudland_levy", "norra_hills")
    out = g.walk(day(1), day(60))
    (opened,) = [e.payload for e in out if isinstance(e.payload, ev.BattleOpened)]
    assert opened.battle.defender.pieces == (FeatureId(entity("norra_levy")),)
    assert [e for e in out if isinstance(e.payload, ev.BattleEnded)]
    herald = piece(g.state, "norra_herald")
    assert in_play(herald) and herald.lost_on is None


def test_an_envoy_is_seen_by_every_other_nations_seat(tmp_path: Path) -> None:
    g = game(tmp_path, on=("holders", "reports"))
    g.walk(day(1), day(1))
    for who, nation in ((TOMAS, SUDLAND), (OLAF, OSTMARK)):
        found = [r for r in project(g.state, who).reports.values() if r.kind == "herald"]
        assert len(found) == 1
        (r,) = found
        today = g.state.in_world_date
        assert (r.area, r.seen, r.arrives) == (PLAIN, today, today)
        assert r.confidence is detect.Confidence.A
        assert r.key == detect.report_key(g.state, nation, HERALD)
    assert not [r for r in project(g.state, ILSE).reports.values() if r.kind == "herald"]


def test_an_envoy_is_public_without_the_reports_rule(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.walk(day(1), day(1))
    assert [r.kind for r in project(g.state, TOMAS).reports.values()] == ["herald"]


def test_an_envoy_moved_shows_where_it_stands_now(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.send("ilse", "norra_herald", "isle")
    g.walk(day(1), day(3))
    (r,) = project(g.state, TOMAS).reports.values()
    assert (r.area, r.seen) == (ISLE, g.state.in_world_date)


# --- Rule 2: an offer carried by an envoy is delivered at the capital ------------------


def test_an_offer_carried_by_an_envoy_is_delivered_the_day_it_reaches_the_capital(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    g.send("ilse", "norra_herald", "isle")
    oid = offer(g)
    g.walk(day(1), day(2))
    assert oid not in g.state.agreements.offers
    assert oid not in project(g.state, OLAF).agreements.offers
    assert papers_to(g, OLAF) == []
    assert all(p.decided is None for p in g.state.routed[oid].parts)
    g.walk(ARRIVES, ARRIVES)
    found = g.state.agreements.offers[oid]
    assert (found.filed, found.expires) == (START, ARRIVES + timedelta(days=OFFER_DAYS))
    assert oid in project(g.state, OLAF).agreements.offers
    (paper,) = papers_to(g, OLAF)
    assert paper.arrives == ARRIVES
    answer_by = [b.value for b in paper.body if b.label == "Answer by"]
    assert answer_by == [process.day_words(ARRIVES + timedelta(days=OFFER_DAYS))]


def test_a_carried_offers_expiry_counts_from_its_delivery(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.send("ilse", "norra_herald", "isle")
    oid = offer(g)
    g.walk(day(1), ARRIVES)
    due = ARRIVES + timedelta(days=OFFER_DAYS)
    assert process.offer_due(g.state, g.state.routed[oid]) == due
    from tests.test_agreements import answer

    answer(g, oid, OLAF, True)
    g.walk(day(4), due - timedelta(days=1))
    assert g.state.agreements.made == {}
    out = g.walk(due, due)
    (x,) = [e.payload for e in out if isinstance(e.payload, ev.AgreementMade)]
    assert x.agreement.made == due and x.agreement.parties == (NORRA, OSTMARK)


def test_an_envoy_already_at_the_capital_delivers_on_the_day_filed(tmp_path: Path) -> None:
    g = game(tmp_path)
    stand(g, "norra_herald", ISLE)
    oid = offer(g)
    g.walk(day(1), day(1))
    found = g.state.agreements.offers[oid]
    assert found.expires == START + timedelta(days=OFFER_DAYS)


def test_an_offer_whose_envoy_never_arrives_lapses_unseen_by_the_other_side(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    oid = offer(g)
    lapse = START + timedelta(days=agreement.CARRY_DAYS)
    g.walk(day(1), lapse - timedelta(days=1))
    assert all(p.decided is None for p in g.state.routed[oid].parts)
    out = g.walk(lapse, lapse)
    assert not [e for e in out if isinstance(e.payload, ev.AgreementOffered)]
    assert all(p.decided is not None and not p.accepted for p in g.state.routed[oid].parts)
    assert all(p.applied is not None for p in g.state.routed[oid].parts)
    papers = [e.payload.document for e in out if isinstance(e.payload, ev.DocumentIssued)]
    assert [p.scope.known_by for p in papers] == [frozenset({ILSE})]
    assert "envoy" in " ".join(str(b.value) for b in papers[0].body)
    assert papers_to(g, OLAF) == []
    assert project(g.state, OLAF).agreements.offers == {}


def test_an_envoy_must_be_the_offering_nations_own(tmp_path: Path) -> None:
    g = game(tmp_path)
    lent = Deal(
        counterparty=OSTMARK,
        parties=(NORRA, OSTMARK),
        wording="Friendship.",
        envoy=FeatureId(entity("norra_levy")),
    )
    assert "envoy" in refused_offer(g, lent)


def test_an_envoy_carries_an_offer_to_one_nation(tmp_path: Path) -> None:
    g = game(tmp_path)
    three = Deal(
        counterparty=OSTMARK,
        parties=(NORRA, OSTMARK, SUDLAND),
        wording="Friendship.",
        envoy=HERALD,
    )
    assert "one other nation" in refused_offer(g, three)


def test_an_envoy_goes_only_to_a_nation_with_a_capital(tmp_path: Path) -> None:
    g = game(tmp_path, set_entity("ostmark", capital=None))
    d = Deal(counterparty=OSTMARK, parties=(NORRA, OSTMARK), wording="Friendship.", envoy=HERALD)
    assert "capital" in refused_offer(g, d)


# --- Rule 3: letters arrive the same day while an envoy stands at the capital ----------


def test_letters_to_the_leader_arrive_the_same_day_while_an_envoy_is_at_his_capital(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, courier_to_olaf)
    oid = offer(g, envoy=None)
    routed = g.state.routed[oid]
    assert process.arrives(g.state, routed, routed.parts[0]) == START + timedelta(days=5)

    (tmp_path / "with").mkdir()
    h = game(tmp_path / "with", courier_to_olaf)
    stand(h, "norra_herald", ISLE)
    oid = offer(h, envoy=None)
    routed = h.state.routed[oid]
    assert process.arrives(h.state, routed, routed.parts[0]) == START
    assert process.offer_due(h.state, routed) == START + timedelta(days=OFFER_DAYS)
    h.walk(day(1), day(1))
    (paper,) = papers_to(h, OLAF)
    assert paper.arrives == START


def test_an_envoy_elsewhere_or_arriving_after_the_letter_changes_nothing(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, courier_to_olaf)
    g.send("ilse", "norra_herald", "isle")
    oid = offer(g, envoy=None)
    g.walk(day(1), ARRIVES)
    routed = g.state.routed[oid]
    assert piece(g.state, "norra_herald").places == (ISLE,)
    assert process.arrives(g.state, routed, routed.parts[0]) == START + timedelta(days=5)


def test_only_the_leaders_letters_are_quickened(tmp_path: Path) -> None:
    def not_head(w: World) -> None:
        for c in w["cards"]:
            if c["person"] == "olaf":
                c["reach"] = {"rank": 3}

    g = game(tmp_path, courier_to_olaf, not_head)
    stand(g, "norra_herald", ISLE)
    oid = offer(g, envoy=None)
    routed = g.state.routed[oid]
    assert process.arrives(g.state, routed, routed.parts[0]) == START + timedelta(days=5)


# --- Rule 4: an envoy may not enter the territory of a nation at war with its own ------


def test_an_envoy_may_not_enter_an_enemys_territory(tmp_path: Path) -> None:
    g = game(tmp_path)
    found = territory.plan(g.state, piece(g.state, "norra_herald"), COAST)
    assert isinstance(found, Refused)
    assert "at war" in found.reason
    assert COAST not in territory.plans(g.state, piece(g.state, "norra_herald"))
    assert territory.plan(g.state, piece(g.state, "norra_herald"), entity("the_gulf")) == Plan(
        (entity("the_gulf"),), (2,)
    )


def test_an_envoy_under_way_halts_at_the_border_of_a_new_enemy(tmp_path: Path) -> None:
    g = game(tmp_path)
    g.send("ilse", "norra_herald", "isle")
    war = War(
        war_id=war_id_for(NORRA, OSTMARK),
        a=NORRA,
        b=OSTMARK,
        since=day(1),
        declared_by=entity("ilse"),
    )
    g.add([ev.WarDeclared(war=war)])
    g.walk(day(1), day(5))
    herald = piece(g.state, "norra_herald")
    assert herald.places == (PLAIN,) and herald.path == ()


# --- Rule 5: no detection roll is made on an envoy -------------------------------------


def test_no_source_sights_an_envoy(tmp_path: Path) -> None:
    g = game(tmp_path, on=("holders", "reports"))
    stand(g, "norra_herald", HILLS)
    stand(g, "norra_kites", HILLS)
    found = detect.sightings(g.state, g.state, day(1), SUDLAND)
    assert HERALD not in [s.force.feature_id for s in found]
    assert FeatureId(entity("norra_kites")) in [s.force.feature_id for s in found]
    g.walk(day(1), day(20))
    picture = g.state.reports.get(SUDLAND)
    made = [*picture.delivered.values(), *picture.pending] if picture is not None else []
    assert detect.report_key(g.state, SUDLAND, HERALD) not in [r.key for r in made]
