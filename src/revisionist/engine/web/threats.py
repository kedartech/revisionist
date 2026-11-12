"""The opponents list of ``view.realism``: who is set against the seat, as its staff
believe it.

The staff know where everyone stood at the start, and after that only what
evidence shows: a paper the person wrote, a press page or a sighting about them
or their country, their answer to the seat, a war, or a change the seat's own
order brought on. A stance that changed after the last evidence is not shown,
and a cause the seat did not see is not named. No score, aim or card policy
leaves the engine here.
"""

from datetime import date

from revisionist.core.ids import EntityId, SeatId
from revisionist.core.realism import opponents
from revisionist.core.realism.card import words
from revisionist.core.realism.stance import OPPOSED, RANK, StanceCause, Standing
from revisionist.core.realism.war import polity_of
from revisionist.core.state import State, View
from revisionist.engine.web.realism_api import Threat

FIRM_DAYS, DATED_DAYS = 7, 30
"""Evidence this many days old or less reads as firm, then as dated, then as old [proposed]."""
UNKNOWN = "Cause not known."


def _evidence(state: State, view: View, figure: EntityId, start: date) -> date:
    """The last day the seat had evidence about ``figure``; the start if none since."""
    polity = polity_of(state, figure)
    about = {figure} | ({polity} if polity is not None else set())
    days = [start]
    for doc in state.documents.values():
        page = view.documents.get(doc.view.doc_id)
        if page is None:
            continue
        news = state.news.get(doc.truth.news_id) if doc.truth.news_id is not None else None
        if (
            page.author == figure
            or any(line.sight is not None and line.sight.side in about for line in page.body)
            or (news is not None and about & {news.subject, news.obj})
        ):
            days.append(page.issued)
    for order in view.routed.values():
        for part in order.parts:
            if part.target == figure and part.decided is not None:
                days.append(part.decided)
            if part.executor == figure and part.executed is not None:
                days.append(part.executed)
    mine = polity_of(state, view.me.embodies)
    days += [
        w.since for w in view.wars.values() if polity is not None and {w.a, w.b} == {polity, mine}
    ]
    for standing in state.stances.get(view.viewer, {}).get(figure, ()):
        if standing.order is not None and standing.order in view.routed:
            days.append(standing.on)
    today = view.in_world_date
    return max(d for d in days if today is None or d <= today)


def _cause(state: State, view: View, figure: EntityId, standing: Standing) -> str:
    if standing.cause is StanceCause.START:
        return "As things stood at the start."
    if standing.cause is StanceCause.SIDES:
        pair = {polity_of(state, figure), polity_of(state, view.me.embodies)}
        if any({w.a, w.b} == pair and w.since <= standing.on for w in view.wars.values()):
            return "Your countries went to war."
        return UNKNOWN  # a contest opening or closing: not every contest is the seat's to see
    if standing.order is not None and standing.order in view.routed:
        return f"After your order of {view.routed[standing.order].filed:%-d %B %Y}."
    return UNKNOWN


def seat_threats(state: State, seat: SeatId, view: View) -> list[Threat]:
    """At most ``opponents.CAP`` lines, the most hostile first."""
    today = view.in_world_date
    out: list[tuple[int, str, Threat]] = []
    for figure, history in state.stances.get(seat, {}).items():
        if not history or today is None:
            continue
        seen = _evidence(state, view, figure, history[0].on)
        known = [s for s in history if s.on <= seen] or [history[0]]
        believed = known[-1]
        if believed.stance not in OPPOSED:
            continue
        before = known[-2] if len(known) > 1 else None
        drift = 0 if before is None else RANK[believed.stance] - RANK[before.stance]
        age = (today - seen).days
        card = view.cards[figure]
        name = view.entities[figure].name
        out.append(
            (
                RANK[believed.stance],
                name,
                Threat(
                    person=figure,
                    name=name,
                    office=card.office,
                    stance=believed.stance.value,
                    stance_label=words(believed.stance.value),
                    trend="worse" if drift < 0 else "better" if drift > 0 else "steady",
                    as_of=seen.isoformat(),
                    confidence="firm"
                    if age <= FIRM_DAYS
                    else "dated"
                    if age <= DATED_DAYS
                    else "old",
                    over=[x.over for x in opponents.conflicts(state, figure, view.me.embodies)],
                    cause=_cause(state, view, figure, believed),
                ),
            )
        )
    return [t for _, _, t in sorted(out, key=lambda x: (x[0], x[1]))][: opponents.CAP]


__all__ = ["seat_threats"]
