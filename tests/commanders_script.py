"""The commanders' games (NPG): a scripted 1941 game for each nation with a military seat.

Each game opens the way a player opens one: from the opening's three answers (the nation,
the military path, the commander by name, as ``new_game_api.opening`` lists them), then
claims the commander, and, where the script plays him, the person his held order is put
to. The commander files the order his nation's lock holds and asks for it; the lock then
opens the way that nation decides: the head of state sets the posture the row waits on
(the United States, Britain, Germany), a single person grants the matter (Italy, the
Soviet Union, China, Finland), or the Imperial Conference grants it by every member
agreeing (Japan). Britain has a second game for its Commons row: the Prime Minister puts
the National Service bill to the House, and the order lands once the blocs pass it.

The script files only orders a seat could file: every act is ``realism_tick.file_order``,
``ask_order``, ``take_step``, ``choose_matter`` or ``set_own_aim``, or ``wake.commit``.
No live model is called: the tick runs offline. A person no seat holds is decided by his
card from the campaign's seed, so a game is pinned by its campaign id; ids drawn by
``new_id`` come from a counter per act (``Ids``), so two runs of one script give one
digest and a retried act shifts no later id.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.ids import CampaignId, EntityId, OrderId, SeatId, derived_id
from revisionist.core.ontology import Phase
from revisionist.core.realism import locks
from revisionist.core.realism.pipeline import OrderStatus, StepAction
from revisionist.core.realism.pipelines import held_by_another, held_paper_id
from revisionist.core.resolution import TickStage
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import realism_tick, runner, session_zero, wake
from revisionist.engine.store import MemoryStore, load_state
from revisionist.engine.web import new_game_api
from tests.locked_orders_script import CAMPAIGN, T0, Form, Ids, World, shipped

WAKES = 40
"""More wakes than any game here takes to open its lock or end its season."""


@dataclass(frozen=True)
class Nation:
    """One nation's commander, the order its lock holds, and how the lock opens."""

    key: str
    commander: str
    head: str
    """The person the commander's ask goes to: the decider, or the council's head."""
    order: Form
    row: str
    allow: tuple[Form, ...] = ()
    """The head's own orders, each filed once the one before is enacted, the last setting
    the posture the row waits on; empty where a grant opens the lock."""
    council: tuple[str, ...] = ()
    """The council's members, where a council decides."""

    @property
    def seated_head(self) -> str:
        """The person the script seats beside the commander when it plays the decider: the
        head, or for a council one member besides the head, who stays silent."""
        return self.council[1] if self.council else self.head


NATIONS = (
    Nation(
        key="usa",
        commander="king",
        head="roosevelt",
        order=("fleet_naval_order", {"order": "shoot_on_sight", "zone": "iceland_route"}),
        row="iceland_shoot_on_sight",
        allow=(("naval_order", {"order": "shoot_on_sight", "zone": "iceland_route"}),),
    ),
    Nation(
        key="uk",
        commander="tovey",
        head="churchill",
        order=("home_fleet_detach", {"force": "home_fleet", "to": "liverpool", "strength": "1"}),
        row="home_fleet_to_the_atlantic",
        allow=(("convoy_orders", {"priority": "atlantic", "route": "hx_route"}),),
    ),
    Nation(
        key="uk_commons",
        commander="tovey",
        head="churchill",
        order=("home_fleet_move", {"force": "home_fleet", "to": "reykjavik"}),
        row="home_fleet_based_at_iceland",
        allow=(("send_bill", {"bill": "national_service", "urgency": "ordinary"}),),
    ),
    Nation(
        key="germany",
        commander="doenitz",
        head="hitler",
        order=("uboat_move", {"force": "uboat_arm", "to": "argentia"}),
        row="uboats_against_american_ships",
        allow=(
            ("declare_war", {"target": "usa"}),
            ("uboat_directive", {"posture": "attack_us_shipping", "theatre": "north_atlantic"}),
        ),
    ),
    Nation(
        key="japan",
        commander="yamamoto",
        head="konoe",
        order=("combined_fleet_move", {"force": "combined_fleet", "to": "pearl_harbor_base"}),
        row="pearl_harbor_strike",
        council=("konoe", "tojo", "sugiyama", "nagano"),
    ),
    Nation(
        key="italy",
        commander="iachino",
        head="mussolini",
        order=("battle_fleet_move", {"force": "italian_fleet", "to": "bardia"}),
        row="battle_fleet_sortie_east",
    ),
    Nation(
        key="ussr",
        commander="timoshenko",
        head="stalin",
        order=("western_front_move", {"force": "soviet_western_front", "to": "moscow"}),
        row="western_front_withdrawal",
    ),
    Nation(
        key="china",
        commander="xue_yue",
        head="chiang",
        order=("ninth_war_area_move", {"force": "ninth_war_area", "to": "chungking"}),
        row="changsha_given_up",
    ),
    Nation(
        key="finland",
        commander="mannerheim",
        head="ryti",
        order=("finnish_army_move", {"force": "finnish_army", "to": "leningrad"}),
        row="finnish_army_beyond_the_border",
    ),
)
BY_KEY = {n.key: n for n in NATIONS}


