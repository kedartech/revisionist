"""Compile a world bible into the creation events of a campaign (build plan Layer 7).

Pure: the world file arrives already parsed and the campaign ID is given, so the
same world into the same campaign yields the same events. Every problem is found
before anything is emitted. The fold runs last, as a check on what was emitted.

A realism world compiles to the same creation events plus ``ruleset: realism`` on
``campaign_created``, one ``quantity_set`` per quantity and one ``cards_declared``.
A legacy world compiles exactly as before. A realism roster may list people who
have no card yet: ``compile_figure`` adds one person's card to a running campaign.
"""

from collections.abc import Callable, Mapping, Sequence
from itertools import pairwise

from pydantic import ValidationError

from revisionist.core import events as ev
from revisionist.core import roster
from revisionist.core.events import Event, Versions
from revisionist.core.fold import FoldError, replay
from revisionist.core.goals import (
    MAX_DEPTH,
    MAX_PARTS,
    AllOf,
    AnyOf,
    Goal,
    Ordered,
    WinCondition,
    depth,
    goal_kind,
    goal_met,
    leaves,
    parts,
    progress,
)
from revisionist.core.ids import (
    AssetId,
    CampaignId,
    ClockId,
    CommitmentId,
    ContestId,
    EntityId,
    EventId,
    FactId,
    FeatureId,
    FeedId,
    GoalId,
    MeterId,
    PipelineId,
    QuantityId,
    RelationshipId,
    ScheduledEventId,
    SeatId,
    derived_id,
)
from revisionist.core.ontology import (
    Asset,
    AssetKind,
    Character,
    CharacterSide,
    Clause,
    Clock,
    ClockKind,
    Commitment,
    Contest,
    ContestKind,
    Controller,
    Entity,
    EntityKind,
    Fact,
    Meter,
    Persona,
    Relationship,
    ScheduledEvent,
    ScheduleSource,
    Seat,
    SeatKind,
)
from revisionist.core.realism import kinds
from revisionist.core.realism import territory as tm
from revisionist.core.realism.agenda import MandateKind, MandateTemplate, Trigger, TriggerKind
from revisionist.core.realism.answer import ENTITY_FIELDS, Answer, ParamValue
from revisionist.core.realism.card import (
    Conflict,
    Contact,
    Domain,
    Lever,
    ParamKind,
    ParamSpec,
    Reach,
    SeatCard,
    Topic,
)
from revisionist.core.realism.document import Feed
from revisionist.core.realism.effect import (
    ESTIMATED_ONLY,
    EffectKind,
    MoveFigure,
    MoveForce,
    SetEngagement,
    ShiftDisposition,
)
from revisionist.core.realism.geography import AT_ONE_PLACE, FORCES, Feature, FeatureKind, Leg
from revisionist.core.realism.kinds import Domain as PieceDomain
from revisionist.core.realism.kinds import PieceKind, Resource, Role
from revisionist.core.realism.pipeline import Pipeline, Step
from revisionist.core.realism.quantity import Quantity
from revisionist.core.realism.trade import TradeLine
from revisionist.core.realism.war import Outlet, War, war_id_for
from revisionist.core.state import Rule, State
from revisionist.core.visibility import PUBLIC, Scope, Visibility, private_to
from revisionist.core.world import (
    CardDecl,
    Cited,
    ClauseDecl,
    DevelopmentDecl,
    EntityDecl,
    FeatureDecl,
    FigureDecl,
    GoalDecl,
    LeverDecl,
    LinkDecl,
    MandateDecl,
    PieceKindDecl,
    ScopeDecl,
    ScopeSpec,
    SeaZoneDecl,
    TerritoryDecl,
    TopicDecl,
    WorldFile,
)


class WorldError(ValueError):
    """Every problem in the world file, one per line, sorted."""

    problems: tuple[str, ...]

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(sorted(problems))
        super().__init__("\n".join(self.problems))


def object_id(campaign_id: CampaignId, section: str, key: str) -> str:
    return derived_id(campaign_id, section, key)


def resolve_keys(world: WorldFile, campaign_id: CampaignId) -> dict[str, str]:
    """key -> ID for every keyed object in the world. Raises WorldError on duplicate keys."""
    problems: list[str] = []
    sections = _index(world, problems)
    if problems:
        raise WorldError(problems)
    return {key: object_id(campaign_id, section, key) for key, section in sections.items()}


def compile_world(world: WorldFile, campaign_id: CampaignId, versions: Versions) -> list[Event]:
    """Validate everything first, then emit events. Raises WorldError listing ALL problems."""
    problems: list[str] = []
    sections = _index(world, problems)
    _check(world, sections, problems)
    if problems:
        raise WorldError(problems)

    ids = {key: object_id(campaign_id, section, key) for key, section in sections.items()}
    emitted = _emit(world, ids, sections)
    if Rule.FUEL in world.rules:
        emitted += _stocks(world, ids, _events(emitted, campaign_id, versions))
    events = _events(emitted, campaign_id, versions)
    try:
        state = replay(events)
    except FoldError as exc:
        raise WorldError([f"fold: {exc}"]) from exc
    met = [f"goal {g.key}: already met at tick 0" for g in world.goals if _met(state, g, ids)]
    if met:
        raise WorldError(met)
    if state.contests:
        unfit = roster.problems(state)
        if unfit:
            raise WorldError(unfit)
    return [_started(e, state) for e in events]


def _events(
    emitted: Sequence[tuple[ev.Payload, Scope]], campaign_id: CampaignId, versions: Versions
) -> list[Event]:
    return [
        Event(
            event_id=EventId(derived_id(campaign_id, "event", str(seq))),
            campaign_id=campaign_id,
            seq=seq,
            tick=0,
            actor=None,
            scope=scope,
            payload=payload,
            versions=versions,
        )
        for seq, (payload, scope) in enumerate(emitted)
    ]


def _stocks(
    world: WorldFile, ids: Mapping[str, str], events: Sequence[Event]
) -> list[tuple[ev.Payload, Scope]]:
    """Each nation's fuel stock on the start date (FUL): the world's figure, or
    ``trade.STOCK_MONTHS`` of its fuel income; none for a nation that starts with none.
    Engine only, as ``economy_set`` always is."""
    from revisionist.core.realism import economy
    from revisionist.core.realism.trade import STOCK_MONTHS

    assert world.start_date is not None  # checked before emitting
    try:
        state = replay(events)
    except FoldError as exc:
        raise WorldError([f"fold: {exc}"]) from exc
    given = {f.polity: f.amount for f in world.fuel_stocks}
    out: list[tuple[ev.Payload, Scope]] = []
    for d in world.entities:
        if d.kind is not EntityKind.POLITY:
            continue
        polity = EntityId(ids[d.key])
        amount = given.get(d.key)
        if amount is None:
            amount = STOCK_MONTHS * economy.income(state, polity, Role.FUEL, world.start_date)
        if amount:
            pools = economy.Pools(fuel=round(amount, 6))
            out.append((ev.EconomySet(polity=polity, pools=pools, on=world.start_date), PUBLIC))
    return out


def _started(event: Event, state: State) -> Event:
    """A goal's objective clock starts at the parts the world already gives it."""
    p = event.payload
    if not isinstance(p, ev.ClockCreated) or p.clock.kind is not ClockKind.OBJECTIVE:
        return event
    goal = next((g for g in state.goals.values() if g.clock_id == p.clock.clock_id), None)
    if goal is None:
        return event
    clock = p.clock.model_copy(update={"segments_filled": progress(state, goal.condition)})
    return event.model_copy(update={"payload": ev.ClockCreated(clock=clock)})


# --- keys and references ------------------------------------------------------


def _keyed(world: WorldFile) -> list[tuple[str, str]]:
    """Every keyed object in file order, as (section, key)."""
    keyed = [("entity", d.key) for d in world.entities]
    keyed += [("entity", d.key) for d in _area_decls(world)]
    keyed += [("asset", d.key) for d in world.assets]
    keyed += [("relationship", d.key) for d in world.relationships]
    keyed += [("meter", d.key) for d in world.meters]
    keyed += [("clock", d.key) for d in world.clocks]
    keyed += [("fact", d.key) for d in world.facts]
    keyed += [("commitment", d.key) for d in world.commitments]
    keyed += [("seat", d.key) for d in world.seats]
    keyed += [("goal", d.key) for d in world.goals]
    keyed += [("contest", d.key) for d in world.contests]
    keyed += [("history", d.key) for d in world.schedule]
    keyed += [("source", d.key) for d in world.sources]
    keyed += [("quantity", d.key) for d in world.quantities]
    keyed += [("feature", d.key) for d in world.features]
    keyed += [("feed", d.key) for d in world.feeds]
    keyed += [("pipeline", d.key) for d in world.pipelines]
    keyed += [("mandate", d.key) for d in world.mandates]
    keyed += [("development", d.key) for d in world.developments]
    keyed += [("topic", d.key) for d in world.topics]
    return keyed


def _index(world: WorldFile, problems: list[str]) -> dict[str, str]:
    """key -> section. A repeated key is a problem; the first declaration is kept."""
    sections: dict[str, str] = {}
    for section, key in _keyed(world):
        if key in sections:
            problems.append(f"{section} {key}: duplicate key")
        else:
            sections[key] = section
    return sections


def _ref(
    problems: list[str], where: str, ref: str | None, expected: str, sections: Mapping[str, str]
) -> None:
    if ref is None:
        return
    actual = sections.get(ref)
    if actual is None:
        problems.append(f"{where}: unknown {expected} {ref}")
    elif actual != expected:
        problems.append(f"{where}: {ref} is a {actual}, not a {expected}")


def _refs(
    problems: list[str],
    where: str,
    refs: Sequence[str],
    expected: str,
    sections: Mapping[str, str],
) -> None:
    for ref in refs:
        _ref(problems, where, ref, expected, sections)


