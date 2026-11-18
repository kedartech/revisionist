"""Guard: no rule names a place, a nation or an era.

The 1941 world file declares keys and names (entities, quantities, features, levers, pipelines,
feeds, bills and the rest). A rule in ``core/`` or ``engine/`` that spells one of them as a string
literal is tied to that world and cannot run another. Every such tie that existed when this guard
landed is listed in ``fixed_names_allow.txt`` with the reason it stays; a new one fails the test.
The list only shrinks: a line whose literal has gone from the code fails too.

A second check covers the territory path (modules that read the map or the world's piece kinds):
none may compare a piece's kind key or a resource's key to a literal. Rules ask a piece for its
domain and a resource for its role, never for its name.
"""

import ast
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "worlds" / "autumn-1941.yaml"
SIDECARS = (
    ROOT / "worlds" / "dossiers" / "autumn-1941.yaml",
    ROOT / "worlds" / "developments" / "autumn-1941.yaml",
)
ALLOW = Path(__file__).with_name("fixed_names_allow.txt")
SCANNED = ("src/revisionist/core", "src/revisionist/engine")

SECTIONS = (
    "entities",
    "quantities",
    "features",
    "feeds",
    "pipelines",
    "outlets",
    "assets",
    "topics",
    "contests",
    "schedule",
    "mandates",
)
"""The world file's lists whose items carry a ``key`` and a ``name``."""

REASON = re.compile(r"^(stored games only|until [A-Z]{3})$")
"""The only two reasons a line may give: a stored game still replays it, or the named item
removes it."""

NOT_RULES = {
    "src/revisionist/engine/transport_check.py": (
        "sample text a live-transport check asks a model to copy back; it is not a rule"
    ),
}
"""Files that spell world names as data, not as rules. A file here must still hold such a
literal, so the exemption cannot go stale."""

PATH_ROOTS = ("core/realism/territory.py", "core/realism/kinds.py")
"""The modules that define the territory path; any module importing one is on it too."""

PIECE_TAILS = frozenset({"piece", "piece_key", "kind_key", "piece_kind_key"})
RESOURCE_TAILS = frozenset({"resource", "resource_key", "res_key"})
TABLE_TAILS = frozenset({"pieces", "resources"})


# ---------------------------------------------------------------- the names a world declares


def declared_names(world: Mapping[str, Any], sidecars: Sequence[Mapping[str, Any]]) -> set[str]:
    """Every key and name the world and its sidecars declare, lever names and bills included."""
    out: set[str] = set()

    def add(value: object) -> None:
        if isinstance(value, str) and value:
            out.add(value)

    for section in SECTIONS:
        for item in world.get(section) or ():
            add(item.get("key"))
            add(item.get("name"))
    for card in world.get("cards") or ():
        for lever in card.get("levers") or ():
            add(lever.get("name"))
            for param in lever.get("params") or ():
                if param.get("name") == "bill":
                    for choice in param.get("choices") or ():
                        add(choice)
    for sidecar in sidecars:
        people = sidecar.get("people") or {}
        for key in people:
            add(key)
        for item in sidecar.get("developments") or ():
            add(item.get("key"))
            add(item.get("name"))
    return out


def load_declared() -> set[str]:
    world = yaml.safe_load(WORLD.read_text())
    return declared_names(world, [yaml.safe_load(p.read_text()) for p in SIDECARS])


# ------------------------------------------------------------------- literals in rule code


