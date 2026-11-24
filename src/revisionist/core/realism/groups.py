"""Groups at home, defined by the world (GRP).

With ``groups`` switched on, a world may give each nation its groups at home: a key, a
name, a free label for its kind, a starting and a baseline support from 0 to 100, for a
chamber's bloc its chamber and seats, what it ``feeds`` (votes, standing, manpower,
output, opinion, each with a weight) and what it is ``moved_by`` (an amount for each of a
fixed list of happenings). A bloc also carries what the votes rule reads: its members
voting and yeas on each listed measure, a default for a measure the world does not list,
and a stance per clause kind.

``shift`` is the only way support moves, and every move is a ``group_moved`` event.
Support moves for three reasons, each in the day walk:

- what happened (rule 3): each listed happening moves the groups of the nation it
  happened to that name it, once;
- what was written (rule 2): writing reaches a group through ``propose`` and is settled
  in one batch a world day (``batch``), by content only: each seat contributes at most
  one change per group per day, the largest in magnitude among its proposals (ties to
  the smaller change, then the smaller text hash), clamped to ``GROUP_DAY_CAP``; when the
  contributions exceed what is left of ``GROUP_WEEK_CAP`` over the last
  ``WEEK_DAYS`` world days, what is left is shared in proportion to magnitude, in whole
  points by largest remainder, ties by seat key. A cap counts absolute influence: +2 and
  -2 use 4 points, and nothing restores the budget. No filing time, append order or
  clock-made id enters the batch;
- drift (rule 4): each Monday a group moves one point toward its baseline.

Groups feed the economy and the floor: a nation's manpower income is multiplied by
``manpower_factor``, its output income by ``output_factor`` (rule 5); ``home_standing``
is the weighted mean of the groups that feed standing plus the prestige the nation
holds (rule 6); ``bloc_support`` gives each bloc of a chamber its support (rule 7).

A nation's groups are seen by its own seats only (``seen_by``). A world with no groups,
or with the rule off, is unchanged (rule 8).

Classes (HCL). With ``classes`` on, a world may give each kind of happening a class:
felt, reported or secret, and for a mixed kind the share of it that is felt. The classes
ride the groups' declaration and are read only through ``cls``; a kind the world does not
class, and every kind with the rule off, is reported. A secret kind moves no group. A
measure passed is ``daily_life_passed`` when the nation's law under the measure's key
touches daily life, else ``measure_passed`` (``passed``), so a group may weigh the two
apart.

Losses (LSS). With ``losses`` on, the steps a nation lost in a day's battle rounds are a
happening of their own kind, ``battle_losses``, scaled by size: each group that names it
moves by its amount times the steps, capped at ``LOSSES_DAY_CAP`` points a day over all
the day's battles (``losses``). The kind is mixed unless the world classes it
(``LOSSES_FELT``): the reported share lands that day, the felt share in equal parts over
the ``FELT_DAYS`` days after (``landed``), held in state until it has landed. When a
battle ends, what its winner lost in it counts half: the difference lands that day as a
correction, and the felt share still held is halved. Losses at sea keep their own
monthly kind. What is held is engine only; a seat reads its own groups' moves.

Places (PLW). With ``places`` on, a world may weigh a handful of territories for a nation:
each moves that nation's groups by listed amounts. A place it held that changes hands is
lost (``place_lost``) by those amounts when a battle has ever opened there, else abandoned
(``place_abandoned``) by ``ABANDONED_TIMES`` them, or ``STOOD_TIMES`` when a piece of the
nation left it within ``STOOD_DAYS`` days; taken back (``place_retaken``) it moves them
back by the amounts (``places``). The seat of government stays the world's ``capital``:
a weighted seat raises ``capital_threatened`` and its own happening apart.

Free writing (FWG). A world may list ``themes`` for a nation: a theme and the points it
moves each of that nation's groups by. Writing that names a theme takes the moves from
that table, in code (``named_theme``, ``theme_nudges``). Writing that names none may be
read by the estimator, from the issuer's own view, into at most ``MAX_GROUP_EFFECTS``
group nudges: the issuer's own nation's groups by up to ``GROUP_DAY_CAP``, and another
nation's group only where the world marks it as hearing ``abroad``, by up to
``ABROAD_CAP`` (``nudge_problem``).
"""

import re
from collections.abc import Sequence
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, ClassVar

from pydantic import Field, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import AssetId, EntityId, SeatId
from revisionist.core.realism.effect import GROUP_DAY_CAP, ClauseKind, GroupNudge
from revisionist.core.realism.offers import Price

if TYPE_CHECKING:
    from revisionist.core.events import GroupMoved, GroupProposed, LossesHeld, Payload
    from revisionist.core.realism.battle import Battle
    from revisionist.core.state import State, View, _World

MAX_GROUP_EFFECTS = 3  # [proposed] plan, FWG Defaults
"""The most group nudges one ruling on a text may hold."""
ABROAD_CAP = 1  # plan, FWG rule 2
"""The most a nudge may move another nation's group that hears abroad, in points."""
GROUP_WEEK_CAP = 6  # [proposed] plan, GRP Defaults
"""The most all writing moves a group over ``WEEK_DAYS`` world days, in absolute points."""
WEEK_DAYS = 7
"""The window of the week cap: the day being settled and the six before it."""
DRIFT_POINTS = 1  # [proposed] plan, GRP Defaults
"""How far a group moves toward its baseline each Monday."""
MANPOWER_LOW = 0.8  # [proposed] plan, GRP Defaults
"""The manpower factor at support 0."""
MANPOWER_HIGH = 1.2  # [proposed] plan, GRP Defaults
"""The manpower factor at support 100."""
STRIKE_LINE = 30  # [proposed] plan, GRP Defaults
"""Below this weighted support of the groups that feed output, output pays less."""
STRIKE_SHARE = 0.9  # [proposed] plan, GRP Defaults
"""The share of output income paid below ``STRIKE_LINE``."""
LOSSES_DAY_CAP = 3  # [proposed] plan, LSS Defaults
"""The most one day's battle losses move one group, in points."""
FELT_DAYS = 21  # [proposed] plan, LSS Defaults
"""The days after a day's losses over which their felt share lands."""
LOSSES_FELT = 0.5  # [proposed] LSS: the contract says mixed and names no share
"""The share of battle losses that is felt when the world does not class the kind."""
ABANDONED_TIMES = 2  # plan, PLW rule 3
"""Abandoning a weighted place, with no battle opened there, against losing it."""
STOOD_TIMES = 3  # [proposed] plan, PLW rule 3
"""Abandoning it when a piece of the holder's left it within ``STOOD_DAYS`` days."""
STOOD_DAYS = 7  # [proposed] plan, PLW rule 3
TOP = 100

