"""Votes and shipping read the world's laws (LAW).

With ``laws`` on, a law is found by what the world declares, never in the code tables
(``votes.HISTORICAL``, ``votes.TALLIES``): ``votes.in_force`` is ``laws.in_force``; a passed
law does what its ``does`` says, an arming law cutting a nation's shipping losses as the
arming clause does with the tables and a law that adds manpower adding its own amount; and
no rule reads a clause's wording. A law passes when its nation's blocs carry the measure of
its key, as any measure the groups tally (GVR). With ``laws`` off every tally and effect is
as before.

A shipping form whose choices the world marks with escort levels (ESC) sets the level its
choice is marked with; an unmarked form is read by the three 1941 choice words as before.

The worlds are the toy world's (``tests/worlds/territory-toy.yaml``): the votes world of
``tests/test_votes_from_groups.py``, where Norra's assembly is two blocs of a hundred, and
the sea world of ``tests/test_shipping_position.py``, where the Sudland Galleys sink Norra's
shipping on the Gulf Run and the Isle Run each month. The toy world declares its own law,
the Barge Act, which arms Norra's merchant ships.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, NoReturn

import pytest

from revisionist.core import events as ev
from revisionist.core.realism import laws
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.economy import Pools
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers import apply_changes, shipping, votes
from revisionist.core.state import State
from tests.test_adjacency_moves import START, Logged
from tests.test_shipping_position import (
    APRIL,
    GULF,
    GULF_RUN,
    ISLE_RUN,
    MAY,
    OPEN_SEA,
    _enum,
    enact,
    feature,
    lost,
    sea_game,
)
from tests.test_votes_from_groups import NORRA, order
from tests.test_votes_from_groups import game as votes_game

World = dict[str, Any]
Change = Callable[[World], None]

LEVY = "levy_act"
RESERVE = "call up the reserve"
"""The levy act's clause: wording no rule knows."""
AMOUNT = 4
BARGE = "barge_act"
BARGE_CLAUSE = "arm the gulf barges"


# --- the worlds -------------------------------------------------------------------------


def game(tmp: Path, *changes: Change) -> Logged:
    tmp.mkdir(parents=True, exist_ok=True)
    return votes_game(tmp, *changes)


def laws_on(w: World) -> None:
    if "laws" not in w["rules"]:
        w["rules"] = [*w["rules"], "laws"]


def levy_law(does: dict[str, Any] | None = None, subject: str = RESERVE) -> Callable[[World], None]:
    """Norra's levy act as a declared law: its key is the measure's, its flag the one the
    tally writes."""

    def change(w: World) -> None:
        law: World = {
            "key": LEVY,
            "title": "The Levy Act",
            "nation": "norra",
            "clauses": [{"kind": "power", "subject": subject}],
            "passed": f"{LEVY}_passed",
        }
        if does is not None:
            law["does"] = does
        w["laws"] = [*w.get("laws", []), law]

    return change


ADDS = {"kind": "adds_manpower", "amount": AMOUNT}


def carried(yeas: int) -> Change:
    """Both blocs' rows on the levy act at ``yeas`` of a hundred."""

    def change(w: World) -> None:
        nation = next(n for n in w["groups"] if n["nation"] == "norra")
        for bloc in nation["groups"]:
            if bloc.get("chamber") == "assembly":
                bloc["votes"] = {LEVY: {"assembly": {"voting": 100, "yeas": yeas}}}

    return change


def pools(state: State) -> Pools:
    return state.economy.pools.get(NORRA, Pools())


def voted(state: State) -> tuple[int | None, list[ev.EconomySet]]:
    """The levy act's result flag and the economy changes the votes rule makes for it."""
    out = rs.ON_ORDER["votes"](state, order())
    flag = rs.qid(state, f"{LEVY}_passed")
    passed = [c.value for c in out if isinstance(c, QuantityChange) and c.quantity_id == flag]
    return (passed[0] if passed else None), [c for c in out if isinstance(c, ev.EconomySet)]


# --- votes: a law the tables do not know passes by its blocs and does what it says -------


def test_a_law_no_table_knows_passes_by_its_blocs_and_adds_its_own_manpower(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, laws_on, levy_law(ADDS), carried(90))
    assert LEVY not in votes.HISTORICAL
    passed, paid = voted(g.state)
    assert passed == 1
    assert [p.polity for p in paid] == [NORRA]
    assert paid[0].pools.manpower == pools(g.state).manpower + AMOUNT
    assert paid[0].on == START


def test_a_law_that_fails_its_vote_adds_nothing(tmp_path: Path) -> None:
    g = game(tmp_path, laws_on, levy_law(ADDS), carried(10))
    assert voted(g.state) == (0, [])


