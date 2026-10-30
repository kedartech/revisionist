"""Landing a Appointment effect in the world. Stub for now."""

from datetime import date

from revisionist.core import events as ev
from revisionist.core.ids import EntityId, FactId, SeatId
from revisionist.core.realism.effect import Appointment
from revisionist.core.realism.pass_world import PassWorld


def land(
    world: PassWorld, effect: Appointment, issuer_seat: SeatId, issuer: EntityId, on: date
) -> tuple[list[ev.Payload], list[FactId]]:
    return [], []