Support = Annotated[int, Field(ge=0, le=TOP)]
Weight = Annotated[float, Field(gt=0)]


class GroupsError(ValueError):
    """Writing the rules cannot take."""


class Feeds(StrEnum):
    """What a group's support feeds."""

    VOTES = "votes"
    STANDING = "standing"
    MANPOWER = "manpower"
    OUTPUT = "output"
    OPINION = "opinion"


class Happening(StrEnum):
    """The fixed list of happenings a group may be moved by (rule 3)."""

    BATTLE_WON = "battle_won"
    BATTLE_LOST = "battle_lost"
    TERRITORY_TAKEN = "territory_taken"
    TERRITORY_LOST = "territory_lost"
    CAPITAL_THREATENED = "capital_threatened"
    """THL's capital mark set on the territory of the nation's capital."""
    LOSSES_AT_SEA = "losses_at_sea"
    """On the first of a month: the nation's routes lost tonnage in the month before."""
    AGREEMENT_BROKEN = "agreement_broken"
    """Declared here, applied by the agreements item (``happened``)."""
    MEASURE_PASSED = "measure_passed"
    """Declared here, applied by the votes rule (``happened``)."""
    WAR_DECLARED = "war_declared"
    DAILY_LIFE_PASSED = "daily_life_passed"
    """With ``classes`` on, a measure passed that the world marks as touching daily life
    (HCL); with it off such a measure is a ``measure_passed``."""
    BATTLE_LOSSES = "battle_losses"
    """With ``losses`` on, the steps a nation lost in a day's battle rounds: a group moves
    by its amount a step (LSS, ``losses``)."""
    PLACE_LOST = "place_lost"
    """With ``places`` on, a weighted place lost where a battle opened (PLW). Its amounts
    are the world's ``places``, not a group's ``moved_by``; so for the two below."""
    PLACE_ABANDONED = "place_abandoned"
    """A weighted place that changed hands where no battle ever opened (PLW)."""
    PLACE_RETAKEN = "place_retaken"
    """A weighted place taken back by the nation it matters to (PLW)."""


class Class(StrEnum):
    """How a kind of happening reaches the groups at home (HCL)."""

    FELT = "felt"
    """Lived at home: the families feel it."""
    REPORTED = "reported"
    """Known at home by report."""
    SECRET = "secret"
    """Not known at home: it moves no group."""


class KindClass(Model):
    """The class the world gives a kind of happening (HCL), and the share of it that is
    felt: 1 for a felt kind, 0 for a reported one unless the world gives a share, which
    makes the kind mixed (that share felt, the rest reported). A secret kind has none."""

    kind: Happening
    reach: Class
    felt: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def _share(cls, data: object) -> object:
        if not isinstance(data, dict) or "reach" not in data:
            return data
        reach = Class(data["reach"])
        if "felt" not in data:
            return {**data, "felt": 1.0 if reach is Class.FELT else 0.0}
        felt = data["felt"]
        if reach is Class.SECRET and felt != 0:
            raise ValueError("a secret kind has no felt share")
        if reach is Class.FELT and felt != 1:
            raise ValueError("a felt kind is felt whole: a mixed kind is reported with a share")
        if reach is Class.REPORTED and felt == 1:
            raise ValueError("a kind felt whole is felt, not reported")
        return data

    @property
    def mixed(self) -> bool:
        """Part felt, the rest reported."""
        return 0 < self.felt < 1


class Cause(StrEnum):
    """Why support moved: a happening, writing, or the Monday drift."""

    BATTLE_WON = "battle_won"
    BATTLE_LOST = "battle_lost"
    TERRITORY_TAKEN = "territory_taken"
    TERRITORY_LOST = "territory_lost"
    CAPITAL_THREATENED = "capital_threatened"
    LOSSES_AT_SEA = "losses_at_sea"
    AGREEMENT_BROKEN = "agreement_broken"
    MEASURE_PASSED = "measure_passed"
    WAR_DECLARED = "war_declared"
    DAILY_LIFE_PASSED = "daily_life_passed"
    WRITING = "writing"
    DRIFT = "drift"
    OFFER_TAKEN = "offer_taken"
    """An offer of a price taken by a bloc (PRC)."""
    PROMISE_KEPT = "promise_kept"
    """A promise made to a bloc kept on its due day (PRC)."""
    PROMISE_BROKEN = "promise_broken"
    """A promise made to a bloc unmet on its due day (PRC)."""
    BATTLE_LOSSES = "battle_losses"
    """The reported share of a day's battle losses, that day (LSS)."""
    LOSSES_FELT = "losses_felt"
    """A part of the felt share of earlier battle losses arriving (LSS)."""
    LOSSES_HALVED = "losses_halved"
    """A battle won: what the nation lost in it counting half from the day it ended (LSS)."""
    PLACE_LOST = "place_lost"
    """A weighted place lost where a battle opened (PLW)."""
    PLACE_ABANDONED = "place_abandoned"
    """A weighted place abandoned with no battle opened there (PLW)."""
    PLACE_RETAKEN = "place_retaken"
    """A weighted place taken back (PLW)."""


