"""Seat cards: one record per person, for every office (pillar 2).

A card says what its person can do and how: formal powers, the levers that
actually move things, the people within reach and the channel to each, the
reports they receive, the pipelines their orders go through. One schema
serves every figure. A card marked ``playable`` can be claimed by a human;
every other person is run by code from the same card.

Three nested shapes, by who may read them:

- ``CardFace``: what anyone knows of the office. Every seat sees every face.
- ``Desk``: the face plus what the person works with. Only the person's own seat.
- ``SeatCard``: the desk plus the policy the engine runs an AI person by. Engine only.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, ClassVar

from pydantic import Field, StringConstraints, model_validator

from revisionist.core._base import Label, Model
from revisionist.core.ids import AssetId, EntityId, FeatureId, FeedId, PipelineId
from revisionist.core.realism.answer import Answer, ParamValue
from revisionist.core.realism.effect import EffectKind
from revisionist.core.realism.quantity import ResolverKey

if TYPE_CHECKING:
    from revisionist.core.goals import AimRule


def words(key: str) -> str:
    """A key in words, for what the world gave no label: "send_bill" -> "Send bill"."""
    spoken = key.replace("_", " ").strip()
    return spoken[:1].upper() + spoken[1:]


class ChannelKind(StrEnum):
    """How words travel. Each trades speed against exposure (direction, channels table)."""

    IN_PERSON = "in_person"
    TELEPHONE = "telephone"
    CABLE = "cable"
    LETTER = "letter"
    COURIER = "courier"
    RADIO = "radio"
    PRESS = "press"


class ParamKind(StrEnum):
    INT = "int"
    ENUM = "enum"
    ENTITY = "entity"
    TEXT = "text"


class WarNeed(Model):
    """What one choice of a form needs: its issuer's nation at war with ``nation``, a
    polity's world key (WRL). A seat whose nation is not is told "<its nation> is not at war
    with <nation>, " and then ``refusal``."""

    nation: Label
    refusal: str = Field(min_length=1, max_length=120)


ESCORT_LEVELS = (0, 1, 2)
"""The levels a choice may mark: none, escort, shoot on sight."""
EscortLevel = Annotated[int, Field(ge=0, le=2)]


class ParamSpec(Model):
    """One typed parameter of a lever. An order's params and every amendment must fit it."""

    name: Label
    kind: ParamKind
    lo: int | None = None
    hi: int | None = None
    choices: tuple[Label, ...] = ()
    # Empty display fields are left out of every dump, so campaigns logged before
    # they existed keep their state hash.
    label: Label = Field(default="", exclude_if=lambda v: not v)
    """What the form calls it. Empty: the client words the name itself."""
    choice_labels: tuple[Label, ...] = Field(default=(), exclude_if=lambda v: not v)
    """One per choice, in order, or none."""

    @model_validator(mode="after")
    def _shape(self) -> "ParamSpec":
        bounded = self.lo is not None or self.hi is not None
        if self.kind is ParamKind.INT:
            if self.lo is None or self.hi is None or self.lo > self.hi:
                raise ValueError(f"int parameter {self.name}: needs lo <= hi")
        elif bounded:
            raise ValueError(f"{self.kind.value} parameter {self.name}: only an int has bounds")
        if self.kind is ParamKind.ENUM:
            if not self.choices or len(set(self.choices)) != len(self.choices):
                raise ValueError(f"enum parameter {self.name}: needs distinct choices")
        elif self.choices:
            raise ValueError(f"{self.kind.value} parameter {self.name}: only an enum has choices")
        if self.choice_labels and len(self.choice_labels) != len(self.choices):
            raise ValueError(f"parameter {self.name}: needs one choice label per choice")
        return self


