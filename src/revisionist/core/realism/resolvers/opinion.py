"""The opinion resolver (plan, Phase 2 unit B3).

Public opinion, moving with a lag. An address moves the target; each Monday the
Gallup "about right" figure steps one point toward it. Other opinion levers
(Churchill's broadcast, cabinet statements, Chiang's appeal) change nothing yet.

A move in the published figure is public news, once per move: a neutral headline short
enough that the figure survives the outlet name in a press title, the new figure and the
one before it. The target it is heading for stays private.

With ``groups`` on (GVR), none of that is read. The figure a nation publishes is the
support of the groups the world says feed opinion, weighted, rounded to a whole point
(``figure``); each Monday it is published as news when it differs from the last one
published, or, before the first, from where those groups started. An address moves groups
through the writing rules, not a target here: an enacted form whose parameter names one of
the issuer's nation's themes (``groups.named_theme``) proposes that theme's moves for the
issuer's seat on the day it settles, as writing naming the theme does, and the day's batch
moves the groups (``heard``).
"""

import hashlib
from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, derived_id
from revisionist.core.realism import groups
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.document import BodyField
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.resolvers.votes import put
from revisionist.core.realism.war import NewsEvent, NewsTopic, polity_of
from revisionist.core.state import State
from revisionist.core.visibility import Visibility
from revisionist.core.world_compile import object_id

THEME_POINTS = {"aid_to_allies": 2, "freedom_of_the_seas": 3, "national_unity": 1}  # [proposed]
INCIDENT_POINTS = 1  # [proposed]
INCIDENTS = ("greer_incident", "kearny_hit", "reuben_james_sunk")
ABOUT_RIGHT = "gallup_fdr_about_right"
HEADLINE_MAX = 60


def _clamp(n: int) -> int:
    return max(0, min(100, n))


def resolve(state: State, order: Order) -> tuple["rs.Change", ...]:
    """Changes from one order enacted through its pipeline."""
    points = THEME_POINTS.get(str(order.params.get("theme")))
    if groups.on(state):
        return heard(state, order)
    if order.status is not OrderStatus.ENACTED or order.lever != "public_address" or points is None:
        return ()
    base = rs.value(state, "opinion_target")
    base = rs.value(state, ABOUT_RIGHT) if base is None else base
    if base is None:
        return ()
    change = put(state, "opinion_target", _clamp(base + points), rs.settled_on(order))
    return () if change is None else (change,)


def heard(state: State, order: Order) -> tuple[ev.GroupProposed, ...]:
    """With ``groups`` on, the enacted form's theme proposed to the day's batch: the
    first parameter value, by name, that names a theme of the issuer's nation gives that
    theme's moves, each a proposal of the issuer's seat dated the day the order settled.
    Nothing when no value names one, or for a group the nation does not have."""
    nation = polity_of(state, state.seats[order.issuer].embodies)
    if order.status is not OrderStatus.ENACTED or nation is None:
        return ()
    theme = next(
        (
            found
            for _, value in sorted(order.params.items())
            if isinstance(value, str) and (found := groups.named_theme(state, nation, value))
        ),
        None,
    )
    if theme is None:
        return ()
    written = hashlib.sha256(f"{theme.key}\0{order.order_id}".encode()).hexdigest()[:16]
    on = rs.settled_on(order)
    out: list[ev.GroupProposed] = []
    for nudge in groups.theme_nudges(nation, theme):
        try:
            out.append(
                groups.propose(
                    state, order.issuer, nudge.nation, nudge.group, nudge.change, written, on
                )
            )
        except groups.GroupsError:
            continue
    return tuple(out)


def _incidents_last_week(state: State, today: date) -> int:
    """Atlantic incidents that fired since the previous Monday, so each counts once."""
    ids = {object_id(state.campaign_id, "history", k): k for k in INCIDENTS}
    return sum(
        1
        for s in state.scheduled.values()
        if s.fired
        and (s.scheduled_id in ids or s.name in INCIDENTS)
        and s.on_date is not None
        and today - timedelta(days=7) <= s.on_date < today
    )


