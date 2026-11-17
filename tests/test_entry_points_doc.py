"""``docs/entry-points.md`` names every entry point the code has.

The inventory is read by whoever picks up the code next, so a command, an action, an
environment variable, a unit or an engine module that the code has and the file lacks is a
hole in the map. Each test reads the thing from the code (the Typer app, the realism and
game dispatch in ``server.py``, the source text, the deploy folders) and looks for its name
in the file; none of them reads a line number.
"""

import ast
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typer.main

from revisionist import cli

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "entry-points.md").read_text()
SRC = ROOT / "src" / "revisionist"
HIDDEN_OPTIONS = {"--help", "--install-completion", "--show-completion"}


def _commands(group: Any, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    for name, command in sorted(group.commands.items()):
        if hasattr(command, "commands"):
            yield from _commands(command, (*prefix, name))
        else:
            yield (*prefix, name)


def _command(path: tuple[str, ...]) -> Any:
    current: Any = typer.main.get_command(cli.app)
    for name in path:
        current = current.commands[name]
    return current


def _section(title: str, start: str, end: str | None) -> list[str]:
    """The lines of the doc between the line ``start`` and the next ``end`` (or the end)."""
    lines = DOC.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(start))
    out: list[str] = []
    for line in lines[first + 1 :]:
        if end is not None and line.startswith(end):
            break
        out.append(line)
    assert out, title
    return out


def _entry(path: tuple[str, ...]) -> str:
    """The text of the doc's code span for one CLI command: ``name [--opt] ARG``."""
    if len(path) == 1:
        block = _section("top-level", "Top-level:", "Groups:")
        text = "\n".join(line for line in block if line.startswith("- "))
    else:
        block = _section("groups", "Groups:", "## 3.")
        kept: list[str] = []
        inside = False
        for line in block:
            if line.startswith("- "):
                inside = line.startswith(f"- `{path[0]}`")
            if inside:
                kept.append(line)
        text = "\n".join(kept)
    found = re.search(r"`" + re.escape(path[-1]) + r"(?:[ `][^`]*)?`", text)
    assert found, f"`revisionist {' '.join(path)}` is not in docs/entry-points.md section 2"
    return found.group(0)


COMMANDS = list(_commands(typer.main.get_command(cli.app)))


@pytest.mark.parametrize("path", COMMANDS, ids=" ".join)
def test_every_cli_command_is_listed_with_its_options(path: tuple[str, ...]) -> None:
    entry = _entry(path)
    options = {
        opt
        for param in _command(path).params
        for opt in getattr(param, "opts", [])
        if opt.startswith("--") and opt not in HIDDEN_OPTIONS
    }
    missing = sorted(opt for opt in options if opt not in entry)
    assert not missing, f"`revisionist {' '.join(path)}` entry lacks {missing}: {entry}"


def _compared_actions(module: Path, method: str) -> set[str]:
    """Every string a method compares ``action`` against: ``action == "x"``, ``in (...)``."""
    tree = ast.parse(module.read_text())
    func = next(
        n
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef)
        for n in cls.body
        if isinstance(n, ast.FunctionDef) and n.name == method
    )
    names: set[str] = set()
    for node in ast.walk(func):
        if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)):
            continue
        if node.left.id != "action":
            continue
        for part in node.comparators:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                names.add(part.value)
            elif isinstance(part, ast.Tuple):
                names.update(
                    e.value
                    for e in part.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                )
    return names


ROUTES = {
    "/api/realism/": ("realism",),
    "/api/game/": ("game",),
    "/api/new/": ("new_game", "_session_zero"),
}


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_every_web_action_is_listed(route: str) -> None:
    server = SRC / "engine" / "web" / "server.py"
    wanted = {a for method in ROUTES[route] for a in _compared_actions(server, method)}
    assert wanted, route
    row = next(line for line in DOC.splitlines() if f"`POST {route}<action>`" in line)
    row = row.split("After the seat has committed")[0]  # the action list, not the prose after it
    missing = sorted(a for a in wanted if f"`{a}`" not in row)
    assert not missing, f"POST {route}<action> lacks {missing}"


def _env_names() -> set[str]:
    names: set[str] = set()
    for folder in (SRC, ROOT / "deploy", ROOT / "scripts"):
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix in {".pyc", ".json", ".sql"}:
                continue
            names.update(re.findall(r"\bREVISIONIST_[A-Z0-9_]*[A-Z0-9]\b", path.read_text()))
    return names


def test_every_environment_variable_is_listed() -> None:
    wanted = _env_names()
    assert "REVISIONIST_SCHEDULER_TRANSPORT" in wanted  # the scan reads the real tree
    # The per-call model override is one family, written once as ``REVISIONIST_MODEL_<CALL>``.
    wanted = {n for n in wanted if not n.startswith("REVISIONIST_MODEL_")}
    missing = sorted(n for n in wanted if f"`{n}`" not in DOC)
    assert not missing, f"docs/entry-points.md lacks {missing}"
    assert "`REVISIONIST_MODEL_<CALL>`" in DOC


def test_every_unit_and_script_is_listed() -> None:
    files = [
        p.name
        for folder in ("systemd", "backup")
        for p in sorted((ROOT / "deploy" / folder).iterdir())
        if p.is_file()
    ]
    assert "revisionist-scheduler@.service" in files
    missing = [name for name in files if name not in DOC]
    assert not missing, f"docs/entry-points.md lacks {missing}"


def test_every_engine_module_is_listed() -> None:
    modules = [
        p.relative_to(ROOT).as_posix()
        for folder in (SRC / "engine", SRC / "engine" / "web")
        for p in sorted(folder.glob("*.py"))
        if p.name != "__init__.py"
    ]
    assert "src/revisionist/engine/wake_report.py" in modules
    missing = [m for m in modules if m not in DOC and Path(m).name not in DOC]
    assert not missing, f"docs/entry-points.md lacks {missing}"


def test_the_schema_version_is_the_one_in_the_code() -> None:
    from revisionist.core import SCHEMA_VERSION

    assert f'`SCHEMA_VERSION = "{SCHEMA_VERSION}"`' in DOC