class Lever(Model):
    """Something the person can set moving. Names a pipeline and a resolver, never a verb."""

    name: Label
    pipeline: PipelineId
    resolver: ResolverKey
    params: tuple[ParamSpec, ...] = ()
    label: Label = Field(default="", exclude_if=lambda v: not v)
    summary: str = Field(default="", max_length=300, exclude_if=lambda v: not v)
    needs_war: dict[Label, dict[Label, WarNeed]] = Field(
        default_factory=dict, exclude_if=lambda v: not v
    )
    """The choices its issuer's nation may take only at war with another, by parameter and
    choice (WRL). Read with ``territories`` on; left out of the dump when empty, as in every
    stored game."""
    escort_levels: dict[Label, EscortLevel] = Field(
        default_factory=dict, exclude_if=lambda v: not v
    )
    """The escort level each choice of one parameter stands for, choice to level (ESC): 0
    none, 1 escort, 2 shoot on sight. Every choice of that parameter or none; left out of
    the dump when empty, as in every stored game."""

    @model_validator(mode="after")
    def _distinct(self) -> "Lever":
        names = [p.name for p in self.params]
        if len(set(names)) != len(names):
            raise ValueError(f"lever {self.name}: a parameter is named twice")
        if problems := war_need_problems(self.params, self.needs_war):
            raise ValueError(f"lever {self.name}: {problems[0]}")
        marked = set(self.escort_levels)
        if marked and not any(set(p.choices) == marked for p in self.params):
            raise ValueError(f"lever {self.name}: escort_levels are not one parameter's choices")
        return self


def war_need_problems(
    params: Iterable["ParamSpec"], needs_war: Mapping[str, Mapping[str, WarNeed]]
) -> list[str]:
    """What is wrong with a form's ``needs_war``: a parameter it does not have, or a choice
    that parameter does not offer."""
    choices = {p.name: p.choices for p in params}
    out: list[str] = []
    for name, marks in needs_war.items():
        if name not in choices:
            out.append(f"needs_war names no parameter {name}")
        out += [
            f"needs_war: {name} offers no choice {c}"
            for c in marks
            if c not in choices.get(name, ())
        ]
    return out


def escort_level_problems(
    params: Iterable["ParamSpec"], marks: Mapping[str, Mapping[str, int]]
) -> list[str]:
    """What is wrong with a form's ``escort_level``: a parameter or choice it does not have,
    a level outside 0 to 2, a marked parameter with a choice left unmarked, or marks on more
    than one parameter."""
    choices = {p.name: p.choices for p in params}
    out: list[str] = []
    if len(marks) > 1:
        out.append("escort_level marks more than one parameter")
    for name, levels in marks.items():
        if name not in choices:
            out.append(f"escort_level names no parameter {name}")
            continue
        out += [
            f"escort_level: {name} offers no choice {c}" for c in levels if c not in choices[name]
        ]
        out += [
            f"escort_level {name} {c}: {v} is not 0, 1 or 2"
            for c, v in levels.items()
            if v not in ESCORT_LEVELS
        ]
        out += [
            f"escort_level {name} leaves {c} unmarked" for c in choices[name] if c not in levels
        ]
    return out


class Contact(Model):
    """A person in the inner circle, and how the words travel."""

    person: EntityId
    channel: ChannelKind


class CardPath(StrEnum):
    """Which ladder the office stands on (CMD). Read with the ``command`` rule on."""

    POLITICAL = "political"
    MILITARY = "military"


class CardFace(Model):
    """What anyone knows of the office: who holds it, its powers and its channels."""

    person: EntityId
    office: Label
    playable: bool = False
    powers: tuple[Label, ...] = ()
    """Formal powers, as the constitution or the record states them."""
    inner_circle: tuple[Contact, ...] = ()
    """Always reachable, fast and secure (spec §8.1). Everyone else is reached by ``reach``."""
    path: CardPath = CardPath.POLITICAL
    """Political, or military: a commander who orders his own force (CMD). A card
    without it is political, and a stored card has none."""
    post: AssetId | None = Field(default=None, exclude_if=lambda v: v is None)
    """With ``posts`` on, the office asset the person holds (PPP): the office, and with it
    the part of the card that goes with the office. None: no post, and the card is all
    the person's own."""

    late_fields: ClassVar[frozenset[str]] = frozenset({"path", "post"})


class Tie(StrEnum):
    """How a person stands to someone they want to reach."""

    INNER = "inner"
    """On the card's inner circle: fast, secure, always available."""
    CHAIN = "chain"
    """In the person's own government or service chain: summoned."""
    HEAD = "head"
    """A foreign head of government."""
    PUBLIC = "public"
    """A legislator, the press, a private citizen."""


