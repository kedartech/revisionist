"""The locked-orders game (LKG): a scripted game with a leader and his commander both played.

The script plays a whole season through the engine's own entry points, as two players
would: the commander files the two orders the world locks and asks for each, the leader
gives the naval order that sets the posture and sends the bill that lifts the law, each
seat takes the steps it holds, and the wake closes on its deadline. It files only orders a
seat could file: every act is ``realism_tick.file_order``, ``ask_order`` or ``take_step``,
or ``wake.commit``. No live model is called: the tick runs offline (template prose, no
estimator, no transport for the offers or the aide).

The middle step (the Chief of Naval Operations on the President's naval order) and the
congressional leaders' steps on the bill are code-held decision steps, decided by each
card's policy from the campaign's seed. The script pins them by the seed: the campaign id
(``Cast.campaign``) is fixed, so their actions and days are fixed, and the game records
each action so the tests can say which it was. A seed that turned the middle step to a
refusal would show in the tests, not pass them by.

Ids drawn by ``new_id`` come from a counter per act (``Ids``), so a retried act cannot
shift a later act's id and two runs of one script give one digest.

The same script runs on the toy world (``tests/worlds/territory-toy.yaml``) through a
second cast: Ilse Varg as the leader, Kara Lind as her general and Olaf Brun between them.
"""

import hashlib
import itertools
import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, OrderId, SeatId, derived_id
from revisionist.core.ontology import Phase
from revisionist.core.realism import locks
from revisionist.core.realism.pipeline import Order, OrderStatus, StepAction
from revisionist.core.realism.pipelines import held_by_another, held_paper_id
from revisionist.core.realism.resolvers import qid
from revisionist.core.resolution import TickStage
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import ids as engine_ids
from revisionist.engine import realism_tick, runner, session_zero, wake
from revisionist.engine.store import MemoryStore, load_state
from tests.test_territory_model import variant

World = dict[str, Any]
Form = tuple[str, dict[str, str]]
"""A form a seat files: its lever and every parameter, as the seat gives them."""

T0 = datetime(2030, 1, 1, tzinfo=UTC)
"""The real-world clock the first wake opens on; each wake closes on its deadline."""
WAKES = 60
"""More wakes than any season the script plays takes."""


# --- the casts -----------------------------------------------------------------------


Change = Callable[[World], None]
"""A change to a world's raw file, made before it is compiled."""


@dataclass(frozen=True)
class Cast:
    """What the script needs from a world: who plays, the forms each files, and the
    figures the law's vote writes. Keys are world keys."""

    name: str
    world: Callable[[Path, tuple[Change, ...]], WorldFile]
    """The world with the given changes made to its raw file."""
    campaign: CampaignId
    leader: str
    commander: str
    middle: str
    """The code-held person whose step comes before the commander's on the leader's order."""
    lock1: Form
    """The commander's order the first lock holds until the leader sets the posture."""
    lock1_row: str
    lock2: Form
    """The commander's order the second lock holds until the law is in force."""
    lock2_row: str
    posture: Form
    """The leader's order that sets the posture: it crosses the middle step, then the
    commander's own desk."""
    bill: Form
    """The leader's bill that, passed, takes the law that holds ``lock2`` out of force."""
    passed: str
    """The flag the bill's vote sets."""
    votes: tuple[str, ...]
    """The yeas and nays the bill's vote writes, by quantity key."""
    leader_move: Form
    """The leader's order moving the commander's force, through the commander's desk."""
    commander_move: Form
    """The commander's own order moving the same force elsewhere."""
    force: str
    leader_bound: str
    """Where the leader's move sends the force: its destination, or for a fleet sent to a
    port, the water the port is on."""
    hidden: Change
    """A change to a fact the commander cannot see, for the twin-world tests."""
    meets: bool
    """Whether the two moves, filed in one wake, first act on the force in one wake, so
    the commander's is settled as replaced. Not in 1941: the President's move waits at
    King's desk until its held due day (arrival, the step's two days, then
    ``process.ANSWER_DAYS``), while King's own move passes his staff in a day, so King's
    acts first and the President's acts after it and stands. In the toy world both go
    through the general's staff, a clerical step, and act on the same day."""

    def entity(self, key: str) -> EntityId:
        return EntityId(object_id(self.campaign, "entity", key))

    def seat(self, key: str) -> SeatId:
        return SeatId(derived_id(self.campaign, "seat", self.entity(key)))


CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")


def autumn_1941(tmp: Path, changes: tuple[Change, ...] = ()) -> WorldFile:
    """The 1941 world as shipped, with ``changes`` made to its raw file; its map and its
    deck are the shipped ones."""
    del tmp
    shipped = cmp.load_world(cmp.world_path("autumn-1941"))
    if not changes:
        return shipped
    raw: World = yaml.safe_load(cmp.world_path("autumn-1941").read_text())
    for change in changes:
        change(raw)
    carried = {"map_data": shipped.map_data, "developments": shipped.developments}
    return WorldFile.model_validate(raw).model_copy(update=carried)


def _halved(key: str) -> Change:
    def change(w: World) -> None:
        q = next(q for q in w["quantities"] if q["key"] == key)
        q["value"] = q["value"] // 2

    return change


NEUTRALITY_VOTES = tuple(
    f"neutrality_revision_{vote}_{side}"
    for vote in ("house", "senate", "concur")
    for side in ("yeas", "nays")
)

FLEET = "us_atlantic_fleet"
NINETEEN_41 = Cast(
    name="autumn-1941",
    world=autumn_1941,
    campaign=CAMPAIGN,
    leader="roosevelt",
    commander="king",
    middle="stark",
    lock1=("fleet_naval_order", {"order": "shoot_on_sight", "zone": "iceland_route"}),
    lock1_row="iceland_shoot_on_sight",
    lock2=("fleet_naval_order", {"order": "escort_convoys", "zone": "war_zone"}),
    lock2_row="war_zone_escort",
    posture=("naval_order", {"order": "shoot_on_sight", "zone": "iceland_route"}),
    bill=("send_bill", {"bill": "neutrality_revision", "urgency": "urgent"}),
    passed="neutrality_revision_passed",
    votes=NEUTRALITY_VOTES,
    leader_move=("move_fleet", {"force": FLEET, "to": "norfolk"}),
    commander_move=("move_fleet", {"force": FLEET, "to": "reykjavik"}),
    force=FLEET,
    leader_bound="western_atlantic",  # Norfolk's port_on
    hidden=_halved("japan_sealift_grt"),
    meets=False,
    # Japan's shipping free for troop lift: Japan's own figure, out of King's view.
)


# --- the toy cast --------------------------------------------------------------------
# The toy world (tests/worlds/territory-toy.yaml) gains the same shape as 1941, every name
# invented: Ilse Varg leads Norra; Kara Lind, a military card, commands the Norra Levy
# under Olaf Brun, Norra's marshal, who is under Ilse. Ilse's watch order crosses Olaf's
# step, then Kara's desk. Kara's watch order, her march and Ilse's own move of the levy go
# through the levy's staff, a clerical step. Ilse's bill goes before Norra's assembly,
# where the Greens vote. Kara's watch on the Gulf is held until Ilse sets it herself; her
# escort on the open sea is held until a law arming merchant ships is in force for Norra.

TOY_LAW_FLAG = "arm_merchant_ships_passed"
TOY_VOTES = ("arm_merchant_ships_assembly_yeas", "arm_merchant_ships_assembly_nays")
DECIDES = ["pass", "expedite", "stall", "amend", "refuse"]


def _enum(name: str, *choices: str) -> World:
    return {"name": name, "kind": "enum", "choices": list(choices)}


