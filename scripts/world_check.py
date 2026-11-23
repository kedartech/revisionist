"""The world check: which of the template's questions a world answers.

``worlds/TEMPLATE.md`` lists every question a world answers, each with the world-file keys
that answer it. This script reads that document and a world, and prints one line per
question: answered; answered, marked a gap; absent, with what is off for want of it; or
absent and required, when the world switches on a rule that needs the answer. Any absent
and required question makes the exit status 1.

Usage::

    python scripts/world_check.py WORLD [WORLD ...]
    python scripts/world_check.py --keys

``WORLD`` is a bundled world's name (``autumn-1941``) or a path. ``--keys`` lists the keys
the world loader accepts that no row of the document names, and exits 1 if there are any.

It reads the standard library and the world loader alone.
"""

import argparse
import re
import sys
import typing
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from revisionist.engine.campaign import WorldFile, load_world, world_path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "worlds" / "TEMPLATE.md"
COLUMNS = ("Question", "Keys", "Allowed values", "Switch", "When absent", "Needed", "Standing")

GRAMMARS = ("revisionist.core.goals", "revisionist.core.realism.effect")
"""Value languages a key takes as a whole: a condition (``check: ...``) and an act's effect
(``kind: ...``). Their inner fields are the value's grammar, not keys of the world."""

_TOKEN = re.compile(r"`([^`]+)`")
_BRACES = re.compile(r"^([a-z0-9_.]*)\{([^{}]+)\}$")
_PART = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$")


@dataclass(frozen=True)
class Row:
    """One question of the template."""

    part: str
    number_label: str
    question: str
    keys: tuple[str, ...]
    allowed: str
    switches: tuple[str, ...]
    when_absent: str
    needed: tuple[str, ...] | None
    """None: never required. Empty: required in every world. Else required when any of
    these rules is on."""
    standing: str


@dataclass(frozen=True)
class Line:
    """What the check found for one question in one world."""

    row: Row
    status: str
    """``answered``, ``gap``, ``absent`` or ``required``."""
    found: int = 0
    gaps: int = 0

    def text(self) -> str:
        head = f"{self.row.number_label} {self.row.question}"
        if self.status == "answered":
            return f"{head}: answered"
        if self.status == "gap":
            return f"{head}: answered, marked a gap ({self.gaps} of {self.found})"
        if self.status == "required":
            on = ", ".join(self.row.needed or ())
            why = f"needed with {on} on" if on else "needed in every world"
            return f"{head}: absent and required ({why})"
        if self.row.standing != "on main":
            return f"{head}: absent: not built yet ({self.row.standing}); {self.row.when_absent}"
        return f"{head}: absent: {self.row.when_absent}"


# --- the document ------------------------------------------------------------------


def expand(cell: str) -> tuple[str, ...]:
    """The keys a cell names: each backticked path, with ``a.{b, c}`` as ``a.b`` and ``a.c``."""
    keys: list[str] = []
    for token in _TOKEN.findall(cell):
        token = token.replace(" ", "")
        braces = _BRACES.match(token)
        if braces is None:
            keys.append(token)
            continue
        base, inner = braces.groups()
        keys.extend(f"{base}{name}" for name in inner.split(",") if name)
    return tuple(keys)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _needed(cell: str) -> tuple[str, ...] | None:
    cell = cell.strip()
    if cell in ("", "-"):
        return None
    if cell == "always":
        return ()
    if cell.startswith("with ") and _TOKEN.findall(cell):
        return tuple(_TOKEN.findall(cell))
    raise ValueError(f"a Needed cell is '-', 'always' or 'with `rule`': {cell!r}")


def parse_template(text: str) -> list[Row]:
    """Every question row of the document, in order, under its part."""
    found: list[Row] = []
    part, number, count, in_table = "", "", 0, False
    for line in text.splitlines():
        heading = _PART.match(line)
        if heading:
            number, part, count, in_table = heading.group(1), heading.group(2), 0, False
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        cells = _cells(line)
        if tuple(cells) == COLUMNS:
            in_table = True
            continue
        if not in_table or set("".join(cells)) <= set("-: "):
            continue
        if len(cells) != len(COLUMNS):
            raise ValueError(f"a template row has {len(COLUMNS)} cells: {line!r}")
        question, keys, allowed, switch, absent, needed, standing = cells
        count += 1
        found.append(
            Row(
                part=part,
                number_label=f"{number}.{count}",
                question=question,
                keys=expand(keys),
                allowed=allowed,
                switches=tuple(_TOKEN.findall(switch))
                or (("legacy",) if "legacy" in switch else ()),
                when_absent=absent,
                needed=_needed(needed),
                standing=standing,
            )
        )
    return found