def rule_literals(source: str) -> dict[str, list[int]]:
    """Each string literal in ``source`` with its lines, bare string statements (docstrings,
    attribute docs) left out: they say what a rule is for and are never read."""
    tree = ast.parse(source)
    prose = {
        id(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
    }
    out: dict[str, list[int]] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in prose:
            out.setdefault(n.value, []).append(n.lineno)
    return out


def code_files() -> dict[str, str]:
    """Repo-relative path to source for every module under the scanned trees."""
    files: dict[str, str] = {}
    for tree in SCANNED:
        for path in sorted((ROOT / tree).rglob("*.py")):
            files[path.relative_to(ROOT).as_posix()] = path.read_text()
    return files


def ties(files: Mapping[str, str], names: set[str]) -> set[tuple[str, str]]:
    """The (file, literal) pairs where a module spells a declared name."""
    return {
        (path, literal)
        for path, source in files.items()
        for literal in rule_literals(source)
        if literal in names
    }


# ------------------------------------------------------------------------- the allow-list


def read_allow(text: str) -> dict[tuple[str, str], str]:
    """``path | literal | reason`` lines; ``#`` lines and blanks skipped. Refuses a line with
    another shape, a reason outside the two allowed, or a pair listed twice."""
    out: dict[tuple[str, str], str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(" | ")
        if len(parts) != 3:
            raise ValueError(f"line {n}: want 'path | literal | reason': {raw!r}")
        path, literal, reason = parts
        if not REASON.match(reason):
            raise ValueError(f"line {n}: reason must be 'stored games only' or 'until <item>'")
        if (path, literal) in out:
            raise ValueError(f"line {n}: {path} {literal!r} is listed twice")
        out[(path, literal)] = reason
    return out


def unlisted(
    found: set[tuple[str, str]], allowed: Iterable[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Ties the list does not cover. A line covers one literal in one file, nothing more."""
    return sorted(found - set(allowed))


def stale(found: set[tuple[str, str]], allowed: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Lines whose literal is no longer in that file: the list only shrinks."""
    return sorted(set(allowed) - found)


# ----------------------------------------------------------------- the territory path check


def _tail(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _is_key_expr(node: ast.expr) -> str | None:
    """Whether ``node`` reads a piece's kind key or a resource's key; names which."""
    tail = _tail(node)
    if tail in PIECE_TAILS:
        return "a piece's kind key"
    if tail in RESOURCE_TAILS:
        return "a resource's key"
    if isinstance(node, ast.Attribute) and node.attr == "key":
        base = _tail(node.value)
        if base in {"piece_kind", "kind_decl"} | PIECE_TAILS:
            return "a piece's kind key"
        if base in {"resource", "res"} | RESOURCE_TAILS:
            return "a resource's key"
    return None


def _str_literals(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return any(_str_literals(e) for e in node.elts)
    return False


def _pattern_has_str(pattern: ast.pattern) -> bool:
    if isinstance(pattern, ast.MatchValue):
        return _str_literals(pattern.value)
    if isinstance(pattern, ast.MatchOr):
        return any(_pattern_has_str(p) for p in pattern.patterns)
    return False


def key_literal_uses(source: str) -> list[tuple[int, str]]:
    """Where ``source`` compares a piece's kind key or a resource's key to a string literal,
    matches on one, or looks one up by a literal in the world's ``pieces`` or ``resources``."""
    found: list[tuple[int, str]] = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Compare):
            sides = [n.left, *n.comparators]
            if any(_str_literals(s) for s in sides):
                for s in sides:
                    if (what := _is_key_expr(s)) is not None:
                        found.append((n.lineno, f"compares {what} to a literal"))
        elif isinstance(n, ast.Match):
            if (what := _is_key_expr(n.subject)) is not None and any(
                _pattern_has_str(c.pattern) for c in n.cases
            ):
                found.append((n.lineno, f"matches {what} on a literal"))
        elif isinstance(n, ast.Subscript):
            if _tail(n.value) in TABLE_TAILS and _str_literals(n.slice):
                found.append((n.lineno, "looks a piece kind or resource up by a literal"))
        elif isinstance(n, ast.Call):
            f = n.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr in {"get", "pop"}
                and _tail(f.value) in TABLE_TAILS
                and n.args
                and _str_literals(n.args[0])
            ):
                found.append((n.lineno, "looks a piece kind or resource up by a literal"))
    return found


def territory_path(files: Mapping[str, str]) -> list[str]:
    """The roots, and every module that imports one of them."""
    roots = {f"src/revisionist/{r}" for r in PATH_ROOTS}
    stems = {Path(r).stem for r in PATH_ROOTS}
    on_path = {p for p in roots if p in files}
    for path, source in files.items():
        for n in ast.walk(ast.parse(source)):
            if isinstance(n, ast.ImportFrom):
                mod = n.module or ""
                if mod.rsplit(".", 1)[-1] in stems or (
                    mod.endswith("core.realism") and any(a.name in stems for a in n.names)
                ):
                    on_path.add(path)
            elif isinstance(n, ast.Import) and any(
                a.name.rsplit(".", 1)[-1] in stems for a in n.names
            ):
                on_path.add(path)
    return sorted(on_path)


# ======================================================================== the real tree


@pytest.fixture(scope="module")
def names() -> set[str]:
    return load_declared()


@pytest.fixture(scope="module")
def files() -> dict[str, str]:
    return code_files()


@pytest.fixture(scope="module")
def allow() -> dict[tuple[str, str], str]:
    return read_allow(ALLOW.read_text())


def _found(files: Mapping[str, str], names: set[str]) -> set[tuple[str, str]]:
    return {t for t in ties(files, names) if t[0] not in NOT_RULES}


def test_the_world_names_are_collected(names: set[str]) -> None:
    """Keys, display names, lever names and bills of the 1941 world and its sidecars."""
    for name in (
        "usa",  # entity key
        "moscow",  # a place
        "United States",  # entity name
        "uk_sealift_grt",  # quantity key
        "us_atlantic_fleet",  # feature key
        "bill_through_congress",  # pipeline key
        "state_dept_reports",  # feed key
        "send_bill",  # lever name
        "arm_merchant_ships",  # a bill, from a lever's choices
        "greer_incident",  # a history item
        "Lend-Lease",  # a topic's name
        "dev_duquesne_trial",  # the developments sidecar
    ):
        assert name in names, name


def test_no_rule_names_a_world_key_outside_the_list(
    files: dict[str, str], names: set[str], allow: dict[tuple[str, str], str]
) -> None:
    """A new literal fails; so does a list line for a literal that has left its file."""
    found = _found(files, names)
    new = unlisted(found, allow)
    assert not new, f"{len(new)} world names spelled in rule code, not on the list: {new[:12]}"


def test_the_list_only_shrinks(
    files: dict[str, str], names: set[str], allow: dict[tuple[str, str], str]
) -> None:
    gone = stale(_found(files, names), allow)
    assert not gone, f"{len(gone)} list lines name a literal no longer in the file: {gone[:12]}"


def test_the_list_files_exist_and_are_sorted(allow: dict[tuple[str, str], str]) -> None:
    for path, _ in allow:
        assert (ROOT / path).is_file(), path
        assert path.startswith(SCANNED), path
    assert list(allow) == sorted(allow)


def test_an_exempt_file_still_holds_such_a_literal(files: dict[str, str], names: set[str]) -> None:
    held = {p for p, _ in ties(files, names)}
    for path in NOT_RULES:
        assert path in held, f"{path} holds no world name any more; drop it from NOT_RULES"


def test_an_added_literal_is_caught(files: dict[str, str], names: set[str]) -> None:
    """One literal added to a rule module shows up as a tie the list does not cover."""
    path = "src/revisionist/core/realism/kinds.py"
    changed = {**files, path: files[path] + '\n_TIE = "moscow"\n'}
    allow = read_allow(ALLOW.read_text())
    assert unlisted(_found(changed, names), allow) == [(path, "moscow")]


def test_the_territory_path_compares_no_kind_or_resource_key(files: dict[str, str]) -> None:
    on_path = territory_path(files)
    assert "src/revisionist/core/realism/territory.py" in on_path
    assert "src/revisionist/core/realism/resolvers/movement.py" in on_path
    bad = [(p, line, why) for p in on_path for line, why in key_literal_uses(files[p])]
    assert not bad, f"territory-path modules naming a kind or resource: {bad}"


# ================================================================ the checks, on small cases


def test_a_docstring_is_not_a_literal() -> None:
    src = '"""moscow."""\nX = 1\n"""moscow again"""\ndef f():\n    """moscow"""\n    return "usa"\n'
    assert rule_literals(src) == {"usa": [6]}


def test_a_literal_in_a_dict_key_a_call_and_an_fstring_part_counts() -> None:
    src = 'a = {"usa": 1}\nb = f("uk")\nc = f"x{a}usa"\n'
    assert set(rule_literals(src)) == {"usa", "uk", "x"}


def test_the_list_covers_one_literal_in_one_file_only() -> None:
    """A line for one literal in one file covers no other literal in it, nor that literal
    in another file."""
    allow = {("a.py", "usa"): "stored games only"}
    assert unlisted({("a.py", "usa")}, allow) == []
    assert unlisted({("a.py", "uk")}, allow) == [("a.py", "uk")]
    assert unlisted({("b.py", "usa")}, allow) == [("b.py", "usa")]


def test_a_line_for_a_literal_that_left_the_file_is_stale() -> None:
    allow = {("a.py", "usa"): "until GVR", ("a.py", "uk"): "until GVR"}
    assert stale({("a.py", "usa")}, allow) == [("a.py", "uk")]
    assert stale({("a.py", "usa"), ("a.py", "uk")}, allow) == []


def test_the_list_reads_two_reasons_and_nothing_else() -> None:
    ok = "a.py | usa | stored games only\n# note\n\nb.py | Alfred Jodl | until GVR\n"
    assert read_allow(ok) == {
        ("a.py", "usa"): "stored games only",
        ("b.py", "Alfred Jodl"): "until GVR",
    }
    for bad in (
        "a.py | usa | because\n",
        "a.py | usa | until gvr\n",
        "a.py | usa | until GVRX\n",
        "a.py | usa\n",
        "a.py | usa | stored games only\na.py | usa | until GVR\n",
    ):
        with pytest.raises(ValueError):
            read_allow(bad)


def test_the_territory_path_check_names_each_comparison() -> None:
    bad = [
        'if feature.piece == "army":\n    pass\n',
        'if piece_key in ("army", "fleet"):\n    pass\n',
        'if y.resource != "oil":\n    pass\n',
        'if "oil" == resource_key:\n    pass\n',
        'if piece_kind.key == "army":\n    pass\n',
        'match feature.piece:\n    case "army" | "fleet":\n        pass\n',
        'k = state.kinds.pieces["army"]\n',
        'r = state.kinds.resources.get("oil")\n',
    ]
    for src in bad:
        assert key_literal_uses(src), src
    fine = [
        'if kind.domain == "land":\n    pass\n',
        'if domain in ("sea", "air"):\n    pass\n',
        "if feature.piece == other.piece:\n    pass\n",
        'if resource.role is Role.FUEL or label == "x":\n    pass\n',
        'msg = "oil"\n',
    ]
    for src in fine:
        assert key_literal_uses(src) == [], src


def test_the_territory_path_follows_imports() -> None:
    files = {
        "src/revisionist/core/realism/territory.py": "X = 1\n",
        "src/revisionist/core/realism/kinds.py": "X = 1\n",
        "src/revisionist/core/realism/a.py": "from revisionist.core.realism import territory\n",
        "src/revisionist/core/realism/b.py": "from revisionist.core.realism.kinds import domain\n",
        "src/revisionist/core/realism/c.py": "import revisionist.core.realism.territory as t\n",
        "src/revisionist/core/realism/d.py": "from revisionist.core import events\n",
    }
    assert [Path(p).name for p in territory_path(files)] == [
        "a.py",
        "b.py",
        "c.py",
        "kinds.py",
        "territory.py",
    ]