def _toy_slice(w: World) -> None:
    w["rules"] = [
        "territories", "holders", "agreements", "groups", "contests", "aims", "command", "locks"
    ]  # fmt: skip
    w["entities"] += [
        {"key": "olaf", "kind": "person", "name": "Olaf Brun", "parent": "norra"},
        {"key": "kara", "kind": "person", "name": "Kara Lind", "parent": "norra"},
    ]
    w["pipelines"] = [
        {"key": "watch_order", "name": "A watch order", "source": "toy", "steps": [
            {"person": "olaf", "kind": "decision", "days": 2, "allowed": DECIDES},
            {"person": "kara", "kind": "decision", "days": 2,
             "allowed": ["pass", "expedite", "stall", "refuse"]},
        ]},
        {"key": "levy_staff", "name": "Through the levy's staff", "source": "toy", "steps": [
            {"person": "kara", "kind": "clerical", "days": 1},
        ]},
        {"key": "assembly_bill", "name": "A bill through the assembly", "source": "toy", "steps": [
            {"person": "olaf", "kind": "decision", "days": 3, "allowed": DECIDES},
            {"person": "ilse", "kind": "decision", "days": 2, "allowed": ["pass", "refuse"]},
        ]},
    ]  # fmt: skip
    watch = [_enum("order", "guard", "escort", "stand_down"), _enum("zone", "gulf", "open")]
    move = [_enum("force", "norra_levy"), _enum("to", "norra_hills", "sudland_coast")]
    ilse = w["cards"][0]
    ilse.update(
        pipelines=["watch_order", "levy_staff", "assembly_bill"],
        levers=[
            {"name": "set_watch", "pipeline": "watch_order", "resolver": "shipping",
             "params": watch},
            {"name": "move_levy", "pipeline": "levy_staff", "resolver": "movement",
             "params": move},
            {"name": "send_bill", "pipeline": "assembly_bill", "resolver": "votes",
             "params": [_enum("bill", "arm_merchant_ships"),
                        _enum("urgency", "ordinary", "urgent")]},
        ],
        authority=[{"name": "the_forces", "effects": ["move_force", "engagement"],
                    "forces": ["norra_levy", "norra_kites"]}],
        inner_circle=[{"person": "olaf", "channel": "letter"},
                      {"person": "kara", "channel": "letter"}],
    )  # fmt: skip
    w["cards"] += [
        {"person": "olaf", "office": "Marshal of Norra", "principals": ["ilse"],
         "horizon_days": 14, "loyalty": 0},
        {"person": "kara", "office": "General of the Norra Levy", "playable": True,
         "path": "military", "principals": ["olaf"], "horizon_days": 7,
         "inner_circle": [{"person": "olaf", "channel": "letter"},
                          {"person": "ilse", "channel": "letter"}],
         "pipelines": ["watch_order", "levy_staff"],
         "levers": [
             {"name": "levy_watch", "pipeline": "levy_staff", "resolver": "shipping",
              "params": watch},
             {"name": "march", "pipeline": "levy_staff", "resolver": "movement",
              "params": move},
         ],
         "authority": [{"name": "the_levy", "effects": ["move_force", "engagement"],
                        "forces": ["norra_levy"]}]},
    ]  # fmt: skip
    w["roster"].append(
        {"entity": "kara", "pitch": "The general.", "reach": "The Norra Levy.", "composite": True}
    )
    w["quantities"] += [
        {"key": TOY_LAW_FLAG, "owner": "norra", "name": "Arming law passed", "unit": "flag",
         "computed": True, "public": True},
        *({"key": k, "owner": "norra", "name": k, "unit": "votes", "computed": True,
           "public": True} for k in TOY_VOTES),
        {"key": "sudland_reserve", "owner": "sudland", "name": "Sudland's reserve",
         "value": 400, "unit": "men", "source": "toy"},
    ]  # fmt: skip
    w["locks"] = [
        {"key": "gulf_watch",
         "order": {"form": "levy_watch", "params": {"order": "guard", "zone": "gulf"}},
         "when": {"check": "posture_not_set", "form": "set_watch", "where": {"zone": "gulf"},
                  "posture": {"order": "guard"}},
         "decider": {"person": "ilse"}},
        {"key": "open_sea_escort",
         "order": {"form": "levy_watch", "params": {"order": "escort", "zone": "open"}},
         "when": {"check": "law_not_in_force", "clause": "arm merchant ships"},
         "decider": {"nation": "norra", "chambers": ["assembly"], "head": "ilse"}},
    ]  # fmt: skip
    w["contests"] = [
        {"key": "border", "kind": "rivalry", "name": "The Border War", "prize": "The hills",
         "sides": ["norra", "sudland"], "countdown_days": 60},
    ]  # fmt: skip
    w["assets"] = [
        {"key": "chancellery", "kind": "office", "name": "Chancellery", "tier": 3,
         "controller": "ilse"},
        {"key": "premiership", "kind": "office", "name": "Premiership", "tier": 3,
         "controller": "tomas"},
        {"key": "levy_command", "kind": "office", "name": "Levy Command", "tier": 3,
         "controller": "kara"},
    ]  # fmt: skip
    hills = {"check": "holds_area", "area": "norra_hills", "holder": "norra"}
    plain = {"check": "holds_area", "area": "norra_plain", "holder": "norra"}
    law = {"check": "quantity_at", "quantity": TOY_LAW_FLAG, "op": "ge", "value": 1}
    ilse["aims"] = ["Keep the hills.", "Keep the plain.", "Arm the merchant ships."]
    ilse["aim_rules"] = [
        {"aim": 1, "rule": "Norra holds the hills.", "condition": hills},
        {"aim": 2, "rule": "Norra holds the plain.", "condition": plain},
        {"aim": 3, "rule": "The arming law passes.", "condition": law, "replaceable": True},
    ]
    kara = w["cards"][-1]
    kara["aims"] = ["Hold the hills.", "Win leave to escort on the open sea."]
    kara["aim_rules"] = [
        {"aim": 1, "rule": "Norra holds the hills.", "condition": hills},
        {"aim": 2, "rule": "The arming law passes.", "condition": law, "replaceable": True},
    ]


