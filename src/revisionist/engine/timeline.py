"""The war's timeline and who held power on a date (Phase 4 unit E1).

The curated start points are the ready-made worlds plus a short list of the war's
turning dates. Who held power on a date is one cheap model call, kept per date."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from revisionist.engine import campaign as cmp
from revisionist.engine.llm import Request, Transport, prompt_text
from revisionist.engine.pitch import PITCH_MODEL

WAR_START = date(1939, 9, 1)
WAR_END = date(1945, 9, 2)
HELD_MAX = 40
"""[proposed] Most people listed for one date."""
OUTSIDE = "The war ran from 1 September 1939 to 2 September 1945. Choose a date inside it."

TURNING_DATES: tuple[tuple[date, str], ...] = (
    (date(1939, 9, 1), "Germany invades Poland"),
    (date(1940, 5, 10), "The attack in the West"),
    (date(1940, 9, 7), "The Blitz begins"),
    (date(1941, 6, 22), "Germany invades the Soviet Union"),
    (date(1942, 6, 4), "Midway"),
    (date(1943, 7, 5), "Kursk"),
    (date(1944, 6, 6), "The Normandy landings"),
    (date(1945, 4, 12), "Roosevelt dies"),
)
"""[proposed] The war's turning dates a game could open on, with no world made for them yet."""

_TEXT = {"type": "string", "minLength": 1}
HELD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "people": {
            "type": "array",
            "maxItems": HELD_MAX,
            "items": {
                "type": "object",
                "properties": {"name": _TEXT, "title": _TEXT, "side": _TEXT, "power": _TEXT},
                "required": ["name", "title", "side", "power"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["people"],
    "additionalProperties": False,
}


class OutsideWarError(ValueError):
    """The date falls outside the war; the message is plain words for the player."""


@dataclass(frozen=True)
class StartPoint:
    on: date
    label: str
    world: str | None
    """The ready-made world to start; None: a date with no curated world."""


@dataclass(frozen=True)
class HeldPower:
    """One figure who held real power on a date."""

    name: str
    title: str
    side: str
    power: str


_held: dict[date, tuple[HeldPower, ...]] = {}


def start_points() -> tuple[StartPoint, ...]:
    """The curated start points, oldest first: the ready-made worlds, then the turning dates."""
    from revisionist.engine.web.server import READY

    points = [
        StartPoint(world.start_date, world.name, key)
        for key in READY
        if (world := cmp.load_world(cmp.world_path(key))).start_date is not None
    ]
    points += [StartPoint(on, label, None) for on, label in TURNING_DATES]
    return tuple(sorted(points, key=lambda p: p.on))


def held_power(on: date, transport: Transport) -> tuple[HeldPower, ...]:
    """Up to ``HELD_MAX`` who held power ``on``. One call per date for the process."""
    if not WAR_START <= on <= WAR_END:
        raise OutsideWarError(OUTSIDE)
    if on in _held:
        return _held[on]
    reply = transport.call(
        Request(
            call_class="held_power",
            model=PITCH_MODEL,
            system=prompt_text("held_power"),
            prompt=f"## Date\n{on.isoformat()}",
            schema=HELD_SCHEMA,
            max_usd=0.3,
        )
    )
    raw = reply.output.get("people") if isinstance(reply.output, dict) else None
    seen: set[str] = set()
    people: list[HeldPower] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        fields = [str(item.get(k) or "").strip() for k in ("name", "title", "side", "power")]
        if not all(fields) or fields[0].casefold() in seen:
            continue
        seen.add(fields[0].casefold())
        people.append(HeldPower(*fields))
    _held[on] = tuple(people[:HELD_MAX])
    return _held[on]


__all__ = [
    "HELD_MAX",
    "OUTSIDE",
    "HeldPower",
    "OutsideWarError",
    "StartPoint",
    "held_power",
    "start_points",
]
