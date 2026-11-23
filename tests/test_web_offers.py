"""The priced move as the seat sees it, with its check and its action (PRR).

The toy world of ``tests/test_offers.py``: ``groups``, ``laws`` and ``offers`` on; Ilse
Varg and Kara Lind sit for Norra, Tomas Brand for Sudland. Ilse sends the Barge Act to the
assembly; the Greens split evenly on it and carry two prices, the harbour dues lifted and a
seat for the guild; the Greys cast no vote on it.

With ``offers`` on, the seat's ``home`` block lists, for each measure of its own nation on
its way, every bloc that votes on it with the prices it would take and the offer that holds
it, and the promises the seat itself has made, each with its due day once the measure has
passed. The check before sending answers a draft offer with what filing it would do; the
``offer`` action files one, and is held by a commit like any order. A promise come due is a
line in the wake notice and in what waits on the seat. Nothing of it reaches another
nation's seat, and with ``offers`` off the block is as it was.
"""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from revisionist.core.ids import EntityId
from revisionist.core.project import project
from revisionist.core.realism import offers
from revisionist.core.realism.offers import OfferStanding
from revisionist.engine import notice, realism_tick
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import agenda_api, held, home_api, locks_api, server
from revisionist.engine.web import realism_api as api
from tests import test_offers as to
from tests.test_offers import (
    DUE,
    DUES,
    DUES_FLAG,
    GUILD,
    GUILD_FLAG,
    ILSE,
    KARA,
    MEASURE,
    TOMAS,
    VOTE,
    Game,
    World,
    bill,
    day,
    game,
    offer,
)
from tests.test_realism_locks import seat
from tests.test_territory_model import CAMPAIGN
from tests.test_web import Client, Web, web  # noqa: F401
from tests.test_web_realism import Realism, make_host, post, realism_of
from tests.test_web_wake import begin

FIXTURE = Path(__file__).parents[1] / "web" / "test" / "fixtures" / "realism-seat.json"
ACT = "The Barge Act"


def home(g: Game, person: EntityId) -> api.HomeBlock:
    found = home_api.block(g.state, project(g.state, seat(person)), g.log)
    assert found is not None
    return found


def off(w: World) -> None:
    w["rules"] = [r for r in w["rules"] if r != "offers"]


def sentence(flag: str) -> str:
    return f"Set {flag.replace('_', ' ')} within ten days of the act."


def price(key: str, flag: str, points: int, loss: int) -> api.OfferPrice:
    return api.OfferPrice(
        key=key, sentence=sentence(flag), points=points, days=to.DUE_DAYS, loss=loss
    )


def promises(g: Game, person: EntityId) -> list[agenda_api.DueMatter]:
    return [m for m in agenda_api.due_matters(g.state, seat(person)) if m.kind == "promise"]


# --- rule 2: the home data lists the prices, the live offer and the seat's promises -----


def test_each_measure_on_its_way_lists_each_blocs_prices(tmp_path: Path) -> None:
    g = game(tmp_path)
    assert home(g, ILSE)["offers"] == []
    bill(g)
    (measure,) = home(g, ILSE)["offers"]
    assert (measure["key"], measure["title"]) == (MEASURE, ACT)
    blocs = {b["group"]: b for b in measure["blocs"]}
    assert set(blocs) == {"greens"}  # the Greys cast no vote on the act
    assert blocs["greens"] == api.OfferBloc(
        group="greens",
        name="The Greens",
        prices=[price(DUES, DUES_FLAG, 2, 6), price(GUILD, GUILD_FLAG, 3, 4)],
        live=None,
    )
    assert home(g, KARA)["offers"] == home(g, ILSE)["offers"]  # the nation's measure