def news(state: State, before: int, after: int, today: date) -> NewsEvent | None:
    """The public record of the figure moving from ``before`` to ``after`` today; None
    when the figure is not public or has no owner."""
    q = state.quantities.get(rs.qid(state, ABOUT_RIGHT))
    if q is None or q.owner is None or q.scope is None:
        return None
    if q.scope.visibility is not Visibility.PUBLIC:
        return None
    way = "up" if after > before else "down"
    return NewsEvent(
        news_id=derived_id(state.campaign_id, "news", "poll", ABOUT_RIGHT, today.isoformat()),
        on=today,
        topic=NewsTopic.POLL,
        subject=q.owner,
        headline=f"Poll: Roosevelt's course {way} to {after}%",
        facts=(
            BodyField(label=q.name, value=after, unit=q.unit),
            BodyField(label="Previous poll", value=before, unit=q.unit),
            BodyField(label="Date", value=f"{today.day} {today:%B %Y}"),
        ),
    )


def _feeders(state: State, nation: EntityId) -> tuple[groups.Group, ...]:
    return tuple(g for g in groups.of(state, nation) if groups.Feeds.OPINION in g.feeds)


def figure(state: State, nation: EntityId, *, start: bool = False) -> int | None:
    """With ``groups`` on, the opinion figure a nation publishes: the support of the groups
    that feed opinion, weighted by what each feeds, to a whole point (halves up); with
    ``start``, where they started. None when no group feeds it."""
    found = _feeders(state, nation)
    if not found:
        return None
    total = sum(g.feeds[groups.Feeds.OPINION] for g in found)
    now = sum(
        (g.start if start else groups.support(state, nation, g.key) or 0)
        * g.feeds[groups.Feeds.OPINION]
        for g in found
    )
    return int(now / total + 0.5)


def _last_poll(state: State, nation: EntityId) -> int | None:
    """The figure of the last poll published about ``nation``, or None before the first."""
    polls = [
        n
        for n in state.news.values()
        if n.topic is NewsTopic.POLL and n.subject == nation and n.facts
    ]
    if not polls:
        return None
    last = max(polls, key=lambda n: (n.on, n.news_id)).facts[0].value
    return last if isinstance(last, int) else None


def _group_polls(state: State, today: date) -> tuple["rs.Change", ...]:
    """On a Monday, each nation's opinion figure, as news, where it moved."""
    out: list[rs.Change] = []
    for nation in sorted(state.groups.declared):
        after = figure(state, nation)
        if after is None:
            continue
        before = _last_poll(state, nation)
        before = figure(state, nation, start=True) if before is None else before
        if before is None or after == before:
            continue
        name = max(_feeders(state, nation), key=lambda g: g.feeds[groups.Feeds.OPINION]).name
        way = "up" if after > before else "down"
        headline = f"Poll: {name} {way} to {after}%"
        out.append(
            NewsEvent(
                news_id=derived_id(
                    state.campaign_id, "news", "poll", "groups", nation, today.isoformat()
                ),
                on=today,
                topic=NewsTopic.POLL,
                subject=nation,
                headline=headline
                if len(headline) <= HEADLINE_MAX
                else headline[: HEADLINE_MAX - 1] + "…",
                facts=(
                    BodyField(label=name, value=after, unit="percent"),
                    BodyField(label="Previous poll", value=before, unit="percent"),
                    BodyField(label="Date", value=f"{today.day} {today:%B %Y}"),
                ),
            )
        )
    return tuple(out)


def on_day(state: State, today: date) -> tuple["rs.Change", ...]:
    """On a Monday, fold in last week's incidents, then step one point toward the target;
    a step is news. With ``groups`` on, the opinion figure each nation's groups give,
    where it moved."""
    if groups.on(state):
        return _group_polls(state, today) if today.weekday() == 0 else ()
    about = rs.value(state, ABOUT_RIGHT)
    if today.weekday() != 0 or about is None:
        return ()
    target = rs.value(state, "opinion_target")
    bump = INCIDENT_POINTS * _incidents_last_week(state, today)
    out: list[rs.Change | None] = []
    if bump:
        target = _clamp((about if target is None else target) + bump)
        out.append(put(state, "opinion_target", target, today))
    if target is not None and target != about:
        after = about + (1 if target > about else -1)
        out += [put(state, ABOUT_RIGHT, after, today), news(state, about, after, today)]
    return tuple(c for c in out if c is not None)
