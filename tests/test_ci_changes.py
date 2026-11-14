"""The CI change-set decision and the final ``gates`` check."""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_changes.py"


def changes() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_changes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("paths", "python"),
    [
        (["web/js/realism-room.js", "web/css/room.css", "web/test/p5-room.test.js"], False),
        (["docs/game-spec.md", "README.md", "CONTRIBUTING.md", "web/README.md"], False),
        (["web/js/realism-room.js", "src/revisionist/engine/web/server.py"], True),
        (["src/revisionist/core/state.py", "tests/test_state.py"], True),
        (["web/js/realism-room.js", "web/test/fixtures/realism-seat.json"], True),
        (["web/assets/portraits/roosevelt.jpg"], True),
        (["web/assets/portraits/SOURCES.md"], True),
        (["docs/deploy.md", "deploy/revisionist.service"], True),
        (["worlds/salt-strait.yaml"], True),
        ([".github/workflows/ci.yml"], True),
        (["pyproject.toml"], True),
        (["uv.lock"], True),
        (["scripts/ci_changes.py"], True),
        (["tests/README.md"], True),
        (["schema/revisionist.schema.json"], True),
        ([], True),
        (["", "  "], True),
    ],
    ids=[
        "client-only",
        "docs-only",
        "mixed",
        "python-only",
        "seat-fixture",
        "portrait",
        "portrait-sources",
        "deploy",
        "world",
        "workflow",
        "pyproject",
        "lockfile",
        "ci-helper",
        "md-under-tests",
        "schema",
        "empty",
        "blank-lines",
    ],
)
def test_needs_python(paths: list[str], python: bool) -> None:
    assert changes().needs_python(paths) is python


def test_decide_prints_a_github_output_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    m = changes()
    for text, want in [("web/js/a.js\ndocs/b.md\n", "python=false"), ("src/x.py\n", "python=true")]:
        listing = tmp_path / "changed.txt"
        listing.write_text(text)
        with listing.open() as fh:
            monkeypatch.setattr("sys.stdin", fh)
            assert m.main(["decide"]) == 0
        assert capsys.readouterr().out == want + "\n"


def web_paths_named_in(path: Path) -> list[str]:
    """Paths spelt as ``"web" / "a" / "b"`` in a Python file."""
    found = re.findall(r'"web"((?:\s*/\s*"[^"]+")+)', path.read_text())
    return ["/".join(["web", *re.findall(r'"([^"]+)"', tail)]) for tail in found]


def test_every_client_path_python_reads_is_kept_out_of_the_skip() -> None:
    sources = [*(ROOT / "tests").rglob("*.py"), *(ROOT / "src").rglob("*.py")]
    sources.remove(Path(__file__).resolve())
    named = sorted({p for f in sources for p in web_paths_named_in(f)})
    assert "web/test/fixtures/realism-seat.json" in named
    m = changes()
    deep = [p for p in named if p.count("/") >= 2]
    assert deep
    for p in deep:
        changed = f"{p}/x" if (ROOT / p).is_dir() else p
        assert not m.skippable(changed), p


GREEN = {"changes": "success", "lint": "success", "node": "success", "pytest": "success"}


@pytest.mark.parametrize(
    ("results", "green"),
    [
        (GREEN | {"python": "true"}, True),
        (GREEN | {"pytest": "skipped", "python": "false"}, True),
        (GREEN | {"pytest": "skipped", "python": "true"}, False),
        (GREEN | {"pytest": "skipped", "python": ""}, False),
        (GREEN | {"pytest": "failure", "python": "true"}, False),
        (GREEN | {"pytest": "cancelled", "python": "true"}, False),
        (GREEN | {"lint": "failure", "python": "true"}, False),
        (GREEN | {"node": "failure", "pytest": "skipped", "python": "false"}, False),
        (GREEN | {"changes": "failure", "pytest": "skipped", "python": ""}, False),
        ({"python": "false", "pytest": "skipped"}, False),
    ],
    ids=[
        "all-passed",
        "skipped-on-purpose",
        "skipped-but-python-changed",
        "skipped-with-no-decision",
        "shard-failed",
        "shard-cancelled",
        "lint-failed",
        "node-failed",
        "changes-failed",
        "jobs-missing",
    ],
)
def test_gate(results: dict[str, str], green: bool) -> None:
    assert (changes().gate(results) == []) is green


def test_gate_reads_the_environment_and_fails_with_reasons(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    m = changes()
    for k, v in (GREEN | {"python": "true"}).items():
        monkeypatch.setenv(f"RESULT_{k.upper()}", v)
    assert m.main(["gate"]) == 0
    monkeypatch.setenv("RESULT_PYTEST", "failure")
    assert m.main(["gate"]) == 1
    assert "not green: pytest: failure" in capsys.readouterr().err
    assert m.main(["nonsense"]) == 2