def test_the_live_offer_shows_on_its_bloc_once_it_lands(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    offer(g, KARA)
    assert home(g, ILSE)["offers"][0]["blocs"][0]["live"] is None  # filed, not yet taken
    g.walk(day(1), day(1))
    seen = home(g, ILSE)["offers"][0]["blocs"][0]["live"]
    assert seen == api.LiveOffer(price=DUES, points=2, mine=False)
    mine = home(g, KARA)["offers"][0]["blocs"][0]["live"]
    assert mine == api.LiveOffer(price=DUES, points=2, mine=True)


def test_each_promise_the_seat_made_is_listed_with_its_due_day(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    made = offer(g, ILSE).offer
    (filed,) = home(g, ILSE)["promises"]
    assert filed == api.OfferPromise(
        offer_id=made.offer_id,
        group="greens",
        name="The Greens",
        measure=MEASURE,
        title=ACT,
        price=DUES,
        sentence=sentence(DUES_FLAG),
        standing="filed",
        filed=to.DAY.isoformat(),
        due=None,
    )
    assert home(g, KARA)["promises"] == []  # each promise the seat itself made
    g.walk(day(1), VOTE)
    (due,) = home(g, ILSE)["promises"]
    assert (due["standing"], due["due"]) == ("due", DUE.isoformat())
    assert home(g, ILSE)["offers"] == []  # passed: no longer on its way
    g.walk(VOTE + timedelta(days=1), DUE)
    (broken,) = home(g, ILSE)["promises"]
    assert (broken["standing"], broken["due"]) == ("broken", DUE.isoformat())


def _greens(g: Game) -> tuple[int, int]:
    (chamber,) = [c for c in home(g, ILSE)["chambers"] if c["key"] == "assembly"]
    (measure,) = chamber["measures"]
    (vote,) = measure["votes"]
    (found,) = [(b["yeas"], b["nays"]) for b in vote["blocs"] if b["group"] == "greens"]
    return found


def test_the_count_on_the_floor_moves_with_the_offer(tmp_path: Path) -> None:
    (tmp_path / "with").mkdir()
    (tmp_path / "without").mkdir()
    made, plain = game(tmp_path / "with"), game(tmp_path / "without")
    for g in (made, plain):
        bill(g)
    offer(made, ILSE)
    for g in (made, plain):
        g.walk(day(1), day(1))
    assert _greens(plain) == (25, 25)
    assert _greens(made) == (26, 24)  # 2 points on 50 voting


def test_with_offers_off_the_home_block_is_as_it_was(tmp_path: Path) -> None:
    g = game(tmp_path, off)
    bill(g)
    block = home(g, ILSE)
    assert set(block) == api.HomeBlock.__required_keys__
    assert not {"offers", "promises"} & set(block)


# --- fog: another nation's seat gets no price list, offer or promise ----------------------


def _abroad(tmp: Path, made: bool) -> str:
    """Tomas's home block, what waits on him and his check of an offer to the Greens, on
    the day the offer lands (the act on its way) and on the promise's due day."""
    g = game(tmp)
    bill(g)
    if made:
        offer(g, ILSE)
    tomas = seat(TOMAS)
    seen = []
    for first, last in ((day(1), day(1)), (day(2), DUE)):
        g.walk(first, last)
        seen.append(
            {
                "home": home(g, TOMAS),
                "due": [m.__dict__ for m in agenda_api.due_matters(g.state, tomas)],
                "check": locks_api.check_offer(g.state, tomas, "greens", MEASURE, DUES),
            }
        )
    return json.dumps(seen, sort_keys=True)


def test_a_seat_of_another_nation_gets_no_price_list_offer_or_promise(tmp_path: Path) -> None:
    (tmp_path / "with").mkdir()
    (tmp_path / "without").mkdir()
    seen = _abroad(tmp_path / "with", True)
    assert seen == _abroad(tmp_path / "without", False)
    for day_seen in json.loads(seen):
        assert day_seen["home"]["offers"] == [] and day_seen["home"]["promises"] == []
    assert "harbour" not in seen and "Greens" not in seen and MEASURE not in seen


# --- rule 4: the check before sending equals what filing then does ------------------------


def _store(g: Game) -> MemoryStore:
    store = MemoryStore()
    store.append_all(g.log)
    return store


def _filed(g: Game, person: EntityId, bloc: str, measure: str, key: str) -> api.LockCheck:
    """What filing does, in the check's shape: allowed when it is filed, else the refusal."""
    try:
        realism_tick.make_offer(_store(g), CAMPAIGN, seat(person), bloc, measure, key)
    except ValueError as exc:
        return api.LockCheck(check="beyond", who=None, reason=str(exc))
    return locks_api.ALLOWED


CASES: tuple[tuple[EntityId, str, str, str, str], ...] = (
    (ILSE, "greens", MEASURE, DUES, ""),
    (KARA, "greens", MEASURE, GUILD, ""),
    (ILSE, "greens", "levy_act", DUES, offers.NO_BILL),
    (TOMAS, "greens", MEASURE, DUES, offers.NO_BLOC),
    (ILSE, "smiths", MEASURE, DUES, offers.NO_BLOC),
    (ILSE, "greens", MEASURE, "a_bridge", offers.NO_PRICE),
)


@pytest.mark.parametrize(("person", "bloc", "measure", "key", "reason"), CASES)
def test_the_check_equals_what_filing_then_does(
    tmp_path: Path, person: EntityId, bloc: str, measure: str, key: str, reason: str
) -> None:
    g = game(tmp_path)
    bill(g)
    checked = locks_api.check_offer(g.state, seat(person), bloc, measure, key)
    assert checked == _filed(g, person, bloc, measure, key)
    assert (checked["check"], checked["reason"]) == ("beyond" if reason else "allowed", reason)


def _case(g: Game, person: EntityId, key: str, reason: str) -> None:
    checked = locks_api.check_offer(g.state, seat(person), "greens", MEASURE, key)
    assert checked == _filed(g, person, "greens", MEASURE, key)
    assert (checked["check"], checked["reason"]) == ("beyond", reason)


def test_the_check_equals_filing_with_no_bill_twice_once_live_and_with_offers_off(
    tmp_path: Path,
) -> None:
    g = game(tmp_path)
    _case(g, ILSE, DUES, offers.NO_BILL)
    bill(g)
    offer(g, ILSE)
    _case(g, ILSE, DUES, offers.FILED)
    g.walk(day(1), day(1))
    _case(g, KARA, GUILD, offers.LIVE)
    (tmp_path / "off").mkdir()
    plain = game(tmp_path / "off", off)
    bill(plain)
    _case(plain, ILSE, DUES, offers.NOT_ON)


def test_the_check_files_nothing(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    before = list(g.log)
    assert locks_api.check_offer(g.state, seat(ILSE), "greens", MEASURE, DUES) == locks_api.ALLOWED
    assert g.log == before and g.state.offers == ()


# --- rule 3: the action files one, held by a commit like any order ------------------------


def test_offer_is_a_realism_action_sealed_by_a_commit() -> None:
    assert "offer" in server.REALISM_ACTIONS and "offer" in server.SEALED_BY_COMMIT


def test_the_offer_is_told_by_its_bloc_its_measure_and_its_price(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    made = offers.offer(g.state, seat(ILSE), "greens", MEASURE, DUES, to.DAY).offer
    assert home_api.offered(g.state, made) == (
        f"Offered to The Greens for {ACT}: {sentence(DUES_FLAG)}"
    )
    assert home_api.offer_label(g.state, seat(ILSE), "greens", MEASURE, DUES) == (
        f"Your offer to The Greens: {sentence(DUES_FLAG)}"
    )
    with pytest.raises(ValueError, match=offers.NO_PRICE):
        home_api.offer_label(g.state, seat(ILSE), "greens", MEASURE, "a_bridge")


def test_a_held_offer_is_filed_when_the_next_wake_opens(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    store = _store(g)
    args = {"bloc": "greens", "measure": MEASURE, "price": DUES}
    assert held.file_one(store, CAMPAIGN, seat(ILSE), "offer", args) is None
    (made,) = load_state(store, CAMPAIGN).offers
    assert (made.seat, made.price, made.standing) == (seat(ILSE), DUES, OfferStanding.FILED)
    again = held.file_one(store, CAMPAIGN, seat(KARA), "offer", args | {"price": "a_bridge"})
    assert again == offers.NO_PRICE


def test_the_server_answers_the_check_and_the_offer_and_holds_it_after_a_commit(
    web: Web,  # noqa: F811
    tmp_path: Path,
) -> None:
    to.world(tmp_path)
    played = Realism(web, world=str(tmp_path / "world.yaml"))
    ilse: Client = played.seat("ilse", "ilse")
    kara: Client = played.seat("kara", "kara")
    make_host(played, ilse)
    begin(played)
    status, out = post(ilse, "lever", lever="propose", params={"bill": MEASURE})
    assert status == 200 and not out["refused"], out
    draft = {"bloc": "greens", "measure": MEASURE, "price": DUES}
    status, out = post(ilse, "check", **draft)
    assert status == 200 and out == locks_api.ALLOWED, out
    assert realism_of(ilse)["home"]["promises"] == []  # the check filed nothing
    status, out = post(ilse, "offer", **draft)
    assert status == 200 and not out["refused"], out
    assert out["reply"] == f"Offered to The Greens for {ACT}: {sentence(DUES_FLAG)}"
    (made,) = realism_of(ilse)["home"]["promises"]
    assert (made["price"], made["standing"]) == (DUES, "filed")
    status, out = post(ilse, "check", **draft)
    assert out == {"check": "beyond", "who": None, "reason": offers.FILED}, out
    status, out = post(ilse, "offer", **draft)
    assert out == {"reply": offers.FILED, "refused": True}, out
    status, out = post(kara, "commit")
    assert status == 200, out
    status, out = post(kara, "offer", **(draft | {"price": GUILD}))
    assert status == 200 and not out["refused"] and "held" in out, out
    assert realism_of(kara)["home"]["promises"] == []  # held for the next wake
    status, out = post(kara, "offer", **(draft | {"price": "a_bridge"}))
    assert out == {"reply": offers.NO_PRICE, "refused": True}, out


# --- rule 5: a promise's due day in the wake notice and in what waits on the seat ---------


def test_a_promise_come_due_waits_on_the_seat_that_made_it(tmp_path: Path) -> None:
    g = game(tmp_path)
    bill(g)
    made = offer(g, ILSE).offer
    g.walk(day(1), day(1))
    assert promises(g, ILSE) == []  # binds only once the measure passes
    g.walk(day(2), VOTE)
    (line,) = promises(g, ILSE)
    assert line == agenda_api.DueMatter(
        "promise",
        made.offer_id,
        f"Your promise to The Greens: {sentence(DUES_FLAG).rstrip('.')}",
        None,
        DUE.isoformat(),
    )
    assert promises(g, KARA) == [] and promises(g, TOMAS) == []
    assert f"- {line.what}. Due {DUE.isoformat()}." in notice._waiting(g.state, seat(ILSE))
    g.walk(VOTE + timedelta(days=1), DUE)
    assert promises(g, ILSE) == []  # judged


# --- the fixture ----------------------------------------------------------------------


def fixture_game(tmp: Path) -> Game:
    """The game the seat fixture's ``home`` offers and promises are Ilse's of: her offer of
    the harbour dues to the Greens for the Barge Act, taken on the first day."""
    g = game(tmp)
    bill(g)
    offer(g, ILSE)
    g.walk(day(1), day(1))
    return g


def test_the_fixture_carries_the_offers_and_promises_of_a_played_game(tmp_path: Path) -> None:
    block = json.loads(FIXTURE.read_text())["home"]
    shown = home(fixture_game(tmp_path), ILSE)
    assert (block["offers"], block["promises"]) == (shown["offers"], shown["promises"])
    for m in block["offers"]:
        assert set(m) == set(api.OfferMeasure.__annotations__)
        for b in m["blocs"]:
            assert set(b) == set(api.OfferBloc.__annotations__)
            assert all(set(p) == set(api.OfferPrice.__annotations__) for p in b["prices"])
            assert set(b["live"]) == set(api.LiveOffer.__annotations__)
    assert all(set(p) == set(api.OfferPromise.__annotations__) for p in block["promises"])
