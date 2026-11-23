"""Every nation of the 1941 world has a flag row and a file; every flag file is safe to draw."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FLAGS = ROOT / "web" / "assets" / "flags"
WORLD = ROOT / "worlds" / "autumn-1941.yaml"
MAX_BYTES = 30 * 1024
OUTSIDE_HREF = re.compile(r"^\s*(?!#)\S")
URL_REF = re.compile(r"url\(\s*['\"]?\s*(?!#)", re.IGNORECASE)


def problems(data: bytes) -> list[str]:
    """What stops a file being drawn as a flag: rule 4 of the flag item."""
    found: list[str] = []
    if len(data) >= MAX_BYTES:
        found.append("30 KB or more")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as err:
        return [*found, f"not XML: {err}"]
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        found.append("root is not svg")
    if not root.get("viewBox"):
        found.append("no view box")
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        if tag in {"script", "foreignobject", "iframe", "embed", "object", "style", "image"}:
            found.append(f"{tag} element")
        for name, value in el.attrib.items():
            local = name.rsplit("}", 1)[-1].lower()
            if local.startswith("on"):
                found.append(f"{local} attribute")
            if local == "href" and OUTSIDE_HREF.match(value):
                found.append("outside reference")
            if URL_REF.search(value):
                found.append("outside reference")
    if b"<!ENTITY" in data:
        found.append("entity declaration")
    return found


def _index() -> dict[str, dict[str, str | None]]:
    index: dict[str, dict[str, str | None]] = json.loads((FLAGS / "index.json").read_text())
    return index


def _world() -> tuple[set[str], set[str]]:
    doc = yaml.safe_load(WORLD.read_text())
    nations = {e["key"] for e in doc["entities"] if e["kind"] == "polity"}
    playable = {
        n for c in doc["cards"] if c.get("playable") for n in c.get("principals", [])
    } & nations
    return nations, playable


def test_every_nation_of_the_1941_world_has_a_row() -> None:
    nations, _ = _world()
    rows = _index()["autumn-1941"]
    assert sorted(nations - rows.keys()) == []


def test_every_playable_nation_has_a_file_and_every_named_file_exists() -> None:
    _, playable = _world()
    rows = _index()["autumn-1941"]
    assert sorted(n for n in playable if not rows.get(n)) == []
    for world, table in _index().items():
        for nation, name in table.items():
            if name is not None:
                assert (FLAGS / name).is_file(), f"{world}/{nation}: {name}"


def test_every_nation_of_the_1941_world_has_its_flag_file() -> None:
    nations, _ = _world()
    rows = _index()["autumn-1941"]
    assert sorted(n for n in nations if not rows.get(n)) == []


def test_every_flag_file_is_an_svg_with_a_view_box_and_nothing_that_runs() -> None:
    files = sorted(FLAGS.glob("*.svg"))
    assert files
    for path in files:
        assert problems(path.read_bytes()) == [], path.name


def test_the_sources_sheet_names_every_file() -> None:
    sheet = (FLAGS / "SOURCES.md").read_text()
    for path in FLAGS.glob("*.svg"):
        assert f"`{path.name}`" in sheet, path.name


@pytest.mark.parametrize(
    "bad",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><script>x()</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2" onload="x()"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><image href="http://a/b.png"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><use href="http://a/b.svg#x"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><rect fill="url(http://a/b)"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2"><foreignObject/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" width="3" height="2"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3 2">' + b" " * 31000 + b"</svg>",
        b"<html/>",
    ],
)
def test_the_file_check_refuses(bad: bytes) -> None:
    assert problems(bad)


def test_the_file_check_passes_a_plain_flag() -> None:
    plain = (
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        b'viewBox="0 0 3 2"><defs><path id="p" d="M0 0"/></defs><use xlink:href="#p"/>'
        b'<rect fill="url(#p)"/></svg>'
    )
    assert problems(plain) == []