def toy(tmp: Path, changes: tuple[Change, ...] = ()) -> WorldFile:
    """The toy world with the slice's shape (``_toy_slice``), then ``changes``."""

    def change(w: World) -> None:
        for c in (_toy_slice, *changes):
            c(w)

    tmp.mkdir(parents=True, exist_ok=True)
    return variant(tmp, change)


TOY = Cast(
    name="territory-toy",
    world=toy,
    campaign=CAMPAIGN,
    leader="ilse",
    commander="kara",
    middle="olaf",
    lock1=("levy_watch", {"order": "guard", "zone": "gulf"}),
    lock1_row="gulf_watch",
    lock2=("levy_watch", {"order": "escort", "zone": "open"}),
    lock2_row="open_sea_escort",
    posture=("set_watch", {"order": "guard", "zone": "gulf"}),
    bill=("send_bill", {"bill": "arm_merchant_ships", "urgency": "urgent"}),
    passed=TOY_LAW_FLAG,
    votes=TOY_VOTES,
    leader_move=("move_levy", {"force": "norra_levy", "to": "norra_hills"}),
    commander_move=("march", {"force": "norra_levy", "to": "sudland_coast"}),
    force="norra_levy",
    leader_bound="norra_hills",
    hidden=_halved("sudland_reserve"),
    meets=True,
    # Sudland's reserve: Sudland's own figure, out of Kara's view.
)
CASTS = (NINETEEN_41, TOY)


# --- the ids -------------------------------------------------------------------------


