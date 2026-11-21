"""Salt Strait plays a whole game under the same rules (SSP).

A scripted two-seat game on ``worlds/salt-strait-realism.yaml`` runs from its first day to
its season's end through the engine's public entry points, as two players would: forms
through ``realism_tick.file_order``, written orders through ``orders_reader.read_order``
and ``file_order``, battle decisions and contingencies through the ``battles_api`` asks and
``realism_tick.commit_order``, the offer through ``agreements_api.offer_reading``, its
answer through ``agenda_api.answer``, the conference through ``conferences_api``, the odds
through ``odds.reply``, and each wake's close through ``wake.commit`` and
``runner.play_tick``. No live model is called: every reply is canned. The aide reading a
written order answers from the script (``Reader``); every other call (prose, options)
gets a canned failure, which the engine takes as it takes a model that is down.

The defending seat sets its force's standing order, sends up a balloon, places a spy in
writing and speaks on a theme in writing, accepts the attacker's offer, then goes away for
the rest of the season; the aide plays it. The attacker declares war, asks the odds twice,
calls a conference and votes in it, marches on the defender's coast, holds in the battle
for a wake and then presses, and the defender's levy withdraws by its standing order.

The same script body plays the 1941 world with only the cast changed (``CASTS``). The
test's copy of each world changes data only (``Cast.changes``): it switches on the three
rules a live model reads, which every shipped world leaves off, and the rest is listed as
findings against the items that own the data (``FINDINGS``). This file changes no rule.
"""

import json
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from revisionist.core import events as ev
from revisionist.core.goals import season_winners
from revisionist.core.ids import CampaignId, EntityId, FeatureId, SeatId, derived_id
from revisionist.core.ontology import Phase
from revisionist.core.project import project
from revisionist.core.realism import conference, economy, holders, territory
from revisionist.core.realism.battle import Ending
from revisionist.core.realism.kinds import Role
from revisionist.core.realism.pipeline import Order
from revisionist.core.state import State
from revisionist.core.world import WorldFile
from revisionist.core.world_compile import compile_world, object_id
from revisionist.engine import campaign as cmp
from revisionist.engine import odds, orders_reader, realism_tick, runner, session_zero, wake
from revisionist.engine.llm import Reply, Request, TransportError
from revisionist.engine.store import EventStore, MemoryStore, load_state
from revisionist.engine.web import agenda_api, agreements_api, battles_api, conferences_api
from revisionist.engine.web import realism_snapshot as rs
from revisionist.engine.web.stakes import seat_stakes
from tests.async_table import SeatIds

World = dict[str, Any]
Change = Callable[[World], None]
Form = tuple[str, dict[str, str]]

CAMPAIGN = CampaignId("01ARZ3NDEKTSV4RRFFQ69G5FAV")
T0 = datetime(2030, 1, 1, tzinfo=UTC)
WAKES = 120
"""More wakes than any season the script plays takes."""
MODEL_RULES = ("writing", "clause_reader", "written_orders")
OFFER_CLAUSE_DAYS = 30
"""The offer's place clause is judged this many days after it is made."""
CONFERENCE_DAYS = 6
"""The attacker's conference votes this many days after its call."""
CONFERENCE = "strait-talks"


# --- the casts -----------------------------------------------------------------------