def _check_scope(
    problems: list[str], where: str, spec: ScopeSpec, sections: Mapping[str, str]
) -> None:
    if not isinstance(spec, ScopeDecl):
        return
    if spec.visibility is Visibility.PUBLIC or not spec.known_by:
        problems.append(f"{where}: bad scope")
    _refs(problems, where, spec.known_by, "seat", sections)


# --- validation ---------------------------------------------------------------


def _check_developments(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    if world.developments and world.start_date is None:
        problems.append("developments: a deck needs a start_date")
    for d in world.developments:
        where = f"development {d.key}"
        if world.start_date is not None and d.window.start < world.start_date:
            problems.append(f"{where}: its window opens before the start date")
        if d.condition is not None:
            if depth(d.condition) > MAX_DEPTH or len(leaves(d.condition)) > MAX_PARTS:
                problems.append(f"{where}: condition too large")
            for leaf in leaves(d.condition):
                for name, section in _CONDITION_REFS.items():
                    _ref(problems, where, getattr(leaf, name, None), section, sections)
        _refs(problems, where, [k for k in (d.subject, d.obj) if k is not None], "entity", sections)
        for e in d.effects:
            if isinstance(e, FigureDecl):
                _ref(problems, where, e.quantity, "quantity", sections)
            else:
                _refs(problems, where, [e.of, e.toward], "entity", sections)


def _check(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    _check_entities(world, sections, problems)
    _check_assets(world, sections, problems)
    _check_relationships(world, sections, problems)
    _check_meters(world, sections, problems)
    _check_clocks(world, sections, problems)
    _check_facts(world, sections, problems)
    _check_commitments(world, sections, problems)
    _check_seats(world, sections, problems)
    _check_goals(world, sections, problems)
    _check_roster(world, sections, problems)
    _check_v3(world, sections, problems)
    _check_realism(world, sections, problems)


ROSTER_MIN, ROSTER_MAX = 8, 12
PLACES_MIN = 6
CONTESTS_MAX = 3


def check_history(world: WorldFile) -> list[str]:
    """What a drafted historical world must also be (spec §5), beyond compiling.

    Humans arrive at the character step and goals at the goal step, so a draft
    has neither; the roster offers 8-12 people to choose from. Factions need
    holdings they can act with, so their people must be linked to them.
    """
    problems: list[str] = []
    if not world.start.strip():
        problems.append("world: no start (place and date)")
    if not ROSTER_MIN <= len(world.roster) <= ROSTER_MAX:
        problems.append(f"roster: {len(world.roster)} characters, not {ROSTER_MIN}-{ROSTER_MAX}")
    for s in world.seats:
        if s.controller is Controller.HUMAN:
            problems.append(f"seat {s.key}: a draft has no human seats")
    if world.goals:
        problems.append("goals: a draft has none; players choose them")
    # Every territory and sea zone is a location entity too.
    places = len([d for d in world.entities if d.kind is EntityKind.LOCATION])
    places += len(world.territories) + len(world.sea_zones)
    if places < PLACES_MIN:
        problems.append(f"places: {places} locations, at least {PLACES_MIN}")
    for a in world.assets:
        if a.kind is AssetKind.FORCE and a.location is None:
            problems.append(f"asset {a.key}: a force needs a location")
    parent = {d.key: d.parent for d in world.entities}
    controllers = {a.controller for a in world.assets}
    for d in world.entities:
        if d.kind is EntityKind.PERSON and d.parent is None and d.key in controllers:
            problems.append(f"entity {d.key}: holds assets but has no parent faction")
    for s in world.seats:
        if s.kind is SeatKind.FACTION and s.controller is Controller.AI:
            held = s.embodies in controllers or any(
                parent.get(c) == s.embodies for c in controllers
            )
            if not held:
                problems.append(
                    f"seat {s.key}: {s.embodies} holds no assets; "
                    f"set its people's parent to {s.embodies}"
                )
    if world.start_date is not None and not 1 <= len(world.contests) <= CONTESTS_MAX:
        problems.append(f"contests: {len(world.contests)}, not 1-{CONTESTS_MAX}")
    return problems


def _check_v3(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    """Contests, history's clock and roster sides (spec §5.3-5.5)."""
    contests = {d.key: d for d in world.contests}
    for k in world.contests:
        where = f"contest {k.key}"
        for side in k.sides:
            _ref(problems, where, side, "entity", sections)
        if len(set(k.sides)) != len(k.sides):
            problems.append(f"{where}: a side is named twice")
        if k.kind is ContestKind.RIVALRY and len(k.sides) < 2:
            problems.append(f"{where}: a rivalry has at least two sides")
        if k.kind is ContestKind.TRIAL and len(k.sides) != 1:
            problems.append(f"{where}: a trial has one power under trial")
        if k.kind is ContestKind.TRIAL and k.track < 0:
            problems.append(f"{where}: a trial's track runs 0..100")
    if world.schedule and world.start_date is None:
        problems.append("schedule: history's clock needs a start_date")
    for h in world.schedule:
        where = f"history {h.key}"
        if world.start_date is not None and h.on_date < world.start_date:
            problems.append(f"{where}: dated before the start date")
        if depth(h.condition) > MAX_DEPTH or len(leaves(h.condition)) > MAX_PARTS:
            problems.append(f"{where}: condition too large")
        for leaf in leaves(h.condition):
            for name, section in _CONDITION_REFS.items():
                _ref(problems, where, getattr(leaf, name, None), section, sections)
        _ref(problems, where, h.subject, "entity", sections)
        _ref(problems, where, h.obj, "entity", sections)
    _check_developments(world, sections, problems)
    for c in world.roster:
        where = f"character {c.entity}"
        seen: set[str] = set()
        for s in c.sides:
            _ref(problems, where, s.contest, "contest", sections)
            if s.contest in seen:
                problems.append(f"{where}: two sides in contest {s.contest}")
            seen.add(s.contest)
            decl = contests.get(s.contest)
            if decl is not None and s.side not in decl.sides:
                problems.append(f"{where}: {s.side} is not a side of {s.contest}")


def _check_realism(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    """Cards, feeds, pipelines, quantities and their citations (realism direction)."""
    if world.ruleset == "legacy":
        for name in (
            "cards",
            "feeds",
            "pipelines",
            "quantities",
            "features",
            "sources",
            "mandates",
            "outlets",
            "topics",
            "wars",
            "rules",
            "map",
            "terrain",
            "regions",
            "territories",
            "sea_zones",
            "adjacency",
            "resources",
            "piece_kinds",
            "fuel_stocks",
            "trade_lines",
        ):
            if getattr(world, name):
                problems.append(f"{name}: only a realism world has {name}")
        return
    if world.start_date is None:
        problems.append("world: a realism world needs a start_date")
    _check_board(world, sections, problems)
    _check_kinds(world, problems)
    for seat in world.seats:
        if seat.controller is Controller.HUMAN:
            problems.append(f"seat {seat.key}: a realism world names no human seat")
    people = {d.key for d in world.entities if d.kind is EntityKind.PERSON}

    def person(where: str, key: str | None) -> None:
        _ref(problems, where, key, "entity", sections)
        if key is not None and key in sections and key not in people:
            problems.append(f"{where}: {key} is not a person")

    for q in world.quantities:
        where = f"quantity {q.key}"
        _ref(problems, where, q.owner, "entity", sections)
        _check_cited(problems, where, q, sections)
    for f in world.feeds:
        where = f"feed {f.key}"
        person(where, f.author)
        _refs(problems, where, f.reports, "quantity", sections)
        _refs(problems, where, f.sights, "feature", sections)
        _check_cited(problems, where, f, sections)
    _check_features(world, sections, problems)
    for pl in world.pipelines:
        where = f"pipeline {pl.key}"
        for step in pl.steps:
            person(where, step.person)
        _check_cited(problems, where, pl, sections)
    carded: set[str] = set()
    for c in world.cards:
        where = f"card {c.person}"
        person(where, c.person)
        if c.person in carded:
            problems.append(f"{where}: a second card for one person")
        carded.add(c.person)
        _refs(problems, where, c.principals, "entity", sections)
        for k in c.inner_circle:
            person(where, k.person)
        _refs(problems, where, c.reach.chain, "entity", sections)
        _refs(problems, where, c.allies, "entity", sections)
        _refs(problems, where, [x.against for x in c.opposes], "entity", sections)
        domains = [dm.name for dm in c.authority]
        if len(set(domains)) != len(domains):
            problems.append(f"{where}: an authority domain is named twice")
        if c.playable and c.authority and all(k.person == c.person for k in c.inner_circle):
            problems.append(f"{where}: has authority but no inner circle to sign its reports")
        for dm in c.authority:
            person(f"{where}: domain {dm.name}", dm.executor)
            if dm.executor == c.person:
                problems.append(f"{where}: domain {dm.name}: the person is their own executor")
            if ESTIMATED_ONLY.intersection(dm.effects):
                problems.append(
                    f"{where}: domain {dm.name}: figure is not something an office orders"
                )
            _refs(problems, f"{where}: domain {dm.name}", dm.forces, "feature", sections)
        _refs(problems, where, c.feeds, "feed", sections)
        _refs(problems, where, c.pipelines, "pipeline", sections)
        _refs(problems, where, [*c.wants, *c.holds_to], "topic", sections)
        person(where, c.successor)
        levers = [lv.name for lv in c.levers]
        if len(set(levers)) != len(levers):
            problems.append(f"{where}: a lever is named twice")
        for lv in c.levers:
            if lv.pipeline not in c.pipelines:
                problems.append(f"{where}: lever {lv.name} names a pipeline not on the card")
            if lv.resolver not in _registered():
                problems.append(
                    f"{where}: lever {lv.name}: the rule name has no rule yet: {lv.resolver}"
                )
            if lv.resolver == "movement":
                _check_movement(world, f"{where}: lever {lv.name}", lv, problems)
    _check_answers(world, sections, problems)
    _check_topics(world, problems)
    _check_wars(world, sections, problems)
    _check_trade(world, sections, problems)
    playable = {c.person for c in world.cards if c.playable}
    listed = {ch.entity for ch in world.roster}
    # A listed person with no card yet is built when picked (compile_figure).
    for key in sorted((listed & carded) - playable):
        problems.append(f"character {key}: a realism roster lists only playable cards")
    for key in sorted(playable - listed):
        problems.append(f"card {key}: playable, so it must be on the roster")
    polities = {d.key for d in world.entities if d.kind is EntityKind.POLITY}
    orgs = {d.key for d in world.entities if d.kind is EntityKind.ORG}
    for o in world.outlets:
        where = f"outlet {o.key}"
        _ref(problems, where, o.key, "entity", sections)
        _ref(problems, where, o.polity, "entity", sections)
        if o.key in sections and o.key not in orgs:
            problems.append(f"{where}: {o.key} is not an org")
        if o.polity in sections and o.polity not in polities:
            problems.append(f"{where}: {o.polity} is not a polity")
    for m in world.mandates:
        where = f"mandate {m.key}"
        try:
            Trigger.model_validate(m.trigger.model_dump())
        except ValidationError as exc:
            problems.append(f"{where}: {exc.errors()[0]['msg']}")
        _ref(problems, where, m.trigger.history, "history", sections)
        _ref(problems, where, m.trigger.quantity, "quantity", sections)
        for key in m.to:
            person(where, key)
        _ref(problems, where, m.issuer, "entity", sections)
        if (m.kind is MandateKind.ORDER) != (m.issuer is not None):
            problems.append(f"{where}: an order, and only an order, has an issuer")
        if depth(m.condition) > MAX_DEPTH or len(leaves(m.condition)) > MAX_PARTS:
            problems.append(f"{where}: condition too large")
        for leaf in leaves(m.condition):
            for name, section in _CONDITION_REFS.items():
                _ref(problems, where, getattr(leaf, name, None), section, sections)


def _check_wars(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    """Each war between two distinct polities, under way by the start date, once per pair."""
    names = {d.key: d.name for d in world.entities if d.kind is EntityKind.POLITY}
    at_war: set[frozenset[str]] = set()
    for w in world.wars:
        where = f"war {w.a}-{w.b}"
        _refs(problems, where, [w.a, w.b], "entity", sections)
        for side in (w.a, w.b):
            if sections.get(side) == "entity" and side not in names:
                problems.append(f"{where}: {side} is not a polity")
        _check_cited(problems, where, w, sections)
        if world.start_date is not None and w.since > world.start_date:
            problems.append(f"{where}: begins after the start date")
        if w.a == w.b:
            problems.append(f"{where}: a power cannot be at war with itself")
        elif frozenset((w.a, w.b)) in at_war:
            a, b = names.get(w.a, w.a), names.get(w.b, w.b)
            problems.append(f"{where}: {a} and {b} are already at war")
        at_war.add(frozenset((w.a, w.b)))
    if len(set(world.rules)) != len(world.rules):
        problems.append("rules: a rule is named twice")


def _fits(spec: ParamSpec, value: ParamValue, sections: Mapping[str, str]) -> bool:
    match spec.kind:
        case ParamKind.INT:
            lo, hi = spec.lo, spec.hi
            return (
                isinstance(value, int) and lo is not None and hi is not None and lo <= value <= hi
            )
        case ParamKind.ENUM:
            return value in spec.choices
        case ParamKind.ENTITY:
            return isinstance(value, str) and sections.get(value) == "entity"
        case ParamKind.TEXT:
            return isinstance(value, str) and bool(value.strip())
    return False


def _check_trade(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    """Fuel stocks and trade lines (FUL): only with ``fuel`` on, between polities, each
    line carrying a resource whose role a nation keeps a pool of."""
    from revisionist.core.realism.trade import PAID_ROLES

    if Rule.FUEL not in world.rules:
        if world.fuel_stocks or world.trade_lines:
            problems.append("rules: fuel stocks and trade lines need fuel")
        return
    polities = {d.key for d in world.entities if d.kind is EntityKind.POLITY}
    roles = {r.key: r.role for r in world.resources}
    if not any(r is Role.FUEL for r in roles.values()):
        problems.append("rules: fuel needs a resource with the fuel role")
    stocked: set[str] = set()
    for f in world.fuel_stocks:
        where = f"fuel stock {f.polity}"
        _check_cited(problems, where, f, sections)
        if f.polity not in polities:
            problems.append(f"{where}: {f.polity} is not a polity")
        if f.polity in stocked:
            problems.append(f"{where}: named twice")
        stocked.add(f.polity)
    keys: set[str] = set()
    for line in world.trade_lines:
        where = f"trade line {line.key}"
        _check_cited(problems, where, line, sections)
        if line.key in keys:
            problems.append(f"{where}: duplicate key")
        keys.add(line.key)
        for side in (line.exporter, line.importer):
            if side not in polities:
                problems.append(f"{where}: {side} is not a polity")
        if line.exporter == line.importer:
            problems.append(f"{where}: a line runs between two nations")
        if roles.get(line.resource) not in PAID_ROLES:
            problems.append(f"{where}: {line.resource} is not output, manpower or fuel")


def _check_answers(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    """Every answer names things that exist, sets off on a form someone has, and acts
    by the person's own form or inside their authority."""
    forms: dict[str, list[LeverDecl]] = {}
    for c in world.cards:
        for lv in c.levers:
            forms.setdefault(lv.name, []).append(lv)
    for c in world.cards:
        own = {lv.name: lv for lv in c.levers}
        for a in c.answers:
            where = f"card {c.person}: answer {a.key}"
            if a.aim > len(c.aims):
                problems.append(f"{where}: the card has no aim {a.aim}")
            when, act = a.when, a.act
            _ref(problems, where, when.by, "entity", sections)
            _ref(problems, where, when.party, "entity", sections)
            _ref(problems, where, a.until, "history", sections)
            used = [p for lv in forms.get(when.lever or "", []) for p in lv.params]
            used += [p for p in own[act.lever].params] if act.lever in own else []
            named = set(when.params) | set(act.params)
            if any(sp.kind is ParamKind.ENTITY and sp.name in named for sp in used):
                problems.append(f"{where}: names a person or place by a form's parameter")
            if when.lever is not None:
                found = forms.get(when.lever, [])
                if not found:
                    problems.append(f"{where}: no card has a form {when.lever}")
                for name, values in when.params.items():
                    specs = [p for lv in found for p in lv.params if p.name == name]
                    if found and not specs:
                        problems.append(f"{where}: no form {when.lever} takes {name}")
                    for v in values:
                        if specs and not any(_fits(sp, v, sections) for sp in specs):
                            problems.append(f"{where}: {name} {v} fits no form {when.lever}")
            if act.lever is not None:
                lever = own.get(act.lever)
                if lever is None:
                    problems.append(f"{where}: {c.person} has no form {act.lever}")
                    continue
                if set(act.params) != {p.name for p in lever.params}:
                    problems.append(f"{where}: {act.lever} takes exactly its own parameters")
                for sp in lever.params:
                    given = act.params.get(sp.name)
                    if given is not None and not _fits(sp, given, sections):
                        problems.append(f"{where}: {sp.name} {given} does not fit {act.lever}")
            elif act.effect is not None:
                kind = EffectKind(act.effect.kind)
                domains = [dm for dm in c.authority if kind in dm.effects]
                if not domains:
                    problems.append(f"{where}: {kind.value} is outside {c.person}'s authority")
                for name in ENTITY_FIELDS:
                    ref = getattr(act.effect, name, None)
                    if isinstance(ref, str):
                        _ref(problems, where, ref, "entity", sections)
                force = getattr(act.effect, "force", None)
                if force is not None:
                    _ref(problems, where, force, "feature", sections)
                    if domains and not any(force in dm.forces for dm in domains):
                        problems.append(f"{where}: {force} is not under {c.person}")


def _check_topics(world: WorldFile, problems: list[str]) -> None:
    """A topic names only levers some card has and effect kinds the engine knows."""
    levers = {lv.name for c in world.cards for lv in c.levers}
    kinds = {k.value for k in EffectKind}
    for t in world.topics:
        problems += [f"topic {t.key}: unknown lever {x}" for x in t.levers if x not in levers]
        problems += [f"topic {t.key}: unknown effect kind {x}" for x in t.effects if x not in kinds]


def _topic(t: TopicDecl) -> Topic:
    return Topic(
        key=t.key,
        name=t.name,
        levers=t.levers,
        effects=tuple(EffectKind(x) for x in t.effects),
        words=t.words,
    )


def _placed(world: WorldFile) -> set[str]:
    return {d.key for d in world.entities if d.kind is EntityKind.LOCATION and d.at is not None}


def _check_features(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    """Places with a position, the right number of them, and sides that can hold forces."""
    for d in world.entities:
        if d.at is not None and d.kind is not EntityKind.LOCATION:
            problems.append(f"entity {d.key}: only a place has a position")
        if d.theatre is not None and d.kind is not EntityKind.LOCATION:
            problems.append(f"entity {d.key}: only a place has a theatre")
    placed = _placed(world)
    bodies = {
        d.key
        for d in world.entities
        if d.kind in (EntityKind.POLITY, EntityKind.ORG, EntityKind.FACTION)
    }
    start = world.start_date
    areas = set(_area_kinds(world)) if Rule.TERRITORIES in world.rules else set()
    for f in world.features:
        where = f"feature {f.key}"
        _ref(problems, where, f.side, "entity", sections)
        if f.side is not None and f.side in sections and f.side not in bodies:
            problems.append(f"{where}: {f.side} is not a polity or body")
        if f.kind in FORCES and f.side is None:
            problems.append(f"{where}: a force belongs to a side")
        domain = _check_piece(world, where, f, problems)
        legs = [(f.as_of or start, f.places), *((leg.since, leg.places) for leg in f.legs)]
        for n, (_, places) in enumerate(legs):
            at = where if n == 0 else f"{where} leg {n}"
            _refs(problems, at, places, "entity", sections)
            for p in places:
                if p in sections and p not in placed and not (n and p in areas):
                    problems.append(f"{at}: {p} is not a place with a position")
            if f.kind in AT_ONE_PLACE and len(places) != 1:
                problems.append(f"{at}: a force is at one place")
            if f.kind not in AT_ONE_PLACE and len(places) < 2:
                problems.append(f"{at}: a {f.kind.value} joins two places or more")
            if domain is not None:
                _check_stands(world, at, domain, places, problems)
        days = [on for on, _ in legs]
        if any(a is not None and b is not None and b <= a for a, b in pairwise(days)):
            problems.append(f"{where}: legs run forward in time")
        _check_takes(world, where, f, problems)
        _check_cited(problems, where, f, sections)


def _check_takes(world: WorldFile, where: str, f: FeatureDecl, problems: list[str]) -> None:
    """A leg's ``takes`` need ``holders`` on, belong to a piece and name territories (HSA
    rule 3)."""
    land = {t.key for t in world.territories}
    for n, leg in enumerate(f.legs, start=1):
        if leg.takes and Rule.HOLDERS not in world.rules:
            problems.append(f"{where} leg {n}: takes needs the holders rule")
        if leg.takes and f.kind is not FeatureKind.PIECE:
            problems.append(f"{where} leg {n}: only a piece's leg takes territories")
        for k in leg.takes:
            if k not in land:
                problems.append(f"{where} leg {n}: takes {k}, which is not a territory")


def _check_piece(
    world: WorldFile, where: str, f: FeatureDecl, problems: list[str]
) -> PieceDomain | None:
    """A piece names one of the world's kinds; a world with kinds has no army, fleet or air feature.
    Returns the piece's domain, or None when it has none to check."""
    declared = {k.key: k for k in world.piece_kinds}
    if f.kind is not FeatureKind.PIECE:
        if f.piece is not None:
            problems.append(f"{where}: only a piece names a piece kind")
        if world.piece_kinds and f.kind in FORCES:
            problems.append(f"{where}: this world's forces are pieces of its own kinds")
        return None
    if f.side is None:
        problems.append(f"{where}: a piece belongs to a side")
    if not world.piece_kinds:
        problems.append(f"{where}: a piece needs the world's piece_kinds")
        return None
    if f.piece is None:
        problems.append(f"{where}: a piece names its kind")
        return None
    kind = declared.get(f.piece)
    if kind is None:
        problems.append(f"{where}: unknown piece kind {f.piece}")
        return None
    return kind.domain


def _area_kinds(world: WorldFile) -> dict[str, tm.TerrainKind]:
    """Each area's kind: land for a territory, sea for a sea zone."""
    return {
        **{t.key: tm.TerrainKind.LAND for t in world.territories},
        **{z.key: tm.TerrainKind.SEA for z in world.sea_zones},
    }


def _check_stands(
    world: WorldFile, where: str, domain: PieceDomain, places: Sequence[str], problems: list[str]
) -> None:
    """A piece stands only in an area its domain can stand in: the area a place lies
    within, or the area itself."""
    areas = _area_kinds(world)
    for p in places:
        area = _stand_area(world, p, domain)
        if area is not None and area in areas and not kinds.stands_on(domain, areas[area]):
            problems.append(f"{where}: a {domain.value} piece cannot stand in {area}")
        elif area is None and Rule.TERRITORIES in world.rules:
            problems.append(f"{where}: {p} lies in no area, and a piece stands in one")


def _stand_area(world: WorldFile, place: str, domain: PieceDomain) -> str | None:
    """The area a piece of ``domain`` stands in at ``place``: the area itself, a sea piece
    at a port the zone the port opens on, else the area the place lies within."""
    if place in _area_kinds(world):
        return place
    decl = next((d for d in world.entities if d.key == place), None)
    if decl is None:
        return None
    if domain is PieceDomain.SEA and decl.port_on is not None:
        return decl.port_on
    return decl.within


def _check_kinds(world: WorldFile, problems: list[str]) -> None:
    """Piece kinds that can step on every terrain of their domain, resources named once,
    and yields of resources the world names (realism only)."""
    resources: set[str] = set()
    for r in world.resources:
        if r.key in resources:
            problems.append(f"resource {r.key}: duplicate key")
        resources.add(r.key)
    for t in world.territories:
        for key in t.yields:
            if key not in resources:
                problems.append(f"territory {t.key}: yields unknown resource {key}")
    if not world.piece_kinds:
        return
    if world.map is None:
        problems.append("piece_kinds: a world with piece kinds needs a map")
        return
    terrain = {t.key: t.kind for t in world.terrain}
    names: set[str] = set()
    for k in world.piece_kinds:
        if k.key in names:
            problems.append(f"piece kind {k.key}: duplicate key")
        names.add(k.key)
    for k in world.piece_kinds:
        where = f"piece kind {k.key}"
        allowed = kinds.steps_on(k.domain)
        for key in terrain:
            if terrain[key] in allowed and key not in k.days_per_step:
                problems.append(f"{where}: no days_per_step for {key}")
        for key in k.days_per_step:
            if key not in terrain:
                problems.append(f"{where}: unknown terrain {key}")
            elif terrain[key] not in allowed:
                problems.append(
                    f"{where}: {key} is {terrain[key].value} terrain, "
                    f"where a {k.domain.value} piece cannot step"
                )
        if k.domain is PieceDomain.AIR and k.range_steps is None:
            problems.append(f"{where}: an air kind needs range_steps")
        if k.domain is not PieceDomain.AIR and k.range_steps is not None:
            problems.append(f"{where}: only an air kind has range_steps")
        for lifted in k.carries:
            if lifted not in names:
                problems.append(f"{where}: carries unknown kind {lifted}")


def _check_movement(world: WorldFile, where: str, lever: LeverDecl, problems: list[str]) -> None:
    """A movement lever offers forces by key and places with a position by key."""
    params = {p.name: p for p in lever.params}
    forces = {f.key for f in world.features if f.kind in AT_ONE_PLACE}
    places = _placed(world) | ({d.key for d in _area_decls(world)} if world.map else set())
    for name, allowed, what in (("force", forces, "force"), ("to", places, "place")):
        spec = params.get(name)
        if spec is None or spec.kind is not ParamKind.ENUM:
            problems.append(f"{where}: needs an enum parameter {name}")
            continue
        for choice in spec.choices:
            if choice not in allowed:
                problems.append(f"{where}: {choice} is not a {what}")


def _check_cited(problems: list[str], where: str, decl: Cited, sections: Mapping[str, str]) -> None:
    _ref(problems, where, decl.source, "source", sections)


# --- the board (MDL) ------------------------------------------------------------------


def _area_decls(world: WorldFile) -> list[TerritoryDecl | SeaZoneDecl]:
    """Every territory, then every sea zone."""
    return [*world.territories, *world.sea_zones]


def _registered() -> frozenset[str]:
    """The rule names for forms that have a function on the order path. A name is added
    for forms (``RESOLVER_KEYS``) before the item that registers its function merges; a
    world naming it before then is refused, so no order reaches a name with no rule."""
    from revisionist.core.realism.resolvers import ON_ORDER

    return frozenset(ON_ORDER)


def _check_board(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    """The map, its regions, terrain, areas and adjacency (realism only)."""
    areas = {d.key for d in _area_decls(world)}
    if Rule.TERRITORIES in world.rules and world.map is None:
        problems.append("rules: territories needs a map")
    if Rule.HOLDERS in world.rules and Rule.TERRITORIES not in world.rules:
        problems.append("rules: holders needs territories")
    if Rule.ECONOMY in world.rules and Rule.HOLDERS not in world.rules:
        problems.append("rules: economy needs holders")
    if Rule.FUEL in world.rules and Rule.ECONOMY not in world.rules:
        problems.append("rules: fuel needs economy")
    if Rule.BATTLES in world.rules and Rule.TERRITORIES in world.rules:
        fights = {
            k.key for k in world.piece_kinds if k.domain in (PieceDomain.LAND, PieceDomain.SEA)
        }
        problems.extend(
            f"feature {d.key}: a piece that fights starts at strength 1 or more"
            for d in world.features
            if d.kind is FeatureKind.PIECE and d.piece in fights and d.tier < 1
        )
    if world.map is None:
        if areas or world.adjacency or world.regions or world.terrain:
            problems.append("map: the world has areas but no map")
        for e in world.entities:
            if e.port_on is not None or e.base is not None:
                problems.append(f"entity {e.key}: a port or a base needs a map")
            if e.capital is not None:
                problems.append(f"entity {e.key}: a capital needs a map")
        return
    _check_map_file(world, problems)
    _check_sites(world, problems)
    regions = _check_regions(world, problems)
    terrain: dict[str, tm.TerrainKind] = {}
    for td in world.terrain:
        if td.key in terrain:
            problems.append(f"terrain {td.key}: duplicate key")
        else:
            terrain[td.key] = td.kind
    for decl in _area_decls(world):
        land = isinstance(decl, TerritoryDecl)
        where = f"territory {decl.key}" if land else f"sea zone {decl.key}"
        want = tm.TerrainKind.LAND if land else tm.TerrainKind.SEA
        if decl.region not in regions:
            problems.append(f"{where}: unknown region {decl.region}")
        kind = terrain.get(decl.terrain)
        if kind is None:
            problems.append(f"{where}: unknown terrain {decl.terrain}")
        elif kind is not want:
            problems.append(f"{where}: {decl.terrain} is {kind} terrain, not {want}")
    kinds = {d.key: d.kind for d in world.entities}
    within = {d.key: d.within for d in world.entities}
    for t in world.territories:
        where = f"territory {t.key}"
        if t.holder is not None:
            if t.holder not in kinds:
                problems.append(f"{where}: unknown entity {t.holder}")
            elif kinds[t.holder] is not EntityKind.POLITY:
                problems.append(f"{where}: holder {t.holder} is not a polity")
        _check_cited(problems, where, t, sections)
        for site in t.sites:
            if site not in kinds:
                problems.append(f"{where}: unknown entity {site}")
            elif kinds[site] is not EntityKind.LOCATION:
                problems.append(f"{where}: site {site} is not a place")
            elif within[site] is not None and within[site] != t.key:
                problems.append(f"{where}: site {site} is within {within[site]}")
    for e in world.entities:
        if e.within is None:
            continue
        where = f"entity {e.key}"
        if e.kind is not EntityKind.LOCATION:
            problems.append(f"{where}: only a place lies within an area")
        elif e.within in areas:
            continue
        elif e.within in sections:
            problems.append(f"{where}: within {e.within}, which is not an area")
        else:
            problems.append(f"{where}: within unknown area {e.within}")
    _check_adjacency(world, areas, sections, problems)
    box = world.map.box
    if world.map.coords == "flat" and box is not None:
        west, south, east, north = box
        for d in world.entities:
            if d.at is not None and not (west <= d.at[1] <= east and south <= d.at[0] <= north):
                problems.append(
                    f"entity {d.key}: at [{d.at[0]:g}, {d.at[1]:g}] is outside the map's box"
                )


def _check_sites(world: WorldFile, problems: list[str]) -> None:
    """Ports open on a sea zone their territory borders, bases serve polities from a place
    in an area, and a lift pool is a quantity of a polity (ADJ); a capital is a place in a
    territory, or the territory, of a polity (THL)."""
    areas = _area_kinds(world)
    kinds_of = {d.key: d.kind for d in world.entities}
    quantities = {q.key for q in world.quantities}
    links = {
        frozenset((e.a, e.b) if isinstance(e, LinkDecl) else (e[0], e[1])) for e in world.adjacency
    }
    for e in world.entities:
        where = f"entity {e.key}"
        if e.port_on is not None:
            if e.kind is not EntityKind.LOCATION:
                problems.append(f"{where}: only a place is a port")
            elif areas.get(e.port_on) is not tm.TerrainKind.SEA:
                problems.append(f"{where}: port_on {e.port_on} is not a sea zone")
            elif e.within is None or areas.get(e.within) is not tm.TerrainKind.LAND:
                problems.append(f"{where}: a port lies within a territory")
            elif frozenset((e.within, e.port_on)) not in links:
                problems.append(f"{where}: {e.within} does not border {e.port_on}")
        if e.base is not None:
            if e.kind is not EntityKind.LOCATION or e.within is None:
                problems.append(f"{where}: a base is a place within an area")
            for side in e.base.sides:
                if kinds_of.get(side) is not EntityKind.POLITY:
                    problems.append(f"{where}: base side {side} is not a polity")
            if len(set(e.base.domains)) != len(e.base.domains):
                problems.append(f"{where}: a base names a domain twice")
        if e.lift_pool is not None:
            if e.kind is not EntityKind.POLITY:
                problems.append(f"{where}: only a polity has a lift pool")
            elif e.lift_pool not in quantities:
                problems.append(f"{where}: lift_pool {e.lift_pool} is not a quantity")
        if e.capital is not None:
            site = next((d for d in world.entities if d.key == e.capital), None)
            if e.kind is not EntityKind.POLITY:
                problems.append(f"{where}: only a polity has a capital")
            elif areas.get(e.capital) is tm.TerrainKind.LAND:
                pass
            elif site is None or site.kind is not EntityKind.LOCATION:
                problems.append(f"{where}: capital {e.capital} is not a place")
            elif site.within is None or areas.get(site.within) is not tm.TerrainKind.LAND:
                problems.append(f"{where}: capital {e.capital} lies within no territory")


def _check_map_file(world: WorldFile, problems: list[str]) -> None:
    """The map file the world names: found, the same bytes, the same areas."""
    ref = world.map
    assert ref is not None
    if ref.coords == "flat" and ref.box is None:
        problems.append("map: a flat map needs a box")
    if ref.box is not None and not (ref.box[0] < ref.box[2] and ref.box[1] < ref.box[3]):
        problems.append("map: box has west >= east or south >= north")
    data = world.map_data
    if data is None:
        problems.append(f"map: the map file {ref.file} is not found")
        return
    sha = tm.file_hash(data)
    if sha != ref.sha256:
        problems.append(f"map: the world names {ref.sha256}, but {ref.file} hashes to {sha}")
    found = tm.file_keys(data)
    if found is None:
        problems.append(f"map: {ref.file} is not a map file")
        return
    in_file, districts = found
    in_world = {d.key for d in _area_decls(world)}
    for key in sorted(in_file - in_world):
        problems.append(f"map: area {key} is in the map file but not in the world")
    for key in sorted(in_world - in_file):
        problems.append(f"map: area {key} is in the world but not in the map file")
    for d in world.territories:
        for district in d.districts:
            if district not in districts:
                problems.append(f"territory {d.key}: district {district} is not in the map file")


def _check_regions(world: WorldFile, problems: list[str]) -> set[str]:
    """The region tree: known parents and no cycle. Returns the region keys."""
    parent: dict[str, str | None] = {}
    for r in world.regions:
        if r.key in parent:
            problems.append(f"region {r.key}: duplicate key")
        else:
            parent[r.key] = r.parent
    for key, up in parent.items():
        if up is not None and up not in parent:
            problems.append(f"region {key}: unknown region {up}")
    for key in parent:
        seen, at = set(), parent[key]
        while at is not None and at in parent and at not in seen:
            if at == key:
                problems.append(f"region {key}: its parents lead back to it")
                break
            seen.add(at)
            at = parent[at]
    return set(parent)


def _check_adjacency(
    world: WorldFile, areas: set[str], sections: Mapping[str, str], problems: list[str]
) -> None:
    seen: set[frozenset[str]] = set()
    for entry in world.adjacency:
        a, b = (entry.a, entry.b) if isinstance(entry, LinkDecl) else entry
        where = f"adjacency {a}-{b}"
        bad = False
        for key in (a, b):
            if key in areas:
                continue
            bad = True
            if key in sections:
                problems.append(f"{where}: {key} is not an area")
            else:
                problems.append(f"{where}: unknown area {key}")
        if a == b:
            problems.append(f"{where}: links an area to itself")
        elif not bad and frozenset((a, b)) in seen:
            problems.append(f"{where}: listed twice")
        seen.add(frozenset((a, b)))


def _check_roster(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    people = {d.key for d in world.entities if d.kind is EntityKind.PERSON}
    held_by = {d.key: d.controller for d in world.assets}
    seen: set[str] = set()
    for c in world.roster:
        where = f"character {c.entity}"
        _ref(problems, where, c.entity, "entity", sections)
        if c.entity in sections and c.entity not in people:
            problems.append(f"{where}: not a person")
        if c.entity in seen:
            problems.append(f"{where}: listed twice")
        seen.add(c.entity)
        for m in c.means:
            _ref(problems, where, m, "asset", sections)
            if m in held_by and held_by[m] != c.entity:
                problems.append(f"{where}: does not control {m}")


def _check_entities(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    for d in world.entities:
        where = f"entity {d.key}"
        _ref(problems, where, d.parent, "entity", sections)
        _ref(problems, where, d.location, "entity", sections)
        if d.within is not None and world.map is None:
            problems.append(f"{where}: within {d.within}, but the world has no map")


def _check_assets(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    for d in world.assets:
        where = f"asset {d.key}"
        _ref(problems, where, d.controller, "entity", sections)
        _ref(problems, where, d.location, "entity", sections)
        _check_scope(problems, where, d.scope, sections)


def _check_relationships(
    world: WorldFile, sections: Mapping[str, str], problems: list[str]
) -> None:
    for d in world.relationships:
        where = f"relationship {d.key}"
        _ref(problems, where, d.a, "entity", sections)
        _ref(problems, where, d.b, "entity", sections)
        _check_scope(problems, where, d.scope, sections)


def _check_meters(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    for d in world.meters:
        where = f"meter {d.key}"
        _ref(problems, where, d.owner, "entity", sections)
        _check_scope(problems, where, d.scope, sections)
        if d.lo >= d.hi or not d.lo <= d.value <= d.hi:
            problems.append(f"{where}: out of range")


def _check_clocks(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    for d in world.clocks:
        where = f"clock {d.key}"
        _ref(problems, where, d.owner, "seat", sections)
        _ref(problems, where, d.target, "entity", sections)
        _check_scope(problems, where, d.scope, sections)
        if d.segments_filled > d.segments_total:
            problems.append(f"{where}: overfilled")


def _check_facts(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    canaries: set[str] = set()
    for d in world.facts:
        where = f"fact {d.key}"
        _ref(problems, where, d.subject, "entity", sections)
        _check_scope(problems, where, d.scope, sections)
        if d.canary is not None:
            if d.canary in canaries:
                problems.append(f"{where}: duplicate canary")
            canaries.add(d.canary)


def _check_commitments(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    for d in world.commitments:
        where = f"commitment {d.key}"
        _refs(problems, where, d.parties, "entity", sections)
        for clause in d.clauses:
            _check_clause(problems, where, clause, sections)
        _check_scope(problems, where, d.scope, sections)


def _check_clause(
    problems: list[str], where: str, clause: ClauseDecl, sections: Mapping[str, str]
) -> None:
    _ref(problems, where, clause.party, "entity", sections)
    _ref(problems, where, clause.beneficiary, "entity", sections)
    _ref(problems, where, clause.asset, "asset", sections)


def _check_seats(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    entity_kinds = {d.key: d.kind for d in world.entities}
    human = [d.key for d in world.seats if d.controller is Controller.HUMAN]
    if len(human) > world.settings.max_human_seats:
        problems.append(f"seat {human[-1]}: too many human seats")
    for d in world.seats:
        where = f"seat {d.key}"
        _ref(problems, where, d.embodies, "entity", sections)
        _refs(problems, where, d.objectives, "clock", sections)
        if d.agent is not None:
            _ref(problems, where, d.agent.entity, "entity", sections)
            if entity_kinds.get(d.agent.entity, EntityKind.PERSON) is not EntityKind.PERSON:
                problems.append(f"{where}: agent must be a person")


_CONDITION_REFS = {
    "holder": "entity",
    "office": "asset",
    "asset": "asset",
    "entity": "entity",
    "meter": "meter",
    "commitment": "commitment",
    "relationship": "relationship",
    "person": "entity",
    "quantity": "quantity",
}
"""Which section each reference field of a win condition names."""


def _check_goals(world: WorldFile, sections: Mapping[str, str], problems: list[str]) -> None:
    seats = {d.key: d for d in world.seats}
    offices = {d.key for d in world.assets if d.kind is AssetKind.OFFICE}
    canaries = {d.canary for d in world.facts if d.canary is not None}
    owners: set[str] = set()
    for g in world.goals:
        where = f"goal {g.key}"
        _ref(problems, where, g.seat, "seat", sections)
        seat = seats.get(g.seat)
        if seat is not None and seat.kind is not SeatKind.PLAYER:
            problems.append(f"{where}: only a player seat has a goal")
        if g.seat in owners:
            problems.append(f"{where}: seat {g.seat} already has a goal")
        owners.add(g.seat)
        if depth(g.condition) > MAX_DEPTH or len(leaves(g.condition)) > MAX_PARTS:
            problems.append(f"{where}: condition too large")
        for leaf in leaves(g.condition):
            for name, section in _CONDITION_REFS.items():
                ref = getattr(leaf, name, None)
                _ref(problems, where, ref, section, sections)
                if name == "office" and ref in sections and ref not in offices:
                    problems.append(f"{where}: {ref} is not an office")
        if g.canary is not None:
            if g.canary in canaries:
                problems.append(f"{where}: duplicate canary")
            canaries.add(g.canary)


def _development(d: DevelopmentDecl, ids: Mapping[str, str]) -> ScheduledEvent:
    effects: list[MoveFigure | ShiftDisposition] = [
        MoveFigure(quantity=QuantityId(ids[e.quantity]), percent=e.percent)
        if isinstance(e, FigureDecl)
        else ShiftDisposition(
            of=EntityId(ids[e.of]), toward=EntityId(ids[e.toward]), change=e.change
        )
        for e in d.effects
    ]
    return ScheduledEvent(
        scheduled_id=ScheduledEventId(ids[d.key]),
        fire_at_tick=0,
        name=d.name,
        scope=PUBLIC,
        source=ScheduleSource.DEVELOPMENT,
        on_date=d.window.start,
        condition=None if d.condition is None else _bind(d.condition, ids),
        headline=d.headline,
        subject=EntityId(ids[d.subject]),
        obj=_maybe(ids, d.obj, EntityId),
        category=d.category,
        window_end=d.window.end,
        chance=d.chance,
        effects=tuple(effects),
        asks=d.asks,
    )


def _bind(c: WinCondition, ids: Mapping[str, str]) -> WinCondition:
    """The same condition with every key replaced by its ID."""
    if isinstance(c, AllOf | AnyOf):
        return c.model_copy(update={"conditions": tuple(_bind(x, ids) for x in c.conditions)})
    update = {name: ids[getattr(c, name)] for name in _CONDITION_REFS if hasattr(c, name)}
    return c.model_copy(update=update)


def _goal_clock(goal_id: str) -> ClockId:
    return ClockId(derived_id(goal_id, "clock"))


def _met(state: State, g: GoalDecl, ids: Mapping[str, str]) -> bool:
    return goal_met(state, _bind(g.condition, ids))


# --- emission -----------------------------------------------------------------


def _maybe[T](ids: Mapping[str, str], key: str | None, to: Callable[[str], T]) -> T | None:
    return None if key is None else to(ids[key])


def _scope(spec: ScopeSpec, ids: Mapping[str, str]) -> Scope:
    if isinstance(spec, ScopeDecl):
        known = frozenset(SeatId(ids[key]) for key in spec.known_by)
        return Scope(visibility=spec.visibility, known_by=known)
    return PUBLIC


def _emit(
    world: WorldFile, ids: Mapping[str, str], sections: Mapping[str, str]
) -> list[tuple[ev.Payload, Scope]]:
    out: list[tuple[ev.Payload, Scope]] = [
        (
            ev.CampaignCreated(
                name=world.name,
                world=world.world,
                ruleset=world.ruleset,
                rules=frozenset(world.rules),
            ),
            PUBLIC,
        ),
        (ev.SettingsSet(settings=world.settings), PUBLIC),
    ]
    out += [(ev.EntityCreated(entity=e), PUBLIC) for e in _areas(world, ids)]
    out += [(ev.EntityCreated(entity=_entity(e, ids)), PUBLIC) for e in world.entities]
    for a in world.assets:
        scope = _scope(a.scope, ids)
        asset = Asset(
            asset_id=AssetId(ids[a.key]),
            kind=a.kind,
            name=a.name,
            tier=a.tier,
            controller=EntityId(ids[a.controller]),
            location=_maybe(ids, a.location, EntityId),
            loyalty=a.loyalty,
            scope=scope,
        )
        out.append((ev.AssetCreated(asset=asset), scope))
    for r in world.relationships:
        scope = _scope(r.scope, ids)
        relationship = Relationship(
            relationship_id=RelationshipId(ids[r.key]),
            a=EntityId(ids[r.a]),
            b=EntityId(ids[r.b]),
            disposition=r.disposition,
            price_tags=frozenset(r.price_tags),
            leverage_tags=frozenset(r.leverage_tags),
            scope=scope,
        )
        out.append((ev.RelationshipSet(relationship=relationship), scope))
    for m in world.meters:
        scope = _scope(m.scope, ids)
        meter = Meter(
            meter_id=MeterId(ids[m.key]),
            owner=EntityId(ids[m.owner]),
            name=m.name,
            value=m.value,
            lo=m.lo,
            hi=m.hi,
            max_delta_per_tick=m.max_delta_per_tick,
            scope=scope,
        )
        out.append((ev.MeterCreated(meter=meter), scope))
    for c in world.clocks:
        scope = _scope(c.scope, ids)
        clock = Clock(
            clock_id=ClockId(ids[c.key]),
            kind=c.kind,
            name=c.name,
            owner=_maybe(ids, c.owner, SeatId),
            target=_maybe(ids, c.target, EntityId),
            segments_total=c.segments_total,
            segments_filled=c.segments_filled,
            exposure=c.exposure,
            holds_slot=c.holds_slot,
            scope=scope,
        )
        out.append((ev.ClockCreated(clock=clock), scope))
    for g in world.goals:
        owner = SeatId(ids[g.seat])
        clock = Clock(
            clock_id=_goal_clock(ids[g.key]),
            kind=ClockKind.OBJECTIVE,
            name="Goal",
            owner=owner,
            segments_total=parts(g.condition),
            scope=private_to(owner),
        )
        out.append((ev.ClockCreated(clock=clock), clock.scope))
    for f in world.facts:
        scope = _scope(f.scope, ids)
        fact = Fact(
            fact_id=FactId(ids[f.key]),
            subject=EntityId(ids[f.subject]),
            predicate=f.predicate,
            obj=_fact_obj(f.obj, ids, sections),
            truth=f.truth,
            exposure=f.exposure,
            scope=scope,
            canary=f.canary,
        )
        out.append((ev.FactAsserted(fact=fact), scope))
    for cm in world.commitments:
        scope = _scope(cm.scope, ids)
        commitment = Commitment(
            commitment_id=CommitmentId(ids[cm.key]),
            parties=frozenset(EntityId(ids[p]) for p in cm.parties),
            clauses=tuple(_clause(c, ids) for c in cm.clauses),
            status=cm.status,
            scope=scope,
        )
        out.append((ev.CommitmentCreated(commitment=commitment), scope))
    if world.start_date is not None:
        out.append((ev.DateAdvanced(to=world.start_date), PUBLIC))
    if world.ruleset == "realism":
        out += _emit_realism(world, ids)
    for k in world.contests:
        scope = _scope(k.scope, ids)
        contest = Contest(
            contest_id=ContestId(ids[k.key]),
            kind=k.kind,
            name=k.name,
            prize=k.prize,
            sides=tuple(EntityId(ids[s]) for s in k.sides),
            track=k.track,
            momentum=k.momentum,
            countdown_days=k.countdown_days,
            scope=scope,
        )
        out.append((ev.ContestCreated(contest=contest), scope))
    for h in world.schedule:
        scope = _scope(h.scope, ids)
        scheduled = ScheduledEvent(
            scheduled_id=ScheduledEventId(ids[h.key]),
            fire_at_tick=0,
            name=h.name,
            scope=scope,
            source=ScheduleSource.HISTORY,
            on_date=h.on_date,
            condition=_bind(h.condition, ids),
            weight=h.weight,
            headline=h.headline,
            subject=_maybe(ids, h.subject, EntityId),
            obj=_maybe(ids, h.obj, EntityId),
        )
        out.append((ev.ScheduledEventCreated(scheduled=scheduled), scope))
    for s in world.seats:
        seat = Seat(
            seat_id=SeatId(ids[s.key]),
            kind=s.kind,
            name=s.name,
            embodies=EntityId(ids[s.embodies]),
            controller=s.controller,
            slots=s.slots if s.slots is not None else world.settings.starting_slots,
            objectives=frozenset(ClockId(ids[k]) for k in s.objectives)
            | {_goal_clock(ids[g.key]) for g in world.goals if g.seat == s.key},
            standing_orders=s.standing_orders,
        )
        out.append((ev.SeatCreated(seat=seat), PUBLIC))
    for s in world.seats:
        if s.agent is None:
            continue
        persona = Persona(
            name=s.agent.name,
            role=s.agent.role,
            voice=s.agent.voice,
            backstory=s.agent.backstory,
            relationship=s.agent.relationship,
        )
        assigned = ev.AgentAssigned(
            seat_id=SeatId(ids[s.key]),
            agent=EntityId(ids[s.agent.entity]),
            persona=persona,
        )
        out.append((assigned, PUBLIC))
    for g in world.goals:
        condition = _bind(g.condition, ids)
        owner = SeatId(ids[g.seat])
        goal = Goal(
            goal_id=GoalId(ids[g.key]),
            seat_id=owner,
            text=g.text,
            condition=condition,
            kind=goal_kind(condition),
            clock_id=_goal_clock(ids[g.key]),
            scope=private_to(owner),
            canary=g.canary,
        )
        out.append((ev.GoalSet(goal=goal), goal.scope))
    for ch in world.roster:
        character = Character(
            entity_id=EntityId(ids[ch.entity]),
            pitch=ch.pitch,
            reach=ch.reach,
            composite=ch.composite,
            means=frozenset(AssetId(ids[m]) for m in ch.means),
            sides=tuple(
                CharacterSide(contest_id=ContestId(ids[s.contest]), side=EntityId(ids[s.side]))
                for s in ch.sides
            ),
            aliases=ch.aliases,
        )
        out.append((ev.CharacterListed(character=character), PUBLIC))
    for d in world.developments:
        out.append((ev.ScheduledEventCreated(scheduled=_development(d, ids)), PUBLIC))
    if world.start:
        out.append((ev.SessionZeroOpened(start=world.start, notes=world.notes), PUBLIC))
    return out


def _emit_realism(world: WorldFile, ids: Mapping[str, str]) -> list[tuple[ev.Payload, Scope]]:
    """Quantities first, so the cards' feeds can name them. All engine only but the
    quantities declared public: cards carry the AI policy fields."""
    assert world.start_date is not None  # checked before emitting
    out: list[tuple[ev.Payload, Scope]] = []
    for q in world.quantities:
        quantity = Quantity(
            quantity_id=QuantityId(ids[q.key]),
            owner=_maybe(ids, q.owner, EntityId),
            name=q.name,
            value=q.value,
            unit=q.unit,
            as_of=q.as_of or world.start_date,
            scope=PUBLIC if q.public else None,
        )
        out.append((ev.QuantitySet(quantity=quantity), PUBLIC))
    if world.piece_kinds or world.resources:
        declared_kinds = ev.KindsDeclared(
            pieces=tuple(_piece_kind(k) for k in world.piece_kinds),
            resources=tuple(
                Resource(key=r.key, name=r.name, unit=r.unit, role=r.role) for r in world.resources
            ),
        )
        out.append((declared_kinds, PUBLIC))
    for d in world.features:
        feature = Feature(
            feature_id=FeatureId(ids[d.key]),
            kind=d.kind,
            name=d.name,
            side=_maybe(ids, d.side, EntityId),
            tier=d.tier,
            places=tuple(EntityId(ids[k]) for k in _standing(world, d)),
            as_of=d.as_of or world.start_date,
            legs=tuple(
                Leg(
                    since=leg.since,
                    places=tuple(EntityId(ids[k]) for k in leg.places),
                    takes=tuple(EntityId(ids[k]) for k in leg.takes),
                    concealed=leg.concealed,
                )
                for leg in d.legs
            ),
            in_service=d.in_service,
            piece=d.piece,
        )
        out.append((ev.FeatureSet(feature=feature), PUBLIC))
    feeds = tuple(
        Feed(
            feed_id=FeedId(ids[f.key]),
            name=f.name,
            author=EntityId(ids[f.author]),
            kind=f.kind,
            channel=f.channel,
            classification=f.classification,
            every_days=f.every_days,
            latency_days=f.latency_days,
            reports=tuple(QuantityId(ids[k]) for k in f.reports),
            sights=tuple(FeatureId(ids[k]) for k in f.sights),
            bias=f.bias,
        )
        for f in world.feeds
    )
    pipelines = tuple(
        Pipeline(
            pipeline_id=PipelineId(ids[pl.key]),
            name=pl.name,
            steps=tuple(
                Step(
                    person=EntityId(ids[st.person]),
                    kind=st.kind,
                    days=st.days,
                    allowed=frozenset(st.allowed),
                )
                for st in pl.steps
            ),
        )
        for pl in world.pipelines
    )
    cards = tuple(_card(c, ids) for c in world.cards)
    templates = tuple(_template(m, ids) for m in world.mandates)
    outlets = tuple(
        Outlet(
            outlet_id=EntityId(ids[o.key]),
            polity=EntityId(ids[o.polity]),
            name=o.name,
            voice=o.voice,
        )
        for o in world.outlets
    )
    declared = ev.CardsDeclared(
        cards=cards,
        feeds=feeds,
        pipelines=pipelines,
        templates=templates,
        outlets=outlets,
        topics=tuple(_topic(t) for t in world.topics),
    )
    out.append((declared, PUBLIC))
    for w in world.wars:
        a, b = EntityId(ids[w.a]), EntityId(ids[w.b])
        war = War(
            war_id=war_id_for(a, b), a=a, b=b, since=w.since, declared_by=a, declared=w.declared
        )
        out.append((ev.WarDeclared(war=war), PUBLIC))
    if world.map is not None:
        out.append((ev.MapDeclared(map=_board(world, ids)), PUBLIC))
    for line in world.trade_lines:
        declared_line = TradeLine(
            key=line.key,
            exporter=EntityId(ids[line.exporter]),
            importer=EntityId(ids[line.importer]),
            resource=line.resource,
            amount=line.amount,
            cut=line.cut,
            source=line.source,
        )
        # Engine only, as every compiled declaration: ``catchup`` never feeds a trade_set,
        # and a seat reads the lines its nation is a party to from its view.
        out.append((ev.TradeSet(line=declared_line, on=world.start_date), PUBLIC))
    return out


def _standing(world: WorldFile, d: FeatureDecl) -> tuple[str, ...]:
    """Where a feature is set at creation: with ``territories`` on, a piece stands in the
    area its place lies in (checked at compile); otherwise at its places as written."""
    kind = next((k for k in world.piece_kinds if k.key == d.piece), None)
    if Rule.TERRITORIES not in world.rules or kind is None:
        return d.places
    return tuple(_stand_area(world, p, kind.domain) or p for p in d.places)


def _piece_kind(k: PieceKindDecl) -> PieceKind:
    return PieceKind(
        key=k.key,
        name=k.name,
        domain=k.domain,
        days_per_step=dict(k.days_per_step),
        max_strength=k.max_strength,
        fuel_per_step=k.fuel_per_step,
        range_steps=k.range_steps,
        detect=k.detect,
        conceal=k.conceal,
        carries=k.carries,
    )


def _areas(world: WorldFile, ids: Mapping[str, str]) -> list[Entity]:
    """One location entity per territory and sea zone, keyed by the area's key."""
    return [
        Entity(entity_id=EntityId(ids[d.key]), kind=EntityKind.LOCATION, name=d.name)
        for d in _area_decls(world)
    ]


def _board(world: WorldFile, ids: Mapping[str, str]) -> tm.WorldMap:
    """The board as ``map_declared`` holds it: no shapes, only what the rules read."""
    ref = world.map
    assert ref is not None
    links = []
    for entry in world.adjacency:
        a, b, crossing = (
            (entry.a, entry.b, entry.crossing)
            if isinstance(entry, LinkDecl)
            else (entry[0], entry[1], None)
        )
        links.append(tm.Link(a=EntityId(ids[a]), b=EntityId(ids[b]), crossing=crossing))
    return tm.WorldMap(
        file=ref.file,
        sha256=ref.sha256,
        coords=ref.coords,
        box=ref.box,
        terrain=tuple(tm.Terrain(key=t.key, kind=t.kind, defence=t.defence) for t in world.terrain),
        regions=tuple(tm.Region(key=r.key, name=r.name, parent=r.parent) for r in world.regions),
        territories=tuple(
            tm.Territory(
                area=EntityId(ids[d.key]),
                key=d.key,
                name=d.name,
                region=d.region,
                terrain=d.terrain,
                holder=_maybe(ids, d.holder, EntityId),
                yields=dict(d.yields),
                sites=tuple(EntityId(ids[k]) for k in d.sites),
                districts=d.districts,
            )
            for d in world.territories
        ),
        sea_zones=tuple(
            tm.SeaZone(
                area=EntityId(ids[d.key]),
                key=d.key,
                name=d.name,
                region=d.region,
                terrain=d.terrain,
            )
            for d in world.sea_zones
        ),
        adjacency=tuple(links),
        ports=tuple(
            tm.Port(
                place=EntityId(ids[e.key]),
                land=EntityId(ids[e.within]),
                sea=EntityId(ids[e.port_on]),
            )
            for e in world.entities
            if e.port_on is not None and e.within is not None
        ),
        bases=tuple(_site_base(world, e, ids) for e in world.entities if e.base is not None),
        lift_pools={
            EntityId(ids[e.key]): QuantityId(ids[e.lift_pool])
            for e in world.entities
            if e.lift_pool is not None
        },
        capitals={
            EntityId(ids[e.key]): EntityId(ids[e.capital])
            for e in world.entities
            if e.capital is not None
        },
    )


def _site_base(world: WorldFile, e: EntityDecl, ids: Mapping[str, str]) -> tm.Base:
    """A base as the board holds it: the area its land pieces stand in, and the sea zone its
    ships stand in (its port's, or the zone it lies in)."""
    assert e.base is not None
    areas = _area_kinds(world)
    here = e.key if e.key in areas else e.within
    land = here if here is not None and areas.get(here) is tm.TerrainKind.LAND else None
    sea = e.port_on if e.port_on is not None else (here if land is None else None)
    return tm.Base(
        place=EntityId(ids[e.key]),
        land=None if land is None else EntityId(ids[land]),
        sea=None if sea is None else EntityId(ids[sea]),
        sides=tuple(EntityId(ids[k]) for k in e.base.sides),
        domains=e.base.domains,
    )


def _entity(e: EntityDecl, ids: Mapping[str, str]) -> Entity:
    return Entity(
        entity_id=EntityId(ids[e.key]),
        kind=e.kind,
        name=e.name,
        parent=_maybe(ids, e.parent, EntityId),
        location=_maybe(ids, e.location, EntityId),
        tags=frozenset(e.tags),
        at=e.at,
        theatre=e.theatre,
        within=_maybe(ids, e.within, EntityId),
    )


def compile_figure(
    state: State,
    figure: EntityId,
    part: WorldFile,
    known: Mapping[str, EntityId],
    versions: Versions,
) -> list[Event]:
    """One person's card for a running realism campaign: the people, quantities,
    feeds and pipelines it brings, then a ``cards_declared`` holding the one card.

    ``known`` gives the keys ``part`` may use for what the log already holds; part
    may refer to them but not declare them again, nor declare a name already in
    the world. Its own keys are salted with the figure, so two cards built apart
    never share an ID, and its event IDs derive from the figure, so a second card
    for one person fails at the store. Raises WorldError listing every problem.
    """
    by_id = {e: k for k, e in known.items()}
    me = by_id.get(figure)
    stubs = tuple(
        EntityDecl(key=k, kind=state.entities[e].kind, name=state.entities[e].name)
        for k, e in known.items()
    )
    # Checked as a world of its own, the stubs standing in for the log. The card is
    # checked as unplayable: its roster entry is already in the log, not in part.
    whole = part.model_copy(
        update={
            "entities": stubs + part.entities,
            "cards": tuple(c.model_copy(update={"playable": False}) for c in part.cards),
            "roster": (),
            "ruleset": "realism",
            "start_date": state.in_world_date,
        }
    )
    problems: list[str] = []
    sections = _index(whole, problems)
    _check(whole, sections, problems)
    if me is None:
        problems.append(f"figure {figure}: not among the known keys")
    elif [c.person for c in part.cards] != [me]:
        problems.append(f"cards: exactly one card, for {me}")
    orderable = (
        {e for d in part.cards[0].authority for e in d.effects} if len(part.cards) == 1 else None
    )
    for m in part.mandates:
        if me is not None and m.to != (me,):
            problems.append(f"mandate {m.key}: aimed at {', '.join(m.to)}, not only at {me}")
        if me is None or orderable is None:
            continue
        for leaf in leaves(m.condition):
            if not isinstance(leaf, Ordered):
                continue
            if leaf.person != me:
                problems.append(f"mandate {m.key}: ordered by {leaf.person}, not by {me}")
            if leaf.effect not in orderable:
                problems.append(f"mandate {m.key}: {me} cannot order {leaf.effect}")
        if m.trigger.on is TriggerKind.ACT and m.trigger.effect not in orderable:
            problems.append(
                f"mandate {m.key}: {me} cannot order {m.trigger.effect}, so it never fires"
            )
    names = {x.name.casefold(): by_id.get(e, "") for e, x in state.entities.items()}
    for d in part.entities:
        if d.name.casefold() in names:
            problems.append(
                f"entity {d.key}: {d.name} is already in the world"
                + (f" as {names[d.name.casefold()]}" if names[d.name.casefold()] else "")
            )
    if problems:
        raise WorldError(problems)

    ids = {
        key: known[key]
        if key in known
        else object_id(state.campaign_id, section, f"{figure}.{key}")
        for key, section in sections.items()
    }
    emitted: list[tuple[ev.Payload, Scope]] = [
        (ev.EntityCreated(entity=_entity(e, ids)), PUBLIC) for e in part.entities
    ]
    # Template keys are global in the state; the figure's tail keeps two cards' keys apart.
    mandates = tuple(
        m.model_copy(update={"key": f"{m.key}.{str(figure)[-12:]}"}) for m in part.mandates
    )
    emitted += [
        (ev.QuantitySet(quantity=x.quantity.model_copy(update={"estimable": True})), scope)
        if isinstance(x, ev.QuantitySet)
        else (x, scope)
        for x, scope in _emit_realism(
            whole.model_copy(update={"cards": part.cards, "mandates": mandates}), ids
        )
    ]
    events = [
        Event(
            event_id=EventId(derived_id(state.campaign_id, "figure", figure, n)),
            campaign_id=state.campaign_id,
            seq=state.last_seq + 1 + n,
            tick=state.tick,
            actor=None,
            scope=scope,
            payload=payload,
            versions=versions,
        )
        for n, (payload, scope) in enumerate(emitted)
    ]
    try:
        replay(events, initial=state)
    except FoldError as exc:
        raise WorldError([f"fold: {exc}"]) from exc
    return events


def _card(c: CardDecl, ids: Mapping[str, str]) -> SeatCard:
    return SeatCard(
        person=EntityId(ids[c.person]),
        office=c.office,
        playable=c.playable,
        powers=c.powers,
        inner_circle=tuple(
            Contact(person=EntityId(ids[k.person]), channel=k.channel) for k in c.inner_circle
        ),
        principals=tuple(EntityId(ids[k]) for k in c.principals),
        levers=tuple(
            Lever(
                name=lv.name,
                pipeline=PipelineId(ids[lv.pipeline]),
                resolver=lv.resolver,
                params=lv.params,
                label=lv.label,
                summary=lv.summary,
            )
            for lv in c.levers
        ),
        feeds=tuple(FeedId(ids[k]) for k in c.feeds),
        pipelines=tuple(PipelineId(ids[k]) for k in c.pipelines),
        constraints=c.constraints,
        personal=c.personal,
        successor=_maybe(ids, c.successor, EntityId),
        horizon_days=c.horizon_days,
        voice=c.voice,
        loyalty=c.loyalty,
        competence=c.competence,
        doctrine=c.doctrine,
        interests=c.interests,
        wants=c.wants,
        holds_to=c.holds_to,
        authority=tuple(
            Domain(
                name=dm.name,
                effects=frozenset(dm.effects),
                executor=_maybe(ids, dm.executor, EntityId),
                forces=tuple(FeatureId(ids[k]) for k in dm.forces),
                summary=dm.summary,
            )
            for dm in c.authority
        ),
        reach=Reach(
            rank=c.reach.rank,
            chain=tuple(EntityId(ids[k]) for k in c.reach.chain),
            heads=c.reach.heads,
        ),
        aims=c.aims,
        allies=tuple(EntityId(ids[k]) for k in c.allies),
        opposes=tuple(
            Conflict(against=EntityId(ids[x.against]), over=x.over, irreducible=x.irreducible)
            for x in c.opposes
        ),
        answers=tuple(_answer(a, ids) for a in c.answers),
        addressed_as=c.addressed_as,
    )


def _answer(a: Answer, ids: Mapping[str, str]) -> Answer:
    """The answer with every key in it replaced by its id."""
    when = a.when.model_copy(
        update={
            "by": _maybe(ids, a.when.by, EntityId),
            "party": _maybe(ids, a.when.party, EntityId),
        }
    )
    effect = a.act.effect
    if effect is not None:
        named = {f: ids[getattr(effect, f)] for f in ENTITY_FIELDS if getattr(effect, f, None)}
        if isinstance(effect, MoveForce | SetEngagement) and effect.force is not None:
            named["force"] = ids[effect.force]
        effect = effect.model_copy(update=named)
    return a.model_copy(
        update={
            "when": when,
            "act": a.act.model_copy(update={"effect": effect}),
            "until": _maybe(ids, a.until, ScheduledEventId),
        }
    )


def card_policy(world: WorldFile, campaign_id: CampaignId) -> list[ev.CardAmended]:
    """Each card's allies, conflicts, answers, voice and form of address as the world file
    has them now, as the amendment that would bring a game's copy of the card up to it.
    Raises WorldError."""
    ids = resolve_keys(world, campaign_id)
    out: list[ev.CardAmended] = []
    for c in world.cards:
        card = _card(c, ids)
        out.append(
            ev.CardAmended(
                person=card.person,
                allies=card.allies,
                opposes=card.opposes,
                answers=card.answers,
                voice=card.voice,
                addressed_as=card.addressed_as,
            )
        )
    return out


def _template(m: MandateDecl, ids: Mapping[str, str]) -> MandateTemplate:
    t = m.trigger
    return MandateTemplate(
        key=m.key,
        kind=m.kind,
        trigger=Trigger(
            on=t.on,
            history=_maybe(ids, t.history, ScheduledEventId),
            quantity=_maybe(ids, t.quantity, QuantityId),
            op=t.op,
            value=t.value,
            effect=t.effect,
        ),
        to=tuple(EntityId(ids[k]) for k in m.to),
        issuer=_maybe(ids, m.issuer, EntityId),
        text=m.text,
        condition=_bind(m.condition, ids),
        days=m.days,
    )


def _fact_obj(
    obj: str, ids: Mapping[str, str], sections: Mapping[str, str]
) -> EntityId | AssetId | ClockId | str:
    match sections.get(obj):
        case "entity":
            return EntityId(ids[obj])
        case "asset":
            return AssetId(ids[obj])
        case "clock":
            return ClockId(ids[obj])
        case _:
            return obj


def _clause(decl: ClauseDecl, ids: Mapping[str, str]) -> Clause:
    return Clause(
        kind=decl.kind,
        party=EntityId(ids[decl.party]),
        beneficiary=EntityId(ids[decl.beneficiary]),
        asset=_maybe(ids, decl.asset, AssetId),
        verb=decl.verb,
        amount=decl.amount,
        until_tick=decl.until_tick,
    )