def test_a_law_s_effect_is_read_from_what_it_does_never_from_its_wording(
    tmp_path: Path,
) -> None:
    worded = game(tmp_path / "w", laws_on, levy_law(None, votes.DRAFT), carried(90))
    assert voted(worded.state) == (1, [])
    arming = game(
        tmp_path / "a", laws_on, levy_law({"kind": "arms_merchant_ships"}, votes.DRAFT), carried(90)
    )
    assert voted(arming.state) == (1, [])
    plain = game(tmp_path / "p", laws_on, levy_law(ADDS, RESERVE), carried(90))
    assert len(voted(plain.state)[1]) == 1


def test_a_law_adds_its_own_amount_not_the_draft_law_s(tmp_path: Path) -> None:
    g = game(tmp_path, laws_on, levy_law({"kind": "adds_manpower", "amount": 7}), carried(90))
    (paid,) = voted(g.state)[1]
    assert paid.pools.manpower == pools(g.state).manpower + 7
    assert votes.DRAFT_MANPOWER != 7


def test_with_laws_off_a_law_the_tables_do_not_know_does_nothing_as_before(
    tmp_path: Path,
) -> None:
    g = game(tmp_path, levy_law(ADDS), carried(90))
    assert not laws.on(g.state)
    assert voted(g.state) == (1, [])


def test_without_the_economy_a_law_adds_no_manpower(tmp_path: Path) -> None:
    def no_economy(w: World) -> None:
        w["rules"] = [r for r in w["rules"] if r != "economy"]

    g = game(tmp_path, laws_on, levy_law(ADDS), carried(90), no_economy)
    assert voted(g.state) == (1, [])


# --- votes.in_force is the world's laws ---------------------------------------------------


def _passed(g: Logged, key: str, value: int = 1, on: date = date(1900, 4, 10)) -> None:
    q = g.state.quantities[rs.qid(g.state, key)]
    g.add([ev.QuantitySet(quantity=q.model_copy(update={"value": value, "as_of": on}))])


def tabled_arming(w: World) -> None:
    """The code table's arming flag, declared by the world and owned by Norra."""
    w["quantities"].append(
        {"key": "arm_merchant_ships_passed", "owner": "norra", "name": "Arming", "unit": "flag"}
        | {"computed": True}
    )


def test_with_laws_on_votes_in_force_reads_the_world_s_laws(tmp_path: Path) -> None:
    g = game(tmp_path, laws_on, levy_law(ADDS), tabled_arming)
    _passed(g, f"{LEVY}_passed")
    _passed(g, "arm_merchant_ships_passed")
    assert votes.in_force(g.state, RESERVE) == {NORRA: date(1900, 4, 10)}
    assert votes.in_force(g.state, votes.ARMING) == {}
    assert votes.in_force(g.state, RESERVE) == laws.in_force(g.state, RESERVE)


def test_with_laws_off_votes_in_force_reads_the_tables_as_before(tmp_path: Path) -> None:
    g = game(tmp_path, levy_law(ADDS), tabled_arming)
    _passed(g, f"{LEVY}_passed")
    _passed(g, "arm_merchant_ships_passed")
    assert votes.in_force(g.state, RESERVE) == {}
    assert votes.in_force(g.state, votes.ARMING) == {NORRA: date(1900, 4, 10)}


# --- no rule with laws on reaches the code tables -----------------------------------------


class Untouchable(dict[str, Any]):
    """A code table no rule may read: any read fails the test."""

    def _read(self, *_: Any, **__: Any) -> NoReturn:
        raise AssertionError("a rule with laws on read a code table")

    __getitem__ = __contains__ = __iter__ = __len__ = get = items = keys = values = _read

    def __bool__(self) -> bool:
        self._read()