@dataclass(frozen=True)
class Cast:
    """What the script needs from a world. Every value is a world key; the script body
    is the same for every cast."""

    name: str
    world: str
    """The shipped world file's stem."""
    changes: tuple[Change, ...]
    """Data changes made to the test's copy of the world before it is compiled."""
    defender: str
    """The seat that is attacked and goes away after the opening wakes."""
    attacker: str
    defender_nation: str
    attacker_nation: str
    defender_force: str
    attacker_force: str
    front: str
    """The defender's territory the attacker marches on and takes."""
    war: Form | None
    """The attacker's declaration of war, or None when the two are at war at the start."""
    march: Form
    cover: Form | None
    """The attacker's air piece moved to cover the front, if the cast has one."""
    recall: Form | None
    """The air piece sent home once the battle is over, where only the agent sees it."""
    recon: Form
    """The defender's reconnaissance flight, by its form."""
    aide: str
    """The person the defender writes to."""
    agent: dict[str, Any]
    """The written order's effect that places an agent; ``target`` is a key."""
    theme: str
    """The defender's theme, named in writing."""
    group: str
    """The defender's group the theme moves."""
    offer_area: str
    """The area the offer's dated place clause names (the attacker's own)."""
    patrol: Form | None
    """A form the attacker files while the battle runs, so each wake is one world day; None
    where the cast's horizon already makes every wake one day."""

    def entity(self, key: str) -> EntityId:
        return EntityId(object_id(CAMPAIGN, "entity", key))

    def seat(self, key: str) -> SeatId:
        return SeatId(derived_id(CAMPAIGN, "seat", self.entity(key)))

    def compiled(self) -> WorldFile:
        path = cmp.world_path(self.world)
        shipped = cmp.load_world(path)
        raw: World = yaml.safe_load(path.read_text())
        for change in self.changes:
            change(raw)
        carried = {"map_data": shipped.map_data, "developments": shipped.developments}
        return WorldFile.model_validate(raw).model_copy(update=carried)


def model_rules(w: World) -> None:
    """The three rules a live model reads, on in the test's copy only (SSG rule 2)."""
    w["rules"] = [*w["rules"], *(r for r in MODEL_RULES if r not in w["rules"])]


def authority(people: dict[str, tuple[str, list[str]]]) -> Change:
    """Each named leader commands the named forces through his aide, and speaks in public.
    The domains are added to any the card already has."""

    def change(w: World) -> None:
        for card in w["cards"]:
            if card["person"] in people:
                executor, forces = people[card["person"]]
                held = card.setdefault("authority", [])
                held.append(
                    {
                        "name": "army",
                        "effects": ["move_force", "engagement", "investigate", "allocate"],
                        "forces": forces,
                        "executor": executor,
                    }
                )
                if not any("statement" in d.get("effects", []) for d in held):
                    held.append({"name": "public_word", "effects": ["statement", "measure"]})

    return change


def tiers(levels: dict[str, int]) -> Change:
    def change(w: World) -> None:
        for f in w["features"]:
            if f["key"] in levels:
                f["tier"] = levels[f["key"]]

    return change


def horizon(people: tuple[str, ...], days: int) -> Change:
    def change(w: World) -> None:
        for card in w["cards"]:
            if card["person"] in people:
                card["horizon_days"] = days

    return change


def placed(piece: str, place: str) -> Change:
    def change(w: World) -> None:
        for f in w["features"]:
            if f["key"] == piece:
                f["places"] = [place]

    return change


SALT_STRAIT = Cast(
    name="salt-strait",
    world="salt-strait-realism",
    changes=(
        model_rules,
        authority(
            {
                "oren_vale": ("mira", ["varda_levy", "varda_galleys", "varda_balloons"]),
                "general_aske": ("sefa", ["ostrel_levy", "ostrel_galleys", "ostrel_balloons"]),
            }
        ),
        tiers({"ostrel_levy": 5, "varda_levy": 3}),
        horizon(("oren_vale", "general_aske"), 14),
    ),
    defender="oren_vale",
    attacker="general_aske",
    defender_nation="varda",
    attacker_nation="ostrel",
    defender_force="varda_levy",
    attacker_force="ostrel_levy",
    front="varda_saltworks",
    war=("declare_war", {"target": "varda"}),
    march=("move_force", {"force": "ostrel_levy", "to": "varda_saltworks"}),
    cover=("move_force", {"force": "ostrel_balloons", "to": "harrow_pass"}),
    recall=("move_force", {"force": "ostrel_balloons", "to": "ostrel_heartland"}),
    recon=("fly_balloon", {"intel": "recon", "piece": "varda_balloons", "area": "harrow_pass"}),
    aide="Mira Toll",
    agent={
        "kind": "investigate",
        "target": "ostrel_heartland",
        "question": "agent",
        "intel": "agent",
    },
    theme="the_open_strait",
    group="salt_guilds",
    offer_area="ostrel_heartland",
    patrol=("galley_patrol", {"intel": "patrol", "piece": "ostrel_galleys"}),
)