class BlocVote(Model):
    """A bloc's part of one chamber vote: its members voting and the yeas among them."""

    voting: int = Field(ge=0)
    yeas: int = Field(ge=0)

    @model_validator(mode="after")
    def _within(self) -> "BlocVote":
        if self.yeas > self.voting:
            raise ValueError("a bloc's yeas are among its members voting")
        return self


class Group(Model):
    """A group at home as the world declares it. True: a view holds its own nation's."""

    key: Label
    name: Label
    kind: Label
    """A free label: a party, a union, a service, the public."""
    start: Support
    baseline: Support
    chamber: Label | None = None
    """For a chamber's bloc, the chamber's key; with ``seats``."""
    seats: int | None = Field(default=None, ge=1)
    feeds: dict[Feeds, Weight] = Field(default_factory=dict)
    moved_by: dict[Happening, int] = Field(default_factory=dict)
    """The points each happening moves the group by, signed."""
    votes: dict[Label, dict[Label, BlocVote]] = Field(default_factory=dict)
    """A bloc's part of each vote of each measure the world lists: by measure, then by
    vote (for example ``house``, ``senate``, ``concur``)."""
    vote_default: dict[Label, BlocVote] = Field(default_factory=dict)
    """A bloc's part of each vote of a measure the world does not list, by vote."""
    stances: dict[ClauseKind, int] = Field(default_factory=dict)
    """A bloc's stance on each kind of clause, in points toward yes."""
    abroad: bool = False
    """The group hears another nation's writing: a nudge from abroad may move it by up to
    ``ABROAD_CAP`` (FWG)."""
    prices: tuple[Price, ...] = ()
    """What a chamber's bloc will take for its votes on a measure, in the world's order
    (PRC): read with ``offers`` on."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"abroad", "prices"})

    @model_validator(mode="after")
    def _bloc(self) -> "Group":
        if (self.chamber is None) != (self.seats is None):
            raise ValueError("a bloc names its chamber and its seats together")
        if self.chamber is None and (self.votes or self.vote_default or self.stances):
            raise ValueError("only a chamber's bloc has votes and stances")
        if self.chamber is None and self.prices:
            raise ValueError("only a chamber's bloc has prices")
        return self


class Theme(Model):
    """A theme a nation's writing may name, and the points it moves each of that nation's
    groups by, signed (FWG rule 3)."""

    key: Label
    name: Label
    moves: dict[Label, Annotated[int, Field(ge=-GROUP_DAY_CAP, le=GROUP_DAY_CAP)]] = Field(
        min_length=1
    )

    @model_validator(mode="after")
    def _moves(self) -> "Theme":
        if 0 in self.moves.values():
            raise ValueError("a theme moves each group it lists")
        return self


class Place(Model):
    """A place with political weight (PLW): a territory, the nation it matters to, and the
    points each of that nation's groups moves when it is lost in a fight, signed."""

    territory: EntityId
    nation: EntityId
    moves: dict[Label, int] = Field(min_length=1)

    @model_validator(mode="after")
    def _moves(self) -> "Place":
        if 0 in self.moves.values():
            raise ValueError("a place moves each group it lists")
        return self


class NationGroups(Model):
    """One nation's groups at home, in the world file's order, and its themes."""

    nation: EntityId
    groups: tuple[Group, ...] = Field(min_length=1)
    themes: tuple[Theme, ...] = ()

    late_fields: ClassVar[frozenset[str]] = frozenset({"themes"})

    @model_validator(mode="after")
    def _keys(self) -> "NationGroups":
        keys = [g.key for g in self.groups]
        if len(set(keys)) != len(keys):
            raise ValueError("a nation's group keys are distinct")
        themes = [t.key for t in self.themes]
        if len(set(themes)) != len(themes):
            raise ValueError("a nation's theme keys are distinct")
        if any(k not in keys for t in self.themes for k in t.moves):
            raise ValueError("a theme moves only the nation's own groups")
        return self


class Proposal(Model):
    """One seat's writing proposing to move a group (rule 2). Engine only: it carries a
    hash of the text, never the text, and no filing time."""

    seat: SeatId
    polity: EntityId
    group: Label
    change: int
    text_hash: Label
    on: date
    """The world day the writing reached the group: the day of the batch."""


class Spent(Model):
    """Writing points a group's batch used on a day, toward the week cap."""

    on: date
    points: int = Field(ge=0)


class HeldLoss(Model):
    """One day's losses of a nation in one battle as they move one of its groups (LSS):
    the reported share, which landed that day, and the felt share, which lands over the
    ``FELT_DAYS`` days after. ``ended``: the battle has ended, so no correction is still to
    come. Engine only."""

    polity: EntityId
    group: Label
    area: EntityId
    opened: date
    """With ``area``, the battle: the day it opened."""
    on: date
    reported: int
    felt: int
    ended: bool = False

    def key(self) -> tuple[EntityId, str, EntityId, date, date]:
        return (self.polity, self.group, self.area, self.opened, self.on)


class Election(Model):
    """An election the world lists (ELE), with ``elections`` on: the nation, the chambers
    it redraws, its day, and the post whose term ends that day, if any. Engine only: the
    post's day is told by its office question's notice."""

    nation: EntityId
    chambers: tuple[Label, ...] = Field(min_length=1, max_length=4)
    day: date
    post: AssetId | None = None


