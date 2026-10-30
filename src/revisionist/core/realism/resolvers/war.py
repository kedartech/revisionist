"""The war resolver: what a declaration of war sets going. Stub for now."""

from datetime import date

from revisionist.core.realism import resolvers as rs
from revisionist.core.realism.pipeline import Order
from revisionist.core.state import State


def resolve(state: State, order: Order) -> tuple["rs.Change", ...]:
    return ()


def on_day(state: State, today: date) -> tuple["rs.Change", ...]:
    return ()
