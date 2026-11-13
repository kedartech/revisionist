"""Where a movement form can send a force (reach R1, server half).

The form's destination opens to every place on the seat's map, not only the choices it
was written with. Each place is grouped and given a day count from the seat's own pages
only, as the map is: a place is the seat's own, an ally's, on a route or contested because
a page the seat holds says a force, route or front is there, and the days run from where
the latest such page places the form's force, by the movement resolver's own route
(``routing.days_between``: by sea through the passages open to its side, given the wars
the view holds, which are public). Nothing is read from the engine's truth.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from revisionist.core.events import Event
from revisionist.core.ids import DocumentId, EntityId
from revisionist.core.realism.card import Lever, ParamSpec
from revisionist.core.realism.document import BodyField, DocumentView
from revisionist.core.realism.geography import FORCES, FeatureKind
from revisionist.core.realism.pipelines import place_named
from revisionist.core.realism.routing import days_between
from revisionist.core.state import State, View
from revisionist.core.world_compile import object_id
from revisionist.engine import campaign as cmp
from revisionist.engine.web.dossiers import world_key
from revisionist.engine.web.realism_api import PlaceChoice

Group = Literal["own", "allied", "route", "contested", "other"]
GROUPS: tuple[Group, ...] = ("own", "allied", "route", "contested", "other")
"""In the order a place is shown, and the first that fits wins."""
FORCE = "force"
_DEPTH = 8

Sightings = dict[tuple[str, str], tuple[DocumentId, DocumentView, BodyField]]


@dataclass(frozen=True)
class Known:
    """What the forms need beyond the seat's view, all of it the seat's own."""

    keys: Mapping[EntityId, str] = field(default_factory=dict)
    """The world key of each place, by its id. Empty: forms keep their own choices."""
    forces: Mapping[str, str] = field(default_factory=dict)
    """Each force key the seat's forms offer, and the name its pages give it."""
    allies: frozenset[EntityId] = frozenset()
    """The sides the seat's own card counts as allies."""


def place_keys(state: State, events: Iterable[Event]) -> dict[EntityId, str]:
    """The world key of every place with a position, by the campaign's id for it, from
    the world file the campaign was compiled from; ``{}`` when that file is gone or no
    longer loads (the forms then offer only their own choices)."""
    name = world_key(events)
    if name is None:
        return {}
    try:
        keys = _located(name)
    except (OSError, ValueError):
        return {}
    return {EntityId(object_id(state.campaign_id, "entity", k)): k for k in keys}


@lru_cache(maxsize=16)
def _located(name: str) -> tuple[str, ...]:
    world = cmp.load_world(cmp.world_path(name))
    return tuple(e.key for e in world.entities if e.at is not None)


def own_sides(view: View) -> set[EntityId]:
    """The viewer's person and everything above it: what counts as its own side."""
    out: set[EntityId] = set()
    at: EntityId | None = view.me.embodies
    for _ in range(_DEPTH):
        if at is None or at not in view.entities:
            break
        out.add(at)
        at = view.entities[at].parent
    return out


def latest_sightings(view: View) -> Sightings:
    """Each sighted feature, by its line's label and kind, as the latest arrived page has it."""
    latest: Sightings = {}
    arrived = sorted(view.documents.items(), key=lambda kv: (kv[1].arrives, kv[1].issued, kv[0]))
    for doc_id, doc in arrived:
        for b in doc.body:
            if b.sight is not None:
                latest[(b.label, b.sight.kind.value)] = (doc_id, doc, b)
    return latest


def _groups(
    view: View, spec: ParamSpec, seen: Sightings, allies: frozenset[EntityId]
) -> dict[EntityId, Group]:
    own = own_sides(view)
    out: dict[EntityId, Group] = {}

    def put(place: EntityId, group: Group) -> None:
        if GROUPS.index(group) < GROUPS.index(out.get(place, "other")):
            out[place] = group

    for key in spec.choices:
        found = place_named(view, key)
        if found is not None:
            put(found.entity_id, "own")
    for _, _, line in seen.values():
        sight = line.sight
        assert sight is not None
        group: Group
        if sight.kind is FeatureKind.ROUTE:
            group = "route"
        elif sight.kind is FeatureKind.FRONT:
            group = "contested"
        elif sight.side in own:
            group = "own"
        elif sight.side in allies:
            group = "allied"
        else:
            group = "contested"
        for place in sight.places:
            put(place, group)
    return out


Origin = tuple[FeatureKind, EntityId | None, EntityId]
"""A force's kind, side, and where the latest page places it."""


def _origins(lever: Lever, forces: Mapping[str, str], seen: Sightings) -> dict[str, Origin | None]:
    """For each force the form offers: its kind, side and place as its latest page has them."""
    spec = next((p for p in lever.params if p.name == FORCE), None)
    out: dict[str, Origin | None] = {}
    for key in spec.choices if spec is not None else ():
        out[key] = None
        for kind in sorted(FORCES):
            hit = seen.get((forces.get(key, ""), kind.value))
            if hit is not None and hit[2].sight is not None:
                out[key] = (kind, hit[2].sight.side, hit[2].sight.places[0])
    return out


def place_choices(view: View, lever: Lever, spec: ParamSpec, known: Known) -> list[PlaceChoice]:
    """Every place the seat's map has, grouped, with days per force of the form; ``[]``
    without the world's keys."""
    if not known.keys:
        return []
    offered = dict(known.keys)
    for key in spec.choices:
        found = place_named(view, key)
        if found is not None:
            offered[found.entity_id] = key
    seen = latest_sightings(view)
    groups = _groups(view, spec, seen, known.allies)
    origins = _origins(lever, known.forces, seen)
    out: list[PlaceChoice] = []
    for place, key in offered.items():
        found = place_named(view, key)
        if found is None or found.entity_id != place:
            continue
        out.append(
            PlaceChoice(
                value=key,
                label=found.name,
                group=groups.get(place, "other"),
                days={
                    force: None
                    if at is None
                    else 0
                    if at[2] == place
                    else days_between(view, at[0], at[1], at[2], place)
                    for force, at in origins.items()
                },
            )
        )
    out.sort(key=lambda p: (GROUPS.index(p["group"]), p["label"], p["value"]))
    return out


__all__ = [
    "GROUPS",
    "Known",
    "latest_sightings",
    "own_sides",
    "place_choices",
    "place_keys",
]