class Groups(Model):
    """Groups' truth. A seat sees its own nation's part only."""

    declared: dict[EntityId, tuple[Group, ...]] = Field(default_factory=dict)
    """Each nation's groups, in the world file's order (``groups_declared``)."""
    support: dict[EntityId, dict[Label, Support]] = Field(default_factory=dict)
    """Each nation's groups' support now, by group key (``group_moved``)."""
    spent: dict[EntityId, dict[Label, tuple[Spent, ...]]] = Field(default_factory=dict)
    """The writing points each group's batches used over the last ``WEEK_DAYS`` days."""
    proposed: tuple[Proposal, ...] = ()
    """Writing not yet settled (``group_proposed``). Engine only."""
    themes: dict[EntityId, tuple[Theme, ...]] = Field(default_factory=dict)
    """Each nation's themes, in the world file's order (``groups_declared``)."""
    classes: dict[Happening, KindClass] = Field(default_factory=dict)
    """With ``classes`` on, the class of each kind the world classes (``groups_declared``):
    public rules of the world. Read through ``cls``."""
    held: tuple[HeldLoss, ...] = ()
    """With ``losses`` on, battle losses whose felt share has still to land, or whose
    battle has still to end (``losses_held``). Engine only."""
    places: tuple[Place, ...] = ()
    """With ``places`` on, the places with political weight, in the world file's order
    (``groups_declared``). A seat sees its own nation's."""
    left: dict[EntityId, dict[EntityId, date]] = Field(default_factory=dict)
    """With ``places`` on, by weighted place, the last day a piece of each nation stepped
    out of it (``piece_stepped``). Engine only."""
    elections: tuple[Election, ...] = ()
    """With ``elections`` on, the elections the world lists, in the world file's order
    (``groups_declared``). Engine only."""

    late_fields: ClassVar[frozenset[str]] = frozenset(
        {"themes", "classes", "held", "places", "left", "elections"}
    )


# --- reading ------------------------------------------------------------------------


def on(state: "_World") -> bool:
    """Whether groups act in this game: the ``groups`` rule on."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.GROUPS in rules


_rule_on = on  # for ``propose``, whose day parameter is named ``on``


def classes_on(state: "_World") -> bool:
    """Whether happenings have classes in this game: the ``classes`` rule on."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.CLASSES in rules


def places_on(state: "_World") -> bool:
    """Whether places with political weight move groups: the ``places`` rule on."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.PLACES in rules


def losses_on(state: "_World") -> bool:
    """Whether the size of battle losses moves groups: the ``losses`` rule on."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.LOSSES in rules


def cls(state: "State | View", happening: Happening) -> KindClass:
    """The class of a kind of happening: the one place a rule reads it (HCL rule 4). With
    ``classes`` on, the world's class; a kind the world does not class, and every kind
    with the rule off, is reported, felt by none, except battle losses, which are mixed,
    ``LOSSES_FELT`` of them felt (LSS rule 3)."""
    found = state.groups.classes.get(happening) if classes_on(state) else None
    if found is not None:
        return found
    if happening is Happening.BATTLE_LOSSES:
        return KindClass(kind=happening, reach=Class.REPORTED, felt=LOSSES_FELT)
    return KindClass(kind=happening, reach=Class.REPORTED)


def _heard(state: "State | View", happening: Happening) -> bool:
    """Whether a happening reaches the groups at all: any but a secret kind (rule 2)."""
    return cls(state, happening).reach is not Class.SECRET


def of(state: "State | View", polity: EntityId) -> tuple[Group, ...]:
    """A nation's declared groups, in the world's order. None in a game with the rule off:
    ``groups_declared`` lands only with it on. A view holds its own nation's only."""
    return state.groups.declared.get(polity, ())


def group(state: "State | View", polity: EntityId, key: str) -> Group | None:
    return next((g for g in of(state, polity) if g.key == key), None)


def support(state: "State | View", polity: EntityId, key: str) -> int | None:
    """A group's support now; None when the nation has no such group."""
    found = group(state, polity, key)
    if found is None:
        return None
    return state.groups.support.get(polity, {}).get(key, found.start)


def _mean(state: "State | View", polity: EntityId, feed: Feeds) -> float | None:
    """The weighted mean support of the nation's groups that feed ``feed``; None when
    none does."""
    weights = [(g, g.feeds[feed]) for g in of(state, polity) if feed in g.feeds]
    total = sum(w for _, w in weights)
    if not weights or total <= 0:
        return None
    return sum((support(state, polity, g.key) or 0) * w for g, w in weights) / total


def manpower_factor(state: "State | View", polity: EntityId) -> float:
    """What a nation's manpower income is multiplied by (rule 5): from ``MANPOWER_LOW``
    at support 0 to ``MANPOWER_HIGH`` at 100, over the groups that feed manpower; 1 when
    none does."""
    mean = _mean(state, polity, Feeds.MANPOWER)
    if mean is None:
        return 1.0
    return round(MANPOWER_LOW + (MANPOWER_HIGH - MANPOWER_LOW) * mean / TOP, 6)


def output_factor(state: "State | View", polity: EntityId) -> float:
    """What a nation's output income is multiplied by (rule 5): ``STRIKE_SHARE`` while the
    groups that feed output stand below ``STRIKE_LINE``, weighted; else 1."""
    mean = _mean(state, polity, Feeds.OUTPUT)
    return STRIKE_SHARE if mean is not None and mean < STRIKE_LINE else 1.0


def home_standing(state: "State | View", polity: EntityId, day: date | None = None) -> float | None:
    """A nation's standing at home (rule 6): the weighted mean of the groups that feed
    standing, plus the prestige income it holds on ``day`` (default: the in-world date),
    clamped to 0 to 100, one decimal. None when no group feeds standing."""
    from revisionist.core.realism import economy
    from revisionist.core.realism.kinds import Role

    mean = _mean(state, polity, Feeds.STANDING)
    if mean is None:
        return None
    today = state.in_world_date if day is None else day
    prestige = 0.0
    if economy.on(state) and today is not None:
        prestige = economy.income(state, polity, Role.PRESTIGE, today)
    return round(max(0.0, min(float(TOP), mean + prestige)), 1)


