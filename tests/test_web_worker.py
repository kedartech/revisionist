"""The service worker as served: ``/sw.js`` carries the shell's file list and a version taken
from the bytes of those files, so a changed client is a changed worker the browser offers."""

import json
import re
from pathlib import Path

from revisionist.engine.web import worker
from tests.test_web import Web, web  # noqa: F401
from tests.test_web_territory_map import fetch

SW = Path(__file__).parents[1] / "web" / "sw.js"


def served_shell(web: Web) -> dict[str, object]:  # noqa: F811
    status, got, raw = fetch(web.client(), "/sw.js", signed=False)
    assert status == 200 and got["service-worker-allowed"] == "/"
    found = re.search(rb"^const SHELL = (\{.*\});$", raw, re.M)
    assert found, raw[:200]
    shell: dict[str, object] = json.loads(found.group(1))
    return shell


def client_files(static: Path) -> None:
    (static / "sw.js").write_text(f"// the worker\n{worker.ANCHOR}\nself.x = 1;\n")
    for rel, text in {
        "manifest.webmanifest": "{}",
        "js/views/room.js": "export {};",
        "css/tokens.css": ":root {}",
        "fonts/plex.woff2": "w",
        "fonts/OFL.txt": "licence",
        "icons/icon-192.png": "p",
        "icons/logo-1024.png": "big",
        "assets/flags/fr.svg": "<svg/>",
        "test/a.test.js": "x",
        "README.md": "# web",
        "package.json": "{}",
    }.items():
        (static / rel).parent.mkdir(parents=True, exist_ok=True)
        (static / rel).write_text(text)


def test_the_repo_worker_has_the_line_the_server_fills_in_once() -> None:
    assert SW.read_text().count(worker.ANCHOR) == 1


def test_the_served_worker_lists_the_page_scripts_styles_fonts_icons_and_assets(
    web: Web,  # noqa: F811
) -> None:
    client_files(web.app.static)
    shell = served_shell(web)
    assert shell["files"] == [
        "/index.html",
        "/manifest.webmanifest",
        "/js/views/room.js",
        "/css/tokens.css",
        "/fonts/plex.woff2",
        "/icons/icon-192.png",
        "/assets/flags/fr.svg",
    ]
    assert re.fullmatch(r"[0-9a-f]{16}", str(shell["version"]))


def test_the_version_follows_the_bytes_of_the_shell_and_of_the_worker(
    web: Web,  # noqa: F811
) -> None:
    client_files(web.app.static)
    first = served_shell(web)["version"]
    assert served_shell(web)["version"] == first
    (web.app.static / "test" / "a.test.js").write_text("changed")
    assert served_shell(web)["version"] == first
    (web.app.static / "css" / "tokens.css").write_text(":root { --bg: #000; }")
    second = served_shell(web)["version"]
    assert second != first
    sw = web.app.static / "sw.js"
    sw.write_text(sw.read_text() + "self.y = 2;\n")
    assert served_shell(web)["version"] not in (first, second)


def test_only_the_worker_is_filled_in(web: Web) -> None:  # noqa: F811
    client_files(web.app.static)
    (web.app.static / "app.js").write_text(f"{worker.ANCHOR}\n")
    status, _, raw = fetch(web.client(), "/app.js", signed=False)
    assert status == 200 and raw.decode() == f"{worker.ANCHOR}\n"
