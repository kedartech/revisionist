"""The service worker's script as served: ``web/sw.js`` with its one ``SHELL`` line filled in
with the shell's files and a version taken from their bytes, so a changed client is a changed
worker, which the browser installs and holds until the player takes it."""

import json
from hashlib import sha256
from pathlib import Path

ANCHOR = 'const SHELL = {"version": "", "files": []};'
TOP = ("index.html", "manifest.webmanifest")
DIRS = ("js", "css", "fonts", "icons", "assets")
SUFFIXES = frozenset({".js", ".css", ".woff2", ".png", ".svg", ".json", ".jpg", ".webp"})
LEFT_OUT = frozenset({"icons/logo-1024.png"})
"""The source the icons are cut from: no page or manifest names it."""


def shell_files(static: Path) -> list[str]:
    """The client's files a worker keeps, relative to ``static``: the page, the manifest, and
    the scripts, styles, fonts, icons and assets under their folders, in a fixed order."""
    names = [name for name in TOP if (static / name).is_file()]
    for folder in DIRS:
        found = sorted(
            path.relative_to(static).as_posix()
            for path in (static / folder).rglob("*")
            if path.is_file() and path.suffix in SUFFIXES
        )
        names += [name for name in found if name not in LEFT_OUT]
    return names


def script(static: Path, text: bytes) -> bytes:
    """``text``, the worker's own bytes, with the ``SHELL`` line filled in."""
    files = shell_files(static)
    digest = sha256(text)
    for name in files:
        digest.update(b"\0" + name.encode() + b"\0")
        digest.update((static / name).read_bytes())
    shell = {"version": digest.hexdigest()[:16], "files": ["/" + name for name in files]}
    return text.replace(ANCHOR.encode(), f"const SHELL = {json.dumps(shell)};".encode(), 1)