def bloc_support(state: "State | View", polity: EntityId, chamber: str) -> dict[str, int]:
    """Each bloc of a nation's chamber, by key: its support now (rule 7)."""
    return {
        g.key: support(state, polity, g.key) or 0 for g in of(state, polity) if g.chamber == chamber
    }


def _scaled(vote: BlocVote, old: int, new: int) -> BlocVote:
    voting = min(new, (vote.voting * new + old // 2) // old)
    return BlocVote(voting=voting, yeas=min(voting, (vote.yeas * new + old // 2) // old))


def reseated(bloc: Group, seats: int) -> Group:
    """A chamber's bloc with ``seats``, each row of its votes scaled by its new seats over
    its old, to the nearest member, halves up (ELE)."""
    old = bloc.seats
    if old is None or old == seats:
        return bloc
    return bloc.model_copy(
        update={
            "seats": seats,
            "votes": {
                m: {v: _scaled(row, old, seats) for v, row in rows.items()}
                for m, rows in bloc.votes.items()
            },
            "vote_default": {v: _scaled(row, old, seats) for v, row in bloc.vote_default.items()},
        }
    )


def seen_by(state: "State", seat: SeatId) -> Groups:
    """What ``seat`` sees of the groups: its own nation's groups, support and spent
    points, and the classes of happenings; no writing in waiting. Nothing for a seat of
    no nation."""
    from revisionist.core.realism.war import polity_of

    me = state.seats.get(seat)
    own = polity_of(state, me.embodies) if me is not None else None
    if own is None:
        return Groups()
    g = state.groups
    return Groups(
        declared={k: v for k, v in g.declared.items() if k == own},
        support={k: v for k, v in g.support.items() if k == own},
        spent={k: v for k, v in g.spent.items() if k == own},
        themes={k: v for k, v in g.themes.items() if k == own},
        classes=g.classes,
        places=tuple(p for p in g.places if p.nation == own),
    )


# --- free writing (FWG) ---------------------------------------------------------------


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


def named_theme(state: "State | View", polity: EntityId, text: str) -> Theme | None:
    """The first of a nation's themes, in the world's order, whose name or key the text
    names as whole words (rule 4); None when it names none."""
    said = f" {_words(text)} "
    for theme in state.groups.themes.get(polity, ()):
        for phrase in (_words(theme.name), _words(theme.key)):
            if phrase and f" {phrase} " in said:
                return theme
    return None


def theme_nudges(polity: EntityId, theme: Theme) -> tuple[GroupNudge, ...]:
    """What a theme moves, as group nudges of its nation, in the table's order."""
    return tuple(
        GroupNudge(nation=polity, group=key, change=change) for key, change in theme.moves.items()
    )


def nudge_problem(state: "State", issuer: EntityId | None, nudge: GroupNudge) -> str:
    """Why a nudge from ``issuer``'s nation may not land, or "" when it may (rule 2): a
    group the nation does not have, or another nation's group not marked as hearing
    abroad, or moved past ``ABROAD_CAP``."""
    found = group(state, nudge.nation, nudge.group)
    if not on(state) or found is None:
        return f"no group {nudge.group} at home in {nudge.nation}"
    if nudge.nation == issuer:
        return ""
    if not found.abroad:
        return f"{nudge.group} does not hear writing from abroad"
    if abs(nudge.change) > ABROAD_CAP:
        return f"{nudge.group} hears writing from abroad by {ABROAD_CAP} at most"
    return ""


# --- moving ---------------------------------------------------------------------------


def _moved(
    was: int,
    polity: EntityId,
    key: str,
    change: int,
    cause: Cause,
    day: date,
    used: int = 0,
) -> "GroupMoved":
    from revisionist.core import events as ev

    now = max(0, min(TOP, was + change))
    return ev.GroupMoved(
        polity=polity, group=key, support=now, change=now - was, cause=cause, used=used, on=day
    )


def shift(
    state: "State", polity: EntityId, key: str, change: int, cause: Cause, on: date
) -> "GroupMoved":
    """The only way support moves: the ``group_moved`` that moves a nation's group by
    ``change`` points, clamped to 0 to 100. Raises ``GroupsError`` for a group the nation
    does not have."""
    was = support(state, polity, key)
    if was is None:
        raise GroupsError(f"no group {key} at home in {polity}")
    return _moved(was, polity, key, change, cause, on)


def happened(
    state: "State", polity: EntityId, happening: Happening, on: date
) -> list["GroupMoved"]:
    """A happening to a nation moves each of its groups that names it, once, in the
    world's order (rule 3). For the happenings another rule decides: an agreement broken
    (AGR) and a measure passed (the votes rule). A secret kind moves none."""
    if not _heard(state, happening):
        return []
    return [
        shift(state, polity, g.key, g.moved_by[happening], Cause(happening.value), on)
        for g in of(state, polity)
        if g.moved_by.get(happening)
    ]


def passed(state: "State", polity: EntityId, measure: str, on: date) -> list["GroupMoved"]:
    """A nation's measure ``measure`` passed (rule 3): with ``classes`` on, a law of that
    nation the world declares under the measure's key and marks as touching daily life
    raises ``daily_life_passed``; any other measure, and every measure with the rule off,
    ``measure_passed``."""
    daily = classes_on(state) and any(
        law.daily_life for law in state.laws if law.key == measure and law.nation == polity
    )
    kind = Happening.DAILY_LIFE_PASSED if daily else Happening.MEASURE_PASSED
    return happened(state, polity, kind, on)


def propose(
    state: "State",
    seat: SeatId,
    polity: EntityId,
    key: str,
    change: int,
    text_hash: str,
    on: date,
) -> "GroupProposed":
    """Writing by ``seat`` that proposes to move a nation's group by ``change`` on world
    day ``on``: the ``group_proposed`` to land. The day's batch settles it (rule 2).
    Raises ``GroupsError`` when the rule is off, the group or the seat is unknown."""
    from revisionist.core import events as ev

    if not _rule_on(state):
        raise GroupsError("the groups rule is off")
    if group(state, polity, key) is None:
        raise GroupsError(f"no group {key} at home in {polity}")
    if seat not in state.seats:
        raise GroupsError(f"no seat {seat}")
    return ev.GroupProposed(
        proposal=Proposal(
            seat=seat, polity=polity, group=key, change=change, text_hash=text_hash, on=on
        )
    )


def used(state: "State | View", polity: EntityId, key: str, day: date) -> int:
    """The writing points a group's batches used in the ``WEEK_DAYS`` days to ``day``."""
    first = day - timedelta(days=WEEK_DAYS - 1)
    return sum(
        s.points for s in state.groups.spent.get(polity, {}).get(key, ()) if first <= s.on <= day
    )


def _chosen(proposals: Sequence[Proposal]) -> Proposal:
    """A seat's one proposal for a group: the largest in magnitude, ties to the smaller
    change, then to the smaller text hash."""
    return min(proposals, key=lambda p: (-abs(p.change), p.change, p.text_hash))


def _shared[K: str | tuple[EntityId, date]](contributions: dict[K, int], left: int) -> dict[K, int]:
    """The contributions within ``left`` points: as they are when they fit, else ``left``
    shared in proportion to magnitude, in whole points by largest remainder, ties by seat
    key; each keeps its sign."""
    total = sum(abs(c) for c in contributions.values())
    if total <= left:
        return dict(contributions)
    if left <= 0:
        return dict.fromkeys(contributions, 0)
    whole = {s: left * abs(c) // total for s, c in contributions.items()}
    rest = {s: left * abs(c) % total for s, c in contributions.items()}
    over = left - sum(whole.values())
    for s in sorted(contributions, key=lambda s: (-rest[s], s))[:over]:
        whole[s] += 1
    return {s: whole[s] if c > 0 else -whole[s] for s, c in contributions.items()}


def batch(state: "State", day: date) -> list["GroupMoved"]:
    """The day's writing, settled (rule 2): one ``group_moved`` for each group with
    writing in waiting on or before ``day``, by nation then group key."""
    if not on(state):
        return []
    pending: dict[tuple[EntityId, str], dict[SeatId, list[Proposal]]] = {}
    for p in state.groups.proposed:
        if p.on <= day:
            pending.setdefault((p.polity, p.group), {}).setdefault(p.seat, []).append(p)
    out: list[GroupMoved] = []
    for (polity, key), by_seat in sorted(pending.items()):
        was = support(state, polity, key)
        if was is None:
            continue
        contributions = {
            seat: max(-GROUP_DAY_CAP, min(GROUP_DAY_CAP, _chosen(found).change))
            for seat, found in sorted(by_seat.items())
        }
        left = max(0, GROUP_WEEK_CAP - used(state, polity, key, day))
        shares = _shared(contributions, left)
        net = sum(shares.values())
        spent = sum(abs(v) for v in shares.values())
        out.append(_moved(was, polity, key, net, Cause.WRITING, day, used=spent))
    return out


def _held_happenings(
    start: "State", payloads: Sequence["Payload"], day: date
) -> list[tuple[EntityId, Happening]]:
    """Each happening in ``payloads`` (a day's events, in order) to the nation it
    happened to; ``start`` is the state before them."""
    from revisionist.core import events as ev
    from revisionist.core.realism import holders

    out: list[tuple[EntityId, Happening]] = []
    opened = dict(start.battles)
    marked = {k: c.marked is not None for k, c in start.captures.items()}
    for p in payloads:
        if isinstance(p, ev.WarDeclared):
            out += [(p.war.a, Happening.WAR_DECLARED), (p.war.b, Happening.WAR_DECLARED)]
        elif isinstance(p, ev.BattleOpened):
            opened[p.battle.area] = p.battle
        elif isinstance(p, ev.BattleEnded):
            out.append((p.winner, Happening.BATTLE_WON))
            fought = opened.get(p.area)
            if fought is not None:
                sides = {fought.attacker.nation, fought.defender.nation} - {p.winner}
                out += [(n, Happening.BATTLE_LOST) for n in sorted(sides)]
        elif isinstance(p, ev.AreaHeld):
            out.append((p.holder, Happening.TERRITORY_TAKEN))
            if p.was is not None and p.was != p.holder:
                out.append((p.was, Happening.TERRITORY_LOST))
        elif isinstance(p, ev.CaptureCounted):
            now = p.capture is not None and p.capture.marked is not None
            if now and not marked.get(p.area, False):
                out += [
                    (n, Happening.CAPITAL_THREATENED) for n in holders.capitals_in(start, p.area)
                ]
            marked[p.area] = now
    return out


def _sea_losses(state: "State", day: date) -> list[tuple[EntityId, Happening]]:
    """On the first of a month: each nation whose routes lost tonnage in the month before
    (the shipping rule's ``losses``, read only)."""
    from revisionist.core.realism import territory
    from revisionist.core.realism.resolvers import shipping

    if day.day != 1 or state.map is None:
        return []
    lost: set[EntityId] = set()
    for fid, tons in shipping.losses(state, day - timedelta(days=1)).items():
        route = state.features.get(fid)
        nation = None if route is None else territory.nation(state, route.side)
        if tons > 0 and nation is not None:
            lost.add(nation)
    return [(n, Happening.LOSSES_AT_SEA) for n in sorted(lost)]


def react(
    state: "State",
    start: "State",
    payloads: Sequence["Payload"],
    day: date,
    *,
    sea: "State | None" = None,
) -> list["GroupMoved"]:
    """With ``groups`` on, each happening in ``payloads`` (events in order; ``start`` is
    the state before them), and on the first of a month, given ``sea`` (the state the
    shipping rule sank from that day), the month's losses at sea, moves the groups of the
    nation it happened to that name it, once (rule 3): one ``group_moved`` for each group
    and kind of happening, the amount times how often it happened, by nation, then kind,
    then the world's order of groups."""
    if not on(state) or not state.groups.declared:
        return []
    found = _held_happenings(start, payloads, day)
    if sea is not None:
        found += _sea_losses(sea, day)
    counts: dict[tuple[EntityId, Happening], int] = {}
    for one in found:
        if _heard(state, one[1]):
            counts[one] = counts.get(one, 0) + 1
    order = list(Happening)
    now: dict[tuple[EntityId, str], int] = {}
    out: list[GroupMoved] = []
    for (polity, what), n in sorted(counts.items(), key=lambda x: (x[0][0], order.index(x[0][1]))):
        for g in of(state, polity):
            amount = g.moved_by.get(what, 0) * n
            if not amount:
                continue
            was = now.get((polity, g.key), support(state, polity, g.key) or 0)
            moved = _moved(was, polity, g.key, amount, Cause(what.value), day)
            now[(polity, g.key)] = moved.support
            if moved.change:
                out.append(moved)
    return out


def places(
    state: "State", start: "State", payloads: Sequence["Payload"], day: date
) -> list["GroupMoved"]:
    """With ``places`` on, each weighted place that changes hands in ``payloads`` (a day's
    events, in order; ``start`` is the state before them) moves the groups of the nation
    it matters to (PLW rule 2), in the order of the changes, then the world's order of
    groups: held by that nation and lost where a battle has opened, by the amounts; lost
    where none has, abandoned, by ``ABANDONED_TIMES`` them, ``STOOD_TIMES`` when a piece
    of the nation stepped out of it within ``STOOD_DAYS`` days; taken by that nation, back
    by the amounts. A secret kind moves none."""
    from revisionist.core import events as ev

    if not on(state) or not state.groups.places:
        return []
    fought = set(start.fought)
    left = {area: dict(by) for area, by in start.groups.left.items()}
    found: list[tuple[Place, Happening, int]] = []
    for p in payloads:
        if isinstance(p, ev.BattleOpened):
            fought.update(a for a in (p.battle.area, p.battle.second) if a is not None)
        elif isinstance(p, ev.PieceStepped):
            left.setdefault(p.left, {})[p.nation] = p.on
        elif isinstance(p, ev.AreaHeld) and p.was is not None and p.was != p.holder:
            for place in state.groups.places:
                if place.territory != p.area:
                    continue
                if place.nation == p.holder:
                    found.append((place, Happening.PLACE_RETAKEN, -1))
                elif place.nation != p.was:
                    continue
                elif p.area in fought:
                    found.append((place, Happening.PLACE_LOST, 1))
                else:
                    out_on = left.get(p.area, {}).get(p.was)
                    stood = out_on is not None and (day - out_on).days <= STOOD_DAYS
                    times = STOOD_TIMES if stood else ABANDONED_TIMES
                    found.append((place, Happening.PLACE_ABANDONED, times))
    now: dict[tuple[EntityId, str], int] = {}
    out: list[GroupMoved] = []
    for place, what, times in found:
        if not _heard(state, what):
            continue
        for g in of(state, place.nation):
            amount = place.moves.get(g.key, 0) * times
            if not amount:
                continue
            was = now.get((place.nation, g.key), support(state, place.nation, g.key) or 0)
            moved = _moved(was, place.nation, g.key, amount, Cause(what.value), day)
            now[(place.nation, g.key)] = moved.support
            if moved.change:
                out.append(moved)
    return out


def landed(felt: int, days: int) -> int:
    """The part of a felt share landed ``days`` days after the day of the losses: equal
    parts over ``FELT_DAYS`` days, in whole points, rounded half away from zero."""
    n = max(0, min(FELT_DAYS, days))
    whole = (2 * abs(felt) * n + FELT_DAYS) // (2 * FELT_DAYS)
    return whole if felt >= 0 else -whole


def _half(points: int) -> int:
    """Half of ``points``, rounded half away from zero: a loss never vanishes by halving."""
    whole = (abs(points) + 1) // 2
    return whole if points >= 0 else -whole


def _fought(
    start: "State", payloads: Sequence["Payload"]
) -> tuple[list[tuple[EntityId, "Battle", int]], list[tuple["Battle", EntityId]]]:
    """Each side's steps lost in ``payloads`` (a day's events, in order), by its leading
    nation and battle, and each battle that ended with its winner; ``start`` is the state
    before them."""
    from revisionist.core import events as ev

    opened = dict(start.battles)
    rounds: list[tuple[EntityId, Battle, int]] = []
    ended: list[tuple[Battle, EntityId]] = []
    for p in payloads:
        if isinstance(p, ev.BattleOpened):
            opened[p.battle.area] = p.battle
        elif isinstance(p, ev.BattleRound) and p.area in opened:
            fought = opened[p.area]
            for side, steps in ((fought.attacker, p.lost[0]), (fought.defender, p.lost[1])):
                if steps:
                    rounds.append((side.nation, fought, steps))
        elif isinstance(p, ev.BattleEnded) and p.area in opened:
            ended.append((opened[p.area], p.winner))
    return rounds, ended


def losses(
    state: "State", start: "State", payloads: Sequence["Payload"], day: date
) -> list["GroupMoved | LossesHeld"]:
    """With ``groups`` and ``losses`` on, the day's battle losses at home (LSS): first the
    felt shares held that fall due today (``losses_felt``); then each group that names
    ``battle_losses`` moved by its amount times the steps its nation lost in each of the
    day's rounds (``payloads``, the day's events; ``start``, the state before them), the
    day's sum over all battles held to ``LOSSES_DAY_CAP`` and shared among them by size;
    the reported share lands now (``battle_losses``) and every share is held
    (``losses_held``). Last, for each battle that ended today, what its winner lost in it
    counts half (``losses_halved``). A secret kind moves nobody and holds nothing."""
    from revisionist.core import events as ev

    if not on(state) or not losses_on(state) or not state.groups.declared:
        return []
    now: dict[tuple[EntityId, str], int] = {}
    out: list[GroupMoved | LossesHeld] = []

    def move(polity: EntityId, key: str, change: int, cause: Cause) -> None:
        was = now.get((polity, key), support(state, polity, key))
        if not change or was is None:
            return
        moved = _moved(was, polity, key, change, cause, day)
        now[(polity, key)] = moved.support
        if moved.change:
            out.append(moved)

    arriving: dict[tuple[EntityId, str], int] = {}
    for h in state.groups.held:
        after = (day - h.on).days
        part = landed(h.felt, after) - landed(h.felt, after - 1)
        if part:
            arriving[(h.polity, h.group)] = arriving.get((h.polity, h.group), 0) + part
    for (polity, key), part in sorted(arriving.items()):
        move(polity, key, part, Cause.LOSSES_FELT)

    kind = cls(state, Happening.BATTLE_LOSSES)
    rounds, ended = _fought(start, payloads)
    held: dict[tuple[EntityId, str, EntityId, date, date], HeldLoss] = {
        h.key(): h for h in state.groups.held
    }
    changed: dict[tuple[EntityId, str, EntityId, date, date], HeldLoss] = {}
    if kind.reach is not Class.SECRET:
        cost: dict[tuple[EntityId, str], dict[tuple[EntityId, date], int]] = {}
        for nation, fought, steps in rounds:
            for g in of(state, nation):
                amount = g.moved_by.get(Happening.BATTLE_LOSSES, 0) * steps
                if amount:
                    by = cost.setdefault((nation, g.key), {})
                    at = (fought.area, fought.opened)
                    by[at] = by.get(at, 0) + amount
        for (polity, key), by_battle in sorted(cost.items()):
            reported = 0
            for (area, opened), points in sorted(_shared(by_battle, LOSSES_DAY_CAP).items()):
                felt = int(round(points * kind.felt, 6))
                one = HeldLoss(
                    polity=polity,
                    group=key,
                    area=area,
                    opened=opened,
                    on=day,
                    reported=points - felt,
                    felt=felt,
                )
                held[one.key()] = changed[one.key()] = one
                reported += one.reported
            move(polity, key, reported, Cause.BATTLE_LOSSES)

    back: dict[tuple[EntityId, str], int] = {}
    for fought, winner in ended:
        mine: dict[tuple[EntityId, str], list[HeldLoss]] = {}
        for k, h in sorted(held.items()):
            if (h.area, h.opened) != (fought.area, fought.opened) or h.ended:
                continue
            if h.polity == winner:
                mine.setdefault((h.polity, h.group), []).append(h)
            held[k] = changed[k] = h.model_copy(update={"ended": True})
        for (polity, key), found in sorted(mine.items()):
            target = _half(sum(h.reported + h.felt for h in found))
            halved = [_half(h.felt) for h in found]
            change = target - sum(halved) - sum(h.reported for h in found)
            for h, felt in zip(found, halved, strict=True):
                after = (day - h.on).days
                change += landed(felt, after) - landed(h.felt, after)
                held[h.key()] = changed[h.key()] = h.model_copy(
                    update={"felt": felt, "ended": True}
                )
            back[(polity, key)] = back.get((polity, key), 0) + change
    for (polity, key), change in sorted(back.items()):
        move(polity, key, change, Cause.LOSSES_HALVED)
    if changed:
        out.append(ev.LossesHeld(on=day, held=tuple(v for _, v in sorted(changed.items()))))
    return out


def drift(state: "State", day: date) -> list["GroupMoved"]:
    """Each Monday, every group off its baseline moves ``DRIFT_POINTS`` toward it (rule 4)."""
    if not on(state) or day.weekday() != 0:
        return []
    out: list[GroupMoved] = []
    for polity, found in sorted(state.groups.declared.items()):
        for g in found:
            was = support(state, polity, g.key) or 0
            if was == g.baseline:
                continue
            step = min(DRIFT_POINTS, abs(g.baseline - was))
            change = step if g.baseline > was else -step
            out.append(_moved(was, polity, g.key, change, Cause.DRIFT, day))
    return out


__all__ = [
    "ABROAD_CAP",
    "DRIFT_POINTS",
    "FELT_DAYS",
    "GROUP_DAY_CAP",
    "GROUP_WEEK_CAP",
    "LOSSES_DAY_CAP",
    "LOSSES_FELT",
    "MANPOWER_HIGH",
    "MANPOWER_LOW",
    "MAX_GROUP_EFFECTS",
    "STRIKE_LINE",
    "STRIKE_SHARE",
    "WEEK_DAYS",
    "BlocVote",
    "Cause",
    "Class",
    "Feeds",
    "Group",
    "Groups",
    "GroupsError",
    "Happening",
    "HeldLoss",
    "KindClass",
    "NationGroups",
    "Proposal",
    "Spent",
    "Theme",
    "batch",
    "bloc_support",
    "classes_on",
    "cls",
    "drift",
    "group",
    "happened",
    "home_standing",
    "landed",
    "losses",
    "losses_on",
    "manpower_factor",
    "named_theme",
    "nudge_problem",
    "of",
    "on",
    "output_factor",
    "passed",
    "propose",
    "react",
    "seen_by",
    "shift",
    "support",
    "theme_nudges",
    "used",
]
