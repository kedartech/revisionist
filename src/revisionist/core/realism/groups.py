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
from revisionist.core.ids import EntityId, SeatId
from revisionist.core.realism.effect import GROUP_DAY_CAP, ClauseKind, GroupNudge

if TYPE_CHECKING:
    from revisionist.core.events import GroupMoved, GroupProposed, Payload
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
    WRITING = "writing"
    DRIFT = "drift"


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

    late_fields: ClassVar[frozenset[str]] = frozenset({"abroad"})

    @model_validator(mode="after")
    def _bloc(self) -> "Group":
        if (self.chamber is None) != (self.seats is None):
            raise ValueError("a bloc names its chamber and its seats together")
        if self.chamber is None and (self.votes or self.vote_default or self.stances):
            raise ValueError("only a chamber's bloc has votes and stances")
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

    late_fields: ClassVar[frozenset[str]] = frozenset({"themes"})


# --- reading ------------------------------------------------------------------------


def on(state: "_World") -> bool:
    """Whether groups act in this game: the ``groups`` rule on."""
    from revisionist.core.state import Rule

    rules: frozenset[Rule] = getattr(state, "rules", frozenset())
    return Rule.GROUPS in rules


_rule_on = on  # for ``propose``, whose day parameter is named ``on``


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


def seen_by(state: "State", seat: SeatId) -> Groups:
    """What ``seat`` sees of the groups: its own nation's groups, support and spent
    points; no writing in waiting. Nothing for a seat of no nation."""
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
    (AGR) and a measure passed (the votes rule)."""
    return [
        shift(state, polity, g.key, g.moved_by[happening], Cause(happening.value), on)
        for g in of(state, polity)
        if g.moved_by.get(happening)
    ]


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


def _shared(contributions: dict[SeatId, int], left: int) -> dict[SeatId, int]:
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
    "GROUP_DAY_CAP",
    "GROUP_WEEK_CAP",
    "MANPOWER_HIGH",
    "MANPOWER_LOW",
    "MAX_GROUP_EFFECTS",
    "STRIKE_LINE",
    "STRIKE_SHARE",
    "WEEK_DAYS",
    "BlocVote",
    "Cause",
    "Feeds",
    "Group",
    "Groups",
    "GroupsError",
    "Happening",
    "NationGroups",
    "Proposal",
    "Spent",
    "Theme",
    "batch",
    "bloc_support",
    "drift",
    "group",
    "happened",
    "home_standing",
    "manpower_factor",
    "named_theme",
    "nudge_problem",
    "of",
    "on",
    "output_factor",
    "propose",
    "react",
    "seen_by",
    "shift",
    "support",
    "theme_nudges",
    "used",
]
