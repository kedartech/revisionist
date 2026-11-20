"""Landing a MakeStatement effect in the world.

A public statement is news about its issuer, and a theme the opinion resolver knows
moves the public's target. A statement to one audience is a private fact its issuer
holds, and moves nothing.
"""

import hashlib
from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FactId, SeatId, derived_id
from revisionist.core.ontology import Fact
from revisionist.core.realism import groups
from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.document import BodyField
from revisionist.core.realism.effect import GroupNudge, MakeStatement
from revisionist.core.realism.pass_world import PassWorld
from revisionist.core.realism.resolvers import opinion
from revisionist.core.realism.war import NewsEvent, NewsTopic, polity_of
from revisionist.core.visibility import private_to

LINE = 60
"""A label's worth of words."""


def _clip(text: str) -> str:
    """``text`` as a label, cut with an ellipsis when it runs over."""
    return text if len(text) <= LINE else text[: LINE - 1] + "…"


def _opinion(world: PassWorld, theme: str, on: date) -> list[ev.Payload]:
    """The public's target moved by the theme's points, from where it stands."""
    points = opinion.THEME_POINTS.get(theme)
    if points is None:
        return []
    target = world.quantities.get(rs.qid(world.state, "opinion_target"))
    about = world.quantities.get(rs.qid(world.state, opinion.ABOUT_RIGHT))
    base = target.value if target is not None else None
    if base is None and about is not None:
        base = about.value
    if base is None or target is None:
        return []
    moved = target.model_copy(update={"value": max(0, min(100, base + points)), "as_of": on})
    world.quantities[moved.quantity_id] = moved
    return [ev.QuantitySet(quantity=moved)]


def text_hash(theme: str, words: str) -> str:
    """A stable stand-in for a written statement's text: the groups rule keeps this hash,
    never the words, and breaks a tie between two statements by it."""
    return hashlib.sha256(f"{theme}\0{words}".encode()).hexdigest()[:16]


def nudge(
    world: PassWorld, effect: GroupNudge, issuer_seat: SeatId, written: str, on: date
) -> list[ev.Payload]:
    """A group nudge a ruling gave a statement, proposed to the day's batch for the
    issuer's seat; the batch, not this call, moves the group. Nothing when the rule is
    off or the group is gone."""
    try:
        wrote = groups.propose(
            world.state, issuer_seat, effect.nation, effect.group, effect.change, written, on
        )
    except groups.GroupsError:
        return []
    return [wrote]


def land(
    world: PassWorld, effect: MakeStatement, issuer_seat: SeatId, issuer: EntityId, on: date
) -> tuple[list[ev.Payload], list[FactId]]:
    state = world.state
    if effect.audience is not None:
        fact_id = FactId(
            derived_id(
                state.campaign_id,
                "fact",
                "statement",
                issuer,
                effect.audience,
                effect.theme,
                on.isoformat(),
            )
        )
        if not world.claim(fact_id, state.facts):
            return [], []
        told = Fact(
            fact_id=fact_id,
            subject=issuer,
            predicate="told",
            obj=effect.audience,
            scope=private_to(issuer_seat),
        )
        return [ev.FactAsserted(fact=told)], []
    news_id = derived_id(
        state.campaign_id, "news", "statement", issuer, effect.theme, on.isoformat()
    )
    if not world.claim(news_id, state.news):
        return [], []
    item = NewsEvent(
        news_id=news_id,
        on=on,
        topic=NewsTopic.STATEMENT,
        subject=issuer,
        obj=polity_of(state, issuer),
        facts=(BodyField(label="Theme", value=effect.theme),),
        headline=_clip(f"{state.entities[issuer].name} speaks on {effect.theme}"),
    )
    moved = [] if groups.on(state) else _opinion(world, effect.theme, on)
    return [ev.NewsReported(news=item), *moved], []