class Ids:
    """``new_id`` drawn from a counter per stream: the engine's own, and one per scripted
    act. An id is a pure function of the stream and its count, never of the clock, of how
    acts interleave, or of a retried act before it."""

    def __init__(self, campaign: CampaignId) -> None:
        self.campaign = campaign
        self.stream = "engine"
        self.counts: dict[str, Iterator[int]] = {}

    def __call__(self) -> str:
        count = self.counts.setdefault(self.stream, itertools.count())
        return derived_id(self.campaign, "lkg-id", self.stream, next(count))

    @contextmanager
    def drawn_by(self, stream: str) -> Iterator[None]:
        before, self.stream = self.stream, stream
        try:
            yield
        finally:
            self.stream = before

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = engine_ids.new_id
        for name, module in list(sys.modules.items()):
            found = getattr(module, "new_id", None)
            if name.startswith("revisionist") and (found is real or isinstance(found, Ids)):
                monkeypatch.setattr(module, "new_id", self)


# --- the script ----------------------------------------------------------------------


@dataclass(frozen=True)
class Script:
    """Which moves the script makes. The full script is the default."""

    posture: bool = True
    """The leader gives the naval order that sets the posture (lock 1)."""
    bill: bool = True
    """The leader sends the bill (lock 2)."""
    commander_present: bool = True
    """The commander commits each wake and takes his step on the leader's order; absent,
    the aide plays his seat and his step falls to the rules."""
    restart_at: int | None = None
    """The wake whose close stops after the pipelines and resumes from a fresh store."""
    retry_at: int | None = None
    """The wake in which each seat repeats what it already did: the same filings, the same
    asks, the same step."""
    both_move: bool = False
    """In the first wake the leader and the commander each move the commander's force,
    to different places. The run stops once both have settled."""
    stop: Callable[[State], bool] | None = None
    """Stop after the first close at which this holds; None plays to the season's end."""


FULL = Script()
NONE_YET = OrderId("")
"""A locked order's id before the script files it."""


@dataclass
class Played:
    """What the script did, and when, for the tests to read."""

    lock1: OrderId = NONE_YET
    lock2: OrderId = NONE_YET
    posture: OrderId | None = None
    bill: OrderId | None = None
    leader_move: OrderId | None = None
    commander_move: OrderId | None = None
    asked: dict[OrderId, locks.Asked] = field(default_factory=dict)
    desk_taken: date | None = None
    """The day the commander chose his step on the leader's order; None if he never did."""
    signed: date | None = None
    """The day the leader took his own last step on the bill."""
    refused_retries: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    """What the engine said each time the commander tried to refuse the leader's order;
    empty words where it took the refusal."""
    wakes: int = 0


