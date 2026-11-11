"""Dossier and setting text from a world's sidecar file (Train 3 unit S4).

The sidecar ``worlds/<world>.dossiers.yaml`` holds public, read-only text: a bio, the
lines history gave each playable person, a sourced quote, a fact and a portrait file,
and for the world a setting paragraph, its sides, the opening crawl and dated events.
Nothing here reads a card's private side. A world with no sidecar gives empty blocks.
"""

from collections.abc import Iterable, Mapping

from revisionist.core.events import Event
from revisionist.core.ids import EntityId
from revisionist.core.state import State
from revisionist.engine.web.realism_api import Dossier, Setting


def empty_dossier() -> Dossier:
    return Dossier(
        bio=None, history=[], quote=None, source=None, fact=None, portrait=None, credit=None
    )


def empty_setting() -> Setting:
    return Setting(situation=None, sides=[], crawl=[], facts=[], dates=[])


def for_people(state: State, events: Iterable[Event]) -> Mapping[EntityId, Dossier]:
    """A dossier for each person the sidecar covers, by entity. contract stub"""
    return {}


def setting(state: State, events: Iterable[Event]) -> Setting:
    """The world's setting dossier. contract stub"""
    return empty_setting()


__all__ = ["empty_dossier", "empty_setting", "for_people", "setting"]