def world_1941(changes: tuple[Callable[[World], None], ...] = ()) -> WorldFile:
    return shipped("autumn-1941", changes)


# --- the script ----------------------------------------------------------------------


@dataclass(frozen=True)
class Script:
    """Which moves the script makes. The default plays the head and lets him allow it."""

    head_played: bool = True
    """The decider (or, for a council, one member) is seated; otherwise his card answers."""
    allows: bool = True
    """A played head allows the order: sets the posture, or grants the matter. A seated
    council member stays silent either way."""
    commander_present: bool = True
    """The commander commits each wake; absent, the aide plays his seat once he has asked."""
    own_aim: Form | None = None
    """The commander sets this own aim from a pattern in the first wake."""
    to_season_end: bool = False
    """Play on after the lock ends until the season ends."""
    restart_at: int | None = None
    """The wake whose close stops after the pipelines and resumes from a fresh store."""
    retry_at: int | None = None
    """The wake in which each seat repeats what it already did."""


PLAY = Script()


NO_ORDER = OrderId("")
"""What ``Played.held`` reads before the commander files."""


@dataclass
class Played:
    """What the script did, for the tests to read."""

    held: OrderId = NO_ORDER
    asked: locks.Asked | None = None
    allowed: list[OrderId] = field(default_factory=list)
    """The head's own orders, in the order filed."""
    chose: date | None = None
    """The day the played decider chose on the matter; None if he never did."""
    refused_retries: list[str] = field(default_factory=list)
    wakes: int = 0