class Game:
    """One game in a memory store, played by the script through the engine."""

    def __init__(
        self,
        cast: Cast,
        tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
        world: WorldFile | None = None,
    ) -> None:
        self.cast = cast
        self.tmp = tmp
        self.ids = Ids(cast.campaign)
        self.ids.install(monkeypatch)
        self.store = MemoryStore()
        decl = world if world is not None else cast.world(tmp / "world", ())
        self.store.append_all(compile_world(decl, cast.campaign, cmp.versions()))
        self.now = T0
        names = load_state(self.store, cast.campaign).entities
        for key in (cast.leader, cast.commander):
            with self.ids.drawn_by(f"claim:{key}"):
                session_zero.claim(
                    self.store, cast.campaign, cast.seat(key), names[cast.entity(key)].name
                )
        with self.ids.drawn_by("open"):
            realism_tick.open_play(self.store, cast.campaign)
        self.played = Played()
        self.leader = cast.seat(cast.leader)
        self.commander = cast.seat(cast.commander)

    # -- reading

    @property
    def state(self) -> State:
        return load_state(self.store, self.cast.campaign)

    def logged(self, kind: type[Any]) -> list[Any]:
        return [
            e.payload for e in self.store.read(self.cast.campaign) if isinstance(e.payload, kind)
        ]

    def events(self) -> list[ev.Event]:
        return list(self.store.read(self.cast.campaign))

    def quantity(self, key: str) -> int | None:
        state = self.state
        q = state.quantities.get(qid(state, key))
        return None if q is None else q.value

    # -- acts, each through an engine entry point and drawn from its own id stream

    def file(self, who: SeatId, form: Form, act: str) -> Order:
        with self.ids.drawn_by(act):
            return realism_tick.file_order(self.store, self.cast.campaign, who, form[0], form[1])

    def ask(self, order_id: OrderId, act: str) -> locks.Asked:
        with self.ids.drawn_by(act):
            return realism_tick.ask_order(self.store, self.cast.campaign, self.commander, order_id)

    def step(self, who: SeatId, order_id: OrderId, act: str) -> None:
        """``who`` passes the step it holds on ``order_id``: on another seat's order by the
        paper that brought it, on its own order by its id."""
        state = self.state
        order = state.orders[order_id]
        ref = (
            held_paper_id(state.campaign_id, order_id, order.step)
            if order.issuer != who
            else order_id
        )
        with self.ids.drawn_by(act):
            realism_tick.take_step(self.store, self.cast.campaign, who, ref, StepAction.PASS, {})

    def close(self, restart: bool = False) -> None:
        """The present seats commit and the wake closes on its deadline; the aide plays
        any seat that did not commit. With ``restart``, the close stops after the
        pipelines, the store is rebuilt from its log, and the tick resumes."""
        state = self.state
        if state.wake is not None and not state.wake.closed:
            self.now = state.wake.deadline
            present = [self.leader] + ([self.commander] if self.script.commander_present else [])
            for who in present:
                with self.ids.drawn_by(f"commit:{who}"):
                    wake.commit(self.store, self.cast.campaign, who, self.now)
        if restart:
            self._tick(TickStage.PIPELINES)
            fresh = MemoryStore()
            fresh.append_all(self.events())
            self.store = fresh
        self._tick(None)
        self.played.wakes += 1

    def _tick(self, stop_after: TickStage | None) -> None:
        runner.play_tick(
            self.store,
            self.cast.campaign,
            offline=True,
            transport_factory=cmp.live_transport,
            briefings=self.tmp / "briefings",
            warn=lambda _m: None,
            stop_after=stop_after,
            now=self.now,
        )

    # -- the script

    script: Script = FULL

    def play(self, script: Script = FULL) -> "Game":
        """Play ``script`` from the first wake to the season's end (or ``script.stop``)."""
        self.script = script
        cast, p = self.cast, self.played
        self._tick(None)  # the first tick opens wake 0
        held1 = self.file(self.commander, cast.lock1, "commander:lock1")
        held2 = self.file(self.commander, cast.lock2, "commander:lock2")
        p.lock1, p.lock2 = held1.order_id, held2.order_id
        for order_id in (p.lock1, p.lock2):
            p.asked[order_id] = self.ask(order_id, f"commander:ask:{order_id}")
        if script.posture:
            p.posture = self.file(self.leader, cast.posture, "leader:posture").order_id
        if script.bill:
            p.bill = self.file(self.leader, cast.bill, "leader:bill").order_id
        if script.both_move:
            p.leader_move = self.file(self.leader, cast.leader_move, "leader:move").order_id
            p.commander_move = self.file(
                self.commander, cast.commander_move, "commander:move"
            ).order_id
        for n in range(WAKES):
            if self.state.phase is not Phase.PLAY:
                return self
            self._steps(n)
            if script.retry_at == n:
                self._retry()
            self.close(restart=script.restart_at == n)
            if script.stop is not None and script.stop(self.state):
                return self
            if script.both_move and self._moves_settled():
                return self
        raise AssertionError("the season never ended")

    def _steps(self, n: int) -> None:
        """The steps the seats hold this wake: the commander's on the leader's order, the
        leader's own on his bill."""
        state, p = self.state, self.played
        for order_id in (p.posture, p.leader_move):
            order = state.orders.get(order_id) if order_id is not None else None
            if (
                order is not None
                and self.script.commander_present
                and held_by_another(state, order) == self.commander
                and order.held_choice is None
            ):
                self._try_refusing(order.order_id)
                self.step(self.commander, order.order_id, f"commander:desk:{order_id}")
                if order_id == p.posture:
                    p.desk_taken = state.in_world_date
        bill = state.orders.get(p.bill) if p.bill is not None else None
        if bill is not None and bill.status is OrderStatus.MOVING:
            person = state.pipelines[bill.pipeline].steps[bill.step].person
            if person == self.cast.entity(self.cast.leader):
                self.step(self.leader, bill.order_id, "leader:sign")
                p.signed = state.in_world_date

    def _try_refusing(self, order_id: OrderId) -> None:
        """The commander first tries to refuse the leader's order at his desk, as a seat
        could; the refusal the engine gives is kept."""
        state = self.state
        paper = held_paper_id(state.campaign_id, order_id, state.orders[order_id].step)
        try:
            with self.ids.drawn_by(f"commander:refuse:{order_id}"):
                realism_tick.take_step(
                    self.store, self.cast.campaign, self.commander, paper, StepAction.REFUSE, {}
                )
        except ValueError as exc:
            self.played.refusals.append(str(exc))
        else:
            self.played.refusals.append("")

    def _moves_settled(self) -> bool:
        state, p = self.state, self.played
        moves = [state.orders.get(o) for o in (p.leader_move, p.commander_move) if o is not None]
        return len(moves) == 2 and all(
            o is not None and o.status is not OrderStatus.MOVING for o in moves
        )

    def _retry(self) -> None:
        """Each seat repeats itself: the commander re-files both locked orders and asks for
        them again, and takes his step on the leader's order again if it still waits."""
        cast, p = self.cast, self.played
        for form, held in ((cast.lock1, p.lock1), (cast.lock2, p.lock2)):
            if held is not None and held in self.state.held:
                again = self.file(self.commander, form, f"retry:file:{held}")
                assert again.order_id == held
                try:
                    self.ask(held, f"retry:ask:{held}")
                except ValueError as exc:
                    p.refused_retries.append(str(exc))
        order = self.state.orders.get(p.posture) if p.posture is not None else None
        if order is not None and order.held_choice is not None:
            self.step(self.commander, order.order_id, "retry:desk")


