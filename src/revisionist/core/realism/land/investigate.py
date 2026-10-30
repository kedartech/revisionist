"""Landing a Investigate effect in the world. Stub for now."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FactId, SeatId
from revisionist.core.realism.effect import Investigate
from revisionist.core.realism.pass_world import PassWorld


def land(
    world: PassWorld, effect: Investigate, issuer_seat: SeatId, issuer: EntityId, on: date
) -> tuple[list[ev.Payload], list[FactId]]:
    return [], []
