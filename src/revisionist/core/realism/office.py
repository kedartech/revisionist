"""The office question as a formal sitting (OFQ).

A seat's last authority is never taken on an order. It is taken only at the office
question's sitting: the question opens on a post, is told that day to every seat of the
holder's nation, and sits on a day dated ``SITTING_DAYS`` ahead, and not before the seats
told have had two wakes to act in: the wake it is told before, and the one after. The same
notice and the same sitting apply to every seat, whether a person, the aide or code plays
it.

What a post rests on (``rests_on``) and how its holder is removed (``removed_by``) are world
data on its ``Ladder``, read only with ``office`` on. A question opens for one of five
causes: its base turned (TUR), an incident, an order that would take the holder's last
authority (LDR's question move), the end of a term, or an election naming the post
(ELE). While it runs the holder plays on and keeps every move. At the sitting it is
decided by the post's way of removal:

- ``vote``: the chamber's blocs, each from its row for the vote on ``MEASURE`` (its
  default row when the world lists none), as a bill's vote is counted;
- ``council`` and ``person``: each member's sealed choice, filed before the day, or, for a
  member who filed none, his card's choice on the day (``card_choice``); the aide never
  files one;
- ``term``: removed.

A question an election opened is decided by the election instead: the holder is removed
when the mean support of what the post rests on stands under ``ELECTION_LINE``; it needs no
way of removal.

Removed: the post goes on by ``post_changed`` (to the order's appointee, else to nobody,
and the day's succession walk gives it to its successor). Kept: no question on that post
opens for ``REST_DAYS``. The holder's presence, absence or controller is never read.
"""

from datetime import date, timedelta

from revisionist.core import events as ev
from revisionist.core.ids import AssetId, DocumentId, EntityId, OrderId, SeatId, derived_id
from revisionist.core.realism import groups, posts
from revisionist.core.realism.card import ChannelKind, PostCause
from revisionist.core.realism.document import (
    BodyField,
    Classification,
    DocumentKind,
    DocumentTruth,
    DocumentView,
)
from revisionist.core.realism.groups import Group
from revisionist.core.realism.war import polity_of
from revisionist.core.state import (
    OfficeQuestion,
    QuestionCause,
    Removal,
    RemovalWay,
    Rule,
    State,
    seat_of_person,
)
from revisionist.core.visibility import Scope, Visibility, private_to

SITTING_DAYS = 10
"""The sitting is dated this many world days after the question opens. [proposed]"""
WAKES_AHEAD = 2
"""And it sits only in the walk of the last of this many wakes the seats told can act in."""
REST_DAYS = 30
"""A holder kept at a sitting faces no question on that post for this long. [proposed]"""
TURN_LINE = 30
"""A post's base turns on its holder while the mean support of what it rests on stands
under this line. [proposed]"""
WARN_DAYS = 14
"""Under the line this many world days running: the holder's seat is warned. [proposed]"""
TURN_DAYS = 21
"""Under the line this many world days running: the office question opens. [proposed]"""
ELECTION_LINE = 50
"""An election naming a post removes its holder while the mean support of what the post
rests on stands under this line on its day. [proposed]"""
MEASURE = "office_question"
"""The measure a chamber's blocs vote on at a sitting: their row for it, else their
default row for the vote."""

NOT_ON = "there is no office question in this game"
NOT_OPEN = "no such office question is open"
NOT_A_MEMBER = "you do not decide this office question"


def on(state: State) -> bool:
    return Rule.OFFICE in state.rules and Rule.POSTS in state.rules


def removal(state: State, post: AssetId) -> Removal | None:
    """How the holder of ``post`` is removed; None when he faces no question on it."""
    held = state.ladders.get(post)
    way = held.removed_by if held is not None else None
    return None if way is None or way.way is RemovalWay.NEVER else way


def nation(state: State, post: AssetId) -> EntityId | None:
    """The nation of the post's holder, else of whoever controls the post."""
    holder = posts.holder(state, post)
    found = polity_of(state, holder) if holder is not None else None
    return found or polity_of(state, state.assets[post].controller)


def seats(state: State, of: EntityId | None) -> frozenset[SeatId]:
    """Every seat whose person belongs to the nation, whoever plays it."""
    return frozenset(
        s.seat_id
        for s in state.seats.values()
        if of is not None and polity_of(state, s.embodies) == of
    )


def scope_of(state: State, question: OfficeQuestion) -> Scope:
    """The question's opening: sealed to the seats of the holder's nation, or to no seat."""
    held = seats(state, nation(state, question.post)) or frozenset({engine_only(state)})
    return Scope(visibility=Visibility.RESTRICTED, known_by=held)


def wake_number(state: State) -> int:
    """The wake openings so far: each tick opens one, and its day walk runs after its
    orders are in."""
    return state.tick


