"""Dossier and setting text from a world's sidecar file (Train 3 unit S4).

The sidecar ``worlds/<world>.dossiers.yaml`` holds public, read-only text: a bio, an arena
paragraph, the lines history gave each playable person, a sourced quote, a fact and a
portrait file, and for the world a setting paragraph, its sides, the opening crawl, short
period facts and dated events. Nothing here reads a card's private side. A world with no
sidecar gives empty blocks.

Sidecar shape (keys under ``people`` are the world file's person keys)::

    world: <world key>
    setting: {situation, sides: [..], crawl: [..], facts: [..], dates: [{on: <ISO date>, what}]}
    people:
      <person key>: {bio, arena, history: [..], quote, source, fact, portrait, credit}
"""

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from revisionist.core.events import Event
from revisionist.core.ids import EntityId
from revisionist.core.state import State
from revisionist.engine.web.realism_api import Dossier, Setting

ROOT = Path(__file__).resolve().parents[4]
WORLDS_DIR = ROOT / "worlds"
PORTRAITS_DIR = ROOT / "web" / "assets" / "portraits"

BIO_MAX = 900
ARENA_MAX = 400
LINE_MAX = 160
"""A history line, a side, a fact, a date's ``what``."""
QUOTE_MAX = 240
SITUATION_MAX = 500
CRAWL_MAX = 320
"""One crawl paragraph."""
CRAWL_PARAGRAPHS = 3
PORTRAIT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.(jpg|png|webp)$")
"""A portrait file name: lowercase, no path, one of three image types."""


class SidecarError(ValueError):
    """Every problem in a sidecar file, one per line, sorted."""

    problems: tuple[str, ...]

    def __init__(self, problems: Iterable[str]) -> None:
        self.problems = tuple(sorted(problems))
        super().__init__("\n".join(self.problems))


def empty_dossier() -> Dossier:
    return Dossier(
        bio=None,
        arena=None,
        history=[],
        quote=None,
        source=None,
        fact=None,
        portrait=None,
        credit=None,
    )


def empty_setting() -> Setting:
    return Setting(situation=None, sides=[], crawl=[], facts=[], dates=[])


def load(
    world: str, worlds_dir: Path = WORLDS_DIR, portraits_dir: Path = PORTRAITS_DIR
) -> tuple[dict[str, Dossier], Setting]:
    """The sidecar for ``world``: a dossier per person key, and the setting. No file gives
    ``({}, empty_setting())``. Raises ``SidecarError`` listing every problem: a field over
    its cap, a quote with no source, more than three crawl paragraphs, a portrait name that
    is not a bare lowercase file name or whose file is missing under ``portraits_dir``, a
    date that is not a date. Dates are served in words (``4 September 1941``). contract stub"""
    return {}, empty_setting()


def world_key(events: Iterable[Event]) -> str | None:
    """The ``world`` of the campaign's ``campaign_created`` event; None with no such event.
    contract stub"""
    return None


def for_people(state: State, events: Iterable[Event]) -> Mapping[EntityId, Dossier]:
    """A dossier for each person the sidecar covers that is in the campaign, keyed by the
    campaign's entity id for that person key (``world_compile.object_id(campaign_id,
    "entity", key)``, the id the world compiler gave it). A campaign whose world has no
    sidecar, or whose sidecar fails to load, gives ``{}``: a bad sidecar never breaks the
    request path. Reads the module's ``WORLDS_DIR`` and ``PORTRAITS_DIR`` at call time
    (tests point them elsewhere). contract stub"""
    return {}


def setting(state: State, events: Iterable[Event]) -> Setting:
    """The world's setting dossier; ``empty_setting()`` when there is no sidecar or it fails
    to load. contract stub"""
    return empty_setting()


__all__ = [
    "ARENA_MAX",
    "BIO_MAX",
    "CRAWL_MAX",
    "CRAWL_PARAGRAPHS",
    "LINE_MAX",
    "PORTRAITS_DIR",
    "QUOTE_MAX",
    "SITUATION_MAX",
    "SidecarError",
    "empty_dossier",
    "empty_setting",
    "for_people",
    "load",
    "setting",
    "world_key",
]
