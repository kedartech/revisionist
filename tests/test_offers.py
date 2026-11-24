"""The priced move: an offer to a bloc, with a promise that comes due (PRC).

The toy world (``tests/worlds/territory-toy.yaml``) with ``groups``, ``laws`` and
``offers`` on, and Kara Lind, Norra's general, as a second seat of Norra beside Ilse
Varg; Tomas Brand holds Sudland. Ilse sends bills to the assembly through the clerks,
three world days a bill. The Greens stand at their baseline and split evenly on the
toy world's own law, the Barge Act (25 to 25 of 50 voting), so the act fails unless an
offer moves them; the Greys cast no vote on it. The Greens carry two prices: the harbour
dues lifted (2 points, due ten days after the act, 6 support lost if unmet) and a seat
for the guild (3 points, due ten days after, 4 lost), each read from a flag the world
declares.
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from revisionist.core import events as ev
from revisionist.core.fold import FoldError, replay
from revisionist.core.goals import goal_met
from revisionist.core.ids import EntityId, OrderId, PipelineId, derived_id
from revisionist.core.project import project
from revisionist.core.realism import groups, offers
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.groups import Cause
from revisionist.core.realism.offers import OffersError, OfferStanding
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.state import Rule, State
from revisionist.core.visibility import Visibility
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import object_id
from revisionist.engine import catchup, realism_tick
from revisionist.engine.store import MemoryStore, load_state
from tests.test_adjacency_moves import Logged
from tests.test_realism_command import card, general
from tests.test_realism_locks import key_id, seat
from tests.test_territory_model import CAMPAIGN, created, refused, variant

World = dict[str, Any]
DAY = date(1900, 4, 2)
ILSE, KARA, TOMAS = key_id("ilse"), key_id("kara"), key_id("tomas")
NORRA = key_id("norra")
MEASURE = "barge_act"
BILL_DAYS = 3
DUE_DAYS = 10
VOTE = DAY + timedelta(days=BILL_DAYS)
DUE = VOTE + timedelta(days=DUE_DAYS)
DUES, GUILD = "harbour_dues", "guild_seat"
DUES_FLAG, GUILD_FLAG = "harbour_dues_lifted", "guild_seat_given"


def day(n: int) -> date:
    return DAY + timedelta(days=n)


def _flag(key: str, name: str, value: int = 0) -> World:
    return {
        "key": key,
        "owner": "norra",
        "name": name,
        "value": value,
        "unit": "flag",
        "source": "toy",
    }


def _price(key: str, flag: str, points: int, loss: int) -> World:
    return {
        "key": key,
        "sentence": f"Set {flag.replace('_', ' ')} within ten days of the act.",
        "condition": {"check": "quantity_at", "quantity": flag, "op": "ge", "value": 1},
        "days": DUE_DAYS,
        "points": points,
        "loss": loss,
    }


def _bloc(w: World, key: str) -> World:
    norra = next(n for n in w["groups"] if n["nation"] == "norra")
    found: World = next(g for g in norra["groups"] if g["key"] == key)
    return found


def priced(w: World) -> None:
    w["rules"] = sorted({*w["rules"], "groups", "laws", "offers"})
    w["quantities"] += [_flag(DUES_FLAG, "Harbour dues lifted"), _flag(GUILD_FLAG, "Guild seat")]
    greens = _bloc(w, "greens")
    greens.update(start=55, baseline=55)
    greens["prices"] = [_price(DUES, DUES_FLAG, 2, 6), _price(GUILD, GUILD_FLAG, 3, 4)]
    w["pipelines"] = [
        {
            "key": "clerks",
            "name": "The clerks",
            "source": "toy",
            "steps": [{"person": "kara", "kind": "clerical", "days": BILL_DAYS}],
        }
    ]
    card(w, "ilse")["pipelines"] = ["clerks"]
    card(w, "ilse")["levers"] = [
        {
            "name": "propose",
            "pipeline": "clerks",
            "resolver": "votes",
            "params": [{"name": "bill", "kind": "enum", "choices": [MEASURE]}],
        }
    ]


def world(tmp: Path, *changes: Callable[[World], None]) -> WorldFile:
    def change(w: World) -> None:
        for c in (general, priced, *changes):
            c(w)

    return variant(tmp, change)


class Game(Logged):
    """The game with Ilse, Kara and Tomas each claimed by a seat of their own."""

    def __init__(self, w: WorldFile) -> None:
        self.log, _ = created(w)
        self.state = replay(self.log)
        self.add([ev.CharacterClaimed(seat_id=seat(p), entity_id=p) for p in (ILSE, KARA, TOMAS)])


def game(tmp: Path, *changes: Callable[[World], None]) -> Game:
    return Game(world(tmp, *changes))


def bill(g: Game, n: int = 1) -> OrderId:
    """Ilse sends the Barge Act to the assembly on the start day."""
    order = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "bill", n)),
        issuer=seat(ILSE),
        lever="propose",
        pipeline=PipelineId(object_id(CAMPAIGN, "pipeline", "clerks")),
        params={"bill": MEASURE},
        filed=DAY,
    )
    g.add([ev.OrderDrafted(order=order)])
    return order.order_id


def offer(g: Game, person: EntityId, key: str = DUES, on: date = DAY) -> ev.OfferMade:
    made = offers.offer(g.state, seat(person), "greens", MEASURE, key, on)
    g.add([made])
    g.log[-1] = g.log[-1].model_copy(update={"scope": realism_tick._nation_scope(g.state, NORRA)})
    return made


def flag(g: Game, key: str, value: int, on: date) -> None:
    change = QuantityChange(quantity_id=rs.qid(g.state, key), value=value, as_of=on)
    g.add(rs.apply_changes(g.state, (change,)))


def passed(state: State) -> int | None:
    return rs.value(state, f"{MEASURE}_passed")


def settled(events: Sequence[ev.Event]) -> list[ev.OfferSettled]:
    return [e.payload for e in events if isinstance(e.payload, ev.OfferSettled)]


def moved(events: Sequence[ev.Event], cause: Cause) -> list[ev.GroupMoved]:
    return [
        e.payload
        for e in events
        if isinstance(e.payload, ev.GroupMoved) and e.payload.cause is cause
    ]


def support(g: Game) -> int | None:
    return groups.support(g.state, NORRA, "greens")


def only(g: Game) -> offers.PricedOffer:
    (found,) = g.state.offers
    return found


# --- rule 1: a bloc's prices, each a thing an act changes by a date --------------------


def test_a_blocs_prices_reach_state_with_their_keys_bound(tmp_path: Path) -> None:
    g = game(tmp_path)
    greens = groups.group(g.state, NORRA, "greens")
    assert greens is not None
    assert [p.key for p in greens.prices] == [DUES, GUILD]
    dues = greens.prices[0]
    assert (dues.days, dues.points, dues.loss) == (DUE_DAYS, 2, 6)
    assert dues.condition.quantity == rs.qid(g.state, DUES_FLAG)  # type: ignore[union-attr]


def test_a_price_whose_condition_no_act_changes_is_refused(tmp_path: Path) -> None:
    def watched(w: World) -> None:
        _bloc(w, "greens")["prices"][0]["condition"] = {
            "check": "all_of",
            "conditions": [
                {"check": "at_war", "a": "norra", "b": "sudland", "war": False},
                {
                    "check": "support_at",
                    "nation": "norra",
                    "group": "greys",
                    "op": "ge",
                    "value": 40,
                },
            ],
        }

    problems = refused(world(tmp_path, watched))
    assert any(f"price {DUES}: its condition holds nothing an act changes" in p for p in problems)

    def acted(w: World) -> None:
        watched(w)
        _bloc(w, "greens")["prices"][0]["condition"]["conditions"].append(
            {"check": "ordered", "person": "ilse", "effect": "statement"}
        )

    (tmp_path / "acted").mkdir()
    created(world(tmp_path / "acted", acted))


def test_a_price_naming_what_the_world_lacks_or_on_a_group_no_chamber_holds_is_refused(
    tmp_path: Path,
) -> None:
    def unknown(w: World) -> None:
        _bloc(w, "greens")["prices"][0]["condition"]["quantity"] = "no_such_flag"
        _bloc(w, "greens")["prices"][1]["key"] = DUES

    problems = refused(world(tmp_path, unknown))
    assert any("no_such_flag" in p for p in problems)
    assert any("greens: a price key is given twice" in p for p in problems)

    def unseated(w: World) -> None:
        _bloc(w, "smiths")["prices"] = [_price("tools", DUES_FLAG, 1, 1)]

    (tmp_path / "unseated").mkdir()
    with pytest.raises(ValueError, match="only a chamber's bloc has prices"):
        world(tmp_path / "unseated", unseated)


# --- rule 2: one live offer per bloc per measure, settled by content ------------------


def test_a_seat_of_the_blocs_nation_offers_a_price_for_a_measure_whose_bill_is_on_its_way(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    with pytest.raises(OffersError, match=offers.NO_BILL):
        offers.offer(g.state, seat(ILSE), "greens", MEASURE, DUES, DAY)
    bill(g)
    with pytest.raises(OffersError, match=offers.NO_BLOC):  # Sudland has no Greens
        offers.offer(g.state, seat(TOMAS), "greens", MEASURE, DUES, DAY)
    with pytest.raises(OffersError, match=offers.NO_PRICE):
        offers.offer(g.state, seat(ILSE), "greens", MEASURE, "a_bridge", DAY)
    with pytest.raises(OffersError, match=offers.NO_BLOC):
        offers.offer(g.state, seat(ILSE), "smiths", MEASURE, DUES, DAY)
    with pytest.raises(OffersError, match=offers.NO_BILL):
        offers.offer(g.state, seat(ILSE), "greens", "levy_act", DUES, DAY)
    made = offer(g, KARA)
    assert made.offer.standing is OfferStanding.FILED and made.offer.bill == OrderId(
        derived_id(CAMPAIGN, "bill", 1)
    )
    with pytest.raises(OffersError, match=offers.FILED):
        offers.offer(g.state, seat(KARA), "greens", MEASURE, DUES, DAY)
    g.walk(day(1), day(1))
    assert only(g).standing is OfferStanding.TAKEN and only(g).on == day(1)


def test_a_second_offer_on_a_bloc_already_held_is_refused(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    offer(g, ILSE)
    g.walk(day(1), day(1))
    with pytest.raises(OffersError, match=offers.LIVE):
        offers.offer(g.state, seat(KARA), "greens", MEASURE, GUILD, day(1))
    late = offers.offer(
        g.state.model_copy(update={"offers": ()}), seat(KARA), "greens", MEASURE, GUILD, day(1)
    )
    g.add([late])
    out = g.walk(day(2), day(2))
    assert [(s.standing, s.on) for s in settled(out)] == [(OfferStanding.REFUSED, day(2))]
    assert offers.points(g.state, NORRA, "greens", MEASURE) == 2
    taken = ev.OfferSettled(offer_id=late.offer.offer_id, standing=OfferStanding.TAKEN, on=day(2))
    with pytest.raises(FoldError, match="cannot go from refused to taken"):
        g.add([taken])
    again = offers.offer(
        g.state.model_copy(update={"offers": ()}), seat(KARA), "greens", MEASURE, GUILD, day(2)
    )
    g.add([again])
    taken = ev.OfferSettled(offer_id=again.offer.offer_id, standing=OfferStanding.TAKEN, on=day(2))
    with pytest.raises(FoldError, match="greens is held on barge_act already"):
        g.add([taken])


def _digest(g: Game, out: Sequence[ev.Event]) -> str:
    body = {
        "settled": [s.model_dump(mode="json") for s in settled(out)],
        "offers": [
            o.model_dump(mode="json") for o in sorted(g.state.offers, key=lambda o: o.offer_id)
        ],
        "groups": g.state.groups.model_dump(mode="json"),
        "passed": passed(g.state),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _two_seats(w: WorldFile, first: EntityId, second: EntityId, keys: tuple[str, str]) -> str:
    g = Game(w)
    bill(g)
    by = {ILSE: keys[0], KARA: keys[1]}
    offer(g, first, by[first])
    offer(g, second, by[second])
    return _digest(g, g.walk(day(1), DUE))


def test_two_seats_offering_one_bloc_in_one_wake_give_one_digest_in_both_orders(
    tmp_path: Path,
) -> None:
    w = world(tmp_path)
    for keys in ((DUES, GUILD), (GUILD, DUES), (DUES, DUES)):
        assert _two_seats(w, ILSE, KARA, keys) == _two_seats(w, KARA, ILSE, keys)
    g = Game(w)
    bill(g)
    offer(g, KARA, DUES)
    offer(g, ILSE, GUILD)
    out = g.walk(day(1), day(1))
    taken = {s.offer_id: s.standing for s in settled(out)}
    by_price = {o.price: taken[o.offer_id] for o in g.state.offers}
    assert by_price == {GUILD: OfferStanding.TAKEN, DUES: OfferStanding.REFUSED}


# --- rule 3: the price's points count on the measure from the day the offer lands ------


def test_an_offer_moves_the_count_and_the_measure_passes_by_it(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    offer(g, ILSE)
    assert offers.points(g.state, NORRA, "greens", MEASURE) == 0
    g.walk(day(1), day(1))
    assert offers.points(g.state, NORRA, "greens", MEASURE) == 2
    assert offers.points(g.state, NORRA, "greys", MEASURE) == 0
    g.walk(day(2), VOTE)
    assert g.state.orders[OrderId(derived_id(CAMPAIGN, "bill", 1))].status is OrderStatus.ENACTED
    assert passed(g.state) == 1


def test_the_same_script_without_the_offer_fails(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    g.walk(day(1), VOTE)
    q = g.state.quantities[rs.qid(g.state, f"{MEASURE}_passed")]
    assert (q.value, q.as_of) == (0, VOTE)


def test_with_offers_off_nothing_is_offered_and_no_point_counts(tmp_path: Path) -> None:
    def off(w: World) -> None:
        w["rules"] = [r for r in w["rules"] if r != "offers"]

    g = game(tmp_path, off)
    greens = groups.group(g.state, NORRA, "greens")
    assert greens is not None and greens.prices == ()
    bill(g)
    with pytest.raises(OffersError, match=offers.NOT_ON):
        offers.offer(g.state, seat(ILSE), "greens", MEASURE, DUES, DAY)
    (tmp_path / "on").mkdir()
    on = game(tmp_path / "on")
    bill(on)
    offer(on, ILSE)
    on.walk(day(1), day(1))
    plain = on.state.model_copy(update={"rules": on.state.rules - {Rule.OFFERS}})
    assert offers.points(plain, NORRA, "greens", MEASURE) == 0
    assert offers.batch(plain, day(2)) == [] and offers.walk(plain, DUE) == []


# --- rule 4: the promise binds only if the measure passes, and is read on its day ------


def test_the_promise_kept_on_its_due_day(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    offer(g, ILSE)
    g.walk(day(1), VOTE)
    assert only(g).standing is OfferStanding.DUE and only(g).due == DUE
    assert offers.points(g.state, NORRA, "greens", MEASURE) == 0
    flag(g, DUES_FLAG, 1, day(5))
    out = g.walk(VOTE + timedelta(days=1), DUE - timedelta(days=1))
    assert not settled(out) and only(g).standing is OfferStanding.DUE
    out = g.walk(DUE, DUE)
    assert [(s.standing, s.on) for s in settled(out)] == [(OfferStanding.KEPT, DUE)]
    (kept,) = moved(out, Cause.PROMISE_KEPT)
    assert (kept.group, kept.change, kept.on) == ("greens", offers.KEPT_POINTS, DUE)
    assert support(g) == 55 + offers.KEPT_POINTS


def test_the_promise_broken_on_its_due_day(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    offer(g, ILSE)
    out = g.walk(day(1), DUE)
    assert [s.standing for s in settled(out)] == [
        OfferStanding.TAKEN,
        OfferStanding.DUE,
        OfferStanding.BROKEN,
    ]
    assert settled(out)[-1].on == DUE
    (broken,) = moved(out, Cause.PROMISE_BROKEN)
    assert (broken.change, broken.on) == (-6, DUE)
    assert support(g) == 55 - 6


def test_the_promise_is_read_from_state_on_its_due_day_not_when_the_offer_was_made(
    tmp_path: Path,
) -> None:
    def lifted(w: World) -> None:
        next(q for q in w["quantities"] if q["key"] == DUES_FLAG)["value"] = 1

    g = game(tmp_path, lifted)
    bill(g)
    offer(g, ILSE)
    out = g.walk(day(1), day(5))
    assert goal_met(g.state, offers.price(g.state, NORRA, "greens", DUES).condition)  # type: ignore[union-attr]
    assert [s.standing for s in settled(out)] == [OfferStanding.TAKEN, OfferStanding.DUE]
    flag(g, DUES_FLAG, 0, day(5))
    out = g.walk(day(6), DUE)
    assert [(s.standing, s.on) for s in settled(out)] == [(OfferStanding.BROKEN, DUE)]


def test_the_promise_binds_only_if_the_measure_passes(tmp_path: Path) -> None:
    def split(w: World) -> None:
        _bloc(w, "greens")["vote_default"] = {"assembly": {"voting": 50, "yeas": 20}}

    g = game(tmp_path, split)
    bill(g)
    offer(g, ILSE)
    g.walk(day(1), day(1))
    assert offers.points(g.state, NORRA, "greens", MEASURE) == 2
    out = g.walk(day(2), DUE + timedelta(days=3))
    assert passed(g.state) == 0
    assert [(s.standing, s.on) for s in settled(out)] == [(OfferStanding.LAPSED, VOTE)]
    assert offers.points(g.state, NORRA, "greens", MEASURE) == 0
    assert offers.live(g.state, NORRA, "greens", MEASURE) is None
    assert not moved(out, Cause.PROMISE_BROKEN) and support(g) == 55


def test_a_restart_between_the_offer_and_its_due_day_gives_one_outcome(tmp_path: Path) -> None:
    w = world(tmp_path)
    straight, broken = Game(w), Game(w)
    for g in (straight, broken):
        bill(g)
        offer(g, ILSE)
    straight.walk(day(1), DUE)
    broken.walk(day(1), day(6))
    broken.state = replay(broken.log)
    broken.walk(day(7), DUE)
    assert straight.state.offers == broken.state.offers
    assert settled(straight.log) == settled(broken.log)
    assert support(straight) == support(broken) == 55 - 6


# --- rule 5: an offer and its outcome are sealed to the seats of the bloc's nation -----


def test_an_offer_and_its_outcome_are_sealed_to_the_seats_of_the_blocs_nation(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    bill(g)
    store = MemoryStore()
    store.append_all(g.log)
    made = realism_tick.make_offer(store, CAMPAIGN, seat(ILSE), "greens", MEASURE, DUES)
    assert (made.filed, made.standing) == (DAY, OfferStanding.FILED)
    g.log, g.state = list(store.read(CAMPAIGN)), load_state(store, CAMPAIGN)
    g.walk(day(1), DUE)
    found = [e for e in g.log if isinstance(e.payload, ev.OfferMade | ev.OfferSettled)]
    assert len(found) == 4
    for e in found:
        assert e.scope.visibility is Visibility.RESTRICTED
        assert e.scope.known_by == frozenset({seat(ILSE), seat(KARA)})
    assert project(g.state, seat(KARA)).offers == g.state.offers
    assert project(g.state, seat(TOMAS)).offers == ()
    kinds = {"offer_made", "offer_settled"}
    for person, n in ((ILSE, 4), (KARA, 4), (TOMAS, 0)):
        fed = catchup.feed(g.state, g.log, seat(person), 0, 99)
        assert len([f for f in fed if f.event.kind in kinds]) == n


def _abroad(tmp: Path, made: bool) -> tuple[str, list[Any]]:
    g = game(tmp)
    bill(g)
    if made:
        offer(g, ILSE)
    g.walk(day(1), day(2))
    view = project(g.state, seat(TOMAS)).model_dump_json()
    fed = [
        f.event.payload.model_dump(mode="json")
        for f in catchup.feed(g.state, g.log, seat(TOMAS), 0, 99)
    ]
    return view, fed


def test_a_seat_of_another_nation_gets_the_same_data_with_and_without_the_offer(
    tmp_path: Path,
) -> None:
    (tmp_path / "with").mkdir()
    (tmp_path / "without").mkdir()
    assert _abroad(tmp_path / "with", True) == _abroad(tmp_path / "without", False)


# --- rule 6: the aide never makes an offer ----------------------------------------------


def test_the_walk_never_makes_an_offer_for_a_seat(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    out = g.walk(day(1), DUE)
    assert not [e for e in out if isinstance(e.payload, ev.OfferMade)]
    assert g.state.offers == ()


# --- rule 7: three new causes -----------------------------------------------------------


def test_a_group_may_be_moved_by_an_offer_taken_a_promise_kept_or_broken() -> None:
    assert {c.value for c in Cause} >= {"offer_taken", "promise_kept", "promise_broken"}


def test_an_offer_and_its_outcome_are_fed_to_the_seats_that_see_them() -> None:
    assert {"offer_made", "offer_settled"} <= catchup.FEED_KINDS