NINETEEN_41 = Cast(
    name="autumn-1941",
    world="autumn-1941",
    changes=(
        model_rules,
        authority(
            {
                "churchill": ("ismay", ["western_desert_force"]),
                "hitler": ("jodl", ["afrika_korps"]),
            }
        ),
        tiers({"afrika_korps": 5, "western_desert_force": 3}),
        placed("afrika_korps", "tripoli"),
        horizon(("hitler",), 1),
    ),
    defender="churchill",
    attacker="hitler",
    defender_nation="uk",
    attacker_nation="germany",
    defender_force="western_desert_force",
    attacker_force="afrika_korps",
    front="egypt",
    war=None,
    march=("move_army", {"force": "afrika_korps", "to": "alexandria"}),
    cover=None,
    recall=None,
    recon=("fly_recon", {"intel": "recon", "piece": "bomber_command", "area": "occupied_france"}),
    aide="Sir Hastings Ismay",
    agent={"kind": "investigate", "target": "tripolitania", "question": "agent", "intel": "agent"},
    theme="an_appeal_to_america",
    group="public",
    offer_area="cyrenaica",
    patrol=None,
)

"""The 1941 cast: Hitler's Afrika Korps marches on Egypt, held by Churchill's Western
Desert Force. The test's copy gives each leader command of his desert army, sets the two
armies' strengths, starts the Afrika Korps at Tripoli (the seeded battle then runs the
script's course: an even first round, a lull while Hitler holds, and the Western Desert
Force leaving by its standing order when he presses), and gives Hitler a one-day horizon
so every wake is one world day, which the patrol does on Salt Strait."""

CASTS = (SALT_STRAIT, NINETEEN_41)


# --- no model -------------------------------------------------------------------------


class Reader:
    """The aide reading a written order: the script's own reading, canned."""

    def __init__(self, asks: list[dict[str, Any]]) -> None:
        self.asks = asks

    def call(self, request: Request) -> Reply:
        return Reply({"asks": self.asks, "reason": ""}, request.model, 0, 0, 0, 0.0)


ASKED: Counter[str] = Counter()
"""Each call class the tick asked for, across every game in this module."""


class NoModel:
    """Every call the tick makes gets a canned failure; the classes asked are counted."""

    def call(self, request: Request) -> Reply:
        ASKED[request.call_class] += 1
        raise TransportError("canned: no model plays this game")


# --- the game -------------------------------------------------------------------------


@dataclass
class Played:
    """What the script did, and when, for the tests to read."""

    odds: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[tuple[date, str]] = field(default_factory=list)
    conference: str | None = None
    away_from: int | None = None
    """The first wake the defender did not commit."""
    away_day: date | None = None
    """The world day that wake opened on."""
    wakes: int = 0
    recalled: bool = False
    rings: list[list[str]] = field(default_factory=list)
    """Each ring the defender's map served, as it was served."""