CHANNELS: dict[Tie, tuple[ChannelKind, ...]] = {
    Tie.INNER: tuple(ChannelKind),
    Tie.CHAIN: (ChannelKind.IN_PERSON, ChannelKind.TELEPHONE),
    Tie.HEAD: (ChannelKind.CABLE, ChannelKind.COURIER),
    Tie.PUBLIC: (ChannelKind.TELEPHONE, ChannelKind.LETTER, ChannelKind.IN_PERSON),
}
"""The channels each tie allows. Courier stands for an envoy; ``in_person`` with the
public is a meeting request, which the other side may decline."""


class Reach(Model):
    """What reach is derived from (spec §8.1). Whether a meeting is taken is computed
    in code from rank, disposition and standing; nothing here is a whitelist."""

    rank: int = Field(default=0, ge=0, le=5)
    """Standing in the world: 5 a head of government, 0 a private citizen."""
    chain: tuple[EntityId, ...] = ()
    """The bodies whose people answer this person's summons: their own government
    and service chain."""
    heads: bool = False
    """May address a foreign head of government directly."""


class Domain(Model):
    """One field the office commands outright (spec §8.1)."""

    name: Label
    effects: frozenset[EffectKind] = Field(min_length=1)
    executor: EntityId | None = None
    """Who carries it out. None: the seat acts itself (a statement, an executive order)."""
    forces: tuple[FeatureId, ...] = ()
    """The forces in scope, where the domain moves or engages forces."""
    summary: str = Field(default="", max_length=300)


Aim = Annotated[str, StringConstraints(min_length=1, max_length=160)]
"""One line on what the person was set on at the start."""


class Desk(CardFace):
    """The face plus what the person works with. Shown only to the person's own seat."""

    principals: tuple[EntityId, ...] = ()
    """Whom the person answers to: an electorate, a sovereign, a superior."""
    levers: tuple[Lever, ...] = ()
    """Actual levers: what moves things, as against the formal powers."""
    feeds: tuple[FeedId, ...] = ()
    """The reports this person receives."""
    pipelines: tuple[PipelineId, ...] = ()
    """The pipelines this person's orders may go through."""
    constraints: tuple[Label, ...] = ()
    personal: tuple[Label, ...] = ()
    """Personal factors: health, travel, absence from the capital."""
    successor: EntityId | None = None
    horizon_days: int = Field(ge=1, le=365)
    """How far ahead this person's decisions play out (pillar 5)."""
    authority: tuple[Domain, ...] = ()
    """What the office commands outright (spec §8.1). Orders inside it are commands."""
    reach: Reach = Reach()
    aims: tuple[Aim, ...] = Field(default=(), max_length=3)
    """What the person was set on at the start, as the record has it. Shown to the
    seat; not a rule."""

    late_fields: ClassVar[frozenset[str]] = CardFace.late_fields | {"authority", "reach", "aims"}

    @model_validator(mode="after")
    def _distinct_domains(self) -> "Desk":
        names = [d.name for d in self.authority]
        if len(set(names)) != len(names):
            raise ValueError(f"card {self.person}: an authority domain is named twice")
        return self


Address = Annotated[str, StringConstraints(min_length=1, max_length=60)]
"""A form of address, written by hand in the world file."""


class Conflict(Model):
    """Something the person is set against, as the world file declares it."""

    against: EntityId
    """A person, or a polity for everyone in it."""
    over: Label
    """What it is over, in words a seat may be shown."""
    irreducible: bool = False
    """No standing with the person ends it: their stance toward whoever it names
    never rises above obstructing."""


class Topic(Model):
    """A matter people want or hold to, named by the world file. An order touches it
    by its lever, the kind of a typed effect it carries, or one of its own words.
    Engine only."""

    key: Label
    name: Label
    levers: tuple[Label, ...] = ()
    effects: tuple[EffectKind, ...] = ()
    words: tuple[Label, ...] = ()
    """Lower-case words."""

    def touched(self, lever: str | None, kinds: Iterable[str], words: Iterable[str]) -> bool:
        return (
            (lever is not None and lever in self.levers)
            or not set(self.effects).isdisjoint(kinds)
            or not set(self.words).isdisjoint(words)
        )


