"""The opinion resolver (plan, Phase 2 unit B3).

Public opinion, moving with a lag. An address moves the target; each Monday the
Gallup "about right" figure steps one point toward it. Other opinion levers
(Churchill's broadcast, cabinet statements, Chiang's appeal) change nothing yet.

A move in the published figure is public news, once per move: a neutral headline short
enough that the figure survives the outlet name in a press title, the new figure and the
one before it. The target it is heading for stays private.
"""

from datetime import date, timedelta

from revisionist.core.ids import derived_id
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.document import BodyField
from revisionist.core.realism.pipeline import Order, OrderStatus
from revisionist.core.realism.quantity import QuantityChange
from revisionist.core.realism.resolvers.votes import put
from revisionist.core.realism.war import NewsEvent, NewsTopic
from revisionist.core.state import State
from revisionist.core.visibility import Visibility
from revisionist.core.world_compile import object_id

THEME_POINTS = {"aid_to_allies": 2, "freedom_of_the_seas": 3, "national_unity": 1}  # [proposed]
INCIDENT_POINTS = 1  # [proposed]
INCIDENTS = ("greer_incident", "kearny_hit", "reuben_james_sunk")
ABOUT_RIGHT = "gallup_fdr_about_right"


def _clamp(n: int) -> int:
    return max(0, min(100, n))


def resolve(state: State, order: Order) -> tuple[QuantityChange, ...]:
    """Changes from one order enacted through its pipeline."""
    points = THEME_POINTS.get(str(order.params.get("theme")))
    if order.status is not OrderStatus.ENACTED or order.lever != "public_address" or points is None:
        return ()
    base = rs.value(state, "opinion_target")
    base = rs.value(state, ABOUT_RIGHT) if base is None else base
    if base is None:
        return ()
    change = put(state, "opinion_target", _clamp(base + points), rs.settled_on(order))
    return () if change is None else (change,)


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


def on_day(state: State, today: date) -> tuple["rs.Change", ...]:
    """On a Monday, fold in last week's incidents, then step one point toward the target;
    a step is news."""
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