class Game:
    """One game in a memory store, played by the script through the engine."""

    def __init__(self, cast: Cast, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.cast = cast
        self.tmp = tmp
        self.ids = SeatIds()
        self.ids.install(monkeypatch)
        self.store: EventStore = MemoryStore()
        self.store.append_all(compile_world(cast.compiled(), CAMPAIGN, cmp.versions()))
        self.now = T0
        names = load_state(self.store, CAMPAIGN).entities
        for key in (cast.defender, cast.attacker):
            with self.ids.drawn_by(f"claim:{key}"):
                session_zero.claim(
                    self.store, CAMPAIGN, cast.seat(key), names[cast.entity(key)].name
                )
        with self.ids.drawn_by("open"):
            realism_tick.open_play(self.store, CAMPAIGN)
        self.defender = cast.seat(cast.defender)
        self.attacker = cast.seat(cast.attacker)
        self.played = Played()

    # -- reading

    @property
    def state(self) -> State:
        return load_state(self.store, CAMPAIGN)

    def logged(self, kind: type[Any]) -> list[Any]:
        return [e.payload for e in self.store.read(CAMPAIGN) if isinstance(e.payload, kind)]

    def key(self, key: str) -> EntityId:
        return self.cast.entity(key)

    # -- acts, each through a public entry point and drawn from its own id stream

    def form(self, who: SeatId, form: Form, act: str) -> Order:
        with self.ids.drawn_by(act):
            return realism_tick.file_order(self.store, CAMPAIGN, who, form[0], form[1])

    def write(self, who: SeatId, to: str, text: str, effect: dict[str, Any], act: str) -> None:
        reading = orders_reader.read_order(
            self.state, who, to, "", text, Reader([{"ask": text, "effect": effect}])
        )
        with self.ids.drawn_by(act):
            done = orders_reader.file_order(self.store, CAMPAIGN, who, reading)
        assert not done["refused"], (act, done["reply"], reading.shown)

    def battle(self, who: SeatId, body: dict[str, Any], act: str) -> None:
        asks, _, _ = battles_api.battle_asks(self.state, who, body)
        with self.ids.drawn_by(act):
            realism_tick.commit_order(self.store, CAMPAIGN, who, asks)

    def contingency(self, who: SeatId, body: dict[str, Any], act: str) -> None:
        asks, _ = battles_api.contingency_asks(self.state, who, body)
        with self.ids.drawn_by(act):
            realism_tick.commit_order(self.store, CAMPAIGN, who, asks)

    def close(self, present: tuple[SeatId, ...]) -> None:
        state = self.state
        if state.wake is not None and not state.wake.closed:
            self.now = state.wake.deadline
            for who in present:
                with self.ids.drawn_by(f"commit:{who}"):
                    wake.commit(self.store, CAMPAIGN, who, self.now)
        self._tick()
        self.played.wakes += 1

    def _tick(self) -> None:
        runner.play_tick(
            self.store,
            CAMPAIGN,
            offline=False,
            transport_factory=NoModel,
            briefings=self.tmp / "briefings",
            warn=lambda _m: None,
            now=self.now,
        )

    # -- the script

    def play(self, *, until: Callable[["Game"], bool] | None = None) -> "Game":
        """The whole script, from the first wake to the season's end."""
        self._tick()  # the first tick opens wake 0
        for n in range(WAKES):
            if self.state.phase is not Phase.PLAY:
                return self
            self.wake(n)
            present = (self.attacker,) if n >= 2 else (self.defender, self.attacker)
            if n == 2:
                self.played.away_from = self.state.wake.number if self.state.wake else None
                self.played.away_day = self.state.in_world_date
            self.close(present)
            self.read_rings()
            if until is not None and until(self):
                return self
        raise AssertionError("the season never ended")

    def wake(self, n: int) -> None:
        """One wake's acts. The defender plays the first two wakes and is away after."""
        c, me, foe = self.cast, self.defender, self.attacker
        today = self.state.in_world_date
        assert today is not None
        if n == 0:
            self.contingency(
                me, {"force": c.defender_force, "kind": "withdraw_below", "below": 3}, "standing"
            )
            self.form(me, c.recon, "recon")
            effect = {**c.agent, "target": str(self.key(c.agent["target"]))}
            self.write(me, c.aide, "Place an agent behind their lines.", effect, "agent")
            said = {"kind": "statement", "theme": c.theme}
            self.write(me, c.aide, f"We speak on {c.theme.replace('_', ' ')}.", said, "statement")
            self.offer(today)
            self.call(today)
        elif n == 1:
            (item,) = [i for i in self.agenda(me) if i["kind"] == "Offer"]
            with self.ids.drawn_by("answer"):
                done = agenda_api.answer(self.store, CAMPAIGN, me, item["id"], True)
            assert not done["refused"], done
            if c.war is not None:
                self.form(foe, c.war, "war")
            self.vote()
        elif n == 2:
            self.form(foe, c.march, "march")
            if c.cover is not None:
                self.form(foe, c.cover, "cover")
            self.ask_odds()
        else:
            self.fight(n)

    def agenda(self, who: SeatId) -> list[Any]:
        return list(agenda_api.agenda(self.state, who, list(self.store.read(CAMPAIGN)))["items"])

    def offer(self, today: date) -> None:
        c = self.cast
        body = {
            "parties": [str(self.key(c.defender_nation))],
            "wording": "Our levy keeps off that shore this season.",
            "clauses": [
                {
                    "type": "place",
                    "binds": str(self.key(c.attacker_nation)),
                    "force": str(FeatureId(object_id(CAMPAIGN, "feature", c.attacker_force))),
                    "area": str(self.key(c.offer_area)),
                    "present": False,
                    "on": (today + timedelta(days=OFFER_CLAUSE_DAYS)).isoformat(),
                }
            ],
        }
        reading = agreements_api.offer_reading(self.state, self.attacker, body)
        with self.ids.drawn_by("offer"):
            done = orders_reader.file_order(self.store, CAMPAIGN, self.attacker, reading)
        assert not done["refused"], done

    def call(self, today: date) -> None:
        c = self.cast
        body = {
            "text": "The strait stays open to every flag.",
            "invited": [str(self.key(c.defender_nation))],
            "voting_day": (today + timedelta(days=CONFERENCE_DAYS)).isoformat(),
            "key": CONFERENCE,
        }
        args, _ = conferences_api.call_args(self.state, self.attacker, body)
        with self.ids.drawn_by("call"):
            conferences_api.call(self.store, CAMPAIGN, self.attacker, args)
        self.played.conference = conference.call_key(CAMPAIGN, self.attacker, CONFERENCE)

    def vote(self) -> None:
        args, _ = conferences_api.vote_args(
            self.state, self.attacker, {"conference": self.played.conference, "vote": "for"}
        )
        with self.ids.drawn_by("vote"):
            conferences_api.vote(self.store, CAMPAIGN, self.attacker, args)

    def ask_odds(self) -> None:
        c = self.cast
        body = {"force": c.attacker_force, "to": c.front}
        for _ in range(2):  # two servers, so the second is computed, not served from a cache
            out = odds.reply(odds.Service(workers=1), self.state, self.attacker, body)
            assert not out["refused"], out
            self.played.odds.append(out["odds"])

    def fight(self, n: int) -> None:
        """While the march is on or the battle runs, the attacker files a patrol each wake,
        so each wake is one world day; in the battle he holds for one wake, then presses."""
        c, state = self.cast, self.state
        front = self.key(c.front)
        battle = state.battles.get(front)
        marching = not any(b.battle.area == front for b in self.logged(ev.BattleOpened))
        if battle is None and not marching:
            if not self.played.recalled and c.recall is not None:
                self.form(self.attacker, c.recall, "recall")
                self.played.recalled = True
            return
        if c.patrol is not None:
            self.form(self.attacker, c.patrol, f"patrol:{n}")
        if battle is None:
            return
        decision = "hold" if not self.played.decisions else "press"
        if len(self.played.decisions) < 2:
            body = {"area": c.front, "decision": decision}
            self.battle(self.attacker, body, f"battle:{n}")
            assert state.in_world_date is not None
            self.played.decisions.append((state.in_world_date, decision))

    def read_rings(self) -> None:
        for r in rs.map_reports(project(self.state, self.defender)):
            if r["ring"]:
                self.played.rings.append(list(r["ring"]))


@pytest.fixture(scope="module")
def games(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Game]]:
    """Each cast's full game, played once for the module."""
    out: dict[str, Game] = {}
    with pytest.MonkeyPatch.context() as m:
        for cast in CASTS:
            out[cast.name] = Game(cast, tmp_path_factory.mktemp(cast.name), m).play()
        yield out


