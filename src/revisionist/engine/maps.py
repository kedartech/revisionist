"""Map objects: every map a stored game names, found again by its hash.

A game stores its map's SHA-256 in ``map_declared`` and never the shapes. Whatever
map the world file names later, the game is served the bytes with that hash: the
immutable object ``<sha256>.json`` in the map-objects directory, or else the
world-named file in ``worlds/maps/`` when its bytes still hash the same. Nothing is
returned whose hash differs. ``worlds/maps/objects/MANIFEST`` lists every object
committed, and no object a stored game names is ever deleted.
"""

import hashlib
import os
import re
from pathlib import Path

OBJECTS_ENV = "REVISIONIST_MAP_OBJECTS"
"""The map-objects directory; default ``worlds/maps/objects/``."""
MAPS_DIR = Path(__file__).resolve().parents[3] / "worlds" / "maps"
"""Where the world-named map files are."""

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def objects_dir() -> Path:
    given = os.environ.get(OBJECTS_ENV)
    return Path(given) if given else MAPS_DIR / "objects"


def map_object(sha256: str, file: str | None = None) -> bytes | None:
    """The map whose bytes hash to ``sha256``: its object, or else the world-named
    ``file`` when that hashes the same. None when neither does."""
    if not _SHA256.fullmatch(sha256):
        return None
    candidates = [objects_dir() / f"{sha256}.json"]
    if file is not None and Path(file).name == file:
        candidates.append(MAPS_DIR / file)
    for path in candidates:
        if path.is_file():
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() == sha256:
                return data
    return None


__all__ = ["MAPS_DIR", "OBJECTS_ENV", "map_object", "objects_dir"]