class SeatCard(Desk):
    """The whole card. The policy fields below are how code runs an unclaimed person;
    they never leave the engine."""

    voice: str = Field(default="", max_length=200)
    """How the person speaks and writes. Read by the prose and counsel models only."""
    loyalty: int = Field(default=0, ge=-5, le=5)
    """Disposition to the principal."""
    doctrine: tuple[Label, ...] = ()
    interests: tuple[Label, ...] = ()
    competence: int = Field(default=3, ge=0, le=5)
    """Engine v2: how well the person carries out a command (fidelity, spec §8.2).
    3 is ordinary. [proposed]"""
    # Left out of the dump while empty, so a campaign whose cards carry neither
    # keeps its state hash.
    allies: tuple[EntityId, ...] = Field(default=(), exclude_if=lambda v: not v)
    """The polities and people this person stands with."""
    opposes: tuple[Conflict, ...] = Field(default=(), max_length=6, exclude_if=lambda v: not v)
    """What this person is set against."""
    answers: tuple[Answer, ...] = Field(default=(), max_length=8, exclude_if=lambda v: not v)
    """What this person does back when someone acts, while nobody plays them."""
    addressed_as: Address | None = Field(default=None, exclude_if=lambda v: v is None)
    """How a letter to this person opens ("Mr. President"). Read by the prose model only."""
    wants: tuple[Label, ...] = Field(default=(), exclude_if=lambda v: not v)
    """Keys of the topics this person wants. Either list set, the topics replace the
    free-text interests and doctrine where an order's appeal is weighed."""
    holds_to: tuple[Label, ...] = Field(default=(), exclude_if=lambda v: not v)
    """Keys of the topics this person holds to."""
    aim_rules: tuple["AimRule | None", ...] = Field(
        default=(), max_length=3, exclude_if=lambda v: not v
    )
    """What makes each aim a goal (AIM), by the aims' index: None for an aim with no
    condition. Read with the ``aims`` rule on."""

    own: "PostPart | None" = Field(default=None, exclude_if=lambda v: v is None)
    """With ``posts`` on, what of the post's kind the person had before he took his post,
    given back when he leaves it (PPP). None: nothing."""

    late_fields: ClassVar[frozenset[str]] = Desk.late_fields | {
        "own",
        "competence",
        "allies",
        "opposes",
        "answers",
        "wants",
        "holds_to",
        "aim_rules",
    }

    @model_validator(mode="after")
    def _distinct_answers(self) -> "SeatCard":
        keys = [a.key for a in self.answers]
        if len(set(keys)) != len(keys):
            raise ValueError(f"card {self.person}: an answer is named twice")
        return self

    @model_validator(mode="after")
    def _aim_rules(self) -> "SeatCard":
        if len(self.aim_rules) > len(self.aims):
            raise ValueError(f"card {self.person}: a rule for an aim the card does not have")
        if sum(r is not None and r.replaceable for r in self.aim_rules) > 1:
            raise ValueError(f"card {self.person}: at most one aim is replaceable")
        return self

    def topics(self) -> tuple[Label, ...]:
        """The keys of every topic the person wants or holds to."""
        return (*self.wants, *self.holds_to)

    def face(self) -> CardFace:
        return CardFace.model_validate(self.model_dump(include=set(CardFace.model_fields)))

    def desk(self) -> Desk:
        return Desk.model_validate(self.model_dump(include=set(Desk.model_fields)))


NO_POST = "Without office"
"""The office line of a card whose person holds no post and had none of his own. [proposed]"""


class PostCause(StrEnum):
    """Why a post changed hands (PPP)."""

    APPOINTED = "appointed"
    """An order named the new holder, or nobody."""
    SUCCEEDED = "succeeded"
    """The post's designated successor took it when it fell vacant."""
    VACATED = "vacated"
    """Its holder left it to take another post."""


class PostPart(Model):
    """The part of a card that goes with its post (PPP): the office's name, its powers,
    authority, forms, pipelines and feeds, the bodies that answer its summons, whom it
    answers to and its designated successor. The rest of the card is the person's own.
    [proposed]"""

    office: Label = NO_POST
    powers: tuple[Label, ...] = ()
    authority: tuple[Domain, ...] = ()
    levers: tuple[Lever, ...] = ()
    pipelines: tuple[PipelineId, ...] = ()
    feeds: tuple[FeedId, ...] = ()
    chain: tuple[EntityId, ...] = ()
    principals: tuple[EntityId, ...] = ()
    successor: EntityId | None = None

    def is_empty(self) -> bool:
        return self == PostPart()