def game_of(games: dict[str, Game], cast: Cast) -> Game:
    return games[cast.name]


ON_EACH = pytest.mark.parametrize("cast", CASTS, ids=lambda c: c.name)


# --- Rule 1: the game, from its first day to its season's end ------------------------


@ON_EACH
def test_the_game_runs_from_its_first_day_to_its_seasons_end(
    games: dict[str, Game], cast: Cast
) -> None:
    g = game_of(games, cast)
    assert g.state.phase is Phase.SEASON_OVER
    (ended,) = g.logged(ev.SeasonEnded)
    assert ended is not None
    assert g.played.away_from is not None


@ON_EACH
def test_pieces_move_by_adjacency(games: dict[str, Game], cast: Cast) -> None:
    g = game_of(games, cast)
    board = g.state.map
    assert board is not None
    stepped = g.logged(ev.PieceStepped)
    assert stepped
    assert all(territory.adjacent(board, p.left, p.entered) for p in stepped)


@ON_EACH
def test_the_front_is_taken_and_its_yield_lags(games: dict[str, Game], cast: Cast) -> None:
    g = game_of(games, cast)
    front, taker = g.key(cast.front), g.key(cast.attacker_nation)
    (taken,) = [h for h in g.logged(ev.AreaHeld) if h.area == front]
    assert taken.holder == taker and taken.was == g.key(cast.defender_nation)
    state = g.state
    assert holders.holder(state, front) == taker
    lag = taken.on + timedelta(days=economy.CAPTURE_LAG_DAYS - 1)
    assert economy.factor(state, front, Role.OUTPUT, taken.on) == 0
    assert economy.factor(state, front, Role.OUTPUT, lag) == 0
    after = taken.on + timedelta(days=economy.CAPTURE_LAG_DAYS)
    assert economy.factor(state, front, Role.OUTPUT, after) == economy.CAPTURE_SHARE / 100