def first_wake(state: State, in_walk: bool) -> int:
    """The first wake a seat told now can act in: this one, or, told in a day walk after
    this wake's orders are in, the next."""
    return wake_number(state) + (1 if in_walk else 0)


def open_on(state: State, post: AssetId) -> OfficeQuestion | None:
    return next((q for q in state.office_questions.values() if q.post == post), None)


def questions(state: State, of: EntityId) -> tuple[OfficeQuestion, ...]:
    """The office questions open on the posts of nation ``of``, earliest sitting first."""
    found = (q for q in state.office_questions.values() if nation(state, q.post) == of)
    return tuple(sorted(found, key=lambda q: (q.sits, q.question_id)))


def refusal(state: State, post: AssetId, today: date, cause: QuestionCause | None = None) -> str:
    """Why no office question may open on ``post`` today, for ``cause``; empty when one may."""
    if not on(state):
        return NOT_ON
    office = state.assets[post].name if post in state.assets else post
    if cause is not QuestionCause.ELECTION and removal(state, post) is None:
        return f"nobody can put the holder of {office} out of it"
    if posts.holder(state, post) is None:
        return f"{office} has no holder"
    if open_on(state, post) is not None:
        return f"a question on {office} is open already"
    rests = state.office_rests.get(post)
    if rests is not None and today < rests and cause is not QuestionCause.ELECTION:
        return f"the holder of {office} was kept; no question on it before {rests.isoformat()}"
    return ""


def notice_id(state: State, question_id: str) -> DocumentId:
    return DocumentId(derived_id(state.campaign_id, "office-notice", question_id))


def open_question(
    state: State,
    post: AssetId,
    cause: QuestionCause,
    today: date,
    move_id: str | None = None,
    *,
    in_walk: bool = False,
    sits: date | None = None,
) -> list[ev.Payload]:
    """The events that open an office question on ``post`` today: the question, and one
    paper the same day to every seat of the holder's nation. ``in_walk``: opened in a day
    walk, after the wake's orders are in. ``sits``: the day it sits, when later than
    ``SITTING_DAYS`` ahead. Raises ``ValueError`` with the reason one may not
    open (``refusal``)."""
    why = refusal(state, post, today, cause)
    if why:
        raise ValueError(why)
    holder = posts.holder(state, post)
    assert holder is not None
    question = OfficeQuestion(
        question_id=derived_id(
            state.campaign_id, "office-question", post, holder, today.isoformat()
        ),
        post=post,
        holder=holder,
        cause=cause,
        move_id=move_id,
        opened=today,
        tick=first_wake(state, in_walk),
        sits=max(today + timedelta(days=SITTING_DAYS), sits or today),
    )
    return [ev.OfficeQuestionOpened(question=question), _notice(state, question)]


def _notice(state: State, q: OfficeQuestion) -> ev.DocumentIssued:
    office = state.assets[q.post].name
    who = state.entities[q.holder].name
    doc_id = notice_id(state, q.question_id)
    author = nation(state, q.post) or q.holder
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.REPORT,
            author=author,
            issued=q.opened,
            arrives=q.opened,
            channel=ChannelKind.CABLE,
            classification=Classification.CONFIDENTIAL,  # [proposed]
            title=f"The office question on {office}"[:120],
            body=(
                BodyField(label="Post", value=office[:120]),
                BodyField(label="Holder", value=who[:120]),
                BodyField(label="Cause", value=q.cause.value),
                BodyField(label="Sits", value=q.sits.isoformat()),
                BodyField(label="Not before", value="You have acted in two wakes"),
            ),
            scope=scope_of(state, q),
        ),
        truth=DocumentTruth(doc_id=doc_id),
    )


def deciders(state: State, q: OfficeQuestion) -> tuple[EntityId, ...]:
    """Who decides the question by a choice: a council's members, or the one person; none
    for a question an election opened."""
    way = removal(state, q.post)
    if way is None or q.cause is QuestionCause.ELECTION:
        return ()
    if way.way is RemovalWay.COUNCIL:
        return way.members
    if way.way is RemovalWay.PERSON and way.person is not None:
        return (way.person,)
    return ()


def may_choose(state: State, seat: SeatId, question_id: str) -> None:
    """Raises ``ValueError`` with the seat's words unless the seat plays a person who
    decides the open question ``question_id``."""
    if not on(state):
        raise ValueError(NOT_ON)
    q = state.office_questions.get(question_id)
    if q is None:
        raise ValueError(NOT_OPEN)
    held = state.seats.get(seat)
    if held is None or held.embodies not in deciders(state, q):
        raise ValueError(NOT_A_MEMBER)


