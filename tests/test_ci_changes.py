"""The CI change-set decision and the final ``gates`` check."""

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_changes.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


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


@pytest.mark.parametrize(
    ("paths", "web"),
    [
        (["web/js/views/realism-board.js"], True),
        (["web/test/e2e/realism_smoke.py", "docs/a.md"], True),
        (["src/revisionist/engine/web/server.py", "web/css/c-shell.css"], True),
        (["src/revisionist/core/state.py", "tests/test_state.py"], True),
        (["worlds/autumn-1941.yaml", "tests/worlds/autumn-1941-points.yaml"], True),
        (["docs/game-spec.md", "README.md"], False),
        ([".github/workflows/ci.yml", "scripts/ci_changes.py"], True),
        (["website/index.html"], True),
        ([], True),
        (["", "  "], True),
    ],
    ids=[
        "client",
        "smoke-script",
        "client-and-server",
        "python-only",
        "world-data-only",
        "docs-only",
        "ci-only",
        "prefix-lookalike",
        "empty",
        "blank-lines",
    ],
)
def test_needs_browser(paths: list[str], web: bool) -> None:
    assert changes().needs_browser(paths) is web


def test_decide_prints_the_github_output_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    m = changes()
    for text, want in [
        ("web/js/a.js\ndocs/b.md\n", "python=false\nweb=true\n"),
        ("src/x.py\n", "python=true\nweb=true\n"),
        ("docs/b.md\n", "python=false\nweb=false\n"),
    ]:
        listing = tmp_path / "changed.txt"
        listing.write_text(text)
        with listing.open() as fh:
            monkeypatch.setattr("sys.stdin", fh)
            assert m.main(["decide"]) == 0
        assert capsys.readouterr().out == want


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


GREEN = {
    "changes": "success",
    "lint": "success",
    "node": "success",
    "pytest": "success",
    "browser": "success",
}


@pytest.mark.parametrize(
    ("results", "green"),
    [
        (GREEN | {"python": "true", "web": "true"}, True),
        (GREEN | {"pytest": "skipped", "python": "false", "web": "true"}, True),
        (GREEN | {"pytest": "skipped", "python": "true", "web": "true"}, False),
        (GREEN | {"pytest": "skipped", "python": "", "web": "true"}, False),
        (GREEN | {"pytest": "failure", "python": "true", "web": "true"}, False),
        (GREEN | {"pytest": "cancelled", "python": "true", "web": "true"}, False),
        (GREEN | {"lint": "failure", "python": "true", "web": "true"}, False),
        (GREEN | {"node": "failure", "pytest": "skipped", "python": "false", "web": "true"}, False),
        (GREEN | {"changes": "failure", "pytest": "skipped", "python": "", "web": ""}, False),
        ({"python": "false", "pytest": "skipped", "web": "false"}, False),
        (GREEN | {"python": "true", "web": "false"}, True),
        (GREEN | {"browser": "skipped", "python": "true", "web": "false"}, True),
        (GREEN | {"browser": "skipped", "python": "true", "web": "true"}, False),
        (GREEN | {"browser": "skipped", "python": "true", "web": ""}, False),
        (GREEN | {"browser": "skipped", "python": "true"}, False),
        (GREEN | {"browser": "failure", "python": "true", "web": "true"}, False),
        (GREEN | {"browser": "failure", "python": "true", "web": "false"}, False),
        (GREEN | {"browser": "cancelled", "python": "true", "web": "true"}, False),
        (GREEN | {"browser": "", "python": "true", "web": "true"}, False),
        (
            {k: v for k, v in GREEN.items() if k != "browser"} | {"python": "true", "web": "true"},
            False,
        ),
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
        "browser-ran-with-no-web-change",
        "browser-skipped-no-web-change",
        "browser-skipped-but-web-changed",
        "browser-skipped-with-no-decision",
        "browser-skipped-decision-missing",
        "browser-failed",
        "browser-failed-no-web-change",
        "browser-cancelled",
        "browser-blank",
        "browser-missing",
    ],
)
def test_gate(results: dict[str, str], green: bool) -> None:
    assert (changes().gate(results) == []) is green


def test_gate_reads_the_environment_and_fails_with_reasons(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    m = changes()
    for k, v in (GREEN | {"python": "true", "web": "true"}).items():
        monkeypatch.setenv(f"RESULT_{k.upper()}", v)
    assert m.main(["gate"]) == 0
    monkeypatch.setenv("RESULT_PYTEST", "failure")
    assert m.main(["gate"]) == 1
    assert "not green: pytest: failure" in capsys.readouterr().err
    monkeypatch.setenv("RESULT_PYTEST", "success")
    monkeypatch.setenv("RESULT_BROWSER", "failure")
    assert m.main(["gate"]) == 1
    assert "not green: browser: failure" in capsys.readouterr().err
    monkeypatch.delenv("RESULT_BROWSER")
    assert m.main(["gate"]) == 1
    assert "not green: browser: missing" in capsys.readouterr().err
    monkeypatch.setenv("RESULT_BROWSER", "skipped")
    monkeypatch.setenv("RESULT_WEB", "false")
    assert m.main(["gate"]) == 0
    assert m.main(["nonsense"]) == 2


def jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    return jobs


def steps_text(job: str) -> str:
    return "\n".join(str(step.get("run", "")) for step in jobs()[job]["steps"])


def test_gates_waits_for_the_browser_job_and_reads_its_result() -> None:
    gates = jobs()["gates"]
    assert "browser" in gates["needs"]
    env = {k: v for step in gates["steps"] for k, v in step.get("env", {}).items()}
    assert env["RESULT_BROWSER"] == "${{ needs.browser.result }}"
    assert env["RESULT_WEB"] == "${{ needs.changes.outputs.web }}"


def test_the_changes_job_publishes_the_web_decision() -> None:
    assert jobs()["changes"]["outputs"]["web"] == "${{ steps.decide.outputs.web }}"
    assert "web=true" in steps_text("changes")


def test_the_browser_job_runs_the_canned_server_and_both_smoke_passes() -> None:
    job = jobs()["browser"]
    assert job["needs"] == "changes"
    assert job["if"] == "needs.changes.outputs.web == 'true'"
    assert job["timeout-minutes"] == 15
    assert "postgres" in job["services"]
    text = steps_text("browser")
    assert "web/test/e2e/serve_canned.py" in text
    smokes = [ln for ln in text.splitlines() if "web/test/e2e/realism_smoke.py" in ln]
    assert len(smokes) == 2
    assert sum(ln.rstrip().endswith(" phone") for ln in smokes) == 1
    assert all("playwright==1.49.*" in ln for ln in smokes)
    assert "model" not in text.lower().replace("canned", "")
    uploads = [s for s in job["steps"] if "upload-artifact" in str(s.get("uses", ""))]
    assert uploads
    assert uploads[0]["if"] == "always()"


def test_no_job_env_reads_a_context_the_runner_has_not_made_yet() -> None:
    # `runner` and `steps` exist only inside a step, so a job-level `env` that reads them
    # makes GitHub refuse the whole workflow file.
    for name, job in jobs().items():
        for key, value in job.get("env", {}).items():
            assert "runner." not in str(value), f"{name}.env.{key}"
            assert "steps." not in str(value), f"{name}.env.{key}"
