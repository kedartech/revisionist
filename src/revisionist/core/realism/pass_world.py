"""The world as it stands mid-pass, shared by ``apply`` and the ``land`` modules."""

from revisionist.core.ids import EntityId, FeatureId, RelationshipId
from revisionist.core.ontology import Relationship
from revisionist.core.realism.geography import Feature
from revisionist.core.state import State


class PassWorld:
    """Features and relationships as they stand mid-pass, so two parts landing on the
    same force or relationship on one day see each other."""

    def __init__(self, state: State) -> None:
        self.state = state
        self.features: dict[FeatureId, Feature] = dict(state.features)
        self.relationships: dict[RelationshipId, Relationship] = dict(state.relationships)

    def relationship(self, a: EntityId, b: EntityId) -> Relationship | None:
        return next(
            (r for r in self.relationships.values() if {r.a, r.b} == {a, b}),
            None,
        )


__all__ = ["PassWorld"]