# --- what the tests read --------------------------------------------------------------

DIGEST_LEAVES_OUT = ("last_seq",)
"""State fields the digest leaves out: how many records the game logged on the way."""


def digest(state: State) -> str:
    """blake2b-128 over the state's canonical JSON, less the record count: everything the
    world holds, and each seat's papers, held orders, asks and commits."""
    dumped = state.model_dump(mode="json")
    for name in DIGEST_LEAVES_OUT:
        dumped.pop(name)
    canon = json.dumps(dumped, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.blake2b(canon.encode(), digest_size=16).hexdigest()


def landed_as(cast: Cast, order_id: OrderId) -> OrderId:
    """The id a held order lands under once its lock opens."""
    return OrderId(derived_id(cast.campaign, "landed", order_id))


def known(order_id: OrderId | None) -> OrderId:
    """The id of an order the script filed."""
    assert order_id is not None, "the script did not file that order"
    return order_id


def ends(g: Game, order_id: OrderId | None) -> list[ev.HeldOrderEnded]:
    return [e for e in g.logged(ev.HeldOrderEnded) if e.order_id == order_id]


def steps_at(g: Game, order_id: OrderId | None, person: str) -> list[Any]:
    """Every step taken on ``order_id`` by ``person``, in log order."""
    who = g.cast.entity(person)
    return [
        e.outcome
        for e in g.logged(ev.OrderStepTaken)
        if e.order_id == order_id and e.outcome.person == who
    ]


__all__ = [
    "CAMPAIGN",
    "CASTS",
    "NINETEEN_41",
    "T0",
    "TOY",
    "Cast",
    "Form",
    "Game",
    "Ids",
    "Played",
    "Script",
    "autumn_1941",
    "digest",
    "ends",
    "known",
    "landed_as",
    "steps_at",
    "toy",
]
