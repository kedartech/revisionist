"""1941: the American laws as world data, and the first switches on (LWD).

The four bills the votes rule's code table holds are declared as laws in the world file:
each with its key, title, clauses, the passed quantity the world declares for it, and what
it does. The rows the blocs carry for them stay, under the same keys. The world's rules gain
``laws`` and ``ask_answers``; ``deciders`` went on with the Liaison Conference (NJP). The
fleet commander's second lock (``war_zone_escort``) finds the declared Neutrality revision
by its clause, never in the code table. The three escort choices of the two naval order
forms are marked with the levels the shipping rule gives their words, so the scripted run
is unchanged.

The scripted run's digest is ``run_digest`` (``tests/test_world_locks_1941.py``); the
locked-orders game's is ``locked_orders_script.digest`` on its full 1941 run.
"""

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

import pytest

from revisionist.core.ids import EntityId
from revisionist.core.realism import laws, locks
from revisionist.core.realism.locks import HeldEnd
from revisionist.core.realism.pipeline import OrderStatus
from revisionist.core.realism.resolvers import shipping, votes
from revisionist.core.state import Rule
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world
from revisionist.engine import campaign as cmp
from tests import locked_orders_script as lo
from tests import test_world_locks_1941 as locks_1941
from tests.test_realism_resolvers import Rig
from tests.test_rule_names import BASELINE_1941
from tests.test_world_template import TEMPLATE, wc

SWITCHES = (Rule.LAWS, Rule.ASK_ANSWERS)
"""The third-run switches this item turns on for 1941. ``deciders`` is the Japanese item's,
which gives 1941 its first council."""

BILLS = ("neutrality_revision", "draft_extension", "lend_lease_appropriation", "arm_merchant_ships")
"""The four bills the votes rule's code table holds, as the send-bill form names them."""

LOCKED_ON = "46b155c5d4e202f2d184c7ddf8b5e18d"
"""The locked-orders game's digest on the shipped 1941 world, the switches on. The game's state
carries everything the world declares, Britain's, Germany's, Japan's, Italy's, the Soviet
Union's, China's and Finland's commanders, Finland's President, the Commons' blocs, every bloc's
prices, its law and the Prime Minister's bill form for it, the Liaison Conference, the
commanders' locks, the seats of everyone an ask could go to (the Chief of the Navy General Staff
among them), the classes and weighted places, each card's post with what each office rests on
and who removes or moves its holder, who may accept a peace for each nation with a seat, and
the authority each card's forms give orders under, the roster held by the playable rule, and the
new lands' wars, Mongolia's protocol and forces (WGN; b59e8343c60b947b83b576c1db39aac5 before), so
it is recorded for the world as it stands; both locks land on the same days with the switches on
and off."""

CLAUSE = "war zones closed to American ships"
"""The clause the commander's second lock names."""


def _world() -> WorldFile:
    return cmp.load_world(cmp.world_path("autumn-1941"))


def without_switches(world: WorldFile) -> WorldFile:
    """A copy of ``world`` with the item's switches taken out of its rules, and the lock rows
    that read a law only the world declares: with ``laws`` off no such law is in the game, and
    the compiler refuses a row whose clause it cannot find."""
    tabled = {c.subject for m in votes.HISTORICAL.values() for c in m.clauses}
    rows = tuple(
        r
        for r in world.locks
        if r.when is None or r.when.check != "law_not_in_force" or r.when.clause in tabled
    )
    rules = tuple(r for r in world.rules if r not in SWITCHES)
    return world.model_copy(update={"rules": rules, "locks": rows})


def american(world: WorldFile) -> list[Any]:
    """The laws the world declares for the United States: the four bills of the code table."""
    return [law for law in world.laws if law.nation == "usa"]


def _law(world: WorldFile, key: str) -> Any:
    return next(law for law in world.laws if law.key == key)


def _lever(world: WorldFile, person: str, name: str) -> Any:
    card = next(c for c in world.cards if c.person == person)
    return next(lv for lv in card.levers if lv.name == name)