@pytest.fixture
def no_tables(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Seals the code tables: from the call on, any read of one fails the test."""

    def seal() -> None:
        monkeypatch.setattr(votes, "HISTORICAL", Untouchable())
        monkeypatch.setattr(votes, "TALLIES", Untouchable())

    return seal


def test_untouchable_refuses_every_read() -> None:
    table = Untouchable()
    for read in (
        lambda: table["x"],
        lambda: "x" in table,
        lambda: list(table),
        lambda: table.get("x"),
        lambda: table.items(),
        lambda: bool(table),
    ):
        with pytest.raises(AssertionError, match="code table"):
            read()


def test_with_laws_on_the_votes_rule_reaches_no_code_table(
    tmp_path: Path, no_tables: Callable[[], None]
) -> None:
    g = game(tmp_path, laws_on, levy_law(ADDS), carried(90), tabled_arming)
    before = voted(g.state)
    no_tables()
    assert voted(g.state) == before
    _passed(g, f"{LEVY}_passed")
    assert votes.in_force(g.state, RESERVE) == {NORRA: date(1900, 4, 10)}
    assert votes.in_force(g.state, votes.ARMING) == {}


def test_with_laws_on_shipping_reaches_no_code_table(
    tmp_path: Path, no_tables: Callable[[], None]
) -> None:
    g = sea_game(tmp_path, laws_on)
    _passed(g, f"{BARGE}_passed")
    before = lost(g, MAY)
    no_tables()
    assert lost(g, MAY) == before


# --- shipping: an arming law found by its declared key -------------------------------------


def bill_for_barges(w: World) -> None:
    """The groups and the laws on, Norra's assembly carrying the Barge Act, and the bill
    form offering it."""
    w["rules"] = [*w["rules"], "groups", "laws"]
    nation = next(n for n in w["groups"] if n["nation"] == "norra")
    for bloc in nation["groups"]:
        if bloc["key"] == "greens":
            bloc["votes"] = {BARGE: {"assembly": {"voting": 50, "yeas": 45}}}
    for card in w["cards"]:
        for lever in card["levers"]:
            if lever["name"] == "send_bill":
                lever["params"] = [_enum("bill", [BARGE])]


def _cut(armed: dict[Any, int], unarmed: dict[Any, int]) -> None:
    assert unarmed and armed.keys() == unarmed.keys()
    for key, n in unarmed.items():
        assert abs(armed[key] - n * (100 - shipping.ARMING_CUT_PCT) / 100) <= 1


def test_an_arming_law_no_table_knows_passes_by_its_blocs_and_cuts_losses(
    tmp_path: Path,
) -> None:
    plain = sea_game(tmp_path / "plain", bill_for_barges)
    g = sea_game(tmp_path / "voted", bill_for_barges)
    bill = enact(g, "ilse", "send_bill", bill=BARGE)
    g.add(apply_changes(g.state, rs.ON_ORDER["votes"](g.state, bill)))
    assert laws.in_force(g.state, BARGE_CLAUSE) == {NORRA: START}
    assert lost(g, APRIL) == lost(plain, APRIL)
    _cut(lost(g, MAY), lost(plain, MAY))


def barge_lock(w: World) -> None:
    """The locks on, and a lock holding Ilse's escort order in the Gulf for Norra's
    assembly while no law carrying the Barge Act's clause is in force for Norra."""
    w["rules"] = sorted({*w["rules"], "locks"})
    w["locks"] = [
        {
            "key": "gulf_escort",
            "order": {"form": "escort", "params": {"zone": GULF}},
            "when": {"check": "law_not_in_force", "clause": BARGE_CLAUSE},
            "decider": {"nation": "norra", "chambers": ["assembly"], "head": "ilse"},
        }
    ]


def test_a_law_no_table_knows_is_held_and_opened_through_the_lock_and_arms(
    tmp_path: Path,
) -> None:
    from revisionist.core.ids import OrderId, derived_id
    from revisionist.core.realism.locks import lock_for
    from revisionist.core.realism.pipeline import Order
    from tests.test_adjacency_moves import seat
    from tests.test_territory_model import CAMPAIGN

    plain = sea_game(tmp_path / "plain", bill_for_barges, barge_lock)
    g = sea_game(tmp_path / "voted", bill_for_barges, barge_lock)
    escort = Order(
        order_id=OrderId(derived_id(CAMPAIGN, "law-escort")),
        issuer=seat("ilse"),
        lever="escort",
        pipeline=next(iter(g.state.pipelines)),
        params={"order": "escort_convoys", "zone": GULF},
        filed=START,
    )
    held = lock_for(g.state, seat("ilse"), escort)
    assert held is not None and held.row is not None and held.row.key == "gulf_escort"
    bill = enact(g, "ilse", "send_bill", bill=BARGE)
    g.add(apply_changes(g.state, rs.ON_ORDER["votes"](g.state, bill)))
    assert lock_for(g.state, seat("ilse"), escort) is None
    _cut(lost(g, MAY), lost(plain, MAY))


def test_with_laws_on_the_tabled_arming_flag_cuts_nothing(tmp_path: Path) -> None:
    plain = sea_game(tmp_path / "plain", laws_on, tabled_arming)
    g = sea_game(tmp_path / "flagged", laws_on, tabled_arming)
    _passed(g, "arm_merchant_ships_passed")
    assert lost(g, MAY) == lost(plain, MAY)


def test_with_laws_on_an_arming_law_cuts_from_the_month_after_its_flag(tmp_path: Path) -> None:
    plain = sea_game(tmp_path / "plain", laws_on)
    g = sea_game(tmp_path / "armed", laws_on)
    _passed(g, f"{BARGE}_passed")
    assert lost(g, APRIL) == lost(plain, APRIL)
    _cut(lost(g, MAY), lost(plain, MAY))


def test_a_passed_law_that_arms_nothing_cuts_nothing(tmp_path: Path) -> None:
    def adds(w: World) -> None:
        w["laws"][0]["does"] = {"kind": "adds_manpower", "amount": 2}

    plain = sea_game(tmp_path / "plain", laws_on, adds)
    g = sea_game(tmp_path / "passed", laws_on, adds)
    _passed(g, f"{BARGE}_passed")
    assert lost(g, MAY) == lost(plain, MAY)


def test_a_law_arming_another_nation_s_ships_leaves_norra_s_losses(tmp_path: Path) -> None:
    def sudland_s(w: World) -> None:
        w["laws"][0]["nation"] = "sudland"

    plain = sea_game(tmp_path / "plain", laws_on, sudland_s)
    g = sea_game(tmp_path / "passed", laws_on, sudland_s)
    _passed(g, f"{BARGE}_passed")
    assert lost(g, MAY) == lost(plain, MAY)


# --- shipping: the escort level marked on the choice ---------------------------------------

MARKED = {"stand_off": 0, "close_escort": 1, "fire_at_will": 2}


def screen(marks: dict[str, int] | None, choices: list[str]) -> Change:
    """A form ``screen`` on both leaders' cards: a stance and the waters, the stance's
    choices marked with ``marks`` (unmarked when None)."""

    def change(w: World) -> None:
        for card in w["cards"]:
            lever: World = {
                "name": "screen",
                "pipeline": "admiralty",
                "resolver": "shipping",
                "params": [_enum("stance", choices), _enum("zone", [GULF, OPEN_SEA])],
            }
            if marks is not None:
                lever["escort_level"] = {"stance": marks}
            card["levers"].append(lever)

    return change


def test_a_marked_form_sets_the_level_its_choice_is_marked_with(tmp_path: Path) -> None:
    for stance, level in MARKED.items():
        g = sea_game(tmp_path / stance, screen(MARKED, list(MARKED)))
        enact(g, "ilse", "screen", stance=stance, zone=GULF)
        assert shipping.escort_level(g.state, feature(g, GULF_RUN), APRIL) == level
        assert shipping.escort_level(g.state, feature(g, ISLE_RUN), APRIL) == level


def test_an_unmarked_form_with_other_words_sets_no_level(tmp_path: Path) -> None:
    g = sea_game(tmp_path, screen(None, list(MARKED)))
    enact(g, "ilse", "screen", stance="fire_at_will", zone=GULF)
    assert shipping.escort_level(g.state, feature(g, GULF_RUN), APRIL) == 0


def test_a_marked_form_reads_its_marks_and_not_the_1941_words(tmp_path: Path) -> None:
    words = sorted(shipping.ESCORT_LEVEL)
    turned = {w: 2 - shipping.ESCORT_LEVEL[w] for w in words}
    for word in words:
        g = sea_game(tmp_path / word, screen(turned, words))
        enact(g, "ilse", "screen", stance=word, zone=GULF)
        assert shipping.escort_level(g.state, feature(g, GULF_RUN), APRIL) == turned[word]


def test_a_marked_form_reads_no_1941_word_from_its_other_choices(tmp_path: Path) -> None:
    def signal(w: World) -> None:
        for card in w["cards"]:
            lever = next(lv for lv in card["levers"] if lv["name"] == "screen")
            lever["params"].append(_enum("that_signal", ["shoot_on_sight"]))

    g = sea_game(tmp_path, screen(MARKED, list(MARKED)), signal)
    enact(g, "ilse", "screen", stance="stand_off", zone=GULF, that_signal="shoot_on_sight")
    assert shipping.escort_level(g.state, feature(g, GULF_RUN), APRIL) == 0


def test_an_unmarked_form_reads_the_1941_words_as_before(tmp_path: Path) -> None:
    words = sorted(shipping.ESCORT_LEVEL)
    for word in words:
        g = sea_game(tmp_path / word, screen(None, words))
        enact(g, "ilse", "screen", stance=word, zone=GULF)
        level = shipping.escort_level(g.state, feature(g, GULF_RUN), APRIL)
        assert level == shipping.ESCORT_LEVEL[word]


def test_a_marked_form_s_level_cuts_losses_as_the_words_do(tmp_path: Path) -> None:
    worded = sea_game(tmp_path / "w", screen(None, sorted(shipping.ESCORT_LEVEL)))
    marked = sea_game(tmp_path / "m", screen(MARKED, list(MARKED)))
    enact(worded, "ilse", "screen", stance="shoot_on_sight", zone=GULF)
    enact(marked, "ilse", "screen", stance="fire_at_will", zone=GULF)
    assert lost(marked, MAY) == lost(worded, MAY)