def choose(state: State, seat: SeatId, question_id: str, remove: bool, today: date) -> ev.Payload:
    """The seat's sealed choice on the question; raises ``ValueError`` as ``may_choose``."""
    may_choose(state, seat, question_id)
    return ev.OfficeChoiceFiled(question_id=question_id, seat_id=seat, remove=remove, on=today)


def choice_scope(seat: SeatId) -> Scope:
    return private_to(seat)


def card_choice(state: State, member: EntityId, holder: EntityId) -> bool:
    """A member who filed no choice: his card decides on the day, to remove a holder he
    regards ill (a regard below nothing), else to keep him. [proposed]"""
    regard = next(
        (r.disposition for r in state.relationships.values() if r.a == member and r.b == holder),
        0,
    )
    return regard < 0


def _choice(state: State, q: OfficeQuestion, member: EntityId) -> bool:
    filed = state.office_choices.get(q.question_id, {})
    for seat_id, remove in sorted(filed.items()):
        held = state.seats.get(seat_id)
        if held is not None and held.embodies == member:
            return remove
    return card_choice(state, member, q.holder)


def removed(state: State, q: OfficeQuestion) -> bool:
    """Whether the sitting removes the holder, by the post's way of removal, or, for a
    question an election opened, by its base on the day."""
    if q.cause is QuestionCause.ELECTION:
        mean = base_support(state, q.post)
        return mean is not None and mean < ELECTION_LINE
    way = removal(state, q.post)
    if way is None:
        return False
    if way.way is RemovalWay.TERM:
        return True
    if way.way is RemovalWay.VOTE:
        # The fold reads this module; the resolvers import the world compiler, which
        # imports the fold: so the vote's count is imported here, when a sitting runs.
        from revisionist.core.realism.resolvers.votes import bloc_tally

        of = nation(state, q.post)
        if of is None or way.chamber is None or way.vote is None:
            return False
        yeas, nays = bloc_tally(state, of, way.chamber, MEASURE, way.vote, OrderId(q.question_id))
        return yeas > nays
    members = deciders(state, q)
    needed = way.needed if way.way is RemovalWay.COUNCIL else 1
    return sum(_choice(state, q, m) for m in members) >= needed


def sits(state: State, q: OfficeQuestion, today: date) -> bool:
    """Whether the question sits today: on or after its day, and in the walk of the
    second wake the seats told could act in, or later."""
    return today >= q.sits and wake_number(state) >= q.tick + WAKES_AHEAD - 1


def due(state: State, today: date) -> list[str]:
    """The questions that sit today, earliest sitting first."""
    if not on(state):
        return []
    ready = (q for q in state.office_questions.values() if sits(state, q, today))
    return [q.question_id for q in sorted(ready, key=lambda q: (q.sits, q.question_id))]


def sit(state: State, question_id: str, today: date) -> list[ev.Payload]:
    """The events of the question's sitting: the decision, the post going on when its
    holder is removed, and the order that stood as its cause settled. A holder who left
    the post before the day is not removed from it."""
    q = state.office_questions[question_id]
    gone = posts.holder(state, q.post) == q.holder and removed(state, q)
    out: list[ev.Payload] = [
        ev.OfficeQuestionDecided(
            question_id=q.question_id,
            post=q.post,
            holder=q.holder,
            on=today,
            removed=gone,
            rests_until=None if gone else today + timedelta(days=REST_DAYS),
        )
    ]
    move = state.post_moves.get(q.move_id) if q.move_id is not None else None
    if gone:
        to = move.person if move is not None and move.appoint else None
        out += posts.change(state, q.post, to, today, PostCause.REMOVED)
    if move is not None:
        out.append(ev.PostMoveSettled(move_id=move.move_id, seat=move.seat, on=today, landed=gone))
    return out


def arising(state: State, today: date) -> list[ev.Payload]:
    """The questions that open today on their own: an order standing as an office
    question's cause that none cites yet, and a term ending today. An order on a post
    whose holder was kept, and is resting, is settled void."""
    if not on(state):
        return []
    out: list[ev.Payload] = []
    cited = {q.move_id for q in state.office_questions.values()}
    taken: set[AssetId] = set()
    for m in sorted(state.post_moves.values(), key=lambda m: (m.ordered, m.move_id)):
        if not m.question or m.move_id in cited or m.post in taken:
            continue
        if open_on(state, m.post) is not None:
            continue  # the holder already faces a question on it: the order waits
        if refusal(state, m.post, today):
            out.append(ev.PostMoveSettled(move_id=m.move_id, seat=m.seat, on=today, landed=False))
            continue
        out += open_question(state, m.post, QuestionCause.ORDER, today, m.move_id, in_walk=True)
        taken.add(m.post)
    for post, held in sorted(state.ladders.items()):
        way = held.removed_by
        if way is None or way.way is not RemovalWay.TERM or way.ends != today:
            continue
        if post not in taken and not refusal(state, post, today):
            out += open_question(state, post, QuestionCause.TERM, today, in_walk=True)
            taken.add(post)
    return out