class Game:
    """One nation's game in a memory store, played by the script through the engine."""

    def __init__(
        self,
        nation: Nation,
        tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        campaign: CampaignId = CAMPAIGN,
        head_played: bool = True,
        world: WorldFile | None = None,
    ) -> None:
        self.nation = nation
        self.campaign = campaign
        self.tmp = tmp
        self.ids = Ids(campaign)
        self.ids.install(monkeypatch)
        self.store = MemoryStore()
        decl = world if world is not None else world_1941()
        self.store.append_all(compile_world(decl, campaign, cmp.versions()))
        self.now = T0
        self.picked = self.pick(nation.commander)
        if head_played:
            self.pick(nation.seated_head)
        with self.ids.drawn_by("open"):
            realism_tick.open_play(self.store, campaign)
        self.commander = self.seat(nation.commander)
        self.head = self.seat(nation.seated_head) if head_played else None
        self.played = Played()
        self.script = PLAY

    # -- the opening

    def pick(self, person: str) -> tuple[str | None, str | None, str]:
        """Claim ``person`` through the opening's three answers: his nation, his path and
        his name, each as the opening lists it. Returns the three answers."""
        state = self.state
        card = state.cards[self.entity(person)]
        name = state.entities[card.person].name
        found = [
            (n["key"], p["path"], q["name"])
            for n in new_game_api.opening(state)["nations"]
            for p in n["paths"]
            for q in p["persons"]
            if q["name"] == name and not q["taken"]
        ]
        assert len(found) == 1, f"the opening lists {name} once, untaken"
        with self.ids.drawn_by(f"claim:{person}"):
            session_zero.claim(self.store, self.campaign, self.seat(person), name)
        return found[0]

    # -- reading

    def entity(self, key: str) -> EntityId:
        return EntityId(object_id(self.campaign, "entity", key))

    def seat(self, key: str) -> SeatId:
        return SeatId(derived_id(self.campaign, "seat", self.entity(key)))

    @property
    def state(self) -> State:
        return load_state(self.store, self.campaign)

    def logged[P](self, kind: type[P]) -> list[P]:
        return [e.payload for e in self.store.read(self.campaign) if isinstance(e.payload, kind)]

    def events(self) -> list[ev.Event]:
        return list(self.store.read(self.campaign))

    def ends(self) -> list[ev.HeldOrderEnded]:
        return [e for e in self.logged(ev.HeldOrderEnded) if e.order_id == self.played.held]

    def landed(self) -> OrderId:
        return OrderId(derived_id(self.campaign, "landed", self.played.held))

    # -- acts, each through an engine entry point and drawn from its own id stream

    def file(self, who: SeatId, form: Form, act: str) -> OrderId:
        with self.ids.drawn_by(act):
            order = realism_tick.file_order(self.store, self.campaign, who, form[0], form[1])
        return order.order_id

    def ask(self, act: str) -> locks.Asked:
        with self.ids.drawn_by(act):
            return realism_tick.ask_order(
                self.store, self.campaign, self.commander, self.played.held
            )

    def step(self, who: SeatId, order_id: OrderId, act: str) -> None:
        state = self.state
        order = state.orders[order_id]
        ref = (
            held_paper_id(state.campaign_id, order_id, order.step)
            if order.issuer != who
            else order_id
        )
        with self.ids.drawn_by(act):
            realism_tick.take_step(self.store, self.campaign, who, ref, StepAction.PASS, {})

    def choose(self, act: str) -> None:
        assert self.head is not None
        with self.ids.drawn_by(act):
            realism_tick.choose_matter(
                self.store, self.campaign, self.head, self.played.held, self.script.allows
            )

    def close(self, restart: bool = False) -> None:
        """The present seats commit and the wake closes on its deadline; the aide plays any
        seat that did not commit. With ``restart``, the close stops after the pipelines,
        the store is rebuilt from its log, and the tick resumes."""
        state = self.state
        if state.wake is not None and not state.wake.closed:
            self.now = state.wake.deadline
            present = [s for s in (self.head,) if s is not None]
            if self.script.commander_present:
                present.append(self.commander)
            for who in present:
                with self.ids.drawn_by(f"commit:{who}"):
                    wake.commit(self.store, self.campaign, who, self.now)
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
            self.campaign,
            offline=True,
            transport_factory=cmp.live_transport,
            briefings=self.tmp / "briefings",
            warn=lambda _m: None,
            stop_after=stop_after,
            now=self.now,
        )

    # -- the script

    def play(self, script: Script = PLAY) -> "Game":
        """Play ``script``: the commander files his held order and asks for it, the head
        allows it his nation's way, and the wakes close until the held order has ended
        (or, with ``to_season_end``, the season has)."""
        self.script = script
        nation, p = self.nation, self.played
        self._tick(None)  # the first tick opens wake 0
        p.held = self.file(self.commander, nation.order, "commander:held")
        p.asked = self.ask("commander:ask")
        if script.own_aim is not None:
            with self.ids.drawn_by("commander:own-aim"):
                realism_tick.set_own_aim(self.store, self.campaign, self.commander, *script.own_aim)
        for n in range(WAKES):
            if self.state.phase is not Phase.PLAY:
                return self
            self._allow()
            self._steps()
            if script.retry_at == n:
                self._retry()
            self.close(restart=script.restart_at == n)
            if not script.to_season_end and (self.ends() or self.declined()):
                return self
        return self

    def declined(self) -> bool:
        """The ask was answered no: final for the held order."""
        found = [a for a in self.logged(ev.AskAnswered) if a.order_id == self.played.held]
        return any(not a.granted for a in found)

    def _allow(self) -> None:
        """A played head files his next order once the one before it is enacted."""
        p, allow = self.played, self.nation.allow
        if self.head is None or not self.script.allows or len(p.allowed) == len(allow):
            return
        if p.allowed and self.state.orders[p.allowed[-1]].status is not OrderStatus.ENACTED:
            return
        form = allow[len(p.allowed)]
        p.allowed.append(self.file(self.head, form, f"head:allow:{len(p.allowed)}"))

    def _steps(self) -> None:
        """What the seats do this wake: the commander takes his step on the head's posture
        order where it crosses his desk, the head takes his own step on his own order (his
        bill), and a played single decider chooses on the matter."""
        state, p = self.state, self.played
        for order_id in p.allowed:
            order = state.orders[order_id]
            if (
                order.status is OrderStatus.MOVING
                and self.script.commander_present
                and held_by_another(state, order) == self.commander
                and order.held_choice is None
            ):
                self.step(self.commander, order_id, f"commander:desk:{order_id}")
            elif (
                order.status is OrderStatus.MOVING
                and self.head is not None
                and state.pipelines[order.pipeline].steps[order.step].person
                == state.seats[self.head].embodies
            ):
                self.step(self.head, order_id, f"head:own-step:{order_id}")
        asked = state.asked.get(p.held)
        if (
            self.head is not None
            and not self.nation.council
            and not self.nation.allow
            and asked is not None
            and asked.answered is None
            and p.chose is None
        ):
            self.choose("head:choose")
            p.chose = state.in_world_date

    def _retry(self) -> None:
        """Each seat repeats itself: the commander asks again, and a played decider who has
        chosen chooses again while the matter is still open."""
        p = self.played
        try:
            self.ask("retry:ask")
        except ValueError as exc:
            p.refused_retries.append(str(exc))
        if p.chose is not None and self.played.held in self.state.held:
            try:
                self.choose("retry:choose")
            except ValueError as exc:
                p.refused_retries.append(str(exc))


__all__ = ["BY_KEY", "NATIONS", "PLAY", "WAKES", "Game", "Nation", "Played", "Script", "world_1941"]