# --- the loader's keys -------------------------------------------------------------


def _models(annotation: object) -> Iterator[type]:
    if isinstance(annotation, type) and hasattr(annotation, "model_fields"):
        yield annotation
        return
    for arg in typing.get_args(annotation):
        yield from _models(arg)


def _fields(model: typing.Any) -> dict[str, typing.Any]:
    fields: dict[str, typing.Any] = model.model_fields
    return {name: f for name, f in fields.items() if not f.exclude}


def loader_keys() -> frozenset[str]:
    """Every key path the world loader accepts: field names joined by dots, through list
    items and the free keys of a mapping, stopping at a value language (``GRAMMARS``)."""
    keys: set[str] = set()

    def walk(model: type, prefix: str, above: frozenset[type]) -> None:
        for name, field in _fields(model).items():
            path = f"{prefix}{name}"
            keys.add(path)
            for sub in _models(field.annotation):
                if sub.__module__ not in GRAMMARS and sub not in above:
                    walk(sub, f"{path}.", above | {sub})

    walk(WorldFile, "", frozenset({WorldFile}))
    return frozenset(keys)


# --- a world -----------------------------------------------------------------------


def load(path: Path) -> WorldFile:
    return load_world(path)


def _items(value: object) -> Iterator[object]:
    """The models inside a value: itself, or every model in a list or a mapping's values."""
    if hasattr(value, "model_fields_set"):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _items(v)
    elif isinstance(value, list | tuple | set | frozenset):
        for v in value:
            yield from _items(v)


def _occurrences(world: WorldFile, path: str, empty: bool = True) -> list[tuple[int, bool]]:
    """Where the world writes ``path``: one entry per object that carries it (each item of
    a list of objects, else the object holding the key), with whether a gap mark covers it.
    With ``empty`` false, a key written with an empty value is not counted."""
    parts = path.split(".")
    found: list[tuple[int, bool]] = []

    def walk(obj: object, at: int, gap: bool) -> None:
        name = parts[at]
        if name not in getattr(obj, "model_fields_set", ()):
            return
        value = getattr(obj, name)
        if not empty and value in (None, (), [], {}):
            return
        if at == len(parts) - 1:
            items = list(_items(value)) if isinstance(value, list | tuple) else []
            for item in items or [obj]:
                found.append((id(item), gap or getattr(item, "gap", False) is True))
            return
        for item in _items(value):
            walk(item, at + 1, gap or getattr(item, "gap", False) is True)

    walk(world, 0, False)
    return found


def check(world: WorldFile, rows: Iterable[Row]) -> list[Line]:
    """One line per question, in the document's order."""
    on = {str(r) for r in world.rules}
    lines: list[Line] = []
    for row in rows:
        seen: dict[int, bool] = {}
        for key in row.keys:
            for ident, gap in _occurrences(world, key, empty=row.needed is None):
                seen[ident] = seen.get(ident, False) or gap
        if seen:
            gaps = sum(seen.values())
            status = "gap" if gaps else "answered"
            lines.append(Line(row, status, found=len(seen), gaps=gaps))
        elif row.needed is not None and (row.needed == () or on.intersection(row.needed)):
            lines.append(Line(row, "required"))
        else:
            lines.append(Line(row, "absent"))
    return lines


def report(name: str, lines: Sequence[Line]) -> list[str]:
    out = [f"world {name}"]
    part = ""
    for line in lines:
        if line.row.part != part:
            part = line.row.part
            out.append(f"  {part}")
        out.append(f"    {line.text()}")
    counts = {
        s: sum(1 for x in lines if x.status == s) for s in ("answered", "gap", "absent", "required")
    }
    out.append(
        "  {answered} answered, {gap} marked a gap, {absent} absent, "
        "{required} absent and required".format(**counts)
    )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Which of the template's questions a world answers."
    )
    parser.add_argument("worlds", nargs="*", help="a bundled world's name or a world file")
    parser.add_argument("--keys", action="store_true", help="list loader keys with no row")
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    args = parser.parse_args(argv)
    rows = parse_template(args.template.read_text())
    if args.keys:
        missing = sorted(loader_keys() - {k for r in rows for k in r.keys})
        for key in missing:
            print(key)
        return 1 if missing else 0
    if not args.worlds:
        parser.error("name a world, or pass --keys")
    failed = False
    for name in args.worlds:
        path = world_path(name)
        lines = check(load(path), rows)
        print("\n".join(report(name, lines)))
        failed = failed or any(x.status == "required" for x in lines)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