def base(state: State, post: AssetId) -> tuple[Group, ...]:
    """The groups of the post's nation it rests on, in the order the post names them. A
    key that names no group of that nation (a body) is not read."""
    held = state.ladders.get(post)
    of = nation(state, post)
    if held is None or of is None:
        return ()
    found = (groups.group(state, of, key) for key in held.rests_on)
    return tuple(g for g in found if g is not None)


def base_support(state: State, post: AssetId) -> float | None:
    """The mean support of the groups the post rests on; None when it rests on none."""
    found = base(state, post)
    of = nation(state, post)
    if not found or of is None:
        return None
    return sum(groups.support(state, of, g.key) or 0 for g in found) / len(found)


def base_fell(state: State, day: date) -> dict[AssetId, date]:
    """For each post whose base stands under ``TURN_LINE`` now, the day it fell under:
    the day already kept, else ``day``. A post at or above the line has none."""
    if not on(state):
        return {}
    out: dict[AssetId, date] = {}
    for post in sorted(state.ladders):
        mean = base_support(state, post)
        if mean is not None and mean < TURN_LINE:
            out[post] = state.office_base_fell.get(post, day)
    return out


def days_under(state: State, post: AssetId, today: date) -> int:
    """How many world days running, today included, the post's base has stood under its
    line; 0 when it stands at or above it."""
    fell = state.office_base_fell.get(post)
    return 0 if fell is None or fell > today else (today - fell).days + 1


def warning_id(state: State, post: AssetId, fell: date) -> DocumentId:
    return DocumentId(derived_id(state.campaign_id, "office-warning", post, fell.isoformat()))


def _warning(state: State, post: AssetId, holder: EntityId, today: date) -> ev.DocumentIssued:
    """One paper to the holder's seat, whoever plays it: his base has turned, by name."""
    fell = state.office_base_fell[post]
    doc_id = warning_id(state, post, fell)
    office = state.assets[post].name
    seat = seat_of_person(state, holder)
    told = seat.seat_id if seat is not None else engine_only(state)
    named = ", ".join(g.name for g in base(state, post))
    return ev.DocumentIssued(
        document=DocumentView(
            doc_id=doc_id,
            kind=DocumentKind.REPORT,
            author=nation(state, post) or holder,
            issued=today,
            arrives=today,
            channel=ChannelKind.CABLE,
            classification=Classification.CONFIDENTIAL,  # [proposed]
            title=f"The base turns: {office}"[:120],
            body=(
                BodyField(label="Post", value=office[:120]),
                BodyField(label="Holder", value=state.entities[holder].name[:120]),
                BodyField(label="Groups", value=named[:120]),
                BodyField(label="Under since", value=fell.isoformat()),
                BodyField(
                    label="Question on",
                    value=(fell + timedelta(days=TURN_DAYS - 1)).isoformat(),
                ),
            ),
            scope=private_to(told),
        ),
        truth=DocumentTruth(doc_id=doc_id),
    )


def engine_only(state: State) -> SeatId:
    return SeatId(derived_id(state.campaign_id, "engine-only", "office-questions"))


def turning(state: State, today: date) -> list[ev.Payload]:
    """Each post whose base has stood under its line: on the ``WARN_DAYS``th day running,
    one warning to its holder's seat; from the ``TURN_DAYS``th, the office question, with
    the cause that the base turned, on the first day one may open."""
    if not on(state):
        return []
    out: list[ev.Payload] = []
    for post in sorted(state.office_base_fell):
        holder = posts.holder(state, post)
        if holder is None or removal(state, post) is None:
            continue
        run = days_under(state, post, today)
        if run == WARN_DAYS:
            out.append(_warning(state, post, holder, today))
        if run >= TURN_DAYS and not refusal(state, post, today):
            out += open_question(state, post, QuestionCause.BASE, today, in_walk=True)
    return out


__all__ = [
    "ELECTION_LINE",
    "MEASURE",
    "NOT_A_MEMBER",
    "NOT_ON",
    "NOT_OPEN",
    "REST_DAYS",
    "SITTING_DAYS",
    "TURN_DAYS",
    "TURN_LINE",
    "WAKES_AHEAD",
    "WARN_DAYS",
    "arising",
    "base",
    "base_fell",
    "base_support",
    "card_choice",
    "choice_scope",
    "choose",
    "days_under",
    "deciders",
    "due",
    "engine_only",
    "first_wake",
    "may_choose",
    "nation",
    "on",
    "open_on",
    "open_question",
    "questions",
    "refusal",
    "removal",
    "removed",
    "scope_of",
    "seats",
    "sit",
    "sits",
    "turning",
    "warning_id",
]
