"""The web client can be installed to a phone home screen with its own icon."""

import json
import re
import struct
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def _png_size(path: Path) -> str:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    width, height = struct.unpack(">II", head[16:24])
    return f"{width}x{height}"


def test_the_shell_links_the_manifest_and_icons() -> None:
    head = (WEB / "index.html").read_text().split("</head>")[0]
    for href in re.findall(
        r'<link rel="(?:manifest|icon|apple-touch-icon)"[^>]*href="([^"]+)"', head
    ):
        assert (WEB / href.lstrip("/")).is_file(), href
    assert '<link rel="manifest" href="/manifest.webmanifest">' in head
    assert 'rel="apple-touch-icon"' in head


def test_the_manifest_is_installable() -> None:
    manifest = json.loads((WEB / "manifest.webmanifest").read_text())
    assert manifest["name"] and manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"
    sizes = set()
    for icon in manifest["icons"]:
        assert _png_size(WEB / icon["src"].lstrip("/")) == icon["sizes"], icon["src"]
        sizes.add((icon["sizes"], icon["purpose"]))
    # Chromium needs a 192 and a 512 icon; Android masks a "maskable" one to its launcher shape.
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