# --- rule 2: the world's rules gain the switches; it compiles and passes the check -------


def test_the_world_switches_on_laws_and_ask_answers_and_compiles() -> None:
    world = _world()
    assert set(SWITCHES) <= set(world.rules)
    state = Rig().state
    assert set(SWITCHES) <= state.rules
    assert [law.key for law in state.laws] == [law.key for law in world.laws]


def test_the_world_check_requires_nothing_the_world_lacks() -> None:
    lines = wc.check(_world(), wc.parse_template(TEMPLATE.read_text()))
    assert [line.text() for line in lines if line.status == "required"] == []


# --- rule 1: the four bills are laws -----------------------------------------------------


def test_the_four_bills_of_the_code_table_are_declared_as_laws() -> None:
    world = _world()
    assert sorted(law.key for law in american(world)) == sorted(BILLS) == sorted(votes.HISTORICAL)
    for law in american(world):
        measure = votes.HISTORICAL[law.key]
        assert law.title == measure.title
        assert law.clauses == measure.clauses
        assert law.nation == "usa"
        assert law.passed == f"{law.key}_passed"


def test_each_law_says_what_it_does() -> None:
    world = _world()
    does = {
        law.key: None if law.does is None else (law.does.kind, law.does.amount)
        for law in american(world)
    }
    assert does == {
        "neutrality_revision": ("arms_merchant_ships", None),
        "arm_merchant_ships": ("arms_merchant_ships", None),
        "draft_extension": ("adds_manpower", votes.DRAFT_MANPOWER),
        "lend_lease_appropriation": None,
    }


def test_the_laws_that_arm_merchant_ships_are_the_ones_whose_clause_did() -> None:
    world = _world()
    arming = {
        law.key for law in american(world) if law.does and law.does.kind == "arms_merchant_ships"
    }
    assert arming == {
        k for k, m in votes.HISTORICAL.items() if votes.ARMING in {c.subject for c in m.clauses}
    }


def test_each_laws_key_is_the_key_its_blocs_rows_and_the_bill_form_name() -> None:
    world = _world()
    keys = {law.key for law in american(world)}
    (usa,) = [g for g in world.groups if g.nation == "usa"]
    voting = [b for b in usa.groups if b.votes]
    assert voting
    for bloc in voting:
        assert keys <= set(bloc.votes), bloc.key
    (bill,) = [p for p in _lever(world, "roosevelt", "send_bill").params if p.name == "bill"]
    assert set(bill.choices) == keys


def test_each_law_is_sourced_or_a_gap() -> None:
    text = cmp.world_path("autumn-1941").read_text()
    start = text.index("\nlaws:\n")
    block = text[start : text.index("\n\n", start + 1)].splitlines()
    for key in BILLS:
        (line,) = [ln for ln in block if ln.strip().startswith(f"- key: {key} ")]
        note = line.partition("#")[2]
        assert "source:" in note or "gap: true" in note, line


# --- rule 3: the second lock finds the declared revision ---------------------------------