@ON_EACH
def test_the_battle_runs_three_days_with_a_decision_changed_and_a_contingency_firing(
    games: dict[str, Game], cast: Cast
) -> None:
    g = game_of(games, cast)
    front = g.key(cast.front)
    (opened,) = [b.battle for b in g.logged(ev.BattleOpened) if b.battle.area == front]
    (ended,) = [b for b in g.logged(ev.BattleEnded) if b.area == front]
    assert (ended.on - opened.opened).days >= 2, "the battle spans three world days"
    decided = [d for d in g.logged(ev.BattleDecided) if d.area == front]
    made = [d.decision for d in decided if d.decision is not None]
    assert len(set(made)) >= 2, f"one decision changed: {made}"
    assert ended.ending is Ending.WON and ended.winner == g.key(cast.attacker_nation)
    withdrew = [
        p
        for p in g.logged(ev.PieceStepped)
        if p.left == front and p.nation == g.key(cast.defender_nation)
    ]
    assert withdrew, "the defender's levy left the front by its standing order"
    assert g.played.away_from is not None
    assert all(d > g.played.decisions[0][0] for d, _ in g.played.decisions[1:])


@ON_EACH
def test_the_absent_seats_levy_left_by_its_own_standing_order(
    games: dict[str, Game], cast: Cast
) -> None:
    """The defender is away from the third wake: no decision of his side is logged, and his
    levy leaves the front on the battle's last day by the contingency he set at the start,
    not broken and forced back."""
    g = game_of(games, cast)
    front, mine = g.key(cast.front), g.key(cast.defender_nation)
    assert not [d for d in g.logged(ev.BattleDecided) if d.nation == mine]
    (ended,) = [b for b in g.logged(ev.BattleEnded) if b.area == front]
    (left,) = [p for p in g.logged(ev.PieceStepped) if p.left == front and p.nation == mine]
    assert left.on == ended.on
    assert left.cause is not territory.StepCause.FORCED
    closed = g.logged(ev.WakeClosed)
    assert all(g.defender in c.timed_out for c in closed if c.wake >= (g.played.away_from or 0))


@ON_EACH
def test_a_report_arrives_and_an_old_one_is_served_with_a_ring(
    games: dict[str, Game], cast: Cast
) -> None:
    g = game_of(games, cast)
    assert g.logged(ev.ReportMade)
    assert g.played.rings, "the defender's map served a ring around an old report"
    board = g.state.map
    assert board is not None
    keys = {t.key for t in board.territories} | {z.key for z in board.sea_zones}
    assert all(set(ring) <= keys for ring in g.played.rings)
    assert max(len(ring) for ring in g.played.rings) >= 2, "an old report widens into a ring"


@ON_EACH
def test_the_flight_from_its_form_and_the_agent_from_writing_both_act(
    games: dict[str, Game], cast: Cast
) -> None:
    g = game_of(games, cast)
    piece = FeatureId(object_id(CAMPAIGN, "feature", cast.recon[1]["piece"]))
    area = g.key(cast.recon[1]["area"])
    flown = [f.feature for f in g.logged(ev.FeatureSet) if f.feature.feature_id == piece]
    assert any(f.recon == area and f.recon_on is not None for f in flown)
    mine = g.key(cast.defender_nation)
    placed, *later = [a for a in g.logged(ev.AgentSet) if a.nation == mine]
    assert placed.agent.area == g.key(cast.agent["target"]) and placed.agent.lost is None
    assert all(a.agent.lost is not None for a in later), "a later set only marks the agent lost"
    intel = g.state.intelligence[mine]
    assert any(a.area == placed.agent.area for a in intel.agents)


