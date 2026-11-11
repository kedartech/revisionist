"""Dossier and setting text from a world's sidecar file (Train 3 unit S4).

The sidecar ``worlds/dossiers/<world>.yaml`` holds public, read-only text: a bio, an arena
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
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from revisionist.core.events import CampaignCreated, Event
from revisionist.core.ids import EntityId
from revisionist.core.state import State
from revisionist.core.world_compile import object_id
from revisionist.engine.web.realism_api import Dossier, Setting, SettingDate

ROOT = Path(__file__).resolve().parents[4]
SIDECAR_DIR = ROOT / "worlds" / "dossiers"
"""Beside the world files, not among them: ``worlds/*.yaml`` is read as the list of worlds."""
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


def _text(problems: list[str], where: str, value: Any, cap: int | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        problems.append(f"{where} must be text")
        return None
    text = value.strip()
    if cap is not None and len(text) > cap:
        problems.append(f"{where} is over {cap} characters")
    return text or None


def _lines(problems: list[str], where: str, value: Any, cap: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append(f"{where} must be a list")
        return []
    out: list[str] = []
    for i, item in enumerate(value, 1):
        text = _text(problems, f"{where} {i}", item, cap)
        if text is not None:
            out.append(text)
    return out


def _date(problems: list[str], where: str, value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    problems.append(f"{where} is not a date")
    return None


def _dossier(problems: list[str], key: str, raw: Any, portraits_dir: Path) -> Dossier:
    if raw is None:
        return empty_dossier()
    if not isinstance(raw, Mapping):
        problems.append(f"{key}: must be a mapping of fields")
        return empty_dossier()
    dossier = empty_dossier()
    dossier["bio"] = _text(problems, f"{key}: bio", raw.get("bio"), BIO_MAX)
    dossier["arena"] = _text(problems, f"{key}: arena", raw.get("arena"), ARENA_MAX)
    dossier["history"] = _lines(problems, f"{key}: history line", raw.get("history"), LINE_MAX)
    dossier["quote"] = _text(problems, f"{key}: quote", raw.get("quote"), QUOTE_MAX)
    dossier["source"] = _text(problems, f"{key}: source", raw.get("source"), None)
    dossier["fact"] = _text(problems, f"{key}: fact", raw.get("fact"), LINE_MAX)
    dossier["credit"] = _text(problems, f"{key}: credit", raw.get("credit"), None)
    if dossier["quote"] and not dossier["source"]:
        problems.append(f"{key}: quote has no source")
    portrait = raw.get("portrait")
    if portrait is not None:
        if not isinstance(portrait, str) or not PORTRAIT_NAME.fullmatch(portrait):
            problems.append(f"{key}: portrait must be a bare image file name, like roosevelt.jpg")
        elif not (portraits_dir / portrait).is_file():
            problems.append(f"{key}: portrait file {portrait} is missing")
        else:
            dossier["portrait"] = portrait
    return dossier


def _setting(problems: list[str], raw: Any) -> Setting:
    if raw is None:
        return empty_setting()
    if not isinstance(raw, Mapping):
        problems.append("setting: must be a mapping of fields")
        return empty_setting()
    crawl = _lines(problems, "setting: crawl paragraph", raw.get("crawl"), CRAWL_MAX)
    if len(crawl) > CRAWL_PARAGRAPHS:
        problems.append(
            f"setting: crawl has {len(crawl)} paragraphs; the limit is {CRAWL_PARAGRAPHS}"
        )
    dated: list[tuple[date, str]] = []
    raw_dates = raw.get("dates")
    if raw_dates is not None and not isinstance(raw_dates, list):
        problems.append("setting: dates must be a list")
        raw_dates = []
    for i, item in enumerate(raw_dates or [], 1):
        where = f"setting: dates entry {i}"
        if not isinstance(item, Mapping):
            problems.append(f"{where} must have on and what")
            continue
        on = _date(problems, f"{where} on", item.get("on"))
        what = _text(problems, f"{where} what", item.get("what"), LINE_MAX)
        if what is None:
            problems.append(f"{where} what is missing")
        if on is not None and what is not None:
            dated.append((on, what))
    dated.sort(key=lambda entry: entry[0])
    dates: list[SettingDate] = [{"on": f"{d.day} {d:%B %Y}", "what": w} for d, w in dated]
    return {
        "situation": _text(problems, "setting: situation", raw.get("situation"), SITUATION_MAX),
        "sides": _lines(problems, "setting: side", raw.get("sides"), LINE_MAX),
        "crawl": crawl,
        "facts": _lines(problems, "setting: fact", raw.get("facts"), LINE_MAX),
        "dates": dates,
    }


def load(
    world: str, sidecar_dir: Path = SIDECAR_DIR, portraits_dir: Path = PORTRAITS_DIR
) -> tuple[dict[str, Dossier], Setting]:
    """The sidecar for ``world``: a dossier per person key, and the setting. No file gives
    ``({}, empty_setting())``. Raises ``SidecarError`` listing every problem: a field over
    its cap, a quote with no source, more than three crawl paragraphs, a portrait name that
    is not a bare lowercase file name or whose file is missing under ``portraits_dir``, a
    date that is not a date. Dates are served in words (``4 September 1941``)."""
    path = sidecar_dir / f"{world}.yaml"
    if not path.is_file():
        return {}, empty_setting()
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as err:
        raise SidecarError([f"{path.name}: cannot be read as YAML ({err})"]) from err
    if doc is None:
        doc = {}
    if not isinstance(doc, Mapping):
        raise SidecarError([f"{path.name}: must be a mapping at the top level"])
    problems: list[str] = []
    raw_people = doc.get("people") or {}
    if not isinstance(raw_people, Mapping):
        raise SidecarError([f"{path.name}: people must be a mapping of person keys"])
    people = {
        str(key): _dossier(problems, str(key), raw, portraits_dir)
        for key, raw in raw_people.items()
    }
    result = _setting(problems, doc.get("setting"))
    if problems:
        raise SidecarError(problems)
    return people, result


def world_key(events: Iterable[Event]) -> str | None:
    """The ``world`` of the campaign's ``campaign_created`` event; None with no such event."""
    for event in events:
        if isinstance(event.payload, CampaignCreated):
            return event.payload.world
    return None


def for_people(state: State, events: Iterable[Event]) -> Mapping[EntityId, Dossier]:
    """A dossier for each person the sidecar covers that is in the campaign, keyed by the
    campaign's entity id for that person key (``world_compile.object_id(campaign_id,
    "entity", key)``, the id the world compiler gave it). A campaign whose world has no
    sidecar, or whose sidecar fails to load, gives ``{}``: a bad sidecar never breaks the
    request path. Reads the module's ``SIDECAR_DIR`` and ``PORTRAITS_DIR`` at call time
    (tests point them elsewhere)."""
    key = world_key(events)
    if key is None:
        return {}
    try:
        people, _ = load(key, SIDECAR_DIR, PORTRAITS_DIR)
    except SidecarError:
        return {}
    out: dict[EntityId, Dossier] = {}
    for person_key, dossier in people.items():
        eid = EntityId(object_id(state.campaign_id, "entity", person_key))
        if eid in state.entities:
            out[eid] = dossier
    return out


def setting(state: State, events: Iterable[Event]) -> Setting:
    """The world's setting dossier; ``empty_setting()`` when there is no sidecar or it fails
    to load."""
    key = world_key(events)
    if key is None:
        return empty_setting()
    try:
        _, result = load(key, SIDECAR_DIR, PORTRAITS_DIR)
    except SidecarError:
        return empty_setting()
    return result


__all__ = [
    "ARENA_MAX",
    "BIO_MAX",
    "CRAWL_MAX",
    "CRAWL_PARAGRAPHS",
    "LINE_MAX",
    "PORTRAITS_DIR",
    "QUOTE_MAX",
    "SIDECAR_DIR",
    "SITUATION_MAX",
    "SidecarError",
    "empty_dossier",
    "empty_setting",
    "for_people",
    "load",
    "setting",
    "world_key",
]