@pytest.fixture
def no_table(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The votes rule's code table emptied, so only the declared laws can be read."""
    monkeypatch.setattr(votes, "HISTORICAL", {})
    yield


def _king(r: Rig) -> Any:
    return locks_1941._order(r, "escort_convoys", "war_zone")


def test_the_second_lock_reads_the_declared_neutrality_revision_by_its_passed_flag() -> None:
    r = locks_1941._rig()
    (flag,) = laws.flags(r.state, CLAUSE)
    (law,) = laws.carrying(r.state, CLAUSE)
    assert law.key == "neutrality_revision" and flag.quantity_id == law.passed


@pytest.mark.usefixtures("no_table")
def test_the_second_lock_holds_and_opens_with_no_code_table() -> None:
    r = locks_1941._rig()
    order = _king(r)
    lock = locks.lock_for(r.state, r.seats["king"], order)
    assert lock is not None and lock.row is not None and lock.row.key == "war_zone_escort"
    r.set_value("arm_merchant_ships_passed", 1, as_of=date(1941, 11, 1))
    assert locks.lock_for(r.state, r.seats["king"], order) is not None
    r.set_value("neutrality_revision_passed", 1, as_of=date(1941, 11, 17))
    assert locks.lock_for(r.state, r.seats["king"], order) is None


@pytest.mark.usefixtures("no_table")
def test_the_world_compiles_with_no_code_table() -> None:
    compile_world(_world(), lo.CAMPAIGN, cmp.versions())


@pytest.mark.usefixtures("no_table")
def test_a_passed_revision_arms_the_merchant_ships_with_no_code_table() -> None:
    r = Rig()
    assert laws.on(r.state)
    assert votes.doing(r.state, laws.Does.ARMS_MERCHANT_SHIPS) == {}
    r.set_value("neutrality_revision_passed", 1, as_of=date(1941, 11, 17))
    usa = EntityId(r.ids["usa"])
    assert votes.doing(r.state, laws.Does.ARMS_MERCHANT_SHIPS) == {usa: date(1941, 11, 17)}


# --- amendment 49: the escort choices are marked with today's levels ---------------------


@pytest.mark.parametrize(
    ("person", "name"), [("roosevelt", "naval_order"), ("king", "fleet_naval_order")]
)
def test_the_naval_orders_escort_choices_are_marked_with_todays_levels(
    person: str, name: str
) -> None:
    lever = _lever(_world(), person, name)
    assert lever.escort_level == {"order": shipping.ESCORT_LEVEL}


def test_the_marked_naval_order_sets_the_level_its_words_set() -> None:
    r = Rig()
    r.seat("roosevelt")
    for word, level in shipping.ESCORT_LEVEL.items():
        order = r.draft(
            "roosevelt",
            "naval_order",
            "naval_order",
            date(1941, 9, 11),
            order=word,
            zone="western_atlantic",
        )
        assert shipping._marks(r.state, order) is not None
        assert shipping.form(r.state, order).escort == level


# --- rule 4: the scripted run and the locked-orders game -------------------------------


def test_the_scripted_run_with_the_switches_out_is_the_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert locks_1941.run_digest(without_switches(_world()), monkeypatch) == BASELINE_1941


def test_the_scripted_run_with_the_switches_on_is_the_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world()
    assert set(SWITCHES) <= set(world.rules)
    assert locks_1941.run_digest(world, monkeypatch) == BASELINE_1941


@pytest.fixture(scope="module")
def games(tmp_path_factory: pytest.TempPathFactory) -> Callable[[bool], lo.Game]:
    kept: dict[bool, lo.Game] = {}

    def game(on: bool) -> lo.Game:
        if on not in kept:
            with pytest.MonkeyPatch.context() as mp:
                tmp = tmp_path_factory.mktemp(f"locked-{on}")
                world = _world() if on else without_switches(_world())
                kept[on] = lo.Game(lo.NINETEEN_41, tmp, mp, world).play()
        return kept[on]

    return game


def _ends(g: lo.Game) -> list[tuple[HeldEnd, date, OrderStatus]]:
    p = g.played
    out = []
    for held in (p.lock1, p.lock2):
        (end,) = lo.ends(g, held)
        out.append((end.end, end.on, g.state.orders[lo.landed_as(g.cast, held)].status))
    return out


def test_the_locked_orders_game_with_the_switches_on_opens_both_locks_as_before(
    games: Callable[[bool], lo.Game],
) -> None:
    on, off = games(True), games(False)
    assert set(SWITCHES) <= on.state.rules
    assert not set(SWITCHES) & off.state.rules
    assert _ends(on) == _ends(off)
    assert [e for e, _, _ in _ends(on)] == [HeldEnd.LANDED, HeldEnd.LANDED]
    assert [s for _, _, s in _ends(on)] == [OrderStatus.ENACTED, OrderStatus.ENACTED]


def test_the_locked_orders_game_with_the_switches_on_is_recorded(
    games: Callable[[bool], lo.Game],
) -> None:
    assert lo.digest(games(True).state) == LOCKED_ON