@ON_EACH
def test_the_odds_asked_twice_are_the_same(games: dict[str, Game], cast: Cast) -> None:
    g = game_of(games, cast)
    first, second = g.played.odds
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


@ON_EACH
def test_a_statement_moves_a_group(games: dict[str, Game], cast: Cast) -> None:
    g = game_of(games, cast)
    mine = g.key(cast.defender_nation)
    moved = [
        m
        for m in g.logged(ev.GroupMoved)
        if m.polity == mine and m.group == cast.group and m.cause.value == "writing"
    ]
    assert len(moved) == 1 and moved[0].change > 0


@ON_EACH
def test_an_offer_is_made_and_accepted_and_its_clause_judged(
    games: dict[str, Game], cast: Cast
) -> None:
    g = game_of(games, cast)
    parties = {g.key(cast.attacker_nation), g.key(cast.defender_nation)}
    (made,) = [
        m.agreement for m in g.logged(ev.AgreementMade) if set(m.agreement.parties) == parties
    ]
    judged = [j for j in g.logged(ev.ClauseJudged) if j.agreement_id == made.agreement_id]
    assert [j.status.value for j in judged] == ["kept"]
    assert judged[0].on == made.clauses[0].on


@ON_EACH
def test_the_conference_tallies_with_the_absent_seat_given_the_fallback(
    games: dict[str, Game], cast: Cast
) -> None:
    g = game_of(games, cast)
    (tallied,) = [t for t in g.logged(ev.ConferenceTallied) if t.conference == g.played.conference]
    votes = {v.nation: v.vote.value for v in tallied.tally.votes}
    assert votes == {g.key(cast.attacker_nation): "for", g.key(cast.defender_nation): "abstain"}
    assert tallied.tally.outcome.value == "resolution"
    sealed = [v for v in g.logged(ev.VoteSealed) if v.conference == g.played.conference]
    assert [v.seat_id for v in sealed] == [g.attacker]
    assert g.played.away_day is not None and tallied.tally.on > g.played.away_day


@ON_EACH
def test_aims_are_scored_at_the_seasons_end(games: dict[str, Game], cast: Cast) -> None:
    g = game_of(games, cast)
    state = g.state
    for who, person in ((g.defender, cast.defender), (g.attacker, cast.attacker)):
        aims = [x for x in state.goals.values() if x.person == g.key(person)]
        assert len(aims) == 3, person
        stakes = seat_stakes(state, who, list(g.store.read(CAMPAIGN)))
        assert len(stakes["aims"]) == 3
        assert all(
            a["status"] in ("met", "at_risk", "failed") and a["reason"] for a in stakes["aims"]
        )
    (ended,) = g.logged(ev.SeasonEnded)
    assert set(ended.winners) == set(season_winners(state))
    assert set(ended.winners) <= {g.defender, g.attacker}


def test_no_model_is_reached_beyond_the_prose_and_the_offers(games: dict[str, Game]) -> None:
    """Every game ran on canned replies: the only calls the tick made were the prose and
    the wake's offers, each answered by a canned failure; the written orders were read by
    the script's own canned reader, and the statement named a theme, so no group call."""
    assert games
    assert set(ASKED) <= {"prose", "options"}, ASKED


# --- Rule 4: the guard's allow-list -----------------------------------------------------


ALLOW = Path(__file__).with_name("fixed_names_allow.txt")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "finding: nine lines still name an owner, not stored games only: production.py "
        "(until PRD, five lines), war_rules.py declare_war and detach_fleet (until EFD), "
        "uboat_directive and usa (until SHP); those items clear them"
    ),
)
def test_every_line_left_in_the_allow_list_is_for_stored_games_only() -> None:
    lines = [x for x in ALLOW.read_text().splitlines() if x.strip() and not x.startswith("#")]
    assert lines
    assert [x for x in lines if x.rsplit("|", 1)[1].strip() != "stored games only"] == []
