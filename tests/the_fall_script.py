"""The fall, played: a scripted 1941 game in which a player loses a post and goes on
playing the person from where he lands. ``tests/test_the_fall_game.py`` reads it.

The game is a copy of the shipped 1941 world with ``posts``, ``office`` and ``defiance``
on, and Japan's posts given what the rules read: the Combined Fleet's command is moved by
the Prime Minister and has the Kure Naval District below it; a written order taking the
fleet to Pearl Harbor is held by the liaison conference; the Prime Minister's card may
appoint. Two scripts play in it, each through the engine's own entry points and with the
ids drawn per act, as ``tests/commanders_script.py`` does (``Game``):

- ``relief``: Yamamoto and Konoe both played. Yamamoto sends his held order anyway; it is
  an incident; Konoe disowns it, then relieves him; the notice reaches Yamamoto a wake
  ahead; he plays on from Kure; Konoe restores him.
- ``fall``: the Army and the Navy stand under the line under Konoe. The warning, the
  question and the sitting follow; the Emperor, run by code, removes him where he regards
  him ill (``removed``) and keeps him otherwise. Konoe's player plays on as the person.

The script files only orders a seat could file; there is no live model call.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import pytest

from revisionist.core import events as ev
from revisionist.core.goals import season_winners
from revisionist.core.ids import AssetId, FeatureId, OrderId, SeatId
from revisionist.core.realism import groups, posts
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.agenda import Ask
from revisionist.core.realism.effect import Appointment, MoveForce
from revisionist.core.realism.pipeline import StepAction
from revisionist.core.resolution import TickStage
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import object_id
from revisionist.engine import realism_tick, wake
from revisionist.engine.store import MemoryStore
from revisionist.engine.web import catchup_api
from revisionist.engine.web.realism_api import WaitLine
from tests import test_replacement
from tests.commanders_script import Game, Nation, Script, world_1941
from tests.locked_orders_script import Ids, World
from tests.test_elections import BILL, support, without_post
from tests.test_office_question import Sitting
from tests.test_posts import ILSE, KARA, NORRA, seat
from tests.test_posts import world as toy_world
from tests.test_territory_model import CAMPAIGN

PLAIN = Script()
"""The scripts as written: no restart."""

RULES = ("posts", "office", "defiance")
"""The stage-4 rules the copy turns on."""

STAGE_4 = (*RULES, "elections", "aide_note")
"""Every stage-4 rule a script here turns on: the toy floor turns on ``elections``, and the
scripts with a seat away turn on ``aide_note``."""

FLEET_POST = "combined_fleet_command"
LESSER_POST = "kure_district_command"
PREMIERSHIP = "japan_premiership"
WRITTEN_ROW = "pearl_harbor_written"
COUNCIL = {"members": ["konoe", "tojo", "sugiyama", "nagano"], "needed": 4, "head": "konoe"}
UNDER = 20
"""Where the copy puts the Army's and the Navy's support, under ``office.TURN_LINE``."""

WAKES = 16
"""More wakes than either script takes to land what it waits on."""

AWAY_WAKES = 4
"""The wakes a seat stays away once it has gone."""

RELIEF = Nation(
    key="japan",
    commander="yamamoto",
    head="konoe",
    order=("combined_fleet_move", {"to": "pearl_harbor_base"}),
    row=WRITTEN_ROW,
)
FALL = Nation(
    key="japan",
    commander="konoe",
    head="yamamoto",
    order=("combined_fleet_move", {"to": "pearl_harbor_base"}),
    row=WRITTEN_ROW,
)
"""The fall's played seat is Konoe's, in the place ``Game`` keeps for the commander; the
seat beside him (Yamamoto's) is played or not as the twin needs."""

BESIDE = RELIEF
"""The fall watched from Yamamoto's seat, with Konoe's run by code when unplayed."""


def _rules(off: str | None, extra: tuple[str, ...] = ()) -> Callable[[World], None]:
    def change(w: World) -> None:
        wanted = {*w.get("rules", []), *RULES, *extra}
        w["rules"] = sorted(wanted - {off} if off is not None else wanted)

    return change


def _japan(w: World) -> None:
    for a in w["assets"]:
        if a["key"] == FLEET_POST:
            a.update(moved_by=[PREMIERSHIP], ladder=[LESSER_POST], without_leave=["border"])
    w["assets"].append(
        {
            "key": LESSER_POST,
            "kind": "office",
            "name": "Commander of the Kure Naval District",
            "tier": 2,
            "controller": "japan",
        }
    )
    w["locks"].append(
        {
            "key": WRITTEN_ROW,
            "question": "war",
            "order": {"effect": "move_force", "zone": "pearl_harbor_base"},
            "decider": {"council": COUNCIL},
        }
    )
    for c in w["cards"]:
        if c["person"] == "konoe":
            c["authority"].append(
                {
                    "name": "appointments",
                    "effects": ["appointment"],
                    "summary": "Advise the Throne on the service commands.",
                }
            )


def _base_under(w: World) -> None:
    for n in w["groups"]:
        if n["nation"] == "japan":
            for g in n["groups"]:
                if g["key"] in ("army", "navy"):
                    g["start"] = g["baseline"] = UNDER


def _regarded_ill(w: World) -> None:
    w["relationships"].append(
        {"key": "hirohito_konoe", "a": "hirohito", "b": "konoe", "disposition": -2}
    )


def fall_world(
    *,
    base_under: bool = False,
    removed: bool = False,
    noted: bool = False,
    off: str | None = None,
    more: tuple[Callable[[World], None], ...] = (),
) -> WorldFile:
    """The copy: the stage-4 rules on (less ``off``), Japan's posts as above, and for the
    fall its base under the line and, with ``removed``, the Emperor's ill regard. With
    ``noted``, ``aide_note`` is on as well."""
    changes: list[Callable[[World], None]] = [
        _rules(off, ("aide_note",) if noted else ()),
        _japan,
    ]
    if base_under:
        changes.append(_base_under)
    if removed:
        changes.append(_regarded_ill)
    return world_1941((*changes, *more))


@dataclass
class Fallen:
    """What the script did, for the tests to read."""

    held: OrderId | None = None
    defied: ev.OrderDefied | None = None
    incident: str | None = None
    relieved: OrderId | None = None
    relieved_wake: int | None = None
    played_on: list[OrderId] = field(default_factory=list)
    restored: OrderId | None = None
    holders: list[tuple[date, str | None, str | None]] = field(default_factory=list)
    """Each close: the day, and who holds the fleet (or the premiership) and Kure."""
    away: SeatId | None = None
    """The seat that stopped committing, from the act after which it went."""
    gone_at: int = 0
    """The number of events in the log when it went."""
    waits: list[WaitLine] = field(default_factory=list)
    """The aide's note of what waits on the seat away, read once what it left had come."""


class Fall(Game):
    """A game of the fall in a memory store, played by the script through the engine."""

    def __init__(
        self,
        nation: Nation,
        tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        world: WorldFile,
        head_played: bool = True,
        script: Script = PLAIN,
    ) -> None:
        super().__init__(nation, tmp, monkeypatch, head_played=head_played, world=world)
        self.script = script
        self.fallen = Fallen()
        self.taking_up: SeatId | None = None

    # -- reading

    def post(self, key: str) -> AssetId:
        return AssetId(object_id(self.campaign, "asset", key))

    def holder(self, key: str) -> str | None:
        who = posts.holder(self.state, self.post(key))
        return next((k for k in self.people if self.entity(k) == who), None)

    people = ("yamamoto", "konoe", "tojo", "hirohito")

    @property
    def wake_number(self) -> int:
        wake = self.state.wake
        return wake.number if wake is not None else -1

    def to_person(self, person: str) -> None:
        """A player takes up ``person``, whom the code has played since the opening, at the
        next close; the seat is played from then on."""
        with self.ids.drawn_by(f"take-up:{person}"):
            self.taking_up = wake.hand_over(self.store, self.campaign, self.entity(person))

    # -- the seats' acts

    def commit(self, who: SeatId, asks: list[Ask], act: str) -> OrderId:
        with self.ids.drawn_by(act):
            filed = realism_tick.commit_order(self.store, self.campaign, who, asks)
        return filed.order_id

    def to_pearl(self) -> Ask:
        force = FeatureId(object_id(self.campaign, "feature", "combined_fleet"))
        to = self.entity("pearl_harbor_base")
        return Ask(
            ask="Take the Combined Fleet to Pearl Harbor.", effect=MoveForce(force=force, to=to)
        )

    def appointment(self, person: str, appoint: bool) -> Ask:
        verb = "Restore" if appoint else "Relieve"
        return Ask(
            ask=f"{verb} Admiral Yamamoto: the Combined Fleet.",
            effect=Appointment(
                person=self.entity(person), office=str(self.post(FLEET_POST)), appoint=appoint
            ),
        )

    def note(self, key: str) -> None:
        self.fallen.holders.append(
            (self.state.in_world_date or date.min, self.holder(key), self.holder(LESSER_POST))
        )

    def until(self, done: Callable[[], bool], key: str) -> None:
        for _ in range(WAKES):
            if done():
                return
            self.close(restart=self.script.restart_at == len(self.fallen.holders))
            self.note(key)

    def close(self, restart: bool = False) -> None:
        """As ``Game.close``, but the seat away commits nothing and the aide plays it."""
        away = self.fallen.away
        if away is None:
            super().close(restart)
            return
        script, head = self.script, self.head
        if away == self.commander:
            self.script = replace(script, commander_present=False)
        else:
            self.head = None
        try:
            super().close(restart)
        finally:
            self.script, self.head = script, head

    def go(self, who: SeatId) -> None:
        self.fallen.away = who
        self.fallen.gone_at = len(self.events())

    def stay_away(self, key: str) -> None:
        f = self.fallen
        assert f.away is not None
        f.waits = list(catchup_api.waits(self.state, f.away) or [])
        for _ in range(AWAY_WAKES):
            self.close(restart=self.script.restart_at == len(f.holders))
            self.note(key)

    # -- the scripts

    def relief(self) -> "Fall":
        """Yamamoto defies; Konoe disowns, relieves and restores him."""
        f = self.fallen
        self._tick(None)
        f.held = self.commit(self.commander, [self.to_pearl()], "commander:held")
        assert f.held in self.state.held, "the conference holds the order"
        with self.ids.drawn_by("commander:anyway"):
            f.defied = realism_tick.send_anyway(self.store, self.campaign, self.commander, f.held)
        self.until(lambda: bool(self.state.incidents), FLEET_POST)
        f.incident = next(iter(self.state.incidents))
        assert self.head is not None
        with self.ids.drawn_by("head:disown"):
            realism_tick.answer_incident(
                self.store, self.campaign, self.head, f.incident, "disowned"
            )
        f.relieved = self.commit(self.head, [self.appointment("yamamoto", False)], "head:relieve")
        f.relieved_wake = self.wake_number
        self.until(lambda: self.holder(LESSER_POST) == "yamamoto", FLEET_POST)
        plays_on = Ask(
            ask="Ready the Kure yards for the fleet's return.", target=self.entity("konoe")
        )
        f.played_on.append(self.commit(self.commander, [plays_on], "commander:plays-on"))
        f.restored = self.commit(self.head, [self.appointment("yamamoto", True)], "head:restore")
        self.until(lambda: self.holder(FLEET_POST) == "yamamoto", FLEET_POST)
        return self

    def commander_away(self) -> "Fall":
        """Yamamoto files the order the conference holds and is away from then on."""
        f = self.fallen
        self._tick(None)
        f.held = self.commit(self.commander, [self.to_pearl()], "commander:held")
        self.go(self.commander)
        self.stay_away(FLEET_POST)
        return self

    def head_away(self) -> "Fall":
        """Yamamoto sends his held order anyway; Konoe is away from then on, and the
        incident comes before his seat."""
        f = self.fallen
        self._tick(None)
        f.held = self.commit(self.commander, [self.to_pearl()], "commander:held")
        with self.ids.drawn_by("commander:anyway"):
            f.defied = realism_tick.send_anyway(self.store, self.campaign, self.commander, f.held)
        assert self.head is not None
        self.go(self.head)
        self.until(lambda: bool(self.state.incidents), FLEET_POST)
        f.incident = next(iter(self.state.incidents))
        self.stay_away(FLEET_POST)
        return self

    def watched(self) -> "Fall":
        """No seat files anything: the wakes close until the question on Konoe's office
        has sat."""
        self._tick(None)
        self.close()
        self.note(PREMIERSHIP)
        self.until(lambda: bool(self.logged(ev.OfficeQuestionDecided)), PREMIERSHIP)
        return self

    def fall(self) -> "Fall":
        """Konoe's base stands under the line until the question sits; he plays on."""
        f = self.fallen
        self._tick(None)
        self.close()
        self.note(PREMIERSHIP)
        if self.taking_up is not None:
            self.head = self.taking_up
        self.until(lambda: bool(self.logged(ev.OfficeQuestionDecided)), PREMIERSHIP)
        plays_on = Ask(ask="Urge a summit with Roosevelt.", target=self.entity("hirohito"))
        f.played_on.append(self.commit(self.commander, [plays_on], "konoe:plays-on"))
        self.close()
        self.note(PREMIERSHIP)
        self.close()
        self.note(PREMIERSHIP)
        return self


def relief(
    tmp: Path, monkeypatch: pytest.MonkeyPatch, *, script: Script = PLAIN, **world: object
) -> Fall:
    return Fall(RELIEF, tmp, monkeypatch, world=fall_world(**world), script=script).relief()  # type: ignore[arg-type]


def fall(
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    removed: bool,
    script: Script = PLAIN,
    beside_played: bool = False,
    **world: object,
) -> Fall:
    """With ``beside_played`` a player takes up Yamamoto, beside Konoe, at the first close;
    the two games open alike and differ only in who plays him after it."""
    decl = fall_world(base_under=True, removed=removed, **world)  # type: ignore[arg-type]
    g = Fall(FALL, tmp, monkeypatch, world=decl, head_played=False, script=script)
    if beside_played:
        g.to_person("yamamoto")
    return g.fall()


def away(
    tmp: Path, monkeypatch: pytest.MonkeyPatch, who: str, *, script: Script = PLAIN, **world: object
) -> Fall:
    """The relief's opening with ``who`` (``commander`` or ``head``) away from the act that
    puts something before his seat, and ``aide_note`` on."""
    decl = fall_world(noted=True, **world)  # type: ignore[arg-type]
    g = Fall(RELIEF, tmp, monkeypatch, world=decl, script=script)
    return g.commander_away() if who == "commander" else g.head_away()


CLOCK_DAYS = 7
"""Yamamoto's horizon, given to Konoe as well in the copy the seats run by code play."""


def _one_clock(w: World) -> None:
    """The world wakes at the smallest horizon among the persons humans hold, and the
    office sits in a wake's walk; with Konoe's and Yamamoto's horizons equal, which of them
    is played leaves the clock as it was."""
    for card in w["cards"]:
        if card["person"] in ("konoe", "yamamoto"):
            card["horizon_days"] = CLOCK_DAYS


def by_code(
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    who: str | None,
    *,
    removed: bool,
    script: Script = PLAIN,
    more: tuple[Callable[[World], None], ...] = (),
) -> Fall:
    """The fall watched with Konoe and Yamamoto both played, or with ``who`` of them run by
    code from the opening and the other played, on one clock."""
    decl = fall_world(base_under=True, removed=removed, more=(_one_clock, *more))
    nation = BESIDE if who == "konoe" else FALL
    g = Fall(nation, tmp, monkeypatch, world=decl, head_played=who is None, script=script)
    return g.watched()


# --- on the toy world: the floor before and after an election, and the lost person ----


def _floor(w: World) -> None:
    """A one-step floor Ilse decides, her ``pass_act`` lever the votes rule tallies, and
    the bill's public result."""
    w["pipelines"] = [
        *w.get("pipelines", []),
        {
            "key": "floor",
            "name": "The floor",
            "source": "toy",
            "steps": [{"person": "ilse", "kind": "decision", "days": 1}],
        },
    ]
    card = next(c for c in w["cards"] if c["person"] == "ilse")
    card["pipelines"] = [*card.get("pipelines", []), "floor"]
    lever = {
        "name": "pass_act",
        "pipeline": "floor",
        "resolver": "votes",
        "params": [{"name": "bill", "kind": "enum", "choices": [BILL]}],
    }
    card["levers"] = [*card.get("levers", []), lever]
    w["quantities"].append(
        {
            "key": f"{BILL}_passed",
            "owner": "norra",
            "name": "Merchant ships armed",
            "unit": "flag",
            "public": True,
            "computed": True,
        }
    )


def purse(value: int) -> Callable[[World], None]:
    """A figure of Sudland's no Norran seat sees."""

    def change(w: World) -> None:
        w["quantities"].append(
            {"key": "sudland_purse", "owner": "sudland", "name": "Purse", "value": value}
            | {"unit": "crowns", "source": "toy"}
        )

    return change


def _without(rule: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        w["rules"] = [r for r in w["rules"] if r != rule]

    return change


@dataclass
class Floor:
    """The toy floor played: the bill sent before the election and again after it."""

    game: Sitting
    passed: list[tuple[date, int | None]] = field(default_factory=list)
    """Each sending: the day it settled, and the bill's result after it."""
    seats: list[dict[str, int | None]] = field(default_factory=list)
    """The assembly's seats at each sending."""


class _Floor(Sitting):
    def __init__(self, w: WorldFile, restart_at: int | None) -> None:
        super().__init__(w)
        self.restart_at = restart_at
        self.ticks = 0

    def tick(self, stop_after: TickStage | None = None) -> None:
        if self.restart_at == self.ticks:
            realism_tick.run_realism_tick(self.store, CAMPAIGN, stop_after=TickStage.PIPELINES)
            fresh = MemoryStore()
            fresh.append_all(list(self.store.read(CAMPAIGN)))
            self.store = fresh
        realism_tick.run_realism_tick(self.store, CAMPAIGN, stop_after=stop_after)
        self.ticks += 1


def floor(
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    restart_at: int | None = None,
    off: str | None = None,
    more: tuple[Callable[[World], None], ...] = (),
) -> Floor:
    """Rule 3 on the toy: the Greens far over their baseline and short of a majority on
    the bill; Ilse sends it, it fails; the election on 1 May redraws the assembly; she
    sends it again, and it passes."""
    tmp.mkdir(parents=True, exist_ok=True)
    Ids(CAMPAIGN).install(monkeypatch)
    changes = [support(95, 0, yeas=44), without_post, _floor, *more]
    if off is not None:
        changes.append(_without(off))
    g = _Floor(toy_world(tmp, *changes), restart_at)
    out = Floor(g)
    for _ in range(2):
        out.seats.append({b.key: b.seats for b in groups.of(g.state, NORRA) if b.chamber})
        order = realism_tick.file_order(g.store, CAMPAIGN, seat(ILSE), "pass_act", {"bill": BILL})
        realism_tick.take_step(g.store, CAMPAIGN, seat(ILSE), order.order_id, StepAction.PASS, {})
        g.tick()
        state = g.state
        result = state.quantities[rs.qid(state, f"{BILL}_passed")].value
        out.passed.append((state.in_world_date or date.min, result))
        for _ in range(2):
            g.tick()
    return out


@dataclass
class Lost:
    """Rule 4 on the toy: Ilse loses the chancellery and with it every way to act; her
    player takes Kara in her place."""

    game: test_replacement.Game
    winners: frozenset[SeatId]


def lost(
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    *changes: Callable[[World], None],
    restart: bool = False,
) -> Lost:
    """Ilse loses the chancellery; at the next close her player takes Kara, and the tick
    after it scores the season. With ``restart``, that tick stops after the pipelines and
    resumes from a fresh store."""
    tmp.mkdir(parents=True, exist_ok=True)
    Ids(CAMPAIGN).install(monkeypatch)
    g = test_replacement.game(tmp, *changes)
    g.tick()
    g.lose_ilse()
    g.open()
    g.take(KARA)
    g.close()
    if restart:
        realism_tick.run_realism_tick(g.store, CAMPAIGN, stop_after=TickStage.PIPELINES)
        fresh = MemoryStore()
        fresh.append_all(list(g.store.read(CAMPAIGN)))
        g.store = fresh
    g.tick()
    return Lost(g, season_winners(g.state))


def held_by(holder: str, *areas: str) -> Callable[[World], None]:
    def change(w: World) -> None:
        for t in w["territories"]:
            if t["key"] in areas:
                t["holder"] = holder

    return change


__all__ = [
    "BESIDE",
    "FALL",
    "FLEET_POST",
    "LESSER_POST",
    "PLAIN",
    "PREMIERSHIP",
    "RELIEF",
    "RULES",
    "STAGE_4",
    "WAKES",
    "Fall",
    "Fallen",
    "Floor",
    "Lost",
    "away",
    "by_code",
    "fall",
    "fall_world",
    "floor",
    "held_by",
    "lost",
    "purse",
    "relief",
]
