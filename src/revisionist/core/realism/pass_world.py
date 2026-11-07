"""The world as it stands mid-pass, shared by ``apply`` and the ``land`` modules."""

from collections.abc import Container

from revisionist.core.ids import EntityId, FeatureId, QuantityId, RelationshipId
from revisionist.core.ontology import Relationship
from revisionist.core.realism.geography import Feature
from revisionist.core.realism.quantity import Quantity
from revisionist.core.state import State


class PassWorld:
    """Features and relationships as they stand mid-pass, so two parts landing on the
    same force or relationship on one day see each other."""

    def __init__(self, state: State) -> None:
        self.state = state
        self.features: dict[FeatureId, Feature] = dict(state.features)
        self.relationships: dict[RelationshipId, Relationship] = dict(state.relationships)
        self.quantities: dict[QuantityId, Quantity] = dict(state.quantities)
        self.claimed: set[str] = set()

    def claim(self, item_id: str, known: Container[str]) -> bool:
        """Take ``item_id`` for this pass: False if the state holds it or an earlier part took it.
        The fold refuses an id twice, so every fact, news item and document goes through here."""
        if item_id in known or item_id in self.claimed:
            return False
        self.claimed.add(item_id)
        return True

    def relationship(self, a: EntityId, b: EntityId) -> Relationship | None:
        return next(
            (r for r in self.relationships.values() if {r.a, r.b} == {a, b}),
            None,
        )


__all__ = ["PassWorld"]