class Post(Model):
    """A post that has changed hands, as the fold keeps it (PPP). Engine only."""

    holder: EntityId | None
    """Who holds it now; None: nobody, and its office is the nation's."""
    part: PostPart
    last: EntityId | None = None
    """While nobody holds it, the last holder: the steps and executors that still name him
    name whoever takes the post next."""


def post_part(card: Desk) -> PostPart:
    """The fields of the post's kind as ``card`` carries them."""
    return PostPart(
        office=card.office,
        powers=card.powers,
        authority=card.authority,
        levers=card.levers,
        pipelines=card.pipelines,
        feeds=card.feeds,
        chain=card.reach.chain,
        principals=card.principals,
        successor=card.successor,
    )


def _union[T](own: tuple[T, ...], more: tuple[T, ...]) -> tuple[T, ...]:
    return (*own, *(x for x in more if x not in own))


def _named[T: Lever | Domain](own: tuple[T, ...], more: tuple[T, ...]) -> tuple[T, ...]:
    """``more`` over ``own``, one per name: the post's form or domain where both name one."""
    names: set[str] = {x.name for x in more}
    kept: tuple[T, ...] = tuple(x for x in own if x.name not in names)
    return kept + more


def with_part(card: SeatCard, part: PostPart, post: AssetId | None) -> SeatCard:
    """``card`` holding ``part`` over the person's own, which it keeps aside in ``own``.
    With ``post`` None, the card left with ``part`` alone: what was the person's own (PPP)."""
    if post is None:
        return card.model_copy(update={**_fields(card, part), "post": None, "own": None})
    own = post_part(card)
    merged = PostPart(
        office=part.office,
        powers=_union(own.powers, part.powers),
        authority=_named(own.authority, part.authority),
        levers=_named(own.levers, part.levers),
        pipelines=_union(own.pipelines, part.pipelines),
        feeds=_union(own.feeds, part.feeds),
        chain=_union(own.chain, part.chain),
        principals=_union(own.principals, part.principals),
        successor=part.successor,
    )
    kept = None if own.is_empty() else own
    return card.model_copy(update={**_fields(card, merged), "post": post, "own": kept})


def _fields(card: Desk, part: PostPart) -> dict[str, object]:
    return {
        "office": part.office,
        "powers": part.powers,
        "authority": part.authority,
        "levers": part.levers,
        "pipelines": part.pipelines,
        "feeds": part.feeds,
        "principals": part.principals,
        "successor": part.successor,
        "reach": card.reach.model_copy(update={"chain": part.chain}),
    }


def superiors(cards: Mapping[EntityId, Desk], person: EntityId) -> tuple[EntityId, ...]:
    """The chain of ``principals`` above ``person``, nearest first: each principal,
    then each principal's own, as far as cards go. A principal with no card (an
    electorate, a polity) ends its branch. Each person once, so a loop ends (CMD)."""
    out: list[EntityId] = []
    frontier = [person]
    while frontier:
        nxt: list[EntityId] = []
        for who in frontier:
            card = cards.get(who)
            for up in card.principals if card is not None else ():
                if up != person and up not in out:
                    out.append(up)
                    nxt.append(up)
        frontier = nxt
    return tuple(out)


__all__ = [
    "CHANNELS",
    "NO_POST",
    "Aim",
    "CardFace",
    "CardPath",
    "ChannelKind",
    "Conflict",
    "Contact",
    "Desk",
    "Domain",
    "Lever",
    "ParamKind",
    "ParamSpec",
    "ParamValue",
    "Post",
    "PostCause",
    "PostPart",
    "Reach",
    "SeatCard",
    "Tie",
    "Topic",
    "post_part",
    "superiors",
    "with_part",
    "words",
]


# The aims' rules name a win condition, and goals imports this module. A plain import
# works in either order; goals rebuilds SeatCard once it has defined AimRule.
import revisionist.core.goals  # noqa: E402, F401
